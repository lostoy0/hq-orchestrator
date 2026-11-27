#!/usr/bin/env python3
"""hq scale-out rules: shard sizing, straggler re-split, delivery marker, layered verification,
batched merges, active monitoring with rate-limited analysis, and threshold calibration.

Every subcommand is a pure function of its input (JSON on stdin or flags) and prints JSON.
The rules are documented in references/scale-out.md; this script is the executable version so
the main session does not re-derive them by hand.

  scale.py shards     --units N --unit-min X [--overhead-min 8] [--target-min 40] [--limit 20]
                      [--reserve-ratio 0.2] [--max-overhead-ratio 0.3] [--units-file F]
  scale.py straggler  [--target-min 40] [--overhead-min 8] [--free-slots K] [--now ISO]  < shards.json
  scale.py progress   [--file F]            < text   (last "HQ-PROGRESS done=.. total=.." line)
  scale.py delivered  [--done-file F]       < commit body / final message
  scale.py test-scope --changed F... [--foundation GLOB...] [--require-full]
  scale.py full-gate  [--since-shards N] [--since-lines L] [--since-files F] [--batch-complete]
                      [--before-push] [--ci-checkpoint] [--every-shards 4] [--every-lines 1500] [--every-files 60]
  scale.py merge-group                      < {"delivered":[..],"pending":[..],"owners":{..}}
  scale.py locate                           < {"group":[{"id","files"}],"failures":[paths]}
  scale.py monitor    --state F [--config F] [--now ISO]   < snapshot.json
  scale.py label                                           < {"records":[..],"outcomes":{..}}
  scale.py calibrate  [--playbook F --write]               < {"current":..,"history":[..],"ratios":{..}}
  scale.py thresholds --playbook F [--rollback]
"""
import argparse
import json
import math
import os
import re
import statistics
import sys
from datetime import datetime, timedelta, timezone


def out(obj, code=0):
    sys.stdout.write(json.dumps(obj, ensure_ascii=False, indent=2) + "\n")
    return code


def die(msg, code=2):
    print("scale.py: " + msg, file=sys.stderr)
    sys.exit(code)


def read_text(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def write_text(path, text):
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


def read_json_stdin():
    try:
        return json.load(sys.stdin)
    except ValueError as e:
        die("stdin is not valid JSON: %s" % e)


def num(x):
    if isinstance(x, bool) or not isinstance(x, (int, float)):
        return None
    return x if math.isfinite(x) else None


def parse_ts(s):
    if not isinstance(s, str) or not s.strip():
        return None
    try:
        d = datetime.fromisoformat(s.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def now_or(s):
    d = parse_ts(s) if s else None
    return d or datetime.now(timezone.utc)


def minutes(a, b):
    return (b - a).total_seconds() / 60.0


def r1(x):
    return None if x is None else round(x, 1)


# =====================================================================================
# 1. shard count: by workload, not by module count
# =====================================================================================

def shard_plan(units, unit_min, overhead_min=8.0, target_min=40.0, limit=20,
               reserve_ratio=0.2, max_overhead_ratio=0.3):
    """n = min(usable slots, ceil(work / target), units), then fewer shards while fixed overhead
    exceeds max_overhead_ratio of a shard's duration. usable = limit - floor(limit*reserve_ratio):
    slots kept free for straggler re-splits, the shared-file fix session and prerequisite work."""
    if units <= 0 or unit_min <= 0:
        die("--units and --unit-min must be > 0")
    limit = max(1, int(limit))
    reserve = int(math.floor(limit * max(0.0, reserve_ratio)))
    usable = max(1, limit - reserve)
    work = units * unit_min
    by_target = max(1, int(math.ceil(work / target_min)))
    n = max(1, min(usable, by_target, int(units)))
    why = []
    if by_target > usable:
        why.append("concurrency: ceil(%.0f/%.0f)=%d > usable slots %d (limit %d, reserve %d)"
                   % (work, target_min, by_target, usable, limit, reserve))
    else:
        why.append("workload: ceil(%.0f min / %.0f min target) = %d" % (work, target_min, by_target))
    if n == units and units < min(usable, by_target):
        why.append("capped by unit count %d" % units)

    def shard_len(k):
        return work / k + overhead_min

    reduced = False
    while n > 1 and overhead_min / shard_len(n) > max_overhead_ratio:
        n -= 1
        reduced = True
    if reduced:
        why.append("fewer shards: overhead %.0f min would exceed %.0f%% of a shard"
                   % (overhead_min, max_overhead_ratio * 100))
    per = shard_len(n)
    return {
        "shards": n, "total_work_min": r1(work), "units": units,
        "units_per_shard": r1(units / n), "shard_min": r1(per),
        "overhead_ratio": round(overhead_min / per, 3),
        "batch_eta_min": r1(per), "serial_min": r1(work + overhead_min),
        "usable_slots": usable, "reserved_slots": reserve,
        "over_target": per > target_min * 1.25,
        "why": "; ".join(why),
    }


def split_units(items, n):
    """Contiguous, weight-balanced split of an ordered unit list into n shards (keeps neighbours
    together for locality, ignores module boundaries). items: [(name, weight)]."""
    total = sum(w for _, w in items) or 1.0
    shards = [[] for _ in range(n)]
    acc = 0.0
    for name, w in items:
        mid = acc + w / 2.0
        i = min(n - 1, int(mid / total * n))
        shards[i].append(name)
        acc += w
    return [s for s in shards if s]


def read_units_file(path):
    items = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            name, _, w = line.partition("\t")
            try:
                weight = float(w) if w.strip() else 1.0
            except ValueError:
                weight = 1.0
            items.append((name, weight))
    return items


def cmd_shards(a):
    units = a.units
    items = None
    if a.units_file:
        items = read_units_file(a.units_file)
        units = units or len(items)
    if not units:
        die("give --units or --units-file")
    plan = shard_plan(units, a.unit_min, a.overhead_min, a.target_min, a.limit,
                      a.reserve_ratio, a.max_overhead_ratio)
    if items:
        parts = split_units(items, plan["shards"])
        plan["shards"] = len(parts)
        plan["assignment"] = parts
    return out(plan)


# =====================================================================================
# 4. progress rate, ETA and straggler re-split
# =====================================================================================

PROGRESS_RE = re.compile(r"HQ-PROGRESS\b([^\n]*)")
KV_RE = re.compile(r"(\w+)=([^\s]+)")


def parse_progress(text):
    """Last 'HQ-PROGRESS done=37 total=150 rework=1 failed=0' line, or a JSON progress file."""
    s = text.strip()
    if s.startswith("{"):
        try:
            d = json.loads(s)
            return {k: d.get(k) for k in ("done", "total", "rework", "failed", "updated_at") if k in d} or None
        except ValueError:
            pass
    m = None
    for m in PROGRESS_RE.finditer(text):
        pass
    if not m:
        return None
    o = {}
    for k, v in KV_RE.findall(m.group(1)):
        try:
            o[k] = int(v)
        except ValueError:
            try:
                o[k] = float(v)
            except ValueError:
                o[k] = v
    return o


def cmd_progress(a):
    text = read_text(a.file) if a.file else sys.stdin.read()
    p = parse_progress(text)
    return out({"progress": p}, 0 if p else 1)


def straggler_check(s, target_min=40.0, overhead_min=8.0, free_slots=0, now=None):
    """Decide whether to split the rest of one shard into new sessions.

    Straggler: projected total > 2 x planned shard length. Re-split only if the remainder is still
    worth it (> 2 x target): a shard close to done is left alone because a new session's start-up
    overhead would eat the gain."""
    est = num(s.get("est_min")) or target_min
    elapsed = num(s.get("elapsed_min"))
    if elapsed is None:
        st = parse_ts(s.get("started_at") or s.get("created_at"))
        elapsed = minutes(st, now) if st and now else None
    done, total = num(s.get("done")), num(s.get("total"))
    res = {"id": s.get("id"), "elapsed_min": r1(elapsed), "est_min": est, "done": done, "total": total}
    if elapsed is None or not total:
        return dict(res, action="none", reason="no_progress_data")
    work_min = max(0.0, elapsed - overhead_min)
    remaining_units = max(0, total - (done or 0))
    if remaining_units == 0:
        return dict(res, action="none", reason="complete", remaining_min=0)
    if not done or work_min <= 0:
        return dict(res, action="none", reason="no_rate_yet")
    rate = done / work_min  # units per minute
    remaining_min = remaining_units / rate
    projected = elapsed + remaining_min
    res.update(rate_per_min=round(rate, 3), remaining_units=remaining_units,
               remaining_min=r1(remaining_min), projected_total_min=r1(projected),
               projected_ratio=round(projected / est, 2))
    if projected <= 2 * est:
        return dict(res, action="none", reason="on_track")
    if remaining_min <= 2 * target_min:
        return dict(res, action="none", reason="near_done")
    if free_slots <= 0:
        return dict(res, action="report", reason="straggler_no_free_slot")
    k = min(int(free_slots), max(1, int(math.ceil(remaining_min / target_min)) - 1))
    # the original shard keeps one share; each new session pays the start-up overhead
    new_eta = overhead_min + remaining_min / (k + 1)
    if new_eta >= remaining_min:
        return dict(res, action="none", reason="no_gain")
    return dict(res, action="resplit", reason="straggler", new_sessions=k,
                eta_after_min=r1(new_eta), saves_min=r1(remaining_min - new_eta),
                extra_overhead_min=r1(k * overhead_min),
                split=[int(round(remaining_units * i / (k + 1))) for i in range(k + 2)])


def cmd_straggler(a):
    data = read_json_stdin()
    shards = data.get("shards", data) if isinstance(data, dict) else data
    now = now_or(a.now)
    free = a.free_slots
    res = []
    for s in shards:
        r = straggler_check(s, a.target_min, a.overhead_min, free, now)
        if r["action"] == "resplit":
            free -= r["new_sessions"]
        res.append(r)
    return out({"shards": res, "free_slots_left": free})


# =====================================================================================
# 9. delivery marker: a real "交付" section with a verification result, not the word anywhere
# =====================================================================================

HEAD_RE = re.compile(r"^(#{1,6})\s*(交付|delivery)\s*[:：]?\s*$", re.I)
ANY_HEAD_RE = re.compile(r"^(#{1,6})\s+\S")
EMPTY_VERIFY = re.compile(r"^(none|n/?a|无|待补|待补记|tbd|todo|-|…|\.\.\.)?$", re.I)


def check_delivery(text):
    lines = text.splitlines()
    for i, line in enumerate(lines):
        m = HEAD_RE.match(line.strip())
        if not m:
            continue
        level = len(m.group(1))
        body = []
        for l in lines[i + 1:]:
            h = ANY_HEAD_RE.match(l.strip())
            if h and len(h.group(1)) <= level:
                break
            body.append(l.strip())
        status = next((l.split(":", 1)[1].strip() for l in body if l.upper().startswith("STATUS:")), None)
        verify = next((l.split(":", 1)[1].strip() for l in body if l.upper().startswith("VERIFY:")), None)
        if status is None or status.split()[0].upper() != "DONE":
            return {"delivered": False, "reason": "section_status_not_done", "status": status}
        if verify is None or EMPTY_VERIFY.match(verify):
            return {"delivered": False, "reason": "section_without_verify", "status": status}
        return {"delivered": True, "reason": "section", "status": status, "verify": verify}
    return {"delivered": False, "reason": "no_delivery_section"}


def check_done_file(path):
    try:
        d = json.loads(read_text(path))
    except (OSError, ValueError):
        return {"delivered": False, "reason": "done_file_unreadable"}
    if not isinstance(d, dict) or str(d.get("status", "")).upper() != "DONE":
        return {"delivered": False, "reason": "done_file_status_not_done"}
    v = d.get("verify")
    if not v or (isinstance(v, str) and EMPTY_VERIFY.match(v.strip())):
        return {"delivered": False, "reason": "done_file_without_verify"}
    return {"delivered": True, "reason": "done_file", "status": "DONE", "verify": v}


def cmd_delivered(a):
    r = check_done_file(a.done_file) if a.done_file else check_delivery(sys.stdin.read())
    return out(r, 0 if r["delivered"] else 1)


# =====================================================================================
# 6. layered verification: related tests in workers, full suite at hq checkpoints only
# =====================================================================================

DEFAULT_FOUNDATION = [
    "package.json", "**/package.json", "pnpm-lock.yaml", "yarn.lock", "package-lock.json",
    "pnpm-workspace.yaml", "tsconfig*.json", "**/tsconfig*.json",
    "**/vite.config.*", "**/vitest.config.*", "**/vitest.workspace.*", "**/jest.config.*",
    "**/webpack.config.*", "**/babel.config.*", "**/.eslintrc*", "**/eslint.config.*",
    "**/setupTests.*", "**/test/setup*", "**/test-utils/**", "**/testing/**", "**/__mocks__/**",
    "pyproject.toml", "setup.cfg", "conftest.py", "**/conftest.py", "go.mod", "Cargo.toml",
    "Makefile", ".github/workflows/**",
]


def glob_re(g):
    """Glob with ** (any depth), * (no slash), ? ; anchored at the path start."""
    i, rx = 0, ""
    while i < len(g):
        c = g[i]
        if g.startswith("**/", i):
            rx += "(?:.*/)?"
            i += 3
            continue
        if g.startswith("**", i):
            rx += ".*"
            i += 2
            continue
        rx += {"*": "[^/]*", "?": "[^/]"}.get(c, re.escape(c))
        i += 1
    return re.compile("^" + rx + "$")


def match_any(path, globs):
    p = path.lstrip("./")
    return next((g for g in globs if glob_re(g).match(p)), None)


def test_scope(changed, foundation=None, require_full=False):
    globs = list(foundation or []) + DEFAULT_FOUNDATION
    hits = [{"file": f, "glob": match_any(f, globs)} for f in changed if match_any(f, globs)]
    if require_full:
        return {"scope": "full", "reason": "project_rule", "foundation_hits": hits}
    if hits:
        return {"scope": "full", "reason": "shared_foundation", "foundation_hits": hits}
    return {"scope": "related", "reason": "no_shared_foundation", "foundation_hits": []}


def cmd_test_scope(a):
    return out(test_scope(a.changed or [], a.foundation, a.require_full))


def full_gate(since_shards=0, since_lines=0, since_files=0, batch_complete=False, before_push=False,
              ci_checkpoint=False, every_shards=4, every_lines=1500, every_files=60):
    reasons = []
    if batch_complete:
        reasons.append("batch_complete")
    if before_push:
        reasons.append("before_push")
    if ci_checkpoint:
        reasons.append("ci_checkpoint")
    if every_shards and since_shards >= every_shards:
        reasons.append("shards>=%d" % every_shards)
    if every_lines and since_lines >= every_lines:
        reasons.append("lines>=%d" % every_lines)
    if every_files and since_files >= every_files:
        reasons.append("files>=%d" % every_files)
    return {"run_full": bool(reasons), "reasons": reasons}


def cmd_full_gate(a):
    return out(full_gate(a.since_shards, a.since_lines, a.since_files, a.batch_complete, a.before_push,
                         a.ci_checkpoint, a.every_shards, a.every_lines, a.every_files))


# =====================================================================================
# 7. batched merge: everything delivered this check-in merges and verifies as one group
# =====================================================================================

def merge_group(delivered, pending=(), owners=None, wait_max_min=10):
    owners = owners or {}
    pending_ids = {p.get("id") for p in pending}
    ids = [d.get("id") for d in delivered]
    by_id = {d.get("id"): d for d in delivered}
    group, deferred, claimed = [], [], {}
    # topological order among delivered shards; deps on undelivered work defer the shard
    order, seen = [], set()

    def visit(i, stack=()):
        if i in seen or i not in by_id or i in stack:
            return
        for dep in by_id[i].get("depends_on") or []:
            visit(dep, stack + (i,))
        seen.add(i)
        order.append(i)

    for i in ids:
        visit(i)
    in_group = set()
    for i in order:
        d = by_id[i]
        deps = d.get("depends_on") or []
        bad_dep = next((x for x in deps if x in pending_ids or (x in by_id and x not in in_group)), None)
        if bad_dep:
            deferred.append({"id": i, "reason": "depends_on:%s" % bad_dep})
            continue
        files = d.get("files") or []
        foreign = [f for f in files if f in owners and owners[f] != i]
        if foreign:
            deferred.append({"id": i, "reason": "touches_owned_file", "files": foreign,
                             "owners": {f: owners[f] for f in foreign}})
            continue
        clash = [f for f in files if f in claimed]
        if clash:
            deferred.append({"id": i, "reason": "overlap", "files": clash,
                             "with": sorted({claimed[f] for f in clash})})
            continue
        for f in files:
            claimed[f] = i
        group.append(i)
        in_group.add(i)
    soon = [p for p in pending if num(p.get("eta_min")) is not None and p["eta_min"] <= wait_max_min]
    wait = max((p["eta_min"] for p in soon), default=0)
    return {
        "group": group, "deferred": deferred,
        "verify_files": sorted(claimed),
        "wait_min": r1(wait) if group or soon else 0,
        "wait_for": [p.get("id") for p in soon],
        "note": "merge in this order, then verify once over the union of files",
    }


def cmd_merge_group(a):
    d = read_json_stdin()
    return out(merge_group(d.get("delivered") or [], d.get("pending") or [], d.get("owners") or {},
                           num(d.get("wait_max_min")) if num(d.get("wait_max_min")) is not None else a.wait_max_min))


def _dir_overlap(a, b):
    pa, pb = a.split("/")[:-1], b.split("/")[:-1]
    n = 0
    for x, y in zip(pa, pb):
        if x != y:
            break
        n += 1
    return n


def _stem(p):
    base = p.rsplit("/", 1)[-1]
    base = re.sub(r"\.(test|spec)(?=\.)", "", base)
    return base.split(".", 1)[0]


def locate(group, failures):
    """Map failing files/tests to the shard(s) whose changes most plausibly caused them:
    exact file > same file stem (foo.ts <-> foo.test.ts) > deepest shared directory."""
    blame, unresolved = {}, []
    for fpath in failures:
        best, score = [], 0
        for g in group:
            s = 0
            for c in g.get("files") or []:
                if c == fpath:
                    s = max(s, 1000)
                elif _stem(c) == _stem(fpath) and _dir_overlap(c, fpath) >= 1:
                    s = max(s, 500 + _dir_overlap(c, fpath))
                else:
                    s = max(s, _dir_overlap(c, fpath))
            if s > score:
                best, score = [g["id"]], s
            elif s == score and s > 0:
                best.append(g["id"])
        if score == 0 or len(best) > 1 and score < 500:
            unresolved.append({"failure": fpath, "candidates": best})
        else:
            for b in best:
                blame.setdefault(b, []).append(fpath)
    culprits = sorted(blame)
    ids = [g["id"] for g in group]
    res = {"culprits": culprits, "evidence": blame,
           "clean": [i for i in ids if i not in culprits], "unresolved": unresolved}
    if unresolved:
        rest = [i for i in ids if i not in culprits]
        half = rest[: (len(rest) + 1) // 2]
        res["next"] = {"action": "bisect", "revert_and_retest": half}
    else:
        res["next"] = {"action": "fix_or_revert_culprits", "merge_others": res["clean"]}
    return res


def cmd_locate(a):
    d = read_json_stdin()
    return out(locate(d.get("group") or [], d.get("failures") or []))


# =====================================================================================
# 8. active monitoring: thresholds, two-level response, rate-limited analysis
# =====================================================================================

DEFAULT_THRESHOLDS = {
    "duration_ratio": 2.0,     # elapsed / estimate
    "idle_min": 40.0,          # minutes since the last assistant event, progress unchanged
    "cost_ratio": 1.0,         # cost / per-shard budget
    "rework": 2,               # rework rounds
    "failure_rate": 0.2,       # batch: failed / finished
    "straggler_ratio": 2.0,    # batch: longest / median shard duration
    # split health (batch level, computed here from progress; each fires at most once per batch)
    "split_unit_error": 0.5,   # |measured unit time / planned - 1|, median over shards >= 10% done
    "split_uneven": 2.0,       # latest projected finish / median projected finish
    "split_underused": 0.5,    # running shards / shards the remaining work could use (lower is worse)
    "split_boundary": 2,       # shards with boundary signals (overlap, files outside owns, shared fixes)
}
SEVERE = {"cost_ratio": 2.0, "failure_rate": 0.5, "duration_ratio": 4.0, "split_unit_error": 1.5}
BOUNDS = {
    "duration_ratio": (1.3, 4.0), "idle_min": (15.0, 120.0), "cost_ratio": (1.0, 3.0),
    "rework": (1, 5), "failure_rate": (0.1, 0.5), "straggler_ratio": (1.5, 4.0),
    "split_unit_error": (0.3, 1.0), "split_uneven": (1.5, 4.0), "split_underused": (0.25, 0.8),
    "split_boundary": (1, 5),
}
INTEGER = {"rework", "split_boundary"}
LOWER_IS_WORSE = {"split_underused"}
SPLIT_METRICS = ("split_unit_error", "split_uneven", "split_underused", "split_boundary")
LEVEL1 = {
    "idle_min": "message_reminder", "duration_ratio": "straggler_check", "straggler_ratio": "straggler_check",
    "failure_rate": "locate_failing_shard", "cost_ratio": "pause_and_ask_user", "rework": "message_review_brief",
    "split_unit_error": "replan_remaining", "split_uneven": "replan_remaining",
    "split_underused": "replan_remaining", "split_boundary": "review_boundaries",
}
DEFAULT_CAUSE = {
    "idle_min": "no_progress", "duration_ratio": "underestimated", "straggler_ratio": "uneven_split",
    "failure_rate": "verify_failures", "cost_ratio": "over_budget", "rework": "repeated_fixes",
    "split_unit_error": "unit_time", "split_uneven": "uneven", "split_underused": "underused",
    "split_boundary": "boundary",
}
EARLY_PROGRESS = 0.1  # a shard's rate counts once it has finished 10% of its units
DEFAULT_LIMITS = {"cooldown_min": 120, "per_batch": 1, "per_day": 3, "analysis_budget_usd": 0.5,
                  "consecutive": 2}


def thresholds_for(cfg, task_type):
    t = dict(DEFAULT_THRESHOLDS)
    th = (cfg or {}).get("thresholds") or {}
    for scope in ("*", task_type):
        if isinstance(th.get(scope), dict):
            t.update({k: v for k, v in th[scope].items() if num(v) is not None})
    # flat {metric: value} at the top level counts as "*"
    t.update({k: v for k, v in th.items() if k in DEFAULT_THRESHOLDS and num(v) is not None})
    return t


def shard_metrics(s, now, prev):
    m = {}
    est = num(s.get("est_min"))
    elapsed = num(s.get("elapsed_min"))
    if elapsed is None:
        st = parse_ts(s.get("created_at") or s.get("started_at"))
        elapsed = minutes(st, now) if st else None
    if elapsed is not None and est:
        m["duration_ratio"] = round(elapsed / est, 2)
    # idle: from the event stream's latest event; the session list's updated_at can lag for hours
    last = parse_ts(s.get("last_event_at"))
    done = s.get("done")
    unchanged = prev is None or prev.get("done") == done
    if last is not None and unchanged:
        m["idle_min"] = round(minutes(last, now), 1)
    cost, budget = num(s.get("cost_usd")), num(s.get("budget_usd"))
    if cost is not None and budget:
        m["cost_ratio"] = round(cost / budget, 2)
    if num(s.get("rework")) is not None:
        m["rework"] = s["rework"]
    return m


def split_health(snap, now):
    """Batch-level checks of whether the split itself was sound, from data already in the snapshot.
    Returns ({metric: value}, {metric: detail}). Needs at least 2 shards (3 for the unit-time check)."""
    shards = snap.get("shards") or []
    target = num(snap.get("target_min")) or 40.0
    overhead = num(snap.get("overhead_min"))
    overhead = 8.0 if overhead is None else overhead
    limit = num(snap.get("concurrency_limit"))
    vals, detail = {}, {}
    if len(shards) < 2:
        return vals, detail
    errs, unit_meas, projected, running, rem_units, rem_min = [], [], [], 0, 0, 0.0
    for s in shards:
        ov = num(s.get("overhead_min"))
        ov = overhead if ov is None else ov
        elapsed = num(s.get("elapsed_min"))
        if elapsed is None:
            t = parse_ts(s.get("created_at") or s.get("started_at"))
            elapsed = minutes(t, now) if t else None
        done, total = num(s.get("done")), num(s.get("total"))
        if s.get("delivered"):
            if elapsed is not None:
                projected.append(elapsed)
            continue
        running += 1
        if elapsed is None or not total or not done or elapsed <= ov:
            continue
        um = (elapsed - ov) / done  # measured minutes per unit
        unit_meas.append(um)
        left = max(0, total - done)
        rem_units += left
        rem_min += left * um
        projected.append(elapsed + left * um)
        est = num(s.get("unit_min_est"))
        if est and done / total >= EARLY_PROGRESS:
            errs.append(um / est - 1)
    # 1. unit time estimate: the whole plan is off when most shards disagree with it the same way
    if len(errs) >= 3:
        e = statistics.median(errs)
        same_sign = sum(1 for x in errs if (x > 0) == (e > 0)) / len(errs)
        if same_sign >= 0.75:
            vals["split_unit_error"] = round(abs(e), 2)
            detail["split_unit_error"] = {"median_error": round(e, 2), "shards": len(errs),
                                          "measured_unit_min": round(statistics.median(unit_meas), 3)}
    # 2. uneven split: spread of projected finish times, before shards actually finish
    if len(projected) >= 3:
        m = statistics.median(projected)
        if m > 0:
            vals["split_uneven"] = round(max(projected) / m, 2)
            detail["split_uneven"] = {"latest_min": r1(max(projected)), "median_min": r1(m)}
    # 3. under-used slots: the remaining work could keep more sessions busy than are running
    if limit and running and rem_min > 2 * target:
        usable = max(1, int(limit) - int(math.floor(limit * 0.2)))
        could = min(usable, int(math.ceil(rem_min / target)), int(rem_units) or 1)
        if could > running:
            vals["split_underused"] = round(running / could, 2)
            detail["split_underused"] = {"running": running, "could_use": could, "remaining_min": r1(rem_min)}
    # 4. boundary signals: overlap deferrals, files outside owns, SHARED_FIXES entries
    hit = []
    for s in shards:
        b = s.get("boundary") or {}
        if b.get("overlap") or b.get("out_of_owns") or cnt_(b.get("shared_fixes")):
            hit.append(s.get("id"))
    if hit:
        vals["split_boundary"] = len(hit)
        detail["split_boundary"] = {"shards": hit}
    # a re-plan proposal for the remaining work (same rule as `shards`)
    if rem_units and unit_meas:
        plan = shard_plan(rem_units, statistics.median(unit_meas), overhead, target, int(limit or running or 1))
        detail["replan"] = {"remaining_units": int(rem_units), "measured_unit_min": round(statistics.median(unit_meas), 3),
                            "shards_for_remaining": plan["shards"], "running": running,
                            "new_sessions": max(0, plan["shards"] - running), "shard_min": plan["shard_min"],
                            "why": plan["why"]}
    return vals, detail


def cnt_(x):
    v = num(x)
    return v if v is not None else 0


def breached(metric, value, th):
    if metric in LOWER_IS_WORSE:
        return value < th
    return value >= th if metric in INTEGER else value > th


def is_severe(metric, value):
    return metric in SEVERE and value >= SEVERE[metric]


def monitor_step(state, snap, cfg=None, now=None):
    """One check-in. Returns (new_state, result). State is a plain JSON dict the caller persists."""
    cfg = cfg or {}
    now = now or datetime.now(timezone.utc)
    lim = dict(DEFAULT_LIMITS, **(cfg.get("limits") or {}))
    st = {"streak": {}, "last": {}, "seen": {}, "analyzed": {}, "pending": {}, "batch_analyses": {},
          "day_analyses": {}, "split_fired": {}}
    st.update(state or {})
    batch = snap.get("batch_id") or "batch"
    run_id = snap.get("run_id")
    day = now.strftime("%Y-%m-%d")
    ts = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    obs = []  # (subject, task_type, metric, value, threshold, cause)
    for s in snap.get("shards") or []:
        sid = s.get("id")
        if s.get("delivered"):
            st["last"].pop(sid, None)
            continue
        tt = s.get("task_type") or s.get("kind") or "*"
        th = thresholds_for(cfg, tt)
        m = shard_metrics(s, now, st["last"].get(sid))
        st["last"][sid] = {"done": s.get("done")}
        for k, v in m.items():
            obs.append((sid, tt, k, v, th[k], (s.get("cause") or {}).get(k) if isinstance(s.get("cause"), dict) else None))
    b = snap.get("batch") or {}
    th_b = thresholds_for(cfg, snap.get("task_type") or "*")
    for k in ("failure_rate", "straggler_ratio"):
        if num(b.get(k)) is not None:
            obs.append(("batch", snap.get("task_type") or "*", k, b[k], th_b[k], None))
    split_vals, split_detail = split_health(snap, now)
    fired = st["split_fired"].setdefault(batch, [])
    for k, v in split_vals.items():
        if k not in fired:  # each split check acts at most once per batch: no repeated re-planning
            obs.append(("batch", snap.get("task_type") or "*", k, v, th_b[k], None))

    actions, records, triggered = [], [], []
    for subj, tt, metric, value, th, cause in obs:
        key_s = "%s|%s" % (subj, metric)
        if not breached(metric, value, th):
            st["streak"].pop(key_s, None)
            continue
        sev = is_severe(metric, value)
        streak = st["streak"].get(key_s, 0) + 1
        if streak < lim["consecutive"] and not sev:
            st["streak"][key_s] = streak
            continue
        st["streak"].pop(key_s, None)  # re-arm: needs another run of breaches to fire again
        cause = cause or DEFAULT_CAUSE[metric]
        key = ("split:%s" % cause) if metric in SPLIT_METRICS else "%s:%s" % (metric, cause)
        if metric in SPLIT_METRICS:
            fired.append(metric)
        rec = {"type": "monitor", "event": "trigger", "run_id": run_id, "batch_id": batch, "ts": ts,
               "task_id": subj, "task_type": tt, "metric": metric, "value": value, "threshold": th,
               "severity": "severe" if sev else "normal", "level": 1, "action": LEVEL1[metric],
               "key": key, "rate_limited": False, "analysis_cost_usd": None, "label": None}
        act = {"level": 1, "task_id": subj, "metric": metric, "value": value, "threshold": th,
               "action": LEVEL1[metric], "severity": rec["severity"]}
        if metric in SPLIT_METRICS:
            act["detail"] = split_detail.get(metric)
            if LEVEL1[metric] == "replan_remaining":
                act["replan"] = split_detail.get("replan")
        actions.append(act)
        seen = st["seen"].setdefault(key, {"subjects": [], "batches": []})
        if subj not in seen["subjects"]:
            seen["subjects"].append(subj)
        if batch not in seen["batches"]:
            seen["batches"].append(batch)
        repeated = len(seen["subjects"]) >= 2 or len(seen["batches"]) >= 2
        triggered.append((key, sev, repeated, rec))
        records.append(rec)

    analyses, skipped = [], []

    def limits_ok():
        return (st["batch_analyses"].get(batch, 0) < lim["per_batch"]
                and st["day_analyses"].get(day, 0) < lim["per_day"])

    def in_cooldown(key):
        last = st["analyzed"].get(key)
        if not last:
            return False
        if last.get("batch") == batch:
            return True
        t = parse_ts(last.get("ts"))
        return t is not None and minutes(t, now) < lim["cooldown_min"]

    def start(keys, severity, reason):
        counts = {k: st["pending"].pop(k, {}).get("count", 0) + 1 for k in keys}
        for k in keys:
            st["analyzed"][k] = {"ts": ts, "batch": batch}
        st["batch_analyses"][batch] = st["batch_analyses"].get(batch, 0) + 1
        st["day_analyses"][day] = st["day_analyses"].get(day, 0) + 1
        analyses.append({"level": 2, "keys": keys, "counts": counts, "severity": severity, "reason": reason,
                         "budget_usd": lim["analysis_budget_usd"], "model_hint": "light (T1/T2, low effort)",
                         "after": "this check-in's merge and verification"})

    heavy = bool(snap.get("heavy_ops"))
    for key, sev, repeated, rec in triggered:
        if not (sev or repeated):
            continue  # level 1 only
        rec["level"] = 2
        if in_cooldown(key):
            p = st["pending"].setdefault(key, {"count": 0, "severe": False})
            p["count"] += 1
            rec["rate_limited"], rec["skip_reason"] = True, "cooldown"
            skipped.append({"key": key, "reason": "cooldown"})
            continue
        if not sev:
            p = st["pending"].setdefault(key, {"count": 0, "severe": False})
            p["count"] += 1
            rec["deferred"] = "batch_end"
            continue
        if heavy:
            p = st["pending"].setdefault(key, {"count": 0, "severe": False})
            p["count"] += 1
            p["severe"] = True
            rec["deferred"] = "next_checkin_heavy_ops"
            continue
        if not limits_ok():
            st["pending"].setdefault(key, {"count": 0, "severe": True})["count"] += 1
            rec["rate_limited"], rec["skip_reason"] = True, "global_limit"
            skipped.append({"key": key, "reason": "global_limit"})
            continue
        start([key], "severe", "severe")
    # severe triggers postponed by heavy work run on a later quiet check-in
    if not heavy:
        for key in [k for k, p in st["pending"].items() if p.get("severe")]:
            if not limits_ok():
                break
            if key in st["pending"] and not in_cooldown(key):
                start([key], "severe", "postponed_severe")
    if snap.get("batch_done") and not heavy:
        keys = [k for k in st["pending"] if not in_cooldown(k)]
        if keys:
            if limits_ok():
                start(sorted(keys), "normal", "batch_end_merged")
            else:
                skipped.append({"key": ",".join(sorted(keys)), "reason": "global_limit_to_retro"})
                for k in keys:
                    st["pending"][k]["to_retro"] = True
    return st, {"actions": actions, "analyses": analyses, "rate_limited": skipped, "records": records,
                "pending": st["pending"]}


def load_json_file(path, default):
    if not path or not os.path.exists(path):
        return default
    try:
        return json.loads(read_text(path))
    except ValueError:
        die("%s is not valid JSON" % path)


def cmd_monitor(a):
    snap = read_json_stdin()
    cfg = load_json_file(a.config, {})
    if a.playbook:
        cfg = dict(cfg)
        cfg.setdefault("thresholds", effective_thresholds(a.playbook)["thresholds"])
    state = load_json_file(a.state, {})
    st, res = monitor_step(state, snap, cfg, now_or(a.now))
    if a.state:
        d = os.path.dirname(os.path.abspath(a.state))
        os.makedirs(d, exist_ok=True)
        with open(a.state, "w", encoding="utf-8") as fh:
            json.dump(st, fh, ensure_ascii=False, indent=1)
    return out(res)


# =====================================================================================
# 8.5 threshold calibration
# =====================================================================================

MIN_SAMPLES = 5
FP_MAX = 0.3      # false-positive rate above this -> loosen
MISS_MAX = 0.2    # missed / (effective + missed) above this -> tighten
STEP = 0.2        # at most 20% per calibration


def p90(xs):
    xs = sorted(xs)
    if not xs:
        return None
    k = (len(xs) - 1) * 0.9
    lo, hi = int(math.floor(k)), int(math.ceil(k))
    return xs[lo] + (xs[hi] - xs[lo]) * (k - lo)


def clamp(metric, v):
    lo, hi = BOUNDS[metric]
    v = min(hi, max(lo, v))
    return int(round(v)) if metric in INTEGER else round(v, 2)


def stepped(before, target):
    lo, hi = before * (1 - STEP), before * (1 + STEP)
    return min(hi, max(lo, target))


def counts(history, tt, metric):
    e = fp = miss = 0
    for h in history:
        if h.get("metric") != metric or (tt != "*" and (h.get("task_type") or "*") != tt):
            continue
        lab = h.get("label") or ("missed" if h.get("event") == "missed" else None)
        if lab == "effective":
            e += 1
        elif lab == "false_positive":
            fp += 1
        elif lab == "missed":
            miss += 1
    return e, fp, miss


def calibrate(current, history, ratios=None, user=None, task_types=None):
    """current: {task_type: {metric: value}} (missing -> defaults); user: same shape, never changed.
    history: monitor records with label effective|false_positive, or event "missed".
    ratios: {task_type: [actual/estimate ...]} for the duration threshold (P90)."""
    current = current or {}
    user = user or {}
    ratios = ratios or {}
    types = set(task_types or []) | set(current) | {h.get("task_type") or "*" for h in history} | set(ratios) | {"*"}
    new, changes = {}, []
    for tt in sorted(types):
        new[tt] = {}
        for metric, dflt in DEFAULT_THRESHOLDS.items():
            before = (current.get(tt) or {}).get(metric)
            if num(before) is None:
                before = (current.get("*") or {}).get(metric, dflt) if tt != "*" else dflt
            uv = (user.get(tt) or {}).get(metric)
            if num(uv) is None:
                uv = (user.get("*") or {}).get(metric)
            if num(uv) is not None:
                new[tt][metric] = uv
                continue
            e, fp, miss = counts(history, tt, metric)
            n = e + fp + miss
            rs = [x for x in ratios.get(tt, []) if num(x) is not None]
            source = tt
            if n < MIN_SAMPLES and len(rs) < MIN_SAMPLES and tt != "*":
                # too few samples for this task type: fall back to the global value (or default)
                g = new.get("*", {}).get(metric)
                v = g if g is not None else dflt
                new[tt][metric] = v
                if v != before:
                    changes.append({"task_type": tt, "metric": metric, "before": before, "after": v,
                                    "reason": "samples<%d: use global/default" % MIN_SAMPLES, "n": n})
                continue
            target, reason = before, []
            if n >= MIN_SAMPLES:
                fpr = fp / (e + fp) if e + fp else 0.0
                mr = miss / (e + miss) if e + miss else 0.0
                if fpr > FP_MAX and mr > MISS_MAX:
                    reason.append("fp %.0f%% and misses %.0f%% both high: keep" % (fpr * 100, mr * 100))
                elif fpr > FP_MAX:  # loosen = fire less often
                    target = before * (1 - STEP if metric in LOWER_IS_WORSE else 1 + STEP)
                    reason.append("false positives %.0f%% > %.0f%%: loosen" % (fpr * 100, FP_MAX * 100))
                elif mr > MISS_MAX:
                    target = before * (1 + STEP if metric in LOWER_IS_WORSE else 1 - STEP)
                    reason.append("misses %.0f%% > %.0f%%: tighten" % (mr * 100, MISS_MAX * 100))
            if metric == "duration_ratio" and len(rs) >= MIN_SAMPLES and not reason:
                target = p90(rs)
                reason.append("P90 of actual/estimate = %.2f (n=%d)" % (target, len(rs)))
            after = clamp(metric, stepped(before, target))
            if metric in INTEGER and after == before and target != before:
                # 20% of a small integer rounds to no change: move by the minimum step of 1
                after = clamp(metric, before + (1 if target > before else -1))
            new[tt][metric] = after
            if after != before:
                changes.append({"task_type": tt, "metric": metric, "before": before, "after": after,
                                "reason": "; ".join(reason) or "bounds", "n": n, "source": source,
                                "fp": fp, "effective": e, "missed": miss})
    # drop per-type entries identical to the global ones to keep the stored table small
    g = new.get("*", {})
    compact = {"*": g}
    for tt, m in new.items():
        if tt == "*":
            continue
        d = {k: v for k, v in m.items() if v != g.get(k)}
        if d:
            compact[tt] = d
    return {"thresholds": compact, "changes": changes}


# ---------- rule-based labels: effective / false_positive, and rule-detected misses ----------

# Constants of the labelling rules (references/scale-out.md section 9).
LABEL_SAVING_MIN_SHARE = 0.5   # a re-split / re-plan counts as effective when it saved >= 50% of the estimate
LABEL_ON_TIME_RATIO = 1.2      # "finished normally" = actual <= 1.2 x estimate (or cost <= 1.2 x budget)
LABEL_IDLE_WINDOW = 2          # progress must rise within this many check-ins after the reminder
MISSED_DURATION_RATIO = 2.0    # actual > 2 x estimate without a duration_ratio trigger = a miss
LABEL_EPS = 1e-9               # float tolerance for the boundary comparisons (1.2 * 3 = 3.5999999999999996)
LABEL_ACTIONS = ("resplit", "replan")
DURATION_LIKE = ("duration_ratio", "straggler_ratio", "split_unit_error", "split_uneven", "split_underused")


def _outcome_for(outcomes, rec):
    """Outcome of the record's subject, with an optional per-metric override in `by_metric`."""
    base = outcomes.get(str(rec.get("task_id"))) or {}
    if not isinstance(base, dict):
        return {}
    o = {k: v for k, v in base.items() if k != "by_metric"}
    extra = (base.get("by_metric") or {}).get(rec.get("metric"))
    if isinstance(extra, dict):
        o.update(extra)
    return o


def _on_time(actual, planned):
    # exactly 1.2 x counts as on time (<=): the rule says "<= 1.2 x", so the boundary is a false positive
    # with a small tolerance so that e.g. est 3 / actual 3.6 is not lost to float rounding
    return (actual is not None and planned is not None and planned > 0
            and actual <= LABEL_ON_TIME_RATIO * planned + LABEL_EPS)


def _action_taken(v):
    """True / "resplit" / "replan" -> taken; False -> not taken; anything else -> unknown (None)."""
    if v is True or v in LABEL_ACTIONS:
        return True
    if v is False:
        return False
    return None


def _label_duration_like(o):
    actual, est = num(o.get("actual_min")), num(o.get("est_min"))
    raw = o.get("action_taken")
    taken = _action_taken(raw)
    if taken:
        exp, got = num(o.get("expected_saving_min")), num(o.get("actual_saving_min"))
        if exp is None or got is None or exp <= 0:
            return None, "action taken but expected_saving_min / actual_saving_min missing"
        # exactly 50% counts as effective (>=), as the rule says "saved >= 50% of the expected saving"
        if got >= LABEL_SAVING_MIN_SHARE * exp - LABEL_EPS:
            return "effective", "%s saved %.1f of expected %.1f min (>= %d%%)" % (
                raw if isinstance(raw, str) else "action", got, exp, LABEL_SAVING_MIN_SHARE * 100)
        return "false_positive", "%s saved %.1f of expected %.1f min (< %d%%)" % (
            raw if isinstance(raw, str) else "action", got, exp, LABEL_SAVING_MIN_SHARE * 100)
    if taken is False and _on_time(actual, est):
        return "false_positive", "no action; actual %.1f <= %.1f x estimate %.1f min" % (
            actual, LABEL_ON_TIME_RATIO, est)
    if taken is None:
        return None, "action_taken unknown (%r)" % (raw,)
    return None, "no action and actual time over %.1f x estimate (or unknown)" % LABEL_ON_TIME_RATIO


def _progress_series(o):
    pts = []
    for p in o.get("progress") or []:
        if isinstance(p, dict) and parse_ts(p.get("ts")) is not None and num(p.get("done")) is not None:
            pts.append((parse_ts(p["ts"]), p["done"]))
    return sorted(pts, key=lambda x: x[0])


def _label_idle(o, rec):
    at = parse_ts(o.get("reminder_ts") or rec.get("ts"))
    pts = _progress_series(o)
    if at is None or not pts:
        return None, "no progress series or reminder time"
    before = [d for t, d in pts if t <= at]
    after = [d for t, d in pts if t > at]
    if not before:
        return None, "no progress point at or before the reminder"
    base = before[-1]
    effective = any(d > base for d in after[:LABEL_IDLE_WINDOW])
    rising = len(before) >= 2 and before[-1] > before[0] and bool(after) and after[-1] > base
    fp = rising and _on_time(num(o.get("actual_min")), num(o.get("est_min")))
    if effective and fp:
        # progress was rising before the stall, rose again after the reminder, and the shard finished on
        # time: either the reminder unblocked it or it was waiting on a long background step. No rule decides.
        return None, "conflicting: progress rose after the reminder, but also rose before it and finished on time"
    if effective:
        return "effective", "done rose from %s within %d check-ins after the reminder" % (base, LABEL_IDLE_WINDOW)
    if fp:
        return "false_positive", "progress rising before and after the reminder and finished within %.1f x estimate" % LABEL_ON_TIME_RATIO
    return None, "progress did not rise within %d check-ins and the waiting-on-background pattern does not hold" % LABEL_IDLE_WINDOW


def _label_failure(o):
    culprits = o.get("culprits")
    located = o.get("located") is True or (isinstance(culprits, list) and len(culprits) > 0)
    flaky = o.get("rerun_passed") is True
    if located and flaky:
        return None, "conflicting: located to a shard but the rerun also passed"
    if located:
        return "effective", "failure located to shard(s) %s" % (o.get("culprits") or "")
    if flaky:
        return "false_positive", "rerun passed without changes (flaky)"
    return None, "not located and no passing rerun"


def _label_rework(o):
    n = num(o.get("rework_after_message"))
    if n == 0:
        return "effective", "no further rework after the review-brief message"
    return None, "rework continued after the message" if n else "rework_after_message unknown"


def _label_cost(o):
    d = o.get("user_decision")
    if d in ("stop", "adjust"):
        return "effective", "user chose to %s" % d
    if d == "continue":
        cost, budget = num(o.get("final_cost_usd")), num(o.get("budget_usd"))
        if _on_time(cost, budget):
            return "false_positive", "user continued unchanged; final cost %.2f <= %.1f x budget %.2f" % (
                cost, LABEL_ON_TIME_RATIO, budget)
        return None, "user continued and final cost over %.1f x budget (or unknown)" % LABEL_ON_TIME_RATIO
    return None, "no user decision"


def _label_boundary(o):
    c, v = num(o.get("merge_conflicts")), num(o.get("ownership_violations"))
    if (c or 0) > 0 or (v or 0) > 0:
        return "effective", "merge conflicts %s, ownership violations %s" % (c, v)
    if c == 0 and v == 0:
        return "false_positive", "all shards merged cleanly"
    return None, "merge_conflicts / ownership_violations unknown"


def label_one(rec, outcomes):
    o = _outcome_for(outcomes, rec)
    m = rec.get("metric")
    if not o:
        return None, "no outcome for %s" % rec.get("task_id")
    if m in DURATION_LIKE:
        return _label_duration_like(o)
    if m == "idle_min":
        return _label_idle(o, rec)
    if m == "failure_rate":
        return _label_failure(o)
    if m == "rework":
        return _label_rework(o)
    if m == "cost_ratio":
        return _label_cost(o)
    if m == "split_boundary":
        return _label_boundary(o)
    return None, "no rule for metric %s" % m


def label_records(records, outcomes):
    """Label monitor triggers by fixed rules and add rule-detected misses.
    Returns {"records", "unlabeled", "missed", "history"}; history = records + missed, the input
    `scale.py calibrate` expects. Records that already carry a label are kept untouched."""
    if outcomes is None:
        outcomes = {}
    if not isinstance(outcomes, dict):
        raise ValueError("outcomes must be an object keyed by task_id or \"batch\"")
    if records is None:
        records = []
    if not isinstance(records, list):
        raise ValueError("records must be a list")
    outcomes = {str(k): v for k, v in outcomes.items()}  # JSON keys are strings; task_id may be a number
    labelled, unlabeled, missed = [], [], []
    for rec in records or []:
        if not isinstance(rec, dict):
            continue
        if rec.get("label") or rec.get("event", "trigger") != "trigger":
            labelled.append(rec)  # human / reviewer label, or a missed record: never overwritten
            continue
        lab, why = label_one(rec, outcomes)
        if lab:
            labelled.append(dict(rec, label=lab, label_source="rule", label_reason=why))
        else:
            unlabeled.append(dict(rec, label=None, label_reason=why))
    allrecs = [r for r in records or [] if isinstance(r, dict)]

    def has(metric, task_id=None):
        return any(r.get("metric") == metric and (task_id is None or str(r.get("task_id")) == task_id)
                   for r in allrecs)

    batch_ids = sorted({r.get("batch_id") for r in allrecs if r.get("batch_id")})
    run_ids = sorted({r.get("run_id") for r in allrecs if r.get("run_id")})

    def miss(metric, task_id, task_type, reason):
        m = {"type": "monitor", "event": "missed", "metric": metric, "task_id": task_id,
             "task_type": task_type or "*", "label_source": "rule", "label_reason": reason}
        if len(batch_ids) == 1:
            m["batch_id"] = batch_ids[0]
        if len(run_ids) == 1:
            m["run_id"] = run_ids[0]
        return m

    def task_type_of(tid, o):
        if o.get("task_type"):
            return o["task_type"]
        return next((r.get("task_type") for r in allrecs if str(r.get("task_id")) == tid and r.get("task_type")), None)

    for tid, o in outcomes.items():
        if not isinstance(o, dict):
            continue
        if tid != "batch":
            actual, est = num(o.get("actual_min")), num(o.get("est_min"))
            # exactly 2 x is not a miss: the trigger itself fires only above 2 x (strict >)
            if actual is not None and est and actual > MISSED_DURATION_RATIO * est and not has("duration_ratio", tid):
                missed.append(miss("duration_ratio", tid, task_type_of(tid, o),
                                   "actual %.1f > %.1f x estimate %.1f min, no duration_ratio trigger"
                                   % (actual, MISSED_DURATION_RATIO, est)))
            continue
        fails = num(o.get("verify_failed_groups")) or 0
        rate = num(o.get("failure_rate"))
        th = num(o.get("failure_rate_threshold"))
        th = DEFAULT_THRESHOLDS["failure_rate"] if th is None else th
        if fails > 0 and rate is not None and rate > th and not has("failure_rate"):
            missed.append(miss("failure_rate", "batch", task_type_of("batch", o),
                               "%d merge group(s) failed verification, failure rate %.2f > %.2f, no failure_rate trigger"
                               % (fails, rate, th)))
    return {"records": labelled, "unlabeled": unlabeled, "missed": missed, "history": labelled + missed}


def cmd_label(a):
    d = read_json_stdin()
    if not isinstance(d, dict):
        die("stdin must be {\"records\": [...], \"outcomes\": {...}}")
    try:
        res = label_records(d.get("records"), d.get("outcomes"))
    except ValueError as e:
        die(str(e))
    return out(res)


# ---------- PLAYBOOK storage: user values in the 授权 yaml, calibrated values in a marked block ----------

BEGIN, END = "<!-- hq:thresholds:begin -->", "<!-- hq:thresholds:end -->"


def _scalar(v):
    v = v.strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in "'\"":
        return v[1:-1]
    if v in ("null", "~", ""):
        return None
    try:
        return int(v)
    except ValueError:
        pass
    try:
        return float(v)
    except ValueError:
        return v


def _flow(v):
    v = v.strip()
    if v.startswith("{") and v.endswith("}"):
        o = {}
        for part in v[1:-1].split(","):
            if part.strip():
                k, _, x = part.partition(":")
                o[_scalar(k)] = _scalar(x)
        return o
    return _scalar(v)


def yaml_block(text, top):
    """Tiny YAML subset reader for one top-level key inside ```yaml fences (nested maps, flow maps)."""
    root, stack, fence, inside = {}, [], False, False
    for raw in text.splitlines():
        if raw.strip().startswith("```"):
            fence = not fence
            inside = False
            continue
        if not fence:
            continue
        line = raw.split(" #", 1)[0].rstrip() if not raw.lstrip().startswith("#") else ""
        if not line.strip():
            continue
        ind = len(line) - len(line.lstrip())
        if ind == 0:
            inside = line.startswith(top + ":")
            stack = [(0, root)]
            if inside:
                root.setdefault(top, {})
                stack = [(0, root[top])]
            continue
        if not inside:
            continue
        k, sep, v = line.strip().partition(":")
        if not sep:
            continue
        k = _scalar(k)
        while len(stack) > 1 and stack[-1][0] >= ind:
            stack.pop()
        parent = stack[-1][1]
        if not v.strip():
            parent[k] = {}
            stack.append((ind, parent[k]))
        else:
            parent[k] = _flow(v)
    return root.get(top) or {}


def read_block(text):
    i, j = text.find(BEGIN), text.find(END)
    if i < 0 or j < i:
        return None
    body = text[i + len(BEGIN):j]
    m = re.search(r"```json\s*(.*?)```", body, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(1))
    except ValueError:
        return None


def write_block(text, data):
    block = (BEGIN + "\n```json\n" + json.dumps(data, ensure_ascii=False, indent=1) + "\n```\n" + END)
    i, j = text.find(BEGIN), text.find(END)
    if i >= 0 and j > i:
        return text[:i] + block + text[j + len(END):]
    sep = "" if text.endswith("\n") else "\n"
    return (text + sep + "\n## 监控阈值（自动校准，勿手改；手动设定写在授权区 monitor.thresholds）\n\n" + block + "\n")


def effective_thresholds(playbook):
    text = read_text(playbook) if os.path.exists(playbook) else ""
    raw = yaml_block(text, "monitor").get("thresholds") or {}
    user = {}
    flat = {k: v for k, v in raw.items() if k in DEFAULT_THRESHOLDS and num(v) is not None}
    if flat:  # `thresholds: {idle_min: 30}` without a task type means all types
        user["*"] = flat
    for k, v in raw.items():
        if isinstance(v, dict):
            user.setdefault(str(k), {}).update(
                {m: x for m, x in v.items() if m in DEFAULT_THRESHOLDS and num(x) is not None})
    blk = read_block(text) or {}
    cal = blk.get("thresholds") or {}
    eff = {}
    for tt in set(cal) | set(user) | {"*"}:
        m = dict(DEFAULT_THRESHOLDS)
        m.update((cal.get("*") or {}))
        m.update(cal.get(tt) or {})
        m.update((user.get("*") or {}) if tt == "*" else {})
        m.update(user.get(tt) or {})
        eff[tt] = m
    return {"thresholds": eff, "user": user, "calibrated": blk}


def cmd_calibrate(a):
    d = read_json_stdin()
    user = d.get("user")
    current = d.get("current")
    if a.playbook:
        e = effective_thresholds(a.playbook)
        user = user if user is not None else e["user"]
        current = current if current is not None else (e["calibrated"].get("thresholds") or {})
    r = calibrate(current, d.get("history") or [], d.get("ratios"), user, d.get("task_types"))
    r["previous"] = current or {}
    if a.playbook and a.write:
        text = read_text(a.playbook) if os.path.exists(a.playbook) else ""
        old = read_block(text) or {}
        data = {"version": int(old.get("version") or 0) + 1,
                "calibrated_at": now_or(a.now).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "thresholds": r["thresholds"], "changes": r["changes"],
                "previous": {"version": old.get("version"), "thresholds": old.get("thresholds") or {}}}
        write_text(a.playbook, write_block(text, data))
        r["written"] = a.playbook
        r["version"] = data["version"]
    return out(r)


def cmd_thresholds(a):
    if a.rollback:
        text = read_text(a.playbook)
        blk = read_block(text)
        if not blk or not blk.get("previous") or blk["previous"].get("version") is None:
            return out({"rolled_back": False, "reason": "no_previous_version"}, 1)
        prev = blk["previous"]
        data = {"version": prev["version"], "calibrated_at": now_or(a.now).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "thresholds": prev.get("thresholds") or {}, "changes": [],
                "rolled_back_from": blk.get("version"), "previous": {"version": None, "thresholds": {}}}
        write_text(a.playbook, write_block(text, data))
        return out({"rolled_back": True, "from": blk.get("version"), "to": prev["version"],
                    "thresholds": data["thresholds"]})
    return out(effective_thresholds(a.playbook))


# =====================================================================================

def main(argv=None):
    ap = argparse.ArgumentParser(description="hq scale-out rules (see references/scale-out.md)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("shards", help="how many shards for a workload")
    p.add_argument("--units", type=int, default=0)
    p.add_argument("--unit-min", type=float, required=True)
    p.add_argument("--overhead-min", type=float, default=8.0)
    p.add_argument("--target-min", type=float, default=40.0)
    p.add_argument("--limit", type=int, default=4, help="concurrency limit (PLAYBOOK remote_concurrency)")
    p.add_argument("--reserve-ratio", type=float, default=0.2)
    p.add_argument("--max-overhead-ratio", type=float, default=0.3)
    p.add_argument("--units-file", help="one unit per line, optional TAB weight; prints the assignment")
    p.set_defaults(fn=cmd_shards)

    p = sub.add_parser("straggler", help="ETA per shard and re-split proposals")
    p.add_argument("--target-min", type=float, default=40.0)
    p.add_argument("--overhead-min", type=float, default=8.0)
    p.add_argument("--free-slots", type=int, default=0)
    p.add_argument("--now")
    p.set_defaults(fn=cmd_straggler)

    p = sub.add_parser("progress", help="parse the last HQ-PROGRESS line")
    p.add_argument("--file")
    p.set_defaults(fn=cmd_progress)

    p = sub.add_parser("delivered", help="is there a real 交付 section with a verification result")
    p.add_argument("--done-file")
    p.set_defaults(fn=cmd_delivered)

    p = sub.add_parser("test-scope", help="related tests or full suite for a worker")
    p.add_argument("--changed", nargs="*")
    p.add_argument("--foundation", nargs="*", help="extra shared-foundation globs (PLAYBOOK scale_out.shared_foundation)")
    p.add_argument("--require-full", action="store_true")
    p.set_defaults(fn=cmd_test_scope)

    p = sub.add_parser("full-gate", help="is this check-in a full-suite checkpoint")
    for k in ("since-shards", "since-lines", "since-files"):
        p.add_argument("--" + k, type=int, default=0)
    for k in ("batch-complete", "before-push", "ci-checkpoint"):
        p.add_argument("--" + k, action="store_true")
    p.add_argument("--every-shards", type=int, default=4)
    p.add_argument("--every-lines", type=int, default=1500)
    p.add_argument("--every-files", type=int, default=60)
    p.set_defaults(fn=cmd_full_gate)

    p = sub.add_parser("merge-group", help="which delivered shards merge together this check-in")
    p.add_argument("--wait-max-min", type=float, default=10.0)
    p.set_defaults(fn=cmd_merge_group)

    p = sub.add_parser("locate", help="which shard broke the group verification")
    p.set_defaults(fn=cmd_locate)

    p = sub.add_parser("monitor", help="evaluate one check-in against thresholds")
    p.add_argument("--state", help="JSON state file, e.g. .hq/monitor-state.json")
    p.add_argument("--config", help="JSON {thresholds, limits}")
    p.add_argument("--playbook", help="take thresholds from PLAYBOOK (user > calibrated > default)")
    p.add_argument("--now")
    p.set_defaults(fn=cmd_monitor)

    p = sub.add_parser("calibrate", help="adjust thresholds from labelled triggers")
    p.add_argument("--playbook")
    p.add_argument("--write", action="store_true")
    p.add_argument("--now")
    p.set_defaults(fn=cmd_calibrate)

    p = sub.add_parser("label", help="label monitor triggers by rule and add rule-detected misses")
    p.set_defaults(fn=cmd_label)

    p = sub.add_parser("thresholds", help="show effective thresholds or roll back one version")
    p.add_argument("--playbook", required=True)
    p.add_argument("--rollback", action="store_true")
    p.add_argument("--now")
    p.set_defaults(fn=cmd_thresholds)

    a = ap.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())

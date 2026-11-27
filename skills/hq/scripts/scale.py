#!/usr/bin/env python3
"""hq scale-out rules: shard sizing, straggler re-split and re-plan, delivery marker, test scope,
batched merges and failure location.

Every subcommand is a pure function of its input (JSON on stdin or flags) and prints JSON.
The rules are documented in references/scale-out.md; this script is the executable version so
the main session does not re-derive them by hand. Exit codes: 0 = ok / yes, 1 = a "no" answer
(not delivered, no progress line), 2 = bad input.

  scale.py shards      --units N --unit-min X --limit L [--reserve 0] [--overhead-min 8]
                       [--target-min 40] [--max-overhead-ratio 0.3] [--units-file F]
  scale.py straggler   [--target-min 40] [--overhead-min 8] [--free-slots K] [--now ISO] < shards.json
  scale.py progress    [--file F]          < text   (last "HQ-PROGRESS done=.. total=.." line)
  scale.py delivered   [--done-file F]     < commit body / final message
  scale.py test-scope  --changed F... [--foundation GLOB...] [--require-full]
  scale.py merge-group [--wait-max-min 10] < {"delivered":[..],"pending":[..],"owners":{..}}
  scale.py locate                          < {"group":[{"id","files"}],"failures":[paths]}

Monitoring, rate-limited analysis, labelling, threshold calibration and the full-suite gate were
deferred (see scale-out.md "推迟的功能"); the old implementation is in commit b3ead43.
"""
import argparse
import json
import math
import re
import statistics
import sys
from datetime import datetime, timezone

EPS = 1e-9  # every "exactly at the threshold" comparison goes through this tolerance


def out(obj, code=0):
    sys.stdout.write(json.dumps(obj, ensure_ascii=False, indent=2) + "\n")
    return code


def die(msg, code=2):
    print("scale.py: " + msg, file=sys.stderr)
    sys.exit(code)


def read_text(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return fh.read()
    except (OSError, UnicodeDecodeError) as e:
        die("cannot read %s: %s" % (path, e))


def read_json_stdin():
    try:
        return json.load(sys.stdin)
    except ValueError as e:
        die("stdin is not valid JSON: %s" % e)


def num(x):
    """A finite real number, or None (bools and strings are not numbers)."""
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


def r1(x):
    return None if x is None else round(x, 1)


def ceil9(x):
    """ceil() that ignores float noise: 440.00000000000006 / 44 is 10, not 11."""
    return int(math.ceil(round(x, 9)))


# =====================================================================================
# 1. shard count: by workload, not by module count
# =====================================================================================

def _shard_fields(work, units, n, overhead_min, target_min):
    per = work / n + overhead_min
    return {"shards": n, "units_per_shard": r1(units / n), "shard_min": r1(per),
            "overhead_ratio": round(overhead_min / per, 3), "batch_eta_min": r1(per),
            "over_target": per > target_min * 1.25 + EPS}


def shard_plan(units, unit_min, overhead_min=8.0, target_min=40.0, *, limit, reserve=0,
               max_overhead_ratio=0.3):
    """work = units * unit_min; by_target = ceil(work / target); usable = limit - reserve;
    n = min(usable, by_target, units), then fewer shards while the fixed overhead exceeds
    max_overhead_ratio of a shard. Same formula as metrics.py. Raises ValueError on bad input."""
    if isinstance(units, bool) or not isinstance(units, int) or units <= 0:
        raise ValueError("units must be an integer > 0")
    for name, v, lo in (("unit_min", unit_min, 0), ("target_min", target_min, 0)):
        if num(v) is None or v <= lo:
            raise ValueError("%s must be a finite number > 0" % name)
    if num(overhead_min) is None or overhead_min < 0:
        raise ValueError("overhead_min must be a finite number >= 0")
    if num(max_overhead_ratio) is None or max_overhead_ratio < 0:
        raise ValueError("max_overhead_ratio must be a finite number >= 0")
    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
        raise ValueError("limit must be an integer >= 1")
    if isinstance(reserve, bool) or not isinstance(reserve, int) or reserve < 0:
        raise ValueError("reserve must be an integer >= 0")
    work = units * unit_min
    if not math.isfinite(work):
        raise ValueError("units * unit_min is not a finite number (overflow)")
    by_target = max(1, ceil9(work / target_min))
    usable = max(1, limit - reserve)
    n = max(1, min(usable, by_target, units))
    why = []
    if by_target > usable:
        why.append("并发：⌈%g/%g⌉=%d 超过可用槽位 %d（上限 %d − 预留 %d）"
                   % (work, target_min, by_target, usable, limit, reserve))
    else:
        why.append("工作量：⌈%g 分钟 / 目标 %g 分钟⌉ = %d" % (work, target_min, by_target))
    if n == units and units < min(usable, by_target):
        why.append("受单元数 %d 限制" % units)
    reduced = False
    while n > 1 and overhead_min / (work / n + overhead_min) > max_overhead_ratio + EPS:
        n -= 1
        reduced = True
    if reduced:
        why.append("减少片数：固定开销 %g 分钟会超过单片时长的 %g%%" % (overhead_min, max_overhead_ratio * 100))
    needed_limit = reserve + max(1, min(units, by_target))
    plan = {"units": units, "total_work_min": r1(work), "serial_min": r1(work + overhead_min),
            "limit": limit, "reserve": reserve, "usable_slots": usable, "needed_limit": needed_limit}
    plan.update(_shard_fields(work, units, n, overhead_min, target_min))
    if plan["over_target"]:
        if needed_limit > limit:
            why.append("并发上限 %d 不够：要在目标时长内完成需要上限 %d，可请用户提高 remote_concurrency / max_subtasks"
                       % (limit, needed_limit))
        else:
            why.append("单片仍超过目标时长 1.25 倍：单元数或固定开销限制了片数，提高并发上限没有用")
    plan["why"] = "；".join(why)
    return plan


def _weight(w):
    v = num(w)
    return v if v is not None and v > 0 else 1.0


def split_units(items, n):
    """Contiguous, weight-balanced split of an ordered unit list into min(n, len(items)) non-empty
    shards (keeps neighbours together, ignores module boundaries). items: [(name, weight)];
    weights <= 0 or non-finite count as 1."""
    items = [(name, _weight(w)) for name, w in items]
    if not items:
        return []
    k = max(1, min(int(n), len(items)))
    total = sum(w for _, w in items)
    shards = [[]]
    acc = 0.0
    for idx, (name, w) in enumerate(items):
        unopened = k - len(shards)
        if shards[-1] and unopened > 0 and (
                len(items) - idx <= unopened or acc + w / 2.0 > total * len(shards) / k + EPS):
            shards.append([])
        shards[-1].append(name)
        acc += w
    return shards


def read_units_file(path):
    items = []
    for line in read_text(path).splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        name, _, w = line.partition("\t")
        name = name.strip()
        if not name:
            continue
        try:
            weight = float(w) if w.strip() else 1.0
        except ValueError:
            weight = 1.0
        items.append((name, _weight(weight)))
    return items


def cmd_shards(a):
    units, items = a.units, None
    if a.units_file:
        items = read_units_file(a.units_file)
        if not items:
            die("--units-file %s has no units" % a.units_file)
        if units and units != len(items):
            die("--units %d does not match %d units in %s" % (units, len(items), a.units_file))
        units = len(items)
    if not units:
        die("give --units or --units-file")
    try:
        plan = shard_plan(units, a.unit_min, a.overhead_min, a.target_min, limit=a.limit,
                          reserve=a.reserve, max_overhead_ratio=a.max_overhead_ratio)
    except ValueError as e:
        die(str(e))
    if items:
        parts = split_units(items, plan["shards"])
        if len(parts) != plan["shards"]:
            plan.update(_shard_fields(units * a.unit_min, units, len(parts), a.overhead_min, a.target_min))
        plan["assignment"] = parts
    return out(plan)


# =====================================================================================
# 4. progress rate, ETA, straggler re-split and batch re-plan
# =====================================================================================

# only a line that *is* a progress line: at line start, optionally after a log timestamp or [tag];
# quoted (> HQ-PROGRESS), echoed (echo "HQ-PROGRESS ..") or inline-code mentions do not count
PROGRESS_LINE = re.compile(
    r"^\s*(?:\d{4}-\d\d-\d\d[T ][\d:.]+(?:Z|[+-]\d\d:?\d\d)?\s+|\[[^\]\n]*\]\s*)*HQ-PROGRESS\b(.*)$")
KV_RE = re.compile(r"(\w+)=(\S+)")
PROGRESS_KEYS = ("done", "total", "rework", "failed")


def _num_text(v):
    v = v.rstrip(",;.。，；、")
    try:
        x = float(v)
    except ValueError:
        return None
    if not math.isfinite(x):
        return None
    return int(x) if x.is_integer() else x


def parse_progress(text):
    """Last 'HQ-PROGRESS done=37 total=150 rework=1 failed=0' line, or a JSON progress file.
    Only finite numbers are kept; a line with no usable value is skipped."""
    s = text.strip()
    if s.startswith("{"):
        try:
            d = json.loads(s)
        except ValueError:
            d = None
        if isinstance(d, dict):
            o = {k: d[k] for k in PROGRESS_KEYS if k in d and num(d[k]) is not None}
            if o and isinstance(d.get("updated_at"), str):
                o["updated_at"] = d["updated_at"]
            return o or None
    last = None
    fence = False
    for line in text.splitlines():
        if line.strip().startswith(("```", "~~~")):
            fence = not fence
            continue
        if fence:
            continue
        m = PROGRESS_LINE.match(line)
        if not m:
            continue
        o = {}
        for k, v in KV_RE.findall(m.group(1)):
            x = _num_text(v)
            if x is not None:
                o[k] = x
        if o:
            last = o
    return last


def cmd_progress(a):
    text = read_text(a.file) if a.file else sys.stdin.read()
    p = parse_progress(text)
    return out({"progress": p}, 0 if p else 1)


def _elapsed(s, now):
    e = num(s.get("elapsed_min"))
    if e is not None:
        return e if e >= 0 else None
    st = parse_ts(s.get("started_at") or s.get("created_at"))
    if st and now:
        e = (now - st).total_seconds() / 60.0
        return e if e >= 0 else None
    return None


def _counts(s):
    done, total = num(s.get("done")), num(s.get("total"))
    if s.get("done") is not None and done is None:  # string / bool / NaN done: same as a bad total
        return None, None
    if total is None or total <= 0 or (done is not None and done < 0):
        return None, None
    return done, total


def straggler_check(s, target_min=40.0, overhead_min=8.0, free_slots=0, now=None):
    """Decide whether to split the rest of one shard into new sessions.

    Straggler: projected total > 2 x planned shard length. Re-split only if the remainder is still
    worth it (> 2 x target): a shard close to done is left alone because a new session's start-up
    overhead would eat the gain. Never more pieces than remaining units."""
    if not isinstance(s, dict):
        return {"id": None, "action": "none", "reason": "invalid_shard"}
    est = num(s.get("est_min"))
    est_ok = est is not None and est > 0
    est = est if est_ok else target_min
    elapsed = _elapsed(s, now)
    done, total = _counts(s)
    res = {"id": s.get("id"), "elapsed_min": r1(elapsed), "est_min": est, "done": done, "total": total}
    if not est_ok:
        res["est_min_defaulted"] = True
    if elapsed is None or total is None:
        return dict(res, action="none", reason="no_progress_data")
    remaining_units = max(0, total - (done or 0))
    if remaining_units <= EPS:
        return dict(res, action="none", reason="complete", remaining_min=0)
    work_min = elapsed - overhead_min
    if not done or work_min <= EPS:
        return dict(res, action="none", reason="no_rate_yet")
    rate = done / work_min  # units per minute
    remaining_min = remaining_units / rate
    projected = elapsed + remaining_min
    res.update(rate_per_min=round(rate, 3), remaining_units=remaining_units,
               remaining_min=r1(remaining_min), projected_total_min=r1(projected),
               projected_ratio=round(projected / est, 2))
    if projected <= 2 * est + EPS:
        return dict(res, action="none", reason="on_track")
    if remaining_min <= 2 * target_min + EPS:
        return dict(res, action="none", reason="near_done")
    rem_u = int(math.ceil(remaining_units - EPS))
    if rem_u <= 1:
        return dict(res, action="report", reason="straggler_unsplittable")
    if free_slots <= 0:
        return dict(res, action="report", reason="straggler_no_free_slot")
    k = min(int(free_slots), max(1, ceil9(remaining_min / target_min) - 1), rem_u - 1)
    # the original shard keeps one share; each new session pays the start-up overhead
    new_eta = overhead_min + remaining_min / (k + 1)
    if new_eta >= remaining_min - EPS:
        return dict(res, action="none", reason="no_gain")
    split = [int(math.floor(rem_u * i / (k + 1) + 0.5)) for i in range(k + 2)]
    base = int(done)
    return dict(res, action="resplit", reason="straggler", new_sessions=k,
                eta_after_min=r1(new_eta), saves_min=r1(remaining_min - new_eta),
                extra_overhead_min=r1(k * overhead_min), split=split,
                keep_until=base + split[1],
                ranges=[[base + split[i] + 1, base + split[i + 1]] for i in range(k + 1)])


REPLAN_MIN_SHARDS = 3
REPLAN_MIN_PROGRESS = 0.1   # a shard's measured unit time counts once it has done 10% of its units
REPLAN_ERROR = 0.5          # |median(measured / estimated - 1)| above this re-plans the rest
REPLAN_AGREEMENT = 0.75     # and at least this share of shards err the same way


def replan(shards, target_min=40.0, overhead_min=8.0, free_slots=0, now=None):
    """Batch-level: when most shards show the unit-time estimate was wrong the same way, re-plan the
    remaining units with the measured unit time (same formula as `shards`). None otherwise."""
    errs, meas, remaining, running = [], [], 0.0, 0
    for s in shards:
        if not isinstance(s, dict) or s.get("delivered"):
            continue
        done, total = _counts(s)
        if total is None:
            continue
        left = max(0.0, total - (done or 0))
        if left <= EPS:
            continue
        running += 1
        remaining += left
        elapsed = _elapsed(s, now)
        est = num(s.get("unit_min_est"))
        if (elapsed is None or not done or est is None or est <= 0
                or elapsed - overhead_min <= EPS or done / total < REPLAN_MIN_PROGRESS - EPS):
            continue
        um = (elapsed - overhead_min) / done
        meas.append(um)
        errs.append(um / est - 1)
    if len(errs) < REPLAN_MIN_SHARDS or running == 0:
        return None
    e = statistics.median(errs)
    if abs(e) <= REPLAN_ERROR + EPS:
        return None
    agree = sum(1 for x in errs if (x > 0) == (e > 0) and abs(x) > EPS) / len(errs)
    if agree < REPLAN_AGREEMENT - EPS:
        return None
    unit = statistics.median(meas)
    rem_u = int(math.ceil(remaining - EPS))
    free = max(0, int(free_slots))
    plan = shard_plan(rem_u, unit, overhead_min, target_min, limit=running + free)
    return {"measured_unit_min": round(unit, 3), "median_error": round(e, 2), "shards_measured": len(errs),
            "remaining_units": rem_u, "shards_for_remaining": plan["shards"], "running": running,
            "new_sessions": max(0, min(free, plan["shards"] - running)), "shard_min": plan["shard_min"],
            "why": plan["why"]}


def cmd_straggler(a):
    data = read_json_stdin()
    shards = data.get("shards") if isinstance(data, dict) else data
    if not isinstance(shards, list) or not all(isinstance(s, dict) for s in shards):
        die("stdin must be a list of shard objects or {\"shards\": [...]}")
    now = parse_now(a.now)
    free = max(0, a.free_slots)
    rp = replan(shards, a.target_min, a.overhead_min, max(0, a.free_slots), now)
    res = []
    for s in shards:
        r = straggler_check(s, a.target_min, a.overhead_min, free, now)
        if r["action"] == "resplit":
            free -= r["new_sessions"]
        res.append(r)
    obj = {"shards": res, "free_slots_left": free, "replan": rp}
    if rp is not None:  # the batch-level re-plan owns the free slots; per-shard resplits are advisory
        obj["free_slots_left"] = max(0, max(0, a.free_slots) - rp["new_sessions"])
        obj["note"] = "replan 优先，各片 resplit 建议仅供参考"
    return out(obj)


# =====================================================================================
# 8. delivery marker: a real "交付" section with a verification result, not the word anywhere
# =====================================================================================

HEAD_RE = re.compile(r"^(#{1,6})\s*(?:\*\*|__)?\s*(交付|delivery)\s*(?:\*\*|__)?\s*[:：]?\s*$", re.I)
ANY_HEAD_RE = re.compile(r"^(#{1,6})\s+\S")
OTHER_FIELD_RE = re.compile(
    r"^\s*(?:[-*+]\s+)?(?:\*\*|__)?\s*(?:BRANCH|CHANGES|CHECKPOINTS|DERIVED|RISKS|QUESTIONS|SHARED_FIXES|PROGRESS|STATUS)"
    r"\s*(?:\*\*|__)?\s*[:：]")
# a VERIFY continuation line is a list item or a command line, never prose
CONT_RE = re.compile(r"^(?:[-*+•$`]|\d+[.)．])")
FIELD_RE = re.compile(r"^(?:[-*+]\s+)?(?:\*\*|__)?\s*(STATUS|VERIFY)\s*(?:\*\*|__)?\s*[:：]\s*(?:\*\*|__)?\s*(.*)$", re.I)
PLACEHOLDER = re.compile(
    r"^(none|n/?a|na|null|nil|无|暂无|没有|待补|待补记|待补充|待定|待验证|未验证|未运行|未跑|没跑|稍后|稍后补|"
    r"tbd|todo|pending|not run|not yet run|not yet|not verified|unverified|-+|—+|…+|\.{2,}|\?+|？+)?$", re.I)


def is_placeholder(v):
    if not isinstance(v, str):
        return True
    s = re.sub(r"<!--.*?-->", "", v, flags=re.S).strip()
    s = s.strip("*_` ").strip()
    if re.fullmatch(r"<[^<>]*>", s):
        return True  # template slot like <命令及结果>
    def bare(x):
        return bool(PLACEHOLDER.match(x.strip().rstrip("。.,，;；!！ ").strip()))
    # brackets are only dropped around fixed placeholder words: （待补记）, 待补记（稍后）;
    # a bracketed result such as (pytest 12 passed) is a real value
    m = re.fullmatch(r"[（(]([^（）()]*)[）)]", s)
    if m:
        return bare(m.group(1))
    m = re.fullmatch(r"(.*?)\s*[（(][^（）()]*[）)]", s)
    if m and m.group(1).strip():
        return bare(m.group(1))
    return bare(s)


def _outside_fences(lines):
    fence = None
    for line in lines:
        t = line.strip()
        m = re.match(r"^(`{3,}|~{3,})", t)
        if m:
            if fence is None:
                fence = m.group(1)[0]
            elif t.startswith(fence * 3):
                fence = None
            yield None
            continue
        yield None if fence else t


def check_delivery(text):
    """The last '## 交付' section (outside code blocks) must say STATUS: DONE and have a real VERIFY."""
    lines = list(_outside_fences(text.splitlines()))
    heads = [(i, len(m.group(1))) for i, l in enumerate(lines) if l is not None for m in [HEAD_RE.match(l)] if m]
    if not heads:
        return {"delivered": False, "reason": "no_delivery_section"}
    i, level = heads[-1]
    status = verify = None
    in_verify = False  # VERIFY's result may continue on the following lines (a list of commands and output)
    for l in lines[i + 1:]:
        if l is None:
            continue
        h = ANY_HEAD_RE.match(l)
        if h and len(h.group(1)) <= level:
            break
        if h:
            in_verify = False
        m = FIELD_RE.match(l)
        if not m and OTHER_FIELD_RE.match(l):
            in_verify = False  # CHANGES: / CHECKPOINTS: / RISKS: ... end the VERIFY block
            continue
        if not m:
            if in_verify:
                if CONT_RE.match(l):
                    if not is_placeholder(l.lstrip("-*+• ").strip()):
                        verify = (verify + " " if verify else "") + l
                else:
                    in_verify = False  # blank line, prose or a sub-heading ends the VERIFY block
            continue
        in_verify = False
        key, val = m.group(1).upper(), m.group(2).strip().strip("*_ ").strip()
        if key == "STATUS" and status is None:
            status = val
        elif key == "VERIFY" and verify is None:
            verify = val
            in_verify = not val  # only an empty same-line value collects the lines below
    word = re.match(r"([A-Za-z_]+)", status or "")
    if not word or word.group(1).upper() != "DONE" or "|" in status:
        return {"delivered": False, "reason": "section_status_not_done", "status": status}
    if verify is None or is_placeholder(verify):
        return {"delivered": False, "reason": "section_without_verify", "status": status}
    return {"delivered": True, "reason": "section", "status": status, "verify": verify}


def check_done_file(path):
    try:
        with open(path, encoding="utf-8") as fh:
            d = json.load(fh)
    except (OSError, ValueError):
        return {"delivered": False, "reason": "done_file_unreadable"}
    if not isinstance(d, dict) or not isinstance(d.get("status"), str) or d["status"].strip().upper() != "DONE":
        return {"delivered": False, "reason": "done_file_status_not_done"}
    v = d.get("verify")
    if isinstance(v, str):
        ok = not is_placeholder(v)
    elif isinstance(v, list):
        ok = bool(v) and all(isinstance(x, str) and not is_placeholder(x) for x in v)
    else:
        ok = False  # true, numbers, objects: no verification result
    if not ok:
        return {"delivered": False, "reason": "done_file_without_verify"}
    return {"delivered": True, "reason": "done_file", "status": "DONE", "verify": v}


def cmd_delivered(a):
    r = check_done_file(a.done_file) if a.done_file else check_delivery(sys.stdin.read())
    return out(r, 0 if r["delivered"] else 1)


# =====================================================================================
# 5. layered verification: related tests in workers, full suite only for shared foundation
# =====================================================================================

DEFAULT_FOUNDATION = [
    "**/package.json", "**/pnpm-lock.yaml", "**/yarn.lock", "**/package-lock.json",
    "**/pnpm-workspace.yaml", "**/tsconfig*.json",
    "**/vite.config.*", "**/vitest.config.*", "**/vitest.workspace.*", "**/jest.config.*",
    "**/webpack.config.*", "**/babel.config.*", "**/.eslintrc*", "**/eslint.config.*",
    "**/setupTests.*", "**/test/setup*", "**/test-utils/**", "**/testing/**", "**/__mocks__/**",
    "**/.storybook/**",
    "**/pyproject.toml", "**/setup.cfg", "**/conftest.py", "**/go.mod", "**/go.sum", "**/Cargo.toml",
    "**/Makefile", ".github/workflows/**",
]


def norm_path(p):
    """Repo-relative form: backslashes to '/', leading './' (only that prefix) removed."""
    p = str(p).replace("\\", "/")
    p = re.sub(r"/{2,}", "/", p)
    return re.sub(r"^(\./)+", "", p)


def glob_re(g):
    """Glob with ** (any depth), * (no slash), ? ; anchored at the path start."""
    g = norm_path(g)
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
    p = norm_path(path)
    return next((g for g in globs if glob_re(g).match(p)), None)


def test_scope(changed, foundation=None, require_full=False):
    globs = list(foundation or []) + DEFAULT_FOUNDATION
    hits = []
    for f in changed:
        g = match_any(f, globs)
        if g:
            hits.append({"file": f, "glob": g})
    if require_full:
        return {"scope": "full", "reason": "project_rule", "foundation_hits": hits}
    if hits:
        return {"scope": "full", "reason": "shared_foundation", "foundation_hits": hits}
    return {"scope": "related", "reason": "no_shared_foundation", "foundation_hits": []}


def cmd_test_scope(a):
    return out(test_scope(a.changed or [], a.foundation, a.require_full))


# =====================================================================================
# 6. batched merge: everything delivered this check-in merges and verifies as one group
# =====================================================================================

def _eta(v):
    x = num(v)
    if x is None and isinstance(v, str):
        try:
            x = float(v.strip())
        except ValueError:
            x = None
        x = x if x is not None and math.isfinite(x) else None
    return None if x is None else max(0.0, x)


def _under(path, key):
    """path equals key, or lies under directory key."""
    k = key.rstrip("/")
    return path == k or path.startswith(k + "/")


def _overlaps(a, b):
    return _under(a, b) or _under(b, a)


def _owner_of(path, owners):
    """Most specific owner entry (exact file or enclosing directory). Returns (key, set) or None."""
    best = None
    for key, v in owners.items():
        if _under(path, key) and (best is None or len(key.rstrip("/")) > len(best[0].rstrip("/"))):
            best = (key, v)
    if best is None:
        return None
    v = best[1]
    ids = {str(x) for x in v if x is not None} if isinstance(v, list) else ({str(v)} if v not in (None, "") else set())
    return (best[0], ids) if ids else None


def _list(v):
    if v is None:
        return []
    return [v] if isinstance(v, str) else list(v) if isinstance(v, list) else []


def merge_group(delivered, pending=(), owners=None, wait_max_min=10):
    owners = {norm_path(k): v for k, v in (owners or {}).items()}
    wait_max_min = max(0.0, wait_max_min)
    deferred, by_id, ids = [], {}, []
    dup = set()
    for d in delivered:
        i = d.get("id")
        if i is None or i == "":
            deferred.append({"id": None, "reason": "missing_id", "files": _list(d.get("files"))})
            continue
        i = str(i)
        if i in by_id:
            dup.add(i)
            continue
        by_id[i] = d
        ids.append(i)
    for i in dup:
        deferred.append({"id": i, "reason": "duplicate_id"})
    ids = [i for i in ids if i not in dup]
    pending_ids, soon, ignored = set(), [], []
    for p in pending:
        pid = None if p.get("id") is None else str(p.get("id"))
        if pid in by_id or pid in dup:
            ignored.append(pid)  # delivered wins over a stale pending entry
            continue
        pending_ids.add(pid)
        eta = _eta(p.get("eta_min"))
        if eta is not None and eta <= wait_max_min + EPS:
            soon.append((pid, eta))
    deps = {i: [str(x) for x in _list(by_id[i].get("depends_on"))] for i in ids}

    # cycles among delivered shards (self-dependency included)
    state, cyclic = {}, set()

    def visit(i, stack):
        state[i] = 1
        stack.append(i)
        for x in deps[i]:
            if x not in deps:
                continue
            if state.get(x) == 1:
                cyclic.update(stack[stack.index(x):])
            elif x not in state:
                visit(x, stack)
        stack.pop()
        state[i] = 2

    for i in ids:
        if i not in state:
            visit(i, [])
    order, seen = [], set()

    def topo(i):
        if i in seen:
            return
        seen.add(i)
        for x in deps[i]:
            if x in deps and x not in cyclic:
                topo(x)
        order.append(i)

    for i in ids:
        topo(i)
    group, claimed, in_group = [], {}, set()
    for i in order:
        d = by_id[i]
        if i in cyclic:
            deferred.append({"id": i, "reason": "dependency_cycle",
                             "with": sorted(x for x in deps[i] if x in cyclic)})
            continue
        bad = next((x for x in deps[i] if x in pending_ids or (x in by_id and x not in in_group) or x in dup), None)
        if bad:
            deferred.append({"id": i, "reason": "depends_on:%s" % bad})
            continue
        files = [norm_path(f) for f in _list(d.get("files"))]
        foreign = {}
        for f in files:
            o = _owner_of(f, owners)
            if o and i not in o[1]:
                foreign[f] = sorted(o[1])
        if foreign:
            deferred.append({"id": i, "reason": "touches_owned_file", "files": sorted(foreign),
                             "owners": foreign})
            continue
        clash = {f: c for f in files for c in claimed if _overlaps(f, c)}
        if clash:
            deferred.append({"id": i, "reason": "overlap", "files": sorted(clash),
                             "with": sorted({claimed[c] for c in clash.values()})})
            continue
        for f in files:
            claimed[f] = i
        group.append(i)
        in_group.add(i)
    res = {
        "group": group, "deferred": deferred,
        "verify_files": sorted(claimed),
        "wait_min": r1(max(e for _, e in soon)) if soon else 0,
        "wait_for": [p for p, _ in soon],
        "note": "merge in this order, then verify once over the union of files",
    }
    if ignored:
        res["ignored_pending"] = ignored
    return res


def _objs(d, key):
    v = d.get(key)
    if v is None:
        return []
    if not isinstance(v, list) or not all(isinstance(x, dict) for x in v):
        die("%s must be a list of objects" % key)
    return v


def cmd_merge_group(a):
    d = read_json_stdin()
    if not isinstance(d, dict):
        die("stdin must be an object {delivered, pending, owners}")
    owners = d.get("owners") or {}
    if not isinstance(owners, dict):
        die("owners must be an object {path: shard id}")
    w = num(d.get("wait_max_min"))
    return out(merge_group(_objs(d, "delivered"), _objs(d, "pending"), owners,
                           w if w is not None else a.wait_max_min))


# ---- failure location -------------------------------------------------------------------

TEST_DIRS = {"test", "tests", "__tests__", "spec", "specs", "testing"}
SRC_ROOTS = {"src", "lib", "app", "source"}


def _parts(p):
    p = norm_path(p).lstrip("/")
    parts = [x for x in p.split("/") if x]
    return parts[:-1], (parts[-1] if parts else "")


def _dir_overlap(a, b):
    n = 0
    for x, y in zip(a, b):
        if x != y:
            break
        n += 1
    return n


def _stem(base):
    s = base.split(".", 1)[0]
    s = re.sub(r"^test_", "", s)
    s = re.sub(r"(_test|_spec|Test|Tests|Spec)$", "", s)
    return s


def _mirror(da, db):
    """Same directory, or the same once test directories (tests/, __tests__/…) and one leading
    src/lib root are ignored: src/pkg/mod.py <-> tests/pkg/test_mod.py."""
    def key(d):
        d = [x for x in d if x not in TEST_DIRS]
        d = d[1:] if d and d[0] in SRC_ROOTS else d
        return d[1:] if d and d[0] == "main" else d  # Maven: src/main/java <-> src/test/java
    return da == db or key(da) == key(db)


def _same_file(a, b):
    a, b = norm_path(a), norm_path(b)
    if a == b:
        return True
    if a.startswith("/") != b.startswith("/"):  # absolute vs repo-relative
        rel, ab = (a, b) if b.startswith("/") else (b, a)
        return ab.endswith("/" + rel)
    return False


def _score(changed, failure):
    if _same_file(changed, failure):
        return 1000
    dc, bc = _parts(changed)
    df, bf = _parts(failure)
    ov = _dir_overlap(dc, df)
    if ov < 2:
        ov = 0  # sharing only the top-level directory (src/, lib/ ...) proves nothing
    if _stem(bc) and _stem(bc) == _stem(bf):
        if _mirror(dc, df):
            return 800 + ov
        return ov + 0.5 if ov else 0  # same name in an unrelated directory: only a tie-breaker
    return ov


def locate(group, failures):
    """Map failing files/tests to the shard(s) whose changes most plausibly caused them:
    exact file > test file of a changed file in the same or mirrored directory > deepest shared
    directory. Ties below a test-pair match are unresolved and bisected among the tied shards."""
    blame, unresolved = {}, []
    ids = [str(g.get("id")) for g in group]
    for fpath in failures:
        best, score = [], 0
        for gid, g in zip(ids, group):
            s = max([_score(c, fpath) for c in _list(g.get("files"))] or [0])
            if s > score + EPS:
                best, score = [gid], s
            elif abs(s - score) <= EPS and s > 0:
                best.append(gid)
        if score <= EPS or (len(best) > 1 and score < 800):
            unresolved.append({"failure": fpath, "candidates": best})
        else:
            for b in best:
                blame.setdefault(b, []).append(fpath)
    culprits = sorted(blame)
    res = {"culprits": culprits, "evidence": blame,
           "clean": [i for i in ids if i not in culprits], "unresolved": unresolved}
    if unresolved:
        tied = []
        for u in unresolved:
            tied += [c for c in u["candidates"] if c not in culprits and c not in tied]
        if any(not u["candidates"] for u in unresolved):
            tied = list(ids)  # nothing points anywhere: every shard is a suspect
        pool = tied or [i for i in ids if i not in culprits] or list(ids)
        res["next"] = {"action": "bisect", "suspects": pool, "revert_and_retest": pool[: (len(pool) + 1) // 2]}
    else:
        res["next"] = {"action": "fix_or_revert_culprits", "merge_others": res["clean"]}
    return res


def cmd_locate(a):
    d = read_json_stdin()
    if not isinstance(d, dict):
        die("stdin must be an object {group, failures}")
    group = _objs(d, "group")
    if any(g.get("id") is None for g in group):
        die("every group entry needs an id")
    failures = d.get("failures") or []
    if not isinstance(failures, list) or not all(isinstance(f, str) for f in failures):
        die("failures must be a list of paths")
    return out(locate(group, failures))


# =====================================================================================

def parse_now(s):
    if not s:
        return datetime.now(timezone.utc)
    d = parse_ts(s)
    if d is None:
        die("--now is not an ISO time: %r" % s)
    return d


def _typed(kind, lo, strict):
    def conv(v):
        try:
            x = kind(v)
        except ValueError:
            raise argparse.ArgumentTypeError("not a number: %r" % v)
        if not math.isfinite(x) or (x <= lo if strict else x < lo):
            raise argparse.ArgumentTypeError("must be %s %g" % (">" if strict else ">=", lo))
        return x
    return conv


POS_F, NONNEG_F = _typed(float, 0, True), _typed(float, 0, False)
POS_I, NONNEG_I = _typed(int, 0, True), _typed(int, 0, False)


def main(argv=None):
    ap = argparse.ArgumentParser(description="hq scale-out rules (see references/scale-out.md)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("shards", help="how many shards for a workload")
    p.add_argument("--units", type=POS_I, default=0)
    p.add_argument("--unit-min", type=POS_F, required=True)
    p.add_argument("--limit", type=POS_I, required=True,
                   help="concurrency limit (PLAYBOOK remote_concurrency / max_subtasks); no default on purpose")
    p.add_argument("--reserve", type=NONNEG_I, default=0,
                   help="slots kept for planned prerequisite/fix sessions (+1-2 with auto_resplit)")
    p.add_argument("--overhead-min", type=NONNEG_F, default=8.0)
    p.add_argument("--target-min", type=POS_F, default=40.0)
    p.add_argument("--max-overhead-ratio", type=NONNEG_F, default=0.3)
    p.add_argument("--units-file", help="one unit per line, optional TAB weight; prints the assignment")
    p.set_defaults(fn=cmd_shards)

    p = sub.add_parser("straggler", help="ETA per shard, re-split proposals and batch re-plan")
    p.add_argument("--target-min", type=POS_F, default=40.0)
    p.add_argument("--overhead-min", type=NONNEG_F, default=8.0)
    p.add_argument("--free-slots", type=NONNEG_I, default=0)
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

    p = sub.add_parser("merge-group", help="which delivered shards merge together this check-in")
    p.add_argument("--wait-max-min", type=NONNEG_F, default=10.0)
    p.set_defaults(fn=cmd_merge_group)

    p = sub.add_parser("locate", help="which shard broke the group verification")
    p.set_defaults(fn=cmd_locate)

    a = ap.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())

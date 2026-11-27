#!/usr/bin/env python3
"""Summarize hq run records (JSONL, schema v1) into a metrics report.

Usage: metrics.py <file|dir...> [--format md|json] [--last N] [--project NAME]
                  [--since-version V] [--before-version V]
       metrics.py <file|dir...> --check-changelog CHANGELOG.md [--format md|json]
       metrics.py <file|dir...> --export-anon [--raw] [--last N] [--project NAME]
--export-anon prints an anonymized JSON for sharing: records are first reduced to a
whitelist of enum/number/boolean fields (all free text, project and goal dropped, run ids
hashed, timestamps cut to dates), then summarized; --raw also includes those records.
Records of type "monitor" (written by older versions) are ignored.
"""
import argparse
import hashlib
import json
import math
import os
import re
import statistics
import sys
from datetime import datetime, timezone

MIN_N = 3
TIER_ORDER = ["T0", "T1", "T2", "T3", "T4"]


def num(x):
    if isinstance(x, bool) or not isinstance(x, (int, float)):
        return None
    if isinstance(x, float) and not math.isfinite(x):
        return None
    return x


def cnt(x):
    v = num(x)
    return v if v is not None else 0


def parse_ts(s):
    if not isinstance(s, str):
        return None
    try:
        d = datetime.fromisoformat(s.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d


def collect_files(paths):
    files = []
    for p in paths:
        if os.path.isdir(p):
            for root, dirs, names in os.walk(p):
                dirs.sort()
                files += [os.path.join(root, n) for n in sorted(names) if n.endswith(".jsonl")]
        elif os.path.isfile(p):
            files.append(p)
        else:
            sys.exit("metrics.py: path not found: %s" % p)
    return files


def load(files):
    """Return (runs, corrupt). runs: ordered dict run_id -> {'run': dict|None, 'tasks': [..]}

    The same run is often read from two places (.hq/runs and ~/.claude/hq/runs), so records are
    de-duplicated: a task with the same (run_id, task_id), or a merge with the same
    (run_id, batch_id, group_seq), replaces the earlier record; a merge without group_seq is dropped when
    an identical record (same content) was already read. Tasks without task_id are all kept.
    Records of type "monitor" (older versions) and other types are ignored.
    """
    runs, corrupt, seen, same = {}, 0, {}, set()
    for f in files:
        stem = os.path.splitext(os.path.basename(f))[0]
        with open(f, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                if not line.strip():
                    continue
                try:
                    rec = json.loads(line)
                except ValueError:
                    corrupt += 1
                    continue
                if not isinstance(rec, dict):
                    corrupt += 1
                    continue
                t = rec.get("type")
                if t not in ("task", "run", "merge"):
                    continue
                rid = rec.get("run_id")
                rid = rid if isinstance(rid, str) and rid else stem
                r = runs.setdefault(rid, {"run": None, "tasks": [], "merges": []})
                if t == "run":
                    r["run"] = rec
                    continue
                lst = r["tasks"] if t == "task" else r["merges"]
                if t == "task":
                    tid = rec.get("task_id")
                    key = ("task", rid, tid) if isinstance(tid, str) and tid else None
                else:  # v0.11.0: group merges
                    gs, bid = num(rec.get("group_seq")), rec.get("batch_id")
                    key = ("merge", rid, bid if isinstance(bid, str) else None, gs) if gs is not None else None
                if key is None and t == "task":
                    lst.append(rec)
                elif key is None:
                    ck = (t, rid, json.dumps(rec, sort_keys=True, ensure_ascii=False))
                    if ck in same:
                        continue
                    same.add(ck)
                    lst.append(rec)
                elif key in seen:
                    lst[seen[key]] = rec
                else:
                    seen[key] = len(lst)
                    lst.append(rec)
    return runs, corrupt


def run_project(r):
    p = (r["run"] or {}).get("project")
    if isinstance(p, str) and p:
        return p
    for t in r["tasks"]:
        if isinstance(t.get("project"), str) and t["project"]:
            return t["project"]
    return None


def rate(k, n):
    return k / n if n else None


SPARSE_BELOW = 0.5  # a signal that depends on a field present in fewer than half of the records is marked sparse


def wilson(k, n, z=1.96):
    """Wilson score interval (95% by default) for k successes in n trials; None when n == 0."""
    if not n:
        return None
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0.0, c - h), min(1.0, c + h))


def judge(k, n, thr, side):
    """Confidence of a proportion signal against its threshold. side='below': the signal fires when the rate is
    under thr, 'above': when it is over thr. strong = the whole interval is on the firing side of thr."""
    ci = wilson(k, n)
    if ci is None:
        return None, None
    ok = ci[1] < thr if side == "below" else ci[0] > thr
    return ("strong" if ok else "weak"), ci


def med(xs):
    return statistics.median(xs) if xs else None


def mean(xs):
    return sum(xs) / len(xs) if xs else None


def ratio(t):
    a, e = num(t.get("actual_min")), num(t.get("est_min"))
    return a / e if a is not None and e and e > 0 else None


def first_pass(t):
    return t.get("attempts") == 1 and t.get("review_outcome") in ("pass", "pass_with_fixes")


def issue(t, k):
    i = t.get("issues")
    return cnt(i.get(k)) if isinstance(i, dict) else 0


def found_issues(t):
    """v0.3.3 optional field on review tasks: [{severity, origin_task_id}] (non-dict items ignored)."""
    fi = t.get("found_issues")
    return [x for x in fi if isinstance(x, dict)] if isinstance(fi, list) else []


def attribute(tasks):
    """Attribute review tasks' found_issues to their origin tasks within one run.

    Returns (extra, unattributed): extra maps id(origin task) -> {"n": count, "major": bool};
    unattributed counts found issues whose origin_task_id is missing, not a task of this run, or the
    review task itself (a review task's own findings are never counted on itself).
    """
    by_id = {t["task_id"]: t for t in tasks if isinstance(t.get("task_id"), str) and t["task_id"]}
    extra, unattributed = {}, 0
    for t in tasks:
        for x in found_issues(t):
            oid = x.get("origin_task_id")
            o = by_id.get(oid) if isinstance(oid, str) else None
            if o is None or o is t:
                unattributed += 1
                continue
            e = extra.setdefault(id(o), {"n": 0, "major": False})
            e["n"] += 1
            e["major"] = e["major"] or x.get("severity") == "major"
    return extra, unattributed


def attribute_runs(runs):
    """attribute() over every run: (merged extra, {run_id: unattributed})."""
    extra, un = {}, {}
    for rid, r in runs.items():
        e, u = attribute(r["tasks"])
        extra.update(e)
        un[rid] = u
    return extra, un


def integ(t, extra):
    """issues.integration plus the issues review tasks attributed to t."""
    return issue(t, "integration") + (extra or {}).get(id(t), {}).get("n", 0)


def is_major(t, extra=None):
    return (isinstance(t.get("issues"), dict) and t["issues"].get("severity_max") == "major") or \
        (extra or {}).get(id(t), {}).get("major", False)


def quality(tasks, runs, extra=None, unattributed=0):
    """extra/unattributed: from attribute(); found_issues are counted on their origin task's integration column."""
    extra = extra or {}
    n = len(tasks)
    ip = [r["integration_pass"] for r in runs if isinstance((r or {}).get("integration_pass"), bool)]
    attributed = sum(extra[id(t)]["n"] for t in tasks if id(t) in extra)
    return {
        "n": n,
        "insufficient": n < MIN_N,
        "drift_rate": rate(sum(1 for t in tasks if t.get("drift") is True or t.get("scope_violation") is True), n),
        # only verify_pass == true counts; "partial" is a value but not a pass (counted separately)
        "verify_rate": rate(sum(1 for t in tasks if t.get("verify_evidence") and t.get("verify_pass") is True), n),
        "verify_partial": sum(1 for t in tasks if t.get("verify_pass") == "partial"),
        "avg_issues_review": rate(sum(issue(t, "review") for t in tasks), n),
        "avg_issues_integration": rate(sum(integ(t, extra) for t in tasks), n),
        "attributed_issues": attributed,
        "unattributed_found_issues": unattributed,
        "has_found_issues": any(found_issues(t) for t in tasks),
        "avg_issues_user": rate(sum(issue(t, "user") for t in tasks), n),
        "major_issues": sum(1 for t in tasks if is_major(t, extra)),
        "rework_rate": rate(sum(1 for t in tasks if t.get("review_outcome") in ("rework", "failed")), n),
        "integration_pass_rate": rate(sum(ip), len(ip)),
    }


SCORE_DIMS = ("scope", "ambiguity", "context", "risk", "verify")
REVIEW_OUTCOMES = ("pass", "pass_with_fixes", "rework", "failed")
VERIFY_LEVELS = ("doc", "code", "high", "e2e")
IR_TRIGGERS = ("high", "tier", "lines", "assist_lines", "other")


def score_val(t, d):
    s = t.get("score")
    v = num(s.get(d)) if isinstance(s, dict) else None
    return int(v) if v is not None and v in (0, 1, 2) else None


def ir_rec(t):
    """The independent_review record when it is a dict with a boolean `ran`, else None."""
    r = t.get("independent_review")
    return r if isinstance(r, dict) and isinstance(r.get("ran"), bool) else None


# field -> "has a usable value" (a missing / null / wrong-typed field counts as absent)
VALID = {
    "est_min": lambda t: num(t.get("est_min")) is not None,
    "actual_min": lambda t: num(t.get("actual_min")) is not None,
    "tokens": lambda t: num(t.get("tokens")) is not None,
    "cost_usd": lambda t: num(t.get("cost_usd")) is not None,
    "tier": lambda t: t.get("tier") in TIER_ORDER,
    "verify_level": lambda t: t.get("verify_level") in VERIFY_LEVELS,
    "verify_pass": lambda t: isinstance(t.get("verify_pass"), bool) or t.get("verify_pass") == "partial",
    "review_outcome": lambda t: t.get("review_outcome") in REVIEW_OUTCOMES,
    "attempts": lambda t: num(t.get("attempts")) is not None,
    "issues": lambda t: isinstance(t.get("issues"), dict) and any(num(t["issues"].get(k)) is not None for k in ("review", "integration", "user")),
    "score": lambda t: any(score_val(t, d) is not None for d in SCORE_DIMS),
    "independent_review": lambda t: ir_rec(t) is not None,
    "review_wait_min": lambda t: num(t.get("review_wait_min")) is not None and t["review_wait_min"] >= 0,
}


def cov_frac(ts, fields):
    """Share of tasks that have a usable value for every one of `fields`; None when there are no tasks."""
    return rate(sum(1 for t in ts if all(VALID[k](t) for k in fields)), len(ts))


def coverage(tasks):
    n = len(tasks)
    fields = {}
    for k in VALID:
        c = sum(1 for t in tasks if VALID[k](t))
        fields[k] = {"n": c, "rate": rate(c, n), "sparse": n > 0 and c / n < SPARSE_BELOW}
    return {"tasks": n, "fields": fields,
            "joint": {"est_min+actual_min": cov_frac(tasks, ("est_min", "actual_min")),
                      "attempts+review_outcome": cov_frac(tasks, ("attempts", "review_outcome"))}}


def normalized_ratios(runs, skip=frozenset()):
    """id(task) -> actual/est divided by the median actual/est of all tasks (all tiers) of the same run.
    Tasks in `skip` (runs with contradictory time data) are left out."""
    out = {}
    for r in runs.values():
        rs = [(t, ratio(t)) for t in r["tasks"] if id(t) not in skip and ratio(t) is not None]
        m = med([x for _, x in rs])
        if m is None or m <= 0:  # zero / negative median (bad actual_min): normalizing would flip or blow up
            continue
        for t, x in rs:
            out[id(t)] = x / m
    return out


def group(tasks, keyf, skip=frozenset(), norm=None):
    """skip: id()s of tasks from runs with contradictory time data; left out of actual/est only.
    norm: normalized_ratios(); fills the risk=low / run-normalized actual/est fields."""
    norm = norm or {}
    g = {}
    for t in tasks:
        g.setdefault(keyf(t), []).append(t)
    out = []
    for k in sorted(g):
        ts = g[k]
        n = len(ts)
        toks = [num(t.get("tokens")) for t in ts if num(t.get("tokens")) is not None]
        cost = [num(t.get("cost_usd")) for t in ts if num(t.get("cost_usd")) is not None]
        rs = [ratio(t) for t in ts if id(t) not in skip and ratio(t) is not None]
        fpk = sum(1 for t in ts if first_pass(t))
        low = [t for t in ts if t.get("risk") == "low"]
        low_norm = [norm[id(t)] for t in low if norm.get(id(t)) is not None]
        lfk = sum(1 for t in low if first_pass(t))
        out.append({
            "key": k, "n": n, "insufficient": n < MIN_N,
            "cost_n": len(cost), "tokens_n": len(toks),
            "first_pass_rate": rate(fpk, n), "first_pass_k": fpk, "first_pass_ci": wilson(fpk, n),
            "low_n": len(low), "low_first_pass_k": lfk, "low_first_pass_rate": rate(lfk, len(low)),
            "low_norm_ratio_median": med(low_norm), "low_norm_ratio_n": len(low_norm),
            "cov_time": cov_frac(ts, ("est_min", "actual_min")),
            "cov_first_pass": cov_frac(ts, ("attempts", "review_outcome")),
            "escalation_rate": rate(sum(1 for t in ts if isinstance(t.get("tier_changes"), list) and t["tier_changes"]), n),
            "handoff_rate": rate(sum(1 for t in ts if cnt(t.get("handoffs")) > 0), n),
            "avg_cost_usd": mean(cost), "avg_tokens": mean(toks),
            "ratio_median": med(rs), "ratio_n": len(rs),
            "ratio_excluded": sum(1 for t in ts if id(t) in skip and ratio(t) is not None),
        })
    return out


def cost_by_kind(tasks):
    g = {}
    for t in tasks:
        k = t.get("kind") if isinstance(t.get("kind"), str) else "unknown"
        g.setdefault(k, []).append(t)
    out = []
    for k in sorted(g):
        ts = g[k]
        toks = [num(t.get("tokens")) for t in ts if num(t.get("tokens")) is not None]
        both = [(num(t["cost_usd"]), num(t["est_min"])) for t in ts
                if num(t.get("cost_usd")) is not None and num(t.get("est_min")) and num(t["est_min"]) > 0]
        est = sum(e for _, e in both)
        out.append({"key": k, "n": len(ts), "insufficient": len(ts) < MIN_N, "avg_tokens": mean(toks),
                    "tokens_n": len(toks), "cost_n": len(both),
                    "cost_per_est_min": (sum(c for c, _ in both) / est) if est else None})
    return out


SPEEDUP_TOL = 1.1  # allowed slack over max_concurrency (rounding of minutes)


def efficiency(rid, r):
    run, ts = r["run"] or {}, r["tasks"]
    wall, crit = num(run.get("wall_min")), num(run.get("critical_path_min"))
    acts = [num(t.get("actual_min")) for t in ts if num(t.get("actual_min")) is not None]
    declared = num(run.get("tasks"))
    conc = num(run.get("max_concurrency"))
    speedup = sum(acts) / wall if acts and wall else None
    # Impossible combinations mean actual_min was measured differently (e.g. including review/merge waits)
    problems = []
    if speedup is not None and conc and speedup > conc * SPEEDUP_TOL:
        problems.append("speedup>max_concurrency")
    if wall and any(a > wall for a in acts):
        problems.append("task>wall")
    waits = [t["review_wait_min"] for t in ts if VALID["review_wait_min"](t)]
    return {
        "run_id": rid, "tasks": len(ts),
        "actual_cov": rate(len(acts), len(ts)),
        "wait_n": len(waits), "wait_median": med(waits), "wait_max": max(waits) if waits else None,
        "missing_records": max(0, declared - len(ts)) if declared is not None else None,
        "wall_over_critical": wall / crit if wall is not None and crit else None,
        "speedup": speedup,
        # best speedup the task graph allowed: total work / critical path
        "speedup_ceiling": sum(acts) / crit if acts and crit else None,
        "max_concurrency": conc,
        "throttle_events": num(run.get("throttle_events")),
        "inconsistent": problems,
    }


def adjust(tasks):
    esc = [t for t in tasks if isinstance(t.get("tier_changes"), list) and t["tier_changes"]]
    return {
        "escalated": len(esc),
        "escalated_after_checkpoint_rate": rate(sum(1 for t in esc if cnt(t.get("checkpoints")) > 0), len(esc)),
        "checkpoints": sum(cnt(t.get("checkpoints")) for t in tasks),
        "handoffs": sum(cnt(t.get("handoffs")) for t in tasks),
        "derived_tasks": sum(cnt(t.get("derived_tasks")) for t in tasks),
        "user_manual_adjust": sum(1 for t in tasks if t.get("user_manual_adjust") is True),
    }


def fixed(x):
    v = x.get("fixed_in")
    return isinstance(v, str) and bool(v.strip())


def followups(tasks):
    """v0.3.3 optional field followups: [{desc, fixed_in}]; fixed_in null/empty/missing = still open."""
    items = [(t, x) for t in tasks for x in (t.get("followups") if isinstance(t.get("followups"), list) else [])
             if isinstance(x, dict)]
    open_ = [(t, x) for t, x in items if not fixed(x)]
    return {"total": len(items), "open": len(open_), "fixed": len(items) - len(open_),
            "open_items": [{"run_id": t.get("run_id"), "task_id": t.get("task_id"),
                            "desc": x["desc"] if isinstance(x.get("desc"), str) else None} for t, x in open_]}


def plan_accuracy(tasks):
    """Tasks executed from a /hq-plan backlog carry plan_tier (the planned estimate); tier is what was used."""
    ts = [t for t in tasks if t.get("plan_tier") in TIER_ORDER and t.get("tier") in TIER_ORDER]
    n = len(ts)
    d = [TIER_ORDER.index(t["tier"]) - TIER_ORDER.index(t["plan_tier"]) for t in ts]
    return {
        "n": n, "insufficient": n < MIN_N,
        "cov_tier": cov_frac([t for t in tasks if t.get("plan_tier") in TIER_ORDER], ("tier",)),
        "same_rate": rate(sum(1 for x in d if x == 0), n),
        "under_rate": rate(sum(1 for x in d if x > 0), n),  # plan estimated lower than needed
        "over_rate": rate(sum(1 for x in d if x < 0), n),
        "under_k": sum(1 for x in d if x > 0), "over_k": sum(1 for x in d if x < 0),
        "first_pass_rate": rate(sum(1 for t in ts if first_pass(t)), n),
    }


# ---------- scale-out (v0.11.0): shards, layered verification, group merges ----------
DEFAULT_TARGET_MIN = 40
DEFAULT_OVERHEAD_MIN = 8
DEFAULT_MAX_OVERHEAD_RATIO = 0.3
EPS = 1e-9  # tolerance for "exactly at the threshold" float comparisons


def is_shard(t):
    return isinstance(t.get("shard_group"), str) or num(t.get("units_planned")) is not None


def suggest_shards(units, unit_min, overhead_min, target_min, limit, reserve=0,
                   max_overhead_ratio=DEFAULT_MAX_OVERHEAD_RATIO):
    """Same formula as scale.py shard_plan (tests/test_metrics_scaleout.py checks they agree):
    n = min(limit - reserve, ceil(work / target), units), then fewer shards while the fixed overhead
    exceeds max_overhead_ratio of a shard. None when the inputs can't give a plan."""
    if not units or units <= 0 or unit_min is None or unit_min <= 0 or not target_min or target_min <= 0 or not limit:
        return None
    work = units * unit_min
    by_target = max(1, int(math.ceil(round(work / target_min, 9))))
    usable = max(1, int(limit) - int(reserve))
    n = max(1, min(usable, by_target, int(units)))
    while n > 1 and overhead_min / (work / n + overhead_min) > max_overhead_ratio + EPS:
        n -= 1
    return n


def shard_units(t):
    u = num(t.get("units_actual"))
    return u if u else num(t.get("units_planned"))


def scale_out(rid, r):
    run, ts = r["run"] or {}, r["tasks"]
    sh = [t for t in ts if is_shard(t)]
    merges = r.get("merges") or []
    if not sh and not merges:
        return None
    acts = [num(t.get("actual_min")) for t in sh if num(t.get("actual_min")) is not None]
    longest = max(acts) if acts else None
    med_ = med(acts)
    limit, peak = num(run.get("concurrency_limit")), num(run.get("max_concurrency"))
    errs, unit_actual = [], []
    for t in sh:
        a, u, e = num(t.get("actual_min")), shard_units(t), num(t.get("unit_min_est"))
        if a is None or not u or u <= 0:
            continue
        ua = max(0.0, a - (num(t.get("overhead_min")) or 0)) / u
        unit_actual.append(ua)
        if e and e > 0:
            errs.append(ua / e - 1)
    # full test runs: hq-side (merge records) + worker-side (test_scope == full)
    full, acc, covered = [], 0, []
    for m in merges:
        k = len(m["shards"]) if isinstance(m.get("shards"), list) else cnt(m.get("shards_n"))
        acc += k
        if m.get("full_test") is True:
            full.append(num(m.get("full_test_min")))
            covered.append(acc)
            acc = 0
    worker_full = [t for t in sh if t.get("test_scope") == "full"]
    full_n = len(full) + len(worker_full)
    full_min = [x for x in full if x is not None] + [num(t.get("test_min")) for t in worker_full if num(t.get("test_min")) is not None]
    groups = [len(m["shards"]) if isinstance(m.get("shards"), list) else cnt(m.get("shards_n")) for m in merges]
    units_total = sum(cnt(shard_units(t)) for t in sh)
    target = num(run.get("target_shard_min")) or DEFAULT_TARGET_MIN
    ov = med([num(t.get("overhead_min")) for t in sh if num(t.get("overhead_min")) is not None])
    ov = ov if ov is not None else DEFAULT_OVERHEAD_MIN  # a measured 0 stays 0
    reserve = num(run.get("reserved_slots"))
    reserve = max(0, int(reserve)) if reserve is not None else 0
    mor = num(run.get("max_overhead_ratio"))
    mor = mor if mor is not None and mor >= 0 else DEFAULT_MAX_OVERHEAD_RATIO  # 0 is a valid cap, as in scale.py
    return {
        "run_id": rid, "shards": len(sh),
        "parallel_efficiency": sum(acts) / (len(acts) * longest) if acts and longest else None,
        "straggler_ratio": longest / med_ if longest and med_ else None,
        "concurrency_utilization": peak / limit if peak is not None and limit else None,
        "unit_est_error_median": med([abs(x) for x in errs]), "unit_est_bias_median": med(errs), "unit_est_n": len(errs),
        "resplit": sum(1 for t in sh if t.get("resplit") is True),
        "test_related": sum(1 for t in sh if t.get("test_scope") == "related"),
        "full_tests": full_n, "full_tests_hq": len(full), "full_tests_worker": len(worker_full),
        "full_test_min": sum(full_min) if full_min else None,
        "shards_per_full_test": mean(covered) if covered else None,
        "merge_groups": len(merges), "shards_per_group": mean(groups) if groups else None,
        "verify_runs": sum(cnt(m.get("verify_runs")) for m in merges),
        "concurrency_limit": limit, "reserved_slots": reserve, "max_overhead_ratio": mor,
        "suggest_shards": suggest_shards(units_total, med(unit_actual), ov, target, int(limit), reserve, mor)
                          if units_total and unit_actual and limit and limit >= 1 else None,
    }


def scale_signals(sc, add):
    for x in sc:
        scope = "run %s" % x["run_id"]
        n = x["shards"]
        if n < 2:
            continue
        u = x["concurrency_utilization"]
        if u is not None and u < 0.5 - EPS and x["concurrency_limit"] and x["concurrency_limit"] > n:
            msg = "并发利用率 %.0f%% (<50%%)" % (u * 100)
            if x["suggest_shards"] and x["suggest_shards"] > n:
                msg += "，同类任务下次切成 %d 片（按实测单元耗时和上限 %d 计算）" % (x["suggest_shards"], x["concurrency_limit"])
            add(scope, msg, n)
        if x["straggler_ratio"] is not None and x["straggler_ratio"] > 2 + EPS:
            add(scope, "掉队比 %.2f (>2)：按工作单元清单均匀切，并在巡检时对掉队片再拆" % x["straggler_ratio"], n)
        if x["full_tests"] >= 2 and x["full_tests"] > n * 0.5 + EPS:
            add(scope, "全量测试 %d 次 / %d 片（>0.5 次每片）：子会话只跑关联测试，全量测试改成每 %d 片合入后跑一次"
                % (x["full_tests"], n, max(2, min(n, 4))), n)
        if x["unit_est_error_median"] is not None and x["unit_est_n"] >= 3 and x["unit_est_error_median"] > 0.5 + EPS:
            add(scope, "单元耗时估算误差中位数 %.0f%% (>50%%)：开工前先跑小样本测单元耗时" % (x["unit_est_error_median"] * 100), x["unit_est_n"])


FULL_PASS_FLOOR = 0.8  # "一次通过率 100%" counts as strong only when the interval's lower bound is above this
DOWNGRADE_RATIO = 0.7  # downgrade hint: run-normalized actual/est median of risk=low tasks below this


def make_add(out):
    """add(scope, msg, n, prop=(k, n, thr, side), deps=[(field, coverage)]) appends a signal.
    prop adds confidence/ci (Wilson 95% vs thr); deps adds data='sparse' when a needed field covers < 50%."""
    def add(scope, msg, n, prop=None, deps=()):
        sig = {"scope": scope, "message": msg, "n": n}
        if prop:
            conf, ci = judge(*prop)
            if conf:
                sig.update(confidence=conf, ci=[ci[0], ci[1]], threshold=prop[2])
        low = [(k, v) for k, v in deps if v is not None and v < SPARSE_BELOW]
        if low:
            k, v = min(low, key=lambda x: x[1])
            sig.update(data="sparse", data_field=k, data_coverage=v)
        out.append(sig)
    return add


def signals(tiers, models, overall_ratio, effs, plan=None, scale=None, cov=None):
    s = []
    add = make_add(s)
    jt = (cov or {}).get("joint", {})
    for label, groups in (("tier", tiers), ("model/effort", models)):
        for g in groups:
            fp, n, rm = g["first_pass_rate"], g["n"], g["ratio_median"]
            sc = "%s %s" % (label, g["key"])
            d_fp = [("attempts+review_outcome", g.get("cov_first_pass"))]
            d_tm = [("est_min+actual_min", g.get("cov_time"))]
            if n >= 3 and fp is not None and fp < 0.6:
                add(sc, "一次通过率 %.0f%% (<60%%)" % (fp * 100), n, prop=(g["first_pass_k"], n, 0.6, "below"), deps=d_fp)
            # 降档（v0.3.3）：只看 risk=low 的任务；actual/est 先除以所在 run 全部任务的中位数做归一化，
            # 避免把“整次运行估时偏保守”读成“档位过高”。1e-9：恰好 0.7 的浮点误差不算触发
            ln, lk, lnn, lrm = g["low_n"], g["low_first_pass_k"], g["low_norm_ratio_n"], g["low_norm_ratio_median"]
            if lnn >= 5 and ln and lk == ln and lrm is not None and lrm < DOWNGRADE_RATIO - 1e-9:
                add(sc, "risk=low 任务一次通过率 100%%，归一化 actual/est 中位数 %.2f (<0.7)，可能存在降档空间" % lrm, ln,
                    prop=(lk, ln, FULL_PASS_FLOOR, "above"), deps=d_fp + d_tm)
            if rm is not None and g["ratio_n"] >= 3 and rm > 1.5:
                add(sc, "actual/est 用时比中位数 %.2f (>1.5)，估时偏乐观" % rm, g["ratio_n"], deps=d_tm)
    if plan and plan["n"] >= 5:
        if plan["under_rate"] is not None and plan["under_rate"] > 0.3:
            add("plan", "%.0f%% 的计划任务实际用了比预估更高的档位 (>30%%)，/hq-plan 打分偏低" % (plan["under_rate"] * 100), plan["n"],
                prop=(plan["under_k"], plan["n"], 0.3, "above"), deps=[("tier", plan.get("cov_tier"))])
        if plan["over_rate"] is not None and plan["over_rate"] > 0.3:
            add("plan", "%.0f%% 的计划任务实际用了比预估更低的档位 (>30%%)，/hq-plan 打分偏高" % (plan["over_rate"] * 100), plan["n"],
                prop=(plan["over_k"], plan["n"], 0.3, "above"), deps=[("tier", plan.get("cov_tier"))])
    om, on = overall_ratio
    if om is not None and on >= 3 and om > 1.5:
        add("overall", "actual/est 用时比中位数 %.2f (>1.5)，估时偏乐观" % om, on,
            deps=[("est_min+actual_min", jt.get("est_min+actual_min"))])
    for e in effs:
        if e["tasks"] < 3:
            continue
        if e["inconsistent"]:
            add("run %s" % e["run_id"], "时间数据矛盾（%s），该 run 的加速比不可信，先核对 actual_min 口径"
                % ", ".join(e["inconsistent"]), e["tasks"])
            continue
        # only flag low speedup when the task graph left room to parallelize
        if (e["speedup"] is not None and e["speedup"] < 1.3
                and e["speedup_ceiling"] is not None and e["speedup_ceiling"] >= 1.3):
            add("run %s" % e["run_id"], "并行加速比 %.2f (<1.3)，而任务图允许的上限为 %.2f"
                % (e["speedup"], e["speedup_ceiling"]), e["tasks"], deps=[("actual_min", e.get("actual_cov"))])
    scale_signals(scale or [], add)
    return s


# ---------- v0.11.0: plugin versions, rule flags, verify-level escapes, recommendations ----------
VER_RE = re.compile(r"^\[?v?(\d+)\.(\d+)\.(\d+)", re.I)


def vtuple(v):
    m = VER_RE.match(v.strip()) if isinstance(v, str) else None
    return tuple(int(x) for x in m.groups()) if m else None


def vnorm(v):
    """'v0.11.0' / '0.11.0' / '[0.11.0]' -> '0.11.0'; None when unparseable."""
    t = vtuple(v)
    return ".".join(str(x) for x in t) if t else None


def run_version(r):
    """The plugin version the run was executed under: plugin_version_at_start (v0.3.3) when it parses,
    else plugin_version (older records only have this one, and it meant the version in effect).
    When neither parses, the first non-empty string of the two (e.g. "dev"), else None."""
    run = r["run"] or {}
    vals = [run[k] for k in ("plugin_version_at_start", "plugin_version") if isinstance(run.get(k), str) and run[k].strip()]
    for v in vals:
        if vtuple(v):
            return v
    return vals[0] if vals else None


def filter_versions(runs, since=None, before=None):
    """since: keep runs whose version in effect (run_version) >= since; before: < before. Runs without a
    parseable version are dropped when either bound is given (they can't be placed before/after).
    An unparseable bound raises ValueError (callers report it instead of silently ignoring it)."""
    if not since and not before:
        return runs
    lo, hi = vtuple(since) if since else None, vtuple(before) if before else None
    if (since and lo is None) or (before and hi is None):
        raise ValueError("cannot parse version: %s" % (since if since and lo is None else before))
    out = {}
    for k, r in runs.items():
        v = vtuple(run_version(r))
        if v is None or (lo and v < lo) or (hi and v >= hi):
            continue
        out[k] = r
    return out


def by_version(runs, extra=None, skip=frozenset()):
    """Rows per version in effect, normalized ('v0.11.0' and '0.11.0' are one row); skip: tasks of runs
    with contradictory time data, left out of ratio_median as in by_tier."""
    g = {}
    for rid, r in runs.items():
        v = run_version(r)
        g.setdefault(vnorm(v) or v or "unknown", []).append(r)
    rows = []
    for v in sorted(g, key=lambda x: (vtuple(x) is None, vtuple(x) or (0,), x)):
        rs = g[v]
        ts = [t for r in rs for t in r["tasks"]]
        q = quality(ts, [r["run"] or {} for r in rs], extra)
        rr = [ratio(t) for t in ts if id(t) not in skip and ratio(t) is not None]
        cost = [num(t.get("cost_usd")) for t in ts if num(t.get("cost_usd")) is not None]
        rows.append({"key": v, "runs": len(rs), "n": len(ts), "insufficient": len(ts) < MIN_N,
                     "first_pass_rate": rate(sum(1 for t in ts if first_pass(t)), len(ts)),
                     "rework_rate": q["rework_rate"], "drift_rate": q["drift_rate"], "verify_rate": q["verify_rate"],
                     "verify_partial": q["verify_partial"],
                     "escaped_per_task": rate(sum(integ(t, extra) + issue(t, "user") for t in ts), len(ts)),
                     "ratio_median": med(rr), "ratio_n": len(rr), "avg_cost_usd": mean(cost), "cost_n": len(cost)})
    return rows


# rule markers used to live only in notes; structured `flags` (v0.11.0) wins, notes are a fallback for old data.
# ASCII boundaries: "not rate_limited_at_all" or "x:billing:y" is not a marker (CJK neighbours are fine).
NOTE_FLAG_RE = re.compile(r"(?<![A-Za-z0-9_:])(bias:\+1\((?:tier|effort|cost_low)\)|downgrade:user_allowed\(-\d{1,2}\)"
                          r"|rate_limited|assist_unavailable:[A-Za-z0-9_.-]+|assist_auto_models|effort_env:[A-Za-z0-9_-]+"
                          r"|billing:[A-Za-z0-9_-]+|tier:not-applied)(?![A-Za-z0-9_])")
FLAG_RE = re.compile(r"^[A-Za-z0-9_.:()+-]{1,48}$")
# --export-anon keeps only these flags; a prefixed marker whose suffix is not listed becomes "<prefix>:other"
EXPORT_FLAGS = {"bias:+1(tier)", "bias:+1(effort)", "rate_limited", "assist_auto_models", "tier:not-applied"}
EXPORT_FLAG_SUFFIXES = {
    "billing": {"deepseek", "kimi", "moonshot", "codex", "openai", "anthropic", "claude", "gemini", "other"},
    "effort_env": {"minimal", "low", "medium", "high", "xhigh", "max"},
    "assist_unavailable": {"rate_limited", "cli_missing", "cli_unavailable", "no_key", "missing_key", "auth",
                           "quota", "timeout", "network", "same_as_host", "other"},
}
DOWNGRADE_RE = re.compile(r"^downgrade:user_allowed\(-\d{1,2}\)$")


def export_flag(x):
    """The exported form of one rule marker, or None to drop it (no free text survives)."""
    if x in EXPORT_FLAGS or DOWNGRADE_RE.match(x):
        return x
    pre, sep, suf = x.partition(":")
    if sep and pre in EXPORT_FLAG_SUFFIXES:
        return "%s:%s" % (pre, suf if suf in EXPORT_FLAG_SUFFIXES[pre] else "other")
    return None


def task_flags(t):
    fl = [x for x in t.get("flags") if isinstance(x, str) and FLAG_RE.match(x)] if isinstance(t.get("flags"), list) else []
    if isinstance(t.get("notes"), str):
        fl += NOTE_FLAG_RE.findall(t["notes"])
    out = []
    for x in fl:
        x = "bias:+1(tier)" if x == "bias:+1(cost_low)" else x  # old spelling
        if x not in out:
            out.append(x)
    return out


def by_flag(tasks):
    g, plain = {}, []
    for t in tasks:
        fl = task_flags(t)
        for x in fl:
            g.setdefault(x, []).append(t)
        if not fl:
            plain.append(t)
    if not g:
        return []
    g["(无标记)"] = plain  # baseline to compare flagged tasks against
    rows = []
    for k in sorted(g, key=lambda x: (x == "(无标记)", x)):
        ts = g[k]
        n = len(ts)
        cost = [num(t.get("cost_usd")) for t in ts if num(t.get("cost_usd")) is not None]
        rows.append({"key": k, "n": n, "insufficient": n < MIN_N,
                     "first_pass_rate": rate(sum(1 for t in ts if first_pass(t)), n),
                     "first_pass_k": sum(1 for t in ts if first_pass(t)),
                     "cov_first_pass": cov_frac(ts, ("attempts", "review_outcome")),
                     "rework_rate": rate(sum(1 for t in ts if t.get("review_outcome") in ("rework", "failed")), n),
                     "escalation_rate": rate(sum(1 for t in ts if isinstance(t.get("tier_changes"), list) and t["tier_changes"]), n),
                     "avg_cost_usd": mean(cost)})
    return rows


def by_verify_level(tasks, extra=None):
    """Problems that got past a verification level: found at integration or by the user
    (integration includes issues review tasks attributed to the task via found_issues)."""
    g = {}
    for t in tasks:
        g.setdefault(t["verify_level"] if isinstance(t.get("verify_level"), str) else "unknown", []).append(t)
    rows = []
    for k in sorted(g):
        ts = g[k]
        n = len(ts)
        rows.append({"key": k, "n": n, "insufficient": n < MIN_N,
                     "verify_rate": rate(sum(1 for t in ts if t.get("verify_evidence") and t.get("verify_pass") is True), n),
                     "cov_issues": cov_frac(ts, ("issues",)),
                     "verify_partial": sum(1 for t in ts if t.get("verify_pass") == "partial"),
                     "escaped_integration": rate(sum(integ(t, extra) for t in ts), n),
                     "escaped_user": rate(sum(issue(t, "user") for t in ts), n),
                     "escaped_per_task": rate(sum(integ(t, extra) + issue(t, "user") for t in ts), n),
                     "escaped_major": sum(1 for t in ts if is_major(t, extra)
                                          and integ(t, extra) + issue(t, "user") > 0),
                     "rework_rate": rate(sum(1 for t in ts if t.get("review_outcome") in ("rework", "failed")), n)})
    return rows


def recommendations(runs):
    """Standing mode: was the next batch taken from the previous batch's recommendations?
    Consecutive batches of one standing session = same project, standing_seq k then k+1, ordered by
    (project, started_at, standing_seq): equal or missing started_at falls back to seq order, so file order
    doesn't matter."""
    rs = []
    for rid, r in runs.items():
        run = r["run"] or {}
        if num(run.get("standing_seq")) is None:
            continue
        rs.append((run_project(r) or "", parse_ts(run.get("started_at")) or datetime.min.replace(tzinfo=timezone.utc),
                   run["standing_seq"], run))
    rs.sort(key=lambda x: (x[0], x[1], x[2]))
    offered = accepted = done_claims = 0
    for a, b in zip(rs, rs[1:]):
        if a[0] != b[0] or b[2] != a[2] + 1:
            continue
        if cnt(a[3].get("recommended_next")) > 0:
            offered += 1
            if b[3].get("from_recommendation") is True:
                accepted += 1
    for x in rs:
        if num(x[3].get("recommended_next")) == 0:  # False is not a completion claim
            done_claims += 1
    return {"standing_runs": len(rs), "offered": offered, "accepted": accepted,
            "acceptance_rate": rate(accepted, offered), "completion_claims": done_claims,
            "recommended_total": sum(cnt(x[3].get("recommended_next")) for x in rs)}


def fp_dep(g):
    return ("attempts+review_outcome", g.get("cov_first_pass"))


def extra_signals(add, flags, levels, rec):
    for g in flags:
        if g["n"] >= 5 and g["key"].startswith("bias:+1") and g["first_pass_rate"] == 1 and (g["rework_rate"] or 0) == 0:
            add("flag %s" % g["key"], "规则 9 上调的任务一次通过率 100%%、返工 0：可以小范围实验不上调", g["n"],
                prop=(g["first_pass_k"], g["n"], FULL_PASS_FLOOR, "above"), deps=[fp_dep(g)])
        if g["n"] >= 3 and g["key"].startswith("downgrade:") and g["first_pass_rate"] is not None and g["first_pass_rate"] < 0.6:
            add("flag %s" % g["key"], "规则 11 授权降档的任务一次通过率 %.0f%% (<60%%)：降档代价偏高" % (g["first_pass_rate"] * 100), g["n"],
                prop=(g["first_pass_k"], g["n"], 0.6, "below"), deps=[fp_dep(g)])
    for g in levels:
        d_is = [("issues", g.get("cov_issues"))]
        if g["n"] >= 5 and g["escaped_per_task"] is not None and g["escaped_per_task"] > 0.3:
            add("verify %s" % g["key"], "%.2f 个问题/任务漏到合并或用户环节 (>0.3)：考虑加严这一级的子会话验证" % g["escaped_per_task"], g["n"], deps=d_is)
        if g["escaped_major"]:
            add("verify %s" % g["key"], "%d 个 major 问题漏过了这一级的验证" % g["escaped_major"], g["n"], deps=d_is)
    if rec["offered"] >= 5 and rec["acceptance_rate"] is not None and rec["acceptance_rate"] < 0.3:
        add("standing", "推荐被采纳 %.0f%% (<30%%)：推荐的来源或排序不贴合用户" % (rec["acceptance_rate"] * 100), rec["offered"],
            prop=(rec["accepted"], rec["offered"], 0.3, "below"))


# ---------- structured acceptance criteria in CHANGELOG (`- **验收判定**：` lines) ----------
# EPS tolerance: sum/mean/median are not exact, a value that equals the threshold on paper must compare equal
OPS = {"<=": lambda a, b: a <= b + EPS, ">=": lambda a, b: a >= b - EPS, "<": lambda a, b: a < b - EPS,
       ">": lambda a, b: a > b + EPS, "==": lambda a, b: abs(a - b) <= EPS, "!=": lambda a, b: abs(a - b) > EPS}
EXPR_RE = re.compile(r"^\s*(?P<path>\S+)\s*(?P<op><=|>=|==|!=|<|>)\s*(?P<val>-?\d+(?:\.\d+)?)"
                     r"(?P<opts>(?:\s+(?:n>=\d+|since=\S+|before=\S+))*)\s*$")
AGG = {"median": med, "mean": mean, "max": lambda xs: max(xs) if xs else None,
       "min": lambda xs: min(xs) if xs else None, "sum": lambda xs: sum(xs) if xs else None}
SEG_RE = re.compile(r"^(?P<name>[A-Za-z_][A-Za-z0-9_]*)(?:\[(?P<sel>[^\]]+)\])?$")
# sample size of a selected value: the count that value was computed from, else the row's own size
N_FIELD = {"ratio_median": "ratio_n", "avg_cost_usd": "cost_n", "avg_tokens": "tokens_n", "cost_per_est_min": "cost_n",
           "low_norm_ratio_median": "low_norm_ratio_n", "low_first_pass_rate": "low_n",
           "unit_est_error_median": "unit_est_n", "unit_est_bias_median": "unit_est_n",
           "wait_median": "wait_n", "wait_max": "wait_n", "acceptance_rate": "offered"}
N_KEYS = ("n", "tasks", "shards", "offered")


def _walk(node, segs):
    """Returns (values, n). A [*] segment fans out; [key=val] picks the element whose key (or run_id) matches."""
    cur = [(node, None)]
    leaf = None
    for seg in segs:
        m = SEG_RE.match(seg)
        if not m:
            raise ValueError("bad path segment: %s" % seg)
        leaf = m.group("name")
        nxt = []
        for x, _ in cur:
            if not isinstance(x, dict) or m.group("name") not in x:
                continue
            v = x[m.group("name")]
            sel = m.group("sel")
            if sel is None:
                nxt.append((v, x))
            elif sel == "*" and isinstance(v, list):
                nxt += [(e, e) for e in v]
            elif isinstance(v, list):
                k, _, want = sel.partition("=")
                nxt += [(e, e) for e in v if isinstance(e, dict) and str(e.get(k)) == want]
        cur = nxt
    vals = [num(v) for v, _ in cur if num(v) is not None]
    parents = [p for _, p in cur if isinstance(p, dict)]
    n = None
    if len(cur) == 1 and parents:
        p = parents[0]
        keys = ((N_FIELD[leaf],) if leaf in N_FIELD else ()) + N_KEYS
        n = next((p[k] for k in keys if num(p.get(k)) is not None), None)
    return vals, n


def split_path(path):
    """Split on dots outside [...] so selectors like by_version[key=0.11.0] stay whole."""
    segs, cur, depth = [], "", 0
    for ch in path:
        if ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
        if ch == "." and depth == 0:
            segs.append(cur)
            cur = ""
        else:
            cur += ch
    return segs + [cur]


def eval_expr(expr, rep):
    m = EXPR_RE.match(expr)
    if not m:
        return {"expr": expr, "verdict": "无法解析"}
    path, op, want = m.group("path"), m.group("op"), float(m.group("val"))
    agg = None
    am = re.match(r"^(\w+)\((.+)\)$", path)
    if am and am.group(1) in AGG:
        agg, path = am.group(1), am.group(2)
    try:
        vals, n = _walk(rep, split_path(path))
    except ValueError as e:
        return {"expr": expr, "verdict": "无法解析", "error": str(e)}
    if agg:
        value, n = AGG[agg](vals), len(vals)
    else:
        value = vals[0] if len(vals) == 1 else None
        if n is None:  # the value's object has no size of its own: fall back to the task count
            n = num((rep.get("overview") or {}).get("tasks"))
    need = re.search(r"n>=(\d+)", m.group("opts"))
    need = int(need.group(1)) if need else MIN_N
    res = {"expr": expr, "value": value, "n": n, "need_n": need}
    if value is None or n is None or n < need:
        return dict(res, verdict="样本不足")
    return dict(res, verdict="达到" if OPS[op](value, want) else "未达到")


STATUS_RE = re.compile(r"^(待验证|已验证|已撤回)(?:$|[（(\s，；,;:：])")
OP_CHARS = re.compile(r"<|>|==|!=")
FENCE_RE = re.compile(r"^\s*(`{3,}|~{3,})")


def judge_exprs(text):
    """Backtick fragments of a 验收判定 text that are meant as expressions. A "不适用…" text has none;
    otherwise fragments that parse or contain a comparison are kept (a mention like `scale.py shards`
    is not); when no fragment qualifies they are all kept, so they come out as 无法解析."""
    if re.sub(r"^[\s:：*]+", "", text).startswith("不适用"):
        return []
    frags = re.findall(r"`([^`]+)`", text)
    keep = [x for x in frags if EXPR_RE.match(x) or OP_CHARS.search(x)]
    return keep or frags


def parse_changelog(text):
    """Entries under `### ` headings with their version (`## vX.Y.Z` or `## [X.Y.Z]`; None under 未发布 or an
    unparseable heading), status and 验收判定 expressions (a 验收判定 may continue on following lines up to
    the next `- **`, heading or blank line). Lines inside ``` / ~~~ fences are ignored."""
    entries, ver, cur, fence, judge = [], None, None, None, None

    def flush(cur, judge):
        if cur is not None and judge is not None:
            cur["exprs"] += judge_exprs(judge)

    for line in text.splitlines():
        fm = FENCE_RE.match(line)
        if fm:
            mark = fm.group(1)[0]
            fence = None if fence == mark else (fence or mark)
            continue
        if fence:
            continue
        if line.startswith("## ") or line.startswith("### ") or line.startswith("- **") or not line.strip():
            flush(cur, judge)
            judge = None
        if line.startswith("## "):
            m = VER_RE.match(line[3:].strip())
            ver = ".".join(m.groups()) if m else None
            ver = vnorm(ver) if ver else None
            cur = None
        elif line.startswith("### "):
            cur = {"title": line[4:].strip(), "version": ver, "status": None, "exprs": []}
            entries.append(cur)
        elif cur is not None:
            st = re.match(r"^- \*\*状态\*\*[:：]\s*(.*)$", line)
            if st:
                v = st.group(1).replace("*", "").strip()
                sm = STATUS_RE.match(v)
                cur["status"] = sm.group(1) if sm else (v.split()[0] if v.split() else None)
            jm = re.match(r"^- \*\*验收判定\*\*(.*)$", line)
            if jm:
                judge = jm.group(1)
            elif judge is not None:  # continuation line of a multi-line 验收判定
                judge += " " + line
    flush(cur, judge)
    return entries


def rework_k(runs):
    ts = [t for r in runs.values() for t in r["tasks"]]
    return sum(1 for t in ts if t.get("review_outcome") in ("rework", "failed")), len(ts)


def quality_guard(runs, since, before):
    """Rework rate of runs in [since, before) vs runs < since. Fires when both sides have >= 5 tasks and the
    rate rose by MORE than 5 percentage points (exactly +5pp does not fire); compared in integers."""
    pk, pn = rework_k(filter_versions(runs, None, since))
    qk, qn = rework_k(filter_versions(runs, since, before))
    if pn >= 5 and qn >= 5 and (qk * pn - pk * qn) * 100 > 5 * pn * qn:
        return "返工率 %.0f%% → %.0f%%" % (pk / pn * 100, qk / qn * 100)
    return None


def check_changelog(path, runs, corrupt):
    try:
        with open(path, encoding="utf-8") as fh:
            entries = parse_changelog(fh.read())
    except OSError as e:
        sys.exit("metrics.py: cannot read %s: %s" % (path, e))
    out = []
    for e in entries:
        if e["status"] != "待验证" or not e["exprs"]:
            continue
        rows, bounds = [], []
        for x in e["exprs"]:
            m = EXPR_RE.match(x)
            opts = m.group("opts") if m else ""
            since = re.search(r"since=(\S+)", opts)
            before = re.search(r"before=(\S+)", opts)
            since = since.group(1) if since else e["version"]
            before = before.group(1) if before else None
            if m and not since:
                rows.append({"expr": x, "verdict": "无法解析", "since": None,
                             "error": "no since= and the entry is not under a version heading"})
                continue
            try:
                sub = filter_versions(runs, since, before) if m else runs
            except ValueError as err:
                rows.append({"expr": x, "verdict": "无法解析", "since": since, "error": str(err)})
                continue
            r = eval_expr(x, build(sub, corrupt))
            r["since"] = since
            rows.append(r)
            if m and (since, before) not in bounds:
                bounds.append((since, before))
        # quality guard: rework rate after the change must not rise against the runs before it,
        # checked for every distinct since/before pair of the entry's criteria
        guards = []
        for sb in bounds:
            g = quality_guard(runs, *sb)
            if g:
                guards.append(g if len(bounds) == 1 else "%s（since %s）" % (g, sb[0]))
        guard = "；".join(guards) or None
        vs = [r["verdict"] for r in rows]
        verdict = ("未达到" if guard or "未达到" in vs else "无法解析" if "无法解析" in vs
                   else "达到" if all(v == "达到" for v in vs) else "样本不足")
        out.append({"title": e["title"], "version": e["version"], "verdict": verdict, "quality_guard": guard,
                    "criteria": rows})
    return out


def render_check(res):
    L = ["# CHANGELOG 验收判定", ""]
    if not res:
        return "\n".join(L + ["没有带“验收判定”的待验证条目。"]) + "\n"
    L += table(["条目", "版本", "判定", "依据"], [[r["title"], r["version"] or "未发布", r["verdict"],
                "；".join("%s → %s (值 %s, n=%s, since %s)" % (c["expr"], c["verdict"], f(c.get("value")),
                          c.get("n") if c.get("n") is not None else "-", c.get("since") or "-") for c in r["criteria"])
                + ("；质量变差：" + r["quality_guard"] if r["quality_guard"] else "")] for r in res])
    return "\n".join(L) + "\n"


# ---------- v0.12: score dimensions, independent review, review wait ----------
def esc(t):
    return isinstance(t.get("tier_changes"), list) and bool(t["tier_changes"])


def by_score(tasks):
    """{dimension: [{value, n, first_pass_*, escalation_*}]} over tasks that carry that dimension; {} for old data."""
    out = {}
    for d in SCORE_DIMS:
        rows = []
        for v in (0, 1, 2):
            ts = [t for t in tasks if score_val(t, d) == v]
            if not ts:
                continue
            n = len(ts)
            fk, ek = sum(1 for t in ts if first_pass(t)), sum(1 for t in ts if esc(t))
            rows.append({"value": v, "n": n, "insufficient": n < MIN_N,
                         "first_pass_rate": rate(fk, n), "first_pass_k": fk, "first_pass_ci": wilson(fk, n),
                         "escalation_rate": rate(ek, n), "escalation_k": ek, "escalation_ci": wilson(ek, n)})
        if rows:
            out[d] = rows
    return out


def independent_review(tasks):
    """By trigger over tasks whose independent_review.ran is true; `not_run` counts ran=false records."""
    recs = [ir_rec(t) for t in tasks if ir_rec(t) is not None]
    ran = [r for r in recs if r["ran"]]
    if not recs:
        return {}
    g = {}
    for r in ran:
        k = r.get("trigger") if r.get("trigger") in IR_TRIGGERS else "other"
        g.setdefault(k, []).append(r)
    rows = []
    for k in IR_TRIGGERS:
        if k not in g:
            continue
        rs = g[k]
        n = len(rs)
        found = sum(1 for r in rs if cnt(r.get("findings")) > 0)
        rows.append({"trigger": k, "n": n, "insufficient": n < MIN_N,
                     "found": found, "found_rate": rate(found, n), "found_ci": wilson(found, n),
                     "findings": sum(cnt(r.get("findings")) for r in rs), "major": sum(cnt(r.get("major")) for r in rs)})
    return {"ran": len(ran), "not_run": len(recs) - len(ran), "by_trigger": rows}


def quality_signals(add, score, ir, effs, cov):
    fields = cov["fields"]
    for d, rows in score.items():
        for r in rows:
            others = [x for x in rows if x is not r]
            on = sum(x["n"] for x in others)
            if r["n"] < 5 or not on:
                continue
            orate = sum(x["escalation_k"] for x in others) / on
            if r["escalation_rate"] - orate >= 0.3 - 1e-9:  # tolerance: 0.7 - 0.4 is 0.29999999999999993
                add("score %s=%d" % (d, r["value"]),
                    "维度 %s=%d 的任务升档率偏高（%.0f%%，该维度其他取值 %.0f%%），打分可能低估了这一维"
                    % (d, r["value"], r["escalation_rate"] * 100, orate * 100), r["n"],
                    prop=(r["escalation_k"], r["n"], orate + 0.3 - 1e-9, "above"),
                    deps=[("score", fields["score"]["rate"])])
    for r in (ir or {}).get("by_trigger", []):
        if r["n"] >= 5 and r["found_rate"] is not None and r["found_rate"] < 0.1:
            add("review %s" % r["trigger"], "这一触发条件几乎发现不了问题（%d 次审核 %d 次有发现），可考虑放宽" % (r["n"], r["found"]), r["n"],
                prop=(r["found"], r["n"], 0.1, "below"), deps=[("independent_review", fields["independent_review"]["rate"])])
    for e in effs:
        if e["wait_n"] >= 3 and e["wait_median"] is not None and e["wait_median"] > 15:
            add("run %s" % e["run_id"], "交付后平均 %.0f 分钟才审核（中位数，最长 %.0f 分钟），巡检间隔偏长"
                % (e["wait_median"], e["wait_max"]), e["wait_n"], deps=[("review_wait_min", fields["review_wait_min"]["rate"])])


def build(runs, corrupt):
    ids = list(runs)
    tasks = [t for i in ids for t in runs[i]["tasks"]]
    rr = [runs[i]["run"] or {} for i in ids]
    stamps = []
    for r in rr:
        for k in ("started_at", "ended_at"):
            d = parse_ts(r.get(k))
            if d:
                stamps.append((d, r[k]))
    effs = [efficiency(i, runs[i]) for i in ids]
    # actual_min of runs with contradictory time data is unreliable: keep those tasks out of actual/est
    skip = frozenset(id(t) for e in effs if e["inconsistent"] for t in runs[e["run_id"]]["tasks"])
    norm = normalized_ratios(runs, skip)
    tiers = group(tasks, lambda t: t["tier"] if isinstance(t.get("tier"), str) else "unknown", skip, norm)
    models = group(tasks, lambda t: "%s/%s" % (t["model"] if isinstance(t.get("model"), str) else "unknown",
                                               t["effort"] if isinstance(t.get("effort"), str) else "unknown"), skip, norm)
    s_ = lambda t, k: t[k] if isinstance(t.get(k), str) else "unknown"
    hosts = group(tasks, lambda t: "%s/%s" % (s_(t, "host"), s_(t, "channel")), skip, norm)
    extra, unattr = attribute_runs(runs)
    # 辅助执行者（v0.5.0 可选字段 assist）：null/缺失记为 main（主宿主自己的模型）
    assist = group(tasks, lambda t: "assist:%s/%s" % (t["assist"], s_(t, "tier")) if isinstance(t.get("assist"), str) and t["assist"]
                   else "main/%s" % s_(t, "tier"), skip)
    rs = [ratio(t) for t in tasks if id(t) not in skip and ratio(t) is not None]
    miss = [e["missing_records"] for e in effs if e["missing_records"] is not None]
    plan = plan_accuracy(tasks)
    sc = [x for x in (scale_out(i, runs[i]) for i in ids) if x]
    flags, levels, rec = by_flag(tasks), by_verify_level(tasks, extra), recommendations(runs)
    cov = coverage(tasks)
    sig = signals(tiers, models, (med(rs), len(rs)), effs, plan, sc, cov)
    add = make_add(sig)
    extra_signals(add, flags, levels, rec)
    bs, ir = by_score(tasks), independent_review(tasks)
    quality_signals(add, bs, ir, effs, cov)
    return {
        "overview": {"runs": len(ids), "tasks": len(tasks), "corrupt_lines": corrupt,
                     "missing_task_records": sum(miss) if miss else None,
                     "time_from": min(stamps)[1] if stamps else None, "time_to": max(stamps)[1] if stamps else None},
        "quality": {"overall": quality(tasks, rr, extra, sum(unattr.values())),
                    "per_run": [dict(quality(runs[i]["tasks"], [runs[i]["run"] or {}], extra, unattr[i]), run_id=i)
                                for i in ids]},
        "by_tier": tiers, "by_model": models, "by_host_channel": hosts, "by_assist": assist,
        "efficiency": effs,
        "cost": cost_by_kind(tasks),
        "adjust": adjust(tasks),
        "followups": followups(tasks),
        "autonomy": {"autonomy_stops": sum(cnt(r.get("autonomy_stops")) for r in rr),
                     "decisions": sum(cnt(r.get("decisions")) for r in rr),
                     "user_corrections": sum(cnt(t.get("user_corrections")) for t in tasks)},
        "plan": plan,
        "scale_out": sc,
        "coverage": cov, "by_score": bs, "independent_review": ir,
        "by_version": by_version(runs, extra, skip), "by_flag": flags, "by_verify_level": levels, "recommendations": rec,
        "signals": sig,
    }


def f(v, kind="n"):
    if v is None:
        return "-"
    if kind == "p":
        return "%.1f%%" % (v * 100)
    if kind == "c":
        return "%.4f" % v
    if kind == "d":
        return "%d" % v if float(v).is_integer() else "%.1f" % v
    return "%.2f" % v if not float(v).is_integer() else "%d" % v


def table(head, rows):
    out = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    out += ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]
    return out


def ci_s(ci):
    return "-" if not ci else "%.0f%%–%.0f%%" % (ci[0] * 100, ci[1] * 100)


def sig_notes(s):
    out = ""
    if s.get("confidence") == "weak":
        out += "（弱：95%% 区间 %s 跨过阈值）" % ci_s(s["ci"])
    if s.get("data") == "sparse":
        out += "（数据不足：%s 覆盖 %.0f%%）" % (s["data_field"], s["data_coverage"] * 100)
    return out


def render_md(rep):
    o = rep["overview"]
    L = ["# HQ 指标报告 (schema v1)", "", "## 1. 总览", ""]
    L += table(["run 数", "task 数", "损坏行数", "缺记录任务数", "时间范围"],
               [[o["runs"], o["tasks"], o["corrupt_lines"], f(o["missing_task_records"], "d"),
                 "%s ~ %s" % (o["time_from"] or "-", o["time_to"] or "-")]])
    cv = rep.get("coverage")
    if cv:
        names = {"est_min": "est_min", "actual_min": "actual_min", "tokens": "tokens", "cost_usd": "cost_usd", "tier": "tier",
                 "verify_level": "verify_level", "verify_pass": "verify_pass", "review_outcome": "review_outcome",
                 "attempts": "attempts", "issues": "issues", "score": "score（新）",
                 "independent_review": "independent_review（新）", "review_wait_min": "review_wait_min（新）"}
        L += ["", "## 1b. 字段覆盖率（有有效值的任务占比；< 50% 时依赖该字段的信号标“数据不足”）", ""]
        L += table(["字段", "有值任务数", "覆盖率", "备注"],
                   [[names.get(k, k), v["n"], f(v["rate"], "p"), "数据不足" if v["sparse"] else ""] for k, v in cv["fields"].items()])
    L += ["", "## 2. 质量门槛", ""]
    qo = rep["quality"]["overall"]
    # v0.3.3 columns appear only when the data has them, so old reports look the same
    show_partial, show_attr = bool(qo.get("verify_partial")), bool(qo.get("has_found_issues"))
    qh = (["范围", "n", "漂移率", "验证到位率"] + (["partial 数"] if show_partial else [])
          + ["问题/任务 review", "integration（含审核归因）" if show_attr else "integration"]
          + (["审核归因数", "未归因数"] if show_attr else []) + ["user", "major 数", "返工率", "合并通过率", "备注"])
    def qrow(name, q):
        return ([name, q["n"], f(q["drift_rate"], "p"), f(q["verify_rate"], "p")]
                + ([q["verify_partial"]] if show_partial else [])
                + [f(q["avg_issues_review"]), f(q["avg_issues_integration"])]
                + ([q["attributed_issues"], q["unattributed_found_issues"]] if show_attr else [])
                + [f(q["avg_issues_user"]), q["major_issues"], f(q["rework_rate"], "p"),
                   f(q["integration_pass_rate"], "p"), "样本不足" if q["insufficient"] else ""])
    L += table(qh, [qrow("总体", qo)] + [qrow(q["run_id"], q) for q in rep["quality"]["per_run"]])
    if show_partial:
        L += ["", "验证到位率只算 verify_pass=true；partial（只做了部分验证，如只核对文档、未实机运行）单列，不算到位。"]
    if show_attr:
        L += ["", "integration 含审核任务 found_issues 归到来源任务（同一 run 的 origin_task_id）的问题，不计入审核任务自己；"
              "被归因了 major 问题的来源任务计入 major 数；未归因数是 origin_task_id 缺失、不在本 run 或指向审核任务自己的问题。"
              "若审核任务的 found_issues 和来源任务自己的 issues.integration 都记了同一问题，会重复计数；按约定只记在审核任务里。"]
    gh = ["分组", "n", "有值数 cost/tokens/ratio", "一次通过率", "升档率", "交接率", "平均 cost_usd", "平均 tokens",
          "actual/est 中位数", "备注"]
    def grow(g):
        return [g["key"], g["n"], "%d/%d/%d" % (g["cost_n"], g["tokens_n"], g["ratio_n"]), f(g["first_pass_rate"], "p"), f(g["escalation_rate"], "p"), f(g["handoff_rate"], "p"),
                f(g["avg_cost_usd"]), f(g["avg_tokens"], "d"), f(g["ratio_median"]),
                "；".join(x for x in ("样本不足" if g["insufficient"] else "",
                                     "用时比排除矛盾 run 的 %d 条" % g["ratio_excluded"] if g["ratio_excluded"] else "") if x)]
    gh2 = gh[:4] + ["一次通过率 95% 区间"] + gh[4:]
    def grow2(g):
        r = grow(g)
        return r[:4] + [ci_s(g.get("first_pass_ci"))] + r[4:]
    L += ["", "有值数：平均 cost_usd / 平均 tokens / actual/est 中位数实际用到的任务数；n 大而有值数小时均值不可靠。"]
    L += ["", "## 3a. 按档位", ""] + table(gh2, [grow2(g) for g in rep["by_tier"]])
    L += ["", "## 3b. 按模型/思考深度", ""] + table(gh2, [grow2(g) for g in rep["by_model"]])
    L += ["", "## 3c. 按宿主/通道", ""] + table(gh, [grow(g) for g in rep["by_host_channel"]])
    if any(g["key"].startswith("assist:") for g in rep["by_assist"]):
        L += ["", "## 3d. 辅助执行者 vs 主宿主（按档位；交接率≈被收回给主宿主的比例）", ""] + table(gh, [grow(g) for g in rep["by_assist"]])
    p = rep["plan"]
    if p["n"]:
        L += ["", "## 3e. 计划预估档位 vs 实际（按计划执行的任务，plan_tier）", ""] + table(
            ["n", "一致", "预估偏低", "预估偏高", "一次通过率", "备注"],
            [[p["n"], f(p["same_rate"], "p"), f(p["under_rate"], "p"), f(p["over_rate"], "p"),
              f(p["first_pass_rate"], "p"), "样本不足" if p["insufficient"] else ""]])
    if any(g["key"] != "unknown" for g in rep["by_version"]):
        vh = ["版本", "run 数", "task 数", "一次通过率", "返工率", "漂移率", "验证到位率", "漏网问题/任务", "actual/est 中位数", "平均 cost_usd", "备注"]
        L += ["", "## 3f. 按插件版本（运行时生效的版本：plugin_version_at_start，解析不出时用 plugin_version；"
              "--since-version / --before-version 可只看一段）", ""] + table(vh, [
            [g["key"], g["runs"], g["n"], f(g["first_pass_rate"], "p"), f(g["rework_rate"], "p"), f(g["drift_rate"], "p"),
             f(g["verify_rate"], "p"), f(g["escaped_per_task"]), f(g["ratio_median"]), f(g["avg_cost_usd"]),
             "样本不足" if g["insufficient"] else ""] for g in rep["by_version"]])
    if any(g["key"] != "unknown" for g in rep["by_verify_level"]):
        L += ["", "## 3g. 按验证级别（漏网 = 合并或用户环节才发现的问题）", ""] + table(
            ["级别", "n", "验证到位率", "漏到合并/任务", "漏到用户/任务", "漏网 major", "返工率", "备注"],
            [[g["key"], g["n"], f(g["verify_rate"], "p"), f(g["escaped_integration"]), f(g["escaped_user"]),
              g["escaped_major"], f(g["rework_rate"], "p"), "样本不足" if g["insufficient"] else ""] for g in rep["by_verify_level"]])
    if rep["by_flag"]:
        L += ["", "## 3h. 按规则标记（flags；旧数据从 notes 识别）", ""] + table(
            ["标记", "n", "一次通过率", "返工率", "升档率", "平均 cost_usd", "备注"],
            [[g["key"], g["n"], f(g["first_pass_rate"], "p"), f(g["rework_rate"], "p"), f(g["escalation_rate"], "p"),
              f(g["avg_cost_usd"]), "样本不足" if g["insufficient"] else ""] for g in rep["by_flag"]])
    if rep.get("by_score"):
        L += ["", "## 3i. 按打分维度（score 各维 0-2；升档率高说明这一维打分偏低）", ""]
        L += table(["维度", "取值", "n", "一次通过率", "一次通过率 95% 区间", "升档率", "升档率 95% 区间", "备注"],
                   [[d, r["value"], r["n"], f(r["first_pass_rate"], "p"), ci_s(r["first_pass_ci"]), f(r["escalation_rate"], "p"),
                     ci_s(r["escalation_ci"]), "样本不足" if r["insufficient"] else ""]
                    for d, rows in rep["by_score"].items() for r in rows])
    L += ["", "## 4. 效率", ""]
    has_wait = any(e.get("wait_n") for e in rep["efficiency"])
    L += table(["run", "任务数", "wall/关键路径", "并行加速比", "加速比上限", "max_concurrency", "throttle_events"]
               + (["审核等待中位数(分)", "审核等待最大(分)"] if has_wait else []) + ["备注"],
               [[e["run_id"], e["tasks"], f(e["wall_over_critical"]), f(e["speedup"]), f(e["speedup_ceiling"]),
                 f(e["max_concurrency"], "d"), f(e["throttle_events"], "d")]
                + ([f(e["wait_median"], "d"), f(e["wait_max"], "d")] if has_wait else [])
                + ["数据矛盾：" + ", ".join(e["inconsistent"]) if e["inconsistent"] else ""] for e in rep["efficiency"]])
    if rep.get("scale_out"):
        L += ["", "## 4b. 分片、分层校验与合入（v0.11.0 起的字段；旧数据没有就不出）", ""]
        L += table(["run", "片数", "并行效率", "掉队比", "并发利用率", "单元耗时误差", "再拆", "关联/全量(片内)",
                    "全量测试次数", "全量耗时(分)", "每次全量覆盖片数", "合入组数", "每组片数", "校验次数"],
                   [[x["run_id"], x["shards"], f(x["parallel_efficiency"], "p"), f(x["straggler_ratio"]),
                     f(x["concurrency_utilization"], "p"), f(x["unit_est_error_median"], "p"), x["resplit"],
                     "%d/%d" % (x["test_related"], x["full_tests_worker"]), x["full_tests"], f(x["full_test_min"], "d"),
                     f(x["shards_per_full_test"]), x["merge_groups"], f(x["shards_per_group"]), x["verify_runs"]]
                    for x in rep["scale_out"]])
    L += ["", "## 5. 开销（按 kind）", ""]
    L += table(["kind", "n", "有值数 tokens/cost", "平均 tokens", "每预计分钟成本 (USD)", "备注"],
               [[c["key"], c["n"], "%d/%d" % (c["tokens_n"], c["cost_n"]), f(c["avg_tokens"], "d"),
                 f(c["cost_per_est_min"], "c"), "样本不足" if c["insufficient"] else ""] for c in rep["cost"]])
    a = rep["autonomy"]
    L += ["", "## 6. 自主性", ""] + table(["autonomy_stops", "decisions", "user_corrections"],
                                          [[f(a["autonomy_stops"], "d"), f(a["decisions"], "d"), f(a["user_corrections"], "d")]])
    d = rep["adjust"]
    L += ["", "## 6b. 调档与检查点", ""] + table(
        ["升档任务数", "其中有检查点的比例", "checkpoints", "handoffs", "derived_tasks", "user_manual_adjust"],
        [[d["escalated"], f(d["escalated_after_checkpoint_rate"], "p"), d["checkpoints"], d["handoffs"],
          d["derived_tasks"], d["user_manual_adjust"]]])
    rc = rep["recommendations"]
    if rc["standing_runs"]:
        L += ["", "## 6c. 常驻模式推荐", ""] + table(
            ["常驻批次", "推荐过的批次", "下一批采纳推荐", "采纳率", "推荐总条数", "完工声明"],
            [[rc["standing_runs"], rc["offered"], rc["accepted"], f(rc["acceptance_rate"], "p"),
              rc["recommended_total"], rc["completion_claims"]]])
    ir = rep.get("independent_review")
    if ir:
        L += ["", "## 6d. 独立审核（按触发条件；执行 %d 次，记录了但未执行 %d 次）" % (ir["ran"], ir["not_run"]), ""]
        L += table(["trigger", "触发次数", "有发现", "有发现比例", "有发现比例 95% 区间", "发现总数", "其中 major", "备注"],
                   [[r["trigger"], r["n"], r["found"], f(r["found_rate"], "p"), ci_s(r["found_ci"]), r["findings"], r["major"],
                     "样本不足" if r["insufficient"] else ""] for r in ir["by_trigger"]])
    fu = rep.get("followups") or {}
    if fu.get("total"):
        L += ["", "## 6e. 待修追踪（task 的 followups；fixed_in 为空算未修）", ""]
        L += table(["待修项总数", "未修", "已修"], [[fu["total"], fu["open"], fu["fixed"]]])
        if fu["open_items"]:
            L += [""] + ["- [%s/%s] %s" % (x["run_id"] or "-", x["task_id"] or "-", x["desc"] or "-") for x in fu["open_items"]]
    L += ["", "## 7. 信号", ""]
    L += ["- [%s] %s（n=%d）%s" % (s["scope"], s["message"], s["n"], sig_notes(s)) for s in rep["signals"]] or ["- 无"]
    return "\n".join(L) + "\n"


# ---------- anonymized export (whitelist only; anything not listed is dropped) ----------
ENUMS = {
    "kind": {"code", "docs", "research", "review", "config"},
    "risk": {"low", "med", "high"},
    "tier": {"T0", "T1", "T2", "T3", "T4"},
    "host": {"claude-code", "codex", "dsh", "opencode", "cursor", "gemini", "other"},
    "channel": {"A", "B", "C", "D", "W", "main"},
    "verify_level": {"doc", "code", "high", "e2e"},
    "review_outcome": {"pass", "pass_with_fixes", "rework", "failed"},
}
SEVERITY = {"none", "minor", "major"}
EFFORTS = {"minimal", "low", "medium", "high", "xhigh", "max", "none"}
TOKEN_RE = re.compile(r"^[A-Za-z0-9._:/@+-]{1,64}$")  # model / effort names
TASK_NUMS = ("tier_score", "est_min", "actual_min", "tokens", "cost_usd", "attempts", "handoffs",
             "derived_tasks", "checkpoints", "user_corrections",
             "units_planned", "units_actual", "unit_min_est", "overhead_min", "test_min", "rework_rounds",
             "review_wait_min")
TASK_BOOLS = ("user_manual_adjust", "scope_violation", "drift", "verify_pass", "resplit")
RUN_NUMS = ("wall_min", "critical_path_min", "tasks", "max_concurrency", "throttle_events",
            "autonomy_stops", "decisions", "standing_seq", "recommended_next", "concurrency_limit",
            "target_shard_min", "reserved_slots", "max_overhead_ratio")
TASK_TYPES = {"patrol", "dev", "docs", "test", "research", "review", "config", "code", "*"}
RUN_BOOLS = ("integration_pass", "from_recommendation")


def anon_id(rid):
    return "r-" + hashlib.sha256(("hq-anon:" + rid).encode("utf-8")).hexdigest()[:10]


def a_enum(k, v):
    return None if v is None else (v if isinstance(v, str) and v in ENUMS[k] else "other")


def a_set(v, allowed):
    """Enum value from a closed set; anything else (incl. lists / dicts) becomes "other"."""
    return None if v is None else (v if isinstance(v, str) and v in allowed else "other")


def a_token(v):
    return None if v is None else (v if isinstance(v, str) and TOKEN_RE.match(v) else "other")


# only vendor-shaped model names leave the machine ("claude-opus-4-5", "gpt-5.1-codex", "o3", "codex:gpt-5.2");
# a free-form string that merely fits TOKEN_RE could be a pasted secret
MODEL_RE = re.compile(r"^(?:[a-z][a-z0-9_-]{0,15}:)?(?:claude-|gpt-|o\d|gemini-|deepseek|kimi|haiku|sonnet|opus|codex)"
                      r"[a-z0-9._-]{0,40}$", re.I)
ASSIST_NAMES = {"codex", "kimi", "claude", "opencode", "gemini", "cursor"}


def a_model(v):
    return None if v is None else (v if isinstance(v, str) and len(v) <= 64 and MODEL_RE.match(v)
                                   and not re.search(r"[A-Za-z0-9]{24,}", v) else "other")


def a_assist(v):
    return None if v is None else (v if isinstance(v, str) and v in ASSIST_NAMES else "other")


def a_bool(v):
    return v if isinstance(v, bool) else None


def a_date(v):
    d = parse_ts(v)
    return d.strftime("%Y-%m-%d") if d else None


def anon_task(t, rid, idx, idmap=None):
    """idmap: original task_id -> anonymized task_id of the same run (for found_issues.origin_task_id)."""
    o = {"type": "task", "run_id": rid, "task_id": "t%d" % idx}
    for k in ENUMS:
        if k in t:
            o[k] = a_enum(k, t[k])
    if "plan_tier" in t:
        o["plan_tier"] = a_enum("tier", t["plan_tier"])
    if "model" in t:
        o["model"] = a_model(t["model"])
    if "assist" in t:
        o["assist"] = a_assist(t["assist"])
    if "effort" in t:
        o["effort"] = a_set(t["effort"], EFFORTS)
    for k in TASK_NUMS:
        if k in t:
            o[k] = num(t[k])
    for k in TASK_BOOLS:
        if k in t:
            o[k] = a_bool(t[k])
    if t.get("verify_pass") == "partial":
        o["verify_pass"] = "partial"
    if isinstance(t.get("found_issues"), list):  # severity enum + origin mapped to this run's sequence ids
        o["found_issues"] = [{"severity": a_set(x.get("severity"), ("minor", "major")),
                              "origin_task_id": (idmap or {}).get(x.get("origin_task_id"))
                              if isinstance(x.get("origin_task_id"), str) and x.get("origin_task_id") != t.get("task_id")
                              else None}  # self-reference → unattributed, as in attribute()
                             for x in found_issues(t)]
    if isinstance(t.get("followups"), list):  # counts only: desc dropped, fixed_in reduced to fixed / open
        o["followups"] = [{"fixed_in": "fixed" if fixed(x) else None} for x in t["followups"] if isinstance(x, dict)]
    if "verify_evidence" in t:  # keep only whether evidence was given
        o["verify_evidence"] = "[redacted]" if t["verify_evidence"] else ""
    if isinstance(t.get("issues"), dict):
        i = t["issues"]
        o["issues"] = {k: num(i.get(k)) for k in ("review", "integration", "user")}
        sm = i.get("severity_max")
        o["issues"]["severity_max"] = sm if isinstance(sm, str) and sm in SEVERITY else None
    if "flags" in t or "notes" in t:
        fl = []
        for x in task_flags(t):  # known rule markers only; unknown suffixes collapse to "<prefix>:other"
            x = export_flag(x)
            if x and x not in fl:
                fl.append(x)
        if fl:
            o["flags"] = fl
    if isinstance(t.get("score"), dict):  # only the integers 0/1/2 per dimension survive
        o["score"] = {d: score_val(t, d) for d in SCORE_DIMS}
    if isinstance(t.get("independent_review"), dict):
        r = t["independent_review"]
        o["independent_review"] = {"ran": a_bool(r.get("ran")),
                                   "trigger": a_set(r.get("trigger"), IR_TRIGGERS),
                                   "findings": num(r.get("findings")), "major": num(r.get("major"))}
    if "test_scope" in t:
        o["test_scope"] = t["test_scope"] if isinstance(t["test_scope"], str) and t["test_scope"] in ("related", "full") else None
    if "task_type" in t:
        o["task_type"] = a_set(t["task_type"], TASK_TYPES)
    if "shard_group" in t:
        o["shard_group"] = "g" if isinstance(t["shard_group"], str) else None
    if isinstance(t.get("tier_changes"), list):
        o["tier_changes"] = [{"from": a_enum("tier", c.get("from")), "to": a_enum("tier", c.get("to"))}
                             if isinstance(c, dict) else {} for c in t["tier_changes"]]
    return o


def anon_run(r, rid):
    o = {"type": "run", "run_id": rid}
    if "host" in r:
        o["host"] = a_enum("host", r["host"])
    for k in ("started_at", "ended_at"):
        if k in r:
            o[k] = a_date(r[k])
    for k in RUN_NUMS:
        if k in r:
            o[k] = num(r[k])
    for k in RUN_BOOLS:
        if k in r:
            o[k] = a_bool(r[k])
    for k in ("plugin_version_at_start", "plugin_version"):
        v = r.get(k)
        if v is not None:  # empty string stays empty-ish (null) so run_version still falls back like on raw data
            o[k] = None if isinstance(v, str) and not v.strip() else (vnorm(v) or "other")
    return o


def anon_merge(m, rid):
    o = {"type": "merge", "run_id": rid,
         "shards_n": len(m["shards"]) if isinstance(m.get("shards"), list) else num(m.get("shards_n"))}
    for k in ("group_seq", "verify_runs", "full_test_min", "wait_min", "conflicts_n"):
        if k in m:
            o[k] = num(m[k])
    for k in ("full_test", "pass"):
        if k in m:
            o[k] = a_bool(m[k])
    return o


def anonymize(runs):
    out = {}
    for rid, r in runs.items():
        h = anon_id(rid)
        idmap = {}
        for i, t in enumerate(r["tasks"]):
            if isinstance(t.get("task_id"), str) and t["task_id"]:
                idmap.setdefault(t["task_id"], "t%d" % (i + 1))
        out[h] = {"run": anon_run(r["run"], h) if r["run"] else None,
                  "tasks": [anon_task(t, h, i + 1, idmap) for i, t in enumerate(r["tasks"])],
                  "merges": [anon_merge(m, h) for m in r.get("merges") or []]}
    return out


def export_anon(runs, corrupt, raw):
    ar = anonymize(runs)
    versions = sorted({(r["run"] or {}).get(k) for r in ar.values()
                       for k in ("plugin_version", "plugin_version_at_start")} - {None})
    o = {"format": "hq-anon/v1", "schema": "v1", "plugin_versions": versions,
         "note": "Whitelisted enum/number/boolean fields only; free text, project and goal removed; "
                 "run ids hashed; timestamps cut to dates. Without project, standing batches of different "
                 "projects may be paired in summary.recommendations.",
         "summary": build(ar, corrupt)}
    if raw:
        o["records"] = [x for r in ar.values() for x in ([r["run"]] if r["run"] else []) + r["tasks"]
                        + r["merges"]]
    return o


def main(argv=None):
    ap = argparse.ArgumentParser(description="Summarize hq run records into a metrics report.")
    ap.add_argument("paths", nargs="*", help="jsonl files or directories")
    ap.add_argument("--format", choices=["md", "json"], default="md")
    ap.add_argument("--last", type=int, metavar="N")
    ap.add_argument("--project", metavar="NAME")
    ap.add_argument("--export-anon", action="store_true", help="print an anonymized JSON for sharing")
    ap.add_argument("--raw", action="store_true", help="with --export-anon: also include the anonymized records")
    ap.add_argument("--since-version", metavar="V",
                    help="only runs whose version in effect (plugin_version_at_start, else plugin_version) >= V")
    ap.add_argument("--before-version", metavar="V", help="only runs whose version in effect < V")
    ap.add_argument("--check-changelog", metavar="CHANGELOG", help="evaluate `验收判定` lines of 待验证 entries")
    a = ap.parse_args(argv)
    if a.raw and not a.export_anon:
        ap.error("--raw requires --export-anon")
    for opt, v in (("--since-version", a.since_version), ("--before-version", a.before_version)):
        if v is not None and vtuple(v) is None:
            ap.error("%s: cannot parse version %r (expected X.Y.Z)" % (opt, v))
    if not a.paths:
        ap.error("paths are required")
    runs, corrupt = load(collect_files(a.paths))
    if a.project:
        runs = {k: v for k, v in runs.items() if run_project(v) == a.project}
    if a.last is not None:
        ids = list(runs)
        # stable sort: runs without started_at keep file order and count as oldest
        ids.sort(key=lambda i: parse_ts((runs[i]["run"] or {}).get("started_at")) or datetime.min.replace(tzinfo=timezone.utc))
        ids = ids[-a.last:] if a.last > 0 else []
        runs = {i: runs[i] for i in ids}
    runs = filter_versions(runs, a.since_version, a.before_version)
    if a.check_changelog:
        res = check_changelog(a.check_changelog, runs, corrupt)
        sys.stdout.write(json.dumps(res, ensure_ascii=False, indent=2) + "\n" if a.format == "json" else render_check(res))
        return
    if a.export_anon:
        sys.stdout.write(json.dumps(export_anon(runs, corrupt, a.raw), ensure_ascii=False, indent=2) + "\n")
        return
    rep = build(runs, corrupt)
    sys.stdout.write(json.dumps(rep, ensure_ascii=False, indent=2) + "\n" if a.format == "json" else render_md(rep))


if __name__ == "__main__":
    main()

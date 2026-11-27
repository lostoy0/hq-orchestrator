#!/usr/bin/env python3
"""Summarize hq run records (JSONL, schema v1) into a metrics report.

Usage: metrics.py <file|dir...> [--format md|json] [--last N] [--project NAME]
                  [--since-version V] [--before-version V]
       metrics.py <file|dir...> --check-changelog CHANGELOG.md [--format md|json]
       metrics.py <file|dir...> --export-anon [--raw] [--last N] [--project NAME]
--export-anon prints an anonymized JSON for sharing: records are first reduced to a
whitelist of enum/number/boolean fields (all free text, project and goal dropped, run ids
hashed, timestamps cut to dates), then summarized; --raw also includes those records.
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

    A task with the same (run_id, task_id) seen again (e.g. the same run read from both
    .hq/runs and ~/.claude/hq/runs) replaces the earlier record instead of being counted twice.
    """
    runs, corrupt, seen = {}, 0, {}
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
                if t not in ("task", "run", "merge", "monitor"):
                    continue
                rid = rec.get("run_id")
                rid = rid if isinstance(rid, str) and rid else stem
                r = runs.setdefault(rid, {"run": None, "tasks": [], "merges": [], "monitors": []})
                if t in ("merge", "monitor"):  # v0.11.0: group merges and monitor triggers
                    r[t + "s"].append(rec)
                    continue
                if t == "run":
                    r["run"] = rec
                    continue
                tid = rec.get("task_id")
                key = (rid, tid) if isinstance(tid, str) and tid else None
                if key in seen:
                    r["tasks"][seen[key]] = rec
                else:
                    if key:
                        seen[key] = len(r["tasks"])
                    r["tasks"].append(rec)
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


def quality(tasks, runs):
    n = len(tasks)
    ip = [r["integration_pass"] for r in runs if isinstance((r or {}).get("integration_pass"), bool)]
    return {
        "n": n,
        "insufficient": n < MIN_N,
        "drift_rate": rate(sum(1 for t in tasks if t.get("drift") is True or t.get("scope_violation") is True), n),
        "verify_rate": rate(sum(1 for t in tasks if t.get("verify_evidence") and t.get("verify_pass") is True), n),
        "avg_issues_review": rate(sum(issue(t, "review") for t in tasks), n),
        "avg_issues_integration": rate(sum(issue(t, "integration") for t in tasks), n),
        "avg_issues_user": rate(sum(issue(t, "user") for t in tasks), n),
        "major_issues": sum(1 for t in tasks if isinstance(t.get("issues"), dict) and t["issues"].get("severity_max") == "major"),
        "rework_rate": rate(sum(1 for t in tasks if t.get("review_outcome") in ("rework", "failed")), n),
        "integration_pass_rate": rate(sum(ip), len(ip)),
    }


def group(tasks, keyf, skip=frozenset()):
    """skip: id()s of tasks from runs with contradictory time data; left out of actual/est only."""
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
        out.append({
            "key": k, "n": n, "insufficient": n < MIN_N,
            "first_pass_rate": rate(sum(1 for t in ts if first_pass(t)), n),
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
    return {
        "run_id": rid, "tasks": len(ts),
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


def plan_accuracy(tasks):
    """Tasks executed from a /hq-plan backlog carry plan_tier (the planned estimate); tier is what was used."""
    ts = [t for t in tasks if t.get("plan_tier") in TIER_ORDER and t.get("tier") in TIER_ORDER]
    n = len(ts)
    d = [TIER_ORDER.index(t["tier"]) - TIER_ORDER.index(t["plan_tier"]) for t in ts]
    return {
        "n": n, "insufficient": n < MIN_N,
        "same_rate": rate(sum(1 for x in d if x == 0), n),
        "under_rate": rate(sum(1 for x in d if x > 0), n),  # plan estimated lower than needed
        "over_rate": rate(sum(1 for x in d if x < 0), n),
        "first_pass_rate": rate(sum(1 for t in ts if first_pass(t)), n),
    }


# ---------- scale-out (v0.11.0): shards, layered verification, group merges, monitoring ----------
DEFAULT_TARGET_MIN = 40
DEFAULT_OVERHEAD_MIN = 8


def is_shard(t):
    return isinstance(t.get("shard_group"), str) or num(t.get("units_planned")) is not None


def suggest_shards(units, unit_min, overhead, target, limit):
    """Same rule as scale.py shards (kept in sync; see references/scale-out.md)."""
    usable = max(1, limit - int(math.floor(limit * 0.2)))
    work = units * unit_min
    n = max(1, min(usable, int(math.ceil(work / target)), int(units)))
    while n > 1 and overhead / (work / n + overhead) > 0.3:
        n -= 1
    return n


def scale_out(rid, r):
    run, ts = r["run"] or {}, r["tasks"]
    sh = [t for t in ts if is_shard(t)]
    merges = r.get("merges") or []
    mons = r.get("monitors") or []
    if not sh and not merges and not mons:
        return None
    acts = [num(t.get("actual_min")) for t in sh if num(t.get("actual_min")) is not None]
    longest = max(acts) if acts else None
    med_ = med(acts)
    limit, peak = num(run.get("concurrency_limit")), num(run.get("max_concurrency"))
    errs, unit_actual = [], []
    for t in sh:
        a, u, e = num(t.get("actual_min")), num(t.get("units_actual")) or num(t.get("units_planned")), num(t.get("unit_min_est"))
        if a is None or not u:
            continue
        ua = max(0.0, a - (num(t.get("overhead_min")) or 0)) / u
        unit_actual.append(ua)
        if e:
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
    trig = [m for m in mons if m.get("event", "trigger") == "trigger"]
    missed = [m for m in mons if m.get("event") == "missed"]
    by_metric = {}
    for m in trig + missed:
        k = m.get("metric") if isinstance(m.get("metric"), str) else "unknown"
        g = by_metric.setdefault(k, {"triggers": 0, "effective": 0, "false_positive": 0, "missed": 0})
        if m.get("event") == "missed":
            g["missed"] += 1
            continue
        g["triggers"] += 1
        if m.get("label") in ("effective", "false_positive"):
            g[m["label"]] += 1
    for g in by_metric.values():
        lab = g["effective"] + g["false_positive"]
        g["effective_rate"] = rate(g["effective"], lab)
        g["false_positive_rate"] = rate(g["false_positive"], lab)
    units_total = sum(cnt(t.get("units_actual")) or cnt(t.get("units_planned")) for t in sh)
    target = num(run.get("target_shard_min")) or DEFAULT_TARGET_MIN
    ov = med([num(t.get("overhead_min")) for t in sh if num(t.get("overhead_min")) is not None]) or DEFAULT_OVERHEAD_MIN
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
        "monitor_triggers": len(trig),
        "monitor_level1": sum(1 for m in trig if m.get("level") == 1),
        "monitor_level2": sum(1 for m in trig if m.get("level") == 2),
        "monitor_rate_limited": sum(1 for m in trig if m.get("rate_limited") is True),
        "analysis_cost_usd": sum(cnt(m.get("analysis_cost_usd")) for m in mons) if mons else None,
        "monitor_missed": len(missed),
        "monitor_by_metric": by_metric,
        "concurrency_limit": limit,
        "suggest_shards": suggest_shards(units_total, med(unit_actual), ov, target, int(limit))
                          if units_total and unit_actual and limit else None,
    }


def scale_signals(sc, add):
    for x in sc:
        scope = "run %s" % x["run_id"]
        n = x["shards"]
        if n < 2:
            continue
        u = x["concurrency_utilization"]
        if u is not None and u < 0.5 and x["concurrency_limit"] and x["concurrency_limit"] > n:
            msg = "并发利用率 %.0f%% (<50%%)" % (u * 100)
            if x["suggest_shards"] and x["suggest_shards"] > n:
                msg += "，同类任务下次切成 %d 片（按实测单元耗时和上限 %d 计算）" % (x["suggest_shards"], x["concurrency_limit"])
            add(scope, msg, n)
        if x["straggler_ratio"] is not None and x["straggler_ratio"] > 2:
            add(scope, "掉队比 %.2f (>2)：按工作单元清单均匀切，并在巡检时对掉队片再拆" % x["straggler_ratio"], n)
        if x["full_tests"] >= 2 and x["full_tests"] > n * 0.5:
            add(scope, "全量测试 %d 次 / %d 片（>0.5 次每片）：子会话只跑关联测试，全量测试改成每 %d 片合入后跑一次"
                % (x["full_tests"], n, max(2, min(n, 4))), n)
        if x["unit_est_error_median"] is not None and x["unit_est_n"] >= 3 and x["unit_est_error_median"] > 0.5:
            add(scope, "单元耗时估算误差中位数 %.0f%% (>50%%)：开工前先跑小样本测单元耗时" % (x["unit_est_error_median"] * 100), x["unit_est_n"])
        for k, g in sorted(x["monitor_by_metric"].items()):
            lab = g["effective"] + g["false_positive"]
            if lab >= 5 and g["false_positive_rate"] > 0.3:
                add(scope, "监控阈值 %s 误报率 %.0f%% (>30%%)，校准时放宽" % (k, g["false_positive_rate"] * 100), lab)
            if g["missed"] >= 2 and g["missed"] > g["effective"] * 0.25:
                add(scope, "监控阈值 %s 漏报 %d 次，校准时收紧" % (k, g["missed"]), g["missed"] + g["effective"])


def signals(tiers, models, overall_ratio, effs, plan=None, scale=None):
    s = []
    def add(scope, msg, n):
        s.append({"scope": scope, "message": msg, "n": n})
    for label, groups in (("tier", tiers), ("model/effort", models)):
        for g in groups:
            fp, n, rm = g["first_pass_rate"], g["n"], g["ratio_median"]
            sc = "%s %s" % (label, g["key"])
            if n >= 3 and fp is not None and fp < 0.6:
                add(sc, "一次通过率 %.0f%% (<60%%)" % (fp * 100), n)
            if n >= 5 and fp == 1 and rm is not None and rm < 0.7:
                add(sc, "一次通过率 100%%，actual/est 中位数 %.2f (<0.7)，可能存在降档空间" % rm, n)
            if rm is not None and g["ratio_n"] >= 3 and rm > 1.5:
                add(sc, "actual/est 用时比中位数 %.2f (>1.5)，估时偏乐观" % rm, g["ratio_n"])
    if plan and plan["n"] >= 5:
        if plan["under_rate"] is not None and plan["under_rate"] > 0.3:
            add("plan", "%.0f%% 的计划任务实际用了比预估更高的档位 (>30%%)，/hq-plan 打分偏低" % (plan["under_rate"] * 100), plan["n"])
        if plan["over_rate"] is not None and plan["over_rate"] > 0.3:
            add("plan", "%.0f%% 的计划任务实际用了比预估更低的档位 (>30%%)，/hq-plan 打分偏高" % (plan["over_rate"] * 100), plan["n"])
    om, on = overall_ratio
    if om is not None and on >= 3 and om > 1.5:
        add("overall", "actual/est 用时比中位数 %.2f (>1.5)，估时偏乐观" % om, on)
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
                % (e["speedup"], e["speedup_ceiling"]), e["tasks"])
    scale_signals(scale or [], add)
    return s


# ---------- v0.11.0: plugin versions, rule flags, verify-level escapes, recommendations ----------
VER_RE = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)")


def vtuple(v):
    m = VER_RE.match(v.strip()) if isinstance(v, str) else None
    return tuple(int(x) for x in m.groups()) if m else None


def run_version(r):
    return (r["run"] or {}).get("plugin_version") if isinstance((r["run"] or {}).get("plugin_version"), str) else None


def filter_versions(runs, since=None, before=None):
    """since: keep runs with plugin_version >= since; before: keep runs < before. Runs without a
    parseable version are dropped when either bound is given (they can't be placed before/after)."""
    if not since and not before:
        return runs
    lo, hi = vtuple(since) if since else None, vtuple(before) if before else None
    out = {}
    for k, r in runs.items():
        v = vtuple(run_version(r))
        if v is None or (lo and v < lo) or (hi and v >= hi):
            continue
        out[k] = r
    return out


def by_version(runs):
    g = {}
    for rid, r in runs.items():
        g.setdefault(run_version(r) or "unknown", []).append(r)
    rows = []
    for v in sorted(g, key=lambda x: (vtuple(x) is None, vtuple(x) or (0,), x)):
        rs = g[v]
        ts = [t for r in rs for t in r["tasks"]]
        q = quality(ts, [r["run"] or {} for r in rs])
        rr = [ratio(t) for t in ts if ratio(t) is not None]
        cost = [num(t.get("cost_usd")) for t in ts if num(t.get("cost_usd")) is not None]
        rows.append({"key": v, "runs": len(rs), "n": len(ts), "insufficient": len(ts) < MIN_N,
                     "first_pass_rate": rate(sum(1 for t in ts if first_pass(t)), len(ts)),
                     "rework_rate": q["rework_rate"], "drift_rate": q["drift_rate"], "verify_rate": q["verify_rate"],
                     "escaped_per_task": rate(sum(issue(t, "integration") + issue(t, "user") for t in ts), len(ts)),
                     "ratio_median": med(rr), "avg_cost_usd": mean(cost)})
    return rows


# rule markers used to live only in notes; structured `flags` (v0.11.0) wins, notes are a fallback for old data
NOTE_FLAG_RE = re.compile(r"(bias:\+1\((?:tier|effort|cost_low)\)|downgrade:user_allowed\(-\d+\)|rate_limited"
                          r"|assist_unavailable:[A-Za-z0-9_.-]+|assist_auto_models|effort_env:[A-Za-z0-9_-]+"
                          r"|billing:[A-Za-z0-9_-]+|tier:not-applied)")
FLAG_RE = re.compile(r"^[A-Za-z0-9_.:()+-]{1,48}$")


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
                     "rework_rate": rate(sum(1 for t in ts if t.get("review_outcome") in ("rework", "failed")), n),
                     "escalation_rate": rate(sum(1 for t in ts if isinstance(t.get("tier_changes"), list) and t["tier_changes"]), n),
                     "avg_cost_usd": mean(cost)})
    return rows


def by_verify_level(tasks):
    """Problems that got past a verification level: found at integration or by the user."""
    g = {}
    for t in tasks:
        g.setdefault(t["verify_level"] if isinstance(t.get("verify_level"), str) else "unknown", []).append(t)
    rows = []
    for k in sorted(g):
        ts = g[k]
        n = len(ts)
        rows.append({"key": k, "n": n, "insufficient": n < MIN_N,
                     "verify_rate": rate(sum(1 for t in ts if t.get("verify_evidence") and t.get("verify_pass") is True), n),
                     "escaped_integration": rate(sum(issue(t, "integration") for t in ts), n),
                     "escaped_user": rate(sum(issue(t, "user") for t in ts), n),
                     "escaped_per_task": rate(sum(issue(t, "integration") + issue(t, "user") for t in ts), n),
                     "escaped_major": sum(1 for t in ts if isinstance(t.get("issues"), dict)
                                          and t["issues"].get("severity_max") == "major"
                                          and issue(t, "integration") + issue(t, "user") > 0),
                     "rework_rate": rate(sum(1 for t in ts if t.get("review_outcome") in ("rework", "failed")), n)})
    return rows


def recommendations(runs):
    """Standing mode: was the next batch taken from the previous batch's recommendations?
    Consecutive batches of one standing session = same project, standing_seq k then k+1, in time order."""
    rs = []
    for rid, r in runs.items():
        run = r["run"] or {}
        if num(run.get("standing_seq")) is None:
            continue
        rs.append((run_project(r) or "", parse_ts(run.get("started_at")) or datetime.min.replace(tzinfo=timezone.utc),
                   run["standing_seq"], run))
    rs.sort(key=lambda x: (x[0], x[1]))
    offered = accepted = done_claims = 0
    for a, b in zip(rs, rs[1:]):
        if a[0] != b[0] or b[2] != a[2] + 1:
            continue
        if cnt(a[3].get("recommended_next")) > 0:
            offered += 1
            if b[3].get("from_recommendation") is True:
                accepted += 1
    for x in rs:
        if x[3].get("recommended_next") == 0:
            done_claims += 1
    return {"standing_runs": len(rs), "offered": offered, "accepted": accepted,
            "acceptance_rate": rate(accepted, offered), "completion_claims": done_claims,
            "recommended_total": sum(cnt(x[3].get("recommended_next")) for x in rs)}


def extra_signals(add, flags, levels, rec):
    for g in flags:
        if g["n"] >= 5 and g["key"].startswith("bias:+1") and g["first_pass_rate"] == 1 and (g["rework_rate"] or 0) == 0:
            add("flag %s" % g["key"], "规则 9 上调的任务一次通过率 100%%、返工 0：可以小范围实验不上调", g["n"])
        if g["n"] >= 3 and g["key"].startswith("downgrade:") and g["first_pass_rate"] is not None and g["first_pass_rate"] < 0.6:
            add("flag %s" % g["key"], "规则 11 授权降档的任务一次通过率 %.0f%% (<60%%)：降档代价偏高" % (g["first_pass_rate"] * 100), g["n"])
    for g in levels:
        if g["n"] >= 5 and g["escaped_per_task"] is not None and g["escaped_per_task"] > 0.3:
            add("verify %s" % g["key"], "%.2f 个问题/任务漏到合并或用户环节 (>0.3)：考虑加严这一级的子会话验证" % g["escaped_per_task"], g["n"])
        if g["escaped_major"]:
            add("verify %s" % g["key"], "%d 个 major 问题漏过了这一级的验证" % g["escaped_major"], g["n"])
    if rec["offered"] >= 5 and rec["acceptance_rate"] is not None and rec["acceptance_rate"] < 0.3:
        add("standing", "推荐被采纳 %.0f%% (<30%%)：推荐的来源或排序不贴合用户" % (rec["acceptance_rate"] * 100), rec["offered"])


# ---------- structured acceptance criteria in CHANGELOG (`- **验收判定**：` lines) ----------
OPS = {"<=": lambda a, b: a <= b, ">=": lambda a, b: a >= b, "<": lambda a, b: a < b, ">": lambda a, b: a > b,
       "==": lambda a, b: a == b, "!=": lambda a, b: a != b}
EXPR_RE = re.compile(r"^\s*(?P<path>\S+)\s*(?P<op><=|>=|==|!=|<|>)\s*(?P<val>-?\d+(?:\.\d+)?)"
                     r"(?P<opts>(?:\s+(?:n>=\d+|since=\S+|before=\S+))*)\s*$")
AGG = {"median": med, "mean": mean, "max": lambda xs: max(xs) if xs else None,
       "min": lambda xs: min(xs) if xs else None, "sum": lambda xs: sum(xs) if xs else None}
SEG_RE = re.compile(r"^(?P<name>[A-Za-z_][A-Za-z0-9_]*)(?:\[(?P<sel>[^\]]+)\])?$")


def _walk(node, segs):
    """Returns (values, n). A [*] segment fans out; [key=val] picks the element whose key (or run_id) matches."""
    cur = [(node, None)]
    for seg in segs:
        m = SEG_RE.match(seg)
        if not m:
            raise ValueError("bad path segment: %s" % seg)
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
        n = next((p[k] for k in ("n", "ratio_n", "tasks", "shards", "offered") if num(p.get(k)) is not None), None)
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
    need = re.search(r"n>=(\d+)", m.group("opts"))
    need = int(need.group(1)) if need else MIN_N
    res = {"expr": expr, "value": value, "n": n, "need_n": need}
    if value is None:
        return dict(res, verdict="样本不足")
    if n is not None and n < need:
        return dict(res, verdict="样本不足")
    return dict(res, verdict="达到" if OPS[op](value, want) else "未达到")


def parse_changelog(text):
    """Entries under `### ` headings with their version (`## vX.Y.Z` or 未发布), status and 验收判定 expressions."""
    entries, ver, cur = [], None, None
    for line in text.splitlines():
        if line.startswith("## "):
            m = VER_RE.match(line[3:].strip())
            ver = ".".join(m.groups()) if m else None
            cur = None
        elif line.startswith("### "):
            cur = {"title": line[4:].strip(), "version": ver, "status": None, "exprs": []}
            entries.append(cur)
        elif cur is not None:
            st = re.match(r"^- \*\*状态\*\*[:：]\s*(\S+?)(?:[（(\s]|$)", line)
            if st:
                cur["status"] = st.group(1)
            if line.startswith("- **验收判定**"):
                cur["exprs"] += re.findall(r"`([^`]+)`", line)
    return entries


def check_changelog(path, runs, corrupt):
    entries = parse_changelog(open(path, encoding="utf-8").read())
    out = []
    for e in entries:
        if e["status"] != "待验证" or not e["exprs"]:
            continue
        rows = []
        for x in e["exprs"]:
            m = EXPR_RE.match(x)
            opts = m.group("opts") if m else ""
            since = re.search(r"since=(\S+)", opts)
            before = re.search(r"before=(\S+)", opts)
            since = since.group(1) if since else e["version"]
            sub = filter_versions(runs, since, before.group(1) if before else None) if since or before else runs
            r = eval_expr(x, build(sub, corrupt))
            r["since"] = since
            rows.append(r)
        # quality guard: rework rate after the change must not rise against the runs before it
        guard = None
        since = rows[0]["since"] if rows else None
        if since:
            pre = quality([t for r in filter_versions(runs, None, since).values() for t in r["tasks"]], [])
            post = quality([t for r in filter_versions(runs, since, None).values() for t in r["tasks"]], [])
            if pre["n"] >= 5 and post["n"] >= 5 and post["rework_rate"] > pre["rework_rate"] + 0.05:
                guard = "返工率 %.0f%% → %.0f%%" % (pre["rework_rate"] * 100, post["rework_rate"] * 100)
        vs = [r["verdict"] for r in rows]
        verdict = ("未达到" if guard or "未达到" in vs else "样本不足" if any(v != "达到" for v in vs) else "达到")
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
    tiers = group(tasks, lambda t: t["tier"] if isinstance(t.get("tier"), str) else "unknown", skip)
    models = group(tasks, lambda t: "%s/%s" % (t["model"] if isinstance(t.get("model"), str) else "unknown",
                                               t["effort"] if isinstance(t.get("effort"), str) else "unknown"), skip)
    s_ = lambda t, k: t[k] if isinstance(t.get(k), str) else "unknown"
    hosts = group(tasks, lambda t: "%s/%s" % (s_(t, "host"), s_(t, "channel")), skip)
    # 辅助执行者（v0.5.0 可选字段 assist）：null/缺失记为 main（主宿主自己的模型）
    assist = group(tasks, lambda t: "assist:%s/%s" % (t["assist"], s_(t, "tier")) if isinstance(t.get("assist"), str) and t["assist"]
                   else "main/%s" % s_(t, "tier"), skip)
    rs = [ratio(t) for t in tasks if id(t) not in skip and ratio(t) is not None]
    miss = [e["missing_records"] for e in effs if e["missing_records"] is not None]
    plan = plan_accuracy(tasks)
    sc = [x for x in (scale_out(i, runs[i]) for i in ids) if x]
    flags, levels, rec = by_flag(tasks), by_verify_level(tasks), recommendations(runs)
    sig = signals(tiers, models, (med(rs), len(rs)), effs, plan, sc)
    extra_signals(lambda scope, msg, n: sig.append({"scope": scope, "message": msg, "n": n}), flags, levels, rec)
    return {
        "overview": {"runs": len(ids), "tasks": len(tasks), "corrupt_lines": corrupt,
                     "missing_task_records": sum(miss) if miss else None,
                     "time_from": min(stamps)[1] if stamps else None, "time_to": max(stamps)[1] if stamps else None},
        "quality": {"overall": quality(tasks, rr),
                    "per_run": [dict(quality(runs[i]["tasks"], [runs[i]["run"] or {}]), run_id=i) for i in ids]},
        "by_tier": tiers, "by_model": models, "by_host_channel": hosts, "by_assist": assist,
        "efficiency": effs,
        "cost": cost_by_kind(tasks),
        "adjust": adjust(tasks),
        "autonomy": {"autonomy_stops": sum(cnt(r.get("autonomy_stops")) for r in rr),
                     "decisions": sum(cnt(r.get("decisions")) for r in rr),
                     "user_corrections": sum(cnt(t.get("user_corrections")) for t in tasks)},
        "plan": plan,
        "scale_out": sc,
        "by_version": by_version(runs), "by_flag": flags, "by_verify_level": levels, "recommendations": rec,
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


def render_md(rep):
    o = rep["overview"]
    L = ["# HQ 指标报告 (schema v1)", "", "## 1. 总览", ""]
    L += table(["run 数", "task 数", "损坏行数", "缺记录任务数", "时间范围"],
               [[o["runs"], o["tasks"], o["corrupt_lines"], f(o["missing_task_records"], "d"),
                 "%s ~ %s" % (o["time_from"] or "-", o["time_to"] or "-")]])
    L += ["", "## 2. 质量门槛", ""]
    qh = ["范围", "n", "漂移率", "验证到位率", "问题/任务 review", "integration", "user", "major 数", "返工率", "合并通过率", "备注"]
    def qrow(name, q):
        return [name, q["n"], f(q["drift_rate"], "p"), f(q["verify_rate"], "p"), f(q["avg_issues_review"]),
                f(q["avg_issues_integration"]), f(q["avg_issues_user"]), q["major_issues"], f(q["rework_rate"], "p"),
                f(q["integration_pass_rate"], "p"), "样本不足" if q["insufficient"] else ""]
    L += table(qh, [qrow("总体", rep["quality"]["overall"])] + [qrow(q["run_id"], q) for q in rep["quality"]["per_run"]])
    gh = ["分组", "n", "一次通过率", "升档率", "交接率", "平均 cost_usd", "平均 tokens", "actual/est 中位数", "备注"]
    def grow(g):
        return [g["key"], g["n"], f(g["first_pass_rate"], "p"), f(g["escalation_rate"], "p"), f(g["handoff_rate"], "p"),
                f(g["avg_cost_usd"]), f(g["avg_tokens"], "d"), f(g["ratio_median"]),
                "；".join(x for x in ("样本不足" if g["insufficient"] else "",
                                     "用时比排除矛盾 run 的 %d 条" % g["ratio_excluded"] if g["ratio_excluded"] else "") if x)]
    L += ["", "## 3a. 按档位", ""] + table(gh, [grow(g) for g in rep["by_tier"]])
    L += ["", "## 3b. 按模型/思考深度", ""] + table(gh, [grow(g) for g in rep["by_model"]])
    L += ["", "## 3c. 按宿主/通道", ""] + table(gh, [grow(g) for g in rep["by_host_channel"]])
    if any(g["key"].startswith("assist:") for g in rep["by_assist"]):
        L += ["", "## 3d. 辅助执行者 vs 主宿主（按档位；交接率≈被收回给主宿主的比例）", ""] + table(gh, [grow(g) for g in rep["by_assist"]])
    p = rep["plan"]
    if p["n"]:
        L += ["", "## 3e. 计划预估档位 vs 实际（按计划执行的任务，plan_tier）", ""] + table(
            ["n", "一致", "预估偏低", "预估偏高", "一次通过率", "备注"],
            [[p["n"], f(p["same_rate"], "p"), f(p["under_rate"], "p"), f(p["over_rate"], "p"),
              f(p["first_pass_rate"], "p"), "样本不足" if p["insufficient"] else ""]])
    vh = ["版本", "run 数", "task 数", "一次通过率", "返工率", "漂移率", "验证到位率", "漏网问题/任务", "actual/est 中位数", "平均 cost_usd", "备注"]
    L += ["", "## 3f. 按插件版本（改动前后对比用；--since-version / --before-version 可只看一段）", ""] + table(vh, [
        [g["key"], g["runs"], g["n"], f(g["first_pass_rate"], "p"), f(g["rework_rate"], "p"), f(g["drift_rate"], "p"),
         f(g["verify_rate"], "p"), f(g["escaped_per_task"]), f(g["ratio_median"]), f(g["avg_cost_usd"]),
         "样本不足" if g["insufficient"] else ""] for g in rep["by_version"]])
    L += ["", "## 3g. 按验证级别（漏网 = 合并或用户环节才发现的问题）", ""] + table(
        ["级别", "n", "验证到位率", "漏到合并/任务", "漏到用户/任务", "漏网 major", "返工率", "备注"],
        [[g["key"], g["n"], f(g["verify_rate"], "p"), f(g["escaped_integration"]), f(g["escaped_user"]),
          g["escaped_major"], f(g["rework_rate"], "p"), "样本不足" if g["insufficient"] else ""] for g in rep["by_verify_level"]])
    if rep["by_flag"]:
        L += ["", "## 3h. 按规则标记（flags；旧数据从 notes 识别）", ""] + table(
            ["标记", "n", "一次通过率", "返工率", "升档率", "平均 cost_usd", "备注"],
            [[g["key"], g["n"], f(g["first_pass_rate"], "p"), f(g["rework_rate"], "p"), f(g["escalation_rate"], "p"),
              f(g["avg_cost_usd"]), "样本不足" if g["insufficient"] else ""] for g in rep["by_flag"]])
    rc = rep["recommendations"]
    if rc["standing_runs"]:
        L += ["", "## 6c. 常驻模式推荐", ""] + table(
            ["常驻批次", "推荐过的批次", "下一批采纳推荐", "采纳率", "推荐总条数", "完工声明"],
            [[rc["standing_runs"], rc["offered"], rc["accepted"], f(rc["acceptance_rate"], "p"),
              rc["recommended_total"], rc["completion_claims"]]])
    L += ["", "## 4. 效率", ""]
    L += table(["run", "任务数", "wall/关键路径", "并行加速比", "加速比上限", "max_concurrency", "throttle_events", "备注"],
               [[e["run_id"], e["tasks"], f(e["wall_over_critical"]), f(e["speedup"]), f(e["speedup_ceiling"]),
                 f(e["max_concurrency"], "d"), f(e["throttle_events"], "d"),
                 "数据矛盾：" + ", ".join(e["inconsistent"]) if e["inconsistent"] else ""] for e in rep["efficiency"]])
    L += ["", "## 5. 开销（按 kind）", ""]
    L += table(["kind", "n", "平均 tokens", "每预计分钟成本 (USD)", "备注"],
               [[c["key"], c["n"], f(c["avg_tokens"], "d"), f(c["cost_per_est_min"], "c"), "样本不足" if c["insufficient"] else ""]
                for c in rep["cost"]])
    a = rep["autonomy"]
    L += ["", "## 6. 自主性", ""] + table(["autonomy_stops", "decisions", "user_corrections"],
                                          [[f(a["autonomy_stops"], "d"), f(a["decisions"], "d"), f(a["user_corrections"], "d")]])
    d = rep["adjust"]
    L += ["", "## 6b. 调档与检查点", ""] + table(
        ["升档任务数", "其中有检查点的比例", "checkpoints", "handoffs", "derived_tasks", "user_manual_adjust"],
        [[d["escalated"], f(d["escalated_after_checkpoint_rate"], "p"), d["checkpoints"], d["handoffs"],
          d["derived_tasks"], d["user_manual_adjust"]]])
    if rep.get("scale_out"):
        L += ["", "## 4b. 分片、分层校验与合入（v0.11.0 起的字段；旧数据没有就不出）", ""]
        L += table(["run", "片数", "并行效率", "掉队比", "并发利用率", "单元耗时误差", "再拆", "关联/全量(片内)",
                    "全量测试次数", "全量耗时(分)", "每次全量覆盖片数", "合入组数", "每组片数", "校验次数"],
                   [[x["run_id"], x["shards"], f(x["parallel_efficiency"], "p"), f(x["straggler_ratio"]),
                     f(x["concurrency_utilization"], "p"), f(x["unit_est_error_median"], "p"), x["resplit"],
                     "%d/%d" % (x["test_related"], x["full_tests_worker"]), x["full_tests"], f(x["full_test_min"], "d"),
                     f(x["shards_per_full_test"]), x["merge_groups"], f(x["shards_per_group"]), x["verify_runs"]]
                    for x in rep["scale_out"]])
        L += ["", "## 4c. 主动监控", ""]
        L += table(["run", "触发", "一级", "二级", "限频跳过", "漏报", "分析花费 (USD)", "各阈值 触发/有效率/误报率/漏报"],
                   [[x["run_id"], x["monitor_triggers"], x["monitor_level1"], x["monitor_level2"], x["monitor_rate_limited"],
                     x["monitor_missed"], f(x["analysis_cost_usd"], "c"),
                     "；".join("%s %d/%s/%s/%d" % (k, g["triggers"], f(g["effective_rate"], "p"), f(g["false_positive_rate"], "p"), g["missed"])
                              for k, g in sorted(x["monitor_by_metric"].items())) or "-"]
                    for x in rep["scale_out"]])
    L += ["", "## 7. 信号", ""]
    L += ["- [%s] %s（n=%d）" % (s["scope"], s["message"], s["n"]) for s in rep["signals"]] or ["- 无"]
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
TOKEN_RE = re.compile(r"^[A-Za-z0-9._:/@+-]{1,64}$")  # model / effort names
VERSION_RE = re.compile(r"^\d+\.\d+\.\d+[A-Za-z0-9.+-]{0,16}$")
TASK_NUMS = ("tier_score", "est_min", "actual_min", "tokens", "cost_usd", "attempts", "handoffs",
             "derived_tasks", "checkpoints", "user_corrections",
             "units_planned", "units_actual", "unit_min_est", "overhead_min", "test_min", "rework_rounds")
TASK_BOOLS = ("user_manual_adjust", "scope_violation", "drift", "verify_pass", "resplit")
RUN_NUMS = ("wall_min", "critical_path_min", "tasks", "max_concurrency", "throttle_events",
            "autonomy_stops", "decisions", "standing_seq", "recommended_next", "concurrency_limit",
            "target_shard_min")
MONITOR_ENUMS = {
    "event": {"trigger", "missed"},
    "metric": {"duration_ratio", "idle_min", "cost_ratio", "rework", "failure_rate", "straggler_ratio",
               "split_unit_error", "split_uneven", "split_underused", "split_boundary"},
    "severity": {"normal", "severe"},
    "label": {"effective", "false_positive"},
}
TASK_TYPES = {"patrol", "dev", "docs", "test", "research", "review", "config", "code", "*"}
RUN_BOOLS = ("integration_pass", "from_recommendation")


def anon_id(rid):
    return "r-" + hashlib.sha256(("hq-anon:" + rid).encode("utf-8")).hexdigest()[:10]


def a_enum(k, v):
    return None if v is None else (v if isinstance(v, str) and v in ENUMS[k] else "other")


def a_token(v):
    return None if v is None else (v if isinstance(v, str) and TOKEN_RE.match(v) else "other")


def a_bool(v):
    return v if isinstance(v, bool) else None


def a_date(v):
    d = parse_ts(v)
    return d.strftime("%Y-%m-%d") if d else None


def anon_task(t, rid, idx):
    o = {"type": "task", "run_id": rid, "task_id": "t%d" % idx}
    for k in ENUMS:
        if k in t:
            o[k] = a_enum(k, t[k])
    if "plan_tier" in t:
        o["plan_tier"] = a_enum("tier", t["plan_tier"])
    for k in ("model", "effort", "assist"):
        if k in t:
            o[k] = a_token(t[k])
    for k in TASK_NUMS:
        if k in t:
            o[k] = num(t[k])
    for k in TASK_BOOLS:
        if k in t:
            o[k] = a_bool(t[k])
    if "verify_evidence" in t:  # keep only whether evidence was given
        o["verify_evidence"] = "[redacted]" if t["verify_evidence"] else ""
    if isinstance(t.get("issues"), dict):
        i = t["issues"]
        o["issues"] = {k: num(i.get(k)) for k in ("review", "integration", "user")}
        o["issues"]["severity_max"] = i["severity_max"] if i.get("severity_max") in SEVERITY else None
    if "flags" in t or "notes" in t:
        fl = [x for x in task_flags(t) if NOTE_FLAG_RE.fullmatch(x)]  # known rule markers only
        if fl:
            o["flags"] = fl
    if "test_scope" in t:
        o["test_scope"] = t["test_scope"] if t["test_scope"] in ("related", "full") else None
    if "task_type" in t:
        o["task_type"] = t["task_type"] if t["task_type"] in TASK_TYPES else "other"
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
    v = r.get("plugin_version")
    if v is not None:
        o["plugin_version"] = v if isinstance(v, str) and VERSION_RE.match(v) else "other"
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


def anon_monitor(m, rid):
    o = {"type": "monitor", "run_id": rid}
    for k, vals in MONITOR_ENUMS.items():
        if k in m:
            o[k] = m[k] if m[k] in vals else ("other" if m[k] is not None else None)
    if "task_type" in m:
        o["task_type"] = m["task_type"] if m["task_type"] in TASK_TYPES else "other"
    for k in ("value", "threshold", "level", "analysis_cost_usd"):
        if k in m:
            o[k] = num(m[k])
    if "rate_limited" in m:
        o["rate_limited"] = a_bool(m["rate_limited"])
    return o


def anonymize(runs):
    out = {}
    for rid, r in runs.items():
        h = anon_id(rid)
        out[h] = {"run": anon_run(r["run"], h) if r["run"] else None,
                  "tasks": [anon_task(t, h, i + 1) for i, t in enumerate(r["tasks"])],
                  "merges": [anon_merge(m, h) for m in r.get("merges") or []],
                  "monitors": [anon_monitor(m, h) for m in r.get("monitors") or []]}
    return out


def export_anon(runs, corrupt, raw):
    ar = anonymize(runs)
    versions = sorted({(r["run"] or {}).get("plugin_version") for r in ar.values()} - {None})
    o = {"format": "hq-anon/v1", "schema": "v1", "plugin_versions": versions,
         "note": "Whitelisted enum/number/boolean fields only; free text, project and goal removed; "
                 "run ids hashed; timestamps cut to dates.",
         "summary": build(ar, corrupt)}
    if raw:
        o["records"] = [x for r in ar.values() for x in ([r["run"]] if r["run"] else []) + r["tasks"]
                        + r["merges"] + r["monitors"]]
    return o


def main(argv=None):
    ap = argparse.ArgumentParser(description="Summarize hq run records into a metrics report.")
    ap.add_argument("paths", nargs="+", help="jsonl files or directories")
    ap.add_argument("--format", choices=["md", "json"], default="md")
    ap.add_argument("--last", type=int, metavar="N")
    ap.add_argument("--project", metavar="NAME")
    ap.add_argument("--export-anon", action="store_true", help="print an anonymized JSON for sharing")
    ap.add_argument("--raw", action="store_true", help="with --export-anon: also include the anonymized records")
    ap.add_argument("--since-version", metavar="V", help="only runs with plugin_version >= V")
    ap.add_argument("--before-version", metavar="V", help="only runs with plugin_version < V")
    ap.add_argument("--check-changelog", metavar="CHANGELOG", help="evaluate `验收判定` lines of 待验证 entries")
    a = ap.parse_args(argv)
    if a.raw and not a.export_anon:
        ap.error("--raw requires --export-anon")
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

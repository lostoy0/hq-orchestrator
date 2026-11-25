#!/usr/bin/env python3
"""Summarize hq run records (JSONL, schema v1) into a metrics report.

Usage: metrics.py <file|dir...> [--format md|json] [--last N] [--project NAME]
"""
import argparse
import json
import math
import os
import statistics
import sys
from datetime import datetime, timezone

MIN_N = 3


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
                if t not in ("task", "run"):
                    continue
                rid = rec.get("run_id")
                rid = rid if isinstance(rid, str) and rid else stem
                r = runs.setdefault(rid, {"run": None, "tasks": []})
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


def group(tasks, keyf):
    g = {}
    for t in tasks:
        g.setdefault(keyf(t), []).append(t)
    out = []
    for k in sorted(g):
        ts = g[k]
        n = len(ts)
        toks = [num(t.get("tokens")) for t in ts if num(t.get("tokens")) is not None]
        cost = [num(t.get("cost_usd")) for t in ts if num(t.get("cost_usd")) is not None]
        rs = [ratio(t) for t in ts if ratio(t) is not None]
        out.append({
            "key": k, "n": n, "insufficient": n < MIN_N,
            "first_pass_rate": rate(sum(1 for t in ts if first_pass(t)), n),
            "escalation_rate": rate(sum(1 for t in ts if isinstance(t.get("tier_changes"), list) and t["tier_changes"]), n),
            "handoff_rate": rate(sum(1 for t in ts if cnt(t.get("handoffs")) > 0), n),
            "avg_cost_usd": mean(cost), "avg_tokens": mean(toks),
            "ratio_median": med(rs), "ratio_n": len(rs),
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


def efficiency(rid, r):
    run, ts = r["run"] or {}, r["tasks"]
    wall, crit = num(run.get("wall_min")), num(run.get("critical_path_min"))
    acts = [num(t.get("actual_min")) for t in ts if num(t.get("actual_min")) is not None]
    declared = num(run.get("tasks"))
    return {
        "run_id": rid, "tasks": len(ts),
        "missing_records": max(0, declared - len(ts)) if declared is not None else None,
        "wall_over_critical": wall / crit if wall is not None and crit else None,
        "speedup": sum(acts) / wall if acts and wall else None,
        "max_concurrency": num(run.get("max_concurrency")),
        "throttle_events": num(run.get("throttle_events")),
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


def signals(tiers, models, overall_ratio, effs):
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
    om, on = overall_ratio
    if om is not None and on >= 3 and om > 1.5:
        add("overall", "actual/est 用时比中位数 %.2f (>1.5)，估时偏乐观" % om, on)
    for e in effs:
        if e["speedup"] is not None and e["speedup"] < 1.3 and e["tasks"] >= 3:
            add("run %s" % e["run_id"], "并行加速比 %.2f (<1.3)" % e["speedup"], e["tasks"])
    return s


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
    tiers = group(tasks, lambda t: t["tier"] if isinstance(t.get("tier"), str) else "unknown")
    models = group(tasks, lambda t: "%s/%s" % (t["model"] if isinstance(t.get("model"), str) else "unknown",
                                               t["effort"] if isinstance(t.get("effort"), str) else "unknown"))
    s_ = lambda t, k: t[k] if isinstance(t.get(k), str) else "unknown"
    hosts = group(tasks, lambda t: "%s/%s" % (s_(t, "host"), s_(t, "channel")))
    effs = [efficiency(i, runs[i]) for i in ids]
    rs = [ratio(t) for t in tasks if ratio(t) is not None]
    miss = [e["missing_records"] for e in effs if e["missing_records"] is not None]
    return {
        "overview": {"runs": len(ids), "tasks": len(tasks), "corrupt_lines": corrupt,
                     "missing_task_records": sum(miss) if miss else None,
                     "time_from": min(stamps)[1] if stamps else None, "time_to": max(stamps)[1] if stamps else None},
        "quality": {"overall": quality(tasks, rr),
                    "per_run": [dict(quality(runs[i]["tasks"], [runs[i]["run"] or {}]), run_id=i) for i in ids]},
        "by_tier": tiers, "by_model": models, "by_host_channel": hosts,
        "efficiency": effs,
        "cost": cost_by_kind(tasks),
        "adjust": adjust(tasks),
        "autonomy": {"autonomy_stops": sum(cnt(r.get("autonomy_stops")) for r in rr),
                     "decisions": sum(cnt(r.get("decisions")) for r in rr),
                     "user_corrections": sum(cnt(t.get("user_corrections")) for t in tasks)},
        "signals": signals(tiers, models, (med(rs), len(rs)), effs),
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
                f(g["avg_cost_usd"]), f(g["avg_tokens"], "d"), f(g["ratio_median"]), "样本不足" if g["insufficient"] else ""]
    L += ["", "## 3a. 按档位", ""] + table(gh, [grow(g) for g in rep["by_tier"]])
    L += ["", "## 3b. 按模型/思考深度", ""] + table(gh, [grow(g) for g in rep["by_model"]])
    L += ["", "## 3c. 按宿主/通道", ""] + table(gh, [grow(g) for g in rep["by_host_channel"]])
    L += ["", "## 4. 效率", ""]
    L += table(["run", "任务数", "wall/关键路径", "并行加速比", "max_concurrency", "throttle_events"],
               [[e["run_id"], e["tasks"], f(e["wall_over_critical"]), f(e["speedup"]), f(e["max_concurrency"], "d"),
                 f(e["throttle_events"], "d")] for e in rep["efficiency"]])
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
    L += ["", "## 7. 信号", ""]
    L += ["- [%s] %s（n=%d）" % (s["scope"], s["message"], s["n"]) for s in rep["signals"]] or ["- 无"]
    return "\n".join(L) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description="Summarize hq run records into a metrics report.")
    ap.add_argument("paths", nargs="+", help="jsonl files or directories")
    ap.add_argument("--format", choices=["md", "json"], default="md")
    ap.add_argument("--last", type=int, metavar="N")
    ap.add_argument("--project", metavar="NAME")
    a = ap.parse_args(argv)
    runs, corrupt = load(collect_files(a.paths))
    if a.project:
        runs = {k: v for k, v in runs.items() if run_project(v) == a.project}
    if a.last is not None:
        ids = list(runs)
        # stable sort: runs without started_at keep file order and count as oldest
        ids.sort(key=lambda i: parse_ts((runs[i]["run"] or {}).get("started_at")) or datetime.min.replace(tzinfo=timezone.utc))
        ids = ids[-a.last:] if a.last > 0 else []
        runs = {i: runs[i] for i in ids}
    rep = build(runs, corrupt)
    sys.stdout.write(json.dumps(rep, ensure_ascii=False, indent=2) + "\n" if a.format == "json" else render_md(rep))


if __name__ == "__main__":
    main()

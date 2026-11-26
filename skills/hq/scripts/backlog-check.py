#!/usr/bin/env python3
"""Check a /hq-plan backlog (hq-backlog/1). Read-only.

Exit codes: 0 no errors (warnings allowed), 1 errors found, 2 bad arguments / unreadable file.
Format: skills/hq/references/backlog-schema.md
"""
import argparse
import json
import re
import sys

SCHEMA = "hq-backlog/1"
KINDS = {"code", "docs", "research", "review", "config"}
VERIFY = {"doc", "code", "high", "e2e"}
STATUS = {"todo", "in_progress", "done", "blocked", "dropped"}
PRIO = {"P0", "P1", "P2"}
TIERS = ["T0", "T1", "T2", "T3", "T4"]
DIMS = ("scope", "ambiguity", "context", "risk", "verify")
# Ids keep the project's own scheme (hq writes F-001 / B-001 / R1; an imported plan may use REQ-001, NFR-01,
# LC-01, DF-V1-BASE01, M1 ...). Only the shape is checked: an upper-case prefix, a dash, a number.
REQ_RE = re.compile(r"^[A-Z][A-Z0-9]*-\d+$")
TASK_RE = re.compile(r"^[A-Z][A-Z0-9]*(-[A-Z0-9]+)+$")
REL_RE = re.compile(r"^[A-Za-z][\w.-]{0,31}$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
LONG_TASK_MIN = 120


def tier_for(score):
    """calibration.md score bands: T0 0-1, T1 2-3, T2 4-5, T3 6-7, T4 8-10."""
    return TIERS[min(4, score // 2)]


def is_str(v):
    return isinstance(v, str) and v.strip() != ""


def is_str_list(v, allow_empty=True):
    return isinstance(v, list) and all(is_str(x) for x in v) and (allow_empty or len(v) > 0)


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def check(doc, prd_text=None):
    errs, warns = [], []
    E = lambda where, msg: errs.append("%s: %s" % (where, msg))
    W = lambda where, msg: warns.append("%s: %s" % (where, msg))

    if not isinstance(doc, dict):
        E("root", "顶层必须是对象")
        return errs, warns, {}
    if doc.get("schema") != SCHEMA:
        E("schema", "必须是 %r" % SCHEMA)
    if not is_str(doc.get("project")):
        E("project", "缺失或为空")
    if not (isinstance(doc.get("updated"), str) and DATE_RE.match(doc["updated"])):
        E("updated", "必须是 YYYY-MM-DD")
    if not isinstance(doc.get("based_on"), dict):
        E("based_on", "必须是对象")
    for k in ("requirements", "releases", "tasks"):
        if not isinstance(doc.get(k), list):
            E(k, "必须是数组")
    if errs:
        return errs, warns, {}

    # releases
    rel_order = {}
    for i, r in enumerate(doc["releases"]):
        w = "releases[%d]" % i
        if not isinstance(r, dict):
            E(w, "必须是对象"); continue
        rid = r.get("id")
        if not (isinstance(rid, str) and REL_RE.match(rid)):
            E(w, "id 必须以字母开头，如 R1、M1、v1.1"); continue
        w = "release %s" % rid
        if rid in rel_order:
            E(w, "id 重复"); continue
        rel_order[rid] = i
        for k in ("name", "goal"):
            if not is_str(r.get(k)):
                E(w, "%s 缺失或为空" % k)
        if not is_str_list(r.get("exit_criteria"), allow_empty=False):
            E(w, "exit_criteria 必须是非空字符串数组")
    if not rel_order:
        E("releases", "至少要有一个版本")

    # requirements
    reqs = {}
    for i, q in enumerate(doc["requirements"]):
        w = "requirements[%d]" % i
        if not isinstance(q, dict):
            E(w, "必须是对象"); continue
        qid = q.get("id")
        if not (isinstance(qid, str) and REQ_RE.match(qid)):
            E(w, "id 必须是大写前缀加编号，如 F-001、NFR-001、REQ-001"); continue
        w = "requirement %s" % qid
        if qid in reqs:
            E(w, "id 重复"); continue
        reqs[qid] = q
        if not is_str(q.get("title")):
            E(w, "title 缺失或为空")
        if q.get("priority") not in PRIO:
            E(w, "priority 必须是 P0/P1/P2")
        if "release" not in q:
            E(w, "缺 release（暂不安排写 null）")
        elif q["release"] is not None and q["release"] not in rel_order:
            E(w, "release %r 不存在" % q["release"])
        elif q["release"] is None and q.get("priority") == "P0":
            E(w, "P0 需求必须安排版本")

    # tasks
    tasks = {}
    imported = bool(doc.get("imported_from"))  # converted from another plan: its own task granularity is kept
    long_imported = []
    for i, t in enumerate(doc["tasks"]):
        w = "tasks[%d]" % i
        if not isinstance(t, dict):
            E(w, "必须是对象"); continue
        tid = t.get("id")
        if not (isinstance(tid, str) and TASK_RE.match(tid)):
            E(w, "id 必须是大写前缀加编号，如 B-001、DF-V1-BASE01"); continue
        w = "task %s" % tid
        if tid in tasks:
            E(w, "id 重复"); continue
        tasks[tid] = t
        if t.get("release") not in rel_order:
            E(w, "release %r 不存在" % t.get("release"))
        if not is_str(t.get("title")):
            E(w, "title 缺失或为空")
        if t.get("kind") not in KINDS:
            E(w, "kind 必须是 %s 之一" % "/".join(sorted(KINDS)))
        if not is_str_list(t.get("requirements")):
            E(w, "requirements 必须是字符串数组")
        else:
            for q in t["requirements"]:
                if q not in reqs:
                    E(w, "引用了不存在的需求 %s" % q)
            if not t["requirements"] and not is_str(t.get("notes")):
                W(w, "没有关联需求，notes 里写明它为谁服务")
        if not is_str_list(t.get("depends_on")):
            E(w, "depends_on 必须是字符串数组")
        if not is_str_list(t.get("owns"), allow_empty=False):
            E(w, "owns 必须是非空字符串数组")
        if not is_str_list(t.get("acceptance"), allow_empty=False):
            E(w, "acceptance 至少 1 条")
        if t.get("verify_level") not in VERIFY:
            E(w, "verify_level 必须是 doc/code/high/e2e")
        if t.get("status") not in STATUS:
            E(w, "status 必须是 %s 之一" % "/".join(sorted(STATUS)))
        est = t.get("est_min")
        if not (isinstance(est, (int, float)) and not isinstance(est, bool) and est > 0):
            E(w, "est_min 必须是正数")
        elif est > LONG_TASK_MIN:
            if imported:
                long_imported.append(tid)
            else:
                W(w, "est_min=%s 超过 %d，建议拆分" % (est, LONG_TASK_MIN))
        # tier
        sc = t.get("score")
        ok_score = isinstance(sc, dict) and all(is_int(sc.get(d)) and 0 <= sc[d] <= 2 for d in DIMS)
        if not ok_score:
            E(w, "score 必须含 %s，每项 0–2 的整数" % "/".join(DIMS))
        ts = t.get("tier_score")
        if not (is_int(ts) and 0 <= ts <= 10):
            E(w, "tier_score 必须是 0–10 的整数")
        elif ok_score and ts != sum(sc[d] for d in DIMS):
            E(w, "tier_score=%d 不等于 5 维之和 %d" % (ts, sum(sc[d] for d in DIMS)))
        tier = t.get("tier")
        if tier not in TIERS:
            E(w, "tier 必须是 T0–T4")
        elif is_int(ts) and 0 <= ts <= 10:
            base = tier_for(ts)
            if TIERS.index(tier) < TIERS.index(base):
                if is_str(t.get("tier_note")):
                    W(w, "档位 %s 低于分数线 %s（tier_score=%d），依据：%s" % (tier, base, ts, t["tier_note"]))
                else:
                    E(w, "档位 %s 低于分数线 %s（tier_score=%d），必须在 tier_note 写依据" % (tier, base, ts))

    if long_imported:
        W("tasks", "%d 个任务 est_min 超过 %d（导入自 %s，保留原计划的粒度，/hq 派发时再拆）：%s" % (
            len(long_imported), LONG_TASK_MIN, doc.get("imported_from"), "、".join(long_imported[:8]) + ("…" if len(long_imported) > 8 else "")))

    # dependencies
    for tid, t in tasks.items():
        for d in t.get("depends_on") or []:
            if not isinstance(d, str):
                continue
            if d == tid:
                E("task %s" % tid, "依赖了自己"); continue
            if d not in tasks:
                E("task %s" % tid, "依赖的任务 %s 不存在" % d); continue
            a, b = rel_order.get(t.get("release")), rel_order.get(tasks[d].get("release"))
            if a is not None and b is not None and b > a:
                E("task %s" % tid, "依赖了更晚版本的任务 %s" % d)
    deps = {tid: [d for d in (t.get("depends_on") or []) if d in tasks and d != tid] for tid, t in tasks.items()}
    color, cycle = {}, []

    def visit(n, path):
        color[n] = 1
        for m in deps[n]:
            if color.get(m) == 1:  # m is on the current DFS path
                cycle.append(path[path.index(m):] + [m]); continue
            if not color.get(m):
                visit(m, path + [m])
        color[n] = 2

    for n in tasks:
        if not color.get(n):
            visit(n, [n])
    for c in cycle[:3]:
        E("depends_on", "依赖有环：%s" % " -> ".join(c))

    # ancestors for overlap check
    anc = {}

    def ancestors(n, stack=()):
        if n in anc:
            return anc[n]
        if n in stack:
            return set()
        s = set()
        for m in deps[n]:
            s.add(m)
            s |= ancestors(m, stack + (n,))
        anc[n] = s
        return s

    live = [tid for tid, t in tasks.items() if t.get("status") != "dropped"]
    for i, x in enumerate(live):
        for y in live[i + 1:]:
            tx, ty = tasks[x], tasks[y]
            if tx.get("release") != ty.get("release"):
                continue
            if x in ancestors(y) or y in ancestors(x):
                continue
            common = set(tx.get("owns") or []) & set(ty.get("owns") or [])
            common = {c for c in common if isinstance(c, str)}
            if common:
                W("task %s/%s" % (x, y), "同一版本、没有依赖关系，却负责相同的 %s；并行会冲突，加依赖或合并" % ", ".join(sorted(common)))

    # coverage
    for qid, q in reqs.items():
        rel = q.get("release")
        if rel not in rel_order:  # unscheduled (null) or already reported as invalid
            continue
        cover = [tid for tid in live if qid in (tasks[tid].get("requirements") or [])
                 and rel_order.get(tasks[tid].get("release"), 1 << 30) <= rel_order[rel]]
        if not cover:
            if q.get("priority") == "P0":
                E("requirement %s" % qid, "P0 需求在 %s 及以前没有任务覆盖" % rel)
            elif q.get("priority") == "P1":
                W("requirement %s" % qid, "P1 需求在 %s 及以前没有任务覆盖" % rel)
    if prd_text is not None:
        prefixes = sorted({r.split("-")[0] for r in reqs} | {"F", "NFR"})  # the backlog's own prefixes plus hq's
        in_text = re.findall(r"\b(?:%s)-\d+\b" % "|".join(map(re.escape, prefixes)), prd_text)
        missing = sorted(set(in_text) - set(reqs))
        if missing:
            W("prd", "需求文档里有、清单里没有的编号：%s" % ", ".join(missing))

    by_rel = {}
    for tid in live:
        r = tasks[tid].get("release")
        e = by_rel.setdefault(r, {"tasks": 0, "est_min": 0, "tiers": {}})
        e["tasks"] += 1
        if isinstance(tasks[tid].get("est_min"), (int, float)):
            e["est_min"] += tasks[tid]["est_min"]
        tr = tasks[tid].get("tier")
        e["tiers"][tr] = e["tiers"].get(tr, 0) + 1
    summary = {"releases": len(rel_order), "requirements": len(reqs), "tasks": len(tasks),
               "by_release": {r: by_rel[r] for r in sorted(by_rel, key=lambda r: rel_order.get(r, 1 << 30))}}
    return errs, warns, summary


def main(argv=None):
    ap = argparse.ArgumentParser(description="Check a /hq-plan backlog.json (read-only)")
    ap.add_argument("backlog")
    ap.add_argument("--prd", metavar="FILE", help="requirements doc; warn on F-/NFR- ids missing from the backlog")
    ap.add_argument("--format", choices=["md", "json"], default="md")
    a = ap.parse_args(argv)
    try:
        with open(a.backlog, encoding="utf-8") as fh:
            doc = json.load(fh)
    except (OSError, ValueError) as e:
        print("错误: 读不了 %s: %s" % (a.backlog, e), file=sys.stderr)
        return 2
    prd = None
    if a.prd:
        try:
            with open(a.prd, encoding="utf-8", errors="replace") as fh:
                prd = fh.read()
        except OSError as e:
            print("错误: 读不了 %s: %s" % (a.prd, e), file=sys.stderr)
            return 2
    errs, warns, summary = check(doc, prd)
    if a.format == "json":
        print(json.dumps({"errors": errs, "warnings": warns, "summary": summary}, ensure_ascii=False, indent=2))
    else:
        print("# backlog 检查：%s" % a.backlog)
        if summary:
            print("\n版本 %d 个，需求 %d 条，任务 %d 个" % (summary["releases"], summary["requirements"], summary["tasks"]))
            for r, e in summary["by_release"].items():
                tiers = " ".join("%s×%d" % (k, v) for k, v in sorted(e["tiers"].items(), key=lambda kv: str(kv[0])))
                print("- %s：%d 个任务，预计 %s 分钟，档位 %s" % (r, e["tasks"], e["est_min"], tiers))
        print("\n## 错误（%d）" % len(errs))
        print("\n".join("- " + x for x in errs) or "- 无")
        print("\n## 警告（%d）" % len(warns))
        print("\n".join("- " + x for x in warns) or "- 无")
    return 1 if errs else 0


if __name__ == "__main__":
    sys.exit(main())

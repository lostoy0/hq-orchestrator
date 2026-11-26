#!/usr/bin/env python3
"""Report the state of every stage artifact in a project. Read-only.

  stage-status.py [--docs <docs_root>] [--format md|json]

For each stage (research, prd, design, arch, plan) it lists the artifacts, their version, whether they are
stale (a based_on entry names an older version of an upstream artifact) and how many errors the stage's
checker finds. /hq-blueprint uses it to decide which stages to run.

Stage state: ok | missing (no artifact) | partial (some artifacts missing) | needs_work (checker errors) | stale.
Exit codes: 0 report printed, 2 bad arguments.
"""
import argparse
import importlib.util
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ORDER = ["research", "prd", "design", "arch", "plan"]
# (stage, key, path under docs_root, names other artifacts use for it in based_on)
ARTIFACTS = [
    ("research", "competitors", "research/competitors.md", ["competitors", "research"]),
    ("prd", "prd", "product/prd.md", ["prd"]),
    ("design", "design-system", "design/design-system.md", ["design-system", "design"]),
    ("design", "screens", "design/screens.md", ["screens"]),
    ("design", "prototype", "design/prototype/manifest.js", ["prototype"]),
    ("arch", "architecture", "tech/architecture.md", ["architecture", "arch"]),
    ("arch", "detailed-design", "tech/detailed-design.md", ["detailed-design", "detailed"]),
    ("plan", "roadmap", "plan/roadmap.md", ["roadmap"]),
    ("plan", "backlog", "plan/backlog.json", ["backlog", "plan"]),
]
ALT_PATHS = {"prd": ["product/prd-hq.md"]}  # /hq-prd writes here when product/prd.md is someone else's file


def load(name):
    spec = importlib.util.spec_from_file_location(name.replace("-", "_"), os.path.join(HERE, name + ".py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def read(p):
    with open(p, encoding="utf-8", errors="replace") as fh:
        return fh.read().replace("\r\n", "\n")


def frontmatter(text):
    meta = {}
    if not text.startswith("---\n"):
        return meta
    end = text.find("\n---", 4)
    for line in text[4:end if end > 0 else 0].splitlines():
        line = line.split("#", 1)[0].rstrip()
        if ":" in line:
            k, v = line.split(":", 1)
            meta[k.strip()] = v.strip()
    return meta


def based_on_tokens(meta_value):
    """'[prd@3, competitors@1]' -> [('prd', '3'), ('competitors', '1')]"""
    return [(m.group(1).strip(), m.group(2).strip()) for m in re.finditer(r"([\w.-]+)@([\w.-]+)", meta_value or "")]


def collect(docs):
    arts = {}
    for stage, key, rel, names in ARTIFACTS:
        path = os.path.join(docs, rel)
        if not os.path.exists(path):
            for alt in ALT_PATHS.get(key, []):
                if os.path.exists(os.path.join(docs, alt)):
                    path, rel = os.path.join(docs, alt), alt
                    break
        a = {"stage": stage, "key": key, "path": rel, "exists": os.path.exists(path), "abs": path,
             "names": names, "version": None, "status": None, "based_on": []}
        if a["exists"] and path.endswith(".md"):
            meta = frontmatter(read(path))
            a["version"] = int(meta["version"]) if str(meta.get("version", "")).isdigit() else None
            a["status"] = meta.get("status")
            a["based_on"] = based_on_tokens(meta.get("based_on", ""))
        elif a["exists"] and key == "backlog":
            try:
                doc = json.loads(read(path))
                for v in (doc.get("based_on") or {}).values():
                    m = re.match(r"^(.*?)@([\w.-]+)$", str(v))
                    if m:
                        name = os.path.splitext(os.path.basename(m.group(1)))[0]
                        a["based_on"].append((name, m.group(2)))
                a["status"] = doc.get("updated")
            except ValueError:
                pass
        arts[key] = a
    return arts


def staleness(arts):
    by_name = {}
    for a in arts.values():
        for n in a["names"]:
            by_name[n] = a
    for a in arts.values():
        a["stale"] = []
        for name, ver in a["based_on"]:
            up = by_name.get(name)
            if up and up["exists"] and up["version"] is not None and ver.isdigit() and up["version"] > int(ver):
                a["stale"].append("%s@%s → 现在是 %s@%d" % (name, ver, up["key"], up["version"]))


def run_checks(arts):
    dc, bc, pc = load("doc-check"), load("backlog-check"), load("prototype-check")
    prd_text = read(arts["prd"]["abs"]) if arts["prd"]["exists"] else None
    for a in arts.values():
        a["errors"], a["warnings"] = None, None
        if not a["exists"]:
            continue
        try:
            if a["key"] in ("prd", "competitors"):
                e, w, _ = (dc.check_prd if a["key"] == "prd" else dc.check_research)(read(a["abs"]))
            elif a["key"] == "architecture":
                det = arts["detailed-design"]
                e, w, _ = dc.check_arch(read(a["abs"]), a["abs"], read(det["abs"]) if det["exists"] else None, prd_text)
            elif a["key"] == "prototype":
                _, e, w, _ = pc.check(os.path.dirname(a["abs"]), prd_text)
            elif a["key"] == "backlog":
                e, w, _ = bc.check(json.loads(read(a["abs"])), prd_text)
            else:
                continue
            a["errors"], a["warnings"] = len(e), len(w)
        except Exception as ex:  # a broken artifact must not hide the rest of the report
            a["errors"], a["warnings"] = 1, 0
            a["check_failed"] = "%s: %s" % (type(ex).__name__, ex)


def stage_states(arts):
    out = []
    for s in ORDER:
        mine = [a for a in arts.values() if a["stage"] == s]
        have = [a for a in mine if a["exists"]]
        if not have:
            state = "missing"
        elif len(have) < len(mine):
            state = "partial"
        elif any(a["errors"] for a in mine):
            state = "needs_work"
        elif any(a["stale"] for a in mine):
            state = "stale"
        else:
            state = "ok"
        out.append({"stage": s, "state": state, "artifacts": [
            {k: a[k] for k in ("key", "path", "exists", "version", "status", "stale", "errors", "warnings")}
            | ({"check_failed": a["check_failed"]} if "check_failed" in a else {}) for a in mine]})
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description="Report the state of stage artifacts (read-only)")
    ap.add_argument("--docs", default="docs", help="docs_root (default: docs)")
    ap.add_argument("--format", choices=["md", "json"], default="md")
    a = ap.parse_args(argv)
    if not os.path.isdir(a.docs):
        print("错误: 文档目录不存在：%s（新项目可以先建好目录，或用 --docs 指定）" % a.docs, file=sys.stderr)
        return 2
    arts = collect(a.docs)
    staleness(arts)
    run_checks(arts)
    stages = stage_states(arts)
    todo = [s["stage"] for s in stages if s["state"] != "ok"]
    if a.format == "json":
        print(json.dumps({"docs": a.docs, "stages": stages, "todo": todo}, ensure_ascii=False, indent=2))
        return 0
    names = {"ok": "已完成", "missing": "没有", "partial": "不完整", "needs_work": "检查有错误", "stale": "上游已更新"}
    print("# 阶段产物状态：%s\n" % a.docs)
    print("| 阶段 | 状态 | 产物 | 版本 | 检查（错误/警告） | 说明 |\n|---|---|---|---|---|---|")
    for s in stages:
        for i, x in enumerate(s["artifacts"]):
            chk = "-" if x["errors"] is None else "%d/%d" % (x["errors"], x["warnings"])
            note = "；".join(x["stale"]) or x.get("check_failed", "") or ("" if x["exists"] else "不存在")
            print("| %s | %s | %s | %s | %s | %s |" % (s["stage"] if i == 0 else "", names[s["state"]] if i == 0 else "",
                                                     x["path"], x["version"] if x["version"] is not None else "-", chk, note))
    print("\n待处理：%s" % ("、".join(todo) if todo else "无，全部阶段已完成"))
    return 0


if __name__ == "__main__":
    sys.exit(main())

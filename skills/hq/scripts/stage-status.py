#!/usr/bin/env python3
"""Report the state of every stage artifact in a project.

  stage-status.py [--docs <docs_root>] [--format md|json]
  stage-status.py --discover [--root <repo>]                 suggest hq-artifacts.json from existing files
  stage-status.py --docs <docs_root> --record-audit <stage> --report <file> --blockers N [--majors N]
  stage-status.py --docs <docs_root> --record-source <stage>   remember the fingerprint of a stage's "source"

For each stage (research, prd, design, arch, plan) it lists the artifacts, their version, whether they are
stale (a based_on entry names an older version of an upstream artifact) and how many errors the stage's
checker finds. /hq-blueprint uses it to decide which stages to run.

Projects that already have their own documents (another tool's layout, another format) describe them in
<docs_root>/hq-artifacts.json (schema hq-artifacts/1, see skills/hq/references/stages/common.md section 10).
A stage marked "foreign" is not checked by format; it is ok once a content audit was recorded with
--record-audit, found no blockers, and the files have not changed since (sha256 fingerprint).

Stage state: ok | missing | partial | needs_work (checker errors or audit blockers) | unaudited (foreign,
not audited or changed since the audit) | stale.
Exit codes: 0 done, 2 bad arguments.
"""
import argparse
import hashlib
import importlib.util
import json
import os
import re
import sys
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
ORDER = ["research", "prd", "design", "arch", "plan"]
MAP_FILE = "hq-artifacts.json"
MAP_SCHEMA = "hq-artifacts/1"
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
SKIP_DIRS = {".git", "node_modules", "vendor", "dist", "build", "target", ".venv", "venv", "__pycache__",
             ".hq", ".claude", ".agents", ".next", ".turbo", "coverage"}
DOC_ROOTS = ["docs", "doc", "documentation", ".opc", "specs", "spec"]  # checked in this order
# directories that exist to hold a set of files: the directory is the artifact, so files added later are noticed
COLLECTION_DIR_RE = re.compile(r"(^|/)(adrs?|contracts?|api[-_]?specs?|prototype|原型|mockups?|wireframes?)$", re.I)
FROZEN_RE = re.compile(r"已冻结|冻结版|\bfrozen\b|status:\s*approved|\|\s*状态\s*\|\s*(已批准|已确认)", re.I)
# discovery heuristics: (stage, regex on the repo-relative path)
DISCOVER = [
    ("research", re.compile(r"(competitor|竞品|market[-_ ]?research|调研)[^/]*\.md$", re.I)),
    ("prd", re.compile(r"(^|/)(prd|需求|requirements?|product[-_ ]?spec)[^/]*\.md$", re.I)),
    ("design", re.compile(r"(^|/)(prototype|原型|mockups?|wireframes?)/[^/]+\.html$|(design[-_ ]?system|设计规范|screens)[^/]*\.md$", re.I)),
    ("arch", re.compile(r"(^|/)(architecture|架构|detailed[-_ ]?design|技术设计|tech[-_ ]?design)[^/]*\.md$|(^|/)tech/[^/]*design[^/]*\.md$|(^|/)adrs?/[^/]+\.md$|(^|/)(contracts?|api[-_]?specs?)/[^/]+\.(ya?ml|json|sql|md|proto|graphql)$", re.I)),
    ("plan", re.compile(r"(^|/)(roadmap|backlog|plan|计划)[^/]*\.(md|json|ya?ml)$|\.dag\.ya?ml$|(^|/)plan/[^/]+\.(md|json|ya?ml)$", re.I)),
]


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


def repo_root(start):
    d = os.path.abspath(start)
    while True:
        if os.path.exists(os.path.join(d, ".git")):
            return d
        parent = os.path.dirname(d)
        if parent == d:
            return os.path.dirname(os.path.abspath(start))
        d = parent


def walk_files(path):
    if os.path.isfile(path):
        return [path]
    out = []
    for dp, dns, fns in os.walk(path):
        dns[:] = sorted(x for x in dns if x not in SKIP_DIRS)
        out += [os.path.join(dp, f) for f in sorted(fns)]
    return out


def fingerprint(root, paths):
    """sha256 over the content of every file under the given repo-relative paths (first 16 hex chars)."""
    h = hashlib.sha256()
    for p in sorted(paths):
        full = os.path.join(root, p)
        if not os.path.exists(full):
            h.update(("missing:" + p).encode())
            continue
        for f in walk_files(full):
            h.update(os.path.relpath(f, root).encode() + b"\0")
            with open(f, "rb") as fh:
                h.update(fh.read())
    return h.hexdigest()[:16]


def load_map(docs):
    p = os.path.join(docs, MAP_FILE)
    if not os.path.isfile(p):
        return None
    m = json.loads(read(p))
    if m.get("schema") != MAP_SCHEMA or not isinstance(m.get("stages"), dict):
        raise ValueError("%s: schema 必须是 %s，且有 stages 对象" % (p, MAP_SCHEMA))
    return m


def collect(docs, amap=None):
    arts = {}
    overrides = {}
    for stage, conf in ((amap or {}).get("stages") or {}).items():
        if conf.get("format", "hq") == "hq" and isinstance(conf.get("paths"), dict):
            overrides.update(conf["paths"])  # key -> path under docs_root
    for stage, key, rel, names in ARTIFACTS:
        rel = overrides.get(key, rel)
        path = os.path.join(docs, rel)
        if not os.path.exists(path):
            for alt in ALT_PATHS.get(key, []):
                if os.path.exists(os.path.join(docs, alt)):
                    path, rel = os.path.join(docs, alt), alt
                    break
        a = {"stage": stage, "key": key, "path": rel, "exists": os.path.exists(path), "abs": path,
             "names": names, "version": None, "status": None, "based_on": [], "format": "hq"}
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
    for stage, conf in ((amap or {}).get("stages") or {}).items():
        if conf.get("format", "hq") == "hq":
            for k in conf.get("skip") or []:  # e.g. an imported plan needs no roadmap.md
                if k in arts and arts[k]["stage"] == stage:
                    del arts[k]
    return arts


def apply_foreign(arts, amap, root):
    """Replace the hq artifacts of every stage marked foreign with the mapped files."""
    for stage, conf in ((amap or {}).get("stages") or {}).items():
        if conf.get("format") != "foreign" or stage not in ORDER:
            continue
        for k in [k for k, a in arts.items() if a["stage"] == stage]:
            del arts[k]
        paths = conf.get("paths") if isinstance(conf.get("paths"), list) else []
        audit = conf.get("audit") if isinstance(conf.get("audit"), dict) else None
        fp = fingerprint(root, paths)
        for p in paths or ["(未指定路径)"]:
            full = os.path.join(root, p)
            arts["%s:%s" % (stage, p)] = {
                "stage": stage, "key": "%s:%s" % (stage, p), "path": p, "abs": full, "exists": bool(paths) and os.path.exists(full),
                "names": [], "version": None, "status": "frozen" if conf.get("frozen") else None, "based_on": [],
                "format": "foreign", "frozen": bool(conf.get("frozen")), "audit": audit, "fingerprint": fp,
                "audit_current": bool(audit) and audit.get("fingerprint") == fp,
            }


def source_staleness(arts, amap, root):
    """hq-format stages converted from another file (e.g. a plan imported by /hq-plan) go stale when it changes."""
    for stage, conf in ((amap or {}).get("stages") or {}).items():
        src = conf.get("source")
        if conf.get("format", "hq") != "hq" or not src:
            continue
        src = src if isinstance(src, list) else [src]
        if fingerprint(root, src) != conf.get("source_fingerprint"):
            for a in arts.values():
                if a["stage"] == stage and a["exists"]:
                    a["stale"].append("来源 %s 在转换后改过" % "、".join(src))


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
    prd = arts.get("prd")
    prd_text = read(prd["abs"]) if prd and prd["exists"] else None
    for a in arts.values():
        a["errors"], a["warnings"] = None, None
        if not a["exists"] or a["format"] != "hq":
            continue
        try:
            if a["key"] in ("prd", "competitors"):
                e, w, _ = (dc.check_prd if a["key"] == "prd" else dc.check_research)(read(a["abs"]))
            elif a["key"] == "architecture":
                det = arts.get("detailed-design")
                e, w, _ = dc.check_arch(read(a["abs"]), a["abs"], read(det["abs"]) if det and det["exists"] else None, prd_text)
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
        foreign = bool(mine) and mine[0]["format"] == "foreign"
        audit = mine[0].get("audit") if foreign else None
        if not have:
            state = "missing"
        elif len(have) < len(mine):
            state = "partial"
        elif foreign and audit and mine[0]["audit_current"] and int(audit.get("blockers") or 0) > 0:
            state = "needs_work"
        elif foreign and not (audit and mine[0]["audit_current"]):
            state = "unaudited"
        elif any(a["errors"] for a in mine):
            state = "needs_work"
        elif any(a["stale"] for a in mine):
            state = "stale"
        else:
            state = "ok"
        entry = {"stage": s, "state": state, "format": "foreign" if foreign else "hq", "artifacts": [
            {k: a[k] for k in ("key", "path", "exists", "version", "status", "stale", "errors", "warnings")}
            | ({"check_failed": a["check_failed"]} if "check_failed" in a else {}) for a in mine]}
        if foreign:
            entry.update(frozen=mine[0]["frozen"], audit=audit, fingerprint=mine[0]["fingerprint"],
                         audit_current=mine[0]["audit_current"])
        out.append(entry)
    return out


def discover(root):
    """Suggest an hq-artifacts.json for a repository that already has documents."""
    hits = {s: [] for s in ORDER}
    for dp, dns, fns in os.walk(root):
        dns[:] = sorted(x for x in dns if x not in SKIP_DIRS or x == ".opc")
        rel_dir = os.path.relpath(dp, root)
        if re.search(r"(^|/)reviews?(/|$)", rel_dir):
            continue
        for f in sorted(fns):
            rel = os.path.normpath(os.path.join(rel_dir, f))
            for stage, rx in DISCOVER:
                if rx.search(rel):
                    hits[stage].append(rel)
                    break
    docs_root = next((d for d in DOC_ROOTS if os.path.isdir(os.path.join(root, d))), "docs")
    stages = {}
    for s, files in hits.items():
        if not files:
            continue
        hq = all(frontmatter(read(os.path.join(root, f))).get("hq_stage") for f in files if f.endswith(".md")) and \
            any(f.endswith(".md") for f in files)
        # several hits in one directory (ADRs, contracts, prototype pages) -> the directory itself
        per_dir = {}
        for f in files:
            per_dir.setdefault(os.path.dirname(f), []).append(f)
        paths = []
        for d, fs in per_dir.items():
            collapse = d not in ("", ".") and (len(fs) > 1 or bool(COLLECTION_DIR_RE.search(d)))
            paths += [d] if collapse else fs
        paths = sorted(set(paths))
        frozen = any(FROZEN_RE.search("\n".join(read(os.path.join(root, f)).splitlines()[:30]))
                     for f in files if f.endswith(".md"))
        stages[s] = {"format": "hq" if hq else "foreign", "paths": paths, "frozen": frozen}
        if hq:
            del stages[s]["paths"]  # hq-format stages use the default layout under docs_root
    return {"schema": MAP_SCHEMA, "docs_root": docs_root, "stages": stages}


def record_audit(docs, stage, report, blockers, majors):
    p = os.path.join(docs, MAP_FILE)
    amap = load_map(docs)
    if amap is None:
        raise ValueError("%s 不存在，先建对应表" % p)
    conf = amap["stages"].get(stage)
    if not conf or conf.get("format") != "foreign":
        raise ValueError("阶段 %s 在对应表里不是 foreign 格式" % stage)
    root = repo_root(docs)
    conf["audit"] = {"date": date.today().isoformat(), "report": report, "blockers": blockers, "majors": majors,
                     "fingerprint": fingerprint(root, conf.get("paths") or [])}
    with open(p, "w", encoding="utf-8") as fh:
        json.dump(amap, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    return conf["audit"]


STATE_NAMES = {"ok": "已完成", "missing": "没有", "partial": "不完整", "needs_work": "需要修改", "stale": "上游已更新",
               "unaudited": "外来格式，待接管评审"}


def main(argv=None):
    ap = argparse.ArgumentParser(description="Report the state of stage artifacts")
    ap.add_argument("--docs", default="docs", help="docs_root (default: docs)")
    ap.add_argument("--format", choices=["md", "json"], default="md")
    ap.add_argument("--discover", action="store_true", help="suggest hq-artifacts.json from existing files")
    ap.add_argument("--root", default=".", help="--discover: repository root (default: .)")
    ap.add_argument("--record-audit", metavar="STAGE", choices=ORDER)
    ap.add_argument("--record-source", metavar="STAGE", choices=ORDER)
    ap.add_argument("--report", help="--record-audit: path of the audit report")
    ap.add_argument("--blockers", type=int, help="--record-audit: unresolved blockers")
    ap.add_argument("--majors", type=int, default=0, help="--record-audit: unresolved majors")
    a = ap.parse_args(argv)

    if a.discover:
        if not os.path.isdir(a.root):
            print("错误: 不是目录：%s" % a.root, file=sys.stderr)
            return 2
        print(json.dumps(discover(a.root), ensure_ascii=False, indent=2))
        return 0
    if not os.path.isdir(a.docs):
        print("错误: 文档目录不存在：%s（新项目可以先建好目录，或用 --docs 指定；已有文档的项目先运行 --discover）" % a.docs, file=sys.stderr)
        return 2
    if a.record_source:
        try:
            amap = load_map(a.docs)
            conf = (amap or {}).get("stages", {}).get(a.record_source) or {}
            if not conf.get("source"):
                raise ValueError("阶段 %s 在对应表里没有 source" % a.record_source)
            src = conf["source"] if isinstance(conf["source"], list) else [conf["source"]]
            conf["source_fingerprint"] = fingerprint(repo_root(a.docs), src)
            with open(os.path.join(a.docs, MAP_FILE), "w", encoding="utf-8") as fh:
                json.dump(amap, fh, ensure_ascii=False, indent=2)
                fh.write("\n")
            print(json.dumps({"stage": a.record_source, "source_fingerprint": conf["source_fingerprint"]}))
        except (ValueError, OSError, AttributeError) as e:
            print("错误: %s" % e, file=sys.stderr)
            return 2
        return 0
    if a.record_audit:
        if not a.report or a.blockers is None:
            print("错误: --record-audit 需要 --report 和 --blockers", file=sys.stderr)
            return 2
        try:
            print(json.dumps(record_audit(a.docs, a.record_audit, a.report, a.blockers, a.majors), ensure_ascii=False))
        except (ValueError, OSError) as e:
            print("错误: %s" % e, file=sys.stderr)
            return 2
        return 0
    try:
        amap = load_map(a.docs)
    except ValueError as e:
        print("错误: %s" % e, file=sys.stderr)
        return 2
    arts = collect(a.docs, amap)
    apply_foreign(arts, amap, repo_root(a.docs))
    staleness(arts)
    source_staleness(arts, amap, repo_root(a.docs))
    run_checks(arts)
    stages = stage_states(arts)
    todo = [s["stage"] for s in stages if s["state"] != "ok"]
    if a.format == "json":
        print(json.dumps({"docs": a.docs, "map": bool(amap), "stages": stages, "todo": todo}, ensure_ascii=False, indent=2))
        return 0
    print("# 阶段产物状态：%s%s\n" % (a.docs, "（按 %s）" % MAP_FILE if amap else ""))
    print("| 阶段 | 状态 | 产物 | 版本 | 检查（错误/警告） | 说明 |\n|---|---|---|---|---|---|")
    for s in stages:
        for i, x in enumerate(s["artifacts"]):
            chk = "-" if x["errors"] is None else "%d/%d" % (x["errors"], x["warnings"])
            if s["format"] == "foreign":
                au = s.get("audit")
                note = ("外来格式" + ("，已冻结" if s.get("frozen") else "") +
                        ("；评审 %s，blocker %s%s" % (au.get("date"), au.get("blockers"), "" if s["audit_current"] else "，评审后文件改过")
                         if au else "；未评审"))
                note = note if x["exists"] else "不存在"
            else:
                note = "；".join(x["stale"]) or x.get("check_failed", "") or ("" if x["exists"] else "不存在")
            print("| %s | %s | %s | %s | %s | %s |" % (s["stage"] if i == 0 else "", STATE_NAMES[s["state"]] if i == 0 else "",
                                                     x["path"], x["version"] if x["version"] is not None else "-", chk, note))
    print("\n待处理：%s" % ("、".join(todo) if todo else "无，全部阶段已完成"))
    return 0


if __name__ == "__main__":
    sys.exit(main())

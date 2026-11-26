#!/usr/bin/env python3
"""Static checks for a /hq-design clickable prototype. Read-only, Python stdlib only.

  prototype-check.py <prototype dir> [--prd <prd.md>] [--format md|json] [--foreign] [--allow-external]

Without manifest.js (or with --foreign) the directory is treated as an adopted, foreign-format prototype
(plain .html files): local links/resources must exist, no external network resources, and with --prd
requirement IDs from the PRD that never appear in any HTML file are warned about (a coverage signal only).

Exit codes: 0 no errors (warnings allowed), 1 errors found, 2 bad arguments / unreadable manifest.
Format: skills/hq-design/prototype-schema.md
"""
import argparse
import importlib.util
import json
import os
import re
import sys
from urllib.parse import unquote
from collections import deque
from html.parser import HTMLParser

SCHEMA = "hq-prototype/1"
PLATFORMS = {"web", "ios", "android", "mini"}
STATES = ["default", "empty", "loading", "error", "forbidden", "first"]
ACTIONS = {"goto", "click", "fill", "select", "expect", "see"}
REQUIRED_INCLUDES = ["../manifest.js", "../data/seed.js", "../assets/app.js", "../assets/tokens.css", "../assets/base.css"]
HEX_RE = re.compile(r"#[0-9a-fA-F]{3,8}\b")
TESTID_RE = re.compile(r"^\[data-testid=['\"]?([\w-]+)['\"]?\]$")
RESOURCE_TAGS = {"script", "link", "img", "iframe", "source", "video", "audio", "embed"}
# requirement-like IDs (same shape as backlog-check.py: upper-case prefix, dash, number), taken where they
# are defined: at the start of a heading, list item or table cell, or in bold at the start of a line
ID_DEF_RE = re.compile(r"^\s*(?:(?:#{1,6}\s+|[-*+]\s+|\d+[.)]\s+|\|\s*)(?:\*\*|`)?|\*\*|`)([A-Z][A-Z0-9]*(?:-\d+)+)(?![\w-])", re.M)
NOT_IDS = {"UTF", "ISO", "SHA", "HTTP", "TLS", "ES", "RFC", "CVE", "GB", "IPV"}  # standards, not requirements
COMMENT_RE = re.compile(r"<!--.*?-->", re.S)
SKIP_DIRS = {"node_modules", ".git", "__pycache__"}


def load_manifest(root):
    p = os.path.join(root, "manifest.js")
    with open(p, encoding="utf-8") as fh:
        text = fh.read()
    m = re.search(r"window\.PROTOTYPE\s*=\s*", text)
    if not m:
        raise ValueError("manifest.js 里没有 window.PROTOTYPE = …")
    body = text[m.end():].strip()
    body = body[:body.rfind("}") + 1]
    return json.loads(body)


class Page(HTMLParser):
    def __init__(self):
        super().__init__()
        self.refs, self.navs, self.testids, self.states, self.external = [], [], set(), set(), []
        self.external_res = []  # (tag, url) for resources the page loads from the network
        self.body_page = None
        self.style_text = []
        self._in_style = False

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "body":
            self.body_page = a.get("data-hq-page")
        for k in ("href", "src"):
            v = a.get(k)
            if v is None:
                continue
            if re.match(r"^(https?:)?//", v):
                self.external.append(v)
                if tag in RESOURCE_TAGS and not (tag == "link" and (a.get("rel") or "").lower() in ("canonical", "alternate")):
                    self.external_res.append((tag, v))
            elif not re.match(r"^(#|mailto:|tel:|javascript:|data:|\?)", v) and v:
                self.refs.append(v)
        if a.get("data-hq-nav"):
            self.navs.append(a["data-hq-nav"])
        if a.get("data-testid"):
            self.testids.add(a["data-testid"])
        if a.get("data-hq-state"):
            self.states.update(a["data-hq-state"].split())
        if a.get("style"):
            self.style_text.append(a["style"])
        self._in_style = tag == "style"

    def handle_endtag(self, tag):
        if tag == "style":
            self._in_style = False

    def handle_data(self, data):
        if self._in_style:
            self.style_text.append(data)


def parse_html(path):
    p = Page()
    with open(path, encoding="utf-8", errors="replace") as fh:
        p.feed(fh.read())
    return p


def load_doc_check():
    here = os.path.dirname(os.path.abspath(__file__))
    spec = importlib.util.spec_from_file_location("doc_check", os.path.join(here, "doc-check.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def prd_ui_requirements(text):
    """{id: priority} for F- requirements that have a UI (界面状态 not 不适用)."""
    dc = load_doc_check()
    _, body, _ = dc.split_frontmatter(text.replace("\r\n", "\n"))
    body = dc.COMMENT_RE.sub("", body)
    out, allf = {}, {}
    for lv, t, st, end in dc.headings(body):
        m = re.match(r"^(F-\d{3,})\b", t)
        if lv != 3 or not m:
            continue
        f = dc.fields(body[st:end])
        pr = (f.get("优先级") or [""])[0]
        allf[m.group(1)] = pr
        if not " ".join(f.get("界面状态", [])).startswith("不适用"):
            out[m.group(1)] = pr
    return out, allf


def check(root, prd_text=None):
    errs, warns = [], []
    E = lambda w, m: errs.append("%s: %s" % (w, m))
    W = lambda w, m: warns.append("%s: %s" % (w, m))
    try:
        man = load_manifest(root)
    except (OSError, ValueError) as e:
        return None, ["manifest.js: %s" % e], [], {}
    if not isinstance(man, dict):
        return None, ["manifest.js: window.PROTOTYPE 必须是对象"], [], {}
    if man.get("schema") != SCHEMA:
        E("manifest", "schema 必须是 %s" % SCHEMA)
    if not isinstance(man.get("product"), str) or not man["product"].strip():
        E("manifest", "product 缺失")
    if man.get("platform") not in PLATFORMS:
        E("manifest", "platform 必须是 %s 之一" % "/".join(sorted(PLATFORMS)))
    pages = man.get("pages") if isinstance(man.get("pages"), list) else []
    flows = man.get("flows") if isinstance(man.get("flows"), list) else []
    accounts = man.get("accounts") if isinstance(man.get("accounts"), list) else []
    if not pages:
        E("manifest", "pages 不能为空")
    if not isinstance(man.get("flows"), list):
        E("manifest", "flows 必须是数组")

    byid, byfile, parsed = {}, {}, {}
    for i, p in enumerate(pages):
        if not isinstance(p, dict) or not re.match(r"^P-\d{2,}$", str(p.get("id", ""))):
            E("pages[%d]" % i, "id 必须形如 P-01"); continue
        pid = p["id"]
        if pid in byid:
            E(pid, "编号重复"); continue
        byid[pid] = p
        if not isinstance(p.get("title"), str) or not p["title"].strip():
            E(pid, "title 缺失")
        if not isinstance(p.get("requirements"), list):
            E(pid, "requirements 必须是数组")
        if not isinstance(p.get("auth"), bool):
            E(pid, "auth 必须是 true/false")
        f = p.get("file")
        if not isinstance(f, str) or not f:
            E(pid, "file 缺失"); continue
        if os.path.basename(f).startswith("_"):
            E(pid, "页面文件名不能以 _ 开头（_ 开头的是模板）")
        path = os.path.normpath(os.path.join(root, f))
        if not os.path.isfile(path):
            E(pid, "文件不存在：%s" % f); continue
        byfile[path] = pid
        h = parse_html(path)
        parsed[pid] = (path, h)
        if h.body_page != pid:
            E(pid, "<body data-hq-page> 是 %r，应为 %s" % (h.body_page, pid))
        states = p.get("states") if isinstance(p.get("states"), list) else []
        na = p.get("na") if isinstance(p.get("na"), dict) else None
        if na is None:
            E(pid, "na 必须是对象（没做的状态及原因）"); na = {}
        if "default" not in states:
            E(pid, "states 必须含 default")
        for s in states:
            if s not in STATES:
                E(pid, "未知状态 %s" % s)
            elif s not in h.states:
                E(pid, "声明了 %s 状态，但页面里没有 data-hq-state=\"%s\" 的区块" % (s, s))
        for s in STATES:
            if s not in states and not (isinstance(na.get(s), str) and na[s].strip()):
                E(pid, "没做 %s 状态，也没在 na 里写原因" % s)
        got = {os.path.normpath(os.path.join(os.path.dirname(path), r.split("?")[0])) for r in h.refs}
        for inc in REQUIRED_INCLUDES:  # resolved against the prototype root, wherever the page lives
            want = os.path.normpath(os.path.join(root, inc[3:]))
            if want not in got:
                E(pid, "没有引入 %s" % inc[3:])
        hexes = [x for s in h.style_text for x in HEX_RE.findall(s)]
        if hexes:
            W(pid, "页面里写死了 %d 处颜色（如 %s），改用 tokens.css 的变量" % (len(hexes), hexes[0]))

    for k in ("entry", "login"):
        v = man.get(k)
        if k == "entry" and v not in byid:
            E("manifest", "entry %r 不是已有页面" % v)
        if k == "login" and v is not None and v not in byid:
            E("manifest", "login %r 不是已有页面" % v)
    if any(p.get("auth") for p in byid.values()):
        if man.get("login") not in byid:
            E("manifest", "有需要登录的页面时必须写 login")
        if not accounts:
            E("manifest", "有需要登录的页面时至少要有 1 个演示账号")
    acc_ids = set()
    for i, a in enumerate(accounts):
        w = "accounts[%d]" % i
        if not isinstance(a, dict):
            E(w, "必须是对象"); continue
        for k in ("id", "email", "password", "note"):
            if not isinstance(a.get(k), str) or not a[k]:
                E(w, "缺 %s" % k)
        if a.get("id") in acc_ids:
            E(w, "id 重复")
        acc_ids.add(a.get("id"))

    # files: index.html + pages; local refs must exist
    all_html = [(os.path.join(root, "index.html"), None)] if os.path.isfile(os.path.join(root, "index.html")) else []
    if not all_html:
        W("index.html", "没有原型目录页 index.html")
    all_html += [(path, pid) for pid, (path, _) in parsed.items()]
    graph = {}
    testids = set()
    for path, pid in all_html:
        h = parsed[pid][1] if pid else parse_html(path)
        name = pid or "index.html"
        testids |= h.testids
        for x in h.external:
            W(name, "引用了外部资源 %s；原型要能离线打开，资源放进原型目录" % x)
        targets = set()
        for r in h.refs:
            q = os.path.normpath(os.path.join(os.path.dirname(path), r.split("#")[0].split("?")[0]))
            if not os.path.exists(q):
                E(name, "链接或资源不存在：%s" % r)
            elif q in byfile:
                targets.add(byfile[q])
        for n in h.navs:
            if n not in byid:
                E(name, "data-hq-nav 指向不存在的页面 %s" % n)
            else:
                targets.add(n)
        graph[name] = targets

    # reachability from entry (index.html links to every page by script, so start from entry itself)
    entry = man.get("entry")
    seen = set()
    if entry in byid:
        dq = deque([entry])
        while dq:
            n = dq.popleft()
            if n in seen:
                continue
            seen.add(n)
            dq.extend(graph.get(n, ()))
        for pid in byid:
            if pid not in seen and pid not in flow_pages(flows):
                W(pid, "从入口 %s 顺着链接走不到这一页（也没有流程用到它）" % entry)

    # flows
    fids = set()
    for i, fl in enumerate(flows):
        if not isinstance(fl, dict) or not re.match(r"^FL-\d{2,}$", str(fl.get("id", ""))):
            E("flows[%d]" % i, "id 必须形如 FL-01"); continue
        w = fl["id"]
        if w in fids:
            E(w, "编号重复")
        fids.add(w)
        if not isinstance(fl.get("title"), str) or not fl["title"].strip():
            E(w, "title 缺失")
        if not isinstance(fl.get("requirements"), list):
            E(w, "requirements 必须是数组")
        if fl.get("account") is not None and fl["account"] not in acc_ids:
            E(w, "account %r 不是演示账号" % fl["account"])
        steps = fl.get("steps") if isinstance(fl.get("steps"), list) else []
        if not steps:
            E(w, "steps 不能为空"); continue
        for j, st in enumerate(steps, 1):
            acts = [k for k in st if k in ACTIONS] if isinstance(st, dict) else []
            if len(acts) != 1:
                E(w, "第 %d 步必须恰好有一个动作（%s）" % (j, "/".join(sorted(ACTIONS)))); continue
            act = acts[0]
            v = st[act]
            if j == 1 and act != "goto":
                E(w, "第 1 步必须是 goto")
            if act in ("goto", "expect"):
                if v not in byid:
                    E(w, "第 %d 步 %s 的页面 %r 不存在" % (j, act, v))
            elif act == "see" and isinstance(v, str) and v.startswith("text="):
                pass
            else:
                m = TESTID_RE.match(str(v))
                if not m:
                    E(w, "第 %d 步的选择器要写成 [data-testid=…]：%r" % (j, v))
                elif m.group(1) not in testids:
                    E(w, "第 %d 步的 data-testid=%s 在页面里找不到" % (j, m.group(1)))
                if act in ("fill", "select") and not isinstance(st.get("value"), str):
                    E(w, "第 %d 步 %s 缺 value" % (j, act))
    if not flows:
        W("flows", "没有任何流程，核心流程要写成 flows 才能自动走查")

    # requirements coverage
    if prd_text is not None:
        ui, allf = prd_ui_requirements(prd_text)
        on_pages = {r for p in byid.values() for r in (p.get("requirements") or [])}
        in_flows = {r for f in flows if isinstance(f, dict) for r in (f.get("requirements") or [])}
        for r in sorted(on_pages | in_flows):
            if r not in allf and re.match(r"^F-\d{3,}$", str(r)):
                E("需求", "%s 在需求文档里不存在" % r)
        for r, pr in sorted(ui.items()):
            if r not in on_pages:
                (E if pr == "P0" else W if pr == "P1" else (lambda *a: None))("需求", "%s（%s）没有对应的页面" % (r, pr))
            if pr == "P0" and r not in in_flows:
                W("需求", "%s（P0）没有流程覆盖" % r)
    summary = {"pages": len(byid), "flows": len(fids), "accounts": len(accounts), "platform": man.get("platform"),
               "reachable": len(seen)}
    return man, errs, warns, summary


def html_files(root):
    out = []
    for d, dirs, files in os.walk(root):
        dirs[:] = sorted(x for x in dirs if x not in SKIP_DIRS and not x.startswith("."))
        out += [os.path.join(d, f) for f in sorted(files) if f.lower().endswith((".html", ".htm"))]
    return out


def prd_ids(text, prefixes=None):
    """Requirement-like IDs defined in a PRD of any format, in order of first appearance."""
    text = COMMENT_RE.sub("", text.replace("\r\n", "\n"))
    if prefixes:
        found = re.findall(r"(?<![\w-])((?:%s)(?:-\d+)+)(?![\w-])" % "|".join(map(re.escape, prefixes)), text)
    else:
        found = [x for x in ID_DEF_RE.findall(text) if x.split("-")[0] not in NOT_IDS]
    return list(dict.fromkeys(found))



def check_foreign(root, prd_text=None, allow_external=False, prefixes=None):
    """Baseline checks for an adopted prototype that is just a folder of .html files."""
    errs, warns = [], []
    files = html_files(root)
    if not files:
        return None, ["目录里没有 .html 文件"], [], {}
    root_abs = os.path.abspath(root)
    texts, refs, ext = [], 0, 0
    for path in files:
        name = os.path.relpath(path, root)
        with open(path, encoding="utf-8", errors="replace") as fh:
            text = fh.read()
        texts.append(text)
        h = Page()
        h.feed(text)
        for tag, x in h.external_res:
            ext += 1
            (warns if allow_external else errs).append(
                "%s: <%s> 引用了外部网络资源 %s；原型要能离线打开，资源放进原型目录" % (name, tag, x))
        for r in h.refs:
            refs += 1
            rel = r.split("#")[0].split("?")[0]
            if not rel:
                continue
            rel = unquote(rel)
            base = root_abs if rel.startswith("/") else os.path.dirname(os.path.abspath(path))
            q = os.path.normpath(os.path.join(base, rel.lstrip("/")))
            if not os.path.exists(q):
                errs.append("%s: 链接或资源不存在：%s" % (name, r))
    summary = {"html": len(files), "local_refs": refs, "external": ext}
    if prd_text is not None:
        ids = prd_ids(prd_text, prefixes)
        blob = "\n".join(texts)
        missing = [i for i in ids if not re.search(r"(?<![\w-])%s(?![\w]|-\d)" % re.escape(i), blob)]
        for i in missing:
            warns.append("需求: %s 在任何 HTML 文件里都没出现（只是覆盖信号，不代表没做）" % i)
        summary.update(prd_ids=len(ids), prd_ids_missing=len(missing))
    return {"files": [os.path.relpath(f, root) for f in files]}, errs, warns, summary


def flow_pages(flows):
    out = set()
    for f in flows:
        for st in (f.get("steps") or []) if isinstance(f, dict) else []:
            if isinstance(st, dict):
                for k in ("goto", "expect"):
                    if isinstance(st.get(k), str):
                        out.add(st[k])
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description="Static checks for a /hq-design prototype (read-only)")
    ap.add_argument("prototype_dir")
    ap.add_argument("--prd", metavar="FILE")
    ap.add_argument("--format", choices=["md", "json"], default="md")
    ap.add_argument("--foreign", action="store_true", help="treat as a foreign-format prototype (auto when no manifest.js)")
    ap.add_argument("--allow-external", action="store_true", help="foreign mode: external network resources are warnings, not errors")
    ap.add_argument("--id-prefixes", metavar="P1,P2", help="foreign mode with --prd: only collect IDs with these prefixes (anywhere in the PRD)")
    a = ap.parse_args(argv)
    if not os.path.isdir(a.prototype_dir):
        print("错误: 不是目录：%s" % a.prototype_dir, file=sys.stderr)
        return 2
    prd = None
    if a.prd:
        try:
            with open(a.prd, encoding="utf-8") as fh:
                prd = fh.read()
        except OSError as e:
            print("错误: 读不了 %s: %s" % (a.prd, e), file=sys.stderr)
            return 2
    foreign = a.foreign or not os.path.isfile(os.path.join(a.prototype_dir, "manifest.js"))
    if foreign:
        prefixes = [x.strip() for x in (a.id_prefixes or "").split(",") if x.strip()]
        man, errs, warns, summary = check_foreign(a.prototype_dir, prd, a.allow_external, prefixes)
    else:
        man, errs, warns, summary = check(a.prototype_dir, prd)
    if man is None:
        print("错误: %s" % errs[0], file=sys.stderr)
        return 2
    mode = "foreign" if foreign else "hq"
    if a.format == "json":
        out = {"mode": mode, "errors": errs, "warnings": warns, "summary": summary}
        if foreign:
            out["files"] = man["files"]
        print(json.dumps(out, ensure_ascii=False, indent=2))
    else:
        print("# 原型检查（%s）：%s\n" % ("外来格式，无 manifest.js" if foreign else "hq 格式", a.prototype_dir))
        print("、".join("%s %s" % (k, v) for k, v in summary.items()))
        if foreign:
            print("\n## 页面（%d）" % len(man["files"]))
            print("\n".join("- " + x for x in man["files"]))
        print("\n## 错误（%d）" % len(errs))
        print("\n".join("- " + x for x in errs) or "- 无")
        print("\n## 警告（%d）" % len(warns))
        print("\n".join("- " + x for x in warns) or "- 无")
    return 1 if errs else 0


if __name__ == "__main__":
    sys.exit(main())

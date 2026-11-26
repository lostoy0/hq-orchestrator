#!/usr/bin/env python3
"""Mechanical checks for stage documents. Read-only.

  doc-check.py prd <prd.md>            requirements doc written by /hq-prd
  doc-check.py research <report.md>    competitor research written by /hq-research

Exit codes: 0 no errors (warnings allowed), 1 errors found, 2 bad arguments / unreadable file.
Formats: skills/hq-prd/template.md, skills/hq-research/template.md
"""
import argparse
import json
import re
import sys

# 上线必需项（skills/hq-prd/template.md 第 8 节的行；两处保持一致，tests/test_doc_check.py 会核对）
LAUNCH_ITEMS = ["注册", "登录", "找回密码", "退出登录", "注销账号", "个人资料", "设置", "消息通知",
                "意见反馈", "帮助与客服", "隐私政策", "用户协议", "新手引导", "空状态", "错误与网络异常",
                "搜索", "数据导出", "支付与退款", "管理后台", "内容审核", "版本更新", "多语言",
                "数据看板", "备份与恢复"]
UI_STATES = ["空", "加载", "错误", "无权限", "首次使用"]
NFR_KINDS = {"性能", "可用性", "安全", "隐私", "兼容", "可访问性", "国际化", "合规", "可观测"}
PRIO = {"P0", "P1", "P2"}
PRD_SECTIONS = ["概述", "范围", "用户旅程", "功能需求", "非功能需求", "商业化", "数据与埋点",
                "上线必需项", "风险", "假设与待确认", "需求索引"]
RESEARCH_SECTIONS = ["结论摘要", "调研范围", "竞品概览", "竞品详情", "对比矩阵", "定价", "用户痛点",
                     "机会点", "对需求的建议", "假设与待确认", "来源"]
COMP_TYPES = {"直接", "间接", "替代"}
COMP_DEPTH = {"深挖", "简析"}
MIN_CITES = {"深挖": 5, "简析": 2}
OFFLINE_BANNER = "未联网"
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
CITE_RE = re.compile(r"\[(S\d+)\]")
COMMENT_RE = re.compile(r"<!--.*?-->", re.S)
PLACEHOLDER_RE = re.compile(r"<[^<>\n/]{1,20}>")  # template placeholders such as <功能名>
FIELD_RE = re.compile(r"^- ([^：:\s][^：:]{0,15})[：:]\s*(.*)$")


def split_frontmatter(text):
    meta = {}
    if not text.startswith("---\n"):
        return meta, text, False
    end = text.find("\n---", 4)
    if end < 0:
        return meta, text, False
    for line in text[4:end].splitlines():
        line = line.split("#", 1)[0].rstrip()
        if ":" not in line:
            continue
        k, v = line.split(":", 1)
        meta[k.strip()] = v.strip()
    return meta, text[end + 4:].lstrip("\n"), True


def headings(body):
    """[(level, title, start, end)] — end is where the next heading of the same or higher level starts."""
    hs = [(len(m.group(1)), m.group(2).strip(), m.start()) for m in re.finditer(r"^(#{1,6})\s+(.+?)\s*$", body, re.M)]
    out = []
    for i, (lv, t, st) in enumerate(hs):
        end = len(body)
        for lv2, _, st2 in hs[i + 1:]:
            if lv2 <= lv:
                end = st2
                break
        out.append((lv, t, st, end))
    return out


def section(body, hs, keyword, level=2):
    for lv, t, st, end in hs:
        if lv == level and keyword in t:
            return body[st:end]
    return None


def fields(block):
    """Top-level '- 字段：值' lines; indented lines and numbered items below a field belong to it."""
    out, cur = {}, None
    for line in block.splitlines()[1:]:
        m = FIELD_RE.match(line)
        if m:
            cur = m.group(1).strip()
            out[cur] = [m.group(2).strip()]
        elif cur and line.strip() and (line.startswith((" ", "\t")) or re.match(r"^\d+[.、)]", line.strip())):
            out[cur].append(line.strip())
        elif line.startswith("#"):
            cur = None
    return out


def items(lines):
    """Numbered or bulleted sub-items under a field (the field's own line excluded)."""
    return [x for x in lines[1:] if re.match(r"^(\d+[.、)]|[-*])\s*\S", x)]


def table_rows(block):
    rows = []
    for line in block.splitlines():
        line = line.strip()
        if not line.startswith("|") or re.match(r"^\|[\s:|-]+\|?$", line):
            continue
        rows.append([c.strip() for c in line.strip("|").split("|")])
    return rows[1:] if rows else []  # drop header


def blank(v):
    return not v or v.strip() in ("", "…", "...", "-", "<", "无")


def check_common(meta, has_fm, stage, E, W):
    if not has_fm:
        E("元数据", "文件开头缺少 --- 元数据块")
        return
    if meta.get("hq_stage") != stage:
        E("元数据", "hq_stage 必须是 %s" % stage)
    if not str(meta.get("version", "")).isdigit():
        E("元数据", "version 必须是整数")
    if meta.get("status") not in ("draft", "reviewed", "approved"):
        E("元数据", "status 必须是 draft/reviewed/approved")
    if not DATE_RE.match(meta.get("updated", "")):
        E("元数据", "updated 必须是 YYYY-MM-DD")
    if "based_on" not in meta:
        E("元数据", "缺 based_on（没有上游写 []）")


def open_decisions(body, hs):
    s = section(body, hs, "假设与待确认") or ""
    return sorted(set(re.findall(r"\bD-\d{2,}\b", s)))


def check_prd(text):
    errs, warns = [], []
    E = lambda w, m: errs.append("%s: %s" % (w, m))
    W = lambda w, m: warns.append("%s: %s" % (w, m))
    meta, body, has_fm = split_frontmatter(text)
    body = COMMENT_RE.sub("", body)
    check_common(meta, has_fm, "prd", E, W)
    hs = headings(body)
    for k in PRD_SECTIONS:
        if section(body, hs, k) is None:
            E("章节", "缺少二级标题“%s”" % k)

    feats, nfrs = {}, {}
    for lv, t, st, end in hs:
        m = re.match(r"^(F|NFR)-(\d{3,})\b\s*(.*)$", t)
        if lv != 3 or not m:
            continue
        rid, name = "%s-%s" % (m.group(1), m.group(2)), m.group(3).strip()
        w = rid
        target = feats if m.group(1) == "F" else nfrs
        if rid in feats or rid in nfrs:
            E(w, "编号重复"); continue
        f = fields(body[st:end])
        target[rid] = f
        if blank(name) or PLACEHOLDER_RE.search(name):
            E(w, "标题缺少名称")
        ph = PLACEHOLDER_RE.findall(body[st:end].split("\n", 1)[-1])
        if ph:
            E(w, "还有占位符：%s" % "、".join(sorted(set(ph))[:3]))
        prio = (f.get("优先级") or [""])[0]
        if prio not in PRIO:
            E(w, "优先级必须是 P0/P1/P2")
        if not items(f.get("验收标准", [])):
            E(w, "验收标准至少 1 条（写成编号列表）")
        if m.group(1) == "F":
            story = (f.get("用户故事") or [""])[0]
            if blank(story) or "<" in story:
                E(w, "缺用户故事")
            elif not ("作为" in story and "我想" in story and "以便" in story):
                W(w, "用户故事建议写成“作为…，我想…，以便…”")
            st_ = " ".join(f.get("界面状态", []))
            if not st_:
                E(w, "缺界面状态（空、加载、错误、无权限、首次使用；不适用的写“不适用（原因）”）")
            elif not st_.startswith("不适用"):
                miss = [s for s in UI_STATES if not re.search(r"(^|[/／\s；;])" + s + r"[：:]", st_)]
                if miss:
                    E(w, "界面状态缺少：%s" % "、".join(miss))
                if "…" in st_:
                    E(w, "界面状态还有占位符“…”")
            if blank((f.get("埋点") or [""])[0]):
                W(w, "没写埋点")
        else:
            kind = (f.get("类别") or [""])[0]
            if kind not in NFR_KINDS:
                E(w, "类别必须是 %s 之一" % "/".join(sorted(NFR_KINDS)))
            if blank((f.get("要求") or [""])[0]):
                E(w, "缺要求")
    if not feats:
        E("功能需求", "没有任何 F-xxx 功能（三级标题“### F-001 名称”）")
    if not nfrs:
        E("非功能需求", "没有任何 NFR-xxx（三级标题“### NFR-001 名称”）")
    p0 = [k for k, f in feats.items() if (f.get("优先级") or [""])[0] == "P0"]
    if feats and not p0:
        E("功能需求", "没有 P0 功能")
    if feats and len(p0) / len(feats) > 0.6 and len(feats) >= 5:
        W("功能需求", "P0 占 %d/%d，首版范围可能偏大" % (len(p0), len(feats)))
    kinds = {(f.get("类别") or [""])[0] for f in nfrs.values()}
    for k in ("性能", "安全", "隐私"):
        if nfrs and k not in kinds:
            W("非功能需求", "没有“%s”类的非功能需求" % k)

    # 需求索引
    idx = section(body, hs, "需求索引")
    if idx is not None:
        rows = {r[0]: r for r in table_rows(idx) if r and re.match(r"^(F|NFR)-\d{3,}$", r[0])}
        allids = dict(feats, **nfrs)
        for rid in sorted(set(allids) - set(rows)):
            E("需求索引", "缺少 %s" % rid)
        for rid in sorted(set(rows) - set(allids)):
            E("需求索引", "%s 在正文里不存在" % rid)
        for rid in sorted(set(rows) & set(allids)):
            r = rows[rid]
            pr = (allids[rid].get("优先级") or [""])[0]
            if len(r) >= 3 and r[2] != pr:
                E("需求索引", "%s 的优先级 %s 和正文 %s 不一致" % (rid, r[2], pr))
            if len(r) < 4 or blank(r[3]):
                W("需求索引", "%s 没写建议版本" % rid)

    # 上线必需项
    lc = section(body, hs, "上线必需项")
    if lc is not None:
        rows = {r[0]: r for r in table_rows(lc) if r}
        for it in LAUNCH_ITEMS:
            r = rows.get(it)
            if not r:
                E("上线必需项", "缺少“%s”这一行" % it); continue
            v = r[1] if len(r) > 1 else ""
            if v.startswith("包含"):
                ref = " ".join(r[1:])
                if not re.search(r"\b(F|NFR)-\d{3,}\b", ref):
                    E("上线必需项", "“%s”写了包含，但没写对应需求编号" % it)
            elif re.match(r"^(不做|不适用)[：:]\s*\S", v):
                pass
            else:
                E("上线必需项", "“%s”的结论要写“包含（编号）”“不做：原因”或“不适用：原因”" % it)

    ds = open_decisions(body, hs)
    if ds and meta.get("status") == "approved":
        E("元数据", "还有待决定事项 %s，status 不能是 approved" % ", ".join(ds))
    summary = {"features": len(feats), "p0": len(p0), "nfrs": len(nfrs), "open_decisions": ds}
    return errs, warns, summary


def check_research(text):
    errs, warns = [], []
    E = lambda w, m: errs.append("%s: %s" % (w, m))
    W = lambda w, m: warns.append("%s: %s" % (w, m))
    meta, body, has_fm = split_frontmatter(text)
    body = COMMENT_RE.sub("", body)
    check_common(meta, has_fm, "research", E, W)
    mode = meta.get("mode")
    if mode not in ("online", "offline"):
        E("元数据", "mode 必须是 online 或 offline")
    try:
        target = int(meta.get("competitors_target", ""))
        deep_target = int(meta.get("deep_target", ""))
    except ValueError:
        E("元数据", "competitors_target、deep_target 必须是整数")
        target = deep_target = None
    if mode == "offline" and OFFLINE_BANNER not in body.split("\n## ", 1)[0]:
        E("离线说明", "mode: offline 时，正文开头必须保留“本报告未联网…”的说明")
    hs = headings(body)
    for k in RESEARCH_SECTIONS:
        if section(body, hs, k) is None:
            E("章节", "缺少二级标题“%s”" % k)

    # sources
    src = section(body, hs, "来源") or ""
    sources = {}
    for r in table_rows(src):
        if not r or not re.match(r"^S\d+$", r[0]):
            continue
        sid = r[0]
        if sid in sources:
            E("来源", "%s 重复" % sid); continue
        sources[sid] = r
        if len(r) < 4 or not re.match(r"^https?://\S+\.\S+", r[2]):
            E("来源", "%s 的链接必须是 http(s) 地址" % sid)
        if len(r) < 4 or not DATE_RE.match(r[3]):
            E("来源", "%s 的访问日期必须是 YYYY-MM-DD" % sid)
    body_wo_src = body.replace(src, "") if src else body
    cited = set(CITE_RE.findall(body_wo_src))
    for sid in sorted(cited - set(sources), key=lambda x: int(x[1:])):
        E("来源", "引用了 [%s]，但来源表里没有" % sid)
    for sid in sorted(set(sources) - cited, key=lambda x: int(x[1:])):
        W("来源", "%s 没有被引用" % sid)

    # competitors
    comps = {}
    for lv, t, st, end in hs:
        m = re.match(r"^(C-\d{2,})\b\s*(.*)$", t)
        if lv != 3 or not m:
            continue
        cid = m.group(1)
        if cid in comps:
            E(cid, "编号重复"); continue
        blk = body[st:end]
        f = fields(blk)
        comps[cid] = f
        if blank(m.group(2)) or "<" in m.group(2):
            E(cid, "标题缺少名称")
        typ, dep = (f.get("类型") or [""])[0], (f.get("深度") or [""])[0]
        if typ not in COMP_TYPES:
            E(cid, "类型必须是 直接/间接/替代")
        if dep not in COMP_DEPTH:
            E(cid, "深度必须是 深挖/简析")
        if mode == "online" and dep in MIN_CITES:
            n = len(set(CITE_RE.findall(blk)))
            if n < MIN_CITES[dep]:
                E(cid, "%s的竞品至少引用 %d 个不同来源，现在 %d 个" % (dep, MIN_CITES[dep], n))
    deep = [c for c, f in comps.items() if (f.get("深度") or [""])[0] == "深挖"]
    if not comps:
        E("竞品详情", "没有任何竞品（三级标题“### C-01 名称”）")
    elif target is not None:
        if len(comps) < target:
            W("竞品详情", "竞品 %d 家，少于目标 %d 家；请在“调研范围”说明原因" % (len(comps), target))
        if len(deep) < deep_target:
            W("竞品详情", "深挖 %d 家，少于目标 %d 家" % (len(deep), deep_target))
    ov = section(body, hs, "竞品概览")
    if ov is not None:
        ids = {r[0] for r in table_rows(ov) if r and re.match(r"^C-\d{2,}$", r[0])}
        for c in sorted(set(comps) - ids):
            E("竞品概览", "缺少 %s" % c)
        for c in sorted(ids - set(comps)):
            E("竞品概览", "%s 在竞品详情里不存在" % c)
    sug = section(body, hs, "对需求的建议")
    if sug is not None and len([l for l in sug.splitlines()[1:] if l.strip()]) == 0:
        E("对需求的建议", "不能为空")
    if mode == "online" and OFFLINE_BANNER in body.split("\n## ", 1)[0]:
        W("离线说明", "mode: online，却保留了“未联网”说明，确认后删掉")
    summary = {"competitors": len(comps), "deep": len(deep), "sources": len(sources), "mode": mode,
               "open_decisions": open_decisions(body, hs)}
    return errs, warns, summary


def main(argv=None):
    ap = argparse.ArgumentParser(description="Mechanical checks for /hq-prd and /hq-research documents (read-only)")
    ap.add_argument("kind", choices=["prd", "research"])
    ap.add_argument("file")
    ap.add_argument("--format", choices=["md", "json"], default="md")
    a = ap.parse_args(argv)
    try:
        with open(a.file, encoding="utf-8") as fh:
            text = fh.read()
    except OSError as e:
        print("错误: 读不了 %s: %s" % (a.file, e), file=sys.stderr)
        return 2
    errs, warns, summary = (check_prd if a.kind == "prd" else check_research)(text.replace("\r\n", "\n"))
    if a.format == "json":
        print(json.dumps({"errors": errs, "warnings": warns, "summary": summary}, ensure_ascii=False, indent=2))
    else:
        print("# %s 检查：%s\n" % ("需求文档" if a.kind == "prd" else "竞品调研", a.file))
        print("、".join("%s %s" % (k, v) for k, v in summary.items()))
        print("\n## 错误（%d）" % len(errs))
        print("\n".join("- " + x for x in errs) or "- 无")
        print("\n## 警告（%d）" % len(warns))
        print("\n".join("- " + x for x in warns) or "- 无")
    return 1 if errs else 0


if __name__ == "__main__":
    sys.exit(main())

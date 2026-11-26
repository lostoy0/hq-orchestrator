import json
import os
import re
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, "skills", "hq", "scripts", "doc-check.py")
PRD_TPL = os.path.join(ROOT, "skills", "hq-prd", "template.md")
RES_TPL = os.path.join(ROOT, "skills", "hq-research", "template.md")

sys.path.insert(0, os.path.dirname(SCRIPT))
import importlib.util  # noqa: E402
_spec = importlib.util.spec_from_file_location("doc_check", SCRIPT)
dc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(dc)

LAUNCH_ROWS = "\n".join(
    "| %s | %s | %s |" % (it, "包含" if it in ("注册", "登录") else "不做：首版不需要", "F-001" if it in ("注册", "登录") else "")
    for it in dc.LAUNCH_ITEMS)

PRD = """---
hq_stage: prd
version: 2
based_on: [competitors@1]
status: draft
updated: 2026-11-26
---

# 记账 需求文档

## 1. 概述
### 目标用户
独立开发者。
## 2. 范围
首版只做记账。
## 3. 用户旅程与信息架构
略。
## 4. 功能需求

### F-001 邮箱注册登录

- 模块：账号
- 优先级：P0
- 用户故事：作为新用户，我想用邮箱注册，以便同步数据
- 验收标准：
  1. 注册后收到验证邮件
  2. 密码错误 5 次锁定 10 分钟
- 界面状态：空：无 / 加载：按钮转圈 / 错误：字段下方提示 / 无权限：不适用（公开页面） / 首次使用：引导卡片
- 权限：所有人
- 埋点：signup_submit
- 依赖：邮件服务

### F-002 记一笔

- 优先级：P1
- 用户故事：作为用户，我想快速记一笔，以便知道钱花在哪
- 验收标准：
  1. 3 步内完成
- 界面状态：不适用（只有接口）
- 埋点：entry_create

## 5. 非功能需求

### NFR-001 首屏速度

- 类别：性能
- 优先级：P0
- 要求：首屏 2 秒内
- 验收标准：
  1. Lighthouse 测 3 次取中位数

### NFR-002 数据安全

- 类别：安全
- 优先级：P0
- 要求：密码加盐哈希
- 验收标准：
  1. 代码审查

### NFR-003 个人信息

- 类别：隐私
- 优先级：P0
- 要求：可导出、可删除
- 验收标准：
  1. 注销后 30 天内删除

## 6. 商业化
订阅。
## 7. 数据与埋点
见上。
## 8. 上线必需项核对

| 项目 | 结论 | 对应需求 |
|---|---|---|
""" + LAUNCH_ROWS + """

## 9. 风险与依赖
无。
## 10. 假设与待确认
- A-01 用户愿意用邮箱注册
## 11. 需求索引

| 编号 | 标题 | 优先级 | 建议版本 | 出处 |
|---|---|---|---|---|
| F-001 | 邮箱注册登录 | P0 | MVP | 第 4 节 |
| F-002 | 记一笔 | P1 | MVP | 第 4 节 |
| NFR-001 | 首屏速度 | P0 | MVP | 第 5 节 |
| NFR-002 | 数据安全 | P0 | MVP | 第 5 节 |
| NFR-003 | 个人信息 | P0 | MVP | 第 5 节 |
"""


def comp(cid, depth, cites):
    return """### %s 产品%s

- 类型：直接
- 深度：%s
- 官网：https://example.com
- 定位与目标用户：个人记账 %s
""" % (cid, cid, depth, " ".join("[S%d]" % i for i in cites))


RESEARCH = """---
hq_stage: research
version: 1
based_on: []
status: draft
updated: 2026-11-26
competitors_target: 3
deep_target: 1
market: cn
mode: online
---

# 记账 竞品调研

## 结论摘要
格局分散 [S1]。
## 调研范围
- 产品类别：记账
## 竞品概览

| 编号 | 名称 | 类型 | 深度 | 一句话定位 | 目标用户 | 商业模式 | 来源 |
|---|---|---|---|---|---|---|---|
| C-01 | A | 直接 | 深挖 | x | y | 订阅 | [S1] |
| C-02 | B | 直接 | 简析 | x | y | 免费 | [S6] |
| C-03 | C | 替代 | 简析 | x | y | 免费 | [S7] |

## 竞品详情

""" + comp("C-01", "深挖", [1, 2, 3, 4, 5]) + comp("C-02", "简析", [6, 2]) + comp("C-03", "简析", [7, 1]) + """
## 对比矩阵
略。
## 定价对比
略。
## 用户痛点与评价
略。
## 机会点
略。
## 对需求的建议
- 首版做自动分类 | C-01 [S3] | P1
## 假设与待确认
## 来源

| 编号 | 标题 | 链接 | 访问日期 |
|---|---|---|---|
""" + "\n".join("| S%d | 页面%d | https://example.com/%d | 2026-11-26 |" % (i, i, i) for i in range(1, 8)) + "\n"


def run(kind, text):
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "doc.md")
        with open(p, "w", encoding="utf-8") as fh:
            fh.write(text)
        r = subprocess.run([sys.executable, SCRIPT, kind, p, "--format", "json"], capture_output=True, text=True)
        return r.returncode, json.loads(r.stdout) if r.stdout.strip().startswith("{") else None


def read(p):
    with open(p, encoding="utf-8") as fh:
        return fh.read()


class PrdCheckTest(unittest.TestCase):
    def test_valid(self):
        rc, out = run("prd", PRD)
        self.assertEqual(rc, 0, out)
        self.assertEqual(out["summary"]["features"], 2)
        self.assertEqual(out["summary"]["nfrs"], 3)

    def errs(self, text, kind="prd"):
        rc, out = run(kind, text)
        self.assertEqual(rc, 1, out)
        return "\n".join(out["errors"])

    def test_missing_frontmatter_and_section(self):
        e = self.errs(PRD.split("---\n", 2)[2].replace("## 6. 商业化", "## 6. 其他"))
        self.assertIn("元数据", e)
        self.assertIn("商业化", e)

    def test_feature_fields(self):
        t = PRD.replace("- 优先级：P1", "- 优先级：高").replace("- 用户故事：作为用户，我想快速记一笔，以便知道钱花在哪\n", "")
        e = self.errs(t)
        self.assertIn("F-002: 优先级", e)
        self.assertIn("F-002: 缺用户故事", e)

    def test_ui_states(self):
        e = self.errs(PRD.replace(" / 首次使用：引导卡片", ""))
        self.assertIn("界面状态缺少：首次使用", e)

    def test_acceptance_required(self):
        e = self.errs(PRD.replace("  1. 3 步内完成\n", ""))
        self.assertIn("F-002: 验收标准至少 1 条", e)

    def test_index_consistency(self):
        e = self.errs(PRD.replace("| F-002 | 记一笔 | P1 |", "| F-002 | 记一笔 | P0 |").replace("| NFR-003 | 个人信息 | P0 | MVP | 第 5 节 |\n", ""))
        self.assertIn("F-002 的优先级 P0 和正文 P1 不一致", e)
        self.assertIn("缺少 NFR-003", e)

    def test_launch_items(self):
        e = self.errs(PRD.replace("| 注销账号 | 不做：首版不需要 |", "| 注销账号 | |").replace("| 登录 | 包含 | F-001 |", "| 登录 | 包含 | |").replace("| 搜索 |", "| 检索 |"))
        self.assertIn("“注销账号”的结论", e)
        self.assertIn("“登录”写了包含，但没写对应需求编号", e)
        self.assertIn("缺少“搜索”这一行", e)

    def test_open_decision_blocks_approved(self):
        t = PRD.replace("status: draft", "status: approved").replace("- A-01 用户愿意用邮箱注册", "- D-01 订阅还是买断")
        self.assertIn("status 不能是 approved", self.errs(t))
        rc, out = run("prd", t.replace("status: approved", "status: draft"))
        self.assertEqual((rc, out["summary"]["open_decisions"]), (0, ["D-01"]))

    def test_placeholders(self):
        e = self.errs(PRD.replace("2. 密码错误 5 次锁定 10 分钟", "2. <可检验的条件>").replace("### F-002 记一笔", "### F-002 <功能名>"))
        self.assertIn("F-001: 还有占位符：<可检验的条件>", e)
        self.assertIn("F-002: 标题缺少名称", e)

    def test_duplicate_id(self):
        self.assertIn("编号重复", self.errs(PRD.replace("### F-002 记一笔", "### F-001 记一笔")))

    def test_warnings(self):
        rc, out = run("prd", PRD.replace("以便同步数据", "同步数据").replace("- 类别：隐私", "- 类别：合规"))
        self.assertEqual(rc, 0)
        w = "\n".join(out["warnings"])
        self.assertIn("作为…，我想…，以便…", w)
        self.assertIn("“隐私”类", w)

    def test_template_matches_checker(self):
        tpl = read(PRD_TPL)
        rows = re.findall(r"^\| ([^|]+?) \| \| \|$", tpl.split("## 8.")[1].split("## 9.")[0], re.M)
        self.assertEqual(rows, dc.LAUNCH_ITEMS)
        rc, out = run("prd", tpl)
        self.assertFalse([x for x in out["errors"] if "缺少二级标题" in x], out["errors"])


class ResearchCheckTest(unittest.TestCase):
    def errs(self, text):
        rc, out = run("research", text)
        self.assertEqual(rc, 1, out)
        return "\n".join(out["errors"])

    def test_valid(self):
        rc, out = run("research", RESEARCH)
        self.assertEqual(rc, 0, out)
        self.assertEqual(out["warnings"], [])
        self.assertEqual((out["summary"]["competitors"], out["summary"]["deep"], out["summary"]["sources"]), (3, 1, 7))

    def test_citations(self):
        e = self.errs(RESEARCH.replace("[S5]", "[S9]"))
        self.assertIn("引用了 [S9]", e)
        rc, out = run("research", RESEARCH.replace("[S7]", "[S6]"))
        self.assertTrue(any("S7 没有被引用" in w for w in out["warnings"]))

    def test_min_citations_per_depth(self):
        e = self.errs(RESEARCH.replace("[S1] [S2] [S3] [S4] [S5]", "[S1] [S2] [S3] [S4]"))
        self.assertIn("C-01: 深挖的竞品至少引用 5 个不同来源", e)

    def test_source_table(self):
        e = self.errs(RESEARCH.replace("https://example.com/2 | 2026-11-26", "example.com/2 | 昨天"))
        self.assertIn("S2 的链接", e)
        self.assertIn("S2 的访问日期", e)

    def test_fields_and_overview(self):
        e = self.errs(RESEARCH.replace("- 类型：直接\n- 深度：简析", "- 类型：竞品\n- 深度：简析", 1)
                      .replace("| C-03 | C |", "| C-04 | C |"))
        self.assertIn("C-02: 类型", e)
        self.assertIn("竞品概览: 缺少 C-03", e)
        self.assertIn("C-04 在竞品详情里不存在", e)

    def test_target_counts_are_warnings(self):
        rc, out = run("research", RESEARCH.replace("competitors_target: 3", "competitors_target: 10").replace("deep_target: 1", "deep_target: 3"))
        self.assertEqual(rc, 0)
        w = "\n".join(out["warnings"])
        self.assertIn("少于目标 10 家", w)
        self.assertIn("深挖 1 家", w)

    def test_offline(self):
        t = RESEARCH.replace("mode: online", "mode: offline")
        self.assertIn("未联网", self.errs(t))
        t2 = t.replace("# 记账 竞品调研\n", "# 记账 竞品调研\n\n> 本报告未联网，仅依据模型训练知识（截至 2026-06），所有结论未经核实。\n")
        t2 = t2.replace("[S1] [S2] [S3] [S4] [S5]", "")  # offline: citation minimum does not apply
        rc, out = run("research", t2)
        self.assertEqual(rc, 0, out)
        rc, out = run("research", t2.replace("mode: offline", "mode: online").replace("[S7]", "[S7] [S3] [S4] [S5]"))
        self.assertTrue(any("却保留了“未联网”说明" in w for w in out["warnings"]), out)

    def test_template_sections(self):
        rc, out = run("research", read(RES_TPL))
        self.assertFalse([x for x in out["errors"] if "缺少二级标题" in x], out["errors"])

    def test_bad_args(self):
        r = subprocess.run([sys.executable, SCRIPT, "prd", "/nonexistent.md"], capture_output=True, text=True)
        self.assertEqual(r.returncode, 2)
        r = subprocess.run([sys.executable, SCRIPT, "design", PRD_TPL], capture_output=True, text=True)
        self.assertEqual(r.returncode, 2)


if __name__ == "__main__":
    unittest.main()

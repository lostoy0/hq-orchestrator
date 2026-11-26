import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CHECK = os.path.join(ROOT, "skills", "hq", "scripts", "prototype-check.py")
WALK = os.path.join(ROOT, "skills", "hq", "scripts", "prototype-walk.mjs")
STARTER = os.path.join(ROOT, "skills", "hq-design", "prototype-starter")


def read(p):
    with open(p, encoding="utf-8") as fh:
        return fh.read()


def write(p, text):
    with open(p, "w", encoding="utf-8") as fh:
        fh.write(text)


class Proto:
    """A temp copy of the starter kit that tests can mutate."""

    def __enter__(self):
        self.tmp = tempfile.mkdtemp()
        self.dir = os.path.join(self.tmp, "prototype")
        shutil.copytree(STARTER, self.dir)
        return self

    def __exit__(self, *a):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def manifest(self):
        t = read(os.path.join(self.dir, "manifest.js"))
        return json.loads(t[t.index("{"):t.rindex("}") + 1])

    def set_manifest(self, m):
        write(os.path.join(self.dir, "manifest.js"), "window.PROTOTYPE = " + json.dumps(m, ensure_ascii=False, indent=2) + ";\n")

    def edit(self, rel, old, new):
        p = os.path.join(self.dir, rel)
        t = read(p)
        assert old in t, (rel, old)
        write(p, t.replace(old, new, 1))

    def check(self, *args):
        r = subprocess.run([sys.executable, CHECK, self.dir, "--format", "json", *args], capture_output=True, text=True)
        return r.returncode, json.loads(r.stdout) if r.stdout.strip().startswith("{") else r.stderr


PRD = """---
hq_stage: prd
version: 1
based_on: []
status: draft
updated: 2026-11-26
---
# x
## 4. 功能需求
### F-001 登录
- 优先级：P0
- 界面状态：空：无 / 加载：转圈 / 错误：提示 / 无权限：不适用（公开） / 首次使用：无
### F-002 事项列表
- 优先级：P0
- 界面状态：空：引导 / 加载：骨架 / 错误：重试 / 无权限：提示 / 首次使用：引导
### F-003 导出
- 优先级：P1
- 界面状态：空：无 / 加载：无 / 错误：无 / 无权限：无 / 首次使用：无
### F-004 定时同步
- 优先级：P0
- 界面状态：不适用（后台任务）
"""


class PrototypeCheckTest(unittest.TestCase):
    def test_starter_is_clean(self):
        with Proto() as p:
            rc, out = p.check()
            self.assertEqual(rc, 0, out)
            self.assertEqual(out["warnings"], [])
            self.assertEqual((out["summary"]["pages"], out["summary"]["flows"]), (2, 1))

    def errs(self, p, *args):
        rc, out = p.check(*args)
        self.assertEqual(rc, 1, out)
        return "\n".join(out["errors"])

    def test_state_blocks_and_na(self):
        with Proto() as p:
            m = p.manifest()
            m["pages"][0]["states"].append("empty")
            del m["pages"][0]["na"]["forbidden"]
            p.set_manifest(m)
            e = self.errs(p)
            self.assertIn("P-01: 声明了 empty 状态，但页面里没有", e)
            self.assertIn("P-01: 没做 forbidden 状态，也没在 na 里写原因", e)

    def test_multi_state_block_counts(self):
        with Proto() as p:  # login's submit button sits in data-hq-state="default error"
            p.edit("pages/login.html", '<section data-hq-state="error" hidden>', '<section data-hq-state="x" hidden>')
            rc, out = p.check()
            self.assertEqual(rc, 0, out)

    def test_body_page_includes_and_links(self):
        with Proto() as p:
            p.edit("pages/home.html", 'data-hq-page="P-02"', 'data-hq-page="P-09"')
            p.edit("pages/home.html", '<script src="../data/seed.js"></script>', "")
            p.edit("pages/home.html", 'href="home.html">重试', 'href="retry.html">重试')
            e = self.errs(p)
            self.assertIn("应为 P-02", e)
            self.assertIn("没有引入 data/seed.js", e)
            self.assertIn("链接或资源不存在：retry.html", e)

    def test_flows(self):
        with Proto() as p:
            m = p.manifest()
            m["flows"][0]["steps"][1] = {"fill": "[data-testid=nope]", "value": "x"}
            m["flows"][0]["steps"][3] = {"click": "#submit"}
            m["flows"][0]["steps"][4] = {"expect": "P-99"}
            m["flows"].append({"id": "FL-02", "title": "t", "requirements": [], "steps": [{"click": "[data-testid=submit]"}]})
            p.set_manifest(m)
            e = self.errs(p)
            self.assertIn("data-testid=nope 在页面里找不到", e)
            self.assertIn("选择器要写成 [data-testid=…]", e)
            self.assertIn("页面 'P-99' 不存在", e)
            self.assertIn("FL-02: 第 1 步必须是 goto", e)

    def test_auth_needs_login_and_accounts(self):
        with Proto() as p:
            m = p.manifest()
            m["accounts"] = []
            m["login"] = None
            p.set_manifest(m)
            e = self.errs(p)
            self.assertIn("必须写 login", e)
            self.assertIn("至少要有 1 个演示账号", e)

    def test_warnings_external_and_colors(self):
        with Proto() as p:
            p.edit("pages/home.html", "</head>", '<script src="https://cdn.example.com/x.js"></script>\n</head>')
            p.edit("pages/home.html", '<div class="title">首页</div>', '<div class="title" style="color: #ff0000">首页</div>')
            rc, out = p.check()
            self.assertEqual(rc, 0, out)
            w = "\n".join(out["warnings"])
            self.assertIn("外部资源 https://cdn.example.com/x.js", w)
            self.assertIn("写死了 1 处颜色", w)

    def test_prd_coverage(self):
        with Proto() as p:
            m = p.manifest()
            m["pages"][0]["requirements"] = ["F-001"]
            m["flows"][0]["requirements"] = ["F-001"]
            p.set_manifest(m)
            write(os.path.join(p.tmp, "prd.md"), PRD)
            rc, out = p.check("--prd", os.path.join(p.tmp, "prd.md"))
            self.assertEqual(rc, 1)
            e, w = "\n".join(out["errors"]), "\n".join(out["warnings"])
            self.assertIn("F-002（P0）没有对应的页面", e)
            self.assertNotIn("F-004", e + w)  # no UI
            self.assertIn("F-003（P1）没有对应的页面", w)
            self.assertIn("F-002（P0）没有流程覆盖", w)
            m["pages"][1]["requirements"] = ["F-002", "F-009"]
            p.set_manifest(m)
            rc, out = p.check("--prd", os.path.join(p.tmp, "prd.md"))
            self.assertIn("F-009 在需求文档里不存在", "\n".join(out["errors"]))

    def test_unreachable_page_warning(self):
        with Proto() as p:
            shutil.copy(os.path.join(p.dir, "pages", "home.html"), os.path.join(p.dir, "pages", "orphan.html"))
            p.edit("pages/orphan.html", 'data-hq-page="P-02"', 'data-hq-page="P-03"')
            m = p.manifest()
            m["pages"].append(dict(m["pages"][1], id="P-03", file="pages/orphan.html"))
            p.set_manifest(m)
            rc, out = p.check()
            self.assertEqual(rc, 0, out)
            self.assertTrue(any("P-03: 从入口" in w for w in out["warnings"]), out["warnings"])

    def test_bad_manifest(self):
        with Proto() as p:
            write(os.path.join(p.dir, "manifest.js"), "window.PROTOTYPE = {nope};")
            r = subprocess.run([sys.executable, CHECK, p.dir], capture_output=True, text=True)
            self.assertEqual(r.returncode, 2)

    def test_schema_doc_lists_every_action(self):
        doc = read(os.path.join(ROOT, "skills", "hq-design", "prototype-schema.md"))
        for a in ("goto", "click", "fill", "select", "expect", "see"):
            self.assertIn("| %s |" % a, doc)


FOREIGN_INDEX = """<!doctype html><html><head><meta charset="utf-8"><title>商店</title>
<script src="https://cdn.example.com/lib.js"></script>
<link rel="stylesheet" href="style.css"></head>
<body>
<nav><a href="#list">商品</a> <a href="cart.html">购物车</a> <a href="missing.html">坏链接</a> <a href="mailto:a@b.c">邮件</a></nav>
<main id="view" data-req="REQ-001">首页</main>
<script>
function render() { document.getElementById("view").textContent = location.hash === "#list" ? "商品甲 商品乙" : "首页"; }
addEventListener("hashchange", render); render();
</script></body></html>
"""
FOREIGN_CART = """<!doctype html><html><head><meta charset="utf-8"><title>购物车</title></head>
<body><!-- REQ-002 --><a href="index.html">返回</a>
<button id="add" onclick="var n=document.getElementById('n'); n.textContent=String(Number(n.textContent)+1)">加入</button>
<span id="n">0</span></body></html>
"""
FOREIGN_PRD = """# 商店需求
## REQ-001 首页
## REQ-002 购物车
- REQ-003 优惠券
| NFR-01 | 离线可用 |
### UTF-8 编码
正文里顺带提到 REQ-009 不算定义
"""


class Foreign:
    """A tiny adopted prototype: 2 plain html pages, a hash route, a broken local link, an external script."""

    def __enter__(self):
        self.tmp = tempfile.mkdtemp()
        self.dir = os.path.join(self.tmp, "proto")
        os.mkdir(self.dir)
        write(os.path.join(self.dir, "index.html"), FOREIGN_INDEX)
        write(os.path.join(self.dir, "cart.html"), FOREIGN_CART)
        write(os.path.join(self.dir, "style.css"), "body { margin: 0 }\n")
        self.prd = os.path.join(self.tmp, "prd.md")
        write(self.prd, FOREIGN_PRD)
        return self

    def __exit__(self, *a):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def check(self, *args):
        r = subprocess.run([sys.executable, CHECK, self.dir, "--format", "json", *args], capture_output=True, text=True)
        return r.returncode, json.loads(r.stdout) if r.stdout.strip().startswith("{") else r.stderr


class PrototypeCheckForeignTest(unittest.TestCase):
    def test_errors(self):
        with Foreign() as f:
            rc, out = f.check()
            self.assertEqual(rc, 1, out)
            self.assertEqual(out["mode"], "foreign")
            self.assertEqual(out["files"], ["cart.html", "index.html"])
            e = "\n".join(out["errors"])
            self.assertIn("index.html: 链接或资源不存在：missing.html", e)
            self.assertIn("<script> 引用了外部网络资源 https://cdn.example.com/lib.js", e)
            self.assertEqual(len(out["errors"]), 2, e)  # #list, mailto:, style.css, cart.html are fine
            self.assertEqual(out["warnings"], [])

    def test_allow_external_and_md_header(self):
        with Foreign() as f:
            rc, out = f.check("--allow-external")
            self.assertEqual(rc, 1)
            self.assertTrue(any("外部网络资源" in w for w in out["warnings"]))
            write(os.path.join(f.dir, "index.html"), '<a href="cart.html">购物车</a><img src="data:image/png;base64,AA==">')
            r = subprocess.run([sys.executable, CHECK, f.dir], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stdout)
            self.assertIn("原型检查（外来格式", r.stdout.splitlines()[0])

    def test_prd_coverage_warning(self):
        with Foreign() as f:
            rc, out = f.check("--prd", f.prd)
            self.assertEqual(rc, 1)
            w = "\n".join(out["warnings"])
            self.assertIn("REQ-003 在任何 HTML 文件里都没出现", w)
            self.assertIn("NFR-01 在任何 HTML 文件里都没出现", w)
            for x in ("REQ-001", "REQ-002", "UTF-8", "REQ-009"):  # present / not a requirement / not defined
                self.assertNotIn(x, w)
            self.assertEqual((out["summary"]["prd_ids"], out["summary"]["prd_ids_missing"]), (4, 2))
            rc, out = f.check("--prd", f.prd, "--id-prefixes", "REQ")
            self.assertEqual([w.split()[1] for w in out["warnings"]], ["REQ-003", "REQ-009"])

    def test_forced_on_hq_prototype_and_empty_dir(self):
        with Proto() as p:
            r = subprocess.run([sys.executable, CHECK, p.dir, "--foreign", "--format", "json"], capture_output=True, text=True)
            self.assertEqual(json.loads(r.stdout)["mode"], "foreign")
            rc, out = p.check()
            self.assertEqual(out["mode"], "hq")
        d = tempfile.mkdtemp()
        try:
            r = subprocess.run([sys.executable, CHECK, d], capture_output=True, text=True)
            self.assertEqual(r.returncode, 2)
        finally:
            shutil.rmtree(d)


def have_playwright():
    if not shutil.which("node"):
        return False
    r = subprocess.run(["node", "-e", "require('playwright')"], capture_output=True, cwd=ROOT)
    return r.returncode == 0


@unittest.skipUnless(have_playwright(), "需要 node 和 playwright")
class PrototypeWalkTest(unittest.TestCase):
    def walk(self, d, out):
        r = subprocess.run(["node", WALK, d, "--out", out, "--format", "json", "--scale", "1"], capture_output=True, text=True, timeout=300)
        return r.returncode, json.loads(r.stdout) if r.stdout.strip().startswith("{") else r.stderr

    def test_starter_walks_clean(self):
        with Proto() as p:
            out = os.path.join(p.tmp, "shots")
            rc, res = self.walk(p.dir, out)
            self.assertEqual(rc, 0, res)
            self.assertEqual(len(res["pages"]), 9)
            self.assertTrue(all(r["ok"] for r in res["flows"]))
            self.assertTrue(os.path.isfile(os.path.join(out, "P-02-empty.png")))

    def test_failures_are_reported(self):
        with Proto() as p:
            m = p.manifest()
            m["flows"][0]["steps"][2]["value"] = "wrong-password"  # login fails, never reaches P-02
            p.set_manifest(m)
            p.edit("pages/home.html", "function render() {", "nope.call(); function render() {")
            rc, res = self.walk(p.dir, os.path.join(p.tmp, "shots"))
            self.assertEqual(rc, 1)
            self.assertEqual(res["flows"][0]["failed_step"], 5)
            self.assertTrue(any("pageerror" in e for r in res["pages"] for e in r["errors"]))


FLOWS = """export default async ({ page, baseUrl, step, check, shot }) => {
  await step("打开购物车", () => page.goto(baseUrl + "cart.html"));
  await step("加入一件", () => page.click("#add"));
  await check(async () => (await page.textContent("#n")) === "1", "数量是 1");
  await check(async () => (await page.textContent("#n")) === "5", "数量是 5");
  await shot("cart");
  await step("页面报错", () => page.evaluate(() => setTimeout(() => { throw new Error("boom"); }, 0)));
};
"""


@unittest.skipUnless(have_playwright(), "需要 node 和 playwright")
class PrototypeWalkForeignTest(unittest.TestCase):
    def walk(self, d, *args):
        r = subprocess.run(["node", WALK, d, "--format", "json", "--scale", "1", *args], capture_output=True, text=True, timeout=300)
        return r.returncode, json.loads(r.stdout) if r.stdout.strip().startswith("{") else r.stderr

    def test_views_and_errors(self):
        with Foreign() as f:
            out = os.path.join(f.tmp, "shots")
            rc, res = self.walk(f.dir, "--out", out)
            self.assertEqual(rc, 1, res)  # the external script cannot load offline
            self.assertEqual(res["mode"], "foreign")
            views = {(v["page"], v["view"]): v for v in res["views"]}
            self.assertEqual(set(views), {("cart.html", ""), ("index.html", ""), ("index.html", "#list")})
            self.assertTrue(views[("cart.html", "")]["ok"])
            self.assertTrue(any("cdn.example.com" in e for e in views[("index.html", "")]["errors"]))
            self.assertTrue(os.path.isfile(os.path.join(out, "index--list.png")))
            self.assertEqual(res["steps"], [])
            rc, res = self.walk(f.dir, "--pages", "cart.html")
            self.assertEqual(rc, 0, res)
            self.assertEqual(len(res["views"]), 1)
            rc, res = self.walk(f.dir, "--max-views", "2")
            self.assertTrue(res["truncated"])
            self.assertEqual(len(res["views"]), 2)

    def test_script(self):
        with Foreign() as f:
            sp = os.path.join(f.tmp, "flows.mjs")
            write(sp, FLOWS)
            out = os.path.join(f.tmp, "shots")
            rc, res = self.walk(f.dir, "--pages", "cart.html", "--script", sp, "--out", out)
            self.assertEqual(rc, 1, res)
            self.assertEqual([(a["label"], a["ok"]) for a in res["assertions"]], [("数量是 1", True), ("数量是 5", False)])
            steps = {s["label"]: s for s in res["steps"]}
            self.assertTrue(steps["打开购物车"]["ok"] and steps["加入一件"]["ok"])
            self.assertTrue(any("boom" in e for e in steps["页面报错"]["errors"]))
            self.assertEqual(len(res["failures"]), 2, res["failures"])
            self.assertTrue(os.path.isfile(os.path.join(out, "script-cart.png")))
            write(sp, FLOWS.replace('=== "5"', '=== "1"').replace("throw new Error", "void new Error"))
            rc, res = self.walk(f.dir, "--pages", "cart.html", "--script", sp)
            self.assertEqual(rc, 0, res)
            write(sp, "export const x = 1;\n")
            rc, res = self.walk(f.dir, "--script", sp)
            self.assertEqual(rc, 2, res)


if __name__ == "__main__":
    unittest.main()

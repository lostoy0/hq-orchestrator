import copy
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, "skills", "hq", "scripts", "stage-status.py")
STARTER = os.path.join(ROOT, "skills", "hq-design", "prototype-starter")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_backlog_check as tb  # noqa: E402
import test_doc_check as td  # noqa: E402

DESIGN_DOC = """---
hq_stage: %s
version: 1
based_on: [prd@2]
status: draft
updated: 2026-11-26
---
# x
"""


def write(p, text):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as fh:
        fh.write(text)


class Project:
    """docs/ with every stage artifact, built from the other tests' fixtures; all stages start out ok."""

    def __enter__(self):
        self.tmp = tempfile.mkdtemp()
        d = self.docs = os.path.join(self.tmp, "docs")
        write(os.path.join(d, "research", "competitors.md"), td.RESEARCH)
        write(os.path.join(d, "product", "prd.md"), td.PRD)
        write(os.path.join(d, "design", "design-system.md"), DESIGN_DOC % "design")
        write(os.path.join(d, "design", "screens.md"), DESIGN_DOC % "design-screens")
        proto = os.path.join(d, "design", "prototype")
        shutil.copytree(STARTER, proto)
        mp = os.path.join(proto, "manifest.js")
        t = td.read(mp)
        m = json.loads(t[t.index("{"):t.rindex("}") + 1])
        m["pages"][0]["requirements"] = ["F-001"]
        m["pages"][1]["requirements"] = ["F-002"]
        m["flows"][0]["requirements"] = ["F-001"]
        write(mp, "window.PROTOTYPE = " + json.dumps(m, ensure_ascii=False) + ";\n")
        write(os.path.join(d, "tech", "architecture.md"), td.ARCH)
        write(os.path.join(d, "tech", "detailed-design.md"), td.DETAILED)
        write(os.path.join(d, "tech", "adr", "0001-db.md"), td.ADR)
        write(os.path.join(d, "plan", "roadmap.md"), DESIGN_DOC % "plan")
        bl = copy.deepcopy(tb.BASE)
        bl["based_on"] = {"prd": "docs/product/prd.md@2"}
        bl["requirements"] = [
            {"id": "F-001", "title": "login", "priority": "P0", "release": "R1"},
            {"id": "F-002", "title": "entry", "priority": "P1", "release": "R2"},
        ]
        write(os.path.join(d, "plan", "backlog.json"), json.dumps(bl, ensure_ascii=False))
        return self

    def __exit__(self, *a):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def path(self, rel):
        return os.path.join(self.docs, rel)

    def edit(self, rel, old, new):
        t = td.read(self.path(rel))
        assert old in t, (rel, old)
        write(self.path(rel), t.replace(old, new, 1))

    def status(self):
        r = subprocess.run([sys.executable, SCRIPT, "--docs", self.docs, "--format", "json"], capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
        out = json.loads(r.stdout)
        return {s["stage"]: s for s in out["stages"]}, out["todo"]


class StageStatusTest(unittest.TestCase):
    def test_all_ok(self):
        with Project() as p:
            st, todo = p.status()
            self.assertEqual(todo, [], {k: v for k, v in st.items() if v["state"] != "ok"})
            prd = st["prd"]["artifacts"][0]
            self.assertEqual((prd["version"], prd["errors"]), (2, 0))

    def test_empty_project(self):
        with tempfile.TemporaryDirectory() as d:
            r = subprocess.run([sys.executable, SCRIPT, "--docs", d, "--format", "json"], capture_output=True, text=True)
            out = json.loads(r.stdout)
            self.assertEqual(out["todo"], ["research", "prd", "design", "arch", "plan"])
            self.assertTrue(all(s["state"] == "missing" for s in out["stages"]))

    def test_stale_when_upstream_version_moves(self):
        with Project() as p:
            p.edit("product/prd.md", "version: 2", "version: 3")
            st, todo = p.status()
            self.assertEqual(todo, ["design", "arch", "plan"])
            self.assertEqual({st[s]["state"] for s in todo}, {"stale"})
            self.assertIn("prd@2 → 现在是 prd@3", st["plan"]["artifacts"][1]["stale"][0])

    def test_needs_work_and_partial(self):
        with Project() as p:
            p.edit("product/prd.md", "- 优先级：P1", "- 优先级：高")
            os.remove(p.path("design/screens.md"))
            st, todo = p.status()
            self.assertEqual(st["prd"]["state"], "needs_work")
            self.assertEqual(st["design"]["state"], "partial")

    def test_prd_alt_path(self):
        with Project() as p:
            os.rename(p.path("product/prd.md"), p.path("product/prd-hq.md"))
            st, _ = p.status()
            self.assertEqual(st["prd"]["artifacts"][0]["path"], "product/prd-hq.md")
            self.assertEqual(st["prd"]["state"], "ok")

    def test_broken_artifact_does_not_crash(self):
        with Project() as p:
            write(p.path("plan/backlog.json"), "{not json")
            st, _ = p.status()
            self.assertEqual(st["plan"]["state"], "needs_work")
            self.assertIn("check_failed", st["plan"]["artifacts"][1])

    def test_md_output_and_bad_args(self):
        with Project() as p:
            r = subprocess.run([sys.executable, SCRIPT, "--docs", p.docs], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0)
            self.assertIn("全部阶段已完成", r.stdout)
        r = subprocess.run([sys.executable, SCRIPT, "--docs", "/nonexistent/docs"], capture_output=True, text=True)
        self.assertEqual(r.returncode, 2)


def foreign_repo(tmp):
    """A repository laid out like a project made by another tool (.opc/, REQ ids, a DAG plan)."""
    r = os.path.join(tmp, "repo")
    os.makedirs(os.path.join(r, ".git"))
    write(os.path.join(r, ".opc", "product", "prd.md"), "# 需求文档\n\n| 项 | 值 |\n|---|---|\n| 状态 | 已冻结 |\n\n### REQ-001 〔P0〕登录\n")
    write(os.path.join(r, ".opc", "product", "prototype", "index.html"), "<html></html>")
    write(os.path.join(r, ".opc", "product", "prototype", "web.html"), "<html></html>")
    write(os.path.join(r, ".opc", "tech", "design.md"), "# 技术设计\n\n设计 v1.0 已确认（G2，2026-11-24）\n")
    write(os.path.join(r, ".opc", "tech", "adr", "ADR-001-a.md"), "# a\n")
    write(os.path.join(r, ".opc", "tech", "adr", "ADR-002-b.md"), "# b\n")
    write(os.path.join(r, ".opc", "tech", "contracts", "api.yaml"), "openapi: 3.0.0\n")
    write(os.path.join(r, ".opc", "plan", "v1.dag.yaml"), "tasks: []\n")
    write(os.path.join(r, ".opc", "reviews", "prd-v0.1.md"), "# 评审\n")
    write(os.path.join(r, "node_modules", "x", "prd.md"), "# not ours\n")
    return r


def ss(*args):
    r = subprocess.run([sys.executable, SCRIPT, *args], capture_output=True, text=True)
    return r.returncode, r.stdout, r.stderr


class ForeignArtifactsTest(unittest.TestCase):
    def test_discover(self):
        with tempfile.TemporaryDirectory() as tmp:
            r = foreign_repo(tmp)
            rc, out, _ = ss("--discover", "--root", r)
            self.assertEqual(rc, 0)
            m = json.loads(out)
            self.assertEqual(m["docs_root"], ".opc")
            st = m["stages"]
            self.assertEqual(st["prd"], {"format": "foreign", "paths": [".opc/product/prd.md"], "frozen": True})
            self.assertEqual(st["design"]["paths"], [".opc/product/prototype"])
            self.assertEqual(st["arch"]["paths"], [".opc/tech/adr", ".opc/tech/contracts", ".opc/tech/design.md"])
            self.assertTrue(st["arch"]["frozen"])  # "设计 v1.0 已确认"
            self.assertFalse(st["plan"]["frozen"])
            self.assertEqual(st["plan"]["paths"], [".opc/plan/v1.dag.yaml"])
            self.assertNotIn("research", st)

    def test_lifecycle(self):
        with tempfile.TemporaryDirectory() as tmp:
            r = foreign_repo(tmp)
            docs = os.path.join(r, ".opc")
            _, out, _ = ss("--discover", "--root", r)
            write(os.path.join(docs, "hq-artifacts.json"), out)

            def states():
                rc, o, e = ss("--docs", docs, "--format", "json")
                self.assertEqual(rc, 0, e)
                return {s["stage"]: s for s in json.loads(o)["stages"]}

            st = states()
            self.assertEqual(st["prd"]["state"], "unaudited")
            self.assertTrue(st["prd"]["frozen"])
            self.assertEqual(st["research"]["state"], "missing")  # not mapped -> hq layout under .opc

            rc, o, e = ss("--docs", docs, "--record-audit", "prd", "--report", ".opc/reviews/prd-audit.md", "--blockers", "0")
            self.assertEqual(rc, 0, e)
            self.assertEqual(states()["prd"]["state"], "ok")

            with open(os.path.join(docs, "product", "prd.md"), "a", encoding="utf-8") as fh:
                fh.write("### REQ-002 〔P1〕搜索\n")
            st = states()
            self.assertEqual(st["prd"]["state"], "unaudited")
            self.assertFalse(st["prd"]["audit_current"])

            ss("--docs", docs, "--record-audit", "arch", "--report", "x.md", "--blockers", "2", "--majors", "1")
            self.assertEqual(states()["arch"]["state"], "needs_work")
            # not frozen: majors still need fixing in place; frozen: majors are only proposals
            ss("--docs", docs, "--record-audit", "design", "--report", "x.md", "--blockers", "0", "--majors", "3")
            self.assertEqual(states()["design"]["state"], "needs_work")
            ss("--docs", docs, "--record-audit", "design", "--report", "x.md", "--blockers", "0", "--majors", "0")
            self.assertEqual(states()["design"]["state"], "ok")
            ss("--docs", docs, "--record-audit", "prd", "--report", "x.md", "--blockers", "0", "--majors", "5")
            self.assertEqual(states()["prd"]["state"], "ok")  # frozen

    def test_record_audit_errors(self):
        with tempfile.TemporaryDirectory() as tmp:
            r = foreign_repo(tmp)
            docs = os.path.join(r, ".opc")
            rc, _, e = ss("--docs", docs, "--record-audit", "prd", "--report", "x.md", "--blockers", "0")
            self.assertEqual(rc, 2)
            self.assertIn("不存在", e)
            write(os.path.join(docs, "hq-artifacts.json"), json.dumps({"schema": "hq-artifacts/1", "stages": {"prd": {"format": "hq"}}}))
            rc, _, e = ss("--docs", docs, "--record-audit", "prd", "--report", "x.md", "--blockers", "0")
            self.assertIn("不是 foreign", e)
            write(os.path.join(docs, "hq-artifacts.json"), json.dumps({"schema": "nope"}))
            rc, _, e = ss("--docs", docs)
            self.assertEqual(rc, 2)

    def test_hq_path_override(self):
        with Project() as p:
            os.rename(p.path("product/prd.md"), p.path("product/requirements-v2.md"))
            write(p.path("hq-artifacts.json"), json.dumps({"schema": "hq-artifacts/1", "stages": {
                "prd": {"format": "hq", "paths": {"prd": "product/requirements-v2.md"}}}}))
            st, _ = p.status()
            self.assertEqual(st["prd"]["state"], "ok")
            self.assertEqual(st["prd"]["artifacts"][0]["path"], "product/requirements-v2.md")

    def test_imported_plan_skip_and_source(self):
        with Project() as p:
            os.remove(p.path("plan/roadmap.md"))
            write(os.path.join(p.tmp, ".git", "HEAD"), "x")  # repo root = p.tmp
            write(os.path.join(p.tmp, ".opc", "plan.dag.yaml"), "tasks: [a]\n")
            write(p.path("hq-artifacts.json"), json.dumps({"schema": "hq-artifacts/1", "stages": {
                "plan": {"format": "hq", "skip": ["roadmap"], "source": ".opc/plan.dag.yaml"}}}))
            rc, _, e = ss("--docs", p.docs, "--record-source", "plan")
            self.assertEqual(rc, 0, e)
            st, todo = p.status()
            self.assertEqual(st["plan"]["state"], "ok", st["plan"])
            self.assertEqual([x["key"] for x in st["plan"]["artifacts"]], ["backlog"])
            write(os.path.join(p.tmp, ".opc", "plan.dag.yaml"), "tasks: [a, b]\n")
            st, _ = p.status()
            self.assertEqual(st["plan"]["state"], "stale")
            self.assertIn("转换后改过", st["plan"]["artifacts"][0]["stale"][0])


if __name__ == "__main__":
    unittest.main()

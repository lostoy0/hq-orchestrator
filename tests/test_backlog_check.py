import copy
import json
import os
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, "skills", "hq", "scripts", "backlog-check.py")


def task(tid, release="R1", reqs=("F-001",), deps=(), owns=None, score=(1, 0, 1, 2, 0), tier="T2", **kw):
    t = {"id": tid, "release": release, "title": "task " + tid, "kind": "code",
         "requirements": list(reqs), "depends_on": list(deps), "owns": owns or ["src/%s/**" % tid],
         "acceptance": ["works"], "verify_level": "code", "verify_cmd": "make test",
         "score": dict(zip(("scope", "ambiguity", "context", "risk", "verify"), score)),
         "tier_score": sum(score), "tier": tier, "est_min": 30, "status": "todo"}
    t.update(kw)
    return t


BASE = {
    "schema": "hq-backlog/1", "project": "demo", "updated": "2026-11-26",
    "based_on": {"prd": "docs/product/prd.md@1"},
    "requirements": [
        {"id": "F-001", "title": "login", "priority": "P0", "release": "R1"},
        {"id": "F-002", "title": "export", "priority": "P1", "release": "R2"},
        {"id": "F-003", "title": "themes", "priority": "P2", "release": None},
    ],
    "releases": [
        {"id": "R1", "name": "MVP", "goal": "sign in", "exit_criteria": ["F-001 passes"]},
        {"id": "R2", "name": "v1.1", "goal": "export", "exit_criteria": ["F-002 passes"]},
    ],
    "tasks": [task("B-001"), task("B-002", deps=["B-001"]), task("B-003", release="R2", reqs=["F-002"], deps=["B-001"])],
}


def run(doc, *args):
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "backlog.json")
        with open(p, "w", encoding="utf-8") as fh:
            json.dump(doc, fh)
        extra = []
        for a in args:
            if isinstance(a, tuple):  # (flag, file content)
                q = os.path.join(d, "x.md")
                with open(q, "w", encoding="utf-8") as fh:
                    fh.write(a[1])
                extra += [a[0], q]
            else:
                extra.append(a)
        r = subprocess.run([sys.executable, SCRIPT, p, "--format", "json", *extra], capture_output=True, text=True)
        out = json.loads(r.stdout) if r.stdout.strip().startswith("{") else None
        return r.returncode, out


def mutate(fn):
    d = copy.deepcopy(BASE)
    fn(d)
    return d


class BacklogCheckTest(unittest.TestCase):
    def test_valid(self):
        rc, out = run(BASE)
        self.assertEqual(rc, 0, out)
        self.assertEqual(out["errors"], [])
        self.assertEqual(out["summary"]["tasks"], 3)
        self.assertEqual(out["summary"]["by_release"]["R1"]["tasks"], 2)

    def test_md_output(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "b.json")
            with open(p, "w", encoding="utf-8") as fh:
                json.dump(BASE, fh)
            r = subprocess.run([sys.executable, SCRIPT, p], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0)
        self.assertIn("## 错误（0）", r.stdout)

    def test_unreadable(self):
        r = subprocess.run([sys.executable, SCRIPT, "/nonexistent/backlog.json"], capture_output=True, text=True)
        self.assertEqual(r.returncode, 2)

    def errs(self, doc):
        rc, out = run(doc)
        self.assertEqual(rc, 1, out)
        return "\n".join(out["errors"])

    def test_duplicate_and_missing_dep(self):
        e = self.errs(mutate(lambda d: d["tasks"].append(task("B-001"))))
        self.assertIn("id 重复", e)
        e = self.errs(mutate(lambda d: d["tasks"][1].update(depends_on=["B-099"])))
        self.assertIn("B-099 不存在", e)

    def test_cycle(self):
        e = self.errs(mutate(lambda d: d["tasks"][0].update(depends_on=["B-002"])))
        self.assertIn("依赖有环", e)

    def test_depends_on_later_release(self):
        e = self.errs(mutate(lambda d: d["tasks"][1].update(depends_on=["B-003"])))
        self.assertIn("更晚版本", e)

    def test_tier_score_sum(self):
        e = self.errs(mutate(lambda d: d["tasks"][0].update(tier_score=9, tier="T4")))
        self.assertIn("不等于 5 维之和", e)

    def test_tier_below_band_needs_note(self):
        e = self.errs(mutate(lambda d: d["tasks"][0].update(tier="T1")))
        self.assertIn("必须在 tier_note 写依据", e)
        rc, out = run(mutate(lambda d: d["tasks"][0].update(tier="T1", tier_note="PLAYBOOK 已验证")))
        self.assertEqual(rc, 0)
        self.assertTrue(any("低于分数线" in w for w in out["warnings"]))
        rc, out = run(mutate(lambda d: d["tasks"][0].update(tier="T3")))  # upward is fine
        self.assertEqual((rc, out["warnings"]), (0, []))

    def test_p0_coverage(self):
        e = self.errs(mutate(lambda d: [t.update(requirements=["F-002"]) for t in d["tasks"]]))
        self.assertIn("P0 需求在 R1 及以前没有任务覆盖", e)
        e = self.errs(mutate(lambda d: d["requirements"][0].update(release=None)))
        self.assertIn("P0 需求必须安排版本", e)
        # dropped tasks do not count
        e = self.errs(mutate(lambda d: [t.update(status="dropped") for t in d["tasks"][:2]]))
        self.assertIn("没有任务覆盖", e)

    def test_p1_coverage_is_warning(self):
        rc, out = run(mutate(lambda d: d["tasks"].pop()))
        self.assertEqual(rc, 0)
        self.assertTrue(any("F-002" in w for w in out["warnings"]))

    def test_unknown_requirement_and_bad_enums(self):
        e = self.errs(mutate(lambda d: d["tasks"][0].update(requirements=["F-404"], kind="x", verify_level="y")))
        self.assertIn("F-404", e)
        self.assertIn("kind", e)
        self.assertIn("verify_level", e)

    def test_required_lists(self):
        e = self.errs(mutate(lambda d: d["tasks"][0].update(acceptance=[], owns=[])))
        self.assertIn("acceptance", e)
        self.assertIn("owns", e)

    def test_owns_overlap_warning(self):
        rc, out = run(mutate(lambda d: d["tasks"].append(task("B-004", owns=["src/B-001/**"]))))
        self.assertEqual(rc, 0)
        self.assertTrue(any("B-001/B-004" in w for w in out["warnings"]))
        # overlap along a dependency chain is fine
        rc, out = run(mutate(lambda d: d["tasks"][1].update(owns=["src/B-001/**"])))
        self.assertEqual(out["warnings"], [])

    def test_long_task_warning(self):
        rc, out = run(mutate(lambda d: d["tasks"][0].update(est_min=240)))
        self.assertEqual(rc, 0)
        self.assertTrue(any("建议拆分" in w for w in out["warnings"]))

    def test_prd_ids_missing_from_backlog(self):
        rc, out = run(BASE, ("--prd", "# PRD\nF-001 login\nF-007 search\nNFR-001 fast\n"))
        self.assertEqual(rc, 0)
        self.assertTrue(any("F-007" in w and "NFR-001" in w for w in out["warnings"]))

    def test_garbage(self):
        for doc in ([], {"schema": "nope"}, mutate(lambda d: d.update(tasks=[1, "x", None]))):
            rc, out = run(doc)
            self.assertEqual(rc, 1)


if __name__ == "__main__":
    unittest.main()

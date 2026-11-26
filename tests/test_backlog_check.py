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

    def test_foreign_ids_are_accepted(self):
        def conv(d):
            d["requirements"] = [{"id": "REQ-001", "title": "login", "priority": "P0", "release": "M1"},
                                 {"id": "NFR-01", "title": "fast", "priority": "P0", "release": "M1"}]
            d["releases"] = [{"id": "M1", "name": "首发", "goal": "上线", "exit_criteria": ["REQ-001 通过"]}]
            d["tasks"] = [task("DF-V1-BASE01", release="M1", reqs=["REQ-001", "NFR-01"]),
                          task("DF-V1-AUTH01", release="M1", reqs=["REQ-001"], deps=["DF-V1-BASE01"])]
        rc, out = run(mutate(conv), ("--prd", "### REQ-001 登录\n### REQ-002 搜索\nNFR-01 快\n"))
        self.assertEqual(rc, 0, out)
        self.assertTrue(any("REQ-002" in w for w in out["warnings"]), out["warnings"])

    def test_bad_id_shapes(self):
        e = self.errs(mutate(lambda d: d["tasks"].append(task("b-1"))))
        self.assertIn("大写前缀加编号", e)

    def test_imported_long_tasks_collapse(self):
        def conv(d):
            d["imported_from"] = ".opc/plan/x.dag.yaml"
            for t in d["tasks"]:
                t["est_min"] = 230
        rc, out = run(mutate(conv))
        self.assertEqual(rc, 0, out)
        self.assertEqual(len(out["warnings"]), 1, out["warnings"])
        self.assertIn("3 个任务 est_min 超过 120", out["warnings"][0])

    def test_hold(self):
        e = self.errs(mutate(lambda d: d["tasks"][2].update(status="hold")))
        self.assertIn("必须写 hold_reason", e)
        rc, out = run(mutate(lambda d: d["tasks"][2].update(status="hold", hold_reason="等客户确认导出范围")))
        self.assertEqual(rc, 0, out)
        s = out["summary"]
        self.assertEqual(s["hold"], [{"id": "B-003", "release": "R2", "reason": "等客户确认导出范围"}])
        self.assertEqual((s["by_release"]["R2"]["tasks"], s["by_release"]["R2"]["hold"]), (0, 1))
        self.assertNotIn("B-003", s["critical_path"])
        # P1 covered only by a hold task: not covered
        self.assertTrue(any("F-002" in w and "hold 的任务不算：B-003" in w for w in out["warnings"]), out["warnings"])

    def test_hold_excluded_from_p0_coverage(self):
        e = self.errs(mutate(lambda d: [t.update(status="hold", hold_reason="范围待定") for t in d["tasks"][:2]]))
        self.assertIn("P0 需求在 R1 及以前没有任务覆盖（hold 的任务不算：B-001、B-002）", e)

    def test_depends_on_hold_task(self):
        e = self.errs(mutate(lambda d: d["tasks"][0].update(status="hold", hold_reason="等客户确认")))
        self.assertIn("task B-002: 依赖了 hold 的任务 B-001", e)
        self.assertIn("task B-003: 依赖了 hold 的任务 B-001", e)
        # hold depending on hold is fine, and so is a dropped task
        def ok(d):
            for t in d["tasks"]:
                t.update(status="hold", hold_reason="等客户确认")
            d["tasks"][1]["status"] = "dropped"
            d["tasks"].append(task("B-004"))
        rc, out = run(mutate(ok))
        self.assertEqual(rc, 0, out)

    def test_needs_human(self):
        e = self.errs(mutate(lambda d: d["tasks"][0].update(needs_human=["device"])))
        self.assertIn("必须写 human_step", e)
        e = self.errs(mutate(lambda d: d["tasks"][0].update(needs_human=["robot"], human_step="x")))
        self.assertIn("needs_human 必须是非空数组", e)
        e = self.errs(mutate(lambda d: d["tasks"][0].update(needs_human=[], human_step="x")))
        self.assertIn("needs_human 必须是非空数组", e)
        rc, out = run(mutate(lambda d: d["tasks"][0].update(human_step="x")))
        self.assertTrue(any("没有 needs_human" in w for w in out["warnings"]))
        rc, out = run(mutate(lambda d: d["tasks"][1].update(needs_human=["device", "test_account"], human_step="真机上用测试账号付一笔")))
        self.assertEqual(rc, 0, out)
        nh = out["summary"]["needs_human"]
        self.assertEqual((nh["tasks"], nh["ids"], nh["on_critical_path"]), (1, ["B-002"], ["B-002"]))
        rc, out = run(mutate(lambda d: d["tasks"][2].update(est_min=10, needs_human=["manual_check"], human_step="看一眼")))
        self.assertEqual(out["summary"]["needs_human"]["on_critical_path"], [])

    def test_milestone_shifts_critical_path(self):
        rc, out = run(BASE)
        self.assertEqual((out["summary"]["critical_path_min"], out["summary"]["critical_path"]), (60, ["B-001", "B-002"]))
        ms = [{"id": "M-ACCOUNTS", "name": "商店账号和支付测试账号就绪", "at_min": 200, "owner": "客户"}]
        rc, out = run(mutate(lambda d: (d.update(milestones=ms), d["tasks"][2].update(ready_after="M-ACCOUNTS"))))
        self.assertEqual(rc, 0, out)
        s = out["summary"]
        self.assertEqual((s["critical_path_min"], s["critical_path"]), (230, ["M-ACCOUNTS", "B-003"]))
        self.assertEqual((s["by_release"]["R1"]["finish_min"], s["by_release"]["R2"]["finish_min"]), (60, 230))
        self.assertEqual(s["milestones"], 1)
        # a milestone earlier than the dependencies does not move anything
        ms[0]["at_min"] = 10
        rc, out = run(mutate(lambda d: (d.update(milestones=ms), d["tasks"][2].update(ready_after="M-ACCOUNTS"))))
        self.assertEqual((out["summary"]["critical_path_min"], out["summary"]["critical_path"]), (60, ["B-001", "B-002"]))

    def test_milestone_validation(self):
        e = self.errs(mutate(lambda d: d["tasks"][0].update(ready_after="M-NOPE")))
        self.assertIn("不是顶层 milestones 里的里程碑", e)
        e = self.errs(mutate(lambda d: d.update(milestones=[{"id": "M-X", "name": "x", "at_min": -1}])))
        self.assertIn("at_min", e)
        self.assertIn("owner", e)
        e = self.errs(mutate(lambda d: d.update(milestones="M-X")))
        self.assertIn("milestones: 必须是数组", e)

    def test_md_shows_hold_and_critical_path(self):
        doc = mutate(lambda d: (d.update(milestones=[{"id": "M-DOC", "name": "客户资料", "at_min": 100, "owner": "客户"}]),
                                d["tasks"][1].update(ready_after="M-DOC", needs_human=["customer_doc"], human_step="客户给出价目表"),
                                d["tasks"].append(task("B-009", release="R2", reqs=["F-002"], status="hold", hold_reason="等客户确认"))))
        with tempfile.TemporaryDirectory() as tmp:
            p = os.path.join(tmp, "b.json")
            with open(p, "w", encoding="utf-8") as fh:
                json.dump(doc, fh)
            r = subprocess.run([sys.executable, SCRIPT, p], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertIn("130 分钟：M-DOC -> B-002", r.stdout)
        self.assertIn("在关键路径上的：B-002", r.stdout)
        self.assertIn("- B-009（R2）：等客户确认", r.stdout)

    def test_garbage(self):
        for doc in ([], {"schema": "nope"}, mutate(lambda d: d.update(tasks=[1, "x", None]))):
            rc, out = run(doc)
            self.assertEqual(rc, 1)


if __name__ == "__main__":
    unittest.main()

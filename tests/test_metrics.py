import json
import os
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, "skills", "hq", "scripts", "metrics.py")
FIX = os.path.join(ROOT, "tests", "fixtures")


def run(*args):
    p = subprocess.run([sys.executable, SCRIPT, *args], capture_output=True, text=True)
    return p


def rep(*args):
    p = run(*args, "--format", "json")
    assert p.returncode == 0, p.stderr
    return json.loads(p.stdout)


def grp(groups, key):
    return next(g for g in groups if g["key"] == key)


class MetricsTest(unittest.TestCase):
    def test_overview_and_corrupt(self):
        o = rep(FIX)["overview"]
        self.assertEqual((o["runs"], o["tasks"], o["corrupt_lines"]), (3, 11, 3))
        self.assertEqual(o["time_from"], "2026-01-01T10:00:00Z")
        self.assertEqual(o["time_to"], "2026-01-03T08:00:00Z")

    def test_directory_recursive_equals_files(self):
        files = [os.path.join(FIX, "a.jsonl"), os.path.join(FIX, "b.jsonl"), os.path.join(FIX, "sub", "c.jsonl")]
        self.assertEqual(rep(FIX), rep(*files))
        self.assertEqual(rep(os.path.join(FIX, "sub"))["overview"]["runs"], 1)

    def test_quality(self):
        q = rep(FIX)["quality"]
        self.assertAlmostEqual(q["overall"]["drift_rate"], 3 / 11)
        self.assertAlmostEqual(q["overall"]["verify_rate"], 7 / 11)
        self.assertEqual(q["overall"]["major_issues"], 1)
        self.assertAlmostEqual(q["overall"]["rework_rate"], 2 / 11)
        self.assertAlmostEqual(q["overall"]["integration_pass_rate"], 0.5)
        per = {r["run_id"]: r for r in q["per_run"]}
        self.assertAlmostEqual(per["r1"]["drift_rate"], 0.2)
        self.assertAlmostEqual(per["r2"]["drift_rate"], 2 / 3)

    def test_groups(self):
        r = rep(FIX)
        t2 = grp(r["by_tier"], "T2")
        self.assertEqual(t2["n"], 3)
        self.assertAlmostEqual(t2["first_pass_rate"], 1 / 3)
        self.assertAlmostEqual(t2["escalation_rate"], 1 / 3)
        self.assertAlmostEqual(t2["handoff_rate"], 1 / 3)
        self.assertAlmostEqual(t2["avg_cost_usd"], 0.4)
        self.assertAlmostEqual(t2["ratio_median"], 2.0)
        self.assertFalse(t2["insufficient"])
        self.assertTrue(grp(r["by_tier"], "T3")["insufficient"])
        self.assertEqual(grp(r["by_tier"], "unknown")["n"], 2)
        self.assertEqual(grp(r["by_model"], "sonnet/low")["n"], 5)
        self.assertEqual(sum(g["n"] for g in r["by_host_channel"]), r["overview"]["tasks"])

    def test_efficiency_and_autonomy(self):
        r = rep(FIX)
        e = {x["run_id"]: x for x in r["efficiency"]}
        self.assertAlmostEqual(e["r1"]["speedup"], 2.0)
        self.assertAlmostEqual(e["r1"]["wall_over_critical"], 1.5)
        self.assertAlmostEqual(e["r1"]["speedup_ceiling"], 3.0)
        self.assertEqual(e["r1"]["inconsistent"], [])
        self.assertAlmostEqual(e["r3"]["speedup"], 0.75)
        self.assertIsNone(e["r3"]["wall_over_critical"])
        self.assertIsNone(e["r3"]["speedup_ceiling"])
        # r2: 3 tasks totalling 90 min in a 30 min run with max_concurrency 1, one task 40 min > wall
        self.assertEqual(e["r2"]["inconsistent"], ["speedup>max_concurrency", "task>wall"])
        self.assertEqual(r["autonomy"], {"autonomy_stops": 1, "decisions": 3, "user_corrections": 3})

    def test_signals(self):
        s = [(x["scope"], x["message"], x["n"]) for x in rep(FIX)["signals"]]
        has = lambda scope, frag: any(a == scope and frag in m for a, m, _ in s)
        self.assertTrue(has("tier T1", "降档"))
        self.assertTrue(has("tier T2", "一次通过率 33%"))
        self.assertTrue(has("tier T2", ">1.5"))
        self.assertTrue(has("run r2", "时间数据矛盾"))
        self.assertFalse(has("run r2", "并行加速比"))
        self.assertFalse(has("run r3", "并行加速比"))  # no critical path: room to parallelize unknown
        self.assertFalse(has("run r1", "并行加速比"))
        self.assertFalse(has("run r1", "矛盾"))
        self.assertFalse(has("tier T3", ""))
        self.assertTrue(all(n >= 3 for _, _, n in s))

    def _speedup_signals(self, run_rec, acts):
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "s.jsonl"), "w") as fh:
                for i, a in enumerate(acts):
                    fh.write(json.dumps({"type": "task", "run_id": "s", "task_id": "t%d" % i, "actual_min": a}) + "\n")
                fh.write(json.dumps(dict(run_rec, type="run", run_id="s")) + "\n")
            r = rep(d)
        return r["efficiency"][0], [x["message"] for x in r["signals"] if x["scope"] == "run s"]

    def test_speedup_signal_needs_room_to_parallelize(self):
        # serial chain: critical path == wall, speedup 1 is unavoidable -> no signal
        e, s = self._speedup_signals({"wall_min": 30, "critical_path_min": 30, "max_concurrency": 1}, [10, 10, 10])
        self.assertAlmostEqual(e["speedup_ceiling"], 1.0)
        self.assertEqual(s, [])
        # independent tasks run one after another: ceiling 3, speedup 1 -> signal
        e, s = self._speedup_signals({"wall_min": 30, "critical_path_min": 10, "max_concurrency": 1}, [10, 10, 10])
        self.assertEqual(len(s), 1)
        self.assertIn("上限为 3.00", s[0])
        # speedup slightly above max_concurrency stays within tolerance
        e, _ = self._speedup_signals({"wall_min": 20, "critical_path_min": 10, "max_concurrency": 2}, [15, 14, 14])
        self.assertEqual(e["inconsistent"], [])
        e, s = self._speedup_signals({"wall_min": 20, "critical_path_min": 10, "max_concurrency": 2}, [15, 15, 15])
        self.assertEqual(e["inconsistent"], ["speedup>max_concurrency"])
        self.assertTrue(any("时间数据矛盾" in m for m in s))

    def test_last_and_project(self):
        self.assertEqual(rep(FIX, "--last", "1")["overview"]["runs"], 1)
        self.assertEqual(rep(FIX, "--last", "1")["efficiency"][0]["run_id"], "r3")
        self.assertEqual([e["run_id"] for e in rep(FIX, "--last", "2")["efficiency"]], ["r2", "r3"])
        self.assertEqual(rep(FIX, "--project", "p2")["overview"]["tasks"], 3)
        p1 = rep(FIX, "--project", "p1")["overview"]
        self.assertEqual((p1["runs"], p1["tasks"]), (2, 8))
        self.assertEqual(rep(FIX, "--project", "p1", "--last", "1")["overview"]["runs"], 1)
        self.assertEqual(rep(FIX, "--project", "nope")["overview"]["runs"], 0)

    def test_last_without_started_at_keeps_file_order(self):
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "x.jsonl"), "w") as fh:
                for rid in ("z", "a", "m"):
                    fh.write(json.dumps({"type": "task", "run_id": rid, "task_id": "t"}) + "\n")
            r = rep(d, "--last", "2")
            self.assertEqual([e["run_id"] for e in r["efficiency"]], ["a", "m"])

    def test_adjust_section(self):
        a = rep(FIX)["adjust"]
        self.assertEqual(a, {"escalated": 1, "escalated_after_checkpoint_rate": 0.0, "checkpoints": 0,
                             "handoffs": 1, "derived_tasks": 0, "user_manual_adjust": 0})
        self.assertEqual(rep(FIX)["overview"]["missing_task_records"], 0)

    def test_duplicate_task_records_and_missing(self):
        t = {"type": "task", "run_id": "d", "task_id": "t1", "attempts": 1, "review_outcome": "rework",
             "tier_changes": [{"from": "T1", "to": "T2"}], "checkpoints": 1, "user_manual_adjust": True}
        with tempfile.TemporaryDirectory() as d:
            for sub in ("proj", "home"):
                os.makedirs(os.path.join(d, sub))
                with open(os.path.join(d, sub, "d.jsonl"), "w") as fh:
                    fh.write(json.dumps(t) + "\n")
                    fh.write(json.dumps(dict(t, review_outcome="pass")) + "\n")
                    fh.write(json.dumps({"type": "task", "run_id": "d"}) + "\n")
                    fh.write(json.dumps({"type": "run", "run_id": "d", "tasks": 4}) + "\n")
            r = rep(d)
            self.assertEqual(r["overview"]["tasks"], 3)  # t1 once (last wins) + 2 records without task_id
            self.assertEqual(r["quality"]["overall"]["rework_rate"], 0)
            self.assertEqual(r["overview"]["missing_task_records"], 1)
            a = r["adjust"]
            self.assertEqual((a["escalated"], a["escalated_after_checkpoint_rate"], a["user_manual_adjust"]), (1, 1.0, 1))
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "n.jsonl"), "w") as fh:
                fh.write('{"type":"task","run_id":"n","task_id":"x","checkpoints":null,"derived_tasks":"a","tier_changes":[1]}\n')
                fh.write('{"type":"run","run_id":"n","tasks":null}\n')
            r = rep(d)
            self.assertIsNone(r["overview"]["missing_task_records"])
            self.assertEqual(r["adjust"]["escalated_after_checkpoint_rate"], 0.0)

    def test_md_output(self):
        p = run(FIX)
        self.assertEqual(p.returncode, 0, p.stderr)
        for h in ("## 1. 总览", "## 2. 质量门槛", "## 3a. 按档位", "## 4. 效率", "## 6b. 调档与检查点", "## 7. 信号", "样本不足",
                  "加速比上限", "数据矛盾：speedup>max_concurrency, task>wall"):
            self.assertIn(h, p.stdout)

    def test_garbage_does_not_crash(self):
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "g.jsonl"), "wb") as fh:
                fh.write(b'\xff\xfe\n{"type":"task","issues":"x","tier_changes":5,"est_min":"a","tokens":true}\n"str"\nnull\n')
            r = rep(d)
            self.assertEqual(r["overview"]["corrupt_lines"], 3)
            self.assertEqual(r["overview"]["tasks"], 1)

    def test_export_anon_keeps_metrics(self):
        plain, anon = rep(FIX), json.loads(run(FIX, "--export-anon").stdout)
        self.assertEqual(anon["format"], "hq-anon/v1")
        s = anon["summary"]
        self.assertEqual(s["overview"]["runs"], plain["overview"]["runs"])
        self.assertEqual(s["overview"]["tasks"], plain["overview"]["tasks"])
        self.assertEqual(s["overview"]["time_from"], "2026-01-01")
        strip = lambda q: {k: v for k, v in q.items() if k != "run_id"}
        self.assertEqual(s["quality"]["overall"], plain["quality"]["overall"])
        self.assertEqual(s["by_tier"], plain["by_tier"])
        self.assertEqual(s["by_model"], plain["by_model"])
        self.assertEqual([strip(e) for e in s["efficiency"]], [strip(e) for e in plain["efficiency"]])
        self.assertNotIn("records", anon)
        self.assertTrue(all(e["run_id"].startswith("r-") for e in s["efficiency"]))
        self.assertEqual(json.loads(run(FIX, "--export-anon").stdout), anon)  # stable hashes

    def test_export_anon_drops_free_text(self):
        secret = "SECRET-acme-login"
        t = {"type": "task", "run_id": "20260105-" + secret, "task_id": secret, "title": secret, "project": secret,
             "notes": secret, "drift_note": secret, "verify_evidence": secret + " 12 passed", "verify_pass": True,
             "kind": secret, "tier": "T2", "model": "codex:" + secret + " with spaces", "effort": "high",
             "host": "claude-code", "tier_changes": [{"from": "T1", "to": "T2", "reason": secret}],
             "issues": {"review": 1, "user": secret, "severity_max": secret}, "future": secret, "cost_usd": 0.5}
        r = {"type": "run", "run_id": t["run_id"], "project": secret, "goal": secret, "plugin_version": secret,
             "started_at": "2026-01-05T10:11:12Z", "tasks": 1, "integration_pass": "yes"}
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "s.jsonl"), "w") as fh:
                fh.write(json.dumps(t) + "\n" + json.dumps(r) + "\n")
            p = run(d, "--export-anon", "--raw")
            self.assertEqual(p.returncode, 0, p.stderr)
            self.assertNotIn("SECRET", p.stdout)
            self.assertNotIn("acme", p.stdout)
            recs = json.loads(p.stdout)["records"]
            run_rec = next(x for x in recs if x["type"] == "run")
            task = next(x for x in recs if x["type"] == "task")
            self.assertEqual(run_rec["started_at"], "2026-01-05")
            self.assertEqual(run_rec["plugin_version"], "other")
            self.assertIsNone(run_rec["integration_pass"])
            self.assertEqual((task["kind"], task["model"], task["tier"], task["task_id"]), ("other", "other", "T2", "t1"))
            self.assertEqual(task["verify_evidence"], "[redacted]")
            self.assertEqual(task["tier_changes"], [{"from": "T1", "to": "T2"}])
            self.assertEqual(task["issues"], {"review": 1, "integration": None, "user": None, "severity_max": None})
            self.assertEqual(json.loads(p.stdout)["summary"]["quality"]["overall"]["verify_rate"], 1.0)
            for k in ("title", "project", "notes", "drift_note", "future", "goal"):
                self.assertNotIn(k, task)
                self.assertNotIn(k, run_rec)

    def test_raw_requires_export(self):
        self.assertNotEqual(run(FIX, "--raw").returncode, 0)

    def test_missing_path_errors(self):
        self.assertNotEqual(run("/no/such/path").returncode, 0)


if __name__ == "__main__":
    unittest.main()

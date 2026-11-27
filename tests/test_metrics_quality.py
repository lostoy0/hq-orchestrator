"""Signal confidence (Wilson), field coverage, score / independent review / review wait."""
import json
import os
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, "skills", "hq", "scripts", "metrics.py")
FIX = os.path.join(ROOT, "tests", "fixtures")
sys.path.insert(0, os.path.join(ROOT, "skills", "hq", "scripts"))
import metrics  # noqa: E402


def run(*args):
    return subprocess.run([sys.executable, SCRIPT, *args], capture_output=True, text=True)


def task(i, **kw):
    t = {"type": "task", "run_id": "r", "task_id": "t%d" % i}
    t.update(kw)
    return t


def passing(i, **kw):
    return task(i, tier="T2", attempts=1, review_outcome="pass", **kw)


def failing(i, **kw):
    return task(i, tier="T2", attempts=2, review_outcome="rework", **kw)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def write(self, name, rows, text=None):
        p = os.path.join(self.tmp.name, name)
        with open(p, "w", encoding="utf-8") as fh:
            fh.write(text if text is not None else "\n".join(json.dumps(x, ensure_ascii=False) for x in rows) + "\n")
        return p

    def rep(self, tasks, run_rec=None, *extra):
        rows = list(tasks) + ([dict(run_rec, type="run", run_id="r")] if run_rec else [])
        p = run(self.write("r.jsonl", rows), "--format", "json", *extra)
        self.assertEqual(p.returncode, 0, p.stderr)
        return json.loads(p.stdout)

    def md(self, tasks, run_rec=None):
        rows = list(tasks) + ([dict(run_rec, type="run", run_id="r")] if run_rec else [])
        p = run(self.write("r.jsonl", rows))
        self.assertEqual(p.returncode, 0, p.stderr)
        return p.stdout

    @staticmethod
    def sig(rep, scope, text):
        return [s for s in rep["signals"] if s["scope"] == scope and text in s["message"]]


class WilsonTest(unittest.TestCase):
    def test_values(self):
        lo, hi = metrics.wilson(1, 3)
        self.assertAlmostEqual(lo, 0.0615, places=3)
        self.assertAlmostEqual(hi, 0.7923, places=3)
        lo, hi = metrics.wilson(30, 90)
        self.assertAlmostEqual(lo, 0.2445, places=3)
        self.assertAlmostEqual(hi, 0.4358, places=3)

    def test_edges(self):
        self.assertIsNone(metrics.wilson(0, 0))
        lo, hi = metrics.wilson(0, 5)
        self.assertEqual(lo, 0.0)
        self.assertAlmostEqual(hi, 0.4345, places=3)
        self.assertEqual(metrics.wilson(5, 5)[1], 1.0)

    def test_judge_sides(self):
        self.assertEqual(metrics.judge(1, 3, 0.6, "below")[0], "weak")
        self.assertEqual(metrics.judge(2, 20, 0.6, "below")[0], "strong")
        self.assertEqual(metrics.judge(3, 10, 0.3, "above")[0], "weak")
        self.assertEqual(metrics.judge(60, 100, 0.3, "above")[0], "strong")
        self.assertEqual(metrics.judge(0, 0, 0.3, "above"), (None, None))


class ConfidenceTest(Base):
    def test_low_first_pass_weak_and_strong(self):
        weak = self.rep([passing(1), failing(2), failing(3)])
        s = self.sig(weak, "tier T2", "一次通过率 33%")
        self.assertEqual(len(s), 1)  # signal kept even though noisy
        self.assertEqual(s[0]["confidence"], "weak")
        lo, hi = s[0]["ci"]
        self.assertAlmostEqual(lo, 0.0615, places=3)
        self.assertAlmostEqual(hi, 0.7923, places=3)
        self.assertEqual(s[0]["threshold"], 0.6)
        strong = self.rep([passing(1), passing(2)] + [failing(i) for i in range(3, 13)])
        s = self.sig(strong, "tier T2", "一次通过率 17%")
        self.assertEqual(s[0]["confidence"], "strong")
        self.assertLess(s[0]["ci"][1], 0.6)

    def test_md_weak_marker_only_on_weak(self):
        md = self.md([passing(1), failing(2), failing(3)])
        line = next(l for l in md.splitlines() if "一次通过率 33%" in l and "[tier T2]" in l)
        self.assertTrue(line.endswith("（弱：95% 区间 6%–79% 跨过阈值）"), line)
        md = self.md([passing(1), passing(2)] + [failing(i) for i in range(3, 13)])
        line = next(l for l in md.splitlines() if "[tier T2]" in l and "一次通过率" in l)
        self.assertNotIn("弱", line)

    def test_full_pass_signal(self):
        def ts(n):
            # v0.3.3 规则只看 risk=low、按 run 中位数归一化：加 n+1 个偏慢的对照任务，使 run 中位数为 1.0，
            # T2 归一化后仍是 0.4
            return ([passing(i, est_min=10, actual_min=4, risk="low") for i in range(n)]
                    + [task(1000 + i, tier="T3", risk="med", attempts=1, review_outcome="pass", est_min=10, actual_min=10)
                       for i in range(n + 1)])
        w = self.sig(self.rep(ts(5)), "tier T2", "降档空间")
        self.assertEqual(w[0]["confidence"], "weak")
        s = self.sig(self.rep(ts(30)), "tier T2", "降档空间")
        self.assertEqual(s[0]["confidence"], "strong")

    def test_plan_signal(self):
        def ts(under, same):
            return ([passing(i, plan_tier="T1") for i in range(under)]
                    + [passing(100 + i, plan_tier="T2") for i in range(same)])
        w = self.sig(self.rep(ts(2, 4)), "plan", "打分偏低")  # 33% of 6
        self.assertEqual(w[0]["confidence"], "weak")
        s = self.sig(self.rep(ts(20, 0)), "plan", "打分偏低")
        self.assertEqual(s[0]["confidence"], "strong")

    def test_other_proportion_signals(self):
        out = []
        add = metrics.make_add(out)
        rec = {"offered": 20, "accepted": 1, "acceptance_rate": 0.05}
        metrics.extra_signals(add, [], [], rec)
        self.assertEqual(out[0]["confidence"], "strong")
        out.clear()
        metrics.extra_signals(add, [], [], {"offered": 5, "accepted": 1, "acceptance_rate": 0.2})
        self.assertEqual(out[0]["confidence"], "weak")
        out.clear()
        flags = [{"key": "bias:+1(tier)", "n": 5, "first_pass_rate": 1, "first_pass_k": 5, "rework_rate": 0}]
        metrics.extra_signals(add, flags, [], {"offered": 0, "accepted": 0, "acceptance_rate": None})
        self.assertEqual(out[0]["confidence"], "weak")
        out.clear()
        flags = [{"key": "downgrade:user_allowed(-1)", "n": 12, "first_pass_rate": 0.1, "first_pass_k": 1}]
        metrics.extra_signals(add, flags, [], {"offered": 0, "accepted": 0, "acceptance_rate": None})
        self.assertEqual(out[0]["confidence"], "strong")

    def test_tier_and_model_tables_have_interval_column(self):
        md = self.md([passing(1), failing(2), failing(3)])
        self.assertEqual(md.count("一次通过率 95% 区间"), 2)
        self.assertIn("6%–79%", md)
        j = self.rep([passing(1), failing(2), failing(3)])
        self.assertEqual(len(j["by_tier"][0]["first_pass_ci"]), 2)


class SparseDepsTest(Base):
    def test_rule11_flag_sparse(self):
        ts = ([task(i, tier="T2", flags=["downgrade:user_allowed(-1)"], attempts=2, review_outcome="rework") for i in range(2)]
              + [task(10 + i, tier="T2", flags=["downgrade:user_allowed(-1)"]) for i in range(4)])
        s = self.sig(self.rep(ts), "flag downgrade:user_allowed(-1)", "规则 11")[0]
        self.assertEqual((s["data"], s["data_field"]), ("sparse", "attempts+review_outcome"))
        full = [passing(i, flags=["downgrade:user_allowed(-1)"]) for i in range(1)] + \
               [failing(10 + i, flags=["downgrade:user_allowed(-1)"]) for i in range(3)]
        self.assertNotIn("data", self.sig(self.rep(full), "flag downgrade:user_allowed(-1)", "规则 11")[0])

    def test_rule9_flag_dependency(self):
        out = []
        g = {"key": "bias:+1(tier)", "n": 5, "first_pass_rate": 1, "first_pass_k": 5, "rework_rate": 0, "cov_first_pass": 0.2}
        metrics.extra_signals(metrics.make_add(out), [g], [], {"offered": 0, "accepted": 0, "acceptance_rate": None})
        self.assertEqual(out[0]["data"], "sparse")
        out.clear()
        metrics.extra_signals(metrics.make_add(out), [dict(g, cov_first_pass=1.0)], [], {"offered": 0, "accepted": 0, "acceptance_rate": None})
        self.assertNotIn("data", out[0])

    def test_plan_signal_sparse_on_tier(self):
        ts = [passing(i, plan_tier="T1") for i in range(5)] + [task(10 + i, plan_tier="T1") for i in range(6)]
        s = self.sig(self.rep(ts), "plan", "打分偏低")[0]
        self.assertEqual((s["data"], s["data_field"]), ("sparse", "tier"))
        ok = [passing(i, plan_tier="T1") for i in range(6)]
        self.assertNotIn("data", self.sig(self.rep(ok), "plan", "打分偏低")[0])

    def test_verify_level_escape_sparse_on_issues(self):
        ts = ([task(i, verify_level="code", issues={"integration": 1}) for i in range(2)]
              + [task(10 + i, verify_level="code") for i in range(3)])
        s = self.sig(self.rep(ts), "verify code", "漏到合并或用户环节")[0]
        self.assertEqual((s["data"], s["data_field"]), ("sparse", "issues"))
        ok = [task(i, verify_level="code", issues={"integration": 1 if i < 2 else 0}) for i in range(5)]
        self.assertNotIn("data", self.sig(self.rep(ok), "verify code", "漏到合并或用户环节")[0])

    def test_other_boundaries_not_fooled(self):
        # exactly 10% found, exactly 15 min median and exactly 50% coverage are not signals / not sparse
        self.assertFalse(metrics.coverage([task(1, est_min=1), task(2)])["fields"]["est_min"]["sparse"])


class CoverageTest(Base):
    def test_coverage_counts(self):
        ts = [task(1, est_min=5, actual_min=5, cost_usd=0.1, tier="T1", attempts=1, review_outcome="pass",
                   verify_level="code", verify_pass=True, issues={"review": 0}),
              task(2, est_min=5, cost_usd=None, tier="bogus", verify_pass="yes", review_outcome="weird"),
              task(3), task(4)]
        c = self.rep(ts)["coverage"]
        self.assertEqual(c["tasks"], 4)
        f = c["fields"]
        self.assertEqual((f["est_min"]["n"], f["est_min"]["rate"]), (2, 0.5))
        self.assertEqual(f["actual_min"]["n"], 1)
        self.assertEqual(f["cost_usd"]["n"], 1)
        self.assertTrue(f["cost_usd"]["sparse"])
        self.assertFalse(f["est_min"]["sparse"])  # exactly 50% is not sparse
        for k in ("tier", "review_outcome", "verify_pass", "verify_level", "issues", "attempts"):
            self.assertEqual(f[k]["n"], 1, k)
        self.assertEqual(c["joint"]["est_min+actual_min"], 0.25)

    def test_empty(self):
        c = metrics.coverage([])
        self.assertEqual(c["tasks"], 0)
        self.assertIsNone(c["fields"]["est_min"]["rate"])
        self.assertFalse(c["fields"]["est_min"]["sparse"])

    def test_md_has_section_1b(self):
        md = self.md([task(1, est_min=3)])
        self.assertIn("## 1b. 字段覆盖率", md)
        self.assertIn("| est_min | 1 | 100.0% |", md)

    def test_sparse_first_pass_signal(self):
        # 8 of 10 tasks lack attempts/review_outcome, so the "low pass rate" comes from missing data
        ts = [failing(i) for i in range(2)] + [task(10 + i, tier="T2") for i in range(8)]
        r = self.rep(ts)
        s = self.sig(r, "tier T2", "一次通过率")[0]
        self.assertEqual(s["data"], "sparse")
        self.assertEqual(s["data_field"], "attempts+review_outcome")
        self.assertAlmostEqual(s["data_coverage"], 0.2)
        md = self.md(ts)
        self.assertIn("（数据不足：attempts+review_outcome 覆盖 20%）", md)

    def test_full_data_not_sparse(self):
        r = self.rep([passing(1), failing(2), failing(3)])
        self.assertNotIn("data", self.sig(r, "tier T2", "一次通过率")[0])

    def test_sparse_time_ratio_signal(self):
        ts = [passing(i, est_min=10, actual_min=30) for i in range(3)] + [passing(10 + i) for i in range(7)]
        r = self.rep(ts)
        s = self.sig(r, "tier T2", "估时偏乐观")[0]
        self.assertEqual(s["data"], "sparse")
        self.assertEqual(s["data_field"], "est_min+actual_min")
        o = self.sig(r, "overall", "估时偏乐观")[0]
        self.assertEqual(o["data"], "sparse")
        full = self.rep([passing(i, est_min=10, actual_min=30) for i in range(3)])
        self.assertNotIn("data", self.sig(full, "tier T2", "估时偏乐观")[0])

    def test_fixture_report_still_has_coverage(self):
        p = run(FIX, "--format", "json")
        self.assertEqual(json.loads(p.stdout)["coverage"]["tasks"], 11)


CHANGELOG = """# 更新记录

## 格式说明

- **状态**：`待验证` / `已验证` / `已撤回`。

## 未发布

### 条目甲
- **状态**：待验证（自测通过）
- **验收判定**：`by_tier[key=T2].first_pass_rate >= 0.8`

### 条目乙
- **状态**：已验证

## v1.2.0（2026-01-02）

### 条目丙
- **状态**：已验证（复盘 x）
- **验收判定**：`quality.overall.rework_rate <= 0.1`

### 条目丁
- **状态**：已撤回
- **验收判定**：`quality.overall.rework_rate <= 0.1`

### 条目戊
- **状态**：已验证

### 条目己
- **状态**：暂缓

## v1.1.0

### 条目庚
- **改动**：没有状态行
"""


class ChangelogCheckSmokeTest(Base):
    """--changelog-stats was removed; what is left here only checks --check-changelog on the same inputs."""
    def test_unparseable_version_heading(self):
        text = ("## 格式说明\n\n- 说明\n\n## 未发布\n\n### a\n- **状态**：待验证\n\n"
                "## v0.1.x（复盘后的小改进）\n\n### b\n- **状态**：已验证\n\n### c\n- **状态**：待验证\n"
                "- **验收判定**：`quality.overall.rework_rate <= 0.5`\n\n## 杂项说明\n\n### d\n- **状态**：已撤回\n")
        p = self.write("CHANGELOG.md", None, text=text)
        r = run(FIX, "--check-changelog", p)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("c", r.stdout)

    def test_missing_paths_and_check_changelog(self):
        self.assertNotEqual(run().returncode, 0)  # paths are required
        self.assertNotEqual(run("--changelog-stats", "x").returncode, 0)  # option removed
        p = self.write("CHANGELOG.md", None, text=CHANGELOG)
        r = run(FIX, "--check-changelog", p)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(r.stdout.startswith("# CHANGELOG 验收判定"))


class ScoreTest(Base):
    def tasks(self, v0, v2):
        """v0 / v2: (n, escalated) for ambiguity=0 and ambiguity=2."""
        out, i = [], 0
        for val, (n, e) in ((0, v0), (2, v2)):
            for j in range(n):
                i += 1
                kw = {"tier_changes": [{"from": "T1", "to": "T2"}]} if j < e else {"tier_changes": []}
                out.append(passing(i, score={"scope": 1, "ambiguity": val, "context": 1, "risk": 0, "verify": 1}, **kw))
        return out

    def test_signal_fires(self):
        r = self.rep(self.tasks((6, 0), (5, 3)))
        s = self.sig(r, "score ambiguity=2", "升档率偏高")
        self.assertEqual(len(s), 1)
        self.assertIn("打分可能低估了这一维", s[0]["message"])
        self.assertEqual(s[0]["n"], 5)
        self.assertIn(s[0]["confidence"], ("weak", "strong"))
        self.assertEqual(self.sig(r, "score ambiguity=0", "升档率偏高"), [])

    def test_signal_not_fired(self):
        # n < 5
        self.assertEqual(self.sig(self.rep(self.tasks((6, 0), (4, 4))), "score ambiguity=2", "升档率偏高"), [])
        # gap below 30 points: 2/5 = 40% vs 1/6 = 16.7%
        self.assertEqual(self.sig(self.rep(self.tasks((6, 1), (5, 2))), "score ambiguity=2", "升档率偏高"), [])

    def test_float_boundary_7_of_10_vs_4_of_10_fires(self):
        r = self.rep(self.tasks((10, 4), (10, 7)))  # 0.7 - 0.4 == 0.29999999999999993
        s = self.sig(r, "score ambiguity=2", "升档率偏高")
        self.assertEqual(len(s), 1)
        self.assertIn(s[0]["confidence"], ("weak", "strong"))
        # just under the gap still does not fire: 6/10 vs 4/10
        self.assertEqual(self.sig(self.rep(self.tasks((10, 4), (10, 6))), "score ambiguity=2", "升档率偏高"), [])

    def test_gap_exactly_30_points_fires(self):
        r = self.rep(self.tasks((10, 1), (10, 4)))  # 40% vs 10%
        self.assertEqual(len(self.sig(r, "score ambiguity=2", "升档率偏高")), 1)

    def test_section_3i_and_values(self):
        r = self.rep(self.tasks((6, 0), (5, 3)))
        rows = {x["value"]: x for x in r["by_score"]["ambiguity"]}
        self.assertEqual((rows[0]["n"], rows[2]["n"]), (6, 5))
        self.assertAlmostEqual(rows[2]["escalation_rate"], 0.6)
        self.assertEqual(rows[2]["first_pass_rate"], 1.0)
        self.assertEqual(sorted(r["by_score"]), ["ambiguity", "context", "risk", "scope", "verify"])
        md = self.md(self.tasks((6, 0), (5, 3)))
        self.assertIn("## 3i. 按打分维度", md)
        self.assertIn("| ambiguity | 2 | 5 | 100.0% |", md)

    def test_invalid_values_ignored(self):
        ts = [passing(i, score={"scope": 3, "ambiguity": "high", "context": None, "risk": 1.5, "verify": True}) for i in range(6)]
        r = self.rep(ts)
        self.assertEqual(r["by_score"], {})
        self.assertEqual(r["coverage"]["fields"]["score"]["n"], 0)

    def test_old_data_has_no_new_sections(self):
        r = self.rep([passing(i) for i in range(4)], {"wall_min": 10})
        self.assertEqual(r["by_score"], {})
        self.assertEqual(r["independent_review"], {})
        md = self.md([passing(i) for i in range(4)])
        for h in ("3i.", "6d.", "审核等待"):
            self.assertNotIn(h, md)
        p = run(FIX)
        self.assertEqual(p.returncode, 0)
        for h in ("3i.", "6d.", "审核等待"):
            self.assertNotIn(h, p.stdout)

    def test_partial_score_and_sparse(self):
        ts = self.tasks((6, 0), (5, 3)) + [passing(100 + i) for i in range(30)]
        s = self.sig(self.rep(ts), "score ambiguity=2", "升档率偏高")[0]
        self.assertEqual(s["data"], "sparse")
        self.assertEqual(s["data_field"], "score")


def ir(trigger, found=0, major=0, ran=True):
    return {"ran": ran, "trigger": trigger, "findings": found, "major": major}


class IndependentReviewTest(Base):
    def test_signal_fires_and_not(self):
        ts = ([passing(i, independent_review=ir("lines")) for i in range(5)]
              + [passing(10 + i, independent_review=ir("high", found=2 if i < 3 else 0, major=1 if i == 0 else 0)) for i in range(5)])
        r = self.rep(ts)
        s = self.sig(r, "review lines", "几乎发现不了问题")
        self.assertEqual(len(s), 1)
        self.assertIn("可考虑放宽", s[0]["message"])
        self.assertEqual(s[0]["confidence"], "weak")  # 0 of 5: upper bound ~43%
        self.assertEqual(self.sig(r, "review high", "几乎发现不了问题"), [])
        rows = {x["trigger"]: x for x in r["independent_review"]["by_trigger"]}
        self.assertEqual((rows["lines"]["n"], rows["lines"]["found"], rows["lines"]["findings"]), (5, 0, 0))
        self.assertEqual((rows["high"]["n"], rows["high"]["found"], rows["high"]["findings"], rows["high"]["major"]), (5, 3, 6, 1))
        self.assertAlmostEqual(rows["high"]["found_rate"], 0.6)

    def test_strong_with_many_runs(self):
        r = self.rep([passing(i, independent_review=ir("tier")) for i in range(40)])
        self.assertEqual(self.sig(r, "review tier", "几乎发现不了问题")[0]["confidence"], "strong")

    def test_small_n_and_ten_percent_boundary(self):
        r = self.rep([passing(i, independent_review=ir("tier")) for i in range(4)])
        self.assertEqual(self.sig(r, "review tier", "几乎发现不了问题"), [])
        ts = [passing(i, independent_review=ir("tier", found=1 if i == 0 else 0)) for i in range(10)]  # exactly 10%
        self.assertEqual(self.sig(self.rep(ts), "review tier", "几乎发现不了问题"), [])

    def test_ran_false_and_unknown_trigger(self):
        ts = [passing(i, independent_review=ir("high", ran=False)) for i in range(3)] + \
             [passing(10 + i, independent_review=ir("weird", found=1)) for i in range(2)]
        d = self.rep(ts)["independent_review"]
        self.assertEqual((d["ran"], d["not_run"]), (2, 3))
        self.assertEqual([x["trigger"] for x in d["by_trigger"]], ["other"])

    def test_md_section(self):
        md = self.md([passing(i, independent_review=ir("assist_lines", found=1, major=1)) for i in range(3)])
        self.assertIn("## 6d. 独立审核", md)
        self.assertIn("| assist_lines | 3 | 3 | 100.0% |", md)


class ReviewWaitTest(Base):
    def waits(self, ws):
        return [passing(i, review_wait_min=w) for i, w in enumerate(ws)]

    def test_signal_fires(self):
        r = self.rep(self.waits([20, 30, 40]))
        s = self.sig(r, "run r", "巡检间隔偏长")
        self.assertEqual(len(s), 1)
        self.assertIn("交付后平均 30 分钟才审核", s[0]["message"])
        e = r["efficiency"][0]
        self.assertEqual((e["wait_median"], e["wait_max"], e["wait_n"]), (30, 40, 3))
        md = self.md(self.waits([20, 30, 40]))
        self.assertIn("审核等待中位数(分)", md)

    def test_not_fired(self):
        self.assertEqual(self.sig(self.rep(self.waits([16, 40])), "run r", "巡检间隔偏长"), [])  # n < 3
        self.assertEqual(self.sig(self.rep(self.waits([5, 15, 15])), "run r", "巡检间隔偏长"), [])  # median 15 is not > 15
        e = self.rep(self.waits([5, 15, 15]))["efficiency"][0]
        self.assertEqual(e["wait_median"], 15)

    def test_invalid_waits_ignored(self):
        ts = [passing(0, review_wait_min=-3), passing(1, review_wait_min="soon"), passing(2, review_wait_min=None), passing(3, review_wait_min=10)]
        e = self.rep(ts)["efficiency"][0]
        self.assertEqual((e["wait_n"], e["wait_max"]), (1, 10))

    def test_per_run(self):
        rows = [dict(t, run_id="a") for t in self.waits([30, 30, 30])] + [dict(t, run_id="b") for t in self.waits([1, 2, 3])]
        p = run(self.write("x.jsonl", rows), "--format", "json")
        sigs = [s for s in json.loads(p.stdout)["signals"] if "巡检间隔偏长" in s["message"]]
        self.assertEqual([s["scope"] for s in sigs], ["run a"])


class AnonTest(Base):
    def test_whitelist(self):
        secret = "SECRET-free-text"
        t = passing(1, title=secret, notes=secret, review_wait_min=12.5,
                    score={"scope": 2, "ambiguity": 1, "context": 0, "risk": secret, "verify": 7, "extra": secret},
                    independent_review={"ran": True, "trigger": secret, "findings": 3, "major": secret, "note": secret})
        t2 = passing(2, independent_review={"ran": "yes", "trigger": "lines", "findings": secret, "major": 1},
                     score={"scope": 1.0})
        p = run(self.write("r.jsonl", [t, t2]), "--export-anon", "--raw")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertNotIn(secret, p.stdout)
        recs = {x["task_id"]: x for x in json.loads(p.stdout)["records"] if x["type"] == "task"}
        self.assertEqual(recs["t1"]["score"], {"scope": 2, "ambiguity": 1, "context": 0, "risk": None, "verify": None})
        self.assertEqual(recs["t1"]["independent_review"],
                         {"ran": True, "trigger": "other", "findings": 3, "major": None})
        self.assertEqual(recs["t1"]["review_wait_min"], 12.5)
        self.assertEqual(recs["t2"]["independent_review"], {"ran": None, "trigger": "lines", "findings": None, "major": 1})
        self.assertEqual(recs["t2"]["score"]["scope"], 1)

    def test_summary_uses_anon_fields(self):
        ts = [passing(i, independent_review=ir("lines"), review_wait_min=20,
                      score={"scope": 0, "ambiguity": 0, "context": 0, "risk": 0, "verify": 0}) for i in range(5)]
        s = json.loads(run(self.write("r.jsonl", ts), "--export-anon").stdout)["summary"]
        self.assertEqual(s["independent_review"]["ran"], 5)
        self.assertIn("scope", s["by_score"])
        self.assertEqual(s["coverage"]["fields"]["review_wait_min"]["n"], 5)


if __name__ == "__main__":
    unittest.main()

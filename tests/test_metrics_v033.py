"""v0.3.3 fixes re-implemented on current metrics.py: found_issues attribution, verify_pass "partial",
plugin_version_at_start, value counts in group tables, run-normalized low-risk ratios (data only), followups."""
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


def task(rid, tid, **kw):
    t = {"type": "task", "run_id": rid, "task_id": tid}
    t.update(kw)
    return t


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def write(self, name, rows):
        p = os.path.join(self.tmp.name, name)
        with open(p, "w", encoding="utf-8") as fh:
            fh.write("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))
        return p

    def rep(self, *extra):
        p = run(self.tmp.name, "--format", "json", *extra)
        self.assertEqual(p.returncode, 0, p.stderr)
        return json.loads(p.stdout)

    def md(self, *extra):
        p = run(self.tmp.name, *extra)
        self.assertEqual(p.returncode, 0, p.stderr)
        return p.stdout


class OldData(unittest.TestCase):
    """Records without any v0.3.3 field: no errors, no new sections or columns."""

    def test_fixture_report_unchanged_shape(self):
        p = run(FIX)
        self.assertEqual(p.returncode, 0, p.stderr)
        md = p.stdout
        for frag in ("partial 数", "审核归因数", "未归因数", "含审核归因", "6e. 待修追踪"):
            self.assertNotIn(frag, md)
        r = json.loads(run(FIX, "--format", "json").stdout)
        o = r["quality"]["overall"]
        self.assertEqual((o["verify_partial"], o["attributed_issues"], o["unattributed_found_issues"]), (0, 0, 0))
        self.assertFalse(o["has_found_issues"])
        self.assertEqual(r["followups"], {"total": 0, "open": 0, "fixed": 0, "open_items": []})

    def test_old_export_has_no_new_fields(self):
        p = run(FIX, "--export-anon", "--raw")
        self.assertEqual(p.returncode, 0, p.stderr)
        recs = json.loads(p.stdout)["records"]
        for x in recs:
            for k in ("found_issues", "followups", "plugin_version_at_start"):
                self.assertNotIn(k, x)


class Attribution(Base):
    def rows(self):
        return [
            task("f", "t1", tier="T1", verify_level="code", issues={"integration": 1, "severity_max": "minor"}),
            task("f", "t2", tier="T2", verify_level="code"),
            task("f", "rv", tier="T2", kind="review", verify_level="doc", found_issues=[
                {"severity": "minor", "origin_task_id": "t1"}, {"severity": "major", "origin_task_id": "t2"},
                {"severity": "minor", "origin_task_id": "nope"}, {"severity": "minor"}, "junk"]),
            task("g", "t1", tier="T1"),
            {"type": "run", "run_id": "f", "plugin_version": "0.12.0"},
            {"type": "run", "run_id": "g", "plugin_version": "0.12.0"},
        ]

    def test_quality_counts_on_origin(self):
        self.write("f.jsonl", self.rows())
        q = self.rep()["quality"]
        o = q["overall"]
        self.assertEqual(o["attributed_issues"], 2)
        self.assertEqual(o["unattributed_found_issues"], 2)
        self.assertAlmostEqual(o["avg_issues_integration"], 3 / 4)  # 1 recorded + 2 attributed over 4 tasks
        self.assertEqual(o["major_issues"], 1)  # t2 got a major attributed
        per = {r["run_id"]: r for r in q["per_run"]}
        self.assertAlmostEqual(per["f"]["avg_issues_integration"], 1.0)
        self.assertEqual((per["f"]["attributed_issues"], per["f"]["unattributed_found_issues"]), (2, 2))
        self.assertEqual((per["g"]["attributed_issues"], per["g"]["unattributed_found_issues"]), (0, 0))
        self.assertAlmostEqual(per["g"]["avg_issues_integration"], 0.0)  # g/t1 is not f/t1

    def test_attributed_not_counted_on_review_task(self):
        self.write("f.jsonl", self.rows())
        lv = {g["key"]: g for g in self.rep()["by_verify_level"]}
        # doc level holds only the review task: its own found issues are not escapes of its level
        self.assertAlmostEqual(lv["doc"]["escaped_integration"], 0.0)
        self.assertAlmostEqual(lv["code"]["escaped_integration"], 1.5)  # t1: 1+1, t2: 0+1 over 2
        self.assertEqual(lv["code"]["escaped_major"], 1)
        v = {g["key"]: g for g in self.rep()["by_version"]}
        self.assertAlmostEqual(v["0.12.0"]["escaped_per_task"], 3 / 4)

    def test_md_columns_and_note(self):
        self.write("f.jsonl", self.rows())
        md = self.md()
        self.assertIn("integration（含审核归因）", md)
        self.assertIn("审核归因数", md)
        self.assertIn("未归因数", md)
        self.assertIn("不计入审核任务自己", md)
        head = next(l for l in md.splitlines() if l.startswith("| 范围 |"))
        row = next(l for l in md.splitlines() if l.startswith("| 总体 |"))
        cells = dict(zip([c.strip() for c in head.split("|")], [c.strip() for c in row.split("|")]))
        self.assertEqual((cells["审核归因数"], cells["未归因数"], cells["integration（含审核归因）"]), ("2", "2", "0.75"))

    def test_attribute_function(self):
        a = {"task_id": "a"}
        b = {"task_id": "b", "found_issues": [{"severity": "major", "origin_task_id": "a"},
                                              {"severity": "minor", "origin_task_id": "a"},
                                              {"severity": "minor", "origin_task_id": 3}]}
        extra, un = metrics.attribute([a, b])
        self.assertEqual(extra, {id(a): {"n": 2, "major": True}})
        self.assertEqual(un, 1)
        self.assertEqual(metrics.attribute([{"found_issues": "bad"}, {"found_issues": None}]), ({}, 0))

    def test_self_reference_is_unattributed(self):
        rv = {"task_id": "rv", "found_issues": [{"severity": "major", "origin_task_id": "rv"}]}
        self.assertEqual(metrics.attribute([{"task_id": "a"}, rv]), ({}, 1))
        self.write("s.jsonl", [task("s", "a", verify_level="code"),
                               task("s", "rv", kind="review", verify_level="doc", found_issues=[
                                   {"severity": "major", "origin_task_id": "rv"}, {"severity": "minor", "origin_task_id": "a"}])])
        o = self.rep()["quality"]["overall"]
        self.assertEqual((o["attributed_issues"], o["unattributed_found_issues"], o["major_issues"]), (1, 1, 0))
        self.assertAlmostEqual(o["avg_issues_integration"], 1 / 2)
        lv = {g["key"]: g for g in self.rep()["by_verify_level"]}
        self.assertAlmostEqual(lv["doc"]["escaped_integration"], 0.0)
        self.assertIn("指向审核任务自己", self.md())
        self.assertIn("会重复计数；按约定只记在审核任务里", self.md())
        # anonymized export: self-reference maps to null, and its summary agrees with the raw report
        out = json.loads(run(self.tmp.name, "--export-anon", "--raw").stdout)
        rec = next(x for x in out["records"] if x.get("kind") == "review")
        self.assertEqual([x["origin_task_id"] for x in rec["found_issues"]], [None, "t1"])
        q = out["summary"]["quality"]["overall"]
        self.assertEqual((q["attributed_issues"], q["unattributed_found_issues"], q["major_issues"]), (1, 1, 0))


class Partial(Base):
    def test_partial_counts_as_value_not_pass(self):
        self.write("v.jsonl", [
            task("v", "a", verify_evidence="ok", verify_pass=True),
            task("v", "b", verify_evidence="只核对文档", verify_pass="partial"),
            task("v", "c", verify_evidence="x", verify_pass="partial"),
            task("v", "d", verify_evidence="x", verify_pass=False),
            task("v", "e", verify_pass="yes"),
        ])
        r = self.rep()
        o = r["quality"]["overall"]
        self.assertAlmostEqual(o["verify_rate"], 1 / 5)
        self.assertEqual(o["verify_partial"], 2)
        self.assertEqual(r["coverage"]["fields"]["verify_pass"]["n"], 4)  # partial is a value; "yes" is not
        self.assertEqual(r["by_version"][0]["verify_partial"], 2)
        md = self.md()
        self.assertIn("partial 数", md)
        self.assertIn("partial（只做了部分验证", md)

    def test_export_keeps_partial(self):
        self.write("v.jsonl", [task("v", "a", verify_pass="partial"), task("v", "b", verify_pass="nah")])
        p = run(self.tmp.name, "--export-anon", "--raw")
        recs = [x for x in json.loads(p.stdout)["records"] if x["type"] == "task"]
        self.assertEqual([x["verify_pass"] for x in recs], ["partial", None])


class VersionAtStart(Base):
    def rows(self):
        mk = lambda rid, n, **kw: [task(rid, "t%d" % i, attempts=1, review_outcome="pass") for i in range(n)] + \
            [dict({"type": "run", "run_id": rid}, **kw)]
        return (mk("a", 2, plugin_version="0.3.2")  # old record: only plugin_version
                + mk("b", 3, plugin_version_at_start="0.3.2", plugin_version="0.3.3")  # produced 0.3.3 under 0.3.2
                + mk("c", 4, plugin_version_at_start="0.3.3", plugin_version="0.3.3")
                + mk("d", 1, plugin_version_at_start="", plugin_version="0.3.3"))  # empty start → fall back

    def test_run_version(self):
        self.assertEqual(metrics.run_version({"run": {"plugin_version_at_start": "0.3.2", "plugin_version": "0.3.3"}}), "0.3.2")
        self.assertEqual(metrics.run_version({"run": {"plugin_version": "0.3.3"}}), "0.3.3")
        self.assertEqual(metrics.run_version({"run": {"plugin_version_at_start": 3, "plugin_version": "0.3.3"}}), "0.3.3")
        self.assertIsNone(metrics.run_version({"run": None}))

    def test_by_version_and_filters(self):
        for rid in "abcd":
            self.write("%s.jsonl" % rid, [x for x in self.rows() if x["run_id"] == rid])
        v = {g["key"]: g for g in self.rep()["by_version"]}
        self.assertEqual((v["0.3.2"]["runs"], v["0.3.2"]["n"]), (2, 5))
        self.assertEqual((v["0.3.3"]["runs"], v["0.3.3"]["n"]), (2, 5))
        self.assertEqual(self.rep("--since-version", "0.3.3")["overview"]["tasks"], 5)
        self.assertEqual(self.rep("--before-version", "0.3.3")["overview"]["tasks"], 5)
        self.assertIn("plugin_version_at_start", self.md())

    def test_check_changelog_since_uses_version_at_start(self):
        self.write("all.jsonl", self.rows())
        cl = os.path.join(self.tmp.name, "CHANGELOG.md")
        with open(cl, "w", encoding="utf-8") as fh:
            fh.write("## v0.3.3（2026-11-25）\n\n### x\n- **状态**：待验证\n"
                     "- **验收判定**：`overview.tasks >= 5 n>=1`\n")
        p = run(os.path.join(self.tmp.name, "all.jsonl"), "--check-changelog", cl, "--format", "json")
        self.assertEqual(p.returncode, 0, p.stderr)
        c = json.loads(p.stdout)[0]["criteria"][0]
        self.assertEqual(c["value"], 5)  # runs c and d only; b ran under 0.3.2

    def test_export_keeps_version_at_start(self):
        self.write("all.jsonl", self.rows())
        out = json.loads(run(self.tmp.name, "--export-anon", "--raw").stdout)
        rr = [x["plugin_version_at_start"] for x in out["records"] if x["type"] == "run" and "plugin_version_at_start" in x]
        self.assertEqual(sorted(rr, key=str), ["0.3.2", "0.3.3", None])  # empty start string → null, not "other"
        self.assertEqual(out["plugin_versions"], ["0.3.2", "0.3.3"])
        v = {g["key"]: g["n"] for g in out["summary"]["by_version"]}
        self.assertEqual(v, {"0.3.2": 5, "0.3.3": 5})  # same split as the raw data


class ValueCounts(Base):
    def test_group_and_cost_counts(self):
        self.write("x.jsonl", [
            task("x", "a", tier="T2", kind="code", cost_usd=0.5, tokens=100, est_min=10, actual_min=12),
            task("x", "b", tier="T2", kind="code", tokens=200, est_min=10),
            task("x", "c", tier="T2", kind="code", cost_usd=None, tokens="n/a"),
            task("x", "d", tier="T3", kind="docs"),
        ])
        r = self.rep()
        t2 = next(g for g in r["by_tier"] if g["key"] == "T2")
        self.assertEqual((t2["n"], t2["cost_n"], t2["tokens_n"], t2["ratio_n"]), (3, 1, 2, 1))
        t3 = next(g for g in r["by_tier"] if g["key"] == "T3")
        self.assertEqual((t3["cost_n"], t3["tokens_n"], t3["ratio_n"]), (0, 0, 0))
        for k in ("by_model", "by_host_channel", "by_assist"):
            self.assertIn("cost_n", r[k][0])
        code = next(c for c in r["cost"] if c["key"] == "code")
        self.assertEqual((code["tokens_n"], code["cost_n"]), (2, 1))
        md = self.md()
        self.assertIn("有值数 cost/tokens/ratio", md)
        self.assertIn("| T2 | 3 | 1/2/1 |", md)
        self.assertIn("有值数 tokens/cost", md)
        # CI column still sits right after 一次通过率
        head = next(l for l in md.splitlines() if l.startswith("| 分组 |") and "95%" in l)
        cols = [c.strip() for c in head.strip("|").split("|")]
        self.assertEqual(cols[cols.index("一次通过率") + 1], "一次通过率 95% 区间")


class DowngradeSignal(Base):
    """v0.3.3 downgrade hint: risk=low only, actual/est normalized by the run median, < 0.7 with 1e-9 tolerance."""

    def build(self, n_low=5, low_risk="low", low=(5, 10), ctrl=(10, 10), n_ctrl=None, extra=()):
        rows = [task("x", "l%d" % i, tier="T1", risk=low_risk, attempts=1, review_outcome="pass",
                     est_min=low[1], actual_min=low[0]) for i in range(n_low)]
        rows += [task("x", "c%d" % i, tier="T3", risk="med", attempts=1, review_outcome="pass",
                      est_min=ctrl[1], actual_min=ctrl[0]) for i in range(n_low + 1 if n_ctrl is None else n_ctrl)]
        rows += list(extra)
        self.write("x.jsonl", rows)
        return [s for s in self.rep()["signals"] if "降档" in s["message"]]

    def scopes(self, sigs):
        return [s["scope"] for s in sigs]

    def test_fires_for_low_risk_fast_group(self):
        s = self.build()
        t1 = [x for x in s if x["scope"] == "tier T1"]
        self.assertEqual(len(t1), 1)
        self.assertIn("归一化", t1[0]["message"])
        self.assertIn("0.50", t1[0]["message"])  # 0.5 / run median 1.0
        self.assertEqual(t1[0]["n"], 5)
        self.assertNotIn("tier T3", self.scopes(s))

    def test_whole_run_fast_does_not_fire(self):
        self.assertEqual(self.build(n_ctrl=0), [])  # old rule would fire on raw 0.5

    def test_high_risk_tasks_not_counted(self):
        self.assertEqual(self.build(low_risk="high"), [])
        self.assertEqual(self.build(low_risk="med"), [])
        # failing high-risk tasks in the same tier do not block the low-risk group
        bad = [task("x", "h%d" % i, tier="T1", risk="high", attempts=3, review_outcome="rework",
                    est_min=10, actual_min=5) for i in range(3)]
        s = self.build(extra=bad, n_ctrl=12)
        t1 = [x for x in s if x["scope"] == "tier T1"]
        self.assertEqual(len(t1), 1)
        self.assertEqual(t1[0]["n"], 5)

    def test_low_risk_not_all_first_pass_does_not_fire(self):
        miss = [task("x", "lx", tier="T1", risk="low", attempts=2, review_outcome="pass", est_min=10, actual_min=5)]
        self.assertNotIn("tier T1", self.scopes(self.build(extra=miss, n_ctrl=8)))

    def test_fewer_than_five_does_not_fire(self):
        self.assertEqual(self.build(n_low=4), [])

    def test_exactly_threshold_non_integer_does_not_fire(self):
        # 35/17 ÷ 50/17 is exactly 0.7, but in floating point it is 0.6999999999999998
        self.assertLess((35 / 17) / (50 / 17), 0.7)
        s = self.build(low=(35, 17), ctrl=(50, 17))
        self.assertEqual(s, [])
        g = next(x for x in self.rep()["by_tier"] if x["key"] == "T1")
        self.assertAlmostEqual(g["low_norm_ratio_median"], 0.7, places=9)
        # just below the threshold still fires
        self.assertIn("tier T1", self.scopes(self.build(low=(34, 17), ctrl=(50, 17))))

    def test_confidence_from_low_counts(self):
        s = [x for x in self.build() if x["scope"] == "tier T1"][0]
        self.assertEqual(s["confidence"], "weak")
        self.assertEqual(s["threshold"], metrics.FULL_PASS_FLOOR)
        lo, hi = metrics.wilson(5, 5)
        self.assertAlmostEqual(s["ci"][0], lo)
        self.assertAlmostEqual(s["ci"][1], hi)
        # extra non-low tasks in the group do not change the interval (k/n are low_first_pass_k/low_n)
        med_ = [task("x", "m%d" % i, tier="T1", risk="med", attempts=2, review_outcome="rework", est_min=10, actual_min=10)
                for i in range(20)]
        s2 = [x for x in self.build(extra=med_, n_ctrl=0) if x["scope"] == "tier T1"]
        self.assertEqual(len(s2), 1)
        self.assertAlmostEqual(s2[0]["ci"][0], lo)
        strong = [x for x in self.build(n_low=30) if x["scope"] == "tier T1"][0]
        self.assertEqual(strong["confidence"], "strong")
        self.assertGreater(strong["ci"][0], metrics.FULL_PASS_FLOOR)


class NormalizedLowRisk(Base):
    """Fields behind the downgrade signal."""

    def test_fixture_t1_normalizes_to_one(self):
        r = json.loads(run(FIX, "--format", "json").stdout)
        t1 = next(g for g in r["by_tier"] if g["key"] == "T1")
        self.assertEqual((t1["low_n"], t1["low_norm_ratio_n"]), (5, 5))
        self.assertAlmostEqual(t1["low_first_pass_rate"], 1.0)
        self.assertAlmostEqual(t1["low_norm_ratio_median"], 1.0)  # r1 has only T1 tasks
        t2 = next(g for g in r["by_tier"] if g["key"] == "T2")
        self.assertIsNone(t2["low_norm_ratio_median"])  # r2 has contradictory time data → excluded

    def test_non_integer_normalization(self):
        rows = [task("n", "l%d" % i, tier="T1", risk="low", attempts=1, review_outcome="pass", est_min=10, actual_min=7)
                for i in range(5)]
        rows += [task("n", "h%d" % i, tier="T3", risk="med", attempts=1, review_outcome="pass", est_min=10, actual_min=10)
                 for i in range(5)]
        rows += [task("n", "x", tier="T1", risk="med", est_min=10, actual_min=3)]
        self.write("n.jsonl", rows)
        g = {x["key"]: x for x in self.rep()["by_tier"]}
        # run median of 0.3, 0.7×5, 1.0×5 is 0.7 → low-risk T1 normalized to exactly 1 (0.7/0.7)
        self.assertAlmostEqual(g["T1"]["low_norm_ratio_median"], 1.0, places=9)
        self.assertEqual((g["T1"]["low_n"], g["T1"]["low_norm_ratio_n"]), (5, 5))
        self.assertEqual(g["T3"]["low_n"], 0)
        self.assertIsNone(g["T3"]["low_norm_ratio_median"])
        self.assertAlmostEqual(g["T3"]["ratio_median"], 1.0)

    def test_normalized_ratios_function(self):
        a = {"est_min": 10, "actual_min": 5}
        b = {"est_min": 10, "actual_min": 15}
        z = {"est_min": 10, "actual_min": 0}
        n = metrics.normalized_ratios({"r": {"tasks": [a, b, {"est_min": 0, "actual_min": 3}]}})
        self.assertAlmostEqual(n[id(a)], 0.5)
        self.assertAlmostEqual(n[id(b)], 1.5)
        self.assertEqual(len(n), 2)
        self.assertEqual(metrics.normalized_ratios({"r": {"tasks": [z]}}), {})  # median 0 → skipped
        neg = [{"est_min": 10, "actual_min": -5}, {"est_min": 10, "actual_min": -5}, {"est_min": 10, "actual_min": 8}]
        self.assertEqual(metrics.normalized_ratios({"r": {"tasks": neg}}), {})  # median -0.5 → skipped
        self.assertEqual(metrics.normalized_ratios({"r": {"tasks": [a, b]}}, skip=frozenset({id(a), id(b)})), {})

    def test_negative_median_run_gives_no_signal(self):
        rows = [task("n", "l%d" % i, tier="T1", risk="low", attempts=1, review_outcome="pass", est_min=10,
                     actual_min=-5 if i < 4 else 8) for i in range(7)]
        self.write("n.jsonl", rows)
        r = self.rep()
        g = next(x for x in r["by_tier"] if x["key"] == "T1")
        self.assertIsNone(g["low_norm_ratio_median"])
        self.assertEqual(g["low_norm_ratio_n"], 0)
        self.assertFalse(any("降档" in s["message"] for s in r["signals"]))


class Followups(Base):
    def rows(self):
        return [
            task("u", "a", followups=[{"desc": "补测试", "fixed_in": None}, {"desc": "改文档", "fixed_in": "v0.3.3"},
                                      {"desc": "x"}]),
            task("u", "b", followups=[{"desc": "清理", "fixed_in": ""}, 3, {"desc": "y", "fixed_in": "u/c"}]),
            task("u", "c", followups="bad"),
        ]

    def test_counts_and_section(self):
        self.write("u.jsonl", self.rows())
        fu = self.rep()["followups"]
        self.assertEqual((fu["total"], fu["open"], fu["fixed"]), (5, 3, 2))
        self.assertIn({"run_id": "u", "task_id": "b", "desc": "清理"}, fu["open_items"])
        md = self.md()
        self.assertIn("## 6e. 待修追踪", md)
        self.assertIn("| 5 | 3 | 2 |", md)
        self.assertIn("- [u/a] 补测试", md)

    def test_no_section_without_followups(self):
        self.write("u.jsonl", [task("u", "a"), task("u", "b", followups=[])])
        self.assertNotIn("6e. 待修追踪", self.md())

    def test_export_counts_only(self):
        self.write("u.jsonl", self.rows())
        out = json.loads(run(self.tmp.name, "--export-anon", "--raw").stdout)
        text = json.dumps(out, ensure_ascii=False)
        for secret in ("补测试", "改文档", "清理", "u/c", "v0.3.3"):
            self.assertNotIn(secret, text)
        fu = out["summary"]["followups"]
        self.assertEqual((fu["total"], fu["open"], fu["fixed"]), (5, 3, 2))
        self.assertTrue(all(x["desc"] is None for x in fu["open_items"]))


class AnonFoundIssues(Base):
    def test_severity_and_origin_mapping(self):
        self.write("f.jsonl", [
            task("secret-run", "impl-login", tier="T2"),
            task("secret-run", "review-1", kind="review", found_issues=[
                {"severity": "major", "origin_task_id": "impl-login", "note": "密码明文"},
                {"severity": "critical", "origin_task_id": "elsewhere"}, {"origin_task_id": None}]),
        ])
        out = json.loads(run(self.tmp.name, "--export-anon", "--raw").stdout)
        text = json.dumps(out, ensure_ascii=False)
        for secret in ("impl-login", "elsewhere", "密码明文", "secret-run"):
            self.assertNotIn(secret, text)
        rv = next(x for x in out["records"] if x.get("kind") == "review")
        self.assertEqual(rv["found_issues"], [{"severity": "major", "origin_task_id": "t1"},
                                              {"severity": "other", "origin_task_id": None},
                                              {"severity": None, "origin_task_id": None}])
        q = out["summary"]["quality"]["overall"]
        self.assertEqual((q["attributed_issues"], q["unattributed_found_issues"], q["major_issues"]), (1, 2, 1))


if __name__ == "__main__":
    unittest.main()

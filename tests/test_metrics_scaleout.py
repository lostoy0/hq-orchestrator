"""metrics.py: 4b shard metrics (moved from tests/test_scale.py RetroMetrics, without the removed 4c), the
suggest_shards formula shared with scale.py shard_plan, and regression tests for the metrics.py review fixes."""
import importlib.util
import inspect
import json
import os
import random
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(ROOT, "skills", "hq", "scripts")
METRICS = os.path.join(SCRIPTS, "metrics.py")
sys.path.insert(0, SCRIPTS)
import metrics  # noqa: E402


def run(*args):
    return subprocess.run([sys.executable, METRICS, *args], capture_output=True, text=True)


def write(path, rows=None, text=None):
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text if text is not None else "\n".join(json.dumps(x, ensure_ascii=False) for x in rows) + "\n")


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.d = self.tmp.name

    def path(self, name):
        return os.path.join(self.d, name)

    def report(self, lines, name="r.jsonl"):
        write(self.path(name), lines)
        p = run(self.d, "--format", "json")
        self.assertEqual(p.returncode, 0, p.stderr)
        md = run(self.d)
        self.assertEqual(md.returncode, 0, md.stderr)
        anon = run(self.d, "--export-anon", "--raw")
        self.assertEqual(anon.returncode, 0, anon.stderr)
        return json.loads(p.stdout), md.stdout, json.loads(anon.stdout)


def shard_run(acts=(150, 160, 240, 150), **run_kw):
    recs = [dict({"type": "run", "run_id": "r1", "wall_min": 245, "tasks": len(acts), "max_concurrency": 4,
                  "concurrency_limit": 20, "target_shard_min": 40}, **run_kw)]
    for i, a in enumerate(acts):
        recs.append({"type": "task", "run_id": "r1", "task_id": "s%d" % i, "shard_group": "patrol",
                     "units_planned": 150, "units_actual": 150, "unit_min_est": 1.0, "overhead_min": 8,
                     "actual_min": a, "test_scope": "full", "test_min": 12, "resplit": False})
    recs += [{"type": "merge", "run_id": "r1", "group_seq": 1, "shards": ["s0", "s1"], "verify_runs": 1,
              "full_test": True, "full_test_min": 12},
             {"type": "merge", "run_id": "r1", "group_seq": 2, "shards": ["s2", "s3"], "verify_runs": 1,
              "full_test": True, "full_test_min": 11}]
    return recs


class ScaleOutMetrics(Base):
    def test_scale_out_metrics(self):
        acts = [150, 160, 240, 150]
        rep, md, anon = self.report(shard_run(acts))
        x = rep["scale_out"][0]
        self.assertAlmostEqual(x["parallel_efficiency"], sum(acts) / (4 * 240))
        self.assertAlmostEqual(x["straggler_ratio"], 240 / 155)
        self.assertAlmostEqual(x["concurrency_utilization"], 0.2)
        # per-unit actual (a - 8) / 150 vs 1.0: |errors| 0.053, 0.013, 0.547, 0.053 -> median 0.053
        self.assertAlmostEqual(x["unit_est_error_median"], 8 / 150)
        self.assertEqual(x["unit_est_n"], 4)
        self.assertEqual(x["full_tests"], 6)
        self.assertEqual((x["full_tests_hq"], x["full_tests_worker"]), (2, 4))
        self.assertEqual(x["full_test_min"], 12 * 4 + 23)
        self.assertEqual(x["shards_per_full_test"], 2)
        self.assertEqual((x["merge_groups"], x["shards_per_group"], x["verify_runs"]), (2, 2, 2))
        # measured 0.98 min/unit * 600 units = 588 min; ceil(588/40) = 15; usable 20 - 0; 8/(588/15+8) < 0.3
        self.assertEqual(x["suggest_shards"], 15)
        self.assertEqual((x["reserved_slots"], x["max_overhead_ratio"]), (0, 0.3))
        for k in ("monitor_triggers", "label_sources", "rule_label_share", "monitor_by_metric"):
            self.assertNotIn(k, x)
        msgs = " ".join(s["message"] for s in rep["signals"])
        self.assertIn("同类任务下次切成 15 片", msgs)
        self.assertIn("全量测试改成每 4 片合入后跑一次", msgs)
        self.assertIn("4b. 分片", md)
        self.assertNotIn("4c", md)
        self.assertEqual(anon["summary"]["scale_out"][0]["merge_groups"], 2)
        self.assertEqual({r["type"] for r in anon["records"]}, {"run", "task", "merge"})
        self.assertNotIn("s0", json.dumps(anon["records"]))

    def test_reserved_slots_and_overhead_ratio_from_run(self):
        x = self.report(shard_run(reserved_slots=10))[0]["scale_out"][0]
        self.assertEqual(x["suggest_shards"], 10)  # usable = 20 - 10
        # 0.1 cap: 8/(588/9+8) = 0.109 > 0.1, 8/(588/8+8) = 0.098 -> 8
        x = self.report(shard_run(max_overhead_ratio=0.1))[0]["scale_out"][0]
        self.assertEqual(x["suggest_shards"], 8)

    def test_monitor_records_ignored(self):
        recs = shard_run() + [
            {"type": "monitor", "run_id": "r1", "metric": "idle_min", "level": 2, "label": "false_positive",
             "label_source": ["rule"], "event": {"x": 1}, "analysis_cost_usd": 0.2},
            {"type": "monitor", "run_id": "r1", "event": "missed", "metric": "idle_min"}]
        rep, md, anon = self.report(recs)
        self.assertEqual(rep["scale_out"][0]["merge_groups"], 2)
        self.assertFalse(any("监控" in s["message"] for s in rep["signals"]))
        self.assertNotIn("monitor", json.dumps(anon))
        self.assertNotIn("主动监控", md)

    def test_old_records_without_new_fields(self):
        rep, md, _ = self.report([{"type": "run", "run_id": "old", "wall_min": 30},
                                  {"type": "task", "run_id": "old", "task_id": "t1", "actual_min": 10}])
        self.assertEqual(rep["scale_out"], [])
        self.assertNotIn("4b. 分片", md)

    def test_partial_new_fields_do_not_crash(self):
        rep, _, _ = self.report([{"type": "task", "run_id": "p", "task_id": "s1", "shard_group": "g"},
                                 {"type": "merge", "run_id": "p"}, {"type": "monitor", "run_id": "p"}])
        x = rep["scale_out"][0]
        self.assertIsNone(x["parallel_efficiency"])
        self.assertIsNone(x["suggest_shards"])
        self.assertEqual(x["merge_groups"], 1)

    def test_measured_unit_time_zero_gives_no_suggestion(self):
        recs = [{"type": "run", "run_id": "z", "concurrency_limit": 8, "max_concurrency": 2}]
        recs += [{"type": "task", "run_id": "z", "task_id": "s%d" % i, "shard_group": "g", "units_actual": 10,
                  "overhead_min": 5, "actual_min": 5} for i in range(3)]
        self.assertIsNone(self.report(recs)[0]["scale_out"][0]["suggest_shards"])

    def test_measured_overhead_zero_is_not_replaced_by_default(self):
        recs = [{"type": "run", "run_id": "o", "concurrency_limit": 20, "max_overhead_ratio": 0.1}]
        recs += [{"type": "task", "run_id": "o", "task_id": "s%d" % i, "shard_group": "g", "units_actual": 100,
                  "overhead_min": 0, "actual_min": 100} for i in range(3)]
        # work 300, ceil(300/40) = 8; overhead 0 never trims. With the default 8 it would trim to 4.
        self.assertEqual(self.report(recs)[0]["scale_out"][0]["suggest_shards"], 8)
        self.assertEqual(metrics.suggest_shards(300, 1.0, 8, 40, 20, 0, 0.1), 4)


class SuggestShards(unittest.TestCase):
    def test_formula(self):
        self.assertEqual(metrics.suggest_shards(600, 0.98, 8, 40, 20), 15)
        self.assertEqual(metrics.suggest_shards(600, 0.98, 8, 40, 20, reserve=10), 10)
        self.assertEqual(metrics.suggest_shards(600, 0.98, 8, 40, 5, reserve=10), 1)  # usable floor 1
        self.assertEqual(metrics.suggest_shards(4, 100, 0, 40, 20), 4)  # capped by units
        self.assertIsNone(metrics.suggest_shards(10, 0, 8, 40, 20))
        self.assertIsNone(metrics.suggest_shards(0, 1, 8, 40, 20))

    def test_ceil_float_error(self):
        # 3 * 0.1 / 0.3 = 1.0000000000000002: one shard of target length, not two
        self.assertEqual(metrics.suggest_shards(3, 0.1, 0, 0.3, 20), 1)

    def test_overhead_ratio_exactly_at_cap_keeps_n(self):
        # work 70, target 35 -> n = 2; overhead 15 / (35 + 15) == 0.3 exactly: not over the cap, keep 2
        self.assertEqual(metrics.suggest_shards(70, 1, 15, 35, 20), 2)

    def test_same_as_scale_py_shard_plan(self):
        spec = importlib.util.spec_from_file_location("hq_scale_for_test", os.path.join(SCRIPTS, "scale.py"))
        scale = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(scale)
        params = inspect.signature(scale.shard_plan).parameters
        self.assertIn("reserve", params)
        rnd = random.Random(20261127)
        for _ in range(500):
            units = rnd.randint(1, 400)
            unit_min = rnd.choice([0.1, 0.3, 0.5, 0.98, 1.0, 1.4, 2.5, 7.0, round(rnd.uniform(0.05, 10), 2)])
            overhead = rnd.choice([0, 2, 5, 8, 15, round(rnd.uniform(0, 30), 1)])
            target = rnd.choice([0.3, 20, 30, 40, 60, round(rnd.uniform(5, 90), 1)])
            limit = rnd.randint(1, 40)
            reserve = rnd.randint(0, 10)
            mor = rnd.choice([0.1, 0.2, 0.3, 0.5])
            want = metrics.suggest_shards(units, unit_min, overhead, target, limit, reserve, mor)
            got = scale.shard_plan(units, unit_min, overhead_min=overhead, target_min=target, limit=limit,
                                   reserve=reserve, max_overhead_ratio=mor)["shards"]
            self.assertEqual(got, want, (units, unit_min, overhead, target, limit, reserve, mor))


class OverheadRatioZero(Base):
    """p5 item 7: a run record's max_overhead_ratio of 0 is a real cap (as in scale.py), not "unset"."""
    def test_zero_ratio_is_kept_and_matches_scale_py(self):
        spec = importlib.util.spec_from_file_location("hq_scale_for_test2", os.path.join(SCRIPTS, "scale.py"))
        scale = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(scale)
        results = {}
        for mor in (0, 0.3):
            rep = self.report(shard_run(max_overhead_ratio=mor))[0]["scale_out"][0]
            self.assertEqual(rep["max_overhead_ratio"], mor)
            want = scale.shard_plan(600, 1.0, overhead_min=8, target_min=40, limit=20, reserve=0,
                                    max_overhead_ratio=mor)["shards"]
            self.assertEqual(rep["suggest_shards"], want, mor)
            results[mor] = rep["suggest_shards"]
        self.assertEqual(results[0], 1)
        self.assertGreater(results[0.3], 1)


class ScaleSignalBoundaries(Base):
    """Major 1: thresholds exactly at 50% / 2 / 0.5 must not fire through float error."""
    def test_unit_error_exactly_50_percent_does_not_fire(self):
        recs = [{"type": "run", "run_id": "u", "concurrency_limit": 8}]
        recs += [{"type": "task", "run_id": "u", "task_id": "s%d" % i, "shard_group": "g", "units_actual": 10,
                  "actual_min": 21, "unit_min_est": 1.4, "overhead_min": 0} for i in range(3)]
        rep = self.report(recs)[0]
        self.assertAlmostEqual(rep["scale_out"][0]["unit_est_error_median"], 0.5)
        self.assertFalse([s for s in rep["signals"] if "单元耗时估算误差" in s["message"]])

    def test_straggler_and_utilization_exactly_at_threshold(self):
        out = []
        add = metrics.make_add(out)
        x = {"run_id": "r", "shards": 4, "concurrency_utilization": 0.5, "concurrency_limit": 8,
             "straggler_ratio": 2.0000000000000004, "full_tests": 2, "unit_est_error_median": None,
             "unit_est_n": 0, "suggest_shards": None}
        metrics.scale_signals([x], add)
        self.assertEqual(out, [])
        metrics.scale_signals([dict(x, concurrency_utilization=0.49, straggler_ratio=2.1, full_tests=3)], add)
        self.assertEqual(len(out), 3)


class EvalExpr(unittest.TestCase):
    def test_float_sum_equal_to_threshold(self):  # major 2
        r = metrics.eval_expr("sum(c[*].avg_cost_usd) <= 0.3 n>=2", {"c": [{"avg_cost_usd": 0.1}, {"avg_cost_usd": 0.2}]})
        self.assertEqual(r["verdict"], "达到")
        r = metrics.eval_expr("sum(c[*].v) >= 0.3 n>=2", {"c": [{"v": 0.1}, {"v": 0.2}]})
        self.assertEqual(r["verdict"], "达到")
        r = metrics.eval_expr("sum(c[*].v) == 0.3 n>=2", {"c": [{"v": 0.1}, {"v": 0.2}]})
        self.assertEqual(r["verdict"], "达到")
        r = metrics.eval_expr("sum(c[*].v) < 0.3 n>=2", {"c": [{"v": 0.1}, {"v": 0.2}]})
        self.assertEqual(r["verdict"], "未达到")

    def test_n_follows_the_field(self):  # major 5
        rep = {"by_tier": [{"key": "T1", "n": 5, "ratio_n": 1, "cost_n": 2, "tokens_n": 5,
                            "ratio_median": 1.0, "avg_cost_usd": 0.1, "avg_tokens": 10, "first_pass_rate": 1}]}
        self.assertEqual(metrics.eval_expr("by_tier[key=T1].ratio_median <= 2", rep)["n"], 1)
        self.assertEqual(metrics.eval_expr("by_tier[key=T1].ratio_median <= 2", rep)["verdict"], "样本不足")
        self.assertEqual(metrics.eval_expr("by_tier[key=T1].avg_cost_usd <= 2", rep)["n"], 2)
        self.assertEqual(metrics.eval_expr("by_tier[key=T1].avg_tokens <= 20", rep)["n"], 5)
        self.assertEqual(metrics.eval_expr("by_tier[key=T1].first_pass_rate >= 1", rep)["n"], 5)

    def test_by_version_rows_have_value_counts(self):  # major 5
        runs = {"a": {"run": {"plugin_version": "0.1.0"}, "merges": [],
                      "tasks": [{"type": "task", "task_id": "t%d" % i, "est_min": 10,
                                 "actual_min": 10 if i == 0 else None, "cost_usd": 0.1 if i < 2 else None}
                                for i in range(4)]}}
        row = metrics.build(runs, 0)["by_version"][0]
        self.assertEqual((row["n"], row["ratio_n"], row["cost_n"]), (4, 1, 2))
        r = metrics.eval_expr("by_version[key=0.1.0].ratio_median <= 2", metrics.build(runs, 0))
        self.assertEqual((r["n"], r["verdict"]), (1, "样本不足"))

    def test_value_without_size_uses_task_count(self):  # major 6
        r = metrics.eval_expr("adjust.escalated == 0", metrics.build({}, 0))
        self.assertEqual((r["value"], r["n"], r["verdict"]), (0, 0, "样本不足"))
        runs = {"a": {"run": None, "merges": [], "tasks": [{"type": "task", "task_id": "t%d" % i} for i in range(3)]}}
        r = metrics.eval_expr("adjust.escalated == 0", metrics.build(runs, 0))
        self.assertEqual((r["n"], r["verdict"]), (3, "达到"))


def vruns(spec):
    """spec: {version: (rework, total)} -> runs dict in memory."""
    out = {}
    for v, (k, n) in spec.items():
        out[v] = {"run": {"plugin_version": v}, "merges": [],
                  "tasks": [{"task_id": "t%d" % i, "review_outcome": "rework" if i < k else "pass"} for i in range(n)]}
    return out


class QualityGuard(unittest.TestCase):  # major 3
    def test_exactly_five_points_does_not_fire(self):
        self.assertIsNone(metrics.quality_guard(vruns({"0.1.0": (7, 20), "0.2.0": (8, 20)}), "0.2.0", None))
        self.assertIsNone(metrics.quality_guard(vruns({"0.1.0": (2, 20), "0.2.0": (3, 20)}), "0.2.0", None))

    def test_more_than_five_points_fires(self):
        self.assertIsNotNone(metrics.quality_guard(vruns({"0.1.0": (2, 20), "0.2.0": (4, 20)}), "0.2.0", None))
        self.assertIsNotNone(metrics.quality_guard(vruns({"0.1.0": (7, 20), "0.2.0": (9, 20)}), "0.2.0", None))

    def test_before_bound_is_used(self):
        runs = vruns({"0.1.0": (0, 10), "0.2.0": (0, 10), "0.3.0": (9, 10)})
        self.assertIsNone(metrics.quality_guard(runs, "0.2.0", "0.3.0"))
        self.assertIsNotNone(metrics.quality_guard(runs, "0.2.0", None))


class MergeDedupe(Base):  # major 4, acceptance 3
    def test_same_run_from_two_dirs(self):
        recs = shard_run() + [{"type": "merge", "run_id": "r1", "shards_n": 1, "verify_runs": 1, "full_test": True}]
        for sub in ("proj", "home"):
            os.makedirs(self.path(sub))
            write(os.path.join(self.d, sub, "r1.jsonl"), recs)
        p = run(self.d, "--format", "json")
        self.assertEqual(p.returncode, 0, p.stderr)
        rep = json.loads(p.stdout)
        x = rep["scale_out"][0]
        self.assertEqual(rep["overview"]["tasks"], 4)
        self.assertEqual((x["merge_groups"], x["verify_runs"], x["full_tests_hq"], x["full_tests"]), (3, 3, 3, 7))

    def test_updated_merge_record_replaces_earlier(self):
        recs = [{"type": "merge", "run_id": "m", "group_seq": 1, "shards": ["a"], "verify_runs": 1},
                {"type": "merge", "run_id": "m", "group_seq": 1, "shards": ["a"], "verify_runs": 2},
                {"type": "task", "run_id": "m", "task_id": "a", "shard_group": "g"}]
        x = self.report(recs)[0]["scale_out"][0]
        self.assertEqual((x["merge_groups"], x["verify_runs"]), (1, 2))


class AnonPrivacy(Base):  # majors 7, 8; acceptance 2
    def test_no_secret_in_export(self):
        S = "SECRET"
        t = {"type": "task", "run_id": "r", "task_id": "t1", "tier": "T2", "attempts": 1, "review_outcome": "pass",
             "flags": ["billing:SECRET", "effort_env:SECRET", "assist_unavailable:SECRET", "SECRET", "bias:+1(tier)",
                       "billing:deepseek", "effort_env:max", ["SECRET"], {"SECRET": 1}],
             "notes": "billing:SECRET2 effort_env:SECRET3 assist_unavailable:SECRET4 not rate_limited_at_all",
             "kind": [S], "risk": {S: S}, "host": [S], "channel": {"a": S}, "verify_level": [S], "plan_tier": {S: 1},
             "review_outcome_x": S, "model": "x " + S, "effort": S, "assist": [S],
             "task_type": [S], "test_scope": {S: S}, "shard_group": [S],
             "issues": {"review": 1, "severity_max": [S]},
             "found_issues": [{"severity": [S], "origin_task_id": [S]}, {"severity": {S: 1}, "origin_task_id": S}],
             "independent_review": {"ran": True, "trigger": {S: S}, "findings": [S]},
             "score": {"scope": [S], "risk": {S: 1}}, "followups": [{"desc": S, "fixed_in": S}],
             "tier_changes": [{"from": [S], "to": {S: 1}, "reason": S}], "verify_pass": [S]}
        r = {"type": "run", "run_id": "r", "project": S, "goal": S, "host": {S: 1}, "plugin_version": "0.1.0-" + S,
             "plugin_version_at_start": [S], "integration_pass": [S], "from_recommendation": S}
        m = {"type": "merge", "run_id": "r", "group_seq": [S], "shards": [S], "full_test": [S], "reasons": [S]}
        mon = {"type": "monitor", "run_id": "r", "metric": [S], "event": {S: S}, "label": [S], "task_type": [S]}
        write(self.path("r.jsonl"), [t, r, m, mon])
        p = run(self.d, "--export-anon", "--raw")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertNotIn(S, p.stdout)
        out = json.loads(p.stdout)
        task = next(x for x in out["records"] if x["type"] == "task")
        self.assertEqual(task["flags"], ["billing:other", "effort_env:other", "assist_unavailable:other",
                                         "bias:+1(tier)", "billing:deepseek", "effort_env:max"])
        self.assertEqual((task["kind"], task["task_type"], task["effort"]), ("other", "other", "other"))
        run_rec = next(x for x in out["records"] if x["type"] == "run")
        self.assertEqual(run_rec["plugin_version"], "0.1.0")

    def test_model_and_assist_only_known_shapes(self):
        S = "SECRET"
        cases = {"claude-opus-4-5": "claude-opus-4-5", "gpt-5.1-codex-max": "gpt-5.1-codex-max", "o3": "o3",
                 "gemini-2.5-pro": "gemini-2.5-pro", "kimi-k2": "kimi-k2", "deepseek-v3": "deepseek-v3",
                 "codex:gpt-5.2": "codex:gpt-5.2", "sonnet": "sonnet", "haiku": "haiku", "opus": "opus",
                 S: "other", "sk-" + S + "123": "other", "my-" + S: "other", "claude-" + "a1B2" * 8: "other",
                 "x " + S: "other", 7: "other", "": "other"}
        for model, want in cases.items():
            recs = [{"type": "task", "run_id": "r", "task_id": "t1", "model": model, "assist": model}]
            write(self.path("r.jsonl"), recs)
            p = run(self.d, "--export-anon", "--raw")
            self.assertEqual(p.returncode, 0, p.stderr)
            task = next(x for x in json.loads(p.stdout)["records"] if x["type"] == "task")
            self.assertEqual(task["model"], want, model)
            self.assertNotIn(S, p.stdout, model)
            self.assertIn(task["assist"], {"other"}, model)  # none of these is a profile name

    def test_assist_profile_names_survive(self):
        for name in ("codex", "kimi", "claude", "opencode", "gemini", "cursor"):
            self.assertEqual(metrics.a_assist(name), name)
        self.assertEqual(metrics.a_assist("SECRET-profile"), "other")
        self.assertIsNone(metrics.a_assist(None))

    def test_note_flags_need_boundaries(self):
        t = {"notes": "not rate_limited_at_all; xbilling:kimi; 限流 rate_limited；中文billing:kimi"}
        self.assertEqual(metrics.task_flags(t), ["rate_limited", "billing:kimi"])


class VersionArgs(Base):  # major 9
    def test_cli_rejects_unparseable_versions(self):
        write(self.path("r.jsonl"), [{"type": "run", "run_id": "a", "plugin_version": "0.10.6"}])
        for opt in ("--since-version", "--before-version"):
            p = run(self.d, opt, "0.11")
            self.assertNotEqual(p.returncode, 0)
            self.assertIn("cannot parse version", p.stderr)
        self.assertEqual(run(self.d, "--since-version", "V0.10.0").returncode, 0)

    def test_check_changelog_unparseable_since(self):
        write(self.path("r.jsonl"), [{"type": "run", "run_id": "a", "plugin_version": "0.10.6"},
                                     {"type": "task", "run_id": "a", "task_id": "t1"}])
        cl = self.path("CHANGELOG.md")
        write(cl, text="## 未发布\n\n### x\n- **状态**：待验证\n- **验收判定**：`quality.overall.n >= 1 n>=1 since=abc`\n")
        p = run(self.d, "--check-changelog", cl, "--format", "json")
        self.assertEqual(p.returncode, 0, p.stderr)
        r = json.loads(p.stdout)[0]
        self.assertEqual((r["criteria"][0]["verdict"], r["verdict"]), ("无法解析", "无法解析"))

    def test_check_changelog_missing_file(self):
        write(self.path("r.jsonl"), [{"type": "run", "run_id": "a"}])
        p = run(self.d, "--check-changelog", self.path("nope.md"))
        self.assertNotEqual(p.returncode, 0)
        self.assertNotIn("Traceback", p.stderr)


FENCE = "`" * 3


class ParseChangelog(unittest.TestCase):
    def test_code_fence_ignored(self):  # major 10
        text = ("## v0.2.0\n\n### real\n- **状态**：待验证\n\n" + FENCE + "markdown\n## v9.9.9\n\n### fake\n"
                "- **状态**：已验证\n- **验收判定**：`overview.tasks >= 100`\n" + FENCE + "\n\n"
                "- **验收判定**：`overview.tasks >= 1`\n\n### next\n- **状态**：已撤回\n")
        es = metrics.parse_changelog(text)
        self.assertEqual([e["title"] for e in es], ["real", "next"])
        self.assertEqual((es[0]["version"], es[0]["status"], es[0]["exprs"]), ("0.2.0", "待验证", ["overview.tasks >= 1"]))
        self.assertEqual(es[1]["version"], "0.2.0")

    def test_status_variants_and_multiline_judge(self):
        text = ("## v0.2.0\n\n### a\n- **状态**：待验证，自测通过\n- **验收判定**：\n  `overview.tasks >= 1 n>=1`；\n"
                "  `overview.runs >= 1 n>=1`\n- **原因**：x\n\n### b\n- **状态**：**待验证**\n\n### c\n- **状态**：暂缓\n")
        es = {e["title"]: e for e in metrics.parse_changelog(text)}
        self.assertEqual(es["a"]["status"], "待验证")
        self.assertEqual(es["a"]["exprs"], ["overview.tasks >= 1 n>=1", "overview.runs >= 1 n>=1"])
        self.assertEqual(es["b"]["status"], "待验证")
        self.assertEqual(es["c"]["status"], "暂缓")

    def test_not_applicable_and_mentions_are_not_expressions(self):
        text = ("## v0.2.0\n\n### a\n- **验收判定**：不适用，见 `scale.py shards` 命令\n- **状态**：待验证\n\n"
                "### b\n- **验收判定**：`overview.tasks >= 1`；另见 `scale.py shards`\n- **状态**：待验证\n")
        es = {e["title"]: e for e in metrics.parse_changelog(text)}
        self.assertEqual(es["a"]["exprs"], [])
        self.assertEqual(es["b"]["exprs"], ["overview.tasks >= 1"])

    def test_bracket_version_heading_and_no_since(self):
        text = ("### before-any-heading\n- **状态**：待验证\n- **验收判定**：`overview.tasks >= 0 n>=0`\n\n"
                "## [0.10.0] - 2026-01-01\n\n### x\n- **状态**：待验证\n")
        es = metrics.parse_changelog(text)
        self.assertEqual([e["version"] for e in es], [None, "0.10.0"])
        with tempfile.TemporaryDirectory() as d:
            cl = os.path.join(d, "CHANGELOG.md")
            write(cl, text=text)
            r = metrics.check_changelog(cl, {}, 0)
        self.assertEqual(r[0]["criteria"][0]["verdict"], "无法解析")
        self.assertEqual(r[0]["verdict"], "无法解析")


class VersionsAndRecommendations(Base):
    def test_versions_normalized_and_fallback(self):
        self.assertEqual(metrics.run_version({"run": {"plugin_version_at_start": "dev", "plugin_version": "0.3.3"}}), "0.3.3")
        self.assertEqual(metrics.vtuple("V0.11.0"), (0, 11, 0))
        recs = [{"type": "run", "run_id": "a", "plugin_version": "v0.11.0"},
                {"type": "run", "run_id": "b", "plugin_version": "0.11.0"},
                {"type": "task", "run_id": "a", "task_id": "t"}, {"type": "task", "run_id": "b", "task_id": "t"}]
        rows = self.report(recs)[0]["by_version"]
        self.assertEqual([(g["key"], g["runs"], g["n"]) for g in rows], [("0.11.0", 2, 2)])

    def test_by_version_ratio_skips_contradictory_runs(self):
        recs = [{"type": "run", "run_id": "a", "plugin_version": "0.1.0", "wall_min": 5},
                {"type": "task", "run_id": "a", "task_id": "t", "est_min": 1, "actual_min": 10}]
        row = self.report(recs)[0]["by_version"][0]
        self.assertEqual((row["ratio_median"], row["ratio_n"]), (None, 0))

    def test_standing_pairs_independent_of_file_order(self):
        recs = [{"type": "run", "run_id": "s%d" % k, "project": "p", "standing_seq": k, "recommended_next": 2,
                 "from_recommendation": True} for k in (3, 2, 1)]  # reversed, no started_at
        rc = self.report(recs)[0]["recommendations"]
        self.assertEqual((rc["offered"], rc["accepted"]), (2, 2))

    def test_recommended_next_false_is_not_a_claim(self):
        recs = [{"type": "run", "run_id": "s1", "project": "p", "standing_seq": 1, "recommended_next": False},
                {"type": "run", "run_id": "s2", "project": "p", "standing_seq": 2, "recommended_next": 0.0}]
        self.assertEqual(self.report(recs)[0]["recommendations"]["completion_claims"], 1)


class ReportLayout(Base):
    ORDER = ["## 1. ", "## 1b. ", "## 2. ", "## 3a. ", "## 3b. ", "## 3c. ", "## 3f. ", "## 3g. ", "## 3h. ",
             "## 4. ", "## 4b. ", "## 5. ", "## 6. ", "## 6b. ", "## 6c. ", "## 7. "]

    def test_sections_in_number_order(self):
        recs = shard_run()
        recs[0].update(plugin_version="0.11.0", project="p", standing_seq=1, recommended_next=1)
        recs[1].update(verify_level="code", flags=["rate_limited"])
        md = self.report(recs)[1]
        pos = [md.index(h) for h in self.ORDER]
        self.assertEqual(pos, sorted(pos))

    def test_old_data_hides_3f_3g(self):
        md = self.report([{"type": "run", "run_id": "o"}, {"type": "task", "run_id": "o", "task_id": "t"}])[1]
        self.assertNotIn("3f.", md)
        self.assertNotIn("3g.", md)


if __name__ == "__main__":
    unittest.main()

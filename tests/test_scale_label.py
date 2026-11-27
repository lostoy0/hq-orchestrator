import importlib.util
import json
import os
import subprocess
import sys
import unittest
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, "skills", "hq", "scripts", "scale.py")

spec = importlib.util.spec_from_file_location("scale", SCRIPT)
scale = importlib.util.module_from_spec(spec)
spec.loader.exec_module(scale)

T0 = datetime(2026, 11, 27, 10, 0, tzinfo=timezone.utc)


def at(minutes):
    return (T0 + timedelta(minutes=minutes)).strftime("%Y-%m-%dT%H:%M:%SZ")


def cli(*args, stdin=None):
    p = subprocess.run([sys.executable, SCRIPT, *args], input=stdin, capture_output=True, text=True)
    return p.returncode, (json.loads(p.stdout) if p.stdout.strip() else None), p.stderr


def rec(metric, task_id="s1", task_type="patrol", ts=60, **kw):
    r = {"type": "monitor", "event": "trigger", "run_id": "r1", "batch_id": "b1", "ts": at(ts),
         "task_id": task_id, "task_type": task_type, "metric": metric, "value": 3.0,
         "threshold": scale.DEFAULT_THRESHOLDS[metric], "severity": "normal", "level": 1,
         "action": scale.LEVEL1[metric], "key": "%s:x" % metric, "rate_limited": False, "label": None}
    r.update(kw)
    return r


def one(r, outcomes):
    res = scale.label_records([r], outcomes)
    if res["records"]:
        return res["records"][0]["label"], res
    return None, res


class DurationLike(unittest.TestCase):
    def test_resplit_saved_enough_is_effective(self):
        lab, res = one(rec("duration_ratio"), {"s1": {"action_taken": "resplit", "expected_saving_min": 60,
                                                       "actual_saving_min": 40, "est_min": 40, "actual_min": 100}})
        self.assertEqual(lab, "effective")
        self.assertEqual(res["records"][0]["label_source"], "rule")
        self.assertTrue(res["records"][0]["label_reason"])

    def test_saving_exactly_half_is_effective(self):
        # boundary: actual saving == 50% of the expected saving -> effective (rule is >=)
        lab, _ = one(rec("duration_ratio"), {"s1": {"action_taken": "resplit", "expected_saving_min": 60,
                                                     "actual_saving_min": 30}})
        self.assertEqual(lab, "effective")

    def test_resplit_saved_too_little_is_false_positive(self):
        lab, _ = one(rec("duration_ratio"), {"s1": {"action_taken": "resplit", "expected_saving_min": 60,
                                                     "actual_saving_min": 29.9}})
        self.assertEqual(lab, "false_positive")

    def test_no_action_on_time_is_false_positive(self):
        lab, _ = one(rec("duration_ratio"), {"s1": {"action_taken": False, "est_min": 40, "actual_min": 44}})
        self.assertEqual(lab, "false_positive")

    def test_no_action_exactly_1_2x_is_false_positive(self):
        # boundary: actual == 1.2 x estimate counts as finished normally (rule is <=)
        lab, _ = one(rec("duration_ratio"), {"s1": {"action_taken": False, "est_min": 40, "actual_min": 48}})
        self.assertEqual(lab, "false_positive")

    def test_no_action_over_time_is_unlabeled(self):
        lab, res = one(rec("duration_ratio"), {"s1": {"action_taken": False, "est_min": 40, "actual_min": 48.1}})
        self.assertIsNone(lab)
        self.assertEqual(len(res["unlabeled"]), 1)
        self.assertIsNone(res["unlabeled"][0]["label"])
        self.assertNotIn("label_source", res["unlabeled"][0])

    def test_action_without_saving_data_is_unlabeled(self):
        lab, _ = one(rec("duration_ratio"), {"s1": {"action_taken": "resplit"}})
        self.assertIsNone(lab)

    def test_no_outcome_is_unlabeled(self):
        lab, res = one(rec("duration_ratio"), {})
        self.assertIsNone(lab)
        self.assertIn("no outcome", res["unlabeled"][0]["label_reason"])

    def test_straggler_batch_outcome(self):
        r = rec("straggler_ratio", task_id="batch")
        self.assertEqual(one(r, {"batch": {"action_taken": "resplit", "expected_saving_min": 50,
                                           "actual_saving_min": 45}})[0], "effective")
        self.assertEqual(one(r, {"batch": {"action_taken": False, "est_min": 60, "actual_min": 65}})[0],
                         "false_positive")

    def test_split_metrics_use_by_metric_override(self):
        outcomes = {"batch": {"est_min": 60, "actual_min": 200, "action_taken": False,
                              "by_metric": {"split_unit_error": {"action_taken": "replan", "expected_saving_min": 80,
                                                                 "actual_saving_min": 50}}}}
        res = scale.label_records([rec("split_unit_error", task_id="batch"), rec("split_uneven", task_id="batch"),
                                   rec("split_underused", task_id="batch")], outcomes)
        self.assertEqual([r["metric"] for r in res["records"]], ["split_unit_error"])
        self.assertEqual(res["records"][0]["label"], "effective")
        self.assertEqual(sorted(r["metric"] for r in res["unlabeled"]), ["split_underused", "split_uneven"])

    def test_split_underused_false_positive(self):
        lab, _ = one(rec("split_underused", task_id="batch"),
                     {"batch": {"action_taken": "replan", "expected_saving_min": 40, "actual_saving_min": 5}})
        self.assertEqual(lab, "false_positive")


class Idle(unittest.TestCase):
    def prog(self, *pairs):
        return [{"ts": at(t), "done": d} for t, d in pairs]

    def test_progress_after_reminder_is_effective(self):
        # stalled since minute 20, reminder at 60, progress at the 2nd check-in after it
        o = {"s1": {"progress": self.prog((0, 0), (20, 5), (40, 5), (60, 5), (80, 5), (100, 9)),
                    "est_min": 40, "actual_min": 150}}
        self.assertEqual(one(rec("idle_min"), o)[0], "effective")

    def test_waiting_on_background_task_is_false_positive(self):
        # rising before the stall, rising again only later (3rd check-in), finished within 1.2 x estimate
        o = {"s1": {"progress": self.prog((0, 0), (20, 5), (40, 5), (60, 5), (80, 5), (100, 5), (120, 10)),
                    "est_min": 120, "actual_min": 130}}
        self.assertEqual(one(rec("idle_min"), o)[0], "false_positive")

    def test_conflicting_evidence_is_unlabeled(self):
        o = {"s1": {"progress": self.prog((0, 0), (20, 5), (40, 5), (60, 5), (80, 8)),
                    "est_min": 100, "actual_min": 100}}
        lab, res = one(rec("idle_min"), o)
        self.assertIsNone(lab)
        self.assertIn("conflicting", res["unlabeled"][0]["label_reason"])

    def test_no_progress_is_unlabeled(self):
        o = {"s1": {"progress": self.prog((0, 0), (20, 0), (60, 0), (80, 0), (100, 0)),
                    "est_min": 40, "actual_min": 40}}
        self.assertIsNone(one(rec("idle_min"), o)[0])


class Failure(unittest.TestCase):
    def test_located_is_effective(self):
        self.assertEqual(one(rec("failure_rate", task_id="batch"), {"batch": {"located": True, "culprits": ["s3"]}})[0],
                         "effective")

    def test_rerun_passed_is_false_positive(self):
        self.assertEqual(one(rec("failure_rate", task_id="batch"), {"batch": {"located": False, "rerun_passed": True}})[0],
                         "false_positive")

    def test_neither_is_unlabeled(self):
        self.assertIsNone(one(rec("failure_rate", task_id="batch"), {"batch": {"located": False}})[0])


class Rework(unittest.TestCase):
    def test_no_more_rework_is_effective(self):
        self.assertEqual(one(rec("rework"), {"s1": {"rework_after_message": 0}})[0], "effective")

    def test_more_rework_is_unlabeled(self):
        self.assertIsNone(one(rec("rework"), {"s1": {"rework_after_message": 2}})[0])

    def test_unknown_is_unlabeled(self):
        self.assertIsNone(one(rec("rework"), {"s1": {"actual_min": 30}})[0])


class Cost(unittest.TestCase):
    def test_stop_or_adjust_is_effective(self):
        for d in ("stop", "adjust"):
            self.assertEqual(one(rec("cost_ratio"), {"s1": {"user_decision": d}})[0], "effective")

    def test_continue_within_budget_is_false_positive(self):
        # boundary: final cost == 1.2 x budget counts as within (<=)
        self.assertEqual(one(rec("cost_ratio"), {"s1": {"user_decision": "continue", "final_cost_usd": 1.2,
                                                         "budget_usd": 1.0}})[0], "false_positive")

    def test_continue_over_budget_is_unlabeled(self):
        self.assertIsNone(one(rec("cost_ratio"), {"s1": {"user_decision": "continue", "final_cost_usd": 1.3,
                                                          "budget_usd": 1.0}})[0])

    def test_no_decision_is_unlabeled(self):
        self.assertIsNone(one(rec("cost_ratio"), {"s1": {"final_cost_usd": 0.5, "budget_usd": 1.0}})[0])


class Boundary(unittest.TestCase):
    def test_conflict_is_effective(self):
        self.assertEqual(one(rec("split_boundary", task_id="batch"),
                             {"batch": {"merge_conflicts": 1, "ownership_violations": 0}})[0], "effective")
        self.assertEqual(one(rec("split_boundary", task_id="batch"),
                             {"batch": {"merge_conflicts": 0, "ownership_violations": 2}})[0], "effective")

    def test_clean_is_false_positive(self):
        self.assertEqual(one(rec("split_boundary", task_id="batch"),
                             {"batch": {"merge_conflicts": 0, "ownership_violations": 0}})[0], "false_positive")

    def test_unknown_is_unlabeled(self):
        self.assertIsNone(one(rec("split_boundary", task_id="batch"), {"batch": {"merge_conflicts": 0}})[0])


class Existing(unittest.TestCase):
    def test_existing_label_kept(self):
        r = rec("duration_ratio", label="effective", label_source="reviewer")
        res = scale.label_records([r], {"s1": {"action_taken": False, "est_min": 40, "actual_min": 40}})
        self.assertEqual(res["records"], [r])
        self.assertEqual(res["unlabeled"], [])

    def test_existing_missed_record_passes_through_and_is_not_duplicated(self):
        m = {"type": "monitor", "event": "missed", "metric": "duration_ratio", "task_id": "s2", "task_type": "patrol"}
        res = scale.label_records([m], {"s2": {"est_min": 40, "actual_min": 100}})
        self.assertEqual(res["records"], [m])
        self.assertEqual(res["missed"], [])


class Missed(unittest.TestCase):
    def test_duration_miss(self):
        res = scale.label_records([rec("idle_min", task_id="s1")],
                                  {"s1": {"est_min": 40, "actual_min": 90},
                                   "s2": {"est_min": 40, "actual_min": 81, "task_type": "dev"},
                                   "s3": {"est_min": 40, "actual_min": 80}})  # exactly 2 x: not a miss (strict >)
        got = sorted((m["task_id"], m["task_type"]) for m in res["missed"])
        self.assertEqual(got, [("s1", "patrol"), ("s2", "dev")])
        m = res["missed"][0]
        self.assertEqual((m["type"], m["event"], m["metric"], m["label_source"]),
                         ("monitor", "missed", "duration_ratio", "rule"))
        self.assertEqual(m["batch_id"], "b1")

    def test_no_duration_miss_when_triggered(self):
        res = scale.label_records([rec("duration_ratio", task_id="s1")], {"s1": {"est_min": 40, "actual_min": 200}})
        self.assertEqual(res["missed"], [])

    def test_failure_rate_miss(self):
        o = {"batch": {"verify_failed_groups": 1, "failure_rate": 0.3, "task_type": "patrol"}}
        res = scale.label_records([], o)
        self.assertEqual(len(res["missed"]), 1)
        self.assertEqual((res["missed"][0]["metric"], res["missed"][0]["task_id"]), ("failure_rate", "batch"))

    def test_failure_rate_no_miss_below_threshold_or_triggered(self):
        self.assertEqual(scale.label_records([], {"batch": {"verify_failed_groups": 1, "failure_rate": 0.3,
                                                            "failure_rate_threshold": 0.35}})["missed"], [])
        self.assertEqual(scale.label_records([], {"batch": {"verify_failed_groups": 1, "failure_rate": 0.2}})["missed"], [])
        self.assertEqual(scale.label_records([], {"batch": {"verify_failed_groups": 0, "failure_rate": 0.4}})["missed"], [])
        trig = rec("failure_rate", task_id="batch")
        self.assertEqual(scale.label_records([trig], {"batch": {"verify_failed_groups": 1, "failure_rate": 0.4}})["missed"], [])


class EndToEnd(unittest.TestCase):
    def test_label_output_feeds_calibrate_loosen(self):
        # 6 idle triggers on dev shards: 2 rose after the reminder, 4 were waiting on background work
        records, outcomes = [], {}
        for i in range(6):
            sid = "s%d" % i
            records.append(rec("idle_min", task_id=sid, task_type="dev"))
            if i < 2:
                prog = [(0, 0), (20, 5), (60, 5), (80, 9)]
                outcomes[sid] = {"progress": [{"ts": at(t), "done": d} for t, d in prog], "est_min": 40, "actual_min": 150}
            else:
                prog = [(0, 0), (20, 5), (60, 5), (80, 5), (100, 5), (120, 9)]
                outcomes[sid] = {"progress": [{"ts": at(t), "done": d} for t, d in prog], "est_min": 120, "actual_min": 125}
        rc, lab, err = cli("label", stdin=json.dumps({"records": records, "outcomes": outcomes}))
        self.assertEqual(rc, 0, err)
        self.assertEqual(lab["unlabeled"], [])
        rc, cal, err = cli("calibrate", stdin=json.dumps(lab))  # the label output itself is valid calibrate input
        self.assertEqual(rc, 0, err)
        ch = [c for c in cal["changes"] if c["task_type"] == "dev" and c["metric"] == "idle_min"]
        self.assertEqual(len(ch), 1)
        self.assertEqual((ch[0]["before"], ch[0]["after"], ch[0]["fp"], ch[0]["effective"]), (40.0, 48.0, 4, 2))

    def test_misses_tighten_duration(self):
        # 3 effective duration triggers + 2 rule-detected misses on patrol -> miss rate 40% -> tighten 2.0 -> 1.6
        records, outcomes = [], {}
        for i in range(3):
            sid = "t%d" % i
            records.append(rec("duration_ratio", task_id=sid))
            outcomes[sid] = {"action_taken": "resplit", "expected_saving_min": 60, "actual_saving_min": 50,
                             "est_min": 40, "actual_min": 90}
        outcomes["m1"] = {"est_min": 40, "actual_min": 100, "task_type": "patrol"}
        outcomes["m2"] = {"est_min": 30, "actual_min": 70, "task_type": "patrol"}
        rc, lab, err = cli("label", stdin=json.dumps({"records": records, "outcomes": outcomes}))
        self.assertEqual(rc, 0, err)
        self.assertEqual(len(lab["missed"]), 2)
        rc, cal, err = cli("calibrate", stdin=json.dumps({"history": lab["records"] + lab["missed"]}))
        self.assertEqual(rc, 0, err)
        ch = {(c["task_type"], c["metric"]): c for c in cal["changes"]}
        self.assertEqual((ch[("patrol", "duration_ratio")]["before"], ch[("patrol", "duration_ratio")]["after"]),
                         (2.0, 1.6))
        self.assertEqual(ch[("patrol", "duration_ratio")]["missed"], 2)

    def test_bad_stdin(self):
        rc, _, err = cli("label", stdin="[1]")
        self.assertEqual(rc, 2)
        self.assertIn("records", err)


if __name__ == "__main__":
    unittest.main()

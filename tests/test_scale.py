import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, "skills", "hq", "scripts", "scale.py")
METRICS = os.path.join(ROOT, "skills", "hq", "scripts", "metrics.py")

spec = importlib.util.spec_from_file_location("scale", SCRIPT)
scale = importlib.util.module_from_spec(spec)
spec.loader.exec_module(scale)

T0 = datetime(2026, 11, 27, 10, 0, tzinfo=timezone.utc)


def cli(*args, stdin=None):
    p = subprocess.run([sys.executable, SCRIPT, *args], input=stdin, capture_output=True, text=True)
    return p.returncode, (json.loads(p.stdout) if p.stdout.strip() else None), p.stderr


def write(path, text):
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


def read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def at(minutes):
    return (T0 + timedelta(minutes=minutes)).strftime("%Y-%m-%dT%H:%M:%SZ")


class ShardCount(unittest.TestCase):
    def test_example_600_units(self):
        # 600 pages x 1.5 min, target 40, limit 20 -> 16 shards (4 slots kept for re-splits), not 4 modules
        p = scale.shard_plan(600, 1.5, overhead_min=8, target_min=40, limit=20)
        self.assertEqual(p["shards"], 16)
        self.assertEqual(p["reserved_slots"], 4)
        self.assertAlmostEqual(p["shard_min"], 900 / 16 + 8, places=1)
        self.assertLess(p["batch_eta_min"], 70)  # about an hour instead of 2.5-4 h

    def test_by_workload_when_slots_suffice(self):
        p = scale.shard_plan(100, 2, overhead_min=8, target_min=40, limit=20)
        self.assertEqual(p["shards"], 5)  # ceil(200/40)

    def test_small_task_is_one_shard(self):
        self.assertEqual(scale.shard_plan(4, 3, limit=20)["shards"], 1)
        self.assertEqual(scale.shard_plan(1, 100, limit=20)["shards"], 1)

    def test_never_more_shards_than_units(self):
        self.assertEqual(scale.shard_plan(3, 60, overhead_min=1, limit=20)["shards"], 3)

    def test_overhead_ratio_reduces_shards(self):
        # 40 units x 1 min, target 10 -> 4 shards of 10+8 min: overhead 44% > 30% -> fewer shards
        p = scale.shard_plan(40, 1, overhead_min=8, target_min=10, limit=20)
        self.assertLess(p["shards"], 4)
        self.assertLessEqual(p["overhead_ratio"], 0.3)

    def test_low_limit_keeps_all_slots(self):
        self.assertEqual(scale.shard_plan(600, 1.5, limit=4)["usable_slots"], 4)

    def test_units_file_split_is_even_and_contiguous(self):
        with tempfile.TemporaryDirectory() as d:
            f = os.path.join(d, "units.txt")
            write(f, "\n".join("page-%03d" % i for i in range(600)))
            rc, o, _ = cli("shards", "--units-file", f, "--unit-min", "1.5", "--limit", "20")
            self.assertEqual(rc, 0)
            sizes = [len(x) for x in o["assignment"]]
            self.assertEqual(len(sizes), 16)
            self.assertLessEqual(max(sizes) - min(sizes), 1)
            self.assertEqual(o["assignment"][0][0], "page-000")
            self.assertEqual([u for s in o["assignment"] for u in s], ["page-%03d" % i for i in range(600)])


class Straggler(unittest.TestCase):
    def test_resplit_when_far_behind(self):
        r = scale.straggler_check({"id": "s1", "elapsed_min": 90, "est_min": 40, "done": 20, "total": 150},
                                  target_min=40, overhead_min=8, free_slots=3)
        self.assertEqual(r["action"], "resplit")
        self.assertLessEqual(r["new_sessions"], 3)
        self.assertLess(r["eta_after_min"], r["remaining_min"])
        self.assertEqual(r["extra_overhead_min"], r["new_sessions"] * 8)

    def test_near_done_is_not_split(self):
        # projected 2.7x estimate, but only ~20 min left (< 2 x target)
        r = scale.straggler_check({"id": "s2", "elapsed_min": 90, "est_min": 40, "done": 120, "total": 150},
                                  free_slots=3)
        self.assertEqual((r["action"], r["reason"]), ("none", "near_done"))

    def test_on_track(self):
        r = scale.straggler_check({"id": "s3", "elapsed_min": 30, "est_min": 40, "done": 20, "total": 30},
                                  free_slots=3)
        self.assertEqual(r["reason"], "on_track")

    def test_boundary_exactly_two_targets_left_not_split(self):
        # rate 1 unit/min after overhead; remaining 80 units = 80 min = exactly 2 x target -> near_done
        r = scale.straggler_check({"id": "b", "elapsed_min": 108, "est_min": 40, "done": 100, "total": 180},
                                  target_min=40, overhead_min=8, free_slots=2)
        self.assertEqual(r["reason"], "near_done")
        r = scale.straggler_check({"id": "b", "elapsed_min": 108, "est_min": 40, "done": 100, "total": 181},
                                  target_min=40, overhead_min=8, free_slots=2)
        self.assertEqual(r["action"], "resplit")

    def test_no_free_slot_only_reports(self):
        r = scale.straggler_check({"id": "s1", "elapsed_min": 90, "est_min": 40, "done": 20, "total": 150}, free_slots=0)
        self.assertEqual(r["action"], "report")

    def test_cli_respects_slot_budget(self):
        shards = [{"id": "a", "elapsed_min": 90, "est_min": 40, "done": 20, "total": 150},
                  {"id": "b", "elapsed_min": 90, "est_min": 40, "done": 20, "total": 150}]
        rc, o, _ = cli("straggler", "--free-slots", "2", stdin=json.dumps(shards))
        self.assertEqual(sum(s.get("new_sessions", 0) for s in o["shards"]), 2)
        self.assertEqual(o["free_slots_left"], 0)

    def test_progress_line(self):
        text = "x\nHQ-PROGRESS done=3 total=40\n...\nHQ-PROGRESS done=12 total=40 rework=1\n"
        self.assertEqual(scale.parse_progress(text), {"done": 12, "total": 40, "rework": 1})
        self.assertIsNone(scale.parse_progress("no progress here"))


class Delivery(unittest.TestCase):
    def test_mention_in_intermediate_commit_is_not_delivery(self):
        body = "[hq/s3] 修复排序\n\n交付段待补记\nSTATUS: DONE\nVERIFY: 待补\n"
        self.assertFalse(scale.check_delivery(body)["delivered"])
        self.assertFalse(scale.check_delivery("本次交付了一半，交付说明稍后补")["delivered"])

    def test_heading_with_verify(self):
        body = "[hq/s3] done\n\n## 交付\nSTATUS: DONE\nBRANCH: hq/s3 @ abc\nVERIFY: vitest related 41 passed\n"
        r = scale.check_delivery(body)
        self.assertTrue(r["delivered"])

    def test_heading_without_verify_result(self):
        for v in ("VERIFY: none", "VERIFY: 待补", "VERIFY:", ""):
            body = "## 交付\nSTATUS: DONE\n%s\n" % v
            self.assertFalse(scale.check_delivery(body)["delivered"], v)

    def test_heading_but_partial(self):
        self.assertFalse(scale.check_delivery("## 交付\nSTATUS: PARTIAL\nVERIFY: 3 passed\n")["delivered"])

    def test_verify_outside_section_does_not_count(self):
        body = "## 交付\nSTATUS: DONE\n## 其他\nVERIFY: 3 passed\n"
        self.assertFalse(scale.check_delivery(body)["delivered"])

    def test_done_file_and_exit_codes(self):
        with tempfile.TemporaryDirectory() as d:
            f = os.path.join(d, "done.json")
            write(f, json.dumps({"status": "DONE", "verify": "12 passed"}))
            self.assertEqual(cli("delivered", "--done-file", f)[0], 0)
            write(f, json.dumps({"status": "DONE", "verify": ""}))
            self.assertEqual(cli("delivered", "--done-file", f)[0], 1)
        self.assertEqual(cli("delivered", stdin="交付段待补记")[0], 1)


class LayeredVerify(unittest.TestCase):
    def test_related_by_default(self):
        r = scale.test_scope(["apps/web/src/pages/orders/List.tsx", "apps/web/src/pages/orders/List.test.tsx"])
        self.assertEqual(r["scope"], "related")

    def test_shared_foundation_escalates(self):
        for f in ("apps/web/vite.config.ts", "packages/ui/test-utils/render.ts", "package.json", "tsconfig.base.json"):
            self.assertEqual(scale.test_scope([f])["scope"], "full", f)

    def test_project_foundation_globs_and_rule(self):
        self.assertEqual(scale.test_scope(["src/store/global.ts"], ["src/store/**"])["scope"], "full")
        self.assertEqual(scale.test_scope(["src/a.ts"], require_full=True)["reason"], "project_rule")

    def test_full_gate_only_at_checkpoints(self):
        self.assertFalse(scale.full_gate(since_shards=2, since_lines=300, since_files=10)["run_full"])
        self.assertTrue(scale.full_gate(since_shards=4)["run_full"])
        self.assertTrue(scale.full_gate(since_lines=1600)["run_full"])
        self.assertTrue(scale.full_gate(batch_complete=True)["run_full"])
        self.assertTrue(scale.full_gate(before_push=True)["run_full"])
        self.assertTrue(scale.full_gate(ci_checkpoint=True)["run_full"])
        self.assertFalse(scale.full_gate(since_shards=9, every_shards=10, every_lines=0, every_files=0)["run_full"])


class GroupMerge(unittest.TestCase):
    def test_one_group_per_checkin(self):
        delivered = [{"id": "s1", "files": ["a/x.ts"]}, {"id": "s2", "files": ["b/y.ts"]},
                     {"id": "s3", "files": ["c/z.ts"]}]
        r = scale.merge_group(delivered)
        self.assertEqual(r["group"], ["s1", "s2", "s3"])
        self.assertEqual(r["verify_files"], ["a/x.ts", "b/y.ts", "c/z.ts"])

    def test_overlap_owned_file_and_deps_defer(self):
        delivered = [{"id": "s1", "files": ["a/x.ts", "shared/sort.ts"]},
                     {"id": "s2", "files": ["shared/sort.ts", "b/y.ts"]},
                     {"id": "s3", "files": ["a/x.ts"]},
                     {"id": "s4", "files": ["d/w.ts"], "depends_on": ["s9"]}]
        r = scale.merge_group(delivered, pending=[{"id": "s9", "eta_min": 30}], owners={"shared/sort.ts": "fix"})
        reasons = {d["id"]: d["reason"] for d in r["deferred"]}
        self.assertEqual(reasons["s1"], "touches_owned_file")
        self.assertEqual(reasons["s2"], "touches_owned_file")
        self.assertEqual(reasons["s4"], "depends_on:s9")
        self.assertEqual(r["group"], ["s3"])

    def test_dependency_order_inside_group(self):
        r = scale.merge_group([{"id": "b", "files": ["b"], "depends_on": ["a"]}, {"id": "a", "files": ["a"]}])
        self.assertEqual(r["group"], ["a", "b"])

    def test_short_wait_for_almost_done_shards(self):
        r = scale.merge_group([{"id": "s1", "files": ["a"]}],
                              pending=[{"id": "s2", "eta_min": 4}, {"id": "s3", "eta_min": 25}], wait_max_min=10)
        self.assertEqual((r["wait_min"], r["wait_for"]), (4, ["s2"]))

    def test_locate_only_culprit(self):
        group = [{"id": "s1", "files": ["web/orders/List.tsx"]}, {"id": "s2", "files": ["web/users/Form.tsx"]},
                 {"id": "s3", "files": ["web/billing/Pay.tsx"]}]
        r = scale.locate(group, ["web/users/Form.test.tsx"])
        self.assertEqual(r["culprits"], ["s2"])
        self.assertEqual(r["clean"], ["s1", "s3"])
        self.assertEqual(r["next"]["action"], "fix_or_revert_culprits")

    def test_locate_unknown_bisects(self):
        group = [{"id": "s1", "files": ["a/x.ts"]}, {"id": "s2", "files": ["b/y.ts"]}]
        r = scale.locate(group, ["e2e/flow.spec.ts"])
        self.assertEqual(r["culprits"], [])
        self.assertEqual(r["next"]["action"], "bisect")


def snap(shards, **kw):
    d = {"run_id": "r1", "batch_id": "b1", "shards": shards}
    d.update(kw)
    return d


class Monitor(unittest.TestCase):
    def step(self, state, s, minute, cfg=None):
        return scale.monitor_step(state, s, cfg, T0 + timedelta(minutes=minute))

    def test_two_consecutive_breaches_trigger(self):
        sh = {"id": "s1", "created_at": at(0), "est_min": 40, "last_event_at": at(85), "done": 10}
        st, r = self.step({}, snap([sh]), 90)          # 2.25x once -> not yet
        self.assertEqual(r["actions"], [])
        st, r = self.step(st, snap([dict(sh, last_event_at=at(100), done=12)]), 105)
        self.assertEqual([a["metric"] for a in r["actions"]], ["duration_ratio"])
        self.assertEqual(r["actions"][0]["action"], "straggler_check")

    def test_one_breach_then_recovery_does_not_trigger(self):
        sh = {"id": "s1", "created_at": at(0), "est_min": 40, "last_event_at": at(85), "done": 10}
        st, _ = self.step({}, snap([sh]), 90)
        st, r = self.step(st, snap([dict(sh, est_min=100)]), 95)   # back under
        st, r = self.step(st, snap([dict(sh, est_min=40)]), 100)   # first breach again
        self.assertEqual(r["actions"], [])

    def test_severe_triggers_immediately(self):
        sh = {"id": "s1", "created_at": at(0), "est_min": 60, "last_event_at": at(5), "cost_usd": 10, "budget_usd": 4}
        st, r = self.step({}, snap([sh]), 10)
        acts = {a["metric"]: a for a in r["actions"]}
        self.assertEqual(acts["cost_ratio"]["action"], "pause_and_ask_user")
        self.assertEqual(acts["cost_ratio"]["severity"], "severe")
        self.assertEqual(len(r["analyses"]), 1)   # severe -> immediate analysis

    def test_idle_uses_event_stream_not_list_time(self):
        # session list says updated 2 h ago, but the event stream had an event 5 min ago: not idle
        sh = {"id": "s1", "created_at": at(0), "est_min": 300, "list_updated_at": at(-120),
              "last_event_at": at(115), "done": 5}
        st, _ = self.step({}, snap([sh]), 120)
        st, r = self.step(st, snap([sh]), 125)
        self.assertEqual(r["actions"], [])
        # real idle: last event 50 min ago and progress unchanged twice
        sh2 = dict(sh, last_event_at=at(70))
        st, _ = self.step({}, snap([sh2]), 120)
        st, r = self.step(st, snap([sh2]), 125)
        self.assertEqual([a["action"] for a in r["actions"]], ["message_reminder"])

    def test_idle_with_progress_change_is_not_idle(self):
        sh = {"id": "s1", "created_at": at(0), "est_min": 300, "last_event_at": at(0), "done": 5}
        st, _ = self.step({}, snap([sh]), 60)
        st, r = self.step(st, snap([dict(sh, done=9)]), 70)   # long background task, but progress moved
        self.assertEqual(r["actions"], [])

    def test_batch_metrics(self):
        st, r = self.step({}, snap([], batch={"failure_rate": 0.6}), 10)
        self.assertEqual(r["actions"][0]["action"], "locate_failing_shard")
        self.assertEqual(r["actions"][0]["severity"], "severe")

    def test_records_for_runs_jsonl(self):
        sh = {"id": "s1", "created_at": at(0), "est_min": 60, "cost_usd": 10, "budget_usd": 4}
        _, r = self.step({}, snap([sh]), 10)
        rec = r["records"][0]
        for k in ("type", "ts", "metric", "value", "threshold", "level", "rate_limited", "analysis_cost_usd", "key"):
            self.assertIn(k, rec)
        self.assertEqual(rec["type"], "monitor")


class RateLimit(unittest.TestCase):
    def severe(self, sid, cause="api_loop"):
        return {"id": sid, "created_at": at(0), "est_min": 60, "cost_usd": 10, "budget_usd": 4,
                "cause": {"cost_ratio": cause}}

    def test_same_key_once_per_cooldown(self):
        st, r = scale.monitor_step({}, snap([self.severe("s1")]), None, T0)
        self.assertEqual(len(r["analyses"]), 1)
        st, r = scale.monitor_step(st, snap([self.severe("s2")], batch_id="b2"), None, T0 + timedelta(minutes=30))
        self.assertEqual(r["analyses"], [])
        self.assertEqual(r["rate_limited"][0]["reason"], "cooldown")
        self.assertTrue(r["records"][0]["rate_limited"])
        self.assertEqual(st["pending"]["cost_ratio:api_loop"]["count"], 1)
        # after the cooldown the next analysis carries the accumulated count
        st, r = scale.monitor_step(st, snap([self.severe("s3")], batch_id="b3"), None, T0 + timedelta(minutes=200))
        self.assertEqual(r["analyses"][0]["counts"]["cost_ratio:api_loop"], 2)

    def test_per_batch_and_per_day_limits(self):
        st, r = scale.monitor_step({}, snap([self.severe("s1", "a")]), None, T0)
        self.assertEqual(len(r["analyses"]), 1)
        st, r = scale.monitor_step(st, snap([self.severe("s2", "b")]), None, T0 + timedelta(minutes=5))
        self.assertEqual(r["analyses"], [])                       # 1 per batch
        self.assertEqual(r["rate_limited"][0]["reason"], "global_limit")
        for i, b in enumerate(("b2", "b3")):
            st, r = scale.monitor_step(st, snap([self.severe("x%d" % i, "c%d" % i)], batch_id=b), None,
                                       T0 + timedelta(minutes=10 + i))
            self.assertEqual(len(r["analyses"]), 1)
        st, r = scale.monitor_step(st, snap([self.severe("y", "d")], batch_id="b4"), None, T0 + timedelta(minutes=20))
        self.assertEqual(r["analyses"], [])                       # 3 per day
        self.assertEqual(r["rate_limited"][0]["reason"], "global_limit")

    def test_non_severe_merged_at_batch_end(self):
        def dur(sid):  # non-severe repeated cause across shards
            return {"id": sid, "created_at": at(0), "est_min": 40, "last_event_at": at(99), "done": 1,
                    "cause": {"duration_ratio": "underestimated"}}
        st = {}
        for m in (90, 100):
            st, r = scale.monitor_step(st, snap([dur("s1"), dur("s2")]), None, T0 + timedelta(minutes=m))
        self.assertEqual(len(r["actions"]), 2)
        self.assertEqual(r["analyses"], [])                       # deferred, not analysed yet
        st, r = scale.monitor_step(st, snap([], batch_done=True), None, T0 + timedelta(minutes=120))
        self.assertEqual(len(r["analyses"]), 1)
        self.assertEqual(r["analyses"][0]["reason"], "batch_end_merged")
        self.assertEqual(r["analyses"][0]["counts"]["duration_ratio:underestimated"], 2)

    def test_single_non_severe_stays_level_one(self):
        sh = {"id": "s1", "created_at": at(0), "est_min": 40, "last_event_at": at(99), "done": 1}
        st = {}
        for m in (90, 100):
            st, r = scale.monitor_step(st, snap([sh]), None, T0 + timedelta(minutes=m))
        st, r = scale.monitor_step(st, snap([], batch_done=True), None, T0 + timedelta(minutes=120))
        self.assertEqual(r["analyses"], [])

    def test_heavy_ops_postpone_severe(self):
        st, r = scale.monitor_step({}, snap([self.severe("s1")], heavy_ops=True), None, T0)
        self.assertEqual(r["analyses"], [])
        st, r = scale.monitor_step(st, snap([]), None, T0 + timedelta(minutes=10))
        self.assertEqual(r["analyses"][0]["reason"], "postponed_severe")

    def test_cli_persists_state(self):
        with tempfile.TemporaryDirectory() as d:
            f = os.path.join(d, "state.json")
            sh = {"id": "s1", "created_at": at(0), "est_min": 40, "last_event_at": at(85), "done": 1}
            cli("monitor", "--state", f, "--now", at(90), stdin=json.dumps(snap([sh])))
            rc, o, _ = cli("monitor", "--state", f, "--now", at(100), stdin=json.dumps(snap([sh])))
            self.assertEqual(rc, 0)
            self.assertEqual(o["actions"][0]["metric"], "duration_ratio")


def hist(tt, metric, eff, fp, miss=0):
    return ([{"task_type": tt, "metric": metric, "label": "effective"}] * eff
            + [{"task_type": tt, "metric": metric, "label": "false_positive"}] * fp
            + [{"task_type": tt, "metric": metric, "event": "missed"}] * miss)


class Calibrate(unittest.TestCase):
    def val(self, r, tt, metric):
        return r["thresholds"].get(tt, {}).get(metric, r["thresholds"]["*"][metric])

    def test_loosen_on_false_positives_with_step_limit(self):
        r = scale.calibrate({"*": {"idle_min": 40}}, hist("dev", "idle_min", 2, 6))
        self.assertEqual(self.val(r, "*", "idle_min"), 48)   # +20% max
        self.assertEqual(self.val(r, "dev", "idle_min"), 48)

    def test_tighten_on_misses(self):
        r = scale.calibrate({"*": {"rework": 3}}, hist("dev", "rework", 3, 0, 3))
        self.assertEqual(self.val(r, "*", "rework"), 2)

    def test_bounds(self):
        r = scale.calibrate({"*": {"duration_ratio": 3.9}}, hist("dev", "duration_ratio", 1, 9))
        self.assertEqual(self.val(r, "*", "duration_ratio"), 4.0)
        r = scale.calibrate({"*": {"idle_min": 16}}, hist("dev", "idle_min", 5, 0, 5))
        self.assertEqual(self.val(r, "*", "idle_min"), 15)

    def test_few_samples_keep_default(self):
        r = scale.calibrate({}, hist("docs", "idle_min", 1, 3))
        self.assertEqual(self.val(r, "docs", "idle_min"), 40)
        self.assertEqual(r["changes"], [])

    def test_per_type_differs_from_global(self):
        h = hist("patrol", "idle_min", 1, 6) + hist("dev", "idle_min", 6, 0)
        r = scale.calibrate({}, h, task_types=["patrol", "dev"])
        self.assertEqual(self.val(r, "patrol", "idle_min"), 48)
        self.assertEqual(self.val(r, "dev", "idle_min"), 40)

    def test_user_value_never_overwritten(self):
        r = scale.calibrate({"*": {"idle_min": 40}}, hist("dev", "idle_min", 0, 10), user={"*": {"idle_min": 25}})
        self.assertEqual(self.val(r, "dev", "idle_min"), 25)
        self.assertEqual(self.val(r, "*", "idle_min"), 25)

    def test_duration_from_p90(self):
        r = scale.calibrate({}, [], ratios={"patrol": [1.0, 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 1.8, 3.0]},
                            task_types=["patrol"])
        v = self.val(r, "patrol", "duration_ratio")
        self.assertGreater(v, 1.6)       # moved toward P90 = 1.92 but at most 20% from 2.0
        self.assertLessEqual(v, 2.0)

    def test_playbook_write_user_precedence_and_rollback(self):
        with tempfile.TemporaryDirectory() as d:
            pb = os.path.join(d, "PLAYBOOK.md")
            write(pb, "# PB\n\n## 授权\n\n```yaml\nopen_pr: ask\nmonitor:\n  thresholds:\n"
                                "    rework: 3              # 手动\n    \"patrol\": {idle_min: 60}\n```\n")
            data = {"history": hist("dev", "idle_min", 1, 9)}
            rc, o, _ = cli("calibrate", "--playbook", pb, "--write", stdin=json.dumps(data))
            self.assertEqual((rc, o["version"]), (0, 1))
            rc, e, _ = cli("thresholds", "--playbook", pb)
            self.assertEqual(e["thresholds"]["*"]["idle_min"], 48)
            self.assertEqual(e["thresholds"]["*"]["rework"], 3)          # user
            self.assertEqual(e["thresholds"]["patrol"]["idle_min"], 60)  # user, per type
            cli("calibrate", "--playbook", pb, "--write", stdin=json.dumps(data))
            rc, e, _ = cli("thresholds", "--playbook", pb)
            self.assertAlmostEqual(e["thresholds"]["*"]["idle_min"], 57.6)
            rc, rb, _ = cli("thresholds", "--playbook", pb, "--rollback")
            self.assertEqual((rc, rb["to"]), (0, 1))
            rc, e, _ = cli("thresholds", "--playbook", pb)
            self.assertEqual(e["thresholds"]["*"]["idle_min"], 48)
            self.assertIn("open_pr: ask", read(pb))


def split_snap(shards, **kw):
    d = {"run_id": "r1", "batch_id": "b1", "target_min": 40, "overhead_min": 8, "concurrency_limit": 20,
         "shards": shards}
    d.update(kw)
    return d


def sh(sid, elapsed, done, total, unit_est=None, **kw):
    d = {"id": sid, "elapsed_min": elapsed, "est_min": 60, "done": done, "total": total,
         "last_event_at": at(elapsed - 1)}
    if unit_est is not None:
        d["unit_min_est"] = unit_est
    d.update(kw)
    return d


class SplitHealth(unittest.TestCase):
    def run2(self, snaps, state=None):
        st, r = state or {}, None
        for i, s in enumerate(snaps):
            st, r = scale.monitor_step(st, s, None, T0 + timedelta(minutes=10 * i))
        return st, r

    def by_metric(self, r):
        return {a["metric"]: a for a in r["actions"]}

    def test_unit_time_underestimated_across_shards_replans(self):
        # planned 0.5 min/unit, measured 1.5 min/unit on all 4 shards at ~20%
        s = split_snap([sh("s%d" % i, 38, 20, 100, unit_est=0.5) for i in range(4)])
        vals, det = scale.split_health(s, T0)
        self.assertAlmostEqual(vals["split_unit_error"], 2.0)
        _, r = self.run2([s])   # >= 1.5 is severe: fires at once
        a = self.by_metric(r)["split_unit_error"]
        self.assertEqual(a["action"], "replan_remaining")
        self.assertEqual(a["replan"]["remaining_units"], 320)
        self.assertEqual(a["replan"]["measured_unit_min"], 1.5)
        self.assertGreater(a["replan"]["new_sessions"], 0)
        self.assertEqual(r["records"][0]["key"], "split:unit_time")

    def test_unit_time_needs_early_progress_and_agreement(self):
        early = split_snap([sh("s%d" % i, 9.5, 1, 100, unit_est=0.5) for i in range(4)])  # 1% done
        self.assertNotIn("split_unit_error", scale.split_health(early, T0)[0])
        mixed = split_snap([sh("a", 38, 20, 100, unit_est=0.5), sh("b", 38, 20, 100, unit_est=3.0),
                            sh("c", 38, 20, 100, unit_est=0.5), sh("d", 38, 20, 100, unit_est=3.0)])
        self.assertNotIn("split_unit_error", scale.split_health(mixed, T0)[0])
        two = split_snap([sh("a", 38, 20, 100, unit_est=0.5), sh("b", 38, 20, 100, unit_est=0.5)])
        self.assertNotIn("split_unit_error", scale.split_health(two, T0)[0])

    def test_moderate_unit_error_needs_two_checkins(self):
        s = split_snap([sh("s%d" % i, 38, 20, 100, unit_est=0.9) for i in range(4)])  # 1.5/0.9-1 = 0.67
        st, r = self.run2([s])
        self.assertNotIn("split_unit_error", self.by_metric(r))
        st, r = self.run2([s], st)
        self.assertIn("split_unit_error", self.by_metric(r))

    def test_uneven_projection_before_shards_finish(self):
        shards = [sh("a", 38, 30, 100), sh("b", 38, 30, 100), sh("c", 38, 30, 100), sh("d", 38, 6, 100)]
        vals, det = scale.split_health(split_snap(shards), T0)
        self.assertGreater(vals["split_uneven"], 2)
        _, r = self.run2([split_snap(shards)] * 2)
        self.assertEqual(self.by_metric(r)["split_uneven"]["action"], "replan_remaining")

    def test_underused_slots(self):
        # 2 shards running, 600 units left at 1 min/unit with limit 20: could use 15
        shards = [sh("a", 108, 100, 400), sh("b", 108, 100, 400)]
        vals, det = scale.split_health(split_snap(shards), T0)
        self.assertLess(vals["split_underused"], 0.5)
        self.assertEqual(det["split_underused"]["could_use"], 15)
        # nearly done work does not count as under-used
        near = [sh("a", 108, 390, 400), sh("b", 108, 390, 400)]
        self.assertNotIn("split_underused", scale.split_health(split_snap(near), T0)[0])

    def test_boundary_signals(self):
        shards = [sh("a", 30, 5, 50, boundary={"overlap": True}), sh("b", 30, 5, 50, boundary={"shared_fixes": 2}),
                  sh("c", 30, 5, 50, boundary={"out_of_owns": ["tools/overlay-walk.mjs"]}), sh("d", 30, 5, 50)]
        _, r = self.run2([split_snap(shards)] * 2)
        a = self.by_metric(r)["split_boundary"]
        self.assertEqual((a["value"], a["action"]), (3, "review_boundaries"))
        self.assertEqual(a["detail"]["shards"], ["a", "b", "c"])
        one = [sh("a", 30, 5, 50, boundary={"overlap": True}), sh("b", 30, 5, 50)]
        _, r = self.run2([split_snap(one)] * 2)
        self.assertNotIn("split_boundary", self.by_metric(r))

    def test_each_split_check_once_per_batch(self):
        s = split_snap([sh("s%d" % i, 38, 20, 100, unit_est=0.5) for i in range(4)])
        st, r = self.run2([s])
        self.assertIn("split_unit_error", self.by_metric(r))
        st, r = self.run2([s, s, s], st)
        self.assertNotIn("split_unit_error", self.by_metric(r))
        st, r = self.run2([dict(s, batch_id="b2")], st)   # next batch: armed again
        self.assertIn("split_unit_error", self.by_metric(r))

    def test_single_shard_has_no_split_checks(self):
        self.assertEqual(scale.split_health(split_snap([sh("a", 38, 20, 100, unit_est=0.5)]), T0), ({}, {}))

    def test_calibration_direction_for_lower_is_worse(self):
        r = scale.calibrate({"*": {"split_underused": 0.5}}, hist("patrol", "split_underused", 2, 6))
        self.assertEqual(r["thresholds"]["*"]["split_underused"], 0.4)     # loosen = lower
        r = scale.calibrate({"*": {"split_underused": 0.5}}, hist("patrol", "split_underused", 3, 0, 3))
        self.assertEqual(r["thresholds"]["*"]["split_underused"], 0.6)     # tighten = higher

    def test_integer_threshold_moves_by_one(self):
        r = scale.calibrate({"*": {"rework": 2}}, hist("dev", "rework", 2, 6))
        self.assertEqual(r["thresholds"]["*"]["rework"], 3)
        r = scale.calibrate({"*": {"split_boundary": 2}}, hist("dev", "split_boundary", 3, 0, 3))
        self.assertEqual(r["thresholds"]["*"]["split_boundary"], 1)


class RetroMetrics(unittest.TestCase):
    def report(self, lines):
        with tempfile.TemporaryDirectory() as d:
            f = os.path.join(d, "r.jsonl")
            write(f, "\n".join(json.dumps(x) for x in lines) + "\n")
            p = subprocess.run([sys.executable, METRICS, d, "--format", "json"], capture_output=True, text=True)
            self.assertEqual(p.returncode, 0, p.stderr)
            md = subprocess.run([sys.executable, METRICS, d], capture_output=True, text=True)
            self.assertEqual(md.returncode, 0, md.stderr)
            anon = subprocess.run([sys.executable, METRICS, d, "--export-anon", "--raw"], capture_output=True, text=True)
            self.assertEqual(anon.returncode, 0, anon.stderr)
            return json.loads(p.stdout), md.stdout, json.loads(anon.stdout)

    def test_scale_out_metrics(self):
        acts = [150, 160, 240, 150]
        recs = [{"type": "run", "run_id": "r1", "wall_min": 245, "tasks": 4, "max_concurrency": 4,
                 "concurrency_limit": 20, "target_shard_min": 40}]
        for i, a in enumerate(acts):
            recs.append({"type": "task", "run_id": "r1", "task_id": "s%d" % i, "shard_group": "patrol",
                         "units_planned": 150, "units_actual": 150, "unit_min_est": 1.0, "overhead_min": 8,
                         "actual_min": a, "test_scope": "full", "test_min": 12, "resplit": False})
        recs += [{"type": "merge", "run_id": "r1", "group_seq": 1, "shards": ["s0", "s1"], "verify_runs": 1,
                  "full_test": True, "full_test_min": 12},
                 {"type": "merge", "run_id": "r1", "group_seq": 2, "shards": ["s2", "s3"], "verify_runs": 1,
                  "full_test": True, "full_test_min": 11},
                 {"type": "monitor", "run_id": "r1", "metric": "duration_ratio", "level": 1, "label": "effective",
                  "rate_limited": False, "analysis_cost_usd": None},
                 {"type": "monitor", "run_id": "r1", "metric": "idle_min", "level": 2, "label": "false_positive",
                  "rate_limited": True, "analysis_cost_usd": 0.2},
                 {"type": "monitor", "run_id": "r1", "event": "missed", "metric": "idle_min"}]
        rep, md, anon = self.report(recs)
        x = rep["scale_out"][0]
        self.assertAlmostEqual(x["parallel_efficiency"], sum(acts) / (4 * 240))
        self.assertAlmostEqual(x["straggler_ratio"], 240 / 155)
        self.assertAlmostEqual(x["concurrency_utilization"], 0.2)
        self.assertEqual(x["full_tests"], 6)
        self.assertEqual(x["full_test_min"], 12 * 4 + 23)
        self.assertEqual(x["shards_per_full_test"], 2)
        self.assertEqual((x["merge_groups"], x["shards_per_group"], x["verify_runs"]), (2, 2, 2))
        self.assertEqual((x["monitor_triggers"], x["monitor_level1"], x["monitor_level2"]), (2, 1, 1))
        self.assertEqual((x["monitor_rate_limited"], x["monitor_missed"]), (1, 1))
        self.assertAlmostEqual(x["analysis_cost_usd"], 0.2)
        self.assertEqual(x["monitor_by_metric"]["idle_min"]["missed"], 1)
        self.assertEqual(x["suggest_shards"], 15)  # measured ~0.98 min/unit -> ceil(588/40)
        msgs = " ".join(s["message"] for s in rep["signals"])
        self.assertIn("同类任务下次切成 15 片", msgs)
        self.assertIn("全量测试改成每 4 片合入后跑一次", msgs)
        self.assertIn("4b. 分片", md)
        self.assertEqual(anon["summary"]["scale_out"][0]["merge_groups"], 2)
        kinds = {r["type"] for r in anon["records"]}
        self.assertEqual(kinds, {"run", "task", "merge", "monitor"})
        self.assertNotIn("s0", json.dumps(anon["records"]))

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


if __name__ == "__main__":
    unittest.main()

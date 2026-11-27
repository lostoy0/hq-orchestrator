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
        # 600 pages x 1.5 min, target 40, limit 20, reserve 0: ceil(900/40)=23 > 20 -> 20 shards, not 4 modules
        p = scale.shard_plan(600, 1.5, overhead_min=8, target_min=40, limit=20, reserve=0)
        self.assertEqual(p["shards"], 20)
        self.assertGreaterEqual(p["shards"], 16)
        self.assertLessEqual(p["shards"], 20)
        self.assertEqual((p["usable_slots"], p["reserve"]), (20, 0))
        self.assertAlmostEqual(p["shard_min"], 900 / 20 + 8, places=1)
        self.assertLess(p["batch_eta_min"], 70)  # about an hour instead of 2.5-4 h
        # 53 min > 1.25 x 40: still over target, and the limit needed is reserve + min(units, by_target)
        self.assertTrue(p["over_target"])
        self.assertEqual(p["needed_limit"], 23)

    def test_low_limit_is_over_target_and_says_needed_limit(self):
        p = scale.shard_plan(600, 1.5, overhead_min=8, target_min=40, limit=4)
        self.assertEqual(p["shards"], 4)
        self.assertTrue(p["over_target"])
        self.assertEqual(p["needed_limit"], 23)
        self.assertGreater(p["needed_limit"], 4)
        self.assertIn("并发上限 4 不够", p["why"])
        self.assertIn("23", p["why"])
        self.assertIn("remote_concurrency", p["why"])
        p = scale.shard_plan(600, 1.5, limit=4, reserve=2)
        self.assertEqual((p["usable_slots"], p["shards"], p["needed_limit"]), (2, 2, 25))

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
            self.assertEqual(len(sizes), 20)
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


# ---- regression tests for the independent review (fix-scale.md) ----------------------------

class ShardFormulaEdges(unittest.TestCase):
    def test_major1_exact_multiple_of_target_is_not_one_more_shard(self):
        self.assertEqual(scale.shard_plan(400, 1.1, 0, 44, limit=100)["shards"], 10)
        self.assertEqual(scale.shard_plan(7, 0.1, 0, 0.7, limit=100)["shards"], 1)

    def test_formula_matches_spec(self):
        # n = max(1, min(usable, by_target, units)), then drop shards while overhead ratio > max (+tol)
        for units, um, ov, t, lim, res, ratio in [(600, 1.5, 8, 40, 20, 0, 0.3), (40, 1, 8, 10, 20, 0, 0.3),
                                                  (100, 2, 8, 40, 20, 3, 0.3), (3, 60, 1, 40, 20, 0, 0.3),
                                                  (10, 1, 3, 1, 50, 0, 0.3)]:
            work = units * um
            by_t = max(1, scale.math.ceil(round(work / t, 9)))
            n = max(1, min(max(1, lim - res), by_t, units))
            while n > 1 and ov / (work / n + ov) > ratio + 1e-9:
                n -= 1
            p = scale.shard_plan(units, um, ov, t, limit=lim, reserve=res, max_overhead_ratio=ratio)
            self.assertEqual(p["shards"], n, (units, um))
            self.assertEqual(p["needed_limit"], res + max(1, min(units, by_t)))

    def test_overhead_ratio_exactly_at_limit_keeps_shard(self):
        # 70 units x 1 min, target 7 -> 10 shards of 7 + 3 min: overhead exactly 30%, kept
        p = scale.shard_plan(70, 1, 3, 7, limit=10, max_overhead_ratio=0.3)
        self.assertEqual(p["shards"], 10)
        self.assertAlmostEqual(p["overhead_ratio"], 0.3)

    def test_over_target_at_exactly_125_percent_is_false(self):
        # one unit of 42 min + 8 overhead = 50 == 1.25 x 40 -> not over target
        self.assertFalse(scale.shard_plan(1, 42, 8, 40, limit=5)["over_target"])
        p = scale.shard_plan(1, 100, 8, 40, limit=5)
        self.assertTrue(p["over_target"])
        self.assertNotIn("不够", p["why"])  # more slots would not help a single long unit

    def test_bad_input_raises(self):
        for kw in ({"units": 0}, {"unit_min": float("nan")}, {"target_min": 0}, {"limit": 0}, {"reserve": -1}):
            args = dict(units=10, unit_min=1.0, target_min=40.0, limit=4, reserve=0)
            args.update(kw)
            with self.assertRaises(ValueError, msg=str(kw)):
                scale.shard_plan(args["units"], args["unit_min"], 8, args["target_min"],
                                 limit=args["limit"], reserve=args["reserve"])

    def test_cli_limit_required_and_bad_numbers_exit_2(self):
        self.assertEqual(cli("shards", "--units", "10", "--unit-min", "1")[0], 2)
        for bad in (["--target-min", "0"], ["--unit-min", "nan"], ["--unit-min", "inf"], ["--limit", "0"],
                    ["--reserve", "-1"]):
            args = ["shards", "--units", "10", "--unit-min", "1", "--limit", "4"] + bad
            rc, _, err = cli(*args)
            self.assertEqual(rc, 2, bad)
            self.assertNotIn("Traceback", err)
        rc, o, _ = cli("shards", "--units", "600", "--unit-min", "1.5", "--limit", "4")
        self.assertEqual((rc, o["shards"], o["over_target"], o["needed_limit"]), (0, 4, True, 23))

    def test_units_file_weights_and_mismatch(self):
        with tempfile.TemporaryDirectory() as d:
            f = os.path.join(d, "u.txt")
            write(f, "a\t0\nb\t0\nc\t0\nd\t0\n")
            parts = scale.split_units(scale.read_units_file(f), 2)
            self.assertEqual(parts, [["a", "b"], ["c", "d"]])
            write(f, "a\t-3\nb\tnan\nc\tinf\nd\n")
            parts = scale.split_units(scale.read_units_file(f), 4)
            self.assertEqual(parts, [["a"], ["b"], ["c"], ["d"]])
            write(f, "x\n" * 5)
            rc, _, err = cli("shards", "--units", "7", "--units-file", f, "--unit-min", "1", "--limit", "4")
            self.assertEqual(rc, 2)
            self.assertIn("does not match", err)
            rc, _, err = cli("shards", "--units-file", os.path.join(d, "missing.txt"), "--unit-min", "1", "--limit", "4")
            self.assertEqual(rc, 2)
            self.assertNotIn("Traceback", err)

    def test_split_never_leaves_empty_shards_and_fields_follow(self):
        items = [("big", 100.0)] + [("s%d" % i, 1.0) for i in range(3)]
        parts = scale.split_units(items, 4)
        self.assertEqual(len(parts), 4)
        self.assertTrue(all(parts))
        self.assertEqual([u for p in parts for u in p], [n for n, _ in items])
        with tempfile.TemporaryDirectory() as d:
            f = os.path.join(d, "u.txt")
            write(f, "big\t100\ns0\ns1\ns2\n")
            rc, o, _ = cli("shards", "--units-file", f, "--unit-min", "30", "--limit", "10", "--overhead-min", "0")
            self.assertEqual(rc, 0)
            self.assertEqual(o["shards"], len(o["assignment"]))
            self.assertAlmostEqual(o["units_per_shard"], 4 / o["shards"], places=1)


class StragglerEdges(unittest.TestCase):
    def test_major2_projection_exactly_twice_estimate_is_on_track(self):
        r = scale.straggler_check({"id": "a", "est_min": 21, "elapsed_min": 11.4, "done": 1, "total": 10},
                                  target_min=1, overhead_min=8, free_slots=2)
        self.assertEqual((r["action"], r["reason"]), ("none", "on_track"))

    def test_major2_remaining_exactly_twice_target_is_near_done(self):
        # rate 1/3.4 units per min; 9 units left = 30.6 min; target 15.3 -> exactly 2 x target
        r = scale.straggler_check({"id": "a", "est_min": 5, "elapsed_min": 11.4, "done": 1, "total": 10},
                                  target_min=15.3, overhead_min=8, free_slots=2)
        self.assertEqual(r["reason"], "near_done")

    def test_major3_never_more_pieces_than_remaining_units(self):
        r = scale.straggler_check({"id": "a", "est_min": 30, "elapsed_min": 400, "done": 1, "total": 2},
                                  free_slots=3)
        self.assertNotEqual(r["action"], "resplit")
        self.assertEqual((r["action"], r["reason"]), ("report", "straggler_unsplittable"))
        r = scale.straggler_check({"id": "a", "est_min": 30, "elapsed_min": 400, "done": 1, "total": 4},
                                  free_slots=3)
        self.assertEqual(r["action"], "resplit")
        self.assertLessEqual(r["new_sessions"] + 1, r["remaining_units"])
        diffs = [b - a for a, b in zip(r["split"], r["split"][1:])]
        self.assertTrue(all(d >= 1 for d in diffs), r["split"])
        self.assertEqual(r["split"][-1], 3)
        self.assertEqual(r["ranges"][0][0], 2)
        self.assertEqual(r["ranges"][-1][1], 4)

    def test_split_is_strictly_increasing_for_many_shapes(self):
        for total in range(3, 40):
            for free in range(1, 8):
                r = scale.straggler_check({"id": "x", "est_min": 1, "elapsed_min": 1000, "done": 1, "total": total},
                                          target_min=1, overhead_min=0, free_slots=free)
                if r["action"] == "resplit":
                    sp = r["split"]
                    self.assertTrue(all(b > a for a, b in zip(sp, sp[1:])), (total, free, sp))

    def test_bad_shard_values(self):
        base = {"id": "a", "elapsed_min": 90, "est_min": 40}
        for bad in ({"done": "20", "total": 150}, {"done": 20, "total": "150"}, {"done": True, "total": 150},
                    {"done": 20, "total": True}, {"done": 20, "total": 0}, {"done": -1, "total": 150}):
            r = scale.straggler_check(dict(base, **bad), free_slots=3)
            self.assertEqual(r["action"], "none", bad)
        r = scale.straggler_check({"id": "a", "elapsed_min": -5, "est_min": 40, "done": 2, "total": 10})
        self.assertEqual(r["reason"], "no_progress_data")
        for est in (0, -10, "40"):
            r = scale.straggler_check({"id": "a", "elapsed_min": 90, "est_min": est, "done": 20, "total": 150},
                                      free_slots=1)
            self.assertEqual(r["est_min"], 40.0)
            self.assertTrue(r["est_min_defaulted"])

    def test_cli_bad_shapes_and_now(self):
        for bad in ("[1, 2]", '"str"', '{"shards": [1]}', '{"x": 1}'):
            rc, _, err = cli("straggler", stdin=bad)
            self.assertEqual(rc, 2, bad)
            self.assertNotIn("Traceback", err)
        rc, _, err = cli("straggler", "--now", "yesterday", stdin="[]")
        self.assertEqual(rc, 2)
        self.assertIn("--now", err)
        rc, o, _ = cli("straggler", "--now", at(90), stdin=json.dumps(
            [{"id": "a", "started_at": at(0), "est_min": 40, "done": 20, "total": 150}]))
        self.assertEqual((rc, o["shards"][0]["elapsed_min"]), (0, 90.0))


class Replan(unittest.TestCase):
    def shard(self, i, done, elapsed=58, total=100, unit_est=1.0, **kw):
        d = {"id": "s%d" % i, "elapsed_min": elapsed, "est_min": 108, "done": done, "total": total,
             "unit_min_est": unit_est}
        d.update(kw)
        return d

    def test_unit_time_underestimated_across_shards_replans(self):
        # measured (58-8)/20 = 2.5 min per unit vs 1.0 planned: +150% on all 4 shards
        shards = [self.shard(i, 20) for i in range(4)]
        rp = scale.replan(shards, target_min=40, overhead_min=8, free_slots=6)
        self.assertIsNotNone(rp)
        self.assertAlmostEqual(rp["measured_unit_min"], 2.5)
        self.assertEqual(rp["remaining_units"], 320)
        self.assertEqual(rp["running"], 4)
        p = scale.shard_plan(320, 2.5, 8, 40, limit=4 + 6)
        self.assertEqual(rp["shards_for_remaining"], p["shards"])
        self.assertEqual(rp["new_sessions"], min(6, p["shards"] - 4))
        self.assertLessEqual(rp["new_sessions"], 6)

    def test_new_sessions_limited_by_free_slots(self):
        shards = [self.shard(i, 20) for i in range(4)]
        self.assertEqual(scale.replan(shards, free_slots=1)["new_sessions"], 1)
        self.assertEqual(scale.replan(shards, free_slots=0)["new_sessions"], 0)

    def test_needs_three_shards_ten_percent_done_and_agreement(self):
        self.assertIsNone(scale.replan([self.shard(i, 20) for i in range(2)], free_slots=4))
        # under 10% done does not count
        self.assertIsNone(scale.replan([self.shard(i, 5, elapsed=20.5) for i in range(4)], free_slots=4))
        # exactly 10% counts: (33-8)/10 = 2.5
        self.assertIsNotNone(scale.replan([self.shard(i, 10, elapsed=33) for i in range(3)], free_slots=4))
        # two fast, two slow: no agreement
        mixed = [self.shard(0, 20), self.shard(1, 20), self.shard(2, 20, elapsed=13), self.shard(3, 20, elapsed=13)]
        self.assertIsNone(scale.replan(mixed, free_slots=4))
        # missing unit_min_est: not measured
        self.assertIsNone(scale.replan([self.shard(i, 20, unit_est=None) for i in range(4)], free_slots=4))

    def test_error_exactly_fifty_percent_is_not_a_replan(self):
        # (38-8)/20 = 1.5 vs 1.0: +50% exactly
        self.assertIsNone(scale.replan([self.shard(i, 20, elapsed=38) for i in range(3)], free_slots=4))
        self.assertIsNotNone(scale.replan([self.shard(i, 20, elapsed=38.2) for i in range(3)], free_slots=4))

    def test_overestimate_also_replans(self):
        # (18-8)/20 = 0.5 vs 2.0: -75%
        rp = scale.replan([self.shard(i, 20, elapsed=18, unit_est=2.0) for i in range(3)], free_slots=2)
        self.assertIsNotNone(rp)
        self.assertLess(rp["median_error"], 0)

    def test_delivered_shards_not_running(self):
        shards = [self.shard(i, 20) for i in range(3)] + [self.shard(9, 100, delivered=True)]
        rp = scale.replan(shards, free_slots=2)
        self.assertEqual((rp["running"], rp["remaining_units"]), (3, 240))

    def test_cli_has_top_level_replan(self):
        rc, o, _ = cli("straggler", "--free-slots", "2", stdin=json.dumps([self.shard(i, 20) for i in range(3)]))
        self.assertEqual(rc, 0)
        self.assertIsNotNone(o["replan"])
        rc, o, _ = cli("straggler", stdin=json.dumps(
            [{"id": "a", "elapsed_min": 30, "est_min": 40, "done": 20, "total": 30}]))
        self.assertIn("replan", o)
        self.assertIsNone(o["replan"])


class ProgressEdges(unittest.TestCase):
    def test_non_numeric_values_are_dropped(self):
        self.assertEqual(scale.parse_progress("HQ-PROGRESS done=37 total=150,"), {"done": 37, "total": 150})
        self.assertEqual(scale.parse_progress("HQ-PROGRESS done=37/150 total=150"), {"total": 150})
        self.assertEqual(scale.parse_progress("HQ-PROGRESS done=3 total=nan rework=true"), {"done": 3})
        self.assertEqual(scale.parse_progress('{"done": "37", "total": 150}'), {"total": 150})
        self.assertEqual(scale.parse_progress('{"done": true, "total": 150}'), {"total": 150})
        self.assertIsNone(scale.parse_progress('{"done": "x"}'))
        self.assertIsNone(scale.parse_progress('[1, 2]'))

    def test_quoted_or_echoed_lines_do_not_count(self):
        text = ("HQ-PROGRESS done=10 total=40\n"
                "> HQ-PROGRESS done=99 total=99\n"
                'echo "HQ-PROGRESS done=98 total=99"\n'
                "brief says: print `HQ-PROGRESS done=<n> total=<N>`\n"
                "```\nHQ-PROGRESS done=97 total=99\n```\n")
        self.assertEqual(scale.parse_progress(text), {"done": 10, "total": 40})

    def test_log_prefixes_are_allowed(self):
        self.assertEqual(scale.parse_progress("2026-11-27T10:00:00Z HQ-PROGRESS done=5 total=40\n"),
                         {"done": 5, "total": 40})
        self.assertEqual(scale.parse_progress("[worker s3] HQ-PROGRESS done=6 total=40\n"), {"done": 6, "total": 40})

    def test_cli_missing_file(self):
        rc, _, err = cli("progress", "--file", "/nonexistent/progress.json")
        self.assertEqual(rc, 2)
        self.assertNotIn("Traceback", err)
        self.assertEqual(cli("progress", stdin="nothing")[0], 1)


class DeliveryEdges(unittest.TestCase):
    def test_major4_empty_status_is_not_delivered_not_a_crash(self):
        r = scale.check_delivery("## 交付\nSTATUS:\nVERIFY: ok\n")
        self.assertEqual((r["delivered"], r["reason"]), (False, "section_status_not_done"))
        rc, _, err = cli("delivered", stdin="## 交付\nSTATUS:\nVERIFY: ok\n")
        self.assertEqual(rc, 1)
        self.assertNotIn("Traceback", err)

    def test_last_section_wins(self):
        body = ("## 交付\nSTATUS: PARTIAL\nVERIFY: 待补记\n\n后续修复\n\n"
                "## 交付\nSTATUS: DONE\nVERIFY: vitest related 41 passed\n")
        self.assertTrue(scale.check_delivery(body)["delivered"])
        body = "## 交付\nSTATUS: DONE\nVERIFY: 12 passed\n\n## 交付\nSTATUS: PARTIAL\nVERIFY: 3 passed\n"
        self.assertFalse(scale.check_delivery(body)["delivered"])

    def test_field_formats(self):
        for st in ("STATUS：DONE", "**STATUS:** DONE", "**STATUS**: DONE", "- STATUS: DONE", "status: done",
                   "STATUS: **DONE**"):
            body = "## 交付\n%s\nVERIFY: 12 passed\n" % st
            self.assertTrue(scale.check_delivery(body)["delivered"], st)
        self.assertTrue(scale.check_delivery("## 交付\nSTATUS: DONE\n- **VERIFY：** 12 passed\n")["delivered"])
        self.assertTrue(scale.check_delivery("### **交付**\nSTATUS: DONE\nVERIFY: 12 passed\n")["delivered"])
        # the template line copied verbatim is not a status
        self.assertFalse(scale.check_delivery(
            "## 交付\nSTATUS: DONE | PARTIAL | NEEDS_INPUT | FAILED\nVERIFY: 12 passed\n")["delivered"])

    def test_code_blocks_are_ignored(self):
        body = "说明\n```\n## 交付\nSTATUS: DONE\nVERIFY: 12 passed\n```\n"
        self.assertFalse(scale.check_delivery(body)["delivered"])
        body = "## 交付\nSTATUS: DONE\n```bash\n# run the tests\nnpm test\n```\nVERIFY: 12 passed\n"
        self.assertTrue(scale.check_delivery(body)["delivered"])
        body = "## 交付\nSTATUS: DONE\n```\nVERIFY: 12 passed\n```\n"
        self.assertFalse(scale.check_delivery(body)["delivered"])

    def test_placeholder_verify(self):
        for v in ("待补记（稍后）", "pending", "Pending.", "未验证", "not run", "暂无", "待定", "<命令及结果>",
                  "<!-- fill -->", "TBD", "n/a", "…", "N/A", "todo"):
            body = "## 交付\nSTATUS: DONE\nVERIFY: %s\n" % v
            self.assertFalse(scale.check_delivery(body)["delivered"], v)
        for v in ("pytest 12 passed", "未运行 e2e；单元测试 12 passed", "npm test: 0 failed"):
            self.assertTrue(scale.check_delivery("## 交付\nSTATUS: DONE\nVERIFY: %s\n" % v)["delivered"], v)

    def test_done_file_shapes(self):
        cases = [({"status": " DONE ", "verify": "12 passed"}, True),
                 ({"status": "done", "verify": ["pytest 12 passed", "tsc ok"]}, True),
                 ({"status": "DONE", "verify": True}, False),
                 ({"status": "DONE", "verify": ["待补记"]}, False),
                 ({"status": "DONE", "verify": []}, False),
                 ({"status": "DONE", "verify": "pending"}, False),
                 ({"status": True, "verify": "12 passed"}, False),
                 ([1, 2], False)]
        with tempfile.TemporaryDirectory() as d:
            f = os.path.join(d, "done.json")
            for data, want in cases:
                write(f, json.dumps(data))
                self.assertEqual(scale.check_done_file(f)["delivered"], want, data)
            self.assertEqual(scale.check_done_file(os.path.join(d, "missing.json"))["reason"], "done_file_unreadable")


class TestScopeEdges(unittest.TestCase):
    def test_major5_dot_paths_match_foundation(self):
        r = scale.test_scope([".github/workflows/ci.yml", ".eslintrc.json"], [])
        self.assertEqual(r["scope"], "full")
        self.assertEqual(len(r["foundation_hits"]), 2)
        self.assertEqual(scale.test_scope([".storybook/main.ts"])["scope"], "full")
        self.assertEqual(scale.test_scope(["./.github/workflows/ci.yml"])["scope"], "full")
        self.assertEqual(scale.test_scope([".config/app.ts"], [".config/**"])["scope"], "full")

    def test_prefix_only_and_backslashes(self):
        self.assertEqual(scale.norm_path("./././a/b.ts"), "a/b.ts")
        self.assertEqual(scale.norm_path(".hidden/x"), ".hidden/x")
        self.assertEqual(scale.norm_path("src\\store\\a.ts"), "src/store/a.ts")
        self.assertEqual(scale.test_scope(["src\\store\\a.ts"], ["src/store/**"])["scope"], "full")
        self.assertEqual(scale.test_scope(["src/a.ts"], ["./src/a.ts"])["scope"], "full")

    def test_monorepo_manifests(self):
        for f in ("services/api/go.mod", "crates/core/Cargo.toml", "packages/py/pyproject.toml",
                  "apps/web/Makefile", "apps/web/pnpm-lock.yaml", "apps/web/yarn.lock", "go.mod", "Makefile"):
            self.assertEqual(scale.test_scope([f])["scope"], "full", f)
        self.assertEqual(scale.test_scope(["src/makefile_utils.ts"])["scope"], "related")


class MergeGroupEdges(unittest.TestCase):
    def test_duplicate_ids_are_deferred_not_dropped(self):
        r = scale.merge_group([{"id": "s1", "files": ["a"]}, {"id": "s1", "files": ["b"]}, {"id": "s2", "files": ["c"]}])
        self.assertEqual(r["group"], ["s2"])
        self.assertIn({"id": "s1", "reason": "duplicate_id"}, r["deferred"])

    def test_cycles_and_self_dependency(self):
        r = scale.merge_group([{"id": "a", "files": ["a"], "depends_on": ["b"]},
                               {"id": "b", "files": ["b"], "depends_on": ["a"]},
                               {"id": "c", "files": ["c"], "depends_on": ["c"]},
                               {"id": "d", "files": ["d"], "depends_on": ["a"]},
                               {"id": "e", "files": ["e"]}])
        reasons = {d["id"]: d["reason"] for d in r["deferred"]}
        self.assertEqual(reasons["a"], "dependency_cycle")
        self.assertEqual(reasons["b"], "dependency_cycle")
        self.assertEqual(reasons["c"], "dependency_cycle")
        self.assertEqual(reasons["d"], "depends_on:a")
        self.assertEqual(r["group"], ["e"])

    def test_missing_id_never_in_group(self):
        r = scale.merge_group([{"files": ["a"]}, {"id": "s2", "files": ["b"]}])
        self.assertEqual(r["group"], ["s2"])
        self.assertEqual(r["deferred"][0]["reason"], "missing_id")

    def test_wait_never_negative_and_string_eta(self):
        r = scale.merge_group([{"id": "s1", "files": ["a"]}], pending=[{"id": "s2", "eta_min": -5}])
        self.assertEqual(r["wait_min"], 0)
        r = scale.merge_group([{"id": "s1", "files": ["a"]}], pending=[{"id": "s2", "eta_min": "4"}])
        self.assertEqual((r["wait_min"], r["wait_for"]), (4, ["s2"]))
        r = scale.merge_group([{"id": "s1", "files": ["a"]}], pending=[{"id": "s2", "eta_min": 10}], wait_max_min=10)
        self.assertEqual(r["wait_for"], ["s2"])  # exactly at the limit still waits

    def test_delivered_and_pending_does_not_wait_for_itself(self):
        r = scale.merge_group([{"id": "s1", "files": ["a"]}, {"id": "s2", "files": ["b"], "depends_on": ["s1"]}],
                              pending=[{"id": "s1", "eta_min": 3}])
        self.assertEqual(r["group"], ["s1", "s2"])
        self.assertEqual(r["wait_for"], [])
        self.assertEqual(r["ignored_pending"], ["s1"])

    def test_directory_owners_lists_and_none(self):
        owners = {"shared/": "fix", "./lib/util.ts": ["s1", "s3"], "free.ts": None}
        r = scale.merge_group([{"id": "s1", "files": ["lib/util.ts"]},
                               {"id": "s2", "files": ["shared/sort/index.ts"]},
                               {"id": "s3", "files": ["free.ts"]},
                               {"id": "fix", "files": ["shared/x.ts"]}], owners=owners)
        reasons = {d["id"]: d["reason"] for d in r["deferred"]}
        self.assertEqual(reasons, {"s2": "touches_owned_file"})
        self.assertEqual(r["group"], ["s1", "s3", "fix"])

    def test_dir_file_and_dot_slash_overlap(self):
        r = scale.merge_group([{"id": "s1", "files": ["./src/a.ts"]}, {"id": "s2", "files": ["src/a.ts"]},
                               {"id": "s3", "files": ["pages/"]}, {"id": "s4", "files": ["pages/x.ts"]}])
        reasons = {d["id"]: d["reason"] for d in r["deferred"]}
        self.assertEqual(reasons, {"s2": "overlap", "s4": "overlap"})
        self.assertEqual(r["verify_files"], ["pages/", "src/a.ts"])

    def test_cli_bad_shapes_exit_2(self):
        for bad in ("[1, 2]", '"str"', '{"delivered": [1]}', '{"delivered": [], "owners": [1]}'):
            rc, _, err = cli("merge-group", stdin=bad)
            self.assertEqual(rc, 2, bad)
            self.assertNotIn("Traceback", err)
        rc, o, _ = cli("merge-group", stdin=json.dumps({"delivered": [{"id": "a", "files": ["a"]}]}))
        self.assertEqual((rc, o["group"]), (0, ["a"]))


class LocateEdges(unittest.TestCase):
    def test_major6_generic_name_in_unrelated_dir_does_not_win(self):
        r = scale.locate([{"id": "a", "files": ["src/deep/a/b/c/y.ts"]}, {"id": "b", "files": ["src/other/x.ts"]}],
                         ["src/deep/a/b/c/x.test.ts"])
        self.assertEqual(r["culprits"], ["a"])
        r = scale.locate([{"id": "a", "files": ["src/api/handler.ts"]}, {"id": "b", "files": ["src/ui/index.ts"]}],
                         ["src/api/index.test.ts"])
        self.assertEqual(r["culprits"], ["a"])

    def test_test_name_conventions_and_mirrors(self):
        cases = [("pkg/foo.py", "pkg/test_foo.py"), ("svc/foo.go", "svc/foo_test.go"),
                 ("src/pkg/mod.py", "tests/pkg/test_mod.py"), ("foo.ts", "foo.test.ts"),
                 ("src/ui/Button.tsx", "src/ui/__tests__/Button.test.tsx"),
                 ("src/main/java/a/Foo.java", "src/test/java/a/FooTest.java")]
        for src, test in cases:
            group = [{"id": "hit", "files": [src]}, {"id": "other", "files": ["zzz/unrelated.ts"]}]
            r = scale.locate(group, [test])
            self.assertEqual(r["culprits"], ["hit"], (src, test))

    def test_path_forms(self):
        group = [{"id": "a", "files": ["./web\\users\\Form.tsx"]}, {"id": "b", "files": ["web/orders/List.tsx"]}]
        self.assertEqual(scale.locate(group, ["web/users/Form.tsx"])["culprits"], ["a"])
        self.assertEqual(scale.locate(group, ["/ci/work/repo/web/users/Form.tsx"])["culprits"], ["a"])

    def test_bisect_starts_with_tied_candidates(self):
        group = [{"id": "s1", "files": ["web/a/x.ts"]}, {"id": "s2", "files": ["web/b/y.ts"]},
                 {"id": "s3", "files": ["api/c.ts"]}, {"id": "s4", "files": ["api/d.ts"]}]
        r = scale.locate(group, ["web/flow.spec.ts"])
        self.assertEqual(r["next"]["action"], "bisect")
        self.assertEqual(r["next"]["suspects"], ["s1", "s2"])
        self.assertEqual(r["next"]["revert_and_retest"], ["s1"])

    def test_cli_bad_shapes_exit_2(self):
        for bad in ("[1]", '{"group": [{"files": ["a"]}], "failures": []}', '{"group": [], "failures": "a"}'):
            rc, _, err = cli("locate", stdin=bad)
            self.assertEqual(rc, 2, bad)
            self.assertNotIn("Traceback", err)


class RemovedCommands(unittest.TestCase):
    def test_deferred_subcommands_are_gone(self):
        for c in ("monitor", "calibrate", "thresholds", "label", "full-gate"):
            rc, _, err = cli(c)
            self.assertEqual(rc, 2, c)
            self.assertIn("invalid choice", err)

    def test_kept_subcommands_exist(self):
        for c in ("shards", "straggler", "progress", "delivered", "test-scope", "merge-group", "locate"):
            p = subprocess.run([sys.executable, SCRIPT, c, "--help"], capture_output=True, text=True)
            self.assertEqual(p.returncode, 0, c)


if __name__ == "__main__":
    unittest.main()

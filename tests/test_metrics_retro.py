"""metrics.py retro additions (v0.11.0): version split, CHANGELOG acceptance checks, rule flags,
verify-level escapes, standing-mode recommendation acceptance."""
import json
import os
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, "skills", "hq", "scripts", "metrics.py")


def write(path, text):
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


def task(rid, tid, **kw):
    t = {"type": "task", "run_id": rid, "task_id": tid, "attempts": 1, "review_outcome": "pass",
         "verify_level": "code", "verify_evidence": "ok", "verify_pass": True,
         "issues": {"review": 0, "integration": 0, "user": 0, "severity_max": "none"}}
    t.update(kw)
    return t


def runrec(rid, ver, **kw):
    r = {"type": "run", "run_id": rid, "plugin_version": ver, "project": "p", "started_at": "2026-11-0%sT10:00:00Z" % rid[-1]}
    r.update(kw)
    return r


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def data(self, recs):
        write(os.path.join(self.d, "r.jsonl"), "\n".join(json.dumps(x, ensure_ascii=False) for x in recs) + "\n")

    def run_m(self, *args, fmt="json"):
        p = subprocess.run([sys.executable, SCRIPT, self.d, *args] + (["--format", fmt] if fmt else []),
                           capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stderr)
        return json.loads(p.stdout) if fmt == "json" else p.stdout


def two_versions():
    recs = [runrec("r1", "0.10.6"), runrec("r2", "0.11.0"), runrec("r3", "0.11.1")]
    recs += [task("r1", "t%d" % i, review_outcome="rework" if i < 3 else "pass") for i in range(6)]
    recs += [task("r2", "t%d" % i) for i in range(6)] + [task("r3", "t%d" % i) for i in range(2)]
    return recs


class VersionSplit(Base):
    def test_by_version_table(self):
        self.data(two_versions())
        rep = self.run_m()
        v = {g["key"]: g for g in rep["by_version"]}
        self.assertEqual([g["key"] for g in rep["by_version"]], ["0.10.6", "0.11.0", "0.11.1"])
        self.assertAlmostEqual(v["0.10.6"]["rework_rate"], 0.5)
        self.assertEqual(v["0.11.0"]["rework_rate"], 0)
        self.assertIn("3f. 按插件版本", self.run_m(fmt=None))

    def test_since_and_before(self):
        self.data(two_versions() + [{"type": "task", "run_id": "nov", "task_id": "x"}])
        self.assertEqual(self.run_m("--since-version", "0.11.0")["overview"]["tasks"], 8)
        self.assertEqual(self.run_m("--before-version", "0.11.0")["overview"]["tasks"], 6)
        self.assertEqual(self.run_m("--since-version", "v0.11.1")["overview"]["tasks"], 2)
        self.assertEqual(self.run_m()["overview"]["tasks"], 15)  # unversioned run kept without filters


CHANGELOG = """# 更新记录

## 未发布

### 新规则 A
- **验收判定**：`quality.overall.rework_rate <= 0.2 n>=5 since=0.11.0`；`by_version[key=0.11.0].first_pass_rate >= 0.9 n>=5 since=0.11.0`
- **状态**：待验证（自测通过）

### 新规则 B（样本不够）
- **验收判定**：`by_version[key=0.11.1].first_pass_rate >= 0.9 n>=5 since=0.11.1`
- **状态**：待验证

### 新规则 C（达不到）
- **验收判定**：`quality.overall.rework_rate <= 0.1 since=0.10.0`
- **状态**：待验证

### 新规则 D（聚合）
- **验收判定**：`median(efficiency[*].speedup) >= 1.5 n>=2 since=0.11.0`
- **状态**：待验证

## v0.10.6（2026-11-26）

### 已验证的旧条目
- **验收判定**：`quality.overall.rework_rate <= 0.0`
- **状态**：已验证

### 没写判定的条目
- **验收指标**：自由文本
- **状态**：待验证
"""


class ChangelogCheck(Base):
    def check(self, recs, text=CHANGELOG):
        self.data(recs)
        f = os.path.join(self.d, "CHANGELOG.md")
        write(f, text)
        return {r["title"]: r for r in self.run_m("--check-changelog", f)}

    def test_verdicts(self):
        res = self.check(two_versions())
        self.assertEqual(res["新规则 A"]["verdict"], "达到")
        self.assertEqual(res["新规则 B（样本不够）"]["verdict"], "样本不足")
        self.assertEqual(res["新规则 C（达不到）"]["verdict"], "未达到")
        self.assertEqual(res["新规则 D（聚合）"]["verdict"], "样本不足")   # no wall_min -> no speedup
        self.assertNotIn("已验证的旧条目", res)
        self.assertNotIn("没写判定的条目", res)
        a = res["新规则 A"]["criteria"][0]
        self.assertEqual((a["value"], a["n"], a["since"]), (0, 8, "0.11.0"))

    def test_quality_guard_overrides(self):
        recs = [runrec("r1", "0.10.6"), runrec("r2", "0.11.0", wall_min=10)]
        recs += [task("r1", "t%d" % i, actual_min=5) for i in range(6)]
        recs += [task("r2", "t%d" % i, actual_min=5, review_outcome="rework" if i < 3 else "pass") for i in range(6)]
        text = "## 未发布\n\n### 加速\n- **验收判定**：`efficiency[run_id=r2].speedup >= 2 n>=1 since=0.11.0`\n- **状态**：待验证\n"
        r = self.check(recs, text)["加速"]
        self.assertEqual(r["criteria"][0]["verdict"], "达到")
        self.assertEqual(r["verdict"], "未达到")
        self.assertIn("返工率", r["quality_guard"])

    def test_version_heading_is_default_since(self):
        text = "## v0.11.0（2026-12-01）\n\n### X\n- **验收判定**：`quality.overall.rework_rate <= 0.2 n>=5`\n- **状态**：待验证\n"
        r = self.check(two_versions(), text)["X"]
        self.assertEqual((r["criteria"][0]["since"], r["verdict"]), ("0.11.0", "达到"))

    def test_bad_expression_and_markdown(self):
        text = "## 未发布\n\n### Y\n- **验收判定**：`rework 很低`\n- **状态**：待验证\n"
        r = self.check(two_versions(), text)["Y"]
        self.assertEqual(r["criteria"][0]["verdict"], "无法解析")
        self.assertEqual(r["verdict"], "样本不足")
        f = os.path.join(self.d, "CHANGELOG.md")
        md = self.run_m("--check-changelog", f, fmt=None)
        self.assertIn("CHANGELOG 验收判定", md)

    def test_repo_changelog_parses(self):
        f = os.path.join(ROOT, "CHANGELOG.md")
        self.data(two_versions())
        res = self.run_m("--check-changelog", f)
        self.assertTrue(all(r["verdict"] in ("达到", "未达到", "样本不足") for r in res))


class Flags(Base):
    def test_flags_and_notes_fallback(self):
        recs = [runrec("r1", "0.11.0")]
        recs += [task("r1", "a%d" % i, flags=["bias:+1(effort)"]) for i in range(5)]
        recs += [task("r1", "b%d" % i, notes="选档 bias:+1(tier) 因为模糊") for i in range(2)]
        recs += [task("r1", "c%d" % i, notes="downgrade:user_allowed(-1)", attempts=2, review_outcome="rework")
                 for i in range(3)]
        recs += [task("r1", "d", flags=["rate_limited"], notes="rate_limited 两次")]
        self.data(recs)
        rep = self.run_m()
        g = {x["key"]: x for x in rep["by_flag"]}
        self.assertEqual(g["bias:+1(effort)"]["n"], 5)
        self.assertEqual(g["bias:+1(tier)"]["n"], 2)
        self.assertEqual(g["rate_limited"]["n"], 1)       # not double counted
        self.assertEqual(g["downgrade:user_allowed(-1)"]["first_pass_rate"], 0)
        msgs = " ".join(s["message"] for s in rep["signals"])
        self.assertIn("规则 9 上调的任务一次通过率 100%", msgs)
        self.assertIn("规则 11 授权降档", msgs)

    def test_export_keeps_only_known_flags(self):
        self.data([runrec("r1", "0.11.0"),
                   task("r1", "a", flags=["bias:+1(tier)", "secret-project-x"], notes="客户名 bias:+1(effort)")])
        p = subprocess.run([sys.executable, SCRIPT, self.d, "--export-anon", "--raw"], capture_output=True, text=True)
        out = json.loads(p.stdout)
        t = next(r for r in out["records"] if r["type"] == "task")
        self.assertEqual(t["flags"], ["bias:+1(tier)", "bias:+1(effort)"])
        self.assertNotIn("secret", p.stdout)
        self.assertNotIn("客户名", p.stdout)


class VerifyLevels(Base):
    def test_escapes_by_level(self):
        recs = [runrec("r1", "0.11.0")]
        recs += [task("r1", "d%d" % i, verify_level="doc") for i in range(5)]
        recs += [task("r1", "c%d" % i, verify_level="code",
                      issues={"review": 0, "integration": 1 if i < 2 else 0, "user": 1 if i == 0 else 0,
                              "severity_max": "major" if i == 0 else "minor"}) for i in range(5)]
        self.data(recs)
        rep = self.run_m()
        g = {x["key"]: x for x in rep["by_verify_level"]}
        self.assertEqual(g["doc"]["escaped_per_task"], 0)
        self.assertAlmostEqual(g["code"]["escaped_per_task"], 3 / 5)
        self.assertAlmostEqual(g["code"]["escaped_integration"], 2 / 5)
        self.assertEqual(g["code"]["escaped_major"], 1)
        scopes = [s["scope"] for s in rep["signals"]]
        self.assertIn("verify code", scopes)
        self.assertNotIn("verify doc", scopes)
        self.assertIn("3g. 按验证级别", self.run_m(fmt=None))


class Recommendations(Base):
    def test_acceptance_rate(self):
        recs = []
        seq = [(1, 3, None), (2, 2, True), (3, 4, False), (4, 1, True), (5, 0, True)]
        for i, (k, nxt, fr) in enumerate(seq):
            r = runrec("s%d" % (i + 1), "0.11.0", standing_seq=k, recommended_next=nxt)
            if fr is not None:
                r["from_recommendation"] = fr
            recs.append(r)
        recs.append(runrec("x9", "0.11.0", project="other", standing_seq=2, from_recommendation=True))
        self.data(recs)
        rc = self.run_m()["recommendations"]
        self.assertEqual((rc["standing_runs"], rc["offered"], rc["accepted"]), (6, 4, 3))
        self.assertAlmostEqual(rc["acceptance_rate"], 0.75)
        self.assertEqual(rc["completion_claims"], 1)
        self.assertIn("6c. 常驻模式推荐", self.run_m(fmt=None))

    def test_no_standing_runs(self):
        self.data(two_versions())
        rep = self.run_m()
        self.assertEqual(rep["recommendations"]["standing_runs"], 0)
        self.assertNotIn("6c. 常驻模式推荐", self.run_m(fmt=None))


if __name__ == "__main__":
    unittest.main()

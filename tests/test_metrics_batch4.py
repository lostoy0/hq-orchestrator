"""metrics.py: changelog stats split into checkable / not-applicable judgments; monitor labels by source."""
import json
import os
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, "skills", "hq", "scripts", "metrics.py")


def run(*args):
    p = subprocess.run([sys.executable, SCRIPT, *args], capture_output=True, text=True)
    assert p.returncode == 0, p.stderr
    return p.stdout


CHANGELOG = """# 更新记录

## 未发布

### A 可判定
- **验收判定**：`quality.overall.rework_rate <= 0.2 since=0.11.0`
- **状态**：待验证

### B 不适用
- **验收判定**：不适用（流程改动）
- **状态**：待验证

### C 没写判定
- **状态**：已验证

## v0.10.6（2026-11-26）

### D 不适用
- **验收判定**：不适用
- **状态**：已撤回
"""


class ChangelogSplit(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.f = os.path.join(self.tmp.name, "CHANGELOG.md")
        with open(self.f, "w", encoding="utf-8") as fh:
            fh.write(CHANGELOG)

    def tearDown(self):
        self.tmp.cleanup()

    def test_counts(self):
        st = json.loads(run("--changelog-stats", self.f, "--format", "json"))
        by = {r["version"]: r for r in st["versions"]}
        self.assertEqual((by["未发布"]["checkable"], by["未发布"]["not_applicable"], by["未发布"]["judged"]), (1, 1, 2))
        self.assertEqual((by["0.10.6"]["checkable"], by["0.10.6"]["not_applicable"]), (0, 1))
        t = st["total"]
        self.assertEqual((t["checkable"], t["not_applicable"], t["judged"], t["entries"]), (1, 2, 3, 4))
        self.assertAlmostEqual(t["checkable_rate"], 0.25)
        self.assertAlmostEqual(t["judged_rate"], 0.75)  # kept for compatibility

    def test_markdown_columns(self):
        md = run("--changelog-stats", self.f)
        self.assertIn("可机器判定", md)
        self.assertIn("判定写了不适用", md)
        self.assertIn("另有 2 条写了“不适用”", md)

    def test_repo_changelog(self):
        st = json.loads(run("--changelog-stats", os.path.join(ROOT, "CHANGELOG.md"), "--format", "json"))
        t = st["total"]
        self.assertEqual(t["judged"], t["checkable"] + t["not_applicable"])


class LabelSources(unittest.TestCase):
    def report(self, recs):
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "r.jsonl"), "w", encoding="utf-8") as fh:
                fh.write("\n".join(json.dumps(x) for x in recs) + "\n")
            rep = json.loads(run(d, "--format", "json"))
            md = run(d)
            anon = json.loads(run(d, "--export-anon", "--raw"))
        return rep, md, anon

    def test_sources_counted(self):
        base = {"type": "monitor", "run_id": "r1", "metric": "idle_min", "level": 1}
        recs = [{"type": "task", "run_id": "r1", "task_id": "s1", "shard_group": "g"},
                dict(base, label="effective", label_source="rule"),
                dict(base, label="false_positive", label_source="rule"),
                dict(base, label="effective", label_source="reviewer"),
                dict(base, label="effective", label_source="user"),
                dict(base, label="effective"),                       # labelled, source not recorded
                dict(base, label=None),                              # not labelled yet
                dict(base, label="effective", label_source="secret-x"),
                {"type": "monitor", "run_id": "r1", "event": "missed", "metric": "idle_min", "label_source": "rule"}]
        rep, md, anon = self.report(recs)
        x = rep["scale_out"][0]
        self.assertEqual(x["label_sources"], {"rule": 2, "reviewer": 1, "user": 1, "other": 2, "unlabeled": 1})
        self.assertAlmostEqual(x["rule_label_share"], 2 / 6)
        self.assertIn("2/1/1/2/1", md)
        sources = {r.get("label_source") for r in anon["records"] if r["type"] == "monitor"}
        self.assertEqual(sources, {"rule", "reviewer", "user", "other", None})
        self.assertNotIn("secret-x", json.dumps(anon))

    def test_no_labels(self):
        rep, _, _ = self.report([{"type": "monitor", "run_id": "r1", "metric": "idle_min", "level": 1}])
        x = rep["scale_out"][0]
        self.assertEqual(x["label_sources"]["unlabeled"], 1)
        self.assertIsNone(x["rule_label_share"])


if __name__ == "__main__":
    unittest.main()

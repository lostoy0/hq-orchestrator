import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, "skills", "hq", "scripts", "assist-config.py")
CATALOG = os.path.join(ROOT, "tests", "fixtures", "codex-models", "catalog.json")
TEMPLATE = os.path.join(ROOT, "skills", "hq", "references", "playbook-template.md")


class AssistConfigTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.home = os.path.join(self.tmp, "hq")
        self.proj = os.path.join(self.tmp, "p")
        os.makedirs(self.proj)
        # A codex that is not on PATH and no cache: only --catalog gives a catalog.
        self.env = dict(os.environ, HQ_HOME=self.home, CODEX_HOME=os.path.join(self.tmp, "nocodex"),
                        PATH=os.path.dirname(sys.executable) + os.pathsep + "/usr/bin" + os.pathsep + "/bin")

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def run_(self, *args, rc=0):
        r = subprocess.run([sys.executable, SCRIPT] + list(args), capture_output=True, text=True, env=self.env)
        self.assertEqual(r.returncode, rc, r.stdout + r.stderr)
        return r

    def js(self, *args, rc=0):
        return json.loads(self.run_(*args, "--json", rc=rc).stdout)

    def playbook(self):
        with open(os.path.join(self.proj, ".hq", "PLAYBOOK.md"), encoding="utf-8") as f:
            return f.read()

    def test_models_lists_visible_with_efforts_and_retirement(self):
        d = self.js("models", "--catalog", CATALOG)
        slugs = [m["slug"] for m in d["models"]]
        self.assertNotIn("m-hidden", slugs)
        old = next(m for m in d["models"] if m["slug"] == "m-small-old")
        self.assertEqual(old["replaced_by"], "m-small")
        self.assertEqual(next(m for m in d["models"] if m["slug"] == "m-big")["efforts"], ["medium", "high", "xhigh"])

    def test_suggest_maps_classes_and_fits_effort(self):
        t = self.js("suggest", "--catalog", CATALOG)["tiers"]
        self.assertEqual(t["T0"]["model"], "m-small")          # retiring m-small-old skipped
        self.assertEqual(t["T1"]["model"], "m-main")
        self.assertEqual(t["T2"], {"model": "m-main", "effort": "medium", "basis": t["T2"]["basis"]})
        self.assertEqual(t["T3"]["model"], "m-big")
        self.assertEqual(t["T4"]["effort"], "high")
        mm = self.run_("suggest", "--catalog", CATALOG, "--model-map").stdout.strip()
        self.assertEqual(mm, "T0=m-small,T1=m-main,T2=m-main,T3=m-big,T4=m-big")

    def test_no_catalog_exits_4(self):
        self.run_("models", rc=4)
        self.run_("suggest", "--cli", "claude", rc=4)

    def test_user_level_applies_to_project_from_template(self):
        self.run_("set", "--scope", "user", "--use", "codex", "--auto-models", "--catalog", CATALOG)
        os.makedirs(os.path.join(self.proj, ".hq"))
        shutil.copy(TEMPLATE, os.path.join(self.proj, ".hq", "PLAYBOOK.md"))   # use: [] + <模型> placeholders
        d = self.js("show", "--project", self.proj)
        eff = d["effective"]
        self.assertEqual(eff["use"], ["codex"])
        self.assertEqual(eff["profiles"]["codex"]["models"], {"T0": "m-small", "T1": "m-main", "T2": "m-main"})
        self.assertEqual(eff["profiles"]["codex"]["effort"]["T2"], "medium")
        self.assertEqual(d["sources"]["use"], "user")

    def test_project_overrides_and_off(self):
        self.run_("set", "--scope", "user", "--use", "codex", "--auto-models", "--catalog", CATALOG)
        self.run_("set", "--scope", "project", "--project", self.proj, "--max-tier", "T1",
                  "--profile", "codex", "--models", "T2=m-big")
        pb = self.playbook()
        self.assertIn("cost_weight:", pb)                      # rest of the template kept
        self.assertEqual(pb.count("\nassist:"), 1)
        eff = self.js("show", "--project", self.proj)["effective"]
        self.assertEqual(eff["max_tier"], "T1")
        self.assertEqual(eff["profiles"]["codex"]["models"], {"T0": "m-small", "T1": "m-main", "T2": "m-big"})
        self.run_("set", "--scope", "project", "--project", self.proj, "--use", "off")
        self.assertEqual(self.js("show", "--project", self.proj)["effective"]["use"], "off")
        self.assertIn("assist: 关闭", self.run_("check", "--project", self.proj).stdout)

    def test_auto_models_does_not_overwrite(self):
        self.run_("set", "--scope", "user", "--use", "codex", "--profile", "codex", "--models", "T0=m-main", "--effort", "T0=medium",
                  "--auto-models", "--catalog", CATALOG)
        p = self.js("show", "--project", self.proj)["effective"]["profiles"]["codex"]
        self.assertEqual(p["models"]["T0"], "m-main")
        self.assertEqual(p["effort"]["T0"], "medium")
        self.assertEqual(p["models"]["T1"], "m-main")

    def test_check_flags_bad_model_effort_and_retiring(self):
        self.run_("set", "--scope", "user", "--use", "codex", "--profile", "codex",
                  "--models", "T0=m-small-old,T1=nope,T2=m-big", "--effort", "T2=low", "--catalog", CATALOG, "--force")
        d = self.js("check", "--project", self.proj, "--catalog", CATALOG, rc=1)
        text = " ".join(d["errors"])
        self.assertIn("nope", text)
        self.assertIn("不支持思考深度 low", text)
        self.assertTrue(any("下线" in w for w in d["warnings"]))

    def test_set_refuses_bad_model_without_force(self):
        self.run_("set", "--scope", "user", "--use", "codex", "--profile", "codex", "--models", "T0=nope",
                  "--catalog", CATALOG, rc=1)
        self.assertFalse(os.path.exists(os.path.join(self.home, "config.yaml")))

    def test_check_fills_missing_models(self):
        self.run_("set", "--scope", "user", "--use", "codex")
        d = self.js("check", "--project", self.proj, "--catalog", CATALOG)
        self.assertTrue(d["ok"])
        self.assertEqual(d["fills"]["codex"]["T0"]["model"], "m-small")

    def test_env_file_permission(self):
        ef = os.path.join(self.tmp, "kimi.env")
        with open(ef, "w") as f:
            f.write("X=1\n")
        os.chmod(ef, 0o644)
        self.run_("set", "--scope", "user", "--use", "kimi", "--profile", "kimi", "--cli", "claude", "--env-file", ef,
                  "--models", "T0=k,T1=k,T2=k")
        self.assertIn("600", " ".join(self.js("check", "--project", self.proj, rc=1)["errors"]))
        os.chmod(ef, 0o600)
        self.assertTrue(self.js("check", "--project", self.proj)["ok"])

    def test_bad_args(self):
        self.run_("set", "--scope", "user", "--max-tier", "T3", rc=2)
        self.run_("set", "--scope", "user", "--models", "T0=a", rc=2)
        self.run_("set", "--scope", "user", "--profile", "codex", "--models", "T3=a", rc=2)
        self.run_("set", "--scope", "user", "--profile", "codex", "--effort", "T0=huge", rc=2)
        self.run_("set", "--scope", "user", "--profile", "codex", "--models", "T0=a b", rc=2)

    def test_insert_into_playbook_without_assist(self):
        os.makedirs(os.path.join(self.proj, ".hq"))
        with open(os.path.join(self.proj, ".hq", "PLAYBOOK.md"), "w", encoding="utf-8") as f:
            f.write("# PB\n\n## 授权\n\n```yaml\nmerge_default: ask\n```\n\n## 项目事实\n")
        self.run_("set", "--scope", "project", "--project", self.proj, "--use", "codex", "--profile", "codex",
                  "--models", "T0=m-small", "--catalog", CATALOG)
        pb = self.playbook()
        self.assertLess(pb.index("merge_default"), pb.index("assist:"))
        self.assertLess(pb.index("assist:"), pb.index("## 项目事实"))
        self.assertEqual(self.js("show", "--project", self.proj)["effective"]["profiles"]["codex"]["models"], {"T0": "m-small"})


if __name__ == "__main__":
    unittest.main()

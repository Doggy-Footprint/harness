import json
import unittest

from evaluation.pr_test_quality.tests.fakes import ROOT


class ShippedConfig(unittest.TestCase):
    def setUp(self):
        path = ROOT / "evaluation" / "pr_test_quality" / "config.json"
        self.assertTrue(path.is_file(), "evaluation/pr_test_quality/config.json is missing")
        self.cfg = json.loads(path.read_text(encoding="utf-8"))

    def test_O26_mining_thresholds(self):
        m = self.cfg["mining"]
        self.assertEqual(m["merged_after"], "2026-07-01")
        self.assertEqual(m["min_stars"], 200)
        self.assertEqual(m["per_repo_max"], 3)
        self.assertEqual(m["target_per_language"], 40)
        self.assertTrue(m["licenses"])
        self.assertTrue(m["title_exclude"])

    def test_O26_validation_eval_and_report_thresholds(self):
        self.assertEqual(self.cfg["validation"]["repeats"], 3)
        self.assertEqual(self.cfg["validation"]["timeout_s"], 600)
        self.assertEqual(self.cfg["eval"]["timeout_s"], 900)
        self.assertEqual(self.cfg["report"]["min_mutants"], 10)

    def test_O26_models_and_effort(self):
        for key in ("brief", "usersim", "judge"):
            self.assertEqual(self.cfg[key]["model"], "claude-opus-5-5", key)
            self.assertEqual(self.cfg[key]["effort"], "medium", key)
        self.assertEqual(self.cfg["agent"]["model"], "claude-sonnet-5-5")
        self.assertEqual(self.cfg["agent"]["effort"], "medium")

    def test_O25_agent_limits(self):
        a = self.cfg["agent"]
        self.assertEqual(a["wall_clock_min"], 180)
        self.assertEqual(a["max_user_turns"], 8)
        self.assertEqual(a["concurrency"], 3)
        self.assertEqual(self.cfg["brief"]["attempts"], 3)
        self.assertEqual(self.cfg["usersim"]["timeout_s"], 900)

    def test_O24_gce_project(self):
        self.assertEqual(self.cfg["gce"]["project"], "harness-eval-d31ee3")
        for key in ("region", "zone", "secret", "data_disk"):
            self.assertTrue(self.cfg["gce"].get(key), key)


if __name__ == "__main__":
    unittest.main()

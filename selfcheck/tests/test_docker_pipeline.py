import json
import unittest

from selfcheck import calibrate, evaluate, mutants, score
from selfcheck.tests.helpers import (
    PYTEST_ID, clear_labeled_containers, docker_only, labeled_containers, pass_set, pilot, require_image,
)

SRC_PATHS = ["src/_pytest/reports.py"]
MUTANT_KEYS = {
    "id", "path", "line", "col", "operator", "original", "replacement", "group", "patch",
    "compile_ok", "killed", "timeout",
}


@docker_only
class PytestPipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.row = pilot(PYTEST_ID)
        require_image(cls.row)
        clear_labeled_containers()
        cls.base_sources = evaluate.read_files(cls.row, "", SRC_PATHS)
        cls.gold_sources = evaluate.read_files(cls.row, cls.row["patch"], SRC_PATHS)
        cls.validation = {
            "instance_id": PYTEST_ID, "valid": True, "reasons": [],
            "f2p": list(cls.row["FAIL_TO_PASS"]), "p2p_effective": [], "p2p_flaky": [], "p2p_broken": [],
        }
        cls.generated = mutants.generate(
            cls.base_sources, cls.gold_sources, cls.row["patch"], sample=4, seed=1
        )
        cls.detected = mutants.detect(
            cls.row, cls.generated, validation=cls.validation, workers=2
        )

    def test_vo9_k7_generate_with_sample_four(self):
        self.assertEqual(len(self.generated), 4)
        self.assertEqual({m["path"] for m in self.generated}, set(SRC_PATHS))

    def test_vo9_k7_detect_returns_every_key_in_input_order(self):
        self.assertEqual([m["id"] for m in self.detected], [m["id"] for m in self.generated])
        for item in self.detected:
            with self.subTest(mutant=item["id"]):
                self.assertEqual(set(item), MUTANT_KEYS)
                self.assertIsInstance(item["compile_ok"], bool)
                self.assertIsInstance(item["killed"], bool)
                self.assertIsInstance(item["timeout"], bool)
                if not item["compile_ok"]:
                    self.assertFalse(item["killed"])

    def test_vo9_k7_killed_agrees_with_rerunning_evaluate(self):
        valid = [m for m in self.detected if m["compile_ok"]]
        self.assertTrue(valid, "no compile-valid mutant to re-run")
        chosen = valid[0]
        rerun = evaluate.evaluate(self.row, chosen["patch"], self.row["test_patch"])
        expected = rerun["timed_out"] or any(
            not pass_set(rerun["status"].get(test)) for test in self.validation["f2p"]
        )
        self.assertIs(chosen["killed"], expected)
        self.assertEqual(labeled_containers(), [])

    def test_vo14_i1_ladder_is_monotonic_with_four_mutants(self):
        result = calibrate.calibrate_instance(
            self.row, validation=self.validation, mutants=self.detected
        )
        self.assertEqual(result["instance_id"], PYTEST_ID)
        self.assertEqual(set(result["levels"]), {"gold", "stripped", "existing", "empty"})
        self.assertEqual(result["violations"], [])
        self.assertIs(result["monotonic"], True)

    def test_vo14_i2_gold_prediction_scores_identically_twice_without_cache(self):
        prediction = {
            "instance_id": PYTEST_ID, "src_diff": self.row["patch"], "test_patch": self.row["test_patch"],
        }
        first = score.score_prediction(
            self.row, prediction, validation=self.validation, mutants=self.detected
        )
        second = score.score_prediction(
            self.row, prediction, validation=self.validation, mutants=self.detected
        )
        self.assertEqual(json.dumps(first, sort_keys=True), json.dumps(second, sort_keys=True))
        self.assertIs(first["resolved"], True)


if __name__ == "__main__":
    unittest.main()

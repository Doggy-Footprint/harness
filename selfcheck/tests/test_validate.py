import unittest

from selfcheck import validate
from selfcheck.tests.helpers import FakeEvaluate, eval_result

F1 = "t/test_f.py::test_f1"
F2 = "t/test_f.py::test_f2"
PE = "t/test_p.py::test_effective"
PE2 = "t/test_p.py::test_effective_two"
PF5 = "t/test_p.py::test_flaky_fails_once"
PF1 = "t/test_p.py::test_flaky_passes_once"
PB = "t/test_p.py::test_broken"
GOLD = "GOLD-SRC-DIFF"
TESTS = "GOLD-TEST-PATCH"
OK_LEAK = {"ok": True, "future_commits": 0, "future_tags": [], "gold_blobs_present": [], "gold_copies": []}
BAD_LEAK = {"ok": False, "future_commits": 1, "future_tags": ["v9"], "gold_blobs_present": ["a.py"], "gold_copies": ["/opt/a.py"]}


def make_instance(p2p):
    return {
        "instance_id": "v__v-1", "patch": GOLD, "test_patch": TESTS,
        "FAIL_TO_PASS": [F1, F2], "PASS_TO_PASS": list(p2p),
    }


def default_status(kind, p2p):
    if kind == "base":
        status = {F1: "FAILED"}
        passing = "PASSED"
    else:
        status = {F1: "PASSED", F2: "XFAIL"}
        passing = "PASSED"
    for test in p2p:
        status[test] = passing
    return status


class Scenario:
    def __init__(self, p2p=(PE, PE2), repeats=3, leak=OK_LEAK):
        self.p2p = list(p2p)
        self.repeats = repeats
        self.leak = leak
        self.table = {}
        for kind in ("base", "gold"):
            for i in range(repeats):
                self.table[(kind, i)] = eval_result(default_status(kind, self.p2p), key="%s-%d" % (kind, i))
        self.instance = make_instance(self.p2p)

    def update(self, kind, repeat, **changes):
        current = self.table[(kind, repeat)]
        status = changes.pop("status", None)
        if status is not None:
            current["status"] = status
        current.update(changes)

    def set_test(self, kind, repeat, test, value):
        status = self.table[(kind, repeat)]["status"]
        if value is None:
            status.pop(test, None)
        else:
            status[test] = value

    def respond(self, instance, src_diff, test_patch, repeat=0):
        kind = "base" if src_diff == "" else "gold"
        return self.table[(kind, repeat)]

    def run(self, **kwargs):
        self.evaluate = FakeEvaluate(self.respond)
        self.leak_calls = []

        def leak_fn(instance):
            self.leak_calls.append(instance)
            return self.leak

        return validate.validate_instance(
            self.instance, evaluate_fn=self.evaluate, leak_fn=leak_fn, **kwargs
        )


class ValidateInstanceTests(unittest.TestCase):
    def test_vo4_v1_valid_instance(self):
        scenario = Scenario()
        result = scenario.run(repeats=3)
        self.assertEqual(result["instance_id"], "v__v-1")
        self.assertIs(result["valid"], True)
        self.assertEqual(result["reasons"], [])
        self.assertEqual(result["p2p_effective"], [PE, PE2])
        self.assertEqual(result["p2p_flaky"], [])
        self.assertEqual(result["p2p_broken"], [])
        self.assertEqual(result["leak"], OK_LEAK)
        self.assertEqual(result["f2p"], [F1, F2])

    def test_vo4_v1_runs_hold_the_evaluate_results_in_repeat_order(self):
        scenario = Scenario()
        result = scenario.run(repeats=3)
        self.assertEqual(result["runs"]["base"], [scenario.table[("base", i)] for i in range(3)])
        self.assertEqual(result["runs"]["gold"], [scenario.table[("gold", i)] for i in range(3)])

    def test_vo4_v2_apply_failed(self):
        scenario = Scenario()
        scenario.update("gold", 2, apply="src_failed")
        result = scenario.run(repeats=3)
        self.assertFalse(result["valid"])
        self.assertEqual(result["reasons"], ["apply_failed"])

    def test_vo4_v2_test_failed_apply_counts_as_apply_failed(self):
        scenario = Scenario()
        scenario.update("base", 0, apply="test_failed")
        result = scenario.run(repeats=3)
        self.assertEqual(result["reasons"], ["apply_failed"])

    def test_vo4_v2_reasons_are_not_exclusive_and_follow_the_fixed_order(self):
        scenario = Scenario()
        scenario.update("gold", 2, apply="src_failed", status={})
        result = scenario.run(repeats=3)
        self.assertFalse(result["valid"])
        self.assertEqual(result["reasons"], ["apply_failed", "f2p_fails_on_gold"])

    def test_vo4_v2_skipped_f2p_on_base_is_not_in_fail_set(self):
        scenario = Scenario()
        scenario.set_test("base", 2, F1, "SKIPPED")
        result = scenario.run(repeats=3)
        self.assertEqual(result["reasons"], ["f2p_passes_on_base"])

    def test_vo4_v2_timeout(self):
        scenario = Scenario()
        scenario.update("base", 1, timed_out=True)
        result = scenario.run(repeats=3)
        self.assertFalse(result["valid"])
        self.assertEqual(result["reasons"], ["timeout"])

    def test_vo4_v2_f2p_passes_on_base(self):
        scenario = Scenario()
        scenario.set_test("base", 1, F1, "PASSED")
        result = scenario.run(repeats=3)
        self.assertFalse(result["valid"])
        self.assertEqual(result["reasons"], ["f2p_passes_on_base"])

    def test_vo4_v2_f2p_xfail_on_base_counts_as_passing(self):
        scenario = Scenario()
        scenario.set_test("base", 0, F2, "XFAIL")
        result = scenario.run(repeats=3)
        self.assertEqual(result["reasons"], ["f2p_passes_on_base"])

    def test_vo4_v2_f2p_fails_on_gold(self):
        scenario = Scenario()
        scenario.set_test("gold", 0, F2, "FAILED")
        result = scenario.run(repeats=3)
        self.assertFalse(result["valid"])
        self.assertEqual(result["reasons"], ["f2p_fails_on_gold"])

    def test_vo4_v2_f2p_missing_on_gold_is_a_failure(self):
        scenario = Scenario()
        scenario.set_test("gold", 2, F1, None)
        result = scenario.run(repeats=3)
        self.assertEqual(result["reasons"], ["f2p_fails_on_gold"])

    def test_vo4_v2_p2p_broken(self):
        scenario = Scenario(p2p=(PE, PB))
        for kind in ("base", "gold"):
            for i in range(3):
                scenario.set_test(kind, i, PB, "FAILED")
        result = scenario.run(repeats=3)
        self.assertFalse(result["valid"])
        self.assertEqual(result["reasons"], ["p2p_broken"])

    def test_vo4_v2_leak(self):
        scenario = Scenario(leak=BAD_LEAK)
        result = scenario.run(repeats=3)
        self.assertFalse(result["valid"])
        self.assertEqual(result["reasons"], ["leak"])
        self.assertEqual(result["leak"], BAD_LEAK)

    def test_vo4_v7_leak_check_failure_is_recorded_as_leak_reason(self):
        scenario = Scenario()
        message = "leak_check could not complete for v__v-1"

        def failing(instance):
            raise RuntimeError(message)

        scenario.evaluate = FakeEvaluate(scenario.respond)
        result = validate.validate_instance(
            scenario.instance, repeats=3, evaluate_fn=scenario.evaluate, leak_fn=failing
        )
        self.assertFalse(result["valid"])
        self.assertEqual(result["reasons"], ["leak"])
        self.assertIs(result["leak"]["ok"], False)
        self.assertIn("v__v-1", result["leak"]["error"])
        self.assertEqual(len(result["runs"]["base"]), 3)

    def test_vo4_v2_every_reason_can_occur_together(self):
        scenario = Scenario(p2p=(PE, PB), leak=BAD_LEAK)
        for kind in ("base", "gold"):
            for i in range(3):
                scenario.set_test(kind, i, PB, "ERROR")
        scenario.update("gold", 0, apply="src_failed")
        scenario.update("gold", 1, timed_out=True)
        scenario.set_test("base", 0, F1, "PASSED")
        scenario.set_test("gold", 2, F2, "FAILED")
        result = scenario.run(repeats=3)
        self.assertFalse(result["valid"])
        self.assertEqual(
            result["reasons"],
            ["apply_failed", "timeout", "f2p_passes_on_base", "f2p_fails_on_gold", "p2p_broken", "leak"],
        )

    def test_vo4_v3_flaky_p2p_is_recorded_and_valid(self):
        scenario = Scenario(p2p=(PE, PF5, PF1))
        scenario.set_test("base", 1, PF5, "FAILED")
        for kind in ("base", "gold"):
            for i in range(3):
                if (kind, i) != ("gold", 2):
                    scenario.set_test(kind, i, PF1, "FAILED")
        result = scenario.run(repeats=3)
        self.assertTrue(result["valid"])
        self.assertEqual(result["reasons"], [])
        self.assertEqual(result["p2p_effective"], [PE])
        self.assertEqual(result["p2p_flaky"], [PF5, PF1])
        self.assertEqual(result["p2p_broken"], [])

    def test_vo4_v3_xfail_counts_as_passing_for_effective(self):
        scenario = Scenario(p2p=(PE, PE2))
        scenario.set_test("gold", 1, PE2, "XFAIL")
        result = scenario.run(repeats=3)
        self.assertEqual(result["p2p_effective"], [PE, PE2])
        self.assertEqual(result["p2p_flaky"], [])

    def test_vo4_v4_broken_p2p_never_passes_in_any_run(self):
        scenario = Scenario(p2p=(PE, PB))
        for kind in ("base", "gold"):
            for i in range(3):
                scenario.set_test(kind, i, PB, None)
        result = scenario.run(repeats=3)
        self.assertFalse(result["valid"])
        self.assertEqual(result["p2p_broken"], [PB])
        self.assertEqual(result["p2p_effective"], [PE])
        self.assertEqual(result["p2p_flaky"], [])

    def test_vo4_v5_repeat_indexes_cover_zero_to_repeats_minus_one(self):
        for repeats in (1, 2, 4):
            with self.subTest(repeats=repeats):
                scenario = Scenario(repeats=repeats)
                result = scenario.run(repeats=repeats)
                self.assertEqual(len(scenario.evaluate.calls), 2 * repeats)
                for src_diff in ("", GOLD):
                    indexes = sorted(
                        kwargs["repeat"] for src, _, kwargs in scenario.evaluate.calls if src == src_diff
                    )
                    self.assertEqual(indexes, list(range(repeats)))
                self.assertEqual(len(result["runs"]["base"]), repeats)
                self.assertEqual(len(result["runs"]["gold"]), repeats)
                self.assertEqual(
                    [r["key"] for r in result["runs"]["base"]], ["base-%d" % i for i in range(repeats)]
                )
                self.assertEqual(
                    [r["key"] for r in result["runs"]["gold"]], ["gold-%d" % i for i in range(repeats)]
                )

    def test_vo4_v5_default_repeats_is_three(self):
        scenario = Scenario()
        scenario.evaluate = FakeEvaluate(scenario.respond)
        result = validate.validate_instance(
            scenario.instance, evaluate_fn=scenario.evaluate, leak_fn=lambda instance: OK_LEAK
        )
        self.assertEqual(len(scenario.evaluate.calls), 6)
        self.assertEqual(len(result["runs"]["base"]), 3)

    def test_vo4_v5_flaky_classification_uses_all_two_times_repeats_runs(self):
        scenario = Scenario(p2p=(PE, PF1), repeats=2)
        scenario.set_test("gold", 1, PF1, "FAILED")
        result = scenario.run(repeats=2)
        self.assertTrue(result["valid"])
        self.assertEqual(result["p2p_effective"], [PE])
        self.assertEqual(result["p2p_flaky"], [PF1])
        self.assertEqual(result["p2p_broken"], [])

    def test_vo4_v6_base_uses_empty_src_and_gold_uses_instance_patch(self):
        scenario = Scenario()
        scenario.run(repeats=3)
        sources = sorted(src for src, _, _ in scenario.evaluate.calls)
        self.assertEqual(sources, [""] * 3 + [GOLD] * 3)

    def test_vo4_v6_every_call_uses_the_gold_test_patch_and_repeat_keyword(self):
        scenario = Scenario()
        scenario.run(repeats=3)
        for src, tests, kwargs in scenario.evaluate.calls:
            self.assertEqual(tests, TESTS)
            self.assertEqual(set(kwargs), {"repeat"})

    def test_vo4_v6_leak_fn_receives_the_instance(self):
        scenario = Scenario()
        scenario.run(repeats=3)
        self.assertEqual(scenario.leak_calls, [scenario.instance])


if __name__ == "__main__":
    unittest.main()

import copy
import os
import tempfile
import unittest

from selfcheck import score
from selfcheck.tests.helpers import FakeEvaluate, FakeReadFiles, eval_result, git_diff

BASE_M = (
    "class C:\n    def test_a(self):\n        assert 1 == 1\n\n"
    "    def test_b(self):\n        assert 2 == 2\n\n"
    "    def helper(self):\n        return 1\n"
)
NEW_M = (
    "class C:\n    def test_a(self):\n        assert 1 == 2\n\n"
    "    def test_b(self):\n        assert 2 == 2\n\n"
    "    def helper(self):\n        return 2\n\n"
    "    def test_new(self):\n        assert True\n\n\n"
    "def test_mod():\n    pass\n"
)
BASE_S = "def test_one():\n    assert 1\n\n\ndef test_two():\n    assert 2\n"
NEW_S = "def test_one():\n    assert 3\n\n\ndef test_two():\n    assert 2\n\n\ndef test_three():\n    pass\n"


class TestIdKeyTests(unittest.TestCase):
    def test_vo10_a1_pytest_three_forms(self):
        cases = [
            ("testing/test_reports.py::TestReportSerialization::test_chained_exceptions[TestReport]",
             ("testing/test_reports.py", "TestReportSerialization", "test_chained_exceptions")),
            ("testing/code/test_code.py::test_ne", ("testing/code/test_code.py", None, "test_ne")),
            ("a/t.py::test_x[1-2]", ("a/t.py", None, "test_x")),
            ("a/t.py::Outer::Inner::test_c", ("a/t.py", "Inner", "test_c")),
            ("a/t.py::Cls::test_c", ("a/t.py", "Cls", "test_c")),
        ]
        for test_id, expected in cases:
            with self.subTest(test_id=test_id):
                self.assertEqual(score.test_id_key("pytest-dev/pytest", test_id), expected)

    def test_vo10_a2_django_two_forms(self):
        cases = [
            ("test_get_choices_default_ordering (model_fields.tests.GetChoicesOrderingTests)",
             ("tests/model_fields/tests.py", "GetChoicesOrderingTests", "test_get_choices_default_ordering")),
            ("test_x (a.b.Cls.test_x)", ("tests/a/b.py", "Cls", "test_x")),
            ("test_y (a.b.c.Cls)", ("tests/a/b/c.py", "Cls", "test_y")),
            ("test_relatedfieldlistfilter_reverse_relationships_default_ordering (admin_filters.tests.ListFiltersTests)",
             ("tests/admin_filters/tests.py", "ListFiltersTests",
              "test_relatedfieldlistfilter_reverse_relationships_default_ordering")),
        ]
        for test_id, expected in cases:
            with self.subTest(test_id=test_id):
                self.assertEqual(score.test_id_key("django/django", test_id), expected)

    def test_vo10_a3_sympy_and_other_ids_have_no_file_or_class(self):
        self.assertEqual(score.test_id_key("sympy/sympy", "test_solve_modular"), (None, None, "test_solve_modular"))
        self.assertEqual(
            score.test_id_key("django/django", "RelatedFieldListFilter ordering respects Model.ordering."),
            (None, None, "RelatedFieldListFilter ordering respects Model.ordering."),
        )


class ChangedTestsTests(unittest.TestCase):
    def test_vo10_a4_new_file_returns_every_test(self):
        self.assertEqual(
            score.changed_tests(None, NEW_M),
            {("C", "test_a"), ("C", "test_b"), ("C", "test_new"), (None, "test_mod")},
        )

    def test_vo10_a5_a6_changed_new_and_unchanged_tests(self):
        self.assertEqual(
            score.changed_tests(BASE_M, NEW_M),
            {("C", "test_a"), ("C", "test_new"), (None, "test_mod")},
        )

    def test_vo10_a6_identical_text_changes_nothing(self):
        self.assertEqual(score.changed_tests(BASE_M, BASE_M), set())

    def test_vo10_a5_non_test_function_changes_are_ignored(self):
        changed_helper = BASE_M.replace("return 1", "return 99")
        self.assertEqual(score.changed_tests(BASE_M, changed_helper), set())

    def test_vo10_a5_module_level_functions(self):
        self.assertEqual(
            score.changed_tests(BASE_S, NEW_S), {(None, "test_one"), (None, "test_three")}
        )

    def test_vo10_a10_test_prefix_methods_and_async_functions_are_tests(self):
        source = (
            "class T:\n    def testFoo(self):\n        pass\n\n"
            "    async def test_m(self):\n        pass\n\n"
            "    def helper(self):\n        pass\n\n\n"
            "async def test_x():\n    pass\n\n\ndef other():\n    pass\n"
        )
        self.assertEqual(
            score.changed_tests(None, source), {("T", "testFoo"), ("T", "test_m"), (None, "test_x")}
        )
        changed = source.replace("def testFoo(self):\n        pass", "def testFoo(self):\n        return 1")
        changed = changed.replace("async def test_x():\n    pass", "async def test_x():\n    return 2")
        self.assertEqual(score.changed_tests(source, changed), {("T", "testFoo"), (None, "test_x")})

    def test_vo10_a7_unparsable_new_text_gives_none(self):
        self.assertIsNone(score.changed_tests(BASE_M, "def (:\n"))
        self.assertIsNone(score.changed_tests(None, "class :\n"))


class AttributeTests(unittest.TestCase):
    def test_vo10_a5_a6_a8_a9_django_ids(self):
        ids = [
            "test_a (m.C)", "test_b (m.C)", "test_new (m.C)", "test_a (m.D)",
            "test_a (other.C)", "A docstring test",
        ]
        result = score.attribute("django/django", ids, {"tests/m.py": (BASE_M, NEW_M)})
        self.assertEqual(result, {"test_a (m.C)", "test_new (m.C)"})

    def test_vo10_a5_a6_a8_a9_pytest_ids(self):
        ids = [
            "tests/m.py::C::test_a[1]", "tests/m.py::C::test_a[2]", "tests/m.py::C::test_b",
            "tests/m.py::C::test_new", "tests/m.py::D::test_a", "tests/other.py::C::test_a",
            "tests/m.py::test_mod", "tests/m.py::C::helper",
        ]
        result = score.attribute("pytest-dev/pytest", ids, {"tests/m.py": (BASE_M, NEW_M)})
        self.assertEqual(
            result,
            {
                "tests/m.py::C::test_a[1]", "tests/m.py::C::test_a[2]",
                "tests/m.py::C::test_new", "tests/m.py::test_mod",
            },
        )

    def test_vo10_a5_key_without_class_matches_any_class_with_the_same_function_name(self):
        ids = ["tests/m.py::test_a", "tests/m.py::test_b", "tests/m.py::test_new", "tests/other.py::test_a"]
        result = score.attribute("pytest-dev/pytest", ids, {"tests/m.py": (BASE_M, NEW_M)})
        self.assertEqual(result, {"tests/m.py::test_a", "tests/m.py::test_new"})

    def test_vo10_a3_file_less_key_matches_class_methods_in_any_touched_file(self):
        ids = ["test_new", "test_b", "test_mod", "test_other"]
        result = score.attribute("sympy/sympy", ids, {"tests/m.py": (BASE_M, NEW_M)})
        self.assertEqual(result, {"test_new", "test_mod"})

    def test_vo10_a3_ids_without_file_match_by_function_name(self):
        ids = ["test_one", "test_two", "test_three", "test_other"]
        result = score.attribute("sympy/sympy", ids, {"sympy/x/tests/test_m.py": (BASE_S, NEW_S)})
        self.assertEqual(result, {"test_one", "test_three"})

    def test_vo10_a4_new_file_attributes_all_its_tests(self):
        ids = ["tests/n.py::test_a", "tests/n.py::test_b", "tests/other.py::test_a"]
        result = score.attribute(
            "pytest-dev/pytest", ids, {"tests/n.py": (None, "def test_a():\n    pass\n\n\ndef test_b():\n    pass\n")}
        )
        self.assertEqual(result, {"tests/n.py::test_a", "tests/n.py::test_b"})

    def test_vo10_a7_unparsable_file_attributes_every_id_of_that_file_and_file_less_ids(self):
        ids = [
            "tests/m.py::C::test_a[1]", "tests/m.py::C::test_b", "tests/m.py::D::test_a",
            "tests/m.py::test_mod", "tests/other.py::C::test_a", "test_free",
        ]
        result = score.attribute("pytest-dev/pytest", ids, {"tests/m.py": (BASE_M, "def (:\n")})
        self.assertEqual(
            result,
            {
                "tests/m.py::C::test_a[1]", "tests/m.py::C::test_b", "tests/m.py::D::test_a",
                "tests/m.py::test_mod", "test_free",
            },
        )

    def test_vo10_a7_unparsable_file_in_django_repo(self):
        ids = ["test_a (m.C)", "test_a (other.C)", "A docstring test"]
        result = score.attribute("django/django", ids, {"tests/m.py": (BASE_M, "def (:\n")})
        self.assertEqual(result, {"test_a (m.C)", "A docstring test"})

    def test_vo10_no_touched_files_attributes_nothing(self):
        self.assertEqual(score.attribute("pytest-dev/pytest", ["t.py::test_a"], {}), set())
        self.assertEqual(score.attribute("pytest-dev/pytest", [], {"t.py": (BASE_M, NEW_M)}), set())

    def test_vo10_a8_other_touched_files_do_not_attribute_by_name(self):
        files = {"tests/m.py": (BASE_M, NEW_M), "tests/n.py": (None, "def test_n():\n    pass\n")}
        ids = ["tests/m.py::C::test_b", "tests/n.py::test_n", "tests/n.py::test_a"]
        self.assertEqual(score.attribute("pytest-dev/pytest", ids, files), {"tests/n.py::test_n"})


T1, T2, T3, T4 = "a.py::t1", "a.py::t2", "a.py::t3", "a.py::t4"


def after(status, **kwargs):
    return eval_result(status, **kwargs)


class SwtOutcomeTests(unittest.TestCase):
    def outcome(self, before, afters):
        result = score.swt_outcome(eval_result(before), afters)
        return {
            "applicable": result["applicable"],
            "success": result["success"],
            "f2p": sorted(result["f2p"]),
            "x2f": sorted(result["x2f"]),
        }

    def test_vo11_w1_success(self):
        got = self.outcome({T1: "FAILED", T2: "PASSED"}, [after({T1: "PASSED", T2: "PASSED"})] * 2)
        self.assertEqual(got, {"applicable": True, "success": True, "f2p": [T1], "x2f": []})

    def test_vo11_w1_three_after_runs(self):
        runs = [after({T1: "PASSED"})] * 3
        self.assertTrue(self.outcome({T1: "ERROR"}, runs)["success"])
        runs[-1] = after({T1: "FAILED"})
        got = self.outcome({T1: "ERROR"}, runs)
        self.assertEqual(got, {"applicable": True, "success": False, "f2p": [], "x2f": [T1]})

    def test_vo11_w2_no_fail_to_pass_test(self):
        got = self.outcome({T1: "PASSED", T2: "PASSED"}, [after({T1: "PASSED", T2: "PASSED"})] * 2)
        self.assertEqual(got, {"applicable": True, "success": False, "f2p": [], "x2f": []})

    def test_vo11_w3_pass_to_fail_blocks_success(self):
        got = self.outcome({T1: "FAILED", T2: "PASSED"}, [after({T1: "PASSED", T2: "FAILED"})] * 2)
        self.assertEqual(got, {"applicable": True, "success": False, "f2p": [T1], "x2f": [T2]})

    def test_vo11_w3_failing_before_and_after_counts_as_x2f(self):
        got = self.outcome({T1: "FAILED", T3: "FAILED"}, [after({T1: "PASSED", T3: "FAILED"})] * 2)
        self.assertEqual(got, {"applicable": True, "success": False, "f2p": [T1], "x2f": [T3]})

    def test_vo11_w3_test_absent_after_counts_as_x2f(self):
        got = self.outcome({T1: "FAILED", T4: "PASSED"}, [after({T1: "PASSED"})] * 2)
        self.assertEqual(got, {"applicable": True, "success": False, "f2p": [T1], "x2f": [T4]})

    def test_vo11_w4_flaky_after_run(self):
        for runs in (
            [after({T1: "PASSED"}), after({T1: "FAILED"})],
            [after({T1: "FAILED"}), after({T1: "PASSED"})],
        ):
            with self.subTest(first=runs[0]["status"][T1]):
                got = self.outcome({T1: "FAILED"}, runs)
                self.assertEqual(got, {"applicable": True, "success": False, "f2p": [], "x2f": [T1]})

    def test_vo11_w5_missing_before_counts_as_failing_before(self):
        got = self.outcome({T3: "PASSED"}, [after({T1: "PASSED", T3: "PASSED"})] * 2)
        self.assertEqual(got, {"applicable": True, "success": True, "f2p": [T1], "x2f": []})
        got = self.outcome({}, [after({T1: "PASSED"})] * 2)
        self.assertEqual(got, {"applicable": True, "success": True, "f2p": [T1], "x2f": []})

    def test_vo11_w6_skipped_after_is_excluded_and_skipped_before_is_neutral(self):
        before = {T1: "FAILED", T2: "FAILED", T3: "SKIPPED"}
        runs = [
            after({T1: "PASSED", T2: "SKIPPED", T3: "PASSED"}),
            after({T1: "PASSED", T2: "PASSED", T3: "PASSED"}),
        ]
        got = self.outcome(before, runs)
        self.assertEqual(got, {"applicable": True, "success": True, "f2p": [T1], "x2f": []})

    def test_vo11_w7_xfail_counts_as_pass(self):
        before = {T1: "FAILED", T2: "XFAIL"}
        runs = [after({T1: "XFAIL", T2: "PASSED"}), after({T1: "XFAIL", T2: "XFAIL"})]
        got = self.outcome(before, runs)
        self.assertEqual(got, {"applicable": True, "success": True, "f2p": [T1], "x2f": []})

    def test_vo11_w9_f2p_and_x2f_are_returned_sorted(self):
        ids = ["a.py::t%d" % n for n in (1, 2, 3)]
        losers = ["b.py::u%d" % n for n in (1, 2, 3)]
        before = {}
        for test in reversed(ids):
            before[test] = "FAILED"
        for test in reversed(losers):
            before[test] = "PASSED"
        run = {}
        for test in reversed(ids):
            run[test] = "PASSED"
        for test in reversed(losers):
            run[test] = "FAILED"
        result = score.swt_outcome(eval_result(before), [after(dict(run)), after(dict(run))])
        self.assertEqual(list(before), sorted(ids, reverse=True) + sorted(losers, reverse=True))
        self.assertEqual(result["f2p"], ids)
        self.assertEqual(result["x2f"], losers)
        self.assertIs(result["success"], False)

    def test_vo11_w8_not_applicable_when_an_after_run_is_unusable(self):
        good = after({T1: "PASSED"})
        bad_runs = {
            "src_failed": after({T1: "PASSED"}, apply="src_failed"),
            "test_failed": after({T1: "PASSED"}, apply="test_failed"),
            "no_tests": after({T1: "PASSED"}, no_tests=True),
            "empty_status": after({}),
        }
        for name, bad in bad_runs.items():
            for position in (0, 1):
                with self.subTest(case=name, position=position):
                    runs = [good, good]
                    runs[position] = bad
                    result = score.swt_outcome(eval_result({T1: "FAILED"}), runs)
                    self.assertIs(result["applicable"], False)
                    self.assertIs(result["success"], False)
                    self.assertEqual(result["f2p"], [])
                    self.assertEqual(result["x2f"], [])


IID = "pytest-dev__pytest-9999"
GOLD_SRC = "GOLD-SRC-PATCH"
GOLD_TESTS = "GOLD-TEST-PATCH"
AGENT_SRC = "AGENT-SRC-DIFF"
F2P_1, F2P_2, F2P_3 = "t/test_gold.py::test_f1", "t/test_gold.py::test_f2", "t/test_gold.py::test_f3"
P_EFF, P_FLAKY = "t/test_gold.py::test_eff", "t/test_gold.py::test_flaky"
ZPATH, APATH = "tests/test_zagent.py", "tests/test_agent.py"
AGENT_BASE = "def test_keep():\n    assert 1 == 1\n\n\ndef test_chg():\n    assert 1 == 1\n"
AGENT_NEW = (
    "def test_keep():\n    assert 1 == 1\n\n\ndef test_chg():\n    assert 1 == 2\n\n\n"
    "def test_new():\n    assert True\n\n\ndef test_missing():\n    assert True\n\n\n"
    "def test_err():\n    assert True\n\n\ndef test_fail():\n    assert True\n"
)
Z_NEW = "def test_z_new():\n    assert True\n"
TP_Z = git_diff({}, {ZPATH: Z_NEW})
TP_AGENT = git_diff({APATH: AGENT_BASE}, {APATH: AGENT_NEW})
AGENT_TP = TP_Z + TP_AGENT
ZID = ZPATH + "::test_z_new"
AID, BID, CID = APATH + "::test_new", APATH + "::test_chg", APATH + "::test_keep"
MID, EID, FID = APATH + "::test_missing", APATH + "::test_err", APATH + "::test_fail"

HELPER_BASE = "def helper():\n    return 1\n\n\ndef test_keep():\n    assert helper()\n"
HELPER_NEW = "def helper():\n    return 2\n\n\ndef test_keep():\n    assert helper()\n"
HELPER_TP = git_diff({APATH: HELPER_BASE}, {APATH: HELPER_NEW})


def impl_result(**changes):
    status = {F2P_1: "PASSED", F2P_2: "XFAIL", F2P_3: "PASSED", P_EFF: "PASSED", P_FLAKY: "FAILED"}
    for name, value in changes.items():
        if value is None:
            status.pop(name)
        else:
            status[name] = value
    return eval_result(status)


def before_result():
    return eval_result({ZID: "FAILED", AID: "FAILED", BID: "FAILED", CID: "PASSED", MID: "FAILED",
                        EID: "FAILED", FID: "FAILED"})


def after_results(logs=(None, None)):
    first = eval_result(
        {ZID: "PASSED", AID: "PASSED", BID: "PASSED", CID: "PASSED", EID: "ERROR", FID: "FAILED"},
        log_path=logs[0],
    )
    second = eval_result(
        {ZID: "PASSED", AID: "PASSED", BID: "XFAIL", CID: "PASSED", EID: "ERROR", FID: "FAILED", MID: "PASSED"},
        log_path=logs[1],
    )
    return first, second


def mutant_status(**changes):
    status = {ZID: "PASSED", AID: "PASSED", BID: "PASSED", CID: "PASSED", EID: "ERROR", FID: "FAILED", MID: "PASSED"}
    for name, value in changes.items():
        key = {"z": ZID, "a": AID, "b": BID, "c": CID, "m": MID, "e": EID, "f": FID}[name]
        if value is None:
            status.pop(key)
        else:
            status[key] = value
    return eval_result(status)


def mutant(index, compile_ok=True, killed=False):
    return {"id": "m%d" % index, "path": "src/x.py", "patch": "MUT-%d" % index,
            "compile_ok": compile_ok, "killed": killed, "timeout": False}


MAIN_MUTANTS = [mutant(1, killed=True), mutant(2, killed=True), mutant(3, killed=True), mutant(4), mutant(5)]
MAIN_MUTANT_RESULTS = {
    "MUT-1": mutant_status(a="FAILED"),
    "MUT-2": mutant_status(),
    "MUT-3": mutant_status(),
    "MUT-4": eval_result({}, timed_out=True),
    "MUT-5": mutant_status(c="FAILED", m="FAILED"),
}


class ScoreHarness:
    def __init__(self, test_patch=AGENT_TP, mutants=None, mutant_results=None, impl=None,
                 before=None, afters=None, base_texts=None):
        self.instance = {
            "instance_id": IID, "repo": "pytest-dev/pytest", "patch": GOLD_SRC, "test_patch": GOLD_TESTS,
            "FAIL_TO_PASS": [F2P_1, F2P_2, F2P_3], "PASS_TO_PASS": [P_EFF, P_FLAKY],
        }
        self.validation = {
            "f2p": [F2P_1, F2P_2, F2P_3], "p2p_effective": [P_EFF], "p2p_flaky": [P_FLAKY], "p2p_broken": [],
        }
        self.prediction = {"instance_id": IID, "src_diff": AGENT_SRC, "test_patch": test_patch}
        self.mutants = list(MAIN_MUTANTS if mutants is None else mutants)
        self.mutant_results = MAIN_MUTANT_RESULTS if mutant_results is None else mutant_results
        self.impl = impl or impl_result()
        self.before = before or before_result()
        self.afters = afters or after_results()
        self.log = []
        self.evaluate = FakeEvaluate(self.respond, log=self.log)
        texts = {ZPATH: None, APATH: AGENT_BASE} if base_texts is None else base_texts
        self.read_files = FakeReadFiles(texts, log=self.log)

    def respond(self, instance, src_diff, test_patch, **kwargs):
        if src_diff == AGENT_SRC + self.prediction["test_patch"] and test_patch == GOLD_TESTS and not kwargs:
            return self.impl
        if src_diff == "" and test_patch == self.prediction["test_patch"] and not kwargs:
            return self.before
        if src_diff == GOLD_SRC and test_patch == self.prediction["test_patch"] and "repeat" in kwargs:
            return self.afters[kwargs["repeat"]]
        if src_diff.startswith("MUT-") and test_patch == self.prediction["test_patch"] and not kwargs:
            return self.mutant_results[src_diff]
        raise AssertionError("unexpected evaluate call %r" % ((src_diff, test_patch, kwargs),))

    def run(self, workers=1):
        return score.score_prediction(
            self.instance, self.prediction, validation=self.validation, mutants=self.mutants,
            evaluate_fn=self.evaluate, read_files_fn=self.read_files, workers=workers,
        )


def normalized(result):
    result = copy.deepcopy(result)
    for key in ("agent_tests", "agent_tests_ok"):
        result[key] = sorted(result[key])
    for key in ("f2p", "x2f"):
        result["swt"][key] = sorted(result["swt"][key])
    return result


class ScoreTestCase(unittest.TestCase):
    def assertScore(self, actual, expected, path="score"):
        if isinstance(expected, dict):
            self.assertEqual(set(actual), set(expected), path)
            for key, value in expected.items():
                self.assertScore(actual[key], value, "%s.%s" % (path, key))
        elif isinstance(expected, float):
            self.assertIsInstance(actual, float, path)
            self.assertAlmostEqual(actual, expected, places=9, msg=path)
        else:
            self.assertEqual(actual, expected, path)


MAIN_EXPECTED = {
    "instance_id": IID,
    "resolved": True,
    "f2p_frac": 1.0,
    "src_apply": "ok",
    "swt": {"applicable": True, "success": False, "f2p": sorted([AID, BID, ZID]), "x2f": sorted([EID, FID, MID])},
    "agent_tests": sorted([ZID, AID, BID, MID, EID, FID]),
    "agent_tests_ok": sorted([ZID, AID, BID]),
    "incompatible_frac": 0.5,
    "incompatible": {"missing": 1, "error": 1, "failed": 1},
    "api_mismatch_suspected": False,
    "kill": {
        "sampled": 5, "killed": 2, "primary": 0.4, "d_ref": 3, "killed_in_d_ref": 1,
        "secondary": 1 / 3, "gold_reference": 0.6, "timeouts": 1,
    },
    "evaluations": 9,
}


class ScorePredictionMainTests(ScoreTestCase):
    def test_vo12_f1_to_f6_full_score_for_hand_built_scenario(self):
        harness = ScoreHarness()
        self.assertScore(normalized(harness.run()), MAIN_EXPECTED)

    def test_vo12_worker_count_does_not_change_the_result(self):
        for workers in (1, 3):
            with self.subTest(workers=workers):
                self.assertScore(normalized(ScoreHarness().run(workers=workers)), MAIN_EXPECTED)

    def test_vo12_f3_call_order_and_count(self):
        for workers in (1, 3):
            with self.subTest(workers=workers):
                harness = ScoreHarness()
                result = harness.run(workers=workers)
                self.assertEqual(
                    harness.log[:5],
                    [
                        ("evaluate", AGENT_SRC + AGENT_TP, GOLD_TESTS, {}),
                        ("evaluate", "", AGENT_TP, {}),
                        ("evaluate", GOLD_SRC, AGENT_TP, {"repeat": 0}),
                        ("evaluate", GOLD_SRC, AGENT_TP, {"repeat": 1}),
                        ("read_files", "", [ZPATH, APATH]),
                    ],
                )
                rest = harness.log[5:]
                self.assertEqual(
                    sorted(rest, key=lambda entry: entry[1]),
                    [("evaluate", "MUT-%d" % n, AGENT_TP, {}) for n in range(1, 6)],
                )
                self.assertEqual(len(harness.evaluate.calls), 9)
                self.assertEqual(result["evaluations"], 9)

    def test_vo12_f3_base_text_is_read_once_for_all_test_patch_paths(self):
        harness = ScoreHarness()
        harness.run()
        self.assertEqual(harness.read_files.calls, [("", [ZPATH, APATH])])


class ResolvedTests(ScoreTestCase):
    def run_with(self, impl):
        harness = ScoreHarness(test_patch="", impl=impl)
        result = harness.run()
        self.assertEqual(harness.evaluate.calls, [(AGENT_SRC, GOLD_TESTS, {})])
        self.assertEqual(harness.read_files.calls, [])
        return result

    def test_vo12_f1_f2_resolved_and_f2p_fraction_causes(self):
        cases = [
            ("all_pass", impl_result(), True, 1.0),
            ("one_f2p_failed", impl_result(**{F2P_3: "FAILED"}), False, 2 / 3),
            ("one_f2p_missing", impl_result(**{F2P_3: None}), False, 2 / 3),
            ("one_f2p_skipped", impl_result(**{F2P_3: "SKIPPED"}), False, 2 / 3),
            ("one_f2p_error", impl_result(**{F2P_1: "ERROR"}), False, 2 / 3),
            ("two_f2p_failed", impl_result(**{F2P_1: "FAILED", F2P_3: "FAILED"}), False, 1 / 3),
            ("effective_p2p_failed", impl_result(**{P_EFF: "FAILED"}), False, 1.0),
            ("effective_p2p_missing", impl_result(**{P_EFF: None}), False, 1.0),
            ("flaky_p2p_failing_is_ignored", impl_result(**{P_FLAKY: "FAILED"}), True, 1.0),
            ("flaky_p2p_missing_is_ignored", impl_result(**{P_FLAKY: None}), True, 1.0),
            ("xfail_f2p_is_pass", impl_result(**{F2P_3: "XFAIL"}), True, 1.0),
        ]
        for name, impl, resolved, fraction in cases:
            with self.subTest(case=name):
                result = self.run_with(impl)
                self.assertIs(result["resolved"], resolved)
                self.assertAlmostEqual(result["f2p_frac"], fraction, places=9)
                self.assertEqual(result["src_apply"], "ok")

    def test_vo12_f1_src_apply_failure_is_not_resolved(self):
        failed = eval_result({}, apply="src_failed")
        result = self.run_with(failed)
        self.assertIs(result["resolved"], False)
        self.assertEqual(result["src_apply"], "src_failed")
        self.assertEqual(result["f2p_frac"], 0.0)

    def test_vo12_f1_inconsistent_apply_flag_wins_over_passing_statuses(self):
        inconsistent = impl_result()
        inconsistent["apply"] = "src_failed"
        result = self.run_with(inconsistent)
        self.assertIs(result["resolved"], False)

    def test_vo12_f8_complete_default_score_dict_for_empty_test_patch(self):
        harness = ScoreHarness(test_patch="")
        self.assertScore(
            normalized(harness.run()),
            {
                "instance_id": IID, "resolved": True, "f2p_frac": 1.0, "src_apply": "ok",
                "swt": {"applicable": False, "success": False, "f2p": [], "x2f": []},
                "agent_tests": [], "agent_tests_ok": [], "incompatible_frac": None,
                "incompatible": {"missing": 0, "error": 0, "failed": 0},
                "api_mismatch_suspected": False,
                "kill": {"sampled": 5, "killed": 0, "primary": 0.0, "d_ref": 3, "killed_in_d_ref": 0,
                         "secondary": 0.0, "gold_reference": 0.6, "timeouts": 0},
                "evaluations": 1,
            },
        )

    def test_vo12_f8_empty_test_patch_skips_everything_after_the_first_run(self):
        result = self.run_with(impl_result())
        self.assertIs(result["swt"]["applicable"], False)
        self.assertIs(result["swt"]["success"], False)
        self.assertEqual(result["evaluations"], 1)
        self.assertEqual(result["agent_tests"], [])
        self.assertEqual(result["agent_tests_ok"], [])
        self.assertIsNone(result["incompatible_frac"])
        for key in ("killed", "killed_in_d_ref", "timeouts"):
            self.assertEqual(result["kill"][key], 0, key)
        self.assertIs(result["api_mismatch_suspected"], False)
        self.assertEqual(result["swt"]["f2p"], [])
        self.assertEqual(result["swt"]["x2f"], [])
        self.assertEqual(
            result["kill"],
            {"sampled": 5, "killed": 0, "primary": 0.0, "d_ref": 3, "killed_in_d_ref": 0,
             "secondary": 0.0, "gold_reference": 0.6, "timeouts": 0},
        )


class AgentTestClassificationTests(ScoreTestCase):
    def test_vo12_f4_helper_only_patch_has_no_agent_tests_and_skips_mutants(self):
        harness = ScoreHarness(test_patch=HELPER_TP, base_texts={APATH: HELPER_BASE})
        result = harness.run()
        self.assertEqual(result["agent_tests"], [])
        self.assertEqual(result["agent_tests_ok"], [])
        self.assertIsNone(result["incompatible_frac"])
        self.assertEqual(result["incompatible"], {"missing": 0, "error": 0, "failed": 0})
        self.assertEqual(len(harness.evaluate.calls), 4)
        self.assertEqual(result["evaluations"], 4)
        self.assertScore(
            result["kill"],
            {"sampled": 5, "killed": 0, "primary": 0.0, "d_ref": 3, "killed_in_d_ref": 0,
             "secondary": 0.0, "gold_reference": 0.6, "timeouts": 0},
        )

    def test_vo12_f7_mutants_skipped_when_no_agent_test_is_ok(self):
        afters = (
            eval_result({AID: "FAILED", BID: "ERROR", CID: "PASSED"}),
            eval_result({AID: "FAILED", BID: "ERROR", CID: "PASSED"}),
        )
        before = eval_result({AID: "FAILED", BID: "FAILED", CID: "PASSED"})
        harness = ScoreHarness(test_patch=TP_AGENT, afters=afters, before=before, base_texts={APATH: AGENT_BASE})
        result = harness.run()
        self.assertEqual(result["agent_tests_ok"], [])
        self.assertNotEqual(result["agent_tests"], [])
        self.assertEqual(result["incompatible"]["failed"], 1)
        self.assertEqual(result["incompatible"]["error"], 1)
        self.assertEqual(len(harness.evaluate.calls), 4)
        self.assertEqual(result["evaluations"], 4)
        self.assertScore(
            result["kill"],
            {"sampled": 5, "killed": 0, "primary": 0.0, "d_ref": 3, "killed_in_d_ref": 0,
             "secondary": 0.0, "gold_reference": 0.6, "timeouts": 0},
        )

    def test_vo12_f4_test_passing_only_in_one_after_run_is_not_ok(self):
        afters = (
            eval_result({AID: "PASSED", BID: "PASSED", CID: "PASSED"}),
            eval_result({AID: "PASSED", BID: "FAILED", CID: "PASSED"}),
        )
        before = eval_result({AID: "FAILED", BID: "FAILED", CID: "PASSED"})
        harness = ScoreHarness(test_patch=TP_AGENT, afters=afters, before=before, mutants=[],
                               base_texts={APATH: AGENT_BASE})
        result = harness.run()
        self.assertEqual(sorted(result["agent_tests_ok"]), [AID])
        self.assertEqual(sorted(result["agent_tests"]), sorted([AID, BID]))
        self.assertEqual(result["incompatible"], {"missing": 0, "error": 0, "failed": 1})
        self.assertAlmostEqual(result["incompatible_frac"], 0.5, places=9)

    def test_vo12_f4_status_ids_come_from_before_and_both_after_runs(self):
        before = eval_result({AID: "FAILED", BID: "FAILED"})
        afters = (eval_result({CID: "PASSED"}), eval_result({CID: "PASSED", MID: "PASSED"}))
        harness = ScoreHarness(test_patch=TP_AGENT, afters=afters, before=before, mutants=[],
                               base_texts={APATH: AGENT_BASE})
        result = harness.run()
        self.assertEqual(sorted(result["agent_tests"]), sorted([AID, BID, MID]))
        self.assertEqual(result["agent_tests_ok"], [])
        self.assertEqual(result["incompatible"], {"missing": 3, "error": 0, "failed": 0})


class UnappliableTestPatchTests(ScoreTestCase):
    def test_vo12_f9_test_patch_that_does_not_apply_to_base_texts(self):
        harness = ScoreHarness(base_texts={ZPATH: None, APATH: "completely different\ncontent\n"})
        result = harness.run()
        self.assertEqual(result["agent_tests"], [])
        self.assertEqual(result["agent_tests_ok"], [])
        self.assertEqual(result["incompatible"], {"missing": 0, "error": 0, "failed": 0})
        self.assertIsNone(result["incompatible_frac"])
        self.assertEqual(len(harness.evaluate.calls), 4)
        self.assertEqual(result["evaluations"], 4)
        self.assertScore(
            result["kill"],
            {"sampled": 5, "killed": 0, "primary": 0.0, "d_ref": 3, "killed_in_d_ref": 0,
             "secondary": 0.0, "gold_reference": 0.6, "timeouts": 0},
        )
        self.assertScore(normalized(result)["swt"], MAIN_EXPECTED["swt"])
        self.assertIs(result["resolved"], True)


class ApiMismatchTests(ScoreTestCase):
    def flag(self, logs, tmp):
        paths = []
        for index, text in enumerate(logs):
            if text is None:
                paths.append(None)
                continue
            path = os.path.join(tmp, "log%d.txt" % index)
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(text)
            paths.append(path)
        harness = ScoreHarness(mutants=[], afters=after_results(tuple(paths)))
        return harness.run()["api_mismatch_suspected"]

    def test_vo12_f5_each_token_in_either_after_log(self):
        with tempfile.TemporaryDirectory() as tmp:
            for token in ("ImportError", "ModuleNotFoundError", "AttributeError", "NameError"):
                for position in (0, 1):
                    with self.subTest(token=token, position=position):
                        logs = [None, None]
                        logs[position] = "setup\nE   %s: no module named x\ndone\n" % token
                        self.assertIs(self.flag(logs, tmp), True)

    def test_vo12_f10_log_with_invalid_utf8_is_still_scanned(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "binary.log")
            with open(path, "wb") as handle:
                handle.write(b"\xff\xfe garbage \x80\x81\nE   ImportError: boom\n\xc3(\n")
            harness = ScoreHarness(mutants=[], afters=after_results((path, None)))
            self.assertIs(harness.run()["api_mismatch_suspected"], True)
            clean = os.path.join(tmp, "clean.log")
            with open(clean, "wb") as handle:
                handle.write(b"\xff\xfe nothing relevant \x80\n")
            harness = ScoreHarness(mutants=[], afters=after_results((clean, None)))
            self.assertIs(harness.run()["api_mismatch_suspected"], False)

    def test_vo12_f5_clean_missing_and_before_logs_do_not_set_the_flag(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIs(self.flag(["all good\n", "AssertionError only\n"], tmp), False)
            self.assertIs(self.flag([None, None], tmp), False)
            self.assertIs(self.flag(["TypeError: x\n", None], tmp), False)

    def test_vo12_f5_before_and_impl_logs_are_not_inspected(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad = os.path.join(tmp, "bad.txt")
            with open(bad, "w", encoding="utf-8") as handle:
                handle.write("ImportError\nNameError\n")
            before = before_result()
            before["log_path"] = bad
            impl = impl_result()
            impl["log_path"] = bad
            harness = ScoreHarness(mutants=[], before=before, impl=impl)
            self.assertIs(harness.run()["api_mismatch_suspected"], False)


class KillRateTests(ScoreTestCase):
    def kill(self, mutants, results):
        harness = ScoreHarness(mutants=mutants, mutant_results=results)
        return harness.run()["kill"], harness

    def test_vo12_f6_empty_d_ref_leaves_secondary_none(self):
        mutants = [mutant(1), mutant(2), mutant(3)]
        results = {"MUT-1": mutant_status(a="FAILED"), "MUT-2": mutant_status(), "MUT-3": mutant_status()}
        kill, _ = self.kill(mutants, results)
        self.assertEqual(kill["killed"], 1)
        self.assertEqual(kill["d_ref"], 0)
        self.assertEqual(kill["killed_in_d_ref"], 0)
        self.assertAlmostEqual(kill["primary"], 1 / 3, places=9)
        self.assertIsNone(kill["secondary"])
        self.assertEqual(kill["gold_reference"], 0.0)

    def test_vo12_f6_no_mutants_leaves_primary_and_secondary_none(self):
        kill, harness = self.kill([], {})
        self.assertIsNone(kill["primary"])
        self.assertIsNone(kill["secondary"])
        self.assertEqual(kill["killed"], 0)
        self.assertEqual(len(harness.evaluate.calls), 4)

    def test_vo12_f6_compile_invalid_mutants_leave_every_denominator(self):
        mutants = [mutant(1, killed=True), mutant(2), mutant(3, compile_ok=False), mutant(4, compile_ok=False)]
        results = {"MUT-1": mutant_status(a="FAILED"), "MUT-2": mutant_status()}
        kill, harness = self.kill(mutants, results)
        self.assertEqual(kill["killed"], 1)
        self.assertEqual(kill["d_ref"], 1)
        self.assertEqual(kill["killed_in_d_ref"], 1)
        self.assertAlmostEqual(kill["primary"], 0.5, places=9)
        self.assertAlmostEqual(kill["secondary"], 1.0, places=9)
        self.assertAlmostEqual(kill["gold_reference"], 0.5, places=9)
        evaluated = sorted(call[0] for call in harness.evaluate.calls if call[0].startswith("MUT-"))
        self.assertEqual(evaluated, ["MUT-1", "MUT-2"])
        self.assertEqual(len(harness.evaluate.calls), 6)

    def test_vo12_f12_zero_compile_valid_mutants_leave_every_ratio_none(self):
        invalid = [mutant(1, compile_ok=False, killed=True), mutant(2, compile_ok=False), mutant(3, compile_ok=False)]
        for name, mutants in (("empty_list", []), ("only_compile_invalid", invalid)):
            with self.subTest(case=name):
                kill, harness = self.kill(mutants, {})
                self.assertIsNone(kill["gold_reference"])
                self.assertIsNone(kill["primary"])
                self.assertIsNone(kill["secondary"])
                self.assertEqual(kill["sampled"], 0)
                self.assertEqual(kill["d_ref"], 0)
                self.assertEqual(kill["killed"], 0)
                self.assertEqual(len(harness.evaluate.calls), 4)

    def test_vo12_f12_zero_compile_valid_mutants_when_step_5_is_skipped(self):
        afters = (
            eval_result({AID: "FAILED", BID: "ERROR", CID: "PASSED"}),
            eval_result({AID: "FAILED", BID: "ERROR", CID: "PASSED"}),
        )
        before = eval_result({AID: "FAILED", BID: "FAILED", CID: "PASSED"})
        invalid = [mutant(1, compile_ok=False, killed=True), mutant(2, compile_ok=False)]
        for name, mutants in (("empty_list", []), ("only_compile_invalid", invalid)):
            with self.subTest(case=name):
                harness = ScoreHarness(test_patch=TP_AGENT, afters=afters, before=before,
                                       base_texts={APATH: AGENT_BASE}, mutants=mutants)
                result = harness.run()
                self.assertEqual(result["agent_tests_ok"], [])
                kill = result["kill"]
                self.assertIsNone(kill["gold_reference"])
                self.assertIsNone(kill["primary"])
                self.assertIsNone(kill["secondary"])
                self.assertEqual((kill["sampled"], kill["d_ref"]), (0, 0))

    def test_vo12_f11_sampled_counts_only_compile_valid_mutants_when_step_5_runs(self):
        mutants = [mutant(1, killed=True), mutant(2), mutant(3, compile_ok=False, killed=True),
                   mutant(4, compile_ok=False), mutant(5, compile_ok=False)]
        results = {"MUT-1": mutant_status(a="FAILED"), "MUT-2": mutant_status()}
        kill, _ = self.kill(mutants, results)
        self.assertEqual(kill["sampled"], 2)
        self.assertEqual(kill["killed"], 1)
        self.assertAlmostEqual(kill["primary"], 0.5, places=9)
        self.assertEqual(kill["d_ref"], 1)
        self.assertAlmostEqual(kill["gold_reference"], 0.5, places=9)

    def test_vo12_f11_sampled_counts_only_compile_valid_mutants_when_step_5_is_skipped(self):
        afters = (
            eval_result({AID: "FAILED", BID: "ERROR", CID: "PASSED"}),
            eval_result({AID: "FAILED", BID: "ERROR", CID: "PASSED"}),
        )
        before = eval_result({AID: "FAILED", BID: "FAILED", CID: "PASSED"})
        mutants = [mutant(1, killed=True), mutant(2), mutant(3, compile_ok=False, killed=True),
                   mutant(4, compile_ok=False), mutant(5, compile_ok=False)]
        harness = ScoreHarness(test_patch=TP_AGENT, afters=afters, before=before,
                               base_texts={APATH: AGENT_BASE}, mutants=mutants)
        result = harness.run()
        self.assertEqual(result["agent_tests_ok"], [])
        self.assertScore(
            result["kill"],
            {"sampled": 2, "killed": 0, "primary": 0.0, "d_ref": 1, "killed_in_d_ref": 0,
             "secondary": 0.0, "gold_reference": 0.5, "timeouts": 0},
        )

    def test_vo12_f6_kill_means_timeout_or_an_ok_agent_test_not_passing(self):
        mutants = [mutant(n) for n in range(1, 8)]
        results = {
            "MUT-1": mutant_status(b=None),
            "MUT-2": mutant_status(b="XFAIL"),
            "MUT-3": mutant_status(b="SKIPPED"),
            "MUT-4": mutant_status(z="ERROR"),
            "MUT-5": mutant_status(m="FAILED", e="PASSED", f="PASSED", c="FAILED"),
            "MUT-6": {**mutant_status(), "timed_out": True},
            "MUT-7": mutant_status(),
        }
        kill, _ = self.kill(mutants, results)
        self.assertEqual(kill["killed"], 4)
        self.assertEqual(kill["timeouts"], 1)
        self.assertAlmostEqual(kill["primary"], 4 / 7, places=9)

    def test_vo12_f6_kills_inside_d_ref_are_counted_separately(self):
        mutants = [mutant(1, killed=True), mutant(2, killed=True), mutant(3), mutant(4)]
        results = {
            "MUT-1": mutant_status(a="FAILED"),
            "MUT-2": mutant_status(),
            "MUT-3": mutant_status(a="FAILED"),
            "MUT-4": mutant_status(b="FAILED"),
        }
        kill, _ = self.kill(mutants, results)
        self.assertEqual(kill["killed"], 3)
        self.assertEqual(kill["d_ref"], 2)
        self.assertEqual(kill["killed_in_d_ref"], 1)
        self.assertAlmostEqual(kill["secondary"], 0.5, places=9)
        self.assertAlmostEqual(kill["primary"], 0.75, places=9)
        self.assertAlmostEqual(kill["gold_reference"], 0.5, places=9)


if __name__ == "__main__":
    unittest.main()

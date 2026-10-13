import ast
import copy
import unittest

from selfcheck import calibrate
from selfcheck.tests.helpers import FakeReadFiles, git_apply_files, git_diff


def normalize(source):
    tree = ast.parse(source)
    tree.body = [
        node for node in tree.body
        if not (isinstance(node, ast.Import) and [alias.name for alias in node.names] == ["contextlib"])
    ]
    return ast.dump(tree)


def has_contextlib_import(source):
    return any(
        isinstance(node, ast.Import) and [alias.name for alias in node.names] == ["contextlib"]
        for node in ast.parse(source).body
    )


class StripAssertionsTests(unittest.TestCase):
    def check(self, source, expected):
        stripped = calibrate.strip_assertions(source)
        self.assertEqual(normalize(stripped), normalize(expected))
        return stripped

    def test_vo13_s1_assert_statement_becomes_expression(self):
        self.check("def test_a():\n    assert x == 1\n", "def test_a():\n    x == 1\n")

    def test_vo13_s2_assert_with_message_drops_the_message(self):
        self.check("def test_a():\n    assert x == 1, 'msg'\n", "def test_a():\n    x == 1\n")

    def test_vo13_s3_assert_method_call_becomes_tuple_of_arguments(self):
        self.check(
            "class T:\n    def test_a(self):\n        self.assertEqual(a, b)\n        self.assertTrue(x)\n",
            "class T:\n    def test_a(self):\n        (a, b)\n        (x,)\n",
        )

    def test_vo13_s4_assert_function_call_becomes_tuple_of_arguments(self):
        self.check(
            "def test_a():\n    assert_equal(a, b)\n    np.testing.assert_allclose(a, b)\n",
            "def test_a():\n    (a, b)\n    (a, b)\n",
        )

    def test_vo13_s3_other_calls_and_statements_are_untouched(self):
        source = "def test_a():\n    foo(a)\n    self.helper(a)\n    assertion(x)\n    y = 1\n"
        self.check(source, source)

    def test_vo13_s5_with_pytest_raises_becomes_suppress(self):
        stripped = self.check(
            "def test_a():\n    with pytest.raises(ValueError):\n        f()\n",
            "def test_a():\n    with contextlib.suppress(BaseException):\n        f()\n",
        )
        self.assertTrue(has_contextlib_import(stripped))

    def test_vo13_s6_assert_raises_and_warns_with_items_become_suppress(self):
        cases = [
            "with self.assertRaises(ValueError):",
            "with self.assertRaisesRegex(ValueError, 'x'):",
            "with self.assertWarns(UserWarning):",
            "with self.assertWarnsRegex(UserWarning, 'x'):",
            "with pytest.warns(UserWarning):",
            "with pytest.raises(ValueError, match='x'):",
        ]
        for header in cases:
            with self.subTest(header=header):
                stripped = self.check(
                    "def test_a(self):\n    %s\n        f()\n" % header,
                    "def test_a(self):\n    with contextlib.suppress(BaseException):\n        f()\n",
                )
                self.assertTrue(has_contextlib_import(stripped))

    def test_vo13_s6_only_the_raising_item_is_replaced(self):
        self.check(
            "def test_a():\n    with pytest.raises(E), open(p) as g:\n        f()\n",
            "def test_a():\n    with contextlib.suppress(BaseException), open(p) as g:\n        f()\n",
        )

    def test_vo13_s6_other_context_managers_are_untouched(self):
        source = "def test_a():\n    with open(p) as g:\n        f()\n"
        self.check(source, source)

    def test_vo13_s5_contextlib_import_goes_after_docstring_and_future_imports(self):
        source = (
            '"""module doc"""\n'
            "from __future__ import annotations\n"
            "import pytest\n\n\n"
            "def test_a():\n    with pytest.raises(ValueError):\n        f()\n"
        )
        body = ast.parse(calibrate.strip_assertions(source)).body
        self.assertIsInstance(body[0], ast.Expr)
        self.assertIsInstance(body[1], ast.ImportFrom)
        self.assertEqual(body[1].module, "__future__")
        self.assertIsInstance(body[2], ast.Import)
        self.assertEqual([alias.name for alias in body[2].names], ["contextlib"])
        self.assertIsInstance(body[3], ast.Import)
        self.assertEqual([alias.name for alias in body[3].names], ["pytest"])

    def test_vo13_s5_contextlib_import_is_first_without_docstring(self):
        body = ast.parse(
            calibrate.strip_assertions("import pytest\n\n\ndef test_a():\n    with pytest.warns(W):\n        f()\n")
        ).body
        self.assertEqual([alias.name for alias in body[0].names], ["contextlib"])

    def test_vo13_s1_no_contextlib_import_without_a_replaced_with_item(self):
        for source in (
            "def test_a():\n    assert x\n    self.assertEqual(a, b)\n",
            "def test_a():\n    with open(p) as g:\n        f()\n",
        ):
            with self.subTest(source=source):
                self.assertFalse(has_contextlib_import(calibrate.strip_assertions(source)))
                self.assertNotIn("contextlib", calibrate.strip_assertions(source))

    def test_vo13_s7_output_parses_for_mixed_source(self):
        source = (
            "import pytest\n\n\n"
            "class T(unittest.TestCase):\n"
            "    def test_a(self):\n"
            "        assert f(1) == 2, 'bad'\n"
            "        self.assertEqual(f(2), 3)\n"
            "        with self.assertRaises(ValueError):\n"
            "            f(-1)\n\n"
            "def test_b():\n"
            "    assert_equal(1, 1)\n"
            "    with pytest.raises(KeyError):\n"
            "        {}['x']\n"
        )
        expected = (
            "import pytest\n\n\n"
            "class T(unittest.TestCase):\n"
            "    def test_a(self):\n"
            "        f(1) == 2\n"
            "        (f(2), 3)\n"
            "        with contextlib.suppress(BaseException):\n"
            "            f(-1)\n\n"
            "def test_b():\n"
            "    (1, 1)\n"
            "    with contextlib.suppress(BaseException):\n"
            "        {}['x']\n"
        )
        stripped = self.check(source, expected)
        ast.parse(stripped)
        self.assertTrue(has_contextlib_import(stripped))
        self.assertNotIn("assert ", stripped)


TEST_A = "tests/test_a.py"
TEST_B = "tests/test_b.py"
BASE_A = "def test_old():\n    assert 1 == 1\n"
POST_A = "def test_old():\n    assert 1 == 1\n\n\ndef test_new():\n    assert f(2) == 3, 'msg'\n"
BASE_B = "import pytest\n\n\ndef test_b():\n    with pytest.raises(ValueError):\n        int('x')\n"
POST_B = BASE_B + "\n\ndef test_b2():\n    assert_equal(1, 1)\n"
STRIPPED_A = "def test_old():\n    1 == 1\n\n\ndef test_new():\n    f(2) == 3\n"
STRIPPED_B = (
    "import pytest\n\n\ndef test_b():\n    with contextlib.suppress(BaseException):\n        int('x')\n\n\n"
    "def test_b2():\n    (1, 1)\n"
)
GOLD_TEST_PATCH = git_diff({TEST_A: BASE_A, TEST_B: BASE_B}, {TEST_A: POST_A, TEST_B: POST_B})


def ladder_instance():
    return {
        "instance_id": "l__l-1", "repo": "pytest-dev/pytest", "patch": "GOLD-SRC-PATCH",
        "test_patch": GOLD_TEST_PATCH,
    }


class LadderPredictionTests(unittest.TestCase):
    def setUp(self):
        self.instance = ladder_instance()
        self.reader = FakeReadFiles({TEST_A: BASE_A, TEST_B: BASE_B})
        self.ladder = calibrate.ladder_predictions(self.instance, read_files_fn=self.reader)
        self.base = {TEST_A: BASE_A, TEST_B: BASE_B}

    def test_vo13_l3_levels_and_identity_fields(self):
        self.assertEqual(set(self.ladder), {"gold", "stripped", "existing", "empty"})
        for name, prediction in self.ladder.items():
            with self.subTest(level=name):
                self.assertEqual(prediction["instance_id"], "l__l-1")
                self.assertIn("src_diff", prediction)
                self.assertIn("test_patch", prediction)

    def test_vo13_l3_source_diffs(self):
        for name in ("gold", "stripped", "existing"):
            self.assertEqual(self.ladder[name]["src_diff"], "GOLD-SRC-PATCH", name)
        self.assertEqual(self.ladder["empty"]["src_diff"], "")

    def test_vo13_l3_gold_and_empty_test_patches(self):
        self.assertEqual(self.ladder["gold"]["test_patch"], GOLD_TEST_PATCH)
        self.assertEqual(self.ladder["empty"]["test_patch"], "")

    def test_vo13_l3_stripped_patch_yields_stripped_post_images_on_base(self):
        files = git_apply_files(self.base, self.ladder["stripped"]["test_patch"])
        self.assertEqual(set(files), {TEST_A, TEST_B})
        self.assertEqual(normalize(files[TEST_A]), normalize(STRIPPED_A))
        self.assertEqual(normalize(files[TEST_B]), normalize(STRIPPED_B))
        self.assertTrue(has_contextlib_import(files[TEST_B]))

    def test_vo13_l3_existing_patch_only_appends_the_selfcheck_line(self):
        files = git_apply_files(self.base, self.ladder["existing"]["test_patch"])
        self.assertEqual(set(files), {TEST_A, TEST_B})
        self.assertEqual(files[TEST_A], BASE_A + "# selfcheck\n")
        self.assertEqual(files[TEST_B], BASE_B + "# selfcheck\n")

    def test_vo13_l3_base_texts_are_read_for_the_gold_test_files_in_section_order(self):
        self.assertGreaterEqual(len(self.reader.calls), 1)
        for call in self.reader.calls:
            self.assertEqual(call, ("", [TEST_A, TEST_B]))


DATA = "tests/data.json"
GONE = "tests/test_gone.py"
KEEP = "tests/test_keep.py"
NEWT = "tests/test_new.py"
C21_BASE = {
    DATA: '{"a": 1}\n',
    GONE: "def test_gone():\n    assert 0 == 0\n",
    KEEP: "def test_old():\n    assert 1 == 1\n",
}
C21_POST = {
    DATA: '{"a": 2}\n',
    GONE: None,
    KEEP: "def test_old():\n    assert 1 == 1\n\n\ndef test_k():\n    assert g(1) == 2, 'm'\n",
    NEWT: "def test_new():\n    assert f(1) == 2, 'm'\n",
}
C21_PATCH = git_diff(C21_BASE, C21_POST)


class MixedGoldTestFilesTests(unittest.TestCase):
    def setUp(self):
        instance = ladder_instance()
        instance["test_patch"] = C21_PATCH
        self.reader = FakeReadFiles(C21_BASE)
        self.ladder = calibrate.ladder_predictions(instance, read_files_fn=self.reader)

    def test_vo13_l4_gold_patch_shape(self):
        for path in (DATA, GONE, KEEP, NEWT):
            self.assertIn("diff --git a/%s b/%s" % (path, path), C21_PATCH)
        self.assertIn("new file mode", C21_PATCH)
        self.assertIn("deleted file mode", C21_PATCH)
        self.assertEqual(self.ladder["gold"]["test_patch"], C21_PATCH)

    def test_vo13_l4_stripped_creates_new_file_keeps_deletion_and_gold_data(self):
        files = git_apply_files(C21_BASE, self.ladder["stripped"]["test_patch"])
        self.assertEqual(set(files), {DATA, KEEP, NEWT})
        self.assertEqual(files[DATA], C21_POST[DATA])
        self.assertEqual(
            normalize(files[NEWT]), normalize("def test_new():\n    f(1) == 2\n")
        )
        self.assertEqual(
            normalize(files[KEEP]),
            normalize("def test_old():\n    1 == 1\n\n\ndef test_k():\n    g(1) == 2\n"),
        )

    def test_vo13_l4_existing_touches_only_existing_py_files(self):
        patch = self.ladder["existing"]["test_patch"]
        self.assertNotIn(DATA, patch)
        self.assertNotIn(NEWT, patch)
        files = git_apply_files(C21_BASE, patch)
        self.assertEqual(set(files), {DATA, GONE, KEEP})
        self.assertEqual(files[DATA], C21_BASE[DATA])
        self.assertEqual(files[GONE], C21_BASE[GONE] + "# selfcheck\n")
        self.assertEqual(files[KEEP], C21_BASE[KEEP] + "# selfcheck\n")

    def test_vo13_l4_base_texts_are_requested_for_every_gold_test_path_in_section_order(self):
        self.assertGreaterEqual(len(self.reader.calls), 1)
        for call in self.reader.calls:
            self.assertEqual(call, ("", [DATA, GONE, KEEP, NEWT]))


NONL_PATH = "tests/test_nonl.py"
DEEP_PATH = "tests/pkg/sub/test_deep.py"
NONL_BASE = "def test_a():\n    assert 1 == 1"
NONL_POST = "def test_a():\n    assert 1 == 1\n\n\ndef test_b():\n    assert g(2) == 3\n"
DEEP_POST = "def test_deep():\n    assert f(1) == 2, 'm'\n"
L5_PATCH = git_diff({NONL_PATH: NONL_BASE}, {NONL_PATH: NONL_POST, DEEP_PATH: DEEP_POST})


class NoFinalNewlineAndNestedNewFileTests(unittest.TestCase):
    def setUp(self):
        instance = ladder_instance()
        instance["test_patch"] = L5_PATCH
        self.ladder = calibrate.ladder_predictions(
            instance, read_files_fn=FakeReadFiles({NONL_PATH: NONL_BASE})
        )

    def test_vo13_l5_existing_inserts_a_newline_before_the_selfcheck_line(self):
        patch = self.ladder["existing"]["test_patch"]
        self.assertNotIn(DEEP_PATH, patch)
        files = git_apply_files({NONL_PATH: NONL_BASE}, patch)
        self.assertEqual(files, {NONL_PATH: NONL_BASE + "\n# selfcheck\n"})

    def test_vo13_l5_stripped_creates_a_file_in_a_directory_missing_at_base(self):
        files = git_apply_files({NONL_PATH: NONL_BASE}, self.ladder["stripped"]["test_patch"])
        self.assertEqual(set(files), {NONL_PATH, DEEP_PATH})
        self.assertEqual(normalize(files[DEEP_PATH]), normalize("def test_deep():\n    f(1) == 2\n"))
        self.assertEqual(
            normalize(files[NONL_PATH]),
            normalize("def test_a():\n    1 == 1\n\n\ndef test_b():\n    g(2) == 3\n"),
        )


def level_score(resolved=True, success=False, kill=0, none_kill=False):
    sampled, d_ref = 10, 5
    return {
        "instance_id": "l__l-1",
        "resolved": resolved,
        "swt": {"applicable": True, "success": success, "f2p": [], "x2f": []},
        "kill": {
            "sampled": sampled, "killed": 0 if none_kill else kill, "d_ref": d_ref,
            "killed_in_d_ref": 0 if none_kill else kill,
            "primary": None if none_kill else kill / sampled,
            "secondary": None if none_kill else kill / d_ref,
            "gold_reference": 0.5, "timeouts": 0,
        },
        "evaluations": 1,
    }


def healthy():
    return {
        "gold": level_score(True, True, 5),
        "stripped": level_score(True, False, 2),
        "existing": level_score(True, False, 0),
        "empty": level_score(False, False, 0),
    }


class CheckLadderTests(unittest.TestCase):
    def verdict(self, scores):
        result = calibrate.check_ladder(scores)
        return result["monotonic"], sorted(result["violations"])

    def test_vo13_l2_monotonic_case(self):
        self.assertEqual(calibrate.check_ladder(healthy()), {"monotonic": True, "violations": []})

    def test_vo13_l2_stripped_none_kill_counts_as_zero(self):
        scores = healthy()
        scores["stripped"] = level_score(True, False, none_kill=True)
        self.assertEqual(self.verdict(scores), (True, []))

    def test_vo13_l1_gold_not_resolved(self):
        scores = healthy()
        scores["gold"]["resolved"] = False
        self.assertEqual(self.verdict(scores), (False, ["gold_not_resolved"]))

    def test_vo13_l1_empty_resolved(self):
        scores = healthy()
        scores["empty"]["resolved"] = True
        self.assertEqual(self.verdict(scores), (False, ["empty_resolved"]))

    def test_vo13_l1_gold_swt_failed(self):
        scores = healthy()
        scores["gold"]["swt"]["success"] = False
        self.assertEqual(self.verdict(scores), (False, ["gold_swt_failed"]))

    def test_vo13_l1_existing_swt_success(self):
        scores = healthy()
        scores["existing"]["swt"]["success"] = True
        self.assertEqual(self.verdict(scores), (False, ["existing_swt_success"]))

    def test_vo13_l1_empty_swt_success(self):
        scores = healthy()
        scores["empty"]["swt"]["success"] = True
        self.assertEqual(self.verdict(scores), (False, ["empty_swt_success"]))

    def test_vo13_l1_gold_kill_zero(self):
        scores = {
            "gold": level_score(True, True, 0),
            "stripped": level_score(True, False, 0),
            "existing": level_score(True, False, 0),
            "empty": level_score(False, False, 0),
        }
        self.assertEqual(self.verdict(scores), (False, ["gold_kill_zero"]))

    def test_vo13_l1_gold_none_kill_counts_as_zero(self):
        scores = healthy()
        scores["gold"] = level_score(True, True, none_kill=True)
        scores["stripped"] = level_score(True, False, none_kill=True)
        self.assertEqual(self.verdict(scores), (False, ["gold_kill_zero"]))

    def test_vo13_l1_kill_order_stripped_above_gold(self):
        scores = healthy()
        scores["gold"] = level_score(True, True, 2)
        scores["stripped"] = level_score(True, False, 3)
        self.assertEqual(self.verdict(scores), (False, ["kill_order"]))

    def test_vo13_l1_kill_order_existing_not_zero(self):
        scores = healthy()
        scores["existing"] = level_score(True, False, 1)
        self.assertEqual(self.verdict(scores), (False, ["kill_order"]))

    def test_vo13_l1_kill_order_empty_not_zero(self):
        scores = healthy()
        scores["empty"] = level_score(False, False, 1)
        self.assertEqual(self.verdict(scores), (False, ["kill_order"]))

    def test_vo13_l1_equal_gold_and_stripped_kill_is_allowed(self):
        scores = healthy()
        scores["stripped"] = level_score(True, False, 5)
        self.assertEqual(self.verdict(scores), (True, []))

    def test_vo13_l1_kill_measure_is_primary_with_none_as_zero(self):
        scores = healthy()
        scores["gold"]["kill"].update({"killed": 0, "killed_in_d_ref": 0, "secondary": 0.0, "primary": 0.5})
        self.assertEqual(self.verdict(scores), (True, []))
        scores = healthy()
        scores["gold"]["kill"]["primary"] = None
        scores["stripped"]["kill"]["primary"] = 0.0
        self.assertEqual(self.verdict(scores), (False, ["gold_kill_zero"]))
        scores = healthy()
        scores["stripped"]["kill"].update({"primary": 0.9, "killed": 0, "secondary": 0.0})
        self.assertEqual(self.verdict(scores), (False, ["kill_order"]))

    def test_vo13_l1_all_violations_together(self):
        scores = {
            "gold": level_score(False, False, 0),
            "stripped": level_score(True, False, 0),
            "existing": level_score(True, True, 0),
            "empty": level_score(True, True, 1),
        }
        monotonic, violations = self.verdict(scores)
        self.assertFalse(monotonic)
        self.assertEqual(
            violations,
            sorted([
                "gold_not_resolved", "empty_resolved", "gold_swt_failed", "existing_swt_success",
                "empty_swt_success", "gold_kill_zero", "kill_order",
            ]),
        )

    def test_vo13_l1_input_scores_are_not_modified(self):
        scores = healthy()
        snapshot = copy.deepcopy(scores)
        calibrate.check_ladder(scores)
        self.assertEqual(scores, snapshot)


class CalibrateInstanceTests(unittest.TestCase):
    def run_with(self, table):
        instance = ladder_instance()
        reader = FakeReadFiles({TEST_A: BASE_A, TEST_B: BASE_B})
        calls = []

        def score_fn(inst, prediction, **kwargs):
            calls.append((inst, prediction, kwargs))
            if prediction["src_diff"] == "":
                name = "empty"
            elif prediction["test_patch"] == GOLD_TEST_PATCH:
                name = "gold"
            elif "selfcheck" in prediction["test_patch"]:
                name = "existing"
            else:
                name = "stripped"
            return table[name]

        validation = {"p2p_effective": []}
        mutants = [{"id": "m1"}]
        result = calibrate.calibrate_instance(
            instance, validation=validation, mutants=mutants, score_fn=score_fn, read_files_fn=reader
        )
        return result, calls, validation, mutants

    def test_vo13_calibrate_instance_scores_each_level_once_and_checks_the_ladder(self):
        table = healthy()
        result, calls, validation, mutants = self.run_with(table)
        self.assertEqual(
            result,
            {
                "instance_id": "l__l-1",
                "levels": table,
                "monotonic": True,
                "violations": [],
            },
        )
        self.assertEqual(len(calls), 4)
        for inst, prediction, kwargs in calls:
            self.assertEqual(inst, ladder_instance())
            self.assertEqual(kwargs, {"validation": validation, "mutants": mutants})
        self.assertEqual(
            sorted(prediction["src_diff"] for _, prediction, _ in calls), ["", "GOLD-SRC-PATCH", "GOLD-SRC-PATCH", "GOLD-SRC-PATCH"]
        )

    def test_vo13_calibrate_instance_reports_violations(self):
        table = healthy()
        table["gold"] = level_score(False, True, 5)
        result, _, _, _ = self.run_with(table)
        self.assertFalse(result["monotonic"])
        self.assertEqual(result["violations"], ["gold_not_resolved"])
        self.assertEqual(result["levels"], table)


if __name__ == "__main__":
    unittest.main()

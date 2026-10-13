import re
import unittest

from swebench.harness.test_spec.test_spec import make_test_spec

from selfcheck import swe
from selfcheck.tests.helpers import DJANGO_ID, PYTEST_ID, SYMPY_ID, pilot, pilot_rows

START = ": '>>>>> Start Test Output'"
END = ": '>>>>> End Test Output'"
DIRECTIVES = {
    PYTEST_ID: [
        "testing/code/test_code.py", "testing/code/test_excinfo.py",
        "testing/conftest.py", "testing/test_reports.py",
    ],
    DJANGO_ID: ["admin_filters.tests", "model_fields.tests"],
    SYMPY_ID: [
        "sympy/ntheory/tests/test_residue.py", "sympy/solvers/tests/test_solveset.py",
    ],
}
JSON_ONLY_PATCH = (
    "diff --git a/testing/data/sample.json b/testing/data/sample.json\n"
    "--- a/testing/data/sample.json\n"
    "+++ b/testing/data/sample.json\n"
    "@@ -1 +1 @@\n"
    "-{}\n"
    "+{\"a\": 1}\n"
)
ONE_FILE_PATCH = (
    "diff --git a/testing/test_reports.py b/testing/test_reports.py\n"
    "--- a/testing/test_reports.py\n"
    "+++ b/testing/test_reports.py\n"
    "@@ -1,1 +1,2 @@\n"
    " import pytest\n"
    "+import os\n"
)


def reference(instance, test_patch=None):
    row = dict(instance)
    if test_patch is not None:
        row["test_patch"] = test_patch
    return make_test_spec(row, namespace=None, arch="arm64").eval_script


def normalized(script):
    lines = [" ".join(line.split()) for line in script.splitlines() if "SELFCHECK_" not in line]
    return [line for line in lines if line]


def test_command_index(lines):
    return lines.index(START) + 1


class ImageNameTests(unittest.TestCase):
    def test_vo6_e5_pilot_image_names(self):
        for instance_id in (DJANGO_ID, PYTEST_ID, SYMPY_ID):
            with self.subTest(instance_id=instance_id):
                self.assertEqual(
                    swe.image_name(pilot(instance_id)), "sweb.eval.arm64.%s:latest" % instance_id
                )

    def test_vo6_e5_instance_id_is_lowercased(self):
        instance = pilot(PYTEST_ID)
        instance["instance_id"] = "Mixed__Case-1"
        self.assertEqual(swe.image_name(instance), "sweb.eval.arm64.mixed__case-1:latest")


class EvalScriptTests(unittest.TestCase):
    def test_vo6_e4_equals_swebench_script_without_markers_for_pilots(self):
        for instance_id, instance in pilot_rows().items():
            with self.subTest(instance_id=instance_id):
                self.assertEqual(normalized(swe.eval_script(instance)), normalized(reference(instance)))

    def test_vo6_e4_equals_swebench_script_with_replaced_test_patch(self):
        instance = pilot(PYTEST_ID)
        replacement = ONE_FILE_PATCH
        self.assertEqual(
            normalized(swe.eval_script(instance, replacement)), normalized(reference(instance, replacement))
        )
        self.assertNotEqual(
            normalized(swe.eval_script(instance, replacement)), normalized(reference(instance))
        )

    def test_vo6_e1_exit_marker_is_on_the_line_after_the_test_command(self):
        for instance_id, instance in pilot_rows().items():
            with self.subTest(instance_id=instance_id):
                lines = swe.eval_script(instance).splitlines()
                index = test_command_index(lines)
                reference_lines = reference(instance).splitlines()
                self.assertEqual(
                    " ".join(lines[index].split()),
                    " ".join(reference_lines[test_command_index(reference_lines)].split()),
                )
                self.assertEqual(" ".join(lines[index + 1].split()), "echo SELFCHECK_EXIT=$?")
                self.assertEqual(sum("SELFCHECK_EXIT=" in line for line in lines), 1)
                self.assertLess(index + 1, lines.index(END))

    def test_vo6_e7_marker_line_counts(self):
        for instance_id, instance in pilot_rows().items():
            with self.subTest(instance_id=instance_id, directives="non-empty"):
                lines = swe.eval_script(instance).splitlines()
                self.assertEqual(sum("SELFCHECK_" in line for line in lines), 2)
        instance = pilot(PYTEST_ID)
        for label, patch in (("empty", ""), ("json-only", JSON_ONLY_PATCH)):
            with self.subTest(directives=label):
                lines = swe.eval_script(instance, patch).splitlines()
                self.assertEqual(sum("SELFCHECK_" in line for line in lines), 3)

    def test_vo6_e3_apply_failed_marker_follows_the_test_patch_heredoc(self):
        for instance_id, instance in pilot_rows().items():
            with self.subTest(instance_id=instance_id):
                lines = swe.eval_script(instance).splitlines()
                heredoc = re.search(r"<<'(EOF_\d+)'", "\n".join(lines)).group(1)
                terminator = lines.index(heredoc)
                marked = [i for i, line in enumerate(lines) if "SELFCHECK_TEST_APPLY_FAILED" in line]
                self.assertEqual(len(marked), 1)
                self.assertEqual(marked[0], terminator + 1)
                self.assertEqual(
                    " ".join(lines[marked[0]].split()),
                    "[ $? -eq 0 ] || { echo SELFCHECK_TEST_APPLY_FAILED; exit 1; }",
                )

    def test_vo6_e2_empty_directives_guard_precedes_the_test_command(self):
        instance = pilot(PYTEST_ID)
        for label, patch in (("empty", ""), ("json-only", JSON_ONLY_PATCH)):
            with self.subTest(test_patch=label):
                lines = swe.eval_script(instance, patch).splitlines()
                guards = [
                    i for i, line in enumerate(lines)
                    if " ".join(line.split()) == "echo SELFCHECK_NO_TESTS; exit 0"
                ]
                self.assertEqual(len(guards), 1)
                reference_lines = reference(instance, patch).splitlines()
                command = " ".join(reference_lines[test_command_index(reference_lines)].split())
                command_positions = [i for i, line in enumerate(lines) if " ".join(line.split()) == command]
                self.assertEqual(len(command_positions), 1)
                self.assertLess(guards[0], lines.index(START))
                self.assertLess(guards[0], command_positions[0])
                self.assertEqual(
                    normalized("\n".join(lines)), normalized(reference(instance, patch))
                )

    def test_vo6_e2_non_empty_directives_script_keeps_the_test_command(self):
        instance = pilot(PYTEST_ID)
        script = swe.eval_script(instance)
        self.assertIn("pytest -rA testing/code/test_code.py", script)

    def test_vo6_e2_directives_follow_the_test_patch_argument(self):
        instance = pilot(PYTEST_ID)
        self.assertEqual(swe.directives(instance), DIRECTIVES[PYTEST_ID])
        self.assertEqual(swe.directives(instance, ONE_FILE_PATCH), ["testing/test_reports.py"])
        self.assertEqual(swe.directives(instance, ""), [])
        self.assertEqual(swe.directives(instance, JSON_ONLY_PATCH), [])
        self.assertIn("pytest -rA testing/test_reports.py", swe.eval_script(instance, ONE_FILE_PATCH))

    def test_vo6_e2_directives_for_each_pilot_repo(self):
        for instance_id, expected in DIRECTIVES.items():
            with self.subTest(instance_id=instance_id):
                self.assertEqual(swe.directives(pilot(instance_id)), expected)

    def test_vo6_make_spec_replaces_only_the_test_patch(self):
        instance = pilot(PYTEST_ID)
        replaced = swe.make_spec(instance, ONE_FILE_PATCH)
        self.assertEqual(replaced.instance_id, PYTEST_ID)
        self.assertIn(ONE_FILE_PATCH, replaced.eval_script)
        self.assertNotIn(instance["test_patch"], replaced.eval_script)
        self.assertIn(instance["test_patch"], swe.make_spec(instance).eval_script)
        self.assertEqual(instance, pilot(PYTEST_ID))


PYTEST_LOG = """+ pytest -rA testing/test_reports.py
PASSED testing/outside_before.py::test_before
: '>>>>> Start Test Output'
============================= test session starts ==============================
PASSED testing/test_reports.py::TestA::test_x
FAILED testing/test_reports.py::TestA::test_y - assert 1 == 2
ERROR testing/test_reports.py::test_z - boom
XFAIL testing/test_reports.py::test_xf - reason
: '>>>>> End Test Output'
PASSED testing/outside_after.py::test_after
"""
DJANGO_LOG = """test_outside_before (m.Outside) ... ok
: '>>>>> Start Test Output'
test_get_choices_default_ordering (model_fields.tests.GetChoicesOrderingTests) ... ok
test_other (model_fields.tests.GetChoicesOrderingTests) ... FAIL
test_err (admin_filters.tests.ListFiltersTests) ... ERROR
test_sk (admin_filters.tests.ListFiltersTests) ... skipped 'why'
: '>>>>> End Test Output'
test_outside_after (m.Outside) ... ok
"""
SYMPY_LOG = """test_outside_before ok
: '>>>>> Start Test Output'
test_solve_modular ok
test_bad F
test_err E
: '>>>>> End Test Output'
test_outside_after ok
"""


class ParseStatusTests(unittest.TestCase):
    def test_vo6_e6_pytest_log_between_markers(self):
        self.assertEqual(
            swe.parse_status(pilot(PYTEST_ID), PYTEST_LOG),
            {
                "testing/test_reports.py::TestA::test_x": "PASSED",
                "testing/test_reports.py::TestA::test_y": "FAILED",
                "testing/test_reports.py::test_z": "ERROR",
                "testing/test_reports.py::test_xf": "XFAIL",
            },
        )

    def test_vo6_e6_django_log_between_markers(self):
        self.assertEqual(
            swe.parse_status(pilot(DJANGO_ID), DJANGO_LOG),
            {
                "test_get_choices_default_ordering (model_fields.tests.GetChoicesOrderingTests)": "PASSED",
                "test_other (model_fields.tests.GetChoicesOrderingTests)": "FAILED",
                "test_err (admin_filters.tests.ListFiltersTests)": "ERROR",
                "test_sk (admin_filters.tests.ListFiltersTests)": "SKIPPED",
            },
        )

    def test_vo6_e6_sympy_log_between_markers(self):
        self.assertEqual(
            swe.parse_status(pilot(SYMPY_ID), SYMPY_LOG),
            {"test_solve_modular": "PASSED", "test_bad": "FAILED", "test_err": "ERROR"},
        )

    def test_vo6_e6_parser_is_chosen_by_repo(self):
        self.assertEqual(swe.parse_status(pilot(DJANGO_ID), PYTEST_LOG), {})


if __name__ == "__main__":
    unittest.main()

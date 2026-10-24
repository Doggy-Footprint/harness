import copy
import json
import re
import unittest

from evaluation.pr_test_quality import junit, recipes
from evaluation.pr_test_quality.tests.fakes import LANG_FIXTURES, TmpCase, pytest_junit, spec_cfg, udiff
from evaluation.pr_test_quality.tests.test_pipeline import Pipe, TASK_ID

def pkg(**kw):
    return json.dumps(kw)


def ts(files):
    return recipes.detect("typescript", files)


LOCK = {"yarn.lock": ""}


class RunnerSelection(unittest.TestCase):
    def runner(self, manifest, lock=None):
        return ts({**(lock or LOCK), "package.json": json.dumps(manifest)})["test"]["runner"]

    def test_O3_F31_vitest_wins_over_jest_and_mocha(self):
        self.assertEqual(self.runner({"devDependencies": {"vitest": "1", "jest": "1", "mocha": "1"}}), "vitest")

    def test_O3_F31_jest_wins_over_mocha_and_node_test(self):
        self.assertEqual(self.runner({"devDependencies": {"jest": "1", "mocha": "1"},
                                      "scripts": {"test": "node --test"}}), "jest")

    def test_O3_F31_mocha_wins_over_node_test(self):
        self.assertEqual(self.runner({"devDependencies": {"mocha": "1"}, "scripts": {"test": "node --test"}}), "mocha")

    def test_O3_F31_dependencies_and_dev_dependencies_both_count(self):
        for section in ("dependencies", "devDependencies"):
            self.assertEqual(self.runner({section: {"mocha": "1"}}), "mocha")

    def test_O3_F31_node_test_when_the_test_script_contains_it(self):
        for script in ("node --test", "node --test test/", "c8 node --test --experimental-test-coverage", "NODE_ENV=x node --test"):
            with self.subTest(script=script):
                self.assertEqual(self.runner({"scripts": {"test": script}}), "node-test")

    def test_O3_F31_other_scripts_raise_naming_the_four_supported_runners(self):
        for manifest in ({}, {"scripts": {"test": "echo hi"}}, {"scripts": {"lint": "node --test"}},
                         {"scripts": {"test": "node test.js"}}):
            with self.subTest(manifest=manifest):
                with self.assertRaises(recipes.RecipeError) as ctx:
                    self.runner(manifest)
                self.assertIn("no supported test runner (vitest, jest, mocha, node --test)", str(ctx.exception))

    def test_O3_F31_every_manager_gets_the_same_runner_choice(self):
        for lock in ({"pnpm-lock.yaml": ""}, {"yarn.lock": ""}, {"bun.lock": ""}, {"package-lock.json": "{}"}):
            self.assertEqual(self.runner({"devDependencies": {"mocha": "1"}}, lock), "mocha")


class RunnerArgv(unittest.TestCase):
    JUNIT = "/o/junit-here.xml"
    SEL = ["test/a.test.js", "test/b.test.js"]

    def argv(self, manifest, lock=None, selection=None):
        recipe = ts({**(lock or LOCK), "package.json": json.dumps(manifest)})
        return recipes.test_argv(recipe, selection or self.SEL, self.JUNIT)

    def test_O3_F31_mocha_argv_uses_the_junit_reporter_and_the_destination(self):
        argv = self.argv({"devDependencies": {"mocha": "1"}})
        text = " ".join(argv)
        self.assertTrue(any(a == "mocha" or a.endswith("/mocha") for a in argv), argv)
        self.assertIn("--reporter mocha-junit-reporter", text)
        self.assertIn("--reporter-options mochaFile=%s" % self.JUNIT, text)
        self.assertEqual(argv[-2:], self.SEL)

    def test_O3_F31_argv_changes_with_the_selection_for_every_typescript_runner(self):
        for manifest in ({"devDependencies": {"vitest": "1"}}, {"devDependencies": {"jest": "1"}},
                         {"devDependencies": {"mocha": "1"}}, {"scripts": {"test": "node --test"}}):
            one, two = self.argv(manifest, selection=["a.test.js"]), self.argv(manifest, selection=["b.test.js"])
            with self.subTest(manifest=manifest):
                self.assertNotEqual(one, two)

    def test_O3_F31_the_junit_destination_is_in_every_typescript_argv(self):
        for manifest in ({"devDependencies": {"vitest": "1"}}, {"devDependencies": {"jest": "1"}},
                         {"devDependencies": {"mocha": "1"}}, {"scripts": {"test": "node --test"}}):
            with self.subTest(manifest=manifest):
                self.assertIn(self.JUNIT, " ".join(self.argv(manifest)))

    def test_O3_F31_no_runner_can_download_a_package(self):
        manifests = ({"devDependencies": {"vitest": "1"}}, {"devDependencies": {"jest": "1"}},
                     {"devDependencies": {"mocha": "1"}}, {"scripts": {"test": "node --test"}})
        for lock in ({"pnpm-lock.yaml": ""}, {"yarn.lock": ""}, {"bun.lock": ""}, {"package-lock.json": "{}"}):
            for manifest in manifests:
                argv = self.argv(manifest, lock)
                text = " ".join(argv)
                with self.subTest(lock=sorted(lock), manifest=manifest):
                    for match in re.finditer(r"\bnpx\b(.*)", text):
                        self.assertRegex(match.group(1), r"--no-install|--no\b|--offline", text)
                    self.assertNotRegex(text, r"\b(dlx|bunx)\b")
                    self.assertNotRegex(text, r"npm\s+(exec|x)\b(?!.*--no)")

    def test_O3_F31_mocha_dockerfile_pins_the_reporter_from_cfg_tools(self):
        recipe = ts({"yarn.lock": "", "package.json": pkg(devDependencies={"mocha": "1"})})
        text = recipes.dockerfile(recipe, spec_cfg())
        self.assertRegex(text, r"mocha-junit-reporter@\d+\.\d+\.\d+")
        self.assertNotIn("mocha-junit-reporter@latest", text)
        versions = set(re.findall(r"mocha-junit-reporter@(\d+\.\d+\.\d+)", text))
        self.assertEqual(len(versions), 1)
        self.assertEqual(len(re.findall(r"mocha-junit-reporter", text)), len(re.findall(r"mocha-junit-reporter@", text)))
        self.assertEqual(sum(1 for line in text.splitlines() if "mocha-junit-reporter" in line), 1)

    def test_O3_F31_other_ts_runners_do_not_install_the_mocha_reporter(self):
        for manifest in ({"devDependencies": {"jest": "1"}}, {"devDependencies": {"vitest": "1"}}):
            text = recipes.dockerfile(ts({"yarn.lock": "", "package.json": json.dumps(manifest)}), spec_cfg())
            self.assertNotIn("mocha-junit-reporter", text)

    def test_O3_F31_mocha_reporter_pin_is_held_in_cfg_tools(self):
        tools = json.dumps(spec_cfg()["tools"])
        self.assertRegex(tools, r"mocha-junit-reporter@\d+\.\d+\.\d+")


MOCHA_XML = """<?xml version="1.0" encoding="UTF-8"?>
<testsuites name="Mocha Tests" time="%(t)s" tests="3" failures="1">
  <testsuite name="Root Suite" timestamp="2026-10-01T10:00:00" tests="0" file="/testbed/test/calc.test.js" time="0.000" failures="0"/>
  <testsuite name="Calc" timestamp="2026-10-01T10:00:00" tests="3" file="/testbed/test/calc.test.js" time="%(t)s" failures="1">
    <testcase name="Calc adds numbers" time="%(t)s" classname="adds numbers"/>
    <testcase name="Calc fails loudly" time="%(t)s" classname="fails loudly"><failure message="expected 1 to equal 2" type="AssertionError">trace</failure></testcase>
    <testcase name="Calc skipped one" time="0" classname="skipped one"><skipped/></testcase>
  </testsuite>
</testsuites>"""
NODE_XML = """<?xml version="1.0" encoding="utf-8"?>
<testsuites>
<testsuite name="math" time="%(t)s" disabled="0" errors="0" tests="3" failures="1" skipped="1" hostname="host">
<testcase name="adds" time="%(t)s" classname="test"/>
<testcase name="fails" time="%(t)s" classname="test"><failure type="testCodeFailure" message="boom">trace</failure></testcase>
<testcase name="later" time="0" classname="test"><skipped type="skipped" message="todo"/></testcase>
</testsuite>
<testsuite name="strings" time="%(t)s" disabled="0" errors="0" tests="1" failures="0" skipped="0" hostname="host">
<testcase name="adds" time="%(t)s" classname="test"/>
</testsuite>
</testsuites>"""


class ReporterShapes(unittest.TestCase):
    def parse(self, xml, t="0.01"):
        return junit.parse(xml % {"t": t}, language="typescript")

    def test_O14_F31_mocha_shape_maps_statuses_and_keeps_the_describe_chain(self):
        result = self.parse(MOCHA_XML)
        self.assertEqual(len(result), 3)
        by_name = {k: v for k, v in result.items()}
        pass_id = [k for k in by_name if "adds numbers" in k][0]
        fail_id = [k for k in by_name if "fails loudly" in k][0]
        skip_id = [k for k in by_name if "skipped one" in k][0]
        self.assertEqual((by_name[pass_id], by_name[fail_id], by_name[skip_id]), ("pass", "fail", "skip"))
        for key in (pass_id, fail_id, skip_id):
            self.assertIn("Calc", key)
            self.assertIn("calc.test.js", key)

    def test_O14_F31_mocha_ids_are_stable_when_only_times_change(self):
        self.assertEqual(set(self.parse(MOCHA_XML, "0.01")), set(self.parse(MOCHA_XML, "12.5")))

    def test_O14_F31_mocha_ids_do_not_embed_the_checkout_directory_twice(self):
        for key in self.parse(MOCHA_XML):
            self.assertLessEqual(key.count("/testbed"), 1)

    def test_O14_F31_node_test_shape_maps_statuses(self):
        result = self.parse(NODE_XML)
        self.assertEqual(sorted(result.values()), ["fail", "pass", "pass", "skip"])

    def test_O14_F31_node_test_same_name_in_two_suites_stays_distinct(self):
        result = self.parse(NODE_XML)
        adds = [k for k in result if k.endswith("adds") or "adds" in k.split("::")[-1]]
        self.assertEqual(len(adds), 2)
        self.assertEqual(len(set(adds)), 2)
        self.assertTrue({"math", "strings"} <= {part for k in adds for part in k.split("::")})

    def test_O14_F31_node_test_ids_are_stable_when_only_times_change(self):
        self.assertEqual(set(self.parse(NODE_XML, "0.01")), set(self.parse(NODE_XML, "99.9")))

    def test_O14_F31_truncated_reporter_output_raises_junit_error(self):
        for xml in (MOCHA_XML, NODE_XML):
            with self.assertRaises(junit.JunitError):
                junit.parse((xml % {"t": "0.1"})[:200], language="typescript")


class GoListing(Pipe):
    def go_task(self):
        base = self.tasks()[0]
        row = copy.deepcopy(base)
        fx = LANG_FIXTURES["go"]
        row.update({
            "language": "go", "pilot": False,
            "recipe": recipes.detect("go", {"go.mod": "module m\n\ngo 1.24\n"}),
            "gold_split": {"src": udiff(fx["src_path"], fx["src_old"], fx["src_new"]),
                           "tests": udiff(fx["test_path"], None, fx["test_new"]), "harness": "", "other": ""},
            "gold_base": {fx["src_path"]: fx["src_old"], fx["test_path"]: None},
            "gold_after": {fx["src_path"]: fx["src_new"], fx["test_path"]: fx["test_new"]},
            "f2p": ["ops::TestClampUpperZq"],
        })
        path = self.data() / "tasks" / "go"
        path.mkdir(parents=True, exist_ok=True)
        (path / "tasks.jsonl").write_text(json.dumps(row) + "\n", encoding="utf-8")

    def test_O32_F37_go_mutesting_listing_uses_only_the_diff_exec_script(self):
        self.stage("brief")
        self.go_task()
        seen = []
        diff = ("--- ops/ops.go\n+++ /tmp/go-mutesting-1/ops/ops.go.0\n@@ -5,3 +5,3 @@\n func Clamp(value, lo, hi int) int {\n"
                "-\tif value < lo {\n+\tif value <= lo {\n")

        def policy(cont, argv):
            joined = " ".join(argv)
            seen.append(joined)
            return (0, diff, False) if "go-mutesting" in joined else None
        self.docker.exec_policy = policy
        code, out = self.inv(["mutants", "--language", "go"])
        self.assertEqual(code, 0, out)
        listing = [s for s in seen if "go-mutesting" in s]
        self.assertEqual(len(listing), 1, seen)
        self.assertIn("--exec /tmp/evaluation-mutesting-diff.sh", listing[0])
        self.assertNotRegex(listing[0], r"go-mutesting\s+(?!--exec)")
        task = json.loads((self.data() / "tasks" / "go" / "tasks.jsonl").read_text())
        self.assertGreaterEqual(len(task["mutants"]), 1)
        self.assertTrue(all(m["path"] == "ops/ops.go" for m in task["mutants"]))


def xml_for(language, ids):
    """JUnit for ids `<file>::[<Class>::]<name>` (python) or `<pkg>::<name>` (go)."""
    cases = []
    for tid, status in ids.items():
        inner = {"pass": "", "fail": '<failure message="x"/>'}[status]
        if language == "go":
            pkg_, name = tid.split("::", 1)
            cases.append('<testcase classname="%s" name="%s">%s</testcase>' % (pkg_, name, inner))
    return '<testsuites><testsuite name="s">%s</testsuite></testsuites>' % "".join(cases)


class F2pRestriction(Pipe):
    def validate_with(self, task_patch, results_for):
        self.stage("build")
        rows = self.tasks()
        row = rows[0]
        row.update(task_patch)
        (self.data() / "tasks" / row["language"]).mkdir(parents=True, exist_ok=True)
        (self.data() / "tasks" / row["language"] / "tasks.jsonl").write_text(json.dumps(row) + "\n", encoding="utf-8")
        self.docker.junit_policy = results_for
        code, out = self.inv(["validate", "--language", row["language"], "--force"])
        self.assertEqual(code, 0, out)
        return json.loads((self.data() / "tasks" / row["language"] / "tasks.jsonl").read_text().splitlines()[0])

    def python_patch(self, old_tests, new_tests):
        fx = LANG_FIXTURES["python"]
        return {
            "gold_split": {"src": udiff(fx["src_path"], fx["src_old"], fx["src_new"]),
                           "tests": udiff(fx["test_path"], old_tests, new_tests), "harness": "", "other": ""},
            "gold_base": {fx["src_path"]: fx["src_old"], fx["test_path"]: old_tests},
            "gold_after": {fx["src_path"]: fx["src_new"], fx["test_path"]: new_tests},
        }

    def by_state(self, ids, old=None):
        def policy(cont):
            merged = "def clamp" in cont.tree_text()
            text = next((v for k, v in cont.files().items() if k.endswith("tests/test_ops.py")), None)
            if old is not None and not merged and text == old:
                return pytest_junit({i: "pass" for i in ids if i.split("::")[-1].split("[")[0] in old})
            return pytest_junit({i: ("pass" if merged else "fail") for i in ids})
        return policy

    def test_O5_F33_a_new_test_file_keeps_every_candidate(self):
        ids = ["tests/test_ops.py::test_a", "tests/test_ops.py::test_b"]
        new = "def test_a(): pass\ndef test_b(): pass\n"
        task = self.validate_with(self.python_patch(None, new), self.by_state(ids))
        self.assertEqual(sorted(task["f2p"]), sorted(ids))
        self.assertTrue(task["valid"])

    def test_O5_F33_modified_file_keeps_only_names_found_in_an_added_line(self):
        old = "def test_old_a(): pass\ndef test_old_b(): pass\n"
        new = old + "def test_new_behavior(): pass\n"
        ids = ["tests/test_ops.py::test_old_a", "tests/test_ops.py::test_old_b", "tests/test_ops.py::test_new_behavior"]
        task = self.validate_with(self.python_patch(old, new), self.by_state(ids, old))
        self.assertEqual(task["f2p"], ["tests/test_ops.py::test_new_behavior"])
        self.assertEqual(sorted(task["p2p"]), ["tests/test_ops.py::test_old_a", "tests/test_ops.py::test_old_b"])
        self.assertTrue(task["valid"])

    def test_O5_F33_F42_a_dropped_candidate_that_passes_at_orig_moves_to_p2p_only(self):
        old = "def test_old_a(): pass\n"
        new = old + "def test_new_behavior(): pass\n"
        ids = ["tests/test_ops.py::test_old_a", "tests/test_ops.py::test_new_behavior"]
        task = self.validate_with(self.python_patch(old, new), self.by_state(ids, old))
        self.assertEqual(task["f2p"], ["tests/test_ops.py::test_new_behavior"])
        self.assertEqual(task["p2p"], ["tests/test_ops.py::test_old_a"])

    def test_O5_F33_python_param_suffix_is_ignored_when_matching_the_added_line(self):
        old = "def test_old(): pass\n"
        new = old + "@pytest.mark.parametrize('x', [1, 2])\ndef test_param(x): pass\n"
        ids = ["tests/test_ops.py::test_old", "tests/test_ops.py::test_param[1]", "tests/test_ops.py::test_param[2]"]
        task = self.validate_with(self.python_patch(old, new), self.by_state(ids, old))
        self.assertEqual(sorted(task["f2p"]), ["tests/test_ops.py::test_param[1]", "tests/test_ops.py::test_param[2]"])

    def test_O5_F33_a_name_only_in_a_removed_or_context_line_is_dropped(self):
        old = "def test_kept(): pass\ndef test_gone(): pass\n"
        new = "def test_kept(): pass\ndef test_fresh(): pass\n"
        ids = ["tests/test_ops.py::test_kept", "tests/test_ops.py::test_fresh"]
        task = self.validate_with(self.python_patch(old, new), self.by_state(ids, old))
        self.assertEqual(task["f2p"], ["tests/test_ops.py::test_fresh"])

    def go_patch(self, old_tests, new_tests):
        fx = LANG_FIXTURES["go"]
        return {
            "language": "go", "recipe": recipes.detect("go", {"go.mod": "module m\n\ngo 1.24\n"}),
            "gold_split": {"src": udiff(fx["src_path"], fx["src_old"], fx["src_new"]),
                           "tests": udiff(fx["test_path"], old_tests, new_tests), "harness": "", "other": ""},
            "gold_base": {fx["src_path"]: fx["src_old"], fx["test_path"]: old_tests},
            "gold_after": {fx["src_path"]: fx["src_new"], fx["test_path"]: new_tests},
        }

    def go_policy(self, ids, old=None):
        def policy(cont):
            merged = "func Clamp" in cont.tree_text()
            text = next((v for k, v in cont.files().items() if k.endswith("ops/ops_test.go")), None)
            if old is not None and not merged and text == old:
                return xml_for("go", {i: "pass" for i in ids if ("func " + i.split("::")[-1].split("/")[0]) in old})
            return xml_for("go", {i: ("pass" if merged else "fail") for i in ids})
        return policy

    def test_O5_F33_go_subtests_follow_their_parent_name_and_a_failing_package_does_not_flood_f2p(self):
        old = "package ops\n\nfunc TestOld(t *testing.T) {}\nfunc TestOther(t *testing.T) {}\n"
        new = old + "func TestClamp(t *testing.T) {\n\tt.Run(\"upper\", func(t *testing.T) {})\n}\n"
        ids = ["ops::TestOld", "ops::TestOther", "ops::TestClamp", "ops::TestClamp/upper", "ops::TestClamp/lower"]
        task = self.validate_with(self.go_patch(old, new), self.go_policy(ids, old))
        self.assertEqual(sorted(task["f2p"]), ["ops::TestClamp", "ops::TestClamp/lower", "ops::TestClamp/upper"])
        self.assertEqual(sorted(task["p2p"]), ["ops::TestOld", "ops::TestOther"])

    def test_O5_F33_go_new_test_file_keeps_everything(self):
        new = "package ops\n\nfunc TestA(t *testing.T) {}\nfunc TestB(t *testing.T) {}\n"
        ids = ["ops::TestA", "ops::TestB", "ops::TestB/sub"]
        task = self.validate_with(self.go_patch(None, new), self.go_policy(ids))
        self.assertEqual(sorted(task["f2p"]), sorted(ids))

    def test_O5_F33_every_candidate_dropped_means_no_f2p_and_the_task_is_invalid(self):
        old = "def test_old_a(): pass\n"
        new = old + "# only a comment added\n"
        ids = ["tests/test_ops.py::test_old_a"]
        task = self.validate_with(self.python_patch(old, new), self.by_state(ids, old))
        self.assertFalse(task["valid"])
        self.assertEqual(task["reason"], "no_f2p")
        self.assertEqual(task["f2p"], [])


class UndecodableFiles(Pipe):
    PNG = b"\x89PNG\r\n\x1a\n"

    def setUp(self):
        super().setUp()
        self.bad_paths = set()
        original = self.git

        def git(argv, inp):
            if "show" in argv:
                path = argv[-1].split(":", 1)[1]
                if path in self.bad_paths:
                    raise UnicodeDecodeError("utf-8", self.PNG, 0, 1, "invalid start byte")
            out = original(argv, inp)
            if "diff" in argv and "--binary" in argv and self.bad_paths:
                extra = "".join("diff --git a/%s b/%s\nnew file mode 100644\nindex 0000000..1111111\nGIT binary patch\n"
                                "literal 8\nHcmV?d00001\n\n" % (p, p) for p in sorted(self.bad_paths))
                return out[0], out[1] + extra, out[2]
            return out
        self.run_fn.handler = git

    def build(self):
        self.inv(["mine", "--language", "python"])
        code, out = self.inv(["build", "--language", "python"])
        self.assertEqual(code, 0, out)
        return self.tasks()[0], out

    def test_O3_F34_an_undecodable_asset_is_left_out_and_the_candidate_survives(self):
        self.bad_paths = {"assets/logo.png"}
        task, out = self.build()
        self.assertNotIn("assets/logo.png", task["gold_base"])
        self.assertNotIn("assets/logo.png", task["gold_after"])
        self.assertNotIn("assets/logo.png", task["gold_split"]["other"])
        self.assertNotIn("assets/logo.png", json.dumps(task["gold_split"]))
        fx = LANG_FIXTURES["python"]
        self.assertEqual(task["gold_after"][fx["src_path"]], fx["src_new"])
        self.assertNotIn("Traceback", out)

    def test_O3_F34_an_undecodable_src_file_marks_the_candidate_invalid_binary(self):
        self.bad_paths = {"src/calc/blob.py"}
        task, out = self.build()
        self.assertIs(task["valid"], False)
        self.assertEqual(task["reason"], "binary")
        self.assertNotIn("src/calc/blob.py", task.get("gold_base") or {})
        self.assertNotIn("src/calc/blob.py", task.get("gold_after") or {})

    def test_O3_F34_an_undecodable_test_file_marks_the_candidate_invalid_binary(self):
        self.bad_paths = {"tests/data_blob.py"}
        task, _ = self.build()
        self.assertIs(task["valid"], False)
        self.assertEqual(task["reason"], "binary")

    def test_O3_F34_other_candidates_are_still_built_after_a_binary_one(self):
        self.bad_paths = {"src/calc/blob.py"}
        self.gh = __import__("evaluation.pr_test_quality.tests.test_mine", fromlist=["FakeGh"]).FakeGh({"own/solo": [5, 6]})
        self.inv(["mine", "--language", "python"])
        code, out = self.inv(["build", "--language", "python"])
        self.assertEqual(code, 0, out)
        self.assertEqual(len(self.tasks()), 2)

    def test_O3_F34_texts_are_read_as_utf_8(self):
        fx = LANG_FIXTURES["python"]
        original = self.run_fn.handler

        def git(argv, inp):
            if "show" in argv and argv[-1].endswith(fx["src_path"]) and argv[-1].split(":")[0].endswith("3ed"):
                return 0, "# café ✓\n" + fx["src_old"], ""
            return original(argv, inp)
        self.run_fn.handler = git
        task, _ = self.build()
        self.assertTrue(task["gold_base"][fx["src_path"]].startswith("# café ✓\n"))

import copy
import hashlib
import json
import re
import unittest

from evaluation.pr_test_quality import brief, crossarm, judge, junit, languages, recipes, stats, usersim
from evaluation.pr_test_quality.tests.fakes import FakeCall, make_task, spec_cfg, udiff, interface_request
from evaluation.pr_test_quality.tests.test_judge import BRIEF, CAND, QUOTE, valid_absolute
from evaluation.pr_test_quality.tests.test_usersim import ASK, IDLE, STATEMENTS, task as sim_task

CLOSING = "Implement this and add automated tests."


class JunitIds(unittest.TestCase):
    def ids(self, xml, language):
        return list(junit.parse(xml, language=language))

    def test_O14_F8_go_ids_are_package_dir_and_test_name(self):
        xml = ('<testsuites><testsuite name="s">'
               '<testcase classname="example.com/m/pkg/sub" name="TestAlpha"/>'
               '<testcase classname="example.com/m/pkg/sub" name="TestGamma/sub_case"/></testsuite></testsuites>')
        self.assertEqual(self.ids(xml, "go"), ["example.com/m/pkg/sub::TestAlpha", "example.com/m/pkg/sub::TestGamma/sub_case"])

    def test_O14_F8_go_two_packages_with_the_same_test_name_stay_distinct(self):
        xml = ('<testsuites><testsuite name="s"><testcase classname="m/pkg/one" name="TestX"/>'
               '<testcase classname="m/pkg/two" name="TestX"/></testsuite></testsuites>')
        result = junit.parse(xml, language="go")
        self.assertEqual(sorted(result), ["m/pkg/one::TestX", "m/pkg/two::TestX"])
        self.assertEqual(len(result), 2)

    def test_O14_F8_rust_two_crates_with_the_same_module_path_stay_distinct(self):
        xml = ('<testsuites><testsuite name="x"><testcase name="tests::t" classname="calc"/>'
               '<testcase name="tests::t" classname="other"/>'
               '<testcase name="a::b::t" classname="calc::bin/cli"/></testsuite></testsuites>')
        self.assertEqual(self.ids(xml, "rust"), ["calc::tests::t", "other::tests::t", "calc::bin/cli::a::b::t"])

    def test_O14_F8_typescript_ids_are_file_describe_chain_and_name(self):
        xml = ('<testsuites><testsuite name="src/a.test.ts">'
               '<testcase classname="src/a.test.ts" name="clamp &gt; caps at upper"/>'
               '<testcase classname="src/a.test.ts" name="clamp &gt; inner &gt; deep one"/>'
               '<testcase classname="src/a.test.ts" name="top level test"/>'
               '<testcase classname="src/b.test.ts" name="top level test"/></testsuite></testsuites>')
        self.assertEqual(self.ids(xml, "typescript"), [
            "src/a.test.ts::clamp::caps at upper", "src/a.test.ts::clamp::inner::deep one",
            "src/a.test.ts::top level test", "src/b.test.ts::top level test"])

    def test_O14_F8_python_id_without_file_attribute_maps_classname_dots_to_the_file_path(self):
        xml = ('<testsuites><testsuite><testcase classname="tests.test_a.TestX" name="test_m"/>'
               '<testcase classname="tests.test_a" name="test_f"/>'
               '<testcase classname="pkg.sub.test_b.TestY.TestZ" name="test_n[1-a]"/></testsuite></testsuites>')
        self.assertEqual(self.ids(xml, "python"), [
            "tests/test_a.py::TestX::test_m", "tests/test_a.py::test_f", "pkg/sub/test_b.py::TestY::TestZ::test_n[1-a]"])

    def test_O14_F8_python_id_with_and_without_file_attribute_agree(self):
        with_file = ('<testsuites><testsuite><testcase classname="tests.test_a.TestX" name="test_m" '
                     'file="tests/test_a.py"/></testsuite></testsuites>')
        without = '<testsuites><testsuite><testcase classname="tests.test_a.TestX" name="test_m"/></testsuite></testsuites>'
        self.assertEqual(self.ids(with_file, "python"), self.ids(without, "python"))


JSON_VITEST = json.dumps({"devDependencies": {"vitest": "1"}})
JSON_JEST = json.dumps({"devDependencies": {"jest": "1"}})
RECIPE_FILES = {
    "python": {"requirements.txt": "pytest\n"},
    "vitest": {"yarn.lock": "", "package.json": JSON_VITEST},
    "jest": {"yarn.lock": "", "package.json": JSON_JEST},
    "go": {"go.mod": "module m\n"},
    "rust": {"Cargo.toml": "[package]\nname='x'\n"},
}


class RecipesV5(unittest.TestCase):
    def recipe(self, key):
        lang = {"vitest": "typescript", "jest": "typescript"}.get(key, key)
        return recipes.detect(lang, RECIPE_FILES[key])

    def test_O3_F9_every_runner_changes_argv_with_the_selection(self):
        pairs = {"python": (["tests/test_a.py"], ["tests/test_b.py"]),
                 "vitest": (["src/a.test.ts"], ["src/b.test.ts"]),
                 "jest": (["src/a.test.ts"], ["src/b.test.ts"]),
                 "go": (["a/a_test.go"], ["b/b_test.go"]),
                 "rust": (["tests/one.rs"], ["tests/two.rs"])}
        for key, (one, two) in pairs.items():
            recipe = self.recipe(key)
            with self.subTest(runner=key):
                self.assertNotEqual(recipes.test_argv(recipe, one, "/o/j.xml"), recipes.test_argv(recipe, two, "/o/j.xml"))

    def test_O3_F9_junit_destination_is_present_for_every_runner(self):
        for key in RECIPE_FILES:
            recipe = self.recipe(key)
            argv = recipes.test_argv(recipe, ["tests/x_test"], "/o/junit-here.xml")
            with self.subTest(runner=key):
                self.assertIn("/o/junit-here.xml", " ".join(argv))

    def test_O3_F9_jest_uses_jest_junit_and_nextest_the_junit_profile(self):
        jest = " ".join(recipes.test_argv(self.recipe("jest"), ["src/a.test.ts"], "/o/j.xml"))
        self.assertIn("--reporters=jest-junit", jest)
        self.assertIn("JEST_JUNIT_OUTPUT_FILE=/o/j.xml", jest)
        nextest = " ".join(recipes.test_argv(self.recipe("rust"), ["tests/one.rs"], "/o/j.xml"))
        self.assertIn("nextest", nextest)
        self.assertIn("--profile junit", nextest)

    def test_O3_F9_selection_paths_appear_in_the_argv_of_path_based_runners(self):
        for key in ("python", "vitest", "jest"):
            argv = recipes.test_argv(self.recipe(key), ["a/one.test", "b/two.test"], "/o/j.xml")
            with self.subTest(runner=key):
                self.assertIn("a/one.test", argv)
                self.assertIn("b/two.test", argv)

    def test_O3_F9_typescript_without_lockfile_names_every_accepted_lockfile(self):
        with self.assertRaises(recipes.RecipeError) as ctx:
            recipes.detect("typescript", {"package.json": JSON_VITEST})
        for name in ("pnpm-lock.yaml", "yarn.lock", "bun.lock", "bun.lockb", "package-lock.json"):
            self.assertIn(name, str(ctx.exception))

    def test_O3_F9_python_and_rust_and_go_errors_name_their_manifests(self):
        for lang, needle in (("python", "pyproject.toml"), ("go", "go.mod"), ("rust", "Cargo.toml")):
            with self.assertRaises(recipes.RecipeError) as ctx:
                recipes.detect(lang, {})
            self.assertIn(needle, str(ctx.exception))


class DockerfileNegatives(unittest.TestCase):
    def build(self, key):
        lang = {"vitest": "typescript", "jest": "typescript"}.get(key, key)
        return recipes.dockerfile(recipes.detect(lang, RECIPE_FILES[key]), spec_cfg())

    def test_O4_F16_go_dockerfile_has_only_go_tools(self):
        text = self.build("go")
        for needed in ("go-mutesting", "gotestsum"):
            self.assertIn(needed, text)
        for foreign in ("mutmut", "hypothesis", "stryker", "fast-check", "cargo-mutants", "proptest", "nextest",
                        "pytest"):
            self.assertNotIn(foreign, text)

    def test_O4_F16_rust_dockerfile_has_only_rust_tools(self):
        text = self.build("rust")
        for needed in ("cargo-mutants", "proptest", "nextest"):
            self.assertIn(needed, text)
        for foreign in ("mutmut", "hypothesis", "stryker", "fast-check", "go-mutesting", "gotestsum", "pytest"):
            self.assertNotIn(foreign, text)

    def test_O4_F16_typescript_dockerfile_has_only_ts_tools(self):
        text = self.build("vitest")
        for needed in ("@stryker-mutator/core", "fast-check"):
            self.assertIn(needed, text)
        for foreign in ("mutmut", "hypothesis", "go-mutesting", "cargo-mutants", "proptest"):
            self.assertNotIn(foreign, text)

    def test_O4_single_commit_in_every_language(self):
        for key in RECIPE_FILES:
            text = self.build(key)
            with self.subTest(language=key):
                self.assertEqual(len(re.findall(r"git\b[^\n]*\bcommit\b", text)), 1)
                self.assertNotRegex(text, r"git\s+(remote|tag|fetch|pull|clone)")


def request_with(task, n_sentences, ends=None):
    sigs = brief.interface_signatures(task["language"], task["gold_split"]["src"])
    first = "Please add %s in %s." % (sigs[0]["signature"], sigs[0]["path"])
    fillers = ["Filler sentence number %d." % i for i in range(n_sentences - 2)]
    if ends:
        fillers = [f[:-1] + ends[i % len(ends)] for i, f in enumerate(fillers)]
    return " ".join([first] + fillers + [CLOSING])


class BriefPromptAndSentences(unittest.TestCase):
    def setUp(self):
        self.task = make_task("python", title="Add clamp helper to calc", body="The body explains the PR.")
        self.task["issue_bodies"] = ["LINKED-ISSUE-MARKER text"]

    def test_O8_F12_prompt_carries_title_body_issue_signature_paths_and_ambiguity_instruction(self):
        prompt = brief.build_prompt(self.task)
        for needle in ("Add clamp helper to calc", "The body explains the PR.", "LINKED-ISSUE-MARKER text",
                       "src/calc/ops.py", "def clamp(value, lo, hi)", "ambiguous"):
            self.assertIn(needle, prompt)
        self.assertRegex(prompt, r"1 or 2 statements|1 or 2")
        self.assertIn("3 to 12", prompt)
        self.assertIn(CLOSING, prompt)

    def test_O8_F12_prompt_with_no_linked_issue_says_so(self):
        task = make_task("python", title="T", body="B")
        self.assertRegex(brief.build_prompt(task), r"(?s)## Linked issues\s+\(none\)")

    def parse(self, request):
        text = json.dumps({"request": request, "ambiguous": ["S2"], "statements": [
            {"id": "S1", "text": "a", "f2p": [self.task["f2p"][0]]},
            {"id": "S2", "text": "b", "f2p": [self.task["f2p"][1]]}]})
        return brief.parse_brief(text, self.task)

    def test_O8_F12_sentence_count_boundaries_two_three_twelve_thirteen(self):
        for n, ok in ((2, False), (3, True), (12, True), (13, False)):
            with self.subTest(sentences=n):
                if ok:
                    self.parse(request_with(self.task, n))
                else:
                    with self.assertRaises(brief.BriefFormatError):
                        self.parse(request_with(self.task, n))

    def test_O8_F12_question_and_exclamation_marks_split_sentences_too(self):
        self.parse(request_with(self.task, 12, ends=["!", "?"]))
        with self.assertRaises(brief.BriefFormatError):
            self.parse(request_with(self.task, 13, ends=["!", "?"]))

    def test_O8_F12_a_period_inside_a_path_is_not_a_sentence_break(self):
        request = "Please add def clamp(value, lo, hi) in src/calc/ops.py and keep v1.2 style. Do it well. " + CLOSING
        self.parse(request)

    def test_O8_F12_extra_whitespace_and_newlines_do_not_create_empty_sentences(self):
        sigs = brief.interface_signatures("python", self.task["gold_split"]["src"])
        request = ("  Please add %s in %s.\n\n\n   Second one.   \n" % (sigs[0]["signature"], sigs[0]["path"])
                   + CLOSING + "  ")
        self.parse(request.strip() if False else request)

    def test_O8_F12_missing_closing_sentence_still_rejected_at_valid_length(self):
        request = request_with(self.task, 5)[: -len(CLOSING)] + "Thanks a lot."
        with self.assertRaises(brief.BriefFormatError):
            self.parse(request)


class UsersimPromptRules(unittest.TestCase):
    def test_O11_F13_ask_prompt_contains_request_questions_and_the_three_rule_markers(self):
        prompt = usersim.build_prompt(sim_task(), ASK, [])
        self.assertIn("Please add clamp. Implement this and add automated tests.", prompt)
        low = prompt.lower()
        self.assertIn("only from the intent card", low)
        self.assertIn(usersim.FALLBACK_IDLE, prompt)
        self.assertIn("(Recommended)", prompt)
        self.assertIn("contradict", low)
        self.assertIn("set contradiction to true", low)
        self.assertIn('action "stop" only when', low)
        self.assertIn("finished", low)

    def test_O11_F13_idle_prompt_contains_request_last_text_and_rules(self):
        prompt = usersim.build_prompt(sim_task(), IDLE, [])
        self.assertIn("Please add clamp. Implement this and add automated tests.", prompt)
        self.assertIn(IDLE["last_text"], prompt)
        for needle in ("Answer only", "Approve a plan", "stop"):
            self.assertIn(needle, prompt)

    def test_O11_F13_every_statement_text_is_in_the_prompt_and_no_f2p_ids(self):
        prompt = usersim.build_prompt(sim_task(), IDLE, [])
        for statement in STATEMENTS:
            self.assertIn(statement["text"], prompt)
            for test_id in statement["f2p"]:
                self.assertNotIn(test_id, prompt)


class JudgePromptSanitizing(unittest.TestCase):
    def run_judge(self):
        task = make_task("python", brief=dict(BRIEF, status="ok"))
        task["gold_split"] = dict(task["gold_split"], tests=udiff(
            "tests/test_ops.py", None, "def test_h():\n    assert 1  # reference 0123456789abcdef\n# agent-docs/specs/x.md\n"))
        entries = []
        for arm in ("B0", "Bplus", "H"):
            text = ("def test_%s_t():\n    # agent-docs/specs/x.md plan\n"
                    "    assert 1  # run 0123456789abcdef and S1 and S12\n") % arm.lower()
            entries.append({"key": arm + "-r1", "arm": arm, "repeat": 1, "status": "completed", "text": text})
        call = FakeCall(["not json"])
        judge.judge_task(task, entries, call_fn=call, cfg=spec_cfg())
        return call.prompts

    def test_O18_F14_no_entry_key_arm_label_or_source_name_in_any_prompt(self):
        prompts = self.run_judge()
        self.assertGreaterEqual(len(prompts), 10)
        for prompt in prompts:
            for needle in ("B0-r1", "Bplus-r1", "H-r1", "human", "Human", "Bplus", "/workflow-approach"):
                self.assertNotIn(needle, prompt)
            self.assertIsNone(re.search(r"\bB0\b", prompt))

    def test_O18_F14_agent_docs_lines_and_16_hex_ids_are_sanitized_in_every_prompt(self):
        for prompt in self.run_judge():
            self.assertNotIn("agent-docs/", prompt)
            self.assertNotIn("0123456789abcdef", prompt)
            self.assertIn("ID", prompt)

    def test_O18_A4_hex_boundaries(self):
        sixteen = "0123456789abcdef"
        self.assertEqual(judge.anonymize("x %s y" % sixteen, set()), "x ID y")
        self.assertEqual(judge.anonymize("(%s)" % sixteen, set()), "(ID)")
        self.assertEqual(judge.anonymize("%s." % sixteen, set()), "ID.")
        forty = "ab" * 20
        self.assertEqual(judge.anonymize("sha %s end" % forty, set()), "sha %s end" % forty)
        self.assertEqual(judge.anonymize("n %s0 end" % sixteen, set()), "n %s0 end" % sixteen)
        self.assertEqual(judge.anonymize("n %s end" % sixteen[:15], set()), "n %s end" % sixteen[:15])

    def test_O18_A4_two_distinct_ids_in_one_line_are_both_replaced(self):
        self.assertEqual(judge.anonymize("a 0123456789abcdef b fedcba9876543210 c", set()), "a ID b ID c")

    def test_O18_A4_agent_docs_drop_applies_to_the_whole_line_only(self):
        text = "keep\nsee agent-docs/specs/a.md and 0123456789abcdef\nalso keep\n"
        self.assertEqual(judge.anonymize(text, set()), "keep\nalso keep\n")


class ParseAbsoluteV5(unittest.TestCase):
    def parse(self, data):
        return judge.parse_absolute(json.dumps(data), CAND, BRIEF)

    def bad(self, data):
        with self.assertRaises(judge.JudgeFormatError):
            self.parse(data)

    def test_O19_F15_empty_quote_in_a_smell_is_rejected(self):
        data = valid_absolute()
        data["smells"][0]["quote"] = ""
        self.bad(data)

    def test_O19_F15_empty_quote_in_a_desideratum_is_rejected(self):
        for name in judge.DESIDERATA_JUDGED:
            data = valid_absolute()
            data["desiderata"][name]["quote"] = ""
            with self.subTest(desideratum=name):
                self.bad(data)

    def test_O19_F15_each_missing_desideratum_is_rejected(self):
        for name in judge.DESIDERATA_JUDGED:
            data = valid_absolute()
            del data["desiderata"][name]
            with self.subTest(desideratum=name):
                self.bad(data)

    def test_O19_F15_non_integer_scores_are_rejected(self):
        for value in (4.5, "4", True, None, [4]):
            data = valid_absolute()
            data["desiderata"]["isolated"]["score"] = value
            with self.subTest(score=value):
                self.bad(data)

    def test_O19_F15_integer_scores_one_to_five_are_accepted(self):
        for value in (1, 2, 3, 4, 5):
            data = valid_absolute()
            data["desiderata"]["isolated"]["score"] = value
            self.parse(data)

    def test_O19_F15_each_missing_top_level_key_is_rejected(self):
        for key in ("smells", "desiderata", "coverage", "boundary", "error_path"):
            data = valid_absolute()
            del data[key]
            with self.subTest(missing=key):
                self.bad(data)

    def test_O19_F15_non_boolean_flags_are_rejected(self):
        for key in ("boundary", "error_path"):
            for value in (1, "true", None):
                data = valid_absolute()
                data[key] = value
                with self.subTest(key=key, value=value):
                    self.bad(data)

    def test_O19_F15_smell_entries_need_smell_test_and_quote(self):
        for key in ("smell", "test", "quote"):
            data = valid_absolute()
            del data["smells"][0][key]
            with self.subTest(missing=key):
                self.bad(data)

    def test_O19_F15_returned_shape_equals_input_plus_label(self):
        data = valid_absolute()
        self.assertEqual(self.parse(data), dict(data, label="T1"))


class BootstrapV5(unittest.TestCase):
    def test_O21_F16_polarized_two_clusters_span_the_full_range(self):
        out = stats.cluster_bootstrap({"a": [1.0], "b": [-1.0]}, resamples=2000, seed=1)
        self.assertAlmostEqual(out["mean"], 0.0, delta=1e-12)
        self.assertEqual((out["lo"], out["hi"]), (-1.0, 1.0))
        self.assertEqual((out["n_tasks"], out["n_clusters"]), (2, 2))

    def test_O21_F16_whole_clusters_are_resampled_not_tasks(self):
        # k=2 repos drawn with replacement: P(all a)=P(all b)=1/4, so the 2.5/97.5 percentiles are exactly -1 and 1.
        # Task-level resampling of 6 tasks reaches +-1 with probability 1/64 < 2.5%, so lo > -1 and hi < 1.
        out = stats.cluster_bootstrap({"a": [1.0, 1.0, 1.0], "b": [-1.0, -1.0, -1.0]}, resamples=2000, seed=1)
        self.assertAlmostEqual(out["mean"], 0.0, delta=1e-12)
        self.assertEqual((out["lo"], out["hi"]), (-1.0, 1.0))
        self.assertEqual((out["n_tasks"], out["n_clusters"]), (6, 2))

    def test_O21_F16_pooled_mean_for_unequal_cluster_sizes(self):
        diffs = {"a": [0.0] * 8, "b": [1.0]}
        out = stats.cluster_bootstrap(diffs, resamples=4000, seed=1, alpha=0.9)
        self.assertAlmostEqual(out["mean"], 1 / 9, delta=1e-12)
        self.assertAlmostEqual(out["lo"], 1 / 9, delta=1e-9)
        self.assertAlmostEqual(out["hi"], 1 / 9, delta=1e-9)

    def test_O21_F16_unequal_sizes_tails_follow_cluster_draws_not_task_draws(self):
        # Two repos drawn: P(aa)=1/4 -> 0, P(ab or ba)=1/2 -> 1/9, P(bb)=1/4 -> 1.
        # alpha=0.4 takes the 20% and 80% points: lo = 0 and hi = 1 exactly.
        # Task-level resampling (9 draws, P(b)=1/9) would put the 80% point at 2/9.
        out = stats.cluster_bootstrap({"a": [0.0] * 8, "b": [1.0]}, resamples=4000, seed=1, alpha=0.4)
        self.assertEqual(out["lo"], 0.0)
        self.assertEqual(out["hi"], 1.0)

    def test_O21_F16_resamples_argument_is_honored(self):
        diffs = {"a": [1.0, 1.0, 1.0], "b": [-1.0, -1.0, -1.0], "c": [0.0, 0.0]}
        one = stats.cluster_bootstrap(diffs, resamples=1, seed=1)
        self.assertEqual(one["lo"], one["hi"])
        many = stats.cluster_bootstrap(diffs, resamples=3000, seed=1)
        self.assertLess(many["lo"], many["hi"])
        self.assertGreaterEqual(many["lo"], -1.0)
        self.assertLessEqual(many["hi"], 1.0)

    def test_O21_F16_mean_is_pooled_over_tasks_not_clusters(self):
        out = stats.cluster_bootstrap({"a": [0.0, 0.0, 0.0], "b": [3.0]}, resamples=10, seed=1)
        self.assertAlmostEqual(out["mean"], 0.75, delta=1e-12)

    def test_O21_F16_single_cluster_collapses(self):
        out = stats.cluster_bootstrap({"only": [0.2, 0.4]}, resamples=50, seed=1)
        self.assertAlmostEqual(out["lo"], 0.3, delta=1e-12)
        self.assertAlmostEqual(out["hi"], 0.3, delta=1e-12)


class CrossarmV5(unittest.TestCase):
    def test_O17_A6_error_status_of_a_valid_test_counts_as_detection_and_alarm(self):
        matrix = {("A", "B"): {"status": "ok", "results": {"a1": "error"}},
                  ("A", "C"): {"status": "ok", "results": {"a1": "error"}}}
        out = crossarm.detection(matrix, {"A": True, "B": False, "C": True}, {"A": ["a1"]})["A"]
        self.assertEqual((out["detected"], out["detection_rate"]), (1, 1.0))
        self.assertEqual((out["alarmed"], out["false_alarm_rate"]), (1, 1.0))

    def test_O17_A6_skip_and_pass_do_not_count(self):
        matrix = {("A", "B"): {"status": "ok", "results": {"a1": "skip", "a2": "pass"}}}
        out = crossarm.detection(matrix, {"A": True, "B": False}, {"A": ["a1", "a2"]})["A"]
        self.assertEqual(out["detected"], 0)


ATTR_MOD = (r"#\[cfg\(test\)\](?:\s|//[^\n]*\n|/\*.*?\*/|#\[[^\]]*\])*(?:pub(?:\([^)]*\))?\s+)?mod\b")


class RustInlineP2(unittest.TestCase):
    def split(self, text):
        rest, mods = languages.split_rust_inline(text)
        self.assertIsNone(re.search(ATTR_MOD, rest, re.S), rest)
        for mod in mods:
            self.assertIn(mod, text)
        return rest, mods

    def test_O13_P2_intervening_attributes(self):
        rest, mods = self.split("pub fn a() {}\n#[cfg(test)]\n#[allow(dead_code)]\nmod tests {\n    fn t() {}\n}\npub fn z() {}\n")
        self.assertEqual(len(mods), 1)
        self.assertIn("allow(dead_code)", mods[0])
        self.assertIn("pub fn a", rest)
        self.assertIn("pub fn z", rest)
        self.assertNotIn("fn t()", rest)

    def test_O13_P2_intervening_line_and_block_comments(self):
        rest, mods = self.split("pub fn a() {}\n#[cfg(test)]\n// helper tests\n/* block */\nmod tests {\n    fn t() {}\n}\n")
        self.assertEqual(len(mods), 1)
        self.assertNotIn("helper tests", rest)

    def test_O13_P2_pub_and_restricted_pub_modules(self):
        for head in ("pub mod tests", "pub(crate) mod tests", "pub(super) mod tests"):
            rest, mods = self.split("pub fn a() {}\n#[cfg(test)]\n%s {\n    fn t() {}\n}\n" % head)
            with self.subTest(head=head):
                self.assertEqual(len(mods), 1)
                self.assertNotIn("fn t()", rest)

    def test_O13_P2_attribute_and_module_on_one_line(self):
        rest, mods = self.split("#[cfg(test)] mod tests { fn t() {} }\npub fn z() {}\n")
        self.assertEqual(len(mods), 1)
        self.assertIn("pub fn z", rest)

    def test_O13_P2_bodyless_module_declaration_matches_the_p2_pattern_so_it_leaves_rest(self):
        rest, mods = self.split("pub fn a() {}\n#[cfg(test)]\nmod tests;\npub fn z() {}\n")
        self.assertIn("pub fn a", rest)
        self.assertIn("pub fn z", rest)

    def test_O13_P2_cfg_test_fn_and_string_still_stay(self):
        text = "#[cfg(test)]\nfn helper() {}\nconst S: &str = \"#[cfg(test)]\";\n"
        rest, mods = languages.split_rust_inline(text)
        self.assertEqual((rest, mods), (text, []))

    def test_O13_P2_nested_attribute_on_inner_module_moves_with_the_outer_only(self):
        text = "#[cfg(test)]\nmod outer {\n    #[cfg(test)]\n    mod inner { fn t() {} }\n}\npub fn z() {}\n"
        rest, mods = self.split(text)
        self.assertEqual(len(mods), 1)
        self.assertEqual(rest.strip(), "pub fn z() {}")


if __name__ == "__main__":
    unittest.main()

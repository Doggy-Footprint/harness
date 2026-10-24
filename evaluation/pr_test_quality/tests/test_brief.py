import json
import re
import unittest

from evaluation.pr_test_quality import brief
from evaluation.pr_test_quality.tests.fakes import (
    LANG_FIXTURES, FakeCall, TmpCase, brief_json, interface_request, make_task, udiff,
)

CLOSING = "Implement this and add automated tests."


def names_in(sigs, path=None):
    return [s["signature"] for s in sigs if path is None or s["path"] == path]


def has_name(sigs, name, path=None):
    return any(re.search(r"\b%s\b" % re.escape(name), s) for s in names_in(sigs, path))


class InterfaceSignatures(unittest.TestCase):
    def check(self, language, path, old, new, listed, unlisted):
        sigs = brief.interface_signatures(language, udiff(path, old, new))
        for item in sigs:
            self.assertEqual(set(item), {"path", "signature"})
            self.assertEqual(item["path"], path)
        for name in listed:
            self.assertTrue(has_name(sigs, name), "%s missing in %s" % (name, names_in(sigs)))
        for name in unlisted:
            self.assertFalse(has_name(sigs, name), "%s unexpectedly in %s" % (name, names_in(sigs)))
        return sigs

    def test_O6_python_public_added_changed_private_and_unchanged(self):
        old = ("def kept(a):\n    return a\n\n\ndef ctx_fn():\n    return 0\n\n\n"
               "def changed_fn(a):\n    return a\n\n\nclass Stable:\n    def stable_method(self):\n        return 1\n")
        new = ("def kept(a):\n    return a + 1\n\n\ndef ctx_fn():\n    return 0\n\n\n"
               "def changed_fn(a, b=2):\n    return a\n\n\ndef added_fn(x):\n    return x\n\n\n"
               "def _private_new():\n    pass\n\n\nclass Added:\n    def method(self, y):\n        return y\n\n"
               "    def _hidden_method(self):\n        return 0\n\n\n"
               "class Stable:\n    def stable_method(self):\n        return 1\n\n    def new_method(self, z):\n"
               "        return z\n")
        self.check("python", "src/calc/ops.py", old, new,
                   ["changed_fn", "added_fn", "Added", "method", "new_method"],
                   ["kept", "ctx_fn", "_private_new", "_hidden_method", "stable_method"])

    def test_O6_python_signature_text_carries_parameters(self):
        sigs = brief.interface_signatures("python", udiff("src/m.py", None, "def added_fn(x, y=3):\n    return x\n"))
        self.assertEqual(len(sigs), 1)
        self.assertIn("added_fn", sigs[0]["signature"])
        self.assertIn("y=3", sigs[0]["signature"])

    def test_O6_two_files_keep_their_own_paths(self):
        diff = udiff("src/a.py", None, "def only_a():\n    pass\n") + udiff("src/b.py", None, "def only_b():\n    pass\n")
        sigs = brief.interface_signatures("python", diff)
        self.assertTrue(has_name(sigs, "only_a", "src/a.py"))
        self.assertFalse(has_name(sigs, "only_a", "src/b.py"))
        self.assertTrue(has_name(sigs, "only_b", "src/b.py"))

    def test_O6_typescript_exports_only(self):
        old = ("export function keptFn(a: number): number {\n  return a;\n}\n\nfunction internalFn(): void {}\n\n"
               "export function changedFn(a: number): number {\n  return a;\n}\n")
        new = ("export function keptFn(a: number): number {\n  return a + 1;\n}\n\nfunction internalFn(): void {}\n\n"
               "export function changedFn(a: number, b: number): number {\n  return a;\n}\n\n"
               "export function addedFn(x: string): string {\n  return x;\n}\n\n"
               "export class AddedClass {}\n\nexport const addedConst = 5;\n\nfunction newInternal() {}\n")
        self.check("typescript", "src/ops.ts", old, new,
                   ["changedFn", "addedFn", "AddedClass", "addedConst"],
                   ["keptFn", "internalFn", "newInternal"])

    def test_O6_go_exported_funcs_methods_types(self):
        old = ("package ops\n\nfunc Kept(a int) int {\n\treturn a\n}\n\nfunc lowerOld() {\n}\n\n"
               "func Changed(a int) int {\n\treturn a\n}\n")
        new = ("package ops\n\nfunc Kept(a int) int {\n\treturn a + 1\n}\n\nfunc lowerOld() {\n}\n\n"
               "func Changed(a int, b int) int {\n\treturn a\n}\n\nfunc Added(a int) int {\n\treturn a\n}\n\n"
               "func (r *Thing) Method(x int) error {\n\treturn nil\n}\n\nfunc (r *Thing) lowerMethod() {\n}\n\n"
               "type Widget struct{}\n\ntype hidden struct{}\n\nfunc lowerNew() {\n}\n")
        self.check("go", "ops/ops.go", old, new,
                   ["Changed", "Added", "Method", "Widget"],
                   ["Kept", "lowerOld", "lowerMethod", "hidden", "lowerNew"])

    def test_O6_rust_pub_items_only(self):
        old = ("pub fn kept(a: i32) -> i32 {\n    a\n}\n\nfn private_old() {}\n\n"
               "pub fn changed_fn(a: i32) -> i32 {\n    a\n}\n")
        new = ("pub fn kept(a: i32) -> i32 {\n    a + 1\n}\n\nfn private_old() {}\n\n"
               "pub fn changed_fn(a: i32, b: i32) -> i32 {\n    a\n}\n\npub fn added_fn(x: i32) -> i32 {\n    x\n}\n\n"
               "pub struct AddedStruct {\n    pub field: i32,\n}\n\nfn private_new() {}\n\nstruct Hidden;\n\n"
               "impl AddedStruct {\n    pub fn method(&self) -> i32 {\n        1\n    }\n\n    fn hidden_method(&self) {}\n}\n")
        self.check("rust", "src/lib.rs", old, new,
                   ["changed_fn", "added_fn", "AddedStruct", "method"],
                   ["kept", "private_old", "private_new", "Hidden", "hidden_method"])

    def test_O6_empty_diff_gives_no_signatures(self):
        for lang in ("python", "typescript", "go", "rust"):
            self.assertEqual(brief.interface_signatures(lang, ""), [])


def task_with_tests(language, text, path=None):
    task = make_task(language)
    path = path or LANG_FIXTURES[language]["test_path"]
    diff = udiff(path, None, text)
    task["gold_split"] = dict(task["gold_split"], tests=diff)
    task["gold_patch"] = task["gold_split"]["src"] + diff
    task["gold_after"] = dict(task["gold_after"], **{path: text})
    return task


class ForbiddenTerms(unittest.TestCase):
    def test_O7_term_classes_per_language(self):
        for language, fx in LANG_FIXTURES.items():
            with self.subTest(language=language):
                task = make_task(language)
                terms = brief.forbidden_terms(task)
                self.assertIsInstance(terms, set)
                self.assertIn(fx["name"], terms)
                self.assertIn(fx["test_path"], terms)
                self.assertIn(fx["test_path"].rsplit("/", 1)[-1], terms)
                self.assertIn(fx["literal"], terms)
                self.assertIn(fx["defined"], terms)

    def test_O7_non_forbidden_material_per_language(self):
        for language, fx in LANG_FIXTURES.items():
            with self.subTest(language=language):
                task = make_task(language)
                terms = brief.forbidden_terms(task)
                self.assertNotIn(fx["plain"], terms)
                self.assertNotIn(fx["src_path"], terms)
                self.assertNotIn("clamp", {t.lower() for t in terms})
                self.assertEqual(brief.leaks("a %s b" % fx["plain"], task), [])

    def test_O7_C16_literal_length_boundary(self):
        task = make_task("python")
        terms = brief.forbidden_terms(task)
        self.assertNotIn("ab", terms)
        self.assertNotIn("  x ", terms)
        self.assertNotIn("x", terms)
        self.assertEqual(brief.leaks("ab", task), [])
        self.assertEqual(brief.leaks("  x ", task), [])
        three = task_with_tests("python", "def test_t():\n    assert f() == \"a_c\"\n")
        self.assertIn("a_c", brief.forbidden_terms(three))
        self.assertEqual(brief.leaks("use a_c here", three), ["a_c"])
        self.assertEqual(brief.leaks("use ab here", three), [])

    def test_O7_literal_with_three_non_space_chars_across_spaces_is_forbidden(self):
        task = task_with_tests("python", "def test_t():\n    assert f() == \"a b c\"\n")
        self.assertEqual(brief.leaks("see a b c now", task), ["a b c"])
        two = task_with_tests("python", "def test_t():\n    assert f() == \" a  b \"\n")
        self.assertNotIn(" a  b ", brief.forbidden_terms(two))
        self.assertNotIn("a  b", brief.forbidden_terms(two))

    def test_O7_assertion_keyword_per_language(self):
        cases = {
            "python": ("def test_t():\n    assert f() == \"py-assert-lit\"\n    assert g() == 'py-single-lit'\n"
                       "    print(\"py-plain-log\")\n    expect(\"py-cross-expect\")\n",
                       ["py-assert-lit", "py-single-lit"], ["py-plain-log", "py-cross-expect"]),
            "typescript": ("it(\"works\", () => {\n  expect(f()).toBe(\"ts-expect-lit\");\n"
                           "  assert.equal(g(), 'ts-assert-lit');\n  console.log(\"ts-plain-log\");\n"
                           "  t.Error(\"ts-cross-go\");\n});\n",
                           ["ts-expect-lit", "ts-assert-lit"], ["ts-plain-log", "ts-cross-go"]),
            "go": ("func TestX(t *testing.T) {\n\tt.Error(\"go-terror-lit\")\n\tt.Fatal(\"go-tfatal-lit\")\n"
                   "\tassert.Equal(t, f(), \"go-assert-lit\")\n\trequire.Equal(t, g(), \"go-require-lit\")\n"
                   "\tfmt.Println(\"go-plain-log\")\n\texpect(\"go-cross-ts\")\n}\n",
                   ["go-terror-lit", "go-tfatal-lit", "go-assert-lit", "go-require-lit"],
                   ["go-plain-log", "go-cross-ts"]),
            "rust": ("#[test]\nfn x() {\n    assert!(f() == \"rs-assert-lit\");\n    assert_eq!(g(), \"rs-eq-lit\");\n"
                     "    println!(\"rs-plain-log\");\n    expect(\"rs-cross-ts\");\n}\n",
                     ["rs-assert-lit", "rs-eq-lit"], ["rs-plain-log", "rs-cross-ts"]),
        }
        for language, (text, forbidden, allowed) in cases.items():
            task = task_with_tests(language, text)
            terms = brief.forbidden_terms(task)
            for lit in forbidden:
                with self.subTest(language=language, lit=lit):
                    self.assertIn(lit, terms)
            for lit in allowed:
                with self.subTest(language=language, lit=lit):
                    self.assertNotIn(lit, terms)

    def test_O7_only_added_lines_count_for_literals(self):
        path = "tests/test_ops.py"
        old = ("def test_a():\n    assert f() == \"removed-lit-aa\"\n    assert g() == \"context-lit-bb\"\n")
        new = ("def test_a():\n    assert g() == \"context-lit-bb\"\n    assert h() == \"added-lit-cc\"\n")
        task = make_task("python")
        diff = udiff(path, old, new)
        task["gold_split"] = dict(task["gold_split"], tests=diff)
        task["gold_patch"] = task["gold_split"]["src"] + diff
        terms = brief.forbidden_terms(task)
        self.assertIn("added-lit-cc", terms)
        self.assertNotIn("removed-lit-aa", terms)
        self.assertNotIn("context-lit-bb", terms)

    def test_O7_name_defined_in_src_and_tests_is_not_test_only(self):
        text = "from calc.ops import shared_helper\n\ndef defined_in_tests_only_q():\n    pass\n\ndef shared_helper():\n    pass\n"
        task = task_with_tests("python", text)
        task["gold_split"] = dict(task["gold_split"], src=udiff("src/calc/ops.py", None, "def shared_helper():\n    pass\n"))
        terms = brief.forbidden_terms(task)
        self.assertIn("defined_in_tests_only_q", terms)
        self.assertNotIn("shared_helper", terms)

    def test_O7_F5_merge_sha_and_its_short_form_are_forbidden(self):
        from evaluation.pr_test_quality.tests.fakes import MERGE_SHA
        for language in LANG_FIXTURES:
            task = make_task(language)
            terms = brief.forbidden_terms(task)
            with self.subTest(language=language):
                self.assertIn(MERGE_SHA, terms)
                self.assertIn(MERGE_SHA[:7], terms)
                self.assertIn(MERGE_SHA[:7], brief.leaks("commit %s landed" % MERGE_SHA[:7], task))

    def test_O7_leaks_sorted_deduplicated_and_exact(self):
        task = make_task("python")
        text = "alpha five-marker-zq beta five-marker-zq gamma build_gold_fixture_zq"
        self.assertEqual(brief.leaks(text, task), sorted(["five-marker-zq", "build_gold_fixture_zq"]))
        self.assertEqual(brief.leaks("nothing of note here", task), [])

    def test_O7_leaks_finds_f2p_name_path_and_basename(self):
        task = make_task("python")
        self.assertIn("test_clamp_upper_bound_zq", brief.leaks("run test_clamp_upper_bound_zq please", task))
        self.assertIn("tests/test_ops.py", brief.leaks("open tests/test_ops.py", task))
        self.assertEqual(brief.leaks("open test_ops.py", task), ["test_ops.py"])

    def test_O7_parametrized_f2p_name_is_reported_without_case_suffix_in_text(self):
        task = make_task("python")
        self.assertIn("test_param_case_zq", brief.leaks("the test_param_case_zq case", task))


class Parse(TmpCase):
    def setUp(self):
        super().setUp()
        self.task = make_task("python")

    def test_O8_C14_valid_brief_parsed(self):
        parsed = brief.parse_brief(brief_json(self.task), self.task)
        self.assertEqual(set(parsed), {"request", "statements", "ambiguous"})
        self.assertTrue(parsed["request"].endswith(CLOSING))
        self.assertEqual([s["id"] for s in parsed["statements"]], ["S1", "S2"])
        self.assertEqual({t for s in parsed["statements"] for t in s["f2p"]}, set(self.task["f2p"]))
        self.assertEqual(parsed["ambiguous"], ["S2"])

    def test_O8_ambiguous_ids_are_kept(self):
        parsed = brief.parse_brief(brief_json(self.task, ambiguous=["S2"]), self.task)
        self.assertEqual(parsed["ambiguous"], ["S2"])
        parsed = brief.parse_brief(brief_json(self.task, ambiguous=["S1", "S2"]), self.task)
        self.assertEqual(parsed["ambiguous"], ["S1", "S2"])

    def test_O8_F8_several_statements_need_one_or_two_ambiguous_ids(self):
        for label, ambiguous in (("none", []), ("three", ["S1", "S2", "S3"]), ("unknown", ["S9"])):
            with self.subTest(ambiguous=label):
                statements = [{"id": "S%d" % i, "text": "Behavior %d." % i, "f2p": [self.task["f2p"][i % 2]]}
                              for i in (1, 2, 3)]
                with self.assertRaises(brief.BriefFormatError):
                    brief.parse_brief(brief_json(self.task, statements=statements, ambiguous=ambiguous), self.task)

    def test_O8_F8_single_statement_must_have_empty_ambiguous(self):
        task = make_task("typescript")
        self.assertEqual(len(task["f2p"]), 1)
        ok = brief.parse_brief(brief_json(task, ambiguous=[]), task)
        self.assertEqual(ok["ambiguous"], [])
        with self.assertRaises(brief.BriefFormatError):
            brief.parse_brief(brief_json(task, ambiguous=["S1"]), task)

    def test_O8_request_missing_closing_sentence_rejected(self):
        request = interface_request(self.task)[: -len(CLOSING)].rstrip() + " Thanks."
        with self.assertRaises(brief.BriefFormatError):
            brief.parse_brief(brief_json(self.task, request=request), self.task)

    def test_O8_request_missing_signature_or_path_rejected(self):
        sigs = brief.interface_signatures("python", self.task["gold_split"]["src"])
        self.assertTrue(sigs)
        full = interface_request(self.task)
        for label, request in (("signature", full.replace(sigs[0]["signature"], "the helper")),
                               ("path", full.replace(sigs[0]["path"], "the module"))):
            with self.subTest(missing=label):
                self.assertNotEqual(request, full)
                with self.assertRaises(brief.BriefFormatError):
                    brief.parse_brief(brief_json(self.task, request=request), self.task)

    def test_O8_statements_not_covering_every_f2p_rejected(self):
        statements = [{"id": "S1", "text": "Only one behavior.", "f2p": [self.task["f2p"][0]]}]
        with self.assertRaises(brief.BriefFormatError):
            brief.parse_brief(brief_json(self.task, statements=statements), self.task)

    def test_O8_statement_without_f2p_mapping_rejected(self):
        statements = [{"id": "S1", "text": "A.", "f2p": self.task["f2p"]}, {"id": "S2", "text": "B.", "f2p": []}]
        with self.assertRaises(brief.BriefFormatError):
            brief.parse_brief(brief_json(self.task, statements=statements), self.task)

    def test_O8_non_json_rejected(self):
        for text in ("", "just prose", "{\"request\": "):
            with self.subTest(text=text):
                with self.assertRaises(brief.BriefFormatError):
                    brief.parse_brief(text, self.task)

    def test_O8_error_class_is_value_error(self):
        self.assertTrue(issubclass(brief.BriefFormatError, ValueError))


class Prompt(unittest.TestCase):
    def test_O8_prompt_carries_gold_tests_signatures_and_closing_sentence(self):
        task = make_task("python")
        prompt = brief.build_prompt(task)
        self.assertIsInstance(prompt, str)
        self.assertIn("test_clamp_upper_bound_zq", prompt)
        self.assertRegex(prompt, r"\bclamp\b")
        self.assertIn(CLOSING, prompt)


class MakeBrief(TmpCase):
    def setUp(self):
        super().setUp()
        self.task = make_task("python")
        self.cfg_ = self.cfg()

    def leaky_request(self, term):
        base = interface_request(self.task)
        return base[: -len(CLOSING)] + "Check %s too. " % term + CLOSING

    def make(self, script):
        call = FakeCall(script)
        return brief.make_brief(self.task, call_fn=call, cfg=self.cfg_), call

    def test_O8_ok_first_try(self):
        out, call = self.make([brief_json(self.task)])
        self.assertEqual((out["status"], out["attempts"], out["reason"]), ("ok", 1, "ok"))
        self.assertEqual(len(call.calls), 1)
        self.assertEqual(call.calls[0]["model"], "claude-opus-5-5")
        self.assertEqual(call.calls[0]["effort"], "medium")
        self.assertTrue(out["request"].endswith(CLOSING))
        self.assertEqual([s["id"] for s in out["statements"]], ["S1", "S2"])

    def test_O8_C15_leak_in_request_then_ok(self):
        bad = brief_json(self.task, request=self.leaky_request("test_clamp_upper_bound_zq"))
        out, call = self.make([bad, brief_json(self.task)])
        self.assertEqual((out["status"], out["attempts"]), ("ok", 2))
        self.assertEqual(len(call.calls), 2)
        self.assertNotIn("test_clamp_upper_bound_zq", out["request"])

    def test_O8_leak_in_intent_card_statement_is_regenerated(self):
        leaky = [{"id": "S1", "text": "Returns five-marker-zq for five.", "f2p": [self.task["f2p"][0]]},
                 {"id": "S2", "text": "Other behavior.", "f2p": [self.task["f2p"][1]]}]
        out, call = self.make([brief_json(self.task, statements=leaky), brief_json(self.task)])
        self.assertEqual((out["status"], out["attempts"]), ("ok", 2))
        self.assertNotIn("five-marker-zq", json.dumps(out["statements"]))

    def test_O8_C15_three_leaks_drop_the_task(self):
        bad = brief_json(self.task, request=self.leaky_request("test_ops.py"))
        out, call = self.make([bad])
        self.assertEqual((out["status"], out["attempts"], out["reason"]), ("dropped", 3, "leak"))
        self.assertEqual(len(call.calls), 3)

    def test_O8_format_errors_count_as_attempts_then_drop(self):
        out, call = self.make(["not json at all"])
        self.assertEqual((out["status"], out["attempts"], out["reason"]), ("dropped", 3, "format"))
        self.assertEqual(len(call.calls), 3)

    def test_O8_format_error_then_ok(self):
        out, call = self.make(["garbage", brief_json(self.task)])
        self.assertEqual((out["status"], out["attempts"]), ("ok", 2))

    def test_O8_uncovered_f2p_counts_as_format_attempt(self):
        short = [{"id": "S1", "text": "Only one.", "f2p": [self.task["f2p"][0]]}]
        out, call = self.make([brief_json(self.task, statements=short), brief_json(self.task)])
        self.assertEqual((out["status"], out["attempts"]), ("ok", 2))

    def test_O8_attempts_come_from_cfg(self):
        self.cfg_ = self.cfg(brief={"attempts": 2})
        out, call = self.make(["garbage"])
        self.assertEqual((out["status"], out["attempts"]), ("dropped", 2))
        self.assertEqual(len(call.calls), 2)


if __name__ == "__main__":
    unittest.main()

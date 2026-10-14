"""Spec 54ad633104783ebe: selfcheck.informed (O7 forbidden_terms, O8 leaks, O9 prompt/parse, O10 respond, O11 Relay).

Expected values are written from the spec text (R10-R15) and the instance text, never from the module under test.
Where an oracle calls informed.parse_response/build_prompt it is only to restate that another Signature function
received exactly their output (R14), not to compute an expectation for them.
"""
import copy
import json
import re
import shutil
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from selfcheck import informed
from selfcheck.tests import agent_fakes as F
from selfcheck.tests import review_fakes as R

POOL = F.pool_rows()

# ---------------------------------------------------------------------------------------------
# O7: expected sets derived by hand from the instance text (R12)
# ---------------------------------------------------------------------------------------------

ASTROPY = "astropy__astropy-14365"
DJANGO = "django__django-15731"
SEABORN = "mwaskom__seaborn-3187"

EXPECTED_ASTROPY = {
    "astropy/io/ascii/tests/test_qdp.py::test_roundtrip[True]", "test_roundtrip",
    "astropy/io/ascii/qdp.py", "qdp.py", "astropy/io/ascii/tests/test_qdp.py", "test_qdp.py",
}
EXPECTED_DJANGO = {
    "test_manager_method_signature (basic.tests.ManagerTest)", "test_manager_method_signature",
    "basic.tests.ManagerTest", "django/db/models/manager.py", "manager.py", "tests/basic/tests.py", "tests.py",
}
EXPECTED_SEABORN = {
    "tests/_core/test_plot.py::TestLegend::test_legend_has_no_offset",
    "tests/test_relational.py::TestRelationalPlotter::test_legend_has_no_offset",
    "test_legend_has_no_offset",
    "seaborn/_core/scales.py", "scales.py", "seaborn/utils.py", "utils.py",
    "tests/_core/test_plot.py", "test_plot.py", "tests/test_relational.py", "test_relational.py",
}

PATCH_EXTRA = (
    "diff --git a/pkg/extra_mod.py b/pkg/extra_mod.py\n--- a/pkg/extra_mod.py\n+++ b/pkg/extra_mod.py\n"
    "@@ -1,4 +1,5 @@ def hunk_context_name():\n"
    " def context_only_fn():\n"
    "-class RemovedThing(Base):\n"
    "+def added_helper(x):\n"
    "+    def inner_method(self):\n"
    "+class NewKlass:\n"
)
TEST_PATCH_EXTRA = (
    "diff --git a/tests/test_extra.py b/tests/test_extra.py\n--- a/tests/test_extra.py\n+++ b/tests/test_extra.py\n"
    "@@ -1,1 +1,6 @@\n"
    '+    assert out == "abc"\n'
    '+    assert flag == "ab"\n'
    "+    assert v == 'single-q'\n"
    '+    note = "nonassert-literal"\n'
    "+    def helper_in_test_patch():\n"
    '+    self.assertEqual(x, "assertEqual-lit")\n'
    '+    result = check(1) and assert_that("nonword-lit")\n'
    '+    assert out == "   "\n'
    '+    value == "mid" if assert_ok else "zzzz"; assert out2 == "mid-word"\n'
)


class ForbiddenTermsTests(unittest.TestCase):
    def terms(self, iid, **over):
        return informed.forbidden_terms(dict(POOL[iid], **over))

    def test_o7_pytest_id_with_param_suffix_gives_exactly_the_hand_derived_set(self):
        self.assertEqual(self.terms(ASTROPY), EXPECTED_ASTROPY)

    def test_o7_django_id_style_gives_exactly_the_hand_derived_set(self):
        self.assertEqual(self.terms(DJANGO), EXPECTED_DJANGO)

    def test_o7_name_is_taken_after_the_last_double_colon_and_every_id_contributes(self):
        self.assertEqual(self.terms(SEABORN), EXPECTED_SEABORN)

    def test_o7_def_and_class_names_only_from_added_or_removed_patch_lines(self):
        row = POOL[ASTROPY]
        got = informed.forbidden_terms(dict(row, patch=row["patch"] + PATCH_EXTRA))
        expected = EXPECTED_ASTROPY | {"pkg/extra_mod.py", "extra_mod.py", "added_helper", "inner_method",
                                       "NewKlass", "RemovedThing"}
        self.assertEqual(got, expected)
        for absent in ("context_only_fn", "hunk_context_name"):
            self.assertNotIn(absent, got)

    def test_o7_test_patch_defs_are_not_terms(self):
        # the real astropy test_patch adds `def lowercase_header`
        self.assertIn("def lowercase_header", POOL[ASTROPY]["test_patch"])
        self.assertNotIn("lowercase_header", self.terms(ASTROPY))

    def test_o7_assert_literals_of_length_three_or_more_only_from_assert_lines(self):
        row = POOL[ASTROPY]
        got = informed.forbidden_terms(dict(row, test_patch=row["test_patch"] + TEST_PATCH_EXTRA))
        expected = EXPECTED_ASTROPY | {"tests/test_extra.py", "test_extra.py", "abc", "single-q", "mid", "zzzz", "mid-word"}
        self.assertEqual(got, expected)
        for absent in ("ab", "nonassert-literal", "helper_in_test_patch", "assertEqual-lit", "nonword-lit", "   "):
            self.assertNotIn(absent, got)

    def test_o7_non_assert_literal_in_the_real_test_patch_is_excluded(self):
        # `+@pytest.mark.parametrize("lowercase", ...)` carries a 9 character literal on a line without assert
        self.assertIn('"lowercase"', POOL[ASTROPY]["test_patch"])
        self.assertNotIn("lowercase", self.terms(ASTROPY))

    def test_o7_terms_follow_the_instance_not_a_constant(self):
        self.assertTrue(self.terms(ASTROPY).isdisjoint(self.terms(DJANGO)))


# ---------------------------------------------------------------------------------------------
# synthetic gold instance for O8-O11
# ---------------------------------------------------------------------------------------------

GOLD_LINE_PATCH = "return widget_gold_line(widget)"
GOLD_LINE_TEST = 'assert fmt(1234) == "1,234"'
INST = {
    "instance_id": "proj__widget-1",
    "problem_statement": "Rendering a blank widget crashes inside compute_layout. Expected an empty string.",
    "FAIL_TO_PASS": ["tests/test_w.py::test_x", "tests/test_w.py::TestW::test_render_blank[a-b]"],
    "patch": (
        "diff --git a/src/pkg/widget_core.py b/src/pkg/widget_core.py\n--- a/src/pkg/widget_core.py\n"
        "+++ b/src/pkg/widget_core.py\n@@ -1,2 +1,3 @@\n"
        "+def compute_layout(widget, mode):\n"
        "+    " + GOLD_LINE_PATCH + "\n"
    ),
    "test_patch": (
        "diff --git a/tests/test_w.py b/tests/test_w.py\n--- a/tests/test_w.py\n+++ b/tests/test_w.py\n"
        "@@ -1,1 +1,3 @@\n"
        "+    " + GOLD_LINE_TEST + "\n"
        '+    assert render_hint() == "zzz"\n'
    ),
}
GOLD_FACT = "GOLD-FACT-ONE"
ASK_Q1, ASK_Q2 = "Which layout?", "Keep behaviour?"


def ask_request(n=1, extra_option_text="keep it simple"):
    return {"n": n, "kind": "ask", "questions": [
        {"question": ASK_Q1, "header": "H1", "multiSelect": False,
         "options": [{"label": "Alpha (Recommended)", "description": extra_option_text}, {"label": "Beta", "description": "b"}]},
        {"question": ASK_Q2, "header": "H2", "multiSelect": False,
         "options": [{"label": "Yes", "description": "y"}, {"label": "No", "description": "n"}]},
    ]}


def idle_request(n=2, brief="I plan to special-case blanks."):
    return {"n": n, "kind": "idle", "brief": brief}


def raw_ask(a1=None, a2=None, facts=()):
    return json.dumps({"answers": {ASK_Q1: a1, ASK_Q2: a2}, "gold_facts_used": list(facts)})


def raw_idle(message, facts=()):
    return json.dumps({"message": message, "gold_facts_used": list(facts)})


class LeaksTests(unittest.TestCase):
    def leaks(self, text, request=None):
        return informed.leaks(text, INST, request or ask_request())

    def test_o8_term_absent_reports_nothing(self):
        self.assertEqual(self.leaks("Nothing special here."), [])

    def test_o8_term_present_in_the_issue_is_exempt(self):
        self.assertEqual(self.leaks("Look at compute_layout."), [])

    def test_o8_term_present_in_the_serialized_request_is_exempt(self):
        req = idle_request(brief="Is widget_core.py right, and is 1,234 the output?")
        self.assertEqual(self.leaks("edit widget_core.py and print 1,234", req), [])
        self.assertEqual(self.leaks("return zzz", ask_request(extra_option_text="keep zzz")), [])

    def test_o8_exemption_is_per_term(self):
        req = idle_request(brief="Is widget_core.py right?")
        self.assertEqual(self.leaks("widget_core.py then zzz", req), ["zzz"])

    def test_o8_identifier_term_matches_on_word_boundaries(self):
        for text in ("Call test_x now.", "test_x.", "(test_x)", "x test_x"):
            with self.subTest(text):
                self.assertEqual(self.leaks(text), ["test_x"])

    def test_o8_identifier_inside_a_longer_word_is_no_leak(self):
        self.assertEqual(self.leaks("test_xy and mytest_x and test_x_ and test_x1"), [])

    def test_o8_non_identifier_term_matches_as_a_case_sensitive_substring(self):
        self.assertEqual(self.leaks("total x1,2345y"), ["1,234"])
        self.assertEqual(self.leaks("WIDGET_CORE.PY"), [])
        self.assertEqual(self.leaks("see xwidget_core.py"), ["widget_core.py"])

    def test_o8_result_is_sorted_and_deduplicated(self):
        self.assertEqual(self.leaks("zzz test_x 1,234 zzz test_x"), ["1,234", "test_x", "zzz"])
        self.assertEqual(self.leaks("src/pkg/widget_core.py"), ["src/pkg/widget_core.py", "widget_core.py"])

    def test_o8_c14_gold_file_basename_not_in_issue_or_request_leaks(self):
        self.assertEqual(self.leaks("Edit widget_core.py to fix"), ["widget_core.py"])

    def test_o8_follows_the_instance(self):
        other = dict(INST, problem_statement="Rendering mentions test_x already.")
        self.assertEqual(informed.leaks("call test_x", other, ask_request()), [])


# ---------------------------------------------------------------------------------------------
# O9
# ---------------------------------------------------------------------------------------------

STRICT = lambda x: bool(BuildPromptTests.STRICT_NEG.search(x))


def has_any(text, words):
    low = text.lower()
    return any(w.lower() in low for w in words)


class BuildPromptTests(unittest.TestCase):
    NEUTRAL = {
        "instance_id": "n__n-1", "problem_statement": "ZQISSUE alpha beta.", "patch": "ZQPATCH-LINE",
        "test_patch": "ZQTESTPATCH-LINE", "FAIL_TO_PASS": ["zq/zt.py::zqtest"],
    }
    NEG = re.compile(r"\b(never|not|do not|don't|must not|only|without|rather than|instead of)\b|n't", re.I)
    STRICT_NEG = re.compile(r"\b(never|not|do not|don't|must not)\b|n't", re.I)

    def role_text(self, request):
        """The prompt with every inserted instance/request string removed, split into sentences."""
        text = informed.build_prompt(self.NEUTRAL, request)
        inserted = [json.dumps(request), json.dumps(request, indent=2), json.dumps(request, ensure_ascii=False)]
        inserted += [self.NEUTRAL[k] for k in ("problem_statement", "patch", "test_patch")]
        inserted += self.NEUTRAL["FAIL_TO_PASS"]

        def strings(value):
            if isinstance(value, str):
                yield value
            elif isinstance(value, dict):
                for v in value.values():
                    yield from strings(v)
            elif isinstance(value, list):
                for v in value:
                    yield from strings(v)

        inserted += [v for v in strings(request) if len(v) > 5 and v != request["kind"]]
        for piece in sorted(inserted, key=len, reverse=True):
            text = text.replace(piece, " ")
        return [x.strip() for x in re.split(r"(?<=[.!?:;])\s+|\n+", text) if x.strip()]

    def requests(self):
        return (
            {"n": 1, "kind": "ask", "questions": [{"question": "Which path should we take?", "options": [
                {"label": "Path one", "description": "first route"}]}]},
            {"n": 2, "kind": "idle", "brief": "I finished the first route."},
        )

    @staticmethod
    def has(sentences, subject, predicate=None):
        return [x for x in sentences if re.search(subject, x, re.I) and (predicate is None or predicate(x))]

    def test_o9_constraints_are_stated_with_the_right_polarity(self):
        for request in self.requests():
            sents = self.role_text(request)
            kind = request["kind"]
            with self.subTest(kind=kind):
                # never hand over the solution
                about = self.has(sents, r"\bsolution\b")
                self.assertTrue([x for x in about if self.NEG.search(x)], "no negated sentence about the solution")
                handover = r"\b(hand(s|ing)? over|give|gives|giving|share|reveal|tell|provide|write|supply|state)\b"
                self.assertEqual([x for x in about if re.search(handover, x, re.I) and not self.NEG.search(x)], [],
                                 "affirmative hand-over of the solution")
                # never name tests, assert values, files, code
                subj = r"\b(tests?|files?|code|assert(ion)?s?)\b"
                about = self.has(sents, subj)
                self.assertTrue([x for x in about if self.NEG.search(x) and re.search(r"\btests?\b", x, re.I)
                                 and re.search(r"\bfiles?\b", x, re.I) and re.search(r"\bcode\b", x, re.I)],
                                "no negated sentence naming tests, files and code")
                self.assertEqual([x for x in about if not self.NEG.search(x)
                                  and re.search(r"\b(name|mention|cite|reveal|give|include|quote|state)\b", x, re.I)], [])
                # answer only what was asked or presented for approval
                self.assertTrue(self.has(sents, r"\basked\b", lambda x: re.search(r"\bonly\b", x, re.I)
                                         and not STRICT(x) and re.search(r"approv", x, re.I)))
                # only observable behavior
                self.assertTrue(self.has(sents, r"\bobservable\b", lambda x: re.search(r"\bonly\b", x, re.I)
                                         and not STRICT(x)))
                self.assertEqual(self.has(sents, r"\bobservable\b", STRICT), [])
                # null when there is nothing to add
                nulls = self.has(sents, r"\bnull\b", lambda x: re.search(r"\bnothing\b|\bno\b", x, re.I)
                                 and not re.search(r"\b(never|not|don't)\b[^.]*\bnull\b", x, re.I))
                self.assertTrue(nulls, "no sentence saying to return null when there is nothing to add")
                # role: catch a wrong direction
                self.assertTrue(self.has(sents, r"\bwrong\b", lambda x: not STRICT(x)), "no affirmative wrong-direction role")
                # one JSON object listing gold_facts_used
                self.assertTrue(self.has(sents, r"\bJSON\b", lambda x: re.search(r"\b(one|single)\b", x, re.I)))
                self.assertTrue(self.has(sents, r"gold_facts_used"))

    def prompts(self):
        return informed.build_prompt(INST, ask_request()), informed.build_prompt(INST, idle_request())

    def test_o9_prompt_carries_issue_gold_patch_test_patch_fail_to_pass_and_request(self):
        ask, idle = self.prompts()
        for text in (ask, idle):
            self.assertIn(INST["problem_statement"], text)
            self.assertIn(INST["patch"], text)
            self.assertIn(INST["test_patch"], text)
            for test_id in INST["FAIL_TO_PASS"]:
                self.assertIn(test_id, text)
        self.assertIn(ASK_Q1, ask)
        self.assertIn(ASK_Q2, ask)
        self.assertIn("keep it simple", ask)
        self.assertIn("I plan to special-case blanks.", idle)
        self.assertNotIn("I plan to special-case blanks.", ask)

    def test_o9_prompt_names_the_response_shape_of_its_request_kind(self):
        ask, idle = self.prompts()
        self.assertIn("answers", ask)
        self.assertIn("message", idle)

    def test_o9_prompt_follows_the_instance(self):
        other = dict(INST, problem_statement="OTHER-ISSUE-TEXT", patch="OTHER-PATCH", test_patch="OTHER-TP",
                     FAIL_TO_PASS=["other/test.py::t"])
        text = informed.build_prompt(other, ask_request())
        for needle in ("OTHER-ISSUE-TEXT", "OTHER-PATCH", "OTHER-TP", "other/test.py::t"):
            self.assertIn(needle, text)
        self.assertNotIn(INST["patch"], text)


class ParseResponseTests(unittest.TestCase):
    def parse(self, text, request=None):
        return informed.parse_response(text, request or ask_request())

    def bad(self, text, request=None):
        with self.assertRaises(informed.ResponseFormatError):
            informed.parse_response(text, request or ask_request())

    def test_o9_valid_ask(self):
        self.assertEqual(
            self.parse(raw_ask("a", None, ["f1", "f2"])),
            {"answers": {ASK_Q1: "a", ASK_Q2: None}, "gold_facts_used": ["f1", "f2"]},
        )

    def test_o9_valid_idle(self):
        req = idle_request()
        self.assertEqual(self.parse(raw_idle("m", ["f"]), req), {"message": "m", "gold_facts_used": ["f"]})
        self.assertEqual(self.parse(raw_idle(None), req), {"message": None, "gold_facts_used": []})

    def test_o9_missing_question_becomes_null_and_missing_facts_become_empty(self):
        text = json.dumps({"answers": {ASK_Q1: "a"}})
        self.assertEqual(self.parse(text), {"answers": {ASK_Q1: "a", ASK_Q2: None}, "gold_facts_used": []})

    def test_o9_first_json_object_is_used_with_text_around_it(self):
        text = "Sure, here it is:\n```json\n" + raw_idle("first") + "\n```\nand also " + raw_idle("second")
        self.assertEqual(self.parse(text, idle_request())["message"], "first")

    def test_o9_braces_inside_strings_do_not_end_the_object(self):
        text = raw_idle("use {braces} and } here")
        self.assertEqual(self.parse("x " + text, idle_request())["message"], "use {braces} and } here")

    def test_o9_non_json_braces_before_the_object_are_skipped(self):
        self.assertEqual(self.parse("Note {see below}: " + raw_idle("ok"), idle_request())["message"], "ok")

    def test_o9_text_without_a_json_object_is_rejected(self):
        for text in ("", "no object here", "[1, 2]", "{ broken", "null", '"just a string"'):
            with self.subTest(text):
                self.bad(text, idle_request())
                self.bad(text)

    def test_o9_answers_must_be_an_object(self):
        for value in ([], "text", 5, None):
            with self.subTest(value):
                self.bad(json.dumps({"answers": value}))
        self.bad(json.dumps({"gold_facts_used": []}))

    def test_o9_answer_values_must_be_strings_or_null(self):
        for value in (5, ["a"], {"k": "v"}, True):
            with self.subTest(value):
                self.bad(json.dumps({"answers": {ASK_Q1: value}}))

    def test_o9_unknown_question_key_is_rejected(self):
        self.bad(json.dumps({"answers": {"Not asked?": "x"}}))
        self.bad(json.dumps({"answers": {ASK_Q1: "x", "Not asked?": "y"}}))

    def test_o9_idle_message_must_be_a_string_or_null(self):
        for value in (5, ["m"], {"a": 1}, False):
            with self.subTest(value):
                self.bad(json.dumps({"message": value}), idle_request())

    def test_o9_response_of_the_wrong_kind_is_rejected(self):
        self.bad(json.dumps({"message": "m"}))
        self.bad(json.dumps({"answers": {}}), idle_request())

    def test_o9_gold_facts_used_must_be_a_list_of_strings(self):
        for value in ("fact", {"a": "b"}, 3, None, ["ok", 4], [["nested"]]):
            with self.subTest(value):
                self.bad(json.dumps({"answers": {}, "gold_facts_used": value}))
                self.bad(json.dumps({"message": "m", "gold_facts_used": value}), idle_request())


# ---------------------------------------------------------------------------------------------
# O10
# ---------------------------------------------------------------------------------------------

ROW_KEYS = {"n", "kind", "request", "raw_output", "parsed", "leaks", "sent", "gold_facts_used", "error", "elapsed_s"}


class RespondTests(unittest.TestCase):
    def go(self, request, response):
        call = R.FakeCall(response)
        out = informed.respond(INST, request, call_fn=call)
        return out, call

    def test_o10_clean_ask(self):
        raw = raw_ask("That is wrong; an empty string is expected.", None, ["fact-A"])
        (resp, row), call = self.go(ask_request(3), raw)
        self.assertEqual(resp, {"n": 3, "answers": {ASK_Q1: "That is wrong; an empty string is expected.", ASK_Q2: None}})
        self.assertEqual(call.prompts, [informed.build_prompt(INST, ask_request(3))])
        self.assertEqual(set(row), ROW_KEYS)
        self.assertEqual((row["n"], row["kind"]), (3, "ask"))
        self.assertEqual(row["request"], ask_request(3))
        self.assertEqual(row["raw_output"], raw)
        self.assertEqual(row["parsed"], informed.parse_response(raw, ask_request(3)))
        self.assertTrue(all(v == [] for v in row["leaks"].values()))
        self.assertEqual(row["gold_facts_used"], ["fact-A"])
        self.assertIsNone(row["error"])
        self.assertGreaterEqual(row["elapsed_s"], 0)
        self.assertIn("empty string is expected", json.dumps(row["sent"]))

    def test_o10_one_answer_with_a_leak_becomes_null_and_the_other_is_kept(self):
        raw = raw_ask("Clean answer: expect blank.", "just return zzz", ["f"])
        (resp, row), _ = self.go(ask_request(), raw)
        self.assertEqual(resp, {"n": 1, "answers": {ASK_Q1: "Clean answer: expect blank.", ASK_Q2: None}})
        self.assertEqual(row["leaks"][ASK_Q2], ["zzz"])
        self.assertEqual(row["leaks"].get(ASK_Q1, []), [])
        self.assertNotIn("zzz", json.dumps(row["sent"]))
        self.assertIsNone(row["error"])

    def test_o10_leaking_message_becomes_null(self):
        (resp, row), _ = self.go(idle_request(5), raw_idle("Rename it to test_x", ["f"]))
        self.assertEqual(resp, {"n": 5, "message": None})
        self.assertEqual(row["leaks"], {"message": ["test_x"]})
        self.assertEqual((row["n"], row["kind"]), (5, "idle"))

    def test_o10_clean_message_is_sent(self):
        (resp, row), _ = self.go(idle_request(5), raw_idle("That direction is wrong."))
        self.assertEqual(resp, {"n": 5, "message": "That direction is wrong."})
        self.assertEqual(row["leaks"], {})

    def test_o10_exempt_term_is_not_nulled(self):
        (resp, _), _ = self.go(idle_request(5), raw_idle("compute_layout is where it fails"))
        self.assertEqual(resp["message"], "compute_layout is where it fails")

    def test_o10_call_exception_or_timeout_gives_all_null_with_the_first_line(self):
        for exc in (RuntimeError("boom first\nsecond line"), TimeoutError("timed out")):
            for request, null in ((ask_request(), {"n": 1, "answers": {ASK_Q1: None, ASK_Q2: None}}),
                                  (idle_request(), {"n": 2, "message": None})):
                with self.subTest(exc=repr(exc), kind=request["kind"]):
                    (resp, row), _ = self.go(request, exc)
                    self.assertEqual(resp, null)
                    first = str(exc).splitlines()[0]
                    self.assertIn(first, row["error"])
                    self.assertNotIn("\n", row["error"])
                    self.assertNotIn("second line", row["error"])
                    self.assertEqual(set(row), ROW_KEYS)

    def test_o10_format_error_gives_all_null_and_the_format_message(self):
        raw = "I cannot comply"
        with self.assertRaises(informed.ResponseFormatError) as ctx:
            informed.parse_response(raw, ask_request())
        (resp, row), _ = self.go(ask_request(), raw)
        self.assertEqual(resp, {"n": 1, "answers": {ASK_Q1: None, ASK_Q2: None}})
        self.assertEqual(row["error"], str(ctx.exception))
        self.assertEqual(row["raw_output"], raw)


# ---------------------------------------------------------------------------------------------
# O11
# ---------------------------------------------------------------------------------------------

TOKEN = "tok-relay-0123456789abcdef"


def wait_until(cond, timeout=5.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.01)
    return False


def gold_strings():
    needles = [GOLD_LINE_PATCH, GOLD_LINE_TEST, 'assert render_hint() == "zzz"', "def compute_layout(widget, mode):",
               GOLD_FACT, *INST["FAIL_TO_PASS"]]
    for text in (INST["patch"], INST["test_patch"]):
        for line in text.splitlines():
            if line.startswith("+") and not line.startswith("+++") and len(line.strip("+ ")) >= 8:
                needles.append(line[1:].strip())
    return needles


class RelayTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="relay-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.container = F.RelayFakeContainer(Path(self.tmp) / "relay")
        self.record = Path(self.tmp) / "entry" / "informed.jsonl"
        self.record.parent.mkdir()
        self.calls = []

    def call_fn(self, prompt):
        self.calls.append(prompt)
        if ASK_Q1 in prompt:
            return raw_ask("Do this: " + GOLD_LINE_PATCH + " per test_w.py", None, [GOLD_FACT, INST["FAIL_TO_PASS"][0]])
        return raw_idle("That direction is wrong; expect an empty string.", [GOLD_FACT])

    def relay(self, call_fn=None):
        relay = informed.Relay(self.container, INST, self.record, call_fn=call_fn or self.call_fn, poll_s=0.01,
                               token=TOKEN)
        self.relay_obj = relay
        return relay

    def rows(self):
        if not self.record.exists():
            return []
        return [json.loads(l) for l in self.record.read_text(encoding="utf-8").splitlines() if l.strip()]

    def test_o11_two_requests_are_answered_once_each_in_order(self):
        self.container.put_request(1, ask_request(1))
        self.container.put_request(2, idle_request(2))
        before = threading.active_count()
        relay = self.relay()
        relay.start()
        try:
            self.assertTrue(wait_until(lambda: len(self.rows()) == 2), self.rows())
            time.sleep(0.15)
        finally:
            relay.stop()
        self.assertEqual(threading.active_count(), before)
        self.assertEqual(len(self.calls), 2)
        self.assertIn(ASK_Q1, self.calls[0])
        self.assertIn("I plan to special-case blanks.", self.calls[1])
        self.assertEqual([r["n"] for r in self.rows()], [1, 2])
        files = self.container.response_files()
        self.assertEqual(sorted(files), ["resp-1.json", "resp-2.json"])
        self.assertEqual(json.loads(files["resp-1.json"]), {"n": 1, "answers": {ASK_Q1: None, ASK_Q2: None}})
        self.assertEqual(json.loads(files["resp-2.json"]),
                         {"n": 2, "message": "That direction is wrong; expect an empty string."})

    def test_o11_responses_are_written_to_a_tmp_name_then_renamed(self):
        self.container.put_request(1, ask_request(1))
        relay = self.relay()
        relay.start()
        try:
            self.assertTrue(wait_until(lambda: "resp-1.json" in self.container.response_files()))
        finally:
            relay.stop()
        direct = [op for op in self.container.ops if op[0] == "write" and op[1].endswith("/resp-1.json")]
        self.assertEqual(direct, [])
        tmp_seen = any((op[0] == "write" and op[1].endswith("resp-1.json.tmp")) or
                       (op[0] == "exec" and any("resp-1.json.tmp" in a for a in op[1])) for op in self.container.ops)
        self.assertTrue(tmp_seen)
        self.assertTrue(any(op[0] == "exec" and "resp-1.json.tmp" in " ".join(op[1]) and
                            " ".join(op[1]).replace("resp-1.json.tmp", "").count("resp-1.json")
                            for op in self.container.ops), "no rename of the tmp file observed")
        self.assertNotIn("resp-1.json.tmp", self.container.response_files())

    def test_o11_no_container_write_contains_gold_text(self):
        self.container.put_request(1, ask_request(1))
        self.container.put_request(2, idle_request(2))
        relay = self.relay()
        relay.start()
        try:
            self.assertTrue(wait_until(lambda: len(self.rows()) == 2))
        finally:
            relay.stop()
        written = self.container.everything_written()
        self.assertIn("expect an empty string", written)
        for needle in gold_strings():
            self.assertNotIn(needle, written, needle)
        self.assertNotIn(GOLD_LINE_PATCH, json.dumps(self.container.response_files()))
        row = self.rows()[0]
        self.assertEqual(row["gold_facts_used"], [GOLD_FACT, INST["FAIL_TO_PASS"][0]])
        self.assertTrue(row["leaks"])

    def test_o11_token_in_a_record_row_is_redacted_and_the_line_still_written(self):
        def call_fn(prompt):
            return raw_idle("fine message", ["secret " + TOKEN])

        self.container.put_request(1, idle_request(1))
        relay = self.relay(call_fn)
        relay.start()
        try:
            self.assertTrue(wait_until(lambda: self.record.exists() and self.record.read_text().strip()))
        finally:
            relay.stop()
        text = self.record.read_text(encoding="utf-8")
        self.assertNotIn(TOKEN, text)
        self.assertIn("[REDACTED]", text)
        self.assertEqual(len(text.splitlines()), 1)
        row = json.loads(text.splitlines()[0])
        self.assertEqual(row["raw_output"], raw_idle("fine message", ["secret [REDACTED]"]))
        self.assertEqual(row["gold_facts_used"], ["secret [REDACTED]"])

    def test_o11_handler_exception_isolates_one_request(self):
        real = informed.respond

        attempts = []

        def flaky(instance, request, *, call_fn):
            attempts.append(request["n"])
            if request["n"] == 1:
                raise RuntimeError("boom in handler")
            return real(instance, request, call_fn=call_fn)

        self.container.put_request(1, idle_request(1))
        self.container.put_request(2, idle_request(2))
        with mock.patch.object(informed, "respond", flaky):
            relay = self.relay()
            relay.start()
            try:
                self.assertTrue(wait_until(lambda: "resp-2.json" in self.container.response_files()))
                self.assertTrue(wait_until(lambda: len(self.rows()) == 2))
            finally:
                relay.stop()
        files = self.container.response_files()
        self.assertNotIn("resp-1.json", files)
        failed = [r for r in self.rows() if r.get("n") == 1]
        self.assertEqual(len(failed), 1)
        self.assertIn("boom in handler", failed[0]["error"])
        self.assertEqual(set(failed[0]), ROW_KEYS)
        self.assertEqual(failed[0]["kind"], "idle")
        self.assertEqual(failed[0]["request"], idle_request(1))
        time.sleep(0.2)
        self.assertEqual(attempts.count(1), 1, "the reviewer path was retried for a failed request")

    def test_o11_stop_joins_the_thread_and_answers_nothing_afterwards(self):
        before = threading.active_count()
        relay = self.relay()
        relay.start()
        self.assertGreater(threading.active_count(), before)
        relay.stop()
        self.assertEqual(threading.active_count(), before)
        self.container.put_request(3, idle_request(3))
        time.sleep(0.2)
        self.assertEqual(self.container.response_files(), {})
        self.assertEqual(self.calls, [])

    def test_o11_r9_requests_that_already_have_a_response_are_skipped(self):
        self.container.put_request(1, ask_request(1))
        (self.container.root / "resp-1.json").write_text(json.dumps({"n": 1, "answers": {}}), encoding="utf-8")
        self.container.put_request(2, idle_request(2))
        relay = self.relay()
        relay.start()
        try:
            self.assertTrue(wait_until(lambda: "resp-2.json" in self.container.response_files()))
            time.sleep(0.15)
        finally:
            relay.stop()
        self.assertEqual(len(self.calls), 1)
        self.assertIn("I plan to special-case blanks.", self.calls[0])
        self.assertEqual(json.loads(self.container.response_files()["resp-1.json"]), {"n": 1, "answers": {}})
        self.assertEqual([r["n"] for r in self.rows()], [2])

    def test_o11_g1_g5_response_write_failure_gives_a_complete_error_row_and_no_retry(self):
        self.container = F.RelayFakeContainer(Path(self.tmp) / "relay-wf", fail_write=lambda d: "resp-1.json" in d)
        self.container.put_request(1, idle_request(1, brief="BRIEF-ONE"))
        self.container.put_request(2, idle_request(2, brief="BRIEF-TWO"))
        relay = self.relay()
        relay.start()
        try:
            self.assertTrue(wait_until(lambda: "resp-2.json" in self.container.response_files()))
            self.assertTrue(wait_until(lambda: len(self.rows()) >= 2))
            time.sleep(0.3)
        finally:
            relay.stop()
        files = self.container.response_files()
        self.assertNotIn("resp-1.json", files)
        failed = [r for r in self.rows() if r.get("n") == 1]
        self.assertEqual(len(failed), 1)
        self.assertEqual(set(failed[0]), ROW_KEYS)
        self.assertEqual(failed[0]["kind"], "idle")
        self.assertEqual(failed[0]["request"], idle_request(1, brief="BRIEF-ONE"))
        self.assertTrue(failed[0]["error"])
        self.assertIn("write refused", failed[0]["error"])
        self.assertEqual(len([p for p in self.calls if "BRIEF-ONE" in p]), 1)
        self.assertEqual(len([p for p in self.calls if "BRIEF-TWO" in p]), 1)

    def test_o11_g8_exec_as_an_unknown_user_gets_no_listing(self):
        self.container.put_request(1, idle_request(1))
        code, out, _ = self.container.exec(["ls", F.RELAY_DIR], user="ghost")
        self.assertNotEqual(code, 0)
        self.assertNotIn("req-1.json", out)
        for user in (None, "root", "nonroot"):
            code, out, _ = self.container.exec(["ls", F.RELAY_DIR], user=user)
            self.assertEqual(code, 0)
            self.assertIn("req-1.json", out)
        docker = F.FakeDocker()
        box = docker.start_container("img", name="selfcheck-agent-x-1", network="n", labels={}, cpus=1, memory="1g", mounts=[])
        self.assertNotEqual(box.exec(["ls", "/"], user="ghost")[0], 0)
        self.assertEqual(box.exec(["ls", "/"], user="nonroot")[0], 0)

    def test_o11_request_arriving_while_running_is_answered(self):
        relay = self.relay()
        relay.start()
        try:
            time.sleep(0.05)
            self.container.put_request(1, idle_request(1))
            self.assertTrue(wait_until(lambda: "resp-1.json" in self.container.response_files()))
        finally:
            relay.stop()


if __name__ == "__main__":
    unittest.main()

"""VO1-VO7 for selfcheck.review (spec e4d852bdd61ccf5b v2): extract_briefs, load_spec, parse_review,
build_prompt, review_entry (decision table D1-D6), no-mutation of run files, token confinement."""
import copy
import json
import re
import shutil
import tempfile
import threading
import unittest
from pathlib import Path

from selfcheck import review
from selfcheck.tests import m3_fakes as m
from selfcheck.tests import review_fakes as R


class TmpCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="rev-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)


def rel(name):
    return R.TRANSCRIPT_DIR + "/" + name


class ConstantsTests(unittest.TestCase):
    def test_vo3_constants_match_the_signatures(self):
        self.assertEqual(tuple(review.CATEGORIES), R.CATEGORIES)
        self.assertEqual(tuple(review.VERDICTS), R.VERDICTS)
        self.assertTrue(issubclass(review.ReviewFormatError, Exception))


# ----------------------------------------------------------------------------------------------
# VO1 extract_briefs (equivalence partitioning E1-E8)
# ----------------------------------------------------------------------------------------------

class ExtractBriefsTests(TmpCase):
    def entry(self, transcripts):
        return R.make_entry(self.tmp, transcripts=transcripts)

    def test_vo1_c1_two_text_one_ask_sidechain_and_subagents_excluded(self):
        qs = R.questions("one")
        rows = [
            R.assistant(R.text_block("first main text")),
            R.assistant(R.text_block("SIDECHAIN text"), sidechain=True),
            R.assistant(R.text_block("second main text"), R.ask_block(qs)),
        ]
        entry = self.entry({R.UUID_A + ".jsonl": rows})
        sub = entry / R.TRANSCRIPT_DIR / "subagents"
        m.write_text(sub / "agent-1.jsonl", m.jsonl_text([R.assistant(R.text_block("SUBAGENT text"))]))
        m.write_text(entry / R.TRANSCRIPT_DIR / R.UUID_A / "subagents" / "agent-2.jsonl",
                     m.jsonl_text([R.assistant(R.text_block("NESTED SUBAGENT text"))]))
        items = review.extract_briefs(entry)
        self.assertEqual([(i["kind"], i["line"]) for i in items], [("text", 1), ("text", 3), ("ask", 3)])
        self.assertEqual([i["file"] for i in items], [rel(R.UUID_A + ".jsonl")] * 3)
        self.assertEqual(items[0]["text"], "first main text")
        self.assertEqual(items[1]["text"], "second main text")
        self.assertEqual(json.loads(items[2]["text"]), qs)
        for item in items:
            self.assertEqual(set(item), {"file", "line", "kind", "text"})
            self.assertNotIn("SIDECHAIN", item["text"])
            self.assertNotIn("SUBAGENT", item["text"])

    def test_vo1_e1_e2_e3_e4_each_partition_individually(self):
        cases = (
            ("E1 main text", [R.assistant(R.text_block("t"))], [("text", 1, "t")]),
            ("E3 sidechain only", [R.assistant(R.text_block("t"), sidechain=True)], []),
        )
        for label, rows, expected in cases:
            with self.subTest(label):
                shutil.rmtree(self.tmp / "inst-1", True)
                entry = self.entry({R.UUID_A + ".jsonl": rows})
                got = [(i["kind"], i["line"], i["text"]) for i in review.extract_briefs(entry)]
                self.assertEqual(got, expected)
        shutil.rmtree(self.tmp / "inst-1", True)
        qs = R.questions("only")
        entry = self.entry({R.UUID_A + ".jsonl": [R.assistant(R.ask_block(qs))]})
        items = review.extract_briefs(entry)
        self.assertEqual([(i["kind"], i["line"]) for i in items], [("ask", 1)])
        self.assertEqual(json.loads(items[0]["text"]), qs)
        shutil.rmtree(self.tmp / "inst-1", True)
        entry = self.entry({})
        m.write_text(entry / R.TRANSCRIPT_DIR / "subagents" / "a.jsonl", m.jsonl_text([R.assistant(R.text_block("x"))]))
        self.assertEqual(review.extract_briefs(entry), [])

    def test_vo1_c2_e5_e6_e7_skipped_rows_still_count_for_line_numbers(self):
        rows = [
            R.BAD_JSON_LINE,
            R.user("user words"),
            R.assistant(R.thinking_block("private thoughts")),
            R.assistant(R.tool_block("Bash", command="ls")),
            R.assistant(R.thinking_block("t"), R.text_block("kept"), R.tool_block("Read", file_path="/x")),
            {"type": "user", "isSidechain": False, "message": {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": "toolu_x", "content": "tool output"}]}},
        ]
        items = review.extract_briefs(self.entry({R.UUID_A + ".jsonl": rows}))
        self.assertEqual([(i["kind"], i["line"], i["text"]) for i in items], [("text", 5, "kept")])

    def test_vo1_c2_skipped_rows_before_main_messages_do_not_end_the_scan(self):
        rows = [
            R.user("early user row"),
            R.assistant(R.text_block("early sidechain"), sidechain=True),
            R.BAD_JSON_LINE,
            R.assistant(R.text_block("later one")),
            R.user("another user row"),
            R.assistant(R.text_block("side again"), sidechain=True),
            R.assistant(R.text_block("later two"), R.ask_block(R.questions("late"))),
            R.assistant(R.tool_block("Bash", command="ls")),
            R.assistant(R.text_block("later three")),
        ]
        items = review.extract_briefs(self.entry({R.UUID_A + ".jsonl": rows}))
        self.assertEqual([(i["kind"], i["line"]) for i in items],
                         [("text", 4), ("text", 7), ("ask", 7), ("text", 9)])
        self.assertEqual([i["text"] for i in items if i["kind"] == "text"], ["later one", "later two", "later three"])

    def test_vo1_c2_odd_shaped_main_rows_before_later_messages_do_not_end_the_scan(self):
        rows = [
            {"type": "assistant", "isSidechain": False, "message": {"role": "assistant", "content": "plain string"}},
            {"type": "assistant", "isSidechain": False, "message": "not a dict"},
            {"type": "assistant", "isSidechain": False, "message": None},
            {"type": "assistant", "isSidechain": False, "message": {"role": "assistant", "content": None}},
            R.assistant(R.text_block("after odd rows")),
            R.assistant(R.ask_block(R.questions("odd"))),
        ]
        items = review.extract_briefs(self.entry({R.UUID_A + ".jsonl": rows}))
        later = [(i["kind"], i["line"]) for i in items if i["line"] >= 5]
        self.assertEqual(later, [("text", 5), ("ask", 6)])
        self.assertEqual([i["text"] for i in items if i["line"] == 5], ["after odd rows"])

    def test_vo1_e1_multiple_text_blocks_of_one_message_make_one_item_in_order(self):
        # joiner between blocks is unspecified (spec challenge): only containment and order are asserted
        rows = [R.assistant(R.text_block("alpha-block"), R.text_block("omega-block"))]
        items = review.extract_briefs(self.entry({R.UUID_A + ".jsonl": rows}))
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["kind"], "text")
        self.assertLess(items[0]["text"].index("alpha-block"), items[0]["text"].index("omega-block"))

    def test_vo1_e2_two_ask_tool_uses_in_one_message_give_two_ask_items(self):
        q1, q2 = R.questions("one"), R.questions("two")
        rows = [R.assistant(R.ask_block(q1), R.ask_block(q2))]
        items = review.extract_briefs(self.entry({R.UUID_A + ".jsonl": rows}))
        self.assertEqual([i["kind"] for i in items], ["ask", "ask"])
        self.assertEqual([json.loads(i["text"]) for i in items], [q1, q2])

    def test_vo1_e8_files_in_name_order_with_per_file_line_numbers(self):
        a = [R.assistant(R.text_block("a1")), R.user("u"), R.assistant(R.text_block("a3"))]
        b = [R.assistant(R.text_block("b1"))]
        entry = self.entry({R.UUID_B + ".jsonl": b, R.UUID_A + ".jsonl": a})
        m.write_text(entry / R.TRANSCRIPT_DIR / "notes.txt", "not a transcript")
        got = [(i["file"], i["line"], i["text"]) for i in review.extract_briefs(entry)]
        self.assertEqual(got, [
            (rel(R.UUID_A + ".jsonl"), 1, "a1"), (rel(R.UUID_A + ".jsonl"), 3, "a3"),
            (rel(R.UUID_B + ".jsonl"), 1, "b1"),
        ])


# ----------------------------------------------------------------------------------------------
# VO2 load_spec
# ----------------------------------------------------------------------------------------------

class LoadSpecTests(TmpCase):
    def test_vo2_spec_logs_present(self):
        entry = R.make_entry(self.tmp, diff=m.archived_diff())
        self.assertEqual(review.load_spec(entry), {"source": "spec-logs", "text": "\n".join(m.spec_lines())})

    def test_vo2_specs_present(self):
        entry = R.make_entry(self.tmp, diff=m.archived_diff(status="active", where=m.SPECS))
        self.assertEqual(review.load_spec(entry),
                         {"source": "specs", "text": "\n".join(m.spec_lines(status="active"))})

    def test_vo2_spec_logs_win_over_specs_when_both_exist(self):
        diff = m.archived_diff(status="active", where=m.SPECS) + m.new_file_section(
            m.ARCHIVE_REL, m.spec_lines(status="complete"))
        entry = R.make_entry(self.tmp, diff=diff)
        got = review.load_spec(entry)
        self.assertEqual(got["source"], "spec-logs")
        self.assertIn("status: complete", got["text"])

    def test_vo2_none_when_the_diff_has_no_spec_for_the_run(self):
        entry = R.make_entry(self.tmp, diff=m.decoy_section())
        self.assertIsNone(review.load_spec(entry))

    def test_vo2_none_without_a_diff_file(self):
        self.assertIsNone(review.load_spec(R.make_entry(self.tmp, diff=None)))

    def test_vo2_none_without_workflow_start(self):
        events = [e for e in m.compliant_events() if e["event"] != "workflow_start"]
        entry = R.make_entry(self.tmp, events=events, diff=m.archived_diff())
        self.assertIsNone(review.load_spec(entry))

    def test_vo2_none_without_telemetry(self):
        self.assertIsNone(review.load_spec(R.make_entry(self.tmp, events=None, diff=m.archived_diff())))

    def test_vo2_uses_the_run_id_of_the_first_workflow_start(self):
        events = [m.ev(1, "workflow_start", run="otherrun00000a"), m.ev(2, "workflow_start", run=m.WF)]
        entry = R.make_entry(self.tmp, events=events, diff=m.archived_diff())
        self.assertIsNone(review.load_spec(entry))
        events = [m.ev(1, "workflow_start", run=m.WF), m.ev(2, "workflow_start", run="otherrun00000a")]
        shutil.rmtree(self.tmp / "inst-1")
        entry = R.make_entry(self.tmp, events=events, diff=m.archived_diff())
        self.assertEqual(review.load_spec(entry)["source"], "spec-logs")


# ----------------------------------------------------------------------------------------------
# VO3 parse_review (syntax testing)
# ----------------------------------------------------------------------------------------------

def valid_cases():
    plain = R.payload(
        understanding=R.category("diverged", R.finding("s1", "[f.jsonl:1]", True), R.finding("s2", "[spec]", False)),
        ask_options=R.category("consistent"),
        recommendation_evidence=R.category("n/a"),
    )
    brace = R.payload(spec_requirements=R.category("diverged", R.finding("has } and {braces} inside", "[spec]")))
    return plain, brace


class ParseReviewTests(unittest.TestCase):
    def test_vo3_valid_plain_fenced_and_with_prose(self):
        plain, brace = valid_cases()
        body = R.model_text(plain)
        cases = (
            ("plain", body, plain),
            ("fenced json", "```json\n%s\n```" % body, plain),
            ("prose around", "Here is my review:\n%s\nHope that helps." % body, plain),
            ("fenced with prose", "Result:\n```json\n%s\n```\nDone." % body, plain),
            ("braces inside a string", R.model_text(brace), brace),
            ("all consistent and empty", R.model_text(R.payload()), R.payload()),
            ("first of two objects", body + "\n" + R.model_text(R.payload()), plain),
        )
        for label, text, cats in cases:
            with self.subTest(label):
                self.assertEqual(review.parse_review(text), R.expected_parse(cats))

    def parse_with_timeout(self, text, seconds=5):
        box = {}

        def work():
            try:
                box["value"] = review.parse_review(text)
            except BaseException as exc:  # reported by the assertion below
                box["error"] = exc

        thread = threading.Thread(target=work, daemon=True)
        thread.start()
        thread.join(seconds)
        self.assertFalse(thread.is_alive(), "parse_review did not terminate within %ss" % seconds)
        if "error" in box:
            raise box["error"]
        return box["value"]

    def test_vo3_stray_braces_before_the_real_object(self):
        cats = valid_cases()[0]
        body = R.model_text(cats)
        cases = (
            ("non-json braces before", "Note {not json} then " + body),
            ("stray open brace before", "{" + body),
            ("doubled braces", "{" + body + "}"),
            ("lone brace then prose", "see { here\n" + body),
            ("unbalanced close then object", "} oops " + body),
        )
        for label, text in cases:
            with self.subTest(label):
                self.assertEqual(self.parse_with_timeout(text), R.expected_parse(cats))

    def test_vo3_only_stray_braces_raise_and_terminate(self):
        for text in ("{", "{{", "{ not json }", "}{"):
            with self.subTest(text):
                with self.assertRaises(review.ReviewFormatError):
                    self.parse_with_timeout(text)

    def test_vo3_invalid_inputs_raise_review_format_error(self):
        def mutated(fn):
            cats = copy.deepcopy(R.payload(understanding=R.category("diverged", R.finding())))
            fn(cats)
            return R.model_text(cats)

        def first_finding(cats):
            return cats["understanding"]["findings"][0]

        cases = {
            "no json": "no json at all",
            "empty text": "",
            "json array only": "[1, 2]",
            "truncated json": '{"categories": {"understanding": ',
            "bad verdict": mutated(lambda c: c["ask_options"].update(verdict="maybe")),
            "verdict wrong case": mutated(lambda c: c["ask_options"].update(verdict="Consistent")),
            "verdict missing": mutated(lambda c: c["ask_options"].pop("verdict")),
            "diverged empty": mutated(lambda c: c["understanding"].update(findings=[])),
            "findings missing": mutated(lambda c: c["ask_options"].pop("findings")),
            "findings dict": mutated(lambda c: c["ask_options"].update(findings={"summary": "x"})),
            "findings none": mutated(lambda c: c["ask_options"].update(findings=None)),
            "findings string": mutated(lambda c: c["ask_options"].update(findings="none")),
            "false_claim string": mutated(lambda c: first_finding(c).update(false_claim="true")),
            "false_claim int": mutated(lambda c: first_finding(c).update(false_claim=1)),
            "false_claim null": mutated(lambda c: first_finding(c).update(false_claim=None)),
            "citation missing": mutated(lambda c: first_finding(c).pop("citation")),
            "citation not string": mutated(lambda c: first_finding(c).update(citation=7)),
            "summary missing": mutated(lambda c: first_finding(c).pop("summary")),
            "summary not string": mutated(lambda c: first_finding(c).update(summary=["x"])),
            "bare form without categories key": json.dumps(R.payload(
                understanding=R.category("diverged", R.finding()))),
            "extra category": mutated(lambda c: c.update(extra=R.category())),
            "category not object": mutated(lambda c: c.update(ask_options="consistent")),
        }
        for name in R.CATEGORIES:
            cases["missing category " + name] = mutated(lambda c, n=name: c.pop(n))
        for label, text in cases.items():
            with self.subTest(label):
                with self.assertRaises(review.ReviewFormatError):
                    review.parse_review(text)


# ----------------------------------------------------------------------------------------------
# VO4 build_prompt
# ----------------------------------------------------------------------------------------------

BRIEFS = [
    {"file": rel(R.UUID_A + ".jsonl"), "line": 1, "kind": "text", "text": "BRIEF-TEXT-ONE the issue is X"},
    {"file": rel(R.UUID_A + ".jsonl"), "line": 3, "kind": "ask", "text": '[{"question": "ASK-MARK which?"}]'},
    {"file": rel(R.UUID_B + ".jsonl"), "line": 12, "kind": "text", "text": "BRIEF-TEXT-THREE done"},
]
SPEC = {"source": "spec-logs", "text": "SPEC-BODY-MARK first line\nsecond line"}


class BuildPromptTests(unittest.TestCase):
    def prompt(self, spec=SPEC, briefs=BRIEFS):
        return review.build_prompt(copy.deepcopy(R.INSTANCE), copy.deepcopy(briefs), copy.deepcopy(spec))

    def test_vo4_c12_with_spec_contains_every_required_part(self):
        text = self.prompt()
        for needle in (R.INSTANCE["problem_statement"], R.INSTANCE["patch"], R.INSTANCE["test_patch"],
                       *R.INSTANCE["FAIL_TO_PASS"], *R.CATEGORIES, *R.VERDICTS, "false_claim"):
            self.assertIn(needle, text)
        for brief in BRIEFS:
            self.assertRegex(text, r"\[%s:%d\] \(%s\) %s" % (re.escape(brief["file"]), brief["line"],
                                                           brief["kind"], re.escape(brief["text"].splitlines()[0])))
        self.assertRegex(text, r"\[spec\]\s*SPEC-BODY-MARK first line")
        self.assertIn("second line", text)
        self.assertIn("json", text.lower())
        self.assertIn("opinion", text.lower())  # wording of the false_claim rule is a spec challenge
        positions = [text.index(b["text"].splitlines()[0]) for b in BRIEFS]
        self.assertEqual(positions, sorted(positions))

    def test_vo4_without_spec_has_no_spec_body_and_differs(self):
        with_spec = self.prompt()
        without = self.prompt(spec=None)
        self.assertNotIn("SPEC-BODY-MARK", without)
        self.assertNotEqual(with_spec, without)
        self.assertNotRegex(without, r"\[spec\]\s*SPEC-BODY-MARK")
        for needle in (R.INSTANCE["patch"], *R.CATEGORIES, "BRIEF-TEXT-ONE", "ASK-MARK"):
            self.assertIn(needle, without)

    def test_vo4_task_text_states_citation_rule_no_spec_and_false_claim_exclusions(self):
        for label, spec in (("with spec", SPEC), ("without spec", None)):
            with self.subTest(label):
                low = self.prompt(spec=spec).lower()
                self.assertIn("cite", low)
                self.assertIn("[file:line]", low)
                self.assertIn("[spec]", low)
                self.assertIn("opinion", low)
                self.assertIn("recommendation", low.replace("recommendation_evidence", ""))
        self.assertIn("no spec", self.prompt(spec=None).lower())
        self.assertNotIn("no spec", self.prompt().lower())

    def test_vo4_ask_brief_text_is_included_with_its_location_prefix(self):
        text = self.prompt(briefs=[BRIEFS[1]])
        self.assertRegex(text, r"\[%s:3\] \(ask\) \[\{" % re.escape(BRIEFS[1]["file"]))
        self.assertNotIn("BRIEF-TEXT-ONE", text)

    def test_vo4_every_instance_field_changes_the_prompt(self):
        base = self.prompt()
        for key, value in (("problem_statement", "OTHER-PS"), ("patch", "OTHER-PATCH"),
                           ("test_patch", "OTHER-TP"), ("FAIL_TO_PASS", ["other::id"])):
            inst = copy.deepcopy(R.INSTANCE)
            inst[key] = value
            with self.subTest(key):
                got = review.build_prompt(inst, copy.deepcopy(BRIEFS), copy.deepcopy(SPEC))
                self.assertNotEqual(got, base)
                self.assertIn(value if isinstance(value, str) else value[0], got)


# ----------------------------------------------------------------------------------------------
# VO5 review_entry decision table
# ----------------------------------------------------------------------------------------------

def review_json(entry):
    return json.loads((entry / "review.json").read_text(encoding="utf-8"))


class ReviewEntryTests(TmpCase):
    def test_vo5_d1_ok_with_one_false_claim(self):
        s = R.scenario("D1", self.tmp)
        written = review_json(s.entry)
        self.assertEqual(written, s.result)
        self.assertEqual(written["status"], "ok")
        self.assertEqual((written["instance_id"], written["model"], written["effort"]), ("inst-1", R.MODEL, R.EFFORT))
        self.assertEqual(written["categories"], R.D1_CATS)
        self.assertEqual(len(written["false_claims"]), 1)
        claim = written["false_claims"][0]
        for key, value in R.D1_FALSE_CLAIMS[0].items():
            self.assertEqual(claim[key], value)
        self.assertEqual(s.call.count, 1)
        self.assertIn(R.INSTANCE["problem_statement"], s.call.prompts[0])
        self.assertIn("The issue is about Literal annotations.", s.call.prompts[0])
        self.assert_prompt_has_spec_and_ask(s.call.prompts[0])

    def test_vo5_d1_model_and_effort_kwargs_are_recorded(self):
        entry = R.make_entry(self.tmp)
        result = review.review_entry(entry, dict(R.INSTANCE), call_fn=R.FakeCall(R.model_text(R.payload())),
                                     token=R.TOKEN, model="some-model", effort="high")
        self.assertEqual((result["model"], result["effort"]), ("some-model", "high"))
        self.assertEqual(review_json(entry)["model"], "some-model")

    def test_vo5_d1_two_false_claims_in_different_categories_and_fenced_output(self):
        cats = R.payload(
            ask_options=R.category("diverged", R.finding("opt wrong", "[a:1]", True)),
            spec_requirements=R.category("diverged", R.finding("req wrong", "[spec]", True), R.finding("fine", "[spec]")),
        )
        entry = R.make_entry(self.tmp)
        result = review.review_entry(entry, dict(R.INSTANCE), call_fn=R.FakeCall("```json\n%s\n```" % R.model_text(cats)),
                                     token=R.TOKEN, model=R.MODEL, effort=R.EFFORT)
        got = sorted((c["category"], c["summary"], c["citation"]) for c in result["false_claims"])
        self.assertEqual(got, [("ask_options", "opt wrong", "[a:1]"), ("spec_requirements", "req wrong", "[spec]")])

    def test_vo5_d2_ok_without_false_claims(self):
        s = R.scenario("D2", self.tmp)
        written = review_json(s.entry)
        self.assertEqual(written["status"], "ok")
        self.assertEqual(written["false_claims"], [])
        self.assertEqual(written["categories"], R.payload())
        self.assertEqual(s.call.count, 1)

    def test_vo5_d3_call_fn_raises_status_error_with_first_line_only(self):
        s = R.scenario("D3", self.tmp)
        self.assert_error(s, "claude exited 1")
        self.assertNotIn("second line", s.result["error"])
        self.assertEqual(s.call.count, 1)

    def test_vo5_d3_any_exception_type_is_captured(self):
        for exc in (ValueError("bad value"), OSError("disk"), TimeoutError("slow")):
            with self.subTest(type(exc).__name__):
                entry = R.make_entry(self.tmp / type(exc).__name__)
                result = review.review_entry(entry, dict(R.INSTANCE), call_fn=R.FakeCall(exc), token=R.TOKEN,
                                             model=R.MODEL, effort=R.EFFORT)
                self.assertEqual(result["status"], "error")
                self.assertEqual(review_json(entry), result)

    def test_vo5_d4_garbage_and_schema_violation_status_error(self):
        s = R.scenario("D4", self.tmp)
        self.assert_error(s, None)
        shutil_root = self.tmp / "schema"
        entry = R.make_entry(shutil_root)
        bad = R.model_text(R.payload(understanding=R.category("diverged")))
        result = review.review_entry(entry, dict(R.INSTANCE), call_fn=R.FakeCall(bad), token=R.TOKEN,
                                     model=R.MODEL, effort=R.EFFORT)
        self.assertEqual(result["status"], "error")
        self.assertEqual(review_json(entry), result)

    def test_vo5_d5_no_transcript_dir_missing_or_empty_makes_no_model_call(self):
        for name in ("D5a", "D5b"):
            with self.subTest(name):
                s = R.scenario(name, self.tmp / name)
                self.assert_error(s, "no transcript")
                self.assertEqual(s.result["error"], "no transcript")
                self.assertEqual(s.call.count, 0)

    def test_vo5_d5_jsonl_files_but_zero_brief_items_is_no_transcript(self):
        rows = [R.user("only user"), R.assistant(R.thinking_block("t")), R.BAD_JSON_LINE]
        entry = R.make_entry(self.tmp, transcripts={R.UUID_A + ".jsonl": rows})
        call = R.FakeCall(R.model_text(R.payload()))
        result = review.review_entry(entry, dict(R.INSTANCE), call_fn=call, token=R.TOKEN,
                                     model=R.MODEL, effort=R.EFFORT)
        self.assertEqual(result, {"status": "error", "instance_id": "inst-1", "error": "no transcript"})
        self.assertEqual(review_json(entry), result)
        self.assertEqual(call.count, 0)

    def test_vo5_d6_token_in_output_writes_no_review_and_returns_error_form(self):
        s = R.scenario("D6", self.tmp)
        self.assertFalse((s.entry / "review.json").exists())
        self.assertEqual(s.result, {"status": "error", "instance_id": "inst-1",
                                    "error": "token found in review output"})
        self.assertEqual(s.call.count, 1)

    def test_vo5_d6_token_in_any_field_is_detected(self):
        placements = {
            "citation": R.payload(understanding=R.category("diverged", R.finding("s", "[x] " + R.TOKEN))),
            "false claim summary": R.payload(ask_options=R.category("diverged", R.finding(R.TOKEN, "[spec]", True))),
        }
        for label, cats in placements.items():
            with self.subTest(label):
                entry = R.make_entry(self.tmp / label.replace(" ", "_"))
                result = review.review_entry(entry, dict(R.INSTANCE), call_fn=R.FakeCall(R.model_text(cats)),
                                             token=R.TOKEN, model=R.MODEL, effort=R.EFFORT)
                self.assertEqual(result["error"], "token found in review output")
                self.assertFalse((entry / "review.json").exists())

    def test_vo5_empty_token_never_triggers_the_refusal(self):
        entry = R.make_entry(self.tmp)
        result = review.review_entry(entry, dict(R.INSTANCE), call_fn=R.FakeCall(R.model_text(R.payload())),
                                     token="", model=R.MODEL, effort=R.EFFORT)
        self.assertEqual(result["status"], "ok")
        self.assertTrue((entry / "review.json").is_file())

    def assert_prompt_has_spec_and_ask(self, prompt):
        for line in ("Implementation: src/pkg/mod.py", "Tests: tests/test_x.py", "status: complete"):
            self.assertIn(line, prompt)
        self.assertRegex(prompt, r"\(ask\) ")
        self.assertIn("Which opt?", prompt)
        self.assertIn("A-opt", prompt)

    def test_vo5_d4_bare_form_without_categories_key_is_an_error(self):
        entry = R.make_entry(self.tmp)
        result = review.review_entry(entry, dict(R.INSTANCE), call_fn=R.FakeCall(json.dumps(R.payload())),
                                     token=R.TOKEN, model=R.MODEL, effort=R.EFFORT)
        self.assertEqual(result["status"], "error")

    def assert_error(self, s, reason_part):
        written = review_json(s.entry)
        self.assertEqual(written, s.result)
        self.assertEqual(set(written), {"status", "instance_id", "error"})
        self.assertEqual((written["status"], written["instance_id"]), ("error", "inst-1"))
        self.assertIsInstance(written["error"], str)
        self.assertTrue(written["error"].strip())
        self.assertNotIn("\n", written["error"])
        if reason_part:
            self.assertIn(reason_part, written["error"])


# ----------------------------------------------------------------------------------------------
# VO6 run files are never changed; VO7 token confinement
# ----------------------------------------------------------------------------------------------

class NoMutationTests(TmpCase):
    def test_vo6_only_review_json_may_be_new_and_nothing_else_changes(self):
        for name in R.SCENARIOS:
            with self.subTest(name):
                s = R.scenario(name, self.tmp / name)
                new = set(s.after) - set(s.before)
                expected_new = set() if name == "D6" else {str((s.entry / "review.json").relative_to(s.root))}
                self.assertEqual(new, expected_new)
                for path, data in s.before.items():
                    self.assertEqual(s.after.get(path), data, path)
                self.assertIn("run/inst-1/harness/process.json", s.before)
                self.assertIn("run/inst-1/harness/prediction.json", s.before)
                self.assertIn("run/scores.harness.jsonl", s.before)


class TokenTests(TmpCase):
    def run_with(self, label, response):
        entry = R.make_entry(self.tmp / label)
        result = review.review_entry(entry, dict(R.INSTANCE), call_fn=R.FakeCall(response), token=R.TOKEN,
                                     model=R.MODEL, effort=R.EFFORT)
        self.assertEqual(result["status"], "error")
        self.assertNotIn(R.TOKEN, json.dumps(result))
        for path, data in m.tree(self.tmp / label).items():
            self.assertNotIn(R.TOKEN.encode(), data, path)

    def test_vo7_token_in_garbage_output_or_exception_message_never_lands_anywhere(self):
        cases = {
            "garbage": "not json at all " + R.TOKEN,
            "invalid json with token": '{"categories": ' + R.TOKEN,
            "exception message": RuntimeError("claude failed with " + R.TOKEN),
            "exception second line": RuntimeError("first\n" + R.TOKEN),
            "schema violation": json.dumps({"categories": {"understanding": R.TOKEN}}),
        }
        for label, response in cases.items():
            with self.subTest(label):
                self.run_with(label.replace(" ", "_"), response)

    def test_vo7_no_file_contains_the_token_after_any_scenario(self):
        for name in R.SCENARIOS:
            with self.subTest(name):
                s = R.scenario(name, self.tmp / name)
                for path, data in s.after.items():
                    self.assertNotIn(R.TOKEN.encode(), data, path)
                self.assertNotIn(R.TOKEN, json.dumps(s.result))


if __name__ == "__main__":
    unittest.main()

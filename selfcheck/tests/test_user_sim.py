import copy
import unittest

from claude_agent_sdk import PermissionResultAllow

from selfcheck.agent import user_sim
from selfcheck.tests import agent_fakes as F


def q(question, labels, multi=None, header="H"):
    item = {"question": question, "header": header, "options": [{"label": l, "description": "d"} for l in labels]}
    if multi is not None:
        item["multiSelect"] = multi
    return item


class LiteralConstantTests(unittest.TestCase):
    def test_vo2_d1_phrase_is_the_spec_literal(self):
        self.assertEqual(user_sim.PHRASE, F.PHRASE)

    def test_vo1_a2_approval_words_are_the_spec_literal(self):
        self.assertEqual(user_sim.APPROVAL_WORDS, F.APPROVAL_WORDS)


class AnswerTests(unittest.TestCase):
    def one(self, question):
        return user_sim.answer([question])[question["question"]]

    def test_vo1_a1_single_select_picks_the_first_recommended_option(self):
        for name, labels, expected in (
            ("middle", ["Alpha", "Beta (Recommended)", "Gamma"], "Beta (Recommended)"),
            ("first", ["Alpha (Recommended)", "Beta"], "Alpha (Recommended)"),
            ("two recommended single-select -> first", ["A", "B (Recommended)", "C (Recommended)"], "B (Recommended)"),
        ):
            with self.subTest(name):
                self.assertEqual(self.one(q("Pick?", labels, multi=False)), expected)

    def test_vo1_a1_missing_multiselect_key_is_single_select(self):
        self.assertEqual(self.one(q("Pick?", ["Alpha", "B (Recommended)", "C (Recommended)"])), "B (Recommended)")

    def test_vo1_a2_english_approval_word_is_a_case_insensitive_substring(self):
        for name, labels, expected in (
            ("upper-case word inside text", ["Reject", "Please PROCEED now"], "Please PROCEED now"),
            ("first matching option wins", ["Maybe later", "Accept the plan", "Yes, go"], "Accept the plan"),
            ("substring not whole word", ["Alpha", "Reapproved"], "Reapproved"),
            ("each listed word", ["Alpha", "Continue"], "Continue"),
        ):
            with self.subTest(name):
                self.assertEqual(self.one(q("Pick?", labels, multi=False)), expected)

    def test_vo1_a2_every_english_approval_word_selects_its_option(self):
        for word in ("approve", "proceed", "continue", "accept", "yes"):
            with self.subTest(word=word):
                self.assertEqual(self.one(q("Pick?", ["Alpha", "Go %s now" % word.upper(), "Gamma"])), "Go %s now" % word.upper())

    def test_vo1_a3_korean_approval_word_selects_its_option(self):
        for word in ("승인", "진행", "계속", "예"):
            with self.subTest(word=word):
                labels = ["아니오 취소" if word != "예" else "취소", "%s 합니다" % word]
                self.assertEqual(self.one(q("선택?", labels, multi=False)), "%s 합니다" % word)

    def test_vo1_a4_no_recommended_and_no_approval_word_picks_the_first_option(self):
        self.assertEqual(self.one(q("Pick?", ["Alpha", "Beta", "Gamma"], multi=False)), "Alpha")

    def test_vo1_a5_recommended_wins_over_an_earlier_approval_word(self):
        self.assertEqual(
            self.one(q("Pick?", ["Approve everything", "Use B (Recommended)"], multi=False)), "Use B (Recommended)"
        )

    def test_vo1_a6_multi_select_joins_every_recommended_option_in_option_order(self):
        for name, labels, expected in (
            ("two", ["A (Recommended)", "B", "C (Recommended)"], "A (Recommended), C (Recommended)"),
            ("three", ["X (Recommended)", "Y (Recommended)", "Z (Recommended)"], "X (Recommended), Y (Recommended), Z (Recommended)"),
            ("one", ["A", "B (Recommended)"], "B (Recommended)"),
        ):
            with self.subTest(name):
                self.assertEqual(self.one(q("Pick many?", labels, multi=True)), expected)

    def test_vo1_a7_multi_select_without_recommended_follows_the_single_select_rule(self):
        for name, labels, expected in (
            ("approval word", ["Alpha", "Accept all", "Beta"], "Accept all"),
            ("neither -> first", ["Alpha", "Beta"], "Alpha"),
        ):
            with self.subTest(name):
                self.assertEqual(self.one(q("Pick many?", labels, multi=True)), expected)

    def test_vo1_a8_two_questions_are_answered_independently_keyed_by_question_text(self):
        questions = [
            q("First?", ["Alpha", "Beta (Recommended)"], multi=False),
            q("Second?", ["Nope", "Please continue", "Other"], multi=False),
            q("Third?", ["P (Recommended)", "Q", "R (Recommended)"], multi=True),
        ]
        self.assertEqual(
            user_sim.answer(questions),
            {"First?": "Beta (Recommended)", "Second?": "Please continue", "Third?": "P (Recommended), R (Recommended)"},
        )

    def test_vo1_a11_approval_selection_follows_option_order_not_word_order(self):
        # "accept" precedes "yes" in APPROVAL_WORDS; the option listed first still wins.
        for name, labels, multi, expected in (
            ("single", ["Yes, go", "Accept the plan"], False, "Yes, go"),
            ("single, later word first", ["Alpha", "Yes, go", "Accept the plan"], False, "Yes, go"),
            ("multi without recommended", ["Yes, go", "Accept the plan"], True, "Yes, go"),
            ("korean before english", ["계속 하자", "Approve"], False, "계속 하자"),
        ):
            with self.subTest(name):
                self.assertEqual(self.one(q("Pick?", labels, multi=multi)), expected)

    def test_vo1_a12_a_lowercase_recommended_marker_is_not_recommended(self):
        for name, labels, multi, expected in (
            ("lowercase, neither word -> first", ["Alpha", "Beta (recommended)", "Gamma"], False, "Alpha"),
            ("lowercase, approval word wins", ["Alpha", "Beta (recommended)", "Accept"], False, "Accept"),
            ("uppercase marker is not Recommended either", ["Alpha", "Beta (RECOMMENDED)"], False, "Alpha"),
            ("multi: only the exact-case option is joined", ["A (recommended)", "B (Recommended)"], True, "B (Recommended)"),
            ("multi: lowercase only -> single-select rule", ["Alpha", "B (recommended)"], True, "Alpha"),
        ):
            with self.subTest(name):
                self.assertEqual(self.one(q("Pick?", labels, multi=multi)), expected)

    def test_vo1_a13_a_question_without_options_is_answered_with_the_empty_string(self):
        for name, multi in (("single", False), ("multi", True), ("no multiSelect key", None)):
            with self.subTest(name):
                self.assertEqual(self.one(q("Free text?", [], multi=multi)), "")
        self.assertEqual(
            user_sim.answer([q("Free text?", []), q("Pick?", ["Alpha", "Beta (Recommended)"], multi=False)]),
            {"Free text?": "", "Pick?": "Beta (Recommended)"},
        )


class OnIdleRuleTests(unittest.TestCase):
    SEND = ("send", F.PHRASE)

    def test_vo2_d15_on_idle_returns_exactly_the_rule_outcome_for_each_fr9_rule(self):
        cases = (
            ("first idle point sends, no tool calls", (0, 0, 8), self.SEND),
            ("first idle point sends, with tool calls", (0, 5, 8), self.SEND),
            ("after a phrase with zero tool calls -> completed", (1, 0, 8), ("stop", "completed")),
            ("later phrase with zero tool calls -> completed", (3, 0, 8), ("stop", "completed")),
            ("zero tool calls at max_user_turns -> completed, not stalled", (8, 0, 8), ("stop", "completed")),
            ("zero tool calls at max 1 -> completed", (1, 0, 1), ("stop", "completed")),
            ("max reached with tool calls -> stalled", (8, 1, 8), ("stop", "stalled")),
            ("max reached with many tool calls -> stalled", (3, 40, 3), ("stop", "stalled")),
            ("max 1 reached with tool calls -> stalled", (1, 2, 1), ("stop", "stalled")),
            ("else branch: below max with tool calls", (1, 1, 8), self.SEND),
            ("else branch: middle", (4, 2, 8), self.SEND),
            ("else branch: one below max", (7, 1, 8), self.SEND),
        )
        for name, args, expected in cases:
            with self.subTest(name):
                result = user_sim.on_idle(*args)
                self.assertIsInstance(result, tuple)
                self.assertEqual(result, expected)


class CallbackThroughDriverTests(F.DriverCase):
    def test_vo1_a9_ask_user_question_returns_unchanged_questions_plus_answers_and_logs_answer(self):
        questions = [
            q("Which?", ["Alpha", "Beta (Recommended)"], multi=False),
            q("Many?", ["A (Recommended)", "B", "C (Recommended)"], multi=True),
        ]
        original = copy.deepcopy(questions)
        out = self.drive([[F.Ask(questions, tool_use_id="toolu_q"), F.result()], [F.result()]])
        client = out.client
        self.assertEqual(len(client.permission_results), 1)
        decision = client.permission_results[0]
        self.assertIsInstance(decision, PermissionResultAllow)
        self.assertEqual(
            decision.updated_input,
            {"questions": original, "answers": {"Which?": "Beta (Recommended)", "Many?": "A (Recommended), C (Recommended)"}},
        )
        answer_lines = [l for l in out.user() if l["action"] == "answer"]
        self.assertEqual(len(answer_lines), 1)
        line = answer_lines[0]
        self.assertEqual(set(line), {"t", "action", "questions", "answers"})
        self.assertEqual(line["questions"], original)
        self.assertEqual(line["answers"], decision.updated_input["answers"])
        self.assertEqual([l for l in out.user() if l["action"] == "allow"], [])

    def test_vo1_a10_other_tools_are_allowed_unchanged_and_logged_allow(self):
        tool_input = {"command": "ls -la", "description": "list"}
        out = self.drive([[F.Tool("Bash", tool_input, ask_permission=True, tool_use_id="toolu_b"), F.result()], [F.result()]])
        decision = out.client.permission_results[0]
        self.assertIsInstance(decision, PermissionResultAllow)
        self.assertEqual(decision.updated_input, tool_input)
        allow_lines = [l for l in out.user() if l["action"] == "allow"]
        self.assertEqual(len(allow_lines), 1)
        self.assertEqual(set(allow_lines[0]), {"t", "action", "tool_name"})
        self.assertEqual(allow_lines[0]["tool_name"], "Bash")
        self.assertEqual([l for l in out.user() if l["action"] == "answer"], [])


if __name__ == "__main__":
    unittest.main()

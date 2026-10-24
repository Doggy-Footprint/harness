import unittest

from evaluation.pr_test_quality import compose

PARAGRAPH = ("Write thorough automated tests: cover normal cases, boundaries, invalid inputs and error paths, "
             "assert observable behavior rather than implementation details, and run the tests before you finish.")
BRIEF = {"request": "Please add clamp(value, lo, hi) in src/ops.py. Implement this and add automated tests.",
         "statements": [], "ambiguous": []}


class Compose(unittest.TestCase):
    def test_O9_arms_constant(self):
        self.assertEqual(compose.ARMS, ("B0", "Bplus", "H"))

    def test_O9_C21_bplus_paragraph_text_is_fixed(self):
        self.assertEqual(compose.BPLUS_PARAGRAPH, PARAGRAPH)

    def test_O9_b0_is_the_request_only(self):
        self.assertEqual(compose.compose_prompt(BRIEF, "B0"), BRIEF["request"])

    def test_O9_C21_bplus_is_request_blank_line_paragraph(self):
        self.assertEqual(compose.compose_prompt(BRIEF, "Bplus"), BRIEF["request"] + "\n\n" + PARAGRAPH)

    def test_O9_h_is_slash_command_prefix_and_request(self):
        self.assertEqual(compose.compose_prompt(BRIEF, "H"), "/workflow-approach " + BRIEF["request"])

    def test_O9_prompts_follow_the_request_not_a_constant(self):
        other = dict(BRIEF, request="Different request. Implement this and add automated tests.")
        for arm in compose.ARMS:
            with self.subTest(arm=arm):
                self.assertNotEqual(compose.compose_prompt(BRIEF, arm), compose.compose_prompt(other, arm))
                self.assertIn(other["request"], compose.compose_prompt(other, arm))

    def test_O9_unknown_arm_raises_value_error(self):
        for arm in ("B1", "b0", "", "bplus"):
            with self.subTest(arm=arm):
                with self.assertRaises(ValueError):
                    compose.compose_prompt(BRIEF, arm)

    def test_O9_only_bplus_contains_the_paragraph(self):
        self.assertNotIn(PARAGRAPH, compose.compose_prompt(BRIEF, "B0"))
        self.assertNotIn(PARAGRAPH, compose.compose_prompt(BRIEF, "H"))


if __name__ == "__main__":
    unittest.main()

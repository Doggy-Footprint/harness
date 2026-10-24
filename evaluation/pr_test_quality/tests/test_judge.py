import copy
import hashlib
import itertools
import json
import re
import unittest

from evaluation.pr_test_quality import judge
from evaluation.pr_test_quality.tests.fakes import FakeCall, TmpCase, make_task, udiff

SMELLS = ("assertion_roulette", "conditional_test_logic", "eager_test", "empty_test", "exception_handling",
          "magic_number", "mystery_guest", "redundant_assertion", "sensitive_equality", "sleepy_test",
          "unknown_test", "duplicate_assert", "ignored_test")
DESIDERATA = ("isolated", "composable", "readable", "behavioral", "structure_insensitive", "specific",
              "predictive", "writable")
BRIEF = {"request": "r", "statements": [{"id": "S1", "text": "Upper bound is returned.", "f2p": ["f1"]},
                                         {"id": "S2", "text": "Lower bound is returned.", "f2p": ["f2"]}],
         "ambiguous": []}
CAND = {"label": "T1", "source": "H-r0",
        "text": "def test_magic():\n    assert compute(7) == 42\n    assert compute(0)   ==\n 1\n"}
QUOTE = "assert compute(7) == 42"


def valid_absolute(cand=CAND, brief=BRIEF):
    return {
        "smells": [{"smell": "magic_number", "test": "test_magic", "quote": QUOTE}],
        "desiderata": {p: {"score": 4, "rationale": "fine", "quote": QUOTE} for p in DESIDERATA},
        "coverage": {s["id"]: {"level": "covered", "quote": QUOTE} for s in brief["statements"]},
        "boundary": True,
        "error_path": False,
    }


class Constants(unittest.TestCase):
    def test_O19_smell_catalog(self):
        self.assertEqual(tuple(judge.SMELLS), SMELLS)

    def test_O19_desiderata_judged(self):
        self.assertEqual(tuple(judge.DESIDERATA_JUDGED), DESIDERATA)

    def test_O19_measured_desiderata_are_not_judged(self):
        self.assertNotIn("deterministic", judge.DESIDERATA_JUDGED)
        self.assertNotIn("fast", judge.DESIDERATA_JUDGED)


class ParseAbsolute(unittest.TestCase):
    def parse(self, data, brief=BRIEF):
        text = data if isinstance(data, str) else json.dumps(data)
        return judge.parse_absolute(text, CAND, brief)

    def test_O19_valid_response_is_accepted(self):
        data = valid_absolute()
        out = self.parse(data)
        self.assertEqual(out, dict(data, label="T1"))

    def test_O19_error_class_is_value_error(self):
        self.assertTrue(issubclass(judge.JudgeFormatError, ValueError))

    def test_O19_every_catalog_smell_is_accepted(self):
        for smell in SMELLS:
            data = valid_absolute()
            data["smells"] = [{"smell": smell, "test": "test_magic", "quote": QUOTE}]
            with self.subTest(smell=smell):
                self.parse(data)

    def test_O19_unknown_smell_rejected(self):
        data = valid_absolute()
        data["smells"][0]["smell"] = "flaky_vibes"
        with self.assertRaises(judge.JudgeFormatError):
            self.parse(data)

    def test_O19_unknown_property_rejected(self):
        data = valid_absolute()
        data["desiderata"]["shininess"] = {"score": 3, "rationale": "x", "quote": QUOTE}
        with self.assertRaises(judge.JudgeFormatError):
            self.parse(data)

    def test_O19_score_boundaries_one_and_five_ok_zero_and_six_rejected(self):
        for score, ok in ((1, True), (5, True), (0, False), (6, False)):
            data = valid_absolute()
            data["desiderata"]["isolated"]["score"] = score
            with self.subTest(score=score):
                if ok:
                    self.parse(data)
                else:
                    with self.assertRaises(judge.JudgeFormatError):
                        self.parse(data)

    def test_O19_missing_statement_rejected(self):
        data = valid_absolute()
        del data["coverage"]["S2"]
        with self.assertRaises(judge.JudgeFormatError):
            self.parse(data)

    def test_O19_C33_quote_not_in_candidate_rejected(self):
        for where in ("smell", "desideratum", "coverage"):
            data = valid_absolute()
            if where == "smell":
                data["smells"][0]["quote"] = "assert compute(8) == 99"
            elif where == "desideratum":
                data["desiderata"]["readable"]["quote"] = "assert compute(8) == 99"
            else:
                data["coverage"]["S1"]["quote"] = "assert compute(8) == 99"
            with self.subTest(where=where):
                with self.assertRaises(judge.JudgeFormatError):
                    self.parse(data)

    def test_O19_whitespace_collapsed_quote_is_accepted(self):
        data = valid_absolute()
        data["smells"][0]["quote"] = "assert   compute(7)\n==    42"
        self.parse(data)
        data["smells"][0]["quote"] = "assert compute(0) == 1"
        self.parse(data)

    def test_O19_F10_empty_quote_only_allowed_for_level_none(self):
        data = valid_absolute()
        data["coverage"]["S1"] = {"level": "none", "quote": ""}
        self.parse(data)
        for level in ("covered", "partial"):
            data["coverage"]["S1"] = {"level": level, "quote": ""}
            with self.subTest(level=level):
                with self.assertRaises(judge.JudgeFormatError):
                    self.parse(data)

    def test_O19_F10_coverage_levels_and_flags(self):
        for level in ("covered", "partial", "none"):
            data = valid_absolute()
            data["coverage"]["S1"] = {"level": level, "quote": "" if level == "none" else QUOTE}
            self.parse(data)
        data = valid_absolute()
        data["coverage"]["S1"]["level"] = "mostly"
        with self.assertRaises(judge.JudgeFormatError):
            self.parse(data)
        for key in ("boundary", "error_path"):
            data = valid_absolute()
            del data[key]
            with self.subTest(missing=key):
                with self.assertRaises(judge.JudgeFormatError):
                    self.parse(data)

    def test_O19_non_json_rejected(self):
        for text in ("", "not json", "{\"smells\": ", "[1, 2]"):
            with self.subTest(text=text):
                with self.assertRaises(judge.JudgeFormatError):
                    self.parse(text)


class Candidates(unittest.TestCase):
    def setUp(self):
        self.task = make_task("python")
        self.entries = [
            {"key": "B0-r1", "arm": "B0", "repeat": 1, "status": "completed", "text": "def test_MARK_B0(): pass\n"},
            {"key": "Bplus-r1", "arm": "Bplus", "repeat": 1, "status": "completed",
             "text": "def test_MARK_BPLUS(): pass\n"},
            {"key": "H-r1", "arm": "H", "repeat": 1, "status": "completed", "text": "def test_MARK_H(): pass\n"},
            {"key": "H-r2", "arm": "H", "repeat": 2, "status": "stalled", "text": "def test_MARK_STALLED(): pass\n"},
            {"key": "B0-r2", "arm": "B0", "repeat": 2, "status": "interrupted", "text": "def test_MARK_INT(): pass\n"},
        ]

    def cands(self, seed=0):
        return judge.candidates(self.task, copy.deepcopy(self.entries), seed)

    def expected_order(self, seed):
        sources = ["human", "B0-r1", "Bplus-r1", "H-r1"]
        return sorted(sources, key=lambda src: hashlib.sha256(
            ("%s:%s:%s" % (seed, self.task["task_id"], src)).encode()).hexdigest())

    def test_O18_F11_order_is_ascending_sha256_of_seed_task_source(self):
        for seed in (0, 1, 7, 12345):
            with self.subTest(seed=seed):
                out = self.cands(seed)
                self.assertEqual([c["source"] for c in out], self.expected_order(seed))
                self.assertEqual([c["label"] for c in out], ["T1", "T2", "T3", "T4"])

    def test_O18_only_completed_entries_plus_one_human(self):
        out = self.cands()
        self.assertEqual(sorted(c["source"] for c in out), sorted(["human", "B0-r1", "Bplus-r1", "H-r1"]))
        human = [c for c in out if c["source"] == "human"]
        self.assertEqual(len(human), 1)
        self.assertEqual(human[0]["text"], self.task["gold_split"]["tests"])

    def test_O18_entry_candidates_carry_their_own_text(self):
        out = {c["source"]: c["text"] for c in self.cands()}
        self.assertEqual(out["B0-r1"], self.entries[0]["text"])
        self.assertEqual(out["Bplus-r1"], self.entries[1]["text"])
        self.assertEqual(out["H-r1"], self.entries[2]["text"])
        self.assertNotIn("MARK_STALLED", json.dumps(out))
        self.assertNotIn("MARK_INT", json.dumps(out))

    def test_O18_shuffle_is_deterministic_per_seed(self):
        for seed in (0, 1, 12345):
            self.assertEqual(self.cands(seed), self.cands(seed))

    def test_O18_seed_changes_the_order(self):
        orders = {tuple(c["source"] for c in self.cands(seed)) for seed in range(30)}
        self.assertGreater(len(orders), 1)

    def test_O18_human_is_not_always_first(self):
        firsts = {self.cands(seed)[0]["source"] for seed in range(30)}
        self.assertGreater(len(firsts), 1)


class Anonymize(unittest.TestCase):
    def test_O18_sixteen_hex_ids_replaced(self):
        self.assertEqual(judge.anonymize("run 0123456789abcdef finished", set()), "run ID finished")
        self.assertEqual(judge.anonymize("a 616f94189f1a4147 b 616f94189f1a4147", set()), "a ID b ID")

    def test_O18_spec_ids_replaced_only_as_whole_words(self):
        out = judge.anonymize("see S1 and S12 and XS1 and S1. then FR-A3 matters", {"S1", "FR-A3"})
        self.assertEqual(out, "see ID and S12 and XS1 and ID. then ID matters")

    def test_O18_unlisted_ids_stay(self):
        self.assertEqual(judge.anonymize("S1 and S2", {"S1"}), "ID and S2")

    def test_O18_lines_referencing_agent_docs_are_dropped(self):
        text = "keep one\nsee agent-docs/specs/x.md for more\nkeep two\n"
        self.assertEqual(judge.anonymize(text, set()), "keep one\nkeep two\n")

    def test_O18_plain_text_is_unchanged(self):
        text = "def test_a():\n    assert f(1) == 2\n"
        self.assertEqual(judge.anonymize(text, {"S1"}), text)


class Combine(unittest.TestCase):
    TABLE = {
        ("first", "first"): "inconsistent", ("first", "second"): "A", ("first", "tie"): "tie",
        ("second", "first"): "B", ("second", "second"): "inconsistent", ("second", "tie"): "tie",
        ("tie", "first"): "tie", ("tie", "second"): "tie", ("tie", "tie"): "tie",
    }

    def test_O20_all_nine_combinations(self):
        for (ab, ba), want in self.TABLE.items():
            with self.subTest(ab=ab, ba=ba):
                self.assertEqual(judge.combine_orders(ab, ba), want)

    def test_O20_table_covers_the_whole_product(self):
        self.assertEqual(set(self.TABLE), set(itertools.product(("first", "second", "tie"), repeat=2)))

    def test_O20_C30_same_candidate_wins_in_both_orders(self):
        self.assertEqual(judge.combine_orders("first", "second"), "A")

    def test_O20_C31_tie_with_one_winner_is_tie(self):
        self.assertEqual(judge.combine_orders("tie", "first"), "tie")

    def test_O20_C32_winner_flips_with_position_is_inconsistent(self):
        self.assertEqual(judge.combine_orders("first", "first"), "inconsistent")


class PairwiseParse(unittest.TestCase):
    def test_O20_parse_pairwise_outcomes(self):
        for word in ("first", "second", "tie"):
            with self.subTest(word=word):
                self.assertEqual(judge.parse_pairwise(json.dumps({"winner": word, "rationale": "r"})), word)

    def test_O20_F10_bare_word_is_accepted(self):
        for word in ("first", "second", "tie"):
            self.assertEqual(judge.parse_pairwise(word), word)
            self.assertEqual(judge.parse_pairwise(" %s\n" % word), word)

    def test_O20_parse_pairwise_rejects_garbage(self):
        with self.assertRaises(ValueError):
            judge.parse_pairwise("no idea")


class Prompts(unittest.TestCase):
    def setUp(self):
        self.task = make_task("python")

    def test_O19_absolute_prompt_carries_candidate_catalogs_and_statements(self):
        prompt = judge.build_absolute_prompt(self.task, BRIEF, CAND)
        self.assertIn(QUOTE, prompt)
        for name in SMELLS + DESIDERATA:
            self.assertIn(name, prompt)
        for statement in BRIEF["statements"]:
            self.assertIn(statement["id"], prompt)
            self.assertIn(statement["text"], prompt)

    def test_O20_pairwise_prompt_keeps_candidate_order(self):
        first = {"label": "T1", "source": "x", "text": "def test_FIRSTMARK(): pass\n"}
        second = {"label": "T2", "source": "y", "text": "def test_SECONDMARK(): pass\n"}
        p = judge.build_pairwise_prompt(self.task, BRIEF, first, second)
        self.assertLess(p.index("FIRSTMARK"), p.index("SECONDMARK"))
        q = judge.build_pairwise_prompt(self.task, BRIEF, second, first)
        self.assertLess(q.index("SECONDMARK"), q.index("FIRSTMARK"))


def _text(key, strong=False):
    return "def test_MARK_%s():\n    assert compute(1) == 111  # %s\n%s" % (
        key.replace("-", "_"), key, "    # STRONG\n" if strong else "")


class JudgeTask(TmpCase):
    def setUp(self):
        super().setUp()
        self.task = make_task("python", brief=dict(BRIEF, status="ok"))
        human = _text("human")
        self.task["gold_split"] = dict(self.task["gold_split"], tests=udiff("tests/test_ops.py", None, human))
        self.entries = []
        for repeat in (1, 2):
            for arm in ("B0", "Bplus", "H"):
                key = "%s-r%d" % (arm, repeat)
                status = "stalled" if key == "H-r2" else "completed"
                self.entries.append({"key": key, "arm": arm, "repeat": repeat, "status": status,
                                     "text": _text(key, strong=(arm == "H"))})
        self.cfg_ = self.cfg()
        self.quote = "assert compute(1) == 111"
        self.fail_abs_for = set()

    @staticmethod
    def mark(key):
        return "MARK_" + key.replace("-", "_")

    def responder(self, prompt):
        keys = [e["key"] for e in self.entries] + ["human"]
        present = [k for k in keys if self.mark(k) in prompt]
        if len(present) >= 2:
            if not any(k.startswith("H-") for k in present):
                return json.dumps({"winner": "tie", "rationale": "same"})
            hk = [k for k in present if k.startswith("H-")][0]
            others = [k for k in present if k != hk]
            h_first = prompt.index(self.mark(hk)) < min(prompt.index(self.mark(k)) for k in others)
            return json.dumps({"winner": "first" if h_first else "second", "rationale": "H"})
        data = valid_absolute()
        data["smells"][0]["quote"] = self.quote
        for p in data["desiderata"].values():
            p["quote"] = self.quote
        for s in data["coverage"].values():
            s["quote"] = self.quote
        if present and present[0] in self.fail_abs_for:
            data["smells"][0]["quote"] = "assert nonsense(0) == 0"
        return json.dumps(data)

    def run_judge(self):
        call = FakeCall([self.responder])
        return judge.judge_task(self.task, copy.deepcopy(self.entries), call_fn=call, cfg=self.cfg_), call

    def test_O20_F11_pair_schedule_only_where_both_entries_completed(self):
        out, call = self.run_judge()
        records = out["pairwise"]
        got = sorted((r["repeat"], tuple(sorted(re.findall(r"Bplus|B0|H", json.dumps(r["pair"]))))) for r in records)
        self.assertEqual(got, [(1, ("B0", "Bplus")), (1, ("B0", "H")), (1, ("Bplus", "H")), (2, ("B0", "Bplus"))])
        for r in records:
            self.assertEqual(set(r), {"pair", "repeat", "ab", "ba", "outcome"})
            arms = re.findall(r"Bplus|B0|H", json.dumps(r["pair"]))
            if "H" in arms:
                self.assertEqual(r["outcome"], "A" if arms[0] == "H" else "B")
            else:
                self.assertEqual(r["outcome"], "tie")
            self.assertEqual(r["outcome"], judge.combine_orders(r["ab"], r["ba"]))

    def test_O20_each_pair_is_asked_once_per_order_with_candidates_in_that_order(self):
        out, call = self.run_judge()
        pair_prompts = [p for p in call.prompts if p.count("MARK_") >= 2]
        self.assertEqual(len(pair_prompts), 2 * len(out["pairwise"]))
        self.assertEqual(len(set(pair_prompts)), len(pair_prompts))

    def test_O18_labels_map_to_sources_including_human(self):
        out, _ = self.run_judge()
        self.assertEqual(sorted(out["labels"].values()),
                         sorted(["human", "B0-r1", "Bplus-r1", "H-r1", "B0-r2", "Bplus-r2"]))
        self.assertEqual(sorted(out["labels"]), ["T1", "T2", "T3", "T4", "T5", "T6"])
        self.assertEqual(set(out["absolute"]), set(out["labels"]))

    def test_O19_C33_quote_mismatch_retries_once_then_records_error_and_others_continue(self):
        self.fail_abs_for = {"B0-r1"}
        out, call = self.run_judge()
        errors = [label for label, v in out["absolute"].items() if v == "error"]
        self.assertEqual(len(errors), 1)
        self.assertEqual(out["labels"][errors[0]], "B0-r1")
        good = [v for v in out["absolute"].values() if v != "error"]
        self.assertEqual(len(good), 5)
        abs_calls = [p for p in call.prompts if "MARK_B0_r1" in p and p.count("MARK_") == 1]
        self.assertEqual(len(abs_calls), 2)


if __name__ == "__main__":
    unittest.main()

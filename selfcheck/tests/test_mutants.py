import hashlib
import re
import threading
import time
import unittest
from collections import Counter

from selfcheck import mutants
from selfcheck.tests.helpers import FakeEvaluate, eval_result, git_apply_files, git_diff

FILLER = "".join("# filler %d\n" % n for n in range(12))
BASE2 = (
    "def f(a, b):\n    x = a <= b\n    w = a != b\n    return x\n"
    + FILLER
    + "def g(a, b):\n    y = a - b\n    return y\n"
)
GOLD2 = (
    "def f(a, b):\n    x = a < b\n    w = a == b\n    return x\n"
    + FILLER
    + "def g(a, b):\n    y = a + b\n    return y\n"
)
N_GOLD = "def k(p):\n    if p:\n        return 1\n    return 2\n"
SIMPLE = "def f(a, b):\n    x = a < b\n    return x\n"


def replace_line(text, number, new):
    lines = text.split("\n")
    lines[number - 1] = new
    return "\n".join(lines)


GOLD2_EXPECTED = {
    replace_line(GOLD2, 2, "    x = a <= b"),
    replace_line(GOLD2, 2, "    pass"),
    replace_line(GOLD2, 3, "    w = a != b"),
    replace_line(GOLD2, 3, "    pass"),
    replace_line(GOLD2, 18, "    y = a - b"),
    replace_line(GOLD2, 18, "    pass"),
}
N_EXPECTED = {
    "def k(p):\n    if not (p):\n        return 1\n    return 2\n",
    "def k(p):\n    if p:\n        return 2\n    return 2\n",
    "def k(p):\n    if p:\n        return 1\n    return 3\n",
    "def k(p):\n    if p:\n        pass\n    return 2\n",
    "def k(p):\n    if p:\n        return 1\n    pass\n",
    "def k(p):\n    if p:\n        return None\n    return 2\n",
    "def k(p):\n    if p:\n        return 1\n    return None\n",
}
SIMPLE_EXPECTED = {
    "def f(a, b):\n    x = a <= b\n    return x\n",
    "def f(a, b):\n    pass\n    return x\n",
    "def f(a, b):\n    x = a < b\n    pass\n",
    "def f(a, b):\n    x = a < b\n    return None\n",
}


def generate(base, gold, sample=1000, seed=1, patch=None):
    patch = git_diff(base, gold) if patch is None else patch
    return mutants.generate(base, gold, patch, sample=sample, seed=seed)


def mutated_texts(base, found):
    result = []
    for item in found:
        files = git_apply_files({k: v for k, v in base.items() if v is not None}, item["patch"])
        result.append((item["path"], files))
    return result


def texts_for(source, operator=None, base=None):
    base = {"m.py": None} if base is None else base
    found = generate(base, {"m.py": source})
    if operator is not None:
        found = [m for m in found if m["operator"] == operator]
    return found, [files["m.py"] for _, files in mutated_texts(base, found)]


class OperatorTests(unittest.TestCase):
    def check(self, source, operator, expected, replacements=None):
        found, texts = texts_for(source, operator)
        self.assertEqual(sorted(texts), sorted(expected))
        self.assertEqual(len(found), len(expected))
        if replacements is not None:
            self.assertEqual([m["replacement"] for m in found], replacements)

    def test_vo5_g1_operators_constant(self):
        self.assertEqual(mutants.OPERATORS, ("ROR", "LCR", "AOR", "NEG", "CRP", "SDL", "RVR", "BCR"))

    def test_vo5_g1_ror_every_replacement(self):
        pairs = [
            ("<", "<="), ("<=", "<"), (">", ">="), (">=", ">"), ("==", "!="), ("!=", "=="),
            ("is", "is not"), ("is not", "is"), ("in", "not in"), ("not in", "in"),
        ]
        for old, new in pairs:
            with self.subTest(old=old, new=new):
                self.check("x = a %s b\n" % old, "ROR", ["x = a %s b\n" % new], [new])

    def test_vo5_g1_lcr_every_replacement(self):
        for old, new in (("and", "or"), ("or", "and")):
            with self.subTest(old=old):
                self.check("x = a %s b\n" % old, "LCR", ["x = a %s b\n" % new], [new])

    def test_vo5_g1_aor_every_replacement(self):
        pairs = [("+", "-"), ("-", "+"), ("*", "/"), ("/", "*"), ("//", "/"), ("%", "*")]
        for old, new in pairs:
            with self.subTest(old=old, new=new):
                self.check("x = a %s b\n" % old, "AOR", ["x = a %s b\n" % new], [new])

    def test_vo5_g1_neg_if_while_ternary(self):
        cases = [
            ("if c:\n    y = 1\n", "if not (c):\n    y = 1\n"),
            ("while c:\n    y = 1\n", "while not (c):\n    y = 1\n"),
            ("x = 1 if c else 2\n", "x = 1 if not (c) else 2\n"),
        ]
        for source, expected in cases:
            with self.subTest(source=source):
                self.check(source, "NEG", [expected])

    def test_vo5_g1_neg_not_prefix_is_removed_and_test_is_negated(self):
        found, texts = texts_for("if not done:\n    y = 1\n", "NEG")
        self.assertEqual(
            sorted(texts), sorted(["if not (not done):\n    y = 1\n", "if done:\n    y = 1\n"])
        )
        self.assertEqual(sorted(m["replacement"] for m in found), sorted(["", "not (not done)"]))

    def test_vo5_g1_neg_not_outside_a_test_is_a_site(self):
        found, texts = texts_for("x = not y\n", "NEG")
        self.assertEqual(texts, ["x = y\n"])
        self.assertEqual([m["replacement"] for m in found], [""])

    def test_vo5_g1_assert_test_is_not_wrapped(self):
        for source in ("assert x == 1\n", "assert x\n"):
            with self.subTest(source=source):
                self.check(source, "NEG", [])

    def test_vo5_g11_not_inside_assert_is_a_site_without_wrapping(self):
        found, texts = texts_for("assert not x\n", "NEG")
        self.assertEqual(texts, ["assert x\n"])
        self.assertEqual([m["replacement"] for m in found], [""])
        self.assertEqual([m["original"] for m in found], ["not "])

    def test_vo5_g12_chained_comparison_gives_one_site_per_operator_token(self):
        found, texts = texts_for("x = a < b < c\n", "ROR")
        self.assertEqual(texts, ["x = a <= b < c\n", "x = a < b <= c\n"])
        self.assertEqual([m["col"] for m in found], [6, 10])
        _, texts = texts_for("x = a < b > c\n", "ROR")
        self.assertEqual(sorted(texts), sorted(["x = a <= b > c\n", "x = a < b >= c\n"]))

    def test_vo5_g12_three_operand_boolean_operation_gives_one_site_per_token(self):
        found, texts = texts_for("x = a and b and c\n", "LCR")
        self.assertEqual(texts, ["x = a or b and c\n", "x = a and b or c\n"])
        self.assertEqual([m["col"] for m in found], [6, 12])
        _, texts = texts_for("x = a or b or c\n", "LCR")
        self.assertEqual(texts, ["x = a and b or c\n", "x = a or b and c\n"])

    def test_vo5_g1_crp_every_replacement(self):
        cases = [
            ("x = 5\n", "x = 6\n", "6"),
            ("x = 0\n", "x = 1\n", "1"),
            ("x = True\n", "x = False\n", "False"),
            ("x = False\n", "x = True\n", "True"),
            ('x = "abc"\n', 'x = ""\n', '""'),
            ('x = ""\n', 'x = "XX"\n', '"XX"'),
        ]
        for source, expected, replacement in cases:
            with self.subTest(source=source):
                self.check(source, "CRP", [expected], [replacement])

    def test_vo5_g1_sdl_statement_kinds_and_non_sites(self):
        source = (
            "def f(x):\n"
            "    \"\"\"doc\"\"\"\n"
            "    global G\n"
            "    w: int\n"
            "    pass\n"
            "    for i in x:\n"
            "        break\n"
            "        continue\n"
            "    def inner():\n"
            "        nonlocal y\n"
            "    g(x)\n"
            "    y = x\n"
            "    y += 1\n"
            "    z: int = 2\n"
            "    del y\n"
            "    import os\n"
            "    from os import path\n"
            "    assert x\n"
            "    raise ValueError\n"
            "    return y\n"
        )
        lines = source.split("\n")
        sites = [
            "    g(x)", "    y = x", "    y += 1", "    z: int = 2", "    del y",
            "    import os", "    from os import path", "    assert x",
            "    raise ValueError", "    return y",
        ]
        expected = [replace_line(source, lines.index(site) + 1, "    pass") for site in sites]
        self.check(source, "SDL", expected, ["pass"] * len(sites))

    def test_vo5_g1_sdl_single_kinds(self):
        cases = {
            "expression": ("g(1)\n", "pass\n"),
            "assignment": ("x = 1\n", "pass\n"),
            "augmented": ("x += 1\n", "pass\n"),
            "annotated_with_value": ("x: int = 1\n", "pass\n"),
            "del": ("del x\n", "pass\n"),
            "raise": ("raise ValueError\n", "pass\n"),
            "assert": ("assert x\n", "pass\n"),
            "return": ("def f():\n    return x\n", "def f():\n    pass\n"),
            "import": ("import os\n", "pass\n"),
            "from_import": ("from os import path\n", "pass\n"),
        }
        for name, (source, expected) in cases.items():
            with self.subTest(kind=name):
                self.check(source, "SDL", [expected], ["pass"])

    def test_vo5_g1_sdl_non_sites(self):
        cases = [
            ("pass\n", []),
            ("for i in r:\n    break\n", []),
            ("for i in r:\n    continue\n", []),
            ("def f():\n    global G\n", []),
            ("x: int\n", []),
            ("def f():\n    \"\"\"doc\"\"\"\n", []),
            (
                "def f():\n    y = 1\n    def g():\n        nonlocal y\n",
                ["def f():\n    pass\n    def g():\n        nonlocal y\n"],
            ),
        ]
        for source, expected in cases:
            with self.subTest(source=source):
                self.check(source, "SDL", expected)

    def test_vo5_g1_rvr_replaces_return_values_only(self):
        self.check(
            "def f(x):\n    return x + 1\n", "RVR", ["def f(x):\n    return None\n"]
        )
        self.check("def f(x):\n    return None\n", "RVR", [])

    def test_vo5_g1_bcr_swaps_break_and_continue(self):
        self.check("for i in r:\n    break\n", "BCR", ["for i in r:\n    continue\n"], ["continue"])
        self.check("for i in r:\n    continue\n", "BCR", ["for i in r:\n    break\n"], ["break"])

    def test_vo5_g1_each_mutant_names_its_operator_and_group(self):
        found = generate({"m.py": None}, {"m.py": SIMPLE})
        for item in found:
            self.assertIn(item["operator"], mutants.OPERATORS)
            self.assertTrue(item["group"].endswith(":" + item["operator"]), item["group"])


class SourceSelectionTests(unittest.TestCase):
    def test_vo5_g2_only_changed_lines_are_mutated(self):
        base = {"m.py": BASE2, "unchanged.py": "x = a < b\n"}
        gold = {"m.py": GOLD2, "unchanged.py": "x = a < b\n"}
        found = generate(base, gold)
        texts = {files["m.py"] for _, files in mutated_texts(base, found)}
        self.assertEqual(texts, GOLD2_EXPECTED)
        self.assertEqual(len(found), 6)
        self.assertEqual(Counter(m["operator"] for m in found), Counter({"ROR": 2, "SDL": 3, "AOR": 1}))
        self.assertEqual({m["path"] for m in found}, {"m.py"})
        self.assertEqual(sorted(m["line"] for m in found), [2, 2, 3, 3, 18, 18])

    def test_vo5_g3_new_file_has_every_line_changed(self):
        base = {"n.py": None}
        found = generate(base, {"n.py": N_GOLD})
        self.assertEqual({files["n.py"] for _, files in mutated_texts(base, found)}, N_EXPECTED)
        self.assertEqual(len(found), 7)

    def test_vo5_g4_unparsable_and_non_python_files_are_skipped(self):
        base = {"bad.py": None, "ok.py": None, "notes.txt": None}
        gold = {"bad.py": "def (:\n", "ok.py": "x = a < b\n", "notes.txt": "if x < y\n"}
        found = generate(base, gold)
        self.assertEqual({m["path"] for m in found}, {"ok.py"})
        texts = {files["ok.py"] for _, files in mutated_texts(base, found)}
        self.assertEqual(texts, {"x = a <= b\n", "pass\n"})

    def test_vo5_g4_only_unparsable_file_gives_no_mutants(self):
        self.assertEqual(generate({"bad.py": None}, {"bad.py": "class :\n"}), [])

    def test_vo5_g5_no_two_mutants_produce_the_same_file(self):
        base = {"m.py": None}
        sources = [
            "if not not y:\n    z = 1\n",
            "z = not not y\n",
            "def f(a):\n    return a + a\n",
        ]
        for source in sources:
            with self.subTest(source=source):
                found = generate(base, {"m.py": source})
                texts = [files["m.py"] for _, files in mutated_texts(base, found)]
                self.assertEqual(len(texts), len(set(texts)))
                self.assertEqual(len({m["id"] for m in found}), len(found))
                self.assertNotIn(source, texts)

    def test_vo5_g5_duplicate_texts_are_kept_once(self):
        _, texts = texts_for("if not not y:\n    z = 1\n", "NEG")
        self.assertEqual(sorted(texts), sorted([
            "if not (not not y):\n    z = 1\n", "if not y:\n    z = 1\n",
        ]))
        _, texts = texts_for("z = not not y\n", "NEG")
        self.assertEqual(texts, ["z = not y\n"])

    def test_vo5_g5_mutation_equal_to_gold_is_dropped(self):
        found = generate({"m.py": None}, {"m.py": "def f():\n    return None\n"})
        self.assertEqual([m for m in found if m["operator"] == "RVR"], [])


class NoNewlineMarkerHunkTests(unittest.TestCase):
    def test_vo5_g14_added_lines_after_a_no_newline_marker_carry_that_hunk_index(self):
        base = {"m.py": BASE2.rstrip("\n")}
        gold = {"m.py": GOLD2 + "    q = a * b\n"}
        patch = git_diff(base, gold)
        self.assertIn("\\ No newline at end of file", patch)
        self.assertEqual(patch.count("\n@@ "), 2)
        found = generate(base, gold, patch=patch)
        self.assertEqual(
            sorted((m["line"], m["group"]) for m in found),
            sorted([
                (2, "0:ROR"), (2, "0:SDL"), (3, "0:ROR"), (3, "0:SDL"),
                (18, "1:AOR"), (18, "1:SDL"), (19, "1:RVR"), (19, "1:SDL"),
                (20, "1:AOR"), (20, "1:SDL"),
            ]),
        )


class FieldTests(unittest.TestCase):
    def one(self, source, operator, nth=0):
        found = [m for m in generate({"m.py": None}, {"m.py": source}) if m["operator"] == operator]
        return found[nth]

    def test_vo5_fields_line_col_original_replacement(self):
        cases = [
            ("ROR", "x = a < b\n", 1, 6, "<", "<="),
            ("AOR", "x = a + b\n", 1, 6, "+", "-"),
            ("LCR", "x = a and b\n", 1, 6, "and", "or"),
            ("CRP", "x = 5\n", 1, 4, "5", "6"),
            ("BCR", "for i in r:\n    break\n", 2, 4, "break", "continue"),
            ("RVR", "def f(x):\n    return x + 1\n", 2, 11, "x + 1", "None"),
            ("SDL", "x = a < b\n", 1, 0, "x = a < b", "pass"),
            ("NEG", "x = 1 if c else 2\n", 1, 9, "c", "not (c)"),
            ("NEG", "if c:\n    y = 1\n", 1, 3, "c", "not (c)"),
        ]
        for operator, source, line, col, original, replacement in cases:
            with self.subTest(operator=operator, source=source):
                item = self.one(source, operator)
                self.assertEqual(
                    (item["line"], item["col"], item["original"], item["replacement"]),
                    (line, col, original, replacement),
                )

    def test_vo5_fields_col_counts_characters_not_bytes(self):
        item = self.one('s = "\u00e9" < b\n', "ROR")
        self.assertEqual((item["line"], item["col"], item["original"]), (1, 8, "<"))

    def test_vo5_fields_not_prefix_removal_span(self):
        found = [m for m in generate({"m.py": None}, {"m.py": "x = not y\n"}) if m["operator"] == "NEG"]
        self.assertEqual(
            (found[0]["line"], found[0]["col"], found[0]["original"], found[0]["replacement"]),
            (1, 4, "not ", ""),
        )

    def test_vo5_g13_original_of_not_removal_keeps_the_whitespace_up_to_the_operand(self):
        found, texts = texts_for("x = not   y\n", "NEG")
        self.assertEqual([m["original"] for m in found], ["not   "])
        self.assertEqual(texts, ["x = y\n"])

    def test_vo5_renamed_files_are_skipped(self):
        old = "x = a < b\ny = 1\nz = 2\nw = 3\nv = 4\nu = 5\n"
        new = "x = a < b\ny = 1\nz = 2\nw = 3\nv = 4\nu = 6\n"
        base = {"old.py": old}
        gold = {"new.py": new}
        patch = git_diff(base, gold)
        self.assertIn("rename from old.py", patch)
        self.assertEqual(generate(base, gold, patch=patch), [])


class StructureTests(unittest.TestCase):
    def test_vo5_g9_patches_apply_to_base_and_give_gold_except_mutated_file(self):
        base = {"m.py": BASE2, "n.py": None}
        gold = {"m.py": GOLD2, "n.py": N_GOLD}
        found = generate(base, gold)
        self.assertEqual(len(found), 13)
        pairs = set()
        for item, (path, files) in zip(found, mutated_texts(base, found)):
            other = "n.py" if path == "m.py" else "m.py"
            self.assertEqual(files[other], gold[other])
            self.assertNotEqual(files[path], gold[path])
            compile(files[path], path, "exec")
            pairs.add((path, files[path]))
        self.assertEqual(
            pairs,
            {("m.py", t) for t in GOLD2_EXPECTED} | {("n.py", t) for t in N_EXPECTED},
        )
        self.assertEqual(set(files), {"m.py", "n.py"})

    def test_vo5_g10_ids_follow_the_specified_hash(self):
        found = generate({"m.py": BASE2, "n.py": None}, {"m.py": GOLD2, "n.py": N_GOLD})
        for item in found:
            key = "%s|%d|%d|%s|%s" % (item["path"], item["line"], item["col"], item["operator"], item["replacement"])
            self.assertEqual(item["id"], "m" + hashlib.sha256(key.encode()).hexdigest()[:10])
            self.assertRegex(item["id"], r"^m[0-9a-f]{10}$")
        self.assertEqual(len({m["id"] for m in found}), len(found))

    def test_vo5_g10_mutant_dict_has_exactly_the_specified_keys(self):
        found = generate({"m.py": None}, {"m.py": SIMPLE})
        expected = {"id", "path", "line", "col", "operator", "original", "replacement", "group", "patch"}
        for item in found:
            self.assertEqual(set(item), expected)
            self.assertIsInstance(item["line"], int)
            self.assertIsInstance(item["col"], int)

    def test_vo5_output_is_sorted_by_specified_key(self):
        found = generate({"m.py": BASE2, "n.py": None}, {"m.py": GOLD2, "n.py": N_GOLD})
        keys = [(m["path"], m["line"], m["col"], m["operator"], m["replacement"]) for m in found]
        self.assertEqual(keys, sorted(keys))
        sampled = generate({"m.py": BASE2, "n.py": None}, {"m.py": GOLD2, "n.py": N_GOLD}, sample=5)
        keys = [(m["path"], m["line"], m["col"], m["operator"], m["replacement"]) for m in sampled]
        self.assertEqual(keys, sorted(keys))

    def test_vo5_g6_deterministic_for_equal_inputs(self):
        base = {"m.py": BASE2, "n.py": None}
        gold = {"m.py": GOLD2, "n.py": N_GOLD}
        patch = git_diff(base, gold)
        first = generate(base, gold, sample=5, seed=3, patch=patch)
        second = generate(base, gold, sample=5, seed=3, patch=patch)
        self.assertEqual(first, second)
        reordered_base = dict(reversed(list(base.items())))
        reordered_gold = dict(reversed(list(gold.items())))
        self.assertEqual(generate(reordered_base, reordered_gold, sample=5, seed=3, patch=patch), first)

    def test_vo5_g6_seed_changes_the_sample(self):
        base = {"m.py": BASE2}
        gold = {"m.py": GOLD2}
        outcomes = {tuple(m["id"] for m in generate(base, gold, sample=4, seed=seed)) for seed in range(10)}
        self.assertGreater(len(outcomes), 1)


class SampleTests(unittest.TestCase):
    def setUp(self):
        self.base = {"m.py": None}
        self.gold = {"m.py": SIMPLE}
        self.full = generate(self.base, self.gold)

    def test_vo5_g7_full_candidate_set_is_four_known_files(self):
        texts = {files["m.py"] for _, files in mutated_texts(self.base, self.full)}
        self.assertEqual(texts, SIMPLE_EXPECTED)
        self.assertEqual(len(self.full), 4)

    def test_vo5_g7_candidates_below_and_equal_to_sample_are_all_returned(self):
        for sample in (5, 4):
            with self.subTest(sample=sample):
                self.assertEqual(generate(self.base, self.gold, sample=sample), self.full)

    def test_vo5_g7_candidates_above_sample_are_cut_to_sample(self):
        full_ids = {m["id"] for m in self.full}
        for sample in (3, 2, 1):
            with self.subTest(sample=sample):
                got = generate(self.base, self.gold, sample=sample)
                self.assertEqual(len(got), sample)
                self.assertTrue({m["id"] for m in got} <= full_ids)
                self.assertEqual(len({m["id"] for m in got}), sample)

    def test_vo5_g8_every_group_is_represented_when_sample_covers_groups(self):
        got = generate(self.base, self.gold, sample=3)
        self.assertEqual(Counter(m["operator"] for m in got), Counter({"ROR": 1, "SDL": 1, "RVR": 1}))

    def test_vo5_g8_groups_with_two_hunks_all_represented(self):
        base = {"m.py": BASE2}
        gold = {"m.py": GOLD2}
        every_group = {m["group"] for m in generate(base, gold)}
        self.assertEqual(len(every_group), 4)
        for sample in (4, 5):
            with self.subTest(sample=sample):
                got = generate(base, gold, sample=sample)
                self.assertEqual(len(got), sample)
                self.assertEqual({m["group"] for m in got}, every_group)
        exact = Counter(m["group"] for m in generate(base, gold, sample=4))
        self.assertEqual(set(exact.values()), {1})

    def test_vo5_g8_group_names_carry_zero_based_global_hunk_index(self):
        found = generate({"m.py": BASE2}, {"m.py": GOLD2})
        self.assertEqual(
            sorted((m["line"], m["group"]) for m in found),
            sorted([
                (2, "0:ROR"), (2, "0:SDL"), (3, "0:ROR"), (3, "0:SDL"), (18, "1:AOR"), (18, "1:SDL"),
            ]),
        )

    def test_vo5_g8_hunk_index_continues_across_files_in_patch_order(self):
        found = generate({"m.py": BASE2, "n.py": None}, {"m.py": GOLD2, "n.py": N_GOLD})
        groups = {(m["path"], m["group"].split(":")[0]) for m in found}
        self.assertEqual(groups, {("m.py", "0"), ("m.py", "1"), ("n.py", "2")})

    def test_vo5_g8_fewer_slots_than_groups_pick_distinct_groups(self):
        got = generate(self.base, self.gold, sample=2)
        self.assertEqual(len({m["group"] for m in got}), 2)

    def test_vo5_g6_seed_picks_different_groups_when_slots_are_scarce(self):
        outcomes = {
            tuple(m["id"] for m in generate(self.base, self.gold, sample=2, seed=seed)) for seed in range(10)
        }
        self.assertGreater(len(outcomes), 1)


F1 = "t/test_f.py::test_f1"
PE = "t/test_p.py::test_effective"
PF = "t/test_p.py::test_flaky"
OTHER = "t/test_o.py::test_other"
TESTS = "GOLD-TEST-PATCH"


def survive():
    return eval_result({F1: "PASSED", PE: "PASSED", PF: "PASSED", OTHER: "PASSED"})


def with_status(**changes):
    result = survive()
    for name, value in changes.items():
        test = {"f1": F1, "pe": PE, "pf": PF, "other": OTHER}[name]
        if value is None:
            result["status"].pop(test)
        else:
            result["status"][test] = value
    return result


class DetectTests(unittest.TestCase):
    CASES = [
        ("survive", survive(), True, False, False),
        ("f2p_fail", with_status(f1="FAILED"), True, True, False),
        ("p2p_effective_fail", with_status(pe="FAILED"), True, True, False),
        ("flaky_p2p_and_other_fail", with_status(pf="FAILED", other="FAILED"), True, False, False),
        ("timeout", {**survive(), "timed_out": True}, True, True, True),
        ("f2p_missing", with_status(f1=None), True, True, False),
        ("p2p_effective_missing", with_status(pe=None), True, True, False),
        ("f2p_skipped", with_status(f1="SKIPPED"), True, True, False),
        ("f2p_xfail", with_status(f1="XFAIL"), True, False, False),
        ("f2p_error", with_status(f1="ERROR"), True, True, False),
        ("compile_invalid", survive(), False, False, False),
    ]

    def setUp(self):
        self.instance = {
            "instance_id": "d__d-1", "test_patch": TESTS,
            "FAIL_TO_PASS": [F1], "PASS_TO_PASS": [PE, PF],
        }
        self.validation = {"f2p": [F1], "p2p_effective": [PE], "p2p_flaky": [PF], "p2p_broken": []}
        self.items = [
            {"id": "m%d" % i, "path": "p%d.py" % i, "patch": "PATCH-%d" % i, "line": i}
            for i in range(len(self.CASES))
        ]
        self.by_patch = {
            "PATCH-%d" % i: case[1] for i, case in enumerate(self.CASES)
        }
        self.invalid = {"PATCH-%d" % i for i, case in enumerate(self.CASES) if not case[2]}

    def run_detect(self, workers):
        compile_calls = []
        lock = threading.Lock()
        total = len(self.items)

        def compile_fn(instance, patch, paths):
            with lock:
                compile_calls.append((patch, list(paths)))
            return patch not in self.invalid

        def respond(instance, src_diff, test_patch, **kwargs):
            index = int(src_diff.split("-")[1])
            time.sleep((total - index) * 0.01)
            return self.by_patch[src_diff]

        evaluate = FakeEvaluate(respond)
        found = mutants.detect(
            self.instance, self.items, validation=self.validation,
            evaluate_fn=evaluate, compile_fn=compile_fn, workers=workers,
        )
        return found, compile_calls, evaluate.calls

    def expected(self):
        return [
            {**item, "compile_ok": case[2], "killed": case[3], "timeout": case[4]}
            for item, case in zip(self.items, self.CASES)
        ]

    def test_vo9_k1_to_k6_results_for_every_decision_row(self):
        for workers in (1, 3):
            with self.subTest(workers=workers):
                found, _, _ = self.run_detect(workers)
                self.assertEqual(found, self.expected())

    def test_vo9_k_rows_individually(self):
        found, _, _ = self.run_detect(1)
        for case, item in zip(self.CASES, found):
            with self.subTest(case=case[0]):
                self.assertIs(item["compile_ok"], case[2])
                self.assertIs(item["killed"], case[3])
                self.assertIs(item["timeout"], case[4])

    def test_vo9_k1_compile_invalid_is_not_evaluated(self):
        _, compile_calls, evaluate_calls = self.run_detect(3)
        invalid_patch = "PATCH-%d" % (len(self.CASES) - 1)
        self.assertNotIn(invalid_patch, [call[0] for call in evaluate_calls])
        self.assertEqual(len(evaluate_calls), len(self.CASES) - 1)

    def test_vo9_call_contract_for_compile_and_evaluate(self):
        _, compile_calls, evaluate_calls = self.run_detect(2)
        self.assertEqual(
            sorted(compile_calls), sorted(("PATCH-%d" % i, ["p%d.py" % i]) for i in range(len(self.CASES)))
        )
        self.assertEqual(
            sorted(evaluate_calls, key=lambda call: call[0]),
            sorted(
                [("PATCH-%d" % i, TESTS, {}) for i in range(len(self.CASES) - 1)],
                key=lambda call: call[0],
            ),
        )

    def test_vo9_results_keep_input_order_even_when_completion_order_is_reversed(self):
        found, _, _ = self.run_detect(3)
        self.assertEqual([m["id"] for m in found], ["m%d" % i for i in range(len(self.CASES))])

    def test_vo9_empty_mutant_list(self):
        found = mutants.detect(
            self.instance, [], validation=self.validation,
            evaluate_fn=FakeEvaluate(lambda *a, **k: survive()), compile_fn=lambda *a: True,
        )
        self.assertEqual(found, [])


if __name__ == "__main__":
    unittest.main()

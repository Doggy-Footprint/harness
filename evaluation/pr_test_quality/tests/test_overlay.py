import unittest

from evaluation.pr_test_quality import overlay
from evaluation.pr_test_quality.tests.fakes import udiff

PATHS = {
    "python": {"src": "src/s.py", "other": "conf/x.yaml", "test": "tests/test_t.py"},
    "typescript": {"src": "src/s.ts", "other": "conf/x.yaml", "test": "src/t.test.ts"},
    "go": {"src": "pkg/s.go", "other": "conf/x.yaml", "test": "pkg/t_test.go"},
    "rust": {"src": "src/s.rs", "other": "conf/x.yaml", "test": "tests/t.rs"},
}
HARNESS = ".claude/h.json"
ABSENT = object()


def side(files, kinds):
    """files: path -> (base, after); kinds: path -> src|other|test|harness."""
    split = {"src": "", "tests": "", "harness": "", "other": ""}
    for path, (base, after) in files.items():
        key = {"src": "src", "other": "other", "test": "tests", "harness": "harness"}[kinds[path]]
        split[key] += udiff(path, base, after)
    return {"base": {p: b for p, (b, _) in files.items()}, "after": {p: a for p, (_, a) in files.items()},
            "split": split}


def empty():
    return side({}, {})


class Matrix(unittest.TestCase):
    def build(self, language, kind, who, gold_after="G", agent_after="A", base="B"):
        path = PATHS[language][kind] if kind != "harness" else HARNESS
        kinds = {path: kind}
        make = lambda after: side({path: (base, after)}, kinds)
        gold = make(gold_after) if who in ("gold", "both") else empty()
        agent = make(agent_after) if who in ("agent", "both") else empty()
        return path, gold, agent

    def expect(self, tree, path, want):
        if want is ABSENT:
            self.assertNotIn(path, tree)
        else:
            self.assertIn(path, tree)
            self.assertEqual(tree[path], want)

    TABLE = {
        ("src", "gold"): (ABSENT, "G"), ("src", "agent"): ("A", ABSENT), ("src", "both"): ("A", "G"),
        ("other", "gold"): (ABSENT, "G"), ("other", "agent"): ("A", ABSENT), ("other", "both"): ("A", "G"),
        ("test", "gold"): ("G", ABSENT), ("test", "agent"): (ABSENT, "A"), ("test", "both"): ("G", "A"),
        ("harness", "gold"): (ABSENT, ABSENT), ("harness", "agent"): (ABSENT, ABSENT),
        ("harness", "both"): (ABSENT, ABSENT),
    }

    def test_O15_decision_table_every_row_every_language(self):
        for language in PATHS:
            for (kind, who), (hidden_want, validity_want) in self.TABLE.items():
                with self.subTest(language=language, kind=kind, who=who):
                    path, gold, agent = self.build(language, kind, who)
                    self.expect(overlay.hidden_tree(language, gold, agent), path, hidden_want)
                    self.expect(overlay.validity_tree(language, gold, agent), path, validity_want)

    def test_O15_deletions_are_none_entries(self):
        for language in PATHS:
            with self.subTest(language=language):
                path, gold, agent = self.build(language, "src", "gold", gold_after=None)
                self.assertIsNone(overlay.validity_tree(language, gold, agent)[path])
                path, gold, agent = self.build(language, "src", "agent", agent_after=None)
                self.assertIsNone(overlay.hidden_tree(language, gold, agent)[path])
                path, gold, agent = self.build(language, "test", "gold", gold_after=None)
                self.assertIsNone(overlay.hidden_tree(language, gold, agent)[path])
                path, gold, agent = self.build(language, "test", "agent", agent_after=None)
                self.assertIsNone(overlay.validity_tree(language, gold, agent)[path])

    def test_O15_new_file_in_agent_src_is_written_with_its_text(self):
        path = PATHS["python"]["src"]
        agent = side({path: (None, "NEW\n")}, {path: "src"})
        tree = overlay.hidden_tree("python", empty(), agent)
        self.assertEqual(tree, {path: "NEW\n"})

    def test_O15_all_kinds_together_do_not_cross_contaminate(self):
        p = PATHS["python"]
        files_g = {p["src"]: ("B", "GS"), p["other"]: ("B", "GO"), p["test"]: ("B", "GT"), HARNESS: ("B", "GH")}
        files_a = {p["src"]: ("B", "AS"), p["other"]: ("B", "AO"), p["test"]: ("B", "AT"), HARNESS: ("B", "AH"),
                   "agent-docs/specs/x.md": (None, "spec\n")}
        kinds = {p["src"]: "src", p["other"]: "other", p["test"]: "test", HARNESS: "harness",
                 "agent-docs/specs/x.md": "harness"}
        gold, agent = side(files_g, kinds), side(files_a, kinds)
        self.assertEqual(overlay.hidden_tree("python", gold, agent),
                         {p["src"]: "AS", p["other"]: "AO", p["test"]: "GT"})
        self.assertEqual(overlay.validity_tree("python", gold, agent),
                         {p["src"]: "GS", p["other"]: "GO", p["test"]: "AT"})

    def test_O15_C42_harness_parts_are_never_applied(self):
        files = {".claude/settings.json": ("{}\n", "{\"a\": 1}\n"), "agent-docs/specs/x.md": (None, "s\n")}
        kinds = {k: "harness" for k in files}
        agent = side(files, kinds)
        for tree in (overlay.hidden_tree("python", empty(), agent), overlay.validity_tree("python", empty(), agent),
                     overlay.hidden_tree("python", agent, empty()), overlay.validity_tree("python", agent, empty())):
            self.assertEqual(tree, {})

    def test_O15_trees_use_final_text_not_a_diff(self):
        path, gold, agent = self.build("python", "src", "agent", agent_after="line1\nline2\n")
        tree = overlay.hidden_tree("python", gold, agent)
        self.assertEqual(tree[path], "line1\nline2\n")
        self.assertNotIn("@@", tree[path])


GOLD_MOD = "#[cfg(test)]\nmod tests {\n    #[test]\n    fn gold_case() {\n        assert!(true);\n    }\n}\n"
AGENT_MOD = "#[cfg(test)]\nmod tests {\n    #[test]\n    fn agent_case() {\n        assert!(true);\n    }\n}\n"
BASE_RS = "pub fn base() {}\n"
GOLD_REST = "pub fn base() {}\npub fn gold_fn() {}\n"
AGENT_REST = "pub fn base() {}\npub fn agent_fn() {}\n"
LIB = "src/lib.rs"


def rust_side(rest, mod, base=BASE_RS):
    after = rest + ("\n" + mod if mod else "")
    split = {"src": udiff(LIB, base, rest), "tests": udiff(LIB + "#cfgtest", None, mod) if mod else "",
             "harness": "", "other": ""}
    return {"base": {LIB: base}, "after": {LIB: after}, "split": split}


class RustCfgTest(unittest.TestCase):
    def test_O15_hidden_appends_gold_module_to_agent_version(self):
        tree = overlay.hidden_tree("rust", rust_side(GOLD_REST, GOLD_MOD), rust_side(AGENT_REST, AGENT_MOD))
        text = tree[LIB]
        self.assertIn("agent_fn", text)
        self.assertIn("gold_case", text)
        self.assertNotIn("agent_case", text)
        self.assertNotIn("gold_fn", text)
        self.assertLess(text.index("agent_fn"), text.index("gold_case"))
        self.assertEqual(text.count("#[cfg(test)]"), 1)

    def test_O15_hidden_with_agent_without_module_still_gets_gold_module(self):
        tree = overlay.hidden_tree("rust", rust_side(GOLD_REST, GOLD_MOD), rust_side(AGENT_REST, ""))
        self.assertIn("agent_fn", tree[LIB])
        self.assertIn("gold_case", tree[LIB])

    def test_O15_hidden_agent_untouched_file_uses_base_text_plus_gold_module(self):
        untouched = {"base": {LIB: BASE_RS}, "after": {LIB: BASE_RS}, "split": {"src": "", "tests": "", "harness": "", "other": ""}}
        tree = overlay.hidden_tree("rust", rust_side(GOLD_REST, GOLD_MOD), untouched)
        self.assertIn("pub fn base", tree[LIB])
        self.assertIn("gold_case", tree[LIB])
        self.assertNotIn("gold_fn", tree[LIB])

    def test_O15_validity_agent_module_replaces_gold_module_in_gold_file(self):
        tree = overlay.validity_tree("rust", rust_side(GOLD_REST, GOLD_MOD), rust_side(AGENT_REST, AGENT_MOD))
        text = tree[LIB]
        self.assertIn("gold_fn", text)
        self.assertIn("agent_case", text)
        self.assertNotIn("gold_case", text)
        self.assertNotIn("agent_fn", text)
        self.assertEqual(text.count("#[cfg(test)]"), 1)

    def test_O15_validity_agent_without_module_leaves_no_module(self):
        tree = overlay.validity_tree("rust", rust_side(GOLD_REST, GOLD_MOD), rust_side(AGENT_REST, ""))
        self.assertIn("gold_fn", tree[LIB])
        self.assertNotIn("gold_case", tree[LIB])
        self.assertNotIn("#[cfg(test)]", tree[LIB])


class CrossTree(unittest.TestCase):
    def test_O15_F17_rust_cross_tree_swaps_cfgtest_modules(self):
        impl = rust_side(AGENT_REST, AGENT_MOD)
        tests = rust_side(GOLD_REST, GOLD_MOD)
        text = overlay.cross_tree("rust", rust_side(GOLD_REST, GOLD_MOD), impl, tests)[LIB]
        self.assertIn("agent_fn", text)
        self.assertIn("gold_case", text)
        self.assertNotIn("agent_case", text)
        self.assertNotIn("gold_fn", text)
        self.assertEqual(text.count("#[cfg(test)]"), 1)


    def test_O15_cross_tree_takes_impl_src_and_tests_entry_tests(self):
        p = PATHS["python"]
        gold = side({p["src"]: ("B", "GS"), p["test"]: ("B", "GT")}, {p["src"]: "src", p["test"]: "test"})
        impl = side({p["src"]: ("B", "IS"), p["test"]: ("B", "IT"), HARNESS: ("B", "IH")},
                    {p["src"]: "src", p["test"]: "test", HARNESS: "harness"})
        tests = side({p["src"]: ("B", "TS"), p["test"]: ("B", "TT")}, {p["src"]: "src", p["test"]: "test"})
        tree = overlay.cross_tree("python", gold, impl, tests)
        self.assertEqual(tree[p["src"]], "IS")
        self.assertEqual(tree[p["test"]], "TT")
        self.assertNotIn(HARNESS, tree)


if __name__ == "__main__":
    unittest.main()

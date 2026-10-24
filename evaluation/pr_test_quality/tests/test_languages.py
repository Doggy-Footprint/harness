import unittest

from evaluation.pr_test_quality import languages
from evaluation.pr_test_quality.tests.fakes import diff_files, udiff

HARNESS_PATHS = [
    "agent-docs/adr/x.md", ".harness/hooks/x.sh", ".claude/settings.json", ".agents/skills/SKILL.md",
    ".codex/config.toml", "AGENTS.md", "CLAUDE.md",
]

CLASSIFY_CASES = [
    ("python", "tests/test_x.py", "test"),
    ("python", "src/tests/helper.py", "test"),
    ("python", "pkg/test/util.py", "test"),
    ("python", "pkg/test_mod.py", "test"),
    ("python", "pkg/mod_test.py", "test"),
    ("python", "pkg/conftest.py", "test"),
    ("python", "tests/data.json", "test"),
    ("python", "pkg/mod.py", "src"),
    ("python", "pkg/contest.py", "src"),
    ("python", "pkg/testing.py", "src"),
    ("python", "pkg/tests.py", "src"),
    ("python", "docs/readme.md", "other"),
    ("python", "setup.cfg", "other"),
    ("typescript", "src/a.test.ts", "test"),
    ("typescript", "src/a.spec.tsx", "test"),
    ("typescript", "src/__tests__/a.ts", "test"),
    ("typescript", "test/a.js", "test"),
    ("typescript", "tests/a.mjs", "test"),
    ("typescript", "src/a.ts", "src"),
    ("typescript", "src/a.tsx", "src"),
    ("typescript", "src/a.js", "src"),
    ("typescript", "src/a.jsx", "src"),
    ("typescript", "src/a.mjs", "src"),
    ("typescript", "src/a.cjs", "src"),
    ("typescript", "src/contest/a.ts", "src"),
    ("typescript", "package.json", "other"),
    ("typescript", "src/a.css", "other"),
    ("go", "pkg/a_test.go", "test"),
    ("go", "pkg/testdata/in.txt", "test"),
    ("go", "pkg/a.go", "src"),
    ("go", "pkg/test/a.go", "src"),
    ("go", "tests/a.go", "src"),
    ("go", "go.mod", "other"),
    ("rust", "tests/it.rs", "test"),
    ("rust", "tests/common/mod.rs", "test"),
    ("rust", "src/lib.rs", "src"),
    ("rust", "crates/x/tests/it.rs", "src"),
    ("rust", "benches/b.rs", "src"),
    ("rust", "Cargo.toml", "other"),
    ("python", "src/a.ts", "other"),
    ("typescript", "a.py", "other"),
    ("go", "tests/test_x.py", "other"),
    ("rust", "pkg/a_test.go", "other"),
    ("go", "a.test.ts", "other"),
    ("python", ".claude/tests/test_x.py", "harness"),
    ("typescript", "agent-docs/tests/a.test.ts", "harness"),
    ("python", "pkg/CLAUDE.md", "other"),
    ("python", "docs/AGENTS.md", "other"),
    ("python", "agent-docs-extra/x.py", "src"),
]


class ClassifyPath(unittest.TestCase):
    def test_O13_languages_constant(self):
        self.assertEqual(languages.LANGUAGES, ("python", "typescript", "go", "rust"))

    def test_O13_classification_table(self):
        for lang, path, want in CLASSIFY_CASES:
            with self.subTest(lang=lang, path=path):
                self.assertEqual(languages.classify_path(lang, path), want)

    def test_O13_each_harness_path_is_harness_in_every_language(self):
        for lang in languages.LANGUAGES:
            for path in HARNESS_PATHS:
                with self.subTest(lang=lang, path=path):
                    self.assertEqual(languages.classify_path(lang, path), "harness")


def file_diff_blocks(diff):
    names = diff_files(diff)
    return names


class SplitDiff(unittest.TestCase):
    def _split(self, language, files):
        diffs = [udiff(p, o, n) for p, o, n in files]
        return languages.split_diff(language, "".join(diffs)), diffs

    def test_O13_four_parts_assignment_python(self):
        files = [
            ("src/pkg/a.py", "x = 1\n", "x = 2\n"),
            ("tests/test_a.py", None, "def test_a():\n    assert True\n"),
            (".claude/settings.json", "{}\n", "{\"a\": 1}\n"),
            ("agent-docs/specs/x.md", None, "# spec\n"),
            ("README.md", "a\n", "b\n"),
        ]
        parts, diffs = self._split("python", files)
        self.assertEqual(set(parts), {"src", "tests", "harness", "other"})
        self.assertEqual(diff_files(parts["src"]), ["src/pkg/a.py"])
        self.assertEqual(diff_files(parts["tests"]), ["tests/test_a.py"])
        self.assertEqual(sorted(diff_files(parts["harness"])), [".claude/settings.json", "agent-docs/specs/x.md"])
        self.assertEqual(diff_files(parts["other"]), ["README.md"])
        self.assertIn(diffs[0], parts["src"])
        self.assertIn(diffs[1], parts["tests"])
        self.assertIn(diffs[2], parts["harness"])
        self.assertIn(diffs[3], parts["harness"])
        self.assertIn(diffs[4], parts["other"])

    def test_O13_C42_agent_docs_and_claude_settings_land_only_in_harness(self):
        files = [("agent-docs/specs/x.md", "a\n", "b\n"), (".claude/settings.json", "{}\n", "{\"k\": 1}\n")]
        parts, _ = self._split("python", files)
        self.assertEqual(sorted(diff_files(parts["harness"])), [".claude/settings.json", "agent-docs/specs/x.md"])
        for key in ("src", "tests", "other"):
            self.assertEqual(diff_files(parts[key]), [])

    def test_O13_empty_diff_gives_four_empty_parts(self):
        parts = languages.split_diff("go", "")
        self.assertEqual(set(parts), {"src", "tests", "harness", "other"})
        for value in parts.values():
            self.assertEqual(diff_files(value), [])

    def test_O13_language_specific_assignment_go_and_rust(self):
        go_parts, _ = self._split("go", [("pkg/a.go", "a\n", "b\n"), ("pkg/a_test.go", "a\n", "b\n"),
                                         ("tests/helper.go", "a\n", "b\n")])
        self.assertEqual(sorted(diff_files(go_parts["src"])), ["pkg/a.go", "tests/helper.go"])
        self.assertEqual(diff_files(go_parts["tests"]), ["pkg/a_test.go"])
        rs_parts, _ = self._split("rust", [("tests/it.rs", "a\n", "b\n"), ("crates/x/tests/it.rs", "a\n", "b\n")])
        self.assertEqual(diff_files(rs_parts["tests"]), ["tests/it.rs"])
        self.assertEqual(diff_files(rs_parts["src"]), ["crates/x/tests/it.rs"])

    RUST_OLD = (
        "pub fn add(a: i32, b: i32) -> i32 {\n    a + b\n}\n\n"
        "#[cfg(test)]\nmod tests {\n    use super::*;\n\n    #[test]\n    fn adds_works() {\n"
        "        assert_eq!(add(1, 2), 3);\n    }\n}\n")
    RUST_NEW = (
        "pub fn add(a: i32, b: i32) -> i32 {\n    a.wrapping_add(b)\n}\n\n"
        "#[cfg(test)]\nmod tests {\n    use super::*;\n\n    #[test]\n    fn adds_works() {\n"
        "        assert_eq!(add(1, 2), 3);\n    }\n\n    #[test]\n    fn adds_more() {\n"
        "        assert_eq!(add(2, 2), 4);\n    }\n}\n")

    def test_O13_C12_rust_new_file_inline_module_moves_to_tests(self):
        diff = udiff("src/lib.rs", None, self.RUST_NEW)
        parts = languages.split_diff("rust", diff)
        self.assertIn("pub fn add", parts["src"])
        self.assertNotIn("#[cfg(test)]", parts["src"])
        self.assertNotIn("adds_works", parts["src"])
        self.assertIn("src/lib.rs#cfgtest", parts["tests"])
        self.assertIn("fn adds_works", parts["tests"])
        self.assertNotIn("wrapping_add", parts["tests"])

    def test_O13_C12_rust_modified_file_src_change_and_module_change_separate(self):
        diff = udiff("src/lib.rs", self.RUST_OLD, self.RUST_NEW)
        parts = languages.split_diff("rust", diff)
        self.assertIn("wrapping_add", parts["src"])
        self.assertNotIn("mod tests", parts["src"])
        self.assertNotIn("adds_more", parts["src"])
        self.assertIn("src/lib.rs#cfgtest", parts["tests"])
        self.assertIn("adds_more", parts["tests"])
        self.assertNotIn("wrapping_add", parts["tests"])

    def test_O13_rust_src_without_module_stays_in_src_only(self):
        diff = udiff("src/lib.rs", "pub fn a() {}\n", "pub fn a() {}\npub fn b() {}\n")
        parts = languages.split_diff("rust", diff)
        self.assertEqual(diff_files(parts["src"]), ["src/lib.rs"])
        self.assertEqual(diff_files(parts["tests"]), [])


class SplitRustInline(unittest.TestCase):
    def test_O13_top_level_module_removed_and_returned(self):
        text = ("pub fn run() {}\n\n#[cfg(test)]\nmod tests {\n    #[test]\n    fn t() {}\n}\n\n"
                "pub fn after() {}\n")
        rest, mods = languages.split_rust_inline(text)
        self.assertEqual(len(mods), 1)
        self.assertIn("mod tests", mods[0])
        self.assertIn("fn t()", mods[0])
        self.assertIn(mods[0], text)
        self.assertIn("pub fn run", rest)
        self.assertIn("pub fn after", rest)
        self.assertNotIn("mod tests", rest)
        self.assertNotIn("fn t()", rest)
        self.assertNotIn("#[cfg(test)]", rest)

    def test_O13_two_modules_returned_in_order(self):
        text = ("#[cfg(test)]\nmod first_mod {\n    fn a() {}\n}\n\nfn mid() {}\n\n"
                "#[cfg(test)]\nmod second_mod {\n    fn b() {}\n}\n")
        rest, mods = languages.split_rust_inline(text)
        self.assertEqual(len(mods), 2)
        self.assertIn("first_mod", mods[0])
        self.assertIn("second_mod", mods[1])
        self.assertIn("fn mid()", rest)

    def test_O13_C13_nested_module_moves_with_outer_only_and_cfg_fn_stays(self):
        text = ("pub fn run() {}\n\n#[cfg(test)]\nmod outer {\n    mod tests {\n        fn inner_marker() {}\n"
                "    }\n}\n\n#[cfg(test)]\nfn helper_only_in_tests() {}\n")
        rest, mods = languages.split_rust_inline(text)
        self.assertEqual(len(mods), 1)
        self.assertIn("mod outer", mods[0])
        self.assertIn("mod tests", mods[0])
        self.assertIn("inner_marker", mods[0])
        self.assertNotIn("helper_only_in_tests", mods[0])
        self.assertIn("helper_only_in_tests", rest)
        self.assertIn("pub fn run", rest)
        self.assertNotIn("mod outer", rest)
        self.assertNotIn("inner_marker", rest)

    def test_O13_string_containing_cfg_test_is_not_a_module(self):
        text = "pub fn f() -> &'static str {\n    \"#[cfg(test)]\"\n}\n"
        rest, mods = languages.split_rust_inline(text)
        self.assertEqual(mods, [])
        self.assertIn("#[cfg(test)]", rest)
        self.assertIn("pub fn f", rest)

    def test_O13_no_module_returns_text_unchanged(self):
        text = "pub fn f() {}\n"
        rest, mods = languages.split_rust_inline(text)
        self.assertEqual((rest, mods), (text, []))


class ChangedLines(unittest.TestCase):
    def test_O13_modified_and_added_lines_use_new_numbers(self):
        diff = udiff("src/a.py", "a\nb\nc\nd\ne\n", "a\nb\nC\nd\nX\ne\n")
        self.assertEqual(languages.changed_lines(diff), {"src/a.py": {3, 5}})

    def test_O13_new_file_marks_every_line(self):
        diff = udiff("src/n.py", None, "1\n2\n3\n")
        self.assertEqual(languages.changed_lines(diff), {"src/n.py": {1, 2, 3}})

    def test_O13_deletion_only_marks_nothing_and_two_paths_kept_apart(self):
        diff = udiff("src/a.py", "a\nb\nc\n", "a\nc\n") + udiff("src/b.py", "x\n", "y\n")
        got = languages.changed_lines(diff)
        self.assertEqual(got.get("src/a.py", set()), set())
        self.assertEqual(got["src/b.py"], {1})


if __name__ == "__main__":
    unittest.main()

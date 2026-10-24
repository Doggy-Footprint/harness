import re
import threading
import unittest

from evaluation.pr_test_quality import languages
from evaluation.pr_test_quality.tests.fakes import diff_files, udiff

HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


def check_valid_unified(test, diff):
    """Every hunk header is well formed and its line counts match the hunk body."""
    lines = diff.split("\n")
    i = 0
    while i < len(lines):
        m = HUNK.match(lines[i])
        if lines[i].startswith("@@"):
            test.assertIsNotNone(m, "malformed hunk header %r" % lines[i])
            old = int(m.group(2)) if m.group(2) is not None else 1
            new = int(m.group(4)) if m.group(4) is not None else 1
            j, o, n = i + 1, 0, 0
            while j < len(lines) and not lines[j].startswith(("@@", "diff --git")):
                if lines[j].startswith("-"):
                    o += 1
                elif lines[j].startswith("+"):
                    n += 1
                elif lines[j].startswith(" "):
                    o += 1
                    n += 1
                j += 1
            test.assertEqual((o, n), (old, new), "hunk %r counts %r" % (lines[i], (o, n)))
            i = j
        else:
            i += 1


def timed(fn, seconds=5):
    box = {}
    thread = threading.Thread(target=lambda: box.setdefault("v", fn()), daemon=True)
    thread.start()
    thread.join(seconds)
    return box.get("v", "timeout")


class SplitRustInlineEdges(unittest.TestCase):
    def test_O13_G13_source_without_any_attribute_returns_promptly_with_no_modules(self):
        text = "fn a() { let x = 1; }\n" * 30000
        out = timed(lambda: languages.split_rust_inline(text))
        self.assertNotEqual(out, "timeout")
        self.assertEqual(out, (text, []))

    def test_O13_G13_many_bare_hash_and_brace_characters_stay_linear(self):
        text = "#[derive(Debug)]\nstruct S;\n" * 20000
        out = timed(lambda: languages.split_rust_inline(text))
        self.assertNotEqual(out, "timeout")
        self.assertEqual(out[1], [])

    def test_O13_G14_unterminated_module_does_not_hide_a_later_complete_one(self):
        rest, mods = languages.split_rust_inline("#[cfg(test)]\nmod a {\nfn x(){}\n#[cfg(test)]\nmod b {}\nfn z(){}")
        self.assertEqual(mods, ["#[cfg(test)]\nmod b {}"])
        self.assertIn("fn z()", rest)
        self.assertIn("mod a {", rest)

    def test_O13_G15_block_comment_directly_before_the_attribute(self):
        rest, mods = languages.split_rust_inline("fn a(){} /*a*/#[cfg(test)]\nmod t {}\n")
        self.assertEqual(mods, ["#[cfg(test)]\nmod t {}"])
        self.assertIn("fn a()", rest)

    def test_O13_G15_line_comment_and_attribute_on_same_line_start(self):
        rest, mods = languages.split_rust_inline("fn a(){}\n// note\n#[cfg(test)]\nmod t {}\n")
        self.assertEqual(len(mods), 1)

    def test_O13_G16_raw_string_with_a_backslash_does_not_hide_a_following_module(self):
        for literal in ('r"\\"', 'r#"\\"#', 'r"a\\"'):
            text = "const R: &str = %s;\n#[cfg(test)]\nmod t {}\n" % literal
            rest, mods = languages.split_rust_inline(text)
            with self.subTest(literal=literal):
                self.assertEqual(mods, ["#[cfg(test)]\nmod t {}"])
                self.assertIn("const R", rest)

    def test_O13_G16_braces_inside_strings_and_chars_do_not_end_a_module_early(self):
        text = '#[cfg(test)]\nmod t {\n    fn f() { let s = "}"; let c = \'}\'; }\n}\nfn after() {}\n'
        rest, mods = languages.split_rust_inline(text)
        self.assertEqual(len(mods), 1)
        self.assertIn("let c", mods[0])
        self.assertEqual(rest.strip(), "fn after() {}")


class SplitDiffEdges(unittest.TestCase):
    def test_O13_G17_hunk_in_a_test_module_with_removed_brace_lines_is_classified_tests(self):
        diff = ("diff --git a/src/lib.rs b/src/lib.rs\n--- a/src/lib.rs\n+++ b/src/lib.rs\n@@ -1,6 +1,5 @@\n"
                " pub fn a() {}\n #[cfg(test)]\n mod tests {\n-    if x {\n-        y\n-    }\n     fn t() {}\n+    fn u() {}\n }\n")
        parts = languages.split_diff("rust", diff)
        self.assertEqual(diff_files(parts["src"]), [])
        self.assertEqual(diff_files(parts["tests"]), ["src/lib.rs#cfgtest"])
        self.assertIn("-    if x {", parts["tests"])
        self.assertNotIn("fn u()", parts["src"])

    def test_O13_G17_change_outside_the_module_in_the_same_file_stays_in_src(self):
        diff = udiff("src/lib.rs", "pub fn a() {}\n#[cfg(test)]\nmod tests {\n    fn t() {\n        if x {\n        }\n    }\n}\n",
                     "pub fn a() { 1 }\n#[cfg(test)]\nmod tests {\n    fn t() {\n    }\n}\n")
        parts = languages.split_diff("rust", diff)
        self.assertIn("pub fn a() { 1 }", parts["src"])
        self.assertNotIn("if x", parts["src"])
        self.assertIn("if x", parts["tests"])

    def test_O13_G18_c_quoted_path_decodes_tab_and_octal_escapes(self):
        diff = ('diff --git "a/a\\tb.py" "b/a\\tb.py"\n--- "a/a\\tb.py"\n+++ "b/a\\tb.py"\n@@ -1 +1 @@\n-x\n+y\n'
                'diff --git "a/\\303\\251.py" "b/\\303\\251.py"\n--- "a/\\303\\251.py"\n+++ "b/\\303\\251.py"\n'
                '@@ -1 +1 @@\n-x\n+y\n')
        changed = languages.changed_lines(diff)
        self.assertEqual(set(changed), {"a\tb.py", "é.py"})
        parts = languages.split_diff("python", diff)
        total = sum(p.count("diff --git") for p in parts.values())
        self.assertEqual(total, 2)
        self.assertEqual(parts["src"].count("diff --git"), 2)

    def test_O13_G18_rename_header_keeps_the_file_in_exactly_one_part(self):
        diff = ("diff --git a/old.py b/new.py\nsimilarity index 90%\nrename from old.py\nrename to new.py\n"
                "--- a/old.py\n+++ b/new.py\n@@ -1 +1 @@\n-x\n+y\n")
        parts = languages.split_diff("python", diff)
        holders = [k for k, v in parts.items() if "rename to new.py" in v]
        self.assertEqual(holders, ["src"])
        self.assertEqual(sum(v.count("diff --git") for v in parts.values()), 1)
        self.assertEqual(languages.changed_lines(diff), {"new.py": {1}})

    def test_O13_G18_rename_from_a_src_path_to_a_test_path_lands_once(self):
        diff = ("diff --git a/pkg/old.py b/tests/test_new.py\nsimilarity index 90%\nrename from pkg/old.py\n"
                "rename to tests/test_new.py\n--- a/pkg/old.py\n+++ b/tests/test_new.py\n@@ -1 +1 @@\n-x\n+y\n")
        parts = languages.split_diff("python", diff)
        self.assertEqual(sum(v.count("diff --git") for v in parts.values()), 1)
        self.assertEqual(parts["tests"].count("diff --git"), 1)

    def test_O13_G19_new_test_file_keeps_dev_null_header_in_the_tests_part(self):
        parts = languages.split_diff("python", udiff("tests/test_new.py", None, "def test_a(): pass\n"))
        self.assertIn("--- /dev/null", parts["tests"])
        self.assertIn("new file mode", parts["tests"])
        self.assertNotIn("--- a/tests/test_new.py", parts["tests"])

    def test_O13_G19_new_rust_file_with_a_module_keeps_dev_null_in_both_parts(self):
        diff = udiff("src/lib.rs", None, "pub fn a() {}\n#[cfg(test)]\nmod tests {\n    fn t() {}\n}\n")
        parts = languages.split_diff("rust", diff)
        for key in ("src", "tests"):
            with self.subTest(part=key):
                self.assertIn("--- /dev/null", parts[key])
                self.assertIn("new file mode", parts[key])

    def test_O13_G19_deleted_file_keeps_dev_null_on_the_new_side(self):
        parts = languages.split_diff("python", udiff("tests/test_old.py", "def test_a(): pass\n", None))
        self.assertIn("+++ /dev/null", parts["tests"])
        self.assertIn("deleted file mode", parts["tests"])

    def test_O13_each_part_is_a_valid_unified_diff_for_new_and_modified_files(self):
        cases = {
            "python": udiff("src/a.py", None, "x = 1\ny = 2\n") + udiff("tests/test_a.py", "a\nb\n", "a\nc\n"),
            "rust": udiff("src/lib.rs", None, "pub fn a() {}\n#[cfg(test)]\nmod tests {\n    fn t() {}\n}\n"),
            "rust2": udiff("src/lib.rs", "pub fn a() {}\n#[cfg(test)]\nmod tests {\n    fn t() {}\n}\n",
                           "pub fn a() { 1 }\n#[cfg(test)]\nmod tests {\n    fn t() {}\n    fn u() {}\n}\n"),
        }
        for name, diff in cases.items():
            parts = languages.split_diff("rust" if name.startswith("rust") else "python", diff)
            for key, part in parts.items():
                with self.subTest(case=name, part=key):
                    check_valid_unified(self, part)

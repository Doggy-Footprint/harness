import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tests.test_comment_gate import AGENT_SENTENCE, RepoTestCase, git

STAGED_ENTRY = re.compile(r"^([^:\s]+):(\d+): ?(.*)$")
WARNING_ENTRY = re.compile(r"::warning file=([^,]+),line=(\d+)")


def lines(*rows):
    return "".join(r + "\n" for r in rows)


class DetectionCase(RepoTestCase):
    def write(self, repo, name, data):
        path = repo / name
        if data is None:
            git(repo, "rm", "-q", "-f", name)
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data if isinstance(data, bytes) else data.encode())

    def seed(self, base):
        repo = self.make_repo()
        (repo / "keep.md").write_text("keep\n")
        for name, data in base.items():
            self.write(repo, name, data)
        git(repo, "add", "-A")
        git(repo, "commit", "-q", "-m", "base")
        return repo

    def staged_report(self, base, new):
        repo = self.seed(base)
        for name, data in new.items():
            self.write(repo, name, data)
        git(repo, "add", "-A")
        r = self.run_warn(repo, "--staged")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertNotIn("Traceback", r.stderr)
        entries = [STAGED_ENTRY.match(l) for l in r.stderr.splitlines()]
        entries = [m for m in entries if m]
        return {(m.group(1), int(m.group(2))) for m in entries}, entries, r

    def sha_report(self, base, new, approved="no"):
        repo = self.seed(base)
        b = git(repo, "rev-parse", "HEAD").stdout.strip()
        for name, data in new.items():
            self.write(repo, name, data)
        git(repo, "add", "-A")
        git(repo, "commit", "-q", "--allow-empty", "-m", "head")
        h = git(repo, "rev-parse", "HEAD").stdout.strip()
        r = self.run_warn(repo, b, h, "--approved", approved)
        self.assertNotIn("Traceback", r.stderr + r.stdout)
        self.last_raw = [(m.group(1), int(m.group(2))) for m in WARNING_ENTRY.finditer(r.stdout)]
        return set(self.last_raw), r

    def check(self, base, new, expected):
        expected = set(expected)
        got, _, _ = self.staged_report(base, new)
        self.assertEqual(got, expected, "staged mode")
        got, r = self.sha_report(base, new, "no")
        self.assertEqual(got, expected, "two-SHA mode")
        self.assertEqual(r.returncode, 1 if expected else 0, r.stdout + r.stderr)
        for path in {p for p, _ in expected}:
            self.assertIn(f"- `{path}`:", r.stdout)
        for path in set(new) - {p for p, _ in expected}:
            self.assertNotIn(f"- `{path}`:", r.stdout)
        if not expected:
            self.assertNotIn("::warning", r.stdout)

    def only(self, name, text, *line_numbers, base=None):
        self.check(base or {}, {name: text}, {(name, n) for n in line_numbers})


class R1ShebangTests(DetectionCase):
    def test_line1_shebang_not_reported_in_py_sh_js(self):
        for name, text in (
            ("s.py", lines("#!/usr/bin/env python3", "x = 1")),
            ("s.sh", lines("#!/bin/sh", "echo hi")),
            ("s.js", lines("#!/usr/bin/env node", "let x = 1;")),
        ):
            with self.subTest(name=name):
                self.only(name, text)

    def test_shebang_only_file(self):
        for name in ("s.py", "s.sh", "s.js"):
            with self.subTest(name=name):
                self.only(name, "#!/usr/bin/env x\n")

    def test_comment_after_shebang_still_reported(self):
        for name, text in (
            ("s.py", lines("#!/usr/bin/env python3", "# c", "x = 1")),
            ("s.sh", lines("#!/bin/sh", "echo hi", "# c")),
            ("s.js", lines("#!/usr/bin/env node", "// c", "let x = 1;")),
        ):
            with self.subTest(name=name):
                self.only(name, text, 2 if name != "s.sh" else 3)

    def test_shebang_not_on_line_one_is_reported(self):
        for name, text in (
            ("s.sh", lines("echo hi", "#!/bin/sh")),
            ("s.py", lines("x = 1", "#!/usr/bin/env python3")),
            ("s.js", lines("let x = 1;", "#!/usr/bin/env node")),
        ):
            with self.subTest(name=name):
                self.only(name, text, 2)

    def test_hash_bang_with_space_on_line_one_is_a_comment(self):
        for name in ("s.sh", "s.py"):
            with self.subTest(name=name):
                self.only(name, lines("# !/bin/sh", "x=1"), 1)

    def test_shebang_added_to_existing_file(self):
        for name in ("s.py", "s.sh"):
            with self.subTest(name=name):
                self.check({name: "x=1\n"}, {name: lines("#!/usr/bin/env x", "x=1")}, set())

    def test_unchanged_shebang_and_comment_not_reported_when_other_line_added(self):
        base = {"s.py": lines("#!/usr/bin/env python3", "# old", "x = 1")}
        self.check(base, {"s.py": lines("#!/usr/bin/env python3", "# old", "x = 1", "y = 2")}, set())

    def test_shebang_kept_when_py_file_does_not_tokenize(self):
        self.only("s.py", lines("#!/usr/bin/env python3", "x = '''", "# c"), 3)

    def test_shebang_in_two_files_with_normal_comment_elsewhere(self):
        self.check(
            {},
            {"a.sh": lines("#!/bin/sh", "echo"), "b.py": lines("#!/usr/bin/env python3", "x = 1  # t")},
            {("b.py", 2)},
        )


class R2PythonTests(DetectionCase):
    def test_comment_line_reported(self):
        self.only("a.py", lines("x = 1", "# note", "y = 2", "    # indented"), 2, 4)

    def test_trailing_comment_reported(self):
        self.only("a.py", lines("x = 1", "y = 2  # trailing", "z = 3"), 2)

    def test_trailing_comment_content_printed_in_staged_output(self):
        _, entries, r = self.staged_report({}, {"a.py": lines("x = 1", "y = 2  # trailing")})
        self.assertEqual([(m.group(1), int(m.group(2))) for m in entries], [("a.py", 2)])
        self.assertIn("y = 2  # trailing", entries[0].group(3))
        self.assertIn(AGENT_SENTENCE, r.stderr)

    def test_hash_inside_string_with_code_not_reported(self):
        self.only("a.py", lines("s = 'a # b'", "t = \"# c\"", "u = '''x # y'''"))

    def test_comment_inside_bracket_continuation(self):
        self.only("a.py", lines("x = (1,", "     # note", "     2)"), 2)

    def test_unchanged_comments_not_reported(self):
        base = {"a.py": lines("# old", "x = 1  # old2", "def f():", '    """old doc"""')}
        new = {"a.py": lines("# old", "x = 1  # old2", "def f():", '    """old doc"""', "    return 1")}
        self.check(base, new, set())

    def test_module_docstring_single_line(self):
        self.only("a.py", lines('"""Doc."""', "x = 1"), 1)

    def test_single_quote_triple_docstring(self):
        self.only("a.py", lines("def f():", "    '''Doc.'''", "    return 1"), 2)

    def test_multiline_docstring_every_line_reported(self):
        text = lines("def f():", '    """Summary', "", "    more", '    """', "    return 1")
        self.only("a.py", text, 2, 3, 4, 5)

    def test_class_and_method_docstrings(self):
        text = lines("class C:", '    """Class doc."""', "", "    def m(self):", '        """Method', '        doc."""', "        return 1")
        self.only("a.py", text, 2, 5, 6)

    def test_bare_string_statement_is_docstring(self):
        self.only("a.py", lines("x = 1", '"bare"', "y = 2"), 2)

    def test_bare_multiline_string_mid_file(self):
        self.only("a.py", lines("x = 1", '"""', "text", '"""', "y = 2"), 2, 3, 4)

    def test_docstring_partly_added_reports_only_added_lines(self):
        base = {"a.py": lines("def f():", '    """Summary', "    old", '    """', "    return 1")}
        new = {"a.py": lines("def f():", '    """Summary', "    old", "    new", '    """', "    return 1")}
        self.check(base, new, {("a.py", 4)})

    def test_docstring_unchanged_code_added_after_it(self):
        base = {"a.py": lines("def f():", '    """Summary', "    old", '    """')}
        new = {"a.py": lines("def f():", '    """Summary', "    old", '    """', "    return 1")}
        self.check(base, new, set())

    def test_docstring_expanded_from_single_to_multiline(self):
        base = {"a.py": lines("def f():", '    """Summary."""', "    return 1")}
        new = {"a.py": lines("def f():", '    """Summary.', "    more.", '    """', "    return 1")}
        self.check(base, new, {("a.py", 2), ("a.py", 3), ("a.py", 4)})

    def test_assigned_string_with_markdown_headings_not_reported(self):
        self.only("a.py", lines('TEXT = """', "# Title", "## Section", "body", '"""'))

    def test_assigned_fstring_with_headings_not_reported(self):
        self.only("a.py", lines("x = 1", 'msg = f"""', "# Title {x}", "## Section", '"""'))

    def test_plain_string_lines_starting_with_other_markers_not_reported(self):
        self.only("a.py", lines('x = """', "// not a comment", "/* nor this */", "'''", '"""'))

    def test_string_containing_triple_double_quote_lookalike(self):
        self.only("a.py", lines("x = '''", '"""', "# h", '"""', "'''"))

    def test_string_containing_triple_single_quote_lookalike(self):
        self.only("a.py", lines('x = """', "'''", "# h", "'''", '"""'))

    def test_string_passed_as_argument_or_returned(self):
        text = lines("print('''", "# h", "''')", "def f():", "    return '''", "# r", "'''")
        self.only("a.py", text)

    def test_string_concatenated_in_expression_not_reported(self):
        text = lines("x = ('one'", '     """', "# h", '""" "tail")')
        self.only("a.py", text)

    def test_string_with_operator_or_call_is_not_a_docstring(self):
        text = lines('"""', "# h", '""" + y', '"""', "## g", '""".strip()')
        self.only("a.py", text)

    def test_real_comment_after_string_statement_reported_but_string_body_not(self):
        text = lines("x = '''", "# in string", "'''  # real", "y = 1")
        self.only("a.py", text, 3)

    def test_added_comment_between_unchanged_string_lines_only_its_own_line(self):
        base = {"a.py": lines("x = '''", "# h", "'''", "y = 1")}
        new = {"a.py": lines("x = '''", "# h", "'''", "# new", "y = 1")}
        self.check(base, new, {("a.py", 4)})

    def test_nested_path(self):
        self.only("pkg/sub/mod.py", lines("x = 1  # t"), 1)


class R2DirectiveTests(DetectionCase):
    def test_trailing_and_line_start_directives_not_reported(self):
        for comment in (
            "# noqa", "# noqa: E402", "# noqa E402", "#noqa", "#   noqa:E402", "# noqa\t",
            "# type: ignore", "# type: ignore[attr]", "# pragma: no cover", "# pylint: disable=x",
            "# mypy: ignore-errors", "# pyright: basic", "# fmt: off", "# isort: skip",
        ):
            with self.subTest(comment=comment):
                self.only("a.py", lines("import config  " + comment, comment, "x = 1"))

    def test_non_directives_reported(self):
        for comment in (
            "# noqa-ish note", "# noqax", "# note: type: ignore", "# NOQA", "# Type: ignore",
            "# see noqa: E402", "# types: x", "# typed: x", "# pragmatic: x", "# fmt x", "# isort x",
        ):
            with self.subTest(comment=comment):
                self.only("a.py", lines("x = 1  " + comment, comment, "y = 1"), 1, 2)

    def test_directive_then_ordinary_comment_text_still_directive(self):
        self.only("a.py", lines("x = f()  # type: ignore  because reasons"))

    def test_directive_inside_docstring_still_reported(self):
        self.only("a.py", lines("def f():", '    """Doc', "    # noqa: E402", "    # type: ignore", '    """'), 2, 3, 4, 5)

    def test_directive_inside_assigned_string_not_reported(self):
        self.only("a.py", lines("x = '''", "# noqa: E402", "'''"))

    def test_directive_marker_inside_string_not_a_comment_token(self):
        self.only("a.py", lines("x = '# noqa'  # real note"), 1)

    def test_directive_not_excused_in_js_or_sh(self):
        self.only("a.sh", lines("# noqa: E402", "# type: ignore", "echo # noqa"), 1, 2)
        self.only("a.js", lines("// noqa: E402", "let x = 1; // noqa"), 1)

    def test_directive_in_fallback_file_follows_line_start_pattern(self):
        self.only("a.py", lines("x = '''", "# type: ignore", "y = 1  # noqa"), 2)


class R3FallbackTests(DetectionCase):
    def test_unterminated_triple_quote_falls_back_to_line_start(self):
        self.only("a.py", lines("x = '''", "# h", "y = 1  # trailing not matched", "// slash"), 2, 4)

    def test_indentation_error_falls_back_to_line_start(self):
        text = lines("if x:", "        a = 1", "    b = 2", "# c", "d = 1  # t")
        self.only("a.py", text, 4)

    def test_fallback_reports_string_content_lines_starting_with_marker(self):
        self.only("a.py", lines("x = '''", '"""', "'''", "'''"), 2, 3, 4)

    def test_tokenizable_file_with_syntax_errors_still_uses_token_rules(self):
        self.only("a.py", lines("class:", "    x = '''", "# h", "'''"))

    def test_fallback_applies_per_file(self):
        self.check(
            {},
            {"bad.py": lines("x = '''", "# h"), "good.py": lines("y = '''", "# h", "'''", "z = 1  # t")},
            {("bad.py", 2), ("good.py", 4)},
        )


class R4NonPythonTests(DetectionCase):
    def test_js_line_start_pattern(self):
        text = lines("// c", "let x = 1; // trailing", "  /* b */", "let s = `", "# h", "`;", "'''", '"""', "let y = 2;")
        self.only("a.js", text, 1, 3, 5, 7, 8)

    def test_sh_line_start_pattern(self):
        text = lines("#!/bin/sh", "# c", "echo hi # trailing", "  # indented", "echo done")
        self.only("a.sh", text, 2, 4)

    def test_js_modified_file_only_added_lines(self):
        base = {"a.js": lines("// old", "let x = 1;")}
        new = {"a.js": lines("// old", "let x = 1;", "// new")}
        self.check(base, new, {("a.js", 3)})

    def test_deep_indentation_reported_in_js_sh(self):
        for name, c in (("a.js", "// note"), ("a.js", "/* note */"), ("a.sh", "# note")):
            for indent in ("  ", "    ", "\t", "\t\t", " \t ", "        "):
                with self.subTest(name=name, c=c, indent=repr(indent)):
                    self.only(name, lines("x", indent + c, "y"), 2)

    def test_deep_indentation_markers_quotes_in_js(self):
        self.only("a.js", lines("a", "    '''", "\t\"\"\"", "b"), 2, 3)

    def test_deep_indented_shebang_lookalike_not_line_one_reported(self):
        self.only("a.sh", lines("#!/bin/sh", "    #!/bin/sh"), 2)

    def test_deep_indentation_in_fallback_file(self):
        self.only("a.py", lines("x = '''", "    # two", "\t// tab", "\t\t\"\"\" x"), 2, 3, 4)

    def test_python_js_modified_file_indented_added_only(self):
        base = {"a.js": lines("function f() {", "    // old", "}")}
        new = {"a.js": lines("function f() {", "    // old", "    // new", "}")}
        self.check(base, new, {("a.js", 3)})

    def test_python_rules_not_applied_to_js(self):
        self.only("a.js", lines("let a = '''", "# h", "'''"), 2, 3)


class R5Tests(DetectionCase):
    def test_non_code_extension_never_reported(self):
        self.only("notes.md", lines("#!/bin/sh", "# Title", "// x"))

    def test_deleted_file_not_reported(self):
        base = {"a.py": lines("# old", "x = 1"), "b.js": "// old\n"}
        self.check(base, {"a.py": None, "b.js": None}, set())

    def test_deleted_file_does_not_hide_other_reports(self):
        base = {"a.py": lines("# old", "x = 1")}
        self.check(base, {"a.py": None, "n.py": lines("y = 1  # t")}, {("n.py", 1)})

    def test_non_utf8_python_content_does_not_crash_and_uses_token_rules(self):
        data = b"# c\nx = '\xff\xfe'\ny = 1  # t\n"
        self.only("a.py", data, 1, 3)

    def test_exit_code_unapproved_with_real_comment(self):
        got, r = self.sha_report({}, {"a.py": "# c\n"}, "no")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertEqual(got, {("a.py", 1)})
        self.assertEqual(len([l for l in r.stdout.splitlines() if l.startswith("::error")]), 1)
        self.assertIn("`comments-approved` label", r.stdout)

    def test_exit_code_approved_with_real_comment(self):
        got, r = self.sha_report({}, {"a.py": "# c\n"}, "yes")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(got, {("a.py", 1)})
        self.assertNotIn("::error", r.stdout)

    def test_false_positive_free_change_passes_unapproved_without_output(self):
        files = {"s.py": lines("#!/usr/bin/env python3", 'T = """', "# Title", '"""')}
        got, r = self.sha_report({}, files, "no")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(got, set())
        self.assertNotIn("::warning", r.stdout)
        self.assertNotIn("::error", r.stdout)
        got, _, r = self.staged_report({}, files)
        self.assertEqual(got, set())
        self.assertEqual(r.stderr, "")

    def test_staged_agent_sentence_present_only_when_reported(self):
        _, _, r = self.staged_report({}, {"a.py": "x = 1  # t\n"})
        self.assertIn(AGENT_SENTENCE, r.stderr)
        _, _, r = self.staged_report({}, {"a.py": "#!/usr/bin/env python3\n"})
        self.assertNotIn(AGENT_SENTENCE, r.stderr)

    def test_unstaged_changes_not_reported_and_index_content_used(self):
        repo = self.seed({"a.py": "x = 1\n"})
        (repo / "a.py").write_text(lines("x = 1", "T = '''", "# h", "'''"))
        git(repo, "add", "a.py")
        (repo / "a.py").write_text(lines("x = 1", "# worktree only"))
        r = self.run_warn(repo, "--staged")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stderr, "")

    def test_two_sha_uses_head_content_not_worktree(self):
        repo = self.seed({"a.py": "x = 1\n"})
        b = git(repo, "rev-parse", "HEAD").stdout.strip()
        self.write(repo, "a.py", lines("x = 1", "T = '''", "# h", "'''"))
        git(repo, "commit", "-q", "-am", "h")
        h = git(repo, "rev-parse", "HEAD").stdout.strip()
        (repo / "a.py").write_text(lines("x = 1", "# worktree only"))
        r = self.run_warn(repo, b, h, "--approved", "no")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertNotIn("::warning", r.stdout)


class AuditGapTests(DetectionCase):
    # Gitlink named *.py. Observed: git diff shows one added line
    # "+Subproject commit <sha>" while `git show <rev>:sub.py` fails (exit 128).
    GITLINK = "160000,1111111111111111111111111111111111111111,sub.py"

    def test_gitlink_py_staged_does_not_crash_and_other_file_reported(self):
        repo = self.seed({})
        git(repo, "update-index", "--add", "--cacheinfo", self.GITLINK)
        (repo / "other.py").write_text("x = 1  # real\n")
        git(repo, "add", "other.py")
        r = self.run_warn(repo, "--staged")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn("Traceback", r.stderr)
        got = {(m.group(1), int(m.group(2))) for m in map(STAGED_ENTRY.match, r.stderr.splitlines()) if m}
        self.assertEqual(got, {("other.py", 1)})

    def test_gitlink_py_two_sha_does_not_crash_and_other_file_reported(self):
        repo = self.seed({})
        b = git(repo, "rev-parse", "HEAD").stdout.strip()
        git(repo, "update-index", "--add", "--cacheinfo", self.GITLINK)
        (repo / "other.py").write_text("x = 1  # real\n")
        git(repo, "add", "other.py")
        git(repo, "commit", "-q", "-m", "h")
        h = git(repo, "rev-parse", "HEAD").stdout.strip()
        r = self.run_warn(repo, b, h, "--approved", "no")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertNotIn("Traceback", r.stdout + r.stderr)
        got = {(m.group(1), int(m.group(2))) for m in WARNING_ENTRY.finditer(r.stdout)}
        self.assertEqual(got, {("other.py", 1)})

    def test_docstring_after_shebang_comment_and_blank_line(self):
        text = lines("#!/usr/bin/env python3", "# comment", "", '"""Doc', 'more"""', "x = 1")
        self.only("a.py", text, 2, 4, 5)

    def test_docstring_after_dedent(self):
        self.only("a.py", lines("def f():", "    return 1", '"""bare', 'doc"""', "y = 1"), 3, 4)

    def test_docstring_after_nested_dedent(self):
        text = lines("class C:", "    def m(self):", "        return 1", "", "'''bare", "doc'''", "z = 1")
        self.only("a.py", text, 5, 6)

    def test_docstring_closing_line_with_trailing_comment(self):
        self.only("a.py", lines('"""a', 'b"""  # c', "x = 1"), 1, 2)

    def test_single_line_docstring_with_noqa_trailing_comment(self):
        self.only("a.py", lines('"""doc"""  # noqa: E402', "x = 1"), 1)

    def test_prefixed_docstrings(self):
        for prefix, quote in (("r", '"""'), ("u", '"""'), ("b", '"""'), ("rb", "'''"), ("R", '"""'), ("Rb", "'''")):
            with self.subTest(prefix=prefix, quote=quote):
                self.only("a.py", lines("x = 1", prefix + quote + "a", "b" + quote, "y = 1"), 2, 3)

    def test_more_extensions_r1_and_line_start(self):
        for ext, marker in ((".go", "//"), (".rs", "//"), (".ts", "//"), (".rb", "#"), (".yml", "#")):
            with self.subTest(ext=ext):
                self.only("f" + ext, lines("#!/usr/bin/env x", marker + " c", "    " + marker + " d", "k: 1 " + marker + " t"), 2, 3)
                self.only("g" + ext, lines("k: 1", "#!/usr/bin/env x"), 2)

    def test_non_utf8_bytes_inside_comment_lines(self):
        self.only("a.py", b"x = 1\n# caf\xe9 \xff\ny = 2  # t\xe9\n", 2, 3)
        self.only("a.js", b"let x = 1;\n// caf\xe9 \xff\n", 2)

    def test_no_duplicate_entries(self):
        text = lines('"""Doc', "# inside docstring", 'more"""  # trailing', "x = 1  # t", "# c", "def f():", '    """d"""  # n')
        want = sorted({("a.py", n) for n in (1, 2, 3, 4, 5, 7)})
        _, entries, _ = self.staged_report({}, {"a.py": text})
        self.assertEqual(sorted((m.group(1), int(m.group(2))) for m in entries), want, "staged raw entries")
        self.sha_report({}, {"a.py": text})
        self.assertEqual(sorted(self.last_raw), want, "two-SHA raw entries")

    def test_unclosed_paren_at_eof_falls_back(self):
        self.only("a.py", lines("y = foo(  # t", "# c"), 2)
        self.only("b.py", lines("x = (1,", "# c"), 2)

    def test_no_trailing_newline(self):
        self.only("a.py", "x = 1\n# c", 2)
        self.only("b.py", "x = 1  # t", 1)
        self.only("c.py", '"""d"""', 1)
        self.only("e.js", "let x;\n// c", 2)

    def test_crlf_python(self):
        self.only("a.py", b"x = 1  # t\r\n\"\"\"Doc\r\nmore\"\"\"\r\ny = '''\r\n# h\r\n'''\r\nz = 2\r\n", 1, 2, 3)

    def test_crlf_python_fallback(self):
        self.only("a.py", b"x = '''\r\n# h\r\n", 2)


if __name__ == "__main__":
    unittest.main()

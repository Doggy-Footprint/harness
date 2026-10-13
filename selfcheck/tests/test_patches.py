import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from selfcheck import patches
from selfcheck.tests import diffs
from selfcheck.tests.helpers import verified_paths

FRAMEWORK_DIRS = [
    ("django/django", "django/test/utils.py", "test"),
    ("django/django", "django/test/sub/deep/helpers.py", "test"),
    ("sympy/sympy", "sympy/testing/x.py", "test"),
    ("sphinx-doc/sphinx", "sphinx/testing/util.py", "test"),
    ("pytest-dev/pytest", "src/_pytest/python.py", "src"),
    ("pydata/xarray", "xarray/testing.py", "src"),
]
EXCLUDED_PATHS = [
    ".harness/x",
    ".harness/a/b/c.md",
    ".claude/settings.json",
    ".claude/agents/deep/x.md",
    ".agents/skills/x",
    ".agents/a/b/x",
    ".codex/config.toml",
    ".codex/a/b/x",
    "agent-docs/adr/index.md",
    "agent-docs/specs/deep/x.md",
    "AGENTS.md",
    "CLAUDE.md",
    ".githooks/pre-commit",
    ".githooks/a/b",
    ".github/workflows/harness-comment-warning.yml",
    ".gitignore",
    "mutants/pkg/mod.py",
    "mutants/x.py",
    ".mutmut-cache",
    ".hypothesis/examples/ab/cd",
    ".hypothesis/x",
    ".coverage",
    ".coverage.host.123",
    "htmlcov/index.html",
    "htmlcov/a/b.js",
    "foo.py.orig",
    "pkg/sub/foo.py.orig",
    "foo.py.rej",
    "pkg/sub/foo.py.rej",
    "pkg/__pycache__/m.cpython-312.pyc",
    "a/b/__pycache__/deep/x.py",
    "x.pyc",
    "pkg/sub/x.pyc",
]


class ClassifyPathTests(unittest.TestCase):
    def test_vo1_p1_corpus_patch_files_are_src(self):
        rows = verified_paths()
        self.assertEqual(len(rows), 500)
        checked = 0
        for row in rows:
            for path in row["patch_files"]:
                with self.subTest(instance=row["instance_id"], path=path):
                    self.assertEqual(patches.classify_path(path, row["repo"]), "src")
                checked += 1
        self.assertGreaterEqual(checked, 500)

    def test_vo1_p2_corpus_test_files_are_test(self):
        checked = 0
        for row in verified_paths():
            for path in row["test_patch_files"]:
                with self.subTest(instance=row["instance_id"], path=path):
                    self.assertEqual(patches.classify_path(path, row["repo"]), "test")
                checked += 1
        self.assertGreaterEqual(checked, 500)

    def test_vo1_p3_framework_dirs_follow_the_dataset_convention(self):
        for repo, path, expected in FRAMEWORK_DIRS:
            for is_new in (False, True):
                with self.subTest(repo=repo, path=path, is_new=is_new):
                    self.assertEqual(patches.classify_path(path, repo, is_new=is_new), expected)

    def test_vo1_p3_rules_do_not_depend_on_the_repo(self):
        for _, path, expected in FRAMEWORK_DIRS:
            with self.subTest(path=path):
                self.assertEqual(patches.classify_path(path, "other/repo"), expected)

    def test_vo1_p8_regex_anchors_do_not_match_inside_words(self):
        for path in ("contest.py", "latest/x.py", "attestation.py"):
            with self.subTest(path=path):
                self.assertEqual(patches.classify_path(path, "django/django"), "src")

    def test_vo1_p4_each_excluded_pattern_is_excluded(self):
        for path in EXCLUDED_PATHS:
            for repo in ("django/django", "pytest-dev/pytest"):
                with self.subTest(path=path, repo=repo):
                    self.assertEqual(patches.classify_path(path, repo), "excluded")

    def test_vo1_p4_excluded_wins_over_scratch(self):
        for path in (".gitignore", "foo.py.orig", "x.pyc", "AGENTS.md", ".coverage", ".mutmut-cache"):
            with self.subTest(path=path):
                self.assertEqual(patches.classify_path(path, "django/django", is_new=True), "excluded")

    def test_vo1_p4_excluded_wins_over_repo_src_exception_and_test(self):
        cases = [
            ("pytest-dev/pytest", "src/_pytest/__pycache__/x.pyc"),
            ("pytest-dev/pytest", "src/_pytest/x.py.orig"),
            ("django/django", "django/test/x.py.rej"),
            ("django/django", "tests/__pycache__/test_x.cpython-312.pyc"),
            ("django/django", "tests/test_x.py.orig"),
        ]
        for repo, path in cases:
            with self.subTest(path=path):
                self.assertEqual(patches.classify_path(path, repo), "excluded")

    def test_vo1_p4_only_the_named_workflow_file_is_excluded(self):
        self.assertNotEqual(
            patches.classify_path(".github/workflows/other.yml", "django/django"), "excluded"
        )

    def test_vo1_p5_new_root_file_is_scratch(self):
        for path in ("reproduce.py", "test_repro.py", "notes.txt"):
            with self.subTest(path=path):
                self.assertEqual(
                    patches.classify_path(path, "django/django", is_new=True), "scratch"
                )

    def test_vo1_p6_modified_root_file_is_src(self):
        for path in ("setup.py", "tox.ini"):
            with self.subTest(path=path):
                self.assertEqual(patches.classify_path(path, "django/django"), "src")
                self.assertEqual(patches.classify_path(path, "django/django", is_new=False), "src")

    def test_vo1_p7_new_nested_file_is_not_scratch(self):
        self.assertEqual(
            patches.classify_path("pkg/new_module.py", "django/django", is_new=True), "src"
        )
        self.assertEqual(
            patches.classify_path("tests/test_new.py", "django/django", is_new=True), "test"
        )

    def test_vo1_load_rules_default_returns_dict_usable_as_rules_argument(self):
        rules = patches.load_rules()
        self.assertIsInstance(rules, dict)
        self.assertEqual(
            patches.classify_path("django/test/utils.py", "django/django", rules=rules), "test"
        )
        self.assertEqual(patches.classify_path(".gitignore", "django/django", rules=rules), "excluded")


class FileSectionTests(unittest.TestCase):
    def test_vo2_s1_modify(self):
        self.assertEqual(
            patches.file_sections(diffs.MOD),
            [{"path": "pkg/mod.py", "old_path": "pkg/mod.py", "is_new": False,
              "is_deleted": False, "text": diffs.MOD}],
        )

    def test_vo2_s2_new_file(self):
        self.assertEqual(
            patches.file_sections(diffs.NEW),
            [{"path": "pkg/new.py", "old_path": "pkg/new.py", "is_new": True,
              "is_deleted": False, "text": diffs.NEW}],
        )

    def test_vo2_s3_delete(self):
        self.assertEqual(
            patches.file_sections(diffs.DEL),
            [{"path": "pkg/old.py", "old_path": "pkg/old.py", "is_new": False,
              "is_deleted": True, "text": diffs.DEL}],
        )

    def test_vo2_s4_rename_with_edit_and_pure_rename(self):
        self.assertEqual(
            patches.file_sections(diffs.RENAME_EDIT),
            [{"path": "pkg/after.py", "old_path": "pkg/before.py", "is_new": False,
              "is_deleted": False, "text": diffs.RENAME_EDIT}],
        )
        self.assertEqual(
            patches.file_sections(diffs.RENAME_PURE),
            [{"path": "new_name.py", "old_path": "old_name.py", "is_new": False,
              "is_deleted": False, "text": diffs.RENAME_PURE}],
        )

    def test_vo2_s5_multiple_hunks_stay_in_one_section(self):
        sections = patches.file_sections(diffs.MULTI)
        self.assertEqual(len(sections), 1)
        self.assertEqual(sections[0]["text"], diffs.MULTI)

    def test_vo2_s6_no_newline_marker_stays_in_its_section(self):
        sections = patches.file_sections(diffs.NOEOL + diffs.MOD)
        self.assertEqual([s["path"] for s in sections], ["pkg/noeol.py", "pkg/mod.py"])
        self.assertEqual([s["text"] for s in sections], [diffs.NOEOL, diffs.MOD])

    def test_vo2_s7_sections_follow_input_order_and_flags(self):
        diff = diffs.DEL + diffs.NEW + diffs.MOD + diffs.RENAME_EDIT
        self.assertEqual(
            [(s["path"], s["is_new"], s["is_deleted"]) for s in patches.file_sections(diff)],
            [("pkg/old.py", False, True), ("pkg/new.py", True, False),
             ("pkg/mod.py", False, False), ("pkg/after.py", False, False)],
        )
        self.assertEqual("".join(s["text"] for s in patches.file_sections(diff)), diff)

    def test_vo2_s8_empty_diff_has_no_sections(self):
        self.assertEqual(patches.file_sections(""), [])


class HeaderOnlySectionTests(unittest.TestCase):
    CASES = [
        ("empty_new", diffs.EMPTY_NEW, "pkg/empty.py", "pkg/empty.py", True, False),
        ("deleted_empty", diffs.EMPTY_DELETED_TEST, "tests/test_empty.py", "tests/test_empty.py", False, True),
        ("mode_only", diffs.MODE_ONLY, "pkg/run.sh", "pkg/run.sh", False, False),
        ("space_in_path", diffs.SPACE_PATH_NEW, "dir b/x.py", "dir b/x.py", True, False),
    ]

    def test_vo2_s10_header_only_sections_have_plain_repo_paths(self):
        for name, diff, path, old_path, is_new, is_deleted in self.CASES:
            with self.subTest(case=name):
                self.assertEqual(
                    patches.file_sections(diff),
                    [{"path": path, "old_path": old_path, "is_new": is_new,
                      "is_deleted": is_deleted, "text": diff}],
                )

    def test_vo2_s10_header_only_sections_between_others_keep_boundaries(self):
        diff = diffs.SRC_A + diffs.EMPTY_NEW + diffs.MODE_ONLY + diffs.SPACE_PATH_NEW + diffs.TEST_A
        sections = patches.file_sections(diff)
        self.assertEqual(
            [s["path"] for s in sections],
            ["pkg/a.py", "pkg/empty.py", "pkg/run.sh", "dir b/x.py", "tests/test_a.py"],
        )
        self.assertEqual("".join(s["text"] for s in sections), diff)

    def test_vo2_s10_deleted_empty_test_file_is_classified_test(self):
        result = patches.split_patch(diffs.SRC_A + diffs.EMPTY_DELETED_TEST, "django/django")
        self.assertEqual(
            result, {"src": diffs.SRC_A, "test": diffs.EMPTY_DELETED_TEST, "scratch": "", "excluded": ""}
        )

    def test_vo2_s10_header_only_new_files_are_classified_by_path(self):
        result = patches.split_patch(
            diffs.EMPTY_NEW + diffs.EMPTY_NEW_ROOT + diffs.MODE_ONLY, "django/django"
        )
        self.assertEqual(
            result,
            {"src": diffs.EMPTY_NEW + diffs.MODE_ONLY, "test": "", "scratch": diffs.EMPTY_NEW_ROOT, "excluded": ""},
        )

    def test_vo2_s10_changed_lines_gives_empty_lists_for_sections_without_added_lines(self):
        self.assertEqual(
            patches.changed_lines(diffs.EMPTY_NEW + diffs.MODE_ONLY + diffs.EMPTY_DELETED_TEST + diffs.NEW),
            {"pkg/empty.py": [], "pkg/run.sh": [], "pkg/new.py": [1, 2, 3]},
        )

    def test_vo2_s10_changed_lines_deletion_only_modification_has_an_empty_list(self):
        diff = (
            "diff --git a/pkg/shrink.py b/pkg/shrink.py\n"
            "index 1212121..3434343 100644\n"
            "--- a/pkg/shrink.py\n"
            "+++ b/pkg/shrink.py\n"
            "@@ -1,3 +1,2 @@\n"
            " a\n"
            "-b\n"
            " c\n"
        )
        self.assertEqual(patches.changed_lines(diff), {"pkg/shrink.py": []})
        self.assertEqual(
            patches.changed_lines(diff + diffs.DEL + diffs.MOD),
            {"pkg/shrink.py": [], "pkg/mod.py": [2, 3]},
        )


class SplitPatchTests(unittest.TestCase):
    MIXED = [
        diffs.SRC_A, diffs.TEST_A, diffs.EXCLUDED_GITIGNORE, diffs.CRLF_NEW,
        diffs.DJANGO_TEST_UTILS, diffs.SCRATCH, diffs.EXCLUDED_NOTES, diffs.TEST_B_NOEOL,
    ]

    def test_vo2_s7_mixed_classes_keep_order_and_bytes(self):
        result = patches.split_patch("".join(self.MIXED), "django/django")
        self.assertEqual(
            result,
            {
                "src": diffs.SRC_A + diffs.CRLF_NEW,
                "test": diffs.TEST_A + diffs.DJANGO_TEST_UTILS + diffs.TEST_B_NOEOL,
                "scratch": diffs.SCRATCH,
                "excluded": diffs.EXCLUDED_GITIGNORE + diffs.EXCLUDED_NOTES,
            },
        )

    def test_vo2_s7_modified_root_file_is_src_not_scratch(self):
        result = patches.split_patch(diffs.SETUP_MODIFIED + diffs.SCRATCH, "django/django")
        self.assertEqual(result["src"], diffs.SETUP_MODIFIED)
        self.assertEqual(result["scratch"], diffs.SCRATCH)

    def test_vo2_s7_rename_is_classified_by_new_path(self):
        diff = (
            "diff --git a/pkg/mod.py b/tests/test_mod.py\n"
            "similarity index 100%\n"
            "rename from pkg/mod.py\n"
            "rename to tests/test_mod.py\n"
        )
        result = patches.split_patch(diff, "django/django")
        self.assertEqual(result["test"], diff)
        self.assertEqual(result["src"], "")

    def test_vo2_s7_explicit_rules_argument_is_honored(self):
        rules = patches.load_rules()
        self.assertEqual(
            patches.split_patch("".join(self.MIXED), "django/django", rules),
            patches.split_patch("".join(self.MIXED), "django/django"),
        )

    def test_vo2_s8_empty_input_gives_four_empty_classes(self):
        self.assertEqual(
            patches.split_patch("", "django/django"),
            {"src": "", "test": "", "scratch": "", "excluded": ""},
        )

    def test_vo2_s8_absent_classes_are_empty_strings(self):
        self.assertEqual(
            patches.split_patch(diffs.SRC_A, "django/django"),
            {"src": diffs.SRC_A, "test": "", "scratch": "", "excluded": ""},
        )
        self.assertEqual(
            patches.split_patch(diffs.TEST_A, "django/django"),
            {"src": "", "test": diffs.TEST_A, "scratch": "", "excluded": ""},
        )
        self.assertEqual(
            patches.split_patch(diffs.EXCLUDED_NOTES, "django/django"),
            {"src": "", "test": "", "scratch": "", "excluded": diffs.EXCLUDED_NOTES},
        )


class ChangedLinesTests(unittest.TestCase):
    def test_vo2_s1_modify_counts_added_lines_only(self):
        self.assertEqual(patches.changed_lines(diffs.MOD), {"pkg/mod.py": [2, 3]})

    def test_vo2_s2_new_file_marks_every_line(self):
        self.assertEqual(patches.changed_lines(diffs.NEW), {"pkg/new.py": [1, 2, 3]})

    def test_vo2_s3_deleted_files_are_omitted(self):
        self.assertEqual(patches.changed_lines(diffs.DEL), {})
        self.assertEqual(
            patches.changed_lines(diffs.DEL + diffs.NEW), {"pkg/new.py": [1, 2, 3]}
        )

    def test_vo2_s4_rename_is_keyed_by_new_path(self):
        self.assertEqual(patches.changed_lines(diffs.RENAME_EDIT), {"pkg/after.py": [2]})

    def test_vo2_s5_multiple_hunks_use_post_image_numbers(self):
        self.assertEqual(patches.changed_lines(diffs.MULTI), {"pkg/multi.py": [2, 12]})

    def test_vo2_s6_no_newline_marker_is_not_a_line(self):
        self.assertEqual(patches.changed_lines(diffs.NOEOL), {"pkg/noeol.py": [2]})

    def test_vo2_s7_multiple_files_are_keyed_separately_and_sorted(self):
        diff = diffs.MULTI + diffs.NEW + diffs.NOEOL
        self.assertEqual(
            patches.changed_lines(diff),
            {"pkg/multi.py": [2, 12], "pkg/new.py": [1, 2, 3], "pkg/noeol.py": [2]},
        )

    def test_vo2_s1_added_line_that_looks_like_a_header_is_counted(self):
        diff = (
            "diff --git a/pkg/h.py b/pkg/h.py\n"
            "index 1111111..2222222 100644\n"
            "--- a/pkg/h.py\n"
            "+++ b/pkg/h.py\n"
            "@@ -1,2 +1,4 @@\n"
            " keep\n"
            "+++ b/not-a-header\n"
            "+@@ -1 +1 @@\n"
            " end\n"
        )
        self.assertEqual(patches.changed_lines(diff), {"pkg/h.py": [2, 3]})

    def test_vo2_s8_empty_diff(self):
        self.assertEqual(patches.changed_lines(""), {})


class ApplyToTextsTests(unittest.TestCase):
    def test_vo2_s9_create(self):
        self.assertEqual(
            patches.apply_to_texts({}, diffs.NEW), {"pkg/new.py": diffs.NEW_POST}
        )
        self.assertEqual(
            patches.apply_to_texts({"pkg/new.py": None}, diffs.NEW), {"pkg/new.py": diffs.NEW_POST}
        )

    def test_vo2_s9_modify(self):
        self.assertEqual(
            patches.apply_to_texts({"pkg/mod.py": diffs.MOD_BASE}, diffs.MOD),
            {"pkg/mod.py": diffs.MOD_POST},
        )

    def test_vo2_s9_delete(self):
        self.assertEqual(
            patches.apply_to_texts({"pkg/old.py": diffs.DEL_BASE}, diffs.DEL), {"pkg/old.py": None}
        )

    def test_vo2_s9_combined_keeps_untouched_and_absent_keys(self):
        files = {
            "pkg/mod.py": diffs.MOD_BASE,
            "pkg/old.py": diffs.DEL_BASE,
            "keep.txt": "k\n",
            "ghost.py": None,
        }
        self.assertEqual(
            patches.apply_to_texts(files, diffs.MOD + diffs.NEW + diffs.DEL),
            {
                "pkg/mod.py": diffs.MOD_POST,
                "pkg/old.py": None,
                "keep.txt": "k\n",
                "ghost.py": None,
                "pkg/new.py": diffs.NEW_POST,
            },
        )

    def test_vo2_s9_no_newline_and_crlf_bytes_survive(self):
        self.assertEqual(
            patches.apply_to_texts({"pkg/noeol.py": diffs.NOEOL_BASE}, diffs.NOEOL),
            {"pkg/noeol.py": diffs.NOEOL_POST},
        )
        self.assertEqual(
            patches.apply_to_texts({}, diffs.CRLF_NEW), {"pkg/b.py": diffs.CRLF_POST}
        )

    def test_vo2_s9_non_applying_patch_raises_value_error(self):
        with self.assertRaises(ValueError):
            patches.apply_to_texts({"pkg/mod.py": "unrelated\ncontent\n"}, diffs.MOD)

    def test_vo2_s9_rename_moves_the_text(self):
        result = patches.apply_to_texts(
            {"pkg/before.py": diffs.RENAME_EDIT_BASE}, diffs.RENAME_EDIT
        )
        self.assertEqual(result["pkg/after.py"], diffs.RENAME_EDIT_POST)
        self.assertIsNone(result["pkg/before.py"])


REPO = "django/django"
BASE_LINES = [f"line {i}\n" for i in range(1, 11)]
BASE_TEXT = "".join(BASE_LINES)
POST_TEXT = "".join(l if i != 3 else "line 3 changed\n" for i, l in enumerate(BASE_LINES, 1))
CHANGED_LINE = 3


def git_diff(base, mutate, diff_flags=("-M",)):
    """Real `git diff` output (default core.quotePath) for `mutate` applied to `base`.

    Expected paths in the tests are the names written to disk here, so they do not
    depend on the parser under test.
    """
    env = {
        **os.environ,
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_SYSTEM": os.devnull,
        "GIT_CONFIG_NOSYSTEM": "1",
    }

    def git(root, *args):
        return subprocess.run(
            ["git", "-c", "core.autocrlf=false", "-c", "core.fileMode=true",
             "-c", "user.name=t", "-c", "user.email=t@t", *args],
            cwd=root, env=env, check=True, capture_output=True, text=True, encoding="utf-8",
        ).stdout

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        git(root, "init", "-q")
        for name, text in base.items():
            target = root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8", newline="")
        if base:
            git(root, "add", "-A")
            git(root, "commit", "-q", "-m", "base")
        mutate(root)
        git(root, "add", "-A")
        return git(root, "diff", "--cached", "--no-color", "--no-ext-diff", *diff_flags)


def _write(root, name, text):
    target = root / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8", newline="")


def _rename(root, old, new):
    (root / new).parent.mkdir(parents=True, exist_ok=True)
    os.rename(root / old, root / new)


def _chmod_x(root, name):
    os.chmod(root / name, 0o755)


class GitGeneratedPathTests(unittest.TestCase):
    def _make(self, name, op, new_name=None):
        """Return (diff, expected) for one operation on `name` using real git."""
        if op == "modify":
            diff = git_diff({name: BASE_TEXT}, lambda r: _write(r, name, POST_TEXT))
            return diff, dict(path=name, old_path=name, new=False, deleted=False,
                              lines={name: [CHANGED_LINE]})
        if op == "new":
            diff = git_diff({"keep.txt": "k\n"}, lambda r: _write(r, name, BASE_TEXT))
            return diff, dict(path=name, old_path=None, new=True, deleted=False,
                              lines={name: list(range(1, 11))})
        if op == "empty_new":
            diff = git_diff({"keep.txt": "k\n"}, lambda r: _write(r, name, ""))
            return diff, dict(path=name, old_path=None, new=True, deleted=False,
                              lines={name: []})
        if op == "delete":
            diff = git_diff({name: BASE_TEXT}, lambda r: os.remove(r / name))
            return diff, dict(path=None, old_path=name, new=False, deleted=True, lines={})
        if op == "mode":
            diff = git_diff({name: BASE_TEXT}, lambda r: _chmod_x(r, name))
            return diff, dict(path=name, old_path=name, new=False, deleted=False,
                              lines={name: []})
        if op == "rename":
            def mutate(r):
                _rename(r, name, new_name)
                _write(r, new_name, POST_TEXT)
            diff = git_diff({name: BASE_TEXT}, mutate)
            return diff, dict(path=new_name, old_path=name, new=False, deleted=False,
                              lines={new_name: [CHANGED_LINE]})
        raise AssertionError(op)

    def _check(self, name, op, new_name=None):
        try:
            diff, exp = self._make(name, op, new_name)
        except (OSError, subprocess.CalledProcessError) as exc:
            self.skipTest(f"filesystem/git refused {name!r} for {op}: {exc}")
        label = f"{op} {name!r}"
        sections = patches.file_sections(diff)
        target = [s for s in sections if s["path"] != "keep.txt"]
        self.assertEqual(len(target), 1, label)
        sec = target[0]
        if exp["path"] is not None:
            self.assertEqual(sec["path"], exp["path"], label)
        if exp["old_path"] is not None:
            self.assertEqual(sec["old_path"], exp["old_path"], label)
        self.assertIs(sec["is_new"], exp["new"], label)
        self.assertIs(sec["is_deleted"], exp["deleted"], label)
        self.assertEqual(patches.changed_lines(diff), exp["lines"], label)
        plain = exp["path"] if exp["path"] is not None else exp["old_path"]
        cls = patches.classify_path(plain, REPO, is_new=exp["new"])
        split = patches.split_patch(diff, REPO)
        self.assertEqual(split[cls], sec["text"], label)
        for other, text in split.items():
            if other != cls:
                self.assertEqual(text, "", f"{label}: stray content in {other}")
        self.assertEqual("".join(split.values()), diff, label)
        return diff

    def test_vo2_s11_space_in_path_modify(self):
        self._check("dir x/y z.py", "modify")

    def test_vo2_s11_space_in_path_new_with_content(self):
        self._check("dir x/y z.py", "new")

    def test_vo2_s11_space_in_path_delete(self):
        self._check("dir x/y z.py", "delete")

    def test_vo2_s11_space_in_path_rename_with_content_change(self):
        self._check("dir x/y z.py", "rename", "dir x/w v.py")

    def test_vo2_s11_space_path_has_no_trailing_tab_anywhere(self):
        diff = git_diff({"dir x/y z.py": BASE_TEXT}, lambda r: _write(r, "dir x/y z.py", POST_TEXT))
        for sec in patches.file_sections(diff):
            self.assertNotIn("\t", sec["path"])
            self.assertNotIn("\t", sec["old_path"])
        for key in patches.changed_lines(diff):
            self.assertNotIn("\t", key)

    def test_vo2_s11_space_path_in_tests_dir_is_classified_by_plain_path(self):
        name = "tests/my dir/test a.py"
        diff = git_diff({name: BASE_TEXT}, lambda r: _write(r, name, POST_TEXT))
        self.assertEqual(patches.split_patch(diff, REPO)["test"], diff)
        self.assertEqual(patches.changed_lines(diff), {name: [CHANGED_LINE]})

    def _run_quoted(self, name, new_name, quoted_marker):
        for op in ("modify", "new", "empty_new", "delete", "mode", "rename"):
            with self.subTest(name=name, op=op):
                diff = self._check(name, op, new_name)
                self.assertIn(quoted_marker, diff, "oracle diff must contain the quoted form")

    def test_vo2_s12_non_ascii_name(self):
        self._run_quoted("d\u00e9.py", "d\u00e9_r.py", '"a/d\\303\\251.py"')

    def test_vo2_s12_tab_in_name(self):
        self._run_quoted("a\tb.py", "a\tb_r.py", 'a\\tb.py"')

    def test_vo2_s12_double_quote_in_name(self):
        self._run_quoted('q"x.py', 'q"x_r.py', 'q\\"x.py"')

    def test_vo2_s12_apply_to_texts_round_trips_non_ascii_modify(self):
        name = "d\u00e9.py"
        diff = git_diff({name: BASE_TEXT}, lambda r: _write(r, name, POST_TEXT))
        self.assertEqual(patches.apply_to_texts({name: BASE_TEXT}, diff), {name: POST_TEXT})

    def test_vo2_s11_apply_to_texts_round_trips_space_path_modify(self):
        name = "dir x/y z.py"
        diff = git_diff({name: BASE_TEXT}, lambda r: _write(r, name, POST_TEXT))
        self.assertEqual(patches.apply_to_texts({name: BASE_TEXT}, diff), {name: POST_TEXT})

    def test_vo2_s13_body_lines_that_look_like_dev_null_headers_set_no_flags(self):
        base = "keep\n-- /dev/null\ntail\n"
        post = "keep\n++ /dev/null\ntail\n"
        diff = git_diff({"x.py": base}, lambda r: _write(r, "x.py", post))
        self.assertIn("\n--- /dev/null\n", diff)
        self.assertIn("\n+++ /dev/null\n", diff)
        (sec,) = patches.file_sections(diff)
        self.assertEqual((sec["path"], sec["old_path"]), ("x.py", "x.py"))
        self.assertIs(sec["is_new"], False)
        self.assertIs(sec["is_deleted"], False)
        self.assertEqual(patches.changed_lines(diff), {"x.py": [2]})
        split = patches.split_patch(diff, REPO)
        self.assertEqual(split["src"], diff)
        self.assertEqual((split["scratch"], split["test"], split["excluded"]), ("", "", ""))

    def _check_escapes(self, name, marker):
        try:
            diff, _ = self._make(name, "new")
        except (OSError, subprocess.CalledProcessError) as exc:
            self.skipTest(f"filesystem/git refused {name!r}: {exc}")
        self.assertIn(marker, diff, "oracle diff must contain the escape form")
        self._check(name, "new")

    def test_vo2_s14_bel_bs_vt_ff_cr_in_one_name(self):
        self._check_escapes("e\a\b\v\f\r.py", "e\\a\\b\\v\\f\\r.py")

    def test_vo2_s14_newline_in_name(self):
        self._check_escapes("n\nl.py", "n\\nl.py")

    def test_vo2_s14_backslash_in_name(self):
        self._check_escapes("b\\s.py", "b\\\\s.py")

    def test_vo2_s14_octal_escape_followed_by_literal_digit(self):
        self._check_escapes("\u00e91.py", "\\303\\2511.py")

    def test_vo2_s15_non_utf8_octal_escape_round_trips_bytes(self):
        diff = (
            'diff --git "a/\\377.py" "b/\\377.py"\n'
            "new file mode 100644\n"
            "index 0000000..e69de29\n"
        )
        (sec,) = patches.file_sections(diff)
        self.assertEqual(os.fsencode(sec["path"]), b"\xff.py")
        self.assertIs(sec["is_new"], True)
        self.assertIs(sec["is_deleted"], False)

    COPY_SRC = "".join(f"distinct source row {i} zebra\n" for i in range(1, 13))
    COPY_FLAGS = ("-C", "--find-copies-harder")

    def _copy(self, dst, text=None):
        body = self.COPY_SRC if text is None else text
        return git_diff({"x": self.COPY_SRC},
                        lambda r: _write(r, dst, body), diff_flags=self.COPY_FLAGS)

    def _check_pure_copy(self, dst, marker):
        diff = self._copy(dst)
        self.assertIn("\ncopy from x\n", diff, "oracle must detect the copy")
        self.assertIn(marker, diff)
        (sec,) = patches.file_sections(diff)
        self.assertEqual((sec["old_path"], sec["path"]), ("x", dst))
        self.assertIs(sec["is_new"], False)
        self.assertIs(sec["is_deleted"], False)
        self.assertEqual(set(patches.changed_lines(diff)), {dst})

    def test_vo2_s16_copy_to_plain_path(self):
        self._check_pure_copy("y.py", "\ncopy to y.py\n")

    def test_vo2_s16_copy_to_path_containing_space_b_slash(self):
        self._check_pure_copy("y b/z", "\ncopy to y b/z\n")

    def test_vo2_s16_copy_from_unquoted_to_quoted_name(self):
        self._check_pure_copy("cp \u00e9.py", '\ncopy to "cp \\303\\251.py"\n')

    def test_vo2_s16_copy_with_content_change_to_path_with_space(self):
        dst = "dir x/y z.py"
        changed = self.COPY_SRC.replace("row 5 zebra", "row 5 changed")
        diff = self._copy(dst, changed)
        self.assertIn("\ncopy from x\n", diff, "oracle must detect the copy")
        self.assertIn("\n@@", diff)
        (sec,) = patches.file_sections(diff)
        self.assertEqual((sec["old_path"], sec["path"]), ("x", dst))
        self.assertIs(sec["is_new"], False)
        self.assertIs(sec["is_deleted"], False)
        self.assertEqual(patches.changed_lines(diff), {dst: [5]})


if __name__ == "__main__":
    unittest.main()

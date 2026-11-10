import functools
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from test_installer import INSTALLER, REPO_ROOT, InstallerTestCase, run_git, run_installer
from test_progress import NAME1, ProgressCase, build, load_progress, out

FIXTURE = Path(__file__).resolve().parent / "data" / "harness-block-0.40.0.md"
INSTRUCTIONS = ".harness/instructions"

S1 = (
    "harness: this session changed the project and has no progress yet. "
    "Read .harness/instructions/progress.md, then write agent-docs/progress/<16-hex-id>-<kebab-name>.md "
    "so it is committed with the work."
)
S1_STEM = "has no progress yet"
N2_STEM = "this session changed the project and had no progress, so"
S2 = "following .harness/instructions/progress.md, run"
S3 = "and dead ends, following .harness/instructions/progress.md."
S4 = "following .harness/instructions/progress.md before stopping."
OLD_POINTER = "Progress Rule in AGENTS.md"

S6_LABEL = "move hook-backed rules into their own instruction files"
S6_PLAN = [
    "the Progress, Try-n-Fail, Todo, Index & Staleness, and Synced Comment rules move from .harness/instructions/harness-block.md to their own files in .harness/instructions/",
    "the managed block lists each rule file and when to read it; hook and pre-commit messages name the file of a violated rule",
    "a session's first project change without a progress prints a one-time reminder to write one",
    "no data is migrated; AGENTS.md is unchanged",
]

S7 = """## Rule Files

These rules live in separate files under `.harness/instructions/`. Read the file before the work it covers; hook and pre-commit messages name the file of a rule they find violated.

| file | what it is | read before |
| --- | --- | --- |
| `progress.md` | the per-session record in `agent-docs/progress/`: frontmatter, required sections, retiring before a PR | committing in a session that changed the project, writing in `agent-docs/progress/` or `agent-docs/progress-logs/`, continuing earlier work, or opening a PR |
| `index-and-staleness.md` | file naming, `index.md` entries, and moving a document to `stale/` | adding, renaming, or marking stale a document in an agent-managed directory under `agent-docs/`, or editing its `index.md` or `stale.md` |
| `try-n-fail.md` | the record of a failed attempt or rejected proposal and its required sections | writing or proposing a record in `agent-docs/try-n-fail/` |
| `todos.md` | the record of a work item not tied to a session and its required sections | writing a record in `agent-docs/todos/` |
| `synced-comments.md` | the tracking file and code tags for a comment kept identical in several places | keeping one comment or docstring identical in several places, or editing code tagged `synced id:` |
"""

KEPT_HEADINGS = [
    "# Documentation Guide",
    "## Principles",
    "## Commit Stamp",
    "## Rule Files",
    "# Task Guide",
    "## User Decision",
    "## Reporting to the User",
    "## Commit & PR Messages",
]
MOVED = {
    "## Progress Rule": "progress.md",
    "## Index & Staleness Management": "index-and-staleness.md",
    "## Shared Comment & Docstring Synchronization Rules": "synced-comments.md",
    "## Try-n-Fail Rule": "try-n-fail.md",
    "## Todo Rule": "todos.md",
}
RULE_FILE_ORDER = [
    f"{INSTRUCTIONS}/index-and-staleness.md",
    f"{INSTRUCTIONS}/synced-comments.md",
    f"{INSTRUCTIONS}/try-n-fail.md",
    f"{INSTRUCTIONS}/todos.md",
    f"{INSTRUCTIONS}/progress.md",
]
MOVED_REGEX = re.compile(r"(Progress|Try-n-Fail|Todo) Rule in `?AGENTS\.md")


def split_sections(text):
    sections = []
    fenced = False
    for line in text.splitlines(keepends=True):
        if line.lstrip().startswith("```"):
            fenced = not fenced
        elif not fenced and re.match(r"#{1,2} \S", line):
            sections.append([line.rstrip("\n"), ""])
        if not sections:
            sections.append(["", ""])
        sections[-1][1] += line
    return [(heading, body) for heading, body in sections]


def base_sections():
    return dict(split_sections(FIXTURE.read_text()))


@functools.lru_cache(maxsize=1)
def shared_install():
    tmp = tempfile.TemporaryDirectory()
    shared_install.tmp = tmp
    repo = Path(tmp.name)
    run_git(repo, "init", "-q")
    run_git(repo, "config", "user.email", "test@test.com")
    run_git(repo, "config", "user.name", "test")
    result = run_installer("install", str(repo), "--no-ci")
    if result.returncode != 0:
        raise RuntimeError(result.stdout + result.stderr)
    return repo


def read_block(repo):
    return (repo / ".harness" / "instructions" / "harness-block.md").read_text()


class TestBlockSplit(unittest.TestCase):
    def test_v1_fixture_has_the_twelve_base_sections_in_order(self):
        headings = [h for h, _ in split_sections(FIXTURE.read_text())]
        self.assertEqual(
            headings,
            ["# Documentation Guide", "## Principles", "## Commit Stamp", "## Index & Staleness Management",
             "## Shared Comment & Docstring Synchronization Rules", "## Try-n-Fail Rule", "## Progress Rule",
             "## Todo Rule", "# Task Guide", "## User Decision", "## Reporting to the User",
             "## Commit & PR Messages"],
        )

    def test_v1_kept_sections_are_byte_equal_to_base_and_in_order(self):
        base = base_sections()
        actual = split_sections(read_block(shared_install()))
        self.assertEqual([h for h, _ in actual], KEPT_HEADINGS)
        for heading, body in actual:
            if heading == "## Rule Files":
                continue
            with self.subTest(section=heading):
                self.assertEqual(body.rstrip("\n"), base[heading].rstrip("\n"))

    def test_v1_s7_sits_between_commit_stamp_and_task_guide(self):
        headings = [h for h, _ in split_sections(read_block(shared_install()))]
        self.assertEqual(headings.index("## Rule Files"), headings.index("## Commit Stamp") + 1)
        self.assertEqual(headings.index("# Task Guide"), headings.index("## Rule Files") + 1)

    def test_v1_moved_sections_equal_their_files_per_base_text(self):
        base = base_sections()
        repo = shared_install()
        for heading, name in MOVED.items():
            with self.subTest(section=heading, file=name):
                actual = (repo / ".harness" / "instructions" / name).read_text()
                if name == "progress.md":
                    self.assertTrue(actual.startswith("## Progress Rule"))
                    continue
                expected = base[heading].rstrip("\n") + "\n"
                self.assertEqual(actual, expected)

    def test_v1_moved_headings_are_absent_from_the_block(self):
        lines = read_block(shared_install()).splitlines()
        for heading in MOVED:
            with self.subTest(section=heading):
                self.assertNotIn(heading, lines)
        self.assertNotIn("### Hook Behavior", lines)

    def test_v2_rule_files_section_matches_s7_exactly(self):
        sections = dict(split_sections(read_block(shared_install())))
        self.assertEqual(sections["## Rule Files"].rstrip("\n"), S7.rstrip("\n"))

    def test_v2_five_rule_files_exist_in_a_fresh_install(self):
        repo = shared_install()
        for name in MOVED.values():
            with self.subTest(file=name):
                self.assertTrue((repo / ".harness" / "instructions" / name).is_file())
        self.assertTrue((repo / ".harness" / "instructions" / "harness-block.md").is_file())

    def test_v12_block_size_is_at_most_4500_bytes(self):
        size = len(read_block(shared_install()).encode())
        self.assertLessEqual(size, 4500)
        self.assertGreater(size, len(S7.encode()))


class TestHookSessions(ProgressCase):
    def edit(self, repo, rel, sid="sessa", content=None, tool="Edit", **kw):
        path = repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content if content is not None else f"changed {rel}\n")
        return self.post(repo, path, sid=sid, tool=tool, **kw)

    def started(self):
        repo = self.new_repo()
        self.add_marker(repo, os.getpid())
        self.assertEqual(self.start(repo).returncode, 0)
        return repo

    def commit_progress(self, repo, directory="progress", session="sessa"):
        head = self.head(repo)
        path = self.put(repo, NAME1, build(session=session, stamp=head, next_step=[("alpha work item", head, "none")]),
                        directory=directory)
        run_git(repo, "add", "-A")
        self.commit(repo, "progress")
        return path

    def assert_reminded(self, result):
        self.assertEqual(result.returncode, 2, out(result))
        self.assertEqual(result.stderr.count(N2_STEM), 1, result.stderr)
        self.assertNotIn(S1_STEM, result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def assert_silent(self, result):
        self.assertEqual(result.returncode, 0, out(result))
        self.assertNotIn(S1_STEM, result.stderr)
        self.assertNotIn(N2_STEM, result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_v3_d1_first_modifying_edit_without_progress_prints_s1_and_exits_2(self):
        repo = self.started()
        self.assert_reminded(self.edit(repo, "src/a.py"))

    def test_v3_d2_later_modifying_calls_print_nothing_and_s1_occurs_once_in_the_session(self):
        repo = self.started()
        calls = [
            self.edit(repo, "src/a.py"),
            self.edit(repo, "src/b.py"),
            self.bash(repo, lambda: (repo / "src" / "c.py").write_text("c = 1\n")),
        ]
        self.assert_reminded(calls[0])
        self.assert_silent(calls[1])
        self.assertEqual(calls[1].stderr, "")
        self.assert_silent(calls[2])
        self.assertEqual(calls[2].stderr, "")
        self.assertEqual(sum(call.stderr.count(N2_STEM) for call in calls), 1)

    def test_v3_d3_own_progress_in_progress_dir_before_first_change_prints_nothing(self):
        repo = self.new_repo()
        self.commit_progress(repo, "progress")
        self.assertEqual(self.start(repo).returncode, 0)
        self.assert_silent(self.edit(repo, "src/a.py"))

    def test_v3_d4_own_progress_in_progress_logs_before_first_change_prints_nothing(self):
        repo = self.new_repo()
        self.commit_progress(repo, "progress-logs")
        self.assertEqual(self.start(repo).returncode, 0)
        self.assert_silent(self.edit(repo, "src/a.py"))

    def test_v3_d5_first_change_being_the_sessions_own_progress_write_prints_nothing(self):
        repo = self.started()
        self.add_marker(repo, os.getpid())
        head = self.head(repo)
        path = self.put(repo, NAME1, build(session="sessa", stamp=head, next_step=[("alpha work item", head, "none")]))
        written = self.post(repo, path)
        self.assertNotIn(S1_STEM, written.stderr)
        self.assertNotIn("Traceback", written.stderr)
        self.assert_silent(self.edit(repo, "src/a.py"))

    def test_v3_d6_edit_under_harness_dir_is_not_marked_and_prints_nothing(self):
        repo = self.started()
        result = self.edit(repo, ".harness/scratch.txt")
        self.assert_silent(result)
        self.assertEqual(self.stop(repo).returncode, 0)

    def test_v3_d6_git_ignored_edit_is_not_marked_and_prints_nothing(self):
        repo = self.new_repo()
        (repo / ".gitignore").write_text("logs/\n")
        run_git(repo, "add", ".gitignore")
        self.commit(repo, "ignore logs")
        self.assertEqual(self.start(repo).returncode, 0)
        result = self.edit(repo, "logs/personal.log")
        self.assert_silent(result)
        self.assertEqual(self.stop(repo).returncode, 0)

    def test_v3_d6_bash_call_exempted_by_a_matching_installer_run_record_prints_nothing(self):
        repo = self.started()
        progress = load_progress()
        before = progress.git_worktree_fingerprint(repo, ".harness/")

        def action():
            (repo / "src" / "new.py").write_text("x\n")
            after = progress.git_worktree_fingerprint(repo, ".harness/")
            progress.write_installer_run(repo, before, after)

        result = self.bash(repo, action)
        self.assert_silent(result)
        self.assertEqual(self.stop(repo).returncode, 0)

    def test_v3_d7_bash_first_change_in_post_tool_use_prints_s1_and_exits_2(self):
        repo = self.started()
        self.assert_reminded(self.bash(repo, lambda: (repo / "src" / "new.py").write_text("x\n")))

    def test_v4_failure_event_marks_without_s1_then_next_post_prints_once_then_nothing(self):
        repo = self.started()

        failed = self.bash(repo, lambda: (repo / "src" / "new.py").write_text("x\n"), event="PostToolUseFailure")
        self.assertEqual(failed.returncode, 0, out(failed))
        self.assertNotIn(S1_STEM, out(failed))
        self.assertNotIn(N2_STEM, out(failed))

        first = self.edit(repo, "src/a.py")
        self.assert_reminded(first)

        second = self.edit(repo, "src/b.py")
        self.assert_silent(second)
        self.assertEqual(second.stderr, "")
        self.assertEqual(self.stop(repo).returncode, 2)

    def test_v4_failure_event_marks_then_non_modifying_bash_prints_once_then_nothing(self):
        repo = self.started()

        failed = self.bash(repo, lambda: (repo / "src" / "new.py").write_text("x\n"), event="PostToolUseFailure")
        self.assertEqual(failed.returncode, 0, out(failed))
        self.assertNotIn(S1_STEM, out(failed))
        self.assertNotIn(N2_STEM, out(failed))

        first = self.bash(repo, lambda: None, tool_use_id="toolu_2")
        self.assert_reminded(first)

        for label, action in (("non-modifying", lambda: None),
                              ("modifying", lambda: (repo / "src" / "later.py").write_text("y\n"))):
            with self.subTest(further_call=label):
                further = self.bash(repo, action, tool_use_id=f"toolu_{label}")
                self.assert_silent(further)
                self.assertEqual(further.stderr, "")
        self.assertEqual(self.stop(repo).returncode, 2)

    def test_v4_failure_event_never_prints_s1_even_for_a_failing_edit_tool(self):
        repo = self.started()
        (repo / "src" / "a.py").write_text("a = 2\n")
        result = self.hook(repo, {"hook_event_name": "PostToolUseFailure", "session_id": "sessa", "tool_name": "Edit",
                                  "tool_input": {"file_path": str(repo / "src" / "a.py")}})
        self.assertNotIn(S1_STEM, out(result))
        self.assertNotIn(N2_STEM, out(result))
        self.assertNotIn("Traceback", out(result))


class TestMessages(ProgressCase):
    def changed_session(self, kind="none"):
        repo = self.new_repo()
        head = self.head(repo)
        if kind == "own_filled":
            path = self.put(repo, NAME1, build(session="sessa", stamp=head, next_step=[("alpha work item", head, "none")]))
            run_git(repo, "add", "--", self.rel(repo, path))
            self.commit(repo, "progress")
        self.assertEqual(self.start(repo).returncode, 0)
        self.mark_changed(repo)
        return repo

    def test_v5_s4_stop_for_a_changed_session_without_progress_names_progress_md(self):
        repo = self.changed_session()
        result = self.stop(repo)
        self.assertEqual(result.returncode, 2, out(result))
        self.assertIn(S4, result.stderr)
        self.assertNotIn(OLD_POINTER, out(result))
        self.assertIn(".harness/instructions/progress.md", result.stderr)

    def test_v5_s3_precompact_reminder_ends_with_progress_md_pointer(self):
        for kind in ("none", "own_filled"):
            with self.subTest(progress=kind):
                repo = self.changed_session(kind)
                result = self.precompact(repo)
                self.assertEqual(result.returncode, 0, out(result))
                self.assertIn(S3, result.stdout)
                self.assertNotIn(OLD_POINTER, out(result))
                self.assertIn(".harness/instructions/progress.md", result.stdout)

    def test_v5_s2_gh_pr_create_gate_for_a_changed_session_without_progress_names_progress_md(self):
        repo = self.new_repo()
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        bare = Path(tmp.name) / "origin.git"
        subprocess.run(["git", "init", "-q", "--bare", str(bare)], check=True)
        base = self.branch(repo)
        run_git(repo, "remote", "add", "origin", str(bare))
        run_git(repo, "push", "-q", "-u", "origin", base)
        run_git(repo, "checkout", "-q", "-b", "feat")
        run_git(repo, "push", "-q", "-u", "origin", "feat")
        self.assertEqual(self.start(repo).returncode, 0)
        self.mark_changed(repo)

        result = self.hook(repo, {"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_use_id": "toolu_gate",
                                  "session_id": "sessa", "tool_input": {"command": "gh pr create --fill"}})

        self.assertEqual(result.returncode, 2, out(result))
        self.assertTrue(result.stderr.startswith("harness: gh pr create blocked:"), result.stderr)
        self.assertIn(S2, result.stderr)
        self.assertNotIn(OLD_POINTER, out(result))


class TestHookErrors(ProgressCase):
    def started_and_marked(self):
        repo = self.new_repo()
        self.assertEqual(self.start(repo).returncode, 0)
        marked = self.bash(repo, lambda: (repo / "src" / "new.py").write_text("x\n"), event="PostToolUseFailure")
        self.assertEqual(marked.returncode, 0, out(marked))
        return repo

    @unittest.skipIf(hasattr(os, "geteuid") and os.geteuid() == 0, "permission bits do not bind root")
    def test_v10_read_only_change_dir_after_marking_gives_exit_0_no_s1_no_traceback_and_stop_still_blocks(self):
        repo = self.started_and_marked()
        change_dir = self.sessions_dir(repo) / "progress-sessa.d"
        self.assertTrue(change_dir.is_dir())
        self.addCleanup(os.chmod, change_dir, 0o700)
        os.chmod(change_dir, stat.S_IRUSR | stat.S_IXUSR)

        (repo / "src" / "a.py").write_text("a = 2\n")
        result = self.post(repo, repo / "src" / "a.py", tool="Edit")

        self.assertEqual(result.returncode, 0, out(result))
        self.assertNotIn(S1_STEM, out(result))
        self.assertNotIn(N2_STEM, out(result))
        self.assertNotIn("Traceback", out(result))
        self.assertEqual(self.stop(repo).returncode, 2)

    def test_v10_git_unavailable_prints_no_s1(self):
        repo = self.new_repo()
        env = self.env(PATH=self.empty_path_dir())
        self.assertEqual(self.start(repo, env=env).returncode, 0)
        (repo / "src" / "a.py").write_text("a = 2\n")
        result = self.post(repo, repo / "src" / "a.py", tool="Edit", env=env)
        self.assertNotIn(S1_STEM, out(result))
        self.assertNotIn(N2_STEM, out(result))
        self.assertNotIn("Traceback", out(result))
        again = self.bash(repo, lambda: (repo / "src" / "b.py").write_text("b = 2\n"), env=env)
        self.assertNotIn(S1_STEM, out(again))
        self.assertNotIn(N2_STEM, out(again))
        self.assertNotIn("Traceback", out(again))


class TestVerifyRulesMessages(InstallerTestCase):
    def installed(self):
        repo = self.make_repo()
        result = run_installer("install", str(repo), "--no-ci")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return repo

    def verify(self, repo):
        return self.run_verify_rules(repo)

    def track(self, repo, *paths):
        run_git(repo, "add", "-f", "--", *paths)

    def break_index(self, repo):
        notes = repo / "agent-docs" / "notes"
        notes.mkdir(parents=True)
        (notes / "1234567890abcdef-x.md").write_text("# X\n")
        self.track(repo, "agent-docs/notes")

    def break_synced(self, repo):
        tag = "synced" " id: aabbccddeeff, version: 2, count: 2"
        (repo / "a.py").write_text(f"# {tag}\nx = 1\n")
        (repo / "b.py").write_text(f"# {tag}\ny = 2\n")
        directory = repo / "agent-docs" / "synced-comments"
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "aabbccddeeff.md").write_text(
            "---\nversion: 1\ncount: 3\ncode_hash: 0000\n---\n\n# Content\nshared\n\n# Version Log\n## v1 Log\n- Initial creation.\n"
        )
        self.track(repo, "a.py", "b.py", "agent-docs/synced-comments/aabbccddeeff.md")

    def break_try_n_fail(self, repo):
        directory = repo / "agent-docs" / "try-n-fail"
        name = "0123456789abcdef-cache-warmup.md"
        (directory / name).write_text("# Cache warmup\n\n## Goal\nx\n")
        (directory / "index.md").write_text(f"File: {name}\nSummary: s\nRelated Files: none\nRelated Symbols: none\n")
        self.track(repo, "agent-docs/try-n-fail")

    def break_todos(self, repo):
        directory = repo / "agent-docs" / "todos"
        name = "0123456789abcdef-add-flag.md"
        (directory / name).write_text("# Add flag\n\n## Goal\nx\n")
        (directory / "index.md").write_text(f"File: {name}\nSummary: s\nRelated Files: none\nRelated Symbols: none\n")
        self.track(repo, "agent-docs/todos")

    def break_progress_format(self, repo):
        (repo / "agent-docs" / "progress").mkdir(parents=True, exist_ok=True)
        (repo / "agent-docs" / "progress" / "0123456789abcdef-bad.md").write_text("# Bad\n")
        self.track(repo, "agent-docs/progress/0123456789abcdef-bad.md")

    def break_progress_secret(self, repo):
        text = build(session="sessa", changes="- used key AKIAIOSFODNN7ABCDEFG here")
        (repo / "agent-docs" / "progress").mkdir(parents=True, exist_ok=True)
        (repo / "agent-docs" / "progress" / "0123456789abcdef-secret.md").write_text(text)
        self.track(repo, "agent-docs/progress/0123456789abcdef-secret.md")

    GROUPS = {
        "index": ("break_index", RULE_FILE_ORDER[0:1]),
        "synced": ("break_synced", RULE_FILE_ORDER[1:2]),
        "try_n_fail": ("break_try_n_fail", RULE_FILE_ORDER[2:3]),
        "todos": ("break_todos", RULE_FILE_ORDER[3:4]),
        "progress_format": ("break_progress_format", RULE_FILE_ORDER[4:5]),
        "progress_secret": ("break_progress_secret", RULE_FILE_ORDER[4:5]),
    }

    def assert_layout(self, stderr, files):
        self.assertTrue(stderr.endswith("\n"), repr(stderr))
        lines = stderr[:-1].split("\n")
        self.assertEqual(lines[0], "harness rule violations found:")
        self.assertEqual(lines[1], "")
        errors = lines[2:-3]
        self.assertTrue(errors, stderr)
        self.assertTrue(all(line.startswith("  - ") for line in errors), stderr)
        self.assertEqual(lines[-3], "")
        self.assertEqual(lines[-2], "Rule files: " + ", ".join(files))
        self.assertEqual(lines[-1], f"{len(errors)} violation(s). Commit blocked.")
        self.assertEqual(stderr.count("Rule files:"), 1)

    def test_v7_clean_repo_exits_0_with_empty_output(self):
        repo = self.installed()
        result = self.verify(repo)
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, "", ""))

    def test_v7_each_violated_group_alone_names_only_its_file(self):
        for label, (method, files) in self.GROUPS.items():
            with self.subTest(group=label):
                repo = self.installed()
                getattr(self, method)(repo)
                result = self.verify(repo)
                self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                self.assert_layout(result.stderr, files)

    def test_v7_all_five_groups_list_every_file_once_in_fixed_order(self):
        repo = self.installed()
        for method in ("break_index", "break_synced", "break_try_n_fail", "break_todos", "break_progress_format"):
            getattr(self, method)(repo)
        result = self.verify(repo)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assert_layout(result.stderr, RULE_FILE_ORDER)
        for path in RULE_FILE_ORDER:
            self.assertEqual(result.stderr.count(path), 1, path)

    def test_v7_progress_secret_group_still_names_progress_md_beside_other_groups(self):
        repo = self.installed()
        self.break_todos(repo)
        self.break_progress_secret(repo)
        result = self.verify(repo)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assert_layout(result.stderr, [RULE_FILE_ORDER[3], RULE_FILE_ORDER[4]])

    def test_v7_pre_commit_blocks_a_todo_without_next_step_and_names_todos_md_before_the_count(self):
        repo = self.installed()
        self.break_todos(repo)
        run_git(repo, "add", "-f", "agent-docs/todos")
        result = subprocess.run(["git", "-C", str(repo), "commit", "-m", "t"], capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        rule_line = f"Rule files: {INSTRUCTIONS}/todos.md"
        self.assertIn(rule_line, result.stderr)
        self.assertLess(result.stderr.index(rule_line), result.stderr.index("violation(s). Commit blocked."))


class TestMigration0410(InstallerTestCase):
    def sha(self, data):
        return hashlib.sha256(data).hexdigest()

    def install_0400(self):
        repo = self.install()
        manifest_path = repo / ".harness" / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        block_rel = f"{INSTRUCTIONS}/harness-block.md"
        block_path = repo / block_rel
        sha_scheme_matches = manifest["files"].get(block_rel) == self.sha(block_path.read_bytes())
        block_path.write_bytes(FIXTURE.read_bytes())
        for name in MOVED.values():
            (repo / INSTRUCTIONS / name).unlink()
            manifest["files"].pop(f"{INSTRUCTIONS}/{name}", None)
        if sha_scheme_matches:
            manifest["files"][block_rel] = self.sha(FIXTURE.read_bytes())
        manifest["version"] = "0.40.0"
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
        return repo, manifest_path

    def test_v6_update_from_0400_announces_0410_last_with_plan_lines_and_leaves_agents_md_alone(self):
        repo, manifest_path = self.install_0400()
        agents_before = (repo / "AGENTS.md").read_bytes()

        result = run_installer("update", str(repo), "--no-ci", "--no-commit", input="y\n" * 8, exact=True)

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        announced = re.findall(r"^migration (\d+\.\d+\.\d+):", result.stdout, re.MULTILINE)
        self.assertEqual(announced[-1], "0.42.0")
        self.assertEqual(announced, ["0.41.0", "0.42.0"])
        self.assertIn(f"migration 0.41.0: {S6_LABEL}", result.stdout)
        start = result.stdout.index("migration 0.41.0:")
        positions = []
        for line in S6_PLAN:
            self.assertIn(line, result.stdout[start:])
            positions.append(result.stdout.index(line, start))
        self.assertEqual(positions, sorted(positions))
        self.assertEqual((repo / "AGENTS.md").read_bytes(), agents_before)
        self.assertEqual(json.loads(manifest_path.read_text())["version"], "0.42.0")
        for name in MOVED.values():
            self.assertTrue((repo / INSTRUCTIONS / name).is_file(), name)
        block_headings = [h for h, _ in split_sections(read_block(repo))]
        self.assertEqual(block_headings, KEPT_HEADINGS)
        doctor = run_installer("doctor", str(repo))
        self.assertEqual(doctor.returncode, 0, doctor.stdout + doctor.stderr)

    def test_v6_dry_run_from_0400_changes_nothing_in_agents_md_or_instruction_files(self):
        repo, _ = self.install_0400()
        agents_before = (repo / "AGENTS.md").read_bytes()
        result = run_installer("update", str(repo), "--no-ci", "--dry-run", forbid_input=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual((repo / "AGENTS.md").read_bytes(), agents_before)
        self.assertIn(f"migration 0.41.0: {S6_LABEL}", result.stdout)


class TestDuplicateHeadings(InstallerTestCase):
    def review_items(self, stdout):
        if "== manual review ==\n" not in stdout:
            return []
        section = stdout.split("== manual review ==\n", 1)[1].split("\n== ", 1)[0]
        return [line[2:] for line in section.splitlines() if line.startswith("- ")]

    def test_v8_moved_rule_and_rule_files_headings_outside_the_block_are_flagged_other_heading_is_not(self):
        repo = self.make_repo()
        old_block = (
            "<!-- harness:begin 0.39.0 -->\n# Documentation Guide\n\nold full rule body\n\n"
            "## Principles\n\nold text\n<!-- harness:end -->\n"
        )
        (repo / "AGENTS.md").write_text(
            "# Local Rules\n\n## Progress Rule\n\nown\n\n## Rule Files\n\nown\n\n"
            "## Zebra Crossing Notes Unique 7731\n\nown\n\n" + old_block
        )

        result = run_installer("install", str(repo))

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        items = self.review_items(result.stdout)
        for title, flagged in (("Progress Rule", True), ("Rule Files", True),
                               ("Zebra Crossing Notes Unique 7731", False)):
            with self.subTest(heading=title):
                hits = [item for item in items if f"'{title}'" in item]
                self.assertEqual(bool(hits), flagged, result.stdout)


class TestWordingReplacements(InstallerTestCase):
    def installed_text(self, repo, name):
        return (repo / ".agents" / "skills" / name / "SKILL.md").read_text()

    def test_v9_no_moved_rule_is_said_to_live_in_agents_md_in_the_installed_tree_or_installer(self):
        repo = shared_install()
        roots = [repo / ".harness", repo / ".claude", repo / ".agents", repo / ".codex"]
        files = [repo / "AGENTS.md", INSTALLER]
        for root in roots:
            if root.exists():
                files += [p for p in root.rglob("*") if p.is_file() and ".running" not in p.parts]
        scanned = 0
        for path in files:
            try:
                text = path.read_text(errors="ignore")
            except OSError:
                continue
            scanned += 1
            with self.subTest(file=str(path.name)):
                self.assertIsNone(MOVED_REGEX.search(text))
        self.assertGreater(scanned, 20)

    def test_v9_continue_on_skill_points_at_progress_md(self):
        text = self.installed_text(shared_install(), "continue-on")
        self.assertIn("(`.harness/instructions/progress.md`)", text)
        self.assertNotIn("(Progress Rule in `AGENTS.md`)", text)

    def test_v9_test_audit_skill_points_at_todos_md(self):
        text = self.installed_text(shared_install(), "test-audit")
        self.assertIn("following `.harness/instructions/todos.md`:", text)
        self.assertNotIn("following the Todo Rule in `AGENTS.md`:", text)

    def test_v9_rearrange_docs_skill_points_at_the_rule_files(self):
        text = self.installed_text(shared_install(), "rearrange-docs")
        self.assertIn(
            "the rules live in `.harness/instructions/` (`harness-block.md` and the rule files it lists), manifest files;",
            text,
        )
        self.assertIn(
            "under the Index & Staleness Management rule in `.harness/instructions/index-and-staleness.md`.",
            text,
        )
        self.assertNotIn("the rules live in `.harness/instructions/harness-block.md`, a manifest file;", text)
        self.assertNotIn("under the Index & Staleness Management rule.", text)

    def test_v9_installer_handoff_template_points_at_the_rule_files(self):
        text = INSTALLER.read_text()
        self.assertIn("following the Try-n-Fail Rule in `.harness/instructions/try-n-fail.md`", text)
        self.assertIn(
            "under the Index & Staleness Management rule in `.harness/instructions/index-and-staleness.md`.", text
        )
        self.assertNotIn("following the Try-n-Fail Rule in `AGENTS.md`", text)
        self.assertNotIn("under the Index & Staleness Management rule.", text)

    def test_v9_readme_wording(self):
        text = (REPO_ROOT / "README.md").read_text()
        self.assertIn(
            "항상 읽는 규칙은 [`harness-block.md`](harness/instructions/harness-block.md)에 있습니다. "
            "hook이 위반을 잡는 progress, try-n-fail, todo, index/stale, 동기화 주석 규칙은 같은 디렉터리의 별도 파일에 있어 "
            "해당 작업 전에 읽고, 위반하면 hook 메시지가 그 파일을 알려 줍니다.",
            text,
        )
        self.assertNotIn("규칙 전문은 [`harness-block.md`](harness/instructions/harness-block.md)에 있습니다.", text)
        self.assertNotIn("파일을 바꾼 세션이 progress 없이 끝나려 하면 한 번 막음", text)


if __name__ == "__main__":
    unittest.main()

import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from test_installer import REPO_ROOT, run_git, run_installer
from test_hook_owned_progress import (LOGS_REL, PLACEHOLDER, PROGRESS_REL, S, SKELETON_NAME, TEMPLATE, HookCase,
                                      expected_skeleton, n2, s1, s8, valid_text)
from test_progress import NAME0, NAME1, NAME2, build, frontmatter, load_progress, out

BASE_0420 = "611e1f635fe547798a5a24512249cb2f0743f156"
NAME3 = "3333333333333333-third-task.md"
REC_TODO = "agent-docs/todos/0123456789abcdef-x.md"
REC_TODO_2 = "agent-docs/todos/0123456789abcdee-w.md"
REC_TNF = "agent-docs/try-n-fail/fedcba9876543210-y.md"
REC_IDX = "agent-docs/todos/index.md"
CODE_FINDING = ("record-only progress in a session that changed code; "
                "run any Edit to let the hook upgrade it, or write the full structure")
RECORD_ONLY_TEMPLATE = """---
session: {S}
kind: record-only
before: none
previous: none
branch: {branch}
---

# Record-only session

## Record

### Changes
{changes}

### User Requests
"""
NOT_CONTINUABLE = "not continuable: {path} is a record-only progress"
NO_PROGRESS = "no progress to continue"

_OLD_RELEASE = {}


def n3(label):
    return (f"harness: this session changed only records, so {label} was created as a record-only progress; "
            "the hook keeps its ### Changes and ### User Requests. Commit it with the work.")


def n4(label):
    return (f"harness: this session changed code, so {label} was turned into a full progress. "
            f"Read .harness/instructions/progress.md, replace every [harness-requires] in {label}, and commit it with the work.")


def expected_record_only(session, branch, paths):
    return (RECORD_ONLY_TEMPLATE.replace("{S}", session).replace("{branch}", branch)
            .replace("{changes}", "\n".join(f"- {p}" for p in paths)))


def record_only_file_text(session=S, before="none", branch="main", paths=(REC_TODO,), stamp=None, **drop):
    lines = ["---", f"session: {session}", "kind: record-only", f"before: {before}", "previous: none", f"branch: {branch}"]
    if stamp:
        lines.append(f"commit: {stamp}")
    lines += ["---", ""]
    if not drop.get("title"):
        lines += ["# Record-only session", ""]
    if not drop.get("record"):
        lines += ["## Record", ""]
    lines += ["### Changes"]
    if not drop.get("bullets"):
        lines += [f"- {p}" for p in paths]
    lines += [""]
    if drop.get("extra"):
        lines += ["### Commands", "- ran something", ""]
    if not drop.get("requests"):
        lines += ["### User Requests", ""]
    if drop.get("extra"):
        lines += ["## Appendix", "", "free text", ""]
    return "\n".join(lines)


def split_stamp(text):
    lines = text.split("\n")
    stamped = [i for i, line in enumerate(lines[:9]) if re.fullmatch(r"commit: [0-9a-f]{40}", line)]
    assert len(stamped) <= 1, lines[:9]
    for i in stamped:
        del lines[i]
    return lines


def old_release_source():
    if "source" not in _OLD_RELEASE:
        exists = subprocess.run(["git", "-C", str(REPO_ROOT), "cat-file", "-e", f"{BASE_0420}^{{commit}}"],
                                capture_output=True, text=True)
        if exists.returncode != 0:
            raise RuntimeError(f"commit {BASE_0420} is not available in this checkout")
        tmp = tempfile.TemporaryDirectory()
        _OLD_RELEASE["tmp"] = tmp
        source = Path(tmp.name)
        archive = subprocess.run(["git", "-C", str(REPO_ROOT), "archive", BASE_0420, "installer", "harness"],
                                 capture_output=True, check=True).stdout
        subprocess.run(["tar", "-x", "-C", str(source)], input=archive, check=True)
        _OLD_RELEASE["source"] = source
    return _OLD_RELEASE["source"]


class RecordCase(HookCase):
    def ready_repo(self, sid=S):
        repo = self.new_repo()
        for directory in ("todos", "try-n-fail"):
            index = repo / "agent-docs" / directory / "index.md"
            if not index.exists():
                index.parent.mkdir(parents=True, exist_ok=True)
                index.write_text("")
        run_git(repo, "add", "-A")
        self.commit(repo, "docs")
        self.own_marker(repo)
        self.assertEqual(self.start(repo, sid=sid).returncode, 0)
        return repo

    def changed_paths(self, repo, sid=S):
        path = self.change_dir(repo, sid) / "changed-paths"
        return path.read_text().splitlines() if path.is_file() else None

    def has_code(self, repo, sid=S):
        return (self.change_dir(repo, sid) / "code").exists()

    def own_progress(self, repo):
        return self.single_skeleton(repo)

    def assert_record_only(self, repo, path, paths, branch=None, before="none"):
        text = path.read_text()
        lines = split_stamp(text)
        expected = expected_record_only(S, branch or self.branch(repo), paths)
        cut = "\n### User Requests"
        self.assertIn(cut, "\n".join(lines))
        head = "\n".join(lines)
        pre = head[:head.rfind(cut)]
        self.assertEqual(frontmatter(path)["before"], before)
        pre_lines = pre.split("\n")
        pre_lines[3] = "before: none"
        self.assertEqual("\n".join(pre_lines), expected[:expected.rfind(cut)])
        tail = head[head.rfind(cut) + 1:].split("\n")
        self.assertEqual(tail[0], "### User Requests")
        for line in tail[1:]:
            self.assertTrue(line == "" or line.startswith("####") or line.startswith(">"), repr(line))

    def assert_upgraded(self, text, paths, branch):
        lines = split_stamp(text)
        self.assertNotIn("kind: record-only", lines)
        self.assertEqual(lines[:6], ["---", f"session: {S}", lines[2], "previous: none", f"branch: {branch}", "---"])
        self.assertTrue(lines[2] == "before: none" or lines[2].startswith(f"before: {LOGS_REL}/"), lines[2])
        body = "\n".join(lines)
        cut = "\n### User Requests"
        pre = body[:body.rfind(cut)]
        match = re.search(r"### Changes\n(.*?)\n\n### Commands\n", pre, re.S)
        self.assertIsNotNone(match, pre)
        self.assertEqual(sorted(match.group(1).split("\n")), sorted([f"- {p}" for p in paths] + [f"- {PLACEHOLDER}"]))
        canonical = pre[:match.start(1)] + f"- {PLACEHOLDER}" + pre[match.end(1):]
        canonical_lines = canonical.split("\n")
        canonical_lines[2] = "before: none"
        expected = (expected_skeleton(S, branch).replace("# [harness-requires] title of this session's work",
                                                         "# Record-only session"))
        self.assertEqual("\n".join(canonical_lines), expected[:expected.rfind(cut)])
        tail = body[body.rfind(cut) + 1:].split("\n")
        self.assertEqual(tail[0], "### User Requests")
        for line in tail[1:]:
            self.assertTrue(line == "" or line.startswith("####") or line.startswith(">"), repr(line))

    def git_shim_env(self, failing_word):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        real = shutil.which("git")
        shim = Path(tmp.name) / "git"
        shim.write_text(
            "#!/bin/sh\n"
            f'for a in "$@"; do\n  if [ "$a" = "{failing_word}" ]; then echo "fatal: injected failure" >&2; exit 128; fi\ndone\n'
            f'exec "{real}" "$@"\n')
        shim.chmod(0o755)
        return self.env(PATH=tmp.name + os.pathsep + os.environ.get("PATH", ""))

    def post_bash(self, repo, tool_use_id="toolu_1", sid=S, **kw):
        return self.hook(repo, {"session_id": sid, "tool_name": "Bash", "tool_use_id": tool_use_id,
                                "tool_input": {"command": "x"}, "hook_event_name": "PostToolUse"}, **kw)

    def pre_bash(self, repo, tool_use_id="toolu_1", sid=S, **kw):
        return self.hook(repo, {"session_id": sid, "tool_name": "Bash", "tool_use_id": tool_use_id,
                                "tool_input": {"command": "x"}, "hook_event_name": "PreToolUse"}, **kw)

    def write_rel(self, repo, rel, text=None):
        path = repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text if text is not None else f"changed {rel}\n")
        return path

    def commit_at(self, repo, paths, epoch, message="record"):
        run_git(repo, "add", "-f", "--", *paths)
        date = f"{epoch} +0000"
        env = self.env(GIT_COMMITTER_DATE=date, GIT_AUTHOR_DATE=date)
        result = subprocess.run(["git", "-C", str(repo), "commit", "-q", "--no-verify", "-m", message],
                                capture_output=True, text=True, env=env)
        self.assertEqual(result.returncode, 0, out(result))
        return self.head(repo)


class TestPathClassification(RecordCase):
    def test_edit_of_a_record_path_lists_it_and_sets_no_code_marker(self):
        repo = self.ready_repo()
        self.edit(repo, REC_TODO, tool="Edit")
        self.assertEqual(self.changed_paths(repo), [REC_TODO])
        self.assertFalse(self.has_code(repo))

    def test_repeated_and_out_of_order_edits_list_each_path_once_sorted_one_per_line(self):
        repo = self.ready_repo()
        for rel in ("src/b.py", REC_TNF, REC_TODO, REC_TNF, "src/b.py"):
            self.edit(repo, rel, tool="Edit")
        self.assertEqual(self.changed_paths(repo), [REC_TODO, REC_TNF, "src/b.py"])
        raw = (self.change_dir(repo) / "changed-paths").read_text()
        self.assertEqual(raw.strip("\n").split("\n"), [REC_TODO, REC_TNF, "src/b.py"])

    def test_bash_call_modifying_an_already_dirty_file_records_it_through_the_stat_signature(self):
        cases = (("tracked code", "src/a.py", True, True), ("untracked code", "src/dirty.py", False, True),
                 ("tracked record", REC_IDX, True, False), ("untracked record", REC_TODO, False, False))
        for label, rel, _tracked, is_code in cases:
            with self.subTest(case=label):
                repo = self.ready_repo()
                self.write_rel(repo, rel, "dirty before the call\n")
                path = repo / rel
                self.bash(repo, lambda: path.write_text(path.read_text() + "appended during the call, longer\n"), sid=S)
                self.assertEqual(self.changed_paths(repo), [rel])
                self.assertEqual(self.has_code(repo), is_code)

    def test_edit_of_a_code_path_lists_it_and_sets_the_code_marker(self):
        repo = self.ready_repo()
        self.edit(repo, "src/a.py", tool="Edit")
        self.assertEqual(self.changed_paths(repo), ["src/a.py"])
        self.assertTrue(self.has_code(repo))

    def test_edit_of_a_progress_or_progress_logs_path_sets_no_code_marker(self):
        for directory in ("progress", "progress-logs"):
            with self.subTest(directory=directory):
                repo = self.ready_repo()
                path = self.put(repo, NAME1, valid_text(S), directory=directory)
                run_git(repo, "add", "-A")
                self.commit(repo, "progress")
                path.write_text(valid_text(S, changes="- edited again"))
                self.post(repo, path, sid=S, tool="Edit")
                self.assertFalse(self.has_code(repo))

    def test_bash_call_changing_only_records_lists_them_and_sets_no_code_marker(self):
        repo = self.ready_repo()
        self.bash(repo, lambda: (self.write_rel(repo, REC_TODO), self.write_rel(repo, REC_TNF)), sid=S)
        self.assertEqual(self.changed_paths(repo), [REC_TODO, REC_TNF])
        self.assertFalse(self.has_code(repo))

    def test_bash_call_changing_code_lists_it_and_sets_the_code_marker(self):
        repo = self.ready_repo()
        self.bash(repo, lambda: self.write_rel(repo, "src/new.py"), sid=S)
        self.assertEqual(self.changed_paths(repo), ["src/new.py"])
        self.assertTrue(self.has_code(repo))

    def test_bash_call_changing_records_and_code_lists_both_sorted_and_sets_the_code_marker(self):
        repo = self.ready_repo()
        self.bash(repo, lambda: (self.write_rel(repo, "src/new.py"), self.write_rel(repo, REC_TODO)), sid=S)
        self.assertEqual(self.changed_paths(repo), [REC_TODO, "src/new.py"])
        self.assertTrue(self.has_code(repo))

    def test_bash_commit_of_record_files_moves_head_and_lists_the_committed_records_without_code(self):
        repo = self.ready_repo()

        def action():
            self.write_rel(repo, REC_TODO)
            run_git(repo, "add", "--", REC_TODO)
            self.commit(repo, "record only")

        self.bash(repo, action, sid=S)
        self.assertEqual(self.changed_paths(repo), [REC_TODO])
        self.assertFalse(self.has_code(repo))

    def test_bash_commit_that_includes_a_code_file_sets_the_code_marker(self):
        repo = self.ready_repo()

        def action():
            self.write_rel(repo, REC_TODO)
            self.write_rel(repo, "src/new.py")
            run_git(repo, "add", "--", REC_TODO, "src/new.py")
            self.commit(repo, "mixed")

        self.bash(repo, action, sid=S)
        self.assertEqual(self.changed_paths(repo), [REC_TODO, "src/new.py"])
        self.assertTrue(self.has_code(repo))

    def test_snapshot_in_the_0_42_0_hash_only_format_counts_a_record_change_as_code(self):
        source = old_release_source()
        old = self.make_repo()
        installed = subprocess.run([sys.executable, str(source / "installer" / "harness.py"), "install", str(old), "--no-ci"],
                                   capture_output=True, text=True)
        self.assertEqual(installed.returncode, 0, out(installed))
        (old / "src").mkdir()
        (old / "src" / "a.py").write_text("a = 1\n")
        run_git(old, "add", "-A")
        self.commit(old, "base")
        self.own_marker(old)
        self.assertEqual(self.start(old, sid=S).returncode, 0)
        self.pre_bash(old)
        snapshots = sorted(self.change_dir(old).glob("snap-*"))
        self.assertEqual(len(snapshots), 1, snapshots)

        repo = self.ready_repo()
        self.prompt(repo, "Record a todo", sid=S)
        self.change_dir(repo).mkdir(parents=True, exist_ok=True)
        (self.change_dir(repo) / snapshots[0].name).write_bytes(snapshots[0].read_bytes())
        self.write_rel(repo, REC_TODO)
        result = self.post_bash(repo)
        self.assertTrue(self.has_code(repo))
        progress = self.own_progress(repo)
        self.assertNotIn("kind: record-only", progress.read_text())
        self.assertIn(n2(self.rel(repo, progress)), result.stderr)
        self.assertNotIn("record-only progress", result.stderr)

    def test_git_diff_failure_while_classifying_a_moved_head_counts_the_change_as_code(self):
        repo = self.ready_repo()
        self.pre_bash(repo)
        self.write_rel(repo, REC_TODO)
        run_git(repo, "add", "--", REC_TODO)
        self.commit(repo, "record only")
        result = self.post_bash(repo, env=self.git_shim_env("diff"))
        self.assertNotIn("Traceback", out(result))
        self.assertTrue(self.has_code(repo))
        for path in self.progress_files(repo):
            self.assertNotIn("kind: record-only", path.read_text())
        self.assertNotIn("record-only progress", result.stderr)


class TestStateTransitions(RecordCase):
    def first_record(self, repo, rel=REC_TODO, prompt="Record a todo"):
        if prompt:
            self.prompt(repo, prompt, sid=S)
        return self.edit(repo, rel, tool="Write")

    def test_none_to_record_only_writes_the_exact_template_with_n3_and_exit_two(self):
        repo = self.ready_repo()
        result = self.first_record(repo)
        progress = self.own_progress(repo)
        self.assertEqual(result.returncode, 2, out(result))
        self.assertEqual(result.stderr.count(n3(self.rel(repo, progress))), 1, result.stderr)
        self.assertNotIn(n2(self.rel(repo, progress)), result.stderr)
        self.assertNotIn("Traceback", out(result))
        self.assertRegex(progress.name, SKELETON_NAME)
        self.assertEqual(frontmatter(progress)["kind"], "record-only")
        self.assert_record_only(repo, progress, [REC_TODO])
        self.assertIn("> Record a todo", progress.read_text().split("\n### User Requests")[-1])
        self.assertIn("skeleton", {p.name for p in self.change_dir(repo).iterdir()})

    def test_created_record_only_progress_passes_progress_check(self):
        repo = self.ready_repo()
        self.first_record(repo)
        checked = self.check(repo, self.rel(repo, self.own_progress(repo)))
        self.assertEqual(checked.returncode, 0, out(checked))

    def test_none_to_record_only_rotates_an_earlier_progress_and_sets_before(self):
        repo = self.new_repo()
        self.own_marker(repo)
        self.add_marker(repo, self.dead_pid())
        old_text = valid_text("sessz")
        old = self.put(repo, NAME1, old_text)
        self.commit_files(repo, old)
        self.start(repo, sid=S)
        result = self.first_record(repo)
        progress = self.own_progress(repo)
        self.assertEqual((repo / LOGS_REL / NAME1).read_text(), old_text)
        self.assertEqual(frontmatter(progress)["before"], f"{LOGS_REL}/{NAME1}")
        self.assertIn(n3(self.rel(repo, progress)), result.stderr)
        self.assert_record_only(repo, progress, [REC_TODO], before=f"{LOGS_REL}/{NAME1}")

    def test_refused_rotation_prints_s1_once_and_writes_no_record_only_file(self):
        repo = self.new_repo()
        self.own_marker(repo)
        self.add_marker(repo, 1)
        old_text = valid_text("sessz")
        old = self.put(repo, NAME1, old_text)
        self.commit_files(repo, old)
        self.start(repo, sid=S)
        first = self.first_record(repo)
        self.assertEqual(first.returncode, 2, out(first))
        self.assertEqual(first.stderr.count(s1()), 1, first.stderr)
        self.assertNotIn("was created", first.stderr)
        self.assertEqual(self.progress_files(repo), [old])
        self.assertEqual(old.read_text(), old_text)
        self.assertEqual(self.progress_files(repo, "progress-logs"), [])
        second = self.edit(repo, REC_TNF)
        self.assertEqual((second.returncode, second.stderr), (0, ""))
        self.assertEqual(self.progress_files(repo), [old])

    def test_record_only_to_record_only_with_a_new_path_syncs_changes_sorted_and_stays_silent(self):
        repo = self.ready_repo()
        self.first_record(repo, rel=REC_TNF)
        progress = self.own_progress(repo)
        result = self.edit(repo, REC_TODO, tool="Write")
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, "", ""))
        self.assertEqual(self.progress_files(repo), [progress])
        self.assert_record_only(repo, progress, [REC_TODO, REC_TNF])
        again = self.edit(repo, REC_IDX, tool="Edit")
        self.assertEqual((again.returncode, again.stderr), (0, ""))
        self.assert_record_only(repo, progress, sorted([REC_IDX, REC_TODO, REC_TNF]))
        checked = self.check(repo, self.rel(repo, progress))
        self.assertEqual(checked.returncode, 0, out(checked))

    def test_record_only_changes_never_list_the_progress_file_itself(self):
        repo = self.ready_repo()
        self.first_record(repo)
        progress = self.own_progress(repo)
        result = self.post(repo, progress, sid=S, tool="Edit")
        self.assertNotIn("Traceback", out(result))
        self.assert_record_only(repo, progress, [REC_TODO])

    def test_record_only_to_full_after_a_code_edit_writes_the_upgrade_with_n4_once(self):
        repo = self.ready_repo()
        self.first_record(repo)
        progress = self.own_progress(repo)
        self.edit(repo, REC_TNF)
        result = self.edit(repo, "src/a.py", tool="Edit")
        label = self.rel(repo, progress)
        self.assertEqual(result.returncode, 2, out(result))
        self.assertEqual(result.stderr.count(n4(label)), 1, result.stderr)
        self.assertNotIn("Traceback", out(result))
        self.assertEqual(self.progress_files(repo), [progress])
        self.assert_upgraded(progress.read_text(), [REC_TODO, REC_TNF], self.branch(repo))
        self.assertIn("> Record a todo", progress.read_text().split("\n### User Requests")[-1])
        stop = self.stop(repo, sid=S)
        self.assertEqual(stop.returncode, 2, out(stop))
        self.assertIn(s8(label), stop.stderr)

    def test_upgrade_happens_once_and_later_edits_leave_the_full_progress_unchanged(self):
        repo = self.ready_repo()
        self.first_record(repo)
        progress = self.own_progress(repo)
        self.edit(repo, "src/a.py", tool="Edit")
        upgraded = progress.read_bytes()
        for rel in ("src/b.py", REC_TNF, "agent-docs/todos/index.md"):
            with self.subTest(rel=rel):
                result = self.edit(repo, rel, tool="Edit")
                self.assertEqual((result.returncode, result.stdout, result.stderr), (0, "", ""))
                self.assertEqual(progress.read_bytes(), upgraded)

    def test_bash_code_change_also_upgrades_a_record_only_progress(self):
        repo = self.ready_repo()
        self.first_record(repo)
        progress = self.own_progress(repo)
        result = self.bash(repo, lambda: self.write_rel(repo, "src/new.py"), sid=S, tool_use_id="toolu_2")
        self.assertEqual(result.returncode, 2, out(result))
        self.assertEqual(result.stderr.count(n4(self.rel(repo, progress))), 1, result.stderr)
        self.assert_upgraded(progress.read_text(), [REC_TODO], self.branch(repo))

    def test_full_to_full_a_valid_own_progress_stays_byte_identical_for_record_and_code_edits(self):
        repo = self.new_repo()
        path = self.put(repo, NAME1, valid_text(S))
        self.commit_files(repo, path)
        self.own_marker(repo)
        self.start(repo, sid=S)
        original = path.read_bytes()
        for rel in (REC_TODO, "src/a.py"):
            with self.subTest(rel=rel):
                result = self.edit(repo, rel, tool="Edit")
                self.assertEqual((result.returncode, result.stderr), (0, ""))
                self.assertEqual(path.read_bytes(), original)
        self.assertEqual(self.progress_files(repo), [path])

    def test_none_to_skeleton_when_the_first_change_is_code_matches_the_unchanged_skeleton_flow(self):
        repo = self.ready_repo()
        self.prompt(repo, "Add a --sort flag to list", sid=S)
        result = self.edit(repo, "src/a.py", tool="Edit")
        skeleton = self.own_progress(repo)
        label = self.rel(repo, skeleton)
        self.assertEqual(result.returncode, 2, out(result))
        self.assertEqual(result.stderr.count(n2(label)), 1, result.stderr)
        self.assertNotIn("record-only", out(result))
        self.assert_skeleton_text(skeleton.read_text(), S, self.branch(repo))

    def test_record_edit_after_a_code_first_skeleton_leaves_the_skeleton_unchanged(self):
        repo = self.ready_repo()
        self.edit(repo, "src/a.py", tool="Edit")
        skeleton = self.own_progress(repo)
        before = skeleton.read_bytes()
        result = self.edit(repo, REC_TODO)
        self.assertEqual((result.returncode, result.stderr), (0, ""))
        self.assertEqual(skeleton.read_bytes(), before)
        self.assertEqual(self.progress_files(repo), [skeleton])


class TestFormatDecisionTable(RecordCase):
    def put_record_only(self, repo, **kw):
        path = self.put(repo, NAME1, record_only_file_text(**kw))
        return path

    def check_result(self, repo, path):
        return self.cli(repo, "check", self.rel(repo, path), session_env=S)

    def test_complete_record_only_passes(self):
        repo = self.ready_repo()
        path = self.put_record_only(repo)
        result = self.check_result(repo, path)
        self.assertEqual(result.returncode, 0, out(result))

    def test_changes_without_a_bullet_is_a_finding(self):
        repo = self.ready_repo()
        result = self.check_result(repo, self.put_record_only(repo, bullets=True))
        self.assertEqual(result.returncode, 1, out(result))
        self.assertIn("Changes", out(result))
        self.assertNotIn("Traceback", out(result))

    def test_missing_user_requests_is_a_finding(self):
        repo = self.ready_repo()
        result = self.check_result(repo, self.put_record_only(repo, requests=True))
        self.assertEqual(result.returncode, 1, out(result))
        self.assertIn("User Requests", out(result))

    def test_missing_title_is_a_finding(self):
        repo = self.ready_repo()
        result = self.check_result(repo, self.put_record_only(repo, title=True))
        self.assertEqual(result.returncode, 1, out(result))

    def test_missing_record_heading_is_a_finding(self):
        repo = self.ready_repo()
        result = self.check_result(repo, self.put_record_only(repo, record=True))
        self.assertEqual(result.returncode, 1, out(result))

    def test_extra_headings_are_allowed(self):
        repo = self.ready_repo()
        result = self.check_result(repo, self.put_record_only(repo, extra=True))
        self.assertEqual(result.returncode, 0, out(result))

    def test_record_only_in_a_session_with_the_code_marker_reports_the_exact_finding(self):
        repo = self.ready_repo()
        self.mark_changed(repo, sid=S)
        self.assertTrue(self.has_code(repo))
        path = self.put_record_only(repo)
        result = self.check_result(repo, path)
        self.assertEqual(result.returncode, 1, out(result))
        self.assertIn(CODE_FINDING, out(result))

    def test_record_only_without_the_code_marker_has_no_code_finding(self):
        repo = self.ready_repo()
        self.assertFalse(self.has_code(repo))
        result = self.check_result(repo, self.put_record_only(repo))
        self.assertNotIn(CODE_FINDING, out(result))

    def test_stop_with_a_committed_untouched_record_only_progress_exits_zero(self):
        repo = self.ready_repo()
        self.edit(repo, REC_TODO, tool="Write")
        progress = self.own_progress(repo)
        self.commit_files(repo, progress, repo / REC_TODO)
        result = self.stop(repo, sid=S)
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, "", ""))

    def test_pre_commit_blocks_a_record_only_progress_of_a_session_that_changed_code(self):
        repo = self.ready_repo()
        self.mark_changed(repo, sid=S)
        path = self.put_record_only(repo)
        run_git(repo, "add", "-A")
        result = self.git_commit(repo, self.clean_env(CLAUDE_CODE_SESSION_ID=S))
        self.assertNotEqual(result.returncode, 0, out(result))
        self.assertIn(CODE_FINDING, result.stderr)
        self.assertTrue(path.is_file())


class TestPreCommitSync(RecordCase):
    TODO_TEXT = "# Todo\n\n## Next Step\ndo it\n"
    TNF_TEXT = "# Cache warmup\n\n## Goal\nx\n\n## Attempts\n| a | b | c |\n\n## Revisit Condition\ny\n"

    def changes_bullets(self, text):
        match = re.search(r"### Changes\n(.*?)\n\n###", text, re.S)
        self.assertIsNotNone(match, text)
        return match.group(1).split("\n")

    def index_entry(self, rel):
        return f"File: {Path(rel).name}\nSummary: s\nRelated Files: none\nRelated Symbols: none\n"

    def write_valid_records(self, repo, with_tnf):
        self.write_rel(repo, REC_TODO, self.TODO_TEXT)
        self.write_rel(repo, REC_IDX, self.index_entry(REC_TODO))
        if with_tnf:
            self.write_rel(repo, REC_TNF, self.TNF_TEXT)
            self.write_rel(repo, "agent-docs/try-n-fail/index.md", self.index_entry(REC_TNF))

    def test_pre_commit_resyncs_changes_to_the_recorded_paths_and_stages_the_progress(self):
        repo = self.ready_repo()
        self.write_valid_records(repo, with_tnf=True)
        self.post(repo, repo / REC_TODO, sid=S, tool="Write")
        progress = self.own_progress(repo)
        (self.change_dir(repo) / "changed-paths").write_text(f"{REC_TODO}\n{REC_TNF}\n")
        run_git(repo, "add", "-A")
        self.assertEqual(self.changes_bullets(progress.read_text()), [f"- {REC_TODO}"])
        result = self.git_commit(repo, self.clean_env(CLAUDE_CODE_SESSION_ID=S))
        self.assertEqual(result.returncode, 0, out(result))
        committed = run_git(repo, "show", f"HEAD:{self.rel(repo, progress)}").stdout
        self.assertEqual(self.changes_bullets(committed), [f"- {REC_TODO}", f"- {REC_TNF}"])
        self.assertEqual(committed, progress.read_text())
        self.assertEqual(run_git(repo, "status", "--porcelain").stdout, "")

    def test_pre_commit_gate_passes_with_the_staged_record_only_progress_and_keeps_kind(self):
        repo = self.ready_repo()
        self.write_valid_records(repo, with_tnf=False)
        self.post(repo, repo / REC_TODO, sid=S, tool="Write")
        progress = self.own_progress(repo)
        run_git(repo, "add", "-A")
        result = self.git_commit(repo, self.clean_env(CLAUDE_CODE_SESSION_ID=S))
        self.assertEqual(result.returncode, 0, out(result))
        committed = run_git(repo, "show", f"HEAD:{self.rel(repo, progress)}").stdout
        self.assertIn("\nkind: record-only\n", committed)


class TestShowRecordOnly(RecordCase):
    def full_text(self, repo, session):
        head = self.head(repo)
        return build(session=session, stamp=head, next_step=[(f"{session} work item for next session", head, "none")])

    def assert_shows(self, result, session):
        self.assertEqual(result.returncode, 0, out(result))
        self.assertIn(f"session: {session}", result.stdout)
        self.assertNotIn("Traceback", out(result))

    def chain_repo(self, own=False, length=1):
        repo = self.new_repo()
        self.put(repo, NAME0, self.full_text(repo, "sess0"), directory="progress-logs")
        before = f"{LOGS_REL}/{NAME0}"
        paths = [f"{LOGS_REL}/{NAME0}"]
        names = [NAME1, NAME2]
        for i in range(length - 1):
            self.put(repo, names[i], record_only_file_text(session=f"sessr{i}", before=before), directory="progress-logs")
            before = f"{LOGS_REL}/{names[i]}"
            paths.append(before)
        top = "4444444444444444-top-task.md"
        self.put(repo, top, record_only_file_text(session=S if own else "sessb", before=before))
        paths.append(f"{PROGRESS_REL}/{top}")
        self.commit_at(repo, paths, 1_000_000_000)
        self.put(repo, NAME3, self.full_text(repo, "sessd"), directory="progress-logs")
        self.commit_at(repo, [f"{LOGS_REL}/{NAME3}"], 1_100_000_000, "newer decoy")
        return repo

    def test_record_only_candidate_is_replaced_by_the_full_progress_its_before_names(self):
        self.assert_shows(self.show(self.chain_repo(), "--session", S), "sess0")

    def test_own_record_only_progress_resolves_through_its_before_to_the_full_progress(self):
        self.assert_shows(self.show(self.chain_repo(own=True), "--session", S), "sess0")

    def test_chain_of_two_record_only_progress_files_is_followed_to_the_full_progress(self):
        self.assert_shows(self.show(self.chain_repo(length=2), "--session", S), "sess0")
        self.assert_shows(self.show(self.chain_repo(length=3), session_env=S), "sess0")

    def test_record_only_with_before_none_leaves_nothing_to_continue(self):
        repo = self.new_repo()
        path = self.put(repo, NAME1, record_only_file_text(session="sessb"))
        self.commit_at(repo, [self.rel(repo, path)], 1_000_000_000)
        result = self.show(repo, "--session", S)
        self.assertEqual(result.returncode, 1, out(result))
        self.assertIn(NO_PROGRESS, out(result))
        self.assertNotIn("Traceback", out(result))

    def test_explicit_record_only_path_is_not_continuable(self):
        for directory in ("progress", "progress-logs"):
            with self.subTest(directory=directory):
                repo = self.new_repo()
                self.put(repo, NAME1, record_only_file_text(session="sessb"), directory=directory)
                arg = f"agent-docs/{directory}/{NAME1}"
                result = self.show(repo, arg, "--session", S)
                self.assertEqual(result.returncode, 1, out(result))
                self.assertIn(NOT_CONTINUABLE.format(path=arg), out(result))
                self.assertNotIn("session: sessb", result.stdout)


class TestShowRetiredFallback(RecordCase):
    def full(self, repo, session):
        head = self.head(repo)
        return build(session=session, stamp=head, next_step=[(f"{session} next step item", head, "none")])

    def retired(self, repo, name, session, epoch, text=None):
        path = self.put(repo, name, text if text is not None else self.full(repo, session), directory="progress-logs")
        self.commit_at(repo, [self.rel(repo, path)], epoch)
        return path

    def assert_shows(self, result, session):
        self.assertEqual(result.returncode, 0, out(result))
        self.assertIn(f"session: {session}", result.stdout)
        self.assertNotIn("Traceback", out(result))

    def test_empty_progress_dir_with_one_retired_file_shows_it(self):
        repo = self.new_repo()
        self.retired(repo, NAME1, "sessr", 1_000_000_000)
        self.assert_shows(self.show(repo, "--session", S), "sessr")
        self.assert_shows(self.show(repo, session_env=S), "sessr")

    def test_newest_commit_wins_whatever_the_path_order(self):
        for newer in (NAME0, NAME1):
            with self.subTest(newer=newer):
                repo = self.new_repo()
                older = NAME1 if newer == NAME0 else NAME0
                self.retired(repo, older, "sesso", 1_000_000_000)
                self.retired(repo, newer, "sessn", 1_000_000_100)
                self.assert_shows(self.show(repo, "--session", S), "sessn")

    def test_commit_times_one_second_apart_pick_the_later_one(self):
        repo = self.new_repo()
        self.retired(repo, NAME0, "sesso", 1_000_000_000)
        self.retired(repo, NAME1, "sessn", 1_000_000_001)
        self.assert_shows(self.show(repo, "--session", S), "sessn")

    def test_equal_commit_times_pick_the_ascending_first_path(self):
        for order in ((NAME0, NAME1), (NAME1, NAME0)):
            with self.subTest(order=order):
                repo = self.new_repo()
                for name in order:
                    self.retired(repo, name, "sessa0" if name == NAME0 else "sessa1", 1_000_000_000)
                self.assert_shows(self.show(repo, "--session", S), "sessa0")

    def test_equal_commit_time_in_one_commit_picks_the_ascending_first_path(self):
        repo = self.new_repo()
        paths = []
        for name, session in ((NAME1, "sessa1"), (NAME0, "sessa0")):
            paths.append(self.rel(repo, self.put(repo, name, self.full(repo, session), directory="progress-logs")))
        self.commit_at(repo, paths, 1_000_000_000)
        self.assert_shows(self.show(repo, "--session", S), "sessa0")

    def test_the_last_commit_touching_a_file_decides_its_time(self):
        repo = self.new_repo()
        first = self.retired(repo, NAME1, "sess1", 1_000_000_000)
        self.retired(repo, NAME0, "sess0", 1_000_000_100)
        first.write_text(first.read_text() + "\n")
        self.commit_at(repo, [self.rel(repo, first)], 1_000_000_200, "touch")
        self.assert_shows(self.show(repo, "--session", S), "sess1")

    def test_newest_file_of_the_current_session_is_skipped(self):
        repo = self.new_repo()
        self.retired(repo, NAME0, "sesso", 1_000_000_000)
        self.retired(repo, NAME1, S, 1_000_000_100)
        self.assert_shows(self.show(repo, "--session", S), "sesso")
        self.assert_shows(self.show(repo, session_env=S), "sesso")

    def test_newest_record_only_file_is_skipped(self):
        repo = self.new_repo()
        self.retired(repo, NAME0, "sesso", 1_000_000_000)
        self.retired(repo, NAME1, "sessq", 1_000_000_100, text=record_only_file_text(session="sessq"))
        self.assert_shows(self.show(repo, "--session", S), "sesso")

    def test_untracked_newer_file_is_ignored(self):
        repo = self.new_repo()
        self.retired(repo, NAME0, "sesso", 1_000_000_000)
        self.put(repo, NAME1, self.full(repo, "sessu"), directory="progress-logs")
        self.assert_shows(self.show(repo, "--session", S), "sesso")

    def test_only_untracked_retired_files_leave_nothing_to_continue(self):
        repo = self.new_repo()
        self.put(repo, NAME1, self.full(repo, "sessu"), directory="progress-logs")
        result = self.show(repo, "--session", S)
        self.assertEqual(result.returncode, 1, out(result))
        self.assertIn(NO_PROGRESS, out(result))

    def test_no_retired_file_leaves_nothing_to_continue(self):
        repo = self.new_repo()
        result = self.show(repo, "--session", S)
        self.assertEqual(result.returncode, 1, out(result))
        self.assertIn(NO_PROGRESS, out(result))
        self.assertNotIn("Traceback", out(result))

    def test_only_own_or_record_only_retired_files_leave_nothing_to_continue(self):
        repo = self.new_repo()
        self.retired(repo, NAME0, S, 1_000_000_000)
        self.retired(repo, NAME1, "sessq", 1_000_000_100, text=record_only_file_text(session="sessq"))
        result = self.show(repo, "--session", S)
        self.assertEqual(result.returncode, 1, out(result))
        self.assertIn(NO_PROGRESS, out(result))

    def test_another_sessions_progress_in_progress_dir_wins_over_a_newer_retired_file(self):
        repo = self.new_repo()
        self.retired(repo, NAME0, "sessold", 1_000_000_000)
        current = self.put(repo, NAME2, self.full(repo, "sessb"))
        self.commit_at(repo, [self.rel(repo, current)], 1_000_000_050)
        self.retired(repo, NAME1, "sessnew", 1_000_000_100)
        self.assert_shows(self.show(repo, "--session", S), "sessb")

    def test_own_progress_without_a_before_falls_back_to_the_newest_retired_file(self):
        repo = self.new_repo()
        self.retired(repo, NAME0, "sessold", 1_000_000_000)
        own = self.put(repo, NAME2, self.full(repo, S))
        self.commit_at(repo, [self.rel(repo, own)], 1_000_000_050)
        self.assert_shows(self.show(repo, "--session", S), "sessold")


class TestFailureInjection(RecordCase):
    def test_marker_write_failure_exits_zero_without_traceback_and_keeps_the_session_modified(self):
        for marker in ("changed-paths", "code"):
            with self.subTest(marker=marker):
                repo = self.ready_repo()
                (self.change_dir(repo)).mkdir(parents=True, exist_ok=True)
                target = self.change_dir(repo) / marker
                if marker == "code":
                    target.symlink_to(self.change_dir(repo) / "missing-dir" / "code")
                else:
                    target.mkdir()
                rel = "src/a.py" if marker == "code" else REC_TODO
                result = self.edit(repo, rel, tool="Edit")
                self.assertEqual(result.returncode, 0, out(result))
                self.assertNotIn("Traceback", out(result))
                self.assertTrue((self.change_dir(repo) / "modified").is_file())
                if marker == "code":
                    target.unlink()
                else:
                    target.rmdir()
                self.edit(repo, "src/b.py" if marker == "code" else REC_TNF, tool="Edit")
                if marker == "code":
                    self.assertTrue(self.has_code(repo))
                else:
                    self.assertIn(REC_TNF, self.changed_paths(repo))

    def test_record_only_write_failure_exits_zero_with_no_message(self):
        if os.geteuid() == 0:
            self.skipTest("directory permissions do not bind root")
        repo = self.ready_repo()
        directory = repo / PROGRESS_REL
        directory.mkdir(parents=True, exist_ok=True)
        directory.chmod(0o555)
        self.addCleanup(directory.chmod, 0o755)
        result = self.edit(repo, REC_TODO, tool="Write")
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, "", ""))
        self.assertEqual(self.progress_files(repo), [])

    def test_git_missing_creates_no_progress_and_never_crashes(self):
        repo = self.ready_repo()
        env = self.env(PATH=self.empty_path_dir())
        for label, call in (
            ("edit record", lambda: self.edit(repo, REC_TODO, tool="Write", env=env)),
            ("edit code", lambda: self.edit(repo, "src/a.py", tool="Edit", env=env)),
            ("bash", lambda: self.bash(repo, lambda: self.write_rel(repo, "src/n.py"), sid=S, env=env)),
        ):
            with self.subTest(call=label):
                result = call()
                self.assertEqual(result.returncode, 0, out(result))
                self.assertNotIn("Traceback", out(result))
                self.assertNotIn("record-only progress", out(result))
        self.assertEqual(self.progress_files(repo), [])

    def test_upgrade_input_without_the_record_heading_is_returned_unchanged(self):
        progress = load_progress()
        text = record_only_file_text(record=True)
        self.assertNotIn("## Record", text)
        self.assertEqual(progress.upgrade_record_only(text), text)

    def test_hook_leaves_a_record_only_progress_without_the_record_heading_unchanged_and_check_reports_it(self):
        repo = self.ready_repo()
        path = self.put(repo, NAME1, record_only_file_text(record=True))
        run_git(repo, "add", "-A")
        self.commit(repo, "progress")
        before = path.read_bytes()
        result = self.edit(repo, "src/a.py", tool="Edit")
        self.assertNotIn("Traceback", out(result))
        self.assertIn(result.returncode, (0, 2))
        self.assertEqual(path.read_bytes(), before)
        checked = self.cli(repo, "check", self.rel(repo, path), session_env=S)
        self.assertEqual(checked.returncode, 1, out(checked))
        self.assertNotIn("Traceback", out(checked))


class TestLibrarySignatures(RecordCase):
    def test_record_only_constant_and_marker_paths(self):
        progress = load_progress()
        self.assertEqual(progress.RECORD_ONLY, "record-only")
        repo = self.ready_repo()
        sessions = repo / ".harness" / "sessions" / f"progress-{S}.d"
        self.assertEqual(os.path.realpath(progress.changed_paths_file(repo, S)), os.path.realpath(sessions / "changed-paths"))
        self.assertEqual(os.path.realpath(progress.code_marker(repo, S)), os.path.realpath(sessions / "code"))

    def test_sync_changes_returns_a_full_progress_unchanged(self):
        progress = load_progress()
        text = valid_text(S)
        self.assertEqual(progress.sync_changes(text, [REC_TODO]), text)
        skeleton = expected_skeleton(S, "main")
        self.assertEqual(progress.sync_changes(skeleton, [REC_TODO]), skeleton)


class TestPostToolUseTiming(RecordCase):
    def test_bash_call_with_300_new_files_finishes_within_one_and_a_half_seconds(self):
        repo = self.ready_repo()
        self.pre_bash(repo)
        for i in range(300):
            (repo / "src" / f"gen_{i:03d}.py").write_text(f"v = {i}\n")
        started = time.perf_counter()
        result = self.post_bash(repo)
        elapsed = time.perf_counter() - started
        self.assertNotIn("Traceback", out(result))
        self.assertEqual(len(self.changed_paths(repo)), 300)
        self.assertTrue(self.has_code(repo))
        self.assertLessEqual(elapsed, 1.5)


class TestConfiguredDocsRootClassification(RecordCase):
    def configured_repo(self):
        repo = self.new_repo()
        (repo / ".harness" / "config.json").write_text(json.dumps({"docs_root": "docs/agent"}))
        for directory in ("progress", "progress-logs", "todos"):
            keep = repo / "docs" / "agent" / directory / ".gitkeep"
            keep.parent.mkdir(parents=True, exist_ok=True)
            keep.write_text("")
        run_git(repo, "add", "-A")
        self.commit(repo, "docs root")
        self.own_marker(repo)
        self.assertEqual(self.start(repo, sid=S).returncode, 0)
        return repo

    def test_record_under_the_configured_docs_root_gets_a_record_only_progress_there(self):
        repo = self.configured_repo()
        rec = "docs/agent/todos/0123456789abcdef-x.md"
        result = self.edit(repo, rec, tool="Write")
        self.assertEqual(result.returncode, 2, out(result))
        files = sorted((repo / "docs" / "agent" / "progress").glob("*.md"))
        self.assertEqual(len(files), 1, files)
        label = self.rel(repo, files[0])
        self.assertIn(n3(label), result.stderr)
        self.assertEqual(frontmatter(files[0])["kind"], "record-only")
        self.assertIn(f"- {rec}", files[0].read_text())
        self.assertFalse(self.has_code(repo))
        self.assertEqual(self.progress_files(repo), [])

    def test_default_layout_record_path_counts_as_code_when_docs_root_is_configured(self):
        repo = self.configured_repo()
        result = self.edit(repo, REC_TODO, tool="Write")
        self.assertEqual(result.returncode, 2, out(result))
        self.assertTrue(self.has_code(repo))
        files = sorted((repo / "docs" / "agent" / "progress").glob("*.md"))
        self.assertEqual(len(files), 1, files)
        self.assertNotIn("kind: record-only", files[0].read_text())
        self.assertIn(n2(self.rel(repo, files[0])), result.stderr)


if __name__ == "__main__":
    unittest.main()

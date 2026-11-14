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
from test_progress import NAME0, NAME1, NAME2, ProgressCase, build, frontmatter, load_progress, out, sized
from text_checks import text_test
from test_update_commit import UpdateCommitCase

S = "sessa"
UNKNOWN = "26664246-d290-44aa-8b2f-9bef3d42fabf"
PROGRESS_REL = "agent-docs/progress"
LOGS_REL = "agent-docs/progress-logs"
RULE_FILE = ".harness/instructions/progress.md"
PLACEHOLDER = "[harness-requires]"
PLACEHOLDER_FINDING = "unfilled placeholder [harness-requires]; replace it with content"
BASE_0410 = "6e77d1a234f20cc21dd58109bfd4e1d67171f090"
SKELETON_NAME = re.compile(r"^[0-9a-f]{16}-[a-z0-9]+(-[a-z0-9]+)*\.md$")

TEMPLATE = """---
session: {S}
before: none
previous: none
branch: {branch}
---

# [harness-requires] title of this session's work

## Next Session

### State
- [harness-requires] what is done and verified
  - files: none

### Next Step
- [harness-requires] what the next session does first
  - files: none

### Constraints
- none: [harness-requires] quote user constraints from ### User Requests with `  - source:`, or state that there are none

### Verify
- [harness-requires] commands that re-check the state
  - files: none

### Dead Ends
- none: [harness-requires] failed approaches, or state that there are none

### Related
- none: [harness-requires] records the next session needs, or state that there are none

## Record

### Changes
- [harness-requires]

### Commands
- [harness-requires]

### Failed Attempts
| attempt | failure evidence | cause |
| --- | --- | --- |

### Sources
- [harness-requires]

### User Requests
"""

S9 = [
    "progress hook: a progress written with an unknown session id gets this session's id",
    "progress hook: the first project change creates the session's progress with [harness-requires] placeholders",
    "progress entries: `  - files:` alone is enough; an entry is stale only when a listed file changed after the commit that recorded it",
    "pre-commit: a Claude Code commit in a session that changed the project needs its progress staged",
    "no data is migrated; AGENTS.md is unchanged",
]


def n1(session, label, value):
    shown = value if value else "(empty)"
    return f"harness: set `session: {session}` in {label}; `{shown}` is not a session of this checkout."


def n2(label):
    return (f"harness: this session changed the project and had no progress, so {label} was created. "
            f"Read .harness/instructions/progress.md, replace every [harness-requires] in {label}, and commit it with the work.")


def s1():
    return ("harness: this session changed the project and has no progress yet. "
            f"Read .harness/instructions/progress.md, then write {PROGRESS_REL}/<16-hex-id>-<kebab-name>.md "
            "so it is committed with the work.")


def s8(label):
    return f"harness: {label} still holds [harness-requires] placeholders. Replace them following .harness/instructions/progress.md before stopping."


def g1(session):
    return (f"session {session} changed the project but no progress in {PROGRESS_REL}/ or {LOGS_REL}/ "
            f"has `session: {session}`; write one and stage it with this commit")


def g2(label, session):
    return f"{label}: progress of session {session} is not staged with this commit; run `git add {label}`"


def files_only(text):
    return re.sub(r"  - commit: [0-9a-f]+; files:", "  - files:", text)


def valid_text(session, changes="- edited the parser", **kw):
    return files_only(build(session=session, next_step=[("alpha work item", "a" * 40, "none")], changes=changes, **kw))


def expected_skeleton(session, branch):
    return TEMPLATE.replace("{S}", session).replace("{branch}", branch)


def status_pattern(status):
    return re.escape(status) + r"(?![0-9a-f])"


def stderr_has_traceback(result):
    return "Traceback" in result.stdout or "Traceback" in result.stderr


class HookCase(ProgressCase):
    def clean_env(self, **extra):
        env = self.env()
        env.pop("HARNESS_UPDATE_COMMIT", None)
        env.update(extra)
        return env

    def edit(self, repo, rel, sid=S, tool="Edit", **kw):
        path = repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"changed {rel}\n")
        return self.post(repo, path, sid=sid, tool=tool, **kw)

    def own_marker(self, repo):
        self.add_marker(repo, os.getpid())

    def progress_files(self, repo, directory="progress"):
        folder = repo / "agent-docs" / directory
        return sorted(p for p in folder.glob("*.md")) if folder.is_dir() else []

    def change_dir(self, repo, sid=S):
        return self.sessions_dir(repo) / f"progress-{sid}.d"

    def commit_files(self, repo, *paths, message="record"):
        run_git(repo, "add", "--", *[self.rel(repo, p) for p in paths])
        return self.commit(repo, message)

    def git_commit(self, repo, env, message="work"):
        return subprocess.run(["git", "-C", str(repo), "commit", "-q", "-m", message],
                              capture_output=True, text=True, env=env)

    def session_repo(self, sid=S):
        repo = self.new_repo()
        self.own_marker(repo)
        self.assertEqual(self.start(repo, sid=sid).returncode, 0)
        return repo

    def changed_session(self, sid=S):
        repo = self.session_repo(sid)
        self.mark_changed(repo, sid=sid)
        return repo

    def assert_skeleton_text(self, text, session, branch):
        expected = expected_skeleton(session, branch)
        cut = "\n### User Requests"
        self.assertIn(cut, text)
        actual_pre = text[:text.rfind(cut)]
        actual_tail = text[text.rfind(cut) + 1:]
        expected_pre = expected[:expected.rfind(cut)]
        lines = actual_pre.split("\n")
        stamped = [i for i, line in enumerate(lines[:8]) if re.fullmatch(r"commit: [0-9a-f]{40}", line)]
        self.assertLessEqual(len(stamped), 1, lines[:8])
        for i in stamped:
            del lines[i]
        self.assertTrue(lines[2] == "before: none" or lines[2].startswith(f"before: {LOGS_REL}/"), lines[2])
        lines[2] = "before: none"
        self.assertEqual("\n".join(lines), expected_pre)
        tail_lines = actual_tail.split("\n")
        self.assertEqual(tail_lines[0], "### User Requests")
        for line in tail_lines[1:]:
            self.assertTrue(line == "" or line.startswith("####") or line.startswith(">"), repr(line))

    def single_skeleton(self, repo):
        files = self.progress_files(repo)
        self.assertEqual(len(files), 1, files)
        return files[0]


class TestLibraryUnits(HookCase):
    def test_constants_match_the_signatures(self):
        progress = load_progress()
        self.assertEqual(progress.UNCOMMITTED, "0" * 40)
        self.assertEqual(progress.PLACEHOLDER, PLACEHOLDER)

    def test_skeleton_text_equals_the_template_for_each_session_and_branch(self):
        progress = load_progress()
        for session, branch in ((S, "main"), (UNKNOWN, "feature/add-x"), ("s", "Doggy-Footprint/utility")):
            with self.subTest(session=session, branch=branch):
                self.assertEqual(progress.skeleton(session, branch).rstrip("\n"),
                                 expected_skeleton(session, branch).rstrip("\n"))

    def test_skeleton_name_variants(self):
        progress = load_progress()
        cases = (
            ("sort flag prompt", "Add a --sort flag to list", "add-a-sort-flag-to"),
            ("korean only", "한글만 있는 요청", "session"),
            ("none", None, "session"),
            ("empty", "", "session"),
            ("only five runs and lowercase", "ONE two_three Four five SIX seven", "one-two-three-four-five"),
            ("fewer than five runs", "Fix v2 bug", "fix-v2-bug"),
            ("mixed scripts keep ascii runs", "한글 abc 그리고 def", "abc-def"),
        )
        for label, prompt, slug in cases:
            with self.subTest(case=label):
                name = progress.skeleton_name(prompt)
                stem = name[:-3] if name.endswith(".md") else name
                self.assertRegex(stem, r"^[0-9a-f]{16}-")
                self.assertEqual(stem[17:], slug)
                self.assertRegex(stem + ".md", SKELETON_NAME)

    def test_skeleton_name_ids_differ_between_calls(self):
        progress = load_progress()
        names = {progress.skeleton_name("same prompt")[:16] for _ in range(8)}
        self.assertGreater(len(names), 1)

    def test_session_known_state_file_head_owned_and_unknown(self):
        progress = load_progress()
        repo = self.new_repo()
        self.assertFalse(progress.session_known(repo, UNKNOWN))
        self.start(repo, sid="sessv")
        self.assertTrue(progress.session_known(repo, "sessv"))
        owned = self.put(repo, NAME0, valid_text("sessh"), directory="progress-logs")
        self.assertFalse(progress.session_known(repo, "sessh"))
        self.commit_files(repo, owned)
        self.assertTrue(progress.session_known(repo, "sessh"))
        progress_dir = self.put(repo, NAME1, valid_text("sessp"))
        self.commit_files(repo, progress_dir)
        self.assertTrue(progress.session_known(repo, "sessp"))
        self.put(repo, NAME2, valid_text("sessu"))
        self.assertFalse(progress.session_known(repo, "sessu"))

    def test_line_commits_uncommitted_for_a_path_not_in_head_and_per_line_for_committed(self):
        progress = load_progress()
        repo = self.new_repo()
        path = self.put(repo, NAME1, "one\ntwo\nthree\n")
        untracked = progress.line_commits(repo, path)
        self.assertEqual(untracked, {1: "0" * 40, 2: "0" * 40, 3: "0" * 40})
        first = self.commit_files(repo, path)
        path.write_text("one\nTWO\nthree\n")
        mixed = progress.line_commits(repo, path)
        self.assertEqual(mixed, {1: first, 2: "0" * 40, 3: first})

    def test_line_commits_is_none_when_git_fails(self):
        progress = load_progress()
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            (folder / "f.md").write_text("x\n")
            self.assertIsNone(progress.line_commits(folder, folder / "f.md"))


class TestClaim(HookCase):
    def claim_repo(self, kind, in_head=False):
        repo = self.new_repo()
        self.own_marker(repo)
        value = {"unknown": UNKNOWN, "auto": "auto", "empty": "", "state": "sessv", "head_owned": "sessh", "equal": S}[kind]
        if kind == "state":
            self.assertEqual(self.start(repo, sid="sessv").returncode, 0)
        if kind == "head_owned":
            owned = self.put(repo, NAME0, valid_text("sessh"), directory="progress-logs")
            self.commit_files(repo, owned)
        self.assertEqual(self.start(repo, sid=S).returncode, 0)
        text = valid_text(value).replace("session: \n", "session:\n")
        path = self.put(repo, NAME1, text)
        if in_head:
            self.commit_files(repo, path)
            text = text.replace("- edited the parser", "- edited the parser again")
            path.write_text(text)
        return repo, path, text, value

    def test_r1_to_r3_post_tool_use_claims_unknown_auto_and_empty_with_the_exact_notice(self):
        for kind in ("unknown", "auto", "empty"):
            with self.subTest(value=kind):
                repo, path, _, value = self.claim_repo(kind)
                result = self.post(repo, path, sid=S)
                self.assertNotIn("Traceback", out(result))
                self.assertEqual(result.returncode, 2, out(result))
                self.assertEqual(frontmatter(path)["session"], S)
                self.assertIn(n1(S, self.rel(repo, path), value), out(result))
                self.assertEqual(out(result).count(n1(S, self.rel(repo, path), value)), 1)

    def test_r4_r5_r8_post_tool_use_leaves_known_and_own_values_byte_identical(self):
        for kind in ("state", "head_owned", "equal"):
            with self.subTest(value=kind):
                repo, path, text, value = self.claim_repo(kind)
                result = self.post(repo, path, sid=S)
                self.assertNotIn("Traceback", out(result))
                self.assertNotIn("is not a session of this checkout", out(result))
                self.assertEqual(frontmatter(path)["session"], S if kind == "equal" else value)

    def test_r6_r7_post_tool_use_leaves_paths_in_head_byte_identical(self):
        for kind in ("unknown", "auto", "empty"):
            with self.subTest(value=kind):
                repo, path, text, value = self.claim_repo(kind, in_head=True)
                result = self.post(repo, path, sid=S)
                self.assertNotIn("Traceback", out(result))
                self.assertNotIn("is not a session of this checkout", out(result))
                expected = S if kind == "empty" else value
                self.assertEqual(frontmatter(path)["session"], expected)

    def test_c1_claim_runs_rotation_as_for_the_current_session(self):
        repo = self.new_repo()
        self.own_marker(repo)
        self.add_marker(repo, self.dead_pid())
        self.start(repo, sid=S)
        old_text = valid_text("sessz")
        old = self.put(repo, NAME1, old_text)
        self.commit_files(repo, old)
        self.assertEqual(self.progress_files(repo), [old])
        new = self.put(repo, NAME2, valid_text(UNKNOWN))
        result = self.post(repo, new, sid=S)
        self.assertEqual(frontmatter(new)["session"], S)
        self.assertEqual((repo / LOGS_REL / NAME1).read_text(), old_text)
        self.assertFalse(old.exists())
        self.assertEqual(frontmatter(new)["before"], f"{LOGS_REL}/{NAME1}")
        self.assertIn(n1(S, self.rel(repo, new), UNKNOWN), out(result))
        self.assertNotIn("Traceback", out(result))

    def test_c4_second_untracked_file_is_claimed_then_refused_and_the_skeleton_stays(self):
        repo = self.session_repo()
        first = self.edit(repo, "src/a.py")
        self.assertEqual(first.returncode, 2, out(first))
        skeleton = self.single_skeleton(repo)
        skeleton_bytes = skeleton.read_bytes()
        second = self.put(repo, NAME2, valid_text(UNKNOWN))
        result = self.post(repo, second, sid=S)
        self.assertEqual(result.returncode, 2, out(result))
        self.assertEqual(frontmatter(second)["session"], S)
        self.assertIn(n1(S, self.rel(repo, second), UNKNOWN), result.stderr)
        self.assertIn("already owns", result.stderr.lower())
        self.assertIn("merge", result.stderr.lower())
        self.assertTrue(skeleton.is_file())
        self.assertEqual(skeleton.read_bytes(), skeleton_bytes)
        self.assertEqual(self.progress_files(repo, "progress-logs"), [])
        self.assertEqual(sorted(p.name for p in self.progress_files(repo)), sorted([skeleton.name, NAME2]))

    def test_r9_stop_claims_an_intended_own_file_and_does_not_ask_for_a_new_one(self):
        repo = self.changed_session()
        path = self.put(repo, NAME1, valid_text(UNKNOWN))
        result = self.stop(repo, sid=S)
        self.assertEqual(result.returncode, 2, out(result))
        self.assertEqual(frontmatter(path)["session"], S)
        self.assertIn(n1(S, self.rel(repo, path), UNKNOWN), out(result))
        self.assertNotIn("<16-hex-id>", out(result))
        self.assertNotIn("Traceback", out(result))

    def test_r9_stop_claims_auto_and_empty_values(self):
        for kind in ("auto", "empty"):
            with self.subTest(value=kind):
                repo = self.changed_session()
                text = valid_text("auto" if kind == "auto" else "").replace("session: \n", "session:\n")
                path = self.put(repo, NAME1, text)
                result = self.stop(repo, sid=S)
                self.assertEqual(result.returncode, 2, out(result))
                self.assertEqual(frontmatter(path)["session"], S)
                self.assertIn(n1(S, self.rel(repo, path), "auto" if kind == "auto" else ""), out(result))

    def test_stop_hook_active_claims_silently_and_exits_zero(self):
        repo = self.changed_session()
        path = self.put(repo, NAME1, valid_text(UNKNOWN))
        result = self.stop(repo, sid=S, active=True)
        self.assertEqual(frontmatter(path)["session"], S)
        self.assertNotIn("is not a session of this checkout", out(result))
        self.assertEqual(result.returncode, 0, out(result))
        self.assertNotIn("Traceback", out(result))

    def test_r10_stop_leaves_a_known_value_byte_identical_and_still_asks_for_progress(self):
        repo = self.new_repo()
        self.own_marker(repo)
        self.start(repo, sid="sessv")
        self.start(repo, sid=S)
        self.mark_changed(repo, sid=S)
        path = self.put(repo, NAME1, valid_text("sessv"))
        result = self.stop(repo, sid=S)
        self.assertEqual(frontmatter(path)["session"], "sessv")
        self.assertEqual(result.returncode, 2, out(result))
        self.assertNotIn("is not a session of this checkout", out(result))

    def test_r11_stop_leaves_a_path_in_head_byte_identical(self):
        repo = self.changed_session()
        path = self.put(repo, NAME1, valid_text(UNKNOWN))
        self.commit_files(repo, path)
        path.write_text(path.read_text().replace("- edited the parser", "- edited the parser again"))
        result = self.stop(repo, sid=S)
        self.assertEqual(frontmatter(path)["session"], UNKNOWN)
        self.assertNotIn("is not a session of this checkout", out(result))

    def committed_with_pre_commit(self, value_kind, in_head=False):
        repo = self.new_repo()
        value = {"unknown": UNKNOWN, "auto": "auto", "empty": "", "state": "sessv", "head_owned": "sessh"}[value_kind]
        if value_kind == "state":
            self.start(repo, sid="sessv")
        if value_kind == "head_owned":
            owned = self.put(repo, NAME0, valid_text("sessh"), directory="progress-logs")
            self.commit_files(repo, owned)
        text = valid_text(value).replace("session: \n", "session:\n")
        path = self.put(repo, NAME1, text)
        if in_head:
            self.commit_files(repo, path)
            text = text.replace("- edited the parser", "- edited the parser again")
            path.write_text(text)
        run_git(repo, "add", "--", self.rel(repo, path))
        return repo, path, text

    def test_r12_pre_commit_claims_and_stages_unknown_auto_and_empty(self):
        for kind in ("unknown", "auto", "empty"):
            with self.subTest(value=kind):
                repo, path, _ = self.committed_with_pre_commit(kind)
                result = self.git_commit(repo, self.clean_env(CLAUDE_CODE_SESSION_ID=S))
                self.assertEqual(result.returncode, 0, out(result))
                self.assertEqual(frontmatter(path)["session"], S)
                committed = run_git(repo, "show", f"HEAD:{self.rel(repo, path)}").stdout
                self.assertIn("\nsession: " + S + "\n", committed)
                self.assertEqual(committed, path.read_text())

    def test_r13_pre_commit_leaves_known_values_and_paths_in_head_byte_identical(self):
        cases = (("state", False), ("head_owned", False), ("unknown", True), ("auto", True))
        for kind, in_head in cases:
            with self.subTest(value=kind, in_head=in_head):
                repo, path, text = self.committed_with_pre_commit(kind, in_head)
                result = self.git_commit(repo, self.clean_env(CLAUDE_CODE_SESSION_ID=S))
                self.assertEqual(result.returncode, 0, out(result))
                expected = {"state": "sessv", "head_owned": "sessh", "unknown": UNKNOWN, "auto": "auto"}[kind]
                self.assertEqual(frontmatter(path)["session"], expected)
                self.assertIn(f"\nsession: {expected}\n", run_git(repo, "show", f"HEAD:{self.rel(repo, path)}").stdout)
                self.assertNotIn("is not a session of this checkout", out(result))

    def test_pre_commit_without_a_session_id_does_not_claim(self):
        repo, path, text = self.committed_with_pre_commit("unknown")
        result = self.git_commit(repo, self.clean_env())
        self.assertEqual(result.returncode, 0, out(result))
        self.assertEqual(frontmatter(path)["session"], UNKNOWN)

    def test_c6_claimed_file_then_syncs_user_requests_for_the_current_session(self):
        repo = self.new_repo()
        self.start(repo, sid=S)
        self.prompt(repo, "a request before the commit", sid=S)
        path = self.put(repo, NAME1, valid_text(UNKNOWN))
        run_git(repo, "add", "--", self.rel(repo, path))
        result = self.git_commit(repo, self.clean_env(CLAUDE_CODE_SESSION_ID=S))
        self.assertEqual(result.returncode, 0, out(result))
        self.assertEqual(frontmatter(path)["session"], S)
        self.assertIn("> a request before the commit", run_git(repo, "show", f"HEAD:{self.rel(repo, path)}").stdout)


class FreshnessCase(HookCase):
    def record(self, repo, text, name=NAME1, directory="progress"):
        path = self.put(repo, name, text, directory=directory)
        self.commit_files(repo, path, message="record progress")
        return path

    def status_report(self, repo, path):
        rel = self.rel(repo, path)
        return self.show(repo, rel), self.check(repo, rel)

    def entry_text(self, files, commit=None, text="alpha module wiring", **kw):
        if commit:
            return build(next_step=[(text, commit, files)], **kw)
        return files_only(build(next_step=[(text, "a" * 40, files)], **kw))

    def assert_fresh(self, repo, path):
        shown, checked = self.status_report(repo, path)
        self.assertEqual(shown.returncode, 0, out(shown))
        self.assertRegex(shown.stdout, r"\bfresh\b")
        self.assertNotIn("stale", shown.stdout)
        self.assertEqual(checked.returncode, 0, out(checked))

    def assert_stale(self, repo, path, status):
        shown, checked = self.status_report(repo, path)
        self.assertEqual(shown.returncode, 0, out(shown))
        self.assertRegex(shown.stdout, status_pattern(status))
        self.assertEqual(checked.returncode, 1, out(checked))
        self.assertNotIn("Traceback", out(checked))


class TestFreshnessAnchors(FreshnessCase):
    def test_same_commit_entry_and_listed_change_is_fresh(self):
        repo = self.new_repo()
        path = self.put(repo, NAME1, self.entry_text("src/a.py"))
        (repo / "src" / "a.py").write_text("a = 2\n")
        run_git(repo, "add", "-A")
        self.commit(repo, "work and progress")
        self.assert_fresh(repo, path)

    def test_later_change_is_stale_with_the_exact_status(self):
        repo = self.new_repo()
        path = self.record(repo, self.entry_text("src/a.py"))
        changed = self.touch_commit(repo, "src/a.py")
        self.assert_stale(repo, path, f"stale: changed src/a.py in {changed[:7]}")

    def test_boundary_change_in_the_anchor_commit_is_fresh_and_one_commit_later_is_stale(self):
        repo = self.new_repo()
        path = self.put(repo, NAME1, self.entry_text("src/a.py"))
        (repo / "src" / "a.py").write_text("a = 2\n")
        run_git(repo, "add", "-A")
        self.commit(repo, "anchor commit changes the listed file")
        self.assert_fresh(repo, path)
        later = self.touch_commit(repo, "src/a.py")
        self.assert_stale(repo, path, f"stale: changed src/a.py in {later[:7]}")

    def test_uncommitted_entry_is_fresh_although_the_listed_file_changed_in_history(self):
        repo = self.new_repo()
        self.touch_commit(repo, "src/a.py")
        path = self.put(repo, NAME1, self.entry_text("src/a.py"))
        self.assert_fresh(repo, path)

    def test_edited_metadata_line_in_a_committed_file_is_uncommitted_and_fresh(self):
        repo = self.new_repo()
        path = self.record(repo, self.entry_text("src/a.py"))
        self.touch_commit(repo, "src/a.py")
        path.write_text(path.read_text().replace("  - files: src/a.py", "  - files: src/a.py, src/b.py"))
        self.assert_fresh(repo, path)

    def test_edited_item_text_keeps_the_anchor_of_its_unchanged_metadata_line(self):
        repo = self.new_repo()
        path = self.record(repo, self.entry_text("src/a.py"))
        changed = self.touch_commit(repo, "src/a.py")
        path.write_text(path.read_text().replace("alpha module wiring", "alpha module wiring v2"))
        self.assert_stale(repo, path, f"stale: changed src/a.py in {changed[:7]}")

    def test_listed_directory_covers_changes_below_it(self):
        repo = self.new_repo()
        path = self.record(repo, self.entry_text("src"))
        changed = self.touch_commit(repo, "src/deep/new.py")
        shown, checked = self.status_report(repo, path)
        self.assertRegex(shown.stdout, rf"stale: changed (src|src/deep/new\.py) in {changed[:7]}(?![0-9a-f])")
        self.assertEqual(checked.returncode, 1, out(checked))

    def test_listed_directory_ignores_a_sibling_that_only_shares_the_prefix(self):
        repo = self.new_repo()
        path = self.record(repo, self.entry_text("src"))
        self.touch_commit(repo, "src2/x.py")
        self.assert_fresh(repo, path)

    def test_files_none_is_fresh_after_any_change(self):
        repo = self.new_repo()
        path = self.record(repo, self.entry_text("none"))
        self.touch_commit(repo, "src/a.py")
        self.assert_fresh(repo, path)

    def test_each_entry_is_judged_by_its_own_listed_files(self):
        repo = self.new_repo()
        path = self.record(repo, files_only(build(state=[("beta untouched file", "a" * 40, "src/b.py")],
                                                  next_step=[("alpha touched file", "a" * 40, "src/a.py")])))
        changed = self.touch_commit(repo, "src/a.py")
        shown = self.show(repo, self.rel(repo, path))
        self.assertRegex(shown.stdout, r"\bfresh\b")
        self.assertRegex(shown.stdout, status_pattern(f"stale: changed src/a.py in {changed[:7]}"))

    def test_files_only_and_legacy_metadata_forms_are_both_valid(self):
        repo = self.new_repo()
        base = self.head(repo)
        for label, text in (("files only", self.entry_text("src/a.py")),
                            ("legacy", self.entry_text("src/a.py", commit=base))):
            with self.subTest(form=label):
                path = self.put(repo, NAME1, text)
                checked = self.check(repo, self.rel(repo, path))
                self.assertEqual(checked.returncode, 0, out(checked))

    def entry_texts(self, text):
        progress = load_progress()
        found = []

        def walk(node):
            if hasattr(node, "text") and not isinstance(node, str):
                found.append(node.text)
            elif isinstance(node, dict):
                for value in node.values():
                    walk(value)
            elif isinstance(node, (list, tuple)):
                for value in node:
                    walk(value)

        walk(progress.entries(progress.parse(text)))
        return found

    def test_entry_text_excludes_both_metadata_forms(self):
        for label, text in (("files only", self.entry_text("src/a.py", text="alpha work item")),
                            ("legacy", self.entry_text("src/a.py", commit="a" * 40, text="alpha work item"))):
            with self.subTest(form=label):
                texts = self.entry_texts(text)
                self.assertIn("alpha work item", texts)
                for item in texts:
                    self.assertNotIn("files:", item)
                    self.assertNotIn("commit:", item)

    def test_entry_without_metadata_keeps_its_format_finding(self):
        repo = self.new_repo()
        body = build(session=S).replace("### Next Step\n", "### Next Step\n- " + "x" * 80 + "\n", 1)
        path = self.put(repo, NAME1, body)
        checked = self.check(repo, self.rel(repo, path))
        self.assertEqual(checked.returncode, 1, out(checked))
        self.assertIn("x" * 50, out(checked))
        self.assertNotIn("Traceback", out(checked))

    def test_legacy_non_ancestor_sha_takes_its_status_from_the_recording_commit(self):
        repo = self.new_repo()
        main = self.branch(repo)
        run_git(repo, "checkout", "-q", "-b", "side")
        side = self.touch_commit(repo, "src/side.py")
        run_git(repo, "checkout", "-q", main)
        path = self.record(repo, self.entry_text("src/a.py", commit=side))
        self.assert_fresh(repo, path)
        changed = self.touch_commit(repo, "src/a.py")
        self.assert_stale(repo, path, f"stale: changed src/a.py in {changed[:7]}")

    def test_legacy_explicit_commit_older_than_the_recording_commit_does_not_decide(self):
        repo = self.new_repo()
        base = self.head(repo)
        self.touch_commit(repo, "src/a.py")
        path = self.record(repo, self.entry_text("src/a.py", commit=base))
        self.assert_fresh(repo, path)

    def test_legacy_unresolved_sha_does_not_decide_while_blame_works(self):
        repo = self.new_repo()
        path = self.record(repo, self.entry_text("src/a.py", commit="deadbeef" * 5))
        self.assert_fresh(repo, path)


class TestFreshnessAcrossRename(FreshnessCase):
    def retired(self, repo, text):
        path = self.record(repo, text)
        target = repo / LOGS_REL / path.name
        target.parent.mkdir(parents=True, exist_ok=True)
        run_git(repo, "mv", self.rel(repo, path), self.rel(repo, target))
        self.commit(repo, "retire progress")
        return target

    def test_unrelated_commit_after_the_rename_keeps_the_entry_fresh(self):
        repo = self.new_repo()
        target = self.retired(repo, self.entry_text("src/a.py"))
        self.touch_commit(repo, "src/b.py")
        self.assert_fresh(repo, target)

    def test_listed_change_after_the_rename_is_stale(self):
        repo = self.new_repo()
        target = self.retired(repo, self.entry_text("src/a.py"))
        changed = self.touch_commit(repo, "src/a.py")
        self.assert_stale(repo, target, f"stale: changed src/a.py in {changed[:7]}")

    def test_listed_change_between_recording_and_rename_is_stale_so_the_anchor_follows_the_rename(self):
        repo = self.new_repo()
        path = self.record(repo, self.entry_text("src/a.py"))
        changed = self.touch_commit(repo, "src/a.py")
        target = repo / LOGS_REL / path.name
        target.parent.mkdir(parents=True, exist_ok=True)
        run_git(repo, "mv", self.rel(repo, path), self.rel(repo, target))
        self.commit(repo, "retire progress")
        self.assert_stale(repo, target, f"stale: changed src/a.py in {changed[:7]}")


class BlameFailureCase(FreshnessCase):
    def failing_blame_env(self):
        return self.failing_git_env("blame")

    def failing_git_env(self, *words):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        real = shutil.which("git")
        shim = Path(tmp.name) / "git"
        shim.write_text(
            "#!/bin/sh\n"
            "ok=1\n"
            f"for word in {' '.join(words)}; do\n"
            "  seen=0\n"
            '  for arg in "$@"; do [ "$arg" = "$word" ] && seen=1; done\n'
            "  [ $seen = 1 ] || ok=0\n"
            "done\n"
            'if [ $ok = 1 ]; then echo "fatal: simulated git failure" >&2; exit 128; fi\n'
            f'exec "{real}" "$@"\n'
        )
        shim.chmod(0o755)
        return self.env(PATH=f"{tmp.name}{os.pathsep}{os.environ['PATH']}")

    def shown(self, repo, path, env):
        return subprocess.run([sys.executable, str(repo / ".harness" / "bin" / "progress.py"), "show", self.rel(repo, path)],
                              capture_output=True, text=True, cwd=repo, env=env)

    def checked(self, repo, path, env):
        return subprocess.run([sys.executable, str(repo / ".harness" / "bin" / "progress.py"), "check", self.rel(repo, path)],
                              capture_output=True, text=True, cwd=repo, env=env)


class TestBlameFailure(BlameFailureCase):
    def test_explicit_commit_is_the_anchor_when_blame_fails(self):
        repo = self.new_repo()
        base = self.head(repo)
        changed = self.touch_commit(repo, "src/a.py")
        path = self.record(repo, build(state=[("beta recorded before the change", base, "src/a.py")],
                                       next_step=[("alpha recorded after the change", changed, "src/a.py")]))
        env = self.failing_blame_env()
        shown = self.shown(repo, path, env)
        self.assertEqual(shown.returncode, 0, out(shown))
        self.assertRegex(shown.stdout, status_pattern(f"stale: changed src/a.py in {changed[:7]}"))
        self.assertRegex(shown.stdout, r"\bfresh\b")
        self.assertNotIn("Traceback", out(shown))
        checked = self.checked(repo, path, env)
        self.assertEqual(checked.returncode, 1, out(checked))

    def test_no_explicit_commit_gives_no_recording_commit(self):
        repo = self.new_repo()
        path = self.record(repo, self.entry_text("src/a.py"))
        env = self.failing_blame_env()
        shown = self.shown(repo, path, env)
        self.assertEqual(shown.returncode, 0, out(shown))
        self.assertIn("stale: no recording commit", shown.stdout)
        self.assertNotIn("Traceback", out(shown))
        checked = self.checked(repo, path, env)
        self.assertEqual(checked.returncode, 1, out(checked))
        self.assertNotIn("Traceback", out(checked))

    def test_fresh_explicit_commit_gives_exit_zero_when_blame_fails(self):
        repo = self.new_repo()
        path = self.record(repo, self.entry_text("src/a.py", commit=self.head(repo)))
        env = self.failing_blame_env()
        checked = self.checked(repo, path, env)
        self.assertEqual(checked.returncode, 0, out(checked))
        self.assertNotIn("Traceback", out(checked))

    def test_post_tool_use_survives_blame_failure(self):
        repo = self.new_repo()
        self.own_marker(repo)
        path = self.record(repo, self.entry_text("src/a.py"))
        result = self.post(repo, path, sid=S, env=self.failing_blame_env())
        self.assertEqual(result.returncode, 2, out(result))
        self.assertIn("stale", result.stderr)
        self.assertNotIn("Traceback", out(result))


class TestNearDuplicateAnchors(BlameFailureCase):
    def pair(self, old_at, new_at, old_explicit="first", new_explicit="second"):
        text = sized(40)
        repo = self.new_repo()
        shas = {"first": self.commit(repo, "first explicit"), "second": self.commit(repo, "second explicit")}
        old = self.put(repo, NAME1, build(session="sessb", state=[(text, shas[old_explicit], "none")]), directory="progress-logs")
        new = self.put(repo, NAME2, build(session=S, before=self.rel(repo, old), next_step=[(text, shas[new_explicit], "none")]))
        for tag in ("first", "second"):
            for at, path in ((old_at, old), (new_at, new)):
                if at == tag:
                    run_git(repo, "add", "--", self.rel(repo, path))
            self.commit(repo, f"{tag} anchor commit")
        return repo, old, new

    def duplicate_flag(self, repo, new, env=None):
        env = env if env is not None else self.env()
        rel = self.rel(repo, new)
        runs = [subprocess.run([sys.executable, str(repo / ".harness" / "bin" / "progress.py"), verb, rel],
                               capture_output=True, text=True, cwd=repo, env=env) for verb in ("check", "show")]
        flags = ["near-duplicate" in out(run) for run in runs]
        self.assertEqual(flags[0], flags[1], [out(r) for r in runs])
        self.assertNotIn("Traceback", out(runs[0]))
        return flags[0]

    def test_same_anchor_is_not_flagged(self):
        repo, _, new = self.pair("first", "first")
        self.assertFalse(self.duplicate_flag(repo, new))

    def test_different_anchors_with_similar_text_are_flagged(self):
        repo, _, new = self.pair("first", "second")
        self.assertTrue(self.duplicate_flag(repo, new))

    def test_different_explicit_commits_do_not_flag_when_anchors_agree(self):
        repo, _, new = self.pair("first", "first", "first", "second")
        self.assertFalse(self.duplicate_flag(repo, new))

    def test_equal_explicit_commits_do_not_hide_different_anchors(self):
        repo, _, new = self.pair("first", "second", "first", "first")
        self.assertTrue(self.duplicate_flag(repo, new))

    def test_uncommitted_new_against_committed_predecessor_differ(self):
        repo, _, new = self.pair("first", None)
        self.assertTrue(self.duplicate_flag(repo, new))

    def test_anchor_none_on_the_predecessor_only_skips_the_comparison(self):
        text = sized(40)
        repo = self.new_repo()
        bare = re.sub(r"  - commit: [0-9a-f]+; files: none\n", "", build(session="sessb", state=[(text, "a" * 40, "none")]))
        self.assertNotIn("files: none", bare)
        old = self.put(repo, NAME1, bare, directory="progress-logs")
        new = self.put(repo, NAME2, build(session=S, before=self.rel(repo, old), next_step=[(text, "b" * 40, "none")]))
        run_git(repo, "add", "-A")
        self.commit(repo, "both")
        self.assertFalse(self.duplicate_flag(repo, new))

    def test_anchor_none_on_the_current_entry_only_skips_the_comparison(self):
        text = sized(40)
        repo = self.new_repo()
        explicit = self.commit(repo, "explicit")
        old = self.put(repo, NAME1, build(session="sessb", state=[(text, explicit, "none")]), directory="progress-logs")
        new = self.put(repo, NAME2, files_only(build(session=S, before=self.rel(repo, old), next_step=[(text, "b" * 40, "none")])))
        run_git(repo, "add", "-A")
        self.commit(repo, "both")
        self.assertFalse(self.duplicate_flag(repo, new, self.failing_blame_env()))

    def test_both_uncommitted_share_an_anchor(self):
        repo, _, new = self.pair(None, None)
        self.assertFalse(self.duplicate_flag(repo, new))

    def test_anchor_none_skips_the_comparison(self):
        text = sized(40)
        repo = self.new_repo()
        old = self.put(repo, NAME1, files_only(build(session="sessb", state=[(text, "a" * 40, "none")])), directory="progress-logs")
        new = self.put(repo, NAME2, files_only(build(session=S, before=self.rel(repo, old), next_step=[(text, "b" * 40, "none")])))
        run_git(repo, "add", "-A")
        self.commit(repo, "both")
        self.assertFalse(self.duplicate_flag(repo, new, self.failing_blame_env()))

    def test_blame_failure_falls_back_to_explicit_commits_on_both_sides(self):
        for label, old_explicit, new_explicit, expected in (("different explicit", "first", "second", True),
                                                             ("equal explicit", "first", "first", False)):
            with self.subTest(case=label):
                repo, _, new = self.pair("first", "first", old_explicit, new_explicit)
                self.assertEqual(self.duplicate_flag(repo, new, self.failing_blame_env()), expected)


class TestRetireFreshnessWithRealRetire(HookCase):
    def test_retire_command_keeps_unrelated_entries_fresh_and_listed_change_stale(self):
        repo = self.new_repo()
        self.own_marker(repo)
        self.start(repo, sid=S)
        path = self.put(repo, NAME1, valid_text(S).replace("files: none", "files: src/a.py"))
        self.commit_files(repo, path)
        retired = self.cli(repo, "retire", "--session", S)
        self.assertEqual(retired.returncode, 0, out(retired))
        run_git(repo, "add", "-A")
        self.commit(repo, "retire")
        logs = repo / LOGS_REL / NAME1
        self.assertTrue(logs.is_file())
        self.touch_commit(repo, "src/b.py")
        shown = self.show(repo, self.rel(repo, logs))
        self.assertNotIn("stale", shown.stdout)
        changed = self.touch_commit(repo, "src/a.py")
        shown = self.show(repo, self.rel(repo, logs))
        self.assertRegex(shown.stdout, status_pattern(f"stale: changed src/a.py in {changed[:7]}"))


class TestSkeleton(HookCase):
    def first_change(self, repo, prompt="Add a --sort flag to list", sid=S):
        if prompt is not None:
            self.prompt(repo, prompt, sid=sid)
        return self.edit(repo, "src/a.py", sid=sid)

    def test_first_modifying_edit_creates_the_exact_skeleton_with_notice_and_exit_two(self):
        repo = self.session_repo()
        result = self.first_change(repo)
        skeleton = self.single_skeleton(repo)
        label = self.rel(repo, skeleton)
        self.assertEqual(result.returncode, 2, out(result))
        self.assertEqual(result.stderr.count(n2(label)), 1, result.stderr)
        self.assertNotIn("has no progress yet", result.stderr)
        self.assertNotIn("Traceback", out(result))
        self.assertRegex(skeleton.name, SKELETON_NAME)
        self.assertRegex(skeleton.name, r"^[0-9a-f]{16}-add-a-sort-flag-to\.md$")
        self.assert_skeleton_text(skeleton.read_text(), S, self.branch(repo))
        self.assertIn("> Add a --sort flag to list", skeleton.read_text().split("\n### User Requests")[-1])

    def test_skeleton_name_uses_session_when_the_first_prompt_has_no_ascii_runs(self):
        repo = self.session_repo()
        self.first_change(repo, prompt="한글만 있는 요청")
        self.assertRegex(self.single_skeleton(repo).name, r"^[0-9a-f]{16}-session\.md$")

    def test_skeleton_name_uses_session_when_no_prompt_was_recorded(self):
        repo = self.session_repo()
        self.first_change(repo, prompt=None)
        self.assertRegex(self.single_skeleton(repo).name, r"^[0-9a-f]{16}-session\.md$")

    def test_bash_first_change_also_creates_the_skeleton(self):
        repo = self.session_repo()
        result = self.bash(repo, lambda: (repo / "src" / "new.py").write_text("x\n"), sid=S)
        skeleton = self.single_skeleton(repo)
        self.assertEqual(result.returncode, 2, out(result))
        self.assertEqual(result.stderr.count(n2(self.rel(repo, skeleton))), 1)

    def test_change_dir_holds_the_skeleton_marker_and_no_reminder_marker(self):
        repo = self.session_repo()
        self.first_change(repo)
        names = {p.name for p in self.change_dir(repo).iterdir()}
        self.assertIn("skeleton", names)
        self.assertIn("modified", names)
        self.assertNotIn("reminded", names)

    def test_rotation_moves_an_earlier_progress_and_sets_before(self):
        repo = self.new_repo()
        self.own_marker(repo)
        self.add_marker(repo, self.dead_pid())
        old_text = valid_text("sessz")
        old = self.put(repo, NAME1, old_text)
        self.commit_files(repo, old)
        self.start(repo, sid=S)
        result = self.first_change(repo)
        skeleton = self.single_skeleton(repo)
        self.assertEqual((repo / LOGS_REL / NAME1).read_text(), old_text)
        self.assertEqual(frontmatter(skeleton)["before"], f"{LOGS_REL}/{NAME1}")
        self.assertIn(n2(self.rel(repo, skeleton)), result.stderr)
        self.assertIn(NAME1, result.stderr)
        self.assert_skeleton_text(skeleton.read_text(), S, self.branch(repo))

    def test_second_modifying_call_prints_nothing(self):
        repo = self.session_repo()
        self.first_change(repo)
        for call in (self.edit(repo, "src/b.py"),
                     self.bash(repo, lambda: (repo / "src" / "c.py").write_text("c = 1\n"), sid=S, tool_use_id="toolu_2")):
            self.assertEqual((call.returncode, call.stderr, call.stdout), (0, "", ""))
        self.assertEqual(len(self.progress_files(repo)), 1)

    def test_own_progress_before_the_first_change_means_no_skeleton(self):
        repo = self.new_repo()
        path = self.put(repo, NAME1, valid_text(S))
        self.commit_files(repo, path)
        self.start(repo, sid=S)
        result = self.edit(repo, "src/a.py")
        self.assertEqual((result.returncode, result.stderr), (0, ""))
        self.assertEqual(self.progress_files(repo), [path])

    def test_refused_rotation_prints_s1_once_and_writes_no_file(self):
        repo = self.new_repo()
        self.own_marker(repo)
        self.add_marker(repo, 1)
        old_text = valid_text("sessz")
        old = self.put(repo, NAME1, old_text)
        self.commit_files(repo, old)
        self.start(repo, sid=S)
        first = self.edit(repo, "src/a.py")
        self.assertEqual(first.returncode, 2, out(first))
        self.assertEqual(first.stderr.count(s1()), 1, first.stderr)
        self.assertNotIn("was created", first.stderr)
        self.assertEqual(self.progress_files(repo), [old])
        self.assertEqual(old.read_text(), old_text)
        self.assertEqual(self.progress_files(repo, "progress-logs"), [])
        second = self.edit(repo, "src/b.py")
        self.assertEqual((second.returncode, second.stderr), (0, ""))
        self.assertEqual(self.progress_files(repo), [old])

    def test_stop_with_an_untouched_skeleton_blocks_with_the_exact_message(self):
        repo = self.session_repo()
        self.first_change(repo)
        label = self.rel(repo, self.single_skeleton(repo))
        result = self.stop(repo, sid=S)
        self.assertEqual(result.returncode, 2, out(result))
        self.assertIn(s8(label), result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_stop_with_placeholders_and_an_empty_next_session_reports_the_placeholders(self):
        repo = self.changed_session()
        path = self.put(repo, NAME1, build(session=S, changes=f"- {PLACEHOLDER}"))
        self.commit_files(repo, path)
        result = self.stop(repo, sid=S)
        self.assertEqual(result.returncode, 2, out(result))
        self.assertIn(s8(self.rel(repo, path)), result.stderr)
        self.assertNotIn("Next Session", result.stderr)
        self.assertNotIn("- none:", result.stderr)

    def test_stop_hook_active_with_an_untouched_skeleton_exits_zero(self):
        repo = self.session_repo()
        self.first_change(repo)
        result = self.stop(repo, sid=S, active=True)
        self.assertEqual(result.returncode, 0, out(result))
        self.assertNotIn("Traceback", out(result))

    def fill(self, text, keep_first=False):
        lines = []
        kept = False
        for line in text.split("\n"):
            if PLACEHOLDER in line and "### User Requests" not in line.split(PLACEHOLDER)[0]:
                if keep_first and not kept:
                    kept = True
                else:
                    line = line.replace(PLACEHOLDER + " ", "").replace(PLACEHOLDER, "done")
            lines.append(line)
        return "\n".join(lines)

    def test_filled_skeleton_passes_check_and_stop(self):
        repo = self.session_repo()
        self.first_change(repo)
        skeleton = self.single_skeleton(repo)
        skeleton.write_text(self.fill(skeleton.read_text()))
        checked = self.check(repo, self.rel(repo, skeleton))
        self.assertEqual(checked.returncode, 0, out(checked))
        self.assertNotIn(PLACEHOLDER_FINDING, out(checked))
        self.commit_files(repo, skeleton)
        result = self.stop(repo, sid=S)
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, "", ""))

    def test_one_remaining_placeholder_still_blocks_stop_and_is_one_finding(self):
        repo = self.session_repo()
        self.first_change(repo)
        skeleton = self.single_skeleton(repo)
        skeleton.write_text(self.fill(skeleton.read_text(), keep_first=True))
        checked = self.check(repo, self.rel(repo, skeleton))
        self.assertEqual(checked.returncode, 1, out(checked))
        self.assertEqual(out(checked).count(PLACEHOLDER_FINDING), 1, out(checked))
        result = self.stop(repo, sid=S)
        self.assertEqual(result.returncode, 2, out(result))
        self.assertIn(s8(self.rel(repo, skeleton)), result.stderr)

    def test_check_reports_one_finding_per_placeholder_line_outside_user_requests(self):
        repo = self.session_repo()
        self.first_change(repo)
        skeleton = self.single_skeleton(repo)
        expected = sum(1 for line in expected_skeleton(S, "b").split("\n### User Requests")[0].split("\n") if PLACEHOLDER in line)
        self.assertEqual(expected, 10)
        checked = self.check(repo, self.rel(repo, skeleton))
        self.assertEqual(checked.returncode, 1, out(checked))
        self.assertEqual(out(checked).count(PLACEHOLDER_FINDING), expected, out(checked))

    def test_placeholder_inside_a_fence_or_user_requests_is_not_a_finding(self):
        repo = self.new_repo()
        text = valid_text(S, changes="- see\n```\n" + PLACEHOLDER + " inside a fence\n```",
                          user_requests=f"#### 1 — 2026-01-01T00:00:00Z\n> quoted {PLACEHOLDER} text")
        path = self.put(repo, NAME1, text)
        checked = self.check(repo, self.rel(repo, path))
        self.assertEqual(checked.returncode, 0, out(checked))
        self.assertNotIn(PLACEHOLDER_FINDING, out(checked))

    def test_post_tool_use_on_a_placeholder_holding_progress_reports_the_finding(self):
        repo = self.session_repo()
        self.first_change(repo)
        skeleton = self.single_skeleton(repo)
        result = self.post(repo, skeleton, sid=S)
        self.assertEqual(result.returncode, 2, out(result))
        self.assertIn(PLACEHOLDER_FINDING, result.stderr)

    def test_staged_skeleton_blocks_a_commit_without_a_session_id(self):
        repo = self.session_repo()
        self.first_change(repo)
        run_git(repo, "add", "-A")
        result = self.git_commit(repo, self.clean_env())
        self.assertNotEqual(result.returncode, 0, out(result))
        self.assertIn(PLACEHOLDER_FINDING, result.stderr)
        self.assertIn(f"Rule files: {RULE_FILE}", result.stderr)


class TestCommitGate(HookCase):
    def gate_repo(self, modified=True):
        repo = self.new_repo()
        self.own_marker(repo)
        self.assertEqual(self.start(repo, sid=S).returncode, 0)
        if modified:
            self.mark_changed(repo, sid=S)
        return repo

    def verify(self, repo, **extra):
        env = self.clean_env(**extra)
        return subprocess.run([sys.executable, str(repo / ".harness" / "git" / "verify_rules.py")],
                              capture_output=True, text=True, cwd=repo, env=env)

    def gate_env(self):
        return {"CLAUDE_CODE_SESSION_ID": S}

    def own_progress(self, repo, directory="progress", stage=True, text=None):
        path = self.put(repo, NAME1, text if text is not None else valid_text(S), directory=directory)
        if stage:
            run_git(repo, "add", "--", self.rel(repo, path))
        return path

    def assert_no_gate_error(self, result):
        self.assertNotIn(g1(S), result.stderr)
        self.assertNotIn("is not staged with this commit", result.stderr)

    def test_staged_clean_own_progress_is_allowed(self):
        repo = self.gate_repo()
        self.own_progress(repo)
        result = self.verify(repo, **self.gate_env())
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, "", ""))

    def test_committed_clean_own_progress_is_allowed(self):
        repo = self.gate_repo()
        path = self.own_progress(repo)
        self.commit(repo, "progress")
        self.assertTrue(path.is_file())
        result = self.verify(repo, **self.gate_env())
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, "", ""))

    def test_own_progress_in_logs_counts(self):
        repo = self.gate_repo()
        self.own_progress(repo, directory="progress-logs")
        result = self.verify(repo, **self.gate_env())
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, "", ""))

    def test_no_own_progress_gives_g1_with_the_rule_file_line(self):
        repo = self.gate_repo()
        other = self.put(repo, NAME0, valid_text("sessother"))
        run_git(repo, "add", "--", self.rel(repo, other))
        result = self.verify(repo, **self.gate_env())
        self.assertEqual(result.returncode, 1, out(result))
        self.assertIn(g1(S), result.stderr)
        lines = result.stderr.rstrip("\n").split("\n")
        self.assertEqual(lines[0], "harness rule violations found:")
        self.assertEqual(lines[-2], f"Rule files: {RULE_FILE}")
        self.assertEqual(result.stderr.count("Rule files:"), 1)
        self.assertNotIn("Traceback", result.stderr)

    def test_untracked_own_progress_gives_g2(self):
        repo = self.gate_repo()
        path = self.own_progress(repo, stage=False)
        result = self.verify(repo, **self.gate_env())
        self.assertEqual(result.returncode, 1, out(result))
        self.assertIn(g2(self.rel(repo, path), S), result.stderr)
        self.assertNotIn(g1(S), result.stderr)
        self.assertIn(f"Rule files: {RULE_FILE}", result.stderr)

    def test_unstaged_change_to_own_progress_gives_g2(self):
        repo = self.gate_repo()
        path = self.own_progress(repo)
        self.commit(repo, "progress")
        path.write_text(path.read_text().replace("- edited the parser", "- edited the parser again"))
        result = self.verify(repo, **self.gate_env())
        self.assertEqual(result.returncode, 1, out(result))
        self.assertIn(g2(self.rel(repo, path), S), result.stderr)

    def test_change_made_after_staging_gives_g2(self):
        repo = self.gate_repo()
        path = self.own_progress(repo)
        path.write_text(path.read_text().replace("- edited the parser", "- edited the parser again"))
        result = self.verify(repo, **self.gate_env())
        self.assertEqual(result.returncode, 1, out(result))
        self.assertIn(g2(self.rel(repo, path), S), result.stderr)

    def test_logs_progress_with_a_format_finding_is_reported_like_a_progress_dir_file(self):
        for directory in ("progress", "progress-logs"):
            with self.subTest(directory=directory):
                repo = self.gate_repo()
                text = valid_text(S).replace("- edited the parser", f"- {PLACEHOLDER}")
                self.own_progress(repo, directory=directory, text=text)
                result = self.verify(repo, **self.gate_env())
                self.assertEqual(result.returncode, 1, out(result))
                self.assertIn(PLACEHOLDER_FINDING, result.stderr)
                self.assertIn(f"Rule files: {RULE_FILE}", result.stderr)

    def test_inactive_when_the_session_variable_is_unset_or_empty(self):
        for label, extra in (("unset", {}), ("empty", {"CLAUDE_CODE_SESSION_ID": ""})):
            with self.subTest(env=label):
                repo = self.gate_repo()
                result = self.verify(repo, **extra)
                self.assertEqual((result.returncode, result.stdout, result.stderr), (0, "", ""))

    def test_inactive_when_the_update_commit_flag_is_one(self):
        repo = self.gate_repo()
        result = self.verify(repo, CLAUDE_CODE_SESSION_ID=S, HARNESS_UPDATE_COMMIT="1")
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, "", ""))

    def test_update_commit_flag_other_than_one_does_not_disable_the_gate(self):
        repo = self.gate_repo()
        result = self.verify(repo, CLAUDE_CODE_SESSION_ID=S, HARNESS_UPDATE_COMMIT="0")
        self.assertEqual(result.returncode, 1, out(result))
        self.assertIn(g1(S), result.stderr)

    def test_inactive_when_the_session_did_not_modify_the_project(self):
        repo = self.gate_repo(modified=False)
        result = self.verify(repo, **self.gate_env())
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, "", ""))

    def test_inactive_for_another_sessions_modification(self):
        repo = self.gate_repo(modified=False)
        self.start(repo, sid="sessother")
        self.mark_changed(repo, sid="sessother", rel="src/other.py")
        result = self.verify(repo, **self.gate_env())
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, "", ""))

    def test_inactive_during_merge_cherry_pick_revert_and_rebase(self):
        states = (("MERGE_HEAD", "file"), ("CHERRY_PICK_HEAD", "file"), ("REVERT_HEAD", "file"),
                  ("rebase-merge", "dir"), ("rebase-apply", "dir"))
        for name, kind in states:
            with self.subTest(state=name):
                repo = self.gate_repo()
                git_dir = repo / ".git"
                if kind == "file":
                    (git_dir / name).write_text(self.head(repo) + "\n")
                else:
                    (git_dir / name).mkdir()
                result = self.verify(repo, **self.gate_env())
                self.assert_no_gate_error(result)
                self.assertEqual(result.returncode, 0, out(result))

    def test_real_commit_with_staged_own_progress_succeeds(self):
        repo = self.gate_repo()
        self.own_progress(repo)
        run_git(repo, "add", "-A")
        result = self.git_commit(repo, self.clean_env(CLAUDE_CODE_SESSION_ID=S))
        self.assertEqual(result.returncode, 0, out(result))

    def test_real_commit_without_progress_is_blocked_with_g1_and_the_rule_file(self):
        repo = self.gate_repo()
        run_git(repo, "add", "-A")
        before = self.head(repo)
        result = self.git_commit(repo, self.clean_env(CLAUDE_CODE_SESSION_ID=S))
        self.assertNotEqual(result.returncode, 0, out(result))
        self.assertIn(g1(S), result.stderr)
        self.assertIn(f"Rule files: {RULE_FILE}", result.stderr)
        self.assertEqual(self.head(repo), before)

    def test_real_commit_without_a_session_variable_is_not_gated(self):
        repo = self.gate_repo()
        run_git(repo, "add", "-A")
        result = self.git_commit(repo, self.clean_env())
        self.assertEqual(result.returncode, 0, out(result))

    def test_real_commit_with_the_update_flag_is_not_gated(self):
        repo = self.gate_repo()
        run_git(repo, "add", "-A")
        result = self.git_commit(repo, self.clean_env(CLAUDE_CODE_SESSION_ID=S, HARNESS_UPDATE_COMMIT="1"))
        self.assertEqual(result.returncode, 0, out(result))


class TestUpdateAutoCommitInsideASession(UpdateCommitCase):
    def mark_modified(self, repo, sid=S):
        base = {"cwd": str(repo), "session_id": sid, "tool_name": "Bash", "tool_use_id": "toolu_1",
                "tool_input": {"command": "x"}}
        hook = [sys.executable, str(repo / ".harness" / "hooks" / "progress_hook.py")]
        env = {k: v for k, v in os.environ.items() if k not in ("CLAUDE_CODE_SESSION_ID", "CLAUDE_SESSION_ID")}
        for payload in ({"hook_event_name": "SessionStart", "session_id": sid, "source": "startup", "cwd": str(repo)},
                        {**base, "hook_event_name": "PreToolUse"}):
            subprocess.run(hook, input=json.dumps(payload), capture_output=True, text=True, cwd=repo, env=env)
        (repo / "work.txt").write_text("changed by the session\n")
        subprocess.run(hook, input=json.dumps({**base, "hook_event_name": "PostToolUseFailure"}),
                       capture_output=True, text=True, cwd=repo, env=env)

    def test_auto_commit_succeeds_while_the_session_variable_and_modified_marker_are_present(self):
        repo = self.committed_install(after_commit=self.mark_modified)
        env = {k: v for k, v in os.environ.items() if k not in ("HARNESS_UPDATE_COMMIT", "CLAUDE_SESSION_ID")}
        env["CLAUDE_CODE_SESSION_ID"] = S
        self.assertTrue((repo / ".harness" / "sessions" / f"progress-{S}.d" / "modified").is_file())
        (repo / "work.txt").write_text("changed by the session\n")
        run_git(repo, "add", "--", "work.txt")
        plain = subprocess.run(["git", "-C", str(repo), "commit", "-q", "-m", "plain commit"],
                               capture_output=True, text=True, env=env)
        self.assertNotEqual(plain.returncode, 0, plain.stdout + plain.stderr)
        self.assertIn(g1(S), plain.stderr)
        run_git(repo, "reset", "-q", "--", "work.txt")
        count = self.commit_count(repo)
        result = self.update(repo, "--no-ci", env=env)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn("auto-commit skipped", result.stdout)
        self.assertEqual(self.commit_count(repo), count + 1)


class TestLegacyCompatibility(FreshnessCase):
    def test_legacy_progress_committed_with_its_work_has_no_findings(self):
        repo = self.new_repo()
        base = self.head(repo)
        (repo / "src" / "a.py").write_text("a = 2\n")
        (repo / "src" / "b.py").write_text("b = 2\n")
        path = self.put(repo, NAME1, build(
            stamp=base,
            state=[("a changed", base, "src/a.py")],
            next_step=[("b follows", base, "src/b.py, src")],
            verify=[("tests pass", base, "none")]))
        run_git(repo, "add", "-A")
        self.commit(repo, "work together with its progress")
        checked = self.check(repo, self.rel(repo, path))
        self.assertEqual(checked.returncode, 0, out(checked))
        self.assertNotIn("stale", out(checked))
        self.assertNotIn("Traceback", out(checked))


class TestFaultTolerance(BlameFailureCase):
    @unittest.skipIf(hasattr(os, "geteuid") and os.geteuid() == 0, "permission bits do not bind root")
    def test_unwritable_progress_dir_gives_exit_zero_without_message_or_traceback(self):
        repo = self.session_repo()
        folder = repo / "agent-docs" / "progress"
        folder.mkdir(parents=True, exist_ok=True)
        self.addCleanup(os.chmod, folder, 0o700)
        os.chmod(folder, stat.S_IRUSR | stat.S_IXUSR)
        result = self.edit(repo, "src/a.py")
        self.assertEqual(result.returncode, 0, out(result))
        self.assertEqual(result.stderr, "")
        self.assertNotIn("Traceback", out(result))
        self.assertEqual(self.progress_files(repo), [])

    @unittest.skipIf(hasattr(os, "geteuid") and os.geteuid() == 0, "permission bits do not bind root")
    def test_unwritable_change_dir_gives_exit_zero_without_message_or_traceback(self):
        repo = self.changed_session()
        change_dir = self.change_dir(repo)
        self.assertTrue(change_dir.is_dir())
        self.addCleanup(os.chmod, change_dir, 0o700)
        os.chmod(change_dir, stat.S_IRUSR | stat.S_IXUSR)
        result = self.edit(repo, "src/a.py")
        self.assertEqual(result.returncode, 0, out(result))
        self.assertEqual(result.stderr, "")
        self.assertNotIn("Traceback", out(result))

    def test_gate_is_inactive_without_error_when_the_git_dir_lookup_fails(self):
        repo = self.changed_session()
        env = self.failing_git_env("rev-parse", "--git-dir")
        env.pop("HARNESS_UPDATE_COMMIT", None)
        env["CLAUDE_CODE_SESSION_ID"] = S
        result = subprocess.run([sys.executable, str(repo / ".harness" / "git" / "verify_rules.py")],
                                capture_output=True, text=True, cwd=repo, env=env)
        self.assertNotIn(g1(S), result.stderr)
        self.assertNotIn("Traceback", out(result))

    def test_invalid_frontmatter_claim_target_is_not_claimed_and_reports_the_frontmatter(self):
        repo = self.session_repo()
        text = "no frontmatter here\n"
        path = self.put(repo, NAME1, text)
        result = self.post(repo, path, sid=S)
        self.assertEqual(path.read_text(), text)
        self.assertEqual(result.returncode, 2, out(result))
        self.assertIn("invalid progress frontmatter", result.stderr)
        self.assertNotIn("is not a session of this checkout", out(result))
        self.assertNotIn("Traceback", out(result))

    @unittest.skipIf(hasattr(os, "geteuid") and os.geteuid() == 0, "permission bits do not bind root")
    def test_unreadable_claim_target_is_not_claimed_and_does_not_crash(self):
        repo = self.session_repo()
        path = self.put(repo, NAME1, valid_text(UNKNOWN))
        os.chmod(path, 0)
        self.addCleanup(os.chmod, path, 0o600)
        result = self.post(repo, path, sid=S)
        self.assertNotIn("Traceback", out(result))
        self.assertNotIn("is not a session of this checkout", out(result))
        os.chmod(path, 0o600)
        self.assertEqual(frontmatter(path)["session"], UNKNOWN)

    def test_git_missing_for_post_tool_use_claims_nothing_and_reports_git_unavailable(self):
        repo = self.session_repo()
        path = self.put(repo, NAME1, valid_text(UNKNOWN))
        before = path.read_bytes()
        result = self.post(repo, path, sid=S, env=self.env(PATH=self.empty_path_dir()))
        self.assertEqual(path.read_bytes(), before)
        self.assertIn("git unavailable", result.stderr)
        self.assertNotIn("Traceback", out(result))
        self.assertNotIn("is not a session of this checkout", out(result))

    def test_git_missing_for_stop_exits_zero_silently_and_claims_nothing(self):
        repo = self.changed_session()
        path = self.put(repo, NAME1, valid_text(UNKNOWN))
        before = path.read_bytes()
        result = self.stop(repo, sid=S, env=self.env(PATH=self.empty_path_dir()))
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, "", ""))
        self.assertEqual(path.read_bytes(), before)

    def test_git_missing_for_the_first_change_creates_no_skeleton_and_exits_without_traceback(self):
        repo = self.session_repo()
        result = self.edit(repo, "src/a.py", env=self.env(PATH=self.empty_path_dir()))
        self.assertNotIn("Traceback", out(result))
        self.assertNotIn("was created", out(result))
        self.assertEqual(self.progress_files(repo), [])

    def test_blame_failure_never_raises_in_check_show_or_the_hook(self):
        repo = self.new_repo()
        self.own_marker(repo)
        path = self.put(repo, NAME1, self.entry_for_blame_failure())
        run_git(repo, "add", "--", self.rel(repo, path))
        self.commit(repo, "record")
        env = self.failing_blame_env()
        for label, run in (("check", lambda: self.checked(repo, path, env)), ("show", lambda: self.shown(repo, path, env)),
                           ("post", lambda: self.post(repo, path, sid=S, env=env))):
            with self.subTest(surface=label):
                result = run()
                self.assertNotIn("Traceback", out(result))
                self.assertIn(result.returncode, (0, 1, 2))

    def entry_for_blame_failure(self):
        return files_only(build(session=S, next_step=[("alpha module wiring", "a" * 40, "src/a.py")]))


class TestPerformance(HookCase):
    def build_history(self, repo, count):
        base, branch = self.head(repo), self.branch(repo)
        stream = []
        for i in range(count):
            message, content = f"c{i}", f"v = {i}\n"
            stream.append(
                f"commit refs/heads/{branch}\ncommitter t <t@t.com> {1700000000 + i} +0000\n"
                f"data {len(message)}\n{message}\n" + (f"from {base}\n" if i == 0 else "")
                + f"M 100644 inline src/f{i % 20}.py\ndata {len(content)}\n{content}\n"
            )
        subprocess.run(["git", "-C", str(repo), "fast-import", "--quiet"], input="".join(stream), text=True, check=True)
        run_git(repo, "reset", "-q", "--hard", branch)

    def test_check_on_forty_entries_over_two_hundred_commits_takes_at_most_two_seconds(self):
        repo = self.new_repo()
        self.build_history(repo, 100)
        entries = [(f"step {i:02d}: check module m{i} handles edge {i * 5 % 11} under config {i}", "a" * 40, f"src/f{i % 20}.py")
                   for i in range(40)]
        path = self.put(repo, NAME1, files_only(build(session="sessb", next_step=entries)), directory="progress-logs")
        self.commit_files(repo, path)
        self.build_history(repo, 100)
        rel = self.rel(repo, path)

        started = time.perf_counter()
        result = self.cli(repo, "check", rel)
        elapsed = time.perf_counter() - started

        self.assertGreaterEqual(int(run_git(repo, "rev-list", "--count", "HEAD").stdout), 200)
        self.assertLessEqual(elapsed, 2.0, f"check took {elapsed:.2f}s")
        self.assertEqual(result.returncode, 1, out(result))
        self.assertIn("stale", out(result))
        self.assertNotIn("Traceback", out(result))


def harness_text_files():
    root = REPO_ROOT / "harness"
    for path in sorted(root.rglob("*")):
        if path.is_file():
            try:
                yield path, path.read_text()
            except UnicodeDecodeError:
                continue
    yield REPO_ROOT / "README.md", (REPO_ROOT / "README.md").read_text()


class TestTextScan(unittest.TestCase):
    @text_test
    def test_removed_wording_does_not_occur_in_harness_or_readme(self):
        for needle in ("commit: <sha checked against>", "stale: not ancestor"):
            with self.subTest(needle=needle):
                hits = [str(path.relative_to(REPO_ROOT)) for path, text in harness_text_files() if needle in text]
                self.assertEqual(hits, [])

    @text_test
    def test_progress_rule_text_contains_the_required_phrases(self):
        text = (REPO_ROOT / "harness" / "instructions" / "progress.md").read_text()
        for phrase in (PLACEHOLDER, "`auto`", "  - files:", "does not decide freshness", "staged", "harness.py update"):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, text)

    def test_installed_progress_rule_equals_the_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            run_git(repo, "init", "-q")
            result = run_installer("install", str(repo), "--no-ci")
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            installed = (repo / ".harness" / "instructions" / "progress.md").read_bytes()
        self.assertEqual(installed, (REPO_ROOT / "harness" / "instructions" / "progress.md").read_bytes())

    @text_test
    def test_readme_mentions_the_placeholder_and_drops_the_one_time_notice_wording(self):
        text = (REPO_ROOT / "README.md").read_text()
        self.assertIn(PLACEHOLDER, text)
        self.assertNotIn("한 번 안내", text)

    def test_version_is_0_44_0(self):
        self.assertEqual((REPO_ROOT / "harness" / "VERSION").read_text().strip(), "0.49.0")


class TestUpdateFrom0410(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.tmp.cleanup)
        exists = subprocess.run(["git", "-C", str(REPO_ROOT), "cat-file", "-e", f"{BASE_0410}^{{commit}}"],
                                capture_output=True, text=True)
        if exists.returncode != 0:
            raise RuntimeError(f"commit {BASE_0410} is not available in this checkout")
        cls.source = Path(cls.tmp.name) / "source"
        cls.source.mkdir()
        archive = subprocess.run(["git", "-C", str(REPO_ROOT), "archive", BASE_0410, "installer", "harness"],
                                 capture_output=True, check=True).stdout
        subprocess.run(["tar", "-x", "-C", str(cls.source)], input=archive, check=True)

    def installed_0410(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        repo = Path(tmp.name)
        run_git(repo, "init", "-q")
        run_git(repo, "config", "user.email", "test@test.com")
        run_git(repo, "config", "user.name", "test")
        installed = subprocess.run([sys.executable, str(self.source / "installer" / "harness.py"), "install", str(repo), "--no-ci"],
                                   capture_output=True, text=True)
        self.assertEqual(installed.returncode, 0, installed.stdout + installed.stderr)
        self.assertEqual(json.loads((repo / ".harness" / "manifest.json").read_text())["version"], "0.41.0")
        run_git(repo, "add", "-A")
        run_git(repo, "commit", "-q", "--no-verify", "-m", "base")
        return repo

    def test_update_announces_the_migration_last_with_the_plan_lines_in_order(self):
        repo = self.installed_0410()
        agents = (repo / "AGENTS.md").read_bytes()
        result = run_installer("update", str(repo), "--no-ci", "--no-commit", input="y\n" * 20, exact=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        announced = re.findall(r"^migration (\d+\.\d+\.\d+):", result.stdout, re.MULTILINE)
        self.assertEqual(announced, ["0.42.0", "0.43.0", "0.44.0", "0.45.0", "0.47.0", "0.48.0", "0.49.0"], result.stdout)
        start = result.stdout.index("migration 0.42.0:")
        positions = []
        for line in S9:
            self.assertIn(line, result.stdout[start:])
            positions.append(result.stdout.index(line, start))
        self.assertEqual(positions, sorted(positions))
        self.assertEqual((repo / "AGENTS.md").read_bytes(), agents)
        self.assertEqual(json.loads((repo / ".harness" / "manifest.json").read_text())["version"], "0.49.0")
        doctor = run_installer("doctor", str(repo))
        self.assertEqual(doctor.returncode, 0, doctor.stdout + doctor.stderr)

    def test_dry_run_prints_the_plan_lines_and_changes_nothing(self):
        repo = self.installed_0410()
        agents = (repo / "AGENTS.md").read_bytes()
        result = run_installer("update", str(repo), "--no-ci", "--dry-run", forbid_input=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        for line in S9:
            self.assertIn(line, result.stdout)
        self.assertEqual((repo / "AGENTS.md").read_bytes(), agents)
        self.assertEqual(json.loads((repo / ".harness" / "manifest.json").read_text())["version"], "0.41.0")


if __name__ == "__main__":
    unittest.main()

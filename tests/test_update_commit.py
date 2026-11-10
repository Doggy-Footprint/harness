import hashlib
import json
import os
import re
import stat
import tempfile
import unittest
from pathlib import Path

from test_installer import (
    IMPORT_BLOCK,
    INSTALLER_RUN_RECORD,
    InstallerTestCase,
    run_git,
    run_installer,
)
from test_progress import load_progress

OLD_VERSION = "0.39.0"
OLD_BLOCK = "<!-- harness:begin 0.39.0 -->\n# Documentation Guide\n\nold full rule body\n<!-- harness:end -->\n"
BLOCK_RE = re.compile(r"<!-- harness:begin[^>]*-->.*?<!-- harness:end -->\n", re.DOTALL)
STALE_SOURCE = "agent-docs/try-n-fail/1234567890abcdef-x.md"
SKIP_PREFIX = "warning: auto-commit skipped:"


class UpdateCommitCase(InstallerTestCase):
    def set_version(self, repo, version):
        manifest_path = repo / ".harness" / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["version"] = version
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")

    def manifest_version(self, repo):
        return json.loads((repo / ".harness" / "manifest.json").read_text())["version"]

    def head(self, repo):
        return run_git(repo, "rev-parse", "HEAD").stdout.strip()

    def commit_count(self, repo):
        return int(run_git(repo, "rev-list", "--count", "HEAD").stdout.strip())

    def commit_all(self, repo, message="base", untracked=()):
        run_git(repo, "add", "-A")
        for name in untracked:
            run_git(repo, "rm", "--cached", "-q", "--", name)
        run_git(repo, "commit", "-q", "--no-verify", "-m", message)

    def committed_install(self, before_commit=None, after_commit=None, untracked=()):
        repo = self.install()
        self.set_version(repo, OLD_VERSION)
        agents = repo / "AGENTS.md"
        agents.write_text(BLOCK_RE.sub(lambda m: OLD_BLOCK, agents.read_text()) + "\nUser notes below the block.\n")
        if before_commit:
            before_commit(repo)
        self.commit_all(repo, untracked=untracked)
        if after_commit:
            after_commit(repo)
        return repo

    def expected_agents(self, old_text):
        return BLOCK_RE.sub(lambda m: IMPORT_BLOCK, old_text, count=1).encode()

    def files_state(self, repo):
        listing = run_git(repo, "ls-files", "-z", "--cached", "--others", "--exclude-standard").stdout
        state = {}
        for name in listing.split("\0"):
            if not name:
                continue
            path = repo / name
            if path.is_symlink():
                state[name] = "link:" + os.readlink(path)
            elif path.is_file():
                state[name] = hashlib.sha256(path.read_bytes()).hexdigest()
            else:
                state[name] = None
        return state

    def changed_between(self, before, after):
        return sorted(name for name in set(before) | set(after) if before.get(name) != after.get(name))

    def status(self, repo):
        return run_git(repo, "status", "--porcelain", "-z", "--untracked-files=all").stdout

    def commit_paths(self, repo):
        listing = run_git(repo, "diff-tree", "--no-commit-id", "--name-only", "-r", "-z", "HEAD").stdout
        return sorted(name for name in listing.split("\0") if name)

    def update(self, repo, *flags, env=None, answers="y\n" * 80):
        return run_installer("update", str(repo), *flags, input=answers, env=env, exact=True)

    def observed_update(self, repo, *flags, env=None, answers="y\n" * 80):
        before = self.files_state(repo)
        head = self.head(repo)
        result = self.update(repo, *flags, env=env, answers=answers)
        changed = self.changed_between(before, self.files_state(repo))
        return result, changed, head

    def items(self, stdout, name):
        marker = f"== {name} ==\n"
        if marker not in stdout:
            return []
        body = stdout.split(marker, 1)[1].split("\n== ", 1)[0]
        return [line[2:] for line in body.splitlines() if line.startswith("- ")]

    def listed(self, paths):
        return ", ".join(sorted(paths))

    def modify_settings_unstaged(self, repo):
        path = repo / ".claude" / "settings.json"
        data = json.loads(path.read_text())
        data["env"] = {"USER_EDIT": "1"}
        path.write_text(json.dumps(data, indent=2) + "\n")

    def modify_claude_md_staged(self, repo):
        with (repo / "CLAUDE.md").open("a") as handle:
            handle.write("\nuser line\n")
        run_git(repo, "add", "--", "CLAUDE.md")

    def assert_applied(self, repo, old_agents):
        self.assertNotEqual(self.manifest_version(repo), OLD_VERSION)
        self.assertEqual((repo / "AGENTS.md").read_bytes(), self.expected_agents(old_agents))

    def assert_skipped(self, repo, result, changed, head, pre_dirty):
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.head(repo), head)
        self.assertIn(f"{SKIP_PREFIX} already modified: {self.listed(pre_dirty)}", result.stdout.splitlines())
        self.assertIn(
            f"auto-commit skipped; commit these files yourself: {self.listed(changed)}",
            self.items(result.stdout, "manual review"),
        )
        self.assertNotRegex(result.stdout, r"auto-commit: [0-9a-f]{40}")


class TestAutoCommitHistory(UpdateCommitCase):
    def test_o5_clean_older_install_gets_one_commit_of_exactly_the_changed_paths(self):
        repo = self.committed_install()
        head = self.head(repo)
        count = self.commit_count(repo)

        result, changed, _ = self.observed_update(repo)

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.commit_count(repo), count + 1)
        self.assertEqual(run_git(repo, "rev-parse", "HEAD^").stdout.strip(), head)
        self.assertGreaterEqual(len(changed), 2)
        self.assertEqual(self.commit_paths(repo), changed)
        lines = run_git(repo, "log", "-1", "--format=%B").stdout.splitlines()
        self.assertEqual(lines[0], f"Update harness {OLD_VERSION} -> {self.manifest_version(repo)}")
        self.assertEqual(lines[1:4], ["", "Request: harness.py update", "Intent: commit the files this harness update wrote"])
        self.assertEqual(self.status(repo), "")

    def test_o5_e2_update_at_current_version_that_still_changes_a_file_commits_with_equal_version_subject(self):
        repo = self.install()
        self.commit_all(repo)
        head = self.head(repo)
        count = self.commit_count(repo)

        result, changed, _ = self.observed_update(repo, "--model", "opus")

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertGreaterEqual(len(changed), 1)
        self.assertEqual(self.commit_count(repo), count + 1)
        self.assertEqual(run_git(repo, "rev-parse", "HEAD^").stdout.strip(), head)
        self.assertEqual(self.commit_paths(repo), changed)
        lines = run_git(repo, "log", "-1", "--format=%B").stdout.splitlines()
        self.assertEqual(lines[0], f"Update harness to {self.manifest_version(repo)}")
        self.assertEqual(lines[1:4], ["", "Request: harness.py update", "Intent: commit the files this harness update wrote"])
        self.assertEqual(self.status(repo), "")

    def test_t1_clean_candidates_with_commit_on_commit_and_report_full_commit_id(self):
        repo = self.committed_install()
        head = self.head(repo)

        result, _, _ = self.observed_update(repo)

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotEqual(self.head(repo), head)
        self.assertIn(f"auto-commit: {self.head(repo)}", self.items(result.stdout, "info"))
        self.assertNotIn(SKIP_PREFIX, result.stdout)

    def test_o6_unrelated_staged_file_stays_staged_and_out_of_the_commit(self):
        repo = self.committed_install(after_commit=lambda r: self.stage_unrelated(r))
        head = self.head(repo)

        result, changed, _ = self.observed_update(repo)

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotEqual(self.head(repo), head)
        self.assertNotIn("unrelated-notes.txt", self.commit_paths(repo))
        self.assertEqual(self.commit_paths(repo), [p for p in changed if p != "unrelated-notes.txt"])
        self.assertEqual(run_git(repo, "diff", "--cached", "--name-only").stdout.split(), ["unrelated-notes.txt"])
        self.assertNotIn(SKIP_PREFIX, result.stdout)

    def stage_unrelated(self, repo):
        (repo / "unrelated-notes.txt").write_text("user work\n")
        run_git(repo, "add", "--", "unrelated-notes.txt")

    def test_o4_b1_first_run_at_older_version_commits_and_b2_second_run_has_nothing_to_commit(self):
        repo = self.committed_install()
        old_agents = (repo / "AGENTS.md").read_text()

        first = self.update(repo)

        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        after_first = self.commit_count(repo)
        agents_after_first = (repo / "AGENTS.md").read_bytes()
        self.assertEqual(agents_after_first, self.expected_agents(old_agents))
        head = self.head(repo)

        second = self.update(repo)

        self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
        self.assertEqual(self.commit_count(repo), after_first)
        self.assertEqual(self.head(repo), head)
        self.assertIn("auto-commit: nothing to commit", self.items(second.stdout, "skip"))
        self.assertEqual((repo / "AGENTS.md").read_bytes(), agents_after_first)


class TestCommitDecisionTable(UpdateCommitCase):
    def test_t2_unstaged_candidate_warns_applies_and_makes_no_commit(self):
        repo = self.committed_install(after_commit=self.modify_settings_unstaged)
        old_agents = (repo / "AGENTS.md").read_text()

        result, changed, head = self.observed_update(repo)

        self.assert_skipped(repo, result, changed, head, [".claude/settings.json"])
        self.assert_applied(repo, old_agents)

    def test_t3_staged_candidate_warns_applies_and_makes_no_commit(self):
        repo = self.committed_install(after_commit=self.modify_claude_md_staged)
        old_agents = (repo / "AGENTS.md").read_text()

        result, changed, head = self.observed_update(repo)

        self.assert_skipped(repo, result, changed, head, ["CLAUDE.md"])
        self.assert_applied(repo, old_agents)

    def test_t4_untracked_candidate_warns_applies_and_makes_no_commit(self):
        repo = self.committed_install(untracked=[".codex/hooks.json"])
        old_agents = (repo / "AGENTS.md").read_text()
        self.assertIn("?? .codex/hooks.json", self.status(repo).split("\0"))

        result, changed, head = self.observed_update(repo)

        self.assert_skipped(repo, result, changed, head, [".codex/hooks.json"])
        self.assert_applied(repo, old_agents)

    MULTI_DIRTY = [".claude/settings.json", ".codex/hooks.json", "CLAUDE.md"]

    def multi_dirty_repo(self):
        def dirty(repo):
            self.modify_claude_md_staged(repo)
            self.modify_settings_unstaged(repo)

        return self.committed_install(after_commit=dirty, untracked=[".codex/hooks.json"])

    def test_t2_t3_t4_several_pre_dirty_candidates_are_all_listed_sorted_in_warning_and_commit_is_skipped(self):
        repo = self.multi_dirty_repo()
        old_agents = (repo / "AGENTS.md").read_text()

        result, changed, head = self.observed_update(repo)

        self.assert_skipped(repo, result, changed, head, self.MULTI_DIRTY)
        self.assertIn(
            "warning: auto-commit skipped: already modified: .claude/settings.json, .codex/hooks.json, CLAUDE.md",
            result.stdout.splitlines(),
        )
        self.assert_applied(repo, old_agents)

    def test_t8_dry_run_with_several_pre_dirty_candidates_lists_all_sorted_and_would_skip(self):
        repo = self.multi_dirty_repo()
        state, status, head = self.files_state(repo), self.status(repo), self.head(repo)

        result = run_installer("update", str(repo), "--dry-run", forbid_input=True)

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(
            "warning: auto-commit skipped: already modified: .claude/settings.json, .codex/hooks.json, CLAUDE.md",
            result.stdout.splitlines(),
        )
        self.assertIn("auto-commit: would skip", self.items(result.stdout, "info"))
        self.assertFalse([i for i in self.items(result.stdout, "manual review") if i.startswith("auto-commit skipped;")])
        self.assertEqual((self.head(repo), self.status(repo), self.files_state(repo)), (head, status, state))

    def test_t5_run_changing_a_pre_dirty_non_candidate_path_skips_the_commit_and_names_it(self):
        repo = self.install()
        self.prepare_stale_record(repo)
        self.commit_all(repo)
        source = repo / STALE_SOURCE
        source.write_text(source.read_text() + "user edit\n")
        head = self.head(repo)

        result, changed, _ = self.observed_update(repo)

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.head(repo), head)
        self.assertFalse(source.exists())
        self.assertIn(STALE_SOURCE, changed)
        self.assertNotIn(SKIP_PREFIX, result.stdout)
        self.assertIn(
            "auto-commit skipped: this update changed files that were already modified: "
            f"{STALE_SOURCE}; commit these files yourself: {self.listed(changed)}",
            self.items(result.stdout, "manual review"),
        )

    def test_t6_no_commit_flag_skips_warning_and_commit_even_with_pre_dirty_candidate(self):
        repo = self.committed_install(after_commit=self.modify_settings_unstaged)
        old_agents = (repo / "AGENTS.md").read_text()
        head = self.head(repo)

        result = self.update(repo, "--no-commit")

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.head(repo), head)
        self.assertNotIn("warning: auto-commit", result.stdout)
        self.assertNotRegex(result.stdout, r"auto-commit: [0-9a-f]{40}")
        self.assert_applied(repo, old_agents)

    def test_c10_no_commit_on_clean_older_install_writes_files_without_warning_or_commit(self):
        repo = self.committed_install()
        old_agents = (repo / "AGENTS.md").read_text()
        head = self.head(repo)

        result = self.update(repo, "--no-commit")

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.head(repo), head)
        self.assertNotIn("warning: auto-commit", result.stdout)
        self.assertNotRegex(result.stdout, r"auto-commit: [0-9a-f]{40}")
        self.assert_applied(repo, old_agents)
        self.assertNotEqual(self.status(repo), "")

    def test_t7_dry_run_on_clean_install_reports_would_commit_and_changes_nothing(self):
        repo = self.committed_install()
        state, status, head = self.files_state(repo), self.status(repo), self.head(repo)

        result = run_installer("update", str(repo), "--dry-run", forbid_input=True)

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("auto-commit: would commit the files this update writes", self.items(result.stdout, "info"))
        self.assertNotIn(SKIP_PREFIX, result.stdout)
        self.assertEqual((self.head(repo), self.status(repo), self.files_state(repo)), (head, status, state))

    def test_t8_dry_run_with_pre_dirty_candidate_reports_warning_and_would_skip(self):
        repo = self.committed_install(after_commit=self.modify_settings_unstaged)
        state, status, head = self.files_state(repo), self.status(repo), self.head(repo)

        result = run_installer("update", str(repo), "--dry-run", forbid_input=True)

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(f"{SKIP_PREFIX} already modified: .claude/settings.json", result.stdout.splitlines())
        info = self.items(result.stdout, "info")
        self.assertIn("auto-commit: would skip", info)
        self.assertNotIn("auto-commit: would commit the files this update writes", info)
        self.assertEqual((self.head(repo), self.status(repo), self.files_state(repo)), (head, status, state))

    def test_o8_pre_dirty_warning_is_printed_before_the_first_migration_prompt(self):
        repo = self.committed_install(after_commit=self.modify_settings_unstaged)

        result = self.update(repo)

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("Apply migration", result.stdout)
        warning = f"{SKIP_PREFIX} already modified: .claude/settings.json"
        self.assertIn(warning, result.stdout)
        self.assertLess(result.stdout.index(warning), result.stdout.index("Apply migration"))


class TestCommitFailure(UpdateCommitCase):
    def isolated_env(self, **extra):
        empty = tempfile.TemporaryDirectory()
        self.addCleanup(empty.cleanup)
        env = {
            k: v for k, v in os.environ.items()
            if not k.startswith(("GIT_AUTHOR", "GIT_COMMITTER")) and k not in ("EMAIL", "GIT_CONFIG_GLOBAL", "GIT_CONFIG_SYSTEM")
        }
        env.update(HOME=empty.name, XDG_CONFIG_HOME=empty.name, GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull)
        env.update(extra)
        return env

    def assert_failed_commit(self, repo, result, changed, head, old_agents):
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.head(repo), head)
        self.assert_applied(repo, old_agents)
        failures = [i for i in self.items(result.stdout, "manual review") if i.startswith("auto-commit failed: ")]
        self.assertEqual(len(failures), 1, result.stdout)
        suffix = f"; commit these files yourself: {self.listed(changed)}"
        self.assertTrue(failures[0].endswith(suffix), failures[0])
        reason = failures[0][len("auto-commit failed: "):-len(suffix)]
        self.assertTrue(reason.strip(), failures[0])
        self.assertNotIn("\n", reason)
        return reason

    def test_f1_missing_git_identity_reports_failure_keeps_files_and_head(self):
        def drop_identity(repo):
            run_git(repo, "config", "--unset", "user.email")
            run_git(repo, "config", "--unset", "user.name")
            run_git(repo, "config", "user.useConfigOnly", "true")

        repo = self.committed_install(after_commit=drop_identity)
        old_agents = (repo / "AGENTS.md").read_text()

        result, changed, head = self.observed_update(repo, env=self.isolated_env())

        self.assert_failed_commit(repo, result, changed, head, old_agents)

    def test_f2_rejecting_pre_commit_hook_reports_failure_keeps_files_and_head(self):
        hooks = tempfile.TemporaryDirectory()
        self.addCleanup(hooks.cleanup)
        hook = Path(hooks.name) / "pre-commit"
        hook.write_text("#!/bin/sh\necho rejected-by-test-hook >&2\nexit 1\n")
        hook.chmod(hook.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        env = {**os.environ, "GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "core.hooksPath", "GIT_CONFIG_VALUE_0": hooks.name}
        repo = self.committed_install()
        old_agents = (repo / "AGENTS.md").read_text()

        result, changed, head = self.observed_update(repo, env=env)

        reason = self.assert_failed_commit(repo, result, changed, head, old_agents)
        self.assertIn("rejected-by-test-hook", reason)


class TestInstallDoesNotCommit(UpdateCommitCase):
    def test_i1_install_creates_no_commit(self):
        repo = self.make_repo()

        result = run_installer("install", str(repo))

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(run_git(repo, "rev-list", "--all", "--count").stdout.strip(), "0")

    def test_i1_install_into_repo_with_history_keeps_head(self):
        repo = self.make_repo()
        (repo / "readme.txt").write_text("x\n")
        self.commit_all(repo)
        head = self.head(repo)

        result = run_installer("install", str(repo))

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.head(repo), head)

    def test_i2_no_commit_flag_is_a_parser_error_for_commands_other_than_update(self):
        for command in ("install", "doctor", "import"):
            with self.subTest(command=command):
                repo = self.make_repo()

                result = run_installer(command, str(repo), "--no-commit")

                self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                self.assertIn("--no-commit", result.stderr)
                self.assertEqual(self.snapshot(repo), {})


class TestInstallerRunRecord(UpdateCommitCase):
    def fingerprint(self, repo):
        return load_progress().git_worktree_fingerprint(repo, ".harness/")

    def record(self, repo):
        return json.loads((repo / INSTALLER_RUN_RECORD).read_text())

    def test_h6_successful_update_records_pre_and_post_fingerprints(self):
        repo = self.committed_install()
        before = self.fingerprint(repo)

        result = self.update(repo)

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        record = self.record(repo)
        self.assertEqual(record["before"], before)
        self.assertEqual(record["after"], self.fingerprint(repo))
        self.assertNotEqual(record["before"], record["after"])

    def test_h7_declined_migration_exit_writes_record_and_makes_no_commit(self):
        repo = self.committed_install()
        before = self.fingerprint(repo)
        head = self.head(repo)

        result = self.update(repo, answers="n\n")

        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertEqual(self.head(repo), head)
        record = self.record(repo)
        self.assertEqual(record["before"], before)
        self.assertEqual(record["after"], self.fingerprint(repo))

    def test_dry_run_writes_no_record(self):
        repo = self.committed_install()

        result = run_installer("update", str(repo), "--dry-run", forbid_input=True)

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse((repo / INSTALLER_RUN_RECORD).exists())

    def test_h8_gitignore_lists_the_record_after_install_and_after_update(self):
        installed = self.install()
        self.assertIn(INSTALLER_RUN_RECORD, [l.lstrip("/") for l in (installed / ".gitignore").read_text().splitlines()])

        def drop_line(repo):
            ignore = repo / ".gitignore"
            kept = [line for line in ignore.read_text().splitlines() if line.lstrip("/") != INSTALLER_RUN_RECORD]
            ignore.write_text("\n".join(kept) + "\n")

        repo = self.committed_install(before_commit=drop_line)
        self.assertNotIn(INSTALLER_RUN_RECORD, [l.lstrip("/") for l in (repo / ".gitignore").read_text().splitlines()])

        result = self.update(repo)

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(INSTALLER_RUN_RECORD, [l.lstrip("/") for l in (repo / ".gitignore").read_text().splitlines()])
        self.assertEqual(run_git(repo, "check-ignore", "-q", "--", INSTALLER_RUN_RECORD).returncode, 0)
        self.assertNotIn(INSTALLER_RUN_RECORD, self.commit_paths(repo))
        self.assertEqual(self.status(repo), "")


class TestMigration0400(UpdateCommitCase):
    LABEL = "import the managed block; auto-commit updates; exempt update changes from progress"
    PLAN = [
        "the AGENTS.md managed block becomes an import of .harness/instructions/harness-block.md",
        "update commits the files it changed, skips the commit when any of them was already modified, and --no-commit disables it",
        "changes made by harness.py update alone inside one Claude Code Bash call no longer require a session progress",
        "no data is migrated; the regular update step rewrites the managed block",
    ]

    def test_o12_update_from_0390_announces_the_0400_migration_with_its_plan_lines_in_order(self):
        repo = self.committed_install()

        result = self.update(repo)

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(f"migration 0.40.0: {self.LABEL}", result.stdout)
        start = result.stdout.index("migration 0.40.0:")
        positions = []
        for line in self.PLAN:
            self.assertIn(line, result.stdout[start:])
            positions.append(result.stdout.index(line, start))
        self.assertEqual(positions, sorted(positions))
        self.assertLess(positions[-1], result.stdout.index("Apply migration 0.40.0"))
        doctor = run_installer("doctor", str(repo))
        self.assertEqual(doctor.returncode, 0, doctor.stdout + doctor.stderr)


if __name__ == "__main__":
    unittest.main()

import json
import os
import stat
import subprocess
import sys

from test_installer import InstallerTestCase, run_git, run_installer

COMMIT_WARNING = "commit-msg: the message has no"
PR_REMINDER = "five-minute standup introduction"


class MessageNudgeTestCase(InstallerTestCase):
    def installed(self):
        repo = self.make_repo()
        result = run_installer("install", str(repo), "--no-ci")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return repo

    def commit(self, repo, message, *extra):
        (repo / "file.txt").write_text(message)
        run_git(repo, "add", "-A")
        return subprocess.run(
            ["git", "-C", str(repo), "commit", "-q", *extra, "-m", message], capture_output=True, text=True
        )

    def run_pr_hook(self, repo, command):
        payload = {"hook_event_name": "PostToolUse", "tool_name": "Bash", "cwd": str(repo),
                   "tool_input": {"command": command}}
        return subprocess.run(
            [sys.executable, str(repo / ".harness" / "hooks" / "pr_message_nudge.py")],
            input=json.dumps(payload), capture_output=True, text=True,
        )


class TestCommitMessageNudge(MessageNudgeTestCase):
    def test_missing_trailers_warn_without_blocking(self):
        repo = self.installed()
        result = self.commit(repo, "Add feature")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(COMMIT_WARNING + " `Request:`, `Intent:` line", result.stderr)
        self.assertEqual(run_git(repo, "log", "-1", "--format=%s").stdout.strip(), "Add feature")

    def test_one_missing_trailer_is_named(self):
        repo = self.installed()
        result = self.commit(repo, "Add feature\n\nRequest: add the feature")
        self.assertIn(COMMIT_WARNING + " `Intent:` line", result.stderr)

    def test_both_trailers_are_quiet(self):
        repo = self.installed()
        result = self.commit(repo, "Add feature\n\nRequest: add the feature\nIntent: let users do X")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn(COMMIT_WARNING, result.stderr)

    def test_empty_trailer_value_still_warns(self):
        repo = self.installed()
        result = self.commit(repo, "Add feature\n\nRequest:\nIntent: let users do X")
        self.assertIn(COMMIT_WARNING + " `Request:` line", result.stderr)

    def test_generated_subjects_are_exempt(self):
        repo = self.installed()
        for subject in ("Merge branch 'x'", 'Revert "Add feature"', "fixup! Add feature", "squash! Add feature", "amend! Add feature"):
            with self.subTest(subject=subject):
                self.assertNotIn(COMMIT_WARNING, self.commit(repo, subject).stderr)

    def test_installed_hook_is_executable_and_chains_local_hook(self):
        repo = self.installed()
        hook = repo / ".harness" / "git" / "commit-msg"
        self.assertTrue(os.stat(hook).st_mode & stat.S_IXUSR)
        local = repo / ".git" / "hooks" / "commit-msg"
        local.write_text("#!/bin/sh\necho local-commit-msg >&2\n")
        local.chmod(0o755)
        result = self.commit(repo, "Add feature\n\nRequest: r\nIntent: i")
        self.assertIn("local-commit-msg", result.stderr)


class TestPrMessageNudge(MessageNudgeTestCase):
    def test_pr_create_reminds_agent_via_exit_2(self):
        repo = self.installed()
        result = self.run_pr_hook(repo, 'gh pr create --title "x" --body "$(cat <<EOF\nbody\nEOF\n)"')
        self.assertEqual(result.returncode, 2)
        self.assertIn(PR_REMINDER, result.stderr)
        for command in ("git push && gh pr create --fill", "cd x; gh pr create", "(gh pr create -t x)"):
            with self.subTest(command=command):
                self.assertEqual(self.run_pr_hook(repo, command).returncode, 2)

    def test_pr_edit_reminds_only_with_body_flag(self):
        repo = self.installed()
        for command in ("gh pr edit 12 --body-file pr.md", "gh pr edit 12 -b new", "gh pr edit --body=x"):
            with self.subTest(command=command):
                self.assertEqual(self.run_pr_hook(repo, command).returncode, 2)
        self.assertEqual(self.run_pr_hook(repo, "gh pr edit 12 --add-label bug").returncode, 0)

    def test_unrelated_commands_are_quiet(self):
        repo = self.installed()
        for command in ("gh pr view 12", "git commit -m x", "echo gh pr",
                        "echo 'run gh pr create later'", "python3 - <<'EOF'\ns = '`gh pr create`'\nEOF"):
            with self.subTest(command=command):
                result = self.run_pr_hook(repo, command)
                self.assertEqual(result.returncode, 0)
                self.assertEqual(result.stderr, "")

    def test_claude_settings_register_the_hook_for_bash(self):
        repo = self.installed()
        settings = json.loads((repo / ".claude" / "settings.json").read_text())
        groups = [g for g in settings["hooks"]["PostToolUse"] if "pr_message_nudge.py" in g["hooks"][0]["command"]]
        self.assertEqual([g["matcher"] for g in groups], ["Bash"])

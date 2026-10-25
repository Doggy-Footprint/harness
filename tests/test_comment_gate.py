import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
WARN = REPO_ROOT / "harness" / "git" / "warn_new_comments.py"
INSTALLER = REPO_ROOT / "installer" / "harness.py"
WORKFLOW = REPO_ROOT / "harness" / "ci" / "harness-comment-warning.yml"
AGENT_SENTENCE = "If you are an AI agent, report every added comment above to the user."
_TARGETS_DIR = tempfile.TemporaryDirectory()
os.environ["HARNESS_TARGETS_FILE"] = str(Path(_TARGETS_DIR.name) / "targets.json")


def git(cwd, *args, check=True):
    return subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True, check=check)


class RepoTestCase(unittest.TestCase):
    def make_repo(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        repo = Path(tmp.name)
        git(repo, "init", "-q")
        git(repo, "config", "user.email", "test@test.com")
        git(repo, "config", "user.name", "test")
        git(repo, "config", "commit.gpgsign", "false")
        return repo

    def commit_file(self, repo, name, text, msg="c"):
        path = repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        git(repo, "add", name)
        git(repo, "commit", "-q", "-m", msg)
        return git(repo, "rev-parse", "HEAD").stdout.strip()

    def run_warn(self, cwd, *args):
        return subprocess.run([sys.executable, str(WARN), *args], cwd=cwd, capture_output=True, text=True)


class StagedModeTests(RepoTestCase):
    # O1 EP1
    def test_ep1_staged_comment_reports_path_line_and_agent_sentence(self):
        repo = self.make_repo()
        self.commit_file(repo, "a.py", "x = 1\ny = 2\n")
        (repo / "a.py").write_text("x = 1\ny = 2\n# note\n")
        git(repo, "add", "a.py")
        r = self.run_warn(repo, "--staged")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("a.py:3: # note", r.stderr)
        self.assertIn(AGENT_SENTENCE, r.stderr)

    # O1 EP2
    def test_ep2_no_comment_prints_nothing(self):
        repo = self.make_repo()
        self.commit_file(repo, "a.py", "x = 1\n")
        (repo / "a.py").write_text("x = 1\ny = 2\n")
        git(repo, "add", "a.py")
        r = self.run_warn(repo, "--staged")
        self.assertEqual(r.returncode, 0)
        self.assertEqual(r.stderr, "")

    # O1 EP3
    def test_ep3_unstaged_comment_not_reported(self):
        repo = self.make_repo()
        self.commit_file(repo, "a.py", "x = 1\n")
        self.commit_file(repo, "b.py", "z = 1\n")
        (repo / "b.py").write_text("z = 1\nw = 2\n")
        git(repo, "add", "b.py")
        (repo / "a.py").write_text("x = 1\n# note\n")
        r = self.run_warn(repo, "--staged")
        self.assertEqual(r.returncode, 0)
        self.assertNotIn("# note", r.stderr)
        self.assertNotIn(AGENT_SENTENCE, r.stderr)

    # O1 EP4
    def test_ep4_non_code_extension_not_reported(self):
        repo = self.make_repo()
        self.commit_file(repo, "a.md", "text\n")
        (repo / "a.md").write_text("text\n# note\n")
        git(repo, "add", "a.md")
        r = self.run_warn(repo, "--staged")
        self.assertEqual(r.returncode, 0)
        self.assertNotIn("# note", r.stderr)
        self.assertNotIn(AGENT_SENTENCE, r.stderr)

    # O1 EP5
    def test_ep5_outside_repository_exits_zero_with_message(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        r = self.run_warn(tmp.name, "--staged")
        self.assertEqual(r.returncode, 0)
        self.assertNotEqual(r.stderr.strip(), "")


class HookTests(RepoTestCase):
    def install(self):
        repo = self.make_repo()
        r = subprocess.run([sys.executable, str(INSTALLER), "install", str(repo)], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return repo

    def commit(self, repo):
        return subprocess.run(["git", "-C", str(repo), "commit", "-m", "t"], capture_output=True, text=True)

    def head_exists(self, repo):
        return git(repo, "rev-parse", "--verify", "HEAD", check=False).returncode == 0

    # O2 S1
    def test_s1_commit_with_comment_succeeds_and_warns(self):
        repo = self.install()
        (repo / "a.py").write_text("x = 1\n# note\n")
        git(repo, "add", "a.py")
        r = self.commit(repo)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertTrue(self.head_exists(repo))
        self.assertIn(AGENT_SENTENCE, r.stderr)

    def violation(self, repo):
        records = repo / "agent-docs" / "try-n-fail"
        records.mkdir(parents=True, exist_ok=True)
        (records / "index.md").unlink(missing_ok=True)
        (records / "0123456789abcdef-x.md").write_text("# X\n")
        git(repo, "add", "-f", "agent-docs/try-n-fail/0123456789abcdef-x.md")

    # O2 S2
    def test_s2_verify_rules_violation_still_blocks_commit(self):
        repo = self.install()
        self.violation(repo)
        r = self.commit(repo)
        self.assertNotEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertFalse(self.head_exists(repo))

    # O2 S3
    def test_s3_warning_precedes_verify_rules_output(self):
        repo = self.install()
        self.violation(repo)
        (repo / "a.py").write_text("x = 1\n# note\n")
        git(repo, "add", "a.py")
        r = self.commit(repo)
        self.assertNotEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn(AGENT_SENTENCE, r.stderr)
        self.assertIn("harness rule violations found", r.stderr)
        self.assertLess(r.stderr.index(AGENT_SENTENCE), r.stderr.index("harness rule violations found"))


    # O2 S4
    def test_s4_failing_warning_script_does_not_block_commit(self):
        repo = self.install()
        (repo / ".harness" / "git" / "warn_new_comments.py").write_text("import sys\nsys.exit(3)\n")
        (repo / "a.py").write_text("x = 1\n")
        git(repo, "add", "a.py")
        r = self.commit(repo)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertTrue(self.head_exists(repo))

    # O2 S5
    def test_s5_missing_python3_skips_and_commit_succeeds(self):
        import os
        import shutil
        repo = self.install()
        bindir = tempfile.TemporaryDirectory()
        self.addCleanup(bindir.cleanup)
        for name in ("git", "sh", "bash", "env", "cat", "dirname", "basename", "grep", "sed", "awk",
                     "tr", "head", "tail", "sort", "uname", "ls", "mkdir", "rm", "mktemp", "cut", "wc", "xargs", "printf", "test", "expr"):
            found = shutil.which(name)
            if found:
                os.symlink(found, os.path.join(bindir.name, name))
        env = dict(os.environ, PATH=bindir.name)
        probe = subprocess.run([shutil.which("sh"), "-c", "command -v python3"], env=env, capture_output=True, text=True)
        self.assertNotEqual(probe.returncode, 0, "python3 still resolvable: " + probe.stdout)
        (repo / "a.py").write_text("x = 1\n")
        git(repo, "add", "a.py")
        r = subprocess.run([shutil.which("git"), "-C", str(repo), "commit", "-m", "t"], env=env, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertTrue(self.head_exists(repo))
        self.assertIn("python3 not found", r.stderr)


class GateTests(RepoTestCase):
    def pair(self, with_comment):
        repo = self.make_repo()
        base = self.commit_file(repo, "a.py", "x = 1\n")
        head = self.commit_file(repo, "a.py", "x = 1\n# note\n" if with_comment else "x = 1\ny = 2\n")
        return repo, base, head

    # O3 D1
    def test_d1_comment_not_approved_fails_with_warning(self):
        repo, b, h = self.pair(True)
        r = self.run_warn(repo, b, h, "--approved", "no")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("::warning", r.stdout)

    # O3 D2
    def test_d2_comment_approved_passes(self):
        repo, b, h = self.pair(True)
        r = self.run_warn(repo, b, h, "--approved", "yes")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("::warning", r.stdout)

    # O3 D3
    def test_d3_no_comment_not_approved_passes(self):
        repo, b, h = self.pair(False)
        r = self.run_warn(repo, b, h, "--approved", "no")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertNotIn("::warning", r.stdout)

    # O3 D4
    def test_d4_no_comment_approved_passes(self):
        repo, b, h = self.pair(False)
        r = self.run_warn(repo, b, h, "--approved", "yes")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertNotIn("::warning", r.stdout)

    def test_unapproved_failure_names_required_label(self):
        repo, b, h = self.pair(True)
        r = self.run_warn(repo, b, h, "--approved", "no")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        errors = [l for l in r.stdout.splitlines() if l.startswith("::error")]
        self.assertEqual(len(errors), 1, r.stdout)
        self.assertIn("`comments-approved` label", errors[0])

    def test_approved_or_ungated_run_prints_no_label_error(self):
        repo, b, h = self.pair(True)
        for args in ((b, h, "--approved", "yes"), (b, h)):
            with self.subTest(args=args):
                r = self.run_warn(repo, *args)
                self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
                self.assertNotIn("::error", r.stdout)

    # O3 D5
    def test_d5_invalid_approved_value_exits_two(self):
        repo, b, h = self.pair(True)
        r = self.run_warn(repo, b, h, "--approved", "maybe")
        self.assertEqual(r.returncode, 2)
        self.assertNotEqual(r.stderr.strip(), "")

    # O3 D6
    def test_d6_two_arg_mode_with_comment_exits_zero(self):
        repo, b, h = self.pair(True)
        r = self.run_warn(repo, b, h)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("::warning", r.stdout)

    # O3 D7
    def test_d7_wrong_positional_count_in_gate_mode_exits_two(self):
        repo, b, h = self.pair(True)
        for args in ((b, "--approved", "no"), (b, h, h, "--approved", "no")):
            with self.subTest(args=args):
                r = self.run_warn(repo, *args)
                self.assertEqual(r.returncode, 2, r.stdout + r.stderr)


class WorkflowTextTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = WORKFLOW.read_text()

    # O4 Y1
    def test_y1_trigger_types(self):
        m = re.search(r"pull_request:\s*\n\s*types:\s*\[([^\]]*)\]", self.text)
        if m:
            types = [t.strip().strip("'\"") for t in m.group(1).split(",")]
        else:
            m = re.search(r"pull_request:\s*\n\s*types:\s*\n((?:\s*-\s*\S+\s*\n)+)", self.text)
            self.assertIsNotNone(m, "pull_request types not found")
            types = re.findall(r"-\s*(\S+)", m.group(1))
        self.assertEqual(sorted(types), sorted(["opened", "synchronize", "reopened", "labeled", "unlabeled"]))

    # O4 Y2
    def test_y2_permissions_exact(self):
        m = re.search(r"^permissions:\s*\n((?:[ \t]+\S.*\n?)+)", self.text, re.MULTILINE)
        self.assertIsNotNone(m, "top-level permissions not found")
        perms = dict(re.findall(r"^\s+([\w-]+):\s*(\S+)", m.group(1), re.MULTILINE))
        self.assertEqual(perms, {"contents": "read", "pull-requests": "write", "issues": "write"})

    def steps(self):
        parts = re.split(r"^\s*-\s+(?=name:|uses:|run:|id:|if:)", self.text, flags=re.MULTILINE)
        return parts[1:]

    # O4 Y3
    def test_y3_synchronize_label_removal_step_continues_on_error(self):
        blocks = [s for s in self.steps() if "synchronize" in s and "comments-approved" in s and "continue-on-error" in s]
        self.assertTrue(blocks, "no synchronize label-removal step with continue-on-error")
        b = blocks[0]
        self.assertRegex(b, r"if:.*github\.event\.action\s*==\s*'synchronize'")
        self.assertRegex(b, r"continue-on-error:\s*true")
        self.assertIn("gh api -X DELETE", b)
        self.assertIn("labels/comments-approved", b)

    # O4 Y4
    def test_y4_approved_expression(self):
        lines = [l for l in self.text.splitlines() if "--approved" in l]
        self.assertTrue(lines, "no line passes --approved")
        parts = [
            "github.event.action != 'synchronize'",
            "contains(github.event.pull_request.labels.*.name, 'comments-approved')",
            "'yes' || 'no'",
        ]
        ok = False
        for l in lines:
            if all(p in l for p in parts):
                idx = [l.index(p) for p in parts]
                ok = ok or idx == sorted(idx)
        self.assertTrue(ok, lines)

    # O4 Y5
    def test_y5_no_pull_request_target(self):
        self.assertNotIn("pull_request_target", self.text)


class MigrationTests(RepoTestCase):
    # O5 M1 M2
    def test_m1_m2_update_from_0240_announces_0250_and_records_version(self):
        repo = self.make_repo()
        r = subprocess.run([sys.executable, str(INSTALLER), "install", str(repo)], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        mp = repo / ".harness" / "manifest.json"
        manifest = json.loads(mp.read_text())
        manifest["version"] = "0.24.0"
        mp.write_text(json.dumps(manifest, indent=2) + "\n")
        r = subprocess.run([sys.executable, str(INSTALLER), "update", str(repo)], input="y\n" * 10, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("migration 0.25.0", r.stdout)  # M1
        self.assertEqual(json.loads(mp.read_text())["version"], (REPO_ROOT / "harness" / "VERSION").read_text().strip())  # M2
        # O5 M3
        after = r.stdout.split("migration 0.25.0", 1)[1]
        section = re.split(r"^migration ", after, maxsplit=1, flags=re.MULTILINE)[0]
        self.assertIn("comments-approved", section)
        self.assertIn("branch protection", section)


FAKE_GH = """#!/bin/sh
echo "$(pwd -P)|$GH_PROMPT_DISABLED|$*" >> "$FAKE_GH_LOG"
case "$1" in
  api) exit "${FAKE_GH_API_EXIT:-1}" ;;
  label)
    [ -n "$FAKE_GH_CREATE_ERR" ] && echo "$FAKE_GH_CREATE_ERR" >&2
    exit "${FAKE_GH_CREATE_EXIT:-0}" ;;
esac
exit 3
"""
LABEL_COMMAND = 'gh label create comments-approved --color 0E8A16 --description "New comments and docstrings reviewed"'


class LabelSetupTests(RepoTestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.bindir = Path(tmp.name)
        self.log = self.bindir / "gh.log"
        gh = self.bindir / "gh"
        gh.write_text(FAKE_GH)
        gh.chmod(0o755)

    def run_installer(self, *args, path=None, input="", **fake_env):
        env = dict(os.environ, FAKE_GH_LOG=str(self.log), **fake_env)
        env["PATH"] = path if path is not None else f"{self.bindir}{os.pathsep}{os.environ['PATH']}"
        return subprocess.run(
            [sys.executable, str(INSTALLER), *args], env=env, input=input, capture_output=True, text=True
        )

    def remote_repo(self):
        repo = self.make_repo()
        git(repo, "remote", "add", "origin", "https://github.com/example/project.git")
        return repo

    def gh_calls(self):
        return self.log.read_text().splitlines() if self.log.exists() else []

    def section(self, stdout, name):
        if f"== {name} ==\n" not in stdout:
            return ""
        return stdout.split(f"== {name} ==\n", 1)[1].split("\n== ", 1)[0]

    def test_install_creates_missing_label_in_target_repo(self):
        repo = self.remote_repo()
        r = self.run_installer("install", str(repo))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        calls = self.gh_calls()
        self.assertEqual(len(calls), 2, calls)
        for call in calls:
            cwd, prompt_disabled, _ = call.split("|", 2)
            self.assertEqual(cwd, str(repo.resolve()))
            self.assertEqual(prompt_disabled, "1")
        self.assertEqual(calls[0].split("|", 2)[2], "api repos/{owner}/{repo}/labels/comments-approved")
        self.assertEqual(
            calls[1].split("|", 2)[2],
            "label create comments-approved --color 0E8A16 --description New comments and docstrings reviewed",
        )
        self.assertIn("- GitHub label comments-approved\n", self.section(r.stdout, "write") + "\n")
        self.assertNotIn("comments-approved", self.section(r.stdout, "manual review"))

    def test_existing_label_is_not_recreated(self):
        repo = self.remote_repo()
        r = self.run_installer("install", str(repo), FAKE_GH_API_EXIT="0")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual([c.split("|", 2)[2].split()[0] for c in self.gh_calls()], ["api"])
        self.assertIn("GitHub label comments-approved already exists", self.section(r.stdout, "skip"))
        self.assertNotIn("comments-approved", self.section(r.stdout, "write"))

    def test_create_failure_reports_reason_and_command_without_failing(self):
        repo = self.remote_repo()
        r = self.run_installer(
            "install", str(repo), FAKE_GH_CREATE_EXIT="1", FAKE_GH_CREATE_ERR="HTTP 403: Resource not accessible"
        )
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        manual = self.section(r.stdout, "manual review")
        self.assertIn("HTTP 403: Resource not accessible", manual)
        self.assertIn(LABEL_COMMAND, manual)
        self.assertTrue((repo / ".harness" / "manifest.json").exists())

    def test_no_remote_skips_gh_and_reports_command(self):
        repo = self.make_repo()
        r = self.run_installer("install", str(repo))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.gh_calls(), [])
        manual = self.section(r.stdout, "manual review")
        self.assertIn("no git remote configured", manual)
        self.assertIn(LABEL_COMMAND, manual)

    def test_missing_gh_reports_command(self):
        repo = self.remote_repo()
        only_git = self.bindir / "only-git"
        only_git.mkdir()
        os.symlink(shutil.which("git"), only_git / "git")
        r = self.run_installer("install", str(repo), path=str(only_git))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        manual = self.section(r.stdout, "manual review")
        self.assertIn("gh CLI not found", manual)
        self.assertIn(LABEL_COMMAND, manual)

    def test_no_ci_and_dry_run_never_call_gh(self):
        no_ci = self.run_installer("install", str(self.remote_repo()), "--no-ci")
        self.assertEqual(no_ci.returncode, 0, no_ci.stdout + no_ci.stderr)
        self.assertNotIn("comments-approved", no_ci.stdout)
        dry = self.run_installer("install", str(self.remote_repo()), "--dry-run")
        self.assertEqual(dry.returncode, 0, dry.stdout + dry.stderr)
        self.assertIn("GitHub label comments-approved (if missing)", self.section(dry.stdout, "write"))
        self.assertEqual(self.gh_calls(), [])

    def test_update_from_0250_announces_and_creates_label(self):
        repo = self.remote_repo()
        r = self.run_installer("install", str(repo), "--no-ci")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        mp = repo / ".harness" / "manifest.json"
        manifest = json.loads(mp.read_text())
        manifest["version"] = "0.25.0"
        mp.write_text(json.dumps(manifest, indent=2) + "\n")
        r = self.run_installer("update", str(repo), input="y\ny\ny\ny\ny\n")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(re.findall(r"^migration (\S+):", r.stdout, re.MULTILINE), ["0.26.0", "0.27.0", "0.28.0", "0.29.0", "0.30.0"])
        section = r.stdout.split("migration 0.26.0", 1)[1].split("Apply migration", 1)[0]
        self.assertIn("comments-approved", section)
        self.assertEqual([c.split("|", 2)[2].split()[:2] for c in self.gh_calls()], [["api", "repos/{owner}/{repo}/labels/comments-approved"], ["label", "create"]])
        self.assertIn("- GitHub label comments-approved\n", self.section(r.stdout, "write") + "\n")


if __name__ == "__main__":
    unittest.main()

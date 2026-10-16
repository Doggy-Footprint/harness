import json
import re
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
        adr = repo / "agent-docs" / "adr"
        adr.mkdir(parents=True, exist_ok=True)
        (adr / "index.md").unlink(missing_ok=True)
        (adr / "0123456789abcdef-x.md").write_text("# X\n")
        git(repo, "add", "-f", "agent-docs/adr/0123456789abcdef-x.md")

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
        self.assertEqual(json.loads(mp.read_text())["version"], "0.25.0")  # M2
        # O5 M3
        after = r.stdout.split("migration 0.25.0", 1)[1]
        section = re.split(r"^migration ", after, maxsplit=1, flags=re.MULTILINE)[0]
        self.assertIn("comments-approved", section)
        self.assertIn("branch protection", section)


if __name__ == "__main__":
    unittest.main()

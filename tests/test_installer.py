import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
INSTALLER = REPO_ROOT / "installer" / "harness.py"


def run_installer(*args):
    return subprocess.run(
        [sys.executable, str(INSTALLER)] + list(args),
        capture_output=True,
        text=True,
    )


def run_git(cwd, *args):
    return subprocess.run(
        ["git", "-C", str(cwd)] + list(args),
        capture_output=True,
        text=True,
        check=True,
    )


class InstallerTestCase(unittest.TestCase):
    def make_repo(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        repo = Path(tmp.name)
        run_git(repo, "init", "-q")
        run_git(repo, "config", "user.email", "test@test.com")
        run_git(repo, "config", "user.name", "test")
        return repo

    def snapshot(self, repo):
        files = {}
        for path in repo.rglob("*"):
            if ".git" in path.relative_to(repo).parts:
                continue
            if path.is_file():
                files[str(path.relative_to(repo))] = hashlib.sha256(path.read_bytes()).hexdigest()
        return files


class TestScenarios(InstallerTestCase):
    def test_a_empty_repo_install_then_doctor(self):
        repo = self.make_repo()
        result = run_installer("install", str(repo))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

        result = run_installer("doctor", str(repo))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

        verify = subprocess.run(
            [sys.executable, str(repo / ".harness" / "git" / "verify_rules.py")],
            capture_output=True,
            text=True,
        )
        self.assertEqual(verify.returncode, 0, verify.stdout + verify.stderr)

    def test_b_claude_md_only(self):
        repo = self.make_repo()
        (repo / "CLAUDE.md").write_text("hello")

        result = run_installer("install", str(repo))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

        agents_md = (repo / "AGENTS.md").read_text()
        self.assertIn("<!-- harness:begin", agents_md)
        self.assertIn("<!-- harness:end -->", agents_md)

        claude_md = (repo / "CLAUDE.md").read_text()
        self.assertTrue(claude_md.startswith("@AGENTS.md"))
        self.assertIn("hello", claude_md)

    def test_b2_identical_agents_and_claude(self):
        repo = self.make_repo()
        content = "# Same content\n\nBody text.\n"
        (repo / "AGENTS.md").write_text(content)
        (repo / "CLAUDE.md").write_text(content)

        result = run_installer("install", str(repo))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

        claude_md = (repo / "CLAUDE.md").read_text()
        self.assertEqual(claude_md, "@AGENTS.md\n")

    def test_c_settings_preserved_and_upgrade_no_duplicate(self):
        repo = self.make_repo()
        (repo / ".claude").mkdir()
        original_settings = {
            "permissions": {"allow": ["Bash(ls)"]},
            "hooks": {
                "PreToolUse": [
                    {"matcher": "Write", "hooks": [{"type": "command", "command": "echo hi"}]}
                ]
            },
        }
        (repo / ".claude" / "settings.json").write_text(json.dumps(original_settings, indent=2))

        result = run_installer("install", str(repo))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

        settings = json.loads((repo / ".claude" / "settings.json").read_text())
        self.assertEqual(settings["permissions"], {"allow": ["Bash(ls)"]})
        pretool = settings["hooks"]["PreToolUse"]
        unrelated = [g for g in pretool if g.get("matcher") == "Write"]
        self.assertEqual(len(unrelated), 1)
        harness_bash = [
            g for g in pretool
            if g.get("matcher") == "Bash"
            and any("/.harness/" in h["command"] for h in g["hooks"])
        ]
        self.assertEqual(len(harness_bash), 1)

        result = run_installer("upgrade", str(repo))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

        settings = json.loads((repo / ".claude" / "settings.json").read_text())
        pretool = settings["hooks"]["PreToolUse"]
        harness_bash = [
            g for g in pretool
            if g.get("matcher") == "Bash"
            and any("/.harness/" in h["command"] for h in g["hooks"])
        ]
        self.assertEqual(len(harness_bash), 1)
        unrelated = [g for g in pretool if g.get("matcher") == "Write"]
        self.assertEqual(len(unrelated), 1)

    def test_d_husky_hooks_path_untouched(self):
        repo = self.make_repo()
        (repo / ".husky").mkdir()
        run_git(repo, "config", "core.hooksPath", ".husky")

        result = run_installer("install", str(repo))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

        current = run_git(repo, "config", "--get", "core.hooksPath").stdout.strip()
        self.assertEqual(current, ".husky")
        self.assertIn("manual review", result.stdout)

    def test_e_existing_agent_file_conflicts(self):
        repo = self.make_repo()
        (repo / ".claude" / "agents").mkdir(parents=True)
        (repo / ".claude" / "agents" / "implementer.md").write_text("mine")

        before = self.snapshot(repo)
        result = run_installer("install", str(repo))
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        after = self.snapshot(repo)
        self.assertEqual(before, after)

    def test_f_reinstall_idempotent_after_commit(self):
        repo = self.make_repo()
        result = run_installer("install", str(repo))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

        run_git(repo, "add", "-A")
        run_git(repo, "commit", "-q", "-m", "install harness")

        result = run_installer("upgrade", str(repo))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

        status = run_git(repo, "status", "--porcelain").stdout
        self.assertEqual(status.strip(), "")

    def test_g_upgrade_preserves_user_modification(self):
        repo = self.make_repo()
        result = run_installer("install", str(repo))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

        gate = repo / ".harness" / "hooks" / "contract_gate.py"
        original = gate.read_text()
        gate.write_text(original + "\n# local edit\n")

        result = run_installer("upgrade", str(repo))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(gate.read_text().endswith("# local edit\n"))
        self.assertIn(".harness/hooks/contract_gate.py (user-modified)", result.stdout)

        doctor = run_installer("doctor", str(repo))
        self.assertEqual(doctor.returncode, 1, doctor.stdout + doctor.stderr)

    def test_h_session_end_scoped_to_docs_root(self):
        repo = self.make_repo()
        result = run_installer("install", str(repo))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

        (repo / "contracts").mkdir()
        (repo / "contracts" / "keep.txt").write_text("keep")
        (repo / "agent-docs" / "contracts").mkdir(parents=True)
        (repo / "agent-docs" / "contracts" / "c.md").write_text("c")

        proc = subprocess.run(
            [sys.executable, str(repo / ".harness" / "hooks" / "session_end.py")],
            input=json.dumps({"hook_event_name": "SessionEnd"}),
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertTrue((repo / "contracts" / "keep.txt").exists())
        self.assertFalse((repo / "agent-docs" / "contracts").exists())

    def test_i_handoff_missing_or_wrong_heading(self):
        repo = self.make_repo()
        result = run_installer("install", str(repo))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

        handoff_dir = repo / "agent-docs" / "handoff"
        target_file = handoff_dir / "1234567890abcdef-x.md"
        target_file.write_text(
            "# X\n\n## Goal\ng\n\n## State\ns\n\n## Next Step\nn\n\n"
            "## Open Questions\nq\n\n## Contract Snapshot\nnone\n"
        )
        (handoff_dir / "index.md").write_text(
            "File: 1234567890abcdef-x.md\n"
            "Summary: test\n"
            "Related Files: none\n"
            "Related Symbols: none\n"
        )
        (handoff_dir / "stale.md").write_text("")

        verify = subprocess.run(
            [sys.executable, str(repo / ".harness" / "git" / "verify_rules.py")],
            capture_output=True,
            text=True,
        )
        self.assertEqual(verify.returncode, 1, verify.stdout + verify.stderr)

        target_file.write_text(
            "# X\n\n## Goal\ng\n\n## State\ns\n\n## Failed Attemptsx\nbad\n\n## Next Step\nn\n\n"
            "## Open Questions\nq\n\n## Contract Snapshot\nnone\n"
        )
        verify = subprocess.run(
            [sys.executable, str(repo / ".harness" / "git" / "verify_rules.py")],
            capture_output=True,
            text=True,
        )
        self.assertEqual(verify.returncode, 1, verify.stdout + verify.stderr)


class TestPhaseBFixes(InstallerTestCase):
    def test_fix1_non_ascii_settings_preserved_and_stable(self):
        repo = self.make_repo()
        (repo / ".claude").mkdir()
        original = {"permissions": {"note": "한글 테스트"}, "hooks": {}}
        settings_path = repo / ".claude" / "settings.json"
        settings_path.write_text(
            json.dumps(original, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )

        result = run_installer("install", str(repo))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

        after_install = settings_path.read_bytes()
        text_after_install = after_install.decode("utf-8")
        self.assertIn("한글 테스트", text_after_install)
        self.assertNotIn("\\u", text_after_install)

        result = run_installer("upgrade", str(repo))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        after_second_upgrade = settings_path.read_bytes()
        self.assertEqual(after_install, after_second_upgrade)

    def test_fix2_skipped_file_keeps_old_manifest_sha(self):
        repo = self.make_repo()
        result = run_installer("install", str(repo))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

        manifest_path = repo / ".harness" / "manifest.json"
        pre_manifest = json.loads(manifest_path.read_text())
        pre_sha = pre_manifest["files"][".harness/hooks/contract_gate.py"]

        gate = repo / ".harness" / "hooks" / "contract_gate.py"
        gate.write_text(gate.read_text() + "\n# local edit\n")

        result = run_installer("upgrade", str(repo))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

        post_manifest = json.loads(manifest_path.read_text())
        post_sha = post_manifest["files"][".harness/hooks/contract_gate.py"]
        self.assertEqual(post_sha, pre_sha)

    def test_fix3_disk_already_matches_new_render_is_noop(self):
        repo = self.make_repo()
        result = run_installer("install", str(repo))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

        sys.path.insert(0, str(REPO_ROOT / "installer"))
        import harness as installer_module

        owned = installer_module.render_owned_files(no_ci=False)
        relpath = ".harness/hooks/session_end.py"
        new_content = owned[relpath]

        gate = repo / relpath
        gate.write_bytes(gate.read_bytes() + b"\n")
        gate.write_bytes(new_content)

        result = run_installer("upgrade", str(repo))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn(f"{relpath} (user-modified)", result.stdout)


class TestCodexClearContractCleanup(InstallerTestCase):
    def install_hook_configs(self):
        repo = self.make_repo()
        result = run_installer("install", str(repo))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        claude = json.loads((repo / ".claude" / "settings.json").read_text())
        codex = json.loads((repo / ".codex" / "hooks.json").read_text())
        return claude["hooks"], codex["hooks"]

    def commands(self, hook_groups):
        return [hook["command"] for group in hook_groups for hook in group["hooks"]]

    def test_e1_characterization_shared_session_end_cleanup_is_in_both_configs(self):
        claude, codex = self.install_hook_configs()

        self.assertIn(".harness/hooks/session_end.py", "\n".join(self.commands(claude["SessionEnd"])))
        self.assertIn(".harness/hooks/session_end.py", "\n".join(self.commands(codex["SessionEnd"])))

    def test_i2_e2_codex_clear_hook_is_absent_from_claude_and_present_in_codex(self):
        claude, codex = self.install_hook_configs()

        self.assertEqual(claude.get("SessionStart", []), [])
        self.assertEqual(
            len([group for group in codex["SessionStart"] if group.get("matcher") == "clear"]),
            1,
        )

    def test_e3_codex_clear_reuses_session_end_cleanup_command(self):
        _, codex = self.install_hook_configs()

        clear_commands = self.commands(
            [group for group in codex["SessionStart"] if group.get("matcher") == "clear"]
        )
        self.assertEqual(clear_commands, self.commands(codex["SessionEnd"]))

    def test_i1_session_start_clear_removes_contracts(self):
        repo = self.make_repo()
        result = run_installer("install", str(repo))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        contracts = repo / "agent-docs" / "contracts"
        contracts.mkdir(parents=True)
        (contracts / "contract.md").write_text("contract")

        proc = subprocess.run(
            [sys.executable, str(repo / ".harness" / "hooks" / "session_end.py")],
            input=json.dumps({"hook_event_name": "SessionStart", "source": "clear"}),
            capture_output=True,
            text=True,
        )

        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertFalse(contracts.exists())


if __name__ == "__main__":
    unittest.main()

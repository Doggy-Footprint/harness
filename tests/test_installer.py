import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
INSTALLER = REPO_ROOT / "installer" / "harness.py"
SKILLS = sorted(d.name for d in (REPO_ROOT / "harness" / "skills").iterdir() if d.is_dir())


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

    def install(self):
        repo = self.make_repo()
        result = run_installer("install", str(repo))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return repo

    def snapshot(self, repo):
        files = {}
        for path in repo.rglob("*"):
            if ".git" in path.relative_to(repo).parts:
                continue
            if path.is_file():
                files[str(path.relative_to(repo))] = hashlib.sha256(path.read_bytes()).hexdigest()
        return files

    def install_hook_configs(self):
        repo = self.install()
        claude = json.loads((repo / ".claude" / "settings.json").read_text())
        codex = json.loads((repo / ".codex" / "hooks.json").read_text())
        return claude["hooks"], codex["hooks"]

    def commands(self, hook_groups):
        return [hook["command"] for group in hook_groups for hook in group["hooks"]]

    def run_hook(self, repo, script, payload):
        return subprocess.run(
            [sys.executable, str(repo / ".harness" / "hooks" / script)],
            input=json.dumps(payload),
            capture_output=True,
            text=True,
        )

    def run_session_lock(self, repo, event, extra_payload=None):
        payload = {"hook_event_name": event}
        payload.update(extra_payload or {})
        return self.run_hook(repo, "session_lock.py", payload)

    def run_seed(self, repo, *args):
        return subprocess.run(
            [sys.executable, str(repo / ".harness" / "bin" / "seed.py")] + list(args),
            cwd=repo,
            capture_output=True,
            text=True,
        )

    def run_verify_rules(self, repo):
        return subprocess.run(
            [sys.executable, str(repo / ".harness" / "git" / "verify_rules.py")],
            capture_output=True,
            text=True,
        )


class TestNormal(InstallerTestCase):
    def test_a_empty_repo_install_then_doctor(self):
        repo = self.install()

        result = run_installer("doctor", str(repo))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

        verify = self.run_verify_rules(repo)
        self.assertEqual(verify.returncode, 0, verify.stdout + verify.stderr)

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

    def test_f_reinstall_idempotent_after_commit(self):
        repo = self.install()

        run_git(repo, "add", "-A")
        run_git(repo, "commit", "-q", "-m", "install harness")

        result = run_installer("upgrade", str(repo))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

        status = run_git(repo, "status", "--porcelain").stdout
        self.assertEqual(status.strip(), "")

    def test_h_session_end_scoped_to_docs_root(self):
        repo = self.install()

        (repo / "contracts").mkdir()
        (repo / "contracts" / "keep.txt").write_text("keep")
        (repo / "agent-docs" / "contracts").mkdir(parents=True)
        (repo / "agent-docs" / "contracts" / "c.md").write_text("c")

        proc = self.run_hook(repo, "cleanup.py", {"hook_event_name": "SessionEnd"})
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertTrue((repo / "contracts" / "keep.txt").exists())
        self.assertFalse((repo / "agent-docs" / "contracts").exists())

    def test_i1_session_start_clear_removes_contracts(self):
        repo = self.install()
        contracts = repo / "agent-docs" / "contracts"
        contracts.mkdir(parents=True)
        (contracts / "contract.md").write_text("contract")

        proc = self.run_hook(
            repo, "cleanup.py", {"hook_event_name": "SessionStart", "source": "clear"}
        )

        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertFalse(contracts.exists())

    def test_e1_characterization_shared_session_end_cleanup_is_in_both_configs(self):
        claude, codex = self.install_hook_configs()

        self.assertIn(".harness/hooks/cleanup.py", "\n".join(self.commands(claude["SessionEnd"])))
        self.assertIn(".harness/hooks/cleanup.py", "\n".join(self.commands(codex["SessionEnd"])))

    def test_i2_e2_codex_clear_hook_is_absent_from_claude_and_present_in_codex(self):
        claude, codex = self.install_hook_configs()

        self.assertEqual(
            [group for group in claude.get("SessionStart", []) if group.get("matcher") == "clear"],
            [],
        )
        self.assertEqual(
            len([group for group in codex["SessionStart"] if group.get("matcher") == "clear"]),
            1,
        )

    def test_e3_codex_clear_reuses_session_end_cleanup_command(self):
        _, codex = self.install_hook_configs()

        clear_commands = self.commands(
            [group for group in codex["SessionStart"] if group.get("matcher") == "clear"]
        )
        session_end_commands = self.commands(codex["SessionEnd"])
        for command in clear_commands:
            self.assertIn(command, session_end_commands)

    def test_i4_session_lock_hook_is_present_without_matcher_for_both_targets(self):
        claude, codex = self.install_hook_configs()

        for hooks in (claude, codex):
            unmatched = [group for group in hooks["SessionStart"] if "matcher" not in group]
            self.assertEqual(
                len([g for g in unmatched if "session_lock.py" in self.commands([g])[0]]), 1
            )
            self.assertIn("session_lock.py", "\n".join(self.commands(hooks["SessionEnd"])))

    def test_session_end_removes_own_marker(self):
        repo = self.install()
        running_dir = repo / ".harness" / "sessions" / ".running"

        start = self.run_session_lock(repo, "SessionStart")
        self.assertEqual(start.returncode, 0, start.stdout + start.stderr)
        self.assertEqual(len(list(running_dir.iterdir())), 1)

        end = self.run_session_lock(repo, "SessionEnd")
        self.assertEqual(end.returncode, 0, end.stdout + end.stderr)
        self.assertEqual(list(running_dir.iterdir()), [])

    def test_seed_backup_then_restore_returns_original_bytes_and_removes_seed(self):
        repo = self.install()
        target = repo / "src" / "app.py"
        target.parent.mkdir()
        target.write_bytes(b"def f():\n    return 1\n")
        seed_dir = repo / "agent-docs" / "contracts" / ".seed"

        backup = self.run_seed(repo, "backup", "src/app.py")
        self.assertEqual(backup.returncode, 0, backup.stdout + backup.stderr)
        target.write_bytes(b"def f():\n    return 2\n")
        restore = self.run_seed(repo, "restore")

        self.assertEqual(restore.returncode, 0, restore.stdout + restore.stderr)
        self.assertEqual(target.read_bytes(), b"def f():\n    return 1\n")
        self.assertFalse(seed_dir.exists())


    def test_every_skill_is_installed_with_a_claude_symlink(self):
        repo = self.install()
        self.assertGreater(len(SKILLS), 1)
        for name in SKILLS:
            self.assertTrue((repo / ".agents" / "skills" / name / "SKILL.md").is_file(), name)
            link = repo / ".claude" / "skills" / name
            self.assertTrue(link.is_symlink(), name)
            self.assertEqual(link.resolve(), (repo / ".agents" / "skills" / name).resolve())

    def test_requirements_docs_dir_is_created(self):
        repo = self.install()
        for fname in ("index.md", "stale.md"):
            self.assertTrue((repo / "agent-docs" / "requirements" / fname).is_file(), fname)

    def test_import_reports_the_modified_file_with_a_diff(self):
        repo = self.install()
        gate = repo / ".harness" / "hooks" / "contract_gate.py"
        gate.write_text(gate.read_text() + "\n# local edit\n")

        result = run_installer("import", str(repo))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(".harness/hooks/contract_gate.py", result.stdout)
        self.assertIn("+# local edit", result.stdout)

    def test_import_json_lists_only_the_modified_file(self):
        repo = self.install()
        gate = repo / ".harness" / "hooks" / "contract_gate.py"
        gate.write_text(gate.read_text() + "\n# local edit\n")

        result = run_installer("import", str(repo), "--json")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        drift = json.loads(result.stdout)
        self.assertEqual([e["path"] for e in drift["modified"]], [".harness/hooks/contract_gate.py"])
        self.assertIn("+# local edit", drift["modified"][0]["diff"])
        self.assertEqual(drift["missing"], [])

    def test_import_reports_an_unowned_skill_as_added(self):
        repo = self.install()
        own = repo / ".agents" / "skills" / "local-only"
        own.mkdir(parents=True)
        (own / "SKILL.md").write_text("mine")

        result = run_installer("import", str(repo), "--json")
        drift = json.loads(result.stdout)
        self.assertIn(".agents/skills/local-only/SKILL.md", drift["added"])


class TestBoundary(InstallerTestCase):
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

    def test_fix3_disk_already_matches_new_render_is_noop(self):
        repo = self.install()

        sys.path.insert(0, str(REPO_ROOT / "installer"))
        import harness as installer_module

        owned = installer_module.render_owned_files(no_ci=False)
        relpath = ".harness/hooks/cleanup.py"
        new_content = owned[relpath]

        gate = repo / relpath
        gate.write_bytes(gate.read_bytes() + b"\n")
        gate.write_bytes(new_content)

        result = run_installer("upgrade", str(repo))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn(f"{relpath} (user-modified)", result.stdout)

    def test_sweeps_stale_marker_without_warning(self):
        repo = self.install()
        running_dir = repo / ".harness" / "sessions" / ".running"
        running_dir.mkdir(parents=True)

        dead = subprocess.Popen([sys.executable, "-c", "pass"])
        dead.wait()
        (running_dir / str(dead.pid)).write_text("startup", encoding="utf-8")

        proc = self.run_session_lock(repo, "SessionStart")

        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertEqual(proc.stderr, "")
        self.assertFalse((running_dir / str(dead.pid)).exists())

    def test_cleanup_removes_contracts_when_seed_dir_is_empty(self):
        repo = self.install()
        contracts = repo / "agent-docs" / "contracts"
        (contracts / ".seed" / "src").mkdir(parents=True)
        (contracts / "contract.md").write_text("contract")

        proc = self.run_hook(repo, "cleanup.py", {"hook_event_name": "SessionEnd"})

        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertFalse(contracts.exists())


    def test_import_on_a_fresh_install_reports_no_drift(self):
        repo = self.install()
        result = run_installer("import", str(repo), "--json")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        drift = json.loads(result.stdout)
        self.assertEqual(drift["modified"], [])
        self.assertEqual(drift["missing"], [])
        self.assertEqual(drift["added"], [])
        self.assertGreater(drift["unchanged"], 0)


class TestError(InstallerTestCase):
    def test_e_existing_agent_file_conflicts(self):
        repo = self.make_repo()
        (repo / ".claude" / "agents").mkdir(parents=True)
        (repo / ".claude" / "agents" / "implementer.md").write_text("mine")

        before = self.snapshot(repo)
        result = run_installer("install", str(repo))
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        after = self.snapshot(repo)
        self.assertEqual(before, after)

    def test_import_without_a_manifest_exits_1(self):
        repo = self.make_repo()
        before = self.snapshot(repo)
        result = run_installer("import", str(repo))
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertEqual(before, self.snapshot(repo))

    def test_existing_skill_dir_conflicts(self):
        repo = self.make_repo()
        (repo / ".agents" / "skills" / SKILLS[0]).mkdir(parents=True)

        before = self.snapshot(repo)
        result = run_installer("install", str(repo))
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertEqual(before, self.snapshot(repo))

    def test_import_reports_a_deleted_owned_file_as_missing(self):
        repo = self.install()
        (repo / ".harness" / "hooks" / "contract_gate.py").unlink()
        result = run_installer("import", str(repo), "--json")
        drift = json.loads(result.stdout)
        self.assertIn(".harness/hooks/contract_gate.py", drift["missing"])


    def test_g_upgrade_preserves_user_modification(self):
        repo = self.install()

        gate = repo / ".harness" / "hooks" / "contract_gate.py"
        original = gate.read_text()
        gate.write_text(original + "\n# local edit\n")

        result = run_installer("upgrade", str(repo))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(gate.read_text().endswith("# local edit\n"))
        self.assertIn(".harness/hooks/contract_gate.py (user-modified)", result.stdout)

        doctor = run_installer("doctor", str(repo))
        self.assertEqual(doctor.returncode, 1, doctor.stdout + doctor.stderr)

    def test_fix2_skipped_file_keeps_old_manifest_sha(self):
        repo = self.install()

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

    def test_i_handoff_missing_or_wrong_heading(self):
        repo = self.install()

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

        verify = self.run_verify_rules(repo)
        self.assertEqual(verify.returncode, 1, verify.stdout + verify.stderr)

        target_file.write_text(
            "# X\n\n## Goal\ng\n\n## State\ns\n\n## Failed Attemptsx\nbad\n\n## Next Step\nn\n\n"
            "## Open Questions\nq\n\n## Contract Snapshot\nnone\n"
        )
        verify = self.run_verify_rules(repo)
        self.assertEqual(verify.returncode, 1, verify.stdout + verify.stderr)

    def test_seed_restore_with_tampered_backup_exits_1_and_keeps_seed(self):
        repo = self.install()
        target = repo / "app.py"
        target.write_bytes(b"original\n")
        backup = self.run_seed(repo, "backup", "app.py")
        self.assertEqual(backup.returncode, 0, backup.stdout + backup.stderr)
        seed_copy = repo / "agent-docs" / "contracts" / ".seed" / "app.py"
        seed_copy.write_bytes(b"tampered\n")
        target.write_bytes(b"injected\n")

        restore = self.run_seed(repo, "restore")

        self.assertEqual(restore.returncode, 1, restore.stdout + restore.stderr)
        self.assertEqual(target.read_bytes(), b"injected\n")
        self.assertEqual(seed_copy.read_bytes(), b"tampered\n")

    def test_seed_restore_without_manifest_exits_1_and_keeps_seed(self):
        repo = self.install()
        target = repo / "app.py"
        target.write_bytes(b"injected\n")
        seed_copy = repo / "agent-docs" / "contracts" / ".seed" / "app.py"
        seed_copy.parent.mkdir(parents=True)
        seed_copy.write_bytes(b"original\n")

        restore = self.run_seed(repo, "restore")

        self.assertEqual(restore.returncode, 1, restore.stdout + restore.stderr)
        self.assertEqual(target.read_bytes(), b"injected\n")
        self.assertEqual(seed_copy.read_bytes(), b"original\n")

    def test_seed_backup_while_seed_unrestored_exits_1_and_keeps_first_backup(self):
        repo = self.install()
        (repo / "a.py").write_bytes(b"a\n")
        (repo / "b.py").write_bytes(b"b\n")
        first = self.run_seed(repo, "backup", "a.py")
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        seed_dir = repo / "agent-docs" / "contracts" / ".seed"
        before = sorted(p.relative_to(seed_dir).as_posix() for p in seed_dir.rglob("*") if p.is_file())

        second = self.run_seed(repo, "backup", "b.py")

        self.assertEqual(second.returncode, 1, second.stdout + second.stderr)
        after = sorted(p.relative_to(seed_dir).as_posix() for p in seed_dir.rglob("*") if p.is_file())
        self.assertEqual(after, before)
        self.assertEqual(before, ["a.py", "manifest.json"])

    def test_seed_backup_of_path_outside_repo_exits_1_and_writes_nothing(self):
        repo = self.install()
        outside_tmp = tempfile.TemporaryDirectory()
        self.addCleanup(outside_tmp.cleanup)
        outside = Path(outside_tmp.name) / "x.py"
        outside.write_bytes(b"x\n")

        backup = self.run_seed(repo, "backup", str(outside))

        self.assertEqual(backup.returncode, 1, backup.stdout + backup.stderr)
        self.assertFalse((repo / "agent-docs" / "contracts" / ".seed").exists())


class TestEdge(InstallerTestCase):
    def test_d_husky_hooks_path_untouched(self):
        repo = self.make_repo()
        (repo / ".husky").mkdir()
        run_git(repo, "config", "core.hooksPath", ".husky")

        result = run_installer("install", str(repo))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

        current = run_git(repo, "config", "--get", "core.hooksPath").stdout.strip()
        self.assertEqual(current, ".husky")
        self.assertIn("manual review", result.stdout)

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

    def test_warns_when_another_live_process_holds_a_marker(self):
        repo = self.install()
        running_dir = repo / ".harness" / "sessions" / ".running"
        running_dir.mkdir(parents=True)

        other = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(5)"])
        try:
            (running_dir / str(other.pid)).write_text("startup", encoding="utf-8")

            proc = self.run_session_lock(repo, "SessionStart")

            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            self.assertIn(str(other.pid), proc.stderr)
        finally:
            other.terminate()
            other.wait()

    def stranded_seed_repo(self):
        repo = self.install()
        target = repo / "app.py"
        target.write_bytes(b"original\n")
        backup = self.run_seed(repo, "backup", "app.py")
        self.assertEqual(backup.returncode, 0, backup.stdout + backup.stderr)
        target.write_bytes(b"injected\n")
        return repo

    def assert_cleanup_keeps_stranded_seed(self, payload):
        repo = self.stranded_seed_repo()
        seed_copy = repo / "agent-docs" / "contracts" / ".seed" / "app.py"

        proc = self.run_hook(repo, "cleanup.py", payload)

        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertEqual(seed_copy.read_bytes(), b"original\n")
        self.assertIn("seed.py restore", proc.stderr)

    def test_session_end_cleanup_keeps_contracts_while_seed_unrestored(self):
        self.assert_cleanup_keeps_stranded_seed({"hook_event_name": "SessionEnd"})

    def test_codex_clear_cleanup_keeps_contracts_while_seed_unrestored(self):
        self.assert_cleanup_keeps_stranded_seed({"hook_event_name": "SessionStart", "source": "clear"})

    def test_post_merge_cleanup_keeps_contracts_while_seed_unrestored(self):
        self.assert_cleanup_keeps_stranded_seed({"hook_event_name": "PostMerge"})

    def test_restore_after_kept_cleanup_recovers_original(self):
        repo = self.stranded_seed_repo()
        cleanup = self.run_hook(repo, "cleanup.py", {"hook_event_name": "SessionEnd"})
        self.assertEqual(cleanup.returncode, 0, cleanup.stdout + cleanup.stderr)

        restore = self.run_seed(repo, "restore")

        self.assertEqual(restore.returncode, 0, restore.stdout + restore.stderr)
        self.assertEqual((repo / "app.py").read_bytes(), b"original\n")


if __name__ == "__main__":
    unittest.main()

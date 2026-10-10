import hashlib
import json
import re
import subprocess
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
INSTALLER = REPO_ROOT / "installer" / "harness.py"
SKILLS = sorted(d.name for d in (REPO_ROOT / "harness" / "skills").iterdir() if d.is_dir())


def run_installer(*args, input="", forbid_input=False):
    command = [sys.executable, str(INSTALLER)] + list(args)
    if forbid_input:
        script = (
            "import builtins, runpy, sys; "
            "builtins.input = lambda *args: sys.exit('unexpected confirmation input'); "
            "sys.argv = sys.argv[1:]; runpy.run_path(sys.argv[0], run_name='__main__')"
        )
        command = [sys.executable, "-c", script, str(INSTALLER)] + list(args)
    return subprocess.run(
        command,
        input=input,
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

    def prepare_stale_record(self, repo, directory="handoff", filename="1234567890abcdef-x.md"):
        docs = repo / "agent-docs" / directory
        source = docs / filename
        source.write_text("# Stale\n")
        (docs / "stale.md").write_text(f"{filename}\n")
        index_block = (
            f"File: {filename}\n"
            "Summary: retained archive metadata\n"
            "Related Files: tests/test_installer.py\n"
            "Related Symbols: InstallerTestCase\n"
        )
        (docs / "index.md").write_text(index_block)
        manifest_path = repo / ".harness" / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["version"] = "0.2.0"
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
        return docs, source, manifest_path, index_block

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

    def run_lifecycle(self, repo, *args):
        return subprocess.run(
            [sys.executable, str(repo / ".harness" / "bin" / "spec_lifecycle.py"), *args],
            cwd=repo,
            capture_output=True,
            text=True,
        )

    def write_valid_spec(self, repo, run_id="0123456789abcdef", name="change", status="active", handoff="none"):
        path = repo / "agent-docs" / "specs" / f"{run_id}-{name}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        characteristics = (
            "Functional suitability", "Performance efficiency", "Compatibility",
            "Interaction capability", "Reliability", "Security", "Maintainability",
            "Flexibility", "Safety",
        )
        quality_rows = "\n".join(f"| {item} | no | not affected |" for item in characteristics)
        headings = (
            "# User Intent", "# Scope", "# Paths", "# Signatures",
            "# Functional Requirements", "# Errors", "# Cases",
            "# Quality Applicability", "# Quality Requirements",
            "# Verification Obligations", "# Assumptions and Defaults",
            "# Traceability", "# Workflow Control", "# Version Log",
        )
        sections = []
        for heading in headings:
            sections.append(heading)
            sections.append(quality_rows if heading == "# Quality Applicability" else "none")
        path.write_text(
            "---\n"
            "version: 1\n"
            f"run_id: {run_id}\n"
            f"status: {status}\n"
            f"base_commit: {'a' * 40}\n"
            "max_verifier_invocations: 2\n"
            f"handoff: {handoff}\n"
            "---\n\n"
            + "\n\n".join(sections)
            + "\n"
        )
        return path

    def run_verify_rules(self, repo):
        return subprocess.run(
            [sys.executable, str(repo / ".harness" / "git" / "verify_rules.py")],
            capture_output=True,
            text=True,
        )


class TestNormal(InstallerTestCase):
    def installed_agent_artifacts(self, repo, name):
        artifacts = []
        for target in (".agents", ".claude", ".codex"):
            root = repo / target
            for suffix in ("md", "toml"):
                artifacts.extend(sorted(root.rglob(f"{name}.{suffix}")))
        self.assertGreater(len(artifacts), 0, name)
        return artifacts

    def assert_contains_all(self, text, phrases):
        normalized = text.lower()
        for phrase in phrases:
            self.assertIn(phrase.lower(), normalized)

    def assert_matches(self, text, pattern):
        self.assertRegex(text, re.compile(pattern, re.IGNORECASE | re.DOTALL))

    def test_c1_normal_rewritten_agents_preserve_spec_boundaries_and_reports(self):
        repo = self.install()
        implementer = "\n".join(
            path.read_text() for path in self.installed_agent_artifacts(repo, "implementer")
        )
        test_implementer = "\n".join(
            path.read_text()
            for path in self.installed_agent_artifacts(repo, "test-implementer")
        )
        workflow = (
            repo / ".agents" / "skills" / "workflow-approach" / "SKILL.md"
        ).read_text()

        self.assert_contains_all(
            implementer,
            (
                "spec",
                "challenge",
                "Spec version",
                "Files changed",
                "Checks",
                "Blocked",
                "Unsure",
                "Spec challenges",
            ),
        )
        self.assert_matches(implementer, r"(?:isolation|do not (?:open|read)|independent)")
        self.assert_matches(implementer, r"(?:allowed|permitted|#)\s*paths?")
        self.assert_contains_all(
            test_implementer,
            ("independent", "Implementation", "spec", "challenge", "quality"),
        )
        self.assert_matches(test_implementer, r"(?:independent|do not (?:open|read)).{0,120}implementation")
        self.assert_contains_all(workflow, ("complete replacement instructions", "spec", "quality"))
        self.assert_matches(
            workflow,
            r"instructions.{0,700}(?:risk|verification|oracle)",
        )
        self.assert_matches(
            workflow,
            r"instructions.{0,700}(?:exclude|avoid|not use)",
        )
        self.assert_matches(workflow, r"implementer.{0,400}(?:approach|constraint)")
        self.assert_matches(workflow, r"test-implementer.{0,400}(?:risk|oracle|test)")

    def test_c2_boundary_upgrade_keeps_all_installed_agent_artifacts_in_sync(self):
        repo = self.install()
        before = {
            path: path.read_text()
            for name in ("implementer", "test-implementer")
            for path in self.installed_agent_artifacts(repo, name)
        }
        workflow = repo / ".agents" / "skills" / "workflow-approach" / "SKILL.md"
        before[workflow] = workflow.read_text()

        result = run_installer("upgrade", str(repo))

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        for path, content in before.items():
            self.assertEqual(path.read_text(), content, path)

    def test_a_empty_repo_install_then_doctor(self):
        repo = self.install()

        result = run_installer("doctor", str(repo))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

        verify = self.run_verify_rules(repo)
        self.assertEqual(verify.returncode, 0, verify.stdout + verify.stderr)

    def test_a1_verified_test_gap_checks_clean_baseline_before_seed(self):
        repo = self.install()
        workflow = (
            repo / ".agents" / "skills" / "workflow-approach" / "SKILL.md"
        ).read_text()

        self.assertIn("rerun the restored Test command", workflow)
        self.assertRegex(workflow, r"repeat\s+confirming mutations")
        self.assertIn("stop if restore fails", workflow)

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

    def test_h_session_end_archives_terminal_spec_only_inside_docs_root(self):
        repo = self.install()

        (repo / "specs").mkdir()
        (repo / "specs" / "keep.txt").write_text("keep")
        (repo / "agent-docs" / "specs").mkdir(parents=True)
        spec = repo / "agent-docs" / "specs" / "0123456789abcdef-c.md"
        spec.write_text("---\nstatus: complete\n---\n")

        proc = self.run_lifecycle(repo, "session")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertTrue((repo / "specs" / "keep.txt").exists())
        self.assertFalse(spec.exists())
        self.assertTrue((repo / "agent-docs" / "spec-logs" / spec.name).is_file())

    def test_i1_session_clear_preserves_active_spec_without_handoff(self):
        repo = self.install()
        specs = repo / "agent-docs" / "specs"
        specs.mkdir(parents=True)
        spec = specs / "0123456789abcdef-spec.md"
        spec.write_text("---\nstatus: active\nbase_commit: deadbeef\nhandoff: none\n---\n")

        proc = self.run_lifecycle(repo, "session")

        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertTrue(spec.is_file())
        self.assertIn("without a handoff", proc.stderr)

    def test_e1_spec_lifecycle_session_hook_is_in_both_configs(self):
        claude, codex = self.install_hook_configs()

        self.assertIn(".harness/bin/spec_lifecycle.py", "\n".join(self.commands(claude["SessionEnd"])))
        self.assertIn(".harness/bin/spec_lifecycle.py", "\n".join(self.commands(codex["SessionEnd"])))

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
        seed_dir = repo / "agent-docs" / "specs" / ".seed"

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

    def test_agent_docs_dirs_are_created(self):
        repo = self.install()
        for name in ("adr", "rejections", "handoff"):
            self.assertTrue((repo / "agent-docs" / name / "index.md").is_file())
            self.assertTrue((repo / "agent-docs" / name / "stale.md").is_file())
            self.assertTrue((repo / "agent-docs" / name / "stale" / ".gitkeep").is_file())
        self.assertFalse((repo / "agent-docs" / "requirements").exists())

    def test_c1_update_migrates_stale_records_after_confirmation(self):
        repo = self.install()
        docs, source, manifest_path, index_block = self.prepare_stale_record(repo)

        result = run_installer("update", str(repo), input="y\ny\n" * 16)

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("stale", (result.stdout + result.stderr).lower())
        self.assertFalse(source.exists())
        self.assertEqual((docs / "stale" / source.name).read_text(), "# Stale\n")
        self.assertNotIn(index_block, (docs / "index.md").read_text())
        stale_log = (docs / "stale.md").read_text()
        self.assertIn(index_block, stale_log)
        archive_format = stale_log.replace(index_block, "")
        self.assertTrue(archive_format.strip())
        self.assertNotIn(f"{source.name}\n", archive_format)
        self.assertNotEqual(json.loads(manifest_path.read_text())["version"], "0.2.0")

    def test_c2_update_archives_unindexed_legacy_record_and_retires_filename_line(self):
        repo = self.install()
        docs, source, _, index_block = self.prepare_stale_record(repo)
        (docs / "index.md").write_text((docs / "index.md").read_text().replace(index_block, ""))

        result = run_installer("update", str(repo), input="y\ny\n" * 16)

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse(source.exists())
        self.assertEqual((docs / "stale" / source.name).read_text(), "# Stale\n")
        stale_log = docs / "stale.md"
        self.assertTrue(stale_log.is_file())
        archive_format = stale_log.read_text()
        self.assertTrue(archive_format.strip())
        self.assertNotIn(source.name, archive_format)

    def test_c1_update_keeps_retained_index_blocks_separated_by_newlines(self):
        repo = self.install()
        docs, _, _, stale_block = self.prepare_stale_record(repo)
        first = (
            "File: 1111111111111111-first.md\n"
            "Summary: first retained record\n"
            "Related Files: none\n"
            "Related Symbols: none\n"
        )
        second = (
            "File: 2222222222222222-second.md\n"
            "Summary: second retained record\n"
            "Related Files: none\n"
            "Related Symbols: none\n"
        )
        (docs / "index.md").write_text(first + "\n---\n" + stale_block + "\n---\n" + second)

        result = run_installer("update", str(repo), input="y\ny\n" * 16)

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual((docs / "index.md").read_text(), first.rstrip("\n") + "\n---\n" + second)

    def test_archived_stale_docs_are_excluded_from_index_validation(self):
        repo = self.install()
        archived = repo / "agent-docs" / "handoff" / "stale" / "1234567890abcdef-x.md"
        archived.write_text("# Archived\n")

        verify = self.run_verify_rules(repo)
        self.assertEqual(verify.returncode, 0, verify.stdout + verify.stderr)

    def test_import_reports_the_modified_file_with_a_diff(self):
        repo = self.install()
        gate = repo / ".harness" / "hooks" / "spec_gate.py"
        gate.write_text(gate.read_text() + "\n# local edit\n")

        result = run_installer("import", str(repo))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(".harness/hooks/spec_gate.py", result.stdout)
        self.assertIn("+# local edit", result.stdout)

    def test_import_json_lists_only_the_modified_file(self):
        repo = self.install()
        gate = repo / ".harness" / "hooks" / "spec_gate.py"
        gate.write_text(gate.read_text() + "\n# local edit\n")

        result = run_installer("import", str(repo), "--json")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        drift = json.loads(result.stdout)
        self.assertEqual([e["path"] for e in drift["modified"]], [".harness/hooks/spec_gate.py"])
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
    def test_c2_upgrade_is_a_compatible_alias_and_readme_introduces_update(self):
        repo = self.install()

        result = run_installer("upgrade", str(repo))

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        readme = (REPO_ROOT / "README.md").read_text()
        self.assertIn("installer/harness.py update", readme)
        self.assertNotIn("installer/harness.py upgrade", readme)

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
        agents_md = (repo / "AGENTS.md").read_text()
        self.assertTrue(agents_md.startswith("# Project Definition\n\nBody text.\n\n<!-- harness:begin"))
        self.assertEqual((repo / "agent-docs" / "logs" / "agents-md-pre-harness.md").read_text(), content)

    def manual_review_items(self, stdout: str) -> list[str]:
        section = stdout.split("== manual review ==\n", 1)[1].split("\n== ", 1)[0]
        return [line[2:] for line in section.splitlines() if line.startswith("- ")]

    def assert_definition_install(self, original: str, expected_definition: str, log_name="agents-md-pre-harness.md"):
        repo = self.make_repo()
        (repo / "AGENTS.md").write_bytes(original.encode())
        if log_name != "agents-md-pre-harness.md":
            logs = repo / "agent-docs" / "logs"
            logs.mkdir(parents=True)
            (logs / "agents-md-pre-harness.md").write_text("older\n")

        result = run_installer("install", str(repo))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

        agents_md = (repo / "AGENTS.md").read_text()
        head = agents_md[: agents_md.index("<!-- harness:begin")]
        self.assertEqual(head, f"# Project Definition\n\n{expected_definition}\n\n")
        self.assertEqual((repo / "agent-docs" / "logs" / log_name).read_bytes(), original.encode())
        self.assertIn(f"agent-docs/logs/{log_name}", self.manual_review_items(result.stdout)[-1])
        return result

    def test_0110_install_keeps_explicit_project_definition(self):
        self.assert_definition_install(
            "# Project Definition\n\nA CLI for widgets.\n\n# Rules\n\nAlways use tabs.\n",
            "A CLI for widgets.",
        )

    def test_0110_install_keeps_overview_subsection(self):
        self.assert_definition_install(
            "# Widget\n\n## Overview\n\nA CLI for widgets.\n\n### Detail\n\nMore.\n\n## Style\n\nTabs.\n",
            "A CLI for widgets.\n\n### Detail\n\nMore.",
        )

    def test_0110_install_keeps_korean_definition(self):
        self.assert_definition_install("## 프로젝트 개요\n\n위젯 CLI.\n\n## 규칙\n\n탭 사용.\n", "위젯 CLI.")

    def test_0110_install_keeps_title_body(self):
        self.assert_definition_install("# Widget\n\nA CLI for widgets.\n\n## Rules\n\nTabs.\n", "A CLI for widgets.")

    def test_0110_install_without_definition_records_todo(self):
        result = self.assert_definition_install(
            "# Rules\n\n## Style\n\nTabs.\n",
            "[#TODO]Alert user to set up definition & north-start of the project.",
        )
        self.assertTrue(any(
            item.startswith("AGENTS.md: no project definition found")
            for item in self.manual_review_items(result.stdout)
        ), result.stdout)

    def test_0110_install_keeps_preamble(self):
        self.assert_definition_install("A CLI for widgets.\n\n# Rules\n\nTabs.\n", "A CLI for widgets.")

    def test_0110_install_keeps_level3_and_korean_variants(self):
        self.assert_definition_install("# W\n\n## Rules\n\n### Purpose\n\nShip widgets.\n\n## Style\n", "Ship widgets.")
        self.assert_definition_install("# 프로젝트 정의\n\n위젯 CLI.\n\n# 규칙\n", "위젯 CLI.")
        self.assert_definition_install("## 소개\n\n위젯 CLI.\n\n## 규칙\n", "위젯 CLI.")

    def test_0110_install_suffixes_existing_log(self):
        self.assert_definition_install(
            "# Overview\n\nA CLI.\n\n# Rules\n", "A CLI.", log_name="agents-md-pre-harness-2.md"
        )

    def test_0110_install_dry_run_writes_nothing(self):
        repo = self.make_repo()
        (repo / "AGENTS.md").write_text("# Overview\n\nA CLI.\n\n# Rules\n\nTabs.\n")
        before = self.snapshot(repo)

        result = run_installer("install", str(repo), "--dry-run")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(before, self.snapshot(repo))
        self.assertFalse((repo / "agent-docs").exists())

    def test_0110_install_with_existing_block_skips_extraction(self):
        repo = self.make_repo()
        original = "# Local Rules\n\nTabs.\n\n<!-- harness:begin 0.10.0 -->\nold\n<!-- harness:end -->\n"
        (repo / "AGENTS.md").write_text(original)

        result = run_installer("install", str(repo))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        agents_md = (repo / "AGENTS.md").read_text()
        self.assertTrue(agents_md.startswith("# Local Rules\n\nTabs.\n\n<!-- harness:begin 0.17.0 -->"))
        self.assertNotIn("\nold\n", agents_md)
        self.assertFalse((repo / "agent-docs" / "logs").exists())

    def test_0110_declining_migration_preserves_files(self):
        repo = self.install()
        manifest_path = repo / ".harness" / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["version"] = "0.10.0"
        manifest_path.write_text(json.dumps(manifest))
        before = self.snapshot(repo)

        result = run_installer("update", str(repo), input="n\n")
        self.assertEqual(result.returncode, 1)
        self.assertIn("migration 0.11.0:", result.stdout)
        self.assertEqual(before, self.snapshot(repo))

    def test_0110_update_leaves_agents_md_outside_block(self):
        repo = self.install()
        agents_md = repo / "AGENTS.md"
        agents_md.write_text(agents_md.read_text() + "\n# Local Rules\n\nTabs.\n")
        manifest_path = repo / ".harness" / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["version"] = "0.10.0"
        manifest_path.write_text(json.dumps(manifest))

        result = run_installer("update", str(repo), input="y\ny\n" * 9)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("migration 0.11.0:", result.stdout)
        self.assertIn("# Local Rules\n\nTabs.\n", agents_md.read_text())
        self.assertFalse((repo / "agent-docs" / "logs").exists())

    def prepare_0120_update(self, repo):
        docs_root = repo / "agent-docs"
        filename = "1234567890abcdef-x.md"
        adr = docs_root / "adr"
        (adr / filename).write_text("# X\n")
        existing_stale = "# Stale Index Archive\n<!-- harness:stale-index-archive -->\n\nkept\n"
        (adr / "stale.md").write_text(existing_stale)
        index = (
            f"File: {filename}\n"
            "Summary: test\n"
            "Related Files: none\n"
            "Related Symbols: none\n"
        )
        (adr / "index.md").write_text(index)
        notes = docs_root / "notes" / "deep"
        (notes / "stale").mkdir(parents=True)
        (notes / filename).write_text("# X\n")
        (notes / "index.md").write_text(index)
        (notes / "stale" / "abcdef1234567890-old.md").write_text("# Old\n")
        for name in ("specs", "spec-logs"):
            (docs_root / name).mkdir(exist_ok=True)
            (docs_root / name / filename).write_text("# X\n")
        manifest_path = repo / ".harness" / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["version"] = "0.11.0"
        manifest_path.write_text(json.dumps(manifest))
        return docs_root, adr, notes, existing_stale, manifest_path

    def test_0120_update_creates_missing_stale_records_only_for_managed_dirs(self):
        repo = self.install()
        docs_root, adr, notes, existing_stale, manifest_path = self.prepare_0120_update(repo)
        verify = self.run_verify_rules(repo)
        self.assertEqual(verify.returncode, 1, verify.stdout + verify.stderr)
        self.assertIn("agent-docs/notes/deep: missing required stale.md", verify.stdout + verify.stderr)

        result = run_installer("update", str(repo), input="y\ny\n" * 8)

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("migration 0.12.0:", result.stdout)
        self.assertIn("migration 0.13.0:", result.stdout)
        self.assertIn("migration 0.14.0:", result.stdout)
        self.assertIn("- create agent-docs/notes/deep/stale.md", result.stdout)
        self.assertEqual(
            (notes / "stale.md").read_text(),
            "# Stale Index Archive\n<!-- harness:stale-index-archive -->\n\n",
        )
        self.assertEqual((adr / "stale.md").read_text(), existing_stale)
        for path in (
            docs_root / "notes" / "stale.md",
            notes / "stale" / "stale.md",
            docs_root / "specs" / "stale.md",
            docs_root / "spec-logs" / "stale.md",
        ):
            self.assertFalse(path.exists(), path)
        self.assertEqual(json.loads(manifest_path.read_text())["version"], "0.17.0")
        verify = self.run_verify_rules(repo)
        self.assertEqual(verify.returncode, 0, verify.stdout + verify.stderr)

    def test_0120_dry_run_and_decline_leave_stale_records_absent(self):
        repo = self.install()
        _, _, notes, _, _ = self.prepare_0120_update(repo)
        before = self.snapshot(repo)

        dry_run = run_installer("update", str(repo), "--dry-run")
        self.assertEqual(dry_run.returncode, 0, dry_run.stdout + dry_run.stderr)
        self.assertIn("- create agent-docs/notes/deep/stale.md", dry_run.stdout)
        self.assertEqual(before, self.snapshot(repo))

        declined = run_installer("update", str(repo), input="n\n")
        self.assertEqual(declined.returncode, 1, declined.stdout + declined.stderr)
        self.assertIn("migration 0.12.0:", declined.stdout)
        self.assertEqual(before, self.snapshot(repo))
        self.assertFalse((notes / "stale.md").exists())

    def test_c12_update_from_0120_announces_0130_migration_and_bumps_manifest(self):
        """Independent oracle for spec v4 VO6 (F8, C12): installer MIGRATIONS
        gains (0.13.0, ..., migrate_start_marker_chaining) returning
        instruction strings only, no file changes (Signatures)."""
        repo = self.install()
        manifest_path = repo / ".harness" / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["version"] = "0.12.0"
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
        before = self.snapshot(repo)

        dry_run = run_installer("update", str(repo), "--dry-run")
        self.assertEqual(dry_run.returncode, 0, dry_run.stdout + dry_run.stderr)
        self.assertIn("migration 0.13.0:", dry_run.stdout)
        self.assertIn("chain the workflow start marker after spec lifecycle start", dry_run.stdout)
        self.assertEqual(before, self.snapshot(repo))

        declined = run_installer("update", str(repo), input="n\n")
        self.assertEqual(declined.returncode, 1, declined.stdout + declined.stderr)
        self.assertIn("migration 0.13.0:", declined.stdout)
        self.assertEqual(before, self.snapshot(repo))

        result = run_installer("update", str(repo), input="y\ny\n" * 7)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("migration 0.13.0:", result.stdout)
        self.assertIn("migration 0.14.0:", result.stdout)
        self.assertEqual(json.loads(manifest_path.read_text())["version"], "0.17.0")

    def test_c13_installed_skill_chains_workflow_start_marker_after_spec_lifecycle_start(self):
        """Independent oracle for spec v4 VO6 (F8, C13): SKILL.md Telemetry
        block start line chains workflow_marker.py start after
        spec_lifecycle.py start with '&&' (Signatures)."""
        repo = self.install()
        skill = (repo / ".harness" / "skills" / "workflow-approach" / "SKILL.md").read_text()

        self.assertIn(
            ".harness/bin/spec_lifecycle.py start --spec PATH --run-id ID "
            "&& python3 .harness/bin/workflow_marker.py start",
            skill,
        )

    def test_fix3_disk_already_matches_new_render_is_noop(self):
        repo = self.install()

        sys.path.insert(0, str(REPO_ROOT / "installer"))
        import harness as installer_module

        owned = installer_module.render_owned_files(no_ci=False)
        relpath = ".harness/bin/spec_lifecycle.py"
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

    def test_session_archives_terminal_spec_when_seed_dir_is_empty(self):
        repo = self.install()
        specs = repo / "agent-docs" / "specs"
        (specs / ".seed" / "src").mkdir(parents=True)
        spec = specs / "0123456789abcdef-spec.md"
        spec.write_text("---\nstatus: limit\n---\n")

        proc = self.run_lifecycle(repo, "session")

        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertFalse(spec.exists())
        self.assertTrue((repo / "agent-docs" / "spec-logs" / spec.name).is_file())


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
    def test_c3_malformed_legacy_stale_entry_reports_conflict_without_changes(self):
        repo = self.install()
        docs, _, _, _ = self.prepare_stale_record(repo)
        malformed_entry = "../outside.md"
        (docs.parent / "outside.md").write_text("# Outside handoff\n")
        (docs / "stale.md").write_text(f"{malformed_entry}\n")
        before = self.snapshot(repo)

        result = run_installer("update", str(repo), input="y\ny\ny\ny\ny\ny\n")

        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        output = result.stdout + result.stderr
        self.assertIn("conflict", output.lower())
        self.assertIn(malformed_entry, output)
        self.assertEqual(before, self.snapshot(repo))

    def test_c3_migration_conflicts_are_reported_before_any_change(self):
        repo = self.install()
        docs, source, manifest_path, _ = self.prepare_stale_record(repo)
        (docs / "stale.md").write_text(f"missing.md\n{source.name}\n")
        destination = docs / "stale" / source.name
        destination.write_text("already archived\n")
        before = self.snapshot(repo)

        result = run_installer("update", str(repo), input="y\ny\ny\ny\ny\n")

        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        output = result.stdout + result.stderr
        self.assertIn("missing.md", output)
        self.assertIn(source.name, output)
        self.assertEqual(before, self.snapshot(repo))
        self.assertTrue((docs / "stale.md").exists())
        self.assertTrue(source.exists())
        self.assertEqual(destination.read_text(), "already archived\n")
        self.assertEqual(json.loads(manifest_path.read_text())["version"], "0.2.0")

    def test_c6_invalid_manifest_version_makes_no_changes(self):
        for invalid in (None, "not-a-version"):
            with self.subTest(version=invalid):
                repo = self.install()
                docs, source, manifest_path, _ = self.prepare_stale_record(repo)
                manifest = json.loads(manifest_path.read_text())
                if invalid is None:
                    del manifest["version"]
                else:
                    manifest["version"] = invalid
                manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
                before = self.snapshot(repo)

                result = run_installer("update", str(repo), input="y\ny\ny\ny\ny\n")

                self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                self.assertIn("version", (result.stdout + result.stderr).lower())
                self.assertEqual(before, self.snapshot(repo))
                self.assertTrue((docs / "stale.md").exists())
                self.assertTrue(source.exists())

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
        (repo / ".harness" / "hooks" / "spec_gate.py").unlink()
        result = run_installer("import", str(repo), "--json")
        drift = json.loads(result.stdout)
        self.assertIn(".harness/hooks/spec_gate.py", drift["missing"])


    def test_g_upgrade_preserves_user_modification(self):
        repo = self.install()

        gate = repo / ".harness" / "hooks" / "spec_gate.py"
        original = gate.read_text()
        gate.write_text(original + "\n# local edit\n")

        result = run_installer("upgrade", str(repo))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(gate.read_text().endswith("# local edit\n"))
        self.assertIn(".harness/hooks/spec_gate.py (user-modified)", result.stdout)

        doctor = run_installer("doctor", str(repo))
        self.assertEqual(doctor.returncode, 1, doctor.stdout + doctor.stderr)

    def test_fix2_skipped_file_keeps_old_manifest_sha(self):
        repo = self.install()

        manifest_path = repo / ".harness" / "manifest.json"
        pre_manifest = json.loads(manifest_path.read_text())
        pre_sha = pre_manifest["files"][".harness/hooks/spec_gate.py"]

        gate = repo / ".harness" / "hooks" / "spec_gate.py"
        gate.write_text(gate.read_text() + "\n# local edit\n")

        result = run_installer("upgrade", str(repo))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

        post_manifest = json.loads(manifest_path.read_text())
        post_sha = post_manifest["files"][".harness/hooks/spec_gate.py"]
        self.assertEqual(post_sha, pre_sha)

    def test_i_handoff_missing_or_wrong_heading(self):
        repo = self.install()

        handoff_dir = repo / "agent-docs" / "handoff"
        target_file = handoff_dir / "1234567890abcdef-x.md"
        target_file.write_text(
            "# X\n\n## Goal\ng\n\n## State\ns\n\n## Next Step\nn\n\n"
            "## Open Questions\nq\n\n## Spec Snapshot\nnone\n"
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
            "## Open Questions\nq\n\n## Spec Snapshot\nnone\n"
        )
        verify = self.run_verify_rules(repo)
        self.assertEqual(verify.returncode, 1, verify.stdout + verify.stderr)

    def test_i1_workflow_doc_dirs_skip_index_and_staleness_checks(self):
        repo = self.install()
        docs_root = repo / "agent-docs"
        filename = "1234567890abcdef-x.md"

        control = docs_root / "notes"
        control.mkdir()
        (control / filename).write_text("# X\n")
        verify = self.run_verify_rules(repo)
        self.assertEqual(verify.returncode, 1, verify.stdout + verify.stderr)
        self.assertIn("agent-docs/notes: missing required index.md", verify.stdout + verify.stderr)
        self.assertIn("agent-docs/notes: missing required stale.md", verify.stdout + verify.stderr)
        self.assertIn("agent-docs/notes: missing required stale/ directory", verify.stdout + verify.stderr)
        (control / filename).unlink()
        control.rmdir()

        for name in ("specs", "spec-logs"):
            directory = docs_root / name
            directory.mkdir(parents=True, exist_ok=True)
            (directory / filename).write_text("# X\n")
            self.assertFalse((directory / "index.md").exists())
            self.assertFalse((directory / "stale.md").exists())
            self.assertFalse((directory / "stale").exists())

        verify = self.run_verify_rules(repo)
        self.assertEqual(verify.returncode, 0, verify.stdout + verify.stderr)
        self.assertNotIn("agent-docs/spec", verify.stdout + verify.stderr)

    def test_seed_restore_with_tampered_backup_exits_1_and_keeps_seed(self):
        repo = self.install()
        target = repo / "app.py"
        target.write_bytes(b"original\n")
        backup = self.run_seed(repo, "backup", "app.py")
        self.assertEqual(backup.returncode, 0, backup.stdout + backup.stderr)
        seed_copy = repo / "agent-docs" / "specs" / ".seed" / "app.py"
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
        seed_copy = repo / "agent-docs" / "specs" / ".seed" / "app.py"
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
        seed_dir = repo / "agent-docs" / "specs" / ".seed"
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
        self.assertFalse((repo / "agent-docs" / "specs" / ".seed").exists())


class TestSpecLifecycle(InstallerTestCase):
    def test_validate_requires_all_iso_quality_characteristics(self):
        repo = self.install()
        spec = self.write_valid_spec(repo)
        spec.write_text(spec.read_text().replace("| Safety | no | not affected |\n", ""))

        result = self.run_lifecycle(repo, "validate", "--spec", str(spec))

        self.assertEqual(result.returncode, 1)
        self.assertIn("safety", result.stderr)

    def test_start_is_exclusive_and_resume_is_idempotent(self):
        repo = self.install()
        first = self.write_valid_spec(repo)

        started = self.run_lifecycle(
            repo, "start", "--spec", str(first), "--run-id", "0123456789abcdef"
        )
        resumed = self.run_lifecycle(
            repo, "start", "--spec", str(first), "--run-id", "0123456789abcdef", "--resume"
        )
        second = self.write_valid_spec(repo, "fedcba9876543210", "other")
        rejected = self.run_lifecycle(
            repo, "start", "--spec", str(second), "--run-id", "fedcba9876543210"
        )

        self.assertEqual(started.returncode, 0, started.stderr)
        self.assertEqual(resumed.returncode, 0, resumed.stderr)
        self.assertEqual(rejected.returncode, 1)
        self.assertIn("another workflow is active", rejected.stderr)

    def test_archive_moves_terminal_spec_without_rewriting_it(self):
        repo = self.install()
        spec = self.write_valid_spec(repo)
        self.assertEqual(
            self.run_lifecycle(
                repo, "start", "--spec", str(spec), "--run-id", "0123456789abcdef"
            ).returncode,
            0,
        )
        spec.write_text(spec.read_text().replace("status: active", "status: complete"))
        expected = spec.read_bytes()

        result = self.run_lifecycle(
            repo, "archive", "--spec", str(spec), "--status", "complete"
        )

        archived = repo / "agent-docs" / "spec-logs" / spec.name
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(spec.exists())
        self.assertEqual(archived.read_bytes(), expected)
        self.assertFalse((repo / "agent-docs" / "specs" / ".active").exists())

    def test_session_keeps_active_spec_with_valid_handoff(self):
        repo = self.install()
        handoff = repo / "agent-docs" / "handoff" / "0123456789abcdef-resume.md"
        handoff.write_text("# Resume\n")
        spec = self.write_valid_spec(
            repo, handoff="agent-docs/handoff/0123456789abcdef-resume.md"
        )

        result = self.run_lifecycle(repo, "session")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(spec.is_file())
        self.assertEqual(result.stderr, "")

    def test_070_migration_rejects_legacy_contract_or_seed_without_changes(self):
        for relative in ("old.md", ".seed/app.py"):
            with self.subTest(relative=relative):
                repo = self.install()
                manifest_path = repo / ".harness" / "manifest.json"
                manifest = json.loads(manifest_path.read_text())
                manifest["version"] = "0.6.0"
                manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
                legacy = repo / "agent-docs" / "contracts" / relative
                legacy.parent.mkdir(parents=True, exist_ok=True)
                legacy.write_text("legacy\n")
                before = self.snapshot(repo)

                result = run_installer("update", str(repo), input="y\ny\ny\ny\ny\n")

                self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                self.assertEqual(self.snapshot(repo), before)
                self.assertIn("contract", (result.stdout + result.stderr).lower())


class TestEdge(InstallerTestCase):
    def prepare_070_spec(self, repo, count=1):
        path = self.write_valid_spec(repo)
        content = path.read_text().replace("max_verifier_invocations: 2", "max_correction_rounds: 2")
        content = content.replace("# Workflow Control\n\nnone", f"# Workflow Control\n\n| verifier invocations | {count} |")
        path.write_text(content)
        manifest_path = repo / ".harness" / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["version"] = "0.7.0"
        manifest_path.write_text(json.dumps(manifest))
        return path

    def test_080_migration_preserves_used_budget_and_archived_specs(self):
        for count in (0, 1, 2, 3):
            with self.subTest(count=count):
                repo = self.install()
                path = self.prepare_070_spec(repo, count)
                archived = repo / "agent-docs" / "spec-logs" / path.name
                archived.parent.mkdir(parents=True, exist_ok=True)
                archived.write_bytes(path.read_bytes())
                original = archived.read_bytes()
                before = self.snapshot(repo)
                result = run_installer("update", str(repo), "--dry-run")
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual(before, self.snapshot(repo))
                result = run_installer("update", str(repo), input="y\ny\n" * 12)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                content = path.read_text()
                self.assertIn("version: 2\n", content)
                self.assertIn("max_verifier_invocations: 2\n", content)
                self.assertNotIn("max_correction_rounds:", content)
                self.assertIn(f"| verifier invocations | {count} |", content)
                self.assertIn("## v2", content)
                self.assertEqual(archived.read_bytes(), original)
                validation = self.run_lifecycle(repo, "validate", "--spec", str(path))
                self.assertEqual(validation.returncode, 0, validation.stderr)
                before = self.snapshot(repo)
                result = run_installer("update", str(repo))
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual(before, self.snapshot(repo))

    def test_080_migration_missing_count_or_decline_preserves_files(self):
        for missing_count in (False, True):
            with self.subTest(missing_count=missing_count):
                repo = self.install()
                path = self.prepare_070_spec(repo)
                if missing_count:
                    path.write_text(path.read_text().replace("| verifier invocations | 1 |", "none"))
                before = self.snapshot(repo)
                result = run_installer("update", str(repo), input="n\n")
                self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                self.assertEqual(before, self.snapshot(repo))
                if missing_count:
                    self.assertIn("verifier count", result.stdout + result.stderr)

    def test_verifier_budget_validation_requires_exactly_two(self):
        repo = self.install()
        path = self.write_valid_spec(repo)
        original = path.read_text()
        for field in ("max_verifier_invocations: 0", "max_verifier_invocations: 3",
                      "max_verifier_invocations: invalid", "max_correction_rounds: 2"):
            with self.subTest(field=field):
                path.write_text(original.replace("max_verifier_invocations: 2", field))
                result = self.run_lifecycle(repo, "validate", "--spec", str(path))
                self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                self.assertIn("max_verifier_invocations must be 2", result.stderr)

    def test_090_migration_preserves_spec_decisions_and_installs_new_roles(self):
        repo = self.install()
        active = self.write_valid_spec(repo)
        active.write_text(active.read_text().replace(
            "# Workflow Control\n\nnone", "# Workflow Control\n\n| verifier invocations | 1 |"))
        archived = repo / "agent-docs" / "spec-logs" / active.name
        archived.parent.mkdir(parents=True, exist_ok=True)
        archived.write_bytes(active.read_bytes())
        original = active.read_bytes()
        manifest_path = repo / ".harness" / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["version"] = "0.8.0"
        manifest_path.write_text(json.dumps(manifest))
        before = self.snapshot(repo)

        dry_run = run_installer("update", str(repo), "--dry-run")
        self.assertEqual(dry_run.returncode, 0, dry_run.stdout + dry_run.stderr)
        self.assertIn("before resume", dry_run.stdout)
        self.assertEqual(before, self.snapshot(repo))
        declined = run_installer("update", str(repo), input="n\n")
        self.assertEqual(declined.returncode, 1)
        self.assertEqual(before, self.snapshot(repo))

        result = run_installer("update", str(repo), input="y\ny\n" * 11)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("migration 0.9.0:", result.stdout)
        self.assertEqual(active.read_bytes(), original)
        self.assertEqual(archived.read_bytes(), original)
        for name in ("test-implementer", "test-verifier"):
            source = (REPO_ROOT / "harness" / "agents" / f"{name}.md").read_text()
            installed = repo / ".harness" / "agents" / f"{name}.md"
            self.assertEqual(installed.read_text(), source)
        repeated = run_installer("update", str(repo))
        self.assertEqual(repeated.returncode, 0, repeated.stdout + repeated.stderr)
        self.assertNotIn("migration 0.9.0:", repeated.stdout)

    def test_0100_migration_preserves_specs_and_installs_coverage_targets(self):
        repo = self.install()
        active = self.write_valid_spec(repo)
        active.write_text(active.read_text().replace(
            "# Workflow Control\n\nnone", "# Workflow Control\n\n| verifier invocations | 1 |"))
        archived = repo / "agent-docs" / "spec-logs" / active.name
        archived.parent.mkdir(parents=True, exist_ok=True)
        archived.write_bytes(active.read_bytes())
        original = active.read_bytes()
        manifest_path = repo / ".harness" / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["version"] = "0.9.0"
        manifest_path.write_text(json.dumps(manifest))
        before = self.snapshot(repo)

        dry_run = run_installer("update", str(repo), "--dry-run")
        self.assertEqual(dry_run.returncode, 0, dry_run.stdout + dry_run.stderr)
        self.assertIn("migration 0.10.0:", dry_run.stdout)
        self.assertIn("before resume", dry_run.stdout)
        self.assertEqual(before, self.snapshot(repo))
        declined = run_installer("update", str(repo), input="n\n")
        self.assertEqual(declined.returncode, 1)
        self.assertEqual(before, self.snapshot(repo))

        result = run_installer("update", str(repo), input="y\ny\n" * 10)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("migration 0.10.0:", result.stdout)
        self.assertNotIn("migration 0.9.0:", result.stdout)
        self.assertEqual(active.read_bytes(), original)
        self.assertEqual(archived.read_bytes(), original)
        workflow = (repo / ".harness" / "skills" / "workflow-approach" / "SKILL.md").read_text()
        self.assertIn("ISO/IEC/IEEE 29119-4 technique | coverage items | coverage target", workflow)
        self.assertNotIn("boundary/transition/combination", workflow)
        stop = workflow[workflow.index("**Stop condition.**"):]
        self.assertIn("approved coverage target", stop[:stop.index("\n9. ")])
        repeated = run_installer("update", str(repo))
        self.assertEqual(repeated.returncode, 0, repeated.stdout + repeated.stderr)
        self.assertNotIn("migration 0.10.0:", repeated.stdout)

    def test_c4_update_runs_03_04_06_07_08_09_010_migrations_once_each(self):
        repo = self.install()
        docs, source, _, index_block = self.prepare_stale_record(repo)

        result = run_installer("update", str(repo), input="y\ny\n" * 16)

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        output = result.stdout + result.stderr
        announcement_versions = [
            match.group(0)
            for line in output.splitlines()
            if line.startswith("migration ")
            for match in [re.search(r"\b0\.\d+\.\d+\b", line)]
            if match
        ]
        self.assertEqual(announcement_versions, ["0.3.0", "0.4.0", "0.6.0", "0.7.0", "0.8.0", "0.9.0", "0.10.0", "0.11.0", "0.12.0", "0.13.0", "0.14.0", "0.15.0", "0.15.1", "0.16.0", "0.16.1", "0.16.2", "0.17.0"], output)
        self.assertFalse(source.exists())
        self.assertEqual((docs / "stale" / source.name).read_text(), "# Stale\n")
        self.assertNotIn(index_block, (docs / "index.md").read_text())
        stale_log = (docs / "stale.md").read_text()
        self.assertEqual(
            stale_log.splitlines()[:2],
            ["# Stale Index Archive", "<!-- harness:stale-index-archive -->"],
        )
        self.assertIn(index_block, stale_log)
        archive_format = stale_log.replace(index_block, "")
        self.assertTrue(archive_format.strip())
        self.assertNotIn(f"{source.name}\n", archive_format)

    def test_c4_declining_any_migration_confirmation_preserves_files(self):
        for response in ("n\n", "no\n", "not-sure\n", "\n"):
            with self.subTest(response=response):
                repo = self.install()
                docs, source, manifest_path, _ = self.prepare_stale_record(repo)
                before = self.snapshot(repo)

                result = run_installer("update", str(repo), input=response)

                self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                self.assertIn("migration", (result.stdout + result.stderr).lower())
                self.assertEqual(before, self.snapshot(repo))
                self.assertTrue((docs / "stale.md").exists())
                self.assertTrue(source.exists())
                self.assertEqual(json.loads(manifest_path.read_text())["version"], "0.2.0")

    def test_c4_declining_second_migration_confirmation_preserves_files(self):
        repo = self.install()
        docs, source, manifest_path, _ = self.prepare_stale_record(repo)
        before = self.snapshot(repo)

        result = run_installer("update", str(repo), input="y\nn\n")

        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("migration", (result.stdout + result.stderr).lower())
        self.assertEqual(before, self.snapshot(repo))
        self.assertTrue((docs / "stale.md").exists())
        self.assertTrue(source.exists())
        self.assertEqual(json.loads(manifest_path.read_text())["version"], "0.2.0")

    def test_c5_dry_run_reports_migration_without_writing(self):
        repo = self.install()
        docs, source, manifest_path, _ = self.prepare_stale_record(repo)
        before = self.snapshot(repo)

        result = run_installer("update", str(repo), "--dry-run", input="y\ny\ny\ny\n")

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        output = (result.stdout + result.stderr).lower()
        self.assertIn("migration", output)
        self.assertIn("stale", output)
        self.assertEqual(before, self.snapshot(repo))
        self.assertTrue((docs / "stale.md").exists())
        self.assertTrue(source.exists())
        self.assertEqual(json.loads(manifest_path.read_text())["version"], "0.2.0")

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

    def assert_session_keeps_stranded_seed(self):
        repo = self.stranded_seed_repo()
        seed_copy = repo / "agent-docs" / "specs" / ".seed" / "app.py"

        proc = self.run_lifecycle(repo, "session")

        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertEqual(seed_copy.read_bytes(), b"original\n")
        self.assertIn("seed.py restore", proc.stderr)

    def test_session_end_keeps_specs_while_seed_unrestored(self):
        self.assert_session_keeps_stranded_seed()

    def test_codex_clear_keeps_specs_while_seed_unrestored(self):
        self.assert_session_keeps_stranded_seed()

    def test_post_merge_does_not_run_spec_lifecycle(self):
        repo = self.install()
        post_merge = (repo / ".harness" / "git" / "post-merge").read_text()
        self.assertNotIn("spec_lifecycle", post_merge)

    def test_restore_after_kept_session_recovers_original(self):
        repo = self.stranded_seed_repo()
        session = self.run_lifecycle(repo, "session")
        self.assertEqual(session.returncode, 0, session.stdout + session.stderr)

        restore = self.run_seed(repo, "restore")

        self.assertEqual(restore.returncode, 0, restore.stdout + restore.stderr)
        self.assertEqual((repo / "app.py").read_bytes(), b"original\n")


def load_installer_module():
    sys.path.insert(0, str(REPO_ROOT / "installer"))
    import harness as installer_module

    return installer_module


class TestGitignoreGuard(InstallerTestCase):
    """Spec be4f57b2715f7898 v1. Expected Conflict lines are written literally
    from the spec's format "<relpath> is ignored by git (<source>:<n>:<pattern>)"."""

    HARNESS_BIN_LINES = [
        ".harness/bin/seed.py is ignored by git (.gitignore:1:bin/)",
        ".harness/bin/spec_lifecycle.py is ignored by git (.gitignore:1:bin/)",
        ".harness/bin/workflow_marker.py is ignored by git (.gitignore:1:bin/)",
    ]

    def ignore_lines(self, result):
        items = [line.strip() for line in result.stdout.splitlines() if " is ignored by git (" in line]
        return [
            item.removeprefix("- ").removeprefix("warning: ")
            for item in items
        ]

    def set_manifest_version(self, repo, version):
        path = repo / ".harness" / "manifest.json"
        manifest = json.loads(path.read_text())
        manifest["version"] = version
        path.write_text(json.dumps(manifest, indent=2) + "\n")
        return path

    def ignored_fresh_repo(self, rules="bin/\n"):
        repo = self.make_repo()
        (repo / ".gitignore").write_text(rules)
        return repo

    def installed_ignored_repo(self, rules="bin/\n"):
        repo = self.install()
        (repo / ".gitignore").write_text(rules)
        return repo

    def assert_conflict_only(self, result, expected_lines):
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertEqual(sorted(set(self.ignore_lines(result))), sorted(expected_lines), result.stdout)

    # VO1 EP1 / VO3 P1 (C1)
    def test_c1_ep1_p1_install_reports_ignored_harness_bin_and_writes_nothing(self):
        repo = self.ignored_fresh_repo()
        before = self.snapshot(repo)

        result = run_installer("install", str(repo))

        self.assert_conflict_only(result, self.HARNESS_BIN_LINES)
        self.assertEqual(before, self.snapshot(repo))
        self.assertEqual(list(before), [".gitignore"])

    # VO1 EP2 (C2)
    def test_c2_ep2_update_declined_ignore_consent_keeps_manifest(self):
        repo = self.installed_ignored_repo()
        manifest_path = self.set_manifest_version(repo, "0.17.0")
        before = self.snapshot(repo)

        result = run_installer("update", str(repo), input="n\n")

        self.assert_conflict_only(result, self.HARNESS_BIN_LINES)
        self.assertNotIn("migration", (result.stdout + result.stderr).lower())
        self.assertEqual(json.loads(manifest_path.read_text())["version"], "0.17.0")
        self.assertEqual(before, self.snapshot(repo))

    # VO1 EP3 (C3)
    def test_c3_ep3_doctor_reports_ignored_files_of_installed_repo(self):
        repo = self.installed_ignored_repo()
        before = self.snapshot(repo)

        result = run_installer("doctor", str(repo))

        self.assert_conflict_only(result, self.HARNESS_BIN_LINES)
        self.assertEqual(before, self.snapshot(repo))

    # VO1 EP4 (C9)
    def test_c9_ep4_install_dry_run_reports_conflict_and_writes_nothing(self):
        repo = self.ignored_fresh_repo()
        before = self.snapshot(repo)

        result = run_installer("install", str(repo), "--dry-run")

        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertEqual(sorted(self.ignore_lines(result)), sorted(self.HARNESS_BIN_LINES))
        self.assertIn("ignored harness paths: .gitignore exceptions require consent (dry-run)", result.stdout)
        self.assertNotIn("execution requires consent to update .gitignore", result.stdout)
        self.assertEqual(before, self.snapshot(repo))

    # VO1 EP5 (C9)
    def test_c9_ep5_update_dry_run_reports_conflict_and_writes_nothing(self):
        repo = self.installed_ignored_repo()
        manifest_path = self.set_manifest_version(repo, "0.13.0")
        before = self.snapshot(repo)

        result = run_installer("update", str(repo), "--dry-run")

        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertEqual(sorted(self.ignore_lines(result)), sorted(self.HARNESS_BIN_LINES))
        self.assertIn("ignored harness paths: .gitignore exceptions require consent (dry-run)", result.stdout)
        self.assertNotIn("execution requires consent to update .gitignore", result.stdout)
        announced = re.findall(r"^migration (0\.\d+\.\d+):", result.stdout, re.MULTILINE)
        self.assertEqual(announced, ["0.14.0", "0.15.0", "0.15.1", "0.16.0", "0.16.1", "0.16.2", "0.17.0"])
        self.assertEqual(result.stdout.count("- confirmation required (dry-run: not requested)"), 6)
        write = result.stdout.split("== write ==\n", 1)[1].split("\n== ", 1)[0]
        self.assertIn("- .harness/VERSION", write.splitlines())
        self.assertEqual(json.loads(manifest_path.read_text())["version"], "0.13.0")
        self.assertEqual(before, self.snapshot(repo))

    # VO2 R1 (C4)
    def test_c4_r1_no_ignore_rules_install_update_doctor_succeed(self):
        repo = self.make_repo()

        install = run_installer("install", str(repo))
        self.assertEqual(install.returncode, 0, install.stdout + install.stderr)
        self.assertEqual(self.ignore_lines(install), [])
        self.set_manifest_version(repo, "0.13.0")
        update = run_installer("update", str(repo), input="y\ny\ny\ny\ny\ny\n")
        self.assertEqual(update.returncode, 0, update.stdout + update.stderr)
        self.assertEqual(self.ignore_lines(update), [])
        doctor = run_installer("doctor", str(repo))
        self.assertEqual(doctor.returncode, 0, doctor.stdout + doctor.stderr)
        self.assertEqual(self.ignore_lines(doctor), [])

    # VO2 R2 is covered by test_c1_ep1_p1 (rule match, untracked -> conflict).

    # VO2 R3 (C5)
    def test_c5_r3_negated_pattern_exempts_path(self):
        repo = self.ignored_fresh_repo("bin/\n!.harness/bin/\n")

        result = run_installer("install", str(repo))

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.ignore_lines(result), [])
        self.assertTrue((repo / ".harness" / "bin" / "seed.py").exists())

    # VO2 R3 variant: file-level negations, which check-ignore -v does print
    def test_c5_r3_file_level_negations_exempt_paths(self):
        repo = self.ignored_fresh_repo(
            ".harness/bin/*.py\n"
            "!.harness/bin/seed.py\n"
            "!.harness/bin/spec_lifecycle.py\n"
            "!.harness/bin/workflow_marker.py\n"
        )

        result = run_installer("install", str(repo))

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.ignore_lines(result), [])
        self.assertTrue((repo / ".harness" / "bin" / "seed.py").exists())

    # VO2 R4 (C6)
    def test_c6_r4_tracked_files_matching_a_rule_are_not_conflicts(self):
        repo = self.install()
        run_git(repo, "add", "-f", ".harness/bin/seed.py", ".harness/bin/spec_lifecycle.py", ".harness/bin/workflow_marker.py")
        run_git(repo, "commit", "-q", "-m", "track harness bin")
        (repo / ".gitignore").write_text("bin/\n")

        doctor = run_installer("doctor", str(repo))
        self.assertEqual(doctor.returncode, 0, doctor.stdout + doctor.stderr)
        self.assertEqual(self.ignore_lines(doctor), [])

        self.set_manifest_version(repo, "0.13.0")
        update = run_installer("update", str(repo), input="y\ny\ny\ny\ny\ny\n")
        self.assertEqual(update.returncode, 0, update.stdout + update.stderr)
        self.assertEqual(self.ignore_lines(update), [])

    # VO3 P2 (C7)
    def test_c7_p2_managed_agents_md_ignored(self):
        repo = self.ignored_fresh_repo("AGENTS.md\n")
        before = self.snapshot(repo)

        result = run_installer("install", str(repo))

        self.assert_conflict_only(result, ["AGENTS.md is ignored by git (.gitignore:1:AGENTS.md)"])
        self.assertEqual(before, self.snapshot(repo))

    # VO3 P3 (C10)
    def test_c10_p3_codex_agent_toml_ignored_via_info_exclude(self):
        repo = self.make_repo()
        (repo / ".git" / "info" / "exclude").write_text("*.toml\n")
        names = sorted(p.stem for p in (REPO_ROOT / "harness" / "agents").glob("*.md"))
        self.assertTrue(names)
        before = self.snapshot(repo)

        result = run_installer("install", str(repo))

        self.assert_conflict_only(
            result,
            [f".codex/agents/{name}.toml is ignored by git (.git/info/exclude:1:*.toml)" for name in names],
        )
        self.assertEqual(before, self.snapshot(repo))

    # VO3 P4 (C8)
    def test_c8_p4_ci_files_are_not_guarded_with_no_ci(self):
        repo = self.ignored_fresh_repo(".github/\n")

        result = run_installer("install", str(repo), "--no-ci")

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.ignore_lines(result), [])
        self.assertFalse((repo / ".github").exists())

    # VO4 M1, M2 (C12)
    def test_c12_m1_m2_update_announces_0140_and_records_version(self):
        repo = self.install()
        manifest_path = self.set_manifest_version(repo, "0.13.0")
        before = self.snapshot(repo)

        dry_run = run_installer("update", str(repo), "--dry-run")
        self.assertEqual(dry_run.returncode, 0, dry_run.stdout + dry_run.stderr)
        self.assertIn("migration 0.14.0:", dry_run.stdout)
        self.assertNotIn("migration 0.13.0:", dry_run.stdout)
        self.assertEqual(before, self.snapshot(repo))

        result = run_installer("update", str(repo), input="y\ny\n" * 6)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(json.loads(manifest_path.read_text())["version"], "0.17.0")
        self.assertEqual((REPO_ROOT / "harness" / "VERSION").read_text().strip(), "0.17.0")

    # VO4 M3: existing version-list assertions (test_c4_update_runs_..., 0120 tests,
    # test_0110_install_with_existing_block..., test_c12_update_from_0120...) now include 0.15.0.

    def make_check_repo(self, rules):
        repo = self.make_repo()
        (repo / ".gitignore").write_text(rules)
        return repo

    def recording_run_git(self, module, override=None):
        calls = []
        real = module.run_git

        def wrapper(target, args, stdin=None):
            calls.append(list(args))
            if override is not None and "check-ignore" in args:
                return override(real(target, args, stdin))
            return real(target, args, stdin)

        return calls, wrapper

    # VO5 G1 (C11)
    def test_c11_g1_git_failure_reported_as_single_failure_line(self):
        from unittest import mock

        module = load_installer_module()
        repo = self.make_check_repo("bin/\n")

        def fail(real_result):
            stderr = "fatal: boom\nsecond line\n"
            if isinstance(real_result.stderr, bytes):
                stderr = stderr.encode()
            return subprocess.CompletedProcess(real_result.args, 128, real_result.stdout, stderr)

        calls, wrapper = self.recording_run_git(module, fail)
        with mock.patch.object(module, "run_git", wrapper):
            lines = module.find_ignored_paths(repo, [".harness/bin/seed.py", "AGENTS.md"])

        self.assertTrue(any("check-ignore" in c for c in calls))
        self.assertEqual(lines, ["git check-ignore failed: fatal: boom"])

    def failing_check_ignore(self, module):
        def fail(real_result):
            stderr = "fatal: boom\n"
            if isinstance(real_result.stderr, bytes):
                stderr = stderr.encode()
            return subprocess.CompletedProcess(real_result.args, 128, real_result.stdout, stderr)

        return self.recording_run_git(module, fail)

    def run_main_with_git_failure(self, argv):
        import contextlib
        import io
        from unittest import mock

        module = load_installer_module()
        _, wrapper = self.failing_check_ignore(module)
        out = io.StringIO()
        with mock.patch.object(module, "run_git", wrapper), \
                mock.patch("builtins.input", side_effect=AssertionError("prompted")), \
                contextlib.redirect_stdout(out):
            code = module.main(argv)
        return code, out.getvalue()

    def assert_git_failure_conflict(self, code, stdout):
        self.assertEqual(code, 1, stdout)
        self.assertIn("== conflict ==", stdout)
        section = stdout[stdout.index("== conflict =="):]
        self.assertIn("git check-ignore failed: fatal: boom", section)

    # VO5 G1 (Q3): install aborts with exit 1 and writes nothing
    def test_q3_g1_install_git_failure_exits_1_and_writes_nothing(self):
        repo = self.make_repo()
        (repo / "README.md").write_text("pre-existing\n")
        before = self.snapshot(repo)

        code, stdout = self.run_main_with_git_failure(["install", str(repo)])

        self.assert_git_failure_conflict(code, stdout)
        self.assertEqual(before, self.snapshot(repo))

    # VO5 G1 (Q3): update aborts before migrations, manifest unchanged
    def test_q3_g1_update_git_failure_exits_1_and_writes_nothing(self):
        repo = self.install()
        manifest_path = self.set_manifest_version(repo, "0.13.0")
        before = self.snapshot(repo)

        code, stdout = self.run_main_with_git_failure(["update", str(repo)])

        self.assert_git_failure_conflict(code, stdout)
        self.assertEqual(json.loads(manifest_path.read_text())["version"], "0.13.0")
        self.assertEqual(before, self.snapshot(repo))

    def test_q3_g1_dry_runs_and_doctor_report_git_failure(self):
        fresh = self.make_repo()
        installed = self.install()
        self.set_manifest_version(installed, "0.13.0")
        for argv, repo in (
            (["install", "--dry-run", str(fresh)], fresh),
            (["update", "--dry-run", str(installed)], installed),
            (["doctor", str(installed)], installed),
        ):
            with self.subTest(argv=argv[:-1]):
                before = self.snapshot(repo)
                code, stdout = self.run_main_with_git_failure(argv)
                self.assert_git_failure_conflict(code, stdout)
                self.assertEqual(before, self.snapshot(repo))

    MANAGED_PATHS = (
        ".harness/manifest.json",
        "AGENTS.md",
        "CLAUDE.md",
        ".claude/settings.json",
        ".codex/hooks.json",
    )

    def test_p2_each_managed_path_is_guarded_by_install_update_and_doctor(self):
        for relpath in self.MANAGED_PATHS:
            expected = [f"{relpath} is ignored by git (.gitignore:1:{relpath})"]
            with self.subTest(command="install", path=relpath):
                repo = self.ignored_fresh_repo(relpath + "\n")
                before = self.snapshot(repo)
                result = run_installer("install", str(repo))
                self.assert_conflict_only(result, expected)
                self.assertEqual(before, self.snapshot(repo))
            installed = self.installed_ignored_repo(relpath + "\n")
            with self.subTest(command="doctor", path=relpath):
                self.assert_conflict_only(run_installer("doctor", str(installed)), expected)
            with self.subTest(command="update", path=relpath):
                before = self.snapshot(installed)
                result = run_installer("update", str(installed), input="n\n")
                self.assert_conflict_only(result, expected)
                self.assertEqual(before, self.snapshot(installed))

    # VO6 B1 (Q1)
    def test_q1_b1_many_paths_use_at_most_one_check_ignore_call(self):
        from unittest import mock

        module = load_installer_module()
        repo = self.make_check_repo("bin/\n")
        ignored = [f".harness/bin/tool{i:03d}.py" for i in range(60)]
        clean = [f".harness/lib/mod{i:03d}.py" for i in range(60)]
        paths = clean + ignored
        calls, wrapper = self.recording_run_git(module)

        with mock.patch.object(module, "run_git", wrapper):
            lines = module.find_ignored_paths(repo, paths)

        check_calls = [c for c in calls if "check-ignore" in c]
        self.assertLessEqual(len(check_calls), 1, check_calls)
        self.assertEqual(
            lines,
            [f"{p} is ignored by git (.gitignore:1:bin/)" for p in sorted(ignored)],
        )

    # VO7 S1 (Q2)
    def test_q2_s1_path_with_space_reported_verbatim(self):
        module = load_installer_module()
        repo = self.make_check_repo("my dir/\n")

        lines = module.find_ignored_paths(repo, ["my dir/file.txt", "other/file.txt"])

        self.assertEqual(lines, ["my dir/file.txt is ignored by git (.gitignore:1:my dir/)"])

    # VO7 S2 (Q2)
    def test_q2_s2_path_with_hangul_reported_verbatim(self):
        module = load_installer_module()
        repo = self.make_check_repo("*.txt\n")

        lines = module.find_ignored_paths(repo, ["my dir/한글 파일.txt", "my dir/keep.md"])

        self.assertEqual(lines, ["my dir/한글 파일.txt is ignored by git (.gitignore:1:*.txt)"])


class TestGitignoreConsent(InstallerTestCase):
    QUESTION = "Add .gitignore exceptions for these harness paths and continue? [y/N] "
    MANAGED_PATHS = (
        ".harness/manifest.json",
        "AGENTS.md",
        "CLAUDE.md",
        ".claude/settings.json",
        ".codex/hooks.json",
    )
    GUARDED_BIN = (
        ".harness/bin/seed.py",
        ".harness/bin/spec_lifecycle.py",
        ".harness/bin/workflow_marker.py",
    )

    def ignored(self, repo, path):
        result = subprocess.run(
            ["git", "-C", str(repo), "check-ignore", "--no-index", "-q", "--", path],
            capture_output=True,
        )
        self.assertIn(result.returncode, (0, 1), result.stderr)
        return result.returncode == 0

    def ignored_bin_repo(self):
        repo = self.make_repo()
        (repo / ".gitignore").write_bytes(b"bin/\r\n# retained\r\n")
        return repo

    def assert_narrow_bin_exceptions(self, repo, before):
        after = (repo / ".gitignore").read_bytes()
        self.assertTrue(after.startswith(before))
        self.assertFalse(self.ignored(repo, self.GUARDED_BIN[0]))
        for path in self.GUARDED_BIN:
            self.assertFalse(self.ignored(repo, path), path)
        self.assertTrue(self.ignored(repo, "unrelated/bin/keep.py"))
        self.assertNotIn(b"!**", after)
        return after

    def test_vo1_install_yes_clears_git_ignore_and_prompts_once(self):
        repo = self.ignored_bin_repo()
        before = (repo / ".gitignore").read_bytes()
        result = run_installer("install", str(repo), input="y\ny\n")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stdout.count(self.QUESTION), 1)
        self.assertIn("bin/", result.stdout)
        self.assert_narrow_bin_exceptions(repo, before)
        manifest = json.loads((repo / ".harness" / "manifest.json").read_text())
        guarded = set(manifest["files"]) | set(self.MANAGED_PATHS)
        self.assertTrue(set(self.GUARDED_BIN) <= guarded)
        for path in sorted(guarded):
            with self.subTest(path=path):
                self.assertFalse(self.ignored(repo, path), path)
        self.assertEqual(run_installer("doctor", str(repo)).returncode, 0)

    def test_vo1_update_yes_clears_git_ignore_then_migrates(self):
        repo = self.make_repo()
        self.assertEqual(run_installer("install", str(repo)).returncode, 0)
        manifest = repo / ".harness" / "manifest.json"
        data = json.loads(manifest.read_text())
        data["version"] = "0.14.0"
        manifest.write_text(json.dumps(data, indent=2) + "\n")
        (repo / ".gitignore").write_text("bin/\n")
        result = run_installer("update", str(repo), input="y\ny\ny\ny\ny\ny\n")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stdout.count(self.QUESTION), 1)
        self.assertIn("migration 0.15.0:", result.stdout)
        self.assertIn("migration 0.15.1:", result.stdout)
        self.assertEqual(json.loads(manifest.read_text())["version"], "0.17.0")
        self.assert_narrow_bin_exceptions(repo, b"bin/\n")

    def test_vo2_no_and_eof_leave_entire_target_unchanged(self):
        for answer in ("n\n", ""):
            with self.subTest(answer=answer):
                repo = self.ignored_bin_repo()
                before = self.snapshot(repo)
                result = run_installer("install", str(repo), input=answer)
                self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                self.assertEqual(result.stdout.count(self.QUESTION), 1)
                self.assertEqual(self.snapshot(repo), before)

    def test_vo2_nested_override_restores_original_gitignore_bytes(self):
        repo = self.ignored_bin_repo()
        nested = repo / ".harness" / ".gitignore"
        nested.parent.mkdir()
        nested.write_text("bin/\n")
        before = self.snapshot(repo)
        original = (repo / ".gitignore").read_bytes()
        result = run_installer("install", str(repo), input="y\ny\n")
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertEqual((repo / ".gitignore").read_bytes(), original)
        self.assertEqual(self.snapshot(repo), before)

    def test_vo2_second_git_check_failure_restores_gitignore_and_target(self):
        import contextlib
        import io
        from unittest import mock

        module = load_installer_module()
        repo = self.ignored_bin_repo()
        original_ignore = (repo / ".gitignore").read_bytes()
        before = self.snapshot(repo)
        real_run_git = module.run_git
        checks = []

        def fail_confirmation(target, args, stdin=None):
            if "check-ignore" not in args:
                return real_run_git(target, args, stdin)
            checks.append((repo / ".gitignore").read_bytes())
            result = real_run_git(target, args, stdin)
            if len(checks) == 2:
                stderr = b"fatal: confirmation failed\n" if isinstance(result.stderr, bytes) else "fatal: confirmation failed\n"
                return subprocess.CompletedProcess(result.args, 128, result.stdout, stderr)
            return result

        output = io.StringIO()
        with mock.patch.object(module, "run_git", fail_confirmation), \
                mock.patch("sys.stdin", io.StringIO("y\n")), \
                contextlib.redirect_stdout(output):
            code = module.main(["install", str(repo)])

        self.assertEqual(len(checks), 2, checks)
        self.assertEqual(checks[0], original_ignore)
        self.assertNotEqual(checks[1], original_ignore)
        self.assertEqual(code, 1, output.getvalue())
        self.assertIn("git check-ignore failed", output.getvalue())
        self.assertEqual((repo / ".gitignore").read_bytes(), original_ignore)
        self.assertEqual(self.snapshot(repo), before)

    def test_vo2_preexisting_conflict_does_not_prompt_or_write(self):
        repo = self.ignored_bin_repo()
        (repo / ".harness").write_text("occupied\n")
        before = self.snapshot(repo)
        result = run_installer("install", str(repo), input="y\ny\n")
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertNotIn(self.QUESTION, result.stdout)
        self.assertEqual(self.snapshot(repo), before)

    def test_vo3_dry_runs_preview_without_prompt_or_writes(self):
        # 0.15.1: .harness/ itself is not ignored by `bin/`, so no `!/.harness/` line.
        expected_lines = [
            "!/.harness/bin/",
            "/.harness/bin/*",
            *[f"!/{path}" for path in self.GUARDED_BIN],
        ]
        for command in ("install", "update"):
            with self.subTest(command=command):
                repo = self.make_repo()
                if command == "update":
                    self.assertEqual(run_installer("install", str(repo)).returncode, 0)
                (repo / ".gitignore").write_text("bin/\n")
                before = self.snapshot(repo)
                result = run_installer(command, str(repo), "--dry-run", input="")
                self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                self.assertIn("bin/", result.stdout)
                planned = [
                    line.removeprefix("planned .gitignore exception: ")
                    for line in result.stdout.splitlines()
                    if line.startswith("planned .gitignore exception: ")
                ]
                self.assertEqual(planned, expected_lines)
                self.assertNotIn("execution requires consent to update .gitignore", result.stdout)
                self.assertNotIn(self.QUESTION, result.stdout)
                self.assertEqual(self.snapshot(repo), before)

    def test_vo3_doctor_reports_ignores_read_only(self):
        repo = self.make_repo()
        self.assertEqual(run_installer("install", str(repo)).returncode, 0)
        (repo / ".gitignore").write_text("bin/\n")
        before = self.snapshot(repo)
        result = run_installer("doctor", str(repo))
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn(".harness/bin/seed.py is ignored by git", result.stdout)
        self.assertNotIn(self.QUESTION, result.stdout)
        self.assertEqual(self.snapshot(repo), before)

    def test_vo4_info_exclude_and_global_rules_create_root_gitignore(self):
        for source in ("info", "global"):
            with self.subTest(source=source):
                repo = self.make_repo()
                if source == "info":
                    (repo / ".git" / "info" / "exclude").write_text("bin/\n")
                else:
                    exclude = repo / "global-ignore"
                    exclude.write_text("bin/\n")
                    run_git(repo, "config", "core.excludesFile", str(exclude))
                result = run_installer("install", str(repo), input="y\ny\n")
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual(result.stdout.count(self.QUESTION), 1)
                self.assertTrue((repo / ".gitignore").exists())
                self.assert_narrow_bin_exceptions(repo, b"")

    def test_vo5_existing_exceptions_do_not_duplicate_or_prompt(self):
        repo = self.ignored_bin_repo()
        first = run_installer("install", str(repo), input="y\ny\n")
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        prior = (repo / ".gitignore").read_bytes()
        repeated = run_installer("update", str(repo), input="")
        self.assertEqual(repeated.returncode, 0, repeated.stdout + repeated.stderr)
        self.assertEqual((repo / ".gitignore").read_bytes(), prior)
        self.assertNotIn(self.QUESTION, repeated.stdout)

    def test_vo4_synthetic_names_get_literal_exceptions_and_leave_siblings_ignored(self):
        import contextlib
        import io
        from unittest import mock

        module = load_installer_module()
        repo = self.make_repo()
        (repo / ".gitignore").write_text("*.py\n")
        selected = (
            ".harness/bin/with space.py",
            ".harness/bin/한글.py",
            ".harness/bin/name[ab].py",
            ".harness/bin/star*.py",
            ".harness/bin/question?.py",
        )
        siblings = (
            ".harness/bin/with-space.py",
            ".harness/bin/다른글.py",
            ".harness/bin/namea.py",
            ".harness/bin/starX.py",
            ".harness/bin/questionX.py",
        )
        render = module.render_owned_files

        def with_synthetic_paths(no_ci=False):
            owned = render(no_ci=no_ci).copy()
            owned.update({path: b"synthetic\n" for path in selected})
            return owned

        output = io.StringIO()
        with mock.patch.object(module, "render_owned_files", with_synthetic_paths), \
                mock.patch("sys.stdin", io.StringIO("y\n")), \
                contextlib.redirect_stdout(output):
            code = module.main(["install", str(repo)])
        self.assertEqual(code, 0, output.getvalue())
        self.assertEqual(output.getvalue().count(self.QUESTION), 1)
        for path in selected:
            self.assertFalse(self.ignored(repo, path), path)
        for path in siblings:
            self.assertTrue(self.ignored(repo, path), path)
        self.assertNotIn("!**", (repo / ".gitignore").read_text())

    def test_vo6_from_0140_decline_then_confirm_and_record_0150(self):
        repo = self.make_repo()
        self.assertEqual(run_installer("install", str(repo)).returncode, 0)
        manifest = repo / ".harness" / "manifest.json"
        data = json.loads(manifest.read_text())
        data["version"] = "0.14.0"
        manifest.write_text(json.dumps(data, indent=2) + "\n")
        before = self.snapshot(repo)
        declined = run_installer("update", str(repo), input="n\n")
        self.assertEqual(declined.returncode, 1, declined.stdout + declined.stderr)
        self.assertIn("migration 0.15.0:", declined.stdout)
        self.assertEqual(self.snapshot(repo), before)
        confirmed = run_installer("update", str(repo), input="y\ny\ny\ny\ny\n")
        self.assertEqual(confirmed.returncode, 0, confirmed.stdout + confirmed.stderr)
        self.assertIn("migration 0.15.0:", confirmed.stdout)
        self.assertIn("migration 0.15.1:", confirmed.stdout)
        self.assertNotIn("migration 0.14.0:", confirmed.stdout)
        self.assertEqual(json.loads(manifest.read_text())["version"], "0.17.0")

    def test_vo7_hundred_paths_scan_each_batch_once(self):
        from unittest import mock

        module = load_installer_module()
        repo = self.make_repo()
        (repo / ".gitignore").write_text("bin/\n")
        paths = [f".harness/bin/tool{i:03d}.py" for i in range(100)]
        calls = []
        original = module.run_git

        def recording(target, args, stdin=None):
            if "check-ignore" in args:
                calls.append(list(args))
            return original(target, args, stdin)

        with mock.patch.object(module, "run_git", recording):
            initial = module.find_ignored_paths(repo, paths)
            initial_calls = len(calls)
            (repo / ".gitignore").write_text("bin/\n!/.harness/\n!/.harness/bin/\n")
            confirmation = module.find_ignored_paths(repo, paths)
        self.assertEqual(len(initial), 100)
        self.assertEqual(confirmation, [])
        self.assertEqual(initial_calls, 1, calls)
        self.assertEqual(len(calls) - initial_calls, 1, calls)

    def test_vo7_consented_install_uses_two_check_ignore_calls(self):
        import contextlib
        import io
        from unittest import mock

        module = load_installer_module()
        repo = self.ignored_bin_repo()
        calls = []
        original = module.run_git

        def recording(target, args, stdin=None):
            if "check-ignore" in args:
                calls.append(list(args))
            return original(target, args, stdin)

        output = io.StringIO()
        with mock.patch.object(module, "run_git", recording), \
                mock.patch("sys.stdin", io.StringIO("y\n")), \
                contextlib.redirect_stdout(output):
            code = module.main(["install", str(repo)])
        self.assertEqual(code, 0, output.getvalue())
        self.assertEqual(len(calls), 2, calls)
        self.assertFalse(self.ignored(repo, self.GUARDED_BIN[0]))

    # ---- Spec 43566c0a9bdc1f1f v1 ----
    DRY_CONFLICT = "ignored harness paths: .gitignore exceptions require consent (dry-run)"
    PLANNED = "planned .gitignore exception: "

    def dry_run_in_process(self, command, repo):
        import contextlib
        import io
        from unittest import mock

        module = load_installer_module()
        stdin = io.StringIO("y\ny\ny\n")
        output = io.StringIO()
        with mock.patch("sys.stdin", stdin), contextlib.redirect_stdout(output):
            code = module.main([command, str(repo), "--dry-run"])
        return code, output.getvalue(), stdin.tell()

    def set_version(self, repo, version):
        path = repo / ".harness" / "manifest.json"
        data = json.loads(path.read_text())
        data["version"] = version
        path.write_text(json.dumps(data, indent=2) + "\n")

    def assert_dry_ignored_row(self, command):
        repo = self.make_repo()
        if command == "update":
            self.assertEqual(run_installer("install", str(repo)).returncode, 0)
            self.set_version(repo, "0.15.0")
        (repo / ".gitignore").write_text("bin/\n")
        before = self.snapshot(repo)
        code, out, consumed = self.dry_run_in_process(command, repo)
        self.assertEqual(code, 1, out)
        self.assertIn("== conflict ==", out)
        conflict = out.split("== conflict ==", 1)[1].split("\n== ", 1)[0]
        self.assertIn(self.DRY_CONFLICT, conflict)
        for path in self.GUARDED_BIN:
            self.assertIn(f"{path} is ignored by git", out)
        self.assertIn("warning: ", out)
        planned = [l for l in out.splitlines() if l.startswith(self.PLANNED)]
        self.assertEqual(len(planned), 2 + len(self.GUARDED_BIN), out)
        self.assertIn(self.PLANNED + "!/.harness/bin/", out)
        self.assertIn(".harness/manifest.json", out)
        write = out.split("== write ==\n", 1)[1].split("\n== ", 1)[0]
        self.assertIn("- .harness/VERSION", write.splitlines())
        self.assertIn("- .harness/config.default.json", write.splitlines())
        merge = out.split("== merge ==\n", 1)[1].split("\n== ", 1)[0]
        self.assertIn("- AGENTS.md", write.splitlines() + merge.splitlines())
        if command == "update":
            self.assertIn("migration 0.15.1", out)
        self.assertNotIn(self.QUESTION, out)
        self.assertNotIn("execution requires consent to update .gitignore", out)
        self.assertEqual(consumed, 0, "dry-run must not read stdin")
        self.assertEqual(self.snapshot(repo), before)

    def assert_dry_clear_row(self, command, repo):
        before = self.snapshot(repo)
        code, out, consumed = self.dry_run_in_process(command, repo)
        self.assertEqual(code, 0, out)
        for needle in (self.PLANNED, self.DRY_CONFLICT, " is ignored by git", "execution requires consent", self.QUESTION):
            self.assertNotIn(needle, out)
        self.assertEqual(consumed, 0)
        self.assertEqual(self.snapshot(repo), before)

    # R2 VO1 decision table (F1,F2,Q3 / C1-C4): 5 rules
    def test_r2vo1_install_ignored_dry_run_fails_with_full_plan(self):
        self.assert_dry_ignored_row("install")

    def test_r2vo1_update_ignored_dry_run_fails_with_migration_and_plan(self):
        self.assert_dry_ignored_row("update")

    def test_r2vo1_install_clear_dry_run_exits_zero(self):
        self.assert_dry_clear_row("install", self.make_repo())

    def test_r2vo1_update_clear_dry_run_exits_zero(self):
        repo = self.make_repo()
        self.assertEqual(run_installer("install", str(repo)).returncode, 0)
        self.assert_dry_clear_row("update", repo)

    def test_r2vo1_prior_exceptions_clear_dry_run_exits_zero(self):
        repo = self.ignored_bin_repo()
        first = run_installer("install", str(repo), input="y\ny\n")
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        self.assert_dry_clear_row("update", repo)

    # R2 VO2 classification tree (F3,Q1,Q2,Q4 / C5-C7)
    def reference_dirs_and_paths(self):
        ref = self.make_repo()
        self.assertEqual(run_installer("install", str(ref)).returncode, 0)
        manifest = json.loads((ref / ".harness" / "manifest.json").read_text())
        paths = sorted(set(manifest["files"]) | set(self.MANAGED_PATHS))
        dirs = set()
        for path in paths:
            parts = path.split("/")[:-1]
            for i in range(1, len(parts) + 1):
                dirs.add("/".join(parts[:i]))
        return sorted(dirs), paths

    def consenting_install_checked(self, repo):
        dirs, _ = self.reference_dirs_and_paths()
        expected = {d for d in dirs if self.ignored(repo, d + "/")}
        result = run_installer("install", str(repo), input="y\ny\n")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        text = (repo / ".gitignore").read_text()
        lines = text.splitlines()
        negations = {l[2:-1] for l in lines if l.startswith("!/") and l.endswith("/")}
        stars = {l[1:-2] for l in lines if l.startswith("/") and l.endswith("/*")}
        self.assertEqual(negations, expected, text)
        self.assertEqual(stars, expected, text)
        manifest = json.loads((repo / ".harness" / "manifest.json").read_text())
        for path in sorted(set(manifest["files"]) | set(self.MANAGED_PATHS)):
            self.assertFalse(self.ignored(repo, path), path)
        return expected, lines

    def test_r2vo2_parent_not_ignored_gets_no_parent_lines(self):
        repo = self.ignored_bin_repo()
        expected, lines = self.consenting_install_checked(repo)
        self.assertIn(".harness/bin", expected)
        self.assertIn("!/.harness/bin/", lines)
        self.assertIn("/.harness/bin/*", lines)
        self.assertNotIn(".harness", expected)
        self.assertNotIn("!/.harness/", lines)
        self.assertNotIn("/.harness/*", lines)
        for directory in (".claude", ".codex", ".agents", "agent-docs"):
            self.assertNotIn(f"!/{directory}/", lines)

    def test_r2vo2_parent_ignored_in_root_gitignore_and_unrelated_stays_ignored(self):
        repo = self.make_repo()
        (repo / ".gitignore").write_text(".harness/\n")
        expected, lines = self.consenting_install_checked(repo)
        self.assertIn(".harness", expected)
        self.assertIn("!/.harness/", lines)
        self.assertIn("/.harness/*", lines)
        self.assertNotIn("!/.claude/", lines)
        (repo / ".harness" / "unrelated.txt").write_text("x\n")
        self.assertTrue(self.ignored(repo, ".harness/unrelated.txt"))

    def test_r2vo2_parent_ignored_via_info_exclude_creates_root_gitignore(self):
        repo = self.make_repo()
        (repo / ".git" / "info" / "exclude").write_text(".claude/\n")
        self.assertFalse((repo / ".gitignore").exists())
        expected, lines = self.consenting_install_checked(repo)
        self.assertTrue((repo / ".gitignore").exists())
        self.assertIn(".claude", expected)
        self.assertIn("!/.claude/", lines)
        self.assertIn("/.claude/*", lines)
        self.assertNotIn("!/.harness/", lines)
        self.assertNotIn("!/.codex/", lines)

    # R2 VO3 state transition (F4,Q5 / C8)
    def test_r2vo3_update_from_0150_announces_0151_only_and_records_it(self):
        repo = self.make_repo()
        self.assertEqual(run_installer("install", str(repo)).returncode, 0)
        self.set_version(repo, "0.15.0")
        refused = run_installer("update", str(repo), input="")
        self.assertEqual(refused.returncode, 1, refused.stdout + refused.stderr)
        self.assertEqual(json.loads((repo / ".harness" / "manifest.json").read_text())["version"], "0.15.0")
        result = run_installer("update", str(repo), input="y\ny\ny\ny\n")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("migration 0.15.1:", result.stdout)
        self.assertNotIn("migration 0.15.0:", result.stdout)
        self.assertEqual(json.loads((repo / ".harness" / "manifest.json").read_text())["version"], "0.17.0")

    def test_r2vo3_update_from_0140_announces_0150_then_0151_with_separate_confirmations(self):
        repo = self.make_repo()
        self.assertEqual(run_installer("install", str(repo)).returncode, 0)
        self.set_version(repo, "0.14.0")
        one = run_installer("update", str(repo), input="y\ny\ny\n")
        self.assertEqual(one.returncode, 1, one.stdout + one.stderr)
        self.assertIn("migration 0.15.0:", one.stdout)
        self.assertNotEqual(json.loads((repo / ".harness" / "manifest.json").read_text())["version"], "0.17.0")
        self.set_version(repo, "0.14.0")
        result = run_installer("update", str(repo), input="y\ny\ny\ny\ny\n")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        out = result.stdout
        self.assertIn("migration 0.15.0:", out)
        self.assertIn("migration 0.15.1:", out)
        self.assertLess(out.index("migration 0.15.0:"), out.index("migration 0.15.1:"))
        self.assertNotIn("migration 0.14.0:", out)
        self.assertEqual(json.loads((repo / ".harness" / "manifest.json").read_text())["version"], "0.17.0")


class TestRequirementsMigration(InstallerTestCase):
    def legacy_repo(self):
        repo = self.install()
        manifest_path = repo / ".harness" / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["version"] = "0.16.1"
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
        return repo

    def test_absent_directory_succeeds_without_confirmation(self):
        repo = self.legacy_repo()
        result = run_installer("update", str(repo), input="y\n")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse((repo / "agent-docs" / "requirements").exists())
        self.assertEqual(re.findall(r"^migration (\d+\.\d+\.\d+):", result.stdout, re.MULTILINE), ["0.16.2", "0.17.0"])
        self.assertEqual(json.loads((repo / ".harness" / "manifest.json").read_text())["version"], "0.17.0")
        self.assertEqual(re.findall(r"Apply migration (\S+)", result.stdout), ["0.17.0"])

    def test_empty_directory_is_removed_and_dry_run_preserves_it(self):
        repo = self.legacy_repo()
        directory = repo / "agent-docs" / "requirements"
        directory.mkdir()
        before = self.snapshot(repo)
        result = run_installer("update", str(repo), "--dry-run", forbid_input=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(directory.is_dir())
        self.assertEqual(before, self.snapshot(repo))
        result = run_installer("update", str(repo), input="y\n")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse(directory.exists())

    def test_default_scaffolding_is_removed_without_confirmation(self):
        repo = self.legacy_repo()
        directory = repo / "agent-docs" / "requirements"
        (directory / "stale").mkdir(parents=True)
        (directory / "index.md").write_text("")
        (directory / "stale.md").write_text("# Stale Index Archive\n<!-- harness:stale-index-archive -->\n\n")
        (directory / "stale" / ".gitkeep").write_text("")
        result = run_installer("update", str(repo), input="y\n")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse(directory.exists())
        self.assertEqual(re.findall(r"Apply migration (\S+)", result.stdout), ["0.17.0"])

    def test_content_fails_without_changes_and_guides_manual_backup(self):
        for relative in ("index.md", "stale/0123456789abcdef-old.md"):
            for dry_run in (False, True):
                with self.subTest(relative=relative, dry_run=dry_run):
                    repo = self.legacy_repo()
                    path = repo / "agent-docs" / "requirements" / relative
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text("legacy content\n")
                    before = self.snapshot(repo)
                    result = run_installer("update", str(repo), *(["--dry-run"] if dry_run else []))
                    self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                    self.assertIn("back up its contents", result.stdout)
                    self.assertIn("delete agent-docs/requirements, then retry", result.stdout)
                    self.assertEqual(before, self.snapshot(repo))


class TestGpt61SolDefaults(InstallerTestCase):
    ROLES = ("implementer", "test-implementer", "test-verifier")

    def set_legacy_version(self, repo):
        manifest_path = repo / ".harness" / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["version"] = "0.15.1"
        for role in self.ROLES:
            relative = f".codex/agents/{role}.toml"
            path = repo / relative
            previous = path.read_text().replace('model = "gpt-6.1-sol"', 'model = "gpt-6-sol"')
            self.assertNotEqual(previous, path.read_text(), role)
            path.write_text(previous)
            manifest["files"][relative] = hashlib.sha256(path.read_bytes()).hexdigest()
        relative = ".codex/agents/code-explorer.toml"
        path = repo / relative
        path.write_text(path.read_text().replace('model = "gpt-6.1-sol"\n', ''))
        manifest["files"][relative] = hashlib.sha256(path.read_bytes()).hexdigest()
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")

    def assert_codex_role_defaults(self, repo):
        for role in self.ROLES:
            with self.subTest(role=role):
                path = repo / ".codex" / "agents" / f"{role}.toml"
                config = tomllib.loads(path.read_text())
                self.assertEqual(config["model"], "gpt-6.1-sol")
                self.assertEqual(config["model_reasoning_effort"], "medium")
        explorer = tomllib.loads((repo / ".codex/agents/code-explorer.toml").read_text())
        self.assertEqual(explorer["model"], "gpt-6.1-sol")
        self.assertNotIn("model_reasoning_effort", explorer)

    def test_v1_install_all_three_generated_codex_roles(self):
        repo = self.install()
        self.assert_codex_role_defaults(repo)

    def test_v1_update_all_three_generated_codex_roles(self):
        repo = self.install()
        self.set_legacy_version(repo)
        result = run_installer("update", str(repo), input="y\ny\ny\n")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assert_codex_role_defaults(repo)

    def test_v2_approved_legacy_update_announces_ordered_model_migrations(self):
        repo = self.install()
        self.set_legacy_version(repo)
        result = run_installer("update", str(repo), input="y\ny\ny\n")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(re.findall(r"^migration (\d+\.\d+\.\d+):", result.stdout, re.MULTILINE), ["0.16.0", "0.16.1", "0.16.2", "0.17.0"])
        self.assertEqual(json.loads((repo / ".harness" / "manifest.json").read_text())["version"], "0.17.0")

    def test_v2_declined_legacy_update_announces_migration_and_writes_nothing(self):
        repo = self.install()
        self.set_legacy_version(repo)
        before = self.snapshot(repo)
        result = run_installer("update", str(repo), input="n\n")
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertEqual(re.findall(r"^migration (\d+\.\d+\.\d+):", result.stdout, re.MULTILINE), ["0.16.0", "0.16.1", "0.16.2", "0.17.0"])
        self.assertEqual(self.snapshot(repo), before)

    def test_v2_legacy_dry_run_announces_migration_and_writes_nothing(self):
        repo = self.install()
        self.set_legacy_version(repo)
        before = self.snapshot(repo)
        result = run_installer("update", str(repo), "--dry-run", input="")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(re.findall(r"^migration (\d+\.\d+\.\d+):", result.stdout, re.MULTILINE), ["0.16.0", "0.16.1", "0.16.2", "0.17.0"])
        self.assertEqual(self.snapshot(repo), before)

    def test_v2_current_version_repeat_is_stable_without_migration(self):
        repo = self.install()
        before = self.snapshot(repo)
        result = run_installer("update", str(repo), input="")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotRegex(result.stdout, r"(?m)^migration ")
        self.assertEqual(self.snapshot(repo), before)

    def test_v3_workflow_claude_defaults_and_explorer_model(self):
        repo = self.install()
        for role in self.ROLES:
            with self.subTest(role=role):
                claude_frontmatter = (repo / ".claude" / "agents" / f"{role}.md").read_text().split("---", 2)[1]
                self.assertRegex(claude_frontmatter, r"(?m)^model: sonnet$")
                self.assertRegex(claude_frontmatter, r"(?m)^effort: medium$")
                payload = (repo / ".harness" / "agents" / f"{role}.md").read_text().split("---", 2)[1]
                self.assertRegex(payload, r"(?m)^claude\.model: sonnet$")
                self.assertRegex(payload, r"(?m)^claude\.effort: medium$")
        explorer_payload = (repo / ".harness" / "agents" / "code-explorer.md").read_text().split("---", 2)[1]
        self.assertRegex(explorer_payload, r"(?m)^codex\.model: gpt-6\.1-sol$")
        explorer_config = tomllib.loads((repo / ".codex" / "agents" / "code-explorer.toml").read_text())
        self.assertEqual(explorer_config["model"], "gpt-6.1-sol")
        self.assertNotIn("model_reasoning_effort", explorer_config)
        self.assertEqual(explorer_config["sandbox_mode"], "read-only")


class TestMutationAndFuzzing(InstallerTestCase):
    def test_workflow_declares_hand_mutations_fuzzing_and_mutation_tool(self):
        repo = self.install()
        workflow = (repo / ".agents/skills/workflow-approach/SKILL.md").read_text()
        self.assertIn("8–10 strongest distinct defect classes", workflow)
        self.assertNotIn("2–3", workflow)
        self.assertIn("\nFuzzing: <", workflow)
        self.assertIn("\nMutation tool: <", workflow)
        self.assertIn("mutant-triager", workflow)
        self.assertIn("workflow_marker.py verification --run-id ID", workflow)

    def test_mutant_triager_is_rendered_with_read_only_tool(self):
        repo = self.install()
        claude = (repo / ".claude/agents/mutant-triager.md").read_text()
        self.assertIn("\nmodel: haiku\n", claude)
        self.assertIn("\ntools: Read\n", claude)
        self.assertIn("survival threshold (default 40%)", (repo / ".agents/skills/workflow-approach/SKILL.md").read_text())
        codex = tomllib.loads((repo / ".codex/agents/mutant-triager.toml").read_text())
        self.assertEqual((codex["model"], codex["model_reasoning_effort"], codex["sandbox_mode"]),
                         ("gpt-6.1-luna", "low", "read-only"))

    def test_update_from_0162_announces_mutation_migration(self):
        repo = self.install()
        manifest_path = repo / ".harness" / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["version"] = "0.16.2"
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
        result = run_installer("update", str(repo), input="y\n")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("0.17.0", result.stdout)
        self.assertIn("declare Fuzzing and Mutation tool", result.stdout)


if __name__ == "__main__":
    unittest.main()

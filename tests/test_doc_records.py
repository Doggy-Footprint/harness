import json
import re
import subprocess
import sys
from pathlib import Path

from test_installer import InstallerTestCase, run_git, run_installer

SPEC_NAME = "0123456789abcdef-sample.md"
SPEC_TEXT = """---
version: 1
run_id: 0123456789abcdef
status: active
---

# Version Log
## v1
- Initial.

# Retrospective
"""
RETRO_ROW = "## 2026-10-25\n| observation | evidence | how to re-check |\n| --- | --- | --- |\n| port 8080 is taken by a fixture | bind error in test log | run `lsof -i :8080` |\n"


class DocRecordsTestCase(InstallerTestCase):
    def installed(self, *args):
        repo = self.make_repo()
        result = run_installer("install", str(repo), "--no-ci", *args)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return repo, result

    def commit_all(self, repo, message="base"):
        run_git(repo, "add", "-A")
        return subprocess.run(
            ["git", "-C", str(repo), "commit", "-q", "-m", message], capture_output=True, text=True
        )

    def head(self, repo):
        return run_git(repo, "rev-parse", "HEAD").stdout.strip()

    def run_doc_hook(self, repo, file_path, tool="Write"):
        payload = {"hook_event_name": "PostToolUse", "tool_name": tool, "cwd": str(repo),
                   "tool_input": {"file_path": str(file_path)}}
        return subprocess.run(
            [sys.executable, str(repo / ".harness" / "hooks" / "doc_commit.py")],
            input=json.dumps(payload), capture_output=True, text=True,
        )


class TestCommitStamp(DocRecordsTestCase):
    def test_new_document_gets_frontmatter_with_head(self):
        repo, _ = self.installed()
        self.assertEqual(self.commit_all(repo).returncode, 0)
        doc = repo / "agent-docs" / "try-n-fail" / "1111111111111111-task.md"
        doc.write_text("# Task\n")
        self.assertEqual(self.run_doc_hook(repo, doc).returncode, 0)
        self.assertEqual(doc.read_text(), f"---\ncommit: {self.head(repo)}\n---\n\n# Task\n")

    def test_existing_frontmatter_gains_or_replaces_commit_only(self):
        repo, _ = self.installed()
        self.assertEqual(self.commit_all(repo).returncode, 0)
        spec = repo / "agent-docs" / "specs" / SPEC_NAME
        spec.parent.mkdir(parents=True, exist_ok=True)
        spec.write_text("---\nversion: 1\n---\n\n# Body\n")
        self.run_doc_hook(repo, spec, tool="Edit")
        head = self.head(repo)
        self.assertEqual(spec.read_text(), f"---\nversion: 1\ncommit: {head}\n---\n\n# Body\n")
        spec.write_text("---\ncommit: deadbeef\nversion: 2\n---\n\n# Body\n")
        self.run_doc_hook(repo, spec, tool="Edit")
        self.assertEqual(spec.read_text(), f"---\ncommit: {head}\nversion: 2\n---\n\n# Body\n")

    def test_unstamped_paths_are_left_alone(self):
        repo, _ = self.installed()
        self.assertEqual(self.commit_all(repo).returncode, 0)
        index = repo / "agent-docs" / "try-n-fail" / "index.md"
        stale = repo / "agent-docs" / "try-n-fail" / "stale.md"
        outside = repo / "notes.md"
        text_file = repo / "agent-docs" / "try-n-fail" / "data.txt"
        for path in (outside, text_file):
            path.write_text("# X\n")
        before = {path: path.read_text() for path in (index, stale, outside, text_file)}
        for path in before:
            self.run_doc_hook(repo, path)
        self.assertEqual({path: path.read_text() for path in before}, before)

    def test_o10_signatures_progress_directory_is_skipped_by_doc_commit(self):
        repo, _ = self.installed()
        self.assertEqual(self.commit_all(repo).returncode, 0)
        progress = repo / "agent-docs" / "progress" / "1111111111111111-task.md"
        progress.parent.mkdir(parents=True, exist_ok=True)
        progress.write_text("---\nsession: S1\n---\n\n# Task\n")
        before = progress.read_bytes()

        self.assertEqual(self.run_doc_hook(repo, progress).returncode, 0)

        self.assertEqual(progress.read_bytes(), before)

    def test_repository_without_commits_is_left_alone(self):
        repo, _ = self.installed()
        doc = repo / "agent-docs" / "try-n-fail" / "1111111111111111-task.md"
        doc.write_text("# Task\n")
        self.assertEqual(self.run_doc_hook(repo, doc).returncode, 0)
        self.assertEqual(doc.read_text(), "# Task\n")

    def test_claude_settings_register_the_hook_for_file_edits(self):
        repo, _ = self.installed()
        settings = json.loads((repo / ".claude" / "settings.json").read_text())
        groups = [g for g in settings["hooks"]["PostToolUse"] if "doc_commit.py" in g["hooks"][0]["command"]]
        self.assertEqual([g["matcher"] for g in groups], ["Write|Edit|MultiEdit"])


class TestRetrospectiveWarning(DocRecordsTestCase):
    WARNING = "without a new # Retrospective entry"

    def setup_spec(self):
        repo, _ = self.installed()
        spec = repo / "agent-docs" / "specs" / SPEC_NAME
        spec.parent.mkdir(parents=True, exist_ok=True)
        spec.write_text(SPEC_TEXT)
        result = self.commit_all(repo)
        self.assertIn(self.WARNING, result.stderr)
        self.assertEqual(result.returncode, 0, result.stderr)
        return repo, spec

    def test_spec_change_without_new_row_warns_but_commits(self):
        repo, spec = self.setup_spec()
        spec.write_text(SPEC_TEXT.replace("- Initial.", "- Initial.\n- Changed."))
        result = self.commit_all(repo, "change")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(f"agent-docs/specs/{SPEC_NAME} changed{' ' + self.WARNING}", result.stderr)

    def test_spec_change_with_new_row_does_not_warn(self):
        repo, spec = self.setup_spec()
        spec.write_text(SPEC_TEXT + RETRO_ROW)
        result = self.commit_all(repo, "retro")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn(self.WARNING, result.stderr)

    def test_archive_rename_compares_against_the_active_spec(self):
        repo, spec = self.setup_spec()
        archived = repo / "agent-docs" / "spec-logs" / SPEC_NAME
        archived.parent.mkdir(parents=True, exist_ok=True)
        spec.rename(archived)
        result = self.commit_all(repo, "archive")
        self.assertIn(f"agent-docs/spec-logs/{SPEC_NAME}", result.stderr)
        archived.write_text(SPEC_TEXT + RETRO_ROW)
        result = self.commit_all(repo, "archive retro")
        self.assertNotIn(self.WARNING, result.stderr)

    def test_other_documents_do_not_warn(self):
        repo, _ = self.installed()
        (repo / "a.txt").write_text("x\n")
        result = self.commit_all(repo)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn(self.WARNING, result.stderr)


class TestRecordRules(DocRecordsTestCase):
    def test_retired_record_dirs_are_not_checked(self):
        repo, _ = self.installed()
        for name in ("adr", "rejections"):
            directory = repo / "agent-docs" / name
            directory.mkdir(parents=True, exist_ok=True)
            (directory / "0123456789abcdef-x.md").write_text("# X\n")
        result = self.run_verify_rules(repo)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_try_n_fail_record_requires_its_headings(self):
        repo, _ = self.installed()
        directory = repo / "agent-docs" / "try-n-fail"
        name = "0123456789abcdef-cache-warmup.md"
        (directory / name).write_text("# Cache warmup\n\n## Goal\nx\n")
        (directory / "index.md").write_text(
            f"File: {name}\nSummary: s\nRelated Files: none\nRelated Symbols: none\n"
        )
        result = self.run_verify_rules(repo)
        self.assertEqual(result.returncode, 1)
        self.assertIn("'## Attempts', '## Revisit Condition'", result.stderr)
        (directory / name).write_text("# Cache warmup\n\n## Goal\nx\n\n## Attempts\n| a | b | c |\n\n## Revisit Condition\ny\n")
        result = self.run_verify_rules(repo)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


class TestAgentModel(DocRecordsTestCase):
    SELECTABLE = ("code-explorer", "implementer", "test-implementer", "test-verifier")

    def models(self, repo):
        values = {}
        for path in (repo / ".claude" / "agents").glob("*.md"):
            line = next(line for line in path.read_text().splitlines() if line.startswith("model: "))
            values[path.stem] = line.split(": ", 1)[1]
        return values

    def test_default_install_uses_sonnet_and_writes_no_config(self):
        repo, result = self.installed()
        models = self.models(repo)
        self.assertEqual({models[name] for name in self.SELECTABLE}, {"sonnet"})
        self.assertEqual(models["mutant-triager"], "haiku")
        self.assertFalse((repo / ".harness" / "config.json").exists())
        self.assertIn("workflow subagent model: sonnet", result.stdout)

    def test_model_choice_is_stored_and_kept_by_update(self):
        repo, _ = self.installed("--model", "opus")
        self.assertEqual(json.loads((repo / ".harness" / "config.json").read_text()), {"agent_model": "opus"})
        self.assertEqual({self.models(repo)[name] for name in self.SELECTABLE}, {"opus"})
        self.assertEqual(self.models(repo)["mutant-triager"], "haiku")

        update = run_installer("update", str(repo), "--no-ci")
        self.assertEqual(update.returncode, 0, update.stdout + update.stderr)
        self.assertEqual({self.models(repo)[name] for name in self.SELECTABLE}, {"opus"})
        doctor = run_installer("doctor", str(repo))
        self.assertEqual(doctor.returncode, 0, doctor.stdout + doctor.stderr)

        back = run_installer("update", str(repo), "--no-ci", "--model", "sonnet")
        self.assertEqual(back.returncode, 0, back.stdout + back.stderr)
        self.assertEqual({self.models(repo)[name] for name in self.SELECTABLE}, {"sonnet"})
        self.assertEqual(json.loads((repo / ".harness" / "config.json").read_text()), {"agent_model": "sonnet"})

    def test_model_flag_is_rejected_outside_install_and_update(self):
        repo, _ = self.installed()
        result = run_installer("doctor", str(repo), "--model", "opus")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("--model is only valid with install or update", result.stderr)


class TestMigration0290(DocRecordsTestCase):
    def test_update_from_0280_keeps_retired_dirs_and_announces_them(self):
        repo, _ = self.installed()
        adr = repo / "agent-docs" / "adr"
        (adr / "stale").mkdir(parents=True)
        record = adr / "0123456789abcdef-x.md"
        record.write_text("# X\n")
        manifest_path = repo / ".harness" / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["version"] = "0.28.0"
        manifest_path.write_text(json.dumps(manifest))

        result = run_installer("update", str(repo), "--no-ci", input="y\ny\ny\ny\ny\n")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("migration 0.29.0:", result.stdout)
        self.assertIn("keep agent-docs/adr/ untouched", result.stdout)
        self.assertNotIn("agent-docs/rejections/", result.stdout)
        self.assertEqual(record.read_text(), "# X\n")
        self.assertEqual(json.loads(manifest_path.read_text())["version"], "0.33.0")
        block = (repo / "AGENTS.md").read_text()
        self.assertIn("## Try-n-Fail Rule", block)
        self.assertNotIn("## Architecture Decision Record Rule", block)
        self.assertIn("## Reporting to the User", block)

    def set_version(self, repo, version):
        manifest_path = repo / ".harness" / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["version"] = version
        manifest_path.write_text(json.dumps(manifest))

    def handoffs(self, repo):
        return sorted((repo / "agent-docs" / "handoff").rglob("*-adr-rejection-to-try-n-fail.md"))

    def test_update_with_retired_records_leaves_one_indexed_handoff(self):
        repo, _ = self.installed()
        self.assertEqual(self.commit_all(repo).returncode, 0)
        rejections = repo / "agent-docs" / "rejections"
        (rejections / "stale").mkdir(parents=True)
        (rejections / "0123456789abcdef-x.md").write_text("# X\n")
        (rejections / "stale" / "fedcba9876543210-y.md").write_text("# Y\n")
        self.set_version(repo, "0.28.0")

        dry = run_installer("update", str(repo), "--no-ci", "--dry-run")
        self.assertIn("record(s) to try-n-fail", dry.stdout)
        self.assertEqual(self.handoffs(repo), [])

        result = run_installer("update", str(repo), "--no-ci", input="y\ny\ny\ny\ny\nn\n")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        [handoff] = self.handoffs(repo)
        text = handoff.read_text()
        self.assertTrue(text.startswith(f"---\ncommit: {self.head(repo)}\n---\n"))
        self.assertIn("- `agent-docs/rejections/0123456789abcdef-x.md`", text)
        self.assertIn("- `agent-docs/rejections/stale/fedcba9876543210-y.md`", text)
        self.assertIn(f"File: {handoff.name}", (handoff.parent / "index.md").read_text())
        verify = self.run_verify_rules(repo)
        self.assertEqual(verify.returncode, 0, verify.stdout + verify.stderr)

        self.set_version(repo, "0.28.0")
        again = run_installer("update", str(repo), "--no-ci", input="y\ny\ny\ny\ny\nn\n")
        self.assertEqual(again.returncode, 0, again.stdout + again.stderr)
        self.assertEqual(len(self.handoffs(repo)), 1)

    def test_update_without_retired_records_writes_no_handoff(self):
        repo, _ = self.installed()
        (repo / "agent-docs" / "adr").mkdir(parents=True)
        self.set_version(repo, "0.28.0")
        result = run_installer("update", str(repo), "--no-ci", input="y\ny\ny\ny\ny\n")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.handoffs(repo), [])


PROGRESS_NAME = "0123456789abcdef-sample-task.md"
PROGRESS_TEMPLATE = """---
session: S1
before: none
previous: none
branch: main
commit: abcdef0123456789abcdef0123456789abcdef01
---

# Sample task

## Next Session

### State
- the parser is half done
  - commit: abcdef0123456789abcdef0123456789abcdef01; files: src/parser.py

### Next Step
- finish the tokenizer
  - commit: abcdef0123456789abcdef0123456789abcdef01; files: none

### Constraints
- "do not touch the api"
  - source: user request 1

### Verify
- run the parser tests
  - commit: abcdef0123456789abcdef0123456789abcdef01; files: none

### Dead Ends
- regex tokenizer was too slow
  - commit: abcdef0123456789abcdef0123456789abcdef01; files: none

### Related
- agent-docs/try-n-fail/index.md
  - commit: abcdef0123456789abcdef0123456789abcdef01; files: none

## Record

### Changes
- edited the parser

### Commands
- ran the tests

### Failed Attempts
| attempt | failure evidence | cause |
| --- | --- | --- |

### Sources
- none

### User Requests
"""
TODO_INDEX_BLOCK = "File: {name}\nSummary: s\nRelated Files: none\nRelated Symbols: none\n"


class ProgressRecordTestCase(DocRecordsTestCase):
    def progress_dir(self, repo):
        directory = repo / "agent-docs" / "progress"
        directory.mkdir(parents=True, exist_ok=True)
        return directory

    def logs_dir(self, repo):
        directory = repo / "agent-docs" / "progress-logs"
        directory.mkdir(parents=True, exist_ok=True)
        return directory

    def verify(self, repo):
        result = self.run_verify_rules(repo)
        return result, result.stdout + result.stderr


class TestProgressRecordRules(ProgressRecordTestCase):
    def test_o8_baseline_valid_progress_passes(self):
        repo, _ = self.installed()
        (self.progress_dir(repo) / PROGRESS_NAME).write_text(PROGRESS_TEMPLATE)
        result, output = self.verify(repo)
        self.assertEqual(result.returncode, 0, output)

    def test_o8_c19_two_progress_files_fail(self):
        repo, _ = self.installed()
        directory = self.progress_dir(repo)
        (directory / PROGRESS_NAME).write_text(PROGRESS_TEMPLATE)
        (directory / "fedcba9876543210-other-task.md").write_text(PROGRESS_TEMPLATE)
        result, output = self.verify(repo)
        self.assertEqual(result.returncode, 1, output)
        self.assertIn("progress", output)

    def test_o8_fr16_each_missing_required_heading_fails(self):
        headings = ("## Next Session", "### State", "### Next Step", "### Constraints", "### Verify",
                    "### Dead Ends", "### Related", "## Record", "### Changes", "### Commands",
                    "### Failed Attempts", "### Sources", "### User Requests")
        for heading in headings:
            with self.subTest(missing=heading):
                repo, _ = self.installed()
                text = PROGRESS_TEMPLATE.replace(f"\n{heading}\n", "\n", 1)
                self.assertNotEqual(text, PROGRESS_TEMPLATE)
                (self.progress_dir(repo) / PROGRESS_NAME).write_text(text)
                result, output = self.verify(repo)
                self.assertEqual(result.returncode, 1, output)

    def test_o8_fr16_missing_title_fails(self):
        repo, _ = self.installed()
        (self.progress_dir(repo) / PROGRESS_NAME).write_text(PROGRESS_TEMPLATE.replace("# Sample task\n", ""))
        result, output = self.verify(repo)
        self.assertEqual(result.returncode, 1, output)

    def test_o8_fr16_bad_metadata_lines_fail(self):
        good = "  - commit: abcdef0123456789abcdef0123456789abcdef01; files: src/parser.py"
        cases = {
            "entry without metadata line": ("- the parser is half done\n" + good + "\n", "- the parser is half done\n"),
            "commit too short": (good, "  - commit: abc12; files: src/parser.py"),
            "commit not hex": (good, "  - commit: zzzzzzzzzz; files: src/parser.py"),
            "missing files field": (good, "  - commit: abcdef0123456789abcdef0123456789abcdef01"),
            "garbage metadata": (good, "  - whatever: nothing"),
            "constraint without source": ("  - source: user request 1", "  - commit: abcdef0123456789abcdef0123456789abcdef01; files: none"),
        }
        for label, (old, new) in cases.items():
            with self.subTest(case=label):
                repo, _ = self.installed()
                text = PROGRESS_TEMPLATE.replace(old, new, 1)
                self.assertNotEqual(text, PROGRESS_TEMPLATE)
                (self.progress_dir(repo) / PROGRESS_NAME).write_text(text)
                result, output = self.verify(repo)
                self.assertEqual(result.returncode, 1, output)

    def test_o8_fr16_progress_logs_skip_format_checks(self):
        repo, _ = self.installed()
        directory = self.logs_dir(repo)
        (directory / PROGRESS_NAME).write_text("garbage without headings or frontmatter\n")
        (directory / "fedcba9876543210-two.md").write_text(PROGRESS_TEMPLATE.replace("## Record", "## Recordx"))
        result, output = self.verify(repo)
        self.assertEqual(result.returncode, 0, output)

    def test_o8_fr16_progress_directories_need_no_index_files(self):
        repo, _ = self.installed()
        (self.progress_dir(repo) / PROGRESS_NAME).write_text(PROGRESS_TEMPLATE)
        (self.logs_dir(repo) / "fedcba9876543210-old.md").write_text(PROGRESS_TEMPLATE)
        for name in ("progress", "progress-logs"):
            for leftover in ("index.md", "stale.md", "stale"):
                self.assertFalse((repo / "agent-docs" / name / leftover).exists())
        result, output = self.verify(repo)
        self.assertEqual(result.returncode, 0, output)

    def todo(self, repo, text, name="1111111111111111-legacy.md", indexed=True):
        directory = repo / "agent-docs" / "todos"
        (directory / name).write_text(text)
        if indexed:
            (directory / "index.md").write_text(TODO_INDEX_BLOCK.format(name=name))
        return directory / name

    def test_o8_fr20_todos_accepts_legacy_handoff_record(self):
        repo, _ = self.installed()
        legacy = (
            "# Resume parser work\n\n## User Query\nfix it\n\n## State\nbranch x\n\n"
            "## Failed Attempts\n| attempt | failure evidence | cause |\n\n## Next Step\nfinish\n\n"
            "## Open Questions\nnone\n\n## Spec\nnone\n\n## Execution Ledger\nnone\n"
        )
        self.todo(repo, legacy)
        result, output = self.verify(repo)
        self.assertEqual(result.returncode, 0, output)

    def test_o8_fr16_todos_accepts_extra_sections_and_requires_only_title_and_next_step(self):
        repo, _ = self.installed()
        self.todo(repo, "# Todo\n\n## Next Step\ndo it\n\n## Whatever Else\nx\n\n### Deep\ny\n")
        result, output = self.verify(repo)
        self.assertEqual(result.returncode, 0, output)
        self.todo(repo, "# Todo\n\n## Next Step\ndo it\n")
        result, output = self.verify(repo)
        self.assertEqual(result.returncode, 0, output)

    def test_o8_fr16_todos_without_next_step_or_title_fails(self):
        for label, text in (
            ("no next step", "# Todo\n\n## Goal\ng\n"),
            ("no title", "## Next Step\ndo it\n"),
        ):
            with self.subTest(case=label):
                repo, _ = self.installed()
                self.todo(repo, text)
                result, output = self.verify(repo)
                self.assertEqual(result.returncode, 1, output)

    def test_o8_fr16_todos_is_a_managed_directory_requiring_an_index_entry(self):
        repo, _ = self.installed()
        self.todo(repo, "# Todo\n\n## Next Step\ndo it\n", indexed=False)
        result, output = self.verify(repo)
        self.assertEqual(result.returncode, 1, output)

    def test_o8_fr16_handoff_directory_is_not_checked(self):
        repo, _ = self.installed()
        handoff = repo / "agent-docs" / "handoff"
        handoff.mkdir(parents=True, exist_ok=True)
        (handoff / "1234567890abcdef-x.md").write_text("# X\n\n## Next Stepx\nbad\n")
        (handoff / "not-a-record-name.md").write_text("no heading\n")
        result, output = self.verify(repo)
        self.assertEqual(result.returncode, 0, output)


# category -> samples (Q7/Q8); every sample must be detected
SECRET_SAMPLES = {
    "token": (
        "AKIAIOSFODNN7ABCDEFG",
        "ghp_" + "a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7R8",
        "password=hunter2",
        "sk-ant-api03-abcdefghijklmnopqrstuvwx",
    ),
    "email": ("alice@acme.io", "bob.smith@corp-mail.co"),
    "ip": ("10.0.0.5", "192.168.1.255", "fe80::1"),
    "host": ("build01.corp", "db.prod.internal"),
}
# C28 exceptions and C31 already-masked text; none may be reported
CLEAN_LINES = (
    "dev@example.com",
    "127.0.0.1",
    "::1",
    "task-runner-abcdefghijklmnopqrstuv",
    "version 1.2.3",
    "300.1.1.1",
    "[masked:token] [masked:email] [masked:ip] [masked:host] [masked:log 12 lines]",
    "plain words only",
)


class TestProgressSecretCheck(ProgressRecordTestCase):
    def place(self, repo, location, line_text):
        """Replace the Changes bullet of a valid record with `line_text`; returns (path, line number)."""
        directory = self.progress_dir(repo) if location == "progress" else self.logs_dir(repo)
        lines = PROGRESS_TEMPLATE.splitlines()
        index = lines.index("- edited the parser")
        lines[index] = line_text
        path = directory / PROGRESS_NAME
        path.write_text("\n".join(lines) + "\n")
        return path, index + 1

    def place_at_line(self, repo, line_number, line_text):
        lines = ["filler line"] * (line_number - 1) + [line_text, "tail"]
        path = self.logs_dir(repo) / PROGRESS_NAME
        path.write_text("\n".join(lines) + "\n")
        self.assertEqual(path.read_text().splitlines()[line_number - 1], line_text)
        return path

    def test_o15_q8_every_detected_category_fails_in_both_locations(self):
        for location in ("progress", "progress-logs"):
            for category, samples in SECRET_SAMPLES.items():
                for sample in samples:
                    with self.subTest(location=location, category=category, sample=sample):
                        repo, _ = self.installed()
                        path, line = self.place(repo, location, f"- note: {sample} end")
                        result, output = self.verify(repo)
                        self.assertEqual(result.returncode, 1, output)
                        self.assertIn(f"{path.name}:{line}", output)
                        self.assertIn(f"[masked:{category}]", output)

    def test_o15_c30_akia_key_at_line_40_in_progress_logs_names_line_and_category(self):
        repo, _ = self.installed()
        path = self.place_at_line(repo, 40, "AKIAIOSFODNN7ABCDEFG")
        result, output = self.verify(repo)
        self.assertEqual(result.returncode, 1, output)
        self.assertIn(f"{path.name}:40", output)
        self.assertIn("token", output)

    def test_o15_failure_names_the_actual_line(self):
        repo, _ = self.installed()
        path = self.place_at_line(repo, 57, "contact alice@acme.io")
        result, output = self.verify(repo)
        self.assertEqual(result.returncode, 1, output)
        self.assertIn(f"{path.name}:57", output)
        self.assertNotIn(f"{path.name}:40", output)

    def test_o15_category_none_and_exceptions_pass_in_both_locations(self):
        for location in ("progress", "progress-logs"):
            for line in CLEAN_LINES:
                with self.subTest(location=location, line=line):
                    repo, _ = self.installed()
                    self.place(repo, location, f"- {line}")
                    result, output = self.verify(repo)
                    self.assertEqual(result.returncode, 0, output)

    def test_o15_fr24_log_block_rule_is_not_applied_at_commit_time(self):
        repo, _ = self.installed()
        block = "\n".join(f"2026-10-28 10:00:0{n} INFO step {n}" for n in (1, 2, 3))
        self.place(repo, "progress-logs", block)
        result, output = self.verify(repo)
        self.assertEqual(result.returncode, 0, output)

    def test_o15_only_markdown_files_in_progress_directories_are_scanned(self):
        repo, _ = self.installed()
        (self.logs_dir(repo) / "notes.txt").write_text("AKIAIOSFODNN7ABCDEFG\n")
        result, output = self.verify(repo)
        self.assertEqual(result.returncode, 0, output)


    def test_o16_q3_secret_finding_names_the_file_and_an_action(self):
        verbs = ("write", "merge", "add", "rename", "ask", "re-check", "replace", "end", "remove", "quote", "move", "update", "run", "fix")
        pattern = re.compile(r"(?<![\w-])(" + "|".join(re.escape(v) for v in verbs) + r")(?![\w-])", re.I)
        for location in ("progress", "progress-logs"):
            with self.subTest(location=location):
                repo, _ = self.installed()
                path, _ = self.place(repo, location, "- note: alice@acme.io")
                result, output = self.verify(repo)
                self.assertEqual(result.returncode, 1, output)
                self.assertIn(path.name, output)
                self.assertRegex(output, pattern)

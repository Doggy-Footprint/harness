import hashlib
import json
import re
import tempfile
import unittest
from pathlib import Path

import test_installer

REPO_ROOT = test_installer.REPO_ROOT
SKILL = REPO_ROOT / "harness" / "skills" / "workflow-approach" / "SKILL.md"
VERSION_FILE = REPO_ROOT / "harness" / "VERSION"


def telemetry_section(text):
    found = re.search(r"^# Telemetry[^\n]*\n(.*?)(?=^# |\Z)", text, re.MULTILINE | re.DOTALL)
    return found.group(1) if found else None


class TestTelemetrySectionStatesLiteralMarkerArguments(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.whole = SKILL.read_text(encoding="utf-8")
        cls.section = telemetry_section(cls.whole)

    def test_section_is_found_and_bounded_by_the_next_top_level_heading(self):
        self.assertIsNotNone(self.section)
        self.assertGreater(len(self.section.strip()), 0)
        self.assertLess(len(self.section), len(self.whole))
        self.assertNotRegex(self.section, r"(?m)^# ")

    def test_k1_marker_arguments_are_written_as_literal_values(self):
        self.assertRegex(self.section, r"(?is)marker\s+arguments?\b.{0,160}literal|literal.{0,160}marker\s+arguments?")

    def test_k2_reason_is_that_the_hook_reads_command_text_and_does_not_expand_shell_variables(self):
        for pattern in (r"hook", r"command", r"shell\s+variables?", r"expand"):
            with self.subTest(pattern=pattern):
                self.assertRegex(self.section, rf"(?i){pattern}")
        self.assertRegex(self.section, r"(?is)(not|n't|never|without)\s+(\w+\s+){0,3}expand\w*[^.]{0,80}shell\s+variables?"
                                       r"|shell\s+variables?[^.]{0,80}(not|n't|never)\s+(\w+\s+){0,3}expand")

    def test_k3_a_marker_that_uses_a_variable_is_named_as_not_recorded(self):
        self.assertRegex(self.section, r"(?i)(not|never|n't)\s+(be\s+)?recorded|unrecorded")


def tree_digest(root):
    digests = {}
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if ".git" in relative.parts or "__pycache__" in relative.parts or not path.is_file():
            continue
        digests[str(relative)] = hashlib.sha256(path.read_bytes()).hexdigest()
    return digests


class TestVersionAndMigration(unittest.TestCase):
    def test_version_file_is_0_49_1(self):
        self.assertEqual(VERSION_FILE.read_text(encoding="utf-8").strip(), "0.49.1")

    def test_dry_run_from_0_49_0_announces_the_0_49_1_migration_and_changes_nothing(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        repo = Path(temporary.name) / "repo"
        repo.mkdir()
        test_installer.init_repo(repo)
        installed = test_installer.run_installer("install", str(repo))
        self.assertEqual(installed.returncode, 0, installed.stdout + installed.stderr)
        manifest_path = repo / ".harness" / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["version"] = "0.49.0"
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
        before = tree_digest(repo)

        result = test_installer.run_installer("update", str(repo), "--dry-run")

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(re.findall(r"^migration (\d+\.\d+\.\d+):", result.stdout, re.MULTILINE),
                         ["0.49.1"], result.stdout)
        self.assertRegex(result.stdout, r"(?m)^migration 0\.49\.1: \S")
        section = re.split(r"\n(?=migration \d|Apply migration)",
                           result.stdout.split("migration 0.49.1:", 1)[1])[0]
        self.assertRegex(section, r"(?i)literal")
        self.assertRegex(section, r"(?i)marker")
        self.assertRegex(section, r"(?i)no (existing )?files? (change|changed)|nothing changes|no file changes")
        self.assertEqual(tree_digest(repo), before)
        self.assertEqual(json.loads(manifest_path.read_text())["version"], "0.49.0")


if __name__ == "__main__":
    unittest.main()

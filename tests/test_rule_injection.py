import json
import os
import re
import tempfile
import unittest
from pathlib import Path

from test_installer import REPO_ROOT, run_git, run_installer
from test_lazy_rules import split_sections
from test_progress import ProgressCase

INSTRUCTIONS = ".harness/instructions"
RULE_FILES = ("progress.md", "index-and-staleness.md", "try-n-fail.md", "todos.md", "synced-comments.md")
HEX_RECORD = "0123456789abcdef-x.md"
SID = "sessinj"
S10 = """## Rule Files

These rules live in separate files under `.harness/instructions/`. A hook adds a rule's text to the session at its first Write or Edit in the rule's directory; read the file yourself before other work it covers. Hook and pre-commit messages name the file of a rule they find violated.

| file | read before |
| --- | --- |
| `progress.md` | committing in a session that changed the project, continuing earlier work, or opening a PR |
| `index-and-staleness.md` | adding, renaming, or marking stale a record in `agent-docs/` |
| `try-n-fail.md` | proposing a try-n-fail record |
| `todos.md` | writing a todo |
| `synced-comments.md` | keeping one comment identical in several places, or editing code tagged `synced id:` |
"""



def header(name, directory):
    return f"harness: rule text of {INSTRUCTIONS}/{name} for writing in {directory}/:"


class InjectionCase(ProgressCase):
    def ready(self, docs_root=None):
        repo = self.new_repo()
        if docs_root:
            (repo / ".harness" / "config.json").write_text(json.dumps({"docs_root": docs_root}))
        self.own_marker(repo)
        self.assertEqual(self.start(repo, sid=SID).returncode, 0)
        return repo

    def own_marker(self, repo):
        self.add_marker(repo, os.getpid())

    def rule_text(self, repo, name, directory):
        return header(name, directory) + "\n\n" + (repo / INSTRUCTIONS / name).read_text()

    def expected(self, repo, names, directory):
        return "\n\n".join(self.rule_text(repo, name, directory) for name in names)

    def pre(self, repo, rel, sid=SID, tool="Write", absolute=True, **kw):
        target = str(repo / rel) if absolute else rel
        payload = {"hook_event_name": "PreToolUse", "tool_name": tool, "tool_input": {"file_path": target}}
        if sid is not None:
            payload["session_id"] = sid
        return self.hook(repo, payload, **kw)

    def assert_injected(self, result, text):
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn("Traceback", result.stderr)
        self.assertEqual(json.loads(result.stdout),
                         {"hookSpecificOutput": {"hookEventName": "PreToolUse", "additionalContext": text}})

    def assert_silent(self, result):
        self.assertEqual((result.returncode, result.stdout), (0, ""), result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def markers(self, repo, sid=SID):
        directory = self.sessions_dir(repo) / f"progress-{sid}.d"
        return sorted(p.name for p in directory.glob("rule-*")) if directory.is_dir() else []


class TestDirectoryMapping(InjectionCase):
    def notes_repo(self):
        repo = self.ready()
        (repo / "agent-docs" / "notes").mkdir(parents=True, exist_ok=True)
        (repo / "agent-docs" / "notes" / "index.md").write_text("")
        return repo

    def test_each_rule_directory_returns_its_rule_files_in_order_as_exact_json(self):
        table = (
            ("progress", ["progress.md"]),
            ("progress-logs", ["progress.md"]),
            ("try-n-fail", ["try-n-fail.md", "index-and-staleness.md"]),
            ("todos", ["todos.md", "index-and-staleness.md"]),
            ("synced-comments", ["synced-comments.md"]),
            ("notes", ["index-and-staleness.md"]),
        )
        repo = self.notes_repo()
        for number, (directory, names) in enumerate(table):
            with self.subTest(directory=directory):
                sid = f"sessmap{number}"
                self.start(repo, sid=sid)
                result = self.pre(repo, f"agent-docs/{directory}/{HEX_RECORD}", sid=sid)
                self.assert_injected(result, self.expected(repo, names, f"agent-docs/{directory}"))
                self.assertEqual(self.markers(repo, sid), sorted(f"rule-{Path(n).stem}" for n in names))

    def test_edit_and_multiedit_inject_like_write(self):
        repo = self.ready()
        for number, tool in enumerate(("Edit", "MultiEdit")):
            with self.subTest(tool=tool):
                sid = f"sesstool{number}"
                self.start(repo, sid=sid)
                result = self.pre(repo, f"agent-docs/synced-comments/{HEX_RECORD}", sid=sid, tool=tool)
                self.assert_injected(result, self.expected(repo, ["synced-comments.md"], "agent-docs/synced-comments"))

    def test_relative_and_dotdot_targets_resolve_before_matching(self):
        repo = self.ready()
        for number, target in enumerate((f"agent-docs/todos/{HEX_RECORD}", f"agent-docs/try-n-fail/../todos/{HEX_RECORD}")):
            with self.subTest(target=target):
                sid = f"sessrel{number}"
                self.start(repo, sid=sid)
                result = self.pre(repo, target, sid=sid, absolute=False)
                self.assert_injected(result, self.expected(repo, ["todos.md", "index-and-staleness.md"], "agent-docs/todos"))

    def test_pre_tool_use_is_registered_for_write_edit_and_multiedit(self):
        repo = self.make_repo()
        self.assertEqual(run_installer("install", str(repo), "--no-ci").returncode, 0)
        groups = json.loads((repo / ".claude" / "settings.json").read_text())["hooks"]["PreToolUse"]
        for tool in ("Write", "Edit", "MultiEdit"):
            with self.subTest(tool=tool):
                matched = [g for g in groups if re.fullmatch(g.get("matcher", ".*"), tool)
                           and any("progress_hook.py" in h["command"] for h in g["hooks"])]
                self.assertTrue(matched)


class TestOncePerSession(InjectionCase):
    def test_second_write_into_the_same_directory_prints_nothing(self):
        repo = self.ready()
        first = self.pre(repo, f"agent-docs/todos/{HEX_RECORD}")
        self.assertTrue(first.stdout)
        self.assert_silent(self.pre(repo, f"agent-docs/todos/{HEX_RECORD}"))
        self.assert_silent(self.pre(repo, "agent-docs/todos/index.md", tool="Edit"))

    def test_later_first_write_into_try_n_fail_injects_only_its_own_rule_file(self):
        repo = self.ready()
        self.pre(repo, f"agent-docs/todos/{HEX_RECORD}")
        result = self.pre(repo, f"agent-docs/try-n-fail/{HEX_RECORD}")
        self.assert_injected(result, self.rule_text(repo, "try-n-fail.md", "agent-docs/try-n-fail"))
        self.assertEqual(self.markers(repo), ["rule-index-and-staleness", "rule-todos", "rule-try-n-fail"])

    def test_progress_logs_after_progress_injects_nothing_because_progress_md_is_already_in(self):
        repo = self.ready()
        self.assertTrue(self.pre(repo, f"agent-docs/progress/{HEX_RECORD}").stdout)
        self.assert_silent(self.pre(repo, f"agent-docs/progress-logs/{HEX_RECORD}"))

    def test_another_session_gets_the_rule_text_again(self):
        repo = self.ready()
        self.pre(repo, f"agent-docs/todos/{HEX_RECORD}")
        self.start(repo, sid="sessother")
        result = self.pre(repo, f"agent-docs/todos/{HEX_RECORD}", sid="sessother")
        self.assert_injected(result, self.expected(repo, ["todos.md", "index-and-staleness.md"], "agent-docs/todos"))


class TestNoInjection(InjectionCase):
    def test_paths_outside_rule_directories_print_nothing(self):
        repo = self.ready()
        for rel in ("src/a.py", "agent-docs/sync-state.json", "README.md"):
            with self.subTest(path=rel):
                self.assert_silent(self.pre(repo, rel))
        self.assertEqual(self.markers(repo), [])

    def test_specs_and_spec_logs_directories_print_nothing(self):
        repo = self.ready()
        for directory in ("specs", "spec-logs"):
            with self.subTest(directory=directory):
                (repo / "agent-docs" / directory / "index.md").parent.mkdir(parents=True, exist_ok=True)
                (repo / "agent-docs" / directory / "index.md").write_text("")
                self.assert_silent(self.pre(repo, f"agent-docs/{directory}/{HEX_RECORD}"))
        self.assertEqual(self.markers(repo), [])

    def test_directory_without_an_index_under_docs_root_prints_nothing(self):
        repo = self.ready()
        self.assert_silent(self.pre(repo, f"agent-docs/plain/{HEX_RECORD}"))

    def test_missing_session_id_prints_nothing(self):
        repo = self.ready()
        self.assert_silent(self.pre(repo, f"agent-docs/todos/{HEX_RECORD}", sid=None))
        self.assert_silent(self.pre(repo, f"agent-docs/todos/{HEX_RECORD}", sid=""))

    def test_other_tools_do_not_trigger_injection(self):
        repo = self.ready()
        self.assert_silent(self.pre(repo, f"agent-docs/todos/{HEX_RECORD}", tool="Read"))
        self.assertEqual(self.markers(repo), [])

    def test_unreadable_rule_file_is_skipped_without_marker_and_injected_on_the_next_write(self):
        repo = self.ready()
        rule = repo / INSTRUCTIONS / "todos.md"
        original = rule.read_text()
        rule.unlink()
        first = self.pre(repo, f"agent-docs/todos/{HEX_RECORD}")
        self.assert_injected(first, self.rule_text(repo, "index-and-staleness.md", "agent-docs/todos"))
        self.assertEqual(self.markers(repo), ["rule-index-and-staleness"])
        rule.write_text(original)
        second = self.pre(repo, f"agent-docs/todos/{HEX_RECORD}")
        self.assert_injected(second, self.rule_text(repo, "todos.md", "agent-docs/todos"))

    def test_every_rule_file_unreadable_prints_nothing_and_exits_zero(self):
        repo = self.ready()
        (repo / INSTRUCTIONS / "todos.md").unlink()
        (repo / INSTRUCTIONS / "index-and-staleness.md").unlink()
        self.assert_silent(self.pre(repo, f"agent-docs/todos/{HEX_RECORD}"))
        self.assertEqual(self.markers(repo), [])

    def test_git_missing_prints_no_injection_and_never_crashes(self):
        repo = self.ready()
        env = self.env(PATH=self.empty_path_dir())
        result = self.pre(repo, f"agent-docs/todos/{HEX_RECORD}", env=env)
        self.assert_silent(result)


class TestConfiguredDocsRootInjection(InjectionCase):
    def test_rule_directories_under_the_configured_docs_root_inject_with_that_directory_name(self):
        repo = self.ready(docs_root="docs/agent")
        result = self.pre(repo, f"docs/agent/todos/{HEX_RECORD}")
        self.assert_injected(result, self.expected(repo, ["todos.md", "index-and-staleness.md"], "docs/agent/todos"))

    def test_default_layout_directories_print_nothing_when_docs_root_is_configured(self):
        repo = self.ready(docs_root="docs/agent")
        self.assert_silent(self.pre(repo, f"agent-docs/todos/{HEX_RECORD}"))

    def test_other_indexed_directory_and_specs_follow_the_configured_root(self):
        repo = self.ready(docs_root="docs/agent")
        (repo / "docs" / "agent" / "notes").mkdir(parents=True)
        (repo / "docs" / "agent" / "notes" / "index.md").write_text("")
        (repo / "docs" / "agent" / "specs").mkdir(parents=True)
        (repo / "docs" / "agent" / "specs" / "index.md").write_text("")
        self.start(repo, sid="sessnotes")
        injected = self.pre(repo, f"docs/agent/notes/{HEX_RECORD}", sid="sessnotes")
        self.assert_injected(injected, self.expected(repo, ["index-and-staleness.md"], "docs/agent/notes"))
        self.assert_silent(self.pre(repo, f"docs/agent/specs/{HEX_RECORD}"))


class TestRuleText(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.tmp.cleanup)
        cls.repo = Path(cls.tmp.name)
        run_git(cls.repo, "init", "-q")
        result = run_installer("install", str(cls.repo), "--no-ci")
        if result.returncode != 0:
            raise RuntimeError(result.stdout + result.stderr)

    def payload(self, *parts):
        return (REPO_ROOT / "harness" / Path(*parts)).read_text()

    def test_rule_files_section_of_the_block_equals_the_expected_text_in_source_and_install(self):
        for label, text in (("payload", self.payload("instructions", "harness-block.md")),
                            ("installed", (self.repo / INSTRUCTIONS / "harness-block.md").read_text())):
            with self.subTest(copy=label):
                sections = split_sections(text)
                self.assertEqual([h for h, _ in sections].count("## Rule Files"), 1)
                self.assertEqual(dict(sections)["## Rule Files"].rstrip("\n"), S10.rstrip("\n"))

    def test_synced_comments_rule_names_end_markers_block_hash_and_refresh_command(self):
        text = self.payload("instructions", "synced-comments.md")
        for needle in ("synced end:", "synced-refresh"):
            with self.subTest(needle=needle):
                self.assertIn(needle, text)

    def test_index_rule_names_the_stale_command(self):
        self.assertIn("records.py stale", self.payload("instructions", "index-and-staleness.md"))

    def test_progress_rule_describes_the_record_only_kind(self):
        self.assertIn("record-only", self.payload("instructions", "progress.md"))

    def test_continue_on_skill_notes_that_record_only_progress_is_skipped(self):
        text = self.payload("skills", "continue-on", "SKILL.md")
        self.assertIn("record-only", text)
        self.assertIn("progress-logs", text)

    def test_readme_mentions_records_command_and_record_only_progress(self):
        text = (REPO_ROOT / "README.md").read_text()
        self.assertIn("records.py", text)
        self.assertIn("record-only", text)

    def test_installed_copies_equal_the_payload_files(self):
        pairs = [(Path(INSTRUCTIONS) / name, Path("harness") / "instructions" / name) for name in (*RULE_FILES, "harness-block.md")]
        pairs.append((Path(".harness") / "bin" / "records.py", Path("harness") / "bin" / "records.py"))
        for installed, source in pairs:
            with self.subTest(file=installed.name):
                self.assertEqual((self.repo / installed).read_bytes(), (REPO_ROOT / source).read_bytes())


if __name__ == "__main__":
    unittest.main()

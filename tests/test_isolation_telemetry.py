import ast
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from hypothesis import HealthCheck, given, seed, settings
from hypothesis import strategies as st

from test_telemetry import TelemetryTestCase

REPO_ROOT = Path(__file__).resolve().parents[1]
HARNESS_LIB = REPO_ROOT / "harness" / "lib"
sys.path.insert(0, str(HARNESS_LIB))
try:
    import isolation
except ImportError:
    isolation = None

RULES = ("test_reads_implementation", "test_runs_tests", "impl_reads_tests",
         "impl_runs_test_command", "dispatch_run_instruction")
CANDIDATE_KEYS = {"rule", "tool_name", "match", "match_kind", "excerpt"}
TEST_COMMAND = "make check-all"
IMPL_FILE = "pkg/directives.go"
IMPL_OTHER = "other/config.go"


def write_spec(specs_dir, name, status="active", impl=None, tests=None, command=None):
    specs_dir.mkdir(parents=True, exist_ok=True)
    lines = []
    if status is not None:
        lines += ["---", f"status: {status}", "---"]
    lines += ["", "# Paths"]
    if impl is not None:
        lines.append(f"Implementation: {impl}")
    if tests is not None:
        lines.append(f"Tests: {tests}")
    if command is not None:
        lines.append(f"Test command: {command}")
    lines.append("")
    path = specs_dir / f"{name}.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def pre_tool_use(agent, tool, tool_input, cwd=None, **extra):
    payload = {"hook_event_name": "PreToolUse", "tool_name": tool, "tool_input": tool_input}
    if agent is not None:
        payload["agent_type"] = agent
    if cwd is not None:
        payload["cwd"] = cwd
    payload.update(extra)
    return payload


class DetectCase(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(isolation, "harness/lib/isolation.py is not importable")
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.repo = Path(tmp.name)
        self.specs = self.repo / "agent-docs" / "specs"
        (self.repo / "pkg").mkdir()
        (self.repo / "other").mkdir()
        (self.repo / "tests").mkdir()
        write_spec(self.specs, "main", impl=f"{IMPL_FILE}, {IMPL_OTHER}", tests="tests/",
                   command=TEST_COMMAND)

    def detect(self, payload, specs=None):
        results = isolation.detect(payload, self.specs if specs is None else specs, self.repo)
        self.assertIsInstance(results, list)
        for item in results:
            self.assertEqual(set(item), CANDIDATE_KEYS)
        rules = [item["rule"] for item in results]
        self.assertEqual(len(rules), len(set(rules)), rules)
        self.assertEqual(rules, sorted(rules, key=RULES.index))
        return results

    def run_as(self, agent, tool, tool_input, cwd="repo", specs=None):
        cwd = str(self.repo) if cwd == "repo" else cwd
        return self.detect(pre_tool_use(agent, tool, tool_input, cwd), specs)

    def ti_bash(self, command, cwd="repo", specs=None):
        return self.run_as("test-implementer", "Bash", {"command": command}, cwd, specs)

    def ti_read(self, file_path, cwd="repo"):
        return self.run_as("test-implementer", "Read", {"file_path": file_path}, cwd)

    def assert_single(self, results, rule, kind=None, match=None):
        self.assertEqual([r["rule"] for r in results], [rule], results)
        if kind is not None:
            self.assertEqual(results[0]["match_kind"], kind)
        if match is not None:
            self.assertEqual(results[0]["match"], match)


class TestSignatureConstants(DetectCase):
    def test_rules_and_excerpt_limit_match_signature(self):
        self.assertEqual(isolation.RULES, RULES)
        self.assertEqual(isolation.EXCERPT_LIMIT, 500)


class TestO1PathEquivalence(DetectCase):
    def test_p1_read_relative_path(self):
        for label, cwd in (("cwd=repo", "repo"), ("cwd absent", None), ("cwd not a string", 7)):
            with self.subTest(label):
                payload = pre_tool_use("test-implementer", "Read", {"file_path": IMPL_FILE},
                                       str(self.repo) if cwd == "repo" else cwd)
                self.assert_single(self.detect(payload), "test_reads_implementation", "path", IMPL_FILE)
        for variant in ("./pkg/directives.go", "pkg/../pkg/directives.go"):
            with self.subTest(variant):
                self.assert_single(self.ti_read(variant), "test_reads_implementation", "path", IMPL_FILE)

    def test_p2_read_absolute_path_including_symlinks(self):
        absolute = str(self.repo / IMPL_FILE)
        self.assert_single(self.ti_read(absolute), "test_reads_implementation", "path", IMPL_FILE)
        resolved = os.path.realpath(absolute)
        self.assert_single(self.ti_read(resolved), "test_reads_implementation", "path", IMPL_FILE)
        os.symlink(self.repo / "pkg", self.repo / "alias")
        self.assert_single(self.ti_read(str(self.repo / "alias" / "directives.go")),
                           "test_reads_implementation", "path", IMPL_FILE)

    def test_p3_bash_token_relative_to_cwd(self):
        results = self.ti_bash("sed -n 92,108p directives.go", cwd=str(self.repo / "pkg"))
        self.assert_single(results, "test_reads_implementation", "path", IMPL_FILE)

    def test_p4_bash_bare_basename_with_cwd_elsewhere(self):
        for label, command, cwd in (
            ("cd then bare filename, cwd repo", "cd pkg && sed -n 1,5p directives.go", "repo"),
            ("cwd in other dir", "sed -n 1,5p directives.go", str(self.repo / "other")),
        ):
            with self.subTest(label):
                results = self.ti_bash(command, cwd=cwd)
                self.assert_single(results, "test_reads_implementation", "basename", IMPL_FILE)

    def test_p5_token_with_colon_suffix(self):
        results = self.ti_bash("cat pkg/directives.go:45")
        self.assert_single(results, "test_reads_implementation", "path", IMPL_FILE)
        results = self.ti_bash("grep 'directives.go:4[5-9][0-9]' cover.out")
        self.assert_single(results, "test_reads_implementation", "basename", IMPL_FILE)

    def test_p6_token_with_equals_prefix(self):
        for command in ("go build --out=pkg/directives.go", "tool --x=y=pkg/directives.go"):
            with self.subTest(command):
                results = self.ti_bash(command)
                self.assert_single(results, "test_reads_implementation", "path", IMPL_FILE)

    def test_p7_file_under_directory_spec_path(self):
        write_spec(self.specs, "main", impl="pkg/", tests="tests/", command=TEST_COMMAND)
        for target in ("pkg/sub/x.go", "pkg/x.go"):
            with self.subTest(target):
                self.assert_single(self.ti_read(target), "test_reads_implementation", "path", "pkg/")
        self.assertEqual(self.ti_read("pkgx/x.go"), [])

    def test_p8_glob_pattern_basename(self):
        results = self.run_as("test-implementer", "Glob", {"pattern": "**/directives.go"})
        self.assert_single(results, "test_reads_implementation", "basename", IMPL_FILE)

    def test_p9_grep_path(self):
        results = self.run_as("test-implementer", "Grep", {"pattern": "foo", "path": IMPL_FILE})
        self.assert_single(results, "test_reads_implementation", "path", IMPL_FILE)
        results = self.run_as("test-implementer", "Grep", {"pattern": IMPL_FILE})
        self.assertEqual(results, [])

    def test_a1_grep_glob_key_and_glob_path_key_are_reference_strings(self):
        results = self.run_as("test-implementer", "Grep",
                              {"pattern": "x", "path": "other", "glob": IMPL_FILE})
        self.assert_single(results, "test_reads_implementation", "path", IMPL_FILE)
        results = self.run_as("test-implementer", "Glob", {"pattern": "*.txt", "path": IMPL_FILE})
        self.assert_single(results, "test_reads_implementation", "path", IMPL_FILE)

    def test_p10_ls_path(self):
        results = self.run_as("test-implementer", "LS", {"path": IMPL_FILE})
        self.assert_single(results, "test_reads_implementation", "path", IMPL_FILE)

    def test_p11_unrelated_path_gives_none(self):
        self.assertEqual(self.ti_read("other/unrelated.go"), [])
        self.assertEqual(self.ti_read("pkg/directives.gox"), [])
        self.assertEqual(self.ti_read("pkg/directives.go.bak"), [])
        self.assertEqual(self.run_as("test-implementer", "LS", {"path": str(self.repo)}), [])
        self.assertEqual(self.run_as("test-implementer", "Grep",
                                     {"pattern": "x", "path": str(self.repo), "glob": "*.go"}), [])

    def test_p12_path_match_preferred_over_earlier_basename_candidate(self):
        results = self.ti_bash("cat config.go pkg/directives.go")
        self.assert_single(results, "test_reads_implementation", "path", IMPL_FILE)


RUNNER_CASES = [
    ("R1", "pytest tests/x.py"),
    ("R2", "py.test tests/x.py"),
    ("R3", "python -m pytest tests/x.py"),
    ("R4", "python -m unittest discover"),
    ("R5", "go test ./pkg/"),
    ("R6", "vitest run"),
    ("R7", "jest src"),
    ("R8", "npm test"),
    ("R9", "npm run test"),
    ("R9", "npm run test:unit"),
    ("R10", "yarn test"),
    ("R11", "pnpm test"),
    ("R12", "cargo test"),
    ("R13", "mvn test"),
    ("R14", "gradle test"),
    ("R15", "gradlew test"),
    ("R15", "./gradlew test"),
    ("R16", "rspec spec/x_spec.rb"),
    ("python3.12", "python3.12 -m pytest -q"),
    ("python3", "python3 -m pytest -q"),
    ("venv python", ".venv/bin/python -m pytest -q tests"),
]

EXCLUSION_CASES = [
    ("X1", "pytest --collect-only -q tests/test_x.py"),
    ("X1", "python -m pytest --collect-only -q"),
    ("X2", "pytest --co -q"),
    ("X3", "go test -list . ./pkg/"),
    ("X4", "vitest list src/App.test.jsx"),
    ("X5", "jest --listTests"),
    ("X6", "cargo test --no-run"),
]


class TestO2RunnerRule(DetectCase):
    def test_runner_sequences_fire_as_runner_candidates(self):
        for label, command in RUNNER_CASES:
            with self.subTest(label=label, command=command):
                results = self.ti_bash(command)
                self.assert_single(results, "test_runs_tests", "runner", command)

    def test_a2_pytest_cov_option_is_not_an_exclusion(self):
        results = self.ti_bash("pytest --cov=pkg tests")
        self.assert_single(results, "test_runs_tests", "runner", "pytest --cov=pkg tests")

    def test_exclusions_do_not_fire(self):
        for label, command in EXCLUSION_CASES:
            with self.subTest(label=label, command=command):
                self.assertEqual(self.ti_bash(command), [])

    def test_non_runner_commands_do_not_fire(self):
        for command in ("ls -la", "go build ./...", "npm run build", "python script.py", "git status"):
            with self.subTest(command):
                self.assertEqual(self.ti_bash(command), [])

    def test_runner_in_later_segment_after_and_and_other_separators(self):
        results = self.ti_bash("cd pkg && go test -race ./pkg/")
        self.assert_single(results, "test_runs_tests", "runner", "go test -race ./pkg/")
        for separator in ("||", ";", "|", "\n"):
            with self.subTest(repr(separator)):
                results = self.ti_bash(f"echo hi {separator} cargo test -q")
                self.assert_single(results, "test_runs_tests", "runner", "cargo test -q")

    def test_exclusion_applies_per_segment(self):
        results = self.ti_bash("pytest --collect-only -q && pytest   tests  -x")
        self.assert_single(results, "test_runs_tests", "runner", "pytest tests -x")

    def test_c14_test_command_substring_is_test_command_kind(self):
        for label, command in (
            ("suffix", f"{TEST_COMMAND} -k foo"),
            ("whitespace-normalized", "make\t check-all   -k foo"),
            ("inside compound", f"cd x && {TEST_COMMAND}"),
        ):
            with self.subTest(label):
                self.assert_single(self.ti_bash(command), "test_runs_tests", "test_command", TEST_COMMAND)
        self.assertEqual(self.ti_bash("make check"), [])

    def test_test_command_kind_wins_over_runner_kind(self):
        write_spec(self.specs, "main", impl=IMPL_FILE, tests="tests/",
                   command=".venv/bin/python -m pytest -q tests")
        results = self.ti_bash("cd x && .venv/bin/python -m pytest -q tests -k foo")
        self.assert_single(results, "test_runs_tests", "test_command",
                           ".venv/bin/python -m pytest -q tests")

    def test_spec_test_command_is_whitespace_normalized(self):
        write_spec(self.specs, "main", impl=IMPL_FILE, tests="tests/", command="make    check-all")
        self.assert_single(self.ti_bash("make check-all"), "test_runs_tests", "test_command", TEST_COMMAND)


class TestO3DecisionTable(DetectCase):
    def test_agent_type_by_input_decision_table(self):
        inputs = {
            "impl_read": lambda agent: pre_tool_use(agent, "Read", {"file_path": IMPL_FILE}, str(self.repo)),
            "tests_read": lambda agent: pre_tool_use(agent, "Read", {"file_path": "tests/test_x.py"}, str(self.repo)),
            "runner": lambda agent: pre_tool_use(agent, "Bash", {"command": "go test ./..."}, str(self.repo)),
            "test_command": lambda agent: pre_tool_use(agent, "Bash", {"command": TEST_COMMAND}, str(self.repo)),
        }
        agents = ["test-implementer", "implementer", "absent", "", "test-verifier"]
        expected = {
            ("test-implementer", "impl_read"): {"test_reads_implementation"},
            ("test-implementer", "tests_read"): set(),
            ("test-implementer", "runner"): {"test_runs_tests"},
            ("test-implementer", "test_command"): {"test_runs_tests"},
            ("implementer", "impl_read"): set(),
            ("implementer", "tests_read"): {"impl_reads_tests"},
            ("implementer", "runner"): set(),
            ("implementer", "test_command"): {"impl_runs_test_command"},
        }
        for agent in agents:
            for name, build in inputs.items():
                with self.subTest(agent=agent, input=name):
                    payload = build(None if agent == "absent" else agent)
                    fired = {r["rule"] for r in self.detect(payload)}
                    self.assertEqual(fired, expected.get((agent, name), set()))

    def test_c5_implementer_reads_tests_dir_path_match(self):
        results = self.run_as("implementer", "Read", {"file_path": "tests/test_x.py"})
        self.assert_single(results, "impl_reads_tests", "path", "tests/")

    def test_c11_test_verifier_reads_implementation_gives_none(self):
        self.assertEqual(self.run_as("test-verifier", "Read", {"file_path": IMPL_FILE}), [])

    def test_implementer_test_command_match_fields(self):
        results = self.run_as("implementer", "Bash", {"command": f"{TEST_COMMAND} -v"})
        self.assert_single(results, "impl_runs_test_command", "test_command", TEST_COMMAND)
        self.assertEqual(results[0]["tool_name"], "Bash")


class TestO4DispatchAndExcerpts(DetectCase):
    def dispatch(self, prompt, subagent="test-implementer", tool="Agent", agent=None, specs=None):
        payload = pre_tool_use(agent, tool, {"subagent_type": subagent, "prompt": prompt}, str(self.repo))
        return self.detect(payload, specs)

    def test_c6_runner_in_prompt_fires_for_agent_and_task(self):
        prompt = "Implement tests. Run your tests with `python -m pytest tests -q` and report."
        stripped = prompt.replace("`", "")
        for tool in ("Agent", "Task"):
            with self.subTest(tool):
                results = self.dispatch(prompt, tool=tool)
                self.assert_single(results, "dispatch_run_instruction", "runner", stripped)
                self.assertEqual(results[0]["tool_name"], tool)
                self.assertEqual(results[0]["excerpt"], stripped)

    def test_dispatch_requires_test_implementer_subagent_and_main_caller(self):
        prompt = "Run `pytest -q` please"
        self.assertEqual(self.dispatch(prompt, subagent="implementer"), [])
        self.assertEqual(self.dispatch(prompt, agent="test-implementer"), [])
        self.assertEqual(self.dispatch(prompt, agent=""), self.dispatch(prompt))
        self.assertEqual(len(self.dispatch(prompt, agent="")), 1)

    def test_dispatch_prompt_variants(self):
        results = self.dispatch(f"Please run {TEST_COMMAND} now")
        self.assert_single(results, "dispatch_run_instruction", "test_command", TEST_COMMAND)
        self.assertEqual(self.dispatch("Write tests for the parser module."), [])
        self.assertEqual(self.dispatch("Only list them: pytest --collect-only -q"), [])

    def test_dispatch_runner_condition_needs_no_active_spec(self):
        missing = self.repo / "no-specs-here"
        results = self.dispatch("Run `npm test` and report", specs=missing)
        self.assert_single(results, "dispatch_run_instruction", "runner", "Run npm test and report")
        self.assertEqual(self.dispatch(f"Run {TEST_COMMAND}", specs=missing), [])

    def test_bash_excerpt_boundary_499_500_501(self):
        for length, expected_length in ((499, 499), (500, 500), (501, 500)):
            with self.subTest(length):
                command = "pytest " + "x" * (length - len("pytest "))
                self.assertEqual(len(command), length)
                results = self.ti_bash(command)
                self.assert_single(results, "test_runs_tests", "runner")
                self.assertEqual(len(results[0]["excerpt"]), expected_length)
                self.assertEqual(results[0]["excerpt"], command[:500])

    def test_dispatch_window_start_at_match_index_199_200_1000(self):
        for index, start in ((199, 0), (200, 0), (1000, 800)):
            with self.subTest(index):
                prompt = "a" * (index - 1) + " " + TEST_COMMAND + " " + "z" * 1500
                self.assertEqual(prompt.index(TEST_COMMAND), index)
                results = self.dispatch(prompt)
                self.assert_single(results, "dispatch_run_instruction", "test_command", TEST_COMMAND)
                self.assertEqual(results[0]["excerpt"], prompt[start:start + 500])
                self.assertEqual(len(results[0]["excerpt"]), 500)

    def test_dispatch_runner_window_uses_segment_start_not_runner_token_start(self):
        tail = " tail" * 200
        cases = (
            ("single segment", "word " * 70 + "run pytest -q" + tail, 0),
            ("newline segment", "a" * 300 + "\nNow run pytest -q" + tail, 101),
            ("&& segment", "a" * 300 + "&&Now run pytest -q" + tail, 102),
        )
        for label, prompt, start in cases:
            with self.subTest(label):
                self.assertGreater(len(prompt), start + 500 + 200)
                results = self.dispatch(prompt)
                self.assertEqual([r["rule"] for r in results], ["dispatch_run_instruction"])
                self.assertEqual(results[0]["match_kind"], "runner")
                self.assertEqual(results[0]["excerpt"], prompt[start:start + 500])
                self.assertEqual(len(results[0]["excerpt"]), 500)

    def test_read_excerpt_boundary_499_500_501(self):
        write_spec(self.specs, "main", impl="pkg/", tests="tests/", command=TEST_COMMAND)
        for length, expected_length in ((499, 499), (500, 500), (501, 500)):
            with self.subTest(length):
                file_path = "pkg/" + "x" * (length - len("pkg/"))
                self.assertEqual(len(file_path), length)
                results = self.ti_read(file_path)
                self.assert_single(results, "test_reads_implementation", "path", "pkg/")
                self.assertEqual(len(results[0]["excerpt"]), expected_length)
                self.assertEqual(results[0]["excerpt"], file_path[:500])

    def test_grep_excerpt_boundary_499_500_501(self):
        base = len(json.dumps({"path": IMPL_FILE, "pattern": ""}, separators=(",", ":")))
        for length, expected_length in ((499, 499), (500, 500), (501, 500)):
            with self.subTest(length):
                tool_input = {"pattern": "p" * (length - base), "path": IMPL_FILE}
                compact = json.dumps(tool_input, separators=(",", ":"), sort_keys=True)
                self.assertEqual(len(compact), length)
                results = self.run_as("test-implementer", "Grep", tool_input)
                self.assert_single(results, "test_reads_implementation", "path", IMPL_FILE)
                self.assertEqual(len(results[0]["excerpt"]), expected_length)
                self.assertEqual(results[0]["excerpt"], compact[:500])

    def test_dispatch_window_index_is_taken_after_backtick_removal(self):
        prompt = "`" * 100 + "a" * 999 + " " + TEST_COMMAND + " " + "z" * 1500
        stripped = prompt.replace("`", "")
        self.assertEqual(stripped.index(TEST_COMMAND), 1000)
        results = self.dispatch(prompt)
        self.assert_single(results, "dispatch_run_instruction", "test_command", TEST_COMMAND)
        self.assertEqual(results[0]["excerpt"], stripped[800:1300])

    def test_read_excerpt_is_file_path(self):
        results = self.run_as("test-implementer", "Read", {"file_path": IMPL_FILE, "offset": 5})
        self.assert_single(results, "test_reads_implementation")
        self.assertEqual(results[0]["excerpt"], IMPL_FILE)

    def test_grep_glob_ls_excerpt_is_compact_sorted_json_of_tool_input(self):
        cases = (
            ("Grep", {"pattern": "foo", "path": IMPL_FILE, "glob": "*.go"}),
            ("Glob", {"pattern": "**/directives.go", "path": "other"}),
            ("LS", {"path": IMPL_FILE}),
        )
        for tool, tool_input in cases:
            with self.subTest(tool):
                results = self.run_as("test-implementer", tool, tool_input)
                self.assert_single(results, "test_reads_implementation")
                self.assertEqual(results[0]["excerpt"],
                                 json.dumps(tool_input, separators=(",", ":"), sort_keys=True))
                self.assertEqual(results[0]["tool_name"], tool)

    def test_one_call_firing_two_rules_returns_both_in_rules_order(self):
        results = self.ti_bash("go test ./... && cat pkg/directives.go")
        self.assertEqual([r["rule"] for r in results], ["test_reads_implementation", "test_runs_tests"])


class TestO5SpecSelection(DetectCase):
    def test_no_specs_dir(self):
        missing = self.repo / "absent-dir"
        self.assertEqual(self.ti_bash("cat pkg/directives.go", specs=missing), [])
        self.assert_single(self.ti_bash("npm test", specs=missing), "test_runs_tests", "runner")
        self.assertEqual(self.ti_bash(TEST_COMMAND, specs=missing), [])

    def test_c12_draft_only_spec(self):
        (self.specs / "main.md").unlink()
        write_spec(self.specs, "draft", status="draft", impl=IMPL_FILE, tests="tests/", command=TEST_COMMAND)
        self.assertEqual(self.ti_read(IMPL_FILE), [])
        self.assertEqual(self.ti_bash(TEST_COMMAND), [])
        self.assert_single(self.ti_bash("npm test"), "test_runs_tests", "runner")
        self.assertEqual(self.run_as("implementer", "Read", {"file_path": "tests/test_x.py"}), [])

    def test_one_active_spec_alongside_draft_spec(self):
        write_spec(self.specs, "draft", status="draft", impl="draftdir/secret.go", tests="draft_tests/")
        self.assert_single(self.ti_read(IMPL_FILE), "test_reads_implementation", "path", IMPL_FILE)
        self.assertEqual(self.ti_read("draftdir/secret.go"), [])

    def test_only_markdown_files_directly_under_specs_dir_count(self):
        nested = self.specs / "nested"
        write_spec(nested, "inner", impl="inner/only.go", tests="inner_tests/")
        self.assertEqual(self.ti_read("inner/only.go"), [])

    def test_two_active_specs_are_unioned(self):
        write_spec(self.specs, "second", impl="second/b.go", tests="tests2/", command="make second-check")
        self.assert_single(self.ti_read(IMPL_FILE), "test_reads_implementation", "path", IMPL_FILE)
        self.assert_single(self.ti_read("second/b.go"), "test_reads_implementation", "path", "second/b.go")
        self.assert_single(self.ti_bash(TEST_COMMAND), "test_runs_tests", "test_command", TEST_COMMAND)
        self.assert_single(self.ti_bash("make second-check"), "test_runs_tests", "test_command",
                           "make second-check")
        results = self.run_as("implementer", "Read", {"file_path": "tests2/t.py"})
        self.assert_single(results, "impl_reads_tests", "path", "tests2/")

    def test_spec_missing_tests_line_still_applies_other_parts(self):
        write_spec(self.specs, "main", impl=IMPL_FILE, tests=None, command=TEST_COMMAND)
        self.assertEqual(self.run_as("implementer", "Read", {"file_path": "tests/test_x.py"}), [])
        self.assert_single(self.ti_read(IMPL_FILE), "test_reads_implementation", "path", IMPL_FILE)
        self.assert_single(self.run_as("implementer", "Bash", {"command": TEST_COMMAND}),
                           "impl_runs_test_command", "test_command")

    def test_spec_missing_implementation_and_test_command_lines(self):
        write_spec(self.specs, "main", impl=None, tests="tests/", command=None)
        self.assertEqual(self.ti_read(IMPL_FILE), [])
        self.assertEqual(self.ti_bash(TEST_COMMAND), [])
        self.assert_single(self.run_as("implementer", "Read", {"file_path": "tests/t.py"}),
                           "impl_reads_tests", "path", "tests/")

    def test_directory_path_by_trailing_slash_without_existing_directory(self):
        write_spec(self.specs, "main", impl="ghost/", tests="tests/")
        self.assert_single(self.ti_read("ghost/deep/x.go"), "test_reads_implementation", "path", "ghost/")

    def test_directory_path_by_existing_directory_without_trailing_slash(self):
        write_spec(self.specs, "main", impl="pkg", tests="tests/")
        self.assert_single(self.ti_read("pkg/sub/x.go"), "test_reads_implementation", "path", "pkg")
        write_spec(self.specs, "main", impl="phantom", tests="tests/")
        self.assertEqual(self.ti_read("phantom/sub/x.go"), [])

    def test_comma_separated_paths_trimmed_and_empty_items_dropped(self):
        write_spec(self.specs, "main", impl=" a/one.go ,, b/two.go ,", tests="tests/")
        self.assert_single(self.ti_read("a/one.go"), "test_reads_implementation", "path", "a/one.go")
        self.assert_single(self.ti_read("b/two.go"), "test_reads_implementation", "path", "b/two.go")


class TestO10SideEffectFreeAndOffline(DetectCase):
    def snapshot(self, *roots):
        state = {}
        for root in roots:
            for path in sorted(Path(root).rglob("*")):
                if path.is_file():
                    stat = path.stat()
                    state[str(path)] = (stat.st_size, stat.st_mtime_ns,
                                        hashlib.sha256(path.read_bytes()).hexdigest())
                else:
                    state[str(path)] = None
        return state

    def test_n1_detect_writes_no_file_under_telemetry_dir_home_or_repo(self):
        telemetry = Path(tempfile.mkdtemp())
        home = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: shutil.rmtree(telemetry, ignore_errors=True))
        self.addCleanup(lambda: shutil.rmtree(home, ignore_errors=True))
        payloads = [
            pre_tool_use("test-implementer", "Read", {"file_path": IMPL_FILE}, str(self.repo)),
            pre_tool_use("test-implementer", "Bash", {"command": "go test ./..."}, str(self.repo)),
            pre_tool_use("implementer", "Read", {"file_path": "tests/t.py"}, str(self.repo)),
            pre_tool_use("implementer", "Bash", {"command": TEST_COMMAND}, str(self.repo)),
            pre_tool_use(None, "Agent", {"subagent_type": "test-implementer", "prompt": "run pytest"},
                         str(self.repo)),
        ]
        before = self.snapshot(self.repo, telemetry, home)
        with mock.patch.dict(os.environ, {"HARNESS_TELEMETRY_DIR": str(telemetry), "HOME": str(home)}):
            fired = [self.detect(payload) for payload in payloads]
        self.assertTrue(all(len(results) >= 1 for results in fired), fired)
        self.assertEqual(self.snapshot(self.repo, telemetry, home), before)
        self.assertEqual(list(telemetry.iterdir()), [])
        self.assertEqual(list(home.iterdir()), [])

    def test_n2_isolation_source_imports_no_network_modules(self):
        tree = ast.parse((HARNESS_LIB / "isolation.py").read_text(encoding="utf-8"))
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                imported.add(node.module.split(".")[0])
        self.assertEqual(imported & {"socket", "urllib", "http", "requests"}, set())


class HookCase(TelemetryTestCase):
    def setUp(self):
        self.repo, self.telemetry_dir = self.install_with_telemetry_dir()
        self.env = self.telemetry_env(self.telemetry_dir)
        self.specs = self.repo / "agent-docs" / "specs"
        write_spec(self.specs, "iso", impl=f"{IMPL_FILE}, {IMPL_OTHER}", tests="tests/", command=TEST_COMMAND)

    def fire(self, payload, env=None):
        return self.run_hook_env(self.repo, "telemetry_hook.py", payload, env or self.env)

    def candidates(self):
        return [e for e in self.read_events(self.telemetry_dir, self.repo)
                if e.get("event") == "isolation_candidate"]

    def ti(self, tool, tool_input, **extra):
        return pre_tool_use("test-implementer", tool, tool_input, str(self.repo),
                            agent_id="agent-1", session_id="sess-1", tool_use_id="tu-1", **extra)

    def assert_silent_success(self, result):
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stdout, "")


class TestO6HookScenarios(HookCase):
    def test_s1_read_implementation_path_emits_one_line_with_all_fields(self):
        result = self.fire(self.ti("Read", {"file_path": IMPL_FILE}))
        self.assert_silent_success(result)
        events = self.candidates()
        self.assertEqual(len(events), 1, events)
        event = events[0]
        self.assertEqual(event["event"], "isolation_candidate")
        self.assertEqual((event["agent_type"], event["agent_id"], event["session_id"], event["tool_use_id"]),
                         ("test-implementer", "agent-1", "sess-1", "tu-1"))
        for key in ("workflow_run_id", "ts", "repo", "v"):
            self.assertIn(key, event)
        self.assertEqual(event["repo"], str(self.repo.resolve()))
        self.assertEqual(
            {k: event[k] for k in CANDIDATE_KEYS},
            {"rule": "test_reads_implementation", "tool_name": "Read", "match": IMPL_FILE,
             "match_kind": "path", "excerpt": IMPL_FILE})

    def test_s2_call_firing_two_rules_writes_two_lines_in_rules_order(self):
        result = self.fire(self.ti("Bash", {"command": "go test ./... && cat pkg/directives.go"}))
        self.assert_silent_success(result)
        events = self.candidates()
        self.assertEqual([e["rule"] for e in events], ["test_reads_implementation", "test_runs_tests"])
        self.assertEqual({e["tool_use_id"] for e in events}, {"tu-1"})

    def test_s3_no_match_call_writes_no_line(self):
        for payload in (self.ti("Bash", {"command": "ls"}), self.ti("Read", {"file_path": "README.md"})):
            self.assert_silent_success(self.fire(payload))
        self.assertEqual(self.read_events(self.telemetry_dir, self.repo), [])

    def test_main_dispatch_through_hook_emits_dispatch_event(self):
        payload = pre_tool_use(None, "Agent", {"subagent_type": "test-implementer",
                                               "prompt": "Run your tests with `pytest -q`"},
                               str(self.repo), session_id="sess-1")
        self.assert_silent_success(self.fire(payload))
        events = self.candidates()
        self.assertEqual([e["rule"] for e in events], ["dispatch_run_instruction"])
        self.assertEqual(events[0]["match_kind"], "runner")

    def test_s4_matcher_fullmatch_list_in_generated_claude_settings(self):
        claude, codex = self.install_hook_configs()
        groups = [g for g in claude.get("PreToolUse", [])
                  if any("telemetry_hook.py" in c for c in self.commands([g]))]
        self.assertEqual(len(groups), 1, claude.get("PreToolUse"))
        matcher = groups[0].get("matcher", "")
        for tool in ("Bash", "Read", "Grep", "Glob", "LS", "Agent", "Task"):
            self.assertIsNotNone(re.fullmatch(matcher, tool), (matcher, tool))
        for tool in ("Write", "Edit"):
            self.assertIsNone(re.fullmatch(matcher, tool), (matcher, tool))
        self.assertFalse(any("telemetry_hook.py" in c for c in self.commands(codex.get("PreToolUse", []))))

    def test_s5_existing_pre_tool_use_and_post_tool_use_entries_unchanged(self):
        claude, _codex = self.install_hook_configs()
        pre = self.commands(claude.get("PreToolUse", []))
        self.assertTrue(any("spec_gate.py" in c for c in pre), pre)
        post = self.commands(claude.get("PostToolUse", []))
        self.assertTrue(any("telemetry_hook.py" in c for c in post), post)
        failure = self.commands(claude.get("PostToolUseFailure", []))
        self.assertTrue(any("telemetry_hook.py" in c for c in failure), failure)


junk_fragment = st.sampled_from([
    "pytest", "go test", "npm test", "python3 -m pytest", IMPL_FILE, "directives.go", "tests/",
    TEST_COMMAND, "&&", "||", ";", "|", "\n", "cd", "'", '"', "`", ":", "=", "--collect-only",
    "../", "./", "~", "*", "\\", "\x00", " ", "config.go",
])
junk_text = st.one_of(
    st.text(max_size=60),
    st.lists(junk_fragment, max_size=12).map(" ".join),
    st.lists(junk_fragment, max_size=12).map("".join),
)
junk_value = st.one_of(
    st.none(), st.integers(), st.booleans(), st.floats(allow_nan=False, allow_infinity=False), junk_text,
    st.lists(st.one_of(junk_text, st.integers()), max_size=3),
    st.dictionaries(st.text(max_size=5), st.integers(), max_size=2),
)
AGENT_CHOICES = st.one_of(
    st.sampled_from(["test-implementer", "implementer", "", "test-verifier"]), junk_value)
TOOL_CHOICES = st.one_of(
    st.sampled_from(["Bash", "Read", "Grep", "Glob", "LS", "Agent", "Task", "Write", ""]), junk_value)
TOOL_INPUT_CHOICES = st.one_of(
    junk_value,
    st.dictionaries(
        st.sampled_from(["command", "file_path", "path", "pattern", "glob", "subagent_type", "prompt", "x"]),
        st.one_of(junk_value, st.sampled_from(["test-implementer", "implementer"])),
        max_size=5),
)
PAYLOADS = st.fixed_dictionaries(
    {"tool_input": TOOL_INPUT_CHOICES},
    optional={"agent_type": AGENT_CHOICES, "tool_name": TOOL_CHOICES, "cwd": junk_value,
              "session_id": junk_value, "tool_use_id": junk_value, "agent_id": junk_value},
)
HYPOTHESIS_SETTINGS = dict(database=None, deadline=None,
                           suppress_health_check=list(HealthCheck))


class TestO7ErrorGuessingAndRandom(HookCase):
    def run_raw(self, stdin, env=None):
        return subprocess.run(
            [sys.executable, str(self.repo / ".harness" / "hooks" / "telemetry_hook.py")],
            input=stdin, capture_output=True, text=True, env=env or self.env)

    def test_e1_non_json_stdin(self):
        for stdin in ("not json", "", "{", "[1, 2"):
            with self.subTest(stdin=stdin):
                self.assert_silent_success(self.run_raw(stdin))
        self.assertEqual(self.read_events(self.telemetry_dir, self.repo), [])

    def test_e2_tool_input_not_a_dict(self):
        for value in ([], ["a/b"], "pkg/directives.go", 5, None):
            with self.subTest(tool_input=value):
                payload = pre_tool_use("test-implementer", "Bash", value, str(self.repo))
                self.assert_silent_success(self.fire(payload))
        self.assertEqual(self.candidates(), [])

    def test_e3_command_is_an_int(self):
        for tool, key in (("Bash", "command"), ("Read", "file_path"), ("Agent", "prompt")):
            with self.subTest(tool=tool):
                tool_input = {key: 12345}
                if tool == "Agent":
                    tool_input["subagent_type"] = "test-implementer"
                agent = None if tool == "Agent" else "test-implementer"
                self.assert_silent_success(self.fire(pre_tool_use(agent, tool, tool_input, str(self.repo))))
        self.assertEqual(self.candidates(), [])

    def test_e4_spec_unreadable_or_malformed(self):
        (self.specs / "iso.md").unlink()
        (self.specs / "x.md").mkdir()
        (self.specs / "binary.md").write_bytes(b"\xff\xfe\x00\x80---\nstatus: active\n")
        result = self.fire(self.ti("Read", {"file_path": IMPL_FILE}))
        self.assert_silent_success(result)
        result = self.fire(self.ti("Bash", {"command": "go test ./..."}))
        self.assert_silent_success(result)
        self.read_events(self.telemetry_dir, self.repo)  # every written line must be complete JSON

    @unittest.skipIf(hasattr(os, "geteuid") and os.geteuid() == 0, "root ignores chmod")
    def test_e4_chmod_zero_spec(self):
        spec = self.specs / "iso.md"
        spec.chmod(0)
        self.addCleanup(spec.chmod, 0o644)
        self.assert_silent_success(self.fire(self.ti("Read", {"file_path": IMPL_FILE})))

    def test_e4_detect_does_not_raise_on_unreadable_spec_dir_entries(self):
        self.assertIsNotNone(isolation, "harness/lib/isolation.py is not importable")
        (self.specs / "iso.md").unlink()
        (self.specs / "x.md").mkdir()
        (self.specs / "binary.md").write_bytes(b"\xff\xfe\x00\x80---\nstatus: active\n")
        results = isolation.detect(self.ti("Bash", {"command": "go test ./..."}), self.specs, self.repo)
        self.assertIsInstance(results, list)

    def test_e5_telemetry_dir_is_a_file(self):
        blocker = self.temp_dir() / "not-a-dir"
        blocker.write_text("regular file")
        env = self.telemetry_env(blocker)
        result = self.fire(self.ti("Read", {"file_path": IMPL_FILE}), env)
        self.assert_silent_success(result)
        self.assertEqual(blocker.read_text(), "regular file")

    def test_e6_detect_never_raises_on_generated_payloads(self):
        self.assertIsNotNone(isolation, "harness/lib/isolation.py is not importable")
        calls = []

        @seed(20261025)
        @settings(max_examples=200, **HYPOTHESIS_SETTINGS)
        @given(PAYLOADS)
        def check(payload):
            calls.append(1)
            results = isolation.detect(payload, self.specs, self.repo)
            self.assertIsInstance(results, list)
            rules = [r["rule"] for r in results]
            self.assertEqual(len(rules), len(set(rules)))
            self.assertEqual(rules, sorted(rules, key=RULES.index))
            for item in results:
                self.assertEqual(set(item), CANDIDATE_KEYS)
                self.assertLessEqual(len(item["excerpt"]), 500)

        check()
        self.assertGreaterEqual(len(calls), 200)

    def test_e6_hook_process_exits_zero_and_prints_nothing_on_generated_payloads(self):
        calls = []

        @seed(20261026)
        @settings(max_examples=20, **HYPOTHESIS_SETTINGS)
        @given(PAYLOADS)
        def check(payload):
            calls.append(1)
            payload = dict(payload, hook_event_name="PreToolUse")
            result = self.fire(payload)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(result.stdout, "")

        check()
        self.assertGreaterEqual(len(calls), 20)


if __name__ == "__main__":
    unittest.main()

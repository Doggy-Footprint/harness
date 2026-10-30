"""Independent oracle for spec d63550ad0d3f333d v1 (per-version run metrics).

Expected values are hand-derived from the spec text (F1-F10, C1-C10); the
classifier is never reimplemented here. Unit tests import harness/lib directly
(so coverage of harness/lib is measured); integration tests run the installed
hooks as subprocesses against a temp repo with HARNESS_TELEMETRY_DIR set.
"""
import importlib
import json
import os
import statistics
import subprocess
import sys
import time
from pathlib import Path

import pytest
from hypothesis import given, seed, settings, strategies as st

from test_installer import REPO_ROOT, run_installer
from test_telemetry import HARNESS_VERSION, TelemetryTestCase

LIB = REPO_ROOT / "harness" / "lib"
ROOT = Path("/fake/repo")
ALLOWED_KINDS = {"explore", "code_write", "noncode_write", "unclassified_shell_write"}
MATCHER = "Bash|Write|Edit|NotebookEdit|Read|Grep|Glob|LS"
METRIC_FIELDS = {
    "exploration_before_code", "noncode_writes_before_code", "code_writes",
    "unclassified_shell_writes", "tool_calls", "first_code_write",
    "workflow_run_ids", "ended_cleanly",
}


def sm():
    """Import lazily so a missing module fails only the unit tests."""
    if str(LIB) not in sys.path:
        sys.path.insert(0, str(LIB))
    return importlib.import_module("session_metrics")


def kinds(tool, tool_input):
    return [k for k, _ in sm().classify_tool(tool, tool_input, ROOT)]


# --------------------------------------------------------------------- O1
CODE_EXTS = ".py .js .ts .tsx .jsx .go .rs .java .kt .c .cc .cpp .h .hpp .rb .php .swift .cs .scala .sh".split()


@pytest.mark.parametrize("ext", CODE_EXTS)
def test_o1_p1_code_extension_in_repo_is_code(ext):
    assert sm().classify_path(f"/fake/repo/src/a{ext}", ROOT) == "code"
    assert sm().classify_path(f"src/a{ext}", ROOT) == "code"


@pytest.mark.parametrize("name", ["README.md", "a.json", "a.txt", "a.yaml", "a.pyc", "a.py.txt", "a.html"])
def test_o1_p2_noncode_extension_is_noncode(name):
    assert sm().classify_path(f"/fake/repo/src/{name}", ROOT) == "noncode"


@pytest.mark.parametrize("prefix", ["agent-docs", ".harness", ".claude", ".codex", ".agents"])
def test_o1_p3_each_excluded_prefix_is_noncode(prefix):
    assert sm().classify_path(f"{prefix}/x.py", ROOT) == "noncode"
    assert sm().classify_path(f"/fake/repo/{prefix}/sub/x.py", ROOT) == "noncode"


@pytest.mark.parametrize("path", ["agent-docs-extra/a.py", "harness/hooks/y.py", "src/agent-docs/a.py"])
def test_o1_p3_prefix_must_be_a_leading_directory(path):
    assert sm().classify_path(path, ROOT) == "code"


@pytest.mark.parametrize("path", ["SRC/A.PY", "src/a.Py", "/fake/repo/src/B.TS"])
def test_o1_p4_uppercase_extension_is_code(path):
    assert sm().classify_path(path, ROOT) == "code"


@pytest.mark.parametrize("path", ["/elsewhere/a.py", "/elsewhere/agent-docs/x.py", "/elsewhere/.harness/y.sh"])
def test_o1_p5_outside_repo_code_extension_is_code_by_extension_only(path):
    assert sm().classify_path(path, ROOT) == "code"


def test_o1_p5_outside_repo_noncode_extension_is_noncode():
    assert sm().classify_path("/elsewhere/a.md", ROOT) == "noncode"


@pytest.mark.parametrize("path", ["Makefile", "/fake/repo/src/LICENSE", "/fake/repo/src/py"])
def test_o1_p6_no_extension_is_noncode(path):
    assert sm().classify_path(path, ROOT) == "noncode"


def test_c3_boundary_table():
    got = [sm().classify_path(p, ROOT) for p in
           ("agent-docs/x.py", ".harness/hooks/y.py", "harness/hooks/y.py", "SRC/A.PY")]
    assert got == ["noncode", "noncode", "code", "code"]


# --------------------------------------------------------------------- O2
@pytest.mark.parametrize("tool", ["Read", "Grep", "Glob", "LS"])
def test_o2_explore_tools(tool):
    assert sm().classify_tool(tool, {"file_path": "/fake/repo/src/a.py", "pattern": "x"}, ROOT) == [("explore", None)]


@pytest.mark.parametrize("tool,key", [("Write", "file_path"), ("Edit", "file_path"), ("NotebookEdit", "notebook_path")])
def test_o2_write_tools_classify_target_path(tool, key):
    assert kinds(tool, {key: "/fake/repo/src/a.py"}) == ["code_write"]
    assert kinds(tool, {key: "/fake/repo/docs/a.md"}) == ["noncode_write"]
    assert kinds(tool, {key: "/fake/repo/agent-docs/a.py"}) == ["noncode_write"]


@pytest.mark.parametrize("tool", ["Write", "Edit", "NotebookEdit"])
def test_o2_write_without_path_is_empty(tool):
    assert sm().classify_tool(tool, {}, ROOT) == []
    assert sm().classify_tool(tool, {"content": "x"}, ROOT) == []


def test_o2_unknown_tool_is_empty():
    assert sm().classify_tool("WebFetch", {"url": "http://x"}, ROOT) == []
    assert sm().classify_tool("TodoWrite", {}, ROOT) == []


# --------------------------------------------------------------------- O3
BASH_CASES = [
    ("redirect_code", "echo x > src/b.py", ["code_write"]),  # C2
    ("redirect_noncode", "echo x > notes.md", ["noncode_write"]),
    ("append_code", "echo x >> src/c.rs", ["code_write"]),
    ("append_noncode", "echo x >> log.txt", ["noncode_write"]),
    ("tee_code", "echo x | tee out.py", ["code_write"]),
    ("tee_noncode", "echo x | tee out.md", ["noncode_write"]),
    ("tee_a", "echo x | tee -a log.txt", ["noncode_write"]),  # C10
    ("tee_a_code", "echo x | tee -a run.sh", ["code_write"]),
    ("sed_i", "sed -i 's/a/b/' x.go", ["code_write"]),
    ("sed_i_noncode", "sed -i 's/a/b/' x.md", ["noncode_write"]),
    ("sed_i_bak", "sed -i.bak 's/a/b/' x.go", ["code_write"]),  # C10
    ("sed_i_bak_noncode", "sed -i.bak 's/a/b/' x.txt", ["noncode_write"]),
    ("sed_no_inplace", "sed -n 's/a/b/p' x.go", ["explore"]),
    ("devnull_redirect", "ls > /dev/null", ["explore"]),  # C4
    ("devnull_stderr", "cat a 2>/dev/null", ["explore"]),  # C4
    ("devnull_stderr_space", "cat a 2> /dev/null", ["explore"]),
    ("devnull_amp", "make &> /dev/null", ["explore"]),
    ("python_c", "python -c \"print(1)\"", ["unclassified_shell_write"]),
    ("python3_c", "python3 -c \"open('a.py','w')\"", ["unclassified_shell_write"]),  # C5
    ("node_e", "node -e \"console.log(1)\"", ["unclassified_shell_write"]),
    ("perl_i", "perl -i -pe 's/a/b/' f.txt", ["unclassified_shell_write"]),
    ("perl_e", "perl -e 'print 1'", ["unclassified_shell_write"]),
    ("ruby_e", "ruby -e 'puts 1'", ["unclassified_shell_write"]),
    ("heredoc_no_target", "cat <<EOF\nhello\nEOF", ["unclassified_shell_write"]),
    ("heredoc_with_target", "cat <<EOF > notes.md\nhello\nEOF", ["noncode_write"]),  # C5
    ("heredoc_with_code_target", "cat <<EOF > src/n.py\nx\nEOF", ["code_write"]),
    ("target_beats_marker", "python3 -c 'print(1)' > out.py", ["code_write"]),
    ("marker_with_stderr_devnull", "python3 -c x 2>/dev/null", ["unclassified_shell_write"]),
    ("plain_ls", "ls -la", ["explore"]),
    ("plain_git", "git status", ["explore"]),
    ("plain_pytest", "python3 -m pytest tests", ["explore"]),
]


@pytest.mark.parametrize("command,expected", [c[1:] for c in BASH_CASES], ids=[c[0] for c in BASH_CASES])
def test_o3_bash_syntax(command, expected):
    assert kinds("Bash", {"command": command}) == expected


def test_o3_explore_result_carries_no_path():
    assert sm().classify_tool("Bash", {"command": "ls > /dev/null"}, ROOT) == [("explore", None)]
    assert sm().classify_tool("Bash", {"command": "python3 -c 'x'"}, ROOT) == [("unclassified_shell_write", None)]


def test_o3_multiple_targets_each_yield_a_write():
    assert sorted(kinds("Bash", {"command": "echo a > x.py && echo b >> y.md"})) == ["code_write", "noncode_write"]


def test_o3_code_target_in_excluded_prefix_is_noncode():
    assert kinds("Bash", {"command": "echo x > agent-docs/x.py"}) == ["noncode_write"]


# --------------------------------------------------------------------- O9
_TOKENS = [">", ">>", "tee", "-a", "sed", "-i", "-i.bak", "/dev/null", "2>", "&>", "python", "python3",
           "-c", "node", "-e", "perl", "ruby", "<<", "EOF", "a.py", "b.md", "'", '"', "\n", ";", "|", "&&", "\\", "x"]


@seed(10)
@settings(max_examples=500, deadline=None)
@given(st.one_of(st.text(), st.lists(st.sampled_from(_TOKENS), max_size=12).map(" ".join)))
def test_o9_bash_arbitrary_strings_never_raise_and_stay_in_allowed_kinds(command):
    result = sm().classify_tool("Bash", {"command": command}, ROOT)
    assert isinstance(result, list) and result
    for item in result:
        assert len(item) == 2
        assert item[0] in ALLOWED_KINDS


# ---------------------------------------------------- integration helpers
class MetricsCase(TelemetryTestCase):
    def setUp(self):
        self.repo, self.td = self.install_with_telemetry_dir()
        self.root = self.repo.resolve()
        self.env = self.telemetry_env(self.td)

    def hook(self, payload, raw=None, script="telemetry_hook.py", env=None):
        return subprocess.run(
            [sys.executable, str(self.repo / ".harness" / "hooks" / script)],
            input=raw if raw is not None else json.dumps(payload),
            capture_output=True, text=True, cwd=self.repo, env=env or self.env,
        )

    def tool(self, name, tool_input, sid="s1", event="PostToolUse"):
        result = self.hook({
            "hook_event_name": event, "session_id": sid,
            "transcript_path": "/x/.claude/projects/p/s.jsonl",
            "tool_name": name, "tool_input": tool_input, "tool_response": {},
        })
        self.assertEqual((result.returncode, result.stdout), (0, ""), result.stderr)
        return result

    def read(self, sid="s1"):
        return self.tool("Read", {"file_path": str(self.root / "src" / "a.py")}, sid)

    def write(self, rel, sid="s1", tool="Write"):
        return self.tool(tool, {"file_path": str(self.root / rel)}, sid)

    def bash(self, command, sid="s1"):
        return self.tool("Bash", {"command": command}, sid)

    def end(self, sid="s1"):
        result = self.hook({"hook_event_name": "SessionEnd", "session_id": sid})
        self.assertEqual((result.returncode, result.stdout), (0, ""), result.stderr)
        return result

    def start(self, sid):
        result = self.hook({"hook_event_name": "SessionStart", "session_id": sid}, script="session_lock.py")
        self.assertEqual((result.returncode, result.stdout), (0, ""), result.stderr)
        return result

    def metrics(self):
        return [e for e in self.read_events(self.td, self.repo) if e.get("event") == "session_metrics"]

    def state_files(self):
        return {p for p in self.td.rglob("*")
                if p.is_file() and p.suffix != ".jsonl" and not p.name.endswith(".session-lock")}

    def marker(self, *args):
        result = subprocess.run(
            [sys.executable, str(self.repo / ".harness" / "bin" / "workflow_marker.py"), *args],
            cwd=self.repo, env=self.env, capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def counters(self, event):
        return {k: event[k] for k in METRIC_FIELDS - {"workflow_run_ids"}}


# --------------------------------------------------------------------- O4
class TestConcurrentRecord(MetricsCase):
    def test_parallel_post_tool_use_hooks_lose_no_increments(self):
        payload = json.dumps({
            "hook_event_name": "PostToolUse", "session_id": "par",
            "transcript_path": "/x/.claude/projects/p/s.jsonl",
            "tool_name": "Read", "tool_input": {"file_path": str(self.root / "src" / "a.py")}, "tool_response": {},
        })
        procs = [
            subprocess.Popen([sys.executable, str(self.repo / ".harness" / "hooks" / "telemetry_hook.py")],
                             stdin=subprocess.PIPE, stdout=subprocess.PIPE, cwd=self.repo, env=self.env, text=True)
            for _ in range(20)
        ]
        for proc in procs:
            proc.stdin.write(payload)
            proc.stdin.close()
        for proc in procs:
            self.assertEqual(proc.wait(timeout=60), 0)
            self.assertEqual(proc.stdout.read(), "")
            proc.stdout.close()
        self.end("par")
        [event] = self.metrics()
        self.assertEqual((event["tool_calls"], event["exploration_before_code"]), (20, 20))


class TestO4Scenarios(MetricsCase):
    def test_c1_sequence_exact_fields_and_state_removed(self):
        baseline = self.state_files()
        self.read()
        self.tool("Grep", {"pattern": "x"})
        self.write("README.md")
        self.write("src/a.py", tool="Edit")
        self.read()
        self.assertEqual(self.metrics(), [])
        self.assertNotEqual(self.state_files(), baseline)

        self.end()

        events = self.metrics()
        self.assertEqual(len(events), 1, events)
        event = events[0]
        self.assertEqual(self.counters(event), {
            "exploration_before_code": 2, "noncode_writes_before_code": 1, "code_writes": 1,
            "unclassified_shell_writes": 0, "tool_calls": 5, "first_code_write": True, "ended_cleanly": True,
        })
        self.assertEqual(event["session_id"], "s1")
        self.assertEqual(event["repo"], str(self.root))
        self.assertEqual(event["harness_version"], HARNESS_VERSION)
        self.assertIn("client", event)
        self.assertIsInstance(event["workflow_run_ids"], list)
        self.assertNotIn(None, event["workflow_run_ids"])
        self.assertEqual(self.state_files(), baseline)

    def test_c9_session_without_code_write(self):
        self.read()
        self.write("README.md")
        self.write("notes.txt")
        self.end()
        event = self.metrics()[0]
        self.assertEqual(self.counters(event), {
            "exploration_before_code": 1, "noncode_writes_before_code": 2, "code_writes": 0,
            "unclassified_shell_writes": 0, "tool_calls": 3, "first_code_write": False, "ended_cleanly": True,
        })

    def test_write_before_any_explore(self):
        self.write("src/a.py")
        self.write("README.md")
        self.read()
        self.end()
        self.assertEqual(self.counters(self.metrics()[0]), {
            "exploration_before_code": 0, "noncode_writes_before_code": 0, "code_writes": 1,
            "unclassified_shell_writes": 0, "tool_calls": 3, "first_code_write": True, "ended_cleanly": True,
        })

    def test_bash_kinds_feed_counters(self):
        self.bash("ls -la")
        self.bash("echo x > notes.md")
        self.bash("python3 -c \"open('a.py','w')\"")
        self.bash("echo x > src/b.py")
        self.bash("ls")
        self.end()
        self.assertEqual(self.counters(self.metrics()[0]), {
            "exploration_before_code": 1, "noncode_writes_before_code": 1, "code_writes": 1,
            "unclassified_shell_writes": 1, "tool_calls": 5, "first_code_write": True, "ended_cleanly": True,
        })

    def test_multiple_code_writes_and_unclassified_writes_counted_plainly(self):
        self.bash("python3 -c 'x'")
        self.write("src/a.py")
        self.write("src/b.go", tool="Edit")
        self.write("src/c.rs")
        self.bash("node -e 'x'")
        self.bash("cat <<EOF\nhi\nEOF")
        self.end()
        self.assertEqual(self.counters(self.metrics()[0]), {
            "exploration_before_code": 0, "noncode_writes_before_code": 0, "code_writes": 3,
            "unclassified_shell_writes": 3, "tool_calls": 6, "first_code_write": True, "ended_cleanly": True,
        })

    def test_bash_with_two_code_targets_is_one_tool_call_and_two_code_writes(self):
        self.bash("echo a > a.py && echo b > b.py")
        self.end()
        self.assertEqual(self.counters(self.metrics()[0]), {
            "exploration_before_code": 0, "noncode_writes_before_code": 0, "code_writes": 2,
            "unclassified_shell_writes": 0, "tool_calls": 1, "first_code_write": True, "ended_cleanly": True,
        })

    def test_bash_with_two_noncode_targets_before_code_counts_each(self):
        self.bash("echo a > a.md && echo b >> b.txt")
        self.end()
        self.assertEqual(self.counters(self.metrics()[0]), {
            "exploration_before_code": 0, "noncode_writes_before_code": 2, "code_writes": 0,
            "unclassified_shell_writes": 0, "tool_calls": 1, "first_code_write": False, "ended_cleanly": True,
        })

    def test_unrecognised_write_tool_path_counts_tool_call_only(self):
        self.tool("Write", {})
        self.end()
        event = self.metrics()[0]
        self.assertEqual((event["tool_calls"], event["code_writes"], event["exploration_before_code"],
                          event["noncode_writes_before_code"]), (1, 0, 0, 0))

    def test_sessions_are_isolated_by_session_id(self):
        self.read("sa")
        self.read("sb")
        self.write("src/a.py", "sb")
        self.end("sb")
        events = self.metrics()
        self.assertEqual([e["session_id"] for e in events], ["sb"])
        self.assertEqual((events[0]["tool_calls"], events[0]["code_writes"]), (2, 1))
        self.end("sa")
        by_session = {e["session_id"]: e for e in self.metrics()}
        self.assertEqual((by_session["sa"]["tool_calls"], by_session["sa"]["code_writes"]), (1, 0))

    def test_exactly_one_event_and_second_end_emits_nothing(self):
        self.read()
        self.end()
        self.end()
        self.assertEqual(len(self.metrics()), 1)

    def test_session_end_without_state_emits_nothing(self):
        self.end("never-recorded")
        self.assertEqual(self.metrics(), [])

    def test_run_id_deduplicated_with_active_workflow(self):
        self.marker("start", "--run-id", "run-1", "--spec", "s", "--spec-version", "1")
        baseline = self.state_files()
        self.read()
        self.write("src/a.py")
        self.read()
        self.end()
        event = self.metrics()[0]
        self.assertEqual(event["workflow_run_ids"], ["run-1"])
        self.assertEqual(event["tool_calls"], 3)
        self.assertEqual(self.state_files(), baseline)

    def test_two_runs_in_one_session_are_both_recorded_once(self):
        self.marker("start", "--run-id", "run-1", "--spec", "s", "--spec-version", "1")
        self.read()
        self.read()
        self.marker("end", "--run-id", "run-1", "--status", "complete")
        self.marker("start", "--run-id", "run-2", "--spec", "s", "--spec-version", "1")
        self.read()
        self.read()
        self.end()
        self.assertEqual(sorted(self.metrics()[0]["workflow_run_ids"]), ["run-1", "run-2"])


# --------------------------------------------------------------------- O5
class TestO5Orphans(MetricsCase):
    def test_c7_orphan_flushed_unclean_and_own_session_untouched(self):
        baseline = self.state_files()
        self.read("A")
        self.write("README.md", "A")
        self.write("src/a.py", "A")
        a_files = self.state_files() - baseline
        self.assertTrue(a_files)

        result = self.start("B")

        self.assertEqual(result.stdout, "")
        events = self.metrics()
        self.assertEqual(len(events), 1, events)
        self.assertEqual(events[0]["session_id"], "A")
        self.assertEqual(self.counters(events[0]), {
            "exploration_before_code": 1, "noncode_writes_before_code": 1, "code_writes": 1,
            "unclassified_shell_writes": 0, "tool_calls": 3, "first_code_write": True, "ended_cleanly": False,
        })
        self.assertEqual(self.state_files(), baseline)
        self.assertEqual([e for e in events if e["session_id"] == "B"], [])

    def test_own_session_state_not_flushed_and_survives_to_session_end(self):
        baseline = self.state_files()
        self.read("B")
        b_files = self.state_files() - baseline
        self.start("B")
        self.assertEqual(self.metrics(), [])
        self.assertEqual(self.state_files() - baseline, b_files)
        self.end("B")
        events = self.metrics()
        self.assertEqual([(e["session_id"], e["ended_cleanly"], e["tool_calls"]) for e in events], [("B", True, 1)])

    def test_no_state_emits_nothing(self):
        self.start("B")
        self.assertEqual(self.metrics(), [])

    def test_multiple_orphans_all_flushed_once_and_second_start_is_noop(self):
        self.read("A")
        self.read("C")
        self.start("B")
        self.start("B")
        self.assertEqual(sorted(e["session_id"] for e in self.metrics()), ["A", "C"])
        self.assertTrue(all(e["ended_cleanly"] is False for e in self.metrics()))


class TestO5OrphanIdentity(MetricsCase):
    def test_orphan_with_unsafe_long_session_id_flushed_with_exact_id(self):
        sid = "a/b:c\\d " + "x" * 220
        self.read(sid)
        self.start("B")
        events = self.metrics()
        self.assertEqual([e["session_id"] for e in events], [sid])
        self.assertIs(events[0]["ended_cleanly"], False)
        self.assertEqual(events[0]["tool_calls"], 1)

    def test_two_ids_sharing_a_long_prefix_stay_distinct(self):
        prefix = "p" * 250
        self.read(prefix + "1")
        self.read(prefix + "2")
        self.start("B")
        self.assertEqual(sorted(e["session_id"] for e in self.metrics()), [prefix + "1", prefix + "2"])

    def test_orphan_with_active_workflow_run_carries_run_ids(self):
        self.marker("start", "--run-id", "run-9", "--spec", "s", "--spec-version", "1")
        self.read("A")
        self.read("A")
        self.start("B")
        events = self.metrics()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["workflow_run_ids"], ["run-9"])


# --------------------------------------------------------------------- O6
class TestO6ExistingEvents(MetricsCase):
    def test_spec_write_and_test_command_emitted_once_alongside_counting(self):
        spec = self.write_spec(self.repo, name="x", version=3, test_command="python3 -m unittest")
        self.tool("Write", {"file_path": str(spec.resolve())})
        self.bash("python3 -m unittest")
        self.end()
        events = self.read_events(self.td, self.repo)
        names = [e["event"] for e in events]
        self.assertEqual(names.count("spec_write"), 1, names)
        self.assertEqual(names.count("test_command"), 1, names)
        self.assertEqual(names.count("session_metrics"), 1, names)
        self.assertEqual(next(e for e in events if e["event"] == "spec_write")["version"], 3)
        self.assertEqual(self.metrics()[0]["tool_calls"], 2)


# --------------------------------------------------------------------- O7
class TestO7Errors(MetricsCase):
    def assertSilent(self, result):
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "")

    def test_c6_invalid_json_stdin(self):
        for raw in ("not json", "", "{", "[1,2"):
            with self.subTest(raw=raw):
                self.assertSilent(self.hook(None, raw=raw))
        self.assertEqual(self.read_events(self.td, self.repo), [])
        self.assertEqual(self.state_files(), set())

    def test_c6_corrupt_state_overwritten_on_next_record(self):
        self.read()
        (state,) = self.state_files()
        state.write_text("{not json")
        self.read()
        self.end()
        events = self.metrics()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["tool_calls"], 1)

    def test_c6_corrupt_state_flush_on_session_end_deletes_and_emits_nothing(self):
        self.read()
        (state,) = self.state_files()
        state.write_text("{not json")
        self.assertSilent(self.hook({"hook_event_name": "SessionEnd", "session_id": "s1"}))
        self.assertEqual(self.metrics(), [])
        self.assertEqual(self.state_files(), set())

    def test_c6_corrupt_state_flush_on_session_start_deletes_and_emits_nothing(self):
        self.read("A")
        (state,) = self.state_files()
        state.write_text("\x00\xff garbage")
        self.start("B")
        self.assertEqual(self.metrics(), [])
        self.assertEqual(self.state_files(), set())

    def test_unwritable_telemetry_dir(self):
        blocked = self.temp_dir() / "not-a-dir"
        blocked.write_text("regular file")
        env = self.telemetry_env(blocked)
        payload = {"hook_event_name": "PostToolUse", "session_id": "s1", "tool_name": "Read",
                   "tool_input": {"file_path": "/x/a.py"}, "tool_response": {}}
        self.assertSilent(self.hook(payload, env=env))
        self.assertSilent(self.hook({"hook_event_name": "SessionEnd", "session_id": "s1"}, env=env))
        self.assertSilent(self.hook(payload, env=env))
        self.assertSilent(self.hook({"hook_event_name": "SessionStart", "session_id": "s2"},
                                    script="session_lock.py", env=env))
        self.assertTrue(blocked.is_file())

    def test_valid_json_with_odd_shapes_exits_0_silently(self):
        shapes = [
            [1, 2], "str", 5, None,
            {"hook_event_name": "PostToolUse", "session_id": "s1", "tool_name": "Bash", "tool_input": None},
            {"hook_event_name": "PostToolUse", "session_id": "s1", "tool_name": "Bash", "tool_input": "ls"},
            {"hook_event_name": "PostToolUse", "session_id": "s1", "tool_name": "Write", "tool_input": []},
            {"hook_event_name": "PostToolUse", "session_id": "s1", "tool_name": "Bash", "tool_input": {"command": 5}},
            {"hook_event_name": "PostToolUse", "session_id": 7, "tool_name": "Read", "tool_input": {}},
        ]
        for shape in shapes:
            with self.subTest(shape=shape):
                self.assertSilent(self.hook(shape))
        self.assertSilent(self.hook({"hook_event_name": "SessionEnd", "session_id": "s1"}))

    def test_missing_session_id_is_ignored(self):
        baseline = self.state_files()
        result = self.hook({"hook_event_name": "PostToolUse", "tool_name": "Read",
                            "tool_input": {"file_path": "/x/a.py"}, "tool_response": {}})
        self.assertSilent(result)
        self.assertSilent(self.hook({"hook_event_name": "SessionEnd"}))
        self.assertEqual(self.state_files(), baseline)
        self.assertEqual(self.metrics(), [])


# -------------------------------------------------------------------- O10
class TestO10Performance(MetricsCase):
    def test_q1_read_payload_median_wall_time_at_most_250ms(self):
        payload = json.dumps({
            "hook_event_name": "PostToolUse", "session_id": "perf",
            "transcript_path": "/x/.claude/projects/p/s.jsonl", "tool_name": "Read",
            "tool_input": {"file_path": str(self.root / "src" / "a.py")}, "tool_response": {},
        })
        script = str(self.repo / ".harness" / "hooks" / "telemetry_hook.py")
        samples = []
        for _ in range(20):
            started = time.perf_counter()
            result = subprocess.run([sys.executable, script], input=payload, capture_output=True,
                                    text=True, cwd=self.repo, env=self.env)
            samples.append((time.perf_counter() - started) * 1000)
            self.assertEqual((result.returncode, result.stdout), (0, ""))
        self.assertLessEqual(statistics.median(samples), 250, sorted(samples))


# -------------------------------------------------------------------- O11
class TestO11Packaging(MetricsCase):
    def hooks(self):
        return json.loads((self.repo / ".claude" / "settings.json").read_text())["hooks"]

    def test_version_is_0_26_0(self):
        self.assertEqual((REPO_ROOT / "harness" / "VERSION").read_text().strip(), "0.34.0")

    def test_installed_post_tool_use_matcher(self):
        groups = [g for g in self.hooks()["PostToolUse"] if "telemetry_hook.py" in self.commands([g])[0]]
        self.assertEqual([g.get("matcher") for g in groups], [MATCHER])

    def test_installed_session_end_runs_telemetry_hook(self):
        self.assertIn("telemetry_hook.py", "\n".join(self.commands(self.hooks()["SessionEnd"])))

    def test_installed_session_start_still_runs_session_lock_without_matcher(self):
        groups = [g for g in self.hooks()["SessionStart"]
                  if "matcher" not in g and "session_lock.py" in self.commands([g])[0]]
        self.assertEqual(len(groups), 1)

    def test_migration_0_24_0_announced_with_non_empty_steps(self):
        manifest_path = self.repo / ".harness" / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["version"] = "0.23.0"
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
        result = run_installer("update", str(self.repo), "--dry-run")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        lines = result.stdout.splitlines()
        header = "migration 0.24.0: record per-session run metrics in telemetry"
        self.assertIn(header, lines)
        steps = []
        for line in lines[lines.index(header) + 1:]:
            if not line.startswith("- "):
                break
            if "confirmation required" not in line:
                steps.append(line)
        self.assertTrue(steps, result.stdout)


# ------------------------------------------- in-process lifecycle (coverage)
def _inprocess_events(tmp_path):
    return [json.loads(line) for p in tmp_path.glob("*.jsonl") for line in p.read_text().splitlines() if line.strip()]


def _post(sid, tool, tool_input):
    return {"hook_event_name": "PostToolUse", "session_id": sid, "transcript_path": "/x/.claude/projects/p/s.jsonl",
            "tool_name": tool, "tool_input": tool_input, "tool_response": {}}


def test_inprocess_record_flush_lifecycle(tmp_path, monkeypatch):
    monkeypatch.setenv("HARNESS_TELEMETRY_DIR", str(tmp_path))
    module = sm()
    module.record(_post("L1", "Read", {"file_path": "/elsewhere/a.py"}))
    module.record(_post("L1", "Write", {"file_path": "/elsewhere/a.md"}))
    module.record(_post("L1", "Write", {"file_path": "/elsewhere/a.py"}))
    module.record(_post("L1", "Bash", {"command": "python3 -c 'x'"}))
    module.record({"hook_event_name": "PostToolUse", "tool_name": "Read", "tool_input": {}})
    module.flush({"hook_event_name": "SessionEnd", "session_id": "L1"}, True)
    module.flush({"hook_event_name": "SessionEnd", "session_id": "L1"}, True)
    events = [e for e in _inprocess_events(tmp_path) if e["event"] == "session_metrics"]
    assert len(events) == 1
    assert {k: events[0][k] for k in METRIC_FIELDS - {"workflow_run_ids"}} == {
        "exploration_before_code": 1, "noncode_writes_before_code": 1, "code_writes": 1,
        "unclassified_shell_writes": 1, "tool_calls": 4, "first_code_write": True, "ended_cleanly": True}


def test_inprocess_flush_orphans_skips_current_and_flushes_others(tmp_path, monkeypatch):
    monkeypatch.setenv("HARNESS_TELEMETRY_DIR", str(tmp_path))
    module = sm()
    module.record(_post("A", "Grep", {"pattern": "x"}))
    module.record(_post("B", "Glob", {"pattern": "x"}))
    module.flush_orphans("B")
    events = [e for e in _inprocess_events(tmp_path) if e["event"] == "session_metrics"]
    assert [(e["session_id"], e["ended_cleanly"]) for e in events] == [("A", False)]
    module.flush_orphans(None)
    events = [e for e in _inprocess_events(tmp_path) if e["event"] == "session_metrics"]
    assert sorted((e["session_id"], e["ended_cleanly"]) for e in events) == [("A", False), ("B", False)]

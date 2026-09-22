"""Independent oracle for agent-docs/specs/telemetry-markers.md (v1).

Derived only from the spec text; the implementation is never read. Tests
run the installed hooks/lib as subprocesses against a temp repo and inspect
the resulting ~/.harness/telemetry/<repo-slug>.jsonl style file (redirected
via HARNESS_TELEMETRY_DIR).
"""
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from test_installer import InstallerTestCase, run_installer

REPO_ROOT = Path(__file__).resolve().parents[1]
HARNESS_VERSION = (REPO_ROOT / "harness" / "VERSION").read_text().strip()


def repo_slug(repo):
    return re.sub(r"[^A-Za-z0-9]", "-", str(repo.resolve()))


class TelemetryTestCase(InstallerTestCase):
    def temp_dir(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        return Path(tmp.name)

    def install_with_telemetry_dir(self):
        repo = self.install()
        telemetry_dir = self.temp_dir()
        return repo, telemetry_dir

    def telemetry_env(self, telemetry_dir, extra=None):
        env = dict(os.environ)
        env["HARNESS_TELEMETRY_DIR"] = str(telemetry_dir)
        if extra:
            env.update(extra)
        return env

    def run_hook_env(self, repo, script, payload, env):
        return subprocess.run(
            [sys.executable, str(repo / ".harness" / "hooks" / script)],
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            env=env,
        )

    def read_events(self, telemetry_dir, repo):
        events = []
        for path in telemetry_dir.glob("*.jsonl"):
            events.extend(
                event
                for line in path.read_text().splitlines()
                if line.strip()
                for event in (json.loads(line),)
                if event.get("repo") == str(repo.resolve())
            )
        return events

    def write_spec(self, repo, name="sample", version=None, test_command="python3 -m unittest"):
        specs_dir = repo / "agent-docs" / "specs"
        specs_dir.mkdir(parents=True, exist_ok=True)
        frontmatter = f"---\nversion: {version}\n---\n" if version is not None else ""
        body = f"{frontmatter}\n# Paths\nTest command: {test_command}\n"
        path = specs_dir / f"{name}.md"
        path.write_text(body)
        return path

    def write_handoff(self, repo, filename="0123456789abcdef-y.md"):
        handoff_dir = repo / "agent-docs" / "handoff"
        handoff_dir.mkdir(parents=True, exist_ok=True)
        path = handoff_dir / filename
        path.write_text("# Y\n")
        return path

    def post_tool_use_bash(self, command, exit_code=0, transcript_path=None):
        payload = {
            "hook_event_name": "PostToolUse",
            "tool_name": "Bash",
            "tool_input": {"command": command},
            "tool_response": {"exit_code": exit_code},
            "session_id": "s1",
            "tool_use_id": "t1",
        }
        if transcript_path is not None:
            payload["transcript_path"] = transcript_path
        return payload

    def find_matcher(self, groups, command_substr):
        for group in groups:
            commands = self.commands([group])
            if any(command_substr in c for c in commands):
                return group.get("matcher", "")
        return None

    def post_tool_use_write(self, file_path, transcript_path=None):
        payload = {
            "hook_event_name": "PostToolUse",
            "tool_name": "Write",
            "tool_input": {"file_path": str(file_path)},
            "tool_response": {},
            "session_id": "s1",
            "tool_use_id": "t1",
        }
        if transcript_path is not None:
            payload["transcript_path"] = transcript_path
        return payload


class TestNormal(TelemetryTestCase):
    def test_c1_subagent_start_then_stop_recorded_and_gate_exits_0(self):
        repo, telemetry_dir = self.install_with_telemetry_dir()
        env = self.telemetry_env(telemetry_dir)

        start = self.run_hook_env(
            repo,
            "spec_gate.py",
            {"hook_event_name": "SubagentStart", "agent_type": "implementer", "agent_id": "a1"},
            env,
        )
        stop = self.run_hook_env(
            repo,
            "spec_gate.py",
            {"hook_event_name": "SubagentStop", "agent_type": "implementer", "agent_id": "a1"},
            env,
        )

        self.assertEqual(start.returncode, 0, start.stdout + start.stderr)
        self.assertEqual(stop.returncode, 0, stop.stdout + stop.stderr)
        events = self.read_events(telemetry_dir, repo)
        self.assertEqual(len(events), 2, events)
        self.assertEqual(events[0]["event"], "subagent_start")
        self.assertEqual(events[0]["agent_type"], "implementer")
        self.assertEqual(events[0]["agent_id"], "a1")
        self.assertEqual(events[1]["event"], "subagent_stop")
        self.assertEqual(events[1]["agent_type"], "implementer")
        self.assertEqual(events[1]["agent_id"], "a1")

    def test_c2_subagent_start_for_non_gated_agent_type_is_recorded(self):
        repo, telemetry_dir = self.install_with_telemetry_dir()
        env = self.telemetry_env(telemetry_dir)

        result = self.run_hook_env(
            repo,
            "spec_gate.py",
            {"hook_event_name": "SubagentStart", "agent_type": "test-verifier", "agent_id": "a2"},
            env,
        )

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        events = self.read_events(telemetry_dir, repo)
        self.assertEqual(len(events), 1, events)
        self.assertEqual(events[0]["event"], "subagent_start")
        self.assertEqual(events[0]["agent_type"], "test-verifier")

    def test_c3_test_command_bash_records_null_spec_without_active_marker_and_exit_code(self):
        repo, telemetry_dir = self.install_with_telemetry_dir()
        self.write_spec(repo, name="sample", test_command="python3 -m unittest")
        env = self.telemetry_env(telemetry_dir)

        result = self.run_hook_env(
            repo,
            "telemetry_hook.py",
            self.post_tool_use_bash("python3  -m unittest", exit_code=1),
            env,
        )

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stdout, "")
        events = self.read_events(telemetry_dir, repo)
        self.assertEqual(len(events), 1, events)
        self.assertEqual(events[0]["event"], "test_command")
        self.assertIsNone(events[0]["spec"])
        self.assertEqual(events[0]["exit_code"], 1)

    def test_c3_matches_correct_spec_created_alpha_then_beta(self):
        repo, telemetry_dir = self.install_with_telemetry_dir()
        self.write_spec(repo, name="alpha", test_command="python3 -m pytest tests/alpha")
        self.write_spec(repo, name="beta", test_command="python3 -m pytest tests/beta")
        env = self.telemetry_env(telemetry_dir)

        beta_result = self.run_hook_env(
            repo,
            "telemetry_hook.py",
            self.post_tool_use_bash("python3 -m pytest tests/beta", exit_code=0),
            env,
        )
        self.assertEqual(beta_result.returncode, 0, beta_result.stdout + beta_result.stderr)
        alpha_result = self.run_hook_env(
            repo,
            "telemetry_hook.py",
            self.post_tool_use_bash("python3 -m pytest tests/alpha", exit_code=0),
            env,
        )
        self.assertEqual(alpha_result.returncode, 0, alpha_result.stdout + alpha_result.stderr)

        events = self.read_events(telemetry_dir, repo)
        self.assertEqual(len(events), 2, events)
        self.assertIsNone(events[0]["spec"])
        self.assertIsNone(events[1]["spec"])

    def test_c3_matches_correct_spec_created_beta_then_alpha(self):
        repo, telemetry_dir = self.install_with_telemetry_dir()
        self.write_spec(repo, name="beta", test_command="python3 -m pytest tests/beta")
        self.write_spec(repo, name="alpha", test_command="python3 -m pytest tests/alpha")
        env = self.telemetry_env(telemetry_dir)

        alpha_result = self.run_hook_env(
            repo,
            "telemetry_hook.py",
            self.post_tool_use_bash("python3 -m pytest tests/alpha", exit_code=0),
            env,
        )
        self.assertEqual(alpha_result.returncode, 0, alpha_result.stdout + alpha_result.stderr)
        beta_result = self.run_hook_env(
            repo,
            "telemetry_hook.py",
            self.post_tool_use_bash("python3 -m pytest tests/beta", exit_code=0),
            env,
        )
        self.assertEqual(beta_result.returncode, 0, beta_result.stdout + beta_result.stderr)

        events = self.read_events(telemetry_dir, repo)
        self.assertEqual(len(events), 2, events)
        self.assertIsNone(events[0]["spec"])
        self.assertIsNone(events[1]["spec"])

    def test_c4_seed_bash_records_action_and_exit_code(self):
        repo, telemetry_dir = self.install_with_telemetry_dir()
        env = self.telemetry_env(telemetry_dir)

        result = self.run_hook_env(
            repo,
            "telemetry_hook.py",
            self.post_tool_use_bash(
                "python3 .harness/bin/seed.py backup src/a.py", exit_code=0
            ),
            env,
        )

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        events = self.read_events(telemetry_dir, repo)
        self.assertEqual(len(events), 1, events)
        self.assertEqual(events[0]["event"], "seed")
        self.assertEqual(events[0]["action"], "backup")
        self.assertEqual(events[0]["exit_code"], 0)

    def test_u4_nonzero_codex_bash_seed_records_action_and_exit_code(self):
        repo, telemetry_dir = self.install_with_telemetry_dir()
        env = self.telemetry_env(telemetry_dir)
        payload = self.post_tool_use_bash(
            "python3 .harness/bin/seed.py restore", exit_code=1
        )
        payload["transcript_path"] = "/tmp/.codex/sessions/session.jsonl"

        result = self.run_hook_env(repo, "telemetry_hook.py", payload, env)

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        events = self.read_events(telemetry_dir, repo)
        self.assertEqual(len(events), 1, events)
        self.assertEqual(events[0]["event"], "seed")
        self.assertEqual(events[0]["client"], "codex")
        self.assertEqual(events[0]["action"], "restore")
        self.assertEqual(events[0]["exit_code"], 1)

    def test_c5_spec_write_records_null_spec_without_active_marker_and_frontmatter_version(self):
        repo, telemetry_dir = self.install_with_telemetry_dir()
        spec = self.write_spec(repo, name="x", version=3)
        env = self.telemetry_env(telemetry_dir)

        result = self.run_hook_env(
            repo, "telemetry_hook.py", self.post_tool_use_write(spec), env
        )

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        events = self.read_events(telemetry_dir, repo)
        self.assertEqual(len(events), 1, events)
        self.assertEqual(events[0]["event"], "spec_write")
        self.assertIsNone(events[0]["spec"])
        self.assertEqual(events[0]["version"], 3)

    def test_c6_handoff_write_records_file_name(self):
        repo, telemetry_dir = self.install_with_telemetry_dir()
        handoff = self.write_handoff(repo, "0123456789abcdef-y.md")
        env = self.telemetry_env(telemetry_dir)

        result = self.run_hook_env(
            repo, "telemetry_hook.py", self.post_tool_use_write(handoff), env
        )

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        events = self.read_events(telemetry_dir, repo)
        self.assertEqual(len(events), 1, events)
        self.assertEqual(events[0]["event"], "handoff_write")
        self.assertEqual(events[0]["file"], "0123456789abcdef-y.md")

    def test_c7_gate_block_while_implementer_marker_running_exits_2(self):
        repo, telemetry_dir = self.install_with_telemetry_dir()
        self.write_spec(repo, name="sample", test_command="python3 -m unittest")
        env = self.telemetry_env(telemetry_dir)

        start = self.run_hook_env(
            repo,
            "spec_gate.py",
            {"hook_event_name": "SubagentStart", "agent_type": "implementer", "agent_id": "a1"},
            env,
        )
        self.assertEqual(start.returncode, 0, start.stdout + start.stderr)

        blocked = self.run_hook_env(
            repo,
            "spec_gate.py",
            {
                "hook_event_name": "PreToolUse",
                "tool_name": "Bash",
                "tool_input": {"command": "python3 -m unittest"},
            },
            env,
        )

        self.assertEqual(blocked.returncode, 2, blocked.stdout + blocked.stderr)
        self.assertIn("blocked", blocked.stderr.lower())
        self.assertIn("implementer", blocked.stderr.lower())
        events = self.read_events(telemetry_dir, repo)
        gate_events = [e for e in events if e["event"] == "gate_block"]
        self.assertEqual(len(gate_events), 1, events)
        self.assertEqual(gate_events[0]["running"], ["implementer"])

    def test_c7_gate_block_running_list_is_sorted(self):
        repo, telemetry_dir = self.install_with_telemetry_dir()
        self.write_spec(repo, name="sample", test_command="python3 -m unittest")
        env = self.telemetry_env(telemetry_dir)

        for agent_type, agent_id in (("test-implementer", "a2"), ("implementer", "a1")):
            start = self.run_hook_env(
                repo,
                "spec_gate.py",
                {"hook_event_name": "SubagentStart", "agent_type": agent_type, "agent_id": agent_id},
                env,
            )
            self.assertEqual(start.returncode, 0, start.stdout + start.stderr)

        blocked = self.run_hook_env(
            repo,
            "spec_gate.py",
            {
                "hook_event_name": "PreToolUse",
                "tool_name": "Bash",
                "tool_input": {"command": "python3 -m unittest"},
            },
            env,
        )

        self.assertEqual(blocked.returncode, 2, blocked.stdout + blocked.stderr)
        events = self.read_events(telemetry_dir, repo)
        gate_events = [e for e in events if e["event"] == "gate_block"]
        self.assertEqual(len(gate_events), 1, events)
        self.assertEqual(
            gate_events[0]["running"], sorted(["test-implementer", "implementer"])
        )

    def test_c8_codex_apply_patch_records_spec_write(self):
        repo, telemetry_dir = self.install_with_telemetry_dir()
        self.write_spec(repo, name="x", version=7)
        env = self.telemetry_env(telemetry_dir)
        payload = {
            "hook_event_name": "PostToolUse",
            "tool_name": "apply_patch",
            "tool_input": {
                "command": "*** Begin Patch\n*** Update File: agent-docs/specs/x.md\n*** End Patch\n"
            },
            "session_id": "s1",
        }

        result = self.run_hook_env(repo, "telemetry_hook.py", payload, env)

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        events = self.read_events(telemetry_dir, repo)
        self.assertEqual(len(events), 1, events)
        self.assertEqual(events[0]["event"], "spec_write")
        self.assertIsNone(events[0]["spec"])
        self.assertEqual(events[0]["version"], 7)

    def test_c21_tool_failure_matches_registered_spec_among_two(self):
        repo, telemetry_dir = self.install_with_telemetry_dir()
        self.write_spec(repo, name="alpha", test_command="python3 -m pytest tests/alpha")
        self.write_spec(repo, name="beta", test_command="python3 -m pytest tests/beta")
        env = self.telemetry_env(telemetry_dir)
        payload = {
            "hook_event_name": "PostToolUseFailure",
            "tool_name": "Bash",
            "tool_input": {"command": "python3 -m pytest tests/beta"},
            "error_code": "timeout",
            "session_id": "s1",
        }

        result = self.run_hook_env(repo, "telemetry_hook.py", payload, env)

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        events = self.read_events(telemetry_dir, repo)
        self.assertEqual(len(events), 1, events)
        self.assertEqual(events[0]["event"], "tool_failure")
        self.assertIsNone(events[0]["spec"])
        self.assertIsNone(events[0]["action"])

    def test_c21_tool_failure_matches_registered_spec_created_beta_then_alpha(self):
        repo, telemetry_dir = self.install_with_telemetry_dir()
        self.write_spec(repo, name="beta", test_command="python3 -m pytest tests/beta")
        self.write_spec(repo, name="alpha", test_command="python3 -m pytest tests/alpha")
        env = self.telemetry_env(telemetry_dir)
        payload = {
            "hook_event_name": "PostToolUseFailure",
            "tool_name": "Bash",
            "tool_input": {"command": "python3 -m pytest tests/alpha"},
            "error_code": "timeout",
            "session_id": "s1",
        }

        result = self.run_hook_env(repo, "telemetry_hook.py", payload, env)

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        events = self.read_events(telemetry_dir, repo)
        self.assertEqual(len(events), 1, events)
        self.assertEqual(events[0]["event"], "tool_failure")
        self.assertIsNone(events[0]["spec"])
        self.assertIsNone(events[0]["action"])

    def test_c22_tool_failure_for_seed_restore_records_action_not_spec(self):
        repo, telemetry_dir = self.install_with_telemetry_dir()
        env = self.telemetry_env(telemetry_dir)
        payload = {
            "hook_event_name": "PostToolUseFailure",
            "tool_name": "Bash",
            "tool_input": {"command": "python3 .harness/bin/seed.py restore"},
            "error_code": "timeout",
            "session_id": "s1",
        }

        result = self.run_hook_env(repo, "telemetry_hook.py", payload, env)

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        events = self.read_events(telemetry_dir, repo)
        self.assertEqual(len(events), 1, events)
        self.assertEqual(events[0]["event"], "tool_failure")
        self.assertEqual(events[0]["action"], "restore")
        self.assertIsNone(events[0]["spec"])

    def test_c22_tool_failure_seed_action_matches_seed_event_partition(self):
        cases = {
            "python3 .harness/bin/seed.py status": "status",
            "python3 .harness/bin/seed.py frobnicate x": "frobnicate",
            "python3 .harness/bin/seed.py": None,
        }
        for command, expected_action in cases.items():
            with self.subTest(command=command):
                repo, telemetry_dir = self.install_with_telemetry_dir()
                env = self.telemetry_env(telemetry_dir)
                payload = {
                    "hook_event_name": "PostToolUseFailure",
                    "tool_name": "Bash",
                    "tool_input": {"command": command},
                    "error_code": "timeout",
                    "session_id": "s1",
                }

                result = self.run_hook_env(repo, "telemetry_hook.py", payload, env)

                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                events = self.read_events(telemetry_dir, repo)
                self.assertEqual(len(events), 1, events)
                self.assertEqual(events[0]["event"], "tool_failure")
                self.assertEqual(events[0]["action"], expected_action)
                self.assertIsNone(events[0]["spec"])


class TestBoundary(TelemetryTestCase):
    def test_c9_unrelated_bash_command_writes_nothing(self):
        repo, telemetry_dir = self.install_with_telemetry_dir()
        env = self.telemetry_env(telemetry_dir)

        result = self.run_hook_env(
            repo, "telemetry_hook.py", self.post_tool_use_bash("ls"), env
        )

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.read_events(telemetry_dir, repo), [])

    def test_c9_near_miss_of_registered_test_command_writes_nothing(self):
        repo, telemetry_dir = self.install_with_telemetry_dir()
        self.write_spec(repo, name="sample", test_command="python3 -m unittest")
        env = self.telemetry_env(telemetry_dir)

        for command in ("python3 -m unittest -k x", "echo python3 -m unittest", "python3 -m unittes"):
            with self.subTest(command=command):
                result = self.run_hook_env(
                    repo, "telemetry_hook.py", self.post_tool_use_bash(command), env
                )
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.read_events(telemetry_dir, repo), [])

    def test_c10_write_to_non_spec_non_handoff_path_writes_nothing(self):
        repo, telemetry_dir = self.install_with_telemetry_dir()
        env = self.telemetry_env(telemetry_dir)
        other = repo / "src" / "app.py"
        other.parent.mkdir(parents=True, exist_ok=True)
        other.write_text("x = 1\n")

        result = self.run_hook_env(
            repo, "telemetry_hook.py", self.post_tool_use_write(other), env
        )

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.read_events(telemetry_dir, repo), [])

    def test_c10_write_to_handoff_index_writes_nothing(self):
        repo, telemetry_dir = self.install_with_telemetry_dir()
        env = self.telemetry_env(telemetry_dir)
        index = repo / "agent-docs" / "handoff" / "index.md"
        index.parent.mkdir(parents=True, exist_ok=True)
        index.write_text("")

        result = self.run_hook_env(
            repo, "telemetry_hook.py", self.post_tool_use_write(index), env
        )

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.read_events(telemetry_dir, repo), [])

    def test_c11_missing_exit_code_records_null(self):
        repo, telemetry_dir = self.install_with_telemetry_dir()
        env = self.telemetry_env(telemetry_dir)
        payload = {
            "hook_event_name": "PostToolUse",
            "tool_name": "Bash",
            "tool_input": {"command": "python3 .harness/bin/seed.py backup src/a.py"},
            "tool_response": {},
            "session_id": "s1",
        }

        result = self.run_hook_env(repo, "telemetry_hook.py", payload, env)

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        events = self.read_events(telemetry_dir, repo)
        self.assertEqual(len(events), 1, events)
        self.assertEqual(events[0]["event"], "seed")
        self.assertIsNone(events[0]["exit_code"])

    def test_c11_string_exit_code_records_null(self):
        repo, telemetry_dir = self.install_with_telemetry_dir()
        env = self.telemetry_env(telemetry_dir)
        payload = {
            "hook_event_name": "PostToolUse",
            "tool_name": "Bash",
            "tool_input": {"command": "python3 .harness/bin/seed.py backup src/a.py"},
            "tool_response": {"exit_code": "0"},
            "session_id": "s1",
        }

        result = self.run_hook_env(repo, "telemetry_hook.py", payload, env)

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        events = self.read_events(telemetry_dir, repo)
        self.assertEqual(len(events), 1, events)
        self.assertIsNone(events[0]["exit_code"])

    def test_c12_spec_write_without_frontmatter_version_records_null(self):
        repo, telemetry_dir = self.install_with_telemetry_dir()
        specs_dir = repo / "agent-docs" / "specs"
        specs_dir.mkdir(parents=True, exist_ok=True)
        spec = specs_dir / "noversion.md"
        spec.write_text("# Paths\nTest command: python3 -m unittest\n")
        env = self.telemetry_env(telemetry_dir)

        result = self.run_hook_env(
            repo, "telemetry_hook.py", self.post_tool_use_write(spec), env
        )

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        events = self.read_events(telemetry_dir, repo)
        self.assertEqual(len(events), 1, events)
        self.assertEqual(events[0]["event"], "spec_write")
        self.assertIsNone(events[0]["spec"])
        self.assertIsNone(events[0]["version"])

    def test_c13_default_telemetry_dir_is_under_home_harness_telemetry(self):
        repo = self.install()
        home_dir = self.temp_dir()
        lib_dir = repo / ".harness" / "lib"
        env = dict(os.environ)
        env.pop("HARNESS_TELEMETRY_DIR", None)
        env["HOME"] = str(home_dir)
        code = (
            "import sys; sys.path.insert(0, %r); import telemetry; "
            "print(telemetry.telemetry_file())" % str(lib_dir)
        )

        result = subprocess.run(
            [sys.executable, "-c", code], capture_output=True, text=True, env=env
        )

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        path = Path(result.stdout.strip())
        self.assertEqual(path.parent, home_dir / ".harness" / "telemetry")
        self.assertTrue(path.name.startswith(f"{repo_slug(repo)}-"), path)
        self.assertEqual(path.suffix, ".jsonl")

    def test_c14_client_field_from_transcript_path(self):
        repo, telemetry_dir = self.install_with_telemetry_dir()
        env = self.telemetry_env(telemetry_dir)
        cases = {
            "codex": "/home/user/.codex/projects/session.json",
            "claude": "/home/user/.claude/projects/session.json",
            None: None,
        }
        for expected_client, transcript_path in cases.items():
            with self.subTest(expected=expected_client):
                sub_repo, sub_dir = self.install_with_telemetry_dir()
                sub_env = self.telemetry_env(sub_dir)
                other = sub_repo / "src" / "app.py"
                other.parent.mkdir(parents=True, exist_ok=True)
                other.write_text("x = 1\n")
                self.write_spec(sub_repo, name="x", version=1)
                payload = self.post_tool_use_write(
                    sub_repo / "agent-docs" / "specs" / "x.md",
                    transcript_path=transcript_path,
                )
                result = self.run_hook_env(sub_repo, "telemetry_hook.py", payload, sub_env)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                events = self.read_events(sub_dir, sub_repo)
                self.assertEqual(len(events), 1, events)
                self.assertEqual(events[0].get("client"), expected_client)

    def test_c23_subagent_stop_empty_string_agent_type_records_null(self):
        repo, telemetry_dir = self.install_with_telemetry_dir()
        env = self.telemetry_env(telemetry_dir)

        result = self.run_hook_env(
            repo,
            "spec_gate.py",
            {"hook_event_name": "SubagentStop", "agent_type": "", "agent_id": "a1"},
            env,
        )

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        events = self.read_events(telemetry_dir, repo)
        self.assertEqual(len(events), 1, events)
        self.assertEqual(events[0]["event"], "subagent_stop")
        self.assertIsNone(events[0]["agent_type"])

    def test_c23_subagent_start_non_empty_agent_type_is_not_nulled(self):
        repo, telemetry_dir = self.install_with_telemetry_dir()
        env = self.telemetry_env(telemetry_dir)

        result = self.run_hook_env(
            repo,
            "spec_gate.py",
            {"hook_event_name": "SubagentStart", "agent_type": "implementer", "agent_id": "a1"},
            env,
        )

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        events = self.read_events(telemetry_dir, repo)
        self.assertEqual(len(events), 1, events)
        self.assertEqual(events[0]["agent_type"], "implementer")

    def test_c24_subagent_start_empty_string_agent_type_records_null(self):
        repo, telemetry_dir = self.install_with_telemetry_dir()
        env = self.telemetry_env(telemetry_dir)

        result = self.run_hook_env(
            repo,
            "spec_gate.py",
            {"hook_event_name": "SubagentStart", "agent_type": "", "agent_id": "a1"},
            env,
        )

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        events = self.read_events(telemetry_dir, repo)
        self.assertEqual(len(events), 1, events)
        self.assertEqual(events[0]["event"], "subagent_start")
        self.assertIsNone(events[0]["agent_type"])

    def test_c25_post_tool_use_failure_near_miss_of_registered_test_command_writes_nothing(self):
        repo, telemetry_dir = self.install_with_telemetry_dir()
        self.write_spec(repo, name="sample", test_command="python3 -m unittest")
        env = self.telemetry_env(telemetry_dir)

        for command in ("python3 -m unittest -k x", "echo python3 -m unittest", "python3 -m unittes"):
            with self.subTest(command=command):
                payload = {
                    "hook_event_name": "PostToolUseFailure",
                    "tool_name": "Bash",
                    "tool_input": {"command": command},
                    "error_code": "timeout",
                    "session_id": "s1",
                }
                result = self.run_hook_env(repo, "telemetry_hook.py", payload, env)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.read_events(telemetry_dir, repo), [])

    def test_c24_test_command_event_empty_string_agent_type_records_null(self):
        repo, telemetry_dir = self.install_with_telemetry_dir()
        self.write_spec(repo, name="sample", test_command="python3 -m unittest")
        env = self.telemetry_env(telemetry_dir)
        payload = self.post_tool_use_bash("python3  -m unittest", exit_code=1)
        payload["agent_type"] = ""

        result = self.run_hook_env(repo, "telemetry_hook.py", payload, env)

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        events = self.read_events(telemetry_dir, repo)
        self.assertEqual(len(events), 1, events)
        self.assertEqual(events[0]["event"], "test_command")
        self.assertIsNone(events[0]["agent_type"])

    def test_c24_tool_failure_event_empty_string_agent_type_records_null(self):
        repo, telemetry_dir = self.install_with_telemetry_dir()
        self.write_spec(repo, name="sample", test_command="python3 -m unittest")
        env = self.telemetry_env(telemetry_dir)
        payload = {
            "hook_event_name": "PostToolUseFailure",
            "tool_name": "Bash",
            "tool_input": {"command": "python3 -m unittest"},
            "error_code": "timeout",
            "session_id": "s1",
            "agent_type": "",
        }

        result = self.run_hook_env(repo, "telemetry_hook.py", payload, env)

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        events = self.read_events(telemetry_dir, repo)
        self.assertEqual(len(events), 1, events)
        self.assertEqual(events[0]["event"], "tool_failure")
        self.assertIsNone(events[0]["agent_type"])

    def test_c24_seed_event_empty_string_agent_type_records_null(self):
        repo, telemetry_dir = self.install_with_telemetry_dir()
        env = self.telemetry_env(telemetry_dir)
        payload = self.post_tool_use_bash(
            "python3 .harness/bin/seed.py backup src/a.py", exit_code=0
        )
        payload["agent_type"] = ""

        result = self.run_hook_env(repo, "telemetry_hook.py", payload, env)

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        events = self.read_events(telemetry_dir, repo)
        self.assertEqual(len(events), 1, events)
        self.assertEqual(events[0]["event"], "seed")
        self.assertIsNone(events[0]["agent_type"])

    def test_c24_spec_write_event_empty_string_agent_type_records_null(self):
        repo, telemetry_dir = self.install_with_telemetry_dir()
        spec = self.write_spec(repo, name="x", version=3)
        env = self.telemetry_env(telemetry_dir)
        payload = self.post_tool_use_write(spec)
        payload["agent_type"] = ""

        result = self.run_hook_env(repo, "telemetry_hook.py", payload, env)

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        events = self.read_events(telemetry_dir, repo)
        self.assertEqual(len(events), 1, events)
        self.assertEqual(events[0]["event"], "spec_write")
        self.assertIsNone(events[0]["agent_type"])

    def test_c24_handoff_write_event_empty_string_agent_type_records_null(self):
        repo, telemetry_dir = self.install_with_telemetry_dir()
        handoff = self.write_handoff(repo, "0123456789abcdef-y.md")
        env = self.telemetry_env(telemetry_dir)
        payload = self.post_tool_use_write(handoff)
        payload["agent_type"] = ""

        result = self.run_hook_env(repo, "telemetry_hook.py", payload, env)

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        events = self.read_events(telemetry_dir, repo)
        self.assertEqual(len(events), 1, events)
        self.assertEqual(events[0]["event"], "handoff_write")
        self.assertIsNone(events[0]["agent_type"])

    def test_c24_gate_block_event_empty_string_agent_type_records_null(self):
        repo, telemetry_dir = self.install_with_telemetry_dir()
        self.write_spec(repo, name="sample", test_command="python3 -m unittest")
        env = self.telemetry_env(telemetry_dir)

        start = self.run_hook_env(
            repo,
            "spec_gate.py",
            {"hook_event_name": "SubagentStart", "agent_type": "implementer", "agent_id": "a1"},
            env,
        )
        self.assertEqual(start.returncode, 0, start.stdout + start.stderr)

        blocked = self.run_hook_env(
            repo,
            "spec_gate.py",
            {
                "hook_event_name": "PreToolUse",
                "tool_name": "Bash",
                "tool_input": {"command": "python3 -m unittest"},
                "agent_type": "",
            },
            env,
        )

        self.assertEqual(blocked.returncode, 2, blocked.stdout + blocked.stderr)
        events = self.read_events(telemetry_dir, repo)
        gate_events = [e for e in events if e["event"] == "gate_block"]
        self.assertEqual(len(gate_events), 1, events)
        self.assertIsNone(gate_events[0]["agent_type"])


class TestError(TelemetryTestCase):
    def make_unwritable_telemetry_dir(self):
        parent = self.temp_dir()
        unwritable = parent / "not-a-dir"
        unwritable.write_text("regular file, not a directory")
        return unwritable

    def test_c15_unwritable_telemetry_dir_swallows_failure_and_keeps_hook_behavior(self):
        repo, telemetry_dir_parent = self.install_with_telemetry_dir()
        unwritable = self.make_unwritable_telemetry_dir()
        env = self.telemetry_env(unwritable)

        result = self.run_hook_env(
            repo,
            "telemetry_hook.py",
            self.post_tool_use_bash(
                "python3 .harness/bin/seed.py backup src/a.py", exit_code=0
            ),
            env,
        )

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stdout, "")
        self.assertEqual(result.stderr, "")

    def test_c15_unwritable_telemetry_dir_does_not_change_gate_exit_code(self):
        repo, telemetry_dir_parent = self.install_with_telemetry_dir()
        self.write_spec(repo, name="sample", test_command="python3 -m unittest")
        unwritable = self.make_unwritable_telemetry_dir()
        env = self.telemetry_env(unwritable)

        start = self.run_hook_env(
            repo,
            "spec_gate.py",
            {"hook_event_name": "SubagentStart", "agent_type": "implementer", "agent_id": "a1"},
            env,
        )
        self.assertEqual(start.returncode, 0, start.stdout + start.stderr)

        blocked = self.run_hook_env(
            repo,
            "spec_gate.py",
            {
                "hook_event_name": "PreToolUse",
                "tool_name": "Bash",
                "tool_input": {"command": "python3 -m unittest"},
            },
            env,
        )

        self.assertEqual(blocked.returncode, 2, blocked.stdout + blocked.stderr)
        self.assertIn("blocked", blocked.stderr.lower())
        self.assertNotIn("Traceback", blocked.stderr)

    def run_gate_block_scenario(self, telemetry_dir):
        repo = self.install()
        self.write_spec(repo, name="sample", test_command="python3 -m unittest")
        env = self.telemetry_env(telemetry_dir)
        start = self.run_hook_env(
            repo,
            "spec_gate.py",
            {"hook_event_name": "SubagentStart", "agent_type": "implementer", "agent_id": "a1"},
            env,
        )
        self.assertEqual(start.returncode, 0, start.stdout + start.stderr)
        return self.run_hook_env(
            repo,
            "spec_gate.py",
            {
                "hook_event_name": "PreToolUse",
                "tool_name": "Bash",
                "tool_input": {"command": "python3 -m unittest"},
            },
            env,
        )

    def test_c15_gate_stderr_and_exit_code_byte_identical_writable_vs_unwritable(self):
        writable_dir = self.temp_dir()
        unwritable_dir = self.make_unwritable_telemetry_dir()

        writable_result = self.run_gate_block_scenario(writable_dir)
        unwritable_result = self.run_gate_block_scenario(unwritable_dir)

        self.assertEqual(writable_result.returncode, 2, writable_result.stderr)
        self.assertEqual(writable_result.returncode, unwritable_result.returncode)
        self.assertEqual(writable_result.stderr, unwritable_result.stderr)
        self.assertEqual(writable_result.stdout, unwritable_result.stdout)

    def test_c16_non_json_stdin_exits_0_and_writes_nothing(self):
        repo, telemetry_dir = self.install_with_telemetry_dir()
        env = self.telemetry_env(telemetry_dir)

        result = subprocess.run(
            [sys.executable, str(repo / ".harness" / "hooks" / "telemetry_hook.py")],
            input="not json at all {{{",
            capture_output=True,
            text=True,
            env=env,
        )

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stdout, "")
        self.assertEqual(self.read_events(telemetry_dir, repo), [])


class TestEdge(TelemetryTestCase):
    def test_c17_post_tool_use_failure_records_tool_failure(self):
        repo, telemetry_dir = self.install_with_telemetry_dir()
        self.write_spec(repo, name="sample", test_command="python3 -m unittest")
        env = self.telemetry_env(telemetry_dir)
        payload = {
            "hook_event_name": "PostToolUseFailure",
            "tool_name": "Bash",
            "tool_input": {"command": "python3 -m unittest"},
            "error_code": "timeout",
            "session_id": "s1",
        }

        result = self.run_hook_env(repo, "telemetry_hook.py", payload, env)

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        events = self.read_events(telemetry_dir, repo)
        self.assertEqual(len(events), 1, events)
        self.assertEqual(events[0]["event"], "tool_failure")
        self.assertEqual(events[0]["tool_name"], "Bash")
        self.assertEqual(events[0]["error_code"], "timeout")
        self.assertIsNone(events[0]["spec"])
        self.assertIsNone(events[0]["action"])

    def test_c17_post_tool_use_failure_seed_command_records_tool_failure(self):
        repo, telemetry_dir = self.install_with_telemetry_dir()
        env = self.telemetry_env(telemetry_dir)
        payload = {
            "hook_event_name": "PostToolUseFailure",
            "tool_name": "Bash",
            "tool_input": {"command": "python3 .harness/bin/seed.py backup src/a.py"},
            "error_code": "timeout",
            "session_id": "s1",
        }

        result = self.run_hook_env(repo, "telemetry_hook.py", payload, env)

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        events = self.read_events(telemetry_dir, repo)
        self.assertEqual(len(events), 1, events)
        self.assertEqual(events[0]["event"], "tool_failure")
        self.assertEqual(events[0]["tool_name"], "Bash")
        self.assertEqual(events[0]["error_code"], "timeout")
        self.assertEqual(events[0]["action"], "backup")
        self.assertIsNone(events[0]["spec"])

    def test_c17_post_tool_use_failure_non_matching_command_writes_nothing(self):
        repo, telemetry_dir = self.install_with_telemetry_dir()
        self.write_spec(repo, name="sample", test_command="python3 -m unittest")
        env = self.telemetry_env(telemetry_dir)
        payload = {
            "hook_event_name": "PostToolUseFailure",
            "tool_name": "Bash",
            "tool_input": {"command": "ls -la"},
            "error_code": "timeout",
            "session_id": "s1",
        }

        result = self.run_hook_env(repo, "telemetry_hook.py", payload, env)

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.read_events(telemetry_dir, repo), [])

    def test_c18_two_events_appended_with_v1_and_harness_version(self):
        repo, telemetry_dir = self.install_with_telemetry_dir()
        env = self.telemetry_env(telemetry_dir)

        first = self.run_hook_env(
            repo,
            "telemetry_hook.py",
            self.post_tool_use_bash(
                "python3 .harness/bin/seed.py backup src/a.py", exit_code=0
            ),
            env,
        )
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        second = self.run_hook_env(
            repo,
            "telemetry_hook.py",
            self.post_tool_use_bash(
                "python3 .harness/bin/seed.py restore", exit_code=0
            ),
            env,
        )
        self.assertEqual(second.returncode, 0, second.stdout + second.stderr)

        events = self.read_events(telemetry_dir, repo)
        self.assertEqual(len(events), 2, events)
        for event in events:
            self.assertEqual(event["v"], 1)
            self.assertEqual(event["harness_version"], HARNESS_VERSION)

    def test_c19_claude_and_codex_hook_registration(self):
        claude, codex = self.install_hook_configs()

        claude_post = self.commands(claude.get("PostToolUse", []))
        self.assertTrue(
            any("telemetry_hook.py" in c for c in claude_post), claude_post
        )
        claude_failure = self.commands(claude.get("PostToolUseFailure", []))
        self.assertTrue(
            any("telemetry_hook.py" in c for c in claude_failure), claude_failure
        )

        codex_post = self.commands(codex.get("PostToolUse", []))
        self.assertTrue(any("telemetry_hook.py" in c for c in codex_post), codex_post)
        codex_failure = self.commands(codex.get("PostToolUseFailure", []))
        self.assertEqual(codex_failure, [])

    def test_c19_claude_matcher_covers_bash_write_edit_and_codex_covers_only_bash_and_apply_patch(self):
        claude, codex = self.install_hook_configs()

        claude_matcher = self.find_matcher(claude.get("PostToolUse", []), "telemetry_hook.py")
        self.assertIsNotNone(claude_matcher, claude.get("PostToolUse"))
        for tool_name in ("Bash", "Write", "Edit"):
            self.assertIsNotNone(
                re.fullmatch(claude_matcher, tool_name),
                (claude_matcher, tool_name),
            )

        codex_matcher = self.find_matcher(codex.get("PostToolUse", []), "telemetry_hook.py")
        self.assertIsNotNone(codex_matcher, codex.get("PostToolUse"))
        for tool_name in ("Bash", "apply_patch"):
            self.assertIsNotNone(re.fullmatch(codex_matcher, tool_name), codex_matcher)
        for tool_name in ("Write", "Edit", "Read"):
            self.assertIsNone(re.fullmatch(codex_matcher, tool_name), codex_matcher)

    def test_c26_nonzero_codex_bash_test_command_records_test_command(self):
        repo, telemetry_dir = self.install_with_telemetry_dir()
        self.write_spec(repo, name="sample", test_command="python3 -m unittest")
        env = self.telemetry_env(telemetry_dir)
        payload = self.post_tool_use_bash("python3 -m unittest", exit_code=1)
        payload["transcript_path"] = "/tmp/.codex/sessions/session.jsonl"

        result = self.run_hook_env(repo, "telemetry_hook.py", payload, env)

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        events = self.read_events(telemetry_dir, repo)
        self.assertEqual(len(events), 1, events)
        self.assertEqual(events[0]["event"], "test_command")
        self.assertEqual(events[0]["client"], "codex")
        self.assertIsNone(events[0]["spec"])
        self.assertEqual(events[0]["exit_code"], 1)

    def test_c19_claude_failure_matcher_is_bash_only(self):
        claude, codex = self.install_hook_configs()

        matcher = self.find_matcher(claude.get("PostToolUseFailure", []), "telemetry_hook.py")
        self.assertIsNotNone(matcher, claude.get("PostToolUseFailure"))
        self.assertIsNotNone(re.fullmatch(matcher, "Bash"), matcher)
        for tool_name in ("Write", "Edit", "Read", "apply_patch"):
            self.assertIsNone(re.fullmatch(matcher, tool_name), (matcher, tool_name))
        self.assertNotIn("PostToolUseFailure", codex)

    def test_c20_update_from_0_4_0_merges_telemetry_hook_and_bumps_manifest_version(self):
        repo = self.install()
        manifest_path = repo / ".harness" / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["version"] = "0.4.0"
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")

        result = run_installer("update", str(repo), input="y\ny\ny\ny\n")

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        updated_manifest = json.loads(manifest_path.read_text())
        self.assertEqual(updated_manifest["version"], HARNESS_VERSION)
        claude_settings = json.loads((repo / ".claude" / "settings.json").read_text())
        post_tool_use = self.commands(claude_settings["hooks"].get("PostToolUse", []))
        self.assertTrue(
            any("telemetry_hook.py" in c for c in post_tool_use), post_tool_use
        )


    def test_c18_harness_version_is_0_9_0(self):
        self.assertEqual(HARNESS_VERSION, "0.9.0")

    def test_c20_update_preserves_pre_existing_post_tool_use_hook(self):
        repo = self.install()
        manifest_path = repo / ".harness" / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["version"] = "0.4.0"
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
        settings_path = repo / ".claude" / "settings.json"
        settings = json.loads(settings_path.read_text())
        settings["hooks"].setdefault("PostToolUse", []).append(
            {"matcher": "Read", "hooks": [{"type": "command", "command": "echo user-hook"}]}
        )
        settings_path.write_text(json.dumps(settings, indent=2) + "\n")

        result = run_installer("update", str(repo), input="y\ny\ny\ny\n")

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        post_tool_use = self.commands(
            json.loads(settings_path.read_text())["hooks"].get("PostToolUse", [])
        )
        self.assertIn("echo user-hook", post_tool_use)
        self.assertTrue(
            any("telemetry_hook.py" in c for c in post_tool_use), post_tool_use
        )


class TestEnvelopeAndActions(TelemetryTestCase):
    def test_envelope_fields_on_post_tool_use_event(self):
        repo, telemetry_dir = self.install_with_telemetry_dir()
        env = self.telemetry_env(telemetry_dir)
        payload = self.post_tool_use_bash(
            "python3 .harness/bin/seed.py backup src/a.py", exit_code=0
        )
        payload["session_id"] = "sess-42"
        payload["tool_use_id"] = "tool-7"
        before = datetime.now(timezone.utc)

        result = self.run_hook_env(repo, "telemetry_hook.py", payload, env)

        after = datetime.now(timezone.utc)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        events = self.read_events(telemetry_dir, repo)
        self.assertEqual(len(events), 1, events)
        event = events[0]
        self.assertEqual(event["repo"], str(repo.resolve()))
        self.assertEqual(event["session_id"], "sess-42")
        self.assertEqual(event["tool_use_id"], "tool-7")
        ts = datetime.fromisoformat(event["ts"].replace("Z", "+00:00"))
        self.assertIsNotNone(ts.tzinfo, event["ts"])
        self.assertEqual(ts.utcoffset(), timedelta(0), event["ts"])
        self.assertLessEqual(before - timedelta(seconds=1), ts)
        self.assertLessEqual(ts, after + timedelta(seconds=1))

    def test_seed_action_is_taken_from_command(self):
        cases = {
            "python3 .harness/bin/seed.py restore": "restore",
            "python3 .harness/bin/seed.py status": "status",
            "python3 .harness/bin/seed.py frobnicate x": "frobnicate",
            "python3 .harness/bin/seed.py": None,
        }
        for command, expected in cases.items():
            with self.subTest(command=command):
                repo, telemetry_dir = self.install_with_telemetry_dir()
                env = self.telemetry_env(telemetry_dir)
                result = self.run_hook_env(
                    repo,
                    "telemetry_hook.py",
                    self.post_tool_use_bash(command, exit_code=3),
                    env,
                )
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                events = self.read_events(telemetry_dir, repo)
                self.assertEqual(len(events), 1, events)
                self.assertEqual(events[0]["event"], "seed")
                self.assertEqual(events[0]["action"], expected)
                self.assertEqual(events[0]["exit_code"], 3)

    @unittest.skipIf(hasattr(os, "geteuid") and os.geteuid() == 0, "root ignores chmod")
    def test_unreadable_spec_write_records_null_version_and_exits_0(self):
        repo, telemetry_dir = self.install_with_telemetry_dir()
        spec = self.write_spec(repo, name="locked", version=2)
        spec.chmod(0)
        self.addCleanup(spec.chmod, 0o644)
        env = self.telemetry_env(telemetry_dir)

        result = self.run_hook_env(
            repo, "telemetry_hook.py", self.post_tool_use_write(spec), env
        )

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stdout, "")
        self.assertNotIn("Traceback", result.stderr)
        events = self.read_events(telemetry_dir, repo)
        self.assertEqual(len(events), 1, events)
        self.assertEqual(events[0]["event"], "spec_write")
        self.assertIsNone(events[0]["spec"])
        self.assertIsNone(events[0]["version"])


if __name__ == "__main__":
    unittest.main()

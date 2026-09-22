"""Independent oracle for workflow-markers-v3 contract (v3).

The marker implementation is deliberately exercised only through an installed
harness.  Assertions inspect its public CLI effects and emitted JSONL events.
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


def repo_slug(repo):
    return re.sub(r"[^A-Za-z0-9]", "-", str(repo.resolve()))


class WorkflowMarkerTestCase(InstallerTestCase):
    def temp_dir(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        return Path(temporary.name)

    def install_with_telemetry(self):
        return self.install(), self.temp_dir()

    def environment(self, telemetry_dir):
        env = dict(os.environ)
        env["HARNESS_TELEMETRY_DIR"] = str(telemetry_dir)
        return env

    def events(self, telemetry_dir, repo):
        events = []
        for path in telemetry_dir.glob("*.jsonl"):
            events.extend(
                event
                for line in path.read_text().splitlines()
                if line
                for event in (json.loads(line),)
                if event.get("repo") == str(repo.resolve())
            )
        return events

    def marker(self, repo, env, *args):
        return subprocess.run(
            [sys.executable, str(repo / ".harness" / "bin" / "workflow_marker.py"), *args,
            ],
            cwd=repo,
            env=env,
            capture_output=True,
            text=True,
        )

    def hook(self, repo, env, payload):
        return subprocess.run(
            [sys.executable, str(repo / ".harness" / "hooks" / "telemetry_hook.py")],
            cwd=repo,
            env=env,
            input=json.dumps(payload),
            capture_output=True,
            text=True,
        )

    def gate(self, repo, env, payload):
        return subprocess.run(
            [sys.executable, str(repo / ".harness" / "hooks" / "contract_gate.py")],
            cwd=repo,
            env=env,
            input=json.dumps(payload),
            capture_output=True,
            text=True,
        )

    def write_contract(self, repo, name, command="python3 -m unittest"):
        path = repo / "agent-docs" / "contracts" / f"{name}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"---\nversion: 1\n---\n# Paths\nTest command: {command}\n")

    def test_m1_start_records_identity_and_activates_run(self):
        repo, telemetry_dir = self.install_with_telemetry()
        env = self.environment(telemetry_dir)

        result = self.marker(
            repo, env, "start", "--run-id", "run-1", "--contract", "checkout", "--contract-version", "3"
        )

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stdout, "")
        self.assertEqual(result.stderr, "")
        events = self.events(telemetry_dir, repo)
        self.assertEqual(len(events), 1, events)
        self.assertEqual(events[0]["event"], "workflow_start")
        self.assertEqual(events[0]["workflow_run_id"], "run-1")
        self.assertEqual(events[0]["contract"], "checkout")
        self.assertEqual(events[0]["contract_version"], 3)

    def test_m2_phase_verifier_and_end_are_semantic_and_end_clears_active_run(self):
        repo, telemetry_dir = self.install_with_telemetry()
        env = self.environment(telemetry_dir)
        self.marker(repo, env, "start", "--run-id", "run-2", "--contract", "orders", "--contract-version", "1")

        phase = self.marker(repo, env, "phase", "--run-id", "run-2", "--phase", "implement_test")
        verifier = self.marker(
            repo, env, "verifier", "--run-id", "run-2", "--round", "2", "--result", "retry",
            "--findings", "4", "--seeds-run", "3", "--seeds-detected", "2",
        )
        end = self.marker(repo, env, "end", "--run-id", "run-2", "--status", "complete")

        for result in (phase, verifier, end):
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(result.stdout + result.stderr, "")
        events = self.events(telemetry_dir, repo)
        self.assertEqual([event["event"] for event in events], ["workflow_start", "workflow_phase", "verifier_result", "workflow_end"])
        self.assertEqual(events[1]["phase"], "implement_test")
        self.assertEqual(events[1]["workflow_run_id"], "run-2")
        self.assertEqual(events[1]["contract"], "orders")
        self.assertEqual(
            {key: events[2][key] for key in ("round", "result", "findings", "seeds_run", "seeds_detected")},
            {"round": 2, "result": "retry", "findings": 4, "seeds_run": 3, "seeds_detected": 2},
        )
        self.assertEqual(events[2]["workflow_run_id"], "run-2")
        self.assertEqual(events[2]["contract"], "orders")
        self.assertEqual(events[3]["status"], "complete")

        self.write_contract(repo, "ordinary")
        automatic = self.hook(repo, env, {
            "hook_event_name": "PostToolUse", "tool_name": "Bash",
            "tool_input": {"command": "python3 -m unittest"}, "tool_response": {"exit_code": 0},
        })
        self.assertEqual(automatic.returncode, 0, automatic.stdout + automatic.stderr)
        event = self.events(telemetry_dir, repo)[-1]
        self.assertEqual(event["event"], "test_command")
        self.assertIsNone(event["workflow_run_id"])
        self.assertIsNone(event["contract"])

    def test_m2_each_phase_and_verifier_result_is_preserved(self):
        for phase in ("implement_test", "verify", "amend"):
            with self.subTest(kind="phase", value=phase):
                repo, telemetry_dir = self.install_with_telemetry()
                env = self.environment(telemetry_dir)
                self.marker(repo, env, "start", "--run-id", "phase-run", "--contract", "semantic", "--contract-version", "1")

                result = self.marker(repo, env, "phase", "--run-id", "phase-run", "--phase", phase)

                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                event = self.events(telemetry_dir, repo)[-1]
                self.assertEqual(event["phase"], phase)
                self.assertEqual(event["workflow_run_id"], "phase-run")
                self.assertEqual(event["contract"], "semantic")

        for verifier_result in ("pass", "retry", "limit"):
            with self.subTest(kind="verifier", value=verifier_result):
                repo, telemetry_dir = self.install_with_telemetry()
                env = self.environment(telemetry_dir)
                self.marker(repo, env, "start", "--run-id", "verify-run", "--contract", "semantic", "--contract-version", "1")

                result = self.marker(
                    repo, env, "verifier", "--run-id", "verify-run", "--round", "1",
                    "--result", verifier_result, "--findings", "1", "--seeds-run", "1",
                    "--seeds-detected", "1",
                )

                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                event = self.events(telemetry_dir, repo)[-1]
                self.assertEqual(event["result"], verifier_result)
                self.assertEqual(event["workflow_run_id"], "verify-run")
                self.assertEqual(event["contract"], "semantic")
                self.assertEqual(
                    {key: event[key] for key in ("round", "findings", "seeds_run", "seeds_detected")},
                    {"round": 1, "findings": 1, "seeds_run": 1, "seeds_detected": 1},
                )

    def test_m1_marker_event_retains_v1_telemetry_envelope(self):
        repo, telemetry_dir = self.install_with_telemetry()
        env = self.environment(telemetry_dir)
        before = datetime.now(timezone.utc)

        result = self.marker(
            repo, env, "start", "--run-id", "envelope-run", "--contract", "envelope",
            "--contract-version", "1",
        )

        after = datetime.now(timezone.utc)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        event = self.events(telemetry_dir, repo)[0]
        self.assertEqual(event["v"], 1)
        self.assertEqual(event["harness_version"], "0.6.0")
        self.assertEqual(event["repo"], str(repo.resolve()))
        timestamp = datetime.fromisoformat(event["ts"].replace("Z", "+00:00"))
        self.assertEqual(timestamp.utcoffset(), timedelta(0))
        self.assertLessEqual(before - timedelta(seconds=1), timestamp)
        self.assertLessEqual(timestamp, after + timedelta(seconds=1))

    def test_m3_active_workflow_attributes_automatic_event_over_ordinary_contract_match(self):
        repo, telemetry_dir = self.install_with_telemetry()
        env = self.environment(telemetry_dir)
        self.write_contract(repo, "ordinary")
        self.marker(repo, env, "start", "--run-id", "run-3", "--contract", "active-contract", "--contract-version", "7")

        result = self.hook(repo, env, {
            "hook_event_name": "PostToolUse", "tool_name": "Bash",
            "tool_input": {"command": "python3 -m unittest"}, "tool_response": {"exit_code": 0},
        })

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        event = self.events(telemetry_dir, repo)[-1]
        self.assertEqual(event["workflow_run_id"], "run-3")
        self.assertEqual(event["contract"], "active-contract")

        contract_path = repo / "agent-docs" / "contracts" / "written.md"
        contract_path.write_text("---\nversion: 1\n---\n")
        written = self.hook(repo, env, {
            "hook_event_name": "PostToolUse", "tool_name": "Write",
            "tool_input": {"file_path": str(contract_path)}, "tool_response": {},
        })
        self.assertEqual(written.returncode, 0, written.stdout + written.stderr)
        event = self.events(telemetry_dir, repo)[-1]
        self.assertEqual(event["event"], "contract_write")
        self.assertEqual(event["workflow_run_id"], "run-3")
        self.assertEqual(event["contract"], "active-contract")

    def test_m3_contract_gate_event_has_active_workflow_identity(self):
        repo, telemetry_dir = self.install_with_telemetry()
        env = self.environment(telemetry_dir)
        self.marker(repo, env, "start", "--run-id", "gate-run", "--contract", "gate-contract", "--contract-version", "1")

        result = self.gate(repo, env, {
            "hook_event_name": "SubagentStart", "agent_type": "implementer", "agent_id": "agent-1",
        })

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        event = self.events(telemetry_dir, repo)[-1]
        self.assertEqual(event["event"], "subagent_start")
        self.assertEqual(event["workflow_run_id"], "gate-run")
        self.assertEqual(event["contract"], "gate-contract")

    def test_m3_all_contract_gate_events_have_active_workflow_identity(self):
        repo, telemetry_dir = self.install_with_telemetry()
        env = self.environment(telemetry_dir)
        self.write_contract(repo, "suite")
        self.marker(repo, env, "start", "--run-id", "gate-all", "--contract", "gate-contract", "--contract-version", "1")

        calls = (
            ({"hook_event_name": "SubagentStart", "agent_type": "implementer", "agent_id": "agent-1"}, 0, "subagent_start"),
            ({"hook_event_name": "SubagentStop", "agent_type": "implementer", "agent_id": "agent-1"}, 0, "subagent_stop"),
        )
        for payload, returncode, event_name in calls:
            with self.subTest(event=event_name):
                result = self.gate(repo, env, payload)
                self.assertEqual(result.returncode, returncode, result.stdout + result.stderr)
                event = self.events(telemetry_dir, repo)[-1]
                self.assertEqual(event["event"], event_name)
                self.assertEqual(event["workflow_run_id"], "gate-all")
                self.assertEqual(event["contract"], "gate-contract")

    def test_m4_installed_skill_requires_all_semantic_transitions_and_best_effort(self):
        repo = self.install()
        skill = (repo / ".agents" / "skills" / "contract-workflow" / "SKILL.md").read_text().lower()

        self.assertIn("workflow_marker.py", skill)
        self.assertIn(" start", skill)
        for phase in ("implement_test", "verify", "amend"):
            self.assertIn(phase, skill)
        self.assertIn("verifier", skill)
        for result in ("pass", "retry", "limit"):
            self.assertIn(result, skill)
        self.assertIn(" end", skill)
        for status in ("complete", "handoff", "aborted"):
            self.assertIn(status, skill)
        self.assertRegex(skill, r"(?:best[ -]effort|must not block|never block)")
        command_lines = [line.lower() for line in skill.splitlines() if "workflow_marker.py" in line]
        self.assertTrue(any(re.search(r"\bstart\b.*--run-id.*--contract.*--contract-version", line) for line in command_lines))
        for phase in ("implement_test", "verify", "amend"):
            self.assertTrue(any(
                " phase " in line and phase in line and "--run-id" in line and "--phase" in line
                for line in command_lines
            ), phase)
        self.assertTrue(any(
            " verifier " in line and all(value in line for value in (
                "--run-id", "--round", "--result", "--findings", "--seeds-run", "--seeds-detected",
            ))
            for line in command_lines
        ))
        self.assertTrue(any(
            " end " in line and "--run-id" in line and "--status" in line
            for line in command_lines
        ))
        transition_patterns = (
            r"emit `start`.{0,160}(?:before|prior to) dispatch",
            r"emit `implement_test`.{0,160}before.{0,80}(?:parallel|implement)",
            r"`verify`.{0,160}before dispatching a verifier",
            r"emit one `verifier` marker after every verifier result",
            r"emit `amend` before every amendment or correction",
            r"emit `end complete` after a completed workflow.{0,240}`end handoff`.{0,240}`end aborted`",
        )
        for pattern in transition_patterns:
            self.assertRegex(skill, re.compile(pattern, re.DOTALL), pattern)

    def test_m5_automatic_event_without_marker_has_null_workflow_fields(self):
        repo, telemetry_dir = self.install_with_telemetry()
        env = self.environment(telemetry_dir)
        self.write_contract(repo, "ordinary")

        result = self.hook(repo, env, {
            "hook_event_name": "PostToolUse", "tool_name": "Bash",
            "tool_input": {"command": "python3 -m unittest"}, "tool_response": {"exit_code": 0},
        })

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        event = self.events(telemetry_dir, repo)[0]
        self.assertIsNone(event["workflow_run_id"])
        self.assertIsNone(event["contract"])

    def test_m6_zero_verifier_counts_are_recorded_without_invention(self):
        repo, telemetry_dir = self.install_with_telemetry()
        env = self.environment(telemetry_dir)
        self.marker(repo, env, "start", "--run-id", "run-6", "--contract", "zeroes", "--contract-version", "1")

        result = self.marker(
            repo, env, "verifier", "--run-id", "run-6", "--round", "1", "--result", "pass",
            "--findings", "0", "--seeds-run", "0", "--seeds-detected", "0",
        )

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        event = self.events(telemetry_dir, repo)[-1]
        self.assertEqual(event["findings"], 0)
        self.assertEqual(event["seeds_run"], 0)
        self.assertEqual(event["seeds_detected"], 0)

    def test_m7_invalid_or_mismatched_markers_are_silent_and_preserve_prior_active_state(self):
        repo, telemetry_dir = self.install_with_telemetry()
        env = self.environment(telemetry_dir)
        self.write_contract(repo, "ordinary")
        missing_active = self.marker(repo, env, "phase", "--run-id", "missing", "--phase", "verify")
        self.assertEqual(missing_active.returncode, 0, missing_active.stdout + missing_active.stderr)
        missing_verifier = self.marker(
            repo, env, "verifier", "--run-id", "missing", "--round", "1", "--result", "pass",
            "--findings", "0", "--seeds-run", "0", "--seeds-detected", "0",
        )
        self.assertEqual(missing_verifier.returncode, 0, missing_verifier.stdout + missing_verifier.stderr)
        self.assertEqual(missing_active.stdout + missing_active.stderr, "")
        self.assertEqual(missing_verifier.stdout + missing_verifier.stderr, "")
        self.assertEqual(self.events(telemetry_dir, repo), [])
        self.marker(repo, env, "start", "--run-id", "good", "--contract", "preserved", "--contract-version", "1")
        baseline = self.events(telemetry_dir, repo)

        invalid = (
            ("start", "--run-id", "replacement", "--contract-version", "1"),
            ("start", "--run-id", "replacement", "--contract", "new", "--contract-version", "-1"),
            ("start", "--run-id", "replacement", "--contract", "new", "--contract-version", "one"),
            ("phase", "--run-id", "wrong", "--phase", "verify"),
            ("phase", "--run-id", "good", "--phase", "unknown"),
            ("verifier", "--run-id", "good", "--round", "-1", "--result", "pass", "--findings", "0", "--seeds-run", "0", "--seeds-detected", "0"),
            ("verifier", "--run-id", "good", "--round", "1", "--result", "unknown", "--findings", "0", "--seeds-run", "0", "--seeds-detected", "0"),
            ("verifier", "--run-id", "good", "--round", "1", "--result", "pass", "--findings", "-1", "--seeds-run", "0", "--seeds-detected", "0"),
            ("verifier", "--run-id", "good", "--round", "1", "--result", "pass", "--findings", "0", "--seeds-run", "-1", "--seeds-detected", "0"),
            ("verifier", "--run-id", "good", "--round", "1", "--result", "pass", "--findings", "0", "--seeds-run", "0", "--seeds-detected", "-1"),
            ("verifier", "--run-id", "good", "--round", "1", "--result", "pass", "--findings", "0", "--seeds-run", "0"),
            ("end", "--run-id", "good", "--status", "unknown"),
            ("end", "--run-id", "wrong", "--status", "complete"),
            ("nonsense",),
        )
        for args in invalid:
            with self.subTest(args=args):
                result = self.marker(repo, env, *args)
                self.assertEqual(result.returncode, 0)
                self.assertEqual(result.stdout + result.stderr, "")
        self.assertEqual(self.events(telemetry_dir, repo), baseline)

        automatic = self.hook(repo, env, {
            "hook_event_name": "PostToolUse", "tool_name": "Bash",
            "tool_input": {"command": "python3 -m unittest"}, "tool_response": {"exit_code": 0},
        })
        self.assertEqual(automatic.returncode, 0, automatic.stdout + automatic.stderr)
        event = self.events(telemetry_dir, repo)[-1]
        self.assertEqual(event["workflow_run_id"], "good")
        self.assertEqual(event["contract"], "preserved")

    def test_v3_m7_verifier_omitted_required_argument_is_silent_and_preserves_active_run(self):
        for omitted_option in ("--round", "--result", "--findings", "--seeds-run"):
            with self.subTest(obligation="V3", case="M7", omitted_option=omitted_option):
                repo, telemetry_dir = self.install_with_telemetry()
                env = self.environment(telemetry_dir)
                self.write_contract(repo, "ordinary")
                self.marker(
                    repo, env, "start", "--run-id", "preserved-run", "--contract", "preserved",
                    "--contract-version", "1",
                )
                baseline = self.events(telemetry_dir, repo)
                verifier_args = [
                    "verifier", "--run-id", "preserved-run", "--round", "1", "--result", "pass",
                    "--findings", "0", "--seeds-run", "0", "--seeds-detected", "0",
                ]
                option_index = verifier_args.index(omitted_option)
                del verifier_args[option_index:option_index + 2]

                result = self.marker(repo, env, *verifier_args)

                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual(result.stdout + result.stderr, "")
                self.assertEqual(self.events(telemetry_dir, repo), baseline)
                automatic = self.hook(repo, env, {
                    "hook_event_name": "PostToolUse", "tool_name": "Bash",
                    "tool_input": {"command": "python3 -m unittest"}, "tool_response": {"exit_code": 0},
                })
                self.assertEqual(automatic.returncode, 0, automatic.stdout + automatic.stderr)
                event = self.events(telemetry_dir, repo)[-1]
                self.assertEqual(event["workflow_run_id"], "preserved-run")
                self.assertEqual(event["contract"], "preserved")

    def test_v3_v2_all_automatic_events_follow_active_absent_and_ended_workflow_state(self):
        for workflow_state in ("active", "absent", "ended"):
            with self.subTest(obligation="V2", state=workflow_state):
                repo, telemetry_dir = self.install_with_telemetry()
                env = self.environment(telemetry_dir)
                self.write_contract(repo, "ordinary")
                if workflow_state != "absent":
                    self.marker(repo, env, "start", "--run-id", "automatic-run", "--contract", "automatic", "--contract-version", "1")
                    if workflow_state == "ended":
                        self.marker(repo, env, "end", "--run-id", "automatic-run", "--status", "complete")

                contract_path = repo / "agent-docs" / "contracts" / "written.md"
                contract_path.write_text("---\nversion: 1\n---\n")
                handoff_path = repo / "agent-docs" / "handoff" / "0123456789abcdef-auto.md"
                handoff_path.parent.mkdir(parents=True, exist_ok=True)
                handoff_path.write_text("# Handoff\n")
                event_calls = (
                    ("seed", lambda: self.hook(repo, env, {
                        "hook_event_name": "PostToolUse", "tool_name": "Bash",
                        "tool_input": {"command": "python3 .harness/bin/seed.py backup src/a.py"},
                        "tool_response": {"exit_code": 0},
                    })),
                    ("contract_write", lambda: self.hook(repo, env, {
                        "hook_event_name": "PostToolUse", "tool_name": "Write",
                        "tool_input": {"file_path": str(contract_path)}, "tool_response": {},
                    })),
                    ("handoff_write", lambda: self.hook(repo, env, {
                        "hook_event_name": "PostToolUse", "tool_name": "Write",
                        "tool_input": {"file_path": str(handoff_path)}, "tool_response": {},
                    })),
                    ("test_command", lambda: self.hook(repo, env, {
                        "hook_event_name": "PostToolUse", "tool_name": "Bash",
                        "tool_input": {"command": "python3 -m unittest"}, "tool_response": {"exit_code": 0},
                    })),
                    ("tool_failure", lambda: self.hook(repo, env, {
                        "hook_event_name": "PostToolUseFailure", "tool_name": "Bash",
                        "tool_input": {"command": "python3 -m unittest"}, "error_code": "timeout",
                    })),
                    ("subagent_start", lambda: self.gate(repo, env, {
                        "hook_event_name": "SubagentStart", "agent_type": "test-verifier", "agent_id": "auto-start",
                    })),
                    ("subagent_stop", lambda: self.gate(repo, env, {
                        "hook_event_name": "SubagentStop", "agent_type": "test-verifier", "agent_id": "auto-start",
                    })),
                )
                for event_name, invoke in event_calls:
                    with self.subTest(obligation="V2", state=workflow_state, event=event_name):
                        result = invoke()
                        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                        event = self.events(telemetry_dir, repo)[-1]
                        self.assertEqual(event["event"], event_name)
                        if workflow_state == "active":
                            self.assertEqual(event["workflow_run_id"], "automatic-run")
                            self.assertEqual(event["contract"], "automatic")
                        else:
                            self.assertIsNone(event["workflow_run_id"])
                            self.assertIsNone(event["contract"])

                self.gate(repo, env, {
                    "hook_event_name": "SubagentStart", "agent_type": "implementer", "agent_id": "gate-agent",
                })
                blocked = self.gate(repo, env, {
                    "hook_event_name": "PreToolUse", "tool_name": "Bash",
                    "tool_input": {"command": "python3 -m unittest"},
                })
                self.assertEqual(blocked.returncode, 2, blocked.stdout + blocked.stderr)
                gate_block = self.events(telemetry_dir, repo)[-1]
                self.assertEqual(gate_block["event"], "gate_block")
                if workflow_state == "active":
                    self.assertEqual(gate_block["workflow_run_id"], "automatic-run")
                    self.assertEqual(gate_block["contract"], "automatic")
                else:
                    self.assertIsNone(gate_block["workflow_run_id"])
                    self.assertIsNone(gate_block["contract"])

    def test_v3_v2_all_automatic_events_remain_isolated_when_repo_slugs_collide(self):
        parent = self.temp_dir()
        telemetry_dir = self.temp_dir()
        first, second = parent / "same_name", parent / "same-name"
        for repo in (first, second):
            repo.mkdir()
            init = subprocess.run(["git", "-C", str(repo), "init", "-q"], capture_output=True, text=True)
            self.assertEqual(init.returncode, 0, init.stdout + init.stderr)
            installed = run_installer("install", str(repo))
            self.assertEqual(installed.returncode, 0, installed.stdout + installed.stderr)
            self.write_contract(repo, "ordinary")
        self.assertEqual(repo_slug(first), repo_slug(second))
        env = self.environment(telemetry_dir)
        self.marker(first, env, "start", "--run-id", "first-run", "--contract", "first", "--contract-version", "1")
        self.marker(second, env, "start", "--run-id", "second-run", "--contract", "second", "--contract-version", "1")

        for repo, run_id, contract in ((first, "first-run", "first"), (second, "second-run", "second")):
            contract_path = repo / "agent-docs" / "contracts" / "written.md"
            contract_path.write_text("---\nversion: 1\n---\n")
            handoff_path = repo / "agent-docs" / "handoff" / "0123456789abcdef-auto.md"
            handoff_path.parent.mkdir(parents=True, exist_ok=True)
            handoff_path.write_text("# Handoff\n")
            calls = (
                ("seed", lambda: self.hook(repo, env, {"hook_event_name": "PostToolUse", "tool_name": "Bash", "tool_input": {"command": "python3 .harness/bin/seed.py backup src/a.py"}, "tool_response": {"exit_code": 0}})),
                ("contract_write", lambda: self.hook(repo, env, {"hook_event_name": "PostToolUse", "tool_name": "Write", "tool_input": {"file_path": str(contract_path)}, "tool_response": {}})),
                ("handoff_write", lambda: self.hook(repo, env, {"hook_event_name": "PostToolUse", "tool_name": "Write", "tool_input": {"file_path": str(handoff_path)}, "tool_response": {}})),
                ("test_command", lambda: self.hook(repo, env, {"hook_event_name": "PostToolUse", "tool_name": "Bash", "tool_input": {"command": "python3 -m unittest"}, "tool_response": {"exit_code": 0}})),
                ("tool_failure", lambda: self.hook(repo, env, {"hook_event_name": "PostToolUseFailure", "tool_name": "Bash", "tool_input": {"command": "python3 -m unittest"}, "error_code": "timeout"})),
                ("subagent_start", lambda: self.gate(repo, env, {"hook_event_name": "SubagentStart", "agent_type": "test-verifier", "agent_id": "auto-start"})),
                ("subagent_stop", lambda: self.gate(repo, env, {"hook_event_name": "SubagentStop", "agent_type": "test-verifier", "agent_id": "auto-start"})),
            )
            for event_name, invoke in calls:
                with self.subTest(obligation="V2", repo=contract, event=event_name):
                    result = invoke()
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                    event = self.events(telemetry_dir, repo)[-1]
                    self.assertEqual(event["event"], event_name)
                    self.assertEqual(event["workflow_run_id"], run_id)
                    self.assertEqual(event["contract"], contract)
            self.gate(repo, env, {"hook_event_name": "SubagentStart", "agent_type": "implementer", "agent_id": "gate-agent"})
            blocked = self.gate(repo, env, {"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {"command": "python3 -m unittest"}})
            self.assertEqual(blocked.returncode, 2, blocked.stdout + blocked.stderr)
            event = self.events(telemetry_dir, repo)[-1]
            self.assertEqual(event["event"], "gate_block")
            self.assertEqual(event["workflow_run_id"], run_id)
            self.assertEqual(event["contract"], contract)

    def test_v3_v3_non_integer_counts_are_silent_and_round_zero_is_valid(self):
        for option in ("--round", "--findings", "--seeds-run", "--seeds-detected"):
            with self.subTest(obligation="V3", option=option):
                repo, telemetry_dir = self.install_with_telemetry()
                env = self.environment(telemetry_dir)
                self.marker(repo, env, "start", "--run-id", "numeric-run", "--contract", "numeric", "--contract-version", "1")
                baseline = self.events(telemetry_dir, repo)
                args = ["verifier", "--run-id", "numeric-run", "--round", "1", "--result", "pass", "--findings", "0", "--seeds-run", "0", "--seeds-detected", "0"]
                args[args.index(option) + 1] = "one"
                result = self.marker(repo, env, *args)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual(result.stdout + result.stderr, "")
                self.assertEqual(self.events(telemetry_dir, repo), baseline)
        repo, telemetry_dir = self.install_with_telemetry()
        env = self.environment(telemetry_dir)
        self.marker(repo, env, "start", "--run-id", "zero-round", "--contract", "numeric", "--contract-version", "1")
        result = self.marker(repo, env, "verifier", "--run-id", "zero-round", "--round", "0", "--result", "pass", "--findings", "0", "--seeds-run", "0", "--seeds-detected", "0")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.events(telemetry_dir, repo)[-1]["round"], 0)

    def test_v3_v4_end_without_active_run_is_silent_and_emits_nothing(self):
        repo, telemetry_dir = self.install_with_telemetry()
        env = self.environment(telemetry_dir)
        for status in ("complete", "handoff", "aborted"):
            with self.subTest(obligation="V4", status=status):
                result = self.marker(repo, env, "end", "--run-id", "missing", "--status", status)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual(result.stdout + result.stderr, "")
                self.assertEqual(self.events(telemetry_dir, repo), [])

    def test_v3_v4_phase_verifier_and_start_io_failures_preserve_existing_active_run(self):
        failure_commands = (
            ("phase", "--run-id", "io-run", "--phase", "verify"),
            ("verifier", "--run-id", "io-run", "--round", "1", "--result", "pass", "--findings", "0", "--seeds-run", "0", "--seeds-detected", "0"),
            ("start", "--run-id", "replacement", "--contract", "replacement", "--contract-version", "1"),
        )
        for args in failure_commands:
            with self.subTest(obligation="V4", command=args[0]):
                repo, telemetry_dir = self.install_with_telemetry()
                env = self.environment(telemetry_dir)
                self.write_contract(repo, "ordinary")
                self.marker(repo, env, "start", "--run-id", "io-run", "--contract", "preserved", "--contract-version", "1")
                baseline = self.events(telemetry_dir, repo)
                paths = list(telemetry_dir.rglob("*"))
                try:
                    for path in paths:
                        os.chmod(path, 0o500 if path.is_dir() else 0o400)
                    os.chmod(telemetry_dir, 0o500)
                    failed = self.marker(repo, env, *args)
                    self.assertEqual(failed.returncode, 0, failed.stdout + failed.stderr)
                    self.assertEqual(failed.stdout + failed.stderr, "")
                finally:
                    os.chmod(telemetry_dir, 0o700)
                    for path in paths:
                        os.chmod(path, 0o700 if path.is_dir() else 0o600)
                self.assertEqual(self.events(telemetry_dir, repo), baseline)
                automatic = self.hook(repo, env, {
                    "hook_event_name": "PostToolUse", "tool_name": "Bash",
                    "tool_input": {"command": "python3 -m unittest"}, "tool_response": {"exit_code": 0},
                })
                self.assertEqual(automatic.returncode, 0, automatic.stdout + automatic.stderr)
                event = self.events(telemetry_dir, repo)[-1]
                self.assertEqual(event["workflow_run_id"], "io-run")
                self.assertEqual(event["contract"], "preserved")

    def test_m7_failed_start_cannot_activate_an_unrecorded_run(self):
        repo, telemetry_dir = self.install_with_telemetry()
        env = self.environment(telemetry_dir)
        self.write_contract(repo, "ordinary")

        os.chmod(telemetry_dir, 0o500)
        try:
            failed = self.marker(
                repo, env, "start", "--run-id", "invisible", "--contract", "unrecorded",
                "--contract-version", "1",
            )
            self.assertEqual(failed.returncode, 0, failed.stdout + failed.stderr)
        finally:
            os.chmod(telemetry_dir, 0o700)

        self.assertEqual(self.events(telemetry_dir, repo), [])
        automatic = self.hook(repo, env, {
            "hook_event_name": "PostToolUse", "tool_name": "Bash",
            "tool_input": {"command": "python3 -m unittest"}, "tool_response": {"exit_code": 0},
        })
        self.assertEqual(automatic.returncode, 0, automatic.stdout + automatic.stderr)
        event = self.events(telemetry_dir, repo)[-1]
        self.assertIsNone(event["workflow_run_id"])
        self.assertIsNone(event["contract"])

    def test_m7_unwritable_telemetry_override_is_silent_and_does_not_end_active_run(self):
        repo, telemetry_dir = self.install_with_telemetry()
        env = self.environment(telemetry_dir)
        self.write_contract(repo, "ordinary")
        self.marker(repo, env, "start", "--run-id", "io-run", "--contract", "preserved", "--contract-version", "1")
        baseline = self.events(telemetry_dir, repo)
        paths = list(telemetry_dir.rglob("*"))

        try:
            for path in paths:
                os.chmod(path, 0o500 if path.is_dir() else 0o400)
            os.chmod(telemetry_dir, 0o500)
            failed_end = self.marker(repo, env, "end", "--run-id", "io-run", "--status", "complete")
            self.assertEqual(failed_end.returncode, 0, failed_end.stdout + failed_end.stderr)
            self.assertEqual(failed_end.stdout + failed_end.stderr, "")
        finally:
            os.chmod(telemetry_dir, 0o700)
            for path in paths:
                os.chmod(path, 0o700 if path.is_dir() else 0o600)

        self.assertEqual(self.events(telemetry_dir, repo), baseline)
        automatic = self.hook(repo, env, {
            "hook_event_name": "PostToolUse", "tool_name": "Bash",
            "tool_input": {"command": "python3 -m unittest"}, "tool_response": {"exit_code": 0},
        })
        self.assertEqual(automatic.returncode, 0, automatic.stdout + automatic.stderr)
        event = self.events(telemetry_dir, repo)[-1]
        self.assertEqual(event["workflow_run_id"], "io-run")
        self.assertEqual(event["contract"], "preserved")

    def test_m8_end_event_keeps_identity_but_following_automatic_event_is_unattributed(self):
        for status in ("complete", "handoff", "aborted"):
            with self.subTest(status=status):
                repo, telemetry_dir = self.install_with_telemetry()
                env = self.environment(telemetry_dir)
                self.write_contract(repo, "ordinary")
                self.marker(repo, env, "start", "--run-id", "run-8", "--contract", "ending", "--contract-version", "1")
                self.marker(repo, env, "end", "--run-id", "run-8", "--status", status)

                result = self.hook(repo, env, {
                    "hook_event_name": "PostToolUse", "tool_name": "Bash",
                    "tool_input": {"command": "python3 -m unittest"}, "tool_response": {"exit_code": 0},
                })

                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                end, automatic = self.events(telemetry_dir, repo)[-2:]
                self.assertEqual(end["workflow_run_id"], "run-8")
                self.assertEqual(end["contract"], "ending")
                self.assertIsNone(automatic["workflow_run_id"])
                self.assertIsNone(automatic["contract"])

    def test_m2_each_terminal_status_is_preserved(self):
        for status in ("complete", "handoff", "aborted"):
            with self.subTest(status=status):
                repo, telemetry_dir = self.install_with_telemetry()
                env = self.environment(telemetry_dir)
                self.marker(repo, env, "start", "--run-id", f"{status}-run", "--contract", "terminal", "--contract-version", "1")

                result = self.marker(repo, env, "end", "--run-id", f"{status}-run", "--status", status)

                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                event = self.events(telemetry_dir, repo)[-1]
                self.assertEqual(event["event"], "workflow_end")
                self.assertEqual(event["status"], status)

    def test_m9_update_from_050_announces_060_migration_and_installs_marker_payload(self):
        repo = self.install()
        manifest_path = repo / ".harness" / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["version"] = "0.5.0"
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
        user_file = repo / "user-owned.txt"
        user_file.write_text("keep me\n")
        marker_path = repo / ".harness" / "bin" / "workflow_marker.py"
        skill_path = repo / ".agents" / "skills" / "contract-workflow" / "SKILL.md"
        marker_path.unlink()
        skill_path.unlink()

        result = run_installer("update", str(repo), input="y\n")

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertRegex(result.stdout + result.stderr, r"(?im)^migration .*\b0\.6\.0\b")
        self.assertTrue(marker_path.is_file())
        skill = skill_path.read_text()
        self.assertIn("workflow_marker.py", skill)
        self.assertEqual(json.loads(manifest_path.read_text())["version"], "0.6.0")
        self.assertEqual(user_file.read_text(), "keep me\n")

    def test_m10_repositories_keep_active_runs_and_telemetry_isolated(self):
        first, telemetry_dir = self.install_with_telemetry()
        second = self.install()
        env = self.environment(telemetry_dir)
        for repo, run_id, contract in ((first, "first-run", "first-contract"), (second, "second-run", "second-contract")):
            self.write_contract(repo, "ordinary")
            self.marker(repo, env, "start", "--run-id", run_id, "--contract", contract, "--contract-version", "1")
            result = self.hook(repo, env, {
                "hook_event_name": "PostToolUse", "tool_name": "Bash",
                "tool_input": {"command": "python3 -m unittest"}, "tool_response": {"exit_code": 0},
            })
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

        self.assertEqual(self.events(telemetry_dir, first)[-1]["workflow_run_id"], "first-run")
        self.assertEqual(self.events(telemetry_dir, first)[-1]["contract"], "first-contract")
        self.assertEqual(self.events(telemetry_dir, second)[-1]["workflow_run_id"], "second-run")
        self.assertEqual(self.events(telemetry_dir, second)[-1]["contract"], "second-contract")

        again = self.hook(first, env, {
            "hook_event_name": "PostToolUse", "tool_name": "Bash",
            "tool_input": {"command": "python3 -m unittest"}, "tool_response": {"exit_code": 0},
        })
        self.assertEqual(again.returncode, 0, again.stdout + again.stderr)
        self.assertEqual(self.events(telemetry_dir, first)[-1]["workflow_run_id"], "first-run")
        self.assertEqual(self.events(telemetry_dir, first)[-1]["contract"], "first-contract")
        self.assertNotEqual(repo_slug(first), repo_slug(second))

    def test_m10_colliding_sanitized_repo_names_remain_isolated(self):
        parent = self.temp_dir()
        telemetry_dir = self.temp_dir()
        first = parent / "same_name"
        second = parent / "same-name"
        for repo in (first, second):
            repo.mkdir()
            git = subprocess.run(
                ["git", "-C", str(repo), "init", "-q"], capture_output=True, text=True
            )
            self.assertEqual(git.returncode, 0, git.stdout + git.stderr)
            result = run_installer("install", str(repo))
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(repo_slug(first), repo_slug(second))
        env = self.environment(telemetry_dir)

        self.marker(first, env, "start", "--run-id", "first-run", "--contract", "first", "--contract-version", "1")
        self.marker(second, env, "start", "--run-id", "second-run", "--contract", "second", "--contract-version", "1")

        for repo, run_id, contract in ((first, "first-run", "first"), (second, "second-run", "second")):
            self.write_contract(repo, "ordinary")
            result = self.hook(repo, env, {
                "hook_event_name": "PostToolUse", "tool_name": "Bash",
                "tool_input": {"command": "python3 -m unittest"}, "tool_response": {"exit_code": 0},
            })
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            event = self.events(telemetry_dir, repo)[-1]
            self.assertEqual(event["workflow_run_id"], run_id)
            self.assertEqual(event["contract"], contract)

        first_events = self.events(telemetry_dir, first)
        second_events = self.events(telemetry_dir, second)
        self.assertEqual(first_events[-1]["workflow_run_id"], "first-run")
        self.assertEqual(second_events[-1]["workflow_run_id"], "second-run")


if __name__ == "__main__":
    unittest.main()

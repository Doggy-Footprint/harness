import json
import re
import string
import subprocess
import sys
import unittest
from datetime import datetime
from pathlib import Path

from hypothesis import HealthCheck, given, seed, settings
from hypothesis import strategies as st

from test_installer import REPO_ROOT, run_installer
from test_telemetry import TelemetryTestCase

RID = "49bafb302bb6593c"
REL = ".harness/bin/workflow_marker.py"
ABS = "/x/repo/.harness/bin/workflow_marker.py"
SKILL = REPO_ROOT / "harness" / "skills" / "workflow-approach" / "SKILL.md"
VERSION_FILE = REPO_ROOT / "harness" / "VERSION"

ENVELOPE = ["v", "ts", "harness_version", "repo", "client", "session_id", "agent_id",
            "agent_type", "tool_use_id", "event", "workflow_run_id", "spec"]
BRIEF_KEYS = set(ENVELOPE) | {"stage", "round", "fact_questions", "user_decisions", "split",
                              "picks_differ"}
FACT_KEYS = set(ENVELOPE) | {"fact_id", "dimension"}
E10 = ["v", "ts", "harness_version", "repo", "client", "session_id", "agent_id", "agent_type",
       "tool_use_id", "event"]
SHAPES = {
    "test_command": set(E10) | {"spec", "exit_code", "workflow_run_id"},
    "seed": set(E10) | {"action", "exit_code", "workflow_run_id", "spec"},
    "spec_write": set(E10) | {"spec", "version", "workflow_run_id"},
    "progress_write": set(E10) | {"file", "workflow_run_id", "spec"},
    "workflow_phase": set(E10) | {"phase", "workflow_run_id", "spec", "spec_version"},
    "session_metrics": set(E10) | {
        "exploration_before_code", "noncode_writes_before_code", "code_writes",
        "unclassified_shell_writes", "tool_calls", "first_code_write", "workflow_run_ids",
        "ended_cleanly", "workflow_run_id", "spec"},
}
NEW_FIELDS = {"stage", "round", "fact_questions", "user_decisions", "split", "picks_differ",
              "fact_id", "dimension", "reason"}
DIMENSIONS = ["load", "data", "concurrency", "environment", "consumers", "roadmap", "failure",
              "cost"]
FACT_A = "67ac615b0c9ad3aa-consumers-brief-telemetry-personal-dashboard.md"
FACT_B = "0123456789abcdef-load-second-topic.md"


def brief_command(script=REL, run_id=RID, stage="understanding", rnd="1", tail="", sub="brief"):
    text = f"python3 {script} {sub} --run-id {run_id} --stage {stage} --round {rnd}"
    return f"{text} {tail}" if tail else text


def bash_payload(command, exit_code=0, **extra):
    payload = {
        "hook_event_name": "PostToolUse",
        "tool_name": "Bash",
        "tool_input": {"command": command},
        "tool_response": {"exit_code": exit_code},
        "session_id": "s-brief",
        "tool_use_id": "toolu_brief",
    }
    payload.update(extra)
    return payload


class BriefCase(TelemetryTestCase):
    def setUp(self):
        self.repo = self.install()

    def snapshot(self, repo):
        return {path: digest for path, digest in super().snapshot(repo).items()
                if "__pycache__" not in Path(path).parts}

    def fire(self, payload, telemetry_dir=None, env=None):
        telemetry_dir = telemetry_dir or self.temp_dir()
        env = env or self.telemetry_env(telemetry_dir)
        result = self.run_hook_env(self.repo, "telemetry_hook.py", payload, env)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stdout, "")
        return telemetry_dir

    def lines(self, telemetry_dir, event, keys, forbidden=()):
        found = [e for e in self.read_events(telemetry_dir, self.repo) if e.get("event") == event]
        for line in found:
            self.assert_safe(line, keys, forbidden)
        return found

    def assert_safe(self, line, keys, forbidden=()):
        self.assertEqual(set(line), keys, line)
        serialized = json.dumps(line)
        for text in ("workflow_marker", "--run-id", "--stage", "--round", *forbidden):
            self.assertNotIn(text, serialized)

    def briefs(self, telemetry_dir, command=None):
        forbidden = [command] if command else []
        return self.lines(telemetry_dir, "brief", BRIEF_KEYS, forbidden)

    def fact_lines(self, telemetry_dir, forbidden=()):
        return self.lines(telemetry_dir, "fact_write", FACT_KEYS, forbidden)

    def emitted(self, command, **kwargs):
        exit_code = kwargs.pop("exit_code", 0)
        telemetry_dir = self.fire(bash_payload(command, exit_code, **kwargs))
        return self.briefs(telemetry_dir, command)

    def marker(self, *args, env=None, repo=None):
        repo = repo or self.repo
        return subprocess.run(
            [sys.executable, str(repo / ".harness" / "bin" / "workflow_marker.py"), *args],
            cwd=repo, env=env, capture_output=True, text=True,
        )

    def stages(self, lines):
        return [(line["stage"], line["round"]) for line in lines]


class TestHookDecisionTable(BriefCase):
    def test_emitting_rules_produce_the_expected_lines_in_command_order(self):
        approval = brief_command(stage="approval")
        decision2 = brief_command(stage="decision", rnd="2")
        cases = {
            "relative script path": (brief_command(), [("understanding", 1)]),
            "absolute script path with suffix": (brief_command(script=ABS), [("understanding", 1)]),
            "flags reordered": (
                f"python3 {REL} brief --round 2 --stage decision --run-id {RID}", [("decision", 2)]),
            "flags reordered with absolute path": (
                f"python3 {ABS} brief --round 2 --stage decision --run-id {RID}", [("decision", 2)]),
            "chained with && and ;": (f"true && {approval}; echo done", [("approval", 1)]),
            "preceded by semicolon": (f"cd /tmp;{approval}", [("approval", 1)]),
            "piped": (f"echo a | {approval}", [("approval", 1)]),
            "followed by pipe": (f"{approval} | cat", [("approval", 1)]),
            "background ampersand": (f"{approval} & echo done", [("approval", 1)]),
            "or chain": (f"false || {approval}", [("approval", 1)]),
            "parenthesised": (f"({approval})", [("approval", 1)]),
            "two occurrences with &&": (
                f"{brief_command()} && {decision2}", [("understanding", 1), ("decision", 2)]),
            "two occurrences with ;": (
                f"{decision2}; {brief_command()}", [("decision", 2), ("understanding", 1)]),
            "invalid occurrence then valid": (
                f"{brief_command(stage='approved')} ; {decision2}", [("decision", 2)]),
            "valid occurrence then invalid": (
                f"{brief_command()} ; {brief_command(stage='approved')}", [("understanding", 1)]),
        }
        for name, (command, expected) in cases.items():
            with self.subTest(rule=name):
                self.assertEqual(self.stages(self.emitted(command)), expected)

    def test_non_matching_commands_emit_no_brief_line(self):
        pid = f"--run-id {RID}"
        cases = {
            "script name without harness bin path": f"python3 workflow_marker.py brief {pid} --stage understanding --round 1",
            "script under harness without dot": brief_command(script="harness/bin/workflow_marker.py"),
            "other directory": brief_command(script="bin/workflow_marker.py"),
            "script name with extra prefix": brief_command(script="x.harness/bin/workflow_marker.py"),
            "plus sign on a count flag": brief_command(tail="--fact-questions +1"),
            "phase subcommand": brief_command(sub="phase"),
            "start subcommand": brief_command(sub="start"),
            "brief not immediately after script": f"python3 {REL} x brief {pid} --stage understanding --round 1",
            "duplicated stage": brief_command(tail="--stage decision"),
            "duplicated run id": brief_command(tail=f"--run-id {RID}"),
            "duplicated round": brief_command(tail="--round 2"),
            "missing run id": f"python3 {REL} brief --stage understanding --round 1",
            "missing stage": f"python3 {REL} brief {pid} --round 1",
            "missing round": f"python3 {REL} brief {pid} --stage understanding",
            "unknown flag": brief_command(tail="--foo x"),
            "stray positional": brief_command(tail="extra"),
            "bad stage": brief_command(stage="approved"),
            "fact questions duplicated": brief_command(tail="--fact-questions 1 --fact-questions 1"),
            "user decisions duplicated": brief_command(tail="--user-decisions 1 --user-decisions 2"),
            "split duplicated": brief_command(tail="--split none --split none"),
            "picks differ duplicated": brief_command(tail="--picks-differ 0 --picks-differ 0"),
            "bad split value": brief_command(tail="--split maybe"),
            "unbalanced double quote": brief_command(tail='"oops'),
            "unbalanced single quote": brief_command(tail="'oops"),
            "unbalanced quote before marker": f"echo \"x; {brief_command()}",
        }
        for name, command in cases.items():
            with self.subTest(rule=name):
                self.assertEqual(self.emitted(command), [])

    def test_nonzero_exit_code_suppresses_emission(self):
        for code in (1, 2, 127):
            with self.subTest(exit_code=code):
                self.assertEqual(self.emitted(brief_command(), exit_code=code), [])

    def test_missing_or_non_integer_exit_code_does_not_suppress_emission(self):
        responses = {
            "empty tool response": {"tool_response": {}},
            "no tool response": {"tool_response": None},
            "string exit code": {"tool_response": {"exit_code": "1"}},
            "null exit code": {"tool_response": {"exit_code": None}},
        }
        for name, extra in responses.items():
            with self.subTest(response=name):
                payload = bash_payload(brief_command())
                if extra["tool_response"] is None:
                    del payload["tool_response"]
                else:
                    payload["tool_response"] = extra["tool_response"]
                telemetry_dir = self.fire(payload)
                self.assertEqual(self.stages(self.briefs(telemetry_dir)), [("understanding", 1)])

    def test_failure_pre_tool_use_and_non_bash_payloads_emit_no_brief_line(self):
        command = brief_command()
        payloads = {
            "post tool use failure": {
                "hook_event_name": "PostToolUseFailure", "tool_name": "Bash",
                "tool_input": {"command": command}, "error_code": "timeout",
                "session_id": "s-brief", "tool_use_id": "toolu_brief"},
            "pre tool use": bash_payload(command, hook_event_name="PreToolUse"),
        }
        for tool in ("Read", "Task", "Write", "Edit"):
            payloads[f"tool {tool}"] = bash_payload(command, tool_name=tool)
        for name, payload in payloads.items():
            with self.subTest(payload=name):
                telemetry_dir = self.fire(payload)
                self.assertEqual(self.briefs(telemetry_dir), [])

    def test_untokenizable_command_exits_zero_with_empty_stdout(self):
        telemetry_dir = self.fire(bash_payload(brief_command(tail="'unterminated")))
        self.assertEqual(self.briefs(telemetry_dir), [])

    def test_brief_detection_leaves_other_events_of_the_call_unchanged(self):
        with_marker = self.fire(bash_payload(brief_command()))
        plain = self.fire(bash_payload("echo done"))

        def others(directory):
            return [e["event"] for e in self.read_events(directory, self.repo) if e["event"] != "brief"]

        self.assertEqual(others(with_marker), others(plain))

    def test_unwritable_telemetry_directory_exits_zero_with_empty_stdout(self):
        blocker = self.temp_dir() / "not-a-dir"
        blocker.write_text("regular file")
        env = self.telemetry_env(blocker)
        self.fire(bash_payload(brief_command()), telemetry_dir=blocker, env=env)
        result = self.marker("brief", "--run-id", RID, "--stage", "understanding", "--round", "1", env=env)
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, "", ""))
        self.assertEqual(blocker.read_text(), "regular file")


class TestBriefBoundaries(BriefCase):
    def test_round_values(self):
        cases = {"0": None, "1": 1, "2": 2, "+1": None, "01": 1}
        for value, expected in cases.items():
            with self.subTest(round=value):
                found = self.emitted(brief_command(rnd=value))
                if expected is None:
                    self.assertEqual(found, [])
                else:
                    self.assertEqual([line["round"] for line in found], [expected])
                    self.assertIs(type(found[0]["round"]), int)

    def test_run_id_shapes(self):
        cases = {
            "15 hex": ("49bafb302bb6593", False),
            "16 hex": (RID, True),
            "17 hex": (RID + "0", False),
            "16 uppercase hex": (RID.upper(), False),
        }
        for name, (run_id, valid) in cases.items():
            with self.subTest(run_id=name):
                found = self.emitted(brief_command(run_id=run_id))
                if valid:
                    self.assertEqual([line["workflow_run_id"] for line in found], [run_id])
                else:
                    self.assertEqual(found, [])

    def test_each_count_flag_boundaries(self):
        flag_to_key = {"--fact-questions": "fact_questions", "--user-decisions": "user_decisions",
                       "--picks-differ": "picks_differ"}
        for flag, key in flag_to_key.items():
            for value, expected in (("-1", None), ("0", 0), ("1", 1)):
                with self.subTest(flag=flag, value=value):
                    found = self.emitted(brief_command(tail=f"{flag} {value}"))
                    if expected is None:
                        self.assertEqual(found, [])
                        continue
                    self.assertEqual(len(found), 1)
                    self.assertEqual(found[0][key], expected)
                    self.assertIs(type(found[0][key]), int)
                    others = {k for k in flag_to_key.values() if k != key} | {"split"}
                    for other in others:
                        self.assertIn(other, found[0])
                        self.assertIsNone(found[0][other])

    def test_split_values(self):
        for value in ("none", "proposed", "accepted", "declined"):
            with self.subTest(split=value):
                found = self.emitted(brief_command(tail=f"--split {value}"))
                self.assertEqual([line["split"] for line in found], [value])
        with self.subTest(split="maybe"):
            self.assertEqual(self.emitted(brief_command(tail="--split maybe")), [])

    def test_absent_optional_flags_are_present_as_null(self):
        (line,) = self.emitted(brief_command())
        for key in ("fact_questions", "user_decisions", "split", "picks_differ"):
            self.assertIn(key, line)
            self.assertIsNone(line[key])

    def test_all_optional_flags_present_carry_their_values(self):
        tail = "--picks-differ 4 --split accepted --user-decisions 3 --fact-questions 2"
        (line,) = self.emitted(brief_command(stage="approval", rnd="3", tail=tail))
        self.assertEqual(
            (line["stage"], line["round"], line["fact_questions"], line["user_decisions"],
             line["split"], line["picks_differ"]),
            ("approval", 3, 2, 3, "accepted", 4),
        )


class TestBriefLineFields(BriefCase):
    def check_envelope(self, line):
        self.assertEqual(line["v"], 1)
        self.assertEqual(line["event"], "brief")
        self.assertEqual(line["harness_version"], VERSION_FILE.read_text().strip())
        self.assertEqual(line["repo"], str(self.repo.resolve()))
        self.assertIsNone(line["spec"])
        self.assertEqual(line["workflow_run_id"], RID)
        datetime.fromisoformat(line["ts"].replace("Z", "+00:00"))

    def test_line_with_agent_fields_equals_the_payload_values(self):
        payload = bash_payload(brief_command(stage="decision", rnd="2"), agent_id="agent-9",
                               agent_type="implementer", session_id="S9", tool_use_id="T9")
        (line,) = self.briefs(self.fire(payload))
        self.check_envelope(line)
        self.assertEqual((line["agent_id"], line["agent_type"]), ("agent-9", "implementer"))
        self.assertEqual((line["session_id"], line["tool_use_id"]), ("S9", "T9"))
        self.assertEqual((line["stage"], line["round"]), ("decision", 2))

    def test_line_without_agent_fields_has_null_agent_values(self):
        (line,) = self.briefs(self.fire(bash_payload(brief_command())))
        self.check_envelope(line)
        self.assertIsNone(line["agent_id"])
        self.assertIsNone(line["agent_type"])
        self.assertEqual((line["session_id"], line["tool_use_id"]), ("s-brief", "toolu_brief"))

    def test_claude_transcript_path_gives_claude_client(self):
        payload = bash_payload(brief_command(), transcript_path="/home/u/.claude/projects/p/s.jsonl")
        (line,) = self.briefs(self.fire(payload))
        self.check_envelope(line)
        self.assertEqual(line["client"], "claude")

    def test_run_id_comes_from_the_flag_not_from_an_active_workflow(self):
        env = self.telemetry_env(self.temp_dir())
        started = self.marker("start", "--run-id", "run-active", "--spec", "orders",
                              "--spec-version", "1", env=env)
        self.assertEqual((started.returncode, started.stdout, started.stderr), (0, "", ""))
        telemetry_dir = Path(env["HARNESS_TELEMETRY_DIR"])
        self.fire(bash_payload(brief_command()), telemetry_dir=telemetry_dir, env=env)
        (line,) = self.briefs(telemetry_dir)
        self.check_envelope(line)


class TestBriefCli(BriefCase):
    def test_valid_and_invalid_argv_exit_zero_silently_and_write_nothing(self):
        cases = {
            "valid minimal": ["brief", "--run-id", RID, "--stage", "understanding", "--round", "1"],
            "valid with all optional flags": [
                "brief", "--run-id", RID, "--stage", "approval", "--round", "2",
                "--fact-questions", "1", "--user-decisions", "2", "--split", "declined",
                "--picks-differ", "0"],
            "no flags": ["brief"],
            "missing run id": ["brief", "--stage", "understanding", "--round", "1"],
            "missing stage": ["brief", "--run-id", RID, "--round", "1"],
            "missing round": ["brief", "--run-id", RID, "--stage", "understanding"],
            "bad stage": ["brief", "--run-id", RID, "--stage", "approved", "--round", "1"],
            "round zero": ["brief", "--run-id", RID, "--stage", "understanding", "--round", "0"],
            "round not an integer": ["brief", "--run-id", RID, "--stage", "understanding",
                                     "--round", "x"],
            "unknown flag": ["brief", "--run-id", RID, "--stage", "understanding", "--round", "1",
                             "--foo", "x"],
            "negative count": ["brief", "--run-id", RID, "--stage", "understanding", "--round", "1",
                               "--fact-questions", "-1"],
            "bad split": ["brief", "--run-id", RID, "--stage", "understanding", "--round", "1",
                          "--split", "maybe"],
        }
        for name, argv in cases.items():
            with self.subTest(argv=name):
                telemetry_dir = self.temp_dir()
                before = self.snapshot(self.repo)
                result = self.marker(*argv, env=self.telemetry_env(telemetry_dir))
                self.assertEqual((result.returncode, result.stdout, result.stderr), (0, "", ""))
                self.assertEqual(list(telemetry_dir.iterdir()), [])
                self.assertEqual(self.snapshot(self.repo), before)

    def test_brief_writes_no_line_even_with_an_active_workflow(self):
        telemetry_dir = self.temp_dir()
        env = self.telemetry_env(telemetry_dir)
        self.marker("start", "--run-id", "run-cli", "--spec", "orders", "--spec-version", "1", env=env)
        result = self.marker("brief", "--run-id", RID, "--stage", "decision", "--round", "1", env=env)
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, "", ""))
        self.assertEqual([e["event"] for e in self.read_events(telemetry_dir, self.repo)],
                         ["workflow_start"])


class TestAmendReason(BriefCase):
    def started(self):
        telemetry_dir = self.temp_dir()
        env = self.telemetry_env(telemetry_dir)
        result = self.marker("start", "--run-id", "run-5", "--spec", "orders", "--spec-version", "1",
                             env=env)
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, "", ""))
        return telemetry_dir, env

    def phase(self, env, *args, run_id="run-5"):
        result = self.marker("phase", "--run-id", run_id, *args, env=env)
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, "", ""))

    def phases(self, telemetry_dir):
        return [e for e in self.read_events(telemetry_dir, self.repo) if e["event"] == "workflow_phase"]

    def test_each_reason_is_recorded_on_the_amend_line(self):
        for reason in ("intent_mismatch", "brief_change", "contract_change", "correction"):
            with self.subTest(reason=reason):
                telemetry_dir, env = self.started()
                self.phase(env, "--phase", "implement_test")
                self.phase(env, "--phase", "amend", "--reason", reason)
                baseline, amend = self.phases(telemetry_dir)
                self.assertEqual(amend["reason"], reason)
                self.assertEqual(amend["phase"], "amend")
                self.assertEqual((amend["workflow_run_id"], amend["spec"]), ("run-5", "orders"))
                self.assertEqual(set(baseline), SHAPES["workflow_phase"])
                self.assertEqual(set(amend), SHAPES["workflow_phase"] | {"reason"})

    def test_absent_reason_is_null_and_invalid_reason_emits_nothing(self):
        telemetry_dir, env = self.started()
        self.phase(env, "--phase", "amend")
        (line,) = self.phases(telemetry_dir)
        self.assertIn("reason", line)
        self.assertIsNone(line["reason"])
        before = len(self.read_events(telemetry_dir, self.repo))

        self.phase(env, "--phase", "amend", "--reason", "bogus")

        self.assertEqual(len(self.read_events(telemetry_dir, self.repo)), before)
        self.phase(env, "--phase", "amend", "--reason", "correction")
        self.assertEqual([p["reason"] for p in self.phases(telemetry_dir)], [None, "correction"])

    def test_non_amend_phases_keep_their_key_set_and_never_carry_a_reason(self):
        telemetry_dir, env = self.started()
        self.phase(env, "--phase", "implement_test")
        self.phase(env, "--phase", "verify")
        self.phase(env, "--phase", "verify", "--reason", "correction")
        self.phase(env, "--phase", "implement_test", "--reason", "brief_change")
        lines = self.phases(telemetry_dir)
        self.assertEqual(len(lines), 4)
        key_sets = {frozenset(line) for line in lines}
        self.assertEqual(key_sets, {frozenset(SHAPES["workflow_phase"])})
        for line in lines:
            self.assertNotIn("reason", line)

    def test_amend_without_matching_active_workflow_emits_nothing(self):
        telemetry_dir, env = self.started()
        self.phase(env, "--phase", "amend", "--reason", "correction", run_id="other-run")
        self.assertEqual(self.phases(telemetry_dir), [])
        idle_dir = self.temp_dir()
        idle_env = self.telemetry_env(idle_dir)
        self.phase(idle_env, "--phase", "amend", "--reason", "correction")
        self.assertEqual(self.phases(idle_dir), [])


class TestFactWrite(BriefCase):
    def write_fact(self, relative, text="# fact\n"):
        path = self.repo / "agent-docs" / "facts" / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        return path

    def write_payload(self, path, tool="Write"):
        return {"hook_event_name": "PostToolUse", "tool_name": tool,
                "tool_input": {"file_path": str(path)}, "tool_response": {},
                "session_id": "s-fact", "tool_use_id": "toolu_fact"}

    def patch_payload(self, *entries):
        body = "".join(f"*** {kind} File: {path}\n+x\n" for kind, path in entries)
        return {"hook_event_name": "PostToolUse", "tool_name": "apply_patch",
                "tool_input": {"command": f"*** Begin Patch\n{body}*** End Patch\n"},
                "session_id": "s-fact", "tool_use_id": "toolu_fact"}

    def facts(self, payload, forbidden=()):
        return self.fact_lines(self.fire(payload), forbidden)

    def test_patterned_name_with_valid_dimension_records_id_and_dimension(self):
        (line,) = self.facts(self.write_payload(self.write_fact(FACT_A)),
                             ["brief-telemetry-personal-dashboard", FACT_A])
        self.assertEqual(line["event"], "fact_write")
        self.assertEqual((line["fact_id"], line["dimension"]), ("67ac615b0c9ad3aa", "consumers"))
        self.assertEqual((line["session_id"], line["tool_use_id"]), ("s-fact", "toolu_fact"))
        self.assertEqual(line["v"], 1)
        self.assertIsNone(line["workflow_run_id"])
        self.assertIsNone(line["spec"])

    def test_every_dimension_token_is_recognised(self):
        for index, dimension in enumerate(DIMENSIONS):
            with self.subTest(dimension=dimension):
                name = f"{index:016x}-{dimension}-some-topic.md"
                (line,) = self.facts(self.write_payload(self.write_fact(name)), ["some-topic", name])
                self.assertEqual((line["fact_id"], line["dimension"]), (f"{index:016x}", dimension))

    def test_unrecognised_names_still_emit_with_null_fields(self):
        cases = {
            "invalid dimension segment": ("67ac615b0c9ad3aa-weather-x.md", "67ac615b0c9ad3aa", None),
            "no id prefix": ("abc-load-x.md", None, None),
            "uppercase id": ("67AC615B0C9AD3AA-load-x.md", None, None),
        }
        for label, (name, fact_id, dimension) in cases.items():
            with self.subTest(case=label):
                (line,) = self.facts(self.write_payload(self.write_fact(name)), [name])
                self.assertEqual((line["fact_id"], line["dimension"]), (fact_id, dimension))

    def test_non_fact_files_emit_nothing(self):
        outside = self.repo / "agent-docs" / "todos"
        outside.mkdir(parents=True, exist_ok=True)
        (outside / FACT_A).write_text("x")
        elsewhere = self.repo / "facts"
        elsewhere.mkdir(exist_ok=True)
        (elsewhere / FACT_A).write_text("x")
        sibling = self.repo / "agent-docs" / "factsx"
        sibling.mkdir(parents=True, exist_ok=True)
        (sibling / FACT_A).write_text("x")
        cases = {
            "index.md": self.write_fact("index.md"),
            "stale.md": self.write_fact("stale.md"),
            "subdirectory file": self.write_fact("stale/x.md"),
            "deep subdirectory file": self.write_fact("stale/deeper/" + FACT_A),
            "non-md file": self.write_fact("notes.txt"),
            "non-md with fact name": self.write_fact(FACT_A.replace(".md", ".txt")),
            "different docs directory": outside / FACT_A,
            "repo-level facts directory": elsewhere / FACT_A,
            "sibling directory prefix": sibling / FACT_A,
        }
        for label, path in cases.items():
            for tool in ("Write", "Edit"):
                with self.subTest(case=label, tool=tool):
                    self.assertEqual(self.facts(self.write_payload(path, tool)), [])

    def test_edit_tool_emits_like_write(self):
        (line,) = self.facts(self.write_payload(self.write_fact(FACT_A), tool="Edit"))
        self.assertEqual((line["fact_id"], line["dimension"]), ("67ac615b0c9ad3aa", "consumers"))

    def test_relative_file_path_emits(self):
        self.write_fact(FACT_A)
        payload = self.write_payload(f"agent-docs/facts/{FACT_A}")
        (line,) = self.facts(payload)
        self.assertEqual((line["fact_id"], line["dimension"]), ("67ac615b0c9ad3aa", "consumers"))

    def test_apply_patch_of_two_fact_files_emits_two_lines_in_order(self):
        self.write_fact(FACT_A)
        self.write_fact(FACT_B)
        payload = self.patch_payload(("Add", f"agent-docs/facts/{FACT_A}"),
                                     ("Update", f"agent-docs/facts/{FACT_B}"))
        lines = self.facts(payload, [FACT_A, FACT_B])
        self.assertEqual([(l["fact_id"], l["dimension"]) for l in lines],
                         [("67ac615b0c9ad3aa", "consumers"), ("0123456789abcdef", "load")])

    def test_apply_patch_skips_non_fact_paths_but_keeps_fact_paths(self):
        self.write_fact(FACT_A)
        self.write_fact("index.md")
        payload = self.patch_payload(("Update", "agent-docs/facts/index.md"),
                                     ("Add", f"agent-docs/facts/{FACT_A}"),
                                     ("Add", "agent-docs/facts/stale/x.md"))
        lines = self.facts(payload)
        self.assertEqual([l["fact_id"] for l in lines], ["67ac615b0c9ad3aa"])

    def test_active_workflow_identity_is_recorded_like_spec_write(self):
        telemetry_dir = self.temp_dir()
        env = self.telemetry_env(telemetry_dir)
        self.marker("start", "--run-id", "run-fact", "--spec", "orders", "--spec-version", "1", env=env)
        payload = self.write_payload(self.write_fact(FACT_A))
        self.fire(payload, telemetry_dir=telemetry_dir, env=env)
        (line,) = self.fact_lines(telemetry_dir)
        self.assertEqual((line["workflow_run_id"], line["spec"]), ("run-fact", "orders"))


class TestLineConfidentiality(BriefCase):
    def test_brief_and_fact_lines_carry_only_enumerated_keys_and_no_free_text(self):
        command = brief_command(
            stage="approval", rnd="2",
            tail="--fact-questions 2 --user-decisions 3 --split proposed --picks-differ 1")
        telemetry_dir = self.fire(bash_payload(command))
        for line in self.briefs(telemetry_dir, command):
            self.assertEqual(set(line), BRIEF_KEYS)
            self.assertNotIn("brief --run-id", json.dumps(line))

        path = self.repo / "agent-docs" / "facts" / FACT_A
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("secret body text")
        payload = {"hook_event_name": "PostToolUse", "tool_name": "Write",
                   "tool_input": {"file_path": str(path), "content": "secret body text"},
                   "tool_response": {}, "session_id": "s", "tool_use_id": "t"}
        fact_dir = self.fire(payload)
        for line in self.fact_lines(fact_dir, [FACT_A, "personal-dashboard", "secret body text",
                                               "agent-docs/facts"]):
            self.assertEqual(set(line), FACT_KEYS)


class TestExistingLineShapes(BriefCase):
    def context(self, active):
        telemetry_dir = self.temp_dir()
        env = self.telemetry_env(telemetry_dir)
        if active:
            started = self.marker("start", "--run-id", "run-48", "--spec", "orders",
                                  "--spec-version", "1", env=env)
            self.assertEqual((started.returncode, started.stdout, started.stderr), (0, "", ""))
        return telemetry_dir, env

    def assert_shape(self, events, kind, active):
        picked = [e for e in events if e["event"] == kind]
        self.assertEqual(len(picked), 1, events)
        line = picked[0]
        self.assertEqual(set(line), SHAPES[kind], sorted(line))
        expected = ("run-48", "orders") if active else (None, None)
        self.assertEqual((line["workflow_run_id"], line["spec"]), expected)
        self.assertEqual([e for e in events if e["event"] == "brief"], [])
        return line

    def each_context(self):
        for active in (False, True):
            with self.subTest(active_workflow=active):
                yield (active, *self.context(active))

    def test_test_command_line(self):
        self.write_spec(self.repo, name="sample", test_command="python3 -m unittest")
        for active, _, _ in self.each_context():
            for code in (0, 1):
                directory, env = self.context(active)
                self.fire(self.post_tool_use_bash("python3  -m unittest", exit_code=code),
                          directory, env)
                line = self.assert_shape(self.read_events(directory, self.repo), "test_command", active)
                self.assertEqual(line["exit_code"], code)

    def test_seed_line(self):
        for active, _, _ in self.each_context():
            for action, code in (("backup", 0), ("restore", 1)):
                directory, env = self.context(active)
                self.fire(self.post_tool_use_bash(
                    f"python3 .harness/bin/seed.py {action} src/a.py", exit_code=code), directory, env)
                line = self.assert_shape(self.read_events(directory, self.repo), "seed", active)
                self.assertEqual((line["action"], line["exit_code"]), (action, code))

    def test_spec_write_line(self):
        spec = self.write_spec(self.repo, name="x", version=3)
        for active, directory, env in self.each_context():
            self.fire(self.post_tool_use_write(spec), directory, env)
            line = self.assert_shape(self.read_events(directory, self.repo), "spec_write", active)
            self.assertEqual(line["version"], 3)

    def test_progress_write_line(self):
        progress = self.write_progress(self.repo, "0123456789abcdef-y.md")
        for active, directory, env in self.each_context():
            self.fire(self.post_tool_use_write(progress), directory, env)
            line = self.assert_shape(self.read_events(directory, self.repo), "progress_write", active)
            self.assertEqual(line["file"], "0123456789abcdef-y.md")

    def test_non_amend_workflow_phase_line(self):
        directory, env = self.context(True)
        for phase in ("implement_test", "verify"):
            result = self.marker("phase", "--run-id", "run-48", "--phase", phase, env=env)
            self.assertEqual((result.returncode, result.stdout, result.stderr), (0, "", ""))
            events = [e for e in self.read_events(directory, self.repo) if e["event"] == "workflow_phase"
                      and e["phase"] == phase]
            (line,) = events
            self.assertEqual(set(line), SHAPES["workflow_phase"])
            self.assertEqual((line["workflow_run_id"], line["spec"]), ("run-48", "orders"))

    def test_session_metrics_line_shape_without_and_with_active_workflow(self):
        for active, directory, env in self.each_context():
            self.fire(self.post_tool_use_bash("echo hi"), directory, env)
            self.fire({"hook_event_name": "SessionEnd", "session_id": "s1"}, directory, env)
            self.assert_shape(self.read_events(directory, self.repo), "session_metrics", active)

    def test_session_metrics_is_unchanged_by_a_valid_brief_marker_command(self):
        def sequence(subcommand):
            directory = self.temp_dir()
            env = self.telemetry_env(directory)
            command = brief_command().replace(" brief ", f" {subcommand} ", 1)
            self.fire(bash_payload(command, session_id="s-diff"), directory, env)
            self.fire({"hook_event_name": "SessionEnd", "session_id": "s-diff"}, directory, env)
            lines = [e for e in self.read_events(directory, self.repo) if e["event"] == "session_metrics"]
            self.assertEqual(len(lines), 1, lines)
            self.assertEqual(set(lines[0]), SHAPES["session_metrics"])
            return {k: v for k, v in lines[0].items() if k != "ts"}

        self.assertEqual(sequence("brief"), sequence("bogus"))

    def test_marker_free_commands_with_marker_script_name_emit_no_brief(self):
        self.write_spec(self.repo, name="sample", test_command="python3 -m unittest")
        for command in ("python3 -m unittest", "python3 .harness/bin/seed.py backup a.py",
                        f"python3 {REL} phase --run-id {RID} --phase verify"):
            with self.subTest(command=command):
                directory = self.fire(self.post_tool_use_bash(command))
                events = self.read_events(directory, self.repo)
                self.assertEqual([e for e in events if e["event"] == "brief"], [])


class TestHookNeverCrashes(BriefCase):
    def test_random_bash_commands_exit_zero_with_empty_stdout(self):
        telemetry_dir = self.temp_dir()
        env = self.telemetry_env(telemetry_dir)
        calls = []
        valid = brief_command(stage="decision", tail="--split none")
        tokens = [REL, ABS, "workflow_marker.py", "brief", "phase", "--run-id", RID, RID.upper(),
                  "--stage", "understanding", "decision", "approval", "bogus", "--round", "0", "1",
                  "+1", "--fact-questions", "--user-decisions", "--split", "--picks-differ",
                  "none", "maybe", "-1", "2", "--foo", ";", "&&", "||", "|", "&", "(", ")", "'", '"',
                  "\\", "`", "$(", "echo", "python3", "true", "\n", "#", valid, f"python3 {REL} brief"]
        separators = st.sampled_from(["", " ", "  ", "\t", "\n"])
        pieces = st.lists(st.tuples(st.one_of(st.sampled_from(tokens),
                                              st.text(alphabet=string.printable, max_size=6)),
                                    separators), max_size=30)
        exit_codes = st.one_of(st.none(), st.integers(-5, 300), st.text(max_size=3), st.booleans())
        responses = st.one_of(st.builds(lambda c: {"exit_code": c}, exit_codes), st.just({}))
        events = st.sampled_from(["PostToolUse", "PostToolUse", "PostToolUseFailure", "PreToolUse"])

        @seed(49)
        @settings(max_examples=300, deadline=None, database=None,
                  suppress_health_check=list(HealthCheck))
        @given(pieces, responses, events)
        def check(parts, response, hook_event):
            calls.append(1)
            command = "".join(text + sep for text, sep in parts)
            payload = bash_payload(command, hook_event_name=hook_event, tool_response=response)
            result = self.run_hook_env(self.repo, "telemetry_hook.py", payload, env)
            self.assertEqual(result.returncode, 0, (command, result.stdout, result.stderr))
            self.assertEqual(result.stdout, "", command)

        check()
        self.assertGreaterEqual(len(calls), 300)


class TestSkillText(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = SKILL.read_text()
        cls.flat = re.sub(r"\s+", " ", cls.text)

    def test_k1_brief_command_line_with_three_stages_and_round(self):
        self.assertIn(
            "python3 .harness/bin/workflow_marker.py brief --run-id ID "
            "--stage understanding|decision|approval --round N", self.flat)

    def test_k2_same_turn_emission_for_each_brief_stage(self):
        windows = [self.flat[max(0, m.start() - 300): m.end() + 300].lower()
                   for m in re.finditer(r"same turn", self.flat, re.IGNORECASE)]
        self.assertTrue(windows, "no 'same turn' statement")
        self.assertTrue(any("understanding round" in w and "decision round" in w
                            and "approval brief" in w and re.search(r"`brief`|workflow_marker\.py brief", w)
                            for w in windows), windows)

    def test_k3_run_id_is_chosen_before_the_understanding_round(self):
        pattern = (r"(run id[^.\n]*before[^.\n]*understanding round"
                   r"|before[^.\n]*understanding round[^.\n]*run id)")
        self.assertRegex(self.flat, re.compile(pattern, re.IGNORECASE))

    def test_k4_amend_reason_flag_lists_four_values(self):
        self.assertIn("--reason intent_mismatch|brief_change|contract_change|correction", self.flat)
        self.assertRegex(self.flat, r"phase --run-id ID --phase amend --reason intent_mismatch\|")

    def test_k5_each_reason_value_has_its_meaning_bound_to_its_own_value(self):
        meanings = {
            "intent_mismatch": r"intent mismatch",
            "brief_change": r"brief item",
            "contract_change": r"contract[- ]only",
            "correction": r"correction batch",
        }
        token = re.compile("|".join(meanings))
        marks = list(token.finditer(self.flat))
        for value, meaning in meanings.items():
            with self.subTest(value=value):
                segments = []
                for index, mark in enumerate(marks):
                    if mark.group(0) != value:
                        continue
                    later = [m for m in marks[index + 1:] if m.group(0) != value]
                    end = later[0].start() if later else mark.end() + 300
                    segments.append(self.flat[mark.end(): min(end, mark.end() + 300)])
                self.assertTrue(any(re.search(meaning, seg, re.IGNORECASE) for seg in segments),
                                segments)

    def after_flag(self, flag, before=0, limit=300):
        found = []
        for match in re.finditer(re.escape(flag) + r"(?![\w-])", self.flat):
            rest = self.flat[match.end(): match.end() + limit]
            cut = re.search(r"--[a-z]", rest)
            found.append(self.flat[max(0, match.start() - before): match.end()]
                         + (rest[: cut.start()] if cut else rest))
        self.assertTrue(found, f"{flag} not mentioned")
        return found

    def assert_flag_meaning(self, flag, patterns, before=0):
        segments = self.after_flag(flag, before)
        self.assertTrue(any(all(re.search(p, seg, re.IGNORECASE) for p in patterns) for seg in segments),
                        segments)

    def test_k6_round_number_counts_rounds_of_that_stage_from_one(self):
        self.assertRegex(self.flat, re.compile(
            r"\bN\b[^.;]{0,60}\bcount\w*[^.;]{0,40}\brounds?\b[^.;]{0,30}\bstage\b"
            r"[^.;]{0,30}\b(from|starting (at|from)) 1\b", re.IGNORECASE))

    def test_k7_fact_questions_flag_counts_questions_asked_in_that_round(self):
        self.assert_flag_meaning("--fact-questions", [r"fact questions", r"\basked\b", r"that round"])

    def test_k8_user_decisions_flag_counts_your_decision_over_the_whole_task(self):
        self.assert_flag_meaning("--user-decisions", [r"your decision", r"whole task", r"so far"])

    def test_k9_split_flag_states_proposed_accepted_declined_and_none(self):
        self.assert_flag_meaning("--split", [
            r"proposed.{0,60}(round that proposes|proposing round|proposes a split)",
            r"accepted.{0,30}declined", r"next round", r"\bnone\b"])

    def test_k10_picks_differ_flag_on_the_approval_brief_counts_differing_decisions(self):
        self.assert_flag_meaning("--picks-differ", [
            r"approval brief", r"decisions?", r"choice[^.;]{0,30}differ\w*[^.;]{0,30}picks file"],
            before=80)


class TestVersionAndMigration(BriefCase):
    def test_version_file_is_0_49_0(self):
        self.assertEqual(VERSION_FILE.read_text().strip(), "0.49.1")

    def test_dry_run_from_0_48_0_announces_only_the_0_49_0_migration(self):
        manifest_path = self.repo / ".harness" / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["version"] = "0.48.0"
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
        before = self.snapshot(self.repo)

        result = run_installer("update", str(self.repo), "--dry-run")

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(re.findall(r"^migration (\d+\.\d+\.\d+):", result.stdout, re.MULTILINE),
                         ["0.49.0", "0.49.1"], result.stdout)
        self.assertRegex(result.stdout, r"(?m)^migration 0\.49\.0: \S")
        section = re.split(r"\n(?=migration \d|Apply migration)",
                           result.stdout.split("migration 0.49.0:", 1)[1])[0].lower()
        for word in ("brief", "fact_write", "amend", "reason"):
            self.assertIn(word, section)
        self.assertRegex(section, r"\bno\b[^\n]*\bfiles?\b")
        self.assertEqual(self.snapshot(self.repo), before)
        self.assertEqual(json.loads(manifest_path.read_text())["version"], "0.48.0")


if __name__ == "__main__":
    unittest.main()

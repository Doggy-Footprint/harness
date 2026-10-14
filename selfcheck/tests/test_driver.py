import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from claude_agent_sdk import (
    AssistantMessage,
    ConversationResetMessage,
    HookEventMessage,
    TextBlock,
    ThinkingBlock,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
)

from selfcheck.agent import driver
from selfcheck.tests import agent_fakes as F
from selfcheck.tests.agent_fakes import (
    BG_TASK, PHRASE, Ask, Probe, Raise, StderrLine, Tool, Wait, bg_changed, init, rate_limit, result,
    result_summary,
)

PROMPT = "PROMPT-TEXT"
GRACE = 120


def queries_so_far(client):
    return len(client.queries)


class FakeSdkError(Exception):
    pass


class LoopTransitionTests(F.DriverCase):
    def test_vo2_d1_first_idle_point_sends_phrase_1_even_without_tool_calls(self):
        out = self.drive([[init(), result()], [result()]])
        self.assertEqual(out.client.queries, [PROMPT, PHRASE])
        self.assertEqual([l["n"] for l in out.user() if l["action"] == "phrase"], [1])

    def test_vo2_d2_idle_after_a_phrase_with_zero_tool_calls_completes(self):
        out = self.drive([[Tool(), result()], [result()]])
        self.assertEqual(out.state["status"], "completed")
        self.assertIsNone(out.state["reason"])
        self.assertEqual(out.state["phrases_sent"], 1)
        self.assertEqual(out.state["tool_calls_since_phrase"], 0)
        self.assertEqual(out.client.queries, [PROMPT, PHRASE])
        self.assertEqual(out.state_file(), out.state)

    def test_vo2_d3_idle_with_tool_calls_below_the_maximum_sends_the_next_phrase(self):
        out = self.drive([[result()], [Tool(), result()], [result()]])
        self.assertEqual(out.client.queries, [PROMPT, PHRASE, PHRASE])
        self.assertEqual([l["n"] for l in out.user() if l["action"] == "phrase"], [1, 2])
        self.assertEqual(out.state["status"], "completed")
        self.assertEqual(out.state["phrases_sent"], 2)

    def test_vo2_d4_phrases_at_the_maximum_with_tool_calls_end_stalled(self):
        out = self.drive(
            [[Tool(), result()], [Tool(), result()], [Tool(), result()]],
            inp=self.make_input(max_user_turns=2),
        )
        self.assertEqual(out.client.queries, [PROMPT, PHRASE, PHRASE])
        self.assertEqual(out.state["status"], "stalled")
        self.assertIsNone(out.state["reason"])
        self.assertEqual(out.state["phrases_sent"], 2)
        self.assertEqual(out.state["tool_calls_since_phrase"], 1)

    def test_vo2_d5_result_with_background_tasks_pending_sends_no_phrase_even_after_long_silence(self):
        script = [[
            bg_changed([BG_TASK]), result(),
            Probe(queries_so_far), Wait(5 * GRACE), Probe(queries_so_far), Wait(20),
        ]]
        out = self.drive(script, inp=self.make_input(wall_clock_s=610))
        self.assertEqual(out.client.probes, [1, 1])
        self.assertEqual(out.client.queries, [PROMPT])
        self.assertEqual(out.state["status"], "capped")

    def test_vo2_d6_tasks_cleared_then_a_further_result_is_an_idle_point(self):
        script = [
            [bg_changed([BG_TASK]), result(), Probe(queries_so_far), bg_changed([]), Probe(queries_so_far), result()],
            [result()],
        ]
        out = self.drive(script)
        self.assertEqual(out.client.probes, [1, 1])
        self.assertEqual(out.client.queries, [PROMPT, PHRASE])
        self.assertEqual(out.state["status"], "completed")

    def test_vo2_d7_tasks_cleared_then_idle_grace_silence_is_an_idle_point(self):
        script = [
            [bg_changed([BG_TASK]), result(), bg_changed([]),
             Wait(GRACE - 1), Probe(queries_so_far), Wait(2), Probe(queries_so_far)],
            [result()],
        ]
        out = self.drive(script)
        self.assertEqual(out.client.probes, [1, 2])
        self.assertEqual(out.client.queries, [PROMPT, PHRASE])
        self.assertEqual(out.state["status"], "completed")

    def test_vo2_d7_grace_silence_is_measured_from_the_last_received_message(self):
        script = [
            [bg_changed([BG_TASK]), result(), Wait(100), bg_changed([]),
             Wait(GRACE - 1), Probe(queries_so_far), Wait(2), Probe(queries_so_far)],
            [result()],
        ]
        out = self.drive(script)
        self.assertEqual(out.client.probes, [1, 2])

    def test_vo2_d7_one_grace_expiry_yields_one_idle_point(self):
        def status_now(client):
            return json.loads((self.out_dir / "state.json").read_text(encoding="utf-8"))["status"]

        script = [
            [bg_changed([BG_TASK]), result(), bg_changed([]), Wait(GRACE + 1)],
            [Wait(3 * GRACE), Probe(status_now), Probe(queries_so_far), result()],
        ]
        out = self.drive(script)
        self.assertEqual(out.client.probes, ["running", 2])
        self.assertEqual(out.state["status"], "completed")
        self.assertEqual(out.state["phrases_sent"], 1)

    def test_vo2_d8_rejected_rate_limit_event_interrupts_with_resets_at_and_session(self):
        script = [[
            init(session_id="sess-1"), rate_limit("allowed"), rate_limit("allowed_warning"), Tool(),
            rate_limit("rejected", resets_at=1791843000, rate_limit_type="five_hour", session_id="sess-2"),
        ]]
        out = self.drive(script)
        self.assertEqual(out.state["status"], "interrupted")
        self.assertEqual(out.state["reason"], "rate_limit_event")
        self.assertEqual(out.state["session_id"], "sess-2")
        self.assertEqual(
            out.state["rate_limit"], {"status": "rejected", "resets_at": 1791843000, "rate_limit_type": "five_hour"}
        )
        self.assertEqual(out.client.queries, [PROMPT])
        self.assertEqual(out.state_file(), out.state)

    def test_vo2_d9_result_with_api_error_429_interrupts(self):
        failing = dict(is_error=True, api_error_status=429, session_id="sess-9", subtype="error_during_execution")
        out = self.drive([[Tool(), result(**failing)]])
        self.assertEqual(out.state["status"], "interrupted")
        self.assertEqual(out.state["reason"], "api_error_429")
        self.assertEqual(out.state["session_id"], "sess-9")
        self.assertIsNone(out.state["rate_limit"])
        self.assertEqual(out.state["results"], [result_summary(**failing)])
        self.assertEqual(out.client.queries, [PROMPT])

    def test_vo2_d10_cap_reached_calls_interrupt_and_ends_capped(self):
        script = [[Tool(), Wait(599), Probe(lambda c: c.interrupts), Wait(1)]]
        out = self.drive(script, inp=self.make_input(wall_clock_s=600))
        self.assertEqual(out.client.probes, [0])
        self.assertEqual(out.client.interrupts, 1)
        self.assertEqual(out.state["status"], "capped")
        self.assertEqual(out.state["reason"], "wall_clock")
        self.assertEqual(out.state["elapsed_s"], 600.0)
        self.assertEqual(out.state_file(), out.state)

    def test_vo2_d11_client_raising_ends_in_error_with_class_and_message(self):
        cases = (
            ("stream", {}, [[init(), Raise(RuntimeError("boom"))]], "RuntimeError: boom", [PROMPT]),
            ("connect", {"connect_error": ValueError("bad connect")}, [[]], "ValueError: bad connect", []),
            ("query", {"query_error": FakeSdkError("query failed")}, [[]], "FakeSdkError: query failed", [PROMPT]),
        )
        for name, kw, script, reason, queries in cases:
            with self.subTest(name):
                self.out_dir = Path(self.tmp) / ("out-" + name)
                self.out_dir.mkdir()
                out = self.drive(script, inp=self.make_input(), **kw)
                self.assertEqual(out.state["status"], "error")
                self.assertEqual(out.state["reason"], reason)
                self.assertEqual(out.client.queries, queries)
                self.assertEqual(out.state_file(), out.state)

    def test_vo2_d12_non_429_error_result_is_an_ordinary_idle_point(self):
        for status in (500, 529, None):
            with self.subTest(api_error_status=status):
                self.out_dir = Path(self.tmp) / ("out-%s" % status)
                self.out_dir.mkdir()
                bad = result(is_error=True, api_error_status=status, subtype="error_during_execution")
                out = self.drive([[bad], [result()]], inp=self.make_input())
                self.assertEqual(out.client.queries, [PROMPT, PHRASE])
                self.assertEqual(out.state["status"], "completed")

    def test_vo2_d13_subagent_hook_calls_count_as_tool_calls(self):
        script = [
            [result()],
            [Tool("Bash", agent_id="agent-1", agent_type="general-purpose"), result()],
            [result()],
        ]
        out = self.drive(script)
        self.assertEqual(out.client.queries, [PROMPT, PHRASE, PHRASE])
        self.assertEqual(out.state["status"], "completed")
        self.assertEqual(out.state["phrases_sent"], 2)

    def test_vo2_d14_resume_sets_the_session_logs_resume_and_carries_counters(self):
        self.clock = F.FakeClock(5000.0)
        resume = {"session_id": "sess-R", "phrases_sent": 2, "elapsed_s": 500.0}
        out = self.drive([[Wait(30), result(session_id="sess-R")]], inp=self.make_input(resume=resume))
        self.assertEqual(out.client.options.resume, "sess-R")
        self.assertEqual(out.client.queries, [PHRASE])
        self.assertEqual(out.user(), [{"t": 500.0, "action": "resume"}])
        self.assertEqual(out.state["status"], "completed")
        self.assertEqual(out.state["phrases_sent"], 2)
        self.assertEqual(out.state["tool_calls_since_phrase"], 0)
        self.assertEqual(out.state["elapsed_s"], 530.0)
        self.assertEqual(out.state["session_id"], "sess-R")

    def test_vo2_d14_resume_numbers_the_next_phrase_after_the_restored_count(self):
        resume = {"session_id": "sess-R", "phrases_sent": 2, "elapsed_s": 500.0}
        out = self.drive(
            [[Tool(), result(session_id="sess-R")], [result()]],
            inp=self.make_input(resume=resume, max_user_turns=4),
        )
        self.assertEqual(out.client.queries, [PHRASE, PHRASE])
        self.assertEqual(
            [(l["action"], l.get("n")) for l in out.user()], [("resume", None), ("phrase", 3)]
        )
        self.assertEqual(out.state["phrases_sent"], 3)

    def test_vo2_d14_carried_elapsed_time_counts_toward_the_cap(self):
        resume = {"session_id": "sess-R", "phrases_sent": 1, "elapsed_s": 500.0}
        script = [[Wait(99), Probe(lambda c: c.interrupts), Wait(1)]]
        out = self.drive(script, inp=self.make_input(resume=resume, wall_clock_s=600))
        self.assertEqual(out.client.probes, [0])
        self.assertEqual(out.client.interrupts, 1)
        self.assertEqual(out.state["status"], "capped")
        self.assertEqual(out.state["elapsed_s"], 600.0)

    def fresh_out(self, name):
        self.out_dir = Path(self.tmp) / ("out-" + name.replace(" ", "-"))
        self.out_dir.mkdir()

    def test_vo2_d2_zero_tool_calls_at_max_user_turns_completes_instead_of_stalling(self):
        cases = (
            ("max 2", 2, [[Tool(), result()], [Tool(), result()], [result()]], [PROMPT, PHRASE, PHRASE], 2),
            ("max 1", 1, [[result()], [result()]], [PROMPT, PHRASE], 1),
        )
        for name, maximum, script, queries, phrases in cases:
            with self.subTest(name):
                self.fresh_out(name)
                out = self.drive(script, inp=self.make_input(max_user_turns=maximum))
                self.assertEqual(out.client.queries, queries)
                self.assertEqual(out.state["status"], "completed")
                self.assertIsNone(out.state["reason"])
                self.assertEqual(out.state["phrases_sent"], phrases)
                self.assertEqual(out.state["tool_calls_since_phrase"], 0)

    def test_vo2_d7_silence_of_any_length_before_the_first_result_is_no_idle_point(self):
        long_silence = 10 * GRACE
        cases = (
            ("empty task list from the start",
             [[init(), Wait(long_silence), Probe(queries_so_far), Wait(20)]], [PROMPT]),
            ("task list cleared without a preceding result",
             [[bg_changed([BG_TASK]), bg_changed([]), Wait(long_silence), Probe(queries_so_far), Wait(20)]], [PROMPT]),
            ("silence after a phrase before its result",
             [[result()], [Wait(long_silence), Probe(queries_so_far), Wait(20)]], [PROMPT, PHRASE]),
        )
        for name, script, queries in cases:
            with self.subTest(name):
                self.fresh_out(name)
                out = self.drive(script, inp=self.make_input(wall_clock_s=long_silence + 10))
                self.assertEqual(out.client.probes, [len(queries)])
                self.assertEqual(out.client.queries, queries)
                self.assertEqual(out.state["status"], "capped")

    def test_vo2_d14_a_failure_before_any_message_keeps_the_stored_session_id(self):
        resume = {"session_id": "sess-R", "phrases_sent": 2, "elapsed_s": 500.0}
        cases = (
            ("connect error", [[]], {"connect_error": ValueError("bad connect")}, "error"),
            ("query error", [[]], {"query_error": FakeSdkError("query failed")}, "error"),
            ("stream error before any message", [[Raise(RuntimeError("boom"))]], {}, "error"),
            ("cap before any message", [[Wait(100)]], {}, "capped"),
        )
        for name, script, kw, status in cases:
            with self.subTest(name):
                self.fresh_out(name)
                out = self.drive(script, inp=self.make_input(resume=resume, wall_clock_s=600), **kw)
                self.assertEqual(out.state["status"], status)
                self.assertEqual(out.state["session_id"], "sess-R")
                self.assertEqual(out.state_file()["session_id"], "sess-R")
                self.assertEqual(out.state_file()["phrases_sent"], 2)


class OutputFileTests(F.DriverCase):
    def test_vo3_o1_main_agent_hook_call_becomes_a_ledger_line(self):
        script = [[Wait(12.3456), Tool("Bash", {"command": "ls"}, tool_use_id="toolu_1", session_id="sess-h"), result()], [result()]]
        out = self.drive(script)
        self.assertEqual(
            out.ledger(),
            [{
                "t": 12.346, "session_id": "sess-h", "agent_id": None, "agent_type": None,
                "tool_name": "Bash", "tool_use_id": "toolu_1", "tool_input": {"command": "ls"},
            }],
        )
        self.assertEqual(out.client.hook_results, [{}])

    def test_vo3_o1_tool_use_id_is_the_hook_argument_else_the_input_field(self):
        cases = (
            ("argument wins", dict(tool_use_id="toolu_arg", input_tool_use_id="toolu_in"), "toolu_arg"),
            ("falls back to input", dict(tool_use_id=None, input_tool_use_id="toolu_in"), "toolu_in"),
        )
        for name, kw, expected in cases:
            with self.subTest(name):
                self.out_dir = Path(self.tmp) / ("out-" + name.split()[0])
                self.out_dir.mkdir()
                out = self.drive([[Tool("Bash", **kw), result()], [result()]], inp=self.make_input())
                self.assertEqual(out.ledger()[0]["tool_use_id"], expected)

    def test_vo3_o2_subagent_hook_call_carries_agent_id_and_type(self):
        script = [[
            Tool("Bash", {"command": "a"}, tool_use_id="toolu_a"),
            Tool("Read", {"file_path": "/x"}, tool_use_id="toolu_b", agent_id="agent-7", agent_type="general-purpose"),
            result(),
        ], [result()]]
        out = self.drive(script)
        ledger = out.ledger()
        self.assertEqual([(l["tool_name"], l["agent_id"], l["agent_type"]) for l in ledger],
                         [("Bash", None, None), ("Read", "agent-7", "general-purpose")])
        self.assertEqual(set(ledger[1]), {"t", "session_id", "agent_id", "agent_type", "tool_name", "tool_use_id", "tool_input"})

    def test_vo3_o3_long_strings_in_tool_input_are_cut_to_4000_with_a_length_sibling(self):
        long_ascii = "x" * 4001
        tool_input = {
            "edits": [{"old_string": long_ascii, "new_string": "ok"}],
            "notes": ["y" * 5000, "z"],
            "content": "c" * 4001,
            "exact": "e" * 4000,
            "korean": "한" * 4001,
            "nested": {"deep": {"text": "d" * 4002}},
        }
        out = self.drive([[Tool("Write", tool_input), result()], [result()]])
        self.assertEqual(
            out.ledger()[0]["tool_input"],
            {
                "edits": [{"old_string": "x" * 4000, "old_string__len": 4001, "new_string": "ok"}],
                "notes": ["y" * 4000, "z"],
                "content": "c" * 4000, "content__len": 4001,
                "exact": "e" * 4000,
                "korean": "한" * 4000, "korean__len": 4001,
                "nested": {"deep": {"text": "d" * 4000, "text__len": 4002}},
            },
        )

    def test_vo3_o4_user_lines_for_answer_allow_and_phrase(self):
        questions = [{"question": "Which?", "header": "H", "options": [{"label": "A (Recommended)", "description": "d"}], "multiSelect": False}]
        script = [[Wait(2.5), Ask(questions), Tool("Edit", {"file_path": "/x"}, ask_permission=True), result()], [result()]]
        out = self.drive(script)
        self.assertEqual(
            out.user(),
            [
                {"t": 2.5, "action": "answer", "questions": questions, "answers": {"Which?": "A (Recommended)"}},
                {"t": 2.5, "action": "allow", "tool_name": "Edit"},
                {"t": 2.5, "action": "phrase", "n": 1},
            ],
        )

    def test_vo3_o5_state_after_an_idle_point_is_running_and_complete(self):
        def read_state(client):
            return json.loads((self.out_dir / "state.json").read_text(encoding="utf-8"))

        first = dict(session_id="sess-1", num_turns=2)
        script = [
            [init(), rate_limit("allowed"), Tool(), result(**first)],
            [Wait(1), Probe(read_state), result(session_id="sess-2")],
        ]
        out = self.drive(script)
        at_idle = out.client.probes[0]
        self.assertEqual(
            set(at_idle),
            {"status", "reason", "session_id", "phrases_sent", "tool_calls_since_phrase", "elapsed_s", "results",
             "rate_limit", "cli_version", "init", "env_keys"},
        )
        self.assertEqual(at_idle["status"], "running")
        self.assertIsNone(at_idle["reason"])
        self.assertEqual(at_idle["session_id"], "sess-1")
        self.assertEqual(at_idle["results"], [result_summary(**first)])
        self.assertEqual(at_idle["rate_limit"], {"status": "allowed", "resets_at": 1791843000, "rate_limit_type": "five_hour"})
        self.assertEqual(at_idle["cli_version"], "2.1.294")
        self.assertEqual(at_idle["init"], F.init_summary())
        self.assertEqual(at_idle["env_keys"], sorted(F.SPEC_ENV_KEYS))
        self.assertEqual(
            out.state,
            {
                "status": "completed", "reason": None, "session_id": "sess-2", "phrases_sent": 1,
                "tool_calls_since_phrase": 0, "elapsed_s": 1.0,
                "results": [result_summary(**first), result_summary(session_id="sess-2")],
                "rate_limit": {"status": "allowed", "resets_at": 1791843000, "rate_limit_type": "five_hour"},
                "cli_version": "2.1.294", "init": F.init_summary(), "env_keys": sorted(F.SPEC_ENV_KEYS),
            },
        )
        self.assertEqual(out.state_file(), out.state)

    def test_vo3_o5_session_id_is_the_latest_seen_in_any_listed_source(self):
        sources = (
            ("system message data", [init(session_id="sess-old"), init(session_id="sess-new")]),
            ("result message", [bg_changed([BG_TASK], "sess-old"), result(session_id="sess-new")]),
            ("rate limit event", [init(session_id="sess-old"), rate_limit("allowed", session_id="sess-new")]),
            ("hook input", [init(session_id="sess-old"), Tool("Bash", session_id="sess-new")]),
        )
        for index, (name, items) in enumerate(sources):
            with self.subTest(name):
                self.out_dir = Path(self.tmp) / ("out-%d" % index)
                self.out_dir.mkdir()
                out = self.drive([items + [Wait(100)]], inp=self.make_input(wall_clock_s=100))
                self.assertEqual(out.state["status"], "capped")
                self.assertEqual(out.state["session_id"], "sess-new")

    def test_vo3_o6_messages_lines_for_every_message_kind(self):
        long_text = "a" * 2500
        long_result = "x" * 2500
        failing = dict(num_turns=4, session_id="sess-3", total_cost_usd=1.5, usage={"input_tokens": 9},
                       model_usage={"m": {"inputTokens": 9}}, api_error_status=500, is_error=True,
                       terminal_reason="max_turns", errors=["e1"], subtype="error_max_turns")
        script = [
            [
                init(),
                AssistantMessage(
                    content=[
                        TextBlock(text=long_text),
                        ToolUseBlock(id="toolu_9", name="Bash", input={"command": "ls"}),
                        ThinkingBlock(thinking="secret reasoning", signature="sig"),
                    ],
                    model="claude-haiku-5-5", parent_tool_use_id="toolu_parent",
                ),
                UserMessage(content=[ToolResultBlock(tool_use_id="toolu_9", content=long_result, is_error=False)],
                            parent_tool_use_id="toolu_p"),
                UserMessage(content="plain text"),
                bg_changed([BG_TASK]),
                HookEventMessage(subtype="hook_started", data={"hook_name": "x"}),
                ConversationResetMessage(new_conversation_id="c-1", uuid="u-1", session_id="s-1"),
                StderrLine("some stderr"),
                Wait(1.5),
                rate_limit("allowed_warning", resets_at=1791843001, rate_limit_type="seven_day"),
                bg_changed([]),
                result(**failing),
            ],
            [result()],
        ]
        out = self.drive(script)
        failing_line = {"t": 1.5, "kind": "ResultMessage", **result_summary(**failing)}
        expected = [
            {"t": 0.0, "kind": "SystemMessage", "subtype": "init"},
            {"t": 0.0, "kind": "AssistantMessage",
             "content": [
                 {"type": "text", "text": "a" * 2000},
                 {"type": "tool_use", "id": "toolu_9", "name": "Bash", "input": {"command": "ls"}},
                 {"type": "thinking"},
             ],
             "model": "claude-haiku-5-5", "parent_tool_use_id": "toolu_parent"},
            {"t": 0.0, "kind": "UserMessage",
             "content": [{"type": "tool_result", "tool_use_id": "toolu_9", "is_error": False, "text": "x" * 2000}],
             "parent_tool_use_id": "toolu_p"},
            {"t": 0.0, "kind": "UserMessage", "content": [{"type": "text", "text": "plain text"}],
             "parent_tool_use_id": None},
            {"t": 0.0, "kind": "SystemMessage", "subtype": "background_tasks_changed", "tasks": [BG_TASK]},
            {"t": 0.0, "kind": "HookEventMessage", "subtype": "hook_started"},
            {"t": 0.0, "kind": "ConversationResetMessage"},
            {"t": 0.0, "kind": "stderr", "line": "some stderr"},
            {"t": 1.5, "kind": "RateLimitEvent", "status": "allowed_warning", "resets_at": 1791843001,
             "rate_limit_type": "seven_day"},
            {"t": 1.5, "kind": "SystemMessage", "subtype": "background_tasks_changed", "tasks": []},
            failing_line,
            {"t": 1.5, "kind": "ResultMessage", **result_summary()},
        ]
        self.assertEqual(out.messages(), expected)

    def test_vo3_o6_user_message_and_tool_result_rendering(self):
        def tool_result(content, is_error, parent):
            return UserMessage(content=[ToolResultBlock(tool_use_id="toolu_r", content=content, is_error=is_error)],
                               parent_tool_use_id=parent)

        def line(text, is_error, parent):
            return {"t": 0.0, "kind": "UserMessage",
                    "content": [{"type": "tool_result", "tool_use_id": "toolu_r", "is_error": is_error, "text": text}],
                    "parent_tool_use_id": parent}

        items = [
            UserMessage(content="s" * 2500),
            tool_result("plain output", False, None),
            tool_result([{"type": "text", "text": "first"}, {"type": "text", "text": "second"}], True, "toolu_p"),
            tool_result([{"type": "text", "text": "x" * 1500}, {"type": "text", "text": "y" * 1500}], False, None),
        ]
        out = self.drive([items + [result()], [result()]])
        joined_long = ("x" * 1500 + "\n" + "y" * 1500)[:2000]
        self.assertEqual(
            out.messages()[:4],
            [
                {"t": 0.0, "kind": "UserMessage", "content": [{"type": "text", "text": "s" * 2000}],
                 "parent_tool_use_id": None},
                line("plain output", False, None),
                line("first\nsecond", True, "toolu_p"),
                line(joined_long, False, None),
            ],
        )

    def test_vo3_o7_first_init_message_fixes_cli_version_and_init_summary(self):
        script = [
            [init(), init(claude_code_version="9.9.9", model="other-model"), result()],
            [result()],
        ]
        out = self.drive(script)
        self.assertEqual(out.state["cli_version"], "2.1.294")
        self.assertEqual(out.state["init"], F.init_summary())

    def test_vo3_o8_a_resumed_run_appends_to_the_existing_logs_and_replaces_state_json(self):
        old = {
            "messages.jsonl": [{"t": 1.0, "kind": "OLD-MESSAGE"}, {"t": 2.0, "kind": "OLD-MESSAGE-2"}],
            "ledger.jsonl": [{"t": 1.5, "tool_name": "OLD-LEDGER"}],
            "user.jsonl": [{"t": 0.5, "action": "phrase", "n": 1}, {"t": 0.6, "action": "phrase", "n": 2}],
        }
        old_text = {}
        for name, lines in old.items():
            old_text[name] = "".join(json.dumps(line) + "\n" for line in lines)
            (self.out_dir / name).write_text(old_text[name], encoding="utf-8")
        (self.out_dir / "state.json").write_text(json.dumps({"status": "running", "marker": "OLD-STATE"}), encoding="utf-8")

        resume = {"session_id": "sess-R", "phrases_sent": 2, "elapsed_s": 10.0}
        script = [
            [init(session_id="sess-R"), Tool("Bash", {"command": "ls"}, tool_use_id="toolu_1", session_id="sess-R"),
             result(session_id="sess-R")],
            [result(session_id="sess-R")],
        ]
        out = self.drive(script, inp=self.make_input(resume=resume, max_user_turns=5))
        self.assertEqual(out.state["status"], "completed")
        for name in old:
            with self.subTest(name):
                text = (self.out_dir / name).read_text(encoding="utf-8")
                self.assertTrue(text.startswith(old_text[name]), "pre-existing lines must be kept byte for byte")
                self.assertGreater(len(text), len(old_text[name]))
        lines = lambda name: F.read_jsonl(self.out_dir / name)[len(old[name]):]
        self.assertEqual(F.read_jsonl(self.out_dir / "messages.jsonl")[:2], old["messages.jsonl"])
        self.assertEqual(
            [(l["kind"], l.get("subtype")) for l in lines("messages.jsonl")],
            [("SystemMessage", "init"), ("ResultMessage", "success"), ("ResultMessage", "success")],
        )
        self.assertEqual([l["tool_name"] for l in lines("ledger.jsonl")], ["Bash"])
        self.assertEqual(
            lines("user.jsonl"),
            [{"t": 10.0, "action": "resume"}, {"t": 10.0, "action": "phrase", "n": 3}],
        )
        self.assertEqual(out.state_file(), out.state)
        self.assertNotIn("marker", out.state_file())
        self.assertEqual(out.state["phrases_sent"], 3)

    def test_vo3_o9_state_json_counts_every_hook_call_since_the_last_phrase(self):
        script = [
            [result()],
            [Tool("Bash", tool_use_id="toolu_a"), Tool("Read", tool_use_id="toolu_b", agent_id="agent-1", agent_type="general-purpose"),
             Tool("Edit", tool_use_id="toolu_c"), result()],
        ]
        out = self.drive(script, inp=self.make_input(max_user_turns=1))
        self.assertEqual(out.state["status"], "stalled")
        self.assertEqual(out.state["tool_calls_since_phrase"], 3)
        self.assertEqual(out.state_file()["tool_calls_since_phrase"], 3)
        self.assertEqual(len(out.ledger()), 3)

    def test_vo3_o10_a_content_block_of_another_class_is_logged_by_its_class_name(self):
        class OddBlock:
            pass

        script = [[
            AssistantMessage(content=[TextBlock(text="hi"), OddBlock()], model="claude-haiku-5-5", parent_tool_use_id=None),
            UserMessage(content=[OddBlock(), TextBlock(text="after")], parent_tool_use_id=None),
            result(),
        ], [result()]]
        out = self.drive(script)
        messages = out.messages()
        self.assertEqual(messages[0]["content"], [{"type": "text", "text": "hi"}, {"type": "OddBlock"}])
        self.assertEqual(messages[1]["content"], [{"type": "OddBlock"}, {"type": "text", "text": "after"}])

    def test_vo3_o11_a_disconnect_exception_keeps_status_and_reason_and_adds_one_line(self):
        cases = (
            ("completed", [[result()], [result()]], 0.0, "completed", None),
            ("capped", [[Tool(), Wait(600)]], 600.0, "capped", "wall_clock"),
            ("error", [[init(), Raise(RuntimeError("boom"))]], 0.0, "error", "RuntimeError: boom"),
        )
        for name, script, elapsed, status, reason in cases:
            with self.subTest(name):
                self.out_dir = Path(self.tmp) / ("out-" + name)
                self.out_dir.mkdir()
                out = self.drive(script, inp=self.make_input(wall_clock_s=600), disconnect_error=OSError("disc fail"))
                self.assertEqual(out.state["status"], status)
                self.assertEqual(out.state["reason"], reason)
                self.assertEqual(out.state_file()["status"], status)
                self.assertEqual(out.state_file()["reason"], reason)
                lines = [l for l in out.messages() if l["kind"] == "disconnect_error"]
                self.assertEqual(lines, [{"t": elapsed, "kind": "disconnect_error", "line": "OSError: disc fail"}])
                self.assertEqual(out.messages()[-1], lines[0])


class BuildOptionsTests(unittest.TestCase):
    def setUp(self):
        self.inp = F.driver_input("/selfcheck/out", "/run/secrets/oauth_token", resume=None)
        self.environ = mock.patch.dict(os.environ, {"PATH": "/x/bin:/y/bin"})
        self.environ.start()
        self.addCleanup(self.environ.stop)

    def test_vo4_b1_every_listed_option_value(self):
        options = driver.build_options(self.inp, "tok-secret")
        self.assertEqual(str(options.cwd), "/testbed")
        self.assertEqual(options.permission_mode, "bypassPermissions")
        self.assertEqual(options.setting_sources, ["project"])
        self.assertEqual(options.system_prompt, {"type": "preset", "preset": "claude_code"})
        self.assertEqual(options.model, "claude-haiku-5-5")
        self.assertEqual(options.effort, "medium")
        self.assertEqual(options.disallowed_tools, F.SPEC_AGENT_CFG["disallowed_tools"])
        self.assertEqual(options.mcp_servers, {})
        self.assertIs(options.strict_mcp_config, True)
        self.assertTrue(callable(options.can_use_tool))
        self.assertTrue(callable(options.stderr))
        self.assertEqual(set(options.hooks), {"PreToolUse"})
        matchers = options.hooks["PreToolUse"]
        self.assertEqual(len(matchers), 1)
        self.assertIsNone(matchers[0].matcher)
        self.assertEqual(len(matchers[0].hooks), 1)

    def test_vo4_b2_every_listed_env_key_and_value(self):
        options = driver.build_options(self.inp, "tok-secret")
        aliases = self.inp["aliases"]
        self.assertEqual(
            options.env,
            {
                "CLAUDE_CODE_OAUTH_TOKEN": "tok-secret",
                "CLAUDE_CONFIG_DIR": "/selfcheck/out/claude",
                "CLAUDE_ENV_FILE": "/opt/selfcheck/env.sh",
                "PATH": "/opt/selfcheck/bin:/x/bin:/y/bin",
                "HARNESS_TELEMETRY_DIR": "/selfcheck/out/telemetry",
                "HTTPS_PROXY": "http://selfcheck-proxy:3128",
                "HTTP_PROXY": "http://selfcheck-proxy:3128",
                "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
                "DISABLE_AUTOUPDATER": "1",
                "CLAUDE_CODE_DISABLE_AUTO_MEMORY": "1",
                "ANTHROPIC_DEFAULT_OPUS_MODEL": aliases["opus"],
                "ANTHROPIC_DEFAULT_SONNET_MODEL": aliases["sonnet"],
                "ANTHROPIC_DEFAULT_HAIKU_MODEL": aliases["haiku"],
            },
        )
        self.assertEqual(set(options.env), F.SPEC_ENV_KEYS)

    def test_vo4_b3_resume_sets_the_resume_option_from_the_stored_session(self):
        self.assertIsNone(driver.build_options(self.inp, "tok").resume)
        resumed = dict(self.inp, resume={"session_id": "sess-R", "phrases_sent": 1, "elapsed_s": 3.0})
        self.assertEqual(driver.build_options(resumed, "tok").resume, "sess-R")

    def test_vo4_b4_path_prefix_keeps_the_inherited_path(self):
        with mock.patch.dict(os.environ, {"PATH": "/a/bin:/b/bin:/c"}):
            options = driver.build_options(self.inp, "tok")
        self.assertEqual(options.env["PATH"], "/opt/selfcheck/bin:/a/bin:/b/bin:/c")

    def test_vo4_b5_only_the_oauth_variable_holds_the_token(self):
        token = "tok-very-secret-value"
        options = driver.build_options(self.inp, token)
        holders = [k for k, v in options.env.items() if token in v]
        self.assertEqual(holders, ["CLAUDE_CODE_OAUTH_TOKEN"])


class TokenFileTests(F.DriverCase):
    def test_vo4_b2_run_reads_the_token_file_and_strips_it(self):
        self.assertTrue(Path(self.token_path).read_text(encoding="utf-8").endswith("\n"))
        out = self.drive([[result()], [result()]])
        self.assertEqual(out.client.options.env["CLAUDE_CODE_OAUTH_TOKEN"], self.token)
        self.assertEqual(set(out.client.options.env), F.SPEC_ENV_KEYS)


class MainTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="drvmain-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.out_dir = Path(self.tmp) / "out"
        self.out_dir.mkdir()
        self.token_path, _ = F.write_token_file(self.tmp)
        self.inp = F.driver_input(self.out_dir, self.token_path)

    def write(self, text):
        path = Path(self.tmp) / "input.json"
        path.write_text(text, encoding="utf-8")
        return str(path)

    def test_vo3_sig_unreadable_input_exits_2_and_writes_nothing_under_out_dir(self):
        cases = [("missing file", str(Path(self.tmp) / "absent.json")), ("invalid json", self.write("{not json"))]
        for key in sorted(self.inp):
            cases.append(("missing key " + key, self.write(json.dumps({k: v for k, v in self.inp.items() if k != key}))))
        for name, path in cases:
            with self.subTest(name):
                self.assertEqual(driver.main([path]), 2)
                self.assertEqual(sorted(self.out_dir.iterdir()), [])

    def test_vo3_sig_every_terminal_state_exits_0(self):
        path = self.write(json.dumps(self.inp))
        for status in ("completed", "stalled", "capped", "interrupted", "error"):
            with self.subTest(status):
                with mock.patch.object(driver, "run", return_value={"status": status}) as fake_run:
                    self.assertEqual(driver.main([path]), 0)
                self.assertEqual(fake_run.call_args[0][0], self.inp)


if __name__ == "__main__":
    unittest.main()

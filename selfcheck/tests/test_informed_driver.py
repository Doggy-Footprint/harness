"""Spec 54ad633104783ebe O5/O6: selfcheck.agent.informed_driver with a fake SDK client and a fake relay responder.

A thread (agent_fakes.RelayResponder) plays the host relay against a temporary relay directory. Expected labels for
the fallback answers are written from user_sim's documented rule (Recommended label, else approval word, else first).
"""
import asyncio
import json
import shutil
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from claude_agent_sdk import AssistantMessage, TextBlock, ThinkingBlock, ToolUseBlock

from selfcheck.agent import informed_driver
from selfcheck.tests import agent_fakes as F
from selfcheck.tests.agent_fakes import Ask, Probe, Tool, Wait, result

PROMPT = "PROMPT-TEXT"
PHRASE = F.PHRASE
Q1, Q2 = "Which option?", "Proceed with the plan?"
QS = [
    {"question": Q1, "header": "H1", "multiSelect": False,
     "options": [{"label": "Alpha (Recommended)", "description": "d"}, {"label": "Beta", "description": "d"}]},
    {"question": Q2, "header": "H2", "multiSelect": False,
     "options": [{"label": "Yes, proceed", "description": "d"}, {"label": "No", "description": "d"}]},
]
FALLBACK = {Q1: "Alpha (Recommended)", Q2: "Yes, proceed"}
ROW_KEYS_ANSWER = {"t", "action", "questions", "answers", "informed", "source"}
STATE_KEYS = {"status", "reason", "session_id", "phrases_sent", "tool_calls_since_phrase", "elapsed_s", "results",
              "rate_limit", "cli_version", "init", "env_keys"}


def asst(text, parent=None, extra=()):
    return AssistantMessage(content=[TextBlock(text=text), *extra], model="claude-haiku-5-5", parent_tool_use_id=parent)


def by_kind(ask=None, idle=None):
    def policy(req):
        out = ask if req["kind"] == "ask" else idle
        return out(req) if callable(out) else out
    return policy


class InformedCase(F.DriverCase):
    def setUp(self):
        super().setUp()
        self.relay_dir = Path(self.tmp) / "relay"
        self.relay_dir.mkdir()

    def make_input(self, **over):
        base = dict(user_mode="informed", relay_dir=str(self.relay_dir), relay_timeout_s=5.0, relay_poll_s=0.01)
        base.update(over)
        return F.driver_input(self.out_dir, self.token_path, **base)

    def drive(self, script, *, policy=None, poll_s=0.01, clock=None, inp=None, responder_cls=None, **client_kw):
        clock = clock or self.clock
        factory = F.ClientFactory(script, clock, poll_s=poll_s, **client_kw)
        with F.RelayResponder(self.relay_dir, policy) as responder:
            state = informed_driver.run(inp or self.make_input(), factory, clock, poll_s=poll_s)
        self.responder = responder
        out = F.Outcome(state, factory, self.out_dir)
        self.assertEqual(out.client.callback_errors, [])
        return out

    def rows(self, out, action):
        return [l for l in out.user() if l["action"] == action]

    @staticmethod
    def without_t(row):
        return {k: v for k, v in row.items() if k != "t"}


class AskTests(InformedCase):
    def ask_script(self):
        return [[Ask(QS), result()], [result()]]

    def run_ask(self, body, **kw):
        return self.drive(self.ask_script(), policy=by_kind(ask=body, idle={"message": None}), **kw)

    def test_o5_c6_both_answers_come_from_the_reviewer(self):
        out = self.run_ask({"answers": {Q1: "R1 text", Q2: "R2 text"}})
        answers = {Q1: "R1 text", Q2: "R2 text"}
        self.assertEqual(out.client.permission_results[0].updated_input, {"questions": QS, "answers": answers})
        (row,) = self.rows(out, "answer")
        self.assertEqual(set(row), ROW_KEYS_ANSWER)
        self.assertEqual(self.without_t(row), {"action": "answer", "questions": QS, "answers": answers, "informed": 1,
                                               "source": {Q1: "reviewer", Q2: "reviewer"}})
        self.assertEqual(self.responder.seen[0], {"n": 1, "kind": "ask", "questions": QS})
        self.assertEqual(out.state["status"], "completed")

    def test_o5_c7_partial_null_missing_or_empty_answer_falls_back_for_that_question_only(self):
        cases = (("null", {Q1: "R1 text", Q2: None}), ("missing key", {Q1: "R1 text"}), ("empty string", {Q1: "R1 text", Q2: ""}))
        for name, answers in cases:
            with self.subTest(name):
                self.relay_dir = Path(self.tmp) / ("relay-" + name.replace(" ", "-"))
                self.relay_dir.mkdir()
                self.out_dir = Path(self.tmp) / ("out-" + name.replace(" ", "-"))
                self.out_dir.mkdir()
                out = self.run_ask({"answers": answers})
                expected = {Q1: "R1 text", Q2: FALLBACK[Q2]}
                self.assertEqual(out.client.permission_results[0].updated_input["answers"], expected)
                (row,) = self.rows(out, "answer")
                self.assertEqual(row["answers"], expected)
                self.assertEqual(row["source"], {Q1: "reviewer", Q2: "fallback"})

    def test_o5_all_null_answers_fall_back_everywhere(self):
        out = self.run_ask({"answers": {Q1: None, Q2: None}})
        (row,) = self.rows(out, "answer")
        self.assertEqual(row["answers"], FALLBACK)
        self.assertEqual(row["source"], {Q1: "fallback", Q2: "fallback"})

    def test_o5_c8_timeout_gives_user_sim_answers_for_every_question(self):
        clock = F.HybridClock()
        started = clock()
        out = self.drive(self.ask_script(), policy=None, clock=clock, inp=self.make_input(relay_timeout_s=0.3))
        (row,) = self.rows(out, "answer")
        self.assertGreaterEqual(row["t"], 0.299, "fallback before relay_timeout_s elapsed")
        self.assertGreaterEqual(clock() - started, 0.3)
        self.assertEqual(row["answers"], FALLBACK)
        self.assertEqual(row["source"], {Q1: "fallback", Q2: "fallback"})
        self.assertEqual(row["informed"], 1)
        self.assertEqual(out.client.permission_results[0].updated_input["answers"], FALLBACK)
        self.assertEqual(out.state["status"], "completed")

    def test_o5_late_response_after_the_timeout_is_ignored(self):
        out = self.drive(self.ask_script(), policy=by_kind(ask=("delay", 0.5, {"answers": {Q1: "late", Q2: "late"}})),
                         clock=F.HybridClock(), inp=self.make_input(relay_timeout_s=0.25))
        (row,) = self.rows(out, "answer")
        self.assertEqual(row["answers"], FALLBACK)
        self.assertEqual(row["source"], {Q1: "fallback", Q2: "fallback"})

    def test_o5_malformed_response_file_falls_back_immediately_without_waiting_for_the_timeout(self):
        for name, raw in (("not json", "{ not json"), ("list", '["x"]'), ("answers wrong type", '{"n": 1, "answers": "oops"}')):
            with self.subTest(name):
                self.relay_dir = Path(self.tmp) / ("relay-" + name.replace(" ", "-"))
                self.relay_dir.mkdir()
                self.out_dir = Path(self.tmp) / ("out-" + name.replace(" ", "-"))
                self.out_dir.mkdir()
                started = time.monotonic()
                out = self.drive(self.ask_script(), policy=by_kind(ask=("raw", raw), idle={"message": None}),
                                 clock=F.HybridClock(), inp=self.make_input(relay_timeout_s=60))
                self.assertLess(time.monotonic() - started, 20)
                (row,) = self.rows(out, "answer")
                self.assertEqual(row["answers"], FALLBACK)
                self.assertEqual(row["source"], {Q1: "fallback", Q2: "fallback"})

    def test_o5_c8_wall_clock_cap_fires_while_a_request_is_outstanding(self):
        clock = F.FakeClock(1000.0)
        stop = threading.Event()
        rescued = {}

        def ticker():
            for _ in range(100):
                if stop.wait(0.05):
                    return
                clock.advance(40)

        def rescue():
            # a loop blocked on the request would only end now
            if not stop.wait(4.0):
                rescued["interrupts"] = self.interrupts_at_rescue()
                F.RelayResponder(self.relay_dir).write(1, {"answers": {Q1: "r", Q2: "r"}})

        holder = {}
        self.interrupts_at_rescue = lambda: holder["factory"].clients[0].interrupts
        threads = [threading.Thread(target=ticker, daemon=True), threading.Thread(target=rescue, daemon=True)]
        factory = F.ClientFactory([[Ask(QS)]], clock, poll_s=0.01)
        holder["factory"] = factory
        for t in threads:
            t.start()
        try:
            with F.RelayResponder(self.relay_dir, None):
                state = informed_driver.run(self.make_input(wall_clock_s=60, relay_timeout_s=100000), factory, clock,
                                            poll_s=0.01)
        finally:
            stop.set()
        self.assertEqual(state["status"], "capped")
        self.assertEqual(state["reason"], "wall_clock")
        self.assertEqual(factory.clients[0].interrupts, 1)
        self.assertNotIn("interrupts", rescued, "the cap waited for the relay request")

    def test_o5_state_schema_and_other_tools_are_unchanged(self):
        script = [[Tool("Bash"), Tool("Edit", {"file_path": "/x"}, ask_permission=True), Ask(QS), result()], [result()]]
        out = self.drive(script, policy=by_kind(ask={"answers": {Q1: "a", Q2: "b"}}, idle={"message": None}))
        self.assertEqual(set(out.state), STATE_KEYS)
        allow = [self.without_t(l) for l in out.user() if l["action"] == "allow"]
        self.assertEqual(allow, [{"action": "allow", "tool_name": "Edit"}])
        self.assertEqual(out.ledger()[0]["tool_name"], "Bash")


class IdleTests(InformedCase):
    def test_o6_c9_idle_sends_the_reviewer_message_with_the_brief_since_the_last_query(self):
        script = [[asst("Plan: use approach A"), result()], [result()]]
        out = self.drive(script, policy=by_kind(idle={"message": "That is wrong; expect X"}))
        self.assertEqual(self.responder.seen, [{"n": 1, "kind": "idle", "brief": "Plan: use approach A"}])
        self.assertEqual(out.client.queries, [PROMPT, "That is wrong; expect X"])
        (row,) = self.rows(out, "phrase")
        self.assertEqual(self.without_t(row), {"action": "phrase", "n": 1, "informed": 1, "source": "reviewer"})
        self.assertEqual(out.state["phrases_sent"], 1)
        self.assertEqual(out.state["status"], "completed")

    def test_o6_brief_covers_main_thread_text_since_the_last_query_only(self):
        script = [
            [asst("first-turn text"), Tool(), result()],
            [asst("sub text", parent="toolu_p"),
             asst("second-turn text", extra=[ToolUseBlock(id="t1", name="Bash", input={"command": "ls"}),
                                             ThinkingBlock(thinking="secret reasoning", signature="s")]),
             Tool(), result()],
            [result()],
        ]
        policy = by_kind(idle=lambda req: {"message": "M%d" % req["n"]})
        out = self.drive(script, policy=policy)
        briefs = [r["brief"] for r in self.responder.seen]
        self.assertEqual(briefs, ["first-turn text", "second-turn text"])
        self.assertEqual(out.client.queries, [PROMPT, "M1", "M2"])
        rows = self.rows(out, "phrase")
        self.assertEqual([self.without_t(r) for r in rows], [
            {"action": "phrase", "n": 1, "informed": 1, "source": "reviewer"},
            {"action": "phrase", "n": 2, "informed": 2, "source": "reviewer"},
        ])

    def test_o6_brief_concatenates_several_main_thread_messages_in_order(self):
        script = [[asst("alpha-text"), asst("beta-text"), result()], [result()]]
        self.drive(script, policy=by_kind(idle={"message": None}))
        brief = self.responder.seen[0]["brief"]
        self.assertIn("alpha-text", brief)
        self.assertIn("beta-text", brief)
        self.assertLess(brief.index("alpha-text"), brief.index("beta-text"))

    def test_o6_c10_null_empty_or_missing_message_sends_phrase_as_fallback(self):
        for name, body in (("null", {"message": None}), ("empty", {"message": ""}), ("missing", {})):
            with self.subTest(name):
                self.relay_dir = Path(self.tmp) / ("relay-" + name)
                self.relay_dir.mkdir()
                self.out_dir = Path(self.tmp) / ("out-" + name)
                self.out_dir.mkdir()
                out = self.drive([[result()], [result()]], policy=by_kind(idle=body))
                self.assertEqual(out.client.queries, [PROMPT, PHRASE])
                (row,) = self.rows(out, "phrase")
                self.assertEqual(self.without_t(row), {"action": "phrase", "n": 1, "informed": 1, "source": "fallback"})
                self.assertEqual(out.state["phrases_sent"], 1)

    def test_o6_timeout_sends_phrase_as_fallback(self):
        clock = F.HybridClock()
        out = self.drive([[result()], [result()]], policy=None, clock=clock, inp=self.make_input(relay_timeout_s=0.3))
        self.assertEqual(out.client.queries, [PROMPT, PHRASE])
        (row,) = self.rows(out, "phrase")
        self.assertGreaterEqual(row["t"], 0.299, "fallback before relay_timeout_s elapsed")
        self.assertEqual(row["source"], "fallback")

    def test_o6_malformed_response_file_sends_phrase_immediately(self):
        started = time.monotonic()
        out = self.drive([[result()], [result()]], policy=by_kind(idle=("raw", "{ nope")), clock=F.HybridClock(),
                         inp=self.make_input(relay_timeout_s=60))
        self.assertLess(time.monotonic() - started, 20)
        self.assertEqual(out.client.queries, [PROMPT, PHRASE])
        self.assertEqual(self.rows(out, "phrase")[0]["source"], "fallback")

    def test_o6_stop_rule_completed_after_a_reviewer_message(self):
        script = [[Tool(), result()], [result()]]
        out = self.drive(script, policy=by_kind(idle={"message": "M"}))
        self.assertEqual(out.client.queries, [PROMPT, "M"])
        self.assertEqual(out.state["status"], "completed")
        self.assertEqual(out.state["tool_calls_since_phrase"], 0)
        self.assertEqual(len(self.responder.seen), 1, "the stop decision must not ask the reviewer")

    def test_o6_stop_rule_stalled_after_a_reviewer_message(self):
        script = [[result()], [Tool(), result()]]
        out = self.drive(script, policy=by_kind(idle={"message": "M"}), inp=self.make_input(max_user_turns=1))
        self.assertEqual(out.client.queries, [PROMPT, "M"])
        self.assertEqual(out.state["status"], "stalled")
        self.assertEqual(out.state["phrases_sent"], 1)
        self.assertEqual(out.state["tool_calls_since_phrase"], 1)
        self.assertEqual(len(self.responder.seen), 1)

    def test_o6_c11_resume_prompt_is_phrase_without_a_request_and_numbering_continues(self):
        for n in (5, 6):
            (self.relay_dir / ("req-%d.json" % n)).write_text(json.dumps({"n": n, "kind": "idle", "brief": ""}))
            (self.relay_dir / ("resp-%d.json" % n)).write_text(json.dumps({"n": n, "message": None}))
        resume = {"session_id": "sess-R", "phrases_sent": 2, "elapsed_s": 50.0}
        script = [[Tool(), result(session_id="sess-R")], [result()]]
        seen_numbers = []

        def policy(req):
            seen_numbers.append(req["n"])
            return {"message": "after resume"}

        out = self.drive(script, policy=policy, inp=self.make_input(resume=resume, max_user_turns=4))
        self.assertEqual(out.client.queries, [PHRASE, "after resume"])
        user = out.user()
        self.assertEqual(self.without_t(user[0]), {"action": "resume"})
        self.assertEqual(self.without_t(user[1]), {"action": "phrase", "n": 3, "informed": 7, "source": "reviewer"})
        self.assertFalse((self.relay_dir / "req-8.json").exists())


class TickClient(F.FakeClient):
    """Fake client that also runs a ticking task on the driver's event loop."""

    async def connect(self):
        await super().connect()
        self.ticks = 0
        self._ticker = asyncio.ensure_future(self._tick())

    async def _tick(self):
        while True:
            await asyncio.sleep(0.005)
            self.ticks += 1

    async def disconnect(self):
        self._ticker.cancel()
        await super().disconnect()


class TickFactory(F.ClientFactory):
    def __call__(self, options):
        client = TickClient(options, self.script, self.clock, poll_s=self.poll_s, **self.kw)
        self.clients.append(client)
        return client


class NonBlockingWaitTests(InformedCase):
    """R7/R8: while a relay request is outstanding, other coroutines on the loop keep running."""

    DELAY = 0.4

    def run_with_ticks(self, script):
        factory = TickFactory(script, self.clock, poll_s=0.01)
        ticks_at_response = {}

        def policy(req):
            time.sleep(self.DELAY)
            ticks_at_response[req["kind"]] = factory.clients[0].ticks
            if req["kind"] == "ask":
                return {"answers": {Q1: "a", Q2: "b"}}
            return {"message": "M"}

        with F.RelayResponder(self.relay_dir, policy):
            state = informed_driver.run(self.make_input(relay_poll_s=0.05), factory, self.clock, poll_s=0.01)
        return state, ticks_at_response, factory

    def test_o5_ticks_keep_running_while_an_ask_request_is_outstanding(self):
        state, ticks, factory = self.run_with_ticks([[Ask(QS), result()], [result()]])
        self.assertGreaterEqual(ticks["ask"], 10)
        self.assertEqual(factory.clients[0].permission_results[0].updated_input["answers"], {Q1: "a", Q2: "b"})

    def test_o6_ticks_keep_running_while_an_idle_request_is_outstanding(self):
        state, ticks, factory = self.run_with_ticks([[result()], [result()]])
        self.assertGreaterEqual(ticks["idle"], 10)
        self.assertEqual(factory.clients[0].queries, [PROMPT, "M"])


class MainTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="infmain-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.out_dir = Path(self.tmp) / "out"
        self.out_dir.mkdir()
        self.token_path, _ = F.write_token_file(self.tmp)
        self.inp = F.driver_input(self.out_dir, self.token_path, user_mode="informed", relay_dir=str(Path(self.tmp) / "r"),
                                  relay_timeout_s=5, relay_poll_s=1)

    def write(self, text):
        path = Path(self.tmp) / "input.json"
        path.write_text(text, encoding="utf-8")
        return str(path)

    def test_o5_main_exits_2_on_unreadable_input_or_missing_base_key(self):
        base_keys = set(F.driver_input(self.out_dir, self.token_path))
        cases = [("missing file", str(Path(self.tmp) / "absent.json")), ("invalid json", self.write("{not json"))]
        for key in sorted(base_keys):
            cases.append(("missing " + key, self.write(json.dumps({k: v for k, v in self.inp.items() if k != key}))))
        for name, path in cases:
            with self.subTest(name):
                self.assertEqual(informed_driver.main([path]), 2)

    def test_o5_main_exits_0_for_every_terminal_state_and_passes_the_input(self):
        path = self.write(json.dumps(self.inp))
        for status in ("completed", "stalled", "capped", "interrupted", "error"):
            with self.subTest(status):
                with mock.patch.object(informed_driver, "run", return_value={"status": status}) as fake_run:
                    self.assertEqual(informed_driver.main([path]), 0)
                self.assertEqual(fake_run.call_args[0][0], self.inp)

    def test_o5_relay_dir_constant(self):
        self.assertEqual(informed_driver.RELAY_DIR, "/selfcheck/relay")


if __name__ == "__main__":
    unittest.main()

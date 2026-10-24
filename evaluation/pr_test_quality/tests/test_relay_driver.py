import json
import unittest
from pathlib import Path
from unittest import mock

from claude_agent_sdk import PermissionResultAllow, RateLimitEvent, RateLimitInfo

from evaluation.pr_test_quality import usersim
from evaluation.pr_test_quality.agent import relay_driver
from evaluation.pr_test_quality.tests.fakes import TmpCase
from evaluation.pr_test_quality.tests.sdk_fake import Ask, Factory, Responder, Tool, init, result, text

STOP = {"action": "stop", "message": None, "contradiction": False}
Q = {"question": "Which style?", "header": "Style", "multiSelect": False,
     "options": [{"label": "Alpha", "description": "a"}, {"label": "Beta (Recommended)", "description": "b"}]}


def reply(message):
    return {"action": "reply", "message": message, "contradiction": False}


class Driver(TmpCase):
    def setUp(self):
        super().setUp()
        self.out = self.tmp / "out"
        self.relay = self.tmp / "relay"
        self.out.mkdir()
        self.relay.mkdir()
        (self.tmp / "tok").write_text("T", encoding="utf-8")

    def go(self, script, policy=None, **over):
        inp = {"run_id": "r", "arm": "B0", "prompt": "do it", "model": "claude-sonnet-5-5", "effort": "medium",
               "aliases": {"opus": "claude-opus-5-5", "sonnet": "claude-sonnet-5-5", "haiku": "claude-haiku-5-5"},
               "disallowed_tools": ["WebSearch"], "wall_clock_s": 60, "max_user_turns": 3, "idle_grace_s": 5,
               "out_dir": str(self.out), "token_path": str(self.tmp / "tok"), "proxy_url": "http://p:3128",
               "resume": None, "relay_dir": str(self.relay), "relay_timeout_s": 5, "relay_poll_s": 0.01}
        inp.update(over)
        path = self.tmp / "in.json"
        path.write_text(json.dumps(inp), encoding="utf-8")
        factory = Factory(script)
        with mock.patch.object(relay_driver, "ClaudeSDKClient", factory), \
                Responder(self.relay, policy or (lambda req: STOP)) as responder:
            code = relay_driver.main([str(path)])
        self.state = json.loads((self.out / "state.json").read_text(encoding="utf-8")) if (self.out / "state.json").exists() else None
        return code, factory, responder


class IdleStates(Driver):
    def test_O10_idle_after_tool_call_asks_relay_and_stop_completes(self):
        code, factory, responder = self.go([[init(), Tool(), text("done"), result()]])
        self.assertEqual(code, 0)
        self.assertEqual(self.state["status"], "completed")
        self.assertEqual(responder.seen, [{"n": 1, "kind": "idle", "last_text": "done"}])
        self.assertEqual(factory.clients[0].queries, ["do it"])

    def test_O10_C19_idle_without_tool_call_completes_with_no_relay_call(self):
        code, factory, responder = self.go([[init(), text("Nothing to do."), result()]])
        self.assertEqual(code, 0)
        self.assertEqual(self.state["status"], "completed")
        self.assertEqual(responder.seen, [])

    def test_O10_reply_is_sent_to_the_agent_as_next_user_message(self):
        policy = lambda req: reply("Please add a docstring.") if req["n"] == 1 else STOP
        code, factory, responder = self.go(
            [[init(), Tool(), text("first"), result()], [Tool(), text("second"), result()]], policy)
        self.assertEqual(factory.clients[0].queries, ["do it", "Please add a docstring."])
        self.assertEqual([r["kind"] for r in responder.seen], ["idle", "idle"])
        self.assertEqual(self.state["status"], "completed")

    def test_O10_C20_turn_cap_ends_stalled(self):
        script = [[init(), Tool(), text("a"), result()]] + [[Tool(), text("again"), result()]] * 6
        code, factory, responder = self.go(script, lambda req: reply("keep going"), max_user_turns=3)
        self.assertEqual(self.state["status"], "stalled")
        self.assertEqual(len(factory.clients[0].queries), 4)

    def test_O10_C20_turn_cap_boundary_one_more_turn_allows_one_more_message(self):
        script = [[init(), Tool(), text("a"), result()]] + [[Tool(), text("again"), result()]] * 6
        self.go(script, lambda req: reply("keep going"), max_user_turns=5)
        self.assertEqual(self.state["status"], "stalled")

    def test_O10_last_text_is_cut_to_8000_chars(self):
        _, _, responder = self.go([[init(), Tool(), text("x" * 9000), result()]])
        self.assertLessEqual(len(responder.seen[0]["last_text"]), 8000)
        self.assertGreater(len(responder.seen[0]["last_text"]), 100)

    def test_O10_unanswered_idle_request_falls_back_to_fallback_idle_text(self):
        script = [[init(), Tool(), text("a"), result()], [Tool(), text("b"), result()]]
        code, factory, _ = self.go(script, lambda req: STOP if req["n"] > 1 else None, relay_timeout_s=0.3)
        self.assertIn(usersim.FALLBACK_IDLE, factory.clients[0].queries[1:])


class AskFlow(Driver):
    def test_O10_ask_question_is_relayed_and_answer_returned_to_the_agent(self):
        policy = lambda req: {"answers": {Q["question"]: "Alpha"}} if req["kind"] == "ask" else STOP
        code, factory, responder = self.go([[init(), Ask([Q]), text("ok"), result()]], policy)
        asks = [r for r in responder.seen if r["kind"] == "ask"]
        self.assertEqual(len(asks), 1)
        self.assertEqual(asks[0]["questions"][0]["question"], Q["question"])
        (allowed,) = factory.clients[0].permission_results
        self.assertIsInstance(allowed, PermissionResultAllow)
        self.assertIn("Alpha", json.dumps(allowed.updated_input))

    def test_O10_unanswered_ask_falls_back_to_recommended_option(self):
        code, factory, _ = self.go([[init(), Ask([Q]), text("ok"), result()]], lambda req: None if req["kind"] == "ask" else STOP,
                                   relay_timeout_s=0.3)
        (allowed,) = factory.clients[0].permission_results
        self.assertIn("Beta (Recommended)", json.dumps(allowed.updated_input))


class Boundaries(Driver):
    def test_O12_rate_limit_event_records_state_and_interrupts(self):
        event = RateLimitEvent(rate_limit_info=RateLimitInfo(status="rejected", resets_at=1791843000,
                                                             rate_limit_type="five_hour"), uuid="u", session_id="sess-1")
        code, factory, _ = self.go([[init(), Tool(), event, text("x"), result()]])
        self.assertEqual((self.state["rate_limit"] or {}).get("status"), "rejected")
        self.assertEqual(self.state["status"], "interrupted")

    def test_O12_missing_required_key_returns_two(self):
        path = self.tmp / "bad.json"
        path.write_text(json.dumps({"run_id": "r"}), encoding="utf-8")
        self.assertEqual(relay_driver.main([str(path)]), 2)

    def test_O12_unreadable_input_returns_two(self):
        self.assertEqual(relay_driver.main([str(self.tmp / "nope.json")]), 2)

    def test_O12_state_json_has_the_f3_fields(self):
        self.go([[init(), Tool(), text("done"), result()]])
        for key in ("status", "reason", "session_id", "results", "rate_limit"):
            self.assertIn(key, self.state)
        self.assertEqual(self.state["results"][0]["total_cost_usd"], 0.01)


if __name__ == "__main__":
    unittest.main()

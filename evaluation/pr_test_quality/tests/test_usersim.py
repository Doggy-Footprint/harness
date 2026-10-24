import json
import subprocess
import unittest

from evaluation.pr_test_quality import usersim
from evaluation.pr_test_quality.tests.fakes import (
    MERGE_SHA, TOKEN, FakeCall, RelayFs, TmpCase, make_task, spec_cfg,
)

STATEMENTS = [
    {"id": "S1", "text": "Values above the upper bound come back as the upper bound.", "f2p": ["tests/test_ops.py::test_clamp_upper_bound_zq"]},
    {"id": "S2", "text": "Parametrized cases behave the same for odd inputs.", "f2p": ["tests/test_ops.py::test_param_case_zq[3-x]"]},
]
Q = "Which style?"
ASK = {"n": 1, "kind": "ask", "questions": [{
    "question": Q, "header": "Style", "multiSelect": False,
    "options": [{"label": "Alpha", "description": "first"}, {"label": "Beta (Recommended)", "description": "second"},
                {"label": "Gamma", "description": "third"}]}]}
ASK_NO_REC = {"n": 1, "kind": "ask", "questions": [{
    "question": Q, "header": "Style", "multiSelect": False,
    "options": [{"label": "Alpha", "description": "first"}, {"label": "Beta", "description": "second"},
                {"label": "Gamma", "description": "third"}]}]}
IDLE = {"n": 2, "kind": "idle", "last_text": "I finished the clamp helper and the tests."}


def task():
    return make_task("python", brief={"request": "Please add clamp. Implement this and add automated tests.",
                                      "statements": STATEMENTS, "ambiguous": [], "status": "ok",
                                      "attempts": 1, "reason": ""})


def answers(label):
    return json.dumps({"answers": {Q: label}})


def idle_json(action="reply", message="Please add a docstring.", contradiction=False):
    return json.dumps({"action": action, "message": message, "contradiction": contradiction})


class Prompt(unittest.TestCase):
    def setUp(self):
        self.task = task()

    def test_O11_ask_prompt_contains_request_statements_and_rules(self):
        prompt = usersim.build_prompt(self.task, ASK, [])
        self.assertIn(Q, prompt)
        for label in ("Alpha", "Beta (Recommended)", "Gamma"):
            self.assertIn(label, prompt)
        for statement in STATEMENTS:
            self.assertIn(statement["text"], prompt)
        self.assertIn(usersim.FALLBACK_IDLE, prompt)
        self.assertIn("Recommended", prompt)

    def test_O11_idle_prompt_contains_last_text(self):
        prompt = usersim.build_prompt(self.task, IDLE, [])
        self.assertIn(IDLE["last_text"], prompt)
        for statement in STATEMENTS:
            self.assertIn(statement["text"], prompt)

    def test_O11_prompt_excludes_f2p_ids_gold_diff_and_merge_sha(self):
        for request in (ASK, IDLE):
            prompt = usersim.build_prompt(self.task, request, [])
            for secret in ("tests/test_ops.py", "test_clamp_upper_bound_zq", "test_param_case_zq",
                           "five-marker-zq", "build_gold_fixture_zq", MERGE_SHA, "diff --git"):
                with self.subTest(kind=request["kind"], secret=secret):
                    self.assertNotIn(secret, prompt)

    def test_O11_idle_last_text_is_cut_to_8000_chars(self):
        request = {"n": 3, "kind": "idle", "last_text": "A" * 9000}
        prompt = usersim.build_prompt(self.task, request, [])
        self.assertIn("A" * 100, prompt)
        self.assertNotIn("A" * 8001, prompt)

    def test_O11_short_last_text_is_kept_whole(self):
        request = {"n": 3, "kind": "idle", "last_text": "B" * 8000}
        self.assertIn("B" * 8000, usersim.build_prompt(self.task, request, []))

    def test_O11_prompt_includes_previous_exchanges_of_this_entry(self):
        call = FakeCall([idle_json(message="PREVIOUS-REPLY-MARKER please continue")])
        _, row = usersim.respond(self.task, IDLE, [], call_fn=call, cfg=spec_cfg())
        later = {"n": 4, "kind": "idle", "last_text": "second look"}
        self.assertIn("PREVIOUS-REPLY-MARKER", usersim.build_prompt(self.task, later, [row]))
        self.assertNotIn("PREVIOUS-REPLY-MARKER", usersim.build_prompt(self.task, later, []))


class ParseResponse(unittest.TestCase):
    def test_O10_ask_answers_parsed(self):
        out = usersim.parse_response(answers("Beta (Recommended)"), ASK)
        self.assertEqual(out["answers"], {Q: "Beta (Recommended)"})

    def test_O10_ask_null_answer_is_kept_as_none(self):
        out = usersim.parse_response(answers(None), ASK)
        self.assertEqual(out["answers"], {Q: None})

    def test_O10_idle_reply_stop_and_contradiction_flag(self):
        reply = usersim.parse_response(idle_json("reply", "Add tests.", False), IDLE)
        self.assertEqual((reply["action"], reply["message"], reply["contradiction"]), ("reply", "Add tests.", False))
        stop = usersim.parse_response(idle_json("stop", None, False), IDLE)
        self.assertEqual((stop["action"], stop["message"]), ("stop", None))
        contra = usersim.parse_response(idle_json("reply", "The bound must stay inclusive.", True), IDLE)
        self.assertIs(contra["contradiction"], True)


class Respond(TmpCase):
    def setUp(self):
        super().setUp()
        self.task = task()
        self.cfg_ = self.cfg()

    def go(self, request, reply):
        call = FakeCall([reply])
        response, row = usersim.respond(self.task, request, [], call_fn=call, cfg=self.cfg_)
        return response, row, call

    def test_O10_C17_ask_answered_picks_the_models_option(self):
        response, row, call = self.go(ASK, answers("Gamma"))
        self.assertEqual(response["answers"], {Q: "Gamma"})
        self.assertFalse(row.get("reason"))
        self.assertEqual(len(call.calls), 1)
        self.assertEqual(call.calls[0]["model"], "claude-opus-5-5")
        self.assertEqual(call.calls[0]["effort"], "medium")
        self.assertEqual(call.calls[0]["timeout_s"], 900)

    def test_O10_C17_second_option_label_sent(self):
        response, _, _ = self.go(ASK_NO_REC, answers("Beta"))
        self.assertEqual(response["answers"], {Q: "Beta"})

    def test_O10_C18_ask_leak_falls_back_to_recommended_option(self):
        response, row, _ = self.go(ASK, answers("Alpha, see tests/test_ops.py"))
        self.assertEqual(response["answers"], {Q: "Beta (Recommended)"})
        self.assertEqual(row["reason"], "leak")

    def test_O10_ask_leak_without_recommended_falls_back_to_first_option(self):
        response, row, _ = self.go(ASK_NO_REC, answers("Gamma five-marker-zq"))
        self.assertEqual(response["answers"], {Q: "Alpha"})
        self.assertEqual(row["reason"], "leak")

    def test_O10_ask_null_answer_falls_back(self):
        response, row, _ = self.go(ASK, answers(None))
        self.assertEqual(response["answers"], {Q: "Beta (Recommended)"})
        self.assertTrue(row["reason"])

    def test_O10_ask_unparseable_falls_back(self):
        response, row, _ = self.go(ASK_NO_REC, "I would pick Gamma, honestly.")
        self.assertEqual(response["answers"], {Q: "Alpha"})
        self.assertTrue(row["reason"])

    def test_O10_ask_timeout_falls_back_with_reason(self):
        for exc in (TimeoutError("slow"), subprocess.TimeoutExpired(["claude"], 900)):
            with self.subTest(exc=type(exc).__name__):
                response, row, _ = self.go(ASK, exc)
                self.assertEqual(response["answers"], {Q: "Beta (Recommended)"})
                self.assertIn("time", str(row["reason"]).lower())

    def test_O10_ask_every_question_gets_an_answer_on_fallback(self):
        request = {"n": 1, "kind": "ask", "questions": [
            ASK["questions"][0],
            {"question": "Which color?", "header": "Color", "multiSelect": False,
             "options": [{"label": "Red", "description": ""}, {"label": "Blue", "description": ""}]}]}
        response, _, _ = self.go(request, "garbage")
        self.assertEqual(response["answers"], {Q: "Beta (Recommended)", "Which color?": "Red"})

    def test_O10_idle_reply_passes_message_through(self):
        response, row, _ = self.go(IDLE, idle_json("reply", "Please add a docstring."))
        self.assertEqual((response["action"], response["message"], response["contradiction"]),
                         ("reply", "Please add a docstring.", False))
        self.assertFalse(row.get("reason"))

    def test_O10_idle_stop(self):
        response, _, _ = self.go(IDLE, idle_json("stop", None))
        self.assertEqual(response["action"], "stop")

    def test_O10_idle_contradiction_flag_survives(self):
        response, _, _ = self.go(IDLE, idle_json("reply", "No, the bound is inclusive.", True))
        self.assertIs(response["contradiction"], True)

    def test_O10_idle_leak_unparseable_null_timeout_use_fallback_idle(self):
        cases = {
            "leak": idle_json("reply", "Check build_gold_fixture_zq please."),
            "unparseable": "sure thing",
            "null": idle_json("reply", None),
            "timeout": TimeoutError("slow"),
        }
        for name, reply in cases.items():
            with self.subTest(case=name):
                response, row, _ = self.go(IDLE, reply)
                self.assertEqual((response["action"], response["message"], response["contradiction"]),
                                 ("reply", usersim.FALLBACK_IDLE, False))
                self.assertTrue(row["reason"])
        self.assertEqual(self.go(IDLE, cases["leak"])[1]["reason"], "leak")

    def test_O10_F5_merge_sha_in_model_output_triggers_the_leak_fallback(self):
        for text in (MERGE_SHA, MERGE_SHA[:7]):
            response, row, _ = self.go(IDLE, idle_json("reply", "Match %s please." % text))
            self.assertEqual(response["message"], usersim.FALLBACK_IDLE)
            self.assertEqual(row["reason"], "leak")

    def test_O10_F5_forbidden_terms_are_the_brief_forbidden_terms(self):
        from evaluation.pr_test_quality import brief
        self.assertEqual(usersim.forbidden_terms(self.task), brief.forbidden_terms(self.task))

    def test_O10_fallback_constants(self):
        self.assertEqual(usersim.FALLBACK_ASK, "(Recommended)")
        self.assertEqual(usersim.FALLBACK_IDLE, "No preference; use your recommendation. Please continue.")

    def test_O10_timeout_comes_from_cfg(self):
        self.cfg_ = self.cfg(usersim={"timeout_s": 123})
        _, _, call = self.go(IDLE, idle_json())
        self.assertEqual(call.calls[0]["timeout_s"], 123)


class RelayCase(TmpCase):
    def setUp(self):
        super().setUp()
        self.task = task()
        self.cfg_ = self.cfg(agent={"relay_poll_s": 0.01}, usersim={"poll_s": 0.01})
        self.fs = RelayFs()
        self.record = self.tmp / "run" / "usersim.jsonl"

    def start(self, script):
        self.call = FakeCall(script)
        self.relay = usersim.Relay(self.fs, self.task, self.record, call_fn=self.call, cfg=self.cfg_, token=TOKEN)
        self.relay.start()
        self.addCleanup(self.relay.stop)
        self.directory = self.fs.wait_for(lambda: self.fs.polled[0] if self.fs.polled else None)
        self.assertTrue(self.directory, "relay never polled the container")

    def ask(self, n, request):
        self.fs.put_request(self.directory, n, dict(request, n=n))
        return self.fs.wait_for(lambda: self.fs.responses(self.directory).get("resp-%d.json" % n))

    def rows(self):
        def read():
            if self.record.is_file():
                lines = [ln for ln in self.record.read_text(encoding="utf-8").splitlines() if ln.strip()]
                return [json.loads(ln) for ln in lines]
            return None
        return self.fs.wait_for(read) or []


class RelayProtocol(RelayCase):
    def test_O10_ask_request_gets_response_file_with_n_and_answers(self):
        self.start([answers("Gamma")])
        raw = self.ask(1, ASK)
        self.assertIsNotNone(raw)
        body = json.loads(raw)
        self.assertEqual(body["n"], 1)
        self.assertEqual(body["answers"], {Q: "Gamma"})
        self.assertEqual(len(self.rows()), 1)

    def test_O10_idle_request_gets_idle_response(self):
        self.start([idle_json("reply", "Add a docstring.")])
        body = json.loads(self.ask(2, IDLE))
        self.assertEqual((body["n"], body["action"], body["message"]), (2, "reply", "Add a docstring."))

    def test_O10_each_request_is_answered_once_in_order(self):
        self.start([answers("Alpha"), idle_json("stop", None)])
        self.assertEqual(json.loads(self.ask(1, ASK))["answers"], {Q: "Alpha"})
        self.assertEqual(json.loads(self.ask(2, IDLE))["action"], "stop")
        self.fs.wait_for(lambda: len(self.rows()) >= 2)
        self.assertEqual(len(self.call.calls), 2)

    def test_O10_leak_in_model_output_is_replaced_in_the_response_and_recorded(self):
        self.start([answers("Alpha see tests/test_ops.py")])
        body = json.loads(self.ask(1, ASK))
        self.assertEqual(body["answers"], {Q: "Beta (Recommended)"})
        self.assertNotIn("tests/test_ops.py", json.dumps(body))
        self.assertEqual(self.rows()[0]["reason"], "leak")

    def test_O10_F5_token_in_ask_answer_gets_leak_fallback_and_redacted_record(self):
        self.start([answers("Alpha %s" % TOKEN)])
        body = json.loads(self.ask(1, ASK))
        self.assertEqual(body["answers"], {Q: "Beta (Recommended)"})
        rows = self.rows()
        self.assertEqual(rows[0]["reason"], "leak")
        self.assertNotIn(TOKEN, self.record.read_text(encoding="utf-8"))

    def test_O10_stop_ends_polling(self):
        self.start([idle_json()])
        self.relay.stop()
        before = len(self.call.calls)
        self.fs.put_request(self.directory, 9, dict(IDLE, n=9))
        self.fs.wait_for(lambda: False, timeout=0.3)
        self.assertEqual(len(self.call.calls), before)
        self.assertEqual(self.fs.responses(self.directory), {})

    def test_O10_token_never_reaches_record_or_response(self):
        self.start([idle_json("reply", "use key %s now" % TOKEN)])
        raw = self.ask(2, IDLE)
        self.assertIsNotNone(raw)
        self.assertNotIn(TOKEN, raw)
        self.fs.wait_for(lambda: self.record.is_file())
        recorded = self.record.read_text(encoding="utf-8")
        self.assertNotIn(TOKEN, recorded)
        self.assertIn("[REDACTED]", recorded)
        self.assertEqual(json.loads(raw)["message"], usersim.FALLBACK_IDLE)


class RelayLeakGuard(RelayCase):
    def test_O27_model_output_naming_gold_material_never_reaches_the_container(self):
        for label, reply in (
            ("gold test text", idle_json("reply", 'Make sure describe(5) == "five-marker-zq".')),
            ("f2p name", idle_json("reply", "Cover test_clamp_upper_bound_zq too.")),
            ("test path", idle_json("reply", "Mirror tests/test_ops.py.")),
            ("merge sha", idle_json("reply", "Match commit %s exactly." % MERGE_SHA)),
        ):
            with self.subTest(label=label):
                self.fs = RelayFs()
                self.record = self.tmp / label.replace(" ", "_") / "usersim.jsonl"
                self.start([reply])
                raw = self.ask(2, IDLE)
                self.assertIsNotNone(raw)
                for secret in ("five-marker-zq", "test_clamp_upper_bound_zq", "tests/test_ops.py", MERGE_SHA):
                    self.assertNotIn(secret, raw)
                self.relay.stop()


if __name__ == "__main__":
    unittest.main()

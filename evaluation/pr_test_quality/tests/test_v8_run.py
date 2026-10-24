import io
import json
import re
import subprocess
import time
import unittest
from pathlib import Path
from unittest import mock

from claude_agent_sdk import PermissionResultAllow

from evaluation.pr_test_quality import run as run_mod
from evaluation.pr_test_quality import usersim
from evaluation.pr_test_quality.agent import relay_driver
from evaluation.pr_test_quality.tests import fakes
from evaluation.pr_test_quality.tests.fakes import MERGE_SHA, TOKEN, FakeCall, RelayFs, TmpCase, find
from evaluation.pr_test_quality.tests.sdk_fake import Ask, Factory, Responder, Tool, init, result, text
from evaluation.pr_test_quality.tests.test_relay_driver import Driver, Q, STOP, reply
from evaluation.pr_test_quality.tests.test_run import Lab, mk_task
from evaluation.pr_test_quality.tests.test_usersim import ASK, IDLE, RelayCase, answers, idle_json, task as sim_task

REQUIRED = ("run_id", "arm", "prompt", "model", "effort", "aliases", "disallowed_tools", "wall_clock_s",
            "max_user_turns", "idle_grace_s", "out_dir", "token_path", "proxy_url", "resume", "relay_dir",
            "relay_timeout_s", "relay_poll_s")
ROW_KEYS = {"n", "kind", "request", "raw_output", "parsed", "leaks", "sent", "fallbacks", "reason", "error",
            "contradiction", "elapsed_s"}


class DriverContract(Lab):
    def test_O12_G23_F28_driver_input_has_every_required_key(self):
        self.do_run([mk_task(1)])
        inp = self.docker.agent_started[0].driver_inputs[0]
        self.assertEqual(set(REQUIRED) - set(inp), set())
        self.assertEqual(inp["token_path"], "/run/secrets/oauth_token")
        self.assertEqual(inp["aliases"], {"opus": "claude-opus-5-5", "sonnet": "claude-sonnet-5-5",
                                          "haiku": "claude-haiku-5-5"})

    def test_O12_G24_proxy_url_is_http_proxy_name_port_3128(self):
        self.do_run([mk_task(1)])
        inp = self.docker.agent_started[0].driver_inputs[0]
        name = self.docker.proxies[0]["name"]
        self.assertEqual(inp["proxy_url"], "http://%s:3128" % name)

    def test_O12_G25_out_dir_and_state_paths_are_exactly_evaluation_out(self):
        self.do_run([mk_task(1)])
        cont = self.docker.agent_started[0]
        self.assertEqual(cont.driver_inputs[0]["out_dir"], "/evaluation/out")
        self.assertIn("/evaluation/out/state.json", cont.reads)
        self.assertIn("/evaluation/out/.", cont.copyouts)
        self.assertEqual(cont.driver_inputs[0]["relay_dir"], "/evaluation/relay")

    def test_O12_G27_driver_exit_zero_without_state_is_an_error_entry_and_the_run_continues(self):
        self.script = {(1, "B0"): "nostate"}
        tasks = [mk_task(1), mk_task(2)]
        run_dir = self.do_run(tasks)
        got = self.statuses(run_dir)
        self.assertEqual(got[(tasks[0]["task_id"], "B0", 1)], "error")
        self.assertEqual(got[(tasks[1]["task_id"], "B0", 1)], "completed")
        state = json.loads((self.entry_dir(run_dir, tasks[0]) / "state.json").read_text())
        self.assertEqual(state["status"], "error")
        self.assertTrue(state["reason"])

    def test_O12_G34_run_ids_are_sixteen_lowercase_hex_characters(self):
        for _ in range(3):
            run_dir = self.do_run([mk_task(1)])
            self.assertRegex(Path(run_dir).name, r"^[0-9a-f]{16}$")
            self.assertEqual(self.run_json(run_dir)["run_id"], Path(run_dir).name)
            self.setUp()

    def test_O12_G28_F28_interrupted_state_elapsed_and_phrases_reach_the_resume_input(self):
        base = self.driver

        def drv(cont, inp):
            out = base(cont, inp)
            if len(self.driver_calls) == 1:
                state = json.loads(out["files"]["state.json"])
                state.update({"status": "interrupted", "elapsed_s": 100.0, "phrases_sent": 2})
                out["files"]["state.json"] = json.dumps(state).encode()
            return out
        self.docker.driver_policy = drv
        task = mk_task(1)
        with self.assertRaises(run_mod.Halted) as ctx:
            self.do_run([task])
        run_mod.resume(Path(ctx.exception.run_dir).name, cfg=self.mkcfg(), docker=self.docker, call_fn=FakeCall(["{}"]))
        first, second = [i for c in self.docker.agent_started for i in c.driver_inputs]
        self.assertIsNone(first["resume"])
        self.assertEqual(second["resume"], {"session_id": "sess-1-B0", "phrases_sent": 2, "elapsed_s": 100.0})
        self.assertEqual(second["wall_clock_s"], 180 * 60)
        self.assertEqual(second["max_user_turns"], 8)


class HInstallEnv(Lab):
    def execs(self, arm="H"):
        self.do_run([mk_task(1)], arms=(arm,))
        return self.docker.agent_started[0].execs

    def test_O29_G36_install_runs_with_the_targets_and_preferences_files_and_the_never_preference(self):
        execs = self.execs()
        texts = [" ".join(e["argv"]) for e in execs]
        install = [i for i, t in enumerate(texts) if "installer/harness.py" in t][0]
        self.assertIn("HARNESS_TARGETS_FILE=/tmp/harness-targets.json", texts[install])
        self.assertIn("HARNESS_PREFERENCES_FILE=/tmp/harness-preferences.json", texts[install])
        write = [i for i, t in enumerate(texts) if "/tmp/harness-preferences.json" in t and "installer" not in t]
        self.assertTrue(write)
        self.assertLess(write[0], install)
        payload = re.search(r"printf %s '(\{.*\})' >", texts[write[0]])
        self.assertTrue(payload, texts[write[0]])
        self.assertEqual(json.loads(payload.group(1)),
                         {"repositories": {"/testbed": {"verification_tools_prompt": "never"}}})

    def test_O29_G36_nonzero_install_exit_ends_the_entry_in_error_with_the_exit_code(self):
        def policy(cont, argv):
            if "installer/harness.py" in " ".join(argv):
                return 3, "install exploded", False
            return None
        self.docker.exec_policy = policy
        tasks = [mk_task(1), mk_task(2)]
        run_dir = self.do_run(tasks, arms=("H", "B0"))
        got = self.statuses(run_dir)
        self.assertEqual(got[(tasks[0]["task_id"], "H", 1)], "error")
        state = json.loads((self.entry_dir(run_dir, tasks[0], "H") / "state.json").read_text())
        self.assertEqual(state["reason"], "install failed: exit 3")
        self.assertEqual(self.driver_calls.count((1, "H")), 0)
        self.assertEqual(got[(tasks[0]["task_id"], "B0", 1)], "completed")
        self.assertNotIn("commit", " ".join(" ".join(e["argv"]) for e in self.docker.agent_started[0].execs))

    def test_O29_G36_exit_zero_proceeds_to_commit_then_driver(self):
        texts = [" ".join(e["argv"]) for e in self.execs()]
        self.assertTrue([t for t in texts if "commit" in t])
        self.assertTrue([t for t in texts if "relay_driver.py" in t])


class RelayDriverFacts(Driver):
    def test_O12_G23_valid_input_runs_and_writes_state_json(self):
        code, factory, responder = self.go([[init(), Tool(), text("done"), result()]])
        self.assertEqual(code, 0)
        self.assertEqual(self.state["status"], "completed")

    def test_O12_G23_each_required_key_missing_returns_two(self):
        for key in REQUIRED:
            path = self.tmp / ("in-%s.json" % key)
            data = {"run_id": "r", "arm": "B0", "prompt": "p", "model": "m", "effort": "medium", "aliases": {},
                    "disallowed_tools": [], "wall_clock_s": 60, "max_user_turns": 3, "idle_grace_s": 5,
                    "out_dir": str(self.out), "token_path": str(self.tmp / "tok"), "proxy_url": "http://p:3128",
                    "resume": None, "relay_dir": str(self.relay), "relay_timeout_s": 5, "relay_poll_s": 0.01}
            del data[key]
            path.write_text(json.dumps(data))
            with self.subTest(missing=key):
                self.assertEqual(relay_driver.main([str(path)]), 2)

    def test_O12_G26_driver_exception_writes_state_status_error(self):
        inp_path = self.tmp / "in.json"
        base = {"run_id": "r", "arm": "B0", "prompt": "p", "model": "claude-sonnet-5-5", "effort": "medium",
                "aliases": {}, "disallowed_tools": [], "wall_clock_s": 60, "max_user_turns": 3, "idle_grace_s": 5,
                "out_dir": str(self.out), "token_path": str(self.tmp / "tok"), "proxy_url": "http://p:3128",
                "resume": None, "relay_dir": str(self.relay), "relay_timeout_s": 5, "relay_poll_s": 0.01}
        inp_path.write_text(json.dumps(base))
        factory = Factory([[init()]], query_error=RuntimeError("boom"))
        with mock.patch.object(relay_driver, "ClaudeSDKClient", factory), Responder(self.relay, lambda r: STOP):
            relay_driver.main([str(inp_path)])
        state = json.loads((self.out / "state.json").read_text())
        self.assertEqual(state["status"], "error")
        self.assertIn("boom", state["reason"])

    def test_O12_G24_G35_client_env_carries_the_proxy_and_the_oauth_token(self):
        code, factory, _ = self.go([[init(), Tool(), text("done"), result()]], proxy_url="http://evaluation-proxy:3128")
        env = factory.clients[0].options.env
        self.assertEqual(env["CLAUDE_CODE_OAUTH_TOKEN"], "T")
        self.assertEqual(env["HTTPS_PROXY"], "http://evaluation-proxy:3128")
        self.assertEqual(env["HTTP_PROXY"], "http://evaluation-proxy:3128")

    def test_O10_G29_F28_ask_answers_reach_the_sdk_as_questions_plus_answers(self):
        policy = lambda req: {"answers": {Q["question"]: "Alpha"}} if req["kind"] == "ask" else STOP
        code, factory, _ = self.go([[init(), Ask([Q]), text("ok"), result()]], policy)
        (allowed,) = factory.clients[0].permission_results
        self.assertIsInstance(allowed, PermissionResultAllow)
        self.assertEqual(allowed.updated_input, {"questions": [Q], "answers": {Q["question"]: "Alpha"}})

    def test_O12_G28_F28_resume_continues_phrases_and_elapsed(self):
        script = [[init(), Tool(), text("a"), result()], [Tool(), text("b"), result()], [Tool(), text("c"), result()]]
        resume = {"session_id": "sess-1", "phrases_sent": 2, "elapsed_s": 100.0}
        code, factory, responder = self.go(script, lambda req: reply("go on"), max_user_turns=3, resume=resume,
                                              wall_clock_s=600)
        self.assertEqual(self.state["status"], "stalled")
        self.assertEqual(self.state["phrases_sent"], 3)
        self.assertEqual(len(factory.clients[0].queries), 2)
        self.assertGreaterEqual(self.state["elapsed_s"], 100.0)
        self.assertLess(self.state["elapsed_s"], 110.0)

    def test_O12_G28_F28_without_resume_the_full_turn_cap_applies(self):
        script = [[init(), Tool(), text("a"), result()]] + [[Tool(), text("b"), result()]] * 6
        code, factory, _ = self.go(script, lambda req: reply("go on"), max_user_turns=3)
        self.assertEqual(self.state["phrases_sent"], 3)
        self.assertEqual(len(factory.clients[0].queries), 4)
        self.assertLess(self.state["elapsed_s"], 100.0)

    def test_O12_F28_wall_clock_remaining_is_total_minus_elapsed(self):
        resume = {"session_id": "sess-1", "phrases_sent": 0, "elapsed_s": 100.0}
        script = [[init(), Tool(), text("a"), result()]]
        code, factory, _ = self.go(script, lambda req: STOP, wall_clock_s=100, resume=resume)
        self.assertEqual(self.state["status"], "capped")
        self.setUp()
        code, factory, _ = self.go(script, lambda req: STOP, wall_clock_s=100, resume=None)
        self.assertEqual(self.state["status"], "completed")


class RowFormat(unittest.TestCase):
    def setUp(self):
        self.task = sim_task()
        from evaluation.pr_test_quality.tests.fakes import spec_cfg
        self.cfg = spec_cfg()

    def go(self, request, reply_text):
        return usersim.respond(self.task, request, [], call_fn=FakeCall([reply_text]), cfg=self.cfg)

    def test_O10_G33_F20_rows_have_exactly_the_f20_keys_for_ask_and_idle(self):
        for request, text_ in ((ASK, answers("Alpha")), (IDLE, idle_json())):
            _, row = self.go(request, text_)
            with self.subTest(kind=request["kind"]):
                self.assertEqual(set(row), ROW_KEYS)
                self.assertEqual(row["kind"], request["kind"])
                self.assertEqual(row["n"], request["n"])
                self.assertEqual(row["request"], request)
                self.assertEqual(row["raw_output"], text_)
                self.assertIsInstance(row["elapsed_s"], float)
                self.assertEqual(row["fallbacks"], {})
                self.assertEqual(row["leaks"], {})
                self.assertIsNone(row["error"])

    def test_O10_G33_F20_successful_row_sent_equals_the_response(self):
        response, row = self.go(IDLE, idle_json("reply", "Add a docstring."))
        self.assertEqual(row["sent"], response)
        self.assertEqual(row["parsed"], {"action": "reply", "message": "Add a docstring.", "contradiction": False})

    def test_O10_G33_F20_failure_rows_carry_outcome_names_and_error_text(self):
        cases = (("garbage", "format"), (TimeoutError("slow"), "timeout"), (RuntimeError("boom"), "error"),
                 (idle_json("reply", None), "null"))
        for reply_obj, outcome in cases:
            _, row = usersim.respond(self.task, IDLE, [], call_fn=FakeCall([reply_obj]), cfg=self.cfg)
            with self.subTest(outcome=outcome):
                self.assertEqual(row["reason"], outcome)
                self.assertEqual(list(row["fallbacks"].values()), [outcome])
                self.assertEqual(row["sent"]["message"], usersim.FALLBACK_IDLE)
                if outcome in ("timeout", "error"):
                    self.assertTrue(row["error"])

    def test_O10_G30_multiselect_without_recommended_gets_the_first_option(self):
        request = {"n": 1, "kind": "ask", "questions": [{"question": "Pick many", "header": "h", "multiSelect": True,
                                                           "options": [{"label": "A", "description": ""},
                                                                       {"label": "B", "description": ""}]}]}
        response, row = self.go(request, "garbage")
        self.assertEqual(response["answers"], {"Pick many": "A"})

    def test_O10_G30_several_recommended_options_pick_the_first_recommended(self):
        request = {"n": 1, "kind": "ask", "questions": [{"question": "One", "header": "h", "multiSelect": False,
                                                           "options": [{"label": "X", "description": ""},
                                                                       {"label": "Y (Recommended)", "description": ""},
                                                                       {"label": "Z (Recommended)", "description": ""}]}]}
        response, _ = self.go(request, "garbage")
        self.assertEqual(response["answers"], {"One": "Y (Recommended)"})

    def test_O10_G30_multiselect_with_a_recommended_option_still_picks_it(self):
        request = {"n": 1, "kind": "ask", "questions": [{"question": "Many", "header": "h", "multiSelect": True,
                                                           "options": [{"label": "A", "description": ""},
                                                                       {"label": "B (Recommended)", "description": ""}]}]}
        response, _ = self.go(request, "garbage")
        self.assertEqual(response["answers"], {"Many": "B (Recommended)"})

    def test_O10_G31_a_contradicting_reply_replaced_by_a_fallback_is_not_a_contradiction(self):
        leaky = idle_json("reply", "Mirror tests/test_ops.py.", True)
        response, row = self.go(IDLE, leaky)
        self.assertIs(response["contradiction"], False)
        self.assertIs(row["contradiction"], False)
        self.assertIs(row["parsed"]["contradiction"], True)

    def test_O10_G31_a_kept_contradiction_is_recorded_true(self):
        response, row = self.go(IDLE, idle_json("reply", "The bound is inclusive.", True))
        self.assertIs(response["contradiction"], True)
        self.assertIs(row["contradiction"], True)


class RelayDedup(RelayCase):
    def test_O10_G32_one_response_and_one_row_per_request_across_many_polls(self):
        self.start([answers("Gamma"), answers("Alpha")])
        self.assertIsNotNone(self.ask(1, ASK))
        self.fs.wait_for(lambda: False, timeout=0.4)
        self.assertEqual(len(self.call.calls), 1)
        self.assertEqual(len(self.rows()), 1)
        self.assertEqual(len(self.fs.responses(self.directory)), 1)
        self.assertEqual(json.loads(self.fs.responses(self.directory)["resp-1.json"])["answers"], {"Which style?": "Gamma"})

    def test_O10_G32_two_requests_get_two_rows_in_order(self):
        self.start([answers("Gamma"), idle_json("stop", None)])
        self.ask(1, ASK)
        self.ask(2, IDLE)
        self.fs.wait_for(lambda: len(self.rows()) >= 2)
        rows = self.rows()
        self.assertEqual([r["n"] for r in rows], [1, 2])
        self.assertEqual([r["kind"] for r in rows], ["ask", "idle"])
        self.assertEqual(len(self.call.calls), 2)

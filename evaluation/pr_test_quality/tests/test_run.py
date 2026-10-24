import json
import os
import re
import subprocess
import unittest
from pathlib import Path

from evaluation.pr_test_quality import compose
from evaluation.pr_test_quality import run as run_mod
from evaluation.pr_test_quality.tests import fakes
from evaluation.pr_test_quality.tests.fakes import (
    MERGE_SHA, ROOT, TOKEN, FakeCall, FakeDocker, MISSING, TmpCase, deep_merge, failing_replace, find,
    interface_request, make_task, set_token_file, sha256, snapshot, spec_cfg, udiff,
)

AGENT_DIFF = udiff("tests/test_agent_x.py", None, "def test_agent_x():\n    assert 1 == 1\n")
PREREG_TEXT = "# Preregistration\nfixed before results\n"


def mk_task(pr):
    task = make_task("python", pr=pr, repo="acme/calc")
    request = interface_request(task).replace("added to the library.", "added to the library (TASKMARK_%d)." % pr)
    task["brief"] = {"request": request, "statements": [{"id": "S1", "text": "Keeps value in range.",
                                                         "f2p": list(task["f2p"])}],
                     "ambiguous": [], "status": "ok", "attempts": 1, "reason": ""}
    return task


class Lab(TmpCase):
    def setUp(self):
        super().setUp()
        self.base = spec_cfg(self.tmp / "data")
        self.token_path = set_token_file(self.base, self.tmp)
        self.prereg = self.tmp / "preregistration.md"
        self.prereg.write_text(PREREG_TEXT, encoding="utf-8")
        self.script = {}
        self.rate_limit = {}
        self.driver_calls = []
        self.texts = []
        self.docker = FakeDocker(driver_policy=self.driver, diff_text=AGENT_DIFF)

    def mkcfg(self, **over):
        return deep_merge(self.base, over) if over else self.base

    def driver(self, cont, inp):
        text = json.dumps(inp) + "\n" + cont.tree_text()
        pr = int(re.search(r"TASKMARK_(\d+)", text).group(1))
        arm = "H" if "/workflow-approach " in text else ("Bplus" if "Write thorough automated tests" in text else "B0")
        self.driver_calls.append((pr, arm))
        self.texts.append((pr, arm, text))
        count = sum(1 for c in self.driver_calls if c == (pr, arm))
        status = self.script.get((pr, arm), "completed")
        status = status(count) if callable(status) else status
        if status == "error":
            return {"exit": 1, "files": {}}
        if status == "nostate":
            return {"exit": 0, "files": {"messages.jsonl": b"{}\n"}}
        state = {"status": status, "reason": "key " + TOKEN, "session_id": "sess-%d-%s" % (pr, arm),
                 "results": [{"total_cost_usd": 0.5, "duration_ms": 12000, "num_turns": 3, "is_error": False}],
                 "rate_limit": self.rate_limit.get((pr, arm))}
        files = {
            "state.json": json.dumps(state).encode(),
            "ledger.jsonl": ('{"kind": "ledger", "auth": "%s"}\n' % TOKEN).encode(),
            "messages.jsonl": ('{"role": "assistant", "text": "keep-me-msg %s"}\n' % TOKEN).encode(),
            "telemetry/events.jsonl": ('{"event": "x", "token": "%s"}\n' % TOKEN).encode(),
            "full.diff": AGENT_DIFF.encode(),
        }
        return {"exit": 0, "files": files}

    def do_run(self, tasks, arms=("B0",), repeats=1, concurrency=1, phase="dev", **kw):
        return run_mod.run(tasks, list(arms), cfg=self.mkcfg(agent={"concurrency": concurrency}), phase=phase,
                           repeats=repeats, docker=self.docker, call_fn=FakeCall(["{}"]),
                           prereg_path=self.prereg, **kw)

    def run_json(self, run_dir):
        return json.loads((Path(run_dir) / "run.json").read_text(encoding="utf-8"))

    def statuses(self, run_dir):
        return {(e["task_id"], e["arm"], e["repeat"]): e["status"] for e in self.run_json(run_dir)["entries"]}

    def entry_dir(self, run_dir, task, arm="B0", repeat=1):
        return Path(run_dir) / task["task_id"] / ("%s-r%d" % (arm, repeat))


class EntryStates(Lab):
    def test_O12_entry_states_are_recorded_and_the_run_continues_after_an_error(self):
        tasks = [mk_task(pr) for pr in (1, 2, 3, 4)]
        self.script = {(1, "B0"): "completed", (2, "B0"): "error", (3, "B0"): "stalled", (4, "B0"): "capped"}
        run_dir = self.do_run(tasks)
        got = self.statuses(run_dir)
        self.assertEqual([got[(t["task_id"], "B0", 1)] for t in tasks], ["completed", "error", "stalled", "capped"])
        self.assertEqual(len(self.driver_calls), 4)

    def test_O12_missing_state_file_is_an_error_entry(self):
        task = mk_task(1)
        self.script = {(1, "B0"): "nostate"}
        run_dir = self.do_run([task])
        self.assertEqual(self.statuses(run_dir)[(task["task_id"], "B0", 1)], "error")

    def test_O12_run_json_header_and_entry_files(self):
        task = mk_task(1)
        run_dir = self.do_run([task], arms=("B0", "Bplus"), repeats=2, phase="main")
        data = self.run_json(run_dir)
        self.assertEqual(data["phase"], "main")
        self.assertEqual(data["prereg_sha256"], sha256(PREREG_TEXT))
        self.assertEqual(data["run_id"], Path(run_dir).name)
        self.assertEqual(Path(run_dir).parent, Path(self.base["data_dir"]) / "runs")
        self.assertEqual(len(data["entries"]), 4)
        self.assertEqual({(e["arm"], e["repeat"]) for e in data["entries"]},
                         {("B0", 1), ("B0", 2), ("Bplus", 1), ("Bplus", 2)})
        for arm, rep in (("B0", 1), ("B0", 2), ("Bplus", 1), ("Bplus", 2)):
            d = self.entry_dir(run_dir, task, arm, rep)
            for name in ("manifest.json", "state.json", "full.diff", "split.json"):
                self.assertTrue((d / name).is_file(), "%s/%s" % (d, name))
            split = json.loads((d / "split.json").read_text(encoding="utf-8"))
            self.assertIn("test_agent_x", split["split"]["tests"])
            self.assertNotIn("test_agent_x", split["split"]["src"])
            self.assertIn("test_agent_x", (d / "full.diff").read_text(encoding="utf-8"))
            self.assertEqual(json.loads((d / "state.json").read_text(encoding="utf-8"))["results"][0]["total_cost_usd"], 0.5)

    def test_O12_every_entry_gets_its_own_container(self):
        run_dir = self.do_run([mk_task(1), mk_task(2)], arms=("B0", "Bplus"))
        self.assertEqual(len(self.docker.agent_started), 4)
        self.assertEqual(len({c.name for c in self.docker.agent_started}), 4)
        self.assertEqual(len(self.statuses(run_dir)), 4)


class Manifest(Lab):
    def test_O12_manifest_fields_per_arm(self):
        task = mk_task(1)
        run_dir = self.do_run([task], arms=("B0", "Bplus", "H"))
        head = fakes.HARNESS_REPO["head"]
        image = self.docker.image_id(task["image"])
        for arm in ("B0", "Bplus", "H"):
            m = json.loads((self.entry_dir(run_dir, task, arm) / "manifest.json").read_text(encoding="utf-8"))
            text = json.dumps(m)
            with self.subTest(arm=arm):
                self.assertEqual((m["task_id"], m["arm"], m["repeat"]), (task["task_id"], arm, 1))
                self.assertEqual(find(m, "model"), "claude-sonnet-5-5")
                self.assertEqual(find(m, "effort"), "medium")
                self.assertIn(sha256(compose.compose_prompt(task["brief"], arm)), text)
                self.assertIn(sha256(PREREG_TEXT), text)
                self.assertIn(image, text)
                self.assertIsNot(find(m, "config"), MISSING)
                self.assertTrue(find(m, "config"))
                if arm == "H":
                    self.assertIn(head, text)
                else:
                    self.assertNotIn(head, text)

    def test_O12_prompt_reaches_the_container_for_each_arm(self):
        task = mk_task(1)
        self.do_run([task], arms=("B0", "Bplus", "H"))
        by_arm = {arm: text for pr, arm, text in self.texts}
        self.assertEqual(set(by_arm), {"B0", "Bplus", "H"})
        for arm, text in by_arm.items():
            prompt = compose.compose_prompt(task["brief"], arm)
            self.assertIn(json.dumps(prompt)[1:-1], text, arm)

    def test_O12_arms_share_every_non_prompt_setting(self):
        task = mk_task(1)
        self.do_run([task], arms=("B0", "Bplus", "H"))
        started = self.docker.agent_started
        self.assertEqual(len(started), 3)

        def shape(c):
            k = dict(c.kwargs)
            k.pop("labels", None)
            return {"image": c.image, **k}
        self.assertEqual(shape(started[0]), shape(started[1]))
        self.assertEqual(shape(started[0]), shape(started[2]))

        def neutral(c, arm):
            inp = {k: v for k, v in c.driver_inputs[0].items() if k != "arm"}
            text = json.dumps(inp, sort_keys=True)
            return text.replace(json.dumps(compose.compose_prompt(task["brief"], arm))[1:-1], "<P>")
        b0, bplus = neutral(started[0], "B0"), neutral(started[1], "Bplus")
        self.assertIn("<P>", b0)
        self.assertEqual(b0, bplus)
        self.assertEqual(find(started[2].driver_inputs[0], "model"), find(started[0].driver_inputs[0], "model"))
        self.assertEqual(find(started[2].driver_inputs[0], "effort"), find(started[0].driver_inputs[0], "effort"))

    def test_O12_agent_settings_in_driver_input(self):
        task = mk_task(1)
        self.do_run([task], arms=("B0",))
        inp = self.docker.agent_started[0].driver_inputs[0]
        self.assertEqual(find(inp, "model"), "claude-sonnet-5-5")
        self.assertEqual(find(inp, "effort"), "medium")
        text = json.dumps(inp)
        self.assertNotIn(TOKEN, text)

    def test_O12_egress_proxy_allows_only_anthropic_and_agent_network_is_internal(self):
        self.do_run([mk_task(1)])
        self.assertTrue(self.docker.proxies)
        conf = self.docker.proxies[0]["conf_text"]
        self.assertIn("api.anthropic.com", conf)
        self.assertTrue(any(internal for _, internal in self.docker.networks))
        self.assertNotIn("github.com", conf)

    def test_O12_token_is_mounted_read_only_and_never_copied(self):
        self.do_run([mk_task(1)])
        mounts = self.docker.agent_started[0].kwargs["mounts"]
        token_mounts = [m for m in mounts if str(self.token_path) in m]
        self.assertEqual(len(token_mounts), 1)
        self.assertRegex(token_mounts[0], r"(:ro$|readonly|,ro\b)")
        for kind, dest, text in self.docker.staged_all:
            if kind in ("write", "copy"):
                self.assertNotIn(TOKEN, text)


class Scrub(Lab):
    def test_O12_QR8_token_is_scrubbed_from_every_file_under_the_run_dir(self):
        task = mk_task(1)
        run_dir = self.do_run([task])
        d = self.entry_dir(run_dir, task)
        files = snapshot(run_dir)
        self.assertTrue(files)
        for name, data in files.items():
            self.assertNotIn(TOKEN.encode(), data, name)
        survivors = [n for n, data in files.items() if b"keep-me-msg [REDACTED]" in data]
        self.assertTrue(survivors, "scrub must replace the token with [REDACTED] and keep other bytes")
        self.assertTrue(any(b'"token": "[REDACTED]"' in data for n, data in files.items() if "telemetry" in n))
        self.assertTrue(any("telemetry" in n for n in files))
        self.assertTrue((d / "state.json").is_file())

    def test_O12_QR8_token_is_scrubbed_after_resume_too(self):
        task = mk_task(1)
        self.script = {(1, "B0"): lambda n: "interrupted" if n == 1 else "completed"}
        with self.assertRaises(run_mod.Halted) as ctx:
            self.do_run([task])
        for name, data in snapshot(ctx.exception.run_dir).items():
            self.assertNotIn(TOKEN.encode(), data, name)
        run_dir = run_mod.resume(Path(ctx.exception.run_dir).name, cfg=self.mkcfg(), docker=self.docker,
                                 call_fn=FakeCall(["{}"]))
        for name, data in snapshot(run_dir).items():
            self.assertNotIn(TOKEN.encode(), data, name)


class Contract(Lab):
    def test_O12_F3_container_contract_of_one_entry(self):
        task = mk_task(1)
        self.do_run([task])
        cont = self.docker.agent_started[0]
        driver_execs = [e for e in cont.execs if "relay_driver" in " ".join(e["argv"])]
        self.assertEqual(len(driver_execs), 1)
        ex = driver_execs[0]
        self.assertEqual(ex["argv"], ["/opt/evaluation-py/venv/bin/python", "/opt/evaluation/agent/relay_driver.py",
                                      "/evaluation/in/input.json"])
        self.assertEqual((ex["user"], ex["workdir"]), ("nonroot", "/testbed"))
        self.assertIn("/opt/evaluation/agent/driver.py", cont.files())
        self.assertIn("/opt/evaluation/agent/relay_driver.py", cont.files())
        inp = json.loads(cont.files()["/evaluation/in/input.json"])
        for needle in ("relay_dir", "relay_timeout_s", "relay_poll_s"):
            self.assertIsNot(find(inp, needle), MISSING, needle)

    def test_O12_F2_run_snapshots_its_tasks_before_the_first_entry(self):
        tasks = [mk_task(1), mk_task(2)]
        run_dir = self.do_run(tasks)
        rows = [json.loads(ln) for ln in (Path(run_dir) / "tasks.jsonl").read_text(encoding="utf-8").splitlines() if ln.strip()]
        self.assertEqual([r["task_id"] for r in rows], [t["task_id"] for t in tasks])

    def test_O12_F3_rate_limit_not_allowed_interrupts_the_entry(self):
        for rl, halts in (({"status": "rejected", "resets_at": 1}, True), ({"status": "allowed"}, False), (None, False)):
            with self.subTest(rate_limit=rl):
                self.setUp()
                self.rate_limit = {(1, "B0"): rl}
                if halts:
                    with self.assertRaises(run_mod.Halted) as ctx:
                        self.do_run([mk_task(1)])
                    self.assertEqual(list(self.statuses(ctx.exception.run_dir).values()), ["interrupted"])
                else:
                    run_dir = self.do_run([mk_task(1)])
                    self.assertEqual(list(self.statuses(run_dir).values()), ["completed"])

    def test_O12_F3_state_status_error_is_finished_and_run_continues(self):
        self.script = {(1, "B0"): "error"}
        run_dir = self.do_run([mk_task(1), mk_task(2)])
        self.assertEqual(sorted(self.statuses(run_dir).values()), ["completed", "error"])


class Isolation(Lab):
    SECRETS = ("five-marker-zq", "build_gold_fixture_zq", "test_clamp_upper_bound_zq", "test_param_case_zq",
               "tests/test_ops.py", MERGE_SHA, "plain-not-forbidden-yy")

    def assert_clean(self, staged):
        for secret in self.SECRETS:
            with self.subTest(secret=secret):
                self.assertNotIn(secret, staged)

    def test_O27_nothing_gold_is_staged_into_plain_arm_containers_or_proxy(self):
        task = mk_task(1)
        self.do_run([task], arms=("B0", "Bplus"))
        staged = self.docker.staged_text()
        self.assertIn("TASKMARK_1", staged)
        self.assert_clean(staged)
        gold_lines = [ln[1:] for ln in task["gold_patch"].splitlines() if ln.startswith("+") and len(ln) > 12
                      and not ln.startswith("+++")]
        self.assertTrue(gold_lines)
        for line in gold_lines:
            self.assertNotIn(line, staged)

    def test_O27_harness_arm_non_archive_staging_has_no_gold_material(self):
        task = mk_task(1)
        self.do_run([task], arms=("H",))
        parts = [t for kind, _, t in self.docker.staged_all if kind != "copy"]
        staged = "\n".join(parts)
        self.assertIn("TASKMARK_1", staged)
        self.assert_clean(staged)

    def test_O27_driver_input_carries_no_intent_card_or_f2p_ids(self):
        task = mk_task(1)
        self.do_run([task])
        text = json.dumps(self.docker.agent_started[0].driver_inputs[0])
        self.assertNotIn("Keeps value in range.", text)
        self.assertNotIn("::test_", text)


class Concurrency(Lab):
    def check(self, concurrency, tasks=4):
        self.docker.driver_delay = 0.05
        run_dir = self.do_run([mk_task(pr) for pr in range(1, tasks + 1)], concurrency=concurrency)
        self.assertEqual(sorted(self.statuses(run_dir).values()), ["completed"] * tasks)
        return self.docker.agent_max

    def test_O25_concurrency_one_never_overlaps(self):
        self.assertEqual(self.check(1), 1)

    def test_O25_concurrency_three_with_four_entries_never_exceeds_three(self):
        peak = self.check(3)
        self.assertLessEqual(peak, 3)
        self.assertGreaterEqual(peak, 1)

    def test_O25_concurrency_three_overlaps_when_work_is_available(self):
        self.assertGreaterEqual(self.check(3), 2)

    def test_O25_every_container_is_released_at_the_end(self):
        self.check(3)
        self.assertEqual(self.docker.agent_live, 0)


class Resume(Lab):
    def setUp(self):
        super().setUp()
        self.tasks = [mk_task(pr) for pr in (1, 2, 3, 4)]
        self.script = {(3, "B0"): lambda n: "interrupted" if n == 1 else "completed"}

    def halted_run(self):
        with self.assertRaises(run_mod.Halted) as ctx:
            self.do_run(self.tasks)
        return ctx.exception

    def test_O12_C41_interrupt_halts_run_and_resume_finishes_it(self):
        halted = self.halted_run()
        self.assertTrue(halted.reason)
        run_dir = Path(halted.run_dir)
        before = self.statuses(run_dir)
        order = [(e["task_id"]) for e in self.run_json(run_dir)["entries"]]
        k = order.index(self.tasks[2]["task_id"])
        for tid in order[:k]:
            self.assertEqual(before[(tid, "B0", 1)], "completed")
        self.assertEqual(before[(order[k], "B0", 1)], "interrupted")
        for tid in order[k + 1:]:
            self.assertNotIn(before[(tid, "B0", 1)], ("completed", "stalled", "capped", "error"))
        started_later = [pr for pr, _ in self.driver_calls if self.tasks[pr - 1]["task_id"] in order[k + 1:]]
        self.assertEqual(started_later, [])
        self.assertEqual(self.driver_calls.count((3, "B0")), 1)

    def test_O12_QR6_resume_leaves_finished_entries_byte_identical_and_resumes_the_rest(self):
        halted = self.halted_run()
        run_dir = Path(halted.run_dir)
        order = [e["task_id"] for e in self.run_json(run_dir)["entries"]]
        k = order.index(self.tasks[2]["task_id"])
        finished = {tid: snapshot(run_dir / tid) for tid in order[:k]}
        self.assertTrue(all(finished.values()))
        out = run_mod.resume(run_dir.name, cfg=self.mkcfg(), docker=self.docker, call_fn=FakeCall(["{}"]))
        self.assertEqual(Path(out), run_dir)
        for tid, snap in finished.items():
            self.assertEqual(snapshot(run_dir / tid), snap, tid)
        after = self.statuses(run_dir)
        self.assertEqual(sorted(after.values()), ["completed"] * 4)
        self.assertEqual(self.driver_calls.count((1, "B0")), 1)
        self.assertEqual(self.driver_calls.count((2, "B0")), 1)
        self.assertEqual(self.driver_calls.count((3, "B0")), 2)
        self.assertEqual(self.driver_calls.count((4, "B0")), 1)

    def test_O12_C41_interrupted_entry_resumes_from_its_saved_session(self):
        halted = self.halted_run()
        run_mod.resume(Path(halted.run_dir).name, cfg=self.mkcfg(), docker=self.docker, call_fn=FakeCall(["{}"]))
        texts = [t for pr, arm, t in self.texts if pr == 3]
        self.assertEqual(len(texts), 2)
        self.assertNotIn("sess-3-B0", texts[0])
        self.assertIn("sess-3-B0", texts[1])

    def test_O12_resume_of_a_finished_run_starts_nothing(self):
        self.script = {}
        run_dir = self.do_run(self.tasks)
        calls = len(self.driver_calls)
        run_mod.resume(Path(run_dir).name, cfg=self.mkcfg(), docker=self.docker, call_fn=FakeCall(["{}"]))
        self.assertEqual(len(self.driver_calls), calls)

    def test_O12_QR7_run_json_survives_a_crash_between_write_and_rename(self):
        halted = self.halted_run()
        run_dir = Path(halted.run_dir)
        before = (run_dir / "run.json").read_bytes()
        with failing_replace("run.json"):
            try:
                run_mod.resume(run_dir.name, cfg=self.mkcfg(), docker=self.docker, call_fn=FakeCall(["{}"]))
            except OSError:
                pass
        self.assertEqual((run_dir / "run.json").read_bytes(), before)

    def test_O12_QR7_unpatched_resume_does_change_run_json(self):
        halted = self.halted_run()
        run_dir = Path(halted.run_dir)
        before = (run_dir / "run.json").read_bytes()
        run_mod.resume(run_dir.name, cfg=self.mkcfg(), docker=self.docker, call_fn=FakeCall(["{}"]))
        self.assertNotEqual((run_dir / "run.json").read_bytes(), before)

    def test_O12_halted_carries_run_dir_and_reason(self):
        halted = self.halted_run()
        self.assertTrue(Path(halted.run_dir).is_dir())
        self.assertIsInstance(halted, RuntimeError)
        self.assertTrue(isinstance(halted.reason, str) and halted.reason)


if __name__ == "__main__":
    unittest.main()

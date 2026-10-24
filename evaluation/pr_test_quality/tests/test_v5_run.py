import contextlib
import io
import json
import re
import secrets
import subprocess
import tarfile
from pathlib import Path
from unittest import mock

from evaluation.pr_test_quality import __main__ as cli
from evaluation.pr_test_quality import run as run_mod
from evaluation.pr_test_quality import usersim
from evaluation.pr_test_quality.tests import fakes
from evaluation.pr_test_quality.tests.fakes import ROOT, TOKEN, FakeCall, find, snapshot, udiff
from evaluation.pr_test_quality.tests.test_run import AGENT_DIFF, Lab, mk_task


def randomize(task, uid, sha):
    """Gold strings that exist nowhere in the repository, so scanning archives is meaningful."""
    text = json.dumps(task).replace("zq", uid).replace("c0ffee00c0ffee00c0ffee00c0ffee00c0ffee11", sha)
    return json.loads(text)


class DriverInput(Lab):
    def test_O12_F1_every_arm_gets_the_default_cfg_limits(self):
        task = mk_task(1)
        self.do_run([task], arms=("B0", "Bplus", "H"))
        cfg = self.mkcfg()
        inputs = {}
        for cont in self.docker.agent_started:
            inp = cont.driver_inputs[0]
            inputs[inp["arm"]] = inp
        self.assertEqual(set(inputs), {"B0", "Bplus", "H"})
        for arm, inp in inputs.items():
            with self.subTest(arm=arm):
                self.assertEqual(inp["wall_clock_s"], 180 * 60)
                self.assertEqual(inp["max_user_turns"], 8)
                self.assertEqual(inp["disallowed_tools"], cfg["agent"]["disallowed_tools"])
                self.assertEqual((inp["model"], inp["effort"]), ("claude-sonnet-5-5", "medium"))

    def test_O12_F1_h_input_is_identical_to_b0_except_prompt_and_arm(self):
        task = mk_task(1)
        self.do_run([task], arms=("B0", "H"))
        b0, h = [c.driver_inputs[0] for c in self.docker.agent_started]
        self.assertEqual(b0["arm"], "B0")
        diff_keys = {k for k in set(b0) | set(h) if b0.get(k) != h.get(k)}
        self.assertEqual(diff_keys, {"arm", "prompt"})
        self.assertLessEqual(diff_keys, {"arm", "prompt"})
        self.assertEqual(h["prompt"], "/workflow-approach " + b0["prompt"])

    def test_O12_F1_a_relay_is_started_and_stopped_per_entry_and_its_rows_land_in_the_entry_dir(self):
        events = []

        class Rec:
            def __init__(self, container, task, record_path, *, call_fn, cfg, token):
                self.path = Path(record_path)
                events.append(("init", self.path, token))

            def start(self):
                events.append(("start", self.path))
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with open(self.path, "a", encoding="utf-8") as fh:
                    fh.write(json.dumps({"kind": "ask", "n": 1, "note": "key " + TOKEN}) + "\n")

            def stop(self):
                events.append(("stop", self.path))

        tasks = [mk_task(1), mk_task(2)]
        with mock.patch.object(usersim, "Relay", Rec):
            run_dir = self.do_run(tasks, arms=("B0", "H"))
        inits = [e for e in events if e[0] == "init"]
        self.assertEqual(len(inits), 4)
        self.assertEqual({e[2] for e in inits}, {TOKEN})
        self.assertEqual([e[0] for e in events if e[0] != "init"].count("start"), 4)
        self.assertEqual([e[0] for e in events if e[0] != "init"].count("stop"), 4)
        for task in tasks:
            for arm in ("B0", "H"):
                path = self.entry_dir(run_dir, task, arm) / "usersim.jsonl"
                self.assertEqual(path.read_text(encoding="utf-8"), '{"kind": "ask", "n": 1, "note": "key [REDACTED]"}\n')
        starts = [i for i, e in enumerate(events) if e[0] == "start"]
        stops = [i for i, e in enumerate(events) if e[0] == "stop"]
        self.assertTrue(all(a < b for a, b in zip(starts, stops)))

    def test_O12_F1_relay_is_stopped_even_when_the_entry_errors(self):
        events = []

        class Rec:
            def __init__(self, *a, **k):
                pass

            def start(self):
                events.append("start")

            def stop(self):
                events.append("stop")

        self.script = {(1, "B0"): "error"}
        with mock.patch.object(usersim, "Relay", Rec):
            self.do_run([mk_task(1)])
        self.assertEqual(events, ["start", "stop"])


class Scrub(Lab):
    def test_O12_F4_token_remaining_after_scrub_makes_the_entry_error(self):
        self_ref = "ab[REDACTED]cd"
        self.token_path.write_text(self_ref, encoding="utf-8")
        base = self.driver

        def drv(cont, inp):
            out = base(cont, inp)
            out["files"]["messages.jsonl"] = ("x ab" + self_ref + "cd y\n").encode()
            return out
        self.docker.driver_policy = drv
        task = mk_task(1)
        run_dir = self.do_run([task])
        self.assertEqual(list(self.statuses(run_dir).values()), ["error"])
        state = json.loads((self.entry_dir(run_dir, task) / "state.json").read_text(encoding="utf-8"))
        self.assertEqual(state["status"], "error")
        self.assertEqual(state["reason"], "token remained after scrub")

    def test_O12_F4_clean_scrub_keeps_the_entry_status(self):
        task = mk_task(1)
        run_dir = self.do_run([task])
        self.assertEqual(list(self.statuses(run_dir).values()), ["completed"])


class Network(Lab):
    def test_O12_agent_container_is_on_the_internal_network_only(self):
        self.do_run([mk_task(1), mk_task(2)], arms=("B0", "H"))
        internal = {name for name, flag in self.docker.networks if flag}
        self.assertEqual(len(internal), 1)
        for cont in self.docker.agent_started:
            self.assertIn(cont.kwargs["network"], internal)
        proxy = self.docker.proxies[0]
        self.assertIn(list(internal)[0], proxy["networks"])
        self.assertEqual(len(proxy["networks"]), 2)
        self.assertNotIn(proxy["name"], [c.name for c in self.docker.agent_started])

    def test_O12_proxy_conf_allows_exactly_the_anthropic_api_and_denies_everything_else(self):
        self.do_run([mk_task(1)])
        conf = self.docker.proxies[0]["conf_text"]
        hosts = re.findall(r"^acl\s+\S+\s+dstdomain\s+(\S+)", conf, re.M)
        self.assertEqual(hosts, ["api.anthropic.com"])
        accesses = re.findall(r"^http_access\s+(allow|deny)\s+(.*)$", conf, re.M)
        self.assertEqual(accesses[-1], ("deny", "all"))
        self.assertNotIn(("allow", "all"), accesses)
        allowed_acls = {a for verdict, rest in accesses if verdict == "allow" for a in rest.split()}
        defined = set(re.findall(r"^acl\s+(\S+)\s", conf, re.M))
        self.assertTrue(allowed_acls <= defined)
        host_acl = re.findall(r"^acl\s+(\S+)\s+dstdomain", conf, re.M)[0]
        self.assertTrue(all(host_acl in rest.split() for verdict, rest in accesses if verdict == "allow"))
        self.assertEqual(len([1 for v, _ in accesses if v == "allow"]), 1)


class HInstall(Lab):
    def setUp(self):
        super().setUp()
        self.uid = secrets.token_hex(5)
        self.sha = secrets.token_hex(20)
        self.task = randomize(mk_task(1), self.uid, self.sha)

    def run_arms(self, arms=("B0", "Bplus", "H")):
        run_dir = self.do_run([self.task], arms=arms)
        return run_dir, {c.driver_inputs[0]["arm"]: c for c in self.docker.agent_started}

    def test_O29_h_stages_a_harness_and_installer_only_archive_and_installs_with_y_answers(self):
        head = fakes.HARNESS_REPO["head"]
        run_dir, conts = self.run_arms()
        h = conts["H"]
        archives = [(dest, data) for dest, data in h.copied if tarfile.is_tarfile(__import__("io").BytesIO(data))]
        self.assertEqual(len(archives), 1)
        with tarfile.open(fileobj=__import__("io").BytesIO(archives[0][1])) as tar:
            names = [m.name for m in tar.getmembers()]
        tops = {n.split("/")[0] for n in names if n not in (".", "")}
        self.assertEqual(tops, {"harness", "installer"})
        self.assertIn("installer/harness.py", names)
        self.assertTrue(any("/opt/harness-src" in " ".join(e["argv"]) for e in h.execs))
        argvs = [" ".join(e["argv"]) for e in h.execs]
        install = [i for i, a in enumerate(argvs) if "installer/harness.py" in a and "install" in a]
        self.assertEqual(len(install), 1)
        text = argvs[install[0]]
        self.assertIn("/testbed", text)
        self.assertIn("--no-ci", text)
        self.assertRegex(text, r"(printf|yes|echo)[^|]*y")
        commits = [i for i, a in enumerate(argvs) if "git" in a and "commit" in a]
        self.assertEqual(len(commits), 1)
        self.assertGreater(commits[0], install[0])
        driver_run = [i for i, a in enumerate(argvs) if "relay_driver.py" in a]
        self.assertGreater(driver_run[0], commits[0])
        manifest = json.loads((self.entry_dir(run_dir, self.task, "H") / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["harness_commit"], head)
        self.assertRegex(manifest["harness_commit"], r"^[0-9a-f]{40}$")

    def test_O29_b0_and_bplus_get_no_archive_and_no_install(self):
        run_dir, conts = self.run_arms()
        for arm in ("B0", "Bplus"):
            cont = conts[arm]
            self.assertEqual([d for d, data in cont.copied if "harness" in d], [])
            for ex in cont.execs:
                text = " ".join(ex["argv"])
                self.assertNotIn("harness.py", text)
                self.assertNotIn("--no-ci", text)
                self.assertNotIn("/opt/harness-src", text)
            self.assertNotIn("commit", " ".join(" ".join(e["argv"]) for e in cont.execs))
            manifest = json.loads((self.entry_dir(run_dir, self.task, arm) / "manifest.json").read_text())
            self.assertIsNone(manifest["harness_commit"])

    def test_O29_QR9_h_staged_files_carry_no_gold_strings(self):
        run_dir, conts = self.run_arms()
        h = conts["H"]
        blobs = [text for kind, dest, text in h.staged]
        for dest, data in h.copied:
            if tarfile.is_tarfile(__import__("io").BytesIO(data)):
                with tarfile.open(fileobj=__import__("io").BytesIO(data)) as tar:
                    for member in tar.getmembers():
                        if member.isfile():
                            blobs.append(tar.extractfile(member).read().decode("utf-8", "replace"))
            else:
                blobs.append(data.decode("utf-8", "replace"))
        blobs.extend(" ".join(e["argv"]) for e in h.execs)
        everything = "\n".join(blobs)
        self.assertTrue(everything)
        for secret in (self.uid, self.sha, self.sha[:7]):
            self.assertNotIn(secret, everything)
        self.assertNotIn(self.uid, json.dumps(h.driver_inputs))


class RetryErrors(Lab):
    def cli_run(self, argv):
        deps = {"docker": self.docker, "call_fn": FakeCall(["{}"]), "run_fn": mock.Mock(), "gh_fn": mock.Mock()}
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            try:
                code = cli.main(argv, cfg=self.mkcfg(), deps=deps)
            except SystemExit as exc:
                code = exc.code
        return code, out.getvalue()

    def entries(self, run_dir):
        return {e["task_id"]: e for e in self.run_json(run_dir)["entries"]}

    def test_O31_error_with_one_attempt_is_retried_from_scratch_and_can_complete(self):
        tasks = [mk_task(1), mk_task(2)]
        self.script = {(1, "B0"): lambda n: "error" if n == 1 else "completed"}
        run_dir = self.do_run(tasks)
        first = self.entries(run_dir)
        self.assertEqual((first[tasks[0]["task_id"]]["status"], first[tasks[0]["task_id"]]["attempts"]), ("error", 1))
        self.assertEqual((first[tasks[1]["task_id"]]["status"], first[tasks[1]["task_id"]]["attempts"]), ("completed", 1))
        before_other = snapshot(Path(run_dir) / tasks[1]["task_id"])
        started = len(self.docker.agent_started)
        code, out = self.cli_run(["run", "--retry-errors", Path(run_dir).name])
        self.assertEqual(code, 0, out)
        after = self.entries(run_dir)
        self.assertEqual((after[tasks[0]["task_id"]]["status"], after[tasks[0]["task_id"]]["attempts"]), ("completed", 2))
        self.assertEqual(len(self.docker.agent_started), started + 1)
        self.assertIsNot(self.docker.agent_started[-1], self.docker.agent_started[0])
        self.assertEqual(self.docker.agent_started[-1].fs.get('/evaluation/out/state.json'), None)
        manifest = json.loads((self.entry_dir(run_dir, tasks[0]) / "manifest.json").read_text())
        self.assertEqual(manifest["attempts"], 2)
        self.assertEqual(snapshot(Path(run_dir) / tasks[1]["task_id"]), before_other)
        self.assertEqual(self.driver_calls.count((1, "B0")), 2)

    def test_O31_second_error_is_final_and_never_retried_again(self):
        task = mk_task(1)
        self.script = {(1, "B0"): "error"}
        run_dir = self.do_run([task])
        self.assertEqual(self.cli_run(["run", "--retry-errors", Path(run_dir).name])[0], 0)
        entry = self.entries(run_dir)[task["task_id"]]
        self.assertEqual((entry["status"], entry["attempts"]), ("error", 2))
        calls = len(self.driver_calls)
        code, out = self.cli_run(["run", "--retry-errors", Path(run_dir).name])
        self.assertEqual(code, 0, out)
        self.assertEqual(len(self.driver_calls), calls)
        self.assertEqual(self.entries(run_dir)[task["task_id"]]["attempts"], 2)

    def test_O31_retry_leaves_completed_and_interrupted_entries_alone(self):
        tasks = [mk_task(1), mk_task(2)]
        self.script = {(2, "B0"): "interrupted"}
        with self.assertRaises(run_mod.Halted) as ctx:
            self.do_run(tasks)
        calls = list(self.driver_calls)
        code, out = self.cli_run(["run", "--retry-errors", Path(ctx.exception.run_dir).name])
        self.assertEqual(self.driver_calls, calls)

    def test_O31_report_refuses_unretried_error_naming_the_retry_command(self):
        task = mk_task(1)
        self.script = {(1, "B0"): "error"}
        run_dir = self.do_run([task])
        code, out = self.cli_run(["report", Path(run_dir).name])
        self.assertEqual(code, 2, out)
        self.assertIn("python3 -m evaluation.pr_test_quality run --retry-errors %s" % Path(run_dir).name, out)

    def test_O31_report_refuses_interrupted_entries_naming_resume(self):
        self.script = {(1, "B0"): "interrupted"}
        with self.assertRaises(run_mod.Halted) as ctx:
            self.do_run([mk_task(1)])
        rid = Path(ctx.exception.run_dir).name
        code, out = self.cli_run(["report", rid])
        self.assertEqual(code, 2, out)
        self.assertIn("--resume %s" % rid, out)

    def test_O31_retry_unknown_run_is_refused(self):
        code, out = self.cli_run(["run", "--retry-errors", "nope"])
        self.assertEqual(code, 2, out)
        self.assertIn("nope", out)


class AtomicEntries(Lab):
    def cli_run(self, argv):
        deps = {"docker": self.docker, "call_fn": FakeCall(["{}"]), "run_fn": mock.Mock(), "gh_fn": mock.Mock()}
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            try:
                code = cli.main(argv, cfg=self.mkcfg(), deps=deps)
            except SystemExit as exc:
                code = exc.code
        return code, out.getvalue()

    def interrupted(self):
        self.setUp()
        self.script = {(1, "B0"): lambda n: "interrupted" if n == 1 else "completed"}
        task = mk_task(1)
        with self.assertRaises(run_mod.Halted) as ctx:
            self.do_run([task])
        run_dir = Path(ctx.exception.run_dir)
        return task, run_dir

    def target(self, run_dir, task, name):
        return run_dir / "run.json" if name == "run.json" else self.entry_dir(run_dir, task) / name

    def test_O12_QR7_entry_and_run_files_survive_a_crash_between_write_and_rename(self):
        from evaluation.pr_test_quality.tests.fakes import failing_replace
        for name in ("manifest.json", "state.json", "run.json"):
            task, run_dir = self.interrupted()
            path = self.target(run_dir, task, name)
            before = path.read_bytes()
            with failing_replace(name):
                try:
                    run_mod.resume(run_dir.name, cfg=self.mkcfg(), docker=self.docker, call_fn=FakeCall(["{}"]))
                except OSError:
                    pass
            with self.subTest(file=name):
                self.assertTrue(path.exists())
                self.assertEqual(path.read_bytes(), before)

    def test_O12_QR7_the_same_resume_without_a_crash_does_rewrite_those_files(self):
        for name in ("state.json", "run.json"):
            task, run_dir = self.interrupted()
            path = self.target(run_dir, task, name)
            before = path.read_bytes()
            run_mod.resume(run_dir.name, cfg=self.mkcfg(), docker=self.docker, call_fn=FakeCall(["{}"]))
            with self.subTest(file=name):
                self.assertNotEqual(path.read_bytes(), before)


class F19Collection(Lab):
    START = "0123456789abcdef0123456789abcdef01234567"

    def setUp(self):
        super().setUp()
        self.state = {"src/calc/ops.py": ("def identity(v):\n    return v\n", "def identity(v):\n    return v\n\n\ndef clamp(): pass\n"),
                      "tests/test_new.py": (None, "def test_new(): pass\n"),
                      "src/calc/old.py": ("print('bye')\n", None),
                      ".claude/settings.json": ("{}\n", "{\"a\": 1}\n")}
        self.docker.agent_state = lambda cont: self.state if cont.driver_inputs else None

    def split(self, run_dir, task):
        return json.loads((self.entry_dir(run_dir, task) / "split.json").read_text(encoding="utf-8"))

    def test_O12_F19_sequence_add_diff_show_for_non_new_paths_and_read_for_non_deleted_paths(self):
        task = mk_task(1)
        self.do_run([task])
        cont = self.docker.agent_started[0]
        argvs = [e["argv"] for e in cont.execs]
        add = [i for i, a in enumerate(argvs) if a[:3] == ["git", "add", "-A"]]
        diff = [i for i, a in enumerate(argvs) if a[:1] == ["git"] and "diff" in a and self.START in a
                and "--name-status" not in a]
        self.assertEqual(len(add), 1)
        self.assertEqual(len(diff), 1)
        self.assertLess(add[0], diff[0])
        shown = sorted(a[-1] for a in argvs if a[:1] == ["git"] and "show" in a)
        self.assertIn(self.START + ":src/calc/ops.py", shown)
        self.assertIn(self.START + ":src/calc/old.py", shown)
        self.assertNotIn(self.START + ":tests/test_new.py", shown)
        self.assertFalse([s for s in shown if ".claude" in s])

    def test_O12_F19_split_json_base_and_after_are_collected_from_the_container(self):
        task = mk_task(1)
        data = self.split(self.do_run([task]), task)
        self.assertEqual(data["base"]["src/calc/ops.py"], self.state["src/calc/ops.py"][0])
        self.assertEqual(data["after"]["src/calc/ops.py"], self.state["src/calc/ops.py"][1])
        self.assertIsNone(data["base"].get("tests/test_new.py"))
        self.assertEqual(data["after"]["tests/test_new.py"], "def test_new(): pass\n")
        self.assertEqual(data["base"]["src/calc/old.py"], "print('bye')\n")
        self.assertIsNone(data["after"].get("src/calc/old.py"))
        self.assertNotIn(".claude/settings.json", data["base"])
        self.assertNotIn(".claude/settings.json", data["after"])
        self.assertIn(".claude/settings.json", data["split"]["harness"])
        self.assertIn("tests/test_new.py", data["split"]["tests"])
        self.assertIn("src/calc/ops.py", data["split"]["src"])

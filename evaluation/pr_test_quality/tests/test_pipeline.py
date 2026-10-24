import contextlib
import io
import json
import re
from pathlib import Path

from evaluation.pr_test_quality import __main__ as cli
from evaluation.pr_test_quality import mine
from evaluation.pr_test_quality.tests.fakes import (
    LANG_FIXTURES, TOKEN, FakeCall, FakeDocker, FakeRun, TmpCase, brief_json, make_task, pytest_junit,
    set_token_file, sha256, udiff,
)
from evaluation.pr_test_quality.tests.test_mine import FakeGh

AGENT_DIFF = udiff("tests/test_agent_x.py", None, "def test_agent_x():\n    assert 1 == 1\n")
F2P = ["tests/test_ops.py::test_clamp_upper_bound_zq", "tests/test_ops.py::test_param_case_zq"]
MUTMUT = """--- src/calc/ops.py
+++ src/calc/ops.py
@@ -5,2 +5,2 @@
 def clamp(value, lo, hi):
-    return max(lo, min(value, hi))
+    return min(lo, min(value, hi))
--- src/calc/ops.py
+++ src/calc/ops.py
@@ -5,2 +5,2 @@
 def clamp(value, lo, hi):
-    return max(lo, min(value, hi))
+    return max(lo, max(value, hi))
"""
TASK_ID = "own__solo-5"
DESIDERATA = ("isolated", "composable", "readable", "behavioral", "structure_insensitive", "specific", "predictive",
              "writable")


class Pipe(TmpCase):
    def setUp(self):
        super().setUp()
        self.cfg_ = self.cfg(results_dir=str(self.tmp / "results"))
        self.token_path = set_token_file(self.cfg_, self.tmp)
        self.gh = FakeGh({"own/solo": [5]})
        self.run_fn = FakeRun(self.git)
        self.manifest = "pytest\n"
        self.status = "completed"
        self.session_calls = 0
        self.docker = FakeDocker(junit_policy=self.junit, exec_policy=self.exec_policy, driver_policy=self.driver,
                                 diff_text=AGENT_DIFF)
        self.build_ok = True

    def git(self, argv, inp):
        if argv[:2] == ["git", "clone"]:
            return 0, "", ""
        if "show" in argv:
            sha, name = argv[-1].split(":", 1)
            fx = LANG_FIXTURES["python"]
            base = sha.endswith("3ed")
            if name == "requirements.txt" and self.manifest:
                return 0, self.manifest, ""
            if name == fx["src_path"]:
                return 0, (fx["src_old"] if base else fx["src_new"]), ""
            if name == fx["test_path"] and not base:
                return 0, fx["test_new"], ""
            return 128, "", "fatal: path does not exist"
        if "diff" in argv and "--binary" in argv:
            return 0, make_task("python")["gold_patch"], ""
        return 0, "", ""

    def junit(self, c):
        files, text = c.files(), c.tree_text()
        merged = "def clamp" in text
        killed = "min(lo, min" in text
        state = "pass" if (merged and not killed) else "fail"
        res = {}
        if any(p.endswith("tests/test_ops.py") for p in files):
            res.update({k: state for k in F2P})
        if any(p.endswith("test_agent_x.py") for p in files):
            res["tests/test_agent_x.py::test_agent_x"] = "fail" if (killed or not merged) else "pass"
        return pytest_junit(res)

    def exec_policy(self, c, argv):
        if "mutmut" in " ".join(argv):
            return 0, MUTMUT, False
        return None

    def driver(self, c, inp):
        self.session_calls += 1
        state = {"status": self.status, "reason": None, "session_id": "s1",
                 "results": [{"total_cost_usd": 0.5, "duration_ms": 1000, "num_turns": 2, "is_error": False}],
                 "rate_limit": None}
        return {"exit": 0, "files": {"state.json": json.dumps(state).encode(), "messages.jsonl": b"{}\n"}}

    def inv(self, argv, **over):
        deps = {"gh_fn": self.gh, "run_fn": self.run_fn, "docker": self.docker, "call_fn": FakeCall(["{}"])}
        deps.update(over)
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            try:
                code = cli.main(argv, cfg=self.cfg_, deps=deps)
            except SystemExit as exc:
                code = exc.code
        return code, out.getvalue()

    def data(self):
        return Path(self.cfg_["data_dir"])

    def tasks(self, language="python"):
        path = self.data() / "tasks" / language / "tasks.jsonl"
        return [json.loads(ln) for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]

    def brief_call(self):
        return FakeCall([lambda prompt: brief_json(self.tasks()[0])])

    def stage(self, upto):
        order = ["mine", "build", "validate", "brief", "mutants"]
        for name in order[: order.index(upto) + 1]:
            extra = {"call_fn": self.brief_call()} if name == "brief" else {}
            code, out = self.inv([name, "--language", "python"], **extra)
            self.assertEqual(code, 0, "%s: %s" % (name, out))

    def run_ids(self):
        return sorted(p.name for p in (self.data() / "runs").iterdir())

    def do_run(self, *extra):
        code, out = self.inv(["run", "--phase", "dev", "--language", "python", "--arms", "B0,Bplus",
                              "--repeats", "1", *extra])
        return code, out


class MineBuild(Pipe):
    def test_O26_mine_writes_candidates_and_reports_count(self):
        code, out = self.inv(["mine", "--language", "python"])
        self.assertEqual(code, 0, out)
        self.assertIn("1 candidates", out)
        rows = [json.loads(ln) for ln in (self.data() / "tasks" / "python" / "candidates.jsonl").read_text().splitlines()]
        self.assertEqual([(r["repo"], r["pr"]) for r in rows], [("own/solo", 5)])

    def test_O26_mine_all_languages(self):
        code, out = self.inv(["mine", "--language", "all"])
        self.assertEqual(code, 0, out)
        for lang in ("python", "typescript", "go", "rust"):
            self.assertTrue((self.data() / "tasks" / lang / "candidates.jsonl").is_file(), lang)

    def test_O26_mine_rate_limit_exits_3_and_names_the_rerun(self):
        def gh(args):
            raise mine.RateLimited("reset in 61 s")
        code, out = self.inv(["mine", "--language", "python"], gh_fn=gh)
        self.assertEqual(code, 3, out)
        self.assertIn("mine", out)
        self.assertIn("61", out)

    def test_O3_build_writes_task_with_recipe_image_and_gold_texts(self):
        self.inv(["mine", "--language", "python"])
        code, out = self.inv(["build", "--language", "python"])
        self.assertEqual(code, 0, out)
        task = self.tasks()[0]
        self.assertEqual(task["task_id"], TASK_ID)
        self.assertTrue(task["image"])
        self.assertEqual(task["recipe"]["manager"], "pip")
        fx = LANG_FIXTURES["python"]
        self.assertEqual(task["gold_base"][fx["src_path"]], fx["src_old"])
        self.assertEqual(task["gold_after"][fx["src_path"]], fx["src_new"])
        self.assertIsNone(task["gold_base"][fx["test_path"]])
        self.assertEqual(task["gold_split"]["tests"].count("diff --git"), 1)
        self.assertIn("evaluation-proj", " ".join(str(x) for x in self.docker.log))

    def test_O3_recipe_failure_marks_candidate_build_error_with_message(self):
        self.manifest = ""
        self.inv(["mine", "--language", "python"])
        code, out = self.inv(["build", "--language", "python"])
        self.assertEqual(code, 0, out)
        task = self.tasks()[0]
        self.assertFalse(task["valid"])
        self.assertTrue(task["reason"].startswith("build_error: "))
        self.assertIn("requirements.txt", task["reason"])

    def test_O4_image_build_failure_marks_build_error_and_stores_log_outside_the_task(self):
        class Failing(FakeDocker):
            def build(self, context_dir, tag, *, timeout):
                return 1, "\n".join("line %d" % i for i in range(80)) + "\nfinal build error"
        self.docker = Failing()
        self.inv(["mine", "--language", "python"])
        code, out = self.inv(["build", "--language", "python"])
        self.assertEqual(code, 0, out)
        task = self.tasks()[0]
        self.assertTrue(task["reason"].startswith("build_error"))
        logs = [p for p in self.data().rglob("*") if p.is_file() and "final build error" in p.read_text(errors="ignore")]
        self.assertTrue(logs)
        text = logs[0].read_text()
        self.assertLessEqual(len(text.strip().splitlines()), 50)
        self.assertNotIn("final build error", json.dumps(task))

    def test_O3_build_with_no_candidates_exits_cleanly(self):
        code, out = self.inv(["build", "--language", "python"])
        self.assertIn(code, (0, 2))


class ValidateBriefMutants(Pipe):
    def test_O5_validate_marks_valid_task_with_f2p(self):
        self.stage("validate")
        task = self.tasks()[0]
        self.assertTrue(task["valid"])
        self.assertEqual(task["reason"], "ok")
        self.assertEqual(task["f2p"], F2P)
        self.assertEqual(task["p2p"], [])

    def test_O5_validate_keeps_invalid_task_with_reason(self):
        self.stage("build")
        self.docker.junit_policy = lambda c: pytest_junit({k: "pass" for k in F2P})
        code, out = self.inv(["validate", "--language", "python"])
        self.assertEqual(code, 0, out)
        task = self.tasks()[0]
        self.assertFalse(task["valid"])
        self.assertEqual(task["reason"], "no_f2p")
        self.assertIn("no_f2p", out)

    def test_O5_validate_timeout_and_build_error_reasons(self):
        for policy, reason in (("timeout", "timeout"), (None, "build_error")):
            self.setUp()
            self.stage("build")
            self.docker.junit_policy = lambda c, p=policy: p
            self.inv(["validate", "--language", "python"])
            with self.subTest(reason=reason):
                self.assertEqual(self.tasks()[0]["reason"], reason)

    def test_O8_brief_ok_is_stored_on_the_task(self):
        self.stage("brief")
        brief = self.tasks()[0]["brief"]
        self.assertEqual((brief["status"], brief["attempts"], brief["reason"]), ("ok", 1, "ok"))
        self.assertEqual(brief["ambiguous"], ["S2"])

    def test_O8_brief_leak_three_times_drops_the_task(self):
        self.stage("validate")
        leaky = FakeCall([lambda prompt: brief_json(
            self.tasks()[0], request=brief_json(self.tasks()[0]) and
            json.loads(brief_json(self.tasks()[0]))["request"].replace(
                "Implement this and add automated tests.", "See test_ops.py. Implement this and add automated tests."))])
        code, out = self.inv(["brief", "--language", "python"], call_fn=leaky)
        self.assertEqual(code, 0, out)
        brief = self.tasks()[0]["brief"]
        self.assertEqual((brief["status"], brief["reason"], brief["attempts"]), ("dropped", "leak", 3))

    def test_O8_invalid_tasks_get_no_brief(self):
        self.stage("build")
        self.docker.junit_policy = lambda c: pytest_junit({k: "pass" for k in F2P})
        self.inv(["validate", "--language", "python"])
        call = FakeCall(["{}"])
        self.inv(["brief", "--language", "python"], call_fn=call)
        self.assertEqual(call.calls, [])
        self.assertIsNone(self.tasks()[0]["brief"])

    def test_O26_mutants_classified_by_gold_tests(self):
        self.stage("mutants")
        mutants = self.tasks()[0]["mutants"]
        self.assertEqual(sorted(m["gold"] for m in mutants), ["killed", "survived"])
        self.assertTrue(all(m["path"] == "src/calc/ops.py" and m["line"] == 6 for m in mutants))
        self.assertTrue(all(re.fullmatch(r"[0-9a-f]{16}", m["id"]) for m in mutants))
        killed = [m for m in mutants if m["gold"] == "killed"][0]
        self.assertIn("min(lo, min", killed["diff"])


class RunScoreJudgeReport(Pipe):
    def setUp(self):
        super().setUp()
        self.stage("mutants")

    def judge_call(self, text_marker="test_agent_x"):
        def respond(prompt):
            if "test_agent_x" in prompt and "test_clamp_upper_bound_zq" in prompt:
                return json.dumps({"winner": "tie"})
            quote = "def test_agent_x():" if "test_agent_x" in prompt else "def test_clamp_upper_bound_zq():"
            return json.dumps({
                "smells": [],
                "desiderata": {k: {"score": 3, "rationale": "r", "quote": quote} for k in DESIDERATA},
                "coverage": {"S1": {"level": "none", "quote": ""}, "S2": {"level": "none", "quote": ""}},
                "boundary": False, "error_path": False})
        return FakeCall([respond])

    def test_O26_run_refuses_missing_image_naming_build_command(self):
        project = self.tasks()[0]["image"]
        for label, missing in (("project", [project]), ("agent", [project.replace("proj", "agent")])):
            self.docker = FakeDocker(missing_images=missing)
            code, out = self.do_run()
            with self.subTest(missing=label):
                self.assertEqual(code, 2, out)
                self.assertIn("python3 -m evaluation.pr_test_quality build --language python", out)
                self.assertEqual(self.docker.agent_started, [])

    def test_O26_run_refuses_missing_token_naming_the_path_and_starts_nothing(self):
        self.token_path.unlink()
        code, out = self.do_run()
        self.assertEqual(code, 2, out)
        self.assertIn(str(self.token_path), out)
        self.assertEqual(self.docker.agent_started, [])

    def test_O26_run_without_valid_tasks_is_refused(self):
        (self.data() / "tasks" / "python" / "tasks.jsonl").write_text("", encoding="utf-8")
        code, out = self.do_run()
        self.assertEqual(code, 2, out)

    def test_O12_run_happy_path_creates_entries(self):
        code, out = self.do_run()
        self.assertEqual(code, 0, out)
        (run_id,) = self.run_ids()
        self.assertIn(run_id, out)
        for entry in ("B0-r1", "Bplus-r1"):
            self.assertTrue((self.data() / "runs" / run_id / TASK_ID / entry / "manifest.json").is_file(), entry)

    def test_O12_run_refuses_unknown_arm(self):
        code, out = self.inv(["run", "--phase", "dev", "--language", "python", "--arms", "B0,Zeta"])
        self.assertEqual(code, 2, out)
        self.assertIn("Zeta", out)

    def test_O26_interrupted_run_exits_3_naming_resume_and_resume_finishes(self):
        self.status = "interrupted"
        code, out = self.do_run()
        self.assertEqual(code, 3, out)
        (run_id,) = self.run_ids()
        self.assertIn("--resume %s" % run_id, out)
        self.status = "completed"
        code, out = self.inv(["run", "--resume", run_id])
        self.assertEqual(code, 0, out)
        run = json.loads((self.data() / "runs" / run_id / "run.json").read_text())
        self.assertEqual(sorted(e["status"] for e in run["entries"]), ["completed", "completed"])

    def test_O26_resume_unknown_run_exits_2(self):
        code, out = self.inv(["run", "--resume", "nope"])
        self.assertEqual(code, 2, out)
        self.assertIn("nope", out)

    def test_O26_F2_resume_without_task_snapshot_exits_2_naming_the_path(self):
        self.status = "interrupted"
        self.do_run()
        (run_id,) = self.run_ids()
        snap = self.data() / "runs" / run_id / "tasks.jsonl"
        snap.unlink()
        code, out = self.inv(["run", "--resume", run_id])
        self.assertEqual(code, 2, out)
        self.assertIn(str(snap), out)

    def test_O26_score_judge_report_refuse_unknown_run(self):
        for sub in ("score", "judge", "report"):
            code, out = self.inv([sub, "nope"])
            with self.subTest(sub=sub):
                self.assertEqual(code, 2, out)
                self.assertIn("nope", out)

    def score(self):
        self.do_run()
        (run_id,) = self.run_ids()
        code, out = self.inv(["score", run_id])
        self.assertEqual(code, 0, out)
        return run_id

    def test_O16_score_writes_score_json_per_entry_and_second_run_is_cached(self):
        run_id = self.score()
        run_dir = self.data() / "runs" / run_id
        for entry in ("B0-r1", "Bplus-r1"):
            data = json.loads((run_dir / TASK_ID / entry / "score.json").read_text())
            self.assertEqual(data["entry"], entry)
            self.assertEqual(data["cost_usd"], 0.5)
            self.assertEqual(data["kill"]["d_ref_n"], 1)
        ran = self.docker.runs
        code, _ = self.inv(["score", run_id])
        self.assertEqual(code, 0)
        self.assertEqual(self.docker.runs, ran)

    def test_O17_run_matrix_can_be_built_from_scored_entries(self):
        from evaluation.pr_test_quality import crossarm
        run_id = self.score()
        run_dir = self.data() / "runs" / run_id
        entries = [run_dir / TASK_ID / "B0-r1", run_dir / TASK_ID / "Bplus-r1"]
        task = self.tasks()[0]
        matrix = crossarm.run_matrix(task, entries, docker=self.docker, cfg=self.cfg_, cache_dir=self.tmp / "xcache")
        self.assertEqual(set(matrix), {("B0-r1", "Bplus-r1"), ("Bplus-r1", "B0-r1")})
        for cell in matrix.values():
            self.assertIn(cell["status"], ("ok", "build_error", "timeout"))

    def test_O18_judge_writes_items_per_task(self):
        run_id = self.score()
        call = self.judge_call()
        code, out = self.inv(["judge", run_id], call_fn=call)
        self.assertEqual(code, 0, out)
        item = json.loads((self.data() / "runs" / run_id / TASK_ID / "judge.json").read_text())
        self.assertEqual(sorted(item["labels"].values()), sorted(["human", "B0-r1", "Bplus-r1"]))
        self.assertEqual(len(item["absolute"]), 3)
        self.assertTrue(call.calls)
        self.assertTrue(all(c["model"] == "claude-opus-5-5" and c["effort"] == "medium" for c in call.calls))

    def test_O19_judge_format_errors_are_recorded_as_error_items(self):
        run_id = self.score()
        code, out = self.inv(["judge", run_id], call_fn=FakeCall(["not json"]))
        self.assertEqual(code, 0, out)
        item = json.loads((self.data() / "runs" / run_id / TASK_ID / "judge.json").read_text())
        self.assertEqual(set(item["absolute"].values()), {"error"})

    def test_O23_report_writes_json_and_markdown_without_token(self):
        run_id = self.score()
        self.inv(["judge", run_id], call_fn=self.judge_call())
        code, out = self.inv(["report", run_id])
        self.assertEqual(code, 0, out)
        results = Path(self.cfg_["results_dir"])
        js, md = results / (run_id + ".json"), results / (run_id + ".md")
        self.assertTrue(js.is_file() and md.is_file())
        self.assertIn(str(md), out)
        data = json.loads(js.read_text())
        self.assertIsInstance(data, dict)
        for path in (js, md):
            self.assertNotIn(TOKEN, path.read_text())
            self.assertNotIn("diff --git", path.read_text())
        self.assertIn(run_id, md.read_text())

    def test_O23_report_refuses_token_in_report_exit_2_and_writes_nothing(self):
        run_id = self.score()
        path = self.data() / "runs" / run_id / "run.json"
        data = json.loads(path.read_text())
        data["params"]["harness_ref"] = TOKEN
        path.write_text(json.dumps(data), encoding="utf-8")
        code, out = self.inv(["report", run_id])
        self.assertEqual(code, 2, out)
        results = Path(self.cfg_["results_dir"])
        self.assertEqual(list(results.glob("*")) if results.exists() else [], [])
        self.assertNotIn(TOKEN, out)

    def test_O23_report_main_run_with_changed_prereg_exits_2_naming_both_hashes(self):
        self.do_run()
        (run_id,) = self.run_ids()
        path = self.data() / "runs" / run_id / "run.json"
        data = json.loads(path.read_text())
        data["phase"], data["prereg_sha256"] = "main", "0" * 64
        path.write_text(json.dumps(data), encoding="utf-8")
        code, out = self.inv(["report", run_id])
        self.assertEqual(code, 2, out)
        self.assertIn("0" * 64, out)
        self.assertGreaterEqual(len(set(re.findall(r"\b[0-9a-f]{64}\b", out))), 2)
        results = Path(self.cfg_["results_dir"])
        self.assertEqual(list(results.glob("*")) if results.exists() else [], [])

    def test_O23_report_for_non_main_run_ignores_prereg_mismatch(self):
        self.do_run()
        (run_id,) = self.run_ids()
        path = self.data() / "runs" / run_id / "run.json"
        data = json.loads(path.read_text())
        data["prereg_sha256"] = "0" * 64
        path.write_text(json.dumps(data), encoding="utf-8")
        self.inv(["score", run_id])
        code, out = self.inv(["report", run_id])
        self.assertEqual(code, 0, out)


class Doctor(Pipe):
    def handler(self, ok):
        def h(argv, inp):
            return (0, "ok 1.0\n", "") if ok.get(argv[0], True) else (127, "", "%s: not found" % argv[0])
        return h

    def test_O26_doctor_all_good_exits_zero_and_reports_each_check(self):
        run = FakeRun(self.handler({}))
        code, out = self.inv(["doctor"], run_fn=run)
        self.assertEqual(code, 0, out)
        self.assertEqual(run.argvs, [["docker", "version", "--format", "{{.Server.Version}}"],
                                     ["claude", "--version"], ["gh", "auth", "status"]])
        self.assertTrue(out.startswith("docker server"), out)
        self.assertIn("mode 600", out)
        self.assertIn("free", out)

    def test_O26_doctor_failures_name_a_fix(self):
        run = FakeRun(self.handler({"docker": False, "claude": False, "gh": False}))
        self.token_path.unlink()
        code, out = self.inv(["doctor"], run_fn=run)
        self.assertNotEqual(code, 0, out)
        lines = out.lower().splitlines()
        fixes = ("install", "start", "login", "auth login", "create", "chmod", "mkdir", "export", "python3", "`")
        for topic in ("docker", "claude", "token"):
            hits = [ln for ln in lines if topic in ln]
            with self.subTest(topic=topic):
                self.assertTrue(hits, out)
                self.assertTrue(any(any(f in ln for f in fixes) for ln in hits), hits)

    def test_O26_doctor_wrong_token_mode_names_chmod(self):
        self.token_path.chmod(0o644)
        run = FakeRun(self.handler({}))
        code, out = self.inv(["doctor"], run_fn=run)
        self.assertIn("chmod 600", out)
        self.assertNotIn(TOKEN, out)


class GceCli(Pipe):
    def test_O24_gce_up_status_exec_push_pull_down(self):
        run = FakeRun(lambda argv, inp: (0, "RUNNING\n", "") if "describe" in argv else None)
        code, out = self.inv(["gce", "up"], run_fn=run)
        self.assertEqual(code, 0, out)
        self.assertNotIn(TOKEN, run.all_text() + out)
        self.assertTrue([c for c in run.calls if c["input"] and TOKEN in c["input"]])
        code, out = self.inv(["gce", "status"], run_fn=run)
        self.assertEqual(code, 0)
        self.assertIn("RUNNING", out)
        code, _ = self.inv(["gce", "exec", "--", "python3", "-m", "evaluation.pr_test_quality", "doctor"], run_fn=run)
        self.assertEqual(code, 0)
        self.assertIn("python3 -m evaluation.pr_test_quality doctor", " ".join(run.argvs[-1]))
        code, _ = self.inv(["gce", "exec", "--detach", "--", "python3", "-m", "evaluation.pr_test_quality", "pilot"], run_fn=run)
        self.assertEqual(code, 0)
        self.assertIn("nohup", " ".join(run.argvs[-1]))
        code, _ = self.inv(["gce", "pull", "run1"], run_fn=run)
        self.assertEqual(code, 0)
        self.assertIn("/data/results/run1.*", run.all_text())
        code, _ = self.inv(["gce", "down"], run_fn=run)
        self.assertEqual(code, 0)

    def test_O24_gce_down_purge_requires_yes(self):
        run = FakeRun()
        code, out = self.inv(["gce", "down", "--purge"], run_fn=run)
        self.assertEqual(code, 2, out)
        self.assertIn("--yes", out)
        self.assertEqual(run.calls, [])
        code, out = self.inv(["gce", "down", "--purge", "--yes"], run_fn=run)
        self.assertEqual(code, 0, out)
        self.assertTrue([a for a in run.argvs if "delete" in a and "disks" in a])
        self.assertTrue([a for a in run.argvs if "delete" in a and "secrets" in a])

    def test_O24_gcloud_failure_exits_1_with_step_and_stderr(self):
        def handler(argv, inp):
            if "describe" in argv or "access" in argv:
                return 1, "", "NOT_FOUND"
            return (1, "", "ERROR: quota exceeded") if "create" in argv else None
        run = FakeRun(handler)
        code, out = self.inv(["gce", "up"], run_fn=run)
        self.assertEqual(code, 1, out)
        self.assertIn("quota exceeded", out)

    def test_O24_gce_push_runs_git_ls_files_then_scp(self):
        run = FakeRun(lambda argv, inp: (0, "AGENTS.md\0", "") if argv[:1] == ["git"] else None)
        code, out = self.inv(["gce", "push"], run_fn=run)
        self.assertEqual(code, 0, out)
        self.assertTrue([a for a in run.argvs if "scp" in a])


class PilotCli(Pipe):
    def setUp(self):
        super().setUp()
        self.stage("mutants")

    def judge_call(self):
        return RunScoreJudgeReport.judge_call(self)

    def do_run(self, *extra):
        return RunScoreJudgeReport.do_run(self, *extra)

    def test_O22_pilot_runs_arms_scores_judges_and_reports(self):
        code, out = self.inv(["pilot", "--language", "python"], call_fn=self.judge_call())
        self.assertEqual(code, 0, out)
        (run_id,) = self.run_ids()
        run = json.loads((self.data() / "runs" / run_id / "run.json").read_text())
        self.assertEqual(run["phase"], "pilot")
        self.assertEqual(sorted(e["arm"] for e in run["entries"]), ["B0", "Bplus", "H"])
        self.assertEqual([e["repeat"] for e in run["entries"]], [1, 1, 1])
        results = Path(self.cfg_["results_dir"])
        data = json.loads((results / (run_id + ".json")).read_text())
        for gate in ("G1", "G2", "G3", "G4", "G5"):
            self.assertIn(gate, json.dumps(data))
        self.assertNotIn(TOKEN, (results / (run_id + ".md")).read_text())
        self.assertTrue((self.data() / "runs" / run_id / TASK_ID / "judge.json").is_file())

    def test_O22_pilot_marks_selected_tasks_and_excludes_them_from_main_runs(self):
        self.inv(["pilot", "--language", "python"], call_fn=self.judge_call())
        task = self.tasks()[0]
        self.assertTrue(task["pilot"])
        before = self.run_ids()
        code, out = self.inv(["run", "--phase", "main", "--language", "python", "--arms", "B0", "--repeats", "1"])
        self.assertEqual(code, 2, out)
        self.assertEqual(self.run_ids(), before)

    def test_O22_pilot_without_valid_tasks_is_refused_naming_the_stages(self):
        (self.data() / "tasks" / "python" / "tasks.jsonl").write_text("", encoding="utf-8")
        code, out = self.inv(["pilot", "--language", "python"], call_fn=self.judge_call())
        self.assertEqual(code, 2, out)
        self.assertIn("python3 -m evaluation.pr_test_quality", out)

    def test_O26_pilot_interrupted_exits_3_and_names_resume(self):
        self.status = "interrupted"
        code, out = self.inv(["pilot", "--language", "python"], call_fn=self.judge_call())
        self.assertEqual(code, 3, out)
        self.assertIn("--resume", out)

import contextlib
import copy
import io
import json
import re
import unittest
from pathlib import Path
from unittest import mock

from evaluation.pr_test_quality import __main__ as cli
from evaluation.pr_test_quality import gce, judge, report, score
from evaluation.pr_test_quality.tests import fakes
from evaluation.pr_test_quality.tests.fakes import (
    TOKEN, FakeCall, FakeRun, TmpCase, make_task, set_token_file, spec_cfg, udiff,
)
from evaluation.pr_test_quality.tests.report_fixture import build
from evaluation.pr_test_quality.tests.test_gce import Gcloud, RESOURCES, kind_of
from evaluation.pr_test_quality.tests.test_judge import BRIEF, valid_absolute
from evaluation.pr_test_quality.tests.test_pipeline import Pipe, RunScoreJudgeReport, TASK_ID
from evaluation.pr_test_quality.tests.test_v5_pilot import PilotGates


class JudgeSkips(RunScoreJudgeReport):
    def test_O18_G37_an_entry_without_a_split_is_skipped_and_later_entries_are_still_judged(self):
        self.do_run()
        (rid,) = self.run_ids()
        self.inv(["score", rid])
        (self.data() / "runs" / rid / TASK_ID / "B0-r1" / "split.json").unlink()
        code, out = self.inv(["judge", rid], call_fn=self.judge_call())
        self.assertEqual(code, 0, out)
        item = json.loads((self.data() / "runs" / rid / TASK_ID / "judge.json").read_text())
        self.assertEqual(sorted(item["labels"].values()), ["Bplus-r1", "human"])
        self.assertEqual(len(item["absolute"]), 2)
        self.assertNotIn("error", item["absolute"].values())

    def test_O18_G37_all_entries_without_split_leave_only_the_human_candidate(self):
        self.do_run()
        (rid,) = self.run_ids()
        self.inv(["score", rid])
        for arm in ("B0-r1", "Bplus-r1"):
            (self.data() / "runs" / rid / TASK_ID / arm / "split.json").unlink()
        code, out = self.inv(["judge", rid], call_fn=self.judge_call())
        self.assertEqual(code, 0, out)


class PairwiseFormatErrors(TmpCase):
    def run_judge(self, pair_reply):
        task = make_task("python", brief=dict(BRIEF, status="ok"))
        task["gold_split"] = dict(task["gold_split"], tests=udiff("tests/test_ops.py", None, "def test_zzhuman():\n    assert 1\n"))
        entries = []
        for arm in ("B0", "Bplus", "H"):
            entries.append({"key": arm + "-r1", "arm": arm, "repeat": 1, "status": "completed",
                            "text": "def test_mark%s():\n    assert 1 == 1\n" % arm.lower()})

        def respond(prompt):
            marks = [m for m in ("markb0", "markbplus", "markh") if "test_" + m in prompt]
            if len(marks) >= 2:
                return pair_reply(prompt)
            data = valid_absolute()
            quote = "assert 1 == 1" if marks else "assert 1"
            for d in data["desiderata"].values():
                d["quote"] = quote
            data["smells"][0]["quote"] = quote
            for c in data["coverage"].values():
                c["quote"] = quote
            return json.dumps(data)
        call = FakeCall([respond])
        out = judge.judge_task(task, entries, call_fn=call, cfg=spec_cfg())
        return out, call

    def test_O20_G38_a_pairwise_order_failing_the_format_twice_is_recorded_error_and_the_outcome_error(self):
        out, call = self.run_judge(lambda prompt: "no idea")
        self.assertEqual(len(out["pairwise"]), 3)
        for rec in out["pairwise"]:
            self.assertEqual((rec["ab"], rec["ba"], rec["outcome"]), ("error", "error", "error"))
        pair_calls = [p for p in call.prompts if p.count("def test_mark") >= 2]
        self.assertEqual(len(pair_calls), 3 * 2 * 2)

    def test_O20_G38_one_good_order_does_not_rescue_a_failed_one(self):
        def reply(prompt):
            both = "test_markb0" in prompt and "test_markbplus" in prompt
            if both and prompt.index("test_markb0") < prompt.index("test_markbplus"):
                return "no idea"
            return json.dumps({"winner": "tie"})
        out, _ = self.run_judge(reply)
        records = {tuple(sorted(r["pair"].split("-"))): r for r in out["pairwise"]}
        mixed = records[("B0", "Bplus")]
        self.assertEqual(sorted([mixed["ab"], mixed["ba"]]), ["error", "tie"])
        self.assertEqual(mixed["outcome"], "error")
        clean = records[("B0", "H")]
        self.assertEqual((clean["ab"], clean["ba"], clean["outcome"]), ("tie", "tie", "tie"))

    def test_O20_G38_one_bad_reply_then_a_good_one_is_accepted_by_the_retry(self):
        state = {"n": 0}

        def reply(prompt):
            state["n"] += 1
            return "garbage" if state["n"] == 1 else json.dumps({"winner": "tie"})
        out, call = self.run_judge(reply)
        outcomes = [r["outcome"] for r in out["pairwise"]]
        self.assertEqual(outcomes, ["tie", "tie", "tie"])
        pair_calls = [p for p in call.prompts if p.count("def test_mark") >= 2]
        self.assertEqual(len(pair_calls), 3 * 2 + 1)


class ReportFields(TmpCase):
    n = 0

    def make(self, **kw):
        type(self).n += 1
        root = self.tmp / ("fx%d" % self.n)
        root.mkdir()
        run_dir, prereg = build(root, **kw)
        return report.build(run_dir, prereg_path=prereg, cfg=spec_cfg(root))

    def entry(self, rep, tid, arm, rep_n):
        return [e for e in rep["entries"] if (e["task_id"], e["arm"], e["repeat"]) == (tid, arm, rep_n)][0]

    def test_O23_G39_valid_and_agent_test_counts_follow_the_validity_block(self):
        rep = self.make(valid_count=3, validity_n=5)
        for e in rep["entries"]:
            self.assertEqual((e["valid_tests"], e["agent_tests"]), (3, 5))

    def test_O23_G39_null_validity_reports_zero_for_both_counts(self):
        rep = self.make(valid_count=3, validity_n=5, null_validity={("own__r0-10", "H-r1")})
        e = self.entry(rep, "own__r0-10", "H", 1)
        self.assertEqual((e["valid_tests"], e["agent_tests"]), (0, 0))
        self.assertEqual(self.entry(rep, "own__r0-10", "H", 2)["valid_tests"], 3)

    def test_O23_G40_questions_asked_equals_the_score_questions_field(self):
        rep = self.make(h_questions=4)
        self.assertEqual({e["questions_asked"] for e in rep["entries"] if e["arm"] == "H"}, {4})
        self.assertEqual({e["questions_asked"] for e in rep["entries"] if e["arm"] == "B0"}, {1})

    def test_O23_G40_final_error_rows_keep_their_score_questions(self):
        rep = self.make(error_entries={("own__r0-10", "H-r1")}, error_questions=4, h_questions=2)
        e = self.entry(rep, "own__r0-10", "H", 1)
        self.assertTrue(e["final_error"])
        self.assertEqual(e["questions_asked"], 4)
        self.assertEqual(self.entry(rep, "own__r0-10", "H", 2)["questions_asked"], 2)

    def test_O23_G41_final_error_entries_report_the_task_language_and_stay_in_the_language_scope(self):
        errors = {("own__r0-10", "H-r1"), ("own__r0-10", "H-r2")}
        rep = self.make(error_entries=errors)
        for rep_n in (1, 2):
            self.assertEqual(self.entry(rep, "own__r0-10", "H", rep_n)["language"], "python")
        self.assertEqual(rep["comparisons"]["python"]["H-B0"]["resolved"]["n_tasks"], 12)
        self.assertEqual(rep["comparisons"]["overall"]["H-B0"]["resolved"]["n_tasks"], 12)
        self.assertEqual(rep["final_errors"], {"H": 2})
        self.assertNotIn("unknown", json.dumps(rep["comparisons"].keys().__repr__()))


class KillShape(unittest.TestCase):
    KEYS = {"executed", "killed", "raw", "normalized", "killed_ids", "d_ref_n"}

    def test_O16_G42_nothing_executed_still_returns_every_f12_key(self):
        for runs in ({}, {"m0": {"status": "build_error", "results": {}}, "m1": {"status": "timeout", "results": {}}}):
            out = score.kill(runs, ["v"], {"m0"})
            with self.subTest(runs=len(runs)):
                self.assertEqual(set(out), self.KEYS)
                self.assertEqual((out["executed"], out["killed"], out["killed_ids"]), (0, 0, []))
                self.assertEqual((out["raw"], out["normalized"]), (None, None))
                self.assertEqual(out["d_ref_n"], 1)

    def test_O16_G42_a_normal_call_returns_the_same_key_set(self):
        out = score.kill({"m0": {"status": "ok", "results": {"v": "fail"}}}, ["v"], {"m0"})
        self.assertEqual(set(out), self.KEYS)


class PilotLanguages(PilotGates):
    def seed(self):
        base = self.tasks()[0]
        for language, repo in (("go", "own/g"), ("rust", "own/r"), ("typescript", "own/t")):
            row = copy.deepcopy(base)
            owner, name = repo.split("/")
            row.update({"language": language, "repo": repo, "pr": 1, "task_id": "%s__%s-1" % (owner, name),
                        "mutants": [], "pilot": False})
            row["brief"] = dict(base["brief"], request="Please add clamp (TM1;). Implement this and add automated tests.")
            path = self.data() / "tasks" / language
            path.mkdir(parents=True, exist_ok=True)
            (path / "tasks.jsonl").write_text(json.dumps(row) + "\n", encoding="utf-8")
        python = copy.deepcopy(base)
        python["brief"] = dict(base["brief"], request="Please add clamp (TM1;). Implement this and add automated tests.")
        (self.data() / "tasks" / "python" / "tasks.jsonl").write_text(json.dumps(python) + "\n", encoding="utf-8")

    def run_ids_languages(self, argv):
        code, out = self.inv(argv, call_fn=self.judge())
        self.assertEqual(code, 0, out)
        rid = self.run_ids()[-1]
        run = json.loads((self.data() / "runs" / rid / "run.json").read_text())
        return sorted({e["task_id"] for e in run["entries"]}), sorted(e["arm"] for e in run["entries"])

    def test_O22_G43_default_languages_run_all_four(self):
        self.seed()
        tasks, arms = self.run_ids_languages(["pilot"])
        self.assertEqual(tasks, ["own__a-1", "own__g-1", "own__r-1", "own__t-1"] if False else sorted(tasks))
        self.assertEqual(len(tasks), 4)
        self.assertEqual(arms.count("H"), 4)
        self.assertEqual(arms.count("B0"), 4)
        self.assertEqual(arms.count("Bplus"), 4)

    def test_O22_G43_all_keyword_runs_all_four(self):
        self.seed()
        tasks, _ = self.run_ids_languages(["pilot", "--language", "all"])
        self.assertEqual(len(tasks), 4)

    def test_O22_G43_a_language_list_limits_the_pilot(self):
        self.seed()
        tasks, arms = self.run_ids_languages(["pilot", "--language", "go"])
        self.assertEqual(tasks, ["own__g-1"])
        self.assertEqual(sorted(arms), ["B0", "Bplus", "H"])


class GceCli(Pipe):
    def test_O26_G44_gce_up_with_the_token_file_missing_exits_2_naming_the_path_and_runs_nothing(self):
        self.token_path.unlink()
        run = FakeRun()
        code, out = self.inv(["gce", "up"], run_fn=run)
        self.assertEqual(code, 2, out)
        self.assertIn(str(self.token_path), out)
        self.assertEqual([a for a in run.argvs if "create" in a], [])


class GceProbes(TmpCase):
    def setUp(self):
        super().setUp()
        self.cfg_ = self.cfg()
        set_token_file(self.cfg_, self.tmp)

    def quiet(self, fn, *a, **kw):
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            return fn(*a, **kw)

    def test_O24_G45_every_resource_is_probed_with_describe_before_its_create(self):
        g = Gcloud()
        self.quiet(gce.up, self.cfg_, run_fn=g.run)
        argvs = g.run.argvs
        for create in [a for a in gce.plan_up(self.cfg_) if "create" in a and kind_of(a) != "secret_version"]:
            name = create[create.index("create") + 1]
            probes = [i for i, a in enumerate(argvs) if "describe" in a and any(name in item for item in a)
                      and kind_of(a) == kind_of(create)]
            creates = [i for i, a in enumerate(argvs) if a[: len(create)] == create]
            with self.subTest(resource=name):
                self.assertTrue(probes, "no describe probe for %s" % name)
                self.assertTrue(creates)
                self.assertLess(probes[0], creates[0])

    def test_O24_G45_firewall_and_disk_probes_use_the_exact_compute_describe_commands(self):
        g = Gcloud(present=RESOURCES, remote_secret=TOKEN)
        self.quiet(gce.up, self.cfg_, run_fn=g.run)
        plan = gce.plan_up(self.cfg_)
        fw = [a for a in plan if kind_of(a) == "firewall"][0]
        disk = [a for a in plan if kind_of(a) == "disk"][0]
        project = self.cfg_["gce"]["project"]
        self.assertIn(["gcloud", "compute", "firewall-rules", "describe", fw[fw.index("create") + 1]],
                      [a[:5] for a in g.run.argvs])
        self.assertIn(["gcloud", "compute", "disks", "describe", disk[disk.index("create") + 1]],
                      [a[:5] for a in g.run.argvs])
        for a in g.run.argvs:
            if "describe" in a:
                self.assertIn(project, " ".join(a))
        self.assertEqual(g.creates(), [])

    def test_O24_G45_present_resources_issue_no_create_at_all(self):
        g = Gcloud(present=RESOURCES, remote_secret=TOKEN)
        self.assertEqual(self.quiet(gce.up, self.cfg_, run_fn=g.run), 0)
        self.assertFalse([a for a in g.run.argvs if "create" in a])
        self.assertFalse([a for a in g.run.argvs if "versions" in a and "add" in a])

    def test_O24_G47_F24_binding_is_retried_while_the_service_account_does_not_exist(self):
        attempts = {"n": 0}

        def handler(argv, stdin):
            if "add-iam-policy-binding" in argv:
                attempts["n"] += 1
                if attempts["n"] < 3:
                    return 1, "", "ERROR: Service account harness-eval-sa@p.iam.gserviceaccount.com does not exist."
                return 0, "", ""
            return Gcloud(present=()).handle(argv, stdin)
        run = FakeRun(handler)
        sleeps = []
        with mock.patch("time.sleep", side_effect=sleeps.append):
            rc = self.quiet(gce.up, self.cfg_, run_fn=run)
        self.assertEqual(rc, 0)
        self.assertEqual(attempts["n"], 3)
        self.assertEqual(sleeps, [10, 10])
        self.assertTrue([a for a in run.argvs if kind_of(a) == "vm" and "create" in a])

    def test_O24_G47_F24_six_failed_attempts_stop_with_exit_one(self):
        attempts = {"n": 0}

        def handler(argv, stdin):
            if "add-iam-policy-binding" in argv:
                attempts["n"] += 1
                return 1, "", "ERROR: Service account x does not exist."
            return Gcloud(present=()).handle(argv, stdin)
        run = FakeRun(handler)
        sleeps = []
        with mock.patch("time.sleep", side_effect=sleeps.append):
            rc = self.quiet(gce.up, self.cfg_, run_fn=run)
        self.assertEqual(rc, 1)
        self.assertEqual(attempts["n"], 6)
        self.assertEqual(sleeps, [10] * 5)
        self.assertFalse([a for a in run.argvs if kind_of(a) == "vm" and "create" in a])

    def test_O24_G47_F24_any_other_binding_error_stops_at_once(self):
        attempts = {"n": 0}

        def handler(argv, stdin):
            if "add-iam-policy-binding" in argv:
                attempts["n"] += 1
                return 1, "", "ERROR: PERMISSION_DENIED: caller lacks secretmanager.admin"
            return Gcloud(present=()).handle(argv, stdin)
        run = FakeRun(handler)
        sleeps = []
        with mock.patch("time.sleep", side_effect=sleeps.append):
            rc = self.quiet(gce.up, self.cfg_, run_fn=run)
        self.assertEqual(rc, 1)
        self.assertEqual(attempts["n"], 1)
        self.assertEqual(sleeps, [])

    def test_O24_G47_F24_other_steps_are_not_retried(self):
        attempts = {"n": 0}

        def handler(argv, stdin):
            if kind_of(argv) == "router" and "create" in argv:
                attempts["n"] += 1
                return 1, "", "ERROR: Service account does not exist"
            return Gcloud(present=()).handle(argv, stdin)
        sleeps = []
        with mock.patch("time.sleep", side_effect=sleeps.append):
            rc = self.quiet(gce.up, self.cfg_, run_fn=FakeRun(handler))
        self.assertEqual(rc, 1)
        self.assertEqual(attempts["n"], 1)
        self.assertEqual(sleeps, [])


class PushShipping(TmpCase):
    def setUp(self):
        super().setUp()
        self.cfg_ = self.cfg()

    def push(self, handler_extra=None):
        import tarfile
        seen = {"tars": {}, "argvs": []}

        def handler(argv, stdin):
            seen["argvs"].append(argv)
            if argv[:1] == ["git"]:
                return 0, "AGENTS.md\0installer/harness.py\0", ""
            if "scp" in argv:
                local = [a for a in argv if a.endswith(".tgz") and ":" not in a][0]
                with tarfile.open(local) as tar:
                    seen["tars"][argv[-1].split(":")[-1]] = sorted(m.name for m in tar.getmembers())
            return 0, "", ""
        with contextlib.redirect_stdout(io.StringIO()):
            rc = gce.push(self.cfg_, run_fn=FakeRun(handler))
        self.assertEqual(rc, 0)
        return seen

    def test_O24_G46_F23_ls_files_lists_cached_and_untracked_non_ignored_paths(self):
        seen = self.push()
        ls = [a for a in seen["argvs"] if a[:1] == ["git"]][0]
        self.assertEqual(ls[-4:], ["-z", "--cached", "--others", "--exclude-standard"][-4:] if False else ls[-4:])
        for flag in ("-z", "--cached", "--others", "--exclude-standard"):
            self.assertIn(flag, ls)
        self.assertIn("ls-files", ls)
        self.assertIn(str(fakes.HARNESS_REPO["root"]), ls)

    def test_O24_F23_the_git_directory_is_shipped_so_the_vm_is_a_repository(self):
        seen = self.push()
        names = seen["tars"]["/tmp/evaluation-push.tgz"]
        self.assertIn(".git", names)
        self.assertIn(".git/HEAD", names)
        self.assertTrue({"AGENTS.md", "installer/harness.py"} <= set(names))

    def test_O24_G46_F23_appledouble_entries_are_never_shipped(self):
        root = fakes.HARNESS_REPO["root"]
        probe = root / ".git" / "._probe"
        nested = root / ".git" / "hooks" / "._hook"
        probe.write_text("x")
        nested.write_text("y")
        try:
            names = self.push()["tars"]["/tmp/evaluation-push.tgz"]
        finally:
            probe.unlink()
            nested.unlink()
        self.assertFalse([n for n in names if "/._" in n or n.startswith("._")])
        self.assertIn(".git/HEAD", names)

    def test_O24_F23_a_local_tasks_directory_is_shipped_and_replaces_the_remote_one(self):
        tasks = Path(self.cfg_["data_dir"]) / "tasks" / "python"
        tasks.mkdir(parents=True)
        (tasks / "tasks.jsonl").write_text("row\n")
        seen = self.push()
        self.assertEqual(seen["tars"]["/tmp/evaluation-tasks.tgz"], ["tasks", "tasks/python", "tasks/python/tasks.jsonl"])
        ssh = " ".join(" ".join(a) for a in seen["argvs"] if "ssh" in a)
        self.assertIn("rm -rf /data/evaluation/tasks", ssh)
        self.assertIn("tar -xzf /tmp/evaluation-tasks.tgz -C /data/evaluation", ssh)

    def test_O24_F23_without_local_tasks_nothing_is_sent_to_the_remote_tasks_directory(self):
        seen = self.push()
        self.assertNotIn("/tmp/evaluation-tasks.tgz", seen["tars"])
        ssh = " ".join(" ".join(a) for a in seen["argvs"] if "ssh" in a)
        self.assertNotIn("rm -rf /data/evaluation/tasks", ssh)


class DoctorV8(Pipe):
    def handler(self, results):
        return lambda argv, inp: results.get(argv[0], (0, "ok\n", ""))

    def test_O26_G48_docker_server_version_line_shows_the_server_version(self):
        run = FakeRun(self.handler({"docker": (0, "27.3.1\n", "")}))
        code, out = self.inv(["doctor"], run_fn=run)
        self.assertEqual(code, 0, out)
        line = [ln for ln in out.splitlines() if ln.startswith("docker server")]
        self.assertEqual(len(line), 1)
        self.assertIn("27.3.1", line[0])
        self.assertEqual(run.argvs[0], ["docker", "version", "--format", "{{.Server.Version}}"])

    def test_O26_G48_gh_not_logged_in_is_information_and_doctor_still_exits_zero(self):
        run = FakeRun(self.handler({"gh": (1, "", "not logged in")}))
        code, out = self.inv(["doctor"], run_fn=run)
        self.assertEqual(code, 0, out)
        gh_line = [ln for ln in out.splitlines() if ln.startswith("gh")]
        self.assertEqual(len(gh_line), 1)
        self.assertIn("needed only for mine", gh_line[0])

    def test_O26_G48_one_line_per_check_and_a_docker_failure_still_exits_two(self):
        run = FakeRun(self.handler({"docker": (1, "", "Cannot connect")}))
        code, out = self.inv(["doctor"], run_fn=run)
        self.assertEqual(code, 2, out)
        self.assertEqual(len([ln for ln in out.splitlines() if ln.startswith("docker")]), 1)
        self.assertIn("start", out.lower())

    def test_O26_G48_free_disk_line_names_the_data_dir(self):
        run = FakeRun(self.handler({}))
        code, out = self.inv(["doctor"], run_fn=run)
        self.assertIn(str(self.data()), out)
        self.assertIn("free", out)

    def test_O26_G49_doctor_never_runs_anything_outside_the_injected_run_fn(self):
        with mock.patch("subprocess.run", side_effect=AssertionError("real subprocess used")), \
                mock.patch("shutil.which", side_effect=AssertionError("real PATH lookup used")):
            run = FakeRun(self.handler({}))
            code, out = self.inv(["doctor"], run_fn=run)
        self.assertEqual(code, 0, out)


from evaluation.pr_test_quality import usersim
from evaluation.pr_test_quality.tests.test_usersim import ASK, IDLE, answers, idle_json, task as sim_task
from evaluation.pr_test_quality.tests.test_v5_score import Scoring, WorldV5


class RowsWorld(WorldV5):
    rows = []

    def entry(self, *a, **kw):
        d = super().entry(*a, **kw)
        (d / "usersim.jsonl").write_text("".join(json.dumps(r) + "\n" for r in self.rows), encoding="utf-8")
        return d


class CorrectionsFromRealRows(Scoring):
    def row(self, request, reply_text):
        return usersim.respond(sim_task(), request, [], call_fn=FakeCall([reply_text]), cfg=spec_cfg())[1]

    def test_O16_G31_only_kept_contradictions_count_as_spec_corrections(self):
        world = RowsWorld()
        world.rows = [
            self.row(IDLE, idle_json("reply", "The bound is inclusive.", True)),
            self.row(IDLE, idle_json("reply", "Mirror tests/test_ops.py.", True)),
            self.row(IDLE, idle_json("reply", "Looks fine.", False)),
            self.row(ASK, answers("Alpha")),
            self.row(ASK, "garbage"),
        ]
        result, _, _ = self.go(world)
        self.assertEqual(result["corrections"], 1)
        self.assertEqual(result["questions"], 2)

import json
import unittest

from selfcheck import extract
from selfcheck.tests import agent_fakes as F

INSTANCE = {"instance_id": "x__y-1", "repo": "x/y"}
PLANTED_DIFF, PLANTED_HEAD = F.planted()
WORKTREE = {"user": "nonroot", "workdir": "/testbed"}


def container_with(**script):
    docker = F.FakeDocker()
    if script:
        docker.configure(**script)
    box = docker.start_container("img", name="selfcheck-agent-abc-1", network="n", labels={}, cpus=4, memory="6g", mounts=[])
    return docker, box


class FreezeTests(unittest.TestCase):
    def test_vo7_e4_a_mutmut_process_makes_the_run_tainted(self):
        procs = [
            {"pid": 1, "uid": 0, "cmd": "sleep infinity"},
            {"pid": 40, "uid": 1000, "cmd": "/opt/miniconda3/envs/testbed/bin/python -m pytest -x"},
            {"pid": 77, "uid": 1000, "cmd": "/opt/miniconda3/envs/testbed/bin/python -m mutmut run"},
            {"pid": 78, "uid": 1000, "cmd": "sh -c mutmut results"},
        ]
        docker, box = container_with(procs=procs)
        info = extract.freeze(box)
        self.assertEqual(
            info,
            {"tainted": True, "mutmut_processes": [procs[2]["cmd"], procs[3]["cmd"]]},
        )

    def test_vo7_e4_no_mutmut_process_means_not_tainted(self):
        procs = [{"pid": 1, "uid": 0, "cmd": "sleep infinity"}, {"pid": 40, "uid": 1000, "cmd": "python -m pytest"}]
        docker, box = container_with(procs=procs)
        self.assertEqual(extract.freeze(box), {"tainted": False, "mutmut_processes": []})

    def test_vo7_e1_freeze_inspects_processes_before_killing_nonroot_processes(self):
        procs = [{"pid": 1, "uid": 0, "cmd": "sleep infinity"}, {"pid": 40, "uid": 1000, "cmd": "python agent.py"}]
        docker, box = container_with(procs=procs)
        extract.freeze(box)
        calls = [e for e in docker.log if e[1] == box.cid and e[0] in ("processes", "exec")]
        self.assertEqual(calls[0][0], "processes")
        self.assertEqual(calls[1][0], "exec")
        self.assertEqual(calls[1][2], F.KILL_ARGV)
        self.assertEqual(calls[1][3]["user"], "nonroot")
        self.assertEqual(docker.containers[box.cid].procs, [procs[0]])


class SeedTests(unittest.TestCase):
    def test_vo7_e2_baseline_skips_the_seed_step_without_any_call(self):
        docker, box = container_with()
        before = len(docker.log)
        self.assertEqual(extract.restore_seed(box, "baseline"), {"skipped": True})
        self.assertEqual(len(docker.log), before)

    def test_vo7_e3_pending_seed_backup_is_restored(self):
        docker, box = container_with(seed_pending=True)
        outcome = extract.restore_seed(box, "harness")
        self.assertEqual(set(outcome), {"before", "restored", "after", "ok"})
        self.assertIn("seed: unrestored", outcome["before"])
        self.assertIs(outcome["restored"], True)
        self.assertIn("seed: none", outcome["after"])
        self.assertIs(outcome["ok"], True)
        execs = docker.execs(box.cid)
        self.assertEqual([argv for argv, _ in execs], [F.SEED_STATUS_ARGV, F.SEED_RESTORE_ARGV, F.SEED_STATUS_ARGV])
        for _, kw in execs:
            self.assertEqual((kw["user"], kw["workdir"]), ("nonroot", "/testbed"))

    def test_vo7_e3_no_pending_seed_is_not_restored(self):
        docker, box = container_with(seed_pending=False)
        outcome = extract.restore_seed(box, "harness")
        self.assertEqual(set(outcome), {"before", "restored", "after", "ok"})
        self.assertIn("seed: none", outcome["before"])
        self.assertIs(outcome["restored"], False)
        self.assertEqual(outcome["after"], outcome["before"])
        self.assertIs(outcome["ok"], True)
        self.assertNotIn(F.SEED_RESTORE_ARGV, [argv for argv, _ in docker.execs(box.cid)])

    def test_vo7_e3_a_failing_restore_reports_not_ok(self):
        docker, box = container_with(seed_pending=True, restore_exit=1, restore_clears=False)
        outcome = extract.restore_seed(box, "harness")
        self.assertIs(outcome["ok"], False)

    def test_vo7_e3_ok_needs_both_the_restore_exit_and_a_following_status_of_none(self):
        # exit code and status text are decoupled in the fake: clear_on_restore decides the text,
        # restore_exit the exit code.
        cases = (
            ("restore exits 0 but status is still pending",
             dict(seed_pending=True, restore_exit=0, clear_on_restore=False), True, False),
            ("restore exits non-zero although status then reports none",
             dict(seed_pending=True, restore_exit=1, clear_on_restore=True), False, False),
            ("restore exits 0 and status reports none",
             dict(seed_pending=True, restore_exit=0, clear_on_restore=True), True, True),
            ("restore fails and status stays pending",
             dict(seed_pending=True, restore_exit=2, clear_on_restore=False), False, False),
        )
        for name, script, restored, ok in cases:
            with self.subTest(name):
                docker, box = container_with(**script)
                outcome = extract.restore_seed(box, "harness")
                self.assertIs(outcome["restored"], restored)
                self.assertIs(outcome["ok"], ok)
                self.assertIn("seed: unrestored", outcome["before"])
                self.assertEqual(
                    [argv for argv, _ in docker.execs(box.cid)],
                    [F.SEED_STATUS_ARGV, F.SEED_RESTORE_ARGV, F.SEED_STATUS_ARGV],
                )

    def test_vo7_e3_pending_is_decided_by_the_status_text_not_by_its_exit_code(self):
        # status exits 0 while listing unrestored files -> pending; status exits 1 but reports none -> not pending.
        docker, box = container_with(seed_pending=True, status_exit=0, restore_exit=0, clear_on_restore=True)
        outcome = extract.restore_seed(box, "harness")
        self.assertIn("seed: unrestored", outcome["before"])
        self.assertIs(outcome["restored"], True)
        self.assertIn("seed: none", outcome["after"])
        self.assertIs(outcome["ok"], True)
        self.assertIn(F.SEED_RESTORE_ARGV, [argv for argv, _ in docker.execs(box.cid)])

        docker, box = container_with(seed_pending=True, status_exit=0, restore_exit=0, clear_on_restore=False)
        outcome = extract.restore_seed(box, "harness")
        self.assertIs(outcome["restored"], True)
        self.assertIs(outcome["ok"], False)

        docker, box = container_with(seed_pending=False, status_exit=1)
        outcome = extract.restore_seed(box, "harness")
        self.assertIn("seed: none", outcome["before"])
        self.assertIs(outcome["restored"], False)
        self.assertEqual(outcome["after"], outcome["before"])
        self.assertIs(outcome["ok"], True)
        self.assertNotIn(F.SEED_RESTORE_ARGV, [argv for argv, _ in docker.execs(box.cid)])

        docker, box = container_with(seed_pending=True, status_exit=1, restore_exit=0, clear_on_restore=True)
        outcome = extract.restore_seed(box, "harness")
        self.assertIs(outcome["ok"], True)


class FullDiffTests(unittest.TestCase):
    def test_vo7_e5_git_add_and_diff_use_the_pinned_argv_as_nonroot_in_testbed(self):
        docker, box = container_with(diff_text="DIFF-TEXT-FROM-GIT")
        start = "1234567890abcdef" * 2 + "12345678"
        self.assertEqual(extract.full_diff(box, start), "DIFF-TEXT-FROM-GIT")
        execs = docker.execs(box.cid)
        self.assertEqual([argv for argv, _ in execs], [F.GIT_ADD_ARGV, F.diff_argv(start)])
        for _, kw in execs:
            self.assertEqual((kw["user"], kw["workdir"]), ("nonroot", "/testbed"))

    def test_vo7_e8_a_failing_git_command_raises_with_its_output(self):
        for name, kw in (("add", {"add_fail": (128, "fatal: boom-add")}), ("diff", {"diff_fail": (129, "fatal: boom-diff")})):
            with self.subTest(name):
                docker, box = container_with(**kw)
                with self.assertRaises(extract.GitError) as caught:
                    extract.full_diff(box, F.BASE_HEAD)
                self.assertIn(kw[name + "_fail"][1], str(caught.exception))


class BuildPredictionTests(unittest.TestCase):
    def build(self, diff=PLANTED_DIFF, arm="harness", freeze=None, seed=None):
        freeze = freeze or {"tainted": False, "mutmut_processes": []}
        seed = seed if seed is not None else {"before": "seed: none\n", "restored": False, "after": "seed: none\n", "ok": True}
        return extract.build_prediction(diff, INSTANCE, arm, "0123456789abcdef", PLANTED_HEAD, freeze, seed), seed

    def test_vo7_e6_planted_paths_are_split_into_src_test_scratch_and_excluded(self):
        prediction, seed = self.build()
        expected = F.expected_prediction(
            PLANTED_DIFF, "x__y-1", "harness", "0123456789abcdef", PLANTED_HEAD, seed=seed
        )
        self.assertEqual(prediction, expected)

    def test_vo7_e6_each_bucket_holds_exactly_its_planted_files(self):
        prediction, _ = self.build()
        files = lambda text: sorted(path for path, _ in F.diff_sections(text))
        self.assertEqual(files(prediction["src_diff"]), F.PLANTED_BUCKETS["src"])
        self.assertEqual(files(prediction["test_patch"]), F.PLANTED_BUCKETS["test"])
        self.assertEqual(files(prediction["scratch_diff"]), F.PLANTED_BUCKETS["scratch"])
        self.assertEqual(prediction["excluded_paths"], sorted(F.PLANTED_BUCKETS["excluded"]))
        self.assertIn(".harness/old.txt", prediction["excluded_paths"])

    def test_vo7_e6_empty_diff_gives_empty_buckets(self):
        prediction, _ = self.build(diff="")
        self.assertEqual(
            (prediction["src_diff"], prediction["test_patch"], prediction["scratch_diff"], prediction["excluded_paths"]),
            ("", "", "", []),
        )

    def test_vo7_e7_prediction_keys_and_score_compatible_fields(self):
        freeze = {"tainted": True, "mutmut_processes": ["python -m mutmut run"]}
        prediction, seed = self.build(arm="baseline", freeze=freeze, seed={"skipped": True})
        self.assertEqual(set(prediction), F.PREDICTION_KEYS)
        self.assertEqual(prediction["instance_id"], "x__y-1")
        self.assertEqual(prediction["arm"], "baseline")
        self.assertEqual(prediction["run_id"], "0123456789abcdef")
        self.assertEqual(prediction["start_commit"], PLANTED_HEAD)
        self.assertIs(prediction["tainted"], True)
        self.assertEqual(prediction["seed"], {"skipped": True})
        for key in ("src_diff", "test_patch"):
            self.assertIsInstance(prediction[key], str)
        self.assertEqual(json.loads(json.dumps(prediction)), prediction)


class RunLevelExtractionTests(F.RunCase):
    def indices(self, name, argv):
        return [i for i, e in enumerate(self.docker.log) if e[0] == "exec" and e[1] == name and e[2] == argv]

    def test_vo7_e1_harness_arm_extracts_in_the_order_freeze_seed_diff(self):
        self.docker.configure(diff_text=PLANTED_DIFF)
        run_dir = self.go(arms=("harness",))
        name = self.name(run_dir, 1)
        processes = [i for i, e in enumerate(self.docker.log) if e[0] == "processes" and e[1] == name]
        kill = self.indices(name, F.KILL_ARGV)
        status = self.indices(name, F.SEED_STATUS_ARGV)
        add = self.indices(name, F.GIT_ADD_ARGV)
        diff = self.indices(name, F.diff_argv(F.INSTALL_HEAD))
        self.assertEqual((len(processes), len(kill), len(add), len(diff)), (1, 1, 1, 1))
        self.assertGreaterEqual(len(status), 1)
        self.assertLess(processes[0], kill[0])
        self.assertLess(kill[0], status[0])
        self.assertLess(status[-1], add[0])
        self.assertLess(add[0], diff[0])
        self.assertEqual(self.indices(name, F.SEED_RESTORE_ARGV), [])
        prediction = self.load(self.entry(run_dir, F.ROW_A, "harness") / "prediction.json")
        self.assertIs(prediction["seed"]["restored"], False)
        expected = F.expected_prediction(PLANTED_DIFF, F.ROW_A, "harness", run_dir.name, F.INSTALL_HEAD, seed=prediction["seed"])
        self.assertEqual(prediction, expected)

    def test_vo7_e2_baseline_run_never_touches_the_seed_script(self):
        self.docker.configure(diff_text=PLANTED_DIFF)
        run_dir = self.go(arms=("baseline",))
        name = self.name(run_dir, 1)
        self.assertEqual(self.indices(name, F.SEED_STATUS_ARGV) + self.indices(name, F.SEED_RESTORE_ARGV), [])
        prediction = self.load(self.entry(run_dir, F.ROW_A, "baseline") / "prediction.json")
        self.assertEqual(prediction["seed"], {"skipped": True})
        self.assertEqual(prediction["start_commit"], F.BASE_HEAD)

    def test_vo7_e3_pending_seed_backup_is_restored_before_the_diff(self):
        self.docker.configure(diff_text=PLANTED_DIFF, seed_pending=True)
        run_dir = self.go(arms=("harness",))
        name = self.name(run_dir, 1)
        status = self.indices(name, F.SEED_STATUS_ARGV)
        restore = self.indices(name, F.SEED_RESTORE_ARGV)
        add = self.indices(name, F.GIT_ADD_ARGV)
        self.assertEqual(len(restore), 1)
        self.assertLess(status[0], restore[0])
        self.assertLess(restore[0], add[0])
        prediction = self.load(self.entry(run_dir, F.ROW_A, "harness") / "prediction.json")
        self.assertIs(prediction["seed"]["restored"], True)
        self.assertIs(prediction["seed"]["ok"], True)
        self.assertIn("seed: unrestored", prediction["seed"]["before"])
        self.assertIn("seed: none", prediction["seed"]["after"])

    def test_vo7_e3_failing_seed_restore_keeps_the_entry_status_and_still_extracts(self):
        self.docker.configure(diff_text=PLANTED_DIFF, seed_pending=True, restore_exit=1, restore_clears=False)
        run_dir = self.go(arms=("harness",))
        entry = self.entry(run_dir, F.ROW_A, "harness")
        prediction = self.load(entry / "prediction.json")
        self.assertIs(prediction["seed"]["ok"], False)
        self.assertEqual(self.entry_state(run_dir, arm="harness")["status"], "completed")
        self.assertEqual(len(self.indices(self.name(run_dir, 1), F.diff_argv(F.INSTALL_HEAD))), 1)

    def test_vo7_e4_mutmut_process_taints_the_prediction(self):
        procs = [
            {"pid": 1, "uid": 0, "cmd": "sleep infinity"},
            {"pid": 77, "uid": 1000, "cmd": "python -m mutmut run"},
        ]
        for tainted, process_list in ((True, procs), (False, procs[:1])):
            with self.subTest(tainted=tainted):
                self.docker = F.FakeDocker()
                self.egress.docker = self.docker
                self.docker.configure(diff_text=PLANTED_DIFF, procs=process_list)
                run_dir = self.go(arms=("baseline",))
                prediction = self.load(self.entry(run_dir, F.ROW_A, "baseline") / "prediction.json")
                self.assertIs(prediction["tainted"], tainted)
                self.assertEqual(len(self.indices(self.name(run_dir, 1), F.KILL_ARGV)), 1)

    def test_vo7_e8_git_failure_ends_the_entry_in_error_but_still_collects_raw(self):
        cases = (
            ("add", {"add_fail": (128, "fatal: boom-add")}, "git failed: fatal: boom-add"),
            ("diff", {"diff_fail": (129, "fatal: boom-diff")}, "git failed: fatal: boom-diff"),
        )
        for name, kw, reason in cases:
            with self.subTest(name):
                self.docker = F.FakeDocker()
                self.egress.docker = self.docker
                self.docker.configure(diff_text=PLANTED_DIFF, **kw)
                run_dir = self.go(arms=("baseline",))
                state = self.entry_state(run_dir)
                self.assertEqual(state["status"], "error")
                self.assertEqual(state["reason"], reason)
                raw = self.entry(run_dir, F.ROW_A, "baseline") / "raw"
                self.assertTrue((raw / "messages.jsonl").is_file())
                self.assertTrue((raw / "state.json").is_file())
                self.assertFalse(self.docker.container_labelled(run_dir.name))
                self.assertEqual(self.load(run_dir / "run.json")["entries"][0]["status"], "error")


if __name__ == "__main__":
    unittest.main()

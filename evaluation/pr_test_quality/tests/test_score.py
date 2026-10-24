import json
import re
import unittest
from pathlib import Path

from evaluation.pr_test_quality import recipes, score, testrun
from evaluation.pr_test_quality.tests.fakes import (
    MISSING, FakeDocker, TmpCase, failing_replace, find, make_task, pytest_junit, udiff,
)


def num(result, *needles):
    value = find(result, *needles)
    if value is MISSING:
        raise AssertionError("no key with %r in %r" % (needles, result))
    return value


class HiddenOutcome(unittest.TestCase):
    def test_O16_all_pass_is_resolved(self):
        out = score.hidden_outcome({"f1": "pass", "f2": "pass", "p1": "pass"}, ["f1", "f2"], ["p1"])
        self.assertEqual((out["resolved"], out["f2p_frac"], out["p2p_broken"]), (True, 1.0, []))

    def test_O16_partial_f2p_is_unresolved_with_fraction(self):
        out = score.hidden_outcome({"f1": "pass", "f2": "fail", "p1": "pass", "p2": "error"},
                                   ["f1", "f2"], ["p1", "p2"])
        self.assertFalse(out["resolved"])
        self.assertEqual(out["f2p_frac"], 0.5)
        self.assertEqual(out["p2p_broken"], ["p2"])

    def test_O16_broken_p2p_alone_blocks_resolution(self):
        out = score.hidden_outcome({"f1": "pass", "p1": "fail"}, ["f1"], ["p1"])
        self.assertFalse(out["resolved"])
        self.assertEqual(out["f2p_frac"], 1.0)
        self.assertEqual(out["p2p_broken"], ["p1"])

    def test_O16_missing_and_skipped_ids_do_not_count_as_passing(self):
        out = score.hidden_outcome({"f1": "skip", "p1": "pass"}, ["f1", "f2"], ["p1", "p3"])
        self.assertFalse(out["resolved"])
        self.assertEqual(out["f2p_frac"], 0.0)
        self.assertEqual(out["p2p_broken"], ["p3"])

    def test_O16_zero_f2p_pass_gives_zero_fraction(self):
        out = score.hidden_outcome({"f1": "fail", "f2": "error"}, ["f1", "f2"], [])
        self.assertEqual((out["resolved"], out["f2p_frac"]), (False, 0.0))


class AgentIds(unittest.TestCase):
    def test_O16_ids_absent_from_base_only(self):
        base = {"t_old": "pass", "t_old2": "fail"}
        agent = {"t_old": "pass", "t_new1": "pass", "t_new2": "fail", "t_old2": "fail"}
        self.assertEqual(sorted(score.agent_test_ids(base, agent)), ["t_new1", "t_new2"])

    def test_O16_no_new_ids_gives_empty(self):
        self.assertEqual(score.agent_test_ids({"a": "pass"}, {"a": "fail"}), [])

    def test_O16_everything_new_when_base_empty(self):
        self.assertEqual(sorted(score.agent_test_ids({}, {"x": "pass", "y": "fail"})), ["x", "y"])


class Validity(unittest.TestCase):
    def test_O16_classification_and_false_alarm_rate(self):
        runs = [{"a": "pass", "b": "fail", "c": "error", "d": "pass"},
                {"a": "pass", "b": "fail", "c": "error", "d": "fail"}]
        out = score.validity(runs, ["a", "b", "c", "d", "f"])
        self.assertEqual(out["n"], 5)
        self.assertEqual(sorted(out["valid"]), ["a"])
        self.assertEqual(sorted(out["false_alarm"]), ["b"])
        self.assertEqual(sorted(out["incompatible"]), ["c", "f"])
        self.assertEqual(sorted(out["flaky"]), ["d"])
        self.assertEqual(out["false_alarm_rate"], 0.5)

    def test_O16_rate_is_false_alarm_over_valid_plus_false_alarm(self):
        runs = [{"a": "pass", "b": "pass", "c": "pass", "d": "fail"}] * 2
        out = score.validity(runs, ["a", "b", "c", "d"])
        self.assertEqual(out["false_alarm_rate"], 0.25)
        self.assertEqual(out["valid"], ["a", "b", "c"])

    def test_O16_C27_no_tests_gives_none_rate(self):
        out = score.validity([{}, {}], [])
        self.assertEqual(out["n"], 0)
        self.assertIsNone(out["false_alarm_rate"])
        self.assertEqual(out["valid"], [])

    def test_O16_all_incompatible_gives_none_rate(self):
        out = score.validity([{"x": "error"}, {"x": "error"}], ["x"])
        self.assertEqual(out["incompatible"], ["x"])
        self.assertIsNone(out["false_alarm_rate"])

    def test_O16_all_false_alarms_gives_rate_one(self):
        out = score.validity([{"x": "fail"}, {"x": "fail"}], ["x"])
        self.assertEqual(out["false_alarm_rate"], 1.0)


def mutant_runs(n, killed_by, status=None, extra=None):
    runs = {}
    for i in range(n):
        results = {"v1": "pass", "v2": "pass"}
        for vid in killed_by.get("m%d" % i, ()):
            results[vid] = "fail"
        results.update((extra or {}).get("m%d" % i, {}))
        runs["m%d" % i] = {"status": (status or {}).get("m%d" % i, "ok"), "results": results}
    return runs


class Kill(unittest.TestCase):
    def test_O16_C25_raw_and_normalized(self):
        killed = {"m%d" % i: ["v1"] for i in range(6)}
        killed["m8"] = ["v2"]
        d_ref = {"m%d" % i for i in range(8)}
        out = score.kill(mutant_runs(10, killed), ["v1", "v2"], d_ref)
        self.assertEqual((out["executed"], out["killed"], out["d_ref_n"]), (10, 7, 8))
        self.assertEqual(sorted(out["killed_ids"]), ["m0", "m1", "m2", "m3", "m4", "m5", "m8"])
        self.assertEqual(out["raw"], 0.7)
        self.assertEqual(out["normalized"], 0.75)

    def test_O16_C28_build_error_and_timeout_mutants_are_not_executed(self):
        killed = {"m0": ["v1"], "m1": ["v1"], "m2": ["v2"]}
        status = {"m6": "build_error", "m7": "timeout"}
        runs = mutant_runs(10, killed, status=status)
        runs["m6"]["results"], runs["m7"]["results"] = {}, {}
        d_ref = {"m0", "m1", "m2", "m3", "m4", "m5"}
        out = score.kill(runs, ["v1", "v2"], d_ref)
        self.assertEqual(out["raw"], 3 / 8)
        self.assertEqual(out["normalized"], 0.5)

    def test_O16_only_valid_tests_can_kill(self):
        runs = mutant_runs(4, {}, extra={"m0": {"bad": "fail"}, "m1": {"v1": "fail"}})
        out = score.kill(runs, ["v1"], {"m0", "m1"})
        self.assertEqual(out["raw"], 0.25)
        self.assertEqual(out["normalized"], 0.5)

    def test_O16_failing_outside_d_ref_raises_raw_but_not_normalized(self):
        runs = mutant_runs(4, {"m3": ["v1"]})
        out = score.kill(runs, ["v1"], {"m0", "m1"})
        self.assertEqual(out["raw"], 0.25)
        self.assertEqual(out["normalized"], 0.0)

    def test_O16_C27_no_valid_tests_kill_zero(self):
        out = score.kill(mutant_runs(10, {}), [], {"m0", "m1", "m2"})
        self.assertEqual(out["raw"], 0)
        self.assertEqual(out["normalized"], 0)

    def test_O16_every_mutant_killed_scores_one(self):
        killed = {"m%d" % i: ["v1"] for i in range(5)}
        out = score.kill(mutant_runs(5, killed), ["v1"], {"m%d" % i for i in range(5)})
        self.assertEqual((out["raw"], out["normalized"]), (1.0, 1.0))


class AmbiguityCorrect(unittest.TestCase):
    BRIEF = {"request": "r", "statements": [
        {"id": "S1", "text": "a", "f2p": ["f1"]}, {"id": "S2", "text": "b", "f2p": ["f2", "f3"]},
        {"id": "S3", "text": "c", "f2p": ["f4"]}], "ambiguous": ["S2", "S3"]}

    def test_O16_counts_ambiguous_statements_whose_f2p_all_pass(self):
        out = score.ambiguity_correct({"f1": "fail", "f2": "pass", "f3": "pass", "f4": "fail"}, self.BRIEF)
        self.assertEqual((out["n"], out["correct"], out["rate"]), (2, 1, 0.5))

    def test_O16_one_failing_f2p_makes_the_statement_incorrect(self):
        out = score.ambiguity_correct({"f1": "pass", "f2": "pass", "f3": "fail", "f4": "pass"}, self.BRIEF)
        self.assertEqual((out["n"], out["correct"], out["rate"]), (2, 1, 0.5))

    def test_O16_all_correct(self):
        out = score.ambiguity_correct({"f1": "pass", "f2": "pass", "f3": "pass", "f4": "pass"}, self.BRIEF)
        self.assertEqual((out["correct"], out["rate"]), (2, 1.0))

    def test_O16_no_ambiguous_statements(self):
        out = score.ambiguity_correct({"f1": "pass"}, dict(self.BRIEF, ambiguous=[]))
        self.assertEqual((out["n"], out["correct"]), (0, 0))


class SelfReport(unittest.TestCase):
    def test_O16_last_verification_marker_counts(self):
        first = {"event": "verification_result", "fuzz_execs": 10, "fuzz_violations": 0, "mutants": 20,
                 "killed": 10, "survived": 10, "equivalent": 0, "overturned": 0}
        last = {"event": "verification_result", "fuzz_execs": 5000, "fuzz_violations": 1, "mutants": 40,
                "killed": 31, "survived": 9, "equivalent": 6, "overturned": 1}
        out = score.self_report([first, {"event": "workflow_phase", "phase": "x"}, last, {"event": "workflow_end"}])
        for key in ("fuzz_execs", "mutants", "killed", "survived", "equivalent"):
            self.assertEqual(out[key], last[key])

    def test_O16_none_without_marker(self):
        self.assertIsNone(score.self_report([]))
        self.assertIsNone(score.self_report([{"event": "workflow_start"}, {"event": "test_command"}]))


SRC = "src/calc/ops.py"
GOLD_TEST = "tests/test_ops.py"
AGENT_TEST = "tests/test_agent_ops.py"
F2P = GOLD_TEST + "::test_clamp_f2p"
P2P = GOLD_TEST + "::test_keeps"
BASE_SRC = "# BASESRC\ndef f0(x):\n    return x\n"
GOLD_SRC = "# GOLDSRC\n" + "".join("def f%d(x):\n    return x + %d\n" % (i, i) for i in range(12))
AGENT_TEST_TEXT = "# AGENTTEST\ndef test_a1(): pass\n"
IDS = {k: AGENT_TEST + "::" + k for k in ("a1", "a2", "a3", "bad", "inc")}


def mutant_rows(n, gold):
    rows = []
    for i in range(n):
        mutated = GOLD_SRC.replace("    return x + %d\n" % i, "    return x - %d  # M%d\n" % (i, i), 1)
        rows.append({"id": "m%02d" % i, "path": SRC, "line": 2 * i + 3, "diff": udiff(SRC, GOLD_SRC, mutated),
                     "gold": gold.get(i, "survived")})
    return rows


class World:
    """Scripts the fake test runner: results depend only on which files the tree wrote."""

    def __init__(self, *, kills=None, agent_src="# AGENTSRC_GOOD\n", agent_ids=("a1", "a2", "a3", "bad", "inc"),
                 mutant_status=None, n_mutants=10, gold_killed=range(8)):
        self.kills = kills or {}
        self.agent_src = agent_src
        self.agent_ids = list(agent_ids)
        self.mutant_status = mutant_status or {}
        gold = {i: "killed" for i in gold_killed}
        gold.update({i: s for i, s in self.mutant_status.items()})
        self.mutants = mutant_rows(n_mutants, gold)
        self.docker = FakeDocker(junit_policy=self.policy)

    def policy(self, c):
        files = c.files()
        src = files.get("/testbed/" + SRC)
        text = c.tree_text()
        marker = re.search(r"# M(\d+)\b", text)
        if marker and self.mutant_status.get(int(marker.group(1))) == "timeout":
            return "timeout"
        if marker and self.mutant_status.get(int(marker.group(1))) == "build_error":
            return None
        results = {}
        if "/testbed/" + GOLD_TEST in files or any(p.endswith(GOLD_TEST) for p in files):
            good = src is not None and ("AGENTSRC_GOOD" in src or "GOLDSRC" in src)
            results[F2P] = "pass" if good else "fail"
            results[P2P] = "pass"
        if any(p.endswith(AGENT_TEST) for p in files):
            gold_src = src is not None and "GOLDSRC" in src
            for key in self.agent_ids:
                if key == "inc":
                    status = "error"
                elif key == "bad":
                    status = "fail"
                elif gold_src:
                    status = "pass"
                    if marker and key in self.kills.get(int(marker.group(1)), ()):
                        status = "fail"
                else:
                    status = "fail"
                results[IDS[key]] = status
        return pytest_junit(results)

    def task(self):
        recipe = recipes.detect("python", {"requirements.txt": "pytest\n"})
        task = make_task("python", recipe=recipe, mutants=self.mutants,
                         brief={"request": "r", "statements": [], "ambiguous": []})
        task["f2p"], task["p2p"] = [F2P], [P2P]
        task["gold_base"] = {SRC: BASE_SRC, GOLD_TEST: None}
        task["gold_after"] = {SRC: GOLD_SRC, GOLD_TEST: "# GOLDTEST\ndef test_x(): pass\n"}
        src_diff = udiff(SRC, BASE_SRC, GOLD_SRC)
        test_diff = udiff(GOLD_TEST, None, task["gold_after"][GOLD_TEST])
        task["gold_split"] = {"src": src_diff, "tests": test_diff, "harness": "", "other": ""}
        task["gold_patch"] = src_diff + test_diff
        return task

    def entry(self, root, task, arm="B0", repeat=1, cost=1.25, with_tests=True):
        d = Path(root) / task["task_id"] / ("%s-r%d" % (arm, repeat))
        (d / "raw").mkdir(parents=True)
        src_diff = udiff(SRC, BASE_SRC, self.agent_src)
        tests_diff = udiff(AGENT_TEST, None, AGENT_TEST_TEXT) if with_tests else ""
        split = {"src": src_diff, "tests": tests_diff, "harness": "", "other": ""}
        (d / "full.diff").write_text(src_diff + tests_diff, encoding="utf-8")
        agent = {"split": split,
                 "base": {SRC: BASE_SRC, AGENT_TEST: None} if with_tests else {SRC: BASE_SRC},
                 "after": {SRC: self.agent_src, AGENT_TEST: AGENT_TEST_TEXT} if with_tests else {SRC: self.agent_src}}
        (d / "split.json").write_text(json.dumps(agent), encoding="utf-8")
        (d / "manifest.json").write_text(json.dumps({"task_id": task["task_id"], "arm": arm, "repeat": repeat}),
                                         encoding="utf-8")
        (d / "state.json").write_text(json.dumps({
            "status": "completed", "reason": None, "session_id": "s", "rate_limit": None,
            "results": [{"total_cost_usd": cost, "duration_ms": 321000, "num_turns": 9, "is_error": False}]}),
            encoding="utf-8")
        (d / "usersim.jsonl").write_text("", encoding="utf-8")
        return d


class ScoreEntry(TmpCase):
    counter = 0

    def run_world(self, world, **kw):
        type(self).counter += 1
        root = self.tmp / ("run%d" % self.counter)
        task = world.task()
        entry = world.entry(root, task, **kw)
        cfg = self.cfg()
        result = score.score_entry(task, entry, docker=world.docker, cfg=cfg, cache_dir=root / "cache")
        return result, entry, task

    def test_O16_resolved_agent_metrics_and_score_json(self):
        result, entry, _ = self.run_world(World())
        self.assertIs(result["hidden"]["resolved"], True)
        self.assertEqual(result["hidden"]["f2p_frac"], 1.0)
        written = json.loads((entry / "score.json").read_text(encoding="utf-8"))
        self.assertEqual(written, json.loads(json.dumps(result)))
        self.assertEqual(result["cost_usd"], 1.25)

    def test_O16_F12_score_json_shape(self):
        result, _, _ = self.run_world(World())
        self.assertEqual(set(result), {"entry", "hidden", "validity", "kill", "ambiguity", "cost_usd", "wall_s",
                                       "questions", "corrections", "self_report"})
        self.assertEqual(result["entry"], "B0-r1")
        self.assertEqual(result["hidden"]["status"], "ok")
        self.assertEqual(result["wall_s"], 321.0)
        self.assertEqual(set(result["kill"]), {"executed", "killed", "raw", "normalized", "killed_ids", "d_ref_n",
                                               "flagged"})

    def test_O16_unresolved_agent_when_hidden_gold_tests_fail(self):
        result, _, _ = self.run_world(World(agent_src="# AGENTSRC_BAD\n"))
        self.assertIs(result["hidden"]["resolved"], False)
        self.assertEqual(result["hidden"]["f2p_frac"], 0.0)

    def test_O16_validity_counts_and_false_alarm_rate(self):
        result, _, _ = self.run_world(World())
        self.assertEqual(result["validity"]["false_alarm_rate"], 0.25)
        incompatible = result["validity"]["incompatible"]
        self.assertEqual(len(incompatible) if isinstance(incompatible, list) else incompatible, 1)

    def test_O16_C25_kill_through_score_entry(self):
        kills = {i: ["a1"] for i in range(6)}
        kills[8] = ["a2"]
        result, _, _ = self.run_world(World(kills=kills))
        self.assertEqual(result["kill"]["raw"], 0.7)
        self.assertEqual(result["kill"]["normalized"], 0.75)

    def flag(self, n_mutants, gold_killed):
        result, _, _ = self.run_world(World(kills={0: ["a1"]}, n_mutants=n_mutants, gold_killed=range(gold_killed)))
        return result["kill"]["flagged"]

    def test_O16_C26_d_ref_nine_is_flagged_ten_is_not(self):
        self.assertTrue(self.flag(11, 9))
        self.assertFalse(self.flag(12, 10))

    def test_O16_C25_d_ref_eight_is_flagged(self):
        self.assertTrue(self.flag(10, 8))

    def test_O16_C28_build_error_and_timeout_mutants_excluded_from_executed(self):
        world = World(kills={0: ["a1"], 1: ["a1"], 2: ["a2"]}, mutant_status={6: "build_error", 7: "timeout"},
                      gold_killed=range(6))
        result, _, _ = self.run_world(world)
        self.assertEqual(result["kill"]["raw"], 3 / 8)
        self.assertEqual(result["kill"]["normalized"], 0.5)

    def test_O16_C27_agent_with_no_valid_tests_scores_zero_and_none_rate(self):
        result, _, _ = self.run_world(World(agent_ids=("inc",)))
        self.assertEqual(result["kill"]["raw"], 0)
        self.assertEqual(result["kill"]["normalized"], 0)
        self.assertIsNone(result["validity"]["false_alarm_rate"])

    def test_O16_C27_agent_without_test_files_scores_zero_and_none_rate(self):
        result, _, _ = self.run_world(World(), with_tests=False)
        self.assertEqual(result["kill"]["raw"], 0)
        self.assertEqual(result["kill"]["normalized"], 0)
        self.assertIsNone(result["validity"]["false_alarm_rate"])

    def test_O16_test_runs_are_offline_and_use_eval_timeout(self):
        world = World()
        self.run_world(world)
        self.assertTrue(world.docker.containers)
        for cont in world.docker.containers:
            self.assertIn(cont.kwargs.get("network"), (False, "none", None))
            for ex in cont.execs:
                if "pytest" in " ".join(ex["argv"]):
                    self.assertEqual(ex["timeout"], 900)

    def test_O16_QR7_score_json_survives_failed_replace(self):
        world = World()
        task = world.task()
        entry = world.entry(self.tmp / "run", task)
        cache = self.tmp / "cache"
        score.score_entry(task, entry, docker=world.docker, cfg=self.cfg(), cache_dir=cache)
        self.assertNotEqual((entry / "score.json").read_text(encoding="utf-8"), "PREVIOUS")
        json.loads((entry / "score.json").read_text(encoding="utf-8"))
        (entry / "score.json").write_text("PREVIOUS", encoding="utf-8")
        with failing_replace("score.json"):
            try:
                score.score_entry(task, entry, docker=world.docker, cfg=self.cfg(), cache_dir=cache)
            except OSError:
                pass
        self.assertEqual((entry / "score.json").read_text(encoding="utf-8"), "PREVIOUS")


class ScoreRun(TmpCase):
    def test_O16_QR2_second_score_run_starts_no_containers(self):
        world = World()
        task = world.task()
        run_dir = self.tmp / "run"
        world.entry(run_dir, task, arm="B0")
        world.entry(run_dir, task, arm="H")
        (run_dir / "run.json").write_text(json.dumps({
            "run_id": "r1", "phase": "dev", "prereg_sha256": "0" * 64,
            "entries": [{"task_id": task["task_id"], "arm": "B0", "repeat": 1, "status": "completed"},
                        {"task_id": task["task_id"], "arm": "H", "repeat": 1, "status": "completed"}]}),
            encoding="utf-8")
        cfg = self.cfg()
        first = score.score_run(run_dir, {task["task_id"]: task}, docker=world.docker, cfg=cfg,
                                cache_dir=self.tmp / "cache")
        self.assertEqual(len(first), 2)
        ran = world.docker.runs
        self.assertGreater(ran, 0)
        second = score.score_run(run_dir, {task["task_id"]: task}, docker=world.docker, cfg=cfg,
                                 cache_dir=self.tmp / "cache")
        self.assertEqual(world.docker.runs, ran)
        self.assertEqual(len(second), 2)
        self.assertEqual(second[0]["hidden"]["resolved"], first[0]["hidden"]["resolved"])


class RunTests(TmpCase):
    def setUp(self):
        super().setUp()
        self.task = make_task("python", recipe=recipes.detect("python", {"requirements.txt": "pytest\n"}))
        self.ids = {"tests/test_a.py::test_one": "pass", "tests/test_a.py::test_two": "fail"}
        self.docker = FakeDocker(junit_policy=lambda c: pytest_junit(self.ids))
        self.cache = self.tmp / "cache"
        self.tree = {"src/calc/ops.py": "NEW TEXT\n", "tests/test_a.py": "T\n"}

    def run_tests(self, tree=None, selection=("tests/test_a.py",), repeat=0, task=None):
        return testrun.run_tests(task or self.task, self.tree if tree is None else tree, list(selection),
                                 docker=self.docker, cfg=self.cfg(), cache_dir=self.cache, repeat=repeat)

    def cache_files(self):
        return sorted(p.name for p in self.cache.glob("*.json")) if self.cache.exists() else []

    def test_O16_ok_run_returns_results_and_writes_tree_under_testbed(self):
        out = self.run_tests()
        self.assertEqual(out["status"], "ok")
        self.assertEqual(out["results"], self.ids)
        self.assertFalse(out["cached"])
        self.assertIsInstance(out["runtime_s"], float)
        cont = self.docker.containers[0]
        self.assertEqual(cont.files()["/testbed/src/calc/ops.py"], "NEW TEXT\n")
        self.assertEqual(cont.files()["/testbed/tests/test_a.py"], "T\n")
        self.assertEqual(cont.image, self.task["image"])
        self.assertIn(cont.kwargs["network"], (False, "none", None))

    def test_O16_runner_argv_carries_selection_and_eval_timeout(self):
        self.run_tests(selection=("tests/test_a.py", "tests/test_b.py"))
        runs = [e for e in self.docker.containers[0].execs if "pytest" in " ".join(e["argv"])]
        self.assertEqual(len(runs), 1)
        self.assertIn("tests/test_a.py", runs[0]["argv"])
        self.assertIn("tests/test_b.py", runs[0]["argv"])
        self.assertEqual(runs[0]["timeout"], 900)

    def test_O16_none_entry_deletes_the_path(self):
        self.run_tests(tree={"src/old.py": None, "src/keep.py": "K\n"})
        cont = self.docker.containers[0]
        self.assertNotIn("/testbed/src/old.py", cont.files())
        self.assertEqual(cont.files()["/testbed/src/keep.py"], "K\n")
        removals = [e["argv"] for e in cont.execs if "/testbed/src/old.py" in " ".join(e["argv"])]
        self.assertTrue(removals)

    def test_O16_exit_code_one_with_junit_is_still_ok(self):
        self.docker.junit_exit = 1
        self.assertEqual(self.run_tests()["status"], "ok")

    def test_O16_no_junit_file_is_build_error(self):
        self.docker.junit_policy = lambda c: None
        out = self.run_tests()
        self.assertEqual(out["status"], "build_error")
        self.assertEqual(out["results"], {})

    def test_O16_timeout_status_and_not_cached(self):
        self.docker.junit_policy = lambda c: "timeout"
        out = self.run_tests()
        self.assertEqual(out["status"], "timeout")
        self.assertEqual(self.cache_files(), [])
        self.run_tests()
        self.assertEqual(self.docker.runs, 2)

    def test_O16_QR2_cache_hit_runs_no_container(self):
        self.run_tests()
        self.assertEqual(self.docker.runs, 1)
        again = self.run_tests()
        self.assertEqual(self.docker.runs, 1)
        self.assertTrue(again["cached"])
        self.assertEqual(again["results"], self.ids)
        self.assertEqual(len(self.cache_files()), 1)
        self.assertRegex(self.cache_files()[0], r"^[0-9a-f]{64}\.json$")

    def test_O16_build_error_is_cached_too(self):
        self.docker.junit_policy = lambda c: None
        self.run_tests()
        again = self.run_tests()
        self.assertTrue(again["cached"])
        self.assertEqual(again["status"], "build_error")
        self.assertEqual(self.docker.runs, 1)

    def test_O16_cache_key_covers_tree_selection_repeat_and_image(self):
        self.run_tests()
        self.run_tests(tree={"src/calc/ops.py": "OTHER\n", "tests/test_a.py": "T\n"})
        self.run_tests(selection=("tests/test_b.py",))
        self.run_tests(repeat=1)
        self.run_tests(task=dict(self.task, image="eval/other:image"))
        self.assertEqual(self.docker.runs, 5)
        self.assertEqual(len(self.cache_files()), 5)

    def test_O16_cache_key_ignores_tree_insertion_order(self):
        self.run_tests(tree={"a.py": "A\n", "b.py": "B\n"})
        again = self.run_tests(tree={"b.py": "B\n", "a.py": "A\n"})
        self.assertTrue(again["cached"])
        self.assertEqual(self.docker.runs, 1)


if __name__ == "__main__":
    unittest.main()

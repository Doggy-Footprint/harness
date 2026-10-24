import itertools
import json
import re
import unittest
from pathlib import Path

from evaluation.pr_test_quality import score
from evaluation.pr_test_quality.tests.fakes import FakeDocker, TmpCase, pytest_junit, udiff
from evaluation.pr_test_quality.tests.test_score import (
    AGENT_TEST, AGENT_TEST_TEXT, BASE_SRC, F2P, GOLD_SRC, GOLD_TEST, IDS, P2P, SRC, World,
)

EXIST = "tests/test_existing.py"
E1, E2, E3 = (EXIST + "::test_e%d" % i for i in (1, 2, 3))
EXIST_BASE = "# BASEEXIST\ndef test_e1(): pass\ndef test_e2(): pass\n"
EXIST_AGENT = "# AGENTEXIST\ndef test_e1(): pass\ndef test_e2(): pass\ndef test_e3(): pass\n"


class ValidityClasses(unittest.TestCase):
    STATUSES = ("pass", "fail", "error", "skip", "missing")

    @staticmethod
    def expected(a, b):
        if a == b == "pass":
            return "valid"
        if a == b == "fail":
            return "false_alarm"
        if a == b == "skip":
            return "skipped"
        if a in ("error", "missing") and b in ("error", "missing"):
            return "incompatible"
        return "flaky"

    def runs(self, a, b):
        return [{} if s == "missing" else {"x": s} for s in (a, b)]

    def test_O16_every_pair_of_run_statuses_lands_in_the_hand_derived_class(self):
        for a, b in itertools.product(self.STATUSES, repeat=2):
            out = score.validity(self.runs(a, b), ["x"])
            want = self.expected(a, b)
            with self.subTest(first=a, second=b, want=want):
                for cls in ("valid", "false_alarm", "incompatible", "flaky"):
                    self.assertEqual(out[cls], ["x"] if cls == want else [], cls)
                self.assertEqual(out["n"], 0 if want == "skipped" else 1)

    def test_O16_skipped_ids_are_excluded_from_n_and_the_rate(self):
        runs = [{"a": "pass", "s": "skip", "b": "fail"}, {"a": "pass", "s": "skip", "b": "pass"}]
        out = score.validity(runs, ["a", "s", "b"])
        self.assertEqual(out["n"], 2)
        self.assertEqual((out["valid"], out["flaky"]), (["a"], ["b"]))
        self.assertEqual(out["false_alarm_rate"], 0.0)

    def test_O16_n_is_the_sum_of_the_four_classes(self):
        runs = [{"v": "pass", "f": "fail", "i": "error", "m": "pass", "s": "skip"},
                {"v": "pass", "f": "fail", "i": "error", "m": "fail", "s": "skip"}]
        out = score.validity(runs, ["v", "f", "i", "m", "s", "gone"])
        self.assertEqual(out["n"], 5)
        self.assertEqual(sum(len(out[c]) for c in ("valid", "false_alarm", "incompatible", "flaky")), 5)
        self.assertEqual(sorted(out["incompatible"]), ["gone", "i"])
        self.assertEqual(out["false_alarm_rate"], 0.5)


class KillNoneRules(unittest.TestCase):
    def runs(self, n, status="ok"):
        return {"m%d" % i: {"status": status, "results": {"v": "pass"}} for i in range(n)}

    def test_O16_nothing_executed_gives_none_for_raw_and_normalized(self):
        out = score.kill({}, ["v"], {"m0"})
        self.assertEqual((out["executed"], out["raw"], out["normalized"]), (0, None, None))
        out = score.kill(self.runs(3, "build_error"), ["v"], {"m0"})
        self.assertEqual((out["executed"], out["raw"], out["normalized"]), (0, None, None))
        out = score.kill(self.runs(2, "timeout"), [], set())
        self.assertEqual((out["raw"], out["normalized"]), (None, None))

    def test_O16_empty_d_ref_gives_none_normalized_but_a_raw_value(self):
        runs = self.runs(4)
        runs["m1"]["results"]["v"] = "fail"
        out = score.kill(runs, ["v"], set())
        self.assertEqual((out["executed"], out["killed"], out["raw"]), (4, 1, 0.25))
        self.assertIsNone(out["normalized"])
        self.assertEqual(out["d_ref_n"], 0)

    def test_O16_zero_valid_tests_with_executed_mutants_scores_zero_not_none(self):
        out = score.kill(self.runs(4), [], {"m0", "m1"})
        self.assertEqual((out["raw"], out["normalized"]), (0.0, 0.0))

    def test_O16_a_failing_or_erroring_valid_test_kills_the_mutant(self):
        runs = self.runs(3)
        runs["m0"]["results"]["v"] = "fail"
        runs["m1"]["results"]["v"] = "error"
        out = score.kill(runs, ["v"], {"m0", "m1", "m2"})
        self.assertEqual(sorted(out["killed_ids"]), ["m0", "m1"])
        self.assertEqual(out["normalized"], 2 / 3)


class WorldV5(World):
    def __init__(self, *, existing=True, hidden_override=None, state_status="completed", ask=3, idle=(True, False),
                 telemetry=None, results=((0.5, 1000), (0.25, 2500)), **kw):
        super().__init__(**kw)
        self.existing, self.hidden_override, self.state_status = existing, hidden_override, state_status
        self.ask, self.idle, self.telemetry, self.results = ask, idle, telemetry, results
        self.docker = FakeDocker(junit_policy=self.policy)

    def policy(self, c):
        files = c.files()
        gold_test = any(p.endswith(GOLD_TEST) for p in files)
        if gold_test and self.hidden_override is not None:
            return self.hidden_override
        base = super().policy(c)
        res = {}
        text_by_suffix = {p: t for p, t in files.items()}
        for path, text in text_by_suffix.items():
            if path.endswith(EXIST):
                res[E1] = "pass"
                res[E2] = "pass"
                if "AGENTEXIST" in text:
                    res[E3] = "pass"
        if not res:
            return base
        import xml.etree.ElementTree as ET
        merged = ET.fromstring(base)
        suite = merged.find("testsuite")
        extra = ET.fromstring(pytest_junit(res)).find("testsuite")
        for case in extra:
            suite.append(case)
        return ET.tostring(merged, encoding="unicode")

    def task(self):
        task = super().task()
        task["brief"] = {"request": "r", "ambiguous": ["S1"], "status": "ok", "attempts": 1, "reason": "ok",
                         "statements": [{"id": "S1", "text": "a", "f2p": [F2P]}, {"id": "S2", "text": "b", "f2p": [P2P]}]}
        return task

    def entry(self, root, task, arm="B0", repeat=1, cost=1.25, with_tests=True):
        d = super().entry(root, task, arm=arm, repeat=repeat, with_tests=with_tests)
        split = json.loads((d / "split.json").read_text())
        if self.existing:
            split["base"][EXIST] = EXIST_BASE
            split["after"][EXIST] = EXIST_AGENT
            split["split"]["tests"] += udiff(EXIST, EXIST_BASE, EXIST_AGENT)
            (d / "split.json").write_text(json.dumps(split), encoding="utf-8")
        state = json.loads((d / "state.json").read_text())
        state["status"] = self.state_status
        state["results"] = [{"total_cost_usd": c, "duration_ms": ms, "num_turns": 1, "is_error": False}
                            for c, ms in self.results]
        (d / "state.json").write_text(json.dumps(state), encoding="utf-8")
        rows = [{"kind": "ask", "n": i} for i in range(self.ask)]
        rows += [{"kind": "idle", "n": 10 + i, "contradiction": flag} for i, flag in enumerate(self.idle)]
        (d / "usersim.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
        events = self.telemetry if self.telemetry is not None else [
            {"event": "workflow_start"},
            {"event": "verification_result", "fuzz_execs": 1, "fuzz_violations": 0, "mutants": 20, "killed": 10,
             "survived": 10, "equivalent": 0, "overturned": 0},
            {"event": "test_command"},
            {"event": "verification_result", "fuzz_execs": 5000, "fuzz_violations": 1, "mutants": 40, "killed": 31,
             "survived": 9, "equivalent": 6, "overturned": 1}]
        tel = d / "raw" / "telemetry"
        tel.mkdir(parents=True, exist_ok=True)
        (tel / "events.jsonl").write_text("".join(json.dumps(e) + "\n" for e in events), encoding="utf-8")
        return d


class Scoring(TmpCase):
    counter = 0

    def go(self, world, **kw):
        type(self).counter += 1
        root = self.tmp / ("run%d" % self.counter)
        task = world.task()
        entry = world.entry(root, task, **kw)
        result = score.score_entry(task, entry, docker=world.docker, cfg=self.cfg(), cache_dir=root / "cache")
        return result, task, entry

    def execs(self, world, needle="pytest"):
        out = []
        for cont in world.docker.containers:
            for ex in cont.execs:
                if needle in " ".join(ex["argv"]):
                    out.append((cont, ex))
        return out

    def test_O16_F6_pre_existing_test_ids_of_a_modified_test_file_do_not_count(self):
        result, _, _ = self.go(WorldV5(kills={0: ["a1"]}))
        validity = result["validity"]
        self.assertEqual(sorted(validity["valid"]), sorted([E3, IDS["a1"], IDS["a2"], IDS["a3"]]))
        self.assertEqual(validity["false_alarm"], [IDS["bad"]])
        self.assertEqual(validity["incompatible"], [IDS["inc"]])
        for old in (E1, E2):
            self.assertNotIn(old, json.dumps(validity))
        self.assertEqual(validity["n"], 6)
        self.assertEqual(validity["false_alarm_rate"], 0.2)

    def test_O16_F6_without_the_base_tests_run_the_old_ids_would_leak_in(self):
        world = WorldV5()
        self.go(world)
        base_runs = [c for c, ex in self.execs(world) if any(p.endswith(EXIST) and "BASEEXIST" in t
                                                              for p, t in c.files().items())]
        self.assertEqual(len(base_runs), 1)
        files = base_runs[0].files()
        self.assertFalse([p for p in files if p.endswith(AGENT_TEST)])
        self.assertFalse([p for p in files if p.endswith(SRC)])

    def test_O16_F6_base_tests_run_is_skipped_when_the_agent_touched_no_existing_test_file(self):
        with_existing, without = WorldV5(existing=True), WorldV5(existing=False)
        self.go(with_existing)
        self.go(without)
        self.assertEqual(with_existing.docker.runs, without.docker.runs + 1)

    def test_O16_F6_validity_runs_exactly_twice_with_distinct_cache_keys(self):
        world = WorldV5(existing=False)
        result, task, entry = self.go(world)
        cache_dir = entry.parent.parent / "cache"
        validity_runs = []
        for cont in world.docker.containers:
            files = cont.files()
            text = cont.tree_text()
            if any(p.endswith(AGENT_TEST) for p in files) and "GOLDSRC" in text and not re.search(r"# M\d+\b", text):
                validity_runs.append(cont)
        self.assertEqual(len(validity_runs), 2)
        keys = {p.name for p in cache_dir.glob("*.json")}
        self.assertEqual(len(keys), world.docker.runs)

    def test_O16_F6_run_selections(self):
        world = WorldV5()
        self.go(world)
        gold_runs = [(c, ex) for c, ex in self.execs(world) if any(p.endswith(GOLD_TEST) for p in c.files())]
        self.assertEqual(len(gold_runs), 1)
        argv = gold_runs[0][1]["argv"]
        self.assertIn(GOLD_TEST, argv)
        self.assertFalse([a for a in argv if a.endswith("test_agent_ops.py") or a.endswith("test_existing.py")])
        validity = [(c, ex) for c, ex in self.execs(world)
                    if any(p.endswith(AGENT_TEST) for p in c.files()) and "GOLDSRC" in c.tree_text()
                    and not re.search(r"# M\d+\b", c.tree_text())]
        self.assertEqual(len(validity), 2)
        for _, ex in validity:
            self.assertIn(AGENT_TEST, ex["argv"])
            self.assertIn(EXIST, ex["argv"])
            self.assertNotIn(GOLD_TEST, ex["argv"])
        base = [(c, ex) for c, ex in self.execs(world) if any("BASEEXIST" in t for t in c.files().values())]
        self.assertEqual(len(base), 1)
        self.assertIn(EXIST, base[0][1]["argv"])
        self.assertNotIn(AGENT_TEST, base[0][1]["argv"])
        for cont, ex in self.execs(world):
            if re.search(r"# M\d+\b", cont.tree_text()):
                self.assertIn(AGENT_TEST, ex["argv"])
                self.assertNotIn(GOLD_TEST, ex["argv"])

    def test_O16_F6_metrics_come_from_the_entry_files(self):
        result, _, _ = self.go(WorldV5())
        self.assertEqual(result["questions"], 3)
        self.assertEqual(result["corrections"], 1)
        self.assertEqual(result["cost_usd"], 0.75)
        self.assertEqual(result["wall_s"], 3.5)
        self.assertEqual(result["ambiguity"], {"n": 1, "correct": 1, "rate": 1.0})
        sr = result["self_report"]
        self.assertEqual((sr["mutants"], sr["killed"], sr["survived"], sr["equivalent"], sr["overturned"]),
                         (40, 31, 9, 6, 1))
        self.assertEqual((sr["fuzz_execs"], sr["fuzz_violations"]), (5000, 1))
        self.assertEqual(sr["rate"], 31 / 40)

    def test_O16_F6_self_report_rate_is_none_when_the_last_marker_has_no_mutants(self):
        events = [{"event": "verification_result", "fuzz_execs": 0, "fuzz_violations": 0, "mutants": 0, "killed": 0,
                   "survived": 0, "equivalent": 0, "overturned": 0}]
        result, _, _ = self.go(WorldV5(telemetry=events))
        self.assertIsNone(result["self_report"]["rate"])

    def test_O16_F6_self_report_is_none_without_a_marker(self):
        result, _, _ = self.go(WorldV5(telemetry=[{"event": "workflow_start"}]))
        self.assertIsNone(result["self_report"])

    def test_O16_F6_counts_with_no_usersim_rows(self):
        result, _, _ = self.go(WorldV5(ask=0, idle=()))
        self.assertEqual((result["questions"], result["corrections"]), (0, 0))

    def test_O16_F6_hidden_build_error_and_timeout_are_inconclusive_not_failures(self):
        for override, status in ((None, "inconclusive"), ("timeout", "inconclusive")):
            world = WorldV5(hidden_override=override)
            world.hidden_override = override
            world.policy_override = True
            result = self.hidden(world, override)
            with self.subTest(status=status):
                self.assertEqual(result["hidden"]["status"], status)
                self.assertIsNot(result["hidden"].get("resolved"), True)
                self.assertGreater(result["validity"]["n"], 0)

    def hidden(self, world, override):
        original = world.policy

        def policy(c):
            if any(p.endswith(GOLD_TEST) for p in c.files()):
                return override
            return original(c)
        world.docker.junit_policy = policy
        result, _, _ = self.go(world)
        return result

    def test_O31_final_error_entry_starts_no_container_and_keeps_cost_and_wall(self):
        world = WorldV5(state_status="error")
        result, _, _ = self.go(world)
        self.assertEqual((result["cost_usd"], result["wall_s"]), (0.75, 3.5))
        self.assertEqual(world.docker.runs, 0)
        self.assertIsNot(result["hidden"].get("resolved"), True)


if __name__ == "__main__":
    unittest.main()

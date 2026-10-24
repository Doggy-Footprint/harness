import copy
import json
import re
import unittest
from pathlib import Path
from unittest import mock

from evaluation.pr_test_quality import pilot, usersim
from evaluation.pr_test_quality.tests.fakes import FakeCall, spec_cfg, udiff, LANG_FIXTURES
from evaluation.pr_test_quality.tests.test_pipeline import DESIDERATA, Pipe, TASK_ID


def sel(language, repo, pr, brief_status="ok", valid=True, pilot_flag=False):
    owner, name = repo.split("/")
    return {"task_id": "%s__%s-%d" % (owner, name, pr), "language": language, "repo": repo, "pr": pr, "valid": valid,
            "pilot": pilot_flag, "brief": None if brief_status is None else {"status": brief_status}}


def ids(rows):
    return [(r["repo"], r["pr"]) for r in rows]


class Selection(unittest.TestCase):
    def pick(self, rows, language="python"):
        out = pilot.select({language: rows}, spec_cfg())
        return [r for r in out if r["language"] == language]

    def test_O22_F5_repos_ordered_by_selectable_count_then_name_first_two_tasks_by_pr_number(self):
        rows = [sel("python", "o/b", 30), sel("python", "o/b", 2), sel("python", "o/b", 10),
                sel("python", "o/a", 7), sel("python", "o/a", 5),
                sel("python", "o/c", 1), sel("python", "o/c", 2), sel("python", "o/c", 3), sel("python", "o/c", 4)]
        self.assertEqual(ids(self.pick(rows)), [("o/c", 1), ("o/c", 2), ("o/b", 2), ("o/b", 10)])

    def test_O22_F5_numeric_pr_order_not_lexicographic(self):
        rows = [sel("python", "o/a", 100), sel("python", "o/a", 9), sel("python", "o/a", 20)]
        self.assertEqual(ids(self.pick(rows)), [("o/a", 9), ("o/a", 20)])

    def test_O22_F5_dropped_brief_invalid_and_pilot_tasks_are_not_selectable_and_not_counted(self):
        rows = [sel("python", "o/a", 1, brief_status="dropped"), sel("python", "o/a", 2, brief_status="dropped"),
                sel("python", "o/a", 3, brief_status="dropped"), sel("python", "o/a", 4),
                sel("python", "o/b", 1), sel("python", "o/b", 2, valid=False), sel("python", "o/b", 3),
                sel("python", "o/c", 1, brief_status=None), sel("python", "o/c", 2, pilot_flag=True)]
        self.assertEqual(ids(self.pick(rows)), [("o/b", 1), ("o/b", 3), ("o/a", 4)])

    def test_O22_F5_count_ties_are_broken_by_repo_name(self):
        rows = [sel("python", r, p) for r in ("o/z", "o/m", "o/a") for p in (1, 2)]
        self.assertEqual(ids(self.pick(rows)), [("o/a", 1), ("o/a", 2), ("o/m", 1), ("o/m", 2)])

    def test_O22_F5_h_runs_only_on_the_first_selected_task_of_the_first_repo(self):
        rows = [sel("python", "o/b", 4), sel("python", "o/b", 3), sel("python", "o/a", 9)]
        picked = self.pick(rows)
        self.assertEqual(ids(picked), [("o/b", 3), ("o/b", 4), ("o/a", 9)])
        self.assertEqual([("H" in p["pilot_arms"]) for p in picked], [True, False, False])
        for p in picked:
            self.assertTrue({"B0", "Bplus"} <= set(p["pilot_arms"]))

    def test_O22_F5_each_language_gets_its_own_h_entry(self):
        by = {lang: [sel(lang, "o/a", 1), sel(lang, "o/a", 2)] for lang in ("python", "go")}
        picked = pilot.select(by, spec_cfg())
        self.assertEqual(sum("H" in p["pilot_arms"] for p in picked), 2)

    def test_O22_F5_nothing_selectable_gives_nothing(self):
        self.assertEqual(self.pick([sel("python", "o/a", 1, brief_status="dropped")]), [])


class PilotGates(Pipe):
    def setUp(self):
        super().setUp()
        self.stage("mutants")
        self.resolved_prs = set()
        self.leak_rows = False
        self.human_low_prs = set()
        self.inconsistent_prs = set()
        self.docker.agent_state = self.agent_state

    def write_tasks(self, valid_prs, invalid_prs=(), repos=None):
        base = self.tasks()[0]
        rows = []
        layout = repos or {1: "own/a", 2: "own/a", 3: "own/b", 4: "own/b"}
        for pr in list(valid_prs) + list(invalid_prs):
            row = copy.deepcopy(base)
            repo = layout.get(pr, "own/c")
            owner, name = repo.split("/")
            row.update({"task_id": "%s__%s-%d" % (owner, name, pr), "repo": repo, "pr": pr, "pilot": False,
                        "mutants": []})
            if pr in valid_prs:
                row["brief"] = dict(base["brief"], request="Please add clamp (TM%d;). Implement this and add automated tests." % pr)
            else:
                row.update({"valid": False, "reason": "no_f2p", "brief": None})
            rows.append(row)
        (self.data() / "tasks" / "python" / "tasks.jsonl").write_text(
            "".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")

    def agent_state(self, container):
        prompt = container.driver_inputs[0]["prompt"] if container.driver_inputs else ""
        match = re.search(r"TM(\d+);", prompt)
        if not match:
            return None
        pr = int(match.group(1))
        fx = LANG_FIXTURES["python"]
        state = {"tests/test_agent_x.py": (None, "def test_agent_x():\n    assert 1 == 1\n")}
        if pr in self.resolved_prs and "/workflow-approach" not in prompt:
            state[fx["src_path"]] = (fx["src_old"], fx["src_new"])
        return state

    def judge(self):
        def respond(prompt):
            first_task = "TM1;" in prompt
            pair = prompt.count("def test_agent_x") + prompt.count("def test_clamp_upper_bound_zq") >= 2
            if pair:
                if first_task and 1 in self.inconsistent_prs:
                    return json.dumps({"winner": "first"})
                return json.dumps({"winner": "tie"})
            human = "test_clamp_upper_bound_zq" in prompt
            quote = "def test_clamp_upper_bound_zq():" if human else "def test_agent_x():"
            value = 2 if (human and first_task and 1 in self.human_low_prs) else (5 if human else 4)
            if human and not (first_task and 1 in self.human_low_prs):
                value = 5
            return json.dumps({
                "smells": [], "desiderata": {k: {"score": value, "rationale": "r", "quote": quote} for k in DESIDERATA},
                "coverage": {"S1": {"level": "none", "quote": ""}, "S2": {"level": "none", "quote": ""}},
                "boundary": False, "error_path": False})
        return FakeCall([respond])

    def run_pilot(self):
        events = self.leak_rows

        class Rec:
            def __init__(rec, container, task, record_path, *, call_fn, cfg, token):
                rec.path = Path(record_path)

            def start(rec):
                if events:
                    rec.path.parent.mkdir(parents=True, exist_ok=True)
                    rows = [{"n": 1, "kind": "idle", "reason": "leak", "fallbacks": {"message": "leak"}},
                            {"n": 2, "kind": "ask", "reason": "ok", "fallbacks": {}}]
                    rec.path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")

            def stop(rec):
                pass
        with mock.patch.object(usersim, "Relay", Rec):
            code, out = self.inv(["pilot", "--language", "python"], call_fn=self.judge())
        self.assertEqual(code, 0, out)
        rid = self.run_ids()[-1]
        data = json.loads((Path(self.cfg_["results_dir"]) / (rid + ".json")).read_text())
        return data["pilot_gates"], data

    def test_O22_F4_all_gates_pass_with_hand_counted_inputs(self):
        self.write_tasks([1, 2, 3, 4], invalid_prs=[5, 6, 7, 8])
        self.resolved_prs = {1, 2}
        gates, data = self.run_pilot()
        self.assertEqual(gates["G1"]["value"], 0.5)
        self.assertTrue(gates["G1"]["pass"])
        self.assertEqual(gates["G2"]["value"], 0.5)
        self.assertTrue(gates["G2"]["pass"])
        self.assertEqual(gates["G3"]["value"], 1.0)
        self.assertEqual(gates["G4"]["value"], 0.0)
        self.assertEqual(gates["G5"]["value"], 0)
        self.assertTrue(all(g["pass"] for g in gates.values()))
        self.assertEqual(len([e for e in data["entries"] if e["arm"] == "B0"]), 4)

    def test_O22_F4_one_valid_candidate_of_four_fails_g2_and_all_resolved_fails_g1(self):
        self.write_tasks([1], invalid_prs=[2, 3, 4])
        self.resolved_prs = {1}
        gates, _ = self.run_pilot()
        self.assertEqual(gates["G2"]["value"], 0.25)
        self.assertFalse(gates["G2"]["pass"])
        self.assertEqual(gates["G1"]["value"], 1.0)
        self.assertFalse(gates["G1"]["pass"])

    def test_O22_F4_inconsistent_judge_pairs_and_anchor_ranks_and_leak_rows(self):
        self.write_tasks([1, 2, 3, 4])
        self.inconsistent_prs = {1}
        self.human_low_prs = {1}
        self.leak_rows = True
        gates, _ = self.run_pilot()
        self.assertEqual(gates["G3"]["value"], 0.5)
        self.assertFalse(gates["G3"]["pass"])
        self.assertEqual(gates["G4"]["value"], 0.25)
        self.assertTrue(gates["G4"]["pass"])
        self.assertEqual(gates["G5"]["value"], 9)
        self.assertFalse(gates["G5"]["pass"])

    def test_O22_F20_leak_count_covers_reason_leak_and_any_fallback_leak_once_per_row(self):
        self.write_tasks([1])
        rows = [{"n": 1, "kind": "idle", "reason": "leak", "fallbacks": {}},
                {"n": 2, "kind": "ask", "reason": "timeout", "fallbacks": {"Which?": "leak"}},
                {"n": 3, "kind": "idle", "reason": "leak", "fallbacks": {"message": "leak"}},
                {"n": 4, "kind": "idle", "reason": "format", "fallbacks": {"message": "format"}},
                {"n": 5, "kind": "ask", "reason": "ok", "fallbacks": {}}]

        class Rec:
            def __init__(rec, container, task, record_path, *, call_fn, cfg, token):
                rec.path = Path(record_path)

            def start(rec):
                rec.path.parent.mkdir(parents=True, exist_ok=True)
                if "H-r1" in str(rec.path):
                    rec.path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")

            def stop(rec):
                pass
        with mock.patch.object(usersim, "Relay", Rec):
            code, out = self.inv(["pilot", "--language", "python"], call_fn=self.judge())
        self.assertEqual(code, 0, out)
        rid = self.run_ids()[-1]
        gates = json.loads((Path(self.cfg_["results_dir"]) / (rid + ".json")).read_text())["pilot_gates"]
        self.assertEqual(gates["G5"]["value"], 3)
        self.assertFalse(gates["G5"]["pass"])

    def test_O22_F4_anchor_lowest_everywhere_fails_g4(self):
        self.write_tasks([1, 2])
        self.human_low_prs = {1}
        gates, _ = self.run_pilot()
        self.assertEqual(gates["G4"]["value"], 0.5)
        self.assertTrue(gates["G4"]["pass"])


if __name__ == "__main__":
    unittest.main()

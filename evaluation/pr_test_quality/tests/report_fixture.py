import json
from pathlib import Path

from evaluation.pr_test_quality.tests.fakes import make_task

DESIDERATA = ("isolated", "composable", "readable", "behavioral", "structure_insensitive", "specific", "predictive",
              "writable")
REPOS = ["own/r%d" % i for i in range(4)]


def task_ids():
    out = []
    for r, repo in enumerate(REPOS):
        for k in range(3):
            owner, name = repo.split("/")
            out.append((repo, "%s__%s-%d" % (owner, name, 10 + k)))
    return out


def score(key, *, resolved, f2p, nk, rk, far, amb, cost, wall, flagged=False, hidden_status="ok", valid=2, questions=1,
          validity_n=None, null_validity=False):
    hidden = {"status": hidden_status}
    if hidden_status == "ok":
        hidden.update({"resolved": resolved, "f2p_frac": f2p, "p2p_broken": []})
    return {
        "entry": key, "hidden": hidden,
        "validity": None if null_validity else {
            "n": valid if validity_n is None else validity_n, "valid": ["v%d" % i for i in range(valid)],
            "false_alarm": [], "incompatible": [], "flaky": [], "false_alarm_rate": far},
        "kill": {"executed": 12, "killed": 6, "raw": rk, "normalized": nk, "killed_ids": [], "d_ref_n": 9 if flagged else 12,
                 "flagged": flagged},
        "ambiguity": {"n": 2, "correct": round(amb * 2), "rate": amb},
        "cost_usd": cost, "wall_s": wall, "questions": questions, "corrections": 0, "self_report": None,
    }


def absolute(smells, score_value, levels, boundary=True, error_path=False, quote="q"):
    return {
        "smells": [{"smell": s, "test": "t", "quote": quote} for s in smells],
        "desiderata": {d: {"score": score_value, "rationale": "r", "quote": quote} for d in DESIDERATA},
        "coverage": {sid: {"level": lvl, "quote": "" if lvl == "none" else quote} for sid, lvl in levels.items()},
        "boundary": boundary, "error_path": error_path, "label": "T"}


def build(root, *, h_cost=8.0, error_entries=(), inconclusive=(), judge_errors=0, repeats=2, run_id="fixrun",
          all_resolved=False, quote="q", usersim_text="", validity_n=None, valid_count=2, null_validity=(),
          error_questions=0, h_questions=1, error_arm="H"):
    """Hand-written run: 4 repos x 3 tasks, arms B0 and H, 2 repeats. Per-task numbers are constant by design."""
    run_dir = Path(root) / "runs" / run_id
    run_dir.mkdir(parents=True)
    tasks = task_ids()
    entries, snapshot = [], []
    for index, (repo, tid) in enumerate(tasks):
        task = make_task("python", repo=repo, pr=10 + index % 3)
        task["task_id"] = tid
        task["brief"] = {"request": "r", "statements": [{"id": "S1", "text": "a", "f2p": ["x"]},
                                                         {"id": "S2", "text": "b", "f2p": ["y"]}],
                         "ambiguous": ["S1"], "status": "ok", "attempts": 1, "reason": "ok"}
        snapshot.append(task)
        flagged = index in (10, 11)
        for arm in ("B0", "H"):
            for rep in (1, 2):
                key = "%s-r%d" % (arm, rep)
                status = "error" if (tid, key) in error_entries else "completed"
                entries.append({"task_id": tid, "arm": arm, "repeat": rep, "status": status,
                                "attempts": 2 if status == "error" else 1})
                if arm == "B0":
                    nk, rk, far = (0.0, 0.1, 0.0) if rep == 1 else (0.4, 0.3, 0.2)
                    res = rep == 1 or all_resolved
                    amb, cost, wall = 0.5, 1.0, 100.0
                else:
                    nk, rk, far = (0.5, 0.3, 0.3) if rep == 1 else (0.7, 0.5, 0.5)
                    res, amb, cost, wall = True, 1.0, h_cost, 250.0
                if flagged:
                    nk = 0.0 if arm == "H" else 1.0
                hidden_status = "inconclusive" if (tid, key) in inconclusive else "ok"
                data = score(key, resolved=res, f2p=1.0 if res else 0.0, nk=nk, rk=rk, far=far, amb=amb, cost=cost,
                             wall=wall, flagged=flagged, hidden_status=hidden_status, valid=valid_count,
                             validity_n=validity_n, questions=h_questions if arm == "H" else 1,
                             null_validity=(tid, key) in null_validity)
                if status == "error":
                    data = {"entry": key, "hidden": {"status": "skipped"}, "validity": None, "kill": None,
                            "ambiguity": None, "cost_usd": cost, "wall_s": wall, "questions": error_questions, "corrections": 0,
                            "self_report": None}
                entry = run_dir / tid / key
                (entry / "raw" / "telemetry").mkdir(parents=True)
                (entry / "score.json").write_text(json.dumps(data), encoding="utf-8")
                (entry / "state.json").write_text(json.dumps({"status": status, "reason": None, "session_id": "s",
                                                              "results": [], "rate_limit": None}), encoding="utf-8")
                (entry / "manifest.json").write_text(json.dumps({"task_id": tid, "arm": arm, "repeat": rep,
                                                                 "attempts": 2 if status == "error" else 1}), encoding="utf-8")
                (entry / "usersim.jsonl").write_text(usersim_text, encoding="utf-8")
    prereg = Path(root) / "preregistration.md"
    prereg.write_text("# prereg\n", encoding="utf-8")
    import hashlib
    run = {"run_id": run_id, "phase": "dev", "prereg_sha256": hashlib.sha256(prereg.read_bytes()).hexdigest(),
           "prereg_path": str(prereg), "created_at": 1.0, "params": {"harness_ref": "HEAD", "harness_commit": None,
                                                                    "model": "claude-sonnet-5-5", "effort": "medium",
                                                                    "cap_min": 180},
           "repeats": repeats, "arms": ["B0", "H"], "entries": entries, "halted": None}
    (run_dir / "run.json").write_text(json.dumps(run), encoding="utf-8")
    (run_dir / "tasks.jsonl").write_text("".join(json.dumps(t) + "\n" for t in snapshot), encoding="utf-8")
    for index, (repo, tid) in enumerate(tasks):
        human_score = 2 if index < 3 else 5
        labels = {"T1": "human", "T2": "B0-r1", "T3": "H-r1", "T4": "B0-r2", "T5": "H-r2"}
        absolute_items = {
            "T1": absolute(["assertion_roulette", "eager_test"], human_score, {"S1": "covered", "S2": "covered"}, quote=quote),
            "T2": absolute(["magic_number"], 3, {"S1": "covered", "S2": "none"}, quote=quote),
            "T3": absolute([], 4, {"S1": "covered", "S2": "covered"}, quote=quote),
            "T4": absolute(["magic_number"], 3, {"S1": "covered", "S2": "none"}, quote=quote),
            "T5": absolute([], 4, {"S1": "covered", "S2": "covered"}, quote=quote)}
        if index < judge_errors:
            absolute_items["T4"] = "error"
        pairwise = []
        r2 = "A" if index < 4 else ("B" if index < 6 else "tie")
        pairwise.append({"pair": "H-B0", "repeat": 1, "ab": "first", "ba": "second", "outcome": "A"})
        pairwise.append({"pair": "H-B0", "repeat": 2, "ab": "x", "ba": "y", "outcome": r2})
        if index < 6:
            pairwise.append({"pair": "H-Bplus", "repeat": 1, "ab": "first", "ba": "first", "outcome": "inconsistent"})
        (run_dir / tid / "judge.json").write_text(json.dumps({"absolute": absolute_items, "pairwise": pairwise,
                                                              "labels": labels}), encoding="utf-8")
    return run_dir, prereg

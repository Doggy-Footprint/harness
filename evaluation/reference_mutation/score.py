import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import crossarm, mutants, overlay, read_json, section, session_cost, testrun, validate, write_json

PASS = "pass"
FAILED = ("fail", "error")


def hidden_outcome(results: dict[str, str], f2p: list[str], p2p: list[str]) -> dict:
    passing = [t for t in f2p if results.get(t) == PASS]
    broken = sorted(t for t in p2p if results.get(t) != PASS)
    return {
        "resolved": len(passing) == len(f2p) and not broken,
        "f2p_frac": len(passing) / len(f2p) if f2p else 0.0,
        "p2p_broken": broken,
    }


def agent_test_ids(base_results: dict[str, str], agent_results: dict[str, str]) -> list[str]:
    return sorted(t for t in agent_results if t not in base_results)


def validity(runs: list[dict[str, str]], agent_ids: list[str]) -> dict:
    valid, false_alarm, incompatible, flaky, skipped = [], [], [], [], []
    for test_id in agent_ids:
        seen = {run.get(test_id) for run in runs}
        if seen == {PASS}:
            valid.append(test_id)
        elif seen == {"fail"}:
            false_alarm.append(test_id)
        elif seen == {"skip"}:
            skipped.append(test_id)
        elif seen <= {"error", None}:
            incompatible.append(test_id)
        else:
            flaky.append(test_id)
    denominator = len(valid) + len(false_alarm)
    return {
        "n": len(valid) + len(false_alarm) + len(incompatible) + len(flaky),
        "valid": valid, "false_alarm": false_alarm, "incompatible": incompatible, "flaky": flaky,
        "skipped": skipped, "false_alarm_rate": len(false_alarm) / denominator if denominator else None,
    }


def kill(mutant_runs: dict[str, dict], valid_ids: list[str], d_ref: set[str]) -> dict:
    executed = sorted(m for m, run in mutant_runs.items() if run.get("status") == "ok")
    killed = sorted(
        m for m in executed if any(mutant_runs[m]["results"].get(t) in FAILED for t in valid_ids)
    )
    if not executed:
        return {"executed": 0, "killed": 0, "raw": None, "normalized": None, "killed_ids": [],
                "d_ref_n": len(d_ref)}
    if not valid_ids:
        return {"executed": len(executed), "killed": 0, "raw": 0.0, "normalized": 0.0, "killed_ids": [],
                "d_ref_n": len(d_ref)}
    return {
        "executed": len(executed), "killed": len(killed), "raw": len(killed) / len(executed),
        "normalized": len(set(killed) & set(d_ref)) / len(d_ref) if d_ref else None,
        "killed_ids": killed, "d_ref_n": len(d_ref),
    }


def ambiguity_correct(results: dict[str, str], brief: dict) -> dict:
    by_id = {s["id"]: s for s in brief.get("statements", [])}
    ambiguous = [a for a in brief.get("ambiguous", []) if a in by_id]
    correct = sum(1 for a in ambiguous if all(results.get(t) == PASS for t in by_id[a]["f2p"]))
    return {"n": len(ambiguous), "correct": correct, "rate": correct / len(ambiguous) if ambiguous else None}


def self_report(telemetry_events: list[dict]) -> dict | None:
    marks = [e for e in telemetry_events if e.get("event") in ("verification_result", "verification")]
    if not marks:
        return None
    last = marks[-1]
    counts = {k: last.get(k) for k in (
        "mutants", "killed", "survived", "equivalent", "overturned", "fuzz_execs", "fuzz_violations")}
    mutants_n, killed = counts["mutants"], counts["killed"]
    ok = isinstance(mutants_n, (int, float)) and mutants_n and isinstance(killed, (int, float))
    return {**counts, "rate": killed / mutants_n if ok else None}


def _telemetry_events(entry_dir: Path) -> list[dict]:
    events = []
    for path in sorted((entry_dir / "raw" / "telemetry").glob("*.jsonl")) if (entry_dir / "raw" / "telemetry").is_dir() else []:
        for line in path.read_text(errors="replace").splitlines():
            try:
                obj = json.loads(line)
            except ValueError:
                continue
            if isinstance(obj, dict):
                events.append(obj)
    return events


def _usersim_rows(entry_dir: Path) -> list[dict]:
    path = entry_dir / "usersim.jsonl"
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def _run(task, tree, selection, ctx, repeat=0):
    return testrun.run_tests(task, tree, selection, repeat=repeat, **ctx)


def _results(run: dict) -> dict:
    return run["results"] if run["status"] == "ok" else {}


def _costs(state: dict) -> tuple[float, float]:
    results = state.get("results") or []
    wall = state.get("elapsed_s") or sum((r.get("duration_ms") or 0) for r in results) / 1000
    return session_cost(results) or 0, wall


def _skipped(key: str, state: dict) -> dict:
    cost, wall = _costs(state)
    return {"entry": key, "hidden": {"status": "skipped"}, "validity": None, "kill": None, "ambiguity": None,
            "cost_usd": cost, "wall_s": wall, "questions": 0, "corrections": 0, "self_report": None}


def score_entry(task: dict, entry_dir, *, docker, cfg: dict, cache_dir) -> dict:
    entry_dir = Path(entry_dir)
    key = entry_dir.name
    ctx = {"docker": docker, "cfg": cfg, "cache_dir": cache_dir}
    state = read_json(entry_dir / "state.json", {})
    agent = read_json(entry_dir / "split.json")
    language = task["language"]
    gold = validate.gold_entry(task)
    if agent is None or state.get("status") not in ("completed", "stalled", "capped"):
        out = _skipped(key, state)
        write_json(entry_dir / "score.json", out, indent=1, sort_keys=True)
        return out
    out = _skipped(key, state)
    gold_sel = validate.gold_selection(task)
    hidden = _run(task, overlay.hidden_tree(language, gold, agent), gold_sel, ctx)
    out["hidden"] = (
        {"status": "ok", **hidden_outcome(hidden["results"], task["f2p"], task["p2p"])}
        if hidden["status"] == "ok" else {"status": "inconclusive"}
    )
    out["ambiguity"] = (
        ambiguity_correct(hidden["results"], task["brief"]) if hidden["status"] == "ok" and task.get("brief") else None
    )
    selection = crossarm.test_selection(agent)
    empty = {"status": "ok", "results": {}, "runtime_s": 0}
    base_tree = {p: agent["base"].get(p) for p in selection}
    base_selection = [p for p in selection if agent["base"].get(p) is not None]
    base_agent = _run(task, base_tree, base_selection, ctx) if base_selection else empty
    vtree = overlay.validity_tree(language, gold, agent)
    vruns = [_run(task, vtree, selection, ctx, repeat=k) for k in range(2)] if selection else []
    valid_ids: list[str] = []
    if not selection:
        out["validity"] = validity([{}], [])
    elif vruns and base_agent["status"] == "ok" and all(r["status"] == "ok" for r in vruns):
        ids = agent_test_ids(base_agent["results"], vruns[0]["results"])
        out["validity"] = validity([r["results"] for r in vruns], ids)
        valid_ids = out["validity"]["valid"]
    rows = _usersim_rows(entry_dir)
    out["questions"] = sum(1 for r in rows if r.get("kind") == "ask")
    out["corrections"] = sum(1 for r in rows if r.get("kind") == "idle" and r.get("contradiction"))
    out["self_report"] = self_report(_telemetry_events(entry_dir))
    if out["validity"] is None:
        write_json(entry_dir / "score.json", out, indent=1, sort_keys=True)
        return out
    d_ref = {m["id"] for m in task.get("mutants", []) if m.get("gold") == "killed"}
    sampled = [m for m in task.get("mutants", []) if m.get("gold") in ("killed", "survived")]
    mutant_runs = {m["id"]: {"status": "ok", "results": {}} for m in sampled} if not valid_ids else {}
    if valid_ids:
        def run_mutant(m):
            try:
                mutated = mutants.apply_diff(task["gold_after"][m["path"]], m["diff"])
            except (KeyError, ValueError):
                return None
            r = _run(task, {**vtree, m["path"]: mutated}, selection, ctx)
            return {"status": r["status"], "results": r["results"]}

        # Each mutant runs in its own container; sequential runs leave the VM idle for hours on slow suites.
        with ThreadPoolExecutor(max_workers=max(1, section(cfg, "mutants").get("workers", 1))) as pool:
            for m, r in zip(sampled, pool.map(run_mutant, sampled)):
                if r is not None:
                    mutant_runs[m["id"]] = r
    min_mutants = section(cfg, "report").get("min_mutants", 10)
    out["kill"] = {**kill(mutant_runs, valid_ids, d_ref), "flagged": len(d_ref) < min_mutants}
    write_json(entry_dir / "score.json", out, indent=1, sort_keys=True)
    return out


def score_run(run_dir, tasks: dict[str, dict], *, docker, cfg: dict, cache_dir) -> list[dict]:
    run_dir = Path(run_dir)
    meta = read_json(run_dir / "run.json", {})
    scores = []
    for entry in meta.get("entries", []):
        task = tasks.get(entry["task_id"])
        d = run_dir / entry["task_id"] / f"{entry['arm']}-r{entry['repeat']}"
        if task is None or not d.is_dir():
            continue
        scores.append(score_entry(task, d, docker=docker, cfg=cfg, cache_dir=cache_dir))
    return scores

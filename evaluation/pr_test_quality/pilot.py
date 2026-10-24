from pathlib import Path

from . import (
    compose, crossarm, data_dir, judge, read_json, read_jsonl, results_dir, run as run_mod, score, section,
    tasks_path, write_json, write_jsonl,
)
from .languages import LANGUAGES

GATE_DEFAULTS = {
    "g1_max_b0_resolved": 0.80,
    "g2_min_valid": 0.50,
    "g3_min_consistency": 0.70,
    "g4_max_anchor_lowest": 0.50,
    "g5_max_failures": 0,
}


def _usable(task: dict) -> bool:
    brief = task.get("brief")
    return (
        bool(task.get("valid")) and isinstance(brief, dict) and brief.get("status") == "ok"
        and not task.get("pilot")
    )


def _pr_number(task: dict) -> int:
    return int(task["pr"]) if task.get("pr") is not None else int(task["task_id"].rsplit("-", 1)[-1])


def select(tasks: dict[str, list[dict]], cfg: dict) -> list[dict]:
    pcfg = section(cfg, "pilot")
    repos_n, tasks_n = pcfg.get("repos_per_language", 2), pcfg.get("tasks_per_repo", 2)
    chosen: list[dict] = []
    for language in sorted(tasks):
        by_repo: dict[str, list[dict]] = {}
        for task in tasks[language]:
            if _usable(task):
                by_repo.setdefault(task["repo"], []).append(task)
        ranked = sorted(by_repo, key=lambda r: (-len(by_repo[r]), r))[:repos_n]
        picked = [t for repo in ranked for t in sorted(by_repo[repo], key=_pr_number)[:tasks_n]]
        for k, task in enumerate(picked):
            chosen.append({**task, "pilot": True, "pilot_arms": ["B0", "Bplus", "H"] if k == 0 else ["B0", "Bplus"]})
    return chosen


def _gate(value, threshold, ok) -> dict:
    return {"pass": value is not None and ok(value), "value": value, "threshold": threshold}


def gates(metrics: dict, cfg: dict) -> dict[str, dict]:
    t = {**GATE_DEFAULTS, **section(cfg, "gates")}
    rates = metrics.get("candidate_valid_rate") or {}
    g2_value = min(rates.values()) if rates else None
    failures = None
    if metrics.get("leak_fallbacks") is not None and metrics.get("token_hits") is not None:
        failures = metrics["leak_fallbacks"] + metrics["token_hits"]
    return {
        "G1": _gate(metrics.get("b0_resolved_rate"), t["g1_max_b0_resolved"], lambda v: v <= t["g1_max_b0_resolved"]),
        "G2": _gate(g2_value, t["g2_min_valid"], lambda v: v >= t["g2_min_valid"]),
        "G3": _gate(metrics.get("judge_consistency"), t["g3_min_consistency"], lambda v: v >= t["g3_min_consistency"]),
        "G4": _gate(metrics.get("anchor_lowest_share"), t["g4_max_anchor_lowest"], lambda v: v <= t["g4_max_anchor_lowest"]),
        "G5": _gate(failures, t["g5_max_failures"], lambda v: v <= t["g5_max_failures"]),
    }


def _entry_dirs(run_dir: Path, task_id: str) -> list[Path]:
    root = run_dir / task_id
    return sorted(p for p in root.iterdir() if p.is_dir()) if root.is_dir() else []


def cross_all(run_dir, tasks: dict[str, dict], *, docker, cfg: dict, cache_dir) -> None:
    run_dir = Path(run_dir)
    for task_id, task in sorted(tasks.items()):
        dirs = _entry_dirs(run_dir, task_id)
        scores = {d.name: read_json(d / "score.json") or {} for d in dirs}
        matrix = crossarm.run_matrix(task, dirs, docker=docker, cfg=cfg, cache_dir=cache_dir)
        resolved = {n: bool((s.get("hidden") or {}).get("resolved")) for n, s in scores.items()}
        valid = {n: (s.get("validity") or {}).get("valid", []) for n, s in scores.items()}
        write_json(run_dir / task_id / "crossarm.json", {
            "detection": crossarm.detection(matrix, resolved, valid),
            "matrix": {f"{t}|{i}": r["status"] for (t, i), r in sorted(matrix.items())},
        }, indent=1, sort_keys=True)


def judge_all(run_dir, tasks: dict[str, dict], *, call_fn, cfg: dict) -> None:
    run_dir = Path(run_dir)
    for task_id, task in sorted(tasks.items()):
        entries = []
        for d in _entry_dirs(run_dir, task_id):
            state, split = read_json(d / "state.json", {}), read_json(d / "split.json")
            if not split:
                continue
            arm, _, repeat = d.name.rpartition("-r")
            entries.append({
                "key": d.name, "arm": arm, "repeat": int(repeat), "status": state.get("status"),
                "text": split["split"]["tests"],
                "spec_ids": sorted(judge.spec_ids(split["split"]["harness"])),
            })
        if entries and task.get("brief"):
            write_json(run_dir / task_id / "judge.json",
                       judge.judge_task(task, entries, call_fn=call_fn, cfg=cfg), indent=1, sort_keys=True)


def score_all(run_dir, tasks: dict[str, dict], *, docker, cfg: dict, cache_dir) -> list[dict]:
    scores = score.score_run(run_dir, tasks, docker=docker, cfg=cfg, cache_dir=cache_dir)
    cross_all(run_dir, tasks, docker=docker, cfg=cfg, cache_dir=cache_dir)
    return scores


def mark_pilot(cfg: dict, selected: list[dict]) -> None:
    ids = {t["task_id"] for t in selected}
    for language in LANGUAGES:
        path = tasks_path(cfg, language)
        rows = read_jsonl(path)
        if rows:
            write_jsonl(path, [{**r, "pilot": r["task_id"] in ids or r.get("pilot", False)} for r in rows])


def run_pilot(cfg: dict, *, docker, call_fn, prereg_path, token: str, harness_ref: str = "HEAD", languages=None) -> tuple[Path, Path, Path]:
    by_language = {
        language: read_jsonl(tasks_path(cfg, language)) for language in (languages or LANGUAGES)
    }
    selected = select(by_language, cfg)
    if not selected:
        raise run_mod.Refused(
            "no valid tasks for the pilot; run python3 -m evaluation.pr_test_quality mine/build/validate/brief first"
        )
    mark_pilot(cfg, selected)
    run_dir = run_mod.run(
        selected, list(compose.ARMS), cfg=cfg, phase="pilot", repeats=1, docker=docker, call_fn=call_fn,
        prereg_path=prereg_path, harness_ref=harness_ref,
    )
    return finish_pilot(run_dir, selected, cfg=cfg, docker=docker, call_fn=call_fn, prereg_path=prereg_path, token=token)


def finish_pilot(run_dir, selected, *, cfg, docker, call_fn, prereg_path, token):
    from . import report

    tasks = {t["task_id"]: t for t in selected}
    cache_dir = data_dir(cfg) / "cache"
    score_all(run_dir, tasks, docker=docker, cfg=cfg, cache_dir=cache_dir)
    judge_all(run_dir, tasks, call_fn=call_fn, cfg=cfg)
    built = report.build(run_dir, prereg_path=prereg_path, cfg=cfg)
    return (Path(run_dir), *report.write(built, results_dir(cfg), token=token))

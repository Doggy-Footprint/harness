import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import languages, overlay, section, testrun, validate

FAILED = ("fail", "error")


def _tests_fail(results: dict, valid_ids: list[str]) -> bool:
    return any(results.get(t) in FAILED for t in valid_ids)


def detection(matrix: dict[tuple[str, str], dict], resolved: dict[str, bool], valid: dict[str, list[str]]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for tests_entry in sorted({t for t, _ in matrix}):
        buggy_n = detected = correct_n = alarmed = inconclusive = 0
        for (t, impl), run in sorted(matrix.items()):
            if t != tests_entry or impl == tests_entry:
                continue
            if run.get("status") != "ok":
                inconclusive += 1
                continue
            fails = _tests_fail(run.get("results", {}), valid.get(tests_entry, []))
            if resolved.get(impl):
                correct_n += 1
                alarmed += fails
            else:
                buggy_n += 1
                detected += fails
        out[tests_entry] = {
            "buggy_n": buggy_n, "detected": detected,
            "detection_rate": detected / buggy_n if buggy_n else None,
            "correct_n": correct_n, "alarmed": alarmed,
            "false_alarm_rate": alarmed / correct_n if correct_n else None,
            "inconclusive": inconclusive,
        }
    return out


def _agent(entry_dir) -> dict | None:
    path = Path(entry_dir) / "split.json"
    return json.loads(path.read_text()) if path.is_file() else None


IMPL_STATUSES = ("completed", "stalled", "capped")


def _completed(entry_dir) -> bool:
    path = Path(entry_dir) / "state.json"
    return path.is_file() and json.loads(path.read_text()).get("status") in IMPL_STATUSES


def test_selection(agent: dict) -> list[str]:
    return sorted({p.replace(languages.CFGTEST, "") for p in languages.diff_paths(agent["split"]["tests"])})


def run_matrix(task: dict, entry_dirs: list, *, docker, cfg: dict, cache_dir) -> dict[tuple[str, str], dict]:
    ready = {
        Path(d).name: _agent(d) for d in entry_dirs
        if _completed(d) and (json.loads((Path(d) / "manifest.json").read_text()).get("task_id", task["task_id"])
                              if (Path(d) / "manifest.json").is_file() else task["task_id"]) == task["task_id"]
    }
    gold = validate.gold_entry(task)
    cells = [(t, i) for t in sorted(ready) for i in sorted(ready)
             if i != t and ready[t] is not None and ready[i] is not None]

    def run_cell(cell):
        tests, impl = ready[cell[0]], ready[cell[1]]
        tree = overlay.cross_tree(task["language"], gold, impl, tests)
        result = testrun.run_tests(task, tree, test_selection(tests), docker=docker, cfg=cfg, cache_dir=cache_dir)
        return {"status": result["status"], "results": result["results"]}

    with ThreadPoolExecutor(max_workers=max(1, section(cfg, "mutants").get("workers", 1))) as pool:
        return dict(zip(cells, pool.map(run_cell, cells)))

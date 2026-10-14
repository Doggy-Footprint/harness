import json
from pathlib import Path

METRICS = (
    "resolved", "f2p_frac", "swt_success", "kill_primary", "kill_secondary", "incompatible_frac",
)
KILL_METRICS = ("kill_primary", "kill_secondary")
SMALL_SAMPLE_SUFFIX = " (참고용: 표본 작음)"
NOTE_NO_SIGNIFICANCE = (
    "통계적 유의성은 검정하지 않았다. 범위는 기준선 반복 실행의 최솟값과 최댓값이며 above/within/below는 "
    "그 범위와의 위치 관계일 뿐이다."
)
NOTE_SMALL_SAMPLE = (
    "표본이 작은 인스턴스(컴파일 가능한 변이 수가 기준 미만)의 kill 지표는 참고용이다."
)


class ReportError(Exception):
    pass


def _flag(value) -> float | None:
    return None if value is None else 1.0 if value else 0.0


def metric_values(score: dict | None) -> dict[str, float | None]:
    if not score:
        return {m: None for m in METRICS}
    swt, kill = score.get("swt") or {}, score.get("kill") or {}
    return {
        "resolved": _flag(score.get("resolved")),
        "f2p_frac": score.get("f2p_frac"),
        "swt_success": _flag(swt.get("success")),
        "kill_primary": kill.get("primary"),
        "kill_secondary": kill.get("secondary"),
        "incompatible_frac": score.get("incompatible_frac"),
    }


def verdict(value, baseline_values) -> str:
    present = [v for v in baseline_values if v is not None]
    if value is None or not present:
        return "n/a"
    if value > max(present):
        return "above"
    if value < min(present):
        return "below"
    return "within"


def _read_json(path: Path):
    return json.loads(path.read_text()) if path.is_file() else None


def _check_verdicts(process: dict | None) -> dict[str, str]:
    checks = (process or {}).get("checks") or {}
    return {
        cid: (c.get("verdict") if isinstance(c, dict) else c) for cid, c in sorted(checks.items(), key=lambda kv: (len(kv[0]), kv[0]))
    }


def _cost(state: dict | None) -> float | None:
    costs = [
        r["total_cost_usd"] for r in (state or {}).get("results") or []
        if isinstance(r, dict) and r.get("total_cost_usd") is not None
    ]
    return sum(costs) if costs else None


def build(
    run_dir: Path, *, fixture_dir: Path | None, scores: dict, processes: dict, min_mutants: int
) -> dict:
    run_dir = Path(run_dir)
    meta = _read_json(run_dir / "run.json")
    params = _read_json(run_dir / "params.json") or {}
    fixture_scores = {}
    fixture_manifest = None
    if fixture_dir is not None:
        fixture_dir = Path(fixture_dir)
        fixture_manifest = _read_json(fixture_dir / "manifest.json")
        fixture_scores = _read_json(fixture_dir / "scores.json") or {}

    instances = []
    for entry in meta["entries"]:
        if entry["arm"] != "harness":
            continue
        iid = entry["instance_id"]
        score = scores.get(iid)
        repeats = [r.get("score") for r in fixture_scores.get(iid, [])] if fixture_dir else []
        sampled = ((score or {}).get("kill") or {}).get("sampled")
        if score is None:
            sampled = next(
                ((s.get("kill") or {}).get("sampled") for s in repeats if s), None
            )
        harness = metric_values(score)
        baseline = [metric_values(s) for s in repeats]
        metrics = {}
        for m in METRICS:
            values = [b[m] for b in baseline]
            present = [v for v in values if v is not None]
            metrics[m] = {
                "harness": harness[m],
                "baseline": values,
                "range": [min(present), max(present)] if present else None,
                "verdict": verdict(harness[m], values),
            }
        state = _read_json(run_dir / iid / "harness" / "state.json")
        instances.append({
            "instance_id": iid,
            "status": entry["status"],
            "small_sample": sampled is not None and sampled < min_mutants,
            "metrics": metrics,
            "process": _check_verdicts(processes.get(iid)),
            "cost_usd": _cost(state),
            "elapsed_s": (state or {}).get("elapsed_s"),
        })
    notes = [NOTE_NO_SIGNIFICANCE]
    if any(i["small_sample"] for i in instances):
        notes.append(NOTE_SMALL_SAMPLE)
    return {
        "run_id": meta["run_id"],
        "harness_ref": params.get("harness_ref"),
        "harness_commit": params.get("harness_commit"),
        "fixture_id": (fixture_manifest or {}).get("fixture_id", fixture_dir.name) if fixture_dir else None,
        "baseline": "compared" if fixture_dir else "skipped",
        "instances": instances,
        "notes": notes,
    }


def _cell(value) -> str:
    return "n/a" if value is None else f"{value:.3f}" if isinstance(value, float) else str(value)


def render_markdown(report: dict) -> str:
    fixture = report["fixture_id"] if report["fixture_id"] else "baseline skipped"
    lines = [
        f"# selfcheck report {report['run_id']}",
        "",
        f"- harness ref: {report['harness_ref']}",
        f"- harness commit: {report['harness_commit']}",
        f"- fixture: {fixture}",
    ]
    for inst in report["instances"]:
        lines += ["", f"## {inst['instance_id']} ({inst['status']})", ""]
        lines += ["| metric | harness | baseline (per repeat) | range | verdict |", "| --- | --- | --- | --- | --- |"]
        for m in METRICS:
            row = inst["metrics"][m]
            name = m + SMALL_SAMPLE_SUFFIX if inst["small_sample"] and m in KILL_METRICS else m
            rng = "n/a" if row["range"] is None else f"[{_cell(row['range'][0])}, {_cell(row['range'][1])}]"
            base = ", ".join(_cell(v) for v in row["baseline"]) or "n/a"
            lines.append(f"| {name} | {_cell(row['harness'])} | {base} | {rng} | {row['verdict']} |")
        lines += ["", f"cost_usd: {_cell(inst['cost_usd'])}, elapsed_s: {_cell(inst['elapsed_s'])}", ""]
        lines += ["| check | verdict |", "| --- | --- |"]
        lines += [f"| {cid} | {v} |" for cid, v in inst["process"].items()]
    lines += ["", "## notes", ""]
    lines += [f"- {n}" for n in report["notes"]]
    return "\n".join(lines) + "\n"


def write(report: dict, results_dir: Path, *, token: str) -> tuple[Path, Path]:
    texts = {
        ".json": json.dumps(report, sort_keys=True, indent=1),
        ".md": render_markdown(report),
    }
    if token and any(token in t for t in texts.values()):
        raise ReportError("token found in report output; nothing written")
    results_dir = Path(results_dir)
    results_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for suffix, text in texts.items():
        path = results_dir / f"{report['run_id']}{suffix}"
        path.write_text(text)
        paths.append(path)
    return paths[0], paths[1]

import json
import statistics
from pathlib import Path

from .run import entry_dir, entry_repeat

METRICS = (
    "resolved", "f2p_frac", "swt_success", "kill_primary", "kill_secondary", "incompatible_frac",
)
KILL_METRICS = ("kill_primary", "kill_secondary")
FLAG_METRICS = ("resolved", "swt_success")
SMALL_SAMPLE_SUFFIX = " (참고용: 표본 작음)"
NOTE_NO_SIGNIFICANCE = (
    "통계적 유의성은 검정하지 않았다. 범위는 기준선 반복 실행의 최솟값과 최댓값이며 above/within/below는 "
    "그 범위와의 위치 관계일 뿐이다."
)
NOTE_SMALL_SAMPLE = (
    "표본이 작은 인스턴스(컴파일 가능한 변이 수가 기준 미만)의 kill 지표는 참고용이다."
)
NOTE_USER_SIM = (
    "시뮬레이션된 사용자는 모든 추천을 그대로 수락하므로 Ask 품질은 측정되지 않는다."
)
NOTE_PC5 = (
    "PC5는 오탐일 수 있다. 하네스 텔레메트리가 한 Bash 명령 안의 첫 번째 `seed.py` 호출만 기록하기 때문이다."
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


def _load_reviews(run_dir: Path, entries: list[dict]) -> dict[tuple[str, int], dict]:
    reviews = {}
    for entry in entries:
        path = entry_dir(run_dir, entry) / "review.json"
        if not path.is_file():
            continue
        try:
            obj = json.loads(path.read_text())
        except (OSError, ValueError):
            obj = None
        reviews[(entry["instance_id"], entry_repeat(entry))] = obj if isinstance(obj, dict) else {
            "status": "error", "error": "unreadable review.json",
        }
    return reviews


def _review_view(review: dict | None) -> tuple:
    if review is None:
        return "not run", {}
    if review.get("status") == "error":
        return f"error: {review.get('error')}", {}
    cats = review.get("categories") or {}
    return (
        {cat: c.get("verdict") for cat, c in cats.items()},
        {cat: c.get("findings") or [] for cat, c in cats.items()},
    )


def _summary(metric: str, values: list) -> dict | None:
    present = [v for v in values if v is not None]
    if not present:
        return None
    if metric in FLAG_METRICS:
        return {"k": sum(v == 1.0 for v in present), "n": len(present)}
    return {"median": statistics.median(present), "min": min(present), "max": max(present)}


def _summary_cell(summary: dict | None) -> str:
    if summary is None:
        return "n/a"
    if "k" in summary:
        return f"{summary['k']}/{summary['n']}"
    return f"{_cell(summary['median'])} [{_cell(summary['min'])}, {_cell(summary['max'])}]"


def build(
    run_dir: Path, *, fixture_dir: Path | None, scores: dict, processes: dict, min_mutants: int,
    reviews: dict | None = None,
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

    harness_entries = [e for e in meta["entries"] if e["arm"] == "harness"]
    if reviews is None:
        reviews = _load_reviews(run_dir, harness_entries)
    grouped: dict[str, list[dict]] = {}
    for entry in harness_entries:
        grouped.setdefault(entry["instance_id"], []).append(entry)
    instances = []
    false_claims = []
    for iid, entries in grouped.items():
        entries = sorted(entries, key=entry_repeat)
        base_scores = [r.get("score") for r in fixture_scores.get(iid, [])] if fixture_dir else []
        rows = []
        for entry in entries:
            key = (iid, entry_repeat(entry))
            score = scores.get(key)
            state = _read_json(entry_dir(run_dir, entry) / "state.json")
            review = reviews.get(key)
            verdicts, findings = _review_view(review)
            if review is not None and review.get("status") == "ok":
                false_claims += [
                    {"instance_id": iid, "repeat": key[1], "category": fc.get("category"),
                     "summary": fc.get("summary"), "citation": fc.get("citation")}
                    for fc in review.get("false_claims") or []
                ]
            rows.append({
                "repeat": key[1],
                "status": entry["status"],
                "metrics": metric_values(score),
                "process": _check_verdicts(processes.get(key)),
                "cost_usd": _cost(state),
                "elapsed_s": (state or {}).get("elapsed_s"),
                "review": verdicts,
                "review_findings": findings,
                "score": score,
            })
        sampled = next(
            (((r["score"] or {}).get("kill") or {}).get("sampled") for r in rows
             if ((r["score"] or {}).get("kill") or {}).get("sampled") is not None),
            None,
        )
        if sampled is None:
            sampled = next(
                (((s or {}).get("kill") or {}).get("sampled") for s in base_scores if s), None
            )
        baseline = [metric_values(s) for s in base_scores]
        metrics = {}
        for m in METRICS:
            harness = [r["metrics"][m] for r in rows]
            values = [b[m] for b in baseline]
            present = [v for v in values if v is not None]
            summary = _summary(m, harness)
            median = statistics.median([v for v in harness if v is not None]) if summary else None
            verdicts = [verdict(v, values) for v in harness]
            metrics[m] = {
                "harness": harness,
                "harness_summary": summary,
                "baseline": values,
                "range": [min(present), max(present)] if present else None,
                "verdict": verdict(median, values),
                "repeat_verdicts": {
                    name: verdicts.count(name) for name in ("above", "within", "below", "n/a")
                },
            }
        cids = sorted({c for r in rows for c in r["process"]}, key=lambda c: (len(c), c))
        instances.append({
            "instance_id": iid,
            "small_sample": sampled is not None and sampled < min_mutants,
            "repeats": [{k: v for k, v in r.items() if k != "score"} for r in rows],
            "metrics": metrics,
            "process_fails": {
                c: sum(r["process"].get(c) == "fail" for r in rows) for c in cids
            },
        })
    notes = [NOTE_NO_SIGNIFICANCE, NOTE_USER_SIM, NOTE_PC5]
    if any(i["small_sample"] for i in instances):
        notes.append(NOTE_SMALL_SAMPLE)
    return {
        "run_id": meta["run_id"],
        "harness_ref": params.get("harness_ref"),
        "harness_commit": params.get("harness_commit"),
        "fixture_id": (fixture_manifest or {}).get("fixture_id", fixture_dir.name) if fixture_dir else None,
        "baseline": "compared" if fixture_dir else "skipped",
        "instances": instances,
        "false_claims": false_claims,
        "notes": notes,
    }


def _cell(value) -> str:
    return "n/a" if value is None else f"{value:.3f}" if isinstance(value, float) else str(value)


def _md(value) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def _cite(citation: str) -> str:
    return citation if citation.startswith("[") and citation.endswith("]") else f"[{citation}]"


def _review_lines(inst_review, findings) -> list[str]:
    if isinstance(inst_review, str):
        return [f"review: {inst_review}"]
    lines = ["| category | verdict | findings |", "| --- | --- | --- |"]
    for cat, v in inst_review.items():
        found = "; ".join(f"{f['summary']} {_cite(f['citation'])}" for f in findings.get(cat, []))
        lines.append(f"| {cat} | {v} | {_md(found) or 'none'} |")
    return lines


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
        reps = inst["repeats"]
        cols = [f"r{r['repeat']}" for r in reps]
        lines += ["", f"## {inst['instance_id']}", ""]
        lines += [
            "| " + " | ".join(
                ["metric", *cols, "summary", "baseline (per repeat)", "range", "verdict",
                 "repeats above/within/below"]
            ) + " |",
            "| " + " | ".join(["---"] * (len(cols) + 6)) + " |",
        ]
        for m in METRICS:
            row = inst["metrics"][m]
            name = m + SMALL_SAMPLE_SUFFIX if inst["small_sample"] and m in KILL_METRICS else m
            rng = "n/a" if row["range"] is None else f"[{_cell(row['range'][0])}, {_cell(row['range'][1])}]"
            base = ", ".join(_cell(v) for v in row["baseline"]) or "n/a"
            rv = row["repeat_verdicts"]
            lines.append("| " + " | ".join([
                name, *(_cell(v) for v in row["harness"]), _summary_cell(row["harness_summary"]),
                base, rng, row["verdict"], f"{rv['above']}/{rv['within']}/{rv['below']}",
            ]) + " |")
        lines.append("")
        lines += [
            f"r{r['repeat']} ({r['status']}) cost_usd: {_cell(r['cost_usd'])}, "
            f"elapsed_s: {_cell(r['elapsed_s'])}"
            for r in reps
        ]
        lines += ["", "| " + " | ".join(["check", *cols, "fails"]) + " |"]
        lines.append("| " + " | ".join(["---"] * (len(cols) + 2)) + " |")
        for cid, fails in inst["process_fails"].items():
            cells = [r["process"].get(cid, "n/a") for r in reps]
            lines.append("| " + " | ".join([cid, *cells, str(fails)]) + " |")
        for r in reps:
            lines += ["", f"### r{r['repeat']} review", ""]
            lines += _review_lines(r["review"], r["review_findings"])
    lines += ["", "## false claims", ""]
    if report["false_claims"]:
        lines += ["| instance | repeat | category | summary | citation |", "| --- | --- | --- | --- | --- |"]
        lines += [
            f"| {fc['instance_id']} | r{fc['repeat']} | {fc['category']} | {_md(fc['summary'])} "
            f"| {_md(fc['citation'])} |"
            for fc in report["false_claims"]
        ]
    else:
        lines.append("none")
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

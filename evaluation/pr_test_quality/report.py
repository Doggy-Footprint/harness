import hashlib
import json
import re
import statistics
from pathlib import Path

from . import atomic_write, data_dir, pilot, read_json, read_jsonl, section, stats

QUOTE_CUT = 200
PAIRS = (("H", "B0"), ("H", "Bplus"), ("Bplus", "B0"))
FORBIDDEN_MARKERS = (
    "diff --git", '"role": "assistant"', '"role": "user"', '"type": "tool_use"', '"type": "tool_result"',
    '"tool_input"',
)
FORBIDDEN_LINE_START = re.compile(r"^\s*(?:def test_|func Test|#\[test\])", re.M)
METRICS = (
    ("normalized_kill", "primary"), ("raw_kill", "secondary"), ("false_alarm_rate", "guard"),
    ("resolved", "H1"), ("f2p_frac", "H1"), ("ambiguity_rate", "H2"), ("cost_usd", "H4"), ("wall_s", "H4"),
)
H4_MAX_RATIO = 10.0


class TokenInReport(RuntimeError):
    def __init__(self, message: str, needle: str | None = None):
        super().__init__(message)
        self.needle = needle


class RunIncomplete(RuntimeError):
    pass


def locate_token(run_dir, token: str) -> str | None:
    needle = token.encode()
    root = Path(run_dir)
    for path in sorted(root.rglob("*")):
        if path.is_file() and not path.is_symlink() and needle in path.read_bytes():
            return path.relative_to(root).as_posix()
    return None


class PreregMismatch(RuntimeError):
    pass


def _clip(value):
    if isinstance(value, list):
        return [_clip(v) for v in value]
    if isinstance(value, dict):
        return {
            k: v[:QUOTE_CUT] if k == "quote" and isinstance(v, str) else _clip(v) for k, v in value.items()
        }
    return value


def _metrics(score: dict) -> dict:
    hidden, validity, kill = score.get("hidden") or {}, score.get("validity") or {}, score.get("kill") or {}
    ambiguity = score.get("ambiguity") or {}
    flagged = kill.get("flagged", True)
    return {
        "normalized_kill": None if flagged else kill.get("normalized"),
        "raw_kill": None if flagged else kill.get("raw"),
        "false_alarm_rate": validity.get("false_alarm_rate"),
        "resolved": float(hidden["resolved"]) if hidden.get("status") == "ok" else None,
        "f2p_frac": hidden.get("f2p_frac") if hidden.get("status") == "ok" else None,
        "ambiguity_rate": ambiguity.get("rate"),
        "cost_usd": score.get("cost_usd"),
        "wall_s": score.get("wall_s"),
    }


def _strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for k, v in value.items():
            yield from _strings(k)
            yield from _strings(v)
    elif isinstance(value, list):
        for v in value:
            yield from _strings(v)


def _mean(values: list) -> float | None:
    values = [v for v in values if v is not None]
    return sum(values) / len(values) if values else None


def _task_means(rows: list[dict]) -> dict:
    out: dict = {}
    for r in rows:
        out.setdefault(r["task_id"], {}).setdefault(r["arm"], []).append(r["metrics"])
    return {
        task: {arm: {m: _mean([x[m] for x in ms]) for m, _ in METRICS} for arm, ms in arms.items()}
        for task, arms in out.items()
    }


def _comparison(means: dict, repos: dict, languages: dict, scope: str | None, left: str, right: str, metric: str, scfg: dict, rule: dict) -> dict:
    clusters: dict[str, list[float]] = {}
    for task, arms in means.items():
        if scope and languages.get(task) != scope:
            continue
        a, b = arms.get(left, {}).get(metric), arms.get(right, {}).get(metric)
        if a is not None and b is not None:
            clusters.setdefault(repos[task], []).append(a - b)
    ci = stats.cluster_bootstrap(
        clusters, resamples=scfg.get("resamples", 10000), seed=scfg.get("seed", 1), alpha=scfg.get("alpha", 0.05)
    )
    return {**ci, "verdict": stats.verdict(ci, rule)}


def _failure_row(base: dict, task: dict, score: dict, cfg: dict, flagged: bool | None) -> dict:
    if flagged is None:
        d_ref = sum(1 for m in task.get("mutants", []) if m.get("gold") == "killed")
        flagged = d_ref < section(cfg, "report").get("min_mutants", 10)
    zero = None if flagged else 0.0
    return {
        **base, "language": task.get("language", "unknown"), "repo": task.get("repo", base["task_id"].rsplit("-", 1)[0]),
        "status": "error", "scored": True, "final_error": True,
        "metrics": {
            "normalized_kill": zero, "raw_kill": zero, "false_alarm_rate": None, "resolved": 0.0, "f2p_frac": 0.0,
            "ambiguity_rate": 0.0, "cost_usd": score.get("cost_usd") or 0.0, "wall_s": score.get("wall_s") or 0.0,
        },
        "resolved": False, "cost_usd": score.get("cost_usd") or 0.0, "wall_s": score.get("wall_s") or 0.0,
        "questions_asked": score.get("questions") or 0, "spec_corrections": score.get("corrections") or 0,
        "valid_tests": 0, "agent_tests": 0, "incompatible": 0,
        "flaky": 0, "kill_flagged": flagged, "hidden_inconclusive": False, "validity_inconclusive": False,
        "self_report": None,
    }


def _judge_tables(run_dir: Path, rows: list[dict]) -> dict:
    smells: dict[str, dict[str, int]] = {}
    desiderata: dict[str, dict[str, list[int]]] = {}
    coverage: dict[str, dict[str, int]] = {}
    outcomes: dict[str, dict[str, int]] = {}
    ranks: list[bool] = []
    errors = 0
    pairs = inconsistent = 0
    for task in sorted({r["task_id"] for r in rows}):
        judged = read_json(run_dir / task / "judge.json")
        if not judged:
            continue
        labels = judged["labels"]

        def group(label: str) -> str:
            source = labels[label]
            return "human" if source == "human" else source.rsplit("-r", 1)[0]

        means = {}
        for label, result in judged["absolute"].items():
            g = group(label)
            if result == "error":
                errors += 1
                continue
            for s in result["smells"]:
                smells.setdefault(g, {}).setdefault(s["smell"], 0)
                smells[g][s["smell"]] += 1
            for name, item in result["desiderata"].items():
                desiderata.setdefault(g, {}).setdefault(name, []).append(item["score"])
            for item in result["coverage"].values():
                coverage.setdefault(g, {}).setdefault(item["level"], 0)
                coverage[g][item["level"]] += 1
            means[label] = statistics.fmean(i["score"] for i in result["desiderata"].values())
        human = next((lb for lb in means if labels[lb] == "human"), None)
        if human is not None and len(means) > 1:
            ranks.append(not any(v < means[human] for lb, v in means.items() if lb != human))
        for row in judged["pairwise"]:
            outcomes.setdefault(row["pair"], {}).setdefault(row["outcome"], 0)
            outcomes[row["pair"]][row["outcome"]] += 1
            pairs += 1
            inconsistent += row["outcome"] == "inconsistent"
    return {
        "smell_counts": smells,
        "desiderata_means": {g: {n: _mean(v) for n, v in d.items()} for g, d in desiderata.items()},
        "coverage_counts": coverage, "pairwise": outcomes, "errors": errors,
        "consistency": (pairs - inconsistent) / pairs if pairs else None,
        "anchor_lowest_share": _mean([float(r) for r in ranks]),
        "anchor_tasks": len(ranks),
    }


def _win_rates(run_dir: Path, rows: list[dict], repos: dict, scfg: dict) -> dict:
    out = {}
    for left, right in PAIRS:
        pair = f"{left}-{right}"
        clusters: dict[str, list[float]] = {}
        for task in sorted({r["task_id"] for r in rows}):
            judged = read_json(run_dir / task / "judge.json")
            for row in (judged or {}).get("pairwise", []):
                if row["pair"] == pair and row["outcome"] in ("A", "B"):
                    clusters.setdefault(repos[task], []).append(0.5 if row["outcome"] == "A" else -0.5)
        ci = stats.cluster_bootstrap(
            clusters, resamples=scfg.get("resamples", 10000), seed=scfg.get("seed", 1), alpha=scfg.get("alpha", 0.05)
        )
        shifted = {k: None if v is None else v + 0.5 for k, v in ci.items() if k in ("mean", "lo", "hi")}
        out[pair] = {**ci, **shifted, "verdict": stats.verdict(ci, {})}
    return out


def _h4(rows: list[dict]) -> dict:
    def median_cost(arm: str):
        costs = [r["cost_usd"] for r in rows if r["arm"] == arm and r["resolved"] and r["cost_usd"] is not None]
        return statistics.median(costs) if costs else None

    def median_wall(arm: str):
        walls = [r["wall_s"] for r in rows if r["arm"] == arm and r["wall_s"] is not None]
        return statistics.median(walls) if walls else None

    h, b = median_cost("H"), median_cost("B0")
    ratio = h / b if h is not None and b else None
    wall_h, wall_b = median_wall("H"), median_wall("B0")
    return {
        "median_cost_per_resolved": {"H": h, "B0": b}, "cost_ratio_H_B0": ratio,
        "verdict": None if ratio is None else ("cost excessive" if ratio > H4_MAX_RATIO else "within limit"),
        "wall_ratio_H_B0": wall_h / wall_b if wall_h is not None and wall_b else None,
    }


def _crossarm(run_dir: Path, rows: list[dict]) -> dict:
    per_arm: dict[str, dict[str, list]] = {}
    for task in sorted({r["task_id"] for r in rows}):
        data = read_json(run_dir / task / "crossarm.json")
        for entry, d in ((data or {}).get("detection") or {}).items():
            arm = entry.rsplit("-r", 1)[0]
            bucket = per_arm.setdefault(arm, {"detection_rate": [], "false_alarm_rate": []})
            bucket["detection_rate"].append(d["detection_rate"])
            bucket["false_alarm_rate"].append(d["false_alarm_rate"])
    for r in rows:
        if r.get("final_error"):
            bucket = per_arm.setdefault(r["arm"], {"detection_rate": [], "false_alarm_rate": []})
            bucket["detection_rate"].append(0.0)
    return {arm: {k: _mean(v) for k, v in b.items()} for arm, b in per_arm.items()}


def _candidate_valid_rates(cfg: dict, languages: set[str]) -> dict:
    rates = {}
    for language in sorted(languages):
        tasks = read_jsonl(data_dir(cfg) / "tasks" / language / "tasks.jsonl")
        if tasks:
            rates[language] = sum(1 for t in tasks if t.get("valid")) / len(tasks)
    return rates


def build(run_dir, *, prereg_path, cfg: dict) -> dict:
    run_dir = Path(run_dir)
    meta = read_json(run_dir / "run.json")
    if meta is None:
        raise FileNotFoundError(f"run.json missing in {run_dir}")
    current = None
    if prereg_path and Path(prereg_path).is_file():
        current = hashlib.sha256(Path(prereg_path).read_bytes()).hexdigest()
    if meta.get("phase") == "main" and current != meta.get("prereg_sha256"):
        raise PreregMismatch(
            f"preregistration changed since the main run started: run {meta.get('prereg_sha256')}, "
            f"current {current}; restore {prereg_path} or start a new run"
        )
    run_id = meta["run_id"]
    problems = []
    if any(e["status"] == "error" and e.get("attempts", 1) == 1 for e in meta["entries"]):
        problems.append(f"entries ended in error after one attempt; run `python3 -m evaluation.pr_test_quality run --retry-errors {run_id}`")
    if any(e["status"] == "interrupted" for e in meta["entries"]):
        problems.append(f"entries are interrupted; run `python3 -m evaluation.pr_test_quality run --resume {run_id}`")
    if problems:
        raise RunIncomplete("; ".join(problems))
    rows, entry_rows = [], []
    final_errors: dict[str, int] = {}
    task_flags: dict[str, bool] = {}
    for e in meta["entries"]:
        kill = (read_json(run_dir / e["task_id"] / f"{e['arm']}-r{e['repeat']}" / "score.json") or {}).get("kill")
        if isinstance(kill, dict) and "flagged" in kill:
            task_flags.setdefault(e["task_id"], bool(kill["flagged"]))
    scrubbed = 0
    snapshot = {t["task_id"]: t for t in read_jsonl(run_dir / "tasks.jsonl")}
    for entry in meta["entries"]:
        d = run_dir / entry["task_id"] / f"{entry['arm']}-r{entry['repeat']}"
        score = read_json(d / "score.json")
        state = read_json(d / "state.json", {})
        scrubbed += state.get("scrubbed_occurrences") or 0
        base = {"task_id": entry["task_id"], "arm": entry["arm"], "repeat": entry["repeat"]}
        task = snapshot.get(entry["task_id"], {})
        if entry["status"] == "error":
            final_errors[entry["arm"]] = final_errors.get(entry["arm"], 0) + 1
            row = _failure_row(base, task, score or {}, cfg, task_flags.get(entry["task_id"]))
            rows.append(row)
            entry_rows.append({k: v for k, v in row.items() if k != "metrics"} | row["metrics"])
            continue
        if not score or (score.get("hidden") or {}).get("status") == "skipped":
            entry_rows.append({**base, "status": entry["status"], "scored": False})
            continue
        validity, kill, hidden = score.get("validity"), score.get("kill") or {}, score.get("hidden") or {}
        row = {**base, "language": task.get("language", "unknown"), "repo": task.get("repo", entry["task_id"].rsplit("-", 1)[0]),
               "status": entry["status"], "scored": True, "metrics": _metrics(score),
               "resolved": hidden.get("resolved"), "cost_usd": score.get("cost_usd"), "wall_s": score.get("wall_s"),
               "questions_asked": score.get("questions"), "spec_corrections": score.get("corrections"),
               "valid_tests": len((validity or {}).get("valid", [])),
               "agent_tests": (validity or {}).get("n", 0),
               "incompatible": len((validity or {}).get("incompatible", [])),
               "flaky": len((validity or {}).get("flaky", [])),
               "kill_flagged": kill.get("flagged"),
               "hidden_inconclusive": hidden.get("status") == "inconclusive",
               "validity_inconclusive": validity is None,
               "self_report": score.get("self_report")}
        rows.append(row)
        entry_rows.append({k: v for k, v in row.items() if k != "metrics"} | row["metrics"])
    means = _task_means(rows)
    repos = {r["task_id"]: r["repo"] for r in rows}
    langs = {r["task_id"]: r["language"] for r in rows}
    scfg = section(cfg, "stats")
    min_tasks = scfg.get("min_tasks", stats.MIN_TASKS)
    scopes = {"overall": None, **{lang: lang for lang in sorted(set(langs.values()))}}
    comparisons = {}
    for scope, key in scopes.items():
        comparisons[scope] = {}
        for left, right in PAIRS:
            comparisons[scope][f"{left}-{right}"] = {}
            for metric, _ in METRICS:
                rule = {"min_tasks": min_tasks}
                if metric == "false_alarm_rate":
                    rule["guard_upper"] = 0.10
                comparisons[scope][f"{left}-{right}"][metric] = _comparison(
                    means, repos, langs, key, left, right, metric, scfg, rule
                )
    judge_tables = _judge_tables(run_dir, rows)
    cost = {}
    for arm in sorted({r["arm"] for r in rows}):
        arm_rows = [r for r in rows if r["arm"] == arm]
        cost[arm] = {"entries": len(arm_rows), "total_usd": sum(r["cost_usd"] or 0 for r in arm_rows),
                     "mean_usd": _mean([r["cost_usd"] for r in arm_rows])}
    b0 = [r["resolved"] for r in rows if r["arm"] == "B0" and r["resolved"] is not None]
    report = {
        "run_id": meta["run_id"], "phase": meta["phase"], "prereg_sha256": meta.get("prereg_sha256"),
        "prereg_current_sha256": current, "params": meta.get("params"), "entries": entry_rows,
        "task_means": means, "comparisons": comparisons, "h4": _h4(rows),
        "crossarm": _crossarm(run_dir, rows), "final_errors": dict(sorted(final_errors.items())), "win_rates": _win_rates(run_dir, rows, repos, scfg),
        "judge": judge_tables, "cost": cost,
        "inconclusive": {
            "hidden": sum(1 for r in rows if r["hidden_inconclusive"]),
            "validity": sum(1 for r in rows if r["validity_inconclusive"]),
            "kill_flagged": sum(1 for r in rows if r["kill_flagged"]),
            "unscored": sum(1 for e in entry_rows if not e.get("scored")),
        },
        "manual": {"h2_blind_preference": "record 5-8 pairs by hand; not computed"},
    }
    if meta["phase"] == "pilot":
        leaks = 0
        for r in rows:
            d = run_dir / r["task_id"] / f"{r['arm']}-r{r['repeat']}" / "usersim.jsonl"
            leaks += sum(
                1 for x in read_jsonl(d)
                if x.get("reason") == "leak" or "leak" in (x.get("fallbacks") or {}).values()
            )
        report["pilot_gates"] = pilot.gates({
            "b0_resolved_rate": _mean([float(x) for x in b0]),
            "candidate_valid_rate": _candidate_valid_rates(cfg, set(langs.values())),
            "judge_consistency": judge_tables["consistency"],
            "anchor_lowest_share": judge_tables["anchor_lowest_share"],
            "leak_fallbacks": leaks, "token_hits": scrubbed,
        }, cfg)
    return _clip(report)


def _fmt(value) -> str:
    if value is None:
        return "n/a"
    return f"{value:.3f}" if isinstance(value, float) else str(value)


def _table(headers: list[str], rows: list[list]) -> str:
    lines = ["| " + " | ".join(headers) + " |", "| " + " | ".join("---" for _ in headers) + " |"]
    lines += ["| " + " | ".join(_fmt(c) for c in row) + " |" for row in rows]
    return "\n".join(lines)


_JUDGE_DEFAULT = {
    "desiderata_means": {}, "smell_counts": {}, "coverage_counts": {}, "pairwise": {}, "errors": 0,
    "consistency": None, "anchor_lowest_share": None, "anchor_tasks": 0,
}
_H4_DEFAULT = {
    "median_cost_per_resolved": {"H": None, "B0": None}, "cost_ratio_H_B0": None, "verdict": None,
    "wall_ratio_H_B0": None,
}
_INCONCLUSIVE_DEFAULT = {"hidden": 0, "validity": 0, "kill_flagged": 0, "unscored": 0}


def render_markdown(report: dict) -> str:
    report = {
        "phase": None, "prereg_sha256": None, "comparisons": {}, "cost": {}, "crossarm": {}, "win_rates": {},
        "entries": [], "final_errors": {}, **report,
        "h4": {**_H4_DEFAULT, **report.get("h4", {})}, "judge": {**_JUDGE_DEFAULT, **report.get("judge", {})},
        "inconclusive": {**_INCONCLUSIVE_DEFAULT, **report.get("inconclusive", {})},
    }
    out = [f"# Evaluation report {report['run_id']}", "",
           f"- phase: {report['phase']}", f"- preregistration sha256: {report['prereg_sha256']}", ""]
    if "pilot_gates" in report:
        out += ["## Pilot gates", _table(
            ["gate", "pass", "value", "threshold"],
            [[g, v["pass"], v["value"], v["threshold"]] for g, v in sorted(report["pilot_gates"].items())]), ""]
    out += ["## Paired differences (first arm minus second arm)"]
    for scope, pairs in report["comparisons"].items():
        rows = []
        for pair, metrics in pairs.items():
            for metric, ci in metrics.items():
                rows.append([pair, metric, ci["n_tasks"], ci["mean"], ci["lo"], ci["hi"], ci["verdict"]])
        out += [f"### {scope}", _table(["pair", "metric", "tasks", "mean", "lo", "hi", "verdict"], rows), ""]
    h4 = report["h4"]
    out += ["## H4 cost", _table(["measure", "value"], [
        ["median cost per resolved task, H", h4["median_cost_per_resolved"]["H"]],
        ["median cost per resolved task, B0", h4["median_cost_per_resolved"]["B0"]],
        ["cost ratio H/B0", h4["cost_ratio_H_B0"]], ["verdict", h4["verdict"]],
        ["wall time ratio H/B0", h4["wall_ratio_H_B0"]]]), ""]
    out += ["## Cost by arm", _table(["arm", "entries", "total usd", "mean usd"],
                                     [[a, c["entries"], c["total_usd"], c["mean_usd"]] for a, c in report["cost"].items()]), ""]
    out += ["## Cross-arm detection", _table(["tests from", "detection rate", "false alarm rate"],
                                             [[a, c["detection_rate"], c["false_alarm_rate"]] for a, c in report["crossarm"].items()]), ""]
    judge = report["judge"]
    out += ["## Judge",
            _table(["group", "desideratum", "mean"], [[g, n, v] for g, d in judge["desiderata_means"].items() for n, v in d.items()]), "",
            _table(["group", "smell", "count"], [[g, s, c] for g, d in judge["smell_counts"].items() for s, c in d.items()]), "",
            _table(["group", "coverage", "count"], [[g, s, c] for g, d in judge["coverage_counts"].items() for s, c in d.items()]), "",
            _table(["pair", "outcome", "count"], [[p, o, c] for p, d in judge["pairwise"].items() for o, c in d.items()]), "",
            f"- position consistency: {_fmt(judge['consistency'])}",
            f"- human anchor lowest share: {_fmt(judge['anchor_lowest_share'])} over {judge['anchor_tasks']} tasks",
            f"- judge items recorded as error: {judge['errors']}", "",
            "### Pairwise win rate (wins over non-tie decisions)",
            _table(["pair", "decisions", "win rate", "lo", "hi", "verdict"],
                   [[p, w["n_tasks"], w["mean"], w["lo"], w["hi"], w["verdict"]] for p, w in report["win_rates"].items()]), ""]
    inc = report["inconclusive"]
    out += ["## Final error entries per arm",
            _table(["arm", "count"], [[a, c] for a, c in report["final_errors"].items()]), ""]
    out += ["## Inconclusive counts", _table(["kind", "count"], [[k, v] for k, v in inc.items()]), ""]
    cols = ["task_id", "arm", "repeat", "status", "resolved", "f2p_frac", "normalized_kill", "raw_kill",
            "false_alarm_rate", "valid_tests", "cost_usd", "wall_s"]
    out += ["## Entries", _table(cols, [[e.get(c) for c in cols] for e in report["entries"]]), ""]
    return "\n".join(out)


def write(report: dict, results_dir, *, token: str) -> tuple[Path, Path]:
    results_dir = Path(results_dir)
    report = _clip(report)
    text_json = json.dumps(report, indent=1, sort_keys=True, ensure_ascii=False)
    text_md = render_markdown(report)
    for text in (text_json, text_md, *_strings(report)):
        if token and token in text:
            raise TokenInReport("report contains the OAuth token; nothing written", token)
        for marker in FORBIDDEN_MARKERS:
            if marker in text:
                raise TokenInReport(f"report contains forbidden content marker {marker!r}; nothing written", marker)
        if FORBIDDEN_LINE_START.search(text):
            raise TokenInReport("report contains test-code lines; nothing written", "test code")
    json_path = results_dir / f"{report['run_id']}.json"
    md_path = results_dir / f"{report['run_id']}.md"
    atomic_write(json_path, text_json)
    atomic_write(md_path, text_md)
    return json_path, md_path

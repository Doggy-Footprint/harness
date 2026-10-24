from . import languages, overlay, section, testrun

RUN_ERRORS = ("build_error", "timeout", "parse_error")
PASS = "pass"


def _all(results: list[dict], test_id: str, status: str) -> bool:
    return all(run.get(test_id) == status for run in results)


def _differs(results: list[dict], test_id: str) -> bool:
    return len({run.get(test_id) for run in results}) > 1


def classify(base_runs: list[dict], merge_runs: list[dict], cfg: dict, *, gold_test_files: list[str], orig_runs: list[dict] | None = None) -> dict:
    statuses = {run.get("status", "ok") for run in [*base_runs, *merge_runs]}
    for reason in RUN_ERRORS:
        if reason in statuses:
            return {"valid": False, "reason": reason, "f2p": [], "p2p": [], "flaky": [], "p2p_note": None}
    orig_status = {run.get("status", "ok") for run in orig_runs or []}
    note = next((s for s in RUN_ERRORS if s in orig_status), None)
    if not orig_runs:
        note = "no_base_tests"
    use_orig = orig_runs if note is None else []
    base = [run.get("results", {}) for run in base_runs]
    merge = [run.get("results", {}) for run in merge_runs]
    orig = [run.get("results", {}) for run in use_orig]
    ids = {t for run in [*base, *merge, *orig] for t in run}
    flaky = sorted(t for t in ids if _differs(base, t) or _differs(merge, t) or _differs(orig, t))
    candidates = {t for t in ids if not _all(base, t, PASS) and any(run.get(t) == PASS for run in merge)}
    p2p = sorted(
        t for t in ids
        if orig and _all(orig, t, PASS) and _all(merge, t, PASS) and t not in flaky
    )
    f2p = sorted(t for t in candidates if _all(merge, t, PASS) and t not in flaky)
    out = {"f2p": f2p, "p2p": p2p, "flaky": flaky, "p2p_note": note}
    if not candidates:
        return {**out, "valid": False, "reason": "no_f2p"}
    if candidates & set(flaky):
        return {**out, "valid": False, "reason": "flaky_f2p"}
    return {**out, "valid": True, "reason": "ok"}


def gold_selection(task: dict) -> list[str]:
    paths = {p.replace(languages.CFGTEST, "") for p in languages.diff_paths(task["gold_split"]["tests"])}
    return sorted(p for p in paths if task["gold_after"].get(p) is not None)


def gold_entry(task: dict) -> dict:
    return {"base": task["gold_base"], "after": task["gold_after"], "split": task["gold_split"]}


def base_state_entry(task: dict) -> dict:
    return {"base": task["gold_base"], "after": task["gold_base"], "split": {k: "" for k in ("src", "tests", "harness", "other")}}


def merge_tree(task: dict) -> dict:
    gold = gold_entry(task)
    return overlay.hidden_tree(task["language"], gold, gold)


def f2p_relevant(task: dict, test_id: str, orig_passed: set | None = None) -> bool:
    if orig_passed is not None and test_id not in orig_passed:
        return True
    language = task["language"]
    sections = languages.parse_diff(task["gold_split"]["tests"])
    id_file = test_id.split("::", 1)[0]
    mine = [s for s in sections if languages.id_matches_file(language, id_file, s.path)] or sections
    if any(s.old == "/dev/null" for s in mine if languages.id_matches_file(language, id_file, s.path)):
        return True
    name = languages.base_test_name(language, test_id)
    return any(name in text for s in mine for h in s.hunks for tag, text in h.ops if tag == "+")


def validate_task(task: dict, *, docker, cfg: dict, cache_dir) -> dict:
    vcfg = section(cfg, "validation")
    vc = {**cfg, "eval": {**section(cfg, "eval"), "timeout_s": vcfg.get("timeout_s", 600)}}
    gold = gold_entry(task)
    trees = {
        "base": overlay.hidden_tree(task["language"], gold, base_state_entry(task)),
        "merge": merge_tree(task),
    }
    selection = gold_selection(task)
    if not selection:
        return {"valid": False, "reason": "no_f2p", "f2p": [], "p2p": [], "flaky": [], "p2p_note": "no_base_tests"}
    orig_selection = selection if task["language"] == "go" else [p for p in selection if task["gold_base"].get(p) is not None]
    orig_tree = overlay.hidden_tree(task["language"], {**gold, "after": task["gold_base"]}, base_state_entry(task))
    repeats = range(vcfg.get("repeats", 3))

    # One errored run already decides the verdict (invalid for base/merge, p2p_note for orig); the remaining
    # repeats of a slow repository would each spend the full validation timeout.
    def run(tree, sel):
        out = []
        for k in repeats:
            out.append(testrun.run_tests(task, tree, sel, docker=docker, cfg=vc, cache_dir=cache_dir, repeat=k))
            if out[-1].get("status") in RUN_ERRORS:
                break
        return out

    # Gold tests that call new API do not compile against base src in rust (no junit at all); at base that is
    # the expected fail-to-pass shape, so it counts as every selected test not passing.
    base_runs = [{**r, "status": "ok", "results": {}} if r.get("status") == "build_error" else r
                 for r in run(trees["base"], selection)]
    errored = any(r.get("status") in RUN_ERRORS for r in base_runs)
    merge_runs = [] if errored else run(trees["merge"], selection)
    errored = errored or any(r.get("status") in RUN_ERRORS for r in merge_runs)
    orig_runs = run(orig_tree, orig_selection) if orig_selection and not errored else []
    verdict = classify(base_runs, merge_runs, cfg, gold_test_files=selection, orig_runs=orig_runs)
    if verdict["valid"]:
        orig_passed = None
        if verdict["p2p_note"] is None:
            orig = [run.get("results", {}) for run in orig_runs]
            orig_passed = {t for t in orig[0] if _all(orig, t, PASS)}
        verdict["f2p"] = [t for t in verdict["f2p"] if f2p_relevant(task, t, orig_passed)]
        if not verdict["f2p"]:
            verdict.update(valid=False, reason="no_f2p")
        verdict["p2p"] = [t for t in verdict["p2p"] if t not in set(verdict["f2p"])]
    return verdict

import ast
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import evaluate, patches
from .evaluate import FAIL, PASS

_API_ERRORS = ("ImportError", "ModuleNotFoundError", "AttributeError", "NameError")
_DJANGO_ID = re.compile(r"^(\w+) \(([\w.]+)\)$")


def test_id_key(repo: str, test_id: str) -> tuple[str | None, str | None, str]:
    if repo == "django/django":
        m = _DJANGO_ID.match(test_id)
        if m:
            name, dotted = m.groups()
            parts = dotted.split(".")
            if len(parts) > 1 and parts[-1] == name:
                parts = parts[:-1]
            if len(parts) >= 2:
                return "tests/" + "/".join(parts[:-1]) + ".py", parts[-1], name
    if "::" in test_id:
        head = test_id.split("[", 1)[0]
        parts = head.split("::")
        if len(parts) >= 2:
            cls = parts[-2] if len(parts) >= 3 else None
            return parts[0], cls, parts[-1]
    return None, None, test_id


def _test_functions(tree: ast.AST, text: str) -> dict[tuple[str | None, str], str]:
    found: dict[tuple[str | None, str], str] = {}

    def visit(body, cls):
        for node in body:
            if isinstance(node, ast.ClassDef):
                visit(node.body, node.name)
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test"):
                found[(cls, node.name)] = ast.get_source_segment(text, node) or ""

    visit(tree.body, None)
    return found


def changed_tests(base_text: str | None, new_text: str) -> set[tuple[str | None, str]] | None:
    try:
        new_tree = ast.parse(new_text)
    except (SyntaxError, ValueError):
        return None
    new = _test_functions(new_tree, new_text)
    old: dict = {}
    if base_text is not None:
        try:
            old = _test_functions(ast.parse(base_text), base_text)
        except (SyntaxError, ValueError):
            old = {}
    return {k for k, seg in new.items() if k not in old or old[k] != seg}


def attribute(repo: str, status_ids: list[str], files: dict[str, tuple[str | None, str]]) -> set[str]:
    changed = {path: changed_tests(base, new) for path, (base, new) in files.items()}
    out = set()
    for tid in status_ids:
        file, cls, fn = test_id_key(repo, tid)
        candidates = [file] if file is not None else list(changed)
        for path in candidates:
            if path not in changed:
                continue
            pairs = changed[path]
            if pairs is None or any(
                f == fn and (cls is None or c == cls) for c, f in pairs
            ):
                out.add(tid)
                break
    return out


def swt_outcome(before: dict, after_runs: list[dict]) -> dict:
    applicable = bool(after_runs) and all(
        r["apply"] == "ok" and not r.get("no_tests") and bool(r["status"]) for r in after_runs
    )
    if not applicable:
        return {"applicable": False, "success": False, "f2p": [], "x2f": []}
    skipped = {t for r in after_runs for t, s in r["status"].items() if s == "SKIPPED"}
    considered = (set(before["status"]) | {t for r in after_runs for t in r["status"]}) - skipped
    f2p = sorted(
        t for t in considered
        if (before["status"].get(t) in FAIL or t not in before["status"])
        and all(r["status"].get(t) in PASS for r in after_runs)
    )
    x2f = sorted(t for t in considered if any(r["status"].get(t) not in PASS for r in after_runs))
    return {"applicable": True, "success": bool(f2p) and not x2f, "f2p": f2p, "x2f": x2f}


def _kill_block(mutants: list[dict], killed_ids: set[str], timeouts: int) -> dict:
    valid = [m for m in mutants if m.get("compile_ok")]
    d_ref = {m["id"] for m in valid if m.get("killed")}
    in_ref = len(killed_ids & d_ref)
    return {
        "sampled": len(valid),
        "killed": len(killed_ids),
        "primary": len(killed_ids) / len(valid) if valid else None,
        "d_ref": len(d_ref),
        "killed_in_d_ref": in_ref,
        "secondary": in_ref / len(d_ref) if d_ref else None,
        "gold_reference": len(d_ref) / len(valid) if valid else None,
        "timeouts": timeouts,
    }


def _log_mentions_api_error(runs: list[dict]) -> bool:
    for r in runs:
        if r.get("log_path") is None:
            continue
        try:
            text = Path(r["log_path"]).read_text(errors="replace")
        except OSError:
            continue
        if any(name in text for name in _API_ERRORS):
            return True
    return False


def score_prediction(
    instance: dict,
    prediction: dict,
    *,
    validation: dict,
    mutants: list[dict],
    evaluate_fn=evaluate.evaluate,
    read_files_fn=evaluate.read_files,
    workers: int = 2,
) -> dict:
    src_diff = prediction.get("src_diff") or ""
    test_patch = prediction.get("test_patch") or ""
    calls = 0

    def run(*args, **kw):
        nonlocal calls
        calls += 1
        return evaluate_fn(*args, **kw)

    f2p = list(instance["FAIL_TO_PASS"])
    impl = run(instance, src_diff + test_patch, instance["test_patch"])
    n_pass = sum(1 for t in f2p if impl["status"].get(t) in PASS)
    resolved = (
        impl["apply"] == "ok"
        and n_pass == len(f2p)
        and all(impl["status"].get(t) in PASS for t in validation["p2p_effective"])
    )
    score = {
        "instance_id": instance["instance_id"],
        "resolved": resolved,
        "f2p_frac": n_pass / len(f2p) if f2p else 0.0,
        "src_apply": impl["apply"],
        "swt": {"applicable": False, "success": False, "f2p": [], "x2f": []},
        "agent_tests": [],
        "agent_tests_ok": [],
        "incompatible_frac": None,
        "incompatible": {"missing": 0, "error": 0, "failed": 0},
        "api_mismatch_suspected": False,
        "kill": _kill_block(mutants, set(), 0),
        "evaluations": calls,
    }
    if not test_patch:
        return score

    before = run(instance, "", test_patch)
    afters = [
        run(instance, instance["patch"], test_patch, repeat=0),
        run(instance, instance["patch"], test_patch, repeat=1),
    ]
    score["swt"] = swt_outcome(before, afters)

    paths = [s["path"] for s in patches.file_sections(test_patch)]
    base_texts = read_files_fn(instance, "", paths)
    try:
        new_texts = patches.apply_to_texts(base_texts, test_patch)
    except ValueError:
        new_texts = {}
    files = {
        p: (base_texts.get(p), new_texts[p])
        for p in paths
        if p.endswith(".py") and new_texts.get(p) is not None
    }
    seen_ids = sorted(set(before["status"]) | {t for r in afters for t in r["status"]})
    agent = sorted(attribute(instance["repo"], seen_ids, files))
    ok = [t for t in agent if all(r["status"].get(t) in PASS for r in afters)]
    bad = [t for t in agent if t not in set(ok)]
    first = afters[0]["status"]
    incompatible = {
        "missing": sum(1 for t in bad if t not in first),
        "error": sum(1 for t in bad if first.get(t) == "ERROR"),
    }
    incompatible["failed"] = len(bad) - incompatible["missing"] - incompatible["error"]
    score.update(
        agent_tests=agent,
        agent_tests_ok=ok,
        incompatible_frac=len(bad) / len(agent) if agent else None,
        incompatible=incompatible,
        api_mismatch_suspected=_log_mentions_api_error(afters),
    )

    score["kill"] = _kill_block(mutants, set(), 0)
    if ok:
        valid = [m for m in mutants if m.get("compile_ok")]

        def one(m):
            res = evaluate_fn(instance, m["patch"], test_patch)
            timed_out = bool(res.get("timed_out"))
            return timed_out or any(res["status"].get(t) not in PASS for t in ok), timed_out

        with ThreadPoolExecutor(max_workers=workers) as pool:
            outcomes = list(pool.map(one, valid))
        calls += len(valid)
        killed_ids = {m["id"] for m, (k, _) in zip(valid, outcomes) if k}
        score["kill"] = _kill_block(mutants, killed_ids, sum(1 for _, t in outcomes if t))
    score["evaluations"] = calls
    return score

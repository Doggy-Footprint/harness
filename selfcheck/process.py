import json
import re
from fnmatch import fnmatch
from pathlib import Path

from analytics import compliance

from . import patches

EDIT_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}
DISPATCH_TOOLS = {"Agent", "Task"}
CHECK_IDS = tuple(f"PC{n}" for n in range(1, 12))
_FILE_KEYS = {"file_path", "notebook_path", "path"}
_MAX_VERIFIER_RESULTS = 2
_MAX_VERIFIER_DISPATCHES = 2


def _read_jsonl(path: Path, skipped: list[int]) -> list[tuple[int, dict]]:
    rows = []
    try:
        text = path.read_text(errors="replace")
    except OSError:
        return rows
    for n, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
        except ValueError:
            obj = None
        if isinstance(obj, dict):
            rows.append((n, obj))
        else:
            skipped[0] += 1
    return rows


def _read_json_object(path: Path):
    try:
        obj = json.loads(path.read_text())
    except (OSError, ValueError):
        return None
    return obj if isinstance(obj, dict) else None


def _load_events(entry_dir: Path, skipped: list[int]) -> list[dict]:
    events = []
    tel = entry_dir / "raw" / "telemetry"
    for path in sorted(tel.glob("*.jsonl")) if tel.is_dir() else []:
        rel = path.relative_to(entry_dir).as_posix()
        for n, obj in _read_jsonl(path, skipped):
            events.append({"obj": obj, "file": rel, "line": n})
    events.sort(key=lambda e: str(e["obj"].get("ts") or ""))
    return events


def _load_ledger(entry_dir: Path, skipped: list[int]) -> list[dict]:
    path = entry_dir / "raw" / "ledger.jsonl"
    rows = []
    for n, obj in _read_jsonl(path, skipped) if path.is_file() else []:
        rows.append({"obj": obj, "file": "raw/ledger.jsonl", "line": n})
    return rows


def _ref(item: dict) -> dict:
    return {"file": item["file"], "line": item["line"]}


def _spec_text(diff: str, run_id: str) -> tuple[str | None, str | None]:
    sections = [s for s in patches.file_sections(diff) if s["is_new"]]
    for source in ("spec-logs", "specs"):
        pattern = f"agent-docs/{source}/{run_id}-*.md"
        for sec in sections:
            if fnmatch(sec["path"], pattern):
                body = sec["text"].split("\n@@", 1)
                added = body[1].split("\n")[1:] if len(body) == 2 else []
                return source, "\n".join(ln[1:] for ln in added if ln.startswith("+"))
    return None, None


def _frontmatter_status(text: str) -> str | None:
    lines = text.split("\n")
    if not lines or lines[0].strip() != "---":
        return None
    for ln in lines[1:]:
        if ln.strip() == "---":
            return None
        m = re.match(r"status:\s*(\S+)", ln)
        if m:
            return m.group(1)
    return None


def _entries_line(text: str, key: str) -> list[str]:
    m = re.search(rf"(?m)^{key}:[ \t]*(.*)$", text)
    if not m:
        return []
    items = [i.strip().strip("`").strip() for i in m.group(1).split(",")]
    return [i for i in items if i]


def _matches(path: str, entry: str) -> bool:
    return path == entry or path.startswith(entry.rstrip("/") + "/") or fnmatch(path, entry)


def _normalize(path) -> str | None:
    if not isinstance(path, str) or not path:
        return None
    if path.startswith("/testbed/"):
        return path[len("/testbed/"):]
    if path.startswith("/"):
        return None
    return path[2:] if path.startswith("./") else path


def _row_paths(obj: dict) -> list[str]:
    tool_input = obj.get("tool_input")
    if not isinstance(tool_input, dict):
        return []
    found = []
    for key in _FILE_KEYS:
        norm = _normalize(tool_input.get(key))
        if norm is not None:
            found.append(norm)
    return found


def _targets(obj: dict, entries: list[str]) -> bool:
    if any(_matches(p, e) for p in _row_paths(obj) for e in entries):
        return True
    tool_input = obj.get("tool_input")
    command = tool_input.get("command") if isinstance(tool_input, dict) else None
    if obj.get("tool_name") != "Bash" or not isinstance(command, str):
        return False
    return any("." in e.rstrip("/").rsplit("/", 1)[-1] and e in command for e in entries)


def _is_dispatch(obj: dict, subagent: str | None = None) -> bool:
    if obj.get("tool_name") not in DISPATCH_TOOLS:
        return False
    tool_input = obj.get("tool_input")
    kind = tool_input.get("subagent_type") if isinstance(tool_input, dict) else None
    return kind == subagent if subagent else kind is not None


def _result(verdict: str, detail: str = "", evidence=()) -> dict:
    return {"verdict": verdict, "detail": detail, "evidence": list(evidence)}


def _na(detail: str = "") -> dict:
    return _result("n/a", detail)


def _seed_pairs(seeds: list[dict]) -> tuple[int, list[dict]]:
    pairs, unpaired, pending = 0, [], None
    for item in seeds:
        action = item["obj"].get("action")
        if pending is None and action == "backup":
            pending = item
        elif pending is not None and action == "restore":
            pairs += 1
            pending = None
        else:
            unpaired.append(item)
    if pending is not None:
        unpaired.append(pending)
    return pairs, unpaired


def _kill_from(event: dict | None) -> dict | None:
    if event is None:
        return None
    mutants, killed = event.get("mutants"), event.get("killed")
    rate = killed / mutants if isinstance(mutants, (int, float)) and mutants and isinstance(
        killed, (int, float)) else None
    return {"mutants": mutants, "killed": killed, "rate": rate}


def evaluate_entry(entry_dir: Path, *, score: dict | None = None) -> dict:
    entry_dir = Path(entry_dir)
    skipped = [0]
    manifest = _read_json_object(entry_dir / "manifest.json") or {}
    instance_id = manifest.get("instance_id") or entry_dir.parent.name
    arm = manifest.get("arm") or entry_dir.name
    events = _load_events(entry_dir, skipped)
    ledger = _load_ledger(entry_dir, skipped)
    diff_path = entry_dir / "raw" / "full.diff"
    diff = diff_path.read_text(errors="replace") if diff_path.is_file() else None
    prediction = _read_json_object(entry_dir / "prediction.json")

    start = next((e for e in events if e["obj"].get("event") == "workflow_start"), None)
    run_id = start["obj"].get("workflow_run_id") if start else None
    run_events = [e for e in events if start and e["obj"].get("workflow_run_id") == run_id]
    end = next((e for e in run_events if e["obj"].get("event") == "workflow_end"), None)
    end_status = end["obj"].get("status") if end else None

    def of(name: str) -> list[dict]:
        return [e for e in run_events if e["obj"].get("event") == name]

    source = spec_text = spec_status = None
    impl: list[str] = []
    tests: list[str] = []
    if diff is not None and run_id:
        source, spec_text = _spec_text(diff, run_id)
    if spec_text is not None:
        spec_status = _frontmatter_status(spec_text)
        impl = _entries_line(spec_text, "Implementation")
        tests = _entries_line(spec_text, "Tests")

    main = [r for r in ledger if r["obj"].get("agent_type") is None]
    spec_write = next(
        (i for i, r in enumerate(ledger)
         if r["obj"].get("tool_name") in EDIT_TOOLS
         and any(_matches(p, "agent-docs/specs/") for p in _row_paths(r["obj"]))),
        None,
    )
    index = {id(r): i for i, r in enumerate(ledger)}
    verifier_results = of("verifier_result")
    verification_results = of("verification_result")
    dispatches = [r for r in main if _is_dispatch(r["obj"], "test-verifier")]

    checks: dict[str, dict] = {}
    if start is None:
        checks["PC1"] = _result("fail", "no workflow_start event")
    else:
        checks["PC1"] = _result("pass", "workflow_start present", [_ref(start)])
    started = checks["PC1"]["verdict"] == "pass"

    compliance_report = compliance.evaluate([e["obj"] for e in events])
    reasons = list(compliance_report["reasons"])
    if not compliance_report["completed"]:
        reasons.append("no_workflow_end")
    if compliance_report["compliant"] is True:
        checks["PC2"] = _result("pass", "compliant")
    else:
        checks["PC2"] = _result(
            "fail", ", ".join(reasons) or "no workflow events", [_ref(end)] if end else []
        )

    if not started:
        checks["PC3"] = _na("no workflow_start")
    else:
        ok = len(verifier_results) <= _MAX_VERIFIER_RESULTS and len(dispatches) <= _MAX_VERIFIER_DISPATCHES
        detail = f"verifier_result={len(verifier_results)} dispatches={len(dispatches)}"
        checks["PC3"] = _result(
            "pass" if ok else "fail", detail,
            [] if ok else [_ref(i) for i in verifier_results + dispatches],
        )

    if end_status != "complete":
        checks["PC4"] = _na("workflow did not end complete")
    else:
        before = [e for e in verification_results if events.index(e) < events.index(end)]
        checks["PC4"] = _result(
            "pass" if before else "fail",
            "verification_result before workflow_end" if before else "no verification_result before workflow_end",
        )

    seeds = [e for e in of("seed") if e["obj"].get("action") in ("backup", "restore")]
    pairs, unpaired = _seed_pairs(seeds)
    if not started:
        checks["PC5"] = _na("no workflow_start")
    else:
        late = [e for e in seeds[-1:] if end and events.index(e) > events.index(end)]
        good = (
            bool(seeds) and not unpaired and seeds[-1]["obj"].get("action") == "restore" and not late
        )
        if not seeds:
            detail = "no seed backup"
        elif good:
            detail = f"{pairs} backup/restore pairs"
        else:
            detail = "backup not followed by restore" if unpaired else "restore after workflow_end"
        evidence = [_ref(i) for i in unpaired] + [_ref(i) for i in late if i not in unpaired]
        checks["PC5"] = _result("pass" if good else "fail", detail, [] if good else evidence)

    if prediction is None:
        checks["PC6"] = _na("no prediction.json")
    else:
        seed = prediction.get("seed")
        before = seed.get("before") if isinstance(seed, dict) else None
        clean = isinstance(before, str) and "seed: none" in before
        checks["PC6"] = _result(
            "pass" if clean else "fail", "seed clean" if clean else "seed pending at end",
            [{"file": "prediction.json", "line": 1}],
        )

    if end_status is None:
        checks["PC7"] = _na("no workflow_end")
    else:
        if end_status in ("complete", "limit", "aborted"):
            good = source == "spec-logs" and spec_status == end_status
        elif end_status == "handoff":
            good = source == "specs" and spec_status == "active"
        else:
            good = False
        detail = f"spec in {source or 'none'} status={spec_status}, workflow_end={end_status}"
        checks["PC7"] = _result("pass" if good else "fail", detail, [_ref(end)] if source else [])

    def edits(rows, entries):
        return [r for r in rows if r["obj"].get("tool_name") in EDIT_TOOLS and _targets(r["obj"], entries)]

    after_spec = ledger[spec_write + 1:] if spec_write is not None else []
    if spec_text is None or spec_write is None:
        checks["PC8"] = _na("no spec text or spec write")
    else:
        bad = edits([r for r in after_spec if r["obj"].get("agent_type") is None], tests)
        checks["PC8"] = _result(
            "fail" if bad else "pass",
            f"{len(bad)} main edits of test files after spec write", [_ref(r) for r in bad],
        )

    if spec_text is None:
        checks["PC9"] = _na("no spec text")
    else:
        bad = [
            r for r in ledger
            if (r["obj"].get("agent_type") == "implementer" and _targets(r["obj"], tests))
            or (r["obj"].get("agent_type") in ("test-implementer", "test-verifier")
                and _targets(r["obj"], impl))
        ]
        checks["PC9"] = _result(
            "fail" if bad else "pass", f"{len(bad)} cross-role accesses", [_ref(r) for r in bad]
        )

    last_result = verifier_results[-1]["obj"].get("result") if verifier_results else None
    anchor = next(
        (r for r in reversed(ledger) if r["obj"].get("agent_type") == "test-verifier"),
        dispatches[-1] if dispatches else None,
    )
    if last_result != "pass":
        checks["PC10"] = _na("last verifier_result is not pass")
    elif anchor is None or spec_text is None:
        checks["PC10"] = _na("no verifier anchor or spec text")
    else:
        bad = edits(ledger[index[id(anchor)] + 1:], impl + tests)
        checks["PC10"] = _result(
            "fail" if bad else "pass", f"{len(bad)} edits after final pass", [_ref(r) for r in bad]
        )

    if score is None or end_status != "complete":
        checks["PC11"] = _na("no score or workflow did not end complete")
    else:
        swt = score.get("swt")
        false_pass = score.get("resolved") is False or (
            isinstance(swt, dict) and swt.get("success") is False
        )
        checks["PC11"] = _result(
            "fail" if false_pass else "pass",
            "complete but unresolved or SWT failed" if false_pass else "score confirms completion",
            [{"file": "prediction.json", "line": 1}] if false_pass else [],
        )

    if arm == "baseline":
        checks = {cid: _na("baseline arm") for cid in CHECK_IDS}
    for c in checks.values():
        if c["verdict"] != "fail":
            c["evidence"] = []

    subagents: dict[str, int] = {}
    for r in main:
        if _is_dispatch(r["obj"]):
            kind = r["obj"]["tool_input"]["subagent_type"]
            subagents[kind] = subagents.get(kind, 0) + 1
    metrics = {
        "verifier_results": len(verifier_results),
        "verifier_dispatches": len(dispatches),
        "seed_pairs": pairs,
        "subagent_dispatches": subagents,
        "main_implementation_edits": len(
            edits([r for r in after_spec if r["obj"].get("agent_type") is None], impl)
        ),
        "self_reported_kill": _kill_from(verification_results[-1]["obj"] if verification_results else None),
        "measured_kill": ((score or {}).get("kill") or {}).get("primary"),
    }
    return {
        "instance_id": instance_id,
        "arm": arm,
        "workflow_run_id": run_id,
        "end_status": end_status,
        "checks": {cid: checks[cid] for cid in CHECK_IDS},
        "metrics": metrics,
        "skipped_lines": skipped[0],
    }

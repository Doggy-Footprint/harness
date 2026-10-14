import json
import subprocess
from pathlib import Path

from . import process

CATEGORIES = ("understanding", "ask_options", "recommendation_evidence", "spec_requirements")
VERDICTS = ("diverged", "consistent", "n/a")
_TRANSCRIPTS = Path("raw") / "claude" / "projects" / "-testbed"
_TOKEN_ERROR = "token found in review output"


class ReviewFormatError(Exception):
    pass


def extract_briefs(entry_dir: Path) -> list[dict]:
    entry_dir = Path(entry_dir)
    root = entry_dir / _TRANSCRIPTS
    briefs = []
    for path in sorted(root.glob("*.jsonl")) if root.is_dir() else []:
        rel = path.relative_to(entry_dir).as_posix()
        for n, obj in process._read_jsonl(path, [0]):
            message = obj.get("message")
            if obj.get("type") != "assistant" or obj.get("isSidechain") or not isinstance(message, dict):
                continue
            content = message.get("content")
            if not isinstance(content, list):
                continue
            blocks = [b for b in content if isinstance(b, dict)]
            text = "\n".join(
                b["text"] for b in blocks if b.get("type") == "text" and isinstance(b.get("text"), str)
            )
            if text.strip():
                briefs.append({"file": rel, "line": n, "kind": "text", "text": text})
            for b in blocks:
                if b.get("type") == "tool_use" and b.get("name") == "AskUserQuestion":
                    questions = (b.get("input") or {}).get("questions")
                    briefs.append({
                        "file": rel, "line": n, "kind": "ask",
                        "text": json.dumps(questions, ensure_ascii=False),
                    })
    return briefs


def load_spec(entry_dir: Path) -> dict | None:
    entry_dir = Path(entry_dir)
    diff_path = entry_dir / "raw" / "full.diff"
    if not diff_path.is_file():
        return None
    events = process._load_events(entry_dir, [0])
    start = next((e for e in events if e["obj"].get("event") == "workflow_start"), None)
    run_id = start["obj"].get("workflow_run_id") if start else None
    if not run_id:
        return None
    source, text = process._spec_text(diff_path.read_text(errors="replace"), run_id)
    return None if source is None else {"source": source, "text": text}


def build_prompt(instance: dict, briefs: list[dict], spec: dict | None) -> str:
    brief_lines = [f"[{b['file']}:{b['line']}] ({b['kind']}) {b['text']}" for b in briefs]
    spec_part = f"[spec] {spec['text']}" if spec else "No spec exists for this run."
    return "\n\n".join([
        "You review the briefs and spec produced by a coding-agent harness while it worked on a "
        "software issue. You are given the gold solution, so you know the correct answer.",
        f"## Issue\n{instance['problem_statement']}",
        f"## Gold patch\n{instance['patch']}",
        f"## Gold test patch\n{instance['test_patch']}",
        f"## FAIL_TO_PASS\n{json.dumps(instance['FAIL_TO_PASS'])}",
        "## Briefs (main-thread assistant messages and AskUserQuestion inputs)\n"
        + ("\n".join(brief_lines) if brief_lines else "(none)"),
        f"## Spec\n{spec_part}",
        "## Task\n"
        f"Judge each of these categories: {', '.join(CATEGORIES)}. For each, give a verdict, one of "
        f"{', '.join(VERDICTS)}: diverged if the briefs/spec diverge from the gold solution, consistent "
        "if they agree, n/a if the category does not apply. Every finding must cite a given "
        "[file:line] or [spec] location. A diverged category needs at least one finding.\n"
        "Set false_claim to true only for a factual claim, checkable against the base repository, the "
        "gold patch or the gold tests, that is false. Never set it for opinions or recommendations.\n"
        "Answer with a single JSON object and nothing else, shaped as "
        '{"categories": {"<category>": {"verdict": "...", "findings": '
        '[{"summary": "...", "citation": "...", "false_claim": false}]}}}.',
    ])


def _extract_object(text: str) -> dict:
    decoder = json.JSONDecoder()
    pos = text.find("{")
    while pos != -1:
        try:
            obj, _ = decoder.raw_decode(text, pos)
        except ValueError:
            pos = text.find("{", pos + 1)
            continue
        if isinstance(obj, dict):
            return obj
        pos = text.find("{", pos + 1)
    raise ReviewFormatError("no JSON object in review output")


def parse_review(text: str) -> dict:
    obj = _extract_object(text)
    cats = obj.get("categories")
    if not isinstance(cats, dict) or set(cats) != set(CATEGORIES):
        raise ReviewFormatError(f"categories must be exactly {', '.join(CATEGORIES)}")
    out = {}
    for cat in CATEGORIES:
        entry = cats[cat]
        if not isinstance(entry, dict) or entry.get("verdict") not in VERDICTS:
            raise ReviewFormatError(f"{cat}: verdict must be one of {', '.join(VERDICTS)}")
        findings = entry.get("findings")
        if not isinstance(findings, list):
            raise ReviewFormatError(f"{cat}: findings must be a list")
        parsed = []
        for f in findings:
            if (
                not isinstance(f, dict)
                or not isinstance(f.get("summary"), str)
                or not isinstance(f.get("citation"), str) or not f["citation"]
                or not isinstance(f.get("false_claim"), bool)
            ):
                raise ReviewFormatError(f"{cat}: finding needs summary, citation, boolean false_claim")
            parsed.append({
                "summary": f["summary"], "citation": f["citation"], "false_claim": f["false_claim"],
            })
        if entry["verdict"] == "diverged" and not parsed:
            raise ReviewFormatError(f"{cat}: diverged needs at least one finding")
        out[cat] = {"verdict": entry["verdict"], "findings": parsed}
    return {"categories": out}


def _error(instance_id: str, reason: str) -> dict:
    return {"status": "error", "instance_id": instance_id, "error": reason}


def _first_line(exc: Exception) -> str:
    lines = str(exc).strip().splitlines()
    return lines[0] if lines else type(exc).__name__


def review_entry(
    entry_dir: Path, instance: dict, *, call_fn, token: str,
    model: str | None = None, effort: str | None = None,
) -> dict:
    entry_dir = Path(entry_dir)
    iid = instance["instance_id"]
    briefs = extract_briefs(entry_dir)
    if not briefs:
        result = _error(iid, "no transcript")
    else:
        try:
            parsed = parse_review(call_fn(build_prompt(instance, briefs, load_spec(entry_dir))))
        except Exception as exc:
            result = _error(iid, _first_line(exc))
        else:
            result = {
                "status": "ok", "instance_id": iid,
                "model": model, "effort": effort,
                "categories": parsed["categories"],
                "false_claims": [
                    {"category": cat, **f}
                    for cat, c in parsed["categories"].items() for f in c["findings"] if f["false_claim"]
                ],
            }
    text = json.dumps(result, indent=1, sort_keys=True)
    if token and token in text:
        return _error(iid, _TOKEN_ERROR)
    (entry_dir / "review.json").write_text(text)
    return result


def claude_call(prompt: str, *, model: str, effort: str, timeout_s: int) -> str:
    try:
        proc = subprocess.run(
            ["claude", "-p", "--model", model, "--effort", effort, "--output-format", "text",
             "--tools", ""],
            input=prompt, text=True, capture_output=True, timeout=timeout_s,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"claude timed out after {timeout_s}s") from exc
    if proc.returncode != 0:
        raise RuntimeError(f"claude exited {proc.returncode}: {(proc.stderr or '').strip()}")
    return proc.stdout

import argparse
import json
import re
import sys
from pathlib import Path

from . import compliance

_WORKFLOW_EVENTS = {"workflow_start", "workflow_phase", "verifier_result", "workflow_end"}
_NON_HUMAN_PREFIXES = ("<task-notification>", "<local-command-", "Another Claude session sent a message")
_SLASH_MARKER = "<command-name>/workflow-approach</command-name>"
_WRITE_TOOLS = ("Write", "Edit", "MultiEdit", "NotebookEdit")
_AGENT_TOOLS = ("Agent", "Task")
_CLOSING_COMMANDS = ("workflow_marker.py end", "spec_lifecycle.py archive")
_RUN_ID_SOURCES = ("workflow_marker.py", "spec_lifecycle.py")
_RUN_ID_PATTERN = re.compile(r"--run-id(?:=|\s+)([^\s'\"]+)")


def _load_object(line: str) -> dict | None:
    try:
        value = json.loads(line)
    except (ValueError, RecursionError):
        return None
    return value if isinstance(value, dict) else None


def _content(record: dict):
    message = record.get("message")
    return message.get("content") if isinstance(message, dict) else None


def _blocks(content) -> list[dict]:
    if not isinstance(content, list):
        return []
    return [block for block in content if isinstance(block, dict)]


def _prompt_text(content) -> str:
    if isinstance(content, str):
        return content
    texts = [block.get("text") for block in _blocks(content) if block.get("type") == "text"]
    return "\n".join(text for text in texts if isinstance(text, str))


def _is_human(record: dict, content, text: str) -> bool:
    origin = record.get("origin")
    if isinstance(origin, dict):
        return origin.get("kind") == "human"
    if text.startswith(_NON_HUMAN_PREFIXES):
        return False
    if isinstance(content, str):
        return True
    blocks = _blocks(content)
    types = [block.get("type") for block in blocks]
    return "text" in types and "tool_result" not in types


def _optional_str(value) -> str | None:
    return value if isinstance(value, str) else None


def _new_request(record: dict, stem: str, index: int, text: str) -> dict:
    session_id = _optional_str(record.get("sessionId"))
    invocation = "slash" if _SLASH_MARKER in text else None
    return {
        "session_id": stem if session_id is None else session_id,
        "request_index": index,
        "timestamp": _optional_str(record.get("timestamp")),
        "cwd": _optional_str(record.get("cwd")),
        "text": text,
        "invoked": invocation is not None,
        "invocation": invocation,
        "subagents": {},
        "spec_writes": [],
        "handoff_writes": [],
        "workflow_state": "none",
        "run_id": None,
        "closes_run": False,
    }


def _assign_runs(requests: list[dict], found: list[dict]) -> None:
    members: list[int] = []

    def close() -> None:
        run_id = next((found[i]["run_id"] for i in members if found[i]["run_id"] is not None), None)
        for i in members:
            requests[i]["run_id"] = run_id
        members.clear()

    for index, request in enumerate(requests):
        request["closes_run"] = found[index]["closing"]
        if request["invocation"] is not None:
            if members:
                close()
            request["workflow_state"] = "start"
        elif members:
            request["workflow_state"] = "continue"
        else:
            continue
        members.append(index)
        if request["closes_run"]:
            close()
    if members:
        close()


def _written_path(tool_input: dict) -> str | None:
    path = _optional_str(tool_input.get("file_path"))
    return path if path is not None else _optional_str(tool_input.get("notebook_path"))


def _add_unique(items: list[str], value: str) -> None:
    if value not in items:
        items.append(value)


def _scan_command(command, found: dict) -> None:
    if not isinstance(command, str):
        return
    if any(marker in command for marker in _CLOSING_COMMANDS):
        found["closing"] = True
    if found["run_id"] is None and any(source in command for source in _RUN_ID_SOURCES):
        match = _RUN_ID_PATTERN.search(command)
        if match:
            found["run_id"] = match.group(1)


def _collect_turn(request: dict, content, found: dict) -> None:
    for block in _blocks(content):
        if block.get("type") != "tool_use":
            continue
        name = block.get("name")
        tool_input = block.get("input")
        if not isinstance(tool_input, dict):
            tool_input = {}
        if name == "Bash":
            _scan_command(tool_input.get("command"), found)
        elif name == "Skill":
            if tool_input.get("skill") == "workflow-approach" and request["invocation"] is None:
                request["invocation"] = "skill"
                request["invoked"] = True
        elif name in _AGENT_TOOLS:
            subagent = tool_input.get("subagent_type")
            if not isinstance(subagent, str) or not subagent:
                subagent = "general-purpose"
            request["subagents"][subagent] = request["subagents"].get(subagent, 0) + 1
        elif name in _WRITE_TOOLS:
            path = _written_path(tool_input)
            if path is None:
                continue
            if "agent-docs/specs/" in path:
                _add_unique(request["spec_writes"], path)
            if "agent-docs/handoff/" in path:
                _add_unique(request["handoff_writes"], path)


def extract_requests(path: Path) -> tuple[list[dict], int] | None:
    requests: list[dict] = []
    skipped = 0
    found: list[dict] = []
    current = None
    try:
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                record = _load_object(line)
                if record is None:
                    skipped += 1
                    continue
                if record.get("isSidechain"):
                    continue
                content = _content(record)
                kind = record.get("type")
                if kind == "user" and not record.get("isMeta"):
                    text = _prompt_text(content)
                    if _is_human(record, content, text):
                        current = _new_request(record, path.stem, len(requests), text)
                        requests.append(current)
                        found.append({"closing": False, "run_id": None})
                elif kind == "assistant" and current is not None:
                    _collect_turn(current, content, found[-1])
    except (OSError, UnicodeDecodeError):
        return None
    _assign_runs(requests, found)
    return requests, skipped


def extract_runs(requests: list[dict]) -> list[dict]:
    runs: list[dict] = []
    current = None
    for request in requests:
        state = request.get("workflow_state")
        if state == "start":
            current = {
                "session_id": request["session_id"],
                "run_id": request.get("run_id"),
                "start_request_index": request["request_index"],
                "continue_turns": 0,
                "closed_by_command": False,
            }
            runs.append(current)
        elif state == "continue" and current is not None:
            current["continue_turns"] += 1
        else:
            current = None
            continue
        current["closed_by_command"] = bool(request.get("closes_run", False))
    return runs


def _event_token(item: dict) -> str:
    name = item["event"]
    if name == "workflow_start":
        return "start"
    if name == "workflow_phase":
        return str(item.get("phase"))
    if name == "verifier_result":
        return f"verifier:{item.get('result')}"
    return f"end:{item.get('status')}"


def _read_events(file: Path) -> tuple[list[dict], int] | None:
    events: list[dict] = []
    skipped = 0
    try:
        # Undecodable bytes must not abort the scan; they surface as skipped lines.
        with file.open(encoding="utf-8", errors="replace") as handle:
            for line in handle:
                if not line.strip():
                    continue
                item = _load_object(line)
                if item is None:
                    skipped += 1
                    continue
                event = item.get("event")
                run_id = item.get("workflow_run_id")
                if not isinstance(event, str) or event not in _WORKFLOW_EVENTS:
                    continue
                if not isinstance(run_id, str) or not run_id:
                    continue
                events.append(item)
    except OSError:
        return None
    return events, skipped


def _read_runs(telemetry_dir: Path) -> tuple[dict[str, list[dict]], int, int]:
    runs: dict[str, list[dict]] = {}
    skipped = 0
    skipped_files = 0
    for file in sorted(telemetry_dir.glob("*.jsonl"), key=lambda item: item.name):
        if not file.is_file():
            continue
        read = _read_events(file)
        if read is None:
            skipped_files += 1
            continue
        events, file_skipped = read
        skipped += file_skipped
        for item in events:
            runs.setdefault(item["workflow_run_id"], []).append(item)
    return runs, skipped, skipped_files


def _hashable_status(item: dict) -> dict:
    # compliance.evaluate puts status into a set lookup, which raises on list/dict.
    status = item.get("status")
    if isinstance(status, (list, dict)):
        return {**item, "status": json.dumps(status, ensure_ascii=False)}
    return item


def mine_variants(telemetry_dir: Path) -> tuple[list[dict], int, int]:
    runs, skipped, skipped_files = _read_runs(telemetry_dir)
    groups: dict[str, dict] = {}
    for run_id, events in runs.items():
        variant = " > ".join(_event_token(item) for item in events)
        result = compliance.evaluate([_hashable_status(item) for item in events])
        group = groups.setdefault(
            variant,
            {
                "variant": variant,
                "count": 0,
                "run_ids": [],
                "compliant": 0,
                "noncompliant": 0,
                "incomplete": 0,
                "reasons": set(),
            },
        )
        group["count"] += 1
        group["run_ids"].append(run_id)
        group["reasons"].update(result["reasons"])
        if not result["completed"]:
            group["incomplete"] += 1
        elif result["compliant"]:
            group["compliant"] += 1
        else:
            group["noncompliant"] += 1
    variants = list(groups.values())
    for group in variants:
        group["run_ids"].sort()
        group["reasons"] = sorted(group["reasons"])
    variants.sort(key=lambda group: (-group["count"], group["variant"]))
    return variants, skipped, skipped_files


_LABEL_FIELDS = ("warranted", "left_workflow")


def _parse_label(line: str) -> tuple[tuple[str, int], dict] | None:
    label = _load_object(line)
    if label is None:
        return None
    session_id = label.get("session_id")
    index = label.get("request_index")
    if not isinstance(session_id, str):
        return None
    if not isinstance(index, int) or isinstance(index, bool) or index < 0:
        return None
    fields = {name: label[name] for name in _LABEL_FIELDS if name in label}
    if not fields or not all(isinstance(value, bool) for value in fields.values()):
        return None
    return (session_id, index), fields


def apply_labels(requests: list[dict], labels_path: Path) -> dict:
    labels: dict[tuple[str, int], dict] = {}
    invalid = 0
    duplicate = 0
    for line in labels_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        parsed = _parse_label(line)
        if parsed is None:
            invalid += 1
            continue
        key, fields = parsed
        if key in labels:
            duplicate += 1
        labels[key] = fields

    confusion = {
        "used": 0,
        "misfire": 0,
        "missed": 0,
        "correct_skip": 0,
        "unlabeled": 0,
    }
    follow = {"left": 0, "stayed": 0, "unlabeled": 0}
    ignored = 0
    matched = set()
    for request in requests:
        key = (request["session_id"], request["request_index"])
        fields = labels.get(key, {})
        warranted = fields.get("warranted")
        left = fields.get("left_workflow")
        request["warranted"] = warranted
        request["left_workflow"] = left
        if fields:
            matched.add(key)
        if request.get("workflow_state") == "continue":
            if left is None:
                follow["unlabeled"] += 1
                ignored += warranted is not None
            else:
                follow["left" if left else "stayed"] += 1
            continue
        if warranted is None:
            confusion["unlabeled"] += 1
            ignored += left is not None
            continue
        invoked = request["invoked"]
        if warranted:
            confusion["used" if invoked else "missed"] += 1
        else:
            confusion["misfire" if invoked else "correct_skip"] += 1
    confusion["continue"] = follow
    confusion["ignored_labels"] = ignored
    confusion["invalid_labels"] = invalid
    confusion["duplicate_labels"] = duplicate
    confusion["unmatched_labels"] = len(labels.keys() - matched)
    return confusion


def build_report(transcripts_root: Path, telemetry_dir: Path, labels_path: Path | None) -> dict:
    requests: list[dict] = []
    runs: list[dict] = []
    skipped_lines = 0
    skipped_files = 0
    files = [path for path in transcripts_root.glob("*/*.jsonl") if path.is_file()]
    for path in sorted(files, key=str):
        extracted = extract_requests(path)
        if extracted is None:
            skipped_files += 1
            continue
        file_requests, skipped = extracted
        requests.extend(file_requests)
        runs.extend(extract_runs(file_requests))
        skipped_lines += skipped
    variants, telemetry_skipped, telemetry_files = mine_variants(telemetry_dir)
    confusion = apply_labels(requests, labels_path) if labels_path is not None else None
    return {
        "requests": requests,
        "runs": runs,
        "variants": variants,
        "confusion": confusion,
        "skipped_lines": skipped_lines + telemetry_skipped,
        "skipped_files": skipped_files + telemetry_files,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python3 -m analytics.usage")
    parser.add_argument("--transcripts", type=Path, default=Path.home() / ".claude" / "projects")
    parser.add_argument("--telemetry", type=Path, default=Path.home() / ".harness" / "telemetry")
    parser.add_argument("--labels", type=Path, default=None)
    args = parser.parse_args(argv)
    try:
        report = build_report(args.transcripts, args.telemetry, args.labels)
    except (OSError, UnicodeDecodeError) as error:
        print(f"cannot read labels {args.labels}: {error}", file=sys.stderr)
        return 2
    print(json.dumps(report, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

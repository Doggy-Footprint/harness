#!/usr/bin/env python3
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))
import config  # noqa: E402
import hook_shared  # noqa: E402
import telemetry  # noqa: E402

PATHS = config.load_paths()
REPO_ROOT = config.REPO_ROOT
CONTRACTS_DIR = PATHS.contracts
RUNNING_DIR = CONTRACTS_DIR / ".running"
GATED_AGENTS = {"implementer", "test-implementer"}


def marker_path(payload: dict) -> Path:
    key = payload.get("agent_id") or payload.get("agent_type") or ""
    return RUNNING_DIR / re.sub(r"[^A-Za-z0-9._-]", "_", key)


def on_subagent_start(payload: dict) -> int:
    telemetry.emit(payload, "subagent_start")
    if payload.get("agent_type") not in GATED_AGENTS or not CONTRACTS_DIR.is_dir():
        return 0
    RUNNING_DIR.mkdir(exist_ok=True)
    marker_path(payload).write_text(payload["agent_type"], encoding="utf-8")
    return 0


def on_subagent_stop(payload: dict) -> int:
    telemetry.emit(payload, "subagent_stop")
    if payload.get("agent_type") in GATED_AGENTS:
        marker_path(payload).unlink(missing_ok=True)
    return 0


def on_pre_tool_use(payload: dict) -> int:
    if not RUNNING_DIR.is_dir():
        return 0
    running = sorted(RUNNING_DIR.iterdir())
    # Exact match only: subagents run narrower test invocations that must stay unblocked.
    if not running or hook_shared.normalize(hook_shared.shell_command(payload.get("tool_input"))) not in hook_shared.test_commands(CONTRACTS_DIR):
        return 0
    agent_types = sorted(m.read_text(encoding="utf-8") for m in running)
    telemetry.emit(payload, "gate_block", running=agent_types)
    listing = ", ".join(
        f"{m.read_text(encoding='utf-8')} ({m.relative_to(REPO_ROOT)})" for m in running
    )
    print(
        f"contract-workflow: `Test command` is blocked until these subagents report: {listing}. "
        "If a subagent is no longer running, delete its marker file.",
        file=sys.stderr,
    )
    return 2


HANDLERS = {
    "SubagentStart": on_subagent_start,
    "SubagentStop": on_subagent_stop,
    "PreToolUse": on_pre_tool_use,
}


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError:
        return 0
    handler = HANDLERS.get(payload.get("hook_event_name"))
    return handler(payload) if handler else 0


if __name__ == "__main__":
    sys.exit(main())

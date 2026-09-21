"""Best-effort workflow event log for contract-workflow hooks.

Every failure here (unwritable dir, missing VERSION, bad payload) is
swallowed: telemetry must never change hook exit codes or stderr (U5).
"""
import datetime
import json
import os
import re
from pathlib import Path

import config

_VERSION_FILE = config._HARNESS_DIR / "VERSION"


def telemetry_file() -> Path:
    override = os.environ.get("HARNESS_TELEMETRY_DIR")
    directory = Path(override) if override else Path.home() / ".harness" / "telemetry"
    slug = re.sub(r"[^A-Za-z0-9]", "-", str(config.REPO_ROOT))
    return directory / f"{slug}.jsonl"


def _harness_version():
    try:
        return _VERSION_FILE.read_text(encoding="utf-8").strip()
    except OSError:
        return None


def _client(payload: dict):
    transcript_path = payload.get("transcript_path") or ""
    if "/.codex/" in transcript_path:
        return "codex"
    if "/.claude/" in transcript_path:
        return "claude"
    return None


def emit(payload: dict, event: str, **fields) -> None:
    try:
        line = {
            "v": 1,
            "ts": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "harness_version": _harness_version(),
            "repo": str(config.REPO_ROOT),
            "client": _client(payload),
            "session_id": payload.get("session_id"),
            "agent_id": payload.get("agent_id"),
            "agent_type": payload.get("agent_type"),
            "tool_use_id": payload.get("tool_use_id"),
            "event": event,
            **fields,
        }
        path = telemetry_file()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(line, ensure_ascii=False) + "\n")
    except Exception:
        pass

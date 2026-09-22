import hashlib
import json
import sqlite3
from pathlib import Path

from .store import initialize


_FIELDS = {
    "v", "ts", "repo", "client", "session_id", "agent_id", "agent_type",
    "tool_use_id", "event", "workflow_run_id", "spec", "spec_version",
    "phase", "status", "result", "round", "findings", "seeds_run",
    "seeds_detected",
}


def _event(raw: dict) -> dict | None:
    if not isinstance(raw, dict):
        return None
    if not isinstance(raw.get("workflow_run_id"), str) or not isinstance(raw.get("event"), str):
        return None
    if not isinstance(raw.get("spec"), str) or not isinstance(raw.get("spec_version"), int):
        return None
    return {
        key: raw[key]
        for key in _FIELDS
        if key in raw and isinstance(raw[key], (str, int, float, bool, type(None)))
    }


def _prefix(data: bytes, offset: int) -> str:
    return hashlib.sha256(data[:offset]).hexdigest()


def import_pending(connection: sqlite3.Connection, telemetry_dir: Path) -> None:
    initialize(connection)
    if not telemetry_dir.is_dir():
        return
    for path in sorted(candidate for candidate in telemetry_dir.rglob("*.jsonl") if candidate.is_file()):
        source = str(path.resolve())
        data = path.read_bytes()
        row = connection.execute("SELECT offset, prefix_hash FROM sources WHERE path=?", (source,)).fetchone()
        offset = int(row[0]) if row else 0
        if row and (offset > len(data) or row[1] != _prefix(data, offset)):
            connection.execute("DELETE FROM events WHERE source_path=?", (source,))
            offset = 0
        position = offset
        while position < len(data):
            end = data.find(b"\n", position)
            if end < 0:
                break
            try:
                raw = json.loads(data[position:end].decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                break
            item = _event(raw)
            if item is None:
                break
            connection.execute(
                "INSERT OR IGNORE INTO events(source_path,source_offset,run_id,spec,spec_version,event,timestamp,client,session_id,payload) VALUES(?,?,?,?,?,?,?,?,?,?)",
                (source, position, item["workflow_run_id"], item["spec"], item["spec_version"],
                 item["event"], item.get("ts"), item.get("client"), item.get("session_id"),
                 json.dumps(item, separators=(",", ":"))),
            )
            position = end + 1
        connection.execute(
            "INSERT INTO sources(path,offset,prefix_hash) VALUES(?,?,?) ON CONFLICT(path) DO UPDATE SET offset=excluded.offset,prefix_hash=excluded.prefix_hash",
            (source, position, _prefix(data, position)),
        )
    connection.commit()


def _records(path: Path) -> list[dict]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return []
    records = []
    for line in lines:
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            return []
        if isinstance(value, dict):
            records.append(value)
    return records


def transcript_session_id(path: Path, client: str | None) -> str | None:
    for item in _records(path):
        if client == "claude" and isinstance(item.get("sessionId"), str):
            return item["sessionId"]
        if client == "codex" and item.get("type") == "session_meta":
            payload = item.get("payload")
            if isinstance(payload, dict) and isinstance(payload.get("id"), str):
                return payload["id"]
    return None


def transcript_usage(path: Path, client: str | None) -> dict[str, int | str | None]:
    records = _records(path)
    if not records:
        return {}
    totals = {"model": None, "input_tokens": 0, "output_tokens": 0,
              "cache_read_tokens": 0, "cache_write_5m_tokens": 0,
              "cache_write_1h_tokens": 0}
    found = False
    if client == "claude":
        for item in records:
            message = item.get("message")
            usage = message.get("usage") if isinstance(message, dict) else None
            if not isinstance(usage, dict):
                continue
            if message.get("model"):
                totals["model"] = str(message["model"])
            totals["input_tokens"] += int(usage.get("input_tokens", 0) or 0)
            totals["output_tokens"] += int(usage.get("output_tokens", 0) or 0)
            totals["cache_read_tokens"] += int(usage.get("cache_read_input_tokens", 0) or 0)
            creation = usage.get("cache_creation")
            if isinstance(creation, dict):
                totals["cache_write_5m_tokens"] += int(creation.get("ephemeral_5m_input_tokens", 0) or 0)
                totals["cache_write_1h_tokens"] += int(creation.get("ephemeral_1h_input_tokens", 0) or 0)
            found = True
    elif client == "codex":
        latest = None
        for item in records:
            payload = item.get("payload")
            if item.get("type") == "session_meta" and isinstance(payload, dict) and payload.get("model"):
                totals["model"] = str(payload["model"])
            if item.get("type") == "event_msg" and isinstance(payload, dict):
                info = payload.get("info")
                if payload.get("type") == "token_count" and isinstance(info, dict) and isinstance(info.get("last_token_usage"), dict):
                    latest = info["last_token_usage"]
        if latest is not None:
            cached = int(latest.get("cached_input_tokens", 0) or 0)
            totals["input_tokens"] = max(0, int(latest.get("input_tokens", 0) or 0) - cached)
            totals["output_tokens"] = int(latest.get("output_tokens", 0) or 0)
            totals["cache_read_tokens"] = cached
            found = True
    return totals if found and totals["model"] else {}

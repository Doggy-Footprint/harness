import hashlib
import json
import sqlite3
from pathlib import Path

from .store import initialize
# Re-exported: existing tests import transcript_session_id/transcript_usage
# from analytics.importer even though transcript parsing now lives in
# transcripts.py.
from .transcripts import transcript_session_id, transcript_usage  # noqa: F401


_FIELDS = {
    "v", "ts", "repo", "client", "session_id", "agent_id", "agent_type",
    "tool_use_id", "event", "workflow_run_id", "spec", "spec_version",
    "phase", "status", "result", "round", "findings", "seeds_run",
    "seeds_detected",
}


def _event(raw: dict) -> dict | None:
    if not isinstance(raw, dict):
        return None
    if not isinstance(raw.get("event"), str):
        return None
    run_id = raw.get("workflow_run_id")
    if run_id is not None and not isinstance(run_id, str):
        return None
    spec = raw.get("spec")
    if not isinstance(spec, str):
        spec = None
    spec_version = raw.get("spec_version")
    if not isinstance(spec_version, int) or isinstance(spec_version, bool):
        spec_version = None
    item = {
        key: raw[key]
        for key in _FIELDS
        if key in raw and isinstance(raw[key], (str, int, float, bool, type(None)))
    }
    item["workflow_run_id"] = run_id
    item["spec"] = spec
    item["spec_version"] = spec_version
    return item


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
                # Incomplete final line: leave the offset before it so a
                # later import re-reads it once the newline arrives (FR2).
                break
            next_position = end + 1
            try:
                raw = json.loads(data[position:end].decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                position = next_position
                continue
            item = _event(raw)
            if item is None:
                position = next_position
                continue
            connection.execute(
                "INSERT OR IGNORE INTO events(source_path,source_offset,run_id,spec,spec_version,event,timestamp,client,session_id,payload) VALUES(?,?,?,?,?,?,?,?,?,?)",
                (source, position, item["workflow_run_id"], item["spec"], item["spec_version"],
                 item["event"], item.get("ts"), item.get("client"), item.get("session_id"),
                 json.dumps(item, separators=(",", ":"))),
            )
            position = next_position
        connection.execute(
            "INSERT INTO sources(path,offset,prefix_hash) VALUES(?,?,?) ON CONFLICT(path) DO UPDATE SET offset=excluded.offset,prefix_hash=excluded.prefix_hash",
            (source, position, _prefix(data, position)),
        )
    connection.commit()

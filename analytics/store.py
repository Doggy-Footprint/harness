import json
import sqlite3


def initialize(connection: sqlite3.Connection) -> None:
    connection.executescript("""
    PRAGMA foreign_keys = ON;
    CREATE TABLE IF NOT EXISTS sources (
      path TEXT PRIMARY KEY, offset INTEGER NOT NULL DEFAULT 0,
      prefix_hash TEXT NOT NULL DEFAULT ''
    );
    CREATE TABLE IF NOT EXISTS events (
      id INTEGER PRIMARY KEY, source_path TEXT NOT NULL, source_offset INTEGER NOT NULL,
      run_id TEXT NOT NULL, spec TEXT, spec_version INTEGER, event TEXT NOT NULL,
      timestamp TEXT, client TEXT, session_id TEXT, payload TEXT NOT NULL,
      UNIQUE(source_path, source_offset)
    );
    CREATE INDEX IF NOT EXISTS events_run ON events(run_id, id);
    """)


def event_dict(row: sqlite3.Row) -> dict:
    value = json.loads(row["payload"])
    value.update({"workflow_run_id": row["run_id"]})
    value.update({key: row[key] for key in ("spec", "spec_version", "event", "client", "session_id") if row[key] is not None})
    if row["timestamp"] is not None:
        value["ts"] = row["timestamp"]
    return value

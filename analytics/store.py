import json
import sqlite3

# events.run_id became nullable (FR4) and a transcript_cache table was added
# (FR6); bump so pre-existing sqlite files (run_id NOT NULL, no cache table)
# get their derived events/sources recreated instead of failing inserts.
SCHEMA_VERSION = 2


def initialize(connection: sqlite3.Connection) -> None:
    connection.execute(
        "CREATE TABLE IF NOT EXISTS schema_meta (version INTEGER NOT NULL)"
    )
    row = connection.execute("SELECT version FROM schema_meta").fetchone()
    current = row[0] if row else 0
    if current < SCHEMA_VERSION:
        connection.executescript("DROP TABLE IF EXISTS events; DROP TABLE IF EXISTS sources;")
        connection.execute("DELETE FROM schema_meta")
        connection.execute("INSERT INTO schema_meta(version) VALUES (?)", (SCHEMA_VERSION,))
    connection.executescript("""
    PRAGMA foreign_keys = ON;
    CREATE TABLE IF NOT EXISTS sources (
      path TEXT PRIMARY KEY, offset INTEGER NOT NULL DEFAULT 0,
      prefix_hash TEXT NOT NULL DEFAULT ''
    );
    CREATE TABLE IF NOT EXISTS events (
      id INTEGER PRIMARY KEY, source_path TEXT NOT NULL, source_offset INTEGER NOT NULL,
      run_id TEXT, spec TEXT, spec_version INTEGER, event TEXT NOT NULL,
      timestamp TEXT, client TEXT, session_id TEXT, payload TEXT NOT NULL,
      UNIQUE(source_path, source_offset)
    );
    CREATE INDEX IF NOT EXISTS events_run ON events(run_id, id);
    CREATE TABLE IF NOT EXISTS transcript_cache (
      path TEXT PRIMARY KEY, size INTEGER NOT NULL, mtime REAL NOT NULL,
      client TEXT NOT NULL, data TEXT
    );
    """)
    connection.commit()


def event_dict(row: sqlite3.Row) -> dict:
    value = json.loads(row["payload"])
    value.update({"workflow_run_id": row["run_id"]})
    value.update({key: row[key] for key in ("spec", "spec_version", "event", "client", "session_id") if row[key] is not None})
    if row["timestamp"] is not None:
        value["ts"] = row["timestamp"]
    return value

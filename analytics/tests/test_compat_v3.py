import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from analytics.app import create_app


class OldSchemaCompatibilityV3Tests(unittest.TestCase):
    """Independent oracle for spec v3 VO7 (QR3): create_app must start against a
    pre-change sqlite file whose events.run_id is NOT NULL, and existing
    /api/summary fields must still be present."""

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.telemetry_dir = self.root / "telemetry"
        self.telemetry_dir.mkdir()
        self.prices = self.root / "prices.yaml"
        self.prices.write_text(
            "models:\n  known-model:\n    input: 1\n    output: 1\n    cache_read: 1\n"
            "    cache_write_5m: 1\n    cache_write_1h: 1\n", encoding="utf-8")
        self.transcripts = {"claude": self.root / "claude", "codex": self.root / "codex"}
        for directory in self.transcripts.values():
            directory.mkdir()

    def create_old_schema_db(self, db_path):
        connection = sqlite3.connect(db_path)
        connection.execute(
            "CREATE TABLE sources (path TEXT PRIMARY KEY, offset INTEGER, prefix_hash TEXT)")
        connection.execute(
            "CREATE TABLE events (id INTEGER PRIMARY KEY, source_path TEXT, source_offset INTEGER, "
            "run_id TEXT NOT NULL, spec TEXT, spec_version INTEGER, event TEXT, timestamp TEXT, "
            "client TEXT, session_id TEXT, payload TEXT, UNIQUE(source_path, source_offset))")
        connection.execute(
            "INSERT INTO sources (path, offset, prefix_hash) VALUES (?, ?, ?)",
            ("stale.jsonl", 0, "deadbeef"))
        connection.execute(
            "INSERT INTO events (source_path, source_offset, run_id, spec, spec_version, event, "
            "timestamp, client, session_id, payload) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("stale.jsonl", 0, "stale-run", "analytics", 1, "workflow_start",
             "2026-01-01T00:00:00+00:00", "claude", "stale-session", "{}"))
        connection.commit()
        connection.close()

    def workflow_events(self, run_id):
        base = {"v": 1, "ts": "2026-09-22T00:00:00+00:00", "client": "claude", "session_id": "claude-1",
                "workflow_run_id": run_id, "spec": "analytics", "spec_version": 1}
        return [
            {**base, "event": "workflow_start"},
            {**base, "event": "workflow_phase", "phase": "implement_test"},
            {**base, "event": "workflow_phase", "phase": "verify"},
            {**base, "event": "verifier_result", "round": 1, "result": "pass", "findings": 0,
             "seeds_run": 0, "seeds_detected": 0},
            {**base, "event": "workflow_end", "status": "complete"},
        ]

    def test_v7_starts_and_reimports_against_a_not_null_run_id_schema_file(self):
        db_path = self.root / "old.sqlite3"
        self.create_old_schema_db(db_path)
        (self.telemetry_dir / "repo.jsonl").write_text(
            "".join(json.dumps(e) + "\n" for e in self.workflow_events("run-new")), encoding="utf-8")

        client = TestClient(create_app(db_path, self.telemetry_dir, self.prices, self.transcripts, frontend_dir=None))
        summary = client.get("/api/summary").json()
        for existing_field in ("runs", "completed_runs", "compliant_runs", "run_items"):
            self.assertIn(existing_field, summary)
        self.assertEqual(summary["runs"], 1)
        run_ids = {item["run_id"] for item in summary["run_items"]}
        self.assertIn("run-new", run_ids)
        detail = client.get("/api/runs/run-new").json()
        self.assertEqual(detail["status"], "complete")

    def test_v7_a2_null_workflow_run_id_events_do_not_violate_the_migrated_schema(self):
        """A2/FR4: the pre-change schema forbade a null run_id; after migration
        (events recreated from telemetry) a null-run event must import cleanly."""
        db_path = self.root / "old_with_null_case.sqlite3"
        self.create_old_schema_db(db_path)
        null_run_event = {"v": 1, "ts": "2026-09-22T00:00:00+00:00", "client": "claude",
                           "session_id": "claude-orphan", "event": "subagent_stop",
                           "workflow_run_id": None, "spec": None}
        (self.telemetry_dir / "repo.jsonl").write_text(json.dumps(null_run_event) + "\n", encoding="utf-8")
        client = TestClient(create_app(db_path, self.telemetry_dir, self.prices, self.transcripts, frontend_dir=None))
        summary = client.get("/api/summary").json()
        self.assertEqual(summary["runs"], 0)


if __name__ == "__main__":
    unittest.main()

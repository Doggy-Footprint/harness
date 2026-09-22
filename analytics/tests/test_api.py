import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from analytics.app import create_app


EVENT_SECRET = "EVENT_PRIVATE_PROMPT"
CLAUDE_SECRET = "CLAUDE_PRIVATE_RESPONSE"
CODEX_SECRET = "CODEX_PRIVATE_RESPONSE"


class ApiTests(unittest.TestCase):
    """Public API integration oracle for spec v2 V1-V5/V7 and Q1-Q5."""

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.telemetry_dir = self.root / "telemetry"
        self.telemetry_dir.mkdir()
        self.db_path = self.root / "analytics.sqlite3"
        self.prices = self.root / "prices.yaml"
        self.prices.write_text(
            "models:\n  claude-model:\n    input: 1\n    output: 2\n    cache_read: 0.25\n    cache_write_5m: 1.25\n    cache_write_1h: 2.25\n  codex-model:\n    input: 3\n    output: 4\n    cache_read: 0.5\n    cache_write_5m: 1.5\n    cache_write_1h: 2.5\n",
            encoding="utf-8")
        self.transcripts = {"claude": self.root / "claude", "codex": self.root / "codex"}
        for directory in self.transcripts.values(): directory.mkdir()
        self.client = TestClient(create_app(self.db_path, self.telemetry_dir, self.prices, self.transcripts, frontend_dir=None))

    def event(self, name, run_id="run-1", *, client="claude", session_id="claude-1", **fields):
        return {"v": 1, "ts": "2026-09-22T00:00:00+00:00", "repo": "/repo", "client": client,
                "session_id": session_id, "agent_id": None, "agent_type": None, "tool_use_id": None,
                "event": name, "workflow_run_id": run_id, "spec": "analytics", "spec_version": 1, **fields}

    def completed(self, run_id="run-1", *, status="complete", result="pass", client="claude", session_id="claude-1"):
        return [self.event("workflow_start", run_id, client=client, session_id=session_id),
                self.event("workflow_phase", run_id, client=client, session_id=session_id, phase="implement_test"),
                self.event("workflow_phase", run_id, client=client, session_id=session_id, phase="verify"),
                self.event("verifier_result", run_id, client=client, session_id=session_id, round=1, result=result,
                           findings=1 if result == "retry" else 0, seeds_run=2, seeds_detected=1),
                self.event("workflow_end", run_id, client=client, session_id=session_id, status=status)]

    def early_terminal(self, run_id, status):
        return [self.event("workflow_start", run_id), self.event("workflow_end", run_id, status=status)]

    def write_events(self, records, filename="repo.jsonl", mode="a"):
        path = self.telemetry_dir / filename
        with path.open(mode, encoding="utf-8") as stream:
            for record in records: stream.write(json.dumps(record) + "\n")
        return path

    def test_v1_first_repeat_append_and_rewrite_are_idempotent(self):
        path = self.write_events(self.completed())
        first = self.client.get("/api/summary").json()
        self.assertEqual(self.client.get("/api/summary").json(), first)
        self.assertEqual((first["runs"], first["completed_runs"], first["compliant_runs"]), (1, 1, 1))
        self.write_events(self.completed("run-2", status="handoff", result="retry"), mode="a")
        appended = self.client.get("/api/summary").json()
        self.assertEqual((appended["runs"], appended["handoff_runs"], appended["verifier_rounds"], appended["verifier_retries"]), (2, 1, 2, 1))
        path.write_text("".join(json.dumps(item) + "\n" for item in self.completed() + self.completed("run-2", status="handoff", result="retry")), encoding="utf-8")
        rewritten = self.client.get("/api/summary").json()
        self.assertEqual(rewritten, appended)

    def test_v1_malformed_middle_and_partial_tail_preserve_retry_position(self):
        first, second = self.completed()[:2]
        path = self.telemetry_dir / "broken.jsonl"
        path.write_text(json.dumps(first) + "\n{broken}\n" + json.dumps(second)[:-2], encoding="utf-8")
        self.assertEqual(self.client.get("/api/summary").json()["runs"], 1)
        path.write_text("".join(json.dumps(item) + "\n" for item in self.completed()), encoding="utf-8")
        self.assertEqual(len(self.client.get("/api/runs/run-1").json()["events"]), 5)

    def test_v1_missing_input_is_empty_and_unknown_run_does_not_mutate(self):
        missing = self.root / "missing"
        client = TestClient(create_app(self.root / "empty.sqlite3", missing, self.prices, self.transcripts))
        self.assertEqual(client.get("/api/summary").json()["runs"], 0)
        self.write_events(self.completed())
        before = self.client.get("/api/summary").json()
        self.assertEqual(self.client.get("/api/runs/unknown").status_code, 404)
        self.assertEqual(self.client.get("/api/summary").json(), before)

    def test_v2_status_counts_and_in_progress_exclusion(self):
        self.write_events(self.completed("pass"))
        self.write_events(self.early_terminal("handoff", "handoff"))
        self.write_events(self.completed("limit", status="limit", result="limit"))
        self.write_events(self.early_terminal("aborted", "aborted"))
        self.write_events(self.completed("open")[:-1])
        summary = self.client.get("/api/summary").json()
        self.assertEqual((summary["runs"], summary["completed_runs"], summary["compliant_runs"], summary["handoff_runs"]), (5, 4, 4, 1))
        item = next(value for value in summary["run_items"] if value["run_id"] == "open")
        self.assertEqual((item["status"], item["compliant"]), ("in_progress", None))

    def test_v3_v4_multiple_client_sessions_price_and_unknown_null_propagation(self):
        self.write_events(self.completed("known", client="claude", session_id="claude-1"))
        self.write_events(self.completed("known", client="codex", session_id="codex-1"))
        self.write_events(self.completed("unknown", session_id="unknown-1"))
        (self.transcripts["claude"] / "deep").mkdir()
        (self.transcripts["claude"] / "deep" / "claude-1.jsonl").write_text(json.dumps({"sessionId": "claude-1", "type": "assistant", "message": {"model": "claude-model", "content": CLAUDE_SECRET, "usage": {"input_tokens": 1_000_000, "output_tokens": 500_000}}}) + "\n", encoding="utf-8")
        (self.transcripts["codex"] / "codex-1.jsonl").write_text(json.dumps({"type": "session_meta", "payload": {"id": "codex-1", "model": "codex-model"}}) + "\n" + json.dumps({"type": "event_msg", "payload": {"type": "token_count", "info": {"last_token_usage": {"input_tokens": 1_000_000, "cached_input_tokens": 0, "output_tokens": 0}}}}) + "\n", encoding="utf-8")
        (self.transcripts["claude"] / "unknown-1.jsonl").write_text(json.dumps({"sessionId": "unknown-1", "type": "assistant", "message": {"model": "unknown", "usage": {"input_tokens": 1}}}) + "\n", encoding="utf-8")
        known = self.client.get("/api/runs/known").json()
        self.assertEqual(len(known["transcript_metadata"]), 2)
        self.assertEqual(known["linked_cost_usd"], 5.0)
        unknown = self.client.get("/api/runs/unknown").json()
        self.assertEqual(len(unknown["transcript_metadata"]), 1)
        self.assertIsNone(unknown["transcript_metadata"][0]["linked_cost_usd"])
        self.assertIsNone(unknown["linked_cost_usd"])
        self.assertIsNone(self.client.get("/api/summary").json()["linked_cost_usd"])

    def test_v4_mixed_priced_and_unpriced_sessions_null_run_and_summary_total(self):
        self.write_events(self.completed("mixed", client="claude", session_id="mixed-claude"))
        self.write_events(self.completed("mixed", client="claude", session_id="mixed-unknown"))
        (self.transcripts["claude"] / "mixed-claude.jsonl").write_text(json.dumps({"sessionId": "mixed-claude", "type": "assistant", "message": {"model": "claude-model", "usage": {"input_tokens": 1_000_000, "output_tokens": 500_000}}}) + "\n", encoding="utf-8")
        (self.transcripts["claude"] / "mixed-unknown.jsonl").write_text(json.dumps({"sessionId": "mixed-unknown", "type": "assistant", "message": {"model": "unknown-model", "usage": {"input_tokens": 1}}}) + "\n", encoding="utf-8")
        mixed = self.client.get("/api/runs/mixed").json()
        self.assertEqual(len(mixed["transcript_metadata"]), 2)
        priced_entry = next(entry for entry in mixed["transcript_metadata"] if entry["session_id"] == "mixed-claude")
        unpriced_entry = next(entry for entry in mixed["transcript_metadata"] if entry["session_id"] == "mixed-unknown")
        self.assertEqual(priced_entry["linked_cost_usd"], 2.0)
        self.assertIsNone(unpriced_entry["linked_cost_usd"])
        self.assertIsNone(mixed["linked_cost_usd"])
        self.assertIsNone(self.client.get("/api/summary").json()["linked_cost_usd"])

    def test_v7_event_and_transcript_content_never_crosses_persistence_boundary(self):
        self.write_events([{**item, "unapproved": EVENT_SECRET} for item in self.completed()])
        (self.transcripts["claude"] / "claude-1.jsonl").write_text(json.dumps({"sessionId": "claude-1", "type": "assistant", "message": {"model": "claude-model", "content": CLAUDE_SECRET, "usage": {"input_tokens": 1}}}) + "\n", encoding="utf-8")
        (self.transcripts["codex"] / "other.jsonl").write_text(json.dumps({"type": "response_item", "payload": {"content": CODEX_SECRET}}) + "\n", encoding="utf-8")
        response = self.client.get("/api/runs/run-1")
        self.assertEqual(response.status_code, 200)
        stored_start = response.json()["events"][0]
        self.assertTrue({"v", "ts", "repo", "client", "session_id", "agent_id", "agent_type", "tool_use_id", "event", "workflow_run_id", "spec", "spec_version"}.issubset(stored_start))
        self.assertEqual((stored_start["workflow_run_id"], stored_start["spec"], stored_start["spec_version"]), ("run-1", "analytics", 1))
        self.assertNotIn("unapproved", stored_start)
        all_output = response.text + self.client.get("/api/summary").text + self.db_path.read_bytes().decode("utf-8", errors="ignore")
        for secret in (EVENT_SECRET, CLAUDE_SECRET, CODEX_SECRET): self.assertNotIn(secret, all_output)

    def test_v5_factory_static_fallback_does_not_shadow_api(self):
        frontend = self.root / "dist"; frontend.mkdir()
        (frontend / "index.html").write_text("<main>dashboard</main>", encoding="utf-8")
        client = TestClient(create_app(self.root / "static.sqlite3", self.telemetry_dir, self.prices, self.transcripts, frontend))
        self.assertEqual(client.get("/api/health").json(), {"status": "ok"})
        self.assertIn("dashboard", client.get("/").text)
        self.assertIn("dashboard", client.get("/runs/run-1").text)
        self.assertEqual(client.get("/api/summary").headers["content-type"].split(";")[0], "application/json")

    def test_v2_completed_noncompliant_runs_reach_summary_and_detail_as_noncompliant(self):
        duplicate_start = self.completed("dup-start")
        duplicate_start.insert(1, self.event("workflow_start", "dup-start"))
        self.write_events(self.completed("good") + duplicate_start + self.completed("stale-pass", result="retry"))
        summary = self.client.get("/api/summary").json()
        self.assertEqual((summary["runs"], summary["completed_runs"], summary["compliant_runs"]), (3, 3, 1))
        items = {item["run_id"]: item["compliant"] for item in summary["run_items"]}
        self.assertEqual(items, {"good": True, "dup-start": False, "stale-pass": False})
        for run_id in ("dup-start", "stale-pass"):
            detail = self.client.get(f"/api/runs/{run_id}").json()
            self.assertIs(detail["compliant"], False)
            self.assertTrue(detail["compliance_reasons"])
        self.assertIn("expected_one_start", self.client.get("/api/runs/dup-start").json()["compliance_reasons"])
        good = self.client.get("/api/runs/good").json()
        self.assertEqual((good["compliant"], good["compliance_reasons"]), (True, []))

    def test_v1_reimport_after_restart_keeps_positions_without_duplicates(self):
        self.write_events(self.completed())
        self.assertEqual(len(self.client.get("/api/runs/run-1").json()["events"]), 5)
        restarted = TestClient(create_app(self.db_path, self.telemetry_dir, self.prices, self.transcripts, frontend_dir=None))
        self.assertEqual(len(restarted.get("/api/runs/run-1").json()["events"]), 5)
        self.write_events(self.completed("run-2"))
        restarted_again = TestClient(create_app(self.db_path, self.telemetry_dir, self.prices, self.transcripts, frontend_dir=None))
        summary = restarted_again.get("/api/summary").json()
        self.assertEqual((summary["runs"], summary["completed_runs"]), (2, 2))
        self.assertEqual(len(restarted_again.get("/api/runs/run-1").json()["events"]), 5)
        self.assertEqual(len(restarted_again.get("/api/runs/run-2").json()["events"]), 5)
        with sqlite3.connect(self.db_path) as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM events").fetchone()[0], 10)


if __name__ == "__main__":
    unittest.main()

import json
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from analytics.app import create_app


class SummaryClassificationV3Tests(unittest.TestCase):
    """Independent oracle for spec v4 VO4 (FR10-FR12, C9, C10): decision table
    {linked, unlinked} x {known, unknown model} at the GET /api/summary and
    GET /api/runs/{run_id} surface. Fixture shapes follow the v4 Signatures
    fix for non_workflow/workflow (F5 correction)."""

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

    def make_client(self):
        return TestClient(create_app(self.root / "analytics.sqlite3", self.telemetry_dir, self.prices,
                                      self.transcripts, frontend_dir=None))

    def workflow_events(self, run_id, session_id):
        base = {"v": 1, "ts": "2026-09-22T00:00:00+00:00", "client": "claude", "session_id": session_id,
                "workflow_run_id": run_id, "spec": "analytics", "spec_version": 1}
        return [
            {**base, "event": "workflow_start"},
            {**base, "event": "workflow_phase", "phase": "implement_test"},
            {**base, "event": "workflow_phase", "phase": "verify"},
            {**base, "event": "verifier_result", "round": 1, "result": "pass", "findings": 0,
             "seeds_run": 0, "seeds_detected": 0},
            {**base, "event": "workflow_end", "status": "complete"},
        ]

    def write_transcript(self, session_id, model, input_tokens):
        (self.transcripts["claude"] / f"{session_id}.jsonl").write_text(
            json.dumps({"type": "assistant", "sessionId": session_id,
                        "message": {"model": model, "usage": {"input_tokens": input_tokens, "output_tokens": 0}}}) + "\n",
            encoding="utf-8")

    def test_c9_c10_linked_and_unlinked_sessions_with_known_and_unknown_models(self):
        events = []
        events += self.workflow_events("run-linked-known", "claude-linked-known")
        events += self.workflow_events("run-linked-unknown", "claude-linked-unknown")
        (self.telemetry_dir / "repo.jsonl").write_text(
            "".join(json.dumps(e) + "\n" for e in events), encoding="utf-8")

        self.write_transcript("claude-linked-known", "known-model", 1_000_000)
        self.write_transcript("claude-linked-unknown", "unlisted-model", 1_000_000)
        self.write_transcript("claude-unlinked-known", "known-model", 2_000_000)
        self.write_transcript("claude-unlinked-unknown", "unlisted-model", 500_000)

        client = self.make_client()
        summary = client.get("/api/summary").json()

        # linked+known: contributes to the run's known cost, not to non_workflow.
        linked_known_detail = client.get("/api/runs/run-linked-known").json()
        priced = next(e for e in linked_known_detail["transcript_metadata"] if e["session_id"] == "claude-linked-known")
        self.assertEqual(priced["linked_cost_usd"], 1.0)

        # linked+unknown: run-level cost for that session is null, not silently zero.
        linked_unknown_detail = client.get("/api/runs/run-linked-unknown").json()
        unpriced = next(e for e in linked_unknown_detail["transcript_metadata"] if e["session_id"] == "claude-linked-unknown")
        self.assertIsNone(unpriced["linked_cost_usd"])

        # unlinked+known: appears under non_workflow with known-model cost.
        non_workflow = summary["non_workflow"]
        self.assertIsInstance(non_workflow["sessions"], int)
        self.assertGreaterEqual(non_workflow["sessions"], 1)
        self.assertIn("known-model", non_workflow["cost"]["by_model"])
        self.assertEqual(non_workflow["cost"]["by_model"]["known-model"], 2.0)
        known_tokens = non_workflow["cost"]["tokens_by_model"]["known-model"]
        self.assertEqual(known_tokens["input_tokens"], 2_000_000)

        # unlinked+unknown: listed in unknown_models, does not corrupt total_usd,
        # and its by_model entry (if present) is null rather than a fabricated 0.
        self.assertIn("unlisted-model", non_workflow["cost"]["unknown_models"])
        self.assertIsNone(non_workflow["cost"]["by_model"].get("unlisted-model"))
        self.assertEqual(non_workflow["cost"]["total_usd"], non_workflow["cost"]["by_model"]["known-model"])

        # workflow.runs carries a FR12 run summary for each workflow run,
        # including the two linked runs created above.
        workflow_run_ids = {entry["run_id"] for entry in summary["workflow"]["runs"]}
        self.assertEqual(workflow_run_ids, {"run-linked-known", "run-linked-unknown"})

    def test_summary_keeps_existing_top_level_fields_and_adds_workflow_and_non_workflow(self):
        """Signatures: existing /api/summary fields are kept unchanged; "workflow"
        and "non_workflow" are additive sections."""
        self.write_transcript("claude-none", "known-model", 1)
        client = self.make_client()
        summary = client.get("/api/summary").json()
        for existing_field in ("runs", "completed_runs", "compliant_runs", "handoff_runs",
                                "verifier_rounds", "verifier_retries", "seeds_run", "seeds_detected",
                                "linked_cost_usd", "run_items"):
            self.assertIn(existing_field, summary)
        self.assertIsInstance(summary["workflow"], dict)
        self.assertIn("runs", summary["workflow"])
        self.assertIsInstance(summary["workflow"]["runs"], list)
        self.assertIsInstance(summary["non_workflow"], dict)
        for key in ("sessions", "tools", "cost", "subagents"):
            self.assertIn(key, summary["non_workflow"])
        for key in ("by_model", "tokens_by_model", "total_usd", "unknown_models"):
            self.assertIn(key, summary["non_workflow"]["cost"])


if __name__ == "__main__":
    unittest.main()

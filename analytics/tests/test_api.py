import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from analytics.app import create_app


PRIVATE_TEXT = "PRIVATE PROMPT PRIVATE RESPONSE"


class ApiTests(unittest.TestCase):
    """Contract v4: U1-U5; A1-A3/A5/A7-A10; V1-V4/V6/V7/V9."""

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.telemetry_dir = self.root / "telemetry"
        self.telemetry_dir.mkdir()
        self.db_path = self.root / "analytics.sqlite3"
        self.prices = self.root / "config.yaml"
        self.prices.write_text(
            "models:\n"
            "  claude-model:\n"
            "    input: 1\n"
            "    output: 2\n"
            "    cache_read: 0.25\n"
            "    cache_write_5m: 1.25\n"
            "    cache_write_1h: 2.25\n",
            encoding="utf-8",
        )
        self.transcripts = {"claude": self.root / "claude", "codex": self.root / "codex"}
        for directory in self.transcripts.values():
            directory.mkdir()
        self.client = TestClient(
            create_app(self.db_path, self.telemetry_dir, self.prices, self.transcripts, frontend_dir=None)
        )

    def event(self, name, run_id="run-1", **fields):
        return {
            "v": 1,
            "ts": fields.pop("ts", "2026-09-22T00:00:00+00:00"),
            "repo": "/repo",
            "client": "claude",
            "session_id": "session-1",
            "agent_id": None,
            "agent_type": None,
            "tool_use_id": None,
            "event": name,
            "workflow_run_id": run_id,
            "contract": "sample",
            **fields,
        }

    def completed(self, run_id="run-1", status="complete", verifier_result="pass"):
        return [
            self.event("workflow_start", run_id, contract_version=1),
            self.event("workflow_phase", run_id, phase="implement_test"),
            self.event("workflow_phase", run_id, phase="verify"),
            self.event(
                "verifier_result",
                run_id,
                round=1,
                result=verifier_result,
                findings=1 if verifier_result == "retry" else 0,
                seeds_run=2,
                seeds_detected=1,
            ),
            self.event("workflow_end", run_id, status=status),
        ]

    def append(self, records, suffix=""):
        path = self.telemetry_dir / f"repo{suffix}.jsonl"
        with path.open("a", encoding="utf-8") as stream:
            for record in records:
                stream.write(json.dumps(record) + "\n")
        return path

    def test_v1_v2_v6_first_and_repeated_import_then_append_are_incremental(self):
        path = self.append(self.completed())
        first = self.client.get("/api/summary")
        second = self.client.get("/api/summary")
        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.json(), first.json())
        self.assertEqual(first.json()["runs"], 1)
        self.assertEqual(first.json()["completed_runs"], 1)
        self.assertEqual(first.json()["compliant_runs"], 1)

        with path.open("a", encoding="utf-8") as stream:
            for record in self.completed("run-2", status="handoff", verifier_result="retry"):
                stream.write(json.dumps(record) + "\n")
        detail = self.client.get("/api/runs/run-2")
        summary = self.client.get("/api/summary").json()
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(summary["runs"], 2)
        self.assertEqual(summary["handoff_runs"], 1)
        self.assertEqual(summary["verifier_rounds"], 2)
        self.assertEqual(summary["verifier_retries"], 1)
        self.assertEqual(summary["seeds_run"], 4)
        self.assertEqual(summary["seeds_detected"], 2)
        self.assertEqual({item["run_id"] for item in summary["run_items"]}, {"run-1", "run-2"})

    def test_v1_malformed_middle_and_partial_tail_do_not_advance_progress(self):
        path = self.telemetry_dir / "broken.jsonl"
        first = self.completed()[0]
        second = self.completed()[1]
        path.write_text(json.dumps(first) + "\n{broken}\n" + json.dumps(second)[:-2], encoding="utf-8")
        response = self.client.get("/api/summary")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["runs"], 1)

        path.write_text(
            json.dumps(first) + "\n" + json.dumps(second) + "\n" + "".join(
                json.dumps(record) + "\n" for record in self.completed()[2:]
            ),
            encoding="utf-8",
        )
        detail = self.client.get("/api/runs/run-1").json()
        self.assertEqual(len(detail["events"]), 5)

    def test_v1_missing_directory_is_an_empty_success(self):
        missing = self.root / "missing"
        client = TestClient(create_app(self.root / "empty.db", missing, self.prices, self.transcripts))
        response = client.get("/api/summary")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["runs"], 0)

    def test_v3_unknown_run_is_404_without_mutating_data(self):
        self.append(self.completed())
        before = self.client.get("/api/summary").json()
        response = self.client.get("/api/runs/missing")
        after = self.client.get("/api/summary").json()
        self.assertEqual(response.status_code, 404)
        self.assertEqual(after, before)

    def test_v4_v9_transcript_metadata_and_cost_exclude_content(self):
        self.append(self.completed())
        transcript = self.transcripts["claude"] / "nested" / "session.jsonl"
        transcript.parent.mkdir()
        transcript.write_text(
            json.dumps({"sessionId": "session-1", "type": "user", "message": {"content": PRIVATE_TEXT}})
            + "\n"
            + json.dumps(
                {
                    "sessionId": "session-1",
                    "type": "assistant",
                    "message": {
                        "model": "claude-model",
                        "content": PRIVATE_TEXT,
                        "usage": {"input_tokens": 1_000_000, "output_tokens": 500_000},
                    },
                }
            )
            + "\n",
            encoding="utf-8",
        )
        response = self.client.get("/api/runs/run-1")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["linked_cost_usd"], 2.0)
        self.assertEqual(body["transcript_metadata"]["model"], "claude-model")
        self.assertNotIn(PRIVATE_TEXT, response.text)
        self.assertNotIn(PRIVATE_TEXT.encode(), self.db_path.read_bytes())

    def test_v4_unknown_model_keeps_usage_and_returns_null_cost(self):
        self.append(self.completed())
        transcript = self.transcripts["claude"] / "session.jsonl"
        transcript.write_text(
            json.dumps(
                {
                    "sessionId": "session-1",
                    "type": "assistant",
                    "message": {"model": "unknown", "usage": {"input_tokens": 10}},
                }
            )
            + "\n",
            encoding="utf-8",
        )
        body = self.client.get("/api/runs/run-1").json()
        self.assertEqual(body["transcript_metadata"]["input_tokens"], 10)
        self.assertIsNone(body["linked_cost_usd"])

    def test_v7_factory_serves_dashboard_and_client_side_route_without_shadowing_api(self):
        frontend = self.root / "dist"
        frontend.mkdir()
        (frontend / "index.html").write_text("<main>dashboard sentinel</main>", encoding="utf-8")
        client = TestClient(
            create_app(self.root / "static.db", self.telemetry_dir, self.prices, self.transcripts, frontend)
        )
        self.assertIn("dashboard sentinel", client.get("/").text)
        self.assertIn("dashboard sentinel", client.get("/runs/run-1").text)
        self.assertEqual(client.get("/api/summary").headers["content-type"].split(";")[0], "application/json")


if __name__ == "__main__":
    unittest.main()

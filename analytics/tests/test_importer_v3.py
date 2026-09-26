import json
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from analytics.app import create_app


class ImporterV3Tests(unittest.TestCase):
    """Independent oracle for spec v3 VO1 (FR1-FR4, C1-C5).

    Equivalence classes exercised at the import_pending -> sqlite/API surface:
    valid-workflow, null-run, run-no-version, non-dict, broken-json-with-newline,
    partial-last-line, truncated-file.
    """

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.telemetry_dir = self.root / "telemetry"
        self.telemetry_dir.mkdir()
        self.db_path = self.root / "analytics.sqlite3"
        self.prices = self.root / "prices.yaml"
        self.prices.write_text(
            "models:\n  model-a:\n    input: 1\n    output: 2\n    cache_read: 0.25\n"
            "    cache_write_5m: 1.25\n    cache_write_1h: 2.25\n", encoding="utf-8")
        self.transcripts = {"claude": self.root / "claude", "codex": self.root / "codex"}
        for directory in self.transcripts.values():
            directory.mkdir()
        self.client = TestClient(create_app(self.db_path, self.telemetry_dir, self.prices, self.transcripts, frontend_dir=None))

    def event(self, name, run_id="run-1", *, client="claude", session_id="claude-1", **fields):
        return {"v": 1, "ts": "2026-09-22T00:00:00+00:00", "client": client, "session_id": session_id,
                "agent_type": None, "event": name, "workflow_run_id": run_id, "spec": "analytics",
                "spec_version": 1, **fields}

    def full_run(self, run_id="run-1", **kwargs):
        return [self.event("workflow_start", run_id, **kwargs),
                self.event("workflow_phase", run_id, phase="implement_test", **kwargs),
                self.event("workflow_phase", run_id, phase="verify", **kwargs),
                self.event("verifier_result", run_id, round=1, result="pass", findings=0,
                           seeds_run=1, seeds_detected=1, **kwargs),
                self.event("workflow_end", run_id, status="complete", **kwargs)]

    def write(self, path_name, text, mode="w"):
        path = self.telemetry_dir / path_name
        with path.open(mode, encoding="utf-8") as stream:
            stream.write(text)
        return path

    def lines(self, records):
        return "".join(json.dumps(record) + "\n" for record in records)

    def test_c1_null_run_event_precedes_a_full_run_and_is_not_a_run_but_is_stored(self):
        """FR1/FR4, C1: a null-workflow_run_id line is skipped for run purposes but
        stored so a paired transcript session still counts as non_workflow."""
        null_run_event = {"v": 1, "ts": "2026-09-22T00:00:00+00:00", "client": "claude",
                           "session_id": "claude-orphan", "event": "subagent_stop",
                           "workflow_run_id": None, "spec": None, "agent_type": "general-purpose"}
        self.write("repo.jsonl", self.lines([null_run_event, *self.full_run("run-1")]))
        summary = self.client.get("/api/summary").json()
        self.assertEqual(summary["runs"], 1)
        detail = self.client.get("/api/runs/run-1").json()
        self.assertEqual(detail["status"], "complete")
        self.assertEqual(self.client.get("/api/runs/claude-orphan").status_code, 404)
        (self.transcripts["claude"] / "claude-orphan.jsonl").write_text(
            json.dumps({"sessionId": "claude-orphan", "type": "assistant",
                        "message": {"model": "model-a", "usage": {"input_tokens": 1}}}) + "\n",
            encoding="utf-8")
        after_transcript = self.client.get("/api/summary").json()
        self.assertGreaterEqual(after_transcript["non_workflow"]["sessions"], 1)

    def test_c2_run_tagged_event_without_spec_version_is_attributed_to_the_run(self):
        """FR3, C2: subagent_start missing spec_version is folded into run-1's events
        and does not affect compliance (FR5 ignores it)."""
        events = self.full_run("run-1")
        tagged = {"v": 1, "ts": "2026-09-22T00:00:01+00:00", "client": "claude",
                   "session_id": "claude-1", "event": "subagent_start",
                   "workflow_run_id": "run-1", "agent_type": "reviewer"}
        events = [events[0], events[1], tagged, events[2], events[3], events[4]]
        self.write("repo.jsonl", self.lines(events))
        detail = self.client.get("/api/runs/run-1").json()
        self.assertEqual(detail["compliant"], True)
        matching = [item for item in detail["events"] if item["event"] == "subagent_start"]
        self.assertEqual(len(matching), 1)
        self.assertEqual(matching[0]["spec"], "analytics")
        self.assertEqual(matching[0]["spec_version"], 1)

    def test_non_dict_json_lines_are_skipped_and_do_not_stop_the_stream(self):
        """FR1: a syntactically valid but non-dict JSON line is dropped; later
        lines in the same file still import."""
        events = self.full_run("run-1")
        text = (json.dumps(events[0]) + "\n" + "42\n" + json.dumps(events[1]) + "\n" +
                "[1,2,3]\n" + self.lines(events[2:]))
        self.write("repo.jsonl", text)
        detail = self.client.get("/api/runs/run-1").json()
        self.assertEqual(len(detail["events"]), 5)
        self.assertEqual(detail["status"], "complete")

    def test_c4_broken_json_line_with_trailing_newline_is_skipped(self):
        """FR2, C4: a newline-terminated line that fails to parse is skipped;
        the run is still complete with exactly the 5 valid events."""
        events = self.full_run("run-1")
        text = (self.lines(events[:2]) + "{not-json,\n" + self.lines(events[2:]))
        self.write("repo.jsonl", text)
        detail = self.client.get("/api/runs/run-1").json()
        self.assertEqual(len(detail["events"]), 5)
        self.assertEqual(detail["status"], "complete")

    def test_c3_partial_last_line_is_excluded_until_completed_then_imported_once(self):
        """FR2, C3: a last line missing its trailing newline is not imported;
        after the newline appears the line imports exactly once."""
        events = self.full_run("run-1")
        path = self.write("repo.jsonl", self.lines(events[:4]) + json.dumps(events[4]))
        first = self.client.get("/api/summary").json()
        first_item = next(item for item in first["run_items"] if item["run_id"] == "run-1")
        self.assertEqual(first_item["status"], "in_progress")
        self.assertEqual(len(self.client.get("/api/runs/run-1").json()["events"]), 4)

        with path.open("a", encoding="utf-8") as stream:
            stream.write("\n")
        second_detail = self.client.get("/api/runs/run-1").json()
        self.assertEqual(second_detail["status"], "complete")
        self.assertEqual(len(second_detail["events"]), 5)

        third_detail = self.client.get("/api/runs/run-1").json()
        self.assertEqual(len(third_detail["events"]), 5)

    def test_c5_truncated_file_is_reimported_from_scratch_without_duplicates(self):
        """Errors: truncate/rewrite (prefix hash mismatch) deletes the file's
        prior events and reimports from the start with no duplication."""
        path = self.write("repo.jsonl", self.lines(self.full_run("run-a")))
        baseline = self.client.get("/api/summary").json()
        self.assertEqual(baseline["runs"], 1)

        path.write_text(self.lines(self.full_run("run-b")), encoding="utf-8")
        after_truncate = self.client.get("/api/summary").json()
        self.assertEqual(after_truncate["runs"], 1)
        run_ids = {item["run_id"] for item in after_truncate["run_items"]}
        self.assertEqual(run_ids, {"run-b"})
        self.assertEqual(self.client.get("/api/runs/run-a").status_code, 404)
        self.assertEqual(len(self.client.get("/api/runs/run-b").json()["events"]), 5)


if __name__ == "__main__":
    unittest.main()

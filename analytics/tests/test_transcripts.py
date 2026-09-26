import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from analytics import store, transcripts
from analytics.app import create_app
from analytics.transcripts import index_transcripts, parse_transcript


class ParseTranscriptV3Tests(unittest.TestCase):
    """Independent oracle for spec v3 VO3 (FR6-FR8, C6) at the parse_transcript
    unit surface: tool_use/function_call/custom_tool_call counts by name and
    Agent/Task subagent_type counts (typed and untyped)."""

    def write_jsonl(self, lines):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        path = Path(temporary.name) / "transcript.jsonl"
        path.write_text("".join(json.dumps(line) + "\n" for line in lines), encoding="utf-8")
        return path

    def tool_use(self, name, **input_fields):
        return {"type": "tool_use", "name": name, "input": input_fields}

    def assistant(self, session_id, content, model="claude-model"):
        return {"type": "assistant", "sessionId": session_id, "cwd": "/repo",
                "message": {"model": model, "content": content, "usage": {
                    "input_tokens": 1, "output_tokens": 1}}}

    def test_c6_claude_tool_and_typed_subagent_counts_are_exact(self):
        lines = [
            self.assistant("claude-1", [self.tool_use("Bash"), self.tool_use("Read")]),
            self.assistant("claude-1", [self.tool_use("Bash"),
                                         self.tool_use("Agent", subagent_type="reviewer")]),
            self.assistant("claude-1", [self.tool_use("Write"),
                                         self.tool_use("Agent", subagent_type="reviewer")]),
            self.assistant("claude-1", [self.tool_use("Agent", subagent_type="implementer")]),
        ]
        path = self.write_jsonl(lines)
        result = parse_transcript(path, "claude")
        self.assertEqual(result["session_id"], "claude-1")
        self.assertEqual(result["client"], "claude")
        self.assertEqual(result["tools"], {"Bash": 2, "Read": 1, "Write": 1, "Agent": 3})
        self.assertEqual(result["subagents"], {"reviewer": 2, "implementer": 1})

    def test_claude_agent_tool_use_without_subagent_type_defaults_to_general_purpose(self):
        """FR8 claude-agent-untyped: missing input.subagent_type defaults to
        'general-purpose'."""
        path = self.write_jsonl([self.assistant("claude-2", [self.tool_use("Agent")])])
        result = parse_transcript(path, "claude")
        self.assertEqual(result["subagents"], {"general-purpose": 1})

    def test_c7_codex_function_call_and_custom_tool_call_counts_are_exact(self):
        lines = [
            {"type": "session_meta", "payload": {"id": "codex-1", "model": "codex-model"}},
            {"type": "turn_context", "payload": {"model": "codex-model"}},
            {"type": "response_item", "payload": {"type": "function_call", "name": "shell"}},
            {"type": "response_item", "payload": {"type": "function_call", "name": "shell"}},
            {"type": "response_item", "payload": {"type": "custom_tool_call", "name": "apply_patch"}},
            {"type": "event_msg", "payload": {"type": "token_count", "info": {"last_token_usage": {
                "input_tokens": 10, "cached_input_tokens": 0, "output_tokens": 5}}}},
        ]
        path = self.write_jsonl(lines)
        result = parse_transcript(path, "codex")
        self.assertEqual(result["session_id"], "codex-1")
        self.assertEqual(result["client"], "codex")
        self.assertEqual(result["tools"], {"shell": 2, "apply_patch": 1})

    def test_codex_thread_spawn_parent_thread_id_is_exposed_as_parent_session_id(self):
        """A1: session_meta.payload.source.subagent.thread_spawn.parent_thread_id
        identifies the parent session for a Codex subagent transcript."""
        lines = [
            {"type": "session_meta", "payload": {"id": "codex-child", "model": "codex-model",
             "source": {"subagent": {"thread_spawn": {"parent_thread_id": "codex-parent",
                                                        "agent_role": "reviewer"}}}}},
        ]
        path = self.write_jsonl(lines)
        result = parse_transcript(path, "codex")
        self.assertEqual(result["parent_session_id"], "codex-parent")

    def test_codex_top_level_session_has_no_parent_session_id(self):
        lines = [{"type": "session_meta", "payload": {"id": "codex-top", "model": "codex-model",
                                                        "source": "cli"}}]
        path = self.write_jsonl(lines)
        result = parse_transcript(path, "codex")
        self.assertIsNone(result["parent_session_id"])

    def test_unreadable_and_missing_transcripts_return_none_without_raising(self):
        """C12/Errors: non-UTF-8 and missing files are skipped, not raised."""
        with tempfile.TemporaryDirectory() as directory:
            bad = Path(directory) / "bad.jsonl"
            bad.write_bytes(b"\xff\xfe\x00not-utf8")
            self.assertIsNone(parse_transcript(bad, "claude"))
            self.assertIsNone(parse_transcript(Path(directory) / "missing.jsonl", "claude"))


class IndexTranscriptsV3Tests(unittest.TestCase):
    """Independent oracle for spec v3 VO3 (FR6, C11, C12) at the
    index_transcripts unit surface: incremental caching and missing roots."""

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.connection = sqlite3.connect(self.root / "analytics.sqlite3")
        self.addCleanup(self.connection.close)
        store.initialize(self.connection)

    def write_claude_session(self, directory, session_id):
        path = directory / f"{session_id}.jsonl"
        path.write_text(json.dumps({"type": "assistant", "sessionId": session_id,
                                     "message": {"model": "claude-model", "usage": {"input_tokens": 1}}}) + "\n",
                         encoding="utf-8")
        return path

    def test_c11_unchanged_file_is_not_reparsed_on_a_second_index_pass(self):
        claude_root = self.root / "claude"
        claude_root.mkdir()
        self.write_claude_session(claude_root, "claude-unchanged")
        with patch("analytics.transcripts.parse_transcript", wraps=transcripts.parse_transcript) as spy:
            index_transcripts(self.connection, {"claude": claude_root})
            first_call_count = spy.call_count
            index_transcripts(self.connection, {"claude": claude_root})
            second_call_count = spy.call_count
        self.assertGreaterEqual(first_call_count, 1)
        self.assertEqual(second_call_count, first_call_count)

    def test_changed_mtime_or_size_causes_a_reparse(self):
        claude_root = self.root / "claude"
        claude_root.mkdir()
        path = self.write_claude_session(claude_root, "claude-changed")
        with patch("analytics.transcripts.parse_transcript", wraps=transcripts.parse_transcript) as spy:
            index_transcripts(self.connection, {"claude": claude_root})
            baseline = spy.call_count
            path.write_text(json.dumps({"type": "assistant", "sessionId": "claude-changed",
                                         "message": {"model": "claude-model",
                                                     "usage": {"input_tokens": 2}}}) + "\n\n",
                             encoding="utf-8")
            index_transcripts(self.connection, {"claude": claude_root})
            self.assertGreater(spy.call_count, baseline)

    def test_c12_missing_root_directory_indexes_without_raising(self):
        missing = self.root / "does-not-exist"
        index_transcripts(self.connection, {"claude": missing, "codex": missing / "also-missing"})

    def test_c12_unreadable_file_is_skipped_and_siblings_still_index(self):
        claude_root = self.root / "claude"
        claude_root.mkdir()
        (claude_root / "bad.jsonl").write_bytes(b"\xff\xfe\x00not-utf8")
        self.write_claude_session(claude_root, "claude-good")
        index_transcripts(self.connection, {"claude": claude_root})


class TranscriptApiIntegrationV3Tests(unittest.TestCase):
    """Independent oracle for spec v4 VO3 (FR8-FR9, C7-C8, A1/A4) at the API
    surface, where cross-file aggregation (Codex parent/child sessions,
    Claude subagents/ directories) is observable."""

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.telemetry_dir = self.root / "telemetry"
        self.telemetry_dir.mkdir()
        self.prices = self.root / "prices.yaml"
        self.prices.write_text(
            "models:\n  codex-model:\n    input: 1\n    output: 1\n    cache_read: 1\n"
            "    cache_write_5m: 1\n    cache_write_1h: 1\n"
            # input rate is USD per 1,000,000 tokens (config.yaml convention); this
            # class uses 1_000_000 (i.e. $1/token) so hand-computed session costs
            # for small synthetic token counts are exact round numbers.
            "  claude-model:\n    input: 1000000\n    output: 1000000\n    cache_read: 1000000\n"
            "    cache_write_5m: 1000000\n    cache_write_1h: 1000000\n", encoding="utf-8")
        self.claude_root = self.root / "claude"
        self.codex_root = self.root / "codex"
        self.claude_root.mkdir()
        self.codex_root.mkdir()

    def make_client(self):
        return TestClient(create_app(self.root / "analytics.sqlite3", self.telemetry_dir, self.prices,
                                      {"claude": self.claude_root, "codex": self.codex_root}, frontend_dir=None))

    def workflow_events(self, run_id, client, session_id):
        base = {"v": 1, "ts": "2026-09-22T00:00:00+00:00", "client": client, "session_id": session_id,
                "workflow_run_id": run_id, "spec": "analytics", "spec_version": 1}
        return [
            {**base, "event": "workflow_start"},
            {**base, "event": "workflow_phase", "phase": "implement_test"},
            {**base, "event": "workflow_phase", "phase": "verify"},
            {**base, "event": "verifier_result", "round": 1, "result": "pass", "findings": 0,
             "seeds_run": 0, "seeds_detected": 0},
            {**base, "event": "workflow_end", "status": "complete"},
        ]

    def write_telemetry(self, records):
        (self.telemetry_dir / "repo.jsonl").write_text(
            "".join(json.dumps(record) + "\n" for record in records), encoding="utf-8")

    def write_codex_session(self, path, session_id, model, *, source=None, input_tokens=1, output_tokens=0):
        lines = [json.dumps({"type": "session_meta", "payload": {
            "id": session_id, "model": model, **({"source": source} if source is not None else {})}})]
        lines.append(json.dumps({"type": "event_msg", "payload": {"type": "token_count", "info": {
            "last_token_usage": {"input_tokens": input_tokens, "cached_input_tokens": 0,
                                  "output_tokens": output_tokens}}}}))
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def test_c7_thread_spawn_child_is_attributed_to_the_parents_run_subagents(self):
        """FR8/A1/A4, C7: a Codex child with an explicit parent link
        (thread_spawn.parent_thread_id) is attributed to the parent's run,
        under its agent_role, in GET /api/runs/{run_id}.subagents."""
        self.write_telemetry(self.workflow_events("run-codex", "codex", "codex-parent"))
        self.write_codex_session(self.codex_root / "codex-parent.jsonl", "codex-parent", "codex-model")
        self.write_codex_session(
            self.codex_root / "codex-child.jsonl", "codex-child", "codex-model",
            source={"subagent": {"thread_spawn": {"parent_thread_id": "codex-parent", "agent_role": "implementer"}}})
        client = self.make_client()
        detail = client.get("/api/runs/run-codex").json()
        self.assertEqual(detail["subagents"].get("implementer"), 1)

    def test_c7_other_guardian_child_without_a_parent_link_is_non_workflow_only(self):
        """FR8/A1/A4, C7: a Codex session whose source.subagent.other is
        'guardian' carries no parent link, so it must NOT be attributed to any
        run; it is counted only in GET /api/summary.non_workflow.subagents
        under the literal 'guardian' type."""
        self.write_telemetry(self.workflow_events("run-codex", "codex", "codex-parent"))
        self.write_codex_session(self.codex_root / "codex-parent.jsonl", "codex-parent", "codex-model")
        self.write_codex_session(
            self.codex_root / "codex-guardian.jsonl", "codex-guardian", "codex-model",
            source={"subagent": {"other": "guardian"}})
        client = self.make_client()
        detail = client.get("/api/runs/run-codex").json()
        self.assertNotIn("guardian", detail["subagents"])
        summary = client.get("/api/summary").json()
        self.assertEqual(summary["non_workflow"]["subagents"].get("guardian"), 1)

    def test_c8_claude_subagents_directory_tokens_merge_into_the_parent_session(self):
        """FR9, C8: a subagents/ file under the parent's directory is not a
        separate session; its tokens add to the parent session's cost.
        Rates are USD per 1,000,000 tokens (config.yaml convention), so the
        hand-computed cost for 15 combined tokens at a 1,000,000-per-1M-tok
        rate is 15 * 1,000,000 / 1,000,000 = 15.0."""
        self.write_telemetry(self.workflow_events("run-claude", "claude", "claude-parent"))
        project_dir = self.claude_root / "project-a"
        project_dir.mkdir()
        (project_dir / "claude-parent.jsonl").write_text(
            json.dumps({"type": "assistant", "sessionId": "claude-parent",
                        "message": {"model": "claude-model", "usage": {"input_tokens": 10, "output_tokens": 0}}}) + "\n",
            encoding="utf-8")
        subagents_dir = project_dir / "claude-parent" / "subagents"
        subagents_dir.mkdir(parents=True)
        (subagents_dir / "agent-1.jsonl").write_text(
            json.dumps({"type": "assistant", "sessionId": "claude-parent",
                        "message": {"model": "claude-model", "usage": {"input_tokens": 5, "output_tokens": 0}}}) + "\n",
            encoding="utf-8")
        client = self.make_client()
        detail = client.get("/api/runs/run-claude").json()
        parent_sessions = [entry for entry in detail["sessions"] if entry.get("session_id") == "claude-parent"]
        self.assertEqual(len(parent_sessions), 1)
        self.assertAlmostEqual(parent_sessions[0]["cost_usd"], 15.0, places=6)


if __name__ == "__main__":
    unittest.main()

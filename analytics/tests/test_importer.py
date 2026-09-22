import json
import tempfile
import unittest
from pathlib import Path

from analytics.importer import transcript_usage


PRIVATE_PROMPT = "EVENT_PRIVATE_PROMPT"
PRIVATE_RESPONSE = "EVENT_PRIVATE_RESPONSE"


class TranscriptUsageTests(unittest.TestCase):
    """Independent metadata-boundary oracle for spec v1 V3/V7/Q5."""

    def write_jsonl(self, records):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        path = Path(temporary.name) / "transcript.jsonl"
        path.write_text("".join(json.dumps(record) + "\n" for record in records), encoding="utf-8")
        return path

    def assert_metadata_only(self, usage):
        serialized = json.dumps(usage)
        self.assertNotIn(PRIVATE_PROMPT, serialized)
        self.assertNotIn(PRIVATE_RESPONSE, serialized)

    def test_v3_claude_usage_is_normalized_without_content(self):
        path = self.write_jsonl([
            {"sessionId": "claude-1", "type": "user", "message": {"content": PRIVATE_PROMPT}},
            {"sessionId": "claude-1", "type": "assistant", "message": {
                "model": "claude-model", "content": PRIVATE_RESPONSE,
                "usage": {"input_tokens": 10, "output_tokens": 20, "cache_read_input_tokens": 30,
                          "cache_creation": {"ephemeral_5m_input_tokens": 40, "ephemeral_1h_input_tokens": 50}},
            }},
        ])
        usage = transcript_usage(path, "claude")
        self.assertEqual(usage, {"model": "claude-model", "input_tokens": 10, "output_tokens": 20,
                                 "cache_read_tokens": 30, "cache_write_5m_tokens": 40,
                                 "cache_write_1h_tokens": 50})
        self.assert_metadata_only(usage)

    def test_v3_codex_usage_is_normalized_without_content(self):
        path = self.write_jsonl([
            {"type": "session_meta", "payload": {"id": "codex-1", "model": "codex-model"}},
            {"type": "response_item", "payload": {"content": PRIVATE_PROMPT + PRIVATE_RESPONSE}},
            {"type": "event_msg", "payload": {"type": "token_count", "info": {"last_token_usage": {
                "input_tokens": 110, "cached_input_tokens": 70, "output_tokens": 25}}}},
        ])
        usage = transcript_usage(path, "codex")
        self.assertEqual(usage, {"model": "codex-model", "input_tokens": 40, "output_tokens": 25,
                                 "cache_read_tokens": 70, "cache_write_5m_tokens": 0,
                                 "cache_write_1h_tokens": 0})
        self.assert_metadata_only(usage)

    def test_v3_malformed_and_missing_transcripts_are_empty_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bad.jsonl"
            path.write_text("{not-json}\n", encoding="utf-8")
            self.assertEqual(transcript_usage(path, "claude"), {})
            self.assertEqual(transcript_usage(Path(directory) / "missing.jsonl", "codex"), {})


if __name__ == "__main__":
    unittest.main()

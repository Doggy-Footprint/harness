import json
import tempfile
import unittest
from pathlib import Path

from analytics.importer import transcript_usage


class TranscriptUsageTests(unittest.TestCase):
    """Contract v3: U3; A2/A7/A10; V4/V9."""

    def write_jsonl(self, records):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        path = Path(temporary.name) / "transcript.jsonl"
        path.write_text("".join(json.dumps(record) + "\n" for record in records), encoding="utf-8")
        return path

    def assert_metadata_only(self, usage):
        serialized = json.dumps(usage)
        self.assertNotIn("PRIVATE PROMPT", serialized)
        self.assertNotIn("PRIVATE RESPONSE", serialized)

    def test_v4_claude_usage_is_normalized_without_content(self):
        path = self.write_jsonl(
            [
                {"sessionId": "session-1", "type": "user", "message": {"content": "PRIVATE PROMPT"}},
                {
                    "sessionId": "session-1",
                    "type": "assistant",
                    "message": {
                        "model": "claude-model",
                        "content": "PRIVATE RESPONSE",
                        "usage": {
                            "input_tokens": 10,
                            "output_tokens": 20,
                            "cache_read_input_tokens": 30,
                            "cache_creation": {"ephemeral_5m_input_tokens": 40, "ephemeral_1h_input_tokens": 50},
                        },
                    },
                },
            ]
        )
        usage = transcript_usage(path, "claude")
        self.assertEqual(
            usage,
            {
                "model": "claude-model",
                "input_tokens": 10,
                "output_tokens": 20,
                "cache_read_tokens": 30,
                "cache_write_5m_tokens": 40,
                "cache_write_1h_tokens": 50,
            },
        )
        self.assert_metadata_only(usage)

    def test_v4_codex_usage_is_normalized_without_content(self):
        path = self.write_jsonl(
            [
                {"type": "session_meta", "payload": {"id": "session-2", "model": "codex-model"}},
                {"type": "response_item", "payload": {"content": "PRIVATE PROMPT PRIVATE RESPONSE"}},
                {
                    "type": "event_msg",
                    "payload": {
                        "type": "token_count",
                        "info": {
                            "last_token_usage": {
                                "input_tokens": 110,
                                "cached_input_tokens": 70,
                                "output_tokens": 25,
                            }
                        },
                    },
                },
            ]
        )
        usage = transcript_usage(path, "codex")
        self.assertEqual(usage["model"], "codex-model")
        self.assertEqual(usage["input_tokens"], 40)
        self.assertEqual(usage["cache_read_tokens"], 70)
        self.assertEqual(usage["output_tokens"], 25)
        self.assertEqual(usage["cache_write_5m_tokens"], 0)
        self.assertEqual(usage["cache_write_1h_tokens"], 0)
        self.assert_metadata_only(usage)

    def test_v4_malformed_transcript_returns_no_usage(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bad.jsonl"
            path.write_text("{not-json}\n", encoding="utf-8")
            self.assertEqual(transcript_usage(path, "claude"), {})
            self.assertEqual(transcript_usage(Path(directory) / "missing.jsonl", "codex"), {})


if __name__ == "__main__":
    unittest.main()

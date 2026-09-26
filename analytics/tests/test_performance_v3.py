import json
import tempfile
import time
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from analytics.app import create_app


class SummaryPerformanceV3Tests(unittest.TestCase):
    """Independent oracle for spec v3 VO6 (QR2): with 2000 unchanged synthetic
    transcript files already indexed, the second /api/summary call must
    complete in <= 2 seconds (no full re-parse of unchanged files)."""

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
        self.claude_root = self.root / "claude"
        self.codex_root = self.root / "codex"
        self.claude_root.mkdir()
        self.codex_root.mkdir()
        for index in range(2000):
            (self.claude_root / f"session-{index}.jsonl").write_text(
                json.dumps({"type": "assistant", "sessionId": f"session-{index}",
                            "message": {"model": "known-model", "usage": {"input_tokens": 10, "output_tokens": 5}}}) + "\n",
                encoding="utf-8")
        self.client = TestClient(create_app(self.root / "analytics.sqlite3", self.telemetry_dir, self.prices,
                                             {"claude": self.claude_root, "codex": self.codex_root}, frontend_dir=None))

    def test_qr2_second_summary_call_completes_within_two_seconds(self):
        first = self.client.get("/api/summary")
        self.assertEqual(first.status_code, 200)
        started = time.monotonic()
        second = self.client.get("/api/summary")
        elapsed = time.monotonic() - started
        self.assertEqual(second.status_code, 200)
        self.assertLessEqual(elapsed, 2.0)


if __name__ == "__main__":
    unittest.main()

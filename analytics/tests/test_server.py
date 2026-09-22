"""Production-command oracle for spec v1 V5/V6 and Q2/Q6."""

import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from urllib.request import urlopen


ROOT = Path(__file__).resolve().parents[2]


class ProductionServerTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.telemetry = self.root / "telemetry"; self.telemetry.mkdir()
        self.claude = self.root / "claude"; self.claude.mkdir()
        self.codex = self.root / "codex"; self.codex.mkdir()
        self.prices = self.root / "prices.yaml"
        self.prices.write_text("models:\n  process-claude:\n    input: 7\n    output: 1\n    cache_read: 1\n    cache_write_5m: 1\n    cache_write_1h: 1\n  process-codex:\n    input: 11\n    output: 1\n    cache_read: 1\n    cache_write_5m: 1\n    cache_write_1h: 1\n", encoding="utf-8")
        self.frontend = self.root / "dist"; self.frontend.mkdir()
        (self.frontend / "index.html").write_text("<main>process dashboard</main>", encoding="utf-8")
        self.db = self.root / "analytics.sqlite3"
        records = []
        for run_id, client, session_id in (("process-claude", "claude", "process-claude"), ("process-codex", "codex", "process-codex")):
            base = {"v": 1, "ts": "2026-09-22T00:00:00+00:00", "repo": "/repo", "client": client, "session_id": session_id, "event": None, "workflow_run_id": run_id, "spec": "analytics", "spec_version": 1}
            records.extend([{**base, "event": "workflow_start"}, {**base, "event": "workflow_phase", "phase": "implement_test"}, {**base, "event": "workflow_phase", "phase": "verify"}, {**base, "event": "verifier_result", "round": 1, "result": "pass", "findings": 0, "seeds_run": 0, "seeds_detected": 0}, {**base, "event": "workflow_end", "status": "complete"}])
        (self.telemetry / "process.jsonl").write_text("".join(json.dumps(record) + "\n" for record in records), encoding="utf-8")
        (self.claude / "process-claude.jsonl").write_text(json.dumps({"sessionId": "process-claude", "type": "assistant", "message": {"model": "process-claude", "usage": {"input_tokens": 1_000_000}}}) + "\n", encoding="utf-8")
        (self.codex / "process-codex.jsonl").write_text(json.dumps({"type": "session_meta", "payload": {"id": "process-codex", "model": "process-codex"}}) + "\n" + json.dumps({"type": "event_msg", "payload": {"type": "token_count", "info": {"last_token_usage": {"input_tokens": 1_000_000, "cached_input_tokens": 0, "output_tokens": 0}}}}) + "\n", encoding="utf-8")

    def port(self):
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            return probe.getsockname()[1]

    def environment(self, **overrides):
        env = os.environ.copy()
        env.update({"ANALYTICS_HOST": "127.0.0.1", "ANALYTICS_PORT": str(self.port()),
                    "ANALYTICS_DATABASE_PATH": str(self.db), "ANALYTICS_TELEMETRY_DIR": str(self.telemetry),
                    "ANALYTICS_PRICE_PATH": str(self.prices), "ANALYTICS_CLAUDE_TRANSCRIPT_DIR": str(self.claude),
                    "ANALYTICS_CODEX_TRANSCRIPT_DIR": str(self.codex), "ANALYTICS_FRONTEND_DIR": str(self.frontend)})
        env.update(overrides)
        return env

    def start(self, env):
        process = subprocess.Popen([sys.executable, "-m", "analytics.app"], cwd=ROOT, env=env,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.addCleanup(self.stop, process)
        return process

    def stop(self, process):
        if process.poll() is None:
            process.terminate()
            try: process.communicate(timeout=5)
            except subprocess.TimeoutExpired: process.kill(); process.communicate(timeout=5)

    def wait_for_json(self, url, process):
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if process.poll() is not None:
                self.fail("server exited before ready: " + process.stderr.read())
            try:
                with urlopen(url, timeout=0.5) as response:
                    return response.status, response.headers.get_content_type(), json.loads(response.read())
            except OSError: time.sleep(0.05)
        self.fail("server did not become ready")

    def test_v5_v6_all_environment_overrides_control_production_server(self):
        env = self.environment(); port = env["ANALYTICS_PORT"]
        process = self.start(env)
        status, content_type, payload = self.wait_for_json(f"http://127.0.0.1:{port}/api/health", process)
        self.assertEqual((status, content_type, payload), (200, "application/json", {"status": "ok"}))
        _, _, summary = self.wait_for_json(f"http://127.0.0.1:{port}/api/summary", process)
        self.assertEqual((summary["runs"], summary["linked_cost_usd"]), (2, 18.0))
        self.assertTrue(self.db.is_file())
        with urlopen(f"http://127.0.0.1:{port}/runs/client-route", timeout=2) as response:
            self.assertIn("process dashboard", response.read().decode())

    def test_v6_missing_optional_roots_are_empty_input(self):
        env = self.environment(ANALYTICS_TELEMETRY_DIR=str(self.root / "none"),
                               ANALYTICS_CLAUDE_TRANSCRIPT_DIR=str(self.root / "no-claude"),
                               ANALYTICS_CODEX_TRANSCRIPT_DIR=str(self.root / "no-codex"))
        process = self.start(env)
        _, _, summary = self.wait_for_json(f"http://127.0.0.1:{env['ANALYTICS_PORT']}/api/summary", process)
        self.assertEqual(summary["runs"], 0)

    def test_v6_required_startup_failures_are_nonzero_and_diagnostic(self):
        file_parent = self.root / "database-parent-file"
        file_parent.write_text("not a directory", encoding="utf-8")
        cases = {
            "invalid_port": {"ANALYTICS_PORT": "not-a-port"},
            "bad_price": {"ANALYTICS_PRICE_PATH": str(self.root / "bad.yaml")},
            "missing_build": {"ANALYTICS_FRONTEND_DIR": str(self.root / "missing-dist")},
            "uncreatable_db": {"ANALYTICS_DATABASE_PATH": str(file_parent / "db.sqlite3")},
        }
        (self.root / "bad.yaml").write_text("models: [broken", encoding="utf-8")
        for name, overrides in cases.items():
            with self.subTest(name=name):
                process = subprocess.run([sys.executable, "-m", "analytics.app"], cwd=ROOT,
                    env=self.environment(**overrides), capture_output=True, text=True, timeout=10)
                self.assertNotEqual(process.returncode, 0)
                self.assertTrue(process.stderr.strip())

    def test_v6_a3_package_relative_and_home_defaults_serve_with_only_port_override(self):
        """F8/A3: with no ANALYTICS_* overrides except ANALYTICS_PORT, the process must
        use home-based telemetry/transcript defaults and package-relative price/build defaults."""
        home_dir = tempfile.TemporaryDirectory()
        self.addCleanup(home_dir.cleanup)
        home = Path(home_dir.name)
        telemetry = home / ".harness" / "telemetry"
        telemetry.mkdir(parents=True)
        claude_projects = home / ".claude" / "projects" / "project-a"
        claude_projects.mkdir(parents=True)
        codex_sessions = home / ".codex" / "sessions" / "2026" / "09"
        codex_sessions.mkdir(parents=True)
        db_path = home / ".harness" / "analytics.sqlite3"

        base = {"v": 1, "ts": "2026-09-22T00:00:00+00:00", "repo": "/repo", "spec": "analytics", "spec_version": 1}
        claude_run = {**base, "client": "claude", "session_id": "home-claude-session", "workflow_run_id": "home-claude-run"}
        codex_run = {**base, "client": "codex", "session_id": "home-codex-session", "workflow_run_id": "home-codex-run"}
        records = []
        for run in (claude_run, codex_run):
            records.extend([
                {**run, "event": "workflow_start"},
                {**run, "event": "workflow_phase", "phase": "implement_test"},
                {**run, "event": "workflow_phase", "phase": "verify"},
                {**run, "event": "verifier_result", "round": 1, "result": "pass", "findings": 0, "seeds_run": 0, "seeds_detected": 0},
                {**run, "event": "workflow_end", "status": "complete"},
            ])
        (telemetry / "home.jsonl").write_text("".join(json.dumps(record) + "\n" for record in records), encoding="utf-8")
        (claude_projects / "home-claude-session.jsonl").write_text(
            json.dumps({"sessionId": "home-claude-session", "type": "assistant",
                        "message": {"model": "home-default-unknown-model", "usage": {"input_tokens": 5}}}) + "\n",
            encoding="utf-8")
        (codex_sessions / "home-codex-session.jsonl").write_text(
            json.dumps({"type": "session_meta", "payload": {"id": "home-codex-session", "model": "home-default-unknown-model"}}) + "\n"
            + json.dumps({"type": "event_msg", "payload": {"type": "token_count",
                          "info": {"last_token_usage": {"input_tokens": 5, "cached_input_tokens": 0, "output_tokens": 0}}}}) + "\n",
            encoding="utf-8")

        env = os.environ.copy()
        for name in ("ANALYTICS_HOST", "ANALYTICS_DATABASE_PATH", "ANALYTICS_TELEMETRY_DIR",
                     "ANALYTICS_PRICE_PATH", "ANALYTICS_CLAUDE_TRANSCRIPT_DIR",
                     "ANALYTICS_CODEX_TRANSCRIPT_DIR", "ANALYTICS_FRONTEND_DIR"):
            env.pop(name, None)
        env["HOME"] = str(home)
        env["ANALYTICS_PORT"] = str(self.port())
        self.assertFalse(db_path.exists())

        process = self.start(env)
        _, _, summary = self.wait_for_json(f"http://127.0.0.1:{env['ANALYTICS_PORT']}/api/summary", process)
        self.assertEqual(summary["runs"], 2)
        self.assertEqual(summary["completed_runs"], 2)
        self.assertEqual(summary["compliant_runs"], 2)
        self.assertIsNone(summary["linked_cost_usd"])
        claude_detail = self.wait_for_json(f"http://127.0.0.1:{env['ANALYTICS_PORT']}/api/runs/home-claude-run", process)[2]
        codex_detail = self.wait_for_json(f"http://127.0.0.1:{env['ANALYTICS_PORT']}/api/runs/home-codex-run", process)[2]
        self.assertEqual(len(claude_detail["transcript_metadata"]), 1)
        self.assertEqual(claude_detail["transcript_metadata"][0]["client"], "claude")
        self.assertEqual(len(codex_detail["transcript_metadata"]), 1)
        self.assertEqual(codex_detail["transcript_metadata"][0]["client"], "codex")
        self.assertTrue(db_path.is_file())

    def test_v6_dependency_manifests_are_pinned_and_lockfile_present(self):
        requirements = ROOT / "analytics" / "requirements.txt"
        package = ROOT / "analytics" / "frontend" / "package.json"
        lockfile = ROOT / "analytics" / "frontend" / "package-lock.json"
        self.assertTrue(requirements.is_file())
        self.assertTrue(package.is_file())
        self.assertTrue(lockfile.is_file())
        dependencies = [line.strip() for line in requirements.read_text(encoding="utf-8").splitlines()
                        if line.strip() and not line.lstrip().startswith("#")]
        self.assertTrue(dependencies)
        self.assertTrue(all("==" in dependency for dependency in dependencies))
        package_data = json.loads(package.read_text(encoding="utf-8"))
        lock_data = json.loads(lockfile.read_text(encoding="utf-8"))
        self.assertIn("lockfileVersion", lock_data)
        root_package = lock_data["packages"][""]
        self.assertEqual(root_package.get("dependencies", {}), package_data.get("dependencies", {}))
        self.assertEqual(root_package.get("devDependencies", {}), package_data.get("devDependencies", {}))


if __name__ == "__main__":
    unittest.main()

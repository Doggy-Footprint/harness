import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi.testclient import TestClient

from analytics.app import create_app

RULES = ("test_reads_implementation", "test_runs_tests", "impl_reads_tests",
         "impl_runs_test_command", "dispatch_run_instruction")
CANDIDATE_KEYS = {"ts", "workflow_run_id", "session_id", "agent_type", "rule", "tool_name",
                  "match", "match_kind", "excerpt"}
BASE_TIME = datetime(2026, 9, 22, tzinfo=timezone.utc)
EXTRA_SECRET = "UNAPPROVED_ISOLATION_FIELD_VALUE"


def stamp(seconds):
    return (BASE_TIME + timedelta(seconds=seconds)).isoformat()


class HarnessHackingApiTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.telemetry_dir = self.root / "telemetry"
        self.telemetry_dir.mkdir()
        self.prices = self.root / "prices.yaml"
        self.prices.write_text(
            "models:\n  m:\n    input: 1\n    output: 1\n    cache_read: 1\n    cache_write_5m: 1\n    cache_write_1h: 1\n",
            encoding="utf-8")
        self.transcripts = {"claude": self.root / "claude", "codex": self.root / "codex"}
        for directory in self.transcripts.values():
            directory.mkdir()
        self.client = TestClient(create_app(self.root / "analytics.sqlite3", self.telemetry_dir,
                                            self.prices, self.transcripts, frontend_dir=None))

    def base(self, name, run_id, seconds=0, session_id="s1", agent_type=None, **fields):
        return {"v": 1, "ts": stamp(seconds), "repo": "/repo", "client": "claude",
                "session_id": session_id, "agent_id": None, "agent_type": agent_type,
                "tool_use_id": None, "event": name, "workflow_run_id": run_id,
                "spec": "analytics" if run_id else None, "spec_version": 1 if run_id else None, **fields}

    def workflow(self, run_id, session_id="s1"):
        return [self.base("workflow_start", run_id, session_id=session_id),
                self.base("workflow_phase", run_id, session_id=session_id, phase="implement_test"),
                self.base("workflow_phase", run_id, session_id=session_id, phase="verify"),
                self.base("verifier_result", run_id, session_id=session_id, round=1, result="pass",
                          findings=0, seeds_run=0, seeds_detected=0),
                self.base("workflow_end", run_id, session_id=session_id, status="complete")]

    def candidate(self, run_id, seconds=0, rule="test_reads_implementation", agent_type="test-implementer",
                  tool_name="Read", match="pkg/a.go", match_kind="path", excerpt="pkg/a.go",
                  session_id="s1", **extra):
        return self.base("isolation_candidate", run_id, seconds, session_id, agent_type, rule=rule,
                         tool_name=tool_name, match=match, match_kind=match_kind, excerpt=excerpt, **extra)

    def write(self, records, filename="repo.jsonl"):
        with (self.telemetry_dir / filename).open("a", encoding="utf-8") as stream:
            for record in records:
                stream.write(json.dumps(record) + "\n")

    def summary(self):
        return self.client.get("/api/summary").json()

    def detail(self, run_id):
        response = self.client.get(f"/api/runs/{run_id}")
        self.assertEqual(response.status_code, 200)
        return response.json()

    def test_a1_importer_keeps_the_five_isolation_fields(self):
        self.write(self.workflow("run-1") + [self.candidate(
            "run-1", 10, rule="test_runs_tests", tool_name="Bash", match="go test -race ./pkg/",
            match_kind="runner", excerpt="cd x && go test -race ./pkg/")])
        stored = [e for e in self.detail("run-1")["events"] if e["event"] == "isolation_candidate"]
        self.assertEqual(len(stored), 1)
        self.assertEqual(
            {k: stored[0][k] for k in ("rule", "tool_name", "match", "match_kind", "excerpt")},
            {"rule": "test_runs_tests", "tool_name": "Bash", "match": "go test -race ./pkg/",
             "match_kind": "runner", "excerpt": "cd x && go test -race ./pkg/"})

    def test_a2_non_whitelisted_field_is_still_dropped(self):
        self.write(self.workflow("run-1") + [self.candidate("run-1", 10, unapproved=EXTRA_SECRET)])
        stored = [e for e in self.detail("run-1")["events"] if e["event"] == "isolation_candidate"]
        self.assertEqual(len(stored), 1)
        self.assertNotIn("unapproved", stored[0])
        self.assertNotIn(EXTRA_SECRET, self.client.get("/api/runs/run-1").text)
        self.assertNotIn(EXTRA_SECRET, self.client.get("/api/summary").text)

    def test_a3_by_rule_has_all_five_ids_with_zeros(self):
        self.write(self.workflow("run-1") + [
            self.candidate("run-1", 10, rule="test_runs_tests"),
            self.candidate("run-1", 11, rule="test_runs_tests"),
            self.candidate("run-1", 12, rule="impl_reads_tests", agent_type="implementer")])
        for section in (self.summary()["harness_hacking"], self.detail("run-1")["harness_hacking"]):
            self.assertEqual(section["by_rule"], {
                "test_reads_implementation": 0, "test_runs_tests": 2, "impl_reads_tests": 1,
                "impl_runs_test_command": 0, "dispatch_run_instruction": 0})
            self.assertEqual(section["total"], 3)

    def test_a3_empty_state_has_zero_total_all_rules_and_empty_lists(self):
        self.write(self.workflow("run-1"))
        for section in (self.summary()["harness_hacking"], self.detail("run-1")["harness_hacking"]):
            self.assertEqual(section["total"], 0)
            self.assertEqual(section["by_rule"], {rule: 0 for rule in RULES})
            self.assertEqual(section["by_agent_type"], {})
            self.assertEqual(section["candidates"], [])

    def test_a4_by_agent_type_counts_null_as_main(self):
        self.write(self.workflow("run-1") + [
            self.candidate("run-1", 10, rule="dispatch_run_instruction", agent_type=None),
            self.candidate("run-1", 11, rule="dispatch_run_instruction", agent_type=None),
            self.candidate("run-1", 12, agent_type="test-implementer"),
            self.candidate("run-1", 13, rule="impl_reads_tests", agent_type="implementer")])
        for section in (self.summary()["harness_hacking"], self.detail("run-1")["harness_hacking"]):
            self.assertEqual(section["by_agent_type"],
                             {"main": 2, "test-implementer": 1, "implementer": 1})
        main_rows = [c for c in self.detail("run-1")["harness_hacking"]["candidates"]
                     if c["rule"] == "dispatch_run_instruction"]
        self.assertEqual(len(main_rows), 2)
        self.assertTrue(all(c["agent_type"] is None for c in main_rows))

    def test_a5_null_run_candidate_counted_in_summary_and_absent_from_run_detail(self):
        self.write(self.workflow("run-1") + [
            self.candidate("run-1", 10, excerpt="in-run"),
            self.candidate(None, 11, excerpt="no-run", rule="test_runs_tests", tool_name="Bash",
                           match_kind="runner")])
        summary = self.summary()["harness_hacking"]
        self.assertEqual(summary["total"], 2)
        self.assertEqual(summary["by_rule"]["test_runs_tests"], 1)
        self.assertEqual({c["excerpt"] for c in summary["candidates"]}, {"in-run", "no-run"})
        null_rows = [c for c in summary["candidates"] if c["excerpt"] == "no-run"]
        self.assertIsNone(null_rows[0]["workflow_run_id"])
        detail = self.detail("run-1")["harness_hacking"]
        self.assertEqual(detail["total"], 1)
        self.assertEqual([c["excerpt"] for c in detail["candidates"]], ["in-run"])
        self.assertEqual(detail["by_rule"]["test_runs_tests"], 0)

    def test_a6_run_detail_only_contains_that_runs_candidates(self):
        self.write(self.workflow("run-1") + self.workflow("run-2", "s2") + [
            self.candidate("run-1", 10, excerpt="one"),
            self.candidate("run-2", 11, excerpt="two-a", session_id="s2"),
            self.candidate("run-2", 12, excerpt="two-b", session_id="s2", rule="test_runs_tests")])
        one = self.detail("run-1")["harness_hacking"]
        two = self.detail("run-2")["harness_hacking"]
        self.assertEqual((one["total"], [c["excerpt"] for c in one["candidates"]]), (1, ["one"]))
        self.assertEqual((two["total"], [c["excerpt"] for c in two["candidates"]]), (2, ["two-b", "two-a"]))
        self.assertTrue(all(c["workflow_run_id"] == "run-2" for c in two["candidates"]))
        self.assertEqual(self.summary()["harness_hacking"]["total"], 3)

    def test_a6_candidate_rows_have_exactly_the_specified_keys_and_values(self):
        self.write(self.workflow("run-1") + [self.candidate(
            "run-1", 10, session_id="sess-9", rule="impl_runs_test_command", agent_type="implementer",
            tool_name="Bash", match="make test", match_kind="test_command", excerpt="make test -k foo")])
        row = self.detail("run-1")["harness_hacking"]["candidates"][0]
        self.assertEqual(set(row), CANDIDATE_KEYS)
        self.assertEqual(row, {
            "ts": stamp(10), "workflow_run_id": "run-1", "session_id": "sess-9",
            "agent_type": "implementer", "rule": "impl_runs_test_command", "tool_name": "Bash",
            "match": "make test", "match_kind": "test_command", "excerpt": "make test -k foo"})

    def test_a7_workflow_runs_carry_isolation_candidate_counts(self):
        self.write(self.workflow("run-1") + self.workflow("run-2", "s2") + self.workflow("run-3", "s3") + [
            self.candidate("run-1", 10), self.candidate("run-1", 11),
            self.candidate("run-2", 12, session_id="s2"),
            self.candidate(None, 13)])
        runs = {item["run_id"]: item for item in self.summary()["workflow"]["runs"]}
        self.assertEqual({rid: item["isolation_candidates"] for rid, item in runs.items()},
                         {"run-1": 2, "run-2": 1, "run-3": 0})
        for item in runs.values():
            self.assertIs(type(item["isolation_candidates"]), int)

    def test_a8_cap_at_200_total_counts_all_and_newest_first(self):
        # C9: 201 candidates imported; written in a scrambled order so only a
        # ts sort can produce the expected sequence.
        order = [(i * 77) % 201 for i in range(201)]
        self.assertEqual(sorted(order), list(range(201)))
        self.write(self.workflow("run-1") + [
            self.candidate("run-1", 100 + n, excerpt=f"n{n}") for n in order])
        for section in (self.summary()["harness_hacking"], self.detail("run-1")["harness_hacking"]):
            self.assertEqual(section["total"], 201)
            self.assertEqual(section["by_rule"]["test_reads_implementation"], 201)
            self.assertEqual(section["by_agent_type"], {"test-implementer": 201})
            self.assertEqual(len(section["candidates"]), 200)
            self.assertEqual([c["excerpt"] for c in section["candidates"]],
                             [f"n{n}" for n in range(200, 0, -1)])
        runs = {item["run_id"]: item for item in self.summary()["workflow"]["runs"]}
        self.assertEqual(runs["run-1"]["isolation_candidates"], 201)

    def test_a8_exactly_200_candidates_are_all_returned(self):
        self.write(self.workflow("run-1") + [
            self.candidate("run-1", 100 + n, excerpt=f"n{n}") for n in range(200)])
        section = self.summary()["harness_hacking"]
        self.assertEqual(section["total"], 200)
        self.assertEqual([c["excerpt"] for c in section["candidates"]],
                         [f"n{n}" for n in range(199, -1, -1)])

    def test_a8_summary_cap_includes_null_run_candidates(self):
        self.write([self.candidate(None, 100 + n, excerpt=f"n{n}") for n in range(201)])
        section = self.summary()["harness_hacking"]
        self.assertEqual((section["total"], len(section["candidates"])), (201, 200))
        self.assertEqual(section["candidates"][0]["excerpt"], "n200")


if __name__ == "__main__":
    unittest.main()

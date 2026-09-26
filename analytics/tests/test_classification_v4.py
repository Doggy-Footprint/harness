import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from analytics.app import create_app

REPO_ROOT = Path(__file__).resolve().parents[2]
BASE_COMMIT = "f6aba189f5b908764aa1f15b09d41b4deda46226"

BASE_SUMMARY_SCRIPT = """
import json
import sys
from pathlib import Path

from analytics.app import create_app
from fastapi.testclient import TestClient

db_path, telemetry_dir, prices_path, claude_dir, codex_dir = (Path(p) for p in sys.argv[1:6])
client = TestClient(create_app(db_path, telemetry_dir, prices_path,
                                {"claude": claude_dir, "codex": codex_dir}, frontend_dir=None))
print(json.dumps(client.get("/api/summary").json()))
"""


class ClassificationV4TestCase(unittest.TestCase):
    """Shared fixture plumbing for spec v4 VO2-VO4 (F2-F6, Q1; C5-C11):
    telemetry jsonl + claude/codex transcript directories, in the style of
    analytics/tests/test_api_v3.py and test_transcripts.py."""

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

    def make_client(self):
        return TestClient(create_app(
            self.root / "analytics.sqlite3", self.telemetry_dir, self.prices,
            {"claude": self.claude_root, "codex": self.codex_root}, frontend_dir=None))

    def event(self, name, run_id, session_id, client="claude", **fields):
        return {"v": 1, "ts": "2026-09-22T00:00:00+00:00", "client": client, "session_id": session_id,
                "workflow_run_id": run_id, "spec": "analytics", "spec_version": 1, "event": name, **fields}

    def workflow_events(self, run_id, session_id, client="claude", status="complete", result="pass"):
        return [
            self.event("workflow_start", run_id, session_id, client),
            self.event("workflow_phase", run_id, session_id, client, phase="implement_test"),
            self.event("workflow_phase", run_id, session_id, client, phase="verify"),
            self.event("verifier_result", run_id, session_id, client, round=1, result=result,
                       findings=1 if result == "retry" else 0, seeds_run=0, seeds_detected=0),
            self.event("workflow_end", run_id, session_id, client, status=status),
        ]

    def duplicate_start_events(self, run_id, session_id):
        """F1/F3-independent noncompliant shape: a duplicate workflow_start
        violates 'one start first', giving compliant=False on an ended run."""
        events = self.workflow_events(run_id, session_id)
        events.insert(1, self.event("workflow_start", run_id, session_id))
        return events

    def unterminated_events(self, run_id, session_id, client="claude"):
        return [
            self.event("workflow_start", run_id, session_id, client),
            self.event("workflow_phase", run_id, session_id, client, phase="implement_test"),
            self.event("workflow_phase", run_id, session_id, client, phase="verify"),
        ]

    def write_events(self, records, filename="repo.jsonl"):
        (self.telemetry_dir / filename).write_text(
            "".join(json.dumps(record) + "\n" for record in records), encoding="utf-8")

    def write_claude_transcript(self, session_id, *, subagents=(), input_tokens=1, directory=None):
        content = [{"type": "assistant", "sessionId": session_id, "message": {
            "model": "known-model", "content": [
                {"type": "tool_use", "name": "Agent", "input": {"subagent_type": t}} for t in subagents
            ], "usage": {"input_tokens": input_tokens, "output_tokens": 0}}}]
        target = (directory or self.claude_root) / f"{session_id}.jsonl"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("".join(json.dumps(line) + "\n" for line in content), encoding="utf-8")
        return target

    def write_claude_subagent_file(self, parent_session_id, name, directory=None):
        subagents_dir = (directory or self.claude_root) / parent_session_id / "subagents"
        subagents_dir.mkdir(parents=True, exist_ok=True)
        (subagents_dir / f"{name}.jsonl").write_text(
            json.dumps({"type": "assistant", "sessionId": parent_session_id, "message": {
                "model": "known-model", "usage": {"input_tokens": 1, "output_tokens": 0}}}) + "\n",
            encoding="utf-8")

    def write_codex_transcript(self, session_id, *, source=None):
        lines = [{"type": "session_meta", "payload": {
            "id": session_id, "model": "known-model", **({"source": source} if source is not None else {})}}]
        lines.append({"type": "event_msg", "payload": {"type": "token_count", "info": {
            "last_token_usage": {"input_tokens": 1, "cached_input_tokens": 0, "output_tokens": 0}}}})
        (self.codex_root / f"{session_id}.jsonl").write_text(
            "".join(json.dumps(line) + "\n" for line in lines), encoding="utf-8")


class RunClassificationVO2Tests(ClassificationV4TestCase):
    """Independent oracle for spec v4 VO2 (F2, C5): equivalence partitioning
    over run status {complete, limit, handoff, aborted, none} and, for ended
    runs, compliant in {true, false}."""

    def test_c5_four_ended_statuses_classify_by_compliance_one_in_progress_is_excluded(self):
        self.write_events(
            self.workflow_events("run-complete", "claude-complete", status="complete", result="pass")
            + self.workflow_events("run-limit", "claude-limit", status="limit", result="limit")
            + self.workflow_events("run-handoff", "claude-handoff", status="handoff", result="pass")
            + self.workflow_events("run-aborted", "claude-aborted", status="aborted", result="pass")
            + self.unterminated_events("run-open", "claude-open"))

        summary = self.make_client().get("/api/summary").json()

        self.assertEqual(summary["classification"]["runs"], {"compliant": 4, "noncompliant": 0, "excluded": 1})
        self.assertEqual(summary["runs"], 5)

    def test_ended_noncompliant_run_is_counted_as_noncompliant_not_excluded(self):
        """VO2 second equivalence class: compliant=false for an ended run."""
        self.write_events(
            self.workflow_events("run-good", "claude-good")
            + self.duplicate_start_events("run-bad", "claude-bad"))

        summary = self.make_client().get("/api/summary").json()

        self.assertEqual(summary["classification"]["runs"], {"compliant": 1, "noncompliant": 1, "excluded": 0})


class SessionClassificationVO3Tests(ClassificationV4TestCase):
    """Independent oracle for spec v4 VO3 (F3-F5, C6-C10): decision table over
    session-run linkage cardinality/class and harness sub-agent evidence."""

    def test_c6_session_linked_to_two_distinct_runs_is_noncompliant(self):
        self.write_claude_transcript("claude-c6")
        self.write_events(
            self.workflow_events("run-c6-compliant", "claude-c6")
            + self.unterminated_events("run-c6-open", "claude-c6"))

        summary = self.make_client().get("/api/summary").json()

        self.assertEqual(summary["classification"]["sessions"],
                          {"compliant": 0, "noncompliant": 1, "partial": 0, "unrelated": 0, "excluded": 0})
        self.assertEqual(summary["classification"]["runs"], {"compliant": 1, "noncompliant": 0, "excluded": 1})

    def test_c7_unlinked_claude_session_with_test_verifier_subagent_is_partial(self):
        self.write_claude_transcript("claude-c7", subagents=("test-verifier",))

        summary = self.make_client().get("/api/summary").json()

        self.assertEqual(summary["classification"]["sessions"],
                          {"compliant": 0, "noncompliant": 0, "partial": 1, "unrelated": 0, "excluded": 0})

    def test_c8_unlinked_codex_thread_spawn_implementer_child_makes_parent_and_child_partial(self):
        self.write_codex_transcript("codex-c8-parent")
        self.write_codex_transcript("codex-c8-child", source={
            "subagent": {"thread_spawn": {"parent_thread_id": "codex-c8-parent", "agent_role": "implementer"}}})

        summary = self.make_client().get("/api/summary").json()

        self.assertEqual(summary["classification"]["sessions"],
                          {"compliant": 0, "noncompliant": 0, "partial": 2, "unrelated": 0, "excluded": 0})

    def test_c9_unlinked_session_with_only_explore_subagents_is_unrelated(self):
        self.write_claude_transcript("claude-c9", subagents=("Explore", "Explore"))

        summary = self.make_client().get("/api/summary").json()

        self.assertEqual(summary["classification"]["sessions"],
                          {"compliant": 0, "noncompliant": 0, "partial": 0, "unrelated": 1, "excluded": 0})

    def test_c10_linked_session_with_two_merged_claude_subagent_transcripts_yields_three_compliant_sessions(self):
        project_dir = self.claude_root / "project-a"
        self.write_claude_transcript("claude-c10", directory=project_dir)
        self.write_claude_subagent_file("claude-c10", "agent-1", directory=project_dir)
        self.write_claude_subagent_file("claude-c10", "agent-2", directory=project_dir)
        self.write_events(self.workflow_events("run-c10", "claude-c10"))

        summary = self.make_client().get("/api/summary").json()

        self.assertEqual(summary["classification"]["sessions"],
                          {"compliant": 3, "noncompliant": 0, "partial": 0, "unrelated": 0, "excluded": 0})
        self.assertEqual(summary["classification"]["runs"], {"compliant": 1, "noncompliant": 0, "excluded": 0})

    def test_r1_session_linked_to_one_ended_noncompliant_run_is_noncompliant(self):
        """Correction batch 1, VO3 rule R1: F3 'linked to exactly one run
        takes that run's class' where the run's class is noncompliant."""
        self.write_claude_transcript("claude-noncompliant-linked")
        self.write_events(self.duplicate_start_events("run-noncompliant", "claude-noncompliant-linked"))

        summary = self.make_client().get("/api/summary").json()

        self.assertEqual(summary["classification"]["sessions"],
                          {"compliant": 0, "noncompliant": 1, "partial": 0, "unrelated": 0, "excluded": 0})
        self.assertEqual(summary["classification"]["runs"], {"compliant": 0, "noncompliant": 1, "excluded": 0})

    def test_r2_codex_child_with_non_harness_agent_type_inherits_present_compliant_parent(self):
        """Correction batch 1, VO3 rule R2: F5 'a Codex child session that is
        itself unlinked takes its parent session's class when the parent is
        present'. The child's own agent_role ("explorer") is deliberately not
        a harness sub-agent name, so F4 evidence cannot explain a partial/
        compliant result here -- only F5 inheritance can."""
        self.write_codex_transcript("codex-r2-parent")
        self.write_events(self.workflow_events("run-r2", "codex-r2-parent", client="codex"))
        self.write_codex_transcript("codex-r2-child", source={
            "subagent": {"thread_spawn": {"parent_thread_id": "codex-r2-parent", "agent_role": "explorer"}}})

        summary = self.make_client().get("/api/summary").json()

        self.assertEqual(summary["classification"]["sessions"],
                          {"compliant": 2, "noncompliant": 0, "partial": 0, "unrelated": 0, "excluded": 0})
        self.assertEqual(summary["classification"]["runs"], {"compliant": 1, "noncompliant": 0, "excluded": 0})

    def test_r3_codex_child_with_absent_parent_and_harness_agent_type_is_partial(self):
        """Correction batch 1, VO3 rule R3 (harness branch): the
        parent_thread_id points to a session with no matching transcript
        (Errors: 'not counted as a session'), so F5 falls back to F4 using
        the child's own agent_type; test-verifier is a harness sub-agent."""
        self.write_codex_transcript("codex-r3a-child", source={
            "subagent": {"thread_spawn": {"parent_thread_id": "codex-r3a-missing-parent",
                                           "agent_role": "test-verifier"}}})

        summary = self.make_client().get("/api/summary").json()

        self.assertEqual(summary["classification"]["sessions"],
                          {"compliant": 0, "noncompliant": 0, "partial": 1, "unrelated": 0, "excluded": 0})

    def test_r3_codex_child_with_absent_parent_and_non_harness_agent_type_is_unrelated(self):
        """Correction batch 1, VO3 rule R3 (non-harness branch): same absent-
        parent fallback to F4, but the child's own agent_type is not a
        harness sub-agent name, so it is unrelated."""
        self.write_codex_transcript("codex-r3b-child", source={
            "subagent": {"thread_spawn": {"parent_thread_id": "codex-r3b-missing-parent",
                                           "agent_role": "explorer"}}})

        summary = self.make_client().get("/api/summary").json()

        self.assertEqual(summary["classification"]["sessions"],
                          {"compliant": 0, "noncompliant": 0, "partial": 0, "unrelated": 1, "excluded": 0})


class SummaryBoundaryVO4Tests(ClassificationV4TestCase):
    """Independent oracle for spec v4 VO4/Q1 (F6, C11): boundary value
    analysis at the empty-dataset and one-excluded-run-with-session edges,
    checking that pre-existing summary fields keep their current values and
    that an excluded run/session still lands in every existing total."""

    def test_c11_empty_dataset_all_classification_counts_are_zero(self):
        summary = self.make_client().get("/api/summary").json()

        self.assertEqual(summary["classification"],
                          {"runs": {"compliant": 0, "noncompliant": 0, "excluded": 0},
                           "sessions": {"compliant": 0, "noncompliant": 0, "partial": 0,
                                        "unrelated": 0, "excluded": 0}})
        self.assertEqual((summary["runs"], summary["completed_runs"], summary["compliant_runs"],
                           summary["handoff_runs"]), (0, 0, 0, 0))
        self.assertEqual(summary["non_workflow"]["sessions"], 0)

    def test_c11_excluded_run_with_a_linked_session_still_counted_in_existing_totals(self):
        self.write_events(self.unterminated_events("run-excluded", "claude-excluded"))
        self.write_claude_transcript("claude-excluded", input_tokens=1_000_000)

        client = self.make_client()
        summary = client.get("/api/summary").json()

        self.assertEqual(summary["runs"], 1)
        self.assertEqual(summary["classification"]["runs"], {"compliant": 0, "noncompliant": 0, "excluded": 1})
        self.assertEqual(summary["classification"]["sessions"],
                          {"compliant": 0, "noncompliant": 0, "partial": 0, "unrelated": 0, "excluded": 1})

        detail = client.get("/api/runs/run-excluded").json()
        priced = next(e for e in detail["transcript_metadata"] if e["session_id"] == "claude-excluded")
        self.assertEqual(priced["linked_cost_usd"], 1.0)


class Q1CoexistenceMeasurementTests(ClassificationV4TestCase):
    """Independent oracle for spec v4 Q1 (Compatibility/co-existence):
    measures Q1 exactly as its quality-requirement row states -- 'count of
    pre-existing summary keys with changed value on a fixture without new
    behavior' -- rather than pinning only a subset of keys.

    Procedure: build one fixture using only pre-existing behavior (no F1
    amend placements are used at all, so F1's rule change cannot affect the
    verdict). Extract the base_commit analytics package with `git archive
    <commit> analytics | tar -x -C <tmp>` and run its /api/summary over the
    same fixture, in a subprocess with cwd=<tmp>, using the same Python
    interpreter that has the test's fastapi/etc. dependencies installed.
    Compute the current /api/summary in-process on the identical fixture.
    The measured Q1 count is: (number of pre-existing keys whose value
    differs between the two responses) which must be 0, plus a check that
    the base response has no 'classification' key at all (so the new key is
    additive, not a renamed pre-existing one)."""

    def build_pre_existing_behavior_fixture(self):
        """Several runs (complete/limit/handoff/in-progress, compliant and
        noncompliant via duplicate start), linked and unlinked Claude
        sessions with subagents, a merged subagent transcript, a Codex
        parent + thread_spawn child, and known/unknown models -- all via the
        same pre-existing helpers used by the other VO2-VO4 tests, none of
        which touch an amend phase."""
        self.write_events(
            self.workflow_events("run-q1-complete", "claude-q1-linked", status="complete", result="pass")
            + self.workflow_events("run-q1-limit", "claude-q1-limit", status="limit", result="limit")
            + self.workflow_events("run-q1-handoff", "claude-q1-handoff", status="handoff", result="pass")
            + self.unterminated_events("run-q1-open", "claude-q1-open")
            + self.duplicate_start_events("run-q1-dup", "claude-q1-dup")
            + self.workflow_events("run-q1-codex", "codex-q1-parent", client="codex"))

        project_dir = self.claude_root / "project-q1"
        self.write_claude_transcript("claude-q1-linked", subagents=("test-verifier",), directory=project_dir)
        self.write_claude_subagent_file("claude-q1-linked", "agent-1", directory=project_dir)
        self.write_claude_transcript("claude-q1-unlinked", subagents=("Explore",))
        (self.claude_root / "claude-q1-unknown-model.jsonl").write_text(
            json.dumps({"type": "assistant", "sessionId": "claude-q1-unknown-model", "message": {
                "model": "unlisted-model", "usage": {"input_tokens": 1, "output_tokens": 0}}}) + "\n",
            encoding="utf-8")

        self.write_codex_transcript("codex-q1-parent")
        self.write_codex_transcript("codex-q1-child", source={
            "subagent": {"thread_spawn": {"parent_thread_id": "codex-q1-parent", "agent_role": "implementer"}}})

    def compute_base_summary(self):
        if shutil.which("git") is None:
            self.skipTest("git is not available to extract the base_commit analytics package for the Q1 procedure")

        extract_dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, extract_dir, ignore_errors=True)
        archive = subprocess.run(
            f"git archive {BASE_COMMIT} analytics | tar -x -C '{extract_dir}'",
            shell=True, cwd=REPO_ROOT, capture_output=True, text=True)
        self.assertEqual(archive.returncode, 0, archive.stdout + archive.stderr)
        self.assertTrue((extract_dir / "analytics" / "app.py").is_file())

        result = subprocess.run(
            [sys.executable, "-c", BASE_SUMMARY_SCRIPT,
             str(self.root / "base.sqlite3"), str(self.telemetry_dir), str(self.prices),
             str(self.claude_root), str(self.codex_root)],
            cwd=extract_dir, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return json.loads(result.stdout)

    def test_q1_zero_pre_existing_summary_keys_change_value(self):
        self.build_pre_existing_behavior_fixture()

        base_summary = self.compute_base_summary()
        current_summary = self.make_client().get("/api/summary").json()

        self.assertNotIn("classification", base_summary)

        current_pre_existing = {k: v for k, v in current_summary.items() if k != "classification"}
        changed_keys = [key for key in base_summary
                         if key not in current_pre_existing or current_pre_existing[key] != base_summary[key]]
        self.assertEqual(changed_keys, [])
        self.assertEqual(current_pre_existing, base_summary)


if __name__ == "__main__":
    unittest.main()

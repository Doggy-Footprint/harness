import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from analytics.app import create_app

PRICES = ("models:\n  known-model:\n    input: 1\n    output: 1\n    cache_read: 1\n"
          "    cache_write_5m: 1\n    cache_write_1h: 1\n")
BRIEF_ENTRY_KEYS = {"stage", "round", "fact_questions", "user_decisions", "split", "picks_differ",
                    "ts", "session_id", "tool_use_id", "parsed"}
REASONS = ("intent_mismatch", "brief_change", "contract_change", "correction")
AMEND_KEYS = set(REASONS) | {"unspecified"}
NEW_SUMMARY_KEYS = {"brief_only_runs", "brief_questions"}
NEW_DETAIL_KEYS = {"briefs", "amend_reasons"}


def ts(day, hour=0):
    return f"2026-10-{day:02d}T{hour:02d}:00:00+00:00"


def event(name, run_id, session="claude-1", when="2026-09-22T00:00:00+00:00", **fields):
    return {"v": 1, "ts": when, "repo": "/repo", "client": "claude", "session_id": session,
            "agent_id": None, "agent_type": None, "tool_use_id": None, "event": name,
            "workflow_run_id": run_id, "spec": "analytics", "spec_version": 1, **fields}


def brief(run_id, stage="understanding", rnd=1, session="claude-1", when="2026-09-22T00:00:00+00:00",
          tool_use_id="toolu_1", **fields):
    values = {"fact_questions": None, "user_decisions": None, "split": None, "picks_differ": None}
    values.update(fields)
    return {"v": 1, "ts": when, "repo": "/repo", "client": "claude", "session_id": session,
            "agent_id": None, "agent_type": None, "tool_use_id": tool_use_id, "event": "brief",
            "workflow_run_id": run_id, "spec": None, "stage": stage, "round": rnd, **values}


def full_run(run_id, session="claude-1", when="2026-09-22T00:00:00+00:00", result="pass", status="complete"):
    return [event("workflow_start", run_id, session, when),
            event("workflow_phase", run_id, session, when, phase="implement_test"),
            event("workflow_phase", run_id, session, when, phase="verify"),
            event("verifier_result", run_id, session, when, round=1, result=result,
                  findings=0, seeds_run=0, seeds_detected=0),
            event("workflow_end", run_id, session, when, status=status)]


class DashboardCase(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.prices = self.root / "prices.yaml"
        self.prices.write_text(PRICES, encoding="utf-8")

    def make(self, name="a"):
        base = self.root / name
        telemetry = base / "telemetry"
        claude = base / "claude"
        codex = base / "codex"
        for directory in (telemetry, claude, codex):
            directory.mkdir(parents=True)
        client = TestClient(create_app(base / "analytics.sqlite3", telemetry, self.prices,
                                       {"claude": claude, "codex": codex}, frontend_dir=None))
        return client, telemetry, claude, base

    def write(self, telemetry, records, name="repo.jsonl"):
        with (telemetry / name).open("a", encoding="utf-8") as stream:
            for record in records:
                stream.write(json.dumps(record) + "\n")

    def transcript(self, claude, session, tokens=1):
        (claude / f"{session}.jsonl").write_text(json.dumps({
            "type": "assistant", "sessionId": session,
            "message": {"model": "known-model", "usage": {"input_tokens": tokens, "output_tokens": 0}},
        }) + "\n", encoding="utf-8")


class TestBriefOnlyRunsAndDetail(DashboardCase):
    def setUp(self):
        super().setUp()
        self.client, self.telemetry, self.claude, self.base = self.make()

    def summary(self):
        return self.client.get("/api/summary").json()

    def test_a1_brief_only_run_is_listed_and_excluded_from_every_existing_field(self):
        self.write(self.telemetry, full_run("run-full"))
        baseline = self.summary()
        self.write(self.telemetry, [
            brief("run-brief", "understanding", 1, when=ts(1)),
            brief("run-brief", "decision", 1, when=ts(2), tool_use_id="toolu_2"),
        ])
        summary = self.summary()
        self.assertEqual(summary["brief_only_runs"],
                         [{"run_id": "run-brief", "rounds": 2, "last_stage": "decision",
                           "last_ts": ts(2)}])
        for key, value in baseline.items():
            if key not in NEW_SUMMARY_KEYS:
                self.assertEqual(summary[key], value, key)
        self.assertEqual([item["run_id"] for item in summary["run_items"]], ["run-full"])
        self.assertEqual([item["run_id"] for item in summary["workflow"]["runs"]], ["run-full"])
        self.assertEqual(summary["runs"], 1)

    def test_a2_brief_only_runs_are_ordered_by_last_ts_descending_with_latest_event_fields(self):
        self.write(self.telemetry, [
            brief("run-old", "understanding", 1, when=ts(1)),
            brief("run-old", "decision", 1, when=ts(2), tool_use_id="toolu_2"),
            brief("run-new", "decision", 2, when=ts(9), tool_use_id="toolu_3"),
            brief("run-new", "understanding", 1, when=ts(3), tool_use_id="toolu_4"),
        ])
        self.assertEqual(self.summary()["brief_only_runs"], [
            {"run_id": "run-new", "rounds": 2, "last_stage": "decision", "last_ts": ts(9)},
            {"run_id": "run-old", "rounds": 2, "last_stage": "decision", "last_ts": ts(2)},
        ])

    def test_a3_briefs_on_a_full_run_appear_in_stored_order_with_all_entry_keys(self):
        self.write(self.telemetry, [
            brief("run-full", "decision", 2, when=ts(5), tool_use_id="toolu_b", fact_questions=2,
                  user_decisions=1, split="proposed", picks_differ=None, session="claude-9"),
            brief("run-full", "understanding", 1, when=ts(3), tool_use_id="toolu_a", fact_questions=0,
                  user_decisions=0, split="none", picks_differ=0),
            *full_run("run-full"),
        ])
        detail = self.client.get("/api/runs/run-full").json()
        self.assertEqual(detail["briefs"], [
            {"stage": "decision", "round": 2, "fact_questions": 2, "user_decisions": 1,
             "split": "proposed", "picks_differ": None, "ts": ts(5), "session_id": "claude-9",
             "tool_use_id": "toolu_b", "parsed": None},
            {"stage": "understanding", "round": 1, "fact_questions": 0, "user_decisions": 0,
             "split": "none", "picks_differ": 0, "ts": ts(3), "session_id": "claude-1",
             "tool_use_id": "toolu_a", "parsed": None},
        ])
        for entry in detail["briefs"]:
            self.assertEqual(set(entry), BRIEF_ENTRY_KEYS)
        self.assertEqual(detail["status"], "complete")
        self.assertEqual(self.summary()["brief_only_runs"], [])

    def test_a4_amend_reasons_count_each_value_null_missing_and_unknown(self):
        amends = [
            event("workflow_phase", "run-amend", phase="amend", reason="intent_mismatch"),
            event("workflow_phase", "run-amend", phase="amend", reason="brief_change"),
            event("workflow_phase", "run-amend", phase="amend", reason="brief_change"),
            event("workflow_phase", "run-amend", phase="amend", reason="contract_change"),
            event("workflow_phase", "run-amend", phase="amend", reason="correction"),
            event("workflow_phase", "run-amend", phase="amend", reason=None),
            event("workflow_phase", "run-amend", phase="amend"),
            event("workflow_phase", "run-amend", phase="amend", reason="weird"),
        ]
        non_amend = [event("workflow_phase", "run-amend", phase="verify", reason="correction")]
        self.write(self.telemetry, [event("workflow_start", "run-amend"), *non_amend, *amends])
        detail = self.client.get("/api/runs/run-amend").json()
        self.assertEqual(detail["amend_reasons"], {
            "intent_mismatch": 1, "brief_change": 2, "contract_change": 1, "correction": 1,
            "unspecified": 3})
        self.assertEqual(set(detail["amend_reasons"]), AMEND_KEYS)
        for value in detail["amend_reasons"].values():
            self.assertIs(type(value), int)

    def test_a4_run_without_amends_reports_zero_counts_and_no_briefs(self):
        self.write(self.telemetry, full_run("run-plain"))
        detail = self.client.get("/api/runs/run-plain").json()
        self.assertEqual(detail["amend_reasons"], {key: 0 for key in AMEND_KEYS})
        self.assertEqual(detail["briefs"], [])

    def test_a5_brief_only_run_detail_is_200_before_approval(self):
        self.write(self.telemetry, [brief("run-brief", "understanding", 1, when=ts(1))])
        response = self.client.get("/api/runs/run-brief")
        self.assertEqual(response.status_code, 200)
        detail = response.json()
        self.assertEqual(detail["status"], "before_approval")
        self.assertEqual([(b["stage"], b["round"]) for b in detail["briefs"]], [("understanding", 1)])
        self.assertEqual(detail["amend_reasons"], {key: 0 for key in AMEND_KEYS})

    def test_a6_unknown_run_is_404_without_state_change(self):
        self.write(self.telemetry, [brief("run-brief")])
        before = self.summary()
        self.assertEqual(self.client.get("/api/runs/unknown-run").status_code, 404)
        self.assertEqual(self.summary(), before)

    def fact(self, run_id, when, session="claude-1"):
        return {"v": 1, "ts": when, "repo": "/repo", "client": "claude", "session_id": session,
                "agent_id": None, "agent_type": None, "tool_use_id": "toolu_f", "event": "fact_write",
                "workflow_run_id": run_id, "spec": None, "fact_id": "67ac615b0c9ad3aa",
                "dimension": "consumers"}

    def test_a8_group_of_brief_and_fact_write_events_is_brief_only(self):
        self.write(self.telemetry, full_run("run-full"))
        baseline = self.summary()
        self.write(self.telemetry, [
            self.fact("run-bf", ts(1)),
            brief("run-bf", "understanding", 1, when=ts(2)),
            self.fact("run-bf", ts(9)),
        ])
        summary = self.summary()
        self.assertEqual(summary["brief_only_runs"],
                         [{"run_id": "run-bf", "rounds": 1, "last_stage": "understanding",
                           "last_ts": ts(2)}])
        for key, value in baseline.items():
            if key not in NEW_SUMMARY_KEYS:
                self.assertEqual(summary[key], value, key)
        response = self.client.get("/api/runs/run-bf")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "before_approval")

    def test_a8_fact_write_events_belong_to_no_run(self):
        self.write(self.telemetry, [self.fact("run-facts-only", ts(1))])
        self.assertEqual(self.client.get("/api/runs/run-facts-only").status_code, 404)
        summary = self.summary()
        self.assertEqual(summary["brief_only_runs"], [])
        self.assertEqual(summary["runs"], 0)
        self.assertEqual(summary["run_items"], [])

    def test_a7_missing_pointer_and_stage_fields_are_null(self):
        record = brief("run-brief", "decision", 3, when=ts(1))
        for key in ("tool_use_id", "session_id", "stage", "round"):
            del record[key]
        self.write(self.telemetry, [record])
        response = self.client.get("/api/runs/run-brief")
        self.assertEqual(response.status_code, 200)
        (entry,) = response.json()["briefs"]
        self.assertEqual(set(entry), BRIEF_ENTRY_KEYS)
        for key in ("tool_use_id", "session_id", "stage", "round"):
            self.assertIsNone(entry[key], key)
        self.assertEqual(self.summary()["brief_only_runs"][0]["run_id"], "run-brief")

    def test_a7_each_missing_pointer_field_alone_is_null(self):
        for missing in ("tool_use_id", "session_id", "stage", "round"):
            with self.subTest(missing=missing):
                client, telemetry, _, _ = self.make(f"m-{missing}")
                record = brief("run-b", "approval", 4, session="claude-7", tool_use_id="toolu_7",
                               when=ts(1))
                del record[missing]
                self.write(telemetry, [record])
                (entry,) = client.get("/api/runs/run-b").json()["briefs"]
                expected = {"stage": "approval", "round": 4, "session_id": "claude-7",
                            "tool_use_id": "toolu_7"}
                for key, value in expected.items():
                    self.assertEqual(entry[key], None if key == missing else value, key)


class TestImporterFields(DashboardCase):
    FIELDS = {"stage": "decision", "reason": "correction", "fact_id": "67ac615b0c9ad3aa",
              "dimension": "consumers", "fact_questions": 3, "user_decisions": 4, "split": "accepted",
              "picks_differ": 5}

    def stored(self, telemetry_records):
        client, telemetry, _, base = self.make()
        self.write(telemetry, telemetry_records)
        self.assertEqual(client.get("/api/summary").status_code, 200)
        with sqlite3.connect(base / "analytics.sqlite3") as connection:
            rows = connection.execute("SELECT run_id, payload FROM events").fetchall()
        return {run_id: json.loads(payload) for run_id, payload in rows}

    def test_scalar_values_are_kept_in_the_stored_payload(self):
        record = {**brief("run-scalar"), **self.FIELDS}
        stored = self.stored([record])["run-scalar"]
        for key, value in self.FIELDS.items():
            self.assertEqual(stored.get(key), value, key)

    def test_list_values_are_dropped_per_field(self):
        records = [{**brief(f"run-{key}"), **self.FIELDS, key: ["x", 1]} for key in self.FIELDS]
        stored = self.stored(records)
        for key in self.FIELDS:
            with self.subTest(field=key):
                payload = stored[f"run-{key}"]
                self.assertNotIn(key, payload)
                for other, value in self.FIELDS.items():
                    if other != key:
                        self.assertEqual(payload.get(other), value, other)


class TestMetamorphicCompatibility(DashboardCase):
    SESSIONS = ("claude-1", "claude-2", "claude-3", "claude-free", "claude-brief")

    def dataset(self, name, extra):
        client, telemetry, claude, _ = self.make(name)
        for index, session in enumerate(self.SESSIONS, start=1):
            self.transcript(claude, session, tokens=index * 10)
        duplicate = full_run("run-3", "claude-3")
        duplicate.insert(1, event("workflow_start", "run-3", "claude-3"))
        orphan = {"v": 1, "ts": "2026-09-22T00:00:00+00:00", "repo": "/repo", "client": "claude",
                  "session_id": "claude-free", "agent_id": None, "agent_type": "general-purpose",
                  "tool_use_id": None, "event": "subagent_stop", "workflow_run_id": None, "spec": None}
        self.write(telemetry, [orphan, *full_run("run-1", "claude-1"),
                               *full_run("run-2", "claude-2", status="handoff"), *duplicate])
        if extra:
            self.write(telemetry, self.extra_events(), name="extra.jsonl")
        return client

    def extra_events(self):
        fact = {"v": 1, "ts": ts(1), "repo": "/repo", "client": "claude", "session_id": "claude-1",
                "agent_id": None, "agent_type": None, "tool_use_id": "toolu_f", "event": "fact_write",
                "workflow_run_id": None, "spec": None, "fact_id": "67ac615b0c9ad3aa",
                "dimension": "consumers"}
        return [
            brief("run-1", "understanding", 1, session="claude-1", when="2026-09-21T00:00:00+00:00"),
            brief("run-1", "decision", 1, session="claude-2", when="2026-09-21T01:00:00+00:00",
                  tool_use_id="toolu_2", user_decisions=2),
            brief("run-2", "approval", 1, session="claude-3", when="2026-09-21T02:00:00+00:00",
                  tool_use_id="toolu_3", picks_differ=1),
            brief("run-only", "understanding", 1, session="claude-brief", when=ts(1)),
            brief("run-only", "decision", 1, session="claude-free", when=ts(2), tool_use_id="toolu_5"),
            brief("run-only", "approval", 1, session="claude-1", when=ts(3), tool_use_id="toolu_6"),
            fact,
            {**fact, "session_id": "claude-brief", "tool_use_id": "toolu_g"},
        ]

    def setUp(self):
        super().setUp()
        self.base_client = self.dataset("base", extra=False)
        self.plus_client = self.dataset("plus", extra=True)
        self.base_summary = self.base_client.get("/api/summary").json()
        self.plus_summary = self.plus_client.get("/api/summary").json()

    def test_mr0_fixture_is_not_vacuous(self):
        base = self.base_summary
        self.assertEqual(base["runs"], 3)
        self.assertGreaterEqual(base["non_workflow"]["sessions"], 1)
        self.assertTrue(sum(base["classification"]["sessions"].values()) > 0)
        self.assertEqual([r["run_id"] for r in self.plus_summary["brief_only_runs"]], ["run-only"])

    def test_mr1_every_preexisting_summary_key_is_equal(self):
        for key, value in self.base_summary.items():
            if key in NEW_SUMMARY_KEYS:
                continue
            with self.subTest(key=key):
                self.assertEqual(self.plus_summary[key], value)

    def test_mr2_every_preexisting_run_detail_key_is_equal(self):
        for run_id in ("run-1", "run-2", "run-3"):
            base = self.base_client.get(f"/api/runs/{run_id}").json()
            plus = self.plus_client.get(f"/api/runs/{run_id}").json()
            for key, value in base.items():
                if key in NEW_DETAIL_KEYS:
                    continue
                with self.subTest(run=run_id, key=key):
                    plus_value = json.loads(json.dumps(plus[key]).replace(
                        str(self.root / "plus"), str(self.root / "base")))
                    self.assertEqual(plus_value, value)

    def test_mr3_brief_events_sharing_sessions_do_not_link_or_reclassify(self):
        for key in ("classification", "non_workflow", "workflow", "linked_cost_usd"):
            with self.subTest(key=key):
                self.assertEqual(self.plus_summary[key], self.base_summary[key])
        for run_id, sessions in (("run-1", {"claude-1"}), ("run-2", {"claude-2"})):
            detail = self.plus_client.get(f"/api/runs/{run_id}").json()
            linked = {item["session_id"] for item in detail["transcript_metadata"]}
            self.assertEqual(linked, sessions, run_id)

    def test_brief_events_on_existing_runs_are_reported_in_briefs(self):
        detail = self.plus_client.get("/api/runs/run-1").json()
        self.assertEqual([(b["stage"], b["round"], b["session_id"]) for b in detail["briefs"]],
                         [("understanding", 1, "claude-1"), ("decision", 1, "claude-2")])
        self.assertEqual(self.base_client.get("/api/runs/run-1").json()["briefs"], [])


if __name__ == "__main__":
    unittest.main()

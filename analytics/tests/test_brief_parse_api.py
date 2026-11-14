import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from analytics.app import create_app

PRICES = ("models:\n  known-model:\n    input: 1\n    output: 1\n    cache_read: 1\n"
          "    cache_write_5m: 1\n    cache_write_1h: 1\n")
BRIEF_ENTRY_KEYS = {"stage", "round", "fact_questions", "user_decisions", "split", "picks_differ",
                    "ts", "session_id", "tool_use_id"}
QUESTION_ENTRY_KEYS = {"run_id", "stage", "round", "ts", "kind", "text"}
BASE_COMMIT = "ba8371a30185421045dab149bbe1bb324d4cb4cd"
REPO_ROOT = Path(__file__).resolve().parents[2]
BASE_IMPORT_SCRIPT = """
import sys
from pathlib import Path

from analytics.app import create_app
from fastapi.testclient import TestClient

db_path, telemetry_dir, prices_path, claude_dir, codex_dir = (Path(p) for p in sys.argv[1:6])
client = TestClient(create_app(db_path, telemetry_dir, prices_path,
                                {"claude": claude_dir, "codex": codex_dir}, frontend_dir=None))
assert client.get("/api/summary").status_code == 200
"""
_AUDIT = {"counter": None, "installed": False}


class OpenCounter:
    """Counts audit `open` events on one file while active; audit hooks cannot be removed,
    so a single process-wide hook consults the active counter."""

    def __init__(self, target):
        self.target = os.path.realpath(target)
        self.count = 0

    def __enter__(self):
        if not _AUDIT["installed"]:
            sys.addaudithook(_audit)
            _AUDIT["installed"] = True
        _AUDIT["counter"] = self
        return self

    def __exit__(self, *exc):
        _AUDIT["counter"] = None


def _audit(event, args):
    counter = _AUDIT["counter"]
    if counter is None or event != "open" or not args:
        return
    candidate = args[0]
    if isinstance(candidate, (str, bytes, os.PathLike)):
        try:
            if os.path.realpath(candidate) == counter.target:
                counter.count += 1
        except (OSError, ValueError, TypeError):
            pass


IS_ROOT = hasattr(os, "geteuid") and os.geteuid() == 0
ROOT_SKIP = "running as root: file mode bits do not make a file unreadable"


def ts(day, hour=0):
    return f"2026-10-{day:02d}T{hour:02d}:00:00+00:00"


def event(name, run_id, session="s1", when="2026-09-22T00:00:00+00:00", **fields):
    return {"v": 1, "ts": when, "repo": "/repo", "client": "claude", "session_id": session,
            "agent_id": None, "agent_type": None, "tool_use_id": None, "event": name,
            "workflow_run_id": run_id, "spec": "analytics", "spec_version": 1, **fields}


def brief(run_id, stage="understanding", rnd=1, session="s1", when="2026-09-22T00:00:00+00:00",
          tool_use_id="tu-1", client="claude"):
    return {"v": 1, "ts": when, "repo": "/repo", "client": client, "session_id": session,
            "agent_id": None, "agent_type": None, "tool_use_id": tool_use_id, "event": "brief",
            "workflow_run_id": run_id, "spec": None, "stage": stage, "round": rnd,
            "fact_questions": None, "user_decisions": None, "split": None, "picks_differ": None}


def full_run(run_id, session="s1", when="2026-09-22T00:00:00+00:00"):
    return [event("workflow_start", run_id, session, when),
            event("workflow_phase", run_id, session, when, phase="implement_test"),
            event("workflow_phase", run_id, session, when, phase="verify"),
            event("verifier_result", run_id, session, when, round=1, result="pass",
                  findings=0, seeds_run=0, seeds_detected=0),
            event("workflow_end", run_id, session, when, status="complete")]


def text_block(value):
    return {"type": "text", "text": value}


def tool_use(identifier):
    return {"type": "tool_use", "id": identifier, "name": "Bash", "input": {}}


def assistant(*blocks):
    return {"type": "assistant", "isSidechain": False, "message": {"content": list(blocks)}}


def user(content):
    return {"type": "user", "message": {"content": content}}


def turn(prompt, tool_use_id, text):
    return [user(prompt), assistant(tool_use(tool_use_id)), assistant(text_block(text))]


def fact(value):
    return {"kind": "fact", "text": value}


def decision(value):
    return {"kind": "decision", "text": value}


def result(text, understanding, questions):
    return {"text": text, "understanding": understanding, "questions": questions}


def lines(*rows):
    return "\n".join(rows)


TEXT_U = lines("## 제가 이해한 내용", "", "첫 문단.", "", "둘째 문단.", "",
               "## Fact question", "", "1. **A?**", "2. **B?**")
PARSED_U = result(TEXT_U, "첫 문단.\n\n둘째 문단.", [fact("A?"), fact("B?")])
TEXT_D = lines("## Decision round", "", "**1. Which store?**", "**2. Retry policy?**")
PARSED_D = result(TEXT_D, None, [decision("Which store?"), decision("Retry policy?")])
TEXT_Z = lines("## Decision round", "- Z1", "- Z2")
PARSED_Z = result(TEXT_Z, None, [decision("Z1"), decision("Z2")])


class ApiCase(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.prices = self.root / "prices.yaml"
        self.prices.write_text(PRICES, encoding="utf-8")

    def make(self, name="a"):
        base = self.root / name
        self.telemetry = base / "telemetry"
        self.claude = base / "claude"
        codex = base / "codex"
        for directory in (self.telemetry, self.claude, codex):
            directory.mkdir(parents=True)
        self.db = base / "analytics.sqlite3"
        self.client = TestClient(create_app(self.db, self.telemetry, self.prices,
                                            {"claude": self.claude, "codex": codex},
                                            frontend_dir=None))
        return self.client

    def write_events(self, records, name="repo.jsonl"):
        with (self.telemetry / name).open("a", encoding="utf-8") as stream:
            for record in records:
                stream.write(json.dumps(record) + "\n")

    def write_transcript(self, records, session="s1", directory=None, raw=None):
        directory = directory or self.claude
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{session}.jsonl"
        rows = raw if raw is not None else [json.dumps(item) for item in records]
        path.write_text("".join(row + "\n" for row in rows), encoding="utf-8")
        return path

    def append(self, path, records):
        with path.open("a", encoding="utf-8") as stream:
            for item in records:
                stream.write(json.dumps(item) + "\n")

    def detail(self, run_id):
        response = self.client.get(f"/api/runs/{run_id}")
        self.assertEqual(response.status_code, 200)
        return response.json()

    def parsed(self, run_id, index=0):
        return self.detail(run_id)["briefs"][index]["parsed"]

    def summary(self):
        response = self.client.get("/api/summary")
        self.assertEqual(response.status_code, 200)
        return response.json()

    def rows(self):
        connection = sqlite3.connect(self.db)
        try:
            return connection.execute(
                "SELECT session_id, tool_use_id, data FROM brief_parse ORDER BY 1, 2").fetchall()
        finally:
            connection.close()


class TestDecisionTable(ApiCase):
    def test_a1_a2_two_briefs_in_one_transcript_and_a_brief_only_run_in_another(self):
        self.make()
        self.write_events([
            *full_run("run-1", "s1"),
            brief("run-1", "understanding", 1, "s1", ts(3), "tu-1"),
            brief("run-1", "decision", 2, "s1", ts(5), "tu-2"),
            brief("run-2", "approval", 1, "s2", ts(4), "tu-3"),
        ])
        self.write_transcript(turn("p1", "tu-1", TEXT_U) + turn("p2", "tu-2", TEXT_D), "s1")
        self.write_transcript(turn("q", "tu-3", TEXT_Z), "s2")

        first = self.detail("run-1")["briefs"]
        self.assertEqual([entry["parsed"] for entry in first], [PARSED_U, PARSED_D])
        for entry in first:
            self.assertEqual(set(entry), BRIEF_ENTRY_KEYS | {"parsed"})
        self.assertEqual(self.parsed("run-2"), PARSED_Z)

        self.assertEqual(self.summary()["brief_questions"], [
            {"run_id": "run-1", "stage": "decision", "round": 2, "ts": ts(5), "kind": "decision",
             "text": "Which store?"},
            {"run_id": "run-1", "stage": "decision", "round": 2, "ts": ts(5), "kind": "decision",
             "text": "Retry policy?"},
            {"run_id": "run-2", "stage": "approval", "round": 1, "ts": ts(4), "kind": "decision",
             "text": "Z1"},
            {"run_id": "run-2", "stage": "approval", "round": 1, "ts": ts(4), "kind": "decision",
             "text": "Z2"},
            {"run_id": "run-1", "stage": "understanding", "round": 1, "ts": ts(3), "kind": "fact",
             "text": "A?"},
            {"run_id": "run-1", "stage": "understanding", "round": 1, "ts": ts(3), "kind": "fact",
             "text": "B?"},
        ])

    def test_a3_order_is_ts_descending_null_last_then_stored_order_then_question_order(self):
        self.make()
        self.write_events([
            brief("run-A", "understanding", 1, "s-order", ts(5), "tu-1"),
            brief("run-B", "decision", 1, "s-order", None, "tu-2"),
            brief("run-A", "decision", 2, "s-order", ts(9), "tu-3"),
            brief("run-B", "approval", 1, "s-order", ts(5), "tu-4"),
        ])
        records = []
        for number in (1, 2, 3, 4):
            records += turn(f"p{number}", f"tu-{number}",
                            lines("## Decision round", f"- n{number}-first", f"- n{number}-second"))
        self.write_transcript(records, "s-order")

        entries = self.summary()["brief_questions"]
        self.assertEqual([(item["run_id"], item["stage"], item["round"], item["ts"], item["text"])
                          for item in entries], [
            ("run-A", "decision", 2, ts(9), "n3-first"),
            ("run-A", "decision", 2, ts(9), "n3-second"),
            ("run-A", "understanding", 1, ts(5), "n1-first"),
            ("run-A", "understanding", 1, ts(5), "n1-second"),
            ("run-B", "approval", 1, ts(5), "n4-first"),
            ("run-B", "approval", 1, ts(5), "n4-second"),
            ("run-B", "decision", 1, None, "n2-first"),
            ("run-B", "decision", 1, None, "n2-second"),
        ])
        for item in entries:
            self.assertEqual(set(item), QUESTION_ENTRY_KEYS)
            self.assertEqual(item["kind"], "decision")

    def test_a3_ts_tie_uses_stored_order_not_run_id_or_tool_use_id_order(self):
        self.make()
        self.write_events([
            brief("run-Z", "understanding", 1, "s-tie", ts(5), "tu-9"),
            brief("run-M", "decision", 1, "s-tie", ts(5), "tu-5"),
            brief("run-A", "approval", 1, "s-tie", ts(5), "tu-1"),
        ])
        records = []
        for number, label in ((9, "nine"), (5, "five"), (1, "one")):
            records += turn(f"p{number}", f"tu-{number}",
                            lines("## Decision round", f"- {label}-first", f"- {label}-second"))
        self.write_transcript(records, "s-tie")
        self.assertEqual([(item["run_id"], item["text"]) for item in self.summary()["brief_questions"]], [
            ("run-Z", "nine-first"), ("run-Z", "nine-second"),
            ("run-M", "five-first"), ("run-M", "five-second"),
            ("run-A", "one-first"), ("run-A", "one-second"),
        ])

    def test_a9_invalid_json_cache_row_gives_null_for_that_brief_only(self):
        self.make()
        self.write_events([
            brief("run-1", "understanding", 1, "s1", ts(3), "tu-1"),
            brief("run-1", "decision", 2, "s1", ts(5), "tu-2"),
        ])
        self.write_transcript(turn("p1", "tu-1", TEXT_U) + turn("p2", "tu-2", TEXT_D), "s1")
        self.assertEqual([e["parsed"] for e in self.detail("run-1")["briefs"]], [PARSED_U, PARSED_D])
        self.assertEqual(len(self.rows()), 2)

        def break_row():
            connection = sqlite3.connect(self.db)
            try:
                connection.execute("UPDATE brief_parse SET data='{not json' WHERE tool_use_id='tu-1'")
                connection.commit()
            finally:
                connection.close()

        break_row()
        briefs = self.detail("run-1")["briefs"]
        self.assertEqual([entry["parsed"] for entry in briefs], [None, PARSED_D])
        break_row()
        self.assertEqual([(item["stage"], item["text"]) for item in self.summary()["brief_questions"]],
                         [("decision", "Which store?"), ("decision", "Retry policy?")])

    def test_a4_each_null_cause_gives_parsed_null_with_http_200(self):
        self.make()
        present = turn("p", "tu-x", TEXT_U)
        self.write_transcript(present, "s-nulltu")
        self.write_transcript(present, "s-codex")
        self.write_transcript(turn("p", "tu-other", TEXT_U), "s-absent")
        self.write_transcript(present, "s-numeric")
        (self.claude / "s-bad.jsonl").write_bytes(
            (json.dumps(present[1]) + "\n").encode("utf-8") + b"\xff\xfe\n"
            + (json.dumps(present[2]) + "\n").encode("utf-8"))
        causes = {
            "missing_file": brief("run-missing", session="s-missing", tool_use_id="tu-x"),
            "null_tool_use_id": brief("run-nulltu", session="s-nulltu", tool_use_id=None),
            "null_session_id": brief("run-nullsess", session=None, tool_use_id="tu-x"),
            "non_string_tool_use_id": brief("run-numeric", session="s-numeric", tool_use_id=123),
            "codex_client": brief("run-codex", session="s-codex", tool_use_id="tu-x", client="codex"),
            "absent_tool_use_id": brief("run-absent", session="s-absent", tool_use_id="tu-x"),
            "invalid_utf8": brief("run-bad", session="s-bad", tool_use_id="tu-x"),
        }
        self.write_events(list(causes.values()))
        for cause, record in causes.items():
            with self.subTest(cause=cause):
                self.assertIsNone(self.parsed(record["workflow_run_id"]))
        self.assertEqual(self.summary()["brief_questions"], [])
        self.assertEqual(self.rows(), [("s-absent", "tu-x", None)])

    def test_a5_broken_json_and_non_object_lines_are_skipped_and_the_rest_parses(self):
        self.make()
        self.write_events([brief("run-1", tool_use_id="tu-1")])
        good = turn("p", "tu-1", TEXT_U)
        raw = ["not json at all", json.dumps(good[0]), "[1, 2]", "", json.dumps(good[1]),
               '"a string"', "3", "{broken", json.dumps(good[2]), "null"]
        self.write_transcript(None, "s1", raw=raw)
        self.assertEqual(self.parsed("run-1"), PARSED_U)

    def test_a6_transcript_under_a_subagents_directory_is_ignored(self):
        self.make()
        self.write_events([brief("run-1", tool_use_id="tu-1"), brief("run-2", session="s2",
                                                                      tool_use_id="tu-1")])
        self.write_transcript(turn("p", "tu-1", TEXT_Z), "s1",
                              directory=self.claude / "a-project" / "subagents")
        self.write_transcript(turn("p", "tu-1", TEXT_U), "s2",
                              directory=self.claude / "a-project" / "subagents")
        self.write_transcript(turn("p", "tu-1", TEXT_D), "s2", directory=self.claude / "z-project")
        self.assertIsNone(self.parsed("run-1"))
        self.assertEqual(self.parsed("run-2"), PARSED_D)

    def test_a7_two_candidate_paths_use_the_lexicographically_first(self):
        self.make()
        self.write_events([brief("run-1", tool_use_id="tu-1")])
        self.write_transcript(turn("p", "tu-1", TEXT_D), "s1", directory=self.claude / "b-project")
        self.write_transcript(turn("p", "tu-1", TEXT_U), "s1", directory=self.claude / "a-project")
        self.assertEqual(self.parsed("run-1"), PARSED_U)

    def test_a7_first_path_without_the_tool_use_id_is_not_skipped_for_the_second(self):
        self.make()
        self.write_events([brief("run-1", tool_use_id="tu-1")])
        self.write_transcript(turn("p", "tu-other", TEXT_Z), "s1", directory=self.claude / "a-project")
        self.write_transcript(turn("p", "tu-1", TEXT_U), "s1", directory=self.claude / "b-project")
        self.assertIsNone(self.parsed("run-1"))

    def test_a8_parsed_brief_without_questions_adds_no_summary_entry(self):
        self.make()
        self.write_events([
            brief("run-1", "understanding", 1, "s1", ts(1), "tu-1"),
            brief("run-1", "decision", 2, "s1", ts(2), "tu-2"),
            brief("run-1", "approval", 3, "s1", ts(3), "tu-3"),
        ])
        only_understanding = "## Understanding\nonly this"
        self.write_transcript(
            turn("p1", "tu-1", only_understanding) + turn("p2", "tu-2", TEXT_Z)
            + [user("p3"), assistant(tool_use("tu-3"))], "s1")
        briefs = self.detail("run-1")["briefs"]
        self.assertEqual(briefs[0]["parsed"], result(only_understanding, "only this", []))
        self.assertEqual(briefs[1]["parsed"], PARSED_Z)
        self.assertEqual(briefs[2]["parsed"], result("", None, []))
        self.assertEqual([(item["stage"], item["text"]) for item in self.summary()["brief_questions"]],
                         [("decision", "Z1"), ("decision", "Z2")])


class TestStateTransitions(ApiCase):
    def setUp(self):
        super().setUp()
        self.make()
        self.write_events([brief("run-1", tool_use_id="tu-1")])

    @unittest.skipIf(IS_ROOT, ROOT_SKIP)
    def test_parsed_row_is_reused_while_unreadable_then_reparsed_after_growth(self):
        path = self.write_transcript(turn("p", "tu-1", TEXT_U))
        self.assertEqual(self.parsed("run-1"), PARSED_U)
        self.assertEqual([(row[0], row[1], row[2] is not None) for row in self.rows()],
                         [("s1", "tu-1", True)])

        self.addCleanup(os.chmod, path, 0o644)
        os.chmod(path, 0)
        self.assertEqual(self.parsed("run-1"), PARSED_U)

        os.chmod(path, 0o644)
        extra = "## Decision round\n1. **C?**"
        self.append(path, [assistant(text_block(extra))])
        self.assertEqual(self.parsed("run-1"), result(
            TEXT_U + "\n\n" + extra, "첫 문단.\n\n둘째 문단.",
            [fact("A?"), fact("B?"), decision("C?")]))
        self.assertEqual(len(self.rows()), 1)

    def clear_rows(self):
        connection = sqlite3.connect(self.db)
        try:
            connection.execute("DELETE FROM brief_parse")
            connection.commit()
        finally:
            connection.close()

    def test_one_request_opens_a_shared_transcript_at_most_once(self):
        self.write_events([brief("run-1", "decision", 2, "s1", ts(5), "tu-2"),
                           brief("run-1", "approval", 3, "s1", ts(6), "tu-3")])
        path = self.write_transcript(turn("p1", "tu-1", TEXT_U) + turn("p2", "tu-2", TEXT_D)
                                     + turn("p3", "tu-3", TEXT_Z))
        self.assertEqual([e["parsed"] for e in self.detail("run-1")["briefs"]][-2:],
                         [PARSED_D, PARSED_Z])
        self.summary()

        self.clear_rows()
        with OpenCounter(path) as counter:
            briefs = self.detail("run-1")["briefs"]
        self.assertLessEqual(counter.count, 1)
        self.assertEqual([e["parsed"] for e in briefs][-2:], [PARSED_D, PARSED_Z])

        self.clear_rows()
        with OpenCounter(path) as counter:
            questions = self.summary()["brief_questions"]
        self.assertLessEqual(counter.count, 1)
        self.assertEqual([item["text"] for item in questions],
                         ["Z1", "Z2", "Which store?", "Retry policy?", "A?", "B?"])

    def full_rows(self):
        connection = sqlite3.connect(self.db)
        try:
            return connection.execute("SELECT * FROM brief_parse ORDER BY 1, 2").fetchall()
        finally:
            connection.close()

    GROWN_TAIL = "## Decision round\n1. **C?**"
    GROWN_QUESTIONS = [fact("A?"), fact("B?"), decision("C?")]

    @unittest.skipIf(IS_ROOT, ROOT_SKIP)
    def test_grown_while_unreadable_gives_null_and_keeps_the_row_then_reparses_once_readable(self):
        path = self.write_transcript(turn("p", "tu-1", TEXT_U))
        self.assertEqual(self.parsed("run-1"), PARSED_U)
        captured = self.full_rows()
        self.assertEqual(len(captured), 1)

        self.append(path, [assistant(text_block(self.GROWN_TAIL))])
        self.addCleanup(os.chmod, path, 0o644)
        os.chmod(path, 0)
        self.assertIsNone(self.parsed("run-1"))
        self.assertEqual(self.full_rows(), captured)

        os.chmod(path, 0o644)
        self.assertEqual(self.parsed("run-1"), result(
            TEXT_U + "\n\n" + self.GROWN_TAIL, "첫 문단.\n\n둘째 문단.", self.GROWN_QUESTIONS))

    def test_grown_with_invalid_utf8_gives_null_and_keeps_the_row_then_reparses_once_valid(self):
        path = self.write_transcript(turn("p", "tu-1", TEXT_U))
        self.assertEqual(self.parsed("run-1"), PARSED_U)
        captured = self.full_rows()
        self.assertEqual(len(captured), 1)

        self.append(path, [assistant(text_block(self.GROWN_TAIL))])
        with path.open("ab") as stream:
            stream.write(b"\xff\xfe\n")
        self.assertIsNone(self.parsed("run-1"))
        self.assertEqual(self.full_rows(), captured)

        valid = turn("p", "tu-1", TEXT_U) + [assistant(text_block(self.GROWN_TAIL)),
                                             assistant(text_block("closing note"))]
        self.write_transcript(valid)
        self.assertEqual(self.parsed("run-1"), result(
            TEXT_U + "\n\n" + self.GROWN_TAIL + "\n\nclosing note", "첫 문단.\n\n둘째 문단.",
            self.GROWN_QUESTIONS))

    def test_unchanged_path_size_and_mtime_reuse_the_cached_result_without_reading_content(self):
        path = self.write_transcript(turn("p", "tu-1", TEXT_U))
        self.assertEqual(self.parsed("run-1"), PARSED_U)
        stat = path.stat()
        swapped = path.read_text(encoding="utf-8").replace("A?", "Z?")
        self.assertEqual(len(swapped.encode("utf-8")), stat.st_size)
        path.write_text(swapped, encoding="utf-8")
        os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))
        self.assertEqual(self.parsed("run-1"), PARSED_U)

    def test_changed_mtime_with_same_size_reparses(self):
        path = self.write_transcript(turn("p", "tu-1", TEXT_U))
        self.assertEqual(self.parsed("run-1"), PARSED_U)
        stat = path.stat()
        path.write_text(path.read_text(encoding="utf-8").replace("A?", "Z?"), encoding="utf-8")
        os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 5_000_000_000))
        self.assertEqual(self.parsed("run-1")["questions"], [fact("Z?"), fact("B?")])

    def test_changed_path_with_same_size_and_mtime_reparses(self):
        path = self.write_transcript(turn("p", "tu-1", TEXT_U))
        self.assertEqual(self.parsed("run-1"), PARSED_U)
        stat = path.stat()
        path.write_text(path.read_text(encoding="utf-8").replace("A?", "Z?"), encoding="utf-8")
        os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))
        moved = self.claude / "moved"
        moved.mkdir()
        shutil.move(str(path), str(moved / path.name))
        self.assertEqual(self.parsed("run-1")["questions"], [fact("Z?"), fact("B?")])

    def test_absent_tool_use_gives_a_null_row_then_parses_after_append(self):
        path = self.write_transcript(turn("p", "tu-other", TEXT_Z))
        self.assertIsNone(self.parsed("run-1"))
        self.assertEqual(self.rows(), [("s1", "tu-1", None)])

        self.append(path, turn("p2", "tu-1", TEXT_U))
        self.assertEqual(self.parsed("run-1"), PARSED_U)
        rows = self.rows()
        self.assertEqual([(row[0], row[1], row[2] is not None) for row in rows], [("s1", "tu-1", True)])

    def test_missing_file_gives_null_without_a_row_then_parses_after_the_file_appears(self):
        self.assertIsNone(self.parsed("run-1"))
        self.assertEqual(self.rows(), [])
        self.write_transcript(turn("p", "tu-1", TEXT_U))
        self.assertEqual(self.parsed("run-1"), PARSED_U)
        self.assertEqual(len(self.rows()), 1)

    @unittest.skipIf(IS_ROOT, ROOT_SKIP)
    def test_unreadable_file_gives_null_without_a_row_then_parses_once_readable(self):
        path = self.write_transcript(turn("p", "tu-1", TEXT_U))
        self.addCleanup(os.chmod, path, 0o644)
        os.chmod(path, 0)
        self.assertIsNone(self.parsed("run-1"))
        self.assertEqual(self.rows(), [])
        os.chmod(path, 0o644)
        self.assertEqual(self.parsed("run-1"), PARSED_U)


class TestMetamorphicCompatibility(ApiCase):
    SESSIONS = {"s1": ("run-1", ["tu-1", "tu-2"]), "s2": ("run-2", ["tu-3"])}

    def dataset(self, name, real_ids):
        client = self.make(name)
        self.write_events([
            *full_run("run-1", "s1"),
            brief("run-1", "understanding", 1, "s1", ts(3), "tu-1"),
            brief("run-1", "decision", 2, "s1", ts(5), "tu-2"),
            brief("run-2", "approval", 1, "s2", ts(4), "tu-3"),
        ])
        for session, (_, ids) in self.SESSIONS.items():
            records = []
            for index, identifier in enumerate(ids):
                pointer = identifier if real_ids else identifier.replace("tu-", "xx-")
                text = TEXT_U if index == 0 else TEXT_D
                records += [
                    user(f"prompt {index}"),
                    {"type": "assistant", "sessionId": session, "isSidechain": False,
                     "message": {"model": "known-model",
                                 "usage": {"input_tokens": 7 + index, "output_tokens": 3},
                                 "content": [tool_use(pointer), text_block(text)]}},
                ]
            self.write_transcript(records, session)
        return client

    def test_mr1_mr2_pre_existing_values_equal_with_and_without_resolvable_pointers(self):
        without = self.dataset("data", real_ids=False)
        summary_without = without.get("/api/summary").json()
        details_without = {run: without.get(f"/api/runs/{run}").json() for run in ("run-1", "run-2")}
        shutil.rmtree(self.root / "data")
        with_pointers = self.dataset("data", real_ids=True)
        summary_with = with_pointers.get("/api/summary").json()
        details_with = {run: with_pointers.get(f"/api/runs/{run}").json() for run in ("run-1", "run-2")}

        self.assertEqual(summary_without["brief_questions"], [])
        self.assertNotEqual(summary_with["brief_questions"], [])
        self.assertEqual(set(summary_without), set(summary_with))
        for key in summary_without:
            if key != "brief_questions":
                self.assertEqual(summary_with[key], summary_without[key], key)
        for run in ("run-1", "run-2"):
            before, after = details_without[run], details_with[run]
            self.assertEqual(set(before), set(after))
            for key in before:
                if key != "briefs":
                    self.assertEqual(after[key], before[key], f"{run}.{key}")
            self.assertEqual(len(before["briefs"]), len(after["briefs"]))
            for old, new in zip(before["briefs"], after["briefs"]):
                self.assertIsNone(old["parsed"])
                self.assertIsNotNone(new["parsed"])
                self.assertEqual({k: v for k, v in new.items() if k != "parsed"},
                                 {k: v for k, v in old.items() if k != "parsed"})

    def test_mr3_database_built_by_the_base_commit_keeps_its_events_and_gains_brief_parse(self):
        if shutil.which("git") is None:
            self.skipTest("git is not available to extract the base commit analytics package")
        base = self.root / "old"
        self.telemetry, self.claude = base / "telemetry", base / "claude"
        codex = base / "codex"
        for directory in (self.telemetry, self.claude, codex):
            directory.mkdir(parents=True)
        self.db = base / "analytics.sqlite3"
        self.write_events([*full_run("run-1", "s1"),
                           brief("run-1", "understanding", 1, "s1", ts(3), "tu-1"),
                           brief("run-1", "decision", 2, "s1", ts(5), "tu-2")])
        self.write_transcript(turn("p", "tu-1", TEXT_U), "s1")

        extract_dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, extract_dir, ignore_errors=True)
        archive = subprocess.run(f"git archive {BASE_COMMIT} analytics | tar -x -C '{extract_dir}'",
                                 shell=True, cwd=REPO_ROOT, capture_output=True, text=True)
        self.assertEqual(archive.returncode, 0, archive.stdout + archive.stderr)
        built = subprocess.run(
            [sys.executable, "-c", BASE_IMPORT_SCRIPT, str(self.db), str(self.telemetry),
             str(self.prices), str(self.claude), str(codex)],
            cwd=extract_dir, capture_output=True, text=True)
        self.assertEqual(built.returncode, 0, built.stdout + built.stderr)

        def snapshot():
            connection = sqlite3.connect(self.db)
            try:
                tables = {row[0] for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'")}
                events = connection.execute("SELECT COUNT(*) FROM events").fetchone()[0]
                meta = [str(v) for row in connection.execute("SELECT * FROM schema_meta") for v in row]
            finally:
                connection.close()
            return tables, events, meta

        tables, events, meta = snapshot()
        self.assertNotIn("brief_parse", tables)
        self.assertEqual(events, 7)
        self.assertIn("2", meta)

        reopened = TestClient(create_app(self.db, self.telemetry, self.prices,
                                         {"claude": self.claude, "codex": codex}, frontend_dir=None))
        response = reopened.get("/api/runs/run-1")
        self.assertEqual(response.status_code, 200)
        briefs = response.json()["briefs"]
        self.assertEqual(briefs[0]["parsed"], PARSED_U)
        self.assertIsNone(briefs[1]["parsed"])

        tables, events, meta = snapshot()
        self.assertIn("brief_parse", tables)
        self.assertEqual(events, 7)
        self.assertIn("2", meta)
        self.assertEqual(reopened.get("/api/summary").status_code, 200)


if __name__ == "__main__":
    unittest.main()

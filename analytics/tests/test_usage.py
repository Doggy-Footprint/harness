"""Independent oracle for spec cce0155b008eaf53 v2 (workflow usage analysis).

Expected values are derived by hand from the spec; nothing here calls the
module under test to compute an expectation.
"""
import ast
import json
import tempfile
import time
from pathlib import Path

import pytest
from hypothesis import given, settings, strategies as st

from analytics import usage

SPEC_PATH = "/r/agent-docs/specs/x.md"
HANDOFF_PATH = "/r/agent-docs/handoff/h.md"
REQUEST_FIELDS = {
    "session_id", "request_index", "timestamp", "cwd", "text", "invoked",
    "invocation", "subagents", "spec_writes", "handoff_writes",
}
# v1 of spec cdafbce69a2c5906 (FR16/FR17) adds two request fields.
CONTINUATION_FIELDS = {"workflow_state", "run_id", "closes_run"}
EMPTY_CONTINUE = {"left": 0, "stayed": 0, "unlabeled": 0}


def full_confusion(**overrides):
    """Hand-written FR12a confusion shape; every count defaults to 0."""
    base = {"used": 0, "misfire": 0, "missed": 0, "correct_skip": 0, "unlabeled": 0,
            "invalid_labels": 0, "duplicate_labels": 0, "unmatched_labels": 0,
            "continue": dict(EMPTY_CONTINUE), "ignored_labels": 0}
    base.update(overrides)
    return base


# ---------------------------------------------------------------- builders

def human(text, sid="s1", ts="2026-01-01T00:00:00Z", **extra):
    record = {"type": "user", "isSidechain": False, "sessionId": sid, "timestamp": ts,
              "cwd": "/r", "origin": {"kind": "human"},
              "message": {"role": "user", "content": text}}
    record.update(extra)
    return record


def legacy(content, sid="s1", **extra):
    record = {"type": "user", "isSidechain": False, "sessionId": sid,
              "message": {"role": "user", "content": content}}
    record.update(extra)
    return record


def tool_use(name, **fields):
    return {"type": "tool_use", "name": name, "input": fields}


def assistant(*blocks, sidechain=False):
    return {"type": "assistant", "isSidechain": sidechain, "sessionId": "s1",
            "message": {"content": list(blocks)}}


def skill_call(name="workflow-approach"):
    return tool_use("Skill", skill=name)


def tool_result_record(**extra):
    record = {"type": "user", "isSidechain": False, "sessionId": "s1",
              "message": {"role": "user", "content": [
                  {"type": "tool_result", "tool_use_id": "t1", "content": "ok"}]}}
    record.update(extra)
    return record


def write_jsonl(path, records):
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [r if isinstance(r, str) else json.dumps(r, ensure_ascii=False) for r in records]
    path.write_text("".join(line + "\n" for line in lines), encoding="utf-8")
    return path


def extract(tmp_path, records, name="s1.jsonl"):
    result = usage.extract_requests(write_jsonl(tmp_path / name, records))
    assert result is not None
    return result


def telemetry(event, run, **fields):
    record = {"v": 1, "event": event, "workflow_run_id": run, "spec": "x.md"}
    record.update(fields)
    return record


def good_run(run):
    return [telemetry("workflow_start", run),
            telemetry("workflow_phase", run, phase="implement_test"),
            telemetry("workflow_phase", run, phase="verify"),
            telemetry("verifier_result", run, result="pass"),
            telemetry("workflow_end", run, status="complete")]


# --------------------------------------------------------------------- VO1

SENTINEL = "SENTINEL-AFTER"


def _non_request_rows():
    return {
        "R2_kind_task_notification": human("n", origin={"kind": "task-notification"}),
        "R2_kind_peer": human("n", origin={"kind": "peer"}),
        "R3_isMeta": human("n", isMeta=True),
        "R4_isSidechain": human("n", isSidechain=True),
        "R5_tool_result_no_origin": tool_result_record(),
        "R8_task_notification_prefix": legacy("<task-notification>done</task-notification>"),
        "R8_local_command_prefix": legacy("<local-command-stdout>x</local-command-stdout>"),
        "R8_peer_message_prefix": legacy("Another Claude session sent a message: hi"),
        "R9_assistant_type": {"type": "assistant", "sessionId": "s1",
                              "message": {"role": "user", "content": "assistant text"}},
        "R9_summary_type": {"type": "summary", "summary": "s", "message": {"content": "summary text"}},
    }


@pytest.mark.parametrize("row", sorted(_non_request_rows()))
def test_vo1_non_request_rows_are_not_requests_nor_boundaries(tmp_path, row):
    records = [human("first"), _non_request_rows()[row],
               assistant(skill_call()), human("last")]
    requests, skipped = extract(tmp_path, records)
    assert skipped == 0
    assert [r["text"] for r in requests] == ["first", "last"]
    assert [r["request_index"] for r in requests] == [0, 1]
    # not a turn boundary: the Skill call after the row still belongs to "first"
    assert requests[0]["invoked"] is True
    assert requests[1]["invoked"] is False


def test_vo1_r1_origin_human_is_request(tmp_path):
    requests, _ = extract(tmp_path, [human("a"), human("b")])
    assert [(r["request_index"], r["text"]) for r in requests] == [(0, "a"), (1, "b")]


def test_vo1_r6_legacy_str_content_is_request(tmp_path):
    requests, _ = extract(tmp_path, [legacy("plain old")])
    assert [r["text"] for r in requests] == ["plain old"]


def test_vo1_r7_legacy_text_blocks_are_request_joined_by_newline(tmp_path):
    content = [{"type": "text", "text": "line1"}, {"type": "image", "source": {}},
               {"type": "text", "text": "line2"}]
    requests, _ = extract(tmp_path, [legacy(content)])
    assert [r["text"] for r in requests] == ["line1\nline2"]


def test_vo1_r8_prefix_must_be_at_start_not_inside(tmp_path):
    requests, _ = extract(tmp_path, [legacy("see <task-notification> later")])
    assert len(requests) == 1


def test_vo1_r8_prefix_check_uses_text_of_block_list(tmp_path):
    record = legacy([{"type": "text", "text": "<local-command-caveat>x"}])
    requests, _ = extract(tmp_path, [legacy("keep"), record])
    assert [r["text"] for r in requests] == ["keep"]


def test_vo1_r5_mixed_text_and_tool_result_legacy_is_not_request(tmp_path):
    record = legacy([{"type": "text", "text": "t"},
                     {"type": "tool_result", "tool_use_id": "1", "content": "x"}])
    requests, _ = extract(tmp_path, [record])
    assert requests == []


def test_vo1_legacy_content_without_text_block_is_not_request(tmp_path):
    requests, _ = extract(tmp_path, [legacy([{"type": "image", "source": {}}])])
    assert requests == []


# --------------------------------------------------------------------- VO2

def one_turn(tmp_path, *turn_records, prompt=None):
    records = [human(prompt if prompt is not None else "go"), *turn_records]
    requests, _ = extract(tmp_path, records)
    assert len(requests) == 1
    return requests[0]


def test_vo2_slash_command_in_prompt(tmp_path):
    req = one_turn(tmp_path, prompt="<command-name>/workflow-approach</command-name> do it")
    assert (req["invoked"], req["invocation"]) == (True, "slash")


def test_vo2_slash_takes_precedence_over_skill(tmp_path):
    req = one_turn(tmp_path, assistant(skill_call()),
                   prompt="<command-name>/workflow-approach</command-name>")
    assert req["invocation"] == "slash"


def test_vo2_skill_tool_use(tmp_path):
    req = one_turn(tmp_path, assistant(skill_call()))
    assert (req["invoked"], req["invocation"]) == (True, "skill")


def test_vo2_other_skill(tmp_path):
    req = one_turn(tmp_path, assistant(skill_call("other-skill")))
    assert (req["invoked"], req["invocation"]) == (False, None)


def test_vo2_other_command_name_is_not_slash(tmp_path):
    req = one_turn(tmp_path, prompt="<command-name>/other</command-name>")
    assert (req["invoked"], req["invocation"]) == (False, None)


def test_vo2_plugin_prefixed_skill_not_counted_a6(tmp_path):
    req = one_turn(tmp_path, assistant(skill_call("x:workflow-approach")))
    assert req["invoked"] is False


def test_vo2_none(tmp_path):
    req = one_turn(tmp_path, assistant({"type": "text", "text": "hello"}))
    assert (req["invoked"], req["invocation"]) == (False, None)


def test_vo2_skill_in_next_turn_not_attributed_to_previous(tmp_path):
    requests, _ = extract(tmp_path, [human("a"), assistant({"type": "text", "text": "x"}),
                                     human("b"), assistant(skill_call())])
    assert [(r["invoked"], r["invocation"]) for r in requests] == [(False, None), (True, "skill")]


def test_vo2_sidechain_records_ignored_in_turn(tmp_path):
    side = assistant(skill_call(), tool_use("Agent", subagent_type="reviewer"),
                     tool_use("Write", file_path=SPEC_PATH),
                     tool_use("Write", file_path=HANDOFF_PATH), sidechain=True)
    req = one_turn(tmp_path, side)
    assert (req["invoked"], req["invocation"]) == (False, None)
    assert req["subagents"] == {}
    assert req["spec_writes"] == [] and req["handoff_writes"] == []


def test_vo2_last_request_has_empty_turn(tmp_path):
    requests, _ = extract(tmp_path, [human("a"), assistant(skill_call()), human("last")])
    last = requests[-1]
    assert (last["invoked"], last["invocation"]) == (False, None)
    assert (last["subagents"], last["spec_writes"], last["handoff_writes"]) == ({}, [], [])


def test_vo2_c16_file_without_human_requests(tmp_path):
    result = extract(tmp_path, [assistant(skill_call()), tool_result_record()])
    assert result == ([], 0)


# --------------------------------------------------------------------- VO3

def test_vo3_c1_full_scenario(tmp_path):
    records = [
        human("one", ts="t0"),
        assistant({"type": "text", "text": "ok"}),
        human("two", ts="t1"),
        assistant(skill_call(), tool_use("Agent", subagent_type="implementer"),
                  tool_use("Agent", description="d"),
                  tool_use("Write", file_path=SPEC_PATH)),
        tool_result_record(),
        human("three", ts="t2"),
        assistant({"type": "text", "text": "done"}),
    ]
    requests, skipped = extract(tmp_path, records)
    assert skipped == 0
    assert [r["invoked"] for r in requests] == [False, True, False]
    assert requests[1] == {
        "session_id": "s1", "request_index": 1, "timestamp": "t1", "cwd": "/r", "text": "two",
        "invoked": True, "invocation": "skill",
        "subagents": {"implementer": 1, "general-purpose": 1},
        "spec_writes": [SPEC_PATH], "handoff_writes": [],
        "workflow_state": "start", "run_id": None, "closes_run": False,  # amended by spec cdafbce69a2c5906 FR16/FR17
    }
    for other in (requests[0], requests[2]):
        assert other["subagents"] == {} and other["spec_writes"] == []


def test_vo3_agent_and_task_typed_counted_together(tmp_path):
    req = one_turn(tmp_path, assistant(
        tool_use("Agent", subagent_type="reviewer"),
        tool_use("Task", subagent_type="reviewer"),
        tool_use("Task", subagent_type="implementer")))
    assert req["subagents"] == {"reviewer": 2, "implementer": 1}


def test_vo3_untyped_variants_default_to_general_purpose(tmp_path):
    req = one_turn(tmp_path, assistant(
        tool_use("Agent"),
        tool_use("Task", subagent_type=""),
        tool_use("Agent", subagent_type=7),
        tool_use("Task", subagent_type=None)))
    assert req["subagents"] == {"general-purpose": 4}


def test_vo3_non_agent_tools_not_counted(tmp_path):
    req = one_turn(tmp_path, assistant(tool_use("Bash", command="ls"),
                                       tool_use("Read", file_path="/a")))
    assert req["subagents"] == {}


def test_vo3_spec_and_handoff_paths_by_each_writing_tool(tmp_path):
    req = one_turn(tmp_path, assistant(
        tool_use("Write", file_path="/r/agent-docs/specs/a.md"),
        tool_use("Edit", file_path="/r/agent-docs/specs/b.md"),
        tool_use("MultiEdit", file_path="/r/agent-docs/handoff/h1.md"),
        tool_use("Write", file_path="/r/agent-docs/handoff/h2.md")))
    assert req["spec_writes"] == ["/r/agent-docs/specs/a.md", "/r/agent-docs/specs/b.md"]
    assert req["handoff_writes"] == ["/r/agent-docs/handoff/h1.md", "/r/agent-docs/handoff/h2.md"]


def test_vo3_unrelated_path_and_non_writing_tool_ignored(tmp_path):
    req = one_turn(tmp_path, assistant(
        tool_use("Write", file_path="/r/src/main.py"),
        tool_use("Write", file_path="/r/agent-docs/adr/a.md"),
        tool_use("Read", file_path=SPEC_PATH),
        tool_use("Bash", file_path=SPEC_PATH)))
    assert req["spec_writes"] == [] and req["handoff_writes"] == []


def test_vo3_duplicate_paths_deduped_in_first_seen_order(tmp_path):
    req = one_turn(tmp_path, assistant(
        tool_use("Edit", file_path="/r/agent-docs/specs/b.md"),
        tool_use("Edit", file_path="/r/agent-docs/specs/a.md"),
        tool_use("Edit", file_path="/r/agent-docs/specs/b.md"),
        tool_use("Write", file_path=HANDOFF_PATH),
        tool_use("Edit", file_path=HANDOFF_PATH)))
    assert req["spec_writes"] == ["/r/agent-docs/specs/b.md", "/r/agent-docs/specs/a.md"]
    assert req["handoff_writes"] == [HANDOFF_PATH]


def test_vo3_notebook_path_used_when_no_file_path(tmp_path):
    req = one_turn(tmp_path, assistant(
        tool_use("NotebookEdit", notebook_path="/r/agent-docs/specs/n.ipynb")))
    assert req["spec_writes"] == ["/r/agent-docs/specs/n.ipynb"]


def test_vo3_c6_two_edits_same_spec_plus_handoff(tmp_path):
    req = one_turn(tmp_path, assistant(tool_use("Edit", file_path=SPEC_PATH)),
                   assistant(tool_use("Edit", file_path=SPEC_PATH)),
                   assistant(tool_use("Write", file_path=HANDOFF_PATH)))
    assert req["spec_writes"] == [SPEC_PATH]
    assert req["handoff_writes"] == [HANDOFF_PATH]


def test_vo3_fr6_prompt_text_str_and_block_list(tmp_path):
    requests, _ = extract(tmp_path, [
        human("plain"),
        human([{"type": "text", "text": "a"}, {"type": "tool_use"}, {"type": "text", "text": "b"}]),
    ])
    assert [r["text"] for r in requests] == ["plain", "a\nb"]


# --------------------------------------------------------------------- VO4

def test_vo4_depth_boundaries_only_depth_two_selected(tmp_path):
    root = tmp_path / "projects"
    write_jsonl(root / "top.jsonl", [human("depth1", sid="d1")])
    write_jsonl(root / "p" / "s.jsonl", [human("depth2", sid="d2")])
    write_jsonl(root / "p" / "s" / "a.jsonl", [human("depth3", sid="d3")])
    write_jsonl(root / "p" / "s" / "subagents" / "a.jsonl", [human("depth4", sid="d4")])
    report = usage.build_report(root, tmp_path / "no-telemetry", None)
    assert [r["text"] for r in report["requests"]] == ["depth2"]


def test_vo4_record_fields_and_session_id_falls_back_to_file_stem(tmp_path):
    root = tmp_path / "projects"
    with_id = human("hello", sid="sess-9", ts="2026-02-02T02:02:02Z")
    without = human("bare")
    del without["sessionId"], without["timestamp"], without["cwd"]
    write_jsonl(root / "p" / "a.jsonl", [with_id])
    write_jsonl(root / "p" / "stem-name.jsonl", [without])
    report = usage.build_report(root, tmp_path / "none", None)
    first, second = report["requests"]
    assert REQUEST_FIELDS <= set(first)
    assert (first["session_id"], first["request_index"], first["timestamp"], first["cwd"],
            first["text"]) == ("sess-9", 0, "2026-02-02T02:02:02Z", "/r", "hello")
    assert (second["session_id"], second["timestamp"], second["cwd"]) == ("stem-name", None, None)
    assert second["request_index"] == 0


def test_vo4_extract_requests_field_set_is_exact(tmp_path):
    requests, _ = extract(tmp_path, [human("x")])
    assert set(requests[0]) == REQUEST_FIELDS | CONTINUATION_FIELDS


def test_vo4_report_shape_without_labels(tmp_path):
    report = usage.build_report(tmp_path / "none", tmp_path / "none2", None)
    assert report == {"requests": [], "variants": [], "confusion": None,
                      "skipped_lines": 0, "skipped_files": 0, "runs": []}


def test_vo4_file_order_is_path_ascending_then_request_index(tmp_path):
    root = tmp_path / "projects"
    write_jsonl(root / "b" / "a.jsonl", [human("b-a-0")])
    write_jsonl(root / "a" / "z.jsonl", [human("a-z-0"), human("a-z-1")])
    write_jsonl(root / "a" / "b.jsonl", [human("a-b-0")])
    report = usage.build_report(root, tmp_path / "none", None)
    assert [(r["text"], r["request_index"]) for r in report["requests"]] == [
        ("a-b-0", 0), ("a-z-0", 0), ("a-z-1", 1), ("b-a-0", 0)]


def test_vo4_skipped_lines_sum_transcript_and_telemetry_and_skipped_files(tmp_path):
    root = tmp_path / "projects"
    write_jsonl(root / "p" / "a.jsonl", [human("ok"), "{broken", "[1,2]", ""])
    (root / "p").mkdir(exist_ok=True)
    (root / "p" / "bad.jsonl").write_bytes(b"\xff\xfe\x00bad")
    tdir = tmp_path / "tel"
    write_jsonl(tdir / "t.jsonl", good_run("r1") + ["not json", "42", ""])
    report = usage.build_report(root, tdir, None)
    assert report["skipped_lines"] == 2 + 2
    assert report["skipped_files"] == 1
    assert len(report["requests"]) == 1 and len(report["variants"]) == 1


# --------------------------------------------------------------------- VO5

def test_vo5_same_variant_two_runs_and_other_variant(tmp_path):
    tdir = tmp_path / "tel"
    events = []
    for run in ("A", "B"):
        events += good_run(run)
    events += [telemetry("workflow_start", "C"),
               telemetry("workflow_phase", "C", phase="implement_test"),
               telemetry("workflow_phase", "C", phase="verify"),
               telemetry("verifier_result", "C", result="pass"),
               telemetry("workflow_end", "C", status="handoff")]
    write_jsonl(tdir / "t.jsonl", events)
    variants, skipped, files = usage.mine_variants(tdir)
    assert (skipped, files) == (0, 0)
    assert variants == [
        {"variant": "start > implement_test > verify > verifier:pass > end:complete",
         "count": 2, "run_ids": ["A", "B"], "compliant": 2, "noncompliant": 0,
         "incomplete": 0, "reasons": []},
        {"variant": "start > implement_test > verify > verifier:pass > end:handoff",
         "count": 1, "run_ids": ["C"], "compliant": 1, "noncompliant": 0,
         "incomplete": 0, "reasons": []},
    ]


def test_vo5_events_without_run_or_non_workflow_are_excluded(tmp_path):
    tdir = tmp_path / "tel"
    events = good_run("A") + [
        {"v": 1, "event": "subagent_start", "agent": "x"},
        {"v": 1, "event": "subagent_start", "workflow_run_id": "A"},
        {"v": 1, "event": "verification", "workflow_run_id": "A", "result": "pass"},
        {"v": 1, "event": "workflow_phase", "phase": "verify"},
        {"v": 1, "event": "workflow_phase", "workflow_run_id": "", "phase": "verify"},
        {"v": 1, "event": "workflow_phase", "workflow_run_id": None, "phase": "verify"},
        {"v": 1, "event": "workflow_phase", "workflow_run_id": 5, "phase": "verify"},
    ]
    write_jsonl(tdir / "t.jsonl", events)
    variants, _, _ = usage.mine_variants(tdir)
    assert len(variants) == 1
    assert variants[0]["count"] == 1 and variants[0]["run_ids"] == ["A"]
    assert variants[0]["variant"] == "start > implement_test > verify > verifier:pass > end:complete"


def test_vo5_noncompliant_run_with_reason(tmp_path):
    tdir = tmp_path / "tel"
    write_jsonl(tdir / "t.jsonl", [
        telemetry("workflow_start", "N"),
        telemetry("workflow_phase", "N", phase="verify"),
        telemetry("workflow_phase", "N", phase="implement_test"),
        telemetry("verifier_result", "N", result="pass"),
        telemetry("workflow_end", "N", status="complete"),
    ])
    variants, _, _ = usage.mine_variants(tdir)
    assert variants == [{
        "variant": "start > verify > implement_test > verifier:pass > end:complete",
        "count": 1, "run_ids": ["N"], "compliant": 0, "noncompliant": 1, "incomplete": 0,
        "reasons": ["implement_test_before_verify"]}]


def test_vo5_incomplete_run_without_end(tmp_path):
    tdir = tmp_path / "tel"
    write_jsonl(tdir / "t.jsonl", [
        telemetry("workflow_start", "I"),
        telemetry("workflow_phase", "I", phase="implement_test"),
    ])
    variants, _, _ = usage.mine_variants(tdir)
    assert variants == [{
        "variant": "start > implement_test", "count": 1, "run_ids": ["I"],
        "compliant": 0, "noncompliant": 0, "incomplete": 1, "reasons": []}]


def test_vo5_tie_sort_by_count_desc_then_variant_ascending(tmp_path):
    tdir = tmp_path / "tel"
    events = []
    events += [telemetry("workflow_start", "D"),
               telemetry("workflow_phase", "D", phase="verify"),
               telemetry("workflow_phase", "D", phase="implement_test"),
               telemetry("verifier_result", "D", result="pass"),
               telemetry("workflow_end", "D", status="complete")]
    events += [telemetry("workflow_start", "E"),
               telemetry("workflow_phase", "E", phase="implement_test")]
    events += [telemetry("workflow_start", "C"),
               telemetry("workflow_phase", "C", phase="implement_test"),
               telemetry("workflow_phase", "C", phase="verify"),
               telemetry("verifier_result", "C", result="pass"),
               telemetry("workflow_end", "C", status="handoff")]
    events += good_run("A") + good_run("B")
    write_jsonl(tdir / "t.jsonl", events)
    variants, _, _ = usage.mine_variants(tdir)
    assert [(v["variant"], v["count"]) for v in variants] == [
        ("start > implement_test > verify > verifier:pass > end:complete", 2),
        ("start > implement_test", 1),
        ("start > implement_test > verify > verifier:pass > end:handoff", 1),
        ("start > verify > implement_test > verifier:pass > end:complete", 1),
    ]


def test_vo5_files_by_name_lines_in_order_run_ids_and_reasons_sorted(tmp_path):
    tdir = tmp_path / "tel"
    # Run ids appear in descending order and one run is split across two files.
    write_jsonl(tdir / "b.jsonl", [
        telemetry("verifier_result", "r2", result="pass"),
        telemetry("workflow_end", "r2", status="complete"),
        telemetry("workflow_phase", "r1", phase="implement_test"),
        telemetry("verifier_result", "r1", result="pass"),
        telemetry("workflow_end", "r1", status="complete", spec="other.md"),
    ])
    write_jsonl(tdir / "a.jsonl", [
        telemetry("workflow_start", "r2"),
        telemetry("workflow_phase", "r2", phase="verify"),
        telemetry("workflow_phase", "r2", phase="implement_test"),
        telemetry("workflow_start", "r1"),
        telemetry("workflow_phase", "r1", phase="verify"),
    ])
    variants, _, _ = usage.mine_variants(tdir)
    assert variants == [{
        "variant": "start > verify > implement_test > verifier:pass > end:complete",
        "count": 2, "run_ids": ["r1", "r2"], "compliant": 0, "noncompliant": 2,
        "incomplete": 0,
        "reasons": ["identity_mismatch", "implement_test_before_verify"]}]


def test_vo5_only_direct_jsonl_children_are_read(tmp_path):
    tdir = tmp_path / "tel"
    write_jsonl(tdir / "t.jsonl", good_run("A"))
    write_jsonl(tdir / "sub" / "t.jsonl", good_run("Z"))
    (tdir / "notes.txt").write_text(json.dumps(telemetry("workflow_start", "Y")) + "\n")
    variants, _, _ = usage.mine_variants(tdir)
    assert [v["run_ids"] for v in variants] == [["A"]]


def test_vo5_verifier_result_token_uses_result_value(tmp_path):
    tdir = tmp_path / "tel"
    write_jsonl(tdir / "t.jsonl", [
        telemetry("workflow_start", "L"),
        telemetry("workflow_phase", "L", phase="implement_test"),
        telemetry("workflow_phase", "L", phase="verify"),
        telemetry("verifier_result", "L", result="limit"),
        telemetry("workflow_end", "L", status="limit"),
    ])
    variants, _, _ = usage.mine_variants(tdir)
    assert variants[0]["variant"] == (
        "start > implement_test > verify > verifier:limit > end:limit")
    assert (variants[0]["compliant"], variants[0]["noncompliant"]) == (1, 0)


# --------------------------------------------------------------------- VO6

def req(sid, idx, invoked, state=None):
    # Pre-existing tests build requests without workflow_state; FR16 implies
    # invoked requests are start and the rest none when no run is open.
    if state is None:
        state = "start" if invoked else "none"
    return {"session_id": sid, "request_index": idx, "invoked": invoked, "text": "t",
            "workflow_state": state}


def label(sid, idx, warranted):
    return {"session_id": sid, "request_index": idx, "warranted": warranted}


def labels_file(tmp_path, lines):
    return write_jsonl(tmp_path / "labels.jsonl", lines)


def test_vo6_four_cells_and_unlabeled(tmp_path):
    requests = [req("s", 0, True), req("s", 1, True), req("s", 2, False),
                req("s", 3, False), req("s", 4, True)]
    path = labels_file(tmp_path, [label("s", 0, True), label("s", 1, False),
                                  label("s", 2, True), label("s", 3, False)])
    confusion = usage.apply_labels(requests, path)
    assert confusion == full_confusion(used=1, misfire=1, missed=1, correct_skip=1, unlabeled=1)
    assert [r["warranted"] for r in requests] == [True, False, True, False, None]


def test_vo6_invalid_label_kinds_each_counted(tmp_path):
    lines = [
        '{"session_id": "s", "request_index": true, "warranted": true}',
        '{"session_id": "s", "request_index": -1, "warranted": true}',
        '{"session_id": "s", "request_index": "0", "warranted": true}',
        '{"session_id": "s", "request_index": 0, "warranted": "yes"}',
        '{"session_id": "s", "request_index": 0}',
        '{broken json',
        "",
        label("s", 1, True),
    ]
    requests = [req("s", 0, True), req("s", 1, True)]
    confusion = usage.apply_labels(requests, labels_file(tmp_path, lines))
    assert confusion["invalid_labels"] == 6
    assert confusion["used"] == 1 and confusion["unlabeled"] == 1
    assert confusion["unmatched_labels"] == 0 and confusion["duplicate_labels"] == 0
    assert [r["warranted"] for r in requests] == [None, True]


@pytest.mark.parametrize("bad", [
    {"session_id": "s", "request_index": True, "warranted": True},
    {"session_id": "s", "request_index": -1, "warranted": True},
    {"session_id": "s", "request_index": "0", "warranted": True},
    {"session_id": "s", "request_index": 0, "warranted": "yes"},
    {"session_id": "s", "request_index": 0},
], ids=["bool_index", "negative", "str_index", "str_warranted", "missing_warranted"])
def test_vo6_each_invalid_kind_individually_never_labels(tmp_path, bad):
    requests = [req("s", 0, True)]
    confusion = usage.apply_labels(requests, labels_file(tmp_path, [bad]))
    assert confusion["invalid_labels"] == 1
    assert confusion["unlabeled"] == 1 and confusion["unmatched_labels"] == 0
    assert requests[0]["warranted"] is None


def test_vo6_index_zero_is_valid_boundary(tmp_path):
    requests = [req("s", 0, False)]
    confusion = usage.apply_labels(requests, labels_file(tmp_path, [label("s", 0, False)]))
    assert confusion["correct_skip"] == 1 and confusion["invalid_labels"] == 0


def test_vo6_duplicate_last_wins_and_unmatched(tmp_path):
    requests = [req("s", 0, True)]
    path = labels_file(tmp_path, [label("s", 0, False), label("s", 0, True),
                                  label("ghost", 0, True)])
    confusion = usage.apply_labels(requests, path)
    assert confusion == full_confusion(used=1, duplicate_labels=1, unmatched_labels=1)
    assert requests[0]["warranted"] is True


def test_vo6_same_index_different_session_is_not_duplicate(tmp_path):
    requests = [req("s1", 0, True), req("s2", 0, True)]
    confusion = usage.apply_labels(requests, labels_file(
        tmp_path, [label("s1", 0, True), label("s2", 0, False)]))
    assert confusion["duplicate_labels"] == 0
    assert (confusion["used"], confusion["misfire"]) == (1, 1)


def test_vo6_label_read_failures_propagate(tmp_path):
    with pytest.raises(OSError):
        usage.apply_labels([], tmp_path / "missing.jsonl")
    bad = tmp_path / "bad.jsonl"
    bad.write_bytes(b"\xff\xfe\x00")
    with pytest.raises(UnicodeDecodeError):
        usage.apply_labels([], bad)


def test_vo6_build_report_with_labels_end_to_end(tmp_path):
    root = tmp_path / "projects"
    # The closing command keeps b and c outside the run (spec cdafbce69a2c5906
    # FR16); without it b and c would be continue requests.
    write_jsonl(root / "p" / "s1.jsonl", [
        human("a", sid="s1"),
        assistant(skill_call(), tool_use("Bash", command="python3 workflow_marker.py end")),
        human("b", sid="s1"), human("c", sid="s1")])
    labels = labels_file(tmp_path, [label("s1", 0, True), label("s1", 1, True), "oops"])
    report = usage.build_report(root, tmp_path / "none", labels)
    assert report["confusion"] == full_confusion(used=1, missed=1, unlabeled=1, invalid_labels=1)
    assert [r["warranted"] for r in report["requests"]] == [True, True, None]
    assert report["skipped_lines"] == 0


# --------------------------------------------------------------------- VO7

def cli_fixture(tmp_path):
    root = tmp_path / "projects"
    write_jsonl(root / "p" / "s1.jsonl", [human("한글 요청입니다", sid="s1"),
                                          assistant(skill_call())])
    tdir = tmp_path / "tel"
    write_jsonl(tdir / "t.jsonl", good_run("A"))
    return root, tdir


def test_vo7_cli_normal_outputs_unescaped_json(tmp_path, capsys):
    root, tdir = cli_fixture(tmp_path)
    code = usage.main(["--transcripts", str(root), "--telemetry", str(tdir)])
    out, err = capsys.readouterr()
    assert code == 0
    assert "한글 요청입니다" in out
    assert "\\u" not in out
    payload = json.loads(out)
    assert payload["requests"][0]["text"] == "한글 요청입니다"
    assert payload["requests"][0]["invocation"] == "skill"
    assert payload["variants"][0]["count"] == 1
    assert payload["confusion"] is None
    assert err == ""


def test_vo7_cli_normal_with_labels(tmp_path, capsys):
    root, tdir = cli_fixture(tmp_path)
    labels = labels_file(tmp_path, [label("s1", 0, True)])
    code = usage.main(["--transcripts", str(root), "--telemetry", str(tdir),
                       "--labels", str(labels)])
    payload = json.loads(capsys.readouterr().out)
    assert code == 0
    assert payload["confusion"]["used"] == 1


def test_vo7_cli_missing_labels_exit_2_stderr_path_stdout_empty(tmp_path, capsys):
    root, tdir = cli_fixture(tmp_path)
    missing = tmp_path / "does-not-exist-labels.jsonl"
    code = usage.main(["--transcripts", str(root), "--telemetry", str(tdir),
                       "--labels", str(missing)])
    out, err = capsys.readouterr()
    assert code == 2
    assert str(missing) in err
    assert len(err.strip().splitlines()) == 1
    assert out == ""
    assert not missing.exists()


# --------------------------------------------------------------------- VO8

def test_vo8_broken_non_dict_and_blank_lines_in_transcript(tmp_path):
    records = [human("before"), "{broken", "", "[1,2]", "42", '"str"',
               assistant(skill_call()), human("after")]
    requests, skipped = extract(tmp_path, records)
    assert skipped == 4
    assert [r["text"] for r in requests] == ["before", "after"]
    assert requests[0]["invoked"] is True


def test_vo8_broken_non_dict_and_blank_lines_in_telemetry(tmp_path):
    tdir = tmp_path / "tel"
    write_jsonl(tdir / "t.jsonl", ["{broken", ""] + good_run("A")[:2] + ["[1,2]", ""]
                + good_run("A")[2:])
    variants, skipped, files = usage.mine_variants(tdir)
    assert (skipped, files) == (2, 0)
    assert variants[0]["count"] == 1 and variants[0]["compliant"] == 1


def test_vo8_missing_roots_give_empty_results_without_exception(tmp_path):
    gone = tmp_path / "gone"
    assert usage.mine_variants(gone) == ([], 0, 0)
    report = usage.build_report(gone, gone, None)
    assert report["requests"] == [] and report["variants"] == []
    assert report["skipped_files"] == 0


def test_vo8_missing_telemetry_does_not_affect_requests(tmp_path):
    root = tmp_path / "projects"
    write_jsonl(root / "p" / "s.jsonl", [human("x")])
    report = usage.build_report(root, tmp_path / "gone", None)
    assert len(report["requests"]) == 1 and report["variants"] == []


def test_vo8_missing_transcripts_does_not_affect_variants(tmp_path):
    tdir = tmp_path / "tel"
    write_jsonl(tdir / "t.jsonl", good_run("A"))
    report = usage.build_report(tmp_path / "gone", tdir, None)
    assert report["requests"] == [] and len(report["variants"]) == 1


def test_vo8_non_utf8_transcript_returns_none_and_counts_file(tmp_path):
    bad = tmp_path / "bad.jsonl"
    bad.write_bytes(b'{"type":"user"}\n\xff\xfe\x80\n')
    assert usage.extract_requests(bad) is None
    assert usage.extract_requests(tmp_path / "absent.jsonl") is None
    root = tmp_path / "projects"
    write_jsonl(root / "p" / "good.jsonl", [human("fine")])
    (root / "p" / "bad.jsonl").write_bytes(b"\xff\xfe\x80")
    report = usage.build_report(root, tmp_path / "none", None)
    assert report["skipped_files"] == 1
    assert [r["text"] for r in report["requests"]] == ["fine"]


def test_vo8_wrong_field_types_content_int(tmp_path):
    bad = legacy(5)
    requests, skipped = extract(tmp_path, [bad, human("ok")])
    assert skipped == 0
    assert [r["text"] for r in requests] == ["ok"]
    assert requests[0]["request_index"] == 0


def test_vo8_wrong_field_types_origin_str_treated_as_absent(tmp_path):
    requests, _ = extract(tmp_path, [legacy("legacy text", origin="human"),
                                     legacy("<task-notification>x", origin="human")])
    assert [r["text"] for r in requests] == ["legacy text"]


def test_vo8_wrong_field_types_input_str_and_message_shapes(tmp_path):
    turn = [
        {"type": "assistant", "message": {"content": [
            {"type": "tool_use", "name": "Skill", "input": "workflow-approach"},
            {"type": "tool_use", "name": "Write", "input": "agent-docs/specs/x.md"},
            {"type": "tool_use", "name": "Agent", "input": "oops"},
            "not-a-block", 7, None]}},
        {"type": "assistant", "message": {"content": "just text"}},
        {"type": "assistant", "message": "str-message"},
        {"type": "assistant"},
    ]
    req = one_turn(tmp_path, *turn)
    assert req["invoked"] is False
    assert req["spec_writes"] == []
    assert req["subagents"] == {"general-purpose": 1}


def test_vo8_message_not_dict_on_legacy_user_is_not_request(tmp_path):
    requests, skipped = extract(tmp_path, [{"type": "user", "message": "x"},
                                           {"type": "user"}, human("ok")])
    assert skipped == 0
    assert [r["text"] for r in requests] == ["ok"]


def _deny_open(monkeypatch, *denied_paths):
    import builtins
    denied_set = {Path(d) for d in denied_paths}
    real_path_open = Path.open
    real_open = builtins.open

    def path_open(self, *args, **kwargs):
        if self in denied_set:
            raise PermissionError(13, "denied", str(self))
        return real_path_open(self, *args, **kwargs)

    def builtin_open(file, *args, **kwargs):
        if isinstance(file, (str, Path)) and Path(file) in denied_set:
            raise PermissionError(13, "denied", str(file))
        return real_open(file, *args, **kwargs)

    monkeypatch.setattr(Path, "open", path_open)
    monkeypatch.setattr(builtins, "open", builtin_open)


def test_vo8_c17_unopenable_telemetry_file_is_skipped_and_counted(tmp_path, monkeypatch):
    tdir = tmp_path / "tel"
    denied = write_jsonl(tdir / "a-denied.jsonl", good_run("D"))
    write_jsonl(tdir / "b-good.jsonl", good_run("A"))
    _deny_open(monkeypatch, denied)
    variants, skipped, files = usage.mine_variants(tdir)
    assert files == 1 and skipped == 0
    assert len(variants) == 1
    assert variants[0]["run_ids"] == ["A"] and variants[0]["count"] == 1


def test_vo8_c17_build_report_counts_telemetry_file_and_keeps_transcripts(tmp_path, monkeypatch):
    root = tmp_path / "projects"
    write_jsonl(root / "p" / "s.jsonl", [human("kept")])
    (root / "p").mkdir(exist_ok=True)
    (root / "p" / "bad.jsonl").write_bytes(b"\xff\xfe\x80")
    tdir = tmp_path / "tel"
    denied = write_jsonl(tdir / "a.jsonl", good_run("D"))
    write_jsonl(tdir / "b.jsonl", good_run("A"))
    _deny_open(monkeypatch, denied)
    report = usage.build_report(root, tdir, None)
    assert report["skipped_files"] == 2
    assert [r["text"] for r in report["requests"]] == ["kept"]
    assert report["variants"][0]["run_ids"] == ["A"]


def test_vo8_c17_cli_exit_0_without_labels_message(tmp_path, monkeypatch, capsys):
    root, tdir = cli_fixture(tmp_path)
    denied = write_jsonl(tdir / "a-denied.jsonl", good_run("D"))
    _deny_open(monkeypatch, denied)
    code = usage.main(["--transcripts", str(root), "--telemetry", str(tdir)])
    out, err = capsys.readouterr()
    assert code == 0
    payload = json.loads(out)
    assert payload["skipped_files"] == 1
    assert payload["variants"][0]["run_ids"] == ["A"]
    assert "label" not in err.lower()


def test_vo8_a7_truthy_flags_and_content_without_text(tmp_path):
    records = [human("a"), human("side", isSidechain=1), human("meta", isMeta="yes"),
               human(5), human("z")]
    requests, _ = extract(tmp_path, records)
    assert [r["text"] for r in requests] == ["a", "", "z"]


def test_vo8_a7_non_string_tokens_use_str_value(tmp_path):
    tdir = tmp_path / "tel"
    write_jsonl(tdir / "t.jsonl", [
        telemetry("workflow_start", "T"),
        {"event": "workflow_phase", "workflow_run_id": "T", "spec": "x.md"},
        {"event": "verifier_result", "workflow_run_id": "T", "spec": "x.md"},
        telemetry("workflow_end", "T", status=5),
    ])
    variants, skipped, files = usage.mine_variants(tdir)
    assert variants[0]["variant"] == "start > None > verifier:None > end:5"
    assert (skipped, files) == (0, 0)


def test_vo8_a7_invalid_run_id_events_not_counted_as_skipped(tmp_path):
    tdir = tmp_path / "tel"
    write_jsonl(tdir / "t.jsonl", [
        {"event": "workflow_phase", "workflow_run_id": "", "phase": "verify"},
        {"event": "workflow_phase", "phase": "verify"},
        {"event": "workflow_start", "workflow_run_id": 3}])
    assert usage.mine_variants(tdir) == ([], 0, 0)


def test_vo8_a7_depth_two_directory_named_jsonl_not_selected(tmp_path):
    root = tmp_path / "projects"
    write_jsonl(root / "p" / "real.jsonl", [human("r")])
    write_jsonl(root / "p" / "dir.jsonl" / "inner.jsonl", [human("inner")])
    report = usage.build_report(root, tmp_path / "none", None)
    assert [r["text"] for r in report["requests"]] == ["r"]
    assert report["skipped_files"] == 0


# ------------------------------------------------- correction batch 2 evidence

def bad_lines(n):
    return ["{broken"] * n


def test_f2_skipped_lines_unequal_sum_over_multiple_files(tmp_path):
    root = tmp_path / "projects"
    write_jsonl(root / "p" / "a.jsonl", [human("a")] + bad_lines(2))
    write_jsonl(root / "p" / "b.jsonl", [human("b")] + bad_lines(1))
    tdir = tmp_path / "tel"
    write_jsonl(tdir / "t.jsonl", good_run("A") + bad_lines(1))
    report = usage.build_report(root, tdir, None)
    assert report["skipped_lines"] == 4
    assert report["skipped_files"] == 0


def test_f2_skipped_lines_three_transcript_lines_two_telemetry_files(tmp_path):
    root = tmp_path / "projects"
    write_jsonl(root / "p" / "a.jsonl", [human("a")] + bad_lines(3))
    tdir = tmp_path / "tel"
    write_jsonl(tdir / "t1.jsonl", good_run("A") + bad_lines(1))
    write_jsonl(tdir / "t2.jsonl", good_run("B") + bad_lines(1))
    assert usage.build_report(root, tdir, None)["skipped_lines"] == 5
    assert usage.mine_variants(tdir)[1] == 2


def test_f2_skipped_files_two_transcripts_one_telemetry(tmp_path, monkeypatch):
    root = tmp_path / "projects"
    (root / "p").mkdir(parents=True)
    (root / "p" / "a.jsonl").write_bytes(b"\xff\xfe\x80")
    (root / "p" / "b.jsonl").write_bytes(b"\xff\xfe\x80")
    write_jsonl(root / "p" / "c.jsonl", [human("ok")])
    tdir = tmp_path / "tel"
    denied = write_jsonl(tdir / "t.jsonl", good_run("A"))
    _deny_open(monkeypatch, denied)
    report = usage.build_report(root, tdir, None)
    assert report["skipped_files"] == 3
    assert report["skipped_lines"] == 0


def test_f2_skipped_files_one_transcript_two_telemetry(tmp_path, monkeypatch):
    root = tmp_path / "projects"
    (root / "p").mkdir(parents=True)
    (root / "p" / "a.jsonl").write_bytes(b"\xff\xfe\x80")
    tdir = tmp_path / "tel"
    d1 = write_jsonl(tdir / "t1.jsonl", good_run("A"))
    d2 = write_jsonl(tdir / "t2.jsonl", good_run("B"))
    write_jsonl(tdir / "t3.jsonl", good_run("C"))
    _deny_open(monkeypatch, d1, d2)
    assert usage.build_report(root, tdir, None)["skipped_files"] == 3
    variants, skipped, files = usage.mine_variants(tdir)
    assert files == 2 and skipped == 0
    assert variants[0]["run_ids"] == ["C"]


def test_f3_cli_defaults_read_home_locations(tmp_path, monkeypatch, capsys):
    home = tmp_path / "home"
    write_jsonl(home / ".claude" / "projects" / "p" / "s.jsonl", [human("from home")])
    write_jsonl(home / ".harness" / "telemetry" / "t.jsonl", good_run("HOMERUN"))
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    code = usage.main([])
    payload = json.loads(capsys.readouterr().out)
    assert code == 0
    assert [r["text"] for r in payload["requests"]] == ["from home"]
    assert payload["variants"][0]["run_ids"] == ["HOMERUN"]


def test_f4_invalid_utf8_telemetry_line_between_valid_events(tmp_path):
    tdir = tmp_path / "tel"
    tdir.mkdir()
    lines = [json.dumps(e).encode() for e in good_run("A")]
    data = b"\n".join(lines[:2]) + b"\n\xff\xfe\n" + b"\n".join(lines[2:]) + b"\n"
    (tdir / "t.jsonl").write_bytes(data)
    variants, skipped, files = usage.mine_variants(tdir)
    assert files == 0
    assert len(variants) == 1 and variants[0]["run_ids"] == ["A"]
    assert variants[0]["compliant"] == 1


def test_f5_list_and_dict_status_do_not_crash_and_are_noncompliant(tmp_path):
    tdir = tmp_path / "tel"
    events = []
    for run, status in (("L", ["x"]), ("M", {"k": 1})):
        events += [telemetry("workflow_start", run),
                   telemetry("workflow_phase", run, phase="implement_test"),
                   telemetry("workflow_phase", run, phase="verify"),
                   telemetry("verifier_result", run, result="pass"),
                   telemetry("workflow_end", run, status=status)]
    write_jsonl(tdir / "t.jsonl", events)
    variants, skipped, files = usage.mine_variants(tdir)
    assert (skipped, files) == (0, 0)
    by_run = {tuple(v["run_ids"]): v for v in variants}
    assert set(by_run) == {("L",), ("M",)}
    for v in by_run.values():
        assert v["count"] == 1 and v["noncompliant"] == 1
        assert v["compliant"] == 0 and v["incomplete"] == 0
        assert "invalid_terminal_status" in v["reasons"]


def test_f6_non_str_session_timestamp_cwd_fall_back(tmp_path):
    records = [human("a", sid=5, ts=7, cwd=None), human("b", sid=None, ts=None)]
    records[0]["cwd"] = 9
    records[1]["cwd"] = ["x"]
    requests, _ = extract(tmp_path, records, name="stem-x.jsonl")
    for r in requests:
        assert r["session_id"] == "stem-x"
        assert r["timestamp"] is None and r["cwd"] is None


def test_f7_within_message_ordering_text_before_skill(tmp_path):
    req = one_turn(tmp_path, assistant({"type": "text", "text": "hi"}, skill_call()))
    assert req["invocation"] == "skill"


def test_f7_write_without_path_then_write_to_spec(tmp_path):
    req = one_turn(tmp_path, assistant(
        tool_use("Write", content="x"),
        tool_use("Write", file_path="/r/agent-docs/specs/a.md")))
    assert req["spec_writes"] == ["/r/agent-docs/specs/a.md"]
    assert req["handoff_writes"] == []


def test_f7_non_tool_use_block_then_typed_agent(tmp_path):
    req = one_turn(tmp_path, assistant({"type": "text", "text": "x"},
                                       tool_use("Agent", subagent_type="reviewer")))
    assert req["subagents"] == {"reviewer": 1}


def test_f8_noise_between_events_of_same_run_keeps_all_events(tmp_path):
    tdir = tmp_path / "tel"
    run = good_run("A")
    noise = [
        [""],
        ["{broken"],
        [{"v": 1, "event": "verification", "workflow_run_id": "A", "result": "pass"}],
        [{"v": 1, "event": "workflow_phase", "phase": "verify"}],
    ]
    lines = []
    for event, filler in zip(run, noise + [[]]):
        lines.append(event)
        lines.extend(filler)
    write_jsonl(tdir / "t.jsonl", lines)
    variants, skipped, files = usage.mine_variants(tdir)
    assert len(variants) == 1
    assert variants[0]["variant"] == (
        "start > implement_test > verify > verifier:pass > end:complete")
    assert variants[0]["compliant"] == 1
    assert skipped == 1 and files == 0


def test_f9_unopenable_first_file_does_not_stop_later_files(tmp_path, monkeypatch):
    tdir = tmp_path / "tel"
    denied = write_jsonl(tdir / "a.jsonl", good_run("A"))
    write_jsonl(tdir / "b.jsonl", good_run("B") + good_run("C"))
    _deny_open(monkeypatch, denied)
    variants, _, files = usage.mine_variants(tdir)
    assert files == 1
    assert variants[0]["run_ids"] == ["B", "C"]


def test_f9_directory_named_jsonl_in_telemetry_silently_skipped(tmp_path):
    tdir = tmp_path / "tel"
    write_jsonl(tdir / "t.jsonl", good_run("A"))
    (tdir / "dir.jsonl").mkdir()
    variants, skipped, files = usage.mine_variants(tdir)
    assert (skipped, files) == (0, 0)
    assert variants[0]["run_ids"] == ["A"]


def test_f10_two_incomplete_runs_same_variant(tmp_path):
    tdir = tmp_path / "tel"
    events = []
    for run in ("I1", "I2"):
        events += [telemetry("workflow_start", run),
                   telemetry("workflow_phase", run, phase="implement_test")]
    write_jsonl(tdir / "t.jsonl", events)
    variants, _, _ = usage.mine_variants(tdir)
    assert len(variants) == 1
    assert (variants[0]["count"], variants[0]["incomplete"]) == (2, 2)
    assert (variants[0]["compliant"], variants[0]["noncompliant"]) == (0, 0)


def test_f11_three_same_key_labels_two_duplicates(tmp_path):
    requests = [req("s", 0, True)]
    confusion = usage.apply_labels(requests, labels_file(
        tmp_path, [label("s", 0, False), label("s", 0, False), label("s", 0, True)]))
    assert confusion["duplicate_labels"] == 2
    assert confusion["used"] == 1 and requests[0]["warranted"] is True


def test_f12_two_per_cell_and_two_unlabeled(tmp_path):
    requests = ([req("s", i, True) for i in range(0, 2)]
                + [req("s", i, True) for i in range(2, 4)]
                + [req("s", i, False) for i in range(4, 6)]
                + [req("s", i, False) for i in range(6, 8)]
                + [req("s", i, True) for i in range(8, 10)])
    lines = ([label("s", 0, True), label("s", 1, True)]
             + [label("s", 2, False), label("s", 3, False)]
             + [label("s", 4, True), label("s", 5, True)]
             + [label("s", 6, False), label("s", 7, False)])
    confusion = usage.apply_labels(requests, labels_file(tmp_path, lines))
    assert confusion == full_confusion(used=2, misfire=2, missed=2, correct_skip=2, unlabeled=2)


def test_f13_path_string_order_dash_before_slash(tmp_path):
    root = tmp_path / "projects"
    write_jsonl(root / "p" / "s.jsonl", [human("in-p")])
    write_jsonl(root / "p-2" / "s.jsonl", [human("in-p-2")])
    report = usage.build_report(root, tmp_path / "none", None)
    assert [r["text"] for r in report["requests"]] == ["in-p-2", "in-p"]


# --------------------------------------------------------------------- VO9

def test_vo9_build_report_performance(tmp_path):
    root = tmp_path / "projects"
    records = []
    for i in range(2000):
        records.append(human(f"request {i}", ts=f"2026-01-01T00:00:{i % 60:02d}Z"))
        records.append(assistant(skill_call() if i % 7 == 0 else {"type": "text", "text": "x"},
                                 tool_use("Agent", subagent_type="reviewer"),
                                 tool_use("Edit", file_path=SPEC_PATH)))
        for _ in range(8):
            records.append(tool_result_record())
    assert len(records) == 20000
    write_jsonl(root / "p" / "big.jsonl", records)
    events = []
    for i in range(1000):
        events += good_run(f"run-{i:04d}")
    assert len(events) == 5000
    tdir = tmp_path / "tel"
    write_jsonl(tdir / "t.jsonl", events)
    started = time.perf_counter()
    report = usage.build_report(root, tdir, None)
    elapsed = time.perf_counter() - started
    assert len(report["requests"]) == 2000
    assert report["variants"][0]["count"] == 1000
    assert elapsed <= 3.0


# -------------------------------------------------------------------- VO10

_FORBIDDEN_CTRL = "\r\n\x0b\x0c\x1c\x1d\x1e\x85  "
_KEYS = ["type", "isSidechain", "isMeta", "origin", "kind", "message", "content", "role",
         "sessionId", "timestamp", "cwd", "text", "name", "input", "skill", "subagent_type",
         "file_path", "notebook_path", "event", "workflow_run_id", "phase", "result",
         "status", "spec", "tool_use_id"]
_SCALARS = st.one_of(
    st.none(), st.booleans(), st.integers(), st.floats(allow_nan=False, allow_infinity=False),
    st.text(max_size=12),
    st.sampled_from(["user", "assistant", "human", "Skill", "Agent", "Task", "Write",
                     "tool_use", "tool_result", "text", "workflow-approach",
                     "workflow_start", "workflow_phase", "verifier_result", "workflow_end",
                     "agent-docs/specs/x.md", "<task-notification>", "r1", "verify"]),
)
_JSON_VALUES = st.recursive(
    _SCALARS,
    lambda children: st.one_of(
        st.lists(children, max_size=4),
        st.dictionaries(st.one_of(st.sampled_from(_KEYS), st.text(max_size=6)), children,
                        max_size=6)),
    max_leaves=15)
_TEXT_LINE = st.text(alphabet=st.characters(blacklist_categories=("Cs",),
                                            blacklist_characters=_FORBIDDEN_CTRL),
                     max_size=40)
_LINES = st.lists(
    st.one_of(_TEXT_LINE, _JSON_VALUES.map(json.dumps),
              _JSON_VALUES.map(lambda v: json.dumps(v, ensure_ascii=False).replace(" ", ""))
              .map(lambda s: "".join(c for c in s if c not in _FORBIDDEN_CTRL))),
    max_size=12)


def _fuzz_file(directory, lines):
    path = Path(directory) / "fuzz.jsonl"
    path.write_text("".join(line + "\n" for line in lines), encoding="utf-8")
    return path, sum(1 for line in lines if line != "")


@settings(max_examples=300, derandomize=True, deadline=None, database=None)
@given(lines=_LINES)
def test_vo10_fuzz_extract_requests(lines):
    with tempfile.TemporaryDirectory() as directory:
        path, non_empty = _fuzz_file(directory, lines)
        result = usage.extract_requests(path)
    assert result is not None
    requests, skipped = result
    assert isinstance(requests, list)
    assert 0 <= skipped <= non_empty


@settings(max_examples=300, derandomize=True, deadline=None, database=None)
@given(lines=_LINES)
def test_vo10_fuzz_mine_variants(lines):
    with tempfile.TemporaryDirectory() as directory:
        _, non_empty = _fuzz_file(directory, lines)
        variants, skipped, files = usage.mine_variants(Path(directory))
    assert isinstance(variants, list)
    assert 0 <= skipped <= non_empty
    assert files == 0


# -------------------------------------------------------------------- VO11

USAGE_SOURCE = Path(__file__).resolve().parents[1] / "usage.py"
FORBIDDEN_MODULES = {"socket", "http", "urllib", "ssl", "requests", "httpx"}
WRITE_MODE_CHARS = set("wax+")


def find_violations(source):
    violations = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[0] in FORBIDDEN_MODULES:
                    violations.append(f"import {alias.name}")
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0 and node.module and node.module.split(".")[0] in FORBIDDEN_MODULES:
                violations.append(f"from {node.module}")
        elif isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Attribute) and func.attr in {"write_text", "write_bytes"}:
                violations.append(func.attr)
            is_builtin_open = isinstance(func, ast.Name) and func.id == "open"
            is_attr_open = isinstance(func, ast.Attribute) and func.attr == "open"
            if is_builtin_open or is_attr_open:
                mode_index = 1 if is_builtin_open else 0
                mode = None
                if len(node.args) > mode_index:
                    mode = node.args[mode_index]
                for keyword in node.keywords:
                    if keyword.arg == "mode":
                        mode = keyword.value
                if mode is None:
                    continue
                if not (isinstance(mode, ast.Constant) and isinstance(mode.value, str)):
                    violations.append("open with non-constant mode")
                elif WRITE_MODE_CHARS & set(mode.value):
                    violations.append(f"open mode {mode.value}")
    return violations


@pytest.mark.parametrize("snippet", [
    "import socket",
    "import http.client",
    "import urllib.request",
    "import ssl",
    "import requests",
    "import httpx",
    "from urllib.request import urlopen",
    "from http import client",
    "from socket import socket",
    "open('f', 'w')",
    "open('f', 'a')",
    "open('f', 'x')",
    "open('f', 'r+')",
    "open('f', mode='wb')",
    "p.open('w')",
    "p.write_text('x')",
    "p.write_bytes(b'x')",
])
def test_vo11_checker_detects_each_forbidden_construct(snippet):
    assert find_violations(snippet)


@pytest.mark.parametrize("snippet", [
    "import json\nfrom pathlib import Path\nfrom analytics import compliance",
    "open('f')",
    "open('f', 'r')",
    "open('f', encoding='utf-8')",
    "p.open(encoding='utf-8')",
    "p.read_text(encoding='utf-8')",
])
def test_vo11_checker_accepts_read_only_constructs(snippet):
    assert find_violations(snippet) == []


def test_vo11_usage_source_has_no_network_import_or_file_write():
    assert find_violations(USAGE_SOURCE.read_text(encoding="utf-8")) == []


# ===========================================================================
# Spec cdafbce69a2c5906 v1 (workflow continuation). Expected values are
# hand-derived from FR15-FR19, FR11a, FR12a and Cases C20-C32.
# ===========================================================================

END_CMD = "python3 .harness/hooks/workflow_marker.py end"
ARCHIVE_CMD = "python3 spec_lifecycle.py archive --spec X --status complete"


def bash(command):
    return tool_use("Bash", command=command)


def convo(*turns, sid="s1"):
    """turns: (prompt, [assistant blocks]) -> human record + one assistant record."""
    records = []
    for prompt, blocks in turns:
        records.append(human(prompt, sid=sid))
        if blocks:
            records.append(assistant(*blocks))
    return records


def states_of(requests):
    return [r["workflow_state"] for r in requests]


def run_ids_of(requests):
    return [r["run_id"] for r in requests]


def run_row(run_id, start, cont, closed, sid="s1"):
    return {"session_id": sid, "run_id": run_id, "start_request_index": start,
            "continue_turns": cont, "closed_by_command": closed}


# -------------------------------------------------------------------- VO20

def test_vo20_c20_full_flow_none_start_continue_continue_close_none(tmp_path):
    requests, _ = extract(tmp_path, convo(
        ("plain", []),
        ("go", [skill_call()]),
        ("understood: yes", []),
        ("approved", [bash(END_CMD + " --run-id abc")]),
        ("after", [])))
    assert states_of(requests) == ["none", "start", "continue", "continue", "none"]
    assert run_ids_of(requests) == [None, "abc", "abc", "abc", None]
    assert usage.extract_runs(requests) == [run_row("abc", 1, 2, True)]


def test_vo20_none_to_none(tmp_path):
    requests, _ = extract(tmp_path, convo(("a", []), ("b", [assistant_text()])))
    assert states_of(requests) == ["none", "none"]
    assert run_ids_of(requests) == [None, None]
    assert usage.extract_runs(requests) == []


def assistant_text():
    return {"type": "text", "text": "hello"}


def test_vo20_slash_invocation_is_start_too(tmp_path):
    requests, _ = extract(tmp_path, convo(
        ("<command-name>/workflow-approach</command-name> do", []), ("reply", [])))
    assert states_of(requests) == ["start", "continue"]


def test_vo20_c21_file_end_leaves_run_open_without_command(tmp_path):
    requests, _ = extract(tmp_path, convo(
        ("go", [skill_call()]), ("a", []), ("b", [])))
    assert states_of(requests) == ["start", "continue", "continue"]
    assert usage.extract_runs(requests) == [run_row(None, 0, 2, False)]


def test_vo20_c22_reinvocation_while_open_restarts_without_command(tmp_path):
    requests, _ = extract(tmp_path, convo(
        ("go", [skill_call(), bash("python3 workflow_marker.py start --run-id r1")]),
        ("answer", []),
        ("again", [skill_call(), bash("python3 workflow_marker.py start --run-id r2")]),
        ("answer2", [])))
    assert states_of(requests) == ["start", "continue", "start", "continue"]
    assert run_ids_of(requests) == ["r1", "r1", "r2", "r2"]
    assert usage.extract_runs(requests) == [run_row("r1", 0, 1, False),
                                            run_row("r2", 2, 1, False)]


def test_vo20_slash_reinvocation_while_open(tmp_path):
    requests, _ = extract(tmp_path, convo(
        ("go", [skill_call()]),
        ("<command-name>/workflow-approach</command-name>", [])))
    assert states_of(requests) == ["start", "start"]


def test_vo20_c23_close_in_start_turn_next_request_is_none(tmp_path):
    requests, _ = extract(tmp_path, convo(
        ("go", [skill_call(), bash(END_CMD + " --run-id q")]),
        ("after", [])))
    assert states_of(requests) == ["start", "none"]
    assert run_ids_of(requests) == ["q", None]
    assert usage.extract_runs(requests) == [run_row("q", 0, 0, True)]


def test_vo20_after_close_new_invocation_starts_fresh_run(tmp_path):
    requests, _ = extract(tmp_path, convo(
        ("go", [skill_call(), bash(END_CMD + " --run-id r1")]),
        ("plain", []),
        ("again", [skill_call(), bash("python3 workflow_marker.py start --run-id r2")]),
        ("answer", [])))
    assert states_of(requests) == ["start", "none", "start", "continue"]
    assert run_ids_of(requests) == ["r1", None, "r2", "r2"]
    assert usage.extract_runs(requests) == [run_row("r1", 0, 0, True),
                                            run_row("r2", 2, 1, False)]


def test_vo20_c26_run_does_not_continue_across_files(tmp_path):
    root = tmp_path / "projects"
    write_jsonl(root / "p" / "a.jsonl", convo(
        ("go", [skill_call(), bash("python3 workflow_marker.py start --run-id ra")]),
        ("answer", []), sid="a1"))
    write_jsonl(root / "p" / "b.jsonl", convo(
        ("first", []), ("go", [skill_call()]), ("answer", []), sid="b1"))
    report = usage.build_report(root, tmp_path / "none", None)
    assert states_of(report["requests"]) == ["start", "continue", "none", "start", "continue"]
    assert run_ids_of(report["requests"]) == ["ra", "ra", None, None, None]
    assert report["runs"] == [run_row("ra", 0, 1, False, sid="a1"),
                              run_row(None, 1, 1, False, sid="b1")]


# -------------------------------------------------------------------- VO21

def _single_run_expectations(closed, run_id):
    states = ["start", "continue", "none" if closed else "continue"]
    ids = [run_id, run_id, None if closed else run_id]
    return states, ids, (1 if closed else 2)


RUNID_CASES = {
    "sep_workflow_marker": ([bash("python3 workflow_marker.py start --run-id x")], "x", False),
    "eq_spec_lifecycle": ([bash("python3 spec_lifecycle.py start --run-id=x")], "x", False),
    "extra_args_and_path": ([bash("python3 /r/.harness/workflow_marker.py phase verify "
                                  "--run-id wr-1 --other 2")], "wr-1", False),
    "non_target_command": ([bash("echo --run-id y")], None, False),
    "no_value_at_end": ([bash("python3 workflow_marker.py start --run-id")], None, False),
    "no_value_after_eq": ([bash("python3 workflow_marker.py start --run-id=")], None, False),
    "no_value_then_later_command_found": (
        [bash("python3 workflow_marker.py start --run-id"),
         bash("python3 spec_lifecycle.py x --run-id z")], "z", False),
    "first_target_occurrence_wins": (
        [bash("python3 workflow_marker.py a --run-id one"),
         bash("python3 spec_lifecycle.py b --run-id two")], "one", False),
    "non_target_before_target_ignored": (
        [bash("tool.py --run-id bad"), bash("python3 workflow_marker.py s --run-id good")],
        "good", False),
    "archive_closes_without_run_id": ([bash(ARCHIVE_CMD)], None, True),
    "end_closes_without_run_id": ([bash(END_CMD)], None, True),
    "end_closes_with_run_id": ([bash(END_CMD + " --run-id e1")], "e1", True),
    "other_marker_subcommand_does_not_close": ([bash("python3 workflow_marker.py status")],
                                               None, False),
    "other_lifecycle_subcommand_does_not_close": (
        [bash("python3 spec_lifecycle.py start --spec X")], None, False),
    "non_str_command_list": (
        [tool_use("Bash", command=["python3 workflow_marker.py end --run-id q"])], None, False),
    "non_str_command_int": ([tool_use("Bash", command=5)], None, False),
    "non_str_command_none": ([tool_use("Bash", command=None)], None, False),
    "non_str_then_valid_command_still_found": (
        [tool_use("Bash", command=["x"]), bash(END_CMD + " --run-id ok")], "ok", True),
    "input_is_str": ([{"type": "tool_use", "name": "Bash",
                       "input": "python3 workflow_marker.py end --run-id q"}], None, False),
    "input_is_list": ([{"type": "tool_use", "name": "Bash",
                        "input": ["workflow_marker.py end --run-id q"]}], None, False),
    "non_bash_tool_write": ([tool_use("Write", command=END_CMD + " --run-id q")], None, False),
    "non_bash_tool_agent": ([tool_use("Agent", command=END_CMD + " --run-id q")], None, False),
    "text_block_not_a_command": (
        [{"type": "text", "text": END_CMD + " --run-id q"}], None, False),
    # correction batch 1, F1: quotes adjacent to the value
    "quote_inside_eq_value": ([bash('python3 workflow_marker.py s --run-id=abc"def')],
                              "abc", False),
    "trailing_quote_after_sep_value": ([bash('python3 workflow_marker.py s --run-id abc"')],
                                       "abc", False),
    # correction batch 1, F2: partial matches of the closing substrings
    "partial_echo_end": ([bash("echo end")], None, False),
    "partial_git_archive": ([bash("git archive HEAD")], None, False),
    "partial_marker_archive": ([bash("python3 workflow_marker.py archive --run-id r")],
                               "r", False),
    "partial_lifecycle_end": ([bash("python3 spec_lifecycle.py end --run-id r")], "r", False),
    "partial_noncontiguous_phase_end": ([bash("python3 workflow_marker.py phase --phase end")],
                                        None, False),
}


@pytest.mark.parametrize("case", sorted(RUNID_CASES))
def test_vo21_run_id_and_close_classification(tmp_path, case):
    blocks, run_id, closed = RUNID_CASES[case]
    requests, _ = extract(tmp_path, convo(
        ("go", [skill_call()]), ("middle", blocks), ("last", [])))
    states, ids, conts = _single_run_expectations(closed, run_id)
    assert states_of(requests) == states
    assert run_ids_of(requests) == ids
    assert [r["closes_run"] for r in requests] == [False, closed, False]
    assert usage.extract_runs(requests) == [run_row(run_id, 0, conts, closed)]


def test_vo21_c24_archive_closes_and_run_id_from_earlier_start_command(tmp_path):
    requests, _ = extract(tmp_path, convo(
        ("go", [skill_call(), bash("python3 spec_lifecycle.py start --run-id=r1")]),
        ("done", [bash(ARCHIVE_CMD)]),
        ("after", [])))
    assert states_of(requests) == ["start", "continue", "none"]
    assert run_ids_of(requests) == ["r1", "r1", None]
    assert usage.extract_runs(requests) == [run_row("r1", 0, 1, True)]


def test_vo21_run_id_found_in_later_turn_applies_to_start_request(tmp_path):
    requests, _ = extract(tmp_path, convo(
        ("go", [skill_call()]),
        ("c1", [bash("python3 workflow_marker.py x --run-id first")]),
        ("c2", [bash("python3 workflow_marker.py x --run-id second")])))
    assert run_ids_of(requests) == ["first", "first", "first"]


def test_vo21_command_in_none_request_neither_closes_nor_leaks_run_id(tmp_path):
    requests, _ = extract(tmp_path, convo(
        ("plain", [bash(END_CMD + " --run-id stray")]),
        ("go", [skill_call()]),
        ("answer", [])))
    assert states_of(requests) == ["none", "start", "continue"]
    assert run_ids_of(requests) == [None, None, None]
    assert usage.extract_runs(requests) == [run_row(None, 1, 1, False)]


def test_vo21_sidechain_commands_are_ignored(tmp_path):
    side = assistant(bash(END_CMD + " --run-id side"), sidechain=True)
    requests, _ = extract(tmp_path, [human("go"), assistant(skill_call()), side,
                                     human("answer")])
    assert states_of(requests) == ["start", "continue"]
    assert run_ids_of(requests) == [None, None]


# -------------------------------------------------------------------- VO22

def test_vo22_extract_runs_empty_list(tmp_path):
    assert usage.extract_runs([]) == []


def test_vo22_closed_unclosed_and_split_runs_in_request_order(tmp_path):
    requests, _ = extract(tmp_path, convo(
        ("p0", []),
        ("s1", [skill_call(), bash("python3 workflow_marker.py start --run-id r1")]),
        ("c1", []),
        ("s2", [skill_call(), bash("python3 workflow_marker.py start --run-id r2")]),
        ("c2", []),
        ("c3", [bash(END_CMD + " --run-id r2")]),
        ("p1", []),
        ("s3", [skill_call()]),
        ("c4", [])))
    assert states_of(requests) == ["none", "start", "continue", "start", "continue",
                                   "continue", "none", "start", "continue"]
    assert usage.extract_runs(requests) == [
        run_row("r1", 1, 1, False),
        run_row("r2", 3, 2, True),
        run_row(None, 7, 1, False)]


def test_vo22_run_record_has_exactly_the_declared_keys(tmp_path):
    requests, _ = extract(tmp_path, convo(("go", [skill_call()])))
    (row,) = usage.extract_runs(requests)
    assert set(row) == {"session_id", "run_id", "start_request_index", "continue_turns",
                        "closed_by_command"}
    assert row["closed_by_command"] is False


def test_vo22_build_report_runs_follow_file_order_then_run_order(tmp_path):
    root = tmp_path / "projects"
    write_jsonl(root / "p" / "b.jsonl", convo(
        ("go", [skill_call(), bash(END_CMD + " --run-id rb")]), sid="sb"))
    write_jsonl(root / "p" / "a.jsonl", convo(
        ("go", [skill_call(), bash("python3 workflow_marker.py x --run-id ra1")]),
        ("again", [skill_call(), bash("python3 workflow_marker.py x --run-id ra2")]),
        ("answer", []), sid="sa"))
    write_jsonl(root / "p" / "c.jsonl", convo(("plain", []), sid="sc"))
    report = usage.build_report(root, tmp_path / "none", None)
    assert report["runs"] == [run_row("ra1", 0, 0, False, sid="sa"),
                              run_row("ra2", 1, 1, False, sid="sa"),
                              run_row("rb", 0, 0, True, sid="sb")]
    assert set(report) == {"requests", "variants", "confusion", "skipped_lines",
                           "skipped_files", "runs"}


# -------------------------------------------------------------------- VO23

def lab(sid, idx, **fields):
    return {"session_id": sid, "request_index": idx, **fields}


_ABSENT = object()
# (warranted, left_workflow, valid); "yes"/1 are the non-bool representatives.
LABEL_TABLE = {
    "w_absent_l_absent": (_ABSENT, _ABSENT, False),
    "w_absent_l_bool": (_ABSENT, True, True),
    "w_absent_l_nonbool": (_ABSENT, 1, False),
    "w_bool_l_absent": (False, _ABSENT, True),
    "w_bool_l_bool": (True, False, True),
    "w_bool_l_nonbool": (True, 1, False),
    "w_nonbool_l_absent": ("yes", _ABSENT, False),
    "w_nonbool_l_bool": ("yes", True, False),
    "w_nonbool_l_nonbool": ("yes", 1, False),
    # correction batch 1, F3: null and 0/1 are not bool
    "w_null_l_true": (None, True, False),
    "w_true_l_null": (True, None, False),
    "w_zero_l_absent": (0, _ABSENT, False),
    "w_one_l_absent": (1, _ABSENT, False),
    "w_absent_l_zero": (_ABSENT, 0, False),
}


@pytest.mark.parametrize("cell", sorted(LABEL_TABLE))
def test_vo23_label_validity_decision_table(tmp_path, cell):
    warranted, left, valid = LABEL_TABLE[cell]
    fields = {}
    if warranted is not _ABSENT:
        fields["warranted"] = warranted
    if left is not _ABSENT:
        fields["left_workflow"] = left
    requests = [req("s", 0, True)]
    confusion = usage.apply_labels(requests, labels_file(tmp_path, [lab("s", 0, **fields)]))
    assert confusion["unmatched_labels"] == 0 and confusion["duplicate_labels"] == 0
    if valid:
        assert confusion["invalid_labels"] == 0
        assert requests[0]["warranted"] == (None if warranted is _ABSENT else warranted)
        assert requests[0]["left_workflow"] == (None if left is _ABSENT else left)
        if warranted is not _ABSENT:
            assert requests[0]["warranted"] is warranted
        if left is not _ABSENT:
            assert requests[0]["left_workflow"] is left
    else:
        assert confusion["invalid_labels"] == 1
        assert requests[0]["warranted"] is None and requests[0]["left_workflow"] is None
        assert confusion["unlabeled"] == 1


def test_vo23_c29_invalid_kinds_counted_together_valid_ones_survive(tmp_path):
    lines = [lab("s", 0), lab("s", 0, left_workflow="yes"),
             lab("s", 0, warranted=True, left_workflow=1), lab("s", 1, left_workflow=True)]
    requests = [req("s", 0, True), req("s", 1, False, state="continue")]
    confusion = usage.apply_labels(requests, labels_file(tmp_path, lines))
    assert confusion["invalid_labels"] == 3
    assert confusion["continue"] == {"left": 1, "stayed": 0, "unlabeled": 0}
    assert confusion["unlabeled"] == 1


def test_vo23_c31_duplicate_replaces_whole_earlier_line(tmp_path):
    requests = [req("s", 0, False, state="continue")]
    confusion = usage.apply_labels(requests, labels_file(
        tmp_path, [lab("s", 0, warranted=True), lab("s", 0, left_workflow=True)]))
    assert requests[0]["warranted"] is None
    assert requests[0]["left_workflow"] is True
    assert confusion["duplicate_labels"] == 1
    assert confusion["continue"] == {"left": 1, "stayed": 0, "unlabeled": 0}
    assert confusion["ignored_labels"] == 0


def test_vo23_duplicate_replacement_other_direction(tmp_path):
    requests = [req("s", 0, True)]
    confusion = usage.apply_labels(requests, labels_file(
        tmp_path, [lab("s", 0, left_workflow=False), lab("s", 0, warranted=True)]))
    assert requests[0]["warranted"] is True
    assert requests[0]["left_workflow"] is None
    assert confusion["duplicate_labels"] == 1
    assert confusion["used"] == 1 and confusion["ignored_labels"] == 0


# -------------------------------------------------------------------- VO24

C_ZERO = dict(EMPTY_CONTINUE)
# id: (state, invoked, label fields or None, confusion overrides, warranted, left)
AGG_TABLE = {
    "start_w_only": ("start", True, {"warranted": True}, dict(used=1), True, None),
    "start_left_only": ("start", True, {"left_workflow": True},
                        dict(unlabeled=1, ignored_labels=1), None, True),
    "start_both": ("start", True, {"warranted": False, "left_workflow": True},
                   dict(misfire=1), False, True),
    "start_no_label": ("start", True, None, dict(unlabeled=1), None, None),
    "none_w_only": ("none", False, {"warranted": True}, dict(missed=1), True, None),
    "none_left_only": ("none", False, {"left_workflow": False},
                       dict(unlabeled=1, ignored_labels=1), None, False),
    "none_both": ("none", False, {"warranted": False, "left_workflow": False},
                  dict(correct_skip=1), False, False),
    "none_no_label": ("none", False, None, dict(unlabeled=1), None, None),
    "continue_w_only": ("continue", False, {"warranted": True},
                        dict(ignored_labels=1, **{"continue": {"left": 0, "stayed": 0,
                                                               "unlabeled": 1}}), True, None),
    "continue_left_only": ("continue", False, {"left_workflow": True},
                           {"continue": {"left": 1, "stayed": 0, "unlabeled": 0}}, None, True),
    "continue_both": ("continue", False, {"warranted": True, "left_workflow": False},
                      {"continue": {"left": 0, "stayed": 1, "unlabeled": 0}}, True, False),
    "continue_no_label": ("continue", False, None,
                          {"continue": {"left": 0, "stayed": 0, "unlabeled": 1}}, None, None),
}


@pytest.mark.parametrize("cell", sorted(AGG_TABLE))
def test_vo24_state_by_label_decision_table(tmp_path, cell):
    state, invoked, fields, overrides, warranted, left = AGG_TABLE[cell]
    requests = [req("s", 0, invoked, state=state)]
    lines = [] if fields is None else [lab("s", 0, **fields)]
    confusion = usage.apply_labels(requests, labels_file(tmp_path, lines))
    assert confusion == full_confusion(**overrides)
    assert requests[0]["warranted"] is warranted
    assert requests[0]["left_workflow"] is left


def test_vo24_c27_mixed_states_aggregate(tmp_path):
    requests = [req("s", 0, True), req("s", 1, False, "continue"),
                req("s", 2, False, "continue"), req("s", 3, False, "continue"),
                req("s", 4, False)]
    lines = [lab("s", 0, warranted=True), lab("s", 1, left_workflow=True),
             lab("s", 2, left_workflow=False), lab("s", 4, warranted=False)]
    confusion = usage.apply_labels(requests, labels_file(tmp_path, lines))
    assert confusion == full_confusion(
        used=1, correct_skip=1, **{"continue": {"left": 1, "stayed": 1, "unlabeled": 1}})


def test_vo24_c28_ignored_labels(tmp_path):
    requests = [req("s", 0, False, "continue"), req("s", 1, False)]
    lines = [lab("s", 0, warranted=True), lab("s", 1, left_workflow=True)]
    confusion = usage.apply_labels(requests, labels_file(tmp_path, lines))
    assert confusion == full_confusion(
        unlabeled=1, ignored_labels=2, **{"continue": {"left": 0, "stayed": 0, "unlabeled": 1}})
    assert (requests[0]["warranted"], requests[0]["left_workflow"]) == (True, None)
    assert (requests[1]["warranted"], requests[1]["left_workflow"]) == (None, True)


def test_vo24_end_to_end_with_transcript_states(tmp_path):
    root = tmp_path / "projects"
    write_jsonl(root / "p" / "s1.jsonl", convo(
        ("plain", []), ("go", [skill_call()]), ("answer", []), ("approve", [bash(END_CMD)]),
        ("after", [])))
    labels = labels_file(tmp_path, [
        lab("s1", 0, warranted=False), lab("s1", 1, warranted=True),
        lab("s1", 2, left_workflow=False), lab("s1", 3, left_workflow=True)])
    report = usage.build_report(root, tmp_path / "none", labels)
    assert states_of(report["requests"]) == ["none", "start", "continue", "continue", "none"]
    assert report["confusion"] == full_confusion(
        used=1, correct_skip=1, unlabeled=1,
        **{"continue": {"left": 1, "stayed": 1, "unlabeled": 0}})


# -------------------------------------------------------------------- VO25

def test_vo25_c30_old_format_labels_keep_old_counts(tmp_path):
    root = tmp_path / "projects"
    write_jsonl(root / "p" / "s1.jsonl", convo(
        ("a", []), ("b", [skill_call(), bash(END_CMD)]), ("c", []), ("d", [])))
    labels = labels_file(tmp_path, [label("s1", 0, True), label("s1", 1, False),
                                    label("s1", 2, False), "bad"])
    confusion = usage.build_report(root, tmp_path / "none", labels)["confusion"]
    old_keys = {k: confusion[k] for k in
                ("used", "misfire", "missed", "correct_skip", "unlabeled",
                 "invalid_labels", "duplicate_labels", "unmatched_labels")}
    assert old_keys == {"used": 0, "misfire": 1, "missed": 1, "correct_skip": 1,
                        "unlabeled": 1, "invalid_labels": 1, "duplicate_labels": 0,
                        "unmatched_labels": 0}
    assert confusion["continue"] == EMPTY_CONTINUE and confusion["ignored_labels"] == 0


# -------------------------------------------------------------------- VO26

_CMD_FRAGMENTS = ["workflow_marker.py", "spec_lifecycle.py", "end", "archive", "--run-id",
                  "--run-id=", "abc", "'q'", '"', "x y", " ", "=", "start", "\n"]
_CMD = st.one_of(
    st.text(max_size=30),
    st.lists(st.sampled_from(_CMD_FRAGMENTS), max_size=8).map(" ".join))
_BLOCK = st.one_of(
    _CMD.map(lambda c: tool_use("Bash", command=c)),
    st.just(skill_call()),
    st.builds(lambda v: tool_use("Bash", command=v), _JSON_VALUES),
    st.builds(lambda v: {"type": "tool_use", "name": "Bash", "input": v}, _JSON_VALUES),
    _CMD.map(lambda c: tool_use("Write", command=c)),
    _JSON_VALUES)
_RECORD = st.one_of(
    st.builds(lambda t: human(t), st.sampled_from(
        ["a", "<command-name>/workflow-approach</command-name>", "ok"])),
    st.builds(lambda bs, side: assistant(*bs, sidechain=side),
              st.lists(_BLOCK, max_size=4), st.booleans()))
_TRANSCRIPT_LINES = st.lists(
    st.one_of(_RECORD.map(json.dumps), _TEXT_LINE, _JSON_VALUES.map(json.dumps)), max_size=14)


@settings(max_examples=300, derandomize=True, deadline=None, database=None)
@given(lines=_TRANSCRIPT_LINES)
def test_vo26_fuzz_extract_requests_continuation(lines):
    with tempfile.TemporaryDirectory() as directory:
        path, non_empty = _fuzz_file(directory, lines)
        result = usage.extract_requests(path)
    assert result is not None
    requests, skipped = result
    assert 0 <= skipped <= non_empty
    for request in requests:
        assert request["workflow_state"] in {"start", "continue", "none"}
        if request["workflow_state"] == "none":
            assert request["run_id"] is None
        assert request["run_id"] is None or (
            isinstance(request["run_id"], str) and request["run_id"] != "")
    seen_start = False
    for request in requests:
        seen_start = seen_start or request["workflow_state"] == "start"
        assert request["workflow_state"] != "continue" or seen_start
    runs = usage.extract_runs(requests)
    assert len(runs) == states_of(requests).count("start")
    assert sum(r["continue_turns"] for r in runs) == states_of(requests).count("continue")


_FUZZ_STATES = ["start", "none", "continue", "start", "continue", "none"]
_LABEL_SCALAR = st.one_of(st.none(), st.booleans(), st.integers(-2, 8),
                          st.sampled_from(["s", "t", "yes", ""]), st.text(max_size=4))
_LABEL_DICT = st.fixed_dictionaries(
    {}, optional={"session_id": st.sampled_from(["s", "t", 5]),
                  "request_index": st.one_of(st.integers(-1, 7), st.booleans(), st.text(max_size=2)),
                  "warranted": _LABEL_SCALAR, "left_workflow": _LABEL_SCALAR})
_LABEL_LINES = st.lists(
    st.one_of(_LABEL_DICT.map(json.dumps), _TEXT_LINE, _JSON_VALUES.map(json.dumps)),
    max_size=14)


@settings(max_examples=300, derandomize=True, deadline=None, database=None)
@given(lines=_LABEL_LINES)
def test_vo26_fuzz_apply_labels(lines):
    requests = [req("s", i, state == "start", state=state)
                for i, state in enumerate(_FUZZ_STATES)]
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "labels.jsonl"
        path.write_text("".join(line + "\n" for line in lines), encoding="utf-8")
        confusion = usage.apply_labels(requests, path)
    assert (confusion["used"] + confusion["misfire"] + confusion["missed"]
            + confusion["correct_skip"] + confusion["unlabeled"]) == 4
    cont = confusion["continue"]
    assert cont["left"] + cont["stayed"] + cont["unlabeled"] == 2
    for request in requests:
        assert request["warranted"] in (True, False, None)
        assert request["left_workflow"] in (True, False, None)


# ------------------------------------------------- FR15a (spec v2) closes_run

def test_vo21_closes_run_true_only_on_closing_turn(tmp_path):
    requests, _ = extract(tmp_path, convo(
        ("go", [skill_call()]), ("mid", [bash("python3 workflow_marker.py status")]),
        ("done", [bash(ARCHIVE_CMD)]), ("after", [])))
    assert [r["closes_run"] for r in requests] == [False, False, True, False]
    assert all(type(r["closes_run"]) is bool for r in requests)


def test_vo21_closes_run_true_on_none_request_but_closes_nothing(tmp_path):
    requests, _ = extract(tmp_path, convo(
        ("plain", [bash(END_CMD)]), ("go", [skill_call()]), ("answer", [])))
    assert [r["closes_run"] for r in requests] == [True, False, False]
    assert states_of(requests) == ["none", "start", "continue"]
    assert usage.extract_runs(requests) == [run_row(None, 1, 1, False)]


def test_vo21_closes_run_on_start_request_own_turn(tmp_path):
    requests, _ = extract(tmp_path, convo(("go", [skill_call(), bash(END_CMD)])))
    assert [r["closes_run"] for r in requests] == [True]


def plain_req(idx, state, run_id=None, closes=False, sid="d"):
    return {"session_id": sid, "request_index": idx, "workflow_state": state,
            "run_id": run_id, "closes_run": closes}


def test_vo22_extract_runs_on_hand_built_plain_dicts():
    requests = [
        plain_req(0, "none", closes=True),
        plain_req(1, "start", "r1"), plain_req(2, "continue", "r1", closes=True),
        plain_req(3, "none"),
        plain_req(4, "start", None), plain_req(5, "continue"),
        plain_req(6, "start", "r3", closes=True),
        plain_req(7, "start", "r4"), plain_req(8, "continue", "r4"),
        plain_req(9, "continue", "r4", closes=True),
    ]
    assert usage.extract_runs(requests) == [
        run_row("r1", 1, 1, True, sid="d"),
        run_row(None, 4, 1, False, sid="d"),
        run_row("r3", 6, 0, True, sid="d"),
        run_row("r4", 7, 2, True, sid="d")]


def test_vo22_closed_by_command_reads_last_request_only():
    requests = [plain_req(0, "start", "r", closes=True), plain_req(1, "continue", "r")]
    assert usage.extract_runs(requests) == [run_row("r", 0, 1, False, sid="d")]


# ---------------------------------- correction batch 2: counter accumulation

def test_vo24_ignored_labels_accumulates_across_two_continue_requests(tmp_path):
    requests = [req("s", 0, False, "continue"), req("s", 1, False, "continue")]
    confusion = usage.apply_labels(requests, labels_file(
        tmp_path, [lab("s", 0, warranted=True), lab("s", 1, warranted=False)]))
    assert confusion == full_confusion(
        ignored_labels=2, **{"continue": {"left": 0, "stayed": 0, "unlabeled": 2}})


def test_vo24_ignored_labels_accumulates_none_left_only_then_continue_warranted_only(tmp_path):
    requests = [req("s", 0, False), req("s", 1, False, "continue")]
    confusion = usage.apply_labels(requests, labels_file(
        tmp_path, [lab("s", 0, left_workflow=True), lab("s", 1, warranted=True)]))
    assert confusion == full_confusion(
        unlabeled=1, ignored_labels=2,
        **{"continue": {"left": 0, "stayed": 0, "unlabeled": 1}})


def test_vo24_continue_left_accumulates(tmp_path):
    requests = [req("s", 0, False, "continue"), req("s", 1, False, "continue")]
    confusion = usage.apply_labels(requests, labels_file(
        tmp_path, [lab("s", 0, left_workflow=True), lab("s", 1, left_workflow=True)]))
    assert confusion == full_confusion(**{"continue": {"left": 2, "stayed": 0, "unlabeled": 0}})


def test_vo24_continue_stayed_accumulates(tmp_path):
    requests = [req("s", 0, False, "continue"), req("s", 1, False, "continue")]
    confusion = usage.apply_labels(requests, labels_file(
        tmp_path, [lab("s", 0, left_workflow=False), lab("s", 1, left_workflow=False)]))
    assert confusion == full_confusion(**{"continue": {"left": 0, "stayed": 2, "unlabeled": 0}})

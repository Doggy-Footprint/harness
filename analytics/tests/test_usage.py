"""Independent oracle for spec cce0155b008eaf53 v1 (workflow usage analysis).

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
    assert set(requests[0]) == REQUEST_FIELDS


def test_vo4_report_shape_without_labels(tmp_path):
    report = usage.build_report(tmp_path / "none", tmp_path / "none2", None)
    assert report == {"requests": [], "variants": [], "confusion": None,
                      "skipped_lines": 0, "skipped_files": 0}


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

def req(sid, idx, invoked):
    return {"session_id": sid, "request_index": idx, "invoked": invoked, "text": "t"}


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
    assert confusion == {"used": 1, "misfire": 1, "missed": 1, "correct_skip": 1,
                         "unlabeled": 1, "invalid_labels": 0, "duplicate_labels": 0,
                         "unmatched_labels": 0}
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
    assert confusion == {"used": 1, "misfire": 0, "missed": 0, "correct_skip": 0,
                         "unlabeled": 0, "invalid_labels": 0, "duplicate_labels": 1,
                         "unmatched_labels": 1}
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
    write_jsonl(root / "p" / "s1.jsonl", [
        human("a", sid="s1"), assistant(skill_call()),
        human("b", sid="s1"), human("c", sid="s1")])
    labels = labels_file(tmp_path, [label("s1", 0, True), label("s1", 1, True), "oops"])
    report = usage.build_report(root, tmp_path / "none", labels)
    assert report["confusion"] == {
        "used": 1, "misfire": 0, "missed": 1, "correct_skip": 0, "unlabeled": 1,
        "invalid_labels": 1, "duplicate_labels": 0, "unmatched_labels": 0}
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


def _deny_open(monkeypatch, denied):
    import builtins
    real_path_open = Path.open
    real_open = builtins.open

    def path_open(self, *args, **kwargs):
        if self == denied:
            raise PermissionError(13, "denied", str(self))
        return real_path_open(self, *args, **kwargs)

    def builtin_open(file, *args, **kwargs):
        if isinstance(file, (str, Path)) and Path(file) == denied:
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

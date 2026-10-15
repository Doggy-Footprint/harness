"""Independent oracle for spec d63550ad0d3f333d v1 (F9, C8, C9, O8).

All expected rows are hand-computed from the spec text.
"""
import pytest

from analytics.version_metrics import summarize

ROW_KEYS = {
    "harness_version", "repo", "sessions", "sessions_with_code_write",
    "median_exploration_before_code", "median_noncode_writes_before_code",
    "total_unclassified_shell_writes",
}


def ev(version, repo, expl=0, noncode=0, code=False, unclassified=0, **extra):
    event = {
        "event": "session_metrics", "harness_version": version, "repo": repo, "client": "claude",
        "session_id": "s", "exploration_before_code": expl, "noncode_writes_before_code": noncode,
        "code_writes": 1 if code else 0, "unclassified_shell_writes": unclassified,
        "tool_calls": 5, "first_code_write": code, "workflow_run_ids": [], "ended_cleanly": True,
    }
    event.update(extra)
    return event


def row(version, repo, sessions, with_code, med_expl, med_nc, unclassified):
    return {
        "harness_version": version, "repo": repo, "sessions": sessions,
        "sessions_with_code_write": with_code, "median_exploration_before_code": med_expl,
        "median_noncode_writes_before_code": med_nc, "total_unclassified_shell_writes": unclassified,
    }


def test_empty_input_gives_no_rows():
    assert summarize([]) == []


def test_c8_two_versions_in_one_repo():
    events = [
        ev("0.23.0", "r", expl=4, noncode=2, code=True, unclassified=1),
        ev("0.23.0", "r", expl=2, noncode=0, code=True),
        ev("0.23.0", "r", expl=7, noncode=9, code=False, unclassified=2),
        ev("0.24.0", "r", expl=10, noncode=3, code=True, unclassified=4),
    ]
    assert summarize(events) == [
        row("0.23.0", "r", 3, 2, 3.0, 1.0, 3),
        row("0.24.0", "r", 1, 1, 10, 3, 4),
    ]


def test_row_has_exactly_the_specified_keys():
    (result,) = summarize([ev("0.24.0", "r", expl=1, code=True)])
    assert set(result) == ROW_KEYS


def test_median_odd_count():
    events = [ev("v", "r", expl=e, noncode=n, code=True) for e, n in ((1, 9), (5, 0), (3, 4))]
    (result,) = summarize(events)
    assert result["median_exploration_before_code"] == 3
    assert result["median_noncode_writes_before_code"] == 4


def test_median_even_count_is_mean_of_middle_two():
    events = [ev("v", "r", expl=e, noncode=n, code=True) for e, n in ((4, 8), (1, 0), (3, 2), (2, 6))]
    (result,) = summarize(events)
    assert result["median_exploration_before_code"] == 2.5
    assert result["median_noncode_writes_before_code"] == 4


def test_median_two_values_boundary():
    events = [ev("v", "r", expl=2, noncode=1, code=True), ev("v", "r", expl=4, noncode=2, code=True)]
    (result,) = summarize(events)
    assert result["median_exploration_before_code"] == 3
    assert result["median_noncode_writes_before_code"] == 1.5


def test_median_single_value():
    (result,) = summarize([ev("v", "r", expl=6, noncode=0, code=True)])
    assert result["median_exploration_before_code"] == 6
    assert result["median_noncode_writes_before_code"] == 0


def test_c9_no_code_write_sessions_give_null_medians_but_count_as_sessions():
    events = [ev("v", "r", expl=3, noncode=1, code=False, unclassified=2),
              ev("v", "r", expl=5, noncode=2, code=False, unclassified=1)]
    assert summarize(events) == [row("v", "r", 2, 0, None, None, 3)]


def test_c9_sessions_without_code_write_are_excluded_from_medians():
    events = [ev("v", "r", expl=100, noncode=100, code=False),
              ev("v", "r", expl=2, noncode=1, code=True)]
    assert summarize(events) == [row("v", "r", 2, 1, 2, 1, 0)]


def test_rows_sorted_by_repo_then_version():
    events = [
        ev("0.24.0", "b", code=True), ev("0.23.0", "b", code=True),
        ev("0.24.0", "a", code=True), ev("0.23.0", "a", code=True),
    ]
    assert [(r["repo"], r["harness_version"]) for r in summarize(events)] == [
        ("a", "0.23.0"), ("a", "0.24.0"), ("b", "0.23.0"), ("b", "0.24.0"),
    ]


def test_same_version_in_different_repos_not_merged():
    events = [ev("v", "a", expl=1, code=True, unclassified=1), ev("v", "b", expl=9, code=True, unclassified=2)]
    assert summarize(events) == [row("v", "a", 1, 1, 1, 0, 1), row("v", "b", 1, 1, 9, 0, 2)]


def test_total_unclassified_sums_all_sessions_including_no_code():
    events = [ev("v", "r", code=True, unclassified=2), ev("v", "r", code=False, unclassified=5)]
    assert summarize(events)[0]["total_unclassified_shell_writes"] == 7


def test_non_session_events_ignored():
    events = [
        {"event": "spec_write", "harness_version": "v", "repo": "r", "version": 1},
        {"event": "test_command", "harness_version": "v", "repo": "r", "exit_code": 0},
        {"harness_version": "v", "repo": "r"},
        {"event": "tool_failure", "harness_version": "other", "repo": "r2"},
        ev("v", "r", expl=2, code=True),
    ]
    assert summarize(events) == [row("v", "r", 1, 1, 2, 0, 0)]


def test_only_non_session_events_give_no_rows():
    assert summarize([{"event": "spec_write", "harness_version": "v", "repo": "r"}]) == []


COUNTERS = ["exploration_before_code", "noncode_writes_before_code", "code_writes",
            "unclassified_shell_writes", "tool_calls"]


def _good():
    return ev("v", "r", expl=2, noncode=1, code=True, unclassified=1)


def _assert_only_good_counted(bad):
    assert summarize([_good(), bad]) == [row("v", "r", 1, 1, 2, 1, 1)]


@pytest.mark.parametrize("counter", COUNTERS)
def test_f9_missing_counter_skips_whole_event(counter):
    bad = ev("v", "r", expl=50, noncode=50, code=True, unclassified=50)
    del bad[counter]
    _assert_only_good_counted(bad)


@pytest.mark.parametrize("counter", COUNTERS)
@pytest.mark.parametrize("value", [True, False])
def test_f9_bool_counter_skips_whole_event(counter, value):
    bad = ev("v", "r", expl=50, noncode=50, code=True, unclassified=50)
    bad[counter] = value
    _assert_only_good_counted(bad)


@pytest.mark.parametrize("counter", COUNTERS)
@pytest.mark.parametrize("value", ["3", None, 1.5, [1], {}])
def test_f9_non_int_counter_skips_whole_event(counter, value):
    bad = ev("v", "r", expl=50, noncode=50, code=True, unclassified=50)
    bad[counter] = value
    _assert_only_good_counted(bad)


@pytest.mark.parametrize("value", [1, 0, "true", None, "false"])
def test_f9_non_bool_first_code_write_skips_whole_event(value):
    bad = ev("v", "r", expl=50, noncode=50, code=True, unclassified=50)
    bad["first_code_write"] = value
    _assert_only_good_counted(bad)


def test_f9_missing_first_code_write_skips_whole_event():
    bad = ev("v", "r", expl=50, noncode=50, code=True, unclassified=50)
    del bad["first_code_write"]
    _assert_only_good_counted(bad)


def test_f9_group_with_only_malformed_events_yields_no_row():
    assert summarize([ev("v", "r", expl="x", code=True)]) == []


def test_input_events_not_mutated():
    events = [ev("v", "r", expl=2, code=True)]
    snapshot = [dict(e) for e in events]
    summarize(events)
    assert events == snapshot

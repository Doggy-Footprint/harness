"""Per-(harness_version, repo) summary of `session_metrics` telemetry events."""
import statistics

_COUNTERS = (
    "exploration_before_code",
    "noncode_writes_before_code",
    "code_writes",
    "unclassified_shell_writes",
    "tool_calls",
)


def _valid(event: dict) -> bool:
    if not isinstance(event, dict) or event.get("event") != "session_metrics":
        return False
    if not isinstance(event.get("first_code_write"), bool):
        return False
    # bool is an int subclass; a bool counter is malformed.
    return all(
        isinstance(event.get(key), int) and not isinstance(event.get(key), bool) for key in _COUNTERS
    )


def _median(values: list[int]):
    return statistics.median(values) if values else None


def summarize(events: list[dict]) -> list[dict]:
    groups: dict[tuple, list[dict]] = {}
    for event in events:
        if _valid(event):
            groups.setdefault((event.get("harness_version"), event.get("repo")), []).append(event)
    rows = []
    for (version, repo), sessions in groups.items():
        with_code = [s for s in sessions if s["first_code_write"]]
        rows.append(
            {
                "harness_version": version,
                "repo": repo,
                "sessions": len(sessions),
                "sessions_with_code_write": len(with_code),
                "median_exploration_before_code": _median([s["exploration_before_code"] for s in with_code]),
                "median_noncode_writes_before_code": _median([s["noncode_writes_before_code"] for s in with_code]),
                "total_unclassified_shell_writes": sum(s["unclassified_shell_writes"] for s in sessions),
            }
        )
    rows.sort(key=lambda r: (str(r["repo"]), str(r["harness_version"])))
    return rows

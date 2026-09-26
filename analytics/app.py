import os
import sqlite3
import sys
import threading
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
import uvicorn

from .compliance import evaluate
from .importer import import_pending
from .pricing import calculate_cost, calculate_codex_cost, load_prices
from .store import event_dict, initialize
from .transcripts import cached_sessions, index_transcripts


def _connection(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, check_same_thread=False)
    connection.row_factory = sqlite3.Row
    initialize(connection)
    return connection


def _metrics(events):
    results = [event for event in events if event.get("event") == "verifier_result"]
    return {"verifier_rounds": len(results), "verifier_retries": sum(event.get("result") == "retry" for event in results),
            "seeds_run": sum(int(event.get("seeds_run") or 0) for event in events),
            "seeds_detected": sum(int(event.get("seeds_detected") or 0) for event in events)}


def _session_cost(session: dict, prices: dict) -> float | None:
    if session.get("client") == "codex":
        return calculate_codex_cost(session.get("model"), session.get("requests", []), prices)
    return calculate_cost(session, prices)


def _run_phases(events):
    return [{"phase": event.get("phase"), "ts": event.get("ts")} for event in events if event.get("event") == "workflow_phase"]


def _run_subagents(events, sessions):
    counts: dict[str, int] = {}
    for event in events:
        if event.get("event") == "subagent_start":
            agent_type = event.get("agent_type") or "general-purpose"
            counts[agent_type] = counts.get(agent_type, 0) + 1
    # Codex child sessions spawned (thread_spawn) from one of this run's
    # linked Codex sessions also count here (Signatures, A4); "other"-kind
    # children (e.g. guardian) are never run-attributed.
    linked_codex_ids = {session_id for client, session_id in _linked_keys(events) if client == "codex"}
    if linked_codex_ids:
        for session in sessions:
            if session.get("client") != "codex" or session.get("subagent_kind") != "thread_spawn":
                continue
            if session.get("parent_session_id") in linked_codex_ids:
                agent_type = session.get("agent_type") or "default"
                counts[agent_type] = counts.get(agent_type, 0) + 1
    return counts


def _linked_keys(events):
    return {(str(e.get("client")), str(e.get("session_id"))) for e in events if e.get("client") and e.get("session_id")}


def _linked_usage(events, sessions_by_key, prices):
    output = []
    for key in _linked_keys(events):
        session = sessions_by_key.get(key)
        if session is None:
            continue
        item = {
            "client": session["client"], "session_id": session.get("session_id"),
            "model": session.get("model"), "input_tokens": session.get("input_tokens", 0),
            "output_tokens": session.get("output_tokens", 0), "cache_read_tokens": session.get("cache_read_tokens", 0),
            "cache_write_5m_tokens": session.get("cache_write_5m_tokens", 0),
            "cache_write_1h_tokens": session.get("cache_write_1h_tokens", 0),
            "path": session.get("_path"),
        }
        item["linked_cost_usd"] = _session_cost(session, prices)
        output.append(item)
    return output


def _run_sessions(events, sessions_by_key, prices):
    output = []
    for key in _linked_keys(events):
        session = sessions_by_key.get(key)
        if session is None:
            continue
        output.append({
            "client": session["client"], "session_id": session.get("session_id"), "model": session.get("model"),
            "tools": session.get("tools", {}),
            "tokens": {
                "input_tokens": session.get("input_tokens", 0),
                "output_tokens": session.get("output_tokens", 0),
                "cache_read_tokens": session.get("cache_read_tokens", 0),
                "cache_write_tokens": session.get("cache_write_5m_tokens", 0) + session.get("cache_write_1h_tokens", 0),
            },
            "cost_usd": _session_cost(session, prices),
        })
    return output


def _workflow_entry(run_id, events, sessions, sessions_by_key, prices):
    state = evaluate(events)
    end = next((event for event in reversed(events) if event.get("event") == "workflow_end"), None)
    status = end.get("status") if end else "in_progress"
    first = events[0]
    return {
        "run_id": run_id, "spec": first.get("spec"), "spec_version": first.get("spec_version"),
        "status": status, "compliant": state["compliant"], "compliance_reasons": state["reasons"],
        "phases": _run_phases(events), **_metrics(events),
        "subagents": _run_subagents(events, sessions), "sessions": _run_sessions(events, sessions_by_key, prices),
    }


def _non_workflow_section(sessions, workflow_keys, prices):
    others = [s for s in sessions if (s.get("client"), s.get("session_id")) not in workflow_keys]

    tool_totals: dict[str, int] = {}
    subagent_totals: dict[str, int] = {}
    by_model_cost: dict[str, float | None] = {}
    by_model_known: dict[str, bool] = {}
    tokens_by_model: dict[str, dict] = {}
    unknown_models: list[str] = []

    for session in others:
        for name, count in session.get("tools", {}).items():
            tool_totals[name] = tool_totals.get(name, 0) + count
        for agent_type, count in session.get("subagents", {}).items():
            subagent_totals[agent_type] = subagent_totals.get(agent_type, 0) + count
        # Every Codex child session not attributed to a run counts here by
        # its type: other-kind (e.g. guardian) always, and thread_spawn
        # children whose parent link is missing or unlinked (F6/A4). Keying
        # off subagent_kind (not parent_session_id) matters because "other"
        # children can carry no parent link at all and must still count.
        if session.get("subagent_kind"):
            agent_type = session.get("agent_type") or "default"
            subagent_totals[agent_type] = subagent_totals.get(agent_type, 0) + 1

        model_key = session.get("model") or "unknown"
        tokens = tokens_by_model.setdefault(model_key, {"input_tokens": 0, "output_tokens": 0, "cache_read_tokens": 0, "cache_write_tokens": 0})
        tokens["input_tokens"] += session.get("input_tokens", 0)
        tokens["output_tokens"] += session.get("output_tokens", 0)
        tokens["cache_read_tokens"] += session.get("cache_read_tokens", 0)
        tokens["cache_write_tokens"] += session.get("cache_write_5m_tokens", 0) + session.get("cache_write_1h_tokens", 0)

        if model_key not in by_model_known:
            by_model_known[model_key] = True
            by_model_cost[model_key] = 0.0
        cost = _session_cost(session, prices)
        if cost is None:
            by_model_known[model_key] = False
            if model_key not in unknown_models:
                unknown_models.append(model_key)
        elif by_model_known[model_key]:
            by_model_cost[model_key] += cost

    for model_key, known in by_model_known.items():
        if not known:
            by_model_cost[model_key] = None

    total_usd = sum(value for value in by_model_cost.values() if value is not None)
    tools_top = sorted(tool_totals.items(), key=lambda item: (-item[1], item[0]))[:20]

    return {
        "sessions": len(others),
        "tools": {name: count for name, count in tools_top},
        "cost": {"by_model": by_model_cost, "tokens_by_model": tokens_by_model, "total_usd": total_usd, "unknown_models": unknown_models},
        "subagents": subagent_totals,
    }


def create_app(database_path: Path, telemetry_dir: Path, price_path: Path, transcript_dirs: dict[str, Path] | None = None, frontend_dir: Path | None = None) -> FastAPI:
    prices = load_prices(price_path)
    connection = _connection(database_path)
    roots = transcript_dirs or {}
    lock = threading.Lock()
    app = FastAPI()

    def runs():
        with lock:
            import_pending(connection, telemetry_dir)
            index_transcripts(connection, roots)
            rows = connection.execute("SELECT * FROM events ORDER BY id").fetchall()
            sessions = cached_sessions(connection)
        grouped: dict[str, list[dict]] = {}
        for row in rows:
            event = event_dict(row)
            run_id = event.get("workflow_run_id")
            if run_id is None:
                continue
            grouped.setdefault(run_id, []).append(event)
        for group in grouped.values():
            # FR3: events carrying this run_id but no spec/spec_version of
            # their own (e.g. subagent_start) are attributed to the run's
            # spec/spec_version rather than staying None.
            run_spec = next((e.get("spec") for e in group if e.get("spec") is not None), None)
            run_spec_version = next((e.get("spec_version") for e in group if e.get("spec_version") is not None), None)
            for event in group:
                if event.get("spec") is None:
                    event["spec"] = run_spec
                if event.get("spec_version") is None:
                    event["spec_version"] = run_spec_version
        sessions_by_key = {(session.get("client"), session.get("session_id")): session for session in sessions}
        return grouped, sessions_by_key, sessions

    def detail(run_id, events, sessions, sessions_by_key):
        state = evaluate(events)
        transcript_metadata = _linked_usage(events, sessions_by_key, prices)
        costs = [u["linked_cost_usd"] for u in transcript_metadata]
        total = None if any(value is None for value in costs) else sum(costs)
        first = events[0]
        end = next((event for event in reversed(events) if event.get("event") == "workflow_end"), None)
        status = end.get("status") if end else "in_progress"
        return {"run_id": run_id, "spec": first.get("spec"), "spec_version": first.get("spec_version"),
                "status": status, "compliant": state["compliant"],
                "compliance_reasons": state["reasons"], "events": events, **_metrics(events),
                "transcript_metadata": transcript_metadata, "linked_cost_usd": total,
                "subagents": _run_subagents(events, sessions), "sessions": _run_sessions(events, sessions_by_key, prices)}

    @app.get("/api/health")
    def health():
        return {"status": "ok"}

    @app.get("/api/summary")
    def summary():
        grouped, sessions_by_key, sessions = runs()
        details = [detail(key, value, sessions, sessions_by_key) for key, value in grouped.items()]
        completed = [item for item in details if item["status"] != "in_progress"]
        costs = [item["linked_cost_usd"] for item in details]
        workflow_keys = {key for events in grouped.values() for key in _linked_keys(events)}
        workflow_runs = [_workflow_entry(key, events, sessions, sessions_by_key, prices) for key, events in grouped.items()]
        return {"runs": len(details), "completed_runs": len(completed), "compliant_runs": sum(item["compliant"] is True for item in completed),
                "handoff_runs": sum(item["status"] == "handoff" for item in details),
                "verifier_rounds": sum(item["verifier_rounds"] for item in details), "verifier_retries": sum(item["verifier_retries"] for item in details),
                "seeds_run": sum(item["seeds_run"] for item in details), "seeds_detected": sum(item["seeds_detected"] for item in details),
                "linked_cost_usd": None if any(x is None for x in costs) else sum(costs),
                "run_items": [{key: item[key] for key in ("run_id", "spec", "status", "compliant")} for item in details],
                "workflow": {"runs": workflow_runs},
                "non_workflow": _non_workflow_section(sessions, workflow_keys, prices)}

    @app.get("/api/runs/{run_id}")
    def run(run_id: str):
        grouped, sessions_by_key, sessions = runs()
        if run_id not in grouped:
            raise HTTPException(status_code=404, detail="run not found")
        return detail(run_id, grouped[run_id], sessions, sessions_by_key)

    if frontend_dir is not None:
        assets = frontend_dir / "assets"
        if assets.is_dir():
            app.mount("/assets", StaticFiles(directory=assets), name="assets")
        index = frontend_dir / "index.html"
        @app.get("/{path:path}")
        def spa(path: str):
            return FileResponse(index)
    return app


def _env_path(name, default):
    return Path(os.environ.get(name, str(default))).expanduser()


def main():
    root = Path(__file__).resolve().parent
    try:
        port = int(os.environ.get("ANALYTICS_PORT", "8000"))
        if not 1 <= port <= 65535:
            raise ValueError("port must be between 1 and 65535")
        app = create_app(_env_path("ANALYTICS_DATABASE_PATH", Path.home() / ".harness/analytics.sqlite3"),
                         _env_path("ANALYTICS_TELEMETRY_DIR", Path.home() / ".harness/telemetry"),
                         _env_path("ANALYTICS_PRICE_PATH", root / "config.yaml"),
                         {"claude": _env_path("ANALYTICS_CLAUDE_TRANSCRIPT_DIR", Path.home() / ".claude/projects"), "codex": _env_path("ANALYTICS_CODEX_TRANSCRIPT_DIR", Path.home() / ".codex/sessions")},
                         _env_path("ANALYTICS_FRONTEND_DIR", root / "frontend/dist"))
        frontend = _env_path("ANALYTICS_FRONTEND_DIR", root / "frontend/dist")
        if not (frontend / "index.html").is_file():
            raise ValueError("frontend build is unavailable")
    except Exception as error:
        print(f"analytics startup error: {error}", file=sys.stderr)
        return 1
    uvicorn.run(app, host=os.environ.get("ANALYTICS_HOST", "127.0.0.1"), port=port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

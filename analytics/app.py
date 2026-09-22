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
from .importer import import_pending, transcript_session_id, transcript_usage
from .pricing import calculate_cost, load_prices
from .store import event_dict, initialize


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


def _usage(events, roots, prices):
    linked = {(str(e.get("client")), str(e.get("session_id"))) for e in events if e.get("client") and e.get("session_id")}
    output = []
    for client, session in linked:
        root = roots.get(client)
        if root is None or not root.is_dir():
            continue
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            item = transcript_usage(path, client)
            if not item:
                continue
            if transcript_session_id(path, client) != session:
                continue
            item.update({"client": client, "session_id": session, "path": str(path)})
            item["linked_cost_usd"] = calculate_cost(item, prices)
            output.append(item)
    return output


def create_app(database_path: Path, telemetry_dir: Path, price_path: Path, transcript_dirs: dict[str, Path] | None = None, frontend_dir: Path | None = None) -> FastAPI:
    prices = load_prices(price_path)
    connection = _connection(database_path)
    roots = transcript_dirs or {}
    lock = threading.Lock()
    app = FastAPI()

    def runs():
        with lock:
            import_pending(connection, telemetry_dir)
            rows = connection.execute("SELECT * FROM events ORDER BY id").fetchall()
        grouped = {}
        for row in rows:
            event = event_dict(row)
            grouped.setdefault(event["workflow_run_id"], []).append(event)
        return grouped

    def detail(run_id, events):
        state = evaluate(events)
        transcript_metadata = _usage(events, roots, prices)
        costs = [u["linked_cost_usd"] for u in transcript_metadata]
        total = None if any(value is None for value in costs) else sum(costs)
        first = events[0]
        end = next((event for event in reversed(events) if event.get("event") == "workflow_end"), None)
        status = end.get("status") if end else "in_progress"
        return {"run_id": run_id, "spec": first.get("spec"), "spec_version": first.get("spec_version"),
                "status": status, "compliant": state["compliant"],
                "compliance_reasons": state["reasons"], "events": events, **_metrics(events),
                "transcript_metadata": transcript_metadata, "linked_cost_usd": total}

    @app.get("/api/health")
    def health():
        return {"status": "ok"}

    @app.get("/api/summary")
    def summary():
        details = [detail(key, value) for key, value in runs().items()]
        completed = [item for item in details if item["status"] != "in_progress"]
        costs = [item["linked_cost_usd"] for item in details]
        return {"runs": len(details), "completed_runs": len(completed), "compliant_runs": sum(item["compliant"] is True for item in completed),
                "handoff_runs": sum(item["status"] == "handoff" for item in details),
                "verifier_rounds": sum(item["verifier_rounds"] for item in details), "verifier_retries": sum(item["verifier_retries"] for item in details),
                "seeds_run": sum(item["seeds_run"] for item in details), "seeds_detected": sum(item["seeds_detected"] for item in details),
                "linked_cost_usd": None if any(x is None for x in costs) else sum(costs),
                "run_items": [{key: item[key] for key in ("run_id", "spec", "status", "compliant")} for item in details]}

    @app.get("/api/runs/{run_id}")
    def run(run_id: str):
        grouped = runs()
        if run_id not in grouped:
            raise HTTPException(status_code=404, detail="run not found")
        return detail(run_id, grouped[run_id])

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

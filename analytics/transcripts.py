import json
import sqlite3
from pathlib import Path

_WORKFLOW_TOOL_NAMES = {"Agent", "Task"}


def _records(path: Path) -> list[dict]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return []
    records = []
    for line in lines:
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            return []
        if isinstance(value, dict):
            records.append(value)
    return records


def transcript_session_id(path: Path, client: str | None) -> str | None:
    for item in _records(path):
        if client == "claude" and isinstance(item.get("sessionId"), str):
            return item["sessionId"]
        if client == "codex" and item.get("type") == "session_meta":
            payload = item.get("payload")
            if isinstance(payload, dict) and isinstance(payload.get("id"), str):
                return payload["id"]
    return None


def transcript_usage(path: Path, client: str | None) -> dict[str, int | str | None]:
    records = _records(path)
    if not records:
        return {}
    totals = {"model": None, "input_tokens": 0, "output_tokens": 0,
              "cache_read_tokens": 0, "cache_write_5m_tokens": 0,
              "cache_write_1h_tokens": 0}
    found = False
    if client == "claude":
        for item in records:
            message = item.get("message")
            usage = message.get("usage") if isinstance(message, dict) else None
            if not isinstance(usage, dict):
                continue
            if message.get("model"):
                totals["model"] = str(message["model"])
            totals["input_tokens"] += int(usage.get("input_tokens", 0) or 0)
            totals["output_tokens"] += int(usage.get("output_tokens", 0) or 0)
            totals["cache_read_tokens"] += int(usage.get("cache_read_input_tokens", 0) or 0)
            creation = usage.get("cache_creation")
            if isinstance(creation, dict):
                totals["cache_write_5m_tokens"] += int(creation.get("ephemeral_5m_input_tokens", 0) or 0)
                totals["cache_write_1h_tokens"] += int(creation.get("ephemeral_1h_input_tokens", 0) or 0)
            found = True
    elif client == "codex":
        latest = None
        for item in records:
            payload = item.get("payload")
            if item.get("type") == "session_meta" and isinstance(payload, dict) and payload.get("model"):
                totals["model"] = str(payload["model"])
            if item.get("type") == "event_msg" and isinstance(payload, dict):
                info = payload.get("info")
                if payload.get("type") == "token_count" and isinstance(info, dict) and isinstance(info.get("last_token_usage"), dict):
                    latest = info["last_token_usage"]
        if latest is not None:
            cached = int(latest.get("cached_input_tokens", 0) or 0)
            totals["input_tokens"] = max(0, int(latest.get("input_tokens", 0) or 0) - cached)
            totals["output_tokens"] = int(latest.get("output_tokens", 0) or 0)
            totals["cache_read_tokens"] = cached
            found = True
    return totals if found and totals["model"] else {}


def _claude_agent_type(item: dict) -> str:
    value = item.get("input")
    if isinstance(value, dict):
        subagent_type = value.get("subagent_type")
        if isinstance(subagent_type, str) and subagent_type:
            return subagent_type
    return "general-purpose"


def _parse_claude(path: Path) -> dict | None:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    session_id = None
    cwd = None
    model = None
    tokens = {"input_tokens": 0, "output_tokens": 0, "cache_read_tokens": 0,
              "cache_write_5m_tokens": 0, "cache_write_1h_tokens": 0}
    tools: dict[str, int] = {}
    subagents: dict[str, int] = {}
    seen = False
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(item, dict):
            continue
        if session_id is None and isinstance(item.get("sessionId"), str):
            session_id = item["sessionId"]
        if cwd is None and isinstance(item.get("cwd"), str):
            cwd = item["cwd"]
        if item.get("type") != "assistant":
            continue
        message = item.get("message")
        if not isinstance(message, dict):
            continue
        usage = message.get("usage")
        if isinstance(usage, dict):
            if message.get("model"):
                model = str(message["model"])
            tokens["input_tokens"] += int(usage.get("input_tokens", 0) or 0)
            tokens["output_tokens"] += int(usage.get("output_tokens", 0) or 0)
            tokens["cache_read_tokens"] += int(usage.get("cache_read_input_tokens", 0) or 0)
            creation = usage.get("cache_creation")
            if isinstance(creation, dict):
                tokens["cache_write_5m_tokens"] += int(creation.get("ephemeral_5m_input_tokens", 0) or 0)
                tokens["cache_write_1h_tokens"] += int(creation.get("ephemeral_1h_input_tokens", 0) or 0)
            seen = True
        content = message.get("content")
        if isinstance(content, list):
            for entry in content:
                if not isinstance(entry, dict) or entry.get("type") != "tool_use":
                    continue
                name = entry.get("name")
                if not isinstance(name, str):
                    continue
                tools[name] = tools.get(name, 0) + 1
                if name in _WORKFLOW_TOOL_NAMES:
                    agent_type = _claude_agent_type(entry)
                    subagents[agent_type] = subagents.get(agent_type, 0) + 1
    if session_id is None and not seen and not tools:
        return None
    parent_session_id = None
    if path.parent.name == "subagents":
        parent_session_id = path.parent.parent.name
    return {
        "session_id": session_id, "client": "claude", "cwd": cwd, "model": model,
        **tokens, "tools": tools, "subagents": subagents,
        "parent_session_id": parent_session_id, "agent_type": None,
    }


def _parse_codex(path: Path) -> dict | None:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    session_id = None
    cwd = None
    model = None
    parent_session_id = None
    agent_type = None
    subagent_kind = None
    tools: dict[str, int] = {}
    requests: list[dict] = []
    last_total = None
    seen = False
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(item, dict):
            continue
        kind = item.get("type")
        payload = item.get("payload")
        if not isinstance(payload, dict):
            continue
        if kind == "session_meta":
            seen = True
            if isinstance(payload.get("id"), str):
                session_id = payload["id"]
            elif isinstance(payload.get("session_id"), str):
                session_id = payload["session_id"]
            if isinstance(payload.get("cwd"), str):
                cwd = payload["cwd"]
            if isinstance(payload.get("model"), str):
                model = payload["model"]
            source = payload.get("source")
            subagent = source.get("subagent") if isinstance(source, dict) else None
            if isinstance(subagent, dict):
                thread_spawn = subagent.get("thread_spawn")
                if isinstance(thread_spawn, dict):
                    parent_session_id = thread_spawn.get("parent_thread_id") or payload.get("parent_thread_id")
                    role = thread_spawn.get("agent_role")
                    agent_type = role if isinstance(role, str) and role else "default"
                    subagent_kind = "thread_spawn"
                elif "other" in subagent:
                    parent_session_id = payload.get("parent_thread_id")
                    other = subagent.get("other")
                    agent_type = other if isinstance(other, str) and other else "other"
                    subagent_kind = "other"
        elif kind == "turn_context":
            if isinstance(payload.get("model"), str):
                model = payload["model"]
        elif kind == "response_item":
            if payload.get("type") in ("function_call", "custom_tool_call"):
                name = payload.get("name")
                if isinstance(name, str):
                    tools[name] = tools.get(name, 0) + 1
        elif kind == "event_msg" and payload.get("type") == "token_count":
            info = payload.get("info")
            if not isinstance(info, dict):
                continue
            total = info.get("total_token_usage")
            last = info.get("last_token_usage")
            if not isinstance(last, dict):
                continue
            if total is not None and total == last_total:
                continue
            last_total = total
            requests.append({
                "input_tokens": int(last.get("input_tokens", 0) or 0),
                "cached_input_tokens": int(last.get("cached_input_tokens", 0) or 0),
                "output_tokens": int(last.get("output_tokens", 0) or 0),
            })
    if not seen:
        return None
    tokens = {
        "input_tokens": sum(r["input_tokens"] for r in requests),
        "output_tokens": sum(r["output_tokens"] for r in requests),
        "cache_read_tokens": sum(r["cached_input_tokens"] for r in requests),
        "cache_write_5m_tokens": 0, "cache_write_1h_tokens": 0,
    }
    return {
        "session_id": session_id, "client": "codex", "cwd": cwd, "model": model,
        **tokens, "tools": tools, "subagents": {}, "requests": requests,
        "parent_session_id": parent_session_id, "agent_type": agent_type,
        "subagent_kind": subagent_kind,
    }


def parse_transcript(path: Path, client: str) -> dict | None:
    if client == "claude":
        return _parse_claude(path)
    if client == "codex":
        return _parse_codex(path)
    return None


def index_transcripts(connection: sqlite3.Connection, roots: dict[str, Path]) -> None:
    from .store import initialize
    initialize(connection)
    seen_paths = set()
    for client, root in roots.items():
        if root is None or not root.is_dir():
            continue
        for path in sorted(root.rglob("*.jsonl")):
            if not path.is_file():
                continue
            try:
                stat = path.stat()
            except OSError:
                continue
            key = str(path.resolve())
            seen_paths.add(key)
            row = connection.execute(
                "SELECT size, mtime FROM transcript_cache WHERE path=?", (key,)
            ).fetchone()
            if row and int(row[0]) == stat.st_size and float(row[1]) == stat.st_mtime:
                continue
            try:
                path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                # Unreadable/non-UTF-8 transcript: skip without caching so it
                # is retried on the next index pass. parse_transcript itself
                # returns None rather than raising (F2), so readability is
                # checked here to decide whether the cache miss is durable.
                continue
            result = parse_transcript(path, client)
            data = json.dumps(result) if result is not None else None
            connection.execute(
                "INSERT INTO transcript_cache(path,size,mtime,client,data) VALUES(?,?,?,?,?) "
                "ON CONFLICT(path) DO UPDATE SET size=excluded.size,mtime=excluded.mtime,client=excluded.client,data=excluded.data",
                (key, stat.st_size, stat.st_mtime, client, data),
            )
    connection.commit()


def cached_sessions(connection: sqlite3.Connection) -> list[dict]:
    """Read parsed transcripts from the cache and merge Claude subagent
    transcript tokens into their parent session (FR9, C8): those files are
    not listed as separate sessions.
    """
    rows = connection.execute("SELECT path, client, data FROM transcript_cache").fetchall()
    by_path: dict[str, dict] = {}
    for path, client, data in rows:
        if data is None:
            continue
        parsed = json.loads(data)
        parsed["_path"] = path
        by_path[path] = parsed

    sessions: list[dict] = []
    subagent_files: list[dict] = []
    for path, parsed in by_path.items():
        if parsed.get("client") == "claude" and Path(path).parent.name == "subagents":
            subagent_files.append(parsed)
        else:
            parsed["child_sessions"] = 0
            sessions.append(parsed)

    parent_dir_index = {
        Path(item["_path"]).stem: item for item in sessions if item.get("client") == "claude"
    }
    for child in subagent_files:
        parent_dir_name = Path(child["_path"]).parent.parent.name
        parent = parent_dir_index.get(parent_dir_name)
        if parent is None:
            continue
        for field in ("input_tokens", "output_tokens", "cache_read_tokens",
                       "cache_write_5m_tokens", "cache_write_1h_tokens"):
            parent[field] = parent.get(field, 0) + child.get(field, 0)
        parent["child_sessions"] += 1
    return sessions

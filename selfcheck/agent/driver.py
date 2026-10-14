import asyncio
import json
import os
import sys
import time
from pathlib import Path

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    HookMatcher,
    PermissionResultAllow,
    RateLimitEvent,
    ResultMessage,
    SystemMessage,
    TextBlock,
    ThinkingBlock,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
)

try:
    from . import user_sim
except ImportError:
    import user_sim

REQUIRED = (
    "run_id", "arm", "prompt", "model", "effort", "aliases", "disallowed_tools", "wall_clock_s",
    "max_user_turns", "idle_grace_s", "phrase", "out_dir", "token_path", "proxy_url", "resume",
)
TEXT_CUT = 2000
INPUT_CUT = 4000
RESULT_FIELDS = (
    "subtype", "is_error", "num_turns", "session_id", "total_cost_usd", "usage", "model_usage",
    "api_error_status", "terminal_reason", "errors",
)


class StreamEnded(RuntimeError):
    pass


def _cut(value):
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            if isinstance(v, str) and len(v) > INPUT_CUT:
                out[k] = v[:INPUT_CUT]
                out[f"{k}__len"] = len(v)
            else:
                out[k] = _cut(v)
        return out
    if isinstance(value, list):
        return [v[:INPUT_CUT] if isinstance(v, str) else _cut(v) for v in value]
    return value


def _render(content) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            str(c.get("text", "")) if isinstance(c, dict) else str(c) for c in content
        )
    return json.dumps(content, default=str)


def _block(block) -> dict:
    if isinstance(block, TextBlock):
        return {"type": "text", "text": block.text[:TEXT_CUT]}
    if isinstance(block, ToolUseBlock):
        return {"type": "tool_use", "id": block.id, "name": block.name, "input": block.input}
    if isinstance(block, ToolResultBlock):
        return {
            "type": "tool_result",
            "tool_use_id": block.tool_use_id,
            "is_error": block.is_error,
            "text": _render(block.content)[:TEXT_CUT],
        }
    if isinstance(block, ThinkingBlock):
        return {"type": "thinking"}
    return {"type": type(block).__name__}


def _blocks(content) -> list[dict]:
    if isinstance(content, str):
        return [{"type": "text", "text": content[:TEXT_CUT]}]
    return [_block(b) for b in content]


def _result_summary(msg: ResultMessage) -> dict:
    return {k: getattr(msg, k, None) for k in RESULT_FIELDS}


def _rate_summary(msg: RateLimitEvent) -> dict:
    info = msg.rate_limit_info
    return {"status": info.status, "resets_at": info.resets_at, "rate_limit_type": info.rate_limit_type}


class Session:
    def __init__(self, inp: dict, clock):
        self.inp = inp
        self.clock = clock
        self.out = Path(inp["out_dir"])
        resume = inp["resume"] or {}
        self.base_elapsed = resume.get("elapsed_s", 0)
        self.start = clock()
        self.status = "running"
        self.reason = None
        self.session_id = resume.get("session_id")
        self.phrases_sent = resume.get("phrases_sent", 0)
        self.tool_calls_since_phrase = 0
        self.results: list[dict] = []
        self.rate_limit = None
        self.cli_version = None
        self.init = None
        self.env_keys: list[str] = []
        self.tasks: list = []

    def elapsed(self, now: float | None = None) -> float:
        return self.base_elapsed + (self.clock() if now is None else now) - self.start

    def t(self, now: float | None = None) -> float:
        return round(self.elapsed(now), 3)

    def append(self, name: str, row: dict) -> None:
        self.out.mkdir(parents=True, exist_ok=True)
        with open(self.out / name, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, default=str, ensure_ascii=False) + "\n")

    def write_state(self, now: float | None = None) -> None:
        self.out.mkdir(parents=True, exist_ok=True)
        state = {
            "status": self.status,
            "reason": self.reason,
            "session_id": self.session_id,
            "phrases_sent": self.phrases_sent,
            "tool_calls_since_phrase": self.tool_calls_since_phrase,
            "elapsed_s": self.t(now),
            "results": self.results,
            "rate_limit": self.rate_limit,
            "cli_version": self.cli_version,
            "init": self.init,
            "env_keys": self.env_keys,
        }
        tmp = self.out / "state.json.tmp"
        tmp.write_text(json.dumps(state, default=str, ensure_ascii=False))
        os.replace(tmp, self.out / "state.json")

    def stderr(self, line: str) -> None:
        self.append("messages.jsonl", {"t": self.t(), "kind": "stderr", "line": line})

    async def pre_tool_use(self, hook_input, tool_use_id, context) -> dict:
        self.tool_calls_since_phrase += 1
        if hook_input.get("session_id"):
            self.session_id = hook_input["session_id"]
        self.append(
            "ledger.jsonl",
            {
                "t": self.t(),
                "session_id": hook_input.get("session_id"),
                "agent_id": hook_input.get("agent_id"),
                "agent_type": hook_input.get("agent_type"),
                "tool_name": hook_input.get("tool_name"),
                "tool_use_id": tool_use_id or hook_input.get("tool_use_id"),
                "tool_input": _cut(hook_input.get("tool_input")),
            },
        )
        return {}

    async def can_use_tool(self, tool_name, input_data, context):
        if tool_name == "AskUserQuestion":
            answers = user_sim.answer(input_data["questions"])
            self.append(
                "user.jsonl",
                {"t": self.t(), "action": "answer", "questions": input_data["questions"], "answers": answers},
            )
            return PermissionResultAllow(
                updated_input={"questions": input_data["questions"], "answers": answers}
            )
        self.append("user.jsonl", {"t": self.t(), "action": "allow", "tool_name": tool_name})
        return PermissionResultAllow(updated_input=input_data)

    def log_message(self, msg, now: float) -> None:
        row = {"t": self.t(now), "kind": type(msg).__name__}
        if isinstance(msg, AssistantMessage):
            row.update(
                content=_blocks(msg.content), model=msg.model, parent_tool_use_id=msg.parent_tool_use_id
            )
        elif isinstance(msg, UserMessage):
            row.update(content=_blocks(msg.content), parent_tool_use_id=msg.parent_tool_use_id)
        elif isinstance(msg, ResultMessage):
            row.update(_result_summary(msg))
        elif isinstance(msg, RateLimitEvent):
            row.update(_rate_summary(msg))
        elif isinstance(msg, SystemMessage):
            row["subtype"] = msg.subtype
            if msg.subtype == "background_tasks_changed":
                row["tasks"] = msg.data.get("tasks")
        self.append("messages.jsonl", row)

    def observe(self, msg) -> None:
        if isinstance(msg, SystemMessage):
            data = msg.data or {}
            if data.get("session_id"):
                self.session_id = data["session_id"]
            if msg.subtype == "init" and self.init is None:
                self.cli_version = data.get("claude_code_version")
                self.init = {
                    k: data.get(k)
                    for k in ("model", "tools", "agents", "skills", "slash_commands", "permissionMode")
                }
            elif msg.subtype == "background_tasks_changed":
                self.tasks = list(data.get("tasks") or [])
        elif isinstance(msg, ResultMessage):
            if msg.session_id:
                self.session_id = msg.session_id
            self.results.append(_result_summary(msg))
        elif isinstance(msg, RateLimitEvent):
            if msg.session_id:
                self.session_id = msg.session_id
            self.rate_limit = _rate_summary(msg)


def build_options(inp: dict, token: str, session: Session | None = None) -> ClaudeAgentOptions:
    session = session or Session(inp, time.monotonic)
    out = inp["out_dir"]
    aliases = inp["aliases"]
    env = {
        "CLAUDE_CODE_OAUTH_TOKEN": token,
        "CLAUDE_CONFIG_DIR": f"{out}/claude",
        "CLAUDE_ENV_FILE": "/opt/selfcheck/env.sh",
        "PATH": "/opt/selfcheck/bin:" + os.environ.get("PATH", ""),
        "HARNESS_TELEMETRY_DIR": f"{out}/telemetry",
        "HTTPS_PROXY": inp["proxy_url"],
        "HTTP_PROXY": inp["proxy_url"],
        "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
        "DISABLE_AUTOUPDATER": "1",
        "CLAUDE_CODE_DISABLE_AUTO_MEMORY": "1",
    }
    for alias, var in (
        ("opus", "ANTHROPIC_DEFAULT_OPUS_MODEL"),
        ("sonnet", "ANTHROPIC_DEFAULT_SONNET_MODEL"),
        ("haiku", "ANTHROPIC_DEFAULT_HAIKU_MODEL"),
    ):
        if alias in aliases:
            env[var] = aliases[alias]
    resume = inp["resume"]
    return ClaudeAgentOptions(
        cwd="/testbed",
        permission_mode="bypassPermissions",
        setting_sources=["project"],
        system_prompt={"type": "preset", "preset": "claude_code"},
        model=inp["model"],
        effort=inp["effort"],
        disallowed_tools=list(inp["disallowed_tools"]),
        mcp_servers={},
        strict_mcp_config=True,
        can_use_tool=session.can_use_tool,
        hooks={"PreToolUse": [HookMatcher(matcher=None, hooks=[session.pre_tool_use])]},
        stderr=session.stderr,
        resume=resume["session_id"] if resume else None,
        env=env,
    )


async def _pump(client, queue: asyncio.Queue) -> None:
    # The queue lets the loop poll the clock while the generator waits for the CLI; cancelling a
    # pending __anext__ directly would close the generator and lose the session stream.
    try:
        async for msg in client.receive_messages():
            await queue.put(("msg", msg))
        await queue.put(("end", None))
    except Exception as exc:
        await queue.put(("err", exc))


async def _send_phrase(s: Session, client, phrase: str, action: str) -> None:
    row = {"t": s.t(), "action": action}
    if action == "phrase":
        s.phrases_sent += 1
        s.tool_calls_since_phrase = 0
        row["n"] = s.phrases_sent
    s.append("user.jsonl", row)
    await client.query(phrase)


async def _loop(s: Session, client, poll_s: float) -> None:
    inp = s.inp
    queue: asyncio.Queue = asyncio.Queue()
    await client.connect()
    pump = asyncio.ensure_future(_pump(client, queue))
    try:
        if inp["resume"]:
            await _send_phrase(s, client, inp["phrase"], "resume")
        else:
            await client.query(inp["prompt"])
        owe_idle = False
        last_msg = s.clock()
        while True:
            try:
                kind, payload = await asyncio.wait_for(queue.get(), poll_s)
            except asyncio.TimeoutError:
                kind, payload = None, None
            now = s.clock()
            idle = False
            if kind == "err":
                raise payload
            if kind == "end":
                raise StreamEnded("message stream closed before a terminal state")
            if kind == "msg":
                last_msg = now
                s.log_message(payload, now)
                s.observe(payload)
                if isinstance(payload, RateLimitEvent) and payload.rate_limit_info.status == "rejected":
                    s.status, s.reason = "interrupted", "rate_limit_event"
                    return
                if isinstance(payload, ResultMessage):
                    if payload.api_error_status == 429:
                        s.status, s.reason = "interrupted", "api_error_429"
                        return
                    if s.tasks:
                        owe_idle = True
                    else:
                        idle = True
            if s.elapsed(now) >= inp["wall_clock_s"]:
                await client.interrupt()
                s.status, s.reason = "capped", "wall_clock"
                return
            if owe_idle and not s.tasks and not idle and now - last_msg >= inp["idle_grace_s"]:
                idle = True
            if not idle:
                continue
            owe_idle = False
            s.write_state(now)
            action, value = user_sim.on_idle(
                s.phrases_sent, s.tool_calls_since_phrase, inp["max_user_turns"]
            )
            if action == "stop":
                s.status = value
                return
            await _send_phrase(s, client, value, "phrase")
    finally:
        pump.cancel()
        try:
            await pump
        except asyncio.CancelledError:
            pass


async def _run(inp: dict, client_factory, clock, poll_s: float) -> dict:
    token = Path(inp["token_path"]).read_text().strip()
    s = Session(inp, clock)
    options = build_options(inp, token, s)
    s.env_keys = sorted(options.env)
    client = client_factory(options)
    try:
        await _loop(s, client, poll_s)
    except Exception as exc:
        s.status, s.reason = "error", f"{type(exc).__name__}: {exc}"
    try:
        await client.disconnect()
    except Exception as exc:
        s.append(
            "messages.jsonl",
            {"t": s.t(), "kind": "disconnect_error", "line": f"{type(exc).__name__}: {exc}"},
        )
    s.write_state()
    return json.loads((s.out / "state.json").read_text())


def run(inp: dict, client_factory, clock, *, poll_s: float = 1.0) -> dict:
    return asyncio.run(_run(inp, client_factory, clock, poll_s))


def main(argv: list[str]) -> int:
    try:
        inp = json.loads(Path(argv[0]).read_text())
        if any(k not in inp for k in REQUIRED):
            return 2
        Path(inp["token_path"]).read_text()
    except (OSError, ValueError, IndexError, TypeError):
        return 2
    run(inp, lambda options: ClaudeSDKClient(options), time.monotonic)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

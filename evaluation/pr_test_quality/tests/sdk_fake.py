import asyncio
import copy
import json
import os
import threading
import time
from pathlib import Path

from claude_agent_sdk import (
    AssistantMessage, ResultMessage, SystemMessage, TextBlock, ToolPermissionContext,
)

RESULT = dict(subtype="success", is_error=False, num_turns=1, session_id="sess-1", total_cost_usd=0.01,
              usage={"input_tokens": 3}, model_usage={"m": {"inputTokens": 3}}, api_error_status=None,
              terminal_reason="completed", errors=None)


def result(**kw):
    return ResultMessage(duration_ms=7, duration_api_ms=5, **{**RESULT, **kw})


def init(session_id="sess-1"):
    return SystemMessage(subtype="init", data={"type": "system", "subtype": "init", "session_id": session_id,
                                               "cwd": "/testbed", "model": "claude-sonnet-5-5", "tools": ["Bash"],
                                               "agents": [], "skills": [], "slash_commands": [],
                                               "permissionMode": "bypassPermissions"})


def text(msg):
    return AssistantMessage(content=[TextBlock(text=msg)], model="claude-sonnet-5-5", parent_tool_use_id=None)


class Tool:
    def __init__(self, name="Bash", input=None, ask=False, tool_use_id="toolu_1"):
        self.name, self.input, self.ask, self.tool_use_id = name, input or {"command": "ls"}, ask, tool_use_id


def Ask(questions):
    return Tool("AskUserQuestion", {"questions": questions}, ask=True)


_END = object()


class FakeClient:
    """Scripted ClaudeSDKClient: segment i plays when query i arrives."""

    def __init__(self, options, script, watchdog_s=20.0, query_error=None):
        self.options, self.script, self.watchdog_s = options, script, watchdog_s
        self.query_error = query_error
        self.queries, self.permission_results, self.interrupts = [], [], 0
        self._queue = None
        self._tasks = []
        self._prev = None
        self._closed = False

    def _ensure(self):
        if self._queue is None:
            self._queue = asyncio.Queue()

    async def connect(self):
        self._ensure()

    async def query(self, text):
        self._ensure()
        self.queries.append(text)
        if self.query_error is not None:
            raise self.query_error
        if len(self.queries) - 1 < len(self.script):
            task = asyncio.ensure_future(self._play(self.script[len(self.queries) - 1], self._prev))
            self._prev = task
            self._tasks.append(task)

    def receive_messages(self):
        client = self

        class Stream:
            def __aiter__(self):
                return self

            async def __anext__(self):
                client._ensure()
                try:
                    item = await asyncio.wait_for(client._queue.get(), timeout=client.watchdog_s)
                except asyncio.TimeoutError:
                    raise RuntimeError("fake client watchdog: driver reached no terminal state")
                if item is _END:
                    raise StopAsyncIteration
                return item
        return Stream()

    async def interrupt(self):
        self.interrupts += 1
        self._closed = True
        self._queue.put_nowait(_END)

    async def disconnect(self):
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)

    async def _play(self, segment, previous):
        if previous is not None:
            await asyncio.wait([previous])
        for item in segment:
            if self._closed:
                return
            if isinstance(item, Tool):
                hook_input = {"session_id": "sess-1", "transcript_path": "/x/t.jsonl", "cwd": "/testbed",
                              "permission_mode": "bypassPermissions", "hook_event_name": "PreToolUse",
                              "tool_name": item.name, "tool_input": copy.deepcopy(item.input),
                              "tool_use_id": item.tool_use_id}
                for matcher in self.options.hooks["PreToolUse"]:
                    for hook in matcher.hooks:
                        await hook(hook_input, item.tool_use_id, {"signal": None})
                if item.ask:
                    ctx = ToolPermissionContext(tool_use_id=item.tool_use_id, agent_id=None)
                    self.permission_results.append(
                        await self.options.can_use_tool(item.name, copy.deepcopy(item.input), ctx))
            else:
                self._queue.put_nowait(item)
                await asyncio.sleep(0.01)


class Factory:
    def __init__(self, script, **kw):
        self.script, self.kw, self.clients = script, kw, []

    def __call__(self, options):
        client = FakeClient(options, self.script, **self.kw)
        self.clients.append(client)
        return client


class Responder:
    """Answers req-<n>.json files in a real directory."""

    def __init__(self, directory, policy):
        self.dir, self.policy, self.seen = Path(directory), policy, []
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, daemon=True)

    def __enter__(self):
        self._thread.start()
        return self

    def __exit__(self, *exc):
        self._stop.set()
        self._thread.join(5)

    def _loop(self):
        done = set()
        while not self._stop.is_set():
            for path in sorted(self.dir.glob("req-*.json")):
                n = int(path.stem.split("-")[1])
                if n in done:
                    continue
                try:
                    req = json.loads(path.read_text(encoding="utf-8"))
                except ValueError:
                    continue
                done.add(n)
                self.seen.append(req)
                body = self.policy(req)
                if body is None:
                    continue
                tmp = self.dir / ("resp-%d.json.tmp" % n)
                tmp.write_text(json.dumps(dict(body, n=n)), encoding="utf-8")
                os.replace(tmp, self.dir / ("resp-%d.json" % n))
            time.sleep(0.005)

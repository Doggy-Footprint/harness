"""Fakes and spec-literal oracles for the M2 agent runner tests.

Expected values here are copied from the spec text (spec 3a7ecc520d8871ae v2), never derived from
the implementation. The fakes implement only the spec's pinned seams: the SDK client used by
`driver.run`, the host docker module/Container used by `run` and `extract`.
"""
import asyncio
import copy
import io
import json
import os
import re
import secrets
import subprocess
import tarfile
import shutil
import tempfile
import threading
import time
import unittest
from unittest import mock
from dataclasses import dataclass, field
from pathlib import Path

from claude_agent_sdk import (
    RateLimitEvent,
    ResultMessage,
    SystemMessage,
    ToolPermissionContext,
)
from claude_agent_sdk import RateLimitInfo

ROOT = Path(__file__).resolve().parents[2]

PHRASE = (
    "확인했습니다. 이슈 외 정보는 없습니다. 언급된 개념은 알고 있습니다. "
    "Ask 항목을 포함한 모든 질문에 당신의 권장안을 제 답으로 삼습니다. 승인합니다, 진행하세요."
)
APPROVAL_WORDS = ("approve", "proceed", "continue", "accept", "yes", "승인", "진행", "계속", "예")

PROMPT_SUFFIX = "\n\nResolve the issue above in the repository at /testbed. Add or modify automated tests that verify the fix.\n"
HARNESS_PREFIX = "/workflow-approach "

PLACEHOLDERS = (
    "[#TODO][3-5 lines of description of the project]",
    "[#TODO]Alert user to set up definition & north-start of the project.",
)

SPEC_AGENT_CFG = {
    "sdk": "claude-agent-sdk==0.2.165",
    "uv_image": "ghcr.io/astral-sh/uv:0.6.5",
    "tools_base": "ubuntu@sha256:5ec03bb3441e8b0bf3b4f9cd4629a1ae763010dc3035bb8da3ae6cf026486401",
    "python": "3.12",
    "testbed_tools": ["mutmut==2.5.1", "hypothesis", "coverage", "pytest-cov"],
    "proxy_image": "ubuntu/squid@sha256:6a097f68bae708cedbabd6188d68c7e2e7a38cedd05a176e1cc0ba29e3bbe029",
    "allow_hosts": ["api.anthropic.com"],
    "network": "selfcheck-int",
    "proxy_name": "selfcheck-proxy",
    "cpus": 4,
    "memory": "6g",
    "model": "claude-opus-5-5",
    "effort": "low",
    "aliases": {"opus": "claude-opus-5-5", "sonnet": "claude-sonnet-5-5", "haiku": "claude-haiku-5-5"},
    "wall_clock_min": 180,
    "max_user_turns": 8,
    "idle_grace_s": 120,
    "host_grace_s": 600,
    "disallowed_tools": [
        "WebSearch", "WebFetch", "EnterWorktree", "ExitWorktree", "CronCreate", "CronDelete",
        "CronList", "ScheduleWakeup", "RemoteTrigger",
    ],
    "runs_dir": "~/.harness/selfcheck/runs",
    "token_file": "~/.config/selfcheck/oauth_token",
}

SPEC_ENV_KEYS = {
    "CLAUDE_CODE_OAUTH_TOKEN", "CLAUDE_CONFIG_DIR", "CLAUDE_ENV_FILE", "PATH", "HARNESS_TELEMETRY_DIR",
    "HTTPS_PROXY", "HTTP_PROXY", "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC", "DISABLE_AUTOUPDATER",
    "CLAUDE_CODE_DISABLE_AUTO_MEMORY", "ANTHROPIC_DEFAULT_OPUS_MODEL", "ANTHROPIC_DEFAULT_SONNET_MODEL",
    "ANTHROPIC_DEFAULT_HAIKU_MODEL",
}

MANIFEST_KEYS = {
    "run_id", "instance_id", "arm", "selfcheck_commit", "harness_ref", "harness_commit", "start_commit",
    "install", "model", "effort", "aliases", "sdk", "cli_version", "tools", "disallowed_tools", "caps",
    "container", "env_keys", "prompt_template_hash", "user_sim_hash", "images", "network",
}
FR13_DIFFERENCES = {"arm", "harness_ref", "harness_commit", "start_commit", "install", "prompt_template_hash"}
PREDICTION_KEYS = {
    "instance_id", "arm", "run_id", "start_commit", "tainted", "seed", "src_diff", "test_patch",
    "scratch_diff", "excluded_paths",
}

DRIVER_ARGV = ["/opt/selfcheck-py/venv/bin/python", "/opt/selfcheck/agent/driver.py", "/selfcheck/in/input.json"]
# Spec 54ad633104783ebe R6: the informed entry runs informed_driver.py staged next to driver.py, same interpreter and input path.
INFORMED_DRIVER_ARGV = [
    "/opt/selfcheck-py/venv/bin/python", "/opt/selfcheck/agent/informed_driver.py", "/selfcheck/in/input.json",
]
RELAY_DIR = "/selfcheck/relay"
SEED_STATUS_ARGV = ["/opt/selfcheck-py/venv/bin/python", ".harness/bin/seed.py", "status"]
SEED_RESTORE_ARGV = ["/opt/selfcheck-py/venv/bin/python", ".harness/bin/seed.py", "restore"]
KILL_ARGV = ["sh", "-c", "kill -9 -1"]
REV_PARSE_ARGV = ["git", "rev-parse", "HEAD"]
GIT_ADD_ARGV = ["git", "add", "-A"]
INSTALLER_FRAGMENT = "installer/harness.py install /testbed --no-ci"
MKDIR_OUT_ARGV = ["sh", "-c", "mkdir -p /selfcheck/in /selfcheck/out && chown nonroot:nonroot /selfcheck/out"]
EXTRACT_ARGV = [
    "sh", "-c",
    "mkdir -p /opt/harness-src && tar -xf /opt/harness-src.tar -C /opt/harness-src && rm /opt/harness-src.tar",
]
CHOWN_AGENTS_ARGV = ["chown", "nonroot:nonroot", "/testbed/AGENTS.md"]
COMMIT_ARGV = [
    "sh", "-c",
    "git add -A && git -c core.hooksPath=/dev/null -c user.name=selfcheck -c user.email=selfcheck@localhost "
    "commit -q -m \"selfcheck: install harness\"",
]
HOOKS_ARGV = ["git", "config", "--get", "core.hooksPath"]
PRECOMMIT_ARGV = ["test", "-f", ".pre-commit-config.yaml"]
CLEANUP_ARGV = ["rm", "-rf", "/opt/harness-src"]
BASE_HEAD = "a" * 40
INSTALL_HEAD = "b" * 40
PENDING_SEED_TEXT = "seed: unrestored files in /testbed/.harness/seed\n  AGENTS.md\n"


def diff_argv(start_commit):
    return [
        "git", "-c", "core.quotePath=true", "diff", "--cached", "--binary", "--no-color", "--no-ext-diff",
        "--no-textconv", "--no-renames", "--src-prefix=a/", "--dst-prefix=b/", start_commit,
    ]


def expected_prompt(instance, arm):
    text = instance["problem_statement"].strip() + PROMPT_SUFFIX
    return (HARNESS_PREFIX + text) if arm == "harness" else text


def cfg_copy(**over):
    cfg = copy.deepcopy(SPEC_AGENT_CFG)
    cfg.update(over)
    return cfg


def read_jsonl(path):
    text = Path(path).read_text(encoding="utf-8")
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def dummy_token():
    return "tok-" + secrets.token_hex(24)


def write_token_file(directory, token=None, name="oauth_token"):
    token = token or dummy_token()
    path = Path(directory) / name
    path.write_text(token + "\n", encoding="utf-8")
    path.chmod(0o600)
    return str(path), token


# ----------------------------------------------------------------------------------------------
# SDK message builders (real claude_agent_sdk classes)
# ----------------------------------------------------------------------------------------------

RESULT_DEFAULTS = {
    "subtype": "success", "is_error": False, "num_turns": 1, "session_id": "sess-1",
    "total_cost_usd": 0.01, "usage": {"input_tokens": 3}, "model_usage": {"m": {"inputTokens": 3}},
    "api_error_status": None, "terminal_reason": "completed", "errors": None,
}


def result(**kw):
    fields = {**RESULT_DEFAULTS, **kw}
    return ResultMessage(duration_ms=7, duration_api_ms=5, **fields)


def result_summary(**kw):
    return {**RESULT_DEFAULTS, **kw}


INIT_DATA = {
    "claude_code_version": "2.1.294",
    "model": "claude-haiku-5-5",
    "tools": ["Bash", "Edit", "AskUserQuestion"],
    "agents": ["general-purpose"],
    "skills": ["workflow-approach"],
    "slash_commands": ["workflow-approach"],
    "permissionMode": "bypassPermissions",
}


def init(session_id="sess-1", **over):
    data = {"type": "system", "subtype": "init", "session_id": session_id, "cwd": "/testbed",
            "unlisted_key": "ignored", **INIT_DATA, **over}
    return SystemMessage(subtype="init", data=data)


def init_summary(**over):
    base = {k: INIT_DATA[k] for k in ("model", "tools", "agents", "skills", "slash_commands", "permissionMode")}
    base.update(over)
    return base


def bg_changed(tasks, session_id="sess-1"):
    return SystemMessage(
        subtype="background_tasks_changed",
        data={"type": "system", "subtype": "background_tasks_changed", "tasks": tasks, "session_id": session_id},
    )


BG_TASK = {"task_id": "t1", "run_id": "r1", "task_type": "local_agent", "description": "bg"}


def rate_limit(status, resets_at=1791843000, rate_limit_type="five_hour", session_id="sess-1"):
    return RateLimitEvent(
        rate_limit_info=RateLimitInfo(status=status, resets_at=resets_at, rate_limit_type=rate_limit_type),
        uuid="u-1", session_id=session_id,
    )


# ----------------------------------------------------------------------------------------------
# Fake clock and fake SDK client
# ----------------------------------------------------------------------------------------------

class FakeClock:
    def __init__(self, start=1000.0):
        self.value = float(start)

    def __call__(self):
        return self.value

    def advance(self, seconds):
        self.value += seconds


class Tool:
    """A tool call as the CLI performs it: PreToolUse hook, then (optionally) can_use_tool."""

    def __init__(self, name="Bash", input=None, *, tool_use_id="toolu_1", input_tool_use_id="same",
                 agent_id=None, agent_type=None, session_id="sess-1", ask_permission=False):
        self.name = name
        self.input = {"command": "ls"} if input is None else input
        self.tool_use_id = tool_use_id
        self.input_tool_use_id = tool_use_id if input_tool_use_id == "same" else input_tool_use_id
        self.agent_id = agent_id
        self.agent_type = agent_type
        self.session_id = session_id
        self.ask_permission = ask_permission


def Ask(questions, **kw):
    return Tool("AskUserQuestion", {"questions": questions}, ask_permission=True, **kw)


class Wait:
    """Let the driver poll, advance the fake clock by `seconds`, then let it poll again."""

    def __init__(self, seconds):
        self.seconds = seconds


class Probe:
    def __init__(self, fn):
        self.fn = fn


class Raise:
    def __init__(self, exc):
        self.exc = exc


class StderrLine:
    def __init__(self, line):
        self.line = line


class FakeTimeout(Exception):
    pass


_END = object()


class _Raised:
    def __init__(self, exc):
        self.exc = exc


class _Stream:
    def __init__(self, client):
        self.client = client

    def __aiter__(self):
        return self

    async def __anext__(self):
        client = self.client
        client._ensure()
        if client._queue.empty():
            client._idle.set()
        try:
            item = await asyncio.wait_for(client._queue.get(), timeout=client._remaining())
        except asyncio.TimeoutError:
            raise FakeTimeout("fake client watchdog expired: the driver did not reach a terminal state")
        if item is _END:
            raise StopAsyncIteration
        if isinstance(item, _Raised):
            raise item.exc
        return item


class FakeClient:
    """Scripted stand-in for ClaudeSDKClient.

    `script[i]` is played when the i-th `query` arrives. A segment is a list of SDK messages and
    the items Tool/Ask/Wait/Probe/Raise/StderrLine. The stream goes silent after a segment ends.
    """

    def __init__(self, options, script, clock, *, poll_s, connect_error=None, query_error=None,
                 disconnect_error=None, watchdog_s=30.0):
        self.options = options
        self.script = script
        self.clock = clock
        self.poll_s = poll_s
        self.connect_error = connect_error
        self.query_error = query_error
        self.disconnect_error = disconnect_error
        self.watchdog_s = watchdog_s
        self.queries = []
        self.interrupts = 0
        self.connected = False
        self.disconnected = False
        self.log = []
        self.hook_results = []
        self.permission_results = []
        self.callback_errors = []
        self.probes = []
        self._queue = None
        self._idle = None
        self._tasks = []
        self._prev = None
        self._closed = False
        self._deadline = None

    def _ensure(self):
        if self._queue is None:
            self._queue = asyncio.Queue()
            self._idle = asyncio.Event()

    def _remaining(self):
        if self._deadline is None:
            return self.watchdog_s
        return max(0.01, self._deadline - time.monotonic())

    async def connect(self):
        self._ensure()
        self.log.append(("connect",))
        self.connected = True
        if self.connect_error is not None:
            raise self.connect_error

    async def query(self, text):
        self._ensure()
        self.log.append(("query", text))
        self.queries.append(text)
        if self._deadline is None:
            self._deadline = time.monotonic() + self.watchdog_s
        if self.query_error is not None:
            raise self.query_error
        index = len(self.queries) - 1
        if index < len(self.script):
            task = asyncio.ensure_future(self._play(self.script[index], self._prev))
            self._prev = task
            self._tasks.append(task)

    def receive_messages(self):
        return _Stream(self)

    async def interrupt(self):
        self._ensure()
        self.log.append(("interrupt",))
        self.interrupts += 1
        self._closed = True
        self._queue.put_nowait(_END)

    async def disconnect(self):
        self.log.append(("disconnect",))
        self.disconnected = True
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        if self.disconnect_error is not None:
            raise self.disconnect_error

    async def _play(self, segment, previous):
        if previous is not None:
            await asyncio.wait([previous])
        try:
            for item in segment:
                if self._closed or self.disconnected:
                    return
                await self._do(item)
        except asyncio.CancelledError:
            raise
        except BaseException as exc:
            self.callback_errors.append(exc)

    async def _settle(self):
        for _ in range(500):
            if self._idle.is_set() or self._closed or self.disconnected:
                return
            await asyncio.sleep(0.002)

    async def _do(self, item):
        if isinstance(item, Wait):
            await asyncio.sleep(self.poll_s * 3)
            self.clock.advance(item.seconds)
            await asyncio.sleep(self.poll_s * 5)
        elif isinstance(item, Probe):
            self.probes.append(item.fn(self))
        elif isinstance(item, Raise):
            self._queue.put_nowait(_Raised(item.exc))
            self._closed = True
        elif isinstance(item, Tool):
            await self._tool(item)
        elif isinstance(item, StderrLine):
            self.options.stderr(item.line)
        else:
            self._idle.clear()
            self._queue.put_nowait(item)
            await self._settle()

    async def _tool(self, tool):
        hook_input = {
            "session_id": tool.session_id, "transcript_path": "/x/t.jsonl", "cwd": "/testbed",
            "permission_mode": "bypassPermissions", "hook_event_name": "PreToolUse",
            "tool_name": tool.name, "tool_input": copy.deepcopy(tool.input),
        }
        if tool.input_tool_use_id is not None:
            hook_input["tool_use_id"] = tool.input_tool_use_id
        if tool.agent_id is not None:
            hook_input["agent_id"] = tool.agent_id
        if tool.agent_type is not None:
            hook_input["agent_type"] = tool.agent_type
        for matcher in self.options.hooks["PreToolUse"]:
            for hook in matcher.hooks:
                self.hook_results.append(await hook(hook_input, tool.tool_use_id, {"signal": None}))
        if tool.ask_permission:
            context = ToolPermissionContext(tool_use_id=tool.tool_use_id, agent_id=tool.agent_id)
            self.permission_results.append(
                await self.options.can_use_tool(tool.name, copy.deepcopy(tool.input), context)
            )


class ClientFactory:
    def __init__(self, script, clock, *, poll_s=0.01, **kw):
        self.script = script
        self.clock = clock
        self.poll_s = poll_s
        self.kw = kw
        self.clients = []

    def __call__(self, options):
        client = FakeClient(options, self.script, self.clock, poll_s=self.poll_s, **self.kw)
        self.clients.append(client)
        return client

    @property
    def client(self):
        return self.clients[0]


def driver_input(out_dir, token_path, **over):
    inp = {
        "run_id": "run-fixture", "arm": "baseline", "prompt": "PROMPT-TEXT", "model": "claude-haiku-5-5",
        "effort": "medium", "aliases": dict(SPEC_AGENT_CFG["aliases"]),
        "disallowed_tools": list(SPEC_AGENT_CFG["disallowed_tools"]), "wall_clock_s": 1000,
        "max_user_turns": 3, "idle_grace_s": 120, "phrase": PHRASE, "out_dir": str(out_dir),
        "token_path": str(token_path), "proxy_url": "http://selfcheck-proxy:3128", "resume": None,
    }
    inp.update(over)
    return inp


# ----------------------------------------------------------------------------------------------
# Real git diffs for extraction tests
# ----------------------------------------------------------------------------------------------

def _git_env():
    env = dict(os.environ)
    env.update(GIT_CONFIG_GLOBAL="/dev/null", GIT_CONFIG_SYSTEM="/dev/null", GIT_CONFIG_NOSYSTEM="1")
    return env


def _git(cwd, *args):
    return subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "core.autocrlf=false", *args],
        cwd=cwd, env=_git_env(), capture_output=True, check=True,
    ).stdout.decode("utf-8")


def real_git_diff(base, edits):
    """Run the spec's pinned `git add -A` + diff argv in a real temp repo; returns (diff, head)."""
    with tempfile.TemporaryDirectory(prefix="agentfake-git-") as tmp:
        _git(tmp, "init", "-q", ".")
        for name, text in base.items():
            target = Path(tmp, name)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(text.encode("utf-8"))
        _git(tmp, "add", "-A")
        _git(tmp, "commit", "-q", "-m", "base")
        head = _git(tmp, "rev-parse", "HEAD").strip()
        for name, text in edits.items():
            target = Path(tmp, name)
            if text is None:
                target.unlink()
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(text.encode("utf-8"))
        _git(tmp, "add", "-A")
        diff = _git(tmp, *diff_argv(head)[1:])
    return diff, head


PLANTED_BASE = {
    "pkg/mod.py": "a = 1\nb = 2\n",
    "tests/test_mod.py": "def test_a():\n    assert True\n",
    "AGENTS.md": "# agents\n",
    ".harness/old.txt": "old\n",
    "README.md": "readme\n",
}
PLANTED_EDITS = {
    "pkg/mod.py": "a = 1\nb = 3\n",
    "tests/test_mod.py": "def test_a():\n    assert True\n\n\ndef test_b():\n    assert 1\n",
    "tests/test_new.py": "def test_n():\n    pass\n",
    "pkg/helper.py": "x = 1\n",
    "repro_issue.py": "print(1)\n",
    ".harness/lib/x.py": "y = 1\n",
    ".claude/settings.json": "{}\n",
    "AGENTS.md": "# agents\nmore\n",
    ".hypothesis/examples/aa": "z\n",
    "mutants/pkg/mod.py": "m = 1\n",
    ".coverage": "c\n",
    ".harness/old.txt": None,
}
PLANTED_BUCKETS = {
    "src": ["pkg/helper.py", "pkg/mod.py"],
    "test": ["tests/test_mod.py", "tests/test_new.py"],
    "scratch": ["repro_issue.py"],
    "excluded": [
        ".harness/lib/x.py", ".claude/settings.json", "AGENTS.md", ".hypothesis/examples/aa",
        "mutants/pkg/mod.py", ".coverage", ".harness/old.txt",
    ],
}

_PLANTED_CACHE = []


def planted():
    """(diff, head) of the planted edits, computed once."""
    if not _PLANTED_CACHE:
        _PLANTED_CACHE.append(real_git_diff(PLANTED_BASE, PLANTED_EDITS))
    return _PLANTED_CACHE[0]


def diff_sections(diff):
    """Independent splitter: [(path, text)] using the `diff --git a/<p> b/<p>` header line."""
    out = []
    for part in re.split(r"(?m)^(?=diff --git )", diff):
        if not part.startswith("diff --git "):
            continue
        header = part.split("\n", 1)[0]
        match = re.match(r"^diff --git a/(.+) b/(.+)$", header)
        out.append((match.group(1), part))
    return out


def expected_split(diff, buckets=PLANTED_BUCKETS):
    where = {p: b for b, paths in buckets.items() for p in paths}
    parts = {"src": [], "test": [], "scratch": [], "excluded": []}
    for path, text in diff_sections(diff):
        parts[where[path]].append(text)
    return {
        "src_diff": "".join(parts["src"]),
        "test_patch": "".join(parts["test"]),
        "scratch_diff": "".join(parts["scratch"]),
        "excluded_paths": sorted(buckets["excluded"]),
    }


def expected_prediction(diff, instance_id, arm, run_id, start_commit, *, tainted=False, seed=None,
                        buckets=PLANTED_BUCKETS):
    pred = expected_split(diff, buckets)
    pred.update(instance_id=instance_id, arm=arm, run_id=run_id, start_commit=start_commit,
                tainted=tainted, seed=seed if seed is not None else {"skipped": True})
    return pred


# ----------------------------------------------------------------------------------------------
# Fake docker module / container (the spec's "Host docker seam")
# ----------------------------------------------------------------------------------------------

class DockerError(Exception):
    pass


class DockerUnreachable(DockerError):
    pass


class ImageMissing(DockerError):
    pass


class DriverResult:
    def __init__(self, exit_code=0, files=None, timed_out=False):
        self.exit_code = exit_code
        self.files = files or {}
        self.timed_out = timed_out


def driver_state_dict(**over):
    state = {
        "status": "completed", "reason": None, "session_id": "sess-1", "phrases_sent": 1,
        "tool_calls_since_phrase": 0, "elapsed_s": 12.5, "results": [], "rate_limit": None,
        "cli_version": "2.1.294", "init": init_summary(), "env_keys": sorted(SPEC_ENV_KEYS),
    }
    state.update(over)
    return state


def driver_files(state=None, *, extra=None, omit_state=False):
    files = {
        "messages.jsonl": b'{"t": 0.0, "kind": "SystemMessage", "subtype": "init"}\n',
        "ledger.jsonl": b"", "user.jsonl": b"",
        "claude/projects/-testbed/s.jsonl": b"{}\n", "telemetry/x.jsonl": b"{}\n",
    }
    if not omit_state:
        files["state.json"] = json.dumps(state if state is not None else driver_state_dict()).encode("utf-8")
    for name, data in (extra or {}).items():
        files[name] = data if isinstance(data, bytes) else data.encode("utf-8")
    return files


def returning(state=None, *, exit_code=0, timed_out=False, extra=None, omit_state=False, raw_state=None):
    """Driver stand-in producing fixed outputs."""
    def driver(container, inp):
        files = driver_files(state, extra=extra, omit_state=omit_state)
        if raw_state is not None:
            files["state.json"] = raw_state
        return DriverResult(exit_code, files, timed_out)
    return driver


@dataclass
class Script:
    head: str = BASE_HEAD
    install_head: str = INSTALL_HEAD
    procs: list = field(default_factory=lambda: [{"pid": 1, "uid": 0, "cmd": "sleep infinity"}])
    seed_pending: bool = False
    restore_exit: int = 0
    restore_clears: bool = True
    clear_on_restore: object = None
    status_exit: object = None
    installer: tuple = (0, "installed ok\n")
    agents_md: str = "# Project\n\n" + PLACEHOLDERS[0] + "\n\nrest\n"
    hooks_path: object = None
    precommit: bool = False
    diff_text: str = ""
    add_fail: object = None
    diff_fail: object = None
    freeze_before: bytes = b"pkg-a==1.0\npkg-b==2.0\n"
    freeze_after: bytes = b"pkg-a==1.0\npkg-b==2.0\nmutmut==2.5.1\nhypothesis==6.0\n"
    driver: object = None
    exec_fail: dict = field(default_factory=dict)


class _State:
    def __init__(self, name, image, labels, script):
        self.name = name
        self.image = image
        self.labels = dict(labels)
        self.running = True
        self.script = script
        self.head = script.head
        self.pending = script.seed_pending
        self.procs = copy.deepcopy(script.procs)
        self.files = {}
        self.dirs = {"/selfcheck/in", "/selfcheck/out", "/opt", "/opt/selfcheck", "/tmp"}
        self.out_files = {}
        self.driver_inputs = []
        self.installed = False
        self.out_ready = False
        self.extracted = False
        if script.agents_md is not None:
            self.files["/testbed/AGENTS.md"] = script.agents_md.encode("utf-8")


def _is_prep_exec(argv):
    """Root `sh -c` that creates /selfcheck/in and /selfcheck/out and chowns /selfcheck/out to nonroot.

    The informed entry's variant also creates and chowns /selfcheck/relay (spec leaves the exact command open).
    """
    if len(argv) != 3 or argv[:2] != ["sh", "-c"]:
        return False
    cmd = argv[2]
    return ("mkdir" in cmd and "/selfcheck/in" in cmd and "/selfcheck/out" in cmd
            and "chown" in cmd and "nonroot" in cmd)


def _name_index(name):
    match = re.search(r"-(\d+)$", name)
    return int(match.group(1)) if match else None


class FakeContainer:
    def __init__(self, docker, cid):
        self._d = docker
        self.cid = cid

    @property
    def _st(self):
        state = self._d.containers.get(self.cid)
        if state is None:
            raise DockerError("No such container: %s" % self.cid)
        return state

    def _record(self, *entry):
        self._d.log.append((entry[0], self.cid, *entry[1:]))

    def paths(self):
        return sorted(self._st.files)

    def find(self, suffix):
        return {p: b for p, b in self._st.files.items() if p.endswith(suffix)}

    def exec(self, argv, *, timeout=None, user=None, workdir=None):
        argv = list(argv)
        self._record("exec", argv, {"timeout": timeout, "user": user, "workdir": workdir})
        state = self._st
        if not state.running:
            raise DockerError("container %s is not running" % self.cid)
        if user not in (None, "root", "nonroot"):
            return 126, "unable to find user %s: no matching entries in passwd file\n" % user, False
        script = state.script
        joined = " ".join(argv)
        for fragment, outcome in script.exec_fail.items():
            if fragment in joined:
                return outcome
        if argv == REV_PARSE_ARGV:
            return 0, state.head + "\n", False
        if argv == SEED_STATUS_ARGV:
            if state.pending:
                return (1 if script.status_exit is None else script.status_exit), PENDING_SEED_TEXT, False
            return (0 if script.status_exit is None else script.status_exit), "seed: none\n", False
        if argv == SEED_RESTORE_ARGV:
            if script.clear_on_restore is None:
                clears = script.restore_exit == 0 and script.restore_clears
            else:
                clears = script.clear_on_restore
            if clears:
                state.pending = False
            return script.restore_exit, "restored AGENTS.md\n" if script.restore_exit == 0 else "restore boom\n", False
        if argv == KILL_ARGV:
            state.procs = [p for p in state.procs if p["uid"] != 1000]
            return 0, "", False
        if argv == GIT_ADD_ARGV:
            if script.add_fail:
                return script.add_fail[0], script.add_fail[1], False
            return 0, "", False
        if argv[:4] == ["git", "-c", "core.quotePath=true", "diff"]:
            if script.diff_fail:
                return script.diff_fail[0], script.diff_fail[1], False
            return 0, script.diff_text, False
        if argv == DRIVER_ARGV or argv == INFORMED_DRIVER_ARGV:
            return self._run_driver(state, script, timeout)
        if argv == MKDIR_OUT_ARGV or _is_prep_exec(argv):
            state.out_ready = True
            return 0, "", False
        if argv == EXTRACT_ARGV:
            if "/opt/harness-src.tar" not in state.files:
                return 2, "tar: /opt/harness-src.tar: Cannot open: No such file or directory\n", False
            del state.files["/opt/harness-src.tar"]
            state.extracted = True
            return 0, "", False
        if argv[:2] == ["sh", "-c"] and len(argv) > 2 and INSTALLER_FRAGMENT in argv[2]:
            if not state.extracted:
                return 127, "python: can't open file '/opt/harness-src/installer/harness.py'\n", False
            code, output = script.installer
            if code == 0:
                state.installed = True
            return code, output, False
        if argv == COMMIT_ARGV:
            state.head = script.install_head
            return 0, "", False
        if argv == HOOKS_ARGV:
            if script.hooks_path is None:
                return 1, "", False
            return 0, script.hooks_path + "\n", False
        if argv == PRECOMMIT_ARGV:
            return (0 if script.precommit else 1), "", False
        if argv == CLEANUP_ARGV:
            state.extracted = False
            return 0, "", False
        return 0, "", False

    def _run_driver(self, state, script, timeout):
        if not state.out_ready:
            return 1, "fake: /selfcheck/out was not created by the pinned mkdir command\n", False
        raw = None
        for path, data in state.files.items():
            if path.endswith("input.json"):
                raw = data
        inp = json.loads(raw.decode("utf-8")) if raw else None
        state.driver_inputs.append(inp)
        driver = script.driver or returning()
        outcome = driver(self, inp)
        state.out_files.update(outcome.files)
        if outcome.timed_out:
            return None, "", True
        return outcome.exit_code, "", False

    def copy_in(self, local, dest):
        local = str(local)
        self._record("copy_in", local, dest)
        state = self._st
        path = Path(local)
        if path.is_dir():
            if local.endswith("/."):
                base = dest.rstrip("/")
            elif dest.endswith("/") or dest in state.dirs:
                base = dest.rstrip("/") + "/" + path.name
            else:
                base = dest
            for item in sorted(path.rglob("*")):
                if item.is_file():
                    state.files[base + "/" + item.relative_to(path).as_posix()] = item.read_bytes()
            return
        data = path.read_bytes()
        if dest.endswith("/") or dest in state.dirs:
            target = dest.rstrip("/") + "/" + path.name
        else:
            target = dest
        state.files[target] = data
        if tarfile.is_tarfile(io.BytesIO(data)):
            with tarfile.open(fileobj=io.BytesIO(data)) as archive:
                for member in archive.getmembers():
                    if member.isfile():
                        state.files["tar::" + member.name.lstrip("./")] = archive.extractfile(member).read()

    def write_text(self, dest, text):
        self._record("write_text", dest, text)
        self._st.files[dest] = text.encode("utf-8")

    def read_bytes(self, src):
        self._record("read_bytes", src)
        state = self._st
        if src == "/opt/selfcheck/freeze-before.txt":
            return state.script.freeze_before
        if src == "/opt/selfcheck/freeze-after.txt":
            return state.script.freeze_after
        if src.startswith("/selfcheck/out/"):
            return state.out_files.get(src[len("/selfcheck/out/"):])
        return state.files.get(src)

    def copy_out(self, src, local):
        self._record("copy_out", src, str(local))
        state = self._st
        if src != "/selfcheck/out/.":
            raise DockerError("fake: unexpected copy_out source %s" % src)
        base = Path(local)
        base.mkdir(parents=True, exist_ok=True)
        for name, data in state.out_files.items():
            target = base / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)

    def processes(self):
        self._record("processes")
        return copy.deepcopy(self._st.procs)

    def stop(self):
        self._record("stop")
        self._st.running = False

    def start(self):
        self._record("start")
        self._st.running = True

    def remove(self):
        self._record("remove")
        self._st
        del self._d.containers[self.cid]
        self._d.removed.append(self.cid)


class FakeDocker:
    """Module-like object implementing the spec's host docker seam; one ordered call log."""

    DockerError = DockerError
    DockerUnreachable = DockerUnreachable
    ImageMissing = ImageMissing

    def __init__(self, *, image_missing=None):
        self.log = []
        self.containers = {}
        self.history = {}
        self.removed = []
        self.networks = set()
        self.default_script = Script()
        self.scripts = {}
        self.image_missing = image_missing or (lambda name: False)
        self.proxy_error = None

    def configure(self, n=None, **kw):
        base = self.default_script if n is None else self.scripts.setdefault(n, copy.deepcopy(self.default_script))
        for key, value in kw.items():
            if not hasattr(base, key):
                raise AttributeError(key)
            setattr(base, key, value)

    def _script_for(self, name):
        return self.scripts.get(_name_index(name), self.default_script)

    def image_id(self, image):
        self.log.append(("image_id", image))
        if self.image_missing(image):
            raise ImageMissing(image)
        import hashlib
        return "sha256:" + hashlib.sha256(image.encode()).hexdigest()

    def Container(self, cid):
        return FakeContainer(self, cid)

    def start_container(self, image, *, name, network, labels, cpus, memory, mounts):
        self.log.append(("start_container", name, {
            "image": image, "network": network, "labels": dict(labels), "cpus": cpus, "memory": memory,
            "mounts": list(mounts),
        }))
        if name in self.containers:
            raise DockerError("name in use: %s" % name)
        self.containers[name] = _State(name, image, labels, copy.deepcopy(self._script_for(name)))
        self.history[name] = self.containers[name]
        return FakeContainer(self, name)

    def container_exists(self, name):
        self.log.append(("container_exists", name))
        return name in self.containers

    def network_exists(self, name):
        self.log.append(("network_exists", name))
        return name in self.networks

    def ensure_network(self, name, internal=True):
        self.log.append(("ensure_network", name, internal))
        self.networks.add(name)

    def container_status(self, name):
        self.log.append(("container_status", name))
        state = self.containers.get(name)
        if state is None:
            return None
        return {"running": state.running, "labels": dict(state.labels)}

    def remove_container(self, name):
        self.log.append(("remove_container", name))
        if name in self.containers:
            del self.containers[name]
            self.removed.append(name)

    def start_proxy(self, image, *, name, networks, labels, conf_text):
        self.log.append(("start_proxy", name, {
            "image": image, "networks": list(networks), "labels": dict(labels), "conf_text": conf_text,
        }))
        if self.proxy_error is not None:
            raise self.proxy_error
        self.containers[name] = _State(name, image, labels, Script())
        return FakeContainer(self, name)

    def preload(self, name, labels, *, running=True, image="preloaded-image"):
        self.containers[name] = _State(name, image, labels, Script())
        self.containers[name].running = running

    def vanish(self, name):
        del self.containers[name]

    # --- inspection helpers -------------------------------------------------------------------

    def calls(self, kind, name=None):
        return [e for e in self.log if e[0] == kind and (name is None or (len(e) > 1 and e[1] == name))]

    def execs(self, name):
        return [(e[2], e[3]) for e in self.log if e[0] == "exec" and e[1] == name]

    def exec_index(self, name, argv):
        for i, e in enumerate(self.log):
            if e[0] == "exec" and e[1] == name and e[2] == list(argv):
                return i
        return None

    def exec_index_containing(self, name, fragment, after=-1):
        for i, e in enumerate(self.log):
            if i > after and e[0] == "exec" and e[1] == name and fragment in " ".join(e[2]):
                return i
        return None

    def started(self):
        return [e for e in self.log if e[0] == "start_container"]

    def container_labelled(self, run_id):
        return [n for n, s in self.containers.items() if s.labels.get("selfcheck.agent") == run_id]


class StubEgress:
    """Replacement for run.ensure_egress that records into the docker log."""

    def __init__(self, docker, error=None):
        self.docker = docker
        self.error = error
        self.calls = 0

    def __call__(self, cfg, *, docker=None):
        self.calls += 1
        self.docker.log.append(("ensure_egress",))
        if self.error is not None:
            raise self.error


# ----------------------------------------------------------------------------------------------
# Driver test harness
# ----------------------------------------------------------------------------------------------

class Outcome:
    def __init__(self, state, factory, out_dir):
        self.state = state
        self.factory = factory
        self.client = factory.clients[0] if factory.clients else None
        self.out_dir = Path(out_dir)

    def _jsonl(self, name):
        path = self.out_dir / name
        return read_jsonl(path) if path.exists() else []

    def messages(self):
        return self._jsonl("messages.jsonl")

    def ledger(self):
        return self._jsonl("ledger.jsonl")

    def user(self):
        return self._jsonl("user.jsonl")

    def state_file(self):
        return json.loads((self.out_dir / "state.json").read_text(encoding="utf-8"))


class DriverCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="drv-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.token_path, self.token = write_token_file(self.tmp)
        self.out_dir = Path(self.tmp) / "out"
        self.out_dir.mkdir()
        self.clock = FakeClock(1000.0)

    def make_input(self, **over):
        return driver_input(self.out_dir, self.token_path, **over)

    def drive(self, script, *, poll_s=0.01, clock=None, inp=None, **client_kw):
        from selfcheck.agent import driver

        clock = clock or self.clock
        factory = ClientFactory(script, clock, poll_s=poll_s, **client_kw)
        state = driver.run(inp or self.make_input(), factory, clock, poll_s=poll_s)
        outcome = Outcome(state, factory, self.out_dir)
        for client in factory.clients:
            self.assertEqual(client.callback_errors, [], "fake callbacks raised")
        return outcome


# ----------------------------------------------------------------------------------------------
# Host orchestration harness (run.run / run.resume against FakeDocker)
# ----------------------------------------------------------------------------------------------

ROW_A = "sphinx-doc__sphinx-9602"
ROW_B = "mwaskom__seaborn-3187"


def pool_rows():
    rows = {}
    for line in (ROOT / "selfcheck" / "fixtures" / "instances.jsonl").read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            rows[row["instance_id"]] = row
    return rows


def project_definition(repo):
    return json.loads((ROOT / "selfcheck" / "fixtures" / "project_defs.json").read_text(encoding="utf-8"))[repo]


class RunCase(unittest.TestCase):
    CAP_MIN = 5

    def setUp(self):
        from selfcheck import run

        self.run_mod = run
        self.tmp = tempfile.mkdtemp(prefix="runcase-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.token_path, self.token = write_token_file(self.tmp)
        self.runs_dir = Path(self.tmp) / "runs"
        self.cfg = cfg_copy(runs_dir=str(self.runs_dir), token_file=self.token_path)
        self.docker = FakeDocker()
        self.egress = StubEgress(self.docker)
        patcher = mock.patch.object(run, "ensure_egress", self.egress)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.rows = pool_rows()

    def go(self, ids=(ROW_A,), arms=("baseline",), **kw):
        kw.setdefault("cap_min", self.CAP_MIN)
        return self.run_mod.run([self.rows[i] for i in ids], list(arms), cfg=self.cfg, docker=self.docker, **kw)

    def resume(self, run_id, **kw):
        return self.run_mod.resume(run_id, cfg=self.cfg, docker=self.docker, **kw)

    @staticmethod
    def entry(run_dir, instance_id, arm):
        return Path(run_dir) / instance_id / arm

    @staticmethod
    def load(path):
        return json.loads(Path(path).read_text(encoding="utf-8"))

    def entry_state(self, run_dir, instance_id=ROW_A, arm="baseline"):
        return self.load(self.entry(run_dir, instance_id, arm) / "state.json")

    @staticmethod
    def name(run_dir, n):
        return "selfcheck-agent-%s-%d" % (Path(run_dir).name, n)


# ----------------------------------------------------------------------------------------------
# Informed-condition fakes (spec 54ad633104783ebe)
# ----------------------------------------------------------------------------------------------

class HybridClock(FakeClock):
    """FakeClock that also advances with real time, so a timeout measured on either clock elapses."""

    def __init__(self, start=1000.0):
        super().__init__(start)
        self._t0 = time.monotonic()

    def __call__(self):
        return self.value + (time.monotonic() - self._t0)


class RelayResponder:
    """Thread standing in for the host relay: answers req-<n>.json in a directory.

    policy(request) -> dict body (written with `n` added) | None (no response) | ("raw", text) | ("delay", s, body).
    """

    def __init__(self, directory, policy=None, poll_s=0.005):
        self.dir = Path(directory)
        self.policy = policy or (lambda req: None)
        self.poll_s = poll_s
        self.seen = []
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._done = set()

    def __enter__(self):
        self._thread.start()
        return self

    def __exit__(self, *exc):
        self._stop.set()
        self._thread.join(5)
        return False

    def write(self, n, body):
        if isinstance(body, tuple) and body[0] == "raw":
            (self.dir / ("resp-%d.json" % n)).write_text(body[1], encoding="utf-8")
            return
        tmp = self.dir / ("resp-%d.json.tmp" % n)
        tmp.write_text(json.dumps(dict(body, n=n)), encoding="utf-8")
        os.replace(tmp, self.dir / ("resp-%d.json" % n))

    def _handle(self, n, req):
        out = self.policy(req)
        if out is None:
            return
        if isinstance(out, tuple) and out[0] == "delay":
            threading.Timer(out[1], self.write, (n, out[2])).start()
            return
        self.write(n, out)

    def _loop(self):
        while not self._stop.is_set():
            for path in sorted(self.dir.glob("req-*.json")):
                n = int(path.stem.split("-")[1])
                if n in self._done:
                    continue
                try:
                    req = json.loads(path.read_text(encoding="utf-8"))
                except ValueError:
                    continue
                self._done.add(n)
                self.seen.append(req)
                self._handle(n, req)
            time.sleep(self.poll_s)


class FakeRelay:
    """Replacement for informed.Relay: logs construction/start/stop into the fake docker log."""

    def __init__(self, recorder, container, instance, record_path, *, call_fn, poll_s, token):
        self.recorder = recorder
        self.container = container
        self.instance = instance
        self.record_path = Path(record_path)
        self.call_fn = call_fn
        self.poll_s = poll_s
        self.token = token
        self.started = False
        self.stopped = False

    def _log(self, kind):
        self.container._d.log.append((kind, self.container.cid, self.record_path))

    def start(self):
        self.started = True
        self._log("relay_start")
        if self.recorder.record_text is not None:
            self.record_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.record_path, "a", encoding="utf-8") as fh:
                fh.write(self.recorder.record_text.replace("{token}", self.token) + "\n")

    def stop(self):
        self.stopped = True
        self._log("relay_stop")


class RelayRecorder:
    """Callable used to patch informed.Relay; keeps every constructed FakeRelay."""

    def __init__(self, record_text=None):
        self.relays = []
        self.record_text = record_text

    def __call__(self, container, instance, record_path, *, call_fn, poll_s, token):
        relay = FakeRelay(self, container, instance, record_path, call_fn=call_fn, poll_s=poll_s, token=token)
        self.relays.append(relay)
        return relay


class RelayFakeContainer:
    """Container whose /selfcheck/relay is a real temp directory; every write and exec is logged.

    exec runs the argv for real (POSIX tools) with the container path remapped to the temp directory.
    """

    def __init__(self, root, fail_write=None):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.cid = "relay-fake"
        self.ops = []
        self.fail_write = fail_write  # predicate(dest) -> True makes that write/copy raise, like a docker cp failure

    def _map(self, text):
        return text.replace(RELAY_DIR, str(self.root))

    def _unmap(self, text):
        return text.replace(str(self.root), RELAY_DIR)

    def _path(self, dest):
        return Path(self._map(dest))

    def put_request(self, n, obj):
        tmp = self.root / ("req-%d.json.part" % n)
        tmp.write_text(json.dumps(obj), encoding="utf-8")
        os.replace(tmp, self.root / ("req-%d.json" % n))

    def exec(self, argv, *, timeout=None, user=None, workdir=None):
        argv = list(argv)
        self.ops.append(("exec", argv))
        if user not in (None, "root", "nonroot"):
            return 126, "unable to find user %s: no matching entries in passwd file\n" % user, False
        proc = subprocess.run([self._map(a) for a in argv], capture_output=True, text=True)
        return proc.returncode, self._unmap(proc.stdout + proc.stderr), False

    def write_text(self, dest, text):
        self.ops.append(("write", dest, text))
        if self.fail_write is not None and self.fail_write(dest):
            raise RuntimeError("docker cp failed: write refused for %s" % dest)
        path = self._path(dest)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def copy_in(self, local, dest):
        data = Path(local).read_bytes()
        if dest.endswith("/") or self._path(dest).is_dir():
            dest = dest.rstrip("/") + "/" + Path(local).name
        self.ops.append(("write", dest, data.decode("utf-8", "replace")))
        if self.fail_write is not None and self.fail_write(dest):
            raise RuntimeError("docker cp failed: write refused for %s" % dest)
        path = self._path(dest)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def read_bytes(self, src):
        path = self._path(src)
        return path.read_bytes() if path.is_file() else None

    def copy_out(self, src, local):
        local = Path(local)
        local.mkdir(parents=True, exist_ok=True)
        path = self._path(src[:-2] if src.endswith("/.") else src)
        if path.is_dir():
            for item in path.iterdir():
                if item.is_file():
                    shutil.copy(item, local / item.name)
        elif path.is_file():
            shutil.copy(path, local / path.name)

    def response_files(self):
        out = {}
        for p in sorted(self.root.glob("resp-*")):
            try:
                out[p.name] = p.read_text(encoding="utf-8")
            except FileNotFoundError:  # renamed between listing and reading
                continue
        return out

    def everything_written(self):
        """Text of every write, every exec argv, and every response file left behind."""
        parts = []
        for op in self.ops:
            parts.append(" ".join(op[1]) if op[0] == "exec" else op[2])
        parts.extend(self.response_files().values())
        return "\n".join(parts)

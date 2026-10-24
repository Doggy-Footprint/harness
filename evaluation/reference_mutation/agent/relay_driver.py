import asyncio
import json
import os
import re
import sys
import time
from pathlib import Path

from claude_agent_sdk import ClaudeSDKClient

try:
    from . import driver
except ImportError:
    import driver

RELAY_DIR = "/evaluation/relay"
FALLBACK_IDLE = "No preference; use your recommendation. Please continue."
LAST_TEXT_CUT = 8000
REQUIRED = driver.REQUIRED + ("relay_dir", "relay_timeout_s", "relay_poll_s")
_REQUEST_RE = re.compile(r"^req-(\d+)\.json$")


class RelaySession(driver.Session):
    def __init__(self, inp: dict, clock):
        super().__init__(inp, clock)
        self.relay_dir = Path(inp["relay_dir"])
        self.relay_timeout_s = inp["relay_timeout_s"]
        self.relay_poll_s = inp["relay_poll_s"]
        self.last_request = None

    def _next_request(self) -> int:
        if self.last_request is None:
            try:
                names = os.listdir(self.relay_dir)
            except OSError:
                names = []
            self.last_request = max(
                (int(m.group(1)) for m in map(_REQUEST_RE.match, names) if m), default=0
            )
        self.last_request += 1
        return self.last_request

    def _write_request(self, n: int, body: dict) -> None:
        self.relay_dir.mkdir(parents=True, exist_ok=True)
        tmp = self.relay_dir / f"req-{n}.json.tmp"
        tmp.write_text(json.dumps({"n": n, **body}, ensure_ascii=False))
        os.replace(tmp, self.relay_dir / f"req-{n}.json")

    async def _await_response(self, n: int) -> tuple[dict | None, bool]:
        # Polling with asyncio.sleep keeps the message loop running, so the wall-clock cap
        # still fires while a simulated-user call is pending on the host.
        path = self.relay_dir / f"resp-{n}.json"
        started = self.clock()
        while True:
            if path.exists():
                try:
                    obj = json.loads(path.read_text())
                except (OSError, ValueError):
                    return None, False
                return (obj if isinstance(obj, dict) and obj.get("n") == n else None), False
            if self.elapsed() >= self.inp["wall_clock_s"]:
                return None, True
            if self.clock() - started >= self.relay_timeout_s:
                return None, False
            await asyncio.sleep(self.relay_poll_s)

    async def answer_questions(self, questions: list[dict]) -> dict[str, str]:
        fallback = driver.fallback_answers(questions)
        n = self._next_request()
        self._write_request(n, {"kind": "ask", "questions": questions})
        response, _ = await self._await_response(n)
        given = response.get("answers") if response else None
        given = given if isinstance(given, dict) else {}
        answers, source = {}, {}
        for q in questions:
            text = given.get(q["question"])
            if isinstance(text, str) and text.strip():
                answers[q["question"]], source[q["question"]] = text, "user"
            else:
                answers[q["question"]], source[q["question"]] = fallback[q["question"]], "fallback"
        self.append(
            "user.jsonl",
            {"t": self.t(), "action": "answer", "questions": questions, "answers": answers,
             "relay": n, "source": source},
        )
        return answers

    async def next_message(self) -> tuple[str, str | None]:
        action, value = await super().next_message()
        if action == "stop":
            return action, value
        n = self._next_request()
        self._write_request(n, {"kind": "idle", "last_text": self.last_text[-LAST_TEXT_CUT:]})
        response, capped = await self._await_response(n)
        if capped:
            return "send", None
        if response and response.get("action") == "stop":
            self.append("user.jsonl", {"t": self.t(), "action": "stop", "relay": n})
            return "stop", "completed"
        message = response.get("message") if response else None
        if isinstance(message, str) and message.strip():
            self.append("user.jsonl", {"t": self.t(), "action": "reply", "relay": n, "source": "user",
                                       "contradiction": bool(response.get("contradiction"))})
            return "send", message
        self.append("user.jsonl", {"t": self.t(), "action": "reply", "relay": n, "source": "fallback"})
        return "send", FALLBACK_IDLE


def run(inp: dict, client_factory, clock, *, poll_s: float = 1.0) -> dict:
    return driver.run(inp, client_factory, clock, poll_s=poll_s, session_cls=RelaySession)


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

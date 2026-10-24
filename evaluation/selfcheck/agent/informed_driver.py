import asyncio
import json
import os
import re
import sys
import time
from pathlib import Path

from claude_agent_sdk import AssistantMessage, ClaudeSDKClient, PermissionResultAllow, TextBlock

try:
    from . import driver, user_sim
except ImportError:
    import driver
    import user_sim

RELAY_DIR = "/selfcheck/relay"
REQUIRED = driver.REQUIRED + ("user_mode", "relay_dir", "relay_timeout_s", "relay_poll_s")
_REQUEST_RE = re.compile(r"^req-(\d+)\.json$")


class InformedSession(driver.Session):
    def __init__(self, inp: dict, clock):
        super().__init__(inp, clock)
        self.relay_dir = Path(inp["relay_dir"])
        self.relay_timeout_s = inp["relay_timeout_s"]
        self.relay_poll_s = inp["relay_poll_s"]
        self.brief: list[str] = []
        self.last_request = None

    def reset_brief(self) -> None:
        self.brief = []

    def log_message(self, msg, now: float) -> None:
        super().log_message(msg, now)
        if isinstance(msg, AssistantMessage) and msg.parent_tool_use_id is None:
            self.brief += [b.text for b in msg.content if isinstance(b, TextBlock)]

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

    def _capped(self) -> bool:
        return self.elapsed() >= self.inp["wall_clock_s"]

    async def _await_response(self, n: int) -> tuple[dict | None, bool]:
        # Polling with asyncio.sleep keeps the message loop running, so the wall-clock cap
        # still fires while a reviewer call is pending on the host.
        path = self.relay_dir / f"resp-{n}.json"
        started = self.clock()
        while True:
            if path.exists():
                try:
                    obj = json.loads(path.read_text())
                except (OSError, ValueError):
                    return None, False
                return (obj if isinstance(obj, dict) and obj.get("n") == n else None), False
            if self._capped():
                return None, True
            if self.clock() - started >= self.relay_timeout_s:
                return None, False
            await asyncio.sleep(self.relay_poll_s)

    async def can_use_tool(self, tool_name, input_data, context):
        if tool_name != "AskUserQuestion":
            return await super().can_use_tool(tool_name, input_data, context)
        questions = input_data["questions"]
        fallback = user_sim.answer(questions)
        n = self._next_request()
        self._write_request(n, {"kind": "ask", "questions": questions})
        response, _ = await self._await_response(n)
        given = response.get("answers") if response else None
        given = given if isinstance(given, dict) else {}
        answers, source = {}, {}
        for q in questions:
            text = given.get(q["question"])
            if isinstance(text, str) and text.strip():
                answers[q["question"]], source[q["question"]] = text, "reviewer"
            else:
                answers[q["question"]], source[q["question"]] = fallback[q["question"]], "fallback"
        self.append(
            "user.jsonl",
            {
                "t": self.t(), "action": "answer", "questions": questions, "answers": answers,
                "informed": n, "source": source,
            },
        )
        return PermissionResultAllow(updated_input={"questions": questions, "answers": answers})

    async def idle_message(self, phrase: str) -> tuple[str, int, str] | None:
        n = self._next_request()
        self._write_request(n, {"kind": "idle", "brief": "\n".join(self.brief)})
        response, capped = await self._await_response(n)
        if capped:
            return None
        message = response.get("message") if response else None
        if isinstance(message, str) and message.strip():
            return message, n, "reviewer"
        return phrase, n, "fallback"


def _informed_send(original):
    async def send_phrase(s, client, phrase: str, action: str) -> None:
        if action != "phrase":
            await original(s, client, phrase, action)
            return
        picked = await s.idle_message(phrase)
        if picked is None:
            # The loop's own wall-clock check runs next and interrupts; sending now would be wasted.
            return
        message, n, source = picked
        s.reset_brief()
        s.phrases_sent += 1
        s.tool_calls_since_phrase = 0
        s.append(
            "user.jsonl",
            {"t": s.t(), "action": "phrase", "n": s.phrases_sent, "informed": n, "source": source},
        )
        await client.query(message)

    return send_phrase


def run(inp: dict, client_factory, clock, *, poll_s: float = 1.0) -> dict:
    # driver.py is hashed into the baseline fixture and must stay unmodified, so its Session and
    # idle sender are substituted for the duration of this run instead of edited.
    saved = driver.Session, driver._send_phrase
    driver.Session, driver._send_phrase = InformedSession, _informed_send(saved[1])
    try:
        return driver.run(inp, client_factory, clock, poll_s=poll_s)
    finally:
        driver.Session, driver._send_phrase = saved


def main(argv: list[str]) -> int:
    try:
        inp = json.loads(Path(argv[0]).read_text())
        if any(k not in inp for k in REQUIRED) or inp["user_mode"] != "informed":
            return 2
        Path(inp["token_path"]).read_text()
    except (OSError, ValueError, IndexError, TypeError):
        return 2
    run(inp, lambda options: ClaudeSDKClient(options), time.monotonic)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

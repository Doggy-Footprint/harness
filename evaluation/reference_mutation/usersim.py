import json
import re
import threading
import time
from pathlib import Path

from . import REDACTED, section
from .brief import forbidden_terms as _forbidden_terms
from .brief import leaks

FALLBACK_ASK = "(Recommended)"
FALLBACK_IDLE = "No preference; use your recommendation. Please continue."
RELAY_DIR = "/evaluation/relay"
LAST_TEXT_CUT = 8000
_REQUEST_RE = re.compile(r"^req-(\d+)\.json$")
_RESPONSE_RE = re.compile(r"^resp-(\d+)\.json$")


class ResponseFormatError(ValueError):
    pass


def _first_line(exc: Exception) -> str:
    lines = str(exc).strip().splitlines()
    return lines[0] if lines else type(exc).__name__


def _questions(request: dict) -> list[dict]:
    out = []
    for q in request.get("questions") or []:
        if isinstance(q, dict) and isinstance(q.get("question"), str):
            out.append(q)
    return out


def _labels(question: dict) -> list[str]:
    return [o["label"] for o in question.get("options") or [] if isinstance(o, dict) and "label" in o]


def fallback_answer(question: dict) -> str:
    labels = _labels(question)
    return next((label for label in labels if FALLBACK_ASK in label), labels[0] if labels else "")


def build_prompt(task: dict, request: dict, history: list[dict]) -> str:
    brief = task["brief"]
    statements = "\n".join(f"- {s['text']}" for s in brief["statements"])
    past = "\n".join(
        f"[{h.get('n')}] {h.get('kind')}: sent {json.dumps(h.get('sent'), ensure_ascii=False)}" for h in history
    ) or "(none)"
    if request.get("kind") == "idle":
        shape = '{"action": "reply" | "stop", "message": "<text or null>", "contradiction": true | false}'
        what = (
            "The agent stopped and wrote the message below (last top-level assistant text).\n"
            + (request.get("last_text") or "")[-LAST_TEXT_CUT:]
        )
    else:
        shape = '{"answers": {"<question text>": "<chosen option label or short answer, or null>"}}'
        what = "The agent asked the questions below.\n" + json.dumps(
            _questions(request), ensure_ascii=False, indent=1
        )
    return "\n\n".join([
        "You are the user who handed a coding task to an agent. You hold the intent card below and nothing else.",
        f"## Your request\n{brief['request']}",
        f"## Intent card\n{statements}",
        f"## Earlier exchanges in this session\n{past}",
        f"## Now\n{what}",
        "## Rules\n"
        "- Answer only from the intent card.\n"
        f'- Outside the card reply with "{FALLBACK_IDLE}" or choose the option marked "{FALLBACK_ASK}".\n'
        "- Approve a plan or spec that does not contradict the card; otherwise state the contradicted "
        "behavior in plain words and set contradiction to true.\n"
        '- Return action "stop" only when the agent reports it has finished.\n'
        "- Never name tests, test files, helper names or asserted literals.\n"
        "Answer with a single JSON object and nothing else, shaped as " + shape,
    ])


def _first_object(text: str) -> dict:
    decoder = json.JSONDecoder()
    pos = text.find("{")
    while pos != -1:
        try:
            obj, _ = decoder.raw_decode(text, pos)
        except ValueError:
            pos = text.find("{", pos + 1)
            continue
        if isinstance(obj, dict):
            return obj
        pos = text.find("{", pos + 1)
    raise ResponseFormatError("no JSON object in simulated-user output")


def _resolve_option(question: dict, value):
    if value is None:
        return None
    labels = _labels(question)
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise ResponseFormatError("answer must be a string, an option number or null")
    if isinstance(value, int) or (isinstance(value, str) and value.strip().isdigit()):
        index = int(value) - 1
        if 0 <= index < len(labels):
            return labels[index]
    text = str(value)
    return text if text.strip() else None


def parse_response(text: str, request: dict) -> dict:
    obj = _first_object(text)
    if request.get("kind") == "idle":
        action, message = obj.get("action"), obj.get("message")
        if action not in ("reply", "stop"):
            raise ResponseFormatError("action must be reply or stop")
        if not (message is None or isinstance(message, str)):
            raise ResponseFormatError("message must be a string or null")
        contradiction = obj.get("contradiction", False)
        if not isinstance(contradiction, bool):
            raise ResponseFormatError("contradiction must be a boolean")
        return {"action": action, "message": message, "contradiction": contradiction}
    answers = obj.get("answers")
    if not isinstance(answers, dict):
        raise ResponseFormatError("answers must be an object")
    questions = _questions(request)
    known = {q["question"] for q in questions}
    unknown = [k for k in answers if k not in known]
    if unknown:
        raise ResponseFormatError(f"unknown question key: {unknown[0]}")
    return {"answers": {q["question"]: _resolve_option(q, answers.get(q["question"])) for q in questions}}


def _reason_for(exc: Exception) -> str:
    return "timeout" if isinstance(exc, TimeoutError) or "timed out" in str(exc) else "error"


def forbidden_terms(task: dict) -> set[str]:
    return _forbidden_terms(task)


def respond(
    task: dict, request: dict, history: list[dict], *, call_fn, cfg: dict, token: str = ""
) -> tuple[dict, dict]:
    ucfg = section(cfg, "usersim")
    n, kind = request.get("n"), request.get("kind")
    started = time.monotonic()
    raw = parsed = error = None
    reason = None
    try:
        raw = call_fn(
            build_prompt(task, request, history), model=ucfg.get("model", "claude-opus-5-5"),
            effort=ucfg.get("effort", "medium"), timeout_s=ucfg.get("timeout_s", 900),
        )
        parsed = parse_response(raw, request)
    except ResponseFormatError as exc:
        reason, error = "format", _first_line(exc)
    except Exception as exc:
        reason, error = _reason_for(exc), _first_line(exc)
    found: dict[str, list[str]] = {}
    fallbacks: dict[str, str] = {}

    def screen(key: str, value: str | None) -> str | None:
        if value is None or not str(value).strip():
            return None
        terms = leaks(value, task)
        if token and token in value:
            terms = [*terms, REDACTED]
        if terms:
            found[key] = terms
            return None
        return value

    def clean(key: str, value: str | None, default: str) -> str:
        checked = screen(key, value)
        if checked is None:
            fallbacks[key] = "leak" if key in found else (reason or "null")
            return default
        return checked

    if kind == "idle":
        action = parsed["action"] if parsed else "reply"
        message = parsed["message"] if parsed else None
        if action == "stop":
            sent = {"n": n, "action": "stop", "message": screen("message", message), "contradiction": False}
        else:
            text = clean("message", message, FALLBACK_IDLE)
            sent = {"n": n, "action": "reply", "message": text,
                    "contradiction": bool(parsed and parsed["contradiction"] and "message" not in fallbacks)}
    else:
        given = parsed["answers"] if parsed else {}
        sent = {"n": n, "answers": {
            q["question"]: clean(q["question"], given.get(q["question"]), fallback_answer(q))
            for q in _questions(request)
        }}
    row = {
        "n": n, "kind": kind, "request": request, "raw_output": raw, "parsed": parsed, "leaks": found,
        "sent": sent, "fallbacks": fallbacks, "reason": next(iter(fallbacks.values()), None) or reason,
        "error": error, "contradiction": bool(sent.get("contradiction")),
        "elapsed_s": round(time.monotonic() - started, 3),
    }
    if token:
        row = json.loads(json.dumps(row, ensure_ascii=False).replace(json.dumps(token)[1:-1], REDACTED))
    return sent, row


class Relay:
    def __init__(self, container, task: dict, record_path, *, call_fn, cfg: dict, token: str, relay_dir: str = RELAY_DIR):
        self.container = container
        self.task = task
        self.record_path = Path(record_path)
        self.call_fn = call_fn
        self.cfg = cfg
        self.token = token
        self.relay_dir = relay_dir
        self.poll_s = section(cfg, "usersim").get("poll_s", 2)
        self.history: list[dict] = []
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="usersim-relay", daemon=True)
        self._handled: set[int] = set()

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread.is_alive():
            self._thread.join()

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self._poll()
            except Exception:
                # A failed docker call must not end the relay; the next poll retries.
                pass
            self._stop.wait(self.poll_s)

    def _poll(self) -> None:
        _, out, _ = self.container.exec(["ls", "-1", self.relay_dir], user="nonroot")
        names = out.split()
        self._handled |= {int(m.group(1)) for m in map(_RESPONSE_RE.match, names) if m}
        pending = sorted(
            int(m.group(1)) for m in map(_REQUEST_RE.match, names) if m and int(m.group(1)) not in self._handled
        )
        for n in pending:
            if self._stop.is_set():
                return
            self._handle(n)

    def _handle(self, n: int) -> None:
        blob = self.container.read_bytes(f"{self.relay_dir}/req-{n}.json")
        if blob is None:
            return
        self._handled.add(n)
        request = None
        try:
            request = json.loads(blob)
            if not isinstance(request, dict) or request.get("kind") not in ("ask", "idle"):
                raise ValueError("malformed request")
            response, row = respond(
                self.task, {**request, "n": n}, self.history, call_fn=self.call_fn, cfg=self.cfg, token=self.token
            )
        except Exception as exc:
            self._append({"n": n, "kind": request.get("kind") if isinstance(request, dict) else None,
                          "request": request, "sent": None, "error": _first_line(exc), "reason": "error"})
            return
        try:
            self._send(n, response)
        except Exception as exc:
            row["error"] = row["error"] or f"response write failed: {_first_line(exc)}"
        self.history.append({k: row[k] for k in ("n", "kind", "sent")})
        self._append(row)

    def _send(self, n: int, response: dict) -> None:
        final = f"{self.relay_dir}/resp-{n}.json"
        tmp = f"{final}.tmp"
        self.container.write_text(tmp, json.dumps(response, ensure_ascii=False))
        # docker cp writes as root; nonroot must be able to read the renamed file.
        for argv in (["chmod", "644", tmp], ["mv", tmp, final]):
            code, out, _ = self.container.exec(argv, user="root")
            if code != 0:
                raise RuntimeError(f"{argv[0]} failed: {out.strip()}")

    def _append(self, row: dict) -> None:
        text = json.dumps(row, ensure_ascii=False)
        if self.token:
            text = text.replace(self.token, REDACTED)
        self.record_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.record_path, "a", encoding="utf-8") as fh:
            fh.write(text + "\n")

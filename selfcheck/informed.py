import json
import os
import re
import threading
import time
from pathlib import Path

CONDITIONS = ("unassisted", "informed")
RELAY_DIR = "/selfcheck/relay"
REDACTED = "[REDACTED]"
_REQUEST_RE = re.compile(r"^req-(\d+)\.json$")
_RESPONSE_RE = re.compile(r"^resp-(\d+)\.json$")
_IDENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_DJANGO_ID_RE = re.compile(r"^(\S.*?) \(([\w.]+)\)$")
_DIFF_HEADER_RE = re.compile(r"^diff --git a/(.+?) b/(.+)$", re.MULTILINE)
_DEFINITION_RE = re.compile(r"^[+-]\s*(?:async\s+)?(?:def|class)\s+([A-Za-z_]\w*)")
_LITERAL_RE = re.compile(r'"((?:[^"\\\n]|\\.)*)"|\'((?:[^\'\\\n]|\\.)*)\'')
_MIN_LITERAL = 3
_ASSERT_RE = re.compile(r"\bassert\b")


class ResponseFormatError(Exception):
    pass


def _first_line(exc: Exception) -> str:
    lines = str(exc).strip().splitlines()
    return lines[0] if lines else type(exc).__name__


def _test_names(test_id: str) -> set[str]:
    names = {test_id}
    if "::" in test_id:
        names.add(test_id.split("[", 1)[0].rsplit("::", 1)[-1])
    else:
        match = _DJANGO_ID_RE.match(test_id)
        if match:
            names.update(match.groups())
    return names


def _changed_lines(patch: str, signs: str) -> list[str]:
    return [
        ln for ln in patch.splitlines()
        if ln and ln[0] in signs and not ln.startswith(("+++", "---"))
    ]


def forbidden_terms(instance: dict) -> set[str]:
    terms: set[str] = set()
    for test_id in instance["FAIL_TO_PASS"]:
        terms |= _test_names(test_id)
    for patch in (instance["patch"], instance["test_patch"]):
        for match in _DIFF_HEADER_RE.finditer(patch):
            for path in match.groups():
                terms.add(path)
                terms.add(os.path.basename(path))
    for ln in _changed_lines(instance["patch"], "+-"):
        match = _DEFINITION_RE.match(ln)
        if match:
            terms.add(match.group(1))
    for ln in _changed_lines(instance["test_patch"], "+"):
        if not _ASSERT_RE.search(ln):
            continue
        for match in _LITERAL_RE.finditer(ln):
            literal = match.group(1) if match.group(1) is not None else match.group(2)
            # Whitespace-only literals would match nearly any text.
            if len(literal) >= _MIN_LITERAL and literal.strip():
                terms.add(literal)
    terms.discard("")
    return terms


def _occurs(term: str, text: str) -> bool:
    if _IDENT_RE.fullmatch(term):
        return re.search(rf"(?<![A-Za-z0-9_]){re.escape(term)}(?![A-Za-z0-9_])", text) is not None
    return term in text


def leaks(text: str, instance: dict, request: dict) -> list[str]:
    exempt_text = instance["problem_statement"]
    request_text = json.dumps(request, ensure_ascii=False)
    return sorted(
        t for t in forbidden_terms(instance)
        if _occurs(t, text) and t not in exempt_text and t not in request_text
    )


def _question_texts(request: dict) -> list[str]:
    texts = []
    for q in request.get("questions") or []:
        text = q.get("question") if isinstance(q, dict) else q
        if isinstance(text, str) and text not in texts:
            texts.append(text)
    return texts


def build_prompt(instance: dict, request: dict) -> str:
    if request.get("kind") == "idle":
        shape = '{"message": "<text to send, or null>", "gold_facts_used": ["<fact>", ...]}'
        what = "The harness went idle and presented the brief below for approval or correction."
    else:
        shape = (
            '{"answers": {"<question text>": "<answer, or null>"}, '
            '"gold_facts_used": ["<fact>", ...]}'
        )
        what = "The harness asked the questions below."
    return "\n\n".join([
        "You are the user who reported a software issue to a coding-agent harness. You also know "
        "the gold solution. Your role is to catch a wrong direction: when a recommendation or "
        "claim of the harness is wrong, say that it is wrong and what behavior is expected "
        "instead. You never hand over the solution.",
        f"## Issue\n{instance['problem_statement']}",
        f"## Gold patch\n{instance['patch']}",
        f"## Gold test patch\n{instance['test_patch']}",
        f"## FAIL_TO_PASS\n{json.dumps(instance['FAIL_TO_PASS'])}",
        f"## Request\n{what}\n{json.dumps(request, ensure_ascii=False, indent=1)}",
        "## Constraints\n"
        "- Answer only what was asked or presented for approval.\n"
        "- Speak only of observable behavior derivable from the FAIL_TO_PASS tests.\n"
        "- Never name tests, assert values, files, code, or node/API choices the request did not "
        "raise.\n"
        "- Return null when there is nothing to add; do not approve what you cannot judge.\n"
        "- Anything naming a test, file, code or assert literal is discarded before the harness "
        "sees it.\n"
        "Answer with a single JSON object and nothing else, shaped as "
        f"{shape}. List in gold_facts_used every fact from the gold material your answer relied on.",
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
    raise ResponseFormatError("no JSON object in reviewer output")


def parse_response(text: str, request: dict) -> dict:
    obj = _first_object(text)
    facts = obj.get("gold_facts_used", [])
    if not isinstance(facts, list) or not all(isinstance(f, str) for f in facts):
        raise ResponseFormatError("gold_facts_used must be a list of strings")
    if request.get("kind") == "idle":
        message = obj.get("message")
        if "message" not in obj or not (message is None or isinstance(message, str)):
            raise ResponseFormatError("message must be a string or null")
        return {"message": message, "gold_facts_used": facts}
    answers = obj.get("answers")
    if not isinstance(answers, dict):
        raise ResponseFormatError("answers must be an object")
    questions = _question_texts(request)
    unknown = [k for k in answers if k not in questions]
    if unknown:
        raise ResponseFormatError(f"unknown question key: {unknown[0]}")
    if not all(v is None or isinstance(v, str) for v in answers.values()):
        raise ResponseFormatError("answers values must be strings or null")
    return {"answers": {q: answers.get(q) for q in questions}, "gold_facts_used": facts}


def respond(instance: dict, request: dict, *, call_fn) -> tuple[dict, dict]:
    n, kind = request.get("n"), request.get("kind")
    started = time.monotonic()
    raw = parsed = error = None
    try:
        raw = call_fn(build_prompt(instance, request))
        parsed = parse_response(raw, request)
    except Exception as exc:
        error = _first_line(exc)
    found: dict[str, list[str]] = {}

    def clean(key: str, value):
        if value is None:
            return None
        terms = leaks(value, instance, request)
        if terms:
            found[key] = terms
            return None
        return value

    if kind == "idle":
        response = {"n": n, "message": clean("message", parsed["message"] if parsed else None)}
    else:
        given = parsed["answers"] if parsed else {}
        response = {
            "n": n,
            "answers": {q: clean(q, given.get(q)) for q in _question_texts(request)},
        }
    record = {
        "n": n, "kind": kind, "request": request, "raw_output": raw, "parsed": parsed,
        "leaks": found, "sent": response,
        "gold_facts_used": parsed["gold_facts_used"] if parsed else [], "error": error,
        "elapsed_s": round(time.monotonic() - started, 3),
    }
    return response, record


class Relay:
    def __init__(
        self, container, instance: dict, record_path: Path, *, call_fn, poll_s: float, token: str,
        relay_dir: str = RELAY_DIR,
    ):
        self.container = container
        self.instance = instance
        self.record_path = Path(record_path)
        self.call_fn = call_fn
        self.poll_s = poll_s
        self.token = token
        self.relay_dir = relay_dir
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="informed-relay", daemon=True)
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

    def _listing(self) -> list[str]:
        _, out, _ = self.container.exec(["ls", "-1", self.relay_dir], user="nonroot")
        return out.split()

    def _poll(self) -> None:
        names = self._listing()
        self._handled |= {int(m.group(1)) for m in map(_RESPONSE_RE.match, names) if m}
        pending = sorted(
            int(m.group(1)) for m in map(_REQUEST_RE.match, names)
            if m and int(m.group(1)) not in self._handled
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
            response, row = respond(self.instance, {**request, "n": n}, call_fn=self.call_fn)
        except Exception as exc:
            self._append({
                "n": n, "kind": request.get("kind") if isinstance(request, dict) else None,
                "request": request, "raw_output": None, "parsed": None, "leaks": {},
                "sent": None, "gold_facts_used": [], "error": _first_line(exc), "elapsed_s": None,
            })
            return
        try:
            self._send(n, response)
        except Exception as exc:
            row["error"] = row["error"] or f"response write failed: {_first_line(exc)}"
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

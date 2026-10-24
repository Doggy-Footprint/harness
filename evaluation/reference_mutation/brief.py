import json
import os
import re

from . import section
from .languages import CFGTEST, parse_diff

CLOSING = "Implement this and add automated tests."
MIN_LITERAL = 3
_LITERAL_RE = re.compile(r'"((?:[^"\\\n]|\\.)*)"|\'((?:[^\'\\\n]|\\.)*)\'|`([^`\n]*)`')
_IDENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
# A lone dictionary-shaped word ("type", "value", "First") cannot reveal a test; forbidding it drops briefs that
# must name ordinary concepts. Compound identifiers, multi-word literals, paths and test names stay forbidden.
_PLAIN_WORD_RE = re.compile(r"[A-Za-z][a-z]*")
_ASSERT = {
    "python": re.compile(r"\bassert"),
    "typescript": re.compile(r"\b(expect|assert)\b"),
    "go": re.compile(r"\bt\.(Error|Fatal)|\bassert\.|\brequire\."),
    "rust": re.compile(r"\bassert"),
}
_DEFINITION = {
    "python": re.compile(r"^\s*(?:async\s+)?(?:def|class)\s+([A-Za-z_]\w*)"),
    "typescript": re.compile(
        r"^\s*(?:export\s+)?(?:async\s+)?(?:function\*?|class|const|let|var|interface|type|enum)\s+([A-Za-z_$][\w$]*)"
    ),
    "go": re.compile(r"^\s*(?:func\s+(?:\([^)]*\)\s*)?|type\s+|var\s+|const\s+)([A-Za-z_]\w*)"),
    "rust": re.compile(r"^\s*(?:pub(?:\([^)]*\))?\s+)?(?:async\s+|const\s+|unsafe\s+)*(?:fn|struct|enum|trait|type|const|static|mod)\s+([A-Za-z_]\w*)"),
}
_SYMBOL_RE = re.compile(
    r"(?:def|class|function\*?|const|let|var|interface|type|enum|fn|struct|trait|func|mod|static)\s+(?:\([^)]*\)\s*)?([A-Za-z_$][\w$]*)"
)


class BriefFormatError(ValueError):
    pass


def _added_lines(diff: str):
    for sec in parse_diff(diff):
        for hunk in sec.hunks:
            yield sec.path, hunk, [(t, s) for t, s in hunk.ops]


def _gather(rows: list[tuple[str, str]], start: int, done) -> str:
    parts = []
    for tag, text in rows[start:start + 12]:
        if tag != "+":
            break
        parts.append(text.strip())
        if done(text.rstrip()):
            break
    return " ".join(parts)


def _brace_or_semicolon(line: str) -> bool:
    return "{" in line or line.endswith(";")


def _trim(signature: str, cut: tuple[str, ...]) -> str:
    for token in cut:
        pos = signature.find(token)
        if pos != -1:
            signature = signature[:pos]
    return signature.strip()


def _python_signatures(path: str, hunk, rows) -> list[dict]:
    out = []
    hint = hunk.hint.strip()
    for k, (tag, text) in enumerate(rows):
        m = re.match(r"^(\s*)(?:async\s+def|def|class)\s+([A-Za-z]\w*)", text)
        if tag != "+" or not m:
            continue
        indent = len(m.group(1).expandtabs(4))
        if indent:
            owner = None
            for t2, s2 in reversed(rows[:k]):
                if t2 != "-" and s2.strip() and len(s2) - len(s2.lstrip()) < indent:
                    owner = s2.strip()
                    break
            owner = owner if owner is not None else hint
            if not owner.startswith("class "):
                continue
        joined = _gather(rows, k, lambda line: line.endswith(":"))
        out.append({"path": path, "signature": joined.rstrip(":").strip()})
    return out


def _typescript_signatures(path: str, hunk, rows) -> list[dict]:
    out = []
    decl = re.compile(
        r"^export\s+(?:default\s+)?(?:declare\s+)?(?:abstract\s+)?(?:async\s+)?"
        r"(?:function\*?|class|const|let|var|interface|type|enum)\b"
    )
    for k, (tag, text) in enumerate(rows):
        if tag == "+" and decl.match(text.strip()):
            joined = _gather(rows, k, _brace_or_semicolon)
            sig = _trim(joined, ("{",)).rstrip(";").strip()
            out.append({"path": path, "signature": sig})
    return out


def _go_signatures(path: str, hunk, rows) -> list[dict]:
    out = []
    decl = re.compile(r"^(?:func\s+(?:\([^)]*\)\s*)?[A-Z]\w*|type\s+[A-Z]\w*)")
    for k, (tag, text) in enumerate(rows):
        if tag == "+" and decl.match(text):
            out.append({"path": path, "signature": _trim(_gather(rows, k, _brace_or_semicolon), ("{",))})
    return out


def _rust_signatures(path: str, hunk, rows) -> list[dict]:
    out = []
    decl = re.compile(
        r"^\s*pub\s+(?:async\s+|const\s+|unsafe\s+)*(?:fn|struct|enum|trait|type|const|static|mod)\s+\w+"
    )
    for k, (tag, text) in enumerate(rows):
        if tag == "+" and decl.match(text):
            joined = _gather(rows, k, _brace_or_semicolon)
            out.append({"path": path, "signature": _trim(joined, ("{", ";", " where "))})
    return out


_SIGNATURES = {
    "python": _python_signatures,
    "typescript": _typescript_signatures,
    "go": _go_signatures,
    "rust": _rust_signatures,
}


def interface_signatures(language: str, src_diff: str) -> list[dict]:
    if language not in _SIGNATURES:
        raise ValueError(f"unsupported language: {language}")
    out, seen = [], set()
    for path, hunk, rows in _added_lines(src_diff):
        for item in _SIGNATURES[language](path, hunk, rows):
            key = (item["path"], item["signature"])
            if key not in seen and item["signature"]:
                seen.add(key)
                out.append(item)
    return out


def _test_names(test_id: str) -> set[str]:
    names = set()
    tail = test_id.rsplit("::", 1)[-1]
    tail = tail.split("[", 1)[0].split("(", 1)[0]
    for piece in tail.split("/"):
        piece = piece.strip()
        if piece:
            names.add(piece)
    return names


def _diff_added(diff: str) -> list[str]:
    return [s for sec in parse_diff(diff) for h in sec.hunks for t, s in h.ops if t == "+"]


def _literals(line: str):
    for m in _LITERAL_RE.finditer(line):
        yield next(g for g in m.groups() if g is not None)


def _public_text(task: dict) -> str:
    # Asserted literals already in the pull request text or the interface signatures are the user's own
    # words, not test leakage; short common words such as "read" or "body" otherwise drop most briefs.
    sigs = interface_signatures(task["language"], (task.get("gold_split") or {}).get("src", ""))
    return "\n".join([task.get("title", ""), task.get("body", ""), *(task.get("issue_bodies") or []), json.dumps(sigs)])


def forbidden_terms(task: dict) -> set[str]:
    language = task["language"]
    split = task.get("gold_split") or {}
    tests_diff, src_diff = split.get("tests", ""), split.get("src", "")
    terms: set[str] = set()
    for test_id in task.get("f2p", []):
        terms |= _test_names(test_id)
    for sec in parse_diff(tests_diff):
        path = sec.path.replace(CFGTEST, "")
        terms.add(path)
        terms.add(os.path.basename(path))
    asserting = _ASSERT[language]
    public = _public_text(task)
    for line in _diff_added(tests_diff):
        if not asserting.search(line):
            continue
        for literal in _literals(line):
            literal = literal.strip()
            if (len("".join(literal.split())) >= MIN_LITERAL and not _PLAIN_WORD_RE.fullmatch(literal)
                    and not _occurs(literal, public)):
                terms.add(literal)
    defined_in_src = {
        m.group(1) for line in _diff_added(src_diff) if (m := _DEFINITION[language].match(line))
    }
    for line in _diff_added(tests_diff):
        m = _DEFINITION[language].match(line)
        if m and m.group(1) not in defined_in_src and not _PLAIN_WORD_RE.fullmatch(m.group(1)):
            terms.add(m.group(1))
    sha = task.get("merge_sha")
    if sha:
        terms |= {sha, sha[:7]}
    terms.discard("")
    return terms


def _occurs(term: str, text: str) -> bool:
    if _IDENT_RE.fullmatch(term):
        return re.search(rf"(?<![A-Za-z0-9_]){re.escape(term)}(?![A-Za-z0-9_])", text) is not None
    return term in text


def leaks(text: str, task: dict) -> list[str]:
    return sorted(t for t in forbidden_terms(task) if _occurs(t, text))


def build_prompt(task: dict) -> str:
    sigs = interface_signatures(task["language"], (task.get("gold_split") or {}).get("src", ""))
    issues = "\n\n".join(task.get("issue_bodies") or []) or "(none)"
    f2p = json.dumps(task.get("f2p", []))
    return "\n\n".join([
        "You write the task brief for an evaluation of coding agents. A simulated user will hand the "
        "request below to the agent and answer its questions from the intent card.",
        f"## Pull request title\n{task.get('title', '')}",
        f"## Pull request body\n{task.get('body', '')}",
        f"## Linked issues\n{issues}",
        f"## Interface signatures (path and signature)\n{json.dumps(sigs, indent=1)}",
        f"## Gold test diff\n{(task.get('gold_split') or {}).get('tests', '')}",
        f"## Failing-to-passing test ids\n{f2p}",
        "## Output\n"
        "Answer with a single JSON object and nothing else, shaped as "
        '{"request": "...", "statements": [{"id": "S1", "text": "...", "f2p": ["<test id>"]}], '
        '"ambiguous": ["S2"]}.\n'
        "- request: 3 to 12 English sentences in the voice of a user. It names every interface "
        "signature above together with its path, ends with the exact sentence "
        f'"{CLOSING}", and leaves out the behavior of the 1 or 2 statements listed in ambiguous (ambiguous is empty when there is a single statement).\n'
        "- statements: observable behaviors, each mapped to at least one test id; together they cover "
        "every test id.\n"
        "- Never mention test names, test file paths, test-only helper names or literal values "
        "asserted by the tests.",
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
    raise BriefFormatError("no JSON object in brief output")


def _sentences(text: str) -> int:
    return len([s for s in re.split(r"(?<=[.!?])\s+", text.strip()) if s.strip()])


def _symbol(signature: str) -> str:
    m = _SYMBOL_RE.search(signature)
    return m.group(1) if m else signature


def parse_brief(text: str, task: dict) -> dict:
    obj = _first_object(text)
    request = obj.get("request")
    if not isinstance(request, str) or not request.strip():
        raise BriefFormatError("request must be a non-empty string")
    if not request.strip().endswith(CLOSING):
        raise BriefFormatError(f'request must end with "{CLOSING}"')
    if not 3 <= _sentences(request) <= 12:
        raise BriefFormatError("request must have 3 to 12 sentences")
    for sig in interface_signatures(task["language"], (task.get("gold_split") or {}).get("src", "")):
        if sig["path"] not in request or _symbol(sig["signature"]) not in request:
            raise BriefFormatError(f"request must name {sig['signature']} and {sig['path']}")
    raw = obj.get("statements")
    if not isinstance(raw, list) or not raw:
        raise BriefFormatError("statements must be a non-empty list")
    f2p_all = set(task.get("f2p", []))
    statements, covered, ids = [], set(), []
    for k, item in enumerate(raw, start=1):
        if not isinstance(item, dict):
            raise BriefFormatError("statement must be an object")
        sid, stext, ids_f2p = item.get("id"), item.get("text"), item.get("f2p")
        if not isinstance(sid, str) or not re.fullmatch(r"S\d+", sid) or sid in ids:
            raise BriefFormatError(f"statement id must be unique S<n>: {sid!r}")
        if not isinstance(stext, str) or not stext.strip():
            raise BriefFormatError(f"{sid}: text must be a non-empty string")
        if not isinstance(ids_f2p, list) or not ids_f2p or not all(isinstance(x, str) for x in ids_f2p):
            raise BriefFormatError(f"{sid}: f2p must list at least one test id")
        unknown = [x for x in ids_f2p if x not in f2p_all]
        if unknown:
            raise BriefFormatError(f"{sid}: unknown f2p id {unknown[0]}")
        ids.append(sid)
        covered |= set(ids_f2p)
        statements.append({"id": sid, "text": stext, "f2p": list(ids_f2p)})
    if covered != f2p_all:
        raise BriefFormatError("statements must cover every f2p id")
    ambiguous = obj.get("ambiguous")
    allowed = (0, 0) if len(ids) == 1 else (1, 2)
    if (
        not isinstance(ambiguous, list) or not allowed[0] <= len(ambiguous) <= allowed[1]
        or not all(isinstance(a, str) and a in ids for a in ambiguous)
    ):
        raise BriefFormatError(
            "ambiguous must be empty for a single statement, otherwise list 1 or 2 statement ids"
        )
    return {"request": request, "statements": statements, "ambiguous": list(ambiguous)}


def make_brief(task: dict, *, call_fn, cfg: dict) -> dict:
    bcfg = section(cfg, "brief")
    attempts_max = bcfg.get("attempts", 3)
    base_prompt = build_prompt(task)
    note, reason, attempt = "", "format", 0
    while attempt < attempts_max:
        attempt += 1
        raw = call_fn(
            base_prompt + note, model=bcfg.get("model", "claude-opus-5-5"),
            effort=bcfg.get("effort", "medium"), timeout_s=bcfg.get("timeout_s", 900),
        )
        try:
            brief = parse_brief(raw, task)
        except BriefFormatError as exc:
            reason, note = "format", f"\n\n## Previous output rejected\n{exc}"
            continue
        text = brief["request"] + "\n" + "\n".join(s["text"] for s in brief["statements"])
        found = leaks(text, task)
        if found:
            reason = "leak"
            note = "\n\n## Previous output rejected\nIt contained forbidden terms: " + ", ".join(found)
            continue
        return {**brief, "attempts": attempt, "status": "ok", "reason": "ok"}
    return {"attempts": attempt, "status": "dropped", "reason": reason}

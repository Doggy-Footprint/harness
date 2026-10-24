import hashlib
import json
import re

from . import section
from .languages import parse_diff

SMELLS = (
    "assertion_roulette", "conditional_test_logic", "eager_test", "empty_test", "exception_handling",
    "magic_number", "mystery_guest", "redundant_assertion", "sensitive_equality", "sleepy_test",
    "unknown_test", "duplicate_assert", "ignored_test",
)
DESIDERATA_JUDGED = (
    "isolated", "composable", "readable", "behavioral", "structure_insensitive", "specific",
    "predictive", "writable",
)
LEVELS = ("covered", "partial", "none")
PAIRS = (("H", "B0"), ("H", "Bplus"), ("Bplus", "B0"))
_HEX_ID = re.compile(r"\b[0-9a-f]{16}\b")


class JudgeFormatError(ValueError):
    pass


def _entry_key(entry: dict) -> str:
    return entry.get("key") or f"{entry.get('arm')}-r{entry.get('repeat')}"


def _entry_text(entry: dict) -> str:
    for name in ("text", "tests", "tests_diff"):
        if isinstance(entry.get(name), str):
            return entry[name]
    return ""


def candidates(task: dict, entries: list[dict], seed: int) -> list[dict]:
    pool = [
        {"source": _entry_key(e), "text": _entry_text(e)}
        for e in sorted(entries, key=_entry_key) if e.get("status") == "completed"
    ]
    pool.append({"source": "human", "text": (task.get("gold_split") or {}).get("tests", "")})
    pool.sort(key=lambda c: hashlib.sha256(f"{seed}:{task['task_id']}:{c['source']}".encode()).hexdigest())
    return [{"label": f"T{k + 1}", **c} for k, c in enumerate(pool)]


_SPEC_ROW = re.compile(r"^\|\s*([A-Za-z][A-Za-z0-9_.-]*\d[A-Za-z0-9_.-]*)\s*\|")


def spec_ids(harness_diff: str) -> set[str]:
    ids = set()
    for sec in parse_diff(harness_diff):
        if not sec.path.startswith("agent-docs/specs/"):
            continue
        for hunk in sec.hunks:
            for tag, text in hunk.ops:
                m = _SPEC_ROW.match(text) if tag == "+" else None
                if m:
                    ids.add(m.group(1))
    return ids


def anonymize(text: str, spec_ids: set[str]) -> str:
    kept = [ln for ln in text.splitlines(keepends=True) if "agent-docs/" not in ln]
    out = _HEX_ID.sub("ID", "".join(kept))
    for sid in sorted(spec_ids, key=len, reverse=True):
        out = re.sub(rf"(?<![\w-]){re.escape(sid)}(?![\w-])", "ID", out)
    return out


def _context(brief: dict) -> str:
    statements = "\n".join(f"- {s['id']}: {s['text']}" for s in brief["statements"])
    return f"## User request\n{brief['request']}\n\n## Intent statements\n{statements}"


def build_absolute_prompt(task: dict, brief: dict, cand: dict) -> str:
    shape = {
        "smells": [{"smell": "<one of SMELLS>", "test": "<test name>", "quote": "<exact text from the tests>"}],
        "desiderata": {name: {"score": 3, "rationale": "...", "quote": "<exact text>"} for name in DESIDERATA_JUDGED},
        "coverage": {s["id"]: {"level": "covered|partial|none", "quote": "<exact text or empty>"} for s in brief["statements"]},
        "boundary": False,
        "error_path": False,
    }
    return "\n\n".join([
        "You review one automated test set for a software change. You do not know who wrote it.",
        _context(brief),
        f"## Tests ({cand['label']})\n{cand['text']}",
        "## Rubric\n"
        f"- smells (test-smell catalog): report only these names: {', '.join(SMELLS)}. Each finding names the test and quotes it.\n"
        f"- desiderata (Kent Beck's Test Desiderata): score each of {', '.join(DESIDERATA_JUDGED)} from 1 (poor) to 5 (excellent) with a rationale and a quote.\n"
        "- coverage (ISO/IEC/IEEE 29119-4 test design): for every intent statement give level covered, partial or none with a quote; "
        "set boundary true when boundary values are exercised and error_path true when error or invalid-input paths are exercised.\n"
        "Every quote must be copied exactly from the tests above.\n"
        "Answer with a single JSON object and nothing else, shaped as " + json.dumps(shape),
    ])


def _collapse(text: str) -> str:
    return " ".join(text.split())


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
    raise JudgeFormatError("no JSON object in judge output")


def _quote(value, haystack: str, where: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise JudgeFormatError(f"{where}: quote must be a string")
    if not value.strip():
        if allow_empty:
            return value
        raise JudgeFormatError(f"{where}: quote must not be empty")
    if _collapse(value) not in haystack:
        raise JudgeFormatError(f"{where}: quote not found in candidate text")
    return value


def parse_absolute(text: str, cand: dict, brief: dict) -> dict:
    obj = _first_object(text)
    haystack = _collapse(cand["text"])
    smells = obj.get("smells")
    if not isinstance(smells, list):
        raise JudgeFormatError("smells must be a list")
    out_smells = []
    for item in smells:
        if not isinstance(item, dict) or item.get("smell") not in SMELLS:
            raise JudgeFormatError(f"unknown smell: {item.get('smell') if isinstance(item, dict) else item!r}")
        if not isinstance(item.get("test"), str):
            raise JudgeFormatError("smell test must be a string")
        out_smells.append({"smell": item["smell"], "test": item["test"], "quote": _quote(item.get("quote"), haystack, item["smell"])})
    desiderata = obj.get("desiderata")
    if not isinstance(desiderata, dict) or set(desiderata) != set(DESIDERATA_JUDGED):
        raise JudgeFormatError(f"desiderata must be exactly {', '.join(DESIDERATA_JUDGED)}")
    out_d = {}
    for name in DESIDERATA_JUDGED:
        item = desiderata[name]
        score = item.get("score") if isinstance(item, dict) else None
        if isinstance(score, bool) or not isinstance(score, int) or not 1 <= score <= 5:
            raise JudgeFormatError(f"{name}: score must be an integer 1-5")
        if not isinstance(item.get("rationale"), str):
            raise JudgeFormatError(f"{name}: rationale must be a string")
        out_d[name] = {"score": score, "rationale": item["rationale"], "quote": _quote(item.get("quote", ""), haystack, name)}
    coverage = obj.get("coverage")
    ids = [s["id"] for s in brief["statements"]]
    if not isinstance(coverage, dict) or any(i not in coverage for i in ids):
        raise JudgeFormatError("coverage must list every intent statement")
    out_c = {}
    for sid in ids:
        item = coverage[sid]
        if not isinstance(item, dict) or item.get("level") not in LEVELS:
            raise JudgeFormatError(f"{sid}: level must be one of {', '.join(LEVELS)}")
        quote = item.get("quote") or ""
        _quote(quote, haystack, sid, allow_empty=item["level"] == "none")
        out_c[sid] = {"level": item["level"], "quote": quote}
    for flag in ("boundary", "error_path"):
        if not isinstance(obj.get(flag), bool):
            raise JudgeFormatError(f"{flag} must be a boolean")
    return {
        "label": cand["label"], "smells": out_smells, "desiderata": out_d, "coverage": out_c,
        "boundary": obj["boundary"], "error_path": obj["error_path"],
    }


def build_pairwise_prompt(task: dict, brief: dict, first: dict, second: dict) -> str:
    return "\n\n".join([
        "You compare two automated test sets for the same software change. You do not know who wrote them.",
        _context(brief),
        f"## First tests\n{first['text']}",
        f"## Second tests\n{second['text']}",
        "## Question\nWhich test set is better at checking that the change meets the intent statements "
        "(coverage of behaviors, boundaries and error paths, absence of test smells, clarity)? "
        'Answer with a single JSON object and nothing else: {"winner": "first" | "second" | "tie"}.',
    ])


def parse_pairwise(text: str) -> str:
    try:
        winner = _first_object(text).get("winner")
    except JudgeFormatError:
        winner = text.strip().strip('."\'').lower()
    if winner not in ("first", "second", "tie"):
        raise JudgeFormatError("winner must be first, second or tie")
    return winner


def combine_orders(ab: str, ba: str) -> str:
    if "tie" in (ab, ba):
        return "tie"
    a_wins_ab, a_wins_ba = ab == "first", ba == "second"
    if a_wins_ab and a_wins_ba:
        return "A"
    if not a_wins_ab and not a_wins_ba:
        return "B"
    return "inconsistent"


def _ask(call_fn, prompt: str, parse, jcfg: dict):
    last = None
    for _ in range(2):
        raw = call_fn(prompt, model=jcfg.get("model", "claude-opus-5-5"), effort=jcfg.get("effort", "medium"),
                      timeout_s=jcfg.get("timeout_s", 900))
        try:
            return parse(raw)
        except JudgeFormatError as exc:
            last = exc
    raise JudgeFormatError(str(last))


def judge_task(task: dict, entries: list[dict], *, call_fn, cfg: dict) -> dict:
    jcfg = section(cfg, "judge")
    brief = task["brief"]
    seed = jcfg.get("seed", 0)
    keys = {_entry_key(e) for e in entries}
    spec_ids = {_entry_key(e): set(e.get("spec_ids") or ()) | keys for e in entries}
    spec_ids["human"] = set(keys)
    cands = candidates(task, entries, seed)
    for cand in cands:
        cand["text"] = anonymize(cand["text"], spec_ids.get(cand["source"], set()))
    by_source = {c["source"]: c for c in cands}
    absolute: dict = {}
    for cand in sorted(cands, key=lambda c: c["label"]):
        try:
            absolute[cand["label"]] = _ask(
                call_fn, build_absolute_prompt(task, brief, cand), lambda t, c=cand: parse_absolute(t, c, brief), jcfg
            )
        except JudgeFormatError:
            absolute[cand["label"]] = "error"
    pairwise = []
    arm_entry = {(e.get("arm"), e.get("repeat")): e for e in entries if e.get("status") == "completed"}
    repeats = sorted({k[1] for k in arm_entry}, key=lambda r: (r is None, r))
    for repeat in repeats:
        for left, right in PAIRS:
            if (left, repeat) not in arm_entry or (right, repeat) not in arm_entry:
                continue
            a = by_source[_entry_key(arm_entry[(left, repeat)])]
            b = by_source[_entry_key(arm_entry[(right, repeat)])]
            row = {"pair": f"{left}-{right}", "repeat": repeat}
            for name, (x, y) in (("ab", (a, b)), ("ba", (b, a))):
                try:
                    row[name] = _ask(call_fn, build_pairwise_prompt(task, brief, x, y), parse_pairwise, jcfg)
                except JudgeFormatError:
                    row[name] = "error"
            row["outcome"] = "error" if "error" in (row["ab"], row["ba"]) else combine_orders(row["ab"], row["ba"])
            pairwise.append(row)
    return {"absolute": absolute, "pairwise": pairwise, "labels": {c["label"]: c["source"] for c in cands}}

"""Synthetic evidence builders for the review tests (spec e4d852bdd61ccf5b v1).

Shapes come from the spec text and from the Claude Code transcript format; nothing is derived from the
modules under test. Constants such as CATEGORIES are restated here so a wrong constant in the
implementation is caught rather than mirrored.
"""
import json
from pathlib import Path
from types import SimpleNamespace

from selfcheck.tests import m3_fakes as m

CATEGORIES = ("understanding", "ask_options", "recommendation_evidence", "spec_requirements")
VERDICTS = ("diverged", "consistent", "n/a")
MODEL, EFFORT, TIMEOUT_S = "claude-opus-5-5", "low", 900
TRANSCRIPT_DIR = "raw/claude/projects/-testbed"
UUID_A = "aaaaaaaa-0000-4000-8000-000000000001"
UUID_B = "bbbbbbbb-0000-4000-8000-000000000002"
TOKEN = "tok-" + "cd34" * 12
BAD_JSON_LINE = "this is { not json"

WRAP_CATEGORIES = True

INSTANCE = {
    "instance_id": "inst-1",
    "problem_statement": "PROBLEM-STATEMENT-MARK nitpick flags Literal values",
    "patch": "diff --git a/src/x.py b/src/x.py\n+GOLD-PATCH-MARK\n",
    "test_patch": "diff --git a/tests/t.py b/tests/t.py\n+GOLD-TESTPATCH-MARK\n",
    "FAIL_TO_PASS": ["tests/test_a.py::test_one", "tests/test_a.py::test_two"],
    "PASS_TO_PASS": ["tests/test_a.py::test_three"],
}


# -- transcript rows ---------------------------------------------------------------------------

def text_block(text):
    return {"type": "text", "text": text}


def thinking_block(text):
    return {"type": "thinking", "thinking": text}


def tool_block(name, **tool_input):
    return {"type": "tool_use", "id": "toolu_x", "name": name, "input": tool_input}


def ask_block(questions):
    return tool_block("AskUserQuestion", questions=questions)


def assistant(*blocks, sidechain=False):
    return {"type": "assistant", "isSidechain": sidechain,
            "message": {"role": "assistant", "content": list(blocks)}}


def user(text):
    return {"type": "user", "isSidechain": False,
            "message": {"role": "user", "content": [{"type": "text", "text": text}]}}


def questions(tag="q"):
    return [{"question": "Which %s?" % tag, "header": tag,
             "options": [{"label": "A-" + tag, "description": "first"}, {"label": "B-" + tag, "description": "second"}]}]


def default_rows():
    return [
        assistant(text_block("The issue is about Literal annotations.")),
        user("go ahead"),
        assistant(text_block("I will choose between two options."), ask_block(questions("opt"))),
    ]


# -- review model output -----------------------------------------------------------------------

def finding(summary="a finding", citation="[spec]", false_claim=False):
    return {"summary": summary, "citation": citation, "false_claim": false_claim}


def category(verdict="consistent", *findings):
    return {"verdict": verdict, "findings": list(findings)}


def payload(**over):
    cats = {name: category() for name in CATEGORIES}
    cats.update(over)
    return cats


def model_text(cats):
    return json.dumps({"categories": cats} if WRAP_CATEGORIES else cats)


def expected_parse(cats):
    return {"categories": cats}


D1_CATS = payload(
    understanding=category("diverged", finding("claims the gold keeps Literal as py:class", "[%s/%s.jsonl:1]" % (
        TRANSCRIPT_DIR, UUID_A), True)),
    recommendation_evidence=category("diverged", finding("recommendation lacks evidence", "[spec]", False)),
    spec_requirements=category("n/a"),
)
D1_FALSE_CLAIMS = [{"category": "understanding", "summary": D1_CATS["understanding"]["findings"][0]["summary"],
                    "citation": D1_CATS["understanding"]["findings"][0]["citation"]}]


# -- entries -----------------------------------------------------------------------------------

AUTO = m.AUTO


def make_entry(root, iid="inst-1", *, transcripts=AUTO, events=AUTO, diff=AUTO, empty_transcript_dir=False):
    """Entry dir <root>/<iid>/harness. transcripts: {file name: rows}; None omits raw/claude entirely."""
    if transcripts is AUTO:
        transcripts = {UUID_A + ".jsonl": default_rows()}
    raw_files = {}
    for name, rows in (transcripts or {}).items():
        raw_files[TRANSCRIPT_DIR + "/" + name] = rows if isinstance(rows, str) else m.jsonl_text(rows)
    entry = m.write_entry(root, iid, "harness", manifest={"instance_id": iid, "arm": "harness"}, events=events,
                          ledger=None, diff=diff, prediction_=m.prediction(iid), state=m.state(), raw_files=raw_files)
    if empty_transcript_dir:
        (entry / TRANSCRIPT_DIR).mkdir(parents=True, exist_ok=True)
    return entry


class FakeCall:
    """call_fn stand-in; `response` is a string, a callable(prompt), or an exception instance to raise."""

    def __init__(self, response):
        self.response = response
        self.prompts = []

    def __call__(self, prompt):
        self.prompts.append(prompt)
        response = self.response(prompt) if callable(self.response) else self.response
        if isinstance(response, BaseException):
            raise response
        return response

    @property
    def count(self):
        return len(self.prompts)


SCENARIOS = ("D1", "D2", "D3", "D4", "D5a", "D5b", "D6")


def scenario(name, root):
    """Build the entry for decision-table column `name`, snapshot the tree, run review_entry. Returns a namespace."""
    from selfcheck import review

    root = Path(root)
    run_dir = root / "run"
    kw = {}
    if name == "D1":
        call = FakeCall(model_text(D1_CATS))
    elif name == "D2":
        call = FakeCall(model_text(payload()))
    elif name == "D3":
        call = FakeCall(RuntimeError("claude exited 1\nsecond line of stderr"))
    elif name == "D4":
        call = FakeCall("I am unable to produce JSON, sorry")
    elif name in ("D5a", "D5b"):
        call = FakeCall(model_text(payload()))
        kw = {"transcripts": None, "empty_transcript_dir": name == "D5b"}
    elif name == "D6":
        call = FakeCall(model_text(payload(understanding=category("diverged", finding("leaked " + TOKEN)))))
    else:
        raise AssertionError(name)
    entry = make_entry(run_dir, **kw)
    m.write_text(entry / "process.json", json.dumps({"checks": {}, "marker": "process-before"}))
    m.write_text(run_dir / "scores.harness.jsonl", json.dumps({"instance_id": "inst-1", "marker": "score-before"}) + "\n")
    m.write_text(run_dir / "inst-1" / "baseline" / "prediction.json", json.dumps({"marker": "baseline"}))
    m.write_text(root / "elsewhere.txt", "outside the run dir")
    before = m.tree(root)
    result = review.review_entry(entry, dict(INSTANCE), call_fn=call, token=TOKEN, model=MODEL, effort=EFFORT)
    after = m.tree(root)
    return SimpleNamespace(root=root, entry=entry, call=call, result=result, before=before, after=after)

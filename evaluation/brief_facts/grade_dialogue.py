#!/usr/bin/env python3
import argparse
import json
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
SPEC_NAME = re.compile(r"^specs-[0-9a-f]{16}-[a-z0-9]+(?:-[a-z0-9]+)*\.md$")
FACT_NAME = re.compile(r"^facts-[0-9a-f]{16}-[a-z]+-[a-z0-9]+(?:-[a-z0-9]+)*\.md$")
FACT_KEYS = ("dimension:", "fact:", "source:", "asked for:", "re-check:")
SPEC_KEYS = ("version:", "run_id:", "status: draft", "base_commit:", "max_verifier_invocations:")

B = {"type": ["boolean", "null"]}
S = {"type": "string"}
VERDICT_SCHEMA = {
    "type": "object",
    "properties": {
        "answered_facts": {"type": "array", "items": {"type": "object", "properties": {
            "id": S, "answered": {"type": "boolean"},
            "after_answer": {"type": ["string", "null"], "enum": [
                "settled_cited", "settled_uncited", "user_decision", "re_asked", "ignored", "contradicted", None]},
            "evidence": S}, "required": ["id", "answered", "after_answer", "evidence"]}},
        "total_user_decisions": {"type": "integer"},
        "split_recommended": {"type": "boolean"},
        "late_fact_questions": {"type": "array", "items": {"type": "object", "properties": {
            "text": S, "repo_answers": {"type": "boolean"}}, "required": ["text", "repo_answers"]}},
        "decision_round": {"type": ["object", "null"], "properties": {
            "count": {"type": "integer"},
            "questions": {"type": "array", "items": {"type": "object", "properties": {
                "text": S, "has_options": B, "has_recommendation": B, "states_significance": B, "states_facts": B},
                "required": ["text", "has_options", "has_recommendation", "states_significance", "states_facts"]}}},
            "required": ["count", "questions"]},
        "options_reply": {"type": ["object", "null"], "properties": {
            "consequences": B, "recommendation": B, "evidence": S},
            "required": ["consequences", "recommendation", "evidence"]},
        "approval_brief": {"type": ["object", "null"], "properties": {
            "user_choices_with_own_pick": B, "picks_match_file": B, "own_picks_differ": {"type": "integer"},
            "asks_basis_when_differs": B, "decided_items_with_reason": B,
            "plain_quality": B, "evidence": S},
            "required": ["user_choices_with_own_pick", "picks_match_file", "own_picks_differ", "asks_basis_when_differs", "decided_items_with_reason",
                         "plain_quality", "evidence"]},
        "spec": {"type": "object", "properties": {
            "brief_in_spec": {"type": "boolean"}, "missing_from_spec": {"type": "array", "items": S}},
            "required": ["brief_in_spec", "missing_from_spec"]},
        "contradictions": {"type": "array", "items": {"type": "object", "properties": {
            "quote": S, "against": S}, "required": ["quote", "against"]}},
        "seeded_facts": {"type": "array", "items": {"type": "object", "properties": {
            "file": S, "shown_as_assumption": {"type": "boolean"}, "re_asked": {"type": "boolean"},
            "mentioned": {"type": "boolean"}}, "required": ["file", "shown_as_assumption", "re_asked", "mentioned"]}},
        "notes": S,
    },
    "required": ["answered_facts", "total_user_decisions", "split_recommended", "late_fact_questions",
                 "decision_round", "options_reply", "approval_brief", "spec", "contradictions", "seeded_facts", "notes"],
}


def judge(case: dict, run_dir: Path, model: str) -> dict:
    outputs = run_dir / "outputs"
    files = "\n\n".join(f"=== {path.name} ===\n{path.read_text(encoding='utf-8')}"
                        for path in sorted(outputs.glob("*.md")) if path.name != "dialogue.md")
    prompt = (
        (HERE / "dialogue_grader.md").read_text(encoding="utf-8")
        + "\n\n# CASE\n" + json.dumps(case, ensure_ascii=False, indent=1)
        + "\n\n# DIALOGUE\n" + (outputs / "dialogue.md").read_text(encoding="utf-8")
        + "\n\n# FILES THE AGENT WROTE\n" + (files or "(none)")
        + "\n\nReturn only the JSON object."
    )
    command = ["claude", "-p", "--model", model, "--tools", "", "--no-session-persistence",
               "--strict-mcp-config", "--setting-sources", "project", "--disable-slash-commands",
               "--output-format", "json", "--json-schema", json.dumps(VERDICT_SCHEMA)]
    done = subprocess.run(command, input=prompt, capture_output=True, text=True, cwd=run_dir, timeout=900)
    reply = json.loads(done.stdout)
    (run_dir / "judge_cost.json").write_text(json.dumps({"cost_usd": reply.get("total_cost_usd") or 0}),
                                             encoding="utf-8")
    data = reply.get("structured_output")
    if isinstance(data, dict) and set(data) == {"answer"} and isinstance(data["answer"], str):
        data = json.loads(data["answer"])
    if not data:
        text = reply.get("result") or ""
        data = json.loads(text[text.find("{"): text.rfind("}") + 1])
    return data


def file_checks(case: dict, run_dir: Path) -> dict:
    outputs = run_dir / "outputs"
    specs = sorted(outputs.glob("specs-*.md"))
    facts = sorted(outputs.glob("facts-*.md"))
    spec_ok = len(specs) == 1 and bool(SPEC_NAME.match(specs[0].name)) and all(
        key in specs[0].read_text(encoding="utf-8").split("\n---", 1)[0] for key in SPEC_KEYS)
    bad_facts = [path.name for path in facts if not FACT_NAME.match(path.name)
                 or not all(key in path.read_text(encoding="utf-8") for key in FACT_KEYS)]
    turns = json.loads((run_dir / "transcript.json").read_text(encoding="utf-8"))
    first = next((turn for turn in turns if turn["role"] == "agent"), {"tools": []})
    picks_turn = round_turn = None
    agent_index = 0
    for position, turn in enumerate(turns):
        if turn["role"] != "agent":
            continue
        agent_index += 1
        wrote = any(tool["name"] in ("Write", "Edit") and "picks" in json.dumps(tool.get("input") or {})
                    and "/scratch/" in json.dumps(tool.get("input") or {}) for tool in turn["tools"])
        if wrote and picks_turn is None:
            picks_turn = agent_index
        following = turns[position + 1] if position + 1 < len(turns) else {}
        if following.get("stage") == "decision" and round_turn is None:
            round_turn = agent_index
    seeded = {fact["file"]: fact.get("relevant", False) for fact in case.get("seed_facts", [])}
    read = set()
    listed = False
    for tool in first["tools"]:
        text = json.dumps(tool.get("input") or {})
        if "facts" not in text:
            continue
        if tool["name"] == "Read":
            read.update(name for name in seeded if name in text)
        elif tool["name"] == "Glob":
            listed = True
    return {
        "spec_files": [path.name for path in specs],
        "spec_ok": spec_ok,
        "facts_written": len(facts),
        "bad_facts": bad_facts,
        "seeded_listed": listed,
        "picks_turn": picks_turn,
        "round_turn": round_turn,
        "unrelated_read": sorted(name for name in read if not seeded[name]),
    }


def expectations(case: dict, meta: dict, verdict: dict, checks: dict) -> list[dict]:
    rows = []

    def add(text: str, passed: bool, evidence: str) -> None:
        rows.append({"text": text, "passed": bool(passed), "evidence": evidence or "none"})

    answered = [item for item in verdict.get("answered_facts", []) if item.get("answered")]
    bad = [item for item in answered if item.get("after_answer") in ("re_asked", "ignored", "contradicted")]
    add("Uses every answered fact without re-asking, ignoring, or contradicting it", not bad,
        "; ".join(f"{item['id']} {item['after_answer']}: {item.get('evidence', '')}" for item in bad))
    uncited = [item for item in answered if item.get("after_answer") == "settled_uncited"]
    add("Cites the user's answer for each decision it settles", not uncited,
        "; ".join(f"{item['id']}: {item.get('evidence', '')}" for item in uncited))

    rnd = verdict.get("decision_round") or {}
    questions = rnd.get("questions") or []
    with_options = [q["text"] for q in questions if q.get("has_options")]
    with_rec = [q["text"] for q in questions if q.get("has_recommendation")]
    thin = [q["text"] for q in questions if not (q.get("states_significance") and q.get("states_facts"))]
    add("Decision round names no options", not with_options, "; ".join(with_options) or ("no round" if not rnd else ""))
    add("Decision round implies no recommendation", not with_rec, "; ".join(with_rec))
    add("Each user decision says why it matters and what facts it rests on", not thin, "; ".join(thin))
    total = verdict.get("total_user_decisions") or rnd.get("count") or len(questions)
    add("Recommends a split when more than 3 decisions in the whole dialogue are the user's",
        total <= 3 or verdict.get("split_recommended"),
        f"{total} decisions, split_recommended={verdict.get('split_recommended')}")
    late = verdict.get("late_fact_questions") or []
    late_repo = [q["text"] for q in late if q.get("repo_answers")]
    add("Asks no later fact question the repository answers", not late_repo, "; ".join(late_repo))

    options = verdict.get("options_reply")
    if options:
        add("Options on request carry consequences and no recommendation",
            options.get("consequences") and not options.get("recommendation"), options.get("evidence", ""))

    add("Reaches the approval brief within eight agent turns", meta.get("reached_approval"),
        f"agent turns {meta.get('agent_turns')}, error {meta.get('error')}")
    brief = verdict.get("approval_brief")
    if brief:
        add("Approval brief shows its own pick next to each user decision",
            brief.get("user_choices_with_own_pick") is not False, brief.get("evidence", ""))
        add("Approval brief reports the picks recorded before the user answered",
            brief.get("picks_match_file") is True, f"own picks differing from the user: {brief.get('own_picks_differ')}")
        add("Approval brief gives a reason and a way back for each decided item",
            brief.get("decided_items_with_reason"), brief.get("evidence", ""))
    if checks["round_turn"] is not None:
        add("Writes its own picks to the scratchpad before the first decision round is sent",
            checks["picks_turn"] is not None and checks["picks_turn"] <= checks["round_turn"],
            f"picks written in agent turn {checks['picks_turn']}, decision round in agent turn {checks['round_turn']}")
    add("Writes one draft spec at agent-docs/specs/<16 hex>-<name>.md with the required frontmatter",
        checks["spec_ok"], ", ".join(checks["spec_files"]) or "no spec file")
    spec = verdict.get("spec") or {}
    if checks["spec_files"]:
        add("Spec holds the contract, not the brief", not spec.get("brief_in_spec"), "")
        missing = spec.get("missing_from_spec") or []
        add("Spec reflects every user answer and decision", not missing, "; ".join(missing))
    add("Records each answered fact under agent-docs/facts/ in the fact format",
        checks["facts_written"] >= len(answered) and not checks["bad_facts"],
        f"{checks['facts_written']} files for {len(answered)} answered facts; malformed: {checks['bad_facts']}")
    contradictions = verdict.get("contradictions") or []
    add("States nothing that contradicts the hidden context or the user", not contradictions,
        "; ".join(f"{item.get('quote')} (against {item.get('against')})" for item in contradictions))

    if case.get("seed_facts"):
        seeded = {item.get("file"): item for item in verdict.get("seeded_facts") or []}
        relevant = [fact["file"] for fact in case["seed_facts"] if fact.get("relevant")]
        unrelated = [fact["file"] for fact in case["seed_facts"] if not fact.get("relevant")]
        add("Shows each relevant recorded fact as a dated assumption",
            all(seeded.get(name, {}).get("shown_as_assumption") for name in relevant),
            ", ".join(name for name in relevant if not seeded.get(name, {}).get("shown_as_assumption")))
        add("Does not ask again for a recorded fact",
            not any(seeded.get(name, {}).get("re_asked") for name in relevant),
            ", ".join(name for name in relevant if seeded.get(name, {}).get("re_asked")))
        add("Mentions no unrelated recorded fact",
            not any(seeded.get(name, {}).get("mentioned") for name in unrelated),
            ", ".join(name for name in unrelated if seeded.get(name, {}).get("mentioned")))
        add("Finds recorded facts by search, without listing or opening unrelated ones",
            not checks["seeded_listed"] and not checks["unrelated_read"],
            f"listed={checks['seeded_listed']}, unrelated read={checks['unrelated_read']}")
    return rows


def grade_run(run_dir: Path, case: dict, model: str, force: bool) -> tuple[Path, dict]:
    target = run_dir / "dialogue_judgement.json"
    if force or not target.exists():
        target.write_text(json.dumps(judge(case, run_dir, model), ensure_ascii=False, indent=2), encoding="utf-8")
    verdict = json.loads(target.read_text(encoding="utf-8"))
    meta = json.loads((run_dir / "meta.json").read_text(encoding="utf-8"))
    checks = file_checks(case, run_dir)
    rows = expectations(case, meta, verdict, checks)
    passed = sum(row["passed"] for row in rows)
    rnd = verdict.get("decision_round") or {}
    metrics = {
        "decision_count": verdict.get("total_user_decisions") or rnd.get("count") or 0,
        "late_fact_questions": len(verdict.get("late_fact_questions") or []),
        "contradictions": len(verdict.get("contradictions") or []),
        "facts_written": checks["facts_written"],
        "agent_turns": meta.get("agent_turns"),
        "own_picks_differ": (verdict.get("approval_brief") or {}).get("own_picks_differ"),
        "agent_cost_usd": meta.get("agent_cost_usd"),
    }
    (run_dir / "grading.json").write_text(json.dumps({
        "expectations": rows,
        "summary": {"passed": passed, "failed": len(rows) - passed, "total": len(rows),
                    "pass_rate": round(passed / len(rows), 3) if rows else 0},
        "metrics": metrics,
        "notes": verdict.get("notes", ""),
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    return run_dir, {"rows": rows, "metrics": metrics}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("iteration", type=Path)
    parser.add_argument("--cases", type=Path, default=HERE / "cases")
    parser.add_argument("--model", default="sonnet")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--jobs", type=int, default=6)
    args = parser.parse_args()

    work = []
    for meta in sorted(args.iteration.glob("eval-*/*/run-*/meta.json")):
        run_dir = meta.parent
        case_id = run_dir.parent.parent.name.removeprefix("eval-")
        case = json.loads((args.cases / f"{case_id}.json").read_text(encoding="utf-8"))
        work.append((run_dir, case))
    with ThreadPoolExecutor(args.jobs) as pool:
        results = list(pool.map(lambda item: grade_run(item[0], item[1], args.model, args.force), work))
    table: dict[tuple[str, str], list[dict]] = {}
    for run_dir, result in results:
        key = (run_dir.parent.parent.name, run_dir.parent.name)
        table.setdefault(key, []).append(result)
    for (case_id, config), runs in sorted(table.items()):
        print(f"\n{case_id} / {config} ({len(runs)} runs)")
        texts = [row["text"] for row in runs[0]["rows"]]
        for text in texts:
            hits = [row["passed"] for run in runs for row in run["rows"] if row["text"] == text]
            print(f"  {sum(hits)}/{len(hits)}  {text}")
        for key in runs[0]["metrics"]:
            values = [run["metrics"][key] for run in runs]
            print(f"  {key}: {values}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
import argparse
import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
S = {"type": "string"}
NULLABLE_BOOL = {"type": ["boolean", "null"]}
SCHEMA = {
    "type": "object",
    "properties": {
        "unknowns": {"type": "array", "items": {"type": "object", "properties": {
            "id": S,
            "status": {"type": "string", "enum": ["asked", "assumed", "decided", "dismissed", "absent"]},
            "form": {"type": ["string", "null"], "enum": ["fact", "decision", None]},
            "evidence": S}, "required": ["id", "status", "form", "evidence"]}},
        "questions": {"type": "array", "items": {"type": "object", "properties": {
            "text": S, "targets": {"type": "array", "items": S},
            "form": {"type": "string", "enum": ["fact", "decision"]},
            "recommendation": {"type": "boolean"}, "useful": NULLABLE_BOOL},
            "required": ["text", "targets", "form", "recommendation", "useful"]}},
        "decisions_as_assumptions": {"type": "array", "items": S},
        "invitation_examples": NULLABLE_BOOL,
        "notes": S,
    },
    "required": ["unknowns", "questions", "decisions_as_assumptions", "invitation_examples", "notes"],
}


def judge(run_dir: Path, case: dict, model: str) -> None:
    prompt = (
        (HERE / "grader.md").read_text(encoding="utf-8")
        + "\n\n# CASE\n" + json.dumps(case, ensure_ascii=False, indent=1)
        + "\n\n# MESSAGE (outputs/output.md)\n" + (run_dir / "outputs" / "output.md").read_text(encoding="utf-8")
        + "\n\nReturn only the JSON object."
    )
    command = ["claude", "-p", "--model", model, "--tools", "", "--no-session-persistence",
               "--strict-mcp-config", "--setting-sources", "project", "--disable-slash-commands",
               "--output-format", "json", "--json-schema", json.dumps(SCHEMA)]
    done = subprocess.run(command, input=prompt, capture_output=True, text=True, cwd=run_dir, timeout=900)
    reply = json.loads(done.stdout)
    (run_dir / "judgement.json").write_text(
        json.dumps(reply["structured_output"], ensure_ascii=False, indent=2), encoding="utf-8")
    (run_dir / "judge_cost.json").write_text(
        json.dumps({"cost_usd": reply.get("total_cost_usd") or 0}), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("iteration", type=Path)
    parser.add_argument("--cases", type=Path, default=HERE / "cases")
    parser.add_argument("--model", default="sonnet")
    parser.add_argument("--jobs", type=int, default=8)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    work = []
    for output in sorted(args.iteration.glob("eval-*/*/run-*/outputs/output.md")):
        run_dir = output.parent.parent
        if (run_dir / "judgement.json").exists() and not args.force:
            continue
        case_id = run_dir.parent.parent.name.removeprefix("eval-")
        work.append((run_dir, json.loads((args.cases / f"{case_id}.json").read_text(encoding="utf-8"))))
    with ThreadPoolExecutor(args.jobs) as pool:
        list(pool.map(lambda item: judge(item[0], item[1], args.model), work))
    print(f"judged {len(work)} runs")
    return 0


if __name__ == "__main__":
    sys.exit(main())

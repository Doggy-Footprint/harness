#!/usr/bin/env python3
import argparse
import json
import subprocess
import sys
from pathlib import Path

STOP_RULE = (
    "The user invoked the workflow-approach skill for the request in ARGUMENTS; follow the skill. "
    "This session ends at the first point where the skill makes you wait for the user's reply: "
    "output, as your final answer, the complete message you would send to the user at that point. "
    "Your read-only tools are enough to reach that point."
)


def skill_body(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    if text.startswith("---\n"):
        text = text.split("\n---\n", 1)[1]
    return text.lstrip("\n")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skill", required=True, type=Path)
    parser.add_argument("--case", required=True, type=Path)
    parser.add_argument("--repo", required=True, type=Path)
    parser.add_argument("--run-dir", required=True, type=Path)
    parser.add_argument("--model", default="haiku")
    parser.add_argument("--effort")
    parser.add_argument("--timeout", default=900, type=int)
    args = parser.parse_args()

    case = json.loads(args.case.read_text(encoding="utf-8"))
    prompt = (
        "<command-message>workflow-approach</command-message>\n"
        "<command-name>/workflow-approach</command-name>\n"
        f"<command-args>{case['task']}</command-args>\n\n"
        f"{skill_body(args.skill)}\n\nARGUMENTS: {case['task']}\n"
    )
    outputs = args.run_dir / "outputs"
    outputs.mkdir(parents=True, exist_ok=True)
    meta_path = args.run_dir / "meta.json"
    command = [
        "claude", "-p", "--model", args.model, "--tools", "Read,Grep,Glob",
        "--strict-mcp-config", "--setting-sources", "project", "--disable-slash-commands",
        "--no-session-persistence", "--output-format", "json", "--append-system-prompt", STOP_RULE,
    ]
    if args.effort:
        command += ["--effort", args.effort]
    try:
        done = subprocess.run(command, input=prompt, capture_output=True, text=True,
                              cwd=args.repo, timeout=args.timeout)
    except subprocess.TimeoutExpired:
        meta_path.write_text(json.dumps({"error": "timeout"}), encoding="utf-8")
        return 3
    try:
        reply = json.loads(done.stdout)
    except json.JSONDecodeError:
        meta_path.write_text(
            json.dumps({"error": "no json", "stdout": done.stdout[-2000:], "stderr": done.stderr[-2000:]}),
            encoding="utf-8")
        return 1
    (outputs / "output.md").write_text(reply.get("result") or "", encoding="utf-8")
    meta = {key: reply.get(key) for key in ("is_error", "num_turns", "duration_ms", "total_cost_usd", "usage", "modelUsage")}
    meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    usage = reply.get("usage") or {}
    tokens = sum(usage.get(key) or 0 for key in (
        "input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens"))
    duration = reply.get("duration_ms") or 0
    (args.run_dir / "timing.json").write_text(json.dumps({
        "total_tokens": tokens, "duration_ms": duration, "total_duration_seconds": round(duration / 1000, 1),
    }), encoding="utf-8")
    return 1 if reply.get("is_error") else 0


if __name__ == "__main__":
    sys.exit(main())

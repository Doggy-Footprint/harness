#!/usr/bin/env python3
import argparse
import json
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

from run_model import skill_body

STOP_RULE = (
    "The user invoked the workflow-approach skill for the request in ARGUMENTS; follow the skill. "
    "Each of your turns ends at the next point where the skill makes you wait for the user's reply: "
    "output, as your final answer, the complete message you would send to the user at that point. "
    "Your tools are read tools plus Write and Edit for the files the skill tells you to write. "
    "This checkout has no .harness/ scripts: treat every script step as done and do not mention it. "
    "Records the skill looks for that do not exist are empty. "
    "The session ends once you have presented the approval brief: do not mark the spec active, "
    "dispatch subagents, or implement anything. "
    "Your session scratchpad directory is {scratch}."
)

USER_RULES = """You play the user of a coding agent in a Korean-speaking team. You own this product and know the facts under HIDDEN CONTEXT; you know nothing else about the code. Reply in short, plain Korean, as a busy engineer would.

Classify the agent's latest message and write your reply:
- understanding: the agent restates the task and asks fact questions and/or lists assumptions. Answer every question it asks, using only HIDDEN CONTEXT; when HIDDEN CONTEXT does not say, answer "모르겠어" or "상관없어". Correct any stated assumption, or any line naming what it did not ask about, that HIDDEN CONTEXT contradicts, giving the true fact. Volunteer nothing else. If it invites you to list decisions you want to make yourself, answer as instructed under INVITATION.
- decision: the agent asks you to make design decisions. If OPTIONS_REQUESTED is false, reply exactly "각 결정마다 선택지를 보여줘." Otherwise make every decision it asks for, each with one short reason, as the owner of HIDDEN CONTEXT would.
- options: the agent lists options for decisions you have to make. Make every decision, each with one short reason, as the owner of HIDDEN CONTEXT would.
- approval: the agent presents a finished spec or approval brief and asks for approval. Set done to true; reply "".
- other: anything else (a question about whether you know a concept, a conflict, a request to confirm). Answer briefly as the owner of HIDDEN CONTEXT would; if it asks whether you know a concept, say you know it only roughly.

Never ask the agent for its recommendation."""

USER_SCHEMA = json.dumps({
    "type": "object",
    "properties": {
        "stage": {"type": "string", "enum": ["understanding", "decision", "options", "approval", "other"]},
        "reply": {"type": "string"},
        "done": {"type": "boolean"},
    },
    "required": ["stage", "reply", "done"],
})


def run_claude(command: list[str], prompt: str, cwd: Path, timeout: int) -> list[dict]:
    done = subprocess.run(command, input=prompt, capture_output=True, text=True, cwd=cwd, timeout=timeout)
    events = []
    for line in done.stdout.splitlines():
        line = line.strip()
        if line.startswith("{"):
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    if not any(event.get("type") == "result" for event in events):
        raise RuntimeError(f"no result event: {done.stderr[-1500:]}")
    return events


def agent_turn(events: list[dict]) -> dict:
    tools = []
    for event in events:
        if event.get("type") != "assistant":
            continue
        for block in event.get("message", {}).get("content", []):
            if block.get("type") == "tool_use":
                tools.append({"name": block.get("name"), "input": block.get("input")})
    result = next(event for event in events if event.get("type") == "result")
    return {
        "role": "agent",
        "text": result.get("result") or "",
        "tools": tools,
        "cost_usd": result.get("total_cost_usd") or 0,
        "duration_ms": result.get("duration_ms") or 0,
        "is_error": bool(result.get("is_error")),
    }


def simulate_user(case: dict, turns: list[dict], options_requested: bool, model: str, cwd: Path) -> dict:
    history = "\n\n".join(f"[{turn['role']}]\n{turn['text']}" for turn in turns)
    invitation = case.get("user_named_decision") or "답하지 않는다(언급하지 않음)."
    prompt = (
        f"{USER_RULES}\n\nHIDDEN CONTEXT:\n" + "\n".join(f"- {line}" for line in case["hidden_context"])
        + f"\n\nINVITATION: {invitation}\nOPTIONS_REQUESTED: {str(options_requested).lower()}\n\n"
        f"YOUR ORIGINAL REQUEST: {case['task']}\n\nCONVERSATION SO FAR:\n{history}\n"
    )
    command = ["claude", "-p", "--model", model, "--tools", "", "--no-session-persistence",
               "--strict-mcp-config", "--setting-sources", "project", "--disable-slash-commands",
               "--output-format", "json", "--json-schema", USER_SCHEMA]
    done = subprocess.run(command, input=prompt, capture_output=True, text=True, cwd=cwd, timeout=600)
    reply = json.loads(done.stdout)
    data = reply.get("structured_output") or json.loads(reply.get("result") or "{}")
    data["cost_usd"] = reply.get("total_cost_usd") or 0
    return data


def copy_written(workdir: Path, scratch: Path, outputs: Path, seeded: set[str]) -> None:
    for path in sorted(scratch.glob("*")):
        if path.is_file():
            shutil.copyfile(path, outputs / f"scratch-{path.name}")
    for sub in ("specs", "facts"):
        source = workdir / "agent-docs" / sub
        if not source.is_dir():
            continue
        for path in sorted(source.glob("*.md")):
            if f"{sub}/{path.name}" in seeded:
                continue
            target = outputs / f"{sub}-{path.name}"
            shutil.copyfile(path, target)


def write_dialogue(outputs: Path, turns: list[dict]) -> None:
    parts = []
    for index, turn in enumerate(turns, 1):
        header = f"## {index}. {'agent' if turn['role'] == 'agent' else 'user'}"
        if turn["role"] == "user":
            header += f" (stage seen: {turn.get('stage')})"
        parts.append(f"{header}\n\n{turn['text']}\n")
    (outputs / "dialogue.md").write_text("\n".join(parts), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skill", required=True, type=Path)
    parser.add_argument("--case", required=True, type=Path)
    parser.add_argument("--repo", required=True, type=Path)
    parser.add_argument("--run-dir", required=True, type=Path)
    parser.add_argument("--model", default="sonnet")
    parser.add_argument("--effort", default="low")
    parser.add_argument("--user-model", default="sonnet")
    parser.add_argument("--max-agent-turns", default=8, type=int)
    parser.add_argument("--timeout", default=1200, type=int)
    args = parser.parse_args()

    case = json.loads(args.case.read_text(encoding="utf-8"))
    run_dir = args.run_dir.resolve()
    outputs = run_dir / "outputs"
    outputs.mkdir(parents=True, exist_ok=True)
    workdir = run_dir / "repo"
    if workdir.exists():
        shutil.rmtree(workdir)
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=args.repo, capture_output=True, text=True,
                          check=True).stdout.strip()
    subprocess.run(["git", "clone", "-q", "--shared", "--no-checkout", str(args.repo.resolve()), str(workdir)],
                   check=True)
    subprocess.run(["git", "checkout", "-q", head], cwd=workdir, check=True)

    seeded = set()
    for fact in case.get("seed_facts", []):
        path = workdir / "agent-docs" / "facts" / fact["file"]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(fact["text"].rstrip("\n") + "\n", encoding="utf-8")
        seeded.add(f"facts/{fact['file']}")

    scratch = run_dir / "scratch"
    if scratch.exists():
        shutil.rmtree(scratch)
    scratch.mkdir()
    session = str(uuid.uuid4())
    base = ["claude", "-p", "--model", args.model, "--effort", args.effort,
            "--tools", "Read,Grep,Glob,Write,Edit", "--permission-mode", "acceptEdits",
            "--strict-mcp-config", "--setting-sources", "project", "--disable-slash-commands",
            "--add-dir", str(scratch), "--output-format", "stream-json", "--verbose",
            "--append-system-prompt", STOP_RULE.format(scratch=scratch)]
    prompt = (
        "<command-message>workflow-approach</command-message>\n"
        "<command-name>/workflow-approach</command-name>\n"
        f"<command-args>{case['task']}</command-args>\n\n"
        f"{skill_body(args.skill)}\n\nARGUMENTS: {case['task']}\n"
    )
    turns: list[dict] = [{"role": "user", "text": case["task"], "stage": "request"}]
    options_requested = False
    error = None
    for index in range(args.max_agent_turns):
        command = base + (["--session-id", session] if index == 0 else ["--resume", session])
        try:
            events = run_claude(command, prompt, workdir, args.timeout)
        except (RuntimeError, subprocess.TimeoutExpired) as failure:
            error = str(failure)
            break
        turns.append(agent_turn(events))
        try:
            user = simulate_user(case, turns, options_requested, args.user_model, workdir)
        except (json.JSONDecodeError, subprocess.TimeoutExpired) as failure:
            error = f"user simulation: {failure}"
            break
        if user["done"] or user["stage"] == "approval":
            turns.append({"role": "user", "text": "(승인 단계 도달: 종료)", "stage": user["stage"],
                          "cost_usd": user["cost_usd"]})
            break
        if user["stage"] == "decision" and not options_requested:
            options_requested = True
        turns.append({"role": "user", "text": user["reply"], "stage": user["stage"], "cost_usd": user["cost_usd"]})
        prompt = user["reply"]

    copy_written(workdir, scratch, outputs, seeded)
    write_dialogue(outputs, turns)
    (run_dir / "transcript.json").write_text(json.dumps(turns, ensure_ascii=False, indent=2), encoding="utf-8")
    agent = [turn for turn in turns if turn["role"] == "agent"]
    duration = sum(turn["duration_ms"] for turn in agent)
    meta = {
        "error": error,
        "agent_turns": len(agent),
        "reached_approval": any(turn.get("stage") == "approval" for turn in turns),
        "agent_cost_usd": round(sum(turn["cost_usd"] for turn in agent), 4),
        "user_cost_usd": round(sum(turn.get("cost_usd", 0) for turn in turns if turn["role"] == "user"), 4),
    }
    (run_dir / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    (run_dir / "timing.json").write_text(json.dumps({
        "total_tokens": 0, "duration_ms": duration, "total_duration_seconds": round(duration / 1000, 1),
    }), encoding="utf-8")
    return 1 if error else 0


if __name__ == "__main__":
    sys.exit(main())

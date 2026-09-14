"""Renders Claude/Codex agent and hook config text from the single-source
harness/ files. Kept import-only (no side effects) so a later installer can
call these functions directly.
"""
import json
import re

FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n\n(.*)$", re.DOTALL)

CLAUDE_FIELD_ORDER = [
    ("tools", "claude.tools"),
    ("disallowedTools", "claude.disallowedTools"),
    ("model", "claude.model"),
    ("effort", "claude.effort"),
]

CODEX_FIELD_ORDER = [
    ("model", "codex.model"),
    ("model_reasoning_effort", "codex.model_reasoning_effort"),
]


def parse_agent_source(text: str):
    match = FRONTMATTER_RE.match(text)
    if not match:
        raise ValueError("agent source missing frontmatter")
    fields = {}
    for line in match.group(1).splitlines():
        key, _, value = line.partition(": ")
        fields[key] = value
    return fields, match.group(2)


def render_claude_agent_md(fields: dict, body: str) -> str:
    lines = ["---", f"name: {fields['name']}", f"description: {fields['description']}"]
    for out_key, in_key in CLAUDE_FIELD_ORDER:
        if in_key in fields:
            lines.append(f"{out_key}: {fields[in_key]}")
    lines.append("---")
    lines.append("")
    return "\n".join(lines) + "\n" + body


def render_codex_agent_toml(fields: dict, body: str) -> str:
    lines = [f'name = "{fields["name"]}"', f'description = "{fields["description"]}"']
    for out_key, in_key in CODEX_FIELD_ORDER:
        if in_key in fields:
            lines.append(f'{out_key} = "{fields[in_key]}"')
    lines.append(f'sandbox_mode = "{fields["codex.sandbox_mode"]}"')
    lines.append(f'developer_instructions = """\n{body}"""\n')
    return "\n".join(lines[:-1]) + "\n" + lines[-1]


def load_hooks_spec(spec_path) -> list:
    with open(spec_path, encoding="utf-8") as fh:
        return json.load(fh)["hooks"]


def _render_hooks_dict(hooks_spec: list, root_var: str, target: str) -> dict:
    result = {"hooks": {}}
    for entry in hooks_spec:
        if target not in entry.get("targets", ("claude", "codex")):
            continue
        event = entry["event"]
        hook = {"type": "command", "command": entry["command"].replace("{root}", root_var)}
        group = {"hooks": [hook]}
        if "matcher" in entry:
            group = {"matcher": entry["matcher"], "hooks": [hook]}
        result["hooks"].setdefault(event, []).append(group)
    return result


def render_claude_settings_hooks(hooks_spec: list) -> dict:
    return _render_hooks_dict(hooks_spec, "$CLAUDE_PROJECT_DIR", "claude")


def render_codex_hooks(hooks_spec: list) -> dict:
    return _render_hooks_dict(hooks_spec, "$(git rev-parse --show-toplevel)", "codex")

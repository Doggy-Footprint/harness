# Project Definition

AI agent harness for Claude Code, installable into any git repository.
Codex is unsupported: `.codex/` files are still generated best-effort, but Codex subagents inherit the parent session's sandbox, permissions, and MCP servers, so per-agent restrictions are enforced only in Claude Code.
It ships documentation rules (the managed block below), the workflow-approach skill and helper skills, sub-agents, agent hooks, git hooks, and a CI comment check.
Source: `harness/` (payload), `installer/harness.py` (install / update / doctor), `tests/`, `evaluation/` (archived harness evaluation experiments `selfcheck/` and `reference_mutation/`, not installed). This repo installs itself into `.harness/` for dogfooding.
Edit `harness/`, never `.harness/` or the generated `.claude/`, `.codex/`, `.agents/` files; then run `python3 installer/harness.py update . --no-commit` so the source and installed copy land in one commit. `update` MUST provide version-by-version migration steps.

<!-- harness:begin -->
@.harness/instructions/harness-block.md
<!-- harness:end -->

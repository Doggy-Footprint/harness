---
version: 4
---

# User Intent
| id | intention | goal to achieve |
|---|---|---|
| U1 | Harness hooks record structured workflow marker events | Analyzer identifies contract-workflow steps without inferring from transcripts |
| U2 | Markers go to one per-user file per repo | `~/.harness/telemetry/<repo-slug>.jsonl`, aggregatable across projects, outside the repo |
| U3 | Record existing hook points plus PostToolUse | subagent start/stop, gate block, Test command runs + exit code, seed.py runs + exit code, contract writes + version, handoff writes |
| U4 | Works for Claude Code and Codex | Same events from both; a field Codex does not provide is recorded as null, no Codex-specific tooling |
| U6 | Failed Test command / seed runs stay attributable | tool_failure carries the matched contract stem or seed action, so failures group with their contract |
| U7 | Missing payload values are uniformly null | empty-string agent_type (observed on real SubagentStop) is recorded as null |
| U5 | Telemetry never changes hook behavior | Write failures are swallowed; gate exit codes and stderr are unchanged |

# Paths
Implementation: harness/lib/telemetry.py, harness/hooks/telemetry_hook.py, harness/hooks/contract_gate.py, harness/hooks/hooks.spec.json, harness/VERSION, installer/harness.py
Tests: tests/test_telemetry.py
Test command: python3 -m unittest discover -s tests -p 'test_*.py'

# Signatures
harness/lib/telemetry.py: telemetry_file() -> pathlib.Path
harness/lib/telemetry.py: emit(payload: dict, event: str, **fields) -> None
harness/hooks/telemetry_hook.py: reads one hook payload JSON on stdin, emits events, always exits 0 with empty stdout
Env HARNESS_TELEMETRY_DIR overrides the directory `~/.harness/telemetry`.
repo-slug = resolved repo root path with every char outside [A-Za-z0-9] replaced by "-".
Event line (one JSON object per line, append-only):
  {"v": 1, "ts": <UTC ISO-8601>, "harness_version": <VERSION>, "repo": <repo root str>, "client": "claude"|"codex"|null, "session_id", "agent_id", "agent_type", "tool_use_id", "event": <kind>, ...kind fields}
  missing payload fields are null; agent_type "" is recorded as null. client: "codex" when transcript_path contains "/.codex/", "claude" when it contains "/.claude/", else null.
Kinds and fields:
  subagent_start: -
  subagent_stop: -
  gate_block: running (list of agent types, sorted)
  test_command: contract (contract file stem whose `Test command` matched), exit_code (int|null)
  exit_code is always null on Claude (real PostToolUse payload has no tool_response.exit_code). Claude success vs failure is the event kind: test_command/seed = succeeded, tool_failure = failed. Codex emits test_command/seed from PostToolUse for both zero and non-zero exits; exit_code is recorded when its payload supplies an integer.
  seed: action ("backup"|"restore"|"status"|other token|null), exit_code (int|null)
  contract_write: contract (file stem), version (int|null from frontmatter)
  handoff_write: file (file name)
  tool_failure: tool_name, error_code, contract (matched Test command file stem, else null), action (seed action as in seed, else null) (from PostToolUseFailure; only for Bash commands that match test_command or seed)
Hook registration (hooks.spec.json):
  PostToolUse, both targets, matcher covering Bash, Write, Edit (Claude) and Bash, apply_patch (Codex) -> telemetry_hook.py
  PostToolUseFailure, claude only, matcher Bash -> telemetry_hook.py
  SubagentStart/SubagentStop/PreToolUse stay on contract_gate.py, which also emits subagent_start / subagent_stop / gate_block.

harness/VERSION becomes 0.5.0; no MIGRATIONS entry is added (hook merge in update already covers it).

# Errors
none raised — every telemetry failure (unwritable dir, malformed payload, unreadable contract) is swallowed; hook exits as before.

# Cases
| id | level | input / state | expected result |
|---|---|---|---|
| C1 | normal | SubagentStart then SubagentStop payload for implementer, agent_id "a1" | two lines subagent_start, subagent_stop with agent_type implementer, agent_id a1; contract_gate exit 0 |
| C2 | normal | SubagentStart for a non-gated agent type (test-verifier) | subagent_start recorded (all agent types recorded, not only gated) |
| C3 | normal | contract with `Test command: python3 -m unittest`, PostToolUse Bash command "python3  -m unittest" with tool_response.exit_code 1 | test_command, contract = file stem, exit_code 1 |
| C4 | normal | PostToolUse Bash "python3 .harness/bin/seed.py backup src/a.py", exit_code 0 | seed, action backup, exit_code 0 |
| C5 | normal | PostToolUse Write to agent-docs/contracts/x.md whose frontmatter has version: 3 | contract_write, contract x, version 3 |
| C6 | normal | PostToolUse Write to agent-docs/handoff/0123456789abcdef-y.md | handoff_write, file 0123456789abcdef-y.md |
| C7 | normal | PreToolUse Bash Test command while implementer marker is running | gate_block with running ["implementer"]; exit code 2 and stderr unchanged from before |
| C8 | normal | Codex PostToolUse tool_name apply_patch, tool_input.command contains "*** Update File: agent-docs/contracts/x.md" | contract_write for x |
| C9 | boundary | PostToolUse Bash unrelated command ("ls") | no line written |
| C10 | boundary | PostToolUse Write to a non-contract, non-handoff path; and to agent-docs/handoff/index.md | no line written |
| C11 | boundary | tool_response has no exit_code (or is a string) | exit_code null |
| C12 | boundary | contract frontmatter lacks version | contract_write with version null |
| C13 | boundary | HARNESS_TELEMETRY_DIR unset | file path under ~/.harness/telemetry/<repo-slug>.jsonl (checked via telemetry_file with HOME overridden) |
| C14 | boundary | transcript_path under ~/.codex/ vs ~/.claude/ vs absent | client codex / claude / null |
| C15 | error | HARNESS_TELEMETRY_DIR points to an unwritable path (a regular file) | hook exits 0 (contract_gate keeps its own exit code), no exception trace in stderr |
| C16 | error | stdin not JSON | telemetry_hook exits 0, nothing written |
| C17 | edge | PostToolUseFailure Bash matching Test command, error_code "timeout" | tool_failure with tool_name Bash, error_code timeout |
| C18 | edge | two events appended | file has two lines, each valid JSON with v 1, harness_version equal to harness/VERSION |
| C19 | edge | installed repo hook configs | Claude settings has PostToolUse matching Bash/Write/Edit and PostToolUseFailure matching Bash -> telemetry_hook.py; Codex hooks.json has PostToolUse matching Bash/apply_patch, no PostToolUseFailure |
| C21 | normal | PostToolUseFailure Bash matching registered Test command of contract file x | tool_failure with contract x, action null |
| C22 | normal | PostToolUseFailure Bash "python3 .harness/bin/seed.py restore" | tool_failure with action restore, contract null |
| C23 | boundary | SubagentStop payload with agent_type "" | subagent_stop with agent_type null |
| C24 | boundary | SubagentStart payload with agent_type "" | subagent_start with agent_type null (rule is envelope-wide, all event kinds) |
| C25 | boundary | registered `Test command: python3 -m unittest`; PostToolUseFailure Bash "python3 -m unittest -k x" and "echo python3 -m unittest" | no tool_failure line (same exact normalized match as C9) |
| C20 | edge | `installer/harness.py update` from a 0.4.0 install | succeeds, manifest version = new VERSION, new hooks merged |
| C26 | edge | Codex PostToolUse Bash for a registered Test command exits non-zero | test_command is recorded; contract is the matching file stem and exit_code is the integer supplied by Codex, otherwise null |

# Version Log
## v4
- Codex PostToolUse matcher now covers Bash and apply_patch; non-zero Codex Bash runs remain test_command/seed events. Evidence: real Codex session recorded apply_patch but no Bash events with the apply_patch-only matcher; official Codex hook documentation says unified exec matches Bash and PostToolUse runs for non-zero exits.
## v3
- Added C24, C25. Evidence: verifier findings; seeds (agent_type normalized only for subagent_stop; substring match on PostToolUseFailure path) stayed green.
## v2
- tool_failure gains contract/action; agent_type "" -> null; exit_code documented always null on Claude. Evidence: real Claude session 2026-09-21: failed Test command produced only tool_failure (error_code null, no contract); successful test_command/seed had exit_code null; SubagentStop lines had agent_type "".
## v1
- Initial contract.

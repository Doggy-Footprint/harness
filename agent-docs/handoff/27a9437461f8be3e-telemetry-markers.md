# Harness telemetry marker hooks

## Goal
"Otel을 이용해서 하네스가 잘 작동하는지, 작동 워크플로우를 준수하는지, test-verifier/seed 등에서 실제로 문제를 잡아내는지, test-verifier에 의한 retry는 평균 몇 round 반복되고 handoff로 넘어가는 비율은 어떤지 서브 에이전트 등이 실행될 때 비용은 얼마나 드는지 등을 통계로 확인하고 싶어." Decisions: markers adopted; analyzer in `analytics/` (not in payload, separate contract, not started); markers written to `~/.harness/telemetry/<repo-slug>.jsonl`; events = existing hooks + PostToolUse; Claude and Codex both, fields Codex lacks are null; no Docker; VERSION 0.5.0 without MIGRATIONS entry. Work on branch `feat/harness-analytics`.

## State
- Branch: feat/harness-analytics, base commit 33be63b; work committed as 4f01f82; session 2 changes uncommitted.
- Changed: harness/VERSION, harness/hooks/contract_gate.py, harness/hooks/hooks.spec.json.
- Added: harness/lib/telemetry.py, harness/lib/hook_shared.py, harness/hooks/telemetry_hook.py, tests/test_telemetry.py.
- `python3 -m unittest discover -s tests -p 'test_*.py'`: 92 tests OK (session 2).
- `python3 installer/harness.py update .` run on this repo in session 2 (.harness/, .claude/settings.json, .codex/hooks.json, AGENTS.md updated).
- Contract-workflow stopped at Limit: round 2 used; the third verifier produced 2 findings confirmed by seed (suite stayed green):
  1. C19: the Claude `PostToolUseFailure` group's matcher is not asserted; widening `"Bash"` to `".*"` passes.
  2. C9/C3: no near-miss test against a registered Test command; substring matching instead of exact normalized matching passes.
- Unseeded verifier findings: malformed/unreadable contract file during parsing (Errors section) never exercised; C18/C20 read harness/VERSION dynamically so a missing 0.5.0 bump passes.

## Failed Attempts
| attempt | failure evidence | cause |
|---|---|---|
| Round 1: tests added for C19 PostToolUse matcher, C17 non-matching failure, C7 sorted running | Verifier 2 then found 4 more gaps; seeds for C17 seed-branch, C3 stem choice, C15 stderr stayed green | verified: each verifier pass audits the grown suite and finds adjacent uncovered combinations |
| Round 2: tests added for C17 seed branch, C3 two-contract stem, C15 byte-identical stderr | Verifier 3 found PostToolUseFailure matcher and near-miss Test command gaps; both seeds stayed green | verified: same as above |
| Round 3 (user-approved extra, main agent wrote tests): added C9 near-miss and C19 PostToolUseFailure Bash-only tests; seeds for both now fail | Verifier 4 found 4 gaps; seeds stayed green for: repo field emitted as null, seed action hardcoded to "backup", OSError from contract read re-raised | verified: envelope fields (ts, repo, session_id, tool_use_id), non-backup seed actions, and unreadable-contract path are never asserted |

## Seed Log
Each seed: `python3 .harness/bin/seed.py backup <file>`, inject, run the Test command, `seed.py restore` (all restores exited 0). "green" = suite passed with the defect = test gap confirmed.

| seed | file | injected defect | before fix | after fix |
|---|---|---|---|---|
| S1 | harness/hooks/hooks.spec.json | Claude PostToolUse matcher `Bash\|Write\|Edit` -> `Bash` | green | fails (round 1) |
| S2 | harness/hooks/telemetry_hook.py | PostToolUseFailure filter removed (tool_failure for any Bash) | green | fails (round 1) |
| S3 | harness/hooks/contract_gate.py | gate_block running not sorted (reversed marker order) | green | fails (round 1) |
| S4 | harness/hooks/telemetry_hook.py | seed branch dropped from PostToolUseFailure filter | green | fails (round 2) |
| S5 | harness/hooks/telemetry_hook.py | test_command contract = last-seen stem, not matched one | green | fails (round 2) |
| S6 | harness/lib/telemetry.py | swallowed write failure prints "telemetry write failed" to stderr | green | fails (round 2) |
| S7 | harness/hooks/hooks.spec.json | Claude PostToolUseFailure matcher `Bash` -> `.*` | green | fails (round 3) |
| S8 | harness/hooks/telemetry_hook.py | Test command matched by substring instead of exact normalized match | green | fails (round 3) |
| S9 | harness/lib/telemetry.py | `repo` emitted as null | green | fails (session 2) |
| S10 | harness/hooks/telemetry_hook.py | seed `action` hardcoded to "backup" | green | fails (session 2) |
| S11 | harness/hooks/telemetry_hook.py | OSError reading a contract re-raised in parse_contract_version | green | fails (session 2) |

## Next Step
Session 2 progress: step 1 done (tests added in tests/test_telemetry.py class TestEnvelopeAndActions, plus C18 VERSION == 0.5.0 and C20 pre-existing PostToolUse hook preserved; 92 tests OK; S9–S11 re-seeded and all fail). `python3 installer/harness.py update .` run on this repo (uncommitted). Remaining: step 2 real Claude/Codex session checks (needs a fresh session so the new hooks load), then commit.

User decision (after round 3): stop the verifier loop and resume in a new session with both of:
1. Close S9–S11: assert envelope fields ts/repo/session_id/tool_use_id on a PostToolUse-derived event; assert seed action for restore and status; make a contract file unreadable (chmod 000) during contract_write and assert the event is still recorded with version null and exit 0. Re-run S9–S11; each must now fail. Unseeded verifier-4 finding: C20 update should preserve pre-existing PostToolUse hooks.
2. Then run `python3 installer/harness.py update .` on this repo, start a real Claude session, and check `~/.harness/telemetry/<repo-slug>.jsonl` receives subagent_start/stop, test_command, seed, contract_write lines; check whether the real Claude PostToolUse Bash payload carries `tool_response.exit_code` (docs say yes, observed transcripts show failed Bash as error text). Same check in a Codex session.
After that, commit on feat/harness-analytics and start the separate `analytics/` analyzer contract.

Done in round 3 (kept for history): Continue test-implementer (fresh one if needed) with: C19 assert Claude PostToolUseFailure matcher fullmatches "Bash" and not "Write"/"Edit"; C9 with a registered `Test command: python3 -m unittest`, Bash `python3 -m unittest -k x` and `echo python3 -m unittest` write no test_command line. Then run the suite, fresh test-verifier, re-seed (matcher `.*`, substring match in telemetry_hook.handle_bash). Then run `python3 installer/harness.py update .`, check a real session writes markers, and check whether Claude's PostToolUse payload actually carries `tool_response.exit_code` for Bash.

## Open Questions
- Resolved: user approved one extra round (round 3), then chose to close S9–S11 and verify in a real session in a new session.
- Whether real Claude/Codex PostToolUse Bash payloads include exit_code (docs and observed transcripts disagree).

## Contract Snapshot
---
version: 1
---

# User Intent
| id | intention | goal to achieve |
|---|---|---|
| U1 | Harness hooks record structured workflow marker events | Analyzer identifies contract-workflow steps without inferring from transcripts |
| U2 | Markers go to one per-user file per repo | `~/.harness/telemetry/<repo-slug>.jsonl`, aggregatable across projects, outside the repo |
| U3 | Record existing hook points plus PostToolUse | subagent start/stop, gate block, Test command runs + exit code, seed.py runs + exit code, contract writes + version, handoff writes |
| U4 | Works for Claude Code and Codex | Same events from both; a field Codex does not provide is recorded as null, no Codex-specific tooling |
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
  missing payload fields are null. client: "codex" when transcript_path contains "/.codex/", "claude" when it contains "/.claude/", else null.
Kinds and fields:
  subagent_start: -
  subagent_stop: -
  gate_block: running (list of agent types, sorted)
  test_command: contract (contract file stem whose `Test command` matched), exit_code (int|null)
  seed: action ("backup"|"restore"|"status"|other token|null), exit_code (int|null)
  contract_write: contract (file stem), version (int|null from frontmatter)
  handoff_write: file (file name)
  tool_failure: tool_name, error_code (from PostToolUseFailure; only for Bash commands that match test_command or seed)
Hook registration (hooks.spec.json):
  PostToolUse, both targets, matcher covering Bash, Write, Edit (Claude) and apply_patch (Codex) -> telemetry_hook.py
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
| C19 | edge | installed repo hook configs | Claude settings has PostToolUse and PostToolUseFailure -> telemetry_hook.py; Codex hooks.json has PostToolUse, no PostToolUseFailure |
| C20 | edge | `installer/harness.py update` from a 0.4.0 install | succeeds, manifest version = new VERSION, new hooks merged |

# Version Log
## v1
- Initial contract.

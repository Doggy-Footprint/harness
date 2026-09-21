# Harness telemetry marker hooks

## Goal
"Otel을 이용해서 하네스가 잘 작동하는지, 작동 워크플로우를 준수하는지, test-verifier/seed 등에서 실제로 문제를 잡아내는지, test-verifier에 의한 retry는 평균 몇 round 반복되고 handoff로 넘어가는 비율은 어떤지 서브 에이전트 등이 실행될 때 비용은 얼마나 드는지 등을 통계로 확인하고 싶어." Decisions: markers adopted; analyzer in `analytics/` (not in payload, separate contract, not started); markers written to `~/.harness/telemetry/<repo-slug>.jsonl`; events = existing hooks + PostToolUse; Claude and Codex both, fields Codex lacks are null; no Docker; VERSION 0.5.0 without MIGRATIONS entry. Work on branch `feat/harness-analytics`.

## State
- Branch: feat/harness-analytics. Session 3 work (contract v3, tests, `installer/harness.py update .` applied to this repo) is committed; see `git log -1`.
- `python3 -m unittest discover -s tests -p 'test_*.py'`: 107 tests OK.
- Real Claude session check done (session 3): contract_write, test_command, seed, tool_failure lines written to `~/.harness/telemetry/-Users-hwansu-tools-harness.jsonl` with client "claude". Observed: Claude PostToolUse Bash payload has no tool_response.exit_code (always null); a failed Bash fires only PostToolUseFailure; SubagentStop sent agent_type "". Compound commands (`cd x && <test command>`) are not matched (by design, C9).
- User decisions (session 3): tool_failure gains contract/action; keep exit_code, documented always null on Claude (success/failure = event kind); agent_type "" -> null for every event kind.
- Claude side closed. Known test gaps accepted by user as open issues (not fixed): S18, S19 (see Seed Log).

## Failed Attempts
| attempt | failure evidence | cause |
|---|---|---|
| Round 1: tests added for C19 PostToolUse matcher, C17 non-matching failure, C7 sorted running | Verifier 2 then found 4 more gaps; seeds for C17 seed-branch, C3 stem choice, C15 stderr stayed green | verified: each verifier pass audits the grown suite and finds adjacent uncovered combinations |
| Round 2: tests added for C17 seed branch, C3 two-contract stem, C15 byte-identical stderr | Verifier 3 found PostToolUseFailure matcher and near-miss Test command gaps; both seeds stayed green | verified: same as above |
| Round 3 (user-approved extra, main agent wrote tests): added C9 near-miss and C19 PostToolUseFailure Bash-only tests; seeds for both now fail | Verifier 4 found 4 gaps; seeds stayed green for: repo field emitted as null, seed action hardcoded to "backup", OSError from contract read re-raised | verified: envelope fields (ts, repo, session_id, tool_use_id), non-backup seed actions, and unreadable-contract path are never asserted |

| Session 3 round 1: added C24 (SubagentStart "" -> null), C25 (failure-path near-miss) after S12/S13 stayed green | Verifier found failure-path action partition and non-subagent agent_type "" uncovered (S14/S15 green) | verified: each verifier pass finds adjacent uncovered combinations |
| Session 3 round 2: added C24 tests for test_command/tool_failure, C22 action partition status/token/none; S12-S15 now fail | Verifier found agent_type "" untested for seed/contract_write/handoff_write/gate_block, and C21 tested only alpha-then-beta order (S16/S17 green) | verified: same as above |
| Session 3 extra round (user-approved): added C24 tests for seed/contract_write/handoff_write/gate_block, C21 beta-then-alpha; S16/S17 now fail | Verifier found failure-path whitespace normalization and in-script tool_name=="Bash" guard untested (S18/S19 green) | verified: same as above |

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
| S12 | harness/lib/telemetry.py | agent_type "" -> null only for subagent_stop | green | fails (session 3 r1) |
| S13 | harness/hooks/telemetry_hook.py | PostToolUseFailure test command matched by substring | green | fails (session 3 r1) |
| S14 | harness/lib/telemetry.py | agent_type "" -> null only for subagent_* events | green | fails (session 3 r2) |
| S15 | harness/hooks/telemetry_hook.py | tool_failure action only for backup/restore | green | fails (session 3 r2) |
| S16 | harness/lib/telemetry.py | agent_type "" -> null only for subagent_start/stop, test_command, tool_failure | green | fails (session 3 extra) |
| S17 | harness/hooks/telemetry_hook.py | tool_failure contract = last registered contract when any matches | green | fails (session 3 extra) |
| S18 | harness/hooks/telemetry_hook.py | PostToolUseFailure command not whitespace-normalized | green | open |
| S19 | harness/hooks/telemetry_hook.py | tool_name == "Bash" guard removed in handle_post_tool_use_failure | green | open |

## Next Step
Resume in Codex, in this repo on feat/harness-analytics:
1. Confirm Codex loads the hooks: `.codex/hooks.json` must have PostToolUse -> `.harness/hooks/telemetry_hook.py` (installed by update).
2. In the Codex session, create a probe contract `agent-docs/contracts/zz-telemetry-probe.md` via apply_patch with frontmatter `version: 2` and a line `Test command: python3 -c "import sys; sys.exit(0)"`. Then run as separate, standalone commands (no `cd ... &&` prefix): `python3 -c "import sys; sys.exit(0)"`, then change the probe to exit 3 and run `python3 -c "import sys; sys.exit(3)"`, then `python3 .harness/bin/seed.py status`.
3. Inspect the last lines of `~/.harness/telemetry/-Users-hwansu-tools-harness.jsonl`. Check: client is "codex"; contract_write from apply_patch has contract zz-telemetry-probe, version 2; whether test_command/seed exit_code is populated on Codex; whether a failed Bash (exit 3) still produces a test_command line (Codex has no PostToolUseFailure hook, so a failure may produce no line at all); whether agent_type/agent_id/tool_use_id are populated.
4. Delete the probe contract. If Codex results contradict the contract (e.g. failed Bash yields no event), report to the user and propose a contract amendment; do not decide it.
5. Then start the separate `analytics/` analyzer contract (outside `harness/` payload).

## Open Questions
- Codex: is exit_code present in PostToolUse Bash payload; does a failed Bash fire PostToolUse.
- Open issue S18 (accepted): PostToolUseFailure command whitespace normalization is not tested (`python3  -m unittest` double-space).
- Open issue S19 (accepted): the in-script `tool_name == "Bash"` guard in handle_post_tool_use_failure is not tested (hook matcher already limits to Bash).
- Resolved (session 3): real Claude PostToolUse has no exit_code; failed Bash fires only PostToolUseFailure.

## Contract Snapshot
---
version: 3
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
  exit_code is always null on Claude (real PostToolUse payload has no tool_response.exit_code); success vs failure is the event kind: test_command/seed = succeeded, tool_failure = failed.
  seed: action ("backup"|"restore"|"status"|other token|null), exit_code (int|null)
  contract_write: contract (file stem), version (int|null from frontmatter)
  handoff_write: file (file name)
  tool_failure: tool_name, error_code, contract (matched Test command file stem, else null), action (seed action as in seed, else null) (from PostToolUseFailure; only for Bash commands that match test_command or seed)
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
| C21 | normal | PostToolUseFailure Bash matching registered Test command of contract file x | tool_failure with contract x, action null |
| C22 | normal | PostToolUseFailure Bash "python3 .harness/bin/seed.py restore" | tool_failure with action restore, contract null |
| C23 | boundary | SubagentStop payload with agent_type "" | subagent_stop with agent_type null |
| C24 | boundary | SubagentStart payload with agent_type "" | subagent_start with agent_type null (rule is envelope-wide, all event kinds) |
| C25 | boundary | registered `Test command: python3 -m unittest`; PostToolUseFailure Bash "python3 -m unittest -k x" and "echo python3 -m unittest" | no tool_failure line (same exact normalized match as C9) |
| C20 | edge | `installer/harness.py update` from a 0.4.0 install | succeeds, manifest version = new VERSION, new hooks merged |

# Version Log
## v3
- Added C24, C25. Evidence: verifier findings; seeds (agent_type normalized only for subagent_stop; substring match on PostToolUseFailure path) stayed green.
## v2
- tool_failure gains contract/action; agent_type "" -> null; exit_code documented always null on Claude. Evidence: real Claude session 2026-09-21: failed Test command produced only tool_failure (error_code null, no contract); successful test_command/seed had exit_code null; SubagentStop lines had agent_type "".
## v1
- Initial contract.

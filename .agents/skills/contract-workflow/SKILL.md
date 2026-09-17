---
name: contract-workflow
description: Contract-first implementation and test workflow with implementer, test-implementer, and test-verifier subagents. Use before feature/fix level implementation or debugging. Not for typo fixes, renames, config or doc edits, or local bug fixes.
---

# Contract

A contract is a session-scoped working file, not persisting documentation.

1. Location: `agent-docs/contracts/<kebab-case-name>.md`. Excluded from Index & Staleness Management: no `index.md`, `stale.md`, or `<hex-id>-` naming.
2. Hooks delete `agent-docs/contracts/` on the end of the session.
3. Only the main agent writes or amends a contract. Subagents read it and are given its path and version.
4. Amendment: bump `version`, append a Version Log entry, re-dispatch. Never edit a contract silently.
5. Format:

````
---
version: <n>
---

# User Intent
| id | intention | goal to achieve |

# Paths
Implementation: <comma-separated repo paths>
Tests: <comma-separated repo paths>
Test command: <one shell command that runs the full suite, including Tests>

# Signatures
<signature per line>

# Errors
<error type — raised when>

# Cases
| id | level | input / state | expected result |

# Version Log
## v<n>
- <what changed, and the evidence that forced the change>
````

6. Every intent item and case has an `id`. Tests, challenges, and verifier findings reference them.
7. `level` is one of `normal`, `boundary`, `error`, `edge`. Each level has at least one row. When a level cannot occur, write `| - | <level> | none — <reason> | - |`. An `error` row's expected result names a type from `# Errors` and the observable state after the failure.
8. `Implementation` and `Tests` are disjoint. `implementer` never reads `Tests`; `test-implementer` and `test-verifier` never read `Implementation`.
9. Before dispatch, confirm User Intent with the user. If an intent item is ambiguous or conflicts with another, ask the user; do not resolve it yourself.

# Subagent Model

Use the model and effort set in each agent definition (`.claude/agents/`, `.codex/agents/`). Override them only when the user names a model.

# Workflow

Contract before code. Implementation and tests both derive from the contract, never from each other.

1. **Ground (main).** Read the deciding source files yourself. Delegate only locating them (e.g. `code-explorer` returning `path:line`): signatures, types, and error types enter the contract only from lines you have read.
2. **Contract (main).** Write `agent-docs/contracts/<name>.md`, including `# Paths`. Confirm User Intent (Contract rule 9).
3. **Implement + Test (parallel).** Dispatch both on the same contract version without either agent's output. Each instruction is task-specific as well as complete:
   - `implementer`: contract path and version; implementation direction; critical constraints and risks; verification direction; and approaches excluded for this task.
   - `test-implementer`: contract path and version; existing test files that establish conventions; risk model; independent-oracle strategy; appropriate test level; verification direction; and approaches excluded for this task.
4. **Amend (main).** Wait until both have reported. For each challenge: amend the contract, or reject it with a reason. Never let a subagent resolve a gap. After an amendment, continue each existing subagent (Claude: `SendMessage`; Codex: its follow-up tool). Send a complete replacement instruction containing the current contract path and version, the applicable Version Log entry, the full role-specific direction from step 3, and the remaining assignment. It supersedes the earlier instruction; do not send only information to append. Spawn a fresh `implementer` or `test-implementer` only when the original cannot be continued.
5. **Reconcile (main).** Only after both subagents have reported on the same contract version, run `Test command` exactly as written. `.harness/hooks/contract_gate.py` blocks that exact command while either subagent is running. For each failing test, judge against the contract and User Intent, not against which side seems plausible:
   - implementation defect → continue `implementer` with a complete replacement instruction limited to the `id` and its expected result. Do not pass test code or assertion output.
   - test defect → continue `test-implementer` with a complete replacement instruction limited to the `id` and the reason. Do not pass implementation code.
   - contract gap → step 4.
6. **Verify (`test-verifier`).** Once the suite passes, spawn a fresh verifier and give it the contract path only. After any test correction, use another fresh verifier rather than continuing the previous one.
7. **Seed (main).** For the 2-3 strongest findings, one at a time:
   1. `python3 .harness/bin/seed.py backup <every file you will edit>`.
   2. Inject the finding's defect and run `Test command`.
   3. `python3 .harness/bin/seed.py restore`. If it exits non-zero, stop and report to the user. Never restore with `git checkout` or `git stash`: they discard the uncommitted implementation.

   While `.seed/` holds files, session cleanup keeps `agent-docs/contracts/`; `python3 .harness/bin/seed.py status` lists an unrestored seed.

   A suite that stays green confirms the finding.
8. **Close (main).**
   - confirmed → continue `test-implementer` with a complete replacement instruction limited to the `id` and defect class, not the injected diff. When it reports, run `Test command` on the restored implementation. A failure enters step 5; a pass enters step 7 only after step 6 runs with a fresh verifier, and the same seed must now fail.
   - not confirmed → drop.
   - `ambiguous contract` → step 4.
9. **Limit.** The first pass through steps 4-8 is free. Each later return to step 4 or 5 is one round; allow at most 2. If challenges, failing tests, or confirmed findings remain after that, stop, write a handoff per the Handoff Rule, and report to the user.
10. **Report (main).** Contract version, `id -> test` coverage map, each finding as confirmed / not confirmed / fixed, open challenges, blocked ids, and the handoff file path if one was written.

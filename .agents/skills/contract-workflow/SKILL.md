---
name: contract-workflow
description: Contract-first implementation and test workflow with implementer, test-implementer, and test-verifier subagents. Use this skill before feature/fix level implementation or debugging. Do not use for simple typo fixes, renames, config or doc edits, or local bug fixes that keep interfaces unchanged.
---

# Contract

A contract is a session-scoped working file, not documentation.

1. Location: `contracts/<kebab-case-name>.md`. This directory is excluded from Index & Staleness Management: no `index.md`, no `stale.md`, no `<hex-id>-` naming.
2. Lifetime is the session. Delete `contracts/` before the session ends.
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

# Edge Cases
| id | input / state | expected result |

# Version Log
## v<n>
- <what changed, and the evidence that forced the change>
````

6. Every intent item and edge case has an `id`. Tests, challenges, and verifier findings reference them.
7. `Implementation` and `Tests` are disjoint. `implementer` never reads `Tests`; `test-implementer` and `test-verifier` never read `Implementation`.
8. Before dispatch, confirm User Intent with the user. If an intent item is ambiguous or conflicts with another, ask the user; do not resolve it yourself.

# Subagent Model

Use the model and effort set in each agent definition (`.claude/agents/`, `.codex/agents/`). Override them only when the user names a model.

# Workflow

Contract before code. Implementation and tests both derive from the contract, never from each other.

1. **Ground (main).** The main agent reads the deciding source files itself. It may delegate locating them (e.g. `code-explorer` returning `path:line`), never reading them: signatures, types, and error types enter the contract only from lines the main agent has read, not from a subagent's summary.
2. **Contract (main).** Write `contracts/<name>.md`, including `# Paths`. Confirm User Intent (Contract rule 8).
3. **Implement + Test (parallel).** Dispatch both in one message on the same contract version. Neither prompt contains the other's output.
   - `implementer`: contract path and version.
   - `test-implementer`: contract path and version, and existing test files to take conventions from.
4. **Amend (main).** Wait until both have reported. For each challenge: amend the contract, or reject it with a reason. Never let a subagent resolve a gap. After an amendment, continue each existing subagent with the new version and its Version Log entry (Claude: `SendMessage`; Codex: its follow-up tool). Spawn a fresh one only when the original cannot be continued.
5. **Reconcile (main).** Only after both subagents have reported on the same contract version, run `Test command` exactly as written. `.agents/hooks/contract_gate.py` blocks that exact command while either subagent is running. For each failing test, judge against the contract and User Intent, not against which side seems plausible:
   - implementation defect → continue `implementer` with the `id` and its expected result. Do not pass test code or assertion output.
   - test defect → continue `test-implementer` with the `id` and the reason. Do not pass implementation code.
   - contract gap → step 4.
6. **Verify (`test-verifier`).** Once the suite passes. Give it the contract path only.
7. **Seed (main).** For the 2-3 strongest findings, one at a time:
   1. Copy every file you will edit to `contracts/.seed/<repo path>` and record its `sha256`.
   2. Inject the finding's defect and run `Test command`.
   3. Restore from `contracts/.seed/` and confirm each `sha256` matches. Never restore with `git checkout` or `git stash`: they discard the uncommitted implementation.

   A suite that stays green confirms the finding.
8. **Close (main).**
   - confirmed → continue `test-implementer` with the `id` and the defect class, not the injected diff. Then repeat step 7 for that defect; the suite must now fail.
   - not confirmed → drop.
   - `ambiguous contract` → step 4.
9. **Limit.** The first pass through steps 4-8 is free. Each later return to step 4 or 5 is one round; allow at most 2. If challenges, failing tests, or confirmed findings remain after that, stop and report to the user.
10. **Report (main).** Contract version, `id -> test` coverage map, each finding as confirmed / not confirmed / fixed, open challenges, and blocked ids.

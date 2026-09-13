---
name: contract-workflow
description: Contract-first implementation and test workflow with implementer and test-verifier subagents. Use this skill before feature/fix level implementation or debugging. Do not use for simple typo fixes, renames, config or doc edits, or local bug fixes that keep interfaces unchanged.
---

# Contract

A contract is a session-scoped working file, not documentation.

1. Location: `contracts/<kebab-case-name>.md`. This directory is excluded from Index & Staleness Management: no `index.md`, no `stale.md`, no `<hex-id>-` naming.
2. Lifetime is the session. Delete `contracts/` before the session ends.
3. Never add `contracts/` to `.gitignore`.
4. A commit that contains `contracts/` is warned, not blocked. A merge deletes `contracts/`.
5. Only the main agent writes or amends a contract. Subagents read it and are given its path and version.
6. Amendment: bump `version`, append a Version Log entry, re-dispatch. Never edit a contract silently.
7. Format:

````
---
version: <n>
---

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

8. Every edge case has an `id`. Tests and verifier findings reference it.

# Implementation + Test Workflow

Fix the contract before any code is written. Both implementation and tests derive from it.

1. **Ground (main).** Read the deciding source files directly. Delegate locating, never reading. Signatures, types, and error types entering the contract come from lines the main agent has read, not from a subagent's summary.
2. **Contract (main).** Write `contracts/<name>.md`.
3. **Implement (`implementer`).** Implementation + tests, run to green. The implementer does not edit the contract; it returns Contract challenges.
4. **Amend (main).** For each challenge: amend the contract (version bump) and re-dispatch, or reject it with a reason. Do not let the implementer resolve a contract gap.
5. **Verify (`test-verifier`).** Given the contract path and the test file paths only.
6. **Seed (main).** For the 2-3 strongest findings, inject that defect into the implementation, run the suite, revert. A suite that stays green confirms the finding. Report each finding as confirmed or not confirmed.

## Contract-specific rules for tests

In addition to "Rules for tests" in `AGENTS.md`:

- Expected values come from the contract's edge-case table or from an independent hand calculation.
- Every edge case `id` in the contract table has a test naming that `id`.

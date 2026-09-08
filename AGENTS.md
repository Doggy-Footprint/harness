# Project Definition

[#TODO][3-5 lines of description of the project]

# Documentation Guide

"Documentation" refers to standalone docs, inline comments, and docstrings.

## Principles
1. **Code is the Ground Truth**: Write documentation only to explain non-obvious rationale, behaviors, and constraints that cannot be inferred directly from the code.

  ## Comment Enforcement

  Default to no new comments or docstrings.

  A comment/docstring is allowed only when it records a non-obvious:
  - design constraint,
  - external-system,
  - safety/security invariant, or
  - reason a seemingly odd implementation is necessary.

  Do not use comments to narrate code, restate names/types/control flow, provide tutorials, or justify ordinary implementation choices.

## Index & Staleness Management
1. Every agent-managed directory (e.g., `/adr`) must contain `index.md` and `stale.md`.
2. File Naming: `<16-char-hex-id>-<kebab-case-name>.md` (e.g., `3f8a9c12b0e45d67-auth-flow.md`).
3. `index.md` Format: Use the following structure separated by `---` for grep/find compatibility:
   ````
   File: <file-name>
   Summary: <one-line summary>
   Related Files: <comma-separated repo paths>
   Related Symbols: <comma-separated function/class/module names>
   ````
4. `stale.md` Format: append stale files for each line.

## Shared Comment & Docstring Synchronization Rules

Follow these rules when identical docstrings or comments must be maintained across multiple locations:

1.	Generate a synced ID: Generate a 48-bit random hexadecimal ID (12 hex characters, e.g., a1b2c3d4e5f6).
2.	Create the tracking file: Create a file at `synced-comments/<synced_id>.md` with the following structure. `code_hash` fingerprints the participating files' non-comment content (each file's content with comments stripped, concatenated in alphanumeric order of filename, hashed):

````
---
version: 1
count: <number of associated code locations>
code_hash: <hash of participating files' non-comment content>
---

# Content
<Write the shared comment or docstring here>

# Version Log
## v1 Log
- Initial creation.
````
3.	Annotate in code: In all associated code locations, include the synchronization tag: `synced id: <synced_id>, version: <n>, count: <n>`
4. Handle content updates: When the shared comment text or the underlying non-comment code changes, increment the version in the frontmatter (and every code tag), recompute `code_hash` if the code changed, and add a new entry under # Version Log.
5.	Version bump trigger: Any code modification that changes the recomputed `code_hash`, or any edit to the shared comment/docstring text, requires the update in rule 4.
6. Deprecation & Removal: When removing the shared content entirely.
- Remove all corresponding comments/docstrings from every referenced code location.
- Increment the document's version, record the removal reason in the version log, and add obsolete: true to the frontmatter.

## Architecture Decision Record Rule

To write ADR, prompt user with checklists & contents below. Do not write by your decision.
ADRs record past architectural decisions; they are not immutable principles.

### Checklist for updating ADR

Create an ADR only if all of the following are true:

- [ ] The decision is expensive or risky to reverse.
- [ ] A concrete alternative was seriously considered and rejected.
- [ ] The reason for the decision cannot be reliably recovered from the code alone.

### Contents

- Title / Status
- Context
- Decision
- Alternatives: acutally considered but rejected (capped to 1-2)
- Consequences: positive / negative (capped to 1-2 each)

#### DO NOT Include

- Any tutorials, concepts.
- Any rhetoric expressions.
- Any non-deterministic sentences.
- Any non-falsifiable sentences.
- Any Session-dependent sentences.

# Task Guide

## User Decision

DO NOT arbitrary determine unspecified details of task. Freely talk back to resolve undermined and ambiguous details.

## Contract

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

## Implementation + Test Workflow

Fix the contract before any code is written. Both implementation and tests derive from it.

1. **Ground (main).** Read the deciding source files directly. Delegate locating, never reading. Signatures, types, and error types entering the contract come from lines the main agent has read, not from a subagent's summary.
2. **Contract (main).** Write `contracts/<name>.md`.
3. **Implement (`implementer`).** Implementation + tests, run to green. The implementer does not edit the contract; it returns Contract challenges.
4. **Amend (main).** For each challenge: amend the contract (version bump) and re-dispatch, or reject it with a reason. Do not let the implementer resolve a contract gap.
5. **Verify (`test-verifier`).** Given the contract path and the test file paths only.
6. **Seed (main).** For the 2-3 strongest findings, inject that defect into the implementation, run the suite, revert. A suite that stays green confirms the finding. Report each finding as confirmed or not confirmed.

### Rules for tests

- Expected values come from the contract's edge-case table or from an independent hand calculation.
- An expected value read off the implementation's own output is permitted only to pin pre-existing legacy behavior, and that test must be marked `@characterization`. Unmarked, it is a tautology.
- Time, randomness, network, and filesystem are injected, not called directly.
- Errors are asserted by type, and observable state after the failure is asserted unchanged.
- Every edge case `id` in the contract table has a test naming that `id`.

### Subagent Reporting

Applies to every subagent dispatch.

1. The caller gives a findings-file path for anything longer than the return payload. Detail goes in the file; the return payload stays short.
2. The return payload always carries what the file cannot reconstruct: assumptions made, alternatives rejected, what was searched for and not found, what remains unresolved.
3. One dispatch, one subject. Reuse a session only for iterations on the same contract; discard it when the subject or the contract version changes.

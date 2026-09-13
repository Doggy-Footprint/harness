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

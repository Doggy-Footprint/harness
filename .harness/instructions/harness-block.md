# Documentation Guide

"Documentation" refers to standalone docs, inline comments, and docstrings.

## Principles
1. **Code is the Ground Truth**: Document only non-obvious rationale, behaviors, and constraints that cannot be inferred from the code.
2. **Preserve Failed Attempts**: Approaches whose failure took real work to discover (an implementation, a run, or an investigation, not a reading of the code), and concrete proposals the user rejected, keep their evidence and cause: in the handoff while the task is open, in a try-n-fail record afterwards.
3. **Record Observations, Not Mandates**: Records carried across sessions state what was observed, its evidence, and how to re-check it. They do not bind a later session to an earlier session's choices; a later session re-checks and decides for itself.

### Comment Enforcement

A comment/docstring is allowed only when it records a non-obvious:
- design constraint,
- external-system,
- safety/security invariant, or
- reason a seemingly odd implementation is necessary.

Do not use comments to narrate code, restate names/types/control flow, provide tutorials, or justify ordinary implementation choices.

### Record Writing

Every record under `agent-docs/` excludes:
- tutorials and concepts;
- rhetorical expressions;
- non-deterministic, non-falsifiable, or session-dependent sentences.

## Commit Stamp

A hook writes `commit: <HEAD at last write>` into the frontmatter of every Markdown document under `agent-docs/` except `index.md` and `stale.md`. Do not edit it by hand. Before relying on a record, compare its `commit` with HEAD and re-check claims about code changed since then.

## Index & Staleness Management
1. Every agent-managed directory (e.g., `agent-docs/try-n-fail`, `agent-docs/handoff`) must contain `index.md`, `stale.md`, and a `stale/` directory. `agent-docs/specs/` and `agent-docs/spec-logs/` are workflow state and run records, so they are exempt. `agent-docs/adr/` and `agent-docs/rejections/` from harness versions before 0.29.0 are no longer managed or checked.
2. File Naming: `<16-char-hex-id>-<kebab-case-name>.md` (e.g., `3f8a9c12b0e45d67-auth-flow.md`).
3. `index.md` Format: entries separated by `---`:
   ````
   File: <file-name>
   Summary: <one-line summary>
   Related Files: <comma-separated repo paths>
   Related Symbols: <comma-separated function/class/module names>
   ````
4. When marking a document stale, remove its entry from `index.md`, append that index block verbatim to `stale.md`, and move the document to `stale/`.

## Shared Comment & Docstring Synchronization Rules

Apply when an identical comment or docstring must be maintained across multiple locations:

1. Synced ID: a random 48-bit hex ID (12 hex characters, e.g., a1b2c3d4e5f6).
2. Tracking file: `agent-docs/synced-comments/<synced_id>.md`. `code_hash` hashes the participating files' contents with comments stripped, concatenated in alphanumeric filename order:
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
3. Code tag: every associated code location includes `synced id: <synced_id>, version: <n>, count: <n>`.
4. Update: when the shared text is edited, or a code change alters the recomputed `code_hash`, increment the version in the frontmatter and every code tag, recompute `code_hash`, and add a `# Version Log` entry.
5. Removal: when removing the shared content entirely,
   - remove it from every referenced code location;
   - increment the version, record the removal reason in the version log, and add `obsolete: true` to the frontmatter.

## Try-n-Fail Rule

Directory: `agent-docs/try-n-fail/`.

Records approaches a later task could plausibly try again: an attempt whose failure took real work to discover (an implementation, a run, or an investigation, not a reading of the code), or a concrete proposal the user rejected. Candidates come from a completing handoff's Failed Attempts, a spec's execution ledger, or a rejection in conversation. Show the draft to the user and write only after confirmation.

Required file structure:

- `#` Title
- `## Goal` (what the attempts tried to achieve)
- `## Attempts` (table `| attempt | failure evidence | cause |`; cause marked `verified`, `hypothesis`, or `user rejected: <reason>`)
- `## Revisit Condition` (the observable change that would make another attempt worthwhile)

Append rows for new attempts at the same goal; never delete or edit existing rows. When the goal is dropped or an attempt later succeeds, mark the record stale.

## Handoff Rule

Directory: `agent-docs/handoff/`.

Write when a workflow-approach task exhausts its verifier budget, cannot make progress without a user decision or external change, the user pauses or stops mid-task, or the user requests it.

Required file structure:

- `#` Title
- `## User Query` (user's original words)
- `## State` (branch, changed files)
- `## Failed Attempts` (table `| attempt | failure evidence | cause |`, cause marked `verified` or `hypothesis`)
- `## Next Step`
- `## Open Questions`
- `## Spec` (active or archived spec path, version, status, and run ID)
- `## Execution Ledger` (findings and dispositions, evidence, fuzz, and mutation outcomes (hand and tool), correction and verifier counters)

An incomplete nonterminal workflow keeps its active spec in `agent-docs/specs/`
and records this handoff path in the spec. A limit handoff points to the archived
spec in `agent-docs/spec-logs/`. The handoff must still state remaining work and
failed attempts without requiring telemetry to reconstruct them.
Handoffs created before harness 0.7.0 may retain `## Contract Snapshot` instead
of `## Spec` and `## Execution Ledger`; do not rewrite historical records solely
to change their format.
Handoffs created before harness 0.27.0 may retain `## Goal` instead of `## User Query`.

When resuming, never delete or edit existing Failed Attempts rows; only append.

When the task completes, propose try-n-fail records for Failed Attempts a later task could repeat, then remove the handoff's entry from `index.md` and move the file to `stale/`.

# Task Guide

## User Decision

Never decide unspecified task details silently. Resolve what the project, code, and conversation can answer. For the rest, either ask, or state a default (what you chose, why, and how to change it later) so the user can veto it before it takes effect. Ask instead when the choice is expensive or risky to reverse, or contradicts what the user or project has stated.

## Reporting to the User

Summaries, briefs, and reports must be readable without opening another file. Do not use a label the user cannot resolve from the message itself (e.g., `H3`, `F2`, `O-4`, a finding or obligation id) on its own: state what it refers to in plain words, and add the id in parentheses only when the user needs it to find the item.

## Commit & PR Messages

- A commit message carries a `Request:` line (the user request the work answers) and an `Intent:` line (what the change is meant to achieve). The commit-msg hook warns when either is missing; merge, revert, `fixup!`, `squash!`, and `amend!` commits are exempt.
- A PR description is written as a five-minute standup introduction for someone who does not know the project: the problem, what changed, why this approach, and how it was checked. A Claude Code hook repeats this after `gh pr create`, and after `gh pr edit` with a body flag.

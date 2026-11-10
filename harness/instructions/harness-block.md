# Documentation Guide

"Documentation" refers to standalone docs, inline comments, and docstrings.

## Principles
1. **Code is the Ground Truth**: Document only non-obvious rationale, behaviors, and constraints that cannot be inferred from the code.
2. **Preserve Failed Attempts**: Approaches whose failure took real work to discover (an implementation, a run, or an investigation, not a reading of the code), and concrete proposals the user rejected, keep their evidence and cause: in the session progress while the task is open, in a try-n-fail record afterwards.
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

## Rule Files

These rules live in separate files under `.harness/instructions/`. A hook adds a rule's text to the session at its first Write or Edit in the rule's directory; read the file yourself before other work it covers. Hook and pre-commit messages name the file of a rule they find violated.

| file | read before |
| --- | --- |
| `progress.md` | committing in a session that changed the project, continuing earlier work, or opening a PR |
| `index-and-staleness.md` | adding, renaming, or marking stale a record in `agent-docs/` |
| `try-n-fail.md` | proposing a try-n-fail record |
| `todos.md` | writing a todo |
| `synced-comments.md` | keeping one comment identical in several places, or editing code tagged `synced id:` |

# Task Guide

## User Decision

Never decide unspecified task details silently. Resolve what the project, code, and conversation can answer. For the rest, either ask, or state a default (what you chose, why, and how to change it later) so the user can veto it before it takes effect. Ask instead when the choice is expensive or risky to reverse, or contradicts what the user or project has stated.

## Reporting to the User

Summaries, briefs, and reports must be readable without opening another file. Do not use a label the user cannot resolve from the message itself (e.g., `H3`, `F2`, `O-4`, a finding or obligation id) on its own: state what it refers to in plain words, and add the id in parentheses only when the user needs it to find the item.

## Commit & PR Messages

- A commit message carries a `Request:` line (the user request the work answers) and an `Intent:` line (what the change is meant to achieve). The commit-msg hook warns when either is missing; merge, revert, `fixup!`, `squash!`, and `amend!` commits are exempt.
- A PR description is written as a five-minute standup introduction for someone who does not know the project: the problem, what changed, why this approach, and how it was checked. A Claude Code hook repeats this after `gh pr create`, and after `gh pr edit` with a body flag.

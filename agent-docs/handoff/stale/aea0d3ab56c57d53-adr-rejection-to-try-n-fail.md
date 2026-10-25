---
commit: f2e75b78aecbcef2eef38ad7af02220665d61d4a
---

# Migrate ADR and rejection records to try-n-fail

## User Query
Harness 0.29.0 replaced the ADR and rejection record rules with the try-n-fail rule. Review the ADR and rejection records below and move what a later task still needs into `agent-docs/try-n-fail/`. How each record is handled depends on the repository's current state and the user's choices.

## State
Written by `harness.py update` (migration 0.29.0); no code or record was changed. Records to review (`stale/` entries are history):
- `agent-docs/adr/4a5b6c7d8e9f0123-versioned-migrations.md`
- `agent-docs/adr/stale/5c4c01bdc91769f7-selfcheck-swe-bench-baseline.md`

## Failed Attempts
| attempt | failure evidence | cause |
| --- | --- | --- |
| none | none | none |

## Next Step
1. Read each record and check its claims against the current code.
2. Per record, propose one of these to the user, with the reason: convert its rejected alternatives or failed approaches to try-n-fail attempts (cause `user rejected: <reason>` or `verified`/`hypothesis`) with a Revisit Condition; leave it in place; or delete it. A decision the code already shows needs no record.
3. Write only what the user confirms, following the Try-n-Fail Rule in `AGENTS.md`.
4. Mark this handoff stale under the Index & Staleness Management rule.

## Open Questions
- Which records the user wants converted, kept in place, or deleted.

## Spec
none — not a workflow-approach task.

## Execution Ledger
none

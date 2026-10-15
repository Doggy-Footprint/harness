# Dashboard partial-use classification from Skill calls

## Goal
"대시보드에도 반영" — GitHub issue #7 (closed and moved here): count a session that invoked a harness skill (e.g. workflow-approach) without harness sub-agents as 부분 사용 in the analytics dashboard.

## State
Branch `issues`, commit 57925cb. No code changes yet.
- `analytics/usage.py` `_collect_turn` already detects `Skill` calls with `skill == "workflow-approach"`.
- `analytics/transcripts.py` counts `Skill` calls but drops the `skill` input name.
- `analytics/app.py` `_classify_sessions` returns `partial` only through `_has_harness_evidence` (harness sub-agents).

## Failed Attempts
| attempt | failure evidence | cause |
|---|---|---|

## Next Step
Run workflow-approach: record skill names in `analytics/transcripts.py` / store, and extend `_has_harness_evidence` to accept harness skill invocations. Claude only; Codex is unsupported and has no Skill tool signal.

## Open Questions
- Which skills count as harness evidence: only workflow-approach, or every skill shipped in `harness/skills/`?
- Whether existing imported sessions need a re-import to gain skill names.

## Spec
None yet.

## Execution Ledger
None yet.

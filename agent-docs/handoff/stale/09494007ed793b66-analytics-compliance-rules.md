# Analytics compliance false negatives and marker robustness

## Goal
"완료된 run이 대부분 비준수로 나오는 문제에 대해서 좀 더 살펴보자." → "일단 커밋하고, 수정 방향에 대해서는 handoff로 남겨"

## State
- Branch: master. Commit: the commit containing this handoff (analytics import fix + transcript stats, spec run f89a33aaa16ab15a).
- Changed files for this topic: none yet (investigation only).
- Evidence: `~/.harness/telemetry/*.jsonl` workflow events per run (2026-09-26):
  - 2106fd306d5f: start > implement_test > amend > amend > verify > retry > amend > verify > pass > end complete — noncompliant `amend_without_retry_result`
  - f4e54a4cec9a: start > implement_test > amend > verify > retry > amend > verify > pass > end complete — noncompliant `amend_without_retry_result`
  - f89a33aaa16a: start > implement_test > amend > amend > verify > retry > amend > verify > pass > end complete — noncompliant `amend_without_retry_result`
  - 8f8bc346160a: start > implement_test > start > implement_test > verify > pass > end complete — noncompliant `duplicate_implement_test`, `expected_one_start`
  - 0f804148d5a8: start > implement_test > verify > retry > amend > verify > limit > end limit — compliant

## Failed Attempts
| attempt | failure evidence | cause |
|---|---|---|
| none | - | - |

## Next Step
Each item needs user approval, then a workflow-approach spec.
1. `analytics/compliance.py`: accept `amend` after `implement_test` whenever no verifier result is pending. Keep flagging an amend between `verify` and its `verifier_result`, and an amend before `implement_test`. Cause (verified): `harness/skills/workflow-approach/SKILL.md` says "Emit `amend` before every amendment or correction", which includes Reconcile-step corrections before the first verify. The evaluator accepts amend only when the last result was `retry`. The original spec (`agent-docs/spec-logs/7176826b00d34cc7-analytics-dashboard.md` F3, "correction amend cycles") was read narrowly. This changes the F3 interpretation.
2. Duplicate start (verified in `~/.claude/projects/-Users-hwansu-orca-workspaces-blog-editor/5755a596-5680-4d10-9537-8dce17b19f14.jsonl` at 12:16:18Z): the agent ran `spec_lifecycle.py start ...; echo rc=$?; workflow_marker.py start ...; workflow_marker.py phase ...`. Lifecycle failed (`max_verifier_invocations must be 2`) but the `;` chain still emitted the markers, and the retry emitted them again. Options:
   - (a) change the skill example to chain the start marker with `&&` after lifecycle start (recommended; the violation stays visible in compliance);
   - (b) make `workflow_marker.py start` idempotent per run (hides the mistake).
   Either option edits `harness/` and needs a version bump with `update` migration steps.
3. Workflow marker events carry `session_id: null`, because markers run through Bash and get no hook payload. Run-to-session cost linkage currently depends on run-tagged subagent hook events. A run without subagent events gets no linked cost. Options: have the marker record the session (source of the session id to be investigated), or leave as is.

## Open Questions
- Approve the new amend rule in item 1, including whether an amend before `implement_test` stays a violation.
- Item 2: choose (a), (b), or both.
- Item 3: fix or leave.

## Spec
None yet for this follow-up. The prior run is archived at `agent-docs/spec-logs/f89a33aaa16ab15a-analytics-import-and-session-stats.md`: version 4, status complete, run f89a33aaa16ab15a.

## Execution Ledger
- Findings: C1 amend rule too strict (3 runs, verified); C2 duplicate start from `;` chaining (1 run, verified); C3 marker session_id null (verified from telemetry).
- Dispositions: all pending a user decision. No corrections or verifier invocations yet.

---
commit: 40078a67b4015352344c64edf927ac9a5583f928
---

# Telemetry does not cover the workflow-approach brief, recorded facts, or amendment reasons

## Goal
Make the brief stages of workflow-approach (understanding round, decision round, approval brief) and the facts under `agent-docs/facts/` observable in the telemetry jsonl, so their behavior across real runs can be measured.

## Observation
Observed at harness 0.48.0. Each item gives a re-check.

1. No event is emitted before approval.
   - `workflow_marker.py start` is emitted only after `spec_lifecycle.py start` succeeds, which happens after the approval brief (`harness/skills/workflow-approach/SKILL.md` Workflow step 2 and the Telemetry section).
   - `telemetry.workflow_phase`, `verifier_result`, `verification_result`, and `workflow_end` return without emitting when no active workflow state matches the run id (`harness/lib/telemetry.py`).
   - So nothing records: how many understanding and decision rounds ran; how many fact questions and user decisions there were; whether a split was proposed or accepted; how many of the agent's picks (`<run-id>-picks.md`) differ from the user's choices; and whether a brief stopped before approval.
   - The picks file is named by run id, so a run id exists by the first decision round.
   - Re-check: `grep -n "Emit telemetry start only after" harness/skills/workflow-approach/SKILL.md` and read `workflow_phase` in `harness/lib/telemetry.py`.
2. Writes to `agent-docs/facts/` emit no event.
   - `emit_path_write` in `harness/hooks/telemetry_hook.py` emits only `spec_write` (files directly under the specs directory) and `progress_write` (files directly under the progress directory).
   - Re-check: read `emit_path_write`.
3. The `amend` phase carries no reason.
   - Identity and lifecycle rule 5 of the skill prefixes a Version Log entry with `[intent-mismatch]` when an intent mismatch found after approval forces the amendment.
   - `workflow_marker.py phase --phase amend` takes no field that tells such an amendment from a contract-only one.
   - Re-check: `grep -n "intent-mismatch" harness/skills/workflow-approach/SKILL.md` and the `phase` parser in `harness/bin/workflow_marker.py`.
4. `analytics/compliance.py` evaluates only `workflow_start`, `workflow_phase`, `verifier_result`, and `workflow_end` (`_WORKFLOW_EVENTS`).
   - New event names do not change its verdicts, but they also do not appear in the dashboard unless the analytics side reads them.
   - Re-check: read `_WORKFLOW_EVENTS` and `evaluate` in `analytics/compliance.py`, and `_event` in `analytics/importer.py`.

## Next Step
- Re-check items 1 to 4 against the current code.
- For item 1, decide the event shape with the user before implementing, for example a `brief` marker emitted with a run id and no active workflow state, with fields for round, fact questions, user decisions, split proposed, and picks differing.
- Items 2 and 3 each add a field or an event to existing code paths. Analytics display is a separate decision.

## Related
- harness/lib/telemetry.py, harness/bin/workflow_marker.py, harness/hooks/telemetry_hook.py, harness/skills/workflow-approach/SKILL.md, analytics/compliance.py, analytics/importer.py

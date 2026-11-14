# Parse workflow-approach brief text from transcripts into the analytics dashboard

## Goal
Show, per workflow run, the technical decision axes the agent proposed and the understanding it stated in each brief round, extracted from the transcript by a rule-based (non-LLM) parser. Trend-level accuracy is the target, not 100%.

## Observation
- Requested by the user on 2026-11-14 during workflow run 49bafb302bb6593c, which was split in two: that run adds the `brief` telemetry event (stage, round, run id, counts of fact questions, cumulative user decisions, split state and picks differing, and a pointer of session id plus `tool_use_id` to the brief's turn); this item is the second half.
- On 2026-11-14 the user asked for the parser to be built well ("파서를 잘 만들어줘").
- The user rejected every extra parser field proposed in that run (assumption list, fact-question dimension tokens, not-asked dimensions, exclusions, significance criteria, split proposal, Decided-for-you titles, picks-differing lines, Conflict and New concept presence, reply latency, reply length, invitation answered, veto wording, parse status, parser version). Reason given: the pointer lets the original text be recovered.
- Telemetry jsonl carries no free text; parsed text was proposed to stay in the local analytics database only.

## Next Step
- Check that the `brief` events from run 49bafb302bb6593c exist in `~/.harness/telemetry` and that their `session_id` and `tool_use_id` locate the brief turn in the transcript.
- Run workflow-approach for the parser, storage, and dashboard view of decision axes and understanding.

## Related
- analytics/transcripts.py, analytics/app.py, analytics/importer.py, analytics/frontend/src/App.jsx, harness/hooks/telemetry_hook.py

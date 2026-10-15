# Per-version run metrics in telemetry

## Goal
"#10 우선 착수" — GitHub issue #10 (closed and moved here): record per-run metrics in trace data at run time, tagged with the harness version, so before/after comparisons survive transcript cleanup.

## State
Branch `issues`, commit 57925cb. No code changes yet.
Evidence from the issue: pre-0.7.0 sessions with a code write n=8 (Claude Code 0); post-0.7.0 n=66, median 9 exploration calls before first code write; no-marker sessions n=216, median 8. 31 sessions carried multiple harness marker versions; 1,481 shell/inline-interpreter writes were unclassifiable.

## Failed Attempts
| attempt | failure evidence | cause |
|---|---|---|
| Retroactive comparison from local transcripts | only 8 pre-0.7.0 sessions with a code write, none from Claude Code | hypothesis: Claude Code transcript cleanup period removed older transcripts |
| Version attribution from first `<!-- harness:begin X.Y.Z -->` in transcript | 31 sessions contained multiple marker versions | verified: transcript text is not a reliable version source |

## Next Step
Run workflow-approach. Proposed metrics per run: harness version (from installed payload), exploration tool calls before first code write (source extensions only, excluding docs/config/harness dirs), non-code writes before first code write, verifier rounds, correction count, workflow compliance, cost, project/repo id. Persist aggregates outside the transcript directory.

## Open Questions
- Storage location and retention of aggregates (telemetry dir vs analytics store).
- How to classify shell/inline-interpreter writes as code writes.
- Acceptance: metrics queryable by version and project; two-version comparison without raw transcripts.

## Spec
None yet.

## Execution Ledger
None yet.

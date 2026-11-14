# Collect telemetry from several people and digest it for insights

## Goal
Combine harness telemetry from several people's machines and extract insights across them.

## Observation
- On 2026-11-14 the project owner stated the plan (fact `e06d861b6fec1853`) and, during run 1b81d06b91eeb079, that it is future work with no scheduled run (fact `88f7f3e0ef2a3ecd`).
- Telemetry jsonl lines carry no free text since 0.49.0; parsed brief text (run 1b81d06b91eeb079) lives only in each person's local analytics database.

## Next Step
- Ask the project owner how records would be collected (who sends them, where they are stored) and which questions the digest should answer.

## Related
- analytics/importer.py, analytics/app.py, harness/lib/telemetry.py

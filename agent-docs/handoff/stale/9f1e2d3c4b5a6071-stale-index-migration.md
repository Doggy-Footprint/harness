# Stale Index Migration

## Goal

"index.md에 있던 내용 중 stale해진 것들을 stale.md에 옮겨서 보관하고, 해당 문서들은 `stale/`로 이동. stale.md 파일이 이번 버전에서 삭제될텐데 삭제하지 말고, 옛 로그를 보관하는 곳으로 활용. 버전별로 step-by-step migration (ex. ver 2 -> 3 -> 4 이면 2 -> 3 이후 3 ->4) 하는 걸 ADR에 추가."

## State

Branch: `master`
Commit: `356e50f`
Changed files: `installer/harness.py`, `harness/VERSION`, `harness/instructions/harness-block.md`, `agent-docs/adr/index.md`, `agent-docs/adr/4a5b6c7d8e9f0123-versioned-migrations.md`, `tests/test_installer.py`, `agent-docs/contracts/stale-index-migration.md`, this handoff record.

## Failed Attempts

| attempt | failure evidence | cause |
| --- | --- | --- |
| Initial full suite after implementation | C1/C2 supplied one confirmation although `0.2.0` to `0.4.0` runs two migrations; version output was a tuple; requirements test expected no `stale.md`. | verified |
| Full suite after first corrections | C4 counted both migration announcements and confirmation prompts as version executions. | verified |
| Full suite after C4 narrowing | C4 searched for `Migration ` while CLI emits `migration `. | verified |

## Next Step

In `tests/test_installer.py`, make C4 select lines beginning `migration ` (lowercase), then run `python3 -m unittest tests/test_installer.py`. If it passes, continue the contract workflow from verification and seed stages using contract v2.

## Open Questions

none

## Contract Snapshot

Contract: `agent-docs/contracts/stale-index-migration.md`, version 2.

- C1: archive a matching index block verbatim into `stale.md`, remove it from `index.md`, and move its document to `stale/`.
- C2: archive an unindexed legacy document and retire its filename-list entry while retaining the recognizable log.
- C3: malformed, missing, or conflicting sources fail atomically with `MigrationConflict`.
- C4: a `0.2.0` installation updates through `0.3.0` and `0.4.0` once each in order.

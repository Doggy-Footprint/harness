---
session: f2f45dd9-4022-476a-89bb-a7ffaa2e4aa4
before: none
previous: none
branch: master
commit: a75fb6f3d1424e3948293eafed85b7fa28678a7d
---

# Leave spec, progress, and stale records out of rearrange-docs

## Next Session

### State
- Done: harness 0.37.0, committed on master and pushed to origin/master at the user's request (no PR). rearrange-docs Scope gains a "Leave these out entirely" list (no search, read, edit, report, or sync-state entry): `agent-docs/specs/`, `spec-logs/`, `progress/`, `progress-logs/`, and `stale.md` / `stale/` of every agent-managed directory. specs/ and spec-logs/ moved there from the "Never edit; report" list. Migration `migrate_rearrange_docs_skip_records` announces it; `update .` regenerated `.harness/`, `.agents/skills/rearrange-docs/`, AGENTS.md.
  - commit: a75fb6f3d1424e3948293eafed85b7fa28678a7d; files: harness/skills/rearrange-docs/SKILL.md, installer/harness.py, harness/VERSION
- Default chosen without asking: `agent-docs/specs/` (active workflow state) and the `stale.md` / `stale/` archives were added to the exclusion alongside the logs the user named. To narrow it, edit the list in harness/skills/rearrange-docs/SKILL.md.
  - commit: a75fb6f3d1424e3948293eafed85b7fa28678a7d; files: harness/skills/rearrange-docs/SKILL.md

### Next Step
- The user did not answer whether agent-docs/specs/ should go back to the never-edit-but-report list; ask before changing it.
  - commit: a75fb6f3d1424e3948293eafed85b7fa28678a7d; files: harness/skills/rearrange-docs/SKILL.md

### Constraints
- "rearrange-docs  - spec-logs, progress-logs 등은 제외하도록 해줘"
  - source: ### User Requests #1

### Verify
- `python3 -m unittest discover -s tests`: 879 tests, only the two hypothesis import errors (test_session_metrics, test_isolation_telemetry); `uv run --no-project --with pytest --with hypothesis python -m unittest test_session_metrics test_isolation_telemetry` (in tests/) passed 102 tests. `python3 .harness/git/verify_rules.py` exited 0.
  - commit: a75fb6f3d1424e3948293eafed85b7fa28678a7d; files: tests/test_installer.py, tests/test_progress_retire.py, tests/test_doc_records.py, tests/test_comment_gate.py

### Dead Ends
- none: no approach was abandoned.
  - commit: a75fb6f3d1424e3948293eafed85b7fa28678a7d; files: none

### Related
- agent-docs/progress-logs/78c6316f37fa8deb-spec-ids-out-of-code-comments.md
  - commit: a75fb6f3d1424e3948293eafed85b7fa28678a7d; files: agent-docs/progress-logs/78c6316f37fa8deb-spec-ids-out-of-code-comments.md

## Record

### Changes
- harness/skills/rearrange-docs/SKILL.md: exclusion list in Scope.
- installer/harness.py: `migrate_rearrange_docs_skip_records` and the 0.37.0 MIGRATIONS entry; harness/VERSION 0.37.0.
- tests: version pins 0.36.0 -> 0.37.0, migration lists extended with 0.37.0, one more `y` answer per update through the new migration, dry-run confirmation count 29 -> 30; tests/test_progress_retire.py u1/u2 renamed to drop the "only"/version wording; new `test_update_from_0360_leaves_records_out_of_rearrange_docs`.

### Commands
- `python3 installer/harness.py update .` with `y` answers piped in.

### Failed Attempts
| attempt | failure evidence | cause |
| --- | --- | --- |
| Full suite after the version bump | 23 failures with EOFError at `Apply migration` and a dry-run count mismatch | verified: update tests hard-code the number of `y` answers and the dry-run confirmation count |

### Sources
- harness/skills/rearrange-docs/SKILL.md, AGENTS.md (Index & Staleness Management exemptions), installer/harness.py MIGRATIONS

### User Requests

#### 1 — 2026-11-06T06:41:14Z

> rearrange-docs  - spec-logs, progress-logs 등은 제외하도록 해줘

#### 2 — 2026-11-06T07:09:39Z

> 커밋하고 master에 바로 push해.

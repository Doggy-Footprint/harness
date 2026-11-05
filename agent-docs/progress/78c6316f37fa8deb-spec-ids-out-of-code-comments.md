---
session: 902ce331-4118-40fd-9ccf-8184edbf4c1b
before: none
previous: none
branch: feat/sub-inst
commit: 11dce6f351512ac8e4ecd4b8b8462ac50a195bf2
---

# Keep spec ids out of code comments written by implementer and test-implementer

## Next Session

### State
- Observed: implementer and test-implementer receive CLAUDE.md and the imported AGENTS.md as project context without a tool call; both quoted the Project Definition first sentence and the Task Guide headings in a no-tool probe. code-explorer, test-verifier, and mutant-triager were not probed.
  - commit: 11dce6f351512ac8e4ecd4b8b8462ac50a195bf2; files: harness/agents/implementer.md, harness/agents/test-implementer.md
- Done (uncommitted): harness 0.35.0. test-implementer labels cases through test names or parameter ids and keeps spec, requirement, Case, and obligation ids in the report's evidence map, not in Tests comments or docstrings; implementer keeps the same ids out of code comments and docstrings. Migration `migrate_spec_ids_out_of_code` announces it; `update .` regenerated `.harness/`, `.claude/agents/`, `.codex/agents/`, AGENTS.md.
  - commit: 11dce6f351512ac8e4ecd4b8b8462ac50a195bf2; files: harness/agents/implementer.md, harness/agents/test-implementer.md, installer/harness.py, harness/VERSION
- Done (uncommitted): removed 161 spec-id tag comments and the spec-id parts of 11 docstrings from tests/. Comments that also carry a non-id reason were kept with the id stripped (tests/test_installer.py check-ignore negation comment, tests/test_test_scan_rules.py swift omission comment).
  - commit: 11dce6f351512ac8e4ecd4b8b8462ac50a195bf2; files: tests/test_comment_gate.py, tests/test_installer.py, tests/test_session_metrics.py, tests/test_telemetry.py, tests/test_test_scan.py, tests/test_test_scan_rules.py, tests/test_verification_tools.py, tests/test_workflow_markers.py

### Next Step
- Commit the 0.35.0 change and the test comment cleanup once the user approves.
  - commit: 11dce6f351512ac8e4ecd4b8b8462ac50a195bf2; files: none
- Left in place, not id tags: test function names that carry ids (e.g. `test_vo9_...`), and narration comments without ids in tests/test_test_scan.py (`# py test_`, `# go`, ...).
  - commit: 11dce6f351512ac8e4ecd4b8b8462ac50a195bf2; files: tests/test_test_scan.py, tests/test_installer.py

### Constraints
- "A, D"
  - source: ### User Requests #4

### Verify
- `python3 -m unittest discover -s tests` before the last two pin fixes: 822 tests, only those two installer pins and the two pytest/hypothesis import errors failed. After the fixes, `python3 -m unittest test_installer test_doc_records test_comment_gate test_workflow_markers test_telemetry` (run in tests/) passed 340 tests, and `uv run --no-project --with pytest --with hypothesis python -m unittest test_session_metrics test_isolation_telemetry` passed 102 tests.
  - commit: 11dce6f351512ac8e4ecd4b8b8462ac50a195bf2; files: tests/test_installer.py, tests/test_doc_records.py, tests/test_session_metrics.py
- Re-check that no spec-id tag comment or docstring remains: enumerate COMMENT tokens and docstrings in tests/*.py and grep for `V?O[0-9]|FR[0-9]|[Ss]pec [0-9a-f]{8}|C[0-9]{1,2}\b`; this run returned no match.
  - commit: 11dce6f351512ac8e4ecd4b8b8462ac50a195bf2; files: tests/

### Dead Ends
- none: no approach was abandoned beyond the failed attempts recorded below.
  - commit: 11dce6f351512ac8e4ecd4b8b8462ac50a195bf2; files: none

### Related
- agent-docs/progress-logs/9c41e7a2b85d03f6-live-session-rotation-refusal.md
  - commit: 11dce6f351512ac8e4ecd4b8b8462ac50a195bf2; files: agent-docs/progress-logs/9c41e7a2b85d03f6-live-session-rotation-refusal.md

## Record

### Changes
- harness/agents/test-implementer.md: case labels through test names or parameter ids; ids stay in the evidence map; Tests comments follow Comment Enforcement.
- harness/agents/implementer.md: ids stay out of code comments and docstrings.
- installer/harness.py: `migrate_spec_ids_out_of_code` and the 0.35.0 MIGRATIONS entry; harness/VERSION 0.35.0.
- tests: version pins 0.34.4 -> 0.35.0, migration lists extended with 0.35.0, one more `y` answer for each update that runs through the new migration, dry-run confirmation count 27 -> 28; spec-id comments and docstring parts removed.

### Commands
- `python3 installer/harness.py update .` with `y` answers piped in.
- Subagent probes of implementer and test-implementer with tool use forbidden, asking whether CLAUDE.md/AGENTS.md content is in context.

### Failed Attempts
| attempt | failure evidence | cause |
| --- | --- | --- |
| Collapse blank lines after comment removal with a regex over the whole file | diff removed pre-existing double blank lines unrelated to any comment (tests/test_installer.py near lines 424, 1186, 1290) | verified: the regex matched every double blank inside classes; redone from HEAD, dropping only a blank line next to a removed comment run |
| Full suite after the version bump | 23 failures with EOFError at `Apply migration` and list mismatches | verified: update tests hard-code the number of `y` answers and the dry-run confirmation count |

### Sources
- harness/agents/*.md, harness/skills/workflow-approach/SKILL.md (Traceability, evidence map), harness/git/warn_new_comments.py (exit 0 at pre-commit), harness/ci/harness-comment-warning.yml

### User Requests

#### 1 — 2026-11-04T23:45:59Z

> `test-implementer`, `implementer`, 등의 sub agent에서 `CLAUDE.md`를 읽는지 체크해줘

#### 2 — 2026-11-04T23:48:12Z

> IDK why but there are comments in test files constantly

#### 3 — 2026-11-05T01:28:45Z

> 한글로 말해줘

#### 4 — 2026-11-05T06:43:47Z

> A, D

#### 5 — 2026-11-05T07:13:33Z

> 커밋

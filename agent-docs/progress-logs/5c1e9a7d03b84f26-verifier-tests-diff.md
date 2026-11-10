---
session: 7950534c-aadb-4b46-9a0c-4ea2e45bd5de
before: agent-docs/progress-logs/bc2e2e7149ea9995-progress-rule-layout.md
previous: none
branch: master
commit: f0470794e9321c7efa4119fa1ad45d8075f1c31c
---

# Pass test-verifier a Tests-only diff file

## Next Session

### State
- Harness 0.39.0, committed on master as d1339e8 and pushed to origin/master at the user's request (no PR): workflow-approach Verify step now has main write `git diff <base_commit> -- <Tests paths>` plus untracked Tests files (`git ls-files --others --exclude-standard -- <Tests paths>`) to a file outside the working tree and pass its path to test-verifier; test-verifier's inputs list that file and it reads only Tests, imported test helpers, and that file. The audit-state paragraph says the verifier checks the impact assessment against the Tests diff file. Migration `migrate_verifier_tests_diff` announces it; `update .` regenerated `.harness/`, `.claude/`, `.codex/`, `.agents/`.
  - commit: f0470794e9321c7efa4119fa1ad45d8075f1c31c; files: harness/skills/workflow-approach/SKILL.md, harness/agents/test-verifier.md, installer/harness.py, harness/VERSION
- test-verifier still has only Read, Grep, Glob; no hook enforces its read paths, so the tool list is the isolation boundary.
  - commit: f0470794e9321c7efa4119fa1ad45d8075f1c31c; files: harness/agents/test-verifier.md, harness/hooks/spec_gate.py

### Next Step
- No workflow run has yet exercised the new Verify instruction; check the first test-verifier dispatch reads the Tests diff file.
  - commit: f0470794e9321c7efa4119fa1ad45d8075f1c31c; files: harness/skills/workflow-approach/SKILL.md

### Constraints
- "1번 안이 좋겠네. 지시 수정은 append 말고 의도에 맞게 rewrite해"
  - source: ### User Requests #3

### Verify
- `.venv/bin/python -m unittest discover -s tests`: 982 tests OK. `python3 installer/harness.py doctor .` exit 0; `git diff --check` clean.
  - commit: f0470794e9321c7efa4119fa1ad45d8075f1c31c; files: tests/test_installer.py, tests/test_doc_records.py, tests/test_comment_gate.py, tests/test_progress_retire.py

### Dead Ends
- Giving test-verifier Bash limited by a PreToolUse hook to Tests-path `git diff` was proposed and not chosen by the user.
  - commit: f0470794e9321c7efa4119fa1ad45d8075f1c31c; files: harness/agents/test-verifier.md

### Related
- none: no other record was needed.

## Record

### Changes
- harness/skills/workflow-approach/SKILL.md: Verify step rewritten to produce and pass the Tests diff file; audit-state paragraph references it.
- harness/agents/test-verifier.md: inputs and read scope rewritten.
- installer/harness.py: `migrate_verifier_tests_diff` and the 0.39.0 MIGRATIONS entry; harness/VERSION 0.39.0.
- tests: version pins 0.38.0 -> 0.39.0, migration lists extended, one more `y` answer in the 28 update inputs that ran out, dry-run confirmation count 31 -> 32; new `test_update_from_0380_passes_verifier_a_tests_diff_file`.

### Commands
- `printf 'y\n' | python3 installer/harness.py update .`

### Failed Attempts
| attempt | failure evidence | cause |
| --- | --- | --- |
| Running the suite with system `python3` | `ModuleNotFoundError: No module named 'hypothesis'` for test_isolation_telemetry and test_session_metrics, also on the clean tree | verified: hypothesis is installed only in `.venv` |

### Sources
- harness/agents/test-verifier.md, harness/skills/workflow-approach/SKILL.md (Verify step, audit-state paragraph), harness/hooks/spec_gate.py, commit f047079 test diff

### User Requests

#### 1 — 2026-11-07T09:58:17Z

> test-verifier가 git diff를 못 하는 문제가 있어.

#### 2 — 2026-11-07T10:03:39Z

> 1번 안이 좋겠네.

#### 3 — 2026-11-07T10:03:55Z

> 1번 안이 좋겠네. 지시 수정은 append 말고 의도에 맞게 rewrite해

#### 4 — 2026-11-07T12:29:09Z

> 커밋하고 push

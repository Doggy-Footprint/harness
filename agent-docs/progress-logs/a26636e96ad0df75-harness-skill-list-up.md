---
session: 1acc7524-6b80-4fd0-9f22-ff54fd5c8357
before: none
previous: none
branch: engineer-call
commit: 87844dbd1527813f86ff7262d3f3bba07f8c2847
---

# Remove five installed skills (0.45.0)

## Next Session

### State
- Removed skills requirement-oracle, architecture-options, harness-import, rearrange-docs, test-audit from the payload, plus harness/bin/test_scan.py (used only by test-audit) and agent-docs/sync-state.json (written only by rearrange-docs). Remaining skills: workflow-approach, continue-on.
  - files: harness/skills, harness/bin, README.md
- workflow-approach lost its two `requirement-oracle` sentences (step 6 of Identity and lifecycle; Required format step 2); nothing else in it referenced the removed skills.
  - files: harness/skills/workflow-approach/SKILL.md
- 0.45.0 migration `migrate_drop_skills` unlinks `.claude/skills/<name>` only when it is the harness symlink `../../.agents/skills/<name>`; `apply_owned_files` deletes the unmodified `.agents/skills/<name>/` files but never removes stale skill symlinks, which is why the migration exists. Downstream `agent-docs/sync-state.json` is left in place.
  - files: installer/harness.py, harness/VERSION
- Tests for the removed skills and scanner were deleted; version asserts moved to 0.45.0.
  - files: tests/test_installer.py, tests/test_lazy_rules.py
- Tests whose `update` starts from a manifest version below 0.40.0 raise SkipTest unless `HARNESS_LEGACY_MIGRATION_TESTS=1`; the check runs inside `run_installer` (tests/test_installer.py, shared by the other test files) and the two installer calls in tests/test_comment_gate.py. The installer itself still runs every migration.
  - files: tests/legacy_migrations.py, tests/test_installer.py, tests/test_comment_gate.py

### Next Step
- The user plans to edit workflow-approach further; start from the current harness/skills/workflow-approach/SKILL.md.
  - files: harness/skills/workflow-approach/SKILL.md
- Test-suite speedup is deferred to the todo agent-docs/todos/d706c17a1d003208-speed-up-test-suite.md (git hook commits measured at about 10% of the run; per-file parallel runs are its next step).
  - files: agent-docs/todos/d706c17a1d003208-speed-up-test-suite.md

### Constraints
- "workflow-approach는 쓰지 않는다."
  - source: User Requests 3
- "테스트는 이제 안 쓰게 되는 거니 지우면 돼."
  - source: User Requests 3
- "test에서 TEXT 수정은 켜지마"
  - source: User Requests 4
- "테스트 종료하고, 0.40.0 이전 migration은 실행하지 않는 걸 기본으로 해"
  - source: User Requests 8; scope answered "테스트만" (tests only, installer unchanged) in a question card
- "test 간소화 -> todo에 적어두고 원래 하던 일 마무리 하자."
  - source: User Requests, the prompt after the subagent timing report (the last one of this session)

### Verify
- `python3 -m unittest discover -s tests -q` (without HARNESS_TEXT_TESTS) and `grep -rn -E "test-audit|test_scan|requirement-oracle|architecture-options|harness-import|rearrange-docs" harness README.md tests`
  - files: tests, harness, README.md

### Dead Ends
- none: no approach failed

### Related
- agent-docs/todos/d706c17a1d003208-speed-up-test-suite.md: test-suite timing measurements and next step
  - files: agent-docs/todos/d706c17a1d003208-speed-up-test-suite.md

## Record

### Changes
- Deleted harness/skills/{requirement-oracle,architecture-options,harness-import,rearrange-docs,test-audit}/, harness/bin/test_scan.py, tests/test_test_scan.py, tests/test_test_scan_rules.py, agent-docs/sync-state.json.
- harness/skills/workflow-approach/SKILL.md: removed the requirement-oracle mentions.
- README.md: skill list, Spec step, rearrange-docs bullet, import row.
- agent-docs/todos/d706c17a1d003208-speed-up-test-suite.md and agent-docs/todos/index.md: 2026-11-13 timing observations and new next step.
- installer/harness.py: `DROPPED_SKILLS_0450`, `migrate_drop_skills`, 0.45.0 entry in MIGRATIONS; harness/VERSION 0.45.0.
- tests: removed 16 test_installer.py members and 2 test_lazy_rules.py tests for the removed skills; migration lists gained "0.45.0"; current-version asserts set to 0.45.0; answer counts in pre-0.40.0 update tests shifted by one for the 0.45.0 prompt (test_installer.py dry-run confirmation count 37→38, TestHandoffToTodosMigration 16→17, test_doc_records.py 20→21).
- Dogfood install refreshed with `yes y | python3 installer/harness.py update . --no-commit`; empty leftover `.agents/skills/<removed>/` and `.harness/skills/<removed>/` directories deleted by hand (update removes files, not directories).
- tests/legacy_migrations.py: `skip_legacy_update`, called from `run_installer` in tests/test_installer.py and from tests/test_comment_gate.py.

### Commands
- `python3 -m unittest discover -s tests`: 1219 run, 109 skipped as pre-0.40.0 updates, no failures; test_isolation_telemetry and test_session_metrics import pytest/hypothesis, absent from the system python, and pass under `uv run --no-project --with pytest --with hypothesis`.
- `HARNESS_LEGACY_MIGRATION_TESTS=1` full run: 1319 run, 6 failures from answer counts, fixed and re-run (11 tests OK).
- `yes y | python3 installer/harness.py update . --no-commit`

### Failed Attempts
| attempt | failure evidence | cause |
| --- | --- | --- |
| `python3 installer/harness.py update . --no-commit` without input | EOFError at the 0.45.0 `Apply migration` prompt | stdin had no answer; verified by re-running with `yes y` |

### Sources
- installer/harness.py `apply_owned_files` (skill symlink creation only, no removal) and `migrate_workflow_specs` (precedent for removing the contract-workflow symlink).

### User Requests

#### 1 — 2026-11-13T05:46:44Z

> 지금 이 harness에 의해 설치되는 skill을 list up해줘. 간략한 설명도

#### 2 — 2026-11-13T05:49:33Z

> requirement-oracle, architecture-options, harness-import ,rearrange-docs 삭제할 때 의존성 문제 생기는 부분이 있나?

#### 3 — 2026-11-13T05:54:02Z

> test-audit은 같이 삭제하고, workflow-approach에서 영향을 받는 부분은 언급을 자연스럽게 삭제할 수 있겠어?
> 
> (workflow-approach도 고칠거니 제거만 되면 돼)
> 
> 테스트는 이제 안 쓰게 되는 거니 지우면 돼.
> 
> workflow-approach는 쓰지 않는다.

#### 4 — 2026-11-13T06:01:10Z

> test에서 TEXT 수정은 켜지마

#### 5 — 2026-11-13T06:04:17Z

> <task-notification>
> <task-id>blhbwxovo</task-id>
> <tool-use-id>toolu_01C66h5czPJ1hmEAj3EHpqmz</tool-use-id>
> <output-file>/private/tmp/claude-501/-Users-hwansu-orca-workspaces-harness-feat-engi-call/1acc7524-6b80-4fd0-9f22-ff54fd5c8357/tasks/blhbwxovo.output</output-file>
> <status>completed</status>
> <summary>Background command "Update current-version asserts and run the test suite" completed (exit code 0)</summary>
> </task-notification>

#### 6 — 2026-11-13T06:05:39Z

> 테스트가 왜 이렇게 오래 걸리는 거야?

#### 7 — 2026-11-13T06:06:50Z

> 테스트 종료하고, 0.43.0 이전 migration은 실행하지 않는 걸 기본으로 해

#### 8 — 2026-11-13T06:07:02Z

> 테스트 종료하고, 0.40.0 이전 migration은 실행하지 않는 걸 기본으로 해

#### 9 — 2026-11-13T06:16:05Z

> <task-notification>
> <task-id>bjwfd3v2u</task-id>
> <tool-use-id>toolu_01KStdTHbHDta5XjwgqnMMfP</tool-use-id>
> <output-file>/private/tmp/claude-501/-Users-hwansu-orca-workspaces-harness-feat-engi-call/1acc7524-6b80-4fd0-9f22-ff54fd5c8357/tasks/bjwfd3v2u.output</output-file>
> <status>completed</status>
> <summary>Background command "Run the test suite with legacy migration tests skipped" completed (exit code 1: No matches found)</summary>
> </task-notification>

#### 10 — 2026-11-13T06:17:14Z

> 실행 시간이 6분 넘던데, 시간이 오래 걸리는 문제 원인 추정해봐

#### 11 — 2026-11-13T06:19:24Z

> hook 을 거치는 커밋 테스트에서 뺄 수 있는 부분이 얼마나 있는지 서브 에이전트 시켜서 봐봐

#### 12 — 2026-11-13T06:24:58Z

> <task-notification>
> <task-id>bzogaz94l</task-id>
> <tool-use-id>toolu_01HKTUm3qjBwMjHoDDcM6yGa</tool-use-id>
> <output-file>/private/tmp/claude-501/-Users-hwansu-orca-workspaces-harness-feat-engi-call/1acc7524-6b80-4fd0-9f22-ff54fd5c8357/tasks/bzogaz94l.output</output-file>
> <status>completed</status>
> <summary>Background command "Run full suite with legacy migration tests enabled" completed (exit code 0)</summary>
> </task-notification>

#### 13 — 2026-11-13T06:32:05Z

> test 간소화 -> todo에 적어두고 원래 하던 일 마무리 하자.

#### 14 — 2026-11-13T06:33:40Z

> 주석 추가된 거 있어?

#### 15 — 2026-11-13T06:33:50Z

> push하고 PR 만들어줘

---
session: a57c23b5-f803-408b-848a-ef0b960b7dde
before: none
previous: none
branch: feat/brief-telemetry
commit: 38d9b7eedb6418b1d4298e9235cf94927134d46a
---

# Brief telemetry gaps and test telemetry leak

## Next Session

### State
- Workflow run 49bafb302bb6593c: spec v1 approved by the user on 2026-11-14; implementation not started at this entry.
  - files: agent-docs/specs/49bafb302bb6593c-brief-telemetry.md
- Test suite telemetry leak fixed: `tests/telemetry_sandbox.py` sets `HARNESS_TELEMETRY_DIR` to a temp dir for every test process that imports `legacy_migrations`; a full `tests/run_parallel.py` run left the `~/.harness/telemetry` file count unchanged (1041 before and after). The 886 empty `*T-tmp*.session-lock` files were deleted.
  - files: tests/telemetry_sandbox.py, tests/legacy_migrations.py

### Next Step
- Start the run (spec status active, `spec_lifecycle.py start`, `workflow_marker.py start`), emit implement_test, dispatch implementer and test-implementer.
  - files: agent-docs/specs/49bafb302bb6593c-brief-telemetry.md

### Constraints
- "Brief telemtry는 지금으로서는 나만, 앞으로는 여러 사람의 기록을 digest해서 처리하여 insight를 추출하는 용도로 사용될거야. 내가 개인적으로 보고 파악하는데도 사용할거야. 그러니 둘 다 필요해. 대시보드까지 작업에 넣고"
  - source: User Requests 2
- "나눠서 진행해, 추천 필드는 전부 배제(포인터 있으니 복원 가능한 게 이유)"
  - source: User Requests 5
- "생각해보니 이미 있는 값을 넣지 않을 이유도 없지. 파서를 잘 만들어줘."
  - source: User Requests 7

### Verify
- `uv run --python 3.12 --with-requirements analytics/requirements.txt --with pytest --with hypothesis python tests/run_parallel.py`, counting `ls ~/.harness/telemetry | wc -l` before and after; the count must not change.
  - files: tests/telemetry_sandbox.py, tests/legacy_migrations.py

### Dead Ends
- Running analytics tests with `/Users/hwansu/tools/harness/.venv` fails 58 tests with `Router.__init__() got an unexpected keyword argument 'on_startup'` (starlette and fastapi versions mismatch); use uv with `analytics/requirements.txt`.
  - files: analytics/requirements.txt
- Extra transcript-parser fields (assumption list, dimension tokens, reply latency, parse status, and others) were proposed and rejected by the user: the session id and tool_use_id pointer lets the original text be recovered.
  - files: agent-docs/todos/b2373e0fdc356594-brief-transcript-parser.md

### Related
- agent-docs/specs/49bafb302bb6593c-brief-telemetry.md
  - files: agent-docs/specs/49bafb302bb6593c-brief-telemetry.md
- agent-docs/todos/b2373e0fdc356594-brief-transcript-parser.md
  - files: agent-docs/todos/b2373e0fdc356594-brief-transcript-parser.md
- agent-docs/todos/e77323782c45bbfb-brief-telemetry-gaps.md
  - files: agent-docs/todos/e77323782c45bbfb-brief-telemetry-gaps.md
- agent-docs/todos/stale/e00f26d26c7ef940-tests-write-real-telemetry-dir.md
  - files: agent-docs/todos/stale/e00f26d26c7ef940-tests-write-real-telemetry-dir.md
- agent-docs/facts/67ac615b0c9ad3aa-consumers-brief-telemetry-personal-dashboard.md
  - files: agent-docs/facts/67ac615b0c9ad3aa-consumers-brief-telemetry-personal-dashboard.md
- agent-docs/facts/e06d861b6fec1853-roadmap-telemetry-multi-person-digest.md
  - files: agent-docs/facts/e06d861b6fec1853-roadmap-telemetry-multi-person-digest.md

## Record

### Changes
- agent-docs/facts/67ac615b0c9ad3aa-consumers-brief-telemetry-personal-dashboard.md
- agent-docs/facts/e06d861b6fec1853-roadmap-telemetry-multi-person-digest.md
- agent-docs/specs/49bafb302bb6593c-brief-telemetry.md
- agent-docs/todos/b2373e0fdc356594-brief-transcript-parser.md
- agent-docs/todos/index.md
- agent-docs/todos/stale/e00f26d26c7ef940-tests-write-real-telemetry-dir.md: marked stale (leak fixed)
- tests/telemetry_sandbox.py: new; sets HARNESS_TELEMETRY_DIR to a per-process temp dir removed at exit
- tests/legacy_migrations.py: imports telemetry_sandbox

### Commands
- leak check: T-tmp lock count 879 → 886 across one suite run before the fix; 886 → 886 and total 1041 → 1041 after it
- `find ~/.harness/telemetry -maxdepth 1 -name '*T-tmp*.session-lock' -size 0 -delete` (886 files, all empty)

### Failed Attempts
| attempt | failure evidence | cause |
| --- | --- | --- |
| analytics tests under `/Users/hwansu/tools/harness/.venv` | 58 failed, `Router.__init__() got an unexpected keyword argument 'on_startup'` | starlette/fastapi version mismatch in that venv (verified: passes under uv with analytics/requirements.txt) |
| propose extra transcript-parser fields | user: "추천 필드는 전부 배제(포인터 있으니 복원 가능한 게 이유)" | user rejection (verified) |
| brief event fields Tier 1 + pointer | user moved to Tier 2 at the approval brief: "이미 있는 값을 넣지 않을 이유도 없지" | user change (verified) |

### Sources
- harness/lib/session_metrics.py `_state_lock()`: creates `<slug>-<identity>.session-lock` in the telemetry dir and never removes it (leak source)
- harness/lib/telemetry.py `_telemetry_directory()`: honors HARNESS_TELEMETRY_DIR

### User Requests

#### 1 — 2026-11-14T01:13:37Z

> /workflow-approach 
> brief-telemetry-gaps.md
> tests-write-real-telemetry-dir.md
> 이 두가지를 수행할거야
> 새로운 브랜치로 체크아웃해서 작업해

#### 2 — 2026-11-14T01:20:39Z

> Brief telemtry는 지금으로서는 나만, 앞으로는 여러 사람의 기록을 digest해서 처리하여 insight를 추출하는 용도로 사용될거야. 내가 개인적으로 보고 파악하는데도 사용할거야. 그러니 둘 다 필요해.
> 대시보드까지 작업에 넣고, 이벤트 필드는 tier별로 보여줘
> 

#### 3 — 2026-11-14T01:32:50Z

> 3. 삭제
> 2. non-LLM 파서로 기술적 결정 축 제안, 이해한 내용을 저장(추가로 넣으면 좋을 필드 추천 받음) - 100%는 목표가 아님, 동향 파악 정도면 ok, 원문을 찾을 수 있는 포인터도 같이 남길것 (세션id + 턴 등)
> 1. Tier 1 + 2에서도 말한 포인터.

#### 4 — 2026-11-14T01:42:31Z

> 나눠서 진행해, 필드는 전부 배제(포인터 있으니 복원 가능한 게 이유)

#### 5 — 2026-11-14T01:42:43Z

> 나눠서 진행해, 추천 필드는 전부 배제(포인터 있으니 복원 가능한 게 이유)

#### 6 — 2026-11-14T01:47:29Z

> <task-notification>
> <task-id>bdq3megkl</task-id>
> <tool-use-id>toolu_01KJrjqqtiQKXqAPa5WVCkay</tool-use-id>
> <output-file>/private/tmp/claude-501/-Users-hwansu-orca-workspaces-harness-fix-spec/13e4ceef-b5dc-4493-b345-88b38b127184/tasks/bdq3megkl.output</output-file>
> <status>completed</status>
> <summary>Background command "Run baseline test suites and count leaked files" completed (exit code 0)</summary>
> </task-notification>

#### 7 — 2026-11-14T02:27:00Z

> 이벤트 필드 - 다르긴 한데, 뭐 그렇게 하자. 생각해보니 이미 있는 값을 넣지 않을 이유도 없지. 파서를 잘 만들어줘.
> 
> metamorphic testing은 모르니까 간단히 설명 부탁해

#### 8 — 2026-11-14T03:11:25Z

> 승인

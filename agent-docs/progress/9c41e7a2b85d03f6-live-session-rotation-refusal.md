---
session: 17233f01-50e1-4880-b898-8446cabc8bdf
before: agent-docs/progress-logs/014f982c329b53af-post-merge-committed-copies.md
previous: none
branch: fix/progress
commit: 8516bd1b2ea03a41591c2f11417ec5af7571bf25
---

# Narrow the live-session rotation refusal; keep subagent hand-backs out of User Requests

## Next Session

### State
- Done: rotation is refused only when a progress to be moved belongs to a session whose claude process is still running (session id now recorded in the `.harness/sessions/.running/<pid>` marker); legacy/malformed markers and progress without `session:` keep the 0.34.2 refusal. Harness 0.34.3, spec complete and archived.
  - commit: 82d76210effd63a9853d27b75e177eb708100fb3; files: harness/hooks/progress_hook.py, harness/hooks/session_lock.py, installer/harness.py, harness/instructions/harness-block.md, agent-docs/spec-logs/48b8b8950d2e14c7-live-session-rotation-refusal.md
- Done: prompts starting with `<agent-message from=` (subagent hand-backs) are not recorded and are left out when `### User Requests` is rendered (harness 0.34.4). Summarizing long user prompts was dropped by the user.
  - commit: 82d76210effd63a9853d27b75e177eb708100fb3; files: harness/lib/progress.py, harness/hooks/progress_hook.py, harness/instructions/harness-block.md, installer/harness.py

### Next Step
- none: both requested changes are implemented and verified.
  - commit: 82d76210effd63a9853d27b75e177eb708100fb3; files: none

### Constraints
- "응 그 방향으로 구현해줘"
  - source: ### User Requests #3
- "회고 중에 다시 파악하는 비용이 비싸지 않은 건 제외. 그 다음 승인. 커밋/푸시/RP 까지"
  - source: ### User Requests #7
- "요약 기능은 빼고, 하위 에이전트 보고가 들어오는 것만 빼줘"
  - source: ### User Requests #12

### Verify
- `uv run --with pytest --with hypothesis python -m pytest tests -q -p no:cacheprovider` passed: 1016 passed, 2005 subtests passed (after the 0.34.4 change). `python3 -m unittest discover -s tests` cannot import test_session_metrics.py and test_isolation_telemetry.py without pytest/hypothesis.
  - commit: 82d76210effd63a9853d27b75e177eb708100fb3; files: tests/test_progress.py, tests/test_installer.py

### Dead Ends
- Removing the one-progress limit was analyzed and not pursued: `before:`, near-duplicate checks, `/continue-on` default target, ended-session detection, and pre-commit User Requests sync depend on it.
  - commit: 82d76210effd63a9853d27b75e177eb708100fb3; files: harness/lib/progress.py, harness/bin/progress.py, harness/git/sync_progress.py, harness/git/verify_rules.py

### Related
- agent-docs/spec-logs/48b8b8950d2e14c7-live-session-rotation-refusal.md
  - commit: 82d76210effd63a9853d27b75e177eb708100fb3; files: agent-docs/spec-logs/48b8b8950d2e14c7-live-session-rotation-refusal.md

## Record

### Changes
- harness/hooks/session_lock.py: SessionStart writes the marker as JSON `{"session_id", "source"}`; `marker_session()` reads it, None for anything else.
- harness/hooks/progress_hook.py: `other_live_sessions()` returns (pid, session id); `rotation_refusal()` refuses only for files owned by a live session, or when a live marker or the file has no session id.
- installer/harness.py: 0.34.3 migration `migrate_live_session_rotation`; harness/VERSION 0.34.3; Progress Rule sentence in harness/instructions/harness-block.md; regenerated `.harness/` and AGENTS.md with `update .`.
- harness/lib/progress.py `is_agent_message()` and `state_prompts()` filter; harness/hooks/progress_hook.py skips recording such prompts; User Requests paragraph of the Progress Rule rewritten; 0.34.4 migration; four TestPromptRecording tests.
- tests: new TestLiveSessionRotationRefusal (R1-R13, M1-M6, E1-E5, P1-P4) and VO5 installer tests; version-bump updates in six test files.
- Removed the parameter docstrings of `put_marker` and `setup_rotation` in tests/test_progress.py; kept only the external-system comment on `AGENT_MESSAGE_PREFIX` in harness/lib/progress.py.

### Commands
- `echo y | python3 installer/harness.py update .` (the update prompt raises EOFError without stdin).
- Hand mutations m1-m12 via `.harness/bin/seed.py backup/restore`, all detected after correction batch 2.
- Removed spec-id-only test comments flagged by the pre-commit comment warning; tests/test_progress.py and tests/test_installer.py re-run: 352 passed, 502 subtests passed.

### Failed Attempts
| attempt | failure evidence | cause |
| --- | --- | --- |
| Test command `python3 -m unittest discover -s tests` | 9 failures, 2 import errors (EOFError in update tests, '0.34.3' != '0.34.2', No module named pytest/hypothesis) | verified: version strings and prompt counts hard-coded in other test files; runner lacked pytest/hypothesis |
| New hand-back test checked the state only after a later prompt | removing the record-time filter passed the test | verified: the render-time filter in state_prompts() dropped the entry on the next prompt; test now checks state right after the hand-back |
| First VO1 table with one live marker per case | hand mutation "check only first live marker" passed all tests | verified: no case had two live markers; fixed by R11 |

### Sources
- harness/hooks/progress_hook.py rotation_refusal, harness/hooks/session_lock.py, harness/lib/progress.py rotate, harness/bin/progress.py resolve_target, harness/git/sync_progress.py, harness/git/verify_rules.py check_progress, harness/git/post-merge

### User Requests

#### 1 — 2026-11-05T01:30:14Z

> progress 파일이 제대로 처리되지 않아서 문제로 이어지는 경우가 자주 발생해 - progress가 하나만 있을 수 있는 제한을 지우면 다른 동작에 어떤 영향을 미쳐?

#### 2 — 2026-11-05T01:33:09Z

> 최근 실패 메시지네
> 
> 두 경우 모두 아니었습니다. 이전 세션이 쓴 progress 파일은 이미 master에 반영돼 있고, 옮기기가 막힌 건 이 워크트리에서 살아 있던 다른 claude 프로세스의 잠금 때문이었습니다. 그 프로세스가 끝나 잠금이 풀렸으니 이제 progress를 다시 써서 이전 파일을 옮기겠습니다.

#### 3 — 2026-11-05T01:35:14Z

> 응 그 방향으로 구현해줘

#### 4 — 2026-11-05T01:38:44Z

> 승인

#### 5 — 2026-11-05T05:25:02Z

> 승인

#### 6 — 2026-11-05T06:02:00Z

> 회고 중에 다시 파악하는 비용이 비싸지 않은 건 제외.
> 그 다음 승인.
> 커밋/푸시/RP rr

#### 7 — 2026-11-05T06:02:03Z

> 회고 중에 다시 파악하는 비용이 비싸지 않은 건 제외.
> 그 다음 승인.
> 커밋/푸시/RP 까지

#### 8 — 2026-11-05T06:10:25Z

> 고쳐줘. 아 그리고 유저 입력이 너무 길면 요약해서 적도록 해줘. - 이러려면 SKILL 고쳐야 하지?

#### 9 — 2026-11-05T06:10:42Z

> 고쳐줘. 아 그리고 유저 입력이 너무 길면 요약해서 적도록 해줘. - 이러려면 SKILL 고쳐야 하지? 추가 정보 append말고 목적에 맞게 rewrite해줘

#### 10 — 2026-11-05T06:13:08Z

> 아 자동으로 적히는 거면 cost overhead는 많이 없겠네?

#### 11 — 2026-11-05T06:13:32Z

> 아 자동으로 적히는 거면 기존 방식은 cost overhead는 많이 없겠네?

#### 12 — 2026-11-05T06:14:55Z

> 요약 기능은 빼고, 하위 에이전트 보고가 들어오는 것만 빼줘

#### 13 — 2026-11-05T06:35:28Z

> RP은 한글로 해줘

#### 14 — 2026-11-05T06:36:53Z

> 필수인 주석만 남겨
> 
> 
> 
> <pasted_content id="571f">
> - `.harness/lib/progress.py`: line(s) 661, 662
> - `harness/lib/progress.py`: line(s) 661, 662
> - `tests/test_progress.py`: line(s) 218, 368, 369
> </pasted_content id="571f">
> 

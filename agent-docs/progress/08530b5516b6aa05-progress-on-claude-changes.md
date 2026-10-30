---
session: 67547623-25f1-4646-b667-f46c6b0cebaf
before: agent-docs/progress-logs/e73a776390393450-progress-and-continue-on.md
previous: none
branch: master
commit: 16258311a647f09f3ee84183d79028e26222e464
---

# Require progress only when Claude Code changed the project (0.34.0)

## Next Session

### State
- The progress hook now requires a progress only when this session's own tool calls changed the project: Write/Edit/MultiEdit/NotebookEdit inside the repository, or a Bash call (including a failed one) whose before/after fingerprint of HEAD, git status, and changed paths' mtime/size differs; paths under .harness/ do not count. The old check (HEAD differs from start_head or any dirty path) is removed. Work is uncommitted on master.
  - commit: 1625831; files: harness/hooks/progress_hook.py, harness/lib/progress.py, harness/hooks/hooks.spec.json, harness/instructions/harness-block.md
- Harness version is 0.34.0 with migration `migrate_progress_session_changes` (instruction strings only); this repository was updated with `python3 installer/harness.py update .`.
  - commit: 1625831; files: harness/VERSION, installer/harness.py, .harness/manifest.json, .claude/settings.json, AGENTS.md

### Next Step
- Commit the change on a branch and open a PR if the user asks; nothing is committed yet.
  - commit: 1625831; files: none
- This session's hooks were registered mid-session, so its Bash/Edit tracking only started after the update; the first session started after the update is the first live run of the new detection.
  - commit: 1625831; files: harness/hooks/progress_hook.py

### Constraints
- "progress 작성 기준을 파일 변경 → 클로드 코드에 의한 프로젝트 변경시로 바꿔 (수정, 패치 등 작업)"
  - source: user, first prompt of this session
- "이건 개인용 로그를 git에 커밋하며 쌓는 경우에 대응하기 위한거야"
  - source: user, second prompt of this session

### Verify
- Run `uv run --no-project --with pytest --with hypothesis python3 -m unittest discover -s tests`; 879 tests passed after the change (system python3 lacks pytest and hypothesis).
  - commit: 1625831; files: tests/test_progress.py, tests/test_installer.py

### Dead Ends
- none: no approach failed in this session.

### Related
- Spec log of the original progress feature, whose FR10 and A2 state the replaced "changed repository files" criterion.
  - commit: 1625831; files: agent-docs/spec-logs/388ea2d9a2de1f5f-progress-and-continue-on.md

## Record

### Changes
- harness/hooks/progress_hook.py: `modified_project` replaces `changed_repository`; PreToolUse Bash stores a fingerprint per `tool_use_id`; PostToolUse and PostToolUseFailure set `modified` in the session state.
- harness/lib/progress.py: `git_worktree_fingerprint` replaces `git_changed_paths`.
- harness/hooks/hooks.spec.json: PreToolUse Bash and PostToolUseFailure Bash for progress_hook.py; PostToolUse matcher widened to NotebookEdit and Bash.
- harness/instructions/harness-block.md: Progress Rule wording.
- installer/harness.py, harness/VERSION: 0.34.0 migration.
- tests: new Stop cases (Bash commit/modify, failed Bash, edit tools, user changes and pre-existing dirty files ignored, per-session attribution, .harness and outside paths ignored); version and prompt-count updates.
- Removed the untracked leftover agent-docs/progress-logs/e73a776390393450-progress-and-continue-on.md after the user chose to delete it, so rotation of the previous progress is not refused.

### Commands
- `python3 installer/harness.py update .`
- `uv run --no-project --with pytest --with hypothesis python3 -m unittest discover -s tests`

### Failed Attempts
| attempt | failure evidence | cause |
| --- | --- | --- |

### Sources
- none

### User Requests

#### 1 — 2026-10-30T04:00:22Z

> progress 작성 기준을 파일 변경 → 클로드 코드에 의한 프로젝트 변경시로 바꿔 (수정, 패치 등 작업)

#### 2 — 2026-10-30T04:07:37Z

> 이건 개인용 로그를 git에 커밋하며 쌓는 경우에 대응하기 위한거야

#### 3 — 2026-10-30T05:23:39Z

> 이 하네스를 설치한 다른 세션에서의 전달 사항이야. 바로 반영하지 말고 검토해봐.
> 
> 
> <pasted_content id="7246">
> # progress_hook: 세션 상태 파일 동시 갱신 경쟁 조건 수정 (0.34.0)
> 
> ## 배경
> 0.34.0부터 progress가 필요한지는 "이 세션이 도구 호출로 프로젝트를 바꿨는가"로 판정한다.
> - Bash: PreToolUse에서 `git_worktree_fingerprint`를 `bash_snapshots[tool_use_id]`에 저장하고, PostToolUse / PostToolUseFailure에서 비교해 `modified=True`를 기록한다.
> - Edit 계열: 레포 안 파일(`.harness/` 제외)이면 `modified=True`를 기록한다.
> - 이 상태는 모두 `.harness/sessions/progress-<sid>.json` 한 파일에 `update_state()`의 load → modify → write로 저장된다(`write_state`는 `os.replace`로 원자적).
> 
> ## 문제
> `update_state()`에는 잠금이 없다. 훅 프로세스 여러 개가 동 다른 쪽의 갱신을 덮어쓴다. Claude Code는 한 메시지 안의 병렬 도구 호출에 대한 훅을 동시에 실행할 수 있다.
> 
> 관찰 결과 (로컬 설치본, macOS, Python 3.12):
> - 같은 세션에서 PreToolUse(Bash) 8개를 동시에 실행했다. 4번은 4/8, 5/8, 7/8, 7/8개였다.
> - PostToolUse 8개를 동시에 실행한 뒤에도 스냅샷이 0~1개 남았다. 지워야 할 항목이 다른 쓰기에 의해 되살아난 것이다.
> - 같은 원리로 `modified=True`도 동시에 쓰인 Pre 훅의 상태에 우는 코드를 읽고 추론한 것이고, 직접 재현하지는 않았다.
> 
> 영향: 거짓 음성. 프로젝트를 바꾼 세션인데 Stop 훅이 progres 세션을 잘못 막지는 않는다. 덤으로 상태 파일에 고아 스냅샷이 쌓인다.
> 
> ## 재현 방법
> 가짜 session_id로 `progress_hook.py`에 stdin JSON을 넣어 실`session_id`, `cwd`, `tool_name`, `tool_use_id`,`tool_input`).
> 1. SessionStart
> 2. ThreadPoolExecutor로 PreToolUse(Bash, tool_use_id=p0..p7)를 동시에 실행한다.
> 3. 상태 JSON의 `bash_snapshots` 개수를 센다. 기대값은 8이다
> 4. 레포 안에 추적되지 않는 파일을 하나 만든다.
> 5. PostToolUse(Bash, p0..p7)를 동시에 실행한다.
> 6. `modified`가 True인지, `bash_snapshots`가 비었는지 확인한다.
> 7. Stop을 실행해 exit 2가 나오는지 확인한다.
> 
> ## 수정 방향 (제안)
> 공유 JSON에 대한 load → modify → write를 없애는 쪽을 권한다.                                                                                - 스냅샷은 `tool_use_id`별 파일로 둔다: `.harness/sessions/d>`. Pre 훅이 쓰고 Post 훅이 읽은 뒤 지운다.
> - 변경 여부는 표시 파일 하나로 둔다: `.harness/sessions/.running/<sid>/modified`. 만드는 동작은 몇 번 해도 같으므로 경쟁이 생기지 않는다.   - `modified_project()`는 표시 파일이 있는지만 본다.
> - 대안으로 `update_state()` 전체를 `fcntl.flock`(Windows는 `msvcrt.locking`)으로 감쌀 수 있다. 다만 prompts 등 다른 상태 쓰기도 같은 잠금을 거쳐야 한다.
> - 세션이 끝날 때 `.running/<sid>/`를 정리한다. SessionEnd 훅이나 session_lock 쪽에서 하면 된다.                                                  
> ## 함께 정리할 사소한 점                                                                                                                          1. `on_session_start`가 아직 `start_head`를 기록하지만, 0.3지우거나 용도를 정할 것.
> 2. 판정 기준이 서로 다르다. Edit 계열은 gitignore된 경로도 변경으로 치지만, Bash 지문은 `git status`를 쓰므로 무시된 파일을 보지 못한다. 한쪽으로 맞출 것. 제안: Edit도 `git check-ignore`된 경로는 제외한다.
> 3. `run_in_background` Bash는 PostToolUse가 시작 직후에 실행되므로, 그 뒤에 생기는 변경을 놓친다. 문서에 한계로 적거나 별도로 처리할 것.
> 
> ## 수정 후에도 그대로 통과해야 하는 시나리오 (0.34.0에서 확인한 동작)
> | 시나리오 | modified | Stop exit |
> |---|---|---|
> | 읽기만 하는 Bash | 없음 | 0 |
> | Bash로 레포 안에 추적되지 않는 파일 생성 | True | 2 |
> | Bash로 gitignore된 파일 생성 | 없음 | 0 |
> | Edit: 레포 안 파일 | True | 2 |
> | Edit: `.harness/` 안 파일 | 없음 | 0 |
> | Write: 레포 밖 파일 | 없음 | 0 |
> | Bash가 파일을 바꾼 뒤 실패 (PostToolUseFailure) | True |
> | Bash 8개 병렬 실행, 그중 하나가 파일 생성 | True | 2, 그리고 **스냅샷 8/8 저장, 종료 후 0개 남음** ← 지금은 실패 |
> 
> 이 시나리오들을 하네스 테스트로 추가할 것. 병렬 시나리오는 20번 반복해도 모두 통과해야 한다.   
> </pasted_content id="7246">
> 

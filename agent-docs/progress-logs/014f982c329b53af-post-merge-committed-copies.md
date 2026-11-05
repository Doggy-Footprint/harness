---
session: 7ad08bfa-d402-4180-a340-f0d73d08541a
before: agent-docs/progress-logs/08530b5516b6aa05-progress-on-claude-changes.md
previous: none
branch: master
commit: 25c608193ee1d954a984e3fb160e932fd1a73c07
---

# post-merge clears uncommitted copies of committed progress (0.34.2)

## Next Session

### State
- 0.34.2 (uncommitted on master): post-merge now handles progress files the merge added or modified. When `progress-logs/<name>` already exists, is untracked, and its blob equals a committed version of `progress/<name>` reachable from HEAD, the hook deletes that copy and moves the merged progress there. A modified progress with no existing log copy is still left in place. A tracked or non-matching log copy is kept: the hook warns for an added progress and stays silent for a modified one.
  - commit: 25c6081; files: harness/git/post-merge, installer/harness.py, harness/VERSION
- This repository is updated to 0.34.2 (`python3 installer/harness.py update .`).
  - commit: 25c6081; files: .harness/git/post-merge, .harness/VERSION, .harness/manifest.json, AGENTS.md

### Next Step
- Commit the change on a branch and open a PR if the user asks; nothing is committed yet. The first write of this progress was refused rotation while read-only session 3b6e1695 (pid 83361) held a lock; it exited before the retry.
  - commit: 25c6081; files: none

### Constraints
- "post-merge 훅 고쳐줘. 이미 커밋된 사본인거 체크하고 정리해줘"
  - source: user, third prompt of this session

### Verify
- Run `uv run --no-project --with pytest --with hypothesis python3 -m unittest discover -s tests`; 887 tests passed. `test_second_merge_of_same_branch_replaces_uncommitted_committed_copy` failed against the 0.34.1 hook and passes with 0.34.2.
  - commit: 25c6081; files: tests/test_progress.py

### Dead Ends
- none: no approach failed in this session
  - commit: 25c6081; files: none

### Related
- Previous session's progress, which added commit-time User Requests sync and was merged as 25c6081.
  - commit: 25c6081; files: agent-docs/progress-logs/08530b5516b6aa05-progress-on-claude-changes.md

## Record

### Changes
- harness/git/post-merge: reads `--name-status --diff-filter=AM`; `is_committed_copy` checks that the destination is untracked and that its `git hash-object` blob appears in `git log --raw -m HEAD -- <progress path>`. It uses awk instead of `grep -q` so `pipefail` does not turn an early grep exit (SIGPIPE on git log) into a mismatch.
- installer/harness.py, harness/VERSION: 0.34.2 migration `migrate_post_merge_committed_copies`.
- tests/test_progress.py: second merge of the same branch (fast-forward and true merge), untracked non-matching copy kept, tracked matching copy kept.
- tests/test_installer.py, test_comment_gate.py, test_doc_records.py, test_session_metrics.py, test_telemetry.py, test_workflow_markers.py: version pins and one more `update` confirmation for 0.34.2.
- Cause found before the fix (reflog 2026-10-30 15:14): after `git pull` fast-forwarded master to 53cee07, post-merge moved the 2c5f04e version of `progress/08530b5516b6aa05-progress-on-claude-changes.md` to progress-logs/. The local merge of the feature branch three seconds later restored the newer `progress/` file. Diff-filter A missed it because the file already existed at ORIG_HEAD. The user deleted the leftover copy by hand at the start of this session.

### Commands
- `python3 installer/harness.py update .`
- `uv run --no-project --with pytest --with hypothesis python3 -m unittest discover -s tests`

### Failed Attempts
| attempt | failure evidence | cause |
| --- | --- | --- |

### Sources
- none

### User Requests

#### 1 — 2026-11-04T22:28:57Z

> 지금 커밋 안 된 progress - 이거 읽어봐. 커밋해야해 버려야해?

#### 2 — 2026-11-04T22:50:16Z

> post-merge 훅 고쳐줘

#### 3 — 2026-11-04T22:50:30Z

> post-merge 훅 고쳐줘. 이미 커밋된 사본인거 체크하고 정리해줘

#### 4 — 2026-11-04T23:19:36Z

> I don't know what does 83361 do. read the content of the progress file.

#### 5 — 2026-11-04T23:44:33Z

> just commit on master

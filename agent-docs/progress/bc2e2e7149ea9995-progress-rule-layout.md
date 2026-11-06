---
session: 80076199-d6aa-420a-943f-5cfa6300040f
before: agent-docs/progress-logs/408eddc117aee747-rearrange-docs-skip-records.md
previous: none
branch: master
commit: 07958a9e2e50dd78d4baefa28e3008c8c2dcf9fb
---

# Exempt none bullets, fix contradictions, and split hook behavior in the Progress Rule

## Next Session

### State
- Done: harness 0.38.0, committed on master and pushed to origin/master at the user's request (no PR). Progress Rule in harness/instructions/harness-block.md now (a) states a `- none: <reason>` bullet is not an entry and carries no `commit:` line, (b) replaces "Never edit a progress after its session ends" with "A session edits only its own progress, never another session's" and directs parallel sessions to separate git worktrees, (c) moves hook-driven behavior to a `### Hook Behavior` list and makes the PR steps a numbered list. Migration `migrate_progress_rule_layout` announces it; `update .` regenerated `.harness/` and AGENTS.md.
  - commit: 07958a9e2e50dd78d4baefa28e3008c8c2dcf9fb; files: harness/instructions/harness-block.md, installer/harness.py, harness/VERSION, AGENTS.md
- Validation code was not changed: harness/lib/progress.py `entries()` already skips `none:` bullets, so (a) is a wording fix only.
  - commit: 07958a9e2e50dd78d4baefa28e3008c8c2dcf9fb; files: harness/lib/progress.py

### Next Step
- Items not chosen by the user from the review: overlap of Dead Ends / Failed Attempts and Changes / Commands with git history, and a shorter form for small sessions. They are policy changes left to the user.
  - commit: 07958a9e2e50dd78d4baefa28e3008c8c2dcf9fb; files: harness/instructions/harness-block.md

### Constraints
- "2, 4, 1 순서대로 진행해줘"
  - source: ### User Requests #3

### Verify
- `python3 -m unittest discover -s tests`: 881 tests, only the two hypothesis import errors; `uv run --no-project --with pytest --with hypothesis python -m unittest test_session_metrics test_isolation_telemetry` (in tests/) passed 102 tests. `python3 .harness/git/verify_rules.py` exited 0.
  - commit: 07958a9e2e50dd78d4baefa28e3008c8c2dcf9fb; files: tests/test_installer.py, tests/test_doc_records.py, tests/test_comment_gate.py, tests/test_progress_retire.py
- A Sonnet subagent read the uncommitted diff against the hook and lib code and found no runtime change beyond the version and the announce-only migration. It flagged that dropping "Never edit a progress after its session ends" changes the rule text; the user kept the new wording ("A session edits only its own progress").
  - commit: 07958a9e2e50dd78d4baefa28e3008c8c2dcf9fb; files: harness/instructions/harness-block.md, harness/hooks/progress_hook.py, harness/lib/progress.py, installer/harness.py

### Dead Ends
- none: no approach was abandoned.

### Related
- none: no other record was needed.

## Record

### Changes
- harness/instructions/harness-block.md: Progress Rule rewording and `### Hook Behavior` subsection.
- installer/harness.py: `migrate_progress_rule_layout` and the 0.38.0 MIGRATIONS entry; harness/VERSION 0.38.0.
- tests: version pins 0.37.0 -> 0.38.0, migration lists extended with 0.38.0, one more `y` answer per update through the new migration (including `"y\ny\n" * 20 -> * 21`, `* 7 -> * 8`, and the handoff decline/eof answers), dry-run confirmation count 30 -> 31; new `test_update_from_0370_announces_progress_rule_layout`.

### Commands
- `printf 'y\ny\ny\n' | python3 installer/harness.py update .`

### Failed Attempts
| attempt | failure evidence | cause |
| --- | --- | --- |
| Adding a `y` answer with `re.sub(r'input="', 'input="y\\n', ...)` | SyntaxError: unterminated string literal in tests/test_installer.py | verified: `\n` in a re.sub replacement string becomes a real newline |
| Reusing only the lines the 0.37.0 bump edited | 7 failures in tests that use `"y\ny\n" * N` or fixed handoff answers | verified: those tests had spare answers before 0.38.0 and ran out with one more migration |

### Sources
- harness/lib/progress.py (`entries`, `_is_none_item`), harness/hooks/progress_hook.py (`rotation_refusal`), commit 4fa897a test diff

### User Requests

#### 1 — 2026-11-06T07:57:44Z

> AGENTS.md Progress Rule 부분 왜 이렇게 번잡스럽게 써놧어

#### 2 — 2026-11-06T07:58:10Z

> AGENTS.md Progress Rule 부분 어떻게 생각해?

#### 3 — 2026-11-06T07:59:09Z

> 2, 4, 1 순서대로 진행해줘

#### 4 — 2026-11-06T08:33:16Z

> sonnet sub agent 불러서 기능 변경 없는지 체크 한 번만 해봐. 바로 수용하지 말고 나한테 보고하고

#### 5 — 2026-11-06T08:35:31Z

> 지금 문구로 커밋, master push

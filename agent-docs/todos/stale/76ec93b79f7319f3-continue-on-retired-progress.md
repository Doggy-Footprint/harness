# continue-on without an argument misses a progress retired to progress-logs

## Goal
`/continue-on` without an argument finds the previous session's progress also when that session retired it to `agent-docs/progress-logs/` before opening a PR.

## Observation
- `resolve_target` in `harness/bin/progress.py` without an argument looks only at files in `agent-docs/progress/`, then at the `before:` of this session's own progress there.
- Since 0.36.0, a session retires its progress to `progress-logs/` before `gh pr create`. When the next session starts on that branch, `progress/` is empty, so `show` exits 1 with "no progress to continue" unless the user passes the `progress-logs/` path.
- Example: session 26664246-d290-44aa-8b2f-9bef3d42fabf retired `agent-docs/progress-logs/3cb7a8fbae561809-import-block-and-update-commit.md` for PR #32 and left its 0.43.0 next step there.

## Next Step
- Decide how `show` picks a retired progress when `progress/` holds no other session's file (for example the most recently committed `progress-logs/` file on the current branch), then update `resolve_target` and the continue-on skill text.

## Related
- harness/bin/progress.py, harness/skills/continue-on/SKILL.md

## Progress Rule

Directory: `agent-docs/progress/`, holding at most one `<16-char-hex-id>-<kebab-case-name>.md`, the current session's. Every session in which Claude Code changes the project (edits, patches, commits, or other commands that change the working tree or HEAD) writes one and commits it with the work; files changed outside the session's own tool calls, under `.harness/`, or ignored by git, and changes (including its commit) made by `harness.py update` alone within one Bash call, do not count. One progress per session: merge into the existing one instead of writing a second. A session edits only its own progress, never another session's.

Before opening a PR from a Claude Code session:
1. Retire the progress to `agent-docs/progress-logs/` with `python3 .harness/bin/progress.py retire`.
2. Commit and push it.
3. Run `gh pr create` in its own Bash call.

After retiring, the session keeps editing its progress in `progress-logs/`.

Frontmatter: `session` (Claude Code session id), `before` (repo path of the progress moved to logs when this one was created, or `none`), `previous` (repo path of the progress this session continued through `/continue-on`, or `none`), `branch`, and the `commit` stamp. `before` records order only; `previous` records an explicit continuation.

Required file structure:

- `#` Title
- `## Next Session` with `### State`, `### Next Step`, `### Constraints`, `### Verify`, `### Dead Ends`, `### Related`
- `## Record` with `### Changes`, `### Commands`, `### Failed Attempts` (table `| attempt | failure evidence | cause |`, cause marked `verified` or `hypothesis`), `### Sources`, `### User Requests`

Every `## Next Session` bullet outside `### Constraints` is an entry followed by `  - commit: <sha checked against>; files: <comma-separated repo paths or none>`; record each entry's own commit. `### Constraints` bullets quote the user verbatim from `### User Requests` and carry `  - source: <where it was said>`. A subsection with nothing to continue holds `- none: <reason>`; a `none:` bullet is not an entry and carries no `commit:` line. `### Related` lists the exact records a later session needs; never point to records you did not check.

`### User Requests` records, masked, the prompts the user sent in this session; subagent hand-backs that arrive as prompts are left out. Hooks rewrite it when the progress is written and at each commit, which stages it, so never edit it. Pre-commit blocks keys, tokens, emails, IP addresses, and internal hostnames in `progress/` and `progress-logs/`; replace each with `[masked:<category>]`.

To continue earlier work, read only the `## Next Session` of the chosen progress and the pointers under its `### Related` (`/continue-on`); never guess related records. Re-check entries the hooks flag as stale, and ask the user whether a flagged near-duplicate was re-verified or copied.

### Hook Behavior

- When a new session writes its progress, the previous one moves to `agent-docs/progress-logs/` under the same name; a merge moves progress files it adds there too.
- A progress whose session may still be running in another process is not moved, and the new progress is refused; run parallel sessions in separate git worktrees.
- Project changes are detected per tool call; a Bash command run in the background is checked only until its tool call returns, so later changes it makes are not seen.
- `gh pr create` is blocked until the session's progress is retired, committed, and pushed, so a merged PR leaves nothing in `progress/` to move.
- A retired progress in `progress-logs/` gets the same checks and User Requests sync, and Stop blocks while it is uncommitted or unpushed.

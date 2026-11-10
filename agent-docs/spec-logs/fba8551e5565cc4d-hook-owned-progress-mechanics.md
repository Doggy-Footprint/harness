---
version: 5
run_id: fba8551e5565cc4d
status: complete
base_commit: 9f66056340134cba4dc0972319a827a32bd5be30
max_verifier_invocations: 2
commit: 6e77d1a234f20cc21dd58109bfd4e1d67171f090
---

# User Intent
| id | stakeholder | intention | observable goal |
| --- | --- | --- | --- |
| I1 | agent in a Claude Code session | Never have to know its own session id | a progress file the session writes with an unknown `session:` value ends up holding the real id without a Stop block |
| I2 | agent in a Claude Code session | Satisfy the Progress Rule in the same commit as the work | an entry recorded in the commit that also changes its listed files is fresh; no second commit is needed to clear `stale:` |
| I3 | agent in a Claude Code session | Start from a correct progress instead of composing one from the rule | the first project change of a session without a progress creates one with frontmatter, every heading, and `[harness-requires]` placeholders |
| I4 | harness user | Catch a missing or unfinished progress at the commit instead of at Stop | a Claude Code commit in a session that changed the project is blocked until its progress is staged and has no placeholders |
| I5 | harness user | Know whether the change pays off | before/after evaluation shows fewer Stop blocks, no session with two progress files, and no more turns |

# Scope
In scope: session-id claiming in the progress hook (PostToolUse, Stop) and in `harness/git/sync_progress.py`; freshness anchored to the commit that recorded each entry (`git blame`), `commit:` optional in entry metadata; near-duplicate comparison on recording commits; `[harness-requires]` placeholder findings; progress skeleton creation at the first project change (replacing the 0.41.0 reminder, which stays as the fallback when rotation is refused); a commit-time progress gate in `verify_rules.py`; `HARNESS_UPDATE_COMMIT=1` on the installer's auto-commit; Progress Rule text in `harness/instructions/progress.md`; 0.42.0 version and migration announcement; dogfood update of this repo; before/after evaluation R1.
Out of scope: synced-comment hash scope, `code_hash` and stale-move commands, rule-text injection, Rule Files table changes, record-only-session progress (all 0.43.0); Codex; rewriting existing progress files; PR #32 metadata.

# Paths
Implementation: harness/lib/progress.py, harness/hooks/progress_hook.py, harness/git/sync_progress.py, harness/git/verify_rules.py, harness/bin/progress.py, harness/instructions/progress.md, harness/skills/continue-on/SKILL.md, installer/harness.py, harness/VERSION, README.md
Tests: tests/test_hook_owned_progress.py, tests/test_progress.py, tests/test_progress_retire.py, tests/test_lazy_rules.py, tests/test_installer.py, tests/test_comment_gate.py, tests/test_doc_records.py, tests/test_telemetry.py, tests/test_session_metrics.py, tests/test_workflow_markers.py, tests/test_update_commit.py
Test command: /Users/hwansu/tools/harness/.venv/bin/python -m unittest discover -s tests
Review evidence: R1 — before/after evaluation run by main after the suite passes. Target simonw/mcp-explorer at 56910d7c6c9f7e143dadd67bf047d7650a79ffdd. Arms: before = installer at 6e77d1a234f20cc21dd58109bfd4e1d67171f090 (0.41.0), after = working-tree installer (0.42.0). Same five tasks as the 0.41.0 evaluation (T1 code change, T2 todo, T3 try-n-fail, T4 mark todo stale, T5 synced comment) × 5 repetitions × 2 arms = 50 sessions, `claude -p --model haiku --effort medium --output-format stream-json --verbose --max-budget-usd 1 --setting-sources project,local --strict-mcp-config --mcp-config '{"mcpServers":{}}'`, allowed tools `Read,Write,Edit,Glob,Grep,Bash(git *),Bash(python3 *),Bash(ls *),Bash(cat *)`, network git commands and pip disallowed. Repositories live under `/private/tmp/harness-eval/` (no session UUID in the path); scripts stay in the session scratchpad. Metrics per arm: E1 sessions with at least one Stop block; E2 sessions whose committed own progress files number 2 or more; E3 sessions whose own progress passes its arm's `progress.py check` and is in the first work commit; E4 mean first-request input tokens (incl. cache); E5 mean turns; E6 pre-commit blocks; E7 mean commits; E8 cost; E9 task rule items passing (T2–T5). Pass criteria Q6–Q9; E6–E9 reported. Rule-file reads count both the Read tool and Bash commands naming the file.
Fuzzing: none — the only new parser input is a progress file, covered by equivalence classes and the existing parser tests.
Mutation tool: none

# Signatures
harness/lib/progress.py:
- `UNCOMMITTED = "0" * 40`
- `PLACEHOLDER = "[harness-requires]"`
- `Entry` gains `anchor: str | None = None` (recording commit, `UNCOMMITTED`, or None when unknown)
- `entries(progress)` accepts metadata `  - files: <paths or none>` or `  - commit: <sha>; files: <paths or none>`
- `line_commits(repo_root: Path, path: Path) -> dict[int, str] | None` — 1-based line → commit, one key per line (a trailing newline adds none), from `git blame --porcelain` of the working-tree file; every line `UNCOMMITTED` when the path is not in HEAD; None when git fails
- `anchor_entries(entry_list, repo_root, path) -> None` — sets `anchor` from the entry's metadata line; on None from `line_commits`, falls back to the explicit `commit` (resolved) or None
- `freshness(entry_list, repo_root, path: Path) -> list[str]`
- `entry_report(parsed, repo_root, path: Path)`
- `placeholder_lines(progress) -> list[int]`
- `session_known(repo_root: Path, value: str) -> bool`
- `skeleton(session_id: str, branch: str) -> str`
- `skeleton_name(first_prompt: str | None) -> str`
harness/hooks/progress_hook.py: `claim_session(path: Path, session_id: str) -> str | None` (returns the N1 notice or None); `create_skeleton(session_id: str) -> int` replaces `first_change_reminder` as the PostToolUse no-target branch.
harness/git/verify_rules.py: `check_session_progress(errors: list)` routed to `progress.md`.

# Functional Requirements
| id | requirement | priority | source |
| --- | --- | --- | --- |
| F1 | Claim: a progress file in `agent-docs/progress/` whose `session:` value V differs from the current session S is rewritten to `session: S` when all hold: the path has no blob in HEAD; V is empty, `auto`, or not known (no `.harness/sessions/progress-<safe V>.json`, no file in HEAD's `progress/` or `progress-logs/` with `session: V`). Points: PostToolUse after Write/Edit/MultiEdit of that file (before rotation checks, notice N1; PostToolUse exits 2 whenever N1 is printed); Stop before the own-progress lookup (N1 printed with the Stop result); pre-commit `sync_progress.py` with S from `CLAUDE_CODE_SESSION_ID`, then the existing User Requests sync and staging | must | I1 |
| F2 | Entry metadata is `  - files: <paths or none>`; `  - commit: <7+ hex>; files: <...>` stays valid. Item text excludes both metadata forms. Missing/invalid-metadata finding wording is free but shows the `  - files:` form | must | I2 |
| F3 | Freshness: an entry's anchor is the commit blame assigns to its metadata line. Anchor `UNCOMMITTED` → fresh. Otherwise stale when a listed path (or a path under a listed directory) changed in a commit reachable from HEAD and not from the anchor: `stale: changed <changed path> in <7-char sha>`. Entries with no metadata or invalid metadata keep their format finding; when blame fails, the explicit commit (if any) is the anchor; with neither, the status is `stale: no recording commit` | must | I2 |
| F4 | Near-duplicate: compared on anchors instead of explicit commits; skipped when either anchor is None; predecessor anchors come from blame of the predecessor file, falling back to its explicit commit | must | I2 |
| F5 | Placeholders: every line outside fenced blocks and outside `### User Requests` containing `[harness-requires]` is a format finding `unfilled placeholder [harness-requires]; replace it with content` (in `format_findings`, so PostToolUse, `progress.py check`, and pre-commit report it) | must | I3, I4 |
| F6 | Skeleton (PostToolUse only; PostToolUseFailure never creates one): PostToolUse with no progress target, session S marked modified, and no own progress in `progress/` or `progress-logs/` → once per session (marker `skeleton` in the change dir): if `rotation_refusal` refuses the new path, print the 0.41.0 reminder S1 instead; else write `progress/<skeleton_name>.md` with `skeleton(S, branch)`, rotate, sync User Requests, print N2 (plus the existing moved notice when a file was moved), exit 2 | must | I3 |
| F7 | `skeleton_name` (returned without `.md`): 16 random lowercase hex, `-`, then the first five `[a-z0-9]+` runs of the lowercased first recorded prompt joined by `-`, or `session` when none | must | I3 |
| F8 | Stop: own progress holding placeholders blocks with S8 before the existing `## Next Session` entry check. With `stop_hook_active` true, Stop applies the claim silently and returns 0, as for every Stop check. N1 at Stop exits 2 | must | I4 |
| F9 | Commit gate (`check_session_progress`): active only when `CLAUDE_CODE_SESSION_ID`=S is non-empty, `HARNESS_UPDATE_COMMIT` is not `1`, `.harness/sessions/progress-<safe S>.d/modified` (`progress.change_dir`) exists, and no `MERGE_HEAD`, `CHERRY_PICK_HEAD`, `REVERT_HEAD`, `rebase-merge`, or `rebase-apply` exists in the git dir. Then: no own progress in `progress/` or `progress-logs/` → G1; own progress whose index blob differs from the working-tree file (including untracked) → G2; own progress in `progress-logs/` with format findings → each finding as for `progress/` files. Rule file `progress.md` | must | I4 |
| F10 | Installer auto-commit runs `git commit` with `HARNESS_UPDATE_COMMIT=1` | must | I4 |
| F11 | `progress.md` rule text: metadata `  - files:`; `commit:` optional; freshness from the recording commit; `session:` is filled by the hook (write `auto` when unsure); hook behavior bullets for the skeleton, the claim, and the commit gate; the "Write `<16-hex-id>-<kebab-name>.md`" wording in Stop and gate messages is kept only where no own progress exists | must | I1–I4 |
| F12 | 0.42.0 version; migration registered last with S6-style lines (see S9); `AGENTS.md` unchanged; dogfood update; `continue-on` skill and README wording that describes `commit:` metadata or stale meaning updated | must | I4 |

Exact strings:
- N1: `harness: set \`session: {S}\` in {label}; \`{V}\` is not a session of this checkout.` (`{V}` printed as `(empty)` when empty)
- N2: `harness: this session changed the project and had no progress, so {label} was created. Read .harness/instructions/progress.md, replace every [harness-requires] in {label}, and commit it with the work.`
- S1 (unchanged from 0.41.0): `harness: this session changed the project and has no progress yet. Read .harness/instructions/progress.md, then write {progress_rel}/<16-hex-id>-<kebab-name>.md so it is committed with the work.`
- S8: `harness: {label} still holds [harness-requires] placeholders. Replace them following .harness/instructions/progress.md before stopping.`
- G1: `session {S} changed the project but no progress in {progress_rel}/ or {logs_rel}/ has \`session: {S}\`; write one and stage it with this commit`
- G2: `{label}: progress of session {S} is not staged with this commit; run \`git add {label}\``
- S9 (migration lines, in order): `progress hook: a progress written with an unknown session id gets this session's id`, `progress hook: the first project change creates the session's progress with [harness-requires] placeholders`, `progress entries: \`  - files:\` alone is enough; an entry is stale only when a listed file changed after the commit that recorded it`, `pre-commit: a Claude Code commit in a session that changed the project needs its progress staged`, `no data is migrated; AGENTS.md is unchanged`
- Skeleton template (`{S}`, `{branch}` substituted; `before` set by rotation; the hook's commit stamp adds `commit: <HEAD>` to the frontmatter as for every agent-docs record):

```
---
session: {S}
before: none
previous: none
branch: {branch}
---

# [harness-requires] title of this session's work

## Next Session

### State
- [harness-requires] what is done and verified
  - files: none

### Next Step
- [harness-requires] what the next session does first
  - files: none

### Constraints
- none: [harness-requires] quote user constraints from ### User Requests with `  - source:`, or state that there are none

### Verify
- [harness-requires] commands that re-check the state
  - files: none

### Dead Ends
- none: [harness-requires] failed approaches, or state that there are none

### Related
- none: [harness-requires] records the next session needs, or state that there are none

## Record

### Changes
- [harness-requires]

### Commands
- [harness-requires]

### Failed Attempts
| attempt | failure evidence | cause |
| --- | --- | --- |

### Sources
- [harness-requires]

### User Requests
```

# Errors
- git unavailable in PostToolUse/Stop — existing "git unavailable" messages; no claim, no skeleton; exit as today.
- blame fails (shallow clone, git error) — anchors fall back per F3/F4; no exception escapes; `progress.py check` exit reflects findings only.
- skeleton write or marker write fails (OSError) — exit 0, no message, no traceback; next PostToolUse tries again only if the marker was not created.
- rotation refused at skeleton time — S1 printed once (marker set); no file written.
- claim target unreadable or frontmatter invalid — no claim; existing frontmatter message path.
- commit gate: git dir lookup fails — gate inactive (no error added).
- any exception in hooks — exit 0 (existing `main` guard).

# Cases
| id | level | input / state | expected result |
| --- | --- | --- | --- |
| C1 | normal | Write of untracked `progress/x.md` with `session: 26664246-…` (no state file), current S | file holds `session: S`; N1; rotation/sync proceed as for S |
| C2 | normal | same with `session: auto` and with empty `session:` | claimed; N1 for `auto`; empty handled (N1 with `(empty)`) |
| C3 | boundary | V has a state file, or V owns a file in HEAD, or path is in HEAD | no claim (no N1, `session:` unchanged; an empty value in a HEAD path is still filled by rotation without N1, as in 0.41.0); other behavior as 0.41.0 |
| C4 | edge | skeleton exists for S; agent writes second untracked file with unknown V | claimed to S, then the existing "already owns … merge" refusal; skeleton not moved |
| C5 | normal | Stop with untracked own-intended file holding unknown V, project modified | claimed; no "no file has session" block; N1 shown |
| C6 | normal | pre-commit with `CLAUDE_CODE_SESSION_ID`=S and staged untracked progress holding V unknown | file rewritten to S and staged |
| C7 | normal | entry with `  - files: a.py` committed in the same commit as a change to `a.py` | fresh |
| C8 | normal | entry committed in commit K; later commit changes `a.py` | `stale: changed a.py in <sha>` |
| C9 | boundary | uncommitted entry line; listed file changed in HEAD history | fresh |
| C10 | edge | progress moved from `progress/` to `progress-logs/` in a commit (rename), entry lines unchanged | anchors follow the rename (commit that recorded the entry) |
| C11 | edge | legacy `commit: <sha>; files:` entry whose sha is not an ancestor (squash) | anchor from blame → fresh unless a listed file changed after the recording commit |
| C12 | error | git blame fails | explicit commit used as anchor; neither → `stale: no recording commit` |
| C13 | normal | first modifying Edit, no own progress, rotation allowed | skeleton written with exact template, rotation done, User Requests synced, N2, exit 2 |
| C14 | boundary | second modifying call after skeleton | nothing printed |
| C15 | error | rotation refused (live other session) | S1 once, no file |
| C16 | normal | Stop with skeleton untouched | S8, exit 2 |
| C17 | normal | `progress.py check` on skeleton | one placeholder finding per `[harness-requires]` line |
| C18 | normal | commit gate: S set, modified, own progress staged and clean | commit allowed |
| C19 | error | gate: no own progress | G1, exit 1, `Rule files: .harness/instructions/progress.md` |
| C20 | error | gate: own progress unstaged change / untracked | G2 |
| C21 | boundary | gate inactive: env unset; `HARNESS_UPDATE_COMMIT=1`; not modified; MERGE_HEAD present | no gate error |
| C22 | normal | `harness.py update` auto-commit inside a modified session env | commit succeeds |
| C23 | normal | `skeleton_name("Add a --sort flag to list")`, Korean-only prompt, None | `<hex>-add-a-sort-flag-to`, `<hex>-session`, `<hex>-session` |
| C24 | normal | update from 0.41.0 | S9 lines in order after the version announcement; AGENTS.md byte-identical; doctor 0 |
| C25 | edge | skeleton write raises OSError | exit 0, no traceback |

# Quality Applicability
| ISO/IEC 25010:2023 characteristic | applicable | rationale |
| --- | --- | --- |
| Functional suitability | yes | rule outcomes must be correct |
| Performance efficiency | yes | blame adds a git call to every progress check; R1 tokens/turns |
| Compatibility | yes | existing progress files and installs keep working |
| Interaction capability | yes | messages must lead to one fix without a second file |
| Reliability | yes | hooks must not crash or block on git failure |
| Security | yes | claiming must not take over another live session's progress |
| Maintainability | yes | one freshness definition; rule text matches behavior |
| Flexibility | no | configured progress dirs already flow through `PATHS` |
| Safety | no | no physical or user-harm surface |

# Quality Requirements
| id | characteristic / subcharacteristic | target and context | measure method / inputs / unit | threshold and direction | evidence: automated, review, mutation | source |
| --- | --- | --- | --- | --- | --- | --- |
| Q1 | Compatibility / co-existence | 0.41.0 progress with legacy `commit:` entries | findings from `progress.py check` before vs after on a fixture committed in one commit with its work | after ≤ before | automated V9 | I2 |
| Q2 | Reliability / fault tolerance | blame failure, OSError on skeleton, git missing | exit codes, `Traceback` count | hook exit 0 or documented code; 0 tracebacks | automated V10 | Errors |
| Q3 | Security / integrity | a file not claimed per F1 (path in HEAD, or V known) | `session:` value and N1 presence before vs after PostToolUse/Stop/pre-commit; the existing commit stamp, User Requests sync, and rotation's filling of an empty `session:` still apply | `session:` unchanged except the pre-existing empty-value fill; no N1 | automated V2 | I1 |
| Q4 | Performance efficiency / time behaviour | `progress.py check` on a 40-entry progress in a 200-commit repo | wall time, s | ≤ 2.0 | automated V11 | I2 |
| Q5 | Maintainability / modifiability | `progress.md` and hook messages | strings `commit: <sha checked against>` and `stale: not ancestor` in `harness/` | 0 | automated V12 | F11 |
| Q6 | Interaction capability / user error protection | R1 E1 | sessions with ≥1 Stop block, after arm | ≤ 3 of 25 | review R1 | I1, I4 |
| Q7 | Functional suitability / functional correctness | R1 E2 | sessions with ≥2 committed own progress files, after arm | 0 of 25 | review R1 | I1 |
| Q8 | Functional suitability / functional correctness | R1 E3 | sessions passing, after arm | ≥ 22 of 25 and ≥ before | review R1 | I2, I3 |
| Q9 | Performance efficiency / resource utilization | R1 E4, E5 | mean first-request tokens; mean turns | tokens ≤ before + 500; turns ≤ before | review R1 | I5 |

# Verification Obligations
| id | parent requirement/Case ids | variant and target surface | test layer and selection policy | ISO/IEC/IEEE 29119-4 technique | coverage items | coverage target | observation and expected result | evidence procedure |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| V1 | F1, C1–C6 | progress_hook subprocess (PostToolUse, Stop) and `sync_progress.py` in temp repos | integration | decision table | conditions: path in HEAD (y/n); V empty/auto/unknown/state-file/HEAD-owned/equal S; point PostToolUse/Stop/pre-commit → 13 rules listed by the test-implementer from these | 100% | `session:` value, N1 exact, exit code (2 whenever N1 is printed at PostToolUse or Stop); Stop with `stop_hook_active` true and an unknown-V file: claimed, no N1, exit 0 | Test command |
| V2 | F1, C3, Q3 | known V variants | integration | equivalence partitioning | state file; HEAD-owned; path in HEAD | 100% | bytes unchanged | Test command |
| V3 | F2, F3, C7–C9, C11 | `progress.freshness` / `progress.py check` in temp repos | integration | equivalence partitioning + boundary value analysis | same-commit; later change; uncommitted; directory listing; `none`; legacy sha non-ancestor; change exactly at anchor vs one after; item text (`Entry.text` from `entries`) excludes the `  - files:` line and the legacy `  - commit: …; files:` line | 100% | status strings; item text | Test command |
| V4 | F3, C10 | rename via retire commit | integration | scenario | retire then later unrelated commit; retire then change of a listed file | 100% | fresh / stale | Test command |
| V5 | F3, F4, C12 | blame failure (simulated by a non-git dir or patched git) | integration | error guessing | blame fails with and without explicit commit | none — experience-based | fallback statuses | Test command |
| V6 | F4 | near-duplicates | unit/integration | equivalence partitioning | same anchor; different anchors similar; uncommitted vs committed predecessor; anchor None on both sides; anchor None on one side only | 100% | flagged or not | Test command |
| V7 | F5, F6, F7, F8, C13–C17, C23 | skeleton path | integration | state transition | no-progress→skeleton (N2); skeleton→next call (silent); refused→S1 once; skeleton→Stop (S8); filled→Stop (pass); name variants; Stop with placeholders and an empty `## Next Session` → S8 (not the entries message); Stop with `stop_hook_active` true and placeholders → exit 0 | 100% | file text equals template, messages exact | Test command |
| V8 | F9, F10, C18–C22 | `verify_rules.py` / real `git commit` in temp repos with env | integration | decision table | env unset; update flag; not modified; merge/cherry-pick/revert/rebase state; no progress; unstaged; untracked; staged clean; logs file with format finding; C22 with the modified marker asserted present and the same fixture blocked (G1) for a plain `git commit` without the flag | 100% | exit code, G1/G2 exact, rule-files line | Test command |
| V9 | Q1 | legacy fixture | integration | scenario | fixture committed with its work in one commit | 100% | findings count after ≤ before (0) | Test command |
| V10 | Errors, C25, Q2 | OSError and git failures | integration | error guessing | skeleton write OSError; marker OSError; git missing for claim; blame failure; gate with `git rev-parse --git-dir` failing (gate inactive, no gate error, no Traceback); claim target with invalid frontmatter (no claim, existing invalid-frontmatter message) and unreadable claim target (no claim, no Traceback) | none — experience-based | exit 0/2 per Errors, no Traceback | Test command |
| V11 | Q4 | timing fixture | integration | boundary value analysis (2-value at 2.0 s) | 40 entries, 200 commits | 100% | elapsed ≤ 2.0 s | Test command |
| V12 | F11, F12, Q5 | text of `harness/**`, README, skill | unit | error guessing | old metadata wording; `stale: not ancestor`; S9 strings; F11 content of `harness/instructions/progress.md`: contains `[harness-requires]`, `` `auto` ``, `  - files:`, `does not decide freshness`, `staged`, and `harness.py update`; installed `.harness/instructions/progress.md` equals `harness/instructions/progress.md` after install; README contains `[harness-requires]` and not `한 번 안내` | none — experience-based | 0 matches; strings present; equality | Test command; `continue-on` wording and the dogfood update are review evidence by main (V16) |
| V13 | F12, C24 | update from a 0.41.0 install | end-to-end | scenario | announcement order, AGENTS.md bytes, doctor | 100% | all hold | Test command |
| V14 | F12 | version pins in existing tests | unit | equivalence partitioning | assertions pinned to 0.41.0 as current or last migration | 100% | updated | Test command |
| V15 | Q6–Q9 | R1 | review | scenario | 5 tasks × 2 arms × 5 repetitions | 100% completed or recorded as errored | thresholds | R1 |
| V16 | F12 | `harness/skills/continue-on/SKILL.md`; this repo after `update . --no-commit` | review | scenario | continue-on states the anchor-based stale meaning; `doctor .` | 100% | sentence present; exit 0 | main reads the skill text and runs doctor after the dogfood update |

# Assumptions and Defaults
| id | decision | evidence and uncertainty | brief v<n> — approved / vetoed → <answer> / user answer |
| --- | --- | --- | --- |
| A1 | All seven countermeasures accepted; split into 0.42.0 (claim, freshness, skeleton, commit gate) and 0.43.0 (generators, hash scope, injection, record-only sessions) | size | user answer ("대책 전부 수용해도 좋을 것 같네.") for scope; split brief v1 — approved |
| A2 | Record-only sessions: hook writes a minimal progress (0.43.0) | — | user answer ("1. (a)") |
| A3 | `code_hash` limited to tagged blocks with data migration (0.43.0) | — | user answer ("2. (a)") |
| A4 | Rule Files table shortened to file + when to read; rule text injected by hooks (0.43.0) | — | user answer ("3. (a)") |
| A5 | Freshness anchor is the blame commit of the metadata line; the explicit `commit:` no longer decides freshness | squash/rebase made every sha "not ancestor" | brief v1 — approved |
| A6 | Placeholder token `[harness-requires]` | `TODO` occurs in legitimate content | user answer ("[fill] -> [harness-requires]") |
| A7 | Claim only for paths not in HEAD and unknown V | protects committed and live sessions' files | brief v1 — approved |
| A8 | Gate keyed on `CLAUDE_CODE_SESSION_ID` (set in Claude Code Bash, checked in this session) and the modified marker | subagent env id may differ from the parent's; then the gate stays inactive | brief v1 — approved |
| A9 | R1 repositories under `/private/tmp/harness-eval/` instead of the scratchpad | scratchpad path contains the session UUID, which 14–16 of 25 sessions copied into `session:` | brief v1 — approved |
| A10 | R1 allows `Bash(cat *)`; `rm`/`mv` stay disallowed (`git mv`/`git rm` are covered by `Bash(git *)`) | two 0.41.0 T4 failures came from `rm`/`mv` denials | brief v1 — approved |
| A11 | Roles use the installed default model (sonnet, effort medium); R1 sessions use haiku, effort medium | no task-specific reason | user answer ("평가 세션은 haiku-medium") for R1; brief v1 — approved for roles |
| A12 | Thresholds Q4 2.0 s, Q6 ≤ 3/25, Q8 ≥ 22/25, Q9 +500 tokens | 0.41.0: 18–20 Stop blocks, 32/45 raw | brief v1 — approved |

# Traceability
| requirement id | Case ids | obligation ids | evidence procedure |
| --- | --- | --- | --- |
| F1 | C1–C6 | V1, V2 | Test command |
| F2 | C7 | V3 | Test command |
| F3 | C7–C12 | V3, V4, V5 | Test command |
| F4 | — | V6 | Test command |
| F5 | C17 | V7 | Test command |
| F6, F7 | C13–C15, C23, C25 | V7, V10 | Test command |
| F8 | C16 | V7 | Test command |
| F9, F10 | C18–C22 | V8 | Test command |
| F11, F12 | C24 | V12, V13, V14 | Test command |
| Q1–Q5 | — | V9, V10, V2, V11, V12 | Test command |
| Q6–Q9 | — | V15 | R1 |

# Workflow Control
| item | value |
| --- | --- |
| correction batches used | 2 |
| verifier invocations | 2 |
| open finding ids | none |

Audit state (one entry per obligation; retain prior decisions in the execution ledger):
| obligation id | spec version | evidence references and revision | accepted / open / invalidated / pending | rationale and mutation outcome | dependencies and reopening evidence |
| --- | --- | --- | --- | --- | --- |

Execution ledger (append attempts; preserve failed approaches):
| attempt | finding / failure signature | cause hypothesis | changed approach / new evidence | result / disposition |
| --- | --- | --- | --- | --- |
| 1 | test-run-1: 19 failures, 1 error of 1166 | test defects (gate helper pops the flag after applying it; missing migration `y`; c9_ep5 count; 0.41.0 verbatim/README pins; metadata regex; empty-session exit code), spec gaps (Q3 bytes vs stamp/sync/empty fill; skeleton stamp), implementation defect (`line_commits` counts a line after the trailing newline) | spec v3; correction batch 1 to both roles | test-run-2: 1166 tests OK (484 s) |
| 2 | verifier 1 (retry): EG1 Stop exit code and `stop_hook_active` unobserved; EG2 C22 passes without the modified marker; EG3 item text unobserved; SC1 two Errors rows unmapped; SC2 F11/F12 text unverified | evidence gaps and spec omissions | spec v4; correction batch 2 to test-implementer | test-run-3: 1177 tests OK (468 s); N9 rerun detected by 10 tests |
| 3 | hand mutations N1–N10 on tests/test_hook_owned_progress.py (strongest classes: claim guards ×2, gate guards ×2, anchor source, near-duplicate comparison, placeholder scope, skeleton once-marker, status sha length, Stop placeholder block) | — | `.harness/bin/seed.py` backup/restore per mutation | 9/10 detected; N9 (status prints the full sha) survived → sent with batch 2 |
| 4 | verifier 2: pass, V1–V14 accepted, no blocking finding; advisory notes on marker-failure retry, git-dir test exit code, malformed metadata, directory status path | — | V16 by main: `update . --no-commit` applied, `doctor .` exit 0, AGENTS.md unchanged, continue-on states the anchor-based stale meaning | V1–V14, V16 accepted; V15 (R1) pending |
| 5 | R1 first pass (50 sessions): v042 T4 r1/r2/r4/r5 and v041 T4 r1/r3/r4 made no commit | T4 prompt said the --sort todo was done but the code had no --sort (agents refused or stopped), plus `rm`/`mv` denials | R1 v5: T4 setup applies the --sort implementation before the setup commit; T4 rerun in both arms (10 sessions); first-pass T4 runs kept aside | see row 6 |
| 6 | R1 final (v041 vs v042, 25 each) | — | E1 Stop-blocked sessions 11 → 0; E2 sessions with ≥2 progress 0 → 0; E3 progress passing and in the first work commit 15 → 24 (v042 miss: T4 r2 `mv` denied); E4 first-request tokens at 25 tools 22,177 → 22,178; E5 mean turns 24.9 → 17.7; E6 pre-commit blocks 14 → 26, all in T5 (unfilled placeholders at first commit; both arms also count a progress that quotes a `synced id:` tag as a code location); E7 mean commits 1.52 → 0.96; mean input tokens 772K → 470K; E9 rule items 20/20 → 19/20 | Q6, Q7, Q8, Q9 pass; V15 accepted |

# Version Log
## v1
- Initial draft from the outside-view countermeasures (accepted in full) and the rescored 0.41.0 evaluation; placeholder token renamed to `[harness-requires]` before approval.

## v2
- Contract clarifications from the test-implementer's challenges: F9 marker path is `progress.change_dir` (`progress-<S>.d`), as the existing hook uses; `skeleton_name` returns no `.md`; stale status names the changed path; PostToolUseFailure never creates a skeleton; `stop_hook_active` keeps Stop at exit 0; missing-metadata wording free. No behavior change for either role.
## v3
- Test-run-1 spec gaps: Q3/C3 compare the `session:` value and N1, since the existing commit stamp, User Requests sync, and rotation's empty-session fill still rewrite the file; the skeleton also carries the commit stamp; `line_commits` keys one entry per line.
## v4
- Verifier 1 (retry): F1 states PostToolUse exits 2 with N1; V1, V3, V6, V7, V8 gain coverage items for EG1–EG3 and N-B; V10 covers the gate's git-dir failure and invalid/unreadable claim targets (SC1); V12 gains F11 required phrases, installed-copy equality, and README phrases, and V16 makes continue-on wording and the dogfood update main's review evidence (SC2).
## v5
- R1 T4 fixture: setup applies the --sort implementation so the task premise holds; review-evidence procedure only.

# Retrospective
## 2026-11-10
| observation | evidence | how to re-check |
| --- | --- | --- |
| The before/after evaluation targeted simonw/mcp-explorer at commit `56910d7c6c9f7e143dadd67bf047d7650a79ffdd` | evaluation runs in this session | clone the repository and run `git rev-parse HEAD` after checkout |

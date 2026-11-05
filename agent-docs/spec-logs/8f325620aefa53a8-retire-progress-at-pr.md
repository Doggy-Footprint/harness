---
version: 3
run_id: 8f325620aefa53a8
status: complete
base_commit: f6acba9a94af757e8b4371891ed56e25cf3cec38
max_verifier_invocations: 2
commit: f6acba9a94af757e8b4371891ed56e25cf3cec38
---

# User Intent
| id | stakeholder | intention | observable goal |
| --- | --- | --- | --- |
| UI1 | harness user | Pulling master after a PR made from a Claude Code session leaves no working-tree changes | after the PR branch is merged (merge, squash, or rebase) and master is pulled, `git status --porcelain` is empty |
| UI2 | harness user | The session moves its own progress to `progress-logs/` inside the PR branch before the PR exists | `gh pr create` is blocked until the session's progress is retired, committed, and pushed |
| UI3 | harness user | The same session keeps working on its retired progress after the PR | edits to the session's own `progress-logs/` file get the same checks and User Requests sync as `progress/`, and the session cannot stop with that file uncommitted or unpushed |

# Scope
In scope: a PreToolUse gate on `gh pr create` in `progress_hook.py`; a `retire` subcommand in `harness/bin/progress.py`; treating the session's own `progress-logs/` file as its progress in PostToolUse, Stop, PreCompact, commit-time User Requests sync, and doc_commit stamping; refusing a second progress in `progress/` when the session already owns a logs file; Progress Rule text; version 0.36.0 with a message-only `update` migration.
Out of scope: another session's progress left in `progress/` at PR time; PRs or pushes made outside Claude Code; later sessions adding progress to an existing PR branch (all three keep the `post-merge` fallback, which is unchanged); `/continue-on` with no argument when `progress/` is empty (it keeps failing — user answer); setting `before` when `progress/` is empty (stays `none` — user answer); `verify_rules.py` format checks for logs files; a clone that pulled the branch before the retire commit; worktree switches mid-session; Codex.

# Paths
Implementation: harness/hooks/progress_hook.py, harness/bin/progress.py, harness/lib/progress.py, harness/lib/hook_shared.py, harness/hooks/pr_message_nudge.py, harness/git/sync_progress.py, harness/hooks/doc_commit.py, harness/instructions/harness-block.md, installer/harness.py, harness/VERSION
Tests: tests/test_progress_retire.py, tests/test_progress.py, tests/test_installer.py, tests/test_comment_gate.py, tests/test_doc_records.py, tests/test_session_metrics.py, tests/test_telemetry.py, tests/test_workflow_markers.py, tests/test_message_nudge.py
Test command: uv run --no-project --with pytest --with hypothesis python3 -m pytest tests -q -p no:cacheprovider
Review evidence: R1 — after `python3 installer/harness.py update .`, read the Progress Rule paragraph in `harness/instructions/harness-block.md` and the regenerated `AGENTS.md`; expected: both state that `gh pr create` from a Claude Code session is blocked until the session's progress is retired to `progress-logs/` (`python3 .harness/bin/progress.py retire`), committed, and pushed, and that the session keeps editing it there; the rest of the paragraph is unchanged (checked with `git diff`).
Fuzzing: none — inputs are git repository states and Bash command strings already enumerated by the decision tables in VO1 and VO2; no parser of untrusted structured input is added.
Mutation tool: none — mutmut and cosmic-ray are not installed in the project environment; 8–10 hand mutations supply mutation evidence.

# Signatures
CLI: `python3 .harness/bin/progress.py retire [--session ID]` — session from `--session`, else `$CLAUDE_CODE_SESSION_ID`; exit 0 and stdout `retired: <src repo path> -> <dest repo path>`; exit 1 and stderr `progress.py: <message>` on error.
Hook (PreToolUse, Bash, `progress_hook.py`): payload `{"hook_event_name": "PreToolUse", "session_id", "tool_name": "Bash", "tool_use_id", "tool_input": {"command"}, "cwd"}`; blocking result is exit 2 with stderr starting `harness: gh pr create blocked:`; allowed result is exit 0 with empty stderr.
Hook (Stop, `progress_hook.py`): new blocking result is exit 2 with stderr starting `harness:` naming the logs file and the needed action (`commit` or `push`).
Push target ref: if the command has `--head <B>` / `--head=<B>` / `-H <B>` (B with any `owner:` prefix removed), `refs/remotes/origin/<B>`; otherwise `@{push}` of the current branch. Unresolvable ref → the push checks are skipped.
Path configuration: `.harness/config.json` key `docs_root` (repo-relative directory, default `agent-docs`); the progress dirs are `<docs_root>/progress` and `<docs_root>/progress-logs`. No other key moves them.

# Functional Requirements
| id | requirement | priority | source |
| --- | --- | --- | --- |
| FR1 | PreToolUse Bash: a command containing `gh pr create` at a command start (start of string, after `;`, `&`, `|`, `(`, or newline, followed by optional whitespace — the same rule as `pr_message_nudge.py`) is gated; any other command keeps the current PreToolUse behavior (exit 0, no stderr, snapshot written). | must | user decision 1 |
| FR2 | Gate, first matching condition wins, S = payload session_id: (a) a file directly in `progress/` of the working tree has `session: S` → block, message names that file and the command `python3 .harness/bin/progress.py retire --session S`, then commit, push, and rerun `gh pr create` in its own Bash call; (b) S changed the project (modified marker) and owns no file directly in `progress/` or `progress-logs/` → block, message says to write the progress, then retire, commit, push; (c) HEAD's tree has a file directly under `progress/` with `session: S` → block, message says to commit; (d) S's file in `progress-logs/` is absent from HEAD or its working-tree bytes differ from HEAD's blob → block, message says to commit it; (e) the push target ref resolves and its tree has a file directly under `progress/` with `session: S`, or lacks S's logs file, or holds a different blob for it than HEAD → block, message says to push; otherwise allow. | must | user decision 1; review findings 1, 4, 7 |
| FR3 | Every block message from FR2 contains the literal session id S (as `--session S` where retire is mentioned) and says to run `gh pr create` in its own Bash call. | must | review findings 5, 6 |
| FR4 | Gate fails open: missing session_id, git unavailable, or not a git repository → exit 0. | must | existing hook policy |
| FR5 | `retire`: moves S's single file in `progress/` to `progress-logs/<same name>`; a tracked file is moved with `git mv`, an untracked one with a rename; afterwards the destination's index entry equals its working-tree content (staged) and the source path is gone from both working tree and index. Prints `retired: <src> -> <dest>`. | must | user decision 1 |
| FR6 | `retire` refuses (exit 1, nothing moved, nothing staged) when: no session id is given or set; S owns no file in `progress/`; S owns more than one file in `progress/`; S already owns a file in `progress-logs/`; the destination already exists. | must | review finding 8 |
| FR7 | PostToolUse Write/Edit/MultiEdit/NotebookEdit on a file directly in `progress-logs/` whose frontmatter `session` equals the payload session_id: no rotation; User Requests synced from the session state; commit stamp written; `check_findings` run; findings reported as in `progress/` (exit 2). Logs files of other sessions or with invalid frontmatter are left unchanged and produce no output. | must | user decision 2 |
| FR8 | PostToolUse on a new file in `progress/` whose session (the frontmatter `session`, or the payload session_id when the frontmatter has none — the existing `own_session` rule) already owns a file in `progress-logs/` → exit 2, message names the logs file and says to merge into it and remove the new file; no rotation happens. | must | user decision 2 |
| FR9 | `doc_commit.py` does not stamp a `progress-logs/` file whose frontmatter session equals the payload session_id; it keeps stamping other `progress-logs/` files. | must | review finding 3 |
| FR10 | Commit-time `sync_progress.py` also syncs User Requests in `progress-logs/` files whose session equals `$CLAUDE_CODE_SESSION_ID` and stages them; with the variable unset it touches no logs file. | must | user decision 2 |
| FR11 | Stop and PreCompact find the session's progress in `progress/` first, then in `progress-logs/`. A session whose own progress is in `progress-logs/` no longer gets the "no file in progress/" block. | must | user decision 2 |
| FR12 | Stop, when the session's own progress is in `progress-logs/` and `stop_hook_active` is not true: after the existing Next Session check, block (exit 2) if the file is absent from HEAD or differs from HEAD's blob (message: commit and push), else block if `@{push}` resolves and its blob differs from HEAD's or is absent (message: push). | must | user answer (Stop block) |
| FR13 | Progress Rule text describes the gate, `retire`, and editing in `progress-logs/` after retire. | must | R1 |
| FR14 | `harness/VERSION` is 0.36.0; `installer/harness.py` MIGRATIONS has a 0.36.0 message-only entry describing the gate, retire, and post-PR editing. | must | AGENTS.md update rule |

# Errors
- No session id for `retire` — stderr `progress.py:` names `--session` and `$CLAUDE_CODE_SESSION_ID`, exit 1 — repository unchanged.
- `retire` with no own file / several own files / own logs file present / destination exists — stderr `progress.py:` names the paths involved, exit 1 — repository unchanged (no move, no staging).
- `git mv` fails inside `retire` — stderr `progress.py:` with git's message, exit 1 — source left in place.
- Gate git command fails (corrupt repo, no HEAD) — exit 0, no stderr — command allowed.
- Gate with unresolvable push target ref — checks (e) skipped — allowed when (a)–(d) pass.
- Second progress in `progress/` while a logs file is owned — exit 2 with merge instruction — no rotation, files unchanged except normal write.
- Stop with uncommitted/unpushed own logs file — exit 2 naming the file and `commit`/`push` — no file changes.

# Cases
| id | level | input / state | expected result |
| --- | --- | --- | --- |
| C1 | normal | own progress in `progress/`, `gh pr create --fill` | exit 2, names the file, `retire --session S`, own-call advice |
| C2 | normal | own progress retired, committed, pushed (`@{push}` equal); `gh pr create` | exit 0 |
| C3 | normal | `retire` on tracked own progress | exit 0, rename staged, dest content staged, src gone |
| C4 | normal | `retire` on untracked own progress | exit 0, dest staged as added |
| C5 | normal | own logs file edited after retire (Write) | User Requests synced, stamp written, findings reported, no rotation |
| C6 | normal | scenario: bare remote; clone works on a branch, writes progress, gate blocks, retire, commit, push, gate allows; other clone merges the branch into master by `--no-ff`, by squash, and by rebase, pushes; first clone checks out master and pulls | `git status --porcelain` empty in each merge variant |
| C7 | boundary | `retire` then gate before commit | exit 2 at (c): HEAD still has the file under `progress/` → commit message |
| C8 | boundary | retire committed, not pushed (`@{push}` tree still has `progress/` file) | exit 2, push message |
| C9 | boundary | no upstream/`@{push}` unresolvable, retire committed | exit 0 |
| C10 | boundary | `--head feat` / `-H feat` / `--head=owner:feat` with `refs/remotes/origin/feat` behind HEAD | exit 2 push message; with origin/feat equal → exit 0 |
| C11 | edge | modified project, no progress anywhere | exit 2 at (b) |
| C12 | edge | session made no change and owns no progress | exit 0 |
| C13 | edge | another session's progress in `progress/`, own progress retired and pushed | exit 0 |
| C14 | edge | `git commit -m x && git push && gh pr create` with own progress in `progress/` | exit 2 (gate applies; message says own call) |
| C15 | edge | command `echo gh pr create` / `gh pr view` / `gh pr edit --body x` | not gated: exit 0 |
| C16 | edge | logs file of another session edited | unchanged, no output; doc_commit still stamps it |
| C17 | edge | own logs file exists, new file written in `progress/` | exit 2 merge message, no rotation |
| C18 | error | `retire` without session; with no own file; two own files; own logs exists; destination exists | exit 1, repo unchanged (`git status --porcelain` and index identical before/after) |
| C19 | error | gate without session_id; in a non-git directory | exit 0 |
| C20 | normal | Stop: own logs file committed and pushed | exit 0 |
| C21 | boundary | Stop: own logs file modified after commit; committed but `@{push}` behind; `stop_hook_active: true` | exit 2 commit; exit 2 push; exit 0 |
| C22 | normal | pre-commit with `$CLAUDE_CODE_SESSION_ID`=S and own logs file with stale User Requests | file rewritten and included in the commit; unset variable → logs untouched |
| C23 | normal | PreCompact with own progress in logs | notice names the logs file |
| C24 | normal | doc_commit PostToolUse on own logs file | file not stamped by doc_commit (byte-identical to what progress_hook wrote) |

# Quality Applicability
| ISO/IEC 25010:2023 characteristic | applicable | rationale |
| --- | --- | --- |
| Functional suitability | yes | new gate, CLI, and hook behaviors |
| Performance efficiency | no | gate runs a few git commands only for `gh pr create`; other commands keep the existing work |
| Compatibility | yes | existing PreToolUse, rotation, Stop, doc_commit, and post-merge behavior must not change outside the new cases |
| Interaction capability | yes | block messages must tell the agent the exact next command |
| Reliability | yes | hooks must fail open on git errors and never leave partial moves |
| Security | no | no new trust boundary; secret masking checks already cover `progress-logs/` |
| Maintainability | no | covered by existing project conventions; no measurable target agreed |
| Flexibility | yes | configured progress paths (`config.load_paths`) must be honored |
| Safety | no | no physical or human-safety effect |

# Quality Requirements
| id | characteristic / subcharacteristic | target and context | measure method / inputs / unit | threshold and direction | evidence: automated, review, mutation | source |
| --- | --- | --- | --- | --- | --- | --- |
| QR1 | Compatibility / co-existence | full existing suite at base_commit (1016 tests) | count of pre-existing tests failing, excluding version-pin and migration-count updates | 0, lower is better | automated: Test command; mutation: hand | AGENTS.md |
| QR2 | Interaction capability / user assistance | every FR2 block message and FR6/FR12 message | presence of file path, session id (FR2/FR3), and the next action word (`retire`/`write`/`commit`/`push`) per message | 100% of messages, higher is better | automated: VO7 | review findings 5, 6 |
| QR3 | Reliability / fault tolerance | gate and retire under git failure or refusal conditions | count of runs leaving a moved/staged file or raising a traceback | 0, lower is better | automated: VO4, VO3 | FR4, FR6 |
| QR4 | Flexibility / adaptability | a repo whose `.harness/config.json` sets `docs_root` to another directory | gate and retire act on configured dirs | pass, n/a | automated: VO8 | config.load_paths |

# Verification Obligations
| id | parent requirement/Case ids | variant and target surface | test layer and selection policy | ISO/IEC/IEEE 29119-4 technique | coverage items | coverage target | observation and expected result | evidence procedure |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| VO1 | FR1, C14, C15 | PreToolUse hook stdin/exit/stderr | integration (subprocess hook in temp repo); one test per item | equivalence partitioning | P1 bare `gh pr create`; P2 after `&&`; P3 after `;`; P4 after newline; P5 `echo gh pr create`; P6 `gh pr view`; P7 `gh pr edit --body x` | 100% | P1–P4 gated (exit 2 with own progress in `progress/`); P5–P7 exit 0, empty stderr | Test command |
| VO2 | FR2, C1, C2, C7, C8, C9, C11, C12, C13 | PreToolUse hook | integration; one test per rule | decision table | rules R(a), R(b), R(c), R(d), R(e-progress), R(e-logs-diff), R(allow-all-pass), R(allow-no-change), R(allow-other-session); R(c-only): HEAD holds own file under `progress/` while S's logs file is committed and equal to HEAD (only the logs file was committed) → commit message; R(e-progress-only): push target holds own file under `progress/` and the same logs blob as HEAD → push message | 100% | exit code and action word per rule | Test command |
| VO3 | FR5, FR6, C3, C4, C18 | `progress.py retire` CLI, git index and working tree | integration | equivalence partitioning | E1 tracked; E2 untracked; E3 tracked with unstaged edits (dest staged content equals working tree); X1 no session; X2 no own file; X3 two own files; X4 own logs exists; X5 destination exists; X6 `git mv` fails (a `.git/index.lock` exists, tracked source) → exit 1, `progress.py:` with git's message, source still tracked in place; E4 both `--session` and `$CLAUDE_CODE_SESSION_ID` set to different sessions → `--session` wins | 100% | E*: exit 0, stdout line, index state; X*: exit 1, `git status --porcelain` and `git ls-files -s` identical before/after | Test command |
| VO4 | FR4, C19 | PreToolUse hook | integration | equivalence partitioning | F1 no session_id; F2 non-git cwd/REPO_ROOT; F3 unresolvable push ref; F4 repository with no commit (unborn HEAD) and own progress in `progress/` | 100% | F1, F2, F4 exit 0 empty stderr, no traceback; F3 allowed when (a)–(d) pass | Test command |
| VO5 | FR2(e), C10 | PreToolUse hook, push target selection | integration; base choice = no flag | combinatorial (base choice) | B0 no flag with `@{push}`; B1 `--head feat`; B2 `-H feat`; B3 `--head=owner:feat`; each with origin ref behind → block, and B1 with ref equal → allow | 100% | exit codes as stated | Test command |
| VO6 | FR7, FR8, FR9, FR11, C5, C16, C17, C23, C24 | PostToolUse, PreCompact hooks, doc_commit hook | integration | equivalence partitioning | L1 own logs Write; L2 other session logs Write (progress_hook no-op, doc_commit stamps); L3 own logs with format defect → findings; L4 new `progress/` file while own logs exists; L5 PreCompact names logs file; L6 doc_commit on own logs leaves bytes unchanged; L7 Stop with own progress only in logs and Next Session filled, committed and pushed → exit 0; L8 PostToolUse on a logs file with invalid frontmatter → unchanged bytes, exit 0, no output; L9 new `progress/` file without frontmatter `session` while the payload session owns a logs file → refused as L4 | 100% | as stated in Cases | Test command |
| VO7 | FR3, FR12, QR2, C20, C21 | gate, retire, Stop stderr | integration | state transition | states: S0 no progress+modified; S1 progress in `progress/`; S2 retired uncommitted; S3 committed unpushed; S4 pushed; S5 logs edited after push; transitions write, retire, commit, push, edit; Stop/gate observed in each state | all 6 states and 5 transitions | gate: S0 write, S1 retire, S2 commit, S3 push, S4 allow, S5 commit; Stop in S4 exit 0, S5 commit, S3 push; every gate block message (including both (e) logs branches: target lacks the logs file, target has a different blob) contains session id, path, and the own-Bash-call advice; Stop with own logs file committed and no `@{push}` (no upstream) → exit 0; Stop with own logs file uncommitted and an empty `## Next Session` → the Next Session block message, not the commit message | Test command |
| VO8 | QR4 | gate and retire with configured progress dirs | integration | equivalence partitioning | K1 `.harness/config.json` with `{"docs_root": "notes"}` (progress dirs `notes/progress`, `notes/progress-logs`) | 100% | C1 and C3 behaviors hold on configured dirs | Test command |
| VO9 | FR10, C22 | `git commit` running pre-commit in temp repo | integration | equivalence partitioning | V1 env set to S, own logs stale → rewritten and committed; V2 env unset → logs unchanged; V3 env set, other session's logs → unchanged | 100% | file contents in the commit | Test command |
| VO10 | UI1, C6 | end-to-end git flow with bare remote and two clones | end-to-end; one test per merge variant | scenario | M1 `--no-ff`; M2 squash; M3 rebase | 100% | `git status --porcelain` empty after pull in clone A | Test command |
| VO11 | FR14, QR1 | installer update, VERSION, existing suite | integration | equivalence partitioning | U1 VERSION 0.36.0; U2 `update` lists the 0.36.0 migration message, mentioning `gh pr create`, `retire`, and editing in `progress-logs/` after the PR; U3 pre-existing tests | 100% | values and pass | Test command |
| VO12 | FR13 | instructions text | review | none — review | R1 | R1 done | as stated in Review evidence | R1 |

# Assumptions and Defaults
| id | decision | evidence and uncertainty | brief v<n> — approved / vetoed → <answer> / user answer |
| --- | --- | --- | --- |
| A1 | Gate blocks before `gh pr create` and tells the agent to retire, commit, push | user choice | user answer |
| A2 | After retire the session edits its file in `progress-logs/` | user choice | user answer |
| A3 | `before` stays `none`; `/continue-on` without argument fails after a PR | user choice ("RP 이후 continue-on은 실패하는 게 맞다") | user answer |
| A4 | Stop blocks while the session's own logs file is uncommitted or unpushed | user choice | user answer |
| A5 | Gate only considers the current session's progress; other sessions' leftovers use the post-merge fallback | understanding round, confirmed by user | user answer |
| A6 | Also block when the session changed the project but wrote no progress (FR2 b) | review finding 1: progress is usually written at Stop, after the PR | brief v1 — approved |
| A7 | doc_commit skips only the current session's logs file, not all logs files | review finding 3; keeps stamping for other logs edits | brief v1 — approved |
| A8 | Commit-time sync identifies the session with `$CLAUDE_CODE_SESSION_ID` only; gate messages pass `--session S` explicitly | env var observed 2026-10-28, not verified across versions; after `/clear` the env may name an older session, whose logs file would then be re-synced with its own state | brief v1 — approved |
| A9 | Push target is `@{push}`, or `refs/remotes/origin/<B>` for `--head B`; unresolvable → skip push checks | review finding 7; remote name `origin` assumed for `--head` | brief v1 — approved |
| A10 | `retire` stages the destination's full working-tree content | otherwise unstaged edits would be missed by the commit and trip check (d) | brief v1 — approved |
| A11 | Gate matches `gh pr create` lines inside heredoc bodies too (same regex as pr_message_nudge) | review finding 6; false positive only blocks with an actionable message | brief v1 — approved |
| A12 | Version 0.36.0 (minor: new CLI subcommand and gate) | project semver practice in MIGRATIONS | brief v1 — approved |
| A13 | Subagents use installed default model sonnet (implementer, test-implementer, test-verifier) | `.claude/agents/*.md` frontmatter | brief v1 — approved |
| A14 | Test thresholds: 100% of declared coverage items; 0 regressions | project practice | brief v1 — approved |

# Traceability
| requirement id | Case ids | obligation ids | evidence procedure |
| --- | --- | --- | --- |
| FR1 | C14, C15 | VO1 | Test command |
| FR2 | C1, C2, C7–C13 | VO2, VO5, VO7 | Test command |
| FR3 | C1, C14 | VO7 | Test command |
| FR4 | C19 | VO4 | Test command |
| FR5 | C3, C4 | VO3 | Test command |
| FR6 | C18 | VO3 | Test command |
| FR7 | C5, C16 | VO6 | Test command |
| FR8 | C17 | VO6 | Test command |
| FR9 | C16, C24 | VO6 | Test command |
| FR10 | C22 | VO9 | Test command |
| FR11 | C23 | VO6 | Test command |
| FR12 | C20, C21 | VO7 | Test command |
| FR13 | — | VO12 | R1 |
| FR14 | — | VO11 | Test command |
| UI1 | C6 | VO10 | Test command |
| QR1 | — | VO11 | Test command |
| QR2 | — | VO7 | Test command |
| QR3 | C18, C19 | VO3, VO4 | Test command |
| QR4 | — | VO8 | Test command |

# Workflow Control
| item | value |
| --- | --- |
| correction batches used | 2 |
| verifier invocations | 2 |
| open finding ids | none |

Audit state (one entry per obligation; retain prior decisions in the execution ledger):
| obligation id | spec version | evidence references and revision | accepted / open / invalidated / pending | rationale and mutation outcome | dependencies and reopening evidence |
| --- | --- | --- | --- | --- | --- |
| VO1–VO11 | 3 | tests/test_progress_retire.py (57 tests, after correction batch 2) + version pins; Test command 1073 passed | accepted | verifier round 2 pass; 15 hand mutations detected by the intended tests | spec v3; reopen on changes to gate, retire, logs-edit, Stop, or sync behavior |
| VO12 | 3 | R1 after `python3 installer/harness.py update .` | accepted | harness-block.md and AGENTS.md carry the new sentences; rest unchanged | harness-block.md text |

Execution ledger (append attempts; preserve failed approaches):
| attempt | finding / failure signature | cause hypothesis | changed approach / new evidence | result / disposition |
| --- | --- | --- | --- | --- |
| 0 | design review (Plan subagent) before drafting | — | 10 findings; 1, 3–8 folded into FR2, FR3, FR6, FR9, FR12, A6–A11; 2 resolved by user (A3); 9, 10 out of scope | drafted v1 |
| 1 | Test command v2: 1063 passed, 1 failed — `test_o9_q6_name_collision_in_todos...` EOFError on 0.36.0 migration prompt | test defect: one `update` input not given the extra confirmation for the new migration | sent to test-implementer with a sweep of all `update` inputs | fixed (8 answers); sweep found no other short input; Test command 1064 passed; R1 checked after `update .`: AGENTS.md diff is the version marker and the two appended Progress Rule sentences |
| 2 | verifier round 1 retry: F-1, F-2 evidence gaps; F-3 spec challenge (clauses without coverage items); hand mutations M1–M10 run on tests/test_progress_retire.py + test_message_nudge.py + test_doc_records.py (targeted files, ~85 s each, instead of the 6-minute full suite): 9 detected, M7 survived | F-3: coverage items missing for declared clauses; MUT-7: V3 oracle cannot see a wrong sync because the other session's state equals its file | spec v3 adds the items (contract-only); correction batch 2 to test-implementer | batch 2 done (57 tests in the file); Test command 1073 passed; mutations M7 (rerun), M11 Stop blocks without upstream, M12 Stop logs check before Next Session check, M13 env wins over --session, M14 rule (c) dropped — all detected by the intended tests; all files restored (`seed.py status`: none) |

# Version Log
## v3
- Contract-only, from verifier round 1: coverage items added for clauses already in the spec (VO3 X6, E4; VO4 F4; VO6 L8, L9; VO2 R(c-only), R(e-progress-only); VO7 own-call advice on both (e) logs branches, Stop without `@{push}`, Stop ordering after the Next Session check; VO11 U2 wording). FR8 wording fixed to the existing `own_session` rule (frontmatter session, else payload) because "frontmatter or payload" left the differing case undefined.
## v2
- Contract-only: Signatures name the path configuration key (`docs_root`) because test-implementer found no test that configures progress dirs; VO8 K1 and QR4 restated with it. Evidence: `harness/lib/config.py` `Paths` derives progress and progress-logs from `docs_root` only.
## v1
- Initial draft from the user's decisions and the design review.

# Retrospective
## 2026-11-05
| observation | evidence | how to re-check |
| --- | --- | --- |
| none | every observation of this session is recorded in this spec's Assumptions and Defaults, execution ledger, and Version Log | read those sections of this file in spec-logs/ |

---
version: 4
run_id: 533bf9acadc402a8
status: limit
base_commit: 7983e9de5517658b921e9b9a4615c1ce3b4e5b4d
max_verifier_invocations: 2
commit: 7983e9de5517658b921e9b9a4615c1ce3b4e5b4d
---

# User Intent
| id | stakeholder | intention | observable goal |
| --- | --- | --- | --- |
| I1 | harness user running workflow-approach | A new spec workflow is never refused because of a leftover marker after the previous spec left `agent-docs/specs/` | `start` succeeds after a spec was moved with `mv`/`git mv`, renamed, or deleted, and when a later session re-runs `start` on its own active spec |
| I2 | harness user | A workflow never starts, and a session is never left unaware, while an injected mutation (unrestored seed backup) is still in the tree | `start` refuses while `.seed/` holds files; a Claude Code session start prints the seed state |
| I3 | harness user with several sessions on one worktree | A session cannot abort a workflow that another live session may be running without explicit user confirmation | `abort` and `archive --status aborted` refuse, leaving the spec untouched, while another live harness session exists, unless `--other-sessions-confirmed` is given |
| I4 | maintainer of installed repositories | Installed repositories move to the new behavior through `update` | migration 0.44.0 removes a leftover `.active` and announces the changes |
| I5 | harness developer | Wording checks of skill, rule, and README text added in 0.42.0 and 0.43.0 do not run in the default suite | `python -m unittest discover -s tests` reports them as skipped unless `HARNESS_TEXT_TESTS=1` |

# Scope
In scope: `spec_lifecycle.py` `start`/`archive`/`session` stop reading, writing, and deleting `agent-docs/specs/.active`; `start` refuses with an unrestored seed backup; new `abort` subcommand and `--other-sessions-confirmed` flag on `abort` and `archive`; live-session classification from `.harness/sessions/.running/` markers; a spec-state notice printed by a new `notice` subcommand and by the Claude Code SessionStart progress hook; workflow-approach SKILL.md step 1 abort order; harness VERSION 0.44.0 and migration; tests whose hard-coded harness version changes; opt-in gating of the wording tests listed in FR17 and of this run's SKILL.md wording test; one README development line on the opt-in.
Out of scope: session scoping or cleanup of `agent-docs/specs/.running/` subagent markers; reconciling telemetry run state with spec files or re-emitting telemetry on resume; progress skeleton one-shot guard; pid-reuse protection; cleanup of `.harness/sessions/progress-*` files; blocking resume of a spec another live session runs; Codex SessionStart notice; changing `.gitignore` lines; changing `seed.py`; a before/after `claude -p` session evaluation (not evidence for this run); gating tests other than those named in FR17.

# Paths
Implementation: harness/bin/spec_lifecycle.py, harness/lib/spec_state.py, harness/hooks/progress_hook.py, harness/skills/workflow-approach/SKILL.md, harness/VERSION, installer/harness.py, README.md
Tests: tests/test_spec_active_state.py, tests/text_checks.py, tests/test_installer.py, tests/test_comment_gate.py, tests/test_hook_owned_progress.py, tests/test_rule_injection.py, tests/test_doc_records.py, tests/test_lazy_rules.py, tests/test_progress_retire.py, tests/test_synced_blocks.py, tests/test_telemetry.py, tests/test_session_metrics.py, tests/test_workflow_markers.py
Test command: cd /Users/hwansu/tools/harness && HARNESS_TEXT_TESTS=1 .venv/bin/python -m unittest discover -s tests
Review evidence: R1 — main reads the installed `.harness/skills/workflow-approach/SKILL.md` step 1 after `update` and checks FR16's five items in order, including the ask-the-user-then-confirm wording of item 4; R2 — main reads README.md section `## 이 저장소에서 개발하기` and checks the FR17 sentence (skill, rule, or README text changes run the suite with `HARNESS_TEXT_TESTS=1`); results recorded in the execution ledger.
Fuzzing: none — inputs are file-system states and CLI arguments enumerated by decision tables and equivalence classes; no fuzzer harness exists for subprocess CLIs here.
Mutation tool: none — tests drive the scripts through an installed copy in temporary repositories, so each mutant would need minutes of suite time; 8–10 hand mutations replace it.

# Signatures
python3 .harness/bin/spec_lifecycle.py start --spec PATH --run-id ID [--resume]
python3 .harness/bin/spec_lifecycle.py archive --spec PATH --status complete|limit|aborted [--other-sessions-confirmed]
python3 .harness/bin/spec_lifecycle.py abort --spec PATH [--other-sessions-confirmed]
python3 .harness/bin/spec_lifecycle.py session
python3 .harness/bin/spec_lifecycle.py notice
python3 .harness/bin/spec_lifecycle.py validate --spec PATH
progress_hook.py SessionStart (stdin JSON `{"hook_event_name": "SessionStart", ...}`) prints the notice to stdout
installer migration 0.44.0 run by `python3 installer/harness.py update <target>`
tests/text_checks.py: `text_test` decorator (unittest skip unless `HARNESS_TEXT_TESTS` equals `1`)

# Functional Requirements
| id | requirement | priority | source |
| --- | --- | --- | --- |
| FR1 | No `spec_lifecycle.py` subcommand reads, creates, or deletes `<specs>/.active`. A pre-existing `.active` (any content, including empty) has no effect on any subcommand's result. | must | I1 |
| FR2 | `start` checks in this order and reports the first failing check with exit 1: spec validation (unchanged messages, `invalid spec: ` prefix); status is `active` (stderr contains `start requires spec status active`); `--run-id` equals frontmatter `run_id` (stderr contains `--run-id does not match spec frontmatter`); no unrestored seed (FR3); no other `*.md` directly in `<specs>/` with status `draft` or `active` (stderr contains `another workflow is active` and each such file name). Otherwise exit 0. `--resume` is accepted and changes nothing. Re-running `start` on the same active spec, with or without `--resume`, exits 0. | must | I1 |
| FR3 | When `<specs>/.seed/` contains any file, `start` exits 1 and stderr contains `unrestored seed backup` and `python3 .harness/bin/seed.py restore`. | must | I2 |
| FR4 | Live-session classification: a marker is a file directly in `<repo>/.harness/sessions/.running/` whose name is a decimal pid; other names are ignored. A marker is live when signal 0 to its pid succeeds or fails with a permission error. A live marker is own when its pid is the current process or one of its ancestors, or when its JSON `session_id` equals a non-empty `CLAUDE_CODE_SESSION_ID` environment variable. Every other live marker, including one with no readable `session_id`, is another live session. A missing directory means no other live sessions. | must | I3 |
| FR5 | `archive` checks in this order: unrestored seed; status equals `--status` and is terminal; path is a direct `.md` child of `<specs>/`; for `--status aborted` only, no other live session unless `--other-sessions-confirmed` (FR7 message); destination absent in `<spec-logs>/`. On success it renames the file to `<spec-logs>/<same name>` without rewriting it and prints the repo-relative destination. Refusal exits 1. `complete` and `limit` never consult live sessions. | must | I3 |
| FR6 | `abort --spec P` checks in this order, exiting 1 at the first failure with the spec file unchanged and nothing created in `<spec-logs>/`: P resolves to a direct `.md` child of `<specs>/` that exists (stderr contains `agent-docs/specs`); P has a frontmatter block with a `status` line (stderr contains `frontmatter`); status is `draft`, `active`, or `aborted` (for `complete`/`limit` stderr contains `use archive`); no unrestored seed (stderr as FR3 minus the start-specific wording, containing `unrestored seed backup` and `python3 .harness/bin/seed.py restore`); no other live session unless `--other-sessions-confirmed` (FR7); destination absent (stderr contains `archive destination already exists`). On success it sets the frontmatter `status` value to `aborted` changing no other byte, moves the file to `<spec-logs>/<same name>`, prints the repo-relative destination to stdout, and exits 0. | must | I3 |
| FR7 | A live-session refusal's stderr contains `other harness session`, every other live session's pid, its session id when known, and `--other-sessions-confirmed`. | must | I3 |
| FR8 | `session` behaves as before except: it no longer touches `.active`; an `aborted` spec is archived through FR5's rules without the confirmation flag, so with another live session it stays in `<specs>/` and stderr names it. `complete`/`limit` specs archive as before; `draft`/`active` print the existing resume hint; other or missing status is ignored; with an unrestored seed nothing is archived. | must | I3 |
| FR9 | The notice consists of lines each starting with `spec lifecycle: `, in this order, and is empty when none apply: (N1) when `.seed/` has files (including only `manifest.json`, in which case the line lists no file), one line containing `unrestored seed backup`, each file path relative to `.seed/` except `manifest.json` and `manifest.json.tmp`, and `python3 .harness/bin/seed.py restore`; (N2) for each `draft`/`active` spec in `<specs>/` sorted by name, one line with its repo-relative path, its status, and its `base_commit` value (`unknown` when absent); (N3) for each `complete`/`limit`/`aborted` spec still in `<specs>/` sorted by name, one line with its repo-relative path, its status, and the reason: `unrestored seed backup` when `.seed/` has files, else the repo-relative destination path when it already exists in `<spec-logs>/`, else `not archived yet`; (N4) when `<specs>/.running/` has entries, one line containing each entry's repo-relative path sorted by name and the word `delete`. | must | I2 |
| FR10 | `notice` prints the notice to stdout and exits 0. | must | I2 |
| FR11 | The progress hook's SessionStart handler prints the notice to stdout before its existing work, regardless of `session_id` presence or git readiness, and keeps its exit status 0. Its stdout for a given state equals `notice` stdout for that state. | must | I2 |
| FR12 | Building the notice never raises: an unreadable or undecodable spec, seed entry, or marker is skipped (or reported with the information still readable) and the remaining items are still printed. | must | I2 |
| FR13 | All `<specs>`, `<spec-logs>` paths derive from the harness config `docs_root` (default `agent-docs`). | must | I4 |
| FR14 | `harness/VERSION` is `0.44.0`. Migration 0.44.0 (label mentions the `.active` marker) is announced on update from 0.43.0; when not a dry run it deletes `<docs_root>/specs/.active` if it is a regular file, and leaves everything else in `<specs>/` untouched; a dry run deletes nothing. Its planned lines mention: `.active` removal, `start` refusal with an unrestored seed, the `abort` command with `--other-sessions-confirmed`, and the SessionStart spec notice. | must | I4 |
| FR15 | Hard-coded harness versions and migration lists in tests reflect 0.44.0. | must | I4 |
| FR16 | workflow-approach SKILL.md step 1 states the abort order: (1) restore any seed with `python3 .harness/bin/seed.py restore`; (2) get the retrospective entry approved and written in the active spec; (3) run `python3 .harness/bin/spec_lifecycle.py abort --spec PATH`; (4) if it refuses because of other live sessions, ask the user whether any of them runs this workflow and re-run with `--other-sessions-confirmed` only after the user confirms none does; (5) emit `workflow_marker.py end --status aborted`. | must | I3 |
| FR17 | These tests run only when the environment variable `HARNESS_TEXT_TESTS` equals `1`; otherwise unittest reports each as skipped with a reason containing `HARNESS_TEXT_TESTS=1`: in `tests/test_hook_owned_progress.py` `TestTextScan.test_removed_wording_does_not_occur_in_harness_or_readme`, `test_progress_rule_text_contains_the_required_phrases`, `test_readme_mentions_the_placeholder_and_drops_the_one_time_notice_wording`; in `tests/test_rule_injection.py` `TestRuleText.test_rule_files_section_of_the_block_equals_the_expected_text_in_source_and_install`, `test_synced_comments_rule_names_end_markers_block_hash_and_refresh_command`, `test_index_rule_names_the_stale_command`, `test_progress_rule_describes_the_record_only_kind`, `test_continue_on_skill_notes_that_record_only_progress_is_skipped`, `test_readme_mentions_records_command_and_record_only_progress`; and the C44 SKILL.md wording test. Version tests and installed-copy byte-equality tests in those classes stay always-run. The gate is one decorator in `tests/text_checks.py`. README's development section states that changes to skill, rule, or README text run the suite with `HARNESS_TEXT_TESTS=1`. | must | I5 |

# Errors
- Unrestored seed at `start`/`archive`/`abort` — exit 1, stderr `unrestored seed backup` + restore command — spec and `.seed/` unchanged.
- Other draft/active spec at `start` — exit 1, `another workflow is active: <names>` — nothing written.
- Other live session at `abort` or `archive --status aborted` without flag — exit 1, FR7 message — spec bytes unchanged, nothing in `<spec-logs>/`.
- `abort` on a path outside `<specs>/`, a missing file, a file without frontmatter/status, or a terminal `complete`/`limit` spec — exit 1 with FR6 text — nothing changed.
- `abort`/`archive` destination exists — exit 1, `archive destination already exists` — spec unchanged.
- Unreadable spec or marker while building the notice — no traceback, exit 0 — other notice lines still printed.
- `session` meeting an aborted spec with another live session — exit 0 (hook), stderr names the spec — spec stays in `<specs>/`.

# Cases
| id | level | input / state | expected result |
| --- | --- | --- | --- |
| C1 | normal | one active valid spec A, nothing else; `start A` | exit 0; no `.active` file exists afterwards |
| C2 | normal | C1 done; `start A` again without `--resume` | exit 0 |
| C3 | normal | C1 done; `start A --resume` | exit 0 |
| C4 | error | active A started; write active B; `start B` | exit 1; stderr `another workflow is active` and A's file name |
| C5 | error | draft spec D present; `start B` | exit 1; names D |
| C6 | normal | `complete` spec T present in specs/; `start B` | exit 0 |
| C7 | error | `.seed/` has a file; `start A` | exit 1; FR3 text; also when another active spec exists, the seed message is reported (seed precedes other-spec check) |
| C8 | edge | `.active` exists naming a missing file / empty / naming B itself; `start B` | exit 0; `.active` content unchanged by start |
| C9 | edge | A started, then `mv` to spec-logs; `start B` | exit 0 |
| C10 | edge | A started, renamed to A2, set complete, `archive A2`; `start B` | archive exit 0; start exit 0 |
| C11 | edge | A started then deleted; `start B` | exit 0 |
| C12 | error | invalid spec / status draft / run-id mismatch | existing exit 1 messages unchanged |
| C13 | normal | `complete` spec, `archive --status complete` | moved byte-identical; destination printed |
| C14 | error | aborted spec; live non-ancestor pid marker with session id S2; env session S1; `archive --status aborted` | exit 1; FR7 text incl. pid and S2; spec unchanged; with `--other-sessions-confirmed` exit 0 and moved |
| C15 | normal | aborted spec; only marker is an ancestor pid (no session id) | `archive --status aborted` exit 0 |
| C16 | normal | aborted spec; live non-ancestor marker whose session_id equals env `CLAUDE_CODE_SESSION_ID` | exit 0 |
| C17 | boundary | aborted spec; markers: dead pid, non-numeric name, live non-ancestor marker without session_id (env unset) | dead and non-numeric ignored; marker without id counts as other → exit 1 naming its pid |
| C18 | normal | `complete` spec with live other session | `archive --status complete` exit 0 |
| C19 | error | archive with seed / status mismatch / outside path / destination exists | existing refusals unchanged |
| C20 | normal | active spec, no other live session; `abort` | exit 0; destination printed; destination equals original with only the status value changed to `aborted` |
| C21 | normal | draft spec; `abort` | exit 0, status aborted |
| C22 | boundary | spec already `aborted` in specs/; `abort` | exit 0, moved byte-identical |
| C23 | error | `complete` or `limit` spec; `abort` | exit 1; `use archive`; unchanged |
| C24 | error | seed present; `abort` active spec | exit 1; seed text; unchanged |
| C25 | error | other live session; `abort` without/with flag | without: exit 1 FR7 text, unchanged; with: exit 0 moved |
| C26 | error | destination exists; `abort` | exit 1; `archive destination already exists`; spec unchanged (status still original) |
| C27 | error | `abort` on a path outside specs/, on a nonexistent path in specs/, on a file in a subdirectory of specs/ | exit 1; nothing changed or created |
| C28 | error | spec without frontmatter, or frontmatter without `status`; `abort` | exit 1; `frontmatter`; unchanged |
| C29 | normal | `session` with complete spec | archived (regression) |
| C30 | error | `session` with aborted spec + other live session, plus a complete spec | complete archived; aborted stays; stderr names the aborted spec |
| C31 | boundary | `session` with seed present and a complete spec | nothing archived (regression) |
| C32 | normal | clean specs/ (or missing specs/) | `notice` stdout empty, exit 0; hook stdout empty |
| C33 | normal | `.seed/` with `src/app.py` and `manifest.json` | N1 line names `src/app.py`, not `manifest.json`, includes restore command |
| C34 | normal | active spec with base_commit X; draft spec without base_commit | N2 lines: path, status, X; second with `unknown` |
| C35 | normal | terminal specs: one with seed present, one whose destination exists, one plain | N3 reasons: `unrestored seed backup` (when seed present all terminal lines carry it), destination path, `not archived yet` |
| C36 | normal | `specs/.running/agent1` exists | N4 line with `agent-docs/specs/.running/agent1` and `delete` |
| C37 | normal | all of C33–C36 combined | lines ordered N1, N2…, N3…, N4 |
| C38 | edge | SessionStart payload without session_id; active spec present | hook prints N2 line, exit 0 |
| C39 | edge | a spec file with mode 000 or invalid UTF-8 bytes, plus a readable active spec | `notice` and hook exit 0, no `Traceback`, readable spec's line printed |
| C40 | normal | each state of C32–C37 | hook stdout == `notice` stdout |
| C41 | edge | target config `docs_root: docs`; specs under `docs/specs` | `notice`, `start`, `abort` use `docs/specs` and `docs/spec-logs` |
| C42 | normal | installed 0.43.0 repo with `agent-docs/specs/.active` and an active spec; `update` | migration 0.44.0 announced; `.active` gone; active spec untouched; dry-run keeps `.active` |
| C43 | boundary | installed 0.43.0 repo without `.active`; `update` | succeeds; migration announced |
| C44 | normal | installed SKILL.md | step 1 contains FR16 items in order |
| C45 | normal | `HARNESS_TEXT_TESTS` unset; run the FR17 tests by id | each reported skipped with reason containing `HARNESS_TEXT_TESTS=1`; exit 0 |
| C46 | normal | `HARNESS_TEXT_TESTS=1`; same ids | each runs and passes (none skipped) |
| C47 | boundary | `HARNESS_TEXT_TESTS` set to `0`, to empty, to `true` | skipped as C45 |
| C49 | normal | two other active/draft specs B and C; `start A` | stderr names both B and C |
| C50 | edge | `.active` naming the spec being archived, aborted, or session-archived; `.active` empty; `.active` naming another existing active spec; `validate` with a `.active` present | each subcommand's result as without `.active`; `.active` bytes unchanged |
| C51 | boundary | live marker whose pid the caller cannot signal (permission error), not an ancestor | counts as another live session |
| C52 | boundary | marker pid is a grandparent (not the parent) of the lifecycle process | own |
| C53 | normal | `.seed/` holds two non-manifest files, one nested (`a/b.py`, `c.py`) | N1 names both |
| C54 | edge | `docs_root: docs` target with `docs/specs/.active` and `agent-docs/specs/.active`; `.active` as a directory; `.active` as a symlink | migration deletes only `docs/specs/.active` (regular file); directory and symlink (and its target) stay |
| C48 | normal | `HARNESS_TEXT_TESTS` unset; run the version tests and installed-copy equality tests of `TestTextScan` and `TestRuleText` | they run (not skipped) |

# Quality Applicability
| ISO/IEC 25010:2023 characteristic | applicable | rationale |
| --- | --- | --- |
| Functional suitability | yes | lifecycle commands decide whether workflows may start or be aborted |
| Performance efficiency | no | each command reads a handful of small files; one `ps` walk per abort/aborted-archive; no repository-wide scan added |
| Compatibility | yes | installed repos carry `.active` files and callers using `--resume`; existing CLI behavior for complete/limit and validate must stay |
| Interaction capability | yes | refusals must tell the agent the cause and the next command |
| Reliability | yes | the SessionStart hook runs on every session start and must not fail on broken files |
| Security | no | local CLI run by the same user; no new privilege boundary or external input |
| Maintainability | yes | the hook and `notice` must share one notice source so they cannot drift; wording tests that break on every text edit stay out of the default suite |
| Flexibility | yes | configured `docs_root` must be honored |
| Safety | yes | abort must not alter a spec another live session may own without confirmation, and refusals must leave files unchanged |

# Quality Requirements
| id | characteristic / subcharacteristic | target and context | measure method / inputs / unit | threshold and direction | evidence: automated, review, mutation | source |
| --- | --- | --- | --- | --- | --- | --- |
| QR1 | Reliability / fault tolerance | notice building under C39 fault inputs (mode-000 spec, invalid UTF-8 spec, unreadable marker) via `notice` and the hook | count of runs with exit 0 and no `Traceback` in stderr over runs executed | 100%, higher is better | automated V12; mutation | FR12 |
| QR2 | Safety / fail safe | every refusal of `abort` and `archive` in C14, C17, C19, C23–C28 | sha256 of the spec file before and after, plus absence of new files in spec-logs; refusals passing over refusals executed | 100%, higher is better | automated V6, V7; mutation | FR5, FR6 |
| QR3 | Interaction capability / user error protection | every refusal message in FR2, FR3, FR6, FR7 | presence of the required substrings per refusal; refusals passing over refusals executed | 100%, higher is better | automated V1–V7 | FR2–FR7 |
| QR4 | Compatibility / co-existence | full existing suite plus C8, C12, C19, C29, C31, C42 | Test command result | all pass | automated full suite | FR1, FR8, FR14 |
| QR5 | Maintainability / modularity | hook vs `notice` output for C32–C37 states | byte equality of stdout | 6/6 states equal | automated V11 | FR11 |
| QR6 | Flexibility / adaptability | C41 with `docs_root: docs` | commands operate only under `docs/` | pass | automated V13 | FR13 |
| QR7 | Maintainability / modifiability | the ten FR17 tests under C45–C47 env values | tests reported skipped without `HARNESS_TEXT_TESTS=1` and run with it, over tests × env values | 100%, higher is better | automated V16 | FR17 |

# Verification Obligations
| id | parent requirement/Case ids | variant and target surface | test layer and selection policy | ISO/IEC/IEEE 29119-4 technique | coverage items | coverage target | observation and expected result | evidence procedure |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| V1 | FR1, FR2; C1–C6, C12 | `start` CLI in an installed temp repo | integration; every listed item | decision table | rules: valid-sole, rerun, rerun+resume, other-active, other-draft, other-terminal, invalid, status-draft, run-id-mismatch | 100% | exit codes and stderr substrings per Cases; no `.active` after C1 | Test command |
| V2 | FR3; C7 | `start` with seed | integration | decision table | seed-only, seed+other-active | 100% | exit 1, FR3 text in both | Test command |
| V3 | FR1; C8–C11 | `start` after out-of-band spec changes and leftover `.active` | integration | state transition | transitions: mv-to-logs, rename-then-archive, delete, `.active` missing-target, `.active` empty, `.active` naming the new spec | 100% | exit 0 each; `.active` content unchanged where it pre-existed | Test command |
| V4 | FR4; C14–C17 | live-session classification observed through `archive --status aborted` | integration; real processes (`sleep`) for live non-ancestor pids, the test process pid as ancestor, a reaped child pid as dead; subprocess env explicitly sets or removes `CLAUDE_CODE_SESSION_ID` | equivalence partitioning | classes: ancestor-own, env-own, other-with-id, other-without-id, dead, non-numeric-name, missing-dir | 100% | refusal iff an other class is present | Test command |
| V5 | FR5, FR7; C13, C14, C18, C19 | `archive` CLI | integration | decision table | rules: complete-ok, aborted-other-live, aborted-other-live+flag, complete-other-live, seed, status-mismatch, outside, destination-exists | 100% | exit codes; FR7 substrings; byte-identical move | Test command |
| V6 | FR6, FR7; C20–C28 | `abort` CLI | integration | decision table | rules: active-ok, draft-ok, aborted-ok, complete, limit, seed, other-live, other-live+flag, destination-exists, outside, nonexistent, subdirectory, no-frontmatter, no-status | 100% | exit codes; substrings; on success only the status value differs; on refusal sha256 unchanged and spec-logs unchanged | Test command |
| V7 | FR6 order; C24–C26 | `abort` with two failing conditions at once | integration | decision table | pairs: complete+seed (status reported), seed+other-live (seed reported), other-live+destination (live reported) | 100% | the earlier check's message appears | Test command |
| V8 | FR8; C29–C31 | `session` CLI | integration | decision table | rules: complete, aborted+other-live with complete, seed+complete, draft hint | 100% | archive outcomes and stderr | Test command |
| V9 | FR9, FR10; C32–C37 | `notice` CLI | integration | equivalence partitioning | classes: empty, missing-specs-dir, N1 (manifest excluded), N2 with/without base_commit, N3 seed/destination/plain, N4, combined order | 100% | stdout lines and order per FR9 | Test command |
| V10 | FR11; C38 | progress hook SessionStart | integration; payload with and without session_id | equivalence partitioning | with-id, without-id | 100% | notice on stdout, exit 0 | Test command |
| V11 | FR11, QR5; C40 | hook vs `notice` | integration | equivalence partitioning | states C32–C37 | 100% | byte-equal stdout | Test command |
| V12 | FR12, QR1; C39 | `notice` and hook with broken files | integration | error guessing | guessed defects: mode-000 spec, invalid UTF-8 spec, mode-000 marker dir entry | none — experience-based | exit 0, no Traceback, readable items printed | Test command |
| V13 | FR13, QR6; C41 | `notice`, `start`, `abort` with `docs_root: docs` | integration | equivalence partitioning | default-root, custom-root | 100% | paths under configured root only | Test command |
| V14 | FR14, FR15; C42, C43 | `installer/harness.py update` from an installed 0.43.0 copy | integration | scenario | with-.active, with-.active dry-run, without-.active | 100% | migration 0.44.0 announced; `.active` deleted only when not dry run; other spec files untouched; manifest version 0.44.0 | Test command |
| V15 | FR16; C44 | installed SKILL.md text | integration (text) + review R1 | syntax | the five FR16 items and their order | 100% | substrings present in order within step 1 | Test command; R1 |
| V17 | FR1, FR2, FR4, FR9, FR13, FR14; C49–C54 | gaps from verifier round 1 | integration | equivalence partitioning | items: start-two-others, status-before-run-id order, draft/run-id messages, `.active` via archive/abort/session naming the moved spec, `.active` empty and naming another active spec through those subcommands, validate with `.active`, permission-error live, grandparent own, two nested seed files, migration custom docs_root, `.active` directory, `.active` symlink | 100% | per Cases | Test command |
| V16 | FR17, QR7; C45–C48 | unittest runs of the FR17 test ids and the kept tests in a subprocess with controlled env | integration | equivalence partitioning | env classes: unset, `1`, `0`, empty, `true`; test classes: gated, kept | 100% | gated tests skipped except under `1` with the reason text; kept tests run under unset | Test command |

# Assumptions and Defaults
| id | decision | evidence and uncertainty | brief v<n> — approved / vetoed → <answer> / user answer |
| --- | --- | --- | --- |
| A1 | Abort is a new `abort` subcommand that checks before changing status; `archive --status aborted` keeps working with the same live check | user chose option A over checking only in `archive` | user answer |
| A2 | A live marker without a session id counts as another session | conservative for safety; causes false refusals for pre-0.34.3 or Codex markers, bypassable with the flag | brief v1 — approved |
| A3 | Own session = ancestor pid or matching `CLAUDE_CODE_SESSION_ID` | Bash tool processes are children of the Claude process whose pid names the marker (observed: shell ppid 4744 = marker 4744); env var observed set in Bash | brief v1 — approved |
| A4 | `--resume` kept as an accepted no-op | no skill passes it; removing it would break scripted callers | brief v1 — approved |
| A5 | Notice printed on every SessionStart source (startup, resume, clear, compact) | re-informs after compaction; small output | brief v1 — approved |
| A6 | `.gitignore` keeps the `agent-docs/specs/.active` line | prevents committing leftovers from older harness versions on other branches | brief v1 — approved |
| A7 | `session` archives aborted specs only under FR5's live check | a hand-edited aborted status should not move a spec a live session may own | brief v1 — approved |
| A8 | Test command uses `.venv/bin/python` | system python3 lacks hypothesis/pytest (baseline: 2 import errors, 1232 tests) | brief v1 — approved |
| A9 | Mutation tool none; 8–10 hand mutations | mutmut 2.5.1 is installed but per-mutant suite time is minutes | brief v1 — approved |
| A10 | Version 0.44.0 (minor) | new subcommand and behavior change | brief v1 — approved |
| A11 | Roles use installed default model sonnet, effort medium | change is local to a few scripts | brief v1 — approved |
| A12 | Wording checks added in 0.42.0/0.43.0 leave the default suite behind an env opt-in; before/after evaluations are not default evidence | user: 0.42/0.43 skill-change regression tests and Evaluation leave the always-run set; chose project-level opt-in of wording checks | user answer |
| A13 | Opt-in variable `HARNESS_TEXT_TESTS=1`; gated set = the nine FR17 tests plus C44; version and copy-equality tests stay always-run | the nine are the 0.42.0/0.43.0-added tests asserting payload or README wording (scan of tests added by commits 471d97a and 17bb3bf); copy-equality does not change when wording changes | brief v2 — stated, not vetoed |
| A14 | This run's Test command sets `HARNESS_TEXT_TESTS=1` | this run edits SKILL.md and README | brief v2 — stated, not vetoed |

# Traceability
| requirement id | Case ids | obligation ids | evidence procedure |
| --- | --- | --- | --- |
| FR1 | C1, C8–C11 | V1, V3 | Test command |
| FR2 | C1–C6, C12 | V1 | Test command |
| FR3 | C7 | V2 | Test command |
| FR4 | C14–C17 | V4 | Test command |
| FR5 | C13, C14, C18, C19 | V5 | Test command |
| FR6 | C20–C28 | V6, V7 | Test command |
| FR7 | C14, C25 | V5, V6 | Test command |
| FR8 | C29–C31 | V8 | Test command |
| FR9, FR10 | C32–C37 | V9 | Test command |
| FR11 | C38, C40 | V10, V11 | Test command |
| FR12 | C39 | V12 | Test command |
| FR13 | C41 | V13 | Test command |
| FR14, FR15 | C42, C43 | V14 | Test command |
| FR16 | C44 | V15 | Test command; R1 |
| FR17 | C45–C48 | V16 | Test command; R2 |
| FR1, FR2, FR4, FR9, FR13, FR14 (round 1 gaps) | C49–C54 | V17 | Test command |
| QR1–QR7 | — | V12, V6, V7, V1–V7, full suite, V11, V13, V16 | Test command |

# Workflow Control
| item | value |
| --- | --- |
| correction batches used | 4 |
| verifier invocations | 2 |
| open finding ids | none blocking in tests; B1–B3 evidence added after the last audit (unaudited) |

Audit state (one entry per obligation; retain prior decisions in the execution ledger):
| obligation id | spec version | evidence references and revision | accepted / open / invalidated / pending | rationale and mutation outcome | dependencies and reopening evidence |
| --- | --- | --- | --- | --- | --- |
| V2, V5–V8, V10–V13, V15 (test part), V16, FR15, FR17 gating | 3 | verifier round 1 | accepted | test-verifier round 1; hand mutations M2–M10 detected | invalidated by changes to their tests or helpers |
| V1, V3, V14 | 4 | verifier round 2 | accepted | F1, F2, F5 closed by batches 2–3; mutations N1, N2, N6 detected | — |
| V4 | 4 | main after round 2 (no audit) | evidence added, unaudited | batch 4: TestUnreadableLiveMarkerCountsAsOther; mutation skipping unreadable markers detected. Before: B1: no test supplies a live marker with unreadable content (empty, invalid JSON, non-object, non-string session_id); mutation skipping such markers survived | — |
| V17 | 4 | main after round 2 (no audit) | evidence added, unaudited | batch 4: TestNoActiveFileIsCreated and baseline absence in TestActiveFileNamingTheMovedSpec; mutation archive-touches-`.active` detected. Before: B2: no test observes that archive/abort/session/notice/validate do not create an absent `.active`; mutation making archive touch `.active` survived | — |
| V5, V6, V9, V13 | 4 | main after round 2 (no audit) | evidence added, unaudited | batch 4: TestRepoRelativePathForms; mutations abort-prints-absolute, notice-absolute-paths, seed-names-prefixed detected by it. Before: B3: path assertions are substring checks, so absolute or `.seed/`-prefixed paths pass; mutation making abort print an absolute destination failed only through the baseline-comparison test (temp paths differ), not a path-form assertion | — |

Execution ledger (append attempts; preserve failed approaches):
| attempt | finding / failure signature | cause hypothesis | changed approach / new evidence | result / disposition |
| --- | --- | --- | --- | --- |
| 0 | baseline: 2 errors of 1232 with system python3 | test_isolation_telemetry and test_session_metrics import hypothesis/pytest, absent from system python3 | Test command uses .venv/bin/python (A8) | resolved: suite ran under .venv |
| 1 | Test command: 1423 tests, 7 failures. 6: updates from older installs exit 1 (EOFError at `Apply migration` prompt) or count 37 != 36 confirmation lines; 1: archive seed refusal lacks `python3 .harness/bin/seed.py restore` | test defect: fixed prompt-answer counts predate the 0.44.0 migration prompt; implementation defect: Errors section requires the restore command for archive too | correction batch 1: test-implementer adjusts prompt counts; implementer adds the restore command to the archive seed refusal | fixed: Test command 1423 tests OK (HARNESS_TEXT_TESTS=1, 558 s) |
| 2 | verifier round 1 retry: F1 start order/messages/multiple names; F2 `.active` naming the moved spec; F3 permission-error liveness and grandparent ancestor; F4 multiple seed files; F5 migration custom docs_root and non-regular `.active`; F6 README sentence without obligation | evidence gaps; F6 spec gap | v4: FR2 message substrings, C49–C54, V17, R2; correction batch 2 to test-implementer | pending |
| 2a | hand mutations M1–M10 (stale `.active` in start; seed after other-active; abort destination before live; live check for all archive statuses; no-id marker own; no ancestor walk; manifest in N1; N3 destination before seed; hook notice after early return; migration deletes on dry run) | — | run on repo copies with test_spec_active_state | 10/10 detected by intended tests (M5 rerun after an rsync setup failure) |
| 2b | verifier-proposed mutations N1–N6 (archive deletes `.active` naming the moved spec; run-id before status; PermissionError as dead; parent-only ancestor; N1 first file only; migration hard-coded root) after batch 2 | N2–N6 detected; N1 survived | `.active` fixtures use `agent-docs/specs/<name>`; legacy format is the bare file name (base_commit cmd_start writes `path.name + "\n"`) | correction batch 3: fixtures use the bare name; rerun N1 | N1 detected (archive and session `naming-moved` subtests); M1 rerun still detected; N2–N6 detected |
| 3 | R1/R2 reviews after `python3 installer/harness.py update . --no-commit` (installed 0.44.0; leftover `agent-docs/specs/.active` deleted by the migration) | — | R1: `.harness/skills/workflow-approach/SKILL.md` line 184 step 1 holds items (1) seed restore, (2) retrospective approved and written, (3) `spec_lifecycle.py abort --spec PATH`, (4) ask the user and re-run with `--other-sessions-confirmed` only after the user confirms none does, (5) `workflow_marker.py end --run-id ID --status aborted`, in order; R2: README.md line 115 under `## 이 저장소에서 개발하기` states skill, rule, README text changes run `HARNESS_TEXT_TESTS=1 python3 -m unittest discover -s tests` | R1 pass; R2 pass; full suite 1436 OK (573 s) |
| 4 | verifier round 2 (last) retry: B1 unreadable marker content, B2 `.active` creation by other subcommands, B3 repo-relative path form | evidence gaps | triage mutations: B1 skip-unreadable-marker survived; B2 archive-touches-`.active` survived; B3 abort-prints-absolute detected only incidentally | gaps confirmed; corrections need a third audit beyond max_verifier_invocations 2 → stop with status limit; implementation behavior for B1–B3 read by main matches FR4/FR1/FR5–FR9 (unreadable JSON → no session id → other; no `.active` writes; `relative_to(REPO_ROOT)` and `.seed/`-relative names) |
| 5 | user asked to add the B1–B3 tests after the verifier budget was spent | — | correction batch 4 (helper wrote bytes via write_text → TypeError, fixed); mutations B1, B2, B3 (abort absolute), B3b (notice absolute), B3c (`.seed/`-prefixed names) each detected by the intended new test | evidence added without a third audit; status stays limit |
| note | hand mutations ran on rsync copies of the working tree with `test_spec_active_state` only, not via seed.py on the tree with the full Test command | — | parallel runs without touching the working tree | recorded deviation from the step 6 procedure |

# Version Log
## v1
- Initial draft from the stale `.active` investigation, two subagent reviews, and the user's choice of option A.
## v2
- User added: wording tests added in 0.42.0/0.43.0 leave the default suite (FR17, I5, C45–C48, V16, QR7, A12–A14); README and the modules holding gated tests or hard-coded 0.43.0 versions join the paths; Test command sets `HARNESS_TEXT_TESTS=1`. Approved with brief v1 defaults.
## v3
- Contract-only: FR15 needs the hard-coded 0.43.0 in test_progress_retire, test_synced_blocks, test_telemetry, test_session_metrics, test_workflow_markers; they join the Tests paths (reported by test-implementer).
## v4
- Verifier round 1: FR2 names the existing status and run-id messages; FR9 N1 covers a manifest-only seed; Cases C49–C54 and V17 close gaps F1–F5; R2 reviews the README sentence of FR17 (F6).

# Retrospective
## 2026-11-13
| observation | evidence | how to re-check |
| --- | --- | --- |
| none | the other observations are reproduced at once by running the test suite or recovered from git history | — |

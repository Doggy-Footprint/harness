---
version: 4
run_id: 196b9bca4789bf84
status: complete
base_commit: 631d5fe08133da4feffee2aeb6a7fe4d231abd66
max_verifier_invocations: 2
commit: 631d5fe08133da4feffee2aeb6a7fe4d231abd66
---

# User Intent
| id | stakeholder | intention | observable goal |
| --- | --- | --- | --- |
| UI1 | downstream project owner | keep harness rule text out of the project's own `AGENTS.md` | after install/update, the managed block in `AGENTS.md` holds only an import line of `.harness/instructions/harness-block.md`, and the block no longer changes between harness versions |
| UI2 | downstream project owner | stop committing by hand after every `update` | after `update`, the files the update changed are committed and `git status` shows none of them |
| UI3 | downstream project owner | never have own edits swept into the harness commit | when a file the update would commit was already modified before the run, the user is warned before any write and nothing is auto-committed |
| UI4 | Claude Code session running `update` | not be forced to write a session progress for changes the installer made | a Bash call whose only project change is a `harness.py update` run (including its commit) does not mark the session as having changed the project |

# Scope
In scope: managed-block import in `install_or_merge_agents_md` and `cmd_doctor`; auto-commit in `cmd_update` with a pre-write dirty check and `--no-commit`; an installer-run record written by `cmd_update` and consumed by the progress hook; a 0.40.0 migration entry announcing the changes; Progress Rule text, README, and `rearrange-docs` wording; VERSION 0.40.0.
Out of scope: lazy-loading of hook-backed rules (stage B, a later run); auto-commit on `install`; pushing; any change to how `.harness/` files are tracked; Codex reading the imported rules (Codex is unsupported and reads `AGENTS.md` raw); exempting `install` runs from progress.

# Paths
Implementation: installer/harness.py, harness/lib/progress.py, harness/hooks/progress_hook.py, harness/instructions/harness-block.md, harness/VERSION, harness/skills/rearrange-docs/SKILL.md, README.md
Tests: tests/test_installer.py, tests/test_progress.py, tests/test_update_commit.py, tests/test_doc_records.py, tests/test_telemetry.py, tests/test_session_metrics.py, tests/test_progress_retire.py, tests/test_workflow_markers.py, tests/test_comment_gate.py
Test command: python3 -m unittest discover -s tests
Review evidence: R1 — main runs `claude -p` in a throwaway repo whose `CLAUDE.md` is `@AGENTS.md` and whose `AGENTS.md` holds the 0.40.0 managed block importing a block file containing a unique token; expected: the reply quotes the token. Pre-approval run on 2026-11-10 quoted the token.
Fuzzing: none — inputs are git working-tree states enumerated by the decision table; no parser or untrusted byte input is added.
Mutation tool: none

# Signatures
installer/harness.py: `cmd_update(target: Path, dry_run: bool, no_ci: bool, ask_tools: bool = False, model: str | None = None, commit: bool = True) -> int`
installer/harness.py CLI: `update` accepts `--no-commit`; using it with `install`, `doctor`, or `import` is a parser error.
harness/lib/progress.py: `INSTALLER_RUN_RECORD = ".harness/sessions/installer-run.json"`
harness/lib/progress.py: `write_installer_run(repo_root: Path, before: str, after: str) -> None`
harness/lib/progress.py: `consume_installer_run(repo_root: Path, before: str, after: str) -> bool` — True and deletes the record when it exists and its `before`/`after` equal the arguments; otherwise False and leaves the record in place.
AGENTS.md managed block written by install and update (exact bytes): `<!-- harness:begin -->\n@.harness/instructions/harness-block.md\n<!-- harness:end -->\n`

Output strings (paths sorted, joined by `, `):
- S1 pre-dirty stdout line, printed before migration plans/prompts (also in dry-run): `warning: auto-commit skipped: already modified: <pre-dirty candidate paths>`
- S2 `manual review` item after a pre-dirty skip (not in dry-run): `auto-commit skipped; commit these files yourself: <paths changed by the run>`
- S3 `manual review` item for FR8: `auto-commit skipped: this update changed files that were already modified: <those paths>; commit these files yourself: <paths changed by the run>`
- S4 `manual review` item for FR11: `auto-commit failed: <first non-empty stderr line of git, else of stdout>; commit these files yourself: <paths changed by the run>`
- S5 `skip` item for FR10: `auto-commit: nothing to commit`
- S6 `info` item, dry-run without pre-dirty candidate: `auto-commit: would commit the files this update writes`; dry-run with one: `auto-commit: would skip`
- S7 `info` item after a successful commit: `auto-commit: <full commit id>`
- S8 0.40.0 migration label `import the managed block; auto-commit updates; exempt update changes from progress`; plan lines, in order: `the AGENTS.md managed block becomes an import of .harness/instructions/harness-block.md`, `update commits the files it changed, skips the commit when any of them was already modified, and --no-commit disables it`, `changes made by harness.py update alone inside one Claude Code Bash call no longer require a session progress`, `no data is migrated; the regular update step rewrites the managed block`
- First fingerprint for FR14 is taken right after `.harness/manifest.json` parses; the record is then written on every later non-dry-run return of `cmd_update`.

# Functional Requirements
| id | requirement | priority | source |
| --- | --- | --- | --- |
| FR1 | `install` and `update` write the managed block as the exact import block in Signatures: replacing an existing `<!-- harness:begin … -->…<!-- harness:end -->` region (any version, any body) in place, appending it after existing content when no marker exists, and preceding it with the project-definition TODO when `AGENTS.md` does not exist. Content outside the markers is unchanged. | must | UI1 |
| FR2 | The duplicate-heading `manual review` check keeps comparing headings outside the markers with the headings of `harness/instructions/harness-block.md`. | must | UI1 |
| FR3 | `doctor` reports a conflict `AGENTS.md: managed block missing` when no marker region exists, and `AGENTS.md: managed block does not import .harness/instructions/harness-block.md` when the region's body is not exactly the import line; it reports neither for an `AGENTS.md` written by 0.40.0 install/update. | must | UI1 |
| FR4 | Running `update` twice in a row on the same version leaves `AGENTS.md` byte-identical after the second run. | must | UI1 |
| FR5 | Before any write (before migration prompts), `update` computes the commit-candidate set: every path in the new owned set, every path in the old manifest, `.harness/manifest.json`, `.harness/config.json`, `AGENTS.md`, `CLAUDE.md`, `.claude/settings.json`, `.codex/hooks.json`, `.gitignore`, the `agent-docs` scaffold files (`index.md`, `stale.md`, `stale/.gitkeep` of managed dirs, `.gitkeep` of progress dirs), and the `.claude/skills/<name>` links. A candidate is pre-dirty when `git status --porcelain --untracked-files=all` lists it (staged, unstaged, or untracked). | must | UI3 |
| FR6 | When any candidate is pre-dirty, `update` prints to stdout, before migration prompts, a line starting `warning: auto-commit skipped:` followed by the pre-dirty paths; it still applies the update; it makes no commit; and its final report lists under `manual review` the paths changed by the run that the user must commit. Exit code is unchanged by the skip. | must | UI3, user answer 1 |
| FR7 | When no candidate is pre-dirty, after all writes `update` commits exactly the paths the run changed — every path git status lists after the run that it did not list before, plus pre-run-listed paths whose content the run changed — and no other path. Paths staged by the user before the run that are not changed by the run stay staged and are not in the commit. | must | UI2 |
| FR8 | If the run changed a path that was listed by git status before the run but was not a candidate (e.g., a migration edited a pre-dirty record), no commit is made and the path is reported under `manual review` with the same skip wording. | must | UI3 |
| FR9 | The auto-commit message's first line is `Update harness <old version> -> <new version>` (or `Update harness to <version>` when they are equal), followed by a blank line, `Request: harness.py update`, and `Intent: commit the files this harness update wrote`. The commit runs the repository's git hooks (no `--no-verify`). | must | UI2 |
| FR10 | When the run changed no path, no commit is made and the report says `skip` with `auto-commit: nothing to commit`. | must | UI2 |
| FR11 | When `git commit` fails (missing identity, merge in progress, rejecting hook, other), the written files stay in the working tree, the report lists under `manual review` `auto-commit failed: <first stderr line>` and the paths to commit, and the exit code is unchanged by the failure. | must | UI2 |
| FR12 | `update --no-commit` performs no pre-dirty warning and no commit; everything else is unchanged. `update --dry-run` makes no commit and reports under `info` either the pre-dirty warning or `auto-commit: would commit the files this update writes`. | must | user answer 2 |
| FR13 | `install` never commits. | must | user answer 3 |
| FR14 | `update` (not dry-run) computes the progress worktree fingerprint (`progress.git_worktree_fingerprint(target, ".harness/")`) before its first write and after its last action (after the commit or its skip/failure), and writes `{"before": ..., "after": ...}` with `write_installer_run`; the record is written on every non-dry-run exit path after the first fingerprint, including conflict and migration-declined exits. | must | UI4 |
| FR15 | The progress hook's PostToolUse for a Bash call does not mark the session modified when its pre-call snapshot and post-call fingerprint equal a stored record's `before` and `after` (consuming the record); in every other case behavior is unchanged. | must | UI4 |
| FR16 | `.harness/sessions/installer-run.json` is added to the installer's gitignore lines. | must | UI4 |
| FR17 | `MIGRATIONS` gains a 0.40.0 entry whose plan lists: the managed block becomes an import line; `update` auto-commits the files it changed, skips when they were already modified, and `--no-commit` disables it; changes a `harness.py update` makes inside a Claude Code Bash call no longer require a session progress. It migrates no data. | must | AGENTS.md "update MUST provide version-by-version migration steps" |
| FR18 | The Progress Rule states that changes made by `harness.py update` alone within one Bash call, including its commit, do not count. README and `rearrange-docs` describe the managed block as the import of `.harness/instructions/harness-block.md`; README documents auto-commit and `--no-commit`. | must | UI1, UI2, UI4 |

# Errors
- `git commit` fails during auto-commit — `manual review` item `auto-commit failed: <first stderr line>` plus paths — files remain written, HEAD unchanged, exit code as without the commit.
- Pre-dirty candidate — stdout `warning: auto-commit skipped: <paths>` before migration prompts and a `manual review` list — update applied, HEAD unchanged.
- Run changed a non-candidate pre-dirty path — `manual review` skip item naming it — update applied, HEAD unchanged.
- Installer-run record missing, unreadable, malformed JSON, or mismatching — hook falls back to existing behavior (session marked when fingerprint changed) — record left as is when mismatching, no exception escapes the hook.
- `--no-commit` with a command other than `update` — argparse error, exit 2 — nothing written.

# Cases
| id | level | input / state | expected result |
| --- | --- | --- | --- |
| C1 | normal | fresh repo, `install` | `AGENTS.md` = definition TODO + exact import block; no commit made |
| C2 | normal | 0.39.0-style install committed, block with full body and versioned marker, user text above and below; `update` | block replaced by exact import block; outside text byte-identical; doctor clean |
| C3 | normal | clean committed install of older version; `update` | one new commit with FR9 message containing exactly the changed paths; `git status --porcelain` empty afterwards (ignoring ignored files) |
| C4 | normal | same as C3 plus an unrelated user file staged before the run | commit excludes it; it is still staged afterwards |
| C5 | error | clean committed install; user modified `.claude/settings.json` (unstaged) before `update` | warning line printed before migration prompts naming it; update applied; HEAD unchanged; `manual review` lists paths to commit |
| C6 | error | pre-dirty candidate is untracked (e.g., a new owned path already exists untracked) or staged | same as C5 |
| C7 | error | committed install, no identity configured (`user.email` unset via isolated HOME / config) | `auto-commit failed:` reported; files written; HEAD unchanged; exit 0 |
| C8 | error | committed install, repo pre-commit hook path exits 1 | `auto-commit failed:` reported; HEAD unchanged |
| C9 | boundary | committed install already at current version; `update` twice | second run: no commit, `auto-commit: nothing to commit`; `AGENTS.md` identical |
| C10 | boundary | `update --no-commit` on clean committed older install | no warning, no commit, files written |
| C11 | boundary | `update --dry-run` on clean committed older install, and on one with a pre-dirty candidate | no commit, no writes; `info` says would-commit or the warning respectively |
| C12 | edge | migration in range edits a pre-dirty `agent-docs` record that is not a candidate | no commit; the record named under `manual review` |
| C13 | error | `install --no-commit` | argparse error, exit 2 |
| C14 | normal | progress hook: PreToolUse snapshot, then installer-run record with before = snapshot and after = current fingerprint, then PostToolUse | session not marked modified; record deleted |
| C15 | error | progress hook: record whose `after` differs from current fingerprint (another change in the same call) | session marked modified; record kept |
| C16 | error | progress hook: record file malformed JSON / missing keys | session marked modified; hook exits normally |
| C17 | normal | end-to-end: real `update` of a committed older install run between PreToolUse and PostToolUse payloads | session not marked; HEAD advanced by one commit |
| C18 | normal | doctor on `AGENTS.md` whose marker region holds the old full body | conflict `does not import` reported |
| C19 | normal | update from 0.39.0 prints migration 0.40.0 plan lines per FR17 | lines present |
| C20 | edge | update exits with a conflict after the first fingerprint (e.g., migration declined) | record written; no commit |

# Quality Applicability
| ISO/IEC 25010:2023 characteristic | applicable | rationale |
| --- | --- | --- |
| Functional suitability | yes | the commit set and block content must be exactly right |
| Performance efficiency | no | one-shot CLI adding a few git calls; hook adds one small file read |
| Compatibility | yes | Claude Code must still load the rules through a two-level import |
| Interaction capability | yes | the warning and failure messages must tell the user what to commit |
| Reliability | yes | a failed commit must not lose or roll back the update |
| Security | yes | auto-commit must never commit a file the user modified before the run, and must keep the repo's hooks (secret scanning) in the path |
| Maintainability | yes | existing suite must keep passing |
| Flexibility | yes | installability: existing 0.39.0 installs migrate through `update` |
| Safety | no | no physical or human-safety effect |

# Quality Requirements
| id | characteristic / subcharacteristic | target and context | measure method / inputs / unit | threshold and direction | evidence: automated, review, mutation | source |
| --- | --- | --- | --- | --- | --- | --- |
| QR1 | Compatibility / interoperability | Claude Code loading `CLAUDE.md` → `@AGENTS.md` → import block | R1 procedure; count of runs quoting the token | 1 of 1, higher is better | review R1 | UI1 |
| QR2 | Interaction capability / user error protection | C5, C6, C7, C8, C12 outputs | each output names every affected path; count of cases missing a path | 0, lower is better | automated O8, O9 | UI3 |
| QR3 | Reliability / fault tolerance | C7, C8 | files written by update present and HEAD unchanged after commit failure; count of violations | 0, lower is better | automated O9 | UI2 |
| QR4 | Security / integrity | C4, C5, C6, C12 | paths in the auto-commit that were pre-run dirty and not changed by the run, or pre-dirty candidates; count | 0, lower is better | automated O6, O8, mutation | UI3 |
| QR5 | Maintainability / modifiability | full Test command | tests failing or erroring other than the baseline errors recorded in the Version Log | 0 new, lower is better | automated Test command | project |
| QR6 | Flexibility / installability | C2, C19 | 0.39.0-style install updates to 0.40.0 with doctor clean; count of doctor conflicts | 0, lower is better | automated O2, O12 | AGENTS.md migration rule |

# Verification Obligations
| id | parent requirement/Case ids | variant and target surface | test layer and selection policy | ISO/IEC/IEEE 29119-4 technique | coverage items | coverage target | observation and expected result | evidence procedure |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| O1 | FR1, C1, C2 | `AGENTS.md` bytes after install/update via CLI | integration (installer subprocess on temp git repo); one test per partition | equivalence partitioning | P1 no `AGENTS.md`; P2 `AGENTS.md` without marker; P3 marker with old versioned full body and outside text; P4 marker with already-import body | 100% | file equals expected bytes built from the Signatures literal, outside text preserved | Test command |
| O2 | FR3, C18, QR6 | `doctor` stdout and exit code | integration | equivalence partitioning | D1 import body (clean); D2 old full body; D3 marker missing | 100% | D1 no AGENTS.md conflict; D2/D3 exact FR3 strings | Test command |
| O3 | FR2 | install report | integration | error guessing | duplicate heading outside block still flagged | none — experience-based | `manual review` contains the duplicate-heading item | Test command |
| O4 | FR4, FR10, C9 | `AGENTS.md` and git log after two updates | integration | boundary value analysis (2-value) | B1 first run at older version; B2 second run at same version | 100% | identical bytes; no second commit; `auto-commit: nothing to commit` | Test command |
| O5 | FR7, FR9, C3 | HEAD commit after update | integration | equivalence partitioning | E1 clean committed older install; E2 clean committed install already at the current version whose update still changes a file (e.g. `--model opus`), subject `Update harness to <version>` | 100% | exactly one new commit; its paths equal the paths changed by the run (computed by test from pre/post snapshots); message matches FR9; `git status --porcelain` empty | Test command |
| O6 | FR7, C4, QR4 | index and HEAD commit | integration | decision table | rule: unrelated staged file + clean candidates | 100% | staged file not in commit and still staged | Test command |
| O7 | FR5, FR6, FR7, FR8, FR12 | commit/skip decision | integration | decision table | T1 clean, commit on → commit; T2 unstaged candidate → skip+warn; T3 staged candidate → skip+warn; T4 untracked candidate → skip+warn; T5 non-candidate pre-dirty path changed by run → skip; T6 `--no-commit` → neither; T7 `--dry-run` clean → info would-commit; T8 `--dry-run` pre-dirty → info warning | 100% | HEAD change matches rule; output strings per FR6/FR8/FR12 | Test command |
| O8 | FR6, C5, QR2, QR4 | stdout ordering | integration | error guessing | warning printed before first `Apply migration` prompt | none — experience-based | index of warning line < index of first prompt in stdout | Test command |
| O9 | FR11, C7, C8, QR3 | failure handling | integration | equivalence partitioning | F1 no identity; F2 rejecting pre-commit hook | 100% | `auto-commit failed:` item; written files present; HEAD unchanged; exit 0 | Test command |
| O10 | FR13, C13 | install and CLI parsing | integration | equivalence partitioning | I1 install creates no commit; I2 `install --no-commit` exits 2 | 100% | HEAD absent/unchanged; argparse error | Test command |
| O11 | FR14, FR15, FR16, C14–C17, C20 | `consume_installer_run`, hook marker state, record file | unit for library; integration for hook and end-to-end | decision table | H1 record match → not marked, record deleted; H2 `after` mismatch → marked, record kept; H3 `before` mismatch → marked; H4 malformed record → marked, no crash; H5 no record → existing behavior; H6 end-to-end update between hook payloads → not marked; H7 conflict exit writes record; H8 gitignore line present | 100% | marker file presence per existing hook tests' observation; record file state | Test command |
| O12 | FR17, C19 | update stdout | integration | equivalence partitioning | update from 0.39.0 | 100% | `migration 0.40.0:` and the three FR17 plan statements present | Test command |
| O13 | FR18 | block, README, skill text | review | error guessing | Progress Rule sentence; README import/auto-commit/`--no-commit`; rearrange-docs wording | none — experience-based | main reads the three files | review by main |

# Assumptions and Defaults
| id | decision | evidence and uncertainty | brief v<n> — approved / vetoed → <answer> / user answer |
| --- | --- | --- | --- |
| A1 | pre-dirty candidate → warn, apply update, skip the whole auto-commit | partial commits could leave HEAD inconsistent (hooks committed, settings not) | user answer |
| A2 | auto-commit on by default; `--no-commit` disables | user's problem is the manual commit after every update | user answer |
| A3 | auto-commit only for `update`, not `install` | | user answer |
| A4 | this run covers import (A), auto-commit, and progress exemption as 0.40.0; lazy-load (B) is a later run | user: "단계적으로 A -> B 순으로 진행" | brief v1 — approved |
| A5 | exemption by before/after fingerprint record rather than command-text matching | command text cannot tell `update && other-edit` apart; fingerprint includes HEAD so the commit is covered | brief v1 — approved |
| A6 | marker loses its version (`<!-- harness:begin -->`) | a versioned marker would change `AGENTS.md` every update; `MARKER_RE` already matches the unversioned form | brief v1 — approved |
| A7 | commit failure and skip do not change the exit code | the update itself succeeded; scripts calling `update --all` should not fail on a commit hiccup | brief v1 — approved |
| A8 | this repo's own dogfood `update .` runs with `--no-commit` so source and installed copy stay in one commit | repo history bundles `harness/` and `.harness/` changes per version | brief v1 — approved |
| A9 | the exemption covers `update` only, not `install` | user scoped auto-commit to update; install is a one-time setup that a session should record | brief v1 — approved |
| A10 | a deliberate forged record could bypass the progress requirement; not defended | the record lives in `.harness/sessions/`; forging needs intent to evade the harness | brief v1 — approved |

# Traceability
| requirement id | Case ids | obligation ids | evidence procedure |
| --- | --- | --- | --- |
| FR1 | C1, C2 | O1 | Test command |
| FR2 | — | O3 | Test command |
| FR3 | C18 | O2 | Test command |
| FR4 | C9 | O4 | Test command |
| FR5 | C5, C6 | O7 | Test command |
| FR6 | C5, C6 | O7, O8 | Test command |
| FR7 | C3, C4 | O5, O6, O7 | Test command |
| FR8 | C12 | O7 | Test command |
| FR9 | C3 | O5 | Test command |
| FR10 | C9 | O4 | Test command |
| FR11 | C7, C8 | O9 | Test command |
| FR12 | C10, C11 | O7 | Test command |
| FR13 | C1, C13 | O10 | Test command |
| FR14 | C17, C20 | O11 | Test command |
| FR15 | C14, C15, C16 | O11 | Test command |
| FR16 | — | O11 | Test command |
| FR17 | C19 | O12 | Test command |
| FR18 | — | O13 | review by main |
| QR1 | — | R1 | review R1 |

# Workflow Control
| item | value |
| --- | --- |
| correction batches used | 2 |
| verifier invocations | 2 |
| open finding ids | none |

Audit state (one entry per obligation; retain prior decisions in the execution ledger):
| obligation id | spec version | evidence references and revision | accepted / open / invalidated / pending | rationale and mutation outcome | dependencies and reopening evidence |
| --- | --- | --- | --- | --- | --- |
| O1 | 4 | Test command run2; verifier 1 | accepted | verifier 1 accepted; hand mutations M1–M12 detected where targeted | Tests or implementation change of this behavior reopens |
| O2 | 4 | Test command run3; verifiers 1 and 2 | accepted | verifier 1 accepted; advisory 3 confirmed by M14 (doctor accepting import line plus extra text) surviving; batch 2 adds that body to D2 | D2 test change reopens |
| O3 | 4 | Test command run2; verifier 1 | accepted | verifier 1 accepted; hand mutations M1–M12 detected where targeted | Tests or implementation change of this behavior reopens |
| O4 | 4 | Test command run2; verifier 1 | accepted | verifier 1 accepted; hand mutations M1–M12 detected where targeted | Tests or implementation change of this behavior reopens |
| O5 | 4 | Test command run2; verifier 1 | accepted | verifier 1 accepted; hand mutations M1–M12 detected where targeted | Tests or implementation change of this behavior reopens |
| O6 | 4 | Test command run2; verifier 1 | accepted | verifier 1 accepted; hand mutations M1–M12 detected where targeted | Tests or implementation change of this behavior reopens |
| O7 | 4 | Test command run3 (929 tests, baseline errors only); batch 2 tests; verifier 2 | accepted | V1-F1 resolved by multi-path S1 tests (real and dry-run); M13 detected | Tests or implementation change of this behavior reopens |
| O8 | 4 | Test command run2; verifier 1 | accepted | verifier 1 accepted; hand mutations M1–M12 detected where targeted | Tests or implementation change of this behavior reopens |
| O9 | 4 | Test command run2; verifier 1 | accepted | verifier 1 accepted; hand mutations M1–M12 detected where targeted | Tests or implementation change of this behavior reopens |
| O10 | 4 | Test command run2; verifier 1 | accepted | verifier 1 accepted; hand mutations M1–M12 detected where targeted | Tests or implementation change of this behavior reopens |
| O11 | 4 | Test command run2; verifier 1 | accepted | verifier 1 accepted; hand mutations M1–M12 detected where targeted | Tests or implementation change of this behavior reopens |
| O12 | 4 | Test command run2; verifier 1 | accepted | verifier 1 accepted; hand mutations M1–M12 detected where targeted | Tests or implementation change of this behavior reopens |
| O13 | 4 | main review of harness-block.md Progress Rule, README, rearrange-docs diff | accepted | wording states the import, auto-commit, --no-commit and the update exemption | text change reopens |
| R1 | 4 | claude -p token quote 2026-11-10 | accepted | nested import loaded | Claude Code import behavior change reopens |

Execution ledger (append attempts; preserve failed approaches):
| attempt | finding / failure signature | cause hypothesis | changed approach / new evidence | result / disposition |
| --- | --- | --- | --- | --- |
| 3 | verifier 1: V1-F1 blocking — S1 never observed with ≥2 pre-dirty paths; advisory: D2 never uses an import-plus-extra body | M13 and M14 survived (targeted tests green) | correction batch 2 to test-implementer: multi-path S1 for T2–T4 style real run and T8 dry-run; D2 variant body = import line + extra line | M13 and M14 now detected by the new tests; run3 baseline errors only |
| 4 | hand mutations M1, M2, M4–M7, M9–M12 (10 strongest classes: commit sweep, untracked not pre-dirty, FR8 drop, consume ignores before, record only on success, commit despite pre-dirty, doctor accepts any body, versioned marker, failure changes exit code, warning after migrations) | each failed its intended assertion (O6, T4, T5, H3, H7, T2–T4, D2, O1/O4, F1/F2, O8) on the targeted subset `test_update_commit test_progress.TestInstallerRunExemption test_installer.TestImportBlock`; files restored via seed.py | chosen as the defects that would commit user edits, lose the exemption, or break the block | detected |
| 2 | first Test command run: 12 failures, 10 errors beyond baseline import errors | all test defects: missing helper `setup_session` in TestInstallerRunExemption; P1 expected wrong TODO text; O3 matched heading with `#` prefix; fixture wrote owned `.harness/VERSION` (update preserves user-modified owned files → doctor sha mismatch); c2_ep2 answer consumed by the new 0.40.0 prompt; hard-coded 0.39.0 / migration lists / prompt counts in six other test files | correction batch 1 to test-implementer with these rules and observed outputs | run2: only baseline import errors remain |
| 1 | test-implementer ran `grep -A3` on harness/lib/progress.py and saw ~5 lines of `git_worktree_fingerprint` | locating a signature already given in the brief | signature only used; no test logic depends on those lines | accepted, noted |

# Version Log
## v4
- Contract-only: O5 gains coverage item E2 for FR9's equal-version subject, which no obligation covered (test-implementer report).

## v3
- Contract-only: Tests paths gain the test files that hard-code the harness version, migration lists, or the AGENTS.md block body (reported by test-implementer); no brief item changed.

## v2
- Contract-only: fixed exact output strings S1–S8 and the FR14 first-fingerprint point so both roles share one oracle; no brief item changed.

## v1
- Initial draft from the conversation's decisions (pre-dirty → warn and skip, auto-commit default on, update only, progress exemption) and the R1 pre-check.
- Baseline errors at base_commit (two runs): `test_isolation_telemetry` (ModuleNotFoundError: hypothesis) and `test_session_metrics` (ModuleNotFoundError: pytest) in both runs; `test_test_scan.TestVO8Quality.test_qr3_scan_leaves_target_tree_unchanged_and_runs_no_project_code` (FileNotFoundError on `.git/objects/maintenance.lock`) in the second run only. QR5 excludes these three.

# Retrospective
## 2026-11-10
| observation | evidence | how to re-check |
| --- | --- | --- |
| Claude Code loads a nested import `CLAUDE.md` → `@AGENTS.md` → `@.harness/instructions/harness-block.md` when the import line sits between `<!-- harness:begin -->` and `<!-- harness:end -->` | `claude -p` in a throwaway repo quoted a token from the nested file on 2026-11-10 | R1 procedure in Paths |

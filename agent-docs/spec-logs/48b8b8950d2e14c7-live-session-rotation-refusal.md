---
version: 3
run_id: 48b8b8950d2e14c7
status: complete
base_commit: 6bb07e09cabf4dc91f29ea40c4db4dfc7774816c
max_verifier_invocations: 2
commit: 6bb07e09cabf4dc91f29ea40c4db4dfc7774816c
---

# User Intent
| id | stakeholder | intention | observable goal |
| --- | --- | --- | --- |
| UI1 | harness user | A progress whose session already ended rotates to `progress-logs/` even while another claude process runs in the same checkout | Writing a new progress moves the ended session's progress although an unrelated live session marker exists |
| UI2 | harness user | A progress that belongs to a session still running in another process is never moved | Rotation is refused when a file to be moved belongs to a live session |
| UI3 | harness maintainer | Sessions started before the update keep today's protective behavior | A marker without a session id blocks rotation exactly as in 0.34.2 |
| UI4 | harness maintainer | `update` explains the change version by version | `installer/harness.py update` lists a 0.34.3 migration step |

# Scope
In scope: session id recorded in the `.harness/sessions/.running/<pid>` marker by the SessionStart hook; the live-session refusal in `rotation_refusal()` of the progress hook narrowed to files owned by live sessions; legacy-marker and unknown-owner fallbacks; refusal message; 0.34.3 migration entry and VERSION; Progress Rule sentence in the managed block.
Out of scope: the one-progress limit, the same-session refusal, the destination-exists refusal, `rotate()` in `harness/lib/progress.py`, post-merge, `/continue-on` target selection, pre-commit checks, PID-reuse handling of stale markers, the SessionStart "other sessions running" warning text.

# Paths
Implementation: harness/hooks/session_lock.py, harness/hooks/progress_hook.py, harness/instructions/harness-block.md, installer/harness.py, harness/VERSION
Tests: tests/test_progress.py, tests/test_installer.py, tests/test_comment_gate.py, tests/test_doc_records.py, tests/test_session_metrics.py, tests/test_telemetry.py, tests/test_workflow_markers.py
Test command: uv run --with pytest --with hypothesis python -m pytest tests -q -p no:cacheprovider
Review evidence: R1 — after `python3 installer/harness.py update .`, read the Progress Rule paragraph in `harness/instructions/harness-block.md` and the regenerated `AGENTS.md`; expected: both state that rotation does not move a progress whose session is still running in another process, and the remaining sentences of the paragraph are unchanged (checked with `git diff`).
Fuzzing: none — marker files are written only by the harness's own SessionStart hook in a git-ignored local directory; malformed content classes are enumerated deterministically in VO3.
Mutation tool: none — mutmut and cosmic-ray are not installed; 8–10 hand mutations supply mutation evidence.

# Signatures
session_lock.on_session_start(payload: dict) -> int  # writes RUNNING_DIR/<ppid> as JSON object {"session_id": <str>, "source": <str>}; "session_id" omitted when the payload has none
session_lock.marker_session(marker: Path) -> str | None  # non-empty string session_id from a JSON-object marker, else None (legacy / unreadable)
progress_hook.other_live_sessions() -> list[tuple[str, str | None]]  # (pid name, session id or None) for live markers other than own
progress_hook.rotation_refusal(path: Path, session_id: str | None, own_session: str | None) -> str | None

# Functional Requirements
| id | requirement | priority | source |
| --- | --- | --- | --- |
| FR1 | SessionStart writes the own marker (`RUNNING_DIR/<os.getppid()>`) as a JSON object holding `session_id` (the payload's non-empty string `session_id`) and `source` (payload `source`, default `""`), replacing any previous content of that marker | must | user approval of understanding round |
| FR2 | When writing a progress would rotate other files and a live other marker's session id equals the `session:` of any file to be moved, the hook refuses: exit 2, stderr names the written path, the blocking file's path, its session id, and the marker pid, and tells to end that session or use a separate git worktree; no file is moved or changed | must | UI2 |
| FR3 | When every live other marker carries a session id and none equals the `session:` of a file to be moved, rotation proceeds as it does with no other live marker | must | UI1 |
| FR4 | When any live other marker has no session id (legacy content, unparseable, non-object JSON, missing/empty/non-string `session_id`, unreadable), the refusal is the 0.34.2 live-session refusal (stderr contains "parallel"); nothing moved | must | UI3 |
| FR5 | When a file to be moved has no `session:` value (or invalid frontmatter) and at least one live other marker exists, rotation is refused; nothing moved | must | approved default (unknown owner keeps old behavior) |
| FR6 | Dead markers and the own marker (name equal to `os.getppid()` of the hook) never cause a refusal, whatever session id they hold | must | existing behavior |
| FR7 | Refusal precedence is unchanged: same-session refusal first, then live-session refusal, then destination-exists refusal | must | existing behavior |
| FR8 | `installer/harness.py` MIGRATIONS gains a 0.34.3 entry describing the narrowed refusal and the marker session id; `harness/VERSION` is `0.34.3` | must | AGENTS.md update rule |
| FR9 | The Progress Rule paragraph of `harness/instructions/harness-block.md` states that rotation does not move a progress whose session is still running in another process | should | approved default |

# Errors
- Marker file unreadable (directory, permission, non-UTF-8 bytes) — treated as a marker without session id (FR4) — hook exits 0 or 2 with no traceback; no progress file moved.
- Marker content not a JSON object with a non-empty string `session_id` — same as above.
- SessionStart payload without `session_id` — marker written without `session_id` — later treated per FR4.

# Cases
| id | level | input / state | expected result |
| --- | --- | --- | --- |
| C1 | normal | own marker; live other marker `{"session_id":"sessc"}`; old progress `session: sessa`; write new progress `sessb` | old moved to `progress-logs/`, new `before:` points to it |
| C2 | normal | live other marker `{"session_id":"sessa"}` (pid 1); old progress `session: sessa`; write new `sessb` | exit 2; stderr names new path, old path, `sessa`, pid `1`; old file bytes unchanged; logs empty |
| C3 | edge | live other marker with content `startup` | refused per FR4, stderr contains "parallel"; nothing moved |
| C4 | edge | live other marker with empty content | refused per FR4 |
| C5 | edge | old progress frontmatter without `session:`; live other marker `{"session_id":"sessc"}` | refused; nothing moved |
| C6 | boundary | two old progress files, `sessa` and `sessd`; live other marker `{"session_id":"sessd"}` | refused; neither moved |
| C7 | normal | SessionStart payload `{"session_id":"s1","source":"startup"}` | own marker JSON has `session_id` `s1` and `source` `startup` |
| C8 | edge | SessionStart payload without `session_id` | own marker exists, JSON object without a usable `session_id` |
| C9 | boundary | own marker already holds `{"session_id":"old"}`; SessionStart with `session_id` `new` | own marker holds `new` |
| C10 | error | live other marker contents: `{`, `[]`, `{"session_id": 5}`, `{"session_id": ""}`, a directory named as pid, bytes `\xff\xfe` | each: refused per FR4, no traceback in stderr, nothing moved |
| C11 | edge | dead marker `{"session_id":"sessa"}`; old progress `sessa` | old moved |
| C12 | edge | own marker `{"session_id":"sessa"}`; old progress `sessa`; write new `sessb` | old moved |
| C13 | normal | `update` from an installed 0.34.2 manifest | stdout lists `migration 0.34.3:` whose step text mentions the session id in the marker and the refusal for sessions still running; manifest version `0.34.3` |
| C15 | boundary | two live other markers, `{"session_id":"sessc"}` and `{"session_id":"sessa"}`; old progress `sessa` | refused, whichever marker name sorts first |
| C16 | edge | live `{"session_id":"sessc"}` plus live legacy marker | refused per FR4 |
| C17 | edge | old progress file whose first line is not `---`; live `{"session_id":"sessc"}` | refused per FR5 |
| C14 | none | performance boundaries — none: at most a few marker and progress files are read per hook call |

# Quality Applicability
| ISO/IEC 25010:2023 characteristic | applicable | rationale |
| --- | --- | --- |
| Functional suitability | yes | refusal decision is the feature |
| Performance efficiency | no | reads a handful of small local files per hook call |
| Compatibility | yes | markers written by 0.34.2 sessions coexist with new ones during the update window |
| Interaction capability | yes | the refusal message is what the agent acts on |
| Reliability | yes | a hook traceback would confuse the agent's turn; malformed markers must be tolerated |
| Security | no | marker directory is local and git-ignored; no trust boundary is crossed |
| Maintainability | yes | existing suite must keep passing; migration documentation |
| Flexibility | no | no new configuration or platform |
| Safety | no | no harm to people or environment; data integrity is covered under Functional suitability |

# Quality Requirements
| id | characteristic / subcharacteristic | target and context | measure method / inputs / unit | threshold and direction | evidence: automated, review, mutation | source |
| --- | --- | --- | --- | --- | --- | --- |
| QR1 | Compatibility / co-existence | legacy marker classes C3, C4 | count of classes producing the 0.34.2 refusal (exit 2, "parallel", nothing moved) / 2 | = 100% | automated VO1; mutation | UI3 |
| QR2 | Reliability / fault tolerance | malformed marker classes of C10 | count of classes with exit code in {0,2}, no `Traceback` in stderr, nothing moved / 6 | = 100% | automated VO3; mutation | Errors |
| QR3 | Interaction capability / self-descriptiveness | refusal message of C2 | count of required elements present (written path, blocking path, session id, pid, remedy) / 5 | = 100% | automated VO4 | FR2 |
| QR4 | Maintainability / modifiability | full suite after change | Test command exit status | exit 0 | automated VO7; review R1 | AGENTS.md |

# Verification Obligations
| id | parent requirement/Case ids | variant and target surface | test layer and selection policy | ISO/IEC/IEEE 29119-4 technique | coverage items | coverage target | observation and expected result | evidence procedure |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| VO1 | FR2-FR7, QR1, C1-C6, C11, C12 | PostToolUse Write of a progress through `.harness/hooks/progress_hook.py` subprocess | integration; one test per rule | decision table | R1 no other live marker → move; R2 live id ≠ old session → move; R3 live id = old session → refuse; R4 live legacy content → refuse; R5 live legacy empty → refuse; R6 old without session + live id → refuse; R7 two old files, one matching → refuse none moved; R8 dead marker matching → move; R9 own marker matching → move; R10 same-session file present + live matching marker → same-session refusal text; R11 two live id markers, one non-matching and one matching the old session, run with the matching id on each of the two marker names → refuse both times; R12 one live id marker not matching + one live legacy marker → refusal containing "parallel"; R13 old file with invalid frontmatter (no leading `---`) + live id marker → refuse | 100% | exit code, stderr, file locations and bytes | Test command |
| VO2 | FR1, C7-C9 | SessionStart through `.harness/hooks/session_lock.py` subprocess | integration | equivalence partitioning | P1 id+source present; P2 id absent; P3 source absent; P4 overwrite of own marker | 100% | marker JSON content | Test command |
| VO3 | Errors, QR2, C10 | PostToolUse progress write with each malformed live marker | integration | equivalence partitioning | M1 `{`; M2 `[]`; M3 non-string id; M4 empty id; M5 directory; M6 non-UTF-8 bytes | 100% | exit code 2, stderr contains "parallel", no `Traceback`, nothing moved | Test command |
| VO4 | FR2, QR3, C2 | stderr of the C2 refusal | integration | equivalence partitioning | E1 written path; E2 blocking path; E3 session id; E4 pid; E5 remedy (separate git worktree) | 100% | substrings present | Test command |
| VO5 | FR8, C13 | `installer/harness.py update` on a 0.34.2 install; `harness/VERSION` | integration | scenario | S1 migration list includes 0.34.3 last; S2 manifest version 0.34.3; S3 VERSION file 0.34.3; S4 the text printed between `migration 0.34.3:` and its `Apply migration` prompt contains "session id" and "still running" | 100% | stdout and files | Test command |
| VO6 | FR9, QR4 | managed block and AGENTS.md | review | experience-based (error guessing) | guessed defect: sentence missing or other Progress Rule sentences altered | none — experience-based | R1 | Review evidence R1 |
| VO7 | QR4 | whole suite | all | equivalence partitioning | T1 Test command run | 100% | exit 0 | Test command |

# Assumptions and Defaults
| id | decision | evidence and uncertainty | brief v<n> — approved / vetoed → <answer> / user answer |
| --- | --- | --- | --- |
| A1 | Marker content becomes a JSON object; anything else is legacy | no code reads marker content (grep of `.running` readers); marker dir is git-ignored | user answer (understanding round) |
| A2 | Legacy live marker keeps the 0.34.2 refusal | only sessions started before the update write legacy markers | user answer |
| A3 | Progress without `session:` is refused while any other live marker exists | hook-written progress always has `session:`; only hand-made files lack it | user answer |
| A4 | Same-process `/clear` or resume overwrites the marker's session id | SessionStart runs per session in the same claude process | user answer |
| A5 | Progress Rule sentence gains the live-session clause; "Parallel sessions on one checkout are not supported." stays | two live sessions that both write progress still refuse each other | user answer |
| A6 | Test command `python3 -m unittest discover -s tests`; mutation tool and fuzzing none | coverage, mutmut, cosmic-ray not installed | user answer |
| A9 | Test command runs pytest with hypothesis through uv; version-bump assertions in every test file are updated | v1 command could not import tests/test_session_metrics.py (pytest) and tests/test_isolation_telemetry.py (hypothesis); version 0.34.2 and migration-prompt counts are hard-coded in 5 more test files, as in commit 6bb07e0 | contract-only change (spec v2) |
| A7 | Existing installer tests that hard-code the migration list and version 0.34.2 are updated to 0.34.3 | tests/test_installer.py:530-650 | brief v1 — approved |
| A8 | Roles use agent-definition models: implementer sonnet, test-implementer sonnet, test-verifier sonnet | single-module change, small obligation map | brief v1 — approved |

# Traceability
| requirement id | Case ids | obligation ids | evidence procedure |
| --- | --- | --- | --- |
| FR1 | C7, C8, C9 | VO2 | Test command |
| FR2 | C2 | VO1, VO4 | Test command |
| FR3 | C1 | VO1 | Test command |
| FR4 | C3, C4, C10 | VO1, VO3 | Test command |
| FR5 | C5 | VO1 | Test command |
| FR6 | C11, C12 | VO1 | Test command |
| FR7 | C6 | VO1 | Test command |
| FR8 | C13 | VO5 | Test command |
| FR9 | — | VO6 | Review R1 |
| QR1 | C3, C4 | VO1 | Test command |
| QR2 | C10 | VO3 | Test command |
| QR3 | C2 | VO4 | Test command |
| QR4 | — | VO6, VO7 | Test command, Review R1 |

# Workflow Control
| item | value |
| --- | --- |
| correction batches used | 2 |
| verifier invocations | 2 |
| open finding ids | none (F1-F4 closed by verifier 2; F5 advisory: non-string payload session_id undeclared; advisory: substring/prefix id comparison would survive, ids in tests share no substring) |

Audit state (one entry per obligation; retain prior decisions in the execution ledger):
| obligation id | spec version | evidence references and revision | accepted / open / invalidated / pending | rationale and mutation outcome | dependencies and reopening evidence |
| --- | --- | --- | --- | --- | --- |
| VO1 | 3 | tests after correction batch 2; Test command 1012 passed | accepted | verifier 2: R1-R13 accepted; m1-m8 detected; m4 by R11 after batch 2 | reopens on change to progress_hook.py rotation_refusal, session_lock.py marker read/write, or the 0.34.3 migration |
| VO2 | 3 | test_progress.py rev after batch 1 | accepted | verifier 1; mutations m11 (VO2), m9/m2 (VO4) detected | tests unchanged by v3 |
| VO3 | 3 | tests after correction batch 2; Test command 1012 passed | accepted | verifier 2: M1-M6 (v3 observation) accepted; m5, m10 detected | reopens on change to progress_hook.py rotation_refusal, session_lock.py marker read/write, or the 0.34.3 migration |
| VO4 | 3 | test_progress.py rev after batch 1 | accepted | verifier 1; mutations m11 (VO2), m9/m2 (VO4) detected | tests unchanged by v3 |
| VO5 | 3 | tests after correction batch 2; Test command 1012 passed | accepted | verifier 2: S1-S4 accepted; m12 (changed probe) detected by S4 | reopens on change to progress_hook.py rotation_refusal, session_lock.py marker read/write, or the 0.34.3 migration |
| VO6 | 3 | R1 diff / Test command run | accepted | verifier 1 | VO7 reopens on any code or test change |
| VO7 | 3 | R1 diff / Test command run | accepted | verifier 1 | VO7 reopens on any code or test change |

Execution ledger (append attempts; preserve failed approaches):
| attempt | finding / failure signature | cause hypothesis | changed approach / new evidence | result / disposition |
| --- | --- | --- | --- | --- |
| 1 | v1 Test command: 9 failures, 2 import errors — `EOFError: EOF when reading a line` in update tests of test_comment_gate, test_doc_records, test_installer (O9 q6); `'0.34.3' != '0.34.2'` in test_telemetry, test_workflow_markers; `No module named 'hypothesis'/'pytest'` | version bump adds one migration prompt and a new version string that other test files hard-code; unittest runner lacks pytest/hypothesis | spec v2: widen Tests paths, switch Test command to uv+pytest+hypothesis; test-implementer correction batch | v2 Test command: 1008 passed, 2001 subtests passed (286 s) |
| 2 | verifier 1: F1 (blocking) migration text unchecked; F2/F3/F4 advisories; hand mutation m4 (check only first live marker) survived the targeted run, m1-m3, m5-m11 detected | FR2/FR3 'any/every' over several live markers, FR5 invalid frontmatter, FR8 text, and the FR4 message for malformed markers lack coverage items | spec v3 adds VO1 R11-R13, VO3 'parallel' observation, VO5 S4; test-implementer batch 2 | Test command 1012 passed, 2005 subtests passed (279 s); m4 now detected by R11 (arrangement 'matching on child pid'); m5, m7, m10 re-run detected (VO3 M-tests now also fail under m5/m10; m7 by R6 and R13) |
| 3 | hand mutation m12 (first migration step line made generic) passed S4 | inconclusive: remaining step lines still contained "session id" and "still running", so the probe did not violate the declared observation | changed probe: whole 0.34.3 step text replaced by "marker format changed" | S4 failed as intended; restored |

# Version Log
## v1
- Initial draft from the approved understanding round.
## v2
- Tests paths add the five other test files that hard-code the harness version or migration prompt count; Test command switches to `uv run --with pytest --with hypothesis python -m pytest tests -q -p no:cacheprovider` because the v1 command failed to import test_session_metrics.py and test_isolation_telemetry.py (execution ledger attempt 1). Contract-only.

## v3
- [verifier-1] VO1 gains R11-R13, VO3 observation requires the FR4 "parallel" refusal, VO5 gains S4 for the FR8 migration text, Cases C15-C17 added; forced by verifier finding F1 and surviving hand mutation m4 (execution ledger attempt 2). F5 (non-string payload session_id) stays advisory: undeclared behavior. Contract-only.

# Retrospective
## 2026-11-05
| observation | evidence | how to re-check |
| --- | --- | --- |
| Bumping the harness version breaks hard-coded version strings and migration-prompt `y` counts in five test files besides tests/test_installer.py (test_comment_gate, test_doc_records, test_session_metrics, test_telemetry, test_workflow_markers), and in test_installer inputs built in a variable (O9 q6) that a pattern sweep misses | execution ledger attempt 1 failure list; tests/ changes in commit 6bb07e0 | `grep -rn '"0\.34\.3"' tests/` and `grep -rn 'input=' tests/ \| grep -c y` before a version bump |

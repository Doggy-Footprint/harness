---
version: 1
run_id: 43566c0a9bdc1f1f
status: complete
base_commit: 833c5133ea2e89b40fa1772b1b3398025257ab3e
max_verifier_invocations: 2
handoff: none
---

# User Intent
| id | stakeholder | intention | observable goal |
| --- | --- | --- | --- |
| I1 | installer user | dry-run exposes ignored harness paths as a failure | `install/update --dry-run` with ignored guarded paths prints warnings, planned exception lines and the full plan, then exits 1 without prompting or writing |
| I2 | installer user | `.gitignore` gets only the exceptions Git needs | parent-directory exceptions appear only for parent directories Git reports as ignored |

# Scope
In scope: dry-run outcome when guarded paths are ignored (install, update/upgrade); parent-directory exception selection; version 0.15.1 with migration announcement.
Out of scope: README changes (user decision); non-dry-run consent, rollback and recheck behavior from run 4dcc865a307f4e1d (unchanged); doctor; `.git/info/exclude`, global or nested ignore file edits.
Base note: work tree at base_commit already carries the uncommitted 0.15.0 change archived in `agent-docs/spec-logs/4dcc865a307f4e1d-gitignore-exception-prompt.md`; this run builds on it.

# Paths
Implementation: installer/harness.py, harness/VERSION
Tests: tests/test_installer.py, tests/test_telemetry.py, tests/test_workflow_markers.py
Test command: python3 -m unittest discover -s tests
Review evidence: `git diff --check`; diff review of exception-line selection and dry-run exit path (VO4).

# Signatures
`cmd_install(target, dry_run, no_ci) -> int`; `cmd_update(target, dry_run, no_ci) -> int`.
`planned_gitignore_exceptions(paths, ignored_directories, existing) -> list[str]` (internal; tests observe through CLI output and `.gitignore` content).
Dry-run output line format unchanged: `planned .gitignore exception: <line>`.
Dry-run conflict text: `ignored harness paths: .gitignore exceptions require consent (dry-run)`.

# Functional Requirements
| id | requirement | priority | source |
| --- | --- | --- | --- |
| F1 | When guarded paths are ignored, `install --dry-run` and `update --dry-run` print each ignore warning and every planned exception line, continue to print the full remaining plan (update: migration plan; both: file write/merge plan), add the dry-run conflict text to the `conflict` report section, and exit 1. No prompt, no target writes. The previous `info` line "execution requires consent to update .gitignore" is removed. | must | user |
| F2 | When no guarded path is ignored (including when prior exceptions already clear them), dry-run behavior and exit 0 are unchanged. | must | existing behavior |
| F3 | Planned exceptions include `!/<parent>/` and `/<parent>/*` for a parent directory of an ignored guarded path only when the initial Git scan reports that parent directory as ignored; non-ignored parents receive no line. Exact path exceptions, literal escaping, de-duplication against existing lines, and recheck/rollback stay as in 0.15.0. | must | user |
| F4 | Version becomes 0.15.1 with a 0.15.1 migration announcement in `MIGRATIONS`; updates from 0.15.0 and 0.14.0 announce and confirm each version step in order and record 0.15.1. | must | user, AGENTS.md |

# Errors
Dry-run with ignored guarded paths — `conflict` section contains the dry-run conflict text, exit 1 — target bytes unchanged, no prompt.
Dry-run with Git check failure or pre-existing conflict — unchanged 0.15.0 behavior (conflict, exit 1, no writes).
Consenting non-dry-run where needed-parent-only exceptions do not clear Git — unchanged 0.15.0 rollback (conflict, exit 1, original `.gitignore` bytes).

# Cases
| id | level | input / state | expected result |
| --- | --- | --- | --- |
| C1 | error | fresh repo, `bin/` ignored, `install --dry-run` | warnings, planned lines, write plan printed; conflict text; exit 1; no prompt; snapshot unchanged |
| C2 | error | installed 0.15.0 repo, `bin/` ignored, `update --dry-run` | warnings, planned lines, migration 0.15.1 plan and file plan printed; conflict text; exit 1; no prompt; snapshot unchanged |
| C3 | boundary | no ignored guarded paths, install/update `--dry-run` | exit 0; no warning, no planned exception line, no dry-run conflict |
| C4 | boundary | exceptions from a prior consenting run already present, `update --dry-run` | exit 0; no planned exception line |
| C5 | normal | `bin/` ignored only (`.harness/` itself not ignored), consenting install | `.gitignore` has `!/.harness/bin/`, `/.harness/bin/*` and file lines but no `!/.harness/` or `/.harness/*`; exit 0; guarded paths not ignored |
| C6 | edge | `.harness/` ignored in root `.gitignore`, consenting install | `!/.harness/`, `/.harness/*` plus each ignored nested guarded parent; exit 0; guarded paths not ignored; unrelated file under `.harness/` remains ignored |
| C7 | edge | `.claude/` ignored via `.git/info/exclude`, no root `.gitignore`, consenting install | root `.gitignore` created with `!/.claude/`, `/.claude/*` and needed nested lines only; no parent line for other non-ignored directories; exit 0 |
| C8 | normal | update from 0.15.0, and from 0.14.0 | each version migration announced and confirmed in order; manifest 0.15.1 |

# Quality Applicability
| ISO/IEC 25010:2023 characteristic | applicable | rationale |
| --- | --- | --- |
| Functional suitability | yes | dry-run outcome and exception set must match Git |
| Performance efficiency | no | Git call pattern unchanged; prior 100-path and two-call tests stay in the suite |
| Compatibility | yes | parent ignore may come from root or `.git/info/exclude` |
| Interaction capability | yes | dry-run exit code and output are the CLI contract |
| Reliability | no | rollback logic unchanged; existing rollback tests stay in the suite |
| Security | yes | negations must not un-ignore directories Git did not ignore |
| Maintainability | yes | version-by-version migration rule |
| Flexibility | no | no customization surface |
| Safety | no | no physical or human safety consequence |

# Quality Requirements
| id | characteristic / subcharacteristic | target and context | measure method / inputs / unit | threshold and direction | evidence: automated, review, mutation | source |
| --- | --- | --- | --- | --- | --- | --- |
| Q1 | Functional suitability / correctness | consenting install under C5–C7 | Git `check-ignore` on all guarded paths after exit, count of ignored | 0 ignored and exit 0, lower | automated | user |
| Q2 | Compatibility / interoperability | parent ignored via root `.gitignore` and via `.git/info/exclude` | end-to-end outcome per source, count | 2/2 expected, higher | automated | user |
| Q3 | Interaction capability / user control | dry-run states C1–C4 | exit code, prompt count, output lines, byte snapshot; count of matching states | 4/4, higher | automated | user |
| Q4 | Security / integrity | C5 non-ignored `.harness/` parent; C6 unrelated file under ignored parent | count of `!/<parent>/` lines for parents not reported ignored; unrelated file ignored state | 0 lines, lower; unrelated file ignored, 100% | automated + review | user |
| Q5 | Maintainability / modularity | update from 0.15.0 and 0.14.0 | announcements in order and final manifest version, count | 2/2 paths correct, higher | automated | AGENTS.md |

# Verification Obligations
| id | parent requirement/Case ids | variant and target surface | test layer and selection policy | ISO/IEC/IEEE 29119-4 technique | coverage items | coverage target | observation and expected result | evidence procedure |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| VO1 | F1,F2,Q3 / C1,C2,C3,C4 | CLI `install`/`update --dry-run` | end-to-end; every coverage item | decision table | install-ignored, update-ignored, install-clear, update-clear, prior-exceptions-clear | 5/5 | ignored rules: exit 1, conflict text, warnings, planned lines, plan output, no prompt, unchanged snapshot, no info consent line; clear rules: exit 0, none of those lines | Test command |
| VO2 | F3,Q1,Q2,Q4 / C5,C6,C7 | consenting CLI install; resulting `.gitignore` and Git | end-to-end; every coverage item | classification tree | parent-not-ignored (`bin/`), parent-ignored root (`.harness/`), parent-ignored info/exclude (`.claude/`), unrelated-file-under-ignored-parent | 4/4 | exact parent lines match Git-reported ignored parents only; guarded paths not ignored; unrelated file still ignored; exit 0 | Test command |
| VO3 | F4,Q5 / C8 | CLI `update` | end-to-end; every coverage item | state transition | 0.15.0→0.15.1, 0.14.0→0.15.0→0.15.1, manifest recorded | 3/3 | ordered announcements and confirmations; manifest version 0.15.1 | Test command |
| VO4 | F1,F3,Q4 | installer diff | review | error guessing | parent line emitted for non-ignored parent; dry-run returns 0 after ignore plan; prompt reachable in dry-run | none — experience-based | none of the guessed defects present | `git diff --check` and diff review recorded in ledger |

# Assumptions and Defaults
| id | decision | evidence and uncertainty | user approval or explicit delegation |
| --- | --- | --- | --- |
| A1 | Dry-run shows full plan then exits 1 | user answer | approved |
| A2 | Version 0.15.1 with own migration announcement | user answer | approved |
| A3 | README unchanged | user answer | approved |
| A4 | "Needed parent" = parent the initial `git check-ignore` reports as ignored | Git reports descendants of an ignored directory as ignored (checked in scratch repo) | approved (whole-spec approval) |
| A5 | Dry-run conflict wording as in Signatures | main proposal | approved (whole-spec approval) |

# Traceability
| requirement id | Case ids | obligation ids | evidence procedure |
| --- | --- | --- | --- |
| F1,F2,Q3 | C1,C2,C3,C4 | VO1,VO4 | Test command, review |
| F3,Q1,Q2,Q4 | C5,C6,C7 | VO2,VO4 | Test command, review |
| F4,Q5 | C8 | VO3 | Test command |

# Workflow Control
| item | value |
| --- | --- |
| correction batches used | 0 |
| verifier invocations | 1 |
| open finding ids | none |

Audit state (one entry per obligation; retain prior decisions in the execution ledger):
| obligation id | spec version | evidence references and revision | accepted / open / invalidated / pending | rationale and mutation outcome | dependencies and reopening evidence |
| --- | --- | --- | --- | --- | --- |
| VO1 | 1 | test_r2vo1_* (5) + updated test_vo3/test_c9_ep4/ep5; suite 204 OK | accepted | verifier 1 accepted; mutations per ledger detected by intended tests | no changed dependency |
| VO2 | 1 | test_r2vo2_* (3, items a-d); suite 204 OK | accepted | verifier 1 accepted; mutations per ledger detected by intended tests | no changed dependency |
| VO3 | 1 | test_r2vo3_* (2) + updated test_vo6/test_vo1_update; suite 204 OK | accepted | verifier 1 accepted; mutations per ledger detected by intended tests | no changed dependency |
| VO4 | 1 | main diff review in ledger; git diff --check 0 | accepted | verifier 1 accepted; mutations per ledger detected by intended tests | no changed dependency |

Execution ledger (append attempts; preserve failed approaches):
| attempt | finding / failure signature | cause hypothesis | changed approach / new evidence | result / disposition |
| --- | --- | --- | --- | --- |
| 1 | test-implementer: `python3 -m unittest discover -s tests` did not finish in 600s | hypothesis: run_installer(input=None) subprocess inherits an open stdin and blocks on a prompt while implementation was incomplete (concurrent run) | main reran Test command after both roles finished: 204 OK in ~55s with and without stdin closed | no defect in final state; same hang reproduced under mutation M1 with open stdin, so mutation runs use `</dev/null` |
| VO4 review | installer diff | inspect parent selection, dry-run exit path, prompt reachability | parents skipped unless in ignored_directories; both commands return 1 when dry_run and ignored; dry-run returns before input() and run_migrations returns before before_apply; git diff --check 0 | accepted by verifier 1 |
| M1 | remove ignored_directories filter (all parents get `!/p/` and `/p/*`) | over-broad negation | seed backup, inject, Test command, restore | 13 failures incl. test_r2vo2_parent_not_ignored_gets_no_parent_lines; restored |
| M1' | restore 0.15.0 behavior (unconditional `!/p/`) | exact original defect | same | 5 failures incl. test_r2vo2_parent_not_ignored_gets_no_parent_lines, r2vo1 ignored rows; restored |
| M2 | dry-run returns 0 with ignored paths | F1 regression | same | 6 failures incl. test_r2vo1_*_ignored_*; restored |
| M3 | drop 0.15.1 MIGRATIONS entry | F4 regression | same | 6 failures incl. test_r2vo3_*; restored |
| dogfood | `python3 installer/harness.py update .` | — | manifest 0.15.1 | rc 0 |
| verifier 1 | VO1–VO4 accepted, no blocking finding | — | advisory A1: update dry-run file plan asserted only via manifest line; A2: update-ignored dry-run seeded only from 0.15.0 | advisory, not a requirement gap; left open by choice |

# Version Log
## v1
- Initial draft from review of run 4dcc865a307f4e1d: dry-run exit 0 with ignored paths and unconditional parent exceptions; user chose 0.15.1, full-plan dry-run failure, no README change.

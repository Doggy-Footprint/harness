---
version: 2
run_id: 4dcc865a307f4e1d
status: complete
base_commit: 833c5133ea2e89b40fa1772b1b3398025257ab3e
max_verifier_invocations: 2
handoff: none
---

# User Intent
| id | stakeholder | intention | observable goal |
| --- | --- | --- | --- |
| I1 | installer user | ignored harness files can be included safely | install/update warns, asks, adds targeted `.gitignore` exceptions on consent, then succeeds only if Git confirms the files are included |

# Scope
In scope: install/update/upgrade prompts, target root `.gitignore` exceptions, dry-run preview, doctor read-only checks, version migration and usage text.
Out of scope: editing `.git/info/exclude`, global or nested ignore files; forced Git add; resolving pre-existing non-ignore conflicts.

# Paths
Implementation: installer/harness.py, harness/VERSION, README.md
Tests: tests/test_installer.py, tests/test_telemetry.py, tests/test_workflow_markers.py
Test command: python3 -m unittest discover -s tests
Review evidence: `git diff --check`; inspect exception lines for path specificity and rollback behavior.

# Signatures
`find_ignored_paths(target, relpaths) -> list[str]` preserves current reporting behavior.
`cmd_install(target, dry_run, no_ci) -> int`; `cmd_update(target, dry_run, no_ci) -> int`; `cmd_doctor(target) -> int`.
CLI question: `Add .gitignore exceptions for these harness paths and continue? [y/N] `.

# Functional Requirements
| id | requirement | priority | source |
| --- | --- | --- | --- |
| F1 | When guarded harness paths are ignored, print each current ignore reason and ask once before install/update writes; affirmative `y` adds exact root-anchored path exceptions plus needed parent-directory exceptions to target root `.gitignore`. | must | user |
| F2 | Recheck the whole guarded set after writing exceptions; continue only if none remains ignored. If recheck fails or paths remain ignored, restore original `.gitignore` bytes (or remove newly created file), report conflict, and stop before other writes. | must | user |
| F3 | Decline, EOF, and non-interactive input leave target unchanged and return conflict/exit 1. | must | user |
| F4 | `--dry-run` prints warning and planned exception lines without prompting or writing, and reports whether actual execution would require consent; no success claim while ignores remain. | must | dry-run contract |
| F5 | Existing non-ignore conflicts and Git check failures stop without prompting or writing. Doctor remains read-only and reports ignored paths. | must | existing safety behavior |
| F6 | Exception lines are idempotent, preserve existing `.gitignore` bytes/line endings up to appended content, and cover spaces/non-ASCII/literal Git pattern characters. No blanket `!**` rule. | must | targeted exception intent |
| F7 | Bump to 0.15.0 and add a 0.15.0 version-specific migration announcement; update from older versions preserves version-by-version confirmation. | must | project instruction |

# Errors
Decline/EOF: ignore conflict, exit 1, no target writes. Git check failure: conflict, exit 1, no target writes. Recheck still ignored: conflict, exit 1, `.gitignore` restored, no install/update writes. Pre-existing owned/settings conflict: original conflict, no prompt or writes.

# Cases
| id | level | input / state | expected result |
| --- | --- | --- | --- |
| C1 | normal | fresh repo, `bin/`, answer `y` | warning and one prompt; precise exceptions; install and doctor succeed |
| C2 | normal | installed repo, `bin/`, answer `y` | exceptions added, then migrations/update complete; manifest current |
| C3 | boundary | answer `n` or EOF; existing `.gitignore` | exit 1; byte-for-byte snapshot unchanged |
| C4 | boundary | no `.gitignore`, ignore from `.git/info/exclude` or global excludes | root `.gitignore` created only on consent; success if recheck clears ignores |
| C5 | edge | nested `.gitignore` still overrides root exception | restore root `.gitignore`; exit 1; no other writes |
| C6 | edge | direct path-helper inputs with spaces, non-ASCII, Git glob metacharacters | only exact paths exempted; unrelated ignored paths remain ignored |
| C7 | normal | `--dry-run` with ignored paths | planned lines reported; no prompt and no writes |
| C8 | normal | doctor with ignored paths | original conflict reporting; no writes |
| C9 | error | Git check failure or pre-existing file conflict | no prompt and no writes |
| C10 | boundary | existing exceptions or repeated update | no duplicate lines; succeeds without prompt if no paths ignored |
| C11 | normal | update from 0.14.0 | 0.15.0 migration announced and confirmed; manifest becomes 0.15.0 |
| C12 | none | no further case level | all required levels represented |

# Quality Applicability
| ISO/IEC 25010:2023 characteristic | applicable | rationale |
| --- | --- | --- |
| Functional suitability | yes | consent and Git result must match |
| Performance efficiency | yes | many managed paths must remain practical |
| Compatibility | yes | Git ignore sources and filenames vary |
| Interaction capability | yes | warning, consent, dry-run are CLI behavior |
| Reliability | yes | failed remediation must roll back |
| Security | yes | generated ignore patterns must not exempt unrelated files |
| Maintainability | yes | versioned migration and shared flow |
| Flexibility | no | no customization surface requested |
| Safety | no | no physical or human safety consequence |

# Quality Requirements
| id | characteristic / subcharacteristic | target and context | measure method / inputs / unit | threshold and direction | evidence: automated, review, mutation | source |
| --- | --- | --- | --- | --- | --- | --- |
| Q1 | Functional suitability / correctness | ignored guarded set, consent `y` | end-to-end Git `check-ignore` and installer exit | 100% guarded paths unignored and exit 0, higher | automated | user |
| Q2 | Performance efficiency / time behaviour | 100 synthetic ignored paths through the ignore-check helper, plus actual install | instrument check-ignore process calls | at most 1 call per helper scan and at most 2 per consenting install, lower | automated | existing batch behavior |
| Q3 | Compatibility / interoperability | repo, info/exclude, global and nested rules | end-to-end outcomes by source, count | 4/4 expected outcomes, higher | automated | user |
| Q4 | Interaction capability / user control | consent states yes/no/EOF/dry-run | CLI capture and filesystem snapshot, count | 4/4 expected outcomes, higher | automated | user |
| Q5 | Reliability / recoverability | failed recheck | compare before/after snapshot, byte differences | 0 unintended differences, lower | automated | user |
| Q6 | Security / integrity | filenames with Git pattern characters | check unrelated sibling still ignored, count | 100% selected siblings ignored, higher | automated + review | targeted exceptions |
| Q7 | Maintainability / modularity | update from 0.14.0 | migration announcement and final manifest, count | both correct, higher | automated | AGENTS.md |

# Verification Obligations
| id | parent requirement/Case ids | variant and target surface | test layer and selection policy | ISO/IEC/IEEE 29119-4 technique | coverage items | coverage target | observation and expected result | evidence procedure |
| --- | --- | --- | --- | --- | --- | --- | --- |
| VO1 | F1,F2,Q1 / C1,C2 | install/update × ignored `bin/` | end-to-end | equivalence partitioning | install, update | 2/2 | prompt once; Git no longer ignores paths; command succeeds | Test command |
| VO2 | F2,F3,F5,Q4,Q5 / C3,C5,C9 | consent/recheck/error states | end-to-end | decision table | yes-clears, no, EOF, yes-remains, git-fails, preexisting-conflict | 6/6 | correct exit and before/after snapshot | Test command |
| VO3 | F4,F5 / C7,C8 | dry-run, doctor | end-to-end | equivalence partitioning | install dry-run, update dry-run, doctor | 3/3 | planned lines/read-only reporting, no writes | Test command |
| VO4 | F1,F2,F6,Q3,Q6 / C4,C5,C6 | ignore source and path syntax | end-to-end for root/info/global/nested; unit with real Git check-ignore for synthetic names | classification tree | root, info/exclude, global, nested, spaces, non-ASCII, glob metacharacters | 7/7 | success only where Git clears, literal narrow rules | Test command |
| VO5 | F6 / C10 | duplicate prevention | end-to-end | state transition | new→exceptions, existing→unchanged | 2/2 | no duplicate lines/prompt on already-clear state | Test command |
| VO6 | F7,Q7 / C11 | version from 0.14.0 | end-to-end | state transition | announce, confirm, record | 3/3 | migration/version evidence | Test command |
| VO7 | Q2 | 100 synthetic ignored paths plus consenting install | unit for helper; end-to-end for install | boundary value analysis (2-value) | helper scan, install initial scan, install confirmation scan | 3/3 | at most 1 call per helper scan and at most 2 per consenting install | Test command |
| VO8 | Q5,Q6 | rollback and targeted syntax | review | error guessing | restore exact bytes, avoid broad negation | none — experience-based | named review evidence | git diff --check and diff review |

# Assumptions and Defaults
| id | decision | evidence and uncertainty | user approval or explicit delegation |
| --- | --- | --- | --- |
| A1 | Prompt only on ignored guarded paths; consent writes target root `.gitignore`; failure restores it | user response | approved |
| A2 | Decline/EOF stops unchanged | user response | approved |
| A3 | Try root exceptions even for other ignore sources; rollback if ineffective | user response | approved |
| A4 | `--dry-run` previews without requesting consent; version becomes 0.15.0 | CLI dry-run contract, project version rule | whole-spec approval |
| A5 | Synthetic path syntax and volume use helper-level tests; real install/update retain end-to-end tests | fixed distributed payload paths cannot supply those variants without changing product files | user approved verification amendment |

# Traceability
| requirement id | Case ids | obligation ids | evidence procedure |
| --- | --- | --- | --- |
| F1,F2,Q1 | C1,C2,C4,C5 | VO1,VO2,VO4 | Test command |
| F3,F5,Q4,Q5 | C3,C5,C9 | VO2 | Test command |
| F4 | C7,C8 | VO3 | Test command |
| F6,Q3,Q6 | C4,C6,C10 | VO4,VO5,VO8 | Test command and review |
| F7,Q7 | C11 | VO6 | Test command |
| Q2 | C1 | VO7 | Test command |

# Workflow Control
| item | value |
| --- | --- |
| correction batches used | 1 |
| verifier invocations | 2 |
| open finding ids | none |

Audit state (one entry per obligation; retain prior decisions in the execution ledger):
| obligation id | spec version | evidence references and revision | accepted / open / invalidated / pending | rationale and mutation outcome | dependencies and reopening evidence |
| --- | --- | --- | --- | --- | --- |
| VO1 | 2 | TestGitignoreConsent install/update consent tests; final suite 194 OK | accepted | all manifest-owned and five managed paths checked with real Git after success | no changed dependency |
| VO2 | 2 | decline/EOF, nested ignore, second Git failure, preexisting obstruction, initial failure tests; final suite 194 OK | accepted | exact-byte rollback observed; mutations M1 and M2 detected by intended tests | no changed dependency |
| VO3 | 2 | dry-run exact planned-line and doctor snapshot tests; final suite 194 OK | accepted | no prompt/write in dry-run and doctor | no changed dependency |
| VO4 | 2 | root/info/global/nested and synthetic literal-name tests; final suite 194 OK | accepted | unrelated siblings remain ignored; mutation M3 detected | no changed dependency |
| VO5 | 2 | repeated update byte identity/no prompt test; final suite 194 OK | accepted | transition covered | no changed dependency |
| VO6 | 2 | 0.14.0→0.15.0 decline/confirm/manifest tests; final suite 194 OK | accepted | version chain covered | no changed dependency |
| VO7 | 2 | 100-path helper and consenting install call-count tests; final suite 194 OK | accepted | one check per helper scan, two per install; M1 detected | no changed dependency |
| VO8 | 2 | main diff review recorded below, git diff --check 0, narrowing/rollback tests | accepted | root anchored and literal exceptions, parent re-ignore, byte restoration inspected | no changed dependency |

Execution ledger (append attempts; preserve failed approaches):
| attempt | finding / failure signature | cause hypothesis | changed approach / new evidence | result / disposition |
| --- | --- | --- | --- | --- |
| 1 | full suite 23 failures: migration input EOF, old conflict/warning expectations, occupied `.harness` parent still prompts | test expectations outdated for 0.15.0 (verified); parent obstruction not detected before consent (verified) | test role updated expectations/input counts; implementer detects blocked parent paths before prompt | second suite: 193 OK |
| verifier 1 | test-verifier agent could not start audit: usage limit | external usage limit (verified from agent result) | retry with remaining verifier invocation after user resumed | audit not performed; count retained |
| verifier 2 | verifier found recheck Git failure, full guarded-set check, and exact dry-run-line evidence gaps | evidence gaps (verified) | test role added three targeted checks; main reran Test command | 194 OK; verifier accepted VO1–VO8, no open finding |
| F3 interpretation | "non-interactive" might include piped `y` | user said "입력할 수 없는 환경", meaning no available answer; `y` is consent | verifier used original user choice; no behavior amendment | accepted |
| M1 | bypass Git recheck after writing exceptions | would allow nested override to persist | seed backup; replace recheck result with empty; run Test command; restore | intended nested-override, second-check-failure, and two-call tests failed; restored |
| M2 | omit rollback after second Git failure | would retain changed `.gitignore` on exit 1 | seed backup; replace byte restoration with pass; run Test command; restore | intended nested-override and second-check-failure rollback tests failed; restored |
| M3 | generate broad `!**` exceptions | would exempt unrelated paths | seed backup; replace literal exception return with `!**`; run Test command; restore | intended narrow-exception and sibling tests failed; restored |
| final | dogfood update and closure checks | no new defect | `python3 installer/harness.py update .`, `doctor .`, `git diff --check`, full Test command, `seed.py status` | 0.15.0 installed; doctor 0; diff check 0; 194 OK; seed none |
| VO8 review | installer diff and Git behavior | inspect exact path generation, parent re-ignore, recheck rollback, pre-prompt conflict guard | root-anchored literal negations and child re-ignore rules seen; original bytes restored on failure; `git diff --check` 0; real Git/snapshot tests corroborate | accepted |

# Version Log
## v1
- Initial draft from the three user decisions and existing 0.14.0 behavior.
## v2
- User approved helper-level verification for synthetic filename and 100-path variants because installed payload names are fixed; end-to-end installation coverage remains.

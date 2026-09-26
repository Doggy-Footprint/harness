---
version: 1
run_id: 0549e917d670b7f8
status: complete
base_commit: f6aba189f5b908764aa1f15b09d41b4deda46226
max_verifier_invocations: 2
handoff: none
---

# User Intent
| id | stakeholder | intention | observable goal |
|---|---|---|---|
| I1 | harness maintainer | runs that follow the skill are not reported noncompliant | an `amend` with no pending verifier result is not a violation |
| I2 | harness maintainer | a failed lifecycle start no longer emits a start marker | skill telemetry example chains the start marker after lifecycle start with `&&` |
| I3 | harness maintainer | see how much the harness is used, not only whether runs comply | runs and sessions counted separately by 준수 / 비준수 / 부분 사용 / 무관 |

# Scope
In scope: compliance amend rule (C1); skill start-marker chaining with version 0.13.0 and its `update` migration (C2); run and session classification in `/api/summary` and the dashboard.
Out of scope: marker `session_id` (C3, left as is); skill-usage detection (issue Doggy-Footprint/harness#7); making `workflow_marker.py start` idempotent; changing cost/token merging.

# Paths
Implementation: analytics/compliance.py, analytics/app.py, analytics/transcripts.py, analytics/frontend/src/App.jsx, harness/skills/workflow-approach/SKILL.md, harness/VERSION, installer/harness.py
Tests: analytics/tests/, analytics/frontend/src/App.test.jsx, tests/
Test command: cd /Users/hwansu/tools/harness && uv run --with-requirements analytics/requirements.txt --with pytest --with pytest-cov python -m pytest analytics/tests tests -q --cov=analytics.compliance --cov=analytics.app --cov=analytics.transcripts --cov-branch --cov-fail-under=85 && cd analytics/frontend && npx vitest run
Review evidence: none — all obligations are automated.

# Signatures
evaluate(events: list[dict]) -> dict  # unchanged shape {completed, compliant, reasons}
cached_sessions(connection) -> list[dict]  # each session gains "child_sessions": int = number of Claude subagent transcript files merged into it
GET /api/summary adds "classification": {"runs": {"compliant": int, "noncompliant": int, "excluded": int}, "sessions": {"compliant": int, "noncompliant": int, "partial": int, "unrelated": int, "excluded": int}}; all existing fields keep their current values
SKILL.md Telemetry block start line: python3 .harness/bin/spec_lifecycle.py start --spec PATH --run-id ID && python3 .harness/bin/workflow_marker.py start --run-id ID --spec NAME --spec-version N
installer MIGRATIONS gains (0.13.0, "chain the workflow start marker after spec lifecycle start", migrate_start_marker_chaining) returning instruction strings only, no file changes

# Functional Requirements
| id | requirement | priority | source |
|---|---|---|---|
| F1 | `amend` is a violation only while a `verify` awaits its `verifier_result`; otherwise (including before `implement_test` and after a `pass`) it is accepted. The violation reason is renamed `amend_during_verify`. | must | user decision 1 |
| F2 | Run class: a run with no `workflow_end` is `excluded`; any ended run (complete, limit, handoff, aborted, or invalid status) is `compliant` when `evaluate` returns compliant true, else `noncompliant`. | must | user decisions C, 1 |
| F3 | A session linked to two or more distinct runs is `noncompliant`. A session linked to exactly one run takes that run's class. | must | user decision B |
| F4 | An unlinked session is `partial` when it used a harness sub-agent (`implementer`, `test-implementer`, `test-verifier`): in its own `subagents` counts, as its own Codex child `agent_type`, or through a Codex child session whose `parent_session_id` is this session. Otherwise it is `unrelated`. | must | user decisions, answer 2 |
| F5 | Sub-agent sessions count as sessions: each Claude subagent transcript merged into a parent adds one session of the parent's class; a Codex child session that is itself unlinked takes its parent session's class when the parent is present, else is classified by F4. | must | user decision B |
| F6 | `/api/summary.classification` reports F2 run counts and F3–F5 session counts; excluded items stay in all existing totals (runs, cost, tokens, non_workflow). | must | user decisions C, D |
| F7 | The dashboard shows one line of run counts by class and one line of session counts by class, including excluded. | must | user decision D |
| F8 | SKILL.md shows the start marker chained with `&&` after lifecycle start; VERSION is 0.13.0; `update` from 0.12.0 announces migration 0.13.0 with its label and steps. | must | user decision 2 |

# Errors
- Session with no transcript match for a linked key — not counted as a session (current `_linked_keys` behavior); no error.
- Claude subagent transcript whose parent transcript is missing — not counted (matches current merge, which drops it); no error.
- Unknown `agent_type` or subagent name — not a harness sub-agent; session is `unrelated` unless other F4 evidence exists.

# Cases
| id | level | input / state | expected result |
|---|---|---|---|
| C1 | normal | start > implement_test > amend > verify > pass(result) > end complete | compliant, no reasons |
| C2 | edge | start > amend > implement_test > verify > pass > end complete | compliant |
| C3 | error | start > implement_test > verify > amend > verifier_result pass > end complete | noncompliant, `amend_during_verify` |
| C4 | normal | handoff 2106fd306d5f shape: start > implement_test > amend > amend > verify > retry > amend > verify > pass > end complete | compliant |
| C5 | normal | ended runs with status complete, limit, handoff, aborted; one in_progress | four classified by compliance, one `excluded` |
| C6 | edge | one session linked to a compliant run and an in_progress run | session `noncompliant` |
| C7 | normal | unlinked Claude session with subagents {"test-verifier": 1} | `partial` |
| C8 | normal | unlinked Codex parent with a thread_spawn child agent_type `implementer` | parent and child both `partial` |
| C9 | normal | unlinked session with subagents {"Explore": 2} only | `unrelated` |
| C10 | normal | linked session with 2 merged Claude subagent transcripts, compliant run | 3 compliant sessions |
| C11 | boundary | no runs, no sessions | all classification counts 0 |
| C12 | normal | installed 0.12.0, `update` | output contains `migration 0.13.0:`; manifest version 0.13.0 |
| C13 | normal | SKILL.md installed copy | contains the `&&`-chained start line |

# Quality Applicability
| ISO/IEC 25010:2023 characteristic | applicable | rationale |
|---|---|---|
| Functional suitability | yes | classification correctness is the goal |
| Performance efficiency | no | O(runs + sessions) additions to an existing per-request pass |
| Compatibility | yes | existing summary fields and installer upgrade path must keep working |
| Interaction capability | no | two text lines in an existing view; covered by F7 |
| Reliability | no | no new failure modes beyond Errors |
| Security | no | local read-only analytics; no new input surface |
| Maintainability | yes | branch coverage of changed modules |
| Flexibility | no | no portability change |
| Safety | no | no physical or harm impact |

# Quality Requirements
| id | characteristic / subcharacteristic | target and context | measure method / inputs / unit | threshold and direction | evidence: automated, review, mutation | source |
|---|---|---|---|---|---|---|
| Q1 | Compatibility / co-existence | existing `/api/summary` fields and existing analytics tests | count of pre-existing summary keys with changed value on a fixture without new behavior | 0, lower is better | automated; mutation | user decision D |
| Q2 | Maintainability / testability | analytics.compliance, analytics.app, analytics.transcripts | coverage.py branch coverage, % | ≥ 85, higher is better | automated | prior spec VO8 |

# Verification Obligations
| id | parent requirement/Case ids | variant and target surface | test layer and selection policy | ISO/IEC/IEEE 29119-4 technique | coverage items | coverage target | observation and expected result | evidence procedure |
|---|---|---|---|---|---|---|---|---|
| VO1 | F1; C1–C4 | `evaluate` | unit | state transition | transitions of amend from states: before implement_test, after implement_test no result, awaiting result, after retry, after pass | 100% | reasons per Cases | Test command |
| VO2 | F2; C5 | `/api/summary.classification.runs` | integration | equivalence partitioning | status ∈ {complete, limit, handoff, aborted, none}; compliant ∈ {true, false} for ended | 100% | counts per class | Test command |
| VO3 | F3–F5; C6–C10 | `/api/summary.classification.sessions` | integration | decision table | rules: linked 0/1/≥2 runs; linked run class; harness sub-agent evidence own/Codex child/none; Claude merged children count; Codex child with present/absent parent | 100% of rules | counts per class | Test command |
| VO4 | F6, Q1; C11 | `/api/summary` | integration | boundary value analysis (2-value) | empty dataset; one excluded run with session (still in `runs`, cost, tokens) | 100% | existing fields unchanged; excluded counted in totals | Test command |
| VO5 | F7 | App.jsx rendered summary | unit (vitest) | equivalence partitioning | run line; session line | 100% | both lines show fixture counts | Test command |
| VO6 | F8; C12, C13 | installer update, installed SKILL.md | integration | scenario | update 0.12.0→0.13.0; SKILL.md content | 100% | migration announced, manifest 0.13.0, `&&` line present | Test command |
| VO7 | Q2 | changed analytics modules | coverage.py | branch | branches in Implementation py scope | 85% | `--cov-fail-under` passes | Test command |

# Assumptions and Defaults
| id | decision | evidence and uncertainty | user approval or explicit delegation |
|---|---|---|---|
| A1 | Codex child sessions of a linked parent already link through `_run_subagents`; F5 classifies them by parent class | `analytics/app.py:50-60` | approved 2026-09-26 |
| A2 | "excluded" is the only non-classified bucket and appears in the dashboard | user decision C, D | approved 2026-09-26 |

# Traceability
| requirement id | Case ids | obligation ids | evidence procedure |
|---|---|---|---|
| F1 | C1–C4 | VO1 | Test command |
| F2 | C5 | VO2 | Test command |
| F3–F5 | C6–C10 | VO3 | Test command |
| F6, Q1 | C11 | VO4 | Test command |
| F7 | — | VO5 | Test command |
| F8 | C12, C13 | VO6 | Test command |
| Q2 | — | VO7 | Test command |

# Workflow Control
| item | value |
|---|---|
| correction batches used | 2 |
| verifier invocations | 2 |
| open finding ids | none |

Audit state:
| obligation id | spec version | evidence references and revision | accepted / open / invalidated / pending | rationale and mutation outcome | dependencies and reopening evidence |
|---|---|---|---|---|---|
| VO1, VO2, VO3, VO5, VO6, VO7 | 1 | verifier 1, retained by verifier 2 | accepted | independent oracles, targets met | — |
| VO4 | 1 | verifier 2 | accepted (F-Q1 closed) | F6 part accepted; Q1 full-key diff added, M3b detected | test_classification_v4 helpers |

Execution ledger:
| attempt | finding / failure signature | cause hypothesis | changed approach / new evidence | result / disposition |
|---|---|---|---|---|
| 1 | R1 test defect: VO3 rules untested — session linked to one noncompliant run; Codex child inheriting a linked parent's class; Codex child with absent parent classified by own agent_type | test-implementer omitted three decision-table rules (verified by reading test list) | redispatch test-implementer with the three rules | 4 tests added; suite 243 passed |
| 2 | verifier 1 retry, F-Q1: Q1 evidence pins only a subset of pre-existing summary keys; unlisted key changes undetected | test evidence defect (verified from verifier report) | add automated full-key diff of /api/summary (minus classification) against base_commit analytics on a shared no-new-behavior fixture | Q1CoexistenceMeasurementTests added; 244 passed |
| 3 | mutations: M1 revert amend rule to require retry -> test_compliance_v4 C1/C2/C4 fail (detected); M2 >=2 runs boundary to >=3 -> test_c6 fails (detected); M3 handoff_runs counts aborted -> inconclusive (fixture has no aborted run); M3b handoff_runs counts limit -> test_q1 fails (detected) | strongest classes: F1 rule, F3 boundary, Q1 existing-field drift | changed probe for M3 | all restored |
| 4 | verifier 2 pass; advisories: test-implementer name case, direct child_sessions assertion, aborted run in Q1 fixture | — | — | advisory, not blocking |

# Version Log
## v1
- Initial draft from handoff agent-docs/handoff/09494007ed793b66-analytics-compliance-rules.md and user decisions.

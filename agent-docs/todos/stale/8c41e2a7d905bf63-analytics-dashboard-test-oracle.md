# Analytics dashboard test oracle

## Goal
"analytics-dashboard handoff 이어서 작업해. test-implement를 직접 수행해" followed by "여기까지 커밋하고 1. 구현에서 어디까지 완료 되었는지 2. 테스트는 어디까지 verifier에 의해 통과 되었는지 명시해서 handoff를 새로 써. analytics-dashboard handoff에서는 필요한 내용 추출해서 사용하고 stale하고."

## State
- Branch: `feat/harness-analytics-2`.
- Analytics implementation: not started. No `analytics/app.py`, importer, store, pricing, compliance, configuration, frontend application, dependency manifest, or built frontend exists.
- Analytics contract work: the approved FastAPI + React + SQLite design was expanded to contract v5. The session-scoped contract was deleted by cleanup, so its full text is preserved below.
- Analytics test implementation: complete for the v5 oracle in `analytics/tests/test_api.py`, `analytics/tests/test_compliance.py`, `analytics/tests/test_importer.py`, `analytics/tests/test_pricing.py`, and `analytics/frontend/src/App.test.jsx`.
- Analytics test execution: not run. The test-implementer isolation rule prohibited executing tests before reconciliation, the implementation symbols do not exist, and FastAPI/Uvicorn/PyYAML/frontend packages have not been bootstrapped.
- Analytics verifier status: no test-verifier has run, so none of V1-V9 has verifier approval. Python test files passed a compile-only load check; `git diff --check` passed.
- Analytics coverage: V1-V6 and V8-V9 have direct tests. V7 tests FastAPI API/static-SPA routing through `create_app`; actual `python3 -m analytics.app` process startup remains blocked because the contract has no controllable port/readiness boundary.
- Marker prerequisite implementation: explicit workflow markers and the F1-F6 test corrections are present. The restored harness suite passes 132 tests with `python3 -m unittest discover -s tests -p 'test_*.py'`; `python3 .harness/bin/seed.py status` reports `seed: none`.
- Marker verifier status: the final verifier accepted F1-F6. F7-F9 and F11-F12 remain open test gaps; F10 was rejected because the contract specifies one enum-valued end command rather than three status-specific command lines. An interrupted F7 seed was restored and produced no usable result.
- The worktree also contains the separate verification-loop instruction changes tracked by `agent-docs/handoff/286944a68391e237-verification-loop-improvements.md` and generated dogfood files; do not treat those as analytics implementation.

## Failed Attempts
| attempt | failure evidence | cause |
|---|---|---|
| Extra marker seed triage | Non-integer verifier `--round`, end without an active run, and generated commands missing `--run-id` all left the then-current suite green | verified: F2, F3, and F5 were escaping test defects; later tests detect all three seeds |
| Final marker verifier after F1-F6 | F7 collision lifecycle, F8 mismatched verifier identity, F9 malformed non-verifier commands, F11 migrated payload operability, and F12 non-start envelopes remain | verified: the final audit found these variants after F1-F6 passed |
| F7 seed | Execution was interrupted by the user and restored with `seed: none` | verified: no seed outcome can be claimed |
| Analytics production-command coverage | The factory can be tested, but the actual server process cannot be isolated reliably | verified: v5 defines no injectable bind port or readiness signal |

## Next Step
1. Commit-aware resume: read this handoff and use Contract Snapshot v5; recreate `agent-docs/contracts/analytics-dashboard.md` before contract-workflow dispatch.
2. Resolve the V7 signature gap with the user by defining a controllable port/readiness boundary for `python3 -m analytics.app`, then amend the contract.
3. Bootstrap the Python and frontend dependencies and implement only the analytics Implementation paths from the contract. Do not infer behavior from the tests.
4. Reconcile implementation and the existing independent test oracle, then run the exact amended Test command.
5. Dispatch a fresh test-verifier with the complete coverage map. Seed its strongest findings and complete the normal correction loop.
6. Keep marker F7-F9/F11-F12 as known gaps unless the user separately authorizes reopening marker verification.

## Open Questions
- What bind-port override and readiness observation should the production command expose for V7?
- Whether marker F7-F9 and F11-F12 should ever be corrected; they are not blockers for implementing analytics unless the user reopens that scope.

## Contract Snapshot
---
version: 5
---

# User Intent
| id | intention | goal to achieve |
|---|---|---|
| U1 | Import local harness telemetry incrementally into SQLite at request time | The dashboard reflects new JSONL events without a separate ingestion command |
| U2 | Show an aggregate summary and individual workflow-run detail | Users can assess harness usage, compliance, verifier effectiveness, handoff rate, and linked cost |
| U3 | Use transcript metadata from Claude and Codex without storing transcript content | Token usage and model cost are available without copying prompts or responses into analytics storage |
| U4 | Configure model prices in YAML | Costs use editable USD-per-million-token rates for input, output, cache read, 5-minute cache write, and 1-hour cache write |
| U5 | Serve the FastAPI API and React dashboard with one production command | The local dashboard is operable as one application outside the installable harness payload |

# Paths
Implementation: analytics/app.py, analytics/importer.py, analytics/store.py, analytics/pricing.py, analytics/compliance.py, analytics/config.yaml, analytics/frontend/package.json, analytics/frontend/src/App.jsx, analytics/frontend/src/main.jsx, analytics/frontend/src/styles.css, analytics/frontend/dist
Tests: analytics/tests/test_importer.py, analytics/tests/test_pricing.py, analytics/tests/test_compliance.py, analytics/tests/test_api.py, analytics/frontend/src/App.test.jsx
Test command: python3 -m unittest discover -s analytics/tests -p 'test_*.py' && npm --prefix analytics/frontend test -- --run

# Signatures
analytics.importer.import_pending(connection: sqlite3.Connection, telemetry_dir: pathlib.Path) -> None
analytics.importer.transcript_usage(path: pathlib.Path, client: str | None) -> dict[str, int | str | None]
analytics.pricing.load_prices(path: pathlib.Path) -> dict
analytics.pricing.calculate_cost(usage: dict, prices: dict) -> float | None
analytics.compliance.evaluate(events: list[dict]) -> dict
analytics.app.create_app(database_path: pathlib.Path, telemetry_dir: pathlib.Path, price_path: pathlib.Path, transcript_dirs: dict[str, pathlib.Path] | None = None, frontend_dir: pathlib.Path | None = None) -> fastapi.FastAPI
Normalized usage keys: model, input_tokens, output_tokens, cache_read_tokens, cache_write_5m_tokens, cache_write_1h_tokens
Price YAML: models.<model>.input, output, cache_read, cache_write_5m, cache_write_1h are USD per 1M tokens
Transcript discovery: recursively scan configured claude/codex transcript directories and associate metadata whose session id equals the telemetry session_id
GET /api/summary -> JSON object with runs, completed_runs, compliant_runs, handoff_runs, verifier_rounds, verifier_retries, seeds_run, seeds_detected, linked_cost_usd, and run_items containing run_id/contract/status/compliant
GET /api/runs/{run_id} -> JSON object with run_id, contract, contract_version, status, compliant, compliance_reasons, events, verifier_rounds, verifier_retries, seeds_run, seeds_detected, transcript_metadata, and linked_cost_usd
Production command: python3 -m analytics.app
analytics/frontend/src/App.jsx: default export App({ apiBase = "" })

# Errors
malformed or partially written telemetry/transcript input — request succeeds, valid records remain queryable, invalid record is not stored, and source progress does not advance past the invalid record
unknown model price — linked_cost_usd is null while usage metadata remains available
unknown workflow run id — GET /api/runs/{run_id} returns HTTP 404 without changing imported data

# Cases
| id | level | input / state | expected result |
|---|---|---|---|
| A1 | normal | telemetry has a completed run with start, implement_test, verify, verifier pass, and complete end | request-time import stores each event once; summary and detail report one compliant completed run |
| A2 | normal | linked Claude or Codex transcript metadata contains model token usage | detail exposes model and token totals but no transcript content; cost uses configured rates |
| A3 | normal | multiple completed runs include retry, seeds, and handoff | summary totals rounds, retries, seed detection, handoffs, and linked cost |
| A4 | normal | production server command starts the API serving the built React application | one command owns both API and dashboard routes |
| A5 | boundary | repeated request with unchanged files, followed by one appended event | unchanged records are not duplicated; only the appended record is imported |
| A6 | boundary | valid usage includes zero tokens or an unknown model | zero-token known model costs zero; unknown model cost is null |
| A7 | error | malformed JSONL line, partial trailing line, malformed transcript metadata, or missing telemetry directory | request remains successful, no invalid content is stored, and later retry can import a completed trailing record |
| A8 | error | detail requests an unknown run id | response is 404 and prior data is unchanged |
| A9 | edge | completed run has missing, duplicate, out-of-order, mismatched-identity, or post-end semantic transition | run is noncompliant with deterministic reasons; incomplete runs are not classified as compliant or noncompliant completed runs |
| A10 | edge | transcript contains prompt/response text beside metadata | database and API contain only transcript path/client/model/token metadata, never prompt/response content |
| A11 | edge | prices define all five token categories and usage exercises them together | each category is independently charged in USD per 1M tokens and the sum is returned |
| A12 | edge | React dashboard receives empty summary, populated summary, run selection, loading, and API error states | each state has a visible user-facing rendering and summary links to run detail |

# Verification Obligations
| id | parent intent/Case ids | rule and applicable targets/input classes | boundary/transition/combination | observation and expected result |
|---|---|---|---|---|
| V1 | U1,A1,A5,A7 | JSONL importer for every telemetry file | empty/missing directory, first import, unchanged repeat, append, malformed middle line, partial tail completed later | SQLite/API observations prove idempotence, incremental progress, and retry-safe failure isolation |
| V2 | U2,A1,A3 | summary aggregation across completed runs | pass, retry then pass, handoff, zero verifier/seed counts | exact aggregate fields equal independent fixture arithmetic |
| V3 | U2,A1,A8,A9 | run detail and compliance | required ordered path; missing, duplicate, out-of-order, mismatched identity, post-end; incomplete; unknown id | status/reasons/events are deterministic, incomplete is excluded from completed compliance denominator, unknown is 404 |
| V4 | U3,A2,A7,A10 | Claude and Codex transcript metadata adapters | each client, malformed/missing file, content mixed with usage | model/token fields are extracted; prompt/response content is absent from SQLite and serialized responses |
| V5 | U4,A2,A6,A11 | price loader and calculator | five categories individually and together, zero, fractional USD result, unknown model | exact independent Decimal-derived totals or null for unknown price |
| V6 | U1,U2,A1,A3,A5 | both API requests trigger import before querying | summary then detail and detail then summary with newly appended events | each route observes newly available valid events without a separate command |
| V7 | U5,A4 | production command and static application routing | API path, dashboard root, client-side run-detail path | one server command serves API JSON and built React assets/fallback |
| V8 | U5,A12 | React source behavior | empty/populated/loading/error and selected run | source-level frontend tests exercise visible states and summary-to-detail navigation |
| V9 | U1-U5,A1-A12 | persistence privacy boundary | all imported event/transcript fixtures containing sentinel content | sentinel prompt/response text is absent from database bytes and every API response |

# Version Log
## v5
- Added the React component export and injectable API base required for a public frontend test boundary. Evidence: v4 required executable React state tests but exposed no component signature.

## v4
- Defined the summary run-list and run-detail response keys required for independent HTTP and React navigation assertions. Evidence: v3 required summary-to-detail navigation and detailed observations without naming their serialized fields.

## v3
- Added controllable Claude/Codex transcript roots, session-id association, normalized usage keys, and the approved five-category YAML schema. Evidence: telemetry events identify sessions but do not retain transcript paths, and v2 did not define an observable association or price-key mapping.

## v2
- Added the API application factory required to isolate database, telemetry, pricing, and frontend boundaries in tests; separated React implementation and Vitest paths and included both suites in the Test command. Evidence: v1 exposed HTTP behavior without a controllable application signature and listed frontend verification without an executable frontend test path.

## v1
- Restored the confirmed FastAPI, React, SQLite, request-time import, metadata-only transcript, YAML pricing, single-command serving, and ordered-transition compliance decisions from the analytics-dashboard handoff; added the user-approved summary and run-detail API boundary.

## Coverage Map
| obligations | variants | observation | expected source | escaping defect | evidence |
|---|---|---|---|---|---|
| V1,V6 | missing/first/repeat/append/malformed/partial; both route orders | HTTP summary/detail and event count | contract fixture arithmetic | duplicate or skipped incremental rows | `ApiTests.test_v1_*`, `test_v1_v2_v6_*` |
| V2 | pass/retry/handoff/count totals | summary JSON | fixture arithmetic | wrong denominator or collapsed verifier result | `test_v1_v2_v6_first_and_repeated_import_then_append_are_incremental` |
| V3 | valid/incomplete/missing/duplicate/order/identity/post-end/404 | evaluator and detail HTTP | contract transition order | constant compliance result | `ComplianceTests.test_v3_*`, `test_v3_unknown_run_*` |
| V4,V9 | Claude/Codex/malformed/missing/content sentinel/unknown model | normalized metadata, response text, DB bytes | explicit transcript fixtures | prompt persistence or client-specific omission | `TranscriptUsageTests.test_v4_*`, `ApiTests.test_v4_*` |
| V5 | five categories/combined/zero/fraction/unknown/YAML | calculator return | independent Decimal arithmetic | ignored rate or invented unknown-model cost | `PricingTests.test_v5_*` |
| V7 | root/client route/API non-shadowing | TestClient content types/body | static sentinel and API contract | SPA fallback shadows API | `test_v7_factory_serves_dashboard_*`; process startup blocked |
| V8 | loading/empty/populated/navigation/error | accessible DOM and fetch calls | contract response fixtures | ignored UI state or broken detail navigation | `App.test.jsx` |

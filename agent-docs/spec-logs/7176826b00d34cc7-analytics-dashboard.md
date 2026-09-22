---
version: 2
run_id: 7176826b00d34cc7
status: complete
base_commit: f53201b98df4aa53c3d0763827d96b9421c578d5
max_correction_rounds: 2
handoff: agent-docs/handoff/5be48b0b11e837d4-analytics-dashboard-final-verification.md
---

# User Intent
| id | stakeholder | intention | observable goal |
|---|---|---|---|
| U1 | harness maintainer | Import current workflow telemetry incrementally into local SQLite | API requests expose newly appended `spec`-schema events without duplicates or a separate ingestion command |
| U2 | harness maintainer | Inspect aggregate and per-run workflow behavior | Summary and detail show status, compliance, verifier, seed, handoff, and cost information |
| U3 | harness maintainer | Link Claude and Codex usage without retaining conversation content | Every linked session/model exposes token metadata and cost while prompt/response text is absent from storage and responses |
| U4 | harness maintainer | Run the dashboard as one local application | One module command serves the API, readiness endpoint, React dashboard, and client routes |

# Scope
In scope: standalone `analytics/` FastAPI, SQLite, YAML pricing, transcript metadata adapters, React dashboard, dependency manifests, current `spec/spec_version` telemetry, and their automated evidence.
Out of scope: the installable `harness/` payload, unresolved marker findings, historical `contract/contract_version` telemetry compatibility, authentication, remote deployment, and response-latency targets.

# Paths
Implementation: analytics/__init__.py, analytics/app.py, analytics/importer.py, analytics/store.py, analytics/pricing.py, analytics/compliance.py, analytics/config.yaml, analytics/requirements.txt, analytics/frontend/package.json, analytics/frontend/package-lock.json, analytics/frontend/index.html, analytics/frontend/src/App.jsx, analytics/frontend/src/main.jsx, analytics/frontend/src/styles.css, analytics/frontend/dist
Tests: analytics/tests/test_importer.py, analytics/tests/test_pricing.py, analytics/tests/test_compliance.py, analytics/tests/test_api.py, analytics/tests/test_server.py, analytics/frontend/src/App.test.jsx
Test command: npm --prefix analytics/frontend run build && python3 -m unittest discover -s analytics/tests -p 'test_*.py' && npm --prefix analytics/frontend test -- --run && python3 -m unittest discover -s tests -p 'test_*.py'
Review evidence: none — all required behavior and quality targets have public automated observations

# Signatures
`analytics.importer.import_pending(connection: sqlite3.Connection, telemetry_dir: pathlib.Path) -> None`
`analytics.importer.transcript_usage(path: pathlib.Path, client: str | None) -> dict[str, int | str | None]`
`analytics.pricing.load_prices(path: pathlib.Path) -> dict`
`analytics.pricing.calculate_cost(usage: dict, prices: dict) -> float | None`
`analytics.compliance.evaluate(events: list[dict]) -> dict`
`analytics.app.create_app(database_path: pathlib.Path, telemetry_dir: pathlib.Path, price_path: pathlib.Path, transcript_dirs: dict[str, pathlib.Path] | None = None, frontend_dir: pathlib.Path | None = None) -> fastapi.FastAPI`
`GET /api/health -> {"status":"ok"}`
`GET /api/summary -> runs, completed_runs, compliant_runs, handoff_runs, verifier_rounds, verifier_retries, seeds_run, seeds_detected, linked_cost_usd, run_items[{run_id,spec,status,compliant}]`
`GET /api/runs/{run_id} -> run_id, spec, spec_version, status, compliant, compliance_reasons, events, verifier_rounds, verifier_retries, seeds_run, seeds_detected, transcript_metadata[{client,session_id,path,model,input_tokens,output_tokens,cache_read_tokens,cache_write_5m_tokens,cache_write_1h_tokens,linked_cost_usd}], linked_cost_usd`
`analytics/frontend/src/App.jsx: default export App({ apiBase = "" })`
Production command: `python3 -m analytics.app`.
Environment overrides: `ANALYTICS_HOST`, `ANALYTICS_PORT`, `ANALYTICS_DATABASE_PATH`, `ANALYTICS_TELEMETRY_DIR`, `ANALYTICS_PRICE_PATH`, `ANALYTICS_CLAUDE_TRANSCRIPT_DIR`, `ANALYTICS_CODEX_TRANSCRIPT_DIR`, `ANALYTICS_FRONTEND_DIR`.

# Functional Requirements
| id | requirement | priority | source |
|---|---|---|---|
| F1 | Import newline-complete, valid JSON telemetry incrementally using source path and byte position; unchanged requests and rewritten prefixes do not duplicate rows, and malformed/partial input does not advance beyond the invalid position | must | U1, approved plan |
| F2 | Persist and serialize only allowlisted workflow envelope/marker fields; use only `spec/spec_version`, and trigger import before both summary and detail queries | must | U1,U3, approved plan |
| F3 | Evaluate the current workflow state machine deterministically: one start first, identity consistency, initial implement_test before verify, each verifier result following verify, correction amend cycles, and no post-end events. `complete` requires the latest verifier result `pass`; `limit` requires the latest verifier result `limit`; `handoff` and `aborted` may terminate at any workflow point without a verifier result | must | U2, current workflow-approach skill |
| F4 | Include unterminated runs as `in_progress` with `compliant=null`, exclude them from completed/compliant denominators, and return 404 for unknown run IDs without mutation | must | U2, user decision |
| F5 | Recursively discover matching Claude/Codex transcripts by telemetry client and session ID, normalize each session/model usage entry, and never retain transcript content | must | U3, user decision |
| F6 | Load five USD-per-million-token rates, price every usage entry independently, sum known entry costs for run/summary totals, preserve unknown-model usage with entry cost null, and set a run/summary total null when it includes an unpriced entry | must | U3, approved plan |
| F7 | Serve health and JSON API routes before a built-SPA fallback for `/` and client-side routes; render loading, empty, populated, detail, and error states accessibly | must | U4, approved plan |
| F8 | The no-argument production command uses approved home defaults, accepts every named environment override, and fails non-zero with stderr for invalid configuration, uncreatable DB, invalid/missing price YAML, or absent frontend build; missing telemetry/transcript roots remain empty input | must | U4, user decision |
| F9 | Pin Python dependencies in requirements.txt and frontend dependencies in package-lock.json | must | user decision |

# Errors
Malformed or partial telemetry line — request succeeds, prior valid records remain queryable, invalid content is not stored, and source progress stops before that line.
Malformed or missing transcript input — request succeeds, that transcript contributes no usage, and telemetry data remains queryable.
Unknown model price — usage entry remains present with `linked_cost_usd: null`; containing run and summary cost are null without data mutation.
Unknown run ID — detail returns HTTP 404 and imported data is unchanged.
Invalid startup configuration, unavailable required price/build resource, or uncreatable database — process writes a concise diagnostic to stderr and exits non-zero before reporting ready.

# Cases
| id | level | input / state | expected result |
|---|---|---|---|
| C1 | normal | completed current-schema run plus matching Claude/Codex sessions | one compliant completed run, per-session usage array, and correct summed cost |
| C2 | normal | retry/amend/verify loop followed by pass/complete; handoff, limit, and aborted runs | deterministic status, compliance, verifier/seed counts, and aggregate totals |
| C3 | boundary | empty/missing input, unchanged repeat, appended event, rewritten prefix, zero tokens, unknown price, or in-progress run | no duplicate/lost event; zero costs zero; unknown cost null; in-progress excluded from completed denominator |
| C4 | error | malformed middle JSON, partial tail, malformed transcript, unknown run, or invalid startup resource | specified non-destructive signal and post-failure state from Errors |
| C5 | edge | missing/duplicate/out-of-order/mismatched/post-end transitions and prompt/response sentinels in event/transcript fixtures | run is deterministically noncompliant and no sentinel exists in DB bytes or API output |
| C6 | edge | dashboard loading, empty, populated, selected detail, API failure, root, and client route | visible accessible state and correct navigation/API/static routing |

# Quality Applicability
| ISO/IEC 25010:2023 characteristic | applicable | rationale |
|---|---|---|
| Functional suitability | yes | Aggregation, compliance, and cost accuracy are the product purpose |
| Performance efficiency | no | User explicitly selected no response-time or throughput threshold for v1 |
| Compatibility | yes | API, static routing, SQLite, and current telemetry schema must interoperate |
| Interaction capability | yes | The React UI must expose understandable loading, data, navigation, and failure states |
| Reliability | yes | Repeated and malformed incremental inputs must not duplicate or corrupt retained data |
| Security | yes | Local transcript content is sensitive and must never cross the metadata boundary |
| Maintainability | no | No independent quantitative maintainability target was requested for this standalone v1 |
| Flexibility | yes | Runtime locations and bind address must be replaceable through documented environment variables and factory inputs |
| Safety | no | The read-only local analytics application controls no safety-relevant process |

# Quality Requirements
| id | characteristic / subcharacteristic | target and context | measure method / inputs / unit | threshold and direction | evidence: automated, review, mutation | source |
|---|---|---|---|---|---|---|
| Q1 | Functional suitability / correctness | All declared outputs for representative current-schema workflows | Exact independent fixture arithmetic and state-machine expectations; failing assertions count | 0 mismatches | automated plus mutation | U1-U4 |
| Q2 | Compatibility / interoperability | API routes, SPA fallback, SQLite persistence, and current `spec` events work together | Production-process and TestClient observations; failed route/schema checks count | 0 failures | automated | U1,U4 |
| Q3 | Interaction capability / accessibility | Loading, API error, run navigation, and metrics have observable roles/text | Testing Library role/visibility assertions across 5 named states; missing states count | 0 missing states | automated | U4 |
| Q4 | Reliability / recoverability | Re-import, append, rewrite, malformed line, and partial tail preserve valid data and retry position | Event counts and subsequent successful retry across 6 named variants; lost/duplicate rows count | 0 lost or duplicate rows | automated plus mutation | U1 |
| Q5 | Security / confidentiality | Prompt/response sentinel never persists or serializes | Search DB bytes and every relevant API response from event and both transcript clients; occurrences | 0 occurrences | automated plus mutation | U3 |
| Q6 | Flexibility / configurability | Factory inputs and all 8 environment overrides control their named boundary | Isolated temp-path/process cases; ignored overrides count | 0 ignored overrides | automated | U4 |

# Verification Obligations
| id | parent requirement/Case ids | applicable targets/input classes | boundary/transition/combination | observation and expected result | evidence procedure |
|---|---|---|---|---|---|
| V1 | F1,F2,C1,C3,C4,Q4 | every telemetry file and both API entry routes | first/repeat/append/rewrite/malformed/partial/missing and both route orders | exact stored/API event counts prove idempotent retry-safe progress | importer and API integration tests |
| V2 | F3,F4,C1-C5,Q1 | evaluator and summary/detail | normal pass, retry/amend, all terminal statuses, incomplete, missing/duplicate/order/identity/post-end | deterministic status/compliance/reasons and exact denominators | table-driven evaluator plus API fixtures |
| V3 | F5,C1,C4,C5,Q5 | Claude and Codex adapters, multiple sessions/models | valid, malformed, missing, content sentinel, multiple linked sessions | normalized arrays contain metadata only and DB/response sentinel count is zero | adapter and API privacy tests |
| V4 | F6,C1,C3,Q1 | five price categories and aggregate levels | each alone, combined, zero, multiple models, unknown model, malformed YAML | Decimal-derived entry/run/summary result or null exactly matches rule | pricing and API aggregation tests |
| V5 | F7,C6,Q2,Q3 | health/API/root/client route and five UI states | API precedence, static fallback, loading/empty/populated/detail/error | correct content types, visible roles/text, and navigation fetch | TestClient, production process, and Vitest |
| V6 | F8,F9,C3,C4,Q2,Q6 | production command and dependency manifests | defaults, 8 overrides, missing optional roots, each required startup failure class | ready server uses selected paths; invalid required input exits non-zero with stderr | subprocess integration and manifest assertions |
| V7 | F2,F5,C5,Q5 | persistence and serialization allowlists | sentinel in event unknown fields and both transcript formats | sentinel absent from DB bytes and API responses | end-to-end privacy assertions and mutation |

# Assumptions and Defaults
| id | decision | evidence and uncertainty | user approval or explicit delegation |
|---|---|---|---|
| A1 | Only current `spec/spec_version` telemetry is supported | Current harness ground truth; historical compatibility explicitly declined | approved by user |
| A2 | No performance threshold; functionality and confidentiality take priority | User selected the functional/security profile | approved by user |
| A3 | Defaults are DB `~/.harness/analytics.sqlite3`, telemetry `~/.harness/telemetry`, Claude `~/.claude/projects`, Codex `~/.codex/sessions`; price/build are package-relative | User selected home-based defaults and environment overrides | approved by user |
| A4 | Metadata is an array per client/session/path/model and total cost is aggregated | Required to include sub-agent and multi-model usage | approved by user |
| A5 | Missing required startup resources fail fast; missing telemetry/transcript roots are empty input | User selected fail-fast startup | approved by user |
| A6 | Two correction batches are allowed | Workflow skill default; included in the approved implementation plan | approved by implementation request |

# Traceability
| requirement id | Case ids | obligation ids | evidence procedure |
|---|---|---|---|
| F1,F2 | C1,C3,C4,C5 | V1,V7 | importer/API/privacy tests |
| F3,F4 | C1-C5 | V2 | evaluator/API aggregation tests |
| F5,F6 | C1,C3-C5 | V3,V4,V7 | adapter/pricing/API privacy tests |
| F7 | C6 | V5 | process/TestClient/Vitest |
| F8,F9 | C3,C4 | V6 | subprocess and manifest tests |
| Q1-Q6 | C1-C6 | V1-V7 | exact Test command plus verifier audit and mutations |

# Workflow Control
| item | value |
|---|---|
| correction batches used | 6 (user approved four extra rounds beyond the 2-batch limit) |
| verifier invocations | 4 |
| open finding ids | none (G5 deferred, non-blocking) |

# Version Log
## v2 close
- Completed after 6 correction batches (4 user-approved beyond the limit) and 4 verifier rounds; G1 rejected, G2-G4/G6-G8 corrected with mutation evidence, G5 deferred as non-blocking.

## v2
- Resolved the test-role F3 challenge by defining every terminal/verifier pairing from the workflow-approach stop and handoff rules; this is the first correction batch.

## v1
- Recovered analytics handoff v5, updated it to current workflow-approach/spec telemetry, and incorporated all user-approved runtime, compatibility, usage-shape, error, and quality decisions.

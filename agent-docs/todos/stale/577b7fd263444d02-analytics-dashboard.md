# Local analytics dashboard

## Goal
"hand off 의 analytic dashboard 체크하고 작업 마무리를 위해 필요한 태스크 파악해서 완료 계획 세워" followed by "Implement the plan." The user later directed: "거기까지 추가 발견한 사항은 handoff로 넘긴다."

## State
- Final resume state: branch `feat/harness-analytics-2`; `tests/test_workflow_markers.py` now covers F1-F6 and `python3 -m unittest discover -s tests -p 'test_*.py'` passes 132 tests.
- The three confirming seeds for F2/F3/F5 now fail as intended and restore successfully. A final verifier accepted F1-F6 but reported F7-F12. F10 was rejected because the contract defines one end command with a status enum, not three status-specific command lines; F7-F9 and F11-F12 remain open.
- A seed attempt for F7 was interrupted by the user; cleanup completed and `python3 .harness/bin/seed.py status` reports `seed: none`. No result is claimed for that seed.
- The analytics contract draft was session-scoped and cleaned up before dispatch. No `analytics/` implementation exists. Confirmed analytics decisions are recorded under Open Questions below.
- Resume update 2026-09-22: branch is `feat/harness-analytics-2`; the approved extra marker correction added isolated required-argument cases and the full harness suite passes 127 tests.
- A fresh verifier found six further test gaps. Three strongest seeds all stayed green, confirming gaps for non-integer verifier counts, end-without-active, and generated commands missing `--run-id`. The restored tree has `seed: none`.
- `agent-docs/contracts/analytics-dashboard.md` v1 was drafted from the confirmed dashboard plan, but analytics implementation has not been dispatched because marker completion remains a prerequisite.
- Branch: `feat/harness-analytics`
- Workflow marker contract v3 is implemented but stopped at the contract-workflow round limit.
- Changed: `harness/VERSION`, `harness/lib/telemetry.py`, `harness/skills/contract-workflow/SKILL.md`, `installer/harness.py`, `tests/test_installer.py`, `tests/test_telemetry.py`.
- Added: `harness/bin/workflow_marker.py`, `tests/test_workflow_markers.py`, `agent-docs/contracts/workflow-markers-v2.md`.
- Pre-existing user change preserved: deleted `agent-docs/contracts/telemetry-markers.md`.
- Baseline: `python3 -m unittest discover -s tests -p 'test_*.py'` passes 126 tests; `python3 .harness/bin/seed.py status` reports `seed: none`.
- Test-oracle corrections now cover phase/result variants, terminal clearing, marker envelopes, contract-gate events, invalid values, migration payload restoration, and colliding repository slugs.
- `harness/lib/telemetry.py` now disambiguates telemetry/state filenames with a deterministic repository-path digest; telemetry test readers select events by the envelope `repo` field.
- `installer/harness.py update .` has not been run for the v0.6.0 source changes. The `analytics/` analyzer has not started.

## Failed Attempts
| attempt | failure evidence | cause |
|---|---|---|
| Marker v1 | Both roles found verifier counts simultaneously required and optional | verified: contract contradiction |
| Marker v2 reconciliation | Seven marker tests failed because automatic events retained hook-inferred contracts | verified: implementation did not make active marker identity authoritative |
| Marker verifier round 1 | Seeds for global workflow state, missing contract-gate attribution, and collapsed end status all stayed green | verified: tests omitted cross-repo revisit, contract-gate event, and all terminal statuses |
| Marker verifier round 2 | Further gaps remain after the maximum two correction rounds | verified: phase variants, post-end clearing variants, other contract-gate events, invalid counts/enums, colliding repo slugs, migration preservation, and marker envelope are not fully covered |
| Authorized extra marker correction round 1 | Initial slug-collision test exposed shared active state, then the collision-safe filename change invalidated filename-coupled test readers | verified: implementation lacked collision isolation and test readers asserted an unspecified filename detail |
| Authorized extra marker verifier round 1 | Seven gaps: active-state collision, failed/malformed start, non-Bash automatic attribution, semantic identity, transition binding, and migration tautology | verified: tests were strengthened and the full suite passed |
| Authorized extra marker verifier round 2 | Three gaps: semantic transition binding, missing-active verifier, and variant shared fields | verified: tests were strengthened and the full suite passed |
| Final fresh marker verifier | M7 still omits separate checks for verifier commands missing `--findings` or `--seeds-run` | verified: only missing `--seeds-detected` is exercised, and the two authorized correction rounds are exhausted |
| User-authorized extra marker correction | Added isolated omissions for `--round`, `--result`, `--findings`, and `--seeds-run`; 127 tests pass, but fresh audit found F1-F6 | verified: the authorized batch fixed its target while the complete audit exposed adjacent automatic-event, invalid-count, missing-active/I/O, skill-command, and migration assertion gaps |
| Extra marker seed triage | Targeted defects for non-integer verifier `--round`, end without an active run, and generated commands missing `--run-id` all left 127 tests green | verified: F2, F3, and F5 are concrete escaping test defects; all seed restores succeeded |
| User-authorized F1-F6 correction | Added automatic-event state matrices, invalid numeric variants, missing-active/I/O cases, required skill flags, and exact 0.6.0 migration assertions; 132 tests pass and all three prior confirming seeds are detected | verified: F1-F6 are closed by tests and seed evidence |
| Final verifier after F1-F6 | Reported F7 collision lifecycle, F8 mismatched verifier identity, F9 malformed non-verifier commands, F10 per-status command binding, F11 migrated payload operability, and F12 non-start envelopes | verified: F10 exceeds the contract's single enum-valued end command; F7-F9 and F11-F12 remain uncorrected; F7 seed execution was interrupted and restored without a result |

## Next Step
Resume from F7-F9 and F11-F12 only if the user chooses to reopen marker verification; seed the strongest findings, correct them as one batch, run a fresh verifier, then run the 132-test suite and `python3 installer/harness.py update .`. Otherwise accept them as known test gaps, apply the update, and start a new analytics contract-workflow run before implementing `analytics/`.

## Open Questions
- Whether F7-F9 and F11-F12 should be corrected or accepted as known marker test gaps.
- Analytics choices already confirmed: FastAPI + React + SQLite outside `harness/`; request-time incremental imports; summary plus run detail; transcript metadata from Claude and Codex without content; linked workflow costs only; `analytics/config.yaml` YAML prices in USD per 1M tokens for input/output/cache-read/cache-write-5m/cache-write-1h; a single production server command; completed-run ordered-transition compliance.
- FastAPI, Uvicorn, PyYAML, and frontend packages are not installed in this environment and must be bootstrapped when analytics work resumes.

## Contract Snapshot
---
version: 3
---

# User Intent
| id | intention | goal to achieve |
|---|---|---|
| U1 | Explicit workflow markers identify contract-workflow runs | Analytics can distinguish observed workflow decisions from inferred hook activity |
| U2 | Automatic hook events carry the active workflow identity | Existing execution events correlate to one run and contract without transcript inspection |
| U3 | Marker recording is best-effort | Telemetry failures never block or alter the workflow |
| U4 | The shipped contract-workflow instructions emit only semantic transitions | Runs record start, phase changes, verifier outcomes, and terminal status with stable fields |
| U5 | Installed harnesses receive the marker extension through an explicit migration | Updating from 0.5.0 preserves user files and installs the new command and instructions |

# Paths
Implementation: harness/lib/telemetry.py, harness/bin/workflow_marker.py, harness/hooks/contract_gate.py, harness/hooks/telemetry_hook.py, harness/skills/contract-workflow/SKILL.md, harness/VERSION, installer/harness.py
Tests: tests/test_workflow_markers.py, tests/test_installer.py, tests/test_telemetry.py
Test command: python3 -m unittest discover -s tests -p 'test_*.py'

# Signatures
harness/bin/workflow_marker.py: main(argv: list[str] | None = None) -> int
harness/lib/telemetry.py: active_workflow() -> dict | None
harness/lib/telemetry.py: emit(payload: dict, event: str, **fields) -> None
Marker CLI: workflow_marker.py start --run-id ID --contract NAME --contract-version N
Marker CLI: workflow_marker.py phase --run-id ID --phase implement_test|verify|amend
Marker CLI: workflow_marker.py verifier --run-id ID --round N --result pass|retry|limit --findings N --seeds-run N --seeds-detected N
Marker CLI: workflow_marker.py end --run-id ID --status complete|handoff|aborted
Marker events retain telemetry envelope v1 and add workflow_run_id and contract; automatic events include both from per-repo active state when present, otherwise null.
HARNESS_TELEMETRY_DIR overrides the directory for both JSONL telemetry and per-repository active workflow state.

# Errors
none raised — invalid marker input or telemetry/state I/O failure exits zero without output and without changing an existing active state

# Cases
| id | level | input / state | expected result |
|---|---|---|---|
| M1 | normal | valid start marker | workflow_start records run id, contract, contract version and makes the run active |
| M2 | normal | phase, verifier, and complete end for active run | stable semantic events are appended with specified fields; end clears active state |
| M3 | normal | automatic hook event while a run is active | event includes active workflow_run_id and contract |
| M4 | normal | installed contract-workflow instructions | start, implement_test/verify/amend phase, verifier result, and complete/handoff/aborted end commands are required at their semantic transitions and described as best-effort |
| M5 | boundary | automatic event with no active marker | workflow_run_id and contract are null; no run is inferred |
| M6 | boundary | verifier has seeds-run 0 and all required non-negative count arguments | zero is recorded as zero without division or invented values; omitting any count is invalid input under M7 |
| M7 | error | malformed command, invalid enum/count, mismatched or missing active run, unwritable telemetry/state | exits zero silently, emits no misleading marker, preserves prior active state |
| M8 | edge | end followed by automatic event | end event remains attributed; later automatic event has null workflow fields |
| M9 | edge | update a 0.5.0 installation | explicit 0.6.0 migration is listed/applied and payload contains marker command and updated skill |
| M10 | edge | two repositories use markers | active state and telemetry correlation remain isolated per repository |

# Verification Obligations
| id | parent intent/Case ids | rule and applicable targets/input classes | boundary/transition/combination | observation and expected result |
|---|---|---|---|---|
| V1 | U1,M1-M3 | start, all phase values, all verifier results, all terminal values | each semantic transition | emitted event preserves identity and declared fields |
| V2 | U2,M3,M5,M8,M10 | automatic hook and contract-gate events | active, absent, ended, colliding repo slugs | identity is active workflow only, otherwise null, with repo isolation |
| V3 | U3,M6,M7 | every required verifier argument and accepted numeric boundary | omit round, result, findings, seeds-run, seeds-detected individually; zero, negative, and non-integer | omissions and invalids are silent no-ops preserving state; zero is recorded |
| V4 | U3,M7 | malformed, mismatched, missing-active, and I/O failure inputs | before/after active-state transition | no misleading event and prior active state remains |
| V5 | U4,M4 | installed skill marker commands | each semantic transition and required option | generated installation documents every command and required field |
| V6 | U5,M9 | update from 0.5.0 | migration confirmation, exact 0.6.0 payload, user-owned file | migration is announced/applied and user content survives |

# Version Log
## v3
- Restored from handoff and made individual required verifier argument omissions explicit. F1-F6 were corrected; F2/F3/F5 confirming seeds are now detected. Final audit left F7-F9 and F11-F12 open; F10 was rejected as outside the declared single enum-valued end command.

## v2
- Made all verifier counts required and defined zero handling; identified HARNESS_TELEMETRY_DIR as the portable override for both event and active-state I/O. Evidence: both v1 roles found the omitted-count wording contradictory, and the test role could not observe state I/O failures without an explicit override contract.

## v1
- Initial contract from the confirmed dashboard plan and resumed telemetry handoff.

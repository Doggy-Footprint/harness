# Local analytics dashboard

## Goal
"A previous agent produced the plan below to accomplish the user's task. Implement the plan in a fresh context. Treat the plan as the source of user intent, re-read files as needed, and carry the work through implementation and verification."

## State
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

## Next Step
Resume the marker contract at v3 only with explicit user authorization for another contract-workflow round. Add M7 cases for verifier commands separately omitting `--findings` and `--seeds-run`, run a fresh verifier, seed its strongest findings, then run the full suite and `python3 installer/harness.py update .`. After marker completion, create a separate analytics contract and implement the FastAPI/React/SQLite dashboard outside `harness/`.

## Open Questions
- Whether the user authorizes another round beyond the two extra correction rounds completed in this resume.
- Analytics dependency/bootstrap details remain to be contracted; FastAPI is not installed in the current Python environment, while Node/npm are available.

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

# Version Log
## v3
- Added existing installer and telemetry regression suites to Tests. Evidence: the exact full-suite command showed their 0.5.0 version and migration-confirmation expectations necessarily changed under M9/U5.

## v2
- Made all verifier counts required and defined zero handling; identified HARNESS_TELEMETRY_DIR as the portable override for both event and active-state I/O. Evidence: both v1 roles found the omitted-count wording contradictory, and the test role could not observe state I/O failures without an explicit override contract.

## v1
- Initial contract from the confirmed dashboard plan and resumed telemetry handoff.

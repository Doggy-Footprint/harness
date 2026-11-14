---
version: 4
run_id: 49bafb302bb6593c
status: complete
base_commit: 38d9b7eedb6418b1d4298e9235cf94927134d46a
max_verifier_invocations: 2
commit: 38d9b7eedb6418b1d4298e9235cf94927134d46a
---

# User Intent
| id | stakeholder | intention | observable goal |
| --- | --- | --- | --- |
| I1 | harness owner | see workflow-approach brief rounds that happen before approval, including briefs that never reach approval | each understanding round, decision round, and approval brief leaves one `brief` line in the telemetry jsonl, carrying the run id, stage, round number, the round's counts (fact questions, cumulative user decisions, split state, picks differing), and a pointer (session id + `tool_use_id`) to the turn that holds the brief text |
| I2 | harness owner | see when facts are recorded under `agent-docs/facts/` | a Write, Edit, or apply_patch of a fact file leaves one `fact_write` line with the fact id and dimension token |
| I3 | harness owner | tell an intent-mismatch amendment from other amendments and corrections | `workflow_phase` lines for `amend` carry a `reason` |
| I4 | harness owner | read these events personally in the analytics dashboard | run detail lists the run's brief rounds with their pointers and its amend reasons; the summary lists runs that have brief events but no workflow start yet |
| I5 | harness owner, future multi-person digest | aggregate telemetry across people without carrying free text | new events carry only enum values, counts, ids, and pointers; no brief text and no fact file name |

# Scope
In scope: the `brief` subcommand of `harness/bin/workflow_marker.py`; `brief` and `fact_write` emission in `harness/hooks/telemetry_hook.py`; the optional `--reason` of `phase --phase amend`; the analytics importer keeping the new fields; analytics API (`/api/summary`, `/api/runs/{run_id}`) and dashboard display of brief rounds, amend reasons, and brief-only runs; workflow-approach SKILL.md Telemetry text for the new marker and reason; harness version 0.49.0 with its migration entry.
Out of scope: any parsing of transcript text (todo `b2373e0fdc356594-brief-transcript-parser.md`); changes to `analytics/compliance.py` verdicts; Codex-specific behavior; the test-suite telemetry leak (`e00f26d26c7ef940`, fixed by main outside this spec).

# Paths
Implementation: harness/bin/workflow_marker.py, harness/hooks/telemetry_hook.py, harness/lib/telemetry.py, harness/lib/config.py, harness/skills/workflow-approach/SKILL.md, harness/VERSION, installer/harness.py, analytics/importer.py, analytics/app.py, analytics/frontend/src/App.jsx, analytics/frontend/src/hints.js
Tests: tests/test_brief_telemetry.py, analytics/tests/test_brief_dashboard.py, analytics/frontend/src/BriefTelemetry.test.jsx, the existing files under tests/ and analytics/tests/ whose harness version strings must move from 0.48.0 to 0.49.0, and analytics/tests/test_classification_v4.py (its list of summary keys added after its own run gains `brief_only_runs`)
Test command: uv run --python 3.12 --with-requirements analytics/requirements.txt --with pytest --with hypothesis sh -c 'python tests/run_parallel.py && python -m pytest -q -p no:cacheprovider analytics/tests' && cd analytics/frontend && npx vitest run
Test convention: tests under `tests/` are `unittest.TestCase` classes, because `tests/run_parallel.py` collects only those.
Review evidence: R1 — after the Test command passes, main runs `git diff --stat 38d9b7eedb6418b1d4298e9235cf94927134d46a -- tests analytics/tests analytics/frontend/src` and confirms that pre-existing test files changed only in harness version strings (0.48.0 → 0.49.0, including 0.49.0 appended to expected migration lists) and, in analytics/tests/test_classification_v4.py, only by adding `brief_only_runs` to its set of later-added summary keys, so existing behavior assertions are unchanged.
Fuzzing: none — the hook's no-crash property over random Bash commands is a Hypothesis test inside the Test command (O13); there is no separate fuzz surface.
Mutation tool: none

# Signatures
CLI: `python3 .harness/bin/workflow_marker.py brief --run-id <16 lowercase hex> --stage understanding|decision|approval --round <integer ≥ 1> [--fact-questions <integer ≥ 0>] [--user-decisions <integer ≥ 0>] [--split none|proposed|accepted|declined] [--picks-differ <integer ≥ 0>]` → exit 0, empty stdout and stderr, writes no telemetry line.
CLI: `python3 .harness/bin/workflow_marker.py phase --run-id ID --phase implement_test|verify|amend [--reason intent_mismatch|brief_change|contract_change|correction]` → exit 0, empty stdout and stderr.
Telemetry line `brief`: keys exactly `v, ts, harness_version, repo, client, session_id, agent_id, agent_type, tool_use_id, event, workflow_run_id, spec, stage, round, fact_questions, user_decisions, split, picks_differ`; `event: "brief"`, `spec: null`, `workflow_run_id` = the `--run-id` value, `stage` string, `round` integer; `fact_questions`, `user_decisions`, `picks_differ` integers and `split` string from their flags, each null when its flag is absent; `client`, `session_id`, `agent_id`, `agent_type`, `tool_use_id` come from the PostToolUse payload as for every other hook-emitted line.
Telemetry line `fact_write`: keys exactly `v, ts, harness_version, repo, client, session_id, agent_id, agent_type, tool_use_id, event, workflow_run_id, spec, fact_id, dimension`; `workflow_run_id` and `spec` from the active workflow state as for `spec_write` (null without one).
Telemetry line `workflow_phase` with `phase: "amend"`: existing keys plus `reason` (one of the four values, or null when `--reason` was not given). Non-amend `workflow_phase` lines keep exactly their 0.48.0 key set.
0.48.0 line shapes (read from base_commit `harness/lib/telemetry.py` `_emit`/`_event_fields`, `harness/hooks/telemetry_hook.py`, `harness/lib/session_metrics.py`), envelope E = `v, ts, harness_version, repo, client, session_id, agent_id, agent_type, tool_use_id, event`: `test_command` E + `spec, exit_code, workflow_run_id`; `seed` E + `action, exit_code, workflow_run_id, spec`; `spec_write` E + `spec, version, workflow_run_id`; `progress_write` E + `file, workflow_run_id, spec`; non-amend `workflow_phase` E + `phase, workflow_run_id, spec, spec_version`; `session_metrics` E + `exploration_before_code, noncode_writes_before_code, code_writes, unclassified_shell_writes, tool_calls, first_code_write, workflow_run_ids, ended_cleanly, workflow_run_id, spec`. In every one of these, `spec` and `workflow_run_id` are the active workflow's values, or null without one (the `spec` passed by `test_command` and `spec_write` is overwritten by `_event_fields`).
API `/api/runs/{run_id}`: existing keys plus `briefs: [{stage, round, fact_questions, user_decisions, split, picks_differ, ts, session_id, tool_use_id}]` and `amend_reasons: {intent_mismatch, brief_change, contract_change, correction, unspecified}` (integers).
API `/api/summary`: existing keys plus `brief_only_runs: [{run_id, rounds, last_stage, last_ts}]`.

# Functional Requirements
| id | requirement | priority | source |
| --- | --- | --- | --- |
| F1 | `workflow_marker.py brief` with any argv exits 0 with empty stdout and stderr and appends no line to the telemetry jsonl. | must | A2 |
| F2 | On a `PostToolUse` payload with `tool_name: "Bash"`, the hook tokenizes the command (from `hook_shared.shell_command`) with POSIX shell rules where `;`, `&`, `|`, `(`, `)` runs form separate separator tokens. For each occurrence of a token equal to `.harness/bin/workflow_marker.py` or ending in `/.harness/bin/workflow_marker.py` that is immediately followed by the token `brief`, the tokens after `brief` up to the next separator token or the end are the marker's arguments. The occurrence is valid when those arguments are exactly one each of `--run-id`, `--stage`, `--round`, and at most one each of `--fact-questions`, `--user-decisions`, `--split`, `--picks-differ` (in any order, each followed by its value, nothing else); the run id matches `^[0-9a-f]{16}$`; the stage is `understanding`, `decision`, or `approval`; the round is a decimal integer ≥ 1 with no sign; the three count flags are decimal integers ≥ 0 with no sign; `--split` is `none`, `proposed`, `accepted`, or `declined`. Each valid occurrence emits one `brief` line, in command order. | must | I1, A1, A2 |
| F3 | No `brief` line is emitted when the Bash tool response carries an integer `exit_code` other than 0, when the hook event is `PostToolUseFailure` or `PreToolUse`, when the tool is not Bash, or when the command cannot be tokenized (e.g. unbalanced quotes). A missing or non-integer `exit_code` does not suppress emission. | must | I1 |
| F4 | `brief` detection does not change the existing handling of the same call: `test_command`, `seed`, and `session_metrics` behave as in 0.48.0. | must | compatibility |
| F5 | `phase --phase amend --reason R` emits the `workflow_phase` line with `reason: R`; `phase --phase amend` without `--reason` emits it with `reason: null`; a `--reason` value outside the four emits nothing; `--reason` given with `implement_test` or `verify` emits the phase line without a `reason` key. Emission still requires the matching active workflow state as in 0.48.0. | must | I3, A5 |
| F6 | A PostToolUse Write or Edit (`tool_input.file_path`) or apply_patch (`*** Add File:` / `*** Update File:` paths) of a `.md` file whose resolved parent is the resolved `<docs_root>/facts` directory, other than `index.md` and `stale.md`, emits one `fact_write` line per path. `fact_id` is the file name's first 16 characters when the name matches `^[0-9a-f]{16}-`, else null. `dimension` is the hyphen-separated segment after the id when the name matches `^[0-9a-f]{16}-<segment>-` and the segment is one of `load, data, concurrency, environment, consumers, roadmap, failure, cost`, else null. Files in subdirectories of `facts/` emit nothing. | must | I2, A6 |
| F7 | The analytics importer keeps scalar `stage`, `reason`, `fact_id`, `dimension`, `fact_questions`, `user_decisions`, `split`, and `picks_differ` fields in stored event payloads. | must | I4 |
| F8 | In the analytics API, `fact_write` events are not part of any run, and a run-id group with at least one `brief` event and no event other than `brief` and `fact_write` is a brief-only run. Brief-only runs are left out of every pre-existing `/api/summary` field (counts, sums, `run_items`, `workflow.runs`, `classification`, `non_workflow`) and listed in `brief_only_runs` with `rounds` (number of its brief events), `last_stage` and `last_ts` (from its latest-`ts` brief event), ordered by `last_ts` descending. | must | I4, A4 |
| F9 | `brief` events never link a session to a run: they are ignored wherever the API derives linked sessions (usage, cost, session classification, non-workflow sessions). | must | A7 |
| F10 | `/api/runs/{run_id}` returns `briefs` (the run's brief events in stored order, each `{stage, round, fact_questions, user_decisions, split, picks_differ, ts, session_id, tool_use_id}`) and `amend_reasons` (counts of the run's `workflow_phase` amend events by `reason`; a missing, null, or unknown reason counts as `unspecified`). For a brief-only run it returns 200 with `status: "before_approval"`. Unknown run ids still return 404. | must | I4, A4 |
| F11 | The dashboard run detail shows a "Brief" card listing each entry of `briefs` with stage, round, fact questions, user decisions, split, picks differing, time, session id, and tool use id (an empty cell for null), or "No brief events." when empty, and the five `amend_reasons` counts. For `status: "before_approval"` it shows that status badge and no compliance badge. The summary shows a "Briefs before approval" card listing `brief_only_runs` (run id, rounds, last stage) whose run id opens that run's detail as the run list does; "No briefs before approval." when empty. Every new hint key has both `en` and `ko` text. | must | I4, A4 |
| F12 | `harness/skills/workflow-approach/SKILL.md` states: the run id is chosen before the understanding round; `python3 .harness/bin/workflow_marker.py brief --run-id ID --stage understanding|decision|approval --round N` is emitted in the same turn as each understanding round, decision round, and approval brief, with N counting rounds of that stage from 1, plus `--fact-questions` (fact questions asked in that round), `--user-decisions` (the *Your decision* count over the whole task so far, as the cap counts it), `--split` (`proposed` in the round that proposes a split, `accepted` or `declined` in the next round after the user answers, `none` otherwise), and on the approval brief `--picks-differ` (decisions where the user's choice differs from the picks file); `phase --phase amend` takes `--reason intent_mismatch|brief_change|contract_change|correction`, with `intent_mismatch` for amendments forced by an intent mismatch found after approval, `brief_change` for other amendments that change a brief item, `contract_change` for contract-only amendments, and `correction` for correction batches that do not change the spec. | must | I1, I3, A3, A5 |
| F13 | `harness/VERSION` is `0.49.0`, and `installer/harness.py` `MIGRATIONS` has a 0.49.0 entry whose dry-run lines describe the new brief marker, fact_write event, and amend reason, and state that no existing files change. | must | AGENTS.md |

# Errors
- Invalid `brief` CLI argv (missing flag, bad stage, round 0 or non-integer, unknown flag) — exit 0, empty stdout/stderr — no telemetry line, no file created.
- Hook sees an invalid `brief` occurrence (F2 rules violated) or an untokenizable command — no `brief` line, hook exits 0 with empty stdout — other telemetry of the call unchanged, later valid occurrences in the same command still emit.
- Bash call exits non-zero — no `brief` line — other telemetry of the call unchanged.
- Telemetry directory unwritable — no line, hook and CLI exit 0 with empty stdout — no exception reaches the caller.
- `--reason` outside the four values — no `workflow_phase` line, exit 0 — active workflow state unchanged.
- Fact file name not matching the id or dimension pattern — `fact_write` with `fact_id` and/or `dimension` null — line still emitted.
- Stored brief event with a missing `stage`, `round`, `session_id`, or `tool_use_id` — API reports null for that key — no error status.
- `/api/runs/<unknown>` — HTTP 404 — no state change.

# Cases
| id | level | input / state | expected result |
| --- | --- | --- | --- |
| C1 | normal | Bash `python3 .harness/bin/workflow_marker.py brief --run-id 49bafb302bb6593c --stage understanding --round 1`, exit_code 0, payload session_id S, tool_use_id T | one `brief` line with run id, stage `understanding`, round 1, session_id S, tool_use_id T, spec null, exact key set |
| C2 | normal | same with `--round 2 --stage decision --run-id …` (reordered flags), absolute script path `/x/repo/.harness/bin/workflow_marker.py` | one `brief` line, stage `decision`, round 2 |
| C3 | normal | `true && python3 .harness/bin/workflow_marker.py brief --run-id … --stage approval --round 1; echo done` | one `brief` line, stage `approval` |
| C4 | boundary | round `0`, `1`, `+1`, `01`; run id of 15, 16, 17 hex chars; uppercase hex; `--fact-questions` `-1`, `0`, `1`; `--split` `maybe` | only round `1` and `01` with 16 lowercase hex emit; count `0` and `1` emit, `-1` does not; `maybe` does not |
| C4b | normal | valid marker with all four optional flags; valid marker with none | line carries the four values; line carries the four keys as null |
| C5 | error | stage `approved`; missing `--round`; duplicated `--stage`; extra `--foo x`; unbalanced quote | no `brief` line, hook exit 0, empty stdout |
| C6 | error | valid marker but tool_response exit_code 1; PostToolUseFailure payload; PreToolUse payload | no `brief` line |
| C7 | edge | two valid marker occurrences joined by `&&` | two `brief` lines in command order |
| C8 | edge | command equals an active spec's Test command and also contains nothing else; separately a seed command | `test_command` / `seed` lines as in 0.48.0, no `brief` line |
| C9 | normal | `workflow_marker.py brief …` run directly (CLI) | exit 0, empty stdout/stderr, telemetry file not created |
| C10 | normal | active run, `phase --phase amend --reason intent_mismatch` / each other reason | `workflow_phase` line with that `reason` |
| C11 | boundary | `phase --phase amend` without reason; `--reason bogus`; `--phase verify --reason correction` | `reason: null`; no line; line without `reason` key |
| C12 | normal | Write `agent-docs/facts/67ac615b0c9ad3aa-consumers-brief-telemetry-personal-dashboard.md` | `fact_write` with fact_id `67ac615b0c9ad3aa`, dimension `consumers`, no file name anywhere in the line |
| C13 | edge | facts `index.md`, `stale.md`, `stale/x.md`, `notes.txt`, `abc-load-x.md`, `67ac615b0c9ad3aa-weather-x.md`; apply_patch adding two fact files | nothing; nothing; nothing; nothing; fact_id null dimension null; fact_id set dimension null; two lines |
| C14 | normal | analytics dataset with a brief-only run B and a full run W that also has brief events and amend phases with mixed reasons | summary pre-existing fields equal those of the dataset without brief events; `brief_only_runs` lists B; `/api/runs/W` has `briefs` and correct `amend_reasons`; `/api/runs/B` status `before_approval` |
| C15 | edge | brief event missing `tool_use_id`; amend with reason `weird` | `tool_use_id: null`; counted `unspecified` |
| C16 | normal | dashboard renders detail with briefs, empty briefs, before_approval; summary with and without brief_only_runs | card rows / empty message / badge rules / link opens detail |
| C17 | normal | `harness.py update --dry-run` from 0.48.0 | prints `migration 0.49.0: <label>` and its lines |

# Quality Applicability
| ISO/IEC 25010:2023 characteristic | applicable | rationale |
| --- | --- | --- |
| Functional suitability | yes | new events and dashboard views are the deliverable |
| Performance efficiency | no | the hook adds one tokenization per Bash call and a few lines per run; no load-sensitive path |
| Compatibility | yes | existing telemetry lines, analytics outputs, and installed repos on older versions must keep working |
| Interaction capability | no | dashboard additions are plain cards whose content is specified in F11 |
| Reliability | yes | the hook runs on every tool call; a crash or stray stdout would block the agent's tool loop |
| Security | yes | multi-person aggregation is planned (fact `e06d861b6fec1853`); new events must not carry free text |
| Maintainability | no | covered by the migration requirement F13; no separate measure |
| Flexibility | no | no new deployment target |
| Safety | no | no physical or irreversible effect |

# Quality Requirements
| id | characteristic / subcharacteristic | target and context | measure method / inputs / unit | threshold and direction | evidence: automated, review, mutation | source |
| --- | --- | --- | --- | --- | --- | --- |
| Q1 | Compatibility / co-existence | analytics API outputs for data without the new events | metamorphic: base fixture dataset D versus D plus brief-only run, brief events on an existing run, and `fact_write` lines; compare every pre-existing key of `/api/summary` and `/api/runs/{id}` for D's runs; count of differing values | 0, lower is better | automated O9; mutation | I4, F8, F9 |
| Q2 | Compatibility / co-existence | telemetry line shapes of 0.48.0 events | key sets of `workflow_phase` (non-amend), `spec_write`, `progress_write`, `test_command`, `seed` emitted after the change versus the 0.48.0 sets; differing keys | 0, lower is better | automated O5, O8b | F4, F5 |
| Q3 | Reliability / fault tolerance | hook under arbitrary Bash payloads | Hypothesis random testing, 300 examples, fixed seed 49 — random commands mixing marker tokens, separators, quotes, and random exit codes; count of runs with non-zero exit or non-empty stdout | 0, lower is better | automated O13 | F2, F3 |
| Q4 | Security / confidentiality | new event lines | for every `brief` and `fact_write` line in O1–O6 fixtures: key set equals the Signatures set, and the line contains no fact file kebab name and no command text; violations | 0, lower is better | automated O14 | I5, A6 |

# Verification Obligations
| id | parent requirement/Case ids | variant and target surface | test layer and selection policy | ISO/IEC/IEEE 29119-4 technique | coverage items | coverage target | observation and expected result | evidence procedure |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| O1 | F2, F3, C1–C3, C5–C7 | installed hook `.harness/hooks/telemetry_hook.py` in a temp installed repo, stdin payload | integration; every rule below | decision table | R1 valid relative script path; R2 valid absolute-suffix path; R3 other script name (`workflow_marker.py` without `.harness/bin/`); R4 subcommand not `brief`; R5 flags reordered; R6 duplicated flag; R7 missing flag; R8 unknown flag; R9 bad stage; R9b each optional flag duplicated; R9c bad `--split` value; R10 chained with `&&`/`;`; R11 two occurrences; R12 exit_code 1; R13 exit_code missing; R14 PostToolUseFailure; R15 PreToolUse; R16 non-Bash tool; R17 unbalanced quotes | 100% | jsonl lines in `HARNESS_TELEMETRY_DIR`; emit only for R1, R2, R5, R10, R11 (twice), R13 | Test command |
| O2 | F2, C4, C4b | same surface | integration | boundary value analysis (3-value) plus equivalence partitioning for the optional flags | round `0`, `1`, `2`; round `+1`, `01`; run id length 15, 16, 17; uppercase 16-hex; each count flag `-1`, `0`, `1`; split each of the four values and `maybe`; all optional flags absent | 100% | emit for round `1`, `2`, `01` with length 16 lowercase; counts `0`, `1`; the four split values; absent flags give null values | Test command |
| O3 | F2, C1 | same surface | integration | equivalence partitioning | payload with agent_id/agent_type set; payload without them; transcript_path under `/.claude/` | 100% | line values equal payload values; `client` `claude`; key set exact | Test command |
| O4 | F1, C9 | installed `.harness/bin/workflow_marker.py` subprocess | integration | equivalence partitioning | valid argv; each invalid class of Errors bullet 1 | 100% | exit 0, empty stdout/stderr, telemetry file absent | Test command |
| O5 | F5, C10, C11 | installed CLI with an active workflow started via `start` | integration | equivalence partitioning | reason intent_mismatch, brief_change, contract_change, correction, absent, invalid; `verify --reason correction`; `implement_test` without reason (key set unchanged) | 100% | `reason` value / null / no line / no `reason` key | Test command |
| O6 | F6, C12, C13 | installed hook, PostToolUse Write / Edit / apply_patch payloads | integration | decision table | D1 patterned name valid dimension; D2 invalid dimension segment; D3 no id prefix; D4 index.md; D5 stale.md; D6 subdirectory; D7 non-md; D8 outside facts dir; D9 apply_patch two files; D10 Edit tool; D11 relative file_path | 100% | lines and field values per F6 | Test command |
| O7 | F7 | analytics import through `create_app` + an API GET on a temp telemetry dir, stored payload read from the sqlite db | integration | equivalence partitioning | each of stage, reason, fact_id, dimension, fact_questions, user_decisions, split, picks_differ as scalar (kept); as list (dropped) | 100% | stored payload JSON | Test command |
| O8 | F8, F10, C14, C15 | FastAPI TestClient over `create_app` with temp db and telemetry dir | integration | decision table | A1 brief-only run listed and excluded; A2 ordering of two brief-only runs by last_ts; A3 brief events on full run appear in `briefs` in stored order; A4 amend reasons each value + null + missing + unknown; A5 brief-only detail 200 `before_approval`; A6 unknown run 404; A7 missing pointer fields null; A8 a run-id group of `brief` plus `fact_write` events is listed as brief-only and its detail is `before_approval` | 100% | JSON values | Test command |
| O8b | F4, Q2 | installed hook, test_command and seed payloads, spec_write/progress_write payloads | integration | equivalence partitioning | test_command; seed; spec_write; progress_write; non-amend workflow_phase; session_metrics (differential: PostToolUse Bash of a valid brief marker command then SessionEnd, versus the same command with subcommand `bogus` then SessionEnd, same session id) | 100% | exact key sets of the Signatures 0.48.0 line shapes, `spec`/`workflow_run_id` null without and equal to the active workflow with one; no `brief` line from the marker-free commands; the two `session_metrics` lines equal except `ts` | Test command |
| O9 | Q1, F8, F9 | TestClient, dataset D vs D+ | integration | metamorphic testing | MR1 summary pre-existing keys equal; MR2 each D run detail pre-existing keys equal; MR3 classification and non_workflow equal when a brief event shares a session with another run | 100% | zero differing values | Test command |
| O10 | F11, C16 | React components via vitest + Testing Library with stubbed fetch | unit | scenario testing | S1 detail with two briefs; S2 detail empty briefs; S3 before_approval badges; S4 amend reason counts shown; S5 summary list rendered and clicking a run id requests `/api/runs/<id>`; S6 summary empty message; S7 every new hint key has en and ko | 100% | rendered text, badges, fetch URL | Test command |
| O11 | F12 | `harness/skills/workflow-approach/SKILL.md` text | unit | syntax testing | K1 brief command line with three stages and `--round N`; K2 same-turn emission for each of the three brief stages; K3 run id chosen before understanding round; K4 `--reason` with four values; K5 each value's meaning, bound to its own value (the meaning text appears after the value and before the next of the four value tokens); K6 N counts rounds of that stage from 1; K7 `--fact-questions` = fact questions asked in that round; K8 `--user-decisions` = *Your decision* count over the whole task so far; K9 `--split` proposed in the proposing round, accepted or declined in the next round, none otherwise; K10 `--picks-differ` on the approval brief = decisions where the user's choice differs from the picks file | 100% | substring / regex presence | Test command |
| O12 | F13, C17 | installer `update --dry-run` on a repo installed at 0.48.0 (existing test helpers), and `harness/VERSION` | integration | equivalence partitioning | VERSION value; dry-run migration header; dry-run lines mention brief, fact_write, amend reason, no files change | 100% | stdout | Test command |
| O13 | Q3, F3 | installed hook subprocess | integration | random testing | 300 Hypothesis examples, seed 49 | 100% of examples | exit 0, empty stdout | Test command |
| O14 | Q4, I5 | lines produced in O1–O6 | integration | equivalence partitioning | brief lines; fact_write lines | 100% | exact key set; no kebab name; no command text | Test command |

# Assumptions and Defaults
| id | decision | evidence and uncertainty | approval |
| --- | --- | --- | --- |
| A1 | `brief` event carries stage, round, run id, the Tier 2 counts (fact questions, cumulative user decisions, split state, picks differing), and the pointer | user first chose Tier 1 + pointer, then on 2026-11-14 at the approval brief adopted Tier 2 as well: "there is no reason not to include values that already exist" | user decision (main: Tier 2) |
| A2 | the PostToolUse hook emits `brief`; the CLI subcommand emits nothing | the CLI is a Bash child without session id or tool_use_id (`telemetry.workflow_phase` emits with `{}` payload, `harness/lib/telemetry.py:221`); the hook already detects test_command and seed commands the same way (`harness/hooks/telemetry_hook.py:94-104`) | brief v1 — approved |
| A3 | the run id is chosen before the understanding round | the picks file needs it by the decision round; the understanding round's brief event needs it earlier | brief v1 — approved |
| A4 | dashboard: Brief card in run detail, Briefs-before-approval card in summary; brief-only runs excluded from existing summary fields | user accepted run A scope "brief round list and pointer in run detail" on 2026-11-14; the summary card and exclusion keep existing rates unchanged | user answer (detail card); brief v1 — approved (summary card, exclusion) |
| A5 | amend reason vocabulary intent_mismatch / brief_change / contract_change / correction, flag optional | categories from SKILL.md Identity and lifecycle rule 5 and Workflow step 7; optional so an agent following older text still emits the phase | brief v1 — approved |
| A6 | `fact_write` records fact id and dimension token only, not the file name | multi-person aggregation planned (fact `e06d861b6fec1853`); file names embed fact content | brief v1 — approved |
| A7 | brief events do not link sessions to runs | a session that briefed run X and then ran run Y would otherwise be linked to two runs and classified noncompliant (`analytics/app.py:138`) | brief v1 — approved |
| A8 | delete `~/.harness/telemetry/*T-tmp*.session-lock` after the leak fix | user decision 2026-11-14 | user decision (main: delete) |
| A9 | the test-suite leak is fixed by main outside this spec, before dispatch | the fix edits shared test helpers that test roles read; putting them in Implementation would hide them from test-implementer | brief v1 — approved |
| A10 | no transcript parsing and no extra parser fields in this run | user split the work and rejected all extra parser fields (pointer allows recovery) | user answer |
| A11 | models: implementer opus, test-implementer sonnet, test-verifier sonnet | implementer change spans hook, CLI, installer, analytics backend, and React frontend | brief v1 — approved |
| A12 | coverage targets 100% for every specification-based obligation; no structure-based target | changed harness code runs in child processes, which the Test command does not measure | brief v1 — approved |

# Traceability
| requirement id | Case ids | obligation ids | evidence procedure |
| --- | --- | --- | --- |
| F1 | C9 | O4 | Test command |
| F2 | C1–C5, C7 | O1, O2, O3 | Test command |
| F3 | C5, C6 | O1, O13 | Test command |
| F4 | C8 | O8b | Test command |
| F5 | C10, C11 | O5 | Test command |
| F6 | C12, C13 | O6 | Test command |
| F7 | C14 | O7 | Test command |
| F8 | C14 | O8, O9 | Test command |
| F9 | C14 | O9 | Test command |
| F10 | C14, C15 | O8 | Test command |
| F11 | C16 | O10 | Test command |
| F12 | — | O11 | Test command |
| F13 | C17 | O12 | Test command, R1 |
| Q1 | C14 | O9 | Test command |
| Q2 | C8, C11 | O5, O8b | Test command |
| Q3 | C5 | O13 | Test command |
| Q4 | C1, C12 | O14 | Test command |

# Workflow Control
| item | value |
| --- | --- |
| correction batches used | 3 |
| verifier invocations | 2 |
| open finding ids | none |

Audit state (one entry per obligation; retain prior decisions in the execution ledger):
| obligation id | spec version | evidence references and revision | accepted / open / invalidated / pending | rationale and mutation outcome | dependencies and reopening evidence |
| --- | --- | --- | --- | --- | --- |
| O1–O14, O8b | 4 | verifier invocation 2 (v4), Test command run 5 | accepted | invocation 1 accepted O1–O7, O8–O10, O12–O14; invocation 2 closed SC-1, SC-2 (O8b) and SC-3, EG-1 (O11) and re-accepted O1, O5, O8, O12 after their test changes; hand mutations M1–M12 all killed; advisories open: K5 wording does not state that same-value occurrences are skipped, `+1` rejection tested only on `--fact-questions` among the count flags, F4 side check compares event names only | none |

Execution ledger (append attempts; preserve failed approaches):
| attempt | finding / failure signature | cause hypothesis | changed approach / new evidence | result / disposition |
| --- | --- | --- | --- | --- |
| 1 | Test command run 1: 3 failures in tests/test_brief_telemetry.py — TestBriefCli repo snapshot differs by `.harness/lib/__pycache__/config.cpython-312.pyc`; TestSkillText K2 window lacks `workflow_marker.py brief`; K4 literal `phase --phase amend` absent | test defects: bytecode cache is an interpreter artifact ignored by git (Errors bullet 1 means the telemetry file); SKILL.md writes the command as `phase --run-id ID --phase amend` and refers to the marker as `brief` in the emission sentence | snapshot excludes `__pycache__`; K2 accepts `` `brief` ``; K4 matches the full amend command line | run 2: harness suite OK |
| 2 | Test command run 2: analytics MR2 `transcript_metadata` differs only by dataset directory (`base/` vs `plus/`); pre-existing test_classification_v4 Q1 fails on new summary key `brief_only_runs` | test defect (fixture paths) and spec gap (an existing test asserts whole-summary equality) | MR2 normalises the dataset root before comparing; spec v3 admits `brief_only_runs` in test_classification_v4's later-added key set | run 3: Test command rc 0 (1367 harness, 395 analytics, 35 vitest) |
| 3 | implementer challenges: fact_write events absent from API; brief+fact_write-only run shown as brief-only | consistent with Q1 (pre-existing run detail keys unchanged) and F8–F11 (no fact display required) | accepted without amendment | — |
| 4 | verifier invocation 1: retry, blocking SC-1, SC-2, SC-3, EG-1; advisory A-1…A-9 | spec omitted 0.48.0 key sets, session_metrics item and F12 flag meanings; K5 regex not bound to its value | spec v4; test-implementer revised O8b (exact 0.48.0 sets, session_metrics differential), O8 A8, O11 K5–K10, O12 section bound, O1 two advisory cases | Test command run 4: K5 `correction` failed because the meaning text "correction batch" contains the value word, which the segment rule treated as the next value; main changed the segment end to the next *different* value token (swapped-mapping check still fails, checked on a synthetic text); run 5 rc 0 (1375 harness, 397 analytics, 35 vitest) |
| 5 | hand mutations M1–M12 (one at a time, file restored after each) | duplicate optional flag accepted; invalid occurrence aborts later ones; missing exit_code suppresses; round 0 accepted; `+` sign accepted; fact dimension not checked; invalid `--reason` emits; last_stage from last stored event; brief events enter run groups; unknown amend reason dropped; before_approval shows compliance badge; SKILL reason meanings swapped | — | all 12 killed by the intended assertions (O1 R6/R11/R13, O2 round, O1 count `+1`, O6 D2, O5 invalid, O8 A2/A1/A4, O10 S3, O11 K5) |
| 6 | verifier invocation 2 | pass, no blocking finding | — | all obligations accepted; three advisories left open |

# Version Log
## v4
- Verifier invocation 1 findings: SC-1 (0.48.0 key sets unstated) → Signatures list the exact 0.48.0 line shapes read from base_commit and O8b asserts them; SC-2 (F4 `session_metrics` uncovered) → O8b gains a differential session_metrics item; SC-3 and EG-1 (F12 partly covered, K5 unbound) → O11 gains K6–K10 and K5 binds each meaning to its value; advisory A-1 → O7 layer recorded as integration through create_app; advisory A-2 → F8 states that `fact_write` events belong to no run, O8 gains A8. Contract-only.
## v3
- Tests paths and review evidence R1 admit `brief_only_runs` in analytics/tests/test_classification_v4.py's set of later-added summary keys: that test asserts the whole summary equals its own baseline, so F8's new key fails it (Test command run 2). Expected migration lists gaining 0.49.0 count as version-string changes. Contract-only.
## v2
- O7 coverage items extended from four fields to all eight importer fields of F7; the Tier 2 count fields were added to F7 at v1 without O7 following. Contract-only, before dispatch.
## v1
- Before approval, the user moved the brief event from Tier 1 + pointer to Tier 2 + pointer (count flags optional, null when absent).
- Initial draft from the understanding and decision rounds of 2026-11-14; the run was split, transcript parsing moved to todo `b2373e0fdc356594`.

# Retrospective
## 2026-11-14
| observation | evidence | how to re-check |
| --- | --- | --- |
| Running analytics tests with `/Users/hwansu/tools/harness/.venv` fails 58 tests with `Router.__init__() got an unexpected keyword argument 'on_startup'` (starlette/fastapi version mismatch in that venv); the same tests pass under `uv run --python 3.12 --with-requirements analytics/requirements.txt` | baseline run before implementation, 58 failed / 321 passed under the venv, 379 passed under uv | `/Users/hwansu/tools/harness/.venv/bin/python -m pytest -q analytics/tests` |

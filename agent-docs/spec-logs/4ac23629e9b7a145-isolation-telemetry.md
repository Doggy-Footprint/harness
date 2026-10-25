---
version: 3
run_id: 4ac23629e9b7a145
status: complete
base_commit: 58045c79e736ff3d89bc71115f587fa4eb95d61f
max_verifier_invocations: 2
handoff: agent-docs/handoff/7c41e9b2d05af386-test-implementer-isolation-violation.md
commit: 58045c79e736ff3d89bc71115f587fa4eb95d61f
---

# User Intent
| id | stakeholder | intention | observable goal |
| --- | --- | --- | --- |
| I1 | harness maintainer | see how often test-implementer reads Implementation or runs tests, and the reverse for implementer, before deciding on hook blocking (issue #21) | every matching subagent tool call in an installed repo produces one `isolation_candidate` telemetry line per fired rule, carrying a raw excerpt |
| I2 | harness maintainer | see whether main's dispatch still tells test-implementer to run tests after 0.31.0 | a main Agent/Task call to test-implementer whose prompt names a test runner or the Test command produces a candidate |
| I3 | harness maintainer | read the counts in the analytics dashboard's "harness hacking" section | `/api/summary` and `/api/runs/{id}` expose candidate counts and rows; the dashboard renders them |

# Scope
In scope: detection-only PreToolUse telemetry for Claude Code (`isolation_candidate` events), the shared detection module, importer field whitelist, analytics API section, dashboard card.
Out of scope: blocking or exit code 2 (issue #21); classifier (issue #22); worktree isolation (issue #23); transcript-based rules (literal copied from tool output, `path:line` in reports); Codex hooks; harness VERSION bump, installer migration, and SKILL.md wording (main does these outside this run).

# Paths
Implementation: harness/lib/isolation.py, harness/hooks/telemetry_hook.py, harness/hooks/hooks.spec.json, analytics/importer.py, analytics/app.py, analytics/frontend/src/App.jsx, analytics/frontend/src/hints.js, analytics/frontend/src/styles.css
Tests: tests/test_isolation_telemetry.py, analytics/tests/test_harness_hacking.py, analytics/frontend/src/HarnessHacking.test.jsx
Test command: .venv/bin/python -m pytest -q tests analytics/tests && cd analytics/frontend && npx vitest run
Review evidence: R1 — main runs the Test command and confirms pre-existing test files pass unmodified (`git diff --stat <base_commit> -- tests analytics/tests analytics/frontend/src/App.test.jsx` lists no pre-existing test file other than the `added` key set of `analytics/tests/test_classification_v4.py::test_q1_zero_pre_existing_summary_keys_change_value`, which registers `harness_hacking` and `isolation_candidates` as keys added after its base fixture).
Fuzzing: none — randomized payloads for the hook's no-crash property are covered by a Hypothesis test inside the Test command (O7); no separate fuzz surface.
Mutation tool: none

# Signatures
harness/lib/isolation.py: `RULES = ("test_reads_implementation", "test_runs_tests", "impl_reads_tests", "impl_runs_test_command", "dispatch_run_instruction")`
harness/lib/isolation.py: `EXCERPT_LIMIT = 500`
harness/lib/isolation.py: `detect(payload: dict, specs_dir: pathlib.Path, repo_root: pathlib.Path) -> list[dict]` — each dict has exactly the keys `rule`, `tool_name`, `match`, `match_kind`, `excerpt`; at most one dict per rule, ordered as in `RULES`.
harness/hooks/telemetry_hook.py: handles `hook_event_name == "PreToolUse"` by calling `isolation.detect(payload, PATHS.specs, REPO_ROOT)` and emitting `telemetry.emit(payload, "isolation_candidate", **candidate)` per result.
harness/hooks/hooks.spec.json: one `PreToolUse` entry, `targets: ["claude"]`, running `telemetry_hook.py`.
analytics: `/api/summary` and `/api/runs/{run_id}` responses gain key `harness_hacking`; each item of `/api/summary` `workflow.runs` gains key `isolation_candidates` (int).
analytics/frontend/src/App.jsx: a section with accessible name "Harness hacking" (`<section aria-label="Harness hacking">`) in the Workflow summary and in run detail.

# Functional Requirements
| id | requirement | priority | source |
| --- | --- | --- | --- |
| F1 | Active specs are the `*.md` files directly under `specs_dir` whose frontmatter `status:` is `active`. From each, the first line starting `Implementation:` and the first line starting `Tests:` give comma-separated paths (trimmed, empty items dropped); the first `Test command:` line gives the Test command (whitespace-normalized as `hook_shared.normalize`). Paths are repo-relative to `repo_root`. A spec path is a directory path when it ends with `/` or names an existing directory under `repo_root`. | must | user brief; SKILL.md Paths format |
| F2 | Reference strings per tool (`tool_input` keys): Read `file_path`; LS `path`; Glob `path`, `pattern`; Grep `path`, `glob`; Bash the tokens of `command` (shell-split, falling back to whitespace split when quoting is unbalanced). For every reference string the candidates are, in order: the string itself, the part before its first `:`, the part after its last `=`. Non-string values are ignored. | must | handoff caddy evidence (`sed -n 36,62p builtins.go`, `directives.go:4[5-9]...`) |
| F3 | A candidate is a **path** match for spec path P when, after resolving relative candidates against payload `cwd` (repo_root when `cwd` is absent or not a string) and normalizing (`os.path.normpath`; symlinks resolved on both sides), it equals P resolved against repo_root, or lies under P when P is a directory path. `match` is P as written in the spec. | must | I1 |
| F4 | When no candidate of a call path-matches, a candidate is a **basename** match when its last path component is non-empty and equals the last component of a spec path that is not a directory path. `match` is that spec path as written. Path matches take precedence over basename matches across all candidates of the call; otherwise the first match in candidate order wins. | must | I1; caddy `cd` + bare filename |
| F5 | Test runner invocation: the Bash command is split into segments at `&&`, `\|\|`, `;`, `\|`, and newlines. A segment runs a test runner when its tokens contain one of these consecutive token sequences, where the first token is compared by basename and `python` matches `python`, `python3`, `python3.N`: `pytest`; `py.test`; `python -m pytest`; `python -m unittest`; `go test`; `vitest`; `jest`; `npm test`; `npm run test` and `npm run test:<anything>`; `yarn test`; `pnpm test`; `cargo test`; `mvn test`; `gradle test`; `gradlew test`; `rspec`. A segment is excluded (collect/list form) when it contains `--collect-only`, `--co`, `-list` following `go test`, `list` immediately following `vitest`, `--listTests`, or `--no-run`. | must | handoff runner counts; test-implementer.md allowed load checks |
| F6 | Rules by payload `agent_type`: `test-implementer` → `test_reads_implementation` (F3/F4 against Implementation paths) and `test_runs_tests` (Bash only); `implementer` → `impl_reads_tests` (F3/F4 against Tests paths) and `impl_runs_test_command` (Bash only); empty or absent `agent_type` (main) → `dispatch_run_instruction` only; any other `agent_type` → no candidates. | must | I1, I2 |
| F7 | `test_runs_tests` fires with `match_kind: "test_command"` and `match` the Test command when the normalized Bash command contains an active spec's normalized Test command as a substring; otherwise with `match_kind: "runner"` and `match` the matched segment (whitespace-normalized) when F5 finds a non-excluded runner segment. `impl_runs_test_command` fires only on the Test command substring condition, with `match_kind: "test_command"`. | must | I1 |
| F8 | `dispatch_run_instruction` fires when `tool_name` is `Agent` or `Task`, `tool_input.subagent_type` is `test-implementer`, and `tool_input.prompt` (string) contains an active spec's normalized Test command (`match_kind: "test_command"`) or a non-excluded runner per F5 applied to the prompt with backticks removed (`match_kind: "runner"`, `match` the matched segment). It needs no active spec for the runner condition. | must | I2 |
| F9 | `match_kind` for path rules is `path` or `basename`. `excerpt` is the source text truncated to its first `EXCERPT_LIMIT` characters: Bash `command`; Read `file_path`; Grep/Glob/LS the compact JSON (`separators=(",", ":")`, keys sorted) of `tool_input`; for `dispatch_run_instruction` the prompt window starting `max(0, i - 200)` where `i` is the match start index in the prompt with backticks removed (for a runner match, the start of the matched segment), length `EXCERPT_LIMIT`. | must | user answer 1 (500 chars) |
| F10 | With no active spec, path rules and Test-command conditions never fire; runner conditions (F7 runner, F8 runner) still do. | must | F1 |
| F11 | The PreToolUse hook entry's matcher fully matches `Bash`, `Read`, `Grep`, `Glob`, `LS`, `Agent`, `Task` and does not fully match `Write`, `Edit`. Existing hook entries are unchanged. | must | I1 |
| F12 | The emitted telemetry line has `event: "isolation_candidate"`, the standard fields of `telemetry.emit` (including `agent_type`, `agent_id`, `session_id`, `tool_use_id`, `workflow_run_id`), and `rule`, `tool_name`, `match`, `match_kind`, `excerpt`. | must | I1 |
| F13 | The analytics importer keeps `rule`, `tool_name`, `match`, `match_kind`, `excerpt` from telemetry lines; other non-whitelisted fields stay dropped. | must | I3 |
| F14 | `harness_hacking` = `{"total": int, "by_rule": {each of the 5 rule ids: int, zero included}, "by_agent_type": {agent_type or "main": int}, "candidates": [...]}`. Candidates are `isolation_candidate` events, each `{ts, workflow_run_id, session_id, agent_type, rule, tool_name, match, match_kind, excerpt}`, newest `ts` first, at most 200 (counts cover all). In `/api/summary` it covers every imported candidate including those with null `workflow_run_id`; in `/api/runs/{id}` only that run's. `workflow.runs[*].isolation_candidates` counts that run's candidates. | must | I3 |
| F15 | The dashboard's Workflow summary and run detail each render a "Harness hacking" section showing the total (an element whose text is exactly `Total`, immediately followed by a sibling element containing the number), one count per rule id (an element whose text is the rule id, immediately followed by a sibling element containing the count), and a table with columns Time, Run, Agent, Rule, Match, Excerpt (Agent shows `main` for null). With zero candidates it shows "No isolation candidates recorded." When the response has no `harness_hacking` key, the section is not rendered and nothing else changes. | must | user answer 3 |

# Errors
Non-JSON stdin, non-dict `tool_input`, missing or non-string fields, unreadable or malformed spec, unwritable telemetry directory — PreToolUse hook exits 0 with empty stdout; no partial line is written; the tool call proceeds.
Spec without `Implementation:` / `Tests:` / `Test command:` lines — the missing part contributes nothing; other parts still apply.

# Cases
| id | level | input / state | expected result |
| --- | --- | --- | --- |
| C1 | normal | active spec Implementation `pkg/directives.go`; test-implementer Bash `sed -n 92,108p directives.go`, cwd `<repo>/pkg` | one `test_reads_implementation`, match_kind `path`, match `pkg/directives.go` |
| C2 | normal | same spec; test-implementer Bash `cd pkg && sed -n 1,5p directives.go`, cwd repo root | `test_reads_implementation`, match_kind `basename` |
| C3 | normal | test-implementer Bash `go test -race ./pkg/` | `test_runs_tests`, match_kind `runner` |
| C4 | normal | test-implementer Bash `pytest --collect-only -q tests/test_x.py` | no candidate |
| C5 | normal | implementer Read `tests/test_x.py` where Tests is `tests/` | `impl_reads_tests`, match_kind `path`, match `tests/` |
| C6 | normal | main Agent call, subagent_type `test-implementer`, prompt "... Run your tests with `python -m pytest tests -q` ..." | `dispatch_run_instruction`, match_kind `runner` |
| C7 | boundary | Bash command of 499, 500, 501 characters that fires a rule | excerpt lengths 499, 500, 500 |
| C8 | boundary | dispatch prompt with match at index 150 and at index 1000 | excerpt starts at 0 and at 800 |
| C9 | boundary | 201 candidate events imported | `total` 201, `candidates` length 200, newest first |
| C10 | error | stdin `not json` to the hook | exit 0, empty stdout, no telemetry line |
| C11 | edge | test-verifier Read of an Implementation path | no candidate |
| C12 | edge | no active spec (only a `draft` spec); test-implementer Read of a path listed in it; test-implementer Bash `npm test` | no path candidate; one `test_runs_tests` runner candidate |
| C13 | edge | test-implementer Bash `grep 'directives.go:4[5-9][0-9]' cover.out` | `test_reads_implementation` (part before `:`) |
| C14 | edge | test-implementer Bash command equal to `<Test command> -k foo` | `test_runs_tests`, match_kind `test_command` |

# Quality Applicability
| ISO/IEC 25010:2023 characteristic | applicable | rationale |
| --- | --- | --- |
| Functional suitability | yes | detection rules are the product |
| Performance efficiency | no | user accepted tens of ms per hook call (user answer 2) |
| Compatibility | yes | existing telemetry events, hooks, and analytics keys must keep working |
| Interaction capability | yes | dashboard section must be readable in KO/EN with an empty state |
| Reliability | yes | a PreToolUse hook that fails or prints can block every tool call |
| Security | yes | raw excerpts are new stored data; must stay local and bounded |
| Maintainability | yes | issue #21 blocking should reuse the detector without telemetry side effects |
| Flexibility | no | single client (Claude Code); Codex out of scope |
| Safety | no | no physical or human-safety surface |

# Quality Requirements
| id | characteristic / subcharacteristic | target and context | measure method / inputs / unit | threshold and direction | evidence: automated, review, mutation | source |
| --- | --- | --- | --- | --- | --- | --- |
| Q1 | Reliability / fault tolerance | installed PreToolUse hook under malformed input | share of inputs (C10 list in Errors plus ≥200 Hypothesis-generated payloads) with exit 0 and empty stdout | 100%, higher is better | automated O7 | Errors |
| Q2 | Compatibility / co-existence | pre-existing test suite and API keys | pre-existing tests pass unmodified (R1); pre-existing `/api/summary` keys still present | 100% | automated full Test command; review R1 | I3 |
| Q3 | Interaction capability / learnability | dashboard section | KO and EN hint text exists for the section title and each of the 5 rule ids; empty state text shown | all 6 hints in both languages | automated O9 | user answer 3 |
| Q4 | Security / confidentiality | stored excerpt | excerpt length over all emitted candidates; no network call in `isolation.py` or the hook path | ≤ 500 chars; 0 network imports | automated O4, O10 | user answer 1 |
| Q5 | Maintainability / reusability | `detect()` | files written and telemetry lines appended by calling `detect()` directly | 0 | automated O10 | #21 |

# Verification Obligations
| id | parent requirement/Case ids | variant and target surface | test layer and selection policy | ISO/IEC/IEEE 29119-4 technique | coverage items | coverage target | observation and expected result | evidence procedure |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| O1 | F2, F3, F4, C1, C2, C13 | `detect()` with a test-implementer payload against Implementation paths | unit; one case per item | equivalence partitioning | P1 Read relative path; P2 Read absolute path; P3 Bash token relative to `cwd`; P4 Bash bare basename (cwd elsewhere); P5 token with `:` suffix; P6 token `--x=path`; P7 file under a directory spec path; P8 Glob `pattern` basename; P9 Grep `path`; P10 LS `path`; P11 unrelated path → none; P12 path match preferred over an earlier basename candidate | 100% | returned list's rule, match_kind, match | tests/test_isolation_telemetry.py |
| O2 | F5, F7, C3, C4, C14 | `detect()` test-implementer Bash runner rule | unit; one case per item | equivalence partitioning | each of the 16 runner sequences in F5 (R1–R16); `python3.12 -m pytest` and `.venv/bin/python -m pytest`; each of the 6 exclusions (X1–X6); runner after `&&` in a later segment; Test command substring (C14) | 100% | presence/absence of `test_runs_tests`, match_kind | tests/test_isolation_telemetry.py |
| O3 | F6, F7, C5, C11 | `detect()` gating by agent_type | unit | decision table | agent_type {test-implementer, implementer, absent, "", test-verifier} × input {Implementation path read, Tests path read, runner command, Test command} — 20 rules | 100% | exact set of fired rules per cell | tests/test_isolation_telemetry.py |
| O4 | F8, F9, C6, C7, C8, Q4 | dispatch rule and excerpts | unit | boundary value analysis (2-value) + equivalence partitioning | subagent_type test-implementer vs implementer; prompt with runner / Test command / neither; tool_name Agent vs Task; excerpt lengths 499/500/501; window match index 199/200/1000; Read/Grep/Glob/LS excerpt format | 100% | rule presence; excerpt equality | tests/test_isolation_telemetry.py |
| O5 | F1, F10, C12 | active spec selection | unit | equivalence partitioning | no specs dir; draft only; one active; two active (union); spec missing `Tests:` line; directory path by trailing `/`; directory path by existing dir | 100% | fired rules | tests/test_isolation_telemetry.py |
| O6 | F11, F12 | installed hook in a temp repo (`InstallerTestCase` pattern, `HARNESS_TELEMETRY_DIR`) | integration; scenario | scenario testing | S1 test-implementer Read Implementation path → one line with all F12 fields; S2 call firing two rules → two lines in `RULES` order; S3 no-match call → no line; S4 matcher fullmatch list of F11 in generated `.claude/settings.json`; S5 existing `spec_gate.py` PreToolUse entry still present | 100% | telemetry jsonl lines; settings JSON | tests/test_isolation_telemetry.py |
| O7 | Errors, C10, Q1 | installed hook process | integration | error guessing + random testing | E1 non-JSON stdin; E2 `tool_input` list; E3 `command` int; E4 spec unreadable (directory named `x.md`); E5 telemetry dir is a file; E6 ≥200 Hypothesis payloads (seed fixed) to `detect()` and ≥20 to the hook process | none — experience-based for E1–E5; 100% of generated inputs for E6 | exit code 0, empty stdout, `detect()` never raises | tests/test_isolation_telemetry.py |
| O8 | F13, F14, C9 | analytics API via `create_app` + TestClient | integration | equivalence partitioning + boundary value analysis | A1 fields kept by importer; A2 non-whitelisted field still dropped; A3 by_rule has all 5 ids with zeros; A4 by_agent_type `main` for null; A5 null-run candidate in summary, absent from run detail; A6 run detail filtered; A7 `workflow.runs[*].isolation_candidates`; A8 200/201 cap and newest-first order | 100% | JSON response | analytics/tests/test_harness_hacking.py |
| O9 | F15, Q3 | dashboard component with mocked fetch | integration (jsdom) | scenario testing | U1 summary card total + per-rule counts + table row cells; U2 empty state text; U3 missing key → no section, other content intact; U4 run detail card; U5 KO hint text for title and each rule exists and differs from EN | 100% | rendered DOM, `HINTS` export | analytics/frontend/src/HarnessHacking.test.jsx |
| O10 | Q4, Q5 | `isolation.py` module and `detect()` | unit | error guessing | N1 calling `detect()` with an `HARNESS_TELEMETRY_DIR` temp dir writes no file anywhere under it or repo; N2 `isolation.py` source imports none of `socket`, `urllib`, `http`, `requests` | none — experience-based | filesystem state; import list via `ast` | tests/test_isolation_telemetry.py |

# Assumptions and Defaults
| id | decision | evidence and uncertainty | brief v<n> — approved / vetoed → <answer> / user answer |
| --- | --- | --- | --- |
| D1 | store raw excerpt, 500 chars | user answer 1 | user answer |
| D2 | detect at PreToolUse in telemetry_hook, not PostToolUse | PostToolUse can miss failing Bash calls (PostToolUseFailure path); user accepted latency | user answer (2) |
| D3 | include dashboard UI | user answer 3 | user answer |
| D4 | one event per fired rule, first match only | importer keeps scalars only; counts per rule are the target metric | brief v1 — approved |
| D5 | active spec = frontmatter `status: active` | SKILL.md lifecycle sets `active` at approval | brief v1 — approved |
| D6 | dispatch rule fires on runner names even inside negations ("do not run pytest") | string rules cannot read intent; classifier (#22) separates them; excerpt kept | brief v1 — approved |
| D7 | Grep/Glob/LS on a parent directory of Implementation (e.g. repo root) is not a match | otherwise every repo-wide search fires; Grep output content is not inspected | brief v1 — approved |
| D8 | models: implementer and test-implementer default (sonnet), test-verifier default | no task-specific reason to change | brief v1 — approved |

# Traceability
| requirement id | Case ids | obligation ids | evidence procedure |
| --- | --- | --- | --- |
| F1, F10 | C12 | O5 | tests/test_isolation_telemetry.py |
| F2, F3, F4 | C1, C2, C13 | O1 | tests/test_isolation_telemetry.py |
| F5, F7 | C3, C4, C14 | O2 | tests/test_isolation_telemetry.py |
| F6 | C5, C11 | O3 | tests/test_isolation_telemetry.py |
| F8, F9 | C6, C7, C8 | O4 | tests/test_isolation_telemetry.py |
| F11, F12 | C1 | O6 | tests/test_isolation_telemetry.py |
| F13, F14 | C9 | O8 | analytics/tests/test_harness_hacking.py |
| F15 | — | O9 | analytics/frontend/src/HarnessHacking.test.jsx |
| Q1 | C10 | O7 | tests/test_isolation_telemetry.py |
| Q2 | — | R1 | Test command + git diff |
| Q3 | — | O9 | HarnessHacking.test.jsx |
| Q4, Q5 | C7 | O4, O10 | tests/test_isolation_telemetry.py |

# Workflow Control
| item | value |
| --- | --- |
| correction batches used | 2 |
| verifier invocations | 2 |
| open finding ids | none |

Audit state (one entry per obligation; retain prior decisions in the execution ledger):
| obligation id | spec version | evidence references and revision | accepted / open / invalidated / pending | rationale and mutation outcome | dependencies and reopening evidence |
| --- | --- | --- | --- | --- | --- |
| O1 | 3 | tests/test_isolation_telemetry.py TestO1PathEquivalence (working tree, pre-commit) | accepted | verifier 1; advisory A1 (Grep glob / Glob path keys) added in batch 2, verifier 2 retained | — |
| O2 | 3 | tests/test_isolation_telemetry.py TestO2RunnerRule (working tree, pre-commit) | accepted | verifier 1; advisory A2 (`pytest --cov` fires) added in batch 2, verifier 2 retained | — |
| O3 | 3 | tests/test_isolation_telemetry.py TestO3DecisionTable (working tree, pre-commit) | accepted | verifier 1 | — |
| O4 | 3 | tests/test_isolation_telemetry.py TestO4DispatchAndExcerpts (working tree, pre-commit) | accepted | F-O4-1 runner-match window index untested (runner prompts <200 chars); F-O4-2 truncation boundary only for Bash; closed in batch 2, verifier 2 pass | — |
| O5 | 3 | tests/test_isolation_telemetry.py TestO5SpecSelection (working tree, pre-commit) | accepted | verifier 1 | — |
| O6 | 3 | tests/test_isolation_telemetry.py TestO6HookScenarios (working tree, pre-commit) | accepted | verifier 1 | — |
| O7 | 3 | tests/test_isolation_telemetry.py TestO7ErrorGuessingAndRandom (working tree, pre-commit) | accepted | verifier 1 | — |
| O8 | 3 | analytics/tests/test_harness_hacking.py HarnessHackingApiTests (working tree, pre-commit) | accepted | verifier 1 | — |
| O9 | 3 | analytics/frontend/src/HarnessHacking.test.jsx (working tree, pre-commit) | accepted | F-O9-1 v3 DOM shape not asserted; confirmed: relabelling Total→'Total candidates' leaves 8/8 passing; closed in batch 2, verifier 2 pass | — |
| O10 | 3 | tests/test_isolation_telemetry.py TestO10SideEffectFreeAndOffline (working tree, pre-commit) | accepted | verifier 1 | — |
| R1 | 3 | git diff --stat 58045c7 -- tests analytics/tests analytics/frontend/src/App.test.jsx → only test_classification_v4.py added-set (working tree, pre-commit) | accepted | verifier 1 on diff-stat | — |

Execution ledger (append attempts; preserve failed approaches):
| attempt | finding / failure signature | cause hypothesis | changed approach / new evidence | result / disposition |
| --- | --- | --- | --- | --- |
| 1 | Test command: py 1190 passed; vitest 3 failed (U1, U2, U4) `Unable to find an element with the text: /total/i` | spec gap: F15 named no label/locator for the total; implementation rendered an unlabelled number in the card head; test-implementer reported this as an intent-gap challenge | v3 fixes the total and per-rule count DOM shape in F15; implementer correction batch 1 | Test command green: py 1190 passed, vitest 27 passed; R1 diff shows only the v2-permitted change |
| 3 | verifier 2 | — | — | pass; F-O9-1, F-O4-1, F-O4-2 closed; no open findings |
| 2 | verifier 1 retry: F-O9-1, F-O4-1, F-O4-2 | evidence gaps: tests written before v3; long-input cases absent | test-implementer correction batch 2 with behavior-level gaps + advisories A1, A2 | Test command green (py 1195, vitest 27) after 0.32.0 bump; probes killed by intended assertions: Total relabel (U1/U2), count not sibling (U1/U2), runner-token window index (line 409), Read untruncated (501≠500), Grep glob ignored (A1), --co prefix (A2) |
| H | hand mutations M1–M10 (cwd ignored; no symlink resolution; basename beats path; exclusions dropped; implementer gets runner rule; window i-199; index before backtick removal; no truncation; cap applied to total; matcher misses LS) | strongest defect classes from test-implementer and verifier proposals | each injected singly, new test files run, restored via seed.py | 10/10 killed by intended assertions (P3, P10, P12, per-segment exclusion, O3 table, backtick window, excerpt equality, 501≠500, A8, S4) |
| 0 | implementer challenge: pre-existing coexistence test fails on new keys | test's `added` set predates the keys | v2 R1 amendment; main registered the keys | resolved (py suite green) |

# Version Log
## v1
- Initial draft from handoff item 3 and user answers (excerpt 500 chars, latency accepted, UI included).

## v2
- Contract-only: R1 permits registering the two new response keys in the coexistence test's `added` set. Evidence: implementer challenge — that test compares the current summary with a base-commit summary and strips only previously registered added keys, so the Signature-required `isolation_candidates` (and `harness_hacking`) keys fail it. Precedent: the 0.17.0 mutation keys were registered the same way. Pre-existing key values are still compared unchanged.
## v3
- [spec gap] F15 states the DOM shape of the total (`Total` label + sibling number) and per-rule counts (rule id label + sibling count). Evidence: execution ledger attempt 1. Runner-match excerpt index `i` clarified as the matched segment's start in the backtick-stripped prompt (both roles read it this way).

# Retrospective
## 2026-10-25
| observation | evidence | how to re-check |
| --- | --- | --- |
| The Test command depends on `.venv`: system python3 lacks fastapi, pytest, and hypothesis, and `analytics/frontend` needs `npm ci` before vitest runs | `python3 -c "import fastapi"` raised ModuleNotFoundError in this worktree | `.venv/bin/python -m pytest --version`; `ls analytics/frontend/node_modules` |
| A harness version bump also requires raising the `"y\n" * N` answer counts in installer-driven tests; the two c20 tests in `tests/test_telemetry.py` had spare answers through 0.31.0 but needed +1 at 0.32.0 | after the 0.32.0 bump those tests failed with EOFError; `* 15` passed | `grep -n '"y\\n' tests/test_installer.py tests/test_telemetry.py` |
| Adding a key to `/api/summary` (top level or `workflow.runs` items) fails `analytics/tests/test_classification_v4.py::test_q1_zero_pre_existing_summary_keys_change_value` until the key is in its `added` set | implementer challenge in this run; v2 Version Log | run that test after adding a key |

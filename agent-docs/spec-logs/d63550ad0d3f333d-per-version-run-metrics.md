---
version: 4
run_id: d63550ad0d3f333d
status: complete
base_commit: 4551d02711f31995146dfc3d443745a531f5cce0
max_verifier_invocations: 2
handoff: agent-docs/handoff/stale/3cb41f5d6d74d413-per-version-run-metrics.md
---

# User Intent
| id | stakeholder | intention | observable goal |
| --- | --- | --- | --- |
| I1 | harness maintainer | compare harness versions without raw transcripts (issue #10) | per-session metrics tagged with harness_version are persisted at run time in the telemetry JSONL and can be summarized per (harness_version, repo) |

# Scope
In scope: per-session counters updated by the Claude PostToolUse telemetry hook; a `session_metrics` event emitted at SessionEnd; flushing orphaned session state at the next SessionStart; shell-write heuristic classification; an analytics summarizer by version and repo; hook matcher changes; VERSION 0.24.0 with an `update` migration entry.
Out of scope: cost; retroactive transcript analysis; Codex hooks; analytics UI/frontend; changes to existing event types.

# Paths
Implementation: harness/lib/session_metrics.py, harness/lib/telemetry.py, harness/hooks/telemetry_hook.py, harness/hooks/session_lock.py, harness/hooks/hooks.spec.json, harness/VERSION, installer/harness.py, analytics/version_metrics.py
Tests: tests/test_session_metrics.py, analytics/tests/test_version_metrics.py, tests/test_installer.py, tests/test_telemetry.py, tests/test_workflow_markers.py, analytics/tests/test_server.py
Test command: uv run --with pytest --with pytest-cov --with hypothesis --with-requirements analytics/requirements.txt python -m pytest tests analytics/tests -q -p no:cacheprovider --deselect tests/test_test_scan_rules.py::test_name --deselect analytics/tests/test_server.py::ProductionServerTests::test_v6_a3_package_relative_and_home_defaults_serve_with_only_port_override --cov=session_metrics --cov=analytics.version_metrics --cov-branch --cov-report=term-missing --cov-fail-under=85
Review evidence: RE1 — main runs `python3 installer/harness.py update .` then `python3 installer/harness.py doctor .`, and records the generated `.claude/settings.json` PostToolUse matcher and SessionEnd/SessionStart entries.
Fuzzing: none — classifier robustness is covered by a hypothesis property test (O9) inside the Test command, seed fixed via `@seed(10)`, max_examples 500.
Mutation tool: none — mutmut is not installed and its config does not fit the harness/lib sys.path layout; hand mutations (8–10) supply mutation evidence.

# Signatures
harness/lib/session_metrics.py: classify_path(path: str, repo_root: Path) -> "code" | "noncode"
harness/lib/session_metrics.py: classify_tool(tool_name: str, tool_input: dict, repo_root: Path) -> list[tuple[str, str | None]]  # kinds: "explore", "code_write", "noncode_write", "unclassified_shell_write"
harness/lib/session_metrics.py: record(payload: dict) -> None
harness/lib/session_metrics.py: flush(payload: dict, ended_cleanly: bool) -> None
harness/lib/session_metrics.py: flush_orphans(current_session_id: str | None) -> None
harness/hooks/telemetry_hook.py: CLI `telemetry_hook.py` (stdin PostToolUse/PostToolUseFailure/SessionEnd payload)
analytics/version_metrics.py: summarize(events: list[dict]) -> list[dict]

# Functional Requirements
| id | requirement | priority | source |
| --- | --- | --- | --- |
| F1 | classify_path returns "code" iff the extension (case-insensitive) is in {.py .js .ts .tsx .jsx .go .rs .java .kt .c .cc .cpp .h .hpp .rb .php .swift .cs .scala .sh} AND the repo-relative path does not start with agent-docs/, .harness/, .claude/, .codex/, .agents/; paths outside repo_root are classified by extension only | must | understanding round Q3 |
| F2 | classify_tool: Read, Grep, Glob, LS → [("explore", None)]; Write/Edit/NotebookEdit → one write of classify_path(file_path or notebook_path); missing path → [] | must | plan §2 |
| F3 | classify_tool Bash: targets of `>`, `>>`, `tee [-a] FILE`, `sed -i[SUFFIX] ... FILE` (last non-option token) each yield a write classified by F1; `/dev/null` and `&>`/`2>` to /dev/null are ignored; a command with no such target but containing `python -c`, `python3 -c`, `node -e`, `perl -i`, `perl -e`, `ruby -e`, or a heredoc (`<<`) yields [("unclassified_shell_write", None)]; any other Bash yields [("explore", None)] | must | user decision |
| F4 | record(payload) increments per-session counters in a state file under the telemetry directory keyed by session_id: exploration_before_code, noncode_writes_before_code (only before the first code write), code_writes, unclassified_shell_writes, tool_calls (one per hook invocation, regardless of how many write targets a Bash command yields; code_writes, noncode_writes and unclassified_shell_writes count each yielded item); and adds the active workflow_run_id (telemetry.active_workflow) to a de-duplicated run id list; payload without session_id is ignored | must | plan §1 |
| F5 | On SessionEnd the hook emits exactly one `session_metrics` telemetry event (through telemetry's normal emit, so harness_version, repo, client, session_id are present) with fields exploration_before_code, noncode_writes_before_code, code_writes, unclassified_shell_writes, tool_calls, first_code_write (bool), workflow_run_ids (list), ended_cleanly=true, then deletes the state file; a session with no state file emits nothing | must | plan §4 |
| F6 | On SessionStart, state files of other sessions are flushed as `session_metrics` with ended_cleanly=false, using the session_id recorded in the state file, then deleted | must | understanding round Q2 |
| F7 | Existing events (spec_write, handoff_write, test_command, seed, tool_failure) are emitted unchanged | must | plan |
| F8 | hooks.spec.json Claude PostToolUse matcher becomes `Bash|Write|Edit|NotebookEdit|Read|Grep|Glob|LS`; SessionEnd runs telemetry_hook.py; SessionStart orphan flush runs from session_lock.py (no new stdout) | must | understanding round Q1 |
| F9 | summarize(events) groups `session_metrics` events by (harness_version, repo) and returns rows sorted by (repo, harness_version) with: harness_version, repo, sessions, sessions_with_code_write, median_exploration_before_code (over sessions with first_code_write true; null if none), median_noncode_writes_before_code (same subset), total_unclassified_shell_writes; other events are ignored; a session_metrics event whose counter is missing, bool, or non-int, or whose first_code_write is not bool, is skipped entirely (not counted in sessions) | must | I1 |
| F10 | harness/VERSION = 0.24.0 and installer MIGRATIONS has a 0.24.0 entry "record per-session run metrics in telemetry" whose function returns a non-empty step list | must | AGENTS.md |

# Errors
- Hook stdin is invalid JSON or any internal exception — exit code 0, empty stdout, no traceback on stdout — no telemetry or state change beyond what already succeeded.
- State file unreadable/corrupt JSON — treated as empty state and overwritten on the next record; flush of a corrupt file deletes it and emits nothing — no crash.
- Telemetry directory unwritable — record/flush silently do nothing — exit 0.

# Cases
| id | level | input / state | expected result |
| --- | --- | --- | --- |
| C1 | normal | session: Read, Grep, Write README.md, Edit src/a.py, Read; SessionEnd | session_metrics: exploration_before_code=2, noncode_writes_before_code=1, code_writes=1, tool_calls=5, first_code_write=true, ended_cleanly=true |
| C2 | normal | Bash `echo x > src/b.py` | code write |
| C3 | boundary | path `agent-docs/x.py`, `.harness/hooks/y.py`, `harness/hooks/y.py`, `SRC/A.PY` | noncode, noncode, code, code |
| C4 | edge | Bash `ls > /dev/null`, `cat a 2>/dev/null` | explore |
| C5 | edge | Bash `python3 -c "open('a.py','w')"` and `cat <<EOF > notes.md` | unclassified_shell_write; the heredoc with a `>` target notes.md yields noncode_write (target rule takes priority) |
| C6 | error | invalid JSON on stdin; corrupt state file | exit 0, empty stdout; no crash |
| C7 | normal | session A has state, session B SessionStart | one session_metrics for A with ended_cleanly=false; A's state removed; nothing for B |
| C8 | normal | events from versions 0.23.0 and 0.24.0 in repo r | two summarize rows with correct medians |
| C9 | boundary | session with no code write | first_code_write=false; excluded from medians; counted in sessions |
| C10 | edge | `sed -i.bak 's/a/b/' x.go`, `tee -a log.txt` | code write; noncode write |

# Quality Applicability
| ISO/IEC 25010:2023 characteristic | applicable | rationale |
| --- | --- | --- |
| Functional suitability | yes | metric correctness is the goal |
| Performance efficiency | yes | hook now runs on every Read/Grep/Glob |
| Compatibility | yes | existing events and installer update must keep working |
| Interaction capability | no | no user interface |
| Reliability | yes | hook must never break the agent's tool loop |
| Security | no | no new trust boundary; data stays in the existing local telemetry dir |
| Maintainability | yes | classifier isolated and covered |
| Flexibility | no | single platform behavior, no portability change |
| Safety | no | no physical/harmful effect |

# Quality Requirements
| id | characteristic / subcharacteristic | target and context | measure method / inputs / unit | threshold and direction | evidence: automated, review, mutation | source |
| --- | --- | --- | --- | --- | --- | --- |
| Q1 | Performance / time behaviour | telemetry_hook.py on a Read payload, installed repo | median wall time of 20 subprocess runs, ms | ≤ 250 ms | automated O10 | default D2 |
| Q2 | Reliability / fault tolerance | hook under C6 inputs | exit code and stdout | exit 0 and empty stdout, 100% | automated O7 | U5 invariant |
| Q3 | Compatibility / co-existence | existing telemetry tests | tests/test_telemetry.py pass | all pass | automated (Test command) | F7 |
| Q4 | Maintainability / testability | harness/lib/session_metrics.py + analytics.version_metrics | branch coverage % | ≥ 85% | automated (Test command) | default D3 |

# Verification Obligations
| id | parent requirement/Case ids | variant and target surface | test layer and selection policy | ISO/IEC/IEEE 29119-4 technique | coverage items | coverage target | observation and expected result | evidence procedure |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| O1 | F1, C3 | classify_path | unit | equivalence partitioning | P1 code ext in repo, P2 noncode ext, P3 each excluded prefix (5), P4 uppercase ext, P5 outside repo code ext, P6 no extension | 100% | return value equals F1 | pytest |
| O2 | F2 | classify_tool non-Bash | unit | equivalence partitioning | Read, Grep, Glob, LS, Write, Edit, NotebookEdit, Write without path, unknown tool (→ []) | 100% | list equals F2 | pytest |
| O3 | F3, C2, C4, C5, C10 | classify_tool Bash | unit | syntax testing | `>`, `>>`, `tee`, `tee -a`, `sed -i`, `sed -i.bak`, `/dev/null`, `2>/dev/null`, each interpreter marker (7), heredoc without target, heredoc with target, plain command | 100% | kinds per F3 | pytest |
| O4 | F4, F5, C1, C9 | hook subprocess, installed repo, HARNESS_TELEMETRY_DIR | integration | scenario testing | C1 sequence, C9 sequence, write before any explore, run id de-dup with active workflow | 100% | session_metrics fields exact; state file removed | pytest |
| O5 | F6, C7 | session_lock.py SessionStart | integration | state transition | orphan→flushed, own session untouched, no state→nothing | 100% | events + files | pytest |
| O6 | F7 | existing events | integration | scenario testing | spec_write, test_command still emitted once alongside counting | 100% | event present once | pytest |
| O7 | Errors, C6, Q2 | hook | integration | error guessing | invalid JSON, corrupt state file, unwritable telemetry dir, missing session_id | none — experience-based | exit 0, empty stdout | pytest |
| O8 | F9, C8, C9 | summarize | unit | equivalence partitioning + boundary value analysis (2-value) | two versions, even/odd count median, zero code-write sessions (null), malformed counter skipped, non-session events ignored | 100% | rows equal hand-computed | pytest |
| O9 | F3, Errors | classify_tool Bash arbitrary strings | unit | random testing | hypothesis text strategy, seed 10, 500 examples | none — property | never raises; kinds ⊆ allowed set | pytest |
| O10 | Q1 | hook Read payload | integration | boundary value analysis | 20 runs median | 100% | ≤ 250 ms | pytest |
| O12 | F10, Q3 | existing version-pinned tests (installer update migration lists, manifest/VERSION pins, telemetry/markers envelope version, analytics server) | integration | equivalence partitioning | each currently pinned 0.23.0 expectation updated to include 0.24.0 as in commit def8bcb precedent; update tests answering migration prompts supply enough confirmations for the added 0.24.0 migration | 100% | all pass | Test command |
| O11 | F8, F10 | hooks.spec.json, VERSION, installer | integration | equivalence partitioning | matcher string, SessionEnd entry, VERSION value, 0.24.0 migration present & non-empty, install into temp repo produces settings with matcher | 100% | equality | pytest + RE1 |

# Assumptions and Defaults
| id | decision | evidence and uncertainty | brief v<n> — approved / vetoed → <answer> / user answer |
| --- | --- | --- | --- |
| D1 | hook covers Read/Grep/Glob/LS; orphan flush with ended_cleanly=false; extension list as F1 | understanding round | user answer |
| D2 | Q1 threshold 250 ms median | python startup ~50 ms + IO; uncertain on slow disks | brief v1 — approved |
| D3 | coverage ≥ 85% branch | matches prior analytics spec | brief v1 — approved |
| D4 | subagent tool calls (same session_id) are counted in the parent session | Claude Code shares session_id with subagents; exploration by explorers is part of the run | brief v1 — approved |
| D5 | analytics exposes a pure summarize function only; no UI | UI out of scope keeps change small | brief v1 — approved |
| D6 | no fuzz harness / mutation tool; hypothesis property + hand mutations | tools absent | brief v1 — approved |

# Traceability
| requirement id | Case ids | obligation ids | evidence procedure |
| --- | --- | --- | --- |
| F1 | C3 | O1 | pytest |
| F2 | — | O2 | pytest |
| F3 | C2, C4, C5, C10 | O3, O9 | pytest |
| F4, F5 | C1, C9 | O4 | pytest |
| F6 | C7 | O5 | pytest |
| F7 | — | O6 | pytest |
| F8, F10 | — | O11, O12 | pytest, RE1 |
| F9 | C8, C9 | O8 | pytest |
| Q1 | — | O10 | pytest |
| Q2 | C6 | O7 | pytest |

# Workflow Control
| item | value |
| --- | --- |
| correction batches used | 2 |
| verifier invocations | 2 |
| open finding ids | none |

Audit state (one entry per obligation; retain prior decisions in the execution ledger):
| obligation id | spec version | evidence references and revision | accepted / open / invalidated / pending | rationale and mutation outcome | dependencies and reopening evidence |
| --- | --- | --- | --- | --- | --- |
| O1–O12 | 4 | Test command rc 0 (839 passed), cov 93%, RE1 | accepted | verifier r2 pass; 11/11 hand mutations detected | — |

Execution ledger (append attempts; preserve failed approaches):
| attempt | finding / failure signature | cause hypothesis | changed approach / new evidence | result / disposition |
| --- | --- | --- | --- | --- |
| 1 | 31 failures in pre-existing tests pinned to 0.23.0 / migration lists; coverage 61% over all harness/lib; pre-existing collection ERROR tests/test_test_scan_rules.py::test_name | verified: version bump pins (def8bcb updated the same tests); harness/lib modules other than session_metrics run only via subprocess; test_name is a helper collected by pytest, unchanged since base | v2: add pinned tests to Tests paths (O12), narrow coverage to new modules, deselect helper | test defect → correction batch 1 |
| 2 | after batch 1: 785 passed, 1 failed test_v6_a3 `frontend build is unavailable` | verified: worktree has no analytics/frontend/dist (untracked build output); test and analytics server unchanged by this run | v3 deselect with reason | environmental, not in scope |
| 3 | verifier r1 retry: E1 no ≥2 code/unclassified writes (cap mutants escape); E2 orphan session_id from filename / run ids not checked; E3 SessionStart stdout unchecked; S1 F9 malformed scope ambiguous | evidence gaps; S1 spec ambiguity | v4 clarifies F9 and F4 tool_calls; tests strengthened | correction batch 2 |
| 4 | batch 2 new E2 tests failed: session_id >~100 chars dropped (no state file) | verified: state filename exceeded NAME_MAX | implementation: filename = sanitized 32-char prefix + sha256[:16]; Test command rc 0, 839 passed, cov 93% | implementation defect fixed |
| 5 | hand mutations M1–M11 (code_writes cap, explore/noncode after code, prefix boundary, marker vs target priority, sed operand, run id dedup, orphan own-session, orphan id, median subset, unclassified after code), both lib copies, seed backup/restore | strongest: one per counter rule, classifier priority, orphan identity and summarize subset (verifier r1 list) | 11/11 detected by intended assertions; restore ok | accepted |
| 6 | RE1: update/doctor rc 0; settings PostToolUse matcher Bash|Write|Edit|NotebookEdit|Read|Grep|Glob|LS; SessionEnd runs telemetry_hook.py | — | recorded | accepted |

# Version Log
## v4
- Contract clarification after verifier r1 (S1): F9 malformed-event skip scope; F4 per-invocation tool_calls vs per-item write counts. Matches the interpretation already given to test roles.
## v3
- Contract-only: deselect test_v6_a3, which requires a built analytics/frontend/dist absent from this worktree and untouched by this change.
## v2
- Contract-only: Test command coverage scope narrowed to new modules and pre-existing helper deselected; O12 added for version-pinned existing tests (evidence: first Test command run).
## v1
- Initial spec from handoff 3cb41f5d6d74d413 and understanding round answers.

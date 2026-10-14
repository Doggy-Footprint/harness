---
version: 3
run_id: e4d852bdd61ccf5b
status: complete
base_commit: 77eb3d523c8f9ec6be2e2bbae4e60aa7f22ac250
max_verifier_invocations: 2
handoff: agent-docs/handoff/bf0d1dd85535bb18-selfcheck-informed-brief-review.md
---

# User Intent
| id | stakeholder | intention | observable goal |
| --- | --- | --- | --- |
| UI1 | harness maintainer | "하네스가 제공한 구현 사항에 대해 brief를 읽고 정답을 아는 상태에서 검증해주는 절차를 추가한다." — stage 1: post-run diagnosis only | after a run, each harness entry has a `review.json` stating per category whether the briefs/spec diverged from gold, with citations |
| UI2 | harness maintainer | the diagnosis must not bias or alter the measured run | `process.json`, `scores.harness.jsonl`, `prediction.json` and all PC verdicts are byte-identical before and after review |
| UI3 | harness maintainer | false factual claims by the harness-run agent are visible | report shows a separate "false claims" table (user answer to Ask 3) |

# Scope
In scope: new module `selfcheck/review.py`; new CLI subcommand `review`; `report.build`/`render_markdown` showing review results; tests.
Out of scope: changing run, driver, user simulator, scoring, PC checks, fixture comparability (`manifest.py`, `fixture.py`); wiring review into `check` automatically; in-loop reviewer (stage 3); PC8/`--repeats` (stage 2); live harness runs; the live review of `a41e64cb9bbbef03` is run by main after completion with user confirmation (not part of the Test command).

# Paths
Implementation: selfcheck/review.py, selfcheck/report.py, selfcheck/__main__.py, selfcheck/config.json
Tests: selfcheck/tests/test_report.py, selfcheck/tests/test_review.py, selfcheck/tests/test_report_review.py, selfcheck/tests/test_cli_review.py, selfcheck/tests/review_fakes.py
Test command: uv run --python 3.12 --with-requirements selfcheck/requirements.txt --with coverage==7.16.2 sh -c 'export COVERAGE_FILE="$HOME/.harness/selfcheck/.coverage-review" && mkdir -p "$HOME/.harness/selfcheck" && python -m coverage run --branch --source=selfcheck,analytics -m unittest discover -s selfcheck/tests -t . && python -m coverage report --fail-under=90 --include="selfcheck/review.py,selfcheck/report.py"'
Review evidence: R1 — main runs `python3 -m selfcheck review a41e64cb9bbbef03` and `report a41e64cb9bbbef03 --no-baseline` after completion (user-confirmed), compares `review.json` to the handoff reference findings, and records the sha256 of `process.json`, `prediction.json`, `scores.harness.jsonl` before/after in the execution ledger.
Fuzzing: none — inputs are run artifacts written by our own driver and model output already validated by schema checks (C-error rows); no external party controls them.
Mutation tool: mutmut 2.5.1 over Implementation lines changed since base_commit in `selfcheck/review.py`, `selfcheck/report.py`, `selfcheck/__main__.py`, runner `python -m unittest discover -s selfcheck/tests -t .`, sample cap 150, seed 1, survival threshold 40%.

# Signatures
review.CATEGORIES = ("understanding", "ask_options", "recommendation_evidence", "spec_requirements")
review.VERDICTS = ("diverged", "consistent", "n/a")
review.extract_briefs(entry_dir: Path) -> list[dict]  # each {"file": str, "line": int, "kind": "text"|"ask", "text": str}
review.load_spec(entry_dir: Path) -> dict | None  # {"source": "spec-logs"|"specs", "text": str}
review.build_prompt(instance: dict, briefs: list[dict], spec: dict | None) -> str
review.parse_review(text: str) -> dict  # raises review.ReviewFormatError
review.review_entry(entry_dir: Path, instance: dict, *, call_fn, token: str, model: str | None = None, effort: str | None = None) -> dict  # writes entry_dir/review.json, returns it
review.claude_call(prompt: str, *, model: str, effort: str, timeout_s: int) -> str
report.build(run_dir, *, fixture_dir, scores, processes, min_mutants, reviews: dict | None = None) -> dict
CLI: python3 -m selfcheck review <run_id> [--instances a,b]

# Functional Requirements
| id | requirement | priority | source |
| --- | --- | --- | --- |
| FR1 | `extract_briefs` reads every `raw/claude/projects/-testbed/*.jsonl` file directly under that directory (main transcripts; `subagents/` excluded) and returns, in file then line order, one item per main-thread (`isSidechain` false) assistant message: `kind: "text"` for each text block (joined text of the message) and `kind: "ask"` for each `AskUserQuestion` tool_use (text = JSON of its `questions` input). `file` is the path relative to `entry_dir`, `line` the 1-based JSONL line. Malformed lines are skipped. | must | handoff Next Step 1 |
| FR2 | `load_spec` returns the spec added in `raw/full.diff` for the run id of the first `workflow_start` telemetry event, reusing `process._spec_text` and the same event loading as `process.evaluate_entry`; `None` when absent. | must | handoff Next Step 1 |
| FR3 | `build_prompt` includes the issue (`problem_statement`), gold `patch`, gold `test_patch`, `FAIL_TO_PASS`, every brief item as one block `[<file>:<line>] (<kind>) <text>`, and the spec text prefixed `[spec]` (or a statement that no spec exists); it states the four categories, the verdict vocabulary, that each finding must cite a given `[file:line]` or `[spec]` location, and that `false_claim` is true only for factual claims checkable against the base repository, gold patch or gold tests that are false — never for opinions or recommendations; it requests a single JSON object as output. | must | handoff Next Step 2; user answer Ask 3 |
| FR4 | `parse_review` accepts the model text, extracting the first top-level JSON object (also inside a ```json fence), and returns (the model JSON must use this wrapped form) `{"categories": {cat: {"verdict": v, "findings": [{"summary": str, "citation": str, "false_claim": bool}]}}}` with exactly the four categories; a `diverged` category must have ≥1 finding; anything else raises `ReviewFormatError`. | must | user answer Ask 2 |
| FR5 | `review_entry` builds the prompt, calls `call_fn(prompt)`, parses, and writes `review.json` = `{"status": "ok", "instance_id", "model" (the `model` argument), "effort" (the `effort` argument), "categories", "false_claims": [findings with false_claim true, each with its category]}`. On `ReviewFormatError`, any exception from `call_fn`, or a missing transcript directory it writes `{"status": "error", "instance_id", "error": <one-line reason>}` and returns it without raising. It never writes any other file and never modifies existing run files. | must | handoff Next Step 3 |
| FR6 | If `token` (non-empty) occurs in the serialized review, `review.json` is not written and the returned dict is the error form with error `"token found in review output"`. | must | existing `report.write` invariant |
| FR7 | `claude_call` runs the host `claude` CLI: `claude -p --model <model> --effort <effort> --output-format text` with the prompt on stdin, no tools (`--tools ""`), timeout `timeout_s`; non-zero exit or timeout raises `RuntimeError`. Model/effort/timeout come from new `config.json` key `review: {"model": "claude-opus-5-5", "effort": "low", "timeout_s": 900}`. | must | user answer Ask 1 |
| FR8 | CLI `review <run_id>`: unknown run → exit 2 with `unknown run id`; for each harness entry (optionally filtered by `--instances`) with an existing entry dir and a pool row, calls `review_entry` with `claude_call` and prints `<iid> <status>`; exit 1 if any entry status is error, else 0. It does not touch scores/process files. | must | handoff Next Step 3 |
| FR9 | `report.build` gains `reviews` (`{iid: review dict}`; only `None` (not `{}`) → loaded from `<run_dir>/<iid>/harness/review.json` if present). Each instance gets `"review"`: the category verdicts dict and `"review_findings"`: `{category: [findings]}` (empty dict when not ok), or `"error: <reason>"`, or `"not run"`. Report top level gets `"false_claims"`: list of `{instance_id, category, summary, citation}`. `render_markdown` adds per instance a `| category | verdict | findings |` table (findings cell: `summary [citation]` joined by `; `, or `none`; a citation already enclosed in `[...]` is not bracketed again) (or the error/not run line) and, at the end before notes, a `## false claims` section with a table, or `none` when empty. Existing report fields and metrics are unchanged; the closed-set report-key test in `test_report.py` is updated to admit `false_claims` (top level) and `review`, `review_findings` (instance). | must | handoff Next Step 3; user answer Ask 3 |
| FR10 | `_emit_report` passes reviews loaded from the run dir; existing `report.write` token refusal still covers the new content. | must | FR9 |

# Errors
- transcript dir missing, or no brief items extracted from it — `review.json` status error "no transcript" — no model call made, run files unchanged.
- model output not valid JSON or schema violation — status error with reason — run files unchanged.
- `call_fn` raises (CLI failure, timeout) — status error with exception message (first line) — run files unchanged.
- token in output — status error "token found in review output", `review.json` not written.
- unknown run id (CLI) — exit 2, stderr `unknown run id: <id>` — nothing written.
- malformed `review.json` when reporting — instance review shown as `"error: unreadable review.json"`.

# Cases
| id | level | input / state | expected result |
| --- | --- | --- | --- |
| C1 | normal | transcript with 2 main text messages, 1 AskUserQuestion, 1 sidechain message, a `subagents/` file | 3 items in order, sidechain and subagents excluded, correct file/line |
| C2 | edge | malformed JSONL line, user messages, assistant message with only tool_use (non-Ask) or thinking | skipped |
| C3 | normal | diff with spec in spec-logs for run id | `load_spec` returns source and text; no spec → None |
| C4 | normal | valid model JSON (plain and fenced, with prose around) | parsed dict |
| C5 | error | missing category, unknown verdict, diverged with 0 findings, non-bool false_claim, no JSON | `ReviewFormatError` |
| C6 | normal | `review_entry` with fake call_fn returning valid JSON including one false_claim | review.json status ok, false_claims list of 1 with category |
| C7 | error | call_fn raises / returns garbage / no transcript dir | status error written, no exception, other files unchanged (hash) |
| C8 | error | token in model output | no review.json, error returned |
| C9 | normal | report with reviews for one instance, missing for another, error for a third | verdict table / "not run" / error line; false claims section |
| C10 | boundary | no false claims across instances | `## false claims` section says `none`; `false_claims` empty list |
| C11 | normal | CLI review ok / unknown run / one error entry / --instances filter | exit 0 / 2 / 1; only filtered entries reviewed |
| C12 | normal | prompt content | contains issue, gold patch, test_patch, F2P ids, `[file:line]` prefixes, `[spec]`, the four categories, false_claim rule |

# Quality Applicability
| ISO/IEC 25010:2023 characteristic | applicable | rationale |
| --- | --- | --- |
| Functional suitability | yes | review content and report |
| Performance efficiency | no | one CLI call per entry; cost bounded by user-run command |
| Compatibility | yes | must coexist with existing report/process outputs without changing them |
| Interaction capability | no | CLI output follows existing subcommand style; covered by FR8 |
| Reliability | yes | a failing model call must not abort other entries |
| Security | yes | OAuth token must not leak into outputs |
| Maintainability | yes | existing suite must stay green; coverage |
| Flexibility | no | single runner by user decision |
| Safety | no | offline analysis tool |

# Quality Requirements
| id | characteristic / subcharacteristic | target and context | measure method / inputs / unit | threshold and direction | evidence: automated, review, mutation | source |
| --- | --- | --- | --- | --- | --- | --- |
| QR1 | Compatibility / co-existence | run files after review and report | sha256 of every pre-existing file under entry dir before/after `review_entry` (fakes) and R1 live | 0 changed files | automated VO6, review R1 | UI2 |
| QR2 | Reliability / fault tolerance | CLI with one failing entry among several | count of entries attempted | all entries attempted | automated VO8 | FR5 |
| QR3 | Security / confidentiality | token in model output or report | occurrences of planted token in written files | 0 | automated VO7 | FR6 |
| QR4 | Maintainability / modifiability | whole selfcheck suite; branch coverage of review.py, report.py | Test command | all pass; ≥ 90% | automated VO9 | prior selfcheck QR8 |

# Verification Obligations
| id | parent requirement/Case ids | variant and target surface | test layer and selection policy | ISO/IEC/IEEE 29119-4 technique | coverage items | coverage target | observation and expected result | evidence procedure |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| VO1 | FR1, C1, C2 | `extract_briefs` on synthetic entry dirs | unit | equivalence partitioning | E1 main text; E2 main Ask tool_use; E3 sidechain; E4 subagents/ file; E5 malformed line; E6 user message; E7 thinking/non-Ask tool_use only; E8 multiple files ordering | 100% | returned list (kind, file, line, text) | Test command |
| VO2 | FR2, C3 | `load_spec` | unit | equivalence partitioning | spec-logs present; specs present; none; no workflow_start | 100% | return value | Test command |
| VO3 | FR4, C4, C5 | `parse_review` | unit | syntax testing | valid plain; valid fenced; valid with prose; invalid: no JSON, missing category, extra category, bad verdict, diverged empty, findings not list, false_claim non-bool, citation missing | 100% | dict / ReviewFormatError | Test command |
| VO4 | FR3, C12 | `build_prompt` | unit | equivalence partitioning | with spec; without spec; brief with ask kind | 100% | required substrings present | Test command |
| VO5 | FR5, FR6, C6–C8 | `review_entry` with fake call_fn | unit | decision table | D1 ok; D2 ok no false claims; D3 call raises; D4 garbage; D5 no transcript (call_fn not called); D6 token in output | 100% | review.json content/absence, return value, call count | Test command |
| VO6 | QR1 | `review_entry` across D1–D6 | unit | error guessing | guessed defects: overwriting process.json/prediction.json; writing into raw/; writing outside entry dir | none — experience-based | sha256 of pre-existing files unchanged; only review.json new | Test command |
| VO7 | QR3, FR10 | review_entry and report.write with planted token in model output and review.json | unit | error guessing | token in review summary; token in false claim citation reaching report | none — experience-based | no file contains token | Test command |
| VO8 | FR7, FR8, QR2, C11 | `claude_call` with patched subprocess; CLI via `__main__.main` with patched `claude_call` | integration (no docker, no network) | decision table | CLI: ok, unknown run, one error among 3 (all attempted), --instances filter, entry without pool row skipped; claude_call: argv/stdin/timeout passed, non-zero exit → RuntimeError, timeout → RuntimeError | 100% | exit code, stdout, call log, argv | Test command |
| VO9 | FR9, FR10, C9, C10, QR4 | `report.build`/`render_markdown`/`_emit_report` | unit | equivalence partitioning | review ok; error; not run; unreadable file; false claims present; none; existing fields unchanged vs no-review build | 100% | report dict keys, Markdown substrings | Test command |
| VO10 | QR4 | whole suite | integration | branch testing (coverage.py) | branches of review.py, report.py | ≥ 90% | coverage report | Test command |

# Assumptions and Defaults
| id | decision | evidence and uncertainty | brief v<n> — approved / vetoed → <answer> / user answer |
| --- | --- | --- | --- |
| A1 | host-side `claude -p`, opus-5-5, effort low | claude CLI present at ~/.local/bin; no anthropic SDK on host | user answer |
| A2 | fixed-category JSON with verdicts | — | user answer |
| A3 | false claims: reported + separate report table, never scored | — | user answer |
| A4 | brief = all main-thread assistant text + AskUserQuestion inputs, not only the messages right before user turns | simpler and keeps Ask options; transcript has 2 phrase turns but options appear in tool_use | brief v1 — approved |
| A5 | gold tests given as `test_patch` + `FAIL_TO_PASS`; base repository is NOT given to the reviewer (no container) — so claims about repo state are judged only via gold | avoids docker in review; false-claim recall on repo-version facts (sphinx node class) may be lower | brief v1 — approved |
| A6 | review is a separate subcommand, not run automatically by `check` | cost control; easy to wire later | brief v1 — approved |
| A7 | coverage ≥ 90% branch on review.py/report.py; mutmut cap 150, threshold 40% | matches prior selfcheck spec | brief v1 — approved |

# Traceability
| requirement id | Case ids | obligation ids | evidence procedure |
| --- | --- | --- | --- |
| FR1 | C1, C2 | VO1 | Test command |
| FR2 | C3 | VO2 | Test command |
| FR3 | C12 | VO4 | Test command |
| FR4 | C4, C5 | VO3 | Test command |
| FR5, FR6 | C6–C8 | VO5, VO6, VO7 | Test command |
| FR7, FR8 | C11 | VO8 | Test command |
| FR9, FR10 | C9, C10 | VO9, VO7 | Test command |
| QR1–QR4 | — | VO6, VO8, VO7, VO10 | Test command, R1 |

# Workflow Control
| item | value |
| --- | --- |
| correction batches used | 4 |
| verifier invocations | 2 |
| open finding ids | none |

Audit state (one entry per obligation; retain prior decisions in the execution ledger):
| obligation id | spec version | evidence references and revision | accepted / open / invalidated / pending | rationale and mutation outcome | dependencies and reopening evidence |
| --- | --- | --- | --- | --- | --- |
| VO1–VO10 | 3 | Test command run 5 (X6) | accepted (verifier 2) | M1–M10 detected; mutmut 22.8% survival, declared survivors killed | F1–F3 closed by batch 2 |

Execution ledger (append attempts; preserve failed approaches):
| attempt | finding / failure signature | cause hypothesis | changed approach / new evidence | result / disposition |
| --- | --- | --- | --- | --- |
| X1 | Test command run 1: 872 tests, 3 failures — RenderReviewTests findings cell `[[t.jsonl:4]]`; BuildPromptTests x2 regex expects text right after `[file:line]` but prompt has `(kind)` label | cell: spec gap (citation may already carry brackets, as the prompt instructs); prompt: spec gap (format of brief block unspecified) | v3 pins both; impl fix for double brackets; tests adapt to `(kind)` label | batch 1 queued |
| X2 | batch 1 applied (impl `_cite`; tests T1 + challenges 4, 6, bare citation) | — | Test command run 2: 875 tests OK (96 skipped), exit 0; coverage report.py 100%, review.py 97% | accepted pending verifier 1 |
| X3 | verifier 1 RETRY: F1 prompt statements (citation rule, no-spec statement, recommendations rule; spec/ask reaching prompt via review_entry) unasserted; F2 token in error reasons (D3/D4) untested; F3 bare (unwrapped) model form not in invalid corpus. Accepted: VO1, VO2, VO6, VO8, VO9, VO10 | evidence gaps (test-side) | batch 2: tests only | applied; Test command run 3 OK (exit 0, report 100%, review 97%) |
| X4 | hand mutations M1 spec dropped, M2 citation rule removed, M3 token check removed, M4 bare form accepted, M5 sidechain kept, M6 diverged-empty allowed, M7 false_claims unfiltered, M8 reviews {} loads, M9 CLI error ignored, M10 returncode ignored — chosen as the defect classes behind F1–F3 and each FR's core guard | — | 10/10 detected by the intended tests; files restored via seed.py | accepted |
| X5 | mutmut 2.5.1 on selfcheck/review.py only (deviation: report.py/__main__.py omitted for runtime; their changed guards covered by M8, M9), runner test_review+test_cli_review: 250 mutants, 190 killed, 57 survived, 3 timeout; survival 22.8% < 40% | triage: declared 39, 139, 140, 141, 143, 242, 243 → evidence gaps G1–G3; 98, 101 reclassified undeclared by main (block still present, FR3 pins presence); 26, 78 equivalent (main: list arg is the skipped-line counter, unused by review); 144–147 equivalent (raw_decode at `{` returns dict or raises; rechecked); remaining undeclared = unpinned prose/separators/error wording/JSON formatting — not pinned by design (advisory, no spec change) | batch 3: tests G1 scan continues past skipped rows, G2 brace-before-object + termination, G3 text/capture kwargs | applied; rerun of declared survivors: 139, 140, 141, 143, 242, 243 killed; 39 survived (non-list content row before later messages) |
| X6 | mutant 39 survives batch 3 | G1 test lacked a main row with non-list content | batch 4: odd-shaped main rows (string content, non-dict message, None) before later messages | Test command run 5 OK (exit 0, report 100%, review 99%); mutant 39 killed |
| X7 | verifier 2 PASS; advisories A1 (parse corpus lacks non-object finding / list categories / non-string verdict — main checked implementation: all raise ReviewFormatError), A2 keyword-only prompt checks (wording unpinned by design), A3 survivor triage by main | — | — | advisory, not blocking |
| X8 | R1 (user-confirmed): `review a41e64cb9bbbef03` → 3/3 status ok, exit 0; sha256 of process.json ×3, prediction.json ×3, scores.harness.jsonl unchanged; `report a41e64cb9bbbef03` (with baseline 246588b0e19680ee) → only additions to selfcheck/results/a41e64cb9bbbef03.{md,json}. First `report --no-baseline` overwrote the baseline comparison; rerun with baseline restored it. Reference comparison: seaborn ask_options/recommendation_evidence/spec_requirements diverged + false claim "upstream v0.12.2" — match; seaborn understanding consistent — reference noted User Intent drift from the understanding round: miss; sphinx all consistent — reference R1 open "A or B" node type and nonexistent node class: miss (A5: no base repo given; open choices not judged as divergence); astropy all consistent — match | reviewer recall limited on open spec choices and repo-version facts | — | review evidence recorded; misses carried to stage 3 handoff |

# Version Log
## v1
- Initial draft from handoff bf0d1dd85535bb18 and user answers (runner, output format, false-claim handling).
## v2
- Contract-only (implementer challenges): `review_entry` takes `model`/`effort` kwargs recorded in review.json; instance key `review_findings` and findings-cell format defined; `test_report.py` added to Tests so its closed-set key test admits the FR9 keys.
## v3
- Contract-only (Test command run 1, test-implementer challenges): brief block format `[file:line] (kind) text`; model JSON uses wrapped `categories`; findings cell does not double brackets; only `reviews=None` loads from disk; a transcript dir with zero brief items is "no transcript".

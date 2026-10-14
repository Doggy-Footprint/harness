---
version: 4
run_id: 54ad633104783ebe
status: complete
base_commit: 106884acfab6bda33330fe4c18dc8f838b895abb
max_verifier_invocations: 2
handoff: agent-docs/handoff/44ab3e5b5b54f81d-selfcheck-informed-reviewer-condition.md
---

# User Intent
| id | stakeholder | intention | observable goal |
| --- | --- | --- | --- |
| I1 | harness maintainer | "하네스가 제공한 구현 사항에 대해 brief를 읽고 정답을 아는 상태에서 검증해주는 절차를 추가한다." | `check` can run a harness condition where a gold-informed reviewer answers the harness's questions and idle briefs |
| I2 | harness maintainer | in-loop help only as a separate, constrained condition; unassisted check stays primary | informed results are reported beside, never instead of, unassisted results; the difference is labeled as the effect of a user who reads the brief |
| I3 | harness maintainer | the reviewer must not leak the hidden test or the solution | gold text never enters the agent container; answers naming tests, assert literals, files or code are replaced by the fallback and recorded |
| I4 | harness maintainer | the existing baseline fixture stays usable | `driver.py` and `user_sim.py` stay byte-identical, so fixture `246588b0e19680ee` still matches unassisted runs |

# Scope
In scope: an `informed` user mode for the harness arm (new container-side driver wrapper, host-side relay and reviewer, leakage filter, records), `check --conditions`, run/resume/predictions/scores/process/review plumbing for informed entries, manifest condition identity, report sections and effect, config, README.
Out of scope: informed baseline arm; changes to `selfcheck/agent/driver.py` or `selfcheck/agent/user_sim.py`; changes to `review.py` judgment logic; `run` command conditions (stays unassisted); live model or Docker calls in the automated suite.

# Paths
Implementation: selfcheck/informed.py, selfcheck/agent/informed_driver.py, selfcheck/run.py, selfcheck/manifest.py, selfcheck/report.py, selfcheck/__main__.py, selfcheck/config.json, README.md
Tests: selfcheck/tests/test_informed.py, selfcheck/tests/test_informed_driver.py, selfcheck/tests/test_run.py, selfcheck/tests/test_manifest.py, selfcheck/tests/test_report.py, selfcheck/tests/test_report_review.py, selfcheck/tests/test_cli_m3.py, selfcheck/tests/test_cli_review.py, selfcheck/tests/m3_fakes.py, selfcheck/tests/agent_fakes.py, selfcheck/tests/review_fakes.py
Test command: uv run --python 3.12 --with-requirements selfcheck/requirements.txt --with coverage==7.16.2 sh -c 'export COVERAGE_FILE="$HOME/.harness/selfcheck/.coverage" && mkdir -p "$HOME/.harness/selfcheck" && SELFCHECK_DOCKER=1 python -m coverage run --branch --source=selfcheck,analytics -m unittest discover -s selfcheck/tests -t . && python -m coverage report --fail-under=90 --include="selfcheck/patches.py,selfcheck/pool.py,selfcheck/validate.py,selfcheck/mutants.py,selfcheck/score.py,selfcheck/calibrate.py,selfcheck/agent/user_sim.py,selfcheck/agent/driver.py,selfcheck/extract.py,selfcheck/manifest.py,selfcheck/run.py,selfcheck/process.py,selfcheck/fixture.py,selfcheck/report.py,selfcheck/bashparse.py,selfcheck/__main__.py,selfcheck/informed.py,selfcheck/agent/informed_driver.py" && python -m coverage report --fail-under=90 --include="selfcheck/informed.py,selfcheck/agent/informed_driver.py"'
Review evidence: R1 byte-identity: `git diff --exit-code 106884a -- selfcheck/agent/driver.py selfcheck/agent/user_sim.py` exits 0 and `python3 -m selfcheck report a41e64cb9bbbef03` still finds fixture 246588b0e19680ee. R2 comment review of every changed Implementation file against AGENTS.md Comment Enforcement. R3 README review: `check --conditions`, informed records, leakage rule, report sections. R4 live smoke (not automated): `python3 -m selfcheck check --conditions informed --repeats 1 --instances mwaskom__seaborn-3187`; expected: run completes or caps without driver error, `<entry>/informed.jsonl` has ≥1 row, `grep` of the container-copied `raw/` for the gold patch's added lines finds none, the report has an informed section.
Fuzzing: stdlib `random` harness (scratchpad script) over `informed.leaks` and `informed.parse_response`, surface: random answer texts and reviewer outputs built from an alphabet of forbidden terms of a pilot instance, problem-statement words, JSON fragments (`{`, `}`, `"answers"`, `"message"`, `null`), quotes and random printable text; oracle: crash (any exception other than `informed.ResponseFormatError` from `parse_response`) plus properties "every reported leak term occurs in the text and is not exempt" and "a text containing a non-exempt forbidden term reports at least one leak"; seed 1, budget 30000 inputs.
Mutation tool: mutmut 2.5.1 over Implementation Python lines changed since base_commit, runner `python -m unittest discover -s selfcheck/tests -t .` without `SELFCHECK_DOCKER`, sample cap 300, seed 1, survival threshold 40%.

# Signatures
selfcheck/informed.py:
class ResponseFormatError(Exception)
CONDITIONS = ("unassisted", "informed")
def forbidden_terms(instance: dict) -> set[str]
def leaks(text: str, instance: dict, request: dict) -> list[str]   # sorted, de-duplicated
def build_prompt(instance: dict, request: dict) -> str
def parse_response(text: str, request: dict) -> dict   # {"answers": {question: str|None}} or {"message": str|None}, plus "gold_facts_used": list[str]
def respond(instance: dict, request: dict, *, call_fn) -> tuple[dict, dict]   # (response written to container, record row)
class Relay:
    def __init__(self, container, instance: dict, record_path: Path, *, call_fn, poll_s: float, token: str)
    def start(self) -> None
    def stop(self) -> None   # joins the thread; answers no further requests

selfcheck/agent/informed_driver.py (staged next to driver.py and user_sim.py; imports driver as a module):
RELAY_DIR = "/selfcheck/relay"
def main(argv: list[str]) -> int   # same input contract as driver.main plus "user_mode": "informed", "relay_dir", "relay_timeout_s", "relay_poll_s"
def run(inp: dict, client_factory, clock, *, poll_s: float = 1.0) -> dict

Relay file protocol (container paths under `relay_dir`):
- request `req-<n>.json`: `{"n": int, "kind": "ask", "questions": [...]}` or `{"n": int, "kind": "idle", "brief": str}`; n starts at 1 + highest existing request number.
- response `resp-<n>.json`: `{"n": int, "answers": {question: str|null}}` for ask, `{"n": int, "message": str|null}` for idle. The host writes `resp-<n>.json.tmp` then renames, so the driver never reads a partial file.

selfcheck/run.py:
def run(instances, arms, *, cfg, harness_ref="HEAD", model=None, effort=None, cap_min=None, repeats=1, conditions=("unassisted",), docker=docker_exec, now=time.time, call_fn=None) -> Path
def entry_dir(run_dir, entry: dict) -> Path   # "<arm>[-informed][-r<k>]"
def entry_mode(entry: dict) -> str   # entry.get("user_mode", "unassisted")

selfcheck/manifest.py:
def build(..., user_mode: str = "unassisted") -> dict

selfcheck/report.py:
def build(run_dir, *, fixture_dir, scores, processes, min_mutants, reviews=None, informed_scores=None, informed_processes=None) -> dict

selfcheck/__main__.py:
`check --conditions <csv>` (default `unassisted`); `review` covers informed entries.

selfcheck/config.json: `"informed": {"model": "claude-opus-5-5", "effort": "low", "timeout_s": 900, "poll_s": 2}`.

# Functional Requirements
| id | requirement | priority | source |
| --- | --- | --- | --- |
| R1 | `check --conditions` accepts a comma list of `unassisted` and `informed`, default `unassisted`. Each listed condition runs every selected instance with the same `--repeats`. An unknown name exits 2 with `unknown conditions: <names>` on stderr before any run starts. `--resume` ignores `--conditions` and resumes the recorded entries. | must | user answer (standalone needed) |
| R2 | Informed entries have `arm: "harness"` and `user_mode: "informed"`; unassisted entries carry no `user_mode` key, so existing run.json files and directory names are unchanged. Entry directory is `harness-informed` (repeats=1) or `harness-informed-r<k>`. Within one instance and repeat, the unassisted entry runs before the informed entry. | must | plan |
| R3 | Informed predictions go to `predictions.harness-informed.jsonl`; `check` scores them into `scores.harness-informed.jsonl`; process verdicts are written to each informed entry's `process.json`. Unassisted files keep their current names and contents. | must | plan |
| R4 | `manifest.build(user_mode="informed")` adds `"user_mode": "informed"` and computes `user_sim_hash` over `user_sim.py`, `driver.py` and `informed_driver.py` in that order; for unassisted the manifest is identical to the current output (no `user_mode` key, same hash). Hence informed and unassisted `fixture.conditions`/`fixture_id` differ. | must | plan, I4 |
| R5 | Baseline fixture lookup in `check`/`report` uses unassisted harness manifests; when a run has no unassisted entries it uses informed manifests with `user_mode` removed and `user_sim_hash` replaced by the unassisted hash (user_sim.py + driver.py), so a fixture recorded by unassisted runs matches. | must | I4 |
| R6 | For an informed entry, `run` stages `informed_driver.py` with `driver.py` and `user_sim.py`, creates `relay_dir` owned by nonroot, runs `informed_driver.py` instead of `driver.py`, and runs a `Relay` on the host for the whole driver exec (started before, stopped after, also on exceptions). Driver input adds `user_mode`, `relay_dir`, `relay_timeout_s` = `informed.timeout_s + 60`, `relay_poll_s` = 1. | must | user answer (host relay) |
| R7 | On `AskUserQuestion` the informed driver writes an ask request with the questions and waits without blocking the message loop until the response or `relay_timeout_s`. Each question gets the response's non-empty string answer; a question with a null/missing/empty answer, or every question on timeout or unreadable response, gets `user_sim.answer`'s choice. `user.jsonl` gets `{"action": "answer", "questions", "answers", "informed": n, "source": {question: "reviewer"|"fallback"}}`. | must | plan |
| R8 | When `user_sim.on_idle` returns `send`, the informed driver writes an idle request whose `brief` is the concatenated text blocks of main-thread assistant messages received since the last user turn, waits as in R7, and sends the response's non-empty `message` or else `PHRASE`. The send counts as a phrase exactly as now (phrases_sent, tool_calls_since_phrase, stop rules unchanged); the `user.jsonl` phrase row adds `"informed": n, "source": "reviewer"|"fallback"`. The resume prompt stays `PHRASE` with no relay request. | must | user answer (PHRASE fallback) |
| R9 | `Relay` polls the container's `relay_dir` every `poll_s`, answers each request number once in ascending order, skips request numbers that already have a response file (resume), and writes the response protocol file. Gold text (patch, test_patch, FAIL_TO_PASS, gold_facts_used) is never written to the container: the only container writes are response files containing `n` and the sanitized answers/message. | must | I3 |
| R10 | `build_prompt` gives the reviewer the issue text, the gold `patch`, `test_patch`, `FAIL_TO_PASS` and the request, and states the constraints: the reviewer's role is to catch a wrong direction (say that a recommendation or claim is wrong and what behavior is expected instead), never to hand over the solution; answer only what was asked or presented for approval; speak only of observable behavior derivable from the FAIL_TO_PASS tests; never name tests, assert values, files, code, or node/API choices the request did not raise; return null when there is nothing to add; answer with one JSON object of the R11 shape listing `gold_facts_used`. | must | handoff Next Step 2 |
| R11 | `parse_response` accepts the first JSON object in the text. Ask: `answers` must be an object whose keys are a subset of the request's question texts and values strings or null; missing questions become null. Idle: `message` must be a string or null. `gold_facts_used` must be a list of strings (missing → `[]`). Anything else raises `ResponseFormatError`. | must | plan |
| R12 | `forbidden_terms(instance)` is the union of: each FAIL_TO_PASS id; its test name (text after the last `::`, with any `[...]` parameter suffix removed, or for `name (module.Class)` ids the name before ` (` and the dotted part inside); every file path in `diff --git` headers of `patch` and `test_patch` and each path's basename; names defined by `def`/`class` on added or removed lines of `patch`; string literals of length ≥ 3 (not whitespace-only) on added lines of `test_patch` that contain the word `assert` (word boundary; `nonassert` does not count). | must | user answer (observable behavior only) |
| R13 | `leaks(text, instance, request)` returns the forbidden terms that occur in `text` and do not occur in the issue text or in the request's serialized JSON. Identifier-like terms (`[A-Za-z_][A-Za-z0-9_]*`) match on word boundaries; other terms match as case-sensitive substrings. | must | user answer |
| R14 | `respond` calls `call_fn(build_prompt(...))`, parses, and replaces each answer (or the message) that has leaks with null. A call exception, timeout or `ResponseFormatError` yields an all-null response. It returns the response and a record row `{"n", "kind", "request", "raw_output", "parsed", "leaks": {question or "message": [terms]}, "sent", "gold_facts_used", "error", "elapsed_s"}` where `sent` is the post-filter response written to the container. | must | plan |
| R15 | `Relay` appends each record row as one JSON line to `<entry dir>/informed.jsonl` on the host, after replacing the token with `[REDACTED]`. The entry's existing directory scrub and token-remaining check cover this file. | must | handoff Next Step 3 |
| R16 | `report.build` keeps every current key and the shape of `instances` (unassisted only). It adds `informed`: a list of per-instance blocks with exactly the current instance-block shape computed from informed entries, `informed_scores` and `informed_processes`, compared with the same baseline; and `informed_effect`: `{instance_id: {metric: informed_median - unassisted_median or null}}` for instances present in both, null when either median is missing. The markdown renders unassisted sections first, then `## informed condition` sections in the same table format, then an `## informed effect` table with the note "difference from unassisted: effect of a user who reads the brief; unassisted is the primary score". A run without informed entries has `informed: []`, `informed_effect: {}`, and no informed markdown sections. | must | I2, handoff Next Step 4 |
| R17 | `review RUN_ID` reviews informed entries as well and labels them `<iid> informed[ r<k>]`; `report` loads each informed entry's `review.json` into its informed block. | should | plan |
| R18 | `resume` restarts an interrupted informed entry with `informed_driver.py` and a new `Relay`; request numbering continues after the highest existing request. | must | plan |
| R19 | README documents `--conditions`, the informed records, the leakage rule and the report sections. | must | project rule |

# Errors
- Unknown condition name — exit 2, `unknown conditions: <names>` on stderr — no run directory created.
- Reviewer call raises or times out — record `error` set to the first line, all-null response — driver falls back (R7/R8); run continues.
- Reviewer output not R11-shaped — record `error` = the `ResponseFormatError` message — same as above.
- Relay response absent past `relay_timeout_s` — `user.jsonl` row `source: fallback` — fallback sent; a late response file for that n is ignored.
- Unreadable or malformed response file — treated as absent — same as timeout.
- Answer contains a non-exempt forbidden term — record `leaks` lists the terms, that answer becomes null — fallback for that question/message.
- Relay thread exception while handling one request — record row with `error`, no response written — driver times out to fallback; the relay continues with later requests.
- Token in a record row — replaced with `[REDACTED]` before writing — file still written.

# Cases
| id | level | input / state | expected result |
| --- | --- | --- | --- |
| C1 | normal | `check --conditions unassisted,informed --repeats 2` with fakes | entries per instance in order (r1 unassisted, r1 informed, r2 unassisted, r2 informed); dirs `harness-r1`, `harness-informed-r1`, ...; both predictions and scores files written |
| C2 | normal | `check` without `--conditions` | identical entries and files to current behavior (no `user_mode` key, no informed files) |
| C3 | normal | `check --conditions informed --repeats 1` | only `harness-informed` entries; fixture lookup succeeds with informed manifests minus `user_mode`/`user_sim_hash` |
| C4 | error | `check --conditions informed,bogus` | exit 2, stderr `unknown conditions: bogus`, no run started |
| C5 | normal | manifest for unassisted vs informed | unassisted manifest equals current output; informed has `user_mode` and a different `user_sim_hash`; `fixture_id(conditions(...))` differs |
| C6 | normal | ask request with 2 questions; reviewer answers both cleanly | AskUserQuestion answers are the reviewer texts; user.jsonl source both `reviewer`; record row complete |
| C7 | boundary | reviewer answers one question, null for the other | the null one gets `user_sim.answer`'s label; sources `reviewer`/`fallback` |
| C8 | error | relay never responds | after `relay_timeout_s` all answers from `user_sim.answer`; message loop kept polling meanwhile (wall clock cap still fires) |
| C9 | normal | idle with brief, reviewer message "X" | query sent is "X"; phrases_sent +1; brief equals assistant text since last user turn |
| C10 | boundary | idle, reviewer message null | `PHRASE` sent, source `fallback` |
| C11 | edge | resume of an informed entry | resume prompt `PHRASE`, no request written for it; next request number = highest existing + 1 |
| C12 | normal | `forbidden_terms` on pilot instances (pytest `path::name[param]` and django `name (mod.Class)` ids) | contains ids, names, paths, basenames, def/class names, assert string literals ≥3 chars |
| C13 | boundary | answer containing a forbidden test name that also appears in the issue text / in the request | no leak reported |
| C14 | error | answer containing a gold file basename not in issue or request | leak reported; answer nulled; record lists the term |
| C15 | edge | identifier term as a substring of a longer word (`test_x` inside `test_xy`) | no leak (word boundary); non-identifier term (e.g. `"1,234"`) matches as substring |
| C16 | error | reviewer output without JSON, with wrong `answers` type, unknown question key, or non-list `gold_facts_used` | `ResponseFormatError`; respond returns all-null with `error` |
| C17 | error | `call_fn` raises | all-null response, `error` = first line |
| C18 | normal | Relay with fake container holding req-1, req-2 | both answered once in order; responses written via tmp+rename; container writes contain no gold text; record file has 2 rows |
| C19 | edge | record raw_output containing the token | file line has `[REDACTED]` |
| C20 | error | relay handler raises on req-1 | record row with error, no resp-1, req-2 still answered |
| C21 | normal | report with both conditions, repeats 2 | `instances` as before; `informed` blocks same shape; `informed_effect` = median difference; markdown order unassisted → informed → effect |
| C22 | boundary | report without informed entries | `informed: []`, `informed_effect: {}`, markdown unchanged except nothing added |
| C23 | edge | metric median missing in one condition | effect null for that metric |
| C24 | normal | `review` on a run with informed entries | reviews written for both; labels include `informed` |
| C25 | normal | `run._drive` informed entry with fake docker | stages 3 files, creates relay dir, runs informed_driver argv, Relay started before and stopped after exec, also when exec raises |

# Quality Applicability
| ISO/IEC 25010:2023 characteristic | applicable | rationale |
| --- | --- | --- |
| Functional suitability | yes | new condition behavior R1–R19 |
| Performance efficiency | no | relay polling cost is negligible next to agent runs; reviewer latency is bounded by timeout (R6) |
| Compatibility | yes | existing fixture, run layouts and report keys must keep working |
| Interaction capability | no | CLI flag only; covered by R1 |
| Reliability | yes | reviewer/relay failure must never break a run |
| Security | yes | gold and token confidentiality |
| Maintainability | yes | coverage and comment rules |
| Flexibility | no | no portability change |
| Safety | no | no physical/harm surface |

# Quality Requirements
| id | characteristic / subcharacteristic | target and context | measure method / inputs / unit | threshold and direction | evidence: automated, review, mutation | source |
| --- | --- | --- | --- | --- | --- | --- |
| Q1 | Compatibility / co-existence | baseline fixture 246588b0e19680ee, legacy run a41e64cb9bbbef03, unassisted outputs | byte diff of driver.py/user_sim.py; report on legacy run; count of failures | 0 | automated C2, C5, C22; review R1 | I4 |
| Q2 | Reliability / fault tolerance | reviewer error, malformed output, relay timeout, relay exception | runs ending `error` because of the reviewer path, count across C8, C16, C17, C20 | 0 | automated; fuzz | plan default |
| Q3 | Security / confidentiality | container writes during informed runs | container writes containing gold patch lines, test_patch lines, FAIL_TO_PASS ids or gold_facts_used, count | 0 | automated C18; review R4 | I3 |
| Q4 | Security / confidentiality | leakage filter on random texts | property violations per 30000 fuzz inputs | 0 | fuzz; automated C13–C15 | user answer |
| Q5 | Maintainability / testability | Test command include lists | branch coverage | aggregate ≥ 90% and new files (informed.py, informed_driver.py) ≥ 90% | automated | existing project target |
| Q6 | Maintainability / analysability | changed Implementation files | comments violating AGENTS.md Comment Enforcement, count | 0 | review R2 | AGENTS.md |

# Verification Obligations
| id | parent requirement/Case ids | variant and target surface | test layer and selection policy | ISO/IEC/IEEE 29119-4 technique | coverage items | coverage target | observation and expected result | evidence procedure |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| O1 | R1, R2, C1–C4 | `__main__.main(["check", ...])` with run/score fakes | integration; all items | equivalence partitioning | {default, unassisted only, informed only, both, unknown name, resume ignores flag} | 100% | entries/order/dirs/exit codes as specified | unittest |
| O2 | R3, R5, C1, C3 | run dir files after check | integration; all items | equivalence partitioning | {predictions file per mode, scores file per mode, process.json per informed entry, fixture lookup with unassisted present, fixture lookup informed-only} | 100% | file names/contents per mode | unittest |
| O3 | R4, C5 | `manifest.build` | unit; all items | equivalence partitioning | {unassisted unchanged vs recorded current output, informed key, informed hash over 3 files, fixture_id differs} | 100% | as specified | unittest |
| O4 | R6, R18, C25, C11 | `run._run_entry`/`resume` with fake docker and fake Relay | integration; all items | scenario testing | {fresh informed: staging, relay dir, argv, input keys, relay start/stop; exec raises → relay stopped; resume informed → informed argv + new relay; unassisted entry → driver.py, no relay} | 100% | call log matches | unittest |
| O5 | R7, C6–C8 | `informed_driver.run` with fake SDK client and a fake relay responder task writing files in a temp relay dir | integration; all items | decision table | rules {both answered, partial null, empty string, timeout, malformed resp file} | 100% | answers + user.jsonl rows; during timeout the loop still enforces wall clock | unittest |
| O6 | R8, R11-idle, C9–C11 | same harness, idle path | integration; all items | state transition | transitions {idle→send reviewer msg, idle→send PHRASE (null), idle→PHRASE (timeout), stop rules unchanged after reviewer msg (completed, stalled), resume→PHRASE no request, numbering continues} | 100% | sent queries, counters, rows | unittest |
| O7 | R12, C12 | `forbidden_terms` on two pilot instances (one pytest, one django id style) | unit; all items | classification tree | classes {pytest id, param suffix, django id, diff path, basename, def name, class name, assert literal ≥3, literal <3 excluded, non-assert literal excluded} | 100% | expected sets written independently from the instance text | unittest |
| O8 | R13, C13–C15 | `leaks` | unit; all items | decision table | rules {term absent; present+exempt by issue; present+exempt by request; present non-exempt identifier word-bounded; identifier inside longer word; non-identifier substring} | 100% | returned list | unittest |
| O9 | R10, R11, C16 | `build_prompt`, `parse_response` | unit; all items | syntax testing | {prompt contains issue/gold patch/test_patch/FAIL_TO_PASS/request/each constraint including the catch-wrong-direction role; valid ask; valid idle; text before JSON; no JSON; answers not object; value not str/null; unknown key; missing key → null; message wrong type; gold_facts_used missing → []; non-list} | 100% | parsed dict or ResponseFormatError | unittest |
| O10 | R14, C14, C16, C17 | `respond` with fake call_fn | unit; all items | equivalence partitioning | {clean, one answer leaks, message leaks, call raises, format error} | 100% | response and record row fields | unittest |
| O11 | R9, R15, C18–C20 | `Relay` with fake container (in-memory files, write log) | integration; all items | scenario testing | {two requests answered once in order, tmp+rename, no gold text in any container write, records appended, token redacted, handler exception isolates request, stop joins thread} | 100% | write log and record file | unittest |
| O12 | R16, C21–C23 | `report.build` + `render_markdown` with fixtures | unit; all items | equivalence partitioning | {both conditions, no informed, informed only, missing median → null, markdown section order and note, legacy keys unchanged} | 100% | dict and markdown | unittest |
| O13 | R17, C24 | `review` CLI with review fakes | integration; all items | equivalence partitioning | {unassisted entries, informed entries labeled, report loads informed review} | 100% | labels and review.json | unittest |
| O14 | Q2, Q4 | fuzz harness over `leaks`, `parse_response` | random | random testing | 30000 inputs seed 1 | budget completed | no crash, properties hold | main runs fuzz |
| O15 | Q5 | Test command | structure | branch testing | Implementation Python files in the include list | ≥ 90% aggregate and new files | coverage report | Test command |
| O16 | Q1, Q6, R19 | R1–R4 reviews | review | none — experience-based | {byte identity, legacy report, comments, README, live smoke} | none — experience-based | as in Review evidence | main |

# Assumptions and Defaults
| id | decision | evidence and uncertainty | brief v1 — approved / vetoed → <answer> / user answer |
| --- | --- | --- | --- |
| A1 | reviewer on host via relay; gold stays out of the container | plan session | user answer |
| A2 | null/timeout → PHRASE or `user_sim.answer` | plan session | user answer |
| A3 | harness arm only | plan session | user answer |
| A4 | leakage line: observable behavior allowed; tests, literals, files, code forbidden; host filter | plan session | user answer |
| A5 | standalone `--conditions informed` supported | understanding round | user answer |
| A6 | reviewer model opus-5-5, effort low, 900 s per call; wall clock keeps running | understanding round | user answer |
| A7 | separate `informed_driver.py`; driver.py/user_sim.py byte-identical | fixture user_sim_hash check | user answer |
| A8 | relay via `docker exec`/`docker cp` polling rather than a bind mount | avoids host-dir ownership issues for uid nonroot; adds ≤ poll_s latency | brief v1 — approved |
| A9 | reviewer sees the gold patch, test_patch and FAIL_TO_PASS; must not give the answer but must catch wrong directions | leakage is bounded by the R12–R14 filter | user answer |
| A10 | a term is exempt when it appears in the issue text or the request | the issue is what a real reporter knows; the request means the harness raised it | brief v1 — approved |
| A11 | `--conditions` name and `unassisted`/`informed` values; report adds `informed`/`informed_effect` keys only | CLI and report format are interfaces | brief v1 — approved |
| A12 | unassisted runs before informed within each instance/repeat | keeps time-of-day drift balanced per pair | brief v1 — approved |
| A13 | coverage ≥ 90% aggregate and for the two new files; mutation threshold 40% | existing project target | brief v1 — approved |
| A14 | numeric literals on assert lines (e.g. `> 1e7`) are not forbidden terms; a numeric threshold is treated as observable behavior | live smoke acef0816b4a32f64: reviewer said labels must be 'much larger than 1e7', matching seaborn test `> 1e7`; user chose to keep R12 as is | user answer |

# Traceability
| requirement id | Case ids | obligation ids | evidence procedure |
| --- | --- | --- | --- |
| R1 | C1–C4 | O1 | unittest |
| R2 | C1 | O1 | unittest |
| R3 | C1 | O2 | unittest |
| R4 | C5 | O3 | unittest |
| R5 | C3 | O2 | unittest |
| R6 | C25 | O4 | unittest |
| R7 | C6–C8 | O5 | unittest |
| R8 | C9–C11 | O6 | unittest |
| R9 | C18 | O11 | unittest |
| R10 | C16 | O9 | unittest |
| R11 | C16 | O9 | unittest |
| R12 | C12 | O7 | unittest |
| R13 | C13–C15 | O8 | unittest |
| R14 | C14, C16, C17 | O10 | unittest |
| R15 | C18, C19 | O11 | unittest |
| R16 | C21–C23 | O12 | unittest |
| R17 | C24 | O13 | unittest |
| R18 | C11 | O4, O6 | unittest |
| R19 | — | O16 | review R3 |
| Q1 | C2, C5, C22 | O1, O3, O12, O16 | unittest, R1 |
| Q2 | C8, C16, C17, C20 | O5, O10, O11, O14 | unittest, fuzz |
| Q3 | C18 | O11, O16 | unittest, R4 |
| Q4 | C13–C15 | O8, O14 | unittest, fuzz |
| Q5 | — | O15 | Test command |
| Q6 | — | O16 | R2 |

# Workflow Control
| item | value |
| --- | --- |
| correction batches used | 6 |
| verifier invocations | 2 |
| open finding ids | none |

Audit state (one entry per obligation; retain prior decisions in the execution ledger):
| obligation id | spec version | evidence references and revision | accepted / open / invalidated / pending | rationale and mutation outcome | dependencies and reopening evidence |
| --- | --- | --- | --- | --- | --- |
| O1–O8, O10–O14 | 3 | test files at correction batch 2; Test command 1193 OK; fuzz 30000/0 | accepted (verifier 1) | evidence per verifier map | O9 prompt fix does not touch these tests |
| O9 | 4 | test_informed.py BuildPromptTests polarity test (batches 3–4) | accepted (verifier 2), F-O9-1 closed | inversion mutations M1 now killed | — |
| O1, O4, O5, O6, O11, O12 | 4 | additions from batches 5–6 (NonBlockingWaitTests, G1–G8) | accepted (verifier 2) | M8 killed; 17/18 declared mutants killed; mt059 reclassified undeclared (fallback reachable only with `--conditions ""`) | prior items unchanged |
| O15, O16 | 4 | Test command 1201 OK, coverage 94% aggregate, informed.py 94%, informed_driver.py 93%; R1–R4 done (smoke acef0816b4a32f64) | accepted (main) | — | — |

Execution ledger (append attempts; preserve failed approaches):
| attempt | finding / failure signature | cause hypothesis | changed approach / new evidence | result / disposition |
| --- | --- | --- | --- | --- |
| 1 | first Test command: 9 failures, 1 error (1192 tests) | (a) fake container recognises only the unassisted mkdir argv → informed driver exit 1 (verified by _finalize trace: `driver exit 1`); (b) test_report_review vo9 closed key set; (c) informed-only test expects no scores.harness.jsonl, not required by spec; (d) `nonassert` matched as assert line | (a)(b)(c) test defects → test-implementer; (d) spec v3 word-boundary `assert` → implementer | correction batch 1 |
| 2 | Test command: 1 failure / 1193 (test_o4_c1 predictions line ≠ prediction.json); fuzz 30000 inputs 0 violations; R1 identical; R3 README states informed-only lookup removes user_sim_hash and assert lines without word rule | test compares predictions line without the existing per-repeat `repeat` field (verified: existing `_write_predictions` adds it when repeats>1); README stale vs v2/v3 | test defect → test-implementer; README → implementer | correction batch 2 |
| 3 | verifier 1 F-O9-1: R10 constraint checks are keyword-only; inverted constraints pass | confirmed by hand mutation (survived) | test-implementer: polarity-aware constraint assertions; spec v4 defines record `sent` (advisory A-1) | correction batch 3 |
| 4 | new polarity test fails on unmutated prompt: sentence 'You also know the gold solution.' rejected; both inversion mutations now detected | test rule 'no sentence mentions solution without negation' forbids R10's required statement that the reviewer knows the gold | test-implementer: forbid only solution paired with an affirmative hand-over verb | correction batch 4 |
| 5 | hand mutations M1–M11 (prompt polarity, request exemption, word boundary, assert word, leak nulling, gold to container, R9 skip, blocking wait, relay stop on exception, effect sign, manifest key): 10 killed; M8 (blocking time.sleep in relay wait) survived | O5 evidence never observes that other asyncio tasks progress during a pending relay wait; the wait's own cap check masks blocking | test-implementer: assert a concurrent asyncio task progresses while a request is pending | correction batch 5 |
| 6 | M8 now killed (NonBlockingWaitTests). Live smoke acef0816b4a32f64: completed, resolved 1.0, 4 relay rows (2 reviewer, 2 fallback), no relay leak; numeric assert threshold passed (A14 user answer: keep). mutmut 300 sampled of 869 eligible seed 1 targeted modules: 243 killed, 55 survived, 2 timeout (inconclusive) = 18.5% < 40%; triaged ×3 | declared → evidence gaps: mt005, 185, 212, 214, 253 (error row shape), 069, 097, 197 (effect table format), 091, 119, 217, 256 (C22 legacy markdown), 075, 102 (relay dir prep), 220 (failed request re-handled), 139 (redaction literal), 059 (CLI default), 046 (listing user). undeclared advisory: prompt/message wording mt000, 006, 015, 099, 103, 104, 174, 187, 193, 205, 213, 250, 268, 293; mt041 daemon, 057/165 halted user_mode, 145 precision, 192 non-ASCII exemption, 009/232 cfg fallback, 087 unknown kind, 043/066 extra lines, 071 multi-name separator, 248 unlistable relay dir, 289 send at cap. equivalent accepted (main checked mt152): mt016, 033, 074, 085, 126, 152, 153, 254, 287, 297 | test-implementer batch 6 | correction batch 6 |
| 7 | re-run 18 declared mutants: 17 killed; mt059 survives (argparse default makes fallback reachable only with empty `--conditions`) → undeclared advisory; Test command 1201 OK | — | verifier 2 | pass, 0 blocking; advisories A-1..A-3 recorded; R2/R3 reviewed by main |

# Version Log
## v1
- Initial draft from handoff 44ab3e5b5b54f81d and plan-session decisions A1–A7.
## v4
- Closed: verifier 2 pass; status complete.
- R14: define record `sent` as the post-filter response (verifier advisory A-1). Contract-only.
## v3
- R12: assert lines are those containing the word `assert`; whitespace-only literals excluded (implementer report). R9: Relay skips requests that already have a response (test-implementer challenge; matches implementation). Contract-only.
## v2
- R5: informed-only fixture lookup replaces `user_sim_hash` with the unassisted hash instead of removing it (implementer challenge: removal can never match a fixture under `fixture.compare`'s key union). Contract-only.
- Tests: add `selfcheck/tests/test_report_review.py` (closed key-set assertion on the report dict must admit the R16 keys).
- Undefined details fixed: a malformed response file falls back immediately (no wait); "since the last user turn" = since the last query the driver sent; `run._drive`/`_run_entry`/`resume` internal signatures are implementation-private (tests drive `run.run`/`run.resume` and patch `informed.Relay`).

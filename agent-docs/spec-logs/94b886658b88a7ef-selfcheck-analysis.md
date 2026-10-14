---
version: 6
run_id: 94b886658b88a7ef
status: complete
base_commit: ad1acc388a1b2e20ae6efe171ecff6c559d9b885
max_verifier_invocations: 2
handoff: agent-docs/handoff/stale/1ba36300e7469498-selfcheck-m3-verifier-limit.md
---

# User Intent
| id | stakeholder | intention | observable goal |
| --- | --- | --- | --- |
| UI1 | harness maintainer | judge from executed runs whether the harness arm beats a no-harness baseline | `python -m selfcheck check` produces a per-instance report placing each harness metric above, within or below the baseline repeats' range |
| UI2 | harness maintainer | judge whether the harness followed its own workflow in a run | `python -m selfcheck process RUN_ID` writes per-entry pass / fail / n/a verdicts with ledger or telemetry line evidence |
| UI3 | harness maintainer | build the baseline once and reuse it only while conditions are comparable | `baseline create` writes a fixture keyed by its run conditions; `check`/`report` refuse a fixture whose conditions differ and name the differing keys |
| UI4 | harness maintainer | never burn subscription quota past a rate-limit signal | after an entry ends `interrupted` or reports a non-`allowed` rate-limit status, no further entry starts; the batch resumes later |
| UI5 | harness maintainer | find and use the tool from the repository docs | README has a "자체 점검" section; AGENTS.md Source line lists `selfcheck/` |

# Scope
In scope: M3 of `selfcheck/` — batch halting on rate-limit signals in `run.run`/`run.resume`; `process.py` (process-compliance checks over a run entry's raw evidence); `fixture.py` (baseline fixture creation, comparability conditions, fixture lookup and pre-check); `report.py` (harness vs baseline report, JSON and Markdown); CLI `process`, `baseline create`, `check`, `report`; `config.json` keys `baseline` and `report`; README "자체 점검" section; AGENTS.md Source line.
Out of scope: running the live baseline and the first harness check (main runs them after completion, each with user confirmation, not part of the Test command); changes to M1 scoring, mutants, validation, pool or fixtures other than adding `fixtures/baseline/`; changes to the driver, images, extraction or manifest content; `harness/`, `installer/`, `tests/`, `analytics/`; statistical significance; automatic waiting for rate-limit resets; pool replacement (small-sample instances are flagged instead).

# Paths
Implementation: selfcheck/run.py, selfcheck/process.py, selfcheck/fixture.py, selfcheck/report.py, selfcheck/__main__.py, selfcheck/config.json, README.md, AGENTS.md
Tests: selfcheck/tests/test_halt.py, selfcheck/tests/test_process.py, selfcheck/tests/test_fixture.py, selfcheck/tests/test_report.py, selfcheck/tests/test_cli_m3.py, selfcheck/tests/m3_fakes.py, selfcheck/tests/test_run.py, selfcheck/tests/test_cli_run.py
Test command: uv run --python 3.12 --with-requirements selfcheck/requirements.txt --with coverage==7.16.2 sh -c 'export COVERAGE_FILE="$HOME/.harness/selfcheck/.coverage" && mkdir -p "$HOME/.harness/selfcheck" && SELFCHECK_DOCKER=1 python -m coverage run --branch --source=selfcheck,analytics -m unittest discover -s selfcheck/tests -t . && python -m coverage report --fail-under=90 --include="selfcheck/patches.py,selfcheck/pool.py,selfcheck/validate.py,selfcheck/mutants.py,selfcheck/score.py,selfcheck/calibrate.py,selfcheck/agent/user_sim.py,selfcheck/agent/driver.py,selfcheck/extract.py,selfcheck/manifest.py,selfcheck/run.py,selfcheck/process.py,selfcheck/fixture.py,selfcheck/report.py"'
Review evidence: R1 offline replay on the M2 smoke run `~/.harness/selfcheck/runs/9f9be4f8c2b2986e` (no agent run, no quota): main runs `score --predictions <run>/predictions.harness.jsonl --out <run>/scores.harness.jsonl`, `process 9f9be4f8c2b2986e`, `report 9f9be4f8c2b2986e` (expected exit 2 — no comparable fixture — with differing keys printed) and `report 9f9be4f8c2b2986e --no-baseline` (exit 0), records outputs, and checks by hand against the raw files that PC8 = fail (main edited `tests/test_domain_py.py` after the spec write) and PC5 = fail (backups without restores); R2 comment review of every new or changed Implementation file against AGENTS.md Comment Enforcement; R3 docs review: README section names every new subcommand, exit code 3, the quota warning, and where results go; AGENTS.md Source line contains `selfcheck/`.
Fuzzing: none — process inputs are JSONL written by the M2 driver and the harness telemetry library; malformed-line handling is covered by equivalence classes (VO2), and no external party controls these files.
Mutation tool: mutmut 2.5.1 over Python Implementation lines changed since base_commit (`selfcheck/run.py`, `selfcheck/process.py`, `selfcheck/fixture.py`, `selfcheck/report.py`, `selfcheck/__main__.py`), runner `python -m unittest discover -s selfcheck/tests -t .` without `SELFCHECK_DOCKER`, sample cap 300, seed 1, survival threshold 40%.

# Signatures
Configuration (`selfcheck/config.json`, new keys):
- `"baseline": {"repeats": 2, "fixtures_dir": "selfcheck/fixtures/baseline", "progress": "~/.harness/selfcheck/baseline-progress.json"}`
- `"report": {"min_mutants": 10, "results_dir": "selfcheck/results"}`
Relative directories resolve against the repository root.

Batch halting (`selfcheck/run.py`):
- `halt_reason(state: dict | None) -> str | None` — `"interrupted"` when `state["status"] == "interrupted"`; else `"rate_limit:<status>"` when `state["rate_limit"]` is a dict whose `status` is not `"allowed"` (and not None); else None. `state` is the host `state.json` of the entry just finished.
- `run.run` and `run.resume`: after each entry is processed (and `run.json`/predictions rewritten as today), compute `halt_reason`; when non-None, write `run.json` with `"halted": {"reason": <reason>, "instance_id", "arm"}` and return without starting another entry. Entries never started keep status `pending`. `run.json` always carries `halted` (null when the batch ran to its end). `resume` sets `halted` to null before its first entry and processes entries with state `interrupted` or no state (including `pending`) in order, applying the same rule.
- `cmd_run` exit codes: 3 when `run.json` `halted` is non-null (takes precedence), else 1 when any entry is `error`, else 0. On halt it prints the run directory and `halted: <reason> at <instance_id>/<arm>; resume with: python3 -m selfcheck run --resume <run_id>` to stderr.

Process checks (`selfcheck/process.py`):
- `evaluate_entry(entry_dir: Path, *, score: dict | None = None) -> dict` returning `{"instance_id", "arm", "workflow_run_id": str | None, "end_status": str | None, "checks": {<check id>: {"verdict": "pass" | "fail" | "n/a", "detail": str, "evidence": [{"file": <path relative to entry_dir>, "line": <1-based int>}]}}, "metrics": {...}, "skipped_lines": int}`. `instance_id`/`arm` come from `manifest.json` (or the entry directory names when absent). For arm `baseline` every check is `n/a` with detail `baseline arm`.
- Inputs, all optional (missing = empty): `raw/telemetry/*.jsonl` (all files, events ordered by `ts`, stable), `raw/ledger.jsonl` (file order), `raw/full.diff`, `prediction.json`. A non-blank line that is not a JSON object is skipped and counted in `skipped_lines`; blank lines are ignored and not counted. Evidence `line` numbers are physical 1-based line numbers of the file (every line counts).
- Workflow identity: `workflow_run_id` = the `workflow_run_id` of the first `workflow_start` event; "run events" = events with that `workflow_run_id`. `end_status` = `status` of the first run `workflow_end`, or None.
- Spec text: the new-file section of `raw/full.diff` whose path is `agent-docs/spec-logs/<workflow_run_id>-*.md`, else `agent-docs/specs/<workflow_run_id>-*.md`; text = its added lines. Frontmatter `status:` is the archived status; a spec text whose first line is not `---` has no status (None). `Implementation:` and `Tests:` lines (first occurrence each) split on `,`, items stripped of whitespace and backticks.
- Path match: a repo path `p` matches entry `e` when `p == e`, or `p` starts with `e.rstrip("/") + "/"`, or `fnmatch(p, e)`. Ledger paths: `tool_input["file_path"]` or `["notebook_path"]` (Read, Edit, Write, MultiEdit, NotebookEdit), `["path"]` (Grep, Glob); an absolute path under `/testbed/` is made relative; other absolute paths never match; a missing, empty or non-string path value is ignored (no match, no exception). `EDIT_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}`. Main = ledger rows with `agent_type` null.
- Check ids, rules and verdicts (`n/a` only where a rule says so). `evidence` lists the lines that caused a failure; a failure caused by an absence (no start, no spec, no event) has empty evidence. For a harness entry, missing telemetry means no events: PC1 and PC2 fail, PC3–PC5 are n/a.
  - `PC1 workflow_started`: pass iff a `workflow_start` event exists; else fail.
  - `PC2 telemetry_compliant`: `analytics.compliance.evaluate(all events)`; pass iff `compliant is True`; fail otherwise (including no workflow events), detail = its reasons, plus `no_workflow_end` when `completed` is False.
  - `PC3 verifier_budget`: n/a without PC1; pass iff run `verifier_result` events ≤ 2 and main `Agent`/`Task` ledger rows with `tool_input.subagent_type == "test-verifier"` ≤ 2.
  - `PC4 verification_before_complete`: n/a unless `end_status == "complete"`; pass iff a run `verification_result` event precedes the run `workflow_end`.
  - `PC5 seed_paired`: n/a without PC1; run `seed` events with action `backup`/`restore` (others ignored) in order; pass iff at least one backup and the sequence is backup, restore, backup, restore, … ending with restore before `workflow_end` (when present); evidence = telemetry lines of unpaired events plus the last seed event when it follows `workflow_end`.
  - `PC6 seed_clean_at_end`: n/a without `prediction.json`; pass iff `prediction["seed"]["before"]` contains `seed: none`; failure evidence `{"file": "prediction.json", "line": 1}`.
  - `PC7 archive_matches_end`: n/a when `end_status` is None; for `complete`/`limit`/`aborted` pass iff the spec text came from `agent-docs/spec-logs/` with frontmatter status equal to `end_status`; for `handoff` pass iff it came from `agent-docs/specs/` with status `active`; fail otherwise (including no spec found).
  - `PC8 main_no_test_edits`: n/a without spec text or without a ledger row editing (EDIT_TOOLS) a file under `agent-docs/specs/`; fail iff a main EDIT_TOOLS row after the first such row targets a path matching a `Tests:` entry; evidence = ledger lines.
  - `PC9 role_isolation`: n/a without spec text; fail iff (a) an `implementer` row targets a `Tests:` path, or (b) a `test-implementer`/`test-verifier` row targets an `Implementation:` path; "targets" = the path rules above, or a Bash `command` containing literally an entry that has a `.` in its last path component (directory entries are not matched in Bash); evidence = ledger lines.
  - `PC10 no_edit_after_final_pass` (evidence = every offending ledger line): n/a unless the last run `verifier_result` has result `pass`; anchor = the last ledger row with `agent_type == "test-verifier"`, else the last main row dispatching `test-verifier`; n/a without anchor or spec text; fail iff any later EDIT_TOOLS row targets an `Implementation:` or `Tests:` path.
  - `PC11 false_pass`: n/a when `score` is None or `end_status != "complete"`; fail iff `score["resolved"]` is False or `score["swt"]["success"]` is False, with evidence `{"file": "prediction.json", "line": 1}`; else pass.
- `metrics`: `verifier_results` (count), `verifier_dispatches` (count), `seed_pairs` (completed backup→restore pairs), `subagent_dispatches` ({subagent_type: count} of main Agent/Task rows), `main_implementation_edits` (main EDIT_TOOLS rows after the spec write targeting `Implementation:` paths), `self_reported_kill` ({`mutants`, `killed`, `rate`} from the last run `verification_result`, rate = killed/mutants or None; null without such event), `measured_kill` (`score["kill"]["primary"]` or None). The report labels the two kill values as a contrast, not a calibration.

Fixture (`selfcheck/fixture.py`):
- `EXEMPT = {"run_id", "instance_id", "arm", "selfcheck_commit", "harness_ref", "harness_commit", "start_commit", "install", "prompt_template_hash", "images"}`; `conditions(manifest) -> dict` = manifest without EXEMPT keys; `fixture_id(conds) -> str` = first 16 hex of sha256 over `json.dumps(conds, sort_keys=True, separators=(",", ":"))`.
- `FixtureError(Exception)`.
- `assemble(run_dirs: list[Path], *, score_fn, out_root: Path, token: str, now=time.time) -> Path` — repeat k = position in `run_dirs` (1-based); for each baseline entry in each `run.json`: reads `manifest.json`, `state.json`, `prediction.json`. All present manifests must share identical `conditions` (else `FixtureError` naming the differing keys) and, per instance, identical `images` (else `FixtureError`). `score_fn(prediction) -> dict` for entries with a prediction; others get `score: null`. Writes `out_root/<fixture_id>/manifest.json` = `{"fixture_id", "conditions", "images": {iid: images}, "runs": [run_id…], "repeats", "instances": [iid…], "created_at"}` (`now()` epoch seconds; `instances` sorted), `predictions.jsonl` (each prediction plus `"repeat": k`, sorted by instance then repeat), `scores.json` = `{iid: [{"repeat", "run_id", "status", "score"}…]}`. Raises `FixtureError` when the directory already exists or when `token` occurs in any serialized output (nothing written in either case). Returns the directory.
- `create(instances: list[dict], *, repeats: int, cfg: dict, progress_path: Path, run_fn, resume_fn, assemble_fn) -> tuple[str, str]` — progress file JSON `{"instances": [iid…], "repeats", "run_ids": [...]}` created when absent; an existing file with different `instances` or `repeats` raises `FixtureError` naming the file. Run directories are `<cfg["runs_dir"] expanded>/<run_id>`. For each recorded run whose `run.json` has non-null `halted` or an entry `pending`/`interrupted`: `resume_fn(run_id)`; if `halted` is still non-null → return `("halted", run_id)`. Then while fewer than `repeats` runs: `run_dir = run_fn(instances, ["baseline"])`, append its id and save progress; if halted → `("halted", run_id)`. Finally `assemble_fn(run_dirs)`, delete the progress file, return `("done", str(fixture_dir))`.
- `compare(fixture_manifest: dict, manifest: dict) -> list[str]` — sorted keys of `conditions` that differ, plus `"images"` when `fixture_manifest["images"].get(iid) != manifest["images"]` (so an absent instance also yields `"images"`), plus `"instance_id"` when the instance is absent from the fixture; the result is sorted.
- `find(fixtures_root: Path, manifests: list[dict]) -> tuple[Path | None, dict[str, list[str]]]` — the first fixture directory (sorted by name) whose `compare` is empty for every manifest; otherwise None and `{fixture_id: sorted union of differing keys}` for every fixture.
- `precheck(fixtures_root: Path, cfg: dict) -> bool` — True iff some fixture's `conditions` equal these values derived from the effective agent config: `model`, `effort`, `aliases`, `sdk`, `disallowed_tools`, `caps` (`wall_clock_min`, `max_user_turns`, `idle_grace_s`), `container` (`cpus`, `memory`, `user: "nonroot"`).

Report (`selfcheck/report.py`):
- `METRICS = ("resolved", "f2p_frac", "swt_success", "kill_primary", "kill_secondary", "incompatible_frac")` from a score: `resolved` and `swt.success` as 1.0/0.0, `f2p_frac`, `kill.primary`, `kill.secondary`, `incompatible_frac`; a missing score gives None for all.
- `verdict(value, baseline_values) -> "above" | "within" | "below" | "n/a"` — n/a when `value` is None or no baseline value is non-None; above when `value > max`, below when `value < min`, else within (non-None baseline values only).
- `build(run_dir: Path, *, fixture_dir: Path | None, scores: dict, processes: dict, min_mutants: int) -> dict` — `scores` = `{instance_id: score dict}` (as read from `scores.harness.jsonl`, one score per line carrying `instance_id`), `processes` = `{instance_id: evaluate_entry result}`; `harness_ref`/`harness_commit` come from `<run_dir>/params.json`; baseline lists keep one position per repeat (None for a missing score); `range` is null when no baseline value is non-None; `status` = the `run.json` entry status; `elapsed_s` = `state.json` `elapsed_s` (None when absent); result = `{"run_id", "harness_ref", "harness_commit", "fixture_id" | null, "baseline": "compared" | "skipped", "instances": [{"instance_id", "status", "small_sample", "metrics": {m: {"harness", "baseline": [values by repeat], "range": [min, max] | null, "verdict"}}, "process": {check id: verdict}, "cost_usd", "elapsed_s"}], "notes": [...]}` for every harness entry in `run.json` order. `small_sample` = `kill.sampled < min_mutants` from the harness score (or the fixture's first non-null score when the harness score is missing). `cost_usd` = sum of `total_cost_usd` in `state.json` `results` (None when none). With `fixture_dir` None, baseline lists are empty, ranges null and verdicts n/a. `notes` always contains the no-significance note and, when any instance is small-sample, the small-sample note. No field carries transcript text, tool inputs or diffs.
- `render_markdown(report) -> str` — `fixture_id` in `build` is the fixture manifest's `fixture_id`, else the fixture directory name; a header with run id, harness ref/commit, fixture id or "baseline skipped"; one table per instance with columns metric | harness | baseline (per repeat) | range | verdict, kill rows suffixed `(참고용: 표본 작음)` when small-sample; a process table with header `check | verdict`; the notes.
- `write(report, results_dir: Path, *, token: str) -> tuple[Path, Path]` — writes `<run_id>.json` (sorted keys, indent 1) and `<run_id>.md`; raises `ReportError` and writes nothing when `token` occurs in either text.

CLI (`selfcheck/__main__.py`; `SUBCOMMANDS` gains `process`, `baseline`, `check`, `report`):
- `process RUN_ID` (no options): for each harness entry of the run, `evaluate_entry` with the score from `<run_dir>/scores.harness.jsonl` when present; writes `<entry_dir>/process.json`; prints `<iid> pass=<n> fail=<n> n/a=<n>` per entry; exit 0; unknown run → stderr `unknown run id: <id>`, exit 2.
- `baseline create [--instances a,b] [--repeats N]`: default all pool instances and `config.baseline.repeats`; exit 0 printing the fixture directory; exit 3 printing `halted in run <run_id>; rerun \`python3 -m selfcheck baseline create\` to resume`; exit 1 with the message on `FixtureError`, `TokenFileMissing` or `DockerError`.
- `check [--instances a,b] [--harness-ref REF] [--resume RUN_ID] [--no-baseline]`: default core instances; without `--no-baseline` and `--resume`, `precheck` false → exit 2 with `no baseline fixture matches the current conditions; run \`python3 -m selfcheck baseline create\`` before any docker call. Then harness-arm `run.run` (or `run.resume`); halted → exit 3 with `resume with: python3 -m selfcheck check --resume <run_id>`, writing no scores file, no `process.json` and no results. Then scores every harness prediction into `<run_dir>/scores.harness.jsonl`, writes `process.json` per entry, and reports as `report` does.
- `report RUN_ID [--no-baseline]`: reads `scores.harness.jsonl` (when present) and `process.json` files (computing missing ones); without `--no-baseline`, `find` over the entries' manifests; no match → exit 2 printing, per fixture, `fixture <id> differs in: <keys>` (or `no baseline fixture exists`) and the `baseline create` hint, writing nothing. Otherwise writes the results and prints both paths; exit 0.
- `ReportError` and token-file absence for `report`/`check` → exit 1 with the message.
- Streams: refusals, errors, halt messages and resume/creation hints go to stderr; success output (written paths, fixture directory, the run directory, `process` summary lines) goes to stdout.

Docs: README section `## 자체 점검 (selfcheck)` placed before `## 세션 로그 분석 (개발 중)`; AGENTS.md Source line lists `selfcheck/` (self-check tool, not installed).

# Functional Requirements
| id | requirement | priority | source |
| --- | --- | --- | --- |
| FR1 | `halt_reason` and batch halting in `run` and `resume` as in Signatures; no entry starts after a halting entry | must | user decision (한도 처리: 즉시 배치 중단) |
| FR2 | `cmd_run` exit codes and halt message as in Signatures | must | user decision |
| FR3 | `process.evaluate_entry` inputs, identity, spec parsing, path matching and malformed-line handling as in Signatures | must | plan "프로세스 준수" |
| FR4 | Checks PC1–PC11 and metrics exactly as in Signatures | must | plan §3 table |
| FR5 | `fixture.conditions`, `fixture_id`, `assemble` outputs and errors as in Signatures | must | plan "Comparability manifest" |
| FR6 | `fixture.create` progress, resume and halt behaviour as in Signatures | must | plan "baseline create --repeats 2"; FR1 |
| FR7 | `fixture.compare`, `find`, `precheck` as in Signatures | must | UI3 |
| FR8 | `report.verdict`, `build`, `render_markdown`, `write` as in Signatures | must | plan "리포트"; user decision (표본 작음 표시) |
| FR9 | CLI `process`, `baseline create`, `check`, `report` with the exit codes and messages in Signatures | must | plan "디렉터리와 CLI" |
| FR10 | README "자체 점검" section (prerequisites, command order `pool`→`images`→`validate`→`mutants`→`calibrate`→`images --agent`→`baseline create`→`check`, subscription-quota warning and exit 3/resume, where results go, how to read above/within/below and small-sample flags, no-significance caveat); AGENTS.md Source line lists `selfcheck/` | should | plan M3 |

# Errors
- Unknown run id for `process`/`report`/`check --resume` — stderr `unknown run id: <id>`, exit 2 — nothing written.
- Token file missing for `baseline create`/`check`/`report` — stderr `token file missing: <path>`, exit 1 — nothing written, no docker call.
- No comparable fixture (`check` pre-check or `report`) — exit 2 with differing keys / hint — no results files; for `check` after its run, run artifacts, scores and `process.json` remain.
- Token found in a report or fixture output — `ReportError`/`FixtureError`, exit 1 — no results or fixture files written.
- Baseline progress parameter mismatch — `FixtureError` naming the progress file, exit 1 — progress file unchanged, no run started.
- Baseline conditions differ across entries — `FixtureError` naming keys, exit 1 — no fixture directory; progress file kept.
- Fixture directory already exists — `FixtureError`, exit 1 — existing fixture untouched.
- Malformed telemetry/ledger line — no exception; `skipped_lines` incremented.
- Halt — exit 3 with resume hint — `run.json.halted` set; remaining entries `pending`; interrupted container kept (M2 behaviour).

# Cases
| id | level | input / state | expected result |
| --- | --- | --- | --- |
| C1 | normal | three entries; second ends `completed` with `rate_limit.status == "allowed_warning"` | third never starts; `run.json.halted == {"reason": "rate_limit:allowed_warning", ...second}`; third `pending`; `cmd_run` exit 3 |
| C2 | normal | second entry `interrupted` (rejected) | same as C1 with reason `interrupted` |
| C3 | normal | resume of C1 run, all entries then complete with `allowed` | third runs; `halted` null; exit 0 |
| C4 | boundary | `rate_limit` None / status `allowed` on every entry | no halt; all entries run; `halted` null |
| C5 | boundary | halting entry is the last entry | `halted` set, exit 3 |
| C6 | normal | synthetic compliant harness entry (start, implement_test, verify, verifier pass, verification_result, paired seeds, archived spec complete, roles separated) | PC1–PC10 pass, PC11 pass with a resolved + SWT-success score |
| C7 | error | each single violation: no start; compliance reason; 3 verifier results; 3 verifier dispatches; complete without verification_result; unpaired backup; seed pending; archive status mismatch; handoff spec not active; main test edit after spec write; implementer reads a Tests file; test-implementer reads an Implementation file; test-verifier Bash `cat` of an Implementation file; edit after final pass; complete but unresolved; complete but SWT failure | exactly the targeted check fails, with the evidence lines its rule names (absence failures: empty); the "no start" row fails PC1 and PC2 only |
| C8 | edge | main test edit before the first spec write; Bash containing a Tests directory entry; absolute path outside /testbed | PC8 / PC9 pass |
| C9 | edge | missing telemetry dir / ledger / full.diff / prediction; garbage lines | no exception; missing telemetry: PC1, PC2 fail, PC3–PC5 n/a; missing full.diff: PC8–PC10 n/a, PC7 fail when `end_status` is set; missing prediction: PC6 n/a; `skipped_lines` counts the garbage |
| C10 | normal | baseline arm entry | every check n/a, detail `baseline arm` |
| C11 | normal | two baseline runs, equal conditions | fixture written with id = hash of conditions; predictions with repeat; scores per repeat, null for error entries |
| C12 | error | conditions differ (e.g. `cli_version`) / images differ / directory exists / token in output | `FixtureError`, nothing written |
| C13 | normal | `create` with no progress, run_fn halts on repeat 1 | returns `("halted", id)`; progress records the id; rerun resumes that id, then runs repeat 2, assembles, deletes progress |
| C14 | error | progress with different instances | `FixtureError`, no run_fn/resume_fn call |
| C15 | normal | `compare` / `find` with matching fixture; with a fixture differing in `model`; with a different `selfcheck_commit`, `start_commit`, `prompt_template_hash` only | match; `["model"]`; match (exempt) |
| C16 | normal | `precheck` with fixture matching cfg; with fixture differing only in effort; no fixtures dir | True; False; False |
| C17 | boundary | `verdict` at value == max, == min, max+ε, min−ε, None, all-None baseline | within, within, above, below, n/a, n/a |
| C18 | normal | report with fixture: small-sample instance (sampled 4) and normal (sampled 18) | small-sample flag and Markdown suffix only on the first; notes include both notes |
| C19 | error | CLI: unknown run; `check` without fixture (no docker call); `report` with incomparable fixture (exit 2, no files); halted `check` (exit 3); token file missing | exit codes and messages as in Signatures |
| C20 | edge | report without scores file | metrics n/a, file still written |

# Quality Applicability
| ISO/IEC 25010:2023 characteristic | applicable | rationale |
| --- | --- | --- |
| Functional suitability | yes | the verdicts and comparisons are the product |
| Performance efficiency | no | offline analysis of small files; agent run cost is bounded by M2 caps and recorded, not scored |
| Compatibility | yes | must read real M2 run artifacts and reuse `analytics.compliance` unchanged |
| Interaction capability | yes | CLI refusals and halts must tell the maintainer what differs and what to run next |
| Reliability | yes | halting must stop quota use; malformed evidence must not crash analysis; baseline creation must survive interruption |
| Security | yes | results and fixtures are committed; the OAuth token must never reach them |
| Maintainability | yes | M1/M2 evidence must keep passing; branch coverage target |
| Flexibility | no | single host, single runtime by design |
| Safety | no | no physical or human-safety effect |

# Quality Requirements
| id | characteristic / subcharacteristic | target and context | measure method / inputs / unit | threshold and direction | evidence: automated, review, mutation | source |
| --- | --- | --- | --- | --- | --- | --- |
| QR1 | Functional suitability / correctness | process verdicts | per C6–C10 synthetic entry, the check whose verdict differs from the expected table; count | 0 | automated (VO2, VO3), R1 | plan §3 |
| QR2 | Functional suitability / correctness | report verdicts and fixture comparison | C15–C18 outputs vs expected; count of mismatches | 0 | automated (VO5, VO6, VO7) | plan "리포트" |
| QR3 | Compatibility / interoperability | real M2 artifacts | R1: `process` on the smoke run completes, `skipped_lines` = 0, PC8 and PC5 match the hand reading | all hold | review R1 | M2 R1 |
| QR4 | Interaction capability / user error protection | refusals and halts | each C19 refusal message names the differing keys or the next command; exit codes 2/3 distinct from 1 | all C19 rows | automated (VO8) | UI3, UI4 |
| QR5 | Reliability / fault tolerance | quota stop | entries started after a halting entry; count | 0 | automated (VO1) | user decision |
| QR6 | Reliability / recoverability | baseline creation across halts | after C13, fixture equals one assembled from the same runs without interruption | equal | automated (VO4) | UI4 |
| QR7 | Security / confidentiality | committed outputs | occurrences of the token value in report JSON/MD and fixture files written by any test with a planted token | 0, and the write is refused | automated (VO4, VO6) | M2 UI3 |
| QR8 | Maintainability / modifiability | prior evidence and new modules | all existing selfcheck tests pass (with `test_run.py` updated only where FR1 changes continue-after-interrupt); branch coverage over the Test command `--include` list | all pass; ≥ 90% | automated (Test command) | M2 QR10 |

# Verification Obligations
| id | parent requirement/Case ids | variant and target surface | test layer and selection policy | ISO/IEC/IEEE 29119-4 technique | coverage items | coverage target | observation and expected result | evidence procedure |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| VO1 | FR1, FR2, C1–C5, QR5 | `run.run`/`run.resume` with the M2 fake docker and scripted driver states; `cmd_run` | integration (fake docker) | decision table | D1 interrupted; D2 rejected rate limit with completed status; D3 allowed_warning; D4 allowed; D5 None; D6 halt at last entry; D7 resume after halt clears then completes; D8 resume halts again; D9 exit precedence halted+error → 3 | 100% | driver invocations count, `run.json` `halted`/statuses, exit code, stderr hint | Test command |
| VO2 | FR3, FR4, C6–C10, QR1 | `process.evaluate_entry` on synthetic entry dirs built by `m3_fakes` | unit | equivalence partitioning | one compliant class (C6); one failing class per C7 row (16); edge classes C8 (3); missing-input classes C9 (4 missing + garbage); baseline C10 | 100% | `checks[id].verdict`, evidence line numbers, `skipped_lines` | Test command |
| VO3 | FR4 | PC3 counts, PC5 sequence | unit | boundary value analysis (2-value) | verifier results 2/3; dispatches 2/3; seed sequences: [] (fail), [b,r] pass, [b,b,r] fail, [b,r,b] fail, [r] fail | 100% | verdict | Test command |
| VO4 | FR5, FR6, C11–C14, QR6, QR7 | `fixture.assemble`/`create` with fake run dirs and stub run/resume/score functions | unit | state transition | states: no progress → running → halted → resumed → assembled → progress deleted; transitions T1 start, T2 halt, T3 resume-halt, T4 resume-complete, T5 new repeat, T6 assemble, T7 mismatch error, T8 conditions differ, T9 images differ, T10 dir exists, T11 token present | 100% | return values, progress file content, written files, call log | Test command |
| VO5 | FR7, C15, C16 | `compare`/`find`/`precheck` | unit | equivalence partitioning | each EXEMPT key except `images` changed alone (9) → no difference; `images` changed for one instance → `["images"]`; non-exempt keys changed alone: model, effort, cli_version, user_sim_hash, tools, caps, network → reported; images per-instance; instance absent; empty fixtures dir; precheck match / mismatch per cfg key (7) | 100% | returned key lists / booleans | Test command |
| VO6 | FR8, C17, C18, C20, QR2, QR7 | `report.verdict`, `build`, `render_markdown`, `write` | unit | boundary value analysis (3-value) for `verdict`; equivalence partitioning for build/write | verdict items of C17; small-sample below / at / above `min_mutants` (9, 10, 11); fixture vs `None`; missing score; token present | 100% | values, flags, Markdown substrings, files absent on refusal | Test command |
| VO7 | FR8 | report content restrictions | unit | error guessing | guessed defects: transcript text leaks (a planted marker in `messages.jsonl` and ledger `tool_input` must not appear in outputs); diff text leaks (planted marker in `full.diff`); cost summed wrongly across multiple results | none — experience-based | marker absence; cost value | Test command |
| VO8 | FR9, C19, QR4 | CLI via `__main__.main(argv)` with patched run/resume/score/fixture paths | integration (no docker) | decision table | each command × outcome: process ok/unknown; baseline done/halted/error; check precheck-fail (no docker call)/halted/ok/no-fixture-after-run; report ok/no-fixture/--no-baseline/unknown; token missing | 100% | exit code, stdout/stderr text, files written or absent | Test command |
| VO9 | FR10 | README, AGENTS.md | review | none (review) | R3 items | all | present | R3 |
| VO10 | QR3 | smoke run replay | review | none (review) | R1 items | all | as listed in Review evidence | R1 |
| VO11 | QR8 | whole selfcheck suite | integration | branch testing (structure-based, coverage.py) | branches of the `--include` list | ≥ 90% | coverage report | Test command |

# Assumptions and Defaults
| id | decision | evidence and uncertainty | brief v1 — approved / vetoed → <answer> / user answer |
| --- | --- | --- | --- |
| A1 | Code first via this workflow; live baseline (12 runs) and harness check (3 runs) afterwards, each step confirmed by the user | plan answer "코드 먼저, 실행은 단계별" | user answer |
| A2 | Pool unchanged; kill metrics flagged `참고용` when `kill.sampled < 10` | plan answer "유지, 리포트에 경고"; astropy-14365 has 4, django-15731 has 1 compile-valid mutants | user answer |
| A3 | Halt on `interrupted` and on any non-`allowed` rate-limit status including `allowed_warning` | plan answer "즉시 배치 중단"; extra usage is off (user) | user answer |
| A4 | Branch `selfcheck-m1`; commit only on request | plan answer | user answer |
| A5 | Comparability exempt keys = EXEMPT (run identity, `selfcheck_commit`, harness identity, start commit, install, prompt template hash, per-instance images compared separately per instance) | including `selfcheck_commit` would invalidate the 12-run baseline on every commit; scorer/runner changes that matter are caught by `user_sim_hash`, `cli_version`, `tools`, `sdk`, caps; uncertainty: a runner change outside driver/user_sim (e.g. run.py extraction) is not detected | user answer (brief v1 Q1: recommended) |
| A6 | Process evidence = ledger + telemetry + `full.diff`; transcripts are not parsed | smoke run: the ledger has every tool call with `agent_type`; the Skill tool is not used for a slash command, so "skill invoked" = `workflow_start` exists | brief v1 — approved |
| A7 | PC8 counts main test edits only after the first spec write; PC9 Bash matching only for file entries | before a spec exists no Tests paths are declared; directory entries in Bash (e.g. `pytest tests/`) would flag test runs | brief v1 — approved |
| A8 | False pass = harness reported `complete` but the run is unresolved or SWT fails; kill-rate comparison is left to the report's verdicts | a kill threshold would be arbitrary with 1–40 mutants | brief v1 — approved |
| A9 | Baseline `capped`/`stalled` entries are scored as they are; `error` entries are kept with `score: null`; no automatic rerun | reruns cost quota; the report shows missing values | brief v1 — approved |
| A10 | `check` refuses before running when no fixture matches the config-derived conditions (`--no-baseline` overrides) | prevents spending quota on an incomparable run | brief v1 — approved |
| A11 | Report and fixture files are committed (`selfcheck/results/`, `selfcheck/fixtures/baseline/`); writes are refused if the token occurs | plan "results/<run_id>.json 요약만 커밋" | brief v1 — approved |
| A12 | Exit code 3 = halted (resume needed), 2 = refused/unknown, 1 = error | distinct from M2's 1/2 | brief v1 — approved |
| A13 | Coverage target 100% of listed coverage items; ≥ 90% branch on the `--include` list; mutmut sample 300 seed 1, threshold 40% | M1/M2 policy | brief v1 — approved |

# Traceability
| requirement id | Case ids | obligation ids | evidence procedure |
| --- | --- | --- | --- |
| FR1, FR2 | C1–C5 | VO1 | Test command |
| FR3, FR4 | C6–C10 | VO2, VO3, VO10 | Test command, R1 |
| FR5, FR6 | C11–C14 | VO4 | Test command |
| FR7 | C15, C16 | VO5 | Test command |
| FR8 | C17, C18, C20 | VO6, VO7 | Test command |
| FR9 | C19 | VO8 | Test command |
| FR10 | — | VO9 | R3 |
| QR1–QR8 | — | as listed in Quality Requirements | as listed |

# Workflow Control
| item | value |
| --- | --- |
| correction batches used | 5 |
| verifier invocations | 3 |
| user-granted extra verifier invocations | 1 ("1회 추가."; effective limit 3 for this run) |
| open finding ids | none |

Audit state (one entry per obligation; retain prior decisions in the execution ledger):
| obligation id | spec version | evidence references and revision | accepted / open / invalidated / pending | rationale and mutation outcome | dependencies and reopening evidence |
| --- | --- | --- | --- | --- | --- |
| VO1–VO11 | 6 | X3–X7, V1–V3 audit maps | accepted (verifier 3) | M1–M15 detected; mutmut 15% survival, declared survivors killed, 26 equivalent, 7 undeclared pinned (v5) | none open |

Execution ledger (append attempts; preserve failed approaches):
| attempt | finding / failure signature | cause hypothesis | changed approach / new evidence | result / disposition |
| --- | --- | --- | --- | --- |
| X1 | Test command after batch 1: 776 tests OK (7 skipped), exit 0, coverage 97% total; process 96%, fixture 98%, report 100%, run 95% | — | uncovered new lines are defensive branches (no manifests, malformed frontmatter, unknown end_status, non-dict tool_input) — within the 90% target | accepted |
| X2 | R3: README command order omits `images --agent`; `run` only references derived agent images by name, so a run without it fails | spec gap in FR10 order | v3 adds `images --agent`; implementer edits README | batch 2 |
| X3 | R1 replay on smoke run 9f9be4f8c2b2986e: score exit 0 (resolved False, f2p 0.0, SWT False, kill 0/18, incompatible 1.0); process exit 0, `pass=6 fail=4 n/a=1`, skipped_lines 0; PC8 fail evidence ledger 41,45,54,55,56 and PC5 fail evidence telemetry 11,16,22 match a hand reading (spec write at ledger 18, pre-spec test edit at 9 excluded; 3 backups, 0 restores); PC11 fail (complete but unresolved; self-reported kill 1/1 vs measured 0.0); `report` exit 2 with `no baseline fixture exists` + hint on stderr; `report --no-baseline` exit 0 wrote JSON+MD (deleted afterwards, smoke output not committed) | — | QR3 met | accepted |
| V1 | verifier 1: RETRY — F1 assemble sort untested (inputs pre-sorted); F2 Markdown cell contents unasserted; F3 params.json vs manifest refs indistinguishable; F4 run-event scoping/ordering for PC4, PC5, PC10 untested; S1 report `status`/`elapsed_s` sources undefined; advisories A1 precheck keys max_user_turns/idle_grace_s/cpus/user, A2 token in fixture manifest.json, A3 all-None baseline range, A4 halted check writes nothing, A5 ledger-missing PC9 | F1–F4 test evidence gaps; S1 spec omission | v4 pins S1 (status from run.json, elapsed_s from state.json), A3 (range null), A4 (halted check writes nothing); test batch 3 covers F1–F4 and A1–A4 | open |
| H1 | hand mutations M1–M11 (halt_reason allowed_warning, loop continues, resume keeps halted, error beats halt, PC8 anchor, PC9 Bash dirs, prefix without /, EXEMPT misses selfcheck_commit, verdict >= max, check skips precheck, PC5 stray restore) | — | one at a time with seed backup/restore | all 11 detected by the intended tests; restore verified |
| MT1 | mutmut 300 sampled (seed 1, 1324 eligible): 255 killed, 45 survived (15% < 40%); survivors rerun on the full offline suite after batch 3: 1 more killed, 44 survived | — | mutant-triager ×2 + main rechecks | 26 equivalent (rechecked mm001/002/008/035 unused or unread values, mm014/018/020/022/028 by code reading; none overturned); 11 declared → batch 4 evidence gaps: mm003 relative config dir resolution, mm004 CLI score_fn passes a real evaluate_fn, mm005 `fixture <id> differs in:` text, mm006 check prints run dir on stdout, mm009 conditions differ between first two manifests only, mm013 halted-only run resumed, mm017 dot in a non-last component of a directory entry, mm019 metrics without spec text, mm025 PC6 evidence file, mm033 suffix ends the kill metric cell, mm039 exact table header line; 7 undeclared (mm007, mm015, mm016, mm023, mm026, mm032, mm036) → v5 pins current behavior |
| X5 | batch 3 (F1–F4, A1–A4, S1 tests) and batch 4 (11 declared mutants G1–G10 + v5 pins) — tests only; implementation unchanged since batch 2 | — | Test command after batch 4: 801 tests OK (7 live skipped), exit 0, total 97%, process 97%, fixture 98%, report 100%, run 95%; the 11 declared mutants rerun on the full offline suite: 11/11 killed; token occurrences in repo outputs 0 | accepted pending verifier 2 |
| V2 | verifier 2 (last): RETRY — EG1 `~`-prefixed runs_dir/progress untested (VO4, VO8); EG2 PC10 main-agent edit after anchor untested (VO2); EG3 report with missing state.json / elapsed_s untested (VO6); VO5 accepted; advisories PC6 contains, PC5 second-file evidence, non-new-file spec section | test evidence gaps; main read implementation: all three behave correctly | budget exhausted — stop with limit, handoff 1ba36300e7469498 | open |
| R4 | user granted one more verifier invocation ("1회 추가."); spec restored from `spec-logs/` to `specs/`, status active (lifecycle tool requires frontmatter 2; grant recorded in Workflow Control); handoff 1ba36300e7469498 stays referenced until completion | — | correction batch 5 for EG1–EG3 | resumed |
| X6 | batch 5 (EG1–EG3 + PC6/PC5 advisories), tests only | — | confirming mutations M12 runs_dir unexpanded in create, M13 CLI paths unexpanded, M14 PC10 ignores main rows, M15 elapsed_s default 0 — all detected by the EG tests; Test command: see X7 | accepted pending verifier 3 |
| X7 | Test command after batch 5: 807 tests OK (7 live skipped), exit 0; coverage process 97%, fixture 98%, report 100%, run 95%, total 97%; no `<repo>/~`, no `selfcheck/results`; token occurrences 0 | — | — | accepted pending verifier 3 |
| V3 | verifier 3 (user-granted): PASS — EG1–EG3 closed (M12–M15 detected); all obligations accepted or retained; advisories: EG3 missing-state cost not isolated from empty results, PC6/PC5 pins added | — | no open blocking finding | pass |
| X4 | R2: no comments added in new/changed Implementation files; R3: README section covers all four subcommands, exit 3 and resume, quota warning, results location, verdict reading; `images --agent` added (batch 2); AGENTS.md Source line lists `selfcheck/` | — | — | accepted |

# Version Log
## v6
- Closed complete after verifier 3 PASS; handoff moved to stale.
- User granted one extra verifier invocation; spec reopened (R4). No contract change.

## v5
- Mutant triage (MT1) undeclared behaviors pinned as implemented: spec text without frontmatter has no status; missing/empty/non-string ledger paths ignored; PC5 evidence includes a seed event after workflow_end; PC6/PC11 failure evidence prediction.json line 1; report fixture_id source; `process` takes no options. Contract-only.

## v4
- Verifier 1 S1: `report.build` `status` = run.json entry status, `elapsed_s` = state.json `elapsed_s`; `range` null with no baseline values (A3); halted `check` writes no scores/process/results (A4). Contract-only.

## v3
- FR10 command order adds `images --agent` (R3 finding X2: agent images are not built by `run`). Contract-only.

## v2
- Contract clarifications from reconciliation (no brief item changed): PC1/PC2 fail on missing telemetry for a harness entry; absence failures carry empty evidence; PC7 fails when full.diff lacks the spec and the workflow ended; blank lines ignored, evidence uses physical line numbers; `compare` on an absent instance yields `images` and `instance_id`; VO5 exempt items are 9 plus the per-instance images rule; `report.build` input shapes and `params.json` as ref source; process table header `check | verdict`; stream policy (refusals/hints → stderr); fixture `created_at` and runs dir. Sources: implementer and test-implementer reports, challenges 1–16.

## v1
- Initial draft from the approved plan `ticklish-napping-clarke.md` and its user decisions (A1–A4).

---
version: 4
run_id: 2974883932c47b32
status: complete
base_commit: 751077f0630da283094d4724848e901077fe0f8d
max_verifier_invocations: 2
handoff: none
---

# User Intent
| id | stakeholder | intention | observable goal |
| --- | --- | --- | --- |
| I1 | harness maintainer | Process checks must see spec and file writes made through Bash, not only through Edit/Write | Reprocessing run a41e64cb9bbbef03 gives PC8 a pass/fail verdict on every instance instead of n/a |
| I2 | harness maintainer | A spec written after implementation must fail a check | Reprocessing a41e64cb9bbbef03 gives astropy-14365 PC12 = fail |
| I3 | harness maintainer | Implementer test runs are not cross-role access; reading or editing a test file is | PC9 ignores `pytest` runs, fails on `cat tests/...` by the implementer, and counts test runs as a metric |
| I4 | harness maintainer | The harness arm can be repeated so a harness effect can be told apart from run-to-run variance | `check --repeats N` (default 3) runs N repeats per instance in one run; the report shows each repeat, a summary, and the baseline range |

# Scope
In scope: Bash command write/read/test-run classification for process checks; PC8, PC9, PC10, PC12 and `main_implementation_edits` on top of it; harness-arm repeats inside one run (run, resume, predictions, scores, process, review, report); report JSON/Markdown for repeats; `baseline.repeats` default 3; report notes for simulator limitation and PC5 instrumentation; README selfcheck section.
Out of scope: new live runs; harness-side `telemetry_hook.match_seed` fix; test-quality audit items P1–P10; user simulator changes; regenerating existing baseline fixtures; changing `fixture_id` conditions; repeats for `run` subcommand arms other than through `check`.

# Paths
Implementation: selfcheck/bashparse.py, selfcheck/process.py, selfcheck/run.py, selfcheck/report.py, selfcheck/__main__.py, selfcheck/config.json, README.md
Tests: selfcheck/tests/test_bashparse.py, selfcheck/tests/test_process.py, selfcheck/tests/test_report.py, selfcheck/tests/test_report_review.py, selfcheck/tests/test_cli_m3.py, selfcheck/tests/test_cli_review.py, selfcheck/tests/m3_fakes.py, selfcheck/tests/test_run.py, selfcheck/tests/test_halt.py, selfcheck/tests/test_cli_run.py, selfcheck/tests/test_fixture.py
Test command: uv run --python 3.12 --with-requirements selfcheck/requirements.txt --with coverage==7.16.2 sh -c 'export COVERAGE_FILE="$HOME/.harness/selfcheck/.coverage" && mkdir -p "$HOME/.harness/selfcheck" && SELFCHECK_DOCKER=1 python -m coverage run --branch --source=selfcheck,analytics -m unittest discover -s selfcheck/tests -t . && python -m coverage report --fail-under=90 --include="selfcheck/patches.py,selfcheck/pool.py,selfcheck/validate.py,selfcheck/mutants.py,selfcheck/score.py,selfcheck/calibrate.py,selfcheck/agent/user_sim.py,selfcheck/agent/driver.py,selfcheck/extract.py,selfcheck/manifest.py,selfcheck/run.py,selfcheck/process.py,selfcheck/fixture.py,selfcheck/report.py,selfcheck/bashparse.py,selfcheck/__main__.py"'
Review evidence: R1 offline replay on live run `~/.harness/selfcheck/runs/a41e64cb9bbbef03` (no agent run): main runs `python3 -m selfcheck process a41e64cb9bbbef03` and `python3 -m selfcheck report a41e64cb9bbbef03`; expected: PC8 not n/a on all 3 instances, astropy PC12 = fail with evidence at ledger line 3, seaborn and sphinx PC12 = pass, the report renders with one repeat per instance and both new notes. Main checks each verdict by hand against `raw/ledger.jsonl`. R2 comment review of every changed Implementation file against AGENTS.md Comment Enforcement. R3 README review: `check --repeats`, PC1~PC12, baseline default 3.
Fuzzing: stdlib `random` harness (scratchpad script) over `bashparse.classify`, surface: arbitrary command strings built from a token alphabet (`>`, `>>`, `<<EOF`, `EOF`, `'`, `"`, `$X`, `X=a/b.py`, `cd`, `;`, `&&`, `|`, newline, `sed -i`, `tee`, `python -`, `open(p,'w')`, paths, random printable text), oracle: crash (any exception) plus property "every returned path is a str not starting with `/`", seed 1, budget 50000 inputs.
Mutation tool: mutmut 2.5.1 over Implementation Python lines changed since base_commit, runner `python -m unittest discover -s selfcheck/tests -t .` without `SELFCHECK_DOCKER`, sample cap 300, seed 1, survival threshold 40%.

# Signatures
selfcheck/bashparse.py: `classify(command: str) -> dict` returning `{"writes": list[str], "reads": list[str], "test_runs": int, "mentions": list[str], "unknown": bool}`; all paths repo-relative (testbed-relative), normalized, no leading `/`.
selfcheck/process.py: `CHECK_IDS = ("PC1", …, "PC12")`; `evaluate_entry(entry_dir, *, score=None) -> dict` (shape unchanged except PC12 and new metrics `implementer_test_runs: int`, `unknown_bash_accesses: int`).
selfcheck/run.py: `run(instances, arms, *, cfg, harness_ref="HEAD", model=None, effort=None, cap_min=None, repeats=1, docker=..., now=...) -> Path`; `entry_dir(run_dir, entry) -> Path` (`<iid>/<arm>` when entry has no `repeat` key, else `<iid>/<arm>-r<repeat>`); `entry_repeat(entry) -> int` (`entry.get("repeat", 1)`).
selfcheck/report.py: `build(run_dir, *, fixture_dir, scores, processes, min_mutants, reviews=None) -> dict` where `scores`, `processes`, `reviews` are keyed by `(instance_id, repeat)`.
selfcheck/__main__.py: `check --repeats N` (int, default `CONFIG["check"]["repeats"]`).

# Functional Requirements
| id | requirement | priority | source |
| --- | --- | --- | --- |
| F1 | `classify` splits a command into segments at `;`, `&&`, `\|\|`, `\|`, `&` and newlines outside quotes and heredoc bodies; heredoc bodies (`<<WORD`, `<<'WORD'`, `<<"WORD"`, `<<-WORD`) are attached to their segment and never parsed as commands. | must | handoff item 4 |
| F2 | Simple assignments `NAME=value` (as their own segment or as prefix) are recorded; later `$NAME` / `${NAME}` in the same command expand to the recorded value; an unrecorded variable (including `$(...)` command substitution) stays literal text in the path. | must | live ledgers use `F=agent-docs/specs/$RID-x.md; cat > $F` |
| F3 | `cd DIR` sets the working directory for later segments of the same command; each command starts at `/testbed`. Paths are resolved against it and normalized: `/testbed/x` → `x`, other absolute paths and paths escaping `/testbed` are dropped, `./` and `..` are collapsed. | must | seaborn ledger `cd /testbed/tests; ... _core/test_plot.py` |
| F4 | Writes: target of `>`, `>>`, `&>`, `>\|` redirection (not `N>&M`, not `/dev/null`); every file argument of `tee` (with or without `-a`); file arguments of `sed -i…`/`sed --in-place` (arguments after the script; with `-e`/`-f` all non-option arguments); last argument of `cp`, `mv`, `install`; for `python`/`python3` (`-c CODE` or a heredoc body or `-` script) that contains a write call (`open(` with a mode literal containing `w`, `a`, `x` or `+`, `.write_text(`, `.write_bytes(`), every string literal in the code that looks like a path (contains `/` or ends in a dotted extension) plus each positional argument after `-`/the code; when the code writes but yields no path, `unknown` is true. `git apply`, `patch`, `git checkout -- …`/`git restore` set `unknown` true. | must | handoff item 4, user decision Q2 |
| F5 | Reads: file arguments of `cat`, `head`, `tail`, `less`, `more`, `nl`, `grep`, `egrep`, `rg`, `awk`, `sed` without `-i`, `diff`, `wc`, and of `python` code that calls `open(`/`read_text(` without a write mode (string literals as in F4). The command list has 13 entries. | must | user decision Q1 |
| F6 | Test runs: a segment whose command (after stripping leading `NAME=v` assignments, `timeout [opts] N` where opts are `-s SIG`, `-k DUR`, `--signal=SIG`, `--kill-after=DUR`, `--foreground`, `--preserve-status`, `-v`, `env`, and after variable expansion) is `pytest`, `py.test`, `tox`, `nox`, or `python[3] [-W x] -m pytest|unittest|tox` counts one test run; its path arguments are not reads. | must | user decision Q1 |
| F7 | `mentions`: paths appearing as arguments of segments not classified by F4–F6. `unknown` is true when any segment could not be parsed (unbalanced quotes, unterminated heredoc) or matches an F4 unknown form. `classify` never raises. | must | plan |
| F8 | process: a ledger row writes a path when it is an EDIT_TOOLS row naming the path or a row with `tool_name == "Bash"` (only Bash rows are classified) whose `classify(...)["writes"]` contains it. `spec_write` is the first ledger row writing a path under `agent-docs/specs/` (by `_matches`). PC8, PC10 and `main_implementation_edits` count writes by this definition. Matching of a path to an entry uses `_matches`; a path containing unresolved `$` text matches entry E iff D = the text before the first `$` is non-empty and `_matches(D, E)` holds (so `tests/$N.py` matches directory entry `tests/` but not file entry `tests/test_a.py`; an empty D matches nothing). `_matches(p, E)` is `p == E`, or `p` under directory `E` with or without a trailing slash on E (`src.v2/pkg/a.py` matches `src.v2/pkg`), or fnmatch. | must | handoff items 4, Q2 |
| F9 | PC12 (spec before implementation): n/a when no spec text (this includes a missing workflow_start or full.diff), when the ledger is missing or has no rows, or on the baseline arm; otherwise collect rows by main (`agent_type` null) or `implementer` that write an Implementation or Tests path; pass if none; fail if `spec_write` is None or the first such row precedes `spec_write` in ledger order, with evidence = that first row; pass otherwise. | must | handoff item 5 |
| F10 | PC9: a Bash row by `implementer` is a cross-role access only when `classify` reports a Tests path in `reads` or `writes`; same for `test-implementer`/`test-verifier` against Implementation paths. Non-Bash rows keep the existing path rule. Bash rows of these roles where an entry appears only in `mentions` add 1 to `unknown_bash_accesses` and do not fail. `implementer_test_runs` = sum of `test_runs` over implementer Bash rows. | must | Q1 |
| F11 | `run.run(..., repeats=N)`: N=1 produces entries without a `repeat` key and the existing layout; N>1 produces, per instance and arm, entries `{"instance_id", "arm", "repeat": k, "status"}` for k=1..N in order instance → repeat → arm, each in `entry_dir`. Every place that maps an entry to its directory (`_run_entry`, `_halt_after`, `resume`, `_write_predictions`) uses `entry_dir`. Container names stay unique per entry. `halted` records include `repeat` when present. | must | handoff item 7 |
| F12 | Prediction lines for a repeated entry carry `"repeat": k`; legacy runs and N=1 runs carry no `repeat`. `check` writes `scores.harness.jsonl` rows with the prediction's `repeat` (default 1); score lookup, `_process_entries`, `review`, and `_emit_report` key by `(instance_id, repeat)` and use `entry_dir`. | must | handoff item 7 |
| F13 | `check --repeats N` (default `config.check.repeats` = 3) passes `repeats` to `run.run`; `--resume` ignores it. `config.baseline.repeats` = 3. `fixture.conditions`/`fixture_id` are unchanged. N < 1 → argparse-level error exit 2. | must | Q3 |
| F14 | `report.build`: one item per instance (in first-appearance order) with `instance_id`, `small_sample`, `repeats` (list, ordered by repeat, each `{"repeat", "status", "metrics": {m: value}, "process": {cid: verdict}, "cost_usd", "elapsed_s", "review", "review_findings"}`), `metrics` (per METRIC: `harness` list of per-repeat values, `harness_summary`, `baseline`, `range`, `verdict`, `repeat_verdicts`), and `process_fails` `{cid: number of repeats with verdict fail}`. | must | Q3 |
| F15 | `harness_summary`: for `resolved` and `swt_success` → `{"k": count of 1.0, "n": count of non-None}`; for other metrics → `{"median", "min", "max"}` over non-None values (median of even count = mean of the middle two); `None` when no value is present. `verdict` = `verdict(median of non-None harness values, baseline)`; `repeat_verdicts` = counts of `above`, `within`, `below`, `n/a` over each repeat value. | must | Q3 |
| F16 | `small_sample` uses the first non-None `kill.sampled` across repeats, else across fixture scores (existing fallback). `false_claims` entries include `repeat`. | must | existing behavior |
| F17 | Markdown: per instance a metric table `\| metric \| r1 \| … \| rN \| summary \| baseline (per repeat) \| range \| verdict \| repeats above/within/below \|`, a cost line per repeat, a check table `\| check \| r1 \| … \| rN \| fails \|`, and per repeat a review subsection headed `### r<k> review`. Summary cell: `k/n` or `median [min, max]` with `_cell` formatting, `n/a` when None. | must | Q3 |
| F18 | Notes always contain, after the existing no-significance note: NOTE_USER_SIM (the simulated user accepts every recommendation, so Ask quality is not measured) and NOTE_PC5 (PC5 can fail falsely because harness telemetry records only the first `seed.py` call in one Bash command); the small-sample note keeps its condition. | must | Q4, Q5 |
| F20 | Lexer conventions of `classify`: (a) it always terminates; (b) unquoted `\\x` yields `x`, `\\` before newline joins lines, inside double quotes `\\"` yields `"`; (c) a backtick span `` `...` `` and `$(...)` (nested parens balanced) stay inside one word; `$'...'` is read like single quotes; (d) unquoted `#` at word start starts a comment to end of line; (e) `--` ends options; (f) `<`, `<<<` and `<&N` targets are neither reads nor writes nor mentions except `<FILE`, which is a mention; `>&FILE` and `&>>FILE` are writes; a leading fd number (`2>`, `12>`) is not an argument; heredoc operator may be followed by spaces (`<< EOF`); (g) `export`/`local`/`declare`/`readonly NAME=v` records NAME; (h) `cd -P`/`-L` options are skipped; `cd` to a target that cannot be resolved (`~`, unresolved `$X`) makes later relative paths unresolvable and sets `unknown`; (i) value-taking options do not become arguments: `head/tail -n|-c`, `grep/egrep/rg -e -f -A -B -C -m` (rg also `-g -T -t`), `awk -F -v -f`, `sed -e -f`, `python -W -X`, `env -u`, `git -C -c`, `timeout` per F6; with `-e`/`-f` given to grep/egrep/rg/awk/sed, every non-option argument is a file; (j) `--opt=value` contributes `value` to mentions when it is path-like; mentions only ever contain path-like arguments (containing `/` or a dotted extension), never the command word; (k) an empty argument (`""`, or the trailing piece of an unterminated quote) still counts as an argument for last-argument rules (cp/mv/install); (l) python option parsing skips unknown single-dash flags before the script path. | must | mutation triage MT1 |
| F19 | README selfcheck section documents `check --repeats` (default 3), PC1~PC12, PC12 meaning, and baseline default 3. | should | project docs |

# Errors
- Malformed or unparsable Bash command — `classify` returns with `unknown: true`, no exception — process evaluation continues; the row contributes nothing except possibly `unknown_bash_accesses`.
- Non-string or missing `tool_input.command` — row treated as non-Bash-writing, no exception — unchanged evaluation.
- `check --repeats 0` or negative — argparse error, exit 2 — no run directory created.
- Legacy run.json entries without `repeat` and legacy `scores.harness.jsonl` rows without `repeat` — treated as repeat 1, legacy directory — report and process work unchanged.

# Cases
| id | level | input / state | expected result |
| --- | --- | --- | --- |
| C1 | normal | `cd /testbed; F=agent-docs/specs/$RID-x.md; cat > $F <<EOF\n---\nstatus: x\nEOF` | writes == [`agent-docs/specs/$RID-x.md`]; heredoc lines not parsed |
| C2 | normal | astropy line 3: `sed -i '…' astropy/io/ascii/qdp.py\ncat >> astropy/io/ascii/tests/test_qdp.py <<'EOF' … EOF` | writes == both paths |
| C3 | normal | `cd /testbed/tests; python - <<'EOF'\np='_core/test_plot.py'\ns=open(p).read()\nopen(p,'w').write(s)\nEOF` | writes == [`tests/_core/test_plot.py`] |
| C4 | normal | `python -m pytest -q tests/test_x.py 2>&1 \| tail -1` | test_runs 1, reads [], writes [] |
| C5 | normal | `T="timeout 600 python -m pytest tests/a.py -q"; $T 2>&1 \| tail -1` | test_runs 1 |
| C6 | normal | `cat tests/test_x.py; grep -n foo tests/test_y.py` | reads both |
| C7 | boundary | `echo hi > /dev/null; ls 2>&1; cmd 2>/tmp/e` | writes [] (dev/null, fd dup, outside testbed dropped) |
| C8 | boundary | `cd ..; cat x` ; `cat /etc/passwd` ; `cat ./a/../b.py` | first: path escaping testbed dropped; second dropped; third reads [`b.py`] |
| C9 | error | `cat 'unterminated` ; `cat <<EOF\nno end` ; `""` ; non-str | no exception; unknown true for the first two, empty result for empty |
| C10 | edge | `python3 - "$F" <<'EOF'\nimport sys;p=sys.argv[1];open(p,'w').write('x')\nEOF` with `F=agent-docs/specs/r-x.md;` earlier | writes contains `agent-docs/specs/r-x.md` |
| C11 | edge | `git apply p.diff` ; `python -c "import os; open(os.environ['X'],'w')"` | unknown true, writes [] |
| C12 | normal | entry: ledger main Bash heredoc spec write then main Bash `sed -i tests/t.py` | PC8 fail with evidence the sed row |
| C13 | normal | entry astropy-like: main Bash writes impl+tests at row 3, spec written at row 6 | PC12 fail, evidence row 3 |
| C14 | normal | spec written first, then implementer writes impl | PC12 pass |
| C15 | boundary | writes exist, no spec write at all but spec text in diff | PC12 fail |
| C16 | edge | no spec text; missing telemetry dir; missing ledger | PC12 n/a each; baseline arm all n/a |
| C17 | normal | implementer Bash `python -m pytest tests/t.py` | PC9 pass, implementer_test_runs 1 |
| C18 | error | implementer Bash `cat tests/t.py` ; test-implementer `sed -n 1,5p src/impl.py` | PC9 fail each |
| C19 | edge | implementer Bash `./custom_tool tests/t.py` | PC9 pass, unknown_bash_accesses 1 |
| C20 | normal | `run.run` with 2 instances, arms [harness], repeats 2 | entries in order (i1,r1),(i1,r2),(i2,r1),(i2,r2); dirs `<iid>/harness-r<k>`; predictions carry repeat |
| C21 | boundary | repeats 1 | entries without repeat, dirs `<iid>/harness` |
| C22 | normal | resume of a halted repeated run | resumes the interrupted `harness-r<k>` entry only; halted carries repeat |
| C23 | normal | report with 3 repeats resolved [1,0,1], kill [0.2,0.5,None], baseline kill [0.1,0.3] | resolved summary k=2,n=3; kill median 0.35 [0.2,0.5], verdict above, repeat_verdicts above 1 within 1 n/a 1 |
| C24 | boundary | harness median equals baseline max; all harness None | within; summary None, verdict n/a |
| C25 | normal | legacy run (no repeat keys) and legacy scores | report has one repeat per instance, notes include NOTE_USER_SIM and NOTE_PC5 |
| C26 | normal | `check --repeats 2` CLI with fakes | run.run called with repeats=2; scores/process written per repeat; report emitted |
| C27 | error | `check --repeats 0` | exit 2 |
| C29 | normal | each F20 item (a)–(l) with the triage input recorded in MT1 | output as stated in F20 |
| C28 | normal | Markdown of C23 | headers as F17, `2/3` summary cell, `### r1 review` subsections, fails column |

# Quality Applicability
| ISO/IEC 25010:2023 characteristic | applicable | rationale |
| --- | --- | --- |
| Functional suitability | yes | the checks and report are the product |
| Performance efficiency | no | offline parsing of small ledgers; live run cost is governed by N, a user choice |
| Compatibility | yes | existing run directories, run.json, scores and fixtures must keep working |
| Interaction capability | no | report readability is covered by F17 functional cases |
| Reliability | yes | arbitrary agent-written Bash text must not crash processing |
| Security | no | token scrub paths unchanged; no new external input surface beyond local ledgers |
| Maintainability | yes | project comment rules and coverage target |
| Flexibility | no | no new deployment environment |
| Safety | no | no physical or harmful effect |

# Quality Requirements
| id | characteristic / subcharacteristic | target and context | measure method / inputs / unit | threshold and direction | evidence: automated, review, mutation | source |
| --- | --- | --- | --- | --- | --- | --- |
| Q1 | Compatibility / co-existence | legacy run a41e64cb9bbbef03 and legacy unit fixtures | process+report commands succeed on legacy layout; count of failures | 0 failures | automated C21, C25; review R1 | plan default |
| Q2 | Reliability / fault tolerance | `classify` on random commands | exceptions or property violations per 50000 fuzz inputs | 0 | fuzz; automated C9 | plan default |
| Q3 | Maintainability / testability | aggregate over the Test command `--include` list (now with `selfcheck/__main__.py`) | branch coverage via Test command | aggregate ≥ 90% (fail-under); per-file shortfalls mapped to behavior by main | automated | existing project target |
| Q4 | Maintainability / analysability | changed Implementation files | comments violating AGENTS.md Comment Enforcement, count | 0 | review R2 | AGENTS.md |

# Verification Obligations
| id | parent requirement/Case ids | variant and target surface | test layer and selection policy | ISO/IEC/IEEE 29119-4 technique | coverage items | coverage target | observation and expected result | evidence procedure |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| O1 | F1,F2,F3,F4,F5,F6,F7, C1–C11 | `bashparse.classify` return value | unit; every listed partition | equivalence partitioning | P-split, P-heredoc(4 quote forms), P-assign, P-var-unresolved, P-cd, P-normalize(abs-testbed, abs-other, escape, dot), P-redir(>,>>,&>,>\|), P-redir-excluded(fd dup, /dev/null), P-tee, P-sed-i, P-sed-e, P-cp, P-mv, P-python-heredoc-write, P-python-c-write, P-python-argv, P-python-write-nopath, P-python-read, P-read-cmds(each of the 13 commands), P-testrun(pytest, py.test, tox, nox, python -m pytest, python -m unittest, timeout-prefixed, env-prefixed, var-expanded), P-unknown(git apply, patch, git checkout --, git restore, unbalanced quote, unterminated heredoc), P-empty | 100% | exact equality of the returned dict fields named in the Case | Test command |
| O2 | F7, Q2 | `classify` on random strings | fuzz | random testing | 50000 generated inputs, seed 1 | none — random | no exception; every path str without leading `/` | main fuzz run, ledger |
| O3 | F8, C12 | process PC8/PC10/main_implementation_edits with Bash writes | unit via ledger fixtures | decision table | rules: {spec write tool Edit, Bash} × {later main test write via Edit, Bash, none}; PC10 Bash edit after final pass; main_implementation_edits Bash count | 100% | verdict and evidence lines | Test command |
| O4 | F9, C13–C16 | PC12 | unit | decision table | R1 no spec text → n/a; R2 no writes → pass; R3 writes, no spec write → fail; R4 first write before spec → fail (evidence); R5 spec first → pass; R6 only test-implementer writes before spec → pass; R7 baseline arm → n/a | 100% | verdict, evidence ref | Test command |
| O5 | F10, C17–C19 | PC9 and metrics | unit | equivalence partitioning | implementer: test run, read, write, mention-only, non-Bash path; test-implementer/test-verifier: read impl, run tests; metrics values | 100% | verdict, `implementer_test_runs`, `unknown_bash_accesses` | Test command |
| O6 | F11, F12, C20–C22 | run.run/resume/predictions with fake docker | unit/integration with existing fakes | state transition | states: pending→completed per repeat entry, interrupted→resumed, halted record; layout N=1 vs N=2 | 100% transitions listed | entries, dirs, predictions, halted | Test command |
| O7 | F12, F13, C26, C27 | CLI `check` | integration with m3 fakes | equivalence partitioning | default repeats from config, explicit 2, invalid 0, resume ignores repeats, per-repeat score/process keys, review per repeat | 100% | call args, files, exit codes | Test command |
| O8 | F14, F15, F16, C23, C24 | report.build | unit | boundary value analysis (3-value) + equivalence partitioning | median: odd/even/single/all-None; k/n with None; verdict at min-ε, min, max, max+ε of baseline range; repeat_verdicts each class; process_fails 0 and >0; small_sample fallback; false_claims repeat | 100% | report dict values | Test command |
| O9 | F17, F18, C25, C28 | render_markdown and notes | unit | equivalence partitioning | N=1 legacy, N=3; summary cell forms (k/n, median range, n/a); review subsections; both notes present; small-sample note conditional | 100% | exact lines | Test command |
| O10 | Q1, C21, C25 | legacy compatibility | unit + review | scenario testing | legacy run.json, legacy scores rows, legacy process.json; R1 replay | 100% | outputs as expected | Test command + R1 |
| O11 | Q3 | Implementation Python | Test command coverage | branch testing | branches in changed Implementation files | ≥ 90% | coverage report | Test command |
| O13 | F20, C29 | `classify` lexer conventions | unit | equivalence partitioning | L-a … L-l (one item per F20 letter; L-i one sub-item per command/flag listed) | 100% | exact field equality | Test command |
| O12 | Q4, F19 | comments and README | review | none — review | R2, R3 checklists | none — review | zero violations, README items present | R2, R3 |

# Assumptions and Defaults
| id | decision | evidence and uncertainty | brief v1 — approved / vetoed → <answer> / user answer |
| --- | --- | --- | --- |
| A1 | Running tests is not cross-role access; reading/writing is | user chose recommendation | user answer |
| A2 | Bash writes count as edits; ambiguous commands → unknown, not fail | user chose recommendation | user answer |
| A3 | N=3 default for check and baseline; N not in fixture_id | user chose recommendation | user answer |
| A4 | Distribution comparison: k/N, median+range; no significance tests | user chose recommendation | user answer |
| A5 | N=1 keeps legacy layout; entries without repeat are repeat 1 | understanding round | brief v1 — approved |
| A6 | Each Bash command starts at cwd `/testbed`; `cd` is tracked only within one command | live ledgers always `cd /testbed` first or run from testbed; cross-call cwd unknown | brief v1 — approved |
| A7 | Simulator limitation and PC5 bug are notes only | user chose recommendation | user answer |

# Traceability
| requirement id | Case ids | obligation ids | evidence procedure |
| --- | --- | --- | --- |
| F1–F7 | C1–C11 | O1, O2 | Test command, fuzz |
| F8 | C12 | O3 | Test command, R1 |
| F9 | C13–C16 | O4 | Test command, R1 |
| F10 | C17–C19 | O5 | Test command |
| F11, F12 | C20–C22 | O6, O7 | Test command |
| F13 | C26, C27 | O7 | Test command |
| F14–F16 | C23, C24 | O8 | Test command |
| F17, F18 | C25, C28 | O9 | Test command |
| F20 | Lexer conventions of `classify`: (a) it always terminates; (b) unquoted `\\x` yields `x`, `\\` before newline joins lines, inside double quotes `\\"` yields `"`; (c) a backtick span `` `...` `` and `$(...)` (nested parens balanced) stay inside one word; `$'...'` is read like single quotes; (d) unquoted `#` at word start starts a comment to end of line; (e) `--` ends options; (f) `<`, `<<<` and `<&N` targets are neither reads nor writes nor mentions except `<FILE`, which is a mention; `>&FILE` and `&>>FILE` are writes; a leading fd number (`2>`, `12>`) is not an argument; heredoc operator may be followed by spaces (`<< EOF`); (g) `export`/`local`/`declare`/`readonly NAME=v` records NAME; (h) `cd -P`/`-L` options are skipped; `cd` to a target that cannot be resolved (`~`, unresolved `$X`) makes later relative paths unresolvable and sets `unknown`; (i) value-taking options do not become arguments: `head/tail -n|-c`, `grep/egrep/rg -e -f -A -B -C -m` (rg also `-g -T -t`), `awk -F -v -f`, `sed -e -f`, `python -W -X`, `env -u`, `git -C -c`, `timeout` per F6; with `-e`/`-f` given to grep/egrep/rg/awk/sed, every non-option argument is a file; (j) `--opt=value` contributes `value` to mentions when it is path-like; mentions only ever contain path-like arguments (containing `/` or a dotted extension), never the command word; (k) an empty argument (`""`, or the trailing piece of an unterminated quote) still counts as an argument for last-argument rules (cp/mv/install); (l) python option parsing skips unknown single-dash flags before the script path. | must | mutation triage MT1 |
| F19 | — | O12 | R3 |
| F20 | C29 | O13, O2 | Test command, fuzz |
| Q1 | C21, C25 | O10 | Test command, R1 |
| Q2 | C9 | O2 | fuzz |
| Q3 | — | O11 | Test command |
| Q4 | — | O12 | R2 |

# Workflow Control
| item | value |
| --- | --- |
| correction batches used | 2 |
| verifier invocations | 2 |
| open finding ids | none (advisory ADV1–ADV4) |

Audit state (one entry per obligation; retain prior decisions in the execution ledger):
| obligation id | spec version | evidence references and revision | accepted / open / invalidated / pending | rationale and mutation outcome | dependencies and reopening evidence |
| --- | --- | --- | --- | --- | --- |
| O1, O3, O4, O5 | 4 | test_bashparse, test_process (batches 1–2) | accepted (verifier 2) | M1–M8 killed; MT1 declared survivors re-run: killed | bashparse/process changes in batch 2 reassessed by verifier 2 |
| O2 | 4 | fuzz 50000 seed 1 after final changes, 0 violations | accepted (verifier 2) | — | re-run after bashparse changes |
| O6–O10 | 4 | test_run, test_halt, test_cli_m3, test_cli_review, test_report, test_report_review; R1 replay after final changes | accepted (verifier 1, retained by verifier 2) | M9, M10 killed; mm254, mm262 killed after batch 2 | run/report/__main__ unchanged after verifier 1 except report separator tests added |
| O11 | 4 | Test command 1074 OK, aggregate branch 94% | accepted (verifier 2) | — | ADV2: `__main__.py` 73% per file, not mapped |
| O12 | 4 | R2 no new comments; R3 README | accepted (verifier 1, retained) | — | — |
| O13 | 4 | LexerConventionTests, LexerEvidenceGapTests | accepted (verifier 2) | — | — |

Execution ledger (append attempts; preserve failed approaches):
| attempt | finding / failure signature | cause hypothesis | changed approach / new evidence | result / disposition |
| --- | --- | --- | --- | --- |
| 1 | verifier 1 retry: EG1 timeout options untested; SC1 PC12 degraded inputs; SC2 `$`/dotted matching; SC3 14 vs 13; SC4 coverage scope | spec v1 gaps and one test gap | spec v2 pins SC1–SC4; correction batch to test-implementer for EG1, SC1, SC2, A4; implementer ID1 PC12 n/a on missing ledger | Test command 1053 OK, coverage 92% |
| 2 | hand mutations M1–M10 (PC12 order/role, PC9 mentions, Bash spec write, cd, timeout opts, escape, sed script, entry_dir, k/n) | — | targeted test modules per mutation, seed.py backup/restore | all 10 killed |
| 4 | verifier 2 pass; declared MT1 survivors re-applied to final code | — | patch -R of recorded diffs + targeted tests; mm160/mm161 no longer applied after env change, re-created by hand | 45 killed + 2 hand re-creations killed; advisories ADV1 (subagent-written spec at first position untested), ADV2 (`__main__.py` per-file 73%), ADV3 output-text mutants, ADV4 partial results after parse failure remain |
| 3 | MT1 mutmut 2.5.1, 1363 eligible changed lines, 300 sampled seed 1, runner = per-file targeted test modules with -f (full runner 60 s/mutant was too slow): 199 killed, 95 survived, 6 timeout (inconclusive), 32% < 40% | — | mutant-triager ×3 | declared → evidence gaps: mm022–034, 038–040, 050, 056–058, 060, 061, 069, 073, 074, 076, 079, 080, 091, 094, 097, 116, 128, 130, 131, 133, 134, 142, 144, 160, 161, 176, 198, 199, 200, 254, 262; undeclared lexer behaviors → spec v3 F20 pins current behavior (mm014, 042, 048, 075, 081, 083–086, 088, 093, 096, 107–111, 114, 115, 117, 119, 120, 122, 143, 146, 148, 149, 152, 153, 156, 178, 185–187); mm208 → ID2 implementation follows F8 (Bash rows only); output-text mutants mm001, 220, 222, 257, 268, 272, 284 advisory (labels/text not pinned); partial results after an internal parse failure mm054, 059, 095, 118 advisory (Errors pins unknown only); equivalent mm052, 087 accepted after main reading of the triager reasons |


# Version Log
## v4
- Contract-only: F20(j) states the existing path-like filter for mentions (test-implementer clarification).
## v3
- Contract-only after mutation triage MT1: F20 pins existing lexer conventions found as undeclared survivors; F8 limits classification to Bash rows; O13 and C29 added.
## v2
- Contract-only after verifier 1: PC12 n/a for missing workflow/diff/ledger (SC1); `$` and dotted-entry matching policy (SC2); read-command count 13 (SC3); timeout options listed (EG1); coverage is aggregate and includes `__main__.py` (SC4).
## v1
- Initial spec from handoff 3192c062a0fd880f items 4, 5, 7 and user answers to its open questions.

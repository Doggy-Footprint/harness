# selfcheck M1 (scorer and fixtures) stopped at the verifier limit

## Goal
"test-quality-audit-findings handoff 체크해보고. 우리도 이 하네스의 검증 장치를 만들어야 할 것 같아. SWE-bench처럼."

The user clarified that this is a self-check test bed, not a benchmark: 2–3 SWE-bench instances per check, scored by hidden-test resolution, mutant kill rate and process compliance, compared with a stored no-harness baseline ("내가 바란건 신뢰성 있는 test bed 였어", with standard SWE-bench/SWT-bench methods by default). M1 covers the scorer and fixtures; M2 is the agent runner and M3 the process checks, baseline fixture and report (plan: `/Users/hwansu/.claude/plans/test-quality-audit-findings-handoff-jolly-frost.md`; ADR `agent-docs/adr/5c4c01bdc91769f7-selfcheck-swe-bench-baseline.md`).

## State
- Branch `master`, commit `4d447a0` (nothing committed during this run).
- New, untracked:
  - `selfcheck/`: implementation, `tests/` (315 tests), `data/`, `fixtures/` (instances.jsonl, validation.json, mutants/, calibration.json, path_rules.json).
  - `agent-docs/adr/5c4c01bdc91769f7-selfcheck-swe-bench-baseline.md`.
  - `agent-docs/spec-logs/323a0faf25256262-selfcheck-scorer-fixtures.md`.
  - This handoff.
- Modified, uncommitted: `agent-docs/adr/index.md`, `agent-docs/handoff/index.md`.
- Untracked from before this run: `agent-docs/handoff/3435f4b651e6d0e3-test-quality-audit-findings.md`.
- Local Docker images:
  - Pool instances: `sweb.eval.arm64.<id>:latest` for sphinx-doc__sphinx-9602, mwaskom__seaborn-3187, astropy__astropy-14365, sympy__sympy-14531, django__django-15731, matplotlib__matplotlib-14623.
  - Test pilots: django__django-11400, sympy__sympy-18199, pytest-dev__pytest-5787.
  - M0 spike leftovers: `selfcheck-tools:spike`, `selfcheck-derived:django-11400`, the stopped `selfcheck-proxy` container and network `selfcheck-int`.
- The OAuth token for M2 is stored at `~/.config/selfcheck/oauth_token` (mode 600).

## Failed Attempts
| attempt | failure evidence | cause |
|---|---|---|
| Count future commits literally as `git rev-list --all ^base` | every pilot image reported 1 future commit | verified: swebench adds its own `SWE-bench` setup commit on top of base; spec v3/FR6 excludes it by subject and parent |
| Repo-specific src exceptions (`django/test/`, `sympy/testing/`, `sphinx/testing/`) in path rules | three Verified test-patch files fall inside them (django__django-14011, sphinx-doc__sphinx-7910, sympy__sympy-20916) | verified: the dataset split convention treats those dirs as test; spec v3 removed repo exceptions and evaluates `resolved` with the whole model patch |
| Running the Test command while `selfcheck pool` (R1) ran | VO7 T7 found extra `selfcheck=1` containers (run 4) | hypothesis: R1's own labeled evaluation containers; T7 counts containers globally and passed in runs 2, 3, 5, 6 without concurrency |
| Docker-dependent runs right after idle periods | whole Docker test classes failing in about 1 s with "pilot image missing" or empty results (run 1; first HM2–HM5 attempt; first leak rerun of mutmut survivors) | verified for the HM2–HM5 attempt: Docker Desktop Resource Saver (`autoPauseTimeoutSeconds: 300`) logged pause/unpause at the same time; spec v7 adds a readiness wait and retry, and test helpers wait for `docker info` |
| mutmut with per-module runners only | 48 survivors, 17 of them killed once the full offline suite and the Docker leak tests ran | verified: leak_check code is exercised only by Docker tests, and patches helpers are exercised by other modules' tests |
| Holding the CLI command in a shell variable under zsh | R2/R3 exited 127 without running | verified: zsh does not word-split unquoted variables |
| Verifier invocation 2 | retry with EG9, EG10, EG11, SC4 (see Execution Ledger) | verified: the evidence gaps are listed by the verifier; the budget of 2 invocations was exhausted |

## Next Step
Open a new workflow-approach spec for the remaining M1 items, then continue with M2.

1. **SC4.** Decide `gold_reference` when there are zero compile-valid mutants (default proposal: `None`, as for `primary` and `secondary`). Add an assertion in `test_vo12_f6_no_mutants...`.
2. **EG10.** Assert `kill.sampled` counts compile-valid mutants only, in the compile-invalid scenario.
3. **EG11.** After a cache miss with the daemon unreachable, assert the cache directory gained no entry.
4. **EG9.** Exercise the real `leak_check` failure path and assert a `RuntimeError` that contains the instance id. Candidate scenarios:
   - an instance copy whose gold patch does not apply to base, which prints `GOLD_APPLY_FAILED`;
   - unparsable script output, via a docker shim.

   Optionally cover the advisories AD1–AD6 from the verifier.
5. **Then M2:** derived agent images, Agent SDK driver, simulated user and proxy. The M0 spike verified each of these and recorded its findings in the archived spec's ledger row M0.

## Open Questions
- SC4: `None` vs `0.0` for `gold_reference` with no compile-valid mutants.
- Should the pool require a minimum number of mutants? django__django-15731 has 1 mutant and astropy__astropy-14365 has 4, and on astropy the stripped calibration rung does not discriminate (4/4 like gold). A criterion would change the pool and require rerunning R1–R3 for the replaced instances.
- Should Docker Desktop Resource Saver be disabled on this machine? Code and tests now tolerate it.
- When to commit the uncommitted files listed in State.

## Spec
`agent-docs/spec-logs/323a0faf25256262-selfcheck-scorer-fixtures.md`, version 9, status `limit`, run ID `323a0faf25256262`.

## Execution Ledger
- **Counters:** correction batches 5; verifier invocations 2 (1: retry; 2: retry → limit).
- **Test command runs:**
  - Run 1: 240 tests, 11 failures, 2 errors.
  - Run 2: 276 tests, 1 failure.
  - Run 3: 276 tests, all pass, coverage 95%.
  - Run 4: 298 tests, 1 failure (concurrency).
  - Run 5: 314 tests, 1 failure.
  - Run 6: 315 tests, all pass in 768 s; branch coverage 96% (calibrate 97%, mutants 96%, patches 96%, pool 100%, score 97%, validate 96%).
- **Findings closed:**
  - Verifier 1: EG1–EG8 and SC1–SC3, confirmed closed by verifier 2.
  - Test-run defects in batches 1–5: SDL `return`, FR6 setup commit, E2 over-specification, pool `--instances`, `changed_lines` keys.
- **Findings open:** EG9, EG10, EG11, SC4.
  - Advisories AD1–AD6: unanchored `test_`/`conftest` regex, pure-rename `changed_lines` key, R4 oracle naming, astropy stripped rung, T17 no-retry rule, `apply_to_texts` input unmodified.
- **Hand mutations:** HM1–HM10, selected in the spec ledger row HM-sel. All 10 were detected by their intended assertions before and after batches 3–5.
- **Mutation tool:** mutmut 2.5.1, 300 of 1302 mutants sampled with seed 1.
  - Outcome: 269 killed (3 timeouts), 31 survived (10.3%, threshold 40%).
  - Triage: 22 equivalent (none overturned on recheck), 9 declared (closed by v8 coverage items), mm292 resolved by defining leak_check failure handling.
- **Fuzzing:** none (approved; the 500-row corpus covers the diff/path domain).
- **Review evidence:**
  - R1: pool of 6 valid. Rejected pylint-8898 (leak), pytest-5840 (leak) and requests-2931 (needs network).
  - R2: mutant fixtures with 18/12/4/40/1/18 mutants.
  - R3: core 3 calibration all monotonic.
  - R4: eval-script equality 6/6.
  - R5: comment review.
  - R6: CLI orchestration.

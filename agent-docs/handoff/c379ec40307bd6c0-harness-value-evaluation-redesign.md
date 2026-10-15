# Harness value evaluation: replace SWE-bench Verified self-check (stages 1–2)

## Goal
"자 SWE-bench를 쓰려고 한 건 나의 idea였고, 나의 intent는 이 하네스가 정말로 도움이 되고 있는냐를 평가하는 거야. 지난 작업을 포기하는 선택지, 내 idea를 무시하는 선택지도 좋아. 내 intention에 맞게 네가 할 수 있는 지식들을 동원해서 문제 해결 방향을 잡아줘."

Then: "SWE-bench 셋업 환경은 archived로 남겨놓고, 실제 설치한 건 삭제해줘 (용량이 커) 그리고 1, 2단계는 handoff로 넘겨줘. 너의 권장안을 넣어서"

## State
- Branch `master`, base commit `254c41c`. Changed files: `README.md` (selfcheck section marked archived), this handoff, `agent-docs/handoff/index.md`, `selfcheck/results/8b28b1b5525cc30e.{json,md}` (new report).
- `selfcheck/` code stays in place, archived: no further work on it, scorer bugs below left unfixed. Its runner (docker arms, rate-limit halt, resume) and process checks (`selfcheck/process.py`, PC1–PC12) are candidates for reuse in stage 2.
- Deleted from the machine: all `selfcheck-*`, `sweb.*` and `ubuntu/squid` docker images, the `selfcheck-proxy` container, the `selfcheck-int` network, the docker build cache (`docker builder prune -af`, also removed other projects' unused build cache), `~/.harness/selfcheck/{cache,mut,scratch}`, and the SWE-bench Verified / SWT-bench datasets in `~/.cache/huggingface`. Rerunning selfcheck requires `pool`, `images`, `validate`, `mutants`, `calibrate`, `images --agent` again.
- Kept: `~/.harness/selfcheck/runs/` (raw run records, 19 MB), `~/.harness/selfcheck/logs/`, `selfcheck/fixtures/` (baseline fixture `246588b0e19680ee`), `~/.config/selfcheck/oauth_token`.
- ADR `5c4c01bdc91769f7` (SWE-bench self-check) moved to `agent-docs/adr/stale/` at the user's request ("이제 SWE-Bench 안 쓰니까 stale로 보내야지 않을까?"). Its Alternatives section still holds the rejection of local-repository reconstruction that stage 2 answers.

## Failed Attempts
| attempt | failure evidence | cause |
| --- | --- | --- |
| SWE-bench Verified ∩ SWT-bench self-check, harness arm with gold-informed reviewer (`check --conditions informed --repeats 2`, 6 instances), run `8b28b1b5525cc30e` vs fixture `246588b0e19680ee` | resolved 11/12 vs baseline 10/12; only sphinx-9602 moved (0/2 → 1/2); cost per run $0.70–12.88 vs baseline $0.12–1.15 | verified: baseline already resolves 5 of 6 instances on both repeats, so `resolved` has no room to show a harness effect |
| Same run, test quality via `swt_success` | swt 3/12 harness vs 4/12 baseline; 9 harness failures | verified: 7 of 9 are measurement defects. (a) sympy, django: the same test is parsed under different ids in failing and passing logs, so it counts as x2f with `after=None` (`selfcheck/score.py:92`). (b) matplotlib: x2f covers every test in the file, and ~180 pre-existing tests fail before and after (`numpy.float` etc.). (c) seaborn r1: the agent image has `hypothesis` (`testbed_tools`), the SWE-bench eval image does not, so collection fails and the run is not applicable. Baseline swt for sympy, django and matplotlib is 0 for causes (a) and (b) too |
| Same run, genuine test-quality failures | seaborn r2: 16 agent tests (`use_mathtext` variants) fail on gold; sphinx r1: 1 agent test fails on gold | verified: tests assert behavior beyond the gold fix. seaborn r2 followed informer messages stressing "no scientific notation"; hypothesis that the informer pushed the over-specification |
| Same run, scope | astropy r2 skipped `workflow-approach` in 68 s, citing the skill description's "not for local bug fixes", and resolved | verified: most SWE-bench Verified instances are outside the scope the harness claims, so the harness is evaluated on tasks it declines |
| Same run, informed condition | 39 relay requests, 1 AskUserQuestion; the reviewer returned null for 23 of 38 idle briefs; no leaks | verified: the simulated user rarely acts, so it cannot measure the harness's intent-alignment claims |

## Next Step
Recommendation: stop investing in SWE-bench Verified and build the evaluation around the harness's own claims, on tasks inside its scope.

### Stage 1 — falsifiable claims and kill criteria (before any run)
Write a short document (proposed: `agent-docs/specs/` via workflow-approach, or a plain doc if no code) that lists each claim, its measurement, and the threshold that would count as "no help". Fix the thresholds before seeing results. Draft:

| claim | measurement | "no help" if |
| --- | --- | --- |
| H1 harness raises correctness on feature-level tasks | hidden acceptance tests pass rate, paired per task | paired difference CI includes 0 |
| H2 harness output matches user intent better | user corrections needed; blind pairwise preference by the user | preference ≈ 50% |
| H3 harness tests are more useful | kill rate of the agent's tests against mutants of the human reference implementation | no difference |
| H4 cost is acceptable | cost and wall time per successful task | above a user-set multiple (e.g. 5×) of baseline |

Also record which harness components a later ablation would remove (mutation step, separate verifier, implementer/test-implementer split), since "harness vs none" yields one bit.

### Stage 2 — task set inside the harness's scope
Recommended source: **human-authored feature commits with tests from public OSS repositories, committed after the model's training cutoff.** Each task is the parent commit plus a user-style request rewritten from the PR/issue (some deliberately underspecified); the commit's own tests are the hidden acceptance tests and its code is the mutation reference.

This answers both reasons the ADR rejected local-repository reconstruction: the oracle is human-written, and public repositories allow external reproduction. Post-cutoff commits also avoid the training contamination SWE-bench Verified carries.

Selection rules:
- feature-sized changes (multiple files or a new behavior, not one-line fixes), so `workflow-approach` treats them as in scope;
- tests in the same commit that fail before and pass after;
- runnable in a container built from the repo's own tooling; check that the evaluation environment matches the agent environment (the `hypothesis` mismatch above);
- target 15–20 tasks; 2–3 repeats per arm; report paired differences with intervals.

Alternatives, in order:
1. Public feature-level benchmarks (candidates to verify: FEA-Bench, SWE-bench Pro, continuously refreshed sets such as SWE-bench-Live / SWE-rebench). Less build work, but distribution and contamination need checking.
2. The user's own repositories, only commits that were human-written, and only for H2 blind review (the ADR's oracle objection applies to agent-written commits).

Reuse from `selfcheck/`: container runner, arm separation, rate-limit halt and resume, manifest and fixture keying, `process.py` PC checks. Do not reuse `score.swt_outcome` without fixing defects (a) and (b) above: restrict x2f to agent-attributed tests and normalize test ids with `test_id_key`.

In parallel, at low cost: compare sessions with and without `workflow-approach` in `analytics/` data (user correction turns, rework commits) as an observational cross-check. It cannot establish causation.

## Open Questions
- Task source: which public repositories (language, test tooling) and is the user willing to run the H2 blind pairwise review on 5–8 tasks?
- Priority among H1–H4. Recommendation: H2 and H4 decide whether to keep the harness; H1 and H3 explain why.
- A new ADR for the stage-2 design? Propose it to the user when stage 2 is designed; do not write it unilaterally.
- Delete `selfcheck/` from the repository once stage 2 has taken what it needs, or keep it archived?
- Docker Desktop's VM disk may not shrink after the deletions until compacted; check host free space if it matters.

## Spec
None. No workflow spec was opened for this decision. Last selfcheck spec: `agent-docs/spec-logs/54ad633104783ebe-selfcheck-informed-reviewer-condition.md` (v4, complete, run 54ad633104783ebe).

## Execution Ledger
- Run `8b28b1b5525cc30e`: `check --instances <all 6> --conditions informed --repeats 2`, harness commit `254c41c`, fixture `246588b0e19680ee` (baseline runs `e4f65ca38835dc7b`, `2323f291490127f5`). Report `selfcheck/results/8b28b1b5525cc30e.md`. All 12 entries completed, exit 0.
- PC failures: PC1 1/12 (astropy r2, workflow skipped), PC2 3, PC4 5 (no verification_result before workflow_end), PC5 11 (possible false positive, noted in report), PC7 1, PC8 3 (main edited tests after spec), PC9 1, PC10 1, PC11 8.
- SWT failure classification above was derived by replaying cached evaluations (no new docker runs); the cache is now deleted, so reproducing it requires re-scoring.
- No fuzz or mutation tools were run for this decision; no verifier was dispatched.

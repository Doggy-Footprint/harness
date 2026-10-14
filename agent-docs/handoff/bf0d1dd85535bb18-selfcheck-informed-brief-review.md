# selfcheck: a reviewer who knows the correct answer reads the harness brief

## Goal
"harness는 의도대로 진행한다. 따라서 하네스가 제공한 구현 사항에 대해 brief를 읽고 정답을 아는 상태에서 검증해주는 절차를 추가한다."

On the bias trade-off presented afterwards (in-loop help reaches only the harness arm; a gold-informed reviewer knows more than a real issue reporter), the user answered: "그렇게 하자. 그렇게 handoff 써줘." — accepting the recommendation: post-run diagnosis first, in-loop reviewer only as a separate, constrained condition, unassisted check stays primary.

## State
- Branch: `master`, commit `7bebbc7`. `selfcheck-m1` was merged and deleted.
- Changed files: none besides this document and the handoff index.
- Relevant source files: `selfcheck/agent/user_sim.py` (`PHRASE`, `on_idle`), `selfcheck/agent/driver.py`, `selfcheck/run.py` (`compose_prompt`, driver input `phrase`), `selfcheck/process.py`, `selfcheck/report.py`, `selfcheck/fixtures/instances.jsonl` (`patch`, `test_patch`, `FAIL_TO_PASS`).
- Live evidence: `~/.harness/selfcheck/runs/a41e64cb9bbbef03/<instance>/harness/raw/claude/projects/-testbed/*.jsonl` (full transcripts, including each brief).

## Failed Attempts
| attempt | failure evidence | cause |
| --- | --- | --- |
| A user simulator that sends one fixed approval phrase (`user_sim.PHRASE`: "Ask 항목을 포함한 모든 질문에 당신의 권장안을 제 답으로 삼습니다. 승인합니다, 진행하세요.") | seaborn-3187: brief Q1 recommended "offset in the legend title" and cited "upstream seaborn v0.12.2 did this", which is false (gold disables the offset); the phrase approved it, the spec fixed the wrong behavior, and the run ended `complete` but unresolved | verified: the phrase accepts every recommendation, so a wrong Ask answer is never vetoed and the harness's question step has no effect on the outcome |
| Same simulator, sphinx-9602 | spec R1 allowed "`desc_sig_literal_*` or plain Text"; implementation used `desc_sig_punctuation`; the official test requires plain Text | verified: the brief exposed an open choice that a user knowing the intended output would have pinned; nobody answered it |
| Same simulator, astropy-14365 | main took the first approval phrase as permission for a "short version" of the workflow, wrote the spec afterwards | verified from transcript order (edits t=21.7, spec t=57.1); the phrase has no content a reviewer could use to object |

## Next Step
Open a workflow-approach spec for selfcheck with these user-approved decisions:
1. **Post-run diagnostic reviewer (first).** After a harness run, a reviewer that has the issue, the gold patch and the gold tests reads the run's briefs (understanding round, approval brief, Ask items with options and cited evidence) and the archived spec, and reports where they diverged from the correct behavior: understanding, Ask option set, recommendation evidence, spec requirements. It never changes the run or its scores.
2. **In-loop informed reviewer (second, separate condition).** It replaces the fixed phrase only in a condition with its own name, reported apart from the unassisted check. The unassisted check with the fixed phrase remains the primary score. Constraints on what the reviewer may say:
   - answer only what the harness asked or presented for approval;
   - speak only of observable behavior, as derived from the `FAIL_TO_PASS` tests;
   - never name code, files, or node/API choices the question did not raise.
3. Record every reviewer message and the gold facts it used in the run artifacts. The report shows the unassisted and informed conditions side by side. Their difference is the reported effect of a user who reads the brief.

## Open Questions
- Who is the reviewer: a model call inside the driver (cost, model choice, leakage of gold text into the container), or a host-side step between turns?
- Does an informed answer that names behavior from the gold tests (for example "labels must show full numbers") leak the hidden test? Where is the line within the constraints above?
- Should a brief with a false factual claim (the seaborn "upstream v0.12.2" citation) be scored as a process failure on its own?
- Relation to `3192c062a0fd880f-selfcheck-checker-gaps-and-repeats.md`: whether to run both in one spec, and whether `check --repeats` should come first so the informed condition can be compared with variance.

## Spec
none — no spec opened yet. Prior selfcheck spec: `agent-docs/spec-logs/94b886658b88a7ef-selfcheck-analysis.md` (v6, complete).

## Execution Ledger
- Evidence comes from live check `a41e64cb9bbbef03` (opus-5-5, effort low, harness `bf8048e`) and baseline fixture `246588b0e19680ee`; see `selfcheck/results/a41e64cb9bbbef03.md`.
- Transcript analysis was manual (main agent read transcripts, specs, gold patches and tests). No code changes, fuzzing or mutation runs for this handoff. Correction and verifier counters: n/a.

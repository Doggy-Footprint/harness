# selfcheck stage 1 of 3: post-run diagnostic review of harness briefs against gold

## Goal
"harness는 의도대로 진행한다. 따라서 하네스가 제공한 구현 사항에 대해 brief를 읽고 정답을 아는 상태에서 검증해주는 절차를 추가한다."

On the bias trade-off presented afterwards (in-loop help reaches only the harness arm; a gold-informed reviewer knows more than a real issue reporter), the user answered: "그렇게 하자. 그렇게 handoff 써줘." — accepting the recommendation: post-run diagnosis first, in-loop reviewer only as a separate, constrained condition, unassisted check stays primary.

Order then agreed: "그럼 지금 나눠서 써줘." — the work is split into three handoffs, done in this order:
1. this handoff (post-run diagnostic reviewer);
2. `3192c062a0fd880f-selfcheck-checker-gaps-and-repeats.md` (PC8, retroactive-spec check, `check --repeats`);
3. `44ab3e5b5b54f81d-selfcheck-informed-reviewer-condition.md` (in-loop informed reviewer as a separate condition).

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
Open a workflow-approach spec for selfcheck covering only the post-run diagnostic reviewer:
1. After a harness run, a reviewer that has the issue, the gold patch and the gold tests reads the run's briefs (understanding round, approval brief, Ask items with options and cited evidence) and the archived spec.
2. It reports where they diverged from the correct behavior, per category: understanding, Ask option set, recommendation evidence, spec requirements. Each finding cites the transcript or spec location.
3. It never changes the run, its scores, or its process checks. Its output is stored with the run and summarized in the report.
4. Develop and check it offline on the existing run `a41e64cb9bbbef03`; no new live run is needed. The manual analysis of that run is the reference: seaborn (Ask options omitted the gold approach, false "upstream v0.12.2" evidence, User Intent drifted from the understanding round's success criterion), sphinx (R1 left the node type open as "A or B" and named a node class absent in that Sphinx version), astropy (no divergence in understanding; workflow shortened, spec written afterwards).

## Open Questions
- Where the reviewer runs: host-side model call after the run (natural for post-run review) or elsewhere; model and effort; cost per run.
- Should a brief with a false factual claim (the seaborn "upstream v0.12.2" citation) be scored as a process failure on its own, or only reported?
- Output format: free text, or fixed categories with verdicts that the report can tabulate?

## Spec
none — no spec opened yet. Prior selfcheck spec: `agent-docs/spec-logs/94b886658b88a7ef-selfcheck-analysis.md` (v6, complete).

## Execution Ledger
- Evidence comes from live check `a41e64cb9bbbef03` (opus-5-5, effort low, harness `bf8048e`) and baseline fixture `246588b0e19680ee`; see `selfcheck/results/a41e64cb9bbbef03.md`.
- Transcript analysis was manual (main agent read transcripts, specs, gold patches and tests). No code changes, fuzzing or mutation runs for this handoff. Correction and verifier counters: n/a.

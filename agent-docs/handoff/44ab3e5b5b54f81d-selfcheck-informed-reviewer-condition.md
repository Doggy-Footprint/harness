# selfcheck stage 3 of 3: in-loop gold-informed reviewer as a separate condition

## Goal
"harness는 의도대로 진행한다. 따라서 하네스가 제공한 구현 사항에 대해 brief를 읽고 정답을 아는 상태에서 검증해주는 절차를 추가한다."

On the bias trade-off (in-loop help reaches only the harness arm; a gold-informed reviewer knows more than a real issue reporter), the user answered: "그렇게 하자. 그렇게 handoff 써줘." — the in-loop reviewer runs only as a separate, constrained condition, and the unassisted check stays primary. Then: "그럼 지금 나눠서 써줘." — this is the third of three handoffs.

## State
- Branch: `master`. Changed files: none besides the handoff documents and index.
- Depends on, in order:
  1. `bf0d1dd85535bb18-selfcheck-informed-brief-review.md` (post-run diagnostic reviewer; its divergence categories show whether the in-loop answers changed the brief);
  2. `3192c062a0fd880f-selfcheck-checker-gaps-and-repeats.md` (PC8 and retroactive-spec checks so new live runs yield usable process data; `check --repeats` so the two conditions can be compared with variance).
- Relevant source files: `selfcheck/agent/user_sim.py` (`PHRASE`, `on_idle`), `selfcheck/agent/driver.py` (idle handling, user turns), `selfcheck/run.py` (driver input `phrase`, `max_user_turns`), `selfcheck/manifest.py` and `selfcheck/fixture.py` (condition must be part of comparability), `selfcheck/report.py`, `selfcheck/fixtures/instances.jsonl` (`FAIL_TO_PASS`, `test_patch`).

## Failed Attempts
| attempt | failure evidence | cause |
| --- | --- | --- |
| A user simulator that sends one fixed approval phrase (`user_sim.PHRASE`) | seaborn-3187 in run `a41e64cb9bbbef03`: the brief recommended "offset in the legend title" on false "upstream v0.12.2" evidence; the phrase approved it; the run ended `complete` but unresolved | verified: the phrase accepts every recommendation, so the harness's question step cannot affect the outcome; carried over from `bf0d1dd85535bb18` |

- Stage 1 complete: `selfcheck/review.py`, `python3 -m selfcheck review <run_id>`, spec `agent-docs/spec-logs/e4d852bdd61ccf5b-selfcheck-informed-brief-review.md`. Live review of `a41e64cb9bbbef03` caught seaborn's Ask-option omission, false "upstream v0.12.2" claim and spec divergence, but missed sphinx's open "A or B" node type and nonexistent node class (reviewer gets gold only, no base repository) and seaborn's User Intent drift. Expect the same blind spots when its categories are used to judge in-loop answers.

## Next Step
After stages 1 and 2 are complete, open a workflow-approach spec for selfcheck:
1. A new condition (own name in the manifest, the report and `fixture_id` comparability) in which a gold-informed reviewer answers the harness instead of the fixed phrase.
2. Constraints on what the reviewer may say:
   - answer only what the harness asked or presented for approval;
   - speak only of observable behavior, as derived from the `FAIL_TO_PASS` tests;
   - never name code, files, or node/API choices the question did not raise.
3. Record every reviewer message and the gold facts it used in the run artifacts.
4. The report shows the unassisted and informed conditions side by side, with repeats. Their difference is reported as the effect of a user who reads the brief. The unassisted check remains the primary score.

## Open Questions
- Where the reviewer runs: a model call inside the driver (gold text would enter the agent container) or a host-side step between turns; model, effort and cost.
- Does an answer that names behavior from the gold tests (for example "labels must show full numbers") leak the hidden test? Where is the line within the constraints above?
- How many user turns the reviewer may spend, and what it sends when the harness asks nothing (fall back to the fixed phrase?).
- Whether the baseline arm needs a matching informed condition, given it never asks.

## Spec
none — not started; blocked on stages 1 and 2. Prior selfcheck spec: `agent-docs/spec-logs/94b886658b88a7ef-selfcheck-analysis.md` (v6, complete).

## Execution Ledger
- Evidence: live check `a41e64cb9bbbef03` (opus-5-5, effort low, harness `bf8048e`), baseline fixture `246588b0e19680ee`, report `selfcheck/results/a41e64cb9bbbef03.md`.
- No code changes, fuzzing or mutation runs for this handoff. Correction and verifier counters: n/a.

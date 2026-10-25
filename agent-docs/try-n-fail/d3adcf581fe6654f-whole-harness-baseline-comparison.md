---
commit: da6eaffcb1b3d557688e2f801bd034b2ce3d6a94
---

# Whole-harness value measurement against a no-harness baseline

## Goal
Show whether the harness helps by comparing the whole harness arm with a no-harness baseline on the same tasks.

## Attempts
| attempt | failure evidence | cause |
| --- | --- | --- |
| SWE-bench Verified ∩ SWT-bench self-check (`evaluation/selfcheck/`), run `8b28b1b5525cc30e` vs baseline fixture `246588b0e19680ee`, 6 instances × 2 repeats | resolved 11/12 harness vs 10/12 baseline; `swt_success` 3/12 vs 4/12, 7 of 9 harness failures were scorer defects; astropy r2 declined workflow-approach as a local bug fix; cost per run $0.70–12.88 vs $0.12–1.15 | verified: baseline already resolves 5 of 6 instances, most instances are local bug fixes outside workflow-approach scope, and `swt_outcome` miscounts tests; details in `agent-docs/handoff/stale/c379ec40307bd6c0-harness-value-evaluation-redesign.md` |
| Reconstruct past workflow-approach runs from local project repositories (base commit plus spec goal, the test-quality audit's surviving mutants as the bug set) | not run | user rejected: the reference implementations are agent output and cannot serve as an oracle; private repositories prevent external reproduction |
| Post-cutoff public PRs, arms B0 / Bplus / H, agent tests scored against the reference implementation and reference mutants (`evaluation/reference_mutation/`), pilot `7df89a358d3faa30`, 12 tasks | resolved B0 5/12, Bplus 5/12, H 1/3; H cost 3.5–7.4× B0; caddy-7995 H resolved the hidden tests, but its tests call `orderFromOptions`, which the reference lacks, so valid 0 and kill 0; high false-alarm rates in all arms (excalidraw-11632 H 274/319) | verified: judging validity on the reference implementation measures agreement with the reference design, not test quality (`evaluation/reference_mutation/EXPERIMENT.md` §9); hypothesis: most false alarms are intended design differences, not sampled |

## Revisit Condition
A task source where the no-harness baseline leaves a measurable share of tasks unresolved, workflow-approach does not decline the tasks as out of scope, and test quality can be judged without running agent tests against a reference implementation's internal API.

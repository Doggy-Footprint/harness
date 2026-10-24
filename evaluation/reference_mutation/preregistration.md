# Preregistration: harness test-quality evaluation

This file fixes the claims, measures, thresholds and kill criteria before any main-run result exists.
Every report records the sha256 of this file. A run started with `--phase main` stores that sha256, and `report` on that run exits with code 2 and names both hashes when the file differs from the stored one.

## Design

- Languages: python, typescript (javascript repositories included), go. rust was planned and dropped before the pilot (2026-10-24): 0 of the validated rust candidates passed build and validation (G2 rule).
- Tasks: merged pull requests with `merged_at` on or after 2026-07-01 from non-archived, non-fork repositories with at least 200 stars and a license in MIT, Apache-2.0, BSD-2-Clause, BSD-3-Clause, MPL-2.0, ISC. At most 3 candidates per repository, at most 40 candidates per language.
- Agent model for every arm: `claude-sonnet-5-5` at effort `medium`. The same image, cpus, memory, wall clock (180 minutes), user-turn cap (8), disallowed tools and network egress (`api.anthropic.com` only) apply to every arm.
- A simulated user (`claude-opus-5-5`, effort `medium`) holding a per-task intent card answers every question, approval and idle turn of every arm. It has no access to reference code, reference tests or test ids.
- Scoring uses only container test runs on the evaluation VM. The agent's own reported numbers are never used as a score.

## Arms

- B0: the prompt is the request.
- Bplus: the prompt is the request, then a blank line, then this paragraph: "Write thorough automated tests: cover normal cases, boundaries, invalid inputs and error paths, assert observable behavior rather than implementation details, and run the tests before you finish."
- H: the prompt is "/workflow-approach " followed by the request. The harness is installed from the recorded harness commit and committed before the agent starts.

The arms differ only in these prompt and installation points.

## Sample plan

- Main sample: 15 to 20 tasks per language and 2 repeats per arm. The exact count is decided again, and recorded in the run, before the main run starts.
- Pilot: 2 repositories per language (the repositories with the most valid tasks, ties broken by repository name) and up to 2 tasks per repository. B0 and Bplus run once per pilot task. H runs once per language, on its first pilot task.
- Pilot tasks are marked in the task files and are excluded from the main analyses and from main runs.

## Measures and verdict rules

Unit of analysis: the task. Repeats of one arm on one task are averaged first. Differences are paired per task. Confidence intervals come from a cluster bootstrap by repository: 10000 resamples, seed 1, 95% percentile interval. The statistic is the pooled task mean (sum of task differences divided by the number of tasks); each resample draws k clusters with replacement from the k repositories and takes the pooled mean over the tasks of the drawn clusters.

Verdict for a paired difference with interval [lo, hi]:
- `insufficient` when fewer than 10 tasks are in scope (10 tasks are enough, 9 are not).
- `help` when lo > 0.
- `harmful` when hi < 0.
- `no_help` otherwise. lo exactly 0 is `no_help`.

### H3 (primary): test quality

- Primary measure: normalized kill = killed mutants in d_ref / |d_ref|. d_ref is the set of executed reference mutants that the human tests kill. A task with fewer than 10 such mutants is excluded from kill aggregates and flagged in the report.
- Primary comparison: H minus B0 on normalized kill, paired per task, scopes overall and per language.
- Guard: false_alarm_rate = false-alarm tests / (valid + false-alarm tests) of the agent tests run against the reference implementation. When the upper bound of the interval of (H minus B0) false_alarm_rate is greater than +0.10, the verdict is `harmful` regardless of kill. An upper bound of exactly 0.10 is not harmful; the guard then reports `ok`.
- Secondary: cross-arm detection rate (buggy implementations from other entries of the same task that fail at least one valid test / buggy implementations that ran), and the judge pairwise win rate (wins / non-tie decisions, interval compared with 0.5).
- Secondary comparisons against Bplus (H minus Bplus, Bplus minus B0) use the same rules.

### H1: correctness

Resolved rate: an entry is resolved when every fail-to-pass test passes and no pass-to-pass test breaks on the agent source with the reference tests. Comparison H minus B0 with the rules above.

### H2: intent alignment

ambiguity_correct rate: the share of omitted-behavior statements whose fail-to-pass tests pass on the agent source. Comparison H minus B0 with the rules above. In addition the maintainer records a blind preference on 5 to 8 pairs by hand; this is not computed by the tool.

### H4: cost

Median cost in USD per resolved task, H divided by B0. A ratio of 10 or less is within limit (K = 10). A ratio above 10 is reported as cost excessive. The ratio of median wall time H/B0 is reported without a threshold.

## Pilot gates (reported pass or fail)

- G1: the B0 resolved rate over pilot tasks is 0.80 or less. Above 0.80 means the tasks are too easy and difficulty is raised before the main run.
- G2: in every language at least 50% of candidates pass build and validation. Below 50% means the language is fixed or dropped.
- G3: judge position consistency (pairs whose two orders do not disagree on the winner / all pairs) is 0.70 or more.
- G4: the share of judged tasks in which the human anchor has the lowest mean Test Desiderata score is 0.50 or less.
- G5: zero leak fallbacks caused by brief content and zero token occurrences in outputs.

## Judge

A blind `claude-opus-5-5` judge at effort `medium` scores each candidate test set (agent tests of each completed entry and the human tests as an anchor, labels shuffled per task). The rubric is the test-smell catalog (tsDetect/xUnit), Kent Beck's Test Desiderata, and ISO/IEC/IEEE 29119-4 coverage per intent statement. Every quote in a judge answer must occur in the candidate text. A judge item that fails the format twice is recorded as `error` and counted.

## Exclusions and handling

- A scoring run that times out or fails to build is recorded; mutants with such runs are excluded from executed mutants; hidden or validity runs with such status make the entry inconclusive for that metric and the report counts them.
- An entry that ends `error` is re-run once from scratch in a fresh container (`run --retry-errors <run_id>`); `attempts` is 1 on the first run and 2 on the retry. An entry still `error` after its second attempt is final.
- A final `error` entry is scored as a failure in every aggregate: resolved false, f2p_frac 0, normalized and raw kill 0 (unless the task is excluded from kill aggregates), ambiguity_correct rate 0, detection rate 0; it has no tests and is excluded from false_alarm_rate; its cost and wall time are counted. The report shows the final error count per arm.
- `report` exits with code 2 while any entry is `error` with attempts 1 (naming `run --retry-errors <run_id>`) or `interrupted` (naming `run --resume <run_id>`).
- Reports never contain transcripts, tool inputs, diffs, test code, quotes longer than 200 characters, or the OAuth token.

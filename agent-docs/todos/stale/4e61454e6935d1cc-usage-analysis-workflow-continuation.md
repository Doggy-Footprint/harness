# Usage analysis: requests that continue a workflow are counted as not invoked

## Goal
"새로 나온 분류기인 Jev를 이용해서 어떤 궤적으로 workflow approach가 사용되었는지 판별해보려고 하는데 … 어떤 맥락에서 말한 건지 알면 어떻게 기록할지 알 수 있으니까."

Then: "그럼 거기에 더해서 케이스 모델링?이 가능할까? 어떻게 사용되는지 파악할 수 있게."

Then, after the first implementation: "문제만 핸드오프로 남기고 커밋, pr 해줘"

## State
- Branch `claude/jev-workflow-hook-validation-fsmugx`, base commit `51459c5`, head `eeabec4` before this handoff.
- Changed files: `analytics/usage.py` (new CLI `python3 -m analytics.usage`), `analytics/tests/test_usage.py`, `agent-docs/spec-logs/cce0155b008eaf53-workflow-usage-analysis.md`, this handoff, `agent-docs/handoff/index.md`.
- The run is complete. The problem below is outside its approved scope and has not been worked on.

### Problem
`invoked` (FR4 of the spec) is true only in the turn where the `workflow-approach` Skill is called or `/workflow-approach` is typed. Later user turns of the same workflow are recorded as `invoked: false`. These include understanding-round answers, approval of the brief, and decisions made mid-run.

Observed on this session's own transcript with `python3 -m analytics.usage`:

| request_index | prompt | invoked | actual context |
| --- | --- | --- | --- |
| 3 | 진행하자 | true (skill) | workflow start |
| 4 | 코덱스는 제외한다. | false | answer in the understanding round of run `cce0155b008eaf53` |
| 5 | 확인 완료. 깃헙 연결 완료. 진행 | false | approval of brief v1 of the same run |

Consequences:
- A label `warranted: true` on such a turn is counted as `missed`, so misses are overstated. A label `warranted: false` is counted as `correct_skip`, which is semantically wrong.
- The label question "should this request use workflow-approach?" is ambiguous for continuation turns. An external classifier such as Jev, or a human labeler, has no consistent answer for them.
- Requests are not linked to telemetry runs. Variants (FR9/FR10) therefore cannot show how many user turns a run consumed.
- Telemetry alone cannot close this gap. `workflow_start` is emitted only after the brief is approved (SKILL.md Workflow step 2), so understanding-round turns precede it.

## Failed Attempts
| attempt | failure evidence | cause |
| --- | --- | --- |
| Per-turn `invoked` (spec v2 FR4) as the only invocation signal | Requests 4 and 5 above are `invoked: false` inside run `cce0155b008eaf53` | verified: FR4 limits invocation to the turn containing the Skill call or slash command |

## Next Step
Decide the open question below, then run a new workflow-approach spec that amends FR4/FR12. The deterministic signals available in Claude transcripts are:
- the opening Skill call;
- Bash commands invoking `.harness/bin/workflow_marker.py end` or `.harness/bin/spec_lifecycle.py archive`, which close the run;
- `--run-id <id>` in those commands, which links the run.

## Open Questions
- Which option should be adopted?
  - **(A)** Add a per-request `workflow_state` (`start` / `continue` / `none`) and a `run_id`. Compute `confusion` over `start` and `none` only, and report `continue` turns per run. The label format is unchanged; labels on `continue` turns are ignored.
  - **(B)** Option A, plus a second label for `continue` turns ("did the request leave the workflow?"). This adds a field to the label format.
- Should a run without a closing command stay open until the end of the session, or until the next Skill call?

## Spec
`agent-docs/spec-logs/cce0155b008eaf53-workflow-usage-analysis.md`, version 2, status `complete`, run ID `cce0155b008eaf53`.

## Execution Ledger
- Findings:
  - F1: an unopenable telemetry file was reported as a labels error. Fixed in correction batch 1.
  - F2–F5: test evidence gaps. Fixed in correction batch 2.
  - No open findings.
- Evidence: Test command passed with 129 tests and 99.44% branch coverage on `analytics/usage.py`. RE1 was a CLI run on this session's transcript, matched by manual inspection.
- Fuzz: hypothesis, 300 examples × 2 surfaces, seed 0 (derandomized), 0 violations.
- Mutation (tool): mutmut 3.8.0 run against a temporary `setup.cfg` that was not committed.
  - 667 mutants, 649 killed.
  - 18 survivors: 15 equivalent and 3 undeclared (argparse `prog` text, recorded in A7 as not part of the contract).
  - 0 overturned.
- Mutation (hand): 10 hand mutations, each targeting one defect class.
  - M1–M9 were each detected by the intended test.
  - M10 (`main` catching all exceptions) survived. No declared input raises a non-labels exception to `main`.
- Counters: correction batches 2, verifier invocations 2 (round 1 retry, round 2 pass).

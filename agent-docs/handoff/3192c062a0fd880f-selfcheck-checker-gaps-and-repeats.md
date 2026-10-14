# selfcheck: process-check gaps and harness-arm repeats found in the first live check

## Goal
"커밋하고 4, 5, 7번 handoff로 넘기고 3은 완료 확인하고 닫아. 그 다음 마스터 머지해"

Items 4, 5 and 7 as listed to the user after the first live harness check:
- 4: "PC8이 항상 n/a입니다. 세 실행 모두 main이 spec을 Bash heredoc(`cat > spec.md <<EOF`)으로 썼는데, 검사기는 Edit/Write 도구만 spec 작성으로 인식합니다."
- 5: "사후 spec 작성을 잡지 못합니다. astropy는 구현과 테스트를 먼저 끝내고 spec을 나중에 썼습니다."
- 7: "하네스 arm에 반복이 없습니다. `check`는 과제당 1회만 돌립니다. … `check --repeats N` 같은 옵션이 필요합니다."

## State
- Branch: `selfcheck-m1`, merged into `master` after this handoff was committed.
- Commits: `bf8048e` (opus effort low, baseline fixture `246588b0e19680ee`), `5bf0d22` (report `selfcheck/results/a41e64cb9bbbef03.{json,md}`).
- Changed files for this handoff: none besides this document and the handoff index.
- Relevant source files: `selfcheck/process.py` (`evaluate_entry`, PC8 `spec_write`, PC2), `selfcheck/__main__.py` (`cmd_check`, `build_parser`), `selfcheck/run.py` (`run`, `resume`), `selfcheck/report.py` (`build`, `render_markdown`), `selfcheck/fixture.py` (`compare`, `precheck`).
- Live evidence (outside the repo): `~/.harness/selfcheck/runs/a41e64cb9bbbef03/<instance>/harness/` — `process.json`, `raw/ledger.jsonl`, `raw/telemetry/`, `raw/full.diff`, full transcripts in `raw/claude/projects/-testbed/*.jsonl`. `raw/messages.jsonl` cuts text blocks at 2000 characters (`selfcheck/agent/driver.py:74`).

## Failed Attempts
| attempt | failure evidence | cause |
| --- | --- | --- |
| PC8 "main edits test files after spec write" on run a41e64cb9bbbef03 | `n/a — no spec text or spec write` on all 3 instances | verified: `evaluate_entry` finds `spec_write` only among `EDIT_TOOLS` rows; every main agent wrote the spec with a Bash heredoc (`cat > $F <<EOF`, ledger of each instance) |
| Detect retroactive spec on astropy-14365 | PC2 failed only as `implement_test_before_verify, missing_implement_or_verify`; no check names the order | verified: astropy main edited `astropy/io/ascii/qdp.py` and the tests via Bash `sed`/`cat >>` at t=21.7, reported "short version of /workflow-approach" at t=36.9, then wrote the spec at t=57.1 (`raw/messages.jsonl` lines 18–32); no check compares the spec write time with the first Implementation edit |
| Judge harness vs baseline with 1 harness run | sphinx kill 0.89 vs baseline 0; seaborn resolved 0 vs baseline 1 | hypothesis: one run per instance cannot separate a harness effect from run-to-run variance; the 2 baseline repeats were nearly identical, so each baseline range is close to a point |

## Next Step
Open a workflow-approach spec for selfcheck covering:
1. PC8: recognize a spec write made through Bash (heredoc, redirection, `python - <<EOF` writing under `agent-docs/specs/`) as well as Edit/Write.
2. A check that the spec write precedes the first main or implementer edit of an Implementation path; a retroactive spec fails.
3. `check --repeats N` for the harness arm, and report fields that show each harness repeat against the baseline range.

## Open Questions
- PC9 currently fails when an implementer runs a Tests path through Bash (`pytest tests/...`, sphinx ledger lines 9 and 11, seaborn line 16). Should running a test file count as a cross-role access, or only reading it? The user has not decided.
- Item 2: should Bash edits by main count as Implementation edits (astropy edited with `sed -i`)? `main_implementation_edits` was 0 on astropy because only Edit/Write rows are counted.
- Item 3: default N, whether `baseline create` also needs more repeats, and whether `fixture_id` or the report format changes.
- The user simulator always accepts recommendations, so the quality of Ask items is not measured. Record as a report limitation or change the simulator?
- PC5 failures on sphinx and seaborn come from `harness/hooks/telemetry_hook.py:50` `match_seed`, which records only the first `seed.py` call in one Bash command. That is a harness fix, not selfcheck, and is not part of this handoff.
- `3435f4b651e6d0e3-test-quality-audit-findings.md` (now stale) lists harness-side problems P1–P10 that no harness change has addressed yet.

## Spec
none — no spec opened yet. Prior selfcheck specs: `agent-docs/spec-logs/94b886658b88a7ef-selfcheck-analysis.md` (v6, complete, run 94b886658b88a7ef).

## Execution Ledger
- Live baseline: runs `e4f65ca38835dc7b`, `2323f291490127f5`; 12/12 completed, no halt; SDK cost estimate $4.44 (subscription).
- Live check: run `a41e64cb9bbbef03` at `bf8048e`, opus-5-5 effort low; 3/3 completed, no halt; SDK cost estimate $11.79.
  - sphinx-9602: resolved no, kill 0.89 (baseline 0); PC4, PC5, PC9, PC11 fail; PC8 n/a.
  - seaborn-3187: resolved no (baseline yes), kill 0 (baseline 0.5), incompatible 0.5; PC5, PC9, PC11 fail; PC8 n/a.
  - astropy-14365: resolved yes, all metrics within; PC2, PC4, PC5 fail; PC8 n/a.
- Offline Test command after the effort change: 807 tests OK (7 skipped), branch coverage 97%.
- No fuzzing or mutation runs for this handoff. Correction and verifier counters: n/a.

# Adopt ISO/IEC/IEEE 29119-4 test design techniques and coverage targets in workflow-approach

## Goal
"제안을 수용한다. 어디를 수정하면 될지 파악해"
"1. 29119-4만 넣고 나머지 둘은 github issue로 추가한다. 2. ㅇㅇ 3. ㅇㅇ 4. 선택지를 질문 형태로 제시 - 설명과 트레이드 오프도 함께. 지시 수정의 경우 정보를 append하는 형태가 아닌, 목적에 맞게 필요한 부분을 rewrite하는 형태로 한다."
"이 작업을 직전 commit에서 이어갈거야. 새로운 세션에서진행할 수 있게 지시서 뽑아줘"

The accepted proposal: ISO/IEC 25023 keeps defining what to measure, and ISO/IEC/IEEE 29119-4 defines when testing is sufficient. Each verification obligation declares a 29119-4 test design technique, its coverage items, and a coverage target that the user approves.

Decisions made by the user:
1. Scope is 29119-4 only, covering specification-based, structure-based, and experience-based techniques. Risk-tiered structural coverage is tracked in GitHub issue #5, and the mutation score threshold is tracked in #6. Both issues already exist, so do not create them again.
2. Structure-based coverage is measured by main through the Test command. Test roles receive only behavior and measured values, never code locations, because they never read Implementation.
3. Migration 0.10.0 only installs instructions, like 0.9.0. Existing specs, archived records, and verifier counts stay unchanged. When an older spec is resumed, each obligation gets its technique, coverage items, and target, and the user approves them before dispatch.
4. `spec_lifecycle.py validate` keeps checking headings only. Do not add column or row validation. This was chosen over header-column checks (brittle coupling between code and docs) and row-value checks (costly markdown parsing and false positives for experience-based rows).
5. Rewrite instruction text for its purpose. Do not append new paragraphs next to old ones.

## State
- Branch: `master`
- Base commit: `de0a2b2ce035584250a641f46d7a135b7f053586`. Continue from this commit.
- At handoff time, `harness/skills/workflow-approach/SKILL.md` had an uncommitted diff (+26/−7) whose author is unknown; this session did not write it. It adds a separate 29119-4 paragraph after the 25023 paragraph, which is the appended style the user rejected, and it covers only part of the scope. The user chose to start from the commit. Before editing, save that diff with `git stash push -m "unattributed 29119-4 draft" harness/skills/workflow-approach/SKILL.md`. Do not drop it.
- Baseline: `python3 -m unittest discover -s tests` passed 141 tests at the base commit.
- No files were changed by this session other than this handoff and its index entry.

## Failed Attempts
| attempt | failure evidence | cause |
|---|---|---|
| Put the 29119-4 technique and coverage in the Quality Requirements `evidence` column | That column holds evidence for ISO/IEC 25023 measures. The Verification Obligations `boundary/transition/combination` column already informally holds specification-based techniques. | verified: wrong table; the obligation table is the right place |
| Apply the rewrite with a Python exact-replace script | The first replacement's assertion failed because the file had changed after this session read it | verified: concurrent uncommitted edit by an unknown author |

## Next Step
Edit only the `harness/` payload, `installer/`, and `tests/`. Never edit `.harness/`, `.claude/`, `.codex/`, or `.agents/` directly.

1. Rewrite `harness/skills/workflow-approach/SKILL.md`:
   - `# Paths` → `Test command`: one command that covers all automated functional and quality checks and fails when a structure-based coverage target is missed.
   - `# Verification Obligations` header: replace the `boundary/transition/combination` column with `ISO/IEC/IEEE 29119-4 technique / coverage items / coverage target`. Using three separate columns is also acceptable. Keep the variant, surface, layer, and selection policy columns.
   - Rewrite the ISO/IEC 25023 paragraph (after the format block) so it says that 25023 supplies measure concepts and 29119-4 supplies techniques with coverage measures, that neither supplies project thresholds or targets, and that the user approves both. This must be one rewritten paragraph, not a new paragraph.
   - Rewrite `# Verification model`:
     - Coverage = exercised coverage items / declared coverage items, and each obligation states its approved target.
     - Specification-based techniques: equivalence partitioning, classification tree, boundary value analysis (2- or 3-value), syntax, combinatorial (each choice, base choice, pairwise, all combinations), decision table, cause-effect graphing, state transition, scenario, random, metamorphic. Their coverage items are enumerated finitely in the spec. A target below 100% names the selected items and the rationale. Keep the rule that listing dimensions does not imply their Cartesian product.
     - Structure-based techniques: statement, branch, decision, branch-condition, branch-condition combination, MC/DC, data flow. The spec names the tool and the Implementation scope, and main measures coverage. Main maps a shortfall to behavior: undeclared behavior is a spec gap or implementation defect, and declared behavior is a test defect. Test roles get behavior and measured values only.
     - Experience-based technique (error guessing): list the guessed defects as coverage items, with target `none — experience-based`.
     - Replace the old "Use boundary values, transitions and combinations ..." sentence rather than keeping both.
   - Evidence sufficiency sentence: add "meets the approved coverage target" to it.
   - Workflow step 1: pre-0.10 specs get a technique, coverage items, and target for each obligation, approved before dispatch.
   - Workflow step 2: "Define measures, thresholds, 29119-4 techniques, coverage items and targets, evidence, and traceability".
   - Workflow step 3: the test-implementer instructions include the 29119-4 techniques and coverage items.
   - Workflow step 8: obligations pass at their approved coverage target, rewritten inside the existing sentence and wrapped at about 80 columns.
2. Rewrite `harness/skills/requirement-oracle/SKILL.md` lines 20–30: express verification scope as 29119-4 techniques, coverage items, and targets. State that 29119-4 defines coverage measures but not targets, alongside the existing 25023 threshold statement. Structure-based targets require measurement by main.
3. Rewrite `harness/agents/test-implementer.md`:
   - Plan (lines 27–39): apply each obligation's declared technique and exercise every enumerated coverage item. Do not derive extra items or choose representatives. Structure-based targets are measured by main, and the test-implementer receives only measured values and behavior-level gaps.
   - Report map (lines 59–61): include the technique and the coverage items exercised.
4. Rewrite `harness/agents/test-verifier.md` lines 32–43: every declared specification-based coverage item has evidence and the achieved coverage meets the target. Structure-based obligations cite main's measured value, tool, and target. An experience-based row lists its guessed defects.
5. Set `harness/VERSION` to `0.10.0`. In `installer/harness.py`, add a `migrate_test_design_coverage` function modeled on `migrate_verification_scope` and register it in `MIGRATIONS` as `(0.10.0, "declare 29119-4 test design techniques and coverage targets", ...)`. Its plan text includes "before resume".
6. Tests:
   - `tests/test_installer.py`:
     - `test_090_...`: pass input `"y\ny\n"`, because 0.10.0 now also prompts when upgrading from 0.8.0.
     - `test_c4_...`: extend the version regex and the expected list with `0.10.0`, and add one more `y\n` to the input.
     - Add a 0.10.0 migration test modeled on test_090: specs and archives are byte-identical, the dry run prints "before resume", declining leaves a clean snapshot, and a repeated update does not announce 0.10.0.
     - Add assertions that the installed workflow text names 29119-4 and the coverage target in the stop condition.
   - `tests/test_telemetry.py:1101`, `tests/test_workflow_markers.py:192,713`: change `0.9.0` to `0.10.0`.
7. Run `python3 -m unittest discover -s tests`, then `python3 installer/harness.py update .` and `python3 installer/harness.py doctor .`.

Acceptance criteria:
- Obligation rows carry a technique, coverage items, and a target, and the old `boundary/transition/combination` column is gone.
- Test roles never receive Implementation locations for structure-based coverage.
- No 29119-4 instruction is appended beside the unchanged text it supersedes.
- The full suite passes, and the dogfood install matches the payload.

## Open Questions
- Three separate columns or one combined column for technique, coverage items, and target. Recommendation: three columns, for readability in the approval review. Both are compatible with heading-only validation.
- Whether the partial draft saved in the stash has wording worth reusing. Compare it after the rewrite. It is not authoritative.

## Spec
none — the change is limited to instruction and installer edits made directly, not a workflow-approach run.

## Execution Ledger
none — no workflow run, verifier invocation, or mutation was executed.

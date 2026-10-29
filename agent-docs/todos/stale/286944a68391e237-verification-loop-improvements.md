# Reduce verification correction loops

## Goal
"이 세션 작업에 대한 세부 컨텍스트는 제외하고, 어떻게 test-verifier 및 연관 지시, sub-agents를 개선할지 handoff로 남겨놔"

Improve the contract workflow so a verifier completes one broad audit, related gaps are corrected together, and test-only defects do not trigger unnecessary implementation work.

## State
- Branch: `feat/harness-analytics-2`
- Commit: `3ec897f4eb93cc3f634f41bf0dc6276781a8e5fb`
- Implementation has not started.
- Relevant source files: `harness/skills/contract-workflow/SKILL.md`, `harness/agents/test-implementer.md`, `harness/agents/test-verifier.md`, `harness/agents/implementer.md`, `tests/test_installer.py`.
- The current workflow already defines verification obligations, coverage maps, finding ledgers, seed checks, batched correction, and fresh verifier use. It does not fully enforce a pre-correction audit barrier or prevent implementation redispatch for test-only findings.

## Failed Attempts
| attempt | failure evidence | cause |
|---|---|---|
| Correct each verifier finding as soon as it appears | Later audits can expose sibling variants of the same rule and require another correction cycle | verified: correction starts before the full target/input/state space is audited |
| Map tests only to broad case IDs | A case may be marked covered while event types, required arguments, state transitions, or failure modes remain untested | verified: case-level coverage does not demonstrate obligation-variant coverage |
| Redispatch both implementation and test roles for every finding | Test-oracle gaps can cause implementation churn even when observable behavior is already correct | hypothesis: role routing is described but not enforced strongly enough in correction instructions |
| Treat a passing suite as readiness for final verification | Existing assertions may all pass while a plausible contract-breaking mutation escapes | verified: suite success measures implemented assertions, not completeness of the oracle |

## Next Step
Create a contract for the workflow change and update the source payload, never generated `.agents/`, `.claude/`, `.codex/`, or `.harness/` files directly.

1. Add a verification-matrix preflight before implementation dispatch. The main agent must enumerate each obligation by target, input class, boundary, state transition, and meaningful combination. Unresolved cells are contract challenges.
2. Require `test-implementer` to return a machine-checkable coverage map with one row per obligation variant: expected-value source, observable assertion, plausible escaping defect, and exact test evidence. It must perform sibling review before submission and declare every obligation mapped or challenged.
3. Require `test-verifier` to finish the entire audit before recommending any correction. Its response must include audit completeness, unmapped obligation variants, sibling variants for every finding, grouped finding IDs, and 2–3 seed proposals. A partial audit cannot trigger correction or report pass.
4. Add a correction barrier to the main workflow: triage all findings, execute the selected seeds, then issue one batched correction instruction. Do not redispatch while the audit is incomplete.
5. Route corrections strictly by disposition. Test defects go only to `test-implementer`; implementation defects go only to `implementer`; contract gaps amend the contract and redispatch both. Each role must reject assignments outside its disposition.
6. Require table-driven or generated tests when one rule applies to a finite family such as required arguments, event kinds, enum values, terminal states, or lifecycle transitions. Coverage maps must name excluded combinations and why they are inapplicable.
7. After correction, rerun every confirming seed before starting a fresh verifier. The intended assertion must catch the mutation; unrelated failures are inconclusive. The fresh verifier receives the full updated map and ledger and audits the complete contract once.
8. Add installer tests that assert the generated agent instructions preserve these ordering and routing rules. Run the full repository suite, update the dogfood installation with `python3 installer/harness.py update .`, and run `doctor`.

Acceptance criteria:
- No correction dispatch can occur before an explicit complete-audit declaration.
- Every verifier finding contains obligation variants and sibling review, not only a broad case ID.
- A test-only finding cannot cause implementer redispatch.
- All confirmed findings from one audit are corrected in one batch.
- Closure requires complete coverage-map reconciliation, successful seed rechecks, a passing restored suite, and one complete fresh audit.

## Open Questions
- Prefer adding a dedicated preflight verifier before implementation only if the test-implementer's mandatory matrix self-review proves insufficient; otherwise avoid another agent round.
- Decide whether an incomplete verifier response should be continued with the same verifier or replaced. Recommendation: continue the same verifier until its initial audit is complete; use a fresh verifier only after tests change.
- Decide whether repeated omission of required output fields should be mechanically validated. Recommendation: define a small structured report schema and validate it in orchestration tests where practical.

## Contract Snapshot
none

---
name: contract-workflow
description: Contract-first implementation and test workflow with implementer, test-implementer, and test-verifier subagents. Use before feature/fix level implementation or debugging. Not for typo fixes, renames, config or doc edits, or local bug fixes.
---

# Contract

A contract is a session-scoped working file, not persisting documentation.

1. Location: `agent-docs/contracts/<kebab-case-name>.md`. Excluded from Index & Staleness Management: no `index.md`, `stale.md`, or `<hex-id>-` naming.
2. Hooks delete `agent-docs/contracts/` on the end of the session.
3. Only the main agent writes or amends a contract. Subagents read it and are given its path and version.
4. Amendment: bump `version`, append a Version Log entry, re-dispatch. Never edit a contract silently.
5. Format:

````
---
version: <n>
---

# User Intent
| id | intention | goal to achieve |

# Paths
Implementation: <comma-separated repo paths>
Tests: <comma-separated repo paths>
Test command: <one shell command that runs the full suite, including Tests>

# Signatures
<signature per line>

# Errors
<failure condition — observable signal, including non-exception failures — post-failure state>

# Cases
| id | level | input / state | expected result |

# Verification Obligations
| id | parent intent/Case ids | rule and applicable targets/input classes | boundary/transition/combination | observation and expected result |

# Version Log
## v<n>
- <what changed, and the evidence that forced the change>
````

6. Every intent item and case has an `id`. Tests, challenges, and verifier findings reference them.
7. `level` is one of `normal`, `boundary`, `error`, `edge`. Each level has at least one row. When a level cannot occur, write `| - | <level> | none — <reason> | - |`. An `error` row names the signal and post-failure state from `# Errors`; require an exception type only when an exception is specified.
8. `Implementation` and `Tests` are disjoint. `implementer` never reads `Tests`; `test-implementer` and `test-verifier` never read `Implementation`.
9. Before dispatch, confirm User Intent with the user. If an intent item is ambiguous or conflicts with another, ask the user; do not resolve it yourself.

# Shared Verification Criteria

The main agent defines `# Verification Obligations` before dispatch. Give each
independently checkable obligation a stable id and parent intent/Case ids. Split
broad Cases into obligations with explicit targets and observable expectations;
an example is not a complete list of a universal rule's targets.

Include the applicable contract-defined input classes and boundary points with
neighboring values, state before/after transitions, each named target of shared
rules, and each required argument omitted alone with other arguments valid.
For independent conditions affecting one behavior, specify valid pairwise
combinations and any higher-order combination required by the behavior. Record
inapplicable dimensions with reasons; do not invent domains or enumerate an
unbounded Cartesian product. Resolve undefined expected results with the user.

These obligations are the common acceptance scope for both test roles. The
coverage map records obligation/parent ids, variants and level, observation,
expected-value source, plausible escaping defect, and test/assertion evidence.
Both roles independently check for omissions in the obligations. A missing or
ambiguous obligation is a contract challenge, not permission to choose behavior.
Only the main agent amends the contract and version.

# Subagent Model

Use the model and effort set in each agent definition (`.claude/agents/`, `.codex/agents/`). Override them only when the user names a model.

# Telemetry Markers

The main agent records the semantic lifecycle of every contract-workflow run. Choose one stable run ID for the run and use the contract filename without `.md` and its current version in the start marker. Marker commands are best-effort: invoke them normally, never inspect their result, and never let a failure change the workflow.

```sh
python3 .harness/bin/workflow_marker.py start --run-id ID --contract NAME --contract-version N
python3 .harness/bin/workflow_marker.py phase --run-id ID --phase implement_test
python3 .harness/bin/workflow_marker.py phase --run-id ID --phase verify
python3 .harness/bin/workflow_marker.py phase --run-id ID --phase amend
python3 .harness/bin/workflow_marker.py verifier --run-id ID --round N --result pass|retry|limit --findings N --seeds-run N --seeds-detected N
python3 .harness/bin/workflow_marker.py end --run-id ID --status complete|handoff|aborted
```

Emit `start` after the contract is confirmed and immediately before dispatching implementation and tests. Emit `implement_test` before that parallel step and `verify` before dispatching a verifier. Emit one `verifier` marker after every verifier result: `pass` when it passes, `retry` when its findings send work back through amend, and `limit` when the workflow limit stops further correction. Its round is the one-based verifier invocation count, separate from correction batches. Emit the result after triage and any seeds for that audit; use zero for counts that did not run. Count grouped finding ids, and seed executions/detections for that audit, without including later regression rechecks. Emit `amend` before every amendment or correction redispatch. Emit `end complete` after a completed workflow, `end handoff` when the limit writes a handoff, and `end aborted` whenever the workflow stops for another reason. Do not emit markers for ordinary tool activity or intermediate prose.

# Workflow

Contract before code. Implementation and tests both derive from the contract, never from each other.

1. **Ground (main).** Read the deciding source files yourself. Delegate only locating them: signatures, types, and failure behavior enter the contract from lines you have read.
2. **Contract (main).** Write the contract including Paths and Verification Obligations under the shared criteria. Resolve contradictory required/optional inputs and unavailable observation boundaries. Confirm User Intent (Contract rule 9).
3. **Implement + Test (parallel).** Dispatch both on the same version without sharing either agent's output. Each instruction is task-specific and complete:
   - `implementer`: contract path/version, implementation direction, critical constraints and risks, verification direction, and excluded approaches.
   - `test-implementer`: contract path/version, test conventions, risk model, independent-oracle strategy, test level, verification direction, and excluded approaches. Require its complete coverage map and pre-submission review.
4. **Reconcile (main).** Wait for both reports on the same version. Triage all challenges; amend the contract or reject each with evidence. If work is blocked, collect known corrections before redispatch. Otherwise run `Test command` exactly as written; the contract gate blocks it while either role is running. Classify failures against the contract: implementation defect, test defect, or contract gap. Queue corrections together, not one dispatch per finding.
5. **Verify (fresh `test-verifier`).** Once the suite passes and challenges are resolved, supply the contract path/version, complete coverage map, and finding ledger. Require a complete audit, including obligations missing from the map. An incomplete audit cannot pass; finish the audit with a replacement instruction before triage. After any test correction use a fresh verifier. Keep implementation code, injected diffs, and implementation reports out of verifier inputs.
6. **Triage and seed (main).** Maintain a session ledger in the main agent's working context: stable finding id, contract version, affected rule and variants, evidence, disposition, and seed outcomes. Keep it separate from the behavioral contract and include unresolved entries in any handoff. Resolve every finding before a correction dispatch: confirm from contract/test evidence, reject with a reason, or classify as a contract gap. Seed the 2–3 strongest concrete findings first (all if fewer); resolve the rest through evidence or additional seeds. Untested does not mean rejected. For each seed, one at a time:
   1. `python3 .harness/bin/seed.py backup <every file you will edit>`.
   2. Inject the specified contract-breaking behavior and run `Test command`.
   3. `python3 .harness/bin/seed.py restore`. If restoration exits non-zero, stop and report. Never restore with `git checkout` or `git stash`, which discard uncommitted implementation.

   A green suite confirms a gap only when the injected behavior was exercised. A failure rejects the seeded gap only when the intended assertion catches it; syntax, import, or unrelated failures are inconclusive. Retry an inconclusive seed or resolve from independent evidence. Record observations without exposing implementation details to test roles. While `.seed/` holds files, cleanup retains contracts; `seed.py status` lists an unrestored seed.
7. **Correct as a batch (main).** Group all known corrections, including sibling variants, into one redispatch cycle. Continue existing implementation/test agents; spawn replacements only if they cannot be continued. Each redispatch is a complete replacement instruction with the current contract path/version, applicable Version Log entry, full role-specific direction from step 3, and remaining assignment:
   - implementation defect: affected ids and expected observable behavior, without test code or assertion output.
   - test defect: affected ids/rules, all known missing variants, concrete failure evidence stripped of implementation code, and defect classes without injected diffs. Require sibling-case review and a complete updated map.
   - contract gap: main amends the contract and increments its version before redispatching both roles.

   After both reports, return to step 4 and run `Test command` on the restored implementation. If it fails, triage before further seeding. On a restored-suite pass, repeat each confirming seed; the intended assertion must now fail, and restore after each seed. Unresolved seed checks require triage, not a claimed fix. Then run step 5 with a fresh verifier and the updated ledger.
8. **Limit.** Initial dispatch is free; allow at most two subsequent correction batches. Increment the batch count once immediately before a correction redispatch, even when only one role needs changes. Its reconciliation, seed rechecks, and verifier audit do not increment the count. A further correction discovered during those checks requires another batch. Track the cause of each batch as contract gap, implementation defect, test defect, or a combination; count verifier invocations separately. When another correction is needed after two batches, stop and write a handoff with the complete contract, coverage/audit state, ledger, counters, and remaining work under the Handoff Rule.
9. **Close and report (main).** Complete only with a passing restored suite, complete verifier audit, no pending challenges/findings, and successful rechecks of confirming seeds. Report contract version, coverage map, finding dispositions (fixed/rejected/open with evidence), correction batches and causes, verifier count, blocked ids, and any handoff path.

---
name: workflow-approach
description: Spec-first implementation and test workflow with implementer, test-implementer, and test-verifier subagents. Use before feature/fix level implementation or debugging. Not for typo fixes, renames, config or doc edits, or local bug fixes.
---

# Spec

A spec is the approved, versioned source of truth for one workflow run. The
main agent alone creates and amends it. Subagents consume the assigned version
and never choose missing behavior.

## Identity and lifecycle

1. Active path: `agent-docs/specs/<16-hex-run-id>-<kebab-name>.md`.
2. Archived path: `agent-docs/spec-logs/<same-file-name>`.
3. `specs/` and `spec-logs/` are excluded from Index & Staleness Management.
4. Frontmatter fields are `version`, `run_id`, `status`, `base_commit`,
   `max_verifier_invocations`, and `handoff`. Status is `draft`, `active`,
   `complete`, `limit`, or `aborted`; use `handoff: none` when absent.
5. Amendment increments `version` and adds a Version Log entry. Never change an
   approved expectation silently. Reconfirm behavior, quality targets, or the
   verification policy when an amendment changes it.
6. Before dispatch, the user approves the whole spec. If a required decision is
   unresolved, pause. Use `requirement-oracle` when the user lacks enough domain
   or codebase evidence to decide.
7. Only after the user explicitly delegates an unresolved required decision may
   the main agent choose a default. Preserve safety, security, compatibility,
   data, and existing observable behavior in that order; record the choice,
   evidence, uncertainty, and delegation in `# Assumptions and Defaults`.
   Optional quality characteristics may be excluded with a recorded reason.

## Required format

````
---
version: <positive integer>
run_id: <16 lowercase hexadecimal characters>
status: draft|active|complete|limit|aborted
base_commit: <full commit id at workflow start>
max_verifier_invocations: 2
handoff: none|<repo-relative handoff path>
---

# User Intent
| id | stakeholder | intention | observable goal |

# Scope
In scope: <behavior and product boundary>
Out of scope: <explicit exclusions>

# Paths
Implementation: <comma-separated repo paths>
Tests: <comma-separated repo paths>
Test command: <one shell command covering all automated functional and quality checks>
Review evidence: <named procedure/output, or none — reason>

# Signatures
<signature per line>

# Functional Requirements
| id | requirement | priority | source |

# Errors
<failure condition — observable signal, including non-exception failures — post-failure state>

# Cases
| id | level | input / state | expected result |

# Quality Applicability
| ISO/IEC 25010:2023 characteristic | applicable | rationale |
| Functional suitability | yes|no | ... |
| Performance efficiency | yes|no | ... |
| Compatibility | yes|no | ... |
| Interaction capability | yes|no | ... |
| Reliability | yes|no | ... |
| Security | yes|no | ... |
| Maintainability | yes|no | ... |
| Flexibility | yes|no | ... |
| Safety | yes|no | ... |

# Quality Requirements
| id | characteristic / subcharacteristic | target and context | measure method / inputs / unit | threshold and direction | evidence: automated, review, mutation | source |

# Verification Obligations
| id | parent requirement/Case ids | applicable targets/input classes | boundary/transition/combination | observation and expected result | evidence procedure |

# Assumptions and Defaults
| id | decision | evidence and uncertainty | user approval or explicit delegation |

# Traceability
| requirement id | Case ids | obligation ids | evidence procedure |

# Workflow Control
| item | value |
| correction batches used | 0 |
| verifier invocations | 0 |
| open finding ids | none |

Execution ledger (append attempts; preserve failed approaches):
| attempt | finding / failure signature | cause hypothesis | changed approach / new evidence | result / disposition |

# Version Log
## v<n>
- <what changed and the evidence or decision that forced it>
````

Every intent, requirement, Case, quality requirement, obligation, and assumption
has a stable id. Each applicable quality characteristic has at least one quality
requirement. Each quality requirement defines the measured property and context,
method and input quantities, unit, threshold and pass direction, evidence
procedure, and source. ISO/IEC 25023 supplies measure concepts; it does not supply
project-specific pass thresholds. The user approves those thresholds.

`level` is `normal`, `boundary`, `error`, or `edge`; include every level or a
`none — <reason>` row. Error rows name both signal and post-failure state.
Implementation and Tests paths are disjoint. The implementer never reads Tests;
test roles never read Implementation.

# Verification model

Split broad requirements into independently checkable obligations. Cover each
named target, neighboring boundary values, state transition, independently
required argument omission, and valid pairwise combination. Add higher-order
combinations only when behavior requires them. Record inapplicable dimensions
instead of inventing domains or unbounded Cartesian products.

Automated evidence is preferred. Review evidence is permitted only with a
repeatable procedure, inputs, observation boundary, expected result, and named
artifact. Mutation evidence injects a concrete violating behavior and confirms
that the intended automated assertion rejects it; it supplements rather than
replaces the primary measurement or review.

# Subagent model

Use the model and effort in each installed agent definition. Override them only
when the user names a model.

# Telemetry

Telemetry commands are best-effort: never inspect their result or let failure
change the workflow.

```sh
python3 .harness/bin/workflow_marker.py start --run-id ID --spec NAME --spec-version N
python3 .harness/bin/workflow_marker.py phase --run-id ID --phase implement_test
python3 .harness/bin/workflow_marker.py phase --run-id ID --phase verify
python3 .harness/bin/workflow_marker.py phase --run-id ID --phase amend
python3 .harness/bin/workflow_marker.py verifier --run-id ID --round N --result pass|retry|limit --findings N --seeds-run N --seeds-detected N
python3 .harness/bin/workflow_marker.py end --run-id ID --status complete|limit|handoff|aborted
```

Emit `start` before the initial dispatch. Emit `implement_test` before the parallel
roles. Emit `verify` before dispatching a verifier.
Emit one `verifier` marker after every verifier result. Emit `amend` before every amendment or correction. Emit
`end complete` after completion, `end limit` when the verifier budget is exhausted,
`end handoff` for a nonterminal handoff, and `end aborted` after an approved
recovery abort. Do not emit markers for ordinary tool activity.

# Workflow

1. **Recover or ground (main).** Before creating a spec, inspect `specs/`. If an
   active spec exists, do not start another workflow. If its handoff is valid,
   resume only when requested. Without a handoff, compare `base_commit` to HEAD,
   summarize progress and drift, and ask the user whether to resume or archive it
   as aborted. Read deciding code yourself; delegate only location discovery.
2. **Draft and approve (main).** Derive functional requirements and all nine
   quality applicability decisions. Use `requirement-oracle` for decisions the
   user cannot assess. Define measures, thresholds, evidence, traceability, and
   the fixed budget of two verifier invocations per run. Obtain whole-spec approval,
   set status `active`, then run
   and check:
   `python3 .harness/bin/spec_lifecycle.py start --spec PATH --run-id ID`.
   Emit telemetry start only after lifecycle start succeeds.
3. **Implement + test (parallel).** Emit `implement_test`; dispatch both roles on
   the same spec version without sharing outputs. Instructions are task-specific
   and complete:
   - implementer: path/version, implementation direction, quality constraints,
     risks, allowed non-Test checks, and excluded approaches;
   - test-implementer: path/version, conventions, risk model, independent oracle,
     automated and review evidence, test level, and excluded approaches.
4. **Reconcile (main).** Wait for both reports. Resolve every challenge with
   spec/code evidence; amend or reject it with a reason. When unblocked, run the
   exact Test command. Classify failures as implementation defect, test defect,
   evidence defect, or spec gap and queue one correction batch.
5. **Verify (fresh test-verifier).** After a passing Test command, provide the
   spec path/version, complete coverage/evidence map, and finding ledger. Require
   a complete audit of functional and applicable quality obligations. Use a new
   verifier after any test or evidence-procedure correction. Before dispatch,
   check the budget and persist the incremented `verifier invocations` count in
   Workflow Control. The initial audit counts; at most two invocations are allowed
   per run, including failed, interrupted, or incomplete audits. Resume and spec
   amendments never reset the count. Never start a replacement run to evade it.
   Use the invocation count for telemetry `--round`.
6. **Triage and mutate (main).** Track stable finding id, spec version, affected
   obligation/variants, evidence, disposition, and mutation outcome. Resolve
   every finding before redispatch. Exercise the 2–3 strongest concrete findings
   first, all if fewer, one mutation at a time:
   1. `python3 .harness/bin/seed.py backup <every edited file>`.
   2. Inject the violating behavior and run Test command.
   3. `python3 .harness/bin/seed.py restore`; stop if restore fails.

   Green confirms a gap only when the mutation executed. A failure rejects it
   only when the intended assertion detects the violation. Retry an inconclusive
   mutation only with a changed probe that can distinguish execution from the
   observed failure. If no such probe is available, record it as blocked and
   hand off; never treat an inconclusive result as resolved. Never expose
   implementation or injected diffs to test roles.
7. **Correct as one batch (main).** Emit `amend`, increment the correction count,
   and redispatch complete replacement instructions. Continue existing agents
   where possible. Implementation defects receive ids and observable behavior,
   never test code. Test/evidence defects receive rules, variants, and sanitized
   evidence, never implementation diffs. A spec gap increments spec version and
   redispatches both roles. Reconcile, rerun the restored Test command, repeat
   confirming mutations, then use a fresh verifier.
8. **Stop condition.** Ordinary implementation, test, evidence, and spec
   corrections have no count limit; correction batches are recorded for history
   only. Complete only when every required functional and quality obligation
   passes, review artifacts exist, the verifier audit is complete with no open
   finding, and confirming mutations fail for the intended assertion. Triage the
   final audit before deciding: findings rejected with evidence need no further
   audit if tests, evidence procedures, and approved expectations are unchanged.
   If a further audit is required after two invocations, write a handoff, set
   `handoff`, set status `limit`, and archive the spec. Do not perform corrections
   whose required re-audit cannot fit within the remaining budget.

   For every ordinary retry, record the failure signature, cause hypothesis,
   changed approach or new evidence, and the observed result in the execution
   ledger. Continue while there is a concrete diagnostic or corrective next step.
   Do not repeat a failed approach without new evidence. If a resolved finding
   recurs or changes oscillate, compare prior attempts and re-evaluate the cause
   before editing again. Reopen spec decisions only with new evidence; unresolved
   decisions block dependent work until the user decides. If no new discriminating
   check or justified correction is available, finish independent work, write a
   nonterminal handoff, and request the missing decision or external change.
   Keep the spec active; this is not verifier-budget exhaustion.

   Use finite timeouts for test commands and mutation probes, chosen for the
   expected runtime. Check subagent progress with bounded waits; if it stalls,
   interrupt and diagnose before retrying. A timeout is never a pass and does not
   justify an unchanged automatic retry. Restore mutations before continuing or
   handing off; if restoration fails, stop and record the outstanding backup.
9. **Close or hand off (main).** For success, set status `complete`, archive with
   `python3 .harness/bin/spec_lifecycle.py archive --spec PATH --status complete`,
   then emit end complete. For limit, archive with `--status limit`, then emit end
   limit. If a nonterminal session stops, write the required handoff, store its
   path in the still-active spec, emit end handoff, and do not archive. Report
   spec version/path, evidence map, finding dispositions, correction causes and
   count, verifier count, mutations, blocked ids, and handoff if any.

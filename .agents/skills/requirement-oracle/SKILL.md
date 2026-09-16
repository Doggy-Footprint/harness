---
name: requirement-oracle
description: Pin down an unsettled feature request through re-questioning, then derive a test oracle from the settled plan. Use when scope or acceptance criteria are not yet fixed. Not for typo fixes, renames, config or doc edits.
---

# Grounding

1. Do not survey the codebase up front. Explore only when a user answer or question turns on a fact the code already settles.
2. Ask `code-explorer` one question at a time and read the cited `path:line` yourself. A fact enters this skill's output only from lines you have read.
3. Do not re-ask a question already answered in this session.

# Questioning

Work the axes below in order. Ask about an axis only while something in it is undecided, and only when the answer changes what gets built or how it is tested.

1. **Actor and trigger** — who invokes this, from where, how often. A requirement with no named actor is not yet a requirement.
2. **Scope and explicit non-scope** — cut to the thinnest slice that is independently useful and independently testable. Ask what can be left out of the first slice rather than what could be added.
3. **Acceptance criteria** — state each as `given <state>, when <trigger>, then <observable result>`. "Observable" means observable from outside the implementation: a return value, a stored record, an exit code, an emitted event. If a criterion can only be checked by reading the implementation, it is not yet a criterion.
4. **Failure modes** — for each way the trigger can fail (invalid input, absent dependency, concurrent actor, partial write), ask what the caller sees and what state is left behind. Silence here is the most common source of a wrong implementation.
5. **Quality attributes** — raise one only when it constrains the design: expected volume and latency, concurrency and idempotency, durability, permissions, backward compatibility. Do not walk the whole list for its own sake.
6. **Conflicts with existing behavior** — this is where a `code-explorer` query usually belongs. Name the existing behavior and ask which wins.
7. **Reversal cost** — if the answer is high, stop and hand off to `architecture-options` before settling the rest.

Rules:
- Never decide an unspecified detail yourself.
- Never phrase a question as a guess awaiting confirmation. Ask what is undecided, not whether your answer is right.
- When two answers conflict, quote both back and ask which holds.
- A "should", "probably" or "usually" in an answer is still undecided. Ask again for the rule.

# Oracle

Derive every expected result from the settled criteria. Never from implementation code, and never by running anything.

Derive cases, do not brainstorm them:

1. **Partition the input space.** For each input, split it into classes that the criteria treat the same way, and take one case per class. Two cases in the same class are one case.
2. **Take the boundary of every ordered class** — the last value inside and the first value outside, empty and one, first and last, zero and negative.
3. **Build a decision table** when the result depends on a combination of conditions. One case per reachable combination; state explicitly which combinations cannot occur and why.
4. **Walk the states** when the feature has a lifecycle. Cover each legal transition, and at least one transition attempted from a state that forbids it.
5. **Cover every failure mode** from the Questioning step. Each names the failure the caller sees and the observable state left behind.

When an exact expected value cannot be stated from the criteria alone, do not invent one. Assert a relation instead, and say which kind it is:
- an **invariant** that must hold after any run,
- a **round-trip** (encode then decode, write then read, install then verify),
- a **relation between two runs** (same input twice is identical; a superset input yields a superset result; order does not change the outcome).

Map every case onto a `level`:
- `normal` — a representative value from each ordinary class.
- `boundary` — the values from step 2.
- `error` — the failure modes from step 5.
- `edge` — reachable but rare combinations: concurrency, re-entry, absent optional state, the empty case.

Give each level at least one case. When a level cannot occur, write `| - | <level> | none — <reason> | - | - |` rather than leaving the level out silently. Every case carries an `id`.

# Output

Show the draft and get confirmation before writing.

Write `agent-docs/requirements/<16-char-hex-id>-<kebab-case-name>.md`:

````
# <Title>

## Goal
<the user's original words>

## Scope
## Out of Scope

## Acceptance Criteria
| id | given | when | then |

## Decisions
| id | question | user's answer |

## Open Questions

## Oracle
| id | level | input / state | expected result | derived from |
````

`derived from` names the acceptance criterion `id` and the technique that produced the case (partition, boundary, decision table, state transition, failure mode, invariant, round-trip, relation). A row with no source is a guess; drop it or ask.

Then update that directory's `index.md` per the Index & Staleness rules.

This file is standalone. It is not a contract. When implementation follows, `contract-workflow` writes its own contract and may carry these rows over.

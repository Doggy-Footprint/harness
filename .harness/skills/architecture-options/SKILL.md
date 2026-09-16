---
name: architecture-options
description: Lay out where a planned feature could attach in the current structure and what each placement costs. Use when the feature is decided but its placement is open. Not for choices the code already forces.
---

# Grounding

1. Do not survey the codebase up front. Query only for facts that actually separate the options: extension points, existing similar implementations, who depends on what.
2. Ask `code-explorer` one question at a time and read the cited `path:line` yourself. Cite only lines you have read.
3. One query per fact. Do not spend a second query re-confirming an answer you already have.
4. When a fact you need is absent from the code, say it is absent. Do not infer it.

# Frame

Before listing options, fix what the choice is being judged on. Without this the comparison degenerates into taste.

1. **Name the driving quality attribute** — the one thing this feature must not lose: correctness under concurrency, upgrade safety, startup cost, testability in isolation, backward compatibility with installed copies. Usually one, at most two. If the user has not named it, ask.
2. **Name the expected axis of change** — what is most likely to be added or modified next in this area. Structure should absorb the change that is coming, not every change imaginable.
3. **State the constraints that are not negotiable** — existing public surface, file ownership rules, platform parity, anything a hook or test already enforces.

# Options

Present 2-3 options. Never more. For each:

- **Where it attaches** — `path:line`.
- **Direction of dependency** — what starts depending on what. Call out a new dependency that points the wrong way (a general module gaining knowledge of a specific one), and any cycle it introduces.
- **Cohesion** — does the behavior end up in one place, or spread across places that must now change together? Name the places that must change together; that count is the real cost.
- **Extension vs. modification** — does adding the next instance of this require editing existing code, or only adding to it? Answer against the axis of change from Frame, not in the abstract.
- **What it makes easy / what it makes hard**, judged against the driving quality attribute.
- **Reversal cost** — can this be undone in an afternoon, or does it leak into callers, stored data, or installed copies? Distinguish a change that is local from one that changes a published interface.
- **Precedent already in this repo**, or `none`. A shape the repo already uses is cheaper than a better shape it has never used, because everything around it already assumes the old one.
- **What it costs even when unused** — an abstraction added for a case that has not arrived yet is a cost paid now against a benefit that may never come. Say so plainly.

Rules:
- Drop an option that is plainly worse than another on every axis, and say in one line why it was dropped.
- Do not invent a third option for symmetry. Two real options beat three padded ones.
- Compare against this repo's actual structure, not against general best practice. A pattern's reputation is not evidence about this codebase.
- Name the point where the options actually diverge — usually one decision, not the whole design. Everything downstream of it is the same either way; say that instead of repeating it per option.
- If the options differ only in naming or file placement, say the choice does not matter and stop.

# Recommend

State one recommendation, the driving quality attribute it optimizes, and the fact it rests on. Name what you are giving up by recommending it. The user decides; do not pick and proceed.

# Aftermath

Write nothing by default.

- If the user's decision meets every item on the ADR checklist, propose an ADR and write it only after confirmation.
- If the user rejected a concretely proposed option for a reason the code will not preserve, propose a Rejection Record under the same confirmation rule.
- Otherwise leave no document.

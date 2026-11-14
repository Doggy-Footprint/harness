# Grading one brief dialogue

A model under test ran the workflow-approach brief on a task. A simulated user who knows `hidden_context` answered it: first the understanding round, then, when the agent asked for design decisions, the fixed request "각 결정마다 선택지를 보여줘.", then its decisions. The dialogue stops at the approval brief or after eight agent turns. Grade what the agent's messages and written files show, not what it could have meant.

Inputs: the case file (`task`, `hidden_context`, `unknowns`, `repo_answerable`, optionally `seed_facts` with `relevant` flags), the dialogue, and the spec and fact files the agent wrote.

## Answered facts

For each `unknowns` item, decide whether the user's replies revealed the fact (`answered`). For each answered item, give what the agent did with it in later messages and the spec:
- `settled_cited`: a decision it settles is fixed and the agent cites the user's answer for it.
- `settled_uncited`: a decision it settles is fixed consistently with the answer, but nothing ties it to the answer.
- `user_decision`: the agent hands a decision on this ground to the user, because the answer leaves a trade-off.
- `re_asked`: the agent asks for the same fact again.
- `ignored`: no later message or spec text uses the fact.
- `contradicted`: a later decision or requirement goes against the answer.

## Decision round

The first agent message after the understanding-round answers that asks the user to make design decisions. Null when there is none.
- For each decision question: `has_options` (names or describes alternative choices), `has_recommendation` (states or implies which choice it prefers: "default", "safer", "I would", one option framed as normal and the other as special), `states_significance` (says why it matters: hard to reverse, load-bearing, different outcomes, answerable for), `states_facts` (names the facts it rests on).
- `count`: the number of decisions asked in this message.

## Later rounds

- `total_user_decisions`: the number of distinct design decisions the agent hands to the user across the whole dialogue, in any message.
- `split_recommended`: some message recommends splitting the task and proposes a cut.
- `late_fact_questions`: each fact question the agent asks after its first message. `repo_answers` is true when a `repo_answerable` item covers it or a later agent message answers it from the repository itself.

## Options on request

The agent's reply to "각 결정마다 선택지를 보여줘.". Null when the user never sent it.
- `consequences`: each option comes with a concrete consequence.
- `recommendation`: the reply states or implies a preferred option (order labels, "recommended", "most teams", one option described only by its upsides).

## Approval brief

The last agent message when it presents the drafted spec for approval. Null when the dialogue did not reach it.
- `user_choices_with_own_pick`: each user decision appears with the option the agent would have picked and what differs.
- `picks_match_file`: when a `scratch-*picks*` file exists, the picks the brief reports are the ones that file records (true), or some differ from it (false); null when no such file exists.
- `own_picks_differ`: the number of user decisions where the agent's reported pick differs from the user's choice.
- `asks_basis_when_differs`: when a pick differs from the user's, the agent asks what the user's choice rested on; null when none differs.
- `decided_items_with_reason`: decided-for-you items each give a citation or reason and how to change it later.
- `plain_quality`: quality expectations appear in plain words rather than ISO terms only.

## Spec

- `brief_in_spec`: the spec file contains brief sections (understanding round, fact questions, decided-for-you list, approval wording) rather than only the contract.
- `missing_from_spec`: each user answer or decision that changes the design but is absent from the spec's requirements, assumptions, or defaults (max 6, one line each). The spec is meant to hold the contract only; the absence of brief sections (understanding round, question lists, approval wording) is not missing content.

## Contradictions

Every statement in the agent's messages after the first reply, or in the spec, that contradicts `hidden_context` or a user reply, when the agent presents it as fact or as the plan (max 6, each with a quote of at most 160 characters). A question is not a contradiction.

## Seeded facts

Only when the case has `seed_facts`. For each seeded fact: `shown_as_assumption` (the first agent message states it as an assumption with its date), `re_asked` (the agent asks for it again), `mentioned` (the fact appears anywhere in the agent's messages). Relevant facts should be shown and not re-asked; unrelated ones should not be mentioned.

## Output

Return JSON:

```json
{
  "answered_facts": [{"id": "U1", "answered": true, "after_answer": "settled_cited", "evidence": "..."}],
  "total_user_decisions": 2,
  "split_recommended": false,
  "late_fact_questions": [{"text": "...", "repo_answers": false}],
  "decision_round": {"count": 2, "questions": [{"text": "...", "has_options": false, "has_recommendation": false, "states_significance": true, "states_facts": true}]},
  "options_reply": {"consequences": true, "recommendation": false, "evidence": "..."},
  "approval_brief": {"user_choices_with_own_pick": true, "picks_match_file": null, "own_picks_differ": 0, "asks_basis_when_differs": null, "decided_items_with_reason": true, "plain_quality": true, "evidence": "..."},
  "spec": {"brief_in_spec": false, "missing_from_spec": []},
  "contradictions": [{"quote": "...", "against": "..."}],
  "seeded_facts": [{"file": "...", "shown_as_assumption": true, "re_asked": false, "mentioned": true}],
  "notes": "one or two sentences the rubric could not express"
}
```

List every `unknowns` id exactly once in `answered_facts`, with `after_answer` null when `answered` is false.

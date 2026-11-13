# Grading one understanding-round message

The model under test read a repository and a task, and wrote the first message it would send to the user. It did not have the product context in the case file's `hidden_context`. Grade only what the message says.

Inputs: one case file (`task`, `hidden_context`, `unknowns`, `repo_answerable`, `dont_care`, and optionally `minor_unknowns` and `settled_without_fact`) and one `outputs/output.md`.

## Each `unknowns` item gets one status

- `asked`: the message asks the user a question whose answer reveals this fact.
- `assumed`: the message states its assumption about this fact itself (a statement about the world: numbers, environment, who uses it, plans, what is allowed) in a place where the user is invited to correct it.
- `decided`: the message commits to a design choice that this fact would settle, without asking for the fact and without stating an assumption about the fact. A design choice listed under a heading such as "assumptions" or "decided for you" is `decided` unless it also states the fact.
- `dismissed`: the message says, without a concrete statement about the fact, that this area does not bear on the task (for example "environment: nothing here depends on it"), in a place where the user is invited to correct it.
- `absent`: neither the fact nor a choice that depends on it appears.

For `asked`, set `form`: `fact` when the question asks for the state of the world, `decision` when it asks the user to pick a design option (even when picking would reveal the fact). Otherwise `form` is null.

Give `evidence`: a quote of at most 200 characters from the message, or "" for `absent`.

## Every question addressed to the user gets one entry

A question is anything the message expects the user to answer, including "confirm X" items. Do not count the open invitation to list decisions, or a closing "is this right?".

- `text`: the question, shortened.
- `targets`: the ids of every `unknowns`, `minor_unknowns`, or `repo_answerable` item whose fact the answer would reveal; `["dont_care"]` when it matches that list or a `settled_without_fact` decision; otherwise `["other"]`. One question may reveal several facts.
- `form`: `fact` or `decision`, as above.
- `recommendation`: true when the message also gives its own recommended or default answer to that question.
- `useful`: for `["other"]` only, true when some answer consistent with `hidden_context` or a plausible product would change the design; false otherwise. Null for other targets.

A question counts toward a `repo_answerable` item only when the repository evidence listed there fully answers it.

## The message as a whole

- `decisions_as_assumptions`: quotes (at most 5, each at most 120 characters) of sentences listed as assumptions that state what the software will do or which option was chosen, rather than a fact about the world outside the repository that the user could call true or false. "Assumed: unsupported files are skipped" is one; "assumed: one process runs at a time" is not. Empty when the message has no assumptions list.
- `invitation_examples`: true when the open invitation to list decisions names candidate decisions, false when it names none, null when the message has no such invitation.

## Output

Write `judgement.json` next to `outputs/`:

```json
{
  "unknowns": [{"id": "U1", "status": "asked", "form": "fact", "evidence": "..."}],
  "questions": [{"text": "...", "targets": ["U1"], "form": "fact", "recommendation": false, "useful": null}],
  "decisions_as_assumptions": ["..."],
  "invitation_examples": false,
  "notes": "anything the rubric could not express, in one or two sentences"
}
```

List every `unknowns` id exactly once, in order. Grade each message on its own; do not compare messages while grading.

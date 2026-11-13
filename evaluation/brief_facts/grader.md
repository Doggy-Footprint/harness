# Grading one understanding-round message

The model under test read a repository and a task, and wrote the first message it would send to the user. It did not have the product context in the case file's `hidden_context`. Grade only what the message says.

Inputs: one case file (`task`, `hidden_context`, `unknowns`, `repo_answerable`, `dont_care`) and one `outputs/output.md`.

## Each `unknowns` item gets one status

- `asked`: the message asks the user a question whose answer reveals this fact.
- `assumed`: the message states its assumption about this fact itself (a statement about the world: numbers, environment, who uses it, plans, what is allowed) in a place where the user is invited to correct it.
- `decided`: the message commits to a design choice that this fact would settle, without asking for the fact and without stating an assumption about the fact. A design choice listed under a heading such as "assumptions" or "decided for you" is `decided` unless it also states the fact.
- `absent`: neither the fact nor a choice that depends on it appears.

For `asked`, set `form`: `fact` when the question asks for the state of the world, `decision` when it asks the user to pick a design option (even when picking would reveal the fact). Otherwise `form` is null.

Give `evidence`: a quote of at most 200 characters from the message, or "" for `absent`.

## Every question addressed to the user gets one entry

A question is anything the message expects the user to answer, including "confirm X" items. Do not count the open invitation to list decisions, or a closing "is this right?".

- `text`: the question, shortened.
- `target`: the id of the `unknowns` or `repo_answerable` item it is about, `dont_care` when it matches that list, otherwise `other`.
- `form`: `fact` or `decision`, as above.
- `recommendation`: true when the message also gives its own recommended or default answer to that question.
- `useful`: for `other` only, true when some answer consistent with `hidden_context` or a plausible product would change the design; false otherwise. Null for other targets.

A question counts toward a `repo_answerable` item only when the repository evidence listed there fully answers it.

## Output

Write `judgement.json` next to `outputs/`:

```json
{
  "unknowns": [{"id": "U1", "status": "asked", "form": "fact", "evidence": "..."}],
  "questions": [{"text": "...", "target": "U1", "form": "fact", "recommendation": false, "useful": null}],
  "notes": "anything the rubric could not express, in one or two sentences"
}
```

List every `unknowns` id exactly once, in order. Grade each message on its own; do not compare messages while grading.

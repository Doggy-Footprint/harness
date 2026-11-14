---
version: 1
run_id: 1b81d06b91eeb079
status: active
base_commit: ba8371a30185421045dab149bbe1bb324d4cb4cd
max_verifier_invocations: 2
commit: ba8371a30185421045dab149bbe1bb324d4cb4cd
---

# User Intent
| id | stakeholder | intention | observable goal |
| --- | --- | --- | --- |
| I1 | harness owner | see the direction of the questions the agent asks the user in workflow-approach briefs | for every `brief` event whose pointer (session id + `tool_use_id`) locates a Claude transcript turn, the dashboard lists the turn's fact questions and decision questions as written |
| I2 | harness owner | check that what the agent tells the user is what was intended | for the same briefs the dashboard shows the understanding-round "what I understood" section and the full text of the brief turn |
| I3 | harness owner | see question direction across runs, not one run at a time | the summary lists the parsed questions of all runs, newest first, each opening its run's detail |
| I4 | harness owner | keep brief events from being lost when the agent passes marker values through shell variables | SKILL.md tells the agent to write marker arguments literally |

# Scope
In scope: a rule-based (non-LLM) parser of Claude transcript turns located by `brief` event pointers; a local sqlite cache of parse results; `/api/runs/{run_id}` and `/api/summary` additions; dashboard display in the run detail Brief card and a new summary card; one SKILL.md Telemetry sentence on literal marker arguments with harness version 0.49.1 and its migration entry.
Out of scope: briefs without a pointer (written before 0.49.0, or whose marker was not recorded); Codex transcripts; classifying questions into categories; parsing approval briefs into items; the fields rejected in run 49bafb302bb6593c (assumption list, fact-question dimension tokens, not-asked dimensions, exclusions as a separate field, significance criteria, split proposal, Decided-for-you titles, picks-differing lines, Conflict and New concept presence, reply latency, reply length, invitation answered, veto wording, parse status, parser version); any free text in telemetry jsonl; export of parse results; changes to the brief format the SKILL asks for.

# Paths
Implementation: analytics/brief_parser.py, analytics/store.py, analytics/app.py, analytics/frontend/src/App.jsx, analytics/frontend/src/hints.js, analytics/frontend/src/styles.css, harness/skills/workflow-approach/SKILL.md, harness/VERSION, installer/harness.py
Tests: analytics/tests/test_brief_parser.py, analytics/tests/test_brief_parse_api.py, analytics/frontend/src/BriefParse.test.jsx, tests/test_literal_marker_skill.py, and the existing files under tests/ whose harness version strings must move from 0.49.0 to 0.49.1
Test command: uv run --python 3.12 --with-requirements analytics/requirements.txt --with pytest --with hypothesis sh -c 'python tests/run_parallel.py && python -m pytest -q -p no:cacheprovider analytics/tests' && cd analytics/frontend && npx vitest run
Test convention: tests under `tests/` are `unittest.TestCase` classes, because `tests/run_parallel.py` collects only those. Tests never read files under `~/.claude` or `~/.harness`; transcripts are synthetic JSONL written to temporary directories.
Review evidence: R1 — real-brief check. After the Test command passes, main applies `parse_brief_text` to the text of these real brief turns of session `a57c23b5-f803-408b-848a-ef0b960b7dde` (the transcript under `~/.claude/projects/-Users-hwansu-orca-workspaces-harness-fix-spec/`): run 49bafb302bb6593c's understanding round, decision round, and approval brief, and run 1b81d06b91eeb079's understanding round and approval brief, each turn's text built per F2 from the assistant record holding its first text block. Main lists by hand, before running the parser, the expected fact questions, decision questions, and whether an understanding section exists for each turn, writes both lists and the parser output to `<scratchpad>/1b81d06b91eeb079-r1.md` (outside the repository, because the repository is public and the text holds local paths), and computes recall and precision of question items (exact text match after F4 normalization) and of understanding presence. R2 — `git diff --stat ba8371a30185421045dab149bbe1bb324d4cb4cd -- tests analytics/tests analytics/frontend/src` plus `git diff` of pre-existing test files shows they changed only in harness version strings (0.49.0 → 0.49.1, including 0.49.1 appended to expected migration lists).
Fuzzing: none — the parser's no-crash property over random transcripts is a Hypothesis test inside the Test command (O9); there is no separate fuzz surface.
Mutation tool: none

# Signatures
Python: `analytics.brief_parser.locate_brief_turn(records: list[dict], tool_use_id: str) -> str | None`
Python: `analytics.brief_parser.parse_brief_text(text: str) -> dict` returning `{"understanding": str | None, "questions": [{"kind": "fact" | "decision", "text": str}]}`
Transcript record shapes the parser reads (Claude Code JSONL, one JSON object per line, chronological):
- assistant record: `{"type": "assistant", "isSidechain": false, "message": {"content": [<block>, ...]}}` with blocks `{"type": "text", "text": str}`, `{"type": "tool_use", "id": str, "name": str, "input": {...}}`, `{"type": "thinking", ...}`.
- user record: `{"type": "user", "message": {"content": str | [<block>, ...]}}`, optional `"isMeta": true`, optional `"isCompactSummary": true`; blocks `{"type": "text", "text": str}` or `{"type": "tool_result", "tool_use_id": str, "content": ...}`.
- other `type` values (`attachment`, `system`, `summary`, ...) carry no brief text.
API `/api/runs/{run_id}`: each `briefs[]` entry gains `parsed`: `null` or `{"text": str, "understanding": str | null, "questions": [{"kind", "text"}]}`. All existing keys unchanged.
API `/api/summary`: existing keys plus `brief_questions: [{"run_id", "stage", "round", "ts", "kind", "text"}]`.
SQLite (`analytics/store.py`): new table `brief_parse(session_id TEXT NOT NULL, tool_use_id TEXT NOT NULL, path TEXT NOT NULL, size INTEGER NOT NULL, mtime REAL NOT NULL, data TEXT, PRIMARY KEY(session_id, tool_use_id))` created with `CREATE TABLE IF NOT EXISTS`; `SCHEMA_VERSION` stays 2.

# Functional Requirements
| id | requirement | priority | source |
| --- | --- | --- | --- |
| F1 | `locate_brief_turn` finds the first assistant record whose `message.content` list holds a `tool_use` block with `id == tool_use_id`, ignoring records with `isSidechain: true`. If none exists it returns None. | must | I1, A1 |
| F2 | A *human prompt* is a user record that is not `isMeta: true` and not `isCompactSummary: true`, whose content is a string whose stripped text is non-empty and does not start with `<`, or a list holding at least one `text` block whose stripped text is non-empty and does not start with `<` and no `tool_result` block. The brief turn is the records after the last human prompt before the located record (or from the first record when there is none) up to, not including, the first human prompt after it (or to the end). `locate_brief_turn` returns the `text` of every `text` block of the turn's assistant records that are not `isSidechain: true`, in record order, stripped, empty ones dropped, joined with `"\n\n"`; `""` when the turn has none. | must | I2, A5 |
| F3 | `parse_brief_text` splits the text into lines and ignores lines inside fenced code blocks (from a line starting with ```` ``` ```` or `~~~` to the next such line, or to the end). A heading is a line matching `^(#{1,6})\s+(.*?)\s*#*\s*$`; its level is the count of `#`. Its title is classified, after removing `*`, `_`, and backticks and lowercasing, by the first match in this order: contains `fact question` or `사실 질문` → fact; contains `decision round` or `결정 라운드` → decision; contains `understood`, `understanding`, or `이해` → understanding; otherwise none. A heading's section is the lines after it up to, not including, the next heading whose level is ≤ its level, or the end. | must | I1, I2, A2 |
| F4 | An *item line* is a line inside a fact or decision section that starts at column 0 and matches `^\*\*\s*\d+[.)]\s*(.+?)\*\*` (item text = group 1) or else `^(?:[-*+]|\d+[.)])\s+(.+)$` (item text = group 1). Normalization removes every `**` and `__`, collapses runs of whitespace to one space, and strips; an item whose normalized text is empty is dropped. Lines inside a deeper heading of the section count as the section's lines. `questions` lists the items of every fact and decision section in text order, `kind` `fact` or `decision` from the section. | must | I1, A3 |
| F5 | `understanding` is the content of the first understanding section: its lines joined with `"\n"` and stripped, or None when there is no understanding section or its content is empty. | must | I2, A3 |
| F6 | For a `brief` event with `client == "claude"` and non-empty string `session_id` and `tool_use_id`, the API looks for the transcript among `transcript_cache` paths with client `claude` whose file stem equals `session_id` and whose parent directory is not named `subagents`, taking the lexicographically first. It reads that file as UTF-8, decodes each non-empty line as JSON, skips lines that fail to decode or are not objects, and sets `parsed` to `{"text": <locate_brief_turn>, **parse_brief_text(text)}` when the turn is found, else null. Any other event, a missing transcript, an unreadable file, or a not-found turn gives `parsed: null`. | must | I1, I2, A1, A6 |
| F7 | Parse results are cached in `brief_parse` keyed by (session_id, tool_use_id) with the transcript path, size, and mtime. A cached row is reused while the transcript's path, size, and mtime are unchanged; otherwise the brief is parsed again and the row replaced. A not-found turn is cached with `data` null. A missing transcript or unreadable file is not cached. One API request reads each transcript file at most once. | must | A4, Q1 |
| F8 | `/api/summary` `brief_questions` holds one entry per question of every `brief` event with non-null `parsed` (brief-only runs included), with that event's `workflow_run_id` as `run_id`, `stage`, `round`, `ts`, and the question's `kind` and `text`; ordered by `ts` descending (null last), then by stored event order, then by question order. No pre-existing key of `/api/summary` or `/api/runs/{run_id}` changes value because of this feature. | must | I3, A7 |
| F9 | The dashboard run detail Brief card shows, for each brief entry with non-null `parsed`: the questions list (each with a `fact` or `decision` label and its text; "No questions found." when empty), the understanding text with line breaks kept ("No understanding section." when null), and a collapsed "Original text" disclosure holding `parsed.text` with line breaks kept. For `parsed: null` it shows "Brief text not found.". All transcript-derived text renders as text, never as HTML. Existing Brief card content is unchanged. | must | I1, I2, A8 |
| F10 | The dashboard summary shows a "Brief questions" card listing `brief_questions` (run id, stage, kind, question text) in API order; the run id opens that run's detail as the run list does; "No brief questions." when empty. Every new hint key has non-empty `en` and `ko` text. | must | I3, A7 |
| F11 | `harness/skills/workflow-approach/SKILL.md` Telemetry section states that every marker argument is written as a literal value, because the telemetry hook reads the command text and does not expand shell variables, so a marker whose run id is a variable such as `$ID` is not recorded. | must | I4, A9 |
| F12 | `harness/VERSION` is `0.49.1`, and `installer/harness.py` `MIGRATIONS` has a 0.49.1 entry whose dry-run lines say the workflow-approach skill asks for literal marker arguments and that no existing files change. | must | AGENTS.md |

# Errors
- Transcript line that is not JSON or not an object — line skipped — the rest of the file is parsed.
- Transcript file missing, unreadable, or not UTF-8 — `parsed: null`, HTTP 200 — no cache row written, so a later request retries.
- `tool_use_id` not in the transcript (file still being written, or another file) — `parsed: null` — cache row with `data` null, reparsed when size or mtime changes.
- Brief event with null or non-string `session_id`/`tool_use_id`, or `client` other than `claude` — `parsed: null` — no file read.
- Turn with no assistant text — `parsed.text` `""`, `understanding` null, `questions` empty.
- Text with no matching headings — `understanding` null, `questions` empty.
- Unterminated code fence — every line after the fence is ignored.
- Any exception inside parsing one brief — that brief's `parsed` is null and the request still returns 200 with the other briefs parsed.

# Cases
| id | level | input / state | expected result |
| --- | --- | --- | --- |
| C1 | normal | Korean understanding turn: `## 제가 이해한 내용` section with two paragraphs, `## Fact question` with `1. **A?**` + indented sub-bullets and `2. **B?**`, then a `**묻지 않은 것:** ...` line | understanding = the two paragraphs; questions = fact `A?`, fact `B?` |
| C2 | normal | English decision turn: `## Decision round` with `**1. Which store?** (note)` and `**2. Retry policy?**`, indented bullets, a table | questions = decision `Which store?`, decision `Retry policy?`; understanding null |
| C3 | normal | transcript: human prompt, assistant text "checking", assistant tool_use T (marker), user tool_result, assistant text with the brief, next human prompt, assistant text "later" | `locate_brief_turn(records, T)` = `"checking\n\n<brief>"` |
| C4 | edge | brief text before the tool_use in the same record; brief text in a sidechain record; `isMeta` user record and a user string starting with `<local-command` between tool_use and brief text; compact summary record | sidechain text excluded; meta, `<`-prefixed, and compact-summary records do not end the turn |
| C5 | boundary | heading levels: `## U` (understanding) followed by `### sub`, then `## next`; `# top` after `### U` | `### sub` stays inside; `## next` ends; `# top` ends a level-3 section |
| C6 | boundary | item lines: `- a`, `* a`, `+ a`, `1. a`, `1) a`, `**1. a**`, `**1) a** rest`, ` - a` (indented), `-a` (no space), `**a**` (bold, no number), `| a |`, `- ****` | first seven are items (texts `a`), the rest are not |
| C7 | edge | heading inside a fenced code block; unterminated fence | ignored; all lines after the fence ignored |
| C8 | edge | title case and emphasis: `## **Fact Questions**`, `## ` + "`Decision round`", `## UNDERSTOOD` | fact, decision, understanding |
| C9 | normal | API: run with two brief events in one transcript and a brief-only run in another | each `briefs[].parsed` filled; `brief_questions` ordered per F8 |
| C10 | error | brief with missing transcript; with null tool_use_id; codex client; tool_use_id absent from file; file with invalid UTF-8; file with a broken JSON line | `parsed: null` for the first five; the broken-line file still parses other lines |
| C11 | edge | second request with transcript unchanged after it became unreadable (`chmod 000`, size and mtime unchanged); then the file grows | second request still shows the parsed result (cache); after growth with the file readable again, reparsed |
| C12 | normal | dashboard detail with parsed brief, null-parsed brief, parsed brief with empty questions and null understanding; text containing `<b>x</b>` | lists, empty messages, literal `<b>x</b>`; Original text collapsed until opened |
| C13 | normal | summary with and without `brief_questions` | card rows and link; empty message |
| C14 | normal | `harness.py update --dry-run` from 0.49.0 | prints the 0.49.1 migration header and its lines |

# Quality Applicability
| ISO/IEC 25010:2023 characteristic | applicable | rationale |
| --- | --- | --- |
| Functional suitability | yes | extraction and display are the deliverable; accuracy on real briefs is measured |
| Performance efficiency | yes | the dashboard re-runs on every request and transcripts reach several MB; reparsing unchanged files on each request would grow with history |
| Compatibility | yes | existing API keys, an existing sqlite file from 0.49.0, and existing tests must keep working |
| Interaction capability | yes | new text-heavy views need empty states, collapsed long text, and en/ko hints |
| Reliability | yes | transcripts are external, may be partly written or malformed; parsing must never fail the dashboard |
| Security | yes | transcript text is untrusted input rendered in the browser |
| Maintainability | no | the parser is one module with two pure functions (F1–F5); no separate measure beyond the functional tests |
| Flexibility | no | only Korean and English briefs are expected (fact `ce4501e4cadc3a6c`) |
| Safety | no | no physical or irreversible effect; transcripts are only read |

# Quality Requirements
| id | characteristic / subcharacteristic | target and context | measure method / inputs / unit | threshold and direction | evidence: automated, review, mutation | source |
| --- | --- | --- | --- | --- | --- | --- |
| Q1 | Performance efficiency / time behaviour | repeated API requests over unchanged transcripts | a request after an unchanged-transcript request is served from cache: observed by making the transcript unreadable with size and mtime unchanged; count of briefs whose `parsed` becomes null | 0, lower is better | automated O6 | F7 |
| Q2 | Functional suitability / functional correctness | real Korean briefs of this project | R1 recall and precision of question items and of understanding presence, in % | each ≥ 80%, higher is better | review R1 | I1, I2, fact `64391ca09d2e5206` |
| Q3 | Compatibility / co-existence | analytics API outputs and an existing database | metamorphic: dataset D versus D with transcripts present for its brief pointers; count of differing values among pre-existing keys of `/api/summary` and `/api/runs/{id}`; plus an sqlite file created by the 0.49.0 `initialize` with imported events opened by the new code: events kept and `brief_parse` created | 0 differing values; events kept, table present | automated O7, O8 | F8, A4 |
| Q4 | Reliability / fault tolerance | parser under arbitrary transcript content | Hypothesis random testing, 300 examples, seed 49: random record lists (random types, contents, block lists, ids, strings with headings, fences, bullets) to `locate_brief_turn` and random text to `parse_brief_text`; count of raised exceptions or results violating the Signatures shape | 0, lower is better | automated O9 | F1–F5 |
| Q5 | Security / integrity | transcript text in the dashboard | rendering text containing `<script>`, `<img onerror>`, and `<b>` in questions, understanding, and original text; count of created `script`, `img`, or `b` elements | 0, lower is better | automated O10 | F9 |
| Q6 | Interaction capability / operability | dashboard views | each new hint key has en and ko text; Original text collapsed by default; each empty state message shown | all present | automated O10, O11 | F9, F10 |

# Verification Obligations
| id | parent requirement/Case ids | variant and target surface | test layer and selection policy | ISO/IEC/IEEE 29119-4 technique | coverage items | coverage target | observation and expected result | evidence procedure |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| O1 | F1, F2, C3, C4 | `locate_brief_turn` on in-memory record lists | unit; every rule | decision table | T1 tool_use id found; T2 not found; T3 found only in a sidechain record; T4 no human prompt before; T5 no human prompt after; T6 text before tool_use in same record; T7 text in later records of the turn; T8 text in sidechain record in the turn; T9 `isMeta` user record inside turn; T10 user string content starting with `<` inside turn; T11 compact summary record inside turn; T12 user list content with a `tool_result` block inside turn; T13 user list content with a text block (ends turn); T14 empty/whitespace text blocks; T15 thinking blocks; T16 two tool_use ids in different turns, each located to its own turn; T17 turn with no text | 100% | return value equals the expected joined text or None | Test command |
| O2 | F3, C5, C7, C8 | `parse_brief_text` | unit | equivalence partitioning | heading classes: fact by `fact question`, by `사실 질문`; decision by `decision round`, by `결정 라운드`; understanding by `understood`, `understanding`, `이해`; none; precedence (title with both `fact question` and `이해` → fact); emphasis/backticks/case removed; `#`×1..6 and 7 (not a heading); `##x` (no space, not a heading); trailing `#`s; fences ``` and ~~~; unterminated fence | 100% | section kinds observed through `questions` kinds and `understanding` | Test command |
| O3 | F3, F5, C5 | `parse_brief_text` section boundaries | unit | boundary value analysis (3-value) | next heading level = section level − 1, = level, = level + 1; section at end of text; first of two understanding sections used; empty understanding section → None | 100% | `understanding` text exact | Test command |
| O4 | F4, C1, C2, C6 | `parse_brief_text` item lines | unit | syntax testing | each line form of C6 (valid: 7; invalid: 6); item inside a deeper heading of the section; item outside any fact/decision section; normalization of `__`, inner whitespace runs | 100% | `questions` list exact | Test command |
| O5 | F1–F5 | `parse_brief_text` and `locate_brief_turn` | unit | metamorphic testing | MR1 appending a heading-free paragraph outside sections keeps output; MR2 replacing a Korean section keyword with its English pair (`사실 질문`↔`fact question`, `결정 라운드`↔`decision round`, `이해`↔`understood`) keeps output; MR3 splitting one assistant text block into two consecutive records keeps the questions and understanding; MR4 adding records after the next human prompt keeps the located text | 100% | outputs equal | Test command |
| O6 | F6, F7, C10, C11, Q1 | FastAPI TestClient over `create_app` with temp db, telemetry dir, and Claude transcript dir | integration | state transition | states: no row → parsed row (found) → reused (unchanged; observed with file made unreadable, size and mtime unchanged) → reparsed (file grown and readable); no row → null row (tool_use absent) → parsed after append; missing file → no row → parsed after file appears; unreadable file → no row → parsed after readable | 100% of transitions | `briefs[].parsed` values over successive requests | Test command |
| O7 | F6, F8, C9, C10 | TestClient | integration | decision table | A1 two briefs in one transcript both parsed; A2 brief-only run's brief parsed and in `brief_questions`; A3 ordering by ts desc, null ts last, ties by stored order then question order; A4 each null cause of C10 (missing file, null tool_use_id, codex client, absent id, invalid UTF-8); A5 broken JSON line skipped; A6 transcript under a `subagents` directory with the session stem ignored; A7 two candidate paths → lexicographically first; A8 brief whose parsed has no questions contributes no `brief_questions` entry | 100% | JSON values | Test command |
| O8 | Q3, F8 | TestClient, dataset D vs D+transcripts; sqlite file from 0.49.0 `initialize` | integration | metamorphic testing | MR1 summary pre-existing keys equal; MR2 each run detail's pre-existing keys and pre-existing `briefs[]` keys equal; MR3 an existing database file keeps its events and gains `brief_parse` | 100% | zero differing values; table exists; event count unchanged | Test command |
| O9 | Q4 | both parser functions | unit | random testing | 300 Hypothesis examples, seed 49, per function | 100% of examples | no exception; return shape per Signatures | Test command |
| O10 | F9, C12, Q5, Q6 | React components via vitest + Testing Library with stubbed fetch | unit | scenario testing | S1 parsed brief shows questions with kind labels and understanding with line breaks; S2 empty questions and null understanding messages; S3 `parsed: null` message; S4 Original text collapsed then shown on open; S5 HTML-like text rendered literally, no `script`/`img`/`b` elements created; S6 existing Brief card fields still shown | 100% | rendered text and DOM | Test command |
| O11 | F10, C13, Q6 | same | unit | scenario testing | S7 summary card rows in API order; S8 clicking run id requests `/api/runs/<id>`; S9 empty message; S10 every hint key has non-empty en and ko | 100% | rendered text, fetch URL | Test command |
| O12 | F11 | `harness/skills/workflow-approach/SKILL.md` | unit | syntax testing | K1 Telemetry section says marker arguments are written as literal values; K2 it gives the reason that the hook reads the command text and does not expand shell variables; K3 it names an unrecorded marker as the consequence | 100% | regex presence within the `# Telemetry` section | Test command |
| O13 | F12, C14 | installer `update --dry-run` on a repo installed at 0.49.0 (existing test helpers), and `harness/VERSION` | integration | equivalence partitioning | VERSION value; dry-run migration header for 0.49.1; lines mention literal marker arguments and no files change | 100% | stdout | Test command |

# Assumptions and Defaults
| id | decision | evidence and uncertainty | approval |
| --- | --- | --- | --- |
| A1 | only briefs with a pointer are parsed; no heading scan of transcripts without a pointer | user answer 2026-11-14 to "are pre-0.49.0 briefs needed": no | user answer |
| A2 | Korean and English heading keywords (F3) | fact `ce4501e4cadc3a6c` | fact ce4501e4cadc3a6c-data-brief-languages-korean-english.md |
| A3 | extracted: fact questions and decision questions as written, the understanding section, and the full turn text; no classification into categories; approval briefs are not split into items | fact `64391ca09d2e5206` (direction of questions; whether what is told is intended): questions as written and the full text serve both; Decided-for-you titles were rejected in run 49bafb302bb6593c | brief v1 — approved |
| A4 | results live only in the local analytics sqlite (`brief_parse`), as a cache derived from transcripts | fact `88f7f3e0ef2a3ecd` (multi-person collection is future work); `cleanupPeriodDays` 3650 in `~/.claude/settings.json` (2026-11-14) keeps transcripts available for re-parsing | brief v1 — approved |
| A5 | the brief turn runs from the human prompt before the marker call to the next human prompt | SKILL.md Telemetry: marker is emitted "in the same turn" as the brief; in this session the text came after the marker call within the turn | brief v1 — approved |
| A6 | Claude transcripts only, found through `transcript_cache` paths by session-id file stem | Codex unsupported (`AGENTS.md`); Claude transcript file names equal the session id (`~/.claude/projects/.../a57c23b5-....jsonl`) | brief v1 — approved |
| A7 | a summary "Brief questions" card across runs | fact `64391ca09d2e5206`: direction of questions is read across runs | brief v1 — approved |
| A8 | run detail shows questions and understanding expanded and the original text collapsed | full turns reach several thousand characters (run 49bafb302bb6593c approval brief) | brief v1 — approved |
| A9 | SKILL sentence on literal marker arguments, version 0.49.1 | this run's understanding-round marker passed `--run-id $RID` and left no `brief` line (grep of `~/.harness/telemetry` for `1b81d06b91eeb079`, 2026-11-14) | brief v1 — approved |
| A10 | no change to the brief format the SKILL asks for (no fixed parse markers) | rule-based headings are expected to suffice for Korean and English; reversal: R1 below 80% | brief v1 — approved |
| A11 | thresholds: fixture obligations at 100%; R1 recall and precision ≥ 80%; Hypothesis 300 examples, seed 49 | "100% is not the goal, trend level is enough" (user, 2026-11-14, run 49bafb302bb6593c) | brief v1 — approved |
| A12 | implementer, test-implementer, test-verifier use the installed default model (sonnet) | `.claude/agents/*.md`; no concurrency or security boundary beyond text rendering | brief v1 — approved |

# Traceability
| requirement id | Case ids | obligation ids | evidence procedure |
| --- | --- | --- | --- |
| F1 | C3, C4 | O1, O5, O9 | Test command |
| F2 | C3, C4 | O1, O5, O9 | Test command |
| F3 | C5, C7, C8 | O2, O3, O5, O9 | Test command |
| F4 | C1, C2, C6 | O4, O5, O9 | Test command |
| F5 | C1, C5 | O3, O5 | Test command |
| F6 | C9, C10 | O6, O7 | Test command |
| F7 | C11 | O6 | Test command |
| F8 | C9 | O7, O8 | Test command |
| F9 | C12 | O10 | Test command |
| F10 | C13 | O11 | Test command |
| F11 | — | O12 | Test command |
| F12 | C14 | O13 | Test command |
| Q1 | C11 | O6 | Test command |
| Q2 | — | R1 | review R1 |
| Q3 | — | O8 | Test command |
| Q4 | — | O9 | Test command |
| Q5 | C12 | O10 | Test command |
| Q6 | C12, C13 | O10, O11 | Test command |

# Workflow Control
| item | value |
| --- | --- |
| correction batches used | 0 |
| verifier invocations | 0 |
| open finding ids | none |

Audit state (one entry per obligation; retain prior decisions in the execution ledger):
| obligation id | spec version | evidence references and revision | accepted / open / invalidated / pending | rationale and mutation outcome | dependencies and reopening evidence |
| --- | --- | --- | --- | --- | --- |
| O1–O13 | 1 | — | pending | — | — |

Execution ledger (append attempts; preserve failed approaches):
| attempt | finding / failure signature | cause hypothesis | changed approach / new evidence | result / disposition |
| --- | --- | --- | --- | --- |

# Version Log
## v1
- Initial draft from the understanding round answers of 2026-11-14.

# Retrospective

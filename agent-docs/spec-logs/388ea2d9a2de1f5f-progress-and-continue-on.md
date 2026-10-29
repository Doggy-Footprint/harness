---
version: 5
run_id: 388ea2d9a2de1f5f
status: complete
base_commit: b16e923b7d320c869f411a4f06d0fb98a2cc856c
max_verifier_invocations: 2
handoff: none
commit: 128ab48fe66f4f0e082a396aee7e8ddc124bbdc1
---

# User Intent
| id | stakeholder | intention | observable goal |
| --- | --- | --- | --- |
| I1 | harness user | Every working session leaves an objective, session-scoped work record | a session that changed repository files ends with exactly one `agent-docs/progress/*.md` whose `session` is that session |
| I2 | harness user | A later session can pick up unfinished work by reading only what the earlier session marked for it | the user-invoked `continue-on` skill reads only the `## Next Session` section of one chosen progress and only the pointers listed there |
| I3 | harness user | Stale records are quarantined instead of silently reused | only one progress exists; writing a new one moves the old one to `agent-docs/progress-logs/`; carried entries whose files changed since their commit are flagged |
| I4 | harness user | Copied-forward entries are re-verified, not blindly re-stamped | a Next Session entry nearly identical to one in the predecessor progress but with a different commit triggers a warning that tells the agent to ask the user |
| I5 | harness maintainer | `workflow-approach` uses progress instead of handoff, and existing handoffs move to `todos` | no current harness rule, skill, script, or hook writes `agent-docs/handoff/` (the pre-existing 0.29.0 installer migration excepted, A15); `installer update` offers to move existing handoff records to `agent-docs/todos/` |
| I6 | harness user | The user's own words survive the session without leaking secrets into the repository | every user prompt of a session appears, masked, under the progress `### User Requests`; a commit containing an unmasked key, email, IP, or internal hostname in `progress/` or `progress-logs/` is blocked |

# Scope
In scope: progress record format and rules; progress rotation, entry checks, and stop enforcement hooks; automatic masked recording of user prompts into progress; pre-commit check for unmasked secrets in progress records; `continue-on` skill and its helper CLI; post-merge rotation; `verify_rules.py` checks for `progress/`, `progress-logs/`, `todos/`; replacing the Handoff Rule with Progress and Todo rules in `harness-block.md`; `workflow-approach`, `test-audit`, `rearrange-docs` changes from handoff to progress/todos; spec frontmatter `handoff` field becoming optional; `spec_lifecycle.py session` warning text; config paths and mask host suffixes; README mentions; installer 0.33.0 migration with the handoff→todos prompt; tests.
Out of scope: a store for project-wide lessons (separate future work); semantic or vector retrieval; masking free-text personal or customer data that has no fixed pattern (for example customer names; user accepted); `analytics/` changes for the new `progress_write` event; rewriting historical handoff, spec-log, or try-n-fail records; changing the pre-existing 0.29.0 installer migration; Codex behavior beyond best-effort file generation; GitHub-side (server) merges that never run local git hooks.

# Paths
Implementation: harness/lib/progress.py, harness/hooks/progress_hook.py, harness/bin/progress.py, harness/skills/continue-on/SKILL.md, harness/hooks/hooks.spec.json, harness/hooks/doc_commit.py, harness/git/post-merge, harness/git/verify_rules.py, harness/lib/config.py, harness/config.default.json, harness/bin/spec_lifecycle.py, harness/hooks/telemetry_hook.py, harness/instructions/harness-block.md, harness/skills/workflow-approach/SKILL.md, harness/skills/test-audit/SKILL.md, harness/skills/rearrange-docs/SKILL.md, installer/harness.py, harness/VERSION, README.md
Tests: tests/test_progress.py, tests/test_doc_records.py, tests/test_installer.py, tests/test_workflow_markers.py, tests/test_telemetry.py, tests/test_comment_gate.py, tests/test_session_metrics.py
Test command: uv run --no-project --with pytest --with hypothesis python3 -m unittest discover -s tests
Review evidence: R1 — main reads `harness-block.md`, `workflow-approach/SKILL.md`, `test-audit/SKILL.md`, `rearrange-docs/SKILL.md`, `README.md` and confirms no remaining instruction writes or reads `agent-docs/handoff/` except the installer migration notice and the historical-record notes (FR17, FR18); result recorded in the execution ledger. R2 — main confirms `continue-on/SKILL.md` frontmatter has `disable-model-invocation: true` and its steps read only the CLI's `show` output and listed pointers (FR11).
Fuzzing: none — parsing inputs are small Markdown files and prompts; malformed-input robustness is covered deterministically by O5 and masking by fixture sets in O13.
Mutation tool: none — no mutation tool is installed in this repository; hand mutations listed per obligation replace it.

# Signatures
CLI: python3 .harness/bin/progress.py show [PATH] [--session ID]   → prints the target's frontmatter, `## Next Session` section and a freshness report; exit 0, or 1 with a message when no target exists
CLI: python3 .harness/bin/progress.py check PATH                    → validates format, entry commits, freshness, near-duplicates; exit 0 clean, 1 with findings
Hook: python3 .harness/hooks/progress_hook.py                       → reads a Claude Code hook payload on stdin (`hook_event_name`, `session_id`, `cwd`, `prompt`, `tool_name`, `tool_input.file_path`, `stop_hook_active`); events SessionStart, UserPromptSubmit, PostToolUse (Write|Edit|MultiEdit), PreCompact, Stop
Hook output channels: PostToolUse feedback (FR5–FR8 reports, refusals, Errors rows) and Stop blocks (FR10) → exit 2 with the message on stderr; UserPromptSubmit notices and PreCompact reminders → exit 0 with the message on stdout; nothing to report → exit 0, no output
Hook file writes: the progress hook writes progress files itself (session/before fill, User Requests sync) and applies the same `commit:` stamp as `doc_commit.stamped`; `doc_commit.py` skips `agent-docs/progress/` so two PostToolUse hooks never rewrite the same file concurrently
Similarity: `similarity(a, b) = 1 - levenshtein(a, b) / max(len(a), len(b))` on whitespace-normalized text (runs of whitespace → one space, trimmed); two empty strings → 1.0
lib: progress.parse(text) -> Progress; progress.entries(progress) -> list[Entry]; progress.similarity(a: str, b: str) -> float  (normalized Levenshtein, 1.0 = identical)
lib: progress.fresh(entry, repo_root) -> bool; progress.rotate(new_path, session_id) -> Path | None
lib: progress.mask(text: str, host_suffixes: list[str]) -> str; progress.unmasked(text: str, host_suffixes: list[str]) -> list[tuple[int, str]]  (line number, category)
Config: `mask_host_suffixes` in `harness/config.default.json`, default [".corp", ".internal", ".local", ".lan", ".intranet"]; overridable in `.harness/config.json`
Installer: `python3 installer/harness.py update <target>` gains a handoff→todos prompt (FR19)

# Functional Requirements
| id | requirement | priority | source |
| --- | --- | --- | --- |
| FR1 | Progress lives at `agent-docs/progress/<16-hex-id>-<kebab-name>.md`. At most one `*.md` file exists directly in `agent-docs/progress/`. Rotated files live in `agent-docs/progress-logs/` under the same name. Both directories are excluded from Index & Staleness Management. | must | user |
| FR2 | Progress frontmatter: `session` (Claude Code session id), `before` (repo path of the progress moved to logs when this one was created, or `none`), `previous` (repo path of the progress this session continued through `continue-on`, or `none`), `branch`, and the existing file-level `commit:` stamp written by `doc_commit.py`. `before` and `previous` are independent: `before` records order only, `previous` records an explicit continuation. | must | user |
| FR3 | Progress body: `# <title>`; `## Next Session` with subsections `### State`, `### Next Step`, `### Constraints`, `### Verify`, `### Dead Ends`, `### Related`; `## Record` with subsections `### Changes`, `### Commands`, `### Failed Attempts` (table `| attempt | failure evidence | cause |`), `### Sources`, `### User Requests`. `### User Requests` is written by the hook (FR22); the agent does not edit it. | must | design |
| FR4 | Every bullet in `## Next Session` except under `### Constraints` is an entry followed by an indented metadata line `  - commit: <full or ≥7-char sha>; files: <comma-separated repo paths or none>`. `commit` is the commit the entry was checked against; a session with several commits records each entry's own commit. `### Constraints` bullets quote the user verbatim (from `### User Requests`, masked form) and carry `  - source: <where it was said>` instead. The file-level `commit:` stamp is kept alongside (A6). | must | user |
| FR5 | Writing a progress file whose `session` differs from the existing one's moves the existing file to `progress-logs/` (creating the directory if needed), sets the new file's `before` to the moved repo path, and fills a missing `session` with the payload `session_id`. The hook reports the move to the agent. | must | user |
| FR6 | Writing a second progress file with the same `session` as an existing one is refused: the hook reports to the agent that a session owns one progress and the new file must be merged into the existing one; neither file is moved. | must | user (one progress per session) |
| FR7 | Rotation is refused when another live harness session is running against the same checkout (a live marker in `.harness/sessions/.running` other than the current one, same liveness rule as `session_lock.py`): the hook reports that parallel sessions on one checkout are not supported; no file is moved. | must | user (parallel sessions prohibited) |
| FR8 | After each progress write the hook runs the entry checks of `progress.py check` and reports findings to the agent as feedback: (a) `commit` does not resolve or is not an ancestor of HEAD → stale; (b) any commit in `<commit>..HEAD` touches a path in `files` → stale; (c) entry text (metadata line excluded, whitespace-normalized) has similarity ≥ 0.90 with an entry in the `before` or `previous` progress's `## Next Session`, text length ≥ 20 characters, and the two `commit` values differ → near-duplicate warning instructing the agent to ask the user whether the entry was re-verified or copied. An entry with `files: none` is checked only by (a) and (c). | must | user |
| FR9 | SessionStart records `start_head`, `branch`, and an empty `prompts` list for the session in `.harness/sessions/progress-<safe-session-id>.json` (not committed). | must | design |
| FR10 | Stop: when the session changed repository files (HEAD differs from `start_head`, or `git status --porcelain` lists paths outside `.harness/`) and no file in `agent-docs/progress/` has this `session`, the hook blocks the stop once with a reason telling the agent to write progress; when the payload's `stop_hook_active` is true it does not block again. When this session's progress has `## Next Session` with no entries, it blocks once with a reason asking for the Next Session entries or an explicit `- none: <reason>` bullet. Before deciding, Stop runs the FR22 sync when this session has a progress. | must | user (every working session writes progress) |
| FR11 | `harness/skills/continue-on/SKILL.md` has `disable-model-invocation: true` and `argument-hint: "[progress-logs path]"`. It runs `progress.py show [ARG]`, reads only the printed Next Session and the pointers under `### Related`, reports missing pointers or pointers inside a `stale/` directory without searching further, summarizes State, Next Step, Constraints, and flagged entries to the user, and after the user confirms, ensures the current session's progress exists with `previous` set to the target. Information needed but not listed by the target goes into the current session's progress. It never reads try-n-fail, todos, or specs unless listed under `### Related`. | must | user |
| FR12 | `progress.py show` target resolution, with the current session id taken from `--session`, else the `CLAUDE_CODE_SESSION_ID` environment variable: the given PATH if it is inside `progress/` or `progress-logs/`; otherwise the file in `progress/` when its `session` is not the current session; otherwise the current session's progress's `before` file; otherwise exit 1 "no progress to continue". | must | user; env name observed (A14) |
| FR13 | `progress.py show` prints frontmatter, the `## Next Session` section verbatim, then a freshness report listing each entry as `fresh`, `stale: <reason>`, or `near-duplicate`, and a warning line when the Next Session has no entries. It never prints `## Record`. | must | user (partial read) |
| FR14 | `post-merge` moves every progress file the merge added (`git diff --name-only --diff-filter=A ORIG_HEAD HEAD -- agent-docs/progress/`) to `progress-logs/` and prints the moved paths, before delegating to the existing local hook (the delegation uses `exec`, so nothing after it runs). | must | user (merge ends a task) |
| FR15 | PreCompact prints a reminder to update this session's progress `## Next Session` before compaction, only when this session has a progress or changed repository files. | should | research (compaction drops constraints) |
| FR16 | `verify_rules.py`: fails when `agent-docs/progress/` holds more than one `*.md`; checks FR3 headings and FR4 metadata syntax for the file in `progress/`; skips format checks for `progress-logs/`; treats `agent-docs/todos/` as a managed directory (index.md, stale.md, stale/) requiring only `#` title and `## Next Step`, accepting any additional sections; no longer manages `agent-docs/handoff/`. | must | design; user (todos extensible) |
| FR17 | `harness-block.md`: the Handoff Rule is replaced by a Progress Rule (FR1–FR4, FR22, read only the Next Session of the chosen progress and its listed pointers when continuing, never guess related records, never edit a progress after its session ends, commit progress with the work) and a Todo Rule (work items not tied to a session; required `#` title and `## Next Step`, recommended `## Goal` and `## Related`, further sections allowed). Try-n-fail candidates come from a progress `### Failed Attempts` or a spec ledger. | must | user |
| FR18 | `workflow-approach`: spec frontmatter `handoff` becomes optional (not listed in the format); nonterminal stops and `limit` stops write the session progress (remaining work under Next Session, failed attempts under Record) instead of a handoff; Recover step no longer requires a handoff and resumes an active spec only when the user asks or runs `continue-on`. The telemetry end status token `handoff` stays for nonterminal stops (analytics compatibility, A18). `spec_lifecycle.py validate` stops requiring `handoff` and accepts it when present; `spec_lifecycle.py session` no longer mentions a handoff and instead points draft/active specs to the progress and `/continue-on`. `test-audit` writes one todo per feature group to `agent-docs/todos/` instead of handoffs; `rearrange-docs` treats `todos/` as it treated `handoff/`. `telemetry_hook.py` emits `progress_write` for writes to `agent-docs/progress/*.md` instead of `handoff_write`. | must | user |
| FR19 | `installer update` to 0.33.0: creates `progress/`, `progress-logs/`, `todos/` (todos with index.md, stale.md, stale/); registers the progress hooks; installs `continue-on`. The 0.33.0 migration runs after every earlier migration, so a handoff written by the 0.29.0 migration in the same update is included. When `agent-docs/handoff/` contains records other than index.md/stale.md, it lists them and asks, separately from the migration approval, whether to move all of them (including `stale/` and both index files, merged into todos' index/stale) to `agent-docs/todos/`. Yes → move. No, EOF, or closed/absent stdin ("no TTY"; piped answers are accepted like the earlier migration approvals) → leave `handoff/` untouched and print that it is no longer managed. The update never fails or raises `MigrationDeclined` because of this answer. | must | user |
| FR20 | Moved handoff records keep their content; `verify_rules.py` accepts them in `todos/` because they have `#` title and `## Next Step`. | must | project rule (no rewriting historical records) |
| FR21 | UserPromptSubmit appends `{"at": <UTC ISO-8601>, "text": progress.mask(prompt)}` to the session state file's `prompts` (creating the state file when SessionStart did not), and never stores the unmasked prompt anywhere. | must | user |
| FR22 | On every progress write (PostToolUse) and at Stop, the hook rewrites the `### User Requests` subsection of this session's progress from the state file: one `#### <n> — <at>` heading per prompt in order, followed by the masked text with every line prefixed `> `. Content before and after the subsection is preserved byte for byte; a missing subsection is appended at the end of `## Record`. | must | user (record in Record, A20) |
| FR23 | `progress.mask` replaces, in this order: (1) log blocks — fenced code blocks (``` or ~~~, unterminated fence runs to end of text), Python tracebacks (from `Traceback (most recent call last):` through the exception line), and runs of ≥ 3 consecutive lines each beginning (after optional whitespace or `[`) with a date-time `\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}`, a time `\d{2}:\d{2}:\d{2}`, or a level word TRACE/DEBUG/INFO/WARN/WARNING/ERROR/FATAL/CRITICAL followed by a non-letter — each whole block becomes one line `[masked:log <N> lines]`; (2) keys and tokens — `AKIA[0-9A-Z]{16}`, `gh[pousr]_` and `github_pat_` tokens, `sk-` tokens (≥ 20 chars after the prefix), `xox[abposr]-` tokens, `AIza` + 35 chars, JWTs (`eyJ…​.eyJ…​.…`), PEM private key blocks, `Bearer <≥16 chars>`, and the value of `password`/`passwd`/`pwd`/`token`/`secret`/`api_key`/`apikey`/`access_key` assignments (`:` or `=`) — become `[masked:token]`; prefixes match only at a non-alphanumeric boundary; (3) email addresses → `[masked:email]` except domains `example.com`, `example.org`, `example.net`, and TLDs `.test`, `.example`, `.invalid`, `.localhost`; (4) IPv4 addresses (octets 0–255) and IPv6 addresses (8 hex groups or a `::` form with ≥ 2 groups) → `[masked:ip]` except `127.0.0.0/8`, `0.0.0.0`, `::1`, `::`; (5) hostnames whose last label(s) match `mask_host_suffixes` → `[masked:host]`. Masking is idempotent: `mask(mask(x)) == mask(x)`. | must | user; categories and exceptions A19, A22 |
| FR24 | `verify_rules.py` fails when any `*.md` in `agent-docs/progress/` or `agent-docs/progress-logs/` contains a match of FR23 categories (2)–(5) (`progress.unmasked`), naming `<path>:<line>` and the category and telling the user to replace it with `[masked:<category>]`. The log-block rule (1) is not applied at commit time. | must | user (block commit) |

# Errors
Progress file with no frontmatter or unparsable frontmatter — hook feedback "invalid progress frontmatter: <reason>" — file left as written, no rotation, no User Requests sync.
Entry without metadata line — check finding "entry without commit metadata: <first 60 chars>" — no rotation change.
`git` unavailable or not a repository — hook exits 0 silently for SessionStart/PreCompact/Stop; PostToolUse reports "git unavailable; entry checks skipped" — no state change; UserPromptSubmit still records.
Destination already exists in `progress-logs/` — rotation refused with feedback naming the path — both files stay.
`progress.py show` PATH outside progress dirs — exit 1 "not a progress path" — nothing printed from the file.
Missing session state file at Stop — Stop uses `git status --porcelain` only — may block once; User Requests sync writes an empty subsection only when the subsection is missing.
State file unreadable or unwritable at UserPromptSubmit — stdout "harness: prompt not recorded in progress: <reason>; quote the user's constraints under ### Constraints manually" (added to agent context), exit 0 — prompt not stored anywhere.
UserPromptSubmit payload without `prompt` string — exit 0, nothing recorded.
Installer prompt interrupted (EOF) or no TTY — treated as No — handoff left untouched, update continues.

# Cases
| id | level | input / state | expected result |
| --- | --- | --- | --- |
| C1 | normal | empty `progress/`; session S writes P1 | P1 stays; `before: none`; `session: S` filled if missing |
| C2 | normal | `progress/` has P1 (session S1); session S2 writes P2 | P1 in `progress-logs/`; P2 `before: agent-docs/progress-logs/P1` |
| C3 | error | P1 (S1) exists; S1 writes P1b | refused, both stay, feedback about merging |
| C4 | error | P1 (S1) exists; another live session marker; S2 writes P2 | refused, no move, parallel-session feedback |
| C5 | normal | entry commit = HEAD, files unchanged | fresh |
| C6 | boundary | entry commit X; one later commit touches a listed file | stale: changed |
| C7 | boundary | entry commit X; later commits touch only other files, including the progress file itself | fresh |
| C8 | error | entry commit not in repo / not ancestor (rebased) | label starting `stale: unresolved` / `stale: not ancestor` |
| C9 | boundary | entry text similarity 0.90 vs predecessor entry, different commit | near-duplicate warning |
| C10 | boundary | similarity 0.89, or identical text and same commit, or text < 20 chars | no warning |
| C11 | normal | session changed files, no progress, Stop with `stop_hook_active` false | block once with write-progress reason |
| C12 | edge | same as C11 with `stop_hook_active` true | no block |
| C13 | normal | read-only session (no changes) Stop | no block |
| C14 | normal | `show` with no arg, P1 owned by other session | prints P1 Next Session + report, no Record text |
| C15 | normal | `show` with no arg, current session already wrote P2 (`before` P1) | prints P1 from logs |
| C16 | normal | `show agent-docs/progress-logs/P0` | prints P0 |
| C17 | error | `show` with nothing to continue | exit 1 "no progress to continue" |
| C18 | normal | merge adds a progress file | post-merge moves it to logs and prints path |
| C19 | error | two files in `progress/` at commit | verify_rules fails |
| C20 | normal | update with handoff records, answer yes | all moved to todos, index blocks merged, update succeeds |
| C21 | normal | update with handoff records, answer no / EOF / no TTY | handoff untouched, notice printed, update succeeds |
| C22 | edge | Next Session with only `- none: finished` | Stop does not block; show warns nothing |
| C23 | edge | malformed progress (no frontmatter, missing sections, garbage metadata) | findings reported, no crash; no rotation when the frontmatter is missing or unparsable (rotation follows FR5 when the frontmatter is valid) |
| C24 | normal | prompt with an `sk-ant-…` key, a `ghp_…` token, and `password=hunter2` | each value replaced by `[masked:token]`; surrounding text kept |
| C25 | normal | prompt with a fenced 12-line block and a 5-line timestamped log run | `[masked:log 12 lines]` and `[masked:log 5 lines]` (fence lines counted in N); other text kept |
| C26 | boundary | 2 consecutive timestamped lines; 3 consecutive timestamped lines | 2 kept; 3 masked |
| C27 | normal | `alice@acme.io`, `10.0.0.5`, `build01.corp`, `fe80::1` | `[masked:email]`, `[masked:ip]`, `[masked:host]`, `[masked:ip]` |
| C28 | edge | `dev@example.com`, `127.0.0.1`, `::1`, `task-runner-abcdefghijklmnopqrstuv`, version `1.2.3`, `300.1.1.1` | unchanged |
| C29 | normal | three prompts in a session, then a progress write, then a fourth prompt and Stop | `### User Requests` lists 1–3 after the write and 1–4 after Stop; other sections byte-identical |
| C30 | error | progress in `progress-logs/` containing `AKIA` key at line 40 | verify_rules fails naming `:40` and `token` |
| C31 | edge | already-masked text | `mask` returns it unchanged; verify_rules reports nothing |

# Quality Applicability
| ISO/IEC 25010:2023 characteristic | applicable | rationale |
| --- | --- | --- |
| Functional suitability | yes | core behavior |
| Performance efficiency | yes | hooks run on every prompt, every progress write, and every Stop |
| Compatibility | yes | existing hooks, specs, and installed projects must keep working |
| Interaction capability | yes | feedback text must tell the agent what to do |
| Reliability | yes | hooks must not crash or loop |
| Security | yes | user prompts are recorded into committed files; keys, emails, IPs, internal hostnames, and pasted logs must not reach the repository |
| Maintainability | yes | shared logic in one module |
| Flexibility | no | single target platform (Claude Code); Codex best-effort per project definition |
| Safety | yes | rotation and installer move user files; must never delete them |

# Quality Requirements
| id | characteristic / subcharacteristic | target and context | measure method / inputs / unit | threshold and direction | evidence: automated, review, mutation | source |
| --- | --- | --- | --- | --- | --- | --- |
| Q1 | Performance / time behaviour | progress PostToolUse hook on a progress with 40 entries and a predecessor with 40 entries, 1,000-commit repo fixture | wall time, seconds | ≤ 2.0 s | automated (timed test) | design |
| Q2 | Compatibility / co-existence | pre-existing tests | pre-existing test files pass; only listed test files change | 100% | automated Test command; review `git diff --stat base_commit -- tests` | project |
| Q3 | Interaction / self-descriptiveness | every hook feedback and CLI error | each message contains the repo-relative path (or file name) of the file it concerns — or, when that file does not exist yet (FR10 missing progress, `show` with nothing to continue), the `agent-docs/progress` directory — and at least one next-action verb from {write, merge, add, rename, ask, re-check, replace, end, remove, quote, move, update, run, fix} | 100% of messages in Errors and FR5–FR10, FR24 | automated (string assertions) | design |
| Q4 | Reliability / fault tolerance | malformed progress, missing git, missing or unreadable state file, payload without prompt | hook exit status and no traceback | exit 0 or documented feedback, 0 tracebacks | automated (C23, Errors rows) | design |
| Q5 | Maintainability / modularity | parsing, freshness, similarity, rotation, masking | defined once in `harness/lib/progress.py`, imported by hook, CLI, verify_rules | 0 duplicate implementations | review | design |
| Q6 | Safety / fail safe | rotation, post-merge, installer move | files deleted | 0 deletions of records; every moved file exists at its destination with identical bytes; an index.md/stale.md merged into an existing todos index keeps every block | automated | user |
| Q7 | Security / confidentiality | `progress.mask` over a fixture set with ≥ 2 samples per FR23 pattern (each token prefix, PEM, Bearer, each assignment key, email, IPv4, IPv6, each default host suffix, fence, traceback, timestamp run, level run) | samples whose secret substring survives in output / samples | 0 survivors (100% masked) | automated | user |
| Q8 | Security / confidentiality | `verify_rules.py` over progress files containing each Q7 category (2)–(5) sample, and over the C28 exception set | detected samples / samples; false positives on exceptions | 100% detected; 0 false positives | automated | user |
| Q9 | Performance / time behaviour | `progress.mask` on a 100 KB prompt mixing all categories | wall time, seconds, in-process | ≤ 0.2 s | automated (timed test) | design |

# Verification Obligations
| id | parent requirement/Case ids | variant and target surface | test layer and selection policy | ISO/IEC/IEEE 29119-4 technique | coverage items | coverage target | observation and expected result | evidence procedure |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| O1 | FR1, FR2, FR5, FR6, FR7, C1–C4, Q6 | rotation via hook payload | unit, temp git repo | state transition testing | transitions: empty→one, one→rotated, same-session refusal, parallel refusal, destination-exists refusal | 100% | file locations, `before`, feedback text, bytes preserved | tests/test_progress.py |
| O2 | FR4, FR8(a)(b), C5–C8 | freshness | unit, temp git repo | equivalence partitioning + boundary value | commit=HEAD; later commit touching listed file; touching other file; touching only the progress file; unresolved sha; non-ancestor; `files: none` | 100% | fresh/stale labels | tests/test_progress.py |
| O3 | FR8(c), C9, C10 | similarity | unit | boundary value analysis | 0.89 / 0.90 / 1.0 similarity; same vs different commit; 19 / 20 chars; `before` vs `previous` predecessor | 100% | warning presence | tests/test_progress.py |
| O4 | FR9, FR10, FR15, C11–C13, C22 | Stop/SessionStart/PreCompact | unit with payload fixtures | decision table | changed {yes,no} × progress {none, own empty, own filled, other session} × stop_hook_active {true,false} | 100% | block decision and reason | tests/test_progress.py |
| O5 | Errors, C23, Q4 | malformed inputs | unit | error guessing | each Errors row | none — experience-based | no traceback, documented message | tests/test_progress.py |
| O6 | FR12, FR13, C14–C17 | `progress.py show` | CLI subprocess | equivalence partitioning | each resolution branch; session from `--session` vs `CLAUDE_CODE_SESSION_ID` | 100% | stdout contains Next Session, never `## Record`; exit codes | tests/test_progress.py |
| O7 | FR14, C18 | post-merge | integration, temp repo with two branches | use case testing | merge adding progress; merge not adding; executable local post-merge hook present | 100% | moved paths; local hook still runs | tests/test_progress.py |
| O8 | FR16, FR20, C19 | verify_rules | unit | equivalence partitioning | two progress files; bad headings; bad metadata; todos legacy handoff file; todos file with extra sections; handoff dir ignored | 100% | pass/fail and messages | tests/test_doc_records.py |
| O9 | FR18, FR19, C20, C21, Q6 | installer and spec_lifecycle | integration | decision table | handoff {absent, present} × answer {yes, no, EOF/no TTY}; update from pre-0.29.0 with ADR records (0.29.0 handoff included in the move); spec with/without `handoff`; `session` warning text | 100% | files moved or untouched, exit 0, spec validates, warning mentions progress | tests/test_installer.py, tests/test_workflow_markers.py |
| O10 | FR18 telemetry | telemetry hook | unit | equivalence partitioning | progress write; progress-logs write; non-progress write | 100% | `progress_write` emitted only for `progress/*.md` | tests/test_telemetry.py |
| O11 | Q1, Q9 | timing | unit | — | 40×40 entries, 1,000 commits; 100 KB prompt | 1 run each | ≤ 2.0 s; ≤ 0.2 s | tests/test_progress.py |
| O12 | FR11, FR17, FR18 text | skills and instructions | review | — | R1, R2 | 100% | recorded in ledger | review |
| O13 | FR23, C24–C28, C31, Q7 | `progress.mask` | unit | equivalence partitioning + boundary value analysis | each FR23 pattern and each exception as a partition; log-run 2/3 lines; IPv4 octet 255/256; `sk-` 19/20 chars; boundary prefix inside a word; idempotence | 100% | masked output equals expected string | tests/test_progress.py |
| O14 | FR21, FR22, C29, Errors (state file rows) | UserPromptSubmit + sync | unit with payload fixtures, temp repo | state transition testing | no state→first prompt; prompt→progress write sync; prompt after write→Stop sync; subsection missing→appended; unwritable state→notice | 100% | state file `prompts`, subsection text, other bytes unchanged, no raw prompt on disk | tests/test_progress.py |
| O15 | FR24, C30, C31, Q8 | verify_rules secret check | unit, temp repo | decision table | location {progress, progress-logs} × category {token, email, ip, host, none} ; exception set | 100% | exit code, `<path>:<line>` and category in message | tests/test_doc_records.py |
| O16 | Q3, FR5–FR10, FR24, Errors | every hook feedback, Stop reason, CLI error, and verify_rules secret message | unit with payload fixtures / CLI subprocess | equivalence partitioning | one partition per message: FR5 move report; FR6 refusal; FR7 refusal; FR8 stale and near-duplicate findings; FR10 missing-progress and empty-Next-Session reasons; FR24 finding; each Errors row that emits a message (invalid frontmatter, missing metadata, git unavailable, destination exists, show outside progress dirs, prompt not recorded) | 100% | message contains the concerned file's repo-relative path or name and a next-action verb from Q3 | tests/test_progress.py, tests/test_doc_records.py |
| O17 | Q2 | pre-existing tests | review | — | `git diff --stat <base_commit> -- tests` | 100% | only Tests-path files changed; Test command exit 0 | review, recorded in ledger |
| O18 | Q5 | parsing, freshness, similarity, rotation, masking | review | — | hook, CLI, verify_rules import these from `harness/lib/progress.py`; no second Levenshtein, mask, or parser | 100% | 0 duplicate implementations | review, recorded in ledger |

# Assumptions and Defaults
| id | decision | evidence and uncertainty | brief v<n> — approved / vetoed → <answer> / user answer |
| --- | --- | --- | --- |
| A1 | `before` links order, `previous` links explicit continuation | user: A and B are not necessarily related | user answer |
| A2 | Only sessions that changed repository files must write progress | user accepted | user answer |
| A3 | `continue-on` may take a progress-logs path to skip intervening sessions, linked through `previous` | user accepted | user answer |
| A4 | A merge ends the merged branch's task; post-merge sends added progress to logs; parallel sessions on one checkout are refused like active specs | user answer | user answer |
| A5 | Freshness = no commit after the entry's commit touches its files (not strict HEAD equality) | user accepted | user answer |
| A6 | Keep both stamps: file-level frontmatter `commit:` (HEAD at last write) and entry-level `commit` | user: keep both | user answer |
| A7 | Similarity = normalized Levenshtein on whitespace-normalized entry text, threshold 0.90, minimum 20 chars, compared against `before` and `previous` | user specified Levenshtein; threshold and length chosen by main | brief v1 — approved |
| A8 | Handoff records move to `agent-docs/todos/` after an installer prompt; update never fails on them; test-audit writes todos | user answer | user answer |
| A9 | Record user prompts automatically, masked | user: record originals with keys, logs, etc. masked | user answer |
| A10 | Stop enforcement blocks at most once per stop sequence (`stop_hook_active`) | prevents hook loops | brief v1 — approved |
| A11 | PreCompact reminder (FR15) included | research: compaction drops about 37% of scope/process constraints | brief v1 — approved |
| A12 | Skill name `continue-on` | user answer | user answer |
| A13 | Todos require `#` title and `## Next Step`; other sections allowed | user: agree, keep extensible | user answer |
| A14 | Session id env var is `CLAUDE_CODE_SESSION_ID`, `--session` fallback | observed 2026-10-28: env value equals the transcript file id; not verified across Claude Code versions | brief v1 — approved |
| A15 | 0.33.0 handoff move runs after the 0.29.0 migration; 0.29.0 migration code unchanged | `installer/harness.py` `write_try_n_fail_handoff` writes to `handoff/` | brief v1 — approved |
| A16 | post-merge moves progress before `exec` delegation | `harness/git/post-merge` uses `exec` | brief v1 — approved |
| A17 | implementer runs on opus; test-implementer and test-verifier on the installed default (sonnet) | cross-module change over 18 files | brief v1 — approved |
| A18 | Telemetry end status token `handoff` kept for nonterminal stops | `analytics/compliance.py` accepts `handoff` status; analytics out of scope | brief v2 — listed after approval, veto open |
| A19 | Mask exceptions (example domains, loopback IPs) and host suffixes via `mask_host_suffixes` config | reduces false positives that would block commits | brief v2 — listed after approval, veto open |
| A20 | Prompts kept in uncommitted state file, synced into `## Record` → `### User Requests`; continue-on does not read them | user: recommended placement | user answer |
| A21 | Unmasked secrets in progress block the commit | user answer | user answer |
| A22 | Log masking replaces whole blocks, including all fenced code blocks; emails, IPs, internal hostnames masked; free-text customer data not masked | user answer; fenced code in prompts that is not a log is also masked (accepted cost) | user answer |

# Traceability
| requirement id | Case ids | obligation ids | evidence procedure |
| --- | --- | --- | --- |
| FR1, FR2, FR5–FR7 | C1–C4 | O1 | tests/test_progress.py |
| FR3, FR4, FR8 | C5–C10, C23 | O2, O3, O5 | tests/test_progress.py |
| FR9, FR10, FR15 | C11–C13, C22 | O4 | tests/test_progress.py |
| FR11 | — | O12 | review R2 |
| FR12, FR13 | C14–C17 | O6 | tests/test_progress.py |
| FR14 | C18 | O7 | tests/test_progress.py |
| FR16, FR20 | C19 | O8 | tests/test_doc_records.py |
| FR17 | — | O12 | review R1 |
| FR18, FR19 | C20, C21 | O9, O10, O12 | tests/test_installer.py, tests/test_workflow_markers.py, tests/test_telemetry.py, review R1 |
| FR21, FR22 | C29 | O14 | tests/test_progress.py |
| FR23 | C24–C28, C31 | O13, O11 | tests/test_progress.py |
| FR24 | C30, C31 | O15 | tests/test_doc_records.py |
| Q3 | — | O16 | tests/test_progress.py, tests/test_doc_records.py |
| Q2, Q5 | — | O17, O18 | review |

# Workflow Control
| item | value |
| --- | --- |
| correction batches used | 3 |
| verifier invocations | 2 |
| open finding ids | none |

Audit state (one entry per obligation; retain prior decisions in the execution ledger):
| obligation id | spec version | evidence references and revision | accepted / open / invalidated / pending | rationale and mutation outcome | dependencies and reopening evidence |
| --- | --- | --- | --- | --- | --- |
| O1–O8, O10–O12, O14, O15 | 4 | verifier round 1 (spec v3), tests after correction batch 1 | accepted | verifier 1 accepted; advisories A1–A6 recorded in ledger | reopen if hook messages, rotation, freshness, or mask code changes in batch 2 |
| O9, O13, O16 | 5 | batch 2 tests and I1 message rewording; verifier round 2 | accepted | verifier 2 pass; E1, E2, S1 closed; M11, M12 killed | reopen if installer move, traceback masking, or message wording changes |
| O17 | 5 | `git diff --stat b16e923 -- tests` after batch 2 | accepted | only Tests-path files changed; Test command exit 0 | — |
| O18 | 5 | main review: `grep -rn "def levenshtein\|def mask\|def similarity\|def parse_frontmatter\|def unmasked\|def rotate\|re.compile.*AKIA" harness installer` hits only harness/lib/progress.py; progress_hook.py, bin/progress.py, verify_rules.py `import progress` and call parse/mask/unmasked/format_findings/rotate/check_findings/entry_report | accepted | 0 duplicate implementations | — |

Execution ledger (append attempts; preserve failed approaches):
| attempt | finding / failure signature | cause hypothesis | changed approach / new evidence | result / disposition |
| --- | --- | --- | --- | --- |
| 1 | Test command (plain python3): 16 failures + 2 import errors (`pytest`, `hypothesis` missing) | test defects: pre-existing tests hard-code VERSION 0.32.0, migration y-line counts, and the `.harness/bin` file list; tests/test_comment_gate.py and tests/test_session_metrics.py were outside Tests paths; deps not installed in system python | Test command switched to `uv run --with pytest --with hypothesis`; with it test_isolation_telemetry passes and test_session_metrics fails only on VERSION; finding T1 sent to test-implementer | closed by attempt 2 |
| 2 | after test correction batch 1: Test command exit 0, 866 tests | — | — | T1 closed; review R1 and R2 passed (only historical-record notes, migration notice, and the kept `handoff` telemetry token mention handoff; continue-on has `disable-model-invocation: true` and reads only `show` output and `### Related`) |
| 3 | verifier round 1: retry; S1 Q2/Q3/Q5 unmapped; E1 todos-index merge into existing blocks untested; E2 single traceback sample | S1 spec gap; E1, E2 test evidence gaps | spec v4 adds O16–O18; batch 2 to test-implementer for E1, E2, O16; advisories A1 touch-and-revert freshness, A2 PreCompact other-session row, A3 C23 hook silence, A4 6/7-char commit in verify_rules, A5 blank prompt lines, A6 no session id / dangling before / `::x` IPv6 not taken (undeclared combinations) | open |
| 4 | hand mutations on batch-1 tests (targeted modules test_progress / test_doc_records via the Test command's runner) | strongest defect classes: verifier proposals 2–9, 10, 12 plus rotation and storage | M1 similarity ≥→> (killed by test_o3_boundaries_of_the_similarity_threshold); M2 same-commit guard dropped (test_o3_same_commit_never_warns_and_different_commit_does); M3 live foreign marker ignored (test_o1_c4_live_foreign_marker_refuses_rotation); M4 stop_hook_active ignored (test_o4_stop_decision_table, 4 rows); M5 prompt stored unmasked (test_o14_raw_secret_appears_in_no_file_of_the_repository + 2); M6 token prefix boundary dropped (test_o13_prefix_inside_a_word_is_not_a_token); M7 log run 3→2 (test_o13_c26_two_lines_kept_three_masked); M8 loopback exception removed (test_o13_loopback_boundary_126_127_128 + 4); M9 post-merge A→AM (test_o7_merge_that_only_modifies_an_existing_progress_does_not_move_it: FileNotFoundError because the modified progress was moved — the injected violation); M10 secret check skips progress-logs (test_o15_* progress-logs rows, 13) | 10/10 detected; all restored (`seed.py status`: none) |
| 5 | Test command after batch 2: 875 tests, 2 failures in O16: FR5 move report ("Keep … use `/continue-on`") and `show` outside-progress-dir error ("pass a file …") have no Q3 verb | implementation defect I1 (messages written before Q3 was made measurable); test-implementer challenge: messages about a not-yet-existing progress name its directory | spec v5 Q3 accepts the directory for those two; I1 sent to implementer; S1, E1, E2 closed by batch 2 evidence (O9 cases a/b, three traceback samples, O16 table) pending verifier round 2 | closed by attempt 6 |
| 6 | implementer fixed I1: 11 messages reworded (rotation report, findings header, no-session-id notice, invalid frontmatter, missing title/section/subsection, show/check path errors), 46/46 messages checked; Test command exit 0, 875 tests; confirming mutations M11 todos index overwritten instead of merged (killed by test_o9_q6_existing_todos_blocks_survive_the_merge_and_all_records_arrive_intact) and M12 traceback exception line left out of block (killed by 4 traceback tests); restored, `seed.py status`: none; O17 re-checked: `git diff --stat b16e923 -- tests` lists only Tests paths | — | — | I1 closed; verifier round 2 dispatched |
| 7 | verifier round 2: pass, 0 blocking; advisories: O18 grep patterns not recorded (now recorded in Audit state), O16 stale-message scenario covers FR8(b) only (same message path as FR8(a)) | — | — | complete |

# Version Log
## v1
- Draft written from the user's design decisions in session 2026-10-28 and research notes (Handoff Debt 2606.02875, Compact-Bench 2610.31710, Benchmarks Are Surprisingly Compaction-Friendly 2610.31778, Codified Context 2602.20478, SWE Context Bench 2602.08316, planning-with-files #106). The understanding round and brief were deferred at the user's request; the user will review and amend this draft in a later session before approval.
## v2
- Briefs v1 and v2 approved 2026-10-28. User answers: keep both commit stamps (A6); record user prompts with masking of keys, logs, emails, IPs, internal hostnames, whole-block log replacement, free-text customer data unmasked (A9, A22); store in Record and sync from an uncommitted state file (A20); block commits on unmasked secrets (A21); todos extensible (A13).
- Added I6, FR21–FR24, C24–C31, Q7–Q9, O13–O15; Security now applicable.
- Fixed FR12 env var name (`CLAUDE_SESSION_ID` does not exist; `CLAUDE_CODE_SESSION_ID` observed). Added `spec_lifecycle.py session` warning change and `rearrange-docs` to FR18; migration ordering to FR19; post-merge ordering to FR14; README.md and config.default.json to Implementation.
- Status set to `active`.
## v3
- Contract-only: added `harness/hooks/doc_commit.py` to Implementation (required by the Signatures hook-write rule); added tests/test_comment_gate.py and tests/test_session_metrics.py to Tests (they hard-code version and migration counts); Test command runs through `uv` with pytest and hypothesis (repository tests import them; system python lacks them); clarified FR19 "no TTY", C8 labels, C23 rotation, and Q6 for index merges into an existing todos index (implementer and test-implementer challenges).
## v4
- Contract-only, from verifier round 1 finding S1: Q3 made measurable (path/name + next-action verb list); added O16 (Q3 messages), O17 (Q2 review), O18 (Q5 review) and their traceability.
## v5
- Contract-only, from test-implementer challenge in batch 2: Q3 accepts the `agent-docs/progress` directory for messages about a progress that does not exist yet.

# Retrospective
## 2026-10-29
| observation | evidence | how to re-check |
| --- | --- | --- |
| System `python3` lacks pytest and hypothesis; plain `python3 -m unittest discover -s tests` reports import errors for test_session_metrics and test_isolation_telemetry | first Test command run of this spec: `ModuleNotFoundError: No module named 'pytest'` / `'hypothesis'` | `python3 -c "import pytest, hypothesis"` |
| In Bash, `CLAUDE_CODE_SESSION_ID` equals the transcript file id; `CLAUDE_SESSION_ID` is not set | 2026-10-28: env value `1f08ec89-…` matched `~/.claude/projects/<project>/1f08ec89-….jsonl` | `echo $CLAUDE_CODE_SESSION_ID` and compare with the newest transcript file name |
| Pre-existing tests hard-code VERSION and per-migration `y` answer counts, so a version bump fails about 16 tests across 5 files | Test command run 1 failure list (ledger attempt 1) | `grep -rn '"0\.33\.0"\|"y\\n' tests/` |
| This macOS shell has no `timeout`; zsh treats a word starting with `=` as a command lookup (`echo ======` fails) | command output in this session | `which timeout`; `zsh -c 'echo ===='` |


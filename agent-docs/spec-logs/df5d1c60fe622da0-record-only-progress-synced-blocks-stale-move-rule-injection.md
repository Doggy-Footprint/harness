---
version: 2
run_id: df5d1c60fe622da0
status: complete
base_commit: 611e1f635fe547798a5a24512249cb2f0743f156
max_verifier_invocations: 2
commit: 611e1f635fe547798a5a24512249cb2f0743f156
---

# User Intent
| id | stakeholder | intention | observable goal |
| --- | --- | --- | --- |
| I1 | agent in a session that only writes records | Not compose a progress for a session that changed only `agent-docs/` records | the hook writes a progress with `### Changes` and `### User Requests` that passes every check and Stop without agent edits |
| I2 | agent maintaining a synced comment | Have `code_hash` break only when the tagged code changes, and refresh it with one command | an edit outside every tagged block leaves the check passing; `synced-refresh` restores a passing state after an edit inside a block |
| I3 | agent marking a record stale | Move a record to `stale/` with one command | after the command the index check passes and the entry is in `stale.md` verbatim |
| I4 | agent in any session | Get a rule's text when it starts writing in that rule's directory, without a separate read | the first Write/Edit/MultiEdit of a session into a rule's directory returns the rule file's text as additional context |
| I5 | harness user | Stop a progress or other record that quotes a synced tag from counting as a code location | a tag inside `agent-docs/` is not counted |
| I7 | agent starting a session after a PR | Continue the previous session's work with `/continue-on` and no argument after that session retired its progress | `show` prints the retired progress instead of exiting 1 (todo 76ec93b79f7319f3) |
| I6 | harness user | Know whether 0.43.0 pays off | before/after evaluation against 0.42.0 shows no regression in progress passing and fewer turns or tokens in record-only tasks |

# Scope
In scope: changed-path classification in the progress hook (record vs code); record-only progress kind, its creation, hook-owned `### Changes`, upgrade to a full progress; `progress.py show` default pick skipping record-only progress; synced block hashing with `synced end:` markers, scan excluding `docs_root`; `harness/bin/records.py` with `stale` and `synced-refresh`; PreToolUse rule-text injection; Rule Files table shortened; rule text in `harness/instructions/*.md`; 0.43.0 version and migration (synced recompute where possible, list of ids needing end markers); dogfood update; before/after evaluation R1.
Out of scope: Codex; rewriting existing progress or todo files; inserting end markers into downstream code; Bash-written records for injection (only Write/Edit/MultiEdit trigger it); test-suite speed; PR #32 metadata.

# Paths
Implementation: harness/lib/progress.py, harness/lib/synced.py, harness/hooks/progress_hook.py, harness/hooks/hooks.spec.json, harness/git/sync_progress.py, harness/git/verify_rules.py, harness/bin/progress.py, harness/bin/records.py, harness/instructions/harness-block.md, harness/instructions/progress.md, harness/instructions/synced-comments.md, harness/instructions/index-and-staleness.md, harness/instructions/todos.md, harness/instructions/try-n-fail.md, harness/skills/continue-on/SKILL.md, installer/harness.py, harness/VERSION, README.md
Tests: tests/test_record_only_progress.py, tests/test_synced_blocks.py, tests/test_records_cli.py, tests/test_rule_injection.py, tests/test_hook_owned_progress.py, tests/test_progress.py, tests/test_progress_retire.py, tests/test_lazy_rules.py, tests/test_installer.py, tests/test_comment_gate.py, tests/test_doc_records.py, tests/test_telemetry.py, tests/test_session_metrics.py, tests/test_workflow_markers.py, tests/test_update_commit.py, tests/data/
Test command: /Users/hwansu/tools/harness/.venv/bin/python -m unittest discover -s tests
Review evidence: R1 — before/after evaluation run by main after the suite passes, same procedure as R1 of `agent-docs/spec-logs/fba8551e5565cc4d-hook-owned-progress-mechanics.md` v5: target simonw/mcp-explorer at 56910d7c6c9f7e143dadd67bf047d7650a79ffdd; arms before = installer at base_commit (0.42.0), after = working-tree installer (0.43.0); tasks T1 code change, T2 todo, T3 try-n-fail, T4 mark the --sort todo stale (setup applies the --sort implementation), T5 synced comment between two functions; 5 repetitions × 2 arms = 50 sessions, `claude -p --model haiku --effort medium` with the same flags and allowed tools as that R1; repositories under `/private/tmp/harness-eval/`; scripts in the session scratchpad. T5 prompts are identical in both arms; each arm follows its own installed rule text. Metrics per arm: E1 sessions with ≥1 Stop block; E2 sessions with ≥2 committed own progress files; E3 sessions whose own progress passes its arm's `progress.py check` and is in the first work commit; E4 mean first-request input tokens at the same tool count; E5 mean turns (overall and T2–T4); E6 pre-commit blocks; E7 mean commits; E8 cost; E9 task rule items passing (T2–T5; T5 by its arm's synced check); E10 mean input tokens (overall and T2–T4). Pass criteria Q7–Q9; others reported. Rule-file reads count Read and Bash commands naming the file.
Fuzzing: none — the new parsers (block scan, index block split) take repository text covered by equivalence classes and boundary cases.
Mutation tool: none

# Signatures
harness/lib/synced.py (new; `verify_rules.py` and `records.py` both use it):
- `TAG_RE` (same pattern as today's `SYNCED_TAG_RE`), `END_RE = re.compile(r"synced end:\s*([0-9a-f]{12})")`
- `Block` with `path: str` (repo-relative posix), `tag_line: int` (1-based), `end_line: int | None`, `version: int`, `count: int`, `lines: list[str]` (hashed lines)
- `scan(repo_root: Path, paths: list[Path], docs_root: Path, exclude_dirs) -> tuple[dict[str, list[Block]], list[str]]` — blocks per id and structural errors (E-S1, E-S2)
- `block_hash(blocks: list[Block]) -> str`
harness/lib/progress.py:
- `RECORD_ONLY = "record-only"`
- `is_record_only(parsed) -> bool` (frontmatter `kind` equals `record-only`)
- `record_only_text(session_id: str, branch: str, changes: list[str]) -> str`
- `sync_changes(text: str, changes: list[str]) -> str` (record-only only; other kinds returned unchanged)
- `upgrade_record_only(text: str) -> str`
- `changed_paths_file(repo_root, session_id) -> Path` = `change_dir(...) / "changed-paths"`; `code_marker(repo_root, session_id) -> Path` = `change_dir(...) / "code"`
harness/bin/records.py: `stale <path>`, `synced-refresh <id> [--reason TEXT]`; exit 0 success, 1 refusal (message on stderr, no file changed).
progress_hook.py PreToolUse: Write/Edit/MultiEdit may print hook JSON to stdout (`hookSpecificOutput.additionalContext`), exit 0.

# Functional Requirements
| id | requirement | priority | source |
| --- | --- | --- | --- |
| F1 | Path classification: every modification the hook records (as today, same exemptions: `.harness/`, ignored files, `harness.py update` runs) also records its changed repo-relative paths in `changed-paths` (one per line, unique, sorted). A path under `docs_root` excluding the progress and progress-logs dirs is a record path; a path under the progress dirs is neither; any other path is a code path and creates the `code` marker. Edit tools: the edited path. Bash: paths whose `git status --porcelain` line or stat signature differs between the PreToolUse snapshot and PostToolUse, plus `git diff --name-only <old HEAD> <new HEAD>` when HEAD moved; when the paths cannot be determined (snapshot from 0.42.0 format, git failure), the change counts as code | must | I1 |
| F2 | Record-only creation: where 0.42.0 creates the skeleton (PostToolUse, no progress target, modified, no own progress, `skeleton` marker absent), when the `code` marker is absent the hook writes `record_only_text` instead of the skeleton, with `### Changes` listing the record paths; rotation, User Requests sync, marker, and refusal fallback S1 as for the skeleton; message N3; exit 2 | must | I1 |
| F3 | Changes sync: for an own progress with `kind: record-only`, PostToolUse after any recorded modification and pre-commit `sync_progress.py` rewrite `### Changes` to one `- <path>` bullet per record path in `changed-paths`, sorted; pre-commit stages it | must | I1 |
| F4 | Upgrade: when the `code` marker exists and the own progress is `kind: record-only` (in `progress/`), PostToolUse rewrites it with `upgrade_record_only`: the `kind:` line removed, `# <title>` kept, the skeleton's `## Next Session` block inserted before `## Record`, `### Changes` keeps its bullets and gains `- [harness-requires]`, `### Commands`, `### Failed Attempts` (header only), `### Sources` from the skeleton inserted between `### Changes` and `### User Requests`; message N4; exit 2; once (the progress is no longer record-only) | must | I1 |
| F5 | Checks for record-only: `format_findings` requires `# <title>`, `## Record`, `### Changes` with at least one bullet, and `### User Requests`, and nothing else; Stop's `## Next Session` entry check and placeholder check pass for it; the commit gate treats it as any own progress; a record-only progress whose session has the `code` marker is a format finding `record-only progress in a session that changed code; run any Edit to let the hook upgrade it, or write the full structure` | must | I1 |
| F6 | `progress.py show` without argument: a candidate with `kind: record-only` is replaced by the progress its `before:` names, repeatedly, until a non-record-only file or `none`; `none` → existing "no progress to continue" exit 1. With an explicit record-only path: exit 1 `not continuable: <path> is a record-only progress` | must | I1 |
| F14 | `progress.py show` without argument, when the F6 lookup in `progress/` (including the own progress's `before:`) yields nothing: picks from `progress-logs/*.md` the file not owned by the current session and not record-only whose last commit reachable from HEAD touching it (`git log -1 --format=%ct -- <path>`) is newest; ties broken by path, ascending; untracked files ignored; none → existing exit 1. The continue-on skill text states this fallback | must | I7 |
| F7 | Synced blocks: a block starts at a tag line and ends at the first later line in the same file containing `synced end: <same id>`. Hashed lines are the lines strictly between, excluding lines that match `TAG_RE` or `END_RE` and comment-only lines by today's extension table (`.md` and unknown extensions strip nothing). `block_hash`: blocks sorted by (path, tag_line); for each, the hashed lines each followed by `\n`; concatenated; sha256 hex, first 12 characters | must | I2 |
| F8 | Synced check: scans tracked files with today's extensions, excluding paths under `docs_root` and `EXCLUDE_DIRS`; count, version, missing-tracking-file, obsolete, and invalid-frontmatter checks unchanged; hash compares `block_hash` of the id's blocks; structural errors E-S1, E-S2 (E-S2 for every `synced end: <id>` line that does not close an open block of that id in its file, including a second end after a closed block); an id with a structural error skips its hash comparison | must | I2, I5 |
| F9 | `records.py synced-refresh <id> [--reason TEXT]`: refuses (exit 1, no write) when the tracking file is missing, marked obsolete, or any block of the id has a structural error. Otherwise computes count (number of tags) and `block_hash`; if both equal the frontmatter, prints R1 and exits 0 with no write; else sets `version` to version+1, `count`, `code_hash` in the frontmatter, rewrites every tag of the id to the new version and count (spacing normalized to `synced id: <id>, version: <n>, count: <n>`), appends `## v<n> Log` + `- <reason>` (default `Refreshed count and code_hash.`) at the end of the tracking file, prints R2, exit 0 | must | I2 |
| F10 | `records.py stale <path>`: the path must be a file named `<16-hex>-<kebab>.md` directly in a directory that holds `index.md` and lies under `docs_root` outside the exempt dirs. Splits `index.md` on lines matching `^---\s*$`; the block whose `File:` value equals the name is removed together with the separator line after it (or before it when it is the last block); the block's lines are appended to `stale.md`, preceded by a `---` line when `stale.md` has non-whitespace content, ending with `\n`; `stale.md` and `stale/` created when missing; the file moves to `stale/<name>` with `git mv` when tracked, else a rename. Refusals (exit 1, nothing changed): not such a path, no matching index block, more than one matching block, destination exists | must | I3 |
| F11 | Rule injection: PreToolUse for Write/Edit/MultiEdit whose target resolves inside a rule directory prints `{"hookSpecificOutput": {"hookEventName": "PreToolUse", "additionalContext": <text>}}` once per session per rule file (marker `rule-<file stem>` in the change dir). Directories → rule files: progress and progress-logs → `progress.md`; try-n-fail → `try-n-fail.md` and `index-and-staleness.md`; todos → `todos.md` and `index-and-staleness.md`; synced-comments → `synced-comments.md`; any other directory under `docs_root` holding `index.md` (except specs, spec-logs) → `index-and-staleness.md`. `<text>` is, for each rule file not yet injected in this session in the listed order, `harness: rule text of .harness/instructions/<file> for writing in <dir rel>/:` + `\n\n` + the file content, joined by `\n\n`. No session id, all files already injected, or an unreadable rule file → no output for that file; exit 0 always | must | I4 |
| F12 | Rule text: `harness-block.md` `## Rule Files` per S10; `synced-comments.md` per F7–F9 (end marker, block hash, `synced-refresh`); `index-and-staleness.md` rule 4 names `records.py stale`; `progress.md` describes the record-only kind, Changes sync, and upgrade; continue-on skill notes that record-only progress is skipped | must | I1–I4 |
| F13 | 0.43.0 version; migration registered last with S11 lines; data step: for each non-obsolete tracking file under `synced-comments/` whose id has ≥1 block and no structural error, set `code_hash` to `block_hash` (no version change); for each other non-obsolete id with tags, print M1; `AGENTS.md` unchanged; dogfood update; README rows for the progress hook, the synced check, and `records.py` updated | must | I2 |

Exact strings:
- N3: `harness: this session changed only records, so {label} was created as a record-only progress; the hook keeps its ### Changes and ### User Requests. Commit it with the work.`
- N4: `harness: this session changed code, so {label} was turned into a full progress. Read .harness/instructions/progress.md, replace every [harness-requires] in {label}, and commit it with the work.`
- E-S1: `{path}:{line}: synced id {id} has no later \`synced end: {id}\` line; add it where the tagged block ends`
- E-S2: `{path}:{line}: \`synced end: {id}\` has no synced id {id} tag before it`
- R1: `synced id {id}: count and code_hash unchanged`
- R2: `synced id {id}: version {old} -> {new}, count {count}, code_hash {hash}; updated {n} tag(s)`
- M1 (migration output, one per id): `synced id {id}: add \`synced end: {id}\` after each tagged block in {comma-separated paths}, then run python3 .harness/bin/records.py synced-refresh {id}`
- S11 (migration plan lines, in order): `progress hook: a session that changed only agent-docs records gets a record-only progress kept by the hook`, `synced comments: code_hash covers only the lines between a tag and its \`synced end: <id>\` line; python3 .harness/bin/records.py synced-refresh <id> updates count, code_hash, version, and tags`, `python3 .harness/bin/records.py stale <path> marks a record stale`, `the first Write or Edit in an agent-docs rule directory adds that rule's text to the session`, `data: code_hash is recomputed for synced ids that already have end markers; AGENTS.md is unchanged`
- Record-only template (`{S}`, `{branch}` substituted; `{changes}` one `- <path>` per line; the commit stamp adds `commit:`):

```
---
session: {S}
kind: record-only
before: none
previous: none
branch: {branch}
---

# Record-only session

## Record

### Changes
{changes}

### User Requests
```

- S10 (`## Rule Files` section, replacing the 0.42.0 one):

````
## Rule Files

These rules live in separate files under `.harness/instructions/`. A hook adds a rule's text to the session at its first Write or Edit in the rule's directory; read the file yourself before other work it covers. Hook and pre-commit messages name the file of a rule they find violated.

| file | read before |
| --- | --- |
| `progress.md` | committing in a session that changed the project, continuing earlier work, or opening a PR |
| `index-and-staleness.md` | adding, renaming, or marking stale a record in `agent-docs/` |
| `try-n-fail.md` | proposing a try-n-fail record |
| `todos.md` | writing a todo |
| `synced-comments.md` | keeping one comment identical in several places, or editing code tagged `synced id:` |
````

# Errors
- git unavailable in PostToolUse/PreToolUse — no classification, no record-only file, no injection; existing messages; exit as today.
- changed-paths or code marker write fails (OSError) — exit 0, no traceback; the session stays marked modified; the next change retries.
- path determination fails for a Bash change — treated as code (F1); a later record-only creation does not happen.
- record-only write fails (OSError) — exit 0, no message.
- `upgrade_record_only` input lacks `## Record` — progress left unchanged, F5 finding reported.
- records.py refusals — exit 1, stderr names the reason, no file changed (F9, F10).
- tracking file with invalid frontmatter in migration — skipped, M1 not printed for it, existing check reports it.
- rule file unreadable at injection — that file skipped, no marker written for it.
- any exception in hooks — exit 0 (existing guard).

# Cases
| id | level | input / state | expected result |
| --- | --- | --- | --- |
| C1 | normal | first change: Write of `agent-docs/todos/<id>-x.md` | record-only progress with that path in Changes; N3; exit 2; `progress.py check` passes |
| C2 | normal | then Edit of `agent-docs/todos/index.md` | Changes lists both paths sorted; silent unless findings |
| C3 | normal | record-only exists; Edit of `src/a.py` | upgraded per F4; N4; exit 2 |
| C4 | normal | first change is a code Edit | 0.42.0 skeleton and N2 unchanged |
| C5 | boundary | Bash call changing only records; Bash call changing records and code; Bash commit (HEAD moved) of record files | record; code; record |
| C6 | edge | Bash snapshot in 0.42.0 format (hash only) | counted as code |
| C7 | normal | Stop with untouched record-only progress | exit 0 when committed state allows (no placeholder or entry block) |
| C8 | normal | pre-commit with record-only progress and new record paths since last write | Changes synced and staged; gate passes |
| C9 | normal | `show` when `progress/` holds a record-only progress whose `before` is a full progress | that full progress shown |
| C10 | error | `show <record-only path>` | exit 1, not continuable message |
| C11 | normal | two files tagged and ended; edit outside blocks | check passes |
| C12 | normal | edit inside a block | hash mismatch error; `synced-refresh` → R2, version+1, tags updated, check passes |
| C13 | boundary | refresh with nothing changed | R1, no write |
| C14 | error | tag without end; end without tag | E-S1; E-S2; refresh exit 1 |
| C15 | edge | progress/todo quoting a tag | not counted |
| C16 | edge | two blocks of one id in one file; nested different ids | both counted; each id's block ends at its own end marker |
| C17 | normal | `records.py stale` on a middle, first, and last index entry | entry removed with one separator; appended verbatim; file in `stale/`; index check passes |
| C18 | error | stale: no entry; duplicate entries; destination exists; path in `stale/`; path outside managed dir | exit 1, nothing changed |
| C19 | normal | first Write into `agent-docs/todos/` in a session | JSON with todos.md then index-and-staleness.md text |
| C20 | boundary | second Write there; later first Write into `agent-docs/try-n-fail/` | none; only try-n-fail.md text |
| C21 | edge | Write outside rule dirs; Write into `agent-docs/specs/`; no session id | no output |
| C23 | normal | new session, `progress/` empty, previous session retired its progress and committed it | `show` prints that retired progress |
| C22 | normal | update from 0.42.0 with one tracking file with ended blocks and one without | first recomputed, M1 for the second, S11 order, AGENTS.md identical, doctor 0 |

# Quality Applicability
| ISO/IEC 25010:2023 characteristic | applicable | rationale |
| --- | --- | --- |
| Functional suitability | yes | rules and commands must produce correct records |
| Performance efficiency | yes | path classification adds git calls per Bash call; R1 turns and tokens |
| Compatibility | yes | 0.42.0 progress, snapshots, and tracking files keep working |
| Interaction capability | yes | messages and injected text lead to one fix |
| Reliability | yes | hooks never crash or block on failure |
| Security | no | no new trust boundary; claiming and masking unchanged |
| Maintainability | yes | one block-hash definition shared by check and command |
| Flexibility | yes | configured `docs_root` must drive classification, scan exclusion, and injection |
| Safety | no | no physical or user-harm surface |

# Quality Requirements
| id | characteristic / subcharacteristic | target and context | measure method / inputs / unit | threshold and direction | evidence: automated, review, mutation | source |
| --- | --- | --- | --- | --- | --- | --- |
| Q1 | Compatibility / co-existence | 0.42.0 full progress and skeleton flow | findings and messages for C4 and existing progress tests | unchanged | automated V1, V14 | Scope |
| Q2 | Reliability / fault tolerance | OSError on markers/progress, git failure, unreadable rule file | exit codes; `Traceback` count | per Errors; 0 tracebacks | automated V12 | Errors |
| Q3 | Performance efficiency / time behaviour | PostToolUse for a Bash call in a repo with 300 changed paths | wall time, s | ≤ 1.5 | automated V13 | F1 |
| Q4 | Maintainability / modifiability | hash definition | `records.py` and `verify_rules.py` produce the same hash for the same fixture | equal | automated V6 | F7 |
| Q5 | Flexibility / adaptability | `docs_root` configured as `docs/agent` | classification, scan exclusion, injection use it | all hold | automated V15 | F1, F8, F11 |
| Q6 | Interaction capability / user error protection | refusals | files changed on refusal | 0 | automated V8, V9 | F9, F10 |
| Q7 | Functional suitability / functional correctness | R1 E3 | sessions passing, after arm | ≥ before − 1 | review R1 | I6 |
| Q8 | Performance efficiency / resource utilization | R1 E5, E10 for T2–T4 | mean turns; mean input tokens | after ≤ before on at least one, neither > before × 1.1 | review R1 | I1, I6 |
| Q9 | Interaction capability / user error protection | R1 E1 | Stop-blocked sessions, after arm | ≤ 2 of 25 | review R1 | I6 |

# Verification Obligations
| id | parent requirement/Case ids | variant and target surface | test layer and selection policy | ISO/IEC/IEEE 29119-4 technique | coverage items | coverage target | observation and expected result | evidence procedure |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| V1 | F1, C4–C6, Q1 | progress_hook subprocess in temp repos | integration | equivalence partitioning | Edit record path; Edit code path; Edit progress path; Bash records only; Bash code; Bash mixed; Bash commit of records; 0.42.0 snapshot; git failure during Bash classification | 100% | `changed-paths` content, `code` marker presence | Test command |
| V2 | F2, F3, F4, C1–C3 | PostToolUse sequence | integration | state transition | none→record-only (N3); record-only→record-only with new path (Changes synced, silent); record-only→full (N4); full→full (no change); none→skeleton when first change is code; refusal → S1 | 100% | file text exact (template, upgrade), messages exact, exit codes | Test command |
| V3 | F5, C7 | `format_findings`, `progress.py check`, Stop | integration | decision table | record-only complete; missing Changes bullet; missing User Requests; extra headings allowed; record-only with code marker; Stop with record-only | 100% | findings exact; Stop exit 0 | Test command |
| V4 | F3, F5, C8 | pre-commit `sync_progress.py` and gate | integration | scenario | Changes resync and staging; gate passes with staged record-only | 100% | file staged; commit exit 0 | Test command |
| V5 | F6, C9, C10 | `progress.py show` | integration | equivalence partitioning | record-only candidate with full `before`; chain of two record-only; record-only with `before: none`; explicit record-only path | 100% | chosen path / exit 1 message | Test command |
| V18 | F14, C23 | `progress.py show` in temp repos with commits | integration | equivalence partitioning + boundary value analysis | `progress/` empty with one retired file; two retired files with different commit times; equal commit times (path order); newest is own session; newest is record-only; untracked newer file; no committed candidate | 100% | chosen path / exit 1 | Test command |
| V6 | F7, F8, C11, C15, C16, Q4 | `verify_rules.py` and `synced.block_hash` | integration + unit | equivalence partitioning + boundary value analysis | edit outside block; inside block; comment-only line inside block; tag line version change; tag inside `agent-docs/`; two blocks one file; nested ids; `.md` participant; hash equals independently computed sha256 per F7 | 100% | pass/fail, error text, hash value | Test command |
| V7 | F8, C14 | structural errors | integration | equivalence partitioning | tag without end; end without tag; both in one id | 100% | E-S1/E-S2 exact; no hash error for that id | Test command |
| V8 | F9, C12–C14, Q6 | `records.py synced-refresh` | integration | decision table | missing tracking; obsolete; structural error; unchanged; changed hash; changed count; with/without `--reason` | 100% | exit, R1/R2, file bytes, tags rewritten, Version Log appended; check passes after | Test command |
| V9 | F10, C17, C18, Q6 | `records.py stale` | integration | equivalence partitioning + boundary value analysis | first/middle/last/only entry; stale.md empty/non-empty/missing; tracked/untracked file; each refusal | 100% | index.md, stale.md, file location exact; `verify_rules.py` index check passes; bytes unchanged on refusal | Test command |
| V10 | F11, C19–C21 | PreToolUse subprocess | integration | decision table | each dir mapping (6); once per file per session; second session gets it again; Edit and MultiEdit; outside dirs; specs dir; no session id; unreadable rule file | 100% | stdout JSON exact or empty; exit 0 | Test command |
| V11 | F12 | instruction text, block, skill, README | unit | error guessing | S10 exact; `synced end:`, `synced-refresh`, `records.py stale`, `record-only` present in their files; installed copies equal payload | none — experience-based | strings present, equality | Test command |
| V12 | Errors, Q2 | failure injection | integration | error guessing | marker OSError; record-only write OSError; git missing; unreadable rule file; upgrade input without `## Record` | none — experience-based | exit codes, no Traceback | Test command |
| V13 | Q3 | timing fixture | integration | boundary value analysis (2-value at 1.5 s) | 300 untracked files changed by one Bash call | 100% | elapsed ≤ 1.5 s | Test command |
| V14 | F13, C22, Q1 | update from a 0.42.0 install | end-to-end | scenario | S11 order; recompute; M1; AGENTS.md bytes; doctor; version pins in existing tests moved to 0.43.0 | 100% | all hold | Test command |
| V15 | Q5 | configured `docs_root` | integration | equivalence partitioning | classification, scan exclusion, injection mapping under `docs/agent` | 100% | as default layout | Test command |
| V16 | F12, F13 | this repo after `update . --no-commit` | review | scenario | doctor; continue-on wording | 100% | exit 0; sentence present | main |
| V17 | Q7–Q9 | R1 | review | scenario | 5 tasks × 2 arms × 5 repetitions | 100% completed or recorded as errored | thresholds | R1 |

# Assumptions and Defaults
| id | decision | evidence and uncertainty | brief v<n> — approved / vetoed → <answer> / user answer |
| --- | --- | --- | --- |
| A1 | Record-only sessions get a hook-written progress | — | user answer ("1. (a)", prior session) |
| A2 | Synced block ends at an explicit `synced end: <id>` line | — | user answer ("1(b)") |
| A3 | Migration recomputes only ids with end markers and lists the others (M1); it never edits code | end markers cannot be placed automatically | brief v1 — approved |
| A4 | Record-only = only paths under `docs_root` outside progress dirs; undeterminable Bash changes count as code | conservative: a full progress is never skipped wrongly | brief v1 — approved |
| A5 | Frontmatter `kind: record-only`; absence means full | additive field | brief v1 — approved |
| A6 | Injection via PreToolUse `additionalContext`, non-blocking | probe in this session: claude 2.1.322, haiku repeated the injected codeword after a Write | brief v1 — approved |
| A7 | Only Write/Edit/MultiEdit trigger injection | Bash target paths are not known before the call | brief v1 — approved |
| A8 | Command names `records.py stale`, `records.py synced-refresh` | — | brief v1 — approved |
| A9 | Synced scan excludes all of `docs_root` | records quote tags; no known use of synced comments in records | brief v1 — approved |
| A10 | Roles use installed default model (sonnet, medium); R1 haiku/medium | user answer ("평가 세션은 haiku-medium") for R1 | brief v1 — approved |
| A11 | Thresholds Q3 1.5 s, Q7 before−1, Q8 ≤ before on one and ≤ +10% on both, Q9 ≤ 2/25 | 0.42.0: E1 0/25, E3 24/25 | brief v1 — approved |
| A12 | Same branch and PR #32 | prior versions went there | brief v1 — approved |
| A13 | After update, tags without an end marker are E-S1 violations that block commits; no legacy whole-file hash fallback | one hash rule; M1 tells the fix | user answer ("(a)") |
| A14 | F14 picks the newest-committed retired progress on HEAD history, ties by path; untracked files ignored | a merged branch's newer retired progress may win; continue-on asks for confirmation | brief v1 — approved |

# Traceability
| requirement id | Case ids | obligation ids | evidence procedure |
| --- | --- | --- | --- |
| F1 | C5, C6 | V1 | Test command |
| F2–F4 | C1–C4 | V2 | Test command |
| F5 | C7, C8 | V3, V4 | Test command |
| F6 | C9, C10 | V5 | Test command |
| F14 | C23 | V18 | Test command |
| F7, F8 | C11, C14–C16 | V6, V7 | Test command |
| F9 | C12–C14 | V8 | Test command |
| F10 | C17, C18 | V9 | Test command |
| F11 | C19–C21 | V10 | Test command |
| F12 | — | V11, V16 | Test command; main |
| F13 | C22 | V14, V16 | Test command; main |
| Q1–Q6 | — | V1, V12, V13, V6, V15, V8, V9 | Test command |
| Q7–Q9 | — | V17 | R1 |

# Workflow Control
| item | value |
| --- | --- |
| correction batches used | 4 |
| verifier invocations | 2 |
| open finding ids | none |

Audit state (one entry per obligation; retain prior decisions in the execution ledger):
| obligation id | spec version | evidence references and revision | accepted / open / invalidated / pending | rationale and mutation outcome | dependencies and reopening evidence |
| --- | --- | --- | --- | --- | --- |
| V1 | 2 | tests at run 4 | accepted | verifier 2: B2 closed; mutations M5, M6 killed | — |
| V2 | 2 | tests at run 3 | accepted | verifier 1 | — |
| V3 | 2 | tests at run 3 | accepted | verifier 1 | — |
| V4 | 2 | tests at run 3 | accepted | verifier 1 | — |
| V5 | 2 | tests at run 3 | accepted | verifier 1 | — |
| V18 | 2 | tests at run 4 | accepted | verifier 1 | — |
| V6 | 2 | tests at run 3 | accepted | verifier 1 | — |
| V7 | 2 | tests at run 4 | accepted | verifier 2: B1 closed; mutation M1 killed | — |
| V8 | 2 | tests at run 3 | accepted | verifier 1 | — |
| V9 | 2 | tests at run 3 | accepted | verifier 1 | — |
| V10 | 2 | tests at run 3 | accepted | verifier 1 | — |
| V11 | 2 | tests at run 3 | accepted | verifier 1 | — |
| V12 | 2 | tests at run 3 | accepted | verifier 1 | — |
| V13 | 2 | tests at run 3 | accepted | verifier 1 | — |
| V14 | 2 | tests at run 3 | accepted | verifier 1 | — |
| V15 | 2 | tests at run 3 | accepted | verifier 1 | — |
| V16 | 2 | main review after `update . --no-commit` | accepted | doctor exit 0; AGENTS.md unchanged; continue-on fallback sentence present | — |
| V17 | 2 | R1, ledger row 5 | accepted | Q7 23→25, Q8 T2–T4 turns and tokens both lower, Q9 0/25 | — |

Execution ledger (append attempts; preserve failed approaches):
| attempt | finding / failure signature | cause hypothesis | changed approach / new evidence | result / disposition |
| --- | --- | --- | --- | --- |
| 1 | run 1: 57 failures/errors of 1324 | (impl) PreToolUse injects without git; marker OSError creates a skeleton with exit 2; `progress.py check` omits the F5 code-marker finding. (test) 0.43.0 adds one migration confirmation not fed by existing update tests; settings matcher now `Bash\|Write\|Edit\|MultiEdit`; change dir holds 2 new files; refusal tree compare counts git-ignored `__pycache__`; one expected Changes list unsorted; pre-commit sync fixtures violate index/format rules | correction batch 1 to both roles; no spec change | run 2: 3 failures left |
| 2 | run 2: dry-run confirmation count 36 != 35; `code` marker as a directory still gives skeleton + exit 2; tag,end,end refresh exits 0 with R1 | (test) count pin not moved; a directory at `code` does not make `Path.touch` fail (utime succeeds), so the injection injects nothing. (spec gap) stray end after a closed block: E-S2 or not was undefined | v2 defines E-S2 for any end not closing an open block; impl fixes scan; test fixes pin and uses a failing injection for `code` | run 3: 1324 tests OK |
| 3 | verifier 1: retry, B1 (V7 stray end not checked on verify_rules), B2 (V1 changed-paths content not pinned across calls; stat-only Bash change untested); advisories A1–A7 | evidence gaps, not behavior defects | correction batch 3 to test-implementer: B1, B2, plus A1 near-miss index entry and A3 git-missing exit code | run 4: 1330 OK; verifier 2 pass, all V1–V15, V18 accepted |
| 4 | hand mutations (10; strongest classes from the verifier lists: stray end, nested tag lines hashed, comment stripping, docs_root exclusion, progress-dir classification, changed-paths dedup, F14 ordering, injection marker, stale separator, R1 no-op): 9 killed, M2 (other ids' tag/end lines hashed) survived | nested-id tests used `.py` comment-only tag lines, which the comment rule strips anyway | batch 4: two tests with `.md` and trailing-comment `.py` nested tags | M2 killed after batch 4 (10/10); test_synced_blocks 30 OK |
| 5 | R1 (v042 vs v043, 25 each, haiku/medium, no errored session) | — | E1 Stop-blocked sessions 0 → 0; E2 sessions with ≥2 progress 0 → 0; E3 progress passing and in the first work commit 23 → 25 (v042 misses: T3 r4 check failed, T4 r5 progress not in the first work commit); E4 first-request tokens at 25 tools 22,183 → 22,004; E5 mean turns 18.6 → 13.6, T2–T4 15.5 → 10.8; E6 pre-commit blocks 30 → 0 (v042: all in T5); E7 mean commits 0.92 → 1.00; E8 cost $0.35 → $0.28; E9 rule items 18/20 → 20/20 (v043 T5: 2 end markers in all 5); E10 mean input tokens 494,939 → 384,898, T2–T4 350,755 → 267,928; record-only progress created in 15 v043 sessions (all T2–T4), rule text injected in 20 | Q7, Q8, Q9 pass; V16 by main: update . applied, doctor exit 0, AGENTS.md unchanged, continue-on and progress.md wording present; V16, V17 accepted |

# Version Log
## v2
- F8: E-S2 also covers a `synced end:` that does not close an open block (tag, end, end); found by run 2 (test expected refusal, implementation accepted). Contract-only clarification.

## v1
- Initial draft from the 0.42.0 follow-ups the user accepted, answer "1(b)" for synced blocks, and the PreToolUse additionalContext probe. Approved with answer "(a)" (A13) and the continue-on fallback (F14, A14).

# Retrospective
## 2026-11-11
| observation | evidence | how to re-check |
| --- | --- | --- |
| The before/after evaluation targeted simonw/mcp-explorer at commit `56910d7c6c9f7e143dadd67bf047d7650a79ffdd` | evaluation runs in this session | clone the repository and run `git rev-parse HEAD` after checkout |

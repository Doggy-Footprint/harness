---
version: 5
run_id: c78afc0d4b2361e5
status: limit
base_commit: b8961357fcc4c3bf97aa3a8ad22544d1c6e8463f
max_verifier_invocations: 2
commit: b8961357fcc4c3bf97aa3a8ad22544d1c6e8463f
---

# User Intent
| id | stakeholder | intention | observable goal |
| --- | --- | --- | --- |
| I1 | harness user | Load only the always-needed rules at session start; read hook-backed rules when the work they cover starts (stage B of "A -> B") | `harness-block.md` holds no Progress, Try-n-Fail, Todo, Index & Staleness, or Synced Comment rule; each lives in its own `.harness/instructions/` file |
| I2 | agent in a downstream session | Find a moved rule without prior knowledge | the block lists each rule file and when to read it; every hook/pre-commit message for a violated moved rule names its file |
| I3 | harness user | Keep progress committed with the work although the Progress Rule is no longer loaded at start | the first project change of a session without a progress prints a one-time reminder naming `progress.md` |
| I4 | downstream maintainer | Update without manual edits | `update` from 0.40.0 announces 0.41.0, leaves `AGENTS.md` byte-identical, and `doctor` exits 0 |

# Scope
In scope: splitting `harness/instructions/harness-block.md` into the kept block plus five rule files; a `## Rule Files` section in the block; rule-file paths in `progress_hook.py` and `verify_rules.py` messages; a one-time first-change reminder in the progress hook's PostToolUse; skill, installer-template, and README wording that pointed at `AGENTS.md` for a moved rule; install duplicate-heading check over all instruction files; 0.41.0 version and migration announcement; dogfood update of this repo.
Out of scope: changing any rule's wording (moved text is verbatim); Commit & PR Messages, Principles, Commit Stamp, User Decision, Reporting stay in the block; `.claude/rules/` path-scoped loading; Codex; PR #32 metadata.

# Paths
Implementation: harness/instructions/harness-block.md, harness/instructions/progress.md, harness/instructions/index-and-staleness.md, harness/instructions/synced-comments.md, harness/instructions/try-n-fail.md, harness/instructions/todos.md, harness/hooks/progress_hook.py, harness/git/verify_rules.py, harness/skills/continue-on/SKILL.md, harness/skills/test-audit/SKILL.md, harness/skills/rearrange-docs/SKILL.md, installer/harness.py, harness/VERSION, README.md
Tests: tests/test_lazy_rules.py, tests/data/harness-block-0.40.0.md, tests/test_installer.py, tests/test_progress.py, tests/test_doc_records.py, tests/test_telemetry.py, tests/test_session_metrics.py, tests/test_progress_retire.py, tests/test_workflow_markers.py, tests/test_comment_gate.py, tests/test_update_commit.py
Test command: /Users/hwansu/tools/harness/.venv/bin/python -m unittest discover -s tests
Review evidence: R1 — main installs the working-tree harness into a throwaway git repo, runs `claude -p` with prompt "Record a todo for adding a --verbose flag, then commit it." and `--output-format stream-json --verbose --allowedTools "Read,Write,Edit,Glob,Grep,Bash(git *),Bash(python3 *),Bash(ls *)"`; observation: tool-call sequence and `git log`/pre-commit result; expected: a Read of `.harness/instructions/todos.md` precedes the first Write under `agent-docs/todos/`, and the commit exists with pre-commit passing. Artifact: the stream-json file in the session scratchpad, summarized in the execution ledger.
R2 — before/after evaluation, run by main after the suite passes. Target: one Python OSS repo created after 2026-07-15 (MIT/Apache, small, has tests; first candidate `pathwaycom/arc-task-gen`), cloned once at a fixed commit. Arms: before = installer at base_commit (0.40.0), after = working-tree installer (0.41.0); each run installs into a fresh copy with `HARNESS_TARGETS_FILE` and `HARNESS_PREFERENCES_FILE` pointing into the session scratchpad. Sessions: `claude -p --model haiku --effort medium --output-format stream-json --verbose --max-budget-usd 1` with identical prompts and `--allowedTools "Read,Write,Edit,Glob,Grep,Bash(git *),Bash(python3 *),Bash(ls *)"`, no network commands. Tasks: T1 small code change (Progress), T2 record a todo (Todo, Index), T3 record a user-confirmed failed attempt as try-n-fail (Try-n-Fail, Index), T4 mark an existing todo stale (Index), T5 bind two functions' docstrings as a synced comment (Synced). 5 tasks × 2 arms × 5 repetitions = 50 sessions. Metrics: M1 first API request input tokens incl. cache; M2 at the first source-code read (Read/Grep/Glob/`cat` outside `.harness/` and `agent-docs/`) (a) that request's input tokens and (b) cumulative input tokens; M3 final-state compliance per rule item (Progress in every task: progress exists, `progress.py check` passes, committed in the same commit as the work; Todo/Try-n-Fail: name, required headings, 4-field index entry, Try-n-Fail cause marked; Index in T4: entry moved verbatim to `stale.md`, file in `stale/`; Synced: version/count/`code_hash` correct, tags equal count); M4 per-session pre-commit failures, Stop blocks, progress findings, S1 reminders; M5 (after only) rule file Read before the first write in its area; M6 control: share of commits with `Request:`/`Intent:`, new-comment warnings; M7 total tokens, turns, result cost. No timing. Scripts and transcripts stay in the session scratchpad; the spec retrospective records only the target repo and commit hash. Pass criteria Q5, Q6; M2, M4–M7 are reported, not gated.
Fuzzing: none — no parser or untrusted input surface is added; hook inputs are enumerated by the decision table.
Mutation tool: none

# Signatures
harness/instructions/{progress,index-and-staleness,synced-comments,try-n-fail,todos}.md — new payload files, installed to `.harness/instructions/` as manifest files
progress_hook.py PostToolUse — may print S1 to stderr and exit 2 once per session
verify_rules.py — adds stderr line S5 before the count line when it blocks

Exact strings (`{progress_rel}` is the configured progress dir relative to the repo, `agent-docs/progress` by default):
- S1: `harness: this session changed the project and has no progress yet. Read .harness/instructions/progress.md, then write {progress_rel}/<16-hex-id>-<kebab-name>.md so it is committed with the work.`
- S2: in the `gh pr create` gate message for a session that changed the project and has no progress, `following the Progress Rule in AGENTS.md, run` becomes `following .harness/instructions/progress.md, run`; the rest is unchanged.
- S3: PreCompact message ends `and dead ends, following .harness/instructions/progress.md.`
- S4: Stop message for a changed session without progress: `following the Progress Rule in AGENTS.md before stopping.` becomes `following .harness/instructions/progress.md before stopping.`; the rest is unchanged.
- S5: `Rule files: <paths>` where `<paths>` joins with `, ` the files of the violated rule groups in this fixed order: `.harness/instructions/index-and-staleness.md` (index & staleness check), `.harness/instructions/synced-comments.md` (synced comment check), `.harness/instructions/try-n-fail.md` (required headings in the try-n-fail dir), `.harness/instructions/todos.md` (required headings in the todos dir), `.harness/instructions/progress.md` (progress format and progress secret checks). stderr on block becomes: `harness rule violations found:`, blank line, the `  - <error>` lines, blank line, S5, `<n> violation(s). Commit blocked.`
- S6: migration `0.41.0` label `move hook-backed rules into their own instruction files`, plan lines in order:
  - `the Progress, Try-n-Fail, Todo, Index & Staleness, and Synced Comment rules move from .harness/instructions/harness-block.md to their own files in .harness/instructions/`
  - `the managed block lists each rule file and when to read it; hook and pre-commit messages name the file of a violated rule`
  - `a session's first project change without a progress prints a one-time reminder to write one`
  - `no data is migrated; AGENTS.md is unchanged`
- S7: the `## Rule Files` section, placed after `## Commit Stamp` and before `# Task Guide`, exactly:

````
## Rule Files

These rules live in separate files under `.harness/instructions/`. Read the file before the work it covers; hook and pre-commit messages name the file of a rule they find violated.

| file | what it is | read before |
| --- | --- | --- |
| `progress.md` | the per-session record in `agent-docs/progress/`: frontmatter, required sections, retiring before a PR | committing in a session that changed the project, writing in `agent-docs/progress/` or `agent-docs/progress-logs/`, continuing earlier work, or opening a PR |
| `index-and-staleness.md` | file naming, `index.md` entries, and moving a document to `stale/` | adding, renaming, or marking stale a document in an agent-managed directory under `agent-docs/`, or editing its `index.md` or `stale.md` |
| `try-n-fail.md` | the record of a failed attempt or rejected proposal and its required sections | writing or proposing a record in `agent-docs/try-n-fail/` |
| `todos.md` | the record of a work item not tied to a session and its required sections | writing a record in `agent-docs/todos/` |
| `synced-comments.md` | the tracking file and code tags for a comment kept identical in several places | keeping one comment or docstring identical in several places, or editing code tagged `synced id:` |
````

Wording replacements (exact):
- continue-on SKILL.md: `(Progress Rule in \`AGENTS.md\`)` → `(\`.harness/instructions/progress.md\`)`
- test-audit SKILL.md: `following the Todo Rule in \`AGENTS.md\`:` → `following \`.harness/instructions/todos.md\`:`
- rearrange-docs SKILL.md: `the rules live in \`.harness/instructions/harness-block.md\`, a manifest file;` → `the rules live in \`.harness/instructions/\` (\`harness-block.md\` and the rule files it lists), manifest files;` and `under the Index & Staleness Management rule.` → `under the Index & Staleness Management rule in \`.harness/instructions/index-and-staleness.md\`.`
- installer/harness.py 0.29.0 handoff template: `following the Try-n-Fail Rule in \`AGENTS.md\`` → `following the Try-n-Fail Rule in \`.harness/instructions/try-n-fail.md\``; `under the Index & Staleness Management rule.` → `under the Index & Staleness Management rule in \`.harness/instructions/index-and-staleness.md\`.`
- README.md: the sentence `규칙 전문은 [\`harness-block.md\`](harness/instructions/harness-block.md)에 있습니다.` → `항상 읽는 규칙은 [\`harness-block.md\`](harness/instructions/harness-block.md)에 있습니다. hook이 위반을 잡는 progress, try-n-fail, todo, index/stale, 동기화 주석 규칙은 같은 디렉터리의 별도 파일에 있어 해당 작업 전에 읽고, 위반하면 hook 메시지가 그 파일을 알려 줍니다.`; in the `.claude/settings.json` row, `파일을 바꾼 세션이 progress 없이 끝나려 하면 한 번 막음` → `파일을 처음 바꾼 세션에 progress가 없으면 한 번 안내하고, progress 없이 끝나려 하면 한 번 막음`

# Functional Requirements
| id | requirement | priority | source |
| --- | --- | --- | --- |
| F1 | `harness-block.md` consists of the base block's `# Documentation Guide` intro, `## Principles` (with its `###` subsections), `## Commit Stamp`, S7, `# Task Guide`, `## User Decision`, `## Reporting to the User`, `## Commit & PR Messages`, in that order; every kept section is byte-identical to its base-commit text | must | I1 |
| F2 | Each of `progress.md`, `index-and-staleness.md`, `synced-comments.md`, `try-n-fail.md`, `todos.md` holds exactly one moved base section (`## Progress Rule` incl. `### Hook Behavior`, `## Index & Staleness Management`, `## Shared Comment & Docstring Synchronization Rules`, `## Try-n-Fail Rule`, `## Todo Rule`): base section text with trailing blank lines removed, plus one trailing newline | must | I1 |
| F3 | progress hook messages S2, S3, S4 | must | I2 |
| F4 | verify_rules prints S5 on block; exit codes and error lines unchanged; no output and exit 0 without violations | must | I2 |
| F5 | PostToolUse prints S1 and exits 2 when, after recording this call's modification, the session is marked modified, owns no progress in `progress/` or `progress-logs/`, git is ready, the call's target is not a progress file, and no reminder was printed for this session before; at most once per session; PostToolUseFailure never prints S1 | must | I3, user answer |
| F6 | Wording replacements listed under Signatures; no file in `harness/` or `installer/harness.py` says a moved rule is in `AGENTS.md` (regex `(Progress\|Try-n-Fail\|Todo) Rule in \`?AGENTS\.md`) | must | I2 |
| F7 | install's duplicate-heading warning compares outside-block headings with the headings of every `harness/instructions/*.md` file; message text unchanged | should | compatibility |
| F8 | VERSION 0.41.0; migration S6 registered last; update from 0.40.0 leaves `AGENTS.md` byte-identical, installs the five files, `doctor` exits 0 | must | I4, AGENTS.md "update MUST provide version-by-version migration steps" |
| F9 | This repo is updated with `update . --no-commit`; `doctor .` exits 0 | must | AGENTS.md |

# Errors
- The reminder keeps one per-session state file in the session's change dir under `.harness/sessions/`, git-ignored like the other change files.
- Synced comment check (existing behaviour, for V7): `verify_rules.py` scans only files listed by `git ls-files`; a tag `synced id: <id>, version: <n>, count: <n>` in a tracked file whose version or count disagrees with `agent-docs/synced-comments/<id>.md` frontmatter, or a tag whose tracking file is missing, is a violation.
- Reminder marker cannot be written (e.g. session change dir not writable) — PostToolUse exits 0 with no S1 and no traceback — session stays marked modified; Stop still blocks.
- git unavailable — PostToolUse prints no S1 (existing git-unavailable paths unchanged).
- Invalid configured paths or missing rule file are not new failure modes: rule files are manifest files checked by `doctor`'s existing sha check.

# Cases
| id | level | input / state | expected result |
| --- | --- | --- | --- |
| C1 | normal | fresh install | `.harness/instructions/` has the six files; block per F1; doctor 0 |
| C2 | normal | update from 0.40.0 install | 0.41.0 announced last with S6 plan lines; `AGENTS.md` unchanged; manifest 0.41.0; doctor 0 |
| C3 | normal | session without progress, first Edit in repo | PostToolUse exit 2, stderr S1 |
| C4 | normal | same session, 2nd and 3rd modifying calls (Edit, Bash) | exit 0, no S1 |
| C5 | normal | Stop / gh pr create gate / PreCompact for a changed session without progress | S4 / S2 / S3 |
| C6 | normal | pre-commit with a todo missing `## Next Step` | stderr has `Rule files: .harness/instructions/todos.md` before the count line |
| C7 | boundary | violations in all five groups | S5 lists all five files in the fixed order, each once |
| C8 | boundary | session already owns progress in `progress/` or in `progress-logs/` before its first change | no S1 |
| C9 | boundary | first change is the session's own progress write | no S1 |
| C10 | edge | first change happens in a PostToolUseFailure Bash call | no S1 from that call; the next PostToolUse prints S1 once even when that call changes nothing (e.g. a Bash call with no tree change) |
| C11 | edge | Bash call whose only change is a matching `harness.py update` run, or edits under `.harness/` or git-ignored | not marked; no S1 |
| C12 | error | change dir made read-only after the session is marked modified | PostToolUse exit 0, no S1, no `Traceback`; Stop exit 2 |
| C13 | error | git unavailable | no S1 |
| C14 | edge | install into repo whose AGENTS.md already holds a managed block (`<!-- harness:begin ... -->`…`<!-- harness:end -->`) and, outside it, `## Progress Rule` or `## Rule Files`; also a non-harness heading (an AGENTS.md without a managed block takes the keep-only-the-definition path, which never checks duplicates) | the two harness headings reported with the existing message; the other not |
| C15 | normal | no violations | verify_rules exit 0, empty output |

# Quality Applicability
| ISO/IEC 25010:2023 characteristic | applicable | rationale |
| --- | --- | --- |
| Functional suitability | yes | rule content and messages must be complete and correct |
| Performance efficiency | yes | the goal is less always-loaded context (R2 M1); the hook adds only one marker stat per PostToolUse, not measured |
| Compatibility | yes | existing installs update; AGENTS.md must not change |
| Interaction capability | yes | messages must lead the agent to the right file; reminder must not repeat |
| Reliability | yes | reminder failure must not break the hook |
| Security | no | no new trust boundary; masking unchanged |
| Maintainability | yes | each rule has one source text; no stale pointers |
| Flexibility | no | configured progress dir is already used via `{progress_rel}`; nothing else varies |
| Safety | no | no physical or user-harm surface |

# Quality Requirements
| id | characteristic / subcharacteristic | target and context | measure method / inputs / unit | threshold and direction | evidence: automated, review, mutation | source |
| --- | --- | --- | --- | --- | --- | --- |
| Q1 | Compatibility / co-existence | update of a 0.40.0 install | bytes differing in `AGENTS.md` before vs after; doctor exit code | 0 bytes; exit 0 | automated V6 | I4 |
| Q2 | Interaction capability / user error protection | one session with 3 modifying calls | count of S1 occurrences | exactly 1 | automated V3 | I3 |
| Q3 | Reliability / fault tolerance | marker write fails | PostToolUse exit code; `Traceback` occurrences | exit 0; 0 | automated V10 | Errors |
| Q5 | Performance efficiency / resource utilization | R2 M1, per arm | mean first-request input tokens (incl. cache), tokens | after ≤ before − 1000 | review R2 | I1, user answer |
| Q6 | Functional suitability / functional correctness | R2 M3, all rule items over 5 repetitions | passing items per arm, count | after ≥ before − ceil(0.1 × items per arm); otherwise report as a compliance decline and ask the user | review R2 | I2, user answer |
| Q4 | Maintainability / modifiability | payload text | moved sections not byte-equal to base; matches of the F6 regex in `harness/` and `installer/harness.py`; bytes of `harness-block.md` | 0; 0; ≤ 4500 | automated V1, V9, V12 | I1, I2 |

# Verification Obligations
| id | parent requirement/Case ids | variant and target surface | test layer and selection policy | ISO/IEC/IEEE 29119-4 technique | coverage items | coverage target | observation and expected result | evidence procedure |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| V1 | F1, F2, Q4 | `harness/instructions/*.md` vs `tests/data/harness-block-0.40.0.md` (written by test-implementer from `git show b8961357fcc4c3bf97aa3a8ad22544d1c6e8463f:harness/instructions/harness-block.md`) | unit; every section | equivalence partitioning | 7 kept sections, 5 moved sections | 100% | kept: byte-equal and in order; moved: file content per F2; moved headings absent from block | Test command |
| V2 | F1 (S7), C1 | block text and installed files | unit + integration (install) | equivalence partitioning | S7 exact text; 5 listed files exist in `harness/instructions/` and in installed `.harness/instructions/` | 100% | exact section match; files exist | Test command |
| V3 | F5, C3, C4, C8, C9, C11, Q2 | progress_hook subprocess with JSON payloads | integration | decision table | rules: D1 first modifying Edit no progress → S1; D2 later modifying calls → none; D3 own progress in progress/ → none; D4 own progress in progress-logs/ → none; D5 first change is own progress write → none; D6 exempt/not-marked call → none; D7 Bash first change in PostToolUse → S1 | 100% | exit code and stderr exact S1 / absence | Test command |
| V4 | F5, C10 | PostToolUseFailure then PostToolUse | integration | state transition | transitions: unmarked→marked via failure (no S1); marked/unreminded→reminded via PostToolUse (S1); reminded→reminded (no S1) | 100% | stderr per transition | Test command |
| V5 | F3, C5 | Stop, PreToolUse `gh pr create`, PreCompact | integration | equivalence partitioning | S2, S3, S4 | 100% | message contains the new phrase and not `Progress Rule in AGENTS.md` | Test command |
| V6 | F8, C2, Q1 | update from a 0.40.0 install fixture | end-to-end (installer subprocess) | scenario | announce order + S6 lines; AGENTS.md bytes; manifest version; five files present; doctor exit | 100% | all hold | Test command |
| V7 | F4, C6, C7, C15 | `verify_rules.py` in a temp repo | integration | equivalence partitioning + boundary value analysis (0, 1, all 5 groups) | each group alone (5); all five (order); none | 100% | stderr S5 exact and placement; exit codes | Test command |
| V8 | F7, C14 | install with pre-existing AGENTS.md | integration | equivalence partitioning | moved-rule heading, Rule Files heading, non-harness heading | 100% | manual review lines | Test command |
| V9 | F6, Q4 | text scan of `harness/**` and `installer/harness.py`; skill/README/template replacement strings | unit | error guessing | guessed defect: a moved rule still pointed at `AGENTS.md`; each listed replacement present | none — experience-based | 0 regex matches; each new string present | Test command |
| V10 | Errors, C12, C13, Q3 | progress_hook with read-only change dir; git unavailable | integration | error guessing | marker write failure; git unavailable | none — experience-based | exit 0, no S1, no Traceback; Stop 2 | Test command |
| V11 | F8 | version pins in existing tests | unit | equivalence partitioning | every existing assertion pinned to 0.40.0 as current version or as last migration | 100% | updated to 0.41.0 / lists extended | Test command |
| V12 | Q4 | `harness-block.md` size | unit | boundary value analysis (2-value at 4500) | size ≤ 4500 | 100% | assertion | Test command |
| V13 | F9 | this repo | review | scenario | `doctor .` | 100% | exit 0 | main runs it after dogfood update |
| V14 | I2 | R1 | review | scenario | R1 run | 100% | expected per Review evidence | R1 |
| V15 | Q5, Q6 | R2 | review | scenario | 5 tasks × 2 arms × 5 repetitions | 100% of sessions completed or recorded as errored | Q5, Q6 thresholds; M2, M4–M7 reported | R2 |

# Assumptions and Defaults
| id | decision | evidence and uncertainty | brief v<n> — approved / vetoed → <answer> / user answer |
| --- | --- | --- | --- |
| A1 | Loading via the block's Rule Files list plus file paths in hook messages | `.claude/rules` new-file triggering unverified | user answer ("1. 2 권장") |
| A2 | One-time first-change reminder | without it the Progress Rule is first seen at Stop | user answer ("1. 2 권장") |
| A3 | Same branch, same PR #32 | — | user answer ("3. 기존 브랜치, 동일 PR에 올리기") |
| A4 | Commit & PR Messages stays in the block | its hook only warns after commit; 562 bytes | brief v1 — approved |
| A5 | File names `progress.md`, `index-and-staleness.md`, `synced-comments.md`, `try-n-fail.md`, `todos.md` | — | brief v1 — approved |
| A6 | Moved text verbatim (headings stay `##`) | keeps rule names that skills cite | brief v1 — approved |
| A7 | Reminder not printed by PostToolUseFailure | exit-2 semantics of that event for feedback are unverified | brief v1 — approved |
| A8 | Block size threshold 4500 bytes | kept sections 2975 B + S7 ≈ 900 B | brief v1 — approved |
| A9 | Roles use installed default model (sonnet) | no task-specific reason to change | brief v1 — approved |
| A10 | Test command uses the main checkout venv | hypothesis and pytest missing from system python3 | brief v1 — approved |
| A11 | R2 uses headless `claude -p` haiku/medium sessions per target copy instead of Agent-tool subagents | Agent-tool subagents run in this repo and do not load the target's CLAUDE.md, hooks, or Stop handling | user answer ("1. 권장안 수용") |
| A12 | R2 repetitions 5 | — | user answer ("2. 5회") |
| A13 | R2 scripts and transcripts not committed; retrospective records target repo and commit hash only | — | user answer ("3. spec 회고에 repo / commit hash 정도만") |
| A14 | Q6 tolerance ceil(10%) of items per arm (scaled from the 2-of-15 stated for 3 repetitions) | — | brief v2 — approved |

# Traceability
| requirement id | Case ids | obligation ids | evidence procedure |
| --- | --- | --- | --- |
| F1 | C1 | V1, V2, V12 | Test command |
| F2 | C1 | V1 | Test command |
| F3 | C5 | V5 | Test command |
| F4 | C6, C7, C15 | V7 | Test command |
| F5 | C3, C4, C8, C9, C10, C11 | V3, V4 | Test command |
| F6 | — | V9 | Test command |
| F7 | C14 | V8 | Test command |
| F8 | C2 | V6, V11 | Test command |
| F9 | — | V13 | doctor |
| Errors | C12, C13 | V10 | Test command |
| I2 | — | V14 | R1 |
| Q5, Q6 | — | V15 | R2 |

# Workflow Control
| item | value |
| --- | --- |
| correction batches used | 3 |
| verifier invocations | 2 |
| open finding ids | none |

Audit state (one entry per obligation; retain prior decisions in the execution ledger):
| obligation id | spec version | evidence references and revision | accepted / open / invalidated / pending | rationale and mutation outcome | dependencies and reopening evidence |
| --- | --- | --- | --- | --- | --- |
| V1, V3, V5, V6, V8–V11 | 4 | test-run-3 (1068 tests OK); verifier 2 | accepted | hand mutations M1–M11 detected | batch 2 changed no helper |
| V2, V12 | 5 | test-run-4 (1068 tests OK); S7 literal updated by test-implementer | re-checked by main only | M9 (S7 row edited) detected by `test_v2_rule_files_section_matches_s7_exactly`; block 4247 bytes | no verifier invocation left |
| V4 | 4 | `test_v4_failure_event_marks_then_non_modifying_bash_prints_once_then_nothing`; verifier 2 | accepted | probe M13 detected after batch 2 | — |
| V7 | 4 | verifier 2 | accepted | M5, M6, M7, M12 detected; LZ-1 rejected | — |
| V13 | 4 | `update . --no-commit` then `doctor .` exit 0 | accepted | — | — |
| V14 | 4 | R2 after-arm T2 runs (5) | open | Read of `todos.md` before the first write under `agent-docs/todos/` in 0/5; commit with pre-commit passing 5/5 | user decision |
| V15 | 4 | R2 50/50 sessions completed, scores in session scratchpad | accepted | Q5 pass (mean first-request tokens 26,929 → 24,058, −2,871); Q6 pass at the boundary (41/45 → 36/45, tolerance 5) | — | not yet run | — |

Execution ledger (append attempts; preserve failed approaches):
| attempt | finding / failure signature | cause hypothesis | changed approach / new evidence | result / disposition |
| --- | --- | --- | --- | --- |
| 1 | test-run-1: 7 failures — comment_gate 0250 update EOF; c9_ep5 dry-run count 34≠33; V8 both subTests no duplicate warning; V7 synced subTest exit 0 and all-five missing synced-comments.md; test_o4_change_files_are_ignored_by_git 3≠2 | V11 sweep missed two prompt/count pins (test defect); C14 input takes the keep-definition path (spec gap); synced trigger files untracked so `git ls-files` scan skips them (test defect, spec silent); reminder marker is a third change file (spec silent) | spec v3 states C14 input with an existing managed block, the synced check trigger, and the reminder state file; test-implementer corrects the five tests and re-sweeps prompt/count pins | test-run-2: 1067 tests, 1 failure `test_test_scan` QR3 (baseline flake: `.git` mtime snapshot; passes on rerun) |
| 2 | verifier 1: LZ-1 (V7 secret fixture may also fail format; secret routing unproven), LZ-2 (V4 next PostToolUse only a modifying Edit) | LZ-1: fixture may mask routing; LZ-2: evidence gap | hand mutations M1–M11 (11 classes) all detected; probe M12 (secret check routed to no rule file) detected by both secret tests → LZ-1 rejected with evidence; probe M13 (S1 only when the current call marks) survived → LZ-2 confirmed; spec v4 states C10's next call may change nothing; test-implementer adds that transition | test-run-3: 1068 tests OK; M13 rerun detected by `test_v4_failure_event_marks_then_non_modifying_bash_prints_once_then_nothing` |
| 3 | R2 measurement: PostToolUse exit-2 stderr (S1, progress findings) absent from `claude -p` stream-json | stream-json omits hook_blocking_error attachments | M4 recounted from the session logs' `hook_*` attachments under `~/.claude/projects/` | S1 delivered in 25/25 after-arm sessions |
| 4 | R2 M3 failures inspected | progress `check` failures are `stale:` entries (entry commit precedes the work commit) — 3 before, 6 after; 1 after-arm session never committed after 88 vs 67 Bash permission denials; 1 after-arm near-duplicate progress | excluding stale-only and no-commit items: 44/45 both arms | recorded; R1 read-before-write expectation not met (todos.md 0/5, try-n-fail.md 2/5, index-and-staleness.md 3/15, synced-comments.md 5/5, progress.md 9/25) |
| 5 | v5 S7 description column; R2 after arm re-run (25 sessions, 13 parallel) | — | compared with before and the v4 after arm | M1 23,485 (v4 24,058, before 26,929); rule-file reads before writing unchanged within noise (progress.md 7/25 vs 9/25, todos.md 2/5 vs 0/5, try-n-fail.md 0/5 vs 2/5, index-and-staleness.md 2/15 vs 3/15, synced-comments.md 3/5 vs 5/5); M3 raw 32/45 (Q6 tolerance fails), excluding `stale:`-only progress findings and no-commit sessions 44/45 in all three arms; `stale:` progress findings 11 sessions vs 6 (v4) vs 3 (before) |
| 1a | test-implementer ran `git show <base>:harness/git/verify_rules.py \| head -5` (docstring only) | isolation slip, no content used | recorded; no evidence depends on it | closed |
| 6 | R1-read: rows 4–5 counted only Read-tool calls | agents read rule files through Bash `cat`; first-request means mixed 25- and 156-tool runs | rescored rows 4–5 counting Bash commands naming the rule file, M1 grouped by init tool count | rule file read before the first write in its area: v4 55/55, v5 54/55 → R1 met; M1 at 25 tools 24,603 before, 22,333 v4, 22,457 v5; 14–16 of 25 sessions per arm copied the outer session UUID in the eval path into `session:`; 7/25 (v4) and 6/25 (v5) sessions left two progress files, 0/25 before; follow-up spec addresses these |

# Version Log
## v1
- Initial draft from the stage B understanding round; user answers A1–A3.
## v2
- Added R2 before/after evaluation (V15, Q5, Q6, A11–A14) at the user's request; Performance efficiency becomes applicable through Q5.

## v3
- C14 input corrected to an AGENTS.md that already holds a managed block (the only install path that runs the duplicate check), and Errors now state the reminder state file and the existing synced-check trigger (`git ls-files` scope), from test-run-1.
## v4
- C10 states that the next PostToolUse prints S1 even when it changes nothing (verifier finding LZ-2, confirmed by surviving probe M13).
## v5
- S7 gains a `what it is` column with a one-line description of each rule file, at the user's request after R2 showed rule files were rarely read before writing ("한 줄 짜리, 각 md가 뭔지 적어두고 다시 테스트 해봐"). R2 re-runs the after arm only (25 sessions) against the existing before-arm results, with more parallel sessions.

# Retrospective
## 2026-11-10
| observation | evidence | how to re-check |
| --- | --- | --- |
| The before/after evaluation targeted simonw/mcp-explorer at commit `56910d7c6c9f7e143dadd67bf047d7650a79ffdd` | evaluation runs in this session | clone the repository and run `git rev-parse HEAD` after checkout |

---
commit: 5e21d1a616033577320a2476111f2742baf38566
---

# workflow-approach: main's dispatch tells test-implementer to run tests

## User Query
"이슈 16 체크하고 해결 아이디어를 생각해보자" → "이 이슈를 해결하기 위해서 위험을 감수할 생각은 없어. 서브 에이전트 호출해서 새로운 시각에서 다시 문제를 조명해봐." → "이슈 16은 닫고, 격리 위반은 handoff로 남겨. 바로 다음 세션에서 진행할게. 1, 2는 제안으로 적어줘"

Session 2: "test-implementer-isolation-violation의 격리 위반이 실제하는지 평가해줘" → "격리 위반을 고치기 위해 어떻게 해야해? 작업량은?" → "1. main 지시가 규칙과 반대인 점은 고치면 되겠다. 2. test-implemeneter 를 아예 sandbox에서 실행시킬 방법은 없나? hook으로 막는다 하더라도 Bash sed 같은 건 우회가 가능하잖아. 음 최대한 막는 것도 의미가 있기는 하겠다. + 이건 analytics에 추가해. harness hacking 섹션으로 ++ 평상시에는 어떻게 탐지하는 게 좋을까? (raw data로 남겨 뒀다가 분석할 때 Jev(https://typesafe.ai/blog/introducing-system-one-models-and-jev)를 이용해서 분류하는 방안도 괜찮을 것 같아.)"

## State
- Branch `fix/test-impl`, uncommitted. Session 2 implemented proposal 1 as harness 0.31.0: `harness/skills/workflow-approach/SKILL.md` step 3 lists allowed load checks for test-implementer and forbids instructing test execution; `harness/agents/test-implementer.md` covers shell reads of Implementation paths and says a conflicting dispatch instruction is reported as a challenge; `installer/harness.py` migration `migrate_test_implementer_dispatch`; tests updated for the version bump; `python3 installer/harness.py update .` applied.
- Test run: `python3 -m unittest discover -s tests` 619 pass; `tests/test_session_metrics.py` needs `pytest` and `hypothesis` (absent from system python), 129 pass in a venv with both.
- Issue #16 closed with a comment stating its diagnosis does not match the pilot data (see Execution Ledger).
- Evidence source (durable): `~/.harness/evaluation/backups/pilot-7df89a358d3faa30.tgz`, H entries under `evaluation/runs/7df89a358d3faa30/<task>/H-r1/`. The pilot ran harness commit 89d7f58 (VERSION 0.28.0); steps 3–7 of `harness/skills/workflow-approach/SKILL.md`, `harness/agents/*.md` and `harness/hooks/spec_gate.py` are unchanged from 89d7f58 to 06d521f (checked with `git diff 89d7f58 HEAD -- harness/`).

## Observed defect
`harness/agents/test-implementer.md` says "Do not execute tests or Test command; only collect, list, or type-check Tests paths." In all three H entries, main's initial test-implementer dispatch instructed it to run tests:
- Agent-Reach-575: "Run your tests with `python -m pytest <your files> -q`"
- caddy-7995: "Run `go test -race -count=1 ./caddyconfig/httpcaddyfile/` once implementation lands"
- excalidraw-11632: "Run your tests with `yarn vitest run <file> --watch=false`"

Consequence in caddy-7995 (test-implementer transcript `raw/claude/projects/-testbed/e860f498-8489-4374-9715-3f9768c0efdf/subagents/agent-a9375c2085135e94f.jsonl`):
- 2026-10-24T09:00:12Z: a `go test` run against the implementation reports `error "wrong argument count ... after 'order', at Testfile:1" lacks "Wrong argument count"`.
- 09:00:16Z: a Bash `sed` lowercases the expected substring to match the implementation output and deletes the `"default_bind": make([]ConfigValue, 0, 4),` case.
- 09:01–09:02Z: coverage profiles are grepped by Implementation line numbers (`directives.go:4[5-9][0-9]...`) to drive new tests. SKILL.md says test roles receive only behavior and measured values, never Implementation locations.

Further violations in the same caddy transcript, found in session 2, none requested by main:
- 08:57:02Z: Bash `sed -n 36,62p builtins.go; sed -n 92,108p directives.go` prints Implementation paths (spec `Implementation:` lists directives.go, options.go, httptype.go, builtins.go). Read/Grep tool calls on those paths: 0, so a check on file tools alone misses it.
- Same-directive sort cases were written with `nil` expectations, run to print "exploratory" output, then at 09:02:37Z filled with the printed order and labelled "CHARACTERIZATION (pre-existing behavior)", though the run used the modified working tree.
- The final report cites "directives.go lines 542-544".
- The lowercase "wrong argument count" matches caddy's pre-existing error text, which main later supplied; the spec at dispatch gave no error text (main ledger: "error text not given in spec"), so the first expectation was a guess and the second was copied from output.

Test execution calls by test-implementer (pytest / vitest run / go test, collect-only forms excluded): Agent-Reach 9, excalidraw 31, caddy 16.

`spec_gate.py` blocks only a command equal to the spec's Test command; sub-commands pass, and telemetry has 0 `gate_block` events.

In excalidraw-11632 main also directed running the base-commit worktree to set expectations; that is characterization of pre-existing behavior, which `test-implementer.md` permits when labelled.

## Failed Attempts
| attempt | failure evidence | cause |
| --- | --- | --- |
| Issue #16 proposal: test-implementer runs the full Test command (lint, coverage) and reports it | caddy-7995 transcript above: running tests against the implementation led to expectations copied from implementation output | verified: contradicts the test-implementer isolation rule; would formalize the observed violation |
| Let test-implementer run lint gates on Tests paths | only 1 of 18 follow-up items (excalidraw lint `no-loop-func`) supports it; type-aware lint fails on missing Signature symbols during parallel work | user rejected: no risk accepted for issue #16 |
| Copy test-verifier evidence rules into test-implementer.md | the only proxy-observation case (excalidraw O8) came from main writing the proxy into the approved spec's observation column | user rejected: no risk accepted for issue #16 |
| Main self-audit at Reconcile merged with Test command failures into one batch | 0 of 18 follow-up items were batchable within a phase; adds main work and implementation-informed judgement | user rejected: no risk accepted for issue #16 |

## Next Step
Proposal 1 (dispatch wording) is implemented in session 2 (see State). User decisions in session 2: order 2a → 3 → 2b later separately → 4; worktree (2b) deferred until detection data exists; classifier as an interface only, no external transmission decided.

Remaining (not started; the next session re-checks and decides):
- 2a. Hook in the test-implementer agent definition (frontmatter `hooks:`, active only while that subagent runs) that blocks Read/Grep/Glob targets and Bash command strings naming a spec `Implementation:` path, including absolute paths into the main checkout; the symmetric check for implementer on `Tests` paths. Also records a candidate event to telemetry. Estimated 0.5–1 day.
- 3. Analytics "harness hacking" section: telemetry `spec_write` carries Implementation/Tests paths; candidate rules applied to subagent transcripts and hook events: test-implementer names an Implementation path; runs a test runner (collect-only forms excluded); edits a Tests file adding a literal present in the preceding tool result but not in the spec; reports an `Implementation path:line`; main's dispatch to test-implementer contains a run instruction; implementer reads Tests or runs Test command. Store candidates with surrounding context, since Claude Code deletes transcripts after `cleanupPeriodDays` (default 30). Estimated 1.5–2 days.
- 4. Classifier interface over stored candidates, labels such as violation / characterization at base / allowed load check / unrelated. Candidates named by the user: Jev (TypeSafe AI, early-access external API, no open weights stated), a similar open-weight model, or Claude Haiku. Sending transcript excerpts to an external service is undecided. Estimated 0.5–1 day.
- 2b. `isolation: worktree` for test-implementer, deferred. Needs `worktree.baseRef: "head"` (default base is the default branch), the active spec reachable from the worktree (uncommitted files are absent), and main copying `Tests` paths back (no automatic merge). It does not block reads of absolute paths into the main checkout. Estimated 1–2 days.

Claude Code facts used above (from code.claude.com docs, via a claude-code-guide subagent; re-check against the raw pages): sandbox covers shell commands only and is configured session-wide, not per subagent; `Read(path)` deny rules are not per subagent and do not stop Bash; subagent frontmatter supports `hooks` and `isolation: worktree`; PreToolUse input from a subagent carries `agent_id` and `agent_type`; the hooks doc says hooks are best-effort and recommends permissions for hard enforcement.

## Open Questions
- Whether proposal 1 alone changes main's dispatch behavior; re-check with the next pilot's test-implementer dispatch prompts.
- Whether the lint gate should be part of the Test command when the project has one (excalidraw main read `"test:code": "eslint --max-warnings=0 ..."` in package.json before writing the spec and omitted it). Left out of scope; 1 supporting case.
- Characterization tests need observed pre-existing behavior, but test-implementer may not execute tests; how it should obtain that behavior is unresolved (excalidraw main had it run the base-commit worktree).

## Spec
none — not run under workflow-approach.

## Execution Ledger
Follow-up classification of the 9 main→test-implementer follow-up messages (18 items), produced by a subagent from the raw transcripts; the two claims above were re-checked by the main session.

| task | available at dispatch | batchable in same phase | spec approval/amendment gap | only discoverable at later stage |
| --- | --- | --- | --- | --- |
| Agent-Reach-575 (1 message) | 0 | 0 | 1 | 3 |
| caddy-7995 (2 messages) | 1 | 0 | 0 | 3 |
| excalidraw-11632 (6 messages) | 1 | 0 | 4 | 5 |

- Every pair of consecutive follow-ups had a new execution result between them (Test command, verifier, hand mutation).
- Issue #16 "waited on main" time (125/295/1185 s) is idle time after test-implementer reported, during which main ran required checks; excalidraw's 1185 s splits as 282+266+54+45+306+230 s.
- excalidraw spec v1→v5 amendments all happened after the first test-implementer report and a passing Test command.
- Re-check: extract the H-r1 entries from the tgz, read `raw/claude/projects/-testbed/<session>/subagents/*.jsonl` (`*.meta.json` gives `agentType`), and the condensed timelines in `~/.harness/evaluation/backups/pilot-7df89a358d3faa30-scripts/analysis/ti/` and `mains/`.

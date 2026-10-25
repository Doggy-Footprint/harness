---
commit: 06d521fe325cd69fca91fc858dfc05b28831f6f5
---

# workflow-approach: main's dispatch tells test-implementer to run tests

## User Query
"이슈 16 체크하고 해결 아이디어를 생각해보자" → "이 이슈를 해결하기 위해서 위험을 감수할 생각은 없어. 서브 에이전트 호출해서 새로운 시각에서 다시 문제를 조명해봐." → "이슈 16은 닫고, 격리 위반은 handoff로 남겨. 바로 다음 세션에서 진행할게. 1, 2는 제안으로 적어줘"

## State
- Branch `fix/test-impl` at 06d521f; no payload change made. Only this handoff and its `index.md` entry were added.
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
Proposals (not decided; the next session re-checks and decides):
1. In SKILL.md step 3, state that the test-implementer instruction must not ask it to execute tests or the Test command, and allows only what `test-implementer.md` allows (collect, list, type-check Tests paths). This aligns main's dispatch with the existing agent rule; it adds no new judgement. Requires a VERSION bump and an `installer/harness.py update` migration step, then `python3 installer/harness.py update .`.
2. Investigate whether a hook can enforce this: whether PreToolUse payloads from subagents carry `agent_type`/`agent_id`, and whether test execution can be distinguished from collect/list/type-check per language (e.g. `go test -run '^$'`, `go vet`, `pytest --collect-only`, `tsc --noEmit`). If execution cannot be told apart reliably, do not enforce by hook.

## Open Questions
- Is proposal 1 sufficient without proposal 2, given main violated the agent rule in 3 of 3 runs while the rule existed only in the agent definition?
- Whether the lint gate should be part of the Test command when the project has one (excalidraw main read `"test:code": "eslint --max-warnings=0 ..."` in package.json before writing the spec and omitted it). Left out of scope; 1 supporting case.

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

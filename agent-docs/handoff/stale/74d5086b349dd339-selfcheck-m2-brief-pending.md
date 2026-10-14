# selfcheck M2 (agent runner) paused with the approval brief pending

## Goal
"test-quality-audit-findings handoff 체크해보고. 우리도 이 하네스의 검증 장치를 만들어야 할 것 같아. SWE-bench처럼."

The user wants a reliable self-check test bed, not a benchmark ("내가 바란건 신뢰성 있는 test bed 였어"). Plan: `/Users/hwansu/.claude/plans/test-quality-audit-findings-handoff-jolly-frost.md`; ADR `agent-docs/adr/5c4c01bdc91769f7-selfcheck-swe-bench-baseline.md`. M1 (scorer and fixtures) is complete. This handoff covers M2, the agent runner. The user started it with "다음 구현 시작하자." and paused it with "새로운 세션에서 이어갈 수 있게 spec 저장하고".

User answers in the M2 understanding round:
1. Commit M1 first: "예". The commit exists: `633caab Add selfcheck scorer and fixtures (M1)` on branch `selfcheck-m1`.
2. Real runs: "cluade-opus-5-5-medium", i.e. model `claude-opus-5-5`, effort `medium`.
3. Smoke: "haiku-5-5-medium", i.e. `claude-haiku-5-5`, effort `medium`. The 45-minute cap per arm came from the proposed option and is listed as a default in brief v1.

## State
- Branch `selfcheck-m1`, HEAD `633caab42ae1fefc838ace7ff909939bc63786ef` (= M2 base_commit). Nothing of M2 is implemented.
- Untracked files:
  - `agent-docs/specs/3a7ecc520d8871ae-selfcheck-agent-runner.md` (M2 spec draft v1)
  - this handoff
  - `.coverage` and `logs/` at the repository root. These are generated: coverage data and swebench `logs/build_images`. Spec A16 deletes them after approval.
- The OAuth token is stored at `~/.config/selfcheck/oauth_token` (mode 600). Never print or copy it; mount it read-only only.
- Docker leftovers from the M0 spike:
  - images `selfcheck-tools:spike` (SDK 0.2.165, used for SDK introspection) and `selfcheck-derived:django-11400`
  - the stopped container `selfcheck-proxy`, which has no `selfcheck.proxy` label, so `ensure_egress` recreates it
  - network `selfcheck-int` (internal)
- Instance images present: the 6 pool instances and 3 pilots (`pytest-dev__pytest-5787`, `django__django-11400`, `sympy__sympy-18199`). Pool Python is 3.8–3.9; pilot django-11400 is 3.6. Every image has user `nonroot` (UID 1000), and no repository has `AGENTS.md` or `CLAUDE.md`.
- Host: Docker VM has 10 CPUs and 8 GB; 36 GiB disk free; images use about 25 GB.
- M0 prototypes, for reference only: the session scratchpad `/private/tmp/claude-501/-Users-hwansu-tools-harness/ec87a001-7d0a-4134-996c-a7bc6803d9f1/scratchpad/m0/` holds `tools/Dockerfile`, `derived/{Dockerfile,python3,env.sh,install_harness.sh,spike_live.py}`, `proxy/squid.conf` and `out/live1,live2` message logs. It may vanish on reboot. The spec does not depend on it.

## Failed Attempts
| attempt | failure evidence | cause |
| --- | --- | --- |
| `docker run … sweb.eval.arm64.$id:latest` in a zsh loop | docker looked for `…-9602atest:latest` | verified: zsh applies the `:l` history modifier to `$id:latest`; write `${id}:latest` |
| Reading M0 live-spike conclusions from the conversation summary | the summary held only image and gold facts | verified: the live results were only in tool output; recovered from `m0/out/live*/messages.jsonl` and the squid access log, now recorded in spec ledger row M0 |

## Next Step
1. Re-present the approval brief for spec v1. Briefs live only in chat, so rebuild it from the spec's Assumptions A4–A17 and the Quality Requirements. Brief v1 listed no Ask items; every Decided item is an A row.
2. On approval:
   - mark the A rows `brief v1 — approved`, or apply vetoes as a v2 amendment;
   - set `status: active` and run `python3 .harness/bin/spec_lifecycle.py start --spec agent-docs/specs/3a7ecc520d8871ae-selfcheck-agent-runner.md --run-id 3a7ecc520d8871ae`;
   - then emit telemetry `start`.
3. Dispatch implementer and test-implementer in parallel on the same spec version. Give the implementer the M0 facts in ledger row M0, and tell it that SDK option names and message classes match 0.2.165. It can introspect them with `docker run --rm --network none --entrypoint /opt/selfcheck-py/venv/bin/python selfcheck-tools:spike -c …`.
4. Run the Test command under `perl -e 'alarm 3600; exec @ARGV' …`, because macOS has no `timeout`. Never run Docker tests concurrently with other Docker work.
5. Run the live smoke R1 once (`SELFCHECK_LIVE=1`). It uses subscription quota.

## Open Questions
- Pool minimum-mutant criterion: django-15731 has 1 mutant and astropy-14365 has 4. This affects M3 reporting, not M2.
- Whether to disable Docker Desktop Resource Saver or idle shutdown. `docker_exec` already waits through engine restarts.
- When to commit M2. Commit only when the user asks.

## Spec
`agent-docs/specs/3a7ecc520d8871ae-selfcheck-agent-runner.md`, version 1, status `draft`, run ID `3a7ecc520d8871ae`. Approval brief v1 was presented and not yet answered. Lifecycle start and telemetry start have not run.

## Execution Ledger
- Findings: none (no implementation or verification yet).
- Evidence: M0 spike facts (spec ledger row M0); SDK 0.2.165 introspection — `effort` ∈ low/medium/high/xhigh/max, `RateLimitInfo.status` ∈ allowed/allowed_warning/rejected, ResultMessage carries `api_error_status`, `model_usage`, `session_id`; ClaudeAgentOptions has `resume`, `strict_mcp_config`, `task_budget`.
- Fuzz: none declared. Mutations (hand and tool): none run.
- Correction batches: 0. Verifier invocations: 0 of 2.

# selfcheck M2 (agent runner) stopped at the verifier limit with one open evidence gap (EG12)

## Goal
"test-quality-audit-findings handoff 체크해보고. 우리도 이 하네스의 검증 장치를 만들어야 할 것 같아. SWE-bench처럼." The user wants a reliable self-check test bed. M2 is the agent runner. The user resumed it with "selfcheck M2(에이전트 실행기)를 이어서 진행해줘 … workflow-approach로 재개해."

User constraints for this work:
- Never print or copy the OAuth token (`~/.config/selfcheck/oauth_token`); mount it read-only only.
- Never run Docker tests concurrently with other Docker work.
- Use perl alarm instead of `timeout` on macOS.
- Run the live smoke only once, because it uses subscription quota.
- Commit only when the user says so.

## State
- Branch `selfcheck-m1`, HEAD `633caab42ae1fefc838ace7ff909939bc63786ef` (= base_commit). M2 is uncommitted.
- Implementation, all uncommitted:
  - Modified: `selfcheck/{__main__,config.json,docker_exec,requirements.txt,swe}.py`.
  - New: `selfcheck/{images,run,extract,manifest}.py`, `selfcheck/agent/`, `selfcheck/docker/`, `selfcheck/fixtures/project_defs.json`.
- Tests, all new and uncommitted under `selfcheck/tests/`: `agent_fakes.py`, `test_{user_sim,driver,shim,extract,manifest,run,cli_run,docker_agent,live_smoke,images,swe_build,docker_seam}.py`.
- Last Test command run: exit 0, 587 tests (7 live tests skipped), branch coverage 96%, token count 0 in the log, no agent container left.
- Docker state:
  - Images `selfcheck-tools:d8f469b7f426` and `selfcheck-agent.arm64.pytest-dev__pytest-5787:c8b123095310` exist.
  - Network `selfcheck-int` and container `selfcheck-proxy` (labelled) exist.
- Mutation tooling, outside the repo:
  - Scripts `~/.harness/selfcheck/mut/{hm.py,mm.py,plan.json,plan-docker.json}`.
  - Logs `~/.harness/selfcheck/logs/mm1*.jsonl` and `mm2-docker.jsonl`.
- Wrapper for long runs: run the command in its own process group and kill the group on alarm. Plain `perl alarm` on `uv` leaves grandchildren running (ledger T11). The wrapper source is in ledger T12; a copy was at session scratchpad `pgtimeout.pl`.

## Failed Attempts
| attempt | failure evidence | cause |
| --- | --- | --- |
| Test command under `perl -e 'alarm N; exec @ARGV' uv run …` | alarm fired after 62 tests; `docker build` hung at `resolve docker.io/library/<image>@sha256:…`; `sh`, the test python and `buildx` survived the alarm | verified: Docker Desktop BuildKit fault (cleared by restart, T12); alarm on `uv` does not reach grandchildren |
| mutmut rerun with `unittest -q discover …` | every mutant "failed" in 0.0 s | verified: `-q` before `discover` makes unittest read `discover` as a test name (MM1-r1) |
| Running modules from a zsh loop as `$mods` | load error in 0 s | verified: zsh does not word-split unquoted variables |
| Verifier invocation 2 | retry: EG12 | verified by hand mutations M11 (resume ignores the manifest and uses `git rev-parse HEAD`) and M12 (resume drops `install`); both survive `test_run` + `test_extract` |

## Next Step
1. Start a new workflow-approach run that continues this spec's content: the archived spec in `agent-docs/spec-logs/`, copied to a new run id.
2. Close EG12 with one VO9 R3 test. Use a fake container HEAD that differs from the stored `start_commit`, a non-default stored `install`, and a current repo commit that differs from `params.json` `selfcheck_commit`. Expect the resumed manifest and prediction to carry the stored values. Re-run M11/M12 to confirm detection.
3. Decide on ADV-E: either re-run the ~43 declared offline mutmut survivors from MM1-r2 with the full offline suite, or record them as unrun.
4. Run R3 (the FR17 review) and record its output.
5. Run the live smoke R1 once: `SELFCHECK_LIVE=1 python -m unittest selfcheck.tests.test_live_smoke` in the `uv run` environment, haiku-5-5, medium effort, 45 min per arm, `sphinx-doc__sphinx-9602`.
6. Get a fresh verifier pass.

## Open Questions
- Whether to strengthen the squid probes beyond QR2. ADV-A: `CONNECT api.anthropic.com:80` and plain GET to the allowed host are not exercised.
- Pool minimum-mutant criterion (django-15731 has 1 mutant, astropy-14365 has 4). This affects M3 reporting.
- When to commit M1/M2: only when the user asks.

## Spec
`agent-docs/spec-logs/3a7ecc520d8871ae-selfcheck-agent-runner.md`, version 6, status `limit`, run ID `3a7ecc520d8871ae`.

## Execution Ledger
- **Findings**
  - Closed: F1–F6, G1–G3, EG1–EG11, IMP-4, and mm031 (by VO19 DX11).
  - SC1–SC5 were decided in v5.
  - Open: EG12 (blocking; VO9 R3 resume sourcing of `start_commit`, `install`, `selfcheck_commit`).
  - Advisory: ADV-A through ADV-E, plus the undeclared mutants mm007, mm008, mm026, mm028, mm033, mm119, mm126, mm204, mm239.
- **Evidence**: verifier 2 accepted or retained every obligation except VO9 (EG12). VO16 has its procedure accepted; its outcome was not run.
- **Hand mutations**
  - M1–M10: all detected after corrections (H2).
  - M11 and M12: survived, which confirms EG12.
- **mutmut**
  - 300 sampled, seed 1.
  - MM1: 205 killed, 89 survived, 6 timeout.
  - The offline survivors were re-run with the full suite (MM1-r2): 1 killed.
  - The 45 Docker-path survivors were re-run with Docker runners (MM2): 39 killed, 6 survived. Of those six, triage found 1 equivalent, 4 undeclared, and 1 declared (mm031, now detected).
  - Equivalents, rechecked and none overturned: mm001, mm002, mm063, mm094, mm100, mm121, mm201.
- **Fuzz**: none declared.
- **Counters**: 5 correction batches; 2 of 2 verifier invocations.

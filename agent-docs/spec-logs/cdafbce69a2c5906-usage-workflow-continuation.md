---
version: 2
run_id: cdafbce69a2c5906
status: complete
base_commit: e130b49055b0afc8b117f923066217674273ae11
max_verifier_invocations: 2
handoff: none
---

# User Intent
| id | stakeholder | intention | observable goal |
| --- | --- | --- | --- |
| UI1 | harness maintainer | workflow를 이어가는 요청(이해 단계 답변, brief 승인, 중간 결정)이 "호출 안 됨"으로 집계되지 않게 한다 | 요청마다 workflow_state(start/continue/none)와 run_id가 출력되고, continue 요청은 used/misfire/missed/correct_skip에 들어가지 않음 |
| UI2 | harness maintainer | continue 요청에 대해 "요청이 workflow를 벗어났나?"를 별도로 측정 | label의 left_workflow 값이 continue 요청에 대해 left/stayed로 집계됨 |
| UI3 | harness maintainer | run이 사용자 turn을 몇 개 소비했는지 파악 | 보고서 runs 목록에 run별 continue_turns 출력 |

# Scope
In scope: `analytics/usage.py`의 FR4 확장(workflow_state, run_id), label 형식에 `left_workflow` 추가, confusion 확장, 보고서 `runs` 추가. 이전 spec(`agent-docs/spec-logs/cce0155b008eaf53-workflow-usage-analysis.md` v2)의 FR1–FR14는 아래에서 바꾼 부분 외에는 그대로 유지된다.
Out of scope: telemetry 형식, `workflow_marker.py`·`spec_lifecycle.py`·SKILL.md 변경, Codex transcript, Jev 연동, verifier 결과를 run 종료 신호로 쓰기(사용자 결정: 종료 충분조건이 아니고 limit/handoff/aborted run에는 없음).

# Paths
Implementation: analytics/usage.py
Tests: analytics/tests/test_usage.py, analytics/tests/usage_fixtures/
Test command: /private/tmp/claude-501/-Users-hwansu-orca-workspaces-harness-fix/698b3fbc-5f91-449f-8c1d-415272f4c85d/scratchpad/venv/bin/python -m pytest analytics/tests/test_usage.py -q -p no:cacheprovider --cov=analytics.usage --cov-branch --cov-report=term-missing --cov-fail-under=90
Review evidence: RE1 — main이 이 세션 transcript가 들어 있는 `~/.claude/projects/-Users-hwansu-orca-workspaces-harness-fix/`로 CLI를 실행한다. 이 run(`cdafbce69a2c5906`)의 Skill 호출 요청이 start이고, 그 뒤 사용자 요청("1 ok …")이 같은 run_id의 continue이며, 그 이전 요청이 none인지 transcript를 직접 보고 확인해 기록한다.
Fuzzing: hypothesis, surface `extract_requests`(임의 텍스트/임의 JSON 줄, Bash command 임의 문자열 포함)와 `apply_labels`(임의 label 줄), oracle crash(예외 전파 없음) + property(모든 요청의 workflow_state ∈ {start, continue, none}; state가 none이면 run_id가 null; confusion의 used+misfire+missed+correct_skip+unlabeled = start/none 요청 수), seed 0, budget 300 examples per surface
Mutation tool: mutmut 3.x, 커밋하지 않는 임시 `setup.cfg`(paths_to_mutate=analytics/usage.py, tests_dir=analytics/tests/test_usage.py)로 `mutmut run`. base_commit 이후 바뀐 줄의 mutant만 triage 대상이고 표본 상한은 없음(전체), seed 해당 없음, survival threshold 40%

# Signatures
usage.extract_requests(path: Path) -> tuple[list[dict], int] | None   # 시그니처 불변; 요청 레코드에 workflow_state, run_id 추가
usage.extract_runs(requests: list[dict]) -> list[dict]   # 한 파일의 요청 목록(extract_requests 결과)에서 run 요약 목록
usage.apply_labels(requests: list[dict], labels_path: Path) -> dict   # 시그니처 불변; 각 request에 warranted, left_workflow 추가
usage.build_report(transcripts_root: Path, telemetry_dir: Path, labels_path: Path | None) -> dict   # 출력에 "runs" 추가
CLI: 불변

# Functional Requirements
| id | requirement | priority | source |
| --- | --- | --- | --- |
| FR4a | invocation과 invoked는 이전 FR4 그대로 유지한다(하위 호환) | must | UI1 |
| FR15 | 닫는 명령 = 턴(이전 FR3) 안 assistant content의 tool_use 중 name=="Bash"이고 input.command가 str이며 `workflow_marker.py end` 또는 `spec_lifecycle.py archive` 부분 문자열을 포함하는 것 | must | UI1 |
| FR16 | workflow_state는 한 transcript 파일 안에서 요청 순서대로 정한다. 열린 run이 없을 때: invocation이 null이 아니면 start(새 run을 연다), 아니면 none. 열린 run이 있을 때: invocation이 null이 아니면 start(이전 run은 명령 없이 닫히고 새 run을 연다), 아니면 continue. 턴에 닫는 명령(FR15)이 있으면 그 요청은 자기 state를 유지하고, 그 턴이 끝난 뒤 run이 닫힌다. 파일 끝에서 열린 run은 명령 없이 닫힌다. 파일 사이에는 run이 이어지지 않는다 | must | UI1 |
| FR17 | run_id: run에 속한 요청들의 턴에서, Bash tool_use input.command 중 `workflow_marker.py` 또는 `spec_lifecycle.py`를 포함하는 command에 처음 나타나는 `--run-id <값>` 또는 `--run-id=<값>`의 값(공백·따옴표가 아닌 문자의 연속, 비어있지 않음). 같은 run의 모든 요청(start, continue)에 같은 값을 넣는다. 없으면 null. none 요청은 null | must | UI1,UI3 |
| FR15a | 요청 레코드에 "closes_run": bool 필드를 추가한다. 그 요청의 턴에 닫는 명령(FR15)이 있으면 true. workflow_state가 none인 요청에서도 명령이 있으면 true이지만 run을 닫지 않는다 | must | UI3 |
| FR18 | extract_runs: 각 run에 대해 {session_id, run_id, start_request_index, continue_turns(continue 요청 수), closed_by_command(bool: run의 마지막 요청의 closes_run 값). extract_runs는 공개 필드(session_id, request_index, workflow_state, run_id, closes_run)만 읽는다}. 요청 순서대로 | must | UI3 |
| FR19 | build_report 출력에 "runs": 파일 순서(FR1)대로 각 파일의 extract_runs 결과를 이어 붙인 목록을 추가한다. 다른 키는 이전 FR13 그대로 | must | UI3 |
| FR11a | label 줄은 {session_id: str, request_index: bool 아닌 int ≥ 0}에 더해 warranted와 left_workflow 중 최소 하나를 bool로 가져야 한다. 두 키 중 하나라도 있는데 bool이 아니면 invalid. 둘 다 없으면 invalid. 중복 키는 뒤의 줄이 이전 줄 전체를 대체하고 duplicate_labels 증가. unmatched_labels는 이전 정의 그대로 | must | UI2 |
| FR12a | 각 요청에 "warranted"(bool/null)와 "left_workflow"(bool/null)를 label 값 그대로 붙인다. start·none 요청은 warranted로 이전 FR12의 used/misfire/missed/correct_skip/unlabeled에 집계한다(warranted 없으면 unlabeled). continue 요청은 confusion["continue"] = {left, stayed, unlabeled}에 left_workflow로 집계한다(true→left, false→stayed, 없음→unlabeled). confusion["ignored_labels"] = 일치했지만 그 요청 state에 쓰이는 필드가 없는 label 수(start/none에 left_workflow만 있거나 continue에 warranted만 있는 경우) | must | UI1,UI2 |

# Errors
- Bash input.command가 str이 아니거나 input이 dict가 아님 — 닫는 명령/run_id 없음으로 취급, 예외 없음 — 다른 판정 정상
- `--run-id` 뒤에 값이 없음 — 그 occurrence 무시, 이후 command에서 계속 찾음 — 예외 없음
- label 형식 오류(FR11a) — invalid_labels 1 증가 — 다른 label 정상
- 이전 spec Errors 전 행 유지

# Cases
| id | level | input / state | expected result |
| --- | --- | --- | --- |
| C20 | normal | 요청: [일반, Skill 호출, 답변, 승인(턴에 `workflow_marker.py end --run-id abc`)] , 이후 [일반] | none, start, continue, continue, none; run_id abc가 start·continue 3개에; runs=[{start 1, continue_turns 2, closed true, run_id abc}] |
| C21 | normal | slash 호출 후 닫는 명령 없이 파일 끝 | start, continue…; closed false |
| C22 | edge | 열린 run 중 다시 Skill 호출 | 새 요청 start, 이전 run closed false, 두 run 각각 |
| C23 | boundary | 닫는 명령이 start 요청 자기 턴에 있음 | start, 다음 요청 none, continue_turns 0 |
| C24 | edge | `spec_lifecycle.py archive --spec X --status complete`(run-id 없음)로 닫힘, run-id는 앞의 `spec_lifecycle.py start --run-id=r1`에서 | run_id r1, closed true |
| C25 | edge | `--run-id`가 workflow_marker/spec_lifecycle이 아닌 command에만 있음; `--run-id` 뒤 값 없음 | run_id null |
| C26 | edge | 두 transcript 파일; 첫 파일 끝에 열린 run | 둘째 파일 첫 요청 none |
| C27 | normal | label: start에 warranted true, continue에 left_workflow true/false/없음, none에 warranted false | used 1, correct_skip 1, continue {left 1, stayed 1, unlabeled 1} |
| C28 | edge | continue에 warranted만, none에 left_workflow만 | ignored_labels 2; continue unlabeled 1, unlabeled 1; 요청 필드 값 그대로 |
| C29 | error | label: 둘 다 없음; left_workflow가 "yes"; warranted bool + left_workflow 1 | 각각 invalid |
| C30 | boundary | 기존 형식 label(warranted만) 파일 | 이전 결과와 동일(continue 없는 transcript) |
| C31 | edge | 중복 키: 첫 줄 warranted, 둘째 줄 left_workflow | 둘째만 남음(warranted null), duplicate 1 |
| C32 | error | Bash input이 dict 아님 / command가 list | 예외 없음, 닫힘 없음 |

# Quality Applicability
| ISO/IEC 25010:2023 characteristic | applicable | rationale |
| --- | --- | --- |
| Functional suitability | yes | 분류·집계 정확성이 목적 |
| Performance efficiency | no | 오프라인 일회성 분석, 요청 수 선형 |
| Compatibility | yes | 기존 label 파일과 보고서 키 하위 호환 |
| Interaction capability | no | CLI 불변 |
| Reliability | yes | 깨진 transcript/label에서 죽지 않아야 함 |
| Security | no | 로컬 파일 읽기만, 새 입력 경로 없음 |
| Maintainability | yes | 분기 coverage |
| Flexibility | no | 대상 확장 없음 |
| Safety | no | 물리적 위해 없음 |

# Quality Requirements
| id | characteristic / subcharacteristic | target and context | measure method / inputs / unit | threshold and direction | evidence: automated, review, mutation | source |
| --- | --- | --- | --- | --- | --- | --- |
| QR1 | Compatibility / interoperability | 기존 label 파일과 기존 보고서 키 | 이전 spec Cases의 기존 테스트 통과 수 / 전체, % | 100, 높을수록 | automated | UI1 |
| QR2 | Reliability / fault tolerance | 임의 transcript·label 줄 | hypothesis 위반 수 | 0, 낮을수록 | automated (fuzz) | UI1 |
| QR3 | Maintainability / testability | analytics/usage.py | coverage.py branch coverage, % | ≥ 90, 높을수록 | automated (Test command) | UI1 |

# Verification Obligations
| id | parent requirement/Case ids | variant and target surface | test layer and selection policy | ISO/IEC/IEEE 29119-4 technique | coverage items | coverage target | observation and expected result | evidence procedure |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| VO20 | FR16,C20–C23,C26 | extract_requests workflow_state | unit, fixture transcript | state transition | 전이: none→none, none→start, start→continue, continue→continue, (열림)→start 재호출, 닫는 명령→none, 자기 턴 닫힘, 파일 끝, 파일 경계 | 100% | state 목록 기대값 | pytest |
| VO21 | FR15,FR15a,FR17,C20,C24,C25,C32 | run_id·닫는 명령 판정 | unit | equivalence partitioning | `--run-id x`, `--run-id=x`, 비대상 command, 값 없음, archive 닫힘, end 닫힘, 비-str command, 비-dict input, 비-Bash tool | 100% | run_id/closed 기대값 | pytest |
| VO22 | FR18,FR19,C20–C22,C26 | extract_runs, build_report runs | unit+integration(build_report) | equivalence partitioning | 닫힌 run, 안 닫힌 run, 재호출 분할, 여러 파일 순서 | 100% | runs 기대값 | pytest |
| VO23 | FR11a,C29,C31 | label 파싱 | unit | decision table | (warranted 없음/bool/비bool)×(left 없음/bool/비bool) 9칸 + 중복 대체 | 100% | invalid/duplicate/필드 값 | pytest |
| VO24 | FR12a,C27,C28 | apply_labels 집계 | unit | decision table | state(start/none/continue)×label(warranted만/left만/둘 다/없음) 12칸 | 100% | confusion·continue·ignored 기대값 | pytest |
| VO25 | FR4a,QR1,C30 | 하위 호환 | unit | equivalence partitioning | 기존 테스트 전부, 기존 label 파일 | 100% | 기존 기대값 불변 | pytest |
| VO26 | QR2 | extract_requests, apply_labels | unit, hypothesis | random | 300 examples × 2 surface | none — random | 예외 없음, Fuzzing property | pytest (hypothesis, seed 0) |
| VO27 | QR3 | analytics/usage.py | Test command | branch testing | coverage.py 분기 | 90% | --cov-fail-under | Test command |
| VO28 | UI1 | 실제 transcript | review | scenario | RE1 | none — review | RE1 기대값 | RE1 |

# Assumptions and Defaults
| id | decision | evidence and uncertainty | brief v<n> — approved / vetoed → <answer> / user answer |
| --- | --- | --- | --- |
| A1 | option B, 필드명 left_workflow | handoff Open Questions | user answer |
| A2 | 열린 run은 다음 Skill 호출이나 세션(파일) 끝에서 닫힘 | handoff Open Questions | user answer |
| A3 | 닫는 신호는 end/archive 명령, verifier pass 아님 | SKILL.md step 8/9 | user answer |
| A4 | Skill 호출 이후 이해 단계 답변은 continue | Skill turn이 이해 단계를 시작 | user answer |
| A5 | continue 집계는 전체 합계, run별로는 continue_turns만 | 사용자가 위임 | user answer (as you choose) |
| A6 | 닫는 명령이 있는 turn은 그 run에 포함(continue/start), 다음 turn부터 none | 명령은 assistant가 turn 안에서 실행 | brief v1 — approved |
| A7 | run_id는 workflow_marker/spec_lifecycle command에서만 추출 | 다른 도구의 --run-id 오탐 방지 | brief v1 — approved |
| A8 | 도구(pytest, pytest-cov, hypothesis, mutmut)는 scratchpad venv에만 설치하고 저장소에 의존성 추가 안 함 | 로컬 python3에 pytest 없음 | brief v1 — approved |
| A9 | RE1은 원래 클라우드 세션 transcript 대신 이 세션 transcript로 수행 | 원래 transcript(/home/user/harness)는 로컬에 없음 | brief v1 — approved |

# Traceability
| requirement id | Case ids | obligation ids | evidence procedure |
| --- | --- | --- | --- |
| FR4a | C30 | VO25 | pytest |
| FR15,FR15a,FR17 | C20,C24,C25,C32 | VO21 | pytest |
| FR16 | C20–C23,C26 | VO20 | pytest |
| FR18,FR19 | C20–C22,C26 | VO22 | pytest |
| FR11a | C29,C31 | VO23 | pytest |
| FR12a | C27,C28 | VO24 | pytest |
| QR1 | C30 | VO25 | pytest |
| QR2 | — | VO26 | hypothesis |
| QR3 | — | VO27 | Test command |
| UI1 | — | VO28 | RE1 |

# Workflow Control
| item | value |
| --- | --- |
| correction batches used | 2 |
| verifier invocations | 2 |
| open finding ids | none (advisory A-1 leading-quote run-id, A-2 ignored_labels fuzz oracle remain) |

Audit state (one entry per obligation; retain prior decisions in the execution ledger):
| obligation id | spec version | evidence references and revision | accepted / open / invalidated / pending | rationale and mutation outcome | dependencies and reopening evidence |
| --- | --- | --- | --- | --- | --- |
| VO20–VO27 | 2 | analytics/tests/test_usage.py (220 passed, branch 99.58%) | accepted | verifier r2 pass; H1–H10 detected; mutmut 9 changed-line survivors dispositioned | req()/full_confusion shared |
| VO28 | 2 | RE1: this session transcript — req0 none, req1 start cdafbce69a2c5906, req2–4 continue same run_id, run open (closing command not yet run) | accepted | — | — |

Execution ledger (append attempts; preserve failed approaches):
| attempt | finding / failure signature | cause hypothesis | changed approach / new evidence | result / disposition |
| --- | --- | --- | --- | --- |
| 1 | implementer FR18 challenge: closed_by_command not derivable from public fields | verified: v1 public fields lacked close signal | spec v2 FR15a closes_run | amended, both roles redispatched |
| 2 | test-implementer intent gaps: quoted --run-id, null field value, both-field ignored rule, close+reinvoke same turn, missing workflow_state | spec text decides: quotes excluded from value chars; null is non-bool → invalid; ignored only when the state's field is absent; reinvoke opens new run then close applies to it; missing workflow_state outside declared inputs | rejected as challenges, no amendment | Test command 204 passed |
| 3 | verifier r1 retry: F1 quote-adjacent run-id value untested; F2 close detection partial-match untested; F3 null/0/1 non-bool labels untested (VO21, VO23 open; others accepted) | evidence gaps (verifier reading) | correction batch 1 to test-implementer | fixed: 216 passed |
| 4 | hand mutations H1–H10 (strongest classes from verifier r1: quote capture, close split, null-as-absent, reinvoke-as-continue, none-request close leak, last run-id wins, run_id first-member only, closed_by any, ignored always, continue in confusion) | — | seed.py backup/restore one at a time | all detected by intended tests; H5 first probe was a no-op (inconclusive), re-probed as previous-turn close leak → detected |
| 5 | mutmut 3.8.0: 876 mutants in usage.py, 845 killed, 31 survived (3.5%); 9 on changed lines triaged: 7 equivalent (M1–M7, default overwritten or undeclared hand-built inputs; main rechecked, 0 overturned), 2 declared (M8 ignored_labels accumulation, M9 continue counter accumulation); 22 on unchanged lines out of scope | evidence gap | correction batch 2 | fixed: 220 passed; M8, M9 re-injected → killed |
| 6 | fuzz VO26: 300×2 derandomized, 0 violations | — | — | accepted |
| 7 | verifier r2 pass: F1–F3 closed, VO21/VO23/VO24 re-audited accepted | — | — | complete |

# Version Log
## v1
- Initial spec, resolving handoff `agent-docs/handoff/4e61454e6935d1cc-usage-analysis-workflow-continuation.md` with option B.
## v2
- FR15a: public request field `closes_run`, and extract_runs reads only public fields. Implementer challenge: closed_by_command could not be derived from the v1 public fields.

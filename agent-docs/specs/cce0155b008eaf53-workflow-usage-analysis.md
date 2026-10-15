---
version: 2
run_id: cce0155b008eaf53
status: active
base_commit: 51459c5f6a83bc07a3f5f187785c9792e5813908
max_verifier_invocations: 2
handoff: none
---

# User Intent
| id | stakeholder | intention | observable goal |
| --- | --- | --- | --- |
| UI1 | harness maintainer | workflow-approach가 실제 사용자 요청 단위로 언제 호출되는지 파악 | 명령 하나로 Claude transcript의 사용자 요청별 호출 여부/서브에이전트/spec·handoff 쓰기 목록이 JSON으로 출력 |
| UI2 | harness maintainer | workflow run이 어떤 경로(케이스)로 진행되는지 빈도로 파악 | telemetry run 이벤트 순서별 variant와 빈도·compliance 결과 출력 |
| UI3 | harness maintainer | 오발동/누락을 외부 판정(수기 또는 Jev 같은 분류기)과 결합해 측정 | 라벨 파일을 주면 used/misfire/missed/correct_skip 표 출력 |

# Scope
In scope: 새 모듈 `analytics/usage.py`(표준 라이브러리 + 기존 `analytics.compliance`만 사용)와 `python3 -m analytics.usage` CLI. Claude Code transcript만 대상.
Out of scope: Codex transcript(사용자 결정), 분류기/LLM/네트워크 호출, 실시간 훅, 대시보드 API·프런트엔드, harness payload·telemetry 생산 측 변경, 기존 analytics 모듈의 동작 변경.

# Paths
Implementation: analytics/usage.py
Tests: analytics/tests/test_usage.py, analytics/tests/usage_fixtures/
Test command: cd /home/user/harness && python3 -m pytest analytics/tests/test_usage.py -q -p no:cacheprovider --cov=analytics.usage --cov-branch --cov-report=term-missing --cov-fail-under=90
Review evidence: RE1 — main이 이 세션의 실제 transcript(`~/.claude/projects/-home-user-harness/`)와 `~/.harness/telemetry`로 CLI를 실행해 human 요청 수와 workflow-approach 호출 요청이 transcript 수기 확인과 일치하는지 기록
Fuzzing: hypothesis (test-implementer가 작성), surface `extract_requests`와 `mine_variants`에 임의 텍스트/임의 JSON 값 줄로 된 파일 입력, oracle crash(예외 전파 없음) + property(skipped_lines ≤ 비어있지 않은 줄 수), seed 0, budget 300 examples per surface
Mutation tool: mutmut 3.8.0 — 커밋하지 않는 임시 `setup.cfg`(`[mutmut]` paths_to_mutate=analytics/usage.py, tests_dir=analytics/tests/test_usage.py)로 `mutmut run`; 단일 파일이라 표본 상한 없음(전체), seed 해당 없음; survival threshold 40%

# Signatures
usage.extract_requests(path: Path) -> tuple[list[dict], int] | None   # (요청 레코드들, skipped_lines); 읽을 수 없거나 UTF-8이 아니면 None
usage.mine_variants(telemetry_dir: Path) -> tuple[list[dict], int, int]   # (variant 목록, skipped_lines, skipped_files)  [v2: skipped_files 추가]
usage.apply_labels(requests: list[dict], labels_path: Path) -> dict   # 각 request에 "warranted" 추가, confusion dict 반환; 읽기 실패 시 OSError/UnicodeDecodeError 전파
usage.build_report(transcripts_root: Path, telemetry_dir: Path, labels_path: Path | None) -> dict
usage.main(argv: list[str] | None = None) -> int
CLI: python3 -m analytics.usage [--transcripts DIR] [--telemetry DIR] [--labels FILE]

# Functional Requirements
| id | requirement | priority | source |
| --- | --- | --- | --- |
| FR1 | 대상 파일은 `<transcripts_root>/<project>/<name>.jsonl`(깊이 정확히 2)만이다. `subagents/` 등 더 깊은 파일은 제외. 파일 순서는 경로 문자열 오름차순 | must | UI1 |
| FR2 | human 요청 = `type == "user"`이고 `isSidechain`·`isMeta`가 참이 아닌 레코드 중: `origin` 키가 dict이면 `origin.kind == "human"`인 것; `origin` 키가 없으면 content가 str이거나 text 블록을 1개 이상 갖고 tool_result 블록이 없으며, 프롬프트 텍스트(FR6)가 `<task-notification>`, `<local-command-`, `Another Claude session sent a message` 중 하나로 시작하지 않는 것 | must | UI1 |
| FR3 | 요청의 턴 = 그 human 요청 레코드 다음부터 다음 human 요청 직전(또는 파일 끝)까지의 레코드. `isSidechain`이 참인 레코드는 턴 집계에서 무시 | must | UI1 |
| FR4 | invoked: 프롬프트 텍스트에 `<command-name>/workflow-approach</command-name>`가 있으면 invocation="slash"; 아니면 턴 안 assistant content의 tool_use 중 name=="Skill"이고 input.skill=="workflow-approach"가 있으면 "skill"; 둘 다 아니면 invocation=null. invoked = invocation is not null | must | UI1 |
| FR5 | subagents: 턴 안 name이 "Agent" 또는 "Task"인 tool_use를 input.subagent_type(비어있지 않은 str가 아니면 "general-purpose")별로 센 dict | must | UI1 |
| FR6 | 프롬프트 텍스트: content가 str이면 그대로, list면 type=="text"인 블록의 text를 "\n"으로 연결 | must | UI1 |
| FR7 | spec_writes/handoff_writes: 턴 안 name이 Write/Edit/MultiEdit/NotebookEdit인 tool_use의 input.file_path(없으면 notebook_path)가 `agent-docs/specs/`를 포함하면 spec_writes, `agent-docs/handoff/`를 포함하면 handoff_writes. 중복 제거, 최초 등장 순서 | must | UI1 |
| FR8 | 요청 레코드 필드: session_id(레코드의 sessionId str, 없으면 파일 stem), request_index(파일 내 human 요청 0부터), timestamp(레코드 timestamp 또는 null), cwd(레코드 cwd 또는 null), text, invoked, invocation, subagents, spec_writes, handoff_writes | must | UI1 |
| FR9 | mine_variants: telemetry_dir 바로 아래 `*.jsonl`(이름순, 줄순)에서 event가 workflow_start/workflow_phase/verifier_result/workflow_end이고 workflow_run_id가 비어있지 않은 str인 dict만 run별로 모은다. 토큰: workflow_start→"start", workflow_phase→phase 값, verifier_result→"verifier:<result>", workflow_end→"end:<status>". variant = 토큰을 " > "로 연결 | must | UI2 |
| FR10 | variant 항목: {variant, count, run_ids(오름차순), compliant, noncompliant, incomplete, reasons(오름차순 합집합)}; 각 run을 `analytics.compliance.evaluate`로 평가해 completed가 거짓이면 incomplete, compliant 참/거짓이면 각각 집계. 목록은 count 내림차순, 같으면 variant 오름차순 | must | UI2 |
| FR11 | apply_labels: 라벨 파일 각 비어있지 않은 줄은 {session_id: str, request_index: bool 아닌 int ≥ 0, warranted: bool}인 JSON 객체여야 하며 아니면 invalid_labels. 같은 (session_id, request_index) 키가 다시 나오면 뒤의 값이 이기고 duplicate_labels 증가. 일치하는 요청이 없으면 unmatched_labels | must | UI3 |
| FR12 | confusion = {used: warranted∧invoked, misfire: ¬warranted∧invoked, missed: warranted∧¬invoked, correct_skip: ¬warranted∧¬invoked, unlabeled, invalid_labels, duplicate_labels, unmatched_labels}. 라벨이 있는 요청에는 "warranted": bool, 없는 요청에는 "warranted": null이 추가됨 | must | UI3 |
| FR13 | build_report 출력: {"requests": [...], "variants": [...], "confusion": dict 또는 labels 미지정 시 null, "skipped_lines": transcript+telemetry 합, "skipped_files": 읽지 못한(OSError/UnicodeDecodeError) transcript 파일과 telemetry 파일 수}. requests는 파일 순서(FR1) 후 request_index 순 | must | UI1,UI2,UI3 |
| FR14 | CLI: 기본 --transcripts `~/.claude/projects`, --telemetry `~/.harness/telemetry`. 성공 시 stdout에 build_report 결과를 JSON 한 개(ensure_ascii=False)로 출력하고 0 반환. --labels 파일을 읽지 못하면 stderr에 경로를 포함한 한 줄 메시지, stdout 비움, 2 반환 | must | UI1 |

# Errors
- transcripts_root 또는 telemetry_dir 없음 — 해당 결과 빈 목록, 예외 없음 — 다른 결과는 정상
- 읽을 수 없거나 UTF-8이 아닌 transcript — extract_requests가 None, skipped_files 1 증가 — 다른 파일 정상
- 깨진 JSON 줄/비-dict JSON 줄(비어있지 않은) — skipped_lines 1 증가 — 앞뒤 줄 정상 처리
- content/input/origin 등 필드 타입이 기대와 다름 — 해당 필드 없는 것으로 취급, 예외 없음 — 레코드 나머지 처리 정상
- 열 수 없는 telemetry 파일(OSError) — 그 파일 건너뜀, skipped_files 1 증가 — 다른 telemetry 파일과 transcript 결과 정상, exit 0. 비-UTF-8 바이트는 대체 문자로 읽혀 해당 줄이 깨진 줄로 처리될 수 있음
- 라벨 줄 형식 오류 — invalid_labels 증가 — 다른 라벨 정상
- --labels 파일 읽기 실패 — stderr 메시지, exit 2, stdout 비어있음 — 아무 출력 파일도 쓰지 않음

# Cases
| id | level | input / state | expected result |
| --- | --- | --- | --- |
| C1 | normal | origin.kind=human 요청 3개, 두 번째 턴에 Skill(workflow-approach), Agent(implementer), Agent(subagent_type 없음), Write `agent-docs/specs/x.md` | 요청 3개; [1].invoked=true, invocation="skill", subagents={implementer:1, general-purpose:1}, spec_writes=[…/x.md]; [0],[2] invoked=false |
| C2 | normal | 프롬프트 `<command-name>/workflow-approach</command-name>` | invocation="slash" |
| C3 | edge | tool_result user 레코드, isMeta 레코드, origin.kind=task-notification, origin.kind=peer, isSidechain user | 요청 아님, 턴 경계 아님 |
| C4 | edge | origin 키 없는 구형 레코드: str content / text 블록 / tool_result 블록 / `<task-notification>` 시작 | 앞의 둘만 요청 |
| C5 | edge | Skill input.skill="other-skill", 다른 skill 다음 턴 | invoked=false |
| C6 | edge | 같은 spec 경로 Edit 2회 + handoff Write | spec_writes 1개, handoff_writes 1개 |
| C7 | normal | telemetry: run A,B 같은 순서(start>implement_test>verify>verifier:pass>end:complete), run C 다른 순서, run 없는 subagent_start, 다른 이벤트(verification) | variant 2개, 첫 항목 count=2 run_ids=[A,B] compliant=2; 무관 이벤트 제외 |
| C8 | normal | 라벨 4종 조합 + 미라벨 요청 | used/misfire/missed/correct_skip 각 1, unlabeled 1 |
| C9 | error | 라벨: request_index=true, -1, "0", warranted="yes", 키 누락, 깨진 JSON | invalid_labels=6 |
| C10 | edge | 같은 키 라벨 2회(false 다음 true), 존재하지 않는 세션 라벨 | 뒤 값 사용, duplicate_labels=1, unmatched_labels=1 |
| C11 | error | 깨진 JSON 줄, `[1,2]` 줄, 빈 줄이 섞인 transcript/telemetry | 빈 줄 제외 skipped_lines 정확, 나머지 정상 |
| C12 | error | 루트 없음, 비-UTF-8 transcript | 빈 결과 / skipped_files=1 |
| C13 | boundary | 깊이 1(`root/x.jsonl`), 깊이 2, 깊이 3(`root/p/s/subagents/a.jsonl`) | 깊이 2만 대상 |
| C14 | error | CLI --labels 없는 경로 | exit 2, stderr에 경로, stdout 빈 문자열 |
| C15 | normal | CLI 정상 실행 | stdout JSON 파싱 가능, exit 0, 한글 텍스트 비이스케이프 |
| C17 | error | telemetry 디렉터리 안 `*.jsonl` 파일 하나가 읽기 권한 없음(또는 open이 OSError), 다른 파일 정상 | 그 파일만 제외, skipped_files 1, CLI exit 0이고 stderr에 labels 메시지 없음 |
| C16 | boundary | human 요청 0개 파일 / 요청이 파일 마지막 레코드 | 요청 0개 / 빈 턴(invoked=false, 빈 집계) |

# Quality Applicability
| ISO/IEC 25010:2023 characteristic | applicable | rationale |
| --- | --- | --- |
| Functional suitability | yes | 집계 정확성이 목적 자체 |
| Performance efficiency | yes | 실제 transcript는 수십 MB까지 커짐 |
| Compatibility | no | 새 모듈, 기존 모듈·API 무변경 |
| Interaction capability | no | 개인용 CLI, JSON 출력만 |
| Reliability | yes | 깨진/형식 다른 로그에서 중단 없어야 함 |
| Security | yes | transcript는 민감 정보 포함; 외부 전송 금지 |
| Maintainability | yes | 이후 분류기·대시보드 연결 기반, 분기 커버리지 유지 |
| Flexibility | no | Codex 등 확장 요구 없음 |
| Safety | no | 물리적 위해 없음 |

# Quality Requirements
| id | characteristic / subcharacteristic | target and context | measure method / inputs / unit | threshold and direction | evidence: automated, review, mutation | source |
| --- | --- | --- | --- | --- | --- | --- |
| QR1 | Functional suitability / correctness | C1–C16 합성 fixture | 기대값과 다른 필드 수 | = 0 | automated, mutation | UI1–UI3 |
| QR2 | Performance efficiency / time behaviour | 합성 transcript 1개 20,000 레코드(요청 2,000개) + telemetry 5,000줄로 build_report | wall time, s | ≤ 3 s | automated | UI1 |
| QR3 | Reliability / fault tolerance | 임의 텍스트·임의 JSON 줄(fuzz) | 전파된 예외 수 | = 0 | automated(fuzz) | UI1 |
| QR4 | Security / confidentiality | analytics/usage.py | 네트워크 모듈(socket, http, urllib, ssl, requests, httpx) import 수(AST), 파일 쓰기 호출 | = 0 | automated | UI3 |
| QR5 | Maintainability / testability | analytics/usage.py | coverage.py branch coverage, % | ≥ 90 | automated (Test command) | UI1 |

# Verification Obligations
| id | parent requirement/Case ids | variant and target surface | test layer and selection policy | ISO/IEC/IEEE 29119-4 technique | coverage items | coverage target | observation and expected result | evidence procedure |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| VO1 | FR2,C1,C3,C4 | extract_requests 요청 판정 | unit, 모든 항목 | decision table | R1 origin=human, R2 origin 기타 kind, R3 isMeta, R4 isSidechain, R5 tool_result(무 origin), R6 str(무 origin), R7 text 블록(무 origin), R8 3개 접두사 각각(무 origin), R9 type≠user | 100% | 요청 여부와 request_index | pytest |
| VO2 | FR3,FR4,C1,C2,C5,C16 | invocation 판정 | unit | equivalence partitioning | slash, skill, other-skill, none, skill이 다음 턴에 있음, sidechain 안 Skill, 마지막 요청 빈 턴 | 100% | invocation 값 | pytest |
| VO3 | FR5,FR7,C1,C6 | subagents/writes 집계 | unit | equivalence partitioning | Agent typed, Task typed, untyped, specs 경로, handoff 경로, 무관 경로, 중복 경로, notebook_path | 100% | dict/list 기대값 | pytest |
| VO4 | FR1,FR8,FR13,C13 | build_report 파일 선택·레코드 필드 | integration | boundary value (3-value) | 깊이 1, 2, 3 | 100% | 깊이 2만, 필드 전부 존재, sessionId 없음→stem | pytest |
| VO5 | FR9,FR10,C7 | mine_variants | unit | equivalence partitioning | 동일 variant 2 run, 다른 variant, run 없는 이벤트, 비 workflow 이벤트, noncompliant run, incomplete run, 동률 정렬 | 100% | 항목/정렬 기대값 | pytest |
| VO6 | FR11,FR12,C8–C10 | apply_labels | unit | decision table + equivalence partitioning | 4개 cell, unlabeled, invalid 6종(C9), duplicate, unmatched | 100% | confusion 기대값과 warranted 필드 | pytest |
| VO7 | FR14,C14,C15 | CLI main | integration(subprocess 또는 main 직접 호출+capsys) | equivalence partitioning | 정상, labels 읽기 실패 | 100% | exit code, stdout/stderr | pytest |
| VO8 | Errors,C11,C12 | 오류 처리 | unit | equivalence partitioning | 깨진 줄, 비-dict 줄, 빈 줄, 루트 없음, 비-UTF-8, 잘못된 필드 타입(content=int, input=str, origin=str), 열 수 없는 telemetry 파일(C17) | 100% | 카운터와 예외 없음 | pytest |
| VO9 | QR2 | build_report 성능 | integration | boundary value (2-value) | 20,000 레코드 입력 1개 | 100% | ≤ 3 s | pytest |
| VO10 | QR3 | extract_requests, mine_variants | unit | random | hypothesis 300 examples × 2 surface, seed 0 | none — random | 예외 없음, skipped ≤ 비어있지 않은 줄 수 | pytest(hypothesis) |
| VO11 | QR4 | usage.py 소스 | unit | syntax | 금지 import 6종, open(... 'w'/'a') 호출 | 100% | 0개 | pytest(ast) |
| VO12 | QR5 | analytics/usage.py | Test command | branch testing | coverage.py 분기 | 90% | --cov-fail-under | Test command |
| VO13 | UI1 | 실데이터 | review | scenario | RE1 | none — review | 수기 확인과 일치 | RE1 |

# Assumptions and Defaults
| id | decision | evidence and uncertainty | brief v<n> — approved / vetoed → <answer> / user answer |
| --- | --- | --- | --- |
| A1 | Codex 제외 | 사용자 지시 "코덱스는 제외한다." | user answer |
| A2 | 출력은 CLI JSON까지; 대시보드 연결은 후속 | 결과 형태를 먼저 보고 결정하는 편이 되돌리기 쉬움 | brief v1 — approved |
| A3 | 라벨 형식 JSONL {session_id, request_index, warranted} | 분류기 연동 인터페이스가 됨(되돌리기 비용 있음) | brief v1 — approved |
| A4 | human 판정은 origin.kind 우선, origin 없는 구형 기록은 FR2 휴리스틱 | 현재 세션 transcript에서 origin.kind 확인; 구형 포맷 확인 불가 | brief v1 — approved |
| A5 | 요청 텍스트를 잘라내지 않고 전체 포함 | 분류기 입력으로 쓰기 위함; 출력이 커질 수 있음 | brief v1 — approved |
| A6 | 플러그인 접두사(`x:workflow-approach`) Skill 이름은 호출로 보지 않음 | 현재 설치 형태는 접두사 없음 | brief v1 — approved |
| A7 | 해석 기록: `isSidechain`/`isMeta`는 truthy 판정; dict가 아닌 origin은 "없음"으로 보고 FR2 휴리스틱 적용; content가 str/list가 아니면 text="" ; 누락·비문자열 phase/result/status는 `str()` 값으로 토큰화; run id가 유효하지 않은 workflow 이벤트와 라벨 파일 줄은 skipped_lines에 포함하지 않음; 깊이 2의 `*.jsonl` 디렉터리는 대상 아님; list/dict status는 compliance 평가 전 JSON 문자열화; telemetry 디렉터리 바로 아래 `*.jsonl` 이름의 디렉터리는 조용히 건너뜀(skipped_files 미포함) | reconcile 단계 양 역할 질의; Errors의 "타입 다르면 없는 것으로 취급"과 FR13 문구에서 도출 | contract-only (brief 항목 아님) |

# Traceability
| requirement id | Case ids | obligation ids | evidence procedure |
| --- | --- | --- | --- |
| FR1,FR8,FR13 | C13,C16 | VO4 | pytest |
| FR2 | C1,C3,C4 | VO1 | pytest |
| FR3,FR4 | C1,C2,C5,C16 | VO2 | pytest |
| FR5,FR6,FR7 | C1,C6 | VO3 | pytest |
| FR9,FR10 | C7 | VO5 | pytest |
| FR11,FR12 | C8,C9,C10 | VO6 | pytest |
| FR14 | C14,C15 | VO7 | pytest |
| Errors | C11,C12,C17 | VO8 | pytest |
| QR2 | — | VO9 | pytest |
| QR3 | — | VO10 | pytest(hypothesis) |
| QR4 | — | VO11 | pytest |
| QR5 | — | VO12 | Test command |
| UI1 | — | VO13 | RE1 |

# Workflow Control
| item | value |
| --- | --- |
| correction batches used | 1 |
| verifier invocations | 1 |
| open finding ids | F2, F3, F4, F5 |

Audit state (one entry per obligation; retain prior decisions in the execution ledger):
| obligation id | spec version | evidence references and revision | accepted / open / invalidated / pending | rationale and mutation outcome | dependencies and reopening evidence |
| --- | --- | --- | --- | --- | --- |
| VO1–VO12 | 2 | analytics/tests/test_usage.py (111 tests) | pending | F1 수정 후 VO5/VO8/VO10 증거 갱신(mine_variants 3-tuple) | VO8 reopened by F1, now re-evidenced |
| VO13 | 2 | RE1: 이 세션 transcript로 CLI 실행 — human 요청 6개, invoked는 '진행하자' 1개(skill); transcript 수기 확인과 일치 | accepted | main review | 실데이터 형식 변경 시 재검토 |

Execution ledger (append attempts; preserve failed approaches):
| attempt | finding / failure signature | cause hypothesis | changed approach / new evidence | result / disposition |
| --- | --- | --- | --- | --- |
| 1 | F1: 열 수 없는 telemetry 파일의 OSError가 build_report 밖으로 전파되어 main이 'cannot read labels'로 오보, exit 2 | main의 except가 build_report 전체를 감쌈 (verified: usage.py main/_read_runs 코드) | spec v2 Errors/C17 추가; implementer에 telemetry 파일 단위 skip, main은 labels 오류만 보고; test-implementer에 C17 테스트 | fixed: Test command 111 passed, branch coverage 98.33% (미커버: telemetry 디렉터리형 *.jsonl skip, list status 문자열화, __main__ 가드) |
| 2 | verifier #1 retry: F2 skipped_lines/skipped_files 합산을 같은 값(2+2, 1+1)으로만 검증; F3 FR14 기본 경로 미검증; F4 telemetry 비-UTF-8 바이트 미검증; F5 list/dict status 경로 미실행. mutmut 667개 중 57 생존(8.5%) | 테스트 증거 공백 (verified: verifier 감사, 생존 mutant `+=`→`=`, 기본 경로 문자열 변이) | test-implementer에 F2–F5 + mutant-triager declared 판정 전달 | pending |

# Version Log
## v2
- Contract-only: 열 수 없는 telemetry 파일 처리(Errors, C17, FR13 skipped_files 정의) 추가 — implementer 보고 #4에서 labels 오류 오보 결함(F1) 발견. 양 역할의 해석 질의를 A7로 기록.
## v1
- Initial draft.

---
version: 4
run_id: a21bca11396f6e60
status: complete
base_commit: 876b3a1972790877dc9e5548e95001e3c05c11db
max_verifier_invocations: 2
handoff: none
---

# User Intent
| id | stakeholder | intention | observable goal |
| --- | --- | --- | --- |
| UI1 | harness user | Claude Code가 커밋할 때 새 주석이 있으면 사용자에게 보고하게 한다 | staged diff에 새 주석이 있으면 pre-commit이 파일:줄 목록과 "에이전트는 사용자에게 보고하라" 문구를 stderr에 출력하고 커밋은 성공 |
| UI2 | harness user | PR에서 새 주석은 사람이 허가해야 통과 | 새 주석이 있는 PR의 체크는 `comments-approved` 라벨 없이 실패, 라벨이 있으면 통과 |
| UI3 | harness user | 승인 이후 새 push는 다시 허가가 필요 | `synchronize` 이벤트에서 라벨이 제거되고 그 실행은 라벨을 무시하고 판정 |

# Scope
In scope: `harness/git/warn_new_comments.py`의 staged 모드와 승인 게이트 모드, `harness/git/pre-commit`에서 경고 실행, `harness/ci/harness-comment-warning.yml`의 트리거/권한/라벨 제거/게이트, 0.25.0 버전과 마이그레이션 안내, README 해당 행, 테스트.
Out of scope: Claude Code PreToolUse 훅, `--no-verify`/`gh` 차단, branch protection 설정 자동화, 라벨 자동 생성, 주석 감지 패턴(`COMMENT_PATTERN`, `CODE_EXTENSIONS`) 변경, `verify_rules.py` 동작 변경.

# Paths
Implementation: harness/git/warn_new_comments.py, harness/git/pre-commit, harness/ci/harness-comment-warning.yml, harness/VERSION, installer/harness.py, README.md
Tests: tests/test_comment_gate.py, tests/test_installer.py, tests/test_telemetry.py, tests/test_workflow_markers.py, tests/test_session_metrics.py
Test command: uv run --with pytest --with hypothesis python -m unittest discover -s tests
Review evidence: RE2 — main이 README.md의 workflow 행과 hook 문단을 인용하고 G1–G4 판정을 Execution ledger에 기록. RE1 — main이 `harness/ci/harness-comment-warning.yml`을 읽고 트리거 types, permissions, synchronize 시 라벨 제거 단계의 `continue-on-error`, 게이트 단계의 approved 계산식이 FR5–FR8과 일치하는지 표로 기록(실제 GitHub 실행은 불가)
Fuzzing: none — 입력은 git diff 텍스트로, 기존 파서를 변경하지 않으며 fuzz 도구가 설치되어 있지 않음
Mutation tool: none — mutmut 미설치, 사용자가 이전 run에서 도구 설치 없이 hand mutation 8–10개로 대체하는 방식을 승인

# Signatures
warn_new_comments.py --staged    # pre-commit 모드: `git diff --cached`, 항상 exit 0
warn_new_comments.py <base-sha> <head-sha>    # 기존 경고 전용 모드, exit 0 (호환 유지)
warn_new_comments.py <base-sha> <head-sha> --approved yes|no    # 게이트 모드
changed_lines(base: str, head: str) -> list[tuple[str, int, str]]    (기존 유지)
staged_lines() -> list[tuple[str, int, str]]

# Functional Requirements
| id | requirement | priority | source |
| --- | --- | --- | --- |
| FR1 | `--staged`는 `git diff --cached --unified=0`의 추가 줄에 기존 감지 규칙(COMMENT_PATTERN, CODE_EXTENSIONS)을 적용한다 | must | UI1 |
| FR2 | `--staged`에서 감지가 있으면 stderr에 각 `path:line: content`와 "If you are an AI agent, report every added comment above to the user." 문구를 출력하고, 없으면 아무것도 출력하지 않는다. 종료 코드는 항상 0 | must | UI1 |
| FR3 | `harness/git/pre-commit`은 `verify_rules.py`보다 먼저 `warn_new_comments.py --staged`를 실행하며, 그 실패가 커밋을 막지 않는다 | must | UI1 |
| FR4 | 게이트 모드: 감지 있음 & `--approved no` → 기존 `::warning` 출력 + 요약 + exit 1. 감지 있음 & `--approved yes` → 출력 후 exit 0. 감지 없음 → exit 0 | must | UI2 |
| FR5 | 워크플로 트리거: `pull_request` types `opened, synchronize, reopened, labeled, unlabeled` | must | UI2, UI3 |
| FR6 | `synchronize`일 때 `comments-approved` 라벨 제거를 시도하며, 제거 실패(fork 토큰 읽기 전용, 라벨 없음 등)는 job을 실패시키지 않고 `::warning`을 남긴다 | must | UI3 |
| FR7 | approved = 이벤트 action이 `synchronize`가 아니고 PR 라벨에 `comments-approved`가 있음. 게이트 단계는 `--approved yes|no`로 이를 전달 | must | UI2, UI3 |
| FR8 | 워크플로 permissions: `contents: read`, `pull-requests: write`, `issues: write` | must | UI3 |
| FR9 | 버전 0.25.0, MIGRATIONS에 0.25.0 항목 추가. 안내: pre-commit 경고 추가, PR 체크가 라벨 없이는 실패, `comments-approved` 라벨 생성과 required check 지정은 저장소에서 직접 해야 함 | must | 작업 범위 3 |
| FR10 | README의 workflow 행 설명을 승인 게이트로 갱신 | should | 작업 범위 3 |

# Errors
- `--staged`에서 git 실행 실패(저장소 아님 등) — stderr에 한 줄 메시지, exit 0 — 커밋 계속
- pre-commit에서 python3 없음 — 기존 skip 메시지 — 커밋 계속
- 게이트 모드 `--approved` 값이 yes/no 외 또는 위치 인자 수 오류 — usage를 stderr, exit 2
- 라벨 제거 API 실패 — `::warning`, 단계 성공 처리 — 게이트는 approved=no로 판정

# Cases
| id | level | input / state | expected result |
| --- | --- | --- | --- |
| C1 | normal | staged `.py`에 `# note` 줄 추가, `--staged` | stderr에 `path:line: # note`와 에이전트 보고 문구, exit 0 |
| C2 | normal | staged 변경에 주석 없음 | 출력 없음, exit 0 |
| C3 | edge | 주석이 unstaged 상태로만 존재 | 감지 없음 |
| C4 | edge | 주석 줄이 비코드 확장자(`.md`) | 감지 없음 |
| C5 | error | 저장소 밖에서 `--staged` | stderr 메시지, exit 0 |
| C6 | normal | 실제 pre-commit 훅으로 주석 포함 커밋 | 커밋 성공, 경고 출력 |
| C7 | normal | 게이트: 주석 있음, `--approved no` | exit 1, `::warning` 출력 |
| C8 | normal | 게이트: 주석 있음, `--approved yes` | exit 0 |
| C9 | boundary | 게이트: 주석 없음, `--approved no` | exit 0 |
| C10 | error | `--approved maybe` | exit 2 |
| C11 | normal | 인자 2개(기존 모드), 주석 있음 | exit 0 |
| C12 | normal | 워크플로 파일 정적 검사 | FR5–FR8 충족 |
| C13 | normal | 0.24.0 설치본 update | 0.25.0 마이그레이션 안내 출력, 버전 기록 |

# Quality Applicability
| ISO/IEC 25010:2023 characteristic | applicable | rationale |
| --- | --- | --- |
| Functional suitability | yes | 경고/게이트 판정 정확성 |
| Performance efficiency | no | diff 1회 실행, 측정 의미 없음 |
| Compatibility | yes | 기존 2인자 호출 유지, 기존 pre-commit 동작 유지 |
| Interaction capability | yes | 에이전트가 읽을 수 있는 경고 문구 |
| Reliability | yes | pre-commit 경고 실패가 커밋을 막지 않음 |
| Security | yes | 쓰기 권한 범위, `pull_request_target` 미사용 |
| Maintainability | no | 단일 스크립트 확장, 별도 목표 없음 |
| Flexibility | no | 설치 대상 환경 변화 없음 |
| Safety | no | 물리적 위해 없음 |

# Quality Requirements
| id | characteristic / subcharacteristic | target and context | measure method / inputs / unit | threshold and direction | evidence: automated, review, mutation | source |
| --- | --- | --- | --- | --- | --- | --- |
| QR1 | Functional suitability / correctness | 게이트 결정표 | C7–C10 통과 비율 | 100%, 높을수록 | automated O3; mutation | UI2 |
| QR2 | Compatibility / co-existence | 기존 2인자 모드와 verify_rules 차단 | C11 및 verify_rules 위반 시 커밋 차단 유지 | 통과 | automated O2, O5 | 기존 동작 |
| QR3 | Interaction capability / recognizability | 경고 문구 | stderr에 보고 문구 문자열 존재 | 존재 | automated O1 | UI1 |
| QR4 | Reliability / fault tolerance | 경고 단계 오류 | C5에서 exit 0 | 0 | automated O1 | UI1 |
| QR5 | Security / integrity | 워크플로 | `pull_request_target` 부재, permissions 정확히 FR8 | 일치 | automated O4; review RE1 | Ask 1 (a) |

# Verification Obligations
| id | parent requirement/Case ids | variant and target surface | test layer and selection policy | ISO/IEC/IEEE 29119-4 technique | coverage items | coverage target | observation and expected result | evidence procedure |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| O1 | FR1, FR2, C1–C5, QR3, QR4 | `--staged` CLI, 임시 git 저장소 | integration, 전부 | equivalence partitioning | EP1 staged 주석, EP2 무주석, EP3 unstaged 주석, EP4 비코드 확장자, EP5 저장소 밖 | 100% | stderr 내용과 exit code | unittest |
| O2 | FR3, C6, QR2 | `harness/git/pre-commit` 실제 실행 (임시 저장소에 `.harness/` 복사, core.hooksPath) | end-to-end, 전부 | scenario | S1 주석 포함 커밋 성공+경고, S2 verify_rules 위반 시 차단 유지, S3 경고가 verify_rules 출력보다 먼저, S4 설치된 warn_new_comments.py가 비0으로 종료해도 커밋 성공, S5 PATH에 python3 없음 → 커밋 성공 + skip 메시지 | 100% | 커밋 존재 여부, stderr 순서 | unittest |
| O3 | FR4, C7–C11, QR1 | 게이트/기존 모드 CLI, 임시 저장소 커밋 2개 | integration, 전부 | decision table | D1 주석×no, D2 주석×yes, D3 무주석×no, D4 무주석×yes, D5 잘못된 값, D6 2인자 모드 주석, D7 위치 인자 수 오류(1개·3개) → exit 2 | 100% | exit code; 감지가 있는 D1·D2·D6은 stdout에 `::warning` 존재 | unittest |
| O4 | FR5–FR8, C12, QR5 | 워크플로 YAML 텍스트 | unit, 전부 | syntax | Y1 types 5종, Y2 permissions 3개, Y3 synchronize 조건부 제거 단계 + continue-on-error, Y4 approved 식이 action!=synchronize && 라벨 포함이며 `--approved` 인자와 같은 줄에서 `'yes' || 'no'` 순서로 매핑, Y5 `pull_request_target` 부재 | 100% | 텍스트/구조 매칭 | unittest + RE1 |
| O5 | FR9, C13 | installer update | integration, 전부 | scenario | M1 0.24.0→update 시 0.25.0 안내, M2 manifest 버전 0.25.0, M3 0.25.0 안내 본문에 `comments-approved`와 branch protection 안내 포함 | 100% | stdout, manifest | unittest |
| O6 | FR10 | README | review | error guessing | G1 행이 경고 전용 동작을 그대로 설명, G2 `comments-approved` 라벨 이름 누락, G3 커밋 시 경고(비차단) 누락, G4 새 push 시 라벨 제거 누락 | none — experience-based | README 해당 줄 인용과 G별 판정 | RE2 |

# Assumptions and Defaults
| id | decision | evidence and uncertainty | brief v<n> — approved / vetoed → <answer> / user answer |
| --- | --- | --- | --- |
| A1 | fork PR 라벨 제거 실패 시 경고 후 그 실행은 라벨 무시 | GITHUB_TOKEN 읽기 전용 | user answer |
| A2 | 라벨 이름 `comments-approved` | — | user answer |
| A3 | 기존 감지 규칙 그대로 재사용 | 오탐/누락 존재 | user answer (범위 밖) |
| A4 | 새 스크립트 대신 `warn_new_comments.py`에 모드 추가 | 감지 규칙 단일화 | brief v1 — approved |
| A5 | 승인 판정은 이벤트 payload 라벨 + action으로 계산(API 재조회 없음) | synchronize에선 무조건 no라 stale payload 영향 없음. fork에서 제거 실패 후 다른 이벤트 재실행 시 남은 라벨이 통과시킬 수 있음 | brief v1 — approved |
| A6 | permissions에 `issues: write`도 포함 | 라벨 REST 엔드포인트가 issues 경로 | brief v1 — approved |
| A7 | 라벨 생성과 required check 지정은 설치기가 하지 않고 안내만 | 외부 부작용 | brief v1 — approved |
| A8 | 경고 문구 영어 | 기존 하네스 메시지가 영어 | brief v1 — approved |
| A9 | 커버리지 도구·fuzz·mutation 도구 없음, hand mutation 8–10개 | 미설치 | brief v1 — approved |

# Traceability
| requirement id | Case ids | obligation ids | evidence procedure |
| --- | --- | --- | --- |
| FR1, FR2 | C1–C5 | O1 | unittest |
| FR3 | C6 | O2 | unittest |
| FR4 | C7–C11 | O3 | unittest |
| FR5–FR8 | C12 | O4 | unittest + RE1 |
| FR9 | C13 | O5 | unittest |
| FR10 | — | O6 | RE2 |

# Workflow Control
| item | value |
| --- | --- |
| correction batches used | 2 |
| verifier invocations | 2 |
| open finding ids | none |

Audit state (one entry per obligation; retain prior decisions in the execution ledger):
| obligation id | spec version | evidence references and revision | accepted / open / invalidated / pending | rationale and mutation outcome | dependencies and reopening evidence |
| --- | --- | --- | --- | --- | --- |
| O1–O6 | 4 | tests/test_comment_gate.py, RE1, RE2, H1 | accepted | verifier 2 pass; H1 10/10 killed; advisory: D1 summary 미검증, S3는 출력 순서로만 호출 순서 확인 | 없음 |

Execution ledger (append attempts; preserve failed approaches):
| attempt | finding / failure signature | cause hypothesis | changed approach / new evidence | result / disposition |
| --- | --- | --- | --- | --- |
| 1 | 기존 테스트 30개 실패: 최신 버전 0.24.0 하드코딩 기대값; test_session_metrics import 오류(hypothesis 미설치) | 버전 업 시 기존 테스트 기대값 갱신 필요(0.24.0 커밋 선례), Tests 경로 누락은 spec gap; import 오류는 기존 환경 문제 | Tests 경로 확장, Test command에 pytest·hypothesis 추가, test-implementer가 기대값 갱신 | v2+v3 갱신 후 399 OK |
| 2 | verifier 1 retry: F1 D2/D6가 `::warning` 미검증, F2 FR3 실패 비차단·python3 부재·인자 수 오류 미커버, F3 마이그레이션 본문 미검증, F4 O6 guessed defect·artifact 없음 | 증거 공백 + 커버리지 항목 누락(spec gap) | v4: S4, S5, D7, M3, Y4 강화, G1–G4·RE2 추가; test-implementer 보강 | 402 OK |
| RE1 | harness/ci/harness-comment-warning.yml 리뷰 | — | FR5 L5 `types: [opened, synchronize, reopened, labeled, unlabeled]`; FR8 L7–10 `contents: read`/`pull-requests: write`/`issues: write`; FR6 L20 `if: github.event.action == 'synchronize'`, L21 `continue-on-error: true`, L25 `gh api -X DELETE .../labels/comments-approved`, L26 `|| echo "::warning::..."`; FR7 L28 `--approved ${{ (github.event.action != 'synchronize' && contains(github.event.pull_request.labels.*.name, 'comments-approved')) && 'yes' || 'no' }}`; QR5 `pull_request_target` 없음 | 일치 |
| H1 | hand mutations 10개 (선정 이유: verifier 1 제안 중 각 FR의 핵심 결정 지점과 F1/F2/F3 공백을 직접 겨냥) | — | M1 worktree diff→EP1,EP3,S1,S3; M2 staged exit1→EP1; M3 문구 제거→EP1,S1,S3; M4 approved 무시→D1; M5 yes 조기 반환→D2; M6 잘못된 값=no→D5; M7 순서 역전→S3; M8 실패 전파→S4; M9 식 반전→Y4; M10 안내 누락→M3 | 10/10 killed, 원복 후 402 OK |
| RE2 | README.md 리뷰 | — | L33 "…`comments-approved` 라벨이 없을 때 실패하는 승인 게이트…(선택, 새 push 시 라벨 제거)"; L37 "새 주석은 커밋 시 경고만 출력하고 막지 않으며, PR 검사는 `comments-approved` 라벨이 없으면 실패합니다." G1 없음(경고 전용 표현 제거됨), G2 없음(L33, L37), G3 없음(L37), G4 없음(L33) | 통과 |

# Version Log
## v1
- Initial spec.
## v2
- Tests 경로에 버전 기대값을 가진 기존 테스트 3개 추가, Test command를 uv로 pytest·hypothesis 포함 실행으로 변경 (계약 변경; 기존 테스트 30개가 0.24.0을 최신으로 하드코딩, test_session_metrics가 hypothesis 필요).
## v3
- Tests 경로에 tests/test_session_metrics.py 추가 (test_version_is_0_24_0이 현재 버전을 하드코딩; 계약 변경).
## v4
- verifier 1 지적(F2, F4)에 따라 커버리지 항목 S4, S5, D7, M3, G1–G4와 RE2 추가, D1/D2/D6 `::warning` 관측과 Y4 매핑 검사 명시 (계약 변경).

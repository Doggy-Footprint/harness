---
version: 3
run_id: 5aee51c6eb1cf672
status: complete
base_commit: 01065b74bc07760247f4b21b8d061fe9b6201fe1
max_verifier_invocations: 2
handoff: none
---

# User Intent
| id | stakeholder | intention | observable goal |
| --- | --- | --- | --- |
| UI1 | harness 사용자 | 늦게 설치했거나 이전 버전에서 작성된 테스트를 일괄 점검하고, 기능 단위 handoff로 수정 계획을 남긴다 | `/test-audit [path]`로 유저만 호출 가능한 스킬이 설치된다 |
| UI2 | harness 사용자 | rule 기반 처리를 먼저 해 LLM이 읽는 토큰을 줄인다 | `test_scan.py`가 테스트 목록과 의심 신호를 JSON으로 낸다 |

# Scope
In scope: `harness/bin/test_scan.py` (결정론적 정적 스캔), `harness/skills/test-audit/` (SKILL.md, agents/openai.yaml), 0.18.0 migration 항목, VERSION.
Out of scope: 테스트 실행·coverage·mutation 자동화(스킬 절차가 담당), 스캔 결과 기반 자동 수정, Python 외 언어의 AST 수준 파싱.

# Paths
Implementation: harness/bin/test_scan.py, harness/skills/test-audit/SKILL.md, harness/skills/test-audit/agents/openai.yaml, installer/harness.py, harness/VERSION, AGENTS.md
Tests: tests/test_test_scan.py, tests/test_installer.py, tests/test_telemetry.py, tests/test_workflow_markers.py
Test command: python3 -m unittest discover -s tests
Review evidence: R1 — main이 SKILL.md를 FR7 체크리스트(8단계·no-edit·handoff 구조)와 대조하고 결과를 Execution ledger에 기록.
Fuzzing: none — 입력이 파일 트리이며 Python 파싱 실패 경로는 Case E2로 결정론적으로 검증.
Mutation tool: none — mutmut/cosmic-ray 미설치; 8–10 hand mutation으로 대체.

# Signatures
CLI: python3 .harness/bin/test_scan.py [PATH]   (PATH 기본값: 현재 디렉터리; stdout에 JSON 1개; exit 0, PATH 없음 → stderr 메시지 + exit 2)
scan(root: Path) -> dict

Output JSON:
{
  "root": str,
  "runner_candidates": [{"runner": str, "command": str, "evidence": str}],
  "files": [{"path": str(root 기준 posix), "language": str, "last_commit": str|null(ISO), "predates_harness": bool|null, "parse_error": bool, "tests": [{"name": str, "line": int, "flags": [str]}]}],
  "inventory": [str],
  "summary": {"files": int, "tests": int, "flags": {flag: int}}
}

# Functional Requirements
| id | requirement | priority | source |
| --- | --- | --- | --- |
| FR1 | 테스트 파일 탐지: python `test_*.py`/`*_test.py`; js/ts `*.test.{js,jsx,ts,tsx,mjs,cjs}`, `*.spec.{...}`, `__tests__/` 아래 동일 확장자; go `*_test.go`; rust `.rs` 중 `#[test]` 포함; java `*Test.java`/`*Tests.java`. `.git, node_modules, .venv, venv, __pycache__, dist, build, target, .harness, .agents, .claude, .codex` 디렉터리는 건너뜀 | must | plan |
| FR2 | 테스트 추출: python은 `ast`로 `test`로 시작하는 함수/메서드(클래스 내 포함); js/ts는 `it(`/`test(` (수식어 `.skip/.only` 포함, `xit`), go는 `func TestX(t *testing.T)`, rust는 `#[test]` 다음 `fn`, java는 `@Test` 다음 메서드. `line`은 함수/메서드/fn 선언 줄(어노테이션 `#[test]`/`@Test`와 선언이 같은 줄이어도 인식), js `name`은 `it`/`test` 첫 인자 제목 문자열. 비-Python 본문은 시작 줄부터 다음 테스트 시작 직전(또는 EOF)까지 | must | plan |
| FR3 | flags (테스트별, 정렬된 고유 목록): `skip`, `xfail`, `focused`(js `.only`/`fit`), `no_assert`, `empty`, `sleep`, `heavy_mock`(본문 mock 패턴 5회 이상), `duplicate_name`(같은 파일 내 동일 이름 2회 이상, 모든 해당 테스트에 표시). 패턴은 언어별 단일 dict 테이블 | must | plan |
| FR4 | 파일별 `last_commit`(git log -1 커밋 시각) 및 `predates_harness`(last_commit < `.harness/VERSION` 최초 커밋 시각). git 아님/미커밋/harness 미커밋이면 null | must | user: 늦게 설치된 harness |
| FR5 | `runner_candidates`: pytest(pytest.ini, conftest.py, pyproject의 `[tool.pytest` → `pytest`), unittest(python 테스트 있고 pytest 근거 없음 → `python3 -m unittest discover`), npm(package.json scripts.test → `npm test`), go(go.mod → `go test ./...`), cargo(Cargo.toml → `cargo test`), maven(pom.xml → `mvn test`), gradle(build.gradle[.kts] → gradlew 있으면 `./gradlew test` 아니면 `gradle test`). 스캔 root에서만 탐지 | must | plan |
| FR6 | `inventory`: `test/`, `tests/`, `spec/`, `__tests__/` 디렉터리 아래 파일 중 FR1에 해당하지 않는 파일 경로(정렬). 결과 전체는 경로 정렬로 결정론적 | should | user: 기타 언어 인벤토리 |
| FR7 | SKILL.md: frontmatter `name: test-audit`, `disable-model-invocation: true`, `argument-hint`; 단계 Scope→Intent→Run→Spec 대조→Quality→Effectiveness→Classify→Handoff; 코드/테스트 수정 금지(hand mutation은 seed.py backup/restore); 기능 단위 handoff를 Handoff Rule 구조로 작성. openai.yaml `policy.allow_implicit_invocation: false` | must | user |
| FR8 | 설치/업데이트 시 `.agents/skills/test-audit/{SKILL.md,agents/openai.yaml}`와 `.claude/skills/test-audit` symlink, `.harness/bin/test_scan.py`가 생김. MIGRATIONS에 0.18.0 항목, VERSION 0.18.0 | must | AGENTS.md |

# Errors
- PATH 미존재 — stderr 메시지, exit 2, stdout 비어 있음 — 파일 변경 없음.
- Python 문법 오류 파일 — 해당 파일 `parse_error: true`, `tests: []` — 스캔 계속, exit 0.
- 디코딩 불가 파일 — `errors="replace"`로 읽고 계속.
- git 없음/실패 — `last_commit`, `predates_harness` null — 스캔 계속.

# Cases
| id | level | input / state | expected result |
| --- | --- | --- | --- |
| N1 | normal | python 파일에 assert 있는 테스트 1개 | tests 1개, flags [] |
| N2 | normal | 각 언어 테스트 파일 1개씩 | language별 테스트 이름·줄 번호 정확 |
| N3 | normal | pyproject `[tool.pytest.ini_options]` + package.json test script | pytest, npm 후보 |
| B1 | boundary | mock 패턴 4회 / 5회 | heavy_mock 없음 / 있음 |
| B2 | boundary | 파일 last_commit == harness 최초 커밋 시각 | predates_harness false |
| E1 | error | 없는 PATH | exit 2, stdout 비어 있음 |
| E2 | error | python 문법 오류 테스트 파일 | parse_error true, exit 0 |
| E3 | error | git repo 아님 | last_commit null |
| G1 | edge | node_modules 안의 `x.test.js` | 결과에 없음 |
| G2 | edge | 클래스 내 동일 이름 메서드 2개 | 둘 다 duplicate_name |

# Quality Applicability
| ISO/IEC 25010:2023 characteristic | applicable | rationale |
| --- | --- | --- |
| Functional suitability | yes | 핵심 |
| Performance efficiency | no | 유저가 가끔 호출하는 일회성 도구 |
| Compatibility | yes | 어떤 repo에도 설치되므로 표준 라이브러리만 |
| Interaction capability | no | 출력은 에이전트가 읽는 JSON |
| Reliability | yes | 깨진 파일/비-git 환경에서도 끝까지 스캔 |
| Security | yes | 스캔 대상 repo에 쓰기·프로젝트 코드 실행 금지 |
| Maintainability | yes | 언어 패턴 확장 지점이 단일 테이블 |
| Flexibility | no | 언어 추가는 Maintainability로 다룸 |
| Safety | no | 물리적 위해 없음 |

# Quality Requirements
| id | characteristic / subcharacteristic | target and context | measure method / inputs / unit | threshold and direction | evidence: automated, review, mutation | source |
| --- | --- | --- | --- | --- | --- | --- |
| QR1 | Compatibility / co-existence | test_scan.py import | 비표준 import 모듈 수 (AST로 import 수집, sys.stdlib_module_names 대조) | = 0 | automated | plan |
| QR2 | Reliability / fault tolerance | Errors 4종 | 크래시(traceback) 수 | = 0 | automated (E1–E3) | spec Errors |
| QR3 | Security / integrity | 스캔 전후 대상 트리 | 스캔 전후 파일 목록+mtime 차이 수 | = 0 | automated | plan |
| QR4 | Maintainability / modifiability | 언어별 패턴 | 패턴 정의 위치 수 | = 1 dict | review R2 | plan |

# Verification Obligations
| id | parent requirement/Case ids | variant and target surface | test layer and selection policy | ISO/IEC/IEEE 29119-4 technique | coverage items | coverage target | observation and expected result | evidence procedure |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| VO1 | FR1, N2, G1 | CLI JSON files[] | integration, tmp dir | equivalence partitioning | 파일 패턴 클래스 10개(py test_, py _test, js .test, ts .spec, __tests__, go, rust, java Test, java Tests, 제외 디렉터리) + 비대상 1 | 100% | 포함/제외 정확 | unittest |
| VO2 | FR2, N1, N2 | tests[].name/line | integration | equivalence partitioning | 언어 5개 × 추출 형식(python 함수/메서드, js it/test/xit, go, rust, java) | 100% | 이름·줄 일치 | unittest |
| VO3 | FR3, B1, G2 | tests[].flags | integration | decision table + boundary value analysis (2-value) | flag 8종 각 참/거짓 1회, heavy_mock 4/5 | 100% | flags 정확 | unittest |
| VO4 | FR4, B2, E3 | last_commit/predates_harness | integration, 임시 git repo(고정 commit 날짜) | boundary value analysis (3-value) | harness 시각 -1s, ==, +1s, 비-git, 미커밋 파일(null), harness 미커밋(null), VERSION 2회 커밋 시 최초 커밋 기준 | 100% | true/false/false/null/null/null/최초 기준 | unittest |
| VO5 | FR5, N3 | runner_candidates | integration | equivalence partitioning | 러너 7종 + gradlew 유무 | 100% | 명령 정확 | unittest |
| VO6 | FR6 | inventory, 순서 | integration | equivalence partitioning | 디렉터리명 4종, 정렬 | 100% | 경로 정렬 목록 | unittest |
| VO7 | Errors, E1, E2, QR2 | CLI exit/stdout | integration (subprocess) | equivalence partitioning | 에러 4종 | 100% | 명세된 신호 | unittest |
| VO8 | QR1, QR3 | 소스/트리 | unit + integration | error guessing | 비표준 import, 쓰기 | none — experience-based | 0 | unittest |
| VO9 | FR7, FR8 | 설치 결과 | integration (installer) | equivalence partitioning | install, update 2종 | 100% | 파일/symlink/frontmatter/openai.yaml 존재 | unittest |
| VO10 | FR7, QR4 | SKILL.md, test_scan.py | review | error guessing | R1, R2 체크리스트 | none — experience-based | 체크 통과 | ledger |

# Assumptions and Defaults
| id | decision | evidence and uncertainty | user approval or explicit delegation |
| --- | --- | --- | --- |
| A1 | heavy_mock 임계 5회 | 관례적 값, 근거 약함 | 유저 승인 (v1) |
| A2 | 비-Python 본문 경계는 다음 테스트 시작까지(근사) | 파서 없이 결정론 유지 | 유저 승인 (v1) |
| A3 | 스킬은 코드를 수정하지 않고 handoff만 남김 | 유저 답변 | 승인됨(계획) |

# Traceability
| requirement id | Case ids | obligation ids | evidence procedure |
| --- | --- | --- | --- |
| FR1 | N2, G1 | VO1 | unittest |
| FR2 | N1, N2 | VO2 | unittest |
| FR3 | B1, G2 | VO3 | unittest |
| FR4 | B2, E3 | VO4 | unittest |
| FR5 | N3 | VO5 | unittest |
| FR6 | — | VO6 | unittest |
| FR7 | — | VO9, VO10 | unittest, R1 |
| FR8 | — | VO9 | unittest |
| QR1–QR4 | E1–E3 | VO7, VO8, VO10 | unittest, R2 |

# Workflow Control
| item | value |
| --- | --- |
| correction batches used | 2 |
| verifier invocations | 2 |
| open finding ids | none |

Audit state (one entry per obligation; retain prior decisions in the execution ledger):
| obligation id | spec version | evidence references and revision | accepted / open / invalidated / pending | rationale and mutation outcome | dependencies and reopening evidence |
| --- | --- | --- | --- | --- | --- |

Execution ledger (append attempts; preserve failed approaches):
| attempt | finding / failure signature | cause hypothesis | changed approach / new evidence | result / disposition |
| --- | --- | --- | --- | --- |
| 1 | F1 기존 버전 고정 테스트 ~27건 실패(0.18.0 프롬프트 추가·버전 문자열) | verified: 테스트 결함 | Tests 범위 확장, 버전 고정 갱신 | correction 1 |
| 1 | F2 `tests_of` 헬퍼가 테스트로 수집됨 | verified: 테스트 결함 | 헬퍼 이름 변경 | correction 1 |
| 2 | Test command 258 OK after correction 1 | — | — | pass |
| 2 | R1 SKILL.md: 8단계+Report, no-edit, seed.py backup/restore, handoff 구조·index | — | review | pass |
| 2 | R2 패턴 정의: LANGUAGES dict 1곳 (러너 감지는 파일명 규칙, 언어 패턴 아님) | — | review | pass |
| 3 | Hand mutations M1 `<`→`<=` predates, M2 heavy_mock `>=`→`>`, M3 dup `>1`→`>2`, M4 node_modules 미제외, M5 inventory 역순, M6 parse error raise, M7 exit 2→1, M8 gradlew 무시, M9 focused 제거, M10 no_assert 비활성 | 경계·플래그·에러 신호가 가장 실패하기 쉬운 결함 클래스 | seed.py backup/restore, test_test_scan 실행 | 10/10 killed, restore 성공 |
| 4 | Verifier #1 RETRY: F4(=verifier F1) VO9 argument-hint 미검증·openai.yaml을 부분 문자열로만 확인 | verified: 테스트 결함 | frontmatter 블록 파싱, policy 아래 키 확인 | correction 2 |
| 4 | F5(=verifier F2) VO4 FR4 null·최초 커밋 미검증 | spec gap(검증 항목 누락) | v3 VO4 항목 추가, 유저 승인 | correction 2 |
| 4 | F6(=verifier F3) pytest 명령 미정의 | spec gap | v3 FR5 `pytest`, 유저 승인 | correction 2 |
| 5 | Correction 2 후 Test command 261 OK; M11 최신 VERSION 커밋 기준(diff-filter 제거+max) → F5 테스트 kill; M12 argument-hint 삭제 → VO9 2건 kill; restore 성공. test-implementer가 openai.yaml(Implementation) 1회 열람 — 단언은 spec 기술 기준 | — | — | F4–F6 해결 대기 감사 |
| 6 | Verifier #2 pass: VO1–VO10 accepted, F4–F6 resolved; advisories A1–A7 non-blocking | — | — | complete |
| 1 | F3 Rust/Java 한 줄 `#[test] fn`/`@Test void` 미인식 | verified: 구현 결함 + spec gap | spec v2로 line/name 정의 | correction 1 |

# Version Log
## v1
- Initial draft from approved plan.
## v2
- FR2에 line(선언 줄, 같은 줄 어노테이션 허용)과 js name(제목 문자열) 정의; 0.18.0으로 깨진 기존 버전 고정 테스트 파일을 Tests에 추가. 유저 승인.
## v3
- Verifier #1 결과: VO4에 미커밋 파일·harness 미커밋·최초 VERSION 커밋 항목 추가, FR5 pytest 명령 `pytest` 명시. 유저 승인.

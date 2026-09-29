---
version: 3
run_id: be4f57b2715f7898
status: complete
base_commit: 412a40ae8ed5421a950664bd51943c0659d4c079
max_verifier_invocations: 2
handoff: none
---

# User Intent
| id | stakeholder | intention | observable goal |
| I1 | harness user | 대상 저장소 .gitignore가 harness 파일을 ignore해 커밋에서 빠지는 일을 막는다 | install/update가 ignore되는 harness 파일이 있으면 아무것도 쓰지 않고 conflict로 중단한다 |
| I2 | harness user | 이미 설치된 저장소에서 문제를 발견한다 | doctor가 ignore되는 harness 파일을 conflict로 보고한다 |

# Scope
In scope: install, update, doctor의 ignore 검사; 0.14.0 VERSION과 no-op 마이그레이션.
Out of scope: .gitignore 자동 수정, `.claude/skills/<name>` 링크, agent-docs/ 아래 파일, import 명령, 이미 git이 추적 중인(index에 있는) 파일.

# Paths
Implementation: installer/harness.py, harness/VERSION
Tests: tests/test_installer.py, tests/test_telemetry.py, tests/test_workflow_markers.py
Test command: python3 -m unittest discover -s tests 2>&1
Review evidence: none — 모든 의무는 자동 테스트로 관측 가능

# Signatures
Checked paths ("guarded paths"): 설치할 owned 파일 전체(render_owned_files(no_ci)의 키; doctor는 manifest["files"]의 키) ∪ {".harness/manifest.json", "AGENTS.md", "CLAUDE.md", ".claude/settings.json", ".codex/hooks.json"}
installer/harness.py: `def find_ignored_paths(target: Path, relpaths) -> list[str]` — conflict 줄 목록 반환(정상 시 입력 순서가 아닌 relpath 정렬 순), git 실패 시 ["git check-ignore failed: <stderr 첫 줄>"]
installer/harness.py: `def run_git(target: Path, args: list, stdin: str | None = None)` — find_ignored_paths는 git을 이 함수로만 호출 (테스트는 모듈의 run_git을 교체해 호출 수 기록/실패 주입)
Conflict line: "<relpath> is ignored by git (<source>:<linenum>:<pattern>)" — source/linenum/pattern은 `git check-ignore -v`의 출력 그대로

# Functional Requirements
| id | requirement | priority | source |
| F1 | install: guarded path 중 git이 ignore하는(index에 없고 ignore 규칙에 매치되는) 경로마다 Conflict line을 conflict 섹션에 보고하고, 대상 저장소에 어떤 파일도 쓰지 않고 exit 1 | must | user |
| F2 | update: F1과 동일. 마이그레이션 실행/확인 요청 이전에 중단하며 manifest 버전을 바꾸지 않는다 | must | user |
| F3 | doctor: guarded path(manifest files 기준) 중 ignore되는 경로마다 Conflict line을 conflict로 보고하고 exit 1 | must | user |
| F4 | --dry-run에서도 F1/F2와 같이 conflict 보고 후 exit 1 | must | user |
| F5 | git이 추적 중인 파일은 ignore 규칙에 매치되어도 conflict가 아니다 | must | git check-ignore 기본 동작; seed.py 사례 |
| F6 | harness/VERSION = 0.14.0, MIGRATIONS에 (0.14.0, 라벨, 파일을 바꾸지 않고 안내 문구 리스트만 반환하는 함수) 추가 | must | user, AGENTS.md |
| F7 | 부정 패턴(!)으로 예외 처리된 경로는 conflict가 아니다 | must | 사용자 복구 경로 |

# Errors
git check-ignore가 exit 0/1 이외(예: 128)로 끝남 — conflict 섹션에 "git check-ignore failed: <stderr 첫 줄>" 보고, exit 1 — install/update는 아무것도 쓰지 않음
ignore되는 guarded path 존재 — F1/F2/F3 Conflict line, exit 1 — install/update는 대상 저장소 무변경

# Cases
| id | level | input / state | expected result |
| C1 | normal | 새 저장소 .gitignore에 `bin/`; install | exit 1; stdout에 ".harness/bin/spec_lifecycle.py is ignored by git (.gitignore:1:bin/)" 및 workflow_marker.py, seed.py 줄; 저장소 파일 스냅샷 불변 (.gitignore만 존재) |
| C2 | normal | 0.13.0 설치 저장소(manifest version을 0.13.0으로 설정) + .gitignore에 `bin/`; update (입력 y) | exit 1; Conflict line; 마이그레이션 프롬프트 없음; manifest 불변; 스냅샷 불변 |
| C3 | normal | 설치 후 .gitignore에 `bin/` 추가; doctor | exit 1; Conflict line 보고 |
| C4 | normal | .gitignore 없음; install → update → doctor | 모두 exit 0; ignore conflict 없음 |
| C5 | boundary | .gitignore `bin/` + `!.harness/bin/`; install | exit 0 |
| C6 | boundary | 설치 후 .harness/bin/*.py 커밋, 그 다음 .gitignore에 `bin/` 추가; doctor와 update | exit 0; ignore conflict 없음 (추적 파일) |
| C7 | boundary | .gitignore에 `AGENTS.md`; install | exit 1; "AGENTS.md is ignored by git (.gitignore:1:AGENTS.md)" |
| C8 | boundary | .gitignore에 `.github/`; install --no-ci | exit 0 (CI 파일은 guarded 아님) |
| C9 | normal | .gitignore `bin/`; install --dry-run 및 update --dry-run | exit 1; Conflict line; 스냅샷 불변 |
| C10 | edge | .git/info/exclude에 `*.toml`; install | exit 1; ".codex/agents/<name>.toml is ignored by git (.git/info/exclude:<n>:*.toml)" 형식 |
| C11 | error | PATH 조작 없이 재현하기 어려운 git 실패 — 단위 수준: check 함수에 git 실패(returncode 128)를 주입 | conflict에 "git check-ignore failed:" 포함, 쓰기 없음 |
| C12 | normal | 0.13.0 manifest 저장소 update --dry-run (ignore 없음) | stdout에 "migration 0.14.0:" ; update 완료 후 manifest version 0.14.0 |

# Quality Applicability
| ISO/IEC 25010:2023 characteristic | applicable | rationale |
| Functional suitability | yes | 핵심 동작 |
| Performance efficiency | yes | 경로 ~100개를 개별 subprocess로 검사하면 느려짐 |
| Compatibility | yes | 공백/비ASCII 경로, 다양한 ignore 출처(.gitignore, info/exclude, 하위 .gitignore) |
| Interaction capability | no | CLI 메시지 형식은 F 요구사항으로 고정 |
| Reliability | yes | git 실패 시 부분 쓰기 없이 중단 |
| Security | no | 새 입력 경계 없음 |
| Maintainability | no | 기존 테스트 스위트로 충분, 별도 측정 없음 |
| Flexibility | no | 해당 없음 |
| Safety | no | 해당 없음 |

# Quality Requirements
| id | characteristic / subcharacteristic | target and context | measure method / inputs / unit | threshold and direction | evidence: automated, review, mutation | source |
| Q1 | Performance efficiency / time behaviour | 한 명령의 ignore 검사 | 명령 1회당 `git check-ignore` 프로세스 호출 수 (count), subprocess 호출을 기록해 측정 | ≤ 1, 작을수록 좋음 | automated: 호출 기록 단위 테스트; mutation: 경로별 호출 | main |
| Q2 | Compatibility / interoperability | 공백·비ASCII 포함 경로 | guarded path 이름에 공백/한글이 있는 추가 owned 경로를 check 함수에 넣고 ignore 규칙 매치 | 해당 경로 Conflict line이 원래 경로 문자열로 정확히 1줄, 통과 방향: 일치 | automated: 단위 테스트(-z 파싱) | main |
| Q3 | Reliability / fault tolerance | git 실패 | C11 | 쓰기 0건, exit 1 | automated | main |

# Verification Obligations
| id | parent requirement/Case ids | variant and target surface | test layer and selection policy | ISO/IEC/IEEE 29119-4 technique | coverage items | coverage target | observation and expected result | evidence procedure |
| VO1 | F1,F2,F3,F4 / C1,C2,C3,C9 | command ∈ {install, update, doctor} × mode ∈ {normal, dry-run(install/update)} ; CLI stdout, exit, 파일 스냅샷 | end-to-end (subprocess installer) | equivalence partitioning | EP1 install, EP2 update, EP3 doctor, EP4 install --dry-run, EP5 update --dry-run | 100% | Case 기대 결과 | Test command |
| VO2 | F5,F7 / C5,C6,C4 | ignore 상태 분류 ∈ {규칙 없음, 규칙 매치·미추적, 부정 패턴 예외, 규칙 매치·추적됨} | end-to-end | decision table | R1 none→ok, R2 match+untracked→conflict, R3 negated→ok, R4 match+tracked→ok | 100% | 해당 규칙대로 exit/Conflict | Test command |
| VO3 | Signatures guarded set / C7,C8,C10,C1 | guarded 경로 부류 | end-to-end | equivalence partitioning | P1 .harness/ owned, P2 managed(AGENTS.md), P3 .codex/agents owned, P4 --no-ci CI 비대상 | 100% | Case 기대 결과, 출처 문자열 정확히 일치 | Test command |
| VO4 | F6 / C12 | 마이그레이션 | end-to-end | equivalence partitioning | M1 0.14.0 announced, M2 version 기록, M3 기존 버전 목록 테스트에 0.14.0 추가 | 100% | stdout/manifest | Test command |
| VO5 | Errors, Q3 / C11 | git 실패 | unit (installer 모듈 import, subprocess 주입) | error guessing | G1 returncode 128 | none — experience-based | "git check-ignore failed:" conflict, 쓰기 없음 | Test command |
| VO6 | Q1 | 호출 수 | unit | boundary value analysis (2-value) | B1 호출 1회 (guarded 경로 다수) | 100% | 기록된 check-ignore 호출 ≤1 | Test command |
| VO7 | Q2 | 특수 경로 | unit | equivalence partitioning | S1 공백 포함, S2 한글 포함 | 100% | 정확한 경로 문자열 | Test command |

# Assumptions and Defaults
| id | decision | evidence and uncertainty | user approval or explicit delegation |
| A1 | 검사 범위 = owned 전체 + 관리 파일 5개 | 사용자 선택 | 승인 |
| A2 | 0.14.0 + no-op 마이그레이션 | 사용자 선택 | 승인 |
| A3 | 메시지에 check-ignore -v 출처 포함 | 사용자 선택 | 승인 |
| A4 | dry-run도 exit 1 | 사용자 선택 | 승인 |
| A5 | 추적 파일은 conflict 아님 (F5) | git check-ignore 기본 동작; 추적 파일은 커밋에서 빠지지 않음 | 승인 |

# Traceability
| requirement id | Case ids | obligation ids | evidence procedure |
| F1 | C1,C7,C10 | VO1,VO3 | Test command |
| F2 | C2 | VO1 | Test command |
| F3 | C3 | VO1 | Test command |
| F4 | C9 | VO1 | Test command |
| F5 | C6 | VO2 | Test command |
| F6 | C12 | VO4 | Test command |
| F7 | C5 | VO2 | Test command |
| Q1 | - | VO6 | Test command |
| Q2 | - | VO7 | Test command |
| Q3 | C11 | VO5 | Test command |

# Workflow Control
| item | value |
| correction batches used | 2 |
| verifier invocations | 2 |
| open finding ids | none |

Audit state (one entry per obligation; retain prior decisions in the execution ledger):
| obligation id | spec version | evidence references and revision | accepted / open / invalidated / pending | rationale and mutation outcome | dependencies and reopening evidence |
| VO1, VO3, VO4, VO6, VO7 | 3 | TestGitignoreGuard batch 1 | accepted | 감사 1 수락; M2(--no-index)→C6 검출, M3(update 검사 지연)→C2/C9 검출 | find_ignored_paths 또는 cmd_* 가드 위치 변경 시 재개 |
| VO2 R1,R2,R4 | 3 | 동일 | accepted | 감사 1 수락 | 동일 |
| VO2 R3 | 3 | test_c5_r3 + test_c5_r3_file_level_negations_exempt_paths | accepted | M1(부정 패턴 skip 제거) 생존: 디렉터리 부정은 git -v 출력에 안 나옴, 파일 수준 부정(`!keep.py`)은 출력됨(수동 확인) | - |
| VO5 G1 | 3 | test_c11_g1 + test_q3_g1_install/update_* | accepted | 반환값만 관찰, exit/무쓰기 미관찰; batch 2 후 M4(install이 실패줄 무시) 검출 | - |

Execution ledger (append attempts; preserve failed approaches):
| attempt | finding / failure signature | cause hypothesis | changed approach / new evidence | result / disposition |
| 1 | TestGitignoreGuard 7건: 기대 줄에 '- ' 없음, 실제 conflict 섹션은 '- <line>' | test defect (verified): print_report가 항목 앞에 '- '를 붙임 | 테스트 파서가 '- ' 접두를 제거 | 175 OK |
| 2 | F-1: G1이 install/update의 exit 1·무쓰기 미관찰 | evidence defect (verified by verifier) | 모듈 main()을 run_git 교체 상태로 호출해 exit·스냅샷 관찰 | 178 OK; M4 검출 |
| 2 | F-2: 뮤테이션 M1 생존 | evidence defect (verified): R3 테스트가 git이 출력하지 않는 디렉터리 부정만 사용 | 파일 수준 부정 변형 추가 | 178 OK; M1 재실행 → file-level 테스트 검출 |
| 1 | 기존 migration/version 테스트 12건 (installer, telemetry, workflow_markers) | test defect (verified): 0.14.0 추가로 버전·응답 수 가정 불일치, 일부는 Tests 경로 밖 | v3에서 Tests 경로 확장 후 수정 | 175 OK |

# Version Log
## v1
- Initial draft.
## v2
- Test command 수정: `-t .`는 tests/에 __init__.py가 없어 로드 실패(ImportError: Start directory is not importable). 동작/기대값 변경 없음.
## v3
- Tests 경로에 test_telemetry.py, test_workflow_markers.py 추가: 0.14.0 버전 상승으로 이들 파일의 버전/마이그레이션 응답 수 가정이 깨짐(기준선 159개 OK, 변경 후 해당 파일 5건 실패). 동작 변경 없음.

## Post-completion (user request)
- 권고 A-1, A-4 반영: test_p2_each_managed_path_is_guarded_by_install_update_and_doctor(관리 파일 5개 × install/update/doctor), test_q3_g1_dry_runs_and_doctor_report_git_failure 추가. 뮤테이션 M5(CLAUDE.md 가드 제거), M6(doctor가 결과를 conflict 아닌 info로 보고) 모두 검출. 180 OK.

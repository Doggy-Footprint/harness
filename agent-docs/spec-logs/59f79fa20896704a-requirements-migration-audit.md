---
version: 1
run_id: 59f79fa20896704a
status: complete
base_commit: beb075fa2d259334a6203187e87f989b02701361
max_verifier_invocations: 2
handoff: none
---

# User Intent
| id | stakeholder | intention | observable goal |
| --- | --- | --- | --- |
| U1 | user | requirements 삭제 및 내용 유무에 따른 마이그레이션 | 데이터가 있으면 실패·안내, 없으면 자동 성공 |
| U2 | user | test-verifier로 간단히 검사 | 기존 변경과 테스트 증거를 spec에 대조 |

# Scope
In scope: 기존 requirements 제거 변경의 CLI 동작 및 증거 감사. 구현 단계는 이미 완료되어 implementer/test-implementer 재실행 없이 Verify부터 진행한다.
Out of scope: 새 기능, 성능 측정, 전체 harness 재설계. 추가 테스트나 수정이 필요하면 감사 결과를 먼저 보고한다.

# Paths
Implementation: installer/harness.py, harness/VERSION
Tests: tests/test_installer.py
Test command: python3 -m unittest discover -s tests -p test_installer.py
Review evidence: 이 spec의 Execution ledger에 테스트 결과와 verifier의 의무별 감사 결과를 기록한다.

# Signatures
migrate_requirements(target: Path, dry_run: bool) -> list[str]
run_migrations(target, installed_version, dry_run, input_fn, before_apply=None) -> bool
ensure_agent_docs_dirs(target, dry_run, report)

# Functional Requirements
| id | requirement | priority | source |
| --- | --- | --- | --- |
| F1 | 신규 설치에서 requirements를 생성하지 않는다. 기존 adr/rejections/handoff는 유지한다. | must | 최초 사용자 요청 |
| F2 | 0.16.1에서 0.16.2 업데이트 시 requirements가 없으면 확인 질문 없이 성공한다. | must | 최초 사용자 요청 |
| F3 | 빈 디렉터리 또는 기본 틀만 있으면 확인 질문 없이 삭제하고 성공한다. 기본 틀은 빈 index.md, 기본 헤더만 있는 stale.md, 빈 stale/.gitkeep이다. | must | 사용자 추가 승인 |
| F4 | 실제 내용이 있으면 실패하고 내용을 백업한 뒤 requirements 디렉터리를 삭제하고 업데이트를 재시도하라고 안내한다. 기존 파일과 manifest는 보존한다. | must | 최초 사용자 요청 |
| F5 | dry-run은 파일을 변경하지 않으며, 내용이 있으면 실제 업데이트와 같은 실패·안내를 제공한다. | must | 기존 dry-run 계약 |
| F6 | 기존 버전별 마이그레이션에 0.16.2를 순서대로 추가하고 성공 시 manifest에 기록한다. | must | AGENTS.md |

# Errors
requirements 내용 존재: CLI exit 1, 백업·삭제·재시도 안내, 저장소 파일 및 manifest 변경 없음.
검사 실패: 완료로 선언하지 않고 의무·증거 부족을 보고한다.

# Cases
| id | level | input / state | expected result |
| --- | --- | --- | --- |
| C1 | normal | 신규 설치 | F1 |
| C2 | edge | requirements 없음, stdin 비어 있음 | F2, F6 |
| C3 | boundary | 빈 디렉터리, stdin 비어 있음 | 삭제 및 exit 0 |
| C4 | normal | 기본 틀만 존재, stdin 비어 있음 | 삭제 및 exit 0 |
| C5 | error | index.md에 내용 또는 stale 하위 문서 존재; update/dry-run 각각 | F4, F5 |
| C6 | normal | 빈 디렉터리 dry-run | 디렉터리 및 manifest 보존 |
| C7 | normal | 이전 버전 업데이트 | 버전별 순서 및 최종 0.16.2 |

# Quality Applicability
| ISO/IEC 25010:2023 characteristic | applicable | rationale |
| --- | --- | --- |
| Functional suitability | yes | 요청 분기와 결과 |
| Performance efficiency | no | 이번 간단 감사에 성능 목표 없음 |
| Compatibility | yes | 이전 설치와 버전별 업데이트 |
| Interaction capability | yes | 실패 안내 및 자동 성공 |
| Reliability | yes | 실패와 dry-run에서 데이터 보존 |
| Security | no | 권한·인증 정책 변경 없음; 링크 등의 추가 방어 검사는 advisory로 보고 |
| Maintainability | no | 별도 유지보수 지표 목표 없음 |
| Flexibility | no | 환경 확장 요구 없음 |
| Safety | no | 물리적 안전 영향 없음 |

# Quality Requirements
| id | characteristic / subcharacteristic | target and context | measure method / inputs / unit | threshold and direction | evidence: automated, review, mutation | source |
| --- | --- | --- | --- | --- | --- | --- |
| Q1 | Functional suitability | C1-C7 결과 | CLI exit 및 파일 관찰; 성공 case 수 / 선언 case 수 | 100% 이상 | automated | F1-F6 |
| Q2 | Compatibility | 이전 버전 업데이트 | migration 출력 순서·manifest 버전; 불일치 건수 | 0건 이하 | automated | F6 |
| Q3 | Interaction capability | C2-C4 및 C5 | stdin 없이 성공, 실패 안내의 세 행동; 누락 건수 | 0건 이하 | automated | F2-F4 |
| Q4 | Reliability | C5/C6 | 실패·dry-run 전후 파일 hash 및 디렉터리 존재; 변경 건수 | 0건 이하 | automated | F4-F5 |

# Verification Obligations
| id | parent requirement/Case ids | variant and target surface | test layer and selection policy | ISO/IEC/IEEE 29119-4 technique | coverage items | coverage target | observation and expected result | evidence procedure |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| V1 | F1,Q1,C1 | install CLI | integration; 신규 설치 1개 | equivalence partitioning | C1 | 100% | requirements 없음, 나머지 관리 디렉터리 존재 | TestNormal.test_agent_docs_dirs_are_created |
| V2 | F2,F3,Q1,Q3,C2-C4 | update CLI | integration; 없음/빈 디렉터리/기본 틀 각 1개 | equivalence partitioning | C2,C3,C4 | 100% | stdin 없이 exit 0, 디렉터리 없음 | TestRequirementsMigration의 absent/empty/default_scaffolding 테스트 |
| V3 | F4,F5,Q1,Q3,Q4,C5 | update 및 dry-run CLI | integration; index 내용/stale 문서 × update/dry-run 4개 | decision table | index-update,index-dry,stale-update,stale-dry | 100% | exit 1, 백업·삭제·재시도 안내, 파일 snapshot 동일 | test_content_fails_without_changes_and_guides_manual_backup |
| V4 | F5,Q1,Q4,C6 | dry-run CLI | integration; 빈 디렉터리 1개 | state transition | empty-before-to-empty-after | 100% | exit 0 및 디렉터리·manifest 보존 | test_empty_directory_is_removed_and_dry_run_preserves_it; verifier가 실제 관찰 범위를 확인 |
| V5 | F6,Q1,Q2,C2,C7 | migration 출력 및 manifest | integration; 0.16.1/0.15.1 두 시작 버전 | scenario | 0161-to-0162,0151-to-0162 | 100% | 순서대로 migration 출력 및 최종 manifest 0.16.2 | TestRequirementsMigration.legacy_repo 및 TestGpt61SolDefaults.test_v2_approved_legacy_update_announces_ordered_model_migrations |

기법 선택: 분기 구분은 equivalence partitioning, 내용·모드 조합은 decision table, 파일 보존은 state transition, 버전 경로는 scenario로 감사한다. 구조 기반 커버리지·랜덤·성능 검사는 이번 요청의 간단한 동작 감사 범위를 넘어 제외한다. 위 명시 항목 외 조합을 자동 확대하지 않는다.

# Assumptions and Defaults
| id | decision | evidence and uncertainty | user approval or explicit delegation |
| --- | --- | --- | --- |
| A1 | 기본 틀만 있으면 내용 없음 | 사용자 명시 답변 | 승인됨 |
| A2 | 기존 구현의 사후 감사로 Verify부터 실행 | 사용자 요청: test-verifier 실행해서 간단하게 검사 | 사용자 승인됨 |
| A3 | Q1-Q4 및 V1-V5를 간단 감사의 유한 범위로 사용 | 추가 방어 검사는 advisory; 필수 요구의 증거 누락은 blocking | 사용자 승인됨 |

# Traceability
| requirement id | Case ids | obligation ids | evidence procedure |
| --- | --- | --- | --- |
| F1 | C1 | V1 | 설치 테스트 |
| F2,F3,Q3 | C2-C4 | V2 | requirements 성공 테스트 |
| F4 | C5 | V3 | 내용 존재 실패 테스트 |
| F5,Q4 | C5,C6 | V3,V4 | 실패·dry-run 보존 테스트 |
| F6,Q2 | C2,C7 | V5 | 버전 업데이트 테스트 |
| Q1 | C1-C7 | V1-V5 | Test command 및 verifier 감사 |

# Workflow Control
| item | value |
| --- | --- |
| correction batches used | 1 |
| verifier invocations | 2 |
| open finding ids | none |

Audit state:
| obligation id | spec version | evidence references and revision | accepted / open / invalidated / pending | rationale and mutation outcome | dependencies and reopening evidence |
| --- | --- | --- | --- | --- | --- |
| V1 | 1 | tests SHA256 6fa3a2de58483b05401d5e491ab37706d3dea21a4093bebecef5433711831d4c, lines 420-427 | accepted | verifier 2: 설치 상태 관찰 충족 | shared helper 재감사 완료 |
| V2 | 1 | same revision, lines 2384-2416/input guard 16-29 | accepted | EV-01/04 closed; 3/3 partitions | shared helper 재감사 완료 |
| V3 | 1 | same revision, lines 2418-2431/snapshot 58-65 | accepted | 4/4 combinations; M1 detected | shared helper 재감사 완료 |
| V4 | 1 | same revision, lines 2393-2401 | accepted | EV-02 closed; M2 detected | shared helper 재감사 완료 |
| V5 | 1 | same revision, lines 2375-2390,2437-2455,2476-2482 | accepted | EV-03 closed; 2/2 paths; M3 detected | shared helper 재감사 완료 |

Execution ledger:
| attempt | finding / failure signature | cause hypothesis | changed approach / new evidence | result / disposition |
| --- | --- | --- | --- | --- |
| E10 | verifier 2 pass | verified | V1-V5 all accepted, declared coverage 100%; EV-01..04 closed; Q1-Q4 accepted | 보완 1회, verifier 2/2, 정상 탐지 mutation 3/3, open none |
| E9 | restored baseline | verified | exact Test command: 138 tests in 36.486s OK; tests SHA256 6fa3a2de58483b05401d5e491ab37706d3dea21a4093bebecef5433711831d4c | verifier 2 예약; EV-01..04 resolved pending audit |
| E8 | M3 corrected detected | verified | tests/test_installer.py:2390: manifest 0.16.1 != 0.16.2 | 정상 assertion 탐지; seed restore 및 seed none 확인 |
| E6 | M1/M2 detected | verified | 전체 Test command; M1 exit 0 != 1, M2 snapshot mismatch | 정상 assertion이 결함 탐지; 매번 seed restore 완료 |
| E7 | M3 initial inconclusive | verified: install까지 변이하여 setup NameError | update의 manifest write만 대상으로 좁힘 | 첫 결과는 탐지 증거로 불인정; restore 완료; 정상 138 tests in 34.241s OK |
| E4 | mutation driver syntax error, 미실행 | verified: tuple 괄호 불일치 | 임시 driver 수정; backup 전에 실패하여 구현 변경 없음 | inconclusive; mutation 미실행으로 기록 |
| E5 | correction baseline | verified | 138 tests in 33.850s OK; tests SHA256 6fa3a2de58483b05401d5e491ab37706d3dea21a4093bebecef5433711831d4c | 전체 V 재감사 대기 |
| E3 | verifier 1: retry, EV-01..04 evidence gaps | verified: 관찰 누락 | absent 최종 상태·버전, dry-run snapshot, input 거부 instrument 보강 | V1/V3 기존 acceptance는 run_installer helper 변경으로 invalidated; V2/V4/V5 open |
| E2 | 승인 후 baseline | verified | Test command: 138 tests, 32.475s, OK; tests SHA256 245ac3323280f04e94454727e53b1f8140c6a47816d5fb2f5176dbd83528a235 | V1-V5 pending; verifier 1회 예약 |
| E1 | 사후 감사 준비 | verified: 기존 구현 완료 | 이전 실행: installer suite 138 tests OK; 새 승인 후 같은 Test command 실행 | 기존 통과만으로 obligation 승인하지 않음 |

verifier는 Tests와 test helpers만 읽는다. 구현과 변경 diff는 제공하지 않는다. 승인 후 전체 installer suite를 최대 120초로 실행하고, 통과하면 verifier 1회 감사한다. main은 감사에서 선정한 가장 강한 결함 종류 2-3개에 대해 backup/inject/test/restore로 mutation을 확인한다. 변경·증거 보완이 필요하면 결과와 원인을 먼저 보고하며 verifier 총 예산은 2회다.

# Version Log
## v1
- 사용자 요청에 따라 기존 requirements 삭제 변경의 간단 감사 spec 초안 작성.

---
version: 5
run_id: 610c47c1cee69d7f
status: complete
base_commit: e99fa182493cf33295d09973c8f6baa4c0cfff26
max_verifier_invocations: 2
handoff: none
---

# User Intent
| id | stakeholder | intention | observable goal |
| --- | --- | --- | --- |
| UI1 | harness user | install/update 때 fuzzing/mutation 도구가 없으면 설치 여부를 묻고 yes면 설치 | 감지된 언어별 `[y/N/never]` 질문, y면 표의 설치 명령 실행 |
| UI2 | harness user | "다시 묻지 않음" | never 선택 후 같은 repo의 install/update에서 질문 없음; `--ask-tools`로 되돌림 |
| UI3 | harness user | 도구가 없으면 spec에서 none | workflow-approach `Mutation tool:`이 `none`을 허용하고 미선언 시 mutation-tool 조건 면제 |

# Scope
In scope: repo 루트 manifest 기반 언어 감지(Python, JS/TS, Go, Rust), 누락 도구 판정, 대화형 질문과 설치 실행, 사용자별·repo별 never 저장과 `--ask-tools` 해제, dry-run 표시, workflow-approach SKILL.md의 Mutation tool none 허용, VERSION 0.28.0과 migration, README 언급.
Out of scope: report 메시지의 정확한 문구(언어·명령·사유 등 FR이 명시한 요소의 존재만 계약), 비-UTF-8 locale 동작, clear_never 실패 시 report 기록, 부분 사용·rewind 추적, Codex 지원 보강, 하위 디렉터리(monorepo) manifest 감지, 기존 spec 소급 수정, Go 버전 사전 검사, doctor 출력 변경.

# Paths
Implementation: installer/verification_tools.py, installer/harness.py, harness/skills/workflow-approach/SKILL.md, harness/VERSION, README.md
Tests: tests/test_verification_tools.py, tests/test_installer.py, tests/test_comment_gate.py, tests/test_session_metrics.py, tests/test_telemetry.py, tests/test_workflow_markers.py
Test command: uv run --with pytest --with hypothesis --with coverage python -m coverage run --branch --include=installer/verification_tools.py -m unittest discover -s tests -q && uv run --with coverage python -m coverage report --fail-under=90
Review evidence: RE1 — main이 `python3 installer/harness.py update .` 실행 후 이 repo(감지 언어 없음)에서 도구 질문이 나오지 않음을 출력으로 기록
Fuzzing: none — 입력이 고정 표와 소수 manifest 형식이라 FR별 분할/경계 테스트로 충분
Mutation tool: mutmut — `uv run --with mutmut mutmut run` 범위 installer/verification_tools.py 변경 라인, 샘플 상한 60, seed 610c47c1, survival threshold 40%

# Signatures
installer/verification_tools.py:
preferences_file() -> Path   # HARNESS_PREFERENCES_FILE 환경변수, 없으면 ~/.harness/preferences.json; 호출 시점에 읽음
@dataclass(frozen=True) class Plan: language: str; packages: tuple[str, ...]; commands: tuple[tuple[str, ...], ...]; blocker: str | None
detect_plans(target: Path, which: Callable[[str], str | None] = shutil.which) -> list[Plan]   # 언어 순서 python, javascript, go, rust; 모든 도구가 있는 언어는 제외
is_never(target: Path) -> bool
set_never(target: Path) -> bool   # 저장 성공 여부
clear_never(target: Path) -> bool
offer(target: Path, dry_run: bool, ask_tools: bool, report: dict, input_fn: Callable[[str], str] = input, run: Callable = subprocess.run, which: Callable[[str], str | None] = shutil.which) -> None
installer/harness.py:
cmd_install(target, dry_run, no_ci, ask_tools=False) -> int; cmd_update(target, dry_run, no_ci, ask_tools=False) -> int
CLI: `--ask-tools` (install, update, update --all에서만 유효; doctor/import에서는 parser.error)

# Functional Requirements
| id | requirement | priority | source |
| --- | --- | --- | --- |
| FR1 | 언어 감지는 target 루트 파일만 본다: `pyproject.toml`→python, `package.json`→javascript, `go.mod`→go, `Cargo.toml`→rust. 여러 개면 모두, 위 순서로 | must | UI1 |
| FR2 | python 도구 hypothesis, mutmut. 매니저: `uv.lock`→`uv add --dev <pkgs>`, 없고 `poetry.lock`→`poetry add --group dev <pkgs>`, 없고 `pdm.lock`→`pdm add -dG dev <pkgs>`. 셋 다 없으면 blocker | must | brief |
| FR3 | python 도구 존재 판정: pyproject.toml을 tomllib로 파싱해 모든 key와 문자열 값 중, 앞부분 요구사항 이름(`[A-Za-z0-9._-]+`)을 PEP 503 정규화(소문자, `[-_.]+`→`-`)한 값이 패키지 이름과 같은 것이 있으면 존재 | must | brief |
| FR4 | javascript 도구 fast-check, @stryker-mutator/core. 매니저: `pnpm-lock.yaml`→`pnpm add -D`, `yarn.lock`→`yarn add -D`, `bun.lock` 또는 `bun.lockb`→`bun add -d`, 그 외→`npm install --save-dev` (이 우선순위) | must | brief |
| FR5 | javascript 존재 판정: package.json 최상위 object의 dependencies, devDependencies, optionalDependencies, peerDependencies 중 하나의 key | must | brief |
| FR6 | go 도구 go-mutesting: go.mod 텍스트에 `github.com/avito-tech/go-mutesting`이 있으면 존재. 명령 `go get -tool github.com/avito-tech/go-mutesting/cmd/go-mutesting@latest`. packages 표시는 `go-mutesting` | must | brief |
| FR7 | rust 도구 proptest(Cargo.toml의 dependencies 또는 dev-dependencies 테이블 key이면 존재)와 cargo-mutants(`which("cargo-mutants")`가 있으면 존재). 명령은 누락된 것만: `cargo add --dev proptest`, `cargo install cargo-mutants` (이 순서) | must | brief |
| FR8 | 명령에는 누락된 패키지만 들어간다(python/javascript는 한 명령에 누락 패키지를 표의 순서로). 모든 도구가 있는 언어는 Plan을 만들지 않는다 | must | brief |
| FR9 | blocker: manifest 파싱 실패/최상위 형식 오류, python 매니저 lockfile 없음, 필요한 실행 파일(uv/poetry/pdm/pnpm/yarn/bun/npm/go/cargo)이 `which`로 없음. blocker Plan은 묻지 않고 report["manual review"]에 언어, 사유를 남긴다; 명령을 알 수 있으면 명령도 포함 | must | brief |
| FR10 | offer: never 저장 상태이고 ask_tools=False이며 질문 대상(blocker 없는 Plan)이 있으면 묻지 않고 report["skip"]에 1줄(`--ask-tools` 언급) | must | UI2 |
| FR11 | offer: ask_tools=True이면 dry_run이 아닐 때 never를 지우고 평소처럼 묻는다; dry_run이면 저장소를 바꾸지 않고 dry-run 표시만 | must | UI2 |
| FR12 | dry_run: 묻지 않고 실행하지 않고 저장하지 않으며, blocker 없는 Plan마다 report["info"]에 언어와 실행 예정 명령. never 상태여도 dry_run이면 FR10 대신 이 규칙을 적용 | must | brief |
| FR13 | 질문: blocker 없는 Plan마다 한 번, 문구에 언어와 실행될 전체 명령(` && `로 연결)을 포함하고 `[y/N/never]`로 끝난다. 답은 strip+lower; `y`/`yes`→설치, `never`→never 저장 후 남은 언어도 묻지 않음, 그 외·빈 입력·EOFError→건너뜀(report["skip"]) | must | UI1, UI2 |
| FR14 | 설치: commands를 순서대로 run(list 인자, shell 없음, cwd=target, stdin=DEVNULL, capture_output=True, text=True, timeout=600). 모두 returncode 0이면 report["write"]에 언어와 패키지. 실패(0 아님, OSError, TimeoutExpired)면 이후 명령 실행 중단, report["manual review"]에 언어, 실패 사유 첫 줄, 실패 명령과 남은 명령 | must | UI1 |
| FR15 | clear_never는 해당 항목이 없으면 파일을 쓰지 않고 True. 저장 형식: preferences_file() JSON `{"repositories": {"<str(target.resolve())>": {"verification_tools_prompt": "never"}}}`. 다른 key와 다른 repo 항목은 보존. 파일 없음·깨진 JSON·형식 불일치는 is_never=False. 깨진/형식 불일치 파일은 set_never가 덮어쓰지 않고 False 반환. 부모 디렉터리는 생성 | must | UI2 |
| FR16 | set_never 실패 시 offer는 report["manual review"]에 저장 실패를 남기고 계속(남은 언어 질문 안 함) | must | UI2 |
| FR17 | cmd_install/cmd_update는 정상 경로(충돌·migration 거부 등 조기 종료가 아닌 경우)에서 finish_common과 comment label 처리 후, manifest 기록 전에 offer를 호출한다. offer 결과는 exit code를 바꾸지 않는다 | must | UI1 |
| FR18 | 감지 언어가 없거나 모든 도구가 있으면 질문·입력 읽기가 전혀 없다 | must | 호환성 |
| FR19 | `--ask-tools`를 doctor/import에 쓰면 parser.error; update --all에서는 각 repo에 전달 | must | brief |
| FR20 | SKILL.md: `Mutation tool:` 형식 줄에 `— or none` 추가; 선언된 도구만 실행한다는 문구로 mutation-tool 단락에 문구 `with `Mutation tool: none` this step is skipped`와 `Declare only installed tools, otherwise `none``; step 6.4 줄에 `the declared mutation tool (if any)`; `8. **Stop condition.**` 줄에 `survivor of a declared mutation tool`. "install declined" 문구는 넣지 않는다 | must | UI3 |
| FR21 | VERSION 0.28.0, MIGRATIONS에 0.28.0 항목(설명 목록 반환, 파일 변경 없음), README 설치/갱신 절에 질문·never·`--ask-tools` 설명 | must | AGENTS.md |

# Errors
- pyproject.toml/Cargo.toml TOML 오류, package.json JSON 오류·최상위 비-object, 읽기 OSError/UnicodeError — 해당 언어 blocker Plan(예외 없음) — 다른 언어 처리 계속
- 실행 파일 없음 — blocker Plan, 명령 포함 manual review — 질문 없음
- 설치 명령 실패/OSError/timeout — manual review에 사유와 남은 명령 — 이후 명령 미실행, exit code 불변, never 저장 안 함
- preferences 파일 깨짐 — is_never False, set_never False(파일 원본 유지) — offer는 manual review 후 계속
- preferences 쓰기 OSError — set_never/clear_never False — 예외 없음
- 입력 EOFError — 건너뜀으로 처리 — 남은 언어는 계속 질문(각각 EOF→건너뜀)

# Cases
| id | level | input / state | expected result |
| --- | --- | --- | --- |
| C1 | normal | pyproject.toml(의존성 없음)+uv.lock, uv on PATH | Plan(python, (hypothesis, mutmut), ((uv, add, --dev, hypothesis, mutmut),), None) |
| C2 | normal | pyproject에 `[dependency-groups] dev=["Hypothesis>=6"]`, poetry.lock, poetry on PATH | 명령 `poetry add --group dev mutmut` |
| C3 | normal | package.json devDependencies에 fast-check, pnpm-lock.yaml | `pnpm add -D @stryker-mutator/core` |
| C4 | normal | go.mod에 go-mutesting 없음, go on PATH | `go get -tool github.com/avito-tech/go-mutesting/cmd/go-mutesting@latest` |
| C5 | normal | Cargo.toml dev-dependencies에 proptest, cargo-mutants 없음 | 명령 `cargo install cargo-mutants` 하나 |
| C6 | normal | 답 `y`, 명령 모두 0 | run 호출 순서·인자·cwd 일치, report["write"]에 언어 |
| C7 | normal | 답 `never` | never 저장, 다음 offer는 입력 없이 skip 1줄 |
| C8 | normal | never 상태, ask_tools=True | never 삭제, 질문함 |
| C9 | boundary | 모든 도구 존재 / manifest 없음 | Plan 없음, input_fn 호출 0 |
| C10 | boundary | pyproject + uv.lock + poetry.lock | uv 선택 |
| C11 | boundary | package.json + yarn.lock + bun.lock | yarn 선택 |
| C12 | boundary | 답 `""`, `N`, `  YES `, `Never` | 건너뜀, 건너뜀, 설치, never |
| C13 | error | package.json `[1]` 또는 깨진 JSON | blocker, 예외 없음 |
| C14 | error | pyproject만(lockfile 없음) | blocker, manual review, 질문 없음 |
| C15 | error | 첫 명령 returncode 1(rust 두 명령) | 두 번째 미실행, manual review |
| C16 | error | run이 TimeoutExpired/OSError | manual review, 예외 없음 |
| C17 | error | preferences 파일 `not json` | is_never False, set_never False, 원본 유지 |
| C18 | error | input_fn EOFError, 두 언어 | 두 번 모두 건너뜀 |
| C19 | edge | python+javascript 둘, 첫 답 never | 두 번째 질문 없음 |
| C20 | edge | dry_run, ask_tools=True, never 상태 | 입력 0, run 0, 저장 불변, info에 명령 |
| C21 | edge | 다른 repo 항목·다른 key가 있는 preferences | set/clear 후 보존 |
| C22 | edge | 빈 git repo에 installer install/update 서브프로세스(forbid_input) | 도구 질문 없음, 성공 |
| C23 | edge | `doctor --ask-tools` | exit 2(parser.error) |

# Quality Applicability
| ISO/IEC 25010:2023 characteristic | applicable | rationale |
| --- | --- | --- |
| Functional suitability | yes | FR1–FR21 |
| Performance efficiency | no | 설치 명령 시간은 외부 도구에 좌우, timeout만 FR14로 규정 |
| Compatibility | yes | 언어 미감지 repo에서 기존 질문 순서 불변 |
| Interaction capability | yes | 질문이 실행 명령 전체를 보여야 함 |
| Reliability | yes | 깨진 manifest·설치 실패가 install/update를 깨지 않아야 함 |
| Security | yes | 명령은 고정 표에서만, shell 미사용 |
| Maintainability | yes | 언어 추가가 한 표 수정으로 끝나야 함 |
| Flexibility | no | Maintainability로 포괄 |
| Safety | no | 물리적 위해 없음; 외부 설치는 사용자 동의로 통제(FR13) |

# Quality Requirements
| id | characteristic / subcharacteristic | target and context | measure method / inputs / unit | threshold and direction | evidence: automated, review, mutation | source |
| --- | --- | --- | --- | --- | --- | --- |
| QR1 | Compatibility / co-existence | 언어 미감지 repo의 install/update | forbid_input 서브프로세스 실행, 예상치 못한 input 호출 수 | 0, 같거나 작아야 pass | automated (C22) | brief |
| QR2 | Interaction capability / operability | 질문 문구 | 각 Plan 질문 문자열에 모든 명령 인자 포함 여부, 비율 | 100% | automated (C6, C1–C5 문구) | brief |
| QR3 | Reliability / fault tolerance | C13–C18 오류 입력 | 예외 전파 수 | 0 | automated | brief |
| QR4 | Security / integrity | run 호출 | run 호출이 list/tuple 인자이고 shell 키워드 없음 또는 False인 비율 | 100% | automated (C6) | brief |
| QR5 | Maintainability / modifiability | 언어별 도구·매니저 정의 | review: 패키지명·명령 템플릿이 모듈 상단 단일 테이블에만 있는지 main이 grep으로 확인 | 정의 위치 1곳 | review RE2 | brief |
| QR6 | Maintainability / testability | installer/verification_tools.py | coverage.py branch coverage % | ≥ 90 | automated (Test command) | brief |

# Verification Obligations
| id | parent requirement/Case ids | variant and target surface | test layer and selection policy | ISO/IEC/IEEE 29119-4 technique | coverage items | coverage target | observation and expected result | evidence procedure |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| VO1 | FR1, FR8, C9 | detect_plans 언어 집합 | unit; 각 manifest 단독 + 4개 동시 + 없음 | equivalence partitioning | EP-none, EP-py, EP-js, EP-go, EP-rust, EP-all4(순서) | 100% | Plan.language 목록 | tests/test_verification_tools.py |
| VO2 | FR2, FR4, C1, C3, C10, C11 | 매니저 선택 | unit | decision table | python: uv / poetry / pdm / uv+poetry→uv / 없음→blocker; js: pnpm / yarn / bun.lock / bun.lockb / 없음→npm / yarn+bun→yarn | 100% | Plan.commands | 위 |
| VO3 | FR3, FR5, FR6, FR7, FR8, C2, C4, C5 | 존재 판정 | unit | equivalence partitioning | py: 없음/일부(정규화 대소문자·`_`)/전부; js: 4개 dep 테이블 각각/없음; go: 있음/없음; rust: proptest 있음·없음 × cargo-mutants which 있음·없음 (4조합 명시) | 100% | commands에 누락 패키지만, 전부 있으면 Plan 없음 | 위 |
| VO4 | FR9, C13, C14, Errors | blocker | unit | equivalence partitioning | 깨진 TOML(py), 깨진 TOML(rust), 깨진 JSON, JSON 비-object, lockfile 없음, 실행파일 없음(uv, npm, go, cargo 중 각 1) | 100% | blocker not None, 예외 없음 | 위 |
| VO5 | FR13, C12, C18, C19 | 답 해석 | unit (offer, fake input/run) | equivalence partitioning + boundary | `y`, `yes`, `  YES `, `never`, `Never`, `""`, `n`, `x`, EOFError, never 후 다음 언어 | 100% | run 호출 여부, never 저장, report 항목 | 위 |
| VO6 | FR14, C6, C15, C16, QR4 | 설치 실행 | unit | equivalence partitioning | 전부 성공, 첫 명령 실패(returncode), OSError, TimeoutExpired | 100% | run 인자(list, cwd, stdin, timeout=600, shell 없음), 중단, report 섹션 | 위 |
| VO7 | FR10, FR11, FR12, C7, C8, C20 | never/ask_tools/dry_run 상태 | unit | state transition | T1 ask→never, T2 never→skip, T3 never+ask_tools→ask(삭제), T4 dry_run(never 유지, 질문 0, info) | 100% | input/run 호출 수, 저장 상태, report | 위 |
| VO8 | FR15, FR16, C17, C21, Errors | preferences 저장 | unit (HARNESS_PREFERENCES_FILE) | equivalence partitioning | 없음, 정상, 깨진 JSON, 형식 불일치(list), 다른 항목 보존, 쓰기 OSError(읽기전용 디렉터리), set_never 실패 시 offer manual review | 100% | 파일 내용, 반환값 | 위 |
| VO9 | FR17, FR18, FR19, C22, C23, QR1 | installer CLI | integration (서브프로세스) | scenario | install 빈 repo forbid_input, update 빈 repo, `doctor --ask-tools` 오류, `install --ask-tools` 수용, 등록된(HARNESS_TARGETS_FILE) never 상태 repo에 `update --all`(질문 없음) 후 `update --all --ask-tools`(질문함, never 해제), pyproject+uv.lock repo에서 fake `uv` 스크립트 PATH + 입력 `y` → fake uv가 인자 기록 | 100% | exit code, 출력, fake uv 기록 | tests/test_installer.py |
| VO10 | FR13, QR2 | 질문 문구 | unit | equivalence partitioning | 단일 명령, 두 명령(` && `) | 100% | 문구에 모든 인자와 `[y/N/never]` | tests/test_verification_tools.py |
| VO11 | FR20, FR21 | 문서/버전 | unit (텍스트 검사) | syntax | SKILL.md Mutation tool 줄에 `or none`; mutation-tool 단락의 FR20 두 문구; step 6.4 줄 FR20 문구; stop condition 줄 FR20 문구; SKILL.md에 `install declined` 없음; VERSION 0.28.0; MIGRATIONS에 0.28.0; README에 `--ask-tools`, `[y/N/never]`, `never` | 100% | 문자열 존재/부재 | tests/test_installer.py |
| VO12 | QR3 | 오류 입력 | unit | error guessing | 빈 package.json, pyproject 바이너리(UnicodeError), Cargo.toml dependencies가 문자열 | none — experience-based | 예외 없음 | tests/test_verification_tools.py |
| VO13 | QR6 | branch coverage | Test command | branch testing | installer/verification_tools.py 분기 | 90% | coverage report | Test command |
| VO14 | QR5 | 단일 테이블 | review | — | RE2 | 100% | grep 결과 | main 기록 |

# Assumptions and Defaults
| id | decision | evidence and uncertainty | brief v<n> — approved / vetoed → <answer> / user answer |
| --- | --- | --- | --- |
| A1 | 질문 시점은 install/update | 사용자 선택 1.B | user answer |
| A2 | 프로젝트 dev dependency 설치, Rust cargo-mutants만 전역 | 사용자 선택 2.A, 3.A | user answer |
| A3 | never는 사용자별·repo 단위, ~/.harness/preferences.json | 사용자 선택 3.A, 범위 1.A | user answer |
| A4 | 해제는 `--ask-tools` | 사용자 선택 2.A(두 번째 brief) | user answer |
| A5 | 도구 표와 lockfile 우선순위 | 일반 관행; 선택 도구가 바뀌면 표 수정 | brief v1 — approved |
| A6 | 미설치 시 spec은 `none`, "install declined" 문구 없음 | 사용자 지시 | user answer |
| A7 | 설치 실패는 exit code 불변, manual review | ensure_comment_approval_label 선례(installer/harness.py:1113) | brief v1 — approved |
| A8 | 기존 baseline 오류(pytest 미설치)는 Test command의 `--with pytest`로 해소 | baseline 실행 결과 | brief v1 — approved |

# Traceability
| requirement id | Case ids | obligation ids | evidence procedure |
| --- | --- | --- | --- |
| FR1 | C9 | VO1 | unit |
| FR2 | C1, C10, C14 | VO2, VO4 | unit |
| FR3 | C2 | VO3 | unit |
| FR4 | C3, C11 | VO2 | unit |
| FR5 | C3 | VO3 | unit |
| FR6 | C4 | VO3 | unit |
| FR7 | C5 | VO3 | unit |
| FR8 | C9 | VO1, VO3 | unit |
| FR9 | C13, C14 | VO4, VO12 | unit |
| FR10 | C7 | VO7 | unit |
| FR11 | C8, C20 | VO7 | unit |
| FR12 | C20 | VO7 | unit |
| FR13 | C12, C18, C19 | VO5, VO10 | unit |
| FR14 | C6, C15, C16 | VO6 | unit |
| FR15 | C17, C21 | VO8 | unit |
| FR16 | C17 | VO8 | unit |
| FR17 | C22 | VO9 | integration |
| FR18 | C9, C22 | VO1, VO9 | unit, integration |
| FR19 | C23 | VO9 | integration |
| FR20 | — | VO11 | unit |
| FR21 | — | VO11 | unit |
| QR1–QR6 | C22, C6, C13–C18 | VO9, VO10, VO6, VO12, VO13, VO14 | automated, review |

# Workflow Control
| item | value |
| --- | --- |
| correction batches used | 2 |
| verifier invocations | 2 |
| open finding ids | none (advisory: offer_9/11 empty manual hint; README placement) |

Audit state (one entry per obligation; retain prior decisions in the execution ledger):
| obligation id | spec version | evidence references and revision | accepted / open / invalidated / pending | rationale and mutation outcome | dependencies and reopening evidence |
| --- | --- | --- | --- | --- | --- |
| VO1–VO14 | 5 | verifier 2 audit map | accepted | M1–M12 killed; mutmut 359/393 killed, 17 equivalent, 0 overturned | F1, F2 closed |
## v5 closure
- Verifier 2: pass. RE1: `update .` on this repo showed no tool question. Status complete.

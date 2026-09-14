# harness

Claude Code와 Codex 양쪽에서 동작하는, **임의의 git 저장소에 설치·업그레이드 가능한 AI 에이전트 하네스**입니다. 문서화 규칙, contract 기반 구현/테스트 워크플로우, 서브에이전트, 라이프사이클 훅, CI 체크를 하나의 패키지로 배포하고 버전 관리합니다.

## 왜 만들었나

AI 에이전트로 작업할수록 문서·주석·docstring이 통제 불가능하게 불어나고, 이는 사람에게도 에이전트 자신의 컨텍스트에도 오염원이 됩니다. 복사해서 쓰는 템플릿으로는 여러 프로젝트에 걸쳐 규칙을 유지·업그레이드할 수 없어서, **설치형 하네스**로 만들었습니다. 규칙은 가능한 한 LLM의 판단이 아니라 git hook으로 기계적으로 강제합니다(`harness/git/verify_rules.py`).

## 핵심 기능과 설계 근거

### 1. 단일 소스에서 Claude/Codex 두 포맷을 동시 생성
서브에이전트 정의를 `harness/agents/<name>.md` 하나(공통 본문 + `claude.*`/`codex.*` frontmatter)로만 작성하면, `installer/generate.py`가 Claude용 Markdown+frontmatter와 Codex용 TOML로 각각 렌더링합니다. 훅 설정도 동일하게 `hooks.spec.json` 하나에서 `.claude/settings.json`과 `.codex/hooks.json`을 생성합니다.
> 두 플랫폼 사이의 차이를 방지

### 2. 3-way sha 비교 기반 안전한 업그레이드
`upgrade`는 `.harness/manifest.json`에 기록된 이전 sha256, 현재 디스크 상태, 새로 렌더링한 내용을 3방향으로 비교해 "하네스 원본과 동일 → 갱신", "사용자가 수정함 → 건너뛰고 보고", "더 이상 소유하지 않음 → 미변경 시 삭제"를 구분합니다. 건너뛴 파일은 manifest에 이전 sha가 그대로 남아, 이후 `doctor`가 drift를 계속 잡아냅니다.
> 하네스가 배포하는 파일이라도 사용자가 수정했다면 그건 존중해야 할 로컬 변경입니다. 무조건 덮어쓰는 업그레이드는 신뢰할 수 없는 도구가 됩니다.

### 3. Contract 기반 구현/테스트 워크플로우 (`contract-workflow` 스킬)
구현과 테스트를 담당하는 두 서브에이전트(`implementer`, `test-implementer`)를 같은 Contract 문서(시그니처·엣지케이스·Intent)만 보고 서로 결과를 보지 못한 채 병렬로 작업시킵니다. 테스트의 기대값은 코드 실행이 아니라 명세에서만 도출하도록 강제합니다. 이후 `test-verifier`가 구현 코드 없이 테스트 스위트만 감사하고, 발견한 허점을 실제 파일에 주입(`Seed`)해 실증합니다.
> AI agent의 테스트가 많고 쓸모 없는 이유 중 하나는 구현자와 테스트 구현자가 context를 공유하기 때문입니다. 이를 방지하고, test에 대해서는 한 번 더 검증합니다.

### 4. 기계적으로 강제되는 문서화 규칙
`AGENTS.md`의 관리 블록이 주석 최소화 정책, ADR/Rejection/Handoff 작성 규칙, 문서 디렉터리의 Index & Staleness 관리, 여러 위치에 흩어진 동일 주석의 동기화(`synced id`) 규칙을 정의합니다. 이 중 결정론적으로 검증 가능한 부분(파일 네이밍, index/stale 존재, sync 일관성, 필수 헤딩)은 커밋 시점에 `verify_rules.py`가 강제로 차단합니다.
> 지시보다는 **rule**이 낫습니다. 검증 가능한 부분은 커밋 훅으로, 판단이 필요한 부분(ADR 작성 여부 등)만 에이전트/사용자 판단에 남겨둡니다.

### 5. 경로 검증 기반 안전한 자동 삭제
세션 종료 시 세션 한정 디렉터리(`agent-docs/contracts/`)를 자동 삭제하는 `cleanup.py`는, 삭제 대상 경로가 설정 가능한 `docs_root`와 저장소 루트 양쪽에 엄격히 포함되는지(`is_strictly_inside`) 확인한 뒤에만 지웁니다.
> 잘못된 설정 값 하나가 임의 경로 삭제로 이어지지 않도록, 자동화된 삭제 동작에는 항상 경로 포함 검증을 둡니다.

### 6. 기존 프로젝트와의 비파괴적 병합
이미 `AGENTS.md`/`CLAUDE.md`, `.claude/settings.json`의 훅, Husky 같은 git hook 매니저가 있는 저장소에 설치할 때, 하네스는 자기 소유 항목만 추가/교체하고 나머지는 보존합니다. 이름이 충돌하는 agent/skill이 있으면 자동 병합 대신 설치를 중단하고 충돌 목록만 보고합니다.
> 기존 템플릿의 경우, 수정사항을 반영하기 힘들고, 해당 프로젝트에 결합하는 문제가 있었습니다.

## 사용법

```bash
python3 installer/harness.py install <target> [--dry-run] [--no-ci]
python3 installer/harness.py upgrade <target> [--dry-run] [--no-ci]
python3 installer/harness.py doctor <target>
```

- `install`은 대상이 git worktree가 아니거나, 이미 설치돼 있거나, 충돌이 있으면 아무것도 쓰지 않고 종료합니다.
- `upgrade`는 하네스가 소유한 파일만 갱신하고, 사용자가 수정한 파일은 건너뜁니다.
- `doctor`는 설치 상태(파일 sha, 훅 등록, 문서 블록, git 훅 연동)를 점검하는 읽기 전용 명령입니다.
- 이 저장소 자체도 자신을 설치해 도그푸딩합니다. `harness/`를 수정한 뒤에는 `python3 installer/harness.py upgrade .`로 반영합니다.

## 테스트

`tests/test_installer.py`는 mock 없이 실제 CLI/훅 스크립트를 임시 git 저장소에서 서브프로세스로 실행하는 black-box 테스트입니다(~20개 시나리오). 멱등성(반복 업그레이드가 no-op인지), 사용자 수정 보존과 drift 감지, Claude/Codex 두 플랫폼 간 설정 일관성, 그리고 실제 프로세스의 생존/종료 상태를 이용한 세션 락 동시성 검증까지 다룹니다.

```bash
python3 -m unittest tests/test_installer.py
```

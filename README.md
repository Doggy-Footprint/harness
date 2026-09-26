# harness

Claude Code와 Codex에 공통 규칙과 작업 도구를 설치하는 AI 에이전트 하네스입니다. Git 저장소에 설치할 수 있으며, 이 저장소의 `harness/`가 배포 원본입니다. 현재 버전은 [`harness/VERSION`](harness/VERSION)에서 확인할 수 있습니다.

## 빠른 시작

Python 3와 Git이 필요합니다. 이 저장소에서 대상 Git 저장소의 경로를 지정해 실행합니다.

```bash
python3 installer/harness.py install <target> --dry-run
python3 installer/harness.py install <target>
python3 installer/harness.py doctor <target>
```

`--dry-run`은 변경 예정 항목만 보여줍니다. 대상에 이미 `.harness/manifest.json`이 있으면 `install` 대신 `update`를 사용하세요. GitHub Actions를 사용하지 않는 저장소에는 설치·갱신 명령에 `--no-ci`를 붙일 수 있습니다.

## 설치되는 것

| 위치 | 역할 |
| --- | --- |
| `.harness/` | 버전이 기록된 payload, 스크립트, 설정 원본과 소유 파일의 SHA manifest |
| `AGENTS.md`, `CLAUDE.md` | 프로젝트 정의와 관리형 문서 규칙; Claude는 `@AGENTS.md`로 같은 규칙을 읽음 |
| `.agents/skills/`, `.claude/skills/` | `workflow-approach`, `requirement-oracle`, `architecture-options`, `harness-import` 스킬과 Claude용 링크 |
| `.claude/agents/`, `.codex/agents/` | 공통 원본에서 생성한 `implementer`, `test-implementer`, `test-verifier`, `code-explorer` 정의 |
| `.claude/settings.json`, `.codex/hooks.json` | 세션·서브에이전트·도구 훅 |
| `.harness/git/` | 커밋 전 문서 규칙 검증과 기존 Git hook 연결 |
| `agent-docs/` | ADR, 거절 기록, handoff, 요구사항, spec 및 실행 기록의 위치 |
| `.github/workflows/harness-comment-warning.yml` | PR에서 새 주석과 docstring을 알리는 선택적 GitHub Actions 워크플로우 |

설치 시 기존 Claude/Codex hook 설정에는 하네스 항목을 병합합니다. 새로 설치하는 저장소에 기존 `AGENTS.md`가 있으면 프로젝트 정의만 남기고 원문을 `agent-docs/logs/`에 보관합니다. 기존 `CLAUDE.md`에는 필요하면 `@AGENTS.md`를 추가합니다. 파일이나 스킬 이름이 충돌하면 설치를 중단하고 경로를 보고합니다.

Git hook 관리자가 없는 경우 `core.hooksPath`를 `.harness/git`으로 설정합니다. Husky 등 기존 관리자가 있으면 설정을 바꾸지 않고 수동 연결 방법을 출력합니다. 커밋 전 검사는 문서 파일명, index/stale 구조, 동기화된 주석의 메타데이터와 필수 제목처럼 기계적으로 판단할 수 있는 규칙을 검사합니다. PR의 주석 검사는 경고만 출력합니다.

## 작업 흐름

[`workflow-approach`](harness/skills/workflow-approach/SKILL.md)는 기능·수정 수준의 구현과 디버깅에 사용하는 명세 우선 워크플로우입니다. 단순 문서 수정이나 이름 변경에는 적용하지 않습니다.

1. 메인 에이전트가 요구사항, 품질 목표, 검증 의무를 `agent-docs/specs/`의 버전별 spec에 작성하고 사용자 승인을 받습니다. 미결정 사항은 `requirement-oracle`이 선택에 필요한 근거를 정리합니다.
2. `implementer`와 `test-implementer`가 같은 승인된 spec을 기준으로 병렬 작업합니다. 각 역할은 상대방의 결과물을 보지 않습니다.
3. 테스트가 통과하면 `test-verifier`가 증거를 감사합니다. 메인 에이전트는 선택한 결함을 실제로 주입하고 테스트가 이를 잡는지 확인한 뒤 원본을 복원합니다. 검증 에이전트 호출은 한 실행당 최대 2회입니다.
4. 완료·중단 상태의 spec은 `agent-docs/spec-logs/`에 보관합니다. 진행 중인 spec과 handoff는 다음 세션에서 이어갈 수 있도록 유지합니다.

세션 및 도구 훅은 spec 생명주기, 동시 실행 표식, 테스트 명령 제한과 실행 이벤트를 관리합니다. 텔레메트리는 기본적으로 사용자 홈의 `~/.harness/telemetry/`에 JSONL로 기록되며, 기록 실패가 작업 흐름을 막지는 않습니다.

문서 작성 기준과 ADR·거절 기록·handoff 규칙은 [`harness-block.md`](harness/instructions/harness-block.md)에 있습니다.

## 갱신과 점검

```bash
python3 installer/harness.py update <target> --dry-run
python3 installer/harness.py update <target>
python3 installer/harness.py doctor <target>
python3 installer/harness.py import <target> --json
```

`update`는 설치된 버전부터 현재 버전까지 필요한 migration을 **버전별로 출력하고 각각 확인받은 뒤** 적용합니다. 하네스 소유 파일은 manifest의 이전 SHA, 디스크의 현재 SHA, 새 payload를 비교합니다. 사용자가 수정한 파일은 건너뛰고 보고하며 이전 SHA를 유지합니다. 더 이상 배포하지 않는 파일은 수정되지 않았을 때만 삭제합니다. `--dry-run`은 migration 계획과 파일 변경을 쓰지 않고 보여줍니다.

`doctor`는 manifest의 파일 SHA, 설정의 hook 항목, `AGENTS.md` 관리 블록, `CLAUDE.md` 참조와 Git hook 연결을 읽기 전용으로 점검합니다. `import`는 설치본과 현재 원본의 차이를 읽기 전용으로 보여주며, `--json`으로 기계 판독용 결과를 출력합니다. 차이를 원본에 반영할지는 [`harness-import`](harness/skills/harness-import/SKILL.md) 스킬에서 검토합니다.

## 이 저장소에서 개발하기

배포 내용은 `harness/`에서만 수정합니다. `.harness/`, `.claude/`, `.codex/`, `.agents/`의 설치 결과물을 직접 편집하지 마세요. payload를 바꾼 뒤에는 자체 설치본을 갱신합니다.

```bash
python3 installer/harness.py update .
python3 -m unittest discover -s tests
```

버전을 올릴 때는 [`installer/harness.py`](installer/harness.py)의 버전별 migration 단계를 추가해야 합니다. 에이전트 정의와 hook 설정은 각각 `harness/agents/`와 `harness/hooks/hooks.spec.json`에서 관리하고, [`installer/generate.py`](installer/generate.py)가 Claude/Codex 형식으로 생성합니다.

# 세션 로그 분석 (개발 중)

별도의 로컬 분석 화면은 `analytics/`에 있습니다. 실행하려면 Python 의존성과 프런트엔드를 빌드한 뒤 서버를 시작합니다.

```bash
python3 -m pip install -r analytics/requirements.txt
npm ci --prefix analytics/frontend
npm run build --prefix analytics/frontend
python3 -m analytics.app
```

기본 주소는 `http://127.0.0.1:8000`입니다. 분석 화면은 사용자 홈의 텔레메트리와 Claude/Codex 세션 기록을 읽고, 로컬 SQLite 데이터베이스에 가져옵니다.

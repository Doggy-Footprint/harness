# harness

> 포트폴리오: [https://blog-steel-ten-13.vercel.app/posts/harness](https://blog-steel-ten-13.vercel.app/posts/harness)

Git 저장소에 설치하는 Claude Code용 AI 에이전트 하네스입니다. 문서 규칙, 스킬, 서브에이전트, 훅, CI 주석 검사를 함께 설치합니다. 배포 원본은 `harness/`이고, 현재 버전은 [`harness/VERSION`](harness/VERSION)에 있습니다.

> **Codex는 지원하지 않습니다.** `.codex/` 파일은 생성되지만 동작을 보장하지 않으며, 서브에이전트 제약은 Claude Code에서만 강제됩니다.

## 빠른 시작

Python 3와 Git이 필요합니다.

```bash
python3 installer/harness.py install <target> --dry-run   # 변경 예정 항목만 표시
python3 installer/harness.py install <target>
python3 installer/harness.py doctor <target>
```

| 옵션 | 효과 |
| --- | --- |
| `--dry-run` | 파일을 쓰지 않고 계획만 표시 |
| `--no-ci` | GitHub Actions 워크플로우와 라벨 생성을 건너뜀 |
| `--ask-tools` | 저장해 둔 `never` 답을 지우고 도구 설치를 다시 물음 |
| `--model sonnet\|opus` | workflow 서브에이전트의 기본 모델을 바꾸고 `.harness/config.json`에 저장 (기본 `sonnet`) |

- 이미 설치된 저장소(`.harness/manifest.json` 있음)는 `install` 대신 `update`를 씁니다.
- 언어(Python, JS/TS, Go, Rust)를 감지해 fuzzing/mutation 도구가 없으면 설치 여부를 `[y/N/never]`로 묻습니다. `never`는 `~/.harness/preferences.json`에 저장됩니다. 도구를 설치하지 않았다면 spec의 `Mutation tool:`을 `none`으로 둡니다.
- `--model`은 `implementer`, `test-implementer`, `test-verifier`, `code-explorer`에 적용됩니다. 이후 `--model` 없이 `update`하면 저장된 값을 씁니다. `mutant-triager`는 항상 `haiku`를 씁니다. workflow 브리프에는 역할별 모델이 기본값으로 표시됩니다.
- 파일이나 스킬 이름이 충돌하면 설치를 중단하고 경로를 알려 줍니다.

## 설치되는 것

| 위치 | 역할 |
| --- | --- |
| `.harness/` | 버전별 payload, 스크립트, 소유 파일의 SHA manifest |
| `AGENTS.md`, `CLAUDE.md` | 프로젝트 정의와 관리형 문서 규칙 (`CLAUDE.md`는 `@AGENTS.md` 참조) |
| `.agents/skills/`, `.claude/skills/` | `workflow-approach`, `requirement-oracle`, `architecture-options`, `harness-import`, `test-audit`, `rearrange-docs` |
| `.claude/agents/` | `implementer`, `test-implementer`, `test-verifier`, `mutant-triager`, `code-explorer` |
| `.claude/settings.json` | 세션·서브에이전트·도구 훅. `gh pr create`/`gh pr edit` 뒤에는 PR 설명을 5분 standup 소개 기준으로 쓰라고 상기시킴 |
| `.harness/git/` | 커밋 전 문서 규칙 검사, 커밋 메시지의 `Request:`·`Intent:` 줄 경고 |
| `agent-docs/` | try-n-fail 기록, handoff, spec, 실행 기록 |
| `.github/workflows/harness-comment-warning.yml` | 새 주석이 있는 PR은 `comments-approved` 라벨이 있어야 통과 (선택) |

기존 설정과의 관계:

- 기존 hook 설정에는 하네스 항목을 병합합니다.
- 기존 `AGENTS.md`는 프로젝트 정의만 남기고 원문을 `agent-docs/logs/`에 보관합니다.
- Git hook 관리자가 없으면 `core.hooksPath`를 `.harness/git`으로 설정합니다. Husky 등이 있으면 수동 연결 방법만 출력합니다.
- 새 주석은 커밋 때는 경고만 하고, PR에서는 라벨이 없으면 실패합니다.
- 새 회고 항목 없이 바뀐 spec과 `Request:`·`Intent:` 줄이 없는 커밋 메시지도 커밋 때 경고만 합니다.

## 작업 흐름

기능·수정 수준의 구현과 디버깅에는 [`workflow-approach`](harness/skills/workflow-approach/SKILL.md)를 씁니다. 단순 문서 수정이나 이름 변경에는 쓰지 않습니다.

1. **Spec**: 메인 에이전트가 이해한 내용을 제시하고, 사용자 확인을 거쳐 `agent-docs/specs/`에 spec을 쓰고 채팅 브리프로 승인받습니다. 미결정 사항은 `requirement-oracle`이 돕습니다.
   - 브리프는 질문(되돌리기 어려운 결정), 사용자가 거부할 수 있는 기본값, 새 개념 설명으로 나뉘며 파일로 남기지 않습니다.
2. **구현 + 테스트**: `implementer`와 `test-implementer`가 서로의 결과물을 보지 않고 병렬로 작업합니다.
3. **검증**: `test-verifier`가 증거를 감사하고, 메인 에이전트가 결함을 주입해 테스트가 잡는지 확인합니다. 검증 호출은 실행당 최대 2회입니다.
4. **보관**: 끝난 spec은 `agent-docs/spec-logs/`로 옮기고, 진행 중인 spec과 handoff는 다음 세션을 위해 남깁니다.
5. **회고**: 세션을 마칠 때마다 spec의 `# Retrospective`에 넣을 항목(다음 세션이 다시 알아낼 수 없는 관찰, 근거, 재확인 방법) 초안을 사용자에게 보여 주고, 확인받은 뒤 기록합니다.

텔레메트리는 `~/.harness/telemetry/`에 JSONL로 기록됩니다.

## 문서 관리

에이전트는 `AGENTS.md`의 관리 블록에 따라 문서를 씁니다. 전문은 [`harness-block.md`](harness/instructions/harness-block.md)에 있습니다.

| 문서 | 위치 | 언제 쓰나 |
| --- | --- | --- |
| 주석·docstring | 코드 | 코드로 알 수 없는 설계 제약, 외부 시스템, 보안 불변식, 특이한 구현의 이유만 |
| try-n-fail | `agent-docs/try-n-fail/` | 실패를 알아내는 데 실제 구현·실행·조사가 든 시도, 또는 사용자가 거절한 구체적 제안을 다음 작업이 반복할 수 있을 때. 초안 확인 후 작성 |
| handoff | `agent-docs/handoff/` | 검증 예산 소진, 사용자 결정 대기, 중단, 또는 요청 시. 실패한 시도는 지우지 않고 추가만 |
| 동기화 주석 | `agent-docs/synced-comments/` | 같은 주석을 여러 곳에 유지할 때. 코드에 `synced id`와 버전을 태그 |

- 관리 디렉터리마다 `index.md`, `stale.md`, `stale/`을 두고, 파일명은 `<16자리 hex id>-<kebab-case>.md`입니다. 낡은 문서는 지우지 않고 `stale/`로 옮깁니다.
- 커밋 전 Git hook이 파일명, index/stale 구조, 동기화 주석 메타데이터, 필수 제목을 검사합니다.
- `agent-docs/` 문서(`index.md`, `stale.md` 제외)의 frontmatter `commit`은 hook이 마지막 작성 시점의 HEAD로 채웁니다.
- 커밋 메시지에는 작업을 요청한 user 요청(`Request:`)과 의도(`Intent:`)를, PR 설명은 프로젝트를 모르는 사람에게 하는 5분 standup 소개 기준으로 씁니다.
- 규칙이 바뀐 뒤 기존 문서를 현재 규칙에 맞게 다시 쓰려면 `/rearrange-docs`를 실행합니다.

## 갱신과 점검

```bash
python3 installer/harness.py update <target> [--dry-run]
python3 installer/harness.py update <target-a> <target-b>
python3 installer/harness.py update --all
python3 installer/harness.py doctor <target>
python3 installer/harness.py import <target> --json
```

| 명령 | 동작 |
| --- | --- |
| `update` | 버전별 migration을 하나씩 확인받고 적용합니다. 사용자가 수정한 파일은 건너뛰고 보고합니다. |
| `update --all` | 지금까지 `install`/`update`한 저장소(`.harness-targets.json`)를 모두 갱신합니다. |
| `doctor` | manifest SHA, hook 설정, 관리 블록, Git hook 연결을 읽기 전용으로 점검합니다. |
| `import` | 설치본과 원본의 차이를 보여 줍니다. 반영 여부는 [`harness-import`](harness/skills/harness-import/SKILL.md) 스킬로 검토합니다. |

여러 디렉터리를 주면 하나가 실패해도 나머지를 계속 처리하고, 하나라도 실패하면 종료 코드 1을 반환합니다.

## 이 저장소에서 개발하기

`harness/`만 수정합니다. `.harness/`, `.claude/`, `.codex/`, `.agents/`는 생성 결과물이므로 직접 고치지 마세요.

```bash
python3 installer/harness.py update .
python3 -m unittest discover -s tests
```

- 버전을 올리면 [`installer/harness.py`](installer/harness.py)에 버전별 migration을 추가합니다.
- 에이전트는 `harness/agents/`, 훅은 `harness/hooks/hooks.spec.json`에서 관리하며 [`installer/generate.py`](installer/generate.py)가 생성합니다.

## 하네스 평가

평가 코드는 `evaluation/`에 있으며 설치되지 않습니다. 지금까지의 시도는 모두 중단했고, 사용법과 중단 이유는 각 문서에 있습니다.

- [`evaluation/selfcheck`](evaluation/selfcheck/README.md): 보관됨
- [`evaluation/reference_mutation`](evaluation/reference_mutation/README.md): pilot 후 중단 ([실험 기록](evaluation/reference_mutation/EXPERIMENT.md))

## 세션 로그 분석 (analytics)

하네스 텔레메트리와 Claude/Codex 세션 기록을 SQLite로 가져와 보여 주는 로컬 화면입니다. 다른 repo에는 설치되지 않습니다.

```bash
python3 -m pip install -r analytics/requirements.txt
npm ci --prefix analytics/frontend
npm run build --prefix analytics/frontend
python3 -m analytics.app   # http://127.0.0.1:8000
```

- workflow 실행별 상태와 규칙 준수 여부 (`compliant`, `noncompliant`, `partial`, `unrelated`, `excluded`)
- 토큰 사용량과 [`analytics/config.yaml`](analytics/config.yaml) 단가 기준 비용

| 환경 변수 | 기본값 |
| --- | --- |
| `ANALYTICS_HOST` / `ANALYTICS_PORT` | `127.0.0.1` / `8000` |
| `ANALYTICS_DATABASE_PATH` | `~/.harness/analytics.sqlite3` |
| `ANALYTICS_TELEMETRY_DIR` | `~/.harness/telemetry` |
| `ANALYTICS_CLAUDE_TRANSCRIPT_DIR` | `~/.claude/projects` |
| `ANALYTICS_CODEX_TRANSCRIPT_DIR` | `~/.codex/sessions` |
| `ANALYTICS_PRICE_PATH` | `analytics/config.yaml` |
| `ANALYTICS_FRONTEND_DIR` | `analytics/frontend/dist` |

# harness

> 관련 블로그 글: [harness](https://blog-steel-ten-13.vercel.app/posts/harness)

Claude Code와 Codex에 공통 규칙과 작업 도구를 설치하는 AI 에이전트 하네스입니다. Git 저장소에 설치할 수 있으며, 이 저장소의 `harness/`가 배포 원본입니다. 현재 버전은 [`harness/VERSION`](harness/VERSION)에서 확인할 수 있습니다.

> **Codex는 지원 대상이 아닙니다.** `.codex/` 파일은 계속 생성되지만 동작을 보장하지 않습니다. Codex 서브에이전트는 부모 세션의 sandbox·권한·MCP 서버를 그대로 상속하며 에이전트 파일로 제한할 수 없으므로, 읽기 전용 격리 등 하네스의 서브에이전트 제약은 Claude Code에서만 강제됩니다.

## 빠른 시작

Python 3와 Git이 필요합니다. 이 저장소에서 대상 Git 저장소의 경로를 지정해 실행합니다.

```bash
python3 installer/harness.py install <target> --dry-run
python3 installer/harness.py install <target>
python3 installer/harness.py doctor <target>
python3 installer/harness.py doctor <target-a> <target-b>
```

`--dry-run`은 변경 예정 항목만 보여줍니다. 대상에 이미 `.harness/manifest.json`이 있으면 `install` 대신 `update`를 사용하세요. GitHub Actions를 사용하지 않는 저장소에는 설치·갱신 명령에 `--no-ci`를 붙일 수 있습니다.

## 설치되는 것

| 위치 | 역할 |
| --- | --- |
| `.harness/` | 버전이 기록된 payload, 스크립트, 설정 원본과 소유 파일의 SHA manifest |
| `AGENTS.md`, `CLAUDE.md` | 프로젝트 정의와 관리형 문서 규칙; Claude는 `@AGENTS.md`로 같은 규칙을 읽음 |
| `.agents/skills/`, `.claude/skills/` | `workflow-approach`, `requirement-oracle`, `architecture-options`, `harness-import`, `test-audit`, `rearrange-docs` 스킬과 Claude용 링크 |
| `.claude/agents/`, `.codex/agents/` | 공통 원본에서 생성한 `implementer`, `test-implementer`, `test-verifier`, `mutant-triager`, `code-explorer` 정의 |
| `.claude/settings.json`, `.codex/hooks.json` | 세션·서브에이전트·도구 훅 |
| `.harness/git/` | 커밋 전 문서 규칙 검증과 기존 Git hook 연결 |
| `agent-docs/` | ADR, 거절 기록, handoff, spec 및 실행 기록의 위치 |
| `.github/workflows/harness-comment-warning.yml` | PR에서 새 주석과 docstring이 있으면 `comments-approved` 라벨이 없을 때 실패하는 승인 게이트 GitHub Actions 워크플로우(선택, 새 push 시 라벨 제거) |

설치 시 기존 Claude/Codex hook 설정에는 하네스 항목을 병합합니다. 새로 설치하는 저장소에 기존 `AGENTS.md`가 있으면 프로젝트 정의만 남기고 원문을 `agent-docs/logs/`에 보관합니다. 기존 `CLAUDE.md`에는 필요하면 `@AGENTS.md`를 추가합니다. 파일이나 스킬 이름이 충돌하면 설치를 중단하고 경로를 보고합니다.

Git hook 관리자가 없는 경우 `core.hooksPath`를 `.harness/git`으로 설정합니다. Husky 등 기존 관리자가 있으면 설정을 바꾸지 않고 수동 연결 방법을 출력합니다. 커밋 전 검사는 문서 파일명, index/stale 구조, 동기화된 주석의 메타데이터와 필수 제목처럼 기계적으로 판단할 수 있는 규칙을 검사합니다. 새 주석은 커밋 시 경고만 출력하고 막지 않으며, PR 검사는 `comments-approved` 라벨이 없으면 실패합니다.

## 작업 흐름

[`workflow-approach`](harness/skills/workflow-approach/SKILL.md)는 기능·수정 수준의 구현과 디버깅에 사용하는 명세 우선 워크플로우입니다. 단순 문서 수정이나 이름 변경에는 적용하지 않습니다.

1. 메인 에이전트가 먼저 "이해한 내용"(프로젝트, 작업 위치, 성공 기준, 하지 않을 일)을 채팅으로 제시하고 사용자가 바로잡습니다. 그다음 요구사항, 품질 목표, 검증 의무를 `agent-docs/specs/`의 버전별 spec에 작성하고, 채팅 브리프로 승인을 받습니다. 브리프는 질문(되돌리기 어려운 결정), 사용자가 거부할 수 있는 기본값, 새 개념 설명으로 나뉘며 파일로 남기지 않습니다. 미결정 사항은 `requirement-oracle`이 선택에 필요한 근거를 정리합니다.
2. `implementer`와 `test-implementer`가 같은 승인된 spec을 기준으로 병렬 작업합니다. 각 역할은 상대방의 결과물을 보지 않습니다.
3. 테스트가 통과하면 `test-verifier`가 증거를 감사합니다. 메인 에이전트는 선택한 결함을 실제로 주입하고 테스트가 이를 잡는지 확인한 뒤 원본을 복원합니다. 검증 에이전트 호출은 한 실행당 최대 2회입니다.
4. 완료·중단 상태의 spec은 `agent-docs/spec-logs/`에 보관합니다. 진행 중인 spec과 handoff는 다음 세션에서 이어갈 수 있도록 유지합니다.

세션 및 도구 훅은 spec 생명주기, 동시 실행 표식, 테스트 명령 제한과 실행 이벤트를 관리합니다. 텔레메트리는 기본적으로 사용자 홈의 `~/.harness/telemetry/`에 JSONL로 기록되며, 기록 실패가 작업 흐름을 막지는 않습니다.

문서 작성 기준과 ADR·거절 기록·handoff 규칙은 [`harness-block.md`](harness/instructions/harness-block.md)에 있습니다.

## 갱신과 점검

```bash
python3 installer/harness.py update <target> --dry-run
python3 installer/harness.py update <target>
python3 installer/harness.py update <target-a> <target-b>
python3 installer/harness.py update --all
python3 installer/harness.py doctor <target>
python3 installer/harness.py import <target> --json
```

`update`는 설치된 버전부터 현재 버전까지 필요한 migration을 **버전별로 출력하고 각각 확인받은 뒤** 적용합니다. 하네스 소유 파일은 manifest의 이전 SHA, 디스크의 현재 SHA, 새 payload를 비교합니다. 사용자가 수정한 파일은 건너뛰고 보고하며 이전 SHA를 유지합니다. 더 이상 배포하지 않는 파일은 수정되지 않았을 때만 삭제합니다. `--dry-run`은 migration 계획과 파일 변경을 쓰지 않고 보여줍니다. `update`와 `doctor`는 디렉터리를 여러 개 받아 순서대로 각각 처리하며, 하나가 실패해도 나머지를 계속 처리하고 하나라도 실패하면 종료 코드 1을 반환합니다. `install`/`update`가 성공한 디렉터리는 이 레포의 gitignore된 `.harness-targets.json`에 기록되고, `update --all`은 기록된 디렉터리를 모두 갱신합니다(사라졌거나 설치되지 않은 경로는 `skip`으로 알리고 건너뜀).

`doctor`는 manifest의 파일 SHA, 설정의 hook 항목, `AGENTS.md` 관리 블록, `CLAUDE.md` 참조와 Git hook 연결을 읽기 전용으로 점검합니다. `import`는 설치본과 현재 원본의 차이를 읽기 전용으로 보여주며, `--json`으로 기계 판독용 결과를 출력합니다. 차이를 원본에 반영할지는 [`harness-import`](harness/skills/harness-import/SKILL.md) 스킬에서 검토합니다.

## 이 저장소에서 개발하기

배포 내용은 `harness/`에서만 수정합니다. `.harness/`, `.claude/`, `.codex/`, `.agents/`의 설치 결과물을 직접 편집하지 마세요. payload를 바꾼 뒤에는 자체 설치본을 갱신합니다.

```bash
python3 installer/harness.py update .
python3 -m unittest discover -s tests
```

버전을 올릴 때는 [`installer/harness.py`](installer/harness.py)의 버전별 migration 단계를 추가해야 합니다. 에이전트 정의와 hook 설정은 각각 `harness/agents/`와 `harness/hooks/hooks.spec.json`에서 관리하고, [`installer/generate.py`](installer/generate.py)가 Claude/Codex 형식으로 생성합니다.

## 자체 점검 (selfcheck)

> **보관됨(archived).** SWE-bench Verified 기반 점검은 하네스 효과를 측정하지 못한다고 판단해 더 이상 개발·실행하지 않습니다. 로컬 이미지와 캐시는 삭제했으므로 다시 실행하려면 아래 순서를 처음부터 거쳐야 합니다. 이유와 후속 계획은 `agent-docs/handoff/c379ec40307bd6c0-harness-value-evaluation-redesign.md`를 보세요.

`selfcheck/`은 하네스 arm이 하네스 없는 기준선(baseline)보다 나은지, 그리고 실행이 하네스 자신의 워크플로우를 따랐는지 확인하는 로컬 도구입니다. 설치 payload에는 포함되지 않습니다. Docker, `selfcheck/requirements.txt`의 의존성, 그리고 구독 OAuth 토큰 파일(`~/.config/selfcheck/oauth_token`)이 필요합니다.

명령은 다음 순서로 실행합니다.

```bash
python3 -m selfcheck pool
python3 -m selfcheck images
python3 -m selfcheck validate
python3 -m selfcheck mutants
python3 -m selfcheck calibrate
python3 -m selfcheck images --agent
python3 -m selfcheck baseline create
python3 -m selfcheck check
```

- `images --agent`: 에이전트 실행용 도구 이미지와 인스턴스별 파생 이미지를 빌드합니다. `run`은 이미지를 이름으로만 참조하므로 `baseline create` 전에 필요합니다.
- `baseline create`: 기준선 arm을 `--repeats`(기본 3)번 실행해 `selfcheck/fixtures/baseline/<fixture_id>/`에 fixture를 만듭니다. 실행 조건(모델, effort, 도구, 상한, 컨테이너 등)이 같을 때만 재사용되며, 중단되면 같은 명령을 다시 실행해 이어갑니다.
- `check`: 핵심 인스턴스를 하네스 arm으로 실행하고 채점한 뒤 기준선과 비교합니다. 조건이 맞는 fixture가 없으면 실행 전에 종료 코드 2로 거절합니다. `--repeats N`(기본 3, 1 이상)으로 인스턴스마다 하네스 arm을 N번 반복해 실행 간 변동과 하네스 효과를 구분합니다. 항목 디렉터리는 `harness-r<k>`이고, N=1이면 `-r<k>`를 붙이지 않습니다. `--resume`은 `--repeats`를 무시합니다. `--no-baseline`은 비교를 건너뜁니다.
- `check --conditions unassisted,informed`: 쉼표로 나눈 조건 목록(기본 `unassisted`)을 인스턴스·반복마다 모두 실행합니다. 같은 인스턴스·반복 안에서는 `unassisted`가 `informed`보다 먼저 실행됩니다. 알 수 없는 이름은 실행 전에 종료 코드 2로 거절하고(`unknown conditions: <이름>`), `--resume`은 `--conditions`를 무시하고 기록된 항목을 이어갑니다. `informed`는 하네스 arm에만 적용되며 `informed`만 지정하면 기준선 fixture를 informed 매니페스트에서 `user_mode`를 빼고 `user_sim_hash`를 unassisted 해시(`user_sim.py` + `driver.py`)로 바꾼 값으로 찾습니다.
- `process RUN_ID`: 실행 기록(ledger, telemetry, `full.diff`)으로 워크플로우 준수 여부(PC1~PC12)를 pass / fail / n/a로 판정해 각 항목(반복마다) 디렉터리의 `process.json`에 씁니다. PC12는 spec 작성 전에 main 또는 implementer가 구현·테스트 파일을 쓰면 fail입니다. Bash 명령의 쓰기와 읽기는 `selfcheck/bashparse.py`로 분류하며, 테스트 실행(`pytest` 등)은 교차 역할 접근으로 보지 않습니다. 에이전트 transcript는 읽지 않습니다.
- `report RUN_ID [--no-baseline]`: 저장된 점수와 `process.json`으로 리포트를 다시 만듭니다. 조건이 다른 fixture는 달라진 키를 출력하고 종료 코드 2로 끝납니다.
- `review RUN_ID`: 하네스 항목마다 이슈, gold patch, gold test patch, FAIL_TO_PASS를 받은 호스트의 `claude -p` 검토자(`config.json`의 `review`)가 brief와 spec을 범주별(`understanding`, `ask_options`, `recommendation_evidence`, `spec_requirements`)로 인용과 함께 판정하고, 사실과 다른 주장을 표시해 항목 디렉터리의 `review.json`에 씁니다. 실행 파일, 점수, `process.json`은 바꾸지 않습니다. informed 항목은 `<인스턴스> informed[ r<k>]` 이름으로 검토합니다. 리포트에는 검토 표와 `## false claims` 섹션이 붙습니다.

**informed 조건.** `informed`는 brief를 읽고 정답(gold patch, test patch, FAIL_TO_PASS)을 아는 검토자가 하네스의 `AskUserQuestion`과 idle brief에 답하는 별도 조건입니다. 검토자는 호스트에서 `review.claude_call`로 실행되고(`config.json`의 `informed`), 컨테이너와는 `/selfcheck/relay`의 `req-<n>.json` / `resp-<n>.json` 파일을 `docker exec`·`docker cp`로 주고받습니다. gold 텍스트는 컨테이너에 쓰지 않으며 컨테이너에는 `n`과 정제된 답변만 기록합니다. 답변이 null이거나 시간이 지나면 질문은 시뮬레이션 사용자의 선택으로, idle은 unassisted와 같은 고정 문구로 대체됩니다. 항목은 `user_mode: "informed"`로 기록되고 디렉터리는 `harness-informed[-r<k>]`, 예측과 점수는 `predictions.harness-informed.jsonl`, `scores.harness-informed.jsonl`에 따로 저장됩니다. 요청·원문 출력·누출 목록·실제 전송 내용은 항목 디렉터리의 `informed.jsonl`에 토큰을 가린 채 남습니다. 릴레이는 이미 응답 파일이 있는 요청은 건너뛰므로 `--resume` 후에도 같은 요청에 다시 답하지 않습니다.

**누출 규칙.** 검토자의 답변이 FAIL_TO_PASS id·테스트 이름, patch와 test patch의 파일 경로·파일 이름, patch가 추가·삭제한 `def`/`class` 이름, test patch에서 추가된 줄 중 단어 `assert`(단어 경계, `nonassert`·`assertEqual` 제외)를 포함하는 줄의 3자 이상 문자열 리터럴(공백뿐인 리터럴은 제외)을 이슈 본문이나 요청에 없는데 포함하면 그 답변은 null로 바뀌고 `informed.jsonl`의 `leaks`에 용어가 기록됩니다. 식별자 모양의 용어는 단어 경계로, 나머지는 대소문자를 구분한 부분 문자열로 비교합니다.

**구독 한도 경고.** `run`, `baseline create`, `check`는 구독 사용량을 소비합니다. 항목이 `interrupted`로 끝나거나 rate-limit 상태가 `allowed`가 아니면(`allowed_warning` 포함) 이후 항목을 시작하지 않고 종료 코드 3으로 끝납니다. 한도가 풀린 뒤 `python3 -m selfcheck run --resume <run_id>`, `check --resume <run_id>`, 또는 `baseline create` 재실행으로 이어갑니다. 자동으로 기다리지 않습니다.

**결과 위치.** 리포트는 `selfcheck/results/<run_id>.json`과 `.md`에 쓰고, 실행 산출물은 `~/.harness/selfcheck/runs/<run_id>/`에 둡니다. 리포트와 fixture에는 transcript, 도구 입력, diff가 들어가지 않으며 토큰이 포함되면 쓰기를 거절합니다.

**읽는 법.** 리포트는 인스턴스마다 반복별 값, 요약(`resolved`·`swt_success`는 `k/n`, 나머지는 중앙값 [최솟값, 최댓값]), 기준선 범위를 보여줍니다. 요약의 중앙값을 기준선 반복 값의 범위와 비교해 `above`(최댓값 초과), `within`(범위 안), `below`(최솟값 미만), `n/a`(비교할 값 없음)로 표시합니다. 컴파일 가능한 변이가 10개 미만인 인스턴스는 kill 지표에 `(참고용: 표본 작음)`이 붙으므로 참고만 하세요. 통계적 유의성은 검정하지 않으며, 리포트의 자체 보고 kill과 측정 kill은 대조용일 뿐 보정 결과가 아닙니다.

**informed 리포트.** informed 항목이 있으면 리포트 JSON에 `informed`(인스턴스별 블록, `instances`와 같은 모양)와 `informed_effect`(인스턴스·지표별 informed 중앙값 − unassisted 중앙값, 한쪽이 없으면 null)가 추가되고, 마크다운에는 unassisted 섹션 뒤에 `## informed condition: <인스턴스>` 섹션과 `## informed effect` 표가 붙습니다. 차이는 brief를 읽는 사용자의 효과이며 unassisted가 주 점수입니다. informed 항목이 없으면 `informed`는 빈 목록, `informed_effect`는 빈 객체이고 마크다운에 informed 섹션이 붙지 않습니다.

## 세션 로그 분석 (개발 중)

`analytics/`의 목표는 [trace](https://opentelemetry.io/docs/concepts/signals/traces/)를 통해 하네스의 성과를 정량적으로 파악하는 것입니다. 여기서 말하는 trace는 개념상 OpenTelemetry의 trace에서 아이디어를 얻었습니다. 별도의 로컬 분석 화면이며, 설치 payload에는 포함되지 않습니다. 실행하려면 Python 의존성과 프런트엔드를 빌드한 뒤 서버를 시작합니다.

```bash
python3 -m pip install -r analytics/requirements.txt
npm ci --prefix analytics/frontend
npm run build --prefix analytics/frontend
python3 -m analytics.app
```

기본 주소는 `http://127.0.0.1:8000`입니다. 분석 화면은 하네스 텔레메트리와 Claude/Codex 세션 기록을 로컬 SQLite 데이터베이스로 가져와 다음을 보여줍니다.

- workflow 실행별 상태와 규칙 준수 여부. amend는 검증 에이전트 결과를 기다리는 동안에만 위반으로 봅니다.
- 실행 분류(`compliant`, `noncompliant`, `excluded`)와 세션 분류(`compliant`, `noncompliant`, `partial`, `unrelated`, `excluded`)
- 세션 기록 기반 토큰 사용량과 [`analytics/config.yaml`](analytics/config.yaml)의 모델 단가로 계산한 비용

| 환경 변수 | 기본값 |
| --- | --- |
| `ANALYTICS_HOST` / `ANALYTICS_PORT` | `127.0.0.1` / `8000` |
| `ANALYTICS_DATABASE_PATH` | `~/.harness/analytics.sqlite3` |
| `ANALYTICS_TELEMETRY_DIR` | `~/.harness/telemetry` |
| `ANALYTICS_CLAUDE_TRANSCRIPT_DIR` | `~/.claude/projects` |
| `ANALYTICS_CODEX_TRANSCRIPT_DIR` | `~/.codex/sessions` |
| `ANALYTICS_PRICE_PATH` | `analytics/config.yaml` |
| `ANALYTICS_FRONTEND_DIR` | `analytics/frontend/dist` |

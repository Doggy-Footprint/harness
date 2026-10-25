# 자체 점검 (evaluation/selfcheck)

> **보관됨(archived).** SWE-bench Verified 기반 점검은 하네스 효과를 측정하지 못한다고 판단해 더 이상 개발·실행하지 않습니다. 코드는 기록으로만 `evaluation/selfcheck/`로 옮겼고 테스트는 지웠습니다. 아래 명령과 경로(`python3 -m selfcheck`, `selfcheck/...`)는 저장소 최상위에 `selfcheck/`가 있던 시절 기준이며, 옮긴 위치에 맞게 코드를 고치지 않았으므로 그대로는 실행되지 않습니다. 로컬 이미지와 캐시도 삭제했습니다. 이유와 후속 계획은 `agent-docs/handoff/stale/c379ec40307bd6c0-harness-value-evaluation-redesign.md`를 보세요.

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

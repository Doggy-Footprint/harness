# 하네스 테스트 품질 평가 실험 기록 (pilot 7df89a358d3faa30, 중단)

이 문서는 `evaluation/pr_test_quality/`으로 진행한 하네스 테스트 품질 평가 실험의 설계, 실제 실행 절차, 결과, 중단 이유를 정리한 기록입니다. 같은 실험을 다시 돌리거나 결과를 인용할 때 이 문서를 기준으로 삼습니다.
실험은 2026-10-24 12:20 UTC에 pilot 단계에서 사용자 결정으로 끝났고 본 실험(main)은 실행하지 않았습니다.
앞서 진행한 SWE-bench Verified 기반 자체 점검(`selfcheck/`)도 같은 이유로 보관 처리했습니다. 기록은 `agent-docs/handoff/c379ec40307bd6c0-harness-value-evaluation-redesign.md`에 있습니다.

## 1. 요약

- 질문: "이 하네스의 장점은 test를 잘 작성하는 건데, 그 성능을 평가/검증해볼 방법이 없나?"
- 방법: 공개 저장소에서 최근 병합된 PR을 과제로 삼았습니다. 세 arm(B0, Bplus, H)이 같은 요청으로 구현과 테스트를 작성하고, 참조 구현(PR의 merge 상태)과 참조 변이(mutant)로 그 테스트를 채점했습니다.
- pilot 규모: 12개 과제(python, typescript, go 각 4개)와 27개 항목. 항목은 B0 12개, Bplus 12개, H 3개입니다. 오류로 끝난 항목은 없었습니다.
- 결과:
  - 해결률은 B0 5/12, Bplus 5/12, H 1/3이었습니다.
  - H는 B0보다 비용이 3.5~7.4배, 시간이 3.3~5.0배 들었습니다.
  - kill 비교가 가능한 과제(d_ref 10개 이상)에서 H 항목은 1개뿐이었습니다.
- 중단 이유: 이 설계는 하네스의 테스트 품질을 재지 못합니다.
  - 테스트의 유효성을 참조 구현에 대고 판정하므로, 실제로는 "테스트가 참조 구현의 설계와 얼마나 일치하는가"를 잽니다.
  - 그 예로 H가 caddy-7995를 해결했는데도 테스트가 자기 구현에만 있는 함수를 불러 참조 구현에서 컴파일되지 않았습니다. 그 결과 valid 0, kill 0으로 기록되었습니다.
  - 자세한 내용은 [9절](#9-중단-이유-측정-타당성)에 있습니다.

## 2. 질문, 가설, 사전등록

주장, 측정, 임계값, 게이트는 결과를 보기 전에 [`evaluation/pr_test_quality/preregistration.md`](preregistration.md)에 고정했습니다. pilot 실행 기록에는 sha256 `03a8213335bd2999ba1f1ed73c3f5675a218fd65e9ad660ffa8d0e2e8d3d2906`이 저장되어 있고, 현재 파일과 같습니다.

| 가설 | 주 측정 | 비교 |
| --- | --- | --- |
| H3 (주) 테스트 품질 | normalized kill = d_ref 중 에이전트 테스트가 죽인 변이 / \|d_ref\| | H − B0, false_alarm_rate 가드(+0.10) |
| H1 정확성 | resolved (f2p 전부 통과, p2p 깨짐 없음) | H − B0 |
| H2 의도 정렬 | ambiguity_correct (요청에서 생략된 동작의 f2p 통과 비율) | H − B0 |
| H4 비용 | 해결된 과제당 비용 중앙값 H/B0 ≤ 10 | — |

판정은 과제 단위로 짝지은 차이를 사용하고, 저장소 단위 cluster bootstrap(10000회, seed 1, 95%)으로 구간을 냅니다. 과제가 10개 미만이면 `insufficient`이므로 pilot만으로는 어떤 판정도 나오지 않습니다.

## 3. 설계

**arm.** 세 arm의 차이는 프롬프트와 하네스 설치 여부뿐입니다.

- `B0`: 요청을 그대로 프롬프트로 씁니다.
- `Bplus`: 요청 뒤에 테스트를 강조하는 고정 문단을 붙입니다(문구는 사전등록에 있음).
- `H`: 프롬프트는 `/workflow-approach <요청>`입니다. 하네스 커밋 `89d7f58a33b60b86512921cac040d07da6ad933b`(harness 0.28.0)를 설치하고 커밋한 뒤 시작합니다.

**공통 조건.** 모든 arm에 같은 조건을 적용합니다.

- 에이전트: `claude-sonnet-5-5`, effort `medium`, Claude Code CLI 2.1.309, `claude-agent-sdk==0.2.165`.
- 컨테이너 자원: 4 CPU, 8GB 메모리, 벽시계 180분, 사용자 턴 8회.
- 네트워크: squid 프록시를 거쳐 `api.anthropic.com`만 허용합니다.
- 금지 도구: WebSearch, WebFetch, worktree, cron, wakeup, trigger 도구.

**시뮬레이션 사용자.** 호스트에서 `claude-opus-5-5`(medium)가 과제별 의도 카드를 들고 모든 arm의 질문, 승인 요청, idle 턴에 답합니다. 시뮬레이션 사용자와 심사자는 참조 코드, 참조 테스트, f2p id를 보지 못합니다.

**과제 생성(`mine` → `build` → `validate` → `brief` → `mutants`).**

- 선정 조건: 2026-07-01 이후 병합, 별 200개 이상, 허용 라이선스, 언어별 후보 40개, 저장소당 최대 3개(`config.json`의 `mining`).
- `validate`: 참조 테스트를 base와 merge 상태에서 각각 3번 실행해 f2p와 p2p를 나눕니다.
- `brief`: opus가 PR 본문으로 사용자 시점의 요청과 의도 카드를 만듭니다. 참조 테스트의 리터럴과 이름이 새어 나가면 버립니다.
- `mutants`: 참조 구현의 변경된 줄에서 변이를 만듭니다. 도구는 python `mutmut` 2.5.1(API 스크립트), typescript Stryker 10.0.0, go `go-mutesting`(diff 전용 exec)이고, 과제당 최대 40개(seed 1)입니다.

**채점(`score`).** 아래 실행은 모두 VM의 컨테이너에서 합니다.

- hidden: 에이전트 소스에 참조 테스트를 돌려 resolved를 판정합니다.
- validity: 참조 구현에 에이전트 테스트를 돌려 각 테스트를 valid, false_alarm, incompatible, flaky 중 하나로 분류합니다.
- kill: valid 테스트만으로 참조 변이를 죽이는지 봅니다.
- crossarm: 같은 과제의 다른 항목 구현을 버그 구현으로 보고 탐지율을 잽니다.
- 판정에 에이전트의 자체 보고 수치는 쓰지 않습니다.

**심사(`judge`).** opus가 라벨을 섞은 상태에서 각 테스트 세트를 평가합니다. 평가 기준은 test smell, Test Desiderata, ISO/IEC/IEEE 29119-4입니다. 사람이 쓴 테스트를 anchor로 함께 넣습니다.

## 4. 환경과 버전

| 항목 | 값 |
| --- | --- |
| 하네스 | `89d7f58` (master), harness 0.28.0 |
| 평가 코드 | `evaluation/pr_test_quality/` (실험 당시 경로는 `evaluation/`). 아래 "평가 코드 상태" 참고 |
| 테스트(Mac) | `.venv/bin/python -m pytest evaluation/pr_test_quality/tests -q -p no:cacheprovider --cov=evaluation/pr_test_quality --cov-branch --cov-config=evaluation/pr_test_quality/tests/.coveragerc --cov-fail-under=85` → 1049 passed, coverage 91.25% |
| GCP | 프로젝트 `harness-eval-d31ee3`, `us-central1-a` |
| VM | `n2-standard-16` on-demand, 외부 IP 없음, IAP SSH, Cloud NAT |
| 데이터 디스크 | `harness-eval-data` pd-balanced 500GB(설정값 300GB에서 늘림). SSD_TOTAL_GB 지역 할당량이 500이라 그 이상은 불가 |
| docker data-root | `/data/docker`. 50GB 부트 디스크로는 이미지 160개를 감당하지 못함 |
| 도구 고정 | `evaluation/pr_test_quality/config.json`의 `tools`, `evaluation/pr_test_quality/requirements.txt`, `evaluation/pr_test_quality/docker/*.Dockerfile` |
| squid 이미지 | `ubuntu/squid@sha256:6a097f68…bbe029`. VM에서 직접 `docker pull`해야 함 |

**평가 코드 상태.**

- pilot은 커밋하지 않은 작업 트리로 실행했습니다. 그때 패키지 경로는 `evaluation/`(모듈 `evaluation`)였고, VM에서는 `python -m evaluation ...`으로 실행했습니다.
- 실험이 끝난 뒤 코드를 `evaluation/pr_test_quality/`로 옮겨 커밋했습니다. 바뀐 것은 import 경로, 저장소 루트 계산, 문서와 메시지 속 경로뿐이고 동작은 같습니다. 테스트 결과(1049 passed, 91.25%)도 이동 전과 같습니다. 사전등록 파일의 sha256도 그대로입니다.
- pilot 도중 아래 수정을 VM에 `scp`로 반영했고, 커밋한 코드에는 모든 수정이 들어 있습니다.

- 에이전트 실행 전에 반영한 수정: driver 복사 경로, nonroot 토큰 읽기, `allowed_warning`을 멈춤 조건에서 제외.
- 채점 전에 반영한 수정: 누적 비용 계산(`session_cost`), wall time을 `elapsed_s`로 계산, mutant와 cross-arm 병렬 실행.

## 5. 재현 절차 (실제로 실행한 순서)

README의 "평가 실험" 절에 있는 순서가 기본이고, 실제로는 아래처럼 돌렸습니다. VM 보조 스크립트는 `~/.harness/evaluation/backups/pilot-7df89a358d3faa30-scripts/vm/`에 보관했습니다.

1. Mac에서 준비합니다.
   - `python3 -m evaluation.pr_test_quality doctor`로 환경을 점검합니다(docker, claude CLI, 토큰 파일 모드 600, gh 인증).
   - `python3 -m evaluation.pr_test_quality gce up`으로 VM을 만듭니다.
2. Mac에서 `python3 -m evaluation.pr_test_quality mine`으로 후보를 모읍니다. gh 인증이 필요하고, 저장소 검색은 10페이지까지만 봅니다.
3. `python3 -m evaluation.pr_test_quality gce push`로 작업 트리와 과제를 VM의 `/data/src`, `/data/evaluation/tasks`로 보냅니다.
   - **이후에는 push를 다시 하지 마세요.** VM에서 만든 과제 기록이 지워집니다.
   - 소스를 고칠 때는 `gcloud compute scp`와 `sudo install -o evaluation`으로 파일 하나씩 바꿉니다.
4. VM에서 언어별로 `lang.sh`를 병렬 실행합니다.
   - 실행 방법: `sudo -u evaluation bash -c 'setsid nohup /data/lang.sh <L> > /data/logs/lang-<L>.out 2>&1 < /dev/null &'`.
   - 순서: build → 이미지가 없는 행을 지우고 다시 build → validate → `gc.py`가 무효 과제의 두 이미지 태그를 지웁니다.
   - 환경 변수: `EVALUATION_DATA_DIR=/data/evaluation EVALUATION_RESULTS_DIR=/data/results EVALUATION_TOKEN_FILE=/data/secrets/oauth_token`, 인터프리터는 `/data/venv/bin/python`.
5. VM에서 언어별로 `bm.sh <L>`을 실행합니다(brief → mutants, `mutants.workers` 4).
6. 사용자 결정으로 rust를 제외했습니다. 유효 과제가 0개였기 때문이며, 사전등록에도 기록했습니다.
7. pilot을 실행합니다.
   - 시작 전에 squid 이미지를 `docker pull`합니다.
   - `python -m evaluation.pr_test_quality pilot`은 시작할 때 과제에 pilot 표시를 씁니다.
   - 실패한 뒤 다시 실행하면 다른 과제가 뽑힙니다. 다시 실행하기 전에 모든 `tasks.jsonl`의 `pilot`을 false로 되돌리거나 `run --resume` 또는 `run --retry-errors`를 쓰세요.
8. 실행 run `7df89a358d3faa30`을 `run --resume`으로 이어서 끝낸 뒤 `score`, `judge`, `report`를 차례로 돌립니다. `pilot` 명령에는 resume이 없습니다.
   - 이번에는 `postpilot.sh`가 이 순서를 실행했습니다.
   - `judge`는 2개 과제를 처리한 상태에서 중단했고 `report`는 만들지 않았습니다.
9. 정리합니다. 데이터를 묶어 Mac으로 가져온 뒤 `gce down --purge --yes`를 실행하고, Cloud NAT와 router를 지웁니다(11절).

과제 생성 단계는 실행 시점의 GitHub 상태에 따라 다른 후보를 뽑습니다. 같은 과제를 쓰려면 백업의 `tasks/<L>/tasks.jsonl`을 `~/.harness/evaluation/tasks/`에 넣고 `build`부터 시작하세요. 각 행에 base/merge SHA, gold patch, f2p/p2p, recipe가 들어 있습니다.

## 6. 과제 퍼널

| 언어 | 후보 | 유효 | brief ok | 변이 있음 | 주요 탈락 사유 |
| --- | --- | --- | --- | --- | --- |
| python | 40 | 19 | 16 | 14 | python manifest 없음 10, f2p 없음 6 |
| typescript | 40 | 8 | 5 | 5 | 지원 test runner 없음 14, 이미지 빌드 실패 7, binary 6 |
| go | 40 | 25 | 21 | 17 | f2p 없음 9 |
| rust | 34 | 0 | — | — | 제외. gold 테스트가 base에서 컴파일되지 않음, 시스템 의존성, 오프라인 crate |

typescript 유효율 20%는 게이트 G2(50% 이상)를 통과하지 못하는 수준이었습니다. pilot에서는 게이트를 계산하기 전에 실험을 끝냈습니다.

## 7. pilot 과제

언어별로 유효 과제가 가장 많은 저장소 2개를 고르고, 저장소마다 과제를 2개씩 뽑았습니다. H는 언어마다 첫 과제에서만 실행했습니다.

| 과제 | PR | 제목 | f2p / p2p |
| --- | --- | --- | --- |
| caddyserver__caddy-7995 (H) | caddyserver/caddy#7995 | httpcaddyfile: give each adaptation its own directive order | 6 / 27 |
| caddyserver__caddy-8010 | caddyserver/caddy#8010 | events: tell CertMagic which events are worth emitting | 3 / 2 |
| fatedier__frp-5394 | fatedier/frp#5394 | feat: add system info API v2 | 1 / 17 |
| fatedier__frp-5395 | fatedier/frp#5395 | feat: add system prune API v2 | 4 / 21 |
| Panniantong__Agent-Reach-575 (H) | Panniantong/Agent-Reach#575 | fix: resolve urgent install, credential, and routing gaps | 6 / 20 |
| Panniantong__Agent-Reach-576 | Panniantong/Agent-Reach#576 | fix: harden web reads and complete P1 cleanup | 30 / 15 |
| TauricResearch__TradingAgents-1285 | TauricResearch/TradingAgents#1285 | Post-v0.4.0 fixes: FRED vintage, Reddit 429, … | 3 / 33 |
| TauricResearch__TradingAgents-1310 | TauricResearch/TradingAgents#1310 | Point-in-time fixes, honest failure reporting, … | 23 / 74 |
| excalidraw__excalidraw-11632 (H) | excalidraw/excalidraw#11632 | chore(editor): Refactor Actions for clarity | 5 / 145 |
| excalidraw__excalidraw-11677 | excalidraw/excalidraw#11677 | feat: add `props.ui.enabled.zoom/scrollBackToContent` | 5 / 58 |
| google-gemini__gemini-cli-29451 | google-gemini/gemini-cli#29451 | fix(core): bound tool output size … | 24 / 120 |
| google-gemini__gemini-cli-29463 | google-gemini/gemini-cli#29463 | fix(acp): resolve session before config initialization … | 1 / 53 |

## 8. 결과

### 8.1 항목별 점수

열 설명:

- 비용: 누적 비용을 보정한 값(USD). 구독 OAuth로 실행했으므로 실제 청구액이 아니라 CLI가 토큰으로 계산한 환산값입니다.
- valid / FA / inc: 참조 구현에서 돌린 에이전트 테스트의 분류(valid, false_alarm, incompatible).
- nkill: normalized kill. `*` 표시는 d_ref가 10개 미만이라 kill 집계에서 빠지는 과제입니다.

| 과제 | arm | resolved | f2p 비율 | 비용 | 시간(s) | valid / FA / inc | kill (d_ref) | nkill |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Agent-Reach-575 | B0 | ✗ | 0.17 | 0.55 | 145 | 27 / 5 / 0 | 16 (18) | 0.72 |
| | Bplus | ✗ | 0.33 | 1.09 | 283 | 170 / 30 / 0 | 22 (18) | 1.00 |
| | H | ✗ | 0.50 | 2.65 | 734 | 61 / 20 / 0 | 36 (18) | 1.00 |
| Agent-Reach-576 | B0 | ✗ | 0.87 | 0.60 | 222 | 0 / 0 / 1 | 0 (23) | 0.00 |
| | Bplus | ✗ | 0.83 | 0.69 | 233 | 0 / 0 / 2 | 0 (23) | 0.00 |
| TradingAgents-1285 | B0 | ✓ | 1.00 | 0.29 | 231 | 9 / 13 / 0 | 10 (11) | 0.82 |
| | Bplus | ✗ | 0.33 | 0.42 | 282 | 19 / 23 / 0 | 10 (11) | 0.73 |
| TradingAgents-1310 | B0 | ✗ | 0.43 | 0.70 | 564 | 32 / 9 / 0 | 19 (21) | 0.81 |
| | Bplus | ✗ | 0.43 | 0.78 | 497 | 52 / 28 / 0 | 18 (21) | 0.71 |
| caddy-7995 | B0 | ✓ | 1.00 | 0.37 | 312 | 33 / 0 / 0 | 2 (2) | 1.00* |
| | Bplus | ✓ | 1.00 | 0.53 | 389 | 38 / 0 / 0 | 3 (2) | 1.00* |
| | H | ✓ | 1.00 | 2.73 | 1333 | 0 / 1 / 0 | 0 (2) | 0.00* |
| caddy-8010 | B0 | ✓ | 1.00 | 0.16 | 259 | 2 / 0 / 0 | 3 (3) | 1.00* |
| | Bplus | ✓ | 1.00 | 0.21 | 273 | 0 / 1 / 0 | 0 (3) | 0.00* |
| excalidraw-11632 | B0 | ✗ | 1.00 | 2.06 | 1046 | 6 / 6 / 0 | 2 (3) | 0.67* |
| | Bplus | ✓ | 1.00 | 1.98 | 1164 | 31 / 12 / 0 | 3 (3) | 0.67* |
| | H | ✗ | 1.00 | 7.26 | 3443 | 45 / 274 / 0 | 10 (3) | 1.00* |
| excalidraw-11677 | B0 | ✓ | 1.00 | 0.45 | 912 | 9 / 0 / 0 | 17 (20) | 0.80 |
| | Bplus | ✓ | 1.00 | 0.56 | 553 | 23 / 1 / 0 | 16 (20) | 0.75 |
| frp-5394 | B0 | ✗ | 0 | 0.23 | 93 | 2 / 0 / 0 | 0 (0) | —* |
| | Bplus | ✗ | 0 | 0.28 | 110 | 0 / 1 / 0 | 0 (0) | 0.00* |
| frp-5395 | B0 | ✗ | 0.75 | 0.21 | 157 | 2 / 1 / 0 | 3 (4) | 0.75* |
| | Bplus | ✗ | 0.75 | 0.25 | 108 | 4 / 2 / 0 | 3 (4) | 0.75* |
| gemini-cli-29451 | B0 | ✗ | 0.33 | 0.66 | 466 | 8 / 11 / 0 | 5 (14) | 0.36 |
| | Bplus | ✗ | 0.29 | 0.66 | 500 | 21 / 27 / 0 | 11 (14) | 0.79 |
| gemini-cli-29463 | B0 | ✓ | 1.00 | 0.32 | 232 | 1 / 0 / 0 | 4 (3) | 1.00* |
| | Bplus | ✓ | 1.00 | 0.52 | 379 | 9 / 3 / 0 | 4 (3) | 1.00* |

- "kill" 열은 실행된 변이 전체 중 죽인 수입니다. d_ref 밖의 변이도 포함하므로 d_ref보다 클 수 있습니다.
- 해결률: B0 5/12(게이트 G1 ≤ 0.80 통과), Bplus 5/12, H 1/3.
- 에이전트 비용 합계는 $27.20(27개 항목)입니다. brief, 시뮬레이션 사용자, 심사의 opus 호출 비용은 포함하지 않았습니다.
- 질문 수(`questions`)는 모든 항목에서 0이었습니다.
- cross-arm 탐지에서 H는 Agent-Reach-575 2/2, excalidraw-11632 0/1이었고, caddy-7995는 버그 구현이 없었습니다.
- `judge`는 Agent-Reach-575와 Agent-Reach-576만 처리했고 G3, G4는 계산하지 않았습니다.

### 8.2 비용과 시간 (H 과제 3개)

`costs.py`가 transcript에서 assistant 메시지를 `message.id`로 중복 제거한 뒤 토큰을 셉니다.

| 과제 | arm | 비용 (×B0) | 시간 (×B0) | 모델 호출 | cache read | 출력 토큰 |
| --- | --- | --- | --- | --- | --- | --- |
| Agent-Reach-575 | B0 | $0.55 | 145s | 20 | 0.90M | 15k |
| | Bplus | $1.09 (2.0) | 283s (1.9) | 34 | 1.98M | 36k |
| | H | $2.65 (4.8) | 734s (5.0) | 79 | 4.47M | 90k |
| caddy-7995 | B0 | $0.37 | 312s | 16 | 0.53M | 12k |
| | Bplus | $0.53 (1.4) | 389s (1.2) | 21 | 0.83M | 18k |
| | H | $2.73 (7.4) | 1333s (4.3) | 77 | 4.15M | 108k |
| excalidraw-11632 | B0 | $2.06 | 1046s | 70 | 5.75M | 41k |
| | Bplus | $1.98 (1.0) | 1164s (1.1) | 69 | 5.52M | 39k |
| | H | $7.26 (3.5) | 3443s (3.3) | 199 | 18.80M | 190k |

- 비용은 시간에 비례해 매긴 값이 아니라 CLI가 토큰으로 계산한 값입니다. 배율은 cache read 토큰 배율과 거의 같습니다(4.9, 7.8, 3.3배).
- 시간 배율과 비용 배율이 비슷해 보이는 데는 서로 반대 방향의 요인이 섞여 있습니다.
  - 비용이 시간보다 커지는 요인: 병렬 subagent는 같은 시간에 여러 context를 다시 읽습니다.
  - 시간이 비용보다 커지는 요인: sleep 대기와 테스트 실행은 토큰을 쓰지 않습니다.
- SDK의 `total_cost_usd`는 CLI 프로세스 안에서 누적되는 값입니다. 결과를 단순 합산하면 크게 부풀려집니다(Agent-Reach-575 H: $12.41로 보고, 실제 $2.65).

### 8.3 H main 에이전트가 긴 이유 (transcript 분석, LLM 없이)

`segment.py`는 transcript의 타임스탬프 간격을 결정적으로 다음 구간으로 나눕니다: 모델 시간, 도구 시간, 사용자 대기, subagent 대기, coordinator 대기. subagent 대기에는 sleep 폴링과 `queued_command` 알림까지 포함합니다. 결과는 Opus(high) 교차 검토와 일치했습니다.

| 과제 | agent | 총 | 모델 | 도구 | 사용자 대기 | subagent 대기 | main 대기 | main 후속 지시 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Agent-Reach-575 | B0 main | 137 | 108 | 20 | 9 | 0 | — | — |
| | H main | 726 | 286 | 87 | 29 | 324 | — | — |
| | H test-implementer | 363 | 212 | 27 | 0 | — | 125 | 1 |
| caddy-7995 | B0 main | 304 | 91 | 200 | 13 | 0 | — | — |
| | H main | 1327 | 238 | 183 | 18 | 888 (sleep 폴링 771) | — | — |
| | H test-implementer | 879 | 431 | 152 | 0 | — | 295 | 2 |
| excalidraw-11632 | B0 main | 1039 | 299 | 729 | 10 | 0 | — | — |
| | H main | 3435 | 404 | 1296 | 15 | 1720 | — | — |
| | H test-implementer | 2813 | 630 | 999 | 0 | — | 1185 | 6 |

- H main이 B0 main보다 더 쓴 시간의 55%, 87%, 72%는 subagent를 기다린 시간이었습니다.
- 대기의 중심은 test-implementer였습니다. 실제로 일한 시간(모델과 도구)은 238 / 583 / 1629초였고, main이 보낸 보정 지시는 1 / 2 / 6회였습니다. excalidraw에서는 spec이 v1에서 v5까지 바뀌었습니다.
- caddy에서 main은 백그라운드 subagent를 `sleep`으로 폴링했습니다. 완료 알림이 큐에 들어온 뒤에도 302초를 더 잤습니다.
- 하네스 개선 후보는 세 가지입니다(적용하지 않음).
  - 백그라운드 agent를 sleep으로 폴링하지 않습니다.
  - 첫 test-implementer 지시에 lint, mutation, coverage 기준을 넣습니다.
  - 보정 라운드에서는 해당 테스트만 실행합니다.

## 9. 중단 이유: 측정 타당성

1. **유효성 판정이 참조 설계와의 일치를 잽니다.**
   - 에이전트 테스트를 참조 구현에서 실행해 valid와 false alarm을 가릅니다.
   - 에이전트가 요청을 다른 설계(다른 함수 이름, 다른 내부 API)로 구현하면, 올바른 테스트도 참조 구현에서는 실패하거나 컴파일되지 않습니다.
   - caddy-7995 H의 1184줄 Go 테스트 파일은 H 구현에만 있는 `orderFromOptions`를 호출합니다. 그래서 패키지 전체가 컴파일 실패하고 false alarm 1개, valid 0, kill 0이 되었습니다. 같은 항목이 hidden에서는 resolved였습니다.
   - python에서는 같은 상황이 collection error, 즉 `incompatible`로 분류되어 언어마다 처리도 달랐습니다.
2. **false alarm 비율이 모든 arm에서 높습니다.** 예를 들어 excalidraw-11632 H는 274/319, TradingAgents-1285 B0는 13/22였습니다. 사전등록된 가드(H − B0 false_alarm_rate의 상한이 +0.10 초과면 harmful)가 테스트를 더 많이, 더 깊게 쓰는 arm을 해롭다고 판정할 구조입니다. 대부분이 의도된 설계 차이라는 것은 가설이며, 표본을 뽑아 확인하지는 않았습니다.
3. **혼입 요인이 많습니다.**
   - 구현과 테스트를 함께 쓰는 과제라 테스트 품질이 구현 성공 여부에 묶입니다.
   - 시뮬레이션 사용자의 답이 arm마다 다른 경로를 만듭니다.
   - H는 하네스가 강제하는 절차(spec, 승인, 검증)에 비용과 시간을 씁니다.
4. **검정력에 비해 비용이 큽니다.**
   - d_ref가 10개 이상인 과제는 12개 중 6개였습니다.
   - pilot 규모로는 판정이 하나도 나오지 않습니다(과제 10개 미만이면 `insufficient`).
   - 본 실험 계획(언어별 15~20개 과제 × 3 arm × 2회)은 H 비용 배율 3.5~7.4배 때문에 비용이 크게 늘어납니다.
5. **SWE-bench Verified 기반 점검도 같은 이유로 실패했습니다.** 해결률 중심 벤치마크는 테스트를 잘 쓰는 하네스의 효과를 재지 못합니다.

## 10. 다시 설계한다면 (제안, 실행하지 않음)

- **테스트만 쓰는 과제.** 참조 구현을 주고 테스트만 쓰게 합니다. 그 구현의 변이 kill과 버그 버전 탐지로 채점하면 설계 차이에서 오는 false alarm이 사라집니다.
- **자기 구현 기준 채점.** 각 항목의 테스트를 그 항목 자신의 구현과 변이로 채점(self-kill)하고, resolved와 cross-arm 탐지를 함께 봅니다. 컴파일 실패와 collection 실패는 언어와 관계없이 `incompatible`로 통일합니다.
- **소규모 블라인드 정성 비교.** 소수 과제에서 사람이 라벨을 가린 채 테스트를 비교합니다.
- false alarm을 표본으로 뽑아 실제로 틀린 테스트인지, 설계 차이인지 먼저 확인합니다.

## 11. 실패와 수정 기록

시행착오 전체(46행)는 `agent-docs/handoff/d63aaa61098054c3-test-quality-evaluation-verifier-limit.md`의 `## Failed Attempts`에 있습니다. pilot 단계에서 나온 것만 추리면 다음과 같습니다.

| 문제 | 증상 | 조치 |
| --- | --- | --- |
| squid 이미지가 VM에 없음 | pilot 첫 실행에서 `docker create failed` | 직접 pull. build 단계에서는 필요 없어 빠져 있었음 |
| 실패 후 pilot 재실행 | 다른 과제 5개가 선택됨 | pilot 표시가 된 과제가 제외되기 때문. run 2개를 `runs-discarded/`로 옮기고 표시를 초기화 |
| driver 경로 | 모든 항목 `driver exit 2` | `docker cp DIR 기존-dir`이 하위 폴더를 중첩함. `DIR/.`로 복사 |
| 토큰 읽기 실패 | `driver exit 2`, 로그 비어 있음 | 호스트 uid 1001(0600)과 이미지 nonroot uid 1000 불일치. 읽기 전용 bind 후 root가 tmpfs로 0400 복사 |
| `allowed_warning`에서 멈춤 | 완료된 caddy-7995 3개 항목이 `interrupted`로 기록 | warning은 멈춤 조건에서 제외. 3개 항목을 `fixwarn.py`로 복구한 뒤 `run --resume` |
| 비용 과대 계산 | Agent-Reach-575 H $12.41 | 누적 값을 합산했기 때문. `session_cost`가 프로세스 구간마다 마지막 값만 더함 |
| wall time이 0 | 모든 score.json | driver가 `duration_ms`를 기록하지 않음. `elapsed_s` 사용 |
| 순차 채점 | 34분에 16/27, 16코어에서 load 1.3 | mutant와 cross-arm을 스레드 풀로 실행 |
| 참조 구현 기준 유효성 | caddy-7995 H valid 0 | 미해결. 9절 참고 |
| `scored 0 of 27 entries` 출력 | CLI 메시지 | `scored` 키를 설정하지 않음. 고치지 않음 |
| 분석 스크립트 첫 버전 | 사용자 턴이 부풀려지고, sleep 폴링이 도구 시간으로, 알림 5개 누락 | Opus 교차 검토 후 `segment.py`, `condense2.py` 수정 |

## 12. 데이터와 스크립트

모두 Mac 로컬에만 있고 저장소에는 들어 있지 않습니다.

- `~/.harness/evaluation/backups/pilot-7df89a358d3faa30.tgz` (214MB). 압축을 풀면 아래 경로가 나옵니다. 실제 토큰은 0건이고, `sk-ant-oat`는 과제 저장소 코드 안의 패턴 문자열로만 나타납니다.
  - `evaluation/runs/7df89a358d3faa30/`: 항목별 manifest, state, `full.diff`, `split.json`, `usersim.jsonl`, `raw/`(Claude transcript, ledger, telemetry), `score.json`, 과제별 `crossarm.json`, `judge.json`
  - `evaluation/runs-discarded/`: 버린 run 920ced453239d78a, 8141622ef810b4c1
  - `evaluation/tasks/<L>/`: candidates와 tasks
  - `logs/`: VM 로그
- `~/.harness/evaluation/backups/pilot-7df89a358d3faa30-scripts/`
  - `vm/`: `lang.sh`, `bm.sh`, `gc.py`, `fixwarn.py`, `postpilot.sh`, `prep.sh`, `requeue.sh`, `sel.py`, `gopilot.py`, `dbg.py`, `status.py`, `prog.py`, `pstat.sh`, `rust_reset.py`
  - `analysis/`: `costs.py`, `segment.py`, `condense2.py`(압축 타임라인), `trace.py`(초기 버전, 사용자 턴 수가 부정확), `prompts.py`, `mains.sh`, `xcheck/`(Opus 교차 검토 코드), `ti/`와 `mains/`(압축 타임라인 출력)

분석 재실행은 다음과 같이 합니다. 백업은 새 빈 폴더에 풉니다.

```bash
mkdir -p /tmp/pilot && tar xzf ~/.harness/evaluation/backups/pilot-7df89a358d3faa30.tgz -C /tmp/pilot
R=/tmp/pilot/evaluation/runs/7df89a358d3faa30
A=~/.harness/evaluation/backups/pilot-7df89a358d3faa30-scripts/analysis
python3 $A/costs.py $R Panniantong__Agent-Reach-575 caddyserver__caddy-7995 excalidraw__excalidraw-11632
python3 $A/segment.py $R Panniantong__Agent-Reach-575 caddyserver__caddy-7995 excalidraw__excalidraw-11632
```

`costs.py`는 `sys.path`에 저장소 루트를 넣고 `evaluation.pr_test_quality.session_cost`를 가져옵니다. 경로가 다르면 첫 줄들을 고치세요.

## 13. 정리 상태 (2026-10-24)

- 삭제: VM `harness-eval-vm`, 데이터 디스크 `harness-eval-data`, Secret Manager 비밀 `harness-eval-oauth-token`, Cloud NAT `harness-eval-net-nat`, Cloud Router `harness-eval-net-router`.
- 확인: 인스턴스, 디스크, 스냅샷, 커스텀 이미지, 외부 주소, forwarding rule, 비밀, 버킷 모두 0개.
- 남은 것(과금 없음): 프로젝트 자체, VPC `harness-eval-net`과 subnet, 방화벽 규칙, 서비스 계정, 활성화된 API. 프로젝트는 결제 계정에 연결된 상태입니다.
- 다시 실행할 때는 `gce up`이 남은 리소스는 건너뛰고 지운 리소스는 새로 만듭니다.

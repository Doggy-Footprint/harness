# 측정 대장

`workflow-approach` brief를 잰 측정을 한 번에 한 항목씩 적습니다. 실행 결과물(출력, 채점, 뷰어)은 측정한 세션의 scratchpad에만 있고 커밋하지 않으므로, 다시 보려면 같은 명령으로 다시 돌립니다. 비교하는 두 스킬은 커밋과 버전으로 적습니다.

새 측정을 하면 맨 아래에 같은 형식으로 추가합니다. 기록이 없는 칸은 "기록 없음"으로 둡니다.

## 항목 형식

- **id**: `<날짜>-<짧은 이름>`
- **종류**: AB(서로 다른 스킬), AA(같은 스킬 두 사본, 잡음 크기), 회귀(변경 전후의 기존 지표)
- **스킬**: 비교한 스킬의 커밋 또는 버전
- **실행기·모델**: `run_model.py`(첫 메시지) 또는 `run_dialogue.py`(approval brief까지), 실행 모델과 effort, 채점 방식
- **사례×회수**
- **결과**: 핵심 수치
- **비용**: 실행 모델, 시뮬레이션 사용자, 채점 순
- **출처**: 측정한 세션의 기록

## 2026-11-13 (세션 기록 `agent-docs/progress-logs/05c07a463843d48f-spec-brief-spec-context-dau.md`)

이 세션의 iteration 1~7은 세션 기록에 요약만 남아 있어 항목별 수치가 일부 없습니다.

### 2026-11-13-it1-haiku
- 종류: AB
- 스킬: bc71362 작업본과 그 이전 master
- 실행기·모델: `run_model.py`, haiku; sonnet 에이전트가 사례 하나씩 맡아 실행하고 채점
- 사례×회수: batch-cli, cache, tsv-control × 6회
- 결과: 기록 없음
- 비용: 기록 없음

### 2026-11-13-it2-4
- 종류: AB
- 스킬: bc71362 이후 작업본들
- 실행기·모델: `run_model.py`, sonnet low; sonnet 평가 에이전트 5 + 5 + 2
- 사례×회수: 실행 45 + 45 + 12회 (사례 구성은 기록 없음)
- 결과: iteration 2에서 "추측할 수 있는 unknown은 가정으로" 문구가 중요한 결정 뒤의 unknown을 가정으로 옮김(가정 9, 질문 37). 문구를 이동 금지 규칙으로 교체
- 비용: 기록 없음

### 2026-11-13-it5-mail-backfill
- 종류: AB와 AA
- 스킬: 1daddfb 작업본과 master
- 실행기·모델: `run_model.py`, sonnet low; sonnet 평가 에이전트 2
- 사례×회수: mail-backfill, 30회
- 결과: 30개 unknown 칸 중 물은 수 13~14 대 8, decided 2 대 11, 추천 붙은 답 0 대 15. 같은 스킬 두 사본 차이 1~3칸
- 비용: 기록 없음 (시험 실행 1회 38초, $0.22)

### 2026-11-13-it6-7-all
- 종류: AB
- 스킬: 7c1e04d(0.47.0) 문구와 1daddfb
- 실행기·모델: `run_model.py`, sonnet low
- 사례×회수: 7개 사례 (회수 기록 없음)
- 결과: 84칸 중 물은 수 58 대 50. 대조군 질문 9회에 7개. mail-backfill의 "contact.created에 반응하는 팀 에이전트"는 평가자에 따라 5회 중 0~3회
- 비용: 기록 없음

## 2026-11-14 (세션 기록 `agent-docs/progress/20330283d264e832-spec-brief-skill-creator-skill.md`)

### 2026-11-14-dialogue-smoke
- 종류: 시험 실행
- 스킬: 0.47.0 (7c1e04d)
- 실행기·모델: `run_dialogue.py`, sonnet low, 최대 5턴; 사용자와 채점은 sonnet
- 사례×회수: mail-backfill × 1
- 결과: approval brief에 도달하지 못함(5턴). decision round는 선택지·추천 없이 진행. 결정 수 상한을 라운드마다 따로 세어 총 6개에도 분할 권고 없음. 나중 라운드의 사실 질문 7개, 그중 1개는 저장소가 답함
- 비용: $3.04, $0.40, 기록 없음

### 2026-11-14-dialogue-it1
- 종류: 기준치
- 스킬: 0.47.0 (7c1e04d)
- 실행기·모델: `run_dialogue.py`, sonnet medium, 최대 8턴; 사용자와 채점은 sonnet (`grade_dialogue.py`)
- 사례×회수: mail-backfill, log-retention, mail-backfill-facts, plan-quota × 2
- 결과: 8회 모두 approval brief 도달. 보고한 자기 선택이 사용자 선택과 같은 경우가 약 22개 결정 중 21개, 1개는 선택 없음. plan-quota 2회차는 따로 고르는 부분 4개에도 분할 권고 없음. 기록된 사실 검색은 관련 2개 표시·재질문 없음·무관 4개 언급 없음, 1회는 무관 파일 하나를 엶
- 비용: $23.09, $2.49, 기록 없음

### 2026-11-14-dialogue-it2
- 종류: AB
- 스킬: 0.48.0 작업본 대 0.47.0 (0.47.0 쪽은 2026-11-14-dialogue-it1 실행분을 다시 채점)
- 실행기·모델: `run_dialogue.py`, sonnet medium, 최대 8턴; 사용자와 채점은 sonnet
- 사례×회수: mail-backfill, log-retention, mail-backfill-facts, plan-quota × 2
- 결과 (0.48.0 대 0.47.0):
  - 첫 decision round 전에 picks 파일 기록 8/8 대 0/8
  - brief가 그 파일의 선택을 보고 8/8 대 0/8
  - 사용자 선택과 다른 자기 선택 9 대 1
  - 결정이 3개를 넘을 때 분할 권고 8/8 대 7/8
  - 대화당 실행 모델 비용 $4.66 대 $2.89, 턴 수 6.5 대 5, 8턴 상한 도달 3회
- 비용: $37.28, $3.54, 기록 없음 (이 세션 채점 약 34회 합산 추정 $5~10)

### 2026-11-14-firstmsg-regression
- 종류: 회귀
- 스킬: 0.48.0 작업본 대 0.47.0 (7c1e04d)
- 실행기·모델: `run_model.py`, sonnet low; 채점은 sonnet (`judge_message.py`), 집계는 `score.py`
- 사례×회수: 7개 사례 × 3회 × 2 스킬
- 결과 (0.48.0 대 0.47.0):
  - unknown을 묻거나 가정으로 드러낸 칸 53/72 대 56/72. 차이는 mail-backfill(13 대 9 / 18)에서 나옴, 그중 "contact.created에 반응하는 팀 에이전트" 0/3 대 2/3
  - 대조군 질문 합(3회 평균) 3.3 대 3.0
  - 대조군에서 추천으로 채점된 질문 5 대 0. 원문은 "있으면 A, 없으면 B"처럼 답마다 설계가 어떻게 갈리는지 적은 문장
  - 첫 메시지에 picks 언급 없음
- 비용: 실행 $2.71 + $2.61, 채점 $0.75 + $0.74

# brief 사실 질문 평가 (evaluation/brief_facts)

`workflow-approach` 스킬의 brief가 저장소에 없는 사실을 얼마나 잘 찾아내 묻는지 재는 개발용 도구입니다. 설치 payload에는 포함되지 않습니다.

## 구조

- 실행 모델: `claude -p --model <model> [--effort <level>]`(기본 haiku). 읽기 도구(Read, Grep, Glob)만 주고, 스킬 본문과 과제를 실제 `/workflow-approach` 호출과 같은 형식으로 넣습니다. 스킬이 사용자 답을 기다리는 첫 지점의 메시지를 출력으로 받습니다.
- 평가 모델: sonnet 에이전트가 사례 하나를 맡습니다. 실행 모델이 모르는 제품 맥락(`hidden_context`)을 쥐고, 실행 모델을 스킬 변형마다 여러 번 호출한 뒤 `grader.md`대로 채점합니다. 변형 파일은 읽지 않고 `cfg-k`, `cfg-m` 같은 이름만 봅니다.
- 대상 저장소: 실행 모델의 학습 시점 뒤에 만들어진 공개 저장소를 커밋으로 고정합니다(사례 파일의 `repo`).

## 사례 파일 (`cases/<id>.json`)

- `task`: 사용자가 쓴 요청.
- `hidden_context`: 평가 모델만 아는 제품 사실.
- `unknowns`: 저장소로 답할 수 없고 설계를 바꾸는 사실, 그리고 각 사실이 가르는 결정.
- `repo_answerable`: 저장소가 답하므로 사용자에게 물으면 안 되는 질문과 근거 위치.
- `dont_care`: 어떻게 정해도 되는 항목.

`unknowns`가 빈 사례는 대조군입니다. 물을 것이 없는 과제에서 질문이 늘어나는지를 봅니다.

## 실행

```bash
python3 evaluation/brief_facts/run_model.py [--model sonnet --effort low] --skill <SKILL.md> --case evaluation/brief_facts/cases/<id>.json \
  --repo <고정한 저장소 복제본> --run-dir <iteration>/eval-<id>/<config>/run-<n>
python3 evaluation/brief_facts/score.py <iteration>
```

`run_model.py`는 `outputs/output.md`, `meta.json`, `timing.json`을 쓰고, 평가 모델이 `judgement.json`을 씁니다. `score.py`는 `judgement.json`을 skill-creator 뷰어 형식의 `grading.json`으로 바꾸고 사례·변형별 평균을 출력합니다.

## 지표

- `asked` / `assumed` / `decided` / `absent`: `unknowns` 항목별 상태. 물었거나 가정으로 드러냈으면 찾아낸 것으로 봅니다. `decided`는 그 사실이 갈라야 할 선택을 묻지 않고 정한 경우입니다.
- `fact_questions` / `decision_questions`: 세계의 상태를 물었는지, 설계 선택을 골라 달라고 했는지.
- `repo_answerable_questions`, `noise_questions`: 저장소가 답하는 질문과 설계를 바꾸지 않는 질문의 수.
- `recommended_answers`: 질문에 자기 추천이나 기본값을 함께 준 수.

## 평가 항목

1. **사실 찾아내기** (이 디렉터리가 구현한 것): 첫 메시지에서 `unknowns`를 얼마나 드러내는가, 저장소가 답하는 것을 묻지 않는가.
2. **답을 받은 뒤의 분류**: 평가 모델이 물은 것에만 `hidden_context`로 답하고, 다음 메시지에서 사실이 가른 결정은 근거와 함께 확정되고 남은 결정만 사용자에게 가는지, `hidden_context`와 어긋나는 확정이 몇 개인지. 세션 이어가기와 쓰기 가능한 복제본이 필요합니다.
3. **추천 숨김**: 결정 라운드에 선택지와 추천이 없는지, 요청하면 선택지를 추천 없이 주는지.
4. **누적 사실 검색**: `agent-docs/facts/`에 관련 사실과 무관한 사실을 섞어 두고, 디렉터리를 통째로 읽지 않고 검색으로 찾는지, 찾은 사실을 다시 묻지 않고 날짜와 함께 가정으로 보이는지, 무관한 사실이 메시지에 나오지 않는지.
5. **결정 수 상한**: 사용자 결정이 3개를 넘는 과제에서 분할을 권하는지.

## 한계

- 사례의 정답 목록과 스킬 문구를 같은 작성자가 썼습니다. 평가 모델이 보고하는 정답 목록 문제(저장소가 실제로 답하는 항목, 목록에 없는 유용한 질문)를 사례에 반영해야 합니다.
- `claude -p` 한 번의 출력은 실제 대화형 세션과 다릅니다. 사용자 설정과 플러그인은 불러오지 않습니다.
- 평가 모델은 변형 이름만 가리므로 출력 형식에서 변형을 짐작할 수 있습니다.

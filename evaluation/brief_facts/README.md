# brief 사실 질문 평가 (evaluation/brief_facts)

`workflow-approach` 스킬의 brief가 저장소에 없는 사실을 얼마나 잘 찾아내 묻는지 재는 개발용 도구입니다. 설치 payload에는 포함되지 않습니다.

## 구조

- 실행 모델: `claude -p --model <model> [--effort <level>]`(기본 haiku). 읽기 도구(Read, Grep, Glob)만 주고, 스킬 본문과 과제를 실제 `/workflow-approach` 호출과 같은 형식으로 넣습니다. 스킬이 사용자 답을 기다리는 첫 지점의 메시지를 출력으로 받습니다.
- 평가 모델: sonnet 에이전트가 사례 하나를 맡습니다. 실행 모델이 모르는 제품 맥락(`hidden_context`)을 쥐고, 실행 모델을 스킬 변형마다 여러 번 호출한 뒤 `grader.md`대로 채점합니다. 변형 파일은 읽지 않고 `cfg-k`, `cfg-m` 같은 이름만 봅니다.
- 대상 저장소: 실행 모델의 학습 시점 뒤에 만들어진 공개 저장소를 커밋으로 고정합니다(사례 파일의 `repo`). 지금은 문서 변환 라이브러리 `firecrawl/anydoc`(사례 `batch-cli`, `cache`, `tsv-control`)와 웹 서비스 `diwenne/openreply`(사례 `log-retention`, `logs-filter-control`), 에이전트형 CRM `trycompai/crm`(사례 `mail-backfill`, `no-email-filter-control`)입니다. 복제본에는 harness를 설치하지 않으며, 실행 지시문이 그 상태를 정상으로 알려 줍니다. `trycompai/crm`은 자체 `CLAUDE.md`(→ `AGENTS.md`)가 있어 실행 모델이 그 규칙(메시지 끝의 Issues 목록 등)도 따릅니다.
- AA 대조: 같은 스킬 파일을 다른 변형 이름으로 두 번 넣으면, 두 변형의 차이가 실행 모델과 평가 모델의 잡음 크기를 보여 줍니다. 변형 간 차이는 이 잡음보다 클 때만 읽습니다.

측정 기록은 `runs.md`에 한 측정에 한 항목씩 남깁니다.

## 사례 파일 (`cases/<id>.json`)

- `task`: 사용자가 쓴 요청.
- `hidden_context`: 평가 모델만 아는 제품 사실.
- `unknowns`: 저장소로 답할 수 없고 설계를 바꾸는 사실, 그리고 각 사실이 가르는 결정.
- `repo_answerable`: 저장소가 답하므로 사용자에게 물으면 안 되는 질문과 근거 위치.
- `dont_care`: 어떻게 정해도 되는 항목.
- `minor_unknowns` (선택): 저장소가 답하지 못하지만 드문 경우라 가정으로 적는 것이 기대되는 사실. 물어도 감점하지 않습니다.
- `settled_without_fact` (선택): 어떤 사실과도 무관하게 옳은 선택이 있어 묻지 않고 정해도 되는 결정.

- `seed_facts` (선택): 실행 전에 복제본의 `agent-docs/facts/`에 넣는 기록. 각 항목은 `file`, `text`, `relevant`(이 과제와 관련 있는지).
- `user_named_decision` (선택): 대화 평가에서 시뮬레이션 사용자가 초대 문장에 답할 내용.
- `expected_user_decisions` (선택): 사용자 몫으로 예상되는 결정. 사례 작성자용 메모이며 채점에는 쓰지 않습니다.

`unknowns`가 빈 사례는 대조군입니다. 물을 것이 없는 과제에서 질문이 늘어나는지를 봅니다. `mail-backfill-facts`는 `mail-backfill`에 기록된 사실 6개(관련 2개)를 넣은 사례이고, `plan-quota`(`diwenne/openreply`)는 사용자 결정이 3개를 넘는 과제입니다.

## 실행

```bash
python3 evaluation/brief_facts/run_model.py [--model sonnet --effort low] --skill <SKILL.md> --case evaluation/brief_facts/cases/<id>.json \
  --repo <고정한 저장소 복제본> --run-dir <iteration>/eval-<id>/<config>/run-<n>
python3 evaluation/brief_facts/score.py <iteration>
```

`run_model.py`는 `outputs/output.md`, `meta.json`, `timing.json`을 쓰고, 평가 모델이 `judgement.json`을 씁니다. 평가 모델을 에이전트 대신 스크립트로 돌릴 때는 `python3 evaluation/brief_facts/judge_message.py <iteration>`이 `grader.md`와 출력 스키마로 sonnet을 불러 `judgement.json`과 `judge_cost.json`을 씁니다. `score.py`는 `judgement.json`을 skill-creator 뷰어 형식의 `grading.json`으로 바꾸고 사례·변형별 평균을 출력합니다.

### 대화 평가 (approval brief까지)

```bash
python3 evaluation/brief_facts/run_dialogue.py [--model sonnet --effort medium] --skill <SKILL.md> --case evaluation/brief_facts/cases/<id>.json \
  --repo <고정한 저장소 복제본> --run-dir <iteration>/eval-<id>/<config>/run-<n>
python3 evaluation/brief_facts/grade_dialogue.py <iteration>
```

- `run_dialogue.py`는 실행 디렉터리 안에 저장소를 `git clone --shared`로 복제하고, 실행 모델에 Read, Grep, Glob, Write, Edit를 줍니다. 쓰기는 그 복제본과 `scratch/`(세션 scratchpad 역할)로 한정됩니다. 같은 세션을 `--resume`으로 이어 가며, 턴마다 sonnet 시뮬레이션 사용자가 `hidden_context`만 가지고 답합니다. 사용자는 물은 사실에만 답하고, 틀린 가정만 고치고, 첫 결정 요청에는 "각 결정마다 선택지를 보여줘."라고 답한 뒤 결정합니다. approval brief에 이르거나 실행 모델이 8턴을 쓰면 끝납니다.
- 출력: `outputs/dialogue.md`, 실행 모델이 쓴 spec(`specs-*.md`), 사실 기록(`facts-*.md`), picks 파일(`scratch-*.md`), `transcript.json`(턴별 도구 호출 포함), `meta.json`, `timing.json`.
- `grade_dialogue.py`는 `dialogue_grader.md`대로 sonnet이 대화 전체를 판정한 `dialogue_judgement.json`과, 파일·도구 호출을 직접 검사한 결과를 합쳐 `grading.json`을 씁니다.
- 비용: sonnet medium 기준 대화 하나에 실행 모델 $1.4~8.0(평균 $2.9~4.7), 시뮬레이션 사용자 $0.15~0.75.

## 지표

- `asked` / `assumed` / `decided` / `dismissed` / `absent`: `unknowns` 항목별 상태. 물었거나 가정으로 드러냈으면 찾아낸 것으로 봅니다. `decided`는 그 사실이 갈라야 할 선택을 묻지 않고 정한 경우, `dismissed`는 그 영역이 과제와 무관하다고만 적은 경우입니다.
- `fact_questions` / `decision_questions`: 세계의 상태를 물었는지, 설계 선택을 골라 달라고 했는지.
- `repo_answerable_questions`, `noise_questions`: 저장소가 답하는 질문과 설계를 바꾸지 않는 질문의 수.
- `recommended_answers`: 질문에 자기 추천이나 기본값을 함께 준 수.
- `minor_questions`: `minor_unknowns`만 겨냥한 질문 수.
- `decisions_as_assumptions`: 가정 목록에 적힌 문장 중 세계의 사실이 아니라 소프트웨어가 할 일을 적은 문장 수. 가정을 확인해 주는 것으로 결정까지 승인되는 경우를 셉니다.
- `invitation_examples`: 직접 정하고 싶은 결정을 적어 달라는 초대 문장이 후보 결정을 예로 들었는지(1 또는 0).

## 평가 항목

1. **사실 찾아내기** (이 디렉터리가 구현한 것): 첫 메시지에서 `unknowns`를 얼마나 드러내는가, 저장소가 답하는 것을 묻지 않는가.
2. **답을 받은 뒤의 분류** (`run_dialogue.py`): 답한 사실이 가른 결정이 그 답을 인용해 확정되는지, 같은 사실을 다시 묻거나 어기지 않는지, `hidden_context`와 어긋나는 확정이 몇 개인지, 나중 라운드의 사실 질문 중 저장소가 답하는 것이 있는지.
3. **추천 숨김** (`run_dialogue.py`): 결정 라운드에 선택지와 추천이 없는지, 요청하면 결과가 붙은 선택지를 추천 없이 주는지, 사용자 답 전에 기록한 자기 선택(picks 파일)을 approval brief가 그대로 비교하는지.
4. **누적 사실 검색** (`mail-backfill-facts`): 관련 기록을 날짜와 함께 가정으로 보이는지, 다시 묻지 않는지, 무관한 기록이 메시지에 나오지 않는지, 디렉터리를 나열하거나 무관한 파일을 열지 않는지(`transcript.json`의 도구 호출로 검사).
5. **결정 수 상한** (`plan-quota` 외): 대화 전체의 사용자 결정이 3개를 넘을 때 분할을 권하는지.
6. **spec과 approval brief**: spec 파일 이름과 frontmatter, spec에 brief가 섞이지 않는지, 사용자 답과 결정이 spec에 반영되는지, 답한 사실이 `agent-docs/facts/` 형식으로 기록되는지.

## 한계

- 사례의 정답 목록과 스킬 문구를 같은 작성자가 썼습니다. 평가 모델이 보고하는 정답 목록 문제(저장소가 실제로 답하는 항목, 목록에 없는 유용한 질문)를 사례에 반영해야 합니다.
- `score.py`는 첫 메시지만 채점합니다. 사용자 결정으로 분류해 결정 라운드로 미룬 항목은 `absent`로 잡히므로, 미룬 것과 놓친 것은 대화 평가로 가릅니다.
- 대화 평가의 시뮬레이션 사용자는 결정 이유를 말하며 묻지 않은 숨은 사실을 꺼내기도 합니다. 숨은 사실을 찾아내는 능력은 첫 메시지 채점으로 봅니다.
- 대화 평가 채점의 `contradictions`와 `missing_from_spec`은 잡음이 큽니다. 채점자가 "모순 아님"이라 적고도 항목으로 넣는 경우가 있어, 원문 대조 없이 수치로만 읽지 않습니다.
- 사실의 일부에만 닿는 질문에도 `asked`를 줍니다(예: "CI인가 터미널인가"는 CPU·메모리 한도까지 묻지 않습니다). 절대 수치보다 변형 간 차이를 봅니다.
- `claude -p` 한 번의 출력은 실제 대화형 세션과 다릅니다. 사용자 설정과 플러그인은 불러오지 않습니다.
- 평가 모델은 변형 이름만 가리므로 출력 형식에서 변형을 짐작할 수 있습니다.

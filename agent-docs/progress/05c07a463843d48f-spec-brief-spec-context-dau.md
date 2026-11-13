---
session: ba7e2a0d-ff0b-4a0c-b4cf-644931bd9ec8
before: none
previous: none
branch: brief-fact-questions
commit: bc71362de7179ea459c1d9d1ac574cdfc52ea9e3
---

# Brief: fact questions, user-owned engineering decisions, and a fact-question evaluation

## Next Session

### State
- the Brief section of the workflow-approach skill is rewritten as a draft (decision sweep with reversal conditions and dimensions, significance criteria, three rounds: understanding, decision without options or recommendation, approval brief; cap of 3 user decisions with a split recommendation; project facts under agent-docs/facts/ found by grep); rules 5-7, the Assumptions and Defaults column, and Workflow step 2 follow it; that draft is commit bc71362 on branch brief-fact-questions, a checkpoint without a VERSION bump, a migration entry, or `harness.py update`, so .harness/ and .claude/ still hold the 0.45.0 skill; after bc71362 the skill source gained, uncommitted: a context pass over the eight dimensions before the per-decision sweep, an assumption defined as a sentence true or false whatever gets built, no guess on a fact question and no moving of a significant unknown into the assumptions, a single "Not asked" line whose reasons may not be that the repository is silent, an invitation without examples, no decisions or search notes in the understanding round, and exclusions that drop a safeguard or cannot be added back treated as decisions
  - files: harness/skills/workflow-approach/SKILL.md
- evaluation/brief_facts/ holds five cases: on firecrawl/anydoc@e7178e0 batch-cli (7 unknown facts), cache (5; the cache-key item was removed because a content-hash key is right whatever the answer) and tsv-control (none, one minor unknown); on diwenne/openreply@c78b2d2 log-retention (6) and logs-filter-control (none); plus a runner that calls `claude -p --model <m>` with read-only tools, grading rules for a sonnet evaluator, and a scorer that writes skill-creator grading.json; after bc71362 the grader gained the `dismissed` status, multi-target questions, `decisions_as_assumptions` and `invitation_examples`, and the runner tells the model the missing harness is expected (uncommitted)
  - files: evaluation/brief_facts/README.md, evaluation/brief_facts/run_model.py, evaluation/brief_facts/score.py, evaluation/brief_facts/grader.md, evaluation/brief_facts/cases
- iteration 1 ran: 3 cases x 2 skill variants x 3 haiku runs, graded by one sonnet agent per case, all 18 runs succeeded; over the 39 unknown-fact slots of batch-cli and cache the new skill scored asked 22, decided 11, absent 6 and the HEAD skill asked 12, decided 17, absent 10; of all questions the new skill asked 23 as facts and 6 as design choices, the HEAD skill 1 and 25; no run of either variant asked about CPU or memory (batch-cli U2) or about other callers (batch-cli U7), and all 6 cache runs fixed the cache key without asking (cache U4); outputs are in the session scratchpad under ws/iteration-1, outside the repository
  - files: evaluation/brief_facts/score.py, evaluation/brief_facts/grader.md, evaluation/brief_facts/cases, harness/skills/workflow-approach/SKILL.md
- the same 18 runs with `--model sonnet --effort low` as the model under test (skill, cases, grader unchanged; outputs under ws/iteration-1-sonnet-low): new skill asked 26, assumed 1, decided 6, absent 6 of 39; HEAD skill asked 15, decided 16, absent 8; new-skill questions were 31 facts and 1 design choice with 1 recommended answer (haiku: 23, 6, 11); on tsv-control the new skill asked 1 question in 3 runs (haiku: 5); with the new skill neither model asked about CPU or memory (batch-cli U2, 0 of 6 runs) or other callers (batch-cli U7, 0 of 6 asked, 1 assumed), and both fixed the cache key in all runs (cache U4); a sonnet-low tsv-control message still listed a design choice ("탭을 강제하지 않습니다") under assumptions about the world
  - files: evaluation/brief_facts/run_model.py, evaluation/brief_facts/cases, harness/skills/workflow-approach/SKILL.md
- iteration 2 (sonnet at low effort, 5 cases x 3 variants x 3 runs, all 45 succeeded; ws/iteration-2-sonnet-low): over 54 unknown-fact slots the bc71362 draft scored asked 36, assumed 2, decided 12, absent 4 with 41 questions, 40 design choices listed as assumptions and examples in the invitation in 10 of 15 runs; the variant with the context pass and the stricter round rules scored asked 39, assumed 4, decided 8 with 57 questions (5 repository-answerable, 4 noise); the same plus the "Not asked" line scored asked 37, assumed 9, dismissed 3, decided 2 with 47 questions (1 repository-answerable, 2 noise), 5 design choices as assumptions and no invitation examples
  - files: harness/skills/workflow-approach/SKILL.md, evaluation/brief_facts/cases, evaluation/brief_facts/grader.md, evaluation/brief_facts/score.py
- iteration 3 (ws/iteration-3; the "Not asked" variant with the single-line rule and the no-moving rule): sonnet at low effort scored asked 44, assumed 1, dismissed 2, decided 5, absent 2 with 58 questions (5 noise) and 9 design choices as assumptions; haiku scored asked 44, dismissed 2, decided 4, absent 4 with 49 questions (2 decision-form, 0 recommended answers, 3 noise); haiku with the bc71362 draft scored asked 31, decided 12, absent 11 with 40 questions (10 decision-form, 12 recommended answers, 7 noise) and 35 design choices as assumptions
  - files: harness/skills/workflow-approach/SKILL.md, evaluation/brief_facts/cases, evaluation/brief_facts/grader.md, evaluation/brief_facts/score.py
- iteration 4 (ws/iteration-4; adds the exclusion rule): on log-retention, "planned features need old rows" and "deleted logs must be recoverable" were decided in 1 of 6 runs each (iteration 3: 3 and 4 of 6), asked in 1 of 6 each, and absent in the rest; one message deferred the archive choice to the decision round, which the first-message grading counts as absent; on the two control cases sonnet at low effort asked 5 questions in 6 runs, the same as in iteration 3
  - files: harness/skills/workflow-approach/SKILL.md, evaluation/brief_facts/cases/log-retention.json, evaluation/brief_facts/grader.md

### Next Step
- commit the post-bc71362 skill and evaluation changes when the user asks
  - files: harness/skills/workflow-approach/SKILL.md, evaluation/brief_facts
- case-file changes the evaluators reported and that were held back to keep iterations comparable: log-retention has no item for whether a comment older than the reconciler's 72-hour lookback can come back (asked in 4 of 9 runs of iteration 2), and docs/stack.md names a 0.5 GB free database plan while the hidden context says 10 GB; batch-cli U2, U3, U4 and U7 and cache U3, U5 and U6 give full credit to questions that reach only part of the fact
  - files: evaluation/brief_facts/cases, evaluation/brief_facts/grader.md
- evaluation items 2 to 5 of evaluation/brief_facts/README.md (classification after answers, hidden recommendation in the decision round, fact search, decision cap) are not implemented; item 2 is what would show whether a choice deferred from the first message reaches the user in the decision round
  - files: evaluation/brief_facts/README.md
- after the draft settles: add agent-docs/facts/ to the installer (managed directory, migration entry, VERSION bump), run `python3 installer/harness.py update . --no-commit`, and run the tests
  - files: installer/harness.py, harness/VERSION, harness/skills/workflow-approach/SKILL.md
- the user chose a per-person untracked preference file copied into new worktrees; an understanding round for that feature (untracked file, .gitignore line, post-checkout copy, installer and migration, version 0.47.0) was sent and two fact questions are unanswered: whether other local files should be copied too, and whether collaborators already use installed repositories; decision-history aggregation from spec-logs and the category column are not drafted
  - files: harness/skills/workflow-approach/SKILL.md

### Constraints
- "추천을 숨기는 순서를 넣는다. trade-off를 포함한 선택지도 요청시 제공한다. (힌트 없이 생각하는 시간을 마련)"
  - source: user prompt 2 in this session
- "상한 제거, 엔지니어링 결정은 상한을 n개로 하고, 그 이상이면 유저에게 한 번에 처리할 일을 나눌 것을 권고."
  - source: user prompt 2 in this session
- "누적시키는 건 한 가지 신경 써야 하는게 context를 오염시킬 수 있어서 읽고 확인하는 게 아니라 검색어로 찾아 읽는 방향으로 가는 게 좋을 것 같아."
  - source: user prompt 5 in this session
- "일단 협업을 고려하면 각자 하게 두는 게 맞지. 음..  worktree 만들 때 복사하게 해줘"
  - source: user prompt 7 in this session
- "sonnet-haiku 구조로 sub agent를 호출해서 확인해. sonnet이 임의의 context를 가지고 haiku를 불러서 받아보고, 얼마나 잘 구성해내는지 skill prompt를 평가하는 거야, 사용할 repo는 knowledge cutoff 이후 1k star 이상 아무거나."
  - source: user prompt 5 in this session

### Verify
- `git diff master --stat -- harness/skills/workflow-approach/SKILL.md` shows the draft; `git status --short .harness .claude` prints nothing while the installed copy is unchanged
  - files: harness/skills/workflow-approach/SKILL.md
- `python3 evaluation/brief_facts/run_model.py --skill harness/skills/workflow-approach/SKILL.md --case evaluation/brief_facts/cases/cache.json --repo <clone of firecrawl/anydoc at e7178e0> --run-dir <dir>` writes outputs/output.md, meta.json, and timing.json
  - files: evaluation/brief_facts/run_model.py, evaluation/brief_facts/cases

### Dead Ends
- the wording "an unknown you are willing to guess belongs under assumptions" moved unknowns behind significant decisions (file count, where it runs) from questions into the assumptions list: 9 assumed against 37 asked in iteration 2; replaced by a rule against moving them
  - files: harness/skills/workflow-approach/SKILL.md
- a runner prompt made of the skill body plus `ARGUMENTS:` and a stop rule ending in "Do not create or edit files" made haiku skip the workflow and answer the tsv task directly as a no-edit session; wrapping the prompt in the `/workflow-approach` command tags and stating that the session ends where the skill waits for the user fixed it
  - files: evaluation/brief_facts/run_model.py

### Related
- none: no earlier record covers the brief classification or this evaluation

## Record

### Changes
- harness/skills/workflow-approach/SKILL.md: Brief section replaced (Decision sweep, Rounds, Project facts); Identity and lifecycle rules 5-7, the Assumptions and Defaults approval column, and Workflow step 2 adjusted
- evaluation/brief_facts/: README.md, run_model.py, score.py, grader.md, cases/batch-cli.json, cases/cache.json, cases/tsv-control.json added
- AGENTS.md: the project definition names evaluation/brief_facts/
- after bc71362: harness/skills/workflow-approach/SKILL.md (Decision sweep context pass; Understanding round rules for assumptions, fact questions, Not asked, invitation, exclusions)
- after bc71362: evaluation/brief_facts/cases (batch-cli U2 reworded, cache U4 removed, tsv-control minor unknown, new log-retention and logs-filter-control), grader.md, score.py, run_model.py stop rule, README.md

### Commands
- `gh api search/repositories` with `created:>2026-07-15 stars:>1000`; `git clone --depth 1 https://github.com/firecrawl/anydoc.git` into the session scratchpad (HEAD e7178e099b6bf9171e2c52b832cbdb4134b69112)
- `python3 evaluation/brief_facts/run_model.py` smoke runs: tsv-control with the new skill, cache with the new and the HEAD skill
- three sonnet agents, one per case, each ran six haiku runs and wrote judgement.json; `python3 evaluation/brief_facts/score.py <iteration dir>`; skill-creator `scripts.aggregate_benchmark` and `eval-viewer/generate_review.py --static`
- the same three-agent run with `--model sonnet --effort low` as the model under test, then the same scoring and viewer commands
- `git clone --depth 1 https://github.com/diwenne/openreply.git` into the session scratchpad (HEAD c78b2d2f68c9764ef7a7dde51dfa5bfa99304a09); one smoke run of cfg-r on log-retention with sonnet at low effort
- iterations 2 to 4: 5 + 5 + 2 sonnet evaluator agents, 45 + 45 + 12 runs of the model under test; `python3 evaluation/brief_facts/score.py <dir>`; skill-creator `scripts.aggregate_benchmark` and `eval-viewer/generate_review.py --static` for iterations 2 and 3
- tests and `harness.py update` not run

### Failed Attempts
| attempt | failure evidence | cause |
| --- | --- | --- |
| runner prompt without the slash-command wrapper and with "Do not create or edit files" | haiku output for tsv-control began "이 세션은 파일을 만들거나 수정하지 않는 모드라서" and listed code changes instead of an understanding round | hypothesis: the stop rule read as a session mode and nothing marked the skill as invoked |

### Sources
- https://github.com/firecrawl/anydoc at e7178e099b6bf9171e2c52b832cbdb4134b69112 (README.md, src/lib.rs, src/package/limits.rs, src/error.rs, src/formats/csv.rs, node/cli.js, node/anydoc.js)
- https://github.com/diwenne/openreply at c78b2d2f68c9764ef7a7dde51dfa5bfa99304a09 (docs/stack.md, docs/delivery-retries.md, prisma/schema.prisma, vercel.json, scripts/cron.sh, app/api/logs/route.ts, lib/queue/dm-worker.ts, lib/polling/comment-reconciler.ts, lib/reports/data.ts, app/privacy/page.tsx)
- skill-creator plugin: scripts/aggregate_benchmark.py, references/schemas.md, eval-viewer/generate_review.py (directory layout and grading.json fields)

### User Requests

#### 1 — 2026-11-13T09:16:18Z

> 현재의 spec & brief의 체재의 문제점을 찾았어.
> 
> 엔지니어로서 결정해야 되는 사항들이 이미 결정된 상태로 들어오니까, 인지 마찰이 낮아지고, 학습 효과가 떨어지고, 프로젝트 관리자로서 제대로 프로젝트를 파악하기 어려워졌어.
> 
> 여기서 문제는 spec을 모두 내가 결정하는 건 내가 원하는 게 아니라는 거야. 어떻게 내가 결정해야 할 것과, 내가 결정하지 않아도 되는 걸 구분할 수 있을까??
> 
> 이 기준을 정하기가 어려운 이유는 사용자는 알고 있는데, context에는 충분히 주어지지 못한 정보가 있기 때문인 것 같아. 이를테면 이 프로덕트의 예상 DAU가 몇 만이고 피크는 몇인가, 혹은 이후 개발할 기능은 어떤 것들이 있는가, 이런 것들은 AI agent입장에서는 알 수 없는 정보지.
> 
> 또한 엔지니어로서 결정을 내려야하는 것 / 어떻게 정해지더라도 크게 상관 없는 것을 구분하는 기준을 정할 수 있을까?

#### 2 — 2026-11-13T11:54:41Z

> 우려: runtime에 context에 없는 사실이 필요하다는 것을 model이 어떻게 판단하는가. (runtime은 지금의 fable보다 성능이 떨어지는 모델을 사용하고, 판단력이 지금처럼 좋지 않을 수 있다.)
> 
> 우선은 표의 2, 3행이면 사용자 결정이 필요한 것으로 하고, 1-4 케이스 중 어디에 해당하는 지를 같이 표시해주자.. 라고 생각했는데, 뒤에서 그걸 보충 설명하네. 뭐 어떻게 결정해도 상관 없는 거라면, 앞으로도 상관 없을 가능성이 높지 (AI agent를 이용하는 개발 트렌드 측면에서)
> 
> 아 뭐야 정보 비대칭도 다루네.
> 
> ---
> 결정 사항
> 1. 추천을 숨기는 순서를 넣는다. trade-off를 포함한 선택지도 요청시 제공한다. (힌트 없이 생각하는 시간을 마련)
> 2. 상한 제거, 엔지니어링 결정은 상한을 n개로 하고, 그 이상이면 유저에게 한 번에 처리할 일을 나눌 것을 권고.
> 
> 엔지니어링 결정을 해야하는 포인트도 먼저 알려주는 게 좋을까? 아니면 이것도 유추하게 할까? 트레이드 오프 따져봐

#### 3 — 2026-11-13T11:58:04Z

> 누적 사용에 따라 사용자에게 맞춰지는 건 어떻게 할거야?

#### 4 — 2026-11-13T12:09:03Z

> /skill-creator 이걸 이용해서 스킬을 수정하고
>  Evaluation 전략을 구성하자.
> 
> 1. 모르는 사실을 얼마나 잘 조각해내는가. (우리가 논의한 방향으로)
> 
> 그리고 누적시키는 건 한 가지 신경 써야 하는게 context를 오염시킬 수 있어서 읽고 확인하는 게 아니라 검색어로 찾아 읽는 방향으로 가는 게 좋을 것 같아.

#### 5 — 2026-11-13T12:10:40Z

> /skill-creator:skill-creator 이걸 이용해서 스킬을 수정하고
>  Evaluation 전략을 구성하자.
> 
> 1. 모르는 사실을 얼마나 잘 조각해내는가. (우리가 논의한 방향으로) (sonnet-haiku 구조로 sub agent를 호출해서 확인해. sonnet이 임의의 context를 가지고 haiku를 불러서 받아보고, 얼마나 잘 구성해내는지 skill prompt를 평가하는 거야, 사용할 repo는 knowledge cutoff 이후 1k star 이상 아무거나.)
> 
> 그리고 누적시키는 건 한 가지 신경 써야 하는게 context를 오염시킬 수 있어서 읽고 확인하는 게 아니라 검색어로 찾아 읽는 방향으로 가는 게 좋을 것 같아.

#### 6 — 2026-11-13T12:32:36Z

> sonnet-low로 다시해봐. 너무 lightweight이라 그럴 수도 있어.

#### 7 — 2026-11-13T12:34:08Z

>  "무엇을 직접 정하고 싶은가" 선호를 git에 올리는 파일에 둘지 로컬 파일에 둘지입니다. - 이거 난제네.
> 
> 일단 협업을 고려하면 각자 하게 두는 게 맞지. 음..  worktree 만들 때 복사하게 해줘

#### 8 — 2026-11-13T12:38:17Z

> 일단 개선 됐으니까 commit해.

#### 9 — 2026-11-13T12:40:12Z

> 추가 개선을 해보자고

#### 10 — 2026-11-13T13:11:00Z

> 커밋

---
session: ba7e2a0d-ff0b-4a0c-b4cf-644931bd9ec8
before: none
previous: none
branch: brief-fact-questions
commit: 7bcaf1e6d779aeb0a71f12fe1d2b732679e3823d
---

# Brief: fact questions, user-owned engineering decisions, and a fact-question evaluation

## Next Session

### State
- the workflow-approach Brief section (decision sweep with a context pass that follows what the change sets off and stops at additions existing callers never see; reversal conditions; significance criteria; understanding round with fact questions, assumptions true or false whatever gets built, one "Not asked" line, an invitation without examples; decision round without options or recommendation; approval brief; cap of 3 user decisions; project facts under agent-docs/facts/ found by grep) ships as harness 0.47.0: VERSION, a 0.47.0 migration entry that changes no files, the installed copy synced by `harness.py update`, agent-docs/facts/ exempt from index.md and stale.md in the index rule and in verify_rules.py, with a test
  - files: harness/skills/workflow-approach/SKILL.md, harness/VERSION, installer/harness.py, harness/git/verify_rules.py, harness/instructions/index-and-staleness.md, tests/test_doc_records.py
- evaluation/brief_facts/ holds the runner, grading rules, scorer, and seven cases on three repositories: firecrawl/anydoc@e7178e0 (batch-cli, cache, tsv-control), diwenne/openreply@c78b2d2 (log-retention, logs-filter-control), trycompai/crm@c9473b8 (mail-backfill, no-email-filter-control); iteration outputs stay in the session scratchpad
  - files: evaluation/brief_facts/README.md, evaluation/brief_facts/cases/mail-backfill.json, evaluation/brief_facts/cases/no-email-filter-control.json
- measured with sonnet at low effort: against the master skill on mail-backfill (iteration 5) the 1daddfb skill asked 13-14 of 30 unknown-fact slots against 8 and decided 2 against 11, with 0 recommended answers against 15, while two copies of the same skill differed by 1 to 3 slots; across all seven cases (iterations 6 and 7) the final wording asked 58 of 84 slots against 50 for 1daddfb, and the controls stayed at 7 questions in 9 runs; "team agents react to contact.created" on mail-backfill was asked in 0 to 3 of 5 runs depending on the evaluator and no output traced the event
  - files: harness/skills/workflow-approach/SKILL.md, evaluation/brief_facts/grader.md
- comments and docstrings that restated code (module docstrings of verify_rules, progress_hook, isolation, session_metrics, telemetry, generate, workflow_marker; first lines of seed, session_lock, hook_shared; two function docstrings; the pre-commit header; section separators and one restating comment in tests; unresolvable labels U5 and QR3) were removed, and 15 retrospective rows in agent-docs/spec-logs that a test run, an error message, or git history reproduces were removed, leaving a none row where a table emptied
  - files: harness/git/pre-commit, harness/lib/hook_shared.py, agent-docs/spec-logs
- branch brief-fact-questions is pushed and PR #38 (https://github.com/Doggy-Footprint/harness/pull/38) is open against master with a Korean title and description
  - files: none

### Next Step
- evaluation items 2 to 5 of evaluation/brief_facts/README.md (classification after answers, hidden recommendation in the decision round, fact search, decision cap) are not implemented; item 2 would show whether a choice deferred from the first message reaches the user in the decision round; re-checked at 7c1e04d, the README still lists them as not implemented
  - commit: 7c1e04d; files: evaluation/brief_facts/README.md
- case-file changes evaluators reported: log-retention lacks an item for comments older than the reconciler's 72-hour lookback, and docs/stack.md names a 0.5 GB plan while its hidden context says 10 GB; mail-backfill lacks items for whether reps already connected need the backfill and how many reps connect at once; several unknowns give full credit to questions that reach part of the fact
  - files: evaluation/brief_facts/cases
- the user chose a per-person untracked preference file copied into new worktrees; two fact questions sent for it are unanswered: whether other local files should be copied too, and whether collaborators already use installed repositories
  - files: none

### Constraints
- "추천을 숨기는 순서를 넣는다. trade-off를 포함한 선택지도 요청시 제공한다. (힌트 없이 생각하는 시간을 마련)"
  - source: user prompt 2 in this session
- "상한 제거, 엔지니어링 결정은 상한을 n개로 하고, 그 이상이면 유저에게 한 번에 처리할 일을 나눌 것을 권고."
  - source: user prompt 2 in this session
- "누적시키는 건 한 가지 신경 써야 하는게 context를 오염시킬 수 있어서 읽고 확인하는 게 아니라 검색어로 찾아 읽는 방향으로 가는 게 좋을 것 같아."
  - source: user prompt 5 in this session
- "일단 협업을 고려하면 각자 하게 두는 게 맞지. 음..  worktree 만들 때 복사하게 해줘"
  - source: user prompt 7 in this session
- "필요 없다의 기준 = 미래에 쉽게 재현하거나 복구할 수 있는 정보"
  - source: user message during the commit-and-PR request in this session (comments and retrospectives)
- "sonnet-haiku 구조로 sub agent를 호출해서 확인해. sonnet이 임의의 context를 가지고 haiku를 불러서 받아보고, 얼마나 잘 구성해내는지 skill prompt를 평가하는 거야, 사용할 repo는 knowledge cutoff 이후 1k star 이상 아무거나."
  - source: user prompt 5 in this session

### Verify
- `diff harness/skills/workflow-approach/SKILL.md .agents/skills/workflow-approach/SKILL.md` prints nothing and `cat .harness/VERSION` prints 0.47.0; `HARNESS_TEXT_TESTS=1 .venv/bin/python -m unittest discover -s tests` passes (system python3 lacks pytest and hypothesis)
  - files: harness/VERSION, .harness/VERSION, tests
- `python3 evaluation/brief_facts/run_model.py --model sonnet --effort low --skill harness/skills/workflow-approach/SKILL.md --case evaluation/brief_facts/cases/mail-backfill.json --repo <clone of trycompai/crm at c9473b8> --run-dir <dir>` writes outputs/output.md, meta.json, and timing.json (smoke run: 38 s, $0.22)
  - files: evaluation/brief_facts/run_model.py, evaluation/brief_facts/cases/mail-backfill.json

### Dead Ends
- the wording "an unknown you are willing to guess belongs under assumptions" moved unknowns behind significant decisions (file count, where it runs) from questions into the assumptions list: 9 assumed against 37 asked in iteration 2; replaced by a rule against moving them; at 7c1e04d the wording is absent from SKILL.md (`grep -n "willing to guess"` prints nothing)
  - commit: 7c1e04d; files: harness/skills/workflow-approach/SKILL.md
- a runner prompt made of the skill body plus `ARGUMENTS:` and a stop rule ending in "Do not create or edit files" made haiku skip the workflow and answer the tsv task directly as a no-edit session; the current runner wraps the prompt in the `/workflow-approach` command tags and states that the session ends where the skill waits for the user
  - commit: 1daddfb; files: evaluation/brief_facts/run_model.py

### Related
- none: no earlier record covers the brief classification or this evaluation

## Record

### Changes
- harness/skills/workflow-approach/SKILL.md: Brief section replaced (Decision sweep, Rounds, Project facts); Identity and lifecycle rules 5-7, the Assumptions and Defaults approval column, and Workflow step 2 adjusted
- evaluation/brief_facts/: README.md, run_model.py, score.py, grader.md, cases/batch-cli.json, cases/cache.json, cases/tsv-control.json added
- AGENTS.md: the project definition names evaluation/brief_facts/
- after bc71362: harness/skills/workflow-approach/SKILL.md (Decision sweep context pass; Understanding round rules for assumptions, fact questions, Not asked, invitation, exclusions)
- after bc71362: evaluation/brief_facts/cases (batch-cli U2 reworded, cache U4 removed, tsv-control minor unknown, new log-retention and logs-filter-control), grader.md, score.py, run_model.py stop rule, README.md
- after 1daddfb: evaluation/brief_facts/cases/mail-backfill.json and no-email-filter-control.json added; README.md names trycompai/crm and the AA comparison
- after 1daddfb: SKILL.md context pass (what the change sets off; additions callers never see), Not asked reason, safeguard-on-new-input rule; harness/VERSION 0.47.0; installer/harness.py migrate_brief_fact_questions; verify_rules.py FACT_DOC_DIRS; index-and-staleness.md facts exemption; README.md Spec step and agent-docs row; tests version pins and a facts test; installed copy synced
- comment cleanup: docstrings and comments that restate code removed in harness/, installer/, tests/, evaluation/selfcheck/evaluate.py; reproducible retrospective rows removed in six agent-docs/spec-logs files

### Commands
- `gh api search/repositories` with `created:>2026-07-15 stars:>1000`; `git clone --depth 1 https://github.com/firecrawl/anydoc.git` into the session scratchpad (HEAD e7178e099b6bf9171e2c52b832cbdb4134b69112)
- `python3 evaluation/brief_facts/run_model.py` smoke runs: tsv-control with the new skill, cache with the new and the HEAD skill
- three sonnet agents, one per case, each ran six haiku runs and wrote judgement.json; `python3 evaluation/brief_facts/score.py <iteration dir>`; skill-creator `scripts.aggregate_benchmark` and `eval-viewer/generate_review.py --static`
- the same three-agent run with `--model sonnet --effort low` as the model under test, then the same scoring and viewer commands
- `git clone --depth 1 https://github.com/diwenne/openreply.git` into the session scratchpad (HEAD c78b2d2f68c9764ef7a7dde51dfa5bfa99304a09); one smoke run of cfg-r on log-retention with sonnet at low effort
- iterations 2 to 4: 5 + 5 + 2 sonnet evaluator agents, 45 + 45 + 12 runs of the model under test; `python3 evaluation/brief_facts/score.py <dir>`; skill-creator `scripts.aggregate_benchmark` and `eval-viewer/generate_review.py --static` for iterations 2 and 3
- iteration 5: the same search; peach-mitao/peach cloned and dropped (adult content); trycompai/crm, guillaumemeyer/watermarks-remover and browser-use/jev-ultrafast cloned shallow; trycompai/crm chosen (HEAD c9473b82e3b4bfd5d0598bbdf7c1f36f3d2d68f0); one smoke run of the HEAD skill on mail-backfill with sonnet at low effort; two sonnet evaluator agents for 30 runs
- 0.47.0: VERSION bump, migration entry, test version pins extended, `python3 installer/harness.py update . --no-commit` (twice, answering the migration prompt), `HARNESS_TEXT_TESTS=1 python3 -m unittest discover -s tests` (1220 tests, only the two modules needing pytest and hypothesis failed to import) and the same suite under .venv

### Failed Attempts
| attempt | failure evidence | cause |
| --- | --- | --- |
| runner prompt without the slash-command wrapper and with "Do not create or edit files" | haiku output for tsv-control began "이 세션은 파일을 만들거나 수정하지 않는 모드라서" and listed code changes instead of an understanding round | hypothesis: the stop rule read as a session mode and nothing marked the skill as invoked |

### Sources
- https://github.com/firecrawl/anydoc at e7178e099b6bf9171e2c52b832cbdb4134b69112 (README.md, src/lib.rs, src/package/limits.rs, src/error.rs, src/formats/csv.rs, node/cli.js, node/anydoc.js)
- https://github.com/diwenne/openreply at c78b2d2f68c9764ef7a7dde51dfa5bfa99304a09 (docs/stack.md, docs/delivery-retries.md, prisma/schema.prisma, vercel.json, scripts/cron.sh, app/api/logs/route.ts, lib/queue/dm-worker.ts, lib/polling/comment-reconciler.ts, lib/reports/data.ts, app/privacy/page.tsx)
- https://github.com/trycompai/crm at c9473b82e3b4bfd5d0598bbdf7c1f36f3d2d68f0 (AGENTS.md, docs/api.md, docs/agent.md, docs/environment.md, docs/plan/gmail-calendar-plan.md, apps/api/vercel.json, apps/api/src/sync/mailbox-sync.service.ts, apps/api/src/google/gmail-sync.service.ts, apps/api/src/mailbox/mailbox-match.service.ts, apps/api/src/crm/activity-stamp.service.ts, apps/api/src/backfill/backfill.service.ts, apps/api/src/contacts/, apps/api/src/trpc/list-input.ts, packages/db/prisma/schema.prisma)
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

#### 11 — 2026-11-13T13:12:25Z

> 지금 prompt를 어떤 방향으로 변경하고 있어?

#### 12 — 2026-11-13T13:13:42Z

> 다른 예시 repo로도 테스트 해보자.

#### 13 — 2026-11-13T13:13:59Z

> 다른 예시 repo로도 테스트 해보자. AA, AB 테스트 둘 다

#### 14 — 2026-11-13T13:14:09Z

> 다른 예시 repo로도 테스트 해보자. AA, AB 테스트 둘 다

#### 15 — 2026-11-13T13:29:52Z

> 스킬 수정하자.

#### 16 — 2026-11-13T13:40:17Z

> 돌려봐.

#### 17 — 2026-11-13T13:52:37Z

> 이 테스트를 항상 돌리지는 않는 회귀 테스트로 추가해줘.

#### 18 — 2026-11-13T13:53:06Z

> 커밋하고 PR

#### 19 — 2026-11-13T13:54:50Z

> 아 주석에서 필요 없는건 다 지워줘. 회고에서도 마찬가지.
> 
> 필요 없다의 기준 = 미래에 쉽게 재현하거나 복구할 수 있는 정보

#### 20 — 2026-11-13T14:03:07Z

> <task-notification>
> <task-id>b10qq1k0c</task-id>
> <tool-use-id>toolu_01GGEwKfF6krUKepNs6vdCP7</tool-use-id>
> <output-file>/private/tmp/claude-501/-Users-hwansu-tools-harness/679f72e4-a8f7-420d-84c1-34737611997b/tasks/b10qq1k0c.output</output-file>
> <status>completed</status>
> <summary>Background command "Run the full test suite including text checks" completed (exit code 0)</summary>
> </task-notification>

#### 21 — 2026-11-13T14:11:51Z

> <task-notification>
> <task-id>brqb6bow1</task-id>
> <tool-use-id>toolu_016ciG1QUiwJchnyjkkHDKzt</tool-use-id>
> <output-file>/private/tmp/claude-501/-Users-hwansu-tools-harness/679f72e4-a8f7-420d-84c1-34737611997b/tasks/brqb6bow1.output</output-file>
> <status>completed</status>
> <summary>Background command "Run the full test suite with the project venv" completed (exit code 0)</summary>
> </task-notification>

#### 22 — 2026-11-13T23:10:56Z

> 한글로 올려줘

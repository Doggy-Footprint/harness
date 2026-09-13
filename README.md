# AI agent Harness for Document Management
[posting](https://harsh-wavelength-48b.notion.site/Document-management-for-AI-3be2e74ce62180e8852ef0f93bb897a2?source=copy_link)

## 왜 만들었나

1. AI agent로 작업을 하면 문서 / 주석 / docstring이 감당할 수 없을 정도로 불어난다.
2. 불어난 문서는 단순히 읽기 힘든 게 아니라 user-level context 오염원으로 작동한다.
3. 가능한 rule-base 관리가 필요하다.
4. 복사해서 쓰는 template으로는 여러 프로젝트에 걸쳐 규칙을 유지·업그레이드할 수 없다. 임의의 기존 프로젝트에 설치하고 업그레이드할 수 있는 harness가 필요하다.

## 어떻게 동작하나?

### 구조

이 repo(소스) 자체의 구조:

```
.
├── harness/                         # 배포 페이로드. 설치 시 대상 repo의 .harness/로 복사된다
│   ├── VERSION
│   ├── config.default.json          # docs_root, exclude_dirs 기본값
│   ├── instructions/harness-block.md  # AGENTS.md 관리 블록 본문
│   ├── agents/<name>.md             # sub-agent 단일 소스 (공통 본문 + claude.*/codex.* frontmatter)
│   ├── skills/contract-workflow/SKILL.md
│   ├── hooks/hooks.spec.json        # 논리적 hook 선언 → Claude/Codex 설정 생성
│   ├── hooks/contract_gate.py, session_end.py
│   ├── git/pre-commit, post-merge, verify_rules.py, warn_new_comments.py
│   ├── ci/harness-comment-warning.yml
│   └── lib/config.py                # repo root, config 로드, 경로 해석
├── installer/
│   ├── generate.py                  # harness/ 소스 → Claude md / Codex toml / hooks dict 렌더링
│   └── harness.py                   # install / upgrade / doctor CLI
└── tests/test_installer.py          # 임시 git repo에서 install/upgrade/doctor 시나리오 검증
```

harness를 설치한 대상 repo의 구조:

```
.
├── AGENTS.md          # 프로젝트 소유 내용 + <!-- harness:begin vX --> … <!-- harness:end --> 관리 블록
├── CLAUDE.md           # `@AGENTS.md` 한 줄
├── .harness/           # vendored 코드 + config.json(선택) + manifest.json(설치 버전·파일별 sha256)
├── .agents/skills/contract-workflow/          (복사본)
├── .claude/skills/contract-workflow -> ../../.agents/skills/contract-workflow  (symlink)
├── .claude/agents/<name>.md, .codex/agents/<name>.toml   (harness/agents/에서 생성)
├── .claude/settings.json, .codex/hooks.json   (harness 항목만 병합)
├── .github/workflows/harness-comment-warning.yml
└── agent-docs/
    ├── adr/{index,stale}.md
    ├── rejections/{index,stale}.md    # 설계 대안 기각 사유 기록
    ├── handoff/{index,stale}.md       # 미완료 작업 인계 기록
    ├── synced-comments/
    └── contracts/                     # 세션 한정. index/stale 없음, SessionEnd에 삭제
```

### Principles
1. 코드가 가장 우선이며, 문서 / 주석은 예외적으로 작성한다.
2. 모든 문서는 **낡을** 위험이 있다. 폐기가 필요하다.
3. AI의 문서와 사람의 문서는 달라야 한다.
4. `AGENTS.md`, `CLAUDE.md` 등 최상위 지시로 관리하되, 가능한 commit hook, PR hook 등으로 관리한다.
5. 기각 사유는 보존한다. 사용자가 구체적으로 제시된 설계 대안을 기각했고 그 사유가 코드만으로 복원되지 않으면, 확인을 받은 뒤 `agent-docs/rejections/`에 기록한다.
6. 핸드오프 - 시도했지만 실패한 것은 보존한다. 작업이 미완료로 멈추면 `agent-docs/handoff/`에 시도-실패 이력을 남기고, 재개 시 기존 실패 이력은 삭제·수정하지 않고 추가만 한다.

### Design Choice
1. 검색 기능은 AI agent를 위해 넣은 기능이다. `find` `grep` `rg`에 적합하며, 토큰 소모를 아껴준다.
2. `agent-docs/synced-comments`는 낡았을 때 특히 위험할 수 있기에 별도로 관리한다.
3. `agent-docs/synced-comments`는 현재 파일 전부를 hash해서 변경 사항을 감지한다. 사용자가 편한 방식으로 튜닝해도 되지만, 개인적으로 한 파일은 작게 유지하는 것을 권장한다.
4. `ADR`은 반드시 사람이 관리한다. LLM의 설명 가득한 의사 결정 문서를 믿지 않는다.
5. implementer / test-implementer / test-verifier를 별개로 운영한다. test-implementer는 contract의 Intent(유저 원문)까지 달성 대상으로 삼는다. 기능 및 토큰 소모 감소를 위해 툴을 제한한다. (verifier는 READ only, 모두 no mcp)
6. (실험 중) sub-agent 최적화: 기능별 동작 개선, main agent / sub agent context 격차 해소 (context rot과 지식 부족 사이에 균형 잡기)
7. sub-agent 정의(Claude md / Codex toml)는 `harness/agents/<name>.md` 하나의 소스에서 생성한다. 두 플랫폼 파일을 각각 손으로 맞추다 생기는 drift를 없앤다.
8. 문서 루트를 `agent-docs/`로 네임스페이스한다. 대상 repo에 원래 있던 `contracts/`(예: Solidity) 같은 디렉터리와 충돌하지 않기 위해서다. `session_end.py`는 삭제 대상 경로가 `docs_root` 안에 엄격히 포함되는지 확인한 뒤에만 지운다.
9. upgrade는 `.harness/manifest.json`의 파일별 sha256과 현재 디스크 상태를 비교해, 사용자가 수정한 파일은 덮어쓰지 않고 건너뛴다(`skip`으로 보고). 건너뛴 파일은 manifest에 이전 sha가 유지되므로, 이후 `doctor`가 계속 문제로 잡아낸다.
10. 설치 대상에 같은 이름의 agent나 skill이 이미 있으면 install/upgrade를 중단하고 충돌 목록만 보고한다. 자동으로 병합하거나 덮어쓰지 않는다.

### 기존 hook·agent 문서가 있는 프로젝트에 적용하는 정책

| 기존 자산 | 처리 |
|---|---|
| `AGENTS.md` 있음 | 관리 블록만 추가/교체하고 외부 내용은 그대로 둔다. 블록 안팎에 같은 이름의 H1/H2 heading이 있으면 `manual review`로 보고한다 |
| `CLAUDE.md`만 있음 | `AGENTS.md`를 새로 만들고, `CLAUDE.md`는 `@AGENTS.md` 한 줄로 시작하도록 앞에 붙인다 |
| 둘 다 있고 내용이 동일 | `CLAUDE.md`를 `@AGENTS.md` 한 줄로 바꾼다 |
| 둘 다 있고 내용이 다름 | `CLAUDE.md` 맨 위에 import를 추가하고 `manual review`로 중복 가능성을 보고한다 |
| `.claude/settings.json`·`.codex/hooks.json`에 기존 hook | 이벤트 배열에 harness 항목만 추가(append)한다. 파싱 실패 시 install/upgrade를 중단한다 |
| 같은 이름의 agent/skill | install/upgrade 중단 + 충돌 목록 보고 |
| git hook 매니저 없음 | `core.hooksPath=.harness/git`로 설정한다. dispatcher가 harness 검사 후 기존 `.git/hooks/<name>`을 체인 실행한다 |
| git hook 매니저 있음(husky, lefthook, pre-commit framework 등) | `core.hooksPath`를 건드리지 않고, 추가해야 할 연동 줄을 `manual review`로 보고한다 |
| `.github/workflows/harness-comment-warning.yml` 이름 충돌 | 중단한다. `--no-ci`로 CI 설치 자체를 건너뛸 수 있다 |
| `.claude/CLAUDE.md`, `CLAUDE.local.md`, 하위 디렉터리 `AGENTS.md`, `.cursor/rules`, `.github/copilot-instructions.md`, 기존 ADR 체계, non-GitHub CI | 건드리지 않고 `info`로만 보고한다 |

## 사용법

```
python3 installer/harness.py install <target> [--dry-run] [--no-ci]
python3 installer/harness.py upgrade <target> [--dry-run] [--no-ci]
python3 installer/harness.py doctor <target>
```

- `install`은 대상이 git work tree가 아니거나, 이미 설치되어 있거나, 충돌(`agent`/`skill`/CI 이름, 잘못된 JSON)이 있으면 아무것도 쓰지 않고 exit 1로 종료한다. `--dry-run`은 실제 변경 없이 report만 출력한다.
- `upgrade`는 `.harness/manifest.json` 기준으로 harness가 관리하는 파일만 최신 버전으로 갱신하고, 사용자가 수정한 파일은 건너뛴다.
- `doctor`는 설치 상태(파일 sha, hook 등록, AGENTS.md 블록, CLAUDE.md, git hook 연동)를 점검하고 문제가 있으면 exit 1로 보고한다.
- 이 repo 자체도 `python3 installer/harness.py install .`로 dogfood한다. `harness/` 아래 소스를 수정한 뒤에는 `python3 installer/harness.py upgrade .`로 이 repo의 설치본을 갱신한다.
- `.harness/config.json`으로 `harness/config.default.json`의 키를 덮어쓸 수 있다. 단, `docs_root` 변경은 hook·검증 스크립트(`.harness/hooks`, `.harness/git`)에만 반영된다. 지시문(AGENTS.md 블록, SKILL.md), installer의 디렉터리 생성, `.gitignore` 항목은 `agent-docs/`를 전제로 한다.

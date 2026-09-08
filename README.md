# AI agent Template for Document Management
[posting](https://harsh-wavelength-48b.notion.site/Document-management-for-AI-3be2e74ce62180e8852ef0f93bb897a2?source=copy_link)

## 왜 만들었나

1. AI agent로 작업을 하면 문서 / 주석 / docstring이 감당할 수 없을 정도로 불어난다.
2. 불어난 문서는 단순히 읽기 힘든 게 아니라 user-level context 오염원으로 작동한다.
3. 가능한 rule-base 관리가 필요하다.

## 어떻게 동작하나?
### Template

```
.
├── AGENTS.md - 문서 체계, 반복되는 문제(핵심 라이브러리 버전 문제 등), 프로젝트 정의 등
├── CLAUDE.md - `AGENTS.md`를 가리킴
├── USAGE.md / README.md / PLAN.md / DESIGN.md - 필요에 따라 참고용으로 사용
├── adr - Architecture Decision Records
│   ├── <id>-json-schema-contract-between-analyzer-and-renderer.md - 실제 adr
│   ├── index.md - index 파일
│   └── stale.md - 폐기 표시
├── contracts - 세션 한정 interface contract (index/stale 없음, 세션 종료 시 삭제)
│   └── <kebab-case-name>.md
├── synced-comments
│   └── <synced_id>.md - synced comment 관리
└── ref
    ├── feats
    │   ├── <id>-multi-language-dependency-analyzers.md - 실제 feature
    │   ├── index.md - index 파일
    │   └── stale.md - 폐기 표시
    └── issues
        ├── <id>-kotlin-comment-string-literal-false-positive.md - 실제 issue
        ├── index.md - index 파일
        └── stale.md - 폐기 표시

```
### Principles
1. 코드가 가장 우선이며, 문서 / 주석은 예외적으로 작성한다.
2. 모든 문서는 **낡을** 위험이 있다. 폐기가 필요하다. 
3. AI의 문서와 사람의 문서는 달라야 한다.
4. `AGENTS.md`, `CLAUDE.md` 등 최상위 지시로 관리하되, 가능한 commit hook, PR hook 등으로 관리한다.

### Design Choice
1. 검색 기능은 AI agent를 위해 넣은 기능이다. `find` `grep` `rg`에 적합하며, 토큰 소모를 아껴준다.
2. `synced-comments`는 낡았을 때 특히 위험할 수 있기에 별도로 관리한다.
3. `synced-comments`는 현재 파일 전부를 hash해서 변경 사항을 감지한다. 사용자가 편한 방식으로 튜닝해도 되지만, 개인적으로 한 파일은 작게 유지하는 것을 권장한다.
4. `ADR`은 반드시 사람이 관리한다. LLM의 설명 가득한 의사 결정 문서를 믿지 않는다.
5. 테스트는 implement / test-verifier를 별개로 운영한다. 기능 및 토큰 소모 감소를 위해 툴을 제한한다. (READ only, no mcp)
6. (실험 중) sub-agent 최적화: 기능별 동작 개선, main agent / sub agent context 격차 해소 (context rot과 지식 부족 사이에 균형 잡기)

## 사용법
`README.md`를 제거하고 사용하면 된다.


---
commit: b9b1d86f60e9edcec5e40cd60de7b0272ec20450
---

# Progress 기록과 continue-on 스킬: spec 초안 이후 이어가기

## User Query

> Cross session을 지원하기에 handoff 만으로는 충분하지 않다고 생각해. 그래서 1. 서브 에이전트(Opus-medium)에서 학술 자료 (2025년 하반기 이후에 한정)를 모아서 cross session work를 수행하기 위한 과제가 무엇인지, 어떤 방법이 효과가 있는지 모아줘. 다른 서브 에이전트에서는 github 등에서 cross session task를 지원하면서 별이 많은 저장소를 찾아서 분석해줘.

이후 사용자가 정한 설계(원문 요지):
- Progress는 작업 기록이며 한 세션에 귀속된다. 다음 세션에서 참고할 섹션을 따로 관리하고, 다음 세션은 그 부분만 읽는다.
- try-n-fail 등은 이전 세션이 "연관 정보"로 넣어준 경우에만 쓰고 추측해서 가져오지 않는다. 필요하면 이어가는 세션의 progress에 넣는다.
- 작업 이어가기는 agent에 안 보이는 스킬(`continue-on`)로, 유저의 명시적 호출로만 실행한다. spec 기준이 아니며 spec 없는 작업도 이어갈 수 있어야 한다.
- 작업하는 모든 세션이 progress를 만들고 agent-docs에서 관리한다. progress는 하나만 존재한다. 새 progress가 써지면 이전 것은 자동으로 progress-logs로 간다.
- 다음 세션에 전달할 가능성이 있는 항목에는 기준 commit을 적는다. hook으로 검사: 직전 progress와 내용이 거의 같은데(Levenshtein) hash가 다르면 경고해서 묻고, 그 외에는 최신 hash인지 검사.
- `workflow-approach`도 progress를 사용한다. handoff는 `todos`로 이관하고, 설치 시 실패하지 말고 일괄 이동 여부를 물어본다.
- 병합은 작업 종료로 보고 progress를 logs로 보낸다. 한 checkout에서 두 세션 병렬은 일반적으로 금지한다.

## State

- 브랜치: `feat/cross-session` (master `b16e923`에서 분기, origin에 푸시됨)
- 커밋: `b9b1d86` draft spec 추가. 이 handoff는 그 다음 커밋.
- 변경 파일: `agent-docs/specs/388ea2d9a2de1f5f-progress-and-continue-on.md` (v1, `draft`), 이 handoff와 `agent-docs/handoff/index.md`.
- 구현 코드는 아직 없음. 테스트도 실행하지 않음.
- 조사 보고서는 클라우드 세션 scratchpad에만 있었고 저장소에 커밋하지 않았음. 핵심 내용은 아래 Execution Ledger에 옮겨 둠.

## Failed Attempts

| attempt | failure evidence | cause |
| --- | --- | --- |
| Opus 서브에이전트(Agent tool, effort medium)에게 Haiku 서브에이전트를 띄워 수집을 맡기도록 지시 | 두 Opus 에이전트 모두 "Agent tool이 도구 목록에 없고 ToolSearch로도 찾지 못함"이라고 보고하고 수집 없이 반환 | verified: 이 환경에서 서브에이전트는 하위 서브에이전트를 생성할 수 없음. 메인 세션에서 Haiku 8개를 직접 띄우고 메인이 Opus 역할(종합, 필요 시 원문 확인)을 맡는 방식으로 우회 |

## Next Step

1. spec을 검토하고 아래 Open Questions에 답한 뒤 v2로 수정한다(workflow-approach의 understanding round와 brief는 사용자 요청으로 생략된 상태).
2. 승인 후 status를 `active`로 바꾸고 workflow-approach로 구현한다. 이 작업이 완료되면 handoff 체계가 progress/todos로 바뀌므로, 이 문서는 마지막 handoff 중 하나가 된다. 완료 시 이 문서 자체도 설치기 마이그레이션 대상(todos로 이동)이 된다.

## Open Questions

- 사용자 요청 원문 자동 기록(UserPromptSubmit 훅) 여부. 커밋되는 progress에 API 키, 사내 호스트명, 고객 정보, 붙여넣은 로그 속 토큰이 들어갈 수 있음. spec은 현재 "자동 기록 안 함, 에이전트가 `### Constraints`에 원문 인용"(A9, Ask).
- 파일 frontmatter `commit:`과 항목별 `commit`을 둘 다 유지하는 판단(A6). 전자는 마지막 쓰기 시점 HEAD, 후자는 항목별 검증 기준. 사용자가 재검토를 요청했고 메인은 둘 다 필요하다고 판단.
- 유사도 기준값: 정규화 Levenshtein 0.90 이상, 20자 이상, 비교 대상은 `before`와 `previous`(A7).
- Stop 시 progress 미작성이면 1회만 종료 보류(A10), PreCompact 리마인더 포함(A11).
- todos 형식(제목, `## Goal`, `## Next Step`, `## Related`)과 test-audit가 기능 그룹별 todo를 쓰는 방식.

## Spec

- 경로: `agent-docs/specs/388ea2d9a2de1f5f-progress-and-continue-on.md`
- version 1, status `draft`, run_id `388ea2d9a2de1f5f`, base_commit `b16e923b7d320c869f411a4f06d0fb98a2cc856c`
- `spec_lifecycle.py validate` 통과. workflow marker는 아직 발행하지 않음.

## Execution Ledger

verifier 0회, correction 0회. 아래는 설계 근거가 된 조사 요약이다(2026-10-28, Haiku 8개 수집 → 메인 종합).

원문을 직접 확인한 항목:

| 근거 | 확인한 내용 | 설계 반영 |
| --- | --- | --- |
| Handoff Debt (arXiv 2606.02875) | SWE-bench Verified 75과제, 181 handoff 지점. raw trace는 후임 3개 모두 해결률 유의 상승(+6.1/+6.6/+14.9pp). 요약·구조화 노트는 Qwen·Gemma 후임에서 비유의, Devstral만 유의(+9.4~+10.5). 노트가 정확한 검증 명령을 누락, 후임이 선임 해석을 과신 | Next Session의 `### Verify`(정확한 명령), 원문 포인터, 가설과 사실 구분 |
| Compact-Bench (2610.31710) | 반복 세부사항 보존: 최고 LLM 요약 16.0%, 기계적 추출 anchor_index 79.1%. 요약기별 작업 손상 5~64% | 핵심은 의역 없이 원문으로 |
| Benchmarks Are Surprisingly Compaction-Friendly (2610.31778) | 실제 세션 compaction에서 제약 19% 손실, 범위 제외 약 37%, 작업 방식 지시 약 36%, 기능 요구 약 6%. 진행 상태가 디스크에 있으면 대부분 복구 | `### Constraints` 원문 인용, PreCompact 리마인더 |
| Codified Context (2602.20478) | 명세 staleness가 주요 실패 모드. 세션 시작 훅이 최근 커밋과 명세-파일 매핑을 비교해 경고 | 항목별 commit과 files, 최신성 검사 |
| DreamBench-SWE (2608.20664) | 세션3 Pass@1(/180): 메모리 없음 21, 비정형 요약 21, task tracker 19, Mem0 21, verbatim 이벤트 89, hybrid 95(verbatim 대비 비유의). 저자: 함정 대부분이 이전 사건 하나의 정확한 보존을 보상 | 요약보다 원문 보존 |
| SWE Context Bench (2602.08316) | 정확히 고른 요약 재사용 26.26 → 34.34%, 무필터 요약 22.22%. "compact하고 정확히 선택된 경우에만 이득" | 이전 세션이 지정한 것만 사용, 추측 금지 |
| planning-with-files 저장소와 이슈 #106 | 훅 6개(SessionStart, UserPromptSubmit, PreToolUse, PostToolUse, PreCompact, Stop), SHA-256 plan attestation. #106: "계획을 읽으라"는 권고형 훅이 무시됨, Windows 경로 불일치로 조용히 0건 반환. 수정은 계획 내용 직접 주입 | 권고 대신 강제(Stop 보류), 조용한 실패 금지 |

Haiku 보고서 기준(원문 미확인):
- 과거 경험은 적게 가져올수록 좋았음(ReasoningBank 2509.25140: 검색 1개 49.7 → 4개 44.4).
- 원문 일부만 읽기의 근거: Recursive Language Models(2512.24601, 원문을 변수로 두고 코드로 조각만 읽음), The Complexity Trap(2508.21433, 관측 마스킹이 LLM 요약과 같은 해결률에 비용 약 50% 절감).
- 저장소 약 28개에서 반복된 실패: SessionStart 주입이 조용히 빈 컨텍스트로 끝남(beads #6728·#7920, claude-mem), 오래된 상태 주입(claude-mem #4083, codebase-memory-mcp #1296), 매 턴 재주입 토큰 비용(planning-with-files #312), handoff 후 worktree 같은 환경 사실 누락(Continuous-Claude-v3 #130). 독립 재현된 벤치마크는 없음.
- "원문 일부만 읽기"를 "원문 전체 넘기기"와 직접 비교한 연구는 찾지 못함.

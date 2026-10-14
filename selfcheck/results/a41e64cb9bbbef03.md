# selfcheck report a41e64cb9bbbef03

- harness ref: HEAD
- harness commit: bf8048ed39310b6280be7a9c2b52d29726fa7517
- fixture: 246588b0e19680ee

## sphinx-doc__sphinx-9602 (completed)

| metric | harness | baseline (per repeat) | range | verdict |
| --- | --- | --- | --- | --- |
| resolved | 0.000 | 0.000, 0.000 | [0.000, 0.000] | within |
| f2p_frac | 0.000 | 0.000, 0.000 | [0.000, 0.000] | within |
| swt_success | 0.000 | 0.000, 0.000 | [0.000, 0.000] | within |
| kill_primary | 0.889 | 0.000, 0.000 | [0.000, 0.000] | above |
| kill_secondary | 0.941 | 0.000, 0.000 | [0.000, 0.000] | above |
| incompatible_frac | 0.143 | 1.000, 1.000 | [1.000, 1.000] | below |

cost_usd: 4.527, elapsed_s: 251.228

| check | verdict |
| --- | --- |
| PC1 | pass |
| PC2 | pass |
| PC3 | pass |
| PC4 | fail |
| PC5 | fail |
| PC6 | pass |
| PC7 | pass |
| PC8 | n/a |
| PC9 | fail |
| PC10 | pass |
| PC11 | fail |

| category | verdict | findings |
| --- | --- | --- |
| ask_options | consistent | 문자열 Literal 값에 따옴표를 붙여 repr 형식으로 표시할지 사용자에게 물었습니다. 이는 gold의 repr(node.value) 변경과 일치합니다. [raw/claude/projects/-testbed/cf8ee939-1f84-415c-8381-cd21f309049c.jsonl:27] |
| recommendation_evidence | consistent | Literal, typing.Literal, typing_extensions.Literal의 정확한 이름만 인식하도록 권장했고, 근거로 upstream을 들었습니다. gold는 Literal과 typing.Literal만 검사하므로 거의 일치합니다. [raw/claude/projects/-testbed/cf8ee939-1f84-415c-8381-cd21f309049c.jsonl:114] |
| spec_requirements | consistent | R1/C1/C2는 gold 테스트와 일치합니다. Literal 값은 xref가 아닌 텍스트로 출력되고, 따옴표가 유지되며, Literal 이름 자체는 xref로 남습니다. [spec] |
| understanding | consistent | 이 brief는 문제를 올바르게 파악했습니다. `_parse_annotation`이 Literal 안의 값들을 py:class xref로 만들고, 그 결과 nitpicky 경고가 발생한다는 점입니다. [raw/claude/projects/-testbed/cf8ee939-1f84-415c-8381-cd21f309049c.jsonl:27] |

## mwaskom__seaborn-3187 (completed)

| metric | harness | baseline (per repeat) | range | verdict |
| --- | --- | --- | --- | --- |
| resolved | 0.000 | 1.000, 1.000 | [1.000, 1.000] | below |
| f2p_frac | 0.000 | 1.000, 1.000 | [1.000, 1.000] | below |
| swt_success | 0.000 | 1.000, 1.000 | [1.000, 1.000] | below |
| kill_primary | 0.000 | 0.500, 0.500 | [0.500, 0.500] | below |
| kill_secondary | 0.000 | 0.500, 0.500 | [0.500, 0.500] | below |
| incompatible_frac | 0.500 | 0.000, 0.000 | [0.000, 0.000] | above |

cost_usd: 5.642, elapsed_s: 951.835

| check | verdict |
| --- | --- |
| PC1 | pass |
| PC2 | pass |
| PC3 | pass |
| PC4 | pass |
| PC5 | fail |
| PC6 | pass |
| PC7 | pass |
| PC8 | n/a |
| PC9 | fail |
| PC10 | pass |
| PC11 | fail |

| category | verdict | findings |
| --- | --- | --- |
| ask_options | diverged | 제시된 선택지는 (a) offset을 제목에 표시, (b) 각 라벨에 offset 포함 두 가지뿐이었다. gold의 방식인 offset/과학적 표기를 끄고 전체 값을 표시하는 선택지는 없었다. [raw/claude/projects/-testbed/50e0a268-346e-4e67-9297-b8c64d5a5dae.jsonl:27] |
| recommendation_evidence | diverged | 브리프는 업스트림 seaborn v0.12.2가 offset을 범례 제목에 넣는 방식으로 이 이슈를 고쳤다고 주장했다. 실제 gold 수정은 set_useOffset(False)와 set_scientific(False)로 offset 자체를 끄는 방식이다. [raw/claude/projects/-testbed/50e0a268-346e-4e67-9297-b8c64d5a5dae.jsonl:27]; useoffset rcParam을 따르면 offset이 꺼질 때 전체 라벨이 출력된다고 주장했으나, 나중에 이 주장이 틀렸다고 스스로 정정했다(과학적 표기 배수는 그대로 남음). [raw/claude/projects/-testbed/50e0a268-346e-4e67-9297-b8c64d5a5dae.jsonl:142] |
| spec_requirements | diverged | R1과 R2는 offset을 제목에 붙이고 라벨은 짧은 값을 유지하도록 요구한다. gold 테스트는 각 라벨 텍스트가 float로 변환했을 때 1e7보다 커야 하므로(전체 크기 표시), 이 요구사항과 맞지 않는다. [spec]; Signatures 절은 형식화된 라벨에서 offset을 제외하고 제목으로 전달한다고 명시한다. 이는 gold의 utils.py 동작(전체 값 라벨)과 반대다. [spec] |
| understanding | consistent | 브리프는 두 코드 경로(scales.py Continuous._setup, utils.locator_to_legend_entries)에서 offset이 누락되는 원인을 정확히 짚었고, 이는 gold patch가 수정한 위치와 같다. [raw/claude/projects/-testbed/50e0a268-346e-4e67-9297-b8c64d5a5dae.jsonl:27] |

## astropy__astropy-14365 (completed)

| metric | harness | baseline (per repeat) | range | verdict |
| --- | --- | --- | --- | --- |
| resolved | 1.000 | 1.000, 1.000 | [1.000, 1.000] | within |
| f2p_frac | 1.000 | 1.000, 1.000 | [1.000, 1.000] | within |
| swt_success | 1.000 | 1.000, 1.000 | [1.000, 1.000] | within |
| kill_primary (참고용: 표본 작음) | 1.000 | 1.000, 1.000 | [1.000, 1.000] | within |
| kill_secondary (참고용: 표본 작음) | 1.000 | 1.000, 1.000 | [1.000, 1.000] | within |
| incompatible_frac | 0.000 | 0.000, 0.000 | [0.000, 0.000] | within |

cost_usd: 1.622, elapsed_s: 138.251

| check | verdict |
| --- | --- |
| PC1 | pass |
| PC2 | fail |
| PC3 | pass |
| PC4 | fail |
| PC5 | fail |
| PC6 | pass |
| PC7 | pass |
| PC8 | n/a |
| PC9 | pass |
| PC10 | pass |
| PC11 | pass |

| category | verdict | findings |
| --- | --- | --- |
| ask_options | consistent | NO도 대소문자를 구분하지 않게 하는 default를 veto할 수 있는 형태로 제시했습니다. gold patch의 v.upper() == "NO"와 일치합니다. [raw/claude/projects/-testbed/4763d223-142f-4768-9242-ab218d284a83.jsonl:27] |
| recommendation_evidence | consistent | 보고된 fix는 re.IGNORECASE와 v.upper() == "NO"로 gold patch와 같습니다. 각 fix를 되돌리는 hand mutation도 했고, 그 결과 테스트가 실패했습니다. [raw/claude/projects/-testbed/4763d223-142f-4768-9242-ab218d284a83.jsonl:47] |
| spec_requirements | consistent | R1과 R2(명령어와 NO 토큰의 대소문자 무시)는 gold의 두 변경과 일치합니다. R3(호환성 유지)은 gold의 test_roundtrip[False]와 일치합니다. [spec] |
| understanding | consistent | 이 brief는 문제를 정확히 짚었습니다. line classifier regex가 대문자 READ SERR/TERR와 NO만 인식한다는 점이고, gold patch가 re.IGNORECASE로 고치는 부분과 일치합니다. [raw/claude/projects/-testbed/4763d223-142f-4768-9242-ab218d284a83.jsonl:27] |

## false claims

| instance | category | summary | citation |
| --- | --- | --- | --- |
| mwaskom__seaborn-3187 | recommendation_evidence | 브리프는 업스트림 seaborn v0.12.2가 offset을 범례 제목에 넣는 방식으로 이 이슈를 고쳤다고 주장했다. 실제 gold 수정은 set_useOffset(False)와 set_scientific(False)로 offset 자체를 끄는 방식이다. | [raw/claude/projects/-testbed/50e0a268-346e-4e67-9297-b8c64d5a5dae.jsonl:27] |

## notes

- 통계적 유의성은 검정하지 않았다. 범위는 기준선 반복 실행의 최솟값과 최댓값이며 above/within/below는 그 범위와의 위치 관계일 뿐이다.
- 표본이 작은 인스턴스(컴파일 가능한 변이 수가 기준 미만)의 kill 지표는 참고용이다.

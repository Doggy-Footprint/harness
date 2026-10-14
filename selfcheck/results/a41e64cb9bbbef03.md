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

## notes

- 통계적 유의성은 검정하지 않았다. 범위는 기준선 반복 실행의 최솟값과 최댓값이며 above/within/below는 그 범위와의 위치 관계일 뿐이다.
- 표본이 작은 인스턴스(컴파일 가능한 변이 수가 기준 미만)의 kill 지표는 참고용이다.

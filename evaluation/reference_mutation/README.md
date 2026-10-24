# 참조 변이 평가 (evaluation/reference_mutation)

> **중단됨(archived).** pilot(run `7df89a358d3faa30`)에서 이 설계가 하네스의 테스트 품질 대신 참조 구현과의 설계 일치를 잰다고 판단해 본 실험 없이 끝냈습니다. GCP 리소스는 모두 삭제했고, 코드는 기록으로만 남기며 테스트는 지웠습니다. 설계, 재현 절차, 결과, 중단 이유는 [`EXPERIMENT.md`](EXPERIMENT.md)를 보세요.

`evaluation/reference_mutation/`는 하네스 arm이 만든 테스트의 품질을 사람이 쓴 참조 코드·테스트와 비교해 측정하는 개발용 도구입니다. 정확성, 의도 정렬, 비용도 함께 재며, 설치 payload에는 포함되지 않습니다. 대상 언어는 python, typescript(javascript 포함), go입니다. rust는 유효 과제가 0개여서 pilot 전에 제외했습니다. 세 arm을 비교합니다: `B0`(일반 Claude Code), `Bplus`(요청 뒤에 테스트 강조 문단 하나를 붙인 arm), `H`(하네스를 설치하고 `/workflow-approach`를 강제한 arm). 모든 arm은 `claude-sonnet-5-5` / effort `medium`으로 실행하고, 호스트의 `claude-opus-5-5`(medium) 시뮬레이션 사용자가 모든 arm의 질문과 idle에 같은 방식으로 답합니다. 시뮬레이션 사용자와 심사자는 참조 코드, 참조 테스트, f2p id를 보지 못합니다. 주장과 임계값은 결과를 보기 전에 `evaluation/reference_mutation/preregistration.md`에 고정합니다.

**준비물.** `gcloud` CLI와 로그인, GCP 프로젝트 `harness-eval-d31ee3`(Compute Engine, Secret Manager, IAP API 사용 설정), 구독 OAuth 토큰 파일(`~/.config/selfcheck/oauth_token`), `evaluation/reference_mutation/requirements.txt`. 이미지 빌드, 에이전트 컨테이너, 테스트·변이 실행은 GCE VM에서 하고 Mac은 오케스트레이션과 결과 수신만 합니다. `python3 -m evaluation.reference_mutation doctor`가 docker, claude CLI, 토큰 파일(모드 600), 디스크, gh 인증을 점검하고 실패 줄마다 고치는 방법을 알려 줍니다.

명령은 다음 순서로 실행합니다.

```bash
python3 -m evaluation.reference_mutation gce up
python3 -m evaluation.reference_mutation gce push
python3 -m evaluation.reference_mutation mine
python3 -m evaluation.reference_mutation gce push
python3 -m evaluation.reference_mutation gce exec -- python3 -m evaluation.reference_mutation build
python3 -m evaluation.reference_mutation gce exec -- python3 -m evaluation.reference_mutation validate
python3 -m evaluation.reference_mutation gce exec -- python3 -m evaluation.reference_mutation brief
python3 -m evaluation.reference_mutation gce exec -- python3 -m evaluation.reference_mutation mutants
python3 -m evaluation.reference_mutation gce exec --detach -- python3 -m evaluation.reference_mutation pilot
python3 -m evaluation.reference_mutation gce pull <run_id>
python3 -m evaluation.reference_mutation gce down
```

- `gce up`: 네트워크, Cloud NAT, IAP 전용 방화벽, 서비스 계정, Secret Manager 비밀(토큰의 sha256이 다를 때만 새 버전을 stdin으로 추가), 데이터 디스크, 외부 IP 없는 on-demand VM(`n2-standard-16`)을 만듭니다(`config.json`의 `gce.spot`을 true로 하면 spot VM). 이미 있는 리소스는 건너뛰므로 다시 실행해도 됩니다.
- `gce push`: `git ls-files` 기준 작업 트리(추적·미추적 파일, ignore 제외)를 VM의 `/data/src`로 보냅니다. `gce exec`는 IAP SSH로 VM에서 명령을 실행하고 `--detach`는 `nohup`으로 `/data/logs/<시각>.log`에 기록합니다.
- `mine`은 `gh`가 로그인된 로컬 머신에서 실행하고, 이어지는 `gce push`가 수집한 과제를 VM으로 보냅니다. VM에는 GitHub 인증이 필요 없습니다.
- `mine` → `build` → `validate` → `brief` → `mutants`: GitHub에서 후보를 모으고(언어별 40개 목표), 저장소별 이미지를 만들고, 참조 테스트를 base와 merge에서 3번씩 실행해 f2p/p2p를 가르고, 사용자 시점의 요청과 의도 카드를 만들고, 참조 변이를 만듭니다. 각 명령은 `--language python|typescript|go|rust`로 언어를 좁힐 수 있고 이미 처리한 항목은 건너뜁니다(`--force`로 다시).
- `pilot`: 언어별 저장소 2개, 저장소별 과제 최대 2개에서 B0·Bplus를 1번, H를 언어당 1번 실행한 뒤 채점, 교차 탐지, 심사, 리포트까지 한 번에 합니다. 과제는 `pilot`으로 표시되고 main 분석에서 제외됩니다. 게이트 G1~G5의 통과 여부는 리포트에 나옵니다.
- `run --phase main`: 본 실험은 `--phase main`으로만 시작합니다. 시작할 때 `evaluation/reference_mutation/preregistration.md`의 sha256을 실행 기록에 저장하고, 이후 파일이 바뀌면 같은 실행의 `report`가 두 해시를 출력하며 종료 코드 2로 거절합니다. 본 실험 전에 사전등록 파일을 확정(동결)하고 표본 수(과제 15~20개/언어, arm당 2회)를 기록하세요.

**결과 위치.** 리포트는 `evaluation/reference_mutation/results/<run_id>.json`과 `.md`에 쓰고, 실행 산출물은 `~/.harness/evaluation/runs/<run_id>/`(VM에서는 `/data/evaluation/runs/<run_id>/`)에 둡니다. 항목 디렉터리는 `<과제>/<arm>-r<k>/`이며 manifest, state, full.diff, split.json, usersim.jsonl, raw/, score.json이 들어 있습니다. 리포트에는 transcript, 도구 입력, diff, 테스트 코드, 200자를 넘는 인용, 토큰이 들어가지 않으며 포함되면 쓰기를 거절합니다(종료 코드 2).

**종료 코드.** `0` 정상. `2` 입력 거절(토큰 파일 없음, 이미지 없음 → `python3 -m evaluation.reference_mutation build --language <L>`, 사전등록 해시 불일치, 리포트에 토큰 또는 금지 내용 등): 메시지에 고칠 명령이나 경로가 있습니다. `3` 구독 한도(rate limit)·선점·중단으로 멈춤: 끝난 항목은 그대로 두고 `python3 -m evaluation.reference_mutation run --resume <run_id>`로 이어 갑니다. `mine`이 GitHub 한도에 걸리면 3으로 끝나며 같은 명령을 다시 실행하면 마지막 저장소부터 이어 갑니다. 항목이 `error`로 끝나면 `python3 -m evaluation.reference_mutation run --retry-errors <run_id>`로 한 번 다시 실행하고(attempts 2), 그래도 `error`이면 리포트에서 실패로 채점합니다. 재시도 전 `error` 항목이나 `interrupted` 항목이 있으면 `report`가 종료 코드 2로 거절합니다. `gce` 하위 명령이 gcloud 단계에서 실패하면 1입니다. 자동으로 기다리지 않습니다.

**정리.** `gce down`은 VM만 지우고 데이터 디스크는 남깁니다. `gce down --purge --yes`는 디스크와 비밀까지 지웁니다.

---
version: 16
run_id: 616f94189f1a4147
status: limit
base_commit: 89d7f58a33b60b86512921cac040d07da6ad933b
max_verifier_invocations: 2
handoff: agent-docs/handoff/d63aaa61098054c3-test-quality-evaluation-verifier-limit.md
---

# User Intent
| id | stakeholder | intention | observable goal |
| --- | --- | --- | --- |
| I1 | harness maintainer | "이 하네스의 장점은 test를 잘 작성하는 건데, 그 성능을 평가/검증해볼 방법이 없나?" → "전체 실험으로 가자." | `evaluation/` measures the test quality of harness-arm output against human-written reference code and tests, beside correctness, intent alignment and cost (H1–H4) |
| I2 | harness maintainer | "언어별로 넉넉하게 준비하고, pilot으로 언어별 1-2 레포만 대조군으로 빠르게 돌려보자." | tasks are mined for python, typescript, go and rust with ≥40 candidates per language; a pilot command runs B0 and B+ on 2 repos per language plus one H entry per language |
| I3 | harness maintainer | "대조군은 어떻게 할거야?" | arms B0 (plain Claude Code), B+ (plain + fixed test-emphasis paragraph) and H (harness installed, `/workflow-approach` forced) differ only in those points |
| I4 | harness maintainer | "실험은 sonnet-medium으로 할게" | every arm runs `claude-sonnet-5-5` at effort `medium` |
| I5 | harness maintainer | "harness는 의도를 확인 받는 절차가 있어. 이건 어떻게 할거야?" | a host-side `claude-opus-5-5` medium simulated user holding a per-task intent card answers questions, approvals and idle turns identically for all arms, without access to reference code or tests |
| I6 | harness maintainer | "평가에는 opus-medium을 이용한 정성 평가도 넣어줘. 평가 기준은 표준적으로 테스트 품질 평가에 사용하는 걸 쓰고." + "정성 평가도 이번 run에" | a blind `claude-opus-5-5` medium judge scores test sets by the test-smell catalog, Test Desiderata and ISO/IEC/IEEE 29119-4 coverage, with human tests as an anchor; it runs in the pilot |
| I7 | harness maintainer | "CPU/memory intensive 작업은 gcloud 이용해줘." | image builds, agent containers, test runs and mutation runs execute on a GCE VM in project `harness-eval-d31ee3`; the Mac only orchestrates and receives results |
| I8 | harness maintainer | claims and kill criteria are fixed before results (handoff c379ec40307bd6c0 stage 1) | `evaluation/preregistration.md` holds H1–H4 measures and thresholds; every report records its sha256 and a main-phase report refuses a changed file |

# Scope
In scope: new package `evaluation/` (mining, image recipes, validation, briefs and intent cards, reference mutants, agent arms with simulated user, diff splitting, scoring, cross-arm detection, blind judge, statistics, report, GCE provisioning and remote execution, CLI), `evaluation/preregistration.md`, `evaluation/config.json`, `evaluation/requirements.txt`, README section.
Out of scope: running the main experiment; changes to `harness/`, `installer/`, `.harness/`, generated agent files, `selfcheck/` (stays archived; code is copied, not imported); languages other than the four; statistical significance tests beyond bootstrap intervals; live model, Docker, GitHub or gcloud calls in the automated suite.

# Paths
Implementation: evaluation/__init__.py, evaluation/__main__.py, evaluation/config.json, evaluation/preregistration.md, evaluation/requirements.txt, evaluation/languages.py, evaluation/junit.py, evaluation/mine.py, evaluation/recipes.py, evaluation/validate.py, evaluation/brief.py, evaluation/mutants.py, evaluation/compose.py, evaluation/run.py, evaluation/docker_exec.py, evaluation/agent/__init__.py, evaluation/agent/driver.py, evaluation/agent/relay_driver.py, evaluation/usersim.py, evaluation/overlay.py, evaluation/testrun.py, evaluation/score.py, evaluation/pilot.py, evaluation/crossarm.py, evaluation/judge.py, evaluation/stats.py, evaluation/report.py, evaluation/gce.py, evaluation/claude_call.py, evaluation/docker/, README.md
Tests: evaluation/tests/
Test command: python3 -m venv .venv && .venv/bin/pip install -q -r evaluation/requirements.txt && .venv/bin/python -m pytest evaluation/tests -q -p no:cacheprovider --cov=evaluation --cov-branch --cov-config=evaluation/tests/.coveragerc --cov-fail-under=85
Review evidence: R1 comment review of every Implementation file against AGENTS.md Comment Enforcement. R2 preregistration review: `evaluation/preregistration.md` states every row of Quality Requirement QR-PRE and the thresholds in FR-P1, read against this spec. R3 GCE smoke (live, not automated): `python3 -m evaluation gce up` then `gce exec -- python3 -m evaluation doctor` then `gce down`; expected: VM reaches RUNNING with no external IP, `doctor` reports docker, claude CLI and secret file present with mode 0600 owned by the run user, `sudo journalctl -u google-startup-scripts` on the VM contains no line with the token (grep with the local token value, count 0), `down` leaves the data disk. R4 pilot (live, not automated): `python3 -m evaluation pilot` on the VM; expected: report `evaluation/results/<run>.md` with pilot gates, judge section and no token, transcript or diff text (`report` token scan passes). R5 container isolation spot check: in one pilot B0 container `git log --all --oneline | wc -l` prints 1, in one pilot H container it prints 2 and `git show --name-only HEAD` lists only harness paths and `.gitignore`; `git remote` prints nothing in both.
Fuzzing: hypothesis 6.x harness `evaluation/tests/fuzz_parsers.py` (written by test roles), surface `junit.parse`, `languages.split_diff`, `languages.split_rust_inline`, `brief.leaks`; oracle: crash (any exception other than `junit.JunitError`) plus properties P1 "split_diff parts re-join to the input file set with no file in two parts", P2 "split_rust_inline(src) → (rest, mods): every mod text occurs in src and rest contains no `#[cfg(test)]` attribute directly followed (ignoring whitespace, comments and other attributes) by a `mod` item", P3 "every reported leak term occurs in the text"; seed 1, budget 20000 examples per target.
Mutation tool: mutmut 2.5.1 over Implementation Python lines changed since base_commit, runner `.venv/bin/python -m pytest evaluation/tests -q -x -p no:cacheprovider`, sample cap 300, seed 1, survival threshold 40%.

# Signatures
All functions with I/O take injectable callables; automated tests pass fakes. `call_fn(prompt: str, *, model: str, effort: str, timeout_s: int) -> str` (claude CLI), `gh_fn(args: list[str]) -> object` (parsed JSON of `gh api`), `run_fn(argv: list[str], *, input: str | None = None, timeout: int | None = None) -> tuple[int, str, str]` (subprocess), `docker` = module-like object with the `evaluation/docker_exec.py` surface.

evaluation/languages.py:
LANGUAGES = ("python", "typescript", "go", "rust")
def classify_path(language: str, path: str) -> str   # "harness" | "test" | "src" | "other"; rules FR-S1
def split_diff(language: str, diff: str) -> dict[str, str]   # keys "src", "tests", "harness", "other"; each a valid unified diff (possibly empty)
def split_rust_inline(text: str) -> tuple[str, list[str]]   # (text without `#[cfg(test)]` modules, module texts in order)
def changed_lines(diff: str) -> dict[str, set[int]]   # new-file line numbers of added/modified lines per path, src part only when called on a src diff

evaluation/junit.py:
class JunitError(ValueError)
def parse(xml_text: str, *, language: str) -> dict[str, str]   # test id → "pass" | "fail" | "error" | "skip"; id format FR-T2

evaluation/mine.py:
def eligible(pr: dict, files: list[dict], cfg: dict) -> tuple[bool, str]   # (ok, reason code from FR-M2)
def search(language: str, cfg: dict, *, gh_fn) -> list[dict]   # candidate rows, FR-M3

evaluation/recipes.py:
class RecipeError(RuntimeError)
def detect(language: str, files: dict[str, str]) -> dict   # files: repo-root path → text of manifest/lock files; returns {"language", "manager", "install": [cmd], "test": {"runner", "argv_template"}, "base_image"}
def dockerfile(recipe: dict, cfg: dict) -> str
def test_argv(recipe: dict, selection: list[str], junit_path: str) -> list[str]   # selection = test file paths

evaluation/validate.py:
def classify(base_runs: list[dict], merge_runs: list[dict], cfg: dict, *, gold_test_files: list[str], orig_runs: list[dict] | None = None) -> dict   # {"valid": bool, "reason": str, "f2p": [ids], "p2p": [ids], "flaky": [ids], "p2p_note": str | None}; p2p per F36

evaluation/brief.py:
class BriefFormatError(ValueError)
def interface_signatures(language: str, src_diff: str) -> list[dict]   # [{"path", "signature"}] for added or changed public symbols, FR-B2
def forbidden_terms(task: dict) -> set[str]
def leaks(text: str, task: dict) -> list[str]   # sorted, de-duplicated forbidden terms found in text
def build_prompt(task: dict) -> str
def parse_brief(text: str, task: dict) -> dict   # {"request": str, "statements": [{"id": "S<n>", "text": str, "f2p": [ids]}], "ambiguous": ["S<n>", ...]}
def make_brief(task: dict, *, call_fn, cfg: dict) -> dict   # adds "attempts", "status": "ok" | "dropped", "reason"

evaluation/compose.py:
ARMS = ("B0", "Bplus", "H")
BPLUS_PARAGRAPH: str   # fixed text, FR-A2
def compose_prompt(brief: dict, arm: str) -> str

evaluation/mutants.py:
TOOLS = {"python": "mutmut", "typescript": "stryker", "go": "go-mutesting", "rust": "cargo-mutants"}
def normalize(tool: str, raw: str) -> list[dict]   # [{"id", "path", "line", "diff"}]; id = sha256(path, line, diff)[:16]
def restrict(mutants: list[dict], changed: dict[str, set[int]]) -> list[dict]
def sample(mutants: list[dict], cap: int, seed: int) -> list[dict]   # sorted by id before seeded sampling

evaluation/overlay.py:
def hidden_tree(language: str, gold: dict, agent: dict) -> dict[str, str | None]   # path → final text (None = delete); agent src + gold tests, FR-T3
def validity_tree(language: str, gold: dict, agent: dict) -> dict[str, str | None]   # gold src + agent tests, FR-T3
def cross_tree(language: str, gold: dict, impl: dict, tests: dict) -> dict[str, str | None]
# gold/agent/impl/tests dicts: {"base": {path: text|None}, "after": {path: text|None}, "split": split_diff output}

evaluation/usersim.py:
FALLBACK_ASK = "(Recommended)"   # pick the option containing it, else the first option
FALLBACK_IDLE = "No preference; use your recommendation. Please continue."
def build_prompt(task: dict, request: dict, history: list[dict]) -> str
def parse_response(text: str, request: dict) -> dict   # ask: {"answers": {question: str|None}}; idle: {"action": "reply"|"stop", "message": str|None, "contradiction": bool}  (contradiction = the reply states a card behavior the agent's plan/spec contradicts; counted as a spec correction)
def respond(task: dict, request: dict, history: list[dict], *, call_fn, cfg: dict) -> tuple[dict, dict]   # (response sent to container, record row)
class Relay:   # host thread polling `relay_dir` of one container, same file protocol as selfcheck/informed.Relay
    def __init__(self, container, task: dict, record_path, *, call_fn, cfg: dict, token: str)
    def start(self) -> None
    def stop(self) -> None

evaluation/agent/relay_driver.py (container side; driver.py is copied from selfcheck/agent/driver.py with only import paths changed):
def run(inp: dict, client_factory, clock, *, poll_s: float = 1.0) -> dict   # client_factory(options) returns the SDK client; main passes ClaudeSDKClient
def main(argv: list[str]) -> int   # input JSON adds "relay_dir", "relay_timeout_s", "relay_poll_s"
Relay request files: `req-<n>.json` = {"n", "kind": "ask", "questions": [...]} or {"n", "kind": "idle", "last_text": str}; responses `resp-<n>.json` as parse_response output plus "n".

evaluation/score.py:
def hidden_outcome(results: dict[str, str], f2p: list[str], p2p: list[str]) -> dict   # {"resolved": bool, "f2p_frac": float, "p2p_broken": [ids]}
def agent_test_ids(base_results: dict[str, str], agent_results: dict[str, str]) -> list[str]   # ids in agent results absent from base results
def validity(runs: list[dict[str, str]], agent_ids: list[str]) -> dict   # {"n", "valid": [ids], "false_alarm": [ids], "incompatible": [ids], "flaky": [ids], "false_alarm_rate": float|None}
def kill(mutant_runs: dict[str, dict], valid_ids: list[str], d_ref: set[str]) -> dict   # mutant_runs: id → {"status": "ok"|"build_error"|"timeout", "results": {...}}
def ambiguity_correct(results: dict[str, str], brief: dict) -> dict   # {"n", "correct", "rate"}
def self_report(telemetry_events: list[dict]) -> dict | None   # last `verification` marker counts, or None

evaluation/crossarm.py:
def detection(matrix: dict[tuple[str, str], dict], resolved: dict[str, bool], valid: dict[str, list[str]]) -> dict[str, dict]
# matrix[(tests_entry, impl_entry)] = {"status": "ok"|"build_error"|"timeout", "results": {...}}; returns per tests_entry {"buggy_n", "detected", "detection_rate", "correct_n", "alarmed", "false_alarm_rate", "inconclusive"}

evaluation/judge.py:
SMELLS: tuple[str, ...]   # FR-J2
DESIDERATA_JUDGED: tuple[str, ...]   # FR-J2
def candidates(task: dict, entries: list[dict], seed: int) -> list[dict]   # [{"label": "T<k>", "source": entry key or "human", "text": str}]
def anonymize(text: str, spec_ids: set[str]) -> str
def build_absolute_prompt(task: dict, brief: dict, cand: dict) -> str
def parse_absolute(text: str, cand: dict, brief: dict) -> dict   # raises JudgeFormatError
def build_pairwise_prompt(task: dict, brief: dict, first: dict, second: dict) -> str
def parse_pairwise(text: str) -> str   # "first" | "second" | "tie"
def combine_orders(ab: str, ba: str) -> str   # "A" | "B" | "tie" | "inconsistent"
class JudgeFormatError(ValueError)

evaluation/stats.py:
def cluster_bootstrap(diffs: dict[str, list[float]], *, resamples: int, seed: int, alpha: float = 0.05) -> dict   # {"mean", "lo", "hi", "n_tasks", "n_clusters"}
def verdict(ci: dict, rule: dict) -> str   # "help" | "no_help" | "harmful" | "insufficient" | "ok" (guard rule only, F14)

evaluation/report.py:
class TokenInReport(RuntimeError)
def build(run_dir, *, prereg_path, cfg: dict) -> dict
def render_markdown(report: dict) -> str
def write(report: dict, results_dir, *, token: str) -> tuple[Path, Path]   # refuses when token or any forbidden content marker occurs

evaluation/gce.py:
def plan_up(cfg: dict) -> list[list[str]]   # gcloud argv in execution order, FR-G1
def up(cfg: dict, *, run_fn) -> int
def down(cfg: dict, *, run_fn, purge: bool = False, yes: bool = False) -> int
def push(cfg: dict, *, run_fn) -> int
def exec_remote(cfg: dict, argv: list[str], *, run_fn, detach: bool = False) -> int
def pull(cfg: dict, run_id: str, *, run_fn) -> int

evaluation/docker_exec.py (surface copied from selfcheck/docker_exec.py; fakes implement exactly this):
class DockerError(RuntimeError); class DockerUnreachable(RuntimeError); class ImageMissing(RuntimeError)
class Container:
    def exec(self, argv: list[str], *, timeout: int | None = None, user: str | None = None, workdir: str | None = None) -> tuple[int | None, str, bool]   # (exit code or None, combined output, timed_out)
    def write_text(self, dest: str, text: str) -> None
    def copy_in(self, local, dest: str) -> None
    def read_bytes(self, src: str) -> bytes | None
    def copy_out(self, src: str, local) -> None
    def start(self) -> None; def stop(self) -> None; def remove(self) -> None
def container(image: str, *, network: bool = False)   # context manager yielding Container, removed on exit
def start_container(image: str, *, name: str, network: str, labels: dict, cpus, memory: str, mounts: list[str]) -> Container
Container(name: str) re-attaches to an existing container by name (used by resume)
def container_exists(name: str) -> bool; def remove_container(name: str) -> None; def image_id(image: str) -> str   # raises ImageMissing
def ensure_network(name: str, internal: bool = True) -> None
def start_proxy(image: str, *, name: str, networks: list[str], labels: dict, conf_text: str) -> Container
def build(context_dir, tag: str, *, timeout: int) -> tuple[int, str]   # (exit code, log)

evaluation/testrun.py:
def run_tests(task: dict, tree: dict[str, str | None], selection: list[str], *, docker, cfg: dict, cache_dir, repeat: int = 0) -> dict
# fresh container from task["image"] with network disabled; writes every tree path under /testbed (None deletes); runs recipes.test_argv(task["recipe"], selection, junit path) with cfg.eval.timeout_s; returns {"status": "ok"|"build_error"|"timeout", "results": {id: status}, "runtime_s": float, "cached": bool}; "build_error" when the runner exits non-zero and no junit file exists; cache file `<cache_dir>/<sha256(image id, sorted tree items, selection, repeat)>.json`, written only for "ok" and "build_error"

Task record (`<data_dir>/tasks/<language>/tasks.jsonl`, one object per line): {"task_id": "<owner>__<repo>-<pr>", "language", "repo", "pr", "base_sha", "merge_sha", "image", "recipe", "gold_patch", "gold_split": split_diff output, "gold_base": {path: text|None}, "gold_after": {path: text|None}, "f2p", "p2p", "valid", "reason", "brief": make_brief output | null, "mutants": [{"id", "path", "line", "diff", "gold": "killed"|"survived"|"build_error"|"timeout"}], "pilot": bool}

evaluation/run.py:
class Halted(RuntimeError):   # .run_dir, .reason; CLI maps it to exit 3 with `--resume <run_id>`
def run(tasks: list[dict], arms: list[str], *, cfg: dict, phase: str, repeats: int, docker, call_fn, prereg_path, now=time.time, harness_ref: str = "HEAD") -> Path   # phase "pilot" | "main" | "dev"; run.json holds run_id, phase, prereg_sha256, entries [{task_id, arm, repeat, status}]
def resume(run_id: str, *, cfg: dict, docker, call_fn) -> Path
Entry dir: `<run_dir>/<task_id>/<arm>-r<k>/` with manifest.json, state.json, full.diff, split.json, usersim.jsonl, raw/ (ledger.jsonl, messages.jsonl, telemetry/), score.json, judge items in `<run_dir>/<task_id>/judge.json`

evaluation/score.py (additions):
def score_entry(task: dict, entry_dir, *, docker, cfg: dict, cache_dir) -> dict   # writes score.json with FR-T4 metrics
def score_run(run_dir, tasks: dict[str, dict], *, docker, cfg: dict, cache_dir) -> list[dict]

evaluation/crossarm.py (addition):
def run_matrix(task: dict, entry_dirs: list, *, docker, cfg: dict, cache_dir) -> dict[tuple[str, str], dict]

evaluation/judge.py (addition):
def judge_task(task: dict, entries: list[dict], *, call_fn, cfg: dict) -> dict   # {"absolute": {label: dict|"error"}, "pairwise": [{"pair", "repeat", "ab", "ba", "outcome"}], "labels": {label: source}}

evaluation/pilot.py:
def select(tasks: dict[str, list[dict]], cfg: dict) -> list[dict]   # FR-P3; each returned task carries "pilot_arms": list of arms
def gates(metrics: dict, cfg: dict) -> dict[str, dict]   # {"G1".."G5": {"pass": bool, "value": float|int|None, "threshold": ...}}

Formats (fixed in v3; fakes and implementation follow these exactly):
- F1 repeats are 1-based; entry key and dir name `<arm>-r<k>`, k ≥ 1.
- F2 `run` writes the tasks it runs to `<run_dir>/tasks.jsonl` before the first entry; `resume` reads only that snapshot; a missing snapshot is exit 2 naming the path.
- F3 container contract of one entry: `run` stages `evaluation/agent/driver.py` and `relay_driver.py` into `/opt/evaluation/agent/`, writes `/evaluation/in/input.json`, executes `["/opt/evaluation-py/venv/bin/python", "/opt/evaluation/agent/relay_driver.py", "/evaluation/in/input.json"]` as user `nonroot` in `/testbed`, then reads `/evaluation/out/state.json` and copies `/evaluation/out/.` to `<entry>/raw/`. state.json = {"status": "completed"|"stalled"|"capped"|"error"|"interrupted", "reason": str|null, "session_id": str|null, "results": [{"total_cost_usd": float|null, "duration_ms": int|null, "num_turns": int|null, "is_error": bool}], "rate_limit": {"status": str, ...}|null}. The entry is interrupted when status is "interrupted" or rate_limit.status is not null and not "allowed"; FINISHED = completed, stalled, capped, error.
- F4 scrub replaces every token occurrence with `[REDACTED]` in every file under the entry dir and keeps all other bytes; a file still containing the token after scrub makes the entry `error` with reason "token remained after scrub".
- F5 relay: a simulated-user response (answers or message) containing the token or any forbidden term is replaced by the fallback (reason "leak"); `usersim.forbidden_terms(task)` = `brief.forbidden_terms(task)`; `brief.forbidden_terms` includes the task's merge sha and its first 7 characters; record rows redact the token as `[REDACTED]`.
- F6 `gh_fn` receives `[endpoint]`, a REST path with query string, and returns parsed JSON. Sequence: repositories `search/repositories?q=language:<lang>+stars:>=<min_stars>+fork:false+archived:false&sort=stars&order=desc&per_page=100&page=<p>` (typescript also runs the same search with `language:javascript`); per repo with `license.spdx_id` in licenses: `search/issues?q=repo:<owner>/<repo>+is:pr+is:merged+merged:>=<merged_after>&per_page=100`; per hit: `repos/<owner>/<repo>/pulls/<n>` and `repos/<owner>/<repo>/pulls/<n>/files?per_page=100`; linked issues are `#<n>` after closes/fixes/resolves (case-insensitive) in the PR body, fetched with `repos/<owner>/<repo>/issues/<n>`. `eligible(pr, files, cfg)`: pr = REST pull object plus key "language"; author = `pr["user"]["login"]`; files = REST file objects (`filename`, `status`, `additions`, `deletions`, optional `patch`); a file with additions+deletions > 0 and no `patch` key is binary. A rate-limit response is a dict with `"message"` starting "API rate limit exceeded" or gh_fn raising `mine.RateLimited`.
- F7 `validate.classify(base_runs, merge_runs, cfg, *, gold_test_files: list[str])`: runs are `testrun.run_tests` outputs; reason precedence build_error, timeout, parse_error (any run with that status), then no_f2p, flaky_f2p, else "ok"; p2p per F36 (v12 replaces the file-part restriction). `testrun.run_tests` returns status "parse_error" when the junit file exists but `junit.parse` raises.
- F8 brief model output is one JSON object {"request": str, "statements": [{"id": "S<n>", "text": str, "f2p": [ids]}], "ambiguous": [ids]}; `ambiguous` has 1 or 2 ids when there are ≥ 2 statements and must be empty when there is 1; successful `make_brief` has status "ok", reason "ok".
- F9 simulated-user model output is one JSON object: ask {"answers": {question: option label | "Other: <text>" | null}}; idle {"action": "reply"|"stop", "message": str|null, "contradiction": bool}.
- F10 judge absolute output: {"smells": [{"smell", "test", "quote"}], "desiderata": {<each DESIDERATA_JUDGED name>: {"score": int, "rationale": str, "quote": str}}, "coverage": {<each statement id>: {"level": "covered"|"partial"|"none", "quote": str}}, "boundary": bool, "error_path": bool}; a quote may be empty only for level "none"; `parse_absolute` returns the same shape plus "label". Pairwise output {"winner": "first"|"second"|"tie"} (a bare word is also accepted).
- F11 judge entries: `candidates(task, entries, seed)` takes [{"key": "<arm>-r<k>", "arm", "repeat", "status", "text"}] and includes only status "completed" entries plus the human candidate (text = gold tests part); order = ascending sha256(f"{seed}:{task_id}:{source}"); `judge_task` pairs H–B0, H–Bplus, Bplus–B0 for each repeat k where both entries are completed, each pair asked once per order.
- F12 `score.kill` returns {"executed", "killed", "raw", "normalized", "killed_ids", "d_ref_n"}; zero valid tests → raw 0.0 and normalized 0.0 when executed > 0; `score_entry` adds "flagged": d_ref_n < cfg.report.min_mutants. score.json = {"entry": key, "hidden": hidden_outcome + {"status"}, "validity": validity output, "kill": kill output, "ambiguity": ambiguity_correct output, "cost_usd", "wall_s", "questions", "corrections", "self_report"}.
- F13 `pilot.gates(metrics, cfg)` metrics keys: b0_resolved_rate, candidate_valid_rate {language: rate}, judge_consistency, anchor_lowest_share, leak_fallbacks, token_hits; thresholds in cfg.gates (g1_max_b0_resolved 0.80, g2_min_valid 0.50, g3_min_consistency 0.70, g4_max_anchor_lowest 0.50); G1 pass iff value ≤ 0.80, G2 iff every language ≥ 0.50, G3 iff ≥ 0.70, G4 iff anchor_lowest_share ≤ 0.50, G5 iff leak_fallbacks + token_hits == 0; a missing metric gives pass false and value null.
- F14 `stats.verdict(ci, rule)`: rule {"min_tasks": 10} → help/no_help/harmful/insufficient per FR-P1; guard rule {"min_tasks": 10, "guard_upper": 0.10} → "harmful" iff hi > 0.10, else "ok"; insufficient checked first in both.
- F15 `gce push`: tar.gz of `git ls-files` paths → `gcloud compute scp --tunnel-through-iap <local tgz> <vm>:/tmp/evaluation-push.tgz` → ssh extracting into `/data/src`. `gce pull <run_id>`: scp `<vm>:/data/results/<run_id>.*` into cfg.results_dir and `--recurse <vm>:/data/evaluation/runs/<run_id>` into `<data_dir>/runs/`. On the VM, cfg.data_dir is `/data/evaluation` and results_dir `/data/results` (`gce exec` passes `EVALUATION_DATA_DIR` and `EVALUATION_RESULTS_DIR`, which override cfg). `down(cfg, *, run_fn, purge=False, yes=False)`: purge without yes returns 2 and runs nothing.
- F16 `recipes.dockerfile` installs only the task language's mutation/property tools and runner.
- F17 rust overlays: hidden = agent src with its own `#cfgtest` modules removed and gold's appended; validity = gold src with gold's `#cfgtest` modules removed and the agent's appended (none appended when the agent has none).
- F18 rust `split_diff` of a modified file: the src part holds every non-module change; changes inside `#[cfg(test)]` modules appear only in the tests part (C12).

- F19 entry text collection: after the agent stops, `run` stages all changes (`git add -A`), takes the full diff against the start commit, and derives the changed paths from that diff's `diff --git a/<p> b/<p>` headers (harness paths skipped); for each path, base text = output of `git show <start_commit>:<path>` unless the diff marks the file new, and after text = `read_bytes("/testbed/<path>")` unless the diff marks it deleted; undecodable files are dropped from base and after. split.json = {"split": split_diff output, "base": {...}, "after": {...}}.
- F20 usersim record rows (`<entry>/usersim.jsonl`): {"n", "kind": "ask"|"idle", "request", "raw_output", "parsed", "leaks", "sent", "fallbacks": {key: reason}, "reason": first fallback reason, else the failure outcome ("timeout", "null", "format", "error"), else null on success, "error", "contradiction", "elapsed_s"}; G5 leak_fallbacks = number of rows with reason "leak" or any fallbacks value "leak".
- F21 `report.write` refuses (TokenInReport-style error, exit 2 via CLI, nothing written) rendered text containing: the token; `diff --git`; a line starting with `def test_` or `func Test` or `#[test]`; transcript markers `"role": "assistant"`, `"role": "user"`, `"type": "tool_use"`, `"type": "tool_result"`, `"tool_input"`. Before rendering, every string value under a key named `quote` anywhere in the report is cut to its first 200 characters.
- F22 `crossarm.run_matrix` ignores entry dirs whose manifest `task_id` differs from `task["task_id"]`.
- F23 `gce push` ships the `git ls-files --cached --others --exclude-standard` paths plus the `.git` directory (without macOS AppleDouble `._*` entries), so `/data/src` on the VM is a repository at the local HEAD; when `<local data_dir>/tasks/` exists it is also shipped and replaces `/data/evaluation/tasks/`. `mine` runs where `gh` is authenticated (the maintainer's machine); the VM needs no GitHub credential.
- F24 `gce up` retries the secretAccessor binding step up to 6 attempts, 10 s apart, while its stderr says the service account does not exist (IAM propagation); any other failure stops at once.
- F25 H install environment: the install step runs with `HARNESS_TARGETS_FILE=/tmp/harness-targets.json` and `HARNESS_PREFERENCES_FILE=/tmp/harness-preferences.json`, the latter written beforehand as {"repositories": {"/testbed": {"verification_tools_prompt": "never"}}}, so the installer never runs package-manager installs; the image already holds the tools (FR-R2). The install step must exit 0, otherwise the entry ends `error` with reason "install failed: exit <code>".
- F26 python mutant listing does not call the mutmut CLI: a script run with the project interpreter inside the container uses mutmut 2.5.1's `list_mutations`/`mutate` API on each changed src file and prints one unified diff per mutation (file header + single hunk), the format `normalize("mutmut", ...)` accepts.
- F27 base images: go uses `golang:<max(go.mod go directive, 1.24)>-bookworm`; rust uses the pinned `BASE_IMAGES["rust"]` and installs cargo-mutants and cargo-nextest with that image's default toolchain, leaving a repository toolchain file for rustup to honor; python and typescript rules unchanged.
- F28 driver contract additions: state.json also carries `elapsed_s` and `phrases_sent`, and resume continues both (wall clock and turn cap are not reset); the driver passes the token read from `token_path` to the Claude CLI as `CLAUDE_CODE_OAUTH_TOKEN`; input keys required by the driver = run_id, arm, prompt, model, effort, aliases, disallowed_tools, wall_clock_s, max_user_turns, idle_grace_s, out_dir, token_path, proxy_url, resume, relay_dir, relay_timeout_s, relay_poll_s; `relay_driver.main([input_path])` reads `argv[0]`; AskUserQuestion answers are returned to the SDK as `updated_input = {"questions": <original>, "answers": <answers>}`.
- F29 every tool installed into project images has a pinned version held in `cfg.tools`: python `pytest==8.3.5 pytest-cov==6.1.1 hypothesis==6.131.0 mutmut==2.5.1`; typescript `@stryker-mutator/core@10.0.0 fast-check@4.10.2` plus the junit reporter package the runner needs (pinned to the version resolved at implementation time); go `github.com/avito-tech/go-mutesting/cmd/go-mutesting@v0.0.0-20261002081621-9ce5f731e321` and `gotest.tools/gotestsum@v1.13.0`, both installed with `GOTOOLCHAIN=auto` (the tool may need a newer Go than the project image; the project itself keeps the image's toolchain); rust `cargo install --locked cargo-mutants@27.1.0 cargo-nextest@0.9.149`. No `@latest` or unpinned install remains.
- F30 Stryker listing writes `/tmp/stryker.conf.json` = {"mutate": [changed src paths], "testRunner": "command", "commandRunner": {"command": "true"}, "reporters": ["json"], "jsonReporter": {"fileName": "/tmp/mutation.json"}, "tempDirName": "/tmp/stryker-tmp", "cleanTempDir": true, "concurrency": 4}, runs `npx stryker run /tmp/stryker.conf.json`, and prints `/tmp/mutation.json` (Stryker 10 rejects dotted CLI options such as `--commandRunner.command`, and `--dryRunOnly=false`); Stryker `location` columns are 1-based.
- F31 typescript runner selection (replaces "vitest when vitest is a dependency, else jest with jest-junit" in FR-R1): vitest when `vitest` is a dependency; else jest when `jest` is a dependency (jest-junit pinned); else mocha when `mocha` is a dependency (`mocha-junit-reporter` pinned in cfg.tools, `--reporter mocha-junit-reporter --reporter-options mochaFile=<junit path>`); else the Node test runner when the package.json `test` script contains `node --test` (`node --test --test-reporter=junit --test-reporter-destination=<junit path> <files>`); otherwise RecipeError "no supported test runner (vitest, jest, mocha, node --test)". All runners execute with the project's installed binaries only (no `npx` download).
- F32 go-mutesting listing runs `go-mutesting --debug <packages>` (the bool flag `--do-not-remove-tmp-folder` takes no value); its output must normalize to ≥ 1 mutant for a package with arithmetic or comparison code.
- F33 FR-V1 refinement: an f2p candidate is kept only when its test file is new in the gold diff, or its base name (last `::` segment without `[params]`, and for go without a `/subtest` suffix) occurs in an added line of the gold test diff for that file; other candidates are dropped from f2p (v13: they may be in p2p per F36). (A go package whose tests fail to compile at base otherwise turns every test in the package into f2p.)
- F34 `build_task` reads gold texts with UTF-8; a file that does not decode is left out of gold_base/gold_after and the split, and the candidate is not crashed (it is marked invalid with reason "binary" when that file is a src or test path).
- F35 `gold_selection(task)` leaves out test paths that the gold patch deletes (gold_after value None, after `#cfgtest` normalization). When the selection is empty, `validate_task` runs nothing and returns invalid with reason "no_f2p" (an empty selection would make most runners execute the whole suite).
- F36 p2p (replaces the p2p clauses of FR-V1 and F7): `validate_task` also runs the base-original state (tree = gold_base, i.e. base src with base tests) `cfg.validation.repeats` times with the orig selection = gold selection paths whose gold_base value is not None; for go the orig selection is the gold selection unchanged (gotestsum selects package directories). `classify(..., orig_runs=...)` returns p2p = ids passing in every orig run and every merge run, minus flaky ids (flaky also covers ids differing across orig repeats); f2p candidates are not removed there. `validate_task` then removes the final f2p ids (after the F33 relevance filter) from p2p, so an existing test that fails at base only because the gold tests do not compile, and that F33 drops from f2p, stays in p2p. There is no file-part restriction, because every run executes only its selection. An orig run with status build_error, timeout or parse_error does not invalidate the task: p2p is [] and "p2p_note" is that status. An empty orig selection runs nothing, p2p is [], and "p2p_note" is "no_base_tests"; the no-run no_f2p verdict of F35 also carries "no_base_tests". Otherwise "p2p_note" is null; orig_runs None gives p2p [] and "p2p_note" "no_base_tests". The task record keeps "p2p_note". (Gold tests that do not compile at base fail the whole go package or rust crate at base, which emptied p2p under the old rule; go ids are `<package>::<Test>`, so the file-part restriction never matched.)
- F37 go-mutesting listing never runs tests: the command first writes `/tmp/evaluation-mutesting-diff.sh` = `#!/bin/sh` / `diff -u "$MUTATE_ORIGINAL" "$MUTATE_CHANGED"` / `exit 0` (mode 0755), then runs `go-mutesting --exec /tmp/evaluation-mutesting-diff.sh <packages> 2>&1` (replaces F32's command). Its output (`--- <file>` / `+++ /tmp/go-mutesting-<n>/<file>.<k>` blocks between `PASS ...` and dash-rule lines) normalizes to one mutant per block, with path = the original file relative to /testbed (for a sub-package target, the file path includes the directory). The built-in exec ran `go test` for every mutant and exceeded the 1800 s listing timeout on spf13/cobra; the diff-only exec listed 1553 mutants in 24 s.
- F38 the image's nextest config file at `NEXTEST_CONFIG` contains exactly `[profile.junit.junit]` + newline + `path = "junit.xml"` + newline (valid TOML). Evidence must execute the Dockerfile RUN step's shell text with `sh` and parse the produced file with `tomllib`; asserting on the Python string literal is insufficient (the v11 step wrote `path = \"junit.xml\"` and every rust test run ended build_error).
- F39 Node test runner ids carry the file: the Node junit reporter writes no file information (`<testcase name=… classname="test"/>` under `<testsuite name="<describe>">`), so `test_argv` for runner `node-test` runs each selected file in its own `node --test --test-reporter=junit --test-reporter-destination=<dir>/<k>.xml <file>` process, continuing after a failing file and exiting non-zero if any file failed. It then writes one junit file at the requested junit path, in which every case of file `<file>` parses (`junit.parse(..., language="typescript")`) to an id `<file>::<describe chain>::<name>`, the same shape as the other typescript runners. `test_argv` returns `["sh", "-c", <text>]` with relative file paths, resolved from the working directory. The merge step may be one extra `node` invocation without `--test` (node and sh are the only tools guaranteed in the image). A stale file at the junit path is not relevant, because each run uses a fresh container. A file whose process produced no junit output contributes no cases. When no file produced output, no junit file is written (build_error per run_tests). Live: tj/commander.js ids were `help handling::<name>`, so equal describe/test names in two files collide and overwrite each other's status.
- F40 build context freshness: `build_task` reuses `<work>/context/repo` only when it was fully extracted from the same `base_sha`. Extraction goes into a temporary directory under `<work>/context`, which is renamed to `repo` after `tar` succeeds. A file `<work>/context/base_sha`, outside `repo/` so it never enters the image, records the sha. A missing or different record, or a missing `repo/`, removes any old `repo/` and re-extracts. A failed extraction leaves no `repo/` and, like a detection failure (Errors), marks only that candidate `build_error: git archive failed: <message>`; `build` continues with the other candidates and exits 0. Live: two candidates with the same task_id and different base_sha built the second image from the first base tree (the runner was detected as jest from the second base's package.json, while the image held the first tree without jest).
- F41 jest argv: `jest --ci --reporters=jest-junit --runTestsByPath -- <files>` (same env variables as FR-R1/F31). The array option `--reporters=<x>` otherwise consumes the following paths as reporter names ("Could not resolve a module for a custom reporter"). Verified live on typestack/class-validator: 671 cases, classname `<file>::<describe>`.
- F42 f2p relevance (replaces F33's rule; F33's name matching is reused): an f2p candidate is dropped only when (a) it passed in every orig run (F36) and (b) its base name, with F33's normalization, occurs in no added line of the gold test diff for its file. All other candidates stay in f2p: tests absent from the orig results (new tests, including parametrized `test.each` / `it.each` names that never appear literally), tests that did not pass at orig, and modified tests named in added lines. Without usable orig results (p2p_note not null), F33's rule applies unchanged. A dropped candidate that passes in orig and merge stays in p2p (F36). Live: tj/commander.js had 4 real fail→pass tests generated by `test.each([...])('when node execArgv includes %s then app/args')`, which F33 dropped; spf13/cobra's existing tests still pass at orig and are still dropped.
- F43 typescript mutation listing leaves `*.d.ts` paths out of the Stryker `mutate` list and out of FR-MU1 mutants (declaration files have no runtime code). Stryker aborts the whole run on a parse error in one file; live, `typings/index.d.ts` (BABEL_PARSE_ERROR DeclarationMissingInitializer) made the listing print nothing.
- F44 typescript junit names produced by jest-junit (root `<testsuites name="jest tests">`) are HTML-unescaped once more in the id (jest-junit escapes names before XML encoding). Live: `{"flags": "-a, -b <value>"}` arrived as `&lt;value&gt;` after XML parsing. Other runners' ids are unchanged.
evaluation/__main__.py: `def main(argv: list[str], cfg: dict | None = None, deps: dict | None = None) -> int` (deps optional keys "docker", "gh_fn", "call_fn", "run_fn"; `report <run_id>` is positional). Subcommands: mine, build, validate, brief, mutants, run, score, judge, report, pilot, doctor, gce {up, down, push, exec, pull, status}. Exit codes: 0 ok, 2 refused input (message names the fix), 3 halted by rate limit or interruption (message names `--resume <run_id>`).

# Functional Requirements
| id | requirement | priority | source |
| --- | --- | --- | --- |
| FR-M1 | `mine --language L` queries GitHub through `gh_fn` for merged PRs with `merged_at ≥ cfg.mining.merged_after` (2026-07-01) in non-archived, non-fork repos whose primary language is L (typescript also accepts javascript), with stars ≥ `cfg.mining.min_stars` (200) and license in `cfg.mining.licenses` | must | I2, cutoff Jun 2026 |
| FR-M2 | `eligible` rejects with one reason code: `bot_author` (login ends `[bot]`), `title_excluded` (title matches `cfg.mining.title_exclude` regexes), `no_tests` (no file classified test), `src_files` (fewer than 2 src files and no added public symbol), `src_lines` (added+deleted src lines outside [30, 800]), `harness_files` (any path classified harness), `binary` (binary file in diff); otherwise ok; when several apply, the first in the order listed is returned | must | I2 |
| FR-M3 | `search` returns at most `cfg.mining.per_repo_max` (3) candidates per repo and stops at `cfg.mining.target_per_language` (40); rows hold repo, pr number, base sha, merge sha, language, title, body, linked issue bodies, src/test line counts, merged_at; output written to `<cfg.data_dir>/tasks/<language>/candidates.jsonl` sorted by (repo, pr); `cfg.data_dir` defaults to `~/.harness/evaluation` (VM: `/data/evaluation`); run directories are `<cfg.data_dir>/runs/<run_id>/` | must | I2 |
| FR-R1 | `recipes.detect` picks the manager by first matching lockfile (python: uv.lock→uv, poetry.lock→poetry, pdm.lock→pdm, else pip with pyproject/requirements; typescript: pnpm-lock.yaml→pnpm, yarn.lock→yarn, bun.lock/bun.lockb→bun, package-lock.json→npm; go: go.mod; rust: Cargo.toml) and the runner (pytest with `--junitxml`; vitest `--reporter=junit` when vitest is a dependency, else jest with jest-junit; gotestsum `--junitfile`; cargo-nextest with junit profile); no match raises RecipeError naming the missing file | must | I7, environment-match defect in handoff |
| FR-R2 | one image per repo@base sha; the testbed is a fresh git repository whose single commit contains the base tree, with no remotes, tags or other refs; the language's mutation tool and fuzz/property library (mutmut+hypothesis, @stryker-mutator/core+fast-check, go-mutesting, cargo-mutants+proptest) are installed in the image for every arm; agent images add only the agent tool layer outside the project environment, so evaluation and agent runs share the project environment byte-for-byte | must | I3, I5, handoff defect (c) |
| FR-V1 | `validate` runs gold test files on base src and on merge src `cfg.validation.repeats` (3) times each; `classify` returns f2p = ids not passing in every base run and passing in every merge run; p2p per F36 (ids passing in every base-original run and every merge run); flaky = ids whose status differs across repeats of the same state; invalid with reason `no_f2p`, `flaky_f2p` (any f2p candidate flaky), `parse_error`, `timeout` (any run over `cfg.validation.timeout_s` 600) or `build_error` | must | I1 |
| FR-B1 | `make_brief` asks the judge model (`cfg.brief`: claude-opus-5-5, medium) to produce from PR title/body/linked issues, gold test diff and interface signatures: a user-voice request (3–12 sentences, counted as non-empty segments after splitting the stripped request on whitespace that follows `.`, `!` or `?`; English is a prompt instruction only, not validated) that names every interface signature and its path, ends with "Implement this and add automated tests.", and omits the behaviors of 1–2 statements listed in `ambiguous`; and an intent card of behavior statements, each mapped to ≥1 f2p id, covering every f2p id | must | I5 |
| FR-B2 | `interface_signatures` lists added or signature-changed public symbols in the gold src diff: python top-level `def`/`class` and methods not starting with `_`; typescript `export` declarations; go exported (capitalized) funcs, methods, types; rust `pub` items | must | I5 |
| FR-B3 | forbidden terms = f2p test function/case names, gold test file paths and basenames, string literals of ≥3 non-space chars on added gold-test lines that contain an assertion keyword (python `assert`, ts `expect`/`assert`, go `t.Error`/`t.Fatal`/`assert.`/`require.`, rust `assert`), and names defined only in gold test files; a request or intent card containing a forbidden term is regenerated, at most `cfg.brief.attempts` (3) total, then the task is dropped with reason `leak`; a parse failure counts as an attempt | must | I5 |
| FR-MU1 | `mutants --language L` per valid task: runs the language tool on the merge-state tree in the task image (python `mutmut`, typescript Stryker, go `go-mutesting`, rust `cargo mutants`); `normalize` accepts: mutmut and go-mutesting = concatenated unified diffs, one mutant per file-header + single-hunk block; stryker = mutation-testing-report JSON (`files.<path>.source`, `files.<path>.mutants[]` with `id`, `location.start.line`, `location.start.column`, `location.end.line`, `location.end.column`, `replacement`), diff built from source by replacing the location span; cargo-mutants = JSON list of objects with `file`, `line` (or `span.start.line`) and `diff`. id = sha256(f"{path}\0{line}\0{diff}")[:16] hex. `restrict` keeps mutants whose line is in `changed_lines(gold src part)` for that path; `sample` sorts by id then takes `random.Random(seed).sample` of size cap when more than cap (cap 40, seed 1). Each kept mutant is run with the gold tests (selection = gold test files): `gold` = killed when any id passing on the merge state fails or errors, survived otherwise, or the run status build_error/timeout; d_ref = killed mutants | must | A11 |
| FR-A1 | `run` executes entries (task, arm, repeat) with identical model `claude-sonnet-5-5`, effort `medium`, image, cpus/memory, wall clock (`cfg.agent.wall_clock_min` 180), `max_user_turns` (8), disallowed tools, network egress limited to `api.anthropic.com` through the proxy, and OAuth token mounted read-only | must | I3, I4 |
| FR-A2 | prompts: B0 = request; Bplus = request + "\n\n" + BPLUS_PARAGRAPH, where BPLUS_PARAGRAPH = "Write thorough automated tests: cover normal cases, boundaries, invalid inputs and error paths, assert observable behavior rather than implementation details, and run the tests before you finish."; H = "/workflow-approach " + request, with the harness installed from the recorded harness commit and committed before the agent starts: `git archive <harness_commit> harness installer` of this repository (only those two directories) is staged at `/opt/harness-src`, `installer/harness.py install /testbed --no-ci` runs with every prompt answered `y`, then one commit is made; manifest `harness_commit` is the full sha; B0/Bplus get no archive and no install | must | I3 |
| FR-A3 | the simulated user answers every AskUserQuestion and every idle turn of every arm through the relay; inputs are the request, the intent card statements (texts only, no f2p ids), the agent's questions or last top-level assistant text (cut to 8000 chars) and this entry's previous exchanges; rules given to the model: answer only from the card; outside the card reply with FALLBACK_IDLE wording or the recommended option; approve a plan/spec that does not contradict the card, otherwise state the contradicted behavior in plain words; return `stop` only when the agent reports it has finished | must | I5 |
| FR-A4 | a simulated-user response containing a forbidden term, unparseable output, a null answer or a timeout (`cfg.usersim.timeout_s` 900) is replaced by the fallback (ask: option containing "(Recommended)", else first option; idle: FALLBACK_IDLE) and recorded with the reason; the entry ends `completed` on `stop` or when an idle turn follows no tool call since the previous user message, `stalled` when `max_user_turns` simulated-user replies (the initial prompt not counted) were sent and the agent idles again after tool calls | must | I5 |
| FR-A5 | each entry stores manifest (task id, arm, repeat, model, effort, image ids, harness commit for H, prompt sha256, config hash, prereg sha256), full diff, `split_diff` parts, ledger, messages, telemetry, user-sim records, driver state (cost_usd, duration, turns), all scrubbed of the token | must | I1, I8 |
| FR-A6 | a rate-limit event, HTTP 429, VM preemption or host interruption ends the current entry `interrupted`; `run` stops starting entries and exits 3; `run --resume <run_id>` continues interrupted entries from their saved session and skips finished ones | must | reliability, subscription auth |
| FR-A7 | `run --retry-errors <run_id>` re-runs every entry whose status is `error` and whose `attempts` is 1, from scratch in a fresh container, and sets `attempts` 2 in run.json and manifest; an entry still `error` after its second attempt is final. `report` exits 2 naming `python3 -m evaluation run --retry-errors <run_id>` while any entry is `error` with attempts 1, and naming `--resume <run_id>` while any entry is `interrupted`. Final `error` entries are scored as failures: resolved false, f2p_frac 0, normalized and raw kill 0, ambiguity_correct rate 0, detection rate 0, no tests (excluded from false_alarm_rate), cost and wall time counted; the report shows final error counts per arm | must | user answer (error policy) |
| FR-S1 | `classify_path` order: harness (`agent-docs/`, `.harness/`, `.claude/`, `.agents/`, `.codex/`, root `AGENTS.md`, root `CLAUDE.md`), then test (python: a path segment `tests` or `test`, basename `test_*.py`, `*_test.py`, `conftest.py`; typescript: `*.test.*`, `*.spec.*`, segment `__tests__`, `test`, `tests`; go: `*_test.go`, segment `testdata`; rust: top-level `tests/`), then src (language source extensions: .py; .ts .tsx .js .jsx .mjs .cjs; .go; .rs), else other | must | I1 |
| FR-S2 | for rust, `#[cfg(test)]`-attributed `mod` items (blocks or bodyless declarations) inside src files belong to the tests part; `split_diff` represents them by moving those hunks' content: the src part holds the file without the modules, the tests part holds the module texts keyed `<path>#cfgtest` | must | I1 |
| FR-T1 | scoring runs, per entry: hidden (agent src + gold tests, selection = gold test files), validity (gold src + agent tests, 2 repeats), base-tests (base tree with every agent test path at its base version — absent when the agent created it — selection = the agent test paths that exist at base; `agent_test_ids(base_results, agent_results)` takes this run's results as base_results and the first validity run's results as agent_results, so only tests that existed before the agent's change are excluded; when no agent test path exists at base the run is skipped and base_results is empty), mutants (each sampled reference mutant + agent tests that are valid), with `cfg.eval.timeout_s` (900) per run; results cached by sha256 of (image id, tree, selection) | must | I1 |
| FR-T2 | test ids are `<file>::<suite path>::<name>` with parametrization suffix kept, normalized so the same test has the same id across states (python: junit classname dots mapped to file path; go: package dir + test name; rust: binary/crate name + module path; typescript: file + describe chain) | must | handoff defect (a) |
| FR-T3 | overlay rules: hidden = agent `after` for src/other paths + gold `after` for gold test paths (rust: gold `#cfgtest` modules appended to the agent version of that file); validity = gold `after` for src/other + agent `after` for agent test paths (rust: agent `#cfgtest` modules replace gold's in the gold file); harness parts are never applied | must | I1 |
| FR-T4 | metrics per entry: resolved, f2p_frac, agent test ids, validity classes per agent id over the 2 validity runs (valid = pass in both; false_alarm = fail in both; incompatible = each run error or missing; flaky = any other differing combination; skipped = skip in both, excluded from n; n = valid + false_alarm + incompatible + flaky) and false_alarm_rate = false_alarm / (valid + false_alarm), None when that denominator is 0, incompatible count (agent ids missing or error on every validity run), raw kill = killed / executed, normalized kill = |killed ∩ d_ref| / |d_ref| (d_ref = executed mutants killed by gold tests); an entry with zero valid tests scores kill 0 when executed > 0; executed = 0 gives raw and normalized None; |d_ref| = 0 gives normalized None; a task with |d_ref| < `cfg.report.min_mutants` (10) is excluded from kill aggregates and flagged; ambiguity_correct; cost_usd (sum of state results total_cost_usd); wall seconds (sum of duration_ms / 1000); questions = usersim rows of kind ask; corrections = idle rows with contradiction true; self_report = last `verification_result` event in `<entry>/raw/telemetry/*.jsonl` (harness telemetry: fields fuzz_execs, fuzz_violations, mutants, killed, survived, equivalent, overturned; rate = killed / mutants, None when mutants is 0) | must | I1, H1–H4 |
| FR-X1 | cross-arm: every pair (tests entry, impl entry) of the same task with different entries and impl status completed; buggy = impl not resolved; detection_rate = buggy impls where ≥1 valid test of tests-entry has status fail or error / buggy impls run ok; false_alarm_rate = correct impls where ≥1 valid test has status fail or error / correct impls run ok; only completed, stalled or capped entries serve as impls; build_error/timeout counted inconclusive | must | I1 |
| FR-J1 | judge (`cfg.judge`: claude-opus-5-5, medium) per task: candidates = test part of each completed entry plus the human gold test diff, labeled T1..Tn in an order shuffled with seed sha256(task id) ; `anonymize` replaces the run's 16-hex ids and every id from the entry's spec tables (whole word) with `ID`, and drops lines referencing `agent-docs/` | must | I6 |
| FR-J2 | absolute rubric per candidate: smells from the tsDetect/xUnit catalog SMELLS = (assertion_roulette, conditional_test_logic, eager_test, empty_test, exception_handling, magic_number, mystery_guest, redundant_assertion, sensitive_equality, sleepy_test, unknown_test, duplicate_assert, ignored_test) each with test name and quote; Test Desiderata judged properties DESIDERATA_JUDGED = (isolated, composable, readable, behavioral, structure_insensitive, specific, predictive, writable) scored 1–5 with rationale and quote; ISO/IEC/IEEE 29119-4 coverage per intent statement (covered / partial / none, quote) plus boundary and error-path coverage flags; measured desiderata deterministic (validity flaky = 0) and fast (validity runtime) come from scoring, not the judge | must | I6 |
| FR-J3 | pairwise per task and repeat index: H vs B0, H vs Bplus, Bplus vs B0, each in both orders; `combine_orders` gives the consistent winner, `tie` when both say tie or one tie and one winner, `inconsistent` when the orders disagree on winners | must | I6 |
| FR-J4 | judge output is JSON; every quote must be a substring of the candidate text after whitespace collapse; unknown smell or property names, scores outside 1–5, missing statements, or quote mismatches raise JudgeFormatError; one retry, then the item is recorded `error` | must | I6 |
| FR-P1 | `evaluation/preregistration.md` defines: primary H3 = normalized kill, paired per task (H − B0, repeats averaged first), cluster bootstrap by repo (10000 resamples, seed 1, 95% percentile; the statistic is the pooled task mean = sum of task differences / number of tasks, and each resample draws k clusters with replacement from the k repos and takes the pooled mean of the drawn clusters' tasks); verdict help if lo > 0, harmful if hi < 0, else no_help; insufficient if n_tasks < 10 for the scope; H3 guard = false_alarm_rate H − B0 upper bound > +0.10 → harmful; H3 secondary = cross-arm detection rate, judge pairwise win rate (wins / non-tie decisions, CI vs 0.5); H1 = resolved; H2 = ambiguity_correct rate, plus the user's blind preference on 5–8 pairs recorded by hand; H4 = median cost per resolved task ratio H/B0 ≤ 10 (above 10 → cost excessive) and wall time ratio reported; secondary comparisons vs Bplus use the same rules; pilot gates FR-P2 | must | I8 |
| FR-P2 | pilot gates, reported pass/fail: G1 B0 resolved rate ≤ 0.80 over pilot tasks (else raise difficulty before main); G2 per language ≥ 50% of candidates pass build+validate (else fix or drop language); G3 judge position consistency (non-inconsistent pairs / pairs) ≥ 0.70; G4 share of judged tasks where the human anchor has the lowest mean desiderata score ≤ 0.50; G5 zero leak-fallbacks caused by brief content, zero tokens in outputs | must | I2, I6 |
| FR-P3 | `pilot` selects, per language: selectable tasks = valid, brief status ok, not already pilot; repos ordered by (descending selectable count, repo name); first 2 repos; within a repo tasks by ascending PR number, first 2; the language's first task is the first selected task of the first repo; runs B0 and Bplus once per selected task and H once per language on its first task; then score, crossarm, judge, report; pilot tasks are marked and excluded from main runs | must | I2 |
| FR-RP1 | report JSON + Markdown in `evaluation/results/<run_id>.{json,md}`: per-entry metrics, per-task means, per-language and overall paired differences with CIs and verdicts, pilot gates, judge tables (smell counts, desiderata means, coverage rates, pairwise outcomes, consistency, anchor ranks), cost table, prereg sha256; never contains transcripts, tool inputs, diffs, test code, quotes longer than 200 chars, or the token | must | I1, I8 |
| FR-RP2 | a run started with `--phase main` stores the prereg sha256; `report` on that run exits 2 naming both hashes when the current file differs | must | I8 |
| FR-G1 | `gce up` (idempotent; each step skipped when the resource exists) creates in `cfg.gce.project`/`region`/`zone`: network + subnet, Cloud Router + NAT, firewall allowing tcp:22 only from 35.235.240.0/20, service account with secretAccessor on secret `cfg.gce.secret`, the secret version from the local token file when absent or different (compared by sha256 of the value, value passed via stdin, never argv), data disk `cfg.gce.data_disk` (300GB pd-balanced), and the VM (`n2-standard-16`, on-demand by default (`cfg.gce.spot` false; `spot: true` adds `--provisioning-model=SPOT --instance-termination-action=STOP`), no external IP, debian-12, `--service-account <sa email>` with `--scopes=cloud-platform`, `--metadata-from-file startup-script=<path of evaluation/docker/startup.sh>` installing docker, python3.12, node, claude CLI); the secretAccessor binding is `gcloud secrets add-iam-policy-binding <secret> --member=serviceAccount:<sa email> --role=roles/secretmanager.secretAccessor` | must | I7 |
| FR-G2 | `gce push` sends `git ls-files` content of the working tree to the VM; `gce exec` runs a command on the VM over IAP SSH, `--detach` under `nohup` with log in `/data/logs/<ts>.log`; `gce pull <run_id>` copies `/data/results/<run_id>.*` to `evaluation/results/` and the run directory to `~/.harness/evaluation/runs/<run_id>/`; `gce down` deletes the VM and keeps the data disk, `--purge` also deletes disk and secret after confirmation flag `--yes` | must | I7 |
| FR-G3 | on the VM the token file is `/data/secrets/oauth_token`, owner the run user, mode 0600, fetched from Secret Manager at boot by `gcloud secrets versions access latest --secret=<secret>` redirected to that file; the startup script never prints it: no `set -x`, no `echo`/`printf`/`cat` of the token file or of a variable holding the token | must | security |
| FR-C1 | `doctor` prints one line per check — docker server version, claude CLI version, token file presence and mode, free disk on the data dir — and each failure line names the fix; gh auth is printed as information ("needed only for mine") and never makes doctor fail | should | interaction |

# Errors
- GitHub API failure or rate limit in `mine` — exit 3 with remaining-reset time; candidates written so far persisted; rerun continues from the last repo.
- recipe detection failure — candidate marked `build_error: <RecipeError message>`; other candidates continue.
- image build failure or timeout — candidate `build_error` with last 50 log lines stored under the run dir (not in reports); continues.
- validation invalid — candidate kept with `valid: false` and reason; excluded from briefs.
- brief leak after 3 attempts or parse failures — task `dropped`, reason `leak` or `format`; excluded.
- missing image at `run` — exit 2 naming `python3 -m evaluation build --language L`.
- no valid tasks for `run` — exit 2 naming `python3 -m evaluation validate --language L` and `brief --language L`.
- `run --phase main` with only pilot tasks — exit 2 stating pilot tasks are excluded and naming `python3 -m evaluation mine --language L` to add tasks.
- unknown arm — exit 2 listing the valid arms B0, Bplus, H.
- unknown run id — exit 2 naming the runs directory `<data_dir>/runs/`.
- report via CLI: a token in any file under the run dir — exit 2 naming that file, without its content; forbidden content markers (diff headers, test code, transcripts) are checked in the rendered report text only (FR-RP1), since judge.json and usersim.jsonl legitimately hold test code and agent text.
- report with unretried error entries or interrupted entries — exit 2 per FR-A7.
- token file missing — exit 2 naming the expected path; no container started.
- simulated-user failure — fallback answer, row with reason; entry continues.
- driver crash / missing state — entry `error` with reason; run continues with next entry.
- rate limit / preemption — entry `interrupted`, exit 3, resumable; finished entries untouched.
- scoring run timeout or build error — run status recorded; mutant excluded from executed; hidden/validity marked inconclusive and the entry excluded from that metric's aggregate with a count in the report.
- judge format error twice — item `error`, counted in report; other items continue.
- report token or forbidden content — TokenInReport, nothing written, exit 2.
- prereg hash mismatch on main run — exit 2 with both hashes; nothing written.
- gcloud command failure — `gce` subcommand stops at the failing step, prints the step and stderr tail, exit 1; earlier resources stay.

# Cases
| id | level | input / state | expected result |
| --- | --- | --- | --- |
| C1 | normal | PR by human, 3 src files 120 lines, 1 test file, MIT, merged 2026-08-02 | eligible ok |
| C2 | boundary | src lines exactly 30 / 800 / 29 / 801 | ok / ok / src_lines / src_lines |
| C3 | error | author `dependabot[bot]` | bot_author |
| C4 | edge | 1 src file but adds `pub fn new_api` (rust) | ok (added public symbol) |
| C5 | edge | diff touches `CLAUDE.md` at repo root | harness_files |
| C6 | normal | python repo with uv.lock and pytest | manager uv, runner pytest junit |
| C7 | error | go repo without go.mod | RecipeError naming go.mod |
| C8 | normal | base runs: t1 fail×3, t2 pass×3; merge: t1 pass×3, t2 pass×3 | f2p [t1], p2p [t2], valid |
| C9 | boundary | t1 merge pass, pass, fail | t1 flaky; invalid flaky_f2p if t1 was the f2p candidate |
| C10 | edge | t1 missing at base (new test), passes at merge | t1 in f2p |
| C11 | error | no f2p | invalid no_f2p |
| C43 | edge | gold deletes a test file and changes another | selection omits the deleted file; only deletions → invalid no_f2p, no test run |
| C44 | normal | go: gold tests fail to compile at base (every base id fails), orig runs pass t2, merge passes t1 (new), t2 | f2p [t1], p2p [t2], p2p_note null |
| C45 | error | orig run build_error | valid per f2p rules; p2p [], p2p_note "build_error" |
| C46 | normal | go listing on a package with comparison code | ≥ 1 mutant, no `go test` executed (exec script only), each mutant path relative to /testbed |
| C12 | normal | rust file with `#[cfg(test)] mod tests {..}` and src fn changed | src part lacks the module; tests part has `<path>#cfgtest` |
| C13 | edge | nested `mod tests` inside `#[cfg(test)] mod outer` and a `#[cfg(test)]` on a fn (not a mod) | only the outer mod moves; the fn stays in src |
| C14 | normal | brief output with request naming all signatures, statements covering all f2p | parsed brief |
| C15 | error | request contains an f2p test name | regenerated; after 3 leaks dropped `leak` |
| C16 | edge | assert literal "ab" (2 chars) and "  x " (1 non-space) in gold test | not forbidden |
| C17 | normal | AskUserQuestion with 3 options, sim user picks option 2 | answer option 2 label sent |
| C18 | error | sim user output names a gold test file path | fallback "(Recommended)" option; row reason leak |
| C19 | edge | idle turn with no tool calls since last user message | entry completed, no sim-user call |
| C20 | boundary | 8th user message sent and agent idles again with tool calls | entry stalled |
| C21 | normal | Bplus prompt | request + blank line + BPLUS_PARAGRAPH exactly |
| C22 | normal | junit with 2 pass, 1 fail, 1 error, 1 skipped | statuses mapped |
| C23 | error | truncated XML | JunitError |
| C24 | edge | same pytest test reported with classname `tests.test_a.TestX` and file attr `tests/test_a.py` in two states | identical id |
| C25 | normal | 10 mutants executed, d_ref 8, agent kills 6 of d_ref + 1 outside | raw 0.7, normalized 0.75 |
| C26 | boundary | d_ref 9 (< 10) | task flagged, excluded from kill aggregate |
| C27 | edge | agent has 0 valid tests | kill 0, false_alarm_rate None |
| C28 | error | mutant build_error | excluded from executed |
| C29 | normal | 3 impls: A own, B buggy, C correct; A tests fail B, pass C | detection 1.0, false alarm 0.0 |
| C30 | normal | judge AB = first, BA = second (same candidate wins) | winner that candidate |
| C31 | edge | AB = tie, BA = first | tie |
| C32 | error | AB first(A), BA first(B) | inconsistent |
| C33 | error | judge quote not in candidate text | JudgeFormatError, retry, then error |
| C34 | normal | diffs from 12 tasks in 4 repos, seed 1 | deterministic CI identical across calls |
| C35 | boundary | lo exactly 0.0 | no_help (help requires lo > 0) |
| C36 | edge | 9 tasks | insufficient |
| C37 | error | report text contains the token | TokenInReport, no file |
| C38 | error | main run, prereg edited | exit 2 with both hashes |
| C39 | normal | `gce up` with all resources absent | ordered gcloud argv list from FR-G1; secret value via stdin |
| C40 | edge | `gce up` with every resource present and same secret hash | no create commands issued |
| C41 | error | rate-limit event mid-entry | entry interrupted, exit 3, resume continues it with saved session |
| C42 | edge | agent diff modifies `agent-docs/specs/x.md` and `.claude/settings.json` | harness part; never applied in overlays |

# Quality Applicability
| ISO/IEC 25010:2023 characteristic | applicable | rationale |
| --- | --- | --- |
| Functional suitability | yes | metrics decide whether the harness is kept |
| Performance efficiency | yes | thousands of container test runs; caching and concurrency decide wall time and VM cost |
| Compatibility | yes | VM (debian-12, docker) and Mac (unit tests, gce client) |
| Interaction capability | yes | long CLI runs need actionable exit messages and resumability |
| Reliability | yes | VM restarts and subscription rate limits are expected |
| Security | yes | OAuth token, GCP secret, and gold artifacts must not leak into agents or reports |
| Maintainability | yes | per-language logic must stay isolated for adding languages |
| Flexibility | no | languages beyond four are out of scope; maintainability covers adapter isolation |
| Safety | no | no physical or human harm surface |

# Quality Requirements
| id | characteristic / subcharacteristic | target and context | measure method / inputs / unit | threshold and direction | evidence: automated, review, mutation | source |
| --- | --- | --- | --- | --- | --- | --- |
| QR1 | Functional suitability / correctness | score, crossarm, stats, judge combine | automated cases C25–C36 | all pass | automated + mutation | I1 |
| QR-PRE | Functional suitability / appropriateness | preregistration content | R2 review: every FR-P1/FR-P2 rule present with same numbers | 100% rules present | review | I8 |
| QR2 | Performance efficiency / resource utilization | rerun of `score` on an unchanged run | fake docker counts container runs on second `score` | 0 runs (all cached) | automated | I7 |
| QR3 | Performance efficiency / capacity | concurrent entries per VM | `cfg.agent.concurrency` honored; fake docker records max simultaneous containers | ≤ concurrency (default 3) | automated | I7 |
| QR4 | Compatibility / interoperability | gcloud commands | argv from `plan_up` matches FR-G1 flags (`--no-address`, IAP range; no SPOT flags with `spot` false, both SPOT flags with `spot` true) | exact match | automated + R3 | I7 |
| QR5 | Interaction capability / operability | every exit 2/3 message | automated: message contains the remedy command or path | 100% of exit-2/3 paths | automated | FR-C1 |
| QR6 | Reliability / recoverability | interruption at any entry | resume after interrupted entry k of n | entries < k untouched (byte-identical files), k resumed, > k run | automated | FR-A6 |
| QR7 | Reliability / fault tolerance | writes of run.json, entry manifest.json and state.json copies, score.json, judge.json, task files, reports | atomic write via tmp + rename; crash simulated between write and rename | previous file intact | automated | FR-A6 |
| QR8 | Security / confidentiality | token | scan of every file written under run dir and results after scrub | 0 occurrences | automated + R4 | FR-A5, FR-G3 |
| QR9 | Security / confidentiality | gold isolation | files copied into agent containers (all arms, including H) and image build contexts, and relay responses | contain no gold test text, no f2p names, no merge sha; build context src is the base version; testbed history: B0/Bplus 1 commit, H 2 commits (base + install commit whose changed paths are all harness paths or `.gitignore`); no remotes | automated + R5 | I5 |
| QR10 | Security / confidentiality | secret transport | `plan_up` argv and logged commands | token value never in argv or logs | automated | FR-G1 |
| QR11 | Maintainability / modularity | language-specific logic | grep of non-adapter modules for language literals other than dispatch tables | language branches only in languages.py, junit.py, recipes.py, mutants.py, brief.interface_signatures | review R1 | design |
| QR12 | Maintainability / testability | branch coverage | coverage.py branch over evaluation/ excluding agent/driver.py copy and gce live paths | ≥ 85% | automated | Test command |

# Verification Obligations
| id | parent requirement/Case ids | variant and target surface | test layer and selection policy | ISO/IEC/IEEE 29119-4 technique | coverage items | coverage target | observation and expected result | evidence procedure |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| O1 | FR-M2, C1–C5 | `mine.eligible` | unit | boundary value analysis (2-value) + equivalence partitioning | reasons {ok, bot_author, title_excluded, no_tests, src_files, src_lines, harness_files, binary}; boundaries 29/30, 800/801 | 100% | returned reason per case | automated |
| O2 | FR-M1, FR-M3 | `mine.search` with fake gh_fn | integration (fake) | scenario | per_repo_max cap, target stop, sorting, merged_after filter, ts accepts javascript | 100% | rows count/order/fields | automated |
| O3 | FR-R1, C6–C7 | `recipes.detect`, `test_argv` | unit | decision table | rules: 4 python, 4 ts, go, rust, vitest-vs-jest, no-match per language | 100% | manager/runner/argv; RecipeError text names file | automated |
| O4 | FR-R2 | `recipes.dockerfile` + build step with fake docker | integration (fake) | equivalence partitioning | single-commit testbed, no remote, tools per language, agent layer separate | 100% | Dockerfile/commands contain required steps; testbed git commands | automated + R5 |
| O5 | FR-V1, C8–C11, C43–C45, F35, F36 | `validate.classify`, `validate.gold_selection`, `validate.validate_task` | unit | decision table | f2p, p2p from orig ∧ merge (F36), classify p2p minus flaky only (incl. orig-repeat flakiness), validate_task p2p minus final f2p, C44 at validate_task level (F33-dropped candidate t2 stays in p2p), orig error → p2p_note, empty orig selection, orig_runs None, deleted gold test files excluded, empty selection → no run, go orig selection = gold selection, flaky, no_f2p, flaky_f2p, parse_error, timeout, build_error, missing-at-base | 100% | returned dict; selections passed to run_tests | automated |
| O6 | FR-B2 | `brief.interface_signatures` | unit | equivalence partitioning | per language: public added, public changed, private excluded, unchanged excluded | 100% | signature list | automated |
| O7 | FR-B3, C15–C16 | `brief.forbidden_terms`, `leaks` | unit + property | boundary value analysis + equivalence partitioning | term classes {f2p name, test path, basename, assert literal per language keyword, test-only name}; literal length 2/3 non-space | 100% | leaks list | automated + fuzz P3 |
| O8 | FR-B1, FR-B3, C14–C15 | `parse_brief`, `make_brief` with fake call_fn | unit | scenario | ok first try; leak then ok; 3 leaks → dropped; format error counts attempt; statements not covering all f2p → format error; request missing a signature or closing sentence → format error | 100% | status/attempts/reason | automated |
| O9 | FR-A2, C21 | `compose_prompt` | unit | equivalence partitioning | B0, Bplus, H, unknown arm (ValueError) | 100% | exact strings | automated |
| O10 | FR-A3, FR-A4, C17–C20 | `usersim.respond`, `Relay`, relay_driver | unit + integration (fake container) | state transition | states: ask→answered, ask→leak fallback, ask→timeout fallback, ask→null fallback, idle→reply, idle→stop→completed, idle no tools→completed, turn cap→stalled | 100% | responses, rows, final status | automated |
| O11 | FR-A3 | `usersim.build_prompt` | unit | equivalence partitioning | contains request, statement texts, rules; excludes f2p ids, gold diff text | 100% | substring presence/absence | automated |
| O12 | FR-A1, FR-A5, FR-A6, C41, QR6, QR7 | `run` with fake docker and fake driver outputs | integration (fake) | state transition | entry states {completed, stalled, capped, error, interrupted}; resume skips finished, resumes interrupted; exit 3; manifest fields; identical non-prompt config across arms | 100% | files, exit codes, manifests | automated |
| O13 | FR-S1, FR-S2, C12–C13, C42 | `classify_path`, `split_diff`, `split_rust_inline` | unit + property | classification tree | classes: harness paths ×7, test patterns per language, src ext per language, other; rust inline mod top-level, nested, cfg(test) fn, string containing `#[cfg(test)]` | 100% | part assignment | automated + fuzz P1/P2 |
| O14 | FR-T2, C22–C24 | `junit.parse` | unit + property | equivalence partitioning | statuses ×4 per language format; id normalization rules per language; malformed XML | 100% | id→status map; JunitError | automated + fuzz |
| O15 | FR-T3 | `overlay.*_tree` | unit | decision table | path kinds {src, other, test, harness} × {gold only, agent only, both}; rust cfgtest append/replace; deletions | 100% | resulting tree map | automated |
| O16 | FR-T1, FR-T4, C25–C28, QR2 | `score` functions + `score` command with fake docker | unit + integration | decision table + boundary value analysis | resolved rules, false_alarm_rate, incompatible, flaky, kill raw/normalized, d_ref 9/10, zero valid tests, build_error, timeout, cache hit | 100% | metric values, cache-run counts | automated |
| O17 | FR-X1, C29 | `crossarm.detection` | unit | decision table | own excluded, buggy detected/not, correct alarmed/not, inconclusive, zero buggy (rate None) | 100% | per-entry dict | automated |
| O18 | FR-J1 | `judge.candidates`, `anonymize` | unit | equivalence partitioning | human included, shuffle deterministic by task, 16-hex ids, spec ids whole-word only, agent-docs lines dropped | 100% | labels/order/text | automated |
| O19 | FR-J2, FR-J4, C33 | `parse_absolute` | unit | syntax testing | valid; unknown smell; unknown property; score 0/6; missing statement; quote mismatch; whitespace-collapsed quote ok; non-JSON | 100% | dict or JudgeFormatError | automated |
| O20 | FR-J3, C30–C32 | `combine_orders`, pairwise scheduling | unit | decision table | 9 combinations of {first, second, tie}² ; pair list per task/repeat | 100% | outcome | automated |
| O21 | FR-P1, C34–C36 | `stats.cluster_bootstrap`, `verdict` | unit | boundary value analysis + metamorphic | lo 0/+ε, hi 0/−ε, n_tasks 9/10, guard upper bound 0.10/0.10+ε; metamorphic: permuting cluster order leaves result unchanged, adding constant c shifts mean/lo/hi by c | 100% | values/verdicts | automated |
| O22 | FR-P2, FR-P3 | pilot selection + gates | unit | decision table | G1–G5 pass/fail edges (0.80, 0.50, 0.70, 50%); repo selection ties; H on first task per language | 100% | gate results, selected tasks | automated |
| O23 | FR-RP1, FR-RP2, C37–C38, QR8 | `report.build/render/write` | unit + integration | equivalence partitioning | sections present; quotes > 200 chars truncated; token refusal; diff/test-code marker refusal; prereg mismatch exit 2; non-main run ignores mismatch | 100% | files or refusal | automated |
| O24 | FR-G1–G3, C39–C40, QR4, QR10 | `gce.plan_up/up/down/push/exec_remote/pull` with fake run_fn | unit | scenario | all absent; all present; secret changed; down keeps disk; purge requires --yes; exec detach; pull paths; failure stops at step | 100% | argv sequence; stdin carries secret; exit codes | automated + R3 |
| O25 | QR3 | run concurrency | integration (fake) | boundary value analysis | concurrency 1, 3; 4 pending entries | 100% | max simultaneous containers | automated |
| O26 | QR5, FR-C1 | CLI exit paths | integration | equivalence partitioning | each exit-2/3 path listed in Errors | 100% | message contains remedy | automated |
| O27 | QR9 | container staging | integration (fake) | error guessing | gold test text, f2p names, merge sha staged into container or relay response | none — experience-based | absent | automated + R5 |
| O28 | QR12 | coverage | — | branch testing | evaluation/ branches excl. omitted files | 85% | coverage report | Test command |
| O29 | FR-A2 (H install), QR9 | H staging and install with fake docker | integration (fake) | scenario | archive of recorded commit staged at /opt/harness-src; install argv with `--no-ci` and `y` answers; commit after install; manifest harness_commit; B0/Bplus without archive/install; H staged files free of gold strings | 100% | exec/copy records, manifest | automated + R5 |
| O30 | FR-MU1 | `mutants.normalize/restrict/sample` + `mutants` command with fake docker | unit + integration (fake) | equivalence partitioning + boundary value analysis | each tool raw format positive case; id formula; restrict in/out of changed lines; sample at cap 40/41 and seed determinism; gold classification killed/survived/build_error/timeout; d_ref | 100% | mutant lists, task mutants field | automated |
| O31 | FR-A7 | `run --retry-errors`, report refusals, error scoring | integration (fake) | state transition | error attempts 1 → retried → completed; error → retried → error final; report refuses unretried error / interrupted; final error scored as failure per FR-A7 in aggregates | 100% | run.json, report values, exit codes | automated |
| O32 | F37, F38, C46, FR-MU1, FR-R1 | `mutants.list_command`, `mutants.normalize("go-mutesting", …)`, `recipes.dockerfile` nextest step | unit | scenario | go command writes the exec script with the exact text and uses `--exec`, never the built-in exec; normalize of a captured F37 output (root and sub-package files, PASS and dash-rule lines) gives one row per block with relative paths; nextest RUN step executed with sh yields a file `tomllib` parses to {"profile": {"junit": {"junit": {"path": "junit.xml"}}}} | 100% | argv text; rows; parsed TOML | automated + live check 5 |
| O33 | F39, FR-R1 | `recipes.test_argv` (runner node-test) + `junit.parse` | unit | scenario | two files with an identical describe/test name keep distinct ids `<file>::…`; nested describe chain; a failing file still lets later files run and the combined exit is non-zero; a file without output contributes nothing; no output at all → no junit file. Evidence executes the generated shell text with a fake `node` that writes the real Node junit shape | 100% | parsed ids and statuses; exit code; junit file presence | automated + live check 6 |
| O34 | F40, F41, FR-R1 | `recipes.build_task` (fake run_fn/docker), `recipes.test_argv` (jest) | unit | scenario | same task_id built twice with different base_sha → second archive extracted and Dockerfile context holds the second tree; same base_sha → no second extraction; failed tar → no `repo/` and build_error; record file not under `repo/`; jest argv ends with `--runTestsByPath`, `--`, then the selection, with `--reporters=jest-junit` before `--` | 100% | run_fn calls; context contents; argv | automated + live check 7 |
| O35 | F42, F43, F44, C44 | `validate.validate_task`, `mutants.list_command`/`build_mutants` (typescript), `junit.parse` | unit | decision table + scenario | F42 rows: candidate absent at orig (kept, incl. a `test.each` name not in added lines), failed at orig (kept), passed at orig + name in added lines (kept), passed at orig + name absent (dropped, in p2p), orig unavailable → F33 rule; C44 still holds; F43: changed `x.d.ts` + `a.ts` → mutate list `[a.ts]` only, no `.d.ts` mutant; F44: jest root with `&amp;lt;value&amp;gt;` → id contains `<value>`, vitest/node-test ids unchanged | 100% | f2p/p2p lists; Stryker config text; ids | automated + live check 8 |

# Assumptions and Defaults
| id | decision | evidence and uncertainty | brief v<n> — approved / vetoed → <answer> / user answer |
| --- | --- | --- | --- |
| A1 | GCP project `harness-eval-d31ee3` on billing account 018F2D-F14BD0-7BB943, budget alert ₩140,000 (≈$100) at 50/90/100% | created this session; account currency is KRW | user answer |
| A2 | simulated user model claude-opus-5-5 medium | user choice | user answer |
| A3 | H arm forced with `/workflow-approach` | user choice | user answer |
| A4 | Bplus in pilot; main inclusion decided after pilot | user choice | user answer |
| A5 | agents authenticate with the subscription OAuth token via Secret Manager | user choice; rate limits halt with exit 3 | user answer |
| A6 | judge included in this run and the pilot | user choice | user answer |
| A7 | languages python, typescript (incl. javascript), go, rust | harness verification tools cover these four (`installer/verification_tools.py:13`) | brief v1 — approved |
| A8 | tasks merged ≥ 2026-07-01 | Sonnet 5.5 and Opus 5.5 training data cutoff Jun 2026 (platform docs models overview) | brief v1 — approved |
| A9 | request names the public interface signatures and their paths | without it agent tests cannot run against the reference implementation (API mismatch); reduces realism of H2 | user answer |
| A10 | H4 threshold: cost per resolved task ratio H/B0 ≤ 10 | user-set per handoff | user answer |
| A11 | mutation tools per language (mutmut, Stryker, go-mutesting, cargo-mutants), cap 40, seed 1, restricted to gold-changed lines; same tools installed for every arm | standard tools; harness installer uses the same set | brief v1 — approved |
| A12 | JUnit XML as the single result format (pytest, vitest/jest-junit, gotestsum, cargo-nextest) | uniform parsing; runner tools added to the image if absent | brief v1 — approved |
| A13 | GCE: n2-standard-16 on-demand (STANDARD provisioning; was spot until v12), no external IP + Cloud NAT, IAP SSH, 300GB data disk kept on `down` | NAT ≈ $1/day; on-demand ≈ $0.78/h | brief v1 — approved; on-demand by user decision after two spot preemptions ("on-demand로 전환") |
| A14 | main sample 15–20 tasks per language, 2 repeats per arm; decided again before main | power vs subscription throughput | brief v1 — approved |
| A15 | testbed is a single-commit repo without history or remotes | agent could otherwise read the merge commit | brief v1 — approved |
| A16 | `selfcheck/` code copied (driver, docker_exec, relay pattern), not imported | selfcheck is archived; copies keep it frozen | brief v1 — approved |
| A17 | test framework: unittest-style tests run by pytest in `.venv` with pytest-cov and hypothesis | repo uses stdlib unittest; mutmut 2.5.1 needs a pytest runner | brief v1 — approved |
| A18 | cluster bootstrap by repository | tasks from one repo are correlated | brief v1 — approved |
| A19 | error entries: one retry from scratch, then scored as failures; counts reported per arm | user choice in this session | user answer |
| A20 | H testbed has 2 commits (base + harness install); QR9/R5 restated | verifier F-2; a local install writes .agents/ .claude/ .codex/ .gitignore .harness/ agent-docs/ AGENTS.md CLAUDE.md | contract-only (no brief item) |

# Traceability
| requirement id | Case ids | obligation ids | evidence procedure |
| --- | --- | --- | --- |
| FR-M1, FR-M3 | — | O2 | automated |
| FR-M2 | C1–C5 | O1 | automated |
| FR-R1 | C6, C7 | O3 | automated |
| FR-R2 | — | O4, O27 | automated + R5 |
| FR-V1 | C8–C11, C43–C45 | O5 | automated |
| FR-B1 | C14, C15 | O8 | automated |
| FR-B2 | — | O6 | automated |
| FR-B3 | C15, C16 | O7, O8 | automated + fuzz |
| FR-A1, FR-A5, FR-A6 | C41 | O12, O25, O26 | automated |
| FR-A2 | C21 | O9, O29 | automated + R5 |
| FR-A7 | — | O31 | automated |
| FR-MU1 | — | O30 | automated |
| FR-A3, FR-A4 | C17–C20 | O10, O11 | automated |
| FR-S1, FR-S2 | C12, C13, C42 | O13 | automated + fuzz |
| FR-T1, FR-T4 | C25–C28 | O16 | automated |
| FR-T2 | C22–C24 | O14 | automated + fuzz |
| FR-T3 | — | O15 | automated |
| FR-X1 | C29 | O17 | automated |
| FR-J1 | — | O18 | automated |
| FR-J2, FR-J4 | C33 | O19 | automated |
| FR-J3 | C30–C32 | O20 | automated |
| FR-P1 | C34–C36 | O21 | automated + R2 |
| FR-P2, FR-P3 | — | O22 | automated + R4 |
| FR-RP1, FR-RP2 | C37, C38 | O23 | automated |
| FR-G1–FR-G3 | C39, C40 | O24 | automated + R3 |
| FR-C1 | — | O26 | automated |
| QR1–QR12, QR-PRE | — | O16–O28 | as listed |

# Workflow Control
| item | value |
| --- | --- |
| correction batches used | 12 |
| verifier invocations | 2 |
| open finding ids | F-1, F-3, F-4, F-6, F-8, F-9, F-10, F-12–F-21 (verifier round 1; addressed by v5–v8 evidence, awaiting round 2) |

Audit state (one entry per obligation; retain prior decisions in the execution ledger):
| obligation id | spec version | evidence references and revision | accepted / open / invalidated / pending | rationale and mutation outcome | dependencies and reopening evidence |
| --- | --- | --- | --- | --- | --- |
| O1, O2, O6, O7, O9, O10, O15, O20, O25, O28 | 4 → 16 | evaluation/tests/ at run 11 | invalidated (accepted in round 1; tests and shared fakes changed in v5–v16: mine G1–G6, driver F28, judge G37–G38, build-context fakes) | re-audit in round 2 | reopened by evidence changes |
| O3–O5, O8, O11–O14, O16–O19, O21–O24, O26, O27 | 16 | run 11 | open → evidence revised in v5–v16 | round 1 findings addressed; O5 (F35/F36/F42), O3/O4 (F31/F39–F41), O24 (on-demand), O30 changed | — |
| O29–O31 | 6 | run 11 | pending | new in v5; evidence in test_v5_*, test_v8_* | — |
| O32–O35 | 12–16 | run 11 (test_v11 go listing, test_v12, test_v14, test_v15, test_v16) | pending | new in v12–v16; hand mutations M1–M14 (M13 pipeline-equivalent) | — |

Execution ledger (append attempts; preserve failed approaches):
| attempt | finding / failure signature | cause hypothesis | changed approach / new evidence | result / disposition |
| --- | --- | --- | --- | --- |
| 1 | Test command v2: 75 failed / 303 passed / 2 skipped, coverage 61% | verified: undefined formats (gh protocol, model JSON schemas, repeat base, gate keys, kill keys, container contract) guessed differently by the roles; plus implementation defects (relay forwards token/merge sha, all-language tools in Dockerfile, rust split/overlay, stalled entries judged, G4 strictness, search query lacks merged date) and test defects (empty `ambiguous`, seed-sensitivity assertion with 4 clusters) | spec v3 Formats F1–F18; redispatch both roles with the affected ids | resolved by v3 + redispatch; run 2: 6 failed / 492 passed, coverage 86.99% |
| 2 | Test command v3: 6 failed — missing project image not refused; pilot tasks not excluded from main; rate_limit rejected recorded completed; validity n = 0 for new agent test files (3 tests) | verified: 3 implementation defects (Errors, FR-P3, F3); spec defect in FR-T1 base-agent tree | spec v4 FR-T1 base-tests; redispatch implementer D13–D16; tests unchanged | resolved; run 3: 498 passed / 1 skipped (startup-script check → R3), coverage 87.09% |
| 3 | verifier round 1: retry — 17 evidence gaps (F-1, F-3, F-4, F-6, F-8–F-10, F-12–F-21) and 5 spec challenges (F-2, F-5, F-22, F-23, F-24) | verified: tests observe outputs but not wiring (run settings, relay start, report aggregates, pilot metric derivation, score_entry inputs, judge prompt blinding, build context); spec silent on H install, pilot order, mutants, metric edge definitions | spec v5; redispatch test-implementer for all gaps + O29–O31, implementer for FR-A7, FR-MU1, FR-P3, FR-T4/FR-X1 definitions, FR-G1/G3, Errors remedies | resolved by v5/v6 and redispatch; run 4: 705 passed / 9 failed |
| 4 | Test command v6: 705 passed / 9 failed / 1 skipped, coverage 88.33% — hidden tree lacks agent src (split.json base/after empty under the fake), leak rows not counted, final-error kill None, run-file token scan missing, transcript markers and 201-char quotes accepted, run_matrix pairs across tasks | verified: entry text collection, row format, markers and quote location undefined (spec); final-error kill, token scan (v6 sent after implementer finished), cross-task pairing are implementation defects | spec v7 F19–F22; redispatch implementer D17–D23; test-implementer aligns fakes with F19/F20 | resolved by v7; run 5: 721 passed / 0 failed, coverage 88.70% |
| 5 | live checks: realistic H install (4 repos, no network) exit 1 everywhere (installer writes .harness-targets.json into read-only /opt/harness-src) and npm install waits 600 s; image tool check: python mutmut CLI crash → 0 mutants, golang:1.15-bookworm missing, ky has no lockfile (excluded by FR-R1), rust ok; VM suite 20 failures because push lacked .git; gce up IAM propagation failure; mutmut self-run 300 sampled: 194 killed / 105 survived / 1 timeout (35%), triage: ~55 declared, 5 equivalent, ~30 undeclared, 16 insufficient context | verified by live runs on harness-eval-vm | spec v8 F23–F28; implementer fixes; test-implementer closes declared survivors and the main-resolved insufficient ones | pending |
| 6 | Test command v8: 897 passed / 3 failed, coverage 90.35% — invalid `@@ --1,0` hunk headers for new rust files in split parts; final-error report rows drop score questions; usersim format failures recorded `unparseable` instead of `format` | verified implementation defects; F20 success reason conflict resolved in v9 | redispatch implementer D24–D26 | resolved; run 6: 900 passed, coverage 90.35% |
| 7 | live check 2: H install ok (python, typescript, rust: exit 0, 2 commits, 0 non-harness paths, tool prompt not offered); listing ok for python and rust; typescript Stryker CLI options rejected; go-mutesting@latest needs go ≥ 1.27 | verified live | spec v10 F29/F30; implementer fix; live check 3 adds real test runs (junit) per language | resolved by v10; run 7: 922 passed |
| 8 | live check 3 (after VM preemption, restarted): python all steps ok; typescript gold run build_error (repo uses node --test, jest absent); go listing rc 3 (bad flag) and f2p 384 from base compile failure; rust build_task UnicodeDecodeError on a binary file; H install ok in python/typescript/go | verified live | spec v11 F31–F34; implementer + tests | pending |
| 9 | live check 4 (on-demand VM): python all steps ok (971 tests, f2p 18 / p2p 951); typescript gold selection contained only deleted test files → `node --test` "Could not find" → build_error; go listing ran `go test` per mutant and hit the 1800 s timeout, go p2p 0 (base compile failure + file-part restriction never matching `<package>::<Test>` ids); rust every test run build_error from an escaped nextest TOML (`path = \"junit.xml\"`); H install ok in all four languages | verified live (VM reproductions) | spec v12 F35–F38 (+ on-demand FR-G1/A13); implementer + test-implementer; live check 5 picks a range with added test lines | v13 contract fix (F36 candidates vs C44); run 8: 996 passed, coverage 90.87%; hand mutations M1–M6 (final-f2p removal, orig flakiness, go built-in exec, escaped TOML, deleted files kept, spot default) all killed; live check 5 pending |
| 10 | live check 5: python, go, rust, typescript all steps run (go p2p 380, listing 23 s / 1556 mutants; rust gold 11 pass; typescript node --test 30 pass; H install ok ×4); typescript and rust ranges no_f2p (range choice); node-test ids lack the file part (Node junit reporter has no file attribute) | verified live (junit XML inspected in the image) | spec v14 F39; implementer + test-implementer; live check 6 adds vitest (unjs/ufo) and jest (typestack/class-validator) repos | O33 fake node treated the merge invocation as a test run (test defect, fixed; F39 calling convention stated); run 9: 1003 passed, coverage 90.89%; hand mutations M7 (single process) and M8 (failing file ignored) killed; live check 6 pending |
| 11 | live check 6 (typescript): node-test ids carry the file (F39 ok); vitest (unjs/ufo) runs selected files only, 36–212 cases with file ids, listing 682 mutants (34 on changed lines); jest build_error on class-validator (paths consumed by `--reporters`) and on an older commander.js range (stale build context reused for a second base_sha of the same task_id); ufo ranges after the first were built from the first tree (same image id), so their no_f2p is not evidence | verified live (reproduced in images) | spec v15 F40, F41; implementer + test-implementer; live check 7 | archive failure escaped as exit 2 (implementation defect D35; F40 now states candidate build_error); run 10: 1013 passed, coverage 90.97%; hand mutations M9 (reuse regardless of sha), M10 (jest without `--`), M11 (archive failure raises) killed; live check 7 pending |
| 12 | live check 7 (typescript): jest now runs (19–21 cases, file ids); F40 re-extraction ok (fresh image per range); every commander/ufo range no_f2p — diagnosis on commander f7b84757..27b13496: 4 real fail→pass `test.each` tests dropped by F33's name rule; Stryker listing failed on `typings/index.d.ts`; jest ids double-escaped; one range migrates jest→node:test (0 jest cases, correctly no_f2p) | verified live (base/merge diff and Stryker log in the image) | spec v16 F42–F44; implementer + test-implementer; live check 8 | run 11: 1025 passed, coverage 91.11%; hand mutations M12 (F42 ignores orig) and M14 (unescape for every runner) killed; M13 (`.d.ts` kept in the Stryker config) survived as pipeline-equivalent, because `build_mutants` filters `.d.ts` before the config is built; live check 8: commander (node-test, jest), ufo (vitest), class-validator (jest) all have a valid range (f2p 4 / 8 / 8; F42 recovered the `test.each` f2p), Stryker listing ok on every range, H install ok | resolved; verifier round 2 dispatched |
| 13 | verifier round 2: limit — blocking evidence gaps R2-1 (FR-M2 precedence), R2-2 (bodyless rust test mod), R2-3 (agent image FROM project image), R2-4 (detection pipeline/report), R2-5 (kill baseline with non-pass ids; multi-language report); spec challenges R2-S1–R2-S6 | verified by audit report (not re-run by main) | budget exhausted (2 of 2); handoff d63aaa61098054c3 | limit |

# Version Log
## v16
- [intent-mismatch] live check 7: F33's name rule dropped real parametrized f2p (typescript `test.each`), invalidating most typescript ranges; F42 drops a candidate only when it passed at orig and is not named in added lines. F43 `.d.ts` out of Stryker; F44 jest-junit double escaping (O35).
## v15
- Contract-only from live check 6: F40 build context freshness; F41 jest argv ordering (O34).
## v14
- Contract-only from live check 5: F39 node-test runs one process per file so ids carry the file (O33).
## v13
- Contract-only: F36 internal contradiction found while reconciling the implementer report: removing all f2p candidates from p2p empties p2p whenever the gold tests do not compile at base (every id is a candidate), contradicting C44. classify removes only flaky ids; validate_task removes the final (post-F33) f2p. F35 no-run verdict p2p_note stated.
## v12
- [intent-mismatch] live check 4: F35 deleted gold test files left out of the selection; F36 p2p from base-original runs (the user approved the Multi-SWE-bench-style definition: "진행해."); F37 go-mutesting listing via a diff-only exec script; F38 executable nextest TOML evidence; FR-G1/A13/QR4 on-demand VM default per the user's "on-demand로 전환" after two spot preemptions.
## v11
- [intent-mismatch] FR-R1 typescript runner default (jest) was wrong for repositories without jest: tj/commander.js uses `node --test`, and the jest run tried to download jest (no network) → F31. Live check 3 also found the go-mutesting flag error (F32), f2p = 384 for spf13/cobra because base compile failure fails the whole package (F33), and a UnicodeDecodeError on a PNG in build_task (F34). Python passed every live step (971 tests, f2p 20 / p2p 951, 26 mutants, H install ok).
## v10
- Contract-only from live check 2 on harness-eval-vm: H install now exits 0 with 2 commits and no non-harness change in python/typescript/rust; python listing 1249 mutants (26 on changed lines); rust 175 (24); typescript listing failed (`unknown option '--dryRunOnly=false'`, then `--commandRunner.command`) → F30; go image failed (go-mutesting@latest requires go >= 1.27) → F29 pins all tools.
## v9
- Contract-only: F20 success-row reason is null (matches the accepted O10 evidence and the implementation); failure outcome names unchanged.
## v8
- Contract-only from live checks and mutation triage: F23 push ships .git and local tasks; F24 IAM propagation retry; F25 H install environment (targets file, never-preference) — install exited 1 in all four languages and npm waited 600 s in a realistic install test; F26 python mutant listing via mutmut API — mutmut CLI crashed on a modern pyproject.toml (toml IndexError) and produced 0 mutants for pallets/click; F27 base image floors — golang:1.15-bookworm does not exist (spf13/cobra); F28 driver contract fields for resume, token env, input keys, argv, AskUserQuestion payload; FR-C1 doctor lines.
## v7
- Contract-only from Test command run 4 (705 passed / 9 failed): F19 entry text collection derived from the full diff; F20 usersim row format and G5 leak count; F21 report refusal markers and quote truncation; F22 run_matrix task filter; FR-S2 covers bodyless mod declarations. FR-A7 kill 0 for final errors unchanged (implementation defect).
## v6
- Contract-only: H archive limited to `harness/` and `installer/` (whole-repo archive would stage evaluation/ code into agent containers); report refusal scope split: token scan over run files, content-marker scan over rendered report text. Both from implementer report on v5.
## v5
- [intent-mismatch] Error entries were excluded from analysis without a spec rule; the user chose one retry then failure scoring (FR-A7, A19, preregistration update).
- Contract-only from verifier round 1 spec challenges: F-2 H install and QR9/R5 restated (A20, O29); F-5 pilot selection order (FR-P3); F-22 FR-MU1 + O30; F-23 validity classes, kill None rules, self_report source (FR-T4); F-24 sentence counting (FR-B1); F-16 bootstrap statistic (FR-P1); FR-M2 precedence; FR-X1 fail-or-error detection; FR-G1 service account and startup-script flags; FR-G3 non-printing rules; QR7 scope; exit-2 remedies in Errors.
## v4
- [intent-mismatch] FR-T1 base-agent run redefined as base-tests: the v3 wording put the agent's new test files into the base run, so every new agent test counted as pre-existing (validity n = 0). Evidence: test_score ScoreEntry failures in Test command run 2. Turn-cap counting, Container re-attach and relay_driver.run seam stated. No brief item changed.
## v3
- Contract-only: Formats F1–F18 fix data shapes, gh protocol, container contract, model output schemas, gate keys, guard verdict value, rust overlay/split rules; P2 restated to agree with C13; QR9 merge sha added to forbidden terms; garbled FR-T4 incompatible clause and agent_test_ids source fixed; classify takes run_tests outputs and gold_test_files; G4 restated without changing its threshold. Forced by both roles' challenges and the first Test command run (75 failures, coverage 61%).
## v2
- Contract-only: added docker_exec, testrun, run, score/crossarm/judge entry points, pilot module, task record and run layout signatures; data_dir location for tasks; contradiction flag in idle responses. Forced by missing interfaces test roles need; no brief item changed.
## v1
- Initial draft from handoff c379ec40307bd6c0 and the user's answers in this session.

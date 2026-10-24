import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from . import (
    brief, candidates_path, claude_call, data_dir, results_dir, docker_exec, gce, languages, mine, mutants, pilot, read_jsonl,
    recipes, report, run, tasks_path, validate, write_jsonl,
)

ROOT = Path(__file__).parent
REPO_ROOT = ROOT.parents[1]
PREREG = ROOT / "preregistration.md"
SUBCOMMANDS = (
    "mine", "build", "validate", "brief", "mutants", "run", "score", "judge", "report", "pilot", "doctor", "gce",
)
ENV_OVERRIDES = {
    "EVALUATION_DATA_DIR": "data_dir", "EVALUATION_RESULTS_DIR": "results_dir",
    "EVALUATION_TOKEN_FILE": "token_file",
}


class Deps:
    def __init__(self, docker=None, gh_fn=None, call_fn=None, run_fn=None):
        self.docker = docker if docker is not None else docker_exec
        self.gh_fn = gh_fn or _gh_fn
        self.call_fn = call_fn
        self.run_fn = run_fn or _run_fn


def load_config(path=ROOT / "config.json", env=None) -> dict:
    cfg = json.loads(Path(path).read_text())
    for var, key in ENV_OVERRIDES.items():
        value = (env if env is not None else os.environ).get(var)
        if value:
            cfg[key] = value
    return cfg


def _run_fn(argv, *, input=None, timeout=None):
    try:
        proc = subprocess.run(
            argv, input=input.encode() if input is not None else None, capture_output=True, timeout=timeout
        )
    except subprocess.TimeoutExpired:
        return 124, "", f"timed out after {timeout}s"
    except FileNotFoundError as exc:
        return 127, "", str(exc)
    return proc.returncode, proc.stdout.decode(errors="replace"), proc.stderr.decode(errors="replace")


def _gh_fn(args: list[str]):
    code, out, err = _run_fn(["gh", "api", *args], timeout=120)
    if code == 0:
        return json.loads(out) if out.strip() else None
    text = err + out
    if "rate limit" in text.lower() or "HTTP 403" in text or "HTTP 429" in text:
        _, reset, _ = _run_fn(["gh", "api", "rate_limit", "--jq", ".resources.core.reset"], timeout=60)
        raise mine.RateLimited(text.strip()[-300:], reset.strip())
    raise mine.GitHubError(text.strip()[-300:])


def _token(cfg: dict) -> str:
    path = Path(cfg.get("token_file", "")).expanduser()
    return path.read_text().strip() if path.is_file() else ""


def _call_fn(cfg: dict, deps: Deps):
    if deps.call_fn is not None:
        return deps.call_fn
    token = _token(cfg)
    if token and not os.environ.get("CLAUDE_CODE_OAUTH_TOKEN"):
        os.environ["CLAUDE_CODE_OAUTH_TOKEN"] = token
    return claude_call.claude_call


def _languages(value: str | None) -> list[str]:
    return list(languages.LANGUAGES) if value in (None, "all") else [value]


def _say(message: str) -> None:
    print(message, file=sys.stderr)


def _save(cfg: dict, language: str, rows: list[dict]) -> None:
    write_jsonl(tasks_path(cfg, language), rows)


def _cache_dir(cfg: dict) -> Path:
    return data_dir(cfg) / "cache"


def cmd_mine(args, cfg, deps) -> int:
    for language in _languages(args.language):
        try:
            rows = mine.search(language, cfg, gh_fn=deps.gh_fn)
        except mine.GitHubError as exc:
            reset = getattr(exc, "reset", "") or "unknown"
            _say(
                f"GitHub API failure or rate limit ({exc}); candidates so far are saved in "
                f"{candidates_path(cfg, language)}; rerun `python3 -m evaluation.reference_mutation mine --language {language}` "
                f"after the limit resets (reset epoch: {reset})"
            )
            return 3
        print(f"{language}: {len(rows)} candidates")
    return 0


def cmd_build(args, cfg, deps) -> int:
    for language in _languages(args.language):
        existing = {t["task_id"]: t for t in read_jsonl(tasks_path(cfg, language))}
        work, logs = data_dir(cfg) / "work", data_dir(cfg) / "logs" / "build"
        for cand in read_jsonl(candidates_path(cfg, language)):
            task_id = f"{cand['repo'].replace('/', '__')}-{cand['pr']}"
            if task_id in existing and not args.force:
                continue
            task = recipes.build_task(cand, docker=deps.docker, cfg=cfg, run_fn=deps.run_fn, work_dir=work, log_dir=logs)
            if task.get("image") and not task.get("build_error"):
                try:
                    recipes.build_agent_image(task, docker=deps.docker, cfg=cfg, work_dir=work, log_dir=logs)
                except recipes.RecipeError as exc:
                    task = {**task, "valid": False, "reason": f"build_error: {exc}", "build_error": str(exc)}
            existing[task_id] = task
            _save(cfg, language, sorted(existing.values(), key=lambda t: t["task_id"]))
            print(f"{task_id}: {task.get('reason') or 'built'}")
    return 0


def _update(cfg: dict, language: str, rows: list[dict], task: dict) -> None:
    _save(cfg, language, [task if r["task_id"] == task["task_id"] else r for r in rows])


def cmd_validate(args, cfg, deps) -> int:
    for language in _languages(args.language):
        rows = read_jsonl(tasks_path(cfg, language))
        for task in rows:
            if task.get("build_error") or (task.get("valid") is not None and not args.force):
                continue
            verdict = validate.validate_task(task, docker=deps.docker, cfg=cfg, cache_dir=_cache_dir(cfg))
            task = {**task, **{k: verdict[k] for k in ("valid", "reason", "f2p", "p2p", "p2p_note")}}
            _update(cfg, language, rows, task)
            rows = [task if r["task_id"] == task["task_id"] else r for r in rows]
            print(f"{task['task_id']}: {task['reason']}")
    return 0


def cmd_brief(args, cfg, deps) -> int:
    call_fn = _call_fn(cfg, deps)
    for language in _languages(args.language):
        rows = read_jsonl(tasks_path(cfg, language))
        for task in rows:
            if not task.get("valid") or (task.get("brief") and not args.force):
                continue
            task = {**task, "brief": brief.make_brief(task, call_fn=call_fn, cfg=cfg)}
            rows = [task if r["task_id"] == task["task_id"] else r for r in rows]
            _save(cfg, language, rows)
            print(f"{task['task_id']}: {task['brief']['status']} {task['brief']['reason']}")
    return 0


def cmd_mutants(args, cfg, deps) -> int:
    for language in _languages(args.language):
        rows = read_jsonl(tasks_path(cfg, language))
        for task in rows:
            ready = task.get("valid") and (task.get("brief") or {}).get("status") == "ok"
            if not ready or (task.get("mutants") and not args.force):
                continue
            task = {**task, "mutants": mutants.build_mutants(
                task, docker=deps.docker, cfg=cfg, cache_dir=_cache_dir(cfg))}
            rows = [task if r["task_id"] == task["task_id"] else r for r in rows]
            _save(cfg, language, rows)
            print(f"{task['task_id']}: {len(task['mutants'])} mutants")
    return 0


def _load_all(cfg: dict) -> dict[str, dict]:
    return run.load_tasks(cfg)


def _halted(exc: run.Halted) -> int:
    _say(f"halted ({exc.reason}); finished entries are kept; continue with "
         f"`python3 -m evaluation.reference_mutation run --resume {exc.run_dir.name}`")
    return 3


def cmd_run(args, cfg, deps) -> int:
    call_fn = _call_fn(cfg, deps)
    if args.resume:
        run.resume(args.resume, cfg=cfg, docker=deps.docker, call_fn=call_fn)
        return 0
    if args.retry_errors:
        run.retry_errors(args.retry_errors, cfg=cfg, docker=deps.docker, call_fn=call_fn)
        return 0
    tasks = [t for t in _load_all(cfg).values() if t.get("valid") and (t.get("brief") or {}).get("status") == "ok"]
    if args.language:
        tasks = [t for t in tasks if t["language"] == args.language]
    if args.tasks:
        wanted = set(args.tasks.split(","))
        tasks = [t for t in tasks if t["task_id"] in wanted]
    if not tasks:
        language = args.language or "<language>"
        _say(f"no valid tasks for run; run `python3 -m evaluation.reference_mutation validate --language {language}` and "
             f"`python3 -m evaluation.reference_mutation brief --language {language}`, or relax --language/--tasks")
        return 2
    run_dir = run.run(
        sorted(tasks, key=lambda t: t["task_id"]), args.arms.split(","), cfg=cfg, phase=args.phase,
        repeats=args.repeats, docker=deps.docker, call_fn=call_fn, prereg_path=PREREG, harness_ref=args.harness_ref,
    )
    print(run_dir.name)
    return 0


def _run_dir(cfg: dict, run_id: str) -> Path:
    path = data_dir(cfg) / "runs" / run_id
    if not (path / "run.json").is_file():
        raise run.Refused(f"unknown run id: {run_id}; list runs under {data_dir(cfg) / 'runs'}/")
    return path


def _run_tasks(cfg: dict, run_dir: Path) -> dict[str, dict]:
    snapshot = run_dir / "tasks.jsonl"
    if not snapshot.is_file():
        raise run.Refused(f"tasks snapshot missing: {snapshot}; restore it from the run's original host")
    return {t["task_id"]: t for t in read_jsonl(snapshot)}


def cmd_score(args, cfg, deps) -> int:
    run_dir = _run_dir(cfg, args.run_id)
    scores = pilot.score_all(run_dir, _run_tasks(cfg, run_dir), docker=deps.docker, cfg=cfg, cache_dir=_cache_dir(cfg))
    print(f"scored {sum(1 for s in scores if s.get('scored'))} of {len(scores)} entries")
    return 0


def cmd_judge(args, cfg, deps) -> int:
    run_dir = _run_dir(cfg, args.run_id)
    pilot.judge_all(run_dir, _run_tasks(cfg, run_dir), call_fn=_call_fn(cfg, deps), cfg=cfg)
    return 0


def cmd_report(args, cfg, deps) -> int:
    run_dir = _run_dir(cfg, args.run_id)
    token = _token(cfg)
    holder = report.locate_token(run_dir, token) if token else None
    if holder:
        raise report.TokenInReport(f"OAuth token found in {holder}; scrub that file; nothing written", token)
    built = report.build(run_dir, prereg_path=PREREG, cfg=cfg)
    _, md_path = report.write(built, results_dir(cfg), token=_token(cfg))
    print(md_path)
    return 0


def cmd_pilot(args, cfg, deps) -> int:
    call_fn = _call_fn(cfg, deps)
    _, _, md_path = pilot.run_pilot(
        cfg, docker=deps.docker, call_fn=call_fn, prereg_path=PREREG, token=_token(cfg),
        harness_ref=args.harness_ref, languages=_languages(args.language),
    )
    print(md_path)
    return 0


def doctor(cfg: dict, *, run_fn) -> list[str]:
    problems = []
    code, out, _ = run_fn(["docker", "version", "--format", "{{.Server.Version}}"], timeout=60)
    if code != 0:
        problems.append("docker: daemon unreachable; start Docker (VM: `sudo systemctl start docker`)")
    else:
        print(f"docker server: {out.strip()}")
    code, out, _ = run_fn(["claude", "--version"], timeout=60)
    if code != 0:
        problems.append("claude CLI: not found; install with `npm install -g @anthropic-ai/claude-code`")
    else:
        print(f"claude CLI: {out.strip()}")
    token = Path(cfg.get("token_file", "")).expanduser()
    if not token.is_file():
        problems.append(f"token file: missing at {token}; save the OAuth token there and `chmod 600` it")
    elif token.stat().st_mode & 0o777 != 0o600:
        problems.append(f"token file: mode {oct(token.stat().st_mode & 0o777)} at {token}; run `chmod 600 {token}`")
    else:
        print(f"token file: present, mode 600 ({token})")
    target = data_dir(cfg)
    probe = target if target.exists() else target.parent
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    free_gb = shutil.disk_usage(probe).free / 1e9
    print(f"data dir {target}: {free_gb:.1f} GB free")
    if free_gb < 20:
        problems.append(f"disk: only {free_gb:.1f} GB free under {target}; free space or set EVALUATION_DATA_DIR")
    code, _, _ = run_fn(["gh", "auth", "status"], timeout=60)
    print(f"gh auth: {'logged in' if code == 0 else 'not logged in; run `gh auth login`'} (needed only for mine)")
    return problems


def cmd_doctor(args, cfg, deps) -> int:
    problems = doctor(cfg, run_fn=deps.run_fn)
    for line in problems:
        _say(line)
    return 2 if problems else 0


def cmd_gce(args, cfg, deps) -> int:
    action = args.gce_command
    if action == "up":
        return gce.up(cfg, run_fn=deps.run_fn)
    if action == "down":
        return gce.down(cfg, run_fn=deps.run_fn, purge=args.purge, yes=args.yes)
    if action == "push":
        return gce.push(cfg, run_fn=deps.run_fn)
    if action == "exec":
        command = args.remote_argv[1:] if args.remote_argv[:1] == ["--"] else args.remote_argv
        if not command:
            _say("gce exec needs a command; usage: python3 -m evaluation.reference_mutation gce exec -- python3 -m evaluation.reference_mutation doctor")
            return 2
        return gce.exec_remote(cfg, command, run_fn=deps.run_fn, detach=args.detach)
    if action == "pull":
        return gce.pull(cfg, args.run_id, run_fn=deps.run_fn)
    return gce.status(cfg, run_fn=deps.run_fn)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python3 -m evaluation.reference_mutation")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("mine", "build", "validate", "brief", "mutants"):
        p = sub.add_parser(name, help=f"{name} stage")
        p.add_argument("--language", choices=[*languages.LANGUAGES, "all"], default="all")
        p.add_argument("--force", action="store_true")
    p = sub.add_parser("run", help="run agent arms")
    p.add_argument("--phase", choices=("pilot", "main", "dev"), default="dev")
    p.add_argument("--arms", default=",".join(("B0", "Bplus", "H")))
    p.add_argument("--repeats", type=int, default=1)
    p.add_argument("--language", choices=languages.LANGUAGES)
    p.add_argument("--tasks")
    p.add_argument("--resume")
    p.add_argument("--retry-errors", metavar="RUN_ID")
    p.add_argument("--harness-ref", default="HEAD")
    for name in ("score", "judge", "report"):
        sub.add_parser(name, help=f"{name} a run").add_argument("run_id")
    p = sub.add_parser("pilot", help="pilot pipeline")
    p.add_argument("--language", choices=[*languages.LANGUAGES, "all"], default="all")
    p.add_argument("--harness-ref", default="HEAD")
    sub.add_parser("doctor", help="check the environment")
    g = sub.add_parser("gce", help="GCE VM management").add_subparsers(dest="gce_command", required=True)
    g.add_parser("up")
    d = g.add_parser("down")
    d.add_argument("--purge", action="store_true")
    d.add_argument("--yes", action="store_true")
    g.add_parser("push")
    e = g.add_parser("exec")
    e.add_argument("--detach", action="store_true")
    e.add_argument("remote_argv", nargs=argparse.REMAINDER)
    pl = g.add_parser("pull")
    pl.add_argument("run_id")
    g.add_parser("status")
    return parser


HANDLERS = {
    "mine": cmd_mine, "build": cmd_build, "validate": cmd_validate, "brief": cmd_brief, "mutants": cmd_mutants,
    "run": cmd_run, "score": cmd_score, "judge": cmd_judge, "report": cmd_report, "pilot": cmd_pilot,
    "doctor": cmd_doctor, "gce": cmd_gce,
}


def main(argv: list[str] | None = None, cfg: dict | None = None, deps: dict | None = None) -> int:
    args = build_parser().parse_args(argv)
    cfg = dict(cfg) if cfg is not None else load_config()
    for var, key in ENV_OVERRIDES.items():
        if os.environ.get(var):
            cfg[key] = os.environ[var]
    deps = deps if isinstance(deps, Deps) else Deps(**(deps or {}))
    refused = (run.Refused, report.PreregMismatch, report.RunIncomplete, recipes.RecipeError)
    try:
        return HANDLERS[args.command](args, cfg, deps)
    except run.Halted as exc:
        return _halted(exc)
    except report.TokenInReport as exc:
        _say(str(exc))
        return 2
    except refused as exc:
        _say(str(exc))
        return 2
    except KeyboardInterrupt:
        _say("interrupted; rerun the same command, or `python3 -m evaluation.reference_mutation run --resume <run_id>` for a run")
        return 3


if __name__ == "__main__":
    sys.exit(main())

import hashlib
import json
import os
import secrets
import shutil
import subprocess
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import (
    REDACTED, atomic_write, compose, data_dir, languages, read_json, read_jsonl, recipes, section, session_cost,
    usersim, write_json, write_jsonl,
)

ROOT = Path(__file__).parent
REPO_ROOT = ROOT.parents[1]
SQUID_CONF = ROOT / "docker" / "squid.conf"
TOKEN_MOUNT = "/run/secrets/oauth_token"
TOKEN_SOURCE = "/run/host-secrets/oauth_token"
OUT_DIR = "/evaluation/out"
IN_DIR = "/evaluation/in"
DRIVER_DIR = "/opt/evaluation/agent"
DRIVER_ARGV = ["/opt/evaluation-py/venv/bin/python", f"{DRIVER_DIR}/relay_driver.py", f"{IN_DIR}/input.json"]
RELAY_POLL_S = 1
RELAY_TIMEOUT_MARGIN_S = 60
TARGETS_FILE = "/tmp/harness-targets.json"
PREFERENCES_FILE = "/tmp/harness-preferences.json"
PREFERENCES_JSON = json.dumps({"repositories": {"/testbed": {"verification_tools_prompt": "never"}}})
INSTALL_CMD = (
    f"printf 'y\\ny\\ny\\n' | HARNESS_TARGETS_FILE={TARGETS_FILE} HARNESS_PREFERENCES_FILE={PREFERENCES_FILE} "
    "/opt/evaluation-py/venv/bin/python /opt/harness-src/installer/harness.py install /testbed --no-ci"
)
COMMIT_CMD = (
    "git add -A && git -c core.hooksPath=/dev/null -c user.name=evaluation "
    '-c user.email=evaluation@localhost commit -q -m "evaluation: install harness"'
)
DIFF_ARGV = [
    "git", "-c", "core.quotePath=true", "diff", "--cached", "--binary", "--no-color",
    "--no-ext-diff", "--no-textconv", "--no-renames", "--src-prefix=a/", "--dst-prefix=b/",
]
TOKEN_REMAINED = "token remained after scrub"
FINISHED = ("completed", "stalled", "capped", "error")


class Halted(RuntimeError):
    def __init__(self, run_dir, reason: str):
        super().__init__(f"halted: {reason}")
        self.run_dir = Path(run_dir)
        self.reason = reason


class Refused(RuntimeError):
    pass


def token_path(cfg: dict) -> Path:
    path = Path(cfg.get("token_file") or section(cfg, "agent").get("token_file", "")).expanduser()
    if not path.is_file():
        raise Refused(
            f"token file missing: {path}; save the subscription OAuth token there (chmod 600) "
            "or set token_file in evaluation/reference_mutation/config.json"
        )
    return path


def render_squid_conf(agent: dict) -> str:
    return SQUID_CONF.read_text().replace("{{ALLOW_HOSTS}}", " ".join(agent["allow_hosts"]))


def proxy_url(agent: dict) -> str:
    return f"http://{agent['proxy_name']}:3128"


def ensure_egress(agent: dict, *, docker) -> None:
    docker.ensure_network(agent["network"], internal=True)
    conf = render_squid_conf(agent)
    if docker.container_exists(agent["proxy_name"]):
        docker.remove_container(agent["proxy_name"])
    docker.start_proxy(
        agent["proxy_image"], name=agent["proxy_name"], networks=["bridge", agent["network"]],
        labels={"evaluation.proxy": hashlib.sha256(conf.encode()).hexdigest()}, conf_text=conf,
    )


def scrub(directory, token) -> int:
    needle = token if isinstance(token, bytes) else token.encode()
    if not needle:
        return 0
    total = 0
    for root, _, files in os.walk(directory):
        for name in files:
            path = Path(root) / name
            if path.is_symlink() or not path.is_file():
                continue
            data = path.read_bytes()
            count = data.count(needle)
            if count:
                atomic_write(path, data.replace(needle, REDACTED.encode()))
                total += count
    return total


def count_token(directory, token: str) -> int:
    needle = token.encode()
    if not needle:
        return 0
    return sum(
        (Path(root) / name).read_bytes().count(needle)
        for root, _, files in os.walk(directory) for name in files
        if (Path(root) / name).is_file() and not (Path(root) / name).is_symlink()
    )


def _mkdir_shared(path: Path) -> None:
    missing, cur = [], path
    while not cur.exists():
        missing.append(cur)
        cur = cur.parent
    for p in reversed(missing):
        p.mkdir(mode=0o755)
        p.chmod(0o755)


def _git(*args: str) -> str:
    proc = subprocess.run(["git", "-C", str(REPO_ROOT), *args], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if proc.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {proc.stderr.decode(errors='replace').strip()}")
    return proc.stdout.decode().strip()


def _git_archive(commit: str) -> bytes:
    proc = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "archive", "--format=tar", commit, "harness", "installer"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.decode(errors="replace"))
    return proc.stdout


def prereg_sha(path) -> str | None:
    path = Path(path) if path else None
    return hashlib.sha256(path.read_bytes()).hexdigest() if path and path.is_file() else None


def load_tasks(cfg: dict) -> dict[str, dict]:
    out = {}
    for path in sorted((data_dir(cfg) / "tasks").glob("*/tasks.jsonl")):
        for row in read_jsonl(path):
            out[row["task_id"]] = row
    return out


def entry_dir(run_dir, entry: dict) -> Path:
    return Path(run_dir) / entry["task_id"] / f"{entry['arm']}-r{entry['repeat']}"


def halt_reason(state: dict | None) -> str | None:
    if not state:
        return None
    if state.get("status") == "interrupted":
        return "interrupted"
    limit = state.get("rate_limit")
    # "allowed_warning" only reports high usage of the window; requests still succeed.
    if isinstance(limit, dict) and limit.get("status") not in (None, "allowed", "allowed_warning"):
        return f"rate_limit:{limit['status']}"
    return None


class _Ctx:
    def __init__(self, cfg, docker, call_fn, run_id, run_dir, token_file, token, meta, tasks):
        self.cfg, self.agent = cfg, section(cfg, "agent")
        self.docker, self.call_fn = docker, call_fn
        self.run_id, self.run_dir = run_id, Path(run_dir)
        self.token_file, self.token = token_file, token
        self.meta, self.tasks = meta, tasks
        self.lock = threading.Lock()
        self.halt = threading.Event()
        self.inflight: dict[int, object] = {}

    def save(self) -> None:
        with self.lock:
            write_json(self.run_dir / "run.json", self.meta, indent=1)

    def set_status(self, entry: dict, status: str) -> None:
        with self.lock:
            entry["status"] = status
            write_json(self.run_dir / "run.json", self.meta, indent=1)


def config_hash(agent: dict) -> str:
    keys = ("model", "effort", "wall_clock_min", "max_user_turns", "disallowed_tools", "cpus", "memory",
            "allow_hosts", "idle_grace_s", "host_grace_s")
    return hashlib.sha256(json.dumps({k: agent.get(k) for k in keys}, sort_keys=True).encode()).hexdigest()


def _driver_input(ctx: _Ctx, prompt: str, resume_info) -> dict:
    a, u = ctx.agent, section(ctx.cfg, "usersim")
    return {
        "run_id": ctx.run_id, "arm": None, "prompt": prompt, "model": a["model"], "effort": a["effort"],
        "aliases": a["aliases"], "disallowed_tools": a["disallowed_tools"],
        "wall_clock_s": 60 * a["wall_clock_min"], "max_user_turns": a["max_user_turns"],
        "idle_grace_s": a["idle_grace_s"], "out_dir": OUT_DIR, "token_path": TOKEN_MOUNT,
        "proxy_url": proxy_url(a), "resume": resume_info, "relay_dir": usersim.RELAY_DIR,
        "relay_timeout_s": u.get("timeout_s", 900) + RELAY_TIMEOUT_MARGIN_S, "relay_poll_s": RELAY_POLL_S,
    }


def _stage_driver(container) -> None:
    with tempfile.TemporaryDirectory() as td:
        stage = Path(td) / "agent"
        stage.mkdir()
        for name in ("driver.py", "relay_driver.py"):
            (stage / name).write_bytes((ROOT / "agent" / name).read_bytes())
        # agent.Dockerfile creates DRIVER_DIR, and `docker cp DIR existing-dir` nests DIR inside it; "/." copies
        # the contents instead.
        container.copy_in(f"{stage}/.", DRIVER_DIR)


def _step(container, log: list[str], argv, *, user="nonroot", timeout=900):
    code, out, _ = container.exec(argv, timeout=timeout, user=user, workdir="/testbed")
    log.append(f"$ {' '.join(argv)}\n{out}\n")
    return code, out


def _install_harness(ctx: _Ctx, container, log: list[str]):
    try:
        blob = _git_archive(ctx.meta["params"]["harness_commit"])
    except RuntimeError as exc:
        log.append(f"git archive\n{exc}\n")
        return "install failed: git archive", None
    with tempfile.TemporaryDirectory() as td:
        tar = Path(td) / "harness-src.tar"
        tar.write_bytes(blob)
        container.copy_in(tar, "/opt/harness-src.tar")
    code, _ = _step(container, log, [
        "sh", "-c", "mkdir -p /opt/harness-src && tar -xf /opt/harness-src.tar -C /opt/harness-src "
        "&& rm /opt/harness-src.tar"], user="root")
    if code != 0:
        return f"install failed: exit {code}", None
    code, _ = _step(container, log, ["sh", "-c", f"printf %s '{PREFERENCES_JSON}' > {PREFERENCES_FILE}"])
    if code != 0:
        return f"install failed: exit {code}", None
    code, _ = _step(container, log, ["sh", "-c", INSTALL_CMD])
    if code != 0:
        return f"install failed: exit {code}", None
    code, _ = _step(container, log, ["sh", "-c", COMMIT_CMD])
    if code != 0:
        return f"install failed: exit {code}", None
    _step(container, log, ["rm", "-rf", "/opt/harness-src"], user="root")
    return None, True


def _collect(container, language: str, start_commit: str) -> tuple[str, dict]:
    def agent(argv):
        return container.exec(argv, user="nonroot", workdir="/testbed")

    agent(["sh", "-c", "kill -9 -1"])
    code, out, _ = agent(["git", "add", "-A"])
    if code != 0:
        raise RuntimeError(f"git add failed: {out.strip()}")
    code, diff, _ = agent([*DIFF_ARGV, start_commit])
    if code != 0:
        raise RuntimeError(f"git diff failed: {diff.strip()}")
    base, after = {}, {}
    for sec in languages.parse_diff(diff):
        path = sec.path
        if languages.classify_path(language, path) == "harness":
            continue
        created = sec.old == "/dev/null" or any(h.startswith("new file mode") for h in sec.header)
        deleted = sec.new == "/dev/null" or any(h.startswith("deleted file mode") for h in sec.header)
        base[path] = None if created else agent(["git", "show", f"{start_commit}:{path}"])[1]
        if deleted:
            after[path] = None
            continue
        blob = container.read_bytes(f"/testbed/{path}")
        try:
            after[path] = blob.decode() if blob is not None else None
        except UnicodeDecodeError:
            base.pop(path, None)
    return diff, {"split": languages.split_diff(language, diff), "base": base, "after": after}


def _finalize(ctx: _Ctx, d: Path, state: dict, host: dict) -> str:
    count = scrub(d, ctx.token)

    def write(final: dict, base_count: int) -> None:
        text = json.dumps({**final, **host}, indent=1)
        found = text.count(ctx.token) if ctx.token else 0
        host["scrubbed_occurrences"] = base_count + found
        text = json.dumps({**final, **host}, indent=1)
        atomic_write(d / "state.json", text.replace(ctx.token, REDACTED) if ctx.token else text)

    write(state, count)
    if count_token(d, ctx.token):
        state = {**state, "status": "error", "reason": TOKEN_REMAINED}
        host["error"] = TOKEN_REMAINED
        write(state, count)
    return state["status"]


def _missing_image_message(name: str, task: dict) -> str:
    return f"image missing: {name}; run python3 -m evaluation.reference_mutation build --language {task['language']}"


def _run_entry(ctx: _Ctx, n: int, entry: dict, resume_state) -> str:
    docker, agent = ctx.docker, ctx.agent
    task = ctx.tasks[entry["task_id"]]
    d = entry_dir(ctx.run_dir, entry)
    d.mkdir(parents=True, exist_ok=True)
    name = f"evaluation-agent-{ctx.run_id}-{n}"
    host = {"container": name, "host_timeout": False, "scrubbed_occurrences": 0, "error": None}

    def fail(reason: str, base: dict | None = None) -> str:
        state = dict(base or {})
        state.update(status="error", reason=reason)
        host["error"] = reason
        return _finalize(ctx, d, state, host)

    image = recipes.agent_image_name(task["image"])
    resume_info = None
    if resume_state is not None and resume_state.get("session_id") and docker.container_exists(name):
        container = docker.Container(name)
        container.start()
        resume_info = {
            "session_id": resume_state["session_id"], "phrases_sent": resume_state.get("phrases_sent", 0),
            "elapsed_s": resume_state.get("elapsed_s") or 0,
        }
    else:
        try:
            docker.image_id(image)
        except docker.ImageMissing:
            host["container"] = None
            return fail(_missing_image_message(image, task))
        if docker.container_exists(name):
            docker.remove_container(name)
        container = docker.start_container(
            image, name=name, network=agent["network"], labels={"evaluation.agent": ctx.run_id},
            cpus=agent["cpus"], memory=agent["memory"],
            mounts=[f"type=bind,src={ctx.token_file},dst={TOKEN_SOURCE},readonly",
                    f"type=tmpfs,dst={Path(TOKEN_MOUNT).parent}"],
        )
    with ctx.lock:
        ctx.inflight[n] = container
    try:
        return _drive(ctx, container, n, entry, task, d, host, fail, resume_info, image)
    except BaseException:
        container.remove()
        raise
    finally:
        with ctx.lock:
            ctx.inflight.pop(n, None)


def _drive(ctx, container, n, entry, task, d, host, fail, resume_info, image) -> str:
    docker, cfg, agent = ctx.docker, ctx.cfg, ctx.agent
    arm = entry["arm"]
    raw = d / "raw"
    install_log: list[str] = []
    # The host file is 0600 for the run user, whose uid is not the image's nonroot uid; the nonroot-readable copy
    # lives on tmpfs, so it never reaches the container's disk layer, and is redone on resume because tmpfs
    # does not survive a container restart.
    code, out, _ = container.exec(
        ["install", "-o", "nonroot", "-g", "nonroot", "-m", "0400", TOKEN_SOURCE, TOKEN_MOUNT], user="root")
    if code != 0:
        container.remove()
        return fail(f"token staging failed: {out.strip()}")
    prior = read_json(d / "manifest.json") if resume_info else None
    if resume_info is not None and prior:
        start_commit = prior["start_commit"]
    else:
        _stage_driver(container)
        container.exec(["sh", "-c", f"mkdir -p {IN_DIR} {OUT_DIR} {usersim.RELAY_DIR} && "
                        f"chown nonroot:nonroot {OUT_DIR} {usersim.RELAY_DIR}"], user="root")
        if arm == "H":
            reason, _ = _install_harness(ctx, container, install_log)
            if reason:
                raw.mkdir(parents=True, exist_ok=True)
                atomic_write(raw / "install.log", "".join(install_log))
                container.remove()
                return fail(reason)
        code, out, _ = container.exec(["git", "rev-parse", "HEAD"], user="nonroot", workdir="/testbed")
        if code != 0:
            container.remove()
            return fail(f"git failed: {out.strip()}")
        start_commit = out.strip().splitlines()[-1]
    prompt = compose.compose_prompt(task["brief"], arm)
    inp = {**_driver_input(ctx, prompt, resume_info), "arm": arm}
    container.write_text(f"{IN_DIR}/input.json", json.dumps(inp))
    elapsed = resume_info["elapsed_s"] if resume_info else 0
    timeout = inp["wall_clock_s"] - elapsed + agent["host_grace_s"]
    (d / "usersim.jsonl").touch()
    relay = usersim.Relay(container, task, d / "usersim.jsonl", call_fn=ctx.call_fn, cfg=cfg, token=ctx.token)
    relay.start()
    try:
        code, out, timed_out = container.exec(DRIVER_ARGV, timeout=timeout, user="nonroot", workdir="/testbed")
    finally:
        relay.stop()
    blob = container.read_bytes(f"{OUT_DIR}/state.json")
    try:
        driver_state = json.loads(blob) if blob else None
    except ValueError:
        driver_state = None
    error = None
    if timed_out:
        host["host_timeout"] = True
        driver_state = {**(driver_state or {}), "status": "capped", "reason": "wall_clock"}
    elif code != 0:
        error = f"driver exit {code}"
    elif driver_state is None:
        error = "driver state missing"
    if error:
        driver_state = {**(driver_state or {}), "status": "error", "reason": error}
        host["error"] = error
    if driver_state["status"] != "interrupted" and not error and halt_reason(driver_state):
        driver_state.update(status="interrupted", reason=halt_reason(driver_state))
    status = driver_state["status"]
    diff = split = None
    if status != "interrupted" and not error:
        try:
            diff, split = _collect(container, task["language"], start_commit)
        except RuntimeError as exc:
            error = str(exc)
            driver_state.update(status="error", reason=error)
            host["error"] = error
    container.copy_out(f"{OUT_DIR}/.", raw)
    raw.mkdir(parents=True, exist_ok=True)
    if install_log:
        atomic_write(raw / "install.log", "".join(install_log))
    if error or timed_out:
        atomic_write(raw / "driver.log", out)
    if diff is not None:
        atomic_write(d / "full.diff", diff)
        write_json(d / "split.json", split)
    results = driver_state.get("results") or []
    driver_state.update(
        cost_usd=session_cost(results),
        duration_s=driver_state.get("elapsed_s") or (sum(r.get("duration_ms") or 0 for r in results) / 1000 if results else None),
        turns=sum(r.get("num_turns") or 0 for r in results),
    )
    write_json(d / "manifest.json", {
        "run_id": ctx.run_id, "task_id": task["task_id"], "arm": arm, "repeat": entry["repeat"],
        "model": agent["model"], "effort": agent["effort"],
        "image_ids": {"agent": docker.image_id(image), "project": docker.image_id(task["image"])},
        "harness_commit": ctx.meta["params"]["harness_commit"] if arm == "H" else None,
        "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(), "config_hash": config_hash(agent),
        "prereg_sha256": ctx.meta.get("prereg_sha256"), "start_commit": start_commit,
        "attempts": entry.get("attempts", 1),
    }, indent=1, sort_keys=True)
    final = _finalize(ctx, d, driver_state, host)
    if final == "interrupted":
        container.stop()
    else:
        container.remove()
    return final


def _stamp_attempts(ctx: _Ctx, entry: dict) -> None:
    path = entry_dir(ctx.run_dir, entry) / "manifest.json"
    manifest = read_json(path) or {
        "run_id": ctx.run_id, "task_id": entry["task_id"], "arm": entry["arm"], "repeat": entry["repeat"],
    }
    write_json(path, {**manifest, "attempts": entry.get("attempts", 1)}, indent=1, sort_keys=True)


def _execute(ctx: _Ctx, pending: list[tuple[int, dict, dict | None]]) -> None:
    def work(item):
        n, entry, state = item
        if ctx.halt.is_set():
            return
        try:
            status = _run_entry(ctx, n, entry, state)
        except Exception as exc:
            if isinstance(exc, getattr(ctx.docker, "DockerUnreachable", ())):
                status = "interrupted"
                write_json(entry_dir(ctx.run_dir, entry) / "state.json",
                           {"status": "interrupted", "reason": f"docker_unreachable: {exc}"})
            else:
                status = "error"
                write_json(entry_dir(ctx.run_dir, entry) / "state.json",
                           {"status": "error", "reason": f"{type(exc).__name__}: {exc}"[:500]})
        _stamp_attempts(ctx, entry)
        ctx.set_status(entry, status)
        reason = halt_reason(read_json(entry_dir(ctx.run_dir, entry) / "state.json"))
        if reason and not ctx.halt.is_set():
            with ctx.lock:
                ctx.meta["halted"] = {"reason": reason, "task_id": entry["task_id"], "arm": entry["arm"]}
            ctx.halt.set()
            ctx.save()

    pool = ThreadPoolExecutor(max_workers=max(1, ctx.agent.get("concurrency", 3)))
    try:
        futures = [pool.submit(work, item) for item in pending]
        for f in futures:
            f.result()
    except KeyboardInterrupt:
        ctx.halt.set()
        pool.shutdown(wait=False, cancel_futures=True)
        with ctx.lock:
            running = list(ctx.inflight.values())
            ctx.meta["halted"] = {"reason": "keyboard_interrupt"}
        for container in running:
            try:
                container.stop()
            except Exception:
                pass
        for _, entry, _ in pending:
            if entry["status"] == "pending" and entry_dir(ctx.run_dir, entry).is_dir():
                entry["status"] = "interrupted"
        ctx.save()
        raise Halted(ctx.run_dir, "keyboard_interrupt")
    finally:
        pool.shutdown(wait=True)
    if ctx.halt.is_set():
        raise Halted(ctx.run_dir, ctx.meta["halted"]["reason"])


def run(
    tasks: list[dict], arms: list[str], *, cfg: dict, phase: str, repeats: int, docker, call_fn,
    prereg_path, now=time.time, harness_ref: str = "HEAD",
) -> Path:
    if phase not in ("pilot", "main", "dev"):
        raise Refused(f"unknown phase: {phase}; use --phase pilot, main or dev")
    unknown = [a for a in arms if a not in compose.ARMS]
    if unknown:
        raise Refused(f"unknown arms: {', '.join(unknown)}; choose from {', '.join(compose.ARMS)}")
    token_file = token_path(cfg)
    token = token_file.read_text().strip()
    agent = section(cfg, "agent")
    pilot_language = None
    if phase == "main":
        pilot_language = next((t["language"] for t in tasks if t.get("pilot")), None)
        tasks = [t for t in tasks if not t.get("pilot")]
        pilot_language = pilot_language if not tasks else None
        if not prereg_path or not Path(prereg_path).is_file():
            raise Refused(f"preregistration missing: {prereg_path}; restore evaluation/reference_mutation/preregistration.md")
    if not tasks:
        language = pilot_language or "<language>"
        if pilot_language:
            raise Refused(
                "pilot tasks are excluded from main runs and none remain; add tasks with "
                f"python3 -m evaluation.reference_mutation mine --language {language}"
            )
        raise Refused(
            "no valid tasks to run; run python3 -m evaluation.reference_mutation validate --language "
            f"{language} and python3 -m evaluation.reference_mutation brief --language {language}"
        )
    for task in tasks:
        for name in (task["image"], recipes.agent_image_name(task["image"])):
            try:
                docker.image_id(name)
            except docker.ImageMissing:
                raise Refused(_missing_image_message(name, task)) from None
    params = {
        "harness_ref": harness_ref, "harness_commit": _git("rev-parse", harness_ref) if "H" in arms else None,
        "model": agent["model"], "effort": agent["effort"], "cap_min": agent["wall_clock_min"],
    }
    ensure_egress(agent, docker=docker)
    run_id = secrets.token_hex(8)
    run_dir = data_dir(cfg) / "runs" / run_id
    _mkdir_shared(run_dir)
    entries = [
        {"task_id": t["task_id"], "arm": arm, "repeat": k, "status": "pending", "attempts": 1}
        for t in tasks for k in range(1, repeats + 1)
        for arm in arms if arm in t.get("pilot_arms", arms)
    ]
    meta = {
        "run_id": run_id, "phase": phase, "prereg_sha256": prereg_sha(prereg_path),
        "prereg_path": str(prereg_path) if prereg_path else None, "created_at": now(), "params": params,
        "repeats": repeats, "arms": list(arms), "entries": entries, "halted": None,
    }
    ctx = _Ctx(cfg, docker, call_fn, run_id, run_dir, token_file, token, meta, {t["task_id"]: t for t in tasks})
    write_jsonl(run_dir / "tasks.jsonl", tasks)
    ctx.save()
    _execute(ctx, [(n, e, None) for n, e in enumerate(entries, start=1)])
    return run_dir


def resume(run_id: str, *, cfg: dict, docker, call_fn) -> Path:
    run_dir = data_dir(cfg) / "runs" / run_id
    meta = read_json(run_dir / "run.json")
    if meta is None:
        raise Refused(f"unknown run id: {run_id}; list runs under {data_dir(cfg) / 'runs'}/")
    token_file = token_path(cfg)
    token = token_file.read_text().strip()
    snapshot = run_dir / "tasks.jsonl"
    if not snapshot.is_file():
        raise Refused(f"tasks snapshot missing: {snapshot}; restore it from the run's original host or start a new run")
    known = {t["task_id"]: t for t in read_jsonl(snapshot)}
    ensure_egress(section(cfg, "agent"), docker=docker)
    meta["halted"] = None
    ctx = _Ctx(cfg, docker, call_fn, run_id, run_dir, token_file, token, meta,
               {e["task_id"]: known[e["task_id"]] for e in meta["entries"]})
    ctx.save()
    pending = []
    for n, entry in enumerate(meta["entries"], start=1):
        state = read_json(entry_dir(run_dir, entry) / "state.json")
        if entry["status"] in FINISHED or (state is not None and state.get("status") in FINISHED):
            continue
        pending.append((n, entry, state if state and state.get("status") == "interrupted" else None))
    _execute(ctx, pending)
    return run_dir


def retry_errors(run_id: str, *, cfg: dict, docker, call_fn) -> Path:
    run_dir = data_dir(cfg) / "runs" / run_id
    meta = read_json(run_dir / "run.json")
    if meta is None:
        raise Refused(f"unknown run id: {run_id}; list runs under {data_dir(cfg) / 'runs'}/")
    token_file = token_path(cfg)
    token = token_file.read_text().strip()
    snapshot = run_dir / "tasks.jsonl"
    if not snapshot.is_file():
        raise Refused(f"tasks snapshot missing: {snapshot}; restore it from the run's original host or start a new run")
    known = {t["task_id"]: t for t in read_jsonl(snapshot)}
    ensure_egress(section(cfg, "agent"), docker=docker)
    meta["halted"] = None
    ctx = _Ctx(cfg, docker, call_fn, run_id, run_dir, token_file, token, meta, known)
    pending = []
    for n, entry in enumerate(meta["entries"], start=1):
        if entry["status"] == "error" and entry.get("attempts", 1) == 1:
            entry["attempts"] = 2
            entry["status"] = "pending"
            shutil.rmtree(entry_dir(run_dir, entry), ignore_errors=True)
            pending.append((n, entry, None))
    ctx.save()
    _execute(ctx, pending)
    return run_dir

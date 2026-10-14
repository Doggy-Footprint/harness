import hashlib
import json
import os
import secrets
import subprocess
import tempfile
import time
from pathlib import Path

from . import docker_exec, extract, images, manifest, swe
from .agent import user_sim

ROOT = Path(__file__).parent
REPO_ROOT = ROOT.parent
FIXTURES = ROOT / "fixtures"
SQUID_CONF = ROOT / "docker" / "squid.conf"
TOKEN_MOUNT = "/run/secrets/oauth_token"
OUT_DIR = "/selfcheck/out"
IN_DIR = "/selfcheck/in"
DRIVER_DIR = "/opt/selfcheck/agent"
DRIVER_ARGV = [
    "/opt/selfcheck-py/venv/bin/python", f"{DRIVER_DIR}/driver.py", f"{IN_DIR}/input.json",
]
PLACEHOLDERS = (
    "[#TODO][3-5 lines of description of the project]",
    "[#TODO]Alert user to set up definition & north-start of the project.",
)
INSTALL_CMD = (
    "printf 'y\\ny\\ny\\n' | /opt/selfcheck-py/venv/bin/python "
    "/opt/harness-src/installer/harness.py install /testbed --no-ci"
)
COMMIT_CMD = (
    "git add -A && git -c core.hooksPath=/dev/null -c user.name=selfcheck "
    '-c user.email=selfcheck@localhost commit -q -m "selfcheck: install harness"'
)
TOKEN_REMAINED = "token remained after scrub"


class TokenFileMissing(RuntimeError):
    pass


class UnknownRunError(LookupError):
    pass


def compose_prompt(instance: dict, arm: str) -> str:
    text = (
        instance["problem_statement"].strip()
        + "\n\nResolve the issue above in the repository at /testbed. "
        "Add or modify automated tests that verify the fix.\n"
    )
    return "/workflow-approach " + text if arm == "harness" else text


def render_squid_conf(cfg: dict) -> str:
    return SQUID_CONF.read_text().replace("{{ALLOW_HOSTS}}", " ".join(cfg["allow_hosts"]))


def proxy_url(cfg: dict) -> str:
    return f"http://{cfg['proxy_name']}:3128"


def ensure_egress(cfg: dict, *, docker=docker_exec) -> None:
    docker.ensure_network(cfg["network"], internal=True)
    conf = render_squid_conf(cfg)
    conf_hash = hashlib.sha256(conf.encode()).hexdigest()
    status = docker.container_status(cfg["proxy_name"])
    if status and status["running"] and status["labels"].get("selfcheck.proxy") == conf_hash:
        return
    if status is not None:
        docker.remove_container(cfg["proxy_name"])
    docker.start_proxy(
        cfg["proxy_image"],
        name=cfg["proxy_name"],
        networks=["bridge", cfg["network"]],
        labels={"selfcheck.proxy": conf_hash},
        conf_text=conf,
    )


def _token_path(cfg: dict) -> Path:
    path = Path(cfg["token_file"]).expanduser()
    if not path.is_file():
        raise TokenFileMissing(f"token file missing: {path}")
    return path


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
                path.write_bytes(data.replace(needle, b"[REDACTED]"))
                total += count
    return total


def _count_token(directory, token: str) -> int:
    needle = token.encode()
    if not needle:
        return 0
    total = 0
    for root, _, files in os.walk(directory):
        for name in files:
            path = Path(root) / name
            if path.is_symlink() or not path.is_file():
                continue
            total += path.read_bytes().count(needle)
    return total


def _mkdir_private(path: Path) -> None:
    missing = []
    cur = path
    while not cur.exists():
        missing.append(cur)
        cur = cur.parent
    for p in reversed(missing):
        p.mkdir(mode=0o700)
        p.chmod(0o700)


def _git(*args: str) -> str:
    proc = subprocess.run(
        ["git", "-C", str(REPO_ROOT), *args], stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    if proc.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {proc.stderr.decode(errors='replace').strip()}")
    return proc.stdout.decode().strip()


def _write_json(path: Path, obj, **kw) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, **kw))


def _read_json(path: Path):
    return json.loads(path.read_text()) if path.is_file() else None


class _Ctx:
    def __init__(self, cfg, docker, run_id, run_dir, token_path, token, params, instances):
        self.cfg = cfg
        self.docker = docker
        self.run_id = run_id
        self.run_dir = run_dir
        self.token_path = token_path
        self.token = token
        self.params = params
        self.entries = instances
        self.halted = None


def _effective(cfg: dict, model, effort, cap_min) -> dict:
    eff = dict(cfg)
    if model is not None:
        eff["model"] = model
    if effort is not None:
        eff["effort"] = effort
    if cap_min is not None:
        eff["wall_clock_min"] = cap_min
    return eff


def _write_run_json(ctx: _Ctx, created_at) -> None:
    _write_json(
        ctx.run_dir / "run.json",
        {
            "run_id": ctx.run_id, "entries": ctx.entries, "created_at": created_at,
            "halted": ctx.halted,
        },
        indent=1,
    )


def _write_predictions(ctx: _Ctx) -> None:
    lines: dict[str, list[str]] = {}
    for e in ctx.entries:
        d = ctx.run_dir / e["instance_id"] / e["arm"]
        pred, state = d / "prediction.json", _read_json(d / "state.json")
        if pred.is_file() and not (state and state.get("reason") == TOKEN_REMAINED):
            lines.setdefault(e["arm"], []).append(pred.read_text().strip())
    for arm, rows in lines.items():
        (ctx.run_dir / f"predictions.{arm}.jsonl").write_text("".join(r + "\n" for r in rows))


def halt_reason(state: dict | None) -> str | None:
    if not state:
        return None
    if state.get("status") == "interrupted":
        return "interrupted"
    limit = state.get("rate_limit")
    if isinstance(limit, dict) and limit.get("status") not in (None, "allowed"):
        return f"rate_limit:{limit['status']}"
    return None


def _halt_after(ctx: _Ctx, entry: dict, created_at) -> bool:
    d = ctx.run_dir / entry["instance_id"] / entry["arm"]
    reason = halt_reason(_read_json(d / "state.json"))
    if reason is None:
        return False
    ctx.halted = {"reason": reason, "instance_id": entry["instance_id"], "arm": entry["arm"]}
    _write_run_json(ctx, created_at)
    return True


def run(
    instances, arms, *, cfg, harness_ref="HEAD", model=None, effort=None, cap_min=None,
    docker=docker_exec, now=time.time,
) -> Path:
    token_path = _token_path(cfg)
    token = token_path.read_text().strip()
    eff = _effective(cfg, model, effort, cap_min)
    params = {
        "harness_ref": harness_ref,
        "harness_commit": _git("rev-parse", harness_ref),
        "selfcheck_commit": _git("rev-parse", "HEAD"),
        "model": eff["model"],
        "effort": eff["effort"],
        "cap_min": eff["wall_clock_min"],
    }
    ensure_egress(eff, docker=docker)
    run_id = secrets.token_hex(8)
    run_dir = Path(cfg["runs_dir"]).expanduser() / run_id
    _mkdir_private(run_dir)
    pairs = [(inst, arm) for inst in instances for arm in arms]
    entries = [
        {"instance_id": inst["instance_id"], "arm": arm, "status": "pending"} for inst, arm in pairs
    ]
    ctx = _Ctx(eff, docker, run_id, run_dir, token_path, token, params, entries)
    created_at = now()
    _write_json(run_dir / "params.json", params, indent=1)
    _write_run_json(ctx, created_at)
    for n, (inst, arm) in enumerate(pairs, start=1):
        entries[n - 1]["status"] = _run_entry(ctx, n, inst, arm, resume_state=None)
        _write_run_json(ctx, created_at)
        _write_predictions(ctx)
        if _halt_after(ctx, entries[n - 1], created_at):
            break
    return run_dir


def resume(run_id: str, *, cfg, docker=docker_exec) -> Path:
    run_dir = Path(cfg["runs_dir"]).expanduser() / run_id
    meta = _read_json(run_dir / "run.json")
    if meta is None:
        raise UnknownRunError(f"unknown run id: {run_id}")
    params = _read_json(run_dir / "params.json")
    if params is None:
        raise UnknownRunError(f"unknown run id: {run_id}")
    token_path = _token_path(cfg)
    token = token_path.read_text().strip()
    eff = _effective(cfg, params["model"], params["effort"], params["cap_min"])
    ensure_egress(eff, docker=docker)
    pool = {}
    for line in (FIXTURES / "instances.jsonl").read_text().splitlines():
        if line.strip():
            row = json.loads(line)
            pool[row["instance_id"]] = row
    ctx = _Ctx(eff, docker, run_id, run_dir, token_path, token, params, meta["entries"])
    ctx.halted = None
    _write_run_json(ctx, meta["created_at"])
    for n, entry in enumerate(ctx.entries, start=1):
        d = run_dir / entry["instance_id"] / entry["arm"]
        state = _read_json(d / "state.json")
        if state is not None and state.get("status") != "interrupted":
            continue
        if entry["instance_id"] not in pool:
            raise LookupError(f"instance not in pool: {entry['instance_id']}")
        entry["status"] = _run_entry(
            ctx, n, pool[entry["instance_id"]], entry["arm"], resume_state=state
        )
        _write_run_json(ctx, meta["created_at"])
        _write_predictions(ctx)
        if _halt_after(ctx, entry, meta["created_at"]):
            break
    return run_dir


def _append_log(log: list[str], argv_text: str, out: str) -> None:
    log.append(f"$ {argv_text}\n{out}\n")


def _install_harness(ctx: _Ctx, container, instance: dict, log: list[str]):
    def step(argv, *, user="nonroot", timeout=900):
        code, out, _ = container.exec(argv, timeout=timeout, user=user, workdir="/testbed")
        _append_log(log, " ".join(argv), out)
        return code, out

    with tempfile.TemporaryDirectory() as td:
        tar = Path(td) / "harness-src.tar"
        proc = subprocess.run(
            ["git", "-C", str(REPO_ROOT), "archive", "--format=tar", ctx.params["harness_commit"],
             "harness", "installer"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        if proc.returncode != 0:
            _append_log(log, "git archive", proc.stderr.decode(errors="replace"))
            return "install failed: exit %d" % proc.returncode, None, None
        tar.write_bytes(proc.stdout)
        container.copy_in(tar, "/opt/harness-src.tar")
    code, _ = step(
        ["sh", "-c", "mkdir -p /opt/harness-src && tar -xf /opt/harness-src.tar -C /opt/harness-src "
         "&& rm /opt/harness-src.tar"],
        user="root",
    )
    if code != 0:
        return f"install failed: exit {code}", None, None
    code, _ = step(["sh", "-c", INSTALL_CMD])
    if code != 0:
        return f"install failed: exit {code}", None, None

    replaced = False
    definitions = json.loads((FIXTURES / "project_defs.json").read_text())
    agents = container.read_bytes("/testbed/AGENTS.md")
    if agents is not None and instance["repo"] in definitions:
        text = agents.decode()
        new = text
        for placeholder in PLACEHOLDERS:
            new = new.replace(placeholder, definitions[instance["repo"]])
        if new != text:
            container.write_text("/testbed/AGENTS.md", new)
            step(["chown", "nonroot:nonroot", "/testbed/AGENTS.md"], user="root")
            replaced = True
    code, _ = step(["sh", "-c", COMMIT_CMD])
    if code != 0:
        return f"install failed: exit {code}", None, None
    code, out = step(["git", "rev-parse", "HEAD"])
    if code != 0:
        return f"install failed: exit {code}", None, None
    start_commit = out.strip()
    hooks_code, hooks_out = step(["git", "config", "--get", "core.hooksPath"])
    pre_code, _ = step(["test", "-f", ".pre-commit-config.yaml"])
    step(["rm", "-rf", "/opt/harness-src"], user="root")
    install = {
        "hooks_path": hooks_out.strip() if hooks_code == 0 else None,
        "pre_commit_config_present": pre_code == 0,
        "definition_replaced": replaced,
    }
    return None, start_commit, install


def _driver_input(ctx: _Ctx, instance: dict, arm: str, resume_info) -> dict:
    cfg = ctx.cfg
    return {
        "run_id": ctx.run_id,
        "arm": arm,
        "prompt": compose_prompt(instance, arm),
        "model": cfg["model"],
        "effort": cfg["effort"],
        "aliases": cfg["aliases"],
        "disallowed_tools": cfg["disallowed_tools"],
        "wall_clock_s": 60 * cfg["wall_clock_min"],
        "max_user_turns": cfg["max_user_turns"],
        "idle_grace_s": cfg["idle_grace_s"],
        "phrase": user_sim.PHRASE,
        "out_dir": OUT_DIR,
        "token_path": TOKEN_MOUNT,
        "proxy_url": proxy_url(cfg),
        "resume": resume_info,
    }


def _stage_driver(container) -> None:
    with tempfile.TemporaryDirectory() as td:
        stage = Path(td) / "agent"
        stage.mkdir()
        for name in ("driver.py", "user_sim.py"):
            (stage / name).write_bytes((ROOT / "agent" / name).read_bytes())
        container.copy_in(stage, DRIVER_DIR)


def _absent_input_image(docker, instance: dict, cfg: dict) -> str:
    for name in (images.tools_image_name(cfg), swe.image_name(instance)):
        try:
            docker.image_id(name)
        except docker.ImageMissing:
            return name
    return swe.image_name(instance)


def _finalize(ctx: _Ctx, d: Path, state: dict, host: dict) -> str:
    # state.json is serialized in memory and redacted before it is written, so a token carried in
    # driver-reported fields never reaches disk; the directory scrub covers every other file.
    needle = ctx.token
    count = scrub(d, ctx.token)

    def write(final: dict, base: int) -> None:
        text = json.dumps({**final, **host}, indent=1)
        found = text.count(needle) if needle else 0
        host["scrubbed_occurrences"] = base + found
        text = json.dumps({**final, **host}, indent=1)
        (d / "state.json").write_text(text.replace(needle, "[REDACTED]") if needle else text)

    write(state, count)
    if _count_token(d, ctx.token):
        state = {**state, "status": "error", "reason": TOKEN_REMAINED}
        host["error"] = TOKEN_REMAINED
        write(state, count)
    return state["status"]


def _run_entry(ctx: _Ctx, n: int, instance: dict, arm: str, *, resume_state) -> str:
    docker, cfg = ctx.docker, ctx.cfg
    iid = instance["instance_id"]
    d = ctx.run_dir / iid / arm
    d.mkdir(parents=True, exist_ok=True)
    name = f"selfcheck-agent-{ctx.run_id}-{n}"
    host = {"container": name, "host_timeout": False, "scrubbed_occurrences": 0, "error": None}

    def fail(reason: str, base: dict | None = None) -> str:
        state = dict(base or {})
        state.update(status="error", reason=reason)
        host["error"] = reason
        return _finalize(ctx, d, state, host)

    prior_manifest = _read_json(d / "manifest.json") if resume_state is not None else None
    if resume_state is not None:
        if not docker.container_exists(name):
            return fail("container lost", resume_state)
        container = docker.Container(name)
        container.start()
        resume_info = {
            "session_id": resume_state["session_id"],
            "phrases_sent": resume_state["phrases_sent"],
            "elapsed_s": resume_state["elapsed_s"],
        }
    else:
        derived = None
        try:
            derived = images.derived_image_name(instance, cfg, docker=docker)
            docker.image_id(derived)
        except docker.ImageMissing:
            host["container"] = None
            absent = derived or _absent_input_image(docker, instance, cfg)
            return fail(f"image missing: {absent}; run python -m selfcheck images --agent")
        if docker.container_exists(name):
            docker.remove_container(name)
        container = docker.start_container(
            derived, name=name, network=cfg["network"], labels={"selfcheck.agent": ctx.run_id},
            cpus=cfg["cpus"], memory=cfg["memory"],
            mounts=[f"type=bind,src={ctx.token_path},dst={TOKEN_MOUNT},readonly"],
        )
        resume_info = None
    try:
        return _drive(ctx, container, n, instance, arm, d, host, fail, prior_manifest, resume_info)
    except Exception:
        container.remove()
        raise


def _drive(ctx, container, n, instance, arm, d, host, fail, prior_manifest, resume_info) -> str:
    docker, cfg = ctx.docker, ctx.cfg
    raw = d / "raw"
    install_log: list[str] = []
    install = start_commit = None
    if resume_info is not None:
        if prior_manifest is not None:
            start_commit, install = prior_manifest["start_commit"], prior_manifest["install"]
        else:
            _, out, _ = container.exec(["git", "rev-parse", "HEAD"], user="nonroot", workdir="/testbed")
            start_commit = out.strip()
    else:
        _stage_driver(container)
        container.exec(
            ["sh", "-c", f"mkdir -p {IN_DIR} {OUT_DIR} && chown nonroot:nonroot {OUT_DIR}"],
            user="root",
        )
        if arm == "harness":
            reason, start_commit, install = _install_harness(ctx, container, instance, install_log)
            if reason:
                raw.mkdir(parents=True, exist_ok=True)
                (raw / "install.log").write_text("".join(install_log))
                container.remove()
                return fail(reason)
        else:
            code, out, _ = container.exec(
                ["git", "rev-parse", "HEAD"], user="nonroot", workdir="/testbed"
            )
            if code != 0:
                container.remove()
                return fail(f"git failed: {out.strip()}")
            start_commit = out.strip()

    inp = _driver_input(ctx, instance, arm, resume_info)
    container.write_text(f"{IN_DIR}/input.json", json.dumps(inp))
    elapsed = resume_info["elapsed_s"] if resume_info else 0
    timeout = inp["wall_clock_s"] - elapsed + cfg["host_grace_s"]
    code, out, timed_out = container.exec(
        DRIVER_ARGV, timeout=timeout, user="nonroot", workdir="/testbed"
    )
    freeze_info = extract.freeze(container) if timed_out else None
    blob = container.read_bytes(f"{OUT_DIR}/state.json")
    try:
        driver_state = json.loads(blob) if blob else None
    except ValueError:
        driver_state = None

    error = None
    if timed_out:
        host["host_timeout"] = True
        driver_state = dict(driver_state or {})
        driver_state.update(status="capped", reason="wall_clock")
    elif code != 0:
        error = f"driver exit {code}"
    elif driver_state is None:
        error = "driver state missing"
    if error:
        driver_state = dict(driver_state or {})
        driver_state.update(status="error", reason=error)
        host["error"] = error

    prediction = full_diff = None
    status = driver_state["status"]
    if status != "interrupted" and not error:
        freeze_info = freeze_info or extract.freeze(container)
        seed = extract.restore_seed(container, arm)
        try:
            full_diff = extract.full_diff(container, start_commit)
        except extract.GitError as exc:
            error = f"git failed: {exc}"
            driver_state.update(status="error", reason=error)
            host["error"] = error
        else:
            prediction = extract.build_prediction(
                full_diff, instance, arm, ctx.run_id, start_commit, freeze_info, seed
            )

    container.copy_out(f"{OUT_DIR}/.", raw)
    raw.mkdir(parents=True, exist_ok=True)
    if full_diff is not None:
        (raw / "full.diff").write_text(full_diff)
    if install_log:
        (raw / "install.log").write_text("".join(install_log))
    if error or timed_out:
        (raw / "driver.log").write_text(out)

    images_info = {
        "instance_image_id": docker.image_id(swe.image_name(instance)),
        "tools_image_id": docker.image_id(images.tools_image_name(cfg)),
        "derived_image": images.derived_image_name(instance, cfg, docker=docker),
        "freeze_before": (container.read_bytes("/opt/selfcheck/freeze-before.txt") or b"").decode(),
        "freeze_after": (container.read_bytes("/opt/selfcheck/freeze-after.txt") or b"").decode(),
    }
    images_info["derived_image_id"] = docker.image_id(images_info["derived_image"])
    squid_hash = hashlib.sha256(render_squid_conf(cfg).encode()).hexdigest()
    _write_json(
        d / "manifest.json",
        manifest.build(
            run_id=ctx.run_id, instance=instance, arm=arm, cfg=cfg,
            selfcheck_commit=ctx.params["selfcheck_commit"], harness_ref=ctx.params["harness_ref"],
            harness_commit=ctx.params["harness_commit"] if arm == "harness" else None,
            start_commit=start_commit, install=install, images=images_info,
            proxy={"allow_hosts": cfg["allow_hosts"], "proxy_image": cfg["proxy_image"],
                   "squid_conf_hash": squid_hash},
            driver_state=driver_state, prompt=inp["prompt"],
        ),
        indent=1, sort_keys=True,
    )
    if prediction is not None:
        _write_json(d / "prediction.json", prediction, sort_keys=True)

    status = _finalize(ctx, d, driver_state, host)

    if status == "interrupted":
        container.stop()
    else:
        container.remove()
    return status


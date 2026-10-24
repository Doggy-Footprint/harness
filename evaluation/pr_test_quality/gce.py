import hashlib
import os
import shlex
import sys
import tarfile
import tempfile
import time
from pathlib import Path

from . import data_dir, results_dir, section

ROOT = Path(__file__).parent
REPO_ROOT = ROOT.parents[1]
STARTUP_SCRIPT = ROOT / "docker" / "startup.sh"
IAP_RANGE = "35.235.240.0/20"
RUN_USER = "evaluation"
REMOTE_REPO = "/data/src"
REMOTE_ENV = (
    "EVALUATION_DATA_DIR=/data/evaluation EVALUATION_RESULTS_DIR=/data/results "
    "EVALUATION_TOKEN_FILE=/data/secrets/oauth_token"
)
BINDING_ATTEMPTS = 6
BINDING_WAIT_S = 10
STOPPED = ("TERMINATED", "STOPPED", "SUSPENDED")
DEFAULTS = {
    "machine_type": "n2-standard-16", "disk_size": "300GB", "disk_type": "pd-balanced",
    "vm_name": "harness-eval-vm", "service_account": "harness-eval-sa", "subnet_range": "10.10.0.0/24",
    "boot_disk_size": "50GB", "image_family": "debian-12", "image_project": "debian-cloud",
}


def _g(cfg: dict) -> dict:
    return {**DEFAULTS, **section(cfg, "gce")}


def _base(g: dict, *, zone: bool = False, region: bool = False) -> list[str]:
    out = ["--project", g["project"]]
    if zone:
        out += ["--zone", g["zone"]]
    if region:
        out += ["--region", g["region"]]
    return out


def _sa_email(g: dict) -> str:
    return f"{g['service_account']}@{g['project']}.iam.gserviceaccount.com"


def _steps(cfg: dict) -> list[dict]:
    g = _g(cfg)
    net, sub, router = g["network"], f"{g['network']}-subnet", f"{g['network']}-router"
    nat, fw = f"{g['network']}-nat", f"{g['network']}-allow-iap-ssh"
    member = f"serviceAccount:{_sa_email(g)}"
    role = "roles/secretmanager.secretAccessor"
    zone, region, plain = _base(g, zone=True), _base(g, region=True), _base(g)
    create_vm = [
        "gcloud", "compute", "instances", "create", g["vm_name"], *zone,
        "--machine-type", g["machine_type"],
        *(["--provisioning-model=SPOT", "--instance-termination-action=STOP"] if g.get("spot", False) else []),
        "--no-address", "--network", net, "--subnet", sub,
        "--image-family", g["image_family"], "--image-project", g["image_project"],
        "--boot-disk-size", g["boot_disk_size"],
        "--service-account", _sa_email(g), "--scopes=cloud-platform",
        "--disk", f"name={g['data_disk']},device-name={g['data_disk']},mode=rw,boot=no",
        "--metadata", f"eval-project={g['project']},eval-secret={g['secret']},eval-user={RUN_USER},"
                      f"eval-disk={g['data_disk']}",
        "--metadata-from-file", f"startup-script={STARTUP_SCRIPT}",
    ]
    return [
        {"name": "network", "check": ["gcloud", "compute", "networks", "describe", net, *plain],
         "create": ["gcloud", "compute", "networks", "create", net, "--subnet-mode=custom", *plain]},
        {"name": "subnet", "check": ["gcloud", "compute", "networks", "subnets", "describe", sub, *region],
         "create": ["gcloud", "compute", "networks", "subnets", "create", sub, "--network", net,
                    "--range", g["subnet_range"], "--enable-private-ip-google-access", *region]},
        {"name": "router", "check": ["gcloud", "compute", "routers", "describe", router, *region],
         "create": ["gcloud", "compute", "routers", "create", router, "--network", net, *region]},
        {"name": "nat", "check": ["gcloud", "compute", "routers", "nats", "describe", nat, "--router", router, *region],
         "create": ["gcloud", "compute", "routers", "nats", "create", nat, "--router", router,
                    "--auto-allocate-nat-external-ips", "--nat-all-subnet-ip-ranges", *region]},
        {"name": "firewall", "check": ["gcloud", "compute", "firewall-rules", "describe", fw, *plain],
         "create": ["gcloud", "compute", "firewall-rules", "create", fw, "--network", net,
                    "--direction=INGRESS", "--action=allow", "--rules=tcp:22",
                    f"--source-ranges={IAP_RANGE}", *plain]},
        {"name": "service-account", "check": ["gcloud", "iam", "service-accounts", "describe", _sa_email(g), *plain],
         "create": ["gcloud", "iam", "service-accounts", "create", g["service_account"],
                    "--display-name", "harness evaluation VM", *plain]},
        {"name": "secret", "check": ["gcloud", "secrets", "describe", g["secret"], *plain],
         "create": ["gcloud", "secrets", "create", g["secret"], "--replication-policy=automatic", *plain]},
        {"name": "secret-access", "kind": "binding", "member": member, "role": role,
         "check": ["gcloud", "secrets", "get-iam-policy", g["secret"], "--format=json", *plain],
         "create": ["gcloud", "secrets", "add-iam-policy-binding", g["secret"], f"--member={member}",
                    f"--role={role}", *plain]},
        {"name": "secret-version", "kind": "version",
         "check": ["gcloud", "secrets", "versions", "access", "latest", "--secret", g["secret"], *plain],
         "create": ["gcloud", "secrets", "versions", "add", g["secret"], "--data-file=-", *plain]},
        {"name": "data-disk", "check": ["gcloud", "compute", "disks", "describe", g["data_disk"], *zone],
         "create": ["gcloud", "compute", "disks", "create", g["data_disk"], f"--size={g['disk_size']}",
                    f"--type={g['disk_type']}", *zone]},
        {"name": "vm", "kind": "vm",
         "check": ["gcloud", "compute", "instances", "describe", g["vm_name"], "--format=value(status)", *zone],
         "start": ["gcloud", "compute", "instances", "start", g["vm_name"], *zone],
         "create": create_vm},
    ]


def plan_up(cfg: dict) -> list[list[str]]:
    return [step["create"] for step in _steps(cfg)]


def _say(message: str) -> None:
    print(message, file=sys.stderr)


def _fail(step: str, rc: int, err: str) -> int:
    tail = "\n".join((err or "").strip().splitlines()[-10:])
    _say(f"gce step failed: {step} (exit {rc})\n{tail}")
    return 1


def _read_token(cfg: dict) -> str | None:
    path = Path(cfg.get("token_file", "")).expanduser()
    return path.read_text().strip() if path.is_file() else None


def _digest(value: str) -> str:
    return hashlib.sha256(value.strip().encode()).hexdigest()


def up(cfg: dict, *, run_fn) -> int:
    token = _read_token(cfg)
    if token is None:
        _say(f"token file missing: {Path(cfg.get('token_file', '')).expanduser()}; save the OAuth token there first")
        return 2
    for step in _steps(cfg):
        rc, out, err = run_fn(step["check"], timeout=120)
        kind = step.get("kind")
        if kind == "version":
            if rc == 0 and _digest(out) == _digest(token):
                continue
            rc, _, err = run_fn(step["create"], input=token, timeout=120)
        elif kind == "binding":
            if rc == 0 and step["member"] in out and step["role"] in out:
                continue
            for attempt in range(BINDING_ATTEMPTS):
                rc, _, err = run_fn(step["create"], timeout=120)
                if rc == 0 or "does not exist" not in (err or "").lower() or attempt == BINDING_ATTEMPTS - 1:
                    break
                time.sleep(BINDING_WAIT_S)
        elif kind == "vm":
            if rc == 0:
                if out.strip() in STOPPED:
                    rc, _, err = run_fn(step["start"], timeout=300)
                    if rc != 0:
                        return _fail("vm start", rc, err)
                continue
            rc, _, err = run_fn(step["create"], timeout=600)
        else:
            if rc == 0:
                continue
            rc, _, err = run_fn(step["create"], timeout=300)
        if rc != 0:
            return _fail(step["name"], rc, err)
        _say(f"created: {step['name']}")
    return 0


def down(cfg: dict, *, run_fn, purge: bool = False, yes: bool = False) -> int:
    g = _g(cfg)
    if purge and not yes:
        _say("--purge deletes the data disk and the secret; rerun with `gce down --purge --yes` to confirm")
        return 2
    zone, plain = _base(g, zone=True), _base(g)
    steps = [("vm", ["gcloud", "compute", "instances", "describe", g["vm_name"], *zone],
              ["gcloud", "compute", "instances", "delete", g["vm_name"], "--quiet", *zone])]
    if purge:
        steps += [
            ("data-disk", ["gcloud", "compute", "disks", "describe", g["data_disk"], *zone],
             ["gcloud", "compute", "disks", "delete", g["data_disk"], "--quiet", *zone]),
            ("secret", ["gcloud", "secrets", "describe", g["secret"], *plain],
             ["gcloud", "secrets", "delete", g["secret"], "--quiet", *plain]),
        ]
    for name, check, delete in steps:
        rc, _, _ = run_fn(check, timeout=120)
        if rc != 0:
            continue
        rc, _, err = run_fn(delete, timeout=600)
        if rc != 0:
            return _fail(f"delete {name}", rc, err)
        _say(f"deleted: {name}")
    return 0


def _ssh(g: dict, command: str) -> list[str]:
    return ["gcloud", "compute", "ssh", g["vm_name"], *_base(g, zone=True), "--tunnel-through-iap",
            "--command", command]


def _scp(g: dict, *paths: str, recurse: bool = False) -> list[str]:
    return ["gcloud", "compute", "scp", *(["--recurse"] if recurse else []), *_base(g, zone=True),
            "--tunnel-through-iap", *paths]


def _as_run_user(script: str) -> str:
    return f"sudo -u {RUN_USER} -H bash -lc {shlex.quote(script)}"


def _tracked_files(run_fn) -> list[str]:
    rc, out, err = run_fn(["git", "-C", str(REPO_ROOT), "ls-files", "-z", "--cached", "--others",
                           "--exclude-standard"], timeout=120)
    if rc != 0:
        raise RuntimeError(f"git ls-files failed: {err.strip()}")
    return [p for p in out.split("\0") if p]


def _skip_apple_double(info):
    return None if Path(info.name).name.startswith("._") else info


def _ship(g: dict, run_fn, archive: str, remote: str, extract: str, step: str) -> int:
    rc, _, err = run_fn(_scp(g, archive, f"{g['vm_name']}:{remote}"), timeout=1800)
    if rc != 0:
        return _fail(f"scp {step}", rc, err)
    rc, _, err = run_fn(_ssh(g, f"sudo chmod a+r {remote} && " + _as_run_user(extract) + f" && rm -f {remote}"),
                        timeout=600)
    return 0 if rc == 0 else _fail(f"extract {step}", rc, err)


def push(cfg: dict, *, run_fn) -> int:
    g = _g(cfg)
    try:
        names = _tracked_files(run_fn)
    except RuntimeError as exc:
        return _fail("git ls-files", 1, str(exc))
    fd, archive = tempfile.mkstemp(suffix=".tgz", prefix="evaluation-push-")
    os.close(fd)
    try:
        with tarfile.open(archive, "w:gz") as tar:
            for name in names:
                path = REPO_ROOT / name
                if (path.is_file() or path.is_symlink()) and not Path(name).name.startswith("._"):
                    tar.add(path, arcname=name, recursive=False)
            if (REPO_ROOT / ".git").is_dir():
                tar.add(REPO_ROOT / ".git", arcname=".git", filter=_skip_apple_double)
        extract = f"mkdir -p {REMOTE_REPO} && rm -rf {REMOTE_REPO}/.git && tar -xzf /tmp/evaluation-push.tgz -C {REMOTE_REPO}"
        rc = _ship(g, run_fn, archive, "/tmp/evaluation-push.tgz", extract, "push archive")
    finally:
        Path(archive).unlink(missing_ok=True)
    tasks = data_dir(cfg) / "tasks"
    if rc != 0 or not tasks.is_dir():
        return rc
    fd, archive = tempfile.mkstemp(suffix=".tgz", prefix="evaluation-tasks-")
    os.close(fd)
    try:
        with tarfile.open(archive, "w:gz") as tar:
            tar.add(tasks, arcname="tasks", filter=_skip_apple_double)
        remote_data = "/data/evaluation"
        extract = f"mkdir -p {remote_data} && rm -rf {remote_data}/tasks && tar -xzf /tmp/evaluation-tasks.tgz -C {remote_data}"
        return _ship(g, run_fn, archive, "/tmp/evaluation-tasks.tgz", extract, "tasks archive")
    finally:
        Path(archive).unlink(missing_ok=True)


def exec_remote(cfg: dict, argv: list[str], *, run_fn, detach: bool = False) -> int:
    g = _g(cfg)
    inner = shlex.join(argv)
    if detach:
        log = f"/data/logs/{time.strftime('%Y%m%d-%H%M%S')}.log"
        script = f"cd {REMOTE_REPO} && mkdir -p /data/logs && {REMOTE_ENV} nohup {inner} > {log} 2>&1 < /dev/null &"
    else:
        script = f"cd {REMOTE_REPO} && {REMOTE_ENV} {inner}"
    rc, out, err = run_fn(_ssh(g, _as_run_user(script)), timeout=None)
    if out:
        print(out, end="" if out.endswith("\n") else "\n")
    if rc != 0:
        return _fail("remote command", rc, err)
    if detach:
        _say(f"detached; log: {log}")
    return 0


def pull(cfg: dict, run_id: str, *, run_fn) -> int:
    g = _g(cfg)
    results = results_dir(cfg)
    runs = data_dir(cfg) / "runs"
    results.mkdir(parents=True, exist_ok=True)
    runs.mkdir(parents=True, exist_ok=True)
    plan = [
        ("copy results", _scp(g, f"{g['vm_name']}:/data/results/{run_id}.*", str(results))),
        ("copy run directory", _scp(g, f"{g['vm_name']}:/data/evaluation/runs/{run_id}", str(runs), recurse=True)),
    ]
    for name, argv in plan:
        rc, _, err = run_fn(argv, timeout=3600)
        if rc != 0:
            return _fail(name, rc, err)
    return 0


def status(cfg: dict, *, run_fn) -> int:
    g = _g(cfg)
    rc, out, err = run_fn(["gcloud", "compute", "instances", "describe", g["vm_name"],
                           "--format=value(status)", *_base(g, zone=True)], timeout=120)
    if rc != 0:
        return _fail("status", rc, err)
    print(out.strip())
    return 0

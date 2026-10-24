import hashlib
import json
import re
import tempfile
from pathlib import Path

from . import docker_exec, swe

PASS = {"PASSED", "XFAIL"}
FAIL = {"FAILED", "ERROR"}
TESTBED_PYTHON = "/opt/miniconda3/envs/testbed/bin/python"

# Same fallback order as swebench's apply sequence (GIT_APPLY_CMDS).
APPLY_CMDS = (
    "git apply --verbose /tmp/selfcheck_src.diff",
    "git apply --verbose --reject /tmp/selfcheck_src.diff",
    "patch --batch --fuzz=5 -p1 -i /tmp/selfcheck_src.diff",
)

_scratch_logs: Path | None = None


def _log_dir(cache_dir: Path | None) -> Path:
    global _scratch_logs
    if cache_dir is not None:
        d = cache_dir / "logs"
    else:
        if _scratch_logs is None:
            _scratch_logs = Path(tempfile.mkdtemp(prefix="selfcheck-logs-"))
        d = _scratch_logs
    d.mkdir(parents=True, exist_ok=True)
    return d


def _resolve_image_id(image: str, cache_dir: Path | None) -> str:
    record = cache_dir / "image_ids.json" if cache_dir is not None else None
    try:
        iid = docker_exec.image_id(image)
    except docker_exec.DockerUnreachable:
        # Lets a cache hit be served while the daemon is down (QR3).
        if record is not None and record.is_file():
            known = json.loads(record.read_text()).get(image)
            if known is not None:
                return known
        raise
    if record is not None:
        data = json.loads(record.read_text()) if record.is_file() else {}
        if data.get(image) != iid:
            data[image] = iid
            record.parent.mkdir(parents=True, exist_ok=True)
            record.write_text(json.dumps(data))
    return iid


def _apply_src(c, src_diff: str) -> bool:
    c.write_text("/tmp/selfcheck_src.diff", src_diff)
    for cmd in APPLY_CMDS:
        rc, _, _ = c.exec(["bash", "-c", f"cd /testbed && {cmd}"], timeout=300)
        if rc == 0:
            return True
    return False


def _cache_key(image_id: str, script: str, src_diff: str, test_patch: str, repeat: int, network: bool) -> str:
    payload = json.dumps([image_id, script, src_diff, test_patch, repeat, network])
    return hashlib.sha256(payload.encode()).hexdigest()


def evaluate(
    instance: dict,
    src_diff: str,
    test_patch: str,
    *,
    repeat: int = 0,
    timeout_s: int = 1800,
    cache_dir: str | Path | None = None,
    network: bool = False,
) -> dict:
    cache = Path(cache_dir).expanduser() if cache_dir is not None else None
    image = swe.image_name(instance)
    iid = _resolve_image_id(image, cache)
    script = swe.eval_script(instance, test_patch)
    key = _cache_key(iid, script, src_diff, test_patch, repeat, network)
    entry = cache / "entries" / f"{key}.json" if cache is not None else None
    if entry is not None and entry.is_file():
        return json.loads(entry.read_text())

    result = {
        "key": key,
        "apply": "ok",
        "status": {},
        "exit_code": None,
        "no_tests": False,
        "timed_out": False,
        "log_path": None,
    }
    log = ""
    with docker_exec.container(image, network=network) as c:
        if src_diff and not _apply_src(c, src_diff):
            result["apply"] = "src_failed"
        else:
            c.write_text("/tmp/selfcheck_eval.sh", script)
            rc, log, timed_out = c.exec(["bash", "/tmp/selfcheck_eval.sh"], timeout=timeout_s)
            result["timed_out"] = timed_out
            if not timed_out:
                _interpret(instance, result, log)

    if log:
        path = _log_dir(cache) / f"{key}.log"
        path.write_text(log)
        result["log_path"] = str(path)
    if entry is not None:
        entry.parent.mkdir(parents=True, exist_ok=True)
        tmp = entry.with_suffix(".tmp")
        tmp.write_text(json.dumps(result))
        tmp.replace(entry)
    return result


def _interpret(instance: dict, result: dict, log: str) -> None:
    if re.search(r"^SELFCHECK_TEST_APPLY_FAILED\s*$", log, re.M):
        result["apply"] = "test_failed"
        return
    if re.search(r"^SELFCHECK_NO_TESTS\s*$", log, re.M):
        result["no_tests"] = True
        return
    m = re.search(r"^SELFCHECK_EXIT=(-?\d+)\s*$", log, re.M)
    if m:
        result["exit_code"] = int(m.group(1))
    result["status"] = swe.parse_status(instance, log)


def read_files(instance: dict, src_diff: str, paths: list[str]) -> dict[str, str | None]:
    image = swe.image_name(instance)
    docker_exec.image_id(image)
    out: dict[str, str | None] = {}
    with docker_exec.container(image) as c:
        if src_diff and not _apply_src(c, src_diff):
            raise RuntimeError(f"src_diff does not apply to {instance['instance_id']}")
        for p in paths:
            data = c.read_bytes(f"/testbed/{p}")
            out[p] = None if data is None else data.decode("utf-8", errors="replace")
    return out


def compile_ok(instance: dict, patch: str, paths: list[str]) -> bool:
    image = swe.image_name(instance)
    docker_exec.image_id(image)
    with docker_exec.container(image) as c:
        if patch and not _apply_src(c, patch):
            return False
        for p in paths:
            rc, _, _ = c.exec(
                ["bash", "-c", f"cd /testbed && {TESTBED_PYTHON} -m py_compile '{p}'"],
                timeout=300,
            )
            if rc != 0:
                return False
    return True

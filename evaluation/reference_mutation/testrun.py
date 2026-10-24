import hashlib
import json
import posixpath
import time
from pathlib import Path

from . import atomic_write, junit, recipes, section

TESTBED = "/testbed"
JUNIT_PATH = "/tmp/evaluation-junit.xml"
CACHEABLE = ("ok", "build_error")


def cache_key(image_id: str, tree: dict, selection: list[str], repeat: int) -> str:
    payload = json.dumps(
        [image_id, sorted(tree.items(), key=lambda kv: kv[0]), list(selection), repeat],
        ensure_ascii=False, sort_keys=True,
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def apply_tree(c, tree: dict[str, str | None]) -> None:
    writes = {p: t for p, t in tree.items() if t is not None}
    deletes = [p for p, t in tree.items() if t is None]
    dirs = sorted({posixpath.dirname(f"{TESTBED}/{p}") for p in writes})
    if dirs:
        c.exec(["mkdir", "-p", *dirs], user="root")
    if deletes:
        c.exec(["rm", "-f", *[f"{TESTBED}/{p}" for p in deletes]], user="root")
    for path, text in writes.items():
        c.write_text(f"{TESTBED}/{path}", text)


def run_tests(task: dict, tree: dict, selection: list[str], *, docker, cfg: dict, cache_dir, repeat: int = 0) -> dict:
    image_id = docker.image_id(task["image"])
    cache_file = Path(cache_dir) / f"{cache_key(image_id, tree, selection, repeat)}.json"
    if cache_file.is_file():
        return {**json.loads(cache_file.read_text()), "cached": True}
    timeout = section(cfg, "eval").get("timeout_s", 900)
    argv = recipes.test_argv(task["recipe"], selection, JUNIT_PATH)
    started = time.monotonic()
    with docker.container(task["image"], network=False) as c:
        apply_tree(c, tree)
        _, _, timed_out = c.exec(argv, timeout=timeout, user="root", workdir=TESTBED)
        blob = None if timed_out else c.read_bytes(JUNIT_PATH)
    runtime = round(time.monotonic() - started, 3)
    if timed_out:
        return {"status": "timeout", "results": {}, "runtime_s": runtime, "cached": False}
    result = {"status": "ok", "results": {}, "runtime_s": runtime, "cached": False}
    if blob is None:
        result["status"] = "build_error"
    else:
        try:
            result["results"] = junit.parse(blob.decode(errors="replace"), language=task["language"])
        except junit.JunitError:
            result["status"] = "parse_error"
    if result["status"] in CACHEABLE:
        atomic_write(cache_file, json.dumps(result, sort_keys=True))
    return result

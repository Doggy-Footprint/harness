import copy
import json
import os
import shutil
import subprocess
import tempfile
import threading
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "selfcheck" / "data"
DOCKER_ENABLED = os.environ.get("SELFCHECK_DOCKER") == "1"
docker_only = unittest.skipUnless(DOCKER_ENABLED, "set SELFCHECK_DOCKER=1 to run Docker tests")

PYTEST_ID = "pytest-dev__pytest-5787"
DJANGO_ID = "django__django-11400"
SYMPY_ID = "sympy__sympy-18199"


def pilot_rows():
    rows = {}
    with open(DATA / "pilot_instances.jsonl", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                row = json.loads(line)
                rows[row["instance_id"]] = row
    return rows


def pilot(instance_id):
    return copy.deepcopy(pilot_rows()[instance_id])


def verified_paths():
    with open(DATA / "verified_paths.json", encoding="utf-8") as handle:
        return json.load(handle)


def eval_result(status=None, *, apply="ok", exit_code=0, no_tests=False, timed_out=False,
                log_path=None, key="k"):
    return {
        "key": key,
        "apply": apply,
        "status": dict(status or {}),
        "exit_code": exit_code,
        "no_tests": no_tests,
        "timed_out": timed_out,
        "log_path": log_path,
    }


class FakeEvaluate:
    def __init__(self, respond, log=None):
        self.respond = respond
        self.calls = []
        self.log = log
        self.lock = threading.Lock()

    def __call__(self, instance, src_diff, test_patch, **kwargs):
        entry = ("evaluate", src_diff, test_patch, dict(kwargs))
        with self.lock:
            self.calls.append(entry[1:])
            if self.log is not None:
                self.log.append(entry)
        return self.respond(instance, src_diff, test_patch, **kwargs)


class FakeReadFiles:
    def __init__(self, texts, log=None):
        self.texts = texts
        self.calls = []
        self.log = log

    def __call__(self, instance, src_diff, paths):
        self.calls.append((src_diff, list(paths)))
        if self.log is not None:
            self.log.append(("read_files", src_diff, list(paths)))
        return {path: self.texts.get(path) for path in paths}


def _git(cwd, *args, check=True):
    return subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "core.autocrlf=false", *args],
        cwd=cwd, capture_output=True, text=True, check=check,
    )


def _write_tree(root, files):
    for name, text in files.items():
        if text is None:
            continue
        target = Path(root) / name
        target.parent.mkdir(parents=True, exist_ok=True)
        with open(target, "w", encoding="utf-8", newline="") as handle:
            handle.write(text)


def git_diff(base, new):
    with tempfile.TemporaryDirectory() as tmp:
        _git(tmp, "init", "-q")
        _write_tree(tmp, base)
        _git(tmp, "add", "-A")
        _git(tmp, "commit", "-q", "--allow-empty", "-m", "base")
        for name, text in base.items():
            if text is not None and new.get(name) is None:
                (Path(tmp) / name).unlink()
        _write_tree(tmp, new)
        _git(tmp, "add", "-A")
        return _git(tmp, "diff", "--cached", "--no-color").stdout


def git_apply_files(base, patch):
    with tempfile.TemporaryDirectory() as tmp:
        _git(tmp, "init", "-q")
        _write_tree(tmp, base)
        Path(tmp, ".patch").write_text(patch, encoding="utf-8", newline="")
        _git(tmp, "apply", "--whitespace=nowarn", ".patch")
        result = {}
        for path in Path(tmp).rglob("*"):
            if path.is_file() and ".git" not in path.relative_to(tmp).parts and path.name != ".patch":
                result[path.relative_to(tmp).as_posix()] = path.read_bytes().decode("utf-8")
        return result


def wait_for_docker(timeout=90, interval=2):
    deadline = time.monotonic() + timeout
    while True:
        probe = subprocess.run(["docker", "info"], capture_output=True)
        if probe.returncode == 0:
            return
        if time.monotonic() >= deadline:
            raise AssertionError("docker daemon did not become ready within %d s" % timeout)
        time.sleep(interval)


def make_shim(directory, body):
    real = shutil.which("docker")
    path = Path(directory) / "docker"
    path.write_text("#!/bin/sh\n" + body.replace("@REAL@", real), encoding="utf-8")
    path.chmod(0o755)
    return str(directory)


def labeled_containers():
    out = subprocess.run(
        ["docker", "ps", "-a", "--filter", "label=selfcheck=1", "-q"],
        capture_output=True, text=True, check=True,
    ).stdout
    return out.split()


def clear_labeled_containers():
    wait_for_docker()
    ids = labeled_containers()
    if ids:
        subprocess.run(["docker", "rm", "-f", *ids], capture_output=True)


def require_image(instance):
    wait_for_docker()
    tag = "sweb.eval.arm64.%s:latest" % instance["instance_id"].lower()
    result = subprocess.run(["docker", "image", "inspect", tag], capture_output=True)
    # Engine start after Docker Desktop idle shutdown: inspect-by-name fails for up to ~60 s
    # while `image ls` already lists the image.
    deadline = time.monotonic() + 120
    while result.returncode != 0 and time.monotonic() < deadline:
        listed = subprocess.run(["docker", "image", "ls", "-q", tag], capture_output=True, text=True)
        if listed.returncode != 0 or not listed.stdout.strip():
            break
        time.sleep(2)
        result = subprocess.run(["docker", "image", "inspect", tag], capture_output=True)
    if result.returncode != 0:
        raise AssertionError("pilot image %s is missing; build it before running Docker tests" % tag)
    return tag


def pass_set(status):
    return status in ("PASSED", "XFAIL")


def build_derived_image(base_tag, tag, body, files=None, user=""):
    with tempfile.TemporaryDirectory() as context:
        for name, text in (files or {}).items():
            Path(context, name).write_text(text, encoding="utf-8")
        dockerfile = "FROM %s\nUSER root\n%s\n%s\n" % (base_tag, body, "USER %s" % user if user else "")
        Path(context, "Dockerfile").write_text(dockerfile, encoding="utf-8")
        built = subprocess.run(["docker", "build", "-q", "-t", tag, context], capture_output=True, text=True)
    if built.returncode != 0:
        raise AssertionError("docker build failed: " + built.stderr)


def remove_image(tag):
    subprocess.run(["docker", "rmi", "-f", tag], capture_output=True)

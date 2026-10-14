import json
import os
from pathlib import Path

from swebench.harness.constants import END_TEST_OUTPUT, START_TEST_OUTPUT, USE_X86
from swebench.harness.log_parsers import MAP_REPO_TO_PARSER
from swebench.harness.test_spec.python import get_test_directives
from swebench.harness.test_spec.test_spec import make_test_spec

ARCH = "arm64"
APPLY_FAILED_MARKER = "SELFCHECK_TEST_APPLY_FAILED"
NO_TESTS_MARKER = "SELFCHECK_NO_TESTS"
EXIT_MARKER = "SELFCHECK_EXIT"
START_MARKER = START_TEST_OUTPUT
END_MARKER = END_TEST_OUTPUT

__all__ = ["USE_X86"]


def image_name(instance: dict) -> str:
    return f"sweb.eval.{ARCH}.{instance['instance_id'].lower()}:latest"


def _row(instance: dict, test_patch: str | None) -> dict:
    row = dict(instance)
    row.pop("hints_text", None)
    if test_patch is not None:
        row["test_patch"] = test_patch
    return row


def make_spec(instance: dict, test_patch: str | None = None):
    return make_test_spec(_row(instance, test_patch), namespace=None, arch=ARCH)


def directives(instance: dict, test_patch: str | None = None) -> list[str]:
    return get_test_directives(_row(instance, test_patch))


def eval_script(instance: dict, test_patch: str | None = None) -> str:
    items = list(make_spec(instance, test_patch).eval_script_list)
    end_idx = items.index(f": '{END_TEST_OUTPUT}'")
    apply_idx = next(i for i, s in enumerate(items) if s.startswith("git apply -v - <<"))
    out = []
    for i, item in enumerate(items):
        if i == end_idx:
            out.append(f"echo {EXIT_MARKER}=$?")
        out.append(item)
        if i == apply_idx:
            out.append(f"[ $? -eq 0 ] || {{ echo {APPLY_FAILED_MARKER}; exit 1; }}")
    if not directives(instance, test_patch):
        first_reset = next(i for i, s in enumerate(out) if s.startswith("git checkout "))
        out.insert(first_reset, f"echo {NO_TESTS_MARKER}; exit 0")
    return "\n".join(["#!/bin/bash", "set -uxo pipefail"] + out) + "\n"


def parse_status(instance: dict, log_text: str) -> dict[str, str]:
    if START_TEST_OUTPUT not in log_text or END_TEST_OUTPUT not in log_text:
        return {}
    content = log_text.split(START_TEST_OUTPUT)[1].split(END_TEST_OUTPUT)[0]
    spec = make_spec(instance)
    return MAP_REPO_TO_PARSER[instance["repo"]](content, spec)


def build_images(
    instances: list[dict], *, max_workers: int = 2, workdir: str | Path | None = None
) -> tuple[list[str], list[str]]:
    import docker
    from swebench.harness.docker_build import build_instance_images

    if workdir is None:
        cache = json.loads((Path(__file__).parent / "config.json").read_text())["cache_dir"]
        workdir = Path(cache).expanduser() / "build"
    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    client = docker.from_env()
    specs = [make_spec(i) for i in instances]
    # swebench writes logs/build_images relative to the process working directory.
    previous = os.getcwd()
    os.chdir(workdir)
    try:
        ok, _ = build_instance_images(
            client, specs, max_workers=max_workers, namespace=None
        )
    finally:
        os.chdir(previous)
    built = sorted(p[0].instance_id for p in ok)
    failed = sorted(i["instance_id"] for i in instances if i["instance_id"] not in built)
    return built, failed

import hashlib
import json
import shutil
import subprocess
import tempfile
from pathlib import Path

from . import docker_exec, swe

ROOT = Path(__file__).parent
TOOLS_DOCKERFILE = ROOT / "docker" / "tools.Dockerfile"
DERIVED_DOCKERFILE = ROOT / "docker" / "derived.Dockerfile"
SHIM = ROOT / "agent" / "shim" / "python3"
ENV_FILE = ROOT / "agent" / "env.sh"


class ImageBuildError(RuntimeError):
    pass


def _digest(parts: list[bytes]) -> str:
    h = hashlib.sha256()
    for part in parts:
        h.update(part)
        h.update(b"\0")
    return h.hexdigest()[:12]


def tools_image_name(cfg: dict) -> str:
    parts = [TOOLS_DOCKERFILE.read_bytes()]
    parts += [cfg[k].encode() for k in ("sdk", "uv_image", "tools_base", "python")]
    return f"selfcheck-tools:{_digest(parts)}"


def _derived_inputs(instance: dict, cfg: dict, docker) -> dict:
    return {
        "dockerfile": hashlib.sha256(DERIVED_DOCKERFILE.read_bytes()).hexdigest(),
        "shim": hashlib.sha256(SHIM.read_bytes()).hexdigest(),
        "env": hashlib.sha256(ENV_FILE.read_bytes()).hexdigest(),
        "tools_image_id": docker.image_id(tools_image_name(cfg)),
        "instance_image_id": docker.image_id(swe.image_name(instance)),
        "testbed_tools": list(cfg["testbed_tools"]),
    }


def derived_image_name(instance: dict, cfg: dict, *, docker=docker_exec) -> str:
    inputs = _derived_inputs(instance, cfg, docker)
    tag = _digest([json.dumps(inputs, sort_keys=True).encode()])
    return f"selfcheck-agent.arm64.{instance['instance_id'].lower()}:{tag}"


def _exists(name: str) -> bool:
    try:
        docker_exec.image_id(name)
    except docker_exec.ImageMissing:
        return False
    return True


def _build(name: str, context: Path, args: list[str]) -> None:
    proc = subprocess.run(
        ["docker", "build", "-t", name, *args, str(context)],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    if proc.returncode != 0:
        tail = "\n".join(proc.stdout.decode(errors="replace").splitlines()[-40:])
        raise ImageBuildError(f"image build failed for {name}:\n{tail}")


def build_tools_image(cfg: dict) -> str:
    name = tools_image_name(cfg)
    if _exists(name):
        return name
    with tempfile.TemporaryDirectory() as td:
        ctx = Path(td)
        shutil.copy2(TOOLS_DOCKERFILE, ctx / "Dockerfile")
        _build(
            name,
            ctx,
            [
                "--build-arg", f"UV_IMAGE={cfg['uv_image']}",
                "--build-arg", f"BASE={cfg['tools_base']}",
                "--build-arg", f"PYTHON={cfg['python']}",
                "--build-arg", f"SDK={cfg['sdk']}",
            ],
        )
    return name


def build_derived_image(instance: dict, cfg: dict) -> str:
    tools = build_tools_image(cfg)
    name = derived_image_name(instance, cfg)
    if _exists(name):
        return name
    inputs = _derived_inputs(instance, cfg, docker_exec)
    with tempfile.TemporaryDirectory() as td:
        ctx = Path(td)
        shutil.copy2(DERIVED_DOCKERFILE, ctx / "Dockerfile")
        shutil.copy2(SHIM, ctx / "python3")
        shutil.copy2(ENV_FILE, ctx / "env.sh")
        (ctx / "testbed_tools.txt").write_text("".join(f"{t}\n" for t in cfg["testbed_tools"]))
        _build(
            name,
            ctx,
            [
                "--build-arg", f"TOOLS={tools}",
                "--build-arg", f"BASE={swe.image_name(instance)}",
                "--label", f"selfcheck.inputs={json.dumps(inputs, sort_keys=True)}",
            ],
        )
    return name

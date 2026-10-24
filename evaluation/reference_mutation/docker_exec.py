import contextlib
import json
import os
import subprocess
import time
import tempfile
import uuid
from pathlib import Path

LABEL = "evaluation=1"


class DockerError(RuntimeError):
    pass


class DockerUnreachable(RuntimeError):
    pass


def _daemon_answers() -> bool:
    try:
        probe = subprocess.run(
            ["docker", "info"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30
        )
    except subprocess.TimeoutExpired:
        return False
    return probe.returncode == 0


def _recovered_after_failure() -> bool:
    # Docker Desktop Resource Saver pauses the VM after idle time and the first CLI calls during
    # unpause fail, so a failed call is only believed once the daemon answers.
    if _daemon_answers():
        return False
    deadline = time.monotonic() + float(os.environ.get("EVALUATION_DOCKER_WAIT_S", "60"))
    while time.monotonic() < deadline:
        time.sleep(2)
        if _daemon_answers():
            return True
    raise DockerUnreachable("docker daemon did not answer within EVALUATION_DOCKER_WAIT_S")


def _run(args, *, timeout=None, input_bytes=None):
    def once():
        return subprocess.run(
            ["docker", *args],
            input=input_bytes,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout,
        )

    proc = once()
    if proc.returncode != 0 and _recovered_after_failure():
        proc = once()
    return proc


class ImageMissing(RuntimeError):
    pass


def _docker_ok(args) -> subprocess.CompletedProcess | None:
    try:
        return subprocess.run(
            ["docker", *args], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=30
        )
    except subprocess.TimeoutExpired:
        return None


def _run_image(args, image, *, timeout=None):
    # While Docker Desktop's engine restarts after idle shutdown, `image ls` lists the image but
    # `image inspect <name>` and `run <name>` report "No such image" for 30-60 s. A name that
    # `image ls` does not list is genuinely missing and fails at once.
    proc = _run(args, timeout=timeout)
    if proc.returncode == 0 or b"No such image" not in proc.stdout:
        return proc
    listed = _docker_ok(["image", "ls", "-q", image])
    if listed is None or listed.returncode != 0 or not listed.stdout.strip():
        return proc
    deadline = time.monotonic() + float(os.environ.get("EVALUATION_DOCKER_WAIT_S", "60"))
    while time.monotonic() < deadline:
        time.sleep(2)
        probe = _docker_ok(["image", "inspect", "--format", "{{.Id}}", image])
        if probe is not None and probe.returncode == 0:
            return _run(args, timeout=timeout)
    raise DockerUnreachable(
        f"docker image {image} is listed but did not resolve within EVALUATION_DOCKER_WAIT_S"
    )


def image_id(image: str) -> str:
    try:
        proc = _run_image(["image", "inspect", "--format", "{{.Id}}", image], image, timeout=60)
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        raise DockerUnreachable(f"docker unavailable while inspecting image {image}") from exc
    text = proc.stdout.decode(errors="replace")
    if proc.returncode == 0:
        return text.strip()
    if "No such image" in text:
        raise ImageMissing(f"Docker image missing: {image}")
    raise DockerUnreachable(f"docker unreachable while inspecting image {image}: {text.strip()}")


def list_labeled() -> list[str]:
    proc = _run(["ps", "-aq", "--filter", f"label={LABEL}"], timeout=60)
    return proc.stdout.decode().split()


class Container:
    def __init__(self, cid: str):
        self.cid = cid

    def copy_in(self, local: str | Path, dest: str) -> None:
        proc = _run(["cp", str(local), f"{self.cid}:{dest}"], timeout=300)
        if proc.returncode != 0:
            raise DockerError(f"docker cp failed: {proc.stdout.decode(errors='replace')}")

    def write_text(self, dest: str, text: str) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "f"
            path.write_bytes(text.encode())
            self.copy_in(path, dest)

    def exec(
        self,
        argv: list[str],
        *,
        timeout: int | None = None,
        user: str | None = None,
        workdir: str | None = None,
    ) -> tuple[int | None, str, bool]:
        flags = []
        if user:
            flags += ["-u", user]
        if workdir:
            flags += ["-w", workdir]

        def once():
            proc = subprocess.Popen(
                ["docker", "exec", *flags, self.cid, *argv],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
            )
            try:
                out, _ = proc.communicate(timeout=timeout)
            except subprocess.TimeoutExpired:
                proc.kill()
                out, _ = proc.communicate()
                return None, out.decode(errors="replace"), True
            return proc.returncode, out.decode(errors="replace"), False

        result = once()
        if result[0] not in (0, None) and _recovered_after_failure():
            result = once()
        return result

    def read_bytes(self, src: str) -> bytes | None:
        with tempfile.TemporaryDirectory() as td:
            dest = Path(td) / "f"
            proc = _run(["cp", f"{self.cid}:{src}", str(dest)], timeout=300)
            if proc.returncode != 0 or not dest.is_file():
                return None
            return dest.read_bytes()

    def copy_out(self, src: str, local: str | Path) -> None:
        Path(local).mkdir(parents=True, exist_ok=True)
        proc = _run(["cp", f"{self.cid}:{src}", str(local)], timeout=300)
        if proc.returncode != 0:
            raise DockerError(f"docker cp failed: {proc.stdout.decode(errors='replace')}")

    def stop(self) -> None:
        proc = _run(["stop", "-t", "10", self.cid], timeout=120)
        if proc.returncode != 0:
            raise DockerError(f"docker stop failed: {proc.stdout.decode(errors='replace')}")

    def start(self) -> None:
        proc = _run(["start", self.cid], timeout=120)
        if proc.returncode != 0:
            raise DockerError(f"docker start failed: {proc.stdout.decode(errors='replace')}")

    def remove(self) -> None:
        _run(["rm", "-f", "-v", self.cid], timeout=120)


@contextlib.contextmanager
def container(image: str, *, network: bool = False):
    name = f"evaluation-{uuid.uuid4().hex[:16]}"
    args = ["run", "-d", "--pull", "never", "--name", name, "--label", LABEL]
    if not network:
        args += ["--network", "none"]
    args += ["--entrypoint", "sleep", image, "infinity"]
    try:
        proc = _run_image(args, image, timeout=300)
    except DockerUnreachable:
        _run(["rm", "-f", "-v", name], timeout=120)
        raise
    out = proc.stdout.decode(errors="replace").strip()
    if proc.returncode != 0:
        # A failed `run` can still leave a created container behind.
        _run(["rm", "-f", "-v", name], timeout=120)
        raise DockerError(f"docker run failed for {image}: {out}")
    c = Container(out.splitlines()[-1])
    try:
        yield c
    finally:
        c.remove()



def start_container(
    image: str,
    *,
    name: str,
    network: str,
    labels: dict,
    cpus,
    memory: str,
    mounts: list[str],
) -> Container:
    args = ["run", "-d", "--pull", "never", "--name", name]
    for key, value in labels.items():
        args += ["--label", f"{key}={value}"]
    args += ["--network", network, "--cpus", str(cpus), "--memory", memory]
    for mount in mounts:
        args += ["--mount", mount]
    args += ["--entrypoint", "sleep", image, "infinity"]
    try:
        proc = _run_image(args, image, timeout=300)
    except DockerUnreachable:
        _run(["rm", "-f", "-v", name], timeout=120)
        raise
    out = proc.stdout.decode(errors="replace").strip()
    if proc.returncode != 0:
        _run(["rm", "-f", "-v", name], timeout=120)
        raise DockerError(f"docker run failed for {image}: {out}")
    return Container(out.splitlines()[-1])


def container_exists(name: str) -> bool:
    return _run(["container", "inspect", name], timeout=60).returncode == 0


def network_exists(name: str) -> bool:
    return _run(["network", "inspect", name], timeout=60).returncode == 0


def ensure_network(name: str, internal: bool = True) -> None:
    if network_exists(name):
        return
    proc = _run(["network", "create", *(["--internal"] if internal else []), name], timeout=60)
    if proc.returncode != 0:
        raise DockerError(f"docker network create failed: {proc.stdout.decode(errors='replace')}")


def container_status(name: str) -> dict | None:
    proc = _run(["container", "inspect", "--format", "{{json .}}", name], timeout=60)
    if proc.returncode != 0:
        return None
    info = json.loads(proc.stdout.decode(errors="replace"))
    return {
        "running": bool(info["State"]["Running"]),
        "labels": dict(info["Config"].get("Labels") or {}),
    }


def remove_container(name: str) -> None:
    _run(["rm", "-f", "-v", name], timeout=120)


def start_proxy(
    image: str, *, name: str, networks: list[str], labels: dict, conf_text: str
) -> Container:
    # The squid image reads /etc/squid/squid.conf and must attach to two networks, so it cannot
    # use start_container (single network, `sleep infinity` entrypoint, verbatim mounts only).
    args = ["create", "--pull", "never", "--name", name]
    for key, value in labels.items():
        args += ["--label", f"{key}={value}"]
    args += ["--network", networks[0], image]
    proc = _run_image(args, image, timeout=300)
    out = proc.stdout.decode(errors="replace").strip()
    if proc.returncode != 0:
        _run(["rm", "-f", "-v", name], timeout=120)
        raise DockerError(f"docker create failed for {image}: {out}")
    c = Container(name)
    try:
        c.write_text("/etc/squid/squid.conf", conf_text)
        for net in networks[1:]:
            proc = _run(["network", "connect", net, name], timeout=60)
            if proc.returncode != 0:
                raise DockerError(f"docker network connect failed: {proc.stdout.decode(errors='replace')}")
        c.start()
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            status = container_status(name)
            if status and status["running"]:
                time.sleep(1)
                status = container_status(name)
                if status and status["running"]:
                    return c
            time.sleep(1)
        logs = _run(["logs", "--tail", "20", name], timeout=60).stdout.decode(errors="replace")
        raise DockerError(f"proxy {name} did not stay running: {logs}")
    except DockerError:
        c.remove()
        raise


def build(context_dir, tag: str, *, timeout: int) -> tuple[int, str]:
    try:
        proc = subprocess.run(
            ["docker", "build", "-t", tag, str(context_dir)],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        return 124, (exc.stdout or b"").decode(errors="replace") + f"\nbuild timed out after {timeout}s"
    return proc.returncode, proc.stdout.decode(errors="replace")

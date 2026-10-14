import json
import os
import secrets
import shutil
import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from selfcheck import docker_exec, images
from selfcheck.tests import agent_fakes as F
from selfcheck.tests.helpers import PYTEST_ID, docker_only, make_shim, pilot, require_image, wait_for_docker

TEST_LABEL_KEY = "selfcheck.agenttest"
BAD_DIRECTIVE = "unknown_directive_xyz"


def agent_cfg():
    return json.loads((F.ROOT / "selfcheck" / "config.json").read_text(encoding="utf-8"))["agent"]


def docker(*args, timeout=300):
    return subprocess.run(["docker", *args], capture_output=True, text=True, timeout=timeout)


def force_remove(name):
    docker("rm", "-f", name)


def remove_network(name):
    docker("network", "rm", name)


def names_matching(name):
    listed = docker("ps", "-a", "--filter", "name=^%s$" % name, "--format", "{{.Names}}")
    return listed.stdout.split()


@docker_only
class HostDockerSeamTests(unittest.TestCase):
    """VO19: the real docker_exec additions, on the pilot instance's agent image.

    The nonroot user (UID 1000) exists only in the derived agent image, so the containers here
    are started from it; it is built from the pilot instance image when absent.
    """

    @classmethod
    def setUpClass(cls):
        wait_for_docker()
        cls.row = pilot(PYTEST_ID)
        require_image(cls.row)
        cls.cfg = agent_cfg()
        images.build_tools_image(cls.cfg)
        cls.image = images.build_derived_image(cls.row, cls.cfg)

    def labels(self, **extra):
        return {TEST_LABEL_KEY: "1", **extra}

    def start(self, **over):
        name = "selfcheck-seam-%s" % secrets.token_hex(6)
        self.addCleanup(force_remove, name)
        kwargs = dict(
            name=name, network="bridge", labels=self.labels(), cpus=1, memory="512m", mounts=[],
        )
        kwargs.update(over)
        container = docker_exec.start_container(self.image, **kwargs)
        return container, kwargs["name"]

    def inspect(self, name):
        result = docker("inspect", name)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)[0]

    def test_vo19_dx1_a_timed_out_exec_returns_none_output_true_within_the_bound(self):
        container, _ = self.start()
        begun = time.monotonic()
        code, output, timed_out = container.exec(["sleep", "30"], timeout=2)
        elapsed = time.monotonic() - begun
        self.assertIsNone(code)
        self.assertIsInstance(output, str)
        self.assertIs(timed_out, True)
        self.assertLess(elapsed, 15)
        code, output, timed_out = container.exec(["echo", "still-alive"], timeout=60)
        self.assertEqual((code, output.strip(), timed_out), (0, "still-alive", False))

    def test_vo19_dx2_exec_with_user_and_workdir_runs_as_uid_1000_in_testbed(self):
        container, _ = self.start()
        code, output, timed_out = container.exec(["sh", "-c", "id -u; pwd"], user="nonroot", workdir="/testbed", timeout=60)
        self.assertEqual((code, timed_out), (0, False))
        self.assertEqual(output.split(), ["1000", "/testbed"])
        code, output, _ = container.exec(["pwd"], workdir="/tmp", timeout=60)
        self.assertEqual((code, output.strip()), (0, "/tmp"))

    def test_vo19_dx3_stop_and_start_toggle_the_status_and_keep_the_files(self):
        labels = self.labels(**{"selfcheck.seam": "dx3"})
        container, name = self.start(labels=labels)
        container.write_text("/tmp/seam-marker", "kept across stop")
        running = docker_exec.container_status(name)
        self.assertEqual(set(running), {"running", "labels"})
        self.assertIs(running["running"], True)
        self.assertEqual({k: running["labels"].get(k) for k in labels}, labels)

        container.stop()
        stopped = docker_exec.container_status(name)
        self.assertEqual(set(stopped), {"running", "labels"})
        self.assertIs(stopped["running"], False)
        self.assertEqual({k: stopped["labels"].get(k) for k in labels}, labels)
        self.assertEqual(self.inspect(name)["State"]["Running"], False)

        container.start()
        again = docker_exec.container_status(name)
        self.assertIs(again["running"], True)
        self.assertEqual(container.read_bytes("/tmp/seam-marker"), b"kept across stop")
        self.assertEqual(container.exec(["true"], timeout=60)[0], 0)

    def test_vo19_dx4_container_exists_follows_remove_container(self):
        _, name = self.start()
        self.assertIs(docker_exec.container_exists(name), True)
        self.assertIs(docker_exec.container_exists(name + "-absent"), False)
        docker_exec.remove_container(name)
        self.assertIs(docker_exec.container_exists(name), False)
        self.assertEqual(names_matching(name), [])
        self.assertIsNone(docker_exec.container_status(name))

    def test_vo19_dx5_ensure_network_creates_an_internal_network_and_is_idempotent(self):
        network = "selfcheck-seam-net-%s" % secrets.token_hex(6)
        self.addCleanup(remove_network, network)
        self.assertIs(docker_exec.network_exists(network), False)
        docker_exec.ensure_network(network)
        self.assertIs(docker_exec.network_exists(network), True)
        first = docker("network", "inspect", "--format", "{{.Internal}} {{.Id}}", network)
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertTrue(first.stdout.startswith("true "), first.stdout)
        docker_exec.ensure_network(network, internal=True)
        second = docker("network", "inspect", "--format", "{{.Internal}} {{.Id}}", network)
        self.assertEqual(second.stdout, first.stdout)
        self.assertIs(docker_exec.network_exists(network), True)

    def test_vo19_dx6_read_bytes_and_copy_out(self):
        container, _ = self.start()
        code, output, _ = container.exec(
            ["sh", "-c", "mkdir -p /tmp/outdir/sub && printf alpha > /tmp/outdir/a.txt && printf 'be\\000ta' > /tmp/outdir/sub/b.bin"],
            timeout=60,
        )
        self.assertEqual(code, 0, output)
        self.assertEqual(container.read_bytes("/tmp/outdir/a.txt"), b"alpha")
        self.assertEqual(container.read_bytes("/tmp/outdir/sub/b.bin"), b"be\x00ta")
        self.assertIsNone(container.read_bytes("/tmp/outdir/missing.txt"))
        local = Path(tempfile.mkdtemp(prefix="seam-copyout-"))
        self.addCleanup(shutil.rmtree, local, True)
        container.copy_out("/tmp/outdir/.", str(local))
        self.assertEqual((local / "a.txt").read_bytes(), b"alpha")
        self.assertEqual((local / "sub" / "b.bin").read_bytes(), b"be\x00ta")
        self.assertFalse((local / "outdir").exists(), "the directory contents, not the directory, are copied")
        with self.assertRaises(docker_exec.DockerError):
            container.copy_out("/tmp/no-such-dir/.", str(local / "nowhere"))

    def test_vo19_dx7_processes_lists_nonroot_processes_with_exact_keys(self):
        container, _ = self.start()
        marker = "seamproc%s" % secrets.token_hex(6)
        code, output, _ = container.exec(
            ["sh", "-c", "setsid nohup sh -c 'sleep 3600 # %s' >/dev/null 2>&1 < /dev/null &" % marker],
            user="nonroot", workdir="/testbed", timeout=60,
        )
        self.assertEqual(code, 0, output)
        found = []
        deadline = time.monotonic() + 15
        while not found and time.monotonic() < deadline:
            listed = container.processes()
            found = [p for p in listed if marker in p["cmd"]]
            if not found:
                time.sleep(0.5)
        self.assertTrue(found, "the nonroot process was not listed")
        for entry in listed:
            self.assertEqual(set(entry), {"pid", "uid", "cmd"})
            self.assertIsInstance(entry["pid"], int)
            self.assertIsInstance(entry["uid"], int)
            self.assertIsInstance(entry["cmd"], str)
        self.assertTrue(all(p["uid"] == 1000 for p in found))
        self.assertTrue([p for p in listed if p["uid"] == 0 and "sleep infinity" in p["cmd"]])

    def test_vo19_dx8_start_container_with_a_missing_image_raises_and_leaves_no_container(self):
        name = "selfcheck-seam-%s" % secrets.token_hex(6)
        self.addCleanup(force_remove, name)
        missing = "selfcheck-seam-no-such-image:%s" % secrets.token_hex(6)
        with self.assertRaises(docker_exec.DockerError):
            docker_exec.start_container(
                missing, name=name, network="bridge", labels=self.labels(), cpus=1, memory="512m", mounts=[],
            )
        self.assertIs(docker_exec.container_exists(name), False)
        self.assertEqual(names_matching(name), [])

    def test_vo19_dx9_labels_cpus_and_memory_appear_in_inspect(self):
        labels = self.labels(**{"selfcheck.agent": "seam-dx9", "selfcheck.seam": "dx9"})
        _, name = self.start(labels=labels, cpus=2, memory="512m")
        info = self.inspect(name)
        for key, value in labels.items():
            self.assertEqual(info["Config"]["Labels"].get(key), value, key)
        self.assertEqual(info["HostConfig"]["NanoCpus"], 2 * 10**9)
        self.assertEqual(info["HostConfig"]["Memory"], 512 * 1024 * 1024)
        self.assertEqual(info["HostConfig"]["NetworkMode"], "bridge")
        self.assertEqual(info["Config"]["Entrypoint"], ["sleep"])
        self.assertEqual(info["Config"]["Cmd"], ["infinity"])
        self.assertEqual(info["Mounts"], [])

    def test_vo19_dx10_a_proxy_whose_squid_exits_raises_with_a_log_line_and_leaves_no_container(self):
        proxy_image = self.cfg["proxy_image"]
        if docker("image", "inspect", proxy_image).returncode != 0:
            pulled = docker("pull", proxy_image, timeout=600)
            self.assertEqual(pulled.returncode, 0, pulled.stderr)
        name = "selfcheck-seam-proxy-%s" % secrets.token_hex(6)
        self.addCleanup(force_remove, name)
        conf = "%s foo\n" % BAD_DIRECTIVE
        oracle = docker(
            "run", "--rm", "--entrypoint", "sh", proxy_image, "-c",
            "printf '%%s' '%s' > /tmp/bad.conf; squid -N -f /tmp/bad.conf 2>&1 | head -40" % conf.strip(),
            timeout=120,
        )
        self.assertIn(BAD_DIRECTIVE, oracle.stdout, "squid itself must report the bad directive in its log")
        with self.assertRaises(docker_exec.DockerError) as caught:
            docker_exec.start_proxy(
                proxy_image, name=name, networks=["bridge"], labels=self.labels(), conf_text=conf,
            )
        self.assertIn(BAD_DIRECTIVE, str(caught.exception))
        self.assertIs(docker_exec.container_exists(name), False)
        self.assertEqual(names_matching(name), [])

    def test_vo19_dx11_a_failing_container_inspect_during_the_proxy_wait_raises_docker_error_and_leaves_no_container(self):
        proxy_image = self.cfg["proxy_image"]
        if docker("image", "inspect", proxy_image).returncode != 0:
            pulled = docker("pull", proxy_image, timeout=600)
            self.assertEqual(pulled.returncode, 0, pulled.stderr)
        name = "selfcheck-seam-proxy-%s" % secrets.token_hex(6)
        self.addCleanup(force_remove, name)
        conf = "http_port 3128\nhttp_access deny all\n"
        shim_dir = tempfile.mkdtemp(prefix="seam-shim-")
        self.addCleanup(shutil.rmtree, shim_dir, True)
        body = (
            'case " $* " in\n'
            '  *" container inspect "*) for a in "$@"; do [ "$a" = "%s" ] && exit 1; done;;\n'
            "esac\n"
            'exec @REAL@ "$@"\n' % name
        )
        make_shim(shim_dir, body)
        with mock.patch.dict(os.environ, {"PATH": shim_dir + os.pathsep + os.environ["PATH"]}):
            try:
                docker_exec.start_proxy(
                    proxy_image, name=name, networks=["bridge"], labels=self.labels(), conf_text=conf,
                )
            except BaseException as exc:
                raised = exc
            else:
                raised = None
        self.assertIsNotNone(raised, "start_proxy must raise while container inspect fails")
        self.assertIs(type(raised), docker_exec.DockerError, repr(raised))
        self.assertEqual(names_matching(name), [])


if __name__ == "__main__":
    unittest.main()

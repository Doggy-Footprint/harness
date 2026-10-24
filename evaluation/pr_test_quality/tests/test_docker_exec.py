import json
import os
import stat
import sys
import unittest
from pathlib import Path
from unittest import mock

from evaluation.pr_test_quality import docker_exec as de
from evaluation.pr_test_quality.tests.docker_shim import SHIM
from evaluation.pr_test_quality.tests.fakes import TmpCase


class Shimmed(TmpCase):
    def setUp(self):
        super().setUp()
        self.shim_dir = self.tmp / "shim"
        self.shim_dir.mkdir()
        bin_dir = self.tmp / "bin"
        bin_dir.mkdir()
        path = bin_dir / "docker"
        path.write_text(SHIM % {"python": sys.executable}, encoding="utf-8")
        path.chmod(path.stat().st_mode | stat.S_IXUSR)
        patcher = mock.patch.dict(os.environ, {"PATH": "%s:%s" % (bin_dir, os.environ["PATH"]),
                                               "SHIM_DIR": str(self.shim_dir)})
        patcher.start()
        self.addCleanup(patcher.stop)

    def state(self):
        path = self.shim_dir / "state.json"
        return json.loads(path.read_text()) if path.exists() else {"containers": {}, "networks": [], "log": []}

    def start(self, name="n1", **kw):
        return de.start_container("img:1", name=name, network=kw.pop("network", "net"), labels=kw.pop("labels", {"k": "v"}),
                                  cpus=2, memory="4g", mounts=kw.pop("mounts", []))


class Images(Shimmed):
    def test_O12_image_id_returns_the_engine_id(self):
        out = de.image_id("img:1")
        self.assertTrue(out.startswith("sha256:"))
        self.assertNotEqual(out, de.image_id("img:2"))
        self.assertEqual(out, out.strip())

    def test_O12_missing_image_raises_image_missing(self):
        (self.shim_dir / "missing").write_text("gone:1")
        with self.assertRaises(de.ImageMissing):
            de.image_id("gone:1")

    def test_O12_unreachable_docker_raises_docker_unreachable(self):
        with mock.patch.dict(os.environ, {"PATH": str(self.tmp / "nowhere")}):
            with self.assertRaises(de.DockerUnreachable):
                de.image_id("img:1")

    def test_O12_errors_are_runtime_errors(self):
        for cls in (de.DockerError, de.DockerUnreachable, de.ImageMissing):
            self.assertTrue(issubclass(cls, RuntimeError))

    def test_O12_build_returns_exit_code_and_log(self):
        ctx = self.tmp / "ctx"
        ctx.mkdir()
        code, log = de.build(ctx, "tag:1", timeout=30)
        self.assertEqual(code, 0)
        self.assertIn("built ok", log)
        (ctx / "FAIL").write_text("x")
        code, log = de.build(ctx, "tag:1", timeout=30)
        self.assertNotEqual(code, 0)
        self.assertIn("boom: build failed", log)


class Networks(Shimmed):
    def test_O12_ensure_network_is_idempotent_and_internal_by_default(self):
        de.ensure_network("net")
        de.ensure_network("net")
        creates = [a for a in self.state()["log"] if a[:2] == ["network", "create"]]
        self.assertEqual(len(creates), 1)
        self.assertIn("--internal", creates[0])

    def test_O12_ensure_network_external(self):
        de.ensure_network("open", internal=False)
        creates = [a for a in self.state()["log"] if a[:2] == ["network", "create"]]
        self.assertNotIn("--internal", creates[0])


class Containers(Shimmed):
    def test_O12_start_container_exists_then_remove(self):
        c = self.start()
        self.assertIsInstance(c, de.Container)
        self.assertTrue(de.container_exists("n1"))
        de.remove_container("n1")
        self.assertFalse(de.container_exists("n1"))
        de.remove_container("n1")

    def test_O12_start_container_passes_limits_labels_network_and_mounts(self):
        self.start(mounts=["type=bind,src=/x,dst=/y,readonly"], labels={"evaluation": "1"})
        run = [a for a in self.state()["log"] if a[0] == "run"][0]
        text = " ".join(run)
        for needle in ("--cpus 2", "--memory 4g", "--network net", "--label evaluation=1",
                       "--mount type=bind,src=/x,dst=/y,readonly"):
            self.assertIn(needle, text)

    def test_O12_exec_returns_code_output_and_timeout_flag(self):
        c = self.start()
        self.assertEqual(c.exec(["echo", "hi"]), (0, "hi\n", False))
        code, out, timed_out = c.exec(["sh", "-c", "echo bad; exit 3"])
        self.assertEqual((code, timed_out), (3, False))
        self.assertIn("bad", out)

    def test_O12_exec_timeout(self):
        c = self.start()
        code, out, timed_out = c.exec(["sleep", "5"], timeout=1)
        self.assertEqual((code, timed_out), (None, True))

    def test_O12_exec_user_and_workdir_flags(self):
        c = self.start()
        c.exec(["true"], user="nonroot", workdir="/testbed")
        ex = [a for a in self.state()["log"] if a[0] == "exec"][-1]
        self.assertEqual(ex[1:5], ["-u", "nonroot", "-w", "/testbed"])

    def test_O12_write_text_read_bytes_round_trip(self):
        c = self.start()
        c.write_text("/a/b.txt", "héllo\n")
        self.assertEqual(c.read_bytes("/a/b.txt"), "héllo\n".encode())
        self.assertIsNone(c.read_bytes("/a/missing.txt"))

    def test_O12_copy_in_and_copy_out(self):
        c = self.start()
        src = self.tmp / "f.txt"
        src.write_text("payload")
        c.copy_in(src, "/data/f.txt")
        self.assertEqual(c.read_bytes("/data/f.txt"), b"payload")
        out = self.tmp / "out"
        c.copy_out("/data/.", out)
        self.assertEqual((out / "f.txt").read_text(), "payload")

    def test_O12_start_stop_remove_pass_through(self):
        c = self.start()
        c.stop()
        self.assertFalse(self.state()["containers"]["n1"]["running"])
        c.start()
        self.assertTrue(self.state()["containers"]["n1"]["running"])
        c.remove()
        self.assertFalse(de.container_exists("n1"))

    def test_O12_container_context_manager_removes_on_exit(self):
        with de.container("img:1", network=False) as c:
            self.assertEqual(c.exec(["echo", "x"])[0], 0)
            self.assertEqual(len(self.state()["containers"]), 1)
            run = [a for a in self.state()["log"] if a[0] == "run"][0]
            self.assertIn("none", " ".join(run))
        self.assertEqual(self.state()["containers"], {})

    def test_O12_container_context_manager_removes_even_on_error(self):
        with self.assertRaises(ValueError):
            with de.container("img:1"):
                raise ValueError("boom")
        self.assertEqual(self.state()["containers"], {})

    def test_O12_container_network_true_uses_the_default_network(self):
        with de.container("img:1", network=True):
            run = [a for a in self.state()["log"] if a[0] == "run"][0]
            self.assertNotIn("none", " ".join(run))

    def test_O12_start_proxy_installs_conf_and_runs(self):
        px = de.start_proxy("img:1", name="px", networks=["net", "net2"], labels={"k": "v"}, conf_text="http_port 3128\n")
        self.assertEqual(px.read_bytes("/etc/squid/squid.conf"), b"http_port 3128\n")
        self.assertTrue(self.state()["containers"]["px"]["running"])
        connects = [a for a in self.state()["log"] if a[:2] == ["network", "connect"]]
        self.assertTrue(any("net2" in a for a in connects))


if __name__ == "__main__":
    unittest.main()

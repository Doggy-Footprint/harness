import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from selfcheck import swe
from selfcheck.tests import agent_fakes as F
from selfcheck.tests.helpers import PYTEST_ID, pilot

BUILD_TARGET = "swebench.harness.docker_build.build_instance_images"


def configured_cache_dir():
    return json.loads((F.ROOT / "selfcheck" / "config.json").read_text(encoding="utf-8"))["cache_dir"]


class BuildImagesWorkdirTests(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="swebuild-home-")
        self.elsewhere = tempfile.mkdtemp(prefix="swebuild-prev-")
        for path in (self.home, self.elsewhere):
            self.addCleanup(shutil.rmtree, path, True)
        original = os.getcwd()
        self.addCleanup(os.chdir, original)
        os.chdir(self.elsewhere)
        environ = mock.patch.dict(os.environ, {"HOME": self.home})
        environ.start()
        self.addCleanup(environ.stop)
        self.seen = []
        self.row = pilot(PYTEST_ID)

    def build(self, error=None, **kwargs):
        def fake_build(*args, **kw):
            self.seen.append(os.getcwd())
            if error is not None:
                raise error
            return [], []

        with mock.patch(BUILD_TARGET, side_effect=fake_build), mock.patch("docker.from_env"):
            return swe.build_images([self.row], **kwargs)

    def test_vo20_g1_the_default_workdir_is_the_expanded_cache_dir_plus_build_and_is_created(self):
        configured = configured_cache_dir()
        self.assertTrue(configured.startswith("~/"), configured)
        expected = Path(self.home) / configured[2:] / "build"
        self.assertFalse(expected.exists())
        self.build()
        self.assertEqual(len(self.seen), 1)
        self.assertEqual(os.path.realpath(self.seen[0]), os.path.realpath(expected))
        self.assertTrue(expected.is_dir())

    def test_vo20_g2_an_explicit_workdir_is_used(self):
        explicit = Path(tempfile.mkdtemp(prefix="swebuild-explicit-"))
        self.addCleanup(shutil.rmtree, explicit, True)
        self.build(workdir=str(explicit))
        self.assertEqual([os.path.realpath(p) for p in self.seen], [os.path.realpath(explicit)])
        self.seen.clear()
        self.build(workdir=explicit)
        self.assertEqual([os.path.realpath(p) for p in self.seen], [os.path.realpath(explicit)])

    def test_vo20_g3_the_previous_working_directory_is_restored_after_a_return(self):
        before = os.path.realpath(os.getcwd())
        self.build()
        self.assertNotEqual(os.path.realpath(self.seen[0]), before)
        self.assertEqual(os.path.realpath(os.getcwd()), before)

    def test_vo20_g3_the_previous_working_directory_is_restored_after_a_raise(self):
        before = os.path.realpath(os.getcwd())
        with self.assertRaises(RuntimeError):
            self.build(error=RuntimeError("build exploded"))
        self.assertEqual(len(self.seen), 1)
        self.assertNotEqual(os.path.realpath(self.seen[0]), before)
        self.assertEqual(os.path.realpath(os.getcwd()), before)
        explicit = Path(tempfile.mkdtemp(prefix="swebuild-explicit-"))
        self.addCleanup(shutil.rmtree, explicit, True)
        with self.assertRaises(RuntimeError):
            self.build(error=RuntimeError("again"), workdir=str(explicit))
        self.assertEqual(os.path.realpath(os.getcwd()), before)


if __name__ == "__main__":
    unittest.main()

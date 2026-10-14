import re
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from selfcheck import images
from selfcheck.tests import agent_fakes as F

TOOLS_BYTES = b"FROM scratch\n# tools dockerfile\n" + b"x" * 300 + b"\nEND\n"
DERIVED_BYTES = b"ARG TOOLS\nARG BASE\nFROM ${BASE}\n# derived dockerfile\n" + b"y" * 300 + b"\nEND\n"
SHIM_BYTES = b"#!/bin/sh\nexec true\n" + b"z" * 200 + b"\n"
ENV_BYTES = b"# env.sh\nexport A=1\n" + b"w" * 200 + b"\n"
INSTANCE = {"instance_id": "Mixed__Case-12"}


class ImageIds:
    """Fake `docker` object: image ids by role, ImageMissing for anything else."""

    ImageMissing = F.ImageMissing

    def __init__(self, tools_id="sha256:tools-1", instance_id="sha256:instance-1"):
        self.tools_id = tools_id
        self.instance_id = instance_id
        self.asked = []

    def image_id(self, image):
        self.asked.append(image)
        if image.startswith("selfcheck-tools:"):
            return self.tools_id
        if image.lower().startswith("sweb.eval.arm64.") and image.lower().endswith(":latest"):
            return self.instance_id
        raise F.ImageMissing(image)


class FileConstantsCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="images-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.counter = 0

    def file(self, data):
        self.counter += 1
        path = self.tmp / ("f%d" % self.counter)
        path.write_bytes(data)
        return path

    def patch_files(self, **data):
        names = {
            "tools": "TOOLS_DOCKERFILE", "derived": "DERIVED_DOCKERFILE", "shim": "SHIM", "env": "ENV_FILE",
        }
        defaults = {"tools": TOOLS_BYTES, "derived": DERIVED_BYTES, "shim": SHIM_BYTES, "env": ENV_BYTES}
        defaults.update(data)
        for key, attr in names.items():
            patcher = mock.patch.object(images, attr, self.file(defaults[key]))
            patcher.start()
            self.addCleanup(patcher.stop)


class ToolsImageNameTests(FileConstantsCase):
    def name(self, cfg=None, **files):
        with mock.patch.object(images, "TOOLS_DOCKERFILE", self.file(files.get("tools", TOOLS_BYTES))):
            return images.tools_image_name(cfg or F.cfg_copy())

    def test_vo18_im1_the_name_has_the_documented_shape_and_is_stable_for_equal_inputs(self):
        first = self.name()
        self.assertRegex(first, r"^selfcheck-tools:[0-9a-f]{12}$")
        self.assertEqual(self.name(), first)
        self.assertEqual(self.name(F.cfg_copy()), first, "equal bytes in another file give the same name")

    def test_vo18_im1_each_hash_input_changes_the_name(self):
        base = self.name()
        changes = {
            "sdk": "claude-agent-sdk==0.2.166",
            "uv_image": "ghcr.io/astral-sh/uv:0.6.6",
            "tools_base": "ubuntu@sha256:" + "0" * 64,
            "python": "3.13",
        }
        seen = {base}
        for key, value in changes.items():
            with self.subTest(key):
                changed = self.name(F.cfg_copy(**{key: value}))
                self.assertRegex(changed, r"^selfcheck-tools:[0-9a-f]{12}$")
                self.assertNotEqual(changed, base)
                seen.add(changed)
        self.assertEqual(len(seen), 5, "different inputs must not collide")

    def test_vo18_im1_the_tools_dockerfile_bytes_change_the_name(self):
        base = self.name()
        for label, data in (
            ("last byte", TOOLS_BYTES[:-1] + b"X"),
            ("first byte", b"X" + TOOLS_BYTES[1:]),
            ("appended newline", TOOLS_BYTES + b"\n"),
        ):
            with self.subTest(label):
                self.assertNotEqual(self.name(tools=data), base)

    def test_vo18_im1_unrelated_configuration_keys_do_not_change_the_name(self):
        base = self.name()
        unrelated = F.cfg_copy(cpus=2, memory="1g", model="claude-haiku-5-5", effort="high", testbed_tools=["other"])
        self.assertEqual(self.name(unrelated), base)


class DerivedImageNameTests(FileConstantsCase):
    def setUp(self):
        super().setUp()
        self.patch_files()
        self.cfg = F.cfg_copy()

    def name(self, docker=None, cfg=None):
        return images.derived_image_name(INSTANCE, cfg or self.cfg, docker=docker or ImageIds())

    def swap(self, attr, data):
        return mock.patch.object(images, attr, self.file(data))

    def test_vo18_im2_the_name_has_the_documented_shape_and_is_stable_for_equal_inputs(self):
        first = self.name()
        self.assertRegex(first, r"^selfcheck-agent\.arm64\.mixed__case-12:[0-9a-f]{12}$")
        self.assertEqual(self.name(), first)
        with self.swap("DERIVED_DOCKERFILE", DERIVED_BYTES), self.swap("SHIM", SHIM_BYTES), self.swap("ENV_FILE", ENV_BYTES):
            self.assertEqual(self.name(), first, "equal bytes in other files give the same name")
        self.assertEqual(self.name(cfg=F.cfg_copy(testbed_tools=list(self.cfg["testbed_tools"]))), first)

    def test_vo18_im2_each_hash_input_changes_the_name(self):
        base = self.name()
        names = {base}
        variants = {
            "tools image id": lambda: self.name(ImageIds(tools_id="sha256:tools-2")),
            "instance image id": lambda: self.name(ImageIds(instance_id="sha256:instance-2")),
            "testbed_tools extended": lambda: self.name(cfg=F.cfg_copy(testbed_tools=self.cfg["testbed_tools"] + ["extra"])),
            "testbed_tools shortened": lambda: self.name(cfg=F.cfg_copy(testbed_tools=self.cfg["testbed_tools"][:-1])),
            "testbed_tools version": lambda: self.name(cfg=F.cfg_copy(testbed_tools=["mutmut==2.5.2"] + self.cfg["testbed_tools"][1:])),
        }
        for attr, data in (
            ("DERIVED_DOCKERFILE", DERIVED_BYTES[:-1] + b"X"),
            ("SHIM", SHIM_BYTES[:-1] + b"X"),
            ("ENV_FILE", b"X" + ENV_BYTES[1:]),
        ):
            def build(attr=attr, data=data):
                with self.swap(attr, data):
                    return self.name()
            variants[attr] = build
        for label, make in variants.items():
            with self.subTest(label):
                changed = make()
                self.assertRegex(changed, r"^selfcheck-agent\.arm64\.mixed__case-12:[0-9a-f]{12}$")
                self.assertNotEqual(changed, base)
                names.add(changed)
        self.assertEqual(len(names), len(variants) + 1, "every single-input change gives its own name")

    def test_vo18_im2_the_name_follows_the_instance_id_and_ignores_unrelated_keys(self):
        base = self.name()
        other = images.derived_image_name({"instance_id": "Other__Repo-7"}, self.cfg, docker=ImageIds())
        self.assertRegex(other, r"^selfcheck-agent\.arm64\.other__repo-7:[0-9a-f]{12}$")
        unrelated = F.cfg_copy(cpus=2, memory="1g", model="claude-haiku-5-5", effort="high")
        self.assertEqual(self.name(cfg=unrelated), base)


if __name__ == "__main__":
    unittest.main()

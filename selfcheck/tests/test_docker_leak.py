import copy
import os
import subprocess
import tempfile
import unittest
from unittest import mock
from pathlib import Path

from selfcheck import validate
from selfcheck.tests.helpers import FakeEvaluate, eval_result, make_shim, DJANGO_ID, PYTEST_ID, SYMPY_ID, clear_labeled_containers, docker_only, labeled_containers, pilot, require_image

GOLD_SRC_PATH = "src/_pytest/reports.py"
LEAK_KEYS = {"ok", "future_commits", "future_tags", "gold_blobs_present", "gold_copies"}


def docker(*args, **kwargs):
    return subprocess.run(["docker", *args], capture_output=True, text=True, **kwargs)


def original_user(tag):
    return docker("image", "inspect", "--format", "{{.Config.User}}", tag).stdout.strip()


@docker_only
class PilotLeakTests(unittest.TestCase):
    def test_vo8_l1_pilot_images_are_clean(self):
        for instance_id in (PYTEST_ID, DJANGO_ID, SYMPY_ID):
            with self.subTest(instance_id=instance_id):
                row = pilot(instance_id)
                require_image(row)
                clear_labeled_containers()
                result = validate.leak_check(row)
                self.assertEqual(set(result), LEAK_KEYS)
                self.assertEqual(
                    result,
                    {"ok": True, "future_commits": 0, "future_tags": [], "gold_blobs_present": [], "gold_copies": []},
                )
                self.assertEqual(labeled_containers(), [])


@docker_only
class NetworkIsolationTests(unittest.TestCase):
    def test_vo8_l7_leak_check_container_is_started_without_networking(self):
        row = pilot(PYTEST_ID)
        require_image(row)
        clear_labeled_containers()
        with tempfile.TemporaryDirectory() as directory:
            log = os.path.join(directory, "calls.log")
            make_shim(directory, 'echo "$*" >> "%s"\nexec @REAL@ "$@"\n' % log)
            with mock.patch.dict(os.environ, {"PATH": directory + os.pathsep + os.environ["PATH"]}):
                validate.leak_check(row)
            with open(log, encoding="utf-8") as handle:
                runs = [line for line in handle.read().splitlines() if line.startswith("run ")]
        self.assertTrue(runs, "no docker run invocation recorded")
        for line in runs:
            self.assertTrue("--network none" in line or "--network=none" in line, line)
        self.assertEqual(labeled_containers(), [])


def unappliable_copy(row):
    altered = copy.deepcopy(row)
    marker = "\n import py\n"
    assert altered["patch"].count(marker) == 1
    altered["patch"] = altered["patch"].replace(marker, "\n import py_altered_context\n")
    return altered


@docker_only
class LeakCheckFailureTests(unittest.TestCase):
    def setUp(self):
        self.pilot = pilot(PYTEST_ID)
        require_image(self.pilot)
        clear_labeled_containers()

    def test_vo8_l8_gold_patch_not_applying_to_base_raises_with_instance_id(self):
        row = unappliable_copy(self.pilot)
        with self.assertRaises(RuntimeError) as caught:
            validate.leak_check(row)
        self.assertIn(row["instance_id"], str(caught.exception))
        self.assertEqual(labeled_containers(), [])

    def test_vo8_l9_validate_instance_records_the_real_leak_failure_as_reason_leak(self):
        row = unappliable_copy(self.pilot)
        failing = set(row["FAIL_TO_PASS"])

        def respond(instance, src_diff, test_patch, **kwargs):
            status = {name: "PASSED" for name in row["FAIL_TO_PASS"] + row["PASS_TO_PASS"]}
            if src_diff == "":
                status = {name: ("FAILED" if name in failing else "PASSED") for name in status}
            return eval_result(status)

        result = validate.validate_instance(row, repeats=1, evaluate_fn=FakeEvaluate(respond))
        self.assertIs(result["valid"], False)
        self.assertEqual(result["reasons"], ["leak"])
        self.assertIs(result["leak"]["ok"], False)
        self.assertIn(row["instance_id"], result["leak"]["error"])
        self.assertEqual(labeled_containers(), [])

    def test_vo8_l10_leak_script_output_without_future_commits_line_raises_with_instance_id(self):
        row = copy.deepcopy(self.pilot)
        with tempfile.TemporaryDirectory() as directory:
            log = os.path.join(directory, "intercepted.log")
            body = (
                'last=""\nfor a in "$@"; do last="$a"; done\n'
                'if [ "$1" = "exec" ] && [ "$last" = "%s" ]; then\n'
                '  echo intercepted >> "%s"\n  echo "no future commits line here"\n  exit 0\nfi\n'
                'exec @REAL@ "$@"\n' % (row["base_commit"], log)
            )
            make_shim(directory, body)
            with mock.patch.dict(os.environ, {"PATH": directory + os.pathsep + os.environ["PATH"]}):
                with self.assertRaises(RuntimeError) as caught:
                    validate.leak_check(row)
            self.assertTrue(os.path.exists(log), "shim did not intercept the leak script exec")
            with open(log, encoding="utf-8") as handle:
                self.assertIn("intercepted", handle.read())
        self.assertIn(row["instance_id"], str(caught.exception))
        self.assertEqual(labeled_containers(), [])


@docker_only
class PlantedLeakTests(unittest.TestCase):
    def setUp(self):
        self.pilot = pilot(PYTEST_ID)
        self.base_tag = require_image(self.pilot)
        self.user = original_user(self.base_tag)
        self.tags = []
        self.addCleanup(self.remove_images)
        clear_labeled_containers()

    def remove_images(self):
        for tag in self.tags:
            docker("rmi", "-f", tag)

    def derive(self, fake_id, dockerfile_body, files=None):
        tag = "sweb.eval.arm64.%s:latest" % fake_id
        self.tags.append(tag)
        with tempfile.TemporaryDirectory() as context:
            for name, text in (files or {}).items():
                Path(context, name).write_text(text, encoding="utf-8")
            dockerfile = "FROM %s\nUSER root\n%s\n%s\n" % (
                self.base_tag, dockerfile_body, "USER %s" % self.user if self.user else "",
            )
            Path(context, "Dockerfile").write_text(dockerfile, encoding="utf-8")
            built = docker("build", "-q", "-t", tag, context)
        self.assertEqual(built.returncode, 0, built.stderr)
        instance = copy.deepcopy(self.pilot)
        instance["instance_id"] = fake_id
        return instance

    def test_vo8_l2_gold_post_image_copy_under_opt_is_reported(self):
        body = (
            "COPY gold.patch /gold.patch\n"
            "RUN git config --global --add safe.directory /testbed"
            " && cd /testbed && git apply /gold.patch"
            " && mkdir -p /opt/leak && cp %s /opt/leak/reports.py"
            " && git checkout -- . && rm /gold.patch" % GOLD_SRC_PATH
        )
        instance = self.derive("selfcheck-leaktest__copy-1", body, {"gold.patch": self.pilot["patch"]})
        result = validate.leak_check(instance)
        self.assertIs(result["ok"], False)
        self.assertEqual(result["gold_copies"], ["/opt/leak/reports.py"])
        self.assertEqual(result["future_commits"], 0)
        self.assertEqual(result["future_tags"], [])
        self.assertEqual(result["gold_blobs_present"], [])
        self.assertEqual(labeled_containers(), [])

    def test_vo8_l3_commit_after_base_is_reported_as_future_commit_and_tag(self):
        base = self.pilot["base_commit"]
        body = (
            "RUN git config --global --add safe.directory /testbed && cd /testbed"
            " && git tag base-tag %(base)s"
            " && git -c user.name=x -c user.email=x@x commit --allow-empty -m future"
            " && git branch future-branch && git tag future-tag"
            " && git reset --hard %(base)s" % {"base": base}
        )
        instance = self.derive("selfcheck-leaktest__future-1", body)
        result = validate.leak_check(instance)
        self.assertIs(result["ok"], False)
        self.assertGreaterEqual(result["future_commits"], 1)
        self.assertEqual(result["future_commits"], 1)
        self.assertEqual(result["future_tags"], ["future-tag"])
        self.assertEqual(result["gold_copies"], [])
        self.assertEqual(labeled_containers(), [])

    def test_vo8_l5_future_commit_on_base_with_ordinary_subject_is_counted(self):
        base = self.pilot["base_commit"]
        body = (
            "RUN git config --global --add safe.directory /testbed && cd /testbed"
            " && git checkout -q --detach %(base)s"
            " && git -c user.name=x -c user.email=x@x commit -q --allow-empty -m future"
            " && git tag keep-future && git reset -q --hard %(base)s" % {"base": base}
        )
        instance = self.derive("selfcheck-leaktest__future-2", body)
        result = validate.leak_check(instance)
        self.assertIs(result["ok"], False)
        self.assertEqual(result["future_commits"], 1)
        self.assertEqual(result["future_tags"], ["keep-future"])

    def test_vo8_l5_swe_bench_subject_with_a_non_base_parent_is_counted(self):
        base = self.pilot["base_commit"]
        commit = "git -c user.name=x -c user.email=x@x commit -q --allow-empty -m SWE-bench"
        body = (
            "RUN git config --global --add safe.directory /testbed && cd /testbed"
            " && git checkout -q --detach %(base)s"
            " && %(commit)s && %(commit)s"
            " && git tag keep-second && git reset -q --hard %(base)s" % {"base": base, "commit": commit}
        )
        instance = self.derive("selfcheck-leaktest__setup-1", body)
        result = validate.leak_check(instance)
        self.assertIs(result["ok"], False)
        self.assertEqual(result["future_commits"], 1)
        self.assertEqual(result["future_tags"], ["keep-second"])

    def test_vo8_l6_renamed_gold_copy_under_usr_is_reported_with_the_opt_copy(self):
        body = (
            "COPY gold.patch /gold.patch\n"
            "RUN git config --global --add safe.directory /testbed"
            " && cd /testbed && git apply /gold.patch"
            " && mkdir -p /opt/leak /usr/local/share"
            " && cp %s /opt/leak/reports.py && cp %s /usr/local/share/leak.dat"
            " && git checkout -- . && rm /gold.patch" % (GOLD_SRC_PATH, GOLD_SRC_PATH)
        )
        instance = self.derive("selfcheck-leaktest__copy-2", body, {"gold.patch": self.pilot["patch"]})
        result = validate.leak_check(instance)
        self.assertIs(result["ok"], False)
        self.assertEqual(
            sorted(result["gold_copies"]), ["/opt/leak/reports.py", "/usr/local/share/leak.dat"]
        )

    def test_vo8_l4_gold_blob_in_object_database_is_reported(self):
        body = (
            "COPY gold.patch /gold.patch\n"
            "RUN git config --global --add safe.directory /testbed"
            " && cd /testbed && git apply /gold.patch && git add -A"
            " && git -c user.name=x -c user.email=x@x commit -m gold"
            " && git reset --hard %s && rm /gold.patch" % self.pilot["base_commit"]
        )
        instance = self.derive("selfcheck-leaktest__blob-1", body, {"gold.patch": self.pilot["patch"]})
        result = validate.leak_check(instance)
        self.assertIs(result["ok"], False)
        self.assertEqual(result["gold_blobs_present"], [GOLD_SRC_PATH])
        self.assertEqual(result["future_commits"], 0)
        self.assertEqual(result["gold_copies"], [])


if __name__ == "__main__":
    unittest.main()

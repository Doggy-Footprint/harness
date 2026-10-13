import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from selfcheck import evaluate
from selfcheck.tests.helpers import (
    DJANGO_ID, PYTEST_ID, build_derived_image, make_shim, clear_labeled_containers, remove_image, docker_only, git_apply_files, git_diff,
    labeled_containers, pass_set, pilot, require_image,
)

SRC_PATH = "src/_pytest/reports.py"
NET_TEST_ID = "testing/test_selfcheck_net.py::test_network_blocked"
NET_PATCH = (
    "diff --git a/testing/test_selfcheck_net.py b/testing/test_selfcheck_net.py\n"
    "new file mode 100644\n"
    "index 0000000..1111111\n"
    "--- /dev/null\n"
    "+++ b/testing/test_selfcheck_net.py\n"
    "@@ -0,0 +1,5 @@\n"
    "+import socket\n"
    "+\n"
    "+\n"
    "+def test_network_blocked():\n"
    "+    socket.create_connection((\"1.1.1.1\", 53), timeout=3)\n"
)
WRONG_CONTEXT_PATCH = (
    "diff --git a/testing/test_reports.py b/testing/test_reports.py\n"
    "--- a/testing/test_reports.py\n"
    "+++ b/testing/test_reports.py\n"
    "@@ -1,3 +1,3 @@\n"
    " THIS LINE DOES NOT EXIST ANYWHERE\n"
    "-neither does this one\n"
    "+replacement\n"
    " nor this\n"
)
JSON_ONLY_PATCH = (
    "diff --git a/testing/data/sample.json b/testing/data/sample.json\n"
    "--- a/testing/data/sample.json\n"
    "+++ b/testing/data/sample.json\n"
    "@@ -1 +1 @@\n"
    "-{}\n"
    "+{\"a\": 1}\n"
)
SLEEP_PATCH = (
    "diff --git a/testing/test_selfcheck_sleep.py b/testing/test_selfcheck_sleep.py\n"
    "new file mode 100644\n"
    "index 0000000..2222222\n"
    "--- /dev/null\n"
    "+++ b/testing/test_selfcheck_sleep.py\n"
    "@@ -0,0 +1,5 @@\n"
    "+import time\n"
    "+\n"
    "+\n"
    "+def test_sleep():\n"
    "+    time.sleep(30)\n"
)
RESULT_KEYS = {"key", "apply", "status", "exit_code", "no_tests", "timed_out", "log_path"}


@docker_only
class EvaluateScenarioTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.row = pilot(PYTEST_ID)
        require_image(cls.row)
        clear_labeled_containers()
        cls.results = {}
        cls.leftovers = {}
        row = cls.row
        scenarios = [
            ("base", lambda: evaluate.evaluate(row, "", row["test_patch"])),
            ("gold", lambda: evaluate.evaluate(row, row["patch"], row["test_patch"])),
            ("garbage_src", lambda: evaluate.evaluate(row, "this is not a diff\n", row["test_patch"])),
            ("bad_test_patch", lambda: evaluate.evaluate(row, "", WRONG_CONTEXT_PATCH)),
            ("empty_test_patch", lambda: evaluate.evaluate(row, row["patch"], "")),
            ("json_only_test_patch", lambda: evaluate.evaluate(row, row["patch"], JSON_ONLY_PATCH)),
            ("timeout", lambda: evaluate.evaluate(row, row["patch"], row["test_patch"], timeout_s=1)),
            ("network", lambda: evaluate.evaluate(row, "", NET_PATCH)),
        ]
        for name, call in scenarios:
            cls.results[name] = call()
            cls.leftovers[name] = labeled_containers()

    def test_vo7_t1_gold_passes_f2p_and_base_does_not(self):
        gold, base = self.results["gold"], self.results["base"]
        self.assertEqual(gold["apply"], "ok")
        self.assertEqual(base["apply"], "ok")
        self.assertFalse(gold["no_tests"] or gold["timed_out"])
        self.assertFalse(base["no_tests"] or base["timed_out"])
        for test_id in self.row["FAIL_TO_PASS"]:
            with self.subTest(test_id=test_id):
                self.assertTrue(pass_set(gold["status"].get(test_id)), gold["status"].get(test_id))
                self.assertFalse(pass_set(base["status"].get(test_id)), base["status"].get(test_id))
        self.assertIn("PASSED", gold["status"].values())

    def test_vo7_t1_result_has_exactly_the_eval_result_keys(self):
        for name, result in self.results.items():
            with self.subTest(scenario=name):
                self.assertEqual(set(result), RESULT_KEYS)
                self.assertIsInstance(result["status"], dict)

    def test_vo7_t3_unappliable_src_diff(self):
        result = self.results["garbage_src"]
        self.assertEqual(result["apply"], "src_failed")
        self.assertEqual(result["status"], {})
        self.assertFalse(result["no_tests"])
        self.assertFalse(result["timed_out"])

    def test_vo7_t4_unappliable_test_patch(self):
        result = self.results["bad_test_patch"]
        self.assertEqual(result["apply"], "test_failed")
        self.assertEqual(result["status"], {})
        self.assertFalse(result["no_tests"])

    def test_vo7_t5_no_test_directives(self):
        for name in ("empty_test_patch", "json_only_test_patch"):
            with self.subTest(scenario=name):
                result = self.results[name]
                self.assertTrue(result["no_tests"])
                self.assertEqual(result["status"], {})
                self.assertEqual(result["apply"], "ok")
                self.assertFalse(result["timed_out"])

    def test_vo7_t6_timeout(self):
        self.assertTrue(self.results["timeout"]["timed_out"])

    def test_vo7_t7_no_labeled_container_remains_after_each_scenario(self):
        self.assertEqual(self.leftovers, {name: [] for name in self.results})
        self.assertEqual(labeled_containers(), [])

    def test_vo7_t9_network_is_disabled_for_tests(self):
        result = self.results["network"]
        self.assertEqual(result["apply"], "ok")
        self.assertFalse(result["no_tests"])
        self.assertIn(NET_TEST_ID, result["status"])
        self.assertFalse(pass_set(result["status"][NET_TEST_ID]), result["status"][NET_TEST_ID])


@docker_only
class DjangoGoldTests(unittest.TestCase):
    def test_vo7_t2_gold_on_django_11400(self):
        row = pilot(DJANGO_ID)
        require_image(row)
        clear_labeled_containers()
        result = evaluate.evaluate(row, row["patch"], row["test_patch"])
        self.assertEqual(result["apply"], "ok")
        self.assertFalse(result["no_tests"] or result["timed_out"])
        for test_id in row["FAIL_TO_PASS"]:
            with self.subTest(test_id=test_id):
                self.assertTrue(pass_set(result["status"].get(test_id)), result["status"].get(test_id))
        self.assertEqual(labeled_containers(), [])


@docker_only
class CacheTests(unittest.TestCase):
    def setUp(self):
        self.row = pilot(PYTEST_ID)
        require_image(self.row)
        clear_labeled_containers()

    def test_vo7_t8_cache_hit_needs_no_docker(self):
        with tempfile.TemporaryDirectory() as cache:
            first = evaluate.evaluate(self.row, "", "", cache_dir=cache)
            self.assertTrue(first["no_tests"])
            with mock.patch.dict(os.environ, {"DOCKER_HOST": "unix:///nonexistent.sock", "SELFCHECK_DOCKER_WAIT_S": "2"}):
                second = evaluate.evaluate(self.row, "", "", cache_dir=cache)
            self.assertEqual(second, first)
        self.assertEqual(labeled_containers(), [])

    def test_vo7_t16_cache_miss_with_unreachable_daemon_raises_runtime_error(self):
        variants = {
            "repeat": dict(src_diff="", test_patch="", repeat=1),
            "src_diff": dict(src_diff="garbage\n", test_patch=""),
            "test_patch": dict(src_diff="", test_patch=JSON_ONLY_PATCH),
            "network": dict(src_diff="", test_patch="", network=True),
        }
        with tempfile.TemporaryDirectory() as cache:
            evaluate.evaluate(self.row, "", "", cache_dir=cache)
            with mock.patch.dict(os.environ, {"DOCKER_HOST": "unix:///nonexistent.sock", "SELFCHECK_DOCKER_WAIT_S": "2"}):
                for name, kwargs in variants.items():
                    with self.subTest(changed=name):
                        extra = dict(kwargs)
                        src_diff = extra.pop("src_diff")
                        test_patch = extra.pop("test_patch")
                        for attempt in ("first", "repeat_must_not_hit_a_written_entry"):
                            with self.subTest(attempt=attempt):
                                with self.assertRaises(RuntimeError):
                                    evaluate.evaluate(self.row, src_diff, test_patch, cache_dir=cache, **extra)

    def test_vo7_t8_src_failed_result_is_cached(self):
        with tempfile.TemporaryDirectory() as cache:
            first = evaluate.evaluate(self.row, "not a diff\n", self.row["test_patch"], cache_dir=cache)
            self.assertEqual(first["apply"], "src_failed")
            with mock.patch.dict(os.environ, {"DOCKER_HOST": "unix:///nonexistent.sock", "SELFCHECK_DOCKER_WAIT_S": "2"}):
                second = evaluate.evaluate(self.row, "not a diff\n", self.row["test_patch"], cache_dir=cache)
            self.assertEqual(second, first)


@docker_only
class RunningContainerTests(unittest.TestCase):
    def test_vo7_t13_labeled_container_exists_while_evaluate_runs(self):
        row = pilot(PYTEST_ID)
        require_image(row)
        clear_labeled_containers()
        outcome = {}
        worker = threading.Thread(
            target=lambda: outcome.update(result=evaluate.evaluate(row, "", SLEEP_PATCH, timeout_s=180))
        )
        worker.start()
        observed = False
        deadline = time.monotonic() + 60
        while worker.is_alive() and time.monotonic() < deadline:
            if labeled_containers():
                observed = True
                break
            time.sleep(0.5)
        worker.join()
        self.assertTrue(observed, "no container labeled selfcheck=1 seen while evaluate was running")
        self.assertEqual(outcome["result"]["apply"], "ok")
        self.assertEqual(labeled_containers(), [])


@docker_only
class EvalResultKeyTests(unittest.TestCase):
    FAKE_ID = "selfcheck-keytest__image-1"

    def setUp(self):
        self.row = pilot(PYTEST_ID)
        self.base_tag = require_image(self.row)
        self.tag = "sweb.eval.arm64.%s:latest" % self.FAKE_ID
        self.addCleanup(remove_image, self.tag)
        clear_labeled_containers()

    def derived_row(self, **changes):
        row = pilot(PYTEST_ID)
        row["instance_id"] = self.FAKE_ID
        row.update(changes)
        return row

    def test_vo7_t14_key_is_stable_for_identical_inputs(self):
        first = evaluate.evaluate(self.row, "", "")
        second = evaluate.evaluate(self.row, "", "")
        self.assertEqual(first["key"], second["key"])
        with tempfile.TemporaryDirectory() as cache:
            cached_first = evaluate.evaluate(self.row, "", "", cache_dir=cache)
            cached_second = evaluate.evaluate(self.row, "", "", cache_dir=cache)
        self.assertEqual(cached_first["key"], cached_second["key"])
        self.assertEqual(cached_first["key"], first["key"])

    def test_vo7_t14_key_changes_when_the_image_behind_the_same_name_changes(self):
        row = self.derived_row()
        build_derived_image(self.base_tag, self.tag, "LABEL selfcheck.test=1")
        first = evaluate.evaluate(row, "", "")
        build_derived_image(self.base_tag, self.tag, "LABEL selfcheck.test=2")
        second = evaluate.evaluate(row, "", "")
        self.assertNotEqual(first["key"], second["key"])
        third = evaluate.evaluate(row, "", "")
        self.assertEqual(second["key"], third["key"])

    def test_vo7_t14_key_changes_when_base_commit_changes_the_eval_script(self):
        baseline = evaluate.evaluate(self.row, "", "")
        other = pilot(PYTEST_ID)
        other["base_commit"] = "0" * 40
        changed = evaluate.evaluate(other, "", "")
        self.assertNotEqual(baseline["key"], changed["key"])

    def test_vo7_t14_key_changes_with_each_other_input(self):
        baseline = evaluate.evaluate(self.row, "", "")["key"]
        keys = {
            "repeat": evaluate.evaluate(self.row, "", "", repeat=1)["key"],
            "src_diff": evaluate.evaluate(self.row, "not a diff\n", "")["key"],
            "test_patch": evaluate.evaluate(self.row, "", JSON_ONLY_PATCH)["key"],
            "network": evaluate.evaluate(self.row, "", "", network=True)["key"],
        }
        for name, key in keys.items():
            with self.subTest(changed=name):
                self.assertNotEqual(key, baseline)


@docker_only
class DockerReadinessTests(unittest.TestCase):
    def setUp(self):
        self.row = pilot(PYTEST_ID)
        require_image(self.row)
        clear_labeled_containers()

    def run_with_shim(self, body, wait, call):
        with tempfile.TemporaryDirectory() as directory:
            make_shim(directory, body.replace("@DIR@", directory))
            env = {"PATH": directory + os.pathsep + os.environ["PATH"], "SELFCHECK_DOCKER_WAIT_S": str(wait)}
            with mock.patch.dict(os.environ, env):
                return call()

    FLAKY = (
        'n=$(cat "@DIR@/count" 2>/dev/null || echo 0)\n'
        'if [ "$n" -lt 3 ]; then echo $((n+1)) > "@DIR@/count"; '
        'echo "Cannot connect to the Docker daemon" >&2; exit 1; fi\n'
        'exec @REAL@ "$@"\n'
    )
    DEAD = 'echo "Cannot connect to the Docker daemon" >&2\nexit 1\n'

    def test_vo7_t17_calls_recover_after_a_transient_outage(self):
        result = self.run_with_shim(self.FLAKY, 30, lambda: evaluate.evaluate(self.row, "", ""))
        self.assertEqual(result["apply"], "ok")
        self.assertTrue(result["no_tests"])
        self.assertEqual(labeled_containers(), [])

    def test_vo7_t17_read_files_recovers_after_a_transient_outage(self):
        files = self.run_with_shim(
            self.FLAKY, 30, lambda: evaluate.read_files(self.row, "", [SRC_PATH, "no/such/file.py"])
        )
        self.assertIsInstance(files[SRC_PATH], str)
        self.assertIsNone(files["no/such/file.py"])

    def test_vo7_t17_permanent_outage_raises_runtime_error_after_the_wait(self):
        started = time.monotonic()
        with self.assertRaises(RuntimeError):
            self.run_with_shim(self.DEAD, 3, lambda: evaluate.evaluate(self.row, "", ""))
        self.assertLess(time.monotonic() - started, 15)

    def test_vo7_t17_missing_image_with_healthy_daemon_fails_without_waiting(self):
        row = pilot(PYTEST_ID)
        row["instance_id"] = "selfcheck-nonexistent__none-2"
        started = time.monotonic()
        with mock.patch.dict(os.environ, {"SELFCHECK_DOCKER_WAIT_S": "60"}):
            with self.assertRaises(RuntimeError):
                evaluate.evaluate(row, "", "")
        self.assertLess(time.monotonic() - started, 5)

    def pilot_tag(self):
        return "sweb.eval.arm64.%s:latest" % self.row["instance_id"].lower()

    def stale_name_shim(self, inspect_limit, run_limit):
        # Counter files record how often each failing branch fired.
        return (
            'tag="%s"\n'
            'named=0\n'
            'for a in "$@"; do [ "$a" = "$tag" ] && named=1; done\n'
            'bump() { n=$(cat "@DIR@/$1" 2>/dev/null || echo 0); echo $((n+1)) > "@DIR@/$1"; }\n'
            'fail() { echo "Error response from daemon: No such image: $tag" >&2; exit 1; }\n'
            'if [ "$named" = 1 ] && [ "$1" = image ] && [ "$2" = inspect ]; then\n'
            '  n=$(cat "@DIR@/inspect" 2>/dev/null || echo 0)\n'
            '  if [ "%s" = always ] || [ "$n" -lt "%s" ]; then bump inspect; fail; fi\n'
            'fi\n'
            'if [ "$named" = 1 ] && [ "$1" = run ]; then\n'
            '  n=$(cat "@DIR@/run" 2>/dev/null || echo 0)\n'
            '  if [ "$n" -lt %d ]; then bump run; fail; fi\n'
            'fi\n'
            'exec @REAL@ "$@"\n'
        ) % (self.pilot_tag(), inspect_limit, inspect_limit, run_limit)

    def test_vo7_t18_stale_image_name_lookups_recover_during_engine_start(self):
        with tempfile.TemporaryDirectory() as directory:
            make_shim(directory, self.stale_name_shim(3, 1).replace("@DIR@", directory))
            env = {"PATH": directory + os.pathsep + os.environ["PATH"], "SELFCHECK_DOCKER_WAIT_S": "30"}
            with mock.patch.dict(os.environ, env):
                result = evaluate.evaluate(self.row, "", "", cache_dir=None)
            counts = {}
            for name in ("inspect", "run"):
                counts[name] = int(Path(directory, name).read_text().strip())
        self.assertEqual(counts, {"inspect": 3, "run": 1})
        self.assertEqual(result["apply"], "ok")
        self.assertTrue(result["no_tests"])
        self.assertEqual(labeled_containers(), [])

    def test_vo7_t18_permanently_stale_name_raises_runtime_error_after_the_wait(self):
        started = time.monotonic()
        with tempfile.TemporaryDirectory() as directory:
            make_shim(directory, self.stale_name_shim("always", 0).replace("@DIR@", directory))
            env = {"PATH": directory + os.pathsep + os.environ["PATH"], "SELFCHECK_DOCKER_WAIT_S": "3"}
            with mock.patch.dict(os.environ, env):
                with self.assertRaises(RuntimeError):
                    evaluate.evaluate(self.row, "", "", cache_dir=None)
            self.assertGreaterEqual(int(Path(directory, "inspect").read_text().strip()), 1)
        self.assertLess(time.monotonic() - started, 15)
        self.assertEqual(labeled_containers(), [])


@docker_only
class FileAccessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.row = pilot(PYTEST_ID)
        require_image(cls.row)
        clear_labeled_containers()

    def test_vo7_t10_read_files_present_and_absent(self):
        files = evaluate.read_files(self.row, "", [SRC_PATH, "no/such/file.py"])
        self.assertEqual(set(files), {SRC_PATH, "no/such/file.py"})
        self.assertIsInstance(files[SRC_PATH], str)
        self.assertIn("class TestReport", files[SRC_PATH])
        self.assertIsNone(files["no/such/file.py"])
        self.assertEqual(labeled_containers(), [])

    def test_vo7_t10_read_files_applies_the_src_diff_first(self):
        base = evaluate.read_files(self.row, "", [SRC_PATH])[SRC_PATH]
        after = evaluate.read_files(self.row, self.row["patch"], [SRC_PATH])[SRC_PATH]
        self.assertNotEqual(base, after)
        self.assertEqual(after, git_apply_files({SRC_PATH: base}, self.row["patch"])[SRC_PATH])

    def test_vo7_t10_read_files_raises_when_src_diff_does_not_apply(self):
        with self.assertRaises(RuntimeError):
            evaluate.read_files(self.row, "not a diff\n", [SRC_PATH])
        self.assertEqual(labeled_containers(), [])

    def test_vo7_t11_compile_ok_true_for_gold_patch(self):
        self.assertIs(evaluate.compile_ok(self.row, self.row["patch"], [SRC_PATH]), True)

    def test_vo7_t11_compile_ok_false_for_syntax_error(self):
        base = evaluate.read_files(self.row, "", [SRC_PATH])[SRC_PATH]
        broken = git_diff({SRC_PATH: base}, {SRC_PATH: base + "\ndef broken(:\n    pass\n"})
        self.assertIs(evaluate.compile_ok(self.row, broken, [SRC_PATH]), False)

    def test_vo7_t11_compile_ok_false_when_patch_does_not_apply(self):
        mismatched = git_diff({SRC_PATH: "alpha\nbeta\n"}, {SRC_PATH: "alpha\ngamma\n"})
        self.assertIs(evaluate.compile_ok(self.row, mismatched, [SRC_PATH]), False)

    def test_vo7_t15_walrus_is_invalid_on_python_36_and_valid_on_python_39(self):
        django_row = pilot(DJANGO_ID)
        require_image(django_row)
        for row, prefix, expected in ((django_row, "django", False), (self.row, "src/_pytest", True)):
            path = "%s/selfcheck_walrus.py" % prefix
            patch = git_diff({}, {path: "(n := 1)\n"})
            with self.subTest(instance=row["instance_id"]):
                self.assertIs(evaluate.compile_ok(row, patch, [path]), expected)

    def test_vo7_t11_compile_ok_checks_every_path(self):
        new_file = git_diff({}, {"src/_pytest/selfcheck_broken.py": "def broken(:\n"})
        self.assertIs(
            evaluate.compile_ok(self.row, new_file, [SRC_PATH, "src/_pytest/selfcheck_broken.py"]), False
        )


@docker_only
class MissingImageTests(unittest.TestCase):
    def test_vo7_t12_missing_image_raises_runtime_error_naming_it(self):
        row = pilot(PYTEST_ID)
        row["instance_id"] = "selfcheck-nonexistent__none-1"
        clear_labeled_containers()
        with self.assertRaises(RuntimeError) as context:
            evaluate.evaluate(row, "", row["test_patch"])
        self.assertIn("sweb.eval.arm64.selfcheck-nonexistent__none-1:latest", str(context.exception))
        self.assertEqual(labeled_containers(), [])


if __name__ == "__main__":
    unittest.main()

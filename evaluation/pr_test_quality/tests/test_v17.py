import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
import unittest.mock
from pathlib import Path

from evaluation.pr_test_quality import brief, recipes, run
from evaluation.pr_test_quality.tests.test_run import Lab, mk_task
from evaluation.pr_test_quality.tests.test_v10 import dockerfile

FAKE = """#!/bin/sh
echo "$0 $*" >> "$LOG"
case "$MODE" in
  root-flag-required) case " $* " in *" -W "*|*" -w "*) exit 0;; *) exit 1;; esac;;
  root-flag-rejected) case " $* " in *" -W "*|*" -w "*) exit 1;; *) exit 0;; esac;;
esac
"""


def tool_step(manager):
    text = dockerfile({"yarn": "ts-yarn-vitest", "pnpm": "ts-pnpm-vitest"}[manager])
    return next(l[4:] for l in text.splitlines() if l.startswith("RUN ") and "@stryker-mutator/core" in l)


class WorkspaceRootToolInstall(unittest.TestCase):
    def run_step(self, manager, mode):
        with tempfile.TemporaryDirectory() as d:
            fake = Path(d, manager)
            fake.write_text(FAKE)
            fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
            log = Path(d, "log")
            env = {**os.environ, "PATH": f"{d}:{os.environ['PATH']}", "LOG": str(log), "MODE": mode}
            rc = subprocess.run(["sh", "-c", tool_step(manager)], env=env, capture_output=True).returncode
            return rc, log.read_text().splitlines()

    def test_workspace_root_flag_is_tried_first_and_succeeds_for_classic_roots(self):
        for manager in ("yarn", "pnpm"):
            rc, calls = self.run_step(manager, "root-flag-required")
            self.assertEqual(rc, 0, manager)
            self.assertEqual(len(calls), 1, manager)

    def test_a_manager_rejecting_the_flag_falls_back_to_a_plain_add(self):
        for manager in ("yarn", "pnpm"):
            rc, calls = self.run_step(manager, "root-flag-rejected")
            self.assertEqual(rc, 0, manager)
            self.assertEqual(len(calls), 2, manager)
            self.assertNotIn(" -W ", f" {calls[1]} ")
            self.assertNotIn(" -w ", f" {calls[1]} ")


class PublicLiteralsAreNotLeaks(unittest.TestCase):
    def task(self, body):
        from evaluation.pr_test_quality.tests.test_brief import task_with_tests
        t = task_with_tests("python", "def test_reads_body():\n    assert f() == \"body\"\n    assert g() == \"zq9-secret\"\n")
        return {**t, "title": "Parse request", "body": body, "issue_bodies": []}

    def test_an_asserted_literal_in_the_pull_request_text_is_not_forbidden(self):
        task = self.task("Return the request body when it is present.")
        self.assertNotIn("body", brief.forbidden_terms(task))
        self.assertEqual(brief.leaks("send back the body", task), [])

    def test_an_asserted_literal_absent_from_public_text_stays_forbidden(self):
        task = self.task("Return the request body when it is present.")
        self.assertEqual(brief.leaks("it must answer zq9-secret", task), ["zq9-secret"])
        self.assertIn("zq9-secret", brief.forbidden_terms(self.task("Unrelated text.")))

    def test_test_names_stay_forbidden_even_when_the_pull_request_names_them(self):
        task = self.task("See test_reads_body for the case.")
        self.assertIn("test_reads_body", brief.forbidden_terms(task))


class ValidationStopsAtFirstError(unittest.TestCase):
    def run_with(self, statuses_by_tree):
        from unittest import mock
        from evaluation.pr_test_quality import validate
        from evaluation.pr_test_quality.tests.fakes import make_task, spec_cfg
        task = make_task("python")
        calls = []

        def fake(task_, tree, selection, **kw):
            state = "merge" if tree == validate.merge_tree(task_) else ("orig" if len(calls) >= 1 and calls[-1][0] in ("merge", "orig") else "base")
            calls.append((state, kw.get("repeat")))
            status = statuses_by_tree.get(state, "ok")
            return {"status": status, "results": {}, "runtime_s": 1.0, "cached": False}

        with mock.patch.object(validate.testrun, "run_tests", side_effect=fake):
            verdict = validate.validate_task(task, docker=None, cfg=spec_cfg(), cache_dir="/nonexistent")
        return verdict, calls

    def test_a_base_timeout_runs_nothing_more_and_invalidates(self):
        verdict, calls = self.run_with({"base": "timeout"})
        self.assertEqual(calls, [("base", 0)])
        self.assertEqual((verdict["valid"], verdict["reason"]), (False, "timeout"))

    def test_a_merge_build_error_stops_merge_and_skips_orig(self):
        verdict, calls = self.run_with({"merge": "build_error"})
        self.assertEqual([c[0] for c in calls], ["base", "base", "base", "merge"])
        self.assertEqual((verdict["valid"], verdict["reason"]), (False, "build_error"))

    def test_a_base_build_error_counts_as_no_test_passing_and_validation_continues(self):
        verdict, calls = self.run_with({"base": "build_error"})
        self.assertEqual([c[0] for c in calls].count("base"), 1)
        self.assertIn("merge", [c[0] for c in calls])
        self.assertNotEqual(verdict["reason"], "build_error")


class RustBuildScriptPackages(unittest.TestCase):
    PACKAGES = ("cmake", "clang", "libclang-dev", "protobuf-compiler")

    def test_rust_image_installs_build_script_system_packages(self):
        apt = [l for l in dockerfile("rust").splitlines() if "apt-get install" in l]
        for package in self.PACKAGES:
            self.assertTrue(any(f" {package} " in l for l in apt), package)

    def test_other_languages_do_not_get_them(self):
        for key in ("python-pip", "go", "ts-npm-jest"):
            text = dockerfile(key)
            self.assertNotIn("protobuf-compiler", text, key)
            self.assertNotIn("libclang-dev", text, key)


PYPROJECT = """
[project]
name = "x"
[project.optional-dependencies]
test = ["opt-test==1"]
cli = ["not-wanted==1"]
[dependency-groups]
dev = ["group-dev==1", {include-group = "lint"}]
lint = ["not-wanted-either==1"]
[tool.uv]
dev-dependencies = ["uv-dev==1"]
"""


class UnlockedPythonDevDependencies(unittest.TestCase):
    def run_step(self, pyproject):
        line = next(l[4:] for l in dockerfile("python-pip").splitlines() if "tomllib" in l)
        with tempfile.TemporaryDirectory() as d:
            bin_ = Path(d, ".venv", "bin")
            bin_.mkdir(parents=True)
            Path(bin_, "python").symlink_to(sys.executable)
            pip = Path(bin_, "pip")
            pip.write_text('#!/bin/sh\necho "$*" >> "$LOG"\n')
            pip.chmod(pip.stat().st_mode | stat.S_IEXEC)
            if pyproject is not None:
                Path(d, "pyproject.toml").write_text(pyproject)
            log = Path(d, "log")
            rc = subprocess.run(["sh", "-c", line], cwd=d, env={**os.environ, "LOG": str(log)}, capture_output=True).returncode
            return rc, log.read_text().split() if log.exists() else []

    def test_dev_groups_test_extras_and_uv_dev_dependencies_are_installed(self):
        rc, args = self.run_step(PYPROJECT)
        self.assertEqual(rc, 0)
        self.assertEqual(args[0], "install")
        self.assertEqual(sorted(args[1:]), ["group-dev==1", "opt-test==1", "uv-dev==1"])

    def test_no_pyproject_or_no_dev_tables_installs_nothing(self):
        self.assertEqual(self.run_step(None), (0, []))
        self.assertEqual(self.run_step('[project]\nname = "x"\n'), (0, []))


class PlainWordsAreNotLeaks(unittest.TestCase):
    TESTS = (
        "def h():\n    pass\n"
        "def readModel():\n    pass\n"
        "def test_t():\n"
        "    assert f() == \"type\"\n"
        "    assert g() == \"First\"\n"
        "    assert k() == \"read_model\"\n"
        "    assert m() == \"sourceId\"\n"
        "    assert n() == \"two words\"\n"
    )

    def terms(self):
        from evaluation.pr_test_quality.tests.test_brief import task_with_tests
        return brief.forbidden_terms(task_with_tests("python", self.TESTS))

    def test_lone_dictionary_words_from_literals_and_test_definitions_are_allowed(self):
        terms = self.terms()
        for word in ("type", "First", "h"):
            self.assertNotIn(word, terms)

    def test_compound_identifiers_and_multi_word_literals_stay_forbidden(self):
        terms = self.terms()
        for term in ("read_model", "sourceId", "two words", "readModel", "test_t"):
            self.assertIn(term, terms)


class ClaudeFailureDetail(unittest.TestCase):
    def call_with(self, script):
        from evaluation.pr_test_quality import claude_call
        with tempfile.TemporaryDirectory() as d:
            fake = Path(d, "claude")
            fake.write_text(script)
            fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
            with unittest.mock.patch.dict(os.environ, {"PATH": f"{d}:{os.environ['PATH']}"}):
                with self.assertRaises(RuntimeError) as ctx:
                    claude_call.claude_call("p", model="m", effort="e", timeout_s=30)
        return str(ctx.exception)

    def test_stdout_is_reported_when_stderr_is_empty(self):
        self.assertIn("usage limit reached", self.call_with("#!/bin/sh\necho 'usage limit reached'\nexit 1\n"))

    def test_stderr_wins_when_present(self):
        message = self.call_with("#!/bin/sh\necho out\necho err >&2\nexit 1\n")
        self.assertIn("err", message)
        self.assertNotIn("out", message)


class ParallelMutantRuns(unittest.TestCase):
    def test_mutants_run_concurrently_and_keep_the_sampled_order(self):
        import threading
        from unittest import mock
        from evaluation.pr_test_quality import mutants
        from evaluation.pr_test_quality.tests.fakes import make_task, spec_cfg
        task = make_task("python")
        path = next(iter(task["gold_after"]))
        chosen = [{"id": f"m{i}", "path": path, "line": 1, "diff": f"d{i}"} for i in range(8)]
        lock, active, peak = threading.Lock(), [0], [0]
        barrier = threading.Barrier(4, timeout=5)

        def fake_run(task_, tree, selection, **kw):
            with lock:
                active[0] += 1
                peak[0] = max(peak[0], active[0])
            barrier.wait()
            with lock:
                active[0] -= 1
            killed = tree[path].endswith("d0") or tree[path].endswith("d5")
            return {"status": "ok", "results": {t: "fail" if killed else "pass" for t in task_["f2p"]}}

        class Docker:
            def container(self, *a, **k):
                c = mock.MagicMock()
                c.__enter__.return_value.exec.return_value = (0, "", False)
                return c

        with mock.patch.object(mutants, "changed_lines", return_value={path: {1}}), \
             mock.patch.object(mutants, "classify_path", return_value="src"), \
             mock.patch.object(mutants, "diff_paths", return_value=[path]), \
             mock.patch.object(mutants, "normalize", return_value=chosen), \
             mock.patch.object(mutants, "restrict", side_effect=lambda m, c: m), \
             mock.patch.object(mutants, "sample", side_effect=lambda m, cap, seed: m), \
             mock.patch.object(mutants, "apply_diff", side_effect=lambda text, diff: text + diff), \
             mock.patch.object(mutants.testrun, "apply_tree"), \
             mock.patch.object(mutants.testrun, "run_tests", side_effect=fake_run):
            rows = mutants.build_mutants(task, docker=Docker(), cfg=spec_cfg(mutants={"workers": 4}), cache_dir="/x")
        self.assertEqual(peak[0], 4)
        self.assertEqual([r["id"] for r in rows], [m["id"] for m in chosen])
        self.assertEqual([r["gold"] for r in rows].count("killed"), 2)
        self.assertEqual(rows[0]["gold"], "killed")
        self.assertEqual(rows[5]["gold"], "killed")


class DriverStagedIntoExistingDir(unittest.TestCase):
    def test_driver_files_land_directly_in_driver_dir_under_docker_cp_semantics(self):
        with tempfile.TemporaryDirectory() as root:
            dest = Path(root + run.DRIVER_DIR)
            dest.mkdir(parents=True)

            class Container:
                def copy_in(self, local, dest_path):
                    local, target = str(local), Path(root + dest_path)
                    if local.endswith("/."):
                        shutil.copytree(local[:-2], target, dirs_exist_ok=True)
                    else:
                        shutil.copytree(local, target / Path(local).name if target.is_dir() else target)

            run._stage_driver(Container())
            self.assertTrue(Path(root + run.DRIVER_ARGV[1]).is_file())
            self.assertTrue((dest / "driver.py").is_file())


class TokenReadableByNonroot(Lab):
    def test_host_token_is_copied_to_a_nonroot_tmpfs_file_before_the_driver_runs(self):
        self.do_run([mk_task(1)])
        cont = self.docker.agent_started[0]
        mounts = cont.kwargs["mounts"]
        self.assertIn(f"type=bind,src={self.token_path},dst={run.TOKEN_SOURCE},readonly", mounts)
        self.assertIn("type=tmpfs,dst=/run/secrets", mounts)
        argvs = [e["argv"] for e in cont.execs]
        staged = argvs.index(["install", "-o", "nonroot", "-g", "nonroot", "-m", "0400",
                              run.TOKEN_SOURCE, run.TOKEN_MOUNT])
        self.assertEqual(cont.execs[staged]["user"], "root")
        self.assertLess(staged, argvs.index(run.DRIVER_ARGV))


class RateLimitWarningDoesNotHalt(Lab):
    def test_allowed_warning_completes_the_entry(self):
        self.rate_limit = {(1, "B0"): {"status": "allowed_warning", "resets_at": 1, "rate_limit_type": "seven_day"}}
        run_dir = self.do_run([mk_task(1)])
        self.assertEqual(list(self.statuses(run_dir).values()), ["completed"])


class CumulativeSessionCost(unittest.TestCase):
    def test_cumulative_results_count_once_per_cli_process(self):
        from evaluation.pr_test_quality import session_cost

        def rows(*costs):
            return [{"total_cost_usd": c} for c in costs]

        self.assertAlmostEqual(session_cost(rows(0.25, 0.39, 0.63, 2.65)), 2.65)
        self.assertAlmostEqual(session_cost(rows(0.2, 0.5, 0.1, 0.3)), 0.8)
        self.assertAlmostEqual(session_cost(rows(0.4, None, 0.9)), 0.9)
        self.assertIsNone(session_cost(rows(None)))
        self.assertIsNone(session_cost([]))

    def test_score_uses_session_cost_and_driver_elapsed_time(self):
        from evaluation.pr_test_quality import score

        state = {"elapsed_s": 734.0, "results": [{"total_cost_usd": 0.25}, {"total_cost_usd": 2.65}]}
        cost, wall = score._costs(state)
        self.assertAlmostEqual(cost, 2.65)
        self.assertEqual(wall, 734.0)


class ParallelCrossArmCells(unittest.TestCase):
    def test_cells_run_concurrently_and_keep_their_keys(self):
        import threading
        from evaluation.pr_test_quality import crossarm
        from evaluation.pr_test_quality.tests.fakes import make_task, spec_cfg
        task = make_task("python")
        names = ["B0-r1", "Bplus-r1", "H-r1"]
        lock, active, peak = threading.Lock(), [0], [0]
        barrier = threading.Barrier(2, timeout=5)

        def fake_run(task_, tree, selection, **kw):
            with lock:
                active[0] += 1
                peak[0] = max(peak[0], active[0])
            barrier.wait()
            with lock:
                active[0] -= 1
            return {"status": "ok", "results": {"t": tree}}

        with unittest.mock.patch.object(crossarm, "_completed", return_value=True), \
             unittest.mock.patch.object(crossarm, "_agent", side_effect=lambda d: Path(d).name), \
             unittest.mock.patch.object(crossarm, "test_selection", return_value=["x"]), \
             unittest.mock.patch.object(crossarm.overlay, "cross_tree", side_effect=lambda lang, gold, impl, tests: f"{tests}|{impl}"), \
             unittest.mock.patch.object(crossarm.testrun, "run_tests", side_effect=fake_run):
            matrix = crossarm.run_matrix(task, [f"/x/{n}" for n in names], docker=None,
                                         cfg=spec_cfg(mutants={"workers": 2}), cache_dir="/x")
        self.assertEqual(peak[0], 2)
        self.assertEqual(sorted(matrix), sorted((t, i) for t in names for i in names if t != i))
        self.assertTrue(all(r["results"]["t"] == f"{t}|{i}" for (t, i), r in matrix.items()))

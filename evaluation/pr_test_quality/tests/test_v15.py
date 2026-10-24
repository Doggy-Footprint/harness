import json
import re
import shlex
import shutil
import unittest
from pathlib import Path

from evaluation.pr_test_quality import recipes
from evaluation.pr_test_quality.tests.fakes import LANG_FIXTURES
from evaluation.pr_test_quality.tests.test_v5_pipeline import ArchivingPipe, CapturingDocker

PY = LANG_FIXTURES["python"]
FIRST = "%040x" % 1005
SECOND = "%040x" % 2005


class Recording(CapturingDocker):
    def __init__(self, **kw):
        super().__init__(**kw)
        self.dirs = []

    def build(self, context_dir, tag, *, timeout):
        if tag.startswith("evaluation-proj"):
            self.dirs.append(str(context_dir))
        return super().build(context_dir, tag, timeout=timeout)


class FreshContext(ArchivingPipe):
    def setUp(self):
        super().setUp()
        self.docker = Recording(junit_policy=self.junit, exec_policy=self.exec_policy,
                                driver_policy=self.driver, diff_text="")
        self.tar_fails = False

    def git(self, argv, inp):
        if self.tar_fails and argv[:2] == ["sh", "-c"] and "archive" in argv[2]:
            dest = Path(re.search(r"mkdir -p (\S+) && tar", argv[2]).group(1))
            dest.mkdir(parents=True, exist_ok=True)
            (dest / "partial.txt").write_text("half")
            return 2, "", "tar: unexpected end of archive"
        return super().git(argv, inp)

    def archives(self):
        return [a[2] for a in self.run_fn.argvs if a[:2] == ["sh", "-c"] and "archive" in a[2]]

    def candidates_path(self):
        return self.data() / "tasks" / "python" / "candidates.jsonl"

    def rebuild_with_base(self, sha):
        rows = [json.loads(ln) for ln in self.candidates_path().read_text().splitlines() if ln.strip()]
        for row in rows:
            row["base_sha"] = sha
        self.candidates_path().write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
        (self.data() / "tasks" / "python" / "tasks.jsonl").unlink()
        return self.inv(["build", "--language", "python"])

    def project_files(self, index):
        return [files for tag, files in self.docker.contexts if tag.startswith("evaluation-proj")][index]

    def first_build(self):
        self.inv(["mine", "--language", "python"])
        code, out = self.inv(["build", "--language", "python"])
        self.assertEqual(code, 0, out)

    def test_O34_F40_same_task_id_with_a_different_base_sha_extracts_again_into_the_context(self):
        self.first_build()
        self.assertEqual(self.project_files(0)["repo/" + PY["src_path"]].decode(), PY["src_old"])
        code, out = self.rebuild_with_base(SECOND)
        self.assertEqual(code, 0, out)
        archives = self.archives()
        self.assertEqual(len(archives), 2)
        self.assertIn("archive %s" % FIRST, archives[0])
        self.assertIn("archive %s" % SECOND, archives[1])
        self.assertEqual(self.project_files(1)["repo/" + PY["src_path"]].decode(), PY["src_new"])
        self.assertEqual(self.tasks()[0]["base_sha"], SECOND)

    def test_O34_F40_same_base_sha_twice_extracts_once_and_keeps_the_tree(self):
        self.first_build()
        code, out = self.rebuild_with_base(FIRST)
        self.assertEqual(code, 0, out)
        self.assertEqual(len(self.archives()), 1)
        self.assertEqual(self.project_files(1)["repo/" + PY["src_path"]].decode(), PY["src_old"])

    def test_O34_F40_the_old_tree_does_not_survive_a_re_extraction(self):
        self.first_build()
        context = Path(self.docker.dirs[0])
        (context / "repo" / "stale_from_first_tree.txt").write_text("x")
        self.rebuild_with_base(SECOND)
        self.assertNotIn("repo/stale_from_first_tree.txt", self.project_files(1))

    def test_O34_F40_a_missing_repo_directory_forces_re_extraction(self):
        self.first_build()
        shutil.rmtree(Path(self.docker.dirs[0]) / "repo")
        self.rebuild_with_base(FIRST)
        self.assertEqual(len(self.archives()), 2)
        self.assertEqual(self.project_files(1)["repo/" + PY["src_path"]].decode(), PY["src_old"])

    def test_O34_F40_the_sha_record_sits_outside_repo_and_never_enters_repo(self):
        self.first_build()
        context = Path(self.docker.dirs[0])
        record = context / "base_sha"
        self.assertTrue(record.is_file())
        self.assertEqual(record.read_text().strip(), FIRST)
        self.assertFalse((context / "repo" / "base_sha").exists())
        for path, data in self.project_files(0).items():
            if path.startswith("repo/"):
                self.assertNotIn(FIRST.encode(), data)
        self.rebuild_with_base(SECOND)
        self.assertEqual(record.read_text().strip(), SECOND)

    def test_O34_F40_a_failing_extraction_leaves_no_repo_and_marks_build_error(self):
        self.tar_fails = True
        self.inv(["mine", "--language", "python"])
        code, out = self.inv(["build", "--language", "python"])
        self.assertEqual(code, 0, out)
        self.assertEqual([p for p in self.data().rglob("repo") if p.is_dir()], [])
        task = self.tasks()[0]
        self.assertIs(task["valid"], False)
        self.assertTrue(task["reason"].startswith("build_error"))
        self.assertEqual([t for t in self.docker.contexts if t[0].startswith("evaluation-proj")], [])

    def test_O34_F40_a_failure_after_a_good_build_removes_the_old_repo_too(self):
        self.first_build()
        self.tar_fails = True
        self.rebuild_with_base(SECOND)
        self.assertEqual([p for p in self.data().rglob("repo") if p.is_dir()], [])
        self.assertTrue(self.tasks()[0]["reason"].startswith("build_error"))


def jest_argv(files, lock, junit="/o/j.xml"):
    recipe = recipes.detect("typescript", {**lock, "package.json": json.dumps({"devDependencies": {"jest": "29"}})})
    return recipes.test_argv(recipe, files, junit)


def tokens(argv):
    return list(argv) if "--" in argv else shlex.split(argv[-1])


class JestSelection(unittest.TestCase):
    FILES = ["src/b.test.ts", "src/a.test.ts", "test/c.spec.ts"]

    def test_O34_F41_reporter_and_run_tests_by_path_precede_the_double_dash_and_files_follow_in_order(self):
        for lock in ({"yarn.lock": ""}, {"package-lock.json": "{}"}, {"pnpm-lock.yaml": ""}, {"bun.lock": ""}):
            toks = tokens(jest_argv(self.FILES, lock))
            with self.subTest(lock=sorted(lock)):
                self.assertEqual(toks.count("--"), 1)
                cut = toks.index("--")
                self.assertIn("--reporters=jest-junit", toks[:cut])
                self.assertIn("--runTestsByPath", toks[:cut])
                self.assertEqual(toks[cut + 1:], self.FILES)

    def test_O34_F41_the_junit_output_variable_is_kept(self):
        self.assertIn("JEST_JUNIT_OUTPUT_FILE=/o/j.xml", " ".join(jest_argv(self.FILES, {"yarn.lock": ""})))

    def test_O34_F41_a_single_file_still_follows_the_double_dash(self):
        toks = tokens(jest_argv(["src/only.test.ts"], {"yarn.lock": ""}))
        self.assertEqual(toks[toks.index("--") + 1:], ["src/only.test.ts"])

import json
import os
import re
import stat
import subprocess
import sys
import unittest
from pathlib import Path

from evaluation.pr_test_quality import mine, mutants as mutants_mod, recipes
from evaluation.pr_test_quality.tests.fakes import LANG_FIXTURES, ROOT, TOKEN, TmpCase, spec_cfg
from evaluation.pr_test_quality.tests.test_cli import Cli
from evaluation.pr_test_quality.tests.test_mine import FakeGh, pr, sfile, tfile
from evaluation.pr_test_quality.tests.test_v5_pipeline import ArchivingPipe, CapturingDocker, Pipe


class EligibleEdges(unittest.TestCase):
    def check(self, files, reason, **kw):
        ok, got = mine.eligible(pr(**kw), files, spec_cfg())
        self.assertEqual(got, reason)

    def base(self):
        return [sfile("src/a.py", 20), sfile("src/b.py", 20), tfile()]

    def test_O1_G2_file_without_patch_key_and_only_deletions_is_binary(self):
        gone = {"filename": "assets/old.png", "status": "removed", "additions": 0, "deletions": 4}
        self.check(self.base() + [gone], "binary")

    def test_O1_G2_file_without_patch_and_no_changes_is_not_binary(self):
        empty = {"filename": "docs/empty.txt", "status": "added", "additions": 0, "deletions": 0}
        self.check(self.base() + [empty], "ok")

    def test_O1_G3_binary_files_differ_patch_text_is_binary_even_with_a_patch_key(self):
        binary = {"filename": "assets/logo.png", "status": "modified", "additions": 0, "deletions": 0,
                  "patch": "Binary files a/assets/logo.png and b/assets/logo.png differ"}
        self.check(self.base() + [binary], "binary")

    def test_O1_G3_a_normal_patch_mentioning_binary_in_a_comment_line_is_not_binary(self):
        text = sfile("src/c.py", 3, patch="@@ -1 +1,2 @@\n+# handles binary files\n+x = 1\n")
        self.check(self.base() + [text], "ok")


class SearchEdges(TmpCase):
    def test_O2_G4_no_gh_call_is_made_after_the_target_is_reached(self):
        repos = {"own/repo%02d" % i: [10 * i + j for j in range(4)] for i in range(20)}
        gh = FakeGh(repos)
        rows = mine.search("python", self.cfg(mining={"target_per_language": 5}), gh_fn=gh)
        self.assertEqual(len(rows), 5)
        self.assertEqual(len(gh.queries("search/issues")), 2)
        touched = {c.split("/pulls/")[0] for c in gh.calls if "/pulls/" in c}
        self.assertEqual(touched, {"repos/own/repo00", "repos/own/repo01"})
        self.assertEqual(len(gh.queries("search/repositories")), 1)

    def test_O2_G5_merged_at_equal_to_the_cutoff_is_included_and_one_second_earlier_is_not(self):
        class Gh(FakeGh):
            def __call__(inner, args):
                out = super().__call__(args)
                if isinstance(out, dict) and "merged_at" in out:
                    out["merged_at"] = inner.stamp[out["number"]]
                return out
        gh = Gh({"own/solo": [1, 2, 3]})
        gh.stamp = {1: "2026-07-01T00:00:00Z", 2: "2026-06-30T23:59:59Z", 3: "2026-07-01T00:00:01Z"}
        rows = mine.search("python", self.cfg(), gh_fn=gh)
        self.assertEqual([r["pr"] for r in rows], [1, 3])


GH_SHIM = '''#!/bin/sh
echo "$*" >> "$SHIM_LOG"
case "$*" in
  *rate_limit*) cat "$SHIM_DIR/rate_limit.json" 2>/dev/null; [ -f "$SHIM_DIR/rate_limit.json" ] || { echo "no" >&2; exit 1; }; exit 0;;
esac
cat "$SHIM_DIR/stderr.txt" >&2
exit 1
'''


class GhErrors(Cli):
    def stage(self, stderr, rate_limit=None):
        shim_dir = self.tmp / "shim"
        shim_dir.mkdir(exist_ok=True)
        (shim_dir / "stderr.txt").write_text(stderr, encoding="utf-8")
        if rate_limit is not None:
            (shim_dir / "rate_limit.json").write_text(json.dumps(rate_limit), encoding="utf-8")
        gh = self.bin / "gh"
        gh.write_text(GH_SHIM, encoding="utf-8")
        gh.chmod(0o755)
        self.extra = {"SHIM_DIR": str(shim_dir), "SHIM_LOG": str(self.log)}

    def env(self):
        env = super().env()
        env.update(getattr(self, "extra", {}))
        return env

    def test_O26_G6_error_text_carrying_a_reset_epoch_prints_that_epoch(self):
        self.stage("gh: API rate limit exceeded for user (HTTP 403)\nx-ratelimit-reset: 1888888888\n")
        code, out = self.cli("mine", "--language", "python")
        self.assertEqual(code, 3, out)
        self.assertIn("1888888888", out)
        self.assertIn("python3 -m evaluation.pr_test_quality mine --language python", out)

    def test_O26_G6_http_403_without_rate_limit_wording_uses_the_rate_limit_query_reset(self):
        self.stage("gh: HTTP 403: Forbidden\n",
                   {"resources": {"core": {"remaining": 0, "reset": 1999999999},
                                  "search": {"remaining": 0, "reset": 1999999999}}})
        code, out = self.cli("mine", "--language", "python")
        self.assertEqual(code, 3, out)
        self.assertIn("1999999999", out)

    def test_O26_G6_unrelated_failure_still_exits_3_with_unknown_reset(self):
        self.stage("gh: HTTP 500: server error\n")
        code, out = self.cli("mine", "--language", "python")
        self.assertEqual(code, 3, out)
        self.assertIn("unknown", out)

    def test_O26_G6_the_candidate_file_written_so_far_is_named_for_the_rerun(self):
        self.stage("gh: HTTP 403: rate limit exceeded\n")
        code, out = self.cli("mine", "--language", "python")
        self.assertIn("candidates.jsonl", out)


class BuildEdges(Pipe):
    def test_O3_G1_recipe_error_keeps_the_candidate_invalid_and_the_cli_line_shows_it(self):
        self.manifest = ""
        self.inv(["mine", "--language", "python"])
        code, out = self.inv(["build", "--language", "python"])
        self.assertEqual(code, 0, out)
        task = self.tasks()[0]
        self.assertIs(task["valid"], False)
        self.assertTrue(task["reason"].startswith("build_error: "))
        self.assertIn("requirements.txt", task["reason"])
        self.assertIn(task["reason"].split(": ", 1)[1], out)
        self.assertNotIn("built", out)

    def test_O4_G10_failed_build_stores_exactly_the_last_50_log_lines(self):
        lines = ["line %d" % i for i in range(80)]

        class Failing(CapturingDocker):
            def build(inner, context_dir, tag, *, timeout):
                return 1, "\n".join(lines)
        self.docker = Failing()
        self.inv(["mine", "--language", "python"])
        code, out = self.inv(["build", "--language", "python"])
        self.assertEqual(code, 0, out)
        logs = [p for p in self.data().rglob("%s.log" % "own__solo-5")]
        self.assertEqual(len(logs), 1)
        self.assertEqual(logs[0].read_text(encoding="utf-8").rstrip("\n"), "\n".join(lines[-50:]))
        self.assertIs(self.tasks()[0]["valid"], False)
        self.assertTrue(self.tasks()[0]["reason"].startswith("build_error"))

    def test_O4_G10_a_short_log_is_stored_whole(self):
        class Failing(CapturingDocker):
            def build(inner, context_dir, tag, *, timeout):
                return 2, "only\nthree\nlines"
        self.docker = Failing()
        self.inv(["mine", "--language", "python"])
        self.inv(["build", "--language", "python"])
        (log,) = list(self.data().rglob("own__solo-5.log"))
        self.assertEqual(log.read_text(encoding="utf-8").rstrip("\n"), "only\nthree\nlines")


class ContextExtraction(ArchivingPipe):
    def test_O4_G9_the_base_tree_is_extracted_into_exactly_context_repo(self):
        dirs = []

        class Recording(CapturingDocker):
            def build(inner, context_dir, tag, *, timeout):
                dirs.append((tag, str(context_dir)))
                return super().build(context_dir, tag, timeout=timeout)
        self.docker = Recording(junit_policy=self.junit, exec_policy=self.exec_policy, driver_policy=self.driver)
        self.inv(["mine", "--language", "python"])
        self.inv(["build", "--language", "python"])
        project_dir = [d for tag, d in dirs if tag.startswith("evaluation-proj")][0]
        archive = [a for a in self.run_fn.argvs if a[:2] == ["sh", "-c"] and "archive" in a[2]]
        self.assertEqual(len(archive), 1)
        match = re.search(r"tar -x -C (%s/[^/\s)]+)\)?" % re.escape(project_dir), archive[0][2])
        self.assertIsNotNone(match, archive[0][2])
        temp = match.group(1)
        self.assertNotEqual(temp, "%s/repo" % project_dir)
        self.assertIn("mkdir -p %s" % temp, archive[0][2])
        self.assertRegex(archive[0][2], r"&& mv %s %s/repo\s*$" % (re.escape(temp), re.escape(project_dir)))
        self.assertTrue((Path(project_dir) / "repo" / LANG_FIXTURES["python"]["src_path"]).is_file())
        self.assertFalse(Path(temp).exists())
        base_sha = "%040x" % 1005
        self.assertIn("archive %s" % base_sha, archive[0][2])


class DockerfileSyntax(unittest.TestCase):
    FILES = {"python": {"requirements.txt": "pytest\n"},
             "typescript": {"yarn.lock": "", "package.json": json.dumps({"devDependencies": {"vitest": "1"}})},
             "go": {"go.mod": "module m\n\ngo 1.24\n"}, "rust": {"Cargo.toml": "[package]\n"}}
    INSTR = ("FROM", "RUN", "COPY", "ENV", "WORKDIR", "ARG", "USER", "ADD", "LABEL")

    def text(self, language):
        return recipes.dockerfile(recipes.detect(language, self.FILES[language]), spec_cfg())

    def test_O4_G8_every_line_is_a_dockerfile_instruction_or_a_continuation(self):
        for language in self.FILES:
            lines = self.text(language).rstrip("\n").split("\n")
            continued = False
            for line in lines:
                with self.subTest(language=language, line=line[:40]):
                    if continued:
                        pass
                    elif line.strip() and not line.startswith("#"):
                        self.assertIn(line.split()[0], self.INSTR)
                continued = line.endswith("\\")

    def test_O4_G8_the_last_line_is_the_chown_step(self):
        for language in self.FILES:
            last = self.text(language).rstrip("\n").split("\n")[-1]
            with self.subTest(language=language):
                self.assertTrue(last.startswith("RUN "))
                self.assertIn("chown", last)

    def test_O4_G8_typescript_installs_exactly_stryker_core_and_fast_check(self):
        text = self.text("typescript")
        self.assertEqual(sorted(set(re.findall(r"@stryker-mutator/[\w-]+", text))), ["@stryker-mutator/core"])
        self.assertIn("fast-check", text)
        run = [ln for ln in text.splitlines() if "@stryker-mutator/core" in ln]
        self.assertEqual(len(run), 1)
        self.assertIn("fast-check", run[0])

    def test_O4_G8_rust_installs_cargo_mutants_and_cargo_nextest_in_one_valid_instruction(self):
        text = self.text("rust")
        line = [ln for ln in text.splitlines() if "cargo-mutants" in ln]
        self.assertEqual(len(line), 1)
        self.assertTrue(line[0].startswith("RUN "))
        self.assertIn("cargo install", line[0])
        self.assertIn("cargo-nextest", line[0])

    def test_O4_F27_rust_installs_with_the_image_default_toolchain_outside_the_repo(self):
        text = self.text("rust")
        install = [ln for ln in text.splitlines() if "cargo install" in ln][0]
        outside_repo = text.index("cargo install") < text.index("COPY repo/") or re.search(r"cd\s+/\s*&&", install)
        self.assertTrue(outside_repo, install)
        self.assertNotIn("rm -f rust-toolchain", text)
        self.assertNotRegex(text, r"rustup\s+(default|override|toolchain\s+install)")


class BaseImages(unittest.TestCase):
    def go(self, directive):
        return recipes.detect("go", {"go.mod": "module m\n\n%s\n" % directive})["base_image"]

    def test_O3_G7_go_manager_is_go(self):
        self.assertEqual(recipes.detect("go", {"go.mod": "module m\n"})["manager"], "go")

    def test_O4_G11_F27_go_image_follows_the_directive_with_a_1_24_floor(self):
        self.assertEqual(self.go("go 1.15"), "golang:1.24-bookworm")
        self.assertEqual(self.go("go 1.23"), "golang:1.24-bookworm")
        self.assertEqual(self.go("go 1.24"), "golang:1.24-bookworm")
        self.assertEqual(self.go("go 1.25"), "golang:1.25-bookworm")
        self.assertEqual(self.go("go 1.30"), "golang:1.30-bookworm")
        self.assertEqual(self.go("go 1.9"), "golang:1.24-bookworm")

    def test_O4_G11_F27_go_without_a_directive_uses_the_floor(self):
        self.assertEqual(recipes.detect("go", {"go.mod": "module m\n"})["base_image"], "golang:1.24-bookworm")

    def test_O4_G11_F27_rust_uses_the_pinned_image_with_or_without_a_toolchain_file(self):
        plain = recipes.detect("rust", {"Cargo.toml": "[package]\n"})["base_image"]
        pinned = recipes.detect("rust", {"Cargo.toml": "[package]\n",
                                         "rust-toolchain.toml": "[toolchain]\nchannel = \"1.70\"\n"})["base_image"]
        self.assertEqual(plain, recipes.BASE_IMAGES["rust"])
        self.assertEqual(pinned, recipes.BASE_IMAGES["rust"])
        self.assertTrue(plain.startswith("rust:"))
        legacy = recipes.detect("rust", {"Cargo.toml": "[package]\n", "rust-toolchain": "nightly\n"})["base_image"]
        self.assertEqual(legacy, recipes.BASE_IMAGES["rust"])


class NextestFilter(unittest.TestCase):
    def test_O3_G12_two_test_files_produce_a_shell_valid_command_naming_both(self):
        recipe = recipes.detect("rust", {"Cargo.toml": "[package]\nname='x'\n"})
        for selection in (["tests/one.rs"], ["tests/one.rs", "tests/two.rs"], ["tests/one.rs", "tests/two.rs", "tests/three.rs"]):
            argv = recipes.test_argv(recipe, selection, "/o/j.xml")
            with self.subTest(selection=selection):
                proc = subprocess.run(["sh", "-n", "-c", argv[-1]] if argv[:2] == ["sh", "-c"] else ["true"],
                                      capture_output=True, text=True)
                self.assertEqual(proc.returncode, 0, proc.stderr)
                text = " ".join(argv)
                for path in selection:
                    self.assertIn(Path(path).stem, text)
                self.assertEqual(text.count("--profile junit"), 1)

    def test_O3_G12_run_tests_with_two_rust_files_is_ok_not_build_error(self):
        from evaluation.pr_test_quality import testrun
        from evaluation.pr_test_quality.tests.fakes import FakeDocker, make_task
        docker = FakeDocker(junit_policy=lambda c: '<testsuites><testsuite name="calc"><testcase classname="calc" name="t"/></testsuite></testsuites>')
        task = make_task("rust", recipe=recipes.detect("rust", {"Cargo.toml": "[package]\n"}))
        with __import__("tempfile").TemporaryDirectory() as cache:
            out = testrun.run_tests(task, {"src/lib.rs": "x\n"}, ["tests/one.rs", "tests/two.rs"], docker=docker,
                                    cfg=spec_cfg(), cache_dir=cache)
        self.assertEqual(out["status"], "ok")
        self.assertEqual(out["results"], {"calc::t": "pass"})


class NormalizeLines(unittest.TestCase):
    def test_O30_G20_line_is_the_new_side_number_of_the_first_plus_line(self):
        text = ("--- src/a.py\n+++ src/a.py\n@@ -10,4 +10,3 @@\n ctx1\n ctx2\n-old1\n-old2\n+new\n")
        for tool in ("mutmut", "go-mutesting"):
            (item,) = mutants_mod.normalize(tool, text)
            with self.subTest(tool=tool):
                self.assertEqual(item["line"], 12)
                self.assertEqual(item["diff"], text)
                self.assertEqual(item["path"], "src/a.py")

    def test_O30_G20_a_plus_header_line_is_never_taken_as_the_replacement(self):
        text = "--- src/a.py\n+++ src/a.py\n@@ -3,2 +3,2 @@\n keep\n-a\n+b\n"
        (item,) = mutants_mod.normalize("mutmut", text)
        self.assertEqual(item["line"], 4)

    def test_O30_G20_deletion_only_hunk_uses_the_first_changed_position(self):
        text = "--- src/a.py\n+++ src/a.py\n@@ -3,3 +3,2 @@\n keep\n-gone\n tail\n"
        (item,) = mutants_mod.normalize("mutmut", text)
        self.assertEqual(item["line"], 4)

    def test_O30_G20_two_blocks_keep_their_own_diff_text_and_line(self):
        a = "--- x.py\n+++ x.py\n@@ -1,1 +1,1 @@\n-a\n+b\n"
        b = "--- x.py\n+++ x.py\n@@ -9,2 +9,2 @@\n c\n-d\n+e\n"
        items = mutants_mod.normalize("mutmut", a + b)
        self.assertEqual(sorted((i["line"], i["diff"]) for i in items), sorted([(1, a), (10, b)]))

    def test_O30_G21_apply_diff_removes_exactly_the_removed_line(self):
        out = mutants_mod.apply_diff("a\nb\nc\n", "--- x\n+++ x\n@@ -1,3 +1,2 @@\n a\n-b\n c\n")
        self.assertEqual(out, "a\nc\n")
        out = mutants_mod.apply_diff("a\nb\nb\nc\n", "--- x\n+++ x\n@@ -2,2 +2,1 @@\n-b\n b\n")
        self.assertEqual(out, "a\nb\nc\n")

    def test_O30_G21_apply_diff_replaces_and_adds_lines(self):
        out = mutants_mod.apply_diff("a\nb\nc\n", "--- x\n+++ x\n@@ -2,1 +2,2 @@\n-b\n+B\n+B2\n")
        self.assertEqual(out, "a\nB\nB2\nc\n")


class PythonListing(Pipe):
    def test_O30_G22_F26_python_mutants_come_from_the_in_container_mutmut_api_script(self):
        self.stage("brief")
        seen = []

        def policy(c, argv):
            joined = " ".join(argv)
            seen.append(joined)
            if "list_mutations" in joined:
                from evaluation.pr_test_quality.tests.test_pipeline import MUTMUT
                return 0, MUTMUT, False
            return None
        self.docker.exec_policy = policy
        files = []
        orig = self.docker.container

        code, out = self.inv(["mutants", "--language", "python"])
        self.assertEqual(code, 0, out)
        script = [s for s in seen if "list_mutations" in s]
        self.assertTrue(script, seen)
        text = script[0]
        for needle in ("list_mutations", "mutate", "src/calc/ops.py"):
            self.assertIn(needle, text)
        self.assertNotIn("mutmut run", text)
        self.assertFalse([s for s in seen if re.search(r"\bmutmut (run|results|show)\b", s)])
        mutants = self.tasks()[0]["mutants"]
        self.assertEqual(len(mutants), 2)
        self.assertEqual({m["path"] for m in mutants}, {"src/calc/ops.py"})

    def test_O30_G22_only_changed_src_files_are_listed(self):
        self.stage("brief")
        seen = []
        self.docker.exec_policy = lambda c, argv: (seen.append(" ".join(argv)) or None)
        self.inv(["mutants", "--language", "python"])
        listing = [s for s in seen if "list_mutations" in s]
        self.assertTrue(listing)
        self.assertNotIn("tests/test_ops.py", listing[0])

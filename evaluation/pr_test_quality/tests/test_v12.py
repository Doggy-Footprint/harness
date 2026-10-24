import hashlib
import json
import os
import re
import stat
import subprocess
import tempfile
import tomllib
import unittest
from pathlib import Path

from evaluation.pr_test_quality import mutants, recipes, validate
from evaluation.pr_test_quality.tests.fakes import LANG_FIXTURES, make_task, pytest_junit, spec_cfg, udiff
from evaluation.pr_test_quality.tests.test_pipeline import Pipe
from evaluation.pr_test_quality.tests.test_v11 import xml_for

PY = LANG_FIXTURES["python"]
GO = LANG_FIXTURES["go"]
OLD = "def test_old_a(): pass\ndef test_old_b(): pass\n"
NEW = OLD + "def test_new_behavior(): pass\n"
OPS = "tests/test_ops.py"
EXTRA = "tests/test_extra.py"
EXTRA_TEXT = "def test_extra(): pass\n"


def names(text):
    return re.findall(r"def (test_\w+)", text or "")


def runner_containers(docker):
    return [c for c in docker.containers
            if any(re.search(r"pytest|gotestsum", " ".join(e["argv"])) for e in c.execs)]


def runner_argv(cont):
    return [e["argv"] for e in cont.execs if re.search(r"pytest|gotestsum", " ".join(e["argv"]))][0]


class SelectionTask(unittest.TestCase):
    def task(self, base, after):
        split = "".join(udiff(p, base.get(p), after.get(p)) for p in sorted(after) if p != PY["src_path"])
        return make_task("python", gold_base=dict(base, **{PY["src_path"]: PY["src_old"]}),
                         gold_after=dict(after, **{PY["src_path"]: PY["src_new"]}),
                         gold_split={"src": udiff(PY["src_path"], PY["src_old"], PY["src_new"]), "tests": split,
                                     "harness": "", "other": ""})

    def test_O5_C43_F35_deleted_gold_test_files_are_left_out(self):
        task = self.task({OPS: OLD, EXTRA: EXTRA_TEXT}, {OPS: NEW, EXTRA: None})
        self.assertEqual(sorted(validate.gold_selection(task)), [OPS])

    def test_O5_C43_F35_only_deletions_give_an_empty_selection(self):
        task = self.task({EXTRA: EXTRA_TEXT}, {EXTRA: None})
        self.assertEqual(list(validate.gold_selection(task)), [])

    def test_O5_F35_new_and_modified_test_files_stay(self):
        task = self.task({OPS: OLD, EXTRA: None}, {OPS: NEW, EXTRA: EXTRA_TEXT})
        self.assertEqual(sorted(validate.gold_selection(task)), [EXTRA, OPS])


class ValidateRuns(Pipe):
    def patch(self, lang, base, after, *, src=True):
        fx = LANG_FIXTURES[lang]
        out = {}
        if lang == "go":
            out["language"] = "go"
            out["recipe"] = recipes.detect("go", {"go.mod": "module m\n\ngo 1.24\n"})
        files = sorted(after)
        out["gold_split"] = {"src": udiff(fx["src_path"], fx["src_old"], fx["src_new"]),
                             "tests": "".join(udiff(p, base.get(p), after.get(p)) for p in files),
                             "harness": "", "other": ""}
        out["gold_base"] = dict(base, **{fx["src_path"]: fx["src_old"]})
        out["gold_after"] = dict(after, **{fx["src_path"]: fx["src_new"]})
        return out

    def validate_with(self, patch, policy, repeats=None):
        self.stage("build")
        row = self.tasks()[0]
        row.update(patch)
        lang = row["language"]
        (self.data() / "tasks" / lang).mkdir(parents=True, exist_ok=True)
        (self.data() / "tasks" / lang / "tasks.jsonl").write_text(json.dumps(row) + "\n", encoding="utf-8")
        if repeats:
            self.cfg_["validation"]["repeats"] = repeats
        self.docker.junit_policy = policy
        before = len(runner_containers(self.docker))
        code, out = self.inv(["validate", "--language", lang, "--force"])
        self.assertEqual(code, 0, out)
        self.ran = runner_containers(self.docker)[before:]
        return self.tasks(lang)[0]

    def state(self, cont, test_path, old, new, src_marker):
        text = next((v for k, v in cont.files().items() if k.endswith(test_path)), None)
        if src_marker in cont.tree_text():
            return "merge"
        return "orig" if text == old else "base" if text == new else "other"

    def py_policy(self, old, new, orig=None):
        def policy(cont):
            state = self.state(cont, OPS, old, new, "def clamp")
            if state == "orig" and orig is not None:
                return orig(cont)
            res = {}
            for path, text in cont.files().items():
                for p in (OPS, EXTRA):
                    if path.endswith(p):
                        for n in names(text):
                            fresh = n not in names(old)
                            res["%s::%s" % (p, n)] = "fail" if (state == "base" and fresh) else "pass"
            return pytest_junit(res)
        return policy

    def by_state(self, cont_list, test_path, old, new, marker):
        out = {"orig": [], "base": [], "merge": []}
        for c in cont_list:
            out.setdefault(self.state(c, test_path, old, new, marker), []).append(c)
        return out

    def sel(self, cont, paths):
        argv = " ".join(runner_argv(cont))
        return sorted(p for p in paths if p in argv)

    def test_O5_F36_orig_state_runs_repeats_times_on_gold_base_tree_with_existing_paths_only(self):
        old = OLD
        task = self.validate_with(self.patch("python", {OPS: old, EXTRA: None}, {OPS: NEW, EXTRA: EXTRA_TEXT}),
                                  self.py_policy(old, NEW))
        states = self.by_state(self.ran, OPS, old, NEW, "def clamp")
        self.assertEqual(len(states["orig"]), 3)
        self.assertEqual(len(states["base"]), 3)
        self.assertEqual(len(states["merge"]), 3)
        for cont in states["orig"]:
            self.assertEqual(self.sel(cont, [OPS, EXTRA]), [OPS])
            self.assertNotIn("def test_extra", cont.tree_text())
        for cont in states["base"] + states["merge"]:
            self.assertEqual(self.sel(cont, [OPS, EXTRA]), [EXTRA, OPS])
        self.assertTrue(task["valid"])
        self.assertEqual(sorted(task["f2p"]), [EXTRA + "::test_extra", OPS + "::test_new_behavior"])
        self.assertEqual(sorted(task["p2p"]), [OPS + "::test_old_a", OPS + "::test_old_b"])
        self.assertIn("p2p_note", task)
        self.assertIsNone(task["p2p_note"])

    def test_O5_F36_orig_repeat_count_follows_cfg_validation_repeats(self):
        self.validate_with(self.patch("python", {OPS: OLD}, {OPS: NEW}), self.py_policy(OLD, NEW), repeats=2)
        states = self.by_state(self.ran, OPS, OLD, NEW, "def clamp")
        self.assertEqual([len(states[k]) for k in ("orig", "base", "merge")], [2, 2, 2])

    def test_O5_F36_orig_flaky_id_is_excluded_from_p2p(self):
        calls = []

        def flaky(cont):
            calls.append(1)
            status = "fail" if len(calls) % 2 else "pass"
            return pytest_junit({OPS + "::test_old_a": status, OPS + "::test_old_b": "pass"})
        task = self.validate_with(self.patch("python", {OPS: OLD}, {OPS: NEW}), self.py_policy(OLD, NEW, orig=flaky))
        self.assertEqual(task["p2p"], [OPS + "::test_old_b"])
        self.assertTrue(task["valid"])

    def test_O5_C45_orig_error_statuses_keep_the_task_valid_with_empty_p2p_and_a_note(self):
        cases = {"build_error": None, "timeout": "timeout", "parse_error": "<testsuites><testsuite"}
        for note, result in cases.items():
            self.setUp()
            task = self.validate_with(self.patch("python", {OPS: OLD}, {OPS: NEW}),
                                      self.py_policy(OLD, NEW, orig=lambda c, r=result: r))
            with self.subTest(note=note):
                self.assertTrue(task["valid"])
                self.assertEqual(task["reason"], "ok")
                self.assertEqual(task["f2p"], [OPS + "::test_new_behavior"])
                self.assertEqual(task["p2p"], [])
                self.assertEqual(task["p2p_note"], note)

    def test_O5_F36_empty_orig_selection_runs_nothing_for_orig_and_notes_no_base_tests(self):
        task = self.validate_with(self.patch("python", {OPS: None}, {OPS: NEW}), self.py_policy(None, NEW))
        self.assertEqual(len(self.ran), 6)
        for cont in self.ran:
            self.assertIn("test_new_behavior", cont.tree_text())
        self.assertTrue(task["valid"])
        self.assertEqual(task["p2p"], [])
        self.assertEqual(task["p2p_note"], "no_base_tests")

    def test_O5_C43_F35_deletion_only_gold_tests_run_nothing_and_are_no_f2p(self):
        task = self.validate_with(self.patch("python", {OPS: OLD}, {OPS: None}), self.py_policy(OLD, NEW))
        self.assertEqual(self.ran, [])
        self.assertFalse(task["valid"])
        self.assertEqual(task["reason"], "no_f2p")
        self.assertEqual(task["f2p"], [])
        self.assertEqual(task["p2p_note"], "no_base_tests")

    def test_O5_C43_F35_deleted_file_is_in_no_selection_when_another_file_changes(self):
        self.validate_with(self.patch("python", {OPS: OLD, EXTRA: EXTRA_TEXT}, {OPS: NEW, EXTRA: None}),
                           self.py_policy(OLD, NEW))
        self.assertEqual(len(self.ran), 9)
        for cont in self.ran:
            self.assertEqual(self.sel(cont, [OPS, EXTRA]), [OPS])

    def go_policy(self, old, new, orig_ids=None, base_all_fail=True):
        def policy(cont):
            state = self.state(cont, GO["test_path"], old, new, "func Clamp")
            ids = ["ops::TestOld", "ops::TestNew"]
            if state == "orig":
                return xml_for("go", {i: "pass" for i in (orig_ids if orig_ids is not None else ["ops::TestOld"])})
            return xml_for("go", {i: ("pass" if state == "merge" else "fail") for i in ids})
        return policy

    GOLD_OLD = "package ops\n\nfunc TestOld(t *testing.T) {}\n"
    GOLD_NEW = GOLD_OLD + "func TestNew(t *testing.T) {}\n"

    def test_O5_C44_compile_failure_at_base_keeps_the_existing_test_in_p2p_and_only_the_new_one_in_f2p(self):
        task = self.validate_with(self.patch("go", {GO["test_path"]: self.GOLD_OLD}, {GO["test_path"]: self.GOLD_NEW}),
                                  self.go_policy(self.GOLD_OLD, self.GOLD_NEW))
        self.assertTrue(task["valid"])
        self.assertEqual(task["f2p"], ["ops::TestNew"])
        self.assertEqual(task["p2p"], ["ops::TestOld"])
        self.assertIsNone(task["p2p_note"])

    def test_O5_F36_validate_task_removes_final_f2p_ids_from_p2p(self):
        task = self.validate_with(self.patch("go", {GO["test_path"]: self.GOLD_OLD}, {GO["test_path"]: self.GOLD_NEW}),
                                  self.go_policy(self.GOLD_OLD, self.GOLD_NEW,
                                                 orig_ids=["ops::TestOld", "ops::TestNew"]))
        self.assertEqual(task["f2p"], ["ops::TestNew"])
        self.assertEqual(task["p2p"], ["ops::TestOld"])

    def test_O5_F36_go_orig_selection_equals_the_gold_selection(self):
        task = self.validate_with(self.patch("go", {GO["test_path"]: None}, {GO["test_path"]: self.GOLD_NEW}),
                                  self.go_policy(None, self.GOLD_NEW, orig_ids=[]))
        states = self.by_state(self.ran, GO["test_path"], None, self.GOLD_NEW, "func Clamp")
        self.assertEqual(len(states["orig"]), 3)
        gold_argv = runner_argv(states["base"][0])
        for cont in states["orig"]:
            self.assertEqual(runner_argv(cont), gold_argv)
            self.assertNotIn("func TestNew", cont.tree_text())
        self.assertEqual(task["p2p"], [])
        self.assertIsNone(task["p2p_note"])


def run_text(command):
    if isinstance(command, str):
        return command
    if len(command) >= 3 and command[1] in ("-c", "-lc", "-ec"):
        return command[2]
    return " ".join(command)


DIFF_SCRIPT = "/tmp/evaluation-mutesting-diff.sh"
PATHS = ["active_help.go", "doc/man_docs.go"]


class GoMutestingCommand(unittest.TestCase):
    def command(self):
        return run_text(mutants.list_command("go", PATHS))

    def test_O32_F37_command_runs_go_mutesting_only_with_the_exec_script(self):
        text = self.command()
        calls = re.findall(r"go-mutesting\b[^\n;&|]*", text)
        self.assertTrue(calls, text)
        for call in calls:
            self.assertIn("--exec %s" % DIFF_SCRIPT, call)
        self.assertIn("2>&1", text)

    def test_O32_F37_command_never_falls_back_to_the_built_in_exec(self):
        text = self.command()
        self.assertEqual(len(re.findall(r"go-mutesting", text.replace("evaluation-mutesting", ""))), 1)
        self.assertNotRegex(text, r"go-mutesting\s+(?!--exec)")
        self.assertNotIn("--debug", text)

    def test_O32_F37_command_names_each_target_directory(self):
        text = self.command()
        self.assertIn("doc", text.split("--exec", 1)[1])

    def test_O32_F37_executing_the_command_creates_the_exact_executable_script(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            bindir = tmp / "bin"
            bindir.mkdir()
            record = tmp / "args.txt"
            fake = bindir / "go-mutesting"
            fake.write_text('#!/bin/sh\nprintf "%s\\n" "$@" > ' + str(record) + "\n", encoding="utf-8")
            fake.chmod(0o755)
            (tmp / "testbed").mkdir()
            script = tmp / "evaluation-mutesting-diff.sh"
            text = self.command().replace(DIFF_SCRIPT, str(script)).replace("/testbed", str(tmp / "testbed"))
            env = dict(os.environ, PATH="%s:%s" % (bindir, os.environ["PATH"]))
            done = subprocess.run(["sh", "-c", text], cwd=tmp, env=env, capture_output=True, text=True)
            self.assertEqual(done.returncode, 0, done.stderr)
            self.assertEqual(script.read_bytes(),
                             b'#!/bin/sh\ndiff -u "$MUTATE_ORIGINAL" "$MUTATE_CHANGED"\nexit 0\n')
            self.assertTrue(script.stat().st_mode & stat.S_IXUSR)
            self.assertEqual(stat.S_IMODE(script.stat().st_mode) & 0o755, 0o755)
            args = record.read_text().split()
            self.assertEqual(args[:2], ["--exec", str(script)])


CAPTURE = (
    "/testbed/active_help.go:27:28: undefined: X\n"
    "/testbed/active_help.go:30:2: undefined: Y\n"
    "--- active_help.go\t2026-04-24 20:41:57.000000000 +0000\n"
    "+++ /tmp/go-mutesting-2148272493/active_help.go.0\t2026-04-24 20:41:58.000000000 +0000\n"
    "@@ -24,7 +24,7 @@\n"
    " \n"
    " func a() {\n"
    " \tx := 1\n"
    "-\tif x < 2 {\n"
    "+\tif x <= 2 {\n"
    " \t\treturn\n"
    " \t}\n"
    "PASS \"/tmp/go-mutesting-2148272493/active_help.go.0\" with checksum 0123456789abcdef0123456789abcdef\n"
    "----------------------------------------------------------------------------------------------------\n"
    "--- active_help.go\t2026-04-24 20:41:57.000000000 +0000\n"
    "+++ /tmp/go-mutesting-2148272493/active_help.go.1\t2026-04-24 20:41:58.000000000 +0000\n"
    "@@ -40,6 +40,6 @@\n"
    " func b() {\n"
    "-\treturn a + b\n"
    "+\treturn a - b\n"
    " }\n"
    " \n"
    "PASS \"/tmp/go-mutesting-2148272493/active_help.go.1\" with checksum fedcba9876543210fedcba9876543210\n"
    "----------------------------------------------------------------------------------------------------\n"
    "--- doc/man_docs.go\t2026-04-24 20:41:57.000000000 +0000\n"
    "+++ /tmp/go-mutesting-2148272493/doc/man_docs.go.0\t2026-04-24 20:41:59.000000000 +0000\n"
    "@@ -10,7 +10,7 @@\n"
    " \n"
    " func c() {\n"
    "-\tfor i := 0; i < n; i++ {\n"
    "+\tfor i := 0; i <= n; i++ {\n"
    " \t}\n"
    " }\n"
    "PASS \"/tmp/go-mutesting-2148272493/doc/man_docs.go.0\" with checksum 00112233445566778899aabbccddeeff\n"
    "----------------------------------------------------------------------------------------------------\n"
    "The mutation score is 0.000000 (0 passed, 3 failed, 0 duplicated, 0 skipped, total is 3)\n"
)


class GoMutestingNormalize(unittest.TestCase):
    def rows(self, raw=CAPTURE):
        return mutants.normalize("go-mutesting", raw)

    def test_O32_C46_F37_one_row_per_block_with_paths_relative_to_testbed(self):
        rows = self.rows()
        self.assertEqual(sorted((r["path"], r["line"]) for r in rows),
                         [("active_help.go", 27), ("active_help.go", 41), ("doc/man_docs.go", 12)])

    def test_O32_F37_line_is_the_first_changed_line_of_the_hunk(self):
        by = {(r["path"], r["line"]): r for r in self.rows()}
        self.assertIn("x < 2", by[("active_help.go", 27)]["diff"])
        self.assertIn("a - b", by[("active_help.go", 41)]["diff"])
        self.assertIn("i <= n", by[("doc/man_docs.go", 12)]["diff"])

    def test_O32_F37_ids_follow_the_sha256_formula_and_differ_per_block(self):
        rows = self.rows()
        for r in rows:
            want = hashlib.sha256(("%s\0%s\0%s" % (r["path"], r["line"], r["diff"])).encode()).hexdigest()[:16]
            self.assertEqual(r["id"], want)
        self.assertEqual(len({r["id"] for r in rows}), 3)

    def test_O32_F37_compiler_noise_pass_and_dash_lines_stay_out_of_the_diffs(self):
        for r in self.rows():
            self.assertNotIn("undefined:", r["diff"])
            self.assertNotIn("PASS", r["diff"])
            self.assertNotIn("checksum", r["diff"])
            self.assertNotIn("-----------", r["diff"])
            self.assertNotIn("mutation score", r["diff"])

    def test_O32_F37_absolute_testbed_original_paths_are_made_relative(self):
        raw = CAPTURE.replace("--- doc/man_docs.go", "--- /testbed/doc/man_docs.go")
        self.assertIn(("doc/man_docs.go", 12), [(r["path"], r["line"]) for r in self.rows(raw)])

    def test_O32_F37_output_without_blocks_gives_no_rows(self):
        self.assertEqual(self.rows("/testbed/a.go:1:1: undefined: X\nThe mutation score is 0\n"), [])


class NextestConfigStep(unittest.TestCase):
    def dockerfile(self):
        recipe = recipes.detect("rust", {"Cargo.toml": "[package]\nname = \"calc\"\nversion = \"0.1.0\"\n"})
        return recipes.dockerfile(recipe, spec_cfg())

    def instructions(self, text):
        out, cur = [], ""
        for line in text.splitlines():
            if cur:
                cur += "\n" + line
            else:
                cur = line
            if cur.rstrip().endswith("\\"):
                cur = cur.rstrip()[:-1]
                continue
            out.append(cur)
            cur = ""
        return out

    def test_O32_F38_the_run_step_writes_a_valid_toml_with_the_exact_bytes(self):
        text = self.dockerfile()
        steps = self.instructions(text)
        env_path = None
        for step in steps:
            m = re.match(r"ENV\s+NEXTEST_CONFIG[= ]\s*(\S+)", step)
            if m:
                env_path = m.group(1).strip('"')
        run = [s for s in steps if s.startswith("RUN") and "profile.junit" in s]
        self.assertEqual(len(run), 1, steps)
        script = run[0][3:].strip()
        if script.startswith("["):
            script = json.loads(script)[-1]
        if env_path is None:
            env_path = re.search(r"(/[\w./-]+\.toml)", script).group(1)
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            target = tmp / "etc" / "nextest.toml"
            bindir = tmp / "bin"
            bindir.mkdir()
            for tool in ("cargo", "rustup", "apt-get", "curl", "chown", "chmod"):
                p = bindir / tool
                p.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
                p.chmod(0o755)
            parent = os.path.dirname(env_path)
            script = script.replace(env_path, str(target)).replace(parent, str(target.parent))
            env = dict(os.environ, NEXTEST_CONFIG=str(target), PATH="%s:%s" % (bindir, os.environ["PATH"]))
            done = subprocess.run(["sh", "-c", script], cwd=tmp, env=env, capture_output=True, text=True)
            self.assertEqual(done.returncode, 0, done.stderr)
            raw = target.read_bytes()
        self.assertEqual(raw, b'[profile.junit.junit]\npath = "junit.xml"\n')
        self.assertEqual(tomllib.loads(raw.decode()), {"profile": {"junit": {"junit": {"path": "junit.xml"}}}})

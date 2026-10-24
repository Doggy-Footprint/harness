import hashlib
import json
import random
import re
import shutil
import unittest
from pathlib import Path

from evaluation.pr_test_quality import crossarm, gce, mutants as mutants_mod
from evaluation.pr_test_quality.tests.fakes import (
    LANG_FIXTURES, TOKEN, FakeDocker, TmpCase, make_task, pytest_junit, set_token_file, spec_cfg, udiff,
)
from evaluation.pr_test_quality.tests.test_gce import Gcloud, has_flag, kind_of
from evaluation.pr_test_quality.tests.test_pipeline import F2P, MUTMUT, TASK_ID, Pipe, RunScoreJudgeReport
from evaluation.pr_test_quality.tests.test_score import (
    AGENT_TEST, BASE_SRC, GOLD_SRC, GOLD_TEST, SRC, World,
)


class CapturingDocker(FakeDocker):
    def __init__(self, **kw):
        super().__init__(**kw)
        self.contexts = []

    def build(self, context_dir, tag, *, timeout):
        files = {}
        root = Path(context_dir)
        for path in sorted(root.rglob("*")):
            if path.is_file():
                files[path.relative_to(root).as_posix()] = path.read_bytes()
        self.contexts.append((tag, files))
        return super().build(context_dir, tag, timeout=timeout)


class ArchivingPipe(Pipe):
    """Pipe whose fake git materializes the archived tree for the requested sha."""

    def setUp(self):
        super().setUp()
        self.docker = CapturingDocker(junit_policy=self.junit, exec_policy=self.exec_policy,
                                      driver_policy=self.driver, diff_text="")

    def git(self, argv, inp):
        text = " ".join(argv)
        m = re.search(r"archive (\S+) \| \(mkdir -p (\S+) && tar", text)
        if argv[:2] == ["sh", "-c"] and m:
            sha, dest = m.group(1), Path(m.group(2))
            fx = LANG_FIXTURES["python"]
            dest.mkdir(parents=True, exist_ok=True)
            (dest / "src" / "calc").mkdir(parents=True, exist_ok=True)
            (dest / fx["src_path"]).write_text(fx["src_old"] if sha.endswith("3ed") else fx["src_new"])
            (dest / "requirements.txt").write_text(self.manifest)
            moved = re.search(r"&& mv (\S+) (\S+)\s*$", text)
            if moved:
                shutil.move(moved.group(1), moved.group(2))
            return 0, "", ""
        return super().git(argv, inp)


class BuildContext(ArchivingPipe):
    def test_O4_F10_context_holds_the_base_src_and_nothing_gold(self):
        self.inv(["mine", "--language", "python"])
        code, out = self.inv(["build", "--language", "python"])
        self.assertEqual(code, 0, out)
        fx = LANG_FIXTURES["python"]
        self.assertTrue(self.docker.contexts)
        merge_sha = "%040x" % 5
        for tag, files in self.docker.contexts:
            blob = "\n".join(v.decode("utf-8", "replace") for v in files.values())
            with self.subTest(tag=tag):
                for secret in ("five-marker-zq", "build_gold_fixture_zq", "test_clamp_upper_bound_zq",
                               "test_param_case_zq", merge_sha, "tests/test_ops.py"):
                    self.assertNotIn(secret, blob)
                self.assertFalse([p for p in files if p.startswith(".git/") or "/.git/" in p])
        project = [files for tag, files in self.docker.contexts if tag.startswith("evaluation-proj")][0]
        self.assertEqual(project["repo/" + fx["src_path"]].decode(), fx["src_old"])
        self.assertNotIn("def clamp", project["repo/" + fx["src_path"]].decode())
        self.assertNotIn("repo/tests/test_ops.py", project)

    def test_O4_QR9_dockerfiles_make_one_commit_without_remote_or_tags(self):
        self.inv(["mine", "--language", "python"])
        self.inv(["build", "--language", "python"])
        for tag, files in self.docker.contexts:
            text = files["Dockerfile"].decode()
            with self.subTest(tag=tag):
                self.assertNotRegex(text, r"git\s+(remote|tag|fetch|pull|clone)")
                if tag.startswith("evaluation-proj"):
                    self.assertEqual(len(re.findall(r"git\b[^\n]*\bcommit\b", text)), 1)
                    self.assertIn("git init", text)
                else:
                    self.assertNotIn("git init", text)

    def test_O4_agent_context_is_a_separate_layer_without_the_repo(self):
        self.inv(["mine", "--language", "python"])
        self.inv(["build", "--language", "python"])
        agent = [files for tag, files in self.docker.contexts if tag.startswith("evaluation-agent")][0]
        self.assertFalse([p for p in agent if p.startswith("repo/")])


class ValidateRuns(Pipe):
    def test_O5_F21_six_runs_with_the_gold_test_files_and_the_validation_timeout(self):
        self.stage("build")
        before = len(self.docker.containers)
        code, out = self.inv(["validate", "--language", "python"])
        self.assertEqual(code, 0, out)
        runs = self.docker.containers[before:]
        self.assertEqual(len(runs), 6)
        merged = 0
        for cont in runs:
            pytest = [e for e in cont.execs if "pytest" in " ".join(e["argv"])]
            self.assertEqual(len(pytest), 1)
            argv = pytest[0]["argv"]
            self.assertIn("tests/test_ops.py", argv)
            self.assertEqual([a for a in argv if a.endswith(".py")], ["tests/test_ops.py"])
            self.assertEqual(pytest[0]["timeout"], 600)
            self.assertIn(cont.kwargs["network"], (False, "none", None))
            merged += "def clamp" in cont.tree_text()
        self.assertEqual(merged, 3)

    def test_O5_F21_runs_are_distinct_cache_entries_so_repeats_are_not_collapsed(self):
        self.stage("build")
        self.docker.junit_policy = lambda c: pytest_junit({k: "pass" for k in F2P})
        before = self.docker.runs
        self.inv(["validate", "--language", "python"])
        self.assertEqual(self.docker.runs - before, 6)


class ErrorRemedies(RunScoreJudgeReport):
    def test_O26_F18_no_valid_tasks_names_validate_and_brief(self):
        (self.data() / "tasks" / "python" / "tasks.jsonl").write_text("", encoding="utf-8")
        code, out = self.do_run()
        self.assertEqual(code, 2, out)
        self.assertIn("python3 -m evaluation.pr_test_quality validate --language python", out)
        self.assertIn("python3 -m evaluation.pr_test_quality brief --language python", out)

    def test_O26_F18_main_phase_with_only_pilot_tasks_names_mine(self):
        path = self.data() / "tasks" / "python" / "tasks.jsonl"
        rows = [json.loads(ln) for ln in path.read_text().splitlines()]
        for row in rows:
            row["pilot"] = True
        path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
        code, out = self.inv(["run", "--phase", "main", "--language", "python", "--arms", "B0", "--repeats", "1"])
        self.assertEqual(code, 2, out)
        self.assertIn("pilot", out)
        self.assertIn("excluded", out)
        self.assertIn("python3 -m evaluation.pr_test_quality mine --language python", out)

    def test_O26_F18_unknown_arm_lists_the_valid_arms(self):
        code, out = self.inv(["run", "--phase", "dev", "--language", "python", "--arms", "B0,Nope"])
        self.assertEqual(code, 2, out)
        for arm in ("B0", "Bplus", "H"):
            self.assertIn(arm, out)
        self.assertIn("Nope", out)

    def test_O26_F18_unknown_run_id_names_the_runs_directory_for_every_command(self):
        runs_dir = str(self.data() / "runs")
        for argv in (["score", "nope"], ["judge", "nope"], ["report", "nope"], ["run", "--resume", "nope"],
                     ["run", "--retry-errors", "nope"]):
            code, out = self.inv(argv)
            with self.subTest(argv=argv):
                self.assertEqual(code, 2, out)
                self.assertIn(runs_dir, out)

    def test_O26_F18_missing_token_names_the_expected_path(self):
        self.token_path.unlink()
        code, out = self.do_run()
        self.assertEqual(code, 2, out)
        self.assertIn(str(self.token_path), out)

    def test_O26_F18_missing_image_names_the_build_command_for_the_language(self):
        self.docker = FakeDocker(missing_images=[self.tasks()[0]["image"].replace("proj", "agent")])
        code, out = self.do_run()
        self.assertEqual(code, 2, out)
        self.assertIn("python3 -m evaluation.pr_test_quality build --language python", out)

    def test_O26_F18_purge_without_yes_names_the_flag(self):
        code, out = self.inv(["gce", "down", "--purge"])
        self.assertEqual(code, 2, out)
        self.assertIn("--yes", out)

    def test_O23_v6_report_token_in_run_json_names_the_file_and_not_the_token(self):
        self.do_run()
        (rid,) = self.run_ids()
        path = self.data() / "runs" / rid / "run.json"
        data = json.loads(path.read_text())
        data["params"]["harness_ref"] = TOKEN
        path.write_text(json.dumps(data))
        code, out = self.inv(["report", rid])
        self.assertEqual(code, 2, out)
        self.assertIn("run.json", out)
        self.assertNotIn(TOKEN, out)


class Mutants(Pipe):
    def lines(self, n, prefix="x"):
        out = []
        for i in range(n):
            out.append("--- src/calc/ops.py\n+++ src/calc/ops.py\n@@ -5,2 +5,2 @@\n def clamp(value, lo, hi):\n"
                       "-    return max(lo, min(value, hi))\n+    return max(lo, min(value, hi)) + %s%d\n" % (prefix, i))
        return "".join(out)

    def run_mutants(self, text, junit=None):
        self.stage("brief")
        self.docker.exec_policy = lambda c, argv: (0, text, False) if "mutmut" in " ".join(argv) else None
        if junit:
            self.docker.junit_policy = junit
        code, out = self.inv(["mutants", "--language", "python"])
        self.assertEqual(code, 0, out)
        found = self.tasks()[0]["mutants"]
        if text:
            self.assertTrue(found, out)
        return found

    def merged_policy(self, outcome):
        def policy(c):
            text = c.tree_text()
            merged = "def clamp" in text
            for marker, result in outcome.items():
                if marker in text:
                    if result in ("timeout", None):
                        return result
                    return pytest_junit({k: result for k in F2P})
            return pytest_junit({k: "pass" if merged else "fail" for k in F2P})
        return policy

    def test_O30_gold_classification_covers_killed_error_survived_build_error_timeout(self):
        text = self.lines(5, "k")
        policy = self.merged_policy({"+ k0": "fail", "+ k1": "error", "+ k2": "pass", "+ k3": None, "+ k4": "timeout"})
        found = {m["diff"].split("+ k")[1][0]: m["gold"] for m in self.run_mutants(text, policy)}
        self.assertEqual(found, {"0": "killed", "1": "killed", "2": "survived", "3": "build_error", "4": "timeout"})

    def test_O30_id_formula_path_line_diff(self):
        mutants = self.run_mutants(self.lines(3), self.merged_policy({}))
        for m in mutants:
            want = hashlib.sha256(("%s\0%s\0%s" % (m["path"], m["line"], m["diff"])).encode()).hexdigest()[:16]
            self.assertEqual(m["id"], want)

    def test_O30_only_mutants_on_changed_gold_lines_are_kept(self):
        outside = ("--- src/calc/ops.py\n+++ src/calc/ops.py\n@@ -1,2 +1,2 @@\n def identity(value):\n-    return value\n"
                   "+    return value + 1\n")
        mutants = self.run_mutants(self.lines(2) + outside, self.merged_policy({}))
        self.assertEqual(len(mutants), 2)
        self.assertEqual({m["line"] for m in mutants}, {6})

    def test_O30_sample_cap_40_with_seed_1_at_41_mutants_and_exactly_40_mutants(self):
        for total, expect_all in ((40, True), (41, False)):
            self.setUp()
            mutants = self.run_mutants(self.lines(total), self.merged_policy({}))
            with self.subTest(total=total):
                self.assertEqual(len(mutants), 40)
                if not expect_all:
                    normalized = mutants_mod.normalize("mutmut", self.lines(total))
                    ordered = sorted(normalized, key=lambda m: m["id"])
                    want = random.Random(1).sample(ordered, 40)
                    self.assertEqual({m["id"] for m in mutants}, {m["id"] for m in want})

    def test_O30_d_ref_is_the_killed_mutants_and_no_mutants_leaves_an_empty_list(self):
        mutants = self.run_mutants("", self.merged_policy({}))
        self.assertEqual(mutants, [])

    def test_O30_run_uses_gold_test_files_as_selection(self):
        self.run_mutants(self.lines(2), self.merged_policy({}))
        mutant_runs = [c for c in self.docker.containers if "+ x" in c.tree_text()]
        self.assertTrue(mutant_runs)
        for cont in mutant_runs:
            pytest = [e for e in cont.execs if "pytest" in " ".join(e["argv"])]
            self.assertIn("tests/test_ops.py", pytest[0]["argv"])


class RawFormats(unittest.TestCase):
    def check(self, items, path, line):
        self.assertTrue(items)
        for m in items:
            self.assertEqual((m["path"], m["line"]), (path, line))
            want = hashlib.sha256(("%s\0%s\0%s" % (m["path"], m["line"], m["diff"])).encode()).hexdigest()[:16]
            self.assertEqual(m["id"], want)

    def test_O30_mutmut_and_go_mutesting_concatenated_unified_diffs(self):
        text = ("--- ops/ops.go\n+++ ops/ops.go\n@@ -10,3 +10,3 @@\n func Clamp(a int) int {\n-\treturn a + 1\n+\treturn a - 1\n }\n"
                "--- ops/ops.go\n+++ ops/ops.go\n@@ -20,2 +20,2 @@\n func Other() {\n-\tx := 1\n+\tx := 2\n")
        for tool in ("mutmut", "go-mutesting"):
            items = mutants_mod.normalize(tool, text)
            self.assertEqual(len(items), 2, tool)
            self.assertEqual([m["path"] for m in items], ["ops/ops.go", "ops/ops.go"])
            self.assertEqual(sorted(m["line"] for m in items), [11, 21])
            for m in items:
                want = hashlib.sha256(("%s\0%s\0%s" % (m["path"], m["line"], m["diff"])).encode()).hexdigest()[:16]
                self.assertEqual(m["id"], want)
                self.assertTrue(m["diff"].startswith("--- ops/ops.go"))

    def test_O30_cargo_mutants_json_list_with_line_or_span(self):
        diff = "--- a/src/lib.rs\n+++ b/src/lib.rs\n@@ -4,1 +4,1 @@\n-    a + b\n+    a - b\n"
        items = mutants_mod.normalize("cargo-mutants", json.dumps([
            {"file": "src/lib.rs", "line": 4, "diff": diff},
            {"file": "src/lib.rs", "span": {"start": {"line": 9, "column": 1}}, "diff": diff + " "}]))
        self.assertEqual(sorted((m["path"], m["line"]) for m in items), [("src/lib.rs", 4), ("src/lib.rs", 9)])
        self.assertEqual([m["diff"] for m in items if m["line"] == 4], [diff])
        for m in items:
            want = hashlib.sha256(("%s\0%s\0%s" % (m["path"], m["line"], m["diff"])).encode()).hexdigest()[:16]
            self.assertEqual(m["id"], want)

    def test_O30_stryker_diff_is_built_from_the_source_by_replacing_the_location_span(self):
        report = {"files": {"src/a.ts": {"source": "export function f(a) {\n  return a + 1;\n}\n", "mutants": [
            {"id": "1", "replacement": "a - 1", "location": {"start": {"line": 2, "column": 10},
                                                             "end": {"line": 2, "column": 15}}}]}}}
        (item,) = mutants_mod.normalize("stryker", json.dumps(report))
        self.check([item], "src/a.ts", 2)
        lines = item["diff"].splitlines()
        self.assertIn("-  return a + 1;", lines)
        self.assertIn("+  return a - 1;", lines)


class XWorld(TmpCase):
    def entry(self, root, task_id, key, status, src, marker):
        d = Path(root) / task_id / key
        (d / "raw").mkdir(parents=True)
        test_text = "# %s\ndef test_%s(): pass\n" % (marker, marker)
        src_diff = udiff(SRC, BASE_SRC, src)
        tests_diff = udiff(AGENT_TEST, None, test_text)
        split = {"split": {"src": src_diff, "tests": tests_diff, "harness": "", "other": ""},
                 "base": {SRC: BASE_SRC, AGENT_TEST: None}, "after": {SRC: src, AGENT_TEST: test_text}}
        (d / "split.json").write_text(json.dumps(split), encoding="utf-8")
        (d / "full.diff").write_text(src_diff + tests_diff, encoding="utf-8")
        arm = key.split("-")[0]
        (d / "manifest.json").write_text(json.dumps({"task_id": task_id, "arm": arm, "repeat": int(key[-1])}))
        (d / "state.json").write_text(json.dumps({"status": status, "reason": None, "session_id": "s", "rate_limit": None,
                                                  "results": []}))
        (d / "usersim.jsonl").write_text("")
        return d

    def policy(self, c):
        files, text = c.files(), c.tree_text()
        marker = re.search(r"# (m_\w+)", text)
        if not marker:
            return pytest_junit({})
        src = next((t for p, t in files.items() if p.endswith(SRC)), "")
        status = "fail" if "AGENTSRC_BAD" in src else ("error" if "AGENTSRC_ERR" in src else "pass")
        return pytest_junit({"%s::test_%s" % (AGENT_TEST, marker.group(1)): status})

    def test_O17_F19_matrix_cells_follow_impl_src_and_tests_entry_tests(self):
        world = World()
        task = world.task()
        root = self.tmp / "run"
        dirs = [
            self.entry(root, task["task_id"], "B0-1", "completed", "# AGENTSRC_GOOD\n", "m_b0"),
            self.entry(root, task["task_id"], "Bplus-1", "stalled", "# AGENTSRC_BAD\n", "m_bplus"),
            self.entry(root, task["task_id"], "H-1", "interrupted", "# AGENTSRC_ERR\n", "m_h"),
            self.entry(root, "other__task-9", "B0-2", "completed", "# AGENTSRC_GOOD\n", "m_other"),
        ]
        docker = FakeDocker(junit_policy=self.policy)
        matrix = crossarm.run_matrix(task, dirs, docker=docker, cfg=self.cfg(), cache_dir=self.tmp / "cache")
        keys = set(matrix)
        self.assertIn(("B0-1", "Bplus-1"), keys)
        self.assertIn(("Bplus-1", "B0-1"), keys)
        self.assertNotIn(("B0-1", "B0-1"), keys)
        self.assertFalse([k for k in keys if "H-1" == k[1]], "an interrupted entry cannot serve as impl")
        self.assertFalse([k for k in keys if "B0-2" in k], "an entry of another task is never paired")
        self.assertEqual(matrix[("B0-1", "Bplus-1")]["status"], "ok")
        self.assertEqual(matrix[("B0-1", "Bplus-1")]["results"], {"%s::test_m_b0" % AGENT_TEST: "fail"})
        self.assertEqual(matrix[("Bplus-1", "B0-1")]["results"], {"%s::test_m_bplus" % AGENT_TEST: "pass"})

    def test_O17_F19_stalled_and_capped_entries_serve_as_impls_and_error_status_is_reported(self):
        world = World()
        task = world.task()
        root = self.tmp / "run"
        dirs = [self.entry(root, task["task_id"], "B0-1", "completed", "# AGENTSRC_ERR\n", "m_b0"),
                self.entry(root, task["task_id"], "Bplus-1", "capped", "# AGENTSRC_GOOD\n", "m_bplus")]
        docker = FakeDocker(junit_policy=self.policy)
        matrix = crossarm.run_matrix(task, dirs, docker=docker, cfg=self.cfg(), cache_dir=self.tmp / "cache")
        self.assertEqual(matrix[("Bplus-1", "B0-1")]["results"], {"%s::test_m_bplus" % AGENT_TEST: "error"})
        self.assertEqual(matrix[("B0-1", "Bplus-1")]["results"], {"%s::test_m_b0" % AGENT_TEST: "pass"})

    def test_O17_F19_a_cell_that_cannot_build_is_recorded_not_dropped(self):
        world = World()
        task = world.task()
        root = self.tmp / "run"
        dirs = [self.entry(root, task["task_id"], "B0-1", "completed", "# AGENTSRC_GOOD\n", "m_b0"),
                self.entry(root, task["task_id"], "Bplus-1", "completed", "# AGENTSRC_GOOD\n", "m_bplus")]
        docker = FakeDocker(junit_policy=lambda c: None)
        matrix = crossarm.run_matrix(task, dirs, docker=docker, cfg=self.cfg(), cache_dir=self.tmp / "cache")
        self.assertEqual({v["status"] for v in matrix.values()}, {"build_error"})
        docker = FakeDocker(junit_policy=lambda c: "timeout")
        matrix = crossarm.run_matrix(task, dirs, docker=docker, cfg=self.cfg(), cache_dir=self.tmp / "cache2")
        self.assertEqual({v["status"] for v in matrix.values()}, {"timeout"})


class GcePlanV5(TmpCase):
    def setUp(self):
        super().setUp()
        self.cfg_ = self.cfg()
        self.cfg_["gce"].setdefault("region", "us-central1")
        self.cfg_["gce"].setdefault("zone", "us-central1-a")
        self.plan = gce.plan_up(self.cfg_)
        self.vm = [a for a in self.plan if kind_of(a) == "vm"][0]

    def test_O24_F17_binding_grants_secret_accessor_to_the_vm_service_account(self):
        binding = [a for a in self.plan if "add-iam-policy-binding" in a and "secrets" in a]
        self.assertEqual(len(binding), 1)
        argv = binding[0]
        email = [a.split("serviceAccount:")[1] for a in argv if a.startswith("--member=serviceAccount:")]
        self.assertEqual(len(email), 1)
        self.assertTrue(email[0].endswith("@harness-eval-d31ee3.iam.gserviceaccount.com"))
        self.assertIn("--role=roles/secretmanager.secretAccessor", argv)
        self.assertEqual(argv[argv.index("add-iam-policy-binding") + 1], self.cfg_["gce"]["secret"])
        self.assertTrue(has_flag(self.vm, "--service-account", email[0]))
        self.assertIn("--scopes=cloud-platform", self.vm)

    def test_O24_F17_binding_comes_after_service_account_and_secret_and_before_the_vm(self):
        idx = {name: i for i, a in enumerate(self.plan) for name in
               [("sa" if kind_of(a) == "service_account" and "create" in a else
                 "secret" if kind_of(a) == "secret" and "create" in a else
                 "binding" if "add-iam-policy-binding" in a else
                 "vm" if kind_of(a) == "vm" else None)] if name}
        self.assertLess(idx["sa"], idx["binding"])
        self.assertLess(idx["secret"], idx["binding"])
        self.assertLess(idx["binding"], idx["vm"])

    def startup_text(self):
        text = " ".join(self.vm)
        m = re.search(r"startup-script=(\S+)", text)
        self.assertTrue(m, "VM create has no startup-script metadata file")
        self.assertIn("--metadata-from-file", self.vm)
        path = Path(m.group(1))
        self.assertTrue(path.is_file(), path)
        self.assertEqual(path.name, "startup.sh")
        self.assertEqual(path.parent.name, "docker")
        return path.read_text(encoding="utf-8")

    def test_O24_F17_startup_script_fetches_the_secret_into_the_token_file_with_mode_600(self):
        script = self.startup_text()
        secret = self.cfg_["gce"]["secret"]
        self.assertTrue(re.search(r"gcloud secrets versions access latest[^\n]*--secret[= ]\S*", script))
        self.assertTrue("--secret=" in script or "--secret " in script)
        self.assertIn("/data/secrets/oauth_token", script)
        self.assertRegex(script, r"gcloud secrets versions access latest[^\n]*>\s*\S*oauth_token|>\s*\"?\$\{?\w*TOKEN\w*\}?\"?")
        self.assertRegex(script, r"chmod\s+(0?600|u=rw,go=)\b|install\s+[^\n]*-m\s*0?600|umask\s+0?77")

    def test_O24_F17_startup_script_never_prints_the_token(self):
        script = self.startup_text()
        self.assertNotRegex(script, r"(?m)^\s*set\s+-[a-z]*x")
        self.assertNotIn("set -o xtrace", script)
        holders = set(re.findall(r"(\w+)=\$\([^)]*secrets versions access", script))
        for line in script.splitlines():
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            if re.match(r"(echo|printf)\b", stripped) or re.search(r"[;&|]\s*(echo|printf)\b", stripped):
                self.assertNotIn("oauth_token", stripped)
                self.assertNotRegex(stripped, r"\$\{?(%s)\b" % "|".join(holders or {"TOKEN"}))
            self.assertNotRegex(stripped, r"\bcat\s+[^<>|]*oauth_token")
            self.assertNotRegex(stripped, r"\bcat\s+\"?\$\{?\w*TOKEN")

    def test_O24_F17_startup_script_installs_the_required_tooling(self):
        script = self.startup_text()
        for needle in ("docker", "python3.12", "node", "claude"):
            self.assertIn(needle, script)


if __name__ == "__main__":
    unittest.main()


class AtomicWrites(RunScoreJudgeReport):
    def test_O12_QR7_judge_json_survives_a_crash_between_write_and_rename(self):
        from evaluation.pr_test_quality.tests.fakes import failing_replace
        self.do_run()
        (rid,) = self.run_ids()
        self.inv(["score", rid])
        path = self.data() / "runs" / rid / TASK_ID / "judge.json"
        stale = json.dumps({"absolute": {}, "pairwise": [], "labels": {}})
        path.write_text(stale, encoding="utf-8")
        with failing_replace("judge.json"):
            try:
                self.inv(["judge", rid], call_fn=self.judge_call())
            except OSError:
                pass
        self.assertEqual(path.read_text(encoding="utf-8"), stale)
        self.inv(["judge", rid], call_fn=self.judge_call())
        self.assertNotEqual(path.read_text(encoding="utf-8"), stale)

    def test_O12_QR7_task_file_survives_a_crash_between_write_and_rename(self):
        from evaluation.pr_test_quality.tests.fakes import failing_replace
        path = self.data() / "tasks" / "python" / "tasks.jsonl"
        rows = [json.loads(ln) for ln in path.read_text().splitlines()]
        for row in rows:
            row.update({"valid": False, "reason": "stale"})
        path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
        before = path.read_bytes()
        with failing_replace("tasks.jsonl"):
            try:
                self.inv(["validate", "--language", "python", "--force"])
            except OSError:
                pass
        self.assertEqual(path.read_bytes(), before)
        self.inv(["validate", "--language", "python", "--force"])
        self.assertNotEqual(path.read_bytes(), before)

    def test_O12_QR7_report_files_survive_a_crash_between_write_and_rename(self):
        from evaluation.pr_test_quality.tests.fakes import failing_replace
        self.do_run()
        (rid,) = self.run_ids()
        self.inv(["score", rid])
        results = Path(self.cfg_["results_dir"])
        results.mkdir(parents=True, exist_ok=True)
        (results / (rid + ".json")).write_text("PREVIOUS", encoding="utf-8")
        with failing_replace(".json"):
            try:
                self.inv(["report", rid])
            except OSError:
                pass
        self.assertEqual((results / (rid + ".json")).read_text(encoding="utf-8"), "PREVIOUS")

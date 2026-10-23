import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "installer"))
import verification_tools  # noqa: E402

PYPROJECT = '[project]\nname = "demo"\nversion = "0"\n'
GO_CMD = ("go", "get", "-tool", "github.com/avito-tech/go-mutesting/cmd/go-mutesting@latest")
PROMPT = "[y/N/never]"
NEVER_ENTRY = {"verification_tools_prompt": "never"}


def new_report():
    return {key: [] for key in ("write", "merge", "skip", "conflict", "manual review", "info")}


def text_of(report, key):
    return "\n".join(str(item) for item in report[key])


class FakeWhich:
    def __init__(self, missing=()):
        self.missing = set(missing)
        self.calls = []

    def __call__(self, name):
        self.calls.append(name)
        return None if name in self.missing else f"/fake/bin/{name}"


class FakeInput:
    def __init__(self, *answers):
        self.answers = list(answers)
        self.prompts = []

    def __call__(self, prompt=""):
        self.prompts.append(prompt)
        if not self.answers:
            raise AssertionError(f"unexpected extra question: {prompt!r}")
        answer = self.answers.pop(0)
        if isinstance(answer, BaseException):
            raise answer
        return answer


class FakeRun:
    def __init__(self, *outcomes):
        self.outcomes = list(outcomes)
        self.calls = []

    def __call__(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        outcome = self.outcomes.pop(0) if self.outcomes else 0
        if isinstance(outcome, BaseException):
            raise outcome
        returncode, stdout, stderr = outcome if isinstance(outcome, tuple) else (outcome, "", "")
        return subprocess.CompletedProcess(args[0] if args else kwargs.get("args"), returncode, stdout, stderr)

    def commands(self):
        return [tuple((a[0] if a else k["args"])) for a, k in self.calls]


class ToolsTestCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        self.prefs = self.root / "home" / "preferences.json"
        patcher = mock.patch.dict(os.environ, {"HARNESS_PREFERENCES_FILE": str(self.prefs)})
        patcher.start()
        self.addCleanup(patcher.stop)

    def write(self, **files):
        for name, content in files.items():
            path = self.repo / name
            path.parent.mkdir(parents=True, exist_ok=True)
            if isinstance(content, bytes):
                path.write_bytes(content)
            else:
                path.write_text(content)

    def files(self, mapping):
        self.write(**mapping)

    def plans(self, mapping, missing=()):
        self.files(mapping)
        return verification_tools.detect_plans(self.repo, FakeWhich(missing))

    def single(self, mapping, missing=()):
        plans = self.plans(mapping, missing)
        self.assertEqual(len(plans), 1, plans)
        return plans[0]

    def offer(self, *answers, run=None, dry_run=False, ask_tools=False, which=None):
        fake_input = FakeInput(*answers)
        fake_run = run if run is not None else FakeRun()
        report = new_report()
        verification_tools.offer(
            self.repo, dry_run, ask_tools, report,
            input_fn=fake_input, run=fake_run, which=which or FakeWhich(),
        )
        return report, fake_input, fake_run


class TestLanguageDetection(ToolsTestCase):
    # VO1 EP-none / C9
    def test_no_manifest_gives_no_plan(self):
        self.assertEqual(verification_tools.detect_plans(self.repo, FakeWhich()), [])

    # VO1 EP-py, EP-js, EP-go, EP-rust: each manifest alone
    def test_each_manifest_alone_detects_exactly_its_language(self):
        cases = {
            "python": {"pyproject.toml": PYPROJECT, "uv.lock": ""},
            "javascript": {"package.json": "{}"},
            "go": {"go.mod": "module x\n"},
            "rust": {"Cargo.toml": "[package]\nname = \"x\"\n"},
        }
        for language, mapping in cases.items():
            with self.subTest(language=language):
                tmp = tempfile.TemporaryDirectory()
                self.addCleanup(tmp.cleanup)
                self.repo = Path(tmp.name)
                plans = self.plans(mapping)
                self.assertEqual([p.language for p in plans], [language])

    # VO1 EP-all4: order python, javascript, go, rust regardless of creation order
    def test_all_four_manifests_are_ordered_python_javascript_go_rust(self):
        plans = self.plans({
            "Cargo.toml": "[package]\nname = \"x\"\n",
            "go.mod": "module x\n",
            "package.json": "{}",
            "pyproject.toml": PYPROJECT,
            "uv.lock": "",
        })
        self.assertEqual([p.language for p in plans], ["python", "javascript", "go", "rust"])

    # VO1 FR1: only target root files are inspected
    def test_manifest_in_subdirectory_is_ignored(self):
        plans = self.plans({"sub/package.json": "{}", "sub/go.mod": "module x\n", "sub/pyproject.toml": PYPROJECT})
        self.assertEqual(plans, [])

    # VO1 FR8 / C9: every tool present -> no Plan, for each language
    def test_language_with_all_tools_present_has_no_plan(self):
        plans = self.plans({
            "pyproject.toml": '[project]\nname = "d"\ndependencies = ["hypothesis", "mutmut"]\n',
            "package.json": json.dumps({"devDependencies": {"fast-check": "1", "@stryker-mutator/core": "1"}}),
            "go.mod": "module x\nrequire github.com/avito-tech/go-mutesting v1.0.0\n",
            "Cargo.toml": "[dev-dependencies]\nproptest = \"1\"\n",
        })
        self.assertEqual(plans, [])

    # VO1 FR8: a satisfied language disappears while others remain
    def test_only_missing_languages_remain(self):
        plans = self.plans({
            "package.json": json.dumps({"devDependencies": {"fast-check": "1", "@stryker-mutator/core": "1"}}),
            "go.mod": "module x\n",
        })
        self.assertEqual([p.language for p in plans], ["go"])


class TestManagerSelection(ToolsTestCase):
    PY = ("hypothesis", "mutmut")

    def python_commands(self, lockfiles):
        mapping = {"pyproject.toml": PYPROJECT}
        mapping.update({name: "" for name in lockfiles})
        plan = self.single(mapping)
        self.assertIsNone(plan.blocker)
        return plan.commands

    # VO2 python rows / C1
    def test_python_uv(self):
        self.assertEqual(self.python_commands(["uv.lock"]), (("uv", "add", "--dev", "hypothesis", "mutmut"),))

    def test_python_poetry(self):
        self.assertEqual(
            self.python_commands(["poetry.lock"]),
            (("poetry", "add", "--group", "dev", "hypothesis", "mutmut"),),
        )

    def test_python_pdm(self):
        self.assertEqual(self.python_commands(["pdm.lock"]), (("pdm", "add", "-dG", "dev", "hypothesis", "mutmut"),))

    # VO2 C10: uv beats poetry (and pdm)
    def test_python_uv_wins_over_poetry(self):
        self.assertEqual(
            self.python_commands(["uv.lock", "poetry.lock"]),
            (("uv", "add", "--dev", "hypothesis", "mutmut"),),
        )

    def test_python_poetry_wins_over_pdm(self):
        self.assertEqual(
            self.python_commands(["pdm.lock", "poetry.lock"]),
            (("poetry", "add", "--group", "dev", "hypothesis", "mutmut"),),
        )

    # VO2 python none -> blocker
    def test_python_without_lockfile_is_blocker(self):
        plan = self.single({"pyproject.toml": PYPROJECT})
        self.assertEqual(plan.language, "python")
        self.assertIsNotNone(plan.blocker)

    def js_commands(self, lockfiles):
        mapping = {"package.json": "{}"}
        mapping.update({name: "" for name in lockfiles})
        plan = self.single(mapping)
        self.assertIsNone(plan.blocker)
        return plan.commands

    JS = ("fast-check", "@stryker-mutator/core")

    # VO2 js rows / C3, C11
    def test_js_pnpm(self):
        self.assertEqual(self.js_commands(["pnpm-lock.yaml"]), (("pnpm", "add", "-D") + self.JS,))

    def test_js_yarn(self):
        self.assertEqual(self.js_commands(["yarn.lock"]), (("yarn", "add", "-D") + self.JS,))

    def test_js_bun_lock(self):
        self.assertEqual(self.js_commands(["bun.lock"]), (("bun", "add", "-d") + self.JS,))

    def test_js_bun_lockb(self):
        self.assertEqual(self.js_commands(["bun.lockb"]), (("bun", "add", "-d") + self.JS,))

    def test_js_no_lockfile_uses_npm(self):
        self.assertEqual(self.js_commands([]), (("npm", "install", "--save-dev") + self.JS,))

    def test_js_package_lock_alone_uses_npm(self):
        self.assertEqual(self.js_commands(["package-lock.json"]), (("npm", "install", "--save-dev") + self.JS,))

    # VO2 C11: yarn beats bun
    def test_js_yarn_wins_over_bun(self):
        self.assertEqual(self.js_commands(["yarn.lock", "bun.lock"]), (("yarn", "add", "-D") + self.JS,))

    def test_js_pnpm_wins_over_yarn_and_bun(self):
        self.assertEqual(
            self.js_commands(["bun.lockb", "yarn.lock", "pnpm-lock.yaml"]),
            (("pnpm", "add", "-D") + self.JS,),
        )

    def test_js_bun_wins_over_npm_lock(self):
        self.assertEqual(self.js_commands(["package-lock.json", "bun.lock"]), (("bun", "add", "-d") + self.JS,))

    # VO2 C1: Plan content for both tools missing
    def test_c1_plan_fields(self):
        plan = self.single({"pyproject.toml": PYPROJECT, "uv.lock": ""})
        self.assertEqual(
            plan,
            verification_tools.Plan(
                "python", ("hypothesis", "mutmut"), (("uv", "add", "--dev", "hypothesis", "mutmut"),), None
            ),
        )


class TestPresence(ToolsTestCase):
    def py(self, pyproject, lock="uv.lock"):
        return self.plans({"pyproject.toml": pyproject, lock: ""})

    # VO3 py: none / partial / all
    def test_python_partial_hypothesis_present_case_insensitive_c2(self):
        plans = self.py('[dependency-groups]\ndev = ["Hypothesis>=6"]\n', "poetry.lock")
        self.assertEqual(plans[0].commands, (("poetry", "add", "--group", "dev", "mutmut"),))

    def test_python_partial_mutmut_present(self):
        plans = self.py('[project]\nname = "d"\ndependencies = ["mutmut==3.0"]\n')
        self.assertEqual(plans[0].commands, (("uv", "add", "--dev", "hypothesis"),))

    def test_python_extras_and_markers_after_name_are_ignored(self):
        plans = self.py('[project]\nname = "d"\ndependencies = ["Hypothesis[numpy]>=6; python_version > \'3\'"]\n')
        self.assertEqual(plans[0].commands, (("uv", "add", "--dev", "mutmut"),))

    def test_python_key_names_count_as_presence(self):
        plans = self.py('[tool.poetry.group.dev.dependencies]\nHypothesis = "^6"\nmutmut = "^3"\n')
        self.assertEqual(plans, [])

    def test_python_separator_normalization_of_names(self):
        plans = self.py('[project]\nname = "d"\ndependencies = ["MUTMUT>=1", "hypothesis"]\n')
        self.assertEqual(plans, [])

    def test_python_similarly_named_packages_do_not_count(self):
        plans = self.py('[project]\nname = "d"\ndependencies = ["hypothesis-jsonschema>=1", "mutmut_extra", "xmutmut"]\n')
        self.assertEqual(plans[0].commands, (("uv", "add", "--dev", "hypothesis", "mutmut"),))

    def test_python_all_present_gives_no_plan(self):
        self.assertEqual(self.py('[project]\nname = "d"\ndependencies = ["hypothesis", "mutmut"]\n'), [])

    # VO3 js: each of the four dependency tables for one tool
    def test_js_fast_check_in_each_dependency_table(self):
        for table in ("dependencies", "devDependencies", "optionalDependencies", "peerDependencies"):
            with self.subTest(table=table):
                tmp = tempfile.TemporaryDirectory()
                self.addCleanup(tmp.cleanup)
                self.repo = Path(tmp.name)
                plans = self.plans({"package.json": json.dumps({table: {"fast-check": "^3"}})})
                self.assertEqual(plans[0].commands, (("npm", "install", "--save-dev", "@stryker-mutator/core"),))

    def test_js_stryker_present_only_fast_check_missing(self):
        plans = self.plans({"package.json": json.dumps({"devDependencies": {"@stryker-mutator/core": "8"}}), "yarn.lock": ""})
        self.assertEqual(plans[0].commands, (("yarn", "add", "-D", "fast-check"),))

    def test_js_both_present_in_different_tables_gives_no_plan(self):
        pkg = {"dependencies": {"fast-check": "1"}, "peerDependencies": {"@stryker-mutator/core": "1"}}
        self.assertEqual(self.plans({"package.json": json.dumps(pkg)}), [])

    def test_js_names_outside_dependency_tables_do_not_count(self):
        pkg = {"fast-check": "1", "scripts": {"@stryker-mutator/core": "x"}, "bundledDependencies": {"fast-check": "1"}}
        plans = self.plans({"package.json": json.dumps(pkg)})
        self.assertEqual(plans[0].commands, (("npm", "install", "--save-dev", "fast-check", "@stryker-mutator/core"),))

    def test_c3_pnpm_with_fast_check(self):
        plans = self.plans({"package.json": json.dumps({"devDependencies": {"fast-check": "3"}}), "pnpm-lock.yaml": ""})
        self.assertEqual(plans[0].commands, (("pnpm", "add", "-D", "@stryker-mutator/core"),))

    # VO3 go / C4
    def test_c4_go_missing(self):
        plan = self.single({"go.mod": "module example.com/x\n\ngo 1.22\n"})
        self.assertEqual(plan.language, "go")
        self.assertEqual(plan.packages, ("go-mutesting",))
        self.assertEqual(plan.commands, (GO_CMD,))
        self.assertIsNone(plan.blocker)

    def test_go_present_in_go_mod_text(self):
        self.assertEqual(self.plans({"go.mod": "module x\n\ntool github.com/avito-tech/go-mutesting/cmd/go-mutesting\n"}), [])
        self.assertEqual(self.plans({"go.mod": "module x\n\nrequire github.com/avito-tech/go-mutesting v1.0.0\n"}), [])

    # VO3 rust: proptest {absent, present} x cargo-mutants {absent, present}
    CARGO = "[package]\nname = \"x\"\n"
    ADD = ("cargo", "add", "--dev", "proptest")
    INSTALL = ("cargo", "install", "cargo-mutants")

    def test_rust_both_missing(self):
        plans = self.plans({"Cargo.toml": self.CARGO}, missing=["cargo-mutants"])
        self.assertEqual(plans[0].commands, (self.ADD, self.INSTALL))

    def test_rust_proptest_missing_mutants_present(self):
        plans = self.plans({"Cargo.toml": self.CARGO})
        self.assertEqual(plans[0].commands, (self.ADD,))

    def test_c5_rust_proptest_in_dev_dependencies_mutants_missing(self):
        plans = self.plans({"Cargo.toml": self.CARGO + "[dev-dependencies]\nproptest = \"1\"\n"}, missing=["cargo-mutants"])
        self.assertEqual(plans[0].commands, (self.INSTALL,))

    def test_rust_proptest_in_dependencies_counts(self):
        plans = self.plans({"Cargo.toml": self.CARGO + "[dependencies]\nproptest = \"1\"\n"}, missing=["cargo-mutants"])
        self.assertEqual(plans[0].commands, (self.INSTALL,))

    def test_rust_build_dependencies_do_not_count(self):
        plans = self.plans({"Cargo.toml": self.CARGO + "[build-dependencies]\nproptest = \"1\"\n"})
        self.assertEqual(plans[0].commands, (self.ADD,))

    def test_rust_both_present_gives_no_plan(self):
        self.assertEqual(self.plans({"Cargo.toml": self.CARGO + "[dev-dependencies]\nproptest = \"1\"\n"}), [])

    def test_rust_cargo_mutants_is_looked_up_by_exact_name(self):
        which = FakeWhich()
        self.files({"Cargo.toml": self.CARGO})
        verification_tools.detect_plans(self.repo, which)
        self.assertIn("cargo-mutants", which.calls)


class TestBlockers(ToolsTestCase):
    def assert_blocker(self, mapping, language, missing=()):
        plan = self.single(mapping, missing)
        self.assertEqual(plan.language, language)
        self.assertTrue(plan.blocker)
        return plan

    # VO4 / C13 / C14
    def test_broken_toml_python(self):
        self.assert_blocker({"pyproject.toml": "[project\nname =", "uv.lock": ""}, "python")

    def test_broken_toml_rust(self):
        self.assert_blocker({"Cargo.toml": "[package\n"}, "rust")

    def test_broken_json(self):
        self.assert_blocker({"package.json": "{not json"}, "javascript")

    def test_json_top_level_not_object(self):
        self.assert_blocker({"package.json": "[1]"}, "javascript")

    def test_python_without_lockfile(self):
        self.assert_blocker({"pyproject.toml": PYPROJECT}, "python")

    def test_missing_uv_executable(self):
        self.assert_blocker({"pyproject.toml": PYPROJECT, "uv.lock": ""}, "python", missing=["uv"])

    def test_missing_npm_executable(self):
        self.assert_blocker({"package.json": "{}"}, "javascript", missing=["npm"])

    def test_missing_go_executable(self):
        self.assert_blocker({"go.mod": "module x\n"}, "go", missing=["go"])

    def test_missing_cargo_executable(self):
        self.assert_blocker({"Cargo.toml": "[package]\nname = \"x\"\n"}, "rust", missing=["cargo"])

    def test_present_executable_is_not_a_blocker(self):
        plan = self.single({"package.json": "{}"})
        self.assertIsNone(plan.blocker)

    # VO4 Errors: the failing language does not stop the others
    def test_broken_language_does_not_stop_other_languages(self):
        plans = self.plans({"pyproject.toml": "[broken", "uv.lock": "", "package.json": "{}", "go.mod": "module x\n"})
        self.assertEqual([p.language for p in plans], ["python", "javascript", "go"])
        self.assertTrue(plans[0].blocker)
        self.assertIsNone(plans[1].blocker)
        self.assertIsNone(plans[2].blocker)

    # VO4 FR9 via offer: blockers are reported, never asked
    def test_offer_reports_missing_executable_without_asking_c14_style(self):
        self.files({"pyproject.toml": PYPROJECT, "uv.lock": ""})
        report, fake_input, fake_run = self.offer(which=FakeWhich(missing=["uv"]))
        self.assertEqual(fake_input.prompts, [])
        self.assertEqual(fake_run.calls, [])
        review = text_of(report, "manual review").lower()
        self.assertIn("python", review)
        self.assertIn("uv", review)
        for token in ("add", "--dev", "hypothesis", "mutmut"):
            self.assertIn(token, review)

    def test_offer_reports_missing_lockfile_without_asking_c14(self):
        self.files({"pyproject.toml": PYPROJECT})
        report, fake_input, fake_run = self.offer()
        self.assertEqual(fake_input.prompts, [])
        self.assertEqual(fake_run.calls, [])
        self.assertIn("python", text_of(report, "manual review").lower())
        self.assertEqual(report["write"], [])

    def test_offer_reports_broken_manifest_without_exception(self):
        self.files({"package.json": "[1]"})
        report, fake_input, _ = self.offer()
        self.assertEqual(fake_input.prompts, [])
        self.assertIn("javascript", text_of(report, "manual review").lower())


class TestAnswers(ToolsTestCase):
    def setUp(self):
        super().setUp()
        self.files({"pyproject.toml": PYPROJECT, "uv.lock": ""})
        self.uv = ("uv", "add", "--dev", "hypothesis", "mutmut")

    # VO5 install answers: y, yes, "  YES ", C12
    def test_affirmative_answers_install(self):
        for answer in ("y", "yes", "  YES ", "Y", "\tyEs\n"):
            with self.subTest(answer=answer):
                report, fake_input, fake_run = self.offer(answer)
                self.assertEqual(len(fake_input.prompts), 1)
                self.assertEqual(fake_run.commands(), [self.uv])
                write = text_of(report, "write").lower()
                self.assertIn("python", write)
                self.assertFalse(verification_tools.is_never(self.repo))

    # VO5 skip answers: "", n, N, x, "yy", "ye"
    def test_other_answers_skip(self):
        for answer in ("", "n", "N", "x", "yy", "ye", "no", " "):
            with self.subTest(answer=answer):
                report, fake_input, fake_run = self.offer(answer)
                self.assertEqual(len(fake_input.prompts), 1)
                self.assertEqual(fake_run.calls, [])
                self.assertEqual(len(report["skip"]), 1, report)
                self.assertEqual(report["write"], [])
                self.assertFalse(verification_tools.is_never(self.repo))
                self.assertFalse(self.prefs.exists())

    # VO5 never answers: never, Never
    def test_never_answers_store_preference(self):
        for answer in ("never", "Never", " NEVER "):
            with self.subTest(answer=answer):
                if self.prefs.exists():
                    self.prefs.unlink()
                report, fake_input, fake_run = self.offer(answer)
                self.assertEqual(fake_run.calls, [])
                self.assertEqual(report["write"], [])
                self.assertTrue(verification_tools.is_never(self.repo))

    # VO5 EOFError / C18: two languages, both skipped, both asked
    def test_eof_skips_each_language(self):
        self.files({"package.json": "{}"})
        report, fake_input, fake_run = self.offer(EOFError(), EOFError())
        self.assertEqual(len(fake_input.prompts), 2)
        self.assertEqual(fake_run.calls, [])
        self.assertEqual(len(report["skip"]), 2, report)
        self.assertFalse(verification_tools.is_never(self.repo))

    # VO5 C19: never ends the questions
    def test_never_on_first_language_stops_further_questions(self):
        self.files({"package.json": "{}"})
        report, fake_input, fake_run = self.offer("never")
        self.assertEqual(len(fake_input.prompts), 1)
        self.assertEqual(fake_run.calls, [])
        self.assertTrue(verification_tools.is_never(self.repo))

    # VO5/FR13: one question per language, answers apply per language
    def test_yes_then_no_applies_per_language(self):
        self.files({"package.json": "{}"})
        report, fake_input, fake_run = self.offer("y", "n")
        self.assertEqual(len(fake_input.prompts), 2)
        self.assertEqual(fake_run.commands(), [self.uv])
        self.assertIn("python", text_of(report, "write").lower())
        self.assertNotIn("javascript", text_of(report, "write").lower())
        self.assertEqual(len(report["skip"]), 1)

    # VO5/C9, FR18: nothing to ask
    def test_no_plans_never_reads_input(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.repo = Path(tmp.name)
        report, fake_input, fake_run = self.offer()
        self.assertEqual(fake_input.prompts, [])
        self.assertEqual(fake_run.calls, [])
        self.assertEqual(report, new_report())

    def test_all_tools_present_never_reads_input(self):
        self.files({"pyproject.toml": '[project]\nname = "d"\ndependencies = ["hypothesis", "mutmut"]\n'})
        report, fake_input, fake_run = self.offer()
        self.assertEqual(fake_input.prompts, [])
        self.assertEqual(report, new_report())


class TestInstallExecution(ToolsTestCase):
    RUST = {"Cargo.toml": "[package]\nname = \"x\"\n"}
    ADD = ("cargo", "add", "--dev", "proptest")
    INSTALL = ("cargo", "install", "cargo-mutants")

    def rust_offer(self, *outcomes):
        self.files(self.RUST)
        return self.offer("y", run=FakeRun(*outcomes), which=FakeWhich(missing=["cargo-mutants"]))

    # VO6 all success / C6 / QR4
    def test_success_runs_in_order_with_safe_arguments(self):
        report, _, fake_run = self.rust_offer(0, 0)
        self.assertEqual(fake_run.commands(), [self.ADD, self.INSTALL])
        for args, kwargs in fake_run.calls:
            command = args[0] if args else kwargs["args"]
            self.assertIsInstance(command, (list, tuple))
            self.assertFalse(kwargs.get("shell", False))
            self.assertEqual(Path(kwargs["cwd"]).resolve(), self.repo.resolve())
            self.assertIs(kwargs["stdin"], subprocess.DEVNULL)
            self.assertIs(kwargs["capture_output"], True)
            self.assertIs(kwargs["text"], True)
            self.assertEqual(kwargs["timeout"], 600)
        write = text_of(report, "write").lower()
        self.assertIn("rust", write)
        self.assertEqual(report["manual review"], [])

    def test_success_write_lists_language_and_packages(self):
        self.files({"pyproject.toml": PYPROJECT, "uv.lock": ""})
        report, _, _ = self.offer("y")
        write = text_of(report, "write").lower()
        for token in ("python", "hypothesis", "mutmut"):
            self.assertIn(token, write)

    # VO6 / C15: first command returncode 1
    def test_first_command_failure_stops_and_reports(self):
        report, _, fake_run = self.rust_offer((1, "out-line", "boom reason\nsecond line"))
        self.assertEqual(fake_run.commands(), [self.ADD])
        review = text_of(report, "manual review")
        self.assertIn("rust", review.lower())
        self.assertIn("boom reason", review)
        self.assertNotIn("second line", review)
        self.assertIn("cargo add --dev proptest", review)
        self.assertIn("cargo install cargo-mutants", review)
        self.assertEqual(report["write"], [])
        self.assertFalse(verification_tools.is_never(self.repo))

    # VO6 FR14: reason falls back to the first stdout line when stderr is empty
    def test_failure_reason_uses_first_stdout_line_when_stderr_empty(self):
        report, _, _ = self.rust_offer((1, "boom\nmore", ""))
        review = text_of(report, "manual review")
        self.assertIn("boom", review)
        self.assertNotIn("more", review)

    def test_second_command_failure_reports_it_and_no_write(self):
        report, _, fake_run = self.rust_offer(0, (2, "", "late failure"))
        self.assertEqual(fake_run.commands(), [self.ADD, self.INSTALL])
        review = text_of(report, "manual review")
        self.assertIn("late failure", review)
        self.assertIn("cargo install cargo-mutants", review)
        self.assertEqual(report["write"], [])

    # VO6 / C16: OSError and TimeoutExpired
    def test_oserror_is_reported_without_exception(self):
        report, _, fake_run = self.rust_offer(FileNotFoundError("nope-missing-binary"))
        self.assertEqual(len(fake_run.calls), 1)
        review = text_of(report, "manual review")
        self.assertIn("rust", review.lower())
        self.assertIn("nope-missing-binary", review)
        self.assertIn("cargo install cargo-mutants", review)
        self.assertEqual(report["write"], [])

    def test_timeout_is_reported_without_exception(self):
        report, _, fake_run = self.rust_offer(subprocess.TimeoutExpired(list(self.ADD), 600))
        self.assertEqual(len(fake_run.calls), 1)
        review = text_of(report, "manual review")
        self.assertIn("rust", review.lower())
        self.assertIn("cargo install cargo-mutants", review)
        self.assertEqual(report["write"], [])

    def test_failure_in_one_language_does_not_block_next_language_question(self):
        self.files({"Cargo.toml": self.RUST["Cargo.toml"], "package.json": "{}"})
        fake_run = FakeRun(1, 0, 0)
        report, fake_input, _ = self.offer("y", "y", run=fake_run, which=FakeWhich(missing=["cargo-mutants"]))
        self.assertEqual(len(fake_input.prompts), 2)
        self.assertEqual(fake_run.commands(), [("npm", "install", "--save-dev", "fast-check", "@stryker-mutator/core"), self.ADD, self.INSTALL])
        self.assertIn("javascript", text_of(report, "manual review").lower())
        self.assertIn("rust", text_of(report, "write").lower())


class TestStateTransitions(ToolsTestCase):
    def setUp(self):
        super().setUp()
        self.files({"pyproject.toml": PYPROJECT, "uv.lock": ""})
        self.uv = ("uv", "add", "--dev", "hypothesis", "mutmut")

    # VO7 T1 -> T2 / C7
    def test_never_then_next_offer_skips_silently_with_one_line(self):
        self.offer("never")
        self.assertTrue(verification_tools.is_never(self.repo))
        report, fake_input, fake_run = self.offer()
        self.assertEqual(fake_input.prompts, [])
        self.assertEqual(fake_run.calls, [])
        self.assertEqual(len(report["skip"]), 1, report)
        self.assertIn("--ask-tools", text_of(report, "skip"))
        self.assertEqual(report["write"], [])

    # VO7 T3 / C8: never + ask_tools clears and asks; answering n keeps it cleared
    def test_ask_tools_clears_never_and_asks(self):
        self.offer("never")
        report, fake_input, fake_run = self.offer("n", ask_tools=True)
        self.assertEqual(len(fake_input.prompts), 1)
        self.assertFalse(verification_tools.is_never(self.repo))
        self.assertEqual(fake_run.calls, [])
        self.assertEqual(report["manual review"], [])

    def test_ask_tools_clears_never_then_yes_installs(self):
        self.offer("never")
        report, fake_input, fake_run = self.offer("y", ask_tools=True)
        self.assertEqual(fake_run.commands(), [self.uv])
        self.assertFalse(verification_tools.is_never(self.repo))

    def test_ask_tools_without_never_asks_normally(self):
        report, fake_input, fake_run = self.offer("y", ask_tools=True)
        self.assertEqual(len(fake_input.prompts), 1)
        self.assertEqual(fake_run.commands(), [self.uv])

    # VO7 T4 / C20 / FR12
    def test_dry_run_with_never_and_ask_tools_changes_nothing(self):
        self.offer("never")
        before = self.prefs.read_bytes()
        report, fake_input, fake_run = self.offer(dry_run=True, ask_tools=True)
        self.assertEqual(fake_input.prompts, [])
        self.assertEqual(fake_run.calls, [])
        self.assertEqual(self.prefs.read_bytes(), before)
        self.assertTrue(verification_tools.is_never(self.repo))
        info = text_of(report, "info")
        self.assertIn("python", info.lower())
        for token in self.uv:
            self.assertIn(token, info)

    def test_dry_run_plain_shows_each_plan_without_side_effects(self):
        self.files({"package.json": "{}"})
        report, fake_input, fake_run = self.offer(dry_run=True)
        self.assertEqual(fake_input.prompts, [])
        self.assertEqual(fake_run.calls, [])
        self.assertFalse(self.prefs.exists())
        info = text_of(report, "info")
        self.assertIn("python", info.lower())
        self.assertIn("javascript", info.lower())
        self.assertIn("npm install --save-dev fast-check @stryker-mutator/core", info)
        self.assertEqual(report["write"], [])

    def test_dry_run_does_not_list_blocker_plans_as_info(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.repo = Path(tmp.name)
        self.files({"pyproject.toml": PYPROJECT})
        report, _, _ = self.offer(dry_run=True)
        self.assertEqual(report["info"], [])

    # VO7 FR10: skip line only when something would have been asked
    # VO7 FR12 precedence: dry_run beats the FR10 never skip
    def test_dry_run_with_never_and_no_ask_tools_shows_info_not_skip(self):
        self.offer("never")
        before = self.prefs.read_bytes()
        report, fake_input, fake_run = self.offer(dry_run=True, ask_tools=False)
        self.assertEqual(fake_input.prompts, [])
        self.assertEqual(fake_run.calls, [])
        self.assertEqual(report["skip"], [])
        info = text_of(report, "info")
        self.assertIn("python", info.lower())
        for token in self.uv:
            self.assertIn(token, info)
        self.assertEqual(self.prefs.read_bytes(), before)

    def test_never_with_only_blocker_plans_adds_no_skip_line(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        other = Path(tmp.name)
        (other / "pyproject.toml").write_text(PYPROJECT)
        verification_tools.set_never(other)
        report = new_report()
        verification_tools.offer(other, False, False, report, input_fn=FakeInput(), run=FakeRun(), which=FakeWhich())
        self.assertEqual(report["skip"], [])

    def test_never_with_no_plans_adds_no_skip_line(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        other = Path(tmp.name)
        verification_tools.set_never(other)
        report = new_report()
        verification_tools.offer(other, False, False, report, input_fn=FakeInput(), run=FakeRun(), which=FakeWhich())
        self.assertEqual(report["skip"], [])

    def test_never_is_per_repository(self):
        self.offer("never")
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        other = Path(tmp.name)
        (other / "pyproject.toml").write_text(PYPROJECT)
        (other / "uv.lock").write_text("")
        fake_input = FakeInput("n")
        verification_tools.offer(other, False, False, new_report(), input_fn=fake_input, run=FakeRun(), which=FakeWhich())
        self.assertEqual(len(fake_input.prompts), 1)


class TestPreferences(ToolsTestCase):
    def read(self):
        return json.loads(self.prefs.read_text())

    # VO8 preferences_file: env read at call time, home default
    def test_preferences_file_reads_environment_at_call_time(self):
        self.assertEqual(Path(verification_tools.preferences_file()), self.prefs)
        other = self.root / "elsewhere.json"
        with mock.patch.dict(os.environ, {"HARNESS_PREFERENCES_FILE": str(other)}):
            self.assertEqual(Path(verification_tools.preferences_file()), other)
        self.assertEqual(Path(verification_tools.preferences_file()), self.prefs)

    def test_preferences_file_defaults_under_home(self):
        env = {k: v for k, v in os.environ.items() if k != "HARNESS_PREFERENCES_FILE"}
        env["HOME"] = str(self.root / "fakehome")
        with mock.patch.dict(os.environ, env, clear=True):
            self.assertEqual(
                Path(verification_tools.preferences_file()),
                Path(env["HOME"]) / ".harness" / "preferences.json",
            )

    # VO8 absent
    def test_absent_file_is_not_never_and_not_created_by_read(self):
        self.assertFalse(verification_tools.is_never(self.repo))
        self.assertFalse(self.prefs.exists())

    # VO8 normal: exact format, parent creation
    def test_set_never_writes_exact_format_and_creates_parents(self):
        self.assertFalse(self.prefs.parent.exists())
        self.assertTrue(verification_tools.set_never(self.repo))
        self.assertEqual(self.read(), {"repositories": {str(self.repo.resolve()): NEVER_ENTRY}})
        self.assertTrue(verification_tools.is_never(self.repo))

    def test_key_is_the_resolved_path(self):
        link = self.root / "link"
        link.symlink_to(self.repo, target_is_directory=True)
        self.assertTrue(verification_tools.set_never(link))
        self.assertEqual(list(self.read()["repositories"]), [str(self.repo.resolve())])
        self.assertTrue(verification_tools.is_never(self.repo))

    def test_clear_never_removes_only_this_repository(self):
        verification_tools.set_never(self.repo)
        self.assertTrue(verification_tools.clear_never(self.repo))
        self.assertFalse(verification_tools.is_never(self.repo))
        self.assertNotIn(str(self.repo.resolve()), self.read().get("repositories", {}))

    # VO8 FR15: clear_never without an entry succeeds and writes nothing
    def test_clear_never_without_entry_returns_true_and_writes_nothing(self):
        self.assertTrue(verification_tools.clear_never(self.repo))
        self.assertFalse(self.prefs.exists())
        self.assertFalse(self.prefs.parent.exists())
        self.prefs.parent.mkdir(parents=True)
        content = json.dumps({"theme": "x", "repositories": {"/other": NEVER_ENTRY}}, indent=4)
        self.prefs.write_text(content)
        self.assertTrue(verification_tools.clear_never(self.repo))
        self.assertEqual(self.prefs.read_text(), content)

    # VO8 FR15: valid object without "repositories"
    def test_object_without_repositories_key_is_usable(self):
        self.prefs.parent.mkdir(parents=True)
        self.prefs.write_text(json.dumps({"other": 1}))
        self.assertFalse(verification_tools.is_never(self.repo))
        self.assertTrue(verification_tools.set_never(self.repo))
        self.assertTrue(verification_tools.is_never(self.repo))
        data = self.read()
        self.assertEqual(data["other"], 1)
        self.assertEqual(data["repositories"], {str(self.repo.resolve()): NEVER_ENTRY})
        self.prefs.write_text(json.dumps({"other": 1}))
        self.assertTrue(verification_tools.clear_never(self.repo))
        self.assertEqual(self.read(), {"other": 1})

    # VO8 FR15: nested missing parent chain
    def test_set_never_creates_nested_parent_directories(self):
        nested = self.root / "a" / "b" / "prefs.json"
        with mock.patch.dict(os.environ, {"HARNESS_PREFERENCES_FILE": str(nested)}):
            self.assertTrue(verification_tools.set_never(self.repo))
            self.assertTrue(nested.is_file())
            self.assertTrue(verification_tools.is_never(self.repo))

    # VO8 C21 preservation
    def test_other_keys_and_repositories_survive_set_and_clear(self):
        other_repo = {"verification_tools_prompt": "never", "note": 1}
        self.prefs.parent.mkdir(parents=True)
        self.prefs.write_text(json.dumps({"theme": "dark", "repositories": {"/other/repo": other_repo}}))
        self.assertTrue(verification_tools.set_never(self.repo))
        data = self.read()
        self.assertEqual(data["theme"], "dark")
        self.assertEqual(data["repositories"]["/other/repo"], other_repo)
        self.assertEqual(data["repositories"][str(self.repo.resolve())], NEVER_ENTRY)
        self.assertTrue(verification_tools.clear_never(self.repo))
        data = self.read()
        self.assertEqual(data["theme"], "dark")
        self.assertEqual(data["repositories"]["/other/repo"], other_repo)
        self.assertNotIn(str(self.repo.resolve()), data["repositories"])
        self.assertFalse(verification_tools.is_never(self.repo))

    def test_entry_for_other_repository_is_not_never_for_this_one(self):
        self.prefs.parent.mkdir(parents=True)
        self.prefs.write_text(json.dumps({"repositories": {"/other/repo": NEVER_ENTRY}}))
        self.assertFalse(verification_tools.is_never(self.repo))

    def test_entry_with_other_value_is_not_never(self):
        self.prefs.parent.mkdir(parents=True)
        self.prefs.write_text(json.dumps({"repositories": {str(self.repo.resolve()): {"verification_tools_prompt": "ask"}}}))
        self.assertFalse(verification_tools.is_never(self.repo))

    # VO8 C17: malformed content is never overwritten
    def assert_untouched_malformed(self, content):
        self.prefs.parent.mkdir(parents=True, exist_ok=True)
        self.prefs.write_text(content)
        self.assertFalse(verification_tools.is_never(self.repo))
        self.assertFalse(verification_tools.set_never(self.repo))
        self.assertEqual(self.prefs.read_text(), content)
        verification_tools.clear_never(self.repo)
        self.assertEqual(self.prefs.read_text(), content)

    def test_broken_json_is_left_alone(self):
        self.assert_untouched_malformed("not json")

    def test_top_level_list_is_left_alone(self):
        self.assert_untouched_malformed("[]")

    def test_repositories_not_object_is_left_alone(self):
        self.assert_untouched_malformed('{"repositories": []}')

    def test_repository_entry_not_object_is_not_never(self):
        self.prefs.parent.mkdir(parents=True)
        self.prefs.write_text(json.dumps({"repositories": {str(self.repo.resolve()): "never"}}))
        self.assertFalse(verification_tools.is_never(self.repo))

    # VO8 write errors
    def test_parent_path_blocked_by_a_file_returns_false(self):
        blocker = self.root / "blocker"
        blocker.write_text("x")
        with mock.patch.dict(os.environ, {"HARNESS_PREFERENCES_FILE": str(blocker / "preferences.json")}):
            self.assertFalse(verification_tools.set_never(self.repo))
            self.assertTrue(verification_tools.clear_never(self.repo))
            self.assertFalse(verification_tools.is_never(self.repo))

    def test_read_only_directory_returns_false(self):
        self.prefs.parent.mkdir(parents=True)
        verification_tools.set_never(self.repo)
        original = self.prefs.read_bytes()
        os.chmod(self.prefs, 0o400)
        os.chmod(self.prefs.parent, 0o500)
        self.addCleanup(os.chmod, self.prefs.parent, 0o700)
        self.addCleanup(os.chmod, self.prefs, 0o600)
        try:
            self.prefs.write_bytes(original)
        except OSError:
            pass
        else:
            self.skipTest("filesystem permissions are not enforced (running as root)")
        self.assertFalse(verification_tools.clear_never(self.repo))
        other = self.root / "other"
        other.mkdir()
        self.assertFalse(verification_tools.set_never(other))
        self.assertEqual(self.prefs.read_bytes(), original)

    # VO8 FR16: set_never failure inside offer
    def offer_with_unwritable_preferences(self):
        blocker = self.root / "blocker"
        blocker.write_text("x")
        self.files({"pyproject.toml": PYPROJECT, "uv.lock": "", "package.json": "{}"})
        with mock.patch.dict(os.environ, {"HARNESS_PREFERENCES_FILE": str(blocker / "preferences.json")}):
            return self.offer("never")

    def test_offer_reports_manual_review_when_never_cannot_be_saved(self):
        report, fake_input, fake_run = self.offer_with_unwritable_preferences()
        self.assertEqual(len(fake_input.prompts), 1)
        self.assertEqual(fake_run.calls, [])
        self.assertTrue(report["manual review"], report)
        self.assertTrue(all(isinstance(item, str) and item.strip() for item in report["manual review"]), report)

    def test_offer_with_broken_preferences_keeps_file_and_reports(self):
        self.files({"pyproject.toml": PYPROJECT, "uv.lock": ""})
        self.prefs.parent.mkdir(parents=True)
        self.prefs.write_text("not json")
        report, fake_input, fake_run = self.offer("never")
        self.assertEqual(self.prefs.read_text(), "not json")
        self.assertEqual(fake_run.calls, [])
        self.assertTrue(report["manual review"], report)


class TestPromptText(ToolsTestCase):
    def prompts_for(self, mapping, missing=()):
        self.files(mapping)
        answers = [""] * 4
        _, fake_input, _ = self.offer(*answers, which=FakeWhich(missing=missing))
        return fake_input.prompts

    def assert_prompt_shows(self, prompt, language, commands):
        self.assertIn(language, prompt.lower())
        self.assertTrue(prompt.rstrip().endswith(PROMPT), prompt)
        self.assertIn(" && ".join(" ".join(c) for c in commands), prompt)
        for command in commands:
            for argument in command:
                self.assertIn(argument, prompt)

    # VO10 single command
    def test_single_command_prompts_for_each_language(self):
        cases = [
            ("python", {"pyproject.toml": PYPROJECT, "uv.lock": ""}, [("uv", "add", "--dev", "hypothesis", "mutmut")]),
            ("javascript", {"package.json": "{}", "pnpm-lock.yaml": ""}, [("pnpm", "add", "-D", "fast-check", "@stryker-mutator/core")]),
            ("go", {"go.mod": "module x\n"}, [GO_CMD]),
            ("rust", {"Cargo.toml": "[dev-dependencies]\nproptest = \"1\"\n"}, [("cargo", "install", "cargo-mutants")]),
        ]
        for language, mapping, commands in cases:
            with self.subTest(language=language):
                tmp = tempfile.TemporaryDirectory()
                self.addCleanup(tmp.cleanup)
                self.repo = Path(tmp.name)
                missing = ["cargo-mutants"] if language == "rust" else []
                prompts = self.prompts_for(mapping, missing)
                self.assertEqual(len(prompts), 1)
                self.assert_prompt_shows(prompts[0], language, commands)

    # VO10 two commands joined by " && "
    def test_two_commands_are_joined_with_and(self):
        prompts = self.prompts_for({"Cargo.toml": "[package]\nname = \"x\"\n"}, ["cargo-mutants"])
        self.assertEqual(len(prompts), 1)
        self.assertIn("cargo add --dev proptest && cargo install cargo-mutants", prompts[0])
        self.assert_prompt_shows(
            prompts[0], "rust", [("cargo", "add", "--dev", "proptest"), ("cargo", "install", "cargo-mutants")]
        )

    def test_one_prompt_per_askable_plan_names_its_own_language(self):
        prompts = self.prompts_for({"pyproject.toml": PYPROJECT, "uv.lock": "", "go.mod": "module x\n"})
        self.assertEqual(len(prompts), 2)
        self.assertIn("python", prompts[0].lower())
        self.assertNotIn("go get", prompts[0])
        self.assertIn("go get", prompts[1])


class TestRobustness(ToolsTestCase):
    # VO12 QR3: error guessing, no exception propagates
    def test_empty_package_json(self):
        plans = self.plans({"package.json": ""})
        self.assertEqual(len(plans), 1)
        self.assertTrue(plans[0].blocker)

    def test_binary_pyproject_is_a_blocker_not_an_exception(self):
        plans = self.plans({"pyproject.toml": b"\xff\xfe\x00\x80\xc3\x28", "uv.lock": ""})
        self.assertEqual(len(plans), 1)
        self.assertEqual(plans[0].language, "python")
        self.assertTrue(plans[0].blocker)

    def test_cargo_dependencies_as_string_does_not_raise(self):
        plans = self.plans({"Cargo.toml": 'dependencies = "oops"\n[dev-dependencies]\nserde = "1"\n'})
        self.assertEqual([p.language for p in plans], ["rust"])

    def test_offer_survives_every_error_input(self):
        self.files({
            "package.json": "",
            "pyproject.toml": b"\xff\xfe\x00\x80",
            "Cargo.toml": 'dependencies = "oops"\n',
            "go.mod": b"\xff\xfe",
            "uv.lock": "",
        })
        report, fake_input, fake_run = self.offer("", "", "", "")
        self.assertIn("javascript", text_of(report, "manual review").lower())
        self.assertIn("python", text_of(report, "manual review").lower())


if __name__ == "__main__":
    unittest.main()

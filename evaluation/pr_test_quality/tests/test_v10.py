import copy
import json
import re
import unittest

from evaluation.pr_test_quality import mutants as mutants_mod
from evaluation.pr_test_quality import recipes
from evaluation.pr_test_quality.tests.fakes import LANG_FIXTURES, spec_cfg, udiff
from evaluation.pr_test_quality.tests.test_pipeline import Pipe

PINS = {
    "python": ["pytest==8.3.5", "pytest-cov==6.1.1", "hypothesis==6.131.0", "mutmut==2.5.1"],
    "typescript": ["@stryker-mutator/core@10.0.0", "fast-check@4.10.2"],
    "go": ["github.com/avito-tech/go-mutesting/cmd/go-mutesting@v0.0.0-20261002081621-9ce5f731e321",
           "gotest.tools/gotestsum@v1.13.0"],
    "rust": ["cargo-mutants@27.1.0", "cargo-nextest@0.9.149"],
}
VITEST = json.dumps({"devDependencies": {"vitest": "1"}})
JEST = json.dumps({"devDependencies": {"jest": "1"}})
PY = {"requirements.txt": "pytest\n"}
FILES = {
    "python-pip": ("python", PY),
    "python-uv": ("python", {"uv.lock": "", "pyproject.toml": "[project]\nname='x'\n"}),
    "python-poetry": ("python", {"poetry.lock": "", "pyproject.toml": "[project]\nname='x'\n"}),
    "python-pdm": ("python", {"pdm.lock": "", "pyproject.toml": "[project]\nname='x'\n"}),
    "ts-yarn-vitest": ("typescript", {"yarn.lock": "", "package.json": VITEST}),
    "ts-pnpm-vitest": ("typescript", {"pnpm-lock.yaml": "", "package.json": VITEST}),
    "ts-npm-jest": ("typescript", {"package-lock.json": "{}", "package.json": JEST}),
    "ts-bun-vitest": ("typescript", {"bun.lock": "", "package.json": VITEST}),
    "ts-yarn-jest": ("typescript", {"yarn.lock": "", "package.json": JEST}),
    "go": ("go", {"go.mod": "module m\n\ngo 1.24\n"}),
    "rust": ("rust", {"Cargo.toml": "[package]\nname='x'\n"}),
}


def dockerfile(key, cfg=None):
    language, files = FILES[key]
    return recipes.dockerfile(recipes.detect(language, files), cfg or spec_cfg())


class PinnedTools(unittest.TestCase):
    def test_O4_F29_python_install_line_carries_the_four_exact_pins(self):
        text = dockerfile("python-pip")
        line = [ln for ln in text.splitlines() if "pip install" in ln and "mutmut" in ln]
        self.assertEqual(len(line), 1)
        for pin in PINS["python"]:
            self.assertIn(pin, line[0])
        self.assertIn("pip install " + " ".join(PINS["python"]), line[0])

    def test_O4_F29_typescript_install_line_carries_exact_pins_for_every_manager(self):
        for key in ("ts-yarn-vitest", "ts-pnpm-vitest", "ts-npm-jest", "ts-bun-vitest", "ts-yarn-jest"):
            line = [ln for ln in dockerfile(key).splitlines() if "@stryker-mutator" in ln]
            with self.subTest(case=key):
                self.assertEqual(len(line), 1)
                for pin in PINS["typescript"]:
                    self.assertIn(pin, line[0])

    def test_O4_F29_jest_adds_a_pinned_junit_reporter_and_vitest_adds_none(self):
        jest = [ln for ln in dockerfile("ts-npm-jest").splitlines() if "@stryker-mutator" in ln][0]
        self.assertRegex(jest, r"jest-junit@\d+\.\d+\.\d+")
        vitest = [ln for ln in dockerfile("ts-yarn-vitest").splitlines() if "@stryker-mutator" in ln][0]
        self.assertNotIn("jest-junit", vitest)

    def test_O4_F29_go_tools_install_with_gotoolchain_auto_at_the_exact_versions(self):
        text = dockerfile("go")
        for pin in PINS["go"]:
            line = [ln for ln in text.splitlines() if "go install" in ln and pin in ln]
            with self.subTest(pin=pin):
                self.assertEqual(len(line), 1)
                self.assertIn("GOTOOLCHAIN=auto", line[0])
                self.assertTrue(line[0].rstrip().endswith(pin))

    def test_O4_F29_gotoolchain_auto_is_set_for_the_go_tools_only(self):
        text = dockerfile("go")
        with_auto = [ln for ln in text.splitlines() if "GOTOOLCHAIN" in ln]
        self.assertEqual(len(with_auto), 2)
        self.assertTrue(all("go install" in ln for ln in with_auto))
        self.assertNotRegex(text, r"(?m)^ENV\s+GOTOOLCHAIN")
        self.assertNotIn("GOTOOLCHAIN", "\n".join(ln for ln in text.splitlines() if "go mod download" in ln))
        for key in ("python-pip", "ts-yarn-vitest", "rust"):
            self.assertNotIn("GOTOOLCHAIN", dockerfile(key))

    def test_O4_F29_rust_installs_both_tools_with_locked_and_exact_versions(self):
        text = dockerfile("rust")
        line = [ln for ln in text.splitlines() if "cargo install" in ln]
        self.assertEqual(len(line), 1)
        self.assertIn("cargo install --locked cargo-mutants@27.1.0 cargo-nextest@0.9.149", line[0])

    def test_O4_F29_rust_property_library_is_pinned_too(self):
        text = dockerfile("rust")
        add = [ln for ln in text.splitlines() if "cargo add" in ln]
        self.assertEqual(len(add), 1)
        self.assertRegex(add[0], r"cargo add --dev proptest@\d+\.\d+\.\d+")

    def test_O4_F29_pins_come_from_cfg_tools(self):
        cfg = spec_cfg()
        cfg["tools"] = copy.deepcopy(cfg["tools"])
        cfg["tools"]["python"] = ["pytest==1.1.1", "mutmut==2.2.2"]
        cfg["tools"]["rust"] = ["cargo-mutants@1.2.3", "cargo-nextest@4.5.6"]
        cfg["tools"]["go"] = ["example.com/x/y@v9.9.9", "example.com/z@v8.8.8"]
        cfg["tools"]["typescript"] = ["@stryker-mutator/core@1.0.0", "fast-check@2.0.0"]
        self.assertIn("pip install pytest==1.1.1 mutmut==2.2.2", dockerfile("python-pip", cfg))
        self.assertIn("cargo install --locked cargo-mutants@1.2.3 cargo-nextest@4.5.6", dockerfile("rust", cfg))
        go = dockerfile("go", cfg)
        self.assertIn("go install example.com/x/y@v9.9.9", go)
        self.assertIn("go install example.com/z@v8.8.8", go)
        self.assertNotIn("go-mutesting", go)
        ts = dockerfile("ts-yarn-vitest", cfg)
        self.assertIn("@stryker-mutator/core@1.0.0 fast-check@2.0.0", ts)
        self.assertNotIn("10.0.0", ts)

    def test_O4_F29_shipped_cfg_tools_hold_the_spec_pins(self):
        tools = spec_cfg()["tools"]
        for language, pins in PINS.items():
            expected = [p for p in pins]
            if language == "rust":
                expected = ["cargo-mutants@27.1.0", "cargo-nextest@0.9.149"]
            self.assertEqual(tools[language][: len(expected)], expected, language)


INSTALL = re.compile(r"(?:pip3? install|yarn add|npm (?:install|i)|pnpm (?:add|install)|bun (?:add|install)|go install|"
                     r"cargo install|cargo add|pipx install|poetry add|uv pip install|pdm add)\b(.*?)(?:&&|\|\||;|\)|$)")


def install_args(line):
    for m in INSTALL.finditer(line):
        head = line[m.start():m.start(1)]
        args = m.group(1).split()
        skip = False
        for arg in args:
            if skip:
                skip = False
                continue
            if arg in ("-r", "-e", "--requirement", "--editable", "-c", "--constraint", "-C"):
                skip = True
                continue
            if arg.startswith("-") or arg in (".", "\\", "||", "true") or "=" in arg and arg.split("=")[0].isupper():
                continue
            yield head.split()[0], arg


def is_pinned(arg):
    return bool(re.search(r"==\d|@v?\d", arg))


class NoUnpinnedInstalls(unittest.TestCase):
    def test_O4_F29_no_latest_anywhere_in_any_generated_dockerfile(self):
        for key in FILES:
            text = dockerfile(key)
            with self.subTest(case=key):
                self.assertNotIn("@latest", text)
                self.assertIsNone(re.search(r"(?<![\w-])latest(?![\w-])", text))

    def test_O4_F29_every_package_argument_of_every_install_command_is_pinned(self):
        for key in FILES:
            for line in dockerfile(key).splitlines():
                if not line.startswith("RUN "):
                    continue
                for tool, arg in install_args(line):
                    if arg.startswith("$") or arg in ("install", "frozen", "--frozen-lockfile"):
                        continue
                    with self.subTest(case=key, line=line[:70], arg=arg):
                        self.assertTrue(is_pinned(arg), "unpinned %s in %r" % (arg, line))

    def test_O4_F29_manager_bootstraps_are_pinned_from_cfg_tools(self):
        managers = spec_cfg()["tools"]["managers"]
        for key, name in (("python-poetry", "poetry"), ("python-pdm", "pdm"), ("ts-bun-vitest", "bun")):
            text = dockerfile(key)
            with self.subTest(manager=name):
                self.assertIn(managers[name], text)
                self.assertRegex(managers[name], r"==\d|@\d")

    def test_O4_F29_helper_flags_the_defects_it_guards_against(self):
        self.assertFalse(is_pinned("fast-check"))
        self.assertFalse(is_pinned("cargo-mutants@latest"))
        self.assertTrue(is_pinned("pytest==8.3.5"))
        self.assertTrue(is_pinned("gotest.tools/gotestsum@v1.13.0"))
        self.assertEqual(list(install_args("RUN pip install a==1 b && true")), [("pip", "a==1"), ("pip", "b")])


TS_SRC_A = "export const a = 1;\n"
TS_SRC_B = "export const b = 2;\n"


class StrykerListing(Pipe):
    def ts_task(self, sources):
        from evaluation.pr_test_quality import recipes as r
        base = self.tasks()[0]
        row = copy.deepcopy(base)
        fx = LANG_FIXTURES["typescript"]
        src_diff = "".join(udiff(p, None, t) for p, t in sources.items())
        row.update({
            "language": "typescript", "pilot": False,
            "recipe": r.detect("typescript", {"yarn.lock": "", "package.json": VITEST}),
            "gold_split": {"src": src_diff, "tests": udiff(fx["test_path"], None, fx["test_new"]), "harness": "", "other": ""},
            "gold_base": {**{p: None for p in sources}, fx["test_path"]: None},
            "gold_after": {**sources, fx["test_path"]: fx["test_new"]},
            "f2p": ["src/ops.test.ts::clamp::caps at upper bound zq"],
        })
        path = self.data() / "tasks" / "typescript"
        path.mkdir(parents=True, exist_ok=True)
        (path / "tasks.jsonl").write_text(json.dumps(row) + "\n", encoding="utf-8")

    def run_listing(self, sources):
        self.stage("brief")
        self.ts_task(sources)
        seen = []

        def policy(cont, argv):
            joined = " ".join(argv)
            seen.append(joined)
            if "mutation.json" in joined:
                return 0, json.dumps({"files": {}}), False
            return None
        self.docker.exec_policy = policy
        code, out = self.inv(["mutants", "--language", "typescript"])
        self.assertEqual(code, 0, out)
        listing = [s for s in seen if "stryker" in s]
        self.assertEqual(len(listing), 1, seen)
        return listing[0]

    def config_of(self, command):
        m = re.search(r"printf %s '(\{.*?\})' > /tmp/stryker\.conf\.json", command)
        self.assertTrue(m, command)
        return json.loads(m.group(1))

    def test_O30_F30_config_has_exactly_the_f30_keys_and_values(self):
        command = self.run_listing({"src/ops.ts": TS_SRC_A})
        self.assertEqual(self.config_of(command), {
            "mutate": ["src/ops.ts"], "testRunner": "command", "commandRunner": {"command": "true"},
            "reporters": ["json"], "jsonReporter": {"fileName": "/tmp/mutation.json"},
            "tempDirName": "/tmp/stryker-tmp", "cleanTempDir": True, "concurrency": 4})

    def test_O30_F30_mutate_lists_every_changed_src_path_and_no_test_path(self):
        command = self.run_listing({"src/ops.ts": TS_SRC_A, "src/more.ts": TS_SRC_B})
        mutate = self.config_of(command)["mutate"]
        self.assertEqual(sorted(mutate), ["src/more.ts", "src/ops.ts"])
        self.assertFalse([p for p in mutate if "test" in p])

    def test_O30_F30_runs_stryker_with_the_config_file_and_prints_the_report(self):
        command = self.run_listing({"src/ops.ts": TS_SRC_A})
        self.assertIn("npx stryker run /tmp/stryker.conf.json", command)
        self.assertTrue(command.rstrip().endswith("cat /tmp/mutation.json"))
        self.assertLess(command.index("/tmp/stryker.conf.json &&"), command.index("npx stryker"))

    def test_O30_F30_no_dotted_cli_options_are_used(self):
        command = self.run_listing({"src/ops.ts": TS_SRC_A})
        invocation = command[command.index("npx stryker"):]
        self.assertEqual(re.findall(r"--[\w-]+\.[\w.-]+", invocation), [])
        self.assertNotIn("--dryRunOnly", command)
        self.assertNotIn("--commandRunner", command)
        self.assertEqual(re.findall(r"\s--[\w-]+", invocation), [])


class StrykerColumns(unittest.TestCase):
    def normalize(self, source, start, end, replacement, line=1):
        report = {"files": {"src/a.ts": {"source": source, "mutants": [{
            "id": "1", "replacement": replacement,
            "location": {"start": {"line": line, "column": start}, "end": {"line": line, "column": end}}}]}}}
        (item,) = mutants_mod.normalize("stryker", json.dumps(report))
        added = [ln[1:] for ln in item["diff"].splitlines() if ln.startswith("+") and not ln.startswith("+++")]
        removed = [ln[1:] for ln in item["diff"].splitlines() if ln.startswith("-") and not ln.startswith("---")]
        return added, removed, item

    def test_O30_F30_column_21_replaces_from_the_21st_character(self):
        added, removed, item = self.normalize("0123456789ABCDEFGHIJxyztail\n", 21, 24, "###")
        self.assertEqual(removed, ["0123456789ABCDEFGHIJxyztail"])
        self.assertEqual(added, ["0123456789ABCDEFGHIJ###tail"])
        self.assertEqual(item["line"], 1)

    def test_O30_F30_column_1_replaces_from_the_first_character(self):
        added, _, _ = self.normalize("abcdef\n", 1, 4, "XY")
        self.assertEqual(added, ["XYdef"])

    def test_O30_F30_end_column_is_exclusive_so_the_last_character_survives(self):
        added, _, _ = self.normalize("abcdef\n", 2, 6, "-")
        self.assertEqual(added, ["a-f"])

    def test_O30_F30_the_replacement_on_a_later_line_leaves_other_lines_untouched(self):
        added, removed, item = self.normalize("one\nthe two\nthree\n", 5, 8, "2", line=2)
        self.assertEqual((removed, added), (["the two"], ["the 2"]))
        self.assertEqual(item["line"], 2)

    def test_O30_F30_empty_replacement_deletes_the_span(self):
        added, _, _ = self.normalize("keep drop keep\n", 6, 10, "")
        self.assertEqual(added, ["keep  keep"])

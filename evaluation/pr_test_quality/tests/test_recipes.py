import json
import re
import unittest

from evaluation.pr_test_quality import recipes
from evaluation.pr_test_quality.tests.fakes import spec_cfg

PKG_VITEST = json.dumps({"devDependencies": {"vitest": "^1.0.0"}})
PKG_JEST = json.dumps({"devDependencies": {"jest": "^29.0.0"}})


class DetectPython(unittest.TestCase):
    def test_O3_C6_uv_lock_selects_uv_and_pytest_junit(self):
        r = recipes.detect("python", {"uv.lock": "", "pyproject.toml": "[project]\nname='x'\n"})
        self.assertEqual(r["language"], "python")
        self.assertEqual(r["manager"], "uv")
        self.assertEqual(r["test"]["runner"], "pytest")
        self.assertTrue(r["base_image"])
        self.assertTrue(r["install"])

    def test_O3_python_manager_rules(self):
        cases = [
            ({"poetry.lock": "", "pyproject.toml": "x"}, "poetry"),
            ({"pdm.lock": "", "pyproject.toml": "x"}, "pdm"),
            ({"pyproject.toml": "x"}, "pip"),
            ({"requirements.txt": "pytest\n"}, "pip"),
            ({"uv.lock": "", "poetry.lock": "", "pdm.lock": "", "pyproject.toml": "x"}, "uv"),
            ({"poetry.lock": "", "pdm.lock": "", "pyproject.toml": "x"}, "poetry"),
        ]
        for files, manager in cases:
            with self.subTest(files=sorted(files)):
                self.assertEqual(recipes.detect("python", files)["manager"], manager)

    def test_O3_python_without_manifest_raises_naming_a_file(self):
        with self.assertRaises(recipes.RecipeError) as ctx:
            recipes.detect("python", {"README.md": "hi"})
        self.assertTrue(any(n in str(ctx.exception) for n in ("pyproject.toml", "requirements.txt")))


class DetectTypescript(unittest.TestCase):
    def test_O3_typescript_manager_rules(self):
        cases = [
            ({"pnpm-lock.yaml": "", "package.json": PKG_VITEST}, "pnpm"),
            ({"yarn.lock": "", "package.json": PKG_VITEST}, "yarn"),
            ({"bun.lock": "", "package.json": PKG_VITEST}, "bun"),
            ({"bun.lockb": "", "package.json": PKG_VITEST}, "bun"),
            ({"package-lock.json": "{}", "package.json": PKG_VITEST}, "npm"),
            ({"package-lock.json": "{}", "pnpm-lock.yaml": "", "package.json": PKG_VITEST}, "pnpm"),
            ({"package-lock.json": "{}", "yarn.lock": "", "package.json": PKG_VITEST}, "yarn"),
            ({"yarn.lock": "", "pnpm-lock.yaml": "", "package.json": PKG_VITEST}, "pnpm"),
        ]
        for files, manager in cases:
            with self.subTest(files=sorted(files)):
                self.assertEqual(recipes.detect("typescript", files)["manager"], manager)

    def test_O3_vitest_when_dependency_else_jest(self):
        self.assertEqual(
            recipes.detect("typescript", {"pnpm-lock.yaml": "", "package.json": PKG_VITEST})["test"]["runner"],
            "vitest")
        self.assertEqual(
            recipes.detect("typescript", {"pnpm-lock.yaml": "", "package.json": PKG_JEST})["test"]["runner"],
            "jest")
        pkg = json.dumps({"dependencies": {"vitest": "1"}})
        self.assertEqual(recipes.detect("typescript", {"yarn.lock": "", "package.json": pkg})["test"]["runner"],
                         "vitest")

    def test_O3_typescript_without_lockfile_raises(self):
        with self.assertRaises(recipes.RecipeError) as ctx:
            recipes.detect("typescript", {"package.json": PKG_VITEST})
        self.assertTrue(any(n in str(ctx.exception) for n in ("lock", "package")))


class DetectGoRust(unittest.TestCase):
    def test_O3_go_with_go_mod_uses_gotestsum(self):
        r = recipes.detect("go", {"go.mod": "module example.com/m\n\ngo 1.22\n"})
        self.assertEqual(r["language"], "go")
        self.assertEqual(r["test"]["runner"], "gotestsum")
        self.assertTrue(r["base_image"])

    def test_O3_C7_go_without_go_mod_names_go_mod(self):
        with self.assertRaises(recipes.RecipeError) as ctx:
            recipes.detect("go", {"main.go": "package main\n"})
        self.assertIn("go.mod", str(ctx.exception))

    def test_O3_rust_with_cargo_toml_uses_nextest(self):
        r = recipes.detect("rust", {"Cargo.toml": "[package]\nname='x'\n"})
        self.assertEqual(r["language"], "rust")
        self.assertIn("nextest", r["test"]["runner"])

    def test_O3_rust_without_cargo_toml_names_cargo_toml(self):
        with self.assertRaises(recipes.RecipeError) as ctx:
            recipes.detect("rust", {"src/main.rs": "fn main() {}"})
        self.assertIn("Cargo.toml", str(ctx.exception))


class TestArgv(unittest.TestCase):
    JUNIT = "/tmp/out/junit-result.xml"

    def argv(self, language, files, selection):
        recipe = recipes.detect(language, files)
        out = recipes.test_argv(recipe, selection, self.JUNIT)
        self.assertIsInstance(out, list)
        self.assertTrue(all(isinstance(a, str) for a in out))
        return out

    def test_O3_pytest_argv_has_junitxml_path_and_selection(self):
        out = self.argv("python", {"uv.lock": "", "pyproject.toml": "x"}, ["tests/test_a.py", "tests/test_b.py"])
        joined = " ".join(out)
        self.assertIn("pytest", joined)
        self.assertIn("--junitxml", joined)
        self.assertIn(self.JUNIT, joined)
        self.assertIn("tests/test_a.py", out)
        self.assertIn("tests/test_b.py", out)

    def test_O3_vitest_argv_has_junit_reporter_and_selection(self):
        out = self.argv("typescript", {"pnpm-lock.yaml": "", "package.json": PKG_VITEST}, ["src/a.test.ts"])
        joined = " ".join(out)
        self.assertIn("vitest", joined)
        self.assertIn("--reporter=junit", joined)
        self.assertIn(self.JUNIT, joined)
        self.assertIn("src/a.test.ts", out)

    def test_O3_jest_argv_uses_jest_junit_and_selection(self):
        out = self.argv("typescript", {"package-lock.json": "{}", "package.json": PKG_JEST}, ["src/a.test.ts"])
        joined = " ".join(out)
        self.assertIn("jest", joined)
        self.assertIn("jest-junit", joined)
        self.assertIn("src/a.test.ts", out)

    def test_O3_gotestsum_argv_has_junitfile_path(self):
        out = self.argv("go", {"go.mod": "module m\n"}, ["pkg/a_test.go"])
        joined = " ".join(out)
        self.assertIn("gotestsum", joined)
        self.assertIn("--junitfile", joined)
        self.assertIn(self.JUNIT, joined)

    def test_O3_nextest_argv_mentions_nextest(self):
        out = self.argv("rust", {"Cargo.toml": "[package]\nname='x'\n"}, ["tests/it.rs"])
        self.assertIn("nextest", " ".join(out))

    def test_O3_different_selection_gives_different_argv(self):
        a = self.argv("python", {"requirements.txt": "x"}, ["tests/test_a.py"])
        b = self.argv("python", {"requirements.txt": "x"}, ["tests/test_b.py"])
        self.assertNotEqual(a, b)


class Dockerfile(unittest.TestCase):
    TOOLS = {
        "python": (("mutmut", "hypothesis"), {"requirements.txt": "pytest\n"}),
        "typescript": (("@stryker-mutator/core", "fast-check"), {"pnpm-lock.yaml": "", "package.json": PKG_VITEST}),
        "go": (("go-mutesting",), {"go.mod": "module m\n"}),
        "rust": (("cargo-mutants", "proptest"), {"Cargo.toml": "[package]\nname='x'\n"}),
    }

    def build(self, language):
        recipe = recipes.detect(language, self.TOOLS[language][1])
        return recipes.dockerfile(recipe, spec_cfg()), recipe

    def test_O4_each_language_installs_its_mutation_and_property_tools(self):
        for language, (tools, _) in self.TOOLS.items():
            text, _ = self.build(language)
            for tool in tools:
                with self.subTest(language=language, tool=tool):
                    self.assertIn(tool, text)

    def test_O4_other_languages_tools_are_not_installed(self):
        text, _ = self.build("python")
        for foreign in ("stryker", "go-mutesting", "cargo-mutants"):
            self.assertNotIn(foreign, text)

    def test_O4_starts_from_recipe_base_image(self):
        for language in self.TOOLS:
            text, recipe = self.build(language)
            with self.subTest(language=language):
                self.assertRegex(text, r"(?m)^FROM\s+" + re.escape(recipe["base_image"]))

    def test_O4_testbed_is_single_commit_without_remote_tags_or_history(self):
        for language in self.TOOLS:
            text, _ = self.build(language)
            with self.subTest(language=language):
                self.assertIn("git init", text)
                self.assertEqual(len(re.findall(r"git\b[^\n]*\bcommit\b", text)), 1)
                for banned in ("git remote add", "git tag", "git clone", "git fetch", "git pull"):
                    self.assertNotIn(banned, text)

    def test_O4_agent_tool_layer_is_not_part_of_the_evaluation_image(self):
        for language in self.TOOLS:
            text, _ = self.build(language)
            with self.subTest(language=language):
                self.assertNotIn("claude-code", text.lower())
                self.assertNotIn("@anthropic-ai", text)

    def test_O4_testbed_directory_is_used(self):
        text, _ = self.build("python")
        self.assertIn("/testbed", text)


if __name__ == "__main__":
    unittest.main()

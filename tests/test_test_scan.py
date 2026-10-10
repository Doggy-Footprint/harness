"""Independent oracle for spec 5aee51c6eb1cf672 v1 (VO1-VO8).

Expected values are hand-written from the spec's FR/Cases; the scanner is
only driven through its CLI (python3 harness/bin/test_scan.py PATH).
"""
import ast
import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCANNER = REPO_ROOT / "harness" / "bin" / "test_scan.py"

EXCLUDED_DIRS = [
    ".git", "node_modules", ".venv", "venv", "__pycache__", "dist",
    "build", "target", ".harness", ".agents", ".claude", ".codex",
]


def run_scan(root, env=None):
    return subprocess.run(
        [sys.executable, str(SCANNER), str(root)],
        capture_output=True,
        text=True,
        env=env,
    )


def run_git(cwd, *args, when=None):
    env = dict(os.environ, GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_SYSTEM=os.devnull)
    if when is not None:
        env["GIT_AUTHOR_DATE"] = f"{when} +0000"
        env["GIT_COMMITTER_DATE"] = f"{when} +0000"
    return subprocess.run(
        ["git", "-C", str(cwd), "-c", "user.email=t@t.com", "-c", "user.name=t",
         "-c", "commit.gpgsign=false"] + list(args),
        capture_output=True, text=True, check=True, env=env,
    )


class ScanTestCase(unittest.TestCase):
    def tmp(self):
        handle = tempfile.TemporaryDirectory()
        self.addCleanup(handle.cleanup)
        return Path(handle.name).resolve()

    def write(self, root, rel, content="", binary=False):
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        if binary:
            path.write_bytes(content)
        else:
            path.write_text(content)
        return path

    def scan(self, root, env=None):
        result = run_scan(root, env=env)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn("Traceback", result.stderr)
        return json.loads(result.stdout)

    def file_entry(self, data, path):
        matches = [f for f in data["files"] if f["path"] == path]
        self.assertEqual(len(matches), 1, f"{path} in {[f['path'] for f in data['files']]}")
        return matches[0]

    def entry_tests(self, data, path):
        return self.file_entry(data, path)["tests"]

    def name_lines(self, data, path):
        return sorted((t["name"], t["line"]) for t in self.entry_tests(data, path))

    def flags_by_name(self, data, path):
        return {t["name"]: t["flags"] for t in self.entry_tests(data, path)}


def line_of(lines, needle):
    """1-based line of the single fixture line equal to needle."""
    assert lines.count(needle) == 1, needle
    return lines.index(needle) + 1


class TestVO1FileDetection(ScanTestCase):
    # VO1 (FR1, N2, G1): equivalence partitioning, 10 pattern classes + 1 non-target
    def build(self):
        root = self.tmp()
        py_test = "def test_a():\n    assert 1\n"
        self.write(root, "pkg/test_alpha.py", py_test)                       # py test_
        self.write(root, "pkg/beta_test.py", py_test)                        # py _test
        self.write(root, "web/gamma.test.js", "it('g', () => {});\n")        # js .test
        self.write(root, "web/delta.spec.ts", "it('d', () => {});\n")        # ts .spec
        self.write(root, "web/__tests__/epsilon.jsx", "it('e', () => {});\n")  # __tests__
        self.write(root, "go/zeta_test.go", "func TestZ(t *testing.T) {\n}\n")  # go
        self.write(root, "rs/theta.rs", "#[test] fn t() {}\n")               # rust with #[test]
        self.write(root, "java/IotaTest.java", "class IotaTest {\n@Test void i() {}\n}\n")   # java Test
        self.write(root, "java/KappaTests.java", "class KappaTests {\n@Test void k() {}\n}\n")  # java Tests
        for d in EXCLUDED_DIRS:                                             # excluded dirs
            self.write(root, f"{d}/test_hidden.py", py_test)
            self.write(root, f"{d}/hidden.test.js", "it('h', () => {});\n")
        self.write(root, "src/util.py", "def helper():\n    return 1\n")     # non-target
        self.write(root, "src/Plain.java", "class Plain {}\n")               # non-target
        self.write(root, "rs/plain.rs", "fn main() {}\n")                    # rust w/o #[test]
        self.write(root, "notes.txt", "x\n")
        return root

    def test_vo1_detected_files_exactly_match_patterns(self):
        data = self.scan(self.build())
        self.assertEqual(
            [f["path"] for f in data["files"]],
            sorted([
                "go/zeta_test.go",
                "java/IotaTest.java",
                "java/KappaTests.java",
                "pkg/beta_test.py",
                "pkg/test_alpha.py",
                "rs/theta.rs",
                "web/__tests__/epsilon.jsx",
                "web/delta.spec.ts",
                "web/gamma.test.js",
            ]),
        )

    def test_vo1_each_excluded_directory_is_skipped(self):
        data = self.scan(self.build())
        paths = {f["path"] for f in data["files"]}
        for d in EXCLUDED_DIRS:
            with self.subTest(excluded=d):
                self.assertFalse([p for p in paths if p.startswith(d + "/")])

    def test_vo1_g1_node_modules_test_file_alone_yields_no_files(self):
        root = self.tmp()
        self.write(root, "node_modules/pkg/x.test.js", "it('x', () => {});\n")
        data = self.scan(root)
        self.assertEqual(data["files"], [])
        self.assertEqual(data["summary"]["files"], 0)

    def test_vo1_result_is_deterministic_and_path_sorted(self):
        root = self.build()
        first = run_scan(root).stdout
        second = run_scan(root).stdout
        self.assertEqual(first, second)
        paths = [f["path"] for f in json.loads(first)["files"]]
        self.assertEqual(paths, sorted(paths))


class TestVO2TestExtraction(ScanTestCase):
    # VO2 (FR2, N1, N2): equivalence partitioning over 5 languages x extraction forms
    def test_python_functions_and_methods_with_lines(self):
        root = self.tmp()
        lines = [
            "import unittest",
            "",
            "def test_top():",
            "    assert 1",
            "",
            "def helper():",
            "    return 1",
            "",
            "def testcompact():",
            "    assert 1",
            "",
            "class TestK(unittest.TestCase):",
            "    def test_method(self):",
            "        assert 1",
            "",
            "    def setUp(self):",
            "        pass",
        ]
        self.write(root, "test_py.py", "\n".join(lines) + "\n")
        data = self.scan(root)
        self.assertEqual(
            self.name_lines(data, "test_py.py"),
            sorted([
                ("test_top", line_of(lines, "def test_top():")),
                ("testcompact", line_of(lines, "def testcompact():")),
                ("test_method", line_of(lines, "    def test_method(self):")),
            ]),
        )

    def test_n1_python_test_with_assert_has_no_flags(self):
        root = self.tmp()
        self.write(root, "test_one.py", "def test_one():\n    assert 1 + 1 == 2\n")
        data = self.scan(root)
        self.assertEqual(
            self.entry_tests(data, "test_one.py"),
            [{"name": "test_one", "line": 1, "flags": []}],
        )

    def test_js_it_test_xit_and_modifiers_with_lines(self):
        root = self.tmp()
        lines = [
            "describe('suite', () => {",
            "  it('alpha works', () => {",
            "    expect(1).toBe(1);",
            "  });",
            "  test('beta works', () => {",
            "    expect(1).toBe(1);",
            "  });",
            "  xit('gamma works', () => {",
            "    expect(1).toBe(1);",
            "  });",
            "  it.skip('delta works', () => {",
            "    expect(1).toBe(1);",
            "  });",
            "  test.only('epsilon works', () => {",
            "    expect(1).toBe(1);",
            "  });",
            "});",
        ]
        self.write(root, "web/a.test.js", "\n".join(lines) + "\n")
        tests = sorted(self.entry_tests(self.scan(root), "web/a.test.js"), key=lambda t: t["line"])
        expected = [
            ("alpha works", 2), ("beta works", 5), ("gamma works", 8),
            ("delta works", 11), ("epsilon works", 14),
        ]
        self.assertEqual([t["line"] for t in tests], [line for _, line in expected])
        self.assertEqual([t["name"] for t in tests], [title for title, _ in expected])

    def test_go_test_functions_with_lines(self):
        root = self.tmp()
        lines = [
            "package x",
            "",
            "func TestAlpha(t *testing.T) {",
            "\tt.Log(1)",
            "}",
            "",
            "func helper() {}",
            "",
            "func TestBeta(t *testing.T) {",
            "}",
        ]
        self.write(root, "x_test.go", "\n".join(lines) + "\n")
        self.assertEqual(
            self.name_lines(self.scan(root), "x_test.go"),
            [("TestAlpha", 3), ("TestBeta", 9)],
        )

    def test_rust_test_attribute_then_fn_with_lines(self):
        root = self.tmp()
        # attribute on the same line as fn
        lines = [
            "fn helper() {}",
            "#[test] fn first_case() { assert!(true); }",
            "#[test] fn second_case() { assert!(true); }",
        ]
        self.write(root, "lib.rs", "\n".join(lines) + "\n")
        self.assertEqual(
            self.name_lines(self.scan(root), "lib.rs"),
            [("first_case", 2), ("second_case", 3)],
        )

    def test_rust_attribute_on_preceding_line_reports_fn_line(self):
        root = self.tmp()
        lines = [
            "#[test]",
            "fn first_case() { assert!(true); }",
            "",
            "#[test]",
            "fn second_case() {",
            "    assert!(true);",
            "}",
        ]
        self.write(root, "lib.rs", "\n".join(lines) + "\n")
        self.assertEqual(
            self.name_lines(self.scan(root), "lib.rs"),
            [("first_case", 2), ("second_case", 5)],
        )

    def test_java_annotation_on_preceding_line_reports_method_line(self):
        root = self.tmp()
        lines = [
            "class FooTest {",
            "  @Test",
            "  void firstCase() { assertTrue(true); }",
            "",
            "  @Test",
            "  public void secondCase() {",
            "    assertTrue(true);",
            "  }",
            "}",
        ]
        self.write(root, "FooTest.java", "\n".join(lines) + "\n")
        self.assertEqual(
            self.name_lines(self.scan(root), "FooTest.java"),
            [("firstCase", 3), ("secondCase", 6)],
        )

    def test_java_test_annotation_then_method_with_lines(self):
        root = self.tmp()
        lines = [
            "class FooTest {",
            "  @Test void firstCase() { assertTrue(true); }",
            "  void helper() {}",
            "  @Test void secondCase() { assertTrue(true); }",
            "}",
        ]
        self.write(root, "FooTest.java", "\n".join(lines) + "\n")
        self.assertEqual(
            self.name_lines(self.scan(root), "FooTest.java"),
            [("firstCase", 2), ("secondCase", 4)],
        )


class TestVO3Flags(ScanTestCase):
    # VO3 (FR3, B1, G2): decision table, 8 flags true/false + heavy_mock 4/5 boundary
    PY = "\n".join([
        "import time",
        "import unittest",
        "import pytest",
        "from unittest.mock import MagicMock",
        "",
        "def test_plain():",
        "    assert 1",
        "",
        "@unittest.skip('later')",
        "def test_skipped():",
        "    assert 1",
        "",
        "@pytest.mark.xfail",
        "def test_xfailed():",
        "    assert 1",
        "",
        "def test_without_assert():",
        "    x = 1",
        "    print(x)",
        "",
        "def test_empty_body():",
        "    pass",
        "",
        "def test_sleeping():",
        "    time.sleep(1)",
        "    assert 1",
        "",
        "def test_mock_four():",
        "    a = MagicMock()",
        "    b = MagicMock()",
        "    c = MagicMock()",
        "    d = MagicMock()",
        "    assert a and b and c and d",
        "",
        "def test_mock_five():",
        "    a = MagicMock()",
        "    b = MagicMock()",
        "    c = MagicMock()",
        "    d = MagicMock()",
        "    e = MagicMock()",
        "    assert a and b and c and d and e",
        "",
        "class TestDup(unittest.TestCase):",
        "    def test_twice(self):",
        "        assert 1",
        "",
        "    def test_twice(self):",
        "        assert 2",
        "",
        "    def test_once(self):",
        "        assert 3",
    ]) + "\n"

    def py_flags(self):
        root = self.tmp()
        self.write(root, "test_flags.py", self.PY)
        self.write(root, "test_other.py", "def test_twice():\n    assert 1\n")
        data = self.scan(root)
        return data, self.flags_by_name(data, "test_flags.py"), self.entry_tests(data, "test_flags.py")

    def test_plain_python_test_has_no_flags(self):
        _, flags, _ = self.py_flags()
        self.assertEqual(flags["test_plain"], [])
        self.assertEqual(flags["test_mock_four"], [])  # B1: 4 mocks -> no heavy_mock

    def test_flag_lists_are_sorted_and_unique(self):
        _, _, tests = self.py_flags()
        for test in tests:
            self.assertEqual(test["flags"], sorted(set(test["flags"])), test["name"])

    def test_skip_xfail_no_assert_empty_sleep_true_only_where_expected(self):
        _, flags, _ = self.py_flags()
        expectations = {
            "skip": "test_skipped",
            "xfail": "test_xfailed",
            "no_assert": "test_without_assert",
            "empty": "test_empty_body",
            "sleep": "test_sleeping",
        }
        for flag, owner in expectations.items():
            for name in ("test_plain", "test_skipped", "test_xfailed", "test_without_assert",
                         "test_empty_body", "test_sleeping", "test_once"):
                with self.subTest(flag=flag, test=name):
                    if name == owner:
                        self.assertIn(flag, flags[name])
                    elif not (flag == "no_assert" and name == "test_empty_body"):
                        # empty body may also count as no_assert; spec silent
                        self.assertNotIn(flag, flags[name])

    def test_b1_heavy_mock_threshold_is_five(self):
        _, flags, _ = self.py_flags()
        self.assertNotIn("heavy_mock", flags["test_mock_four"])
        self.assertIn("heavy_mock", flags["test_mock_five"])
        self.assertNotIn("heavy_mock", flags["test_plain"])

    def test_g2_duplicate_name_marks_every_same_file_occurrence_only(self):
        data, _, tests = self.py_flags()
        twice = [t for t in tests if t["name"] == "test_twice"]
        self.assertEqual(len(twice), 2)
        for test in twice:
            self.assertIn("duplicate_name", test["flags"])
        once = [t for t in tests if t["name"] == "test_once"]
        self.assertNotIn("duplicate_name", once[0]["flags"])
        # same name in a different file is not a duplicate
        other = self.entry_tests(data, "test_other.py")
        self.assertEqual(len(other), 1)
        self.assertNotIn("duplicate_name", other[0]["flags"])

    def test_focused_true_for_only_and_fit_false_otherwise(self):
        root = self.tmp()
        self.write(root, "a.test.js", "\n".join([
            "it.only('only one', () => { expect(1).toBe(1); });",
            "fit('fit one', () => { expect(1).toBe(1); });",
            "it('normal one', () => { expect(1).toBe(1); });",
        ]) + "\n")
        tests = {t["line"]: t["flags"] for t in self.entry_tests(self.scan(root), "a.test.js")}
        self.assertIn("focused", tests[1])
        self.assertIn("focused", tests[2])
        self.assertNotIn("focused", tests[3])

    def test_js_skip_modifiers_flag_skip(self):
        root = self.tmp()
        self.write(root, "a.test.js", "\n".join([
            "it.skip('skipped one', () => { expect(1).toBe(1); });",
            "xit('x one', () => { expect(1).toBe(1); });",
            "it('normal one', () => { expect(1).toBe(1); });",
        ]) + "\n")
        tests = {t["line"]: t["flags"] for t in self.entry_tests(self.scan(root), "a.test.js")}
        self.assertIn("skip", tests[1])
        self.assertIn("skip", tests[2])
        self.assertNotIn("skip", tests[3])


class TestVO4Git(ScanTestCase):
    # VO4 (FR4, B2, E3): 3-value boundary on harness first-commit time T, plus non-git
    T = 1_700_000_000

    def make_git_scenario(self):
        root = self.tmp()
        run_git(root, "init", "-q")
        self.write(root, ".harness/VERSION", "0.18.0\n")
        run_git(root, "add", "-A")
        run_git(root, "commit", "-q", "-m", "harness", when=self.T)
        for name, when in (("before", self.T - 1), ("equal", self.T), ("after", self.T + 1)):
            self.write(root, f"test_{name}.py", f"def test_{name}():\n    assert 1\n")
            run_git(root, "add", f"test_{name}.py")
            run_git(root, "commit", "-q", "-m", name, when=when)
        return root

    def epoch(self, iso):
        parsed = datetime.fromisoformat(iso)
        self.assertIsNotNone(parsed.tzinfo, iso)
        return int(parsed.timestamp())

    def test_b2_predates_harness_is_strictly_less_than(self):
        data = self.scan(self.make_git_scenario())
        expected = {
            "test_before.py": (self.T - 1, True),
            "test_equal.py": (self.T, False),
            "test_after.py": (self.T + 1, False),
        }
        for path, (when, predates) in expected.items():
            with self.subTest(path=path):
                entry = self.file_entry(data, path)
                self.assertEqual(self.epoch(entry["last_commit"]), when)
                self.assertIs(entry["predates_harness"], predates)

    def test_f5_untracked_file_in_git_repo_has_null_fields(self):
        root = self.tmp()
        run_git(root, "init", "-q")
        self.write(root, ".harness/VERSION", "0.18.0\n")
        run_git(root, "add", "-A")
        run_git(root, "commit", "-q", "-m", "harness", when=self.T)
        self.write(root, "test_untracked.py", "def test_u():\n    assert 1\n")
        entry = self.file_entry(self.scan(root), "test_untracked.py")
        self.assertIsNone(entry["last_commit"])
        self.assertIsNone(entry["predates_harness"])

    def test_f5_uncommitted_harness_gives_null_predates_but_commit_time(self):
        root = self.tmp()
        run_git(root, "init", "-q")
        self.write(root, "test_c.py", "def test_c():\n    assert 1\n")
        run_git(root, "add", "test_c.py")
        run_git(root, "commit", "-q", "-m", "t", when=self.T)
        self.write(root, ".harness/VERSION", "0.18.0\n")
        entry = self.file_entry(self.scan(root), "test_c.py")
        self.assertEqual(self.epoch(entry["last_commit"]), self.T)
        self.assertIsNone(entry["predates_harness"])

    def test_f5_harness_first_commit_is_used_when_version_committed_twice(self):
        root = self.tmp()
        run_git(root, "init", "-q")
        self.write(root, ".harness/VERSION", "0.17.0\n")
        run_git(root, "add", "-A")
        run_git(root, "commit", "-q", "-m", "h1", when=self.T)
        self.write(root, "test_mid.py", "def test_m():\n    assert 1\n")
        run_git(root, "add", "test_mid.py")
        run_git(root, "commit", "-q", "-m", "mid", when=self.T + 100)
        self.write(root, ".harness/VERSION", "0.18.0\n")
        run_git(root, "add", "-A")
        run_git(root, "commit", "-q", "-m", "h2", when=self.T + 200)
        entry = self.file_entry(self.scan(root), "test_mid.py")
        self.assertEqual(self.epoch(entry["last_commit"]), self.T + 100)
        self.assertIs(entry["predates_harness"], False)

    def test_e3_non_git_directory_gives_null_commit_and_predates(self):
        root = self.tmp()
        self.write(root, "test_x.py", "def test_x():\n    assert 1\n")
        entry = self.file_entry(self.scan(root), "test_x.py")
        self.assertIsNone(entry["last_commit"])
        self.assertIsNone(entry["predates_harness"])


class TestVO5Runners(ScanTestCase):
    # VO5 (FR5, N3): equivalence partitioning, 7 runners + gradlew presence
    def candidates(self, root):
        return {(c["runner"], c["command"]) for c in self.scan(root)["runner_candidates"]}

    def runners(self, root):
        return {c["runner"] for c in self.scan(root)["runner_candidates"]}

    PY_TEST = "def test_a():\n    assert 1\n"

    def test_pytest_evidence_variants(self):
        variants = {
            "pytest.ini": ("pytest.ini", "[pytest]\n"),
            "conftest.py": ("conftest.py", ""),
            "pyproject": ("pyproject.toml", "[tool.pytest.ini_options]\naddopts = ''\n"),
        }
        for label, (rel, content) in variants.items():
            with self.subTest(evidence=label):
                root = self.tmp()
                self.write(root, rel, content)
                self.write(root, "test_a.py", self.PY_TEST)
                candidates = self.candidates(root)
                self.assertIn(("pytest", "pytest"), candidates)
                self.assertNotIn("unittest", {runner for runner, _ in candidates})

    def test_unittest_when_python_tests_without_pytest_evidence(self):
        root = self.tmp()
        self.write(root, "test_a.py", self.PY_TEST)
        self.assertEqual(self.candidates(root), {("unittest", "python3 -m unittest discover")})

    def test_no_python_tests_and_no_evidence_yields_no_candidates(self):
        root = self.tmp()
        self.write(root, "notes.txt", "x")
        self.assertEqual(self.scan(root)["runner_candidates"], [])

    def test_npm_requires_scripts_test(self):
        root = self.tmp()
        self.write(root, "package.json", json.dumps({"scripts": {"test": "jest"}}))
        self.assertEqual(self.candidates(root), {("npm", "npm test")})
        other = self.tmp()
        self.write(other, "package.json", json.dumps({"scripts": {"build": "tsc"}}))
        self.assertNotIn("npm", self.runners(other))

    def test_n3_pyproject_pytest_and_package_json_test_script(self):
        root = self.tmp()
        self.write(root, "pyproject.toml", "[tool.pytest.ini_options]\n")
        self.write(root, "package.json", json.dumps({"scripts": {"test": "jest"}}))
        self.write(root, "test_a.py", self.PY_TEST)
        runners = self.runners(root)
        self.assertLessEqual({"pytest", "npm"}, runners)
        self.assertIn(("pytest", "pytest"), self.candidates(root))
        self.assertNotIn("unittest", runners)

    def test_go_cargo_maven(self):
        cases = {
            "go.mod": ("go", "go test ./..."),
            "Cargo.toml": ("cargo", "cargo test"),
            "pom.xml": ("maven", "mvn test"),
        }
        for rel, expected in cases.items():
            with self.subTest(marker=rel):
                root = self.tmp()
                self.write(root, rel, "x\n")
                self.assertEqual(self.candidates(root), {expected})

    def test_gradle_without_and_with_wrapper(self):
        for build_file in ("build.gradle", "build.gradle.kts"):
            with self.subTest(build_file=build_file, wrapper=False):
                root = self.tmp()
                self.write(root, build_file, "x\n")
                self.assertEqual(self.candidates(root), {("gradle", "gradle test")})
            with self.subTest(build_file=build_file, wrapper=True):
                root = self.tmp()
                self.write(root, build_file, "x\n")
                self.write(root, "gradlew", "#!/bin/sh\n")
                self.assertEqual(self.candidates(root), {("gradle", "./gradlew test")})

    def test_detection_is_limited_to_scan_root(self):
        root = self.tmp()
        for rel in ("sub/go.mod", "sub/Cargo.toml", "sub/pom.xml", "sub/build.gradle",
                    "sub/pytest.ini", "sub/package.json"):
            self.write(root, rel, json.dumps({"scripts": {"test": "x"}}))
        self.assertEqual(self.scan(root)["runner_candidates"], [])


class TestVO6Inventory(ScanTestCase):
    # VO6 (FR6): 4 directory names, non-FR1 files only, sorted
    def test_inventory_lists_non_test_files_under_test_dirs_sorted(self):
        root = self.tmp()
        for rel in (
            "tests/zeta.json", "test/data.txt", "spec/c.rb", "__tests__/notes.md",
            "tests/fixtures/b.json", "spec/a.rb",
        ):
            self.write(root, rel, "x\n")
        self.write(root, "tests/test_ok.py", "def test_ok():\n    assert 1\n")
        self.write(root, "__tests__/real.test.js", "it('r', () => {});\n")
        self.write(root, "src/other.txt", "x\n")
        self.write(root, "top.txt", "x\n")
        data = self.scan(root)
        self.assertEqual(
            data["inventory"],
            [
                "__tests__/notes.md",
                "spec/a.rb",
                "spec/c.rb",
                "test/data.txt",
                "tests/fixtures/b.json",
                "tests/zeta.json",
            ],
        )
        self.assertEqual(
            sorted(f["path"] for f in data["files"]),
            ["__tests__/real.test.js", "tests/test_ok.py"],
        )


class TestVO7Errors(ScanTestCase):
    # VO7 (Errors, E1, E2, QR2): equivalence partitioning over the 4 error classes
    def test_e1_missing_path_exits_2_with_empty_stdout_and_stderr_message(self):
        root = self.tmp()
        result = run_scan(root / "does-not-exist")
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, "")
        self.assertTrue(result.stderr.strip())
        self.assertNotIn("Traceback", result.stderr)
        self.assertEqual(list(root.iterdir()), [])

    def test_e2_syntax_error_python_file_is_parse_error_and_scan_continues(self):
        root = self.tmp()
        self.write(root, "test_broken.py", "def test_x(:\n    assert 1\n")
        self.write(root, "test_fine.py", "def test_y():\n    assert 1\n")
        data = self.scan(root)
        broken = self.file_entry(data, "test_broken.py")
        self.assertIs(broken["parse_error"], True)
        self.assertEqual(broken["tests"], [])
        fine = self.file_entry(data, "test_fine.py")
        self.assertIs(fine["parse_error"], False)
        self.assertEqual([t["name"] for t in fine["tests"]], ["test_y"])

    def test_undecodable_bytes_do_not_crash_and_scan_continues(self):
        root = self.tmp()
        self.write(root, "test_bytes.py", b"# \xff\xfe\nbad = '\xff'\ndef test_z():\n    assert 1\n", binary=True)
        self.write(root, "web/b.test.js", b"// \xff\xfe\nit('j', () => {});\n", binary=True)
        self.write(root, "x_test.go", b"// \xff\nfunc TestG(t *testing.T) {\n}\n", binary=True)
        data = self.scan(root)
        self.assertEqual([t["name"] for t in self.entry_tests(data, "test_bytes.py")], ["test_z"])
        self.assertEqual(len(self.entry_tests(data, "web/b.test.js")), 1)
        self.assertEqual([t["name"] for t in self.entry_tests(data, "x_test.go")], ["TestG"])

    def test_git_unavailable_yields_null_fields_and_scan_completes(self):
        root = self.tmp()
        run_git(root, "init", "-q")
        self.write(root, ".harness/VERSION", "0.18.0\n")
        self.write(root, "test_x.py", "def test_x():\n    assert 1\n")
        run_git(root, "add", "-A")
        run_git(root, "commit", "-q", "-m", "c", when=1_700_000_000)
        env = dict(os.environ, PATH="")
        entry = self.file_entry(self.scan(root, env=env), "test_x.py")
        self.assertIsNone(entry["last_commit"])
        self.assertIsNone(entry["predates_harness"])


class TestVO8Quality(ScanTestCase):
    # VO8 (QR1, QR3): error guessing; experience-based, no coverage target
    def test_qr1_scanner_imports_only_stdlib_modules(self):
        tree = ast.parse(SCANNER.read_text())
        roots = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                roots.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                self.assertEqual(node.level, 0, "relative import")
                roots.add(node.module.split(".")[0])
        self.assertTrue(roots)
        self.assertEqual(sorted(roots - set(sys.stdlib_module_names)), [])

    def snapshot(self, root):
        entries = {}
        for path in [root, *root.rglob("*")]:
            stat = path.lstat()
            entries[str(path.relative_to(root))] = (stat.st_mtime_ns, stat.st_size)
        return entries

    def test_qr3_scan_leaves_target_tree_unchanged_and_runs_no_project_code(self):
        root = self.tmp()
        marker = root / "EXECUTED"
        self.write(root, "test_exec.py", f"open({str(marker)!r}, 'w').write('x')\ndef test_a():\n    assert 1\n")
        self.write(root, "conftest.py", f"open({str(marker)!r}, 'w').write('x')\n")
        self.write(root, "web/a.test.js", "it('a', () => {});\n")
        self.write(root, "x_test.go", "func TestX(t *testing.T) {\n}\n")
        self.write(root, "tests/data.json", "{}\n")
        self.write(root, "package.json", json.dumps({"scripts": {"test": "node -e \"require('fs').writeFileSync('EXECUTED','x')\""}}))
        run_git(root, "init", "-q")
        run_git(root, "add", "-A")
        run_git(root, "commit", "-q", "-m", "c", when=1_700_000_000)
        before = self.snapshot(root)
        self.scan(root)
        self.scan(root)
        self.assertEqual(self.snapshot(root), before)
        self.assertFalse(marker.exists())


if __name__ == "__main__":
    unittest.main()

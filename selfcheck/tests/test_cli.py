import ast
import re
import subprocess
import sys
import unittest

from selfcheck.tests.helpers import ROOT

SUBCOMMANDS = ["pool", "images", "validate", "mutants", "calibrate", "score"]
FLAGS = {
    "pool": ["--size", "--seed"],
    "images": ["--instances"],
    "validate": ["--repeats", "--instances"],
    "mutants": ["--sample", "--seed", "--workers", "--instances"],
    "calibrate": ["--workers", "--instances"],
    "score": ["--predictions", "--out", "--no-cache", "--workers"],
}


def run_cli(*args):
    return subprocess.run(
        [sys.executable, "-m", "selfcheck", *args], cwd=ROOT, capture_output=True, text=True, timeout=120
    )


class CliTests(unittest.TestCase):
    def test_vo15_x1_unknown_subcommand_exits_2(self):
        for command in ("nope", "pools", "Pool"):
            with self.subTest(command=command):
                self.assertEqual(run_cli(command).returncode, 2)

    def test_vo15_x2_bad_flag_exits_2(self):
        for args in (
            ["pool", "--no-such-flag"],
            ["validate", "--bogus", "1"],
            ["mutants", "--workers", "many"],
            ["pool", "--size", "six"],
            ["score", "--nope"],
            ["--no-such-global-flag"],
        ):
            with self.subTest(args=args):
                self.assertEqual(run_cli(*args).returncode, 2)

    def test_vo15_x3_help_lists_the_six_subcommands(self):
        result = run_cli("--help")
        self.assertEqual(result.returncode, 0)
        for command in SUBCOMMANDS:
            with self.subTest(command=command):
                self.assertRegex(result.stdout, r"\b%s\b" % command)

    def test_vo15_x3_subcommand_help_lists_the_specified_flags(self):
        for command, flags in FLAGS.items():
            result = run_cli(command, "--help")
            self.assertEqual(result.returncode, 0, command)
            for flag in flags:
                with self.subTest(command=command, flag=flag):
                    self.assertIn(flag, result.stdout)

    def test_vo15_x2_pool_does_not_accept_instances(self):
        self.assertEqual(run_cli("pool", "--instances", "a,b").returncode, 2)

    def test_vo15_x2_score_requires_predictions_and_out(self):
        self.assertEqual(run_cli("score").returncode, 2)
        self.assertEqual(run_cli("score", "--predictions", "x.jsonl").returncode, 2)


def imports_swebench(tree):
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            if any(alias.name.split(".")[0] == "swebench" for alias in node.names):
                return True
        elif isinstance(node, ast.ImportFrom):
            if node.module and node.module.split(".")[0] == "swebench":
                return True
        elif isinstance(node, ast.Call):
            func = node.func
            name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
            if name in ("import_module", "__import__"):
                for arg in node.args[:1]:
                    if isinstance(arg, ast.Constant) and isinstance(arg.value, str) and arg.value.startswith("swebench"):
                        return True
    return False


class ImportBoundaryTests(unittest.TestCase):
    def test_vo15_x4_only_swe_module_imports_swebench(self):
        modules = sorted((ROOT / "selfcheck").glob("*.py"))
        names = {path.name for path in modules}
        for required in ("swe.py", "evaluate.py", "patches.py", "pool.py", "validate.py",
                         "mutants.py", "score.py", "calibrate.py", "docker_exec.py", "__main__.py"):
            self.assertIn(required, names)
        importing = {
            path.name for path in modules
            if imports_swebench(ast.parse(path.read_text(encoding="utf-8"), filename=str(path)))
        }
        self.assertEqual(importing, {"swe.py"})


if __name__ == "__main__":
    unittest.main()

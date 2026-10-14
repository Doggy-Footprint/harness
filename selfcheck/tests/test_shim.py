import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

SHIM = Path(__file__).resolve().parents[1] / "agent" / "shim" / "python3"

FAKE_INTERPRETER = """#!/bin/sh
{ echo "%s"; for a in "$@"; do printf '%%s\\n' "$a"; done; } > "$FAKE_OUT"
exit "${FAKE_EXIT:-0}"
"""


class ShimRoutingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="shim-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.out = Path(self.tmp) / "out.txt"
        self.py312 = self.fake("py312")
        self.testbed = self.fake("testbed")

    def fake(self, name):
        path = Path(self.tmp) / name
        path.write_text(FAKE_INTERPRETER % name, encoding="utf-8")
        path.chmod(0o755)
        return str(path)

    def run_shim(self, args, exit_code=None):
        env = {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "SELFCHECK_PY312": self.py312,
            "SELFCHECK_TESTBED_PY": self.testbed,
            "FAKE_OUT": str(self.out),
        }
        if exit_code is not None:
            env["FAKE_EXIT"] = str(exit_code)
        if self.out.exists():
            self.out.unlink()
        proc = subprocess.run(["/bin/sh", str(SHIM), *args], env=env, capture_output=True, text=True, timeout=30)
        if not self.out.exists():
            return proc, None, None
        lines = self.out.read_text(encoding="utf-8").split("\n")[:-1]
        return proc, lines[0], lines[1:]

    def assertRoutes(self, args, expected):
        proc, which, seen = self.run_shim(args)
        self.assertEqual(which, expected, "args %r: stderr %r" % (args, proc.stderr))
        self.assertEqual(seen, list(args))

    def test_vo6_s1_relative_harness_script_runs_on_312(self):
        self.assertRoutes([".harness/bin/x.py"], "py312")

    def test_vo6_s2_absolute_harness_script_runs_on_312(self):
        self.assertRoutes(["/testbed/.harness/hooks/x.py", "arg1"], "py312")

    def test_vo6_s3_other_dash_option_is_skipped(self):
        self.assertRoutes(["-u", ".harness/x.py"], "py312")

    def test_vo6_s4_w_option_skips_its_argument(self):
        self.assertRoutes(["-W", "ignore", ".harness/x.py"], "py312")
        self.assertRoutes(["-W", ".harness/x.py", "other.py"], "testbed")

    def test_vo6_s5_x_option_skips_its_argument(self):
        self.assertRoutes(["-X", "dev", ".harness/x.py"], "py312")
        self.assertRoutes(["-X", ".harness/x.py", "other.py"], "testbed")

    def test_vo6_s6_c_option_selects_the_testbed(self):
        self.assertRoutes(["-c", "code", ".harness/x.py"], "testbed")

    def test_vo6_s7_m_option_selects_the_testbed(self):
        self.assertRoutes(["-m", "mod"], "testbed")

    def test_vo6_s8_no_arguments_select_the_testbed(self):
        self.assertRoutes([], "testbed")

    def test_vo6_s9_plain_script_selects_the_testbed(self):
        self.assertRoutes(["setup.py"], "testbed")

    def test_vo6_s10_directory_component_must_be_exactly_dot_harness(self):
        self.assertRoutes(["my.harness/x.py"], "testbed")

    def test_vo6_s11_script_must_end_in_py(self):
        self.assertRoutes([".harness/x.txt"], "testbed")

    def test_vo6_s12_arguments_with_spaces_are_passed_unchanged(self):
        self.assertRoutes([".harness/x.py", "a b", "", "*", "--flag=c d"], "py312")
        self.assertRoutes(["-c", "print('a b')", "x y", "*", ""], "testbed")

    def test_vo6_s13_interpreter_exit_status_is_propagated(self):
        for args, which in (([".harness/x.py"], "py312"), (["setup.py"], "testbed")):
            for code in (0, 7, 42):
                with self.subTest(which=which, code=code):
                    proc, seen_which, _ = self.run_shim(args, exit_code=code)
                    self.assertEqual(seen_which, which)
                    self.assertEqual(proc.returncode, code)


if __name__ == "__main__":
    unittest.main()

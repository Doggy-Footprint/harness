import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from evaluation.pr_test_quality import junit, recipes

FILE_A = "test/a.test.js"
FILE_B = "test/b.test.js"

FAKE_NODE = """#!/bin/sh
is_test=0
for a in "$@"; do
  [ "$a" = "--test" ] && is_test=1
done
[ "$is_test" = 1 ] || exec "$REAL_NODE" "$@"
dest=""; file=""
for a in "$@"; do
  case "$a" in
    --test-reporter-destination=*) dest="${a#*=}" ;;
    --*) ;;
    *) file="$a" ;;
  esac
done
key=$(echo "$file" | tr '/' '_')
echo "$file" >> "$FAKE_DIR/calls.log"
[ -f "$FAKE_DIR/$key.xml" ] && cp "$FAKE_DIR/$key.xml" "$dest"
rc=0
[ -f "$FAKE_DIR/$key.rc" ] && rc=$(cat "$FAKE_DIR/$key.rc")
exit "$rc"
"""


def case(name, failing=False):
    inner = '<failure type="testCodeFailure" message="boom">trace</failure>' if failing else ""
    return '<testcase name="%s" time="0.000963" classname="test">%s</testcase>' % (name, inner) if inner \
        else '<testcase name="%s" time="0.000963" classname="test"/>' % name


def xml(*suites):
    return ('<?xml version="1.0" encoding="utf-8"?>\n<testsuites>\n%s\n</testsuites>\n' % "\n".join(suites))


def suite(name, *children):
    return ('<testsuite name="%s" time="0.015503" disabled="0" errors="0" tests="1" failures="0" skipped="0" '
            'hostname="604396bff39c">%s</testsuite>' % (name, "".join(children)))


def key(path):
    return path.replace("/", "_")


REAL_NODE = shutil.which("node")


@unittest.skipUnless(REAL_NODE, "a real node binary is needed for the merge step of the generated shell text")
class NodeTestPerFile(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        self.fake = self.tmp / "fake"
        self.fake.mkdir()
        bindir = self.tmp / "bin"
        bindir.mkdir()
        node = bindir / "node"
        node.write_text(FAKE_NODE, encoding="utf-8")
        node.chmod(0o755)
        self.work = self.tmp / "work"
        (self.work / "test").mkdir(parents=True)
        self.junit = self.tmp / "out" / "junit.xml"
        self.junit.parent.mkdir()
        self.env = dict(os.environ, PATH="%s:%s" % (bindir, os.environ["PATH"]), FAKE_DIR=str(self.fake), REAL_NODE=REAL_NODE or "")

    def script(self, path, text=None, rc=0):
        if text is not None:
            (self.fake / (key(path) + ".xml")).write_text(text, encoding="utf-8")
        (self.fake / (key(path) + ".rc")).write_text(str(rc), encoding="utf-8")

    def run_argv(self, files=(FILE_A, FILE_B)):
        recipe = recipes.detect("typescript", {"yarn.lock": "", "package.json": json.dumps(
            {"scripts": {"test": "node --test"}})})
        self.assertEqual(recipe["test"]["runner"], "node-test")
        argv = recipes.test_argv(recipe, list(files), str(self.junit))
        done = subprocess.run(argv, cwd=self.work, env=self.env, capture_output=True, text=True)
        calls = []
        log = self.fake / "calls.log"
        if log.exists():
            calls = log.read_text().split()
        return done.returncode, calls

    def parsed(self):
        return junit.parse(self.junit.read_text(encoding="utf-8"), language="typescript")

    def test_O33_F39_identical_describe_and_name_in_two_files_keep_distinct_ids(self):
        same = xml(suite("help handling", case("when call .help then exit")))
        self.script(FILE_A, same)
        self.script(FILE_B, same)
        rc, calls = self.run_argv()
        self.assertEqual(rc, 0)
        self.assertEqual(sorted(calls), [FILE_A, FILE_B])
        self.assertEqual(self.parsed(), {
            FILE_A + "::help handling::when call .help then exit": "pass",
            FILE_B + "::help handling::when call .help then exit": "pass"})

    def test_O33_F39_each_file_runs_in_its_own_process(self):
        self.script(FILE_A, xml(suite("s", case("x"))))
        self.script(FILE_B, xml(suite("s", case("x"))))
        _, calls = self.run_argv()
        self.assertEqual(sorted(calls), [FILE_A, FILE_B])
        self.assertEqual(len(calls), 2)

    def test_O33_F39_nested_describe_chain_is_joined_in_order(self):
        self.script(FILE_A, xml(suite("outer", suite("inner", case("deep case")), case("shallow case"))))
        self.script(FILE_B, xml(suite("only", case("deep case"))))
        self.run_argv()
        got = self.parsed()
        self.assertEqual(got[FILE_A + "::outer::inner::deep case"], "pass")
        self.assertEqual(got[FILE_A + "::outer::shallow case"], "pass")
        self.assertEqual(got[FILE_B + "::only::deep case"], "pass")
        self.assertEqual(len(got), 3)

    def test_O33_F39_failing_first_file_does_not_stop_the_second_and_exit_is_non_zero(self):
        self.script(FILE_A, xml(suite("s", case("t", failing=True))), rc=1)
        self.script(FILE_B, xml(suite("s", case("t"))), rc=0)
        rc, calls = self.run_argv()
        self.assertNotEqual(rc, 0)
        self.assertEqual(calls, [FILE_A, FILE_B])
        self.assertEqual(self.parsed(), {FILE_A + "::s::t": "fail", FILE_B + "::s::t": "pass"})

    def test_O33_F39_failing_last_file_also_makes_the_exit_non_zero(self):
        self.script(FILE_A, xml(suite("s", case("t"))), rc=0)
        self.script(FILE_B, xml(suite("s", case("t", failing=True))), rc=1)
        rc, _ = self.run_argv()
        self.assertNotEqual(rc, 0)
        self.assertEqual(self.parsed(), {FILE_A + "::s::t": "pass", FILE_B + "::s::t": "fail"})

    def test_O33_F39_a_file_without_output_contributes_no_cases(self):
        self.script(FILE_A, None, rc=1)
        self.script(FILE_B, xml(suite("s", case("t"))))
        rc, calls = self.run_argv()
        self.assertEqual(calls, [FILE_A, FILE_B])
        self.assertNotEqual(rc, 0)
        self.assertEqual(self.parsed(), {FILE_B + "::s::t": "pass"})

    def test_O33_F39_no_output_from_any_file_leaves_no_junit_file(self):
        self.script(FILE_A, None, rc=1)
        self.script(FILE_B, None, rc=1)
        rc, calls = self.run_argv()
        self.assertEqual(calls, [FILE_A, FILE_B])
        self.assertNotEqual(rc, 0)
        self.assertFalse(self.junit.exists())

    def test_O33_F39_single_file_selection_still_carries_the_file_in_ids(self):
        self.script(FILE_A, xml(suite("s", case("t"))))
        rc, _ = self.run_argv([FILE_A])
        self.assertEqual(rc, 0)
        self.assertEqual(self.parsed(), {FILE_A + "::s::t": "pass"})

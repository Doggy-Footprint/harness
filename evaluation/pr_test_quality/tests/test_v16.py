import copy
import json
import re
import unittest

from evaluation.pr_test_quality import junit, recipes
from evaluation.pr_test_quality.tests import test_v12
from evaluation.pr_test_quality.tests.fakes import LANG_FIXTURES, pytest_junit, udiff
from evaluation.pr_test_quality.tests.test_pipeline import Pipe
from evaluation.pr_test_quality.tests.test_v10 import VITEST

OPS = "tests/test_ops.py"
OLD = "def test_keep(): pass\n"
GEN = "when -e then x"
GEN_ID = "%s::%s" % (OPS, GEN)


def tid(name):
    return "%s::%s" % (OPS, name)


class F2pRelevanceWithOrig(Pipe):
    patch = test_v12.ValidateRuns.patch
    validate_with = test_v12.ValidateRuns.validate_with
    state = test_v12.ValidateRuns.state

    def policy(self, orig, base, merge):
        def policy(cont):
            st = self.state(cont, OPS, self.old, self.new, "def clamp")
            table = {"orig": orig, "base": base, "merge": merge}[st if st in ("orig", "merge") else "base"]
            return pytest_junit({tid(k): v for k, v in table.items()})
        return policy

    def scenario(self, added, orig, base, merge):
        self.old = OLD
        self.new = OLD + "".join(line + "\n" for line in added)
        return self.validate_with(self.patch("python", {OPS: self.old}, {OPS: self.new}),
                                  self.policy(orig, base, merge))

    def test_O35_F42_new_generated_name_absent_from_orig_and_from_added_lines_is_kept(self):
        task = self.scenario(["test.each(['-e'])('when %s then x')"],
                             orig={"test_keep": "pass"},
                             base={"test_keep": "pass", GEN: "fail"},
                             merge={"test_keep": "pass", GEN: "pass"})
        self.assertTrue(task["valid"])
        self.assertEqual(task["f2p"], [GEN_ID])
        self.assertEqual(task["p2p"], [tid("test_keep")])

    def test_O35_F42_candidate_failing_at_orig_is_kept_even_when_unnamed(self):
        task = self.scenario(["def test_other(): pass"],
                             orig={"test_keep": "pass", "test_fail_orig": "fail"},
                             base={"test_keep": "pass", "test_fail_orig": "fail", "test_other": "fail"},
                             merge={"test_keep": "pass", "test_fail_orig": "pass", "test_other": "pass"})
        self.assertEqual(sorted(task["f2p"]), [tid("test_fail_orig"), tid("test_other")])
        self.assertNotIn(tid("test_fail_orig"), task["p2p"])

    def test_O35_F42_candidate_passing_at_orig_and_named_in_added_lines_is_kept(self):
        task = self.scenario(["def test_named(): pass"],
                             orig={"test_keep": "pass", "test_named": "pass"},
                             base={"test_keep": "pass", "test_named": "fail"},
                             merge={"test_keep": "pass", "test_named": "pass"})
        self.assertEqual(task["f2p"], [tid("test_named")])
        self.assertNotIn(tid("test_named"), task["p2p"])

    def test_O35_F42_candidate_passing_at_orig_and_not_named_is_dropped_and_in_p2p(self):
        task = self.scenario(["def test_named(): pass"],
                             orig={"test_keep": "pass", "test_stay": "pass"},
                             base={"test_keep": "pass", "test_stay": "fail", "test_named": "fail"},
                             merge={"test_keep": "pass", "test_stay": "pass", "test_named": "pass"})
        self.assertEqual(task["f2p"], [tid("test_named")])
        self.assertEqual(sorted(task["p2p"]), [tid("test_keep"), tid("test_stay")])

    def test_O35_F42_orig_build_error_applies_the_f33_rule(self):
        self.old = OLD
        self.new = OLD + "test.each(['-e'])('when %s then x')\ndef test_named(): pass\n"
        base = {"test_keep": "pass", GEN: "fail", "test_named": "fail"}
        merge = {"test_keep": "pass", GEN: "pass", "test_named": "pass"}

        def policy(cont):
            st = self.state(cont, OPS, self.old, self.new, "def clamp")
            if st == "orig":
                return None
            return pytest_junit({tid(k): v for k, v in (merge if st == "merge" else base).items()})
        task = self.validate_with(self.patch("python", {OPS: self.old}, {OPS: self.new}), policy)
        self.assertEqual(task["p2p_note"], "build_error")
        self.assertEqual(task["f2p"], [tid("test_named")])
        self.assertEqual(task["p2p"], [])
        self.assertTrue(task["valid"])


TS_A = "export const a = 1;\n"
TS_DTS = "export declare const x: number;\n"
REPORT = {"files": {
    "src/a.ts": {"source": TS_A, "mutants": [{"id": "1", "replacement": "2", "location": {
        "start": {"line": 1, "column": 20}, "end": {"line": 1, "column": 21}}}]},
    "types/x.d.ts": {"source": TS_DTS, "mutants": [{"id": "2", "replacement": "string", "location": {
        "start": {"line": 1, "column": 29}, "end": {"line": 1, "column": 35}}}]}}}


class DeclarationFiles(Pipe):
    def ts_task(self, sources):
        row = copy.deepcopy(self.tasks()[0])
        fx = LANG_FIXTURES["typescript"]
        row.update({
            "language": "typescript", "pilot": False,
            "recipe": recipes.detect("typescript", {"yarn.lock": "", "package.json": VITEST}),
            "gold_split": {"src": "".join(udiff(p, None, t) for p, t in sources.items()),
                           "tests": udiff(fx["test_path"], None, fx["test_new"]), "harness": "", "other": ""},
            "gold_base": {**{p: None for p in sources}, fx["test_path"]: None},
            "gold_after": {**sources, fx["test_path"]: fx["test_new"]},
            "f2p": ["src/ops.test.ts::clamp::caps at upper bound zq"],
        })
        path = self.data() / "tasks" / "typescript"
        path.mkdir(parents=True, exist_ok=True)
        (path / "tasks.jsonl").write_text(json.dumps(row) + "\n", encoding="utf-8")

    def list(self, sources):
        self.stage("brief")
        self.ts_task(sources)
        seen = []

        def policy(cont, argv):
            joined = " ".join(argv)
            seen.append(joined)
            return (0, json.dumps(REPORT), False) if "mutation.json" in joined else None
        self.docker.exec_policy = policy
        code, out = self.inv(["mutants", "--language", "typescript"])
        self.assertEqual(code, 0, out)
        task = json.loads((self.data() / "tasks" / "typescript" / "tasks.jsonl").read_text().splitlines()[0])
        return [s for s in seen if "stryker" in s], task

    def test_O35_F43_declaration_files_are_left_out_of_the_mutate_list_and_the_mutants(self):
        listing, task = self.list({"src/a.ts": TS_A, "types/x.d.ts": TS_DTS})
        self.assertEqual(len(listing), 1)
        conf = json.loads(re.search(r"printf %s '(\{.*?\})' > /tmp/stryker\.conf\.json", listing[0]).group(1))
        self.assertEqual(conf["mutate"], ["src/a.ts"])
        self.assertNotIn(".d.ts", listing[0])
        self.assertTrue(task["mutants"])
        self.assertFalse([m for m in task["mutants"] if m["path"].endswith(".d.ts")])
        self.assertEqual({m["path"] for m in task["mutants"]}, {"src/a.ts"})

    def test_O35_F43_only_declaration_files_changed_means_no_stryker_run_and_no_mutants(self):
        listing, task = self.list({"types/x.d.ts": TS_DTS})
        self.assertEqual(listing, [])
        self.assertEqual(task["mutants"], [])


def jest_xml(root_attrs, name):
    return ('<?xml version="1.0" encoding="UTF-8"?>\n<testsuites %s tests="1">'
            '<testsuite name="flags" tests="1"><testcase classname="src/a.test.ts::flags" name="%s" time="0.1"/>'
            '</testsuite></testsuites>' % (root_attrs, name))


class JestJunitEscaping(unittest.TestCase):
    def ids(self, root, name):
        return list(junit.parse(jest_xml(root, name), language="typescript"))

    def test_O35_F44_jest_root_unescapes_the_name_once_more(self):
        (key,) = self.ids('name="jest tests"', "-a, -b &amp;lt;value&amp;gt;")
        self.assertIn("-a, -b <value>", key)
        self.assertNotIn("&lt;", key)
        self.assertNotIn("&amp;", key)

    def test_O35_F44_only_one_extra_unescape_is_applied(self):
        (key,) = self.ids('name="jest tests"', "a &amp;amp;lt; b")
        self.assertIn("a &lt; b", key)

    def test_O35_F44_a_plain_name_under_the_jest_root_is_unchanged(self):
        (key,) = self.ids('name="jest tests"', "plain name")
        self.assertTrue(key.endswith("plain name"))

    def test_O35_F44_vitest_style_root_keeps_the_once_unescaped_text(self):
        (key,) = self.ids('name="vitest tests"', "-a, -b &amp;lt;value&amp;gt;")
        self.assertIn("-a, -b &lt;value&gt;", key)
        (key,) = self.ids("", "-a, -b &amp;lt;value&amp;gt;")
        self.assertIn("-a, -b &lt;value&gt;", key)

    def test_O35_F44_node_test_output_is_unchanged(self):
        xml = ('<?xml version="1.0" encoding="utf-8"?>\n<testsuites>\n<testsuite name="help" time="0.01" tests="1">'
               '<testcase name="when &amp;lt;x&amp;gt;" time="0.1" classname="test"/></testsuite></testsuites>')
        (key,) = junit.parse(xml, language="typescript")
        self.assertIn("&lt;x&gt;", key)

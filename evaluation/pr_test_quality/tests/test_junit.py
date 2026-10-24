import unittest

from evaluation.pr_test_quality import junit

PY_XML = """<?xml version="1.0" encoding="utf-8"?>
<testsuites><testsuite name="pytest" errors="1" failures="1" skipped="1" tests="5" time="0.1">
<testcase classname="tests.test_a.TestX" name="test_pass" file="tests/test_a.py" line="3" time="0.001"/>
<testcase classname="tests.test_a.TestX" name="test_pass_two" file="tests/test_a.py" line="6" time="0.001"/>
<testcase classname="tests.test_a.TestX" name="test_fail" file="tests/test_a.py" line="9" time="0.002"><failure message="assert 1 == 2">trace</failure></testcase>
<testcase classname="tests.test_a.TestX" name="test_err" file="tests/test_a.py" line="12" time="0.002"><error message="boom">trace</error></testcase>
<testcase classname="tests.test_a.TestX" name="test_skip" file="tests/test_a.py" line="15" time="0.0"><skipped type="pytest.skip" message="later"/></testcase>
</testsuite></testsuites>"""

PY_XML_OTHER_STATE = """<?xml version="1.0" encoding="utf-8"?>
<testsuite name="different-name" tests="1" time="9.9">
<testcase time="7.5" file="tests/test_a.py" name="test_pass" classname="tests.test_a.TestX" line="3"/>
</testsuite>"""

PY_PARAM_XML = """<testsuites><testsuite name="pytest" tests="2">
<testcase classname="tests.test_p" name="test_value[1-a]" file="tests/test_p.py" time="0.1"/>
<testcase classname="tests.test_p" name="test_value[2-b]" file="tests/test_p.py" time="0.1"><failure message="x"/></testcase>
</testsuite></testsuites>"""

GO_XML = """<?xml version="1.0" encoding="UTF-8"?>
<testsuites tests="5"><testsuite tests="5" name="example.com/m/pkg/sub" time="0.2">
<testcase classname="example.com/m/pkg/sub" name="TestAlpha" time="0.00"/>
<testcase classname="example.com/m/pkg/sub" name="TestBeta" time="0.00"><failure message="Failed" type="">x</failure></testcase>
<testcase classname="example.com/m/pkg/sub" name="TestGamma/sub_case" time="0.00"><skipped message="s"/></testcase>
<testcase classname="example.com/m/pkg/sub" name="TestDelta" time="0.00"><error message="panic"/></testcase>
<testcase classname="example.com/m/pkg/sub" name="TestEpsilon" time="0.00"/>
</testsuite></testsuites>"""

RUST_XML = """<?xml version="1.0" encoding="UTF-8"?>
<testsuites name="nextest-run" tests="4"><testsuite name="calc" tests="4">
<testcase name="tests::adds_works" classname="calc" time="0.01"/>
<testcase name="tests::fails_here" classname="calc" time="0.01"><failure type="test failure" message="assertion failed"/></testcase>
<testcase name="tests::ignored_one" classname="calc" time="0.0"><skipped/></testcase>
<testcase name="tests::boom" classname="calc" time="0.0"><error type="crash" message="signal"/></testcase>
</testsuite></testsuites>"""

TS_XML = """<?xml version="1.0" encoding="UTF-8" ?>
<testsuites name="vitest tests" tests="4"><testsuite name="src/a.test.ts" tests="4">
<testcase classname="src/a.test.ts" name="clamp &gt; caps at upper" time="0.001"/>
<testcase classname="src/a.test.ts" name="clamp &gt; caps at lower" time="0.001"><failure message="expected 1 to be 2"/></testcase>
<testcase classname="src/a.test.ts" name="clamp &gt; inner &gt; skipped one" time="0"><skipped/></testcase>
<testcase classname="src/a.test.ts" name="clamp &gt; errors out" time="0"><error message="boom"/></testcase>
</testsuite></testsuites>"""


def only(result, suffix):
    hits = [k for k in result if k.endswith(suffix)]
    assert len(hits) == 1, (suffix, sorted(result))
    return hits[0]


class JunitParse(unittest.TestCase):
    def test_O14_error_class_is_value_error(self):
        self.assertTrue(issubclass(junit.JunitError, ValueError))

    def test_O14_C22_python_statuses_and_ids(self):
        result = junit.parse(PY_XML, language="python")
        self.assertEqual(result, {
            "tests/test_a.py::TestX::test_pass": "pass",
            "tests/test_a.py::TestX::test_pass_two": "pass",
            "tests/test_a.py::TestX::test_fail": "fail",
            "tests/test_a.py::TestX::test_err": "error",
            "tests/test_a.py::TestX::test_skip": "skip",
        })

    def test_O14_C24_same_test_same_id_across_states(self):
        one = junit.parse(PY_XML, language="python")
        two = junit.parse(PY_XML_OTHER_STATE, language="python")
        self.assertEqual(list(two), ["tests/test_a.py::TestX::test_pass"])
        self.assertIn("tests/test_a.py::TestX::test_pass", one)

    def test_O14_python_parametrization_suffix_kept_and_ids_distinct(self):
        result = junit.parse(PY_PARAM_XML, language="python")
        first = only(result, "test_value[1-a]")
        second = only(result, "test_value[2-b]")
        self.assertTrue(first.startswith("tests/test_p.py::"))
        self.assertEqual((result[first], result[second]), ("pass", "fail"))

    def test_O14_go_statuses_and_subtest_name_kept(self):
        result = junit.parse(GO_XML, language="go")
        self.assertEqual(len(result), 5)
        self.assertEqual(result[only(result, "TestAlpha")], "pass")
        self.assertEqual(result[only(result, "TestBeta")], "fail")
        self.assertEqual(result[only(result, "TestGamma/sub_case")], "skip")
        self.assertEqual(result[only(result, "TestDelta")], "error")
        self.assertEqual(result[only(result, "TestEpsilon")], "pass")

    def test_O14_go_id_stable_across_states(self):
        other = GO_XML.replace('time="0.00"', 'time="3.21"')
        self.assertEqual(set(junit.parse(GO_XML, language="go")), set(junit.parse(other, language="go")))

    def test_O14_rust_statuses_and_module_path_kept(self):
        result = junit.parse(RUST_XML, language="rust")
        self.assertEqual(len(result), 4)
        self.assertEqual(result[only(result, "tests::adds_works")], "pass")
        self.assertEqual(result[only(result, "tests::fails_here")], "fail")
        self.assertEqual(result[only(result, "tests::ignored_one")], "skip")
        self.assertEqual(result[only(result, "tests::boom")], "error")
        self.assertTrue(all("calc" in k for k in result))

    def test_O14_typescript_statuses_file_and_describe_chain(self):
        result = junit.parse(TS_XML, language="typescript")
        self.assertEqual(len(result), 4)
        for key in result:
            self.assertTrue(key.startswith("src/a.test.ts::"), key)
        self.assertEqual(result[only(result, "caps at upper")], "pass")
        self.assertEqual(result[only(result, "caps at lower")], "fail")
        self.assertEqual(result[only(result, "skipped one")], "skip")
        self.assertEqual(result[only(result, "errors out")], "error")
        self.assertIn("inner", only(result, "skipped one"))
        self.assertIn("clamp", only(result, "caps at upper"))

    def test_O14_typescript_id_stable_across_states(self):
        other = TS_XML.replace('time="0.001"', 'time="1.5"').replace("vitest tests", "again")
        self.assertEqual(set(junit.parse(TS_XML, language="typescript")),
                         set(junit.parse(other, language="typescript")))

    def test_O14_C23_truncated_xml_raises_junit_error(self):
        for lang in ("python", "typescript", "go", "rust"):
            with self.subTest(lang=lang):
                with self.assertRaises(junit.JunitError):
                    junit.parse(PY_XML[:200], language=lang)

    def test_O14_not_xml_and_empty_raise_junit_error(self):
        for text in ("", "plain text, not xml", "<testsuite><testcase name='x'"):
            with self.subTest(text=text):
                with self.assertRaises(junit.JunitError):
                    junit.parse(text, language="python")

    def test_O14_empty_suite_gives_empty_map(self):
        self.assertEqual(junit.parse('<testsuites><testsuite name="s" tests="0"/></testsuites>', language="go"), {})


if __name__ == "__main__":
    unittest.main()

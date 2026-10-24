import os
import re
import unittest
from xml.sax.saxutils import escape, quoteattr

from hypothesis import HealthCheck, given, seed, settings
from hypothesis import strategies as st

from evaluation.pr_test_quality import brief, junit, languages
from evaluation.pr_test_quality.tests.fakes import LANG_FIXTURES, make_task, udiff

EXAMPLES = int(os.environ.get("EVAL_FUZZ_EXAMPLES", "200"))
LANGS = list(languages.LANGUAGES)
STATUSES = {"pass", "fail", "error", "skip"}


NAME = st.text(alphabet=st.characters(blacklist_categories=("Cs", "Cc")), min_size=0, max_size=12)
IDENT = st.from_regex(r"[A-Za-z_][A-Za-z0-9_]{0,8}", fullmatch=True)

CASE = st.tuples(
    st.lists(IDENT, min_size=0, max_size=3).map(".".join),
    NAME,
    st.one_of(st.none(), st.from_regex(r"[a-z_/]{1,10}\.py", fullmatch=True)),
    st.sampled_from(["", "<failure message='x'/>", "<error message='x'/>", "<skipped/>"]),
)


def render_xml(cases, wrapper):
    body = []
    for classname, name, file, inner in cases:
        attrs = "classname=%s name=%s" % (quoteattr(classname), quoteattr(name))
        if file:
            attrs += " file=%s" % quoteattr(file)
        body.append("<testcase %s>%s</testcase>" % (attrs, inner))
    suite = "<testsuite name='s' tests='%d'>%s</testsuite>" % (len(cases), "".join(body))
    return "<testsuites>%s</testsuites>" % suite if wrapper else suite


TEMPLATE = render_xml([("tests.test_a.TestX", "test_one", "tests/test_a.py", ""),
                       ("tests.test_a.TestX", "test_two[1-a]", "tests/test_a.py", "<failure message='x'/>"),
                       ("tests.test_a", "test_three", "tests/test_a.py", "<skipped/>")], True)

EDITS = st.lists(st.tuples(st.integers(0, len(TEMPLATE)), st.integers(0, 12), st.text(max_size=6)), max_size=4)


def mutate(text, edits):
    for pos, cut, ins in edits:
        pos = min(pos, len(text))
        text = text[:pos] + ins + text[pos + cut:]
    return text


class FuzzJunit(unittest.TestCase):
    def check(self, xml, language):
        try:
            result = junit.parse(xml, language=language)
        except junit.JunitError:
            return None
        self.assertIsInstance(result, dict)
        for key, value in result.items():
            self.assertIsInstance(key, str)
            self.assertIn(value, STATUSES)
        return result

    @seed(1)
    @settings(max_examples=EXAMPLES, derandomize=False, database=None, deadline=None,
              suppress_health_check=list(HealthCheck))
    @given(st.text(max_size=300), st.sampled_from(LANGS))
    def test_fuzz_junit_arbitrary_text_only_raises_junit_error(self, text, language):
        self.check(text, language)

    @seed(1)
    @settings(max_examples=EXAMPLES, derandomize=False, database=None, deadline=None,
              suppress_health_check=list(HealthCheck))
    @given(EDITS, st.sampled_from(LANGS))
    def test_fuzz_junit_mutated_valid_xml_only_raises_junit_error(self, edits, language):
        self.check(mutate(TEMPLATE, edits), language)

    @seed(1)
    @settings(max_examples=EXAMPLES, derandomize=False, database=None, deadline=None,
              suppress_health_check=list(HealthCheck))
    @given(st.lists(CASE, max_size=6), st.booleans(), st.sampled_from(LANGS))
    def test_fuzz_junit_wellformed_xml_maps_cases_to_statuses(self, cases, wrapper, language):
        result = self.check(render_xml(cases, wrapper), language)
        if result is not None:
            self.assertLessEqual(len(result), len(cases))


PATH_POOL = [
    "src/pkg/a.py", "tests/test_a.py", "pkg/conftest.py", "src/a.ts", "src/a.test.ts", "src/__tests__/b.ts",
    "pkg/a.go", "pkg/a_test.go", "pkg/testdata/in.txt", "src/lib.rs", "tests/it.rs", "crates/x/src/lib.rs",
    "README.md", "setup.cfg", "conf/x.yaml", ".claude/settings.json", "agent-docs/specs/x.md", ".harness/h.sh",
    "AGENTS.md", "CLAUDE.md", ".agents/s/SKILL.md", ".codex/c.toml",
]
SEGMENT = st.from_regex(r"[a-z]{1,5}", fullmatch=True)
PATH = st.one_of(st.sampled_from(PATH_POOL),
                 st.tuples(st.lists(SEGMENT, max_size=2), SEGMENT,
                           st.sampled_from([".py", ".ts", ".go", ".rs", ".md", ".test.ts", "_test.go", ".json"]))
                 .map(lambda t: "/".join(t[0] + [t[1] + t[2]])))
LINE = st.text(alphabet=st.characters(blacklist_categories=("Cs", "Cc", "Zl", "Zp"), blacklist_characters="\r\n\x0b\x0c\x1c\x1d\x1e\x85"),
               max_size=24)
LINES = st.lists(LINE, min_size=1, max_size=6).map(lambda ls: "".join(l + "\n" for l in ls))
RUST_SRC = "pub fn a() {}\n\n#[cfg(test)]\nmod tests {\n    #[test]\n    fn t() {}\n}\n"
BODY = st.one_of(LINES, st.just(RUST_SRC))
FILE = st.tuples(PATH, st.one_of(st.none(), BODY), st.one_of(st.none(), BODY))


def diff_names(diff):
    return re.findall(r"^diff --git a/(\S+) b/\S+$", diff, re.M)


class FuzzSplitDiff(unittest.TestCase):
    @seed(1)
    @settings(max_examples=EXAMPLES, derandomize=False, database=None, deadline=None,
              suppress_health_check=list(HealthCheck))
    @given(st.sampled_from(LANGS), st.lists(FILE, min_size=1, max_size=5, unique_by=lambda f: f[0]))
    def test_fuzz_P1_parts_rejoin_to_input_file_set_with_no_file_in_two_parts(self, language, files):
        files = [(p, o, n) for p, o, n in files if o != n]
        if not files:
            return
        diff = "".join(udiff(p, o, n) for p, o, n in files)
        parts = languages.split_diff(language, diff)
        self.assertEqual(set(parts), {"src", "tests", "harness", "other"})
        raw = [n for key in ("src", "tests", "harness", "other") for n in diff_names(parts[key])]
        self.assertEqual(len(raw), len(set(raw)), "a file is in two parts: %r" % raw)
        self.assertEqual({n.split("#cfgtest")[0] for n in raw}, {p for p, _, _ in files})
        owner = {"harness": "harness", "test": "tests", "src": "src", "other": "other"}
        for key in ("src", "tests", "harness", "other"):
            for name in diff_names(parts[key]):
                if "#cfgtest" in name:
                    self.assertEqual(key, "tests")
                else:
                    self.assertEqual(key, owner[languages.classify_path(language, name)], name)

    @seed(1)
    @settings(max_examples=EXAMPLES, derandomize=False, database=None, deadline=None,
              suppress_health_check=list(HealthCheck))
    @given(st.sampled_from(LANGS), st.text(max_size=200))
    def test_fuzz_split_diff_never_crashes_on_arbitrary_text(self, language, text):
        parts = languages.split_diff(language, text)
        self.assertEqual(set(parts), {"src", "tests", "harness", "other"})
        for value in parts.values():
            self.assertIsInstance(value, str)

    @seed(1)
    @settings(max_examples=EXAMPLES, derandomize=False, database=None, deadline=None,
              suppress_health_check=list(HealthCheck))
    @given(st.sampled_from(LANGS), st.lists(FILE, min_size=1, max_size=4, unique_by=lambda f: f[0]))
    def test_fuzz_changed_lines_never_crashes_and_stays_inside_new_file(self, language, files):
        files = [(p, o, n) for p, o, n in files if o != n]
        if not files:
            return
        diff = "".join(udiff(p, o, n) for p, o, n in files)
        got = languages.changed_lines(diff)
        sizes = {p: (0 if n is None else len(n.splitlines())) for p, _, n in files}
        for path, lines in got.items():
            self.assertIn(path, sizes)
            self.assertTrue(all(1 <= x <= max(sizes[path], 1) for x in lines), (path, lines))


ITEM_FN = st.integers(0, 9).map(lambda n: ("fn", "pub fn keep_%d() {}\n" % n))
INNER = st.recursive(
    st.integers(0, 9).map(lambda n: "    fn inner_%d() {}\n" % n),
    lambda inner: st.tuples(st.integers(0, 9), inner).map(
        lambda t: "    mod nested_%d {\n%s    }\n" % (t[0], t[1])),
    max_leaves=3)
MOD_HEAD = st.sampled_from(["mod", "pub mod", "pub(crate) mod"])
MOD_GAP = st.sampled_from(["\n", "\n#[allow(dead_code)]\n", "\n// helper tests\n", "\n/* block */\n",
                           "\n#[derive(Debug)]\n// c\n", " "])
ITEM_MOD = st.tuples(st.integers(0, 9), INNER, MOD_HEAD, MOD_GAP).map(
    lambda t: ("mod", "#[cfg(test)]%s%s outer_%d {\n%s}\n" % (t[3], t[2], t[0], t[1])))
ITEM_CFG_FN = st.integers(0, 9).map(lambda n: ("fn", "#[cfg(test)]\nfn helper_%d() {}\n" % n))
ITEM_STR = st.integers(0, 9).map(lambda n: ("fn", "const S_%d: &str = \"#[cfg(test)]\";\n" % n))
ITEMS = st.lists(st.one_of(ITEM_FN, ITEM_MOD, ITEM_CFG_FN, ITEM_STR), max_size=6)
ATTR_MOD = r"#\[cfg\(test\)\](?:\s|//[^\n]*\n|/\*.*?\*/|#\[[^\]]*\])*(?:pub(?:\([^)]*\))?\s+)?mod\b"


class FuzzSplitRustInline(unittest.TestCase):
    @seed(1)
    @settings(max_examples=EXAMPLES, derandomize=False, database=None, deadline=None,
              suppress_health_check=list(HealthCheck))
    @given(ITEMS)
    def test_fuzz_P2_mods_occur_in_source_and_rest_has_no_cfg_test(self, items):
        src = "\n".join(text for _, text in items)
        rest, mods = languages.split_rust_inline(src)
        for mod in mods:
            self.assertIn(mod, src)
        self.assertIsNone(re.search(ATTR_MOD, rest, re.S))
        self.assertEqual(len(mods), sum(1 for kind, _ in items if kind == "mod"))
        for kind, text in items:
            if kind == "fn":
                self.assertIn(text.strip(), rest)
            else:
                self.assertNotIn(re.search(r"outer_\d+ \{", text).group(0), rest)

    @seed(1)
    @settings(max_examples=EXAMPLES, derandomize=False, database=None, deadline=None,
              suppress_health_check=list(HealthCheck))
    @given(st.text(alphabet="#[]()cfgtestmod {}\n\"/*abc_", max_size=120))
    def test_fuzz_split_rust_inline_never_crashes_and_mods_come_from_the_source(self, text):
        rest, mods = languages.split_rust_inline(text)
        if '"' not in text and "/" not in text:
            self.assertIsNone(re.search(ATTR_MOD, rest, re.S), rest)
        self.assertIsInstance(rest, str)
        self.assertLessEqual(len(rest), len(text))
        for mod in mods:
            self.assertIn(mod, text)


class FuzzLeaks(unittest.TestCase):
    TASKS = {lang: make_task(lang) for lang in LANGS}

    @seed(1)
    @settings(max_examples=EXAMPLES, derandomize=False, database=None, deadline=None,
              suppress_health_check=list(HealthCheck))
    @given(st.sampled_from(LANGS), st.data())
    def test_fuzz_P3_every_reported_leak_occurs_in_the_text(self, language, data):
        task = self.TASKS[language]
        terms = sorted(brief.forbidden_terms(task))
        pieces = st.one_of(st.text(max_size=15), st.sampled_from(terms), st.sampled_from(LANG_FIXTURES[language]["f2p"]))
        text = "".join(data.draw(st.lists(pieces, max_size=8)))
        found = brief.leaks(text, task)
        self.assertEqual(found, sorted(set(found)))
        for term in found:
            self.assertIn(term, text)
            self.assertIn(term, terms)
        for term in terms:
            if re.search(r"(?<!\w)" + re.escape(term) + r"(?!\w)", text):
                self.assertIn(term, found)

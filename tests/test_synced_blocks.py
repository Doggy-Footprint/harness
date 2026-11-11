import hashlib
import importlib
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from test_installer import REPO_ROOT, InstallerTestCase, run_git, run_installer
from test_hook_owned_progress import valid_text
from test_record_only_progress import BASE_0420, old_release_source

ID = "a1b2c3d4e5f6"
ID2 = "0f1e2d3c4b5a"
ID3 = "00aa11bb22cc"
UNRELATED = "0000000000aa"
STUB_HASH = "000000000000"
TRACKING_BODY = "\n# Content\nshared text\n\n# Version Log\n## v1 Log\n- Initial creation.\n"

S11 = [
    "progress hook: a session that changed only agent-docs records gets a record-only progress kept by the hook",
    "synced comments: code_hash covers only the lines between a tag and its `synced end: <id>` line; "
    "python3 .harness/bin/records.py synced-refresh <id> updates count, code_hash, version, and tags",
    "python3 .harness/bin/records.py stale <path> marks a record stale",
    "the first Write or Edit in an agent-docs rule directory adds that rule's text to the session",
    "data: code_hash is recomputed for synced ids that already have end markers; AGENTS.md is unchanged",
]


def e_s1(path, line, ident):
    return f"{path}:{line}: synced id {ident} has no later `synced end: {ident}` line; add it where the tagged block ends"


def e_s2(path, line, ident):
    return f"{path}:{line}: `synced end: {ident}` has no synced id {ident} tag before it"


def r1(ident):
    return f"synced id {ident}: count and code_hash unchanged"


def r2(ident, old, new, count, code_hash, n):
    return f"synced id {ident}: version {old} -> {new}, count {count}, code_hash {code_hash}; updated {n} tag(s)"


def m1_pattern(ident, paths):
    joined = r",\s?".join(re.escape(p) for p in paths)
    return (re.escape(f"synced id {ident}: add `synced end: {ident}` after each tagged block in ")
            + joined + re.escape(f", then run python3 .harness/bin/records.py synced-refresh {ident}"))


def tag(ident, version=1, count=2, style="py"):
    core = f"synced id: {ident}, version: {version}, count: {count}"
    return f"# {core}" if style == "py" else f"<!-- {core} -->"


def end(ident, style="py"):
    core = f"synced end: {ident}"
    return f"# {core}" if style == "py" else f"<!-- {core} -->"


def ref_hash(blocks):
    digest = hashlib.sha256()
    for _, _, lines in sorted(blocks, key=lambda block: (block[0], block[1])):
        for line in lines:
            digest.update(f"{line}\n".encode())
    return digest.hexdigest()[:12]


def tag_line_of(lines, ident):
    return next(i for i, line in enumerate(lines, 1) if f"synced id: {ident}" in line)


def block_of(path, lines, ident):
    start = tag_line_of(lines, ident)
    stop = next(i for i, line in enumerate(lines, 1) if i > start and f"synced end: {ident}" in line)
    inner = [line for line in lines[start:stop - 1]
             if not re.search(r"synced (id|end): [0-9a-f]{12}", line) and not line.strip().startswith("#")]
    return (path, start, inner)


def tracking_text(version, count, code_hash, extra="", body=TRACKING_BODY):
    return f"---\nversion: {version}\ncount: {count}\ncode_hash: {code_hash}\n{extra}---\n{body}"


def sync_lines_a(ident=ID, version=1, count=2):
    return ["start_a = 1", tag(ident, version, count), "def f():", "    return 1", end(ident), "tail_a = 1"]


def sync_lines_b(ident=ID, version=1, count=2):
    return ["import os", tag(ident, version, count), "def g():", "    return 2", end(ident), "tail_b = 2"]


class SyncedCase(InstallerTestCase):
    docs = "agent-docs"

    def installed(self, docs_root=None):
        repo = self.make_repo()
        result = run_installer("install", str(repo), "--no-ci")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        if docs_root:
            (repo / ".harness" / "config.json").write_text(json.dumps({"docs_root": docs_root}))
            self.docs = docs_root
        return repo

    def write_lines(self, repo, rel, lines):
        path = repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(lines) + "\n")
        return path

    def write_tracking(self, repo, ident, text):
        path = repo / self.docs / "synced-comments" / f"{ident}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        return path

    def stage(self, repo, *extra):
        run_git(repo, "add", "-A")
        if extra:
            run_git(repo, "add", "-f", "--", *extra)

    def verify(self, repo):
        env = {k: v for k, v in os.environ.items() if k not in ("CLAUDE_CODE_SESSION_ID", "CLAUDE_SESSION_ID")}
        result = subprocess.run([sys.executable, str(repo / ".harness" / "git" / "verify_rules.py")],
                                capture_output=True, text=True, cwd=repo, env=env)
        return result, result.stdout + result.stderr

    def basic(self, docs_root=None):
        repo = self.installed(docs_root)
        a, b = sync_lines_a(), sync_lines_b()
        self.write_lines(repo, "a.py", a)
        self.write_lines(repo, "b.py", b)
        blocks = [block_of("a.py", a, ID), block_of("b.py", b, ID)]
        tracking = self.write_tracking(repo, ID, tracking_text(1, 2, ref_hash(blocks)))
        self.stage(repo, str(tracking.relative_to(repo)))
        return repo

    def assert_passes(self, repo):
        self.stage(repo)
        result, text = self.verify(repo)
        self.assertEqual(result.returncode, 0, text)

    def assert_fails_for(self, repo, ident=ID):
        self.stage(repo)
        result, text = self.verify(repo)
        self.assertNotEqual(result.returncode, 0, text)
        self.assertIn(ident, text)
        return text

    def lines_mentioning(self, text, ident):
        return [line for line in text.splitlines() if ident in line]


class TestSynced(SyncedCase):
    def test_tracking_with_the_independently_computed_hash_passes(self):
        self.assert_passes(self.basic())

    def test_a_wrong_code_hash_fails(self):
        repo = self.basic()
        path = repo / "agent-docs" / "synced-comments" / f"{ID}.md"
        text = path.read_text()
        current = re.search(r"code_hash: ([0-9a-f]{12})", text).group(1)
        flipped = ("0" if current[0] != "0" else "1") + current[1:]
        path.write_text(text.replace(current, flipped))
        self.assert_fails_for(repo)

    def test_edit_outside_every_block_keeps_the_check_passing(self):
        repo = self.basic()
        self.write_lines(repo, "a.py", ["start_a = 99"] + sync_lines_a()[1:5] + ["tail_a = 99", "extra = 1"])
        self.write_lines(repo, "b.py", ["import sys"] + sync_lines_b()[1:])
        self.assert_passes(repo)

    def test_edit_inside_a_block_fails_the_check(self):
        repo = self.basic()
        lines = sync_lines_a()
        lines[3] = "    return 100"
        self.write_lines(repo, "a.py", lines)
        self.assert_fails_for(repo)

    def test_comment_only_line_inside_a_block_does_not_change_the_hash(self):
        repo = self.basic()
        lines = sync_lines_a()
        lines.insert(3, "    # note added inside the block")
        lines.insert(3, "# another comment-only line")
        self.write_lines(repo, "a.py", lines)
        self.assert_passes(repo)

    def test_tag_line_version_text_is_not_hashed(self):
        repo = self.basic()
        self.write_lines(repo, "a.py", sync_lines_a(version=2))
        self.write_lines(repo, "b.py", sync_lines_b(version=2))
        blocks = [block_of("a.py", sync_lines_a(version=2), ID), block_of("b.py", sync_lines_b(version=2), ID)]
        self.write_tracking(repo, ID, tracking_text(2, 2, ref_hash(blocks)))
        self.assert_passes(repo)

    def test_tag_quoted_inside_agent_docs_is_not_a_code_location(self):
        repo = self.basic()
        quoted = f"`{tag(ID, 1, 3, 'md')}` and `{tag(UNRELATED, 1, 1, 'md')}` quoted in prose"
        progress = repo / "agent-docs" / "progress" / "1111111111111111-quote.md"
        progress.parent.mkdir(parents=True, exist_ok=True)
        progress.write_text(valid_text("sessb", changes=f"- {quoted}"))
        tracking = repo / "agent-docs" / "synced-comments" / f"{ID}.md"
        tracking.write_text(tracking.read_text().replace("shared text", f"shared text {quoted}"))
        self.assert_passes(repo)

    def test_two_blocks_of_one_id_in_one_file_are_both_counted_and_hashed(self):
        repo = self.installed()
        a = ["one = 1", tag(ID, 1, 3), "def f():", "    return 1", end(ID), "gap = 0", tag(ID, 1, 3), "def h():", "    return 3", end(ID)]
        b = sync_lines_b(count=3)
        self.write_lines(repo, "a.py", a)
        self.write_lines(repo, "b.py", b)
        first = ("a.py", 2, ["def f():", "    return 1"])
        second = ("a.py", 7, ["def h():", "    return 3"])
        self.assertEqual(tag_line_of(a, ID), 2)
        tracking = self.write_tracking(repo, ID, tracking_text(1, 3, ref_hash([first, second, block_of("b.py", b, ID)])))
        self.stage(repo, str(tracking.relative_to(repo)))
        self.assert_passes(repo)
        a[8] = "    return 33"
        self.write_lines(repo, "a.py", a)
        self.assert_fails_for(repo)

    def nested_repo(self):
        repo = self.installed()
        a = ["pre = 0", tag(ID), "x1 = 1", tag(ID2), "y1 = 1", end(ID2), "x2 = 2", end(ID), "post = 0"]
        b = ["pre = 0", tag(ID), "x1 = 10", tag(ID2), "y1 = 10", end(ID2), "x2 = 20", end(ID), "post = 0"]
        self.write_lines(repo, "a.py", a)
        self.write_lines(repo, "b.py", b)
        outer = [("a.py", 2, ["x1 = 1", "y1 = 1", "x2 = 2"]), ("b.py", 2, ["x1 = 10", "y1 = 10", "x2 = 20"])]
        inner = [("a.py", 4, ["y1 = 1"]), ("b.py", 4, ["y1 = 10"])]
        self.assertEqual(tag_line_of(a, ID2), 4)
        paths = [self.write_tracking(repo, ID, tracking_text(1, 2, ref_hash(outer))),
                 self.write_tracking(repo, ID2, tracking_text(1, 2, ref_hash(inner)))]
        self.stage(repo, *[str(p.relative_to(repo)) for p in paths])
        return repo, a, b

    def test_nested_ids_each_end_at_their_own_marker_and_pass(self):
        repo, _, _ = self.nested_repo()
        self.assert_passes(repo)

    def test_nested_inner_edit_fails_both_ids_and_outer_only_edit_fails_only_the_outer(self):
        repo, a, b = self.nested_repo()
        inner = list(a)
        inner[4] = "y1 = 99"
        self.write_lines(repo, "a.py", inner)
        self.stage(repo)
        result, text = self.verify(repo)
        self.assertNotEqual(result.returncode, 0, text)
        self.assertTrue(self.lines_mentioning(text, ID), text)
        self.assertTrue(self.lines_mentioning(text, ID2), text)
        outer = list(a)
        outer[6] = "x2 = 99"
        self.write_lines(repo, "a.py", outer)
        self.stage(repo)
        result, text = self.verify(repo)
        self.assertNotEqual(result.returncode, 0, text)
        self.assertTrue(self.lines_mentioning(text, ID), text)
        self.assertEqual(self.lines_mentioning(text, ID2), [], text)

    def nested_non_comment_repo(self, style):
        repo = self.installed()
        if style == "md":
            names = ("notes/a.md", "notes/b.md")

            def layout(n, version=1):
                return ["intro", tag(ID, 1, 2, "md"), f"x1 text {n}", tag(ID2, version, 2, "md"), f"y1 text {n}",
                        end(ID2, "md"), f"x2 text {n}", end(ID, "md"), "outro"]

            outer_lines = lambda n: [f"x1 text {n}", f"y1 text {n}", f"x2 text {n}"]
            inner_lines = lambda n: [f"y1 text {n}"]
        else:
            names = ("a.py", "b.py")

            def layout(n, version=1):
                return [tag(ID), f"x1 = {n}", f"z = 1  # synced id: {ID2}, version: {version}, count: 2", f"y1 = {n}",
                        f"w = 2  # synced end: {ID2}", f"x2 = {n}", end(ID)]

            outer_lines = lambda n: [f"x1 = {n}", f"y1 = {n}", f"x2 = {n}"]
            inner_lines = lambda n: [f"y1 = {n}"]
        outer_tag = 2 if style == "md" else 1
        inner_tag = 4 if style == "md" else 3
        for name, n in zip(names, (1, 2)):
            self.write_lines(repo, name, layout(n))
        outer = [(name, outer_tag, outer_lines(n)) for name, n in zip(names, (1, 2))]
        inner = [(name, inner_tag, inner_lines(n)) for name, n in zip(names, (1, 2))]
        paths = [self.write_tracking(repo, ID, tracking_text(1, 2, ref_hash(outer))),
                 self.write_tracking(repo, ID2, tracking_text(1, 2, ref_hash(inner)))]
        self.stage(repo, *[str(p.relative_to(repo)) for p in paths])
        return repo, names, layout, inner

    def test_nested_id_tag_and_end_lines_that_are_not_comment_only_are_excluded_from_the_outer_hash(self):
        for style in ("md", "py-trailing-comment"):
            with self.subTest(style=style):
                repo, names, layout, inner = self.nested_non_comment_repo(style)
                self.assert_passes(repo)

    def test_bumping_the_inner_tag_version_leaves_the_outer_check_passing(self):
        for style in ("md", "py-trailing-comment"):
            with self.subTest(style=style):
                repo, names, layout, inner = self.nested_non_comment_repo(style)
                for name, n in zip(names, (1, 2)):
                    self.write_lines(repo, name, layout(n, version=2))
                self.write_tracking(repo, ID2, tracking_text(2, 2, ref_hash(inner)))
                self.assert_passes(repo)

    def test_markdown_participant_keeps_heading_lines_inside_its_block(self):
        repo = self.installed()
        a = sync_lines_a(count=2)
        md = ["intro", tag(ID, 1, 2, "md"), "# Heading kept", "plain text", end(ID, "md"), "outro"]
        self.write_lines(repo, "a.py", a)
        self.write_lines(repo, "notes/guide.md", md)
        blocks = [block_of("a.py", a, ID), ("notes/guide.md", 2, ["# Heading kept", "plain text"])]
        tracking = self.write_tracking(repo, ID, tracking_text(1, 2, ref_hash(blocks)))
        self.stage(repo, str(tracking.relative_to(repo)))
        self.assert_passes(repo)
        md[3] = "plain text changed"
        self.write_lines(repo, "notes/guide.md", md)
        self.assert_fails_for(repo)

    def test_block_hash_unit_equals_the_independent_sha256_and_reports_block_fields(self):
        lib = str(REPO_ROOT / "harness" / "lib")
        if lib not in sys.path:
            sys.path.insert(0, lib)
        synced = importlib.import_module("synced")
        repo = self.basic()
        quoted = repo / "agent-docs" / "quoted.md"
        quoted.write_text("\n".join([tag(ID, 1, 2, "md"), "quoted line", end(ID, "md")]) + "\n")
        blocks, errors = synced.scan(repo, [repo / "a.py", repo / "b.py", quoted], repo / "agent-docs", frozenset())
        self.assertEqual(errors, [])
        self.assertEqual(sorted(blocks), [ID])
        found = sorted(blocks[ID], key=lambda block: block.path)
        self.assertEqual([b.path for b in found], ["a.py", "b.py"])
        self.assertEqual([b.tag_line for b in found], [2, 2])
        self.assertEqual([b.end_line for b in found], [5, 5])
        self.assertEqual([(b.version, b.count) for b in found], [(1, 2), (1, 2)])
        self.assertEqual(found[0].lines, ["def f():", "    return 1"])
        expected = ref_hash([block_of("a.py", sync_lines_a(), ID), block_of("b.py", sync_lines_b(), ID)])
        self.assertEqual(synced.block_hash(found), expected)
        self.assertEqual(synced.block_hash(list(reversed(found))), expected)

    def test_scan_reports_the_exact_structural_error_texts(self):
        lib = str(REPO_ROOT / "harness" / "lib")
        if lib not in sys.path:
            sys.path.insert(0, lib)
        synced = importlib.import_module("synced")
        repo = self.installed()
        self.write_lines(repo, "a.py", ["x = 1", tag(ID), "y = 2"])
        self.write_lines(repo, "b.py", ["z = 3", end(ID2), "w = 4"])
        _, errors = synced.scan(repo, [repo / "a.py", repo / "b.py"], repo / "agent-docs", frozenset())
        self.assertEqual(sorted(errors), sorted([e_s1("a.py", 2, ID), e_s2("b.py", 2, ID2)]))

    def test_scan_reports_the_second_end_of_tag_end_end_as_the_second_structural_error(self):
        lib = str(REPO_ROOT / "harness" / "lib")
        if lib not in sys.path:
            sys.path.insert(0, lib)
        synced = importlib.import_module("synced")
        repo = self.installed()
        self.write_lines(repo, "a.py", ["x = 1", tag(ID, 1, 1), "y = 2", end(ID), end(ID)])
        _, errors = synced.scan(repo, [repo / "a.py"], repo / "agent-docs", frozenset())
        self.assertEqual(errors, [e_s2("a.py", 5, ID)])

    def test_synced_comments_count_and_version_checks_are_unchanged(self):
        repo = self.basic()
        a = sync_lines_a(count=3)
        self.write_lines(repo, "a.py", a)
        self.assert_fails_for(repo)


class TestStructuralErrors(SyncedCase):
    def structural_repo(self, a, b, count):
        repo = self.installed()
        self.write_lines(repo, "a.py", a)
        self.write_lines(repo, "b.py", b)
        tracking = self.write_tracking(repo, ID, tracking_text(1, count, STUB_HASH))
        self.stage(repo, str(tracking.relative_to(repo)))
        return repo

    def run_check(self, repo):
        self.stage(repo)
        result, text = self.verify(repo)
        self.assertNotEqual(result.returncode, 0, text)
        return text

    def test_tag_without_a_later_end_reports_the_first_structural_error_and_skips_the_hash(self):
        a = ["x = 1", tag(ID), "y = 2"]
        repo = self.structural_repo(a, sync_lines_b(), 2)
        text = self.run_check(repo)
        self.assertIn(e_s1("a.py", 2, ID), text)
        self.assertEqual(len(self.lines_mentioning(text, ID)), 1, text)

    def test_end_without_an_earlier_tag_reports_the_second_structural_error_and_skips_the_hash(self):
        a = ["x = 1", end(ID), "y = 2"]
        repo = self.structural_repo(a, sync_lines_b(count=1), 1)
        text = self.run_check(repo)
        self.assertIn(e_s2("a.py", 2, ID), text)
        self.assertEqual(len(self.lines_mentioning(text, ID)), 1, text)

    def test_both_errors_in_one_id_are_reported_and_the_end_before_the_tag_does_not_close_it(self):
        a = ["x = 1", end(ID), "y = 2", tag(ID), "z = 3"]
        repo = self.structural_repo(a, sync_lines_b(), 2)
        text = self.run_check(repo)
        self.assertIn(e_s2("a.py", 2, ID), text)
        self.assertIn(e_s1("a.py", 4, ID), text)
        self.assertEqual(len(self.lines_mentioning(text, ID)), 2, text)

    def test_an_end_in_another_file_does_not_close_the_tag(self):
        a = ["x = 1", tag(ID, 1, 1), "y = 2"]
        b = ["w = 0", "v = 1", end(ID)]
        repo = self.structural_repo(a, b, 1)
        text = self.run_check(repo)
        self.assertIn(e_s1("a.py", 2, ID), text)
        self.assertIn(e_s2("b.py", 3, ID), text)

    def test_second_end_after_a_closed_block_is_the_second_structural_error_and_skips_the_hash(self):
        a = ["x = 1", tag(ID, 1, 1), "y = 2", end(ID), end(ID)]
        repo = self.structural_repo(a, ["w = 0"], 1)
        text = self.run_check(repo)
        self.assertIn(e_s2("a.py", 5, ID), text)
        self.assertNotIn(e_s1("a.py", 2, ID), text)
        self.assertEqual(len(self.lines_mentioning(text, ID)), 1, text)

    def test_each_error_names_its_own_line_for_two_unclosed_tags(self):
        a = [tag(ID), "x = 1", "# filler", tag(ID)]
        repo = self.structural_repo(a, ["w = 0"], 2)
        text = self.run_check(repo)
        self.assertIn(e_s1("a.py", 1, ID), text)
        self.assertIn(e_s1("a.py", 4, ID), text)


class TestConfiguredDocsRootScan(SyncedCase):
    def test_tracking_file_and_quoted_tags_under_the_configured_docs_root_are_used_and_excluded(self):
        repo = self.basic(docs_root="docs/agent")
        quoted = f"`{tag(ID, 1, 3, 'md')}` quoted in prose"
        progress = repo / "docs" / "agent" / "progress" / "1111111111111111-quote.md"
        progress.parent.mkdir(parents=True, exist_ok=True)
        progress.write_text(valid_text("sessb", changes=f"- {quoted}"))
        self.assert_passes(repo)

    def test_default_agent_docs_path_is_scanned_when_it_is_not_the_configured_docs_root(self):
        repo = self.basic(docs_root="docs/agent")
        (repo / "agent-docs").mkdir(exist_ok=True)
        (repo / "agent-docs" / "extra.md").write_text("\n".join([tag(ID, 1, 3, "md"), "line", end(ID, "md")]) + "\n")
        self.assert_fails_for(repo)


class TestUpdateFrom0420(SyncedCase):
    P_OLD_HASH = "123456abcdef"

    @classmethod
    def setUpClass(cls):
        cls.source = old_release_source()

    def installed_0420(self):
        repo = self.make_repo()
        installed = subprocess.run([sys.executable, str(self.source / "installer" / "harness.py"), "install", str(repo), "--no-ci"],
                                   capture_output=True, text=True)
        self.assertEqual(installed.returncode, 0, installed.stdout + installed.stderr)
        self.assertEqual(json.loads((repo / ".harness" / "manifest.json").read_text())["version"], "0.42.0")
        return repo

    def populate(self):
        repo = self.installed_0420()
        p_a, p_b = sync_lines_a(ID, 3, 2), sync_lines_b(ID, 3, 2)
        q_c = ["c0 = 0", tag(ID2, 1, 2), "def c():", "    return 1", "c9 = 9"]
        q_d = ["d0 = 0", tag(ID2, 1, 2), "def d():", "    return 2", "d9 = 9"]
        e_a = ["e0 = 0", tag(ID3, 1, 2), "def e():", "    return 1"]
        e_b = ["f0 = 0", tag(ID3, 1, 2), "def f2():", "    return 2", end(ID3)]
        for rel, lines in (("a.py", p_a), ("b.py", p_b), ("c.py", q_c), ("d.py", q_d), ("ea.py", e_a), ("eb.py", e_b)):
            self.write_lines(repo, rel, lines)
        self.write_lines(repo, "oa.py", [tag("0b0b0b0b0b0b", 2, 1), "o = 1", end("0b0b0b0b0b0b")])
        self.write_lines(repo, "za.py", [tag("0c0c0c0c0c0c", 1, 1), "z = 1", end("0c0c0c0c0c0c")])
        files = {
            "p": self.write_tracking(repo, ID, tracking_text(3, 2, self.P_OLD_HASH)),
            "q": self.write_tracking(repo, ID2, tracking_text(1, 2, self.P_OLD_HASH)),
            "e": self.write_tracking(repo, ID3, tracking_text(1, 2, self.P_OLD_HASH)),
            "o": self.write_tracking(repo, "0b0b0b0b0b0b", tracking_text(2, 1, self.P_OLD_HASH, extra="obsolete: true\n")),
            "z": self.write_tracking(repo, "0c0c0c0c0c0c", "no frontmatter here\n"),
            "n": self.write_tracking(repo, "0d0d0d0d0d0d", tracking_text(1, 1, self.P_OLD_HASH)),
        }
        run_git(repo, "add", "-A")
        run_git(repo, "add", "-f", "--", *[str(p.relative_to(repo)) for p in files.values()])
        run_git(repo, "commit", "-q", "--no-verify", "-m", "base")
        return repo, files, (p_a, p_b)

    def update(self, repo):
        return run_installer("update", str(repo), "--no-ci", "--no-commit", input="y\n" * 20, exact=True)

    def test_update_announces_the_migration_last_with_the_plan_lines_in_order(self):
        repo, _, _ = self.populate()
        agents = (repo / "AGENTS.md").read_bytes()
        result = self.update(repo)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        announced = re.findall(r"^migration (\d+\.\d+\.\d+):", result.stdout, re.MULTILINE)
        self.assertEqual(announced, ["0.43.0"], result.stdout)
        start = result.stdout.index("migration 0.43.0:")
        positions = []
        for line in S11:
            self.assertIn(line, result.stdout[start:])
            positions.append(result.stdout.index(line, start))
        self.assertEqual(positions, sorted(positions))
        self.assertEqual((repo / "AGENTS.md").read_bytes(), agents)
        self.assertEqual(json.loads((repo / ".harness" / "manifest.json").read_text())["version"], "0.43.0")
        doctor = run_installer("doctor", str(repo))
        self.assertEqual(doctor.returncode, 0, doctor.stdout + doctor.stderr)

    def test_data_step_recomputes_only_ids_with_ended_blocks_and_changes_no_version(self):
        repo, files, (p_a, p_b) = self.populate()
        before = {key: path.read_bytes() for key, path in files.items()}
        result = self.update(repo)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        expected = ref_hash([block_of("a.py", p_a, ID), block_of("b.py", p_b, ID)])
        self.assertEqual(files["p"].read_text(), before["p"].decode().replace(self.P_OLD_HASH, expected))
        for key in ("q", "e", "o", "z", "n"):
            with self.subTest(file=key):
                self.assertEqual(files[key].read_bytes(), before[key])

    def test_m1_is_printed_once_for_each_id_that_needs_end_markers_and_only_for_them(self):
        repo, _, _ = self.populate()
        result = self.update(repo)
        text = result.stdout + result.stderr
        self.assertEqual(len(re.findall(m1_pattern(ID2, ["c.py", "d.py"]), text)), 1, text)
        loose = (re.escape(f"synced id {ID3}: add `synced end: {ID3}` after each tagged block in ")
                 + r"[^\n]*" + re.escape(f", then run python3 .harness/bin/records.py synced-refresh {ID3}"))
        self.assertEqual(len(re.findall(loose, text)), 1, text)
        for ident in (ID, "0b0b0b0b0b0b", "0c0c0c0c0c0c", "0d0d0d0d0d0d"):
            with self.subTest(ident=ident):
                self.assertNotIn(f"synced id {ident}: add", text)

    def test_update_leaves_code_files_unchanged(self):
        repo, _, _ = self.populate()
        before = {p.name: p.read_bytes() for p in repo.glob("*.py")}
        self.update(repo)
        self.assertEqual({p.name: p.read_bytes() for p in repo.glob("*.py")}, before)

    def test_dry_run_prints_the_plan_lines_and_changes_nothing(self):
        repo, files, _ = self.populate()
        agents = (repo / "AGENTS.md").read_bytes()
        before = {key: path.read_bytes() for key, path in files.items()}
        result = run_installer("update", str(repo), "--no-ci", "--dry-run", forbid_input=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        for line in S11:
            self.assertIn(line, result.stdout)
        self.assertEqual((repo / "AGENTS.md").read_bytes(), agents)
        self.assertEqual({key: path.read_bytes() for key, path in files.items()}, before)
        self.assertEqual(json.loads((repo / ".harness" / "manifest.json").read_text())["version"], "0.42.0")


if __name__ == "__main__":
    unittest.main()

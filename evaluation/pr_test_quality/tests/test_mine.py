import json
import re
import tempfile
import urllib.parse
import unittest
from pathlib import Path

from evaluation.pr_test_quality import mine
from evaluation.pr_test_quality.tests.fakes import MISSING, TmpCase, find, spec_cfg


def pr(title="Add clamp helper", login="alice", language="python", **over):
    out = {"number": 7, "title": title, "body": "body", "user": {"login": login},
           "merged_at": "2026-08-02T10:00:00Z", "language": language}
    out.update(over)
    return out


def sfile(name, add, dele=0, patch=None, **over):
    out = {"filename": name, "status": "modified", "additions": add, "deletions": dele,
           "patch": patch if patch is not None else "@@ -1 +1 @@\n" + "+x = 1\n" * max(add, 1)}
    out.update(over)
    return out


def tfile(name="tests/test_a.py"):
    return sfile(name, 5, patch="@@ -0,0 +1 @@\n+def test_a(): pass\n")


class Eligible(unittest.TestCase):
    def setUp(self):
        self.cfg = spec_cfg()

    def check(self, p, files, reason):
        ok, got = mine.eligible(p, files, self.cfg)
        self.assertEqual(got, reason)
        self.assertEqual(ok, reason == "ok")

    def test_O1_C1_normal_pr_is_ok(self):
        files = [sfile("src/a.py", 40), sfile("src/b.py", 40), sfile("src/c.py", 40), tfile()]
        self.check(pr(), files, "ok")

    def test_O1_C2_src_line_boundaries(self):
        cases = [((15, 15), "ok"), ((15, 14), "src_lines"), ((400, 400), "ok"), ((400, 401), "src_lines")]
        for (a, b), reason in cases:
            with self.subTest(lines=a + b):
                self.check(pr(), [sfile("src/a.py", a), sfile("src/b.py", b), tfile()], reason)

    def test_O1_src_lines_count_added_plus_deleted(self):
        self.check(pr(), [sfile("src/a.py", 10, 5), sfile("src/b.py", 10, 5), tfile()], "ok")
        self.check(pr(), [sfile("src/a.py", 10, 4), sfile("src/b.py", 10, 5), tfile()], "src_lines")

    def test_O1_test_file_lines_do_not_count_as_src_lines(self):
        big_test = sfile("tests/test_big.py", 900)
        self.check(pr(), [sfile("src/a.py", 20), sfile("src/b.py", 20), big_test], "ok")

    def test_O1_C3_bot_author(self):
        files = [sfile("src/a.py", 20), sfile("src/b.py", 20), tfile()]
        self.check(pr(login="dependabot[bot]"), files, "bot_author")
        self.check(pr(login="bot-lover"), files, "ok")

    def test_O1_title_excluded_by_cfg_regex(self):
        files = [sfile("src/a.py", 20), sfile("src/b.py", 20), tfile()]
        self.check(pr(title="Bump lodash from 1 to 2"), files, "title_excluded")
        self.check(pr(title="Revert \"Add clamp\""), files, "title_excluded")
        self.check(pr(title="Add the bumper feature"), files, "ok")

    def test_O1_no_tests(self):
        self.check(pr(), [sfile("src/a.py", 20), sfile("src/b.py", 20)], "no_tests")

    def test_O1_src_files_single_file_without_public_symbol(self):
        patch = "@@ -1 +1,3 @@\n+def _hidden():\n+    return 1\n+x = 2\n"
        self.check(pr(), [sfile("src/a.py", 40, patch=patch), tfile()], "src_files")

    def test_O1_C4_single_rust_file_with_added_pub_fn_is_ok(self):
        patch = "@@ -1 +1,4 @@\n+pub fn new_api() -> i32 {\n+    1\n+}\n+\n"
        files = [sfile("src/lib.rs", 40, patch=patch), sfile("tests/api.rs", 5)]
        self.check(pr(language="rust"), files, "ok")

    def test_O1_single_rust_file_with_private_fn_only_is_src_files(self):
        patch = "@@ -1 +1,4 @@\n+fn private_api() -> i32 {\n+    1\n+}\n+\n"
        files = [sfile("src/lib.rs", 40, patch=patch), sfile("tests/api.rs", 5)]
        self.check(pr(language="rust"), files, "src_files")

    def test_O1_C5_harness_file_at_repo_root(self):
        files = [sfile("src/a.py", 20), sfile("src/b.py", 20), tfile(), sfile("CLAUDE.md", 3)]
        self.check(pr(), files, "harness_files")

    def test_O1_binary_file(self):
        files = [sfile("src/a.py", 20), sfile("src/b.py", 20), tfile(),
                 {"filename": "assets/logo.png", "status": "added", "additions": 5, "deletions": 0}]
        self.check(pr(), files, "binary")


class FakeGh:
    """Serves the F6 endpoints. repos: full_name -> list of PR numbers (all eligible unless in `bots`)."""

    def __init__(self, repos, *, license="MIT", bots=(), bodies=None, issues=None):
        self.repos = repos
        self.license = license
        self.bots = set(bots)
        self.bodies = bodies or {}
        self.issues = issues or {}
        self.calls = []

    def __call__(self, args):
        assert len(args) == 1, args
        ep = urllib.parse.unquote(args[0]).replace(" ", "+")
        self.calls.append(ep)
        if ep.startswith("search/repositories"):
            page = int(re.search(r"&page=(\d+)", ep).group(1))
            if page > 1:
                return {"items": []}
            lang = re.search(r"language:(\w+)", ep).group(1)
            return {"total_count": len(self.repos), "items": [{"full_name": r, "stargazers_count": 500, "archived": False, "fork": False,
                               "license": {"spdx_id": self.license}, "language": lang.capitalize()}
                              for r in sorted(self.repos)]}
        if ep.startswith("search/issues"):
            repo = re.search(r"repo:([^+&]+)", ep).group(1)
            return {"items": [{"number": n} for n in self.repos.get(repo, [])]}
        m = re.match(r"repos/([^/]+/[^/]+)/pulls/(\d+)/files", ep)
        if m:
            return [sfile("src/a%d.py" % i, 20) for i in range(2)] + [tfile()]
        m = re.match(r"repos/([^/]+/[^/]+)/pulls/(\d+)$", ep)
        if m:
            n = int(m.group(2))
            login = "dependabot[bot]" if n in self.bots else "alice"
            return {"number": n, "title": "Add feature %d" % n, "body": self.bodies.get(n, "b"),
                    "merged_at": "2026-08-02T10:00:00Z", "merge_commit_sha": "%040x" % n,
                    "user": {"login": login}, "base": {"sha": "%040x" % (n + 1000)}}
        m = re.match(r"repos/([^/]+/[^/]+)/issues/(\d+)", ep)
        if m:
            return {"number": int(m.group(2)), "body": self.issues.get(int(m.group(2)), "issue body")}
        return {}

    def queries(self, prefix):
        return [c for c in self.calls if c.startswith(prefix)]


class Search(TmpCase):
    def many(self, repos=20, prs=4):
        return {"own/repo%02d" % i: [100 + i * 10 + j for j in range(prs)] for i in range(repos)}

    def test_O2_caps_per_repo_stops_at_target_and_sorts(self):
        rows = mine.search("python", self.cfg(), gh_fn=FakeGh(self.many()))
        self.assertEqual(len(rows), 40)
        per_repo = {}
        for row in rows:
            per_repo[row["repo"]] = per_repo.get(row["repo"], 0) + 1
        self.assertLessEqual(max(per_repo.values()), 3)
        self.assertEqual([(r["repo"], r["pr"]) for r in rows], sorted((r["repo"], r["pr"]) for r in rows))

    def test_O2_single_repo_with_ten_prs_yields_three_rows(self):
        rows = mine.search("python", self.cfg(), gh_fn=FakeGh({"own/solo": list(range(1, 11))}))
        self.assertEqual(len(rows), 3)

    def test_O2_target_per_language_from_cfg_is_honored(self):
        cfg = self.cfg(mining={"target_per_language": 5})
        self.assertEqual(len(mine.search("python", cfg, gh_fn=FakeGh(self.many()))), 5)

    def test_O2_per_repo_max_from_cfg_is_honored(self):
        cfg = self.cfg(mining={"per_repo_max": 1})
        rows = mine.search("python", cfg, gh_fn=FakeGh({"own/solo": list(range(1, 11))}))
        self.assertEqual(len(rows), 1)

    def test_O2_rows_hold_required_fields(self):
        rows = mine.search("python", self.cfg(), gh_fn=FakeGh({"own/solo": [5]}, bodies={5: "Fixes #12 now"},
                                                            issues={12: "the linked issue text"}))
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual((row["repo"], row["pr"], row["language"]), ("own/solo", 5, "python"))
        self.assertEqual(row["merge_sha"], "%040x" % 5)
        self.assertEqual(row["base_sha"], "%040x" % 1005)
        self.assertEqual(row["title"], "Add feature 5")
        self.assertEqual(row["merged_at"], "2026-08-02T10:00:00Z")
        self.assertEqual(row["body"], "Fixes #12 now")
        self.assertIn("the linked issue text", json.dumps(row))
        for needles in (("src", "line"), ("test", "line")):
            self.assertIsNot(find(row, *needles), MISSING, needles)

    def test_O2_linked_issues_only_after_closing_keywords(self):
        gh = FakeGh({"own/solo": [5]}, bodies={5: "See #7. closes #8, RESOLVES #9"}, issues={7: "i7", 8: "i8", 9: "i9"})
        mine.search("python", self.cfg(), gh_fn=gh)
        fetched = gh.queries("repos/own/solo/issues/")
        self.assertEqual(sorted(fetched), ["repos/own/solo/issues/8", "repos/own/solo/issues/9"])

    def test_O2_candidates_file_matches_returned_rows(self):
        cfg = self.cfg()
        rows = mine.search("python", cfg, gh_fn=FakeGh({"own/b": [3, 1], "own/a": [2]}))
        path = Path(cfg["data_dir"]) / "tasks" / "python" / "candidates.jsonl"
        written = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        self.assertEqual(written, rows)
        self.assertEqual([(r["repo"], r["pr"]) for r in written], [("own/a", 2), ("own/b", 1), ("own/b", 3)])

    def test_O2_F6_repository_and_issue_queries(self):
        gh = FakeGh({"own/solo": [1]})
        mine.search("python", self.cfg(), gh_fn=gh)
        repo_q = gh.queries("search/repositories")[0]
        self.assertEqual(repo_q, "search/repositories?q=language:python+stars:>=200+fork:false+archived:false"
                                 "&sort=stars&order=desc&per_page=100&page=1")
        issue_q = gh.queries("search/issues")[0]
        self.assertEqual(issue_q, "search/issues?q=repo:own/solo+is:pr+is:merged+merged:>=2026-07-01&per_page=100")
        self.assertIn("repos/own/solo/pulls/1", gh.calls)
        self.assertIn("repos/own/solo/pulls/1/files?per_page=100", gh.calls)

    def test_O2_typescript_search_also_asks_for_javascript(self):
        gh = FakeGh({"own/solo": [1]})
        mine.search("typescript", self.cfg(), gh_fn=gh)
        langs = [re.search(r"language:(\w+)", q).group(1) for q in gh.queries("search/repositories")
                 if "page=1" in q]
        self.assertEqual(sorted(langs), ["javascript", "typescript"])

    def test_O2_python_search_does_not_ask_for_javascript(self):
        gh = FakeGh({"own/solo": [1]})
        mine.search("python", self.cfg(), gh_fn=gh)
        self.assertNotIn("javascript", " ".join(gh.calls))

    def test_O2_repo_license_outside_cfg_is_skipped_without_issue_search(self):
        gh = FakeGh({"own/solo": [1]}, license="GPL-3.0")
        rows = mine.search("python", self.cfg(mining={"licenses": ["MIT", "Apache-2.0"]}), gh_fn=gh)
        self.assertEqual(rows, [])
        self.assertEqual(gh.queries("search/issues"), [])

    def test_O2_ineligible_prs_are_not_candidates(self):
        gh = FakeGh({"own/solo": [1, 2, 3]}, bots=[2])
        rows = mine.search("python", self.cfg(), gh_fn=gh)
        self.assertEqual([r["pr"] for r in rows], [1, 3])

    def test_O2_rate_limit_dict_raises_rate_limited(self):
        def gh(args):
            return {"message": "API rate limit exceeded for user ID 1.", "documentation_url": "x"}
        with self.assertRaises(mine.RateLimited):
            mine.search("python", self.cfg(), gh_fn=gh)

    def test_O2_rate_limited_from_gh_fn_propagates_and_keeps_rows_so_far(self):
        inner = FakeGh({"own/a": [1], "own/b": [2]})

        def gh(args):
            if args[0].startswith("search/issues") and "own/b" in args[0]:
                raise mine.RateLimited("reset in 60 s")
            return inner(args)
        cfg = self.cfg()
        with self.assertRaises(mine.RateLimited):
            mine.search("python", cfg, gh_fn=gh)
        path = Path(cfg["data_dir"]) / "tasks" / "python" / "candidates.jsonl"
        self.assertIn("own/a", path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()


class SearchPageCap(unittest.TestCase):
    def test_O2_repository_search_never_requests_past_the_1000_result_cap(self):
        calls = []

        def gh(args):
            ep = urllib.parse.unquote(args[0])
            calls.append(ep)
            if ep.startswith("search/repositories"):
                page = int(re.search(r"&page=(\d+)", ep).group(1))
                if page > 10:
                    raise AssertionError("HTTP 422: Only the first 1000 search results are available")
                return {"items": [{"full_name": f"o/r{page}-{i}", "stargazers_count": 500, "archived": False, "fork": False,
                                   "license": {"spdx_id": "NOASSERTION"}, "language": "Python"} for i in range(100)]}
            return {"items": []}

        with tempfile.TemporaryDirectory() as d:
            mine.search("python", {**spec_cfg(), "data_dir": d}, gh_fn=gh)
        pages = [int(re.search(r"&page=(\d+)", c).group(1)) for c in calls if c.startswith("search/repositories")]
        self.assertEqual(max(pages), 10)

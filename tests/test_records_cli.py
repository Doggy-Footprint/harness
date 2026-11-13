import os
import re
import subprocess
import sys
import unittest
from pathlib import Path

from test_installer import InstallerTestCase, run_git
from test_synced_blocks import (ID, ID2, STUB_HASH, SyncedCase, block_of, r1, r2, ref_hash, sync_lines_a, sync_lines_b, tag,
                                end, tracking_text)

A = "1111111111111111-alpha.md"
B = "2222222222222222-bravo.md"
C = "3333333333333333-charlie.md"
STALE_HEADER = "# Stale Index Archive\n<!-- harness:stale-index-archive -->\n"
DEFAULT_REASON = "Refreshed count and code_hash."


def index_block(name):
    return f"File: {name}\nSummary: {name} summary\nRelated Files: none\nRelated Symbols: none\n"


def clean_env():
    return {k: v for k, v in os.environ.items() if k not in ("CLAUDE_CODE_SESSION_ID", "CLAUDE_SESSION_ID")}


def run_records(repo, *args):
    return subprocess.run([sys.executable, str(repo / ".harness" / "bin" / "records.py"), *args],
                          capture_output=True, text=True, cwd=repo, env=clean_env())


def tree(repo):
    files = {}
    for path in repo.rglob("*"):
        parts = path.relative_to(repo).parts
        if ".git" in parts or "__pycache__" in parts or parts[:2] == (".harness", "sessions"):
            continue
        files[path.relative_to(repo).as_posix()] = path.read_bytes() if path.is_file() else None
    status = run_git(repo, "status", "--porcelain").stdout
    cached = run_git(repo, "diff", "--cached", "--name-status").stdout
    return files, status, cached


class TestSyncedRefresh(SyncedCase):
    def tracking_path(self, repo, ident=ID):
        return repo / "agent-docs" / "synced-comments" / f"{ident}.md"

    def refresh(self, repo, *args, ident=ID):
        return run_records(repo, "synced-refresh", ident, *args)

    def assert_refused(self, repo):
        before = tree(repo)
        result = self.refresh(repo)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertTrue(result.stderr.strip(), "refusal names its reason on stderr")
        self.assertNotIn("Traceback", result.stdout + result.stderr)
        self.assertEqual(tree(repo), before)

    def assert_log_tail(self, text, version, reason):
        self.assertTrue(text.rstrip("\n").endswith(f"## v{version} Log\n- {reason}"), text)
        return text[:text.rindex(f"## v{version} Log")].rstrip("\n")

    def test_missing_tracking_file_is_refused_without_changes(self):
        repo = self.basic()
        self.tracking_path(repo).unlink()
        self.assert_refused(repo)

    def test_obsolete_tracking_file_is_refused_without_changes(self):
        repo = self.basic()
        path = self.tracking_path(repo)
        path.write_text(tracking_text(1, 2, STUB_HASH, extra="obsolete: true\n"))
        self.assert_refused(repo)

    def test_structural_error_in_a_block_is_refused_without_changes(self):
        repo = self.basic()
        self.write_lines(repo, "a.py", ["x = 1", tag(ID), "y = 2"])
        self.assert_refused(repo)

    def test_end_without_tag_is_refused_without_changes(self):
        repo = self.basic()
        self.write_lines(repo, "a.py", sync_lines_a() + [end(ID)])
        self.assert_refused(repo)

    def test_unchanged_count_and_hash_prints_r1_and_writes_nothing(self):
        repo = self.basic()
        before = tree(repo)
        result = self.refresh(repo)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(r1(ID), result.stdout)
        self.assertNotIn("version", result.stdout.replace(r1(ID), ""))
        self.assertEqual(tree(repo), before)

    def test_changed_hash_bumps_version_rewrites_every_tag_logs_and_leaves_the_check_passing(self):
        repo = self.basic()
        a = sync_lines_a()
        a[1] = f"# synced id: {ID},  version: 1,  count: 2"
        a[3] = "    return 100"
        self.write_lines(repo, "a.py", a)
        original_b = sync_lines_b()
        new_hash = ref_hash([block_of("a.py", a, ID), block_of("b.py", original_b, ID)])
        result = self.refresh(repo)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(r2(ID, 1, 2, 2, new_hash, 2), result.stdout)
        expected_a = sync_lines_a(version=2)
        expected_a[3] = "    return 100"
        self.assertEqual((repo / "a.py").read_text(), "\n".join(expected_a) + "\n")
        self.assertEqual((repo / "b.py").read_text(), "\n".join(sync_lines_b(version=2)) + "\n")
        text = self.tracking_path(repo).read_text()
        before_log = self.assert_log_tail(text, 2, DEFAULT_REASON)
        self.assertEqual(before_log, tracking_text(2, 2, new_hash).rstrip("\n"))
        self.assert_passes(repo)

    def test_changed_count_alone_updates_count_and_keeps_the_hash(self):
        repo = self.basic()
        path = self.tracking_path(repo)
        path.write_text(path.read_text().replace("count: 2", "count: 3", 1))
        old_hash = re.search(r"code_hash: (\S+)", path.read_text()).group(1)
        result = self.refresh(repo)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(r2(ID, 1, 2, 2, old_hash, 2), result.stdout)
        before_log = self.assert_log_tail(path.read_text(), 2, DEFAULT_REASON)
        self.assertEqual(before_log, tracking_text(2, 2, old_hash).rstrip("\n"))
        self.assert_passes(repo)

    def test_an_added_tag_changes_count_and_hash_and_updates_all_three_tags(self):
        repo = self.basic()
        c = ["head = 0", tag(ID), "def k():", "    return 7", end(ID), "foot = 0"]
        self.write_lines(repo, "c.py", c)
        run_git(repo, "add", "c.py")
        new_hash = ref_hash([block_of("a.py", sync_lines_a(), ID), block_of("b.py", sync_lines_b(), ID), block_of("c.py", c, ID)])
        result = self.refresh(repo)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(r2(ID, 1, 2, 3, new_hash, 3), result.stdout)
        for rel in ("a.py", "b.py", "c.py"):
            with self.subTest(file=rel):
                self.assertIn(f"# synced id: {ID}, version: 2, count: 3", (repo / rel).read_text().splitlines())
        self.assert_passes(repo)

    def test_reason_option_replaces_the_default_log_line(self):
        repo = self.basic()
        a = sync_lines_a()
        a[3] = "    return 5"
        self.write_lines(repo, "a.py", a)
        result = self.refresh(repo, "--reason", "Changed the return value.")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        text = self.tracking_path(repo).read_text()
        self.assert_log_tail(text, 2, "Changed the return value.")
        self.assertNotIn(DEFAULT_REASON, text)

    def test_a_second_refresh_continues_from_the_frontmatter_version(self):
        repo = self.basic()
        for step, value in ((2, "5"), (3, "6")):
            a = sync_lines_a(version=step - 1)
            a[3] = f"    return {value}"
            self.write_lines(repo, "a.py", a)
            new_hash = ref_hash([block_of("a.py", a, ID), block_of("b.py", sync_lines_b(version=step - 1), ID)])
            result = self.refresh(repo)
            self.assertIn(r2(ID, step - 1, step, 2, new_hash, 2), result.stdout, result.stdout + result.stderr)
        text = self.tracking_path(repo).read_text()
        self.assertIn("## v2 Log\n- " + DEFAULT_REASON, text)
        self.assertTrue(text.rstrip("\n").endswith("## v3 Log\n- " + DEFAULT_REASON))
        self.assert_passes(repo)

    def test_refresh_rewrites_only_the_tags_of_its_own_id(self):
        repo = self.installed()
        a = ["pre = 0", tag(ID), "x1 = 1", tag(ID2), "y1 = 1", end(ID2), "x2 = 2", end(ID), "post = 0"]
        b = ["pre = 0", tag(ID), "x1 = 10", tag(ID2), "y1 = 10", end(ID2), "x2 = 20", end(ID), "post = 0"]
        self.write_lines(repo, "a.py", a)
        self.write_lines(repo, "b.py", b)
        outer = [("a.py", 2, ["x1 = 1", "y1 = 1", "x2 = 2"]), ("b.py", 2, ["x1 = 10", "y1 = 10", "x2 = 20"])]
        inner = [("a.py", 4, ["y1 = 1"]), ("b.py", 4, ["y1 = 10"])]
        self.write_tracking(repo, ID, tracking_text(1, 2, ref_hash(outer)))
        self.write_tracking(repo, ID2, tracking_text(1, 2, ref_hash(inner)))
        a[4] = "y1 = 99"
        self.write_lines(repo, "a.py", a)
        self.stage(repo, *[str(self.tracking_path(repo, i).relative_to(repo)) for i in (ID, ID2)])
        result = self.refresh(repo, ident=ID2)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        lines = (repo / "a.py").read_text().splitlines()
        self.assertEqual(lines[1], tag(ID))
        self.assertEqual(lines[3], tag(ID2, 2, 2))
        self.assertEqual(self.tracking_path(repo, ID).read_text(), tracking_text(1, 2, ref_hash(outer)))


class StaleCase(InstallerTestCase):
    def stale_repo(self, names=(A, B, C), header=STALE_HEADER, stale_dir=True, directory="agent-docs/notes"):
        repo = self.installed_copy("--no-ci")[0]
        folder = repo / directory
        folder.mkdir(parents=True, exist_ok=True)
        for name in names:
            (folder / name).write_text(f"# {name}\n")
        (folder / "index.md").write_text("---\n".join(index_block(n) for n in names))
        if header is not None:
            (folder / "stale.md").write_text(header)
        if stale_dir:
            (folder / "stale").mkdir(exist_ok=True)
            (folder / "stale" / ".gitkeep").write_text("")
        run_git(repo, "add", "-A")
        run_git(repo, "commit", "-q", "--no-verify", "-m", "base")
        return repo, folder

    def stale(self, repo, rel):
        return run_records(repo, "stale", rel)

    def verify(self, repo):
        run_git(repo, "add", "-A")
        result = subprocess.run([sys.executable, str(repo / ".harness" / "git" / "verify_rules.py")],
                                capture_output=True, text=True, cwd=repo, env=clean_env())
        return result, result.stdout + result.stderr

    def assert_refused(self, repo, rel):
        before = tree(repo)
        result = self.stale(repo, rel)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertTrue(result.stderr.strip(), "refusal names its reason on stderr")
        self.assertNotIn("Traceback", result.stdout + result.stderr)
        self.assertEqual(tree(repo), before)


class TestStale(StaleCase):
    def assert_marked(self, repo, folder, name, index_after, stale_after):
        result = self.stale(repo, (folder / name).relative_to(repo).as_posix())
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn("Traceback", result.stdout + result.stderr)
        self.assertEqual((folder / "index.md").read_text(), index_after)
        self.assertEqual((folder / "stale.md").read_text(), stale_after)
        self.assertFalse((folder / name).exists())
        self.assertEqual((folder / "stale" / name).read_text(), f"# {name}\n")
        verify, text = self.verify(repo)
        self.assertEqual(verify.returncode, 0, text)

    def test_middle_entry_is_removed_with_one_separator_and_appended_after_a_separator(self):
        repo, folder = self.stale_repo()
        self.assert_marked(repo, folder, B, index_block(A) + "---\n" + index_block(C),
                           STALE_HEADER + "---\n" + index_block(B))

    def test_first_entry_is_removed_with_the_separator_after_it(self):
        repo, folder = self.stale_repo()
        self.assert_marked(repo, folder, A, index_block(B) + "---\n" + index_block(C),
                           STALE_HEADER + "---\n" + index_block(A))

    def test_last_entry_is_removed_with_the_separator_before_it(self):
        repo, folder = self.stale_repo()
        self.assert_marked(repo, folder, C, index_block(A) + "---\n" + index_block(B),
                           STALE_HEADER + "---\n" + index_block(C))

    def test_only_entry_leaves_an_empty_index_without_separators(self):
        repo, folder = self.stale_repo(names=(A,))
        result = self.stale(repo, f"agent-docs/notes/{A}")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual((folder / "index.md").read_text().strip(), "")
        self.assertNotIn("---", (folder / "index.md").read_text())
        self.assertEqual((folder / "stale.md").read_text(), STALE_HEADER + "---\n" + index_block(A))
        self.assertTrue((folder / "stale" / A).is_file())

    def test_empty_stale_md_gets_the_block_without_a_leading_separator(self):
        repo, folder = self.stale_repo(header="")
        self.assert_marked(repo, folder, B, index_block(A) + "---\n" + index_block(C), index_block(B))

    def test_whitespace_only_stale_md_gets_no_leading_separator(self):
        repo, folder = self.stale_repo(header="\n\n")
        result = self.stale(repo, f"agent-docs/notes/{B}")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        text = (folder / "stale.md").read_text()
        self.assertTrue(text.endswith(index_block(B)), text)
        self.assertNotIn("---", text)

    def test_missing_stale_md_and_stale_directory_are_created(self):
        repo, folder = self.stale_repo(header=None, stale_dir=False)
        self.assertFalse((folder / "stale.md").exists())
        self.assertFalse((folder / "stale").exists())
        result = self.stale(repo, f"agent-docs/notes/{B}")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual((folder / "stale.md").read_text(), index_block(B))
        self.assertEqual((folder / "stale" / B).read_text(), f"# {B}\n")
        self.assertEqual((folder / "index.md").read_text(), index_block(A) + "---\n" + index_block(C))

    def test_second_call_appends_after_a_separator_and_keeps_the_first_block(self):
        repo, folder = self.stale_repo()
        self.assertEqual(self.stale(repo, f"agent-docs/notes/{B}").returncode, 0)
        self.assertEqual(self.stale(repo, f"agent-docs/notes/{A}").returncode, 0)
        self.assertEqual((folder / "stale.md").read_text(), STALE_HEADER + "---\n" + index_block(B) + "---\n" + index_block(A))
        self.assertEqual((folder / "index.md").read_text(), index_block(C))

    def test_tracked_file_moves_with_git_mv_as_a_staged_rename(self):
        repo, folder = self.stale_repo()
        self.assertEqual(self.stale(repo, f"agent-docs/notes/{B}").returncode, 0)
        status = run_git(repo, "diff", "--cached", "--name-status").stdout.splitlines()
        wanted = rf"R\d*\tagent-docs/notes/{re.escape(B)}\tagent-docs/notes/stale/{re.escape(B)}"
        self.assertTrue(any(re.fullmatch(wanted, line) for line in status), status)

    def test_untracked_file_is_renamed_without_touching_the_git_index(self):
        repo, folder = self.stale_repo()
        (folder / B).unlink()
        run_git(repo, "add", "-A")
        run_git(repo, "commit", "-q", "--no-verify", "-m", "drop tracked copy")
        (folder / B).write_text(f"# {B}\n")
        self.assertEqual(run_git(repo, "ls-files", "--", f"agent-docs/notes/{B}").stdout, "")
        result = self.stale(repo, f"agent-docs/notes/{B}")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual((folder / "stale" / B).read_text(), f"# {B}\n")
        self.assertFalse((folder / B).exists())
        self.assertEqual(run_git(repo, "ls-files", "--", f"agent-docs/notes/{B}", f"agent-docs/notes/stale/{B}").stdout, "")

    def test_todos_directory_is_managed_like_any_other(self):
        repo, folder = self.stale_repo(directory="agent-docs/todos")
        result = self.stale(repo, f"agent-docs/todos/{B}")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual((folder / "index.md").read_text(), index_block(A) + "---\n" + index_block(C))
        self.assertTrue((folder / "stale" / B).is_file())


class TestStaleRefusals(StaleCase):
    def test_file_without_an_index_entry_is_refused(self):
        repo, folder = self.stale_repo(names=(A, B))
        (folder / C).write_text(f"# {C}\n")
        self.assert_refused(repo, f"agent-docs/notes/{C}")

    def test_file_with_two_index_entries_is_refused(self):
        repo, folder = self.stale_repo()
        (folder / "index.md").write_text("---\n".join(index_block(n) for n in (A, B, B, C)))
        self.assert_refused(repo, f"agent-docs/notes/{B}")

    def test_index_entry_whose_file_value_only_extends_the_name_is_refused(self):
        repo, folder = self.stale_repo()
        near = f"File: {B}x\nSummary: s\nRelated Files: none\nRelated Symbols: none\n"
        (folder / "index.md").write_text("---\n".join([index_block(A), near, index_block(C)]))
        self.assert_refused(repo, f"agent-docs/notes/{B}")

    def test_index_entry_naming_the_file_only_in_its_summary_is_refused(self):
        repo, folder = self.stale_repo()
        near = f"File: {C}\nSummary: replaces {B}\nRelated Files: none\nRelated Symbols: none\n"
        (folder / "index.md").write_text("---\n".join([index_block(A), near]))
        self.assert_refused(repo, f"agent-docs/notes/{B}")

    def test_existing_destination_is_refused(self):
        repo, folder = self.stale_repo()
        (folder / "stale" / B).write_text("# already archived\n")
        self.assert_refused(repo, f"agent-docs/notes/{B}")

    def test_path_already_inside_stale_is_refused(self):
        repo, folder = self.stale_repo()
        (folder / "stale" / B).write_text(f"# {B}\n")
        (folder / B).unlink()
        self.assert_refused(repo, f"agent-docs/notes/stale/{B}")

    def test_path_outside_the_docs_root_is_refused_even_beside_an_index(self):
        repo, _ = self.stale_repo()
        outside = repo / "src"
        outside.mkdir(exist_ok=True)
        (outside / "index.md").write_text(index_block(A))
        (outside / A).write_text("# A\n")
        self.assert_refused(repo, f"src/{A}")

    def test_exempt_directories_are_refused(self):
        for directory in ("specs", "spec-logs"):
            with self.subTest(directory=directory):
                repo, _ = self.stale_repo()
                exempt = repo / "agent-docs" / directory
                exempt.mkdir(parents=True, exist_ok=True)
                (exempt / "index.md").write_text(index_block(A))
                (exempt / A).write_text("# A\n")
                self.assert_refused(repo, f"agent-docs/{directory}/{A}")

    def test_directory_without_an_index_is_refused(self):
        repo, folder = self.stale_repo()
        nested = folder / "deep"
        nested.mkdir()
        (nested / B).write_text(f"# {B}\n")
        self.assert_refused(repo, f"agent-docs/notes/deep/{B}")

    def test_name_that_is_not_hex_dash_kebab_is_refused(self):
        repo, folder = self.stale_repo(names=(A, B, "readme.md"))
        (folder / "readme.md").write_text("# readme\n")
        self.assert_refused(repo, "agent-docs/notes/readme.md")

    def test_index_itself_is_refused(self):
        repo, _ = self.stale_repo()
        self.assert_refused(repo, "agent-docs/notes/index.md")

    def test_missing_path_is_refused(self):
        repo, _ = self.stale_repo()
        self.assert_refused(repo, f"agent-docs/notes/{'9' * 16}-ghost.md")


if __name__ == "__main__":
    unittest.main()

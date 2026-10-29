import importlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from test_installer import REPO_ROOT, InstallerTestCase, run_git, run_installer

EM = "—"
SUFFIXES = [".corp", ".internal", ".local", ".lan", ".intranet"]
SESSION_ENV = ("CLAUDE_CODE_SESSION_ID", "CLAUDE_SESSION_ID")
NAME0 = "0000000000000000-zeroth-task.md"
NAME1 = "1111111111111111-first-task.md"
NAME2 = "2222222222222222-second-task.md"
SHA0 = "0" * 40
RECORD_MARKER = "RECORD-ONLY-MARKER-7431"


def lev(a, b):
    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        current = [i]
        for j, cb in enumerate(b, 1):
            current.append(min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (ca != cb)))
        previous = current
    return previous[-1]


def load_progress():
    lib = str(REPO_ROOT / "harness" / "lib")
    if lib not in sys.path:
        sys.path.insert(0, lib)
    return importlib.import_module("progress")


def entry_lines(items):
    lines = []
    for text, commit, files in items:
        lines += [f"- {text}", f"  - commit: {commit}; files: {files}"]
    return lines


def build(session="sessa", before="none", previous="none", branch="main", stamp=None, state=(),
          next_step=(), constraints=(), verify=(), dead_ends=(), related=(), none_bullet=None,
          changes="- edited the parser", user_requests="", title="Sample task", trailer=""):
    lines = ["---"]
    if session is not None:
        lines.append(f"session: {session}")
    if before is not None:
        lines.append(f"before: {before}")
    lines += [f"previous: {previous}", f"branch: {branch}"]
    if stamp:
        lines.append(f"commit: {stamp}")
    lines += ["---", "", f"# {title}", "", "## Next Session", ""]

    def section(heading, body):
        lines.extend([f"### {heading}", *body, ""])

    section("State", entry_lines(state))
    section("Next Step", [f"- none: {none_bullet}"] if none_bullet else entry_lines(next_step))
    quotes = []
    for quote, source in constraints:
        quotes += [f'- "{quote}"', f"  - source: {source}"]
    section("Constraints", quotes)
    section("Verify", entry_lines(verify))
    section("Dead Ends", entry_lines(dead_ends))
    section("Related", entry_lines(related))
    lines += ["## Record", ""]
    section("Changes", [changes])
    section("Commands", ["- ran the tests"])
    section("Failed Attempts", ["| attempt | failure evidence | cause |", "| --- | --- | --- |"])
    section("Sources", ["- none"])
    if user_requests is not None:
        lines.append("### User Requests")
        if user_requests:
            lines.append(user_requests)
    return "\n".join(lines) + "\n" + trailer


def frontmatter(path):
    fields = {}
    lines = Path(path).read_text().split("\n")
    assert lines[0] == "---", lines[:3]
    for line in lines[1:]:
        if line == "---":
            break
        key, _, value = line.partition(":")
        fields[key.strip()] = value.strip()
    return fields


def split_requests(text):
    match = re.search(r"^### User Requests[ \t]*\n", text, re.M)
    if not match:
        return text, None, ""
    rest = text[match.end():]
    nxt = re.search(r"^#{1,3} ", rest, re.M)
    body = rest[:nxt.start()] if nxt else rest
    after = rest[nxt.start():] if nxt else ""
    return text[:match.start()], [line for line in body.splitlines() if line.strip()], after


class ProgressCase(InstallerTestCase):
    def new_repo(self):
        repo = self.make_repo()
        result = run_installer("install", str(repo), "--no-ci")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        (repo / "src").mkdir()
        (repo / "src" / "a.py").write_text("a = 1\n")
        (repo / "src" / "b.py").write_text("b = 1\n")
        run_git(repo, "add", "-A")
        self.commit(repo, "base")
        return repo

    def commit(self, repo, message):
        run_git(repo, "commit", "-q", "--no-verify", "--allow-empty", "-m", message)
        return self.head(repo)

    def head(self, repo):
        return run_git(repo, "rev-parse", "HEAD").stdout.strip()

    def branch(self, repo):
        return run_git(repo, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()

    def touch_commit(self, repo, rel, message=None):
        path = repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a") as handle:
            handle.write(f"# {message or rel}\n")
        run_git(repo, "add", "--", rel)
        return self.commit(repo, message or f"touch {rel}")

    def env(self, **extra):
        env = {k: v for k, v in os.environ.items() if k not in SESSION_ENV}
        env.update(extra)
        return env

    def put(self, repo, name, text, directory="progress"):
        path = repo / "agent-docs" / directory / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        return path

    def rel(self, repo, path):
        return path.relative_to(repo).as_posix()

    def hook(self, repo, payload, env=None):
        payload = dict(payload)
        payload.setdefault("cwd", str(repo))
        return subprocess.run(
            [sys.executable, str(repo / ".harness" / "hooks" / "progress_hook.py")],
            input=json.dumps(payload), capture_output=True, text=True, cwd=repo,
            env=env if env is not None else self.env(),
        )

    def start(self, repo, sid="sessa", **kw):
        return self.hook(repo, {"hook_event_name": "SessionStart", "session_id": sid, "source": "startup"}, **kw)

    def prompt(self, repo, text, sid="sessa", **kw):
        return self.hook(repo, {"hook_event_name": "UserPromptSubmit", "session_id": sid, "prompt": text}, **kw)

    def post(self, repo, path, sid="sessa", tool="Write", **kw):
        return self.hook(repo, {"hook_event_name": "PostToolUse", "session_id": sid, "tool_name": tool,
                                "tool_input": {"file_path": str(path)}}, **kw)

    def stop(self, repo, sid="sessa", active=False, **kw):
        return self.hook(repo, {"hook_event_name": "Stop", "session_id": sid, "stop_hook_active": active}, **kw)

    def precompact(self, repo, sid="sessa", **kw):
        return self.hook(repo, {"hook_event_name": "PreCompact", "session_id": sid}, **kw)

    def cli(self, repo, *args, session_env=None):
        env = self.env(**({"CLAUDE_CODE_SESSION_ID": session_env} if session_env else {}))
        return subprocess.run(
            [sys.executable, str(repo / ".harness" / "bin" / "progress.py"), *args],
            capture_output=True, text=True, cwd=repo, env=env,
        )

    def show(self, repo, *args, **kw):
        return self.cli(repo, "show", *args, **kw)

    def check(self, repo, path):
        return self.cli(repo, "check", path)

    def sessions_dir(self, repo):
        return repo / ".harness" / "sessions"

    def state_path(self, repo, sid="sessa"):
        return self.sessions_dir(repo) / f"progress-{sid}.json"

    def state(self, repo, sid="sessa"):
        return json.loads(self.state_path(repo, sid).read_text())

    def add_marker(self, repo, name):
        directory = self.sessions_dir(repo) / ".running"
        directory.mkdir(parents=True, exist_ok=True)
        (directory / str(name)).write_text("")

    def dead_pid(self):
        proc = subprocess.Popen([sys.executable, "-c", "pass"])
        proc.wait()
        return proc.pid

    def empty_path_dir(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        return tmp.name

    def all_repo_text(self, repo):
        blobs = []
        for path in repo.rglob("*"):
            if path.is_file():
                try:
                    blobs.append((path, path.read_bytes()))
                except OSError:
                    pass
        return blobs


def out(result):
    return result.stdout + result.stderr


class TestRotation(ProgressCase):

    def test_o1_c1_empty_to_one_keeps_file_fills_session_and_before_none(self):
        repo = self.new_repo()
        self.add_marker(repo, os.getpid())
        path = self.put(repo, NAME1, build(session=None, before="none", stamp=self.head(repo),
                                           next_step=[("alpha wiring", self.head(repo), "none")]))

        result = self.post(repo, path, sid="sessb")

        self.assertEqual(result.returncode, 0, out(result))
        self.assertEqual(result.stderr, "")
        fields = frontmatter(path)
        self.assertEqual(fields["session"], "sessb")
        self.assertEqual(fields["before"], "none")
        self.assertEqual(list((repo / "agent-docs" / "progress").glob("*.md")), [path])
        self.assertFalse(any((repo / "agent-docs" / "progress-logs").glob("*.md")))

    def test_o1_c2_one_to_rotated_moves_old_sets_before_reports_and_keeps_bytes(self):
        for label, new_before, new_session in (("placeholder none", "none", "sessb"),
                                               ("before line absent", None, "sessb"),
                                               ("session missing", "none", None)):
            with self.subTest(case=label):
                repo = self.new_repo()
                self.add_marker(repo, os.getpid())
                self.add_marker(repo, self.dead_pid())
                head = self.head(repo)
                old_text = build(session="sessa", stamp=head, next_step=[("old work item", head, "none")])
                old = self.put(repo, NAME1, old_text)
                new = self.put(repo, NAME2, build(session=new_session, before=new_before, stamp=head,
                                                  next_step=[("new work item", head, "none")]))

                result = self.post(repo, new, sid="sessb")

                logged = repo / "agent-docs" / "progress-logs" / NAME1
                self.assertEqual(logged.read_bytes(), old_text.encode())
                self.assertFalse(old.exists())
                self.assertEqual(list((repo / "agent-docs" / "progress").glob("*.md")), [new])
                self.assertEqual(frontmatter(new)["before"], f"agent-docs/progress-logs/{NAME1}")
                self.assertEqual(frontmatter(new)["session"], "sessb")
                self.assertEqual(result.returncode, 2, out(result))
                self.assertIn(NAME1, result.stderr)
                self.assertNotIn("Traceback", result.stderr)

    def test_o1_c3_same_session_second_file_is_refused_and_nothing_moves(self):
        repo = self.new_repo()
        self.add_marker(repo, os.getpid())
        head = self.head(repo)
        first_text = build(session="sessa", stamp=head, next_step=[("first item", head, "none")])
        first = self.put(repo, NAME1, first_text)
        second = self.put(repo, NAME2, build(session="sessa", stamp=head, next_step=[("second item", head, "none")]))

        result = self.post(repo, second, sid="sessa")

        self.assertEqual(result.returncode, 2, out(result))
        self.assertIn("merge", result.stderr.lower())
        self.assertTrue(NAME1 in result.stderr or NAME2 in result.stderr, result.stderr)
        self.assertEqual(first.read_text(), first_text)
        self.assertTrue(second.is_file())
        self.assertFalse(any((repo / "agent-docs" / "progress-logs").glob("*.md")))
        self.assertEqual(sorted(p.name for p in (repo / "agent-docs" / "progress").glob("*.md")), [NAME1, NAME2])

    def test_o1_c4_live_foreign_marker_refuses_rotation(self):
        repo = self.new_repo()
        self.add_marker(repo, os.getpid())
        self.add_marker(repo, 1)
        head = self.head(repo)
        old_text = build(session="sessa", stamp=head, next_step=[("old work item", head, "none")])
        old = self.put(repo, NAME1, old_text)
        new = self.put(repo, NAME2, build(session="sessb", stamp=head, next_step=[("new item", head, "none")]))

        result = self.post(repo, new, sid="sessb")

        self.assertEqual(result.returncode, 2, out(result))
        self.assertIn("parallel", result.stderr.lower())
        self.assertEqual(old.read_text(), old_text)
        self.assertTrue(new.is_file())
        self.assertFalse(any((repo / "agent-docs" / "progress-logs").glob("*.md")))

    def test_o1_fr7_only_own_and_dead_markers_do_not_block_rotation(self):
        repo = self.new_repo()
        self.add_marker(repo, os.getpid())
        self.add_marker(repo, self.dead_pid())
        head = self.head(repo)
        self.put(repo, NAME1, build(session="sessa", stamp=head, next_step=[("old work item", head, "none")]))
        new = self.put(repo, NAME2, build(session="sessb", stamp=head, next_step=[("new item", head, "none")]))

        self.post(repo, new, sid="sessb")

        self.assertTrue((repo / "agent-docs" / "progress-logs" / NAME1).is_file())

    def test_o1_errors_destination_exists_refuses_and_keeps_both(self):
        repo = self.new_repo()
        self.add_marker(repo, os.getpid())
        head = self.head(repo)
        old_text = build(session="sessa", stamp=head, next_step=[("old work item", head, "none")])
        old = self.put(repo, NAME1, old_text)
        existing = self.put(repo, NAME1, "an earlier log with the same name\n", directory="progress-logs")
        new = self.put(repo, NAME2, build(session="sessb", stamp=head, next_step=[("new item", head, "none")]))

        result = self.post(repo, new, sid="sessb")

        self.assertEqual(result.returncode, 2, out(result))
        self.assertIn(f"progress-logs/{NAME1}", result.stderr)
        self.assertEqual(old.read_text(), old_text)
        self.assertEqual(existing.read_text(), "an earlier log with the same name\n")
        self.assertTrue(new.is_file())
        self.assertNotIn("Traceback", result.stderr)


class TestFreshness(ProgressCase):

    def entry_repo(self, commit, files, text="alpha module wiring"):
        repo = self.new_repo()
        path = self.put(repo, NAME1, build(stamp=self.head(repo), next_step=[(text, commit, files)]))
        return repo, path

    def reports(self, repo, path):
        rel = self.rel(repo, path)
        return self.show(repo, rel), self.check(repo, rel)

    def assert_fresh(self, repo, path):
        shown, checked = self.reports(repo, path)
        self.assertEqual(shown.returncode, 0, out(shown))
        self.assertRegex(shown.stdout, r"\bfresh\b")
        self.assertNotIn("stale", shown.stdout)
        self.assertEqual(checked.returncode, 0, out(checked))

    def assert_stale(self, repo, path, reason):
        shown, checked = self.reports(repo, path)
        self.assertEqual(shown.returncode, 0, out(shown))
        self.assertIn(f"stale: {reason}", shown.stdout)
        self.assertEqual(checked.returncode, 1, out(checked))
        self.assertIn("stale", out(checked))

    def test_o2_c5_commit_equals_head_is_fresh(self):
        repo = self.new_repo()
        path = self.put(repo, NAME1, build(stamp=self.head(repo), next_step=[("alpha module wiring", self.head(repo), "src/a.py")]))
        self.assert_fresh(repo, path)

    def test_o2_c6_later_commit_touching_listed_file_is_stale_changed(self):
        repo = self.new_repo()
        base = self.head(repo)
        self.touch_commit(repo, "src/a.py")
        path = self.put(repo, NAME1, build(stamp=self.head(repo), next_step=[("alpha module wiring", base, "src/a.py")]))
        self.assert_stale(repo, path, "changed")

    def test_o2_c6_any_listed_path_counts_not_only_the_first(self):
        repo = self.new_repo()
        base = self.head(repo)
        self.touch_commit(repo, "src/b.py")
        path = self.put(repo, NAME1, build(stamp=self.head(repo), next_step=[("alpha module wiring", base, "src/a.py, src/b.py")]))
        self.assert_stale(repo, path, "changed")

    def test_o2_c7_later_commit_touching_other_file_is_fresh(self):
        repo = self.new_repo()
        base = self.head(repo)
        self.touch_commit(repo, "src/b.py")
        self.touch_commit(repo, "src/c.py")
        path = self.put(repo, NAME1, build(stamp=self.head(repo), next_step=[("alpha module wiring", base, "src/a.py")]))
        self.assert_fresh(repo, path)

    def test_o2_c7_path_that_only_shares_a_prefix_is_not_a_listed_file(self):
        repo = self.new_repo()
        base = self.head(repo)
        self.touch_commit(repo, "src/a.pyc")
        path = self.put(repo, NAME1, build(stamp=self.head(repo), next_step=[("alpha module wiring", base, "src/a.py")]))
        self.assert_fresh(repo, path)

    def test_o2_c7_later_commit_touching_only_the_progress_file_is_fresh(self):
        repo = self.new_repo()
        base = self.head(repo)
        path = self.put(repo, NAME1, build(stamp=base, next_step=[("alpha module wiring", base, "src/a.py")]))
        run_git(repo, "add", "--", self.rel(repo, path))
        self.commit(repo, "commit the progress")
        self.assert_fresh(repo, path)

    def test_o2_boundary_entry_commit_is_the_commit_that_touched_the_file(self):
        repo = self.new_repo()
        touched = self.touch_commit(repo, "src/a.py")
        path = self.put(repo, NAME1, build(stamp=touched, next_step=[("alpha module wiring", touched, "src/a.py")]))
        self.assert_fresh(repo, path)

    def test_o2_short_sha_of_seven_characters_resolves(self):
        repo = self.new_repo()
        base = self.head(repo)
        short = base[:7]
        path = self.put(repo, NAME1, build(stamp=base, next_step=[("alpha module wiring", short, "src/a.py")]))
        self.assert_fresh(repo, path)
        self.touch_commit(repo, "src/a.py")
        self.assert_stale(repo, path, "changed")

    def test_o2_c8_unresolved_sha_is_stale(self):
        for sha in ("deadbeef" * 5, "deadbee"):
            with self.subTest(sha=sha):
                repo, path = self.entry_repo(sha, "src/a.py")
                self.assert_stale(repo, path, "unresolved")

    def test_o2_c8_non_ancestor_commit_is_stale(self):
        repo = self.new_repo()
        main = self.branch(repo)
        run_git(repo, "checkout", "-q", "-b", "side")
        side = self.touch_commit(repo, "src/side.py")
        run_git(repo, "checkout", "-q", main)
        path = self.put(repo, NAME1, build(stamp=self.head(repo), next_step=[("alpha module wiring", side, "src/a.py")]))
        self.assert_stale(repo, path, "not ancestor")

    def test_o2_files_none_skips_the_changed_check_only(self):
        repo = self.new_repo()
        base = self.head(repo)
        self.touch_commit(repo, "src/a.py")
        path = self.put(repo, NAME1, build(stamp=self.head(repo), next_step=[("alpha module wiring", base, "none")]))
        self.assert_fresh(repo, path)
        path.write_text(build(stamp=self.head(repo), next_step=[("alpha module wiring", "deadbeef" * 5, "none")]))
        self.assert_stale(repo, path, "unresolved")

    def test_o2_files_none_with_non_ancestor_commit_is_stale(self):
        repo = self.new_repo()
        main = self.branch(repo)
        run_git(repo, "checkout", "-q", "-b", "side")
        side = self.touch_commit(repo, "src/side.py")
        run_git(repo, "checkout", "-q", main)
        path = self.put(repo, NAME1, build(stamp=self.head(repo), next_step=[("alpha module wiring", side, "none")]))
        self.assert_stale(repo, path, "not ancestor")

    def test_o2_each_entry_gets_its_own_label(self):
        repo = self.new_repo()
        base = self.head(repo)
        self.touch_commit(repo, "src/a.py")
        path = self.put(repo, NAME1, build(
            stamp=self.head(repo),
            state=[("beta untouched file", base, "src/b.py")],
            next_step=[("alpha touched file", base, "src/a.py")]))
        shown = self.show(repo, self.rel(repo, path))
        self.assertRegex(shown.stdout, r"\bfresh\b")
        self.assertIn("stale: changed", shown.stdout)

    def test_o2_fr8_hook_feedback_reports_stale_and_is_silent_when_fresh(self):
        repo = self.new_repo()
        self.add_marker(repo, os.getpid())
        base = self.head(repo)
        path = self.put(repo, NAME1, build(stamp=base, next_step=[("alpha module wiring", base, "src/a.py")]))
        quiet = self.post(repo, path)
        self.assertEqual((quiet.returncode, quiet.stderr, quiet.stdout), (0, "", ""))
        self.touch_commit(repo, "src/a.py")
        path.write_text(build(stamp=self.head(repo), next_step=[("alpha module wiring", base, "src/a.py")]))
        loud = self.post(repo, path)
        self.assertEqual(loud.returncode, 2, out(loud))
        self.assertIn("stale", loud.stderr)


def near(base, distance):
    assert "#" not in base
    chars = list(base)
    positions = [i for i, c in enumerate(chars) if c != " "]
    step = len(positions) // distance if distance else 1
    for k in range(distance):
        chars[positions[k * step]] = "#"
    result = "".join(chars)
    assert lev(base, result) == distance, (base, result)
    return result


WORDS = "alpha beta gamma delta epsilon zeta eta theta iota kappa lambda mu nu xi omicron pi rho sigma tau upsilon"


def sized(length):
    text = (WORDS + " " + WORDS)[:length]
    if text.endswith(" "):
        text = text[:-1] + "x"
    assert len(text) == length and text == text.strip() and "  " not in text, text
    return text


class TestSimilarity(ProgressCase):

    def pair_repo(self, old_text, new_text, old_commit="first", new_commit="second", link="before",
                  extra_old=(), old_section="state", new_section="next_step"):
        repo = self.new_repo()
        first = self.head(repo)
        second = self.commit(repo, "second commit")
        commits = {"first": first, "second": second}
        old_entries = list(extra_old) + [(old_text, commits[old_commit], "none")]
        old = self.put(repo, NAME1, build(session="sessb", stamp=second, **{old_section: old_entries}), directory="progress-logs")
        links = {"before": {"before": self.rel(repo, old)}, "previous": {"previous": self.rel(repo, old)}, "none": {}}[link]
        new = self.put(repo, NAME2, build(session="sessa", stamp=second, **{new_section: [(new_text, commits[new_commit], "none")]}, **links))
        return repo, new

    def assert_duplicate(self, repo, new, expected):
        checked = self.check(repo, self.rel(repo, new))
        shown = self.show(repo, self.rel(repo, new))
        self.assertEqual("near-duplicate" in checked.stdout + checked.stderr, expected, out(checked))
        self.assertEqual("near-duplicate" in shown.stdout, expected, shown.stdout)
        self.assertEqual(checked.returncode, 1 if expected else 0, out(checked))

    def test_o3_boundaries_of_the_similarity_threshold(self):
        cases = (
            ("0.90 at 20 chars", 20, 2, True),
            ("0.90 at 100 chars", 100, 10, True),
            ("0.89 at 100 chars", 100, 11, False),
            ("0.85 at 20 chars", 20, 3, False),
            ("1.0 at 20 chars", 20, 0, True),
        )
        for label, length, distance, expected in cases:
            with self.subTest(case=label):
                base = sized(length)
                other = near(base, distance) if distance else base
                self.assertAlmostEqual(1 - lev(base, other) / length, {2: 0.9, 10: 0.9, 11: 0.89, 3: 0.85, 0: 1.0}[distance])
                repo, new = self.pair_repo(base, other)
                self.assert_duplicate(repo, new, expected)

    def test_o3_length_boundary_19_vs_20_characters(self):
        for length, expected in ((19, False), (20, True)):
            with self.subTest(length=length):
                text = sized(length)
                repo, new = self.pair_repo(text, text)
                self.assert_duplicate(repo, new, expected)

    def test_o3_same_commit_never_warns_and_different_commit_does(self):
        text = sized(40)
        for old_commit, new_commit, expected in (("first", "first", False), ("second", "second", False),
                                                  ("first", "second", True), ("second", "first", True)):
            with self.subTest(old=old_commit, new=new_commit):
                repo, new = self.pair_repo(text, text, old_commit, new_commit)
                self.assert_duplicate(repo, new, expected)

    def test_o3_whitespace_is_normalized_before_comparing(self):
        spaced = "update   the  schema\tmigration   now  please"
        plain = "update the schema migration now please"
        self.assertGreater(lev(spaced, plain), 3)
        repo, new = self.pair_repo(plain, spaced)
        self.assert_duplicate(repo, new, True)

    def test_o3_predecessor_is_found_through_before_or_previous_only(self):
        text = sized(40)
        for link, expected in (("before", True), ("previous", True), ("none", False)):
            with self.subTest(link=link):
                repo, new = self.pair_repo(text, text, link=link)
                self.assert_duplicate(repo, new, expected)

    def test_o3_both_links_are_consulted(self):
        text = sized(40)
        repo = self.new_repo()
        first = self.head(repo)
        second = self.commit(repo, "second commit")
        unrelated = self.put(repo, NAME0, build(session="sessc", stamp=second, state=[("completely different subject matter here", first, "none")]), directory="progress-logs")
        twin = self.put(repo, NAME1, build(session="sessb", stamp=second, state=[(text, first, "none")]), directory="progress-logs")
        for links in ({"before": self.rel(repo, unrelated), "previous": self.rel(repo, twin)},
                      {"before": self.rel(repo, twin), "previous": self.rel(repo, unrelated)}):
            with self.subTest(links=links):
                new = self.put(repo, NAME2, build(session="sessa", stamp=second, next_step=[(text, second, "none")], **links))
                self.assert_duplicate(repo, new, True)

    def test_o3_any_predecessor_entry_in_any_subsection_matches(self):
        text = sized(40)
        repo, new = self.pair_repo(text, text, extra_old=[("an unrelated first entry with other words", "a" * 40, "none")])
        self.assert_duplicate(repo, new, True)
        repo, new = self.pair_repo(text, text, old_section="verify", new_section="dead_ends")
        self.assert_duplicate(repo, new, True)

    def test_o3_fr8_hook_warns_and_tells_the_agent_to_ask_the_user(self):
        text = sized(40)
        repo, new = self.pair_repo(text, text)
        self.add_marker(repo, os.getpid())
        result = self.post(repo, new, sid="sessa")
        self.assertEqual(result.returncode, 2, out(result))
        self.assertIn("near-duplicate", result.stderr)
        self.assertIn("ask the user", result.stderr.lower())
        repo, new = self.pair_repo(text, near(text, 15))
        self.add_marker(repo, os.getpid())
        quiet = self.post(repo, new, sid="sessa")
        self.assertNotIn("near-duplicate", quiet.stderr)



class TestStopSessionStartPreCompact(ProgressCase):

    def setup_session(self, changed, kind):
        repo = self.new_repo()
        head = self.head(repo)
        if kind != "none":
            session = "sessb" if kind == "other" else "sessa"
            entries = [] if kind == "own_empty" else [("alpha work item", head, "none")]
            path = self.put(repo, NAME1, build(session=session, stamp=head, next_step=entries))
            run_git(repo, "add", "--", self.rel(repo, path))
            self.commit(repo, "progress")
        result = self.start(repo)
        self.assertEqual(result.returncode, 0, out(result))
        if changed:
            (repo / "src" / "new.py").write_text("new = 1\n")
        return repo

    def test_o4_stop_decision_table(self):
        write_reason = "agent-docs/progress"
        empty_reason = "none:"
        table = []
        for active in (False, True):
            table += [
                (True, "none", active, None if active else write_reason),
                (False, "none", active, None),
                (True, "own_empty", active, None if active else empty_reason),
                (False, "own_empty", active, None if active else empty_reason),
                (True, "own_filled", active, None),
                (False, "own_filled", active, None),
                (True, "other", active, None if active else write_reason),
                (False, "other", active, None),
            ]
        for changed, kind, active, reason in table:
            with self.subTest(changed=changed, progress=kind, stop_hook_active=active):
                repo = self.setup_session(changed, kind)
                result = self.stop(repo, active=active)
                if reason is None:
                    self.assertEqual((result.returncode, result.stdout, result.stderr), (0, "", ""))
                else:
                    self.assertEqual(result.returncode, 2, out(result))
                    self.assertIn(reason, result.stderr)
                    self.assertNotIn("Traceback", result.stderr)

    def test_o4_c11_empty_next_session_reason_names_the_section_and_the_none_bullet(self):
        repo = self.setup_session(True, "own_empty")
        result = self.stop(repo)
        self.assertEqual(result.returncode, 2, out(result))
        self.assertIn("Next Session", result.stderr)
        self.assertIn("- none:", result.stderr)

    def test_o4_c11_changed_by_new_commit_or_modified_tracked_file_blocks(self):
        repo = self.setup_session(False, "none")
        self.touch_commit(repo, "src/a.py")
        self.assertEqual(self.stop(repo).returncode, 2)
        repo = self.setup_session(False, "none")
        (repo / "src" / "a.py").write_text("a = 2\n")
        self.assertEqual(self.stop(repo).returncode, 2)

    def test_o4_c13_changes_only_under_harness_do_not_count(self):
        repo = self.setup_session(False, "none")
        (repo / ".harness" / "scratch.txt").write_text("x\n")
        result = self.stop(repo)
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, "", ""))

    def test_o4_c22_only_a_none_bullet_does_not_block_and_show_does_not_warn(self):
        repo = self.new_repo()
        head = self.head(repo)
        path = self.put(repo, NAME1, build(session="sessa", stamp=head, none_bullet="finished"))
        run_git(repo, "add", "--", self.rel(repo, path))
        self.commit(repo, "progress")
        self.start(repo)
        (repo / "src" / "new.py").write_text("x\n")
        result = self.stop(repo)
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, "", ""))
        shown = self.show(repo, self.rel(repo, path))
        self.assertEqual(shown.returncode, 0, out(shown))
        self.assertNotRegex(shown.stdout.lower(), r"warning|no entr")
        empty = self.put(repo, NAME1, build(session="sessa", stamp=head))
        shown = self.show(repo, self.rel(repo, empty))
        self.assertRegex(shown.stdout.lower(), r"warning|no entr")

    def test_o4_fr9_session_start_records_head_branch_and_empty_prompts(self):
        repo = self.new_repo()
        result = self.start(repo)
        self.assertEqual(result.returncode, 0, out(result))
        state = self.state(repo)
        self.assertEqual(state["start_head"], self.head(repo))
        self.assertEqual(state["branch"], self.branch(repo))
        self.assertEqual(state["prompts"], [])

    def test_o4_fr9_state_is_kept_per_session(self):
        repo = self.new_repo()
        self.start(repo, sid="sessa")
        self.touch_commit(repo, "src/a.py")
        self.start(repo, sid="sessb")
        self.assertNotEqual(self.state(repo, "sessa")["start_head"], self.state(repo, "sessb")["start_head"])

    def test_o4_fr15_precompact_reminder_decision_table(self):
        for progress_kind, changed, expected in (
            ("none", False, False), ("none", True, True), ("own_filled", False, True),
            ("own_filled", True, True), ("other", False, False),
        ):
            with self.subTest(progress=progress_kind, changed=changed):
                repo = self.setup_session(changed, progress_kind)
                result = self.precompact(repo)
                self.assertEqual(result.returncode, 0, out(result))
                if expected:
                    self.assertIn("Next Session", result.stdout)
                else:
                    self.assertEqual((result.stdout, result.stderr), ("", ""))


class TestErrors(ProgressCase):

    def old_and_new(self, repo, new_text):
        head = self.head(repo)
        old_text = build(session="sessb", stamp=head, next_step=[("old item", head, "none")])
        old = self.put(repo, NAME1, old_text)
        new = self.put(repo, NAME2, new_text)
        self.add_marker(repo, os.getpid())
        return old, old_text, new

    def test_o5_row1_invalid_frontmatter_is_reported_and_nothing_changes(self):
        good = build(session="sessa")
        body = good.split("---\n", 2)[2]
        cases = {
            "no frontmatter": body,
            "unterminated frontmatter": "---\nsession: sessa\nbefore: none\n" + body,
            "empty file": "",
        }
        for label, text in cases.items():
            with self.subTest(case=label):
                repo = self.new_repo()
                old, old_text, new = self.old_and_new(repo, text)
                self.start(repo)
                self.prompt(repo, "a user request")
                result = self.post(repo, new)
                self.assertEqual(result.returncode, 2, out(result))
                self.assertIn("invalid progress frontmatter", result.stderr)
                self.assertNotIn("Traceback", result.stderr)
                self.assertEqual(new.read_text(), text)
                self.assertEqual(old.read_text(), old_text)
                self.assertFalse(any((repo / "agent-docs" / "progress-logs").glob("*.md")))

    def test_o5_row2_entry_without_metadata_line_is_a_finding(self):
        text = "x" * 80
        for label, run in (("cli", True), ("hook", False)):
            with self.subTest(surface=label):
                repo = self.new_repo()
                head = self.head(repo)
                body = build(session="sessa", stamp=head).replace("### Next Step\n", f"### Next Step\n- {text}\n", 1)
                path = self.put(repo, NAME1, body)
                if run:
                    result = self.check(repo, self.rel(repo, path))
                    self.assertEqual(result.returncode, 1, out(result))
                else:
                    self.add_marker(repo, os.getpid())
                    result = self.post(repo, path)
                    self.assertEqual(result.returncode, 2, out(result))
                self.assertIn("entry without commit metadata: ", out(result))
                self.assertIn(text[:50], out(result))
                self.assertNotIn(text[:75], out(result))
                self.assertNotIn("Traceback", out(result))

    def test_o5_row3_missing_git_hooks_exit_silently_and_prompt_is_still_recorded(self):
        repo = self.new_repo()
        env = self.env(PATH=self.empty_path_dir())
        for event in ("start", "precompact", "stop"):
            with self.subTest(event=event):
                (repo / "src" / "dirty.py").write_text("x\n")
                result = getattr(self, event)(repo, env=env)
                self.assertEqual((result.returncode, result.stdout, result.stderr), (0, "", ""))
        recorded = self.prompt(repo, "still recorded", env=env)
        self.assertEqual(recorded.returncode, 0, out(recorded))
        self.assertEqual([p["text"] for p in self.state(repo)["prompts"]], ["still recorded"])

    def test_o5_row3_post_tool_use_without_git_reports_and_changes_nothing(self):
        repo = self.new_repo()
        head = self.head(repo)
        text = build(session="sessa", stamp=head, next_step=[("alpha item", head, "src/a.py")])
        path = self.put(repo, NAME1, text)
        result = self.post(repo, path, env=self.env(PATH=self.empty_path_dir()))
        self.assertEqual(result.returncode, 2, out(result))
        self.assertIn("git unavailable; entry checks skipped", result.stderr)
        self.assertEqual(path.read_text(), text)
        self.assertNotIn("Traceback", result.stderr)

    def test_o5_row3_directory_that_is_not_a_repository(self):
        repo = self.new_repo()
        head = self.head(repo)
        text = build(session="sessa", stamp=head, next_step=[("alpha item", head, "none")])
        path = self.put(repo, NAME1, text)
        shutil.rmtree(repo / ".git")
        for event in ("start", "precompact", "stop"):
            with self.subTest(event=event):
                result = getattr(self, event)(repo)
                self.assertEqual((result.returncode, result.stdout, result.stderr), (0, "", ""))
        result = self.post(repo, path)
        self.assertEqual(result.returncode, 2, out(result))
        self.assertIn("git unavailable; entry checks skipped", result.stderr)
        self.assertNotIn("Traceback", out(result))

    def test_o5_row5_show_path_outside_progress_directories(self):
        repo = self.new_repo()
        (repo / "notes.md").write_text("# Notes\nSECRET-NOTES-CONTENT\n")
        for rel in ("notes.md", "agent-docs/try-n-fail/index.md"):
            with self.subTest(path=rel):
                result = self.show(repo, rel)
                self.assertEqual(result.returncode, 1, out(result))
                self.assertIn("not a progress path", out(result))
                self.assertNotIn("SECRET-NOTES-CONTENT", out(result))

    def test_o5_row6_stop_without_state_file_uses_git_status_and_appends_empty_subsection_only_if_missing(self):
        repo = self.new_repo()
        head = self.head(repo)
        (repo / "src" / "new.py").write_text("x\n")
        blocked = self.stop(repo)
        self.assertEqual(blocked.returncode, 2, out(blocked))
        self.assertNotIn("Traceback", out(blocked))
        missing = build(session="sessa", stamp=head, next_step=[("alpha item", head, "none")], user_requests=None)
        path = self.put(repo, NAME1, missing)
        result = self.stop(repo)
        self.assertEqual(result.returncode, 0, out(result))
        before, body, after = split_requests(path.read_text())
        self.assertEqual(body, [])
        self.assertTrue(before.startswith(missing.rstrip("\n")))
        kept = build(session="sessa", stamp=head, next_step=[("alpha item", head, "none")], user_requests=f"#### 1 {EM} 2026-01-01T00:00:00Z\n> kept text")
        path.write_text(kept)
        self.stop(repo)
        self.assertEqual(path.read_text(), kept)

    def test_o5_row7_unwritable_state_gives_notice_and_stores_nothing(self):
        repo = self.new_repo()
        self.state_path(repo).mkdir(parents=True)
        raw = "my key AKIAIOSFODNN7ABCDEFG and marker UNIQUE-PROMPT-MARKER-9917"
        result = self.prompt(repo, raw)
        self.assertEqual(result.returncode, 0, out(result))
        self.assertIn("harness: prompt not recorded in progress:", result.stdout)
        self.assertIn("### Constraints", result.stdout)
        self.assertNotIn("Traceback", out(result))
        for path, data in self.all_repo_text(repo):
            self.assertNotIn(b"UNIQUE-PROMPT-MARKER-9917", data, path)
            self.assertNotIn(b"AKIAIOSFODNN7ABCDEFG", data, path)

    def test_o5_row7_corrupt_state_file_does_not_crash_prompt_or_stop(self):
        repo = self.new_repo()
        self.sessions_dir(repo).mkdir(parents=True, exist_ok=True)
        self.state_path(repo).write_text("{not json")
        result = self.prompt(repo, "hello there")
        self.assertEqual(result.returncode, 0, out(result))
        self.assertNotIn("Traceback", out(result))
        result = self.stop(repo)
        self.assertIn(result.returncode, (0, 2))
        self.assertNotIn("Traceback", out(result))

    def test_o5_row8_prompt_payload_without_prompt_string_records_nothing(self):
        repo = self.new_repo()
        self.start(repo)
        for label, extra in (("absent", {}), ("null", {"prompt": None}), ("number", {"prompt": 5}), ("list", {"prompt": ["a"]})):
            with self.subTest(prompt=label):
                result = self.hook(repo, {"hook_event_name": "UserPromptSubmit", "session_id": "sessa", **extra})
                self.assertEqual((result.returncode, result.stdout), (0, ""))
                self.assertNotIn("Traceback", result.stderr)
                self.assertEqual(self.state(repo)["prompts"], [])

    def test_o5_c23_malformed_progress_reports_findings_without_crash_or_rotation(self):
        head_repo = self.new_repo()
        head = self.head(head_repo)
        valid = build(session="sessa", stamp=head, next_step=[("alpha item", head, "none")])
        cases = {
            "no frontmatter": valid.split("---\n", 2)[2],
            "missing sections": valid.replace("### Verify\n", "").replace("## Record", "## Recordx"),
            "garbage metadata": valid.replace(f"  - commit: {head}; files: none", "  - commit: ???; files: ;;"),
        }
        for label, text in cases.items():
            with self.subTest(case=label):
                repo = self.new_repo()
                path = self.put(repo, NAME1, text)
                checked = self.check(repo, self.rel(repo, path))
                self.assertEqual(checked.returncode, 1, out(checked))
                self.assertTrue(out(checked).strip())
                self.assertNotIn("Traceback", out(checked))
                self.add_marker(repo, os.getpid())
                posted = self.post(repo, path, sid="sessa")
                self.assertNotIn("Traceback", out(posted))
                self.assertIn(posted.returncode, (0, 2))

    def test_o5_c23_malformed_new_progress_does_not_rotate_the_old_one(self):
        repo = self.new_repo()
        old, old_text, new = self.old_and_new(repo, "garbage without frontmatter\n")
        result = self.post(repo, new)
        self.assertEqual(result.returncode, 2, out(result))
        self.assertEqual(old.read_text(), old_text)
        self.assertFalse(any((repo / "agent-docs" / "progress-logs").glob("*.md")))


class TestShow(ProgressCase):

    def make(self, repo, name, session, directory="progress", before="none", text="item"):
        head = self.head(repo)
        content = build(session=session, before=before, stamp=head,
                        next_step=[(f"{text} for next session", head, "none")],
                        changes=f"- {RECORD_MARKER} changes",
                        user_requests=f"#### 1 {EM} 2026-01-01T00:00:00Z\n> {RECORD_MARKER} request")
        return self.put(repo, name, content, directory=directory), content

    def next_session(self, content):
        return content[content.index("## Next Session"):content.index("## Record")].rstrip("\n")

    def assert_prints(self, result, content, session):
        self.assertEqual(result.returncode, 0, out(result))
        self.assertIn(f"session: {session}", result.stdout)
        self.assertIn(self.next_session(content), result.stdout)
        self.assertRegex(result.stdout, r"\bfresh\b")
        for forbidden in ("## Record", RECORD_MARKER, "### Changes", "### Commands", "### Failed Attempts",
                          "### Sources", "### User Requests"):
            self.assertNotIn(forbidden, result.stdout)

    def test_o6_c14_other_sessions_progress_is_printed_for_session_flag_and_env(self):
        repo = self.new_repo()
        _, content = self.make(repo, NAME1, "sessb")
        self.assert_prints(self.show(repo, "--session", "sessa"), content, "sessb")
        self.assert_prints(self.show(repo, session_env="sessa"), content, "sessb")

    def test_o6_session_flag_wins_over_environment(self):
        repo = self.new_repo()
        _, previous = self.make(repo, NAME0, "sess0", directory="progress-logs", text="zeroth")
        _, current = self.make(repo, NAME1, "sessb", before=f"agent-docs/progress-logs/{NAME0}")
        flag_wins = self.show(repo, "--session", "sessa", session_env="sessb")
        self.assert_prints(flag_wins, current, "sessb")
        env_only = self.show(repo, session_env="sessb")
        self.assert_prints(env_only, previous, "sess0")

    def test_o6_c15_own_progress_resolves_to_its_before_file(self):
        repo = self.new_repo()
        _, previous = self.make(repo, NAME1, "sessb", directory="progress-logs", text="predecessor")
        _, own = self.make(repo, NAME2, "sessa", before=f"agent-docs/progress-logs/{NAME1}", text="own current")
        for result in (self.show(repo, "--session", "sessa"), self.show(repo, session_env="sessa")):
            self.assert_prints(result, previous, "sessb")
            self.assertNotIn("own current", result.stdout)

    def test_o6_c16_explicit_logs_path(self):
        repo = self.new_repo()
        _, zero = self.make(repo, NAME0, "sess0", directory="progress-logs", text="zeroth")
        self.make(repo, NAME1, "sessb", before=f"agent-docs/progress-logs/{NAME0}")
        result = self.show(repo, f"agent-docs/progress-logs/{NAME0}", "--session", "sessa")
        self.assert_prints(result, zero, "sess0")

    def test_o6_explicit_progress_path_wins_even_for_the_current_session(self):
        repo = self.new_repo()
        _, own = self.make(repo, NAME1, "sessa")
        self.assert_prints(self.show(repo, f"agent-docs/progress/{NAME1}", "--session", "sessa"), own, "sessa")

    def test_o6_c17_nothing_to_continue_exits_1(self):
        repo = self.new_repo()
        result = self.show(repo, "--session", "sessa")
        self.assertEqual(result.returncode, 1, out(result))
        self.assertIn("no progress to continue", out(result))
        self.assertNotIn("Traceback", out(result))
        self.make(repo, NAME1, "sessa", before="none")
        result = self.show(repo, "--session", "sessa")
        self.assertEqual(result.returncode, 1, out(result))
        self.assertIn("no progress to continue", out(result))

    def test_o6_fr13_report_marks_stale_entries(self):
        repo = self.new_repo()
        base = self.head(repo)
        self.touch_commit(repo, "src/a.py")
        self.put(repo, NAME1, build(session="sessb", stamp=self.head(repo), next_step=[("alpha item", base, "src/a.py")]))
        result = self.show(repo, "--session", "sessa")
        self.assertIn("stale: changed", result.stdout)
        self.assertNotIn("## Record", result.stdout)


class TestPostMerge(ProgressCase):

    LOCAL_MARK = "LOCAL-POST-MERGE-RAN"

    def install_local_hook(self, repo):
        local = repo / ".git" / "hooks" / "post-merge"
        local.parent.mkdir(exist_ok=True)
        local.write_text(f"#!/bin/sh\necho {self.LOCAL_MARK}\n")
        local.chmod(local.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    def merge(self, repo, *flags):
        return subprocess.run(["git", "-C", str(repo), "merge", *flags, "feature"], stdout=subprocess.PIPE,
                              stderr=subprocess.STDOUT, text=True, env=self.env())

    def feature_branch(self, repo, files):
        main = self.branch(repo)
        run_git(repo, "checkout", "-q", "-b", "feature")
        for rel, content in files.items():
            path = repo / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)
            run_git(repo, "add", "--", rel)
        self.commit(repo, "feature work")
        run_git(repo, "checkout", "-q", main)
        return main

    def test_o7_c18_merge_that_adds_progress_moves_it_prints_path_then_runs_local_hook(self):
        for label, advance_main, flags in (("true merge", True, ("--no-ff", "--no-edit")),
                                           ("fast-forward", False, ("--ff-only",))):
            with self.subTest(case=label):
                repo = self.new_repo()
                self.install_local_hook(repo)
                added = build(session="sessb", stamp=self.head(repo), next_step=[("feature item", self.head(repo), "none")])
                self.feature_branch(repo, {f"agent-docs/progress/{NAME1}": added})
                if advance_main:
                    self.touch_commit(repo, "src/main_only.py")

                result = self.merge(repo, *flags)

                self.assertEqual(result.returncode, 0, result.stdout)
                destination = repo / "agent-docs" / "progress-logs" / NAME1
                self.assertEqual(destination.read_bytes(), added.encode())
                self.assertFalse((repo / "agent-docs" / "progress" / NAME1).exists())
                self.assertIn(f"agent-docs/progress-logs/{NAME1}", result.stdout)
                self.assertIn(self.LOCAL_MARK, result.stdout)
                self.assertLess(result.stdout.index(f"agent-docs/progress-logs/{NAME1}"), result.stdout.index(self.LOCAL_MARK))

    def test_o7_merge_without_added_progress_moves_nothing_but_local_hook_runs(self):
        repo = self.new_repo()
        self.install_local_hook(repo)
        head = self.head(repo)
        kept_text = build(session="sessa", stamp=head, next_step=[("main item", head, "none")])
        kept = self.put(repo, NAME2, kept_text)
        run_git(repo, "add", "--", self.rel(repo, kept))
        self.commit(repo, "main progress")
        self.feature_branch(repo, {"src/x.py": "x = 1\n"})
        self.touch_commit(repo, "src/main_only.py")

        result = self.merge(repo, "--no-ff", "--no-edit")

        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertEqual(kept.read_text(), kept_text)
        self.assertFalse(any((repo / "agent-docs" / "progress-logs").glob("*.md")))
        self.assertNotIn("progress-logs", result.stdout)
        self.assertIn(self.LOCAL_MARK, result.stdout)

    def test_o7_merge_that_only_modifies_an_existing_progress_does_not_move_it(self):
        repo = self.new_repo()
        head = self.head(repo)
        original = build(session="sessa", stamp=head, next_step=[("main item", head, "none")])
        kept = self.put(repo, NAME2, original)
        run_git(repo, "add", "--", self.rel(repo, kept))
        self.commit(repo, "main progress")
        modified = original.replace("main item", "edited item")
        self.feature_branch(repo, {f"agent-docs/progress/{NAME2}": modified})
        self.touch_commit(repo, "src/main_only.py")

        result = self.merge(repo, "--no-ff", "--no-edit")

        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertEqual(kept.read_text(), modified)
        self.assertFalse(any((repo / "agent-docs" / "progress-logs").glob("*.md")))

    def test_o7_every_added_progress_file_is_moved(self):
        repo = self.new_repo()
        head = self.head(repo)
        texts = {NAME1: build(session="sessb", stamp=head, next_step=[("one item", head, "none")]),
                 NAME2: build(session="sessc", stamp=head, next_step=[("two item", head, "none")])}
        self.feature_branch(repo, {f"agent-docs/progress/{n}": t for n, t in texts.items()})
        self.touch_commit(repo, "src/main_only.py")

        result = self.merge(repo, "--no-ff", "--no-edit")

        self.assertEqual(result.returncode, 0, result.stdout)
        for name, text in texts.items():
            self.assertEqual((repo / "agent-docs" / "progress-logs" / name).read_bytes(), text.encode())
            self.assertIn(name, result.stdout)
        self.assertFalse(any((repo / "agent-docs" / "progress").glob("*.md")))


VERBS = ("write", "merge", "add", "rename", "ask", "re-check", "replace", "end", "remove", "quote", "move", "update", "run", "fix")
VERB_RE = re.compile(r"(?<![\w-])(" + "|".join(re.escape(v) for v in VERBS) + r")(?![\w-])", re.I)


class TestMessageQuality(ProgressCase):

    def assert_actionable(self, text, names, label):
        self.assertTrue(any(n in text for n in names), f"{label}: none of {names} in {text!r}")
        self.assertRegex(text, VERB_RE, f"{label}: no next-action verb in {text!r}")

    def rotation_pair(self, same_session=False, marker=None, logged=False):
        repo = self.new_repo()
        self.add_marker(repo, os.getpid())
        if marker:
            self.add_marker(repo, marker)
        head = self.head(repo)
        self.put(repo, NAME1, build(session="sessa", stamp=head, next_step=[("old work item", head, "none")]))
        if logged:
            self.put(repo, NAME1, "earlier log\n", directory="progress-logs")
        new = self.put(repo, NAME2, build(session="sessa" if same_session else "sessb", stamp=head,
                                          next_step=[("new work item", head, "none")]))
        return repo, new

    def test_o16_hook_messages_name_the_file_and_an_action(self):
        def move():
            repo, new = self.rotation_pair()
            return self.post(repo, new, sid="sessb").stderr, [NAME1]

        def same_session():
            repo, new = self.rotation_pair(same_session=True)
            return self.post(repo, new, sid="sessa").stderr, [NAME2]

        def parallel():
            repo, new = self.rotation_pair(marker=1)
            return self.post(repo, new, sid="sessb").stderr, [NAME2]

        def destination_exists():
            repo, new = self.rotation_pair(logged=True)
            return self.post(repo, new, sid="sessb").stderr, [f"progress-logs/{NAME1}"]

        def stale():
            repo = self.new_repo()
            base = self.head(repo)
            self.touch_commit(repo, "src/a.py")
            path = self.put(repo, NAME1, build(stamp=self.head(repo), next_step=[("alpha module wiring", base, "src/a.py")]))
            return self.post(repo, path).stderr, [NAME1]

        def near_duplicate():
            text = sized(40)
            repo = self.new_repo()
            first = self.head(repo)
            second = self.commit(repo, "second")
            old = self.put(repo, NAME1, build(session="sessb", stamp=second, state=[(text, first, "none")]), directory="progress-logs")
            new = self.put(repo, NAME2, build(session="sessa", stamp=second, before=self.rel(repo, old), next_step=[(text, second, "none")]))
            return self.post(repo, new).stderr, [NAME2]

        def invalid_frontmatter():
            repo = self.new_repo()
            path = self.put(repo, NAME2, "no frontmatter here\n")
            return self.post(repo, path).stderr, [NAME2]

        def missing_metadata():
            repo = self.new_repo()
            body = build(session="sessa", stamp=self.head(repo)).replace("### Next Step\n", "### Next Step\n- an entry without any metadata line\n", 1)
            path = self.put(repo, NAME1, body)
            return self.post(repo, path).stderr, [NAME1]

        def git_unavailable():
            repo = self.new_repo()
            head = self.head(repo)
            path = self.put(repo, NAME1, build(session="sessa", stamp=head, next_step=[("alpha item", head, "src/a.py")]))
            return self.post(repo, path, env=self.env(PATH=self.empty_path_dir())).stderr, [NAME1]

        def stop_missing_progress():
            repo = self.new_repo()
            self.start(repo)
            (repo / "src" / "new.py").write_text("x\n")
            return self.stop(repo).stderr, ["agent-docs/progress"]

        def stop_empty_next_session():
            repo = self.new_repo()
            path = self.put(repo, NAME1, build(session="sessa", stamp=self.head(repo)))
            run_git(repo, "add", "--", self.rel(repo, path))
            self.commit(repo, "progress")
            self.start(repo)
            return self.stop(repo).stderr, [NAME1]

        for label, scenario in (("FR5 move", move), ("FR6 refusal", same_session), ("FR7 refusal", parallel),
                                ("destination exists", destination_exists), ("FR8 stale", stale),
                                ("FR8 near-duplicate", near_duplicate), ("invalid frontmatter", invalid_frontmatter),
                                ("missing metadata", missing_metadata), ("git unavailable", git_unavailable),
                                ("FR10 missing progress", stop_missing_progress),
                                ("FR10 empty Next Session", stop_empty_next_session)):
            with self.subTest(message=label):
                text, names = scenario()
                self.assert_actionable(text, names, label)

    def test_o16_prompt_not_recorded_notice_names_the_state_file(self):
        repo = self.new_repo()
        self.state_path(repo).mkdir(parents=True)
        result = self.prompt(repo, "hello")
        self.assert_actionable(result.stdout, ["progress-sessa.json"], "prompt not recorded")

    def test_o16_cli_errors_name_the_path_and_an_action(self):
        repo = self.new_repo()
        (repo / "notes.md").write_text("# Notes\n")
        result = self.show(repo, "notes.md")
        self.assert_actionable(out(result), ["notes.md"], "show outside progress dirs")
        empty = self.show(repo, "--session", "sessa")
        self.assert_actionable(out(empty), ["agent-docs/progress", "progress"], "no progress to continue")
        body = "x" * 80
        path = self.put(repo, NAME1, build(session="sessa", stamp=self.head(repo)).replace("### Next Step\n", f"### Next Step\n- {body}\n", 1))
        checked = self.check(repo, self.rel(repo, path))
        self.assert_actionable(out(checked), [NAME1], "check finding")


class TestPromptRecording(ProgressCase):

    PROMPTS = ("first request", "second request line one\nsecond request line two",
               "third request with key AKIAIOSFODNN7ABCDEFG inside", "fourth request")

    def own(self, repo, **kw):
        head = self.head(repo)
        text = build(session="sessa", stamp=head, next_step=[("alpha work item", head, "none")], **kw)
        return self.put(repo, NAME1, text), text

    def expected_requests(self, repo, count, sid="sessa"):
        lines = []
        for n, prompt in enumerate(self.state(repo, sid)["prompts"][:count], 1):
            lines.append(f"#### {n} {EM} {prompt['at']}")
            lines += [f"> {line}" for line in prompt["text"].split("\n")]
        return lines

    def assert_only_requests_changed(self, old_text, new_text):
        old_before, _, old_after = split_requests(old_text)
        new_before, _, new_after = split_requests(new_text)
        self.assertEqual(new_before, old_before)
        self.assertEqual(new_after, old_after)

    def test_o14_no_state_first_prompt_creates_state_with_masked_utc_entry(self):
        repo = self.new_repo()
        self.assertFalse(self.state_path(repo).exists())
        before = datetime.now(timezone.utc)

        result = self.prompt(repo, "hello with key AKIAIOSFODNN7ABCDEFG")

        self.assertEqual((result.returncode, result.stdout), (0, ""), out(result))
        prompts = self.state(repo)["prompts"]
        self.assertEqual([p["text"] for p in prompts], ["hello with key [masked:token]"])
        stamp = datetime.fromisoformat(prompts[0]["at"].replace("Z", "+00:00"))
        self.assertEqual(stamp.utcoffset(), timedelta(0))
        self.assertLess(abs((stamp - before).total_seconds()), 120)

    def test_o14_prompts_keep_order_and_session_start_fields(self):
        repo = self.new_repo()
        self.start(repo)
        for text in ("one", "two", "three"):
            self.assertEqual(self.prompt(repo, text).returncode, 0)
        state = self.state(repo)
        self.assertEqual([p["text"] for p in state["prompts"]], ["one", "two", "three"])
        self.assertEqual(state["start_head"], self.head(repo))
        self.assertEqual(state["branch"], self.branch(repo))
        ats = [p["at"] for p in state["prompts"]]
        self.assertEqual(ats, sorted(ats))

    def test_o14_raw_secret_appears_in_no_file_of_the_repository(self):
        repo = self.new_repo()
        self.start(repo)
        head = self.head(repo)
        path = self.put(repo, NAME1, build(session="sessa", stamp=head, next_step=[("alpha item", head, "none")]))
        secrets = ("AKIAIOSFODNN7ABCDEFG", "hunter2-UNIQUE", "alice@acme-unique.io", "10.77.66.55", "build77.corp")
        self.prompt(repo, "use AKIAIOSFODNN7ABCDEFG and alice@acme-unique.io and 10.77.66.55 and build77.corp\npassword=hunter2-UNIQUE")
        self.post(repo, path)
        self.stop(repo)
        for file, data in self.all_repo_text(repo):
            for secret in secrets:
                self.assertNotIn(secret.encode(), data, file)

    def test_o14_c29_progress_write_then_stop_sync_user_requests(self):
        repo = self.new_repo()
        self.start(repo)
        path, original = self.own(repo, user_requests="")
        for prompt in self.PROMPTS[:3]:
            self.prompt(repo, prompt)

        written = self.post(repo, path)

        self.assertNotIn("Traceback", out(written))
        first_pass = path.read_text()
        _, body, _ = split_requests(first_pass)
        self.assertEqual(body, self.expected_requests(repo, 3))
        self.assertIn("> second request line one", body)
        self.assertIn("> second request line two", body)
        self.assertIn("> third request with key [masked:token] inside", body)
        self.assertNotIn("AKIAIOSFODNN7ABCDEFG", first_pass)
        self.assert_only_requests_changed(original, first_pass)

        self.prompt(repo, self.PROMPTS[3])
        stopped = self.stop(repo, active=True)

        self.assertNotIn("Traceback", out(stopped))
        second_pass = path.read_text()
        _, body, _ = split_requests(second_pass)
        self.assertEqual(body, self.expected_requests(repo, 4))
        self.assertEqual(body[:len(self.expected_requests(repo, 3))], self.expected_requests(repo, 3))
        self.assert_only_requests_changed(original, second_pass)

    def test_o14_sync_is_idempotent_and_rewrites_stale_content(self):
        repo = self.new_repo()
        self.start(repo)
        path, original = self.own(repo, user_requests=f"#### 9 {EM} 2020-01-01T00:00:00Z\n> junk from an older sync")
        self.prompt(repo, "only real prompt")
        self.post(repo, path)
        once = path.read_text()
        self.assertNotIn("junk from an older sync", once)
        self.assertEqual(split_requests(once)[1], self.expected_requests(repo, 1))
        self.post(repo, path)
        self.assertEqual(path.read_text(), once)

    def test_o14_content_after_the_subsection_is_preserved(self):
        repo = self.new_repo()
        self.start(repo)
        path, original = self.own(repo, user_requests=f"#### 1 {EM} 2020-01-01T00:00:00Z\n> old", trailer="\n### Extra Notes\nkeep this exactly\n")
        self.prompt(repo, "a prompt")
        self.post(repo, path)
        text = path.read_text()
        self.assert_only_requests_changed(original, text)
        self.assertTrue(text.endswith("### Extra Notes\nkeep this exactly\n"))

    def test_o14_missing_subsection_is_appended_at_the_end_of_record(self):
        repo = self.new_repo()
        self.start(repo)
        path, original = self.own(repo, user_requests=None)
        self.prompt(repo, "a prompt")
        self.post(repo, path)
        text = path.read_text()
        before, body, after = split_requests(text)
        self.assertTrue(before.startswith(original.rstrip("\n")), before)
        self.assertLess(text.index("### Sources"), text.index("### User Requests"))
        self.assertEqual(body, self.expected_requests(repo, 1))
        self.assertEqual(after, "")

    def test_o14_other_sessions_prompts_are_not_mixed_in(self):
        repo = self.new_repo()
        self.start(repo)
        path, _ = self.own(repo, user_requests="")
        self.prompt(repo, "mine", sid="sessa")
        self.prompt(repo, "theirs-UNIQUE", sid="sessb")
        self.post(repo, path)
        self.assertIn("> mine", path.read_text())
        self.assertNotIn("theirs-UNIQUE", path.read_text())

    def test_o14_unsafe_session_id_cannot_write_outside_the_sessions_directory(self):
        repo = self.new_repo()
        self.start(repo)
        before = {p for p in repo.rglob("*") if p.is_file() and ".git" not in p.relative_to(repo).parts}
        result = self.prompt(repo, "hello", sid="../../evil/id")
        self.assertEqual(result.returncode, 0, out(result))
        created = {p for p in repo.rglob("*") if p.is_file() and ".git" not in p.relative_to(repo).parts} - before
        self.assertTrue(created)
        for path in created:
            self.assertIn(self.sessions_dir(repo), path.parents, path)

    def test_o14_unwritable_state_prints_notice_and_exits_zero(self):
        repo = self.new_repo()
        self.state_path(repo).mkdir(parents=True)
        result = self.prompt(repo, "keep this out UNIQUE-STATE-MARKER")
        self.assertEqual(result.returncode, 0, out(result))
        self.assertIn("harness: prompt not recorded in progress:", result.stdout)
        for path, data in self.all_repo_text(repo):
            self.assertNotIn(b"UNIQUE-STATE-MARKER", data, path)


SECRET_FIXTURES = {
    "AKIA": ["AKIAIOSFODNN7ABCDEFG", "AKIAABCDEFGHIJKLMNOP"],
    "gh[pousr]_": ["ghp_" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8", "gho_" + "Zy9X8w7V6u5T4s3R2q1P0o9N8m7L6k5J4i3H",
                   "ghu_" + "B1c2D3e4F5g6H7i8J9k0L1m2N3o4P5q6R7s8", "ghs_" + "C1d2E3f4G5h6I7j8K9l0M1n2O3p4Q5r6S7t8",
                   "ghr_" + "D1e2F3g4H5i6J7k8L9m0N1o2P3q4R5s6T7u8"],
    "github_pat_": ["github_pat_" + "11ABCDEFG0abcdefghijkl_abcdefghijklmnopqrstuvwxyz0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ",
                    "github_pat_" + "22ZYXWVUT0mnopqrstuvwx_9876543210abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"],
    "sk-": ["sk-abcdefghijklmnopqrstuvwxyz0123456789ABCD", "sk-ant-api03-abcdefghijklmnopqrstuvwx", "sk-proj-AbCdEfGhIjKlMnOpQrSt"],
    "xox[abposr]-": ["xoxb-" + "1234567890-0987654321098-AbCdEfGhIjKlMnOpQrStUvWx", "xoxp-" + "1111111111-2222222222222-ZyXwVuTsRqPoNmLkJiHgFeDc",
                     "xoxa-" + "1234567890-0987654321098-AbCdEfGhIjKlMnOpQrStUvWx", "xoxo-" + "1234567890-0987654321098-AbCdEfGhIjKlMnOpQrStUvWx",
                     "xoxs-" + "1234567890-0987654321098-AbCdEfGhIjKlMnOpQrStUvWx", "xoxr-" + "1234567890-0987654321098-AbCdEfGhIjKlMnOpQrStUvWx"],
    "AIza": ["AIza" + "SyABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"[:35], "AIza" + "abcdefghijklmnopqrstuvwxyz0123456789"[:35]],
    "jwt": ["eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IkpvaG4ifQ.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c",
            "eyJ0eXAiOiJKV1QifQ.eyJ1aWQiOjQyfQ.c2lnbmF0dXJlYWJj"],
}
PEM_FIXTURES = [
    "-----BEGIN RSA PRIVATE KEY-----\nMIIEowIBAAKCAQEAxyz1234567890\nabcdefghijklmnop\n-----END RSA PRIVATE KEY-----",
    "-----BEGIN PRIVATE KEY-----\nMIIEvQIBADANBgkqhkiG9w0BAQEFAASC\n-----END PRIVATE KEY-----",
    "-----BEGIN OPENSSH PRIVATE KEY-----\nb3BlbnNzaC1rZXktdjEAAAAABG5vbmU\n-----END OPENSSH PRIVATE KEY-----",
]
ASSIGNMENT_KEYS = ("password", "passwd", "pwd", "token", "secret", "api_key", "apikey", "access_key")
EMAILS = ["alice@acme.io", "bob.smith+tag@mail.acme.co.uk", "x_y@domain.co", "ops@notexample.com"]
EMAIL_EXCEPTIONS = ["dev@example.com", "dev@example.org", "dev@example.net", "dev@box.test", "dev@box.example",
                    "dev@box.invalid", "dev@box.localhost"]
IPV4 = ["10.0.0.5", "192.168.1.255", "255.255.255.255", "126.255.255.255", "128.0.0.0", "0.0.0.1"]
IPV6 = ["fe80::1", "2001:db8:0:0:0:0:0:1", "2001:db8::8a2e:370:7334"]
IP_EXCEPTIONS = ["127.0.0.1", "127.255.255.254", "0.0.0.0", "::1", "::"]
HOSTS = {".corp": ["build01.corp", "db.prod.corp"], ".internal": ["svc.internal", "a.b.internal"],
         ".local": ["printer.local", "mac.local"], ".lan": ["nas.lan", "gw.lan"], ".intranet": ["wiki.intranet", "hr.intranet"]}


class MaskCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.p = load_progress()

    def m(self, text, suffixes=SUFFIXES):
        return self.p.mask(text, suffixes)

    def assert_exact(self, text, expected, suffixes=SUFFIXES):
        self.assertEqual(self.m(text, suffixes), expected)
        self.assertEqual(self.m(expected, suffixes), expected)

    def all_samples(self):
        for group, samples in SECRET_FIXTURES.items():
            for sample in samples:
                yield f"token:{group}", sample, "[masked:token]"
        for pem in PEM_FIXTURES:
            yield "token:pem", pem, "[masked:token]"
        for email in EMAILS:
            yield "email", email, "[masked:email]"
        for ip in IPV4 + IPV6:
            yield "ip", ip, "[masked:ip]"
        for host in sum(HOSTS.values(), []):
            yield "host", host, "[masked:host]"


class TestMaskKeysAndTokens(MaskCase):

    def test_o13_each_token_pattern_is_replaced_whole_in_every_context(self):
        for group, samples in SECRET_FIXTURES.items():
            for sample in samples:
                for template, expected in (("use {} now", "use [masked:token] now"), ("{}", "[masked:token]"),
                                           ("a\n{}\nb", "a\n[masked:token]\nb"), ("({})", "([masked:token])"),
                                           ("x={}", "x=[masked:token]")):
                    with self.subTest(pattern=group, sample=sample[:24], template=template):
                        self.assert_exact(template.format(sample), expected)

    def test_o13_pem_private_key_blocks(self):
        for pem in PEM_FIXTURES:
            with self.subTest(pem=pem[:34]):
                self.assert_exact(f"before\n{pem}\nafter", "before\n[masked:token]\nafter")

    def test_o13_bearer_boundary_15_vs_16_characters(self):
        for tail, masked in (("abcdefghijklmno", False), ("abcdefghijklmnop", True), ("A1b2C3d4E5f6G7h8I9j0", True)):
            with self.subTest(tail=tail):
                text = f"Authorization: Bearer {tail}"
                result = self.m(text)
                if masked:
                    self.assertNotIn(tail, result)
                    self.assertIn("[masked:token]", result)
                    self.assertTrue(result.startswith("Authorization: "))
                    self.assertEqual(self.m(result), result)
                else:
                    self.assertEqual(result, text)

    def test_o13_assignment_values_for_every_key_and_separator(self):
        for key in ASSIGNMENT_KEYS:
            for separator, value in (("=", "S3cr3tVal"), (":", "Tr0ub4dor3")):
                with self.subTest(key=key, separator=separator):
                    self.assert_exact(f"set {key}{separator}{value} and go", f"set {key}{separator}[masked:token] and go")

    def test_o13_assignment_with_space_after_colon_masks_the_value(self):
        result = self.m("password: hunter2")
        self.assertNotIn("hunter2", result)
        self.assertIn("[masked:token]", result)
        self.assertTrue(result.startswith("password"))

    def test_o13_words_that_are_not_assignments_stay(self):
        for text in ("reset your password soon", "the token count is 5", "keep the secret safe"):
            with self.subTest(text=text):
                self.assertEqual(self.m(text), text)

    def test_o13_sk_boundary_19_vs_20_characters(self):
        self.assertEqual(self.m("sk-" + "abcdefghijklmnopqrs"), "sk-abcdefghijklmnopqrs")
        self.assert_exact("sk-" + "abcdefghijklmnopqrst", "[masked:token]")
        self.assert_exact("see sk-" + "abcdefghijklmnopqrstu now", "see [masked:token] now")

    def test_o13_aiza_boundary_35_characters(self):
        self.assertEqual(self.m("AIza" + "a" * 34), "AIza" + "a" * 34)
        self.assert_exact("AIza" + "a" * 35, "[masked:token]")

    def test_o13_akia_boundary_16_characters(self):
        self.assertEqual(self.m("AKIA" + "A" * 15), "AKIA" + "A" * 15)
        self.assert_exact("AKIA" + "A" * 16, "[masked:token]")

    def test_o13_prefix_inside_a_word_is_not_a_token(self):
        for text in ("task-runner-abcdefghijklmnopqrstuv", "xAKIAIOSFODNN7ABCDEFG", "xghp_" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8",
                     "axoxb-" + "1234567890-0987654321098-AbCdEfGhIjKlMnOpQrStUvWx", "xAIza" + "a" * 35,
                     "xgithub_pat_" + "11ABCDEFG0abcdefghijkl_abcdefghijklmnopqrstuvwxyz0123456789"):
            with self.subTest(text=text[:30]):
                self.assertEqual(self.m(text), text)

    def test_o13_prefix_after_a_non_alphanumeric_character_is_a_token(self):
        self.assert_exact("my-sk-abcdefghijklmnopqrstuvwx", "my-[masked:token]")
        self.assert_exact("id:AKIAIOSFODNN7ABCDEFG", "id:[masked:token]")

    def test_o13_c24_prompt_example(self):
        text = "use sk-ant-api03-abcdefghijklmnopqrstuvwx and ghp_" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8" + " with password=hunter2 now"
        self.assert_exact(text, "use [masked:token] and [masked:token] with password=[masked:token] now")


class TestMaskPersonalData(MaskCase):

    def test_o13_c27_each_category_replaced(self):
        for text, expected in (("alice@acme.io", "[masked:email]"), ("10.0.0.5", "[masked:ip]"),
                               ("build01.corp", "[masked:host]"), ("fe80::1", "[masked:ip]")):
            with self.subTest(text=text):
                self.assert_exact(text, expected)
        self.assert_exact("alice@acme.io 10.0.0.5 build01.corp fe80::1", "[masked:email] [masked:ip] [masked:host] [masked:ip]")

    def test_o13_emails(self):
        for email in EMAILS:
            with self.subTest(email=email):
                self.assert_exact(f"mail {email} now", "mail [masked:email] now")

    def test_o13_email_exceptions_are_unchanged(self):
        for email in EMAIL_EXCEPTIONS:
            with self.subTest(email=email):
                self.assertEqual(self.m(f"mail {email} now"), f"mail {email} now")

    def test_o13_email_on_an_internal_host_is_one_email_placeholder(self):
        self.assert_exact("ops@build01.corp", "[masked:email]")

    def test_o13_ip_addresses(self):
        for ip in IPV4 + IPV6:
            with self.subTest(ip=ip):
                self.assert_exact(f"at {ip} now", "at [masked:ip] now")
        self.assert_exact("(10.0.0.5)", "([masked:ip])")

    def test_o13_ipv4_octet_boundary_255_vs_256(self):
        self.assert_exact("ip 10.0.0.255 up", "ip [masked:ip] up")
        self.assertEqual(self.m("ip 10.0.0.256 up"), "ip 10.0.0.256 up")
        self.assertEqual(self.m("300.1.1.1"), "300.1.1.1")

    def test_o13_loopback_boundary_126_127_128(self):
        self.assert_exact("126.1.1.1", "[masked:ip]")
        self.assertEqual(self.m("127.1.1.1"), "127.1.1.1")
        self.assert_exact("128.1.1.1", "[masked:ip]")

    def test_o13_ip_exceptions_are_unchanged(self):
        for ip in IP_EXCEPTIONS:
            with self.subTest(ip=ip):
                self.assertEqual(self.m(f"at {ip} now"), f"at {ip} now")

    def test_o13_values_that_only_look_like_addresses_are_unchanged(self):
        for text in ("version 1.2.3", "std::vector<int>", "at 12:34:56 today", "300.1.1.1"):
            with self.subTest(text=text):
                self.assertEqual(self.m(text), text)

    def test_o13_hosts_for_every_default_suffix(self):
        for suffix, hosts in HOSTS.items():
            for host in hosts:
                with self.subTest(suffix=suffix, host=host):
                    self.assert_exact(f"ssh {host} now", "ssh [masked:host] now")
        self.assert_exact("http://build01.corp:8080/x", "http://[masked:host]:8080/x")

    def test_o13_host_suffix_is_taken_from_the_argument(self):
        self.assertEqual(self.m("ssh build01.corp now", []), "ssh build01.corp now")
        self.assertEqual(self.m("ssh build01.corp now", [".acme"]), "ssh build01.corp now")
        self.assertEqual(self.m("ssh box.acme now", [".acme"]), "ssh [masked:host] now")

    def test_o13_non_matching_hostnames_are_unchanged(self):
        for text in ("see example.com now", "build01.corporate", "it is local", "file.local.txt", "corp"):
            with self.subTest(text=text):
                self.assertEqual(self.m(text), text)

    def test_o13_c28_exception_set_is_unchanged_as_one_text(self):
        text = "dev@example.com 127.0.0.1 ::1 task-runner-abcdefghijklmnopqrstuv version 1.2.3 300.1.1.1"
        self.assertEqual(self.m(text), text)

    def test_o13_c31_already_masked_text_is_unchanged(self):
        text = "[masked:token] [masked:email] [masked:ip] [masked:host] [masked:log 12 lines]"
        self.assertEqual(self.m(text), text)

    def test_o13_plain_and_unicode_text_is_unchanged(self):
        for text in ("", "hello world", "한글 요청: 로그인 기능을 추가해 주세요"):
            self.assertEqual(self.m(text), text)


class TestMaskLogBlocks(MaskCase):

    def test_o13_c25_fenced_block_counts_fence_lines(self):
        block = "```\n" + "\n".join(f"content {n}" for n in range(1, 11)) + "\n```"
        self.assertEqual(len(block.split("\n")), 12)
        self.assert_exact(f"before\n{block}\nafter", "before\n[masked:log 12 lines]\nafter")

    def test_o13_fence_kinds(self):
        for label, block, count in (("language tag", "```python\nx = 1\n```", 3), ("tilde", "~~~\na\nb\n~~~", 4)):
            with self.subTest(fence=label):
                self.assert_exact(f"intro\n{block}\noutro", f"intro\n[masked:log {count} lines]\noutro")

    def test_o13_unterminated_fence_runs_to_the_end(self):
        self.assert_exact("see\n```\nfoo\nbar", "see\n[masked:log 3 lines]")

    def test_o13_c25_timestamp_run_of_five(self):
        run = "\n".join(f"2026-10-28 10:00:0{n} worker {n} started" for n in range(1, 6))
        self.assert_exact(f"intro\n{run}\noutro", "intro\n[masked:log 5 lines]\noutro")

    def test_o13_c26_two_lines_kept_three_masked(self):
        lines = [f"2026-10-28 10:00:0{n} worker {n} started" for n in range(1, 4)]
        two = "\n".join(lines[:2])
        self.assertEqual(self.m(f"intro\n{two}\noutro"), f"intro\n{two}\noutro")
        self.assert_exact("intro\n" + "\n".join(lines) + "\noutro", "intro\n[masked:log 3 lines]\noutro")

    def test_o13_run_broken_by_an_ordinary_line_is_not_a_run(self):
        ts = "2026-10-28 10:00:01 worker started"
        text = f"{ts}\n{ts}\nplain words\n{ts}\n{ts}"
        self.assertEqual(self.m(text), text)

    def test_o13_line_kinds_time_level_bracket_indent_and_mixed(self):
        cases = {
            "time": "\n".join(f"10:00:0{n} worker {n}" for n in range(1, 4)),
            "bracketed date-time": "\n".join(f"[2026-10-28T10:00:0{n}Z] worker {n}" for n in range(1, 4)),
            "indented": "\n".join(f"    2026-10-28 10:00:0{n} worker {n}" for n in range(1, 4)),
            "mixed kinds": "2026-10-28 10:00:01 a\n10:00:02 b\nINFO c",
        }
        for label, run in cases.items():
            with self.subTest(kind=label):
                self.assert_exact(f"intro\n{run}\noutro", "intro\n[masked:log 3 lines]\noutro")

    def test_o13_every_level_word_starts_a_log_line(self):
        for level in ("TRACE", "DEBUG", "INFO", "WARN", "WARNING", "ERROR", "FATAL", "CRITICAL"):
            with self.subTest(level=level):
                run = "\n".join(f"{level}: step {n}" for n in range(1, 4))
                self.assert_exact(f"intro\n{run}\noutro", "intro\n[masked:log 3 lines]\noutro")

    def test_o13_level_word_followed_by_a_letter_is_not_a_log_line(self):
        for word in ("INFORMATION", "ERRORS", "DEBUGGING"):
            with self.subTest(word=word):
                text = "\n".join(f"{word} item {n}" for n in range(1, 4))
                self.assertEqual(self.m(text), text)

    def test_o13_traceback_through_the_exception_line(self):
        trace = ('Traceback (most recent call last):\n  File "a.py", line 3, in f\n    g()\n'
                 '  File "b.py", line 7, in g\n    raise ValueError("x")\nValueError: x')
        self.assertEqual(len(trace.split("\n")), 6)
        self.assert_exact(f"ok\n{trace}\nnext", "ok\n[masked:log 6 lines]\nnext")

    def test_o13_traceback_with_bare_exception_name_and_no_colon(self):
        trace = 'Traceback (most recent call last):\n  File "a.py", line 3, in <module>\n    run()\nKeyboardInterrupt'
        self.assertEqual(len(trace.split("\n")), 4)
        self.assert_exact(f"start\n{trace}\nstill kept text", "start\n[masked:log 4 lines]\nstill kept text")

    def test_o13_traceback_at_the_very_end_of_the_text(self):
        trace = ('Traceback (most recent call last):\n  File "b.py", line 9, in main\n    go()\n'
                 '  File "c.py", line 2, in go\n    raise KeyError("k")\nKeyError: \'k\'')
        self.assertEqual(len(trace.split("\n")), 6)
        self.assert_exact(f"it failed:\n{trace}", "it failed:\n[masked:log 6 lines]")
        self.assert_exact(trace, "[masked:log 6 lines]")

    def test_o13_traceback_followed_by_ordinary_text_that_is_kept(self):
        trace = 'Traceback (most recent call last):\n  File "d.py", line 1, in <module>\n    x()\nZeroDivisionError: division by zero'
        self.assertEqual(len(trace.split("\n")), 4)
        self.assert_exact(f"{trace}\nPlease explain this, thanks.\nSecond kept line",
                          "[masked:log 4 lines]\nPlease explain this, thanks.\nSecond kept line")

    def test_o13_block_placeholder_replaces_secrets_inside_the_block(self):
        run = "\n".join(f"2026-10-28 10:00:0{n} key AKIAIOSFODNN7ABCDEFG user alice@acme.io" for n in range(1, 4))
        self.assert_exact(run, "[masked:log 3 lines]")
        self.assert_exact("```\nAKIAIOSFODNN7ABCDEFG\nalice@acme.io\n```", "[masked:log 4 lines]")

    def test_o13_text_around_blocks_is_still_masked(self):
        text = "mail alice@acme.io\n```\nx\n```\nip 10.0.0.5"
        self.assert_exact(text, "mail [masked:email]\n[masked:log 3 lines]\nip [masked:ip]")

    def test_o13_c25_prompt_with_both_block_kinds(self):
        fenced = "```\n" + "\n".join(f"content {n}" for n in range(1, 11)) + "\n```"
        run = "\n".join(f"2026-10-28 10:00:0{n} worker {n} started" for n in range(1, 6))
        self.assert_exact(f"please read\n{fenced}\nand\n{run}\nthanks",
                          "please read\n[masked:log 12 lines]\nand\n[masked:log 5 lines]\nthanks")


class TestMaskProperties(MaskCase):

    def test_o13_q7_no_sample_survives_masking(self):
        survivors = []
        for category, sample, placeholder in self.all_samples():
            result = self.m(f"context {sample} end")
            if sample in result or placeholder not in result:
                survivors.append((category, sample[:30]))
        self.assertEqual(survivors, [])

    def test_o13_masking_is_idempotent_over_every_sample_and_a_mixed_text(self):
        mixed = []
        for category, sample, _ in self.all_samples():
            once = self.m(f"context {sample} end")
            self.assertEqual(self.m(once), once, category)
            mixed.append(sample)
        text = "\n".join(mixed) + "\n```\nx\n```\nTraceback (most recent call last):\n  File \"a\", line 1\nBoom: x\n"
        once = self.m(text)
        self.assertEqual(self.m(once), once)

    def test_o13_unmasked_reports_line_and_category_for_categories_2_to_5(self):
        cases = (("token", "AKIAIOSFODNN7ABCDEFG"), ("token", "password=hunter2"), ("email", "alice@acme.io"),
                 ("ip", "10.0.0.5"), ("ip", "fe80::1"), ("host", "build01.corp"))
        for category, sample in cases:
            with self.subTest(category=category, sample=sample):
                text = f"first line\nsecond {sample} tail\nthird line"
                self.assertEqual(self.p.unmasked(text, SUFFIXES), [(2, category)])

    def test_o13_unmasked_reports_nothing_for_exceptions_and_masked_text(self):
        clean = ("dev@example.com\n127.0.0.1\n::1\ntask-runner-abcdefghijklmnopqrstuv\nversion 1.2.3\n300.1.1.1\n"
                 "[masked:token] [masked:email] [masked:ip] [masked:host] [masked:log 12 lines]")
        self.assertEqual(self.p.unmasked(clean, SUFFIXES), [])

    def test_o13_unmasked_lines_are_one_based_across_categories_and_use_the_suffix_argument(self):
        text = "a\nb@acme.io\nc\n10.1.1.1\nd.corp"
        self.assertEqual(sorted(self.p.unmasked(text, SUFFIXES)), [(2, "email"), (4, "ip"), (5, "host")])
        self.assertEqual(self.p.unmasked("x.acme", [".acme"]), [(1, "host")])
        self.assertEqual(self.p.unmasked("x.acme", SUFFIXES), [])

    def test_o13_unmasked_does_not_apply_the_log_block_rule(self):
        run = "\n".join(f"2026-10-28 10:00:0{n} worker {n} started" for n in range(1, 4))
        self.assertEqual(self.p.unmasked(run, SUFFIXES), [])
        self.assertEqual(self.p.unmasked("```\nAKIAIOSFODNN7ABCDEFG\n```", SUFFIXES), [(2, "token")])

    def test_o11_q9_mask_of_100_kb_mixed_input_is_fast(self):
        unit = "\n".join([
            "please look at build01.corp and mail alice@acme.io about 10.0.0.5 and fe80::1",
            "token AKIAIOSFODNN7ABCDEFG with password=hunter2 and sk-ant-api03-abcdefghijklmnopqrstuvwx",
            "Authorization: Bearer abcdefghijklmnop1234 ghp_" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8",
            "```\n" + "\n".join(f"content {n}" for n in range(1, 11)) + "\n```",
            "Traceback (most recent call last):\n  File \"a.py\", line 3, in f\n    g()\nValueError: x",
            "\n".join(f"2026-10-28 10:00:0{n} worker {n} started" for n in range(1, 6)),
            "\n".join(f"ERROR: step {n} failed" for n in range(1, 4)),
            "dev@example.com 127.0.0.1 version 1.2.3 plain sentence without any secrets in it",
        ]) + "\n"
        text = unit * (100 * 1024 // len(unit.encode()) + 1)
        self.assertGreaterEqual(len(text.encode()), 100 * 1024)
        started = time.perf_counter()
        result = self.m(text)
        elapsed = time.perf_counter() - started
        self.assertLessEqual(elapsed, 0.2, f"mask took {elapsed:.3f}s")
        for secret in ("AKIAIOSFODNN7ABCDEFG", "alice@acme.io", "10.0.0.5", "build01.corp", "hunter2"):
            self.assertNotIn(secret, result)


class TestHookTiming(ProgressCase):

    def build_history(self, repo, count):
        base, branch = self.head(repo), self.branch(repo)
        stream = []
        for i in range(count):
            message, content = f"c{i}", f"v = {i}\n"
            stream.append(
                f"commit refs/heads/{branch}\ncommitter t <t@t.com> {1700000000 + i} +0000\n"
                f"data {len(message)}\n{message}\n" + (f"from {base}\n" if i == 0 else "")
                + f"M 100644 inline src/f{i % 20}.py\ndata {len(content)}\n{content}\n"
            )
        subprocess.run(["git", "-C", str(repo), "fast-import", "--quiet"], input="".join(stream), text=True, check=True)
        run_git(repo, "reset", "-q", "--hard", branch)

    def test_o11_q1_post_tool_use_on_40_by_40_entries_over_1000_commits_takes_at_most_two_seconds(self):
        repo = self.new_repo()
        self.build_history(repo, 1000)
        shas = run_git(repo, "rev-list", "--reverse", "HEAD").stdout.split()
        self.assertGreaterEqual(len(shas), 1000)
        old_entries = [(f"step {i:02d}: check module m{i} handles edge {i * 5 % 11} under config {i}", shas[40 + i * 3], f"src/f{i % 20}.py")
                       for i in range(40)]
        new_entries = [(f"step {i:02d}: verify module m{i} handles case {i * 7 % 13} with config {i}", shas[60 + i * 4], f"src/f{(i + 3) % 20}.py")
                       for i in range(40)]
        old = self.put(repo, NAME1, build(session="sessb", stamp=self.head(repo), next_step=old_entries), directory="progress-logs")
        new = self.put(repo, NAME2, build(session="sessa", stamp=self.head(repo), before=self.rel(repo, old), next_step=new_entries))
        self.add_marker(repo, os.getpid())

        started = time.perf_counter()
        result = self.post(repo, new)
        elapsed = time.perf_counter() - started

        self.assertLessEqual(elapsed, 2.0, f"hook took {elapsed:.2f}s")
        self.assertEqual(result.returncode, 2, out(result))
        self.assertIn("stale", result.stderr)
        self.assertNotIn("Traceback", result.stderr)


if __name__ == "__main__":
    unittest.main()

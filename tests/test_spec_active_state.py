import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from test_installer import REPO_ROOT, InstallerTestCase, run_git, run_installer
from text_checks import text_test

TESTS_DIR = Path(__file__).resolve().parent
SPECS = "agent-docs/specs"
LOGS = "agent-docs/spec-logs"
RESTORE = "python3 .harness/bin/seed.py restore"
FLAG = "--other-sessions-confirmed"
NOTICE_PREFIX = "spec lifecycle: "
ID_A = "aaaaaaaaaaaaaaaa"
ID_B = "bbbbbbbbbbbbbbbb"
ID_C = "cccccccccccccccc"
BASE_X = "abc123def4567890abc123def4567890abc123de"


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class SpecCase(InstallerTestCase):
    template = None

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        tmp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(tmp.cleanup)
        cls.template = Path(tmp.name) / "template"
        cls.template.mkdir()
        run_git(cls.template, "init", "-q")
        run_git(cls.template, "config", "user.email", "test@test.com")
        run_git(cls.template, "config", "user.name", "test")
        result = run_installer("install", str(cls.template), "--no-ci")
        if result.returncode != 0:
            raise RuntimeError(result.stdout + result.stderr)

    def setUp(self):
        self.repo = self.fresh_repo()
        self.specs = self.repo / "agent-docs" / "specs"
        self.logs = self.repo / "agent-docs" / "spec-logs"
        self.running_dir = self.repo / ".harness" / "sessions" / ".running"
        shutil.rmtree(self.running_dir, ignore_errors=True)

    def fresh_repo(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        repo = Path(tmp.name) / "repo"
        shutil.copytree(self.template, repo, symlinks=True)
        return repo

    def env(self, session=None):
        env = dict(os.environ)
        env.pop("CLAUDE_CODE_SESSION_ID", None)
        env.pop("CLAUDE_SESSION_ID", None)
        if session is not None:
            env["CLAUDE_CODE_SESSION_ID"] = session
        return env

    def lc(self, *args, session=None, repo=None):
        repo = repo or self.repo
        return subprocess.run(
            [sys.executable, str(repo / ".harness" / "bin" / "spec_lifecycle.py"), *args],
            cwd=repo, capture_output=True, text=True, errors="replace", env=self.env(session),
        )

    def hook_start(self, payload=None, repo=None, session=None):
        repo = repo or self.repo
        payload = {"hook_event_name": "SessionStart", "session_id": "sess-hook", "source": "startup",
                   "cwd": str(repo)} if payload is None else payload
        return subprocess.run(
            [sys.executable, str(repo / ".harness" / "hooks" / "progress_hook.py")],
            input=json.dumps(payload), cwd=repo, capture_output=True, text=True, errors="replace",
            env=self.env(session),
        )

    def mk(self, status="active", run_id=ID_A, name="change"):
        return self.write_valid_spec(self.repo, run_id, name, status)

    def raw(self, name, status, base=None, repo=None):
        path = (repo or self.repo) / "agent-docs" / "specs" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        base_line = f"base_commit: {base}\n" if base else ""
        path.write_text(f"---\nstatus: {status}\n{base_line}---\n\n# Body\n")
        return path

    def start(self, spec, run_id=ID_A, *extra, session=None):
        return self.lc("start", "--spec", str(spec), "--run-id", run_id, *extra, session=session)

    def archive(self, spec, status, *extra, session=None):
        return self.lc("archive", "--spec", str(spec), "--status", status, *extra, session=session)

    def abort(self, spec, *extra, session=None):
        return self.lc("abort", "--spec", str(spec), *extra, session=session)

    def seed(self, rel="src/app.py", repo=None):
        path = (repo or self.repo) / "agent-docs" / "specs" / ".seed" / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("backup\n")
        return path

    def log_names(self):
        return sorted(p.name for p in self.logs.iterdir()) if self.logs.is_dir() else []

    def live_process(self):
        proc = subprocess.Popen(["sleep", "60"])

        def cleanup():
            proc.kill()
            proc.wait()

        self.addCleanup(cleanup)
        return proc.pid

    def dead_pid(self):
        proc = subprocess.Popen([sys.executable, "-c", "pass"])
        proc.wait()
        return proc.pid

    def marker(self, name, session_id=None, content=None, repo=None):
        directory = (repo or self.repo) / ".harness" / "sessions" / ".running"
        directory.mkdir(parents=True, exist_ok=True)
        if content is None:
            body = {"source": "startup"}
            if session_id is not None:
                body["session_id"] = session_id
            content = json.dumps(body)
        target = directory / str(name)
        if isinstance(content, bytes):
            target.write_bytes(content)
        else:
            target.write_text(content)

    def assert_refused(self, result, *needles, absent=()):
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertNotIn("Traceback", result.stderr)
        for needle in needles:
            self.assertIn(needle, result.stderr)
        for needle in absent:
            self.assertNotIn(needle, result.stderr)

    def assert_ok(self, result):
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def assert_untouched(self, spec, before):
        self.assertEqual(sha(spec), before)
        self.assertEqual(self.log_names(), [])


class TestStart(SpecCase):
    def test_valid_sole_spec_starts_and_leaves_no_active_file(self):
        spec = self.mk()
        self.assert_ok(self.start(spec))
        self.assertFalse((self.specs / ".active").exists())

    def test_rerun_on_the_same_active_spec_succeeds(self):
        spec = self.mk()
        self.assert_ok(self.start(spec))
        self.assert_ok(self.start(spec))

    def test_rerun_with_resume_on_the_same_active_spec_succeeds(self):
        spec = self.mk()
        self.assert_ok(self.start(spec))
        self.assert_ok(self.start(spec, ID_A, "--resume"))

    def test_other_active_spec_refuses_and_names_it(self):
        first = self.mk(name="first")
        self.assert_ok(self.start(first))
        second = self.mk(run_id=ID_B, name="second")
        before = sha(second)
        result = self.start(second, ID_B)
        self.assert_refused(result, "another workflow is active", first.name)
        self.assertEqual(sha(second), before)
        self.assertFalse((self.specs / ".active").exists())

    def test_other_draft_spec_refuses_and_names_it(self):
        draft = self.mk(status="draft", name="drafty")
        second = self.mk(run_id=ID_B, name="second")
        self.assert_refused(self.start(second, ID_B), "another workflow is active", draft.name)

    def test_other_terminal_spec_does_not_block(self):
        self.mk(status="complete", run_id=ID_A, name="done")
        second = self.mk(run_id=ID_B, name="second")
        self.assert_ok(self.start(second, ID_B))

    def test_invalid_spec_is_refused_with_the_validation_message(self):
        spec = self.mk()
        spec.write_text(spec.read_text().replace("| Safety | no | not affected |\n", ""))
        self.assert_refused(self.start(spec), "invalid spec: ", "safety")

    def test_status_draft_is_refused_with_the_status_message(self):
        spec = self.mk(status="draft")
        self.assert_refused(self.start(spec), "start requires spec status active")

    def test_run_id_mismatch_is_refused_with_the_run_id_message(self):
        spec = self.mk()
        self.assert_refused(self.start(spec, ID_B), "--run-id does not match spec frontmatter",
                            absent=("start requires spec status active",))

    def test_check_order_status_precedes_run_id_by_message(self):
        spec = self.mk(status="draft")
        self.assert_refused(self.start(spec, ID_B), "start requires spec status active",
                            absent=("--run-id does not match spec frontmatter",))

    def test_two_other_workflow_specs_are_both_named(self):
        other_b = self.mk(status="active", run_id=ID_B, name="second")
        other_c = self.mk(status="draft", run_id=ID_C, name="third")
        spec = self.mk()
        self.assert_refused(self.start(spec), "another workflow is active", other_b.name, other_c.name)

    def test_check_order_status_precedes_run_id_and_seed_and_other_spec(self):
        self.seed()
        other = self.mk(name="other")
        draft = self.mk(status="draft", run_id=ID_B, name="drafty")
        result = self.start(draft, ID_C)
        self.assert_refused(result, absent=("unrestored seed backup", "another workflow is active"))
        self.assertTrue(other.exists())

    def test_check_order_run_id_precedes_seed(self):
        self.seed()
        spec = self.mk()
        self.assert_refused(self.start(spec, ID_B), absent=("unrestored seed backup",))

    def test_check_order_validation_precedes_status(self):
        spec = self.mk(status="draft")
        spec.write_text(spec.read_text().replace("| Safety | no | not affected |\n", ""))
        self.assert_refused(self.start(spec), "safety")


class TestStartWithSeed(SpecCase):
    def test_seed_only_refuses_with_restore_command(self):
        spec = self.mk()
        self.seed()
        before = sha(spec)
        self.assert_refused(self.start(spec), "unrestored seed backup", RESTORE)
        self.assertEqual(sha(spec), before)

    def test_seed_with_other_active_reports_the_seed_first(self):
        first = self.mk(name="first")
        second = self.mk(run_id=ID_B, name="second")
        self.seed()
        result = self.start(second, ID_B)
        self.assert_refused(result, "unrestored seed backup", RESTORE, absent=("another workflow is active",))
        self.assertTrue(first.exists())

    def test_seed_refusal_applies_with_resume_flag_too(self):
        spec = self.mk()
        self.seed()
        self.assert_refused(self.start(spec, ID_A, "--resume"), "unrestored seed backup")


class TestStartAfterOutOfBandChanges(SpecCase):
    def test_start_after_spec_was_moved_to_spec_logs(self):
        first = self.mk(name="first")
        self.assert_ok(self.start(first))
        self.logs.mkdir(parents=True)
        shutil.move(str(first), str(self.logs / first.name))
        second = self.mk(run_id=ID_B, name="second")
        self.assert_ok(self.start(second, ID_B))

    def test_start_after_spec_was_renamed_completed_and_archived(self):
        first = self.mk(name="first")
        self.assert_ok(self.start(first))
        renamed = first.with_name(f"{ID_A}-renamed.md")
        first.rename(renamed)
        renamed.write_text(renamed.read_text().replace("status: active", "status: complete"))
        self.assert_ok(self.archive(renamed, "complete"))
        second = self.mk(run_id=ID_B, name="second")
        self.assert_ok(self.start(second, ID_B))

    def test_start_after_spec_was_deleted(self):
        first = self.mk(name="first")
        self.assert_ok(self.start(first))
        first.unlink()
        second = self.mk(run_id=ID_B, name="second")
        self.assert_ok(self.start(second, ID_B))

    def leftover(self, content):
        second = self.mk(run_id=ID_B, name="second")
        active = self.specs / ".active"
        active.write_bytes(content)
        self.assert_ok(self.start(second, ID_B))
        self.assertEqual(active.read_bytes(), content)

    def test_active_file_naming_a_missing_spec_has_no_effect_and_stays(self):
        self.leftover(b"0000000000000000-gone.md\n")

    def test_active_file_with_a_repo_path_form_has_no_effect_and_stays(self):
        self.leftover(b"agent-docs/specs/0000000000000000-gone.md\n")

    def test_empty_active_file_has_no_effect_and_stays(self):
        self.leftover(b"")

    def test_active_file_naming_the_new_spec_has_no_effect_and_stays(self):
        self.leftover(f"{ID_B}-second.md\n".encode())

    def test_active_file_naming_the_new_spec_by_repo_path_has_no_effect_and_stays(self):
        self.leftover(f"{SPECS}/{ID_B}-second.md\n".encode())


class TestLiveSessionClassification(SpecCase):
    def aborted(self):
        spec = self.mk(status="aborted")
        return spec, sha(spec)

    def moved(self, spec):
        self.assertFalse(spec.exists())
        self.assertTrue((self.logs / spec.name).is_file())

    def test_ancestor_pid_marker_without_session_id_is_own(self):
        spec, _ = self.aborted()
        self.marker(os.getpid())
        self.assert_ok(self.archive(spec, "aborted", session="some-other-session"))
        self.moved(spec)

    def test_marker_whose_session_id_equals_the_env_session_is_own(self):
        spec, _ = self.aborted()
        self.marker(self.live_process(), session_id="S1")
        self.assert_ok(self.archive(spec, "aborted", session="S1"))
        self.moved(spec)

    def test_other_live_markers_with_ids_refuse_and_name_every_pid_and_id(self):
        spec, before = self.aborted()
        first, second = self.live_process(), self.live_process()
        self.marker(first, session_id="S2")
        self.marker(second, session_id="S3")
        self.marker(os.getpid(), session_id="S1")
        result = self.archive(spec, "aborted", session="S1")
        self.assert_refused(result, "other harness session", FLAG, str(first), str(second), "S2", "S3")
        self.assertIsNone(re.search(rf"\b{os.getpid()}\b", result.stderr))
        self.assert_untouched(spec, before)

    def test_other_live_marker_without_session_id_refuses_and_names_its_pid(self):
        spec, before = self.aborted()
        pid = self.live_process()
        self.marker(pid)
        result = self.archive(spec, "aborted")
        self.assert_refused(result, "other harness session", str(pid), FLAG)
        self.assert_untouched(spec, before)

    def test_empty_env_session_does_not_match_a_marker_with_empty_session_id(self):
        spec, before = self.aborted()
        pid = self.live_process()
        self.marker(pid, session_id="")
        result = self.archive(spec, "aborted", session="")
        self.assert_refused(result, "other harness session", str(pid))
        self.assert_untouched(spec, before)

    def test_dead_pid_marker_is_ignored(self):
        spec, _ = self.aborted()
        self.marker(self.dead_pid(), session_id="S2")
        self.assert_ok(self.archive(spec, "aborted"))
        self.moved(spec)

    def test_non_numeric_marker_name_is_ignored(self):
        spec, _ = self.aborted()
        self.marker("notapid", session_id="S2")
        self.assert_ok(self.archive(spec, "aborted"))
        self.moved(spec)

    def test_missing_marker_directory_means_no_other_session(self):
        spec, _ = self.aborted()
        self.assertFalse(self.running_dir.exists())
        self.assert_ok(self.archive(spec, "aborted"))
        self.moved(spec)

    def test_mixed_markers_only_the_live_non_own_one_counts(self):
        spec, before = self.aborted()
        dead, live = self.dead_pid(), self.live_process()
        self.marker(dead, session_id="S4")
        self.marker("notapid")
        self.marker(live)
        result = self.archive(spec, "aborted")
        self.assert_refused(result, "other harness session", str(live))
        self.assertIsNone(re.search(rf"\b{dead}\b", result.stderr))
        self.assertNotIn("notapid", result.stderr)
        self.assert_untouched(spec, before)

    def test_markers_inside_subdirectories_are_not_counted(self):
        spec, _ = self.aborted()
        nested = self.running_dir / "sub"
        nested.mkdir(parents=True)
        (nested / str(self.live_process())).write_text(json.dumps({"session_id": "S9"}))
        self.assert_ok(self.archive(spec, "aborted"))


class TestArchive(SpecCase):
    def test_complete_spec_moves_byte_identical_and_prints_destination(self):
        spec = self.mk(status="complete")
        expected = spec.read_bytes()
        result = self.archive(spec, "complete")
        self.assert_ok(result)
        self.assertFalse(spec.exists())
        self.assertEqual((self.logs / spec.name).read_bytes(), expected)
        self.assertIn(f"{LOGS}/{spec.name}", result.stdout)

    def test_limit_spec_moves_byte_identical(self):
        spec = self.mk(status="limit")
        expected = spec.read_bytes()
        self.assert_ok(self.archive(spec, "limit"))
        self.assertEqual((self.logs / spec.name).read_bytes(), expected)

    def test_aborted_with_other_live_session_refuses_then_flag_moves_it(self):
        spec = self.mk(status="aborted")
        before = sha(spec)
        pid = self.live_process()
        self.marker(pid, session_id="S2")
        refused = self.archive(spec, "aborted", session="S1")
        self.assert_refused(refused, "other harness session", str(pid), "S2", FLAG)
        self.assert_untouched(spec, before)
        expected = spec.read_bytes()
        result = self.archive(spec, "aborted", FLAG, session="S1")
        self.assert_ok(result)
        self.assertEqual((self.logs / spec.name).read_bytes(), expected)
        self.assertIn(f"{LOGS}/{spec.name}", result.stdout)

    def test_complete_and_limit_ignore_live_sessions(self):
        self.marker(self.live_process(), session_id="S2")
        for status, run_id in (("complete", ID_A), ("limit", ID_B)):
            with self.subTest(status=status):
                spec = self.mk(status=status, run_id=run_id, name=status)
                self.assert_ok(self.archive(spec, status, session="S1"))
                self.assertTrue((self.logs / spec.name).is_file())

    def test_seed_refuses_with_restore_command_and_keeps_spec(self):
        spec = self.mk(status="complete")
        before = sha(spec)
        self.seed()
        self.assert_refused(self.archive(spec, "complete"), "unrestored seed backup", RESTORE)
        self.assert_untouched(spec, before)

    def test_status_mismatch_refuses(self):
        for actual, asked in (("active", "complete"), ("complete", "limit"), ("complete", "aborted")):
            with self.subTest(actual=actual, asked=asked):
                spec = self.mk(status=actual, name=f"{actual}-{asked}")
                before = sha(spec)
                self.assert_refused(self.archive(spec, asked))
                self.assert_untouched(spec, before)

    def test_path_outside_specs_or_in_a_subdirectory_refuses(self):
        for rel in ("notes/x.md", "agent-docs/specs/sub/x.md", "agent-docs/spec-logs/x.md"):
            with self.subTest(rel=rel):
                path = self.repo / rel
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("---\nstatus: complete\n---\n")
                before = sha(path)
                self.assert_refused(self.archive(path, "complete"))
                self.assertEqual(sha(path), before)

    def test_destination_exists_refuses_and_keeps_both_files(self):
        spec = self.mk(status="complete")
        self.logs.mkdir(parents=True)
        dest = self.logs / spec.name
        dest.write_text("older\n")
        before = sha(spec)
        self.assert_refused(self.archive(spec, "complete"), "archive destination already exists")
        self.assertEqual(sha(spec), before)
        self.assertEqual(dest.read_text(), "older\n")

    def test_order_seed_precedes_status_mismatch(self):
        spec = self.mk(status="active")
        self.seed()
        self.assert_refused(self.archive(spec, "complete"), "unrestored seed backup")

    def test_order_status_mismatch_precedes_live_check(self):
        spec = self.mk(status="active")
        self.marker(self.live_process())
        before = sha(spec)
        self.assert_refused(self.archive(spec, "aborted"), absent=("other harness session",))
        self.assert_untouched(spec, before)

    def test_order_live_check_precedes_destination_exists(self):
        spec = self.mk(status="aborted")
        self.logs.mkdir(parents=True)
        (self.logs / spec.name).write_text("older\n")
        self.marker(self.live_process())
        self.assert_refused(self.archive(spec, "aborted"), "other harness session",
                            absent=("archive destination already exists",))


class TestAbort(SpecCase):
    def only_status_changed(self, original, status_before, dest):
        expected = original.replace(f"\nstatus: {status_before}\n".encode(), b"\nstatus: aborted\n", 1)
        self.assertNotEqual(expected, original)
        self.assertEqual(dest.read_bytes(), expected)

    def test_active_spec_is_aborted_and_moved_changing_only_the_status_value(self):
        spec = self.mk(status="active")
        original = spec.read_bytes()
        result = self.abort(spec)
        self.assert_ok(result)
        self.assertFalse(spec.exists())
        self.only_status_changed(original, "active", self.logs / spec.name)
        self.assertIn(f"{LOGS}/{spec.name}", result.stdout)

    def test_draft_spec_is_aborted_and_moved(self):
        spec = self.mk(status="draft")
        original = spec.read_bytes()
        self.assert_ok(self.abort(spec))
        self.assertFalse(spec.exists())
        self.only_status_changed(original, "draft", self.logs / spec.name)

    def test_already_aborted_spec_moves_byte_identical(self):
        spec = self.mk(status="aborted")
        original = spec.read_bytes()
        result = self.abort(spec)
        self.assert_ok(result)
        self.assertEqual((self.logs / spec.name).read_bytes(), original)
        self.assertIn(f"{LOGS}/{spec.name}", result.stdout)

    def test_complete_and_limit_specs_are_refused_with_use_archive(self):
        for status in ("complete", "limit"):
            with self.subTest(status=status):
                spec = self.mk(status=status, name=status)
                before = sha(spec)
                self.assert_refused(self.abort(spec), "use archive")
                self.assert_untouched(spec, before)

    def test_seed_refuses_with_restore_command(self):
        spec = self.mk()
        before = sha(spec)
        self.seed()
        self.assert_refused(self.abort(spec), "unrestored seed backup", RESTORE)
        self.assert_untouched(spec, before)

    def test_other_live_session_refuses_without_flag_and_moves_with_it(self):
        spec = self.mk()
        before = sha(spec)
        original = spec.read_bytes()
        pid = self.live_process()
        self.marker(pid, session_id="S2")
        refused = self.abort(spec, session="S1")
        self.assert_refused(refused, "other harness session", str(pid), "S2", FLAG)
        self.assert_untouched(spec, before)
        self.assert_ok(self.abort(spec, FLAG, session="S1"))
        self.assertFalse(spec.exists())
        self.only_status_changed(original, "active", self.logs / spec.name)

    def test_own_session_marker_does_not_block(self):
        spec = self.mk()
        self.marker(os.getpid())
        self.assert_ok(self.abort(spec))

    def test_destination_exists_refuses_and_keeps_original_status(self):
        spec = self.mk()
        self.logs.mkdir(parents=True)
        dest = self.logs / spec.name
        dest.write_text("older\n")
        before = sha(spec)
        self.assert_refused(self.abort(spec), "archive destination already exists")
        self.assertEqual(sha(spec), before)
        self.assertIn(b"\nstatus: active\n", spec.read_bytes())
        self.assertEqual(dest.read_text(), "older\n")

    def test_path_outside_specs_nonexistent_or_in_subdirectory_is_refused(self):
        outside = self.repo / "notes" / "x.md"
        outside.parent.mkdir()
        outside.write_text("---\nstatus: active\n---\n")
        sub = self.specs / "sub" / "x.md"
        sub.parent.mkdir(parents=True)
        sub.write_text("---\nstatus: active\n---\n")
        for label, path in (("outside", outside), ("nonexistent", self.specs / "0000000000000000-none.md"),
                            ("subdirectory", sub)):
            with self.subTest(case=label):
                before = sha(path) if path.exists() else None
                self.assert_refused(self.abort(path), "agent-docs/specs")
                if before:
                    self.assertEqual(sha(path), before)
                self.assertEqual(self.log_names(), [])

    def test_spec_without_frontmatter_or_without_status_is_refused(self):
        for label, content in (("no-frontmatter", "# Just a heading\nstatus: active\n"),
                               ("no-status", "---\nrun_id: 1\n---\n\nbody\n")):
            with self.subTest(case=label):
                path = self.specs / f"{label}.md"
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content)
                before = sha(path)
                self.assert_refused(self.abort(path), "frontmatter")
                self.assert_untouched(path, before)

    def test_order_status_precedes_seed(self):
        spec = self.mk(status="complete")
        self.seed()
        before = sha(spec)
        self.assert_refused(self.abort(spec), "use archive", absent=("unrestored seed backup",))
        self.assert_untouched(spec, before)

    def test_order_seed_precedes_live_session(self):
        spec = self.mk()
        self.seed()
        self.marker(self.live_process())
        before = sha(spec)
        self.assert_refused(self.abort(spec), "unrestored seed backup", absent=("other harness session",))
        self.assert_untouched(spec, before)

    def test_order_live_session_precedes_destination_exists(self):
        spec = self.mk()
        self.logs.mkdir(parents=True)
        (self.logs / spec.name).write_text("older\n")
        self.marker(self.live_process())
        before = sha(spec)
        self.assert_refused(self.abort(spec), "other harness session",
                            absent=("archive destination already exists",))
        self.assertEqual(sha(spec), before)


class TestActiveFileIsIgnoredByOtherSubcommands(SpecCase):
    def stale(self):
        content = b"0000000000000000-gone.md\n"
        (self.specs / ".active").write_bytes(content)
        return content

    def test_archive_abort_session_and_notice_neither_read_nor_delete_it(self):
        self.specs.mkdir(parents=True, exist_ok=True)
        content = self.stale()
        notice = self.lc("notice")
        self.assert_ok(notice)
        self.assertEqual(notice.stdout, "")
        done = self.mk(status="complete", name="done")
        self.assert_ok(self.archive(done, "complete"))
        gone = self.mk(status="active", run_id=ID_B, name="gone")
        self.assert_ok(self.abort(gone))
        self.raw(f"{ID_C}-late.md", "complete")
        self.assert_ok(self.lc("session"))
        self.assertEqual((self.specs / ".active").read_bytes(), content)


class TestSession(SpecCase):
    def test_complete_spec_is_archived(self):
        spec = self.raw(f"{ID_A}-done.md", "complete")
        self.assert_ok(self.lc("session"))
        self.assertFalse(spec.exists())
        self.assertTrue((self.logs / spec.name).is_file())

    def test_aborted_spec_with_other_live_session_stays_and_complete_one_is_archived(self):
        aborted = self.raw(f"{ID_A}-aborted.md", "aborted")
        done = self.raw(f"{ID_B}-done.md", "complete")
        self.marker(self.live_process(), session_id="S2")
        result = self.lc("session", session="S1")
        self.assert_ok(result)
        self.assertTrue(aborted.is_file())
        self.assertFalse(done.exists())
        self.assertTrue((self.logs / done.name).is_file())
        self.assertFalse((self.logs / aborted.name).exists())
        self.assertIn(aborted.name, result.stderr)

    def test_aborted_spec_without_other_live_session_is_archived(self):
        aborted = self.raw(f"{ID_A}-aborted.md", "aborted")
        self.assert_ok(self.lc("session"))
        self.assertFalse(aborted.exists())
        self.assertTrue((self.logs / aborted.name).is_file())

    def test_seed_present_archives_nothing(self):
        spec = self.raw(f"{ID_A}-done.md", "complete")
        self.seed()
        result = self.lc("session")
        self.assert_ok(result)
        self.assertTrue(spec.is_file())
        self.assertEqual(self.log_names(), [])
        self.assertIn("seed.py restore", result.stderr)

    def test_draft_and_active_specs_stay_and_print_the_resume_hint(self):
        for status in ("draft", "active"):
            with self.subTest(status=status):
                spec = self.raw(f"{ID_A}-{status}.md", status, base="deadbeef")
                result = self.lc("session")
                self.assert_ok(result)
                self.assertTrue(spec.is_file())
                self.assertIn("/continue-on", result.stderr)
                spec.unlink()


def lines_of(text):
    return text.splitlines()


class NoticeCase(SpecCase):
    def notice(self, **kw):
        result = self.lc("notice", **kw)
        self.assert_ok(result)
        return result

    def only_line(self, lines, needle):
        hits = [i for i, line in enumerate(lines) if needle in line]
        self.assertEqual(len(hits), 1, (needle, lines))
        return hits[0]

    def build_n1(self, repo):
        self.seed("src/app.py", repo=repo)
        self.seed("manifest.json", repo=repo)
        self.seed("manifest.json.tmp", repo=repo)

    def build_n2(self, repo):
        self.raw(f"{ID_A}-alpha.md", "active", base=BASE_X, repo=repo)
        self.raw(f"{ID_B}-beta.md", "draft", repo=repo)

    def build_n3_plain(self, repo):
        self.raw(f"{ID_A}-cplt.md", "complete", repo=repo)
        self.raw(f"{ID_B}-lmt.md", "limit", repo=repo)
        self.raw(f"{ID_C}-abrt.md", "aborted", repo=repo)
        logs = repo / "agent-docs" / "spec-logs"
        logs.mkdir(parents=True, exist_ok=True)
        (logs / f"{ID_B}-lmt.md").write_text("already archived\n")

    def build_n4(self, repo):
        running = repo / "agent-docs" / "specs" / ".running"
        running.mkdir(parents=True, exist_ok=True)
        (running / "agent2").write_text("")
        (running / "agent1").write_text("")

    def build_combined(self, repo):
        self.build_n1(repo)
        self.build_n2(repo)
        self.build_n3_plain(repo)
        self.build_n4(repo)

    def states(self):
        def empty(repo):
            (repo / "agent-docs" / "specs").mkdir(parents=True, exist_ok=True)

        def missing(repo):
            shutil.rmtree(repo / "agent-docs" / "specs", ignore_errors=True)

        return (("empty", empty), ("missing", missing), ("n1", self.build_n1), ("n2", self.build_n2),
                ("n3", self.build_n3_plain), ("n4", self.build_n4), ("combined", self.build_combined))


class TestNotice(NoticeCase):
    def test_clean_specs_dir_prints_nothing(self):
        self.specs.mkdir(parents=True, exist_ok=True)
        result = self.notice()
        self.assertEqual((result.stdout, result.returncode), ("", 0))

    def test_missing_specs_dir_prints_nothing(self):
        shutil.rmtree(self.specs, ignore_errors=True)
        result = self.notice()
        self.assertEqual(result.stdout, "")

    def test_seed_line_names_files_but_not_the_manifest_and_gives_the_restore_command(self):
        self.build_n1(self.repo)
        lines = lines_of(self.notice().stdout)
        self.assertEqual(len(lines), 1, lines)
        self.assertTrue(lines[0].startswith(NOTICE_PREFIX))
        self.assertIn("unrestored seed backup", lines[0])
        self.assertIn("src/app.py", lines[0])
        self.assertNotIn("manifest.json", lines[0])
        self.assertIn(RESTORE, lines[0])

    def test_nonterminal_specs_are_listed_sorted_with_status_and_base_commit(self):
        self.build_n2(self.repo)
        lines = lines_of(self.notice().stdout)
        self.assertEqual(len(lines), 2, lines)
        for line in lines:
            self.assertTrue(line.startswith(NOTICE_PREFIX))
        self.assertIn(f"{SPECS}/{ID_A}-alpha.md", lines[0])
        self.assertIn("active", lines[0])
        self.assertIn(BASE_X, lines[0])
        self.assertNotIn("unknown", lines[0])
        self.assertIn(f"{SPECS}/{ID_B}-beta.md", lines[1])
        self.assertIn("draft", lines[1])
        self.assertIn("unknown", lines[1])

    def test_nonterminal_specs_are_sorted_by_name_not_by_status(self):
        self.raw(f"{ID_B}-first.md", "active", base=BASE_X)
        self.raw(f"{ID_A}-second.md", "draft", base=BASE_X)
        lines = lines_of(self.notice().stdout)
        self.assertIn(f"{ID_A}-second.md", lines[0])
        self.assertIn(f"{ID_B}-first.md", lines[1])

    def test_terminal_specs_without_seed_show_destination_or_not_archived_yet(self):
        self.build_n3_plain(self.repo)
        lines = lines_of(self.notice().stdout)
        self.assertEqual(len(lines), 3, lines)
        for line in lines:
            self.assertTrue(line.startswith(NOTICE_PREFIX))
        cplt = lines[self.only_line(lines, f"{SPECS}/{ID_A}-cplt.md")]
        lmt = lines[self.only_line(lines, f"{SPECS}/{ID_B}-lmt.md")]
        abrt = lines[self.only_line(lines, f"{SPECS}/{ID_C}-abrt.md")]
        self.assertIn("complete", cplt)
        self.assertIn("not archived yet", cplt)
        self.assertNotIn(f"{LOGS}/", cplt)
        self.assertIn("limit", lmt)
        self.assertIn(f"{LOGS}/{ID_B}-lmt.md", lmt)
        self.assertNotIn("not archived yet", lmt)
        self.assertIn("aborted", abrt)
        self.assertIn("not archived yet", abrt)
        self.assertNotIn("unrestored seed backup", "".join((cplt, lmt, abrt)))
        self.assertEqual(lines, sorted(lines, key=lambda l: l.split(f"{SPECS}/")[1]))

    def test_terminal_specs_with_seed_all_carry_the_seed_reason_even_when_destination_exists(self):
        self.build_n3_plain(self.repo)
        self.seed()
        lines = lines_of(self.notice().stdout)
        terminal = [l for l in lines if re.search(r"-(cplt|lmt|abrt)\.md", l)]
        self.assertEqual(len(terminal), 3, lines)
        for line in terminal:
            self.assertIn("unrestored seed backup", line)
            self.assertNotIn("not archived yet", line)
            self.assertNotIn(f"{LOGS}/", line)

    def test_running_entries_are_listed_sorted_with_the_delete_advice_on_one_line(self):
        self.build_n4(self.repo)
        lines = lines_of(self.notice().stdout)
        self.assertEqual(len(lines), 1, lines)
        line = lines[0]
        self.assertTrue(line.startswith(NOTICE_PREFIX))
        self.assertIn(f"{SPECS}/.running/agent1", line)
        self.assertIn(f"{SPECS}/.running/agent2", line)
        self.assertLess(line.index("agent1"), line.index("agent2"))
        self.assertIn("delete", line)

    def test_combined_state_orders_seed_nonterminal_terminal_running(self):
        self.build_combined(self.repo)
        lines = lines_of(self.notice().stdout)
        self.assertEqual(len(lines), 1 + 2 + 3 + 1, lines)
        for line in lines:
            self.assertTrue(line.startswith(NOTICE_PREFIX))
        self.assertIn("src/app.py", lines[0])
        self.assertNotIn("manifest.json", lines[0])
        self.assertIn(f"{ID_A}-alpha.md", lines[1])
        self.assertIn(f"{ID_B}-beta.md", lines[2])
        for index, name in ((3, "cplt"), (4, "lmt"), (5, "abrt")):
            self.assertIn(f"-{name}.md", lines[index])
            self.assertIn("unrestored seed backup", lines[index])
        self.assertIn(f"{SPECS}/.running/agent1", lines[6])
        self.assertIn("delete", lines[6])

    def test_non_markdown_and_nested_files_in_specs_are_not_listed(self):
        self.raw(f"{ID_A}-alpha.md", "active", base=BASE_X)
        (self.specs / "notes.txt").write_text("status: active\n")
        nested = self.specs / "sub"
        nested.mkdir()
        (nested / "x.md").write_text("---\nstatus: active\n---\n")
        lines = lines_of(self.notice().stdout)
        self.assertEqual(len(lines), 1, lines)


class TestHookNotice(NoticeCase):
    def test_hook_prints_the_nonterminal_line_for_payloads_with_and_without_session_id(self):
        self.raw(f"{ID_A}-alpha.md", "active", base=BASE_X)
        payloads = {
            "with-id": {"hook_event_name": "SessionStart", "session_id": "sess-x", "source": "startup",
                        "cwd": str(self.repo)},
            "without-id": {"hook_event_name": "SessionStart", "source": "startup", "cwd": str(self.repo)},
        }
        for label, payload in payloads.items():
            with self.subTest(payload=label):
                result = self.hook_start(payload)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertNotIn("Traceback", result.stderr)
                lines = lines_of(result.stdout)
                self.assertEqual(len(lines), 1, result.stdout)
                self.assertTrue(lines[0].startswith(NOTICE_PREFIX))
                self.assertIn(f"{SPECS}/{ID_A}-alpha.md", lines[0])
                self.assertIn(BASE_X, lines[0])

    def test_hook_prints_nothing_for_clean_and_missing_specs(self):
        self.specs.mkdir(parents=True, exist_ok=True)
        self.assertEqual(self.hook_start().stdout, "")
        shutil.rmtree(self.specs)
        result = self.hook_start()
        self.assertEqual((result.returncode, result.stdout), (0, ""))

    def test_hook_stdout_equals_notice_stdout_for_every_state(self):
        for label, build in self.states():
            with self.subTest(state=label):
                repo = self.fresh_repo()
                build(repo)
                expected = self.lc("notice", repo=repo)
                self.assert_ok(expected)
                result = self.hook_start(repo=repo, payload={
                    "hook_event_name": "SessionStart", "session_id": "sess-eq", "source": "startup",
                    "cwd": str(repo)})
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout.encode(), expected.stdout.encode())
                if label in ("n1", "n2", "n3", "n4", "combined"):
                    self.assertNotEqual(expected.stdout, "")


class TestNoticeFaultTolerance(NoticeCase):
    def assert_survives(self, readable_needles):
        notice = self.lc("notice")
        hook = self.hook_start()
        for label, result in (("notice", notice), ("hook", hook)):
            with self.subTest(surface=label):
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertNotIn("Traceback", result.stderr)
                for needle in readable_needles:
                    self.assertIn(needle, result.stdout)

    @unittest.skipIf(os.geteuid() == 0, "root can read mode 000 files")
    def test_spec_with_mode_000_is_skipped_and_the_readable_spec_is_still_listed(self):
        locked = self.raw(f"{ID_B}-locked.md", "active", base=BASE_X)
        self.raw(f"{ID_A}-alpha.md", "active", base=BASE_X)
        locked.chmod(0)
        self.addCleanup(locked.chmod, 0o644)
        self.assert_survives([f"{SPECS}/{ID_A}-alpha.md"])

    def test_spec_with_invalid_utf8_is_skipped_and_the_readable_spec_is_still_listed(self):
        bad = self.specs / f"{ID_B}-bad.md"
        bad.parent.mkdir(parents=True, exist_ok=True)
        bad.write_bytes(b"---\nstatus: active\nbase_commit: \xff\xfe\xfa\n---\n\xc3\x28\n")
        self.raw(f"{ID_A}-alpha.md", "active", base=BASE_X)
        self.assert_survives([f"{SPECS}/{ID_A}-alpha.md"])

    @unittest.skipIf(os.geteuid() == 0, "root can read mode 000 directories")
    def test_unreadable_marker_directory_entries_do_not_break_the_notice(self):
        self.raw(f"{ID_A}-alpha.md", "active", base=BASE_X)
        running = self.specs / ".running"
        running.mkdir()
        (running / "agent2").write_text("")
        locked = running / "agent1"
        locked.mkdir()
        (locked / "inner").write_text("")
        locked.chmod(0)
        self.addCleanup(locked.chmod, 0o755)
        seed_locked = self.specs / ".seed" / "locked"
        seed_locked.mkdir(parents=True)
        self.seed("ok.py")
        seed_locked.chmod(0)
        self.addCleanup(seed_locked.chmod, 0o755)
        self.assert_survives([f"{SPECS}/{ID_A}-alpha.md", "ok.py", f"{SPECS}/.running/agent2"])


class TestConfiguredDocsRoot(NoticeCase):
    def configure(self):
        (self.repo / ".harness" / "config.json").write_text(json.dumps({"docs_root": "docs"}))
        (self.repo / "docs" / "specs").mkdir(parents=True)

    def test_notice_reads_only_the_configured_root(self):
        self.configure()
        self.raw(f"{ID_C}-decoy.md", "active", base=BASE_X)
        (self.repo / "docs" / "specs" / f"{ID_A}-alpha.md").write_text(
            f"---\nstatus: active\nbase_commit: {BASE_X}\n---\n")
        (self.repo / "docs" / "specs" / f"{ID_B}-done.md").write_text("---\nstatus: complete\n---\n")
        (self.repo / "docs" / "spec-logs").mkdir()
        (self.repo / "docs" / "spec-logs" / f"{ID_B}-done.md").write_text("x\n")
        (self.repo / "docs" / "specs" / ".running").mkdir()
        (self.repo / "docs" / "specs" / ".running" / "agent1").write_text("")
        lines = lines_of(self.notice().stdout)
        self.assertEqual(len(lines), 3, lines)
        self.assertIn(f"docs/specs/{ID_A}-alpha.md", lines[0])
        self.assertIn(f"docs/specs/{ID_B}-done.md", lines[1])
        self.assertIn(f"docs/spec-logs/{ID_B}-done.md", lines[1])
        self.assertIn("docs/specs/.running/agent1", lines[2])
        self.assertNotIn("agent-docs", "".join(lines))

    def test_start_ignores_a_decoy_in_the_default_root_and_abort_moves_into_docs_spec_logs(self):
        self.configure()
        decoy = self.mk(run_id=ID_C, name="decoy")
        spec = self.mk(run_id=ID_A, name="real")
        target = self.repo / "docs" / "specs" / spec.name
        shutil.move(str(spec), str(target))
        self.assert_ok(self.start(target))
        original = target.read_bytes()
        result = self.abort(target)
        self.assert_ok(result)
        dest = self.repo / "docs" / "spec-logs" / spec.name
        self.assertEqual(dest.read_bytes(), original.replace(b"\nstatus: active\n", b"\nstatus: aborted\n", 1))
        self.assertIn(f"docs/spec-logs/{spec.name}", result.stdout)
        self.assertTrue(decoy.is_file())
        self.assertEqual(self.log_names(), [])

    def test_seed_under_the_configured_root_blocks_start(self):
        self.configure()
        spec = self.mk()
        target = self.repo / "docs" / "specs" / spec.name
        shutil.move(str(spec), str(target))
        seed = self.repo / "docs" / "specs" / ".seed" / "a.py"
        seed.parent.mkdir()
        seed.write_text("x\n")
        self.assert_refused(self.start(target), "unrestored seed backup")

    def test_abort_refuses_a_default_root_spec_when_a_custom_root_is_configured(self):
        self.configure()
        spec = self.mk()
        before = sha(spec)
        self.assert_refused(self.abort(spec), "docs/specs")
        self.assertEqual(sha(spec), before)


class TestActiveFileNamingTheMovedSpec(SpecCase):
    def switch(self):
        self.repo = self.fresh_repo()
        self.specs = self.repo / "agent-docs" / "specs"
        self.logs = self.repo / "agent-docs" / "spec-logs"

    def scenario(self, command, active):
        self.switch()
        status = "active" if command == "abort" else "complete"
        moved = self.mk(status=status, run_id=ID_A, name="change")
        other = self.mk(status="active", run_id=ID_B, name="other")
        other_before = sha(other)
        if active is not None:
            (self.specs / ".active").write_bytes(
                active.replace("{movedpath}", f"{SPECS}/{moved.name}").replace("{otherpath}", f"{SPECS}/{other.name}")
                .replace("{moved}", moved.name).replace("{other}", other.name).encode())
        if command == "archive":
            result = self.archive(moved, "complete")
        elif command == "abort":
            result = self.abort(moved)
        else:
            result = self.lc("session")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("Traceback", result.stderr)
        self.assertEqual(sha(other), other_before)
        if active is None:
            self.assertFalse((self.specs / ".active").exists())
        observed = (
            result.returncode,
            result.stdout,
            result.stderr.replace(str(self.repo), "<repo>"),
            sorted(p.name for p in self.specs.iterdir() if p.name != ".active"),
            sorted(p.name for p in self.logs.iterdir()),
            (self.logs / moved.name).read_bytes(),
        )
        return observed, (self.specs / ".active").read_bytes() if active is not None else None

    def test_active_file_does_not_change_archive_abort_or_session_results(self):
        for command in ("archive", "abort", "session"):
            baseline, _ = self.scenario(command, None)
            for label, content in (("naming-moved", "{moved}\n"), ("empty", ""), ("naming-other-active", "{other}\n"),
                                   ("naming-moved-by-path", "{movedpath}\n"),
                                   ("naming-other-by-path", "{otherpath}\n")):
                with self.subTest(command=command, active=label):
                    observed, kept = self.scenario(command, content)
                    self.assertEqual(observed, baseline)
                    expected = content.replace("{movedpath}", f"{SPECS}/{ID_A}-change.md").replace(
                        "{otherpath}", f"{SPECS}/{ID_B}-other.md").replace(
                        "{moved}", f"{ID_A}-change.md").replace("{other}", f"{ID_B}-other.md")
                    self.assertEqual(kept, expected.encode())

    def test_validate_gives_the_same_result_with_and_without_an_active_file(self):
        spec = self.mk()
        plain = self.lc("validate", "--spec", str(spec))
        (self.specs / ".active").write_text(f"{spec.name}\n")
        with_active = self.lc("validate", "--spec", str(spec))
        self.assertEqual((plain.returncode, plain.stdout, plain.stderr),
                         (with_active.returncode, with_active.stdout, with_active.stderr))
        self.assertEqual(plain.returncode, 0, plain.stderr)
        spec.write_text(spec.read_text().replace("| Safety | no | not affected |\n", ""))
        self.assertEqual(self.lc("validate", "--spec", str(spec)).returncode, 1)
        self.assertEqual((self.specs / ".active").read_text(), f"{spec.name}\n")


def ancestor_pids():
    chain, pid = set(), os.getpid()
    while pid > 0 and pid not in chain:
        chain.add(pid)
        out = subprocess.run(["ps", "-o", "ppid=", "-p", str(pid)], capture_output=True, text=True).stdout.strip()
        pid = int(out) if out.isdigit() else 0
    return chain


def foreign_signalable_pid():
    chain = ancestor_pids()
    listing = subprocess.run(["ps", "-axo", "pid=,uid="], capture_output=True, text=True).stdout
    for line in listing.splitlines():
        parts = line.split()
        if len(parts) != 2 or not all(p.isdigit() for p in parts):
            continue
        pid, uid = int(parts[0]), int(parts[1])
        if uid == os.geteuid() or pid in chain:
            continue
        try:
            os.kill(pid, 0)
        except PermissionError:
            return pid
        except OSError:
            continue
    return None


class TestLivenessEdges(SpecCase):
    @unittest.skipIf(os.geteuid() == 0, "root can signal every process")
    def test_permission_error_liveness_counts_as_another_live_session(self):
        pid = foreign_signalable_pid()
        if pid is None:
            self.skipTest("no foreign-owned live non-ancestor pid available")
        spec = self.mk()
        before = sha(spec)
        self.marker(pid, session_id="S5")
        result = self.abort(spec, session="S1")
        self.assert_refused(result, "other harness session", str(pid), "S5", FLAG)
        self.assert_untouched(spec, before)

    def test_grandparent_marker_without_session_id_is_own(self):
        spec = self.mk()
        self.marker(os.getpid())
        script = str(self.repo / ".harness" / "bin" / "spec_lifecycle.py")
        command = f"{shlex.quote(sys.executable)} {shlex.quote(script)} abort --spec {shlex.quote(str(spec))}; exit $?"
        result = subprocess.run(["/bin/sh", "-c", command], cwd=self.repo, capture_output=True, text=True,
                                env=self.env())
        self.assert_ok(result)
        self.assertFalse(spec.exists())
        self.assertTrue((self.logs / spec.name).is_file())


class TestNoticeSeedVariants(NoticeCase):
    def test_two_non_manifest_seed_files_one_nested_are_both_named(self):
        self.seed("a/b.py")
        self.seed("c.py")
        self.seed("manifest.json")
        lines = lines_of(self.notice().stdout)
        self.assertEqual(len(lines), 1, lines)
        self.assertIn("a/b.py", lines[0])
        self.assertIn("c.py", lines[0])
        self.assertNotIn("manifest.json", lines[0])
        self.assertIn(RESTORE, lines[0])

    def test_manifest_only_seed_gives_one_line_listing_no_file(self):
        self.seed("manifest.json")
        lines = lines_of(self.notice().stdout)
        self.assertEqual(len(lines), 1, lines)
        self.assertTrue(lines[0].startswith(NOTICE_PREFIX))
        self.assertIn("unrestored seed backup", lines[0])
        self.assertIn(RESTORE, lines[0])
        self.assertNotIn("manifest.json", lines[0])


class TestUnreadableLiveMarkerCountsAsOther(SpecCase):
    CONTENTS = (
        ("empty-file", b""),
        ("invalid-json", b"{not json"),
        ("json-array", b"[]"),
        ("non-string-session-id", b'{"session_id": 5}'),
        ("invalid-utf8", b"\xff\xfe\x80{"),
    )

    def test_abort_refuses_for_every_unreadable_marker_content(self):
        for label, content in self.CONTENTS:
            with self.subTest(content=label):
                self.setUp()
                spec = self.mk()
                before = sha(spec)
                pid = self.live_process()
                self.marker(pid, content=content)
                result = self.abort(spec)
                self.assert_refused(result, "other harness session", str(pid), FLAG)
                self.assert_untouched(spec, before)

    def test_archive_aborted_refuses_for_an_unreadable_marker_content(self):
        spec = self.mk(status="aborted")
        before = sha(spec)
        pid = self.live_process()
        self.marker(pid, content=b"{not json")
        self.assert_refused(self.archive(spec, "aborted"), "other harness session", str(pid), FLAG)
        self.assert_untouched(spec, before)


class TestNoActiveFileIsCreated(SpecCase):
    def absent(self):
        self.assertFalse((self.specs / ".active").exists())
        self.assertFalse((self.specs / ".active").is_symlink())

    def test_no_subcommand_creates_an_active_file_on_success_or_refusal(self):
        self.specs.mkdir(parents=True, exist_ok=True)
        self.lc("notice")
        self.absent()
        spec = self.mk(name="first")
        self.lc("validate", "--spec", str(spec))
        self.absent()
        self.assert_ok(self.start(spec))
        self.absent()
        other = self.mk(run_id=ID_B, name="second")
        self.assert_refused(self.start(other, ID_B), "another workflow is active")
        self.absent()
        self.assert_refused(self.start(spec, ID_C))
        self.absent()
        self.assert_ok(self.abort(spec))
        self.absent()
        done = self.mk(status="complete", run_id=ID_C, name="done")
        self.assert_ok(self.archive(done, "complete"))
        self.absent()
        self.assert_refused(self.archive(other, "complete"))
        self.absent()
        self.raw(f"{ID_A}-late.md", "complete")
        self.assert_ok(self.lc("session"))
        self.absent()
        self.assert_ok(self.lc("notice"))
        self.absent()


class TestRepoRelativePathForms(NoticeCase):
    def root_setup(self, root):
        if root != "agent-docs":
            (self.repo / ".harness" / "config.json").write_text(json.dumps({"docs_root": root}))
        specs = self.repo / root / "specs"
        specs.mkdir(parents=True, exist_ok=True)
        return specs

    def absolutes(self):
        return {str(self.repo), str(self.repo.resolve())}

    def token(self, path):
        return re.compile(rf"(?<![\w/.-]){re.escape(path)}(?![\w/-])")

    def assert_no_absolute(self, text):
        for absolute in self.absolutes():
            self.assertNotIn(absolute, text)

    def test_archive_and_abort_print_exactly_the_repo_relative_destination(self):
        for root in ("agent-docs", "docs"):
            with self.subTest(root=root):
                self.setUp()
                specs = self.root_setup(root)
                done = self.write_valid_spec(self.repo, ID_A, "done", "complete")
                if done != specs / done.name:
                    shutil.move(str(done), str(specs / done.name))
                result = self.archive(specs / done.name, "complete")
                self.assert_ok(result)
                self.assertEqual(result.stdout, f"{root}/spec-logs/{done.name}\n")
                self.assert_no_absolute(result.stdout)
                live = self.write_valid_spec(self.repo, ID_B, "live", "active")
                if live != specs / live.name:
                    shutil.move(str(live), str(specs / live.name))
                result = self.abort(specs / live.name)
                self.assert_ok(result)
                self.assertEqual(result.stdout, f"{root}/spec-logs/{live.name}\n")
                self.assert_no_absolute(result.stdout)

    def test_notice_paths_are_repo_relative_tokens_without_absolute_or_seed_prefixes(self):
        for root in ("agent-docs", "docs"):
            with self.subTest(root=root):
                self.setUp()
                specs = self.root_setup(root)
                (specs / f"{ID_A}-alpha.md").write_text(f"---\nstatus: active\nbase_commit: {BASE_X}\n---\n")
                (specs / f"{ID_B}-done.md").write_text("---\nstatus: complete\n---\n")
                (specs / f"{ID_C}-plain.md").write_text("---\nstatus: limit\n---\n")
                logs = self.repo / root / "spec-logs"
                logs.mkdir(parents=True)
                (logs / f"{ID_B}-done.md").write_text("x\n")
                (specs / ".running").mkdir()
                (specs / ".running" / "agent1").write_text("")
                result = self.notice()
                self.assert_no_absolute(result.stdout)
                lines = lines_of(result.stdout)
                self.assertEqual(len(lines), 4, lines)
                self.assertRegex(lines[0], self.token(f"{root}/specs/{ID_A}-alpha.md"))
                self.assertRegex(lines[1], self.token(f"{root}/specs/{ID_B}-done.md"))
                self.assertRegex(lines[1], self.token(f"{root}/spec-logs/{ID_B}-done.md"))
                self.assertRegex(lines[2], self.token(f"{root}/specs/{ID_C}-plain.md"))
                self.assertNotIn("spec-logs", lines[2])
                self.assertRegex(lines[3], self.token(f"{root}/specs/.running/agent1"))

    def test_seed_file_names_are_relative_to_the_seed_directory(self):
        for root in ("agent-docs", "docs"):
            with self.subTest(root=root):
                self.setUp()
                specs = self.root_setup(root)
                nested = specs / ".seed" / "a"
                nested.mkdir(parents=True)
                (nested / "b.py").write_text("x\n")
                result = self.notice()
                self.assert_no_absolute(result.stdout)
                lines = lines_of(result.stdout)
                self.assertEqual(len(lines), 1, lines)
                self.assertRegex(lines[0], self.token("a/b.py"))
                self.assertNotIn(".seed/a/b.py", lines[0])
                self.assertNotIn(f"{root}/specs/.seed/a/b.py", lines[0])


class TestMigration044(InstallerTestCase):
    def prepare(self, with_active=True, before_commit=None):
        repo = self.install()
        manifest_path = repo / ".harness" / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["version"] = "0.43.0"
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
        spec = self.write_valid_spec(repo, ID_A, "change", "active")
        keep = spec.parent / "keep.txt"
        keep.write_text("keep\n")
        active = spec.parent / ".active"
        if with_active:
            active.write_text(f"{spec.name}\n")
        if before_commit:
            before_commit(repo, spec)
        run_git(repo, "add", "-A")
        run_git(repo, "commit", "-q", "--no-verify", "-m", "base")
        return repo, spec, keep, active, manifest_path

    def update(self, repo, *flags, dry=False):
        if dry:
            return run_installer("update", str(repo), "--no-ci", "--dry-run", forbid_input=True)
        return run_installer("update", str(repo), "--no-ci", "--no-commit", *flags, input="y\n" * 20, exact=True)

    def announced(self, result):
        return re.findall(r"^migration (\d+\.\d+\.\d+):", result.stdout, re.MULTILINE)

    def assert_plan(self, result):
        start = result.stdout.index("migration 0.44.0:")
        header = result.stdout[start:].splitlines()[0]
        self.assertIn(".active", header)
        plan = result.stdout[start:]
        for needle in (".active", "seed", "abort", FLAG, "SessionStart"):
            self.assertIn(needle, plan)

    def test_update_removes_active_marker_and_touches_nothing_else_in_specs(self):
        repo, spec, keep, active, manifest_path = self.prepare()
        spec_bytes, keep_bytes = spec.read_bytes(), keep.read_bytes()
        result = self.update(repo)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.announced(result), ["0.44.0", "0.45.0", "0.46.0"], result.stdout)
        self.assert_plan(result)
        self.assertFalse(active.exists())
        self.assertEqual(spec.read_bytes(), spec_bytes)
        self.assertEqual(keep.read_bytes(), keep_bytes)
        self.assertEqual(json.loads(manifest_path.read_text())["version"], "0.46.0")

    def test_dry_run_announces_the_migration_and_deletes_nothing(self):
        repo, spec, keep, active, manifest_path = self.prepare()
        before = self.snapshot(repo)
        result = self.update(repo, dry=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.announced(result), ["0.44.0", "0.45.0", "0.46.0"], result.stdout)
        self.assert_plan(result)
        self.assertTrue(active.is_file())
        self.assertEqual(self.snapshot(repo), before)
        self.assertEqual(json.loads(manifest_path.read_text())["version"], "0.43.0")

    def test_custom_docs_root_deletes_only_that_roots_active_file(self):
        def setup(repo, spec):
            (repo / ".harness" / "config.json").write_text(json.dumps({"docs_root": "docs"}))
            (repo / "docs" / "specs").mkdir(parents=True)
            (repo / "docs" / "specs" / ".active").write_text("docs marker\n")

        repo, spec, keep, active, manifest_path = self.prepare(before_commit=setup)
        result = self.update(repo)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse((repo / "docs" / "specs" / ".active").exists())
        self.assertEqual(active.read_text(), f"{spec.name}\n")

    def test_active_directory_stays_with_its_contents(self):
        def setup(repo, spec):
            (spec.parent / ".active").mkdir()
            (spec.parent / ".active" / "inner.txt").write_text("inner\n")

        repo, spec, keep, active, manifest_path = self.prepare(with_active=False, before_commit=setup)
        result = self.update(repo)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(active.is_dir())
        self.assertEqual((active / "inner.txt").read_text(), "inner\n")

    def test_active_symlink_stays_and_its_target_is_untouched(self):
        def setup(repo, spec):
            os.symlink("keep.txt", spec.parent / ".active")

        repo, spec, keep, active, manifest_path = self.prepare(with_active=False, before_commit=setup)
        keep_bytes = keep.read_bytes()
        result = self.update(repo)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(active.is_symlink())
        self.assertEqual(os.readlink(active), "keep.txt")
        self.assertEqual(keep.read_bytes(), keep_bytes)

    def test_update_without_active_marker_succeeds_and_announces_the_migration(self):
        repo, spec, keep, active, manifest_path = self.prepare(with_active=False)
        spec_bytes = spec.read_bytes()
        result = self.update(repo)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.announced(result), ["0.44.0", "0.45.0", "0.46.0"], result.stdout)
        self.assertFalse(active.exists())
        self.assertEqual(spec.read_bytes(), spec_bytes)
        self.assertEqual(json.loads(manifest_path.read_text())["version"], "0.46.0")


class TestSkillAbortOrder(SpecCase):
    @text_test
    def test_step_one_states_the_abort_order(self):
        text = (self.repo / ".harness" / "skills" / "workflow-approach" / "SKILL.md").read_text()
        lines = text.splitlines()
        first = next(i for i, line in enumerate(lines) if line.startswith("1. **"))
        second = next(i for i, line in enumerate(lines) if i > first and line.startswith("2. **"))
        step = "\n".join(lines[first:second]).lower()
        position = 0
        for needle in ("python3 .harness/bin/seed.py restore", "retrospective",
                       "python3 .harness/bin/spec_lifecycle.py abort --spec", "--other-sessions-confirmed",
                       "workflow_marker.py end"):
            found = step.find(needle, position)
            self.assertNotEqual(found, -1, f"{needle!r} missing or out of order in step 1")
            position = found + len(needle)
        self.assertIn("--status aborted", step[position - len("workflow_marker.py end"):])


GATED = (
    "test_hook_owned_progress.TestTextScan.test_removed_wording_does_not_occur_in_harness_or_readme",
    "test_hook_owned_progress.TestTextScan.test_progress_rule_text_contains_the_required_phrases",
    "test_hook_owned_progress.TestTextScan.test_readme_mentions_the_placeholder_and_drops_the_one_time_notice_wording",
    "test_rule_injection.TestRuleText.test_rule_files_section_of_the_block_equals_the_expected_text_in_source_and_install",
    "test_rule_injection.TestRuleText.test_synced_comments_rule_names_end_markers_block_hash_and_refresh_command",
    "test_rule_injection.TestRuleText.test_index_rule_names_the_stale_command",
    "test_rule_injection.TestRuleText.test_progress_rule_describes_the_record_only_kind",
    "test_rule_injection.TestRuleText.test_continue_on_skill_notes_that_record_only_progress_is_skipped",
    "test_rule_injection.TestRuleText.test_readme_mentions_records_command_and_record_only_progress",
    "test_spec_active_state.TestSkillAbortOrder.test_step_one_states_the_abort_order",
)
KEPT = (
    "test_hook_owned_progress.TestTextScan.test_version_is_0_44_0",
    "test_hook_owned_progress.TestTextScan.test_installed_progress_rule_equals_the_source",
    "test_rule_injection.TestRuleText.test_installed_copies_equal_the_payload_files",
)


class TestTextGate(unittest.TestCase):
    _cache = {}

    def run_ids(self, ids, value):
        key = (ids, value)
        if key in self._cache:
            return self._cache[key]
        env = {k: v for k, v in os.environ.items() if k != "HARNESS_TEXT_TESTS"}
        if value is not None:
            env["HARNESS_TEXT_TESTS"] = value
        proc = subprocess.run([sys.executable, "-m", "unittest", "-v", *ids], cwd=TESTS_DIR,
                              capture_output=True, text=True, env=env)
        self._cache[key] = proc
        return proc

    def outcome(self, proc, test_id):
        module, cls, name = test_id.split(".")
        match = re.search(rf"^{name} \({re.escape(test_id)}\)[^\n]*? \.\.\. (.*)$", proc.stderr, re.MULTILINE)
        self.assertIsNotNone(match, f"{test_id} not reported:\n{proc.stderr}")
        return match.group(1).strip()

    def assert_all_skipped(self, value):
        proc = self.run_ids(GATED, value)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        for test_id in GATED:
            with self.subTest(test=test_id):
                result = self.outcome(proc, test_id)
                self.assertTrue(result.startswith("skipped"), result)
                self.assertIn("HARNESS_TEXT_TESTS=1", result)

    def test_unset_variable_skips_every_gated_test_with_the_reason(self):
        self.assert_all_skipped(None)

    def test_value_zero_skips_every_gated_test(self):
        self.assert_all_skipped("0")

    def test_empty_value_skips_every_gated_test(self):
        self.assert_all_skipped("")

    def test_value_true_skips_every_gated_test(self):
        self.assert_all_skipped("true")

    def test_value_one_runs_and_passes_every_gated_test(self):
        proc = self.run_ids(GATED, "1")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        for test_id in GATED:
            with self.subTest(test=test_id):
                self.assertEqual(self.outcome(proc, test_id), "ok")

    def test_kept_tests_run_when_the_variable_is_unset(self):
        proc = self.run_ids(KEPT, None)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        for test_id in KEPT:
            with self.subTest(test=test_id):
                self.assertEqual(self.outcome(proc, test_id), "ok")


if __name__ == "__main__":
    unittest.main()

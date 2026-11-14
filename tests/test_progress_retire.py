import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from test_installer import REPO_ROOT, run_installer
from test_progress import EM, NAME1, NAME2, ProgressCase, build, frontmatter, out, split_requests

SESSION = "sessa"
OTHER = "sessb"
PROG = f"agent-docs/progress/{NAME1}"
LOGS = f"agent-docs/progress-logs/{NAME1}"
GATE_PREFIX = "harness: gh pr create blocked:"
GATE_COMMAND = "gh pr create --fill"


class RetireCase(ProgressCase):
    def git(self, repo, *args, session=None, check=True):
        env = self.env(**({"CLAUDE_CODE_SESSION_ID": session} if session else {}))
        result = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, env=env)
        if check:
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result

    def attach_remote(self, repo, branch):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        bare = Path(tmp.name) / "origin.git"
        subprocess.run(["git", "init", "-q", "--bare", str(bare)], check=True)
        self.git(repo, "remote", "add", "origin", str(bare))
        self.git(repo, "push", "-q", "-u", "origin", branch)
        return bare

    def session_repo(self, remote=True, branch="feat", changed=True):
        repo = self.new_repo()
        base = self.branch(repo)
        if remote:
            self.attach_remote(repo, base)
        self.git(repo, "checkout", "-q", "-b", branch)
        if remote:
            self.git(repo, "push", "-q", "-u", "origin", branch)
        self.assertEqual(self.start(repo).returncode, 0)
        if changed:
            self.bash(repo, lambda: (repo / "src" / "new.py").write_text("new = 1\n"), event="PostToolUseFailure")
        return repo

    def progress_text(self, repo, sid=SESSION, stamp=None, user_requests="", **kw):
        head = self.head(repo)
        return build(session=sid, stamp=stamp or head, next_step=[("alpha work item", head, "none")],
                     user_requests=user_requests, **kw)

    def write_progress(self, repo, name=NAME1, sid=SESSION, directory="progress", post=False, **kw):
        path = self.put(repo, name, self.progress_text(repo, sid=sid, **kw), directory=directory)
        if post:
            self.post(repo, path, sid=sid)
        return path

    def gate(self, repo, command=GATE_COMMAND, sid=SESSION, **kw):
        payload = {"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_use_id": "toolu_gate",
                   "tool_input": {"command": command}}
        if sid is not None:
            payload["session_id"] = sid
        return self.hook(repo, payload, **kw)

    def assert_blocked(self, result, *needles):
        self.assertEqual(result.returncode, 2, out(result))
        self.assertTrue(result.stderr.startswith(GATE_PREFIX), result.stderr)
        self.assertNotIn("Traceback", result.stderr)
        self.assertIn(SESSION, result.stderr)
        self.assertIn("own bash call", result.stderr.lower())
        for needle in needles:
            self.assertIn(needle, result.stderr)

    def assert_allowed(self, result):
        self.assertEqual((result.returncode, result.stderr), (0, ""), out(result))

    def retire(self, repo, *args, session_env=None):
        return self.cli(repo, "retire", *args, session_env=session_env)

    def retire_ok(self, repo):
        result = self.retire(repo, "--session", SESSION)
        self.assertEqual(result.returncode, 0, out(result))
        return result

    def commit_all(self, repo, message="work"):
        self.git(repo, "add", "-A")
        return self.commit(repo, message)

    def push(self, repo):
        self.git(repo, "push", "-q", "origin", "HEAD")

    def committed_retire(self, repo):
        self.write_progress(repo)
        self.retire_ok(repo)
        self.commit_all(repo)

    def lowered(self, result):
        return result.stderr.lower()

    def repo_state(self, repo):
        agent_docs = {str(p.relative_to(repo)): p.read_bytes() for p in (repo / "agent-docs").rglob("*") if p.is_file()}
        return (self.git(repo, "status", "--porcelain").stdout, self.git(repo, "ls-files", "-s").stdout, agent_docs)

    def blob(self, repo, rev, rel):
        return self.git(repo, "show", f"{rev}:{rel}").stdout

    def expected_requests(self, repo, sid=SESSION):
        lines = []
        for n, prompt in enumerate(self.state(repo, sid)["prompts"], 1):
            lines.append(f"#### {n} {EM} {prompt['at']}")
            lines += [f"> {line}" for line in prompt["text"].split("\n")]
        return lines

    def doc_commit(self, repo, path, sid=SESSION):
        payload = {"hook_event_name": "PostToolUse", "session_id": sid, "tool_name": "Write", "cwd": str(repo),
                   "tool_input": {"file_path": str(path)}}
        return subprocess.run([sys.executable, str(repo / ".harness" / "hooks" / "doc_commit.py")],
                              input=json.dumps(payload), capture_output=True, text=True, env=self.env())


class TestGateCommandRecognition(RetireCase):
    def gated_repo(self):
        repo = self.session_repo()
        self.write_progress(repo)
        return repo

    def assert_gated(self, command):
        repo = self.gated_repo()
        self.assert_blocked(self.gate(repo, command), PROG)

    def assert_not_gated(self, command):
        repo = self.gated_repo()
        self.assert_allowed(self.gate(repo, command))

    def test_p1_bare_command_is_gated(self):
        self.assert_gated("gh pr create")

    def test_p2_command_after_double_ampersand_is_gated(self):
        self.assert_gated("git commit -m x && git push && gh pr create")

    def test_p3_command_after_semicolon_is_gated(self):
        self.assert_gated("git status; gh pr create --fill")

    def test_p4_command_after_newline_is_gated(self):
        self.assert_gated("echo hi\ngh pr create --fill")

    def test_p5_echoed_text_is_not_gated(self):
        self.assert_not_gated("echo gh pr create")

    def test_p6_pr_view_is_not_gated(self):
        self.assert_not_gated("gh pr view")

    def test_p7_pr_edit_is_not_gated(self):
        self.assert_not_gated("gh pr edit --body x")


class TestGateDecisionTable(RetireCase):
    def test_rule_a_own_progress_in_progress_dir_blocks_with_retire_command(self):
        repo = self.session_repo()
        self.write_progress(repo)

        result = self.gate(repo)

        self.assert_blocked(result, PROG, f"python3 .harness/bin/progress.py retire --session {SESSION}")
        self.assertIn("commit", self.lowered(result))
        self.assertIn("push", self.lowered(result))
        self.assertIn("own bash call", self.lowered(result))

    def test_rule_a_wins_over_later_rules_when_progress_is_also_committed(self):
        repo = self.session_repo()
        self.write_progress(repo)
        self.commit_all(repo)

        self.assert_blocked(self.gate(repo), PROG, f"retire --session {SESSION}")

    def test_rule_b_changed_project_without_any_progress_blocks_with_write_advice(self):
        repo = self.session_repo(changed=True)

        result = self.gate(repo)

        self.assert_blocked(result, SESSION)
        text = self.lowered(result)
        for word in ("write", "retire", "commit", "push", "own bash call"):
            self.assertIn(word, text)
        self.assertIn(f"--session {SESSION}", result.stderr)

    def test_rule_c_head_still_holds_progress_under_progress_dir_blocks_with_commit_advice(self):
        repo = self.session_repo()
        self.write_progress(repo)
        self.commit_all(repo)
        self.push(repo)
        self.retire_ok(repo)

        result = self.gate(repo)

        self.assert_blocked(result, SESSION, NAME1)
        self.assertIn("commit", self.lowered(result))
        self.assertIn("own bash call", self.lowered(result))

    def test_rule_c_alone_blocks_when_only_the_logs_file_was_committed(self):
        repo = self.session_repo()
        self.write_progress(repo)
        self.commit_all(repo)
        self.push(repo)
        self.retire_ok(repo)
        self.git(repo, "commit", "-q", "--no-verify", "-m", "logs only", "--", LOGS)
        self.assertEqual(self.blob(repo, "HEAD", LOGS), (repo / LOGS).read_text())
        self.assertEqual(self.git(repo, "ls-tree", "HEAD", "--name-only", "--", PROG).stdout.strip(), PROG)

        result = self.gate(repo)

        self.assert_blocked(result, NAME1)
        self.assertIn("commit", self.lowered(result))

    def test_rule_e_alone_blocks_when_push_target_still_holds_progress_with_equal_logs_blob(self):
        repo = self.session_repo()
        path = self.write_progress(repo)
        self.commit_all(repo)
        logs = self.put(repo, NAME1, path.read_text(), directory="progress-logs")
        self.git(repo, "add", "--", LOGS)
        self.commit(repo, "logs copy")
        self.push(repo)
        self.git(repo, "rm", "-q", "--", PROG)
        self.commit(repo, "drop progress copy")
        self.assertEqual(self.blob(repo, "origin/feat", LOGS), self.blob(repo, "HEAD", LOGS))
        self.assertEqual(self.git(repo, "ls-tree", "origin/feat", "--name-only", "--", PROG).stdout.strip(), PROG)

        result = self.gate(repo)

        self.assert_blocked(result, NAME1)
        self.assertIn("push", self.lowered(result))

    def test_rule_d_logs_file_absent_from_head_or_differing_from_head_blocks_with_commit_advice(self):
        for label in ("absent from head", "differs from head"):
            with self.subTest(case=label):
                repo = self.session_repo()
                self.write_progress(repo)
                self.retire_ok(repo)
                if label == "differs from head":
                    self.commit_all(repo)
                    self.push(repo)
                    with (repo / LOGS).open("a") as handle:
                        handle.write("\nlocal edit\n")

                result = self.gate(repo)

                self.assert_blocked(result, SESSION, NAME1)
                self.assertIn("commit", self.lowered(result))
                self.assertIn("own bash call", self.lowered(result))

    def test_rule_e_progress_remains_in_push_target_tree_blocks_with_push_advice(self):
        repo = self.session_repo()
        self.write_progress(repo)
        self.commit_all(repo)
        self.push(repo)
        self.retire_ok(repo)
        self.commit_all(repo, "retire")

        result = self.gate(repo)

        self.assert_blocked(result, SESSION, NAME1)
        self.assertIn("push", self.lowered(result))
        self.assertIn("own bash call", self.lowered(result))

    def test_rule_e_logs_file_missing_or_different_in_push_target_blocks_with_push_advice(self):
        for label in ("missing in target", "different blob in target"):
            with self.subTest(case=label):
                repo = self.session_repo()
                self.committed_retire(repo)
                if label == "different blob in target":
                    self.push(repo)
                    with (repo / LOGS).open("a") as handle:
                        handle.write("\nsecond edit\n")
                    self.commit_all(repo, "edit logs")

                result = self.gate(repo)

                self.assert_blocked(result, SESSION, NAME1)
                self.assertIn("push", self.lowered(result))

    def test_allow_when_every_check_passes(self):
        repo = self.session_repo()
        self.committed_retire(repo)
        self.push(repo)

        self.assert_allowed(self.gate(repo))

    def test_allow_when_session_changed_nothing_and_owns_no_progress(self):
        repo = self.session_repo(changed=False)

        self.assert_allowed(self.gate(repo))

    def test_allow_when_only_another_sessions_progress_remains_in_progress_dir(self):
        repo = self.session_repo()
        self.write_progress(repo, name=NAME2, sid=OTHER)
        self.write_progress(repo)
        self.retire_ok(repo)
        self.assertTrue((repo / "agent-docs" / "progress" / NAME2).is_file())
        self.commit_all(repo)
        self.push(repo)

        self.assert_allowed(self.gate(repo))


class TestGateFailOpen(RetireCase):
    def test_f1_payload_without_session_id_is_allowed(self):
        repo = self.session_repo()
        self.write_progress(repo)

        self.assert_allowed(self.gate(repo, sid=None))

    def test_f2_repository_without_git_is_allowed(self):
        repo = self.session_repo()
        self.write_progress(repo)
        shutil.rmtree(repo / ".git")

        self.assert_allowed(self.gate(repo))

    def test_f4_repository_without_any_commit_is_allowed(self):
        repo = self.make_repo()
        result = run_installer("install", str(repo), "--no-ci")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotEqual(self.git(repo, "rev-parse", "--verify", "-q", "HEAD", check=False).returncode, 0)
        sha = "0" * 40
        self.put(repo, NAME1, build(session=SESSION, stamp=sha, next_step=[("alpha work item", sha, "none")]))

        gated = self.gate(repo)

        self.assert_allowed(gated)
        self.assertNotIn("Traceback", out(gated))

    def test_f3_unresolvable_push_ref_skips_push_checks(self):
        for label in ("no upstream", "head names missing remote ref"):
            with self.subTest(case=label):
                repo = self.session_repo(remote=(label != "no upstream"))
                self.committed_retire(repo)
                command = GATE_COMMAND if label == "no upstream" else "gh pr create --head nosuchbranch"

                self.assert_allowed(self.gate(repo, command))


class TestGatePushTarget(RetireCase):
    HEAD_FORMS = {
        "b1 long flag": "gh pr create --head feat",
        "b2 short flag": "gh pr create -H feat",
        "b3 equals with owner": "gh pr create --head=owner:feat",
    }

    def committed_unpushed(self):
        repo = self.session_repo(branch="work")
        base = self.head(repo)
        self.committed_retire(repo)
        return repo, base

    def test_b0_no_flag_uses_push_ref_of_current_branch(self):
        repo, _ = self.committed_unpushed()
        self.git(repo, "update-ref", "refs/remotes/origin/feat", "HEAD")

        result = self.gate(repo)

        self.assert_blocked(result, NAME1)
        self.assertIn("push", self.lowered(result))

    def test_head_forms_use_the_named_remote_ref_and_block_when_it_is_behind(self):
        for label, command in self.HEAD_FORMS.items():
            with self.subTest(form=label):
                repo, base = self.committed_unpushed()
                self.git(repo, "update-ref", "refs/remotes/origin/work", "HEAD")
                self.git(repo, "update-ref", "refs/remotes/origin/feat", base)

                result = self.gate(repo, command)

                self.assert_blocked(result, NAME1)
                self.assertIn("push", self.lowered(result))

    def test_b1_head_flag_allows_when_named_remote_ref_equals_head(self):
        repo, base = self.committed_unpushed()
        self.git(repo, "update-ref", "refs/remotes/origin/feat", "HEAD")

        self.assert_allowed(self.gate(repo, "gh pr create --head feat"))


class TestRetireCommand(RetireCase):
    def staged_names(self, repo):
        return self.git(repo, "diff", "--cached", "--name-status").stdout.splitlines()

    def index_hash(self, repo, rel):
        parts = self.git(repo, "ls-files", "-s", "--", rel).stdout.split()
        return parts[1] if parts else None

    def work_hash(self, repo, rel):
        return self.git(repo, "hash-object", rel).stdout.strip()

    def test_e1_tracked_progress_is_renamed_and_staged(self):
        repo = self.new_repo()
        path = self.write_progress(repo)
        self.commit_all(repo)
        original = path.read_bytes()

        result = self.retire(repo, "--session", SESSION)

        self.assertEqual(result.returncode, 0, out(result))
        self.assertIn(f"retired: {PROG} -> {LOGS}", result.stdout.splitlines())
        self.assertFalse(path.exists())
        self.assertEqual(self.git(repo, "ls-files", "--", PROG).stdout, "")
        self.assertEqual((repo / LOGS).read_bytes(), original)
        self.assertEqual(self.index_hash(repo, LOGS), self.work_hash(repo, LOGS))
        self.assertTrue(any(re.fullmatch(rf"R\d*\t{re.escape(PROG)}\t{re.escape(LOGS)}", line)
                            for line in self.staged_names(repo)), self.staged_names(repo))

    def test_e2_untracked_progress_is_moved_and_staged_as_added(self):
        repo = self.new_repo()
        path = self.write_progress(repo)
        original = path.read_bytes()

        result = self.retire(repo, session_env=SESSION)

        self.assertEqual(result.returncode, 0, out(result))
        self.assertIn(f"retired: {PROG} -> {LOGS}", result.stdout.splitlines())
        self.assertFalse(path.exists())
        self.assertEqual(self.git(repo, "ls-files", "--", PROG).stdout, "")
        self.assertEqual((repo / LOGS).read_bytes(), original)
        self.assertEqual(self.index_hash(repo, LOGS), self.work_hash(repo, LOGS))
        self.assertIn(f"A\t{LOGS}", self.staged_names(repo))

    def test_e3_tracked_progress_with_unstaged_edits_stages_working_tree_content(self):
        repo = self.new_repo()
        path = self.write_progress(repo)
        self.commit_all(repo)
        edited = path.read_text() + "\nunstaged edit marker\n"
        path.write_text(edited)

        result = self.retire(repo, "--session", SESSION)

        self.assertEqual(result.returncode, 0, out(result))
        self.assertFalse(path.exists())
        self.assertEqual(self.git(repo, "ls-files", "--", PROG).stdout, "")
        self.assertEqual((repo / LOGS).read_text(), edited)
        self.assertEqual(self.index_hash(repo, LOGS), self.work_hash(repo, LOGS))
        self.assertIn("unstaged edit marker", self.git(repo, "cat-file", "-p", self.index_hash(repo, LOGS)).stdout)

    def assert_refused(self, repo, args, needles=(), session_env=None):
        before = self.repo_state(repo)

        result = self.retire(repo, *args, session_env=session_env)

        self.assertEqual(result.returncode, 1, out(result))
        self.assertTrue(result.stderr.startswith("progress.py:"), result.stderr)
        self.assertNotIn("Traceback", result.stderr)
        for needle in needles:
            self.assertIn(needle, result.stderr)
        self.assertEqual(self.repo_state(repo), before)

    def test_e4_session_flag_wins_over_environment_session(self):
        repo = self.new_repo()
        self.write_progress(repo, name=NAME1, sid=SESSION)
        self.write_progress(repo, name=NAME2, sid=OTHER)

        result = self.retire(repo, "--session", SESSION, session_env=OTHER)

        self.assertEqual(result.returncode, 0, out(result))
        self.assertIn(f"retired: {PROG} -> {LOGS}", result.stdout.splitlines())
        self.assertTrue((repo / "agent-docs" / "progress" / NAME2).is_file())
        self.assertFalse((repo / "agent-docs" / "progress-logs" / NAME2).exists())

    def test_x6_failing_git_mv_leaves_tracked_source_in_place(self):
        repo = self.new_repo()
        path = self.write_progress(repo)
        self.commit_all(repo)
        original = path.read_bytes()
        lock = repo / ".git" / "index.lock"
        lock.write_text("")
        self.addCleanup(lambda: lock.unlink() if lock.exists() else None)

        result = self.retire(repo, "--session", SESSION)

        self.assertEqual(result.returncode, 1, out(result))
        self.assertTrue(result.stderr.startswith("progress.py:"), result.stderr)
        self.assertIn("index.lock", result.stderr)
        self.assertNotIn("Traceback", result.stderr)
        self.assertEqual(path.read_bytes(), original)
        self.assertFalse((repo / LOGS).exists())
        lock.unlink()
        self.assertEqual(self.git(repo, "ls-files", "--", PROG).stdout.strip(), PROG)
        self.assertEqual(self.git(repo, "status", "--porcelain").stdout, "")

    def test_x1_no_session_given_or_set_is_refused(self):
        repo = self.new_repo()
        self.write_progress(repo)
        self.commit_all(repo)

        self.assert_refused(repo, (), ("--session", "CLAUDE_CODE_SESSION_ID"))

    def test_x2_no_own_file_is_refused(self):
        repo = self.new_repo()
        self.write_progress(repo, sid=OTHER)

        self.assert_refused(repo, ("--session", SESSION))

    def test_x3_two_own_files_are_refused(self):
        repo = self.new_repo()
        self.write_progress(repo, name=NAME1)
        self.commit_all(repo)
        self.write_progress(repo, name=NAME2)

        self.assert_refused(repo, ("--session", SESSION), (NAME1, NAME2))

    def test_x4_existing_own_logs_file_is_refused(self):
        repo = self.new_repo()
        self.write_progress(repo, name=NAME2, directory="progress-logs")
        self.write_progress(repo, name=NAME1)
        self.commit_all(repo)

        self.assert_refused(repo, ("--session", SESSION), (NAME2,))

    def test_x5_existing_destination_is_refused(self):
        repo = self.new_repo()
        self.write_progress(repo, name=NAME1, sid=OTHER, directory="progress-logs")
        self.write_progress(repo, name=NAME1)

        self.assert_refused(repo, ("--session", SESSION), (LOGS,))


class TestLogsFileHooks(RetireCase):
    def logs_repo(self, sid=SESSION, **kw):
        repo = self.new_repo()
        old = self.head(repo)
        self.touch_commit(repo, "src/a.py", "move head")
        self.start(repo)
        path = self.put(repo, NAME1, build(session=sid, stamp=old, next_step=[("alpha work item", old, "none")],
                                           user_requests="", **kw), directory="progress-logs")
        return repo, path, old

    def test_l1_write_to_own_logs_file_syncs_requests_stamps_commit_and_does_not_rotate(self):
        repo, path, old = self.logs_repo()
        self.prompt(repo, "first logged request")
        self.prompt(repo, "second logged request")

        result = self.post(repo, path)

        self.assertEqual(result.returncode, 0, out(result))
        self.assertEqual(split_requests(path.read_text())[1], self.expected_requests(repo))
        self.assertEqual(len(self.expected_requests(repo)), 4)
        fields = frontmatter(path)
        self.assertEqual(fields["commit"], self.head(repo))
        self.assertNotEqual(fields["commit"], old)
        self.assertEqual(fields["session"], SESSION)
        self.assertEqual(fields["before"], "none")
        self.assertEqual(sorted(p.name for p in (repo / "agent-docs" / "progress-logs").glob("*.md")), [NAME1])
        self.assertEqual(list((repo / "agent-docs" / "progress").glob("*.md")), [])

    def test_l2_other_sessions_logs_file_is_ignored_by_progress_hook_but_stamped_by_doc_commit(self):
        repo, path, old = self.logs_repo(sid=OTHER)
        self.prompt(repo, "request of the writer")
        before = path.read_bytes()

        result = self.post(repo, path)

        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, "", ""))
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(self.doc_commit(repo, path).returncode, 0)
        self.assertEqual(frontmatter(path)["commit"], self.head(repo))
        self.assertNotEqual(frontmatter(path)["commit"], old)

    def test_l3_format_defect_in_own_logs_file_is_reported(self):
        repo, path, old = self.logs_repo()
        defective = path.read_text().replace("### Next Step\n", f"### Next Step\n- {'x' * 80}\n", 1)
        path.write_text(defective)

        result = self.post(repo, path)

        self.assertEqual(result.returncode, 2, out(result))
        self.assertIn("  - files:", out(result))
        self.assertIn("x" * 50, out(result))
        self.assertNotIn("Traceback", result.stderr)

    def test_l4_new_progress_file_while_own_logs_file_exists_is_refused_without_rotation(self):
        repo, logs, old = self.logs_repo()
        logs_bytes = logs.read_bytes()
        new = self.write_progress(repo, name=NAME2)

        result = self.post(repo, new)

        self.assertEqual(result.returncode, 2, out(result))
        self.assertIn(NAME1, result.stderr)
        self.assertIn("merge", self.lowered(result))
        self.assertIn("remove", self.lowered(result))
        self.assertEqual(logs.read_bytes(), logs_bytes)
        self.assertTrue(new.is_file())
        self.assertEqual(sorted(p.name for p in (repo / "agent-docs" / "progress-logs").glob("*.md")), [NAME1])
        self.assertNotIn("Traceback", result.stderr)

    def test_l8_invalid_frontmatter_in_logs_file_is_left_alone_silently(self):
        repo, path, old = self.logs_repo()
        path.write_text("# no frontmatter at all\n")
        before = path.read_bytes()

        result = self.post(repo, path)

        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, "", ""))
        self.assertEqual(path.read_bytes(), before)

    def test_l9_new_progress_file_without_session_line_is_refused_when_payload_session_owns_logs(self):
        repo, logs, old = self.logs_repo()
        logs_bytes = logs.read_bytes()
        new = self.put(repo, NAME2, build(session=None, stamp=old, next_step=[("beta work item", old, "none")]))

        result = self.post(repo, new)

        self.assertEqual(result.returncode, 2, out(result))
        self.assertIn(NAME1, result.stderr)
        self.assertIn("merge", self.lowered(result))
        self.assertEqual(logs.read_bytes(), logs_bytes)
        self.assertTrue(new.is_file())
        self.assertEqual(sorted(p.name for p in (repo / "agent-docs" / "progress-logs").glob("*.md")), [NAME1])
        self.assertNotIn("Traceback", result.stderr)

    def test_l5_precompact_notice_names_logs_file_of_session(self):
        repo, path, old = self.logs_repo()

        result = self.precompact(repo)

        self.assertEqual(result.returncode, 0, out(result))
        self.assertIn(NAME1, result.stdout + result.stderr)

    def test_l6_doc_commit_leaves_own_logs_file_exactly_as_progress_hook_wrote_it(self):
        repo, path, old = self.logs_repo()
        self.prompt(repo, "a request")
        self.post(repo, path)
        written = path.read_bytes()
        self.touch_commit(repo, "src/b.py", "move head again")
        self.assertNotEqual(frontmatter(path)["commit"], self.head(repo))

        result = self.doc_commit(repo, path)

        self.assertEqual(result.returncode, 0, out(result))
        self.assertEqual(path.read_bytes(), written)

    def test_l7_stop_accepts_progress_that_lives_only_in_committed_and_pushed_logs_file(self):
        repo = self.session_repo()
        self.write_progress(repo, directory="progress-logs")
        self.commit_all(repo)
        self.push(repo)

        result = self.stop(repo)

        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, "", ""))


class TestSessionLifecycle(RetireCase):
    def assert_stop_blocked(self, repo, word):
        result = self.stop(repo)
        self.assertEqual(result.returncode, 2, out(result))
        self.assertTrue(result.stderr.startswith("harness:"), result.stderr)
        self.assertIn(NAME1, result.stderr)
        self.assertIn(word, self.lowered(result))
        self.assertNotIn("Traceback", result.stderr)

    def test_gate_and_stop_follow_the_progress_through_every_state(self):
        repo = self.session_repo()

        self.assert_blocked(self.gate(repo), SESSION)
        self.assertIn("write", self.lowered(self.gate(repo)))

        self.write_progress(repo, post=True)
        self.assert_blocked(self.gate(repo), PROG, SESSION, f"retire --session {SESSION}")

        self.retire_ok(repo)
        self.assert_blocked(self.gate(repo), NAME1, SESSION)
        self.assertIn("commit", self.lowered(self.gate(repo)))
        self.assert_stop_blocked(repo, "commit")

        self.commit_all(repo)
        self.assert_blocked(self.gate(repo), NAME1, SESSION)
        self.assertIn("push", self.lowered(self.gate(repo)))
        self.assert_stop_blocked(repo, "push")
        self.assertEqual(self.stop(repo, active=True).returncode, 0)

        self.push(repo)
        self.assert_allowed(self.gate(repo))
        stopped = self.stop(repo)
        self.assertEqual((stopped.returncode, stopped.stdout, stopped.stderr), (0, "", ""))

        logs = repo / LOGS
        with logs.open("a") as handle:
            handle.write("\nedited after the pull request\n")
        self.post(repo, logs, tool="Edit")
        self.assert_blocked(self.gate(repo), NAME1, SESSION)
        self.assertIn("commit", self.lowered(self.gate(repo)))
        self.assert_stop_blocked(repo, "commit")
        self.assertEqual(self.stop(repo, active=True).returncode, 0)

        self.commit_all(repo, "edit logs")
        self.assert_stop_blocked(repo, "push")
        self.assertIn("push", self.lowered(self.gate(repo)))


class TestStopWithLogsFile(RetireCase):
    def test_stop_accepts_committed_logs_file_when_branch_has_no_upstream(self):
        repo = self.session_repo(remote=False)
        self.write_progress(repo, directory="progress-logs")
        self.commit_all(repo)

        result = self.stop(repo)

        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, "", ""))

    def test_stop_reports_empty_next_session_before_commit_advice_for_uncommitted_logs_file(self):
        repo = self.session_repo()
        self.put(repo, NAME1, build(session=SESSION, stamp=self.head(repo)), directory="progress-logs")

        result = self.stop(repo)

        self.assertEqual(result.returncode, 2, out(result))
        self.assertIn("Next Session", result.stderr)
        self.assertIn("- none:", result.stderr)
        self.assertNotIn("commit and push", result.stderr.lower())
        self.assertNotIn("Traceback", result.stderr)


class TestCommitTimeSync(RetireCase):
    def setup_commit(self, owner):
        repo = self.new_repo()
        self.start(repo)
        stale = f"#### 9 {EM} 2020-01-01T00:00:00Z\n> stale request from earlier sync"
        logs = self.write_progress(repo, sid=owner, directory="progress-logs", user_requests=stale)
        self.commit_all(repo, "logs")
        committed = logs.read_text()
        self.prompt(repo, "request made before the commit")
        (repo / "src" / "a.py").write_text("a = 2\n")
        self.git(repo, "add", "--", "src/a.py")
        return repo, logs, committed

    def commit_with_session(self, repo, session):
        return self.git(repo, "commit", "-q", "-m", "work", session=session, check=False)

    def test_v1_commit_with_session_env_rewrites_and_includes_own_logs_file(self):
        repo, logs, committed = self.setup_commit(SESSION)

        result = self.commit_with_session(repo, SESSION)

        self.assertEqual(result.returncode, 0, out(result))
        expected = self.expected_requests(repo)
        self.assertEqual(split_requests(self.blob(repo, "HEAD", LOGS))[1], expected)
        self.assertEqual(logs.read_text(), self.blob(repo, "HEAD", LOGS))
        self.assertEqual(self.git(repo, "status", "--porcelain").stdout, "")
        self.assertNotIn("stale request", self.blob(repo, "HEAD", LOGS))

    def test_v2_commit_without_session_env_leaves_logs_file_alone(self):
        repo, logs, committed = self.setup_commit(SESSION)

        result = self.commit_with_session(repo, None)

        self.assertEqual(result.returncode, 0, out(result))
        self.assertEqual(self.blob(repo, "HEAD", LOGS), committed)
        self.assertEqual(logs.read_text(), committed)
        self.assertEqual(self.git(repo, "status", "--porcelain").stdout, "")

    def test_v3_commit_with_session_env_leaves_other_sessions_logs_file_alone(self):
        repo, logs, committed = self.setup_commit(OTHER)
        self.start(repo, sid=OTHER)
        self.assertEqual(self.prompt(repo, "prompt only the other session recorded", sid=OTHER).returncode, 0)
        self.assertEqual(len(self.state(repo, OTHER)["prompts"]), 1)
        self.assertNotIn("prompt only the other session recorded", committed)

        result = self.commit_with_session(repo, SESSION)

        self.assertEqual(result.returncode, 0, out(result))
        self.assertEqual(self.blob(repo, "HEAD", LOGS), committed)
        self.assertEqual(logs.read_text(), committed)
        self.assertEqual(self.git(repo, "status", "--porcelain").stdout, "")


class TestMergeScenarios(RetireCase):
    def work_session(self):
        repo = self.new_repo()
        base = self.branch(repo)
        bare = self.attach_remote(repo, base)
        self.git(repo, "config", "pull.rebase", "false")
        self.git(repo, "checkout", "-q", "-b", "feat")
        self.git(repo, "push", "-q", "-u", "origin", "feat")
        self.assertEqual(self.start(repo).returncode, 0)
        self.bash(repo, lambda: (repo / "src" / "new.py").write_text("new = 1\n"), event="PostToolUseFailure")

        self.assert_blocked(self.gate(repo), SESSION)
        self.write_progress(repo, post=True)
        self.assert_blocked(self.gate(repo), PROG)
        self.retire_ok(repo)
        self.git(repo, "add", "-A")
        committed = self.git(repo, "commit", "-q", "-m", "work", session=SESSION, check=False)
        self.assertEqual(committed.returncode, 0, out(committed))
        self.assert_blocked(self.gate(repo), NAME1)
        self.git(repo, "push", "-q", "origin", "feat")
        self.assert_allowed(self.gate(repo))
        return repo, base, bare

    def other_clone(self, bare, base):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        clone = Path(tmp.name) / "clone"
        subprocess.run(["git", "clone", "-q", "-b", base, str(bare), str(clone)], check=True, env=self.env())
        self.git(clone, "config", "user.email", "other@test.com")
        self.git(clone, "config", "user.name", "other")
        self.git(clone, "config", "commit.gpgsign", "false")
        return clone

    def pull_master_in_first_clone(self, repo, base):
        self.git(repo, "checkout", "-q", base)
        self.git(repo, "pull", "-q", "origin", base)
        self.assertEqual(self.git(repo, "status", "--porcelain").stdout, "")
        self.assertEqual(list((repo / "agent-docs" / "progress").glob("*.md")), [])
        self.assertTrue((repo / LOGS).is_file())

    def test_m1_no_ff_merge_then_pull_leaves_clean_tree(self):
        repo, base, bare = self.work_session()
        clone = self.other_clone(bare, base)
        self.git(clone, "fetch", "-q", "origin")
        self.git(clone, "merge", "-q", "--no-ff", "-m", "merge feat", "origin/feat")
        self.git(clone, "push", "-q", "origin", base)

        self.pull_master_in_first_clone(repo, base)

    def test_m2_squash_merge_then_pull_leaves_clean_tree(self):
        repo, base, bare = self.work_session()
        clone = self.other_clone(bare, base)
        self.git(clone, "fetch", "-q", "origin")
        self.git(clone, "merge", "-q", "--squash", "origin/feat")
        self.git(clone, "commit", "-q", "-m", "squashed feat")
        self.git(clone, "push", "-q", "origin", base)

        self.pull_master_in_first_clone(repo, base)

    def test_m3_rebase_merge_then_pull_leaves_clean_tree(self):
        repo, base, bare = self.work_session()
        clone = self.other_clone(bare, base)
        (clone / "src" / "other.py").write_text("other = 1\n")
        self.git(clone, "add", "-A")
        self.git(clone, "commit", "-q", "-m", "other work")
        self.git(clone, "push", "-q", "origin", base)
        self.git(clone, "fetch", "-q", "origin")
        self.git(clone, "checkout", "-q", "-b", "feat", "origin/feat")
        self.git(clone, "rebase", "-q", base)
        self.git(clone, "checkout", "-q", base)
        self.git(clone, "merge", "-q", "--ff-only", "feat")
        self.git(clone, "push", "-q", "origin", base)

        self.pull_master_in_first_clone(repo, base)


class TestVersionAndMigration(RetireCase):
    def test_u1_version_file_reads_current_version(self):
        self.assertEqual((REPO_ROOT / "harness" / "VERSION").read_text().strip(), "0.48.0")

    def test_u2_update_from_0_35_0_announces_the_0_36_0_migration(self):
        repo = self.install()
        manifest_path = repo / ".harness" / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["version"] = "0.35.0"
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")

        result = run_installer("update", str(repo), input="y\n" * 9)

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(re.findall(r"^migration (\d+\.\d+\.\d+):", result.stdout, re.MULTILINE), ["0.36.0", "0.37.0", "0.38.0", "0.39.0", "0.40.0", "0.41.0", "0.42.0", "0.43.0", "0.44.0", "0.45.0", "0.47.0", "0.48.0"])
        match = re.search(r"migration 0\.36\.0:(.*?)Apply migration", result.stdout, re.DOTALL)
        self.assertIsNotNone(match, result.stdout)
        text = match.group(1).lower()
        self.assertIn("gh pr create", text)
        self.assertIn("retire", text)
        self.assertIn("progress-logs", text)
        self.assertEqual(json.loads(manifest_path.read_text())["version"], "0.48.0")


class TestConfiguredDocsRoot(RetireCase):
    def configured_repo(self):
        repo = self.session_repo(remote=False)
        (repo / ".harness" / "config.json").write_text(json.dumps({"docs_root": "notes"}))
        return repo

    def put_notes(self, repo, directory):
        path = repo / "notes" / directory / NAME1
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.progress_text(repo))
        return path

    def test_k1_gate_and_retire_act_on_progress_dirs_under_configured_docs_root(self):
        repo = self.configured_repo()
        prog = f"notes/progress/{NAME1}"
        logs = f"notes/progress-logs/{NAME1}"
        path = self.put_notes(repo, "progress")

        blocked = self.gate(repo)

        self.assert_blocked(blocked, prog, f"retire --session {SESSION}")

        self.git(repo, "add", "--", prog)
        self.commit(repo, "tracked progress")
        original = path.read_bytes()

        result = self.retire(repo, "--session", SESSION)

        self.assertEqual(result.returncode, 0, out(result))
        self.assertIn(f"retired: {prog} -> {logs}", result.stdout.splitlines())
        self.assertFalse(path.exists())
        self.assertEqual(self.git(repo, "ls-files", "--", prog).stdout, "")
        self.assertEqual((repo / logs).read_bytes(), original)
        staged = self.git(repo, "ls-files", "-s", "--", logs).stdout.split()[1]
        self.assertEqual(staged, self.git(repo, "hash-object", logs).stdout.strip())
        names = self.git(repo, "diff", "--cached", "--name-status").stdout.splitlines()
        self.assertTrue(any(re.fullmatch(rf"R\d*\t{re.escape(prog)}\t{re.escape(logs)}", line) for line in names), names)
        self.assertFalse((repo / "agent-docs" / "progress-logs" / NAME1).exists())

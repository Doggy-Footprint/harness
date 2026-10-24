import contextlib
import io
import json
import os
import re
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

from evaluation.pr_test_quality.tests.fakes import ROOT, TOKEN, TmpCase, find_str_key, make_task, shipped_config

FIX_PATH = "/usr/bin:/bin"


class Cli(TmpCase):
    def setUp(self):
        super().setUp()
        self.home = self.tmp / "home"
        self.home.mkdir()
        self.bin = self.tmp / "bin"
        self.bin.mkdir()
        self.log = self.tmp / "calls.log"
        self.data = self.home / ".harness" / "evaluation"

    def shim(self, name, body):
        path = self.bin / name
        path.write_text('#!/bin/sh\necho "%s $*" >> "%s"\n%s\n' % (name, self.log, body), encoding="utf-8")
        path.chmod(0o755)

    def calls(self):
        return self.log.read_text(encoding="utf-8").splitlines() if self.log.exists() else []

    def env(self):
        env = {"HOME": str(self.home), "PATH": "%s:%s:%s" % (self.bin, os.path.dirname(sys.executable), FIX_PATH),
               "PYTHONPATH": str(ROOT), "LANG": "C.UTF-8"}
        return env

    def cli(self, *args, timeout=60):
        proc = subprocess.run([sys.executable, "-m", "evaluation.pr_test_quality", *args], cwd=ROOT, env=self.env(),
                              capture_output=True, text=True, timeout=timeout)
        return proc.returncode, proc.stdout + proc.stderr

    def token_location(self):
        hit = find_str_key(shipped_config(), "token")
        if not hit:
            return None, None
        raw = hit[1]
        return raw, Path(raw.replace("~", str(self.home), 1)) if raw.startswith("~") else Path(raw)

    def make_token(self):
        raw, path = self.token_location()
        if path is None or not str(path).startswith(str(self.home)):
            self.skipTest("token file path %r is not under HOME; cannot stage it" % (raw,))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(TOKEN, encoding="utf-8")
        path.chmod(0o600)

    def write_tasks(self, language="python"):
        task = make_task(language, brief={"request": "r", "statements": [], "ambiguous": [], "status": "ok",
                                          "attempts": 1, "reason": ""})
        d = self.data / "tasks" / language
        d.mkdir(parents=True, exist_ok=True)
        (d / "tasks.jsonl").write_text(json.dumps(task) + "\n", encoding="utf-8")
        return task


class MineRateLimit(Cli):
    def test_O26_mine_github_rate_limit_exits_3_and_names_rerun(self):
        self.shim("gh", 'echo "gh: API rate limit exceeded for user ID 1 (HTTP 403)" >&2\n'
                        'echo "X-RateLimit-Reset: 1999999999" >&2\nexit 1')
        code, out = self.cli("mine", "--language", "python")
        self.assertEqual(code, 3, out)
        self.assertIn("mine", out.replace("--language", ""))
        self.assertTrue([c for c in self.calls() if c.startswith("gh")], "gh was never called")


class RunRefusals(Cli):
    def test_O26_missing_image_exits_2_and_names_build_command(self):
        self.make_token()
        self.write_tasks("python")
        self.shim("docker", 'case "$1" in info) exit 0;; version) exit 0;; esac\n'
                            'echo "Error: No such image" >&2\nexit 1')
        code, out = self.cli("run", "--phase", "dev")
        self.assertEqual(code, 2, out)
        self.assertIn("python3 -m evaluation.pr_test_quality build --language python", out)
        self.assertFalse([c for c in self.calls() if re.match(r"docker (run|create|start)\b", c)])

    def test_O26_missing_token_exits_2_names_path_and_starts_no_container(self):
        raw, path = self.token_location()
        self.assertIsNotNone(raw, "shipped config has no token file setting")
        self.write_tasks("python")
        self.shim("docker", 'case "$1" in info) exit 0;; esac\nexit 0')
        code, out = self.cli("run", "--phase", "dev")
        self.assertEqual(code, 2, out)
        self.assertTrue(raw in out or str(path) in out or Path(raw).name in out, out)
        self.assertFalse([c for c in self.calls() if re.match(r"docker (run|create|start)\b", c)])


class ReportRefusals(Cli):
    def run_dir(self, run_id, phase, stored):
        d = self.data / "runs" / run_id
        d.mkdir(parents=True)
        (d / "run.json").write_text(json.dumps({"run_id": run_id, "phase": phase, "prereg_sha256": stored,
                                                "entries": []}), encoding="utf-8")

    def test_O26_C38_main_run_with_edited_prereg_exits_2_naming_both_hashes(self):
        self.run_dir("rid-main", "main", "0" * 64)
        code, out = self.cli("report", "rid-main")
        self.assertEqual(code, 2, out)
        hashes = set(re.findall(r"\b[0-9a-f]{64}\b", out))
        self.assertIn("0" * 64, hashes)
        self.assertGreaterEqual(len(hashes), 2, out)
        self.assertFalse((ROOT / "evaluation" / "pr_test_quality" / "results" / "rid-main.json").exists())


class HaltedExit(Cli):
    def run_main(self, argv, raiser_name):
        from evaluation.pr_test_quality import __main__ as cli
        from evaluation.pr_test_quality import run as run_mod
        run_dir = self.data / "runs" / "rid-halt"
        run_dir.mkdir(parents=True, exist_ok=True)
        try:
            err = run_mod.Halted(run_dir, "rate limit hit")
        except TypeError:
            err = run_mod.Halted("rate limit hit")
            err.run_dir, err.reason = run_dir, "rate limit hit"
        buf = io.StringIO()
        with mock.patch.dict(os.environ, {"HOME": str(self.home)}), \
                mock.patch.object(run_mod, raiser_name, side_effect=err), \
                contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            try:
                code = cli.main(argv)
            except SystemExit as exc:
                code = exc.code
        return code, buf.getvalue()

    def test_O26_halted_run_exits_3_and_names_resume_with_run_id(self):
        self.make_token()
        self.write_tasks("python")
        code, out = self.run_main(["run", "--phase", "dev"], "run")
        self.assertEqual(code, 3, out)
        self.assertIn("--resume rid-halt", out)

    def test_O26_halted_resume_exits_3_and_names_resume_with_run_id(self):
        self.make_token()
        run_dir = self.data / "runs" / "rid-halt"
        run_dir.mkdir(parents=True)
        (run_dir / "run.json").write_text(json.dumps({"run_id": "rid-halt", "phase": "dev", "entries": [],
                                                      "prereg_sha256": "0" * 64}), encoding="utf-8")
        code, out = self.run_main(["run", "--resume", "rid-halt"], "resume")
        self.assertEqual(code, 3, out)
        self.assertIn("--resume rid-halt", out)


class GceRefusals(Cli):
    def setUp(self):
        super().setUp()
        self.shim("gcloud", "exit 0")

    def test_O26_purge_without_yes_exits_2_naming_yes_and_deletes_nothing(self):
        code, out = self.cli("gce", "down", "--purge")
        self.assertEqual(code, 2, out)
        self.assertIn("--yes", out)
        self.assertFalse([c for c in self.calls() if "delete" in c], self.calls())

    def test_O26_purge_with_yes_deletes_vm_disk_and_secret(self):
        code, out = self.cli("gce", "down", "--purge", "--yes")
        self.assertEqual(code, 0, out)
        deletes = " ".join(c for c in self.calls() if "delete" in c)
        for word in ("instances", "disks", "secrets"):
            self.assertIn(word, deletes)

    def test_O26_plain_down_deletes_only_the_vm(self):
        code, out = self.cli("gce", "down")
        self.assertEqual(code, 0, out)
        deletes = " ".join(c for c in self.calls() if "delete" in c)
        self.assertIn("instances", deletes)
        self.assertNotIn("disks", deletes)
        self.assertNotIn("secrets", deletes)


class Doctor(Cli):
    """Hermetic: every external call goes through the injected run_fn, so a real claude/docker/gh is never used."""

    def run_doctor(self, results):
        from evaluation.pr_test_quality import __main__ as cli_main
        from evaluation.pr_test_quality.tests.fakes import FakeRun, set_token_file, spec_cfg
        cfg = spec_cfg(self.tmp / "data")
        token = set_token_file(cfg, self.tmp)
        token.unlink()
        run = FakeRun(lambda argv, inp: results.get(argv[0], (0, "ok 1.0\n", "")))
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            code = cli_main.main(["doctor"], cfg=cfg, deps={"run_fn": run})
        return code, buf.getvalue(), run

    def test_O26_doctor_failure_lines_name_a_fix(self):
        code, out, run = self.run_doctor({"docker": (1, "", "Cannot connect to the Docker daemon"),
                                          "claude": (127, "", "claude: not found")})
        self.assertNotEqual(code, 0)
        lines = out.lower().splitlines()
        fixes = ("install", "start", "login", "auth", "create", "chmod", "mkdir", "export", "python3", "`", "open ")
        for topic in ("docker", "claude", "token"):
            with self.subTest(topic=topic):
                hits = [ln for ln in lines if topic in ln]
                self.assertTrue(hits, out)
                self.assertTrue(any(any(f in ln for f in fixes) for ln in hits), hits)
        self.assertNotIn(TOKEN, out)
        self.assertEqual([a[0] for a in run.argvs], ["docker", "claude", "gh"])

    def test_O26_doctor_never_touches_a_real_binary(self):
        code, out, run = self.run_doctor({})
        self.assertTrue(all(a[0] in ("docker", "claude", "gh") for a in run.argvs))
        self.assertEqual(len(run.argvs), 3)


if __name__ == "__main__":
    unittest.main()

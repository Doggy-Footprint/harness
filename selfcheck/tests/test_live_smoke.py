"""R1 live smoke (VO16): real Claude Code runs on sphinx-doc__sphinx-9602, both arms.

Uses subscription quota; main runs it once with SELFCHECK_LIVE=1. The real token file is read only
to count occurrences of its content; no message, print or log carries the token.
"""
import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from selfcheck import docker_exec, images, manifest, patches
from selfcheck import run as run_mod
from selfcheck.tests import agent_fakes as F

LIVE = os.environ.get("SELFCHECK_LIVE") == "1"
INSTANCE_ID = "sphinx-doc__sphinx-9602"
ARMS = ("harness", "baseline")
TERMINAL_NOT_ERROR = {"completed", "stalled", "capped", "interrupted"}


def agent_cfg():
    return json.loads((F.ROOT / "selfcheck" / "config.json").read_text(encoding="utf-8"))["agent"]


class InspectingDocker:
    """Delegates to the real docker module and keeps `docker inspect` output of every started container."""

    def __init__(self):
        self.inspected = []

    def __getattr__(self, name):
        return getattr(docker_exec, name)

    def start_container(self, *args, **kwargs):
        container = docker_exec.start_container(*args, **kwargs)
        result = subprocess.run(["docker", "inspect", kwargs["name"]], capture_output=True, text=True)
        self.inspected.append(result.stdout)
        return container


def count_in_tree(root, needle):
    total = 0
    for path in Path(root).rglob("*"):
        if path.is_file():
            total += path.read_bytes().count(needle)
    return total


def telemetry_events(raw):
    events = []
    for path in sorted((Path(raw) / "telemetry").rglob("*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                events.append(json.loads(line))
    return events


@unittest.skipUnless(LIVE, "set SELFCHECK_LIVE=1 to run the live smoke (uses subscription quota)")
class LiveSmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cfg = agent_cfg()
        cls.row = F.pool_rows()[INSTANCE_ID]
        images.build_tools_image(cls.cfg)
        images.build_derived_image(cls.row, cls.cfg)
        cls.docker = InspectingDocker()
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            cls.run_dir = run_mod.run(
                [cls.row], list(ARMS), cfg=cls.cfg, model="claude-haiku-5-5", effort="medium", cap_min=45,
                docker=cls.docker,
            )
        cls.captured = out.getvalue() + err.getvalue()
        sys.stderr.write("R1 live smoke run directory: %s\n" % cls.run_dir)
        cls.entries = {arm: cls.run_dir / INSTANCE_ID / arm for arm in ARMS}
        cls.states = {arm: json.loads((path / "state.json").read_text(encoding="utf-8")) for arm, path in cls.entries.items()}
        cls.manifests = {
            arm: json.loads((path / "manifest.json").read_text(encoding="utf-8"))
            for arm, path in cls.entries.items() if (path / "manifest.json").is_file()
        }

    def test_vo16_v1_both_entries_reach_a_terminal_state_other_than_error(self):
        for arm in ARMS:
            with self.subTest(arm=arm):
                self.assertIn(self.states[arm]["status"], TERMINAL_NOT_ERROR)
        listed = json.loads((self.run_dir / "run.json").read_text(encoding="utf-8"))["entries"]
        self.assertEqual([(e["instance_id"], e["arm"]) for e in listed], [(INSTANCE_ID, a) for a in ARMS])
        self.assertEqual([e["status"] in TERMINAL_NOT_ERROR for e in listed], [True, True])

    def test_vo16_v2_manifests_are_filled_and_their_differences_stay_in_the_fr13_set(self):
        self.assertEqual(set(self.manifests), set(ARMS))
        for arm, built in self.manifests.items():
            with self.subTest(arm=arm):
                self.assertEqual(set(built), F.MANIFEST_KEYS)
                nullable = {"harness_commit", "install"} if arm == "baseline" else set()
                empty = [key for key, value in built.items() if value in (None, "", [], {}) and key not in nullable]
                self.assertEqual(empty, [])
                if arm == "baseline":
                    self.assertIsNone(built["harness_commit"])
                    self.assertIsNone(built["install"])
        differing = manifest.differences(self.manifests["harness"], self.manifests["baseline"])
        self.assertLessEqual(differing, F.FR13_DIFFERENCES)

    def test_vo16_v3_harness_arm_telemetry_has_workflow_start_and_an_end_or_a_cap(self):
        events = telemetry_events(self.entries["harness"] / "raw")
        names = [e.get("event") for e in events]
        self.assertIn("workflow_start", names)
        self.assertTrue("workflow_end" in names or self.states["harness"]["status"] == "capped", names)

    def test_vo16_v4_predictions_contain_no_excluded_path(self):
        for arm in ARMS:
            path = self.entries[arm] / "prediction.json"
            if not path.is_file():
                self.assertEqual(self.states[arm]["status"], "interrupted")
                continue
            prediction = json.loads(path.read_text(encoding="utf-8"))
            with self.subTest(arm=arm):
                for key in ("src_diff", "test_patch", "scratch_diff"):
                    for section in patches.file_sections(prediction[key]):
                        path_ = section["old_path"] if section["is_deleted"] else section["path"]
                        self.assertNotEqual(
                            patches.classify_path(path_, self.row["repo"], is_new=section["is_new"]), "excluded", path_
                        )
                        self.assertFalse(path_.startswith((".harness/", ".claude/", "agent-docs/")), path_)

    def test_vo16_v5_selfcheck_score_runs_on_both_predictions_files(self):
        with tempfile.TemporaryDirectory() as directory:
            for arm in ARMS:
                with self.subTest(arm=arm):
                    predictions = self.run_dir / ("predictions.%s.jsonl" % arm)
                    self.assertTrue(predictions.is_file())
                    scored = subprocess.run(
                        [sys.executable, "-m", "selfcheck", "score", "--predictions", str(predictions),
                         "--out", str(Path(directory) / ("score.%s.jsonl" % arm))],
                        cwd=F.ROOT, capture_output=True, text=True, timeout=7200,
                    )
                    self.assertEqual(scored.returncode, 0, scored.stderr[-2000:])

    def test_vo16_v6_the_token_occurs_nowhere_in_the_run_directory_inspect_output_or_run_output(self):
        token_file = Path(os.path.expanduser(self.cfg["token_file"]))
        token = token_file.read_text(encoding="utf-8").strip().encode("utf-8")
        self.assertTrue(token)
        self.assertEqual(count_in_tree(self.run_dir, token), 0)
        self.assertEqual(sum(text.encode("utf-8").count(token) for text in self.docker.inspected), 0)
        self.assertEqual(self.captured.encode("utf-8").count(token), 0)
        self.assertTrue(self.docker.inspected)

    def test_vo16_v7_subagent_calls_in_the_ledger_carry_an_agent_type_when_subagents_were_dispatched(self):
        ledger_path = self.entries["harness"] / "raw" / "ledger.jsonl"
        ledger = F.read_jsonl(ledger_path) if ledger_path.is_file() else []
        dispatched = [l for l in ledger if l["tool_name"] in ("Agent", "Task")]
        if not dispatched:
            self.skipTest("the harness arm dispatched no subagents")
        subagent_calls = [l for l in ledger if l["agent_id"] is not None]
        self.assertTrue(subagent_calls, "subagents were dispatched but no ledger line carries an agent_id")
        self.assertEqual([l["tool_name"] for l in subagent_calls if not l["agent_type"]], [])


if __name__ == "__main__":
    unittest.main()

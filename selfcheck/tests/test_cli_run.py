import contextlib
import io
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from selfcheck import __main__ as cli
from selfcheck import docker_exec, images
from selfcheck import run as run_mod
from selfcheck.tests import agent_fakes as F

POOL_IDS = list(F.pool_rows())
CORE_IDS = [i for i, row in F.pool_rows().items() if row.get("core")]


class BuildBoom(images.ImageBuildError):
    def __init__(self, message):
        Exception.__init__(self, message)


class CliCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="clirun-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.calls = []

    def run_dir(self, statuses, halted=None):
        directory = Path(self.tmp) / ("run%d" % len(list(Path(self.tmp).iterdir())))
        directory.mkdir()
        entries = [{"instance_id": "i%d" % n, "arm": "baseline", "status": s} for n, s in enumerate(statuses)]
        (directory / "run.json").write_text(
            json.dumps({"run_id": directory.name, "entries": entries, "created_at": 0, "halted": halted}),
            encoding="utf-8",
        )
        return directory

    def invoke(self, argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                code = cli.main(argv)
            except SystemExit as exit_:
                code = exit_.code
        return code, out.getvalue(), err.getvalue()

    def fake_run(self, statuses=("completed",), raises=None):
        directory = self.run_dir(statuses)

        def fake(instances, arms, *, cfg, harness_ref="HEAD", model=None, effort=None, cap_min=None, **extra):
            self.calls.append({
                "instances": [row["instance_id"] for row in instances], "arms": list(arms), "cfg": cfg,
                "harness_ref": harness_ref, "model": model, "effort": effort, "cap_min": cap_min,
            })
            if raises is not None:
                raise raises
            return directory

        return fake, directory

    def fake_resume(self, statuses=("completed",), raises=None):
        directory = self.run_dir(statuses)

        def fake(run_id, *, cfg, **extra):
            self.calls.append({"resume": run_id, "cfg": cfg})
            if raises is not None:
                raise raises
            return directory

        return fake, directory


class RunCommandTests(CliCase):
    def test_vo11_l1_defaults_use_core_instances_both_arms_and_head(self):
        fake, directory = self.fake_run()
        with mock.patch.object(run_mod, "run", fake):
            code, out, _ = self.invoke(["run"])
        self.assertEqual(code, 0)
        self.assertEqual(len(self.calls), 1)
        call = self.calls[0]
        self.assertEqual(call["instances"], CORE_IDS)
        self.assertEqual(len(CORE_IDS), 3)
        self.assertEqual(call["arms"], ["harness", "baseline"])
        self.assertEqual(call["harness_ref"], "HEAD")
        self.assertEqual((call["model"], call["effort"], call["cap_min"]), (None, None, None))
        self.assertEqual(call["cfg"], cli.CONFIG["agent"])
        self.assertIn(str(directory), out.splitlines())

    def test_vo11_l2_every_flag_is_forwarded(self):
        ids = POOL_IDS[1:3]
        fake, _ = self.fake_run()
        argv = ["run", "--instances", ",".join(ids), "--arms", "baseline", "--harness-ref", "feature/x",
                "--model", "claude-haiku-5-5", "--effort", "low", "--cap-min", "45"]
        with mock.patch.object(run_mod, "run", fake):
            code, _, _ = self.invoke(argv)
        self.assertEqual(code, 0)
        call = self.calls[0]
        self.assertEqual(call["instances"], ids)
        self.assertEqual(call["arms"], ["baseline"])
        self.assertEqual(call["harness_ref"], "feature/x")
        self.assertEqual(call["model"], "claude-haiku-5-5")
        self.assertEqual(call["effort"], "low")
        self.assertEqual(call["cap_min"], 45)
        self.assertEqual(call["cfg"], cli.CONFIG["agent"])

    def test_vo11_l2_both_arms_flag_keeps_the_given_order(self):
        for arms in ("baseline,harness", "harness,baseline"):
            with self.subTest(arms=arms):
                self.calls.clear()
                fake, _ = self.fake_run()
                with mock.patch.object(run_mod, "run", fake):
                    self.invoke(["run", "--arms", arms])
                self.assertEqual(self.calls[0]["arms"], arms.split(","))

    def test_vo11_l3_exit_code_is_decided_from_the_run_json_statuses(self):
        cases = (
            ("all terminal states are 0", ["completed", "stalled", "capped", "interrupted"], 0),
            ("a single completed entry", ["completed"], 0),
            ("an error entry is 1", ["completed", "error", "capped"], 1),
            ("only errors", ["error", "error"], 1),
        )
        for name, statuses, expected in cases:
            with self.subTest(name):
                fake, _ = self.fake_run(statuses)
                with mock.patch.object(run_mod, "run", fake):
                    code, _, _ = self.invoke(["run"])
                self.assertEqual(code, expected)

    def test_vo11_l3_resume_uses_the_same_exit_codes(self):
        for statuses, expected in ((["completed", "interrupted"], 0), (["completed", "error"], 1)):
            with self.subTest(statuses=statuses):
                fake, directory = self.fake_resume(statuses)
                with mock.patch.object(run_mod, "resume", fake):
                    code, out, _ = self.invoke(["run", "--resume", "abc123"])
                self.assertEqual(code, expected)
                self.assertIn(str(directory), out.splitlines())

    def test_vo11_l3_run_resume_forwards_the_run_id_and_never_starts_a_new_run(self):
        fake, _ = self.fake_resume()
        boom, _ = self.fake_run()
        with mock.patch.object(run_mod, "resume", fake), mock.patch.object(run_mod, "run", boom):
            self.invoke(["run", "--resume", "0123456789abcdef"])
        self.assertEqual(self.calls, [{"resume": "0123456789abcdef", "cfg": cli.CONFIG["agent"]}])

    def test_vo11_l3_token_file_and_docker_errors_print_to_stderr_and_exit_1(self):
        for name, error in (
            ("token", run_mod.TokenFileMissing("token file missing: /nowhere/oauth_token")),
            ("docker", docker_exec.DockerError("proxy could not be started: daemon exploded")),
        ):
            for command in ("run", "resume"):
                with self.subTest(name=name, command=command):
                    patched = self.fake_run(raises=error)[0] if command == "run" else self.fake_resume(raises=error)[0]
                    argv = ["run"] if command == "run" else ["run", "--resume", "abc"]
                    with mock.patch.object(run_mod, command, patched):
                        code, out, err = self.invoke(argv)
                    self.assertEqual(code, 1)
                    self.assertIn(str(error), err)
                    self.assertNotIn(str(error), out)

    def test_vo11_l3_usage_errors_exit_2(self):
        for argv in (
            ["run", "--no-such-flag"],
            ["run", "--cap-min", "forty"],
            ["run", "--instances"],
            ["run", "--arms", "bogus"],
            ["run", "--arms", "harness,bogus"],
            ["images", "--agent", "--no-such-flag"],
        ):
            with self.subTest(argv=argv):
                fake, _ = self.fake_run()
                with mock.patch.object(run_mod, "run", fake):
                    code, _, _ = self.invoke(argv)
                self.assertEqual(code, 2)
                self.assertEqual(self.calls, [])

    def test_vo11_l4_unknown_run_id_prints_exactly_the_message_and_exits_2(self):
        for run_id in ("abc123", "0123456789abcdef"):
            with self.subTest(run_id):
                self.calls.clear()
                fake, _ = self.fake_resume(raises=run_mod.UnknownRunError(run_id))
                with mock.patch.object(run_mod, "resume", fake):
                    code, out, err = self.invoke(["run", "--resume", run_id])
                self.assertEqual(code, 2)
                self.assertEqual(err, "unknown run id: %s\n" % run_id)
                self.assertEqual(out, "")


class ImagesAgentTests(CliCase):
    def fakes(self, failing=()):
        built = {"tools": [], "derived": []}

        def tools(*args, **kwargs):
            cfg = kwargs["cfg"] if "cfg" in kwargs else args[0]
            built["tools"].append(cfg)
            return "selfcheck-tools:aaaaaaaaaaaa"

        def derived(*args, **kwargs):
            instance = kwargs["instance"] if "instance" in kwargs else args[0]
            cfg = kwargs["cfg"] if "cfg" in kwargs else args[1]
            built["derived"].append((instance["instance_id"], cfg))
            if instance["instance_id"] in failing:
                raise BuildBoom("image build failed for %s: last log line" % instance["instance_id"])
            return "selfcheck-agent.arm64.%s:bbbbbbbbbbbb" % instance["instance_id"].lower()

        return tools, derived, built

    @staticmethod
    def lines_for(ids):
        return ["%s selfcheck-agent.arm64.%s:bbbbbbbbbbbb" % (i, i.lower()) for i in ids]

    def invoke_images(self, argv, failing=()):
        tools, derived, built = self.fakes(failing)
        with mock.patch.object(images, "build_tools_image", tools), mock.patch.object(images, "build_derived_image", derived):
            result = self.invoke(argv)
        return result, built

    def test_vo11_l5_default_builds_the_tools_image_and_prints_one_line_per_derived_image_only(self):
        (code, out, _), built = self.invoke_images(["images", "--agent"])
        self.assertEqual(code, 0)
        self.assertEqual(len(built["tools"]), 1)
        self.assertEqual(built["tools"][0], cli.CONFIG["agent"])
        self.assertEqual([i for i, _ in built["derived"]], POOL_IDS)
        self.assertEqual(len(POOL_IDS), 6)
        for instance_id, cfg in built["derived"]:
            self.assertEqual(cfg, cli.CONFIG["agent"])
        self.assertEqual(out.splitlines(), self.lines_for(POOL_IDS))

    def test_vo11_l2_instances_flag_restricts_the_derived_images(self):
        ids = POOL_IDS[:2]
        (code, out, _), built = self.invoke_images(["images", "--agent", "--instances", ",".join(ids)])
        self.assertEqual(code, 0)
        self.assertEqual([i for i, _ in built["derived"]], ids)
        self.assertEqual(out.splitlines(), self.lines_for(ids))
        for instance_id in POOL_IDS[2:]:
            self.assertNotIn(instance_id, out)

    def test_vo11_l3_a_failed_build_exits_1_and_the_other_images_are_still_attempted(self):
        failing = {POOL_IDS[1]}
        (code, out, err), built = self.invoke_images(["images", "--agent"], failing=failing)
        self.assertEqual(code, 1)
        self.assertEqual([i for i, _ in built["derived"]], POOL_IDS)
        self.assertIn(POOL_IDS[1], err)
        self.assertEqual(out.splitlines(), self.lines_for([i for i in POOL_IDS if i not in failing]))


if __name__ == "__main__":
    unittest.main()

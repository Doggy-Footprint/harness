import copy
import hashlib
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from selfcheck import manifest
from selfcheck.tests import agent_fakes as F

TOKEN = "tok-manifest-secret-0123456789abcdef"
PROBLEM = "The problem text.\n\nSecond paragraph."
INSTANCE = {"instance_id": "sphinx-doc__sphinx-9602", "repo": "sphinx-doc/sphinx", "problem_statement": PROBLEM}
FREEZE_BEFORE = "alpha==1.0\nbeta==2.0\n"
FREEZE_AFTER = "alpha==1.0\nbeta==2.0\n\nzeta-new==3.0\nhypothesis==6.1\n"
INSTALL = {"hooks_path": ".githooks", "pre_commit_config_present": True, "definition_replaced": True}
IMAGES = {
    "instance_image_id": "sha256:inst", "tools_image_id": "sha256:tools",
    "derived_image": "selfcheck-agent.arm64.sphinx-doc__sphinx-9602:0123456789ab",
    "derived_image_id": "sha256:derived", "freeze_before": FREEZE_BEFORE, "freeze_after": FREEZE_AFTER,
}
PROXY = {"allow_hosts": ["api.anthropic.com"], "proxy_image": F.SPEC_AGENT_CFG["proxy_image"], "squid_conf_hash": "ab" * 32}
TEMPLATE_TAIL = "{problem}" + F.PROMPT_SUFFIX


def prompt_for(arm):
    return F.expected_prompt(INSTANCE, arm)


def driver_state():
    state = F.driver_state_dict()
    state["env"] = {"CLAUDE_CODE_OAUTH_TOKEN": TOKEN, "PATH": "/x"}
    return state


class ManifestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="manifest-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.user_sim = Path(self.tmp) / "user_sim.py"
        self.driver = Path(self.tmp) / "driver.py"
        self.user_sim.write_bytes(b"# user sim v1\n\xff\x00\n")
        self.driver.write_bytes(b"# driver v1\n")
        patcher = mock.patch.object(manifest, "USER_SIM_FILES", (self.user_sim, self.driver))
        patcher.start()
        self.addCleanup(patcher.stop)

    def build(self, arm="harness", **over):
        kwargs = dict(
            run_id="0123456789abcdef", instance=INSTANCE, arm=arm, cfg=F.cfg_copy(),
            selfcheck_commit="c" * 40, harness_ref="HEAD",
            harness_commit=("d" * 40) if arm == "harness" else None,
            start_commit=F.INSTALL_HEAD if arm == "harness" else F.BASE_HEAD,
            install=dict(INSTALL) if arm == "harness" else None,
            images=copy.deepcopy(IMAGES), proxy=copy.deepcopy(PROXY), driver_state=driver_state(),
            prompt=prompt_for(arm),
        )
        kwargs.update(over)
        return manifest.build(**kwargs)


class BuildTests(ManifestCase):
    def test_vo8_m1_every_key_is_present_with_the_specified_values(self):
        cfg = F.cfg_copy()
        built = self.build("harness")
        self.assertEqual(set(built), F.MANIFEST_KEYS)
        hasher = hashlib.sha256()
        hasher.update(self.user_sim.read_bytes())
        hasher.update(self.driver.read_bytes())
        self.assertEqual(built["run_id"], "0123456789abcdef")
        self.assertEqual(built["instance_id"], "sphinx-doc__sphinx-9602")
        self.assertEqual(built["arm"], "harness")
        self.assertEqual(built["selfcheck_commit"], "c" * 40)
        self.assertEqual(built["harness_ref"], "HEAD")
        self.assertEqual(built["harness_commit"], "d" * 40)
        self.assertEqual(built["start_commit"], F.INSTALL_HEAD)
        self.assertEqual(built["install"], INSTALL)
        self.assertEqual(built["model"], cfg["model"])
        self.assertEqual(built["effort"], cfg["effort"])
        self.assertEqual(built["aliases"], cfg["aliases"])
        self.assertEqual(built["sdk"], cfg["sdk"])
        self.assertEqual(built["cli_version"], "2.1.294")
        self.assertEqual(built["tools"], F.INIT_DATA["tools"])
        self.assertEqual(built["disallowed_tools"], cfg["disallowed_tools"])
        self.assertEqual(
            built["caps"],
            {"wall_clock_min": cfg["wall_clock_min"], "max_user_turns": cfg["max_user_turns"], "idle_grace_s": cfg["idle_grace_s"]},
        )
        self.assertEqual(set(built["container"]), {"cpus", "memory", "user"})
        self.assertEqual(built["container"]["cpus"], cfg["cpus"])
        self.assertEqual(built["container"]["memory"], cfg["memory"])
        self.assertIn(built["container"]["user"], ("nonroot", "1000", 1000))
        self.assertEqual(built["env_keys"], sorted(F.SPEC_ENV_KEYS))
        self.assertEqual(built["prompt_template_hash"], hashlib.sha256((F.HARNESS_PREFIX + TEMPLATE_TAIL).encode("utf-8")).hexdigest())
        self.assertEqual(built["user_sim_hash"], hasher.hexdigest())
        self.assertEqual(
            built["images"],
            {
                "instance_image_id": "sha256:inst", "tools_image_id": "sha256:tools",
                "derived_image": IMAGES["derived_image"], "derived_image_id": "sha256:derived",
                "testbed_tools_resolved": ["zeta-new==3.0", "hypothesis==6.1"],
            },
        )
        self.assertEqual(built["network"], PROXY)

    def test_vo8_m1_values_follow_the_inputs_not_constants(self):
        cfg = F.cfg_copy(model="claude-haiku-5-5", effort="low", wall_clock_min=45, max_user_turns=2, idle_grace_s=30,
                         cpus=2, memory="3g", sdk="claude-agent-sdk==9.9.9", aliases={"opus": "o", "sonnet": "s", "haiku": "h"},
                         disallowed_tools=["WebFetch"])
        state = F.driver_state_dict(cli_version="7.7.7", init=F.init_summary(tools=["Only"]), env_keys=["A", "B"])
        built = self.build("baseline", cfg=cfg, driver_state=state, run_id="f" * 16, selfcheck_commit="e" * 40,
                           harness_ref="HEAD~1", start_commit="9" * 40)
        self.assertEqual(built["model"], "claude-haiku-5-5")
        self.assertEqual(built["effort"], "low")
        self.assertEqual(built["caps"], {"wall_clock_min": 45, "max_user_turns": 2, "idle_grace_s": 30})
        self.assertEqual(built["container"]["cpus"], 2)
        self.assertEqual(built["container"]["memory"], "3g")
        self.assertEqual(built["sdk"], "claude-agent-sdk==9.9.9")
        self.assertEqual(built["aliases"], {"opus": "o", "sonnet": "s", "haiku": "h"})
        self.assertEqual(built["disallowed_tools"], ["WebFetch"])
        self.assertEqual(built["cli_version"], "7.7.7")
        self.assertEqual(built["tools"], ["Only"])
        self.assertEqual(built["env_keys"], ["A", "B"])
        self.assertEqual(built["run_id"], "f" * 16)
        self.assertEqual(built["selfcheck_commit"], "e" * 40)
        self.assertEqual(built["harness_ref"], "HEAD~1")
        self.assertEqual(built["start_commit"], "9" * 40)

    def test_vo8_m2_baseline_has_null_harness_commit_and_install(self):
        built = self.build("baseline")
        self.assertEqual(set(built), F.MANIFEST_KEYS)
        self.assertIsNone(built["harness_commit"])
        self.assertIsNone(built["install"])
        self.assertEqual(built["start_commit"], F.BASE_HEAD)
        self.assertEqual(built["arm"], "baseline")
        self.assertEqual(
            built["prompt_template_hash"], hashlib.sha256(TEMPLATE_TAIL.encode("utf-8")).hexdigest()
        )

    def test_vo8_m3_env_keys_are_names_only(self):
        built = self.build("harness")
        self.assertEqual(built["env_keys"], sorted(F.SPEC_ENV_KEYS))
        for name in built["env_keys"]:
            self.assertIsInstance(name, str)
            self.assertNotIn("=", name)

    def test_vo8_m4_hashes_are_stable_for_equal_inputs_and_change_with_their_inputs(self):
        base = self.build("harness")
        again = self.build("harness")
        self.assertEqual(base["prompt_template_hash"], again["prompt_template_hash"])
        self.assertEqual(base["user_sim_hash"], again["user_sim_hash"])

        with self.subTest("template: prefix"):
            self.assertNotEqual(base["prompt_template_hash"], self.build("baseline")["prompt_template_hash"])
        with self.subTest("template: independent of the problem statement"):
            other = dict(INSTANCE, problem_statement="Totally different problem")
            changed = self.build("harness", instance=other, prompt=F.expected_prompt(other, "harness"))
            self.assertEqual(changed["prompt_template_hash"], base["prompt_template_hash"])
        with self.subTest("template: changed wording"):
            tweaked = self.build("harness", prompt=prompt_for("harness").replace("Resolve", "Fix"))
            self.assertNotEqual(tweaked["prompt_template_hash"], base["prompt_template_hash"])
        with self.subTest("user_sim change"):
            self.user_sim.write_bytes(b"# user sim v2\n")
            after_sim = self.build("harness")
            self.assertNotEqual(after_sim["user_sim_hash"], base["user_sim_hash"])
        with self.subTest("driver change"):
            self.driver.write_bytes(b"# driver v2\n")
            after_driver = self.build("harness")
            self.assertNotEqual(after_driver["user_sim_hash"], after_sim["user_sim_hash"])

    def test_vo8_m4_user_sim_hash_is_sha256_over_the_two_files_in_order(self):
        built = self.build("harness")
        first, second = self.user_sim.read_bytes(), self.driver.read_bytes()
        self.assertEqual(built["user_sim_hash"], hashlib.sha256(first + second).hexdigest())
        self.assertNotEqual(built["user_sim_hash"], hashlib.sha256(second + first).hexdigest())

    def test_vo8_m5_two_arm_differences_stay_inside_the_fr13_set(self):
        harness, baseline = self.build("harness"), self.build("baseline")
        differing = manifest.differences(harness, baseline)
        self.assertLessEqual(differing, F.FR13_DIFFERENCES)
        self.assertEqual(differing, {"arm", "harness_commit", "start_commit", "install", "prompt_template_hash"})

    def test_vo8_m5_differences_reports_top_level_keys_whose_values_differ(self):
        harness = self.build("harness")
        changed = copy.deepcopy(harness)
        changed["model"] = "other"
        changed["caps"]["max_user_turns"] = 99
        self.assertEqual(manifest.differences(harness, changed), {"model", "caps"})
        self.assertEqual(manifest.differences(harness, copy.deepcopy(harness)), set())

    def test_vo8_m6_serialized_manifest_contains_no_token_value(self):
        for arm in ("harness", "baseline"):
            with self.subTest(arm):
                built = self.build(arm)
                self.assertNotIn(TOKEN, json.dumps(built))

    def test_vo8_m7_testbed_tools_resolved_is_freeze_after_minus_freeze_before(self):
        cases = (
            ("new lines in after-order, blanks dropped", "a==1\nb==2\n", "a==1\nb==2\n\nz==3\nh==6\n", ["z==3", "h==6"]),
            ("changed version is a new line", "a==1\nb==2\n", "a==2\nb==2\n", ["a==2"]),
            ("nothing new", "a==1\n", "a==1\n", []),
            ("removed lines never listed", "a==1\nb==2\n", "a==1\n", []),
        )
        for name, before, after, expected in cases:
            with self.subTest(name):
                images = dict(copy.deepcopy(IMAGES), freeze_before=before, freeze_after=after)
                built = self.build("harness", images=images)
                self.assertEqual(built["images"]["testbed_tools_resolved"], expected)
                self.assertNotIn("freeze_before", built["images"])
                self.assertNotIn("freeze_after", built["images"])


AGENT_DIR = F.ROOT / "selfcheck" / "agent"
BASELINE_FIXTURE = F.ROOT / "selfcheck" / "fixtures" / "baseline" / "246588b0e19680ee" / "manifest.json"


def real_hash(*names):
    digest = hashlib.sha256()
    for name in names:
        digest.update((AGENT_DIR / name).read_bytes())
    return digest.hexdigest()


class InformedManifestTests(unittest.TestCase):
    """Spec 54ad633104783ebe O3 (R4, C5). No patching: the hashes are over the real agent files."""

    def build(self, **over):
        kwargs = dict(
            run_id="0123456789abcdef", instance=INSTANCE, arm="harness", cfg=F.cfg_copy(),
            selfcheck_commit="c" * 40, harness_ref="HEAD", harness_commit="d" * 40, start_commit=F.INSTALL_HEAD,
            install=dict(INSTALL), images=copy.deepcopy(IMAGES), proxy=copy.deepcopy(PROXY),
            driver_state=driver_state(), prompt=prompt_for("harness"),
        )
        kwargs.update(over)
        return manifest.build(**kwargs)

    def test_o3_unassisted_output_is_unchanged(self):
        for label, kw in (("default", {}), ("explicit", {"user_mode": "unassisted"})):
            with self.subTest(label):
                built = self.build(**kw)
                self.assertEqual(set(built), F.MANIFEST_KEYS)
                self.assertNotIn("user_mode", built)
                self.assertEqual(built["user_sim_hash"], real_hash("user_sim.py", "driver.py"))

    def test_o3_unassisted_hash_equals_the_recorded_baseline_fixture(self):
        recorded = json.loads(BASELINE_FIXTURE.read_text(encoding="utf-8"))["conditions"]["user_sim_hash"]
        self.assertEqual(self.build()["user_sim_hash"], recorded)

    def test_o3_informed_adds_the_key_and_hashes_three_files_in_order(self):
        built = self.build(user_mode="informed")
        self.assertEqual(set(built), F.MANIFEST_KEYS | {"user_mode"})
        self.assertEqual(built["user_mode"], "informed")
        order = ("user_sim.py", "driver.py", "informed_driver.py")
        self.assertEqual(built["user_sim_hash"], real_hash(*order))
        self.assertNotEqual(built["user_sim_hash"], real_hash("informed_driver.py", "driver.py", "user_sim.py"))
        self.assertNotEqual(built["user_sim_hash"], real_hash("user_sim.py", "driver.py"))

    def test_o3_informed_differs_from_unassisted_only_in_user_mode_and_hash(self):
        self.assertEqual(manifest.differences(self.build(), self.build(user_mode="informed")),
                         {"user_mode", "user_sim_hash"})

    def test_o3_fixture_id_differs_between_modes(self):
        from selfcheck import fixture
        plain = fixture.fixture_id(fixture.conditions(self.build()))
        inf = fixture.fixture_id(fixture.conditions(self.build(user_mode="informed")))
        self.assertNotEqual(plain, inf)
        self.assertEqual(plain, fixture.fixture_id(fixture.conditions(self.build())))


if __name__ == "__main__":
    unittest.main()

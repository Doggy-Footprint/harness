"""VO4 (state transition: assemble/create) and VO5 (equivalence partitioning: compare/find/precheck)."""
import copy
import json
import os
import shutil
import tempfile
import unittest
from unittest import mock
from pathlib import Path

from selfcheck import fixture
from selfcheck.tests import agent_fakes as F
from selfcheck.tests import m3_fakes as m

IIDS = ["a-1", "b-2"]
SHARED_IMAGES = m.images_for("shared")
NOW = 1700000000.0


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def score_of(prediction):
    return {"instance_id": prediction["instance_id"], "resolved": True, "from_run": prediction["run_id"]}


class Calls:
    def __init__(self, fn=score_of):
        self.fn = fn
        self.args = []

    def __call__(self, prediction):
        self.args.append(copy.deepcopy(prediction))
        return self.fn(prediction)


def baseline_entry(iid, run_id, *, status="completed", with_prediction=True, with_manifest=True, **manifest_over):
    return {
        "instance_id": iid, "arm": "baseline", "status": status,
        "manifest": m.manifest(iid, "baseline", run_id, **manifest_over) if with_manifest else None,
        "state": m.state(status),
        "prediction": m.prediction(iid, "baseline", run_id) if with_prediction else None,
    }


class AssembleCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="fixasm-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.runs = Path(self.tmp) / "runs"
        self.out = Path(self.tmp) / "fixtures"
        self.token = F.dummy_token()

    def run_dir(self, run_id, entries, extra_entries=()):
        return m.write_run(self.runs, run_id, list(entries) + list(extra_entries))

    def two_runs(self, **over):
        """Repeat 1 and 2 over IIDS; `over` maps repeat number -> per-entry overrides."""
        dirs = []
        for k in (1, 2):
            rid = "run%dxxxxxxxxxxxxxx" % k
            entries = [baseline_entry(iid, rid, **over.get(k, {})) for iid in IIDS]
            dirs.append(self.run_dir(rid, entries))
        return dirs

    def assemble(self, dirs, score_fn=None, token=None):
        return fixture.assemble(dirs, score_fn=score_fn or Calls(), out_root=self.out,
                                token=token or self.token, now=lambda: NOW)

    def conds(self):
        return m.conditions_of(m.manifest("a-1", "baseline", "x"))


class AssembleTests(AssembleCase):
    def test_vo4_t6_c11_two_runs_write_manifest_predictions_and_scores(self):
        dirs = self.two_runs()
        harness_noise = {"instance_id": "a-1", "arm": "harness", "status": "completed",
                         "manifest": m.manifest("a-1", "harness", "run1xxxxxxxxxxxxxx", model="never-read"),
                         "state": m.state(), "prediction": m.prediction("a-1", "harness", "run1xxxxxxxxxxxxxx")}
        m.write_run(self.runs, "run1xxxxxxxxxxxxxx",
                    [baseline_entry(i, "run1xxxxxxxxxxxxxx") for i in IIDS] + [harness_noise])
        calls = Calls()
        directory = self.assemble(dirs, calls)
        conds = self.conds()
        fid = m.fixture_id_of(conds)
        self.assertEqual(directory, self.out / fid)
        manifest = read_json(directory / "manifest.json")
        self.assertEqual(manifest["fixture_id"], fid)
        self.assertEqual(manifest["conditions"], conds)
        self.assertEqual(manifest["images"], {iid: m.images_for(iid) for iid in IIDS})
        self.assertEqual(manifest["runs"], ["run1xxxxxxxxxxxxxx", "run2xxxxxxxxxxxxxx"])
        self.assertEqual(manifest["repeats"], 2)
        self.assertEqual(manifest["instances"], IIDS)
        self.assertEqual(manifest["created_at"], NOW)

        lines = [json.loads(l) for l in (directory / "predictions.jsonl").read_text(encoding="utf-8").splitlines()]
        want = []
        for iid in IIDS:
            for k in (1, 2):
                row = m.prediction(iid, "baseline", "run%dxxxxxxxxxxxxxx" % k)
                row["repeat"] = k
                want.append(row)
        self.assertEqual(lines, want)

        scores = read_json(directory / "scores.json")
        self.assertEqual(scores, {
            iid: [{"repeat": k, "run_id": "run%dxxxxxxxxxxxxxx" % k, "status": "completed",
                   "score": score_of(m.prediction(iid, "baseline", "run%dxxxxxxxxxxxxxx" % k))}
                  for k in (1, 2)]
            for iid in IIDS
        })
        self.assertEqual(len(calls.args), 4)
        for arg in calls.args:
            self.assertEqual({k: v for k, v in arg.items() if k != "repeat"},
                             m.prediction(arg["instance_id"], "baseline", arg["run_id"]))

    def test_vo4_t6_f1_instances_and_predictions_are_sorted_whatever_the_run_json_order(self):
        rid1, rid2 = "run1xxxxxxxxxxxxxx", "run2xxxxxxxxxxxxxx"
        order1, order2 = ["z-9", "m-5", "a-1"], ["a-1", "z-9", "m-5"]
        d1 = self.run_dir(rid1, [baseline_entry(i, rid1) for i in order1])
        d2 = self.run_dir(rid2, [baseline_entry(i, rid2) for i in order2])
        directory = self.assemble([d2, d1])
        manifest = read_json(directory / "manifest.json")
        self.assertEqual(manifest["instances"], ["a-1", "m-5", "z-9"])
        self.assertEqual(manifest["runs"], [rid2, rid1])
        lines = [json.loads(l) for l in (directory / "predictions.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertEqual([(l["instance_id"], l["repeat"], l["run_id"]) for l in lines],
                         [(i, k, r) for i in ("a-1", "m-5", "z-9") for k, r in ((1, rid2), (2, rid1))])
        scores = read_json(directory / "scores.json")
        for iid in scores:
            self.assertEqual([(r["repeat"], r["run_id"]) for r in scores[iid]], [(1, rid2), (2, rid1)])

    def test_vo4_t6_c11_error_entry_is_kept_with_a_null_score_and_no_prediction_line(self):
        rid1, rid2 = "run1xxxxxxxxxxxxxx", "run2xxxxxxxxxxxxxx"
        d1 = self.run_dir(rid1, [baseline_entry(i, rid1) for i in IIDS])
        d2 = self.run_dir(rid2, [baseline_entry("a-1", rid2),
                                 baseline_entry("b-2", rid2, status="error", with_prediction=False)])
        calls = Calls()
        directory = self.assemble([d1, d2], calls)
        scores = read_json(directory / "scores.json")
        self.assertEqual(scores["b-2"][1], {"repeat": 2, "run_id": rid2, "status": "error", "score": None})
        self.assertIsNotNone(scores["b-2"][0]["score"])
        lines = [json.loads(l) for l in (directory / "predictions.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertEqual([(l["instance_id"], l["repeat"]) for l in lines],
                         [("a-1", 1), ("a-1", 2), ("b-2", 1)])
        self.assertEqual(len(calls.args), 3)

    def test_vo4_t6_an_entry_without_a_manifest_is_tolerated_when_another_repeat_has_one(self):
        rid1, rid2 = "run1xxxxxxxxxxxxxx", "run2xxxxxxxxxxxxxx"
        d1 = self.run_dir(rid1, [baseline_entry(i, rid1) for i in IIDS])
        d2 = self.run_dir(rid2, [baseline_entry("a-1", rid2),
                                 baseline_entry("b-2", rid2, status="error", with_prediction=False, with_manifest=False)])
        directory = self.assemble([d1, d2])
        self.assertEqual(read_json(directory / "manifest.json")["images"]["b-2"], m.images_for("b-2"))

    def test_vo4_t6_exempt_differences_between_runs_do_not_block_assembly(self):
        rid1, rid2 = "run1xxxxxxxxxxxxxx", "run2xxxxxxxxxxxxxx"
        d1 = self.run_dir(rid1, [baseline_entry(i, rid1) for i in IIDS])
        d2 = self.run_dir(rid2, [baseline_entry(i, rid2, selfcheck_commit="9" * 40, start_commit="8" * 40,
                                                prompt_template_hash="q" * 16, harness_ref="other")
                                 for i in IIDS])
        directory = self.assemble([d1, d2])
        self.assertEqual(directory.name, m.fixture_id_of(self.conds()))

    def test_vo4_t8_c12_conditions_that_differ_raise_naming_the_keys_and_write_nothing(self):
        for key, value in (("cli_version", "9.9.9"), ("model", "claude-haiku-5-5")):
            with self.subTest(key=key):
                rid1, rid2 = "run1%sxxxxxxxx" % key[:3], "run2%sxxxxxxxx" % key[:3]
                d1 = self.run_dir(rid1, [baseline_entry(i, rid1) for i in IIDS])
                d2 = self.run_dir(rid2, [baseline_entry(i, rid2, **{key: value}) for i in IIDS])
                with self.assertRaises(fixture.FixtureError) as caught:
                    self.assemble([d1, d2])
                self.assertIn(key, str(caught.exception))
                self.assertEqual(m.tree(self.out), {})

    def test_vo4_t8_g5_conditions_differing_only_between_the_first_and_second_manifest_raise(self):
        rid1, rid2 = "run1xxxxxxxxxxxxxx", "run2xxxxxxxxxxxxxx"
        d1 = self.run_dir(rid1, [baseline_entry("a-1", rid1)])
        d2 = self.run_dir(rid2, [baseline_entry("a-1", rid2, cli_version="9.9.9")])
        with self.assertRaises(fixture.FixtureError) as caught:
            self.assemble([d1, d2])
        self.assertIn("cli_version", str(caught.exception))
        self.assertEqual(m.tree(self.out), {})

    def test_vo4_t8_two_differing_keys_are_both_named(self):
        rid1, rid2 = "run1xxxxxxxxxxxxxx", "run2xxxxxxxxxxxxxx"
        d1 = self.run_dir(rid1, [baseline_entry(i, rid1) for i in IIDS])
        d2 = self.run_dir(rid2, [baseline_entry(i, rid2, effort="high", network="other-net") for i in IIDS])
        with self.assertRaises(fixture.FixtureError) as caught:
            self.assemble([d1, d2])
        self.assertIn("effort", str(caught.exception))
        self.assertIn("network", str(caught.exception))

    def test_vo4_t9_c12_images_that_differ_per_instance_raise_and_write_nothing(self):
        rid1, rid2 = "run1xxxxxxxxxxxxxx", "run2xxxxxxxxxxxxxx"
        d1 = self.run_dir(rid1, [baseline_entry(i, rid1) for i in IIDS])
        changed = dict(m.images_for("b-2"), derived="selfcheck-agent.arm64.b-2:cccccccccccc")
        d2 = self.run_dir(rid2, [baseline_entry("a-1", rid2), baseline_entry("b-2", rid2, images=changed)])
        with self.assertRaises(fixture.FixtureError):
            self.assemble([d1, d2])
        self.assertEqual(m.tree(self.out), {})

    def test_vo4_t10_c12_an_existing_fixture_directory_raises_and_stays_untouched(self):
        dirs = self.two_runs()
        existing = self.out / m.fixture_id_of(self.conds())
        existing.mkdir(parents=True)
        (existing / "keep.txt").write_text("keep", encoding="utf-8")
        before = m.tree(self.out)
        with self.assertRaises(fixture.FixtureError):
            self.assemble(dirs)
        self.assertEqual(m.tree(self.out), before)

    def test_vo4_t11_c12_token_in_a_prediction_raises_and_writes_nothing(self):
        rid1, rid2 = "run1xxxxxxxxxxxxxx", "run2xxxxxxxxxxxxxx"
        leaky = baseline_entry("a-1", rid1)
        leaky["prediction"] = m.prediction("a-1", "baseline", rid1, src_diff="leak %s end" % self.token)
        d1 = self.run_dir(rid1, [leaky, baseline_entry("b-2", rid1)])
        d2 = self.run_dir(rid2, [baseline_entry(i, rid2) for i in IIDS])
        with self.assertRaises(fixture.FixtureError):
            self.assemble([d1, d2])
        self.assertEqual(m.tree(self.out), {})

    def test_vo4_t11_c12_token_in_a_score_raises_and_writes_nothing(self):
        dirs = self.two_runs()
        leaky = Calls(lambda p: {"instance_id": p["instance_id"], "note": "x%sx" % self.token})
        with self.assertRaises(fixture.FixtureError):
            self.assemble(dirs, leaky)
        self.assertEqual(m.tree(self.out), {})

    def test_vo4_t11_a2_token_only_in_a_manifest_field_raises_and_writes_nothing(self):
        for label, over in (("conditions", {"network": "net-%s"}),
                            ("images", {"images": {"tools": "t-%s", "derived": "d"}})):
            with self.subTest(label):
                shutil.rmtree(self.runs, ignore_errors=True)
                planted = {k: (v % self.token if isinstance(v, str) else {a: (b % self.token if "%s" in b else b)
                                                                          for a, b in v.items()})
                           for k, v in over.items()}
                rid1, rid2 = "run1xxxxxxxxxxxxxx", "run2xxxxxxxxxxxxxx"
                d1 = self.run_dir(rid1, [baseline_entry(i, rid1, **planted) for i in ["a-1"]])
                d2 = self.run_dir(rid2, [baseline_entry(i, rid2, **planted) for i in ["a-1"]])
                with self.assertRaises(fixture.FixtureError):
                    self.assemble([d1, d2])
                self.assertEqual(m.tree(self.out), {})

    def test_vo4_t11_a_token_free_run_with_a_similar_prefix_is_accepted(self):
        dirs = self.two_runs()
        self.assertTrue(self.assemble(dirs, token=self.token + "-longer").is_dir())


class ConditionsTests(unittest.TestCase):
    def test_vo4_c11_conditions_drop_exactly_the_exempt_keys(self):
        manifest = m.manifest("a-1", "baseline", "r1")
        self.assertEqual(fixture.EXEMPT, m.EXEMPT)
        self.assertEqual(fixture.conditions(manifest), m.conditions_of(manifest))
        self.assertEqual(set(fixture.conditions(manifest)) & m.EXEMPT, set())
        self.assertEqual(set(fixture.conditions(manifest)) | m.EXEMPT, set(manifest))

    def test_vo4_c11_fixture_id_is_the_first_16_hex_of_sha256_over_the_canonical_json(self):
        conds = m.conditions_of(m.manifest())
        self.assertEqual(fixture.fixture_id(conds), m.fixture_id_of(conds))
        self.assertRegex(fixture.fixture_id(conds), r"^[0-9a-f]{16}$")
        reordered = dict(reversed(list(conds.items())))
        self.assertEqual(fixture.fixture_id(reordered), fixture.fixture_id(conds))
        changed = dict(conds, model="other")
        self.assertNotEqual(fixture.fixture_id(changed), fixture.fixture_id(conds))
        self.assertEqual(fixture.fixture_id({"a": 1, "b": [1, 2]}),
                         m.fixture_id_of({"b": [1, 2], "a": 1}))


class Sandbox:
    """Stub run/resume/assemble functions over run directories under <root>/runs."""

    def __init__(self, root, run_plan, resume_plan=(), real_assemble=False, version_by_run=None):
        self.root = Path(root)
        self.runs = self.root / "runs"
        self.progress = self.root / "progress.json"
        self.cfg = F.cfg_copy(runs_dir=str(self.runs))
        self.instances = [{"instance_id": iid} for iid in IIDS]
        self.run_plan = list(run_plan)
        self.resume_plan = list(resume_plan)
        self.version_by_run = version_by_run or {}
        self.log = []
        self.n_runs = 0
        self.n_resumes = 0
        self.progress_at_run = []
        self.out = self.root / "fixtures"
        self.real_assemble = real_assemble

    def build(self, run_id, halted):
        over = {"cli_version": self.version_by_run[run_id]} if run_id in self.version_by_run else {}
        if halted:
            entries = [{"instance_id": IIDS[0], "arm": "baseline", "status": "interrupted",
                        "manifest": m.manifest(IIDS[0], "baseline", run_id, **over),
                        "state": m.state("interrupted", rate_limit={"status": "rejected"}), "prediction": None}]
            entries += [{"instance_id": iid, "arm": "baseline", "status": "pending"} for iid in IIDS[1:]]
            record = {"reason": "interrupted", "instance_id": IIDS[0], "arm": "baseline"}
        else:
            entries = [baseline_entry(iid, run_id, **over) for iid in IIDS]
            record = None
        return m.write_run(self.runs, run_id, entries, halted=record)

    def run_fn(self, instances, arms, **kw):
        self.n_runs += 1
        n = self.n_runs
        self.log.append(("run", [r["instance_id"] for r in instances], list(arms)))
        self.progress_at_run.append(read_json(self.progress) if self.progress.exists() else None)
        plan = self.run_plan[n - 1] if n <= len(self.run_plan) else "ok"
        return self.build("run%02d" % n, plan == "halt")

    def resume_fn(self, run_id):
        self.log.append(("resume", run_id))
        self.n_resumes += 1
        n = self.n_resumes
        plan = self.resume_plan[n - 1] if n <= len(self.resume_plan) else "clear"
        if plan == "clear":
            self.build(run_id, False)
        return self.runs / run_id

    def assemble_fn(self, run_dirs):
        self.log.append(("assemble", [d.name for d in run_dirs]))
        if self.real_assemble:
            return fixture.assemble(run_dirs, score_fn=score_of, out_root=self.out, token="tok-never-present",
                                    now=lambda: NOW)
        return self.root / "fixture-dir"

    def create(self, repeats=2):
        return fixture.create(self.instances, repeats=repeats, cfg=self.cfg, progress_path=self.progress,
                              run_fn=self.run_fn, resume_fn=self.resume_fn, assemble_fn=self.assemble_fn)


class CreateCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="fixcreate-")
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def sandbox(self, *a, **kw):
        return Sandbox(self.tmp, *a, **kw)


class CreateTests(CreateCase):
    def test_vo4_t1_t2_c13_first_run_halts_and_progress_records_its_id(self):
        sb = self.sandbox(["halt"])
        self.assertEqual(sb.create(), ("halted", "run01"))
        self.assertEqual(sb.log, [("run", IIDS, ["baseline"])])
        self.assertEqual(read_json(sb.progress), {"instances": IIDS, "repeats": 2, "run_ids": ["run01"]})
        self.assertEqual(sb.progress_at_run[0], {"instances": IIDS, "repeats": 2, "run_ids": []})

    def test_vo4_t3_c13_rerun_with_a_still_halted_run_resumes_it_and_halts_again(self):
        sb = self.sandbox(["halt"], ["stay"])
        sb.create()
        before = read_json(sb.progress)
        sb.log.clear()
        self.assertEqual(sb.create(), ("halted", "run01"))
        self.assertEqual(sb.log, [("resume", "run01")])
        self.assertEqual(read_json(sb.progress), before)

    def test_vo4_t4_t5_t6_c13_resume_completes_then_repeat_two_runs_and_the_fixture_is_assembled(self):
        sb = self.sandbox(["halt", "ok"], ["clear"])
        sb.create()
        sb.log.clear()
        result = sb.create()
        self.assertEqual(result, ("done", str(sb.root / "fixture-dir")))
        self.assertEqual(sb.log, [("resume", "run01"), ("run", IIDS, ["baseline"]), ("assemble", ["run01", "run02"])])
        self.assertFalse(sb.progress.exists())

    def test_vo4_eg1_a_tilde_runs_dir_is_expanded_against_home(self):
        home = Path(self.tmp) / "home"
        home.mkdir()
        with mock.patch.dict(os.environ, {"HOME": str(home)}):
            sb = Sandbox(home, ["halt", "ok"], ["clear"])
            sb.cfg["runs_dir"] = "~/runs"
            captured = []
            original = sb.assemble_fn
            sb.assemble_fn = lambda dirs: (captured.append([str(d) for d in dirs]), original(dirs))[1]
            self.assertEqual(sb.create(), ("halted", "run01"))
            self.assertEqual(sb.create()[0], "done")
        self.assertEqual(sb.log[:2], [("run", IIDS, ["baseline"]), ("resume", "run01")])
        self.assertEqual(captured, [[str(home / "runs" / "run01"), str(home / "runs" / "run02")]])
        self.assertFalse(Path("~").exists() and (Path("~") / "runs").exists())

    def test_vo4_t6_assemble_receives_the_recorded_run_directories_in_order(self):
        sb = self.sandbox(["ok", "ok"])
        captured = []
        original = sb.assemble_fn
        sb.assemble_fn = lambda dirs: (captured.append(list(dirs)), original(dirs))[1]
        sb.create()
        self.assertEqual([str(d) for d in captured[0]], [str(sb.runs / "run01"), str(sb.runs / "run02")])

    def test_vo4_t5_uninterrupted_creation_runs_each_repeat_once_then_assembles(self):
        sb = self.sandbox(["ok", "ok"])
        self.assertEqual(sb.create()[0], "done")
        self.assertEqual(sb.log, [("run", IIDS, ["baseline"]), ("run", IIDS, ["baseline"]), ("assemble", ["run01", "run02"])])
        self.assertFalse(sb.progress.exists())

    def test_vo4_t5_repeats_one_runs_once(self):
        sb = self.sandbox(["ok"])
        sb.create(repeats=1)
        self.assertEqual([e[0] for e in sb.log], ["run", "assemble"])

    def test_vo4_t2_a_halt_on_the_second_repeat_records_both_ids_and_the_next_call_only_resumes(self):
        sb = self.sandbox(["ok", "halt"], ["clear"])
        self.assertEqual(sb.create(), ("halted", "run02"))
        self.assertEqual(read_json(sb.progress)["run_ids"], ["run01", "run02"])
        sb.log.clear()
        self.assertEqual(sb.create()[0], "done")
        self.assertEqual(sb.log, [("resume", "run02"), ("assemble", ["run01", "run02"])])

    def test_vo4_t3_a_recorded_run_with_a_pending_entry_is_resumed_even_when_halted_is_null(self):
        sb = self.sandbox(["ok", "ok"])
        sb.n_runs = 1
        run_dir = m.write_run(sb.runs, "run01", [
            {"instance_id": IIDS[0], "arm": "baseline", "status": "interrupted"},
            {"instance_id": IIDS[1], "arm": "baseline", "status": "pending"},
        ], halted=None)
        self.assertTrue(run_dir.is_dir())
        m.write_text(sb.progress, json.dumps({"instances": IIDS, "repeats": 2, "run_ids": ["run01"]}))
        sb.create()
        self.assertEqual(sb.log[0], ("resume", "run01"))

    def test_vo4_t3_g6_a_run_halted_at_its_last_entry_is_resumed_before_the_next_repeat(self):
        sb = self.sandbox(["ok", "ok"], ["clear"])
        sb.n_runs = 1
        run_dir = sb.build("run01", False)
        listing = read_json(run_dir / "run.json")
        listing["halted"] = {"reason": "rate_limit:allowed_warning", "instance_id": IIDS[-1], "arm": "baseline"}
        m.write_text(run_dir / "run.json", json.dumps(listing))
        m.write_text(sb.progress, json.dumps({"instances": IIDS, "repeats": 2, "run_ids": ["run01"]}))
        self.assertEqual(sb.create()[0], "done")
        self.assertEqual([e[0] for e in sb.log], ["resume", "run", "assemble"])
        self.assertEqual(sb.log[0], ("resume", "run01"))

    def test_vo4_t3_a_finished_recorded_run_is_not_resumed(self):
        sb = self.sandbox(["ok", "ok"])
        sb.n_runs = 1
        sb.build("run01", False)
        m.write_text(sb.progress, json.dumps({"instances": IIDS, "repeats": 2, "run_ids": ["run01"]}))
        sb.create()
        self.assertEqual([e[0] for e in sb.log], ["run", "assemble"])

    def test_vo4_t7_c14_progress_with_other_instances_raises_before_any_run_or_resume(self):
        for label, content in (
            ("instances", {"instances": ["a-1", "other"], "repeats": 2, "run_ids": ["run01"]}),
            ("repeats", {"instances": IIDS, "repeats": 3, "run_ids": ["run01"]}),
        ):
            with self.subTest(label):
                sb = self.sandbox(["ok", "ok"])
                m.write_text(sb.progress, json.dumps(content))
                before = sb.progress.read_bytes()
                with self.assertRaises(fixture.FixtureError) as caught:
                    sb.create()
                self.assertIn(str(sb.progress), str(caught.exception))
                self.assertEqual(sb.log, [])
                self.assertEqual(sb.progress.read_bytes(), before)

    def test_vo4_t8_conditions_differing_across_repeats_raise_keep_progress_and_write_no_fixture(self):
        sb = self.sandbox(["ok", "ok"], real_assemble=True, version_by_run={"run02": "9.9.9"})
        with self.assertRaises(fixture.FixtureError) as caught:
            sb.create()
        self.assertIn("cli_version", str(caught.exception))
        self.assertTrue(sb.progress.exists())
        self.assertEqual(m.tree(sb.out), {})

    def test_vo4_qr6_an_interrupted_and_resumed_creation_equals_an_uninterrupted_one(self):
        straight = Sandbox(Path(self.tmp) / "straight", ["ok", "ok"], real_assemble=True)
        broken = Sandbox(Path(self.tmp) / "broken", ["halt", "ok"], ["clear"], real_assemble=True)
        self.assertEqual(straight.create()[0], "done")
        self.assertEqual(broken.create(), ("halted", "run01"))
        self.assertEqual(broken.create()[0], "done")
        self.assertNotEqual(m.tree(straight.out), {})
        self.assertEqual(m.tree(broken.out), m.tree(straight.out))
        self.assertEqual(sorted(p.name for p in broken.out.iterdir()), sorted(p.name for p in straight.out.iterdir()))


# ----------------------------------------------------------------------------------------------
# VO5: compare / find / precheck
# ----------------------------------------------------------------------------------------------

def fixture_manifest(manifests):
    conds = m.conditions_of(manifests[0])
    return {
        "fixture_id": m.fixture_id_of(conds), "conditions": conds,
        "images": {x["instance_id"]: x["images"] for x in manifests},
        "runs": ["r1", "r2"], "repeats": 2, "instances": sorted({x["instance_id"] for x in manifests}),
        "created_at": 0,
    }


def base_pair():
    first = m.manifest("a-1", "baseline", "r1", images=SHARED_IMAGES)
    second = m.manifest("b-2", "baseline", "r1", images=SHARED_IMAGES)
    return first, second


EXEMPT_CHANGES = {
    "run_id": "another-run", "instance_id": "b-2", "arm": "harness", "selfcheck_commit": "1" * 40,
    "harness_ref": "feature/x", "harness_commit": "2" * 40, "start_commit": "3" * 40,
    "install": {"agents_md": "replaced"}, "prompt_template_hash": "z" * 16,
}
NON_EXEMPT_CHANGES = {
    "model": "claude-haiku-5-5", "effort": "high", "cli_version": "9.9.9", "user_sim_hash": "v" * 16,
    "tools": ["Bash"], "caps": {"wall_clock_min": 181, "max_user_turns": 8, "idle_grace_s": 120},
    "network": "other-net",
}


class CompareTests(unittest.TestCase):
    def test_vo5_c15_each_exempt_key_changed_alone_reports_nothing(self):
        first, second = base_pair()
        fm = fixture_manifest([first, second])
        for key, value in EXEMPT_CHANGES.items():
            with self.subTest(key):
                changed = dict(first, **{key: value})
                self.assertEqual(fixture.compare(fm, changed), [])
        self.assertEqual(len(EXEMPT_CHANGES) + 1, len(m.EXEMPT))

    def test_vo5_c15_images_changed_alone_is_reported_per_instance(self):
        first, second = base_pair()
        fm = fixture_manifest([first, second])
        changed = dict(first, images=dict(SHARED_IMAGES, derived="other:dddddddddddd"))
        self.assertEqual(fixture.compare(fm, changed), ["images"])
        self.assertEqual(fixture.compare(fm, first), [])

    def test_vo5_c15_each_listed_non_exempt_key_changed_alone_is_reported(self):
        first, second = base_pair()
        fm = fixture_manifest([first, second])
        for key, value in NON_EXEMPT_CHANGES.items():
            with self.subTest(key):
                self.assertEqual(fixture.compare(fm, dict(first, **{key: value})), [key])

    def test_vo5_c15_several_differing_keys_come_back_sorted(self):
        first, second = base_pair()
        fm = fixture_manifest([first, second])
        changed = dict(first, model="x", effort="high", cli_version="0")
        self.assertEqual(fixture.compare(fm, changed), ["cli_version", "effort", "model"])

    def test_vo5_c15_an_instance_absent_from_the_fixture_is_reported(self):
        first, second = base_pair()
        fm = fixture_manifest([first, second])
        stranger = dict(first, instance_id="zzz-9")
        self.assertEqual(fixture.compare(fm, stranger), ["images", "instance_id"])


class FindCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="fixfind-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.root = Path(self.tmp) / "fixtures"
        self.root.mkdir()


class FindTests(FindCase):
    def test_vo5_c15_find_returns_the_matching_fixture_directory(self):
        first, second = base_pair()
        directory = m.write_fixture(self.root, [first, second])
        found, _ = fixture.find(self.root, [dict(first, arm="harness"), dict(second, arm="harness")])
        self.assertEqual(found, directory)

    def test_vo5_c15_a_fixture_differing_in_model_is_not_found_and_names_the_key(self):
        first, second = base_pair()
        directory = m.write_fixture(self.root, [dict(first, model="claude-haiku-5-5"), dict(second, model="claude-haiku-5-5")])
        found, diffs = fixture.find(self.root, [first, second])
        self.assertIsNone(found)
        self.assertEqual(diffs, {directory.name: ["model"]})

    def test_vo5_c15_exempt_only_differences_still_match(self):
        first, second = base_pair()
        directory = m.write_fixture(self.root, [first, second])
        harness = [dict(x, arm="harness", selfcheck_commit="7" * 40, start_commit="6" * 40, prompt_template_hash="y" * 16)
                   for x in (first, second)]
        self.assertEqual(fixture.find(self.root, harness)[0], directory)

    def test_vo5_find_picks_the_first_matching_directory_in_name_order(self):
        first, second = base_pair()
        original = m.write_fixture(self.root, [first, second])
        early, late = self.root / ("0000" + original.name), self.root / ("zzzz" + original.name)
        shutil.copytree(original, early)
        shutil.copytree(original, late)
        self.assertEqual(fixture.find(self.root, [first, second])[0], early)
        shutil.rmtree(early)
        self.assertEqual(fixture.find(self.root, [first, second])[0], late if late.name < original.name else original)

    def test_vo5_find_requires_every_manifest_to_match(self):
        first, second = base_pair()
        directory = m.write_fixture(self.root, [first])
        found, diffs = fixture.find(self.root, [first, second])
        self.assertIsNone(found)
        self.assertIn("instance_id", diffs[directory.name])

    def test_vo5_find_unions_the_differing_keys_over_all_manifests_for_every_fixture(self):
        first, second = base_pair()
        a = m.write_fixture(self.root, [dict(first, model="m-a"), dict(second, model="m-a")])
        b = m.write_fixture(self.root, [dict(first, network="net-b"), dict(second, network="net-b")])
        changed_second = dict(second, effort="high", images=dict(SHARED_IMAGES, derived="o:eeeeeeeeeeee"))
        found, diffs = fixture.find(self.root, [first, changed_second])
        self.assertIsNone(found)
        self.assertEqual(diffs, {
            a.name: sorted(["model", "effort", "images"]),
            b.name: sorted(["network", "effort", "images"]),
        })

    def test_vo5_c16_find_over_an_empty_fixtures_directory(self):
        first, _ = base_pair()
        self.assertEqual(fixture.find(self.root, [first]), (None, {}))


class PrecheckTests(FindCase):
    def cfg(self, **over):
        return F.cfg_copy(**over)

    def test_vo5_c16_precheck_true_when_a_fixture_matches_the_config_even_if_other_keys_differ(self):
        first, second = base_pair()
        m.write_fixture(self.root, [dict(first, cli_version="1.2.3", user_sim_hash="q" * 16, network="n"), second])
        self.assertTrue(fixture.precheck(self.root, self.cfg()))

    def test_vo5_c16_precheck_false_for_each_config_key_that_differs(self):
        first, second = base_pair()
        m.write_fixture(self.root, [first, second])
        cases = {
            "model": {"model": "claude-haiku-5-5"},
            "effort": {"effort": "high"},
            "aliases": {"aliases": {"opus": "claude-opus-4-1"}},
            "sdk": {"sdk": "claude-agent-sdk==9.9.9"},
            "disallowed_tools": {"disallowed_tools": F.SPEC_AGENT_CFG["disallowed_tools"] + ["Extra"]},
            "caps": {"wall_clock_min": 181},
            "container": {"memory": "8g"},
        }
        for label, over in cases.items():
            with self.subTest(label):
                self.assertFalse(fixture.precheck(self.root, self.cfg(**over)))

    def test_vo5_a1_precheck_mismatch_on_each_remaining_cap_and_container_value(self):
        first, second = base_pair()
        m.write_fixture(self.root, [first, second])
        for label, over in (("max_user_turns", {"max_user_turns": 9}), ("idle_grace_s", {"idle_grace_s": 121}),
                            ("cpus", {"cpus": 8})):
            with self.subTest(label):
                self.assertFalse(fixture.precheck(self.root, self.cfg(**over)))
        other = Path(self.tmp) / "other"
        other.mkdir()
        rooted = dict(container={"cpus": 4, "memory": "6g", "user": "root"})
        m.write_fixture(other, [dict(first, **rooted), dict(second, **rooted)])
        self.assertFalse(fixture.precheck(other, self.cfg()))

    def test_vo5_c16_precheck_true_if_any_one_fixture_matches(self):
        first, second = base_pair()
        m.write_fixture(self.root, [dict(first, effort="high"), dict(second, effort="high")])
        m.write_fixture(self.root, [first, second])
        self.assertTrue(fixture.precheck(self.root, self.cfg()))

    def test_vo5_c16_precheck_false_for_a_fixture_differing_only_in_effort(self):
        first, second = base_pair()
        m.write_fixture(self.root, [dict(first, effort="high"), dict(second, effort="high")])
        self.assertFalse(fixture.precheck(self.root, self.cfg()))

    def test_vo5_c16_precheck_false_without_a_fixtures_directory_or_with_an_empty_one(self):
        self.assertFalse(fixture.precheck(self.root, self.cfg()))
        self.assertFalse(fixture.precheck(Path(self.tmp) / "does-not-exist", self.cfg()))


if __name__ == "__main__":
    unittest.main()

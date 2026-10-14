"""VO8: the M3 CLI commands through `selfcheck.__main__.main(argv)` (decision table: command x outcome).

Seams patched: selfcheck.run.run / resume, selfcheck.score.score_prediction and the config paths
(fixtures_dir, results_dir, progress, token_file, runs_dir). No docker, no network, no real token.
"""
import contextlib
import hashlib
import io
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from selfcheck import __main__ as cli
from selfcheck import docker_exec
from selfcheck import evaluate as evaluate_mod
from selfcheck import report as report_mod
from selfcheck import run as run_mod
from selfcheck import score as score_mod
from selfcheck.tests import agent_fakes as F
from selfcheck.tests import m3_fakes as m
from selfcheck.tests import review_fakes as R

POOL_IDS = list(F.pool_rows())
CORE_IDS = [i for i, row in F.pool_rows().items() if row.get("core")]
NO_FIXTURE_MESSAGE = "no baseline fixture matches the current conditions; run `python3 -m selfcheck baseline create`"


def informed_score(iid):
    return m.score(iid, resolved=False, swt=True, f2p=0.75, primary=0.5, secondary=0.25, incompat=0.0, sampled=18)


def fake_score(instance, prediction, **kw):
    if "INFORMED-MARK" in (prediction or {}).get("src_diff", ""):
        return informed_score(instance["instance_id"])
    return m.score(instance["instance_id"], f2p=1.0, primary=0.5, secondary=0.25, incompat=0.0, sampled=18)


class FakeRuns:
    """Stand-ins for run.run / run.resume writing synthetic run directories under runs_dir."""

    def __init__(self, runs_dir, *, halt_calls=(), manifest_over=None, per_call_over=None, leak=None):
        self.runs_dir = Path(runs_dir)
        self.halt_calls = set(halt_calls)
        self.manifest_over = manifest_over or {}
        self.per_call_over = per_call_over or {}
        self.leak = leak
        self.calls = []
        self.resumes = []

    @staticmethod
    def modes_for(arm, conditions):
        """Entry modes of one (instance, repeat, arm): unassisted first, informed only for the harness arm."""
        if arm != "harness":
            return [None]
        return [None if c == "unassisted" else c for c in ("unassisted", "informed") if c in conditions]

    def build(self, run_id, instances, arms, harness_ref, halted, repeats=1, conditions=("unassisted",)):
        entries = []
        n_call = len(self.calls)
        over = dict(self.manifest_over, **self.per_call_over.get(n_call, {}))
        for position, iid in enumerate([r["instance_id"] for r in instances]):
            for k in range(1, repeats + 1):
                for arm in arms:
                    for mode in self.modes_for(arm, conditions):
                        first = halted and not entries
                        tag = {"repeat": k} if repeats > 1 else {}
                        mtag = {} if mode is None else {"user_mode": mode}
                        if halted and entries:
                            entries.append(dict({"instance_id": iid, "arm": arm, "status": "pending"}, **tag, **mtag))
                            continue
                        extra_pred = {} if mode is None else {"src_diff": "INFORMED-MARK"}
                        pred = m.prediction(iid, arm, run_id, **extra_pred, **tag)
                        if self.leak:
                            pred["src_diff"] = "leak " + self.leak
                        if mode is None:
                            manifest = m.manifest(iid, arm, run_id, harness_ref=harness_ref, **over)
                        else:
                            manifest = m.informed_manifest(iid, run_id, harness_ref=harness_ref, **over)
                        item = dict({
                            "instance_id": iid, "arm": arm, "status": "interrupted" if first else "completed",
                            "manifest": manifest,
                            "state": m.state("interrupted" if first else "completed"),
                            "prediction": None if first else pred,
                        }, **tag, **mtag)
                        if arm == "harness":
                            item["extra"] = {"events": m.compliant_events(), "ledger": m.compliant_ledger_items(),
                                             "diff": m.archived_diff()}
                        entries.append(item)
        record = None
        if halted:
            record = {"reason": "interrupted", "instance_id": entries[0]["instance_id"], "arm": entries[0]["arm"]}
            if "repeat" in entries[0]:
                record["repeat"] = entries[0]["repeat"]
        params = {"harness_ref": harness_ref, "harness_commit": "d" * 40, "selfcheck_commit": "c" * 40}
        run_dir = m.write_run(self.runs_dir, run_id, entries, halted=record, params=params)
        for arm, mode in sorted({(e["arm"], e.get("user_mode")) for e in entries}, key=str):
            name = arm if mode is None else "%s-%s" % (arm, mode)
            lines = [json.dumps(e["prediction"]) for e in entries
                     if e["arm"] == arm and e.get("user_mode") == mode and e.get("prediction")]
            m.write_text(run_dir / ("predictions.%s.jsonl" % name), "\n".join(lines) + ("\n" if lines else ""))
        return run_dir

    def run(self, instances, arms, *, cfg, harness_ref="HEAD", model=None, effort=None, cap_min=None, repeats=1,
            **extra):
        token = Path(cfg["token_file"]).expanduser()
        if not token.exists():
            raise run_mod.TokenFileMissing("token file missing: %s" % token)
        n = len(self.calls) + 1
        conditions = tuple(extra.get("conditions", ("unassisted",)))
        self.calls.append({"instances": [r["instance_id"] for r in instances], "arms": list(arms),
                           "harness_ref": harness_ref, "cfg": cfg, "repeats": repeats, "conditions": conditions,
                           "passed_conditions": "conditions" in extra})
        return self.build("fakerun%02d" % n, instances, list(arms), harness_ref, (n - 1) in self.halt_calls, repeats,
                          conditions)

    def resume(self, run_id, *, cfg, **extra):
        self.resumes.append(run_id)
        run_dir = self.runs_dir / run_id
        if not (run_dir / "run.json").exists():
            raise run_mod.UnknownRunError(run_id)
        listing = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
        instances = [{"instance_id": e["instance_id"]} for e in listing["entries"]]
        arms = sorted({e["arm"] for e in listing["entries"]})
        iids = list(dict.fromkeys(i["instance_id"] for i in instances))
        repeats = max(e.get("repeat", 1) for e in listing["entries"])
        conditions = tuple(sorted({e.get("user_mode", "unassisted") for e in listing["entries"] if e["arm"] == "harness"})) \
            or ("unassisted",)
        shutil.rmtree(run_dir)
        return self.build(run_id, [{"instance_id": i} for i in iids], arms, "HEAD", False, repeats, conditions)


class Boom(AssertionError):
    pass


def forbidden(*args, **kwargs):
    raise Boom("a docker-facing run function was called")


class CliCase(unittest.TestCase):
    use_fake_score = True

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="clim3-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        root = Path(self.tmp)
        self.runs, self.fixtures, self.results = root / "runs", root / "fixtures", root / "results"
        self.progress = root / "progress.json"
        self.fixtures.mkdir()
        self.runs.mkdir()
        self.token_path, self.token = F.write_token_file(self.tmp)
        self.set_config(token_file=self.token_path)
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        if self.use_fake_score:
            self.stack.enter_context(mock.patch.object(score_mod, "score_prediction", fake_score))

    def set_config(self, token_file=None):
        patches = (
            mock.patch.dict(cli.CONFIG["agent"], {"runs_dir": str(self.runs),
                                                  "token_file": token_file or self.token_path}),
            mock.patch.dict(cli.CONFIG["baseline"], {"repeats": 2, "fixtures_dir": str(self.fixtures),
                                                     "progress": str(self.progress)}),
            mock.patch.dict(cli.CONFIG["report"], {"min_mutants": 10, "results_dir": str(self.results)}),
        )
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)

    def invoke(self, argv, fake=None, *, no_run=False):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.ExitStack() as stack:
            if no_run:
                stack.enter_context(mock.patch.object(run_mod, "run", forbidden))
                stack.enter_context(mock.patch.object(run_mod, "resume", forbidden))
            elif fake is not None:
                stack.enter_context(mock.patch.object(run_mod, "run", fake.run))
                stack.enter_context(mock.patch.object(run_mod, "resume", fake.resume))
            stack.enter_context(contextlib.redirect_stdout(out))
            stack.enter_context(contextlib.redirect_stderr(err))
            try:
                code = cli.main(argv)
            except SystemExit as exit_:
                code = exit_.code
        return code, out.getvalue(), err.getvalue()

    # -- builders ------------------------------------------------------------------------------

    def agent_over(self):
        agent = cli.CONFIG["agent"]
        return {
            "model": agent["model"], "effort": agent["effort"], "aliases": dict(agent["aliases"]),
            "sdk": agent["sdk"], "disallowed_tools": list(agent["disallowed_tools"]),
            "caps": {"wall_clock_min": agent["wall_clock_min"], "max_user_turns": agent["max_user_turns"],
                     "idle_grace_s": agent["idle_grace_s"]},
            "container": {"cpus": agent["cpus"], "memory": agent["memory"], "user": "nonroot"},
        }

    def write_matching_fixture(self, ids=POOL_IDS, **over):
        manifests = [m.manifest(i, "baseline", "rb", **dict(self.agent_over(), **over)) for i in ids]
        scores = {i: [m.score(i, resolved=False, swt=False, f2p=0.5, primary=0.25, secondary=0.25, incompat=0.5),
                      m.score(i, resolved=True, swt=True, f2p=0.75, primary=0.5, secondary=0.5, incompat=0.25)]
                  for i in ids}
        return m.write_fixture(self.fixtures, manifests, scores=scores)

    def harness_run(self, run_id="runharness000001", ids=("proj__a-1", "proj__b-2"), *, scores=True,
                    process_json_first=False, harness_ref="HEAD", skip_ledger_for=(), extra_manifest=None,
                    repeats=None, score_of=None, informed=None):
        """repeats=None: legacy layout (no repeat key). Otherwise N repeats per instance in `<iid>/harness-r<k>`."""
        entries = []
        ks = [None] if repeats is None else list(range(1, repeats + 1))
        for iid in ids:
            for k in ks:
                extra = {"events": m.compliant_events(), "ledger": m.compliant_ledger_items(),
                         "diff": m.archived_diff()}
                tag = {} if k is None else {"repeat": k}
                if informed == "only":
                    continue
                entries.append(dict({
                    "instance_id": iid, "arm": "harness", "status": "completed",
                    "manifest": m.manifest(iid, "harness", run_id, harness_ref=harness_ref, **(extra_manifest or {})),
                    "state": m.state(), "prediction": m.prediction(iid, "harness", run_id, **tag), "extra": extra,
                }, **tag))
        entries.append({"instance_id": ids[0], "arm": "baseline", "status": "completed",
                        "manifest": m.manifest(ids[0], "baseline", run_id), "state": m.state(),
                        "prediction": m.prediction(ids[0], "baseline", run_id)})
        if informed in ("both", "only"):
            for iid in ids:
                for k in ks:
                    tag = {} if k is None else {"repeat": k}
                    entries.append(dict({
                        "instance_id": iid, "arm": "harness", "status": "completed", "user_mode": "informed",
                        "manifest": m.informed_manifest(iid, run_id, harness_ref=harness_ref),
                        "state": m.state(),
                        "prediction": m.prediction(iid, "harness", run_id, src_diff="INFORMED-MARK", **tag),
                        "extra": {"events": m.compliant_events(), "ledger": m.compliant_ledger_items(),
                                  "diff": m.archived_diff()},
                    }, **tag))
        run_dir = m.write_run(self.runs, run_id, entries,
                              params={"harness_ref": harness_ref, "harness_commit": "d" * 40})
        if informed in ("both", "only"):
            rows = []
            for iid in ids:
                for k in ks:
                    row = informed_score(iid)
                    rows.append(json.dumps(row if k is None else dict(row, repeat=k)))
            m.write_text(run_dir / "scores.harness-informed.jsonl", "\n".join(rows) + "\n")
        if scores and informed != "only":
            rows = []
            for iid in ids:
                for k in ks:
                    row = score_of(iid, k) if score_of else m.score(iid)
                    rows.append(json.dumps(row if k is None else dict(row, repeat=k)))
            m.write_text(run_dir / "scores.harness.jsonl", "\n".join(rows) + "\n")
        if process_json_first:
            checks = {cid: {"verdict": "pass", "detail": "", "evidence": []} for cid in m.CHECK_IDS}
            checks["PC8"]["verdict"] = "fail"
            m.write_text(run_dir / ids[0] / m.dirname("harness", ks[0]) / "process.json", json.dumps({
                "instance_id": ids[0], "arm": "harness", "workflow_run_id": m.WF, "end_status": "complete",
                "checks": checks, "metrics": {}, "skipped_lines": 0,
            }))
        return run_dir

    def files_under(self, root):
        return m.tree(root)

    @staticmethod
    def load(path):
        return json.loads(Path(path).read_text(encoding="utf-8"))


# ----------------------------------------------------------------------------------------------
# process
# ----------------------------------------------------------------------------------------------

class ProcessCommandTests(CliCase):
    def two_entry_run(self, scores=True):
        run_dir = self.harness_run(scores=scores)
        edit = m.L(None, "Edit", file_path=m.tb(m.TEST_FILE), old_string="a", new_string="b")
        ledger = m.compliant_ledger_items()
        m.write_entry(run_dir, "proj__b-2", "harness", manifest={"instance_id": "proj__b-2", "arm": "harness"},
                      ledger=ledger[:5] + [edit] + ledger[5:], prediction_=m.prediction("proj__b-2", "harness", run_dir.name))
        return run_dir

    def test_vo8_process_ok_prints_counts_per_harness_entry_and_writes_process_json(self):
        run_dir = self.two_entry_run()
        code, out, err = self.invoke(["process", run_dir.name], no_run=True)
        self.assertEqual(code, 0, err)
        self.assertEqual(out.splitlines(), ["proj__a-1 pass=12 fail=0 n/a=0", "proj__b-2 pass=11 fail=1 n/a=0"])
        first = self.load(run_dir / "proj__a-1" / "harness" / "process.json")
        second = self.load(run_dir / "proj__b-2" / "harness" / "process.json")
        self.assertEqual({c["verdict"] for c in first["checks"].values()}, {"pass"})
        self.assertEqual(second["checks"]["PC8"]["verdict"], "fail")
        self.assertEqual(second["checks"]["PC8"]["evidence"], [{"file": "raw/ledger.jsonl", "line": 6}])
        self.assertEqual(second["instance_id"], "proj__b-2")
        self.assertFalse((run_dir / "proj__a-1" / "baseline" / "process.json").exists())

    def test_vo8_process_without_a_scores_file_leaves_pc11_na(self):
        run_dir = self.two_entry_run(scores=False)
        code, out, _ = self.invoke(["process", run_dir.name], no_run=True)
        self.assertEqual(code, 0)
        self.assertEqual(out.splitlines(), ["proj__a-1 pass=11 fail=0 n/a=1", "proj__b-2 pass=10 fail=1 n/a=1"])

    def test_vo8_process_matches_scores_to_entries_by_instance_id(self):
        run_dir = self.two_entry_run()
        only_first = json.dumps(m.score("proj__a-1")) + "\n"
        (run_dir / "scores.harness.jsonl").write_text(only_first, encoding="utf-8")
        code, out, _ = self.invoke(["process", run_dir.name], no_run=True)
        self.assertEqual(out.splitlines(), ["proj__a-1 pass=12 fail=0 n/a=0", "proj__b-2 pass=10 fail=1 n/a=1"])

    def test_vo8_process_takes_no_options(self):
        run_dir = self.two_entry_run()
        code, out, err = self.invoke(["process", run_dir.name, "--instances", "x"], no_run=True)
        self.assertEqual(code, 2)
        self.assertEqual(self.files_under(run_dir / "proj__a-1" / "harness").get("process.json"), None)

    def test_vo8_process_unknown_run_id(self):
        code, out, err = self.invoke(["process", "nosuchrun"], no_run=True)
        self.assertEqual(code, 2)
        self.assertEqual(err, "unknown run id: nosuchrun\n")
        self.assertEqual(out, "")
        self.assertEqual(self.files_under(self.runs), {})


# ----------------------------------------------------------------------------------------------
# baseline create
# ----------------------------------------------------------------------------------------------

class BaselineCommandTests(CliCase):
    def test_vo8_baseline_done_writes_the_fixture_prints_its_directory_and_removes_progress(self):
        fake = FakeRuns(self.runs)
        code, out, err = self.invoke(["baseline", "create"], fake)
        self.assertEqual(code, 0, err)
        self.assertEqual([c["instances"] for c in fake.calls], [POOL_IDS, POOL_IDS])
        self.assertEqual([c["arms"] for c in fake.calls], [["baseline"], ["baseline"]])
        fids = [p.name for p in self.fixtures.iterdir()]
        self.assertEqual(len(fids), 1)
        expected = m.fixture_id_of(m.conditions_of(m.manifest("any", "baseline", "r")))
        self.assertEqual(fids, [expected])
        directory = self.fixtures / expected
        self.assertIn(str(directory), out.splitlines())
        manifest = self.load(directory / "manifest.json")
        self.assertEqual(manifest["repeats"], 2)
        self.assertEqual(manifest["runs"], ["fakerun01", "fakerun02"])
        self.assertEqual(sorted(manifest["instances"]), sorted(POOL_IDS))
        scores = self.load(directory / "scores.json")
        self.assertEqual(sorted(scores), sorted(POOL_IDS))
        for iid, rows in scores.items():
            self.assertEqual([r["repeat"] for r in rows], [1, 2])
            self.assertEqual(rows[0]["score"], m.score(iid, f2p=1.0, primary=0.5, secondary=0.25, incompat=0.0, sampled=18))
        self.assertFalse(self.progress.exists())

    def test_vo8_baseline_flags_select_instances_and_repeats(self):
        fake = FakeRuns(self.runs)
        ids = POOL_IDS[1:3]
        code, out, err = self.invoke(["baseline", "create", "--instances", ",".join(ids), "--repeats", "1"], fake)
        self.assertEqual(code, 0, err)
        self.assertEqual([c["instances"] for c in fake.calls], [ids])
        directory = next(self.fixtures.iterdir())
        self.assertEqual(self.load(directory / "manifest.json")["repeats"], 1)
        self.assertEqual(sorted(self.load(directory / "manifest.json")["instances"]), sorted(ids))

    def test_vo8_baseline_halted_exits_3_names_the_run_and_a_rerun_resumes_it(self):
        fake = FakeRuns(self.runs, halt_calls={0})
        code, out, err = self.invoke(["baseline", "create"], fake)
        self.assertEqual(code, 3)
        message = "halted in run fakerun01; rerun `python3 -m selfcheck baseline create` to resume"
        self.assertIn(message, err.splitlines())
        self.assertNotIn("halted in run", out)
        self.assertEqual(self.load(self.progress)["run_ids"], ["fakerun01"])
        self.assertEqual(list(self.fixtures.iterdir()), [])
        code, out, err = self.invoke(["baseline", "create"], fake)
        self.assertEqual(code, 0, err)
        self.assertEqual(fake.resumes, ["fakerun01"])
        self.assertEqual([c["arms"] for c in fake.calls], [["baseline"], ["baseline"]])
        self.assertEqual(len(list(self.fixtures.iterdir())), 1)
        self.assertFalse(self.progress.exists())

    def test_vo8_baseline_progress_mismatch_exits_1_naming_the_progress_file_and_starts_no_run(self):
        m.write_text(self.progress, json.dumps({"instances": ["other-1"], "repeats": 2, "run_ids": []}))
        before = self.progress.read_bytes()
        fake = FakeRuns(self.runs)
        code, out, err = self.invoke(["baseline", "create"], fake)
        self.assertEqual(code, 1)
        self.assertIn(str(self.progress), err)
        self.assertEqual(fake.calls, [])
        self.assertEqual(self.progress.read_bytes(), before)

    def test_vo8_baseline_differing_conditions_exit_1_and_keep_progress(self):
        fake = FakeRuns(self.runs, per_call_over={2: {"cli_version": "9.9.9"}})
        code, out, err = self.invoke(["baseline", "create"], fake)
        self.assertEqual(code, 1)
        self.assertIn("cli_version", err)
        self.assertEqual(out, "")
        self.assertEqual(list(self.fixtures.iterdir()), [])
        self.assertTrue(self.progress.exists())

    def test_vo8_baseline_token_file_missing_exits_1_with_the_message_and_writes_nothing(self):
        missing = str(Path(self.tmp) / "absent_token")
        self.set_config(token_file=missing)
        fake = FakeRuns(self.runs)
        code, out, err = self.invoke(["baseline", "create"], fake)
        self.assertEqual(code, 1)
        self.assertIn("token file missing: %s" % missing, err)
        self.assertEqual(list(self.fixtures.iterdir()), [])
        self.assertEqual(self.files_under(self.runs), {})

    def test_vo8_baseline_docker_error_exits_1_with_the_message(self):
        def exploding(*a, **kw):
            raise docker_exec.DockerError("daemon exploded")
        with mock.patch.object(run_mod, "run", exploding), mock.patch.object(run_mod, "resume", forbidden):
            out, err = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = cli.main(["baseline", "create"])
        self.assertEqual(code, 1)
        self.assertIn("daemon exploded", err.getvalue())
        self.assertEqual(list(self.fixtures.iterdir()), [])

    def test_vo8_baseline_token_in_a_prediction_exits_1_and_writes_no_fixture_files(self):
        fake = FakeRuns(self.runs, leak=self.token)
        code, out, err = self.invoke(["baseline", "create"], fake)
        self.assertEqual(code, 1)
        self.assertTrue(err.strip())
        self.assertEqual(out, "")
        self.assertEqual(self.files_under(self.fixtures), {})
        for text in (out, err):
            self.assertNotIn(self.token, text)


# ----------------------------------------------------------------------------------------------
# check
# ----------------------------------------------------------------------------------------------

class CheckCommandTests(CliCase):
    def test_vo8_check_precheck_failure_exits_2_before_any_run_call(self):
        code, out, err = self.invoke(["check"], no_run=True)
        self.assertEqual(code, 2)
        self.assertIn(NO_FIXTURE_MESSAGE, err)
        self.assertNotIn(NO_FIXTURE_MESSAGE, out)
        self.assertEqual(self.files_under(self.runs), {})
        self.assertFalse(self.results.exists() and self.files_under(self.results))

    def test_vo8_check_precheck_failure_with_a_fixture_that_differs_in_effort(self):
        self.write_matching_fixture(effort="high")
        code, out, err = self.invoke(["check"], no_run=True)
        self.assertEqual(code, 2)
        self.assertIn(NO_FIXTURE_MESSAGE, err)

    def test_vo8_check_ok_runs_the_harness_arm_on_core_instances_and_writes_the_report(self):
        fixture_dir = self.write_matching_fixture()
        fake = FakeRuns(self.runs)
        code, out, err = self.invoke(["check", "--repeats", "1"], fake)
        self.assertEqual(code, 0, err)
        self.assertEqual(len(fake.calls), 1)
        self.assertEqual(fake.calls[0]["instances"], CORE_IDS)
        self.assertEqual(fake.calls[0]["arms"], ["harness"])
        self.assertEqual(fake.calls[0]["repeats"], 1)
        self.assertEqual(fake.calls[0]["harness_ref"], "HEAD")
        self.assertEqual(fake.resumes, [])
        run_dir = self.runs / "fakerun01"
        rows = [json.loads(l) for l in (run_dir / "scores.harness.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertEqual([r["instance_id"] for r in rows], CORE_IDS)
        for iid in CORE_IDS:
            process = self.load(run_dir / iid / "harness" / "process.json")
            self.assertEqual({c["verdict"] for c in process["checks"].values()}, {"pass"})
        json_path, md_path = self.results / "fakerun01.json", self.results / "fakerun01.md"
        self.assertIn(str(json_path), out)
        self.assertIn(str(md_path), out)
        self.assertNotIn(str(json_path), err)
        self.assertIn(str(run_dir), out.splitlines())
        rep = self.load(json_path)
        self.assertEqual(rep["baseline"], "compared")
        self.assertEqual(rep["fixture_id"], fixture_dir.name)
        self.assertEqual([i["instance_id"] for i in rep["instances"]], CORE_IDS)
        for inst in rep["instances"]:
            self.assertEqual(inst["metrics"]["resolved"], {
                "harness": [1.0], "harness_summary": {"k": 1, "n": 1}, "baseline": [0.0, 1.0], "range": [0.0, 1.0],
                "verdict": "within", "repeat_verdicts": {"above": 0, "within": 1, "below": 0, "n/a": 0}})
            self.assertEqual(inst["metrics"]["f2p_frac"]["verdict"], "above")
            (repeat,) = inst["repeats"]
            self.assertEqual(repeat["repeat"], 1)
            self.assertEqual(repeat["process"], {cid: "pass" for cid in m.CHECK_IDS})
            self.assertEqual(inst["process_fails"], {cid: 0 for cid in m.CHECK_IDS})
        self.assertTrue(md_path.read_text(encoding="utf-8").strip())

    def test_vo8_check_forwards_instances_and_harness_ref(self):
        self.write_matching_fixture()
        fake = FakeRuns(self.runs)
        ids = POOL_IDS[:2]
        code, _, err = self.invoke(["check", "--instances", ",".join(ids), "--harness-ref", "feature/x"], fake)
        self.assertEqual(code, 0, err)
        self.assertEqual(fake.calls[0]["instances"], ids)
        self.assertEqual(fake.calls[0]["harness_ref"], "feature/x")
        self.assertEqual(self.load(self.results / "fakerun01.json")["harness_ref"], "feature/x")

    def test_vo8_check_no_baseline_skips_the_precheck_and_reports_without_a_baseline(self):
        fake = FakeRuns(self.runs)
        code, out, err = self.invoke(["check", "--no-baseline"], fake)
        self.assertEqual(code, 0, err)
        self.assertEqual(len(fake.calls), 1)
        rep = self.load(self.results / "fakerun01.json")
        self.assertEqual(rep["baseline"], "skipped")
        self.assertIsNone(rep["fixture_id"])
        self.assertIn("baseline skipped", (self.results / "fakerun01.md").read_text(encoding="utf-8"))

    def test_vo8_check_resume_skips_the_precheck_and_resumes_instead_of_running(self):
        self.write_matching_fixture()
        first = FakeRuns(self.runs, halt_calls={0})
        code, out, err = self.invoke(["check"], first)
        self.assertEqual(code, 3)
        self.assertIn("resume with: python3 -m selfcheck check --resume fakerun01", err)
        code, out, err = self.invoke(["check", "--resume", "fakerun01"], first)
        self.assertEqual(code, 0, err)
        self.assertEqual(first.resumes, ["fakerun01"])
        self.assertEqual(len(first.calls), 1)
        self.assertTrue((self.results / "fakerun01.json").is_file())

    def test_vo8_check_resume_with_no_fixture_still_resumes_then_refuses_the_report(self):
        first = FakeRuns(self.runs, halt_calls={0})
        self.invoke(["check", "--no-baseline"], first)
        for p in list(self.results.glob("*")) if self.results.exists() else []:
            p.unlink()
        code, out, err = self.invoke(["check", "--resume", "fakerun01"], first)
        self.assertEqual(code, 2)
        self.assertEqual(first.resumes, ["fakerun01"])
        self.assertIn("no baseline fixture exists", err)
        self.assertFalse(self.results.exists() and self.files_under(self.results))

    def test_vo8_check_halted_exits_3_with_the_resume_command(self):
        self.write_matching_fixture()
        fake = FakeRuns(self.runs, halt_calls={0})
        code, out, err = self.invoke(["check"], fake)
        self.assertEqual(code, 3)
        self.assertIn("resume with: python3 -m selfcheck check --resume fakerun01", err)
        run_dir = self.runs / "fakerun01"
        self.assertIn(str(run_dir), out.splitlines())
        self.assertFalse((run_dir / "scores.harness.jsonl").exists())
        self.assertEqual([p for p in run_dir.rglob("process.json")], [])
        self.assertFalse(self.results.exists() and self.files_under(self.results))

    def test_vo8_check_unknown_resume_run_id_exits_2(self):
        fake = FakeRuns(self.runs)
        code, out, err = self.invoke(["check", "--resume", "nosuchrun"], fake)
        self.assertEqual(code, 2)
        self.assertIn("unknown run id: nosuchrun", err)
        self.assertEqual(self.files_under(self.results), {})

    def test_vo8_check_no_fixture_after_the_run_keeps_artifacts_and_writes_no_results(self):
        fixture_dir = self.write_matching_fixture()
        fake = FakeRuns(self.runs, manifest_over={"cli_version": "9.9.9"})
        code, out, err = self.invoke(["check", "--repeats", "1"], fake)
        self.assertEqual(code, 2)
        self.assertIn("fixture %s differs in: cli_version" % fixture_dir.name, err)
        self.assertEqual(self.files_under(self.results), {})
        run_dir = self.runs / "fakerun01"
        self.assertTrue((run_dir / "scores.harness.jsonl").is_file())
        for iid in CORE_IDS:
            self.assertTrue((run_dir / iid / "harness" / "process.json").is_file())

    def test_vo8_check_token_file_missing_exits_1_and_writes_nothing(self):
        missing = str(Path(self.tmp) / "absent_token")
        self.set_config(token_file=missing)
        self.write_matching_fixture()
        fake = FakeRuns(self.runs)
        code, out, err = self.invoke(["check"], fake)
        self.assertEqual(code, 1)
        self.assertIn("token file missing: %s" % missing, err)
        self.assertEqual(self.files_under(self.results), {})

    def test_vo8_check_token_in_the_report_exits_1_and_writes_no_results(self):
        self.write_matching_fixture()
        fake = FakeRuns(self.runs)
        code, out, err = self.invoke(["check", "--harness-ref", "leak-" + self.token], fake)
        self.assertEqual(code, 1)
        self.assertTrue(err.strip())
        self.assertEqual(self.files_under(self.results), {})
        for text in (out, err):
            self.assertNotIn(self.token, text)


# ----------------------------------------------------------------------------------------------
# report
# ----------------------------------------------------------------------------------------------

class ReportCommandTests(CliCase):
    IDS = ("proj__a-1", "proj__b-2")

    def test_vo8_report_ok_with_a_matching_fixture_uses_stored_process_json_and_computes_missing_ones(self):
        fixture_dir = self.write_matching_fixture(ids=self.IDS)
        run_dir = self.harness_run(process_json_first=True)
        code, out, err = self.invoke(["report", run_dir.name], no_run=True)
        self.assertEqual(code, 0, err)
        json_path, md_path = self.results / (run_dir.name + ".json"), self.results / (run_dir.name + ".md")
        self.assertIn(str(json_path), out)
        self.assertIn(str(md_path), out)
        rep = self.load(json_path)
        self.assertEqual(rep["fixture_id"], fixture_dir.name)
        self.assertEqual(rep["baseline"], "compared")
        first, second = rep["instances"]
        self.assertEqual(first["repeats"][0]["process"], dict({cid: "pass" for cid in m.CHECK_IDS}, PC8="fail"))
        self.assertEqual(second["repeats"][0]["process"], {cid: "pass" for cid in m.CHECK_IDS})
        self.assertEqual(first["process_fails"], dict({cid: 0 for cid in m.CHECK_IDS}, PC8=1))
        self.assertEqual(first["metrics"]["resolved"]["harness"], [1.0])
        self.assertEqual(first["metrics"]["resolved"]["verdict"], "within")
        self.assertEqual(first["metrics"]["f2p_frac"]["verdict"], "above")

    def test_vo8_report_no_comparable_fixture_exits_2_naming_keys_and_writes_nothing(self):
        a = self.write_matching_fixture(ids=self.IDS, model="claude-haiku-5-5")
        run_dir = self.harness_run()
        b_manifests = [m.manifest(i, "baseline", "rb", **dict(self.agent_over(), effort="high")) for i in self.IDS]
        b = m.write_fixture(self.fixtures, b_manifests)
        code, out, err = self.invoke(["report", run_dir.name], no_run=True)
        self.assertEqual(code, 2)
        text = err
        self.assertIn("fixture %s differs in: model" % a.name, text)
        self.assertIn("fixture %s differs in: effort" % b.name, text)
        self.assertIn("baseline create", text)
        self.assertFalse(self.results.exists() and self.files_under(self.results))

    def test_vo8_g3_report_refusal_line_joins_sorted_keys_with_comma_space(self):
        run_dir = self.harness_run()
        manifests = [m.manifest(i, "baseline", "rb", **dict(self.agent_over(), model="claude-haiku-5-5", effort="high"))
                     for i in self.IDS]
        directory = m.write_fixture(self.fixtures, manifests)
        code, out, err = self.invoke(["report", run_dir.name], no_run=True)
        self.assertEqual(code, 2)
        self.assertIn("fixture %s differs in: effort, model" % directory.name, err.splitlines())

    def test_vo8_report_without_any_fixture_says_none_exists(self):
        run_dir = self.harness_run()
        code, out, err = self.invoke(["report", run_dir.name], no_run=True)
        self.assertEqual(code, 2)
        self.assertIn("no baseline fixture exists", err)
        self.assertIn("baseline create", err)
        self.assertEqual(out, "")
        self.assertFalse(self.results.exists() and self.files_under(self.results))

    def test_vo8_report_no_baseline_flag_ignores_fixtures(self):
        run_dir = self.harness_run()
        code, out, err = self.invoke(["report", run_dir.name, "--no-baseline"], no_run=True)
        self.assertEqual(code, 0, err)
        rep = self.load(self.results / (run_dir.name + ".json"))
        self.assertEqual(rep["baseline"], "skipped")
        self.assertIsNone(rep["fixture_id"])

    def test_vo8_report_without_a_scores_file_still_writes_with_na_metrics(self):
        run_dir = self.harness_run(scores=False)
        code, _, err = self.invoke(["report", run_dir.name, "--no-baseline"], no_run=True)
        self.assertEqual(code, 0, err)
        rep = self.load(self.results / (run_dir.name + ".json"))
        for inst in rep["instances"]:
            for cell in inst["metrics"].values():
                self.assertEqual(cell["harness"], [None])
                self.assertIsNone(cell["harness_summary"])
                self.assertEqual(cell["verdict"], "n/a")

    def test_vo8_report_unknown_run_id(self):
        code, out, err = self.invoke(["report", "nosuchrun"], no_run=True)
        self.assertEqual(code, 2)
        self.assertEqual(err, "unknown run id: nosuchrun\n")
        self.assertFalse(self.results.exists() and self.files_under(self.results))

    def test_vo8_report_token_file_missing(self):
        missing = str(Path(self.tmp) / "absent_token")
        self.set_config(token_file=missing)
        run_dir = self.harness_run()
        code, out, err = self.invoke(["report", run_dir.name, "--no-baseline"], no_run=True)
        self.assertEqual(code, 1)
        self.assertIn("token file missing: %s" % missing, err)
        self.assertFalse(self.results.exists() and self.files_under(self.results))

    def test_vo8_report_token_in_the_report_text_exits_1_and_writes_nothing(self):
        run_dir = self.harness_run(harness_ref="leak-" + self.token)
        code, out, err = self.invoke(["report", run_dir.name, "--no-baseline"], no_run=True)
        self.assertEqual(code, 1)
        self.assertTrue(err.strip())
        self.assertFalse(self.results.exists() and self.files_under(self.results))
        for text in (out, err):
            self.assertNotIn(self.token, text)


class RelativeConfigTests(CliCase):
    def test_vo8_g1_relative_config_directories_resolve_against_the_repository_root(self):
        import os
        import secrets
        rel = "selfcheck/tests/_tmp_m3_%s" % secrets.token_hex(4)
        root = F.ROOT / rel
        self.addCleanup(shutil.rmtree, root, True)
        fix_rel, res_rel = rel + "/fix", rel + "/res"
        ids = ("proj__a-1", "proj__b-2")
        manifests = [m.manifest(i, "baseline", "rb", **self.agent_over()) for i in ids]
        directory = m.write_fixture(F.ROOT / fix_rel, manifests, scores={i: [m.score(i), m.score(i)] for i in ids})
        run_dir = self.harness_run()
        elsewhere = tempfile.mkdtemp(prefix="cwd-")
        self.addCleanup(shutil.rmtree, elsewhere, True)
        previous = os.getcwd()
        os.chdir(elsewhere)
        self.addCleanup(os.chdir, previous)
        with mock.patch.dict(cli.CONFIG["baseline"], {"fixtures_dir": fix_rel}), \
                mock.patch.dict(cli.CONFIG["report"], {"results_dir": res_rel}):
            code, out, err = self.invoke(["report", run_dir.name], no_run=True)
        self.assertEqual(code, 0, err)
        self.assertTrue((F.ROOT / res_rel / (run_dir.name + ".json")).is_file())
        self.assertEqual(self.load(F.ROOT / res_rel / (run_dir.name + ".json"))["fixture_id"], directory.name)
        self.assertEqual(list(Path(elsewhere).iterdir()), [])


class TildeConfigTests(CliCase):
    def test_vo8_eg1_tilde_runs_dir_and_progress_expand_against_home(self):
        import os
        home = Path(self.tmp) / "home"
        (home / "runs").mkdir(parents=True)
        literal = F.ROOT / "~"
        self.assertFalse(literal.exists())
        self.addCleanup(lambda: shutil.rmtree(literal, True) if literal.exists() else None)
        elsewhere = Path(self.tmp) / "cwd"
        elsewhere.mkdir()
        previous = os.getcwd()
        os.chdir(elsewhere)
        self.addCleanup(os.chdir, previous)
        self.runs = home / "runs"
        with mock.patch.dict(os.environ, {"HOME": str(home)}), \
                mock.patch.dict(cli.CONFIG["agent"], {"runs_dir": "~/runs"}), \
                mock.patch.dict(cli.CONFIG["baseline"], {"progress": "~/progress.json"}):
            fake = FakeRuns(home / "runs", halt_calls={0})
            code, out, err = self.invoke(["baseline", "create"], fake)
            self.assertEqual(code, 3, err)
            self.assertEqual(self.load(home / "progress.json")["run_ids"], ["fakerun01"])
            run_dir = self.harness_run()
            code, out, err = self.invoke(["process", run_dir.name], no_run=True)
            self.assertEqual(code, 0, err)
        self.assertTrue((run_dir / "proj__a-1" / "harness" / "process.json").is_file())
        self.assertFalse(literal.exists())
        self.assertFalse((elsewhere / "~").exists())
        self.assertFalse(Path(self.progress).exists())


class RealScoringWiringTests(CliCase):
    use_fake_score = False

    def test_vo8_g2_check_scoring_receives_the_real_evaluate_functions_and_pool_data(self):
        self.write_matching_fixture()
        seen = []

        def fake_evaluate(instance, src_diff, test_patch, **kw):
            seen.append(instance["instance_id"])
            return {"key": "k", "apply": "ok", "status": {}, "exit_code": 0, "no_tests": False,
                    "timed_out": False, "log_path": None}

        def fake_read_files(instance, src_diff, paths):
            return {path: None for path in paths}

        fake = FakeRuns(self.runs)
        with mock.patch.object(evaluate_mod, "evaluate", fake_evaluate), \
                mock.patch.object(evaluate_mod, "read_files", fake_read_files):
            code, out, err = self.invoke(["check", "--repeats", "1"], fake)
        self.assertEqual(code, 0, err)
        self.assertEqual(sorted(set(seen)), sorted(CORE_IDS))
        rows = [json.loads(l) for l in (self.runs / "fakerun01" / "scores.harness.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertEqual([r["instance_id"] for r in rows], CORE_IDS)


def score_by_repeat(instance, prediction, **kw):
    """Repeat 1 resolves, later repeats do not; the repeat comes from the prediction line (default 1)."""
    k = prediction.get("repeat", 1)
    return m.score(instance["instance_id"], resolved=(k == 1), swt=(k == 1), f2p=1.0 if k == 1 else 0.5,
                   primary=0.5, secondary=0.25, incompat=0.0, sampled=18)


class RepeatsConfigTests(unittest.TestCase):
    def test_o7_config_defaults_are_three(self):
        self.assertEqual(cli.CONFIG["check"]["repeats"], 3)
        self.assertEqual(cli.CONFIG["baseline"]["repeats"], 3)


class RepeatsCheckTests(CliCase):
    def test_o7_default_repeats_comes_from_config_and_reaches_run(self):
        self.write_matching_fixture()
        fake = FakeRuns(self.runs)
        code, out, err = self.invoke(["check"], fake)
        self.assertEqual(code, 0, err)
        self.assertEqual(fake.calls[0]["repeats"], cli.CONFIG["check"]["repeats"])
        self.assertEqual(fake.calls[0]["repeats"], 3)
        rep = self.load(self.results / "fakerun01.json")
        for inst in rep["instances"]:
            self.assertEqual([r["repeat"] for r in inst["repeats"]], [1, 2, 3])

    def test_o7_config_default_follows_the_config_value(self):
        self.write_matching_fixture()
        fake = FakeRuns(self.runs)
        with mock.patch.dict(cli.CONFIG["check"], {"repeats": 2}):
            code, out, err = self.invoke(["check"], fake)
        self.assertEqual(code, 0, err)
        self.assertEqual(fake.calls[0]["repeats"], 2)

    def test_o7_c26_explicit_repeats_two_scores_process_and_report_per_repeat(self):
        self.write_matching_fixture()
        self.stack.enter_context(mock.patch.object(score_mod, "score_prediction", score_by_repeat))
        fake = FakeRuns(self.runs)
        code, out, err = self.invoke(["check", "--repeats", "2"], fake)
        self.assertEqual(code, 0, err)
        self.assertEqual(len(fake.calls), 1)
        self.assertEqual(fake.calls[0]["repeats"], 2)
        self.assertEqual(fake.calls[0]["arms"], ["harness"])
        run_dir = self.runs / "fakerun01"
        rows = [json.loads(l) for l in (run_dir / "scores.harness.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertEqual(sorted((r["instance_id"], r["repeat"]) for r in rows),
                         sorted((i, k) for i in CORE_IDS for k in (1, 2)))
        for row in rows:
            self.assertEqual(row["resolved"], row["repeat"] == 1, row["instance_id"])
        for iid in CORE_IDS:
            self.assertFalse((run_dir / iid / "harness").exists(), iid)
            first = self.load(run_dir / iid / "harness-r1" / "process.json")
            second = self.load(run_dir / iid / "harness-r2" / "process.json")
            self.assertEqual(first["checks"]["PC11"]["verdict"], "pass")
            self.assertEqual(second["checks"]["PC11"]["verdict"], "fail")
        json_path, md_path = self.results / "fakerun01.json", self.results / "fakerun01.md"
        self.assertIn(str(json_path), out)
        rep = self.load(json_path)
        self.assertEqual([i["instance_id"] for i in rep["instances"]], CORE_IDS)
        for inst in rep["instances"]:
            self.assertEqual([r["repeat"] for r in inst["repeats"]], [1, 2])
            self.assertEqual(inst["metrics"]["resolved"]["harness"], [1.0, 0.0])
            self.assertEqual(inst["metrics"]["resolved"]["harness_summary"], {"k": 1, "n": 2})
            self.assertEqual(inst["metrics"]["f2p_frac"]["harness"], [1.0, 0.5])
            self.assertEqual([r["process"]["PC11"] for r in inst["repeats"]], ["pass", "fail"])
            self.assertEqual(inst["process_fails"]["PC11"], 1)
        self.assertIn("### r2 review", md_path.read_text(encoding="utf-8"))

    def test_o7_repeats_one_keeps_the_legacy_layout_and_rows(self):
        self.write_matching_fixture()
        fake = FakeRuns(self.runs)
        code, out, err = self.invoke(["check", "--repeats", "1"], fake)
        self.assertEqual(code, 0, err)
        run_dir = self.runs / "fakerun01"
        rows = [json.loads(l) for l in (run_dir / "scores.harness.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertEqual([(r["instance_id"], r.get("repeat", 1)) for r in rows], [(i, 1) for i in CORE_IDS])
        for iid in CORE_IDS:
            self.assertTrue((run_dir / iid / "harness" / "process.json").is_file())

    def test_o7_c27_invalid_repeats_exit_2_before_any_run_or_directory(self):
        self.write_matching_fixture()
        for value in ("0", "-1", "abc", "1.5"):
            with self.subTest(value):
                fake = FakeRuns(self.runs)
                code, out, err = self.invoke(["check", "--repeats", value], fake)
                self.assertEqual(code, 2)
                self.assertEqual(fake.calls, [])
                self.assertEqual(fake.resumes, [])
                self.assertEqual(self.files_under(self.runs), {})
                self.assertFalse(self.results.exists() and self.files_under(self.results))

    def test_o7_resume_ignores_repeats(self):
        self.write_matching_fixture()
        first = FakeRuns(self.runs, halt_calls={0})
        code, out, err = self.invoke(["check", "--repeats", "2"], first)
        self.assertEqual(code, 3)
        self.assertIn("resume with: python3 -m selfcheck check --resume fakerun01", err)
        code, out, err = self.invoke(["check", "--resume", "fakerun01", "--repeats", "5"], first)
        self.assertEqual(code, 0, err)
        self.assertEqual(first.resumes, ["fakerun01"])
        self.assertEqual(len(first.calls), 1)
        rep = self.load(self.results / "fakerun01.json")
        for inst in rep["instances"]:
            self.assertEqual([r["repeat"] for r in inst["repeats"]], [1, 2])

    def test_o7_check_precheck_failure_still_exits_2_with_repeats(self):
        code, out, err = self.invoke(["check", "--repeats", "2"], no_run=True)
        self.assertEqual(code, 2)
        self.assertIn(NO_FIXTURE_MESSAGE, err)


class RepeatsProcessAndReportTests(CliCase):
    def test_o7_process_keys_scores_and_writes_process_json_per_repeat(self):
        run_dir = self.harness_run(repeats=2, score_of=lambda iid, k: m.score(iid, resolved=(k == 1), swt=(k == 1)))
        code, out, err = self.invoke(["process", run_dir.name], no_run=True)
        self.assertEqual(code, 0, err)
        for iid in ("proj__a-1", "proj__b-2"):
            self.assertFalse((run_dir / iid / "harness" / "process.json").exists())
            first = self.load(run_dir / iid / "harness-r1" / "process.json")
            second = self.load(run_dir / iid / "harness-r2" / "process.json")
            self.assertEqual(first["instance_id"], iid)
            self.assertEqual(first["checks"]["PC11"]["verdict"], "pass")
            self.assertEqual(second["checks"]["PC11"]["verdict"], "fail")
        self.assertFalse((run_dir / "proj__a-1" / "baseline" / "process.json").exists())

    def test_o7_report_of_a_repeated_run_shows_every_repeat_and_the_summary(self):
        run_dir = self.harness_run(repeats=3, score_of=lambda iid, k: m.score(iid, resolved=(k != 2), swt=True))
        code, out, err = self.invoke(["report", run_dir.name, "--no-baseline"], no_run=True)
        self.assertEqual(code, 0, err)
        rep = self.load(self.results / (run_dir.name + ".json"))
        for inst in rep["instances"]:
            self.assertEqual([r["repeat"] for r in inst["repeats"]], [1, 2, 3])
            self.assertEqual(inst["metrics"]["resolved"]["harness"], [1.0, 0.0, 1.0])
            self.assertEqual(inst["metrics"]["resolved"]["harness_summary"], {"k": 2, "n": 3})
        text = (self.results / (run_dir.name + ".md")).read_text(encoding="utf-8")
        self.assertIn("2/3", text)
        for k in (1, 2, 3):
            self.assertIn("### r%d review" % k, text)

    def test_o7_report_uses_the_stored_process_json_of_the_matching_repeat(self):
        run_dir = self.harness_run(repeats=2)
        checks = {cid: {"verdict": "pass", "detail": "", "evidence": []} for cid in m.CHECK_IDS}
        checks["PC8"]["verdict"] = "fail"
        m.write_text(run_dir / "proj__a-1" / "harness-r2" / "process.json", json.dumps({
            "instance_id": "proj__a-1", "arm": "harness", "workflow_run_id": m.WF, "end_status": "complete",
            "checks": checks, "metrics": {}, "skipped_lines": 0}))
        code, out, err = self.invoke(["report", run_dir.name, "--no-baseline"], no_run=True)
        self.assertEqual(code, 0, err)
        first = self.load(self.results / (run_dir.name + ".json"))["instances"][0]
        self.assertEqual([r["process"]["PC8"] for r in first["repeats"]], ["pass", "fail"])
        self.assertEqual(first["process_fails"]["PC8"], 1)

    def test_o10_legacy_run_scores_and_process_json_give_one_repeat(self):
        run_dir = self.harness_run(process_json_first=True)
        code, out, err = self.invoke(["report", run_dir.name, "--no-baseline"], no_run=True)
        self.assertEqual(code, 0, err)
        rep = self.load(self.results / (run_dir.name + ".json"))
        first, second = rep["instances"]
        self.assertEqual([r["repeat"] for r in first["repeats"]], [1])
        self.assertEqual(first["repeats"][0]["process"]["PC8"], "fail")
        self.assertEqual(second["repeats"][0]["process"]["PC8"], "pass")
        self.assertEqual(first["metrics"]["resolved"]["harness"], [1.0])
        self.assertIn(report_mod.NOTE_USER_SIM, (self.results / (run_dir.name + ".md")).read_text(encoding="utf-8"))

    def test_o10_legacy_process_command_writes_the_legacy_directory(self):
        run_dir = self.harness_run()
        code, out, err = self.invoke(["process", run_dir.name], no_run=True)
        self.assertEqual(code, 0, err)
        self.assertTrue((run_dir / "proj__a-1" / "harness" / "process.json").is_file())
        self.assertFalse((run_dir / "proj__a-1" / "harness-r1").exists())


AGENT_DIR = F.ROOT / "selfcheck" / "agent"
REAL_UNASSISTED_HASH = hashlib.sha256(
    (AGENT_DIR / "user_sim.py").read_bytes() + (AGENT_DIR / "driver.py").read_bytes()).hexdigest()
EFFECT_EQUAL_EXCEPT = {"resolved": -1.0, "f2p_frac": -0.25, "swt_success": 0.0, "kill_primary": 0.0,
                       "kill_secondary": 0.0, "incompatible_frac": 0.0}


def jsonl(path):
    return [json.loads(l) for l in Path(path).read_text(encoding="utf-8").splitlines() if l.strip()]


class ReportReviewMixin:
    @staticmethod
    def okfile(iid, cats):
        return json.dumps({"status": "ok", "instance_id": iid, "model": R.MODEL, "effort": R.EFFORT, "categories": cats,
                           "false_claims": [{"category": "understanding", "summary": "WRONG-FACT", "citation": "[t:1]"}]})


class ConditionsCheckTests(CliCase):
    """Spec 54ad633104783ebe O1/O2 (R1, R2, R3, R5, C1-C4)."""

    def check(self, *flags, fake=None):
        fake = fake or FakeRuns(self.runs)
        code, out, err = self.invoke(["check", *flags], fake)
        return fake, code, out, err

    def test_o1_c2_default_conditions_keep_the_current_files_and_entries(self):
        self.write_matching_fixture()
        fake, code, out, err = self.check("--repeats", "1")
        self.assertEqual(code, 0, err)
        self.assertEqual(fake.calls[0]["conditions"], ("unassisted",))
        run_dir = self.runs / "fakerun01"
        entries = self.load(run_dir / "run.json")["entries"]
        self.assertEqual([e["instance_id"] for e in entries], CORE_IDS)
        for e in entries:
            self.assertNotIn("user_mode", e)
        self.assertEqual(sorted(p.name for p in run_dir.glob("*.jsonl")), ["predictions.harness.jsonl", "scores.harness.jsonl"])
        for iid in CORE_IDS:
            self.assertEqual(sorted(p.name for p in (run_dir / iid).iterdir()), ["harness"])
        rep = self.load(self.results / "fakerun01.json")
        self.assertEqual(rep["informed"], [])
        self.assertEqual(rep["informed_effect"], {})
        self.assertNotIn("## informed", (self.results / "fakerun01.md").read_text(encoding="utf-8"))

    def test_o1_g7_bare_check_through_the_real_parser_runs_unassisted(self):
        self.write_matching_fixture()
        fake, code, out, err = self.check()
        self.assertEqual(code, 0, err)
        self.assertEqual(len(fake.calls), 1)
        self.assertEqual(fake.calls[0]["conditions"], ("unassisted",))
        self.assertNotIn("unknown conditions", err)

    def test_o1_unassisted_only_flag_equals_the_default(self):
        self.write_matching_fixture()
        fake, code, _, err = self.check("--conditions", "unassisted", "--repeats", "1")
        self.assertEqual(code, 0, err)
        self.assertEqual(fake.calls[0]["conditions"], ("unassisted",))
        self.assertEqual(sorted(p.name for p in (self.runs / "fakerun01").glob("*.jsonl")),
                         ["predictions.harness.jsonl", "scores.harness.jsonl"])

    def test_o1_o2_c1_both_conditions_with_two_repeats(self):
        fixture_dir = self.write_matching_fixture()
        fake, code, out, err = self.check("--conditions", "unassisted,informed", "--repeats", "2")
        self.assertEqual(code, 0, err)
        self.assertEqual(len(fake.calls), 1)
        self.assertEqual(set(fake.calls[0]["conditions"]), {"unassisted", "informed"})
        self.assertEqual(fake.calls[0]["repeats"], 2)
        self.assertEqual(fake.calls[0]["arms"], ["harness"])
        run_dir = self.runs / "fakerun01"
        for iid in CORE_IDS:
            self.assertEqual(sorted(p.name for p in (run_dir / iid).iterdir()),
                             ["harness-informed-r1", "harness-informed-r2", "harness-r1", "harness-r2"])
        plain = jsonl(run_dir / "scores.harness.jsonl")
        inf = jsonl(run_dir / "scores.harness-informed.jsonl")
        want = sorted((i, k) for i in CORE_IDS for k in (1, 2))
        self.assertEqual(sorted((r["instance_id"], r["repeat"]) for r in plain), want)
        self.assertEqual(sorted((r["instance_id"], r["repeat"]) for r in inf), want)
        self.assertTrue(all(r["resolved"] and r["f2p_frac"] == 1.0 for r in plain))
        self.assertTrue(all((not r["resolved"]) and r["f2p_frac"] == 0.75 for r in inf))
        for iid in CORE_IDS:
            for k in (1, 2):
                plain_pc = self.load(run_dir / iid / ("harness-r%d" % k) / "process.json")
                inf_pc = self.load(run_dir / iid / ("harness-informed-r%d" % k) / "process.json")
                self.assertEqual(plain_pc["checks"]["PC11"]["verdict"], "pass")
                self.assertEqual(inf_pc["checks"]["PC11"]["verdict"], "fail")
        rep = self.load(self.results / "fakerun01.json")
        self.assertEqual(rep["fixture_id"], fixture_dir.name)
        self.assertEqual([i["instance_id"] for i in rep["instances"]], CORE_IDS)
        self.assertEqual([b["instance_id"] for b in rep["informed"]], CORE_IDS)
        for inst, block in zip(rep["instances"], rep["informed"]):
            self.assertEqual(inst["metrics"]["f2p_frac"]["harness"], [1.0, 1.0])
            self.assertEqual(block["metrics"]["f2p_frac"]["harness"], [0.75, 0.75])
            self.assertEqual([r["process"]["PC11"] for r in block["repeats"]], ["fail", "fail"])
            self.assertEqual([r["process"]["PC11"] for r in inst["repeats"]], ["pass", "pass"])
        self.assertEqual(rep["informed_effect"], {iid: EFFECT_EQUAL_EXCEPT for iid in CORE_IDS})
        text = (self.results / "fakerun01.md").read_text(encoding="utf-8")
        self.assertLess(text.index("## informed condition"), text.index("## informed effect"))

    def test_o1_o2_c3_informed_only_matches_a_fixture_recorded_by_unassisted_runs(self):
        fixture_dir = self.write_matching_fixture(user_sim_hash=REAL_UNASSISTED_HASH)
        fake, code, out, err = self.check("--conditions", "informed", "--repeats", "1")
        self.assertEqual(code, 0, err)
        self.assertEqual(fake.calls[0]["conditions"], ("informed",))
        run_dir = self.runs / "fakerun01"
        self.assertEqual([e.get("user_mode") for e in self.load(run_dir / "run.json")["entries"]],
                         ["informed"] * len(CORE_IDS))
        for iid in CORE_IDS:
            self.assertEqual(sorted(p.name for p in (run_dir / iid).iterdir()), ["harness-informed"])
            self.assertTrue((run_dir / iid / "harness-informed" / "process.json").is_file())
        self.assertTrue((run_dir / "predictions.harness-informed.jsonl").is_file())
        self.assertTrue((run_dir / "scores.harness-informed.jsonl").is_file())
        self.assertEqual(len(jsonl(run_dir / "scores.harness-informed.jsonl")), len(CORE_IDS))
        plain_scores = run_dir / "scores.harness.jsonl"
        self.assertTrue(not plain_scores.exists() or jsonl(plain_scores) == [])
        self.assertFalse((run_dir / "predictions.harness.jsonl").exists() and jsonl(run_dir / "predictions.harness.jsonl"))
        rep = self.load(self.results / "fakerun01.json")
        self.assertEqual(rep["fixture_id"], fixture_dir.name)
        self.assertEqual(rep["baseline"], "compared")
        self.assertEqual(rep["instances"], [])
        self.assertEqual(rep["informed_effect"], {})
        self.assertEqual([b["instance_id"] for b in rep["informed"]], CORE_IDS)

    def test_o2_informed_only_lookup_still_compares_every_other_condition(self):
        fixture_dir = self.write_matching_fixture(user_sim_hash=REAL_UNASSISTED_HASH)
        fake = FakeRuns(self.runs, manifest_over={"cli_version": "9.9.9"})
        _, code, out, err = self.check("--conditions", "informed", "--repeats", "1", fake=fake)
        self.assertEqual(code, 2)
        self.assertIn("fixture %s differs in: cli_version" % fixture_dir.name, err)
        self.assertEqual(self.files_under(self.results), {})

    def test_o2_informed_only_lookup_does_not_ignore_a_different_unassisted_hash(self):
        fixture_dir = self.write_matching_fixture()
        _, code, out, err = self.check("--conditions", "informed", "--repeats", "1")
        self.assertEqual(code, 2)
        self.assertIn("fixture %s differs in: user_sim_hash" % fixture_dir.name, err)

    def test_o2_unassisted_entries_decide_the_lookup_when_present(self):
        fixture_dir = self.write_matching_fixture()
        fake, code, out, err = self.check("--conditions", "unassisted,informed", "--repeats", "1")
        self.assertEqual(code, 0, err)
        self.assertEqual(self.load(self.results / "fakerun01.json")["fixture_id"], fixture_dir.name)

    def test_o1_c4_unknown_condition_exits_2_before_any_run(self):
        self.write_matching_fixture()
        fake, code, out, err = self.check("--conditions", "informed,bogus")
        self.assertEqual(code, 2)
        self.assertIn("unknown conditions: bogus", err.splitlines())
        self.assertEqual(fake.calls, [])
        self.assertEqual(fake.resumes, [])
        self.assertEqual(self.files_under(self.runs), {})
        self.assertEqual(self.files_under(self.results), {})

    def test_o1_c4_several_unknown_names_are_all_listed(self):
        self.write_matching_fixture()
        fake, code, out, err = self.check("--conditions", "bogus,other,unassisted")
        self.assertEqual(code, 2)
        line = [l for l in err.splitlines() if l.startswith("unknown conditions: ")]
        self.assertEqual(len(line), 1)
        self.assertIn("bogus", line[0])
        self.assertIn("other", line[0])
        self.assertNotIn("unassisted", line[0])
        self.assertEqual(fake.calls, [])

    def test_o1_resume_ignores_conditions_and_resumes_the_recorded_entries(self):
        self.write_matching_fixture()
        first = FakeRuns(self.runs, halt_calls={0})
        code, out, err = self.invoke(["check", "--conditions", "unassisted,informed", "--repeats", "1"], first)
        self.assertEqual(code, 3)
        code, out, err = self.invoke(["check", "--resume", "fakerun01", "--conditions", "unassisted"], first)
        self.assertEqual(code, 0, err)
        self.assertEqual(first.resumes, ["fakerun01"])
        self.assertEqual(len(first.calls), 1)
        rep = self.load(self.results / "fakerun01.json")
        self.assertEqual([b["instance_id"] for b in rep["informed"]], CORE_IDS)
        self.assertEqual([i["instance_id"] for i in rep["instances"]], CORE_IDS)


class InformedReportCommandTests(CliCase):
    IDS = ("proj__a-1", "proj__b-2")

    def test_o2_report_of_an_informed_only_run_finds_the_unassisted_fixture(self):
        fixture_dir = self.write_matching_fixture(ids=self.IDS, user_sim_hash=REAL_UNASSISTED_HASH)
        run_dir = self.harness_run(informed="only")
        code, out, err = self.invoke(["report", run_dir.name], no_run=True)
        self.assertEqual(code, 0, err)
        rep = self.load(self.results / (run_dir.name + ".json"))
        self.assertEqual(rep["fixture_id"], fixture_dir.name)
        self.assertEqual(rep["instances"], [])
        self.assertEqual([b["instance_id"] for b in rep["informed"]], list(self.IDS))
        self.assertEqual(rep["informed"][0]["metrics"]["f2p_frac"]["harness"], [0.75])
        self.assertEqual(rep["informed"][0]["metrics"]["f2p_frac"]["verdict"], "within")

    def test_o2_report_of_a_run_with_both_conditions_uses_the_unassisted_manifests(self):
        fixture_dir = self.write_matching_fixture(ids=self.IDS)
        run_dir = self.harness_run(informed="both")
        code, out, err = self.invoke(["report", run_dir.name], no_run=True)
        self.assertEqual(code, 0, err)
        rep = self.load(self.results / (run_dir.name + ".json"))
        self.assertEqual(rep["fixture_id"], fixture_dir.name)
        self.assertEqual(rep["informed_effect"]["proj__a-1"]["resolved"], -1.0)

    def test_o13_report_loads_each_informed_entrys_review_json_into_its_block(self):
        run_dir = self.harness_run(informed="both", repeats=2)
        cats = R.payload(understanding=R.category("diverged", R.finding("WRONG-FACT", "[t:1]", True)))
        ok = ReportReviewMixin.okfile("proj__a-1", cats)
        m.write_text(run_dir / "proj__a-1" / "harness-informed-r2" / "review.json", ok)
        code, out, err = self.invoke(["report", run_dir.name, "--no-baseline"], no_run=True)
        self.assertEqual(code, 0, err)
        rep = self.load(self.results / (run_dir.name + ".json"))
        block = rep["informed"][0]["repeats"]
        self.assertEqual(block[0]["review"], "not run")
        self.assertEqual(block[1]["review"]["understanding"], "diverged")
        for repeat in rep["instances"][0]["repeats"]:
            self.assertEqual(repeat["review"], "not run")

    def test_o12_report_without_informed_entries_has_empty_informed_keys(self):
        run_dir = self.harness_run()
        code, out, err = self.invoke(["report", run_dir.name, "--no-baseline"], no_run=True)
        self.assertEqual(code, 0, err)
        rep = self.load(self.results / (run_dir.name + ".json"))
        self.assertEqual((rep["informed"], rep["informed_effect"]), ([], {}))


class SubcommandSurfaceTests(unittest.TestCase):
    def test_vo8_new_subcommands_are_registered(self):
        for name in ("process", "baseline", "check", "report"):
            self.assertIn(name, cli.SUBCOMMANDS)


if __name__ == "__main__":
    unittest.main()

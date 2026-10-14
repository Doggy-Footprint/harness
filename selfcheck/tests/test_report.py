"""VO6 (BVA for verdict, EP for build/write), VO7 (leaks and cost) and spec 2974883932c47b32 v1 O8/O9/O10 for
selfcheck.report.

`scores`, `processes` and `reviews` are keyed by (instance_id, repeat); a run.json entry without a `repeat` key is
repeat 1 (legacy). Process dicts are shaped like process.evaluate_entry / process.json.
"""
import json
import re
import shutil
import tempfile
import unittest
from pathlib import Path

from selfcheck import process, report
from selfcheck.tests import m3_fakes as m

SMALL = "(참고용: 표본 작음)"
METRICS = ("resolved", "f2p_frac", "swt_success", "kill_primary", "kill_secondary", "incompatible_frac")
EPS = 2.0 ** -30
I1, I2 = "inst-a", "inst-b"
RUN = "runharness000001"
CELL_KEYS = {"harness", "harness_summary", "baseline", "range", "verdict", "repeat_verdicts"}
REPEAT_KEYS = {"repeat", "status", "metrics", "process", "cost_usd", "elapsed_s", "review", "review_findings"}
INSTANCE_KEYS = {"instance_id", "small_sample", "repeats", "metrics", "process_fails"}
NO_FAILS = {cid: 0 for cid in m.CHECK_IDS}


def sc(iid, *, resolved=True, swt=True, f2p=1.0, primary=0.5, secondary=0.25, incompat=0.0, sampled=18):
    return m.score(iid, resolved=resolved, swt=swt, f2p=f2p, primary=primary, secondary=secondary,
                   incompat=incompat, sampled=sampled)


def proc(iid, **verdicts):
    checks = {cid: {"verdict": verdicts.get(cid, "pass"), "detail": "", "evidence": []} for cid in m.CHECK_IDS}
    return {"instance_id": iid, "arm": "harness", "workflow_run_id": "w", "end_status": "complete",
            "checks": checks, "metrics": {}, "skipped_lines": 0}


def one(mapping):
    return {(iid, 1): value for iid, value in mapping.items()}


def call_build(run_dir, fixture_dir, scores, processes, min_mutants=10, reviews=None):
    return report.build(run_dir, fixture_dir=fixture_dir, scores=scores, processes=processes,
                        min_mutants=min_mutants, reviews=reviews)


def rv(above=0, within=0, below=0, na=0):
    return {"above": above, "within": within, "below": below, "n/a": na}


def cell_of(harness, summary, baseline, rng, verdict, repeat_verdicts):
    return {"harness": harness, "harness_summary": summary, "baseline": baseline, "range": rng,
            "verdict": verdict, "repeat_verdicts": repeat_verdicts}


def stat(value, low=None, high=None):
    return {"median": value, "min": value if low is None else low, "max": value if high is None else high}


def cells_of(line):
    return [c.strip() for c in line.strip().strip("|").split("|")]


def floats(text):
    return [float(x) for x in re.findall(r"-?\d+(?:\.\d+)?", text)]


class VerdictTests(unittest.TestCase):
    def test_vo6_c17_boundaries_of_the_baseline_range(self):
        base = [0.25, 0.75]
        cases = (
            ("min - eps", 0.25 - EPS, "below"),
            ("min", 0.25, "within"),
            ("min + eps", 0.25 + EPS, "within"),
            ("max - eps", 0.75 - EPS, "within"),
            ("max", 0.75, "within"),
            ("max + eps", 0.75 + EPS, "above"),
        )
        for label, value, expected in cases:
            with self.subTest(label):
                self.assertEqual(report.verdict(value, base), expected)

    def test_vo6_c17_none_value_and_all_none_baseline_are_na(self):
        self.assertEqual(report.verdict(None, [0.25, 0.75]), "n/a")
        self.assertEqual(report.verdict(0.5, [None, None]), "n/a")
        self.assertEqual(report.verdict(0.5, []), "n/a")
        self.assertEqual(report.verdict(None, []), "n/a")

    def test_vo6_c17_none_baseline_values_are_ignored_when_others_exist(self):
        base = [None, 0.25, None, 0.75]
        self.assertEqual(report.verdict(0.5, base), "within")
        self.assertEqual(report.verdict(0.9, base), "above")
        self.assertEqual(report.verdict(0.1, base), "below")

    def test_vo6_c17_zero_values_are_real_values_not_missing(self):
        self.assertEqual(report.verdict(0.0, [0.5]), "below")
        self.assertEqual(report.verdict(0.0, [0.0, None]), "within")
        self.assertEqual(report.verdict(0.25, [0.0, None]), "above")
        self.assertEqual(report.verdict(0.5, [0.5]), "within")

    def test_vo6_metrics_constant(self):
        self.assertEqual(tuple(report.METRICS), METRICS)


class BuildCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="rep-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.runs = Path(self.tmp) / "runs"
        self.fixtures = Path(self.tmp) / "fixtures"
        self.fixtures.mkdir()
        self.results = Path(self.tmp) / "results"
        self.token = "tok-" + "ab12" * 12

    def harness_entry(self, iid, *, repeat=None, status="completed", results=None, elapsed_s=12.5, extra=None,
                      **manifest_over):
        item = {
            "instance_id": iid, "arm": "harness", "status": status,
            "manifest": m.manifest(iid, "harness", RUN, harness_ref="feature/z", **manifest_over),
            "state": m.state(status, results=results, elapsed_s=elapsed_s),
            "prediction": m.prediction(iid, "harness", RUN),
        }
        if repeat is not None:
            item["repeat"] = repeat
        if extra:
            item["extra"] = extra
        return item

    def baseline_entry(self, iid):
        return {"instance_id": iid, "arm": "baseline", "status": "completed",
                "manifest": m.manifest(iid, "baseline", RUN), "state": m.state(), "prediction": None}

    def make_run(self, entries):
        # The spec does not say where build() reads harness_ref/harness_commit from; both the harness entry
        # manifests and the run's params.json carry them here (see the report's spec challenges).
        params = {"harness_ref": "feature/z", "harness_commit": "d" * 40, "selfcheck_commit": "c" * 40}
        return m.write_run(self.runs, RUN, entries, params=params)

    def make_fixture(self, iids, scores=None):
        return m.write_fixture(self.fixtures, [m.manifest(i, "baseline", "rb") for i in iids], scores=scores)

    def repeated_run(self, iid=I1, n=3, per_repeat=None):
        """A run of `n` harness repeats of one instance; per_repeat: {repeat: kwargs for harness_entry}."""
        per_repeat = per_repeat or {}
        return self.make_run([self.harness_entry(iid, repeat=k, **per_repeat.get(k, {})) for k in range(1, n + 1)])


class BuildTests(BuildCase):
    def two_instances(self):
        costs = [{"total_cost_usd": 0.25}, {"total_cost_usd": 0.5}, {"total_cost_usd": 1.0}]
        run_dir = self.make_run([
            self.harness_entry(I1, results=costs),
            self.baseline_entry(I1),
            self.harness_entry(I2, elapsed_s=99.5),
            self.baseline_entry(I2),
        ])
        fixture_dir = self.make_fixture([I1, I2], {
            I1: [sc(I1, resolved=False, swt=False, f2p=0.25, primary=0.25, secondary=0.25, incompat=0.5, sampled=4),
                 sc(I1, resolved=True, swt=True, f2p=0.75, primary=0.5, secondary=0.5, incompat=0.25, sampled=4)],
            I2: [sc(I2, resolved=False, swt=False, f2p=0.5, primary=0.5, secondary=0.25, incompat=0.5), None],
        })
        scores = one({
            I1: sc(I1, resolved=True, swt=True, f2p=1.0, primary=0.5, secondary=0.25, incompat=0.0, sampled=4),
            I2: sc(I2, resolved=False, swt=False, f2p=0.5, primary=0.75, secondary=None, incompat=0.25, sampled=18),
        })
        processes = one({I1: proc(I1), I2: proc(I2, PC8="fail", PC11="n/a")})
        return run_dir, fixture_dir, scores, processes

    def test_vo6_c18_report_with_a_fixture_small_sample_and_normal_instance(self):
        run_dir, fixture_dir, scores, processes = self.two_instances()
        rep = call_build(run_dir, fixture_dir, scores, processes)
        self.assertEqual(rep["run_id"], RUN)
        self.assertEqual(rep["harness_ref"], "feature/z")
        self.assertEqual(rep["harness_commit"], "d" * 40)
        self.assertEqual(rep["fixture_id"], fixture_dir.name)
        self.assertEqual(rep["baseline"], "compared")
        self.assertEqual([i["instance_id"] for i in rep["instances"]], [I1, I2])
        first, second = rep["instances"]
        self.assertIs(first["small_sample"], True)
        self.assertIs(second["small_sample"], False)

        self.assertEqual(first["metrics"], {
            "resolved": cell_of([1.0], {"k": 1, "n": 1}, [0.0, 1.0], [0.0, 1.0], "within", rv(within=1)),
            "f2p_frac": cell_of([1.0], stat(1.0), [0.25, 0.75], [0.25, 0.75], "above", rv(above=1)),
            "swt_success": cell_of([1.0], {"k": 1, "n": 1}, [0.0, 1.0], [0.0, 1.0], "within", rv(within=1)),
            "kill_primary": cell_of([0.5], stat(0.5), [0.25, 0.5], [0.25, 0.5], "within", rv(within=1)),
            "kill_secondary": cell_of([0.25], stat(0.25), [0.25, 0.5], [0.25, 0.5], "within", rv(within=1)),
            "incompatible_frac": cell_of([0.0], stat(0.0), [0.5, 0.25], [0.25, 0.5], "below", rv(below=1)),
        })
        self.assertEqual(second["metrics"], {
            "resolved": cell_of([0.0], {"k": 0, "n": 1}, [0.0, None], [0.0, 0.0], "within", rv(within=1)),
            "f2p_frac": cell_of([0.5], stat(0.5), [0.5, None], [0.5, 0.5], "within", rv(within=1)),
            "swt_success": cell_of([0.0], {"k": 0, "n": 1}, [0.0, None], [0.0, 0.0], "within", rv(within=1)),
            "kill_primary": cell_of([0.75], stat(0.75), [0.5, None], [0.5, 0.5], "above", rv(above=1)),
            "kill_secondary": cell_of([None], None, [0.25, None], [0.25, 0.25], "n/a", rv(na=1)),
            "incompatible_frac": cell_of([0.25], stat(0.25), [0.5, None], [0.5, 0.5], "below", rv(below=1)),
        })
        self.assertEqual(first["process_fails"], NO_FAILS)
        self.assertEqual(second["process_fails"], dict(NO_FAILS, PC8=1))

        (r1,), (r2,) = first["repeats"], second["repeats"]
        self.assertEqual(r1["repeat"], 1)
        self.assertEqual((r1["status"], r2["status"]), ("completed", "completed"))
        self.assertEqual(r1["process"], {cid: "pass" for cid in m.CHECK_IDS})
        self.assertEqual(r2["process"], dict({cid: "pass" for cid in m.CHECK_IDS}, PC8="fail", PC11="n/a"))
        self.assertEqual(r1["cost_usd"], 1.75)
        self.assertIsNone(r2["cost_usd"])
        self.assertEqual((r1["elapsed_s"], r2["elapsed_s"]), (12.5, 99.5))
        self.assertEqual(r1["metrics"], {"resolved": 1.0, "f2p_frac": 1.0, "swt_success": 1.0, "kill_primary": 0.5,
                                         "kill_secondary": 0.25, "incompatible_frac": 0.0})
        self.assertEqual(r2["metrics"], {"resolved": 0.0, "f2p_frac": 0.5, "swt_success": 0.0, "kill_primary": 0.75,
                                         "kill_secondary": None, "incompatible_frac": 0.25})

    def test_o8_closed_key_sets_of_report_instance_repeat_and_metric_cell(self):
        run_dir, fixture_dir, scores, processes = self.two_instances()
        rep = call_build(run_dir, fixture_dir, scores, processes)
        self.assertEqual(set(rep), {"run_id", "harness_ref", "harness_commit", "fixture_id", "baseline", "instances",
                                    "notes", "false_claims"})
        for inst in rep["instances"]:
            self.assertEqual(set(inst), INSTANCE_KEYS)
            self.assertEqual(set(inst["metrics"]), set(METRICS))
            for cell in inst["metrics"].values():
                self.assertEqual(set(cell), CELL_KEYS)
            for repeat in inst["repeats"]:
                self.assertEqual(set(repeat), REPEAT_KEYS)
                self.assertEqual(set(repeat["metrics"]), set(METRICS))

    def test_vo6_c18_notes_always_have_the_no_significance_note_and_one_more_when_a_small_sample_exists(self):
        run_dir, fixture_dir, scores, processes = self.two_instances()
        with_small = call_build(run_dir, fixture_dir, scores, processes)
        only_large = call_build(run_dir, fixture_dir, {**scores, (I1, 1): sc(I1, sampled=18)}, processes)
        self.assertEqual(len(only_large["notes"]), 3)
        self.assertEqual(len(with_small["notes"]), 4)
        for note in with_small["notes"]:
            self.assertIsInstance(note, str)
            self.assertTrue(note.strip())
        for note in only_large["notes"]:
            self.assertIn(note, with_small["notes"])

    def test_o9_f18_notes_contain_user_sim_then_pc5_after_the_no_significance_note(self):
        run_dir = self.make_run([self.harness_entry(I1)])
        rep = call_build(run_dir, None, one({I1: sc(I1, sampled=18)}), one({I1: proc(I1)}))
        notes = rep["notes"]
        self.assertEqual(len(notes), 3)
        self.assertIn(report.NOTE_USER_SIM, notes)
        self.assertIn(report.NOTE_PC5, notes)
        self.assertNotEqual(report.NOTE_USER_SIM, report.NOTE_PC5)
        self.assertLess(notes.index(report.NOTE_USER_SIM), notes.index(report.NOTE_PC5))
        self.assertNotIn(notes[0], (report.NOTE_USER_SIM, report.NOTE_PC5))
        self.assertEqual(notes.index(report.NOTE_USER_SIM), 1)
        self.assertIn("PC5", report.NOTE_PC5)

    def test_o9_f18_notes_are_present_with_a_small_sample_and_without_a_baseline(self):
        run_dir = self.make_run([self.harness_entry(I1)])
        small = call_build(run_dir, None, one({I1: sc(I1, sampled=2)}), one({I1: proc(I1)}))
        for rep in (small, call_build(run_dir, None, {}, {})):
            self.assertIn(report.NOTE_USER_SIM, rep["notes"])
            self.assertIn(report.NOTE_PC5, rep["notes"])
        self.assertEqual(len(small["notes"]), 4)

    def test_vo6_small_sample_boundaries_around_min_mutants(self):
        for min_mutants, sampled, expected in ((10, 9, True), (10, 10, False), (10, 11, False),
                                               (5, 4, True), (5, 5, False), (5, 6, False)):
            with self.subTest(min_mutants=min_mutants, sampled=sampled):
                run_dir = self.make_run([self.harness_entry(I1)])
                rep = call_build(run_dir, None, one({I1: sc(I1, sampled=sampled)}), one({I1: proc(I1)}), min_mutants)
                self.assertIs(rep["instances"][0]["small_sample"], expected)
                shutil.rmtree(self.runs)

    def test_vo6_small_sample_falls_back_to_the_first_non_null_fixture_score(self):
        for sampled, expected in ((4, True), (12, False)):
            with self.subTest(sampled=sampled):
                run_dir = self.make_run([self.harness_entry(I1)])
                fixture_dir = self.make_fixture([I1], {I1: [None, sc(I1, sampled=sampled), sc(I1, sampled=99)]})
                rep = call_build(run_dir, fixture_dir, {}, one({I1: proc(I1)}))
                self.assertIs(rep["instances"][0]["small_sample"], expected)
                shutil.rmtree(self.runs)
                shutil.rmtree(self.fixtures)
                self.fixtures.mkdir()

    def test_vo6_c20_missing_scores_give_na_metrics_and_keep_the_fixture_values(self):
        run_dir, fixture_dir, scores, processes = self.two_instances()
        rep = call_build(run_dir, fixture_dir, {}, processes)
        for inst in rep["instances"]:
            for name in METRICS:
                self.assertEqual(inst["metrics"][name]["harness"], [None], name)
                self.assertIsNone(inst["metrics"][name]["harness_summary"], name)
                self.assertEqual(inst["metrics"][name]["verdict"], "n/a", name)
                self.assertEqual(inst["repeats"][0]["metrics"][name], None, name)
        self.assertEqual(rep["instances"][0]["metrics"]["resolved"]["baseline"], [0.0, 1.0])

    def test_vo6_without_a_fixture_baseline_is_skipped_and_verdicts_are_na(self):
        run_dir, _, scores, processes = self.two_instances()
        rep = call_build(run_dir, None, scores, processes)
        self.assertEqual(rep["baseline"], "skipped")
        self.assertIsNone(rep["fixture_id"])
        for inst in rep["instances"]:
            for name in METRICS:
                cell = inst["metrics"][name]
                self.assertEqual(cell["baseline"], [], name)
                self.assertIsNone(cell["range"], name)
                self.assertEqual(cell["verdict"], "n/a", name)
                self.assertEqual(sum(cell["repeat_verdicts"].values()), 1, name)
                self.assertEqual(cell["repeat_verdicts"]["n/a"], 1, name)
        self.assertEqual(rep["instances"][0]["metrics"]["f2p_frac"]["harness"], [1.0])
        self.assertIs(rep["instances"][0]["small_sample"], True)

    def test_vo6_swt_and_resolved_are_encoded_as_one_and_zero(self):
        run_dir = self.make_run([self.harness_entry(I1), self.harness_entry(I2)])
        scores = one({I1: sc(I1, resolved=True, swt=False), I2: sc(I2, resolved=False, swt=True)})
        rep = call_build(run_dir, None, scores, one({I1: proc(I1), I2: proc(I2)}))
        one_, two = rep["instances"]
        self.assertEqual((one_["metrics"]["resolved"]["harness"], one_["metrics"]["swt_success"]["harness"]),
                         ([1.0], [0.0]))
        self.assertEqual((two["metrics"]["resolved"]["harness"], two["metrics"]["swt_success"]["harness"]),
                         ([0.0], [1.0]))

    def test_vo6_only_harness_entries_are_listed_in_first_appearance_order(self):
        run_dir = self.make_run([self.baseline_entry(I2), self.harness_entry(I2), self.harness_entry(I1)])
        rep = call_build(run_dir, None, {}, {})
        self.assertEqual([i["instance_id"] for i in rep["instances"]], [I2, I1])


class RepeatStatisticsTests(BuildCase):
    """O8: F14-F16, C23, C24. A spec of None is a repeat without a score."""

    def build(self, specs, *, fixture=None, processes=None, min_mutants=10):
        shutil.rmtree(self.runs, True)
        shutil.rmtree(self.fixtures, True)
        self.fixtures.mkdir()
        n = len(specs)
        run_dir = self.repeated_run(I1, n)
        scores = {(I1, k): sc(I1, **kw) for k, kw in enumerate(specs, 1) if kw is not None}
        fixture_dir = None
        if fixture is not None:
            fixture_dir = self.make_fixture([I1], {I1: [None if kw is None else sc(I1, **kw) for kw in fixture]})
        procs = processes if processes is not None else {(I1, k): proc(I1) for k in range(1, n + 1)}
        return call_build(run_dir, fixture_dir, scores, procs, min_mutants)

    def cell(self, rep, name):
        return rep["instances"][0]["metrics"][name]

    def test_o8_c23_three_repeats_resolved_k_of_n_kill_median_and_verdicts(self):
        rep = self.build([dict(resolved=True, primary=0.2), dict(resolved=False, primary=0.5),
                          dict(resolved=True, primary=None)],
                         fixture=[dict(primary=0.1), dict(primary=0.3)])
        resolved = self.cell(rep, "resolved")
        self.assertEqual(resolved["harness"], [1.0, 0.0, 1.0])
        self.assertEqual(resolved["harness_summary"], {"k": 2, "n": 3})
        kill = self.cell(rep, "kill_primary")
        self.assertEqual(kill["harness"], [0.2, 0.5, None])
        self.assertEqual(set(kill["harness_summary"]), {"median", "min", "max"})
        self.assertAlmostEqual(kill["harness_summary"]["median"], 0.35)
        self.assertEqual(kill["harness_summary"]["min"], 0.2)
        self.assertEqual(kill["harness_summary"]["max"], 0.5)
        self.assertEqual(kill["baseline"], [0.1, 0.3])
        self.assertEqual(kill["range"], [0.1, 0.3])
        self.assertEqual(kill["verdict"], "above")
        self.assertEqual(kill["repeat_verdicts"], rv(above=1, within=1, na=1))

    def test_o8_summary_k_n_counts_scored_repeats_only(self):
        rep = self.build([dict(resolved=True), None, dict(resolved=False), dict(resolved=True)])
        self.assertEqual(self.cell(rep, "resolved")["harness"], [1.0, None, 0.0, 1.0])
        self.assertEqual(self.cell(rep, "resolved")["harness_summary"], {"k": 2, "n": 3})
        self.assertEqual(self.cell(rep, "swt_success")["harness_summary"], {"k": 3, "n": 3})

    def test_o8_summary_k_n_with_zero_successes_and_with_a_single_repeat(self):
        rep = self.build([dict(resolved=False, swt=False), dict(resolved=False, swt=False)])
        self.assertEqual(self.cell(rep, "resolved")["harness_summary"], {"k": 0, "n": 2})
        self.assertEqual(self.cell(rep, "swt_success")["harness_summary"], {"k": 0, "n": 2})
        rep = self.build([dict(resolved=True)])
        self.assertEqual(self.cell(rep, "resolved")["harness_summary"], {"k": 1, "n": 1})

    def test_o8_median_odd_count_is_the_middle_value(self):
        rep = self.build([dict(f2p=0.75), dict(f2p=0.25), dict(f2p=0.5)])
        self.assertEqual(self.cell(rep, "f2p_frac")["harness_summary"], {"median": 0.5, "min": 0.25, "max": 0.75})

    def test_o8_median_even_count_is_the_mean_of_the_middle_two(self):
        rep = self.build([dict(f2p=0.75), dict(f2p=0.25), dict(f2p=0.5), dict(f2p=1.0)])
        self.assertEqual(self.cell(rep, "f2p_frac")["harness_summary"], {"median": 0.625, "min": 0.25, "max": 1.0})

    def test_o8_median_single_value(self):
        rep = self.build([dict(f2p=0.375)])
        self.assertEqual(self.cell(rep, "f2p_frac")["harness_summary"], {"median": 0.375, "min": 0.375, "max": 0.375})

    def test_o8_median_skips_none_values(self):
        rep = self.build([dict(primary=None), dict(primary=0.25), dict(primary=0.75), dict(primary=None)])
        self.assertEqual(self.cell(rep, "kill_primary")["harness_summary"], {"median": 0.5, "min": 0.25, "max": 0.75})

    def test_o8_c24_all_none_gives_none_summary_and_na_verdicts(self):
        rep = self.build([dict(primary=None)] * 3, fixture=[dict(primary=0.25), dict(primary=0.5)])
        kill = self.cell(rep, "kill_primary")
        self.assertEqual(kill["harness"], [None, None, None])
        self.assertIsNone(kill["harness_summary"])
        self.assertEqual(kill["verdict"], "n/a")
        self.assertEqual(kill["repeat_verdicts"], rv(na=3))

    def test_o8_all_repeats_unscored_gives_none_summary_for_resolved(self):
        rep = self.build([None, None])
        cell = self.cell(rep, "resolved")
        self.assertEqual(cell["harness"], [None, None])
        self.assertIsNone(cell["harness_summary"])
        self.assertEqual(cell["verdict"], "n/a")

    def test_o8_c24_median_equal_to_baseline_max_is_within(self):
        rep = self.build([dict(primary=0.25), dict(primary=0.75)], fixture=[dict(primary=0.25), dict(primary=0.5)])
        kill = self.cell(rep, "kill_primary")
        self.assertEqual(kill["harness_summary"]["median"], 0.5)
        self.assertEqual(kill["verdict"], "within")
        self.assertEqual(kill["repeat_verdicts"], rv(above=1, within=1))

    def test_o8_verdict_of_the_median_at_the_baseline_range_boundaries(self):
        cases = (
            ("min - eps", 0.25 - EPS, "below"),
            ("min", 0.25, "within"),
            ("max", 0.75, "within"),
            ("max + eps", 0.75 + EPS, "above"),
        )
        for label, value, expected in cases:
            with self.subTest(label):
                rep = self.build([dict(f2p=value)], fixture=[dict(f2p=0.25), dict(f2p=0.75)])
                self.assertEqual(self.cell(rep, "f2p_frac")["verdict"], expected)
                self.assertEqual(self.cell(rep, "f2p_frac")["repeat_verdicts"], rv(**{expected: 1}))

    def test_o8_verdict_uses_the_median_not_the_mean_or_any_single_repeat(self):
        rep = self.build([dict(f2p=v) for v in (0.0, 0.5, 0.5, 1.0, 1.0)],
                         fixture=[dict(f2p=0.25), dict(f2p=0.5)])
        cell = self.cell(rep, "f2p_frac")
        self.assertEqual(cell["harness_summary"]["median"], 0.5)
        self.assertEqual(cell["verdict"], "within")
        self.assertEqual(cell["repeat_verdicts"], rv(above=2, within=2, below=1))

    def test_o8_repeat_verdicts_count_each_class_and_none(self):
        rep = self.build([dict(f2p=0.0), dict(f2p=0.5), dict(f2p=1.0), None],
                         fixture=[dict(f2p=0.25), dict(f2p=0.75)])
        cell = self.cell(rep, "f2p_frac")
        self.assertEqual(cell["repeat_verdicts"], rv(above=1, within=1, below=1, na=1))
        self.assertEqual(cell["verdict"], "within")

    def test_o8_repeat_verdicts_without_a_baseline_are_all_na(self):
        rep = self.build([dict(f2p=0.0), dict(f2p=0.5), dict(f2p=1.0)])
        self.assertEqual(self.cell(rep, "f2p_frac")["repeat_verdicts"], rv(na=3))
        self.assertEqual(self.cell(rep, "f2p_frac")["verdict"], "n/a")

    def test_o8_repeats_are_ordered_by_repeat_and_carry_their_own_values(self):
        run_dir = self.make_run([self.harness_entry(I1, repeat=2), self.harness_entry(I1, repeat=1),
                                 self.harness_entry(I1, repeat=3)])
        scores = {(I1, k): sc(I1, f2p=v) for k, v in ((1, 0.25), (2, 0.5), (3, 0.75))}
        rep = call_build(run_dir, None, scores, {(I1, k): proc(I1) for k in (1, 2, 3)})
        inst = rep["instances"][0]
        self.assertEqual([r["repeat"] for r in inst["repeats"]], [1, 2, 3])
        self.assertEqual([r["metrics"]["f2p_frac"] for r in inst["repeats"]], [0.25, 0.5, 0.75])
        self.assertEqual(inst["metrics"]["f2p_frac"]["harness"], [0.25, 0.5, 0.75])

    def test_o8_one_item_per_instance_in_first_appearance_order_with_repeats_grouped(self):
        run_dir = self.make_run([self.harness_entry(I2, repeat=1), self.harness_entry(I2, repeat=2),
                                 self.harness_entry(I1, repeat=1), self.harness_entry(I1, repeat=2)])
        rep = call_build(run_dir, None, {}, {})
        self.assertEqual([i["instance_id"] for i in rep["instances"]], [I2, I1])
        self.assertEqual([[r["repeat"] for r in i["repeats"]] for i in rep["instances"]], [[1, 2], [1, 2]])

    def test_o8_per_repeat_status_cost_and_elapsed(self):
        run_dir = self.repeated_run(I1, 3, {
            1: dict(status="completed", elapsed_s=10.5, results=[{"total_cost_usd": 0.25}]),
            2: dict(status="capped", elapsed_s=20.5, results=[{"total_cost_usd": 0.5}, {"total_cost_usd": 0.25}]),
            3: dict(status="stalled", elapsed_s=30.5),
        })
        rep = call_build(run_dir, None, {}, {})
        repeats = rep["instances"][0]["repeats"]
        self.assertEqual([r["status"] for r in repeats], ["completed", "capped", "stalled"])
        self.assertEqual([r["elapsed_s"] for r in repeats], [10.5, 20.5, 30.5])
        self.assertEqual([r["cost_usd"] for r in repeats], [0.25, 0.75, None])

    def test_o8_process_fails_count_repeats_with_a_fail_verdict(self):
        procs = {(I1, 1): proc(I1, PC8="fail", PC12="fail"), (I1, 2): proc(I1, PC12="fail", PC11="n/a"),
                 (I1, 3): proc(I1, PC8="fail", PC5="n/a")}
        rep = self.build([dict()] * 3, processes=procs)
        inst = rep["instances"][0]
        self.assertEqual(inst["process_fails"], dict(NO_FAILS, PC8=2, PC12=2))
        self.assertEqual([r["process"]["PC8"] for r in inst["repeats"]], ["fail", "pass", "fail"])
        self.assertEqual([r["process"]["PC11"] for r in inst["repeats"]], ["pass", "n/a", "pass"])

    def test_o8_process_fails_all_zero_when_no_repeat_fails(self):
        rep = self.build([dict()] * 2, processes={(I1, 1): proc(I1), (I1, 2): proc(I1, PC9="n/a")})
        self.assertEqual(rep["instances"][0]["process_fails"], NO_FAILS)

    def test_o8_missing_process_for_a_repeat_does_not_crash(self):
        run_dir = self.repeated_run(I1, 2)
        rep = call_build(run_dir, None, {}, {(I1, 1): proc(I1, PC8="fail")})
        self.assertEqual(rep["instances"][0]["process_fails"]["PC8"], 1)
        self.assertEqual(len(rep["instances"][0]["repeats"]), 2)

    def test_o8_f16_small_sample_uses_the_first_non_none_kill_sampled_across_repeats(self):
        cases = (
            ("first repeat unscored, second small", [None, 4, 99], True),
            ("first repeat large, second small", [12, 4, 4], False),
            ("first repeat small, second large", [4, 99, 99], True),
            ("only third small", [None, None, 4], True),
            ("only third large", [None, None, 18], False),
        )
        for label, sampled, expected in cases:
            with self.subTest(label):
                rep = self.build([None if x is None else dict(sampled=x) for x in sampled])
                self.assertIs(rep["instances"][0]["small_sample"], expected)

    def test_o8_f16_a_score_with_none_sampled_is_skipped(self):
        rep = self.build([dict(sampled=None), dict(sampled=4)])
        self.assertIs(rep["instances"][0]["small_sample"], True)

    def test_o8_f16_small_sample_falls_back_to_fixture_scores_when_no_repeat_has_a_score(self):
        rep = self.build([None, None], fixture=[None, dict(sampled=4)])
        self.assertIs(rep["instances"][0]["small_sample"], True)
        rep = self.build([None, None], fixture=[None, dict(sampled=40)])
        self.assertIs(rep["instances"][0]["small_sample"], False)

    def test_o8_f16_false_claims_include_the_repeat(self):
        from selfcheck.tests import review_fakes as R
        cats = R.payload(understanding=R.category("diverged", R.finding("WRONG", "[t:1]", True)))
        review = {"status": "ok", "instance_id": I1, "model": R.MODEL, "effort": R.EFFORT, "categories": cats,
                  "false_claims": [{"category": "understanding", "summary": "WRONG", "citation": "[t:1]"}]}
        run_dir = self.repeated_run(I1, 3)
        rep = call_build(run_dir, None, {}, {}, reviews={(I1, 2): review, (I1, 3): review})
        self.assertEqual(rep["false_claims"], [
            {"instance_id": I1, "repeat": 2, "category": "understanding", "summary": "WRONG", "citation": "[t:1]"},
            {"instance_id": I1, "repeat": 3, "category": "understanding", "summary": "WRONG", "citation": "[t:1]"},
        ])


class SourceTests(BuildCase):
    def test_vo6_f3_harness_ref_and_commit_come_from_params_json_not_the_manifests(self):
        item = self.harness_entry(I1)
        item["manifest"]["harness_ref"] = "manifest-ref"
        item["manifest"]["harness_commit"] = "f" * 40
        rep = call_build(self.make_run([item]), None, {}, {})
        self.assertEqual((rep["harness_ref"], rep["harness_commit"]), ("feature/z", "d" * 40))

    def test_vo6_s1_status_comes_from_run_json_and_elapsed_from_state_json(self):
        item = self.harness_entry(I1, status="completed", elapsed_s=77.25)
        item["state"]["status"] = "capped"
        rep = call_build(self.make_run([item]), None, {}, {})
        self.assertEqual(rep["instances"][0]["repeats"][0]["status"], "completed")
        self.assertEqual(rep["instances"][0]["repeats"][0]["elapsed_s"], 77.25)

    def test_vo6_a3_all_none_baseline_values_give_null_range_and_na_without_crashing(self):
        run_dir = self.make_run([self.harness_entry(I1)])
        fixture_dir = self.make_fixture([I1], {I1: [None, None]})
        rep = call_build(run_dir, fixture_dir, one({I1: sc(I1)}), one({I1: proc(I1)}))
        for name in METRICS:
            cell = rep["instances"][0]["metrics"][name]
            self.assertEqual(cell["baseline"], [None, None], name)
            self.assertIsNone(cell["range"], name)
            self.assertEqual(cell["verdict"], "n/a", name)
        shutil.rmtree(self.fixtures)
        self.fixtures.mkdir()
        fixture_dir = self.make_fixture([I1], {I1: [sc(I1, secondary=None), sc(I1, secondary=None)]})
        rep = call_build(run_dir, fixture_dir, one({I1: sc(I1)}), one({I1: proc(I1)}))
        cell = rep["instances"][0]["metrics"]["kill_secondary"]
        self.assertEqual((cell["baseline"], cell["range"], cell["verdict"]), ([None, None], None, "n/a"))
        self.assertEqual(rep["instances"][0]["metrics"]["resolved"]["verdict"], "within")


class FixtureIdTests(BuildCase):
    def test_vo6_v5_fixture_id_is_the_manifest_value_else_the_directory_name(self):
        run_dir = self.make_run([self.harness_entry(I1)])
        fixture_dir = self.make_fixture([I1], {I1: [sc(I1), sc(I1)]})
        renamed = fixture_dir.with_name("renamed-dir")
        fixture_dir.rename(renamed)
        rep = call_build(run_dir, renamed, one({I1: sc(I1)}), one({I1: proc(I1)}))
        self.assertEqual(rep["fixture_id"], fixture_dir.name)
        manifest = json.loads((renamed / "manifest.json").read_text(encoding="utf-8"))
        del manifest["fixture_id"]
        (renamed / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        rep = call_build(run_dir, renamed, one({I1: sc(I1)}), one({I1: proc(I1)}))
        self.assertEqual(rep["fixture_id"], "renamed-dir")


class MissingStateTests(BuildCase):
    def test_vo6_eg3_missing_state_json_or_missing_elapsed_gives_none_and_still_renders(self):
        no_state = self.harness_entry(I1)
        no_state["state"] = None
        no_elapsed = self.harness_entry(I2, results=[{"total_cost_usd": 0.5}])
        del no_elapsed["state"]["elapsed_s"]
        run_dir = self.make_run([no_state, no_elapsed])
        rep = call_build(run_dir, None, one({I1: sc(I1), I2: sc(I2)}), one({I1: proc(I1), I2: proc(I2)}))
        (first,), (second,) = [i["repeats"] for i in rep["instances"]]
        self.assertIsNone(first["elapsed_s"])
        self.assertIsNone(first["cost_usd"])
        self.assertIsNone(second["elapsed_s"])
        self.assertEqual(second["cost_usd"], 0.5)
        text = report.render_markdown(rep)
        self.assertIn(I1, text)
        self.assertIn(I2, text)


class CostTests(BuildCase):
    def test_vo7_cost_is_the_sum_over_every_result_not_the_first_or_last(self):
        results = [{"total_cost_usd": 0.25}, {"total_cost_usd": 0.5}, {"total_cost_usd": 1.0}]
        run_dir = self.make_run([self.harness_entry(I1, results=results)])
        rep = call_build(run_dir, None, {}, {})
        self.assertEqual(rep["instances"][0]["repeats"][0]["cost_usd"], 1.75)

    def test_vo7_single_result_and_no_result(self):
        run_dir = self.make_run([self.harness_entry(I1, results=[{"total_cost_usd": 0.125}]), self.harness_entry(I2)])
        rep = call_build(run_dir, None, {}, {})
        self.assertEqual(rep["instances"][0]["repeats"][0]["cost_usd"], 0.125)
        self.assertIsNone(rep["instances"][1]["repeats"][0]["cost_usd"])


class LegacyTests(BuildCase):
    """O10: legacy run.json (no repeat keys), legacy scores and process rows."""

    def test_o10_c25_legacy_entries_give_one_repeat_per_instance_and_the_new_notes(self):
        run_dir, fixture_dir, scores, processes = BuildTests.two_instances(self)
        rep = call_build(run_dir, fixture_dir, scores, processes)
        for inst in rep["instances"]:
            self.assertEqual([r["repeat"] for r in inst["repeats"]], [1])
            for cell in inst["metrics"].values():
                self.assertEqual(len(cell["harness"]), 1)
        self.assertIn(report.NOTE_USER_SIM, rep["notes"])
        self.assertIn(report.NOTE_PC5, rep["notes"])

    def test_o10_c25_markdown_of_a_legacy_run_has_one_repeat_column_and_review_subsection(self):
        run_dir, fixture_dir, scores, processes = BuildTests.two_instances(self)
        text = report.render_markdown(call_build(run_dir, fixture_dir, scores, processes))
        header = "| metric | r1 | summary | baseline (per repeat) | range | verdict | repeats above/within/below |"
        self.assertEqual(text.splitlines().count(header), 2)
        self.assertEqual(text.count("### r1 review"), 2)
        self.assertNotIn("### r2 review", text)
        self.assertEqual(text.splitlines().count("| check | r1 | fails |"), 2)

    def test_o10_legacy_and_explicit_repeat_one_entries_build_the_same_repeat_content(self):
        legacy = call_build(self.make_run([self.harness_entry(I1)]), None, one({I1: sc(I1)}), one({I1: proc(I1)}))
        shutil.rmtree(self.runs)
        explicit = call_build(self.make_run([self.harness_entry(I1, repeat=1)]), None, one({I1: sc(I1)}),
                              one({I1: proc(I1)}))
        self.assertEqual(legacy["instances"], explicit["instances"])


class RenderTests(BuildCase):
    def segments(self, text):
        i1, i2 = text.index(I1), text.index(I2)
        self.assertLess(i1, i2)
        return text[i1:i2], text[i2:]

    @staticmethod
    def rows(segment, needle):
        return [l for l in segment.splitlines() if l.lstrip().startswith("|") and needle in l]

    HEADER_1 = "| metric | r1 | summary | baseline (per repeat) | range | verdict | repeats above/within/below |"

    def test_vo6_c18_markdown_header_tables_suffix_and_notes(self):
        run_dir, fixture_dir, scores, processes = BuildTests.two_instances(self)
        rep = call_build(run_dir, fixture_dir, scores, processes)
        text = report.render_markdown(rep)
        for needle in (RUN, "feature/z", "d" * 40, fixture_dir.name):
            self.assertIn(needle, text)
        self.assertNotIn("baseline skipped", text)
        self.assertEqual(text.splitlines().count(self.HEADER_1), 2)
        self.assertEqual(text.splitlines().count("| check | r1 | fails |"), 2)
        first, second = self.segments(text)
        for name in METRICS:
            self.assertEqual(len(self.rows(first, name)), 1, name)
            self.assertEqual(len(self.rows(second, name)), 1, name)
        for name in ("kill_primary", "kill_secondary"):
            self.assertIn(SMALL, self.rows(first, name)[0])
            self.assertNotIn(SMALL, self.rows(second, name)[0])
        for name in ("resolved", "f2p_frac", "swt_success", "incompatible_frac"):
            self.assertNotIn(SMALL, self.rows(first, name)[0])
        self.assertEqual(cells_of(self.rows(second, "PC8")[0]), ["PC8", "fail", "1"])
        self.assertEqual(cells_of(self.rows(first, "PC8")[0]), ["PC8", "pass", "0"])
        self.assertEqual(cells_of(self.rows(second, "PC11")[0]), ["PC11", "n/a", "0"])
        for note in rep["notes"]:
            self.assertIn(note, text)

    def test_vo6_f2_markdown_cells_carry_the_expected_values(self):
        run_dir, fixture_dir, scores, processes = BuildTests.two_instances(self)
        text = report.render_markdown(call_build(run_dir, fixture_dir, scores, processes))
        first, second = self.segments(text)

        def cells(segment, name):
            return cells_of(self.rows(segment, name)[0])

        expected = (
            (first, "resolved", [1.0], "1/1", [0.0, 1.0], [0.0, 1.0], "within", (0, 1, 0)),
            (first, "f2p_frac", [1.0], None, [0.25, 0.75], [0.25, 0.75], "above", (1, 0, 0)),
            (first, "kill_primary", [0.5], None, [0.25, 0.5], [0.25, 0.5], "within", (0, 1, 0)),
            (first, "incompatible_frac", [0.0], None, [0.5, 0.25], [0.25, 0.5], "below", (0, 0, 1)),
            (second, "resolved", [0.0], "0/1", [0.0], [0.0, 0.0], "within", (0, 1, 0)),
            (second, "kill_primary", [0.75], None, [0.5], [0.5, 0.5], "above", (1, 0, 0)),
        )
        for segment, name, harness, summary, baseline, rng, verdict, counts in expected:
            with self.subTest(name=name, harness=harness):
                c = cells(segment, name)
                self.assertEqual(len(c), 7)
                self.assertIn(name, c[0])
                self.assertEqual(floats(c[1]), harness)
                if summary is not None:
                    self.assertEqual(c[2], summary)
                else:
                    self.assertRegex(c[2], r"^\S+ \[\S+, \S+\]$")
                    self.assertEqual(floats(c[2]), harness * 3)
                self.assertEqual(floats(c[3]), baseline)
                self.assertEqual(floats(c[4]), rng)
                self.assertEqual(c[5], verdict)
                self.assertRegex(c[6], r"^%d\s*/\s*%d\s*/\s*%d" % counts)
        c = cells(second, "kill_secondary")
        self.assertEqual((c[1], c[2], c[5]), ("n/a", "n/a", "n/a"))
        self.assertIn("n/a", cells(second, "resolved")[3])

    def test_vo6_g10_suffix_cell_is_exact(self):
        run_dir, fixture_dir, scores, processes = BuildTests.two_instances(self)
        text = report.render_markdown(call_build(run_dir, fixture_dir, scores, processes))
        first, second = self.segments(text)
        for name in ("kill_primary", "kill_secondary"):
            self.assertEqual(cells_of(self.rows(first, name)[0])[0], name + " " + SMALL)
            self.assertEqual(cells_of(self.rows(second, name)[0])[0], name)

    def test_vo6_markdown_without_a_fixture_says_baseline_skipped(self):
        run_dir, fixture_dir, scores, processes = BuildTests.two_instances(self)
        rep = call_build(run_dir, None, scores, processes)
        text = report.render_markdown(rep)
        self.assertIn("baseline skipped", text)
        self.assertNotIn(fixture_dir.name, text)
        self.assertIn(RUN, text)

    def test_vo6_markdown_has_no_suffix_when_no_instance_is_small(self):
        run_dir = self.make_run([self.harness_entry(I1)])
        rep = call_build(run_dir, None, one({I1: sc(I1, sampled=18)}), one({I1: proc(I1)}))
        self.assertNotIn(SMALL, "\n".join(l for l in report.render_markdown(rep).splitlines() if l.lstrip().startswith("|")))

    def test_o9_small_sample_note_is_conditional_in_the_markdown(self):
        run_dir, fixture_dir, scores, processes = BuildTests.two_instances(self)
        small = call_build(run_dir, fixture_dir, scores, processes)
        large = call_build(run_dir, fixture_dir, {**scores, (I1, 1): sc(I1, sampled=18)}, processes)
        extra = [n for n in small["notes"] if n not in large["notes"]]
        self.assertEqual(len(extra), 1)
        self.assertIn(extra[0], report.render_markdown(small))
        self.assertNotIn(extra[0], report.render_markdown(large))
        for note in (report.NOTE_USER_SIM, report.NOTE_PC5):
            self.assertIn(note, report.render_markdown(large))


class ThreeRepeatRenderTests(BuildCase):
    HEADER_3 = "| metric | r1 | r2 | r3 | summary | baseline (per repeat) | range | verdict | repeats above/within/below |"

    def build(self):
        run_dir = self.repeated_run(I1, 3, {
            1: dict(results=[{"total_cost_usd": 0.25}]),
            2: dict(results=[{"total_cost_usd": 0.5}, {"total_cost_usd": 0.25}]),
        })
        fixture_dir = self.make_fixture([I1], {I1: [sc(I1, resolved=False, swt=False, primary=0.1, sampled=18),
                                                    sc(I1, resolved=True, swt=True, primary=0.3, sampled=18)]})
        scores = {(I1, 1): sc(I1, resolved=True, primary=0.2), (I1, 2): sc(I1, resolved=False, primary=0.5),
                  (I1, 3): sc(I1, resolved=True, primary=None)}
        procs = {(I1, 1): proc(I1, PC8="fail"), (I1, 2): proc(I1, PC11="n/a"), (I1, 3): proc(I1, PC8="fail")}
        rep = call_build(run_dir, fixture_dir, scores, procs)
        return rep, report.render_markdown(rep)

    @staticmethod
    def rows(text, needle):
        return [l for l in text.splitlines() if l.lstrip().startswith("|") and needle in l]

    def test_o9_c28_headers_summary_cells_and_fails_column(self):
        rep, text = self.build()
        lines = text.splitlines()
        self.assertEqual(lines.count(self.HEADER_3), 1)
        self.assertEqual(lines.count("| check | r1 | r2 | r3 | fails |"), 1)
        resolved = cells_of(self.rows(text, "resolved")[0])
        self.assertEqual(len(resolved), 9)
        self.assertEqual(floats(resolved[1]) + floats(resolved[2]) + floats(resolved[3]), [1.0, 0.0, 1.0])
        self.assertEqual(resolved[4], "2/3")
        self.assertRegex(resolved[8], r"^0\s*/\s*3\s*/\s*0")
        kill = cells_of(self.rows(text, "kill_primary")[0])
        self.assertEqual(floats(kill[1]), [0.2])
        self.assertEqual(floats(kill[2]), [0.5])
        self.assertEqual(kill[3], "n/a")
        self.assertRegex(kill[4], r"^\S+ \[\S+, \S+\]$")
        got = floats(kill[4])
        self.assertAlmostEqual(got[0], 0.35, places=2)
        self.assertEqual(got[1:], [0.2, 0.5])
        self.assertEqual(floats(kill[5]), [0.1, 0.3])
        self.assertEqual(kill[7], "above")
        self.assertRegex(kill[8], r"^1\s*/\s*1\s*/\s*0")
        self.assertEqual(cells_of(self.rows(text, "PC8")[0]), ["PC8", "fail", "pass", "fail", "2"])
        self.assertEqual(cells_of(self.rows(text, "PC11")[0]), ["PC11", "pass", "n/a", "pass", "0"])

    def test_o9_metric_table_separator_has_the_header_cell_count(self):
        _, text = self.build()
        lines = text.splitlines()
        at = lines.index(self.HEADER_3)
        separator = lines[at + 1]
        self.assertEqual(len(cells_of(separator)), len(cells_of(self.HEADER_3)))
        self.assertEqual(set(cells_of(separator)), {"---"})
        check_at = lines.index("| check | r1 | r2 | r3 | fails |")
        self.assertEqual(lines[check_at + 1], "| --- | --- | --- | --- | --- |")

    def test_o9_c28_all_twelve_check_rows_are_present_once(self):
        _, text = self.build()
        for cid in m.CHECK_IDS:
            found = [l for l in text.splitlines() if l.lstrip().startswith("|") and cells_of(l)[0] == cid]
            self.assertEqual(len(found), 1, cid)

    def test_o9_c28_cost_line_per_repeat(self):
        _, text = self.build()
        for k, expected in ((1, "0.25"), (2, "0.75"), (3, "n/a")):
            with self.subTest(k):
                found = [l for l in text.splitlines() if "cost" in l.lower() and re.search(r"\br%d\b" % k, l)]
                self.assertEqual(len(found), 1, text)
                self.assertIn(expected, found[0])

    def test_o9_c28_review_subsection_per_repeat_in_order(self):
        _, text = self.build()
        positions = []
        for k in (1, 2, 3):
            self.assertEqual(text.splitlines().count("### r%d review" % k), 1, k)
            positions.append(text.index("### r%d review" % k))
        self.assertEqual(positions, sorted(positions))
        self.assertNotIn("### r4 review", text)

    def test_o9_summary_cell_forms_k_n_median_range_and_na(self):
        rep, text = self.build()
        for name, pattern in (("resolved", r"^\d+/\d+$"), ("swt_success", r"^\d+/\d+$"),
                              ("f2p_frac", r"^\S+ \[\S+, \S+\]$")):
            cell = cells_of(self.rows(text, name)[0])[4]
            self.assertRegex(cell, pattern, name)
        run_dir = self.repeated_run(I1, 2)
        none_rep = call_build(run_dir, None, {}, {})
        none_text = report.render_markdown(none_rep)
        for name in METRICS:
            row = cells_of(self.rows(none_text, name)[0])
            self.assertEqual(row[1:3], ["n/a", "n/a"], name)
            self.assertEqual(row[3], "n/a", name)


class WriteTests(BuildCase):
    def a_report(self):
        run_dir = self.make_run([self.harness_entry(I1)])
        return call_build(run_dir, None, one({I1: sc(I1)}), one({I1: proc(I1)}))

    def test_vo6_write_creates_sorted_indent_one_json_and_the_markdown(self):
        self.results.mkdir()
        rep = self.a_report()
        json_path, md_path = report.write(rep, self.results, token=self.token)
        self.assertEqual(json_path, self.results / (RUN + ".json"))
        self.assertEqual(md_path, self.results / (RUN + ".md"))
        text = json_path.read_text(encoding="utf-8")
        self.assertEqual(json.loads(text), rep)
        self.assertTrue(text.startswith('{\n "'))
        seen = []
        json.loads(text, object_pairs_hook=lambda pairs: (seen.append([k for k, _ in pairs]), dict(pairs))[1])
        self.assertTrue(seen)
        for keys in seen:
            self.assertEqual(keys, sorted(keys))
        self.assertEqual(md_path.read_text(encoding="utf-8").rstrip("\n"), report.render_markdown(rep).rstrip("\n"))

    def test_vo6_write_refuses_a_token_in_both_texts_and_writes_nothing(self):
        self.results.mkdir()
        rep = self.a_report()
        rep["harness_ref"] = "leak-" + self.token
        with self.assertRaises(report.ReportError):
            report.write(rep, self.results, token=self.token)
        self.assertEqual(m.tree(self.results), {})

    def test_vo6_write_refuses_a_token_only_present_in_the_json_text_and_writes_nothing(self):
        self.results.mkdir()
        rep = self.a_report()
        rep["unrendered_extra"] = {"field": self.token}
        with self.assertRaises(report.ReportError):
            report.write(rep, self.results, token=self.token)
        self.assertEqual(m.tree(self.results), {})

    def test_vo6_write_accepts_a_report_without_the_token(self):
        self.results.mkdir()
        json_path, md_path = report.write(self.a_report(), self.results, token=self.token)
        self.assertTrue(json_path.is_file() and md_path.is_file())

    def test_vo6_report_error_is_an_exception(self):
        self.assertTrue(issubclass(report.ReportError, Exception))


class LeakTests(BuildCase):
    TRANSCRIPT = "ZZ-TRANSCRIPT-7f3a91"
    TOOLINPUT = "ZZ-TOOLINPUT-7f3a91"
    DIFFTEXT = "ZZ-DIFFTEXT-7f3a91"

    def planted_entry(self):
        edit = m.L(None, "Edit", file_path=m.tb(m.TEST_FILE), old_string=self.TOOLINPUT, new_string="x")
        ledger = m.compliant_ledger_items()
        ledger = ledger[:5] + [edit, m.L(None, "Bash", command="echo " + self.TOOLINPUT)] + ledger[5:]
        diff = m.archived_diff() + m.new_file_section("src/pkg/new.py", ["# " + self.DIFFTEXT, "x = 1"])
        return self.harness_entry(I1, extra={
            "events": m.compliant_events(), "ledger": ledger, "diff": diff,
            "raw_files": {"raw/messages.jsonl": json.dumps({"kind": "AssistantMessage", "text": self.TRANSCRIPT}) + "\n"},
        })

    def test_vo7_markers_in_messages_ledger_and_diff_never_reach_json_or_markdown(self):
        item = self.planted_entry()
        item["prediction"] = m.prediction(I1, "harness", RUN, src_diff="+ " + self.DIFFTEXT)
        run_dir = self.make_run([item])
        entry_dir = run_dir / I1 / "harness"
        sources = "".join(p.read_text(encoding="utf-8") for p in entry_dir.rglob("*") if p.is_file())
        for marker in (self.TRANSCRIPT, self.TOOLINPUT, self.DIFFTEXT):
            self.assertIn(marker, sources)
        evaluated = process.evaluate_entry(entry_dir, score=sc(I1))
        self.assertEqual(evaluated["checks"]["PC8"]["verdict"], "fail")
        fixture_dir = self.make_fixture([I1], {I1: [sc(I1), sc(I1)]})
        rep = call_build(run_dir, fixture_dir, one({I1: sc(I1)}), {(I1, 1): evaluated})
        self.results.mkdir()
        json_path, md_path = report.write(rep, self.results, token=self.token)
        outputs = [json.dumps(rep, ensure_ascii=False), report.render_markdown(rep),
                   json_path.read_text(encoding="utf-8"), md_path.read_text(encoding="utf-8")]
        for marker in (self.TRANSCRIPT, self.TOOLINPUT, self.DIFFTEXT):
            for text in outputs:
                self.assertNotIn(marker, text)
        self.assertEqual(rep["instances"][0]["repeats"][0]["process"]["PC8"], "fail")

    def test_vo7_report_fields_are_a_closed_set(self):
        run_dir = self.make_run([self.harness_entry(I1)])
        rep = call_build(run_dir, None, one({I1: sc(I1)}), one({I1: proc(I1)}))
        self.assertEqual(set(rep), {"run_id", "harness_ref", "harness_commit", "fixture_id", "baseline", "instances",
                                    "notes", "false_claims"})
        self.assertEqual(set(rep["instances"][0]), INSTANCE_KEYS)
        self.assertEqual(set(rep["instances"][0]["repeats"][0]), REPEAT_KEYS)


if __name__ == "__main__":
    unittest.main()

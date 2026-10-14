"""VO6 (BVA for verdict, EP for build/write) and VO7 (error guessing: leaks and cost) for selfcheck.report.

Assumption isolated in `call_build`: `scores` is {instance_id: score dict} and `processes` is
{instance_id: process dict as returned by process.evaluate_entry / stored in process.json}.
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


def sc(iid, *, resolved=True, swt=True, f2p=1.0, primary=0.5, secondary=0.25, incompat=0.0, sampled=18):
    return m.score(iid, resolved=resolved, swt=swt, f2p=f2p, primary=primary, secondary=secondary,
                   incompat=incompat, sampled=sampled)


def proc(iid, **verdicts):
    checks = {cid: {"verdict": verdicts.get(cid, "pass"), "detail": "", "evidence": []} for cid in m.CHECK_IDS}
    return {"instance_id": iid, "arm": "harness", "workflow_run_id": "w", "end_status": "complete",
            "checks": checks, "metrics": {}, "skipped_lines": 0}


def call_build(run_dir, fixture_dir, scores, processes, min_mutants=10):
    return report.build(run_dir, fixture_dir=fixture_dir, scores=scores, processes=processes,
                        min_mutants=min_mutants)


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

    def harness_entry(self, iid, *, status="completed", results=None, elapsed_s=12.5, extra=None, **manifest_over):
        item = {
            "instance_id": iid, "arm": "harness", "status": status,
            "manifest": m.manifest(iid, "harness", RUN, harness_ref="feature/z", **manifest_over),
            "state": m.state(status, results=results, elapsed_s=elapsed_s),
            "prediction": m.prediction(iid, "harness", RUN),
        }
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
        scores = {
            I1: sc(I1, resolved=True, swt=True, f2p=1.0, primary=0.5, secondary=0.25, incompat=0.0, sampled=4),
            I2: sc(I2, resolved=False, swt=False, f2p=0.5, primary=0.75, secondary=None, incompat=0.25, sampled=18),
        }
        processes = {I1: proc(I1), I2: proc(I2, PC8="fail", PC11="n/a")}
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
        self.assertEqual((first["status"], second["status"]), ("completed", "completed"))
        self.assertIs(first["small_sample"], True)
        self.assertIs(second["small_sample"], False)

        def cell(harness, baseline, rng, verdict):
            return {"harness": harness, "baseline": baseline, "range": rng, "verdict": verdict}

        self.assertEqual(first["metrics"], {
            "resolved": cell(1.0, [0.0, 1.0], [0.0, 1.0], "within"),
            "f2p_frac": cell(1.0, [0.25, 0.75], [0.25, 0.75], "above"),
            "swt_success": cell(1.0, [0.0, 1.0], [0.0, 1.0], "within"),
            "kill_primary": cell(0.5, [0.25, 0.5], [0.25, 0.5], "within"),
            "kill_secondary": cell(0.25, [0.25, 0.5], [0.25, 0.5], "within"),
            "incompatible_frac": cell(0.0, [0.5, 0.25], [0.25, 0.5], "below"),
        })
        self.assertEqual(second["metrics"], {
            "resolved": cell(0.0, [0.0, None], [0.0, 0.0], "within"),
            "f2p_frac": cell(0.5, [0.5, None], [0.5, 0.5], "within"),
            "swt_success": cell(0.0, [0.0, None], [0.0, 0.0], "within"),
            "kill_primary": cell(0.75, [0.5, None], [0.5, 0.5], "above"),
            "kill_secondary": cell(None, [0.25, None], [0.25, 0.25], "n/a"),
            "incompatible_frac": cell(0.25, [0.5, None], [0.5, 0.5], "below"),
        })
        self.assertEqual(first["process"], {cid: "pass" for cid in m.CHECK_IDS})
        self.assertEqual(second["process"], dict({cid: "pass" for cid in m.CHECK_IDS}, PC8="fail", PC11="n/a"))
        self.assertEqual(first["cost_usd"], 1.75)
        self.assertIsNone(second["cost_usd"])
        self.assertEqual((first["elapsed_s"], second["elapsed_s"]), (12.5, 99.5))

    def test_vo6_c18_notes_always_have_the_no_significance_note_and_one_more_when_a_small_sample_exists(self):
        run_dir, fixture_dir, scores, processes = self.two_instances()
        with_small = call_build(run_dir, fixture_dir, scores, processes)
        only_large = call_build(run_dir, fixture_dir, dict(scores, **{I1: sc(I1, sampled=18)}), processes)
        self.assertGreaterEqual(len(only_large["notes"]), 1)
        self.assertEqual(len(with_small["notes"]), len(only_large["notes"]) + 1)
        for note in with_small["notes"]:
            self.assertIsInstance(note, str)
            self.assertTrue(note.strip())
        for note in only_large["notes"]:
            self.assertIn(note, with_small["notes"])

    def test_vo6_small_sample_boundaries_around_min_mutants(self):
        for min_mutants, sampled, expected in ((10, 9, True), (10, 10, False), (10, 11, False),
                                               (5, 4, True), (5, 5, False), (5, 6, False)):
            with self.subTest(min_mutants=min_mutants, sampled=sampled):
                run_dir = self.make_run([self.harness_entry(I1)])
                rep = call_build(run_dir, None, {I1: sc(I1, sampled=sampled)}, {I1: proc(I1)}, min_mutants)
                self.assertIs(rep["instances"][0]["small_sample"], expected)
                shutil.rmtree(self.runs)

    def test_vo6_small_sample_falls_back_to_the_first_non_null_fixture_score(self):
        for sampled, expected in ((4, True), (12, False)):
            with self.subTest(sampled=sampled):
                run_dir = self.make_run([self.harness_entry(I1)])
                fixture_dir = self.make_fixture([I1], {I1: [None, sc(I1, sampled=sampled), sc(I1, sampled=99)]})
                rep = call_build(run_dir, fixture_dir, {}, {I1: proc(I1)})
                self.assertIs(rep["instances"][0]["small_sample"], expected)
                shutil.rmtree(self.runs)
                shutil.rmtree(self.fixtures)
                self.fixtures.mkdir()

    def test_vo6_c20_missing_scores_give_na_metrics_and_keep_the_fixture_values(self):
        run_dir, fixture_dir, scores, processes = self.two_instances()
        rep = call_build(run_dir, fixture_dir, {}, processes)
        for inst in rep["instances"]:
            for name in METRICS:
                self.assertIsNone(inst["metrics"][name]["harness"], name)
                self.assertEqual(inst["metrics"][name]["verdict"], "n/a", name)
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
        self.assertEqual(rep["instances"][0]["metrics"]["f2p_frac"]["harness"], 1.0)
        self.assertIs(rep["instances"][0]["small_sample"], True)

    def test_vo6_swt_and_resolved_are_encoded_as_one_and_zero(self):
        run_dir = self.make_run([self.harness_entry(I1), self.harness_entry(I2)])
        scores = {I1: sc(I1, resolved=True, swt=False), I2: sc(I2, resolved=False, swt=True)}
        rep = call_build(run_dir, None, scores, {I1: proc(I1), I2: proc(I2)})
        one, two = rep["instances"]
        self.assertEqual((one["metrics"]["resolved"]["harness"], one["metrics"]["swt_success"]["harness"]), (1.0, 0.0))
        self.assertEqual((two["metrics"]["resolved"]["harness"], two["metrics"]["swt_success"]["harness"]), (0.0, 1.0))

    def test_vo6_only_harness_entries_are_listed_in_run_json_order(self):
        run_dir = self.make_run([self.baseline_entry(I2), self.harness_entry(I2), self.harness_entry(I1)])
        rep = call_build(run_dir, None, {}, {})
        self.assertEqual([i["instance_id"] for i in rep["instances"]], [I2, I1])


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
        self.assertEqual(rep["instances"][0]["status"], "completed")
        self.assertEqual(rep["instances"][0]["elapsed_s"], 77.25)

    def test_vo6_a3_all_none_baseline_values_give_null_range_and_na_without_crashing(self):
        run_dir = self.make_run([self.harness_entry(I1)])
        fixture_dir = self.make_fixture([I1], {I1: [None, None]})
        rep = call_build(run_dir, fixture_dir, {I1: sc(I1)}, {I1: proc(I1)})
        for name in METRICS:
            cell = rep["instances"][0]["metrics"][name]
            self.assertEqual(cell["baseline"], [None, None], name)
            self.assertIsNone(cell["range"], name)
            self.assertEqual(cell["verdict"], "n/a", name)
        shutil.rmtree(self.fixtures)
        self.fixtures.mkdir()
        fixture_dir = self.make_fixture([I1], {I1: [sc(I1, secondary=None), sc(I1, secondary=None)]})
        rep = call_build(run_dir, fixture_dir, {I1: sc(I1)}, {I1: proc(I1)})
        cell = rep["instances"][0]["metrics"]["kill_secondary"]
        self.assertEqual((cell["baseline"], cell["range"], cell["verdict"]), ([None, None], None, "n/a"))
        self.assertEqual(rep["instances"][0]["metrics"]["resolved"]["verdict"], "within")


class FixtureIdTests(BuildCase):
    def test_vo6_v5_fixture_id_is_the_manifest_value_else_the_directory_name(self):
        run_dir = self.make_run([self.harness_entry(I1)])
        fixture_dir = self.make_fixture([I1], {I1: [sc(I1), sc(I1)]})
        renamed = fixture_dir.with_name("renamed-dir")
        fixture_dir.rename(renamed)
        rep = call_build(run_dir, renamed, {I1: sc(I1)}, {I1: proc(I1)})
        self.assertEqual(rep["fixture_id"], fixture_dir.name)
        manifest = json.loads((renamed / "manifest.json").read_text(encoding="utf-8"))
        del manifest["fixture_id"]
        (renamed / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        rep = call_build(run_dir, renamed, {I1: sc(I1)}, {I1: proc(I1)})
        self.assertEqual(rep["fixture_id"], "renamed-dir")


class MissingStateTests(BuildCase):
    def test_vo6_eg3_missing_state_json_or_missing_elapsed_gives_none_and_still_renders(self):
        no_state = self.harness_entry(I1)
        no_state["state"] = None
        no_elapsed = self.harness_entry(I2, results=[{"total_cost_usd": 0.5}])
        del no_elapsed["state"]["elapsed_s"]
        run_dir = self.make_run([no_state, no_elapsed])
        rep = call_build(run_dir, None, {I1: sc(I1), I2: sc(I2)}, {I1: proc(I1), I2: proc(I2)})
        first, second = rep["instances"]
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
        self.assertEqual(rep["instances"][0]["cost_usd"], 1.75)

    def test_vo7_single_result_and_no_result(self):
        run_dir = self.make_run([self.harness_entry(I1, results=[{"total_cost_usd": 0.125}]), self.harness_entry(I2)])
        rep = call_build(run_dir, None, {}, {})
        self.assertEqual(rep["instances"][0]["cost_usd"], 0.125)
        self.assertIsNone(rep["instances"][1]["cost_usd"])


class RenderTests(BuildCase):
    def segments(self, text):
        i1, i2 = text.index(I1), text.index(I2)
        self.assertLess(i1, i2)
        return text[i1:i2], text[i2:]

    @staticmethod
    def rows(segment, needle):
        return [l for l in segment.splitlines() if l.lstrip().startswith("|") and needle in l]

    def test_vo6_c18_markdown_header_tables_suffix_and_notes(self):
        run_dir, fixture_dir, scores, processes = BuildTests.two_instances(self)
        rep = call_build(run_dir, fixture_dir, scores, processes)
        text = report.render_markdown(rep)
        for needle in (RUN, "feature/z", "d" * 40, fixture_dir.name):
            self.assertIn(needle, text)
        self.assertNotIn("baseline skipped", text)
        self.assertRegex(text, r"metric\s*\|\s*harness\s*\|\s*baseline \(per repeat\)\s*\|\s*range\s*\|\s*verdict")
        self.assertRegex(text, r"\|\s*check\s*\|\s*verdict\s*\|")
        first, second = self.segments(text)
        for name in METRICS:
            self.assertEqual(len(self.rows(first, name)), 1, name)
            self.assertEqual(len(self.rows(second, name)), 1, name)
        for name in ("kill_primary", "kill_secondary"):
            self.assertIn(SMALL, self.rows(first, name)[0])
            self.assertNotIn(SMALL, self.rows(second, name)[0])
        for name in ("resolved", "f2p_frac", "swt_success", "incompatible_frac"):
            self.assertNotIn(SMALL, self.rows(first, name)[0])
        verdicts = {"resolved": "within", "f2p_frac": "above", "incompatible_frac": "below"}
        for name, word in verdicts.items():
            self.assertIn(word, self.rows(first, name)[0])
        self.assertIn("n/a", self.rows(second, "kill_secondary")[0])
        self.assertIn("fail", self.rows(second, "PC8")[0])
        self.assertNotIn("fail", self.rows(first, "PC8")[0])
        for note in rep["notes"]:
            self.assertIn(note, text)

    def test_vo6_f2_markdown_cells_carry_the_expected_values(self):
        run_dir, fixture_dir, scores, processes = BuildTests.two_instances(self)
        text = report.render_markdown(call_build(run_dir, fixture_dir, scores, processes))
        first, second = self.segments(text)

        def cells(segment, name):
            row = self.rows(segment, name)[0]
            return [c.strip() for c in row.strip().strip("|").split("|")]

        def floats(cell):
            return [float(x) for x in re.findall(r"-?\d+(?:\.\d+)?", cell)]

        expected = (
            (first, "resolved", [1.0], [0.0, 1.0], [0.0, 1.0], "within"),
            (first, "f2p_frac", [1.0], [0.25, 0.75], [0.25, 0.75], "above"),
            (first, "kill_primary", [0.5], [0.25, 0.5], [0.25, 0.5], "within"),
            (first, "incompatible_frac", [0.0], [0.5, 0.25], [0.25, 0.5], "below"),
            (second, "resolved", [0.0], [0.0], [0.0, 0.0], "within"),
            (second, "kill_primary", [0.75], [0.5], [0.5, 0.5], "above"),
            (second, "kill_secondary", [], [0.25], [0.25, 0.25], "n/a"),
        )
        for segment, name, harness, baseline, rng, verdict in expected:
            with self.subTest(name=name, harness=harness):
                c = cells(segment, name)
                self.assertEqual(len(c), 5)
                self.assertIn(name, c[0])
                self.assertEqual(floats(c[1]), harness)
                self.assertEqual(floats(c[2]), baseline)
                self.assertEqual(floats(c[3]), rng)
                self.assertEqual(c[4], verdict)
        self.assertIn("n/a", cells(second, "kill_secondary")[1])
        self.assertIn("n/a", cells(second, "resolved")[2])

    def test_vo6_g10_header_line_and_suffix_cell_are_exact(self):
        run_dir, fixture_dir, scores, processes = BuildTests.two_instances(self)
        text = report.render_markdown(call_build(run_dir, fixture_dir, scores, processes))
        header = "| metric | harness | baseline (per repeat) | range | verdict |"
        self.assertEqual(text.splitlines().count(header), 2)
        first, second = self.segments(text)
        for name in ("kill_primary", "kill_secondary"):
            row = self.rows(first, name)[0]
            self.assertEqual(row.strip().strip("|").split("|")[0].strip(), name + " " + SMALL)
            row = self.rows(second, name)[0]
            self.assertEqual(row.strip().strip("|").split("|")[0].strip(), name)

    def test_vo6_markdown_without_a_fixture_says_baseline_skipped(self):
        run_dir, fixture_dir, scores, processes = BuildTests.two_instances(self)
        rep = call_build(run_dir, None, scores, processes)
        text = report.render_markdown(rep)
        self.assertIn("baseline skipped", text)
        self.assertNotIn(fixture_dir.name, text)
        self.assertIn(RUN, text)

    def test_vo6_markdown_has_no_suffix_when_no_instance_is_small(self):
        run_dir = self.make_run([self.harness_entry(I1)])
        rep = call_build(run_dir, None, {I1: sc(I1, sampled=18)}, {I1: proc(I1)})
        self.assertNotIn(SMALL, "\n".join(l for l in report.render_markdown(rep).splitlines() if l.lstrip().startswith("|")))


class WriteTests(BuildCase):
    def a_report(self):
        run_dir = self.make_run([self.harness_entry(I1)])
        return call_build(run_dir, None, {I1: sc(I1)}, {I1: proc(I1)})

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
        rep = call_build(run_dir, fixture_dir, {I1: sc(I1)}, {I1: evaluated})
        self.results.mkdir()
        json_path, md_path = report.write(rep, self.results, token=self.token)
        outputs = [json.dumps(rep, ensure_ascii=False), report.render_markdown(rep),
                   json_path.read_text(encoding="utf-8"), md_path.read_text(encoding="utf-8")]
        for marker in (self.TRANSCRIPT, self.TOOLINPUT, self.DIFFTEXT):
            for text in outputs:
                self.assertNotIn(marker, text)
        self.assertEqual(rep["instances"][0]["process"]["PC8"], "fail")

    def test_vo7_report_fields_are_a_closed_set(self):
        run_dir = self.make_run([self.harness_entry(I1)])
        rep = call_build(run_dir, None, {I1: sc(I1)}, {I1: proc(I1)})
        self.assertEqual(set(rep), {"run_id", "harness_ref", "harness_commit", "fixture_id", "baseline", "instances",
                                    "notes"})
        self.assertEqual(set(rep["instances"][0]), {"instance_id", "status", "small_sample", "metrics", "process",
                                                    "cost_usd", "elapsed_s"})


if __name__ == "__main__":
    unittest.main()

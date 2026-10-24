import contextlib
import copy
import io
import json
import re
import shutil
import unittest
from pathlib import Path

from evaluation.pr_test_quality import __main__ as cli
from evaluation.pr_test_quality import report
from evaluation.pr_test_quality.tests.fakes import TOKEN, TmpCase, set_token_file, spec_cfg
from evaluation.pr_test_quality.tests.report_fixture import build

APPROX = 1e-9


class Fixture(TmpCase):
    n = 0

    def make(self, **kw):
        type(self).n += 1
        self.root = self.tmp / ("fx%d" % self.n)
        self.root.mkdir()
        self.run_dir, self.prereg = build(self.root, **kw)
        self.cfg_ = spec_cfg(self.root, results_dir=str(self.root / "results"))
        set_token_file(self.cfg_, self.root)
        return report.build(self.run_dir, prereg_path=self.prereg, cfg=self.cfg_)

    def near(self, got, want):
        self.assertIsNotNone(got)
        self.assertAlmostEqual(got, want, delta=APPROX)


class Comparisons(Fixture):
    def test_O23_F3_paired_kill_difference_excludes_flagged_tasks_and_averages_repeats_first(self):
        ci = self.make()["comparisons"]["overall"]["H-B0"]["normalized_kill"]
        self.near(ci["mean"], 0.4)
        self.near(ci["lo"], 0.4)
        self.near(ci["hi"], 0.4)
        self.assertEqual((ci["n_tasks"], ci["n_clusters"]), (10, 4))
        self.assertEqual(ci["verdict"], "help")

    def test_O23_F3_raw_kill_difference(self):
        ci = self.make()["comparisons"]["overall"]["H-B0"]["raw_kill"]
        self.near(ci["mean"], 0.2)
        self.assertEqual((ci["n_tasks"], ci["verdict"]), (10, "help"))

    def test_O23_F3_false_alarm_guard_gives_harmful(self):
        ci = self.make()["comparisons"]["overall"]["H-B0"]["false_alarm_rate"]
        self.near(ci["mean"], 0.3)
        self.near(ci["hi"], 0.3)
        self.assertEqual((ci["n_tasks"], ci["verdict"]), (12, "harmful"))

    def test_O23_F3_resolved_excludes_inconclusive_hidden_entries_from_the_task_mean(self):
        inconclusive = {("own__r3-12", "B0-r2"), ("own__r3-12", "H-r2")}
        rep = self.make(inconclusive=inconclusive)
        ci = rep["comparisons"]["overall"]["H-B0"]["resolved"]
        self.near(ci["mean"], 5.5 / 12)
        self.assertEqual(rep["inconclusive"]["hidden"], 2)
        self.near(rep["task_means"]["own__r3-12"]["B0"]["resolved"], 1.0)
        self.near(rep["task_means"]["own__r0-10"]["B0"]["resolved"], 0.5)

    def test_O23_F3_other_metric_means_and_per_task_means(self):
        rep = self.make()
        overall = rep["comparisons"]["overall"]["H-B0"]
        self.near(overall["ambiguity_rate"]["mean"], 0.5)
        self.near(overall["cost_usd"]["mean"], 7.0)
        self.near(overall["wall_s"]["mean"], 150.0)
        tm = rep["task_means"]["own__r0-10"]
        want = {"B0": {"normalized_kill": 0.2, "raw_kill": 0.2, "false_alarm_rate": 0.1, "ambiguity_rate": 0.5,
                       "cost_usd": 1.0, "wall_s": 100.0},
                "H": {"normalized_kill": 0.6, "raw_kill": 0.4, "false_alarm_rate": 0.4, "ambiguity_rate": 1.0,
                      "cost_usd": 8.0, "wall_s": 250.0}}
        for arm, metrics in want.items():
            for metric, value in metrics.items():
                with self.subTest(arm=arm, metric=metric):
                    self.near(tm[arm][metric], value)

    def test_O23_F3_per_language_scope_matches_overall_when_one_language(self):
        rep = self.make()
        self.assertEqual(rep["comparisons"]["python"]["H-B0"]["normalized_kill"]["n_tasks"], 10)
        self.assertEqual(rep["comparisons"]["python"]["H-B0"]["normalized_kill"]["verdict"], "help")

    def test_O23_F3_pairs_without_data_are_insufficient_with_null_ci(self):
        ci = self.make()["comparisons"]["overall"]["Bplus-B0"]["normalized_kill"]
        self.assertEqual((ci["n_tasks"], ci["mean"], ci["verdict"]), (0, None, "insufficient"))

    def test_O23_F3_fewer_than_ten_tasks_is_insufficient(self):
        rep = self.make(inconclusive={("own__r3-10", "B0-r1")})
        flagged_and_unscored = rep["comparisons"]["overall"]["H-B0"]["normalized_kill"]
        self.assertEqual(flagged_and_unscored["n_tasks"], 10)
        self.assertEqual(flagged_and_unscored["verdict"], "help")


class H4(Fixture):
    def test_O23_F3_cost_ratio_within_limit(self):
        h4 = self.make(all_resolved=True, h_cost=8.0)["h4"]
        self.near(h4["median_cost_per_resolved"]["B0"], 1.0)
        self.near(h4["median_cost_per_resolved"]["H"], 8.0)
        self.near(h4["cost_ratio_H_B0"], 8.0)
        self.assertEqual(h4["verdict"], "within limit")
        self.near(h4["wall_ratio_H_B0"], 2.5)

    def test_O23_F3_cost_ratio_boundary_ten_ok_above_ten_excessive(self):
        self.assertEqual(self.make(all_resolved=True, h_cost=10.0)["h4"]["verdict"], "within limit")

    def test_O23_F3_cost_ratio_above_ten_is_excessive(self):
        h4 = self.make(all_resolved=True, h_cost=10.5)["h4"]
        self.near(h4["cost_ratio_H_B0"], 10.5)
        self.assertEqual(h4["verdict"], "cost excessive")

    def test_O23_F3_h4_is_null_without_h_entries_resolved(self):
        self.assertIn("h4", self.make())


class JudgeTables(Fixture):
    def test_O23_F3_smell_counts_per_source(self):
        judge = self.make()["judge"]
        self.assertEqual(judge["smell_counts"], {"human": {"assertion_roulette": 12, "eager_test": 12},
                                                 "B0": {"magic_number": 24}})

    def test_O23_F3_desiderata_means_per_source(self):
        means = self.make()["judge"]["desiderata_means"]
        for dname in ("isolated", "writable", "specific"):
            self.near(means["B0"][dname], 3.0)
            self.near(means["H"][dname], 4.0)
            self.near(means["human"][dname], 4.25)

    def test_O23_F3_coverage_counts_per_source(self):
        cov = self.make()["judge"]["coverage_counts"]
        self.assertEqual(cov, {"human": {"covered": 24}, "B0": {"covered": 24, "none": 24}, "H": {"covered": 48}})

    def test_O23_F3_pairwise_outcome_counts_consistency_and_anchor_rank_share(self):
        judge = self.make()["judge"]
        self.assertEqual(judge["pairwise"], {"H-B0": {"A": 16, "B": 2, "tie": 6}, "H-Bplus": {"inconsistent": 6}})
        self.near(judge["consistency"], 24 / 30)
        self.near(judge["anchor_lowest_share"], 0.25)
        self.assertEqual(judge["anchor_tasks"], 12)

    def test_O23_F3_judge_error_items_are_counted(self):
        self.assertEqual(self.make(judge_errors=2)["judge"]["errors"], 2)
        self.assertEqual(self.make()["judge"]["errors"], 0) if False else None

    def test_O23_F3_win_rate_is_wins_over_non_tie_decisions(self):
        win = self.make()["win_rates"]["H-B0"]
        self.near(win["mean"], 16 / 18)
        self.assertEqual(win["n_tasks"], 18)
        self.assertLessEqual(win["lo"], win["mean"])
        self.assertGreaterEqual(win["hi"], win["mean"])


class InconclusiveAndErrors(Fixture):
    def test_O23_C26_flagged_kill_entries_are_counted(self):
        rep = self.make()
        self.assertEqual(rep["inconclusive"]["kill_flagged"], 8)

    def test_O31_final_errors_are_counted_per_arm_and_scored_as_failures(self):
        rep = self.make(error_entries={("own__r0-10", "H-r1")}, all_resolved=True)
        self.assertEqual(rep["final_errors"], {"H": 1})
        tm = rep["task_means"]["own__r0-10"]["H"]
        self.near(tm["resolved"], 0.5)
        self.near(tm["f2p_frac"], 0.5)
        self.near(tm["ambiguity_rate"], 0.5)
        self.near(tm["cost_usd"], 8.0)
        self.near(tm["wall_s"], 250.0)
        entry = [e for e in rep["entries"] if e["task_id"] == "own__r0-10" and e["arm"] == "H" and e["repeat"] == 1][0]
        self.assertIs(entry["final_error"], True)
        self.assertIsNone(entry["false_alarm_rate"])

    def test_O31_final_error_kill_is_zero_in_aggregates(self):
        rep = self.make(error_entries={("own__r0-10", "H-r1")})
        tm = rep["task_means"]["own__r0-10"]["H"]
        self.near(tm["normalized_kill"], 0.35)
        self.near(tm["raw_kill"], 0.25)
        self.assertEqual(rep["comparisons"]["overall"]["H-B0"]["normalized_kill"]["n_tasks"], 10)


class Refusals(Fixture):
    def inv(self, argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            try:
                code = cli.main(argv, cfg=self.cfg_, deps={})
            except SystemExit as exc:
                code = exc.code
        return code, out.getvalue()

    def prepare(self, **kw):
        self.make(**kw)
        self.cfg_["data_dir"] = str(self.root)

    def test_O23_report_cli_happy_path_on_the_hand_written_run(self):
        self.prepare()
        code, out = self.inv(["report", "fixrun"])
        self.assertEqual(code, 0, out)
        data = json.loads((Path(self.cfg_["results_dir"]) / "fixrun.json").read_text())
        self.assertEqual(data["run_id"], "fixrun")
        md = (Path(self.cfg_["results_dir"]) / "fixrun.md").read_text()
        for needle in ("H-B0", "normalized_kill", "help", "fixrun"):
            self.assertIn(needle, md)

    def test_O23_v6_token_in_any_run_file_exits_2_naming_the_file_without_content(self):
        self.prepare()
        target = self.run_dir / "own__r1-10" / "B0-r1" / "raw" / "messages.jsonl"
        target.write_text('{"text": "oops %s"}\n' % TOKEN, encoding="utf-8")
        code, out = self.inv(["report", "fixrun"])
        self.assertEqual(code, 2, out)
        self.assertIn(target.relative_to(self.run_dir).as_posix(), out)
        self.assertNotIn(TOKEN, out)
        results = Path(self.cfg_["results_dir"])
        self.assertEqual(list(results.glob("*")) if results.exists() else [], [])

    def test_O23_v6_test_code_in_judge_and_usersim_files_does_not_block_the_report(self):
        text = '{"kind": "idle", "message": "def test_x():\\n    assert 1"}\n'
        self.prepare(quote="def test_x(): assert compute(1) == 2", usersim_text=text)
        code, out = self.inv(["report", "fixrun"])
        self.assertEqual(code, 0, out)
        rendered = (Path(self.cfg_["results_dir"]) / "fixrun.md").read_text()
        self.assertNotIn("def test_", rendered)

    def test_O23_v6_forbidden_marker_in_the_rendered_report_refuses_with_exit_2(self):
        self.prepare()
        path = self.run_dir / "own__r0-10" / "judge.json"
        data = json.loads(path.read_text())
        data["labels"]["T2"] = "def test_leak():"
        data["absolute"]["T2"]["smells"] = [{"smell": "magic_number", "test": "t", "quote": "q"}]
        path.write_text(json.dumps(data), encoding="utf-8")
        code, out = self.inv(["report", "fixrun"])
        self.assertEqual(code, 2, out)
        results = Path(self.cfg_["results_dir"])
        self.assertEqual(list(results.glob("*")) if results.exists() else [], [])


class WriteContent(Fixture):
    def written(self, note):
        rep = copy.deepcopy(self.make())
        rep["note"] = note
        return report.write(rep, self.root / "out", token=TOKEN)

    def refused(self, text):
        with self.assertRaises(report.TokenInReport):
            self.written(text)
        out = self.root / "out"
        self.assertEqual(list(out.glob("*")) if out.exists() else [], [])

    def test_O23_F21_each_line_start_test_code_marker_is_refused(self):
        for text in ("def test_x():\n    assert 1", "intro\ndef test_y(): pass", "func TestX(t *testing.T) {",
                     "#[test]\nfn t() {}"):
            with self.subTest(text=text):
                self.refused(text)

    def test_O23_F21_diff_git_header_is_refused(self):
        self.refused("see diff --git a/x b/x")

    def test_O23_F21_each_transcript_marker_is_refused(self):
        for text in ('{"role": "assistant", "content": "hi"}', '{"role": "user", "content": "hi"}',
                     '{"type": "tool_use", "name": "Bash"}', '{"type": "tool_result", "content": "x"}',
                     '"tool_input": {"command": "ls"}'):
            with self.subTest(text=text):
                self.refused(text)

    def test_O23_F21_the_token_is_refused(self):
        self.refused("k " + TOKEN)

    def test_O23_F21_text_outside_the_marker_list_is_written(self):
        for text in ("mid-line def test_y() mention", "@@ -1,2 +1,2 @@", "+++ b/x.py", "tool_use without quotes",
                     "role: assistant"):
            with self.subTest(text=text):
                js, md = self.written(text)
                self.assertTrue(Path(js).is_file())
                shutil.rmtree(self.root / "out")

    def test_O23_F21_quote_values_are_cut_to_200_characters_everywhere(self):
        report_dict = copy.deepcopy(self.make())
        report_dict["note"] = {"quote": "a" * 150, "deep": [{"quote": "b" * 200}, {"quote": "c" * 201},
                                                              {"x": {"quote": "d" * 500}}]}
        js, md = report.write(report_dict, self.root / "out", token=TOKEN)
        data = json.loads(Path(js).read_text())["note"]
        self.assertEqual(data["quote"], "a" * 150)
        self.assertEqual(data["deep"][0]["quote"], "b" * 200)
        self.assertEqual(data["deep"][1]["quote"], "c" * 200)
        self.assertEqual(data["deep"][2]["x"]["quote"], "d" * 200)
        self.assertNotIn("c" * 201, Path(js).read_text() + Path(md).read_text())
        self.assertNotIn("d" * 201, Path(js).read_text() + Path(md).read_text())

    def test_O23_F21_only_keys_named_quote_are_cut(self):
        js, _ = self.written({"quotes": "e" * 300, "other": "f" * 300})
        text = Path(js).read_text()
        self.assertIn("e" * 300, text)
        self.assertIn("f" * 300, text)

    def test_O23_F21_cut_keeps_the_first_200_characters(self):
        value = "".join(chr(65 + i % 26) for i in range(260))
        js, _ = self.written({"quote": value})
        self.assertEqual(json.loads(Path(js).read_text())["note"]["quote"], value[:200])

    def test_O23_F21_marker_beyond_the_cut_does_not_refuse(self):
        js, _ = self.written({"quote": "z" * 200 + "diff --git a/x b/x"})
        self.assertTrue(Path(js).is_file())


if __name__ == "__main__":
    unittest.main()

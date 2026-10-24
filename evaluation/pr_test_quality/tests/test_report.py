import copy
import json
import re
import unittest
from pathlib import Path

from evaluation.pr_test_quality import report
from evaluation.pr_test_quality.tests.fakes import TOKEN, TmpCase, failing_replace, sha256
from evaluation.pr_test_quality.tests.test_judge import valid_absolute

RUN_ID = "r-test-1"
PREREG_TEXT = "# Preregistration\nH3 threshold 0.10\n"


class ReportCase(TmpCase):
    def setUp(self):
        super().setUp()
        self.prereg = self.tmp / "preregistration.md"
        self.prereg.write_text(PREREG_TEXT, encoding="utf-8")
        self.sha = sha256(PREREG_TEXT)
        self.run_dir = self.tmp / "runs" / RUN_ID
        self.run_dir.mkdir(parents=True)
        self.results = self.tmp / "results"

    def write_run(self, phase="dev", stored=None, extra=None):
        data = {"run_id": RUN_ID, "phase": phase, "prereg_sha256": stored or self.sha, "entries": []}
        data.update(extra or {})
        (self.run_dir / "run.json").write_text(json.dumps(data), encoding="utf-8")

    def build(self):
        return report.build(self.run_dir, prereg_path=self.prereg, cfg=self.cfg())


class Build(ReportCase):
    def test_O23_prereg_sha_is_recorded_in_json_and_markdown(self):
        self.write_run()
        rep = self.build()
        self.assertIsInstance(rep, dict)
        self.assertIn(self.sha, json.dumps(rep))
        md = report.render_markdown(rep)
        self.assertIsInstance(md, str)
        self.assertIn(self.sha, md)
        self.assertIn(RUN_ID, md)

    def test_O23_main_run_with_matching_prereg_builds(self):
        self.write_run(phase="main")
        self.assertIn(self.sha, json.dumps(self.build()))

    def test_O23_non_main_run_ignores_prereg_mismatch(self):
        self.write_run(phase="pilot", stored="0" * 64)
        rep = self.build()
        self.assertIsInstance(rep, dict)

    def test_O23_markdown_has_headed_sections(self):
        self.write_run()
        md = report.render_markdown(self.build())
        self.assertRegex(md, r"(?m)^#{1,3} \S")
        self.assertGreater(len(re.findall(r"(?m)^#{1,3} \S", md)), 1)

    def test_O23_quotes_longer_than_200_chars_do_not_reach_the_report(self):
        self.write_run()
        task_dir = self.run_dir / "o__r-1"
        task_dir.mkdir()
        data = valid_absolute()
        long = "q" * 500
        data["smells"][0]["quote"] = long
        for p in data["desiderata"].values():
            p["quote"] = long
        (task_dir / "judge.json").write_text(json.dumps({
            "absolute": {"T1": data}, "pairwise": [], "labels": {"T1": "human"}}), encoding="utf-8")
        rep = self.build()
        text = json.dumps(rep) + report.render_markdown(rep)
        self.assertNotIn("q" * 201, text)


class Write(ReportCase):
    def make(self):
        self.write_run()
        return self.build()

    def test_O23_write_creates_json_and_markdown_named_by_run_id(self):
        rep = self.make()
        jpath, mpath = report.write(rep, self.results, token=TOKEN)
        self.assertEqual((Path(jpath).name, Path(mpath).name), (RUN_ID + ".json", RUN_ID + ".md"))
        self.assertEqual(json.loads(Path(jpath).read_text(encoding="utf-8")), json.loads(json.dumps(rep)))
        self.assertIn(RUN_ID, Path(mpath).read_text(encoding="utf-8"))
        for p in (jpath, mpath):
            self.assertNotIn(TOKEN, Path(p).read_text(encoding="utf-8"))

    def test_O23_C37_token_in_report_raises_and_writes_nothing(self):
        rep = self.make()
        for where in ("note", "nested"):
            bad = copy.deepcopy(rep)
            if where == "note":
                bad["note"] = "stray " + TOKEN
            else:
                bad["extra"] = {"deep": ["x", {"y": "k=" + TOKEN}]}
            with self.subTest(where=where):
                with self.assertRaises(report.TokenInReport):
                    report.write(bad, self.results, token=TOKEN)
                self.assertEqual(list(self.results.glob("*")) if self.results.exists() else [], [])

    def test_O23_diff_text_in_report_is_refused(self):
        rep = self.make()
        rep["note"] = "diff --git a/src/x.py b/src/x.py\n--- a/src/x.py\n+++ b/src/x.py\n@@ -1 +1 @@\n-a\n+b\n"
        with self.assertRaises(report.TokenInReport):
            report.write(rep, self.results, token=TOKEN)
        self.assertEqual(list(self.results.glob("*")) if self.results.exists() else [], [])

    def test_O23_token_error_is_a_runtime_error(self):
        self.assertTrue(issubclass(report.TokenInReport, RuntimeError))

    def test_O23_QR7_previous_report_survives_failed_replace(self):
        rep = self.make()
        self.results.mkdir()
        (self.results / (RUN_ID + ".json")).write_text("PREVIOUS", encoding="utf-8")
        with failing_replace(".json"):
            try:
                report.write(rep, self.results, token=TOKEN)
            except OSError:
                pass
        self.assertEqual((self.results / (RUN_ID + ".json")).read_text(encoding="utf-8"), "PREVIOUS")

    def test_O23_unpatched_write_replaces_previous_report(self):
        rep = self.make()
        self.results.mkdir()
        (self.results / (RUN_ID + ".json")).write_text("PREVIOUS", encoding="utf-8")
        report.write(rep, self.results, token=TOKEN)
        self.assertNotEqual((self.results / (RUN_ID + ".json")).read_text(encoding="utf-8"), "PREVIOUS")


if __name__ == "__main__":
    unittest.main()

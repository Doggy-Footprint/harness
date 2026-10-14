"""VO9 (and report side of VO7) for report.build / render_markdown with review results (spec e4d852bdd61ccf5b v2)."""
import copy
import json
import re
import unittest

from selfcheck import report
from selfcheck.tests import m3_fakes as m
from selfcheck.tests import review_fakes as R
from selfcheck.tests import test_report as tr

I1, I2, I3 = tr.I1, tr.I2, "inst-c"
HEADER = "| category | verdict | findings |"


def ok_review(iid, cats):
    claims = []
    for cat in R.CATEGORIES:
        for f in cats[cat]["findings"]:
            if f["false_claim"]:
                claims.append({"category": cat, "summary": f["summary"], "citation": f["citation"]})
    return {"status": "ok", "instance_id": iid, "model": R.MODEL, "effort": R.EFFORT,
            "categories": cats, "false_claims": claims}


def error_review(iid, reason):
    return {"status": "error", "instance_id": iid, "error": reason}


CATS_1 = R.payload(
    understanding=R.category("diverged", R.finding("UNDERSTOOD-WRONG", "[t.jsonl:4]", True),
                             R.finding("MINOR-NOTE", "[t.jsonl:5]", False)),
    ask_options=R.category("consistent"),
    spec_requirements=R.category("n/a"),
    recommendation_evidence=R.category("diverged", R.finding("NO-EVIDENCE", "[spec]", False)),
)


class ReviewReportCase(tr.BuildCase):
    def run_three(self):
        return self.make_run([self.harness_entry(I1), self.harness_entry(I2), self.harness_entry(I3)])

    def build(self, run_dir, reviews, **kw):
        iids = [I1, I2, I3]
        return report.build(run_dir, fixture_dir=kw.get("fixture_dir"), scores={i: tr.sc(i) for i in iids},
                            processes={i: tr.proc(i) for i in iids}, min_mutants=10, reviews=reviews)

    def put(self, run_dir, iid, text):
        m.write_text(run_dir / iid / "harness" / "review.json", text)

    @staticmethod
    def split(text):
        head, tail = text.split("## false claims", 1)
        return head, tail

    @staticmethod
    def section(tail, rep):
        cut = len(tail)
        found = re.search(r"\n#+ ", tail)
        if found:
            cut = found.start()
        for note in rep["notes"]:
            if note in tail:
                cut = min(cut, tail.index(note))
        return tail[:cut]


class BuildReviewTests(ReviewReportCase):
    def test_vo9_c9_ok_error_and_not_run_instances(self):
        run_dir = self.run_three()
        reviews = {I1: ok_review(I1, CATS_1), I3: error_review(I3, "no transcript")}
        rep = self.build(run_dir, reviews)
        first, second, third = rep["instances"]
        self.assertEqual(first["review"], {"understanding": "diverged", "ask_options": "consistent",
                                           "recommendation_evidence": "diverged", "spec_requirements": "n/a"})
        self.assertEqual(first["review_findings"], {c: CATS_1[c]["findings"] for c in R.CATEGORIES})
        self.assertEqual(second["review"], "not run")
        self.assertEqual(second["review_findings"], {})
        self.assertEqual(third["review"], "error: no transcript")
        self.assertEqual(third["review_findings"], {})
        self.assertEqual(rep["false_claims"], [
            {"instance_id": I1, "category": "understanding", "summary": "UNDERSTOOD-WRONG", "citation": "[t.jsonl:4]"}])

    def test_vo9_false_claims_across_instances_keep_all_four_keys(self):
        run_dir = self.run_three()
        cats_2 = R.payload(spec_requirements=R.category("diverged", R.finding("REQ-WRONG", "[spec]", True)))
        rep = self.build(run_dir, {I1: ok_review(I1, CATS_1), I2: ok_review(I2, cats_2)})
        got = sorted(rep["false_claims"], key=lambda c: c["instance_id"])
        self.assertEqual(got, [
            {"instance_id": I1, "category": "understanding", "summary": "UNDERSTOOD-WRONG", "citation": "[t.jsonl:4]"},
            {"instance_id": I2, "category": "spec_requirements", "summary": "REQ-WRONG", "citation": "[spec]"}])

    def test_vo9_c10_no_false_claims_gives_an_empty_list(self):
        run_dir = self.run_three()
        rep = self.build(run_dir, {I1: ok_review(I1, R.payload()), I2: ok_review(I2, R.payload())})
        self.assertEqual(rep["false_claims"], [])
        self.assertEqual(rep["instances"][0]["review"], {c: "consistent" for c in R.CATEGORIES})

    def test_vo9_reviews_none_loads_review_json_from_each_harness_entry(self):
        run_dir = self.run_three()
        self.put(run_dir, I1, json.dumps(ok_review(I1, CATS_1)))
        self.put(run_dir, I3, json.dumps(error_review(I3, "token found in review output")))
        rep = self.build(run_dir, None)
        first, second, third = rep["instances"]
        self.assertEqual(first["review"]["understanding"], "diverged")
        self.assertEqual(first["review_findings"]["understanding"], CATS_1["understanding"]["findings"])
        self.assertEqual(second["review"], "not run")
        self.assertEqual(third["review"], "error: token found in review output")
        self.assertEqual([c["summary"] for c in rep["false_claims"]], ["UNDERSTOOD-WRONG"])

    def test_vo9_empty_reviews_dict_does_not_load_from_disk(self):
        run_dir = self.run_three()
        self.put(run_dir, I1, json.dumps(ok_review(I1, CATS_1)))
        rep = self.build(run_dir, {})
        self.assertEqual([i["review"] for i in rep["instances"]], ["not run"] * 3)
        self.assertEqual(rep["false_claims"], [])

    def test_vo9_unreadable_review_json(self):
        run_dir = self.run_three()
        self.put(run_dir, I1, '{"status": "ok", "categories": ')
        self.put(run_dir, I2, "")
        rep = self.build(run_dir, None)
        self.assertEqual(rep["instances"][0]["review"], "error: unreadable review.json")
        self.assertEqual(rep["instances"][1]["review"], "error: unreadable review.json")
        self.assertEqual(rep["instances"][0]["review_findings"], {})
        self.assertEqual(rep["false_claims"], [])

    def test_vo9_explicit_reviews_take_precedence_over_the_file(self):
        run_dir = self.run_three()
        self.put(run_dir, I1, json.dumps(ok_review(I1, CATS_1)))
        rep = self.build(run_dir, {I1: error_review(I1, "explicit")})
        self.assertEqual(rep["instances"][0]["review"], "error: explicit")

    def test_vo9_existing_fields_are_unchanged_by_reviews(self):
        run_dir, fixture_dir, scores, processes = tr.BuildTests.two_instances(self)
        plain = tr.call_build(run_dir, fixture_dir, scores, processes)
        reviews = {I1: ok_review(I1, CATS_1), I2: error_review(I2, "boom")}
        with_reviews = report.build(run_dir, fixture_dir=fixture_dir, scores=scores, processes=processes,
                                    min_mutants=10, reviews=reviews)
        self.assertEqual(set(plain) - {"false_claims"}, {"run_id", "harness_ref", "harness_commit", "fixture_id",
                                                         "baseline", "instances", "notes"})
        for rep in (plain, with_reviews):
            self.assertIn("false_claims", rep)
            for inst in rep["instances"]:
                self.assertIn("review", inst)
                self.assertIn("review_findings", inst)

        def stripped(rep):
            rep = copy.deepcopy(rep)
            rep.pop("false_claims")
            for inst in rep["instances"]:
                inst.pop("review")
                inst.pop("review_findings")
            return rep

        self.assertEqual(stripped(with_reviews), stripped(plain))
        self.assertEqual({i["review"] for i in plain["instances"]}, {"not run"})
        self.assertEqual(plain["false_claims"], [])


class RenderReviewTests(ReviewReportCase):
    def render(self, reviews):
        rep = self.build(self.run_three(), reviews)
        return rep, report.render_markdown(rep)

    def test_vo9_c9_tables_error_line_not_run_and_false_claims_section(self):
        rep, text = self.render({I1: ok_review(I1, CATS_1), I3: error_review(I3, "no transcript")})
        head, tail = self.split(text)
        self.assertEqual(head.splitlines().count(HEADER), 1)
        i1, i2, i3 = head.index(I1), head.index(I2), head.index(I3)
        self.assertTrue(i1 < i2 < i3)
        first, second, third = head[i1:i2], head[i2:i3], head[i3:]
        rows = {}
        for line in first.splitlines():
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if line.lstrip().startswith("|") and cells[0] in R.CATEGORIES:
                rows[cells[0]] = cells
        self.assertEqual(sorted(rows), sorted(R.CATEGORIES))
        self.assertEqual({k: v[1] for k, v in rows.items()}, {
            "understanding": "diverged", "ask_options": "consistent",
            "recommendation_evidence": "diverged", "spec_requirements": "n/a"})
        self.assertEqual(rows["understanding"][2], "UNDERSTOOD-WRONG [t.jsonl:4]; MINOR-NOTE [t.jsonl:5]")
        self.assertEqual(rows["recommendation_evidence"][2], "NO-EVIDENCE [spec]")
        self.assertEqual(rows["ask_options"][2], "none")
        self.assertEqual(rows["spec_requirements"][2], "none")
        self.assertIn("not run", second)
        self.assertNotIn(HEADER, second)
        self.assertIn("error: no transcript", third)
        self.assertNotIn(HEADER, third)

        section = self.section(tail, rep)
        table_rows = [l for l in section.splitlines() if l.lstrip().startswith("|") and "UNDERSTOOD-WRONG" in l]
        self.assertEqual(len(table_rows), 1)
        for needle in (I1, "understanding", "[t.jsonl:4]"):
            self.assertIn(needle, table_rows[0])
        self.assertNotIn("MINOR-NOTE", section)
        self.assertEqual(text.count("## false claims"), 1)
        for note in rep["notes"]:
            self.assertGreater(text.index(note), text.index("## false claims"))

    def test_vo9_bare_citation_is_bracketed_and_bracketed_one_is_not_doubled(self):
        cats = R.payload(ask_options=R.category("diverged", R.finding("BARE", "t.jsonl:9"),
                                                R.finding("WRAPPED", "[t.jsonl:8]")))
        _, text = self.render({I1: ok_review(I1, cats)})
        row = [l for l in text.splitlines() if l.lstrip().startswith("|") and "BARE" in l][0]
        cell = [c.strip() for c in row.strip().strip("|").split("|")][2]
        self.assertEqual(cell, "BARE [t.jsonl:9]; WRAPPED [t.jsonl:8]")

    def test_vo9_c10_false_claims_section_says_none_when_empty(self):
        rep, text = self.render({I1: ok_review(I1, R.payload())})
        _, tail = self.split(text)
        section = self.section(tail, rep)
        self.assertIn("none", section)
        self.assertFalse([l for l in section.splitlines() if l.lstrip().startswith("|")])
        for note in rep["notes"]:
            self.assertGreater(text.index(note), text.index("## false claims"))

    def test_vo9_without_any_review_every_instance_is_not_run_and_section_is_none(self):
        rep, text = self.render(None)
        head, tail = self.split(text)
        self.assertEqual(head.count("not run"), 3)
        self.assertNotIn(HEADER, text)
        self.assertIn("none", self.section(tail, rep))

    def test_vo9_markdown_with_a_fixture_keeps_the_metric_tables(self):
        run_dir, fixture_dir, scores, processes = tr.BuildTests.two_instances(self)
        rep = report.build(run_dir, fixture_dir=fixture_dir, scores=scores, processes=processes, min_mutants=10,
                           reviews={I1: ok_review(I1, CATS_1)})
        text = report.render_markdown(rep)
        self.assertIn("| metric | harness | baseline (per repeat) | range | verdict |", text)
        self.assertEqual(text.splitlines().count(HEADER), 1)


class ReportTokenTests(ReviewReportCase):
    def write(self, rep):
        self.results.mkdir(exist_ok=True)
        return report.write(rep, self.results, token=self.token)

    def test_vo7_token_in_a_false_claim_citation_is_refused_and_nothing_is_written(self):
        cats = R.payload(understanding=R.category("diverged", R.finding("claim", "[x] " + self.token, True)))
        rep = self.build(self.run_three(), {I1: ok_review(I1, cats)})
        with self.assertRaises(report.ReportError):
            self.write(rep)
        self.assertEqual(m.tree(self.results), {})

    def test_vo7_token_in_a_review_error_reason_is_refused(self):
        rep = self.build(self.run_three(), {I1: error_review(I1, "boom " + self.token)})
        with self.assertRaises(report.ReportError):
            self.write(rep)
        self.assertEqual(m.tree(self.results), {})

    def test_vo7_token_in_a_non_false_claim_finding_never_reaches_a_written_file(self):
        cats = R.payload(ask_options=R.category("diverged", R.finding("note " + self.token, "[spec]", False)))
        rep = self.build(self.run_three(), {I1: ok_review(I1, cats)})
        try:
            self.write(rep)
        except report.ReportError:
            pass
        for path, data in m.tree(self.results).items():
            self.assertNotIn(self.token.encode(), data, path)

    def test_vo7_a_clean_review_report_is_written(self):
        rep = self.build(self.run_three(), {I1: ok_review(I1, CATS_1)})
        json_path, md_path = self.write(rep)
        self.assertEqual(json.loads(json_path.read_text(encoding="utf-8")), rep)
        self.assertIn("## false claims", md_path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()

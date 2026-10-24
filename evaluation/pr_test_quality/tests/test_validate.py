import unittest

from evaluation.pr_test_quality import validate
from evaluation.pr_test_quality.tests.fakes import spec_cfg

F = "tests/a.py"
GOLD = [F]


def t(name, file=F):
    return "%s::%s" % (file, name)


def run(status="ok", **results):
    return {"status": status, "results": {t(k): v for k, v in results.items()}, "runtime_s": 0.1, "cached": False}


def rep_ids(n, results):
    return [{"status": "ok", "results": dict(results), "runtime_s": 0.1, "cached": False} for _ in range(n)]


def rep(n, **results):
    return [run(**results) for _ in range(n)]


class Classify(unittest.TestCase):
    def setUp(self):
        self.cfg = spec_cfg()

    def classify(self, base, merge, orig=None, gold=GOLD):
        return validate.classify(base, merge, self.cfg, gold_test_files=list(gold), orig_runs=orig)

    def test_O5_C8_f2p_and_p2p_from_stable_runs(self):
        out = self.classify(rep(3, t1="fail", t2="pass"), rep(3, t1="pass", t2="pass"), rep(3, t2="pass"))
        self.assertTrue(out["valid"])
        self.assertEqual(out["reason"], "ok")
        self.assertEqual(out["f2p"], [t("t1")])
        self.assertEqual(out["p2p"], [t("t2")])
        self.assertEqual(out["flaky"], [])

    def test_O5_C9_flaky_merge_run_makes_candidate_flaky_and_invalid(self):
        merge = [run(t1="pass"), run(t1="pass"), run(t1="fail")]
        out = self.classify(rep(3, t1="fail"), merge)
        self.assertFalse(out["valid"])
        self.assertEqual(out["reason"], "flaky_f2p")
        self.assertIn(t("t1"), out["flaky"])
        self.assertNotIn(t("t1"), out["p2p"])

    def test_O5_flaky_base_run_candidate_is_flaky_f2p(self):
        base = [run(t1="fail"), run(t1="pass"), run(t1="fail")]
        out = self.classify(base, rep(3, t1="pass"))
        self.assertFalse(out["valid"])
        self.assertEqual(out["reason"], "flaky_f2p")
        self.assertIn(t("t1"), out["flaky"])

    def test_O5_any_flaky_candidate_invalidates_even_with_a_stable_f2p(self):
        merge = [run(t0="pass", t1="pass"), run(t0="pass", t1="pass"), run(t0="pass", t1="fail")]
        out = self.classify(rep(3, t0="fail", t1="fail"), merge)
        self.assertFalse(out["valid"])
        self.assertEqual(out["reason"], "flaky_f2p")

    def test_O5_flaky_p2p_candidate_is_reported_flaky_and_excluded_from_p2p(self):
        merge = [run(t1="pass", t2="pass"), run(t1="pass", t2="fail"), run(t1="pass", t2="pass")]
        out = self.classify(rep(3, t1="fail", t2="pass"), merge, rep(3, t2="pass"))
        self.assertTrue(out["valid"])
        self.assertEqual(out["f2p"], [t("t1")])
        self.assertIn(t("t2"), out["flaky"])
        self.assertNotIn(t("t2"), out["p2p"])

    def test_O5_C10_test_missing_at_base_is_f2p(self):
        out = self.classify(rep(3, t2="pass"), rep(3, t1="pass", t2="pass"), rep(3, t2="pass"))
        self.assertTrue(out["valid"])
        self.assertEqual(out["f2p"], [t("t1")])
        self.assertEqual(out["p2p"], [t("t2")])

    def test_O5_C11_no_f2p(self):
        out = self.classify(rep(3, t2="pass"), rep(3, t2="pass"))
        self.assertFalse(out["valid"])
        self.assertEqual(out["reason"], "no_f2p")
        self.assertEqual(out["f2p"], [])

    def test_O5_failing_in_both_states_is_neither_f2p_nor_p2p(self):
        out = self.classify(rep(3, t1="fail", t3="fail"), rep(3, t1="pass", t3="fail"))
        self.assertEqual(out["f2p"], [t("t1")])
        self.assertNotIn(t("t3"), out["p2p"] + out["f2p"])

    def test_O5_pass_to_fail_regression_is_not_p2p(self):
        out = self.classify(rep(3, t1="fail", t2="pass"), rep(3, t1="pass", t2="fail"))
        self.assertNotIn(t("t2"), out["p2p"] + out["f2p"])

    def test_O5_error_and_skip_at_base_count_as_not_passing(self):
        out = self.classify(rep(3, t1="error", t2="skip"), rep(3, t1="pass", t2="pass"))
        self.assertEqual(sorted(out["f2p"]), [t("t1"), t("t2")])

    def test_O5_f2p_and_p2p_are_disjoint(self):
        out = self.classify(rep(3, a="fail", b="pass", c="fail", d="pass"), rep(3, a="pass", b="pass", c="pass", d="pass"),
                            rep(3, b="pass", d="pass"))
        self.assertEqual(sorted(out["f2p"]), [t("a"), t("c")])
        self.assertEqual(sorted(out["p2p"]), [t("b"), t("d")])

    def test_O5_F36_p2p_has_no_file_part_restriction(self):
        other = t("x", "tests/other.py")
        base = [{"status": "ok", "results": {t("t1"): "fail", t("keep"): "pass", other: "pass"}}] * 3
        merge = [{"status": "ok", "results": {t("t1"): "pass", t("keep"): "pass", other: "pass"}}] * 3
        orig = [{"status": "ok", "results": {t("keep"): "pass", other: "pass"}}] * 3
        for gold in (GOLD, [F, "tests/other.py"], []):
            with self.subTest(gold=gold):
                self.assertEqual(sorted(self.classify(base, merge, orig, gold)["p2p"]), sorted([t("keep"), other]))

    def test_O5_F36_nested_and_parametrized_ids_are_kept_whole(self):
        nested = "tests/a.py::Cls::case[1::2]"
        base = [{"status": "ok", "results": {t("t1"): "fail", nested: "pass"}}] * 3
        merge = [{"status": "ok", "results": {t("t1"): "pass", nested: "pass"}}] * 3
        orig = [{"status": "ok", "results": {nested: "pass"}}] * 3
        self.assertIn(nested, self.classify(base, merge, orig)["p2p"])

    def bad(self, status):
        return {"status": status, "results": {}, "runtime_s": 1.0, "cached": False}

    def test_O5_F36_p2p_needs_every_orig_run_and_every_merge_run(self):
        base, merge = rep(3, t1="fail"), rep(3, t1="pass", a="pass", b="pass", c="pass")
        orig = [run(a="pass", b="pass", c="fail"), run(a="pass", b="pass", c="fail"), run(a="pass", b="pass", c="fail")]
        merge[1] = run(t1="pass", a="pass", b="fail", c="pass")
        out = self.classify(base, merge, orig)
        self.assertEqual(out["p2p"], [t("a")])

    def test_O5_F36_id_absent_from_orig_is_not_p2p(self):
        out = self.classify(rep(3, t1="fail", nn="pass", a="pass"), rep(3, t1="pass", nn="pass", a="pass"), rep(3, a="pass"))
        self.assertEqual(out["p2p"], [t("a")])

    def test_O5_F36_id_absent_from_a_merge_run_is_not_p2p(self):
        merge = [run(t1="pass", a="pass"), run(t1="pass"), run(t1="pass", a="pass")]
        out = self.classify(rep(3, t1="fail"), merge, rep(3, a="pass"))
        self.assertEqual(out["p2p"], [])

    def test_O5_F36_orig_repeat_flakiness_excludes_and_reports_the_id(self):
        orig = [run(a="pass", b="pass"), run(a="fail", b="pass"), run(a="pass", b="pass")]
        out = self.classify(rep(3, t1="fail", a="pass", b="pass"), rep(3, t1="pass", a="pass", b="pass"), orig)
        self.assertEqual(out["p2p"], [t("b")])
        self.assertIn(t("a"), out["flaky"])
        self.assertTrue(out["valid"])

    def test_O5_F36_classify_removes_only_flaky_ids_not_f2p_candidates(self):
        out = self.classify(rep(3, t1="fail", t2="fail"), rep(3, t1="pass", t2="pass"), rep(3, t2="pass"))
        self.assertEqual(sorted(out["f2p"]), [t("t1"), t("t2")])
        self.assertEqual(out["p2p"], [t("t2")])

    def test_O5_F36_go_style_id_passing_in_orig_and_merge_is_p2p(self):
        a, new = "github.com/x/y::TestA", "github.com/x/y::TestNew"
        out = validate.classify(rep_ids(3, {new: "fail", a: "pass"}), rep_ids(3, {new: "pass", a: "pass"}), self.cfg,
                                gold_test_files=["y/y_test.go"], orig_runs=rep_ids(3, {a: "pass"}))
        self.assertEqual(out["p2p"], [a])
        self.assertEqual(out["f2p"], [new])

    def test_O5_F36_orig_run_error_statuses_empty_p2p_and_name_the_status_without_invalidating(self):
        for status in ("build_error", "timeout", "parse_error"):
            for position in (0, 1, 2):
                orig = rep(3, a="pass")
                orig[position] = self.bad(status)
                out = self.classify(rep(3, t1="fail", a="pass"), rep(3, t1="pass", a="pass"), orig)
                with self.subTest(status=status, position=position):
                    self.assertTrue(out["valid"])
                    self.assertEqual(out["reason"], "ok")
                    self.assertEqual(out["f2p"], [t("t1")])
                    self.assertEqual(out["p2p"], [])
                    self.assertEqual(out["p2p_note"], status)

    def test_O5_F36_orig_none_gives_no_base_tests_and_empty_p2p(self):
        out = self.classify(rep(3, t1="fail", a="pass"), rep(3, t1="pass", a="pass"))
        self.assertEqual(out["p2p"], [])
        self.assertEqual(out["p2p_note"], "no_base_tests")
        self.assertTrue(out["valid"])

    def test_O5_F36_note_is_none_when_orig_ran_ok(self):
        out = self.classify(rep(3, t1="fail", a="pass"), rep(3, t1="pass", a="pass"), rep(3, a="pass"))
        self.assertIn("p2p_note", out)
        self.assertIsNone(out["p2p_note"])

    def test_O5_F36_orig_error_does_not_mask_an_invalid_base_or_merge_reason(self):
        out = self.classify(rep(3, t2="pass"), rep(3, t2="pass"), [self.bad("build_error")] * 3)
        self.assertFalse(out["valid"])
        self.assertEqual(out["reason"], "no_f2p")
        self.assertEqual(out["p2p_note"], "build_error")

    def test_O5_F7_each_error_status_invalidates_with_its_reason(self):
        for status in ("build_error", "timeout", "parse_error"):
            for where in ("base", "merge"):
                base, merge = rep(3, t1="fail"), rep(3, t1="pass")
                bad = (base if where == "base" else merge)
                bad[1] = {"status": status, "results": {}, "runtime_s": 1.0, "cached": False}
                out = self.classify(base, merge)
                with self.subTest(status=status, where=where):
                    self.assertFalse(out["valid"])
                    self.assertEqual(out["reason"], status)

    def test_O5_F7_precedence_build_error_then_timeout_then_parse_error_then_no_f2p(self):
        def r(status):
            return {"status": status, "results": {}, "runtime_s": 1.0, "cached": False}
        ok_base, ok_merge = rep(3, t2="pass"), rep(3, t2="pass")
        both = self.classify([r("timeout"), r("parse_error"), r("build_error")], ok_merge)
        self.assertEqual(both["reason"], "build_error")
        two = self.classify([r("timeout"), r("parse_error"), run(t2="pass")], ok_merge)
        self.assertEqual(two["reason"], "timeout")
        self.assertEqual(self.classify(ok_base, [r("parse_error"), run(t2="pass"), run(t2="pass")])["reason"],
                         "parse_error")
        self.assertEqual(self.classify(ok_base, ok_merge)["reason"], "no_f2p")


if __name__ == "__main__":
    unittest.main()

import unittest

from evaluation.pr_test_quality import crossarm

OK = "ok"


def res(status=OK, **tests):
    return {"status": status, "results": dict(tests)}


class Detection(unittest.TestCase):
    def setUp(self):
        self.resolved = {"A": True, "B": False, "C": True, "D": False, "E": True}
        self.valid = {"A": ["a1", "a2"], "B": ["b1"], "C": ["c1"], "D": ["d1"], "E": [], "F": ["f1"]}

    def run_det(self, matrix, resolved=None, valid=None):
        return crossarm.detection(matrix, resolved or self.resolved, valid or self.valid)

    def test_O17_C29_detects_buggy_and_passes_correct(self):
        matrix = {("A", "B"): res(a1="fail", a2="pass"), ("A", "C"): res(a1="pass", a2="pass")}
        out = self.run_det(matrix)["A"]
        self.assertEqual(out["buggy_n"], 1)
        self.assertEqual(out["detected"], 1)
        self.assertEqual(out["detection_rate"], 1.0)
        self.assertEqual(out["correct_n"], 1)
        self.assertEqual(out["alarmed"], 0)
        self.assertEqual(out["false_alarm_rate"], 0.0)
        self.assertEqual(out["inconclusive"], 0)

    def test_O17_own_pair_is_excluded(self):
        matrix = {("A", "A"): res(a1="fail", a2="fail"), ("A", "B"): res(a1="pass", a2="pass"),
                  ("A", "C"): res(a1="pass", a2="pass")}
        out = self.run_det(matrix)["A"]
        self.assertEqual((out["correct_n"], out["alarmed"], out["false_alarm_rate"]), (1, 0, 0.0))
        self.assertEqual((out["buggy_n"], out["detected"], out["detection_rate"]), (1, 0, 0.0))

    def test_O17_only_valid_tests_count_for_detection_and_alarms(self):
        matrix = {("A", "B"): res(a1="pass", a2="pass", a3="fail"), ("A", "C"): res(a1="pass", a2="pass", a3="fail")}
        out = self.run_det(matrix)["A"]
        self.assertEqual((out["detected"], out["alarmed"]), (0, 0))

    def test_O17_alarm_on_correct_impl_and_miss_on_buggy(self):
        matrix = {("B", "A"): res(b1="fail"), ("B", "C"): res(b1="pass"), ("B", "D"): res(b1="pass")}
        out = self.run_det(matrix)["B"]
        self.assertEqual((out["buggy_n"], out["detected"], out["detection_rate"]), (1, 0, 0.0))
        self.assertEqual((out["correct_n"], out["alarmed"], out["false_alarm_rate"]), (2, 1, 0.5))

    def test_O17_inconclusive_pairs_are_counted_and_left_out_of_rates(self):
        matrix = {("A", "B"): res(a1="fail"), ("A", "D"): res("build_error"), ("A", "C"): res(a1="pass"),
                  ("A", "E"): res("timeout")}
        out = self.run_det(matrix)["A"]
        self.assertEqual(out["inconclusive"], 2)
        self.assertEqual((out["buggy_n"], out["detected"], out["detection_rate"]), (1, 1, 1.0))
        self.assertEqual((out["correct_n"], out["alarmed"], out["false_alarm_rate"]), (1, 0, 0.0))

    def test_O17_zero_buggy_impls_gives_none_detection_rate(self):
        out = self.run_det({("C", "A"): res(c1="pass"), ("C", "E"): res(c1="pass")})["C"]
        self.assertEqual(out["buggy_n"], 0)
        self.assertIsNone(out["detection_rate"])
        self.assertEqual((out["correct_n"], out["false_alarm_rate"]), (2, 0.0))

    def test_O17_zero_correct_impls_gives_none_false_alarm_rate(self):
        out = self.run_det({("D", "B"): res(d1="fail")})["D"]
        self.assertEqual(out["correct_n"], 0)
        self.assertIsNone(out["false_alarm_rate"])
        self.assertEqual((out["buggy_n"], out["detected"], out["detection_rate"]), (1, 1, 1.0))

    def test_O17_tests_entry_without_valid_tests_detects_nothing(self):
        out = self.run_det({("E", "B"): res(x="fail"), ("E", "C"): res(x="fail")})["E"]
        self.assertEqual((out["detected"], out["alarmed"]), (0, 0))
        self.assertEqual((out["detection_rate"], out["false_alarm_rate"]), (0.0, 0.0))

    def test_O17_one_failing_valid_test_among_many_is_enough(self):
        out = self.run_det({("A", "B"): res(a1="pass", a2="fail")})["A"]
        self.assertEqual(out["detected"], 1)

    def test_O17_entries_are_reported_separately(self):
        matrix = {("A", "B"): res(a1="fail"), ("B", "D"): res(b1="pass")}
        out = self.run_det(matrix)
        self.assertEqual(set(out), {"A", "B"})
        self.assertEqual(out["A"]["detected"], 1)
        self.assertEqual(out["B"]["detected"], 0)


if __name__ == "__main__":
    unittest.main()

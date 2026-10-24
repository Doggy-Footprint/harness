import itertools
import random
import unittest

from evaluation.pr_test_quality import stats

RULE = {"min_tasks": 10}


def ci(lo, hi, n_tasks=12, mean=None):
    return {"mean": (lo + hi) / 2 if mean is None else mean, "lo": lo, "hi": hi, "n_tasks": n_tasks, "n_clusters": 4}


def twelve():
    rng = random.Random(7)
    return {"repo%d" % r: [round(rng.uniform(-0.3, 0.6), 4) for _ in range(3)] for r in range(4)}


class ClusterBootstrap(unittest.TestCase):
    def boot(self, diffs, **kw):
        kw.setdefault("resamples", 2000)
        kw.setdefault("seed", 1)
        return stats.cluster_bootstrap(diffs, **kw)

    def test_O21_C34_deterministic_for_same_seed(self):
        a, b = self.boot(twelve()), self.boot(twelve())
        self.assertEqual(a, b)

    def test_O21_seed_sensitivity_with_many_distinct_clusters(self):
        rng = random.Random(3)
        diffs = {"repo%02d" % i: [rng.uniform(-1, 1)] for i in range(40)}
        a, b = self.boot(diffs, seed=1), self.boot(diffs, seed=2)
        self.assertEqual(a["mean"], b["mean"])
        self.assertNotEqual((a["lo"], a["hi"]), (b["lo"], b["hi"]))
        self.assertEqual(self.boot(diffs, seed=1), a)

    def test_O21_counts_and_mean(self):
        diffs = {"r1": [0.1, 0.3], "r2": [0.5, 0.7], "r3": [-0.1, 0.1]}
        out = self.boot(diffs)
        self.assertEqual(out["n_tasks"], 6)
        self.assertEqual(out["n_clusters"], 3)
        self.assertAlmostEqual(out["mean"], (0.1 + 0.3 + 0.5 + 0.7 - 0.1 + 0.1) / 6, places=12)

    def test_O21_interval_is_ordered_and_inside_the_data_range(self):
        diffs = twelve()
        values = [v for vs in diffs.values() for v in vs]
        out = self.boot(diffs)
        self.assertLessEqual(out["lo"], out["hi"])
        self.assertGreaterEqual(out["lo"], min(values) - 1e-12)
        self.assertLessEqual(out["hi"], max(values) + 1e-12)
        self.assertLess(out["lo"], out["hi"])

    def test_O21_constant_differences_collapse_the_interval(self):
        out = self.boot({"a": [0.25, 0.25], "b": [0.25, 0.25], "c": [0.25, 0.25]})
        for key in ("mean", "lo", "hi"):
            self.assertAlmostEqual(out[key], 0.25, places=12)

    def test_O21_more_resamples_do_not_change_n_counts(self):
        self.assertEqual(self.boot(twelve(), resamples=500)["n_tasks"], 12)

    def test_O21_metamorphic_cluster_order_permutation_invariance(self):
        diffs = twelve()
        base = self.boot(diffs)
        for order in itertools.islice(itertools.permutations(diffs), 6):
            permuted = {k: diffs[k] for k in order}
            got = self.boot(permuted)
            for key in ("mean", "lo", "hi"):
                self.assertAlmostEqual(got[key], base[key], delta=1e-9)
            self.assertEqual((got["n_tasks"], got["n_clusters"]), (base["n_tasks"], base["n_clusters"]))

    def test_O21_metamorphic_within_cluster_order_invariance(self):
        diffs = twelve()
        flipped = {k: list(reversed(v)) for k, v in diffs.items()}
        a, b = self.boot(diffs), self.boot(flipped)
        for key in ("mean", "lo", "hi"):
            self.assertAlmostEqual(a[key], b[key], delta=1e-9)

    def test_O21_metamorphic_constant_shift(self):
        diffs = twelve()
        base = self.boot(diffs)
        for c in (0.5, -0.2, 3.0):
            shifted = self.boot({k: [v + c for v in vs] for k, vs in diffs.items()})
            for key in ("mean", "lo", "hi"):
                self.assertAlmostEqual(shifted[key], base[key] + c, delta=1e-9)

    def test_O21_alpha_widens_interval(self):
        narrow = self.boot(twelve(), alpha=0.5)
        wide = self.boot(twelve(), alpha=0.05)
        self.assertGreaterEqual(narrow["lo"], wide["lo"])
        self.assertLessEqual(narrow["hi"], wide["hi"])
        self.assertGreater(wide["hi"] - wide["lo"], narrow["hi"] - narrow["lo"])


class Verdict(unittest.TestCase):
    def test_O21_C35_lo_exactly_zero_is_no_help(self):
        self.assertEqual(stats.verdict(ci(0.0, 0.4), RULE), "no_help")

    def test_O21_lo_just_above_zero_is_help(self):
        self.assertEqual(stats.verdict(ci(1e-12, 0.4), RULE), "help")

    def test_O21_hi_exactly_zero_is_no_help(self):
        self.assertEqual(stats.verdict(ci(-0.4, 0.0), RULE), "no_help")

    def test_O21_hi_just_below_zero_is_harmful(self):
        self.assertEqual(stats.verdict(ci(-0.4, -1e-12), RULE), "harmful")

    def test_O21_interval_spanning_zero_is_no_help(self):
        self.assertEqual(stats.verdict(ci(-0.1, 0.2), RULE), "no_help")

    def test_O21_C36_nine_tasks_is_insufficient_ten_is_not(self):
        self.assertEqual(stats.verdict(ci(0.1, 0.4, n_tasks=9), RULE), "insufficient")
        self.assertEqual(stats.verdict(ci(0.1, 0.4, n_tasks=10), RULE), "help")
        self.assertEqual(stats.verdict(ci(-0.4, -0.1, n_tasks=9), RULE), "insufficient")
        self.assertEqual(stats.verdict(ci(-0.4, -0.1, n_tasks=10), RULE), "harmful")
        self.assertEqual(stats.verdict(ci(-0.1, 0.1, n_tasks=9), RULE), "insufficient")

    def test_O21_zero_tasks_is_insufficient(self):
        self.assertEqual(stats.verdict(ci(0.0, 0.0, n_tasks=0), RULE), "insufficient")

    def test_O21_end_to_end_bootstrap_to_verdict(self):
        diffs = {"r%d" % i: [0.3, 0.35, 0.4] for i in range(4)}
        out = stats.cluster_bootstrap(diffs, resamples=1000, seed=1)
        self.assertEqual(stats.verdict(out, RULE), "help")
        neg = {"r%d" % i: [-0.3, -0.35, -0.4] for i in range(4)}
        self.assertEqual(stats.verdict(stats.cluster_bootstrap(neg, resamples=1000, seed=1), RULE), "harmful")
        few = {"r%d" % i: [0.3, 0.35] for i in range(4)}
        self.assertEqual(stats.verdict(stats.cluster_bootstrap(few, resamples=1000, seed=1), RULE), "insufficient")

    def test_O21_F14_guard_rule_upper_bound_boundary(self):
        guard = {"min_tasks": 10, "guard_upper": 0.10}
        self.assertEqual(stats.verdict(ci(-0.2, 0.10), guard), "ok")
        self.assertEqual(stats.verdict(ci(-0.2, 0.10 + 1e-9), guard), "harmful")
        self.assertEqual(stats.verdict(ci(-0.2, 0.09), guard), "ok")
        self.assertEqual(stats.verdict(ci(0.2, 0.5), guard), "harmful")

    def test_O21_F14_guard_rule_checks_insufficient_first(self):
        guard = {"min_tasks": 10, "guard_upper": 0.10}
        self.assertEqual(stats.verdict(ci(0.2, 0.9, n_tasks=9), guard), "insufficient")
        self.assertEqual(stats.verdict(ci(-0.2, 0.0, n_tasks=9), guard), "insufficient")
        self.assertEqual(stats.verdict(ci(-0.2, 0.0, n_tasks=10), guard), "ok")


if __name__ == "__main__":
    unittest.main()

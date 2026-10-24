import unittest

from evaluation.pr_test_quality import pilot
from evaluation.pr_test_quality.tests.fakes import spec_cfg

LANGS = ("python", "typescript", "go", "rust")


def t(language, repo, n, valid=True):
    owner, name = repo.split("/")
    return {"task_id": "%s__%s-%d" % (owner, name, n), "language": language, "repo": repo, "pr": n,
            "valid": valid, "pilot": False, "brief": {"status": "ok" if valid else "dropped"}}


def tasks_for(language, spec):
    """spec: repo -> (valid count, invalid count)"""
    rows = []
    for repo, (good, bad) in spec.items():
        rows += [t(language, repo, i + 1) for i in range(good)]
        rows += [t(language, repo, 100 + i, valid=False) for i in range(bad)]
    return rows


class Select(unittest.TestCase):
    def setUp(self):
        self.cfg = spec_cfg()

    def pick(self, by_language):
        return pilot.select(by_language, self.cfg)

    def of(self, picked, language):
        return [x for x in picked if x["language"] == language]

    def test_O22_two_repos_with_most_valid_tasks_up_to_two_tasks_each(self):
        spec = {"o/a": (1, 0), "o/b": (4, 0), "o/c": (3, 5), "o/d": (2, 0)}
        picked = self.of(self.pick({"python": tasks_for("python", spec)}), "python")
        counts = {}
        for x in picked:
            counts[x["repo"]] = counts.get(x["repo"], 0) + 1
        self.assertEqual(counts, {"o/b": 2, "o/c": 2})

    def test_O22_ties_are_broken_by_repo_name(self):
        spec = {"o/z": (2, 0), "o/m": (2, 0), "o/a": (2, 0), "o/q": (2, 0)}
        picked = self.of(self.pick({"python": tasks_for("python", spec)}), "python")
        self.assertEqual(sorted({x["repo"] for x in picked}), ["o/a", "o/m"])

    def test_O22_invalid_tasks_are_never_selected(self):
        spec = {"o/a": (1, 4), "o/b": (1, 0)}
        picked = self.of(self.pick({"python": tasks_for("python", spec)}), "python")
        self.assertTrue(all(x["valid"] for x in picked))
        self.assertEqual(len(picked), 2)

    def test_O22_fewer_than_two_repos_or_tasks_selects_what_exists(self):
        picked = self.of(self.pick({"go": tasks_for("go", {"o/a": (1, 0)})}), "go")
        self.assertEqual([x["task_id"] for x in picked], ["o__a-1"])

    def test_O22_h_runs_once_per_language_on_the_first_selected_task(self):
        by_language = {lang: tasks_for(lang, {"o/a": (2, 0), "o/b": (2, 0)}) for lang in LANGS}
        picked = self.pick(by_language)
        for lang in LANGS:
            rows = self.of(picked, lang)
            self.assertEqual(len(rows), 4)
            with_h = [x for x in rows if "H" in x["pilot_arms"]]
            self.assertEqual(len(with_h), 1)
            self.assertIs(with_h[0], rows[0])
            for x in rows:
                self.assertTrue({"B0", "Bplus"} <= set(x["pilot_arms"]))
                self.assertTrue(set(x["pilot_arms"]) <= {"B0", "Bplus", "H"})

    def test_O22_languages_are_selected_independently(self):
        by_language = {"python": tasks_for("python", {"o/a": (2, 0)}), "rust": tasks_for("rust", {"o/x": (1, 0)})}
        picked = self.pick(by_language)
        self.assertEqual({x["language"] for x in picked}, {"python", "rust"})
        self.assertEqual(len(self.of(picked, "python")), 2)
        self.assertEqual(len(self.of(picked, "rust")), 1)
        self.assertEqual(sum("H" in x["pilot_arms"] for x in picked), 2)


def metrics(**over):
    base = {
        "b0_resolved_rate": 0.5,
        "candidate_valid_rate": {lang: 0.8 for lang in LANGS},
        "judge_consistency": 0.9,
        "anchor_lowest_share": 0.2,
        "leak_fallbacks": 0,
        "token_hits": 0,
    }
    base.update(over)
    return base


class Gates(unittest.TestCase):
    def setUp(self):
        self.cfg = spec_cfg()

    def gate(self, name, **over):
        out = pilot.gates(metrics(**over), self.cfg)
        self.assertEqual(set(out), {"G1", "G2", "G3", "G4", "G5"})
        for g in out.values():
            self.assertTrue({"pass", "value", "threshold"} <= set(g))
        return out[name]

    def test_O22_all_good_passes_every_gate(self):
        out = pilot.gates(metrics(), self.cfg)
        self.assertTrue(all(g["pass"] for g in out.values()))

    def test_O22_G1_b0_resolved_rate_edge_at_point_eight(self):
        self.assertTrue(self.gate("G1", b0_resolved_rate=0.80)["pass"])
        self.assertTrue(self.gate("G1", b0_resolved_rate=0.79)["pass"])
        self.assertFalse(self.gate("G1", b0_resolved_rate=0.81)["pass"])
        self.assertEqual(self.gate("G1", b0_resolved_rate=0.81)["value"], 0.81)

    def test_O22_G2_each_language_needs_half_of_candidates(self):
        good = {lang: 0.5 for lang in LANGS}
        self.assertTrue(self.gate("G2", candidate_valid_rate=good)["pass"])
        for lang in LANGS:
            bad = dict(good, **{lang: 0.49})
            with self.subTest(lang=lang):
                self.assertFalse(self.gate("G2", candidate_valid_rate=bad)["pass"])

    def test_O22_G3_judge_consistency_edge_at_point_seven(self):
        self.assertTrue(self.gate("G3", judge_consistency=0.70)["pass"])
        self.assertFalse(self.gate("G3", judge_consistency=0.69)["pass"])
        self.assertTrue(self.gate("G3", judge_consistency=0.71)["pass"])

    def test_O22_F13_G4_anchor_lowest_share_at_most_half(self):
        self.assertTrue(self.gate("G4", anchor_lowest_share=0.50)["pass"])
        self.assertTrue(self.gate("G4", anchor_lowest_share=0.49)["pass"])
        self.assertFalse(self.gate("G4", anchor_lowest_share=0.51)["pass"])

    def test_O22_G5_requires_zero_leak_fallbacks_and_zero_tokens(self):
        self.assertTrue(self.gate("G5", leak_fallbacks=0, token_hits=0)["pass"])
        self.assertFalse(self.gate("G5", leak_fallbacks=1)["pass"])
        self.assertFalse(self.gate("G5", token_hits=1)["pass"])
        self.assertFalse(self.gate("G5", leak_fallbacks=1, token_hits=1)["pass"])

    def test_O22_one_failing_gate_does_not_fail_the_others(self):
        out = pilot.gates(metrics(judge_consistency=0.1), self.cfg)
        self.assertEqual([g for g, v in out.items() if not v["pass"]], ["G3"])

    def test_O22_F13_missing_metric_fails_its_gate_with_null_value(self):
        for key, gate in (("b0_resolved_rate", "G1"), ("candidate_valid_rate", "G2"), ("judge_consistency", "G3"),
                          ("anchor_lowest_share", "G4")):
            m = metrics()
            del m[key]
            out = pilot.gates(m, self.cfg)
            with self.subTest(metric=key):
                self.assertFalse(out[gate]["pass"])
                self.assertIsNone(out[gate]["value"])
                self.assertEqual([g for g, v in out.items() if not v["pass"]], [gate])

    def test_O22_F13_thresholds_come_from_cfg_gates(self):
        cfg = spec_cfg(gates={"g1_max_b0_resolved": 0.6, "g3_min_consistency": 0.9})
        out = pilot.gates(metrics(b0_resolved_rate=0.7, judge_consistency=0.85), cfg)
        self.assertFalse(out["G1"]["pass"])
        self.assertFalse(out["G3"]["pass"])


if __name__ == "__main__":
    unittest.main()

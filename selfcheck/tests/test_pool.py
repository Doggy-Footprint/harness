import random
import unittest

from swebench.harness.constants import USE_X86

from selfcheck import pool

X86_ID = sorted(USE_X86)[0]
DIFFS = ["15 min - 1 hour", "1-4 hours"]


def make_patch(hunks):
    text = "diff --git a/f.py b/f.py\n--- a/f.py\n+++ b/f.py\n"
    for i in range(hunks):
        start = 10 * i + 1
        text += "@@ -%d,1 +%d,1 @@\n-a%d\n+b%d\n" % (start, start, i, i)
    return text


def row(instance_id, repo="x/x", difficulty="15 min - 1 hour", hunks=2):
    return {"instance_id": instance_id, "repo": repo, "difficulty": difficulty, "patch": make_patch(hunks)}


def kwargs(rows, **extra):
    base = {"swt_ids": {r["instance_id"] for r in rows}, "difficulties": DIFFS, "min_hunks": 2}
    base.update(extra)
    return base


class CountHunksTests(unittest.TestCase):
    def test_vo3_d3_counts_hunk_headers(self):
        self.assertEqual(pool.count_hunks(""), 0)
        self.assertEqual(pool.count_hunks(make_patch(1)), 1)
        self.assertEqual(pool.count_hunks(make_patch(4)), 4)

    def test_vo3_d3_counts_across_files(self):
        self.assertEqual(pool.count_hunks(make_patch(2) + make_patch(3)), 5)

    def test_vo3_d3_content_lines_containing_at_signs_are_not_hunks(self):
        patch = make_patch(2) + "+x = '@@ -1 +1 @@'\n y @@ z\n"
        self.assertEqual(pool.count_hunks(patch), 2)


class EligibleTests(unittest.TestCase):
    def check(self, candidate, **overrides):
        args = kwargs([candidate])
        args.update(overrides)
        return pool.eligible(candidate, **args)

    def test_vo3_d2_all_conditions_true(self):
        self.assertTrue(self.check(row("zz__zz-1")))

    def test_vo3_d1_not_in_swt_ids(self):
        self.assertFalse(self.check(row("zz__zz-1"), swt_ids={"other__other-1"}))

    def test_vo3_d1_difficulty_not_listed(self):
        self.assertFalse(self.check(row("zz__zz-1", difficulty="<15 min fix")))
        self.assertTrue(self.check(row("zz__zz-1", difficulty="1-4 hours")))

    def test_vo3_d1_too_few_hunks(self):
        self.assertFalse(self.check(row("zz__zz-1", hunks=1)))

    def test_vo3_d1_id_in_use_x86(self):
        candidate = row(X86_ID)
        self.assertFalse(pool.eligible(candidate, **kwargs([candidate])))
        self.assertTrue(pool.eligible(row("zz__zz-1"), **kwargs([row("zz__zz-1")])))

    def test_vo3_d1_id_in_excluded_ids(self):
        self.assertFalse(self.check(row("zz__zz-1"), excluded_ids={"zz__zz-1"}))
        self.assertTrue(self.check(row("zz__zz-1"), excluded_ids={"zz__zz-2"}))

    def test_vo3_d3_hunk_boundary_around_min_hunks(self):
        for min_hunks in (1, 2, 3):
            with self.subTest(min_hunks=min_hunks):
                below = row("zz__zz-1", hunks=min_hunks - 1)
                at = row("zz__zz-1", hunks=min_hunks)
                above = row("zz__zz-1", hunks=min_hunks + 1)
                self.assertFalse(self.check(below, min_hunks=min_hunks))
                self.assertTrue(self.check(at, min_hunks=min_hunks))
                self.assertTrue(self.check(above, min_hunks=min_hunks))

    def test_vo3_c4_boundary_rows(self):
        self.assertFalse(self.check(row("zz__zz-1", hunks=1, difficulty="<15 min fix")))
        self.assertFalse(self.check(row("zz__zz-1", hunks=2, difficulty="<15 min fix")))
        self.assertTrue(self.check(row("zz__zz-1", hunks=2, difficulty="15 min - 1 hour")))


def reference_rank(rows, seed):
    repos = sorted({r["repo"] for r in rows})
    random.Random(seed).shuffle(repos)
    per_repo = {}
    for repo in repos:
        ids = sorted(r["instance_id"] for r in rows if r["repo"] == repo)
        random.Random("%s:%s" % (seed, repo)).shuffle(ids)
        per_repo[repo] = ids
    order = []
    depth = 0
    while any(depth < len(ids) for ids in per_repo.values()):
        for repo in repos:
            if depth < len(per_repo[repo]):
                order.append(per_repo[repo][depth])
        depth += 1
    return order


def big_rows():
    rows = []
    for repo_index, repo in enumerate(["r0/a", "r1/b", "r2/c", "r3/d", "r4/e", "r5/f"]):
        for n in range(1 + repo_index % 4 + 2):
            rows.append(row("%s__%s-%d" % (repo.split("/")[0], repo.split("/")[1], n), repo=repo))
    return rows


class RankCandidatesTests(unittest.TestCase):
    def ids(self, rows, seed=1, **extra):
        args = kwargs(rows, seed=seed, **extra)
        return [r["instance_id"] for r in pool.rank_candidates(rows, **args)]

    def test_vo3_r3_round_robin_with_unequal_repo_sizes_seed_1(self):
        rows = [
            row("a__a-1", repo="a/a"), row("a__a-2", repo="a/a"), row("a__a-3", repo="a/a"),
            row("b__b-1", repo="b/b"),
            row("c__c-1", repo="c/c"), row("c__c-2", repo="c/c"),
        ]
        self.assertEqual(
            self.ids(rows, seed=1),
            ["b__b-1", "c__c-2", "a__a-3", "c__c-1", "a__a-2", "a__a-1"],
        )

    def test_vo3_r3_round_robin_with_unequal_repo_sizes_seed_7(self):
        rows = [
            row("a__a-1", repo="a/a"), row("a__a-2", repo="a/a"), row("a__a-3", repo="a/a"),
            row("b__b-1", repo="b/b"),
            row("c__c-1", repo="c/c"), row("c__c-2", repo="c/c"),
        ]
        self.assertEqual(
            self.ids(rows, seed=7),
            ["c__c-2", "a__a-2", "b__b-1", "c__c-1", "a__a-3", "a__a-1"],
        )

    def test_vo3_r3_matches_specified_algorithm_for_many_seeds(self):
        rows = big_rows()
        for seed in range(0, 12):
            with self.subTest(seed=seed):
                self.assertEqual(self.ids(rows, seed=seed), reference_rank(rows, seed))

    def test_vo3_r3_first_pass_takes_one_row_from_each_repo(self):
        rows = big_rows()
        ranked = pool.rank_candidates(rows, **kwargs(rows, seed=3))
        repos = {r["repo"] for r in rows}
        self.assertEqual({r["repo"] for r in ranked[: len(repos)]}, repos)
        self.assertEqual(len(ranked[: len(repos)]), len(repos))

    def test_vo3_r3_returns_the_row_objects_unchanged(self):
        rows = big_rows()
        ranked = pool.rank_candidates(rows, **kwargs(rows, seed=3))
        by_id = {r["instance_id"]: r for r in rows}
        self.assertEqual(len(ranked), len(rows))
        for item in ranked:
            self.assertEqual(item, by_id[item["instance_id"]])

    def test_vo3_r1_input_order_does_not_change_ranking(self):
        rows = big_rows()
        expected = self.ids(rows, seed=1)
        orders = [list(reversed(rows)), rows[3:] + rows[:3]]
        for shuffle_seed in range(4):
            shuffled = list(rows)
            random.Random(shuffle_seed).shuffle(shuffled)
            orders.append(shuffled)
        for index, permuted in enumerate(orders):
            with self.subTest(permutation=index):
                self.assertNotEqual([r["instance_id"] for r in permuted], [r["instance_id"] for r in rows])
                self.assertEqual(self.ids(permuted, seed=1), expected)

    def test_vo3_r2_seed_changes_the_order(self):
        rows = big_rows()
        orders = {tuple(self.ids(rows, seed=seed)) for seed in (1, 2, 3, 4, 5)}
        self.assertGreater(len(orders), 1)

    def test_vo3_c5_ineligible_rows_are_filtered_out(self):
        rows = big_rows()
        extras = [
            row("r0__a-low", repo="r0/a", hunks=1),
            row("r1__b-easy", repo="r1/b", difficulty="<15 min fix"),
            row(X86_ID, repo="r2/c"),
            row("r3__d-skip", repo="r3/d"),
            row("r4__e-excluded", repo="r4/e"),
        ]
        everything = rows + extras
        swt_ids = {r["instance_id"] for r in everything if r["instance_id"] != "r3__d-skip"}
        args = kwargs(rows, seed=1, excluded_ids={"r4__e-excluded"}, swt_ids=swt_ids)
        ranked = pool.rank_candidates(everything, **args)
        self.assertEqual([r["instance_id"] for r in ranked], reference_rank(rows, 1))


class BuildPoolTests(unittest.TestCase):
    def setUp(self):
        self.ranked = [row("p__p-%d" % n, repo="r/%d" % n) for n in range(8)]
        self.calls = []

    def validator(self, invalid):
        def validate(candidate):
            self.calls.append(candidate["instance_id"])
            return {"valid": candidate["instance_id"] not in invalid}
        return validate

    def test_vo3_b1_invalid_candidates_are_skipped(self):
        kept = pool.build_pool(self.ranked, size=3, validate_fn=self.validator({"p__p-1", "p__p-3"}))
        self.assertEqual([r["instance_id"] for r in kept], ["p__p-0", "p__p-2", "p__p-4"])

    def test_vo3_b2_validate_not_called_after_size_reached(self):
        pool.build_pool(self.ranked, size=3, validate_fn=self.validator({"p__p-1", "p__p-3"}))
        self.assertEqual(self.calls, ["p__p-0", "p__p-1", "p__p-2", "p__p-3", "p__p-4"])

    def test_vo3_b3_fewer_valid_than_size_returns_the_valid_subset(self):
        invalid = {"p__p-%d" % n for n in (0, 2, 3, 4, 5, 6)}
        kept = pool.build_pool(self.ranked, size=5, validate_fn=self.validator(invalid))
        self.assertEqual([r["instance_id"] for r in kept], ["p__p-1", "p__p-7"])
        self.assertEqual(self.calls, ["p__p-%d" % n for n in range(8)])

    def test_vo3_b4_first_three_kept_rows_are_core(self):
        kept = pool.build_pool(self.ranked, size=5, validate_fn=self.validator({"p__p-1"}))
        self.assertEqual([r["instance_id"] for r in kept], ["p__p-0", "p__p-2", "p__p-3", "p__p-4", "p__p-5"])
        self.assertEqual([r["core"] for r in kept], [True, True, True, False, False])

    def test_vo3_b4_kept_rows_keep_their_fields(self):
        kept = pool.build_pool(self.ranked, size=2, validate_fn=self.validator(set()))
        by_id = {r["instance_id"]: r for r in self.ranked}
        for item in kept:
            self.assertEqual({k: v for k, v in item.items() if k != "core"}, by_id[item["instance_id"]])

    def test_vo3_b4_fewer_than_three_kept_are_all_core(self):
        kept = pool.build_pool(self.ranked, size=2, validate_fn=self.validator(set()))
        self.assertEqual([r["core"] for r in kept], [True, True])

    def test_vo3_c6_validate_fn_receives_each_candidate_row(self):
        seen = []

        def validate(candidate):
            seen.append(candidate["instance_id"])
            return {"valid": True, "extra": 1}

        pool.build_pool(self.ranked, size=2, validate_fn=validate)
        self.assertEqual(seen, ["p__p-0", "p__p-1"])


if __name__ == "__main__":
    unittest.main()

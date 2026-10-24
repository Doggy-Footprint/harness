import json
import random
import re
import unittest

from evaluation.pr_test_quality import mutants


def m(i, path="src/a.py", line=1):
    return {"id": "%016x" % i, "path": path, "line": line, "diff": "d%d" % i}


STRYKER = {"schemaVersion": "1", "files": {"src/a.ts": {"language": "typescript",
           "source": "export function f(a) {\n  return a + 1;\n}\n", "mutants": [
               {"id": "1", "mutatorName": "ArithmeticOperator", "replacement": "a - 1",
                "location": {"start": {"line": 2, "column": 10}, "end": {"line": 2, "column": 15}}, "status": "Survived"},
               {"id": "2", "mutatorName": "ArithmeticOperator", "replacement": "a * 1",
                "location": {"start": {"line": 2, "column": 10}, "end": {"line": 2, "column": 15}}, "status": "Killed"}]}}}
MUTMUT = """--- src/calc/ops.py
+++ src/calc/ops.py
@@ -5,2 +5,2 @@
 def clamp(value, lo, hi):
-    return max(lo, min(value, hi))
+    return min(lo, min(value, hi))
--- src/calc/ops.py
+++ src/calc/ops.py
@@ -5,2 +5,2 @@
 def clamp(value, lo, hi):
-    return max(lo, min(value, hi))
+    return max(lo, max(value, hi))
"""
CARGO = [{"package": "p", "file": "src/lib.rs", "function": {"function_name": "clamp", "return_type": "-> i32",
          "span": {"start": {"line": 3, "column": 1}, "end": {"line": 5, "column": 2}}},
          "span": {"start": {"line": 4, "column": 5}, "end": {"line": 4, "column": 20}}, "replacement": "0",
          "genre": "FnValue"}]


class Tools(unittest.TestCase):
    def test_tools_table(self):
        self.assertEqual(mutants.TOOLS, {"python": "mutmut", "typescript": "stryker", "go": "go-mutesting",
                                         "rust": "cargo-mutants"})


class Normalize(unittest.TestCase):
    def check_shape(self, items):
        for item in items:
            self.assertEqual(set(item), {"id", "path", "line", "diff"})
            self.assertRegex(item["id"], r"^[0-9a-f]{16}$")
            self.assertIsInstance(item["line"], int)
        self.assertEqual(len({i["id"] for i in items}), len(items))

    def test_O16_stryker_mutants_become_diffs_on_their_line(self):
        items = mutants.normalize("stryker", json.dumps(STRYKER))
        self.check_shape(items)
        self.assertEqual({(i["path"], i["line"]) for i in items}, {("src/a.ts", 2)})
        added = {ln for i in items for ln in i["diff"].splitlines() if ln.startswith("+") and not ln.startswith("+++")}
        removed = {ln for i in items for ln in i["diff"].splitlines() if ln.startswith("-") and not ln.startswith("---")}
        self.assertEqual(added, {"+  return a - 1;", "+  return a * 1;"})
        self.assertEqual(removed, {"-  return a + 1;"})

    def test_O16_mutmut_text_is_split_into_one_mutant_per_diff(self):
        items = mutants.normalize("mutmut", MUTMUT)
        self.check_shape(items)
        self.assertEqual(len(items), 2)
        self.assertEqual({(i["path"], i["line"]) for i in items}, {("src/calc/ops.py", 5 + 1)})
        self.assertIn("min(lo, min", items[0]["diff"] + items[1]["diff"])
        self.assertIn("max(lo, max", items[0]["diff"] + items[1]["diff"])

    def test_O16_cargo_mutants_json(self):
        items = mutants.normalize("cargo-mutants", json.dumps(CARGO))
        self.check_shape(items)
        self.assertEqual([(i["path"], i["line"]) for i in items], [("src/lib.rs", 4)])

    def test_O16_ids_are_stable_and_content_addressed(self):
        a = mutants.normalize("stryker", json.dumps(STRYKER))
        b = mutants.normalize("stryker", json.dumps(STRYKER))
        self.assertEqual(a, b)
        other = json.loads(json.dumps(STRYKER))
        other["files"]["src/a.ts"]["mutants"][0]["replacement"] = "a / 1"
        c = mutants.normalize("stryker", json.dumps(other))
        self.assertEqual(len({i["id"] for i in a + c}), 3)

    def test_O16_empty_reports_give_no_mutants(self):
        for tool in mutants.TOOLS.values():
            self.assertEqual(mutants.normalize(tool, "{}"), [], tool)
        self.assertEqual(mutants.normalize("mutmut", ""), [])
        self.assertEqual(mutants.normalize("go-mutesting", ""), [])


class Restrict(unittest.TestCase):
    def test_O16_keeps_only_mutants_on_changed_lines_of_their_path(self):
        items = [m(1, "a.py", 2), m(2, "a.py", 3), m(3, "b.py", 2), m(4, "a.py", 9)]
        got = mutants.restrict(items, {"a.py": {2, 9}, "c.py": {3}})
        self.assertEqual([x["id"] for x in got], [items[0]["id"], items[3]["id"]])

    def test_O16_no_changed_lines_keeps_nothing(self):
        self.assertEqual(mutants.restrict([m(1)], {}), [])
        self.assertEqual(mutants.restrict([m(1)], {"src/a.py": set()}), [])


class Sample(unittest.TestCase):
    def setUp(self):
        self.items = [m(i) for i in range(40)]

    def test_O16_cap_at_or_above_size_returns_everything_sorted_by_id(self):
        shuffled = self.items[:]
        random.Random(5).shuffle(shuffled)
        for cap in (40, 100):
            got = mutants.sample(shuffled, cap, 1)
            self.assertEqual([x["id"] for x in got], sorted(x["id"] for x in self.items))

    def test_O16_sample_has_cap_distinct_members_from_the_input(self):
        got = mutants.sample(self.items, 10, 1)
        self.assertEqual(len(got), 10)
        self.assertEqual(len({x["id"] for x in got}), 10)
        self.assertTrue({x["id"] for x in got} <= {x["id"] for x in self.items})

    def test_O16_sample_is_deterministic_per_seed_and_input_order_independent(self):
        shuffled = self.items[:]
        random.Random(9).shuffle(shuffled)
        a = mutants.sample(self.items, 10, 1)
        self.assertEqual(a, mutants.sample(self.items, 10, 1))
        self.assertEqual({x["id"] for x in a}, {x["id"] for x in mutants.sample(shuffled, 10, 1)})

    def test_O16_different_seeds_give_different_samples(self):
        seen = {tuple(sorted(x["id"] for x in mutants.sample(self.items, 10, seed))) for seed in range(8)}
        self.assertGreater(len(seen), 1)

    def test_O16_empty_input(self):
        self.assertEqual(mutants.sample([], 5, 1), [])


if __name__ == "__main__":
    unittest.main()

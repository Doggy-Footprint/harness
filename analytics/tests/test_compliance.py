import unittest

from analytics.compliance import evaluate


def event(name, **fields):
    return {"event": name, "workflow_run_id": "run-1", "contract": "sample", **fields}


def compliant_events():
    return [
        event("workflow_start", contract_version=1),
        event("workflow_phase", phase="implement_test"),
        event("workflow_phase", phase="verify"),
        event("verifier_result", round=1, result="pass", findings=0, seeds_run=0, seeds_detected=0),
        event("workflow_end", status="complete"),
    ]


class ComplianceTests(unittest.TestCase):
    """Contract v3: U2; A1/A9; V3."""

    def test_v3_completed_ordered_run_is_compliant(self):
        result = evaluate(compliant_events())
        self.assertTrue(result["completed"])
        self.assertTrue(result["compliant"])
        self.assertEqual(result["reasons"], [])

    def test_v3_incomplete_run_is_not_classified_as_completed(self):
        result = evaluate(compliant_events()[:-1])
        self.assertFalse(result["completed"])
        self.assertIsNone(result["compliant"])

    def test_v3_invalid_completed_transition_variants_are_noncompliant(self):
        valid = compliant_events()
        variants = {
            "missing": valid[:2] + valid[3:],
            "duplicate": valid[:2] + [valid[1]] + valid[2:],
            "out_of_order": [valid[0], valid[2], valid[1], *valid[3:]],
            "mismatched_identity": [*valid[:2], {**valid[2], "workflow_run_id": "other"}, *valid[3:]],
            "post_end": [*valid, event("workflow_phase", phase="amend")],
        }
        for name, events in variants.items():
            with self.subTest(variant=name):
                first = evaluate(events)
                second = evaluate(events)
                self.assertTrue(first["completed"])
                self.assertFalse(first["compliant"])
                self.assertTrue(first["reasons"])
                self.assertEqual(first["reasons"], second["reasons"])


if __name__ == "__main__":
    unittest.main()

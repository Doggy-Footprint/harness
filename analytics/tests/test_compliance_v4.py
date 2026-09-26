import unittest

from analytics.compliance import evaluate


def event(name, **fields):
    return {"event": name, "workflow_run_id": "run-1", "spec": "analytics", "spec_version": 1, **fields}


def start():
    return event("workflow_start")


def phase(name):
    return event("workflow_phase", phase=name)


def result(round_, outcome, findings=0):
    return event("verifier_result", round=round_, result=outcome, findings=findings, seeds_run=1, seeds_detected=1)


def end(status="complete"):
    return event("workflow_end", status=status)


class ComplianceV4Tests(unittest.TestCase):
    """Independent oracle for spec v4 VO1 (F1, C1-C4): amend is a violation only
    while a verify awaits its verifier_result; the F1 rename gives that
    violation the reason `amend_during_verify`. Each subTest below is an
    ISO/IEC/IEEE 29119-4 state-transition case: one required amend-state
    (before implement_test, after implement_test with no result pending,
    awaiting a verifier_result, after a retry, after a pass) plus the exact
    C4 handoff-shaped sequence."""

    def test_c2_amend_before_implement_test_is_accepted(self):
        """State: before implement_test. Exact Case C2 sequence."""
        events = [start(), phase("amend"), phase("implement_test"), phase("verify"),
                  result(1, "pass"), end()]
        self.assertEqual(evaluate(events), {"completed": True, "compliant": True, "reasons": []})

    def test_c1_amend_after_implement_test_with_no_pending_result_is_accepted(self):
        """State: after implement_test, no verifier_result pending. Exact Case C1 sequence."""
        events = [start(), phase("implement_test"), phase("amend"), phase("verify"),
                  result(1, "pass"), end()]
        self.assertEqual(evaluate(events), {"completed": True, "compliant": True, "reasons": []})

    def test_c3_amend_while_awaiting_a_verifier_result_is_the_only_violation(self):
        """State: awaiting result (amend emitted after verify, before its
        verifier_result arrives). Exact Case C3 sequence; the F1 rename means
        the violation reason is `amend_during_verify`, not the old
        `amend_without_retry_result`."""
        events = [start(), phase("implement_test"), phase("verify"), phase("amend"),
                  result(1, "pass"), end()]
        outcome = evaluate(events)
        self.assertTrue(outcome["completed"])
        self.assertFalse(outcome["compliant"])
        self.assertIn("amend_during_verify", outcome["reasons"])
        self.assertNotIn("amend_without_retry_result", outcome["reasons"])

    def test_amend_after_a_retry_result_is_accepted(self):
        """State: after retry. A correction cycle amend that follows a retry
        result (the result is no longer pending) is accepted."""
        events = [start(), phase("implement_test"), phase("verify"), result(1, "retry", findings=1),
                  phase("amend"), phase("verify"), result(2, "pass"), end()]
        self.assertEqual(evaluate(events), {"completed": True, "compliant": True, "reasons": []})

    def test_amend_after_a_pass_result_is_accepted(self):
        """State: after pass. F1 explicitly names 'after a pass' as accepted;
        this exercises a further correction cycle started once a verifier
        has already passed."""
        events = [start(), phase("implement_test"), phase("verify"), result(1, "pass"),
                  phase("amend"), phase("verify"), result(2, "pass"), end()]
        self.assertEqual(evaluate(events), {"completed": True, "compliant": True, "reasons": []})

    def test_c4_handoff_2106fd306d5f_shape_is_compliant(self):
        """Exact Case C4 sequence (handoff 2106fd306d5f shape): two consecutive
        amends before the first verify, then a retry/amend/verify/pass cycle."""
        events = [
            start(), phase("implement_test"), phase("amend"), phase("amend"),
            phase("verify"), result(1, "retry", findings=1), phase("amend"),
            phase("verify"), result(2, "pass"), end(),
        ]
        self.assertEqual(evaluate(events), {"completed": True, "compliant": True, "reasons": []})


if __name__ == "__main__":
    unittest.main()

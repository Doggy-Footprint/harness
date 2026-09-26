import unittest

from analytics.compliance import evaluate


def event(name, **fields):
    return {"event": name, "workflow_run_id": "run-1", "spec": "analytics", "spec_version": 1, **fields}


def passing_events():
    return [
        event("workflow_start"),
        event("workflow_phase", phase="implement_test"),
        event("workflow_phase", phase="verify"),
        event("verifier_result", round=1, result="pass", findings=0, seeds_run=1, seeds_detected=1),
        event("workflow_end", status="complete"),
    ]


class ComplianceV3Tests(unittest.TestCase):
    """Independent oracle for spec v3 VO2 (FR5): compliance ignores any event
    outside {workflow_start, workflow_phase, verifier_result, workflow_end},
    regardless of where in the stream it appears."""

    IGNORED_EVENTS = ("subagent_start", "subagent_stop", "seed", "test_command")

    def baseline(self):
        return evaluate(passing_events())

    def test_ignored_event_types_mid_run_do_not_change_the_outcome(self):
        expected = self.baseline()
        for name in self.IGNORED_EVENTS:
            with self.subTest(position="mid_run", event=name):
                events = passing_events()
                events = events[:2] + [event(name, agent_type="general-purpose", seeds_run=99)] + events[2:]
                self.assertEqual(evaluate(events), expected)

    def test_ignored_event_types_immediately_before_end_do_not_change_the_outcome(self):
        expected = self.baseline()
        for name in self.IGNORED_EVENTS:
            with self.subTest(position="end_before", event=name):
                events = passing_events()
                events = events[:-1] + [event(name, agent_type="general-purpose", seeds_run=99)] + events[-1:]
                self.assertEqual(evaluate(events), expected)


if __name__ == "__main__":
    unittest.main()

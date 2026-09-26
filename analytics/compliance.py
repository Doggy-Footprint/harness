_WORKFLOW_EVENTS = {"workflow_start", "workflow_phase", "verifier_result", "workflow_end"}


def evaluate(events: list[dict]) -> dict:
    events = [event for event in events if event.get("event") in _WORKFLOW_EVENTS]
    reasons: list[str] = []
    if not events:
        return {"completed": False, "compliant": None, "reasons": []}

    run_id = events[0].get("workflow_run_id")
    spec = events[0].get("spec")
    ended = False
    implemented = False
    awaiting_result = False
    last_result = None
    implement_count = 0
    verify_count = 0
    terminal_status = None

    for index, item in enumerate(events):
        name = item.get("event")
        if item.get("workflow_run_id") != run_id or item.get("spec") != spec:
            reasons.append("identity_mismatch")
        if ended:
            reasons.append("post_end_event")
            continue
        if name == "workflow_start":
            if index != 0:
                reasons.append("expected_one_start")
        elif name == "workflow_phase":
            phase = item.get("phase")
            if phase == "implement_test":
                implement_count += 1
                if implement_count > 1:
                    reasons.append("duplicate_implement_test")
                implemented = True
            elif phase == "verify":
                verify_count += 1
                if not implemented:
                    reasons.append("implement_test_before_verify")
                if awaiting_result:
                    reasons.append("verify_without_prior_result")
                awaiting_result = True
            elif phase == "amend":
                if last_result != "retry" or awaiting_result:
                    reasons.append("amend_without_retry_result")
            else:
                reasons.append("unknown_phase")
        elif name == "verifier_result":
            if not awaiting_result:
                reasons.append("verifier_result_without_verify")
            awaiting_result = False
            last_result = item.get("result")
        elif name == "workflow_end":
            terminal_status = item.get("status")
            ended = True
        else:
            reasons.append("unknown_event")

    if events[0].get("event") != "workflow_start" or sum(
        item.get("event") == "workflow_start" for item in events
    ) != 1:
        reasons.append("expected_one_start")
    if terminal_status in {"complete", "limit"}:
        if not implemented or verify_count == 0:
            reasons.append("missing_implement_or_verify")
        if awaiting_result:
            reasons.append("missing_verifier_result")
    if terminal_status == "complete" and last_result != "pass":
        reasons.append("completion_requires_passing_verifier_result")
    if terminal_status == "limit" and last_result != "limit":
        reasons.append("limit_requires_limiting_verifier_result")
    if terminal_status not in {None, "complete", "limit", "handoff", "aborted"}:
        reasons.append("invalid_terminal_status")

    unique = sorted(set(reasons))
    if terminal_status is None:
        return {"completed": False, "compliant": None, "reasons": unique}
    return {"completed": True, "compliant": not unique, "reasons": unique}

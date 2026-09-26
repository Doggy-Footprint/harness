File: 27a9437461f8be3e-telemetry-markers.md
Summary: Telemetry marker hooks v4 pass 108 tests; new Codex session must verify Bash PostToolUse after matcher install
Related Files: harness/lib/telemetry.py, harness/lib/hook_shared.py, harness/hooks/telemetry_hook.py, harness/hooks/contract_gate.py, harness/hooks/hooks.spec.json, tests/test_telemetry.py
Related Symbols: emit, telemetry_file, handle_bash, handle_post_tool_use_failure, iter_test_commands
---
File: 286944a68391e237-verification-loop-improvements.md
Summary: General workflow changes to complete verifier audits before one routed, batched correction cycle
Related Files: harness/skills/contract-workflow/SKILL.md, harness/agents/test-implementer.md, harness/agents/test-verifier.md, harness/agents/implementer.md, tests/test_installer.py
Related Symbols: Verification Obligations, coverage map, finding ledger, correction batch
---
File: 09494007ed793b66-analytics-compliance-rules.md
Summary: Completed runs show noncompliant because amend rule is stricter than the skill and a ;-chained marker duplicated start; fixes await user decision
Related Files: analytics/compliance.py, harness/skills/workflow-approach/SKILL.md, harness/bin/workflow_marker.py, harness/lib/telemetry.py
Related Symbols: evaluate, amend_without_retry_result, expected_one_start, workflow_start

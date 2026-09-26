# Stale Index Archive
<!-- harness:stale-index-archive -->

File: 9f1e2d3c4b5a6071-stale-index-migration.md
Summary: Handoff after the migration test oracle needs a lowercase announcement-prefix correction.
Related Files: installer/harness.py, tests/test_installer.py, agent-docs/contracts/stale-index-migration.md
Related Symbols: migrate_stale_records, migrate_stale_index_logs, run_migrations
---
File: 577b7fd263444d02-analytics-dashboard.md
Summary: Marker v3 passes 132 tests; final audit leaves F7-F9 and F11-F12 as known gaps before analytics implementation
Related Files: harness/lib/telemetry.py, harness/bin/workflow_marker.py, harness/skills/contract-workflow/SKILL.md, installer/harness.py, tests/test_workflow_markers.py
Related Symbols: active_workflow, emit, workflow_start, workflow_phase, verifier_result, workflow_end
---
---
File: 8c41e2a7d905bf63-analytics-dashboard-test-oracle.md
Summary: Analytics implementation is unstarted; contract v5 and independent tests exist, with no analytics verifier run yet
Related Files: analytics/tests/test_api.py, analytics/tests/test_compliance.py, analytics/tests/test_importer.py, analytics/tests/test_pricing.py, analytics/frontend/src/App.test.jsx
Related Symbols: create_app, import_pending, transcript_usage, calculate_cost, evaluate, App
---
File: 5be48b0b11e837d4-analytics-dashboard-final-verification.md
Summary: Analytics implementation and tests are present but unverified; lockfile, full suite, verifier, and mutations remain after 2/2 corrections
Related Files: agent-docs/specs/7176826b00d34cc7-analytics-dashboard.md, analytics/app.py, analytics/importer.py, analytics/compliance.py, analytics/tests/test_api.py, analytics/tests/test_server.py
Related Symbols: create_app, import_pending, transcript_usage, evaluate, App
---
File: 49e8d44acdf07bd5-iso-29119-4-test-coverage.md
Summary: Rewrite workflow-approach, requirement-oracle and test agents so obligations declare 29119-4 techniques, coverage items and targets; add 0.10.0 migration
Related Files: harness/skills/workflow-approach/SKILL.md, harness/skills/requirement-oracle/SKILL.md, harness/agents/test-implementer.md, harness/agents/test-verifier.md, harness/VERSION, installer/harness.py, tests/test_installer.py, tests/test_telemetry.py, tests/test_workflow_markers.py
Related Symbols: Verification Obligations, migrate_verification_scope, MIGRATIONS, REQUIRED_HEADINGS
---
File: 09494007ed793b66-analytics-compliance-rules.md
Summary: Completed runs show noncompliant because amend rule is stricter than the skill and a ;-chained marker duplicated start; fixes await user decision
Related Files: analytics/compliance.py, harness/skills/workflow-approach/SKILL.md, harness/bin/workflow_marker.py, harness/lib/telemetry.py
Related Symbols: evaluate, amend_without_retry_result, expected_one_start, workflow_start

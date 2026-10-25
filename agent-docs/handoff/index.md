File: ea9e5b18dd5975cb-dashboard-skill-partial-use.md
Summary: From issue #7, dashboard partial-use classification should also count harness Skill invocations; not started
Related Files: analytics/app.py, analytics/transcripts.py, analytics/usage.py
Related Symbols: _classify_sessions, _has_harness_evidence, _collect_turn
---
File: 7c41e9b2d05af386-test-implementer-isolation-violation.md
Summary: Main's dispatch told test-implementer to run tests in 3/3 pilot runs; dispatch wording fixed in 0.31.0; hook blocking, analytics harness-hacking detection, classifier, worktree isolation remain
Related Files: harness/skills/workflow-approach/SKILL.md, harness/agents/test-implementer.md, harness/hooks/spec_gate.py, installer/harness.py, analytics/transcripts.py, analytics/app.py
Related Symbols: on_pre_tool_use, GATED_AGENTS, migrate_test_implementer_dispatch, _parse_claude

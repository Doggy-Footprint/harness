File: ea9e5b18dd5975cb-dashboard-skill-partial-use.md
Summary: From issue #7, dashboard partial-use classification should also count harness Skill invocations; not started
Related Files: analytics/app.py, analytics/transcripts.py, analytics/usage.py
Related Symbols: _classify_sessions, _has_harness_evidence, _collect_turn
---
File: 7c41e9b2d05af386-test-implementer-isolation-violation.md
Summary: Evaluation pending: whether the 0.31.0 dispatch wording stopped main from telling test-implementer to run tests, measured by 0.32.0 dispatch_run_instruction telemetry against the 0.28.0 pilot (3/3)
Related Files: harness/skills/workflow-approach/SKILL.md, harness/lib/isolation.py, harness/hooks/telemetry_hook.py, analytics/app.py
Related Symbols: detect, _dispatch, _harness_hacking, migrate_isolation_telemetry
---
File: d706c17a1d003208-speed-up-test-suite.md
Summary: Full test suite takes about 457 s single-core for 1219 tests; git hook commits are only ~10% of it; try per-file parallel runs, then measure hook payload subprocesses
Related Files: tests/test_installer.py, tests/test_progress.py, tests/test_hook_owned_progress.py, tests/test_doc_records.py, tests/test_message_nudge.py, tests/legacy_migrations.py
Related Symbols: run_installer, skip_legacy_update, DocRecordsTestCase.commit_all
---
File: e77323782c45bbfb-brief-telemetry-gaps.md
Summary: Telemetry records nothing before approval (brief rounds, fact questions, user decisions, split, picks differing), no event for agent-docs/facts writes, and no reason on amend; not started
Related Files: harness/lib/telemetry.py, harness/bin/workflow_marker.py, harness/hooks/telemetry_hook.py, harness/skills/workflow-approach/SKILL.md, analytics/compliance.py, analytics/importer.py
Related Symbols: workflow_phase, workflow_start, emit_path_write, evaluate, _WORKFLOW_EVENTS
---
File: b2373e0fdc356594-brief-transcript-parser.md
Summary: Second half of run 49bafb302bb6593c: rule-based transcript parser and dashboard view for brief decision axes and understanding, located by the brief event pointer; user rejected extra parser fields; not started
Related Files: analytics/transcripts.py, analytics/app.py, analytics/importer.py, analytics/frontend/src/App.jsx, harness/hooks/telemetry_hook.py
Related Symbols: index_transcripts, cached_sessions, emit_path_write

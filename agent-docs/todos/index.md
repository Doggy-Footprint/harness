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
File: 92b5be21b6ef9b80-multi-person-telemetry-digest.md
Summary: Planned future work to combine several people's telemetry and digest it; collection method and questions not decided; not started
Related Files: analytics/importer.py, analytics/app.py, harness/lib/telemetry.py
Related Symbols: import_pending, emit

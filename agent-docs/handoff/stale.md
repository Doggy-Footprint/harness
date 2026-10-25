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
---
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
File: fb75c4b9bf034034-selfcheck-m1-verifier-limit.md
Summary: selfcheck M1 (SWE-bench scorer and fixtures) stopped at the verifier limit with EG9–EG11 and SC4 open; fixtures and review evidence R1–R6 produced
Related Files: selfcheck/, agent-docs/spec-logs/323a0faf25256262-selfcheck-scorer-fixtures.md, agent-docs/adr/5c4c01bdc91769f7-selfcheck-swe-bench-baseline.md
Related Symbols: leak_check, score_prediction, evaluate, docker_exec, calibrate_instance
---
File: 74d5086b349dd339-selfcheck-m2-brief-pending.md
Summary: selfcheck M2 (agent runner) paused before approval; spec draft v1 written, brief v1 awaiting the user's answer
Related Files: agent-docs/specs/3a7ecc520d8871ae-selfcheck-agent-runner.md, selfcheck/, agent-docs/adr/5c4c01bdc91769f7-selfcheck-swe-bench-baseline.md
Related Symbols: driver.run, user_sim.answer, run.run, extract.build_prediction, manifest.build, build_derived_image
---
File: e3d9cb4226a44cfe-selfcheck-m2-verifier-limit.md
Summary: selfcheck M2 agent runner implemented and tested; stopped at the verifier limit with EG12 (resume sourcing of start_commit/install/selfcheck_commit untested) open; live smoke not run
Related Files: agent-docs/spec-logs/3a7ecc520d8871ae-selfcheck-agent-runner.md, selfcheck/run.py, selfcheck/tests/test_run.py, selfcheck/tests/test_live_smoke.py
Related Symbols: run.resume, run._drive, manifest.build, test_vo9_r3
---
File: 1ba36300e7469498-selfcheck-m3-verifier-limit.md
Summary: selfcheck M3 analysis stopped at verifier limit; EG1-EG3 test gaps open, implementation correct by reading
Related Files: selfcheck/process.py, selfcheck/fixture.py, selfcheck/report.py, selfcheck/run.py, selfcheck/__main__.py, selfcheck/tests/test_fixture.py, selfcheck/tests/test_process.py, selfcheck/tests/test_report.py, selfcheck/tests/test_cli_m3.py
Related Symbols: evaluate_entry, PC10, fixture.create, report.build, halt_reason

---
File: 3435f4b651e6d0e3-test-quality-audit-findings.md
Summary: Audit of 11 verifier+mutation-passed runs: mutant selection bias, non-discriminating inputs, subset oracles, verifier scope acceptance, mislabeled mutants
Related Files: harness/skills/workflow-approach/SKILL.md, harness/agents/test-implementer.md, harness/agents/test-verifier.md, harness/agents/mutant-triager.md, harness/bin/test_scan.py, tests/test_test_scan.py, tests/test_test_scan_rules.py, tests/test_installer.py
Related Symbols: Verification Obligations, Execution Ledger, hand mutations, mutation-tool triage, LANGUAGES, runner_candidates
---
File: bf0d1dd85535bb18-selfcheck-informed-brief-review.md
Summary: Stage 1/3 — post-run reviewer that compares harness briefs and spec with gold and reports divergences, without changing the run
Related Files: selfcheck/agent/user_sim.py, selfcheck/agent/driver.py, selfcheck/run.py, selfcheck/process.py, selfcheck/report.py, selfcheck/fixtures/instances.jsonl
Related Symbols: PHRASE, on_idle, compose_prompt, evaluate_entry, report.build
---
File: 3192c062a0fd880f-selfcheck-checker-gaps-and-repeats.md
Summary: Stage 2/3 — first live selfcheck check exposed PC8 blind to Bash spec writes, no retroactive-spec check, and a single harness run per instance
Related Files: selfcheck/process.py, selfcheck/__main__.py, selfcheck/run.py, selfcheck/report.py, selfcheck/fixture.py, selfcheck/results/a41e64cb9bbbef03.md
Related Symbols: evaluate_entry, PC8, PC2, PC9, cmd_check, run.run, report.build
---
File: 44ab3e5b5b54f81d-selfcheck-informed-reviewer-condition.md
Summary: Stage 3/3 — in-loop gold-informed reviewer answering harness briefs as a separate constrained condition; unassisted check stays primary
Related Files: selfcheck/agent/user_sim.py, selfcheck/agent/driver.py, selfcheck/run.py, selfcheck/manifest.py, selfcheck/fixture.py, selfcheck/report.py
Related Symbols: PHRASE, on_idle, max_user_turns, fixture_id, report.build
---
File: 4e61454e6935d1cc-usage-analysis-workflow-continuation.md
Summary: analytics.usage marks only the Skill-call turn as invoked; continuation turns of a workflow inflate "missed" — choose workflow_state option A or B
Related Files: analytics/usage.py, analytics/tests/test_usage.py, agent-docs/spec-logs/cce0155b008eaf53-workflow-usage-analysis.md
Related Symbols: extract_requests, apply_labels, mine_variants, build_report
---
File: 3cb41f5d6d74d413-per-version-run-metrics.md
Summary: From issue #10, record harness-version-tagged per-run metrics at run time for before/after comparison; not started
Related Files: harness/hooks/telemetry_hook.py, analytics/usage.py, analytics/store.py
Related Symbols: telemetry.emit
---
File: c379ec40307bd6c0-harness-value-evaluation-redesign.md
Summary: SWE-bench Verified self-check archived after run 8b28b1b5525cc30e; stages 1-2 of a claim-based harness evaluation on post-cutoff public feature commits are pending
Related Files: selfcheck/, selfcheck/results/8b28b1b5525cc30e.md, selfcheck/score.py, agent-docs/adr/stale/5c4c01bdc91769f7-selfcheck-swe-bench-baseline.md
Related Symbols: swt_outcome, test_id_key, attribute, process.evaluate_entry
---
File: d63aaa61098054c3-test-quality-evaluation-verifier-limit.md
Summary: Reference-mutation test-quality evaluation ended at pilot run 7df89a358d3faa30 by the user; GCP resources deleted, code archived as evaluation/reference_mutation/ without tests
Related Files: evaluation/reference_mutation/, evaluation/reference_mutation/EXPERIMENT.md, agent-docs/spec-logs/616f94189f1a4147-harness-test-quality-evaluation.md, README.md
Related Symbols: score.score_entry, score.kill, mutants.build_mutants, session_cost, crossarm.run_matrix
---
File: aea0d3ab56c57d53-adr-rejection-to-try-n-fail.md
Summary: Move ADR and rejection records to try-n-fail as the user chooses after the 0.29.0 update.
Related Files: agent-docs/adr/4a5b6c7d8e9f0123-versioned-migrations.md, agent-docs/adr/stale/5c4c01bdc91769f7-selfcheck-swe-bench-baseline.md
Related Symbols: none

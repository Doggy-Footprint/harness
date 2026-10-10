---
name: test-audit
description: User-invoked audit of an existing test suite (for example tests written before the harness was installed) that leaves feature-grouped handoffs for follow-up workflow-approach runs. Invoke only when the user asks for a test audit.
disable-model-invocation: true
argument-hint: "[path]"
---

# Scope

The argument is a path to audit; without one, audit the whole repository. Run `python3 .harness/bin/test_scan.py <path>` first. It lists test files, tests, suspicious signals (`skip`, `xfail`, `focused`, `no_assert`, `empty`, `sleep`, `heavy_mock`, `duplicate_name`), runner candidates, and `predates_harness`. Read only flagged files and files relevant to a feature under review, to save tokens. The scanner is rule-based and approximate for non-Python languages; verify a flag by reading before relying on it.

# Intent

Confirm what the project does at product level before judging any test.

1. Use documentation the user provides.
2. Otherwise draft a feature list from the README and code, and confirm it with the user using question cards. Use `requirement-oracle` for decisions the user cannot yet make.
3. Make no feature judgment (keep, delete, missing) before the user confirms the list.

# Run

1. Use the detected runner from the scan; ask the user when several candidates exist or none does.
2. Run the suite. Record failures, skips, and slow tests.
3. Rerun each failure to separate flaky from deterministic failures.
4. Collect coverage if the project already supports it; do not install tooling.

# Spec check

Read `agent-docs/spec-logs` and confirm that each archived spec's Verification Obligations are still covered by existing tests. Report an uncovered obligation by spec path and obligation id.

# Quality

Review the flagged and feature-relevant tests for:
- weak assertions (no assertion, trivially true, only checks no exception);
- implementation coupling (asserts private details or call order rather than behavior);
- over-mocking (the test verifies mocks, not the unit);
- duplicates;
- tests for features absent from the confirmed list: deletion candidates.

# Effectiveness

Per feature, sample hand mutations (a changed condition, boundary, operator, or return value) and check that a test fails.

1. `python3 .harness/bin/seed.py backup <files>` before mutating, `python3 .harness/bin/seed.py restore` after each mutation round.
2. If restore fails, stop immediately, report the failure, and do not continue.
3. Record each mutation and whether it was killed. A surviving mutation is a missing or weak test.

# Classify

Group every finding by feature, each as one of: delete tests, add tests, fix tests, fix implementation. Split any group that is larger than one workflow-approach run into several groups.

# Handoff

Write one `agent-docs/handoff/<16-hex-id>-test-audit-<feature>.md` per group, following the Handoff Rule structure in `AGENTS.md`:

- `## Spec` is `none — to be created by a follow-up workflow-approach`.
- `## Execution Ledger` holds the scan, run, and mutation evidence for that group.
- Add a matching entry to `agent-docs/handoff/index.md`.

Do not edit code or tests, other than the temporary hand mutations restored through `seed.py`.

# Report

List the groups (feature, finding kinds, handoff path) and the recommended order to run them.

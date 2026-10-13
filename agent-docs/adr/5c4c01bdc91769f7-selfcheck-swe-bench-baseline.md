# Self-check on Public SWE-bench Instances with a Fixture Baseline

Status: Accepted

## Context

The audit in `agent-docs/handoff/3435f4b651e6d0e3-test-quality-audit-findings.md` found that verifier PASS and self-reported mutant kills did not match test quality. The same audit found that the cross-version comparison was confounded with the target repository. None of its judgments were executed.

## Decision

`selfcheck/` runs 2–3 instances from SWE-bench Verified ∩ SWT-bench Verified in locally built arm64 images. It scores three things: hidden-test resolution, the kill rate of agent-written tests against mutants on gold-changed lines, and workflow process compliance. The no-harness baseline is run once and stored as a fixture keyed by its generation configuration.

## Alternatives

- Reconstruct past workflow-approach runs from local project repositories (base commit plus spec goal, with the audit's surviving mutants as the bug set). Rejected because the reference implementations are agent output and cannot serve as an oracle, and because private repositories prevent external comparison and reproduction.
- Rerun the baseline on every self-check. Rejected for cost.

## Consequences

- Positive: harness versions are compared on identical tasks with human-written fixes and tests as the oracle.
- Negative: most SWE-bench instances are bug fixes smaller than the feature scope workflow-approach targets, and a change of model or Claude Code version requires regenerating the baseline fixture.

# Versioned Migration Ordering

Status: Accepted

## Context

Harness updates can cross more than one migration version. A later migration can require the filesystem state established by an earlier migration.

## Decision

Run every applicable migration once in ascending target-version order. Plan and confirm the complete sequence before applying it.

## Alternatives

- Apply only the migration for the final harness version. Rejected because intermediate filesystem state would not be established.

## Consequences

- Positive: migrations can depend on the state from preceding versions.
- Negative: an update can require several confirmations.

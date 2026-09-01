# ADR 0003: PostgreSQL stores registry metadata only

- Status: Accepted
- Date: 2026-09-01

## Context

Model identity, immutable versions, artifact references, and later audit records
need transactional storage and useful querying. Deployment declarations already
have a Kubernetes-native authority.

## Decision

Use PostgreSQL for model registry and audit metadata. Use Alembic for migrations.
Do not store deployment desired state there. A registered `(model, version)` is
immutable; exact repeated registration is idempotent and different content is a
conflict.

## Consequences

Registry writes have clear transactional semantics. A PostgreSQL outage prevents
new registry and API deployment changes, but it will not be placed on the serving
path of already reconciled model workloads.

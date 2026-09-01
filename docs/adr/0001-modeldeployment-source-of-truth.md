# ADR 0001: ModelDeployment is deployment desired state

- Status: Accepted
- Date: 2026-09-01

## Context

Kernexys needs one authoritative desired state for model workloads. Duplicating
that state in PostgreSQL and Kubernetes would require conflict resolution and
could leave the reconciler acting on stale database state.

## Decision

`platform.kernexys.io/v1alpha1 ModelDeployment` will be the authoritative desired
state. The API will validate a request against registry metadata and create or
update the custom resource. The Go controller alone will reconcile child
Kubernetes resources. PostgreSQL may retain audit facts but not a second desired
state.

## Consequences

`kubectl`, the API, and a future CLI share one declaration. Kubernetes generation,
status, watches, ownership, and retries can be used directly. API availability is
not required for an existing declaration to continue reconciling.

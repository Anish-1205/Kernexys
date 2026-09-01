# ADR 0004: OCI images carry the initial model runtime artifacts

- Status: Accepted
- Date: 2026-09-01

## Context

The controller needs one deployable unit that couples runtime code with the exact
small model artifact being served. Fetching model state at pod startup would add
an external availability dependency and make local operation less reproducible.

## Decision

Package each initial reference model version as an OCI image. The demo builds the
same small CPU runtime as separate `v1` and `v2` images with version-specific
weights baked into the artifact. The process rejects a declared model version
that differs from the baked version. Registry metadata can store a tag for local
development or, preferably, an immutable image digest.

## Consequences

Pods can start without PostgreSQL, the control API, or an artifact download
service. Updates and rollback use ordinary Kubernetes image rollouts. Images may
grow inefficient for large future model artifacts; an external artifact store and
verified init-time fetch can be reconsidered when an implemented model requires
it. Mutable tags are acceptable only for the local demo and must not be treated as
immutable release identity.

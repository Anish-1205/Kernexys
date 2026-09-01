# ADR 0002: Python API and Go controller

- Status: Accepted
- Date: 2026-09-01

## Context

The registry API benefits from concise schema and HTTP tooling, while the core
reconciler benefits from Kubernetes-native libraries, types, and conventions.

## Decision

Use Python with FastAPI, Pydantic, and SQLAlchemy for the control API. Use Go with
controller-runtime for the Kubernetes controller. Keep the process boundary
explicit rather than building a shared cross-language domain framework.

## Consequences

Each component uses its ecosystem's idioms and can be tested independently. The
repository carries two toolchains, so CI and developer commands must keep their
validation jobs distinct.

# Architecture

## Intended control flow

```text
REST API / CLI / kubectl
          |
          v
platform.kernexys.io/v1alpha1 ModelDeployment
          |
          v
Kernexys controller reconciliation loop
          |
          v
owned Kubernetes workload + Service -> model runtime
```

The custom resource will be the source of truth for deployment desired state.
The control API will validate registered model metadata and write that resource;
it will not create Deployments, Services, Rollouts, or autoscaling resources.

## Implemented components

### Control API model registry

The Python/FastAPI process exposes health endpoints and a resource-oriented model
registry. PostgreSQL stores model identity and immutable version metadata. Alembic
owns schema evolution. The application uses a bounded connection pool and makes
readiness dependent on a time-bounded database query.

The liveness probe intentionally has no database dependency. A PostgreSQL outage
therefore removes an API pod from service without asking Kubernetes to restart an
otherwise healthy process. The API fails registry operations during that outage;
future, already-reconciled inference workloads will not depend on this database.

### Not yet implemented

The Kubernetes API, Go controller, deployment API, reference model runtime,
Redis/KEDA async path, observability stack, and progressive delivery are future
vertical slices. No behavior from those slices is claimed in this document.

## Data ownership

| Data | Authority | Rationale |
| --- | --- | --- |
| Model identity and immutable artifact metadata | PostgreSQL | Queryable registry metadata |
| Deployment desired state | `ModelDeployment` CR | Native watch/reconcile semantics |
| Child workload state | Kubernetes | Observed and repaired by the controller |
| Async inference jobs (future) | Redis with explicit bounds | Queue pressure and worker handoff |

## Current failure behavior

- API process crash: the process exits; its supervisor is expected to restart it.
- PostgreSQL unavailable: liveness remains healthy, readiness returns `503`, and
  registry requests fail. No inference workload currently exists in this slice.
- Graceful stop: Uvicorn stops accepting work, waits up to the configured graceful
  shutdown timeout, then FastAPI disposes the database engine.
- Oversized input: requests above the configured byte limit return a structured
  `413` before endpoint parsing.

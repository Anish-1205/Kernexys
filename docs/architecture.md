# Architecture

## Control flow

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

The custom resource is the source of truth for deployment desired state. The
deployment API validates registered model metadata and writes that resource; it
does not create Deployments, Services, Rollouts, or autoscaling resources.

## Implemented components

### Control API model registry

The Python/FastAPI process exposes health endpoints and a resource-oriented model
registry. PostgreSQL stores model identity and immutable version metadata. Alembic
owns schema evolution. The application uses a bounded connection pool and makes
readiness dependent on a time-bounded database query.

The liveness probe intentionally has no database dependency. A PostgreSQL outage
therefore removes an API pod from service without asking Kubernetes to restart an
otherwise healthy process. The API fails registry operations during that outage;
already-reconciled inference workloads do not depend on this database or API.

### Deployment API and CLI

The FastAPI deployment routes resolve an immutable model version in PostgreSQL,
then use strict Kubernetes server-side apply for the `ModelDeployment` only.
Read returns the CR's desired spec and controller-owned status. Delete is
idempotent and relies on owner-reference garbage collection. Rollback resolves a
previous registered image while preserving replica, port, and resource settings.

The API uses the `kernexys-control-api` field manager without force. A conflicting
kubectl or other manager-owned field therefore returns `409` instead of being
silently stolen. A resourceVersion precondition protects rollback from racing a
concurrent update. Kubernetes errors are converted to structured, sanitized API
errors. `kernexysctl` is a small HTTP client for deploy, status, rollback, and
delete; it is not a second Kubernetes implementation.

### ModelDeployment controller

The Go controller watches `platform.kernexys.io/v1alpha1` `ModelDeployment`
resources and owns a same-name Deployment and ClusterIP Service. Each reconcile
uses create-or-update semantics, restores controller-managed fields after drift,
and skips writes when the desired child resources and CR status already match.
The controller refuses to adopt a same-name object that has no controller owner.

Status exposes observed generation, desired/ready replicas, endpoint, active
model/version, and `Available`, `Progressing`, and `Degraded` conditions. Invalid
desired state is reported without retrying; Kubernetes/API failures are returned
to controller-runtime for its work-queue retry behavior. No finalizer is used:
children are Kubernetes-owned through controller references and require no
external cleanup.

The controller manager has bounded reconciliation concurrency, health/readiness
probes, a graceful shutdown deadline, leader election, and controller-runtime's
Prometheus reconciliation counters/error counters/duration histograms. Runtime
pods are emitted with CPU/memory settings from the CR and a restricted security
context.

### Reference model runtime

The reference runtime is a small deterministic sentiment classifier with two
sets of baked weights (`v1` and `v2`). Separate OCI image builds couple the HTTP
runtime and selected weights. The process refuses to start if the model version
declared by the controller differs from the image's baked version.

The synchronous runtime has no PostgreSQL or Redis dependency. It exposes live
and ready health, bounded inference requests, request IDs, and Prometheus request
count and latency metrics. Uvicorn bounds concurrent accepted work and drains on
termination. See [Reference runtime](runtime.md) and
[ADR 0004](adr/0004-oci-model-runtime-images.md).

### Asynchronous inference queue

The optional async API writes TTL-bound jobs to a capacity-limited Redis queue.
Workers atomically claim jobs through a processing list, call the already-running
runtime endpoint with a finite timeout, and persist sanitized success/failure
state. Startup requeues abandoned claims, providing at-least-once delivery.
Redis failure does not affect synchronous inference. See
[ADR 0005](adr/0005-redis-async-inference.md).

### Not yet implemented

KEDA reconciliation for the async worker, the observability stack, and progressive
delivery are future vertical slices. The kind manifests and runtime images have not been built
on this host, so real-cluster garbage collection, workload readiness, inference,
and drift-repair E2E behavior remain unverified.

## Data ownership

| Data | Authority | Rationale |
| --- | --- | --- |
| Model identity and immutable artifact metadata | PostgreSQL | Queryable registry metadata |
| Deployment desired state | `ModelDeployment` CR | Native watch/reconcile semantics |
| Child workload state | Kubernetes | Observed and repaired by the controller |
| Async inference jobs (future) | Redis with explicit bounds | Queue pressure and worker handoff |

## Current failure behavior

- API process crash: the process exits; its supervisor is expected to restart it.
- Controller process crash: Kubernetes retains CRs, Deployments, and Services;
  after restart, watches resynchronize and idempotent reconciliation resumes.
- PostgreSQL unavailable: liveness remains healthy, readiness returns `503`, and
  registry requests return a sanitized `database_unavailable` `503`. Existing
  Kubernetes workloads have no PostgreSQL dependency.
- Kubernetes API unavailable: when deployment integration is enabled, readiness
  returns `503` and deployment operations fail with a sanitized dependency error;
  registry data and existing inference workloads remain intact.
- Invalid `ModelDeployment`: the CR receives a `Degraded=True` condition with an
  `InvalidSpec` reason and is not hot-loop retried.
- Transient Kubernetes write failure: status is marked degraded when possible and
  the error is returned for controller-runtime backoff/retry.
- Graceful stop: Uvicorn stops accepting work, waits up to the configured graceful
  shutdown timeout, then FastAPI disposes the database engine.
- Controller graceful stop: the manager drains for up to 20 seconds and releases
  its leader-election lease.
- Oversized input: requests above the configured byte limit return a structured
  `413` before endpoint parsing.
- Runtime process crash: its Deployment restarts the pod; other ready replicas
  continue serving through the Service.
- Omitted runtime resources: the controller supplies conservative defaults of
  `100m` CPU and `128Mi` memory requests with `1` CPU and `512Mi` memory limits.
  Explicit CR values remain authoritative.
- Registry/API/PostgreSQL outage: an already-running synchronous runtime keeps
  serving because its artifact and model weights are in the OCI image.

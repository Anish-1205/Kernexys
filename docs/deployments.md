# Deployment API and CLI

The deployment API is a narrow HTTP projection of `ModelDeployment`. PostgreSQL
is consulted only to verify that the requested model version exists and to obtain
its immutable runtime image metadata. Kubernetes remains the desired-state
authority.

## Enable Kubernetes access

Kubernetes integration is opt-in so the registry and Docker Compose path can run
without a cluster. For a host process using the current kubeconfig:

```bash
export KERNEXYS_KUBERNETES_ENABLED=true
export KERNEXYS_KUBERNETES_CONFIG_MODE=kubeconfig
export KERNEXYS_KUBECONFIG="$HOME/.kube/config"
.venv/bin/kernexys-api
```

An in-cluster deployment uses `KERNEXYS_KUBERNETES_CONFIG_MODE=in-cluster` and
the `kernexys-api` service account. Checked-in RBAC permits only create, get,
patch, and delete on ModelDeployments. The API has no permission to create or
change Deployments, Services, Rollouts, autoscalers, or CR status.

When enabled, readiness checks both PostgreSQL and CRD discovery within the
configured deadlines. Liveness has no dependency call.

## HTTP resources

```text
PUT    /v1/deployments/{namespace}/{name}
GET    /v1/deployments/{namespace}/{name}
DELETE /v1/deployments/{namespace}/{name}
POST   /v1/deployments/{namespace}/{name}/rollback
POST   /v1/deployments/{namespace}/{name}/infer
```

`infer` is a synchronous convenience proxy used by the web console. It reads the
controller-reported `status.endpoint`, refuses with `409 deployment_not_ready`
unless the deployment is `Available` (as the async path does), and forwards
`{"text": ...}` to the runtime's `/v1/infer` within
`KERNEXYS_INFERENCE_TIMEOUT_SECONDS`. Runtime failures are sanitized to
`502 runtime_error` or `503 runtime_unavailable`. This places the API on an
optional inference path; runtimes still serve their own Service directly with no
dependency on the API, and the API still never writes workload resources.

## Web console

The API serves a single-page console at `/` (`app/static/index.html`, no build
step or external assets). It shows the registry, live `ModelDeployment` status
and conditions, and can register versions, apply desired state, roll back,
delete, and run inference through the proxy above.

Example desired state:

```json
{
  "model": "sentiment",
  "version": "v2",
  "replicas": 2,
  "port": 8080,
  "resources": {
    "requests": {"cpu": "50m", "memory": "64Mi"},
    "limits": {"cpu": "500m", "memory": "256Mi"}
  }
}
```

The runtime image is not caller-controlled in this request. It is copied from the
registered immutable version. Unknown versions are rejected before a Kubernetes
write. Repeating the same PUT is state-idempotent; the real API-server integration
test also verifies its resourceVersion stays unchanged.

Strict server-side apply uses field manager `kernexys-control-api` and does not
force conflicts. This is an intentional ownership boundary: a field owned by a
different manager produces `409 deployment_conflict`. Rollback preserves current
replicas, port, and resources, changes version/image, and includes the read
resourceVersion as an optimistic-concurrency precondition.

Delete is idempotent. The API requests background propagation, after which
Kubernetes garbage collection removes controller-owned children. No finalizer is
needed because no external resource is owned.

## CLI

`kernexysctl` talks only to the HTTP API:

```bash
kernexysctl deploy sentiment --namespace default \
  --model sentiment --version v2 --replicas 2 \
  --request cpu=50m --request memory=64Mi
kernexysctl status sentiment
kernexysctl rollback sentiment --version v1
kernexysctl delete sentiment
```

Set `KERNEXYS_API_URL` or pass `--api-url`. The CLI applies a finite HTTP timeout,
sends a request ID, prints JSON, and returns nonzero for structured API errors.

## Validation boundary

Unit tests use a stateful fake gateway for registry resolution, idempotency,
status mapping, rollback, deletion, validation, readiness failure, and sanitized
errors. Gateway tests assert strict apply headers and timeout propagation. The
cross-language envtest run exercised the actual async client against Kubernetes
1.37 kube-apiserver and the generated CRD. It did not run Docker, kind, the
controller process, garbage collection, or inference.

`scripts/demo.sh` covers that gap manually on kind: registry, deploy, inference,
controller drift repair after deleting the Deployment, v1→v2 upgrade, rollback,
and garbage-collected delete. It is not yet part of CI.

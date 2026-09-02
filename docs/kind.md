# Local kind environment

Kernexys pins kind `v0.33.0` and its Kubernetes node image to a digest-backed
Kubernetes `v1.37.0` build. Required host tools are Docker, kind, kubectl, and
GNU Make. The checked-in cluster configuration creates one control-plane and
one worker node.

## Synchronous development baseline

The normal kind baseline enables the registry and Kubernetes deployment API but
leaves optional asynchronous inference disabled. PostgreSQL is therefore
required; Redis and KEDA are not required for API readiness.

Set a URL-safe local PostgreSQL password, then run the existing kind targets:

```bash
export KERNEXYS_POSTGRES_PASSWORD='replace-with-a-random-url-safe-password'
make kind-create KIND_CLUSTER_NAME=kernexys-dev
make kind-build
make kind-load KIND_CLUSTER_NAME=kernexys-dev
make kind-install
make kind-validate
```

Omit the `KIND_CLUSTER_NAME` overrides to use the Makefile default, `kernexys`.
Use the same name for create and load when choosing another cluster name.

`kind-build` builds the control API, controller, and two reference runtime
images. `kind-load` imports those four first-party images into the kind nodes.
The PostgreSQL StatefulSet pulls its separately pinned upstream image.
`kind-install` then:

1. creates or updates the `kernexys-db` Secret from
   `KERNEXYS_POSTGRES_PASSWORD`;
2. applies the local-only PostgreSQL StatefulSet, Service, persistent volume
   claim, and network policy;
3. waits for PostgreSQL and runs the checked-in Alembic migration Job;
4. applies the CRD, API, controller, RBAC, and network policies.

The password is intentionally an out-of-band developer input and is never
checked in. The Secret contains both the API connection URL and the PostgreSQL
container password. Re-running `make kind-install` is supported and reruns the
idempotent migration Job before updating the control plane.

Validate directly when troubleshooting:

```bash
kubectl get statefulset,pods,services -n kernexys-system
kubectl get deployment kernexys-api kernexys-controller -n kernexys-system
kubectl get crd modeldeployments.platform.kernexys.io
kubectl get job kernexys-migrate -n kernexys-system
```

The reference runtime images are available to the cluster, but workloads remain
owned by `ModelDeployment`; bootstrap does not create an extra sample CR.

## Optional asynchronous inference

Redis is consulted by API readiness only when
`KERNEXYS_ASYNC_INFERENCE_ENABLED=true`. When it is false, no Redis Secret or
service is required and synchronous inference remains available. When it is
true, Redis is required and readiness identifies `redis` as the failing
dependency if it cannot be reached.

The Helm chart defaults to the synchronous baseline (`worker.enabled=false` and
`api.env.ASYNC_INFERENCE_ENABLED=false`). Enabling async inference requires all
of the following existing pieces together:

- a reachable Redis service;
- the documented `kernexys-redis` Secret;
- `api.env.ASYNC_INFERENCE_ENABLED=true`;
- `worker.enabled=true`; and
- KEDA when `worker.keda.enabled=true`.

See [Async inference](async-inference.md) and [KEDA autoscaling](keda.md) for the
Redis Secret shape and worker settings. Redis stores async queue state only; it
does not store registry metadata.

## Ownership and cleanup

Repository-managed kind resources are the PostgreSQL development StatefulSet,
migration Job, CRD, API, controller, RBAC, and network policies. PostgreSQL is
metadata storage only. The password value is the sole required out-of-band
baseline input.

Ad-hoc Docker containers, direct container-IP Secrets, load-test Redis services,
and worker test namespaces are not part of the baseline. A Docker container IP
is unstable across Docker restarts and must not be used as the database host.

Delete the cluster with:

```bash
make kind-delete KIND_CLUSTER_NAME=kernexys-dev
```

Deleting the cluster also deletes its local-path PostgreSQL volume. No external
database or Redis data is touched.

## Validation status

The synchronous bootstrap targets, PostgreSQL migration, API/controller
readiness, CRD discovery, reference sentiment runtime, and coexistence with an
installed KEDA control plane have been exercised against `kind-kernexys-dev`.

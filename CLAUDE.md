# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Kernexys is a local-first AI infrastructure control plane. A Kubernetes
`ModelDeployment` custom resource is the source of truth for deployment desired
state; a Go controller continuously reconciles it into an owned Deployment and
Service. The repo has three independently-tested components:

- **Python control plane** (`app/`) — FastAPI model registry, deployment API,
  CLI, and Redis-backed async inference queue/worker.
- **Go controller** (`controller/`) — controller-runtime reconciler for the
  `platform.kernexys.io/v1alpha1` `ModelDeployment` CRD.
- **Reference model runtime** (`runtime/`) — standalone deterministic
  sentiment-classifier HTTP service, baked into versioned OCI images (`v1`,
  `v2`), with no dependency on Postgres/Redis/the control plane.

Read `docs/architecture.md` before making cross-component changes — it documents
control flow, data ownership, and the current failure-behavior contract (what
happens on DB outage, Kubernetes API outage, process crash, etc.). Design
rationale for major boundaries lives in `docs/adr/`.

## Commands

### Python control plane (`app/`, requires `.venv`)

```bash
.venv/bin/ruff format --check .       # lint: format check
.venv/bin/ruff check .                # lint: rules
.venv/bin/python -m pytest --cov=app --cov-report=term-missing   # full suite
.venv/bin/python -m pytest tests/test_deployment_api.py          # single file
.venv/bin/python -m pytest tests/test_deployment_api.py::test_name  # single test
.venv/bin/alembic upgrade head        # apply migrations
```

On PowerShell, replace `.venv/bin/<tool>` with `.venv\Scripts\<tool>.exe`.
Equivalent `make` targets exist: `make install|format|lint|test|migrate|run`.

Tests default to SQLite for speed; real PostgreSQL/Kubernetes integration paths
are marked `integration` (see `pyproject.toml` markers) and require the real
dependency. `tests/conftest.py` is the shared fixture source — check it before
adding new fixtures.

### Go controller (`controller/`)

```bash
make controller-generate         # regenerate deepcopy/CRD/RBAC from api/v1alpha1
make controller-format           # go fmt
make controller-vet              # go vet
make controller-test             # unit tests, fake client, coverage -> cover.out
make controller-integration       # real envtest kube-apiserver + etcd
make api-kubernetes-integration   # envtest + Python control API server-side-apply test
```

`controller-integration`/`api-kubernetes-integration` pin `setup-envtest` and a
specific Kubernetes version (see `Makefile`). On Windows, controller-runtime
can't send Unix shutdown signals to envtest's processes; test teardown code
matches that exact failure and kills only the expected kube-apiserver/etcd
paths — don't broaden that matching without checking
`controller/internal/controller/envtest_cleanup_windows_test.go`.

Regenerate with `controller-generate` after any change to
`controller/api/v1alpha1/modeldeployment_types.go` — deepcopy and CRD YAML are
generated, not hand-edited.

### Reference runtime (`runtime/`)

```bash
make runtime-install
make runtime-lint      # ruff check runtime
make runtime-format    # ruff format runtime
make runtime-test       # pytest runtime/tests --cov=runtime/runtime_app
```

The runtime is a separate installable package (`runtime/pyproject.toml`) with
its own ruff config — don't assume root `pyproject.toml` settings apply there.
It's built into version-pinned images (`MODEL_VERSION` build arg); the process
refuses to start if the controller-declared model version doesn't match the
image's baked version.

### Local Kubernetes (`kind`)

`make kind-create|kind-build|kind-load|kind-install|kind-validate|kind-delete`
build/load all first-party images (control API, controller, both runtime
versions) into a pinned kind cluster and apply `controller/config/default` via
kustomize. See `docs/kind.md`; this workflow has not been run on all hosts —
don't assume it's validated without checking.

### Docker Compose (Python control plane only)

```bash
cp .env.example .env   # replace placeholder password
docker compose up --build --detach --wait
```

Starts Postgres, runs a one-shot migration service to completion, then the API.
`docker compose down` preserves the DB volume; `make container-clean` (or
`down --volumes`) is explicitly destructive.

## Architecture notes

### Control flow

```
REST API / CLI / kubectl
        |
        v
platform.kernexys.io/v1alpha1 ModelDeployment (source of truth)
        |
        v
Go controller reconciliation loop
        |
        v
owned Kubernetes Deployment + Service -> model runtime
```

The deployment API (`app/deployment_routes.py`) validates a registered model
version against PostgreSQL, then does a strict Kubernetes **server-side apply**
of the `ModelDeployment` CR using the `kernexys-control-api` field manager
(without force — a conflicting manager-owned field returns `409`, it is never
silently stolen). **The API never creates Deployments, Services, or any other
child workload resource directly** — only the Go controller does, and only in
reaction to the CR. Preserve this boundary in any change.

### Python app layout (`app/`)

- `main.py` — FastAPI app construction, lifespan/dependency wiring.
- `routes.py` — model registry endpoints (idempotent PUT model, immutable
  PUT model-version).
- `deployment_routes.py` — deploy/status/rollback/delete against
  `ModelDeployment` CRs (Kubernetes-backed, requires `KERNEXYS_KUBERNETES_ENABLED`).
- `async_routes.py` / `async_queue.py` / `worker.py` — optional Redis-backed
  async inference: capacity-bounded queue, at-least-once worker with
  idempotent claim/requeue-on-restart, TTL-bound jobs/results. Independent of
  the sync runtime and of PostgreSQL/Kubernetes availability.
- `kubernetes.py` — thin wrapper around `kubernetes-asyncio` for CR
  server-side apply/read/delete; all Kubernetes errors get sanitized/structured
  here before reaching routes.
- `repository.py` / `db_models.py` / `database.py` — SQLAlchemy async models
  and the model registry persistence layer.
- `config.py` — all runtime configuration via `KERNEXYS_*` env vars, validated
  at startup (see the table in `docs/development.md` for the full list and
  defaults). Every positive numeric setting is validated eagerly — follow that
  pattern for new settings rather than validating lazily at use.
- `errors.py` / `middleware.py` — structured error responses, request ID
  propagation/generation, bounded request bodies.
- `observability.py` / `metrics.py` / `logging_config.py` — JSON logs,
  Prometheus metrics, request correlation.
- `cli.py` — `kernexysctl`, a thin HTTP client for deploy/status/rollback/delete
  against the running API. It is intentionally **not** a second Kubernetes
  client — it must not talk to Kubernetes directly.

### Go controller layout (`controller/`)

- `api/v1alpha1/` — CRD types (`modeldeployment_types.go`); deepcopy is
  generated (`zz_generated.deepcopy.go`) — don't hand-edit.
- `internal/controller/modeldeployment_controller.go` — the reconciler:
  create-or-update of an owned same-name Deployment + ClusterIP Service,
  drift repair, generation-aware `Available`/`Progressing`/`Degraded` status
  conditions. Steady-state reconciliation must perform **zero** child/status
  writes when actual state already matches desired — the unit tests enforce
  this with a write-counting fake client
  (`modeldeployment_controller_test.go`), so avoid unconditional writes.
  Invalid desired spec is reported via status without hot-loop retry;
  Kubernetes/API failures are returned to controller-runtime for its own
  backoff/retry. No finalizer is used — children rely on owner-reference GC.
  The controller refuses to adopt a pre-existing same-name object with no
  controller owner reference (don't relax this without discussion).

### Data ownership

| Data | Authority |
| --- | --- |
| Model identity / immutable version metadata | PostgreSQL |
| Deployment desired state | `ModelDeployment` CR |
| Child workload state (Deployment/Service) | Kubernetes, repaired by controller |
| Async inference jobs | Redis (capacity- and TTL-bounded) |

### Failure-behavior contract

`docs/architecture.md` §"Current failure behavior" enumerates the guaranteed
behavior for each dependency outage (Postgres down, Kubernetes API down,
process crash, oversized input, etc.) — e.g. liveness never depends on the
database, only readiness does; an already-running sync runtime keeps serving
inference with zero Postgres/API/Kubernetes dependency. Treat that table as a
contract: if a change would alter one of these behaviors, call it out
explicitly rather than changing it incidentally.

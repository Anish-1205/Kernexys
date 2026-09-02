# Local development

## Supported runtime

The Python package targets Python 3.11 and newer. Production persistence is
PostgreSQL through `asyncpg`; SQLite is used only for fast isolated tests.

Create a virtual environment and install `.[dev]` as shown in the README. On
PowerShell, use these equivalent commands:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
$env:KERNEXYS_DATABASE_URL = "postgresql+asyncpg://kernexys:kernexys@localhost:5432/kernexys"
.\.venv\Scripts\alembic.exe upgrade head
.\.venv\Scripts\python.exe -m app
```

## Configuration

| Variable | Default | Purpose |
| --- | --- | --- |
| `KERNEXYS_DATABASE_URL` | local `kernexys` PostgreSQL URL | Registry database |
| `KERNEXYS_LOG_LEVEL` | `INFO` | JSON log threshold |
| `KERNEXYS_MAX_REQUEST_BYTES` | `1048576` | Per-request body bound |
| `KERNEXYS_DATABASE_POOL_SIZE` | `5` | Persistent connection bound |
| `KERNEXYS_DATABASE_MAX_OVERFLOW` | `5` | Temporary connection bound |
| `KERNEXYS_DATABASE_COMMAND_TIMEOUT_SECONDS` | `10` | Driver/pool timeout |
| `KERNEXYS_READINESS_TIMEOUT_SECONDS` | `2` | Readiness database deadline |
| `KERNEXYS_SERVER_PORT` | `8000` | Listen port |
| `KERNEXYS_SERVER_LIMIT_CONCURRENCY` | `100` | Accepted concurrent work bound |
| `KERNEXYS_SERVER_TIMEOUT_KEEP_ALIVE_SECONDS` | `5` | Idle keep-alive timeout |
| `KERNEXYS_SERVER_TIMEOUT_GRACEFUL_SHUTDOWN_SECONDS` | `20` | Shutdown drain deadline |
| `KERNEXYS_KUBERNETES_ENABLED` | `false` | Enable deployment CR operations and readiness check |
| `KERNEXYS_KUBERNETES_CONFIG_MODE` | `in-cluster` | Credential source: `in-cluster` or `kubeconfig` |
| `KERNEXYS_KUBECONFIG` | client default | Optional kubeconfig path |
| `KERNEXYS_KUBERNETES_CONTEXT` | current context | Optional kubeconfig context |
| `KERNEXYS_KUBERNETES_REQUEST_TIMEOUT_SECONDS` | `5` | Per-call Kubernetes deadline |
| `KERNEXYS_ASYNC_INFERENCE_ENABLED` | `false` | Enable Redis-backed jobs and readiness |
| `KERNEXYS_REDIS_URL` | `redis://localhost:6379/0` | Async queue connection URL |
| `KERNEXYS_ASYNC_QUEUE_CAPACITY` | `1000` | Waiting jobs before `429` backpressure |
| `KERNEXYS_ASYNC_JOB_TTL_SECONDS` | `3600` | Job and result retention |
| `KERNEXYS_ASYNC_WORKER_CONCURRENCY` | `4` | Concurrent worker consumers |
| `KERNEXYS_ASYNC_INFERENCE_TIMEOUT_SECONDS` | `30` | Worker runtime-call deadline |

Every positive numeric setting is validated at startup. Unknown JSON fields and
invalid resource names are rejected. Caller-supplied `X-Request-ID` values are
accepted only when they contain 1-128 safe characters; otherwise the API creates
a UUID. The ID is echoed in responses, structured errors, and request logs.

## Database changes

Create schema changes only through Alembic:

```bash
.venv/bin/alembic revision --autogenerate -m "describe change"
.venv/bin/alembic upgrade head
```

Review generated migrations before committing them. Model-version rows are
application-immutable: the API accepts an exact repeat and rejects different
content for an existing `(model_name, version)`.

## Docker Compose

The Compose path uses a pinned PostgreSQL image and the first-party multi-stage
API image. It does not require a registry:

```bash
cp .env.example .env
# Replace the placeholder with the same randomly generated URL-safe password in both places.
docker compose up --build --detach --wait
docker compose logs --follow api
```

The one-shot `migrate` service must finish successfully before the API starts.
The API runs as UID/GID 10001 with a read-only root filesystem, all Linux
capabilities dropped, `no-new-privileges`, a bounded temporary filesystem, CPU and
memory limits, and a 25-second termination grace period. The image's health check
tests process liveness; Compose tightens it to database-backed readiness.

Compose leaves Kubernetes integration disabled. To exercise deployments against
kind, run the API from the host with kubeconfig mode as documented in
[Deployments](deployments.md), or use a later Kubernetes-packaged API deployment.

`docker compose down` preserves the named database volume. Running
`docker compose down --volumes` deletes local registry data and is intentionally
exposed only as the clearly named `make container-clean` target.

## Validation status

The unit/API suite and migration upgrade/downgrade test run without external
services. The migration test uses SQLite to validate migration mechanics. A real
PostgreSQL integration run and container build have not yet been performed on the
current host because neither PostgreSQL nor Docker is installed; those validations
must not be inferred from the SQLite test.

The controller unit suite uses controller-runtime's fake client, including a
write-counting wrapper that verifies steady-state reconciliation performs no
child or status writes. Run the real API-server integration test with:

```bash
make controller-integration
make api-kubernetes-integration
```

That target pins `setup-envtest` and Kubernetes `1.37.0`, then starts local
kube-apiserver and etcd processes. On Windows, controller-runtime `v0.24.1`
cannot send its Unix shutdown signals; the test recovery code matches that exact
failure and terminates only the kube-apiserver and etcd executable paths selected
by the test. Other teardown failures still fail the suite.

`api-kubernetes-integration` additionally passes an ephemeral kubeconfig to the
Python control API and verifies a real server-side apply/create, idempotent repeat
without a resourceVersion change, read, and delete. This ran successfully on the
current host. It is an API-server integration test, not kind or workload E2E.

The validated kind workflow and its local PostgreSQL bootstrap are documented in
[Local kind environment](kind.md).

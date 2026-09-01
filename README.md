# Kernexys

Kernexys is a local-first AI infrastructure control plane. A Kubernetes
`ModelDeployment` is the source of truth, and the Go controller continuously
reconciles that declaration into an owned Deployment and Service.

The repository is being built in validated vertical slices. Implemented slices
currently include:

- a typed FastAPI service with liveness and database-backed readiness;
- idempotent model registration and immutable model-version registration;
- PostgreSQL-oriented SQLAlchemy models and Alembic migrations;
- structured errors, JSON logs, request IDs, bounded request bodies, bounded
  database pools, and graceful process shutdown;
- unit/API and migration tests;
- a generated `platform.kernexys.io/v1alpha1` `ModelDeployment` CRD;
- an idempotent controller-runtime reconciler with ownership, drift repair,
  generation-aware status conditions, health probes, and built-in reconciliation
  metrics;
- unit tests using a write-counting fake client and integration tests against a
  real envtest kube-apiserver and etcd;
- pinned kind configuration and local image build/load/install commands;
- deterministic CPU-only `v1` and `v2` reference runtime artifacts with health,
  readiness, bounded inference, request correlation, and Prometheus metrics.

The deployment API and later reliability features are not yet implemented. The
kind workflow is checked in but has not run on this host because Docker, kind, and
a host kubectl installation are absent. See [Architecture](docs/architecture.md),
[Controller](docs/controller.md), [Reference runtime](docs/runtime.md), and
[Local kind environment](docs/kind.md) for the implemented boundaries and exact
validation status.

## Run the current slice

Prerequisites are Python 3.11+ and PostgreSQL. Create an isolated environment and
install the development dependencies:

```bash
python -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
```

On PowerShell, the executable is `.venv\Scripts\python.exe`.

Create a database, export a local connection URL, migrate, and run:

```bash
export KERNEXYS_DATABASE_URL='postgresql+asyncpg://kernexys:kernexys@localhost:5432/kernexys'
.venv/bin/alembic upgrade head
.venv/bin/kernexys-api
```

The OpenAPI UI is at `http://localhost:8000/docs`. Useful probes are:

```text
GET /health/live
GET /health/ready
```

Register a model and an immutable version:

```bash
curl -X PUT http://localhost:8000/v1/models/sentiment \
  -H 'content-type: application/json' \
  -d '{"description":"Deterministic demo classifier"}'

curl -X PUT http://localhost:8000/v1/models/sentiment/versions/v1 \
  -H 'content-type: application/json' \
  -d '{"runtime_image":"kernexys/model-runtime:v1","metadata":{"labels":["negative","positive"]}}'
```

Repeating either request with identical content is safe. Reusing a model-version
identifier with different content returns `409 immutable_model_version`.

## Validate

```bash
.venv/bin/ruff format --check .
.venv/bin/ruff check .
.venv/bin/python -m pytest --cov=app --cov-report=term-missing
```

Additional setup, configuration, and current validation limits are documented in
[Local development](docs/development.md).

Validate the Go controller independently of Docker:

```bash
make controller-generate
make controller-format
make controller-vet
make controller-test
make controller-integration
```

Install and exercise the reference runtime independently of Docker:

```bash
make runtime-install
make runtime-lint
make runtime-test
KERNEXYS_BAKED_MODEL_VERSION=v2 KERNEXYS_MODEL_VERSION=v2 \
  .venv/bin/kernexys-model-runtime
curl -X POST http://127.0.0.1:8080/v1/infer \
  -H 'content-type: application/json' \
  -d '{"text":"reliable and fast"}'
```

## Docker development stack

Copy `.env.example` to `.env`, replace the placeholder password, and run:

```bash
docker compose up --build --detach --wait
curl http://127.0.0.1:8000/health/ready
```

Compose starts PostgreSQL, runs migrations to completion, and then starts the API.
`docker compose down` preserves database data. `make container-clean` is explicitly
destructive and also removes the local PostgreSQL volume.

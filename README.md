# Kernexys

Kernexys is a local-first AI infrastructure control plane. Its intended source of
truth is a Kubernetes `ModelDeployment`; a controller will continuously reconcile
that declaration into a runnable inference workload.

The repository is being built in validated vertical slices. The current slice is
the control API's model registry. It includes:

- a typed FastAPI service with liveness and database-backed readiness;
- idempotent model registration and immutable model-version registration;
- PostgreSQL-oriented SQLAlchemy models and Alembic migrations;
- structured errors, JSON logs, request IDs, bounded request bodies, bounded
  database pools, and graceful process shutdown;
- unit/API and migration tests.

The Kubernetes CRD/controller, deployment API, reference runtime, and later
reliability features are not yet implemented. See [Architecture](docs/architecture.md)
for the boundary that subsequent slices will preserve.

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

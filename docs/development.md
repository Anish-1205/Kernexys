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

## Validation status

The unit/API suite and migration upgrade/downgrade test run without external
services. The migration test uses SQLite to validate migration mechanics. A real
PostgreSQL integration run has not yet been performed on the current host because
neither PostgreSQL nor Docker is installed; that validation must not be inferred
from the SQLite test.

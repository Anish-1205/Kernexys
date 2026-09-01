# Asynchronous inference

Gate G introduces a bounded Redis-backed path without changing synchronous
runtime behavior.

`POST /v1/async-inference/{namespace}/{deployment}/jobs` accepts `{"text":"..."}`.
The deployment must have an `Available=True` controller condition and endpoint.
An optional `Idempotency-Key` returns the same job for an identical repeat and
returns `409` if reused with different input. New jobs return `202`; a full queue
returns `429`.

`GET /v1/async-inference/jobs/{job_id}` returns `queued`, `running`, `succeeded`,
or `failed`. Results expire after `KERNEXYS_ASYNC_JOB_TTL_SECONDS` (one hour by
default). Failure messages are intentionally sanitized.

Workers use an atomic queued-to-processing move. Normal termination finishes the
current request before exiting. A process crash can leave an ID in the processing
list; worker startup requeues such IDs under a Redis recovery lease longer than
the runtime deadline, so scale-out does not reclaim active jobs. A rapid restart
may wait for that lease to expire. Delivery is therefore at least once, not
exactly once. Runtime calls have a finite timeout and worker concurrency is bounded.

Unit tests cover bounded enqueue results, idempotency conflicts, processing-list
recovery, deployment readiness, polling, and worker success/failure. A real Redis
integration and KEDA scale timing require Docker/kind and have not run on this
host.

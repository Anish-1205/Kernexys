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

Workers use an atomic queued-to-processing move and then stamp the claim with
the time it was taken. Normal termination finishes the current request before
exiting. A process crash can leave an ID in the processing list; the recovery
sweep requeues only IDs whose claim is older than the recovery lease -- which
exceeds the runtime deadline -- so a job a live worker is still handling (or has
just finished) is never re-run or rewound to `queued`. The sweep runs as one
atomic Redis script, so a concurrent `finish` cannot slip between its
terminal-status check and the requeue: `finish` lands wholly before (the entry
is only unlinked) or wholly after (the job is already back on the queue and
`claim` rejects the terminal record on the next pop). Entries whose job record
already reached `succeeded`/`failed`, or expired, are unlinked from the
processing list rather than resurrected. An entry still missing its claim stamp
-- popped by `BLMOVE` but not yet stamped, whether by a live worker one
instruction away or a worker that died mid-claim -- is stamped by the sweep and
only requeued if it survives to a later sweep; requeued jobs have the stamp
cleared so a re-claim that dies mid-flight gets the same grace. Recovery runs at
startup and then re-runs once per lease interval, so a restart that races a
still-held lease reclaims the job once the lease lapses instead of stranding it;
the lease still admits only one worker per interval. Delivery is therefore at
least once, not exactly once. Runtime calls have a finite timeout and worker
concurrency is bounded.

Unit tests cover bounded enqueue results, idempotency conflicts, processing-list
recovery, deployment readiness, polling, and worker success/failure.
`make redis-integration` runs the recovery/claim race tests
(`tests/integration/test_async_queue_redis.py`) against a real Redis; KEDA scale
timing still requires kind.

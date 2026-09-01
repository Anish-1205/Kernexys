# ADR 0005: Redis is reserved for asynchronous inference

## Status

Accepted.

## Decision

Kernexys uses Redis only for bounded asynchronous inference jobs. Synchronous
runtime traffic, model registry reads, and controller reconciliation do not
depend on Redis.

The producer atomically creates a TTL-bound job hash and appends its ID to a
bounded list. Workers atomically move IDs to a processing list before calling a
ready runtime. A worker startup moves abandoned processing IDs back to the queue.
Recovery is guarded by a Redis lease longer than the runtime deadline so a newly
scaled worker does not reclaim active work. This provides at-least-once delivery;
the reference inference operation is
deterministic, so duplicate execution is safe. Client idempotency keys prevent
duplicate job creation and conflict when reused with different input.

## Consequences

Redis failure disables only asynchronous submission, polling, and workers.
Existing synchronous inference remains available. Queue depth is directly
observable by KEDA without introducing a separate broker. A Redis outage after a
worker has called a runtime but before it records the result can cause duplicate
execution after recovery; callers must not assume exactly-once side effects.

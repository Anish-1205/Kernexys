"""Bounded Redis queue primitives for asynchronous inference."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any

from redis.asyncio import Redis
from redis.exceptions import RedisError

QUEUE_KEY = "kernexys:inference:queued"
PROCESSING_KEY = "kernexys:inference:processing"
RECOVERY_LOCK_KEY = "kernexys:inference:recovery-lock"
JOB_PREFIX = "kernexys:inference:job:"

_ENQUEUE_SCRIPT = """
local job = KEYS[1]
local queue = KEYS[2]
if redis.call('EXISTS', job) == 1 then
  if redis.call('HGET', job, 'payload') ~= ARGV[1] then
    return -2
  end
  return 0
end
if redis.call('LLEN', queue) >= tonumber(ARGV[2]) then
  return -1
end
redis.call('HSET', job, 'status', 'queued', 'payload', ARGV[1])
redis.call('EXPIRE', job, tonumber(ARGV[3]))
redis.call('RPUSH', queue, ARGV[4])
return 1
"""


@dataclass(frozen=True, slots=True)
class EnqueueResult:
    created: bool
    full: bool
    conflict: bool = False


@dataclass(frozen=True, slots=True)
class ClaimedJob:
    job_id: str
    payload: dict[str, Any]


class AsyncQueueError(Exception):
    pass


class RedisInferenceQueue:
    def __init__(
        self,
        redis: Redis,
        capacity: int,
        job_ttl_seconds: int,
        recovery_lock_seconds: int = 60,
    ) -> None:
        self._redis = redis
        self._capacity = capacity
        self._job_ttl_seconds = job_ttl_seconds
        self._recovery_lock_seconds = recovery_lock_seconds

    @classmethod
    def create(
        cls,
        url: str,
        capacity: int,
        job_ttl_seconds: int,
        socket_timeout_seconds: int,
        recovery_lock_seconds: int = 60,
    ) -> RedisInferenceQueue:
        redis = Redis.from_url(
            url,
            decode_responses=True,
            socket_connect_timeout=socket_timeout_seconds,
            socket_timeout=socket_timeout_seconds,
            health_check_interval=30,
        )
        return cls(redis, capacity, job_ttl_seconds, recovery_lock_seconds)

    async def check_ready(self) -> None:
        try:
            await self._redis.ping()
        except RedisError as exc:
            raise AsyncQueueError("Redis is unavailable") from exc

    async def enqueue(self, job_id: str, payload: dict[str, Any]) -> EnqueueResult:
        try:
            result = await self._redis.eval(
                _ENQUEUE_SCRIPT,
                2,
                JOB_PREFIX + job_id,
                QUEUE_KEY,
                json.dumps(payload, separators=(",", ":"), sort_keys=True),
                self._capacity,
                self._job_ttl_seconds,
                job_id,
            )
        except RedisError as exc:
            raise AsyncQueueError("Redis is unavailable") from exc
        value = int(result)
        return EnqueueResult(created=value == 1, full=value == -1, conflict=value == -2)

    async def get(self, job_id: str) -> dict[str, str] | None:
        try:
            value = await self._redis.hgetall(JOB_PREFIX + job_id)
        except RedisError as exc:
            raise AsyncQueueError("Redis is unavailable") from exc
        return dict(value) if value else None

    async def claim(self, timeout_seconds: int = 2) -> ClaimedJob | None:
        try:
            job_id = await self._redis.blmove(
                QUEUE_KEY, PROCESSING_KEY, timeout_seconds, "LEFT", "RIGHT"
            )
            if job_id is None:
                return None
            job = await self._redis.hgetall(JOB_PREFIX + job_id)
            if not job or job.get("status") in {"succeeded", "failed"}:
                await self._redis.lrem(PROCESSING_KEY, 1, job_id)
                return None
            await self._redis.hset(
                JOB_PREFIX + job_id,
                mapping={"status": "running", "claimed_at": repr(time.time())},
            )
            return ClaimedJob(job_id=job_id, payload=json.loads(job["payload"]))
        except (RedisError, KeyError, json.JSONDecodeError) as exc:
            raise AsyncQueueError("Redis queue state is unavailable or invalid") from exc

    async def finish(
        self,
        job_id: str,
        status: str,
        result: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> None:
        mapping = {"status": status}
        if result is not None:
            mapping["result"] = json.dumps(result, separators=(",", ":"), sort_keys=True)
        if error is not None:
            mapping["error"] = error
        try:
            async with self._redis.pipeline(transaction=True) as pipeline:
                pipeline.hset(JOB_PREFIX + job_id, mapping=mapping)
                pipeline.expire(JOB_PREFIX + job_id, self._job_ttl_seconds)
                pipeline.lrem(PROCESSING_KEY, 1, job_id)
                await pipeline.execute()
        except RedisError as exc:
            raise AsyncQueueError("Redis is unavailable") from exc

    async def recover_processing(self) -> int:
        """Requeue jobs stranded in the processing list by a departed worker.

        The sweep only reclaims an ID whose claim is older than the recovery
        lease: a live worker finishes a claim within the runtime deadline (which
        the lease exceeds), so a younger entry belongs to work still in flight
        and is left untouched. Entries whose job record already reached a
        terminal status, or expired entirely, are only unlinked from the
        processing list -- never resurrected. This keeps delivery at least once
        without re-running or rewinding jobs a worker is actively handling.
        """
        recovered = 0
        try:
            acquired = await self._redis.set(
                RECOVERY_LOCK_KEY, "1", nx=True, ex=self._recovery_lock_seconds
            )
            if not acquired:
                return 0
            stranded_before = time.time() - self._recovery_lock_seconds
            for job_id in await self._redis.lrange(PROCESSING_KEY, 0, -1):
                job = await self._redis.hgetall(JOB_PREFIX + job_id)
                if not job or job.get("status") in {"succeeded", "failed"}:
                    await self._redis.lrem(PROCESSING_KEY, 1, job_id)
                    continue
                try:
                    claimed_at = float(job.get("claimed_at", ""))
                except ValueError:
                    claimed_at = 0.0
                if claimed_at > stranded_before:
                    continue
                if not await self._redis.lrem(PROCESSING_KEY, 1, job_id):
                    continue
                if await self._redis.hget(JOB_PREFIX + job_id, "status") in {
                    "succeeded",
                    "failed",
                }:
                    continue
                await self._redis.hset(JOB_PREFIX + job_id, mapping={"status": "queued"})
                await self._redis.rpush(QUEUE_KEY, job_id)
                recovered += 1
        except RedisError as exc:
            raise AsyncQueueError("Redis is unavailable") from exc
        return recovered

    async def close(self) -> None:
        await self._redis.aclose()

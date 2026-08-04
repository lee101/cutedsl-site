"""Small, dependency-free dynamic microbatch scheduler.

The scheduler preserves FIFO order for the oldest compatibility class while
allowing matching work that arrived in the same short window to share one GPU
residency lease.  Model-specific compatibility and execution stay in the
inference server so this module can be unit tested without importing torch.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Hashable


@dataclass(slots=True)
class _Job:
    value: Any
    key: Hashable
    priority: int
    future: asyncio.Future
    enqueued_at: float


class DynamicBatcher:
    """Collect compatible jobs for a bounded window and execute them together."""

    def __init__(
        self,
        *,
        key_fn: Callable[[Any], Hashable],
        run_batch: Callable[[list[Any]], Awaitable[list[Any]]],
        priority_fn: Callable[[Any], int] | None = None,
        max_batch_size: int,
        window_ms: float,
    ) -> None:
        self._key_fn = key_fn
        self._run_batch = run_batch
        self._priority_fn = priority_fn or (lambda _value: 0)
        self.max_batch_size = max(1, int(max_batch_size))
        self.window_seconds = max(0.0, float(window_ms) / 1000.0)
        self._lock = asyncio.Lock()
        self._pending: list[_Job] = []
        self._runner: asyncio.Task | None = None
        self._closed = False
        self._batches = 0
        self._jobs = 0
        self._max_observed_batch = 0
        self._queue_wait_ms_total = 0.0

    async def submit(self, value: Any) -> Any:
        loop = asyncio.get_running_loop()
        future = loop.create_future()
        job = _Job(
            value,
            self._key_fn(value),
            int(self._priority_fn(value)),
            future,
            time.monotonic(),
        )
        async with self._lock:
            if self._closed:
                raise RuntimeError("dynamic batcher is closed")
            self._pending.append(job)
            if self._runner is None or self._runner.done():
                self._runner = asyncio.create_task(self._drain())
        return await future

    async def close(self) -> None:
        async with self._lock:
            self._closed = True
            runner = self._runner
        if runner is not None:
            await runner

    def snapshot(self) -> dict[str, int | float | bool]:
        average = self._queue_wait_ms_total / self._jobs if self._jobs else 0.0
        return {
            "enabled": not self._closed,
            "window_ms": round(self.window_seconds * 1000.0, 3),
            "max_batch_size": self.max_batch_size,
            "pending": len(self._pending),
            "batches": self._batches,
            "jobs": self._jobs,
            "max_observed_batch": self._max_observed_batch,
            "average_queue_wait_ms": round(average, 3),
        }

    async def _take_batch(self) -> list[_Job]:
        async with self._lock:
            if not self._pending:
                return []
            # Highest priority wins; min() on enqueue time preserves FIFO
            # within that priority. Running GPU work is never preempted.
            lead = max(
                self._pending,
                key=lambda job: (job.priority, -job.enqueued_at),
            )
            key = lead.key
            priority = lead.priority
            selected: list[_Job] = []
            remaining: list[_Job] = []
            for job in self._pending:
                if (
                    job.key == key
                    and job.priority == priority
                    and len(selected) < self.max_batch_size
                ):
                    selected.append(job)
                else:
                    remaining.append(job)
            self._pending = remaining
            return selected

    async def _drain(self) -> None:
        while True:
            if self.window_seconds:
                await asyncio.sleep(self.window_seconds)
            jobs = await self._take_batch()
            if not jobs:
                async with self._lock:
                    self._runner = None
                return

            started = time.monotonic()
            try:
                results = await self._run_batch([job.value for job in jobs])
                if len(results) != len(jobs):
                    raise RuntimeError(
                        f"batch executor returned {len(results)} results for {len(jobs)} jobs"
                    )
            except BaseException as exc:
                for job in jobs:
                    if not job.future.done():
                        job.future.set_exception(exc)
            else:
                for job, result in zip(jobs, results):
                    if not job.future.done():
                        job.future.set_result(result)

            now = time.monotonic()
            self._batches += 1
            self._jobs += len(jobs)
            self._max_observed_batch = max(self._max_observed_batch, len(jobs))
            self._queue_wait_ms_total += sum(
                max(0.0, (started - job.enqueued_at) * 1000.0) for job in jobs
            )

            async with self._lock:
                if not self._pending:
                    self._runner = None
                    return
            # Yield before selecting the next compatibility class. This keeps
            # request cancellation and health probes responsive under load.
            await asyncio.sleep(0)

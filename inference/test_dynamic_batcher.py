import asyncio

from inference.dynamic_batcher import DynamicBatcher


def test_dynamic_batcher_groups_compatible_jobs_and_preserves_results():
    async def scenario():
        calls = []

        async def run_batch(values):
            calls.append(list(values))
            return [value * 10 for value in values]

        batcher = DynamicBatcher(
            key_fn=lambda value: value % 2,
            run_batch=run_batch,
            max_batch_size=3,
            window_ms=2,
        )
        results = await asyncio.gather(*(batcher.submit(i) for i in (1, 3, 2, 5)))
        await batcher.close()
        return results, calls, batcher.snapshot()

    results, calls, stats = asyncio.run(scenario())
    assert results == [10, 30, 20, 50]
    assert calls == [[1, 3, 5], [2]]
    assert stats["jobs"] == 4
    assert stats["max_observed_batch"] == 3


def test_dynamic_batcher_propagates_executor_failure_to_every_job():
    async def scenario():
        async def fail(_values):
            raise ValueError("boom")

        batcher = DynamicBatcher(
            key_fn=lambda _value: "same",
            run_batch=fail,
            max_batch_size=4,
            window_ms=1,
        )
        outcomes = await asyncio.gather(
            batcher.submit(1), batcher.submit(2), return_exceptions=True
        )
        await batcher.close()
        return outcomes

    outcomes = asyncio.run(scenario())
    assert all(isinstance(outcome, ValueError) for outcome in outcomes)


def test_dynamic_batcher_prioritizes_public_work_over_queued_background_work():
    async def scenario():
        calls = []

        async def run_batch(values):
            calls.append(list(values))
            return values

        batcher = DynamicBatcher(
            key_fn=lambda value: value[0],
            priority_fn=lambda value: value[1],
            run_batch=run_batch,
            max_batch_size=4,
            window_ms=5,
        )
        results = await asyncio.gather(
            batcher.submit(("background", 0)),
            batcher.submit(("public", 1)),
        )
        await batcher.close()
        return results, calls

    results, calls = asyncio.run(scenario())
    assert results == [("background", 0), ("public", 1)]
    assert calls == [[("public", 1)], [("background", 0)]]

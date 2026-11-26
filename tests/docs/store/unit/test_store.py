from dataclasses import dataclass
from typing import TYPE_CHECKING

import anyio
import pytest
from cachetools import TTLCache
from python_docs_mcp.core.exception import (
    FillTimeoutError,
    RetrievalFailedError,
    VersionNotPublishedError,
)
from python_docs_mcp.store import CachedLoader

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from anyio.abc import TaskGroup
    from python_docs_mcp.core.exception import (
        DocumentationError,
    )

KEY = 'key'


@dataclass(slots=True, kw_only=True)
class RecordingLoader:
    delay_seconds: float = 0
    failure: Exception | None = None
    calls: int = 0

    async def load(self, key: str) -> str:
        self.calls += 1
        await anyio.sleep(self.delay_seconds)
        if self.failure is not None:
            raise self.failure
        return f'value:{key}'


@dataclass(slots=True)
class Clock:
    now: float = 0

    def read(self) -> float:
        return self.now


@pytest.fixture
async def fills() -> AsyncGenerator[TaskGroup]:
    async with anyio.create_task_group() as group:
        yield group
        group.cancel_scope.cancel()


def create_cache(
    loader: RecordingLoader, fills: TaskGroup, clock: Clock, value_capacity: int = 64
) -> CachedLoader[str, str]:
    return CachedLoader(
        values=TTLCache(maxsize=value_capacity, ttl=60, timer=clock.read, getsizeof=len),
        misses=TTLCache(maxsize=8, ttl=300, timer=clock.read),
        loader=loader.load,
        fills=fills,
        fill_timeout_seconds=0.5,
    )


@pytest.fixture
def clock() -> Clock:
    return Clock()


class TestCachedLoader:
    async def outcome(self, cache: CachedLoader[str, str]) -> str | DocumentationError:
        try:
            return await cache.get(KEY)
        except (RetrievalFailedError, VersionNotPublishedError) as error:
            return error

    async def test_concurrent_callers_share_one_fill(self, fills: TaskGroup, clock: Clock) -> None:
        loader = RecordingLoader(delay_seconds=0.05)
        cache = create_cache(loader, fills, clock)
        results: list[str] = []

        async def collect() -> None:
            results.append(await cache.get(KEY))

        async with anyio.create_task_group() as callers:
            for _ in range(5):
                callers.start_soon(collect)
        assert (results, loader.calls) == ([f'value:{KEY}'] * 5, 1)

    async def test_an_abandoning_caller_does_not_cancel_the_fill(
        self, fills: TaskGroup, clock: Clock
    ) -> None:
        loader = RecordingLoader(delay_seconds=0.1)
        cache = create_cache(loader, fills, clock)
        with anyio.move_on_after(0.01):
            await cache.get(KEY)
        assert (await cache.get(KEY), loader.calls) == (f'value:{KEY}', 1)

    async def test_a_cached_value_is_served_without_loading(
        self, fills: TaskGroup, clock: Clock
    ) -> None:
        loader = RecordingLoader()
        cache = create_cache(loader, fills, clock)
        results = [await cache.get(KEY), await cache.get(KEY)]
        assert (results, loader.calls) == ([f'value:{KEY}'] * 2, 1)

    async def test_a_value_is_loaded_again_after_its_ttl(
        self, fills: TaskGroup, clock: Clock
    ) -> None:
        loader = RecordingLoader()
        cache = create_cache(loader, fills, clock)
        await cache.get(KEY)
        clock.now = 61
        await cache.get(KEY)
        assert loader.calls == 2

    async def test_a_permanent_miss_is_remembered_until_the_miss_ttl(
        self, fills: TaskGroup, clock: Clock
    ) -> None:
        failure = VersionNotPublishedError('3.99')
        loader = RecordingLoader(failure=failure)
        cache = create_cache(loader, fills, clock)
        inside = [await self.outcome(cache), await self.outcome(cache)]
        calls_inside = loader.calls
        clock.now = 301
        await self.outcome(cache)
        assert (inside, calls_inside, loader.calls) == ([failure, failure], 1, 2)

    async def test_a_transient_failure_is_retried(self, fills: TaskGroup, clock: Clock) -> None:
        failure = RetrievalFailedError('https://x')
        loader = RecordingLoader(failure=failure)
        cache = create_cache(loader, fills, clock)
        outcomes = [await self.outcome(cache), await self.outcome(cache)]
        assert (outcomes, loader.calls) == ([failure, failure], 2)

    async def test_a_non_documentation_error_fails_only_its_own_key(
        self, fills: TaskGroup, clock: Clock
    ) -> None:
        failure = RuntimeError('boom')
        loader = RecordingLoader(failure=failure)
        cache = create_cache(loader, fills, clock)
        with pytest.raises(RuntimeError) as raised:
            await cache.get(KEY)
        loader.failure = None
        assert (raised.value, await cache.get('other')) == (failure, 'value:other')

    async def test_an_oversized_value_is_served_but_not_cached(
        self, fills: TaskGroup, clock: Clock
    ) -> None:
        loader = RecordingLoader()
        cache = create_cache(loader, fills, clock, value_capacity=4)
        results = [await cache.get(KEY), await cache.get(KEY)]
        assert (results, loader.calls) == ([f'value:{KEY}'] * 2, 2)

    async def test_a_fill_stops_at_its_own_deadline(self, fills: TaskGroup, clock: Clock) -> None:
        cache = create_cache(RecordingLoader(delay_seconds=5), fills, clock)
        with pytest.raises(FillTimeoutError):
            await cache.get(KEY)

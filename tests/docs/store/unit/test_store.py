from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import anyio
import pytest
from cachetools import TTLCache
from python_docs_mcp.core.exception import (
    FillTimeoutError,
    RetrievalFailedError,
    VersionNotPublishedError,
)
from python_docs_mcp.stores.store import CachedLoader

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from anyio.abc import TaskGroup
    from python_docs_mcp.core.exception import (
        DocumentationError,
    )

    from tests.docs.support.clock import FakeClock

KEY = 'key'


def create_open_gate() -> anyio.Event:
    gate = anyio.Event()
    gate.set()
    return gate


@dataclass(slots=True, kw_only=True)
class RecordingLoader:
    gate: anyio.Event = field(default_factory=create_open_gate)
    started: anyio.Event = field(default_factory=anyio.Event)
    failure: Exception | None = None
    calls: int = 0

    async def load(self, key: str) -> str:
        self.calls += 1
        self.started.set()
        await self.gate.wait()
        if self.failure is not None:
            raise self.failure
        return f'value:{key}'


@pytest.fixture
async def fills() -> AsyncGenerator[TaskGroup]:
    async with anyio.create_task_group() as group:
        yield group
        group.cancel_scope.cancel()


@dataclass(slots=True, kw_only=True, frozen=True)
class Collector:
    cache: CachedLoader[str, str]
    outcomes: list[str | DocumentationError] = field(default_factory=list)

    async def collect(self) -> None:
        try:
            self.outcomes.append(await self.cache.get(KEY))
        except (RetrievalFailedError, VersionNotPublishedError) as error:
            self.outcomes.append(error)


def create_cache(
    loader: RecordingLoader, fills: TaskGroup, clock: FakeClock, value_capacity: int = 64
) -> CachedLoader[str, str]:
    return CachedLoader(
        values=TTLCache(maxsize=value_capacity, ttl=60, timer=clock.monotonic, getsizeof=len),
        misses=TTLCache(maxsize=8, ttl=300, timer=clock.monotonic),
        loader=loader,
        fills=fills,
        fill_timeout_seconds=0.5,
    )


class TestCachedLoader:
    async def outcome(self, cache: CachedLoader[str, str]) -> str | DocumentationError:
        try:
            return await cache.get(KEY)
        except (RetrievalFailedError, VersionNotPublishedError) as error:
            return error

    async def test_concurrent_callers_share_one_fill(
        self, fills: TaskGroup, clock: FakeClock
    ) -> None:
        loader = RecordingLoader(gate=anyio.Event())
        collector = Collector(cache=create_cache(loader, fills, clock))
        async with anyio.create_task_group() as callers:
            for _ in range(5):
                callers.start_soon(collector.collect)
            await loader.started.wait()
            loader.gate.set()
        assert (collector.outcomes, loader.calls) == ([f'value:{KEY}'] * 5, 1)

    async def test_an_abandoning_caller_does_not_cancel_the_fill(
        self, fills: TaskGroup, clock: FakeClock
    ) -> None:
        loader = RecordingLoader(gate=anyio.Event())
        cache = create_cache(loader, fills, clock)
        with anyio.move_on_after(0.01):
            await cache.get(KEY)
        loader.gate.set()
        assert (await cache.get(KEY), loader.calls) == (f'value:{KEY}', 1)

    async def test_a_cached_value_is_served_without_loading(
        self, fills: TaskGroup, clock: FakeClock
    ) -> None:
        loader = RecordingLoader()
        cache = create_cache(loader, fills, clock)
        results = [await cache.get(KEY), await cache.get(KEY)]
        assert (results, loader.calls) == ([f'value:{KEY}'] * 2, 1)

    async def test_a_value_is_loaded_again_after_its_ttl(
        self, fills: TaskGroup, clock: FakeClock
    ) -> None:
        loader = RecordingLoader()
        cache = create_cache(loader, fills, clock)
        await cache.get(KEY)
        clock.advance(61)
        await cache.get(KEY)
        assert loader.calls == 2

    async def test_a_permanent_miss_is_remembered_until_the_miss_ttl(
        self, fills: TaskGroup, clock: FakeClock
    ) -> None:
        failure = VersionNotPublishedError('3.99')
        loader = RecordingLoader(failure=failure)
        cache = create_cache(loader, fills, clock)
        inside = [await self.outcome(cache), await self.outcome(cache)]
        calls_inside = loader.calls
        clock.advance(301)
        await self.outcome(cache)
        assert (
            [type(error) for error in inside],
            [str(error) for error in inside],
            calls_inside,
            loader.calls,
        ) == ([VersionNotPublishedError] * 2, [str(failure)] * 2, 1, 2)

    async def test_a_transient_failure_is_retried(self, fills: TaskGroup, clock: FakeClock) -> None:
        failure = RetrievalFailedError('https://x')
        loader = RecordingLoader(failure=failure)
        cache = create_cache(loader, fills, clock)
        outcomes = [await self.outcome(cache), await self.outcome(cache)]
        assert (
            [type(error) for error in outcomes],
            [str(error) for error in outcomes],
            loader.calls,
        ) == ([RetrievalFailedError] * 2, [str(failure)] * 2, 2)

    async def test_a_non_documentation_error_fails_only_its_own_key(
        self, fills: TaskGroup, clock: FakeClock
    ) -> None:
        failure = RuntimeError('boom')
        loader = RecordingLoader(failure=failure)
        cache = create_cache(loader, fills, clock)
        with pytest.raises(RuntimeError) as raised:
            await cache.get(KEY)
        loader.failure = None
        assert (raised.value.__cause__, str(raised.value), await cache.get('other')) == (
            failure,
            str(failure),
            'value:other',
        )

    async def test_an_oversized_value_is_served_but_not_cached(
        self, fills: TaskGroup, clock: FakeClock
    ) -> None:
        loader = RecordingLoader()
        cache = create_cache(loader, fills, clock, value_capacity=4)
        results = [await cache.get(KEY), await cache.get(KEY)]
        assert (results, loader.calls) == ([f'value:{KEY}'] * 2, 2)

    async def test_a_fill_stops_at_its_own_deadline(
        self, fills: TaskGroup, clock: FakeClock
    ) -> None:
        cache = create_cache(RecordingLoader(gate=anyio.Event()), fills, clock)
        with pytest.raises(FillTimeoutError):
            await cache.get(KEY)


class TestFailureIdentity:
    async def failure(self, cache: CachedLoader[str, str]) -> DocumentationError:
        try:
            await cache.get(KEY)
        except (RetrievalFailedError, VersionNotPublishedError) as error:
            return error
        raise AssertionError

    async def test_waiters_on_a_failed_fill_receive_distinct_errors(
        self, fills: TaskGroup, clock: FakeClock
    ) -> None:
        failure = RetrievalFailedError('https://x')
        loader = RecordingLoader(gate=anyio.Event(), failure=failure)
        collector = Collector(cache=create_cache(loader, fills, clock))
        async with anyio.create_task_group() as callers:
            callers.start_soon(collector.collect)
            callers.start_soon(collector.collect)
            await loader.started.wait()
            loader.gate.set()
        first, second = collector.outcomes
        assert (first is second, type(first), str(first), loader.calls) == (
            False,
            type(second),
            str(second),
            1,
        )

    async def test_calls_answered_from_the_misses_cache_receive_distinct_errors(
        self, fills: TaskGroup, clock: FakeClock
    ) -> None:
        loader = RecordingLoader(failure=VersionNotPublishedError('3.99'))
        cache = create_cache(loader, fills, clock)
        await self.failure(cache)
        first, second = await self.failure(cache), await self.failure(cache)
        assert (first is second, type(first), str(first)) == (
            False,
            type(second),
            str(second),
        )

    async def test_a_note_added_to_one_clone_does_not_reach_the_original_or_other_clones(
        self, fills: TaskGroup, clock: FakeClock
    ) -> None:
        original = VersionNotPublishedError('3.99')
        original.add_note('original')
        cache = create_cache(RecordingLoader(failure=original), fills, clock)
        first, second = await self.failure(cache), await self.failure(cache)
        first.add_note('first')
        assert (original.__notes__, second.__notes__) == (['original'], ['original'])
        assert first.__notes__ == ['original', 'first']

"""The documentation service the tools use, and the factory that composes it."""

from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass, field
from time import monotonic
from typing import TYPE_CHECKING

import anyio
from cachetools import TTLCache

from python_agent_tools_docs.disk_cache import MemoryInventoryStore
from python_agent_tools_docs.errors import CallDeadlineExceededError
from python_agent_tools_docs.repository import (
    DocumentationSource,
    SectionLoader,
    documentation_http_client,
)
from python_agent_tools_docs.store import CachedLoader

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Awaitable, Callable, Generator, Hashable

    import httpx2
    from anyio.abc import TaskGroup

    from python_agent_tools_docs.disk_cache import InventoryStore
    from python_agent_tools_docs.domain import DocumentationUrl, PythonVersion, Symbol
    from python_agent_tools_docs.matching import SymbolCatalog
    from python_agent_tools_docs.settings import Settings


@contextmanager
def call_deadline(seconds: float) -> Generator[None]:
    try:
        with anyio.fail_after(seconds):
            yield
    except TimeoutError as error:
        raise CallDeadlineExceededError(seconds) from error


@dataclass(frozen=True, slots=True, kw_only=True, eq=False)
class DocumentationService:
    catalogs: CachedLoader[PythonVersion, SymbolCatalog]
    sections: CachedLoader[DocumentationUrl, str]
    settings: Settings

    async def catalog(self, version: PythonVersion) -> SymbolCatalog:
        return await self.catalogs.get(version)

    async def section(self, symbol: Symbol) -> str:
        return await self.sections.get(symbol.source_url)


@dataclass(frozen=True, slots=True, kw_only=True, eq=False)
class LoaderEnvironment:
    fills: TaskGroup
    settings: Settings
    store: InventoryStore
    timer: Callable[[], float]


def cached_loader[K: Hashable, V](
    loader: Callable[[K], Awaitable[V]],
    values: TTLCache[K, V],
    environment: LoaderEnvironment,
) -> CachedLoader[K, V]:
    settings = environment.settings
    return CachedLoader(
        values=values,
        misses=TTLCache(
            maxsize=settings.inventory_cache_versions,
            ttl=settings.missing_version_ttl_seconds,
            timer=environment.timer,
        ),
        loader=loader,
        fills=environment.fills,
        fill_timeout_seconds=settings.fill_timeout_seconds,
    )


def compose_service(
    client: httpx2.AsyncClient, environment: LoaderEnvironment
) -> DocumentationService:
    settings = environment.settings
    parsers = anyio.CapacityLimiter(settings.parse_concurrency)
    source = DocumentationSource(
        client=client,
        downloads=anyio.CapacityLimiter(settings.download_concurrency),
        parsers=parsers,
        settings=settings,
        store=environment.store,
    )
    ttl = settings.cache_ttl_seconds
    timer = environment.timer
    page_values: TTLCache[DocumentationUrl, bytes] = TTLCache(
        settings.page_cache_bytes, ttl, timer=timer, getsizeof=len
    )
    pages = cached_loader(source.fetch, page_values, environment)
    return DocumentationService(
        catalogs=cached_loader(
            source.catalog,
            TTLCache(settings.inventory_cache_versions, ttl, timer=timer),
            environment,
        ),
        sections=cached_loader(
            SectionLoader(pages=pages, parsers=parsers).load,
            TTLCache(settings.section_cache_characters, ttl, timer=timer, getsizeof=len),
            environment,
        ),
        settings=settings,
    )


@dataclass(frozen=True, slots=True, kw_only=True, eq=False)
class ServiceOptions:
    transport: httpx2.AsyncBaseTransport | None = None
    timer: Callable[[], float] = monotonic
    store: InventoryStore = field(default_factory=MemoryInventoryStore)


@asynccontextmanager
async def open_documentation_service(
    settings: Settings, options: ServiceOptions
) -> AsyncGenerator[DocumentationService]:
    async with (
        documentation_http_client(settings, options.transport) as client,
        anyio.create_task_group() as fills,
    ):
        environment = LoaderEnvironment(
            fills=fills, settings=settings, store=options.store, timer=options.timer
        )
        yield compose_service(client, environment)
        fills.cancel_scope.cancel()


@asynccontextmanager
async def build_documentation_service(
    settings: Settings,
    transport: httpx2.AsyncBaseTransport | None = None,
    timer: Callable[[], float] = monotonic,
) -> AsyncGenerator[DocumentationService]:
    options = ServiceOptions(transport=transport, timer=timer)
    async with open_documentation_service(settings, options) as service:
        yield service

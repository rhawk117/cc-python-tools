"""The edge that builds the HTTP client, task group, caches and loaders behind the service."""

from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from time import monotonic
from typing import TYPE_CHECKING

import anyio
from cachetools import TTLCache

from python_docs_mcp.disk_cache import NullInventoryStore
from python_docs_mcp.progress import ProgressBoard
from python_docs_mcp.repository import DocumentationSource, documentation_http_client
from python_docs_mcp.services import CatalogLoader, DocumentationService, SectionLoader
from python_docs_mcp.store import CachedLoader

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Awaitable, Callable, Hashable

    import httpx2
    from anyio.abc import TaskGroup

    from python_docs_mcp.disk_cache import InventoryStore
    from python_docs_mcp.domain import DocumentationUrl, PythonVersion
    from python_docs_mcp.matching import SymbolCatalog
    from python_docs_mcp.settings import Settings


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


def catalog_cache(environment: LoaderEnvironment) -> TTLCache[PythonVersion, SymbolCatalog]:
    settings = environment.settings
    return TTLCache(
        settings.inventory_cache_versions, settings.cache_ttl_seconds, timer=environment.timer
    )


def page_cache(environment: LoaderEnvironment) -> TTLCache[DocumentationUrl, bytes]:
    settings = environment.settings
    return TTLCache(
        settings.page_cache_bytes,
        settings.cache_ttl_seconds,
        timer=environment.timer,
        getsizeof=len,
    )


def section_cache(environment: LoaderEnvironment) -> TTLCache[DocumentationUrl, str]:
    settings = environment.settings
    return TTLCache(
        settings.section_cache_characters,
        settings.cache_ttl_seconds,
        timer=environment.timer,
        getsizeof=len,
    )


def documentation_source(
    client: httpx2.AsyncClient, environment: LoaderEnvironment, board: ProgressBoard
) -> DocumentationSource:
    settings = environment.settings
    return DocumentationSource(
        client=client,
        downloads=anyio.CapacityLimiter(settings.download_concurrency),
        settings=settings,
        board=board,
    )


def compose_service(
    client: httpx2.AsyncClient, environment: LoaderEnvironment
) -> DocumentationService:
    board = ProgressBoard()
    source = documentation_source(client, environment, board)
    pages = cached_loader(source.fetch, page_cache(environment), environment)
    parsers = anyio.CapacityLimiter(environment.settings.parse_concurrency)
    loader = CatalogLoader(
        source=source, store=environment.store, parsers=parsers, settings=environment.settings
    )
    sections = SectionLoader(pages=pages, parsers=parsers)
    return DocumentationService(
        catalogs=cached_loader(loader.catalog, catalog_cache(environment), environment),
        sections=cached_loader(sections.load, section_cache(environment), environment),
        settings=environment.settings,
        loader=loader,
        board=board,
    )


@dataclass(frozen=True, slots=True, kw_only=True, eq=False)
class ServiceOptions:
    transport: httpx2.AsyncBaseTransport | None = None
    timer: Callable[[], float] = monotonic
    store: InventoryStore = field(default_factory=NullInventoryStore)


@asynccontextmanager
async def open_documentation_service(
    settings: Settings, options: ServiceOptions
) -> AsyncGenerator[DocumentationService]:
    client = documentation_http_client(settings, options.transport)
    try:
        async with anyio.create_task_group() as fills:
            environment = LoaderEnvironment(
                fills=fills, settings=settings, store=options.store, timer=options.timer
            )
            yield compose_service(client, environment)
            fills.cancel_scope.cancel()
    finally:
        with anyio.move_on_after(settings.shutdown_timeout_seconds, shield=True):
            await client.aclose()

"""Build the caches, loaders and documentation service from settings and a client."""

from dataclasses import dataclass
from typing import TYPE_CHECKING

import anyio
from cachetools import TTLCache

from python_docs_mcp.adapters.progress import ProgressBoard
from python_docs_mcp.services.documentation_service import (
    CatalogLoader,
    DocumentationService,
    SectionLoader,
)
from python_docs_mcp.stores.repository import DocumentationSource
from python_docs_mcp.stores.store import CachedLoader

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Hashable

    import httpx2
    from anyio.abc import TaskGroup

    from python_docs_mcp.schemas.domain_types import DocumentationUrl, PythonVersion
    from python_docs_mcp.schemas.settings import Settings
    from python_docs_mcp.services.matching import SymbolCatalog
    from python_docs_mcp.stores.disk_cache import InventoryStore


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

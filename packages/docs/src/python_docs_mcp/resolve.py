"""Build the caches, loaders and documentation service from settings and a client."""

from contextlib import ExitStack
from dataclasses import dataclass
from typing import TYPE_CHECKING

import anyio
from cachetools import TTLCache
from python_agent_tools_core.exception import PythonAgentToolsError

from python_docs_mcp.adapters.progress import ProgressBoard
from python_docs_mcp.services.documentation_service import (
    CatalogLoader,
    DocumentationService,
    SectionLoader,
    call_deadline,
)
from python_docs_mcp.stores.repository import DocumentationSource
from python_docs_mcp.stores.store import CachedLoader

if TYPE_CHECKING:
    from collections.abc import Hashable, Mapping
    from contextlib import AbstractContextManager
    from types import TracebackType

    import httpx2
    from anyio.abc import TaskGroup
    from mcp.server.mcpserver.exceptions import MCPServerError
    from python_agent_tools_core.version import PythonVersion

    from python_docs_mcp.core.interfaces import ClockInterface, Loader
    from python_docs_mcp.schemas.domain_types import DocumentationUrl
    from python_docs_mcp.schemas.settings import Settings
    from python_docs_mcp.services.matching import SymbolCatalog
    from python_docs_mcp.stores.disk_cache import InventoryStore


@dataclass(frozen=True, slots=True, kw_only=True, eq=False)
class LoaderEnvironment:
    fills: TaskGroup
    settings: Settings
    store: InventoryStore
    clock: ClockInterface


@dataclass(frozen=True, slots=True)
class PageFetcher:
    source: DocumentationSource

    async def load(self, url: DocumentationUrl) -> bytes:
        return await self.source.fetch(url)


@dataclass(frozen=True, slots=True)
class CatalogFetcher:
    loader: CatalogLoader

    async def load(self, version: PythonVersion) -> SymbolCatalog:
        return await self.loader.catalog(version)


def cached_loader[K: Hashable, V](
    loader: Loader[K, V],
    values: TTLCache[K, V],
    environment: LoaderEnvironment,
) -> CachedLoader[K, V]:
    settings = environment.settings
    return CachedLoader(
        values=values,
        misses=TTLCache(
            maxsize=settings.inventory_cache_versions,
            ttl=settings.missing_version_ttl_seconds,
            timer=environment.clock.monotonic,
        ),
        loader=loader,
        fills=environment.fills,
        fill_timeout_seconds=settings.fill_timeout_seconds,
    )


def catalog_cache(environment: LoaderEnvironment) -> TTLCache[PythonVersion, SymbolCatalog]:
    settings = environment.settings
    return TTLCache(
        settings.inventory_cache_versions,
        settings.cache_ttl_seconds,
        timer=environment.clock.monotonic,
    )


def page_cache(environment: LoaderEnvironment) -> TTLCache[DocumentationUrl, bytes]:
    settings = environment.settings
    return TTLCache(
        settings.page_cache_bytes,
        settings.cache_ttl_seconds,
        timer=environment.clock.monotonic,
        getsizeof=len,
    )


def section_cache(environment: LoaderEnvironment) -> TTLCache[DocumentationUrl, str]:
    settings = environment.settings
    return TTLCache(
        settings.section_cache_characters,
        settings.cache_ttl_seconds,
        timer=environment.clock.monotonic,
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
    pages = cached_loader(PageFetcher(source), page_cache(environment), environment)
    parsers = anyio.CapacityLimiter(environment.settings.parse_concurrency)
    loader = CatalogLoader(
        source=source, store=environment.store, parsers=parsers, settings=environment.settings
    )
    sections = SectionLoader(pages=pages, parsers=parsers)
    return DocumentationService(
        catalogs=cached_loader(CatalogFetcher(loader), catalog_cache(environment), environment),
        sections=cached_loader(sections, section_cache(environment), environment),
        settings=environment.settings,
        loader=loader,
        board=board,
    )


@dataclass(frozen=True, slots=True, kw_only=True)
class ErrorTranslator:
    raises: type[MCPServerError]

    def __enter__(self) -> None:
        return None

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if isinstance(exc, PythonAgentToolsError):
            raise self.raises(str(exc)) from exc


@dataclass(frozen=True, slots=True, kw_only=True)
class MCPCallStack:
    translator: AbstractContextManager[None]
    deadline_seconds: float
    environment: Mapping[str, str]

    def create_callstack(self, *extra_caller_handlers: AbstractContextManager[None]) -> ExitStack:
        stack = ExitStack()
        stack.enter_context(self.translator)
        stack.enter_context(call_deadline(self.deadline_seconds))
        for handler in extra_caller_handlers:
            stack.enter_context(handler)

        return stack

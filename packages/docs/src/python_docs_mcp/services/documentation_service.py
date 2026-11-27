"""The documentation service the tools use."""

from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING

import anyio

from python_docs_mcp.adapters.progress import SilentReporter
from python_docs_mcp.core.exception import CallDeadlineExceededError
from python_docs_mcp.services.extraction import extract_markdown
from python_docs_mcp.services.inventory import parse_inventory
from python_docs_mcp.services.matching import catalog_symbols
from python_docs_mcp.stores.store import FillSucceeded

if TYPE_CHECKING:
    from collections.abc import Generator

    from python_agent_tools_core.version import PythonVersion

    from python_docs_mcp.adapters.progress import ProgressBoard
    from python_docs_mcp.core.interfaces import InventoryStore, ProgressReporter
    from python_docs_mcp.schemas.domain_types import DocumentationUrl, Symbol
    from python_docs_mcp.schemas.settings import Settings
    from python_docs_mcp.services.matching import SymbolCatalog
    from python_docs_mcp.stores.repository import DocumentationSource
    from python_docs_mcp.stores.store import CachedLoader


@contextmanager
def call_deadline(seconds: float) -> Generator[None]:
    try:
        with anyio.fail_after(seconds):
            yield
    except TimeoutError as error:
        raise CallDeadlineExceededError(seconds) from error


def build_catalog(content: bytes, version: PythonVersion, settings: Settings) -> SymbolCatalog:
    return catalog_symbols(parse_inventory(content, version, settings))


@dataclass(frozen=True, slots=True, kw_only=True, eq=False)
class CatalogLoader:
    source: DocumentationSource
    store: InventoryStore
    parsers: anyio.CapacityLimiter
    settings: Settings

    async def inventory(self, version: PythonVersion) -> bytes:
        if (stored := await anyio.to_thread.run_sync(self.store.read, version)) is not None:
            return stored

        content = await self.source.fetch_inventory(version)
        await anyio.to_thread.run_sync(self.store.write, version, content)
        return content

    async def parse(self, content: bytes, version: PythonVersion) -> SymbolCatalog:
        return await anyio.to_thread.run_sync(
            build_catalog, content, version, self.settings, limiter=self.parsers
        )

    async def catalog(self, version: PythonVersion) -> SymbolCatalog:
        return await self.parse(await self.inventory(version), version)


@dataclass(frozen=True, slots=True, kw_only=True, eq=False)
class SectionLoader:
    pages: CachedLoader[DocumentationUrl, bytes]
    parsers: anyio.CapacityLimiter

    async def load(self, url: DocumentationUrl) -> str:
        content = await self.pages.get(url.page_url)
        return await anyio.to_thread.run_sync(extract_markdown, content, url, limiter=self.parsers)


@dataclass(frozen=True, slots=True, kw_only=True, eq=False)
class DocumentationService:
    catalogs: CachedLoader[PythonVersion, SymbolCatalog]
    sections: CachedLoader[DocumentationUrl, str]
    settings: Settings
    loader: CatalogLoader
    board: ProgressBoard
    reporter: ProgressReporter = field(default_factory=SilentReporter)

    def reporting_to(self, reporter: ProgressReporter) -> DocumentationService:
        return replace(self, reporter=reporter)

    async def catalog(self, version: PythonVersion) -> SymbolCatalog:
        with self.board.watch(version, self.reporter):
            return await self.catalogs.get(version)

    async def stored_catalog(self, version: PythonVersion) -> SymbolCatalog | None:
        if (catalog := self.catalogs.peek(version)) is not None:
            return catalog

        stored = await anyio.to_thread.run_sync(self.loader.store.read, version)
        if stored is None:
            return None

        catalog = await self.loader.parse(stored, version)
        self.catalogs.remember(version, FillSucceeded(catalog))
        return catalog

    async def section(self, symbol: Symbol) -> str:
        return await self.sections.get(symbol.source_url)

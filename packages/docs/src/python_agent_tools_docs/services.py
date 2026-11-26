"""The documentation service the tools use."""

from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING

import anyio

from python_agent_tools_docs.errors import CallDeadlineExceededError
from python_agent_tools_docs.progress import SilentReporter

if TYPE_CHECKING:
    from collections.abc import Generator

    from python_agent_tools_docs.disk_cache import InventoryStore
    from python_agent_tools_docs.domain import DocumentationUrl, PythonVersion, Symbol
    from python_agent_tools_docs.matching import SymbolCatalog
    from python_agent_tools_docs.progress import ProgressBoard, ProgressReporter
    from python_agent_tools_docs.settings import Settings
    from python_agent_tools_docs.store import CachedLoader


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
    store: InventoryStore
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

        if not await anyio.to_thread.run_sync(self.store.contains, version):
            return None

        return await self.catalogs.get(version)

    async def section(self, symbol: Symbol) -> str:
        return await self.sections.get(symbol.source_url)

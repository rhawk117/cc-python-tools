"""The catalog and section lookups the documentation tools depend on."""

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from python_docs_mcp.matching import SymbolCatalog
    from python_docs_mcp.schemas.domain_types import PythonVersion, Symbol
    from python_docs_mcp.schemas.settings import Settings


@runtime_checkable
class DocumentationCatalogs(Protocol):
    @property
    def settings(self) -> Settings: ...

    async def catalog(self, version: PythonVersion) -> SymbolCatalog: ...

    async def section(self, symbol: Symbol) -> str: ...

"""The catalog and section lookups the documentation tools depend on."""

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from python_agent_tools_docs.domain import PythonVersion, Symbol
    from python_agent_tools_docs.matching import SymbolCatalog
    from python_agent_tools_docs.settings import Settings


@runtime_checkable
class DocumentationCatalogs(Protocol):
    @property
    def settings(self) -> Settings: ...

    async def catalog(self, version: PythonVersion) -> SymbolCatalog: ...

    async def section(self, symbol: Symbol) -> str: ...

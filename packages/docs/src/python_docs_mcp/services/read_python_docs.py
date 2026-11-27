"""Request schema, rendered page and use case for read_python_docs."""

from dataclasses import dataclass
from typing import TYPE_CHECKING

from python_agent_tools_core.version import PythonVersion

from python_docs_mcp.core.exception import OffsetOutOfRangeError, UnknownSymbolError
from python_docs_mcp.schemas import arguments
from python_docs_mcp.schemas import base as schemas
from python_docs_mcp.services.fences import fence_before, scan_fence
from python_docs_mcp.services.matching import create_match_options, match_symbols

if TYPE_CHECKING:
    from python_docs_mcp.schemas.domain_types import Symbol
    from python_docs_mcp.schemas.settings import Settings
    from python_docs_mcp.services.catalogs import DocumentationCatalogs
    from python_docs_mcp.services.matching import SymbolCatalog

TOOL_CONTINUATION = 'call read_python_docs again with offset='


class ReadRequest(schemas.Model):
    version: schemas.VersionText
    symbol: arguments.SymbolName
    offset: arguments.PageOffset
    max_chars: arguments.PageCharacters


@dataclass(frozen=True, slots=True, kw_only=True)
class SectionPage:
    symbol: Symbol
    documentation_version: str
    text: str
    offset: int
    max_chars: int
    continuation: str = TOOL_CONTINUATION

    @property
    def end(self) -> int:
        limit = self.offset + self.max_chars
        if limit >= len(self.text):
            return len(self.text)

        newline = self.text.rfind('\n', self.offset, limit)
        return newline + 1 if newline >= 0 else limit

    @property
    def header(self) -> str:
        symbol = self.symbol
        return (
            f'{symbol.name} ({symbol.kind}) | Python {self.documentation_version}'
            f' documentation | {symbol.source_url.text}'
        )

    @property
    def footer(self) -> str:
        total = len(self.text)
        if self.end < total:
            return f'More: {self.continuation}{self.end} ({self.end} of {total} characters shown).'
        return f'End of section ({total} characters).'

    @property
    def excerpt(self) -> str:
        return self.text[self.offset : self.end]

    @property
    def opening(self) -> str:
        fence = fence_before(self.text, self.offset)
        return f'{fence.opening}\n' if fence else ''

    @property
    def closing(self) -> str:
        fence = scan_fence(self.excerpt, fence_before(self.text, self.offset))
        if fence is None:
            return ''

        separator = '\n' if self.excerpt and not self.excerpt.endswith('\n') else ''
        return f'{separator}{fence.closing}'

    @property
    def body(self) -> str:
        return f'{self.opening}{self.excerpt}{self.closing}'

    def render(self) -> str:
        return f'{self.header}\n\n{self.body}\n\n{self.footer}'


def suggested_names(catalog: SymbolCatalog, symbol: str, settings: Settings) -> list[str]:
    options = create_match_options(settings)
    result = match_symbols(catalog, symbol, options)
    return [match.name for match in result.matches[: settings.suggestion_count]]


def find_catalog_symbol(catalog: SymbolCatalog, name: str, settings: Settings) -> Symbol:
    symbol = catalog.index.symbols.get(name)
    if symbol is None:
        raise UnknownSymbolError(name, suggested_names(catalog, name, settings))
    return symbol


def get_offset_problem(offset: int, text: str) -> OffsetOutOfRangeError | None:
    if offset and offset >= len(text):
        return OffsetOutOfRangeError(offset, len(text))

    return None


async def run(
    service: DocumentationCatalogs,
    request: ReadRequest,
    continuation: str = TOOL_CONTINUATION,
) -> str:
    version = PythonVersion(text=request.version)
    catalog = await service.catalog(version)
    symbol = find_catalog_symbol(catalog, request.symbol, service.settings)
    text = await service.section(symbol)
    if problem := get_offset_problem(request.offset, text):
        raise problem

    page = SectionPage(
        symbol=symbol,
        documentation_version=catalog.index.documentation_version,
        text=text,
        offset=request.offset,
        max_chars=request.max_chars,
        continuation=continuation,
    )
    return page.render()

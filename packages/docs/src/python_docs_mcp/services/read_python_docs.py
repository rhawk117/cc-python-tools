"""Request schema, rendered page and use case for read_python_docs."""

from dataclasses import dataclass
from typing import TYPE_CHECKING, Annotated

from pydantic import Field, NonNegativeInt, StringConstraints
from python_agent_tools_core.version import PythonVersion

from python_docs_mcp.core.exception import OffsetOutOfRangeError, UnknownSymbolError
from python_docs_mcp.schemas import base as schemas
from python_docs_mcp.services.fences import fence_before, scan_fence
from python_docs_mcp.services.matching import MatchOptions, match_symbols

if TYPE_CHECKING:
    from python_docs_mcp.schemas.domain_types import Symbol
    from python_docs_mcp.schemas.settings import Settings
    from python_docs_mcp.services.matching import SymbolCatalog
    from python_docs_mcp.stores.catalogs import DocumentationCatalogs

DEFAULT_PAGE_CHARACTERS = 8_000

SymbolName = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=300),
    Field(description='Exact symbol name from search_python_docs, such as os.path.join.'),
]
PageOffset = Annotated[
    NonNegativeInt,
    Field(description='Character offset to continue from, as given by a page footer.'),
]
PageCharacters = Annotated[
    int,
    Field(ge=500, le=12_000, description='Maximum documentation characters to return.'),
]


class ReadRequest(schemas.Model):
    version: schemas.VersionText
    symbol: SymbolName
    offset: PageOffset
    max_chars: PageCharacters


@dataclass(frozen=True, slots=True, kw_only=True)
class SectionPage:
    symbol: Symbol
    documentation_version: str
    text: str
    offset: int
    max_chars: int

    @property
    def end(self) -> int:
        return min(self.offset + self.max_chars, len(self.text))

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
            return (
                f'More: call read_python_docs again with offset={self.end}'
                f' ({self.end} of {total} characters shown).'
            )
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
    options = MatchOptions(cutoff=settings.fuzzy_score_cutoff, limit=settings.fuzzy_match_limit)
    result = match_symbols(catalog, symbol, options)
    return [match.name for match in result.matches[: settings.suggestion_count]]


def find_catalog_symbol(catalog: SymbolCatalog, name: str, settings: Settings) -> Symbol:
    symbol = catalog.index.symbols.get(name)
    if symbol is None:
        raise UnknownSymbolError(name, suggested_names(catalog, name, settings))
    return symbol


async def find_symbol(service: DocumentationCatalogs, version: PythonVersion, name: str) -> Symbol:
    catalog = await service.catalog(version)
    return find_catalog_symbol(catalog, name, service.settings)


async def run(service: DocumentationCatalogs, request: ReadRequest) -> str:
    version = PythonVersion(text=request.version)
    catalog = await service.catalog(version)
    symbol = find_catalog_symbol(catalog, request.symbol, service.settings)
    text = await service.section(symbol)
    if request.offset and request.offset >= len(text):
        raise OffsetOutOfRangeError(request.offset, len(text))
    page = SectionPage(
        symbol=symbol,
        documentation_version=catalog.index.documentation_version,
        text=text,
        offset=request.offset,
        max_chars=request.max_chars,
    )
    return page.render()

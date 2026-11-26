"""Request schema, rendered page and use case for read_python_docs."""

from dataclasses import dataclass
from typing import TYPE_CHECKING, Annotated

from pydantic import Field, NonNegativeInt, StringConstraints

from python_agent_tools_docs import schemas
from python_agent_tools_docs.domain import PythonVersion
from python_agent_tools_docs.errors import OffsetOutOfRangeError, UnknownSymbolError
from python_agent_tools_docs.matching import match_symbols

if TYPE_CHECKING:
    from python_agent_tools_docs.catalogs import DocumentationCatalogs
    from python_agent_tools_docs.domain import Symbol
    from python_agent_tools_docs.matching import SymbolCatalog
    from python_agent_tools_docs.settings import Settings

DEFAULT_PAGE_CHARACTERS = 8_000

type SymbolName = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=300),
    Field(description='Exact symbol name from search_python_docs, such as os.path.join.'),
]
type PageOffset = Annotated[
    NonNegativeInt,
    Field(description='Character offset to continue from, as given by a page footer.'),
]
type PageCharacters = Annotated[
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

    def render(self) -> str:
        return '\n\n'.join((self.header, self.text[self.offset : self.end], self.footer))


def suggested_names(catalog: SymbolCatalog, symbol: str, settings: Settings) -> list[str]:
    matches = match_symbols(catalog, symbol, settings.fuzzy_score_cutoff)
    return [match.name for match in matches[: settings.suggestion_count]]


async def find_symbol(service: DocumentationCatalogs, version: PythonVersion, name: str) -> Symbol:
    catalog = await service.catalog(version)
    symbol = catalog.index.symbols.get(name)
    if symbol is None:
        raise UnknownSymbolError(name, suggested_names(catalog, name, service.settings))
    return symbol


async def run(service: DocumentationCatalogs, request: ReadRequest) -> str:
    version = PythonVersion(text=request.version)
    symbol = await find_symbol(service, version, request.symbol)
    catalog = await service.catalog(version)
    text = await service.section(symbol)
    if request.offset > len(text):
        raise OffsetOutOfRangeError(request.offset, len(text))
    page = SectionPage(
        symbol=symbol,
        documentation_version=catalog.index.documentation_version,
        text=text,
        offset=request.offset,
        max_chars=request.max_chars,
    )
    return page.render()

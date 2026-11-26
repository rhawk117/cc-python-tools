from dataclasses import dataclass
from typing import TYPE_CHECKING

import pytest
from python_docs_mcp.core.exception import OffsetOutOfRangeError, UnknownSymbolError
from python_docs_mcp.schemas.domain_types import DocumentationUrl, Symbol, SymbolIndex
from python_docs_mcp.schemas.settings import Settings
from python_docs_mcp.services.matching import catalog_symbols
from python_docs_mcp.services.read_python_docs import ReadRequest, run

if TYPE_CHECKING:
    from python_docs_mcp.schemas.domain_types import PythonVersion
    from python_docs_mcp.services.matching import SymbolCatalog

SOURCE_URL = DocumentationUrl(text='https://docs.python.org/3.13/library/os.path.html#os.path.join')
JOIN = Symbol(name='os.path.join', kind='function', source_url=SOURCE_URL)
SECTION_TEXT = 'Join one or more path segments.'


@dataclass(frozen=True, slots=True, kw_only=True)
class FakeCatalogs:
    catalogs: dict[str, SymbolCatalog]
    sections: dict[str, str]
    settings: Settings

    async def catalog(self, version: PythonVersion) -> SymbolCatalog:
        return self.catalogs[version.text]

    async def section(self, symbol: Symbol) -> str:
        return self.sections[symbol.name]


def read_request(symbol: str, offset: int = 0) -> ReadRequest:
    return ReadRequest(version='3.13', symbol=symbol, offset=offset, max_chars=8_000)


class TestRun:
    @pytest.fixture
    def catalogs(self) -> FakeCatalogs:
        index = SymbolIndex(documentation_version='3.13', symbols={JOIN.name: JOIN})
        return FakeCatalogs(
            catalogs={'3.13': catalog_symbols(index)},
            sections={JOIN.name: SECTION_TEXT},
            settings=Settings(),
        )

    async def test_a_known_symbol_renders_its_section(self, catalogs: FakeCatalogs) -> None:
        page = await run(catalogs, read_request('os.path.join'))
        assert page.splitlines()[0].startswith('os.path.join (function) | Python 3.13')
        assert SECTION_TEXT in page
        assert page.endswith(f'End of section ({len(SECTION_TEXT)} characters).')

    async def test_an_unknown_symbol_raises_with_suggestions(self, catalogs: FakeCatalogs) -> None:
        with pytest.raises(UnknownSymbolError):
            await run(catalogs, read_request('os.path.joinn'))

    async def test_an_offset_at_the_section_length_renders_the_end_of_the_section(
        self, catalogs: FakeCatalogs
    ) -> None:
        page = await run(catalogs, read_request('os.path.join', offset=len(SECTION_TEXT)))
        assert page.endswith(f'End of section ({len(SECTION_TEXT)} characters).')

    async def test_an_offset_past_the_section_length_raises(self, catalogs: FakeCatalogs) -> None:
        with pytest.raises(OffsetOutOfRangeError):
            await run(catalogs, read_request('os.path.join', offset=len(SECTION_TEXT) + 1))

from dataclasses import dataclass
from typing import TYPE_CHECKING

import pytest
from python_agent_tools_docs.domain import DocumentationUrl, Symbol, SymbolIndex
from python_agent_tools_docs.errors import UnknownSymbolError
from python_agent_tools_docs.matching import catalog_symbols
from python_agent_tools_docs.read_python_docs import ReadRequest, run
from python_agent_tools_docs.settings import Settings

if TYPE_CHECKING:
    from python_agent_tools_docs.domain import PythonVersion
    from python_agent_tools_docs.matching import SymbolCatalog

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


@pytest.fixture
def catalogs() -> FakeCatalogs:
    index = SymbolIndex(documentation_version='3.13', symbols={JOIN.name: JOIN})
    return FakeCatalogs(
        catalogs={'3.13': catalog_symbols(index)},
        sections={JOIN.name: SECTION_TEXT},
        settings=Settings(),
    )


def read_request(symbol: str) -> ReadRequest:
    return ReadRequest(version='3.13', symbol=symbol, offset=0, max_chars=8_000)


class TestRun:
    async def test_a_known_symbol_renders_its_section(self, catalogs: FakeCatalogs) -> None:
        page = await run(catalogs, read_request('os.path.join'))
        assert page.splitlines()[0].startswith('os.path.join (function) | Python 3.13')
        assert SECTION_TEXT in page
        assert page.endswith(f'End of section ({len(SECTION_TEXT)} characters).')

    async def test_an_unknown_symbol_raises_with_suggestions(self, catalogs: FakeCatalogs) -> None:
        with pytest.raises(UnknownSymbolError):
            await run(catalogs, read_request('os.path.joinn'))

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING

from hypothesis import given
from hypothesis import strategies as st
from python_docs_mcp.schemas.domain_types import DocumentationUrl, Symbol, SymbolIndex
from python_docs_mcp.schemas.settings import Settings
from python_docs_mcp.services.matching import catalog_symbols
from python_docs_mcp.services.search_python_docs import SearchRequest, run

if TYPE_CHECKING:
    from python_agent_tools_core.version import PythonVersion
    from python_docs_mcp.services.matching import SymbolCatalog
    from python_docs_mcp.services.search_python_docs import SearchResult

SOURCE_URL = DocumentationUrl(text='https://docs.python.org/3.13/library/x.html')
UNRELATED_QUERY = 'zzqx'


@dataclass(frozen=True, slots=True, kw_only=True)
class FakeCatalogs:
    catalogs: dict[str, SymbolCatalog]
    settings: Settings

    async def catalog(self, version: PythonVersion) -> SymbolCatalog:
        return self.catalogs[version.text]

    async def section(self, symbol: Symbol) -> str:
        return symbol.name


def create_catalogs(size: int, cap: int) -> FakeCatalogs:
    names = [f'pkg.name{index}' for index in range(size)]
    symbols = {name: Symbol(name=name, kind='py:function', source_url=SOURCE_URL) for name in names}
    index = SymbolIndex(documentation_version='3.13', symbols=symbols)
    settings = Settings(fuzzy_score_cutoff=0, fuzzy_match_limit=cap)
    return FakeCatalogs(catalogs={'3.13': catalog_symbols(index)}, settings=settings)


class TestRun:
    sizes = st.integers(min_value=0, max_value=30)
    caps = st.integers(min_value=1, max_value=30)
    limits = st.integers(min_value=1, max_value=30)

    def search(self, size: int, cap: int, limit: int) -> SearchResult:
        request = SearchRequest(version='3.13', query=UNRELATED_QUERY, limit=limit)
        return asyncio.run(run(create_catalogs(size, cap), request))

    @given(size=sizes, cap=caps, limit=limits)
    def test_total_matches_is_capped_by_the_fuzzy_match_limit(
        self, size: int, cap: int, limit: int
    ) -> None:
        assert self.search(size, cap, limit).total_matches == min(size, cap)

    @given(size=sizes, cap=caps, limit=limits)
    def test_truncated_is_true_exactly_when_matches_outnumber_the_cap(
        self, size: int, cap: int, limit: int
    ) -> None:
        assert self.search(size, cap, limit).truncated == (size > cap)

    @given(size=sizes, cap=caps, limit=limits)
    def test_returned_matches_never_exceed_the_request_limit(
        self, size: int, cap: int, limit: int
    ) -> None:
        result = self.search(size, cap, limit)
        assert len(result.matches) == min(result.total_matches, limit)

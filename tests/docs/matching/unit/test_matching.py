"""Layered matching: precise tiers first, labeled approximations only as a fallback."""

from typing import TYPE_CHECKING

import pytest
from python_agent_tools_core.version import create_python_version
from python_docs_mcp.adapters.inventory import parse_inventory
from python_docs_mcp.schemas.settings import Settings
from python_docs_mcp.services.matching import (
    MatchTier,
    catalog_symbols,
    match_symbols,
)

from tests.docs.support.samples import DOCS_VERSION, inventory_bytes

if TYPE_CHECKING:
    from python_docs_mcp.services.matching import (
        SymbolCatalog,
    )


@pytest.fixture
def catalog() -> SymbolCatalog:
    version = create_python_version(DOCS_VERSION)
    assert not isinstance(version, Exception)
    return catalog_symbols(parse_inventory(inventory_bytes(), version, Settings()))


class TestMatchSymbols:
    cutoff = 80.0

    def first_match(self, catalog: SymbolCatalog, query: str) -> tuple[str, MatchTier]:
        match = match_symbols(catalog, query, self.cutoff)[0]
        return match.name, match.match

    @pytest.mark.parametrize(
        ('query', 'expected'),
        [
            pytest.param('os.path.join', ('os.path.join', MatchTier.EXACT), id='exact'),
            pytest.param('OS.PATH.JOIN', ('os.path.join', MatchTier.EXACT), id='case'),
            pytest.param('path join', ('os.path.join', MatchTier.PREFIX), id='segments'),
            pytest.param('getattr', ('object.__getattr__', MatchTier.PREFIX), id='dunder'),
            pytest.param(
                'ordered dict', ('collections.OrderedDict', MatchTier.PREFIX), id='joined'
            ),
            pytest.param('os.path.joinpath', ('os.path.join', MatchTier.APPROXIMATE), id='scoped'),
            pytest.param(
                'defaultdcit',
                ('collections.defaultdict', MatchTier.APPROXIMATE),
                id='misspelled',
            ),
        ],
    )
    def test_ranks_the_intended_symbol_first(
        self, catalog: SymbolCatalog, query: str, expected: tuple[str, MatchTier]
    ) -> None:
        assert self.first_match(catalog, query) == expected

    def test_named_tuple_finds_both_spellings(self, catalog: SymbolCatalog) -> None:
        names = {match.name for match in match_symbols(catalog, 'named tuple', self.cutoff)}
        assert names == {'collections.namedtuple', 'typing.NamedTuple'}

    def test_approximations_never_mix_with_precise_hits(self, catalog: SymbolCatalog) -> None:
        tiers = {match.match for match in match_symbols(catalog, 'json', self.cutoff)}
        assert MatchTier.APPROXIMATE not in tiers

    @pytest.mark.parametrize(
        'query',
        [pytest.param('zzqx', id='unrelated'), pytest.param('._.', id='separators-only')],
    )
    def test_queries_without_a_plausible_match_find_nothing(
        self, catalog: SymbolCatalog, query: str
    ) -> None:
        assert match_symbols(catalog, query, self.cutoff) == []

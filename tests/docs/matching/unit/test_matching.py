"""Layered matching: precise tiers first, labeled approximations only as a fallback."""

from typing import TYPE_CHECKING

import pytest
from hypothesis import given
from hypothesis import strategies as st
from python_agent_tools_core.version import create_python_version
from python_docs_mcp.schemas.domain_types import DocumentationUrl, Symbol, SymbolIndex
from python_docs_mcp.schemas.settings import Settings
from python_docs_mcp.services.inventory import parse_inventory
from python_docs_mcp.services.matching import (
    MatchOptions,
    MatchTier,
    catalog_symbols,
    create_match_options,
    match_symbols,
    member_text,
    scoped_names,
)

from tests.docs.support.samples import DOCS_VERSION, inventory_bytes

if TYPE_CHECKING:
    from python_docs_mcp.services.matching import MatchResult, SymbolCatalog


@pytest.fixture
def catalog() -> SymbolCatalog:
    version = create_python_version(DOCS_VERSION)
    assert not isinstance(version, Exception)
    return catalog_symbols(parse_inventory(inventory_bytes(), version, Settings()))


def catalog_of_names(names: list[str]) -> SymbolCatalog:
    url = DocumentationUrl(text='https://docs.python.org/3.13/library/x.html')
    symbols = {name: Symbol(name=name, kind='py:function', source_url=url) for name in names}
    return catalog_symbols(SymbolIndex(documentation_version='3.13', symbols=symbols))


class TestMatchSymbols:
    options = create_match_options(Settings())

    def first_match(self, catalog: SymbolCatalog, query: str) -> tuple[str, MatchTier]:
        match = match_symbols(catalog, query, self.options).matches[0]
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
        names = {
            match.name for match in match_symbols(catalog, 'named tuple', self.options).matches
        }
        assert names == {'collections.namedtuple', 'typing.NamedTuple'}

    def test_approximations_never_mix_with_precise_hits(self, catalog: SymbolCatalog) -> None:
        tiers = {match.match for match in match_symbols(catalog, 'json', self.options).matches}
        assert MatchTier.APPROXIMATE not in tiers

    @pytest.mark.parametrize(
        'query',
        [pytest.param('zzqx', id='unrelated'), pytest.param('._.', id='separators-only')],
    )
    def test_queries_without_a_plausible_match_find_nothing(
        self, catalog: SymbolCatalog, query: str
    ) -> None:
        assert match_symbols(catalog, query, self.options).matches == []


class TestMatchLimit:
    unrelated_query = 'zzqx'
    sizes = st.integers(min_value=0, max_value=30)
    caps = st.integers(min_value=1, max_value=30)

    def match_all(self, size: int, cap: int) -> MatchResult:
        catalog = catalog_of_names([f'pkg.name{index}' for index in range(size)])
        options = MatchOptions(cutoff=0, limit=cap)
        return match_symbols(catalog, self.unrelated_query, options)

    @given(size=sizes, cap=caps)
    def test_matches_never_exceed_the_cap(self, size: int, cap: int) -> None:
        result = self.match_all(size, cap)
        assert len(result.matches) == min(size, cap)

    @given(size=sizes, cap=caps)
    def test_truncated_is_true_exactly_when_matches_outnumber_the_cap(
        self, size: int, cap: int
    ) -> None:
        assert self.match_all(size, cap).truncated == (size > cap)

    def test_exact_name_stays_first_under_a_tiny_cap(self, catalog: SymbolCatalog) -> None:
        result = match_symbols(catalog, 'os.path.join', MatchOptions(cutoff=80, limit=1))
        assert (result.matches[0].name, result.matches[0].match, result.truncated) == (
            'os.path.join',
            MatchTier.EXACT,
            False,
        )


class TestScopedNames:
    options = create_match_options(Settings())
    scopes = st.lists(st.text('abcßŉﬁ', min_size=1, max_size=4), min_size=1, max_size=3)
    members = st.text('abcdef', min_size=2, max_size=6)

    def catalog_of(self, name: str) -> SymbolCatalog:
        url = DocumentationUrl(text='https://docs.python.org/3.13/library/x.html')
        symbol = Symbol(name=name, kind='py:function', source_url=url)
        return catalog_symbols(SymbolIndex(documentation_version='3.13', symbols={name: symbol}))

    @given(scope=scopes, member=members)
    def test_casefold_equivalent_scope_finds_the_same_members(
        self, scope: list[str], member: str
    ) -> None:
        dotted = '.'.join(scope)
        name = f'{dotted}.{member}'
        catalog = self.catalog_of(name)
        original = scoped_names(catalog, name, self.options)
        folded = scoped_names(catalog, f'{dotted.casefold()}.{member}', self.options)
        assert original == folded == [name]

    @given(scope=scopes, member=st.lists(st.text('abcdef', min_size=1, max_size=4), min_size=1))
    def test_member_text_is_the_text_after_the_scope(
        self, scope: list[str], member: list[str]
    ) -> None:
        name = '.'.join([*scope, *member])
        assert member_text(name, '.'.join(scope).casefold()) == '.'.join(member)

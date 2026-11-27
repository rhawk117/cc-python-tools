"""Layered symbol matching: exact and segment-prefix hits, then labeled approximations."""

from dataclasses import dataclass
from enum import StrEnum, auto
from itertools import chain
from typing import TYPE_CHECKING, NamedTuple

from rapidfuzz import fuzz, process, utils

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping

    from python_docs_mcp.schemas.domain_types import DocumentationUrl, SymbolIndex
    from python_docs_mcp.schemas.settings import Settings

SEGMENT_SEPARATORS = str.maketrans('._', '  ')


class MatchTier(StrEnum):
    EXACT = auto()
    PREFIX = auto()
    APPROXIMATE = auto()


@dataclass(frozen=True, slots=True, kw_only=True)
class SymbolMatch:
    name: str
    kind: str
    source_url: DocumentationUrl
    match: MatchTier


@dataclass(frozen=True, slots=True, kw_only=True)
class MatchOptions:
    cutoff: float
    limit: int

    @property
    def probe_limit(self) -> int:
        return self.limit + 1


def create_match_options(settings: Settings) -> MatchOptions:
    return MatchOptions(cutoff=settings.fuzzy_score_cutoff, limit=settings.fuzzy_match_limit)


@dataclass(frozen=True, slots=True, kw_only=True)
class MatchResult:
    matches: list[SymbolMatch]
    truncated: bool = False


class SymbolRank(NamedTuple):
    not_exact_match: bool
    not_prefix_match: bool
    name_length: int
    name: str


@dataclass(frozen=True, slots=True, kw_only=True)
class SymbolCatalog:
    index: SymbolIndex
    segments: Mapping[str, tuple[str, ...]]
    fuzzy_keys: Mapping[str, str]
    namespaces: frozenset[str]


def name_segments(text: str) -> tuple[str, ...]:
    return tuple(text.casefold().translate(SEGMENT_SEPARATORS).split())


def dotted_scopes(name: str) -> Iterator[str]:
    parts = name.casefold().split('.')
    return ('.'.join(parts[:end]) for end in range(len(parts) - 1, 0, -1))


def catalog_symbols(index: SymbolIndex) -> SymbolCatalog:
    names = index.symbols.keys()
    return SymbolCatalog(
        index=index,
        segments={name: name_segments(name) for name in names},
        fuzzy_keys={name: utils.default_process(name) for name in names},
        namespaces=frozenset(chain.from_iterable(map(dotted_scopes, names))),
    )


def rank_name(name: str, *, query: str) -> SymbolRank:
    folded = name.casefold()
    return SymbolRank(folded != query, not folded.startswith(query), len(name), name)


def prefixes_any(token: str, segments: tuple[str, ...]) -> bool:
    return any(segment.startswith(token) for segment in segments)


def covers_query(segments: tuple[str, ...], query_segments: tuple[str, ...]) -> bool:
    return all(prefixes_any(token, segments) for token in query_segments)


def prefix_names(catalog: SymbolCatalog, query_segments: tuple[str, ...]) -> list[str]:
    return [
        name
        for name, segments in catalog.segments.items()
        if covers_query(segments, query_segments)
    ]


def query_forms(query: str) -> list[tuple[str, ...]]:
    segments = name_segments(query)
    if not segments:
        return []
    joined = (''.join(segments),)
    if len(segments) > 1:
        return [segments, joined]
    return [segments]


def precise_names(catalog: SymbolCatalog, query: str) -> list[str]:
    candidates = (prefix_names(catalog, form) for form in query_forms(query))
    found = next((names for names in candidates if names), [])
    folded = query.casefold()
    return sorted(found, key=lambda name: rank_name(name, query=folded))


def fuzzy_names(query: str, choices: Mapping[str, str], options: MatchOptions) -> list[str]:
    results = process.extract(
        utils.default_process(query),
        choices,
        scorer=fuzz.WRatio,
        processor=None,
        limit=options.probe_limit,
        score_cutoff=options.cutoff,
    )
    return [name for _, _, name in results]


def member_text(name: str, scope: str) -> str:
    return '.'.join(name.split('.')[scope.count('.') + 1 :])


def scoped_members(catalog: SymbolCatalog, scope: str) -> dict[str, str]:
    prefix = f'{scope}.'
    members = (
        (name, member_text(name, scope))
        for name in catalog.segments
        if name.casefold().startswith(prefix)
    )
    return {name: utils.default_process(member) for name, member in members if '.' not in member}


def scoped_names(catalog: SymbolCatalog, query: str, options: MatchOptions) -> list[str]:
    scope = next((scope for scope in dotted_scopes(query) if scope in catalog.namespaces), None)
    if scope is None:
        return []
    return fuzzy_names(member_text(query, scope), scoped_members(catalog, scope), options)


def approximate_names(catalog: SymbolCatalog, query: str, options: MatchOptions) -> list[str]:
    return scoped_names(catalog, query, options) or fuzzy_names(query, catalog.fuzzy_keys, options)


def symbol_match(catalog: SymbolCatalog, name: str, tier: MatchTier) -> SymbolMatch:
    symbol = catalog.index.symbols[name]
    return SymbolMatch(name=symbol.name, kind=symbol.kind, source_url=symbol.source_url, match=tier)


def precise_tier(name: str, query: str) -> MatchTier:
    if name.casefold() == query.casefold():
        return MatchTier.EXACT
    return MatchTier.PREFIX


def match_symbols(catalog: SymbolCatalog, query: str, options: MatchOptions) -> MatchResult:
    if names := precise_names(catalog, query):
        precise = [symbol_match(catalog, name, precise_tier(name, query)) for name in names]
        return MatchResult(matches=precise)
    names = approximate_names(catalog, query, options)
    approximate = [
        symbol_match(catalog, name, MatchTier.APPROXIMATE) for name in names[: options.limit]
    ]
    return MatchResult(matches=approximate, truncated=len(names) > options.limit)

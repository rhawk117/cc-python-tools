"""Request and result schemas, and the use case, for search_python_docs."""

from typing import TYPE_CHECKING, Annotated

from pydantic import Field, NonNegativeInt, PositiveInt, StringConstraints

from python_docs_mcp import matching
from python_docs_mcp.schemas import base as schemas
from python_docs_mcp.schemas.domain_types import PythonVersion

if TYPE_CHECKING:
    from python_docs_mcp.catalogs import DocumentationCatalogs
    from python_docs_mcp.matching import SymbolMatch

DEFAULT_SEARCH_LIMIT = 10

type SymbolQuery = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=200),
    Field(
        description=(
            'Symbol name or dotted-name fragments, such as json.loads or ordered dict;'
            ' not a question.'
        )
    ),
]
type TotalMatches = Annotated[
    NonNegativeInt, Field(description='Number of matches before the limit applies.')
]
type SearchLimit = Annotated[
    PositiveInt, Field(le=30, description='Maximum number of matches to return.')
]


class SearchRequest(schemas.Model):
    version: schemas.VersionText
    query: SymbolQuery
    limit: SearchLimit


class SearchMatch(schemas.Model):
    name: str
    kind: str
    source_url: schemas.SourceUrl
    match: matching.MatchTier


class SearchResult(schemas.Model):
    python_version: schemas.VersionText
    documentation_version: str
    query: str
    total_matches: TotalMatches
    matches: list[SearchMatch]


def search_match(match: SymbolMatch) -> SearchMatch:
    return SearchMatch(
        name=match.name, kind=match.kind, source_url=match.source_url.text, match=match.match
    )


async def run(service: DocumentationCatalogs, request: SearchRequest) -> SearchResult:
    catalog = await service.catalog(PythonVersion(text=request.version))
    matches = matching.match_symbols(catalog, request.query, service.settings.fuzzy_score_cutoff)
    return SearchResult(
        python_version=request.version,
        documentation_version=catalog.index.documentation_version,
        query=request.query,
        total_matches=len(matches),
        matches=list(map(search_match, matches[: request.limit])),
    )

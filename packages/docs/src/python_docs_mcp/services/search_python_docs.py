"""Request and result schemas, and the use case, for search_python_docs."""

from typing import TYPE_CHECKING, Annotated

from pydantic import Field, NonNegativeInt
from python_agent_tools_core.version import PythonVersion

from python_docs_mcp.schemas import arguments
from python_docs_mcp.schemas import base as schemas
from python_docs_mcp.services import matching

if TYPE_CHECKING:
    from python_docs_mcp.services.matching import SymbolMatch
    from python_docs_mcp.stores.catalogs import DocumentationCatalogs

TotalMatches = Annotated[
    NonNegativeInt, Field(description='Number of matches before the limit applies.')
]
MatchesTruncated = Annotated[
    bool, Field(description='True when the fuzzy match cap cut the matches short.')
]


class SearchRequest(schemas.Model):
    version: schemas.VersionText
    query: arguments.SymbolQuery
    limit: arguments.SearchLimit = arguments.DEFAULT_SEARCH_LIMIT


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
    truncated: MatchesTruncated
    matches: list[SearchMatch]


def search_match(match: SymbolMatch) -> SearchMatch:
    return SearchMatch(
        name=match.name, kind=match.kind, source_url=match.source_url.text, match=match.match
    )


async def run(service: DocumentationCatalogs, request: SearchRequest) -> SearchResult:
    catalog = await service.catalog(PythonVersion(text=request.version))
    options = matching.create_match_options(service.settings)
    result = matching.match_symbols(catalog, request.query, options)
    matches = result.matches
    return SearchResult(
        python_version=request.version,
        documentation_version=catalog.index.documentation_version,
        query=request.query,
        total_matches=len(matches),
        truncated=result.truncated,
        matches=list(map(search_match, matches[: request.limit])),
    )

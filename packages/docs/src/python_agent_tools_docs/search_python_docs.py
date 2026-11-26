"""Request and result schemas, and the use case, for search_python_docs."""

from typing import TYPE_CHECKING, Annotated

from pydantic import BaseModel, ConfigDict, Field, NonNegativeInt, PositiveInt, StringConstraints

from python_agent_tools_docs.domain import VERSION_PATTERN, PythonVersion
from python_agent_tools_docs.matching import MatchTier, match_symbols

if TYPE_CHECKING:
    from python_agent_tools_docs.catalogs import DocumentationCatalogs
    from python_agent_tools_docs.matching import SymbolMatch

DEFAULT_SEARCH_LIMIT = 10

type VersionText = Annotated[
    str,
    StringConstraints(strict=True, pattern=f'^{VERSION_PATTERN}$'),
    Field(
        description=(
            'Python minor version such as 3.13.\n\n'
            'Read requires-python in pyproject.toml or .python-version first; do not guess.'
        )
    ),
]
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
type SearchLimit = Annotated[
    PositiveInt, Field(le=30, description='Maximum number of matches to return.')
]
type SourceUrl = Annotated[str, Field(description='An official, versioned docs.python.org URL.')]


class Model(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True, strict=True)


class SearchRequest(Model):
    version: VersionText
    query: SymbolQuery
    limit: SearchLimit


class SearchMatch(Model):
    name: str
    kind: str
    source_url: SourceUrl
    match: MatchTier


class SearchResult(Model):
    python_version: VersionText
    documentation_version: str
    query: str
    total_matches: NonNegativeInt
    matches: list[SearchMatch]


def search_match(match: SymbolMatch) -> SearchMatch:
    return SearchMatch(
        name=match.name, kind=match.kind, source_url=match.source_url.text, match=match.match
    )


async def run(service: DocumentationCatalogs, request: SearchRequest) -> SearchResult:
    catalog = await service.catalog(PythonVersion(text=request.version))
    matches = match_symbols(catalog, request.query, service.settings.fuzzy_score_cutoff)
    return SearchResult(
        python_version=request.version,
        documentation_version=catalog.index.documentation_version,
        query=request.query,
        total_matches=len(matches),
        matches=list(map(search_match, matches[: request.limit])),
    )

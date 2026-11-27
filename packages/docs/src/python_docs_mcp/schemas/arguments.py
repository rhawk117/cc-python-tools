"""The argument model each tool takes, with the server's own error wording on every field."""

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from python_docs_mcp.schemas.base import VersionText
from python_docs_mcp.services.read_python_docs import (
    DEFAULT_PAGE_CHARACTERS,
    PageCharacters,
    PageOffset,
    SymbolName,
)
from python_docs_mcp.services.search_python_docs import (
    DEFAULT_SEARCH_LIMIT,
    SearchLimit,
    SymbolQuery,
)

ProjectVersionText = Annotated[
    VersionText,
    Field(
        description=(
            'Python minor version such as 3.13.\n\n'
            'Read requires-python in pyproject.toml or .python-version first; do not guess.'
            " Defaults to the lower bound of the project's requires-python."
        )
    ),
]


class ModelArguments(BaseModel):
    model_config = ConfigDict(frozen=True)


class SearchArguments(ModelArguments):
    version: ProjectVersionText | None = None
    query: SymbolQuery
    limit: SearchLimit = DEFAULT_SEARCH_LIMIT


class ReadArguments(ModelArguments):
    version: ProjectVersionText | None = None
    symbol: SymbolName
    offset: PageOffset = 0
    max_chars: PageCharacters = DEFAULT_PAGE_CHARACTERS


class ResourceOffsetArguments(ModelArguments):
    offset: PageOffset

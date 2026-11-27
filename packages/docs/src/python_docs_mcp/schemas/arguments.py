"""The argument model each tool takes, with the server's own error wording on every field."""

from typing import Annotated

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    NonNegativeInt,
    PositiveInt,
    StringConstraints,
    WrapValidator,
    model_validator,
)
from pydantic_core import PydanticCustomError

from python_docs_mcp.schemas.base import ArgumentRule, VersionText

DEFAULT_SEARCH_LIMIT = 10
DEFAULT_PAGE_CHARACTERS = 8_000

SymbolQuery = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=200),
    Field(
        description=(
            'Symbol name or dotted-name fragments, such as json.loads or ordered dict;'
            ' not a question.'
        )
    ),
    WrapValidator(ArgumentRule(field='query', rule='must be text of 1 to 200 characters').check),
]
SearchLimit = Annotated[
    PositiveInt,
    Field(le=30, description='Maximum number of matches to return.'),
    WrapValidator(ArgumentRule(field='limit', rule='must be a whole number from 1 to 30').check),
]
SymbolName = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=300),
    Field(description='Exact symbol name from search_python_docs, such as os.path.join.'),
    WrapValidator(ArgumentRule(field='symbol', rule='must be text of 1 to 300 characters').check),
]
PageOffset = Annotated[
    NonNegativeInt,
    Field(description='Character offset to continue from, as given by a page footer.'),
    WrapValidator(ArgumentRule(field='offset', rule='must be a whole number of 0 or more').check),
]
PageCharacters = Annotated[
    int,
    Field(ge=500, le=12_000, description='Maximum documentation characters to return.'),
    WrapValidator(
        ArgumentRule(field='max_chars', rule='must be a whole number from 500 to 12000').check
    ),
]
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

    @model_validator(mode='before')
    @classmethod
    def require_fields(cls, data: object) -> object:
        if not isinstance(data, dict):
            return data

        required = [name for name, field in cls.model_fields.items() if field.is_required()]
        missing = [name for name in required if name not in data]
        if missing:
            error_type = 'argument_missing'
            message = 'required fields missing: {fields}'
            context = {'fields': ', '.join(missing)}
            raise PydanticCustomError(error_type, message, context)

        return data


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

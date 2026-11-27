"""The argument model each tool takes, with the server's own error wording on every field."""

from typing import Annotated

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    WrapValidator,
    model_validator,
)
from pydantic_core import PydanticCustomError

from python_docs_mcp.schemas.base import ArgumentRule, VersionText

DEFAULT_SEARCH_LIMIT = 10
DEFAULT_PAGE_CHARACTERS = 8_000
MIN_TEXT_LENGTH = 1
MAX_QUERY_LENGTH = 200
MAX_SYMBOL_LENGTH = 300
SEARCH_LIMIT_FLOOR = 0
MIN_SEARCH_LIMIT = SEARCH_LIMIT_FLOOR + 1
MAX_SEARCH_LIMIT = 30
MIN_OFFSET = 0
MIN_PAGE_CHARACTERS = 500
MAX_PAGE_CHARACTERS = 12_000

QUERY_RULE = f'must be text of {MIN_TEXT_LENGTH} to {MAX_QUERY_LENGTH} characters'
LIMIT_RULE = f'must be a whole number from {MIN_SEARCH_LIMIT} to {MAX_SEARCH_LIMIT}'
SYMBOL_RULE = f'must be text of {MIN_TEXT_LENGTH} to {MAX_SYMBOL_LENGTH} characters'
OFFSET_RULE = f'must be a whole number of {MIN_OFFSET} or more'
PAGE_CHARACTERS_RULE = f'must be a whole number from {MIN_PAGE_CHARACTERS} to {MAX_PAGE_CHARACTERS}'

SymbolQuery = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True, min_length=MIN_TEXT_LENGTH, max_length=MAX_QUERY_LENGTH
    ),
    Field(
        description=(
            'Symbol name or dotted-name fragments, such as json.loads or ordered dict;'
            ' not a question.'
        )
    ),
    WrapValidator(ArgumentRule(field='query', rule=QUERY_RULE).check),
]
SearchLimit = Annotated[
    int,
    Field(
        gt=SEARCH_LIMIT_FLOOR,
        le=MAX_SEARCH_LIMIT,
        description='Maximum number of matches to return.',
    ),
    WrapValidator(ArgumentRule(field='limit', rule=LIMIT_RULE).check),
]
SymbolName = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True, min_length=MIN_TEXT_LENGTH, max_length=MAX_SYMBOL_LENGTH
    ),
    Field(description='Exact symbol name from search_python_docs, such as os.path.join.'),
    WrapValidator(ArgumentRule(field='symbol', rule=SYMBOL_RULE).check),
]
PageOffset = Annotated[
    int,
    Field(
        ge=MIN_OFFSET,
        description='Character offset to continue from, as given by a page footer.',
    ),
    WrapValidator(ArgumentRule(field='offset', rule=OFFSET_RULE).check),
]
PageCharacters = Annotated[
    int,
    Field(
        ge=MIN_PAGE_CHARACTERS,
        le=MAX_PAGE_CHARACTERS,
        description='Maximum documentation characters to return.',
    ),
    WrapValidator(ArgumentRule(field='max_chars', rule=PAGE_CHARACTERS_RULE).check),
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

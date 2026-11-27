"""Schema base and field types shared by the tools."""

from dataclasses import dataclass
from typing import TYPE_CHECKING, Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError, WrapValidator
from pydantic_core import PydanticCustomError
from python_agent_tools_core.version import VERSION_PATTERN

if TYPE_CHECKING:
    from pydantic import ValidatorFunctionWrapHandler


@dataclass(slots=True, kw_only=True, frozen=True)
class ArgumentRule:
    field: str
    rule: str

    def check(self, value: object, handler: ValidatorFunctionWrapHandler) -> object:
        try:
            return handler(value)
        except ValidationError as problems:
            error_type = 'argument_invalid'
            context = {'field': self.field, 'rule': self.rule}
            raise PydanticCustomError(error_type, '{field} {rule}', context) from problems


VersionText = Annotated[
    str,
    StringConstraints(strict=True, pattern=f'^{VERSION_PATTERN}$'),
    Field(
        description=(
            'Python minor version such as 3.13.\n\n'
            'Read requires-python in pyproject.toml or .python-version first; do not guess.'
        )
    ),
    WrapValidator(
        ArgumentRule(field='version', rule='must be a Python minor version such as 3.13').check
    ),
]
SourceUrl = Annotated[str, Field(description='An official, versioned docs.python.org URL.')]


class Model(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True, strict=True)

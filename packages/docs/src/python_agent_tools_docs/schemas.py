"""Schema base and field types shared by the tools."""

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from python_agent_tools_docs.domain import VERSION_PATTERN

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
type SourceUrl = Annotated[str, Field(description='An official, versioned docs.python.org URL.')]


class Model(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True, strict=True)

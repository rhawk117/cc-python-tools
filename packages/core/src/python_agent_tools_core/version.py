"""Validated Python minor versions."""

import re
from dataclasses import dataclass

from python_agent_tools_core.exception import InvalidVersionError

VERSION_PATTERN = r'3\.(0|[1-9][0-9]?)'


def python_version_violation(text: str) -> InvalidVersionError | None:
    if re.fullmatch(VERSION_PATTERN, text) is None:
        return InvalidVersionError(text)
    return None


@dataclass(frozen=True, slots=True, kw_only=True)
class PythonVersion:
    text: str

    @property
    def minor(self) -> int:
        return int(self.text.removeprefix('3.'))


def create_python_version(text: str) -> PythonVersion | InvalidVersionError:
    return python_version_violation(text) or PythonVersion(text=text)

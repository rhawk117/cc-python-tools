"""The Python version floor of the project the agent works in, read from its pyproject.toml."""

import tomllib
from pathlib import Path
from typing import TYPE_CHECKING

from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.version import Version

from python_agent_tools_docs.domain import PythonVersion, create_python_version
from python_agent_tools_docs.errors import InvalidVersionError, VersionRequiredError

if TYPE_CHECKING:
    from collections.abc import Mapping

PROJECT_ROOT_VARIABLE = 'CLAUDE_PROJECT_DIR'
PYPROJECT_NAME = 'pyproject.toml'
LOWER_BOUND_OPERATORS = frozenset({'>=', '~=', '=='})

type Floor = PythonVersion | VersionRequiredError


def read_pyproject(environment: Mapping[str, str]) -> str | VersionRequiredError:
    root = environment.get(PROJECT_ROOT_VARIABLE, '')
    if not root:
        return VersionRequiredError(f'{PROJECT_ROOT_VARIABLE} is not set')

    try:
        return Path(root).joinpath(PYPROJECT_NAME).read_text(encoding='utf-8')
    except OSError:
        return VersionRequiredError(f'{PYPROJECT_NAME} could not be read in the project directory')


def read_requires_python(pyproject: str) -> str | VersionRequiredError:
    try:
        document = tomllib.loads(pyproject)
    except tomllib.TOMLDecodeError:
        return VersionRequiredError(f'{PYPROJECT_NAME} is not valid TOML')

    project = document.get('project')
    requires_python = project.get('requires-python') if isinstance(project, dict) else None
    if not isinstance(requires_python, str):
        return VersionRequiredError(f'{PYPROJECT_NAME} has no requires-python')

    return requires_python


def lower_bounds(requires_python: str) -> list[Version]:
    specifiers = SpecifierSet(requires_python)
    return [
        Version(specifier.version.removesuffix('.*'))
        for specifier in specifiers
        if specifier.operator in LOWER_BOUND_OPERATORS
    ]


def floor_from_requires_python(requires_python: str) -> Floor:
    try:
        bounds = lower_bounds(requires_python)
    except InvalidSpecifier:
        return VersionRequiredError(f'requires-python {requires_python!r} is not a valid range')

    if not bounds:
        return VersionRequiredError(f'requires-python {requires_python!r} has no lower bound')

    floor = max(bounds)
    version = create_python_version(f'{floor.major}.{floor.minor}')
    if isinstance(version, InvalidVersionError):
        return VersionRequiredError(f'requires-python {requires_python!r} has no Python 3 floor')

    return version


def resolve_floor(environment: Mapping[str, str]) -> Floor:
    pyproject = read_pyproject(environment)
    if isinstance(pyproject, VersionRequiredError):
        return pyproject

    requires_python = read_requires_python(pyproject)
    if isinstance(requires_python, VersionRequiredError):
        return requires_python

    return floor_from_requires_python(requires_python)

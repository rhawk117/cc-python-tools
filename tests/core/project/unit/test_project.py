from typing import TYPE_CHECKING

import pytest
from python_agent_tools_core.exception import VersionRequiredError
from python_agent_tools_core.project import (
    PROJECT_ROOT_VARIABLE,
    floor_from_requires_python,
    read_pyproject,
    read_requires_python,
)
from python_agent_tools_core.version import PythonVersion

if TYPE_CHECKING:
    from pathlib import Path


def floor_cases() -> pytest.MarkDecorator:
    cases = {
        '>=3.12': '3.12',
        '>=3.12,<4': '3.12',
        '~=3.11': '3.11',
        '==3.13.*': '3.13',
        '==3.10.4': '3.10',
        '>=3.9,>=3.12': '3.12',
    }
    return pytest.mark.parametrize(
        ('requires_python', 'floor'),
        [pytest.param(spec, floor, id=spec) for spec, floor in cases.items()],
    )


def unreadable_range_cases() -> pytest.MarkDecorator:
    texts = ('<4', '!=3.12', '>3.11', 'nonsense', '>=4.0', '')
    return pytest.mark.parametrize('requires_python', [pytest.param(t, id=repr(t)) for t in texts])


class TestFloorFromRequiresPython:
    @floor_cases()
    def test_the_lower_bound_is_the_floor(self, requires_python: str, floor: str) -> None:
        assert floor_from_requires_python(requires_python) == PythonVersion(text=floor)

    @unreadable_range_cases()
    def test_a_range_without_a_usable_lower_bound_asks_for_version(
        self, requires_python: str
    ) -> None:
        assert isinstance(floor_from_requires_python(requires_python), VersionRequiredError)


class TestReadRequiresPython:
    def test_the_project_table_supplies_requires_python(self) -> None:
        assert read_requires_python('[project]\nrequires-python = ">=3.12"\n') == '>=3.12'

    @pytest.mark.parametrize(
        'pyproject',
        [
            pytest.param('[project\n', id='malformed'),
            pytest.param('', id='empty'),
            pytest.param('[project]\nname = "x"\n', id='no-requires-python'),
            pytest.param('project = 3\n', id='project-not-a-table'),
            pytest.param('[project]\nrequires-python = 3\n', id='not-a-string'),
        ],
    )
    def test_anything_else_asks_for_version(self, pyproject: str) -> None:
        assert isinstance(read_requires_python(pyproject), VersionRequiredError)


class TestReadPyproject:
    def test_an_unset_project_directory_asks_for_version(self) -> None:
        assert isinstance(read_pyproject({}), VersionRequiredError)

    def test_an_empty_project_directory_asks_for_version(self) -> None:
        assert isinstance(read_pyproject({PROJECT_ROOT_VARIABLE: ''}), VersionRequiredError)

    def test_a_project_file_that_is_not_utf8_asks_for_version(self, tmp_path: Path) -> None:
        (tmp_path / 'pyproject.toml').write_bytes(b'\xff\xfe')
        result = read_pyproject({PROJECT_ROOT_VARIABLE: str(tmp_path)})
        assert isinstance(result, VersionRequiredError)

from pathlib import Path

import pytest
from python_agent_tools_docs.domain import PythonVersion
from python_agent_tools_docs.errors import VersionRequiredError
from python_agent_tools_docs.project import PROJECT_ROOT_VARIABLE, resolve_floor


class TestResolveFloor:
    @pytest.fixture
    def environment(self, tmp_path: Path) -> dict[str, str]:
        return {PROJECT_ROOT_VARIABLE: str(tmp_path)}

    def write_pyproject(self, environment: dict[str, str], text: str) -> None:
        root = environment[PROJECT_ROOT_VARIABLE]
        (Path(root) / 'pyproject.toml').write_text(text, encoding='utf-8')

    def test_the_floor_comes_from_the_project_pyproject(self, environment: dict[str, str]) -> None:
        self.write_pyproject(environment, '[project]\nrequires-python = ">=3.12"\n')
        assert resolve_floor(environment) == PythonVersion(text='3.12')

    def test_a_missing_pyproject_asks_for_version(self, environment: dict[str, str]) -> None:
        assert isinstance(resolve_floor(environment), VersionRequiredError)

    def test_a_malformed_pyproject_asks_for_version(self, environment: dict[str, str]) -> None:
        self.write_pyproject(environment, '[project\n')
        assert isinstance(resolve_floor(environment), VersionRequiredError)

    def test_a_pyproject_without_requires_python_asks_for_version(
        self, environment: dict[str, str]
    ) -> None:
        self.write_pyproject(environment, '[project]\nname = "x"\n')
        assert isinstance(resolve_floor(environment), VersionRequiredError)

    def test_a_pyproject_that_is_not_utf8_asks_for_version(
        self, environment: dict[str, str]
    ) -> None:
        root = environment[PROJECT_ROOT_VARIABLE]
        (Path(root) / 'pyproject.toml').write_bytes(b'[project]\nname = "\xff\xfe"\n')
        assert isinstance(resolve_floor(environment), VersionRequiredError)

    @pytest.mark.parametrize('requires_python', ['3', '"nonsense"'])
    def test_an_unusable_requires_python_asks_for_version(
        self, environment: dict[str, str], requires_python: str
    ) -> None:
        self.write_pyproject(environment, f'[project]\nrequires-python = {requires_python}\n')
        assert isinstance(resolve_floor(environment), VersionRequiredError)

    def test_an_unset_project_directory_asks_for_version(self) -> None:
        assert isinstance(resolve_floor({}), VersionRequiredError)

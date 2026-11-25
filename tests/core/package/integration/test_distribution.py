import tomllib
from importlib.metadata import version
from importlib.resources import files
from pathlib import Path

import pytest

DISTRIBUTION = 'python-agent-tools-core'
PACKAGE = 'python_agent_tools_core'


class TestCoreDistribution:
    @pytest.fixture
    def package_root(self, repository_root: Path) -> Path:
        return repository_root.joinpath('packages', 'core')

    @pytest.fixture
    def declared_version(self, package_root: Path) -> str:
        contents = package_root.joinpath('pyproject.toml').read_text('utf-8')
        return tomllib.loads(contents)['project']['version']

    def test_installed_version_is_the_declared_one(self, declared_version: str) -> None:
        assert version(DISTRIBUTION) == declared_version

    def test_package_is_imported_from_the_workspace_source(self, package_root: Path) -> None:
        source = Path(str(files(PACKAGE)))

        assert source.is_relative_to(package_root.joinpath('src'))

"""Invariant I1: the docs package never depends on httpx, only on httpx2."""

import ast
import tomllib
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
SOURCE_ROOT = REPOSITORY_ROOT.joinpath('packages', 'docs', 'src')
LOCKFILE = REPOSITORY_ROOT.joinpath('uv.lock')
BANNED = 'httpx'


def imported_modules(source: str) -> set[str]:
    modules: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        if isinstance(node, ast.ImportFrom) and node.module is not None:
            modules.add(node.module)
    return modules


def imports_banned(source: str) -> bool:
    return any(module.split('.')[0] == BANNED for module in imported_modules(source))


def importing_files() -> list[Path]:
    return [
        path
        for path in SOURCE_ROOT.rglob('*.py')
        if imports_banned(path.read_text(encoding='utf-8'))
    ]


def locked_package_names() -> set[str]:
    lock = tomllib.loads(LOCKFILE.read_text(encoding='utf-8'))
    return {package['name'] for package in lock['package']}


def banned_import_cases() -> pytest.MarkDecorator:
    return pytest.mark.parametrize(
        'source',
        [
            pytest.param('import httpx', id='import'),
            pytest.param('import httpx.auth', id='submodule'),
            pytest.param('from httpx import Client', id='from-import'),
            pytest.param('def run():\n    import httpx\n', id='nested'),
        ],
    )


class TestNoHttpx:
    def test_no_source_module_imports_httpx(self) -> None:
        assert SOURCE_ROOT.is_dir()
        assert importing_files() == []

    def test_the_lockfile_holds_no_httpx_package(self) -> None:
        assert BANNED not in locked_package_names()

    def test_the_lockfile_is_read_with_the_replacement_present(self) -> None:
        assert 'httpx2' in locked_package_names()

    @banned_import_cases()
    def test_the_scanner_flags_a_banned_import(self, source: str) -> None:
        assert imports_banned(source)

    def test_the_scanner_accepts_the_replacement(self) -> None:
        assert not imports_banned('import httpx2\nfrom httpx2 import AsyncClient')

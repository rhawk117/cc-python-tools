"""
Plugin Level & Repository Tests, not for application tests
"""

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Self

import pytest

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path


def read_json_file(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text('utf-8'))


@dataclass(slots=True, frozen=True)
class PluginManifestFile:
    path: Path
    contents: Mapping[str, Any]

    @classmethod
    def read(cls, path: Path) -> Self:
        return cls(path, read_json_file(path))

    def required_key(self, key: str) -> Any:
        return self.contents[key]


@dataclass(slots=True, frozen=True, kw_only=True)
class PluginInventory:
    manifest: PluginManifestFile
    mcp: PluginManifestFile
    docs_mcp: PluginManifestFile
    hooks: PluginManifestFile


@pytest.fixture
def claude_plugin(repository_root: Path) -> PluginInventory:
    plugin_paths = {
        'manifest': repository_root.joinpath('.claude-plugin', 'plugin.json'),
        'mcp': repository_root.joinpath('mcp-servers', 'agent-tools-mcp.json'),
        'docs_mcp': repository_root.joinpath('mcp-servers', 'python-docs-mcp.json'),
        'hooks': repository_root.joinpath('hooks', 'hooks.json'),
    }
    plugin_files = {key: PluginManifestFile.read(path) for key, path in plugin_paths.items()}
    return PluginInventory(**plugin_files)

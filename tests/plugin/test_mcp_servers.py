from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path

    from plugin.conftest import PluginInventory


class TestMcpServerListing:
    server_paths = ('./mcp-servers/python-docs-mcp.json',)

    @pytest.mark.parametrize('server_path', server_paths)
    def test_server_file_exists_on_disk(self, repository_root: Path, server_path: str) -> None:
        assert repository_root.joinpath(server_path).is_file(), (
            f'The MCP server file {server_path} is missing on disk'
        )

    @pytest.mark.parametrize('server_path', server_paths)
    def test_manifest_lists_server_file(
        self,
        claude_plugin: PluginInventory,
        server_path: str,
    ) -> None:
        listed = claude_plugin.manifest.required_key('mcpServers')
        assert isinstance(listed, list)
        assert server_path in listed, (
            f'The plugin manifest mcpServers array does not list {server_path}'
        )

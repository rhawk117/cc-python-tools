import json
from typing import TYPE_CHECKING

import pytest
from mcp import Client, StdioServerParameters
from python_agent_tools_mcp.server import SERVER_NAME

if TYPE_CHECKING:
    from pathlib import Path


class TestEntryPoint:
    config_server_name = 'agent-tools-mcp'

    @pytest.fixture
    def server(self, repository_root: Path) -> StdioServerParameters:
        config_path = repository_root.joinpath('mcp-servers', 'agent-tools-mcp.json')
        config = json.loads(config_path.read_text('utf-8'))
        launch = config['mcpServers'][self.config_server_name]
        command, *args = launch['command'], *launch['args']
        isolated_args = [args[0], '--isolated', *args[1:]]
        return StdioServerParameters(command=command, args=isolated_args)

    async def test_console_script_introduces_itself_and_lists_no_tools(
        self, server: StdioServerParameters
    ) -> None:
        async with Client(server) as client:
            listed = await client.list_tools()
            server_info = client.server_info

        assert server_info is not None
        assert server_info.name == SERVER_NAME
        assert listed.tools == []

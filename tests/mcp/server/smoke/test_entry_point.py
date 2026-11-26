from mcp import Client, StdioServerParameters
from python_agent_tools_mcp.server import SERVER_NAME


class TestEntryPoint:
    server = StdioServerParameters(
        command='uv',
        args=(
            'run',
            '--isolated',
            '--locked',
            '--no-dev',
            '--package',
            'python-agent-tools-mcp',
            'python-agent-tools-mcp',
        ),
    )

    async def test_console_script_introduces_itself_and_lists_no_tools(self) -> None:
        async with Client(self.server) as client:
            listed = await client.list_tools()
            server_info = client.server_info

        assert server_info is not None
        assert server_info.name == SERVER_NAME
        assert listed.tools == []

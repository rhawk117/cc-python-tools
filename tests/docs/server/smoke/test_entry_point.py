from mcp import Client, StdioServerParameters

SERVER = StdioServerParameters(
    command='uv',
    args=[
        'run',
        '--locked',
        '--no-dev',
        '--package',
        'python-docs-mcp',
        'python-docs-mcp',
    ],
)


class TestEntryPoint:
    async def test_console_script_lists_exactly_the_two_documentation_tools(self) -> None:
        async with Client(SERVER) as client:
            listed = await client.list_tools()

        assert {tool.name for tool in listed.tools} == {'search_python_docs', 'read_python_docs'}

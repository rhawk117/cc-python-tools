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

MODULE = StdioServerParameters(
    command='uv',
    args=[
        'run',
        '--locked',
        '--no-dev',
        '--package',
        'python-docs-mcp',
        'python',
        '-m',
        'python_docs_mcp',
    ],
)


class TestEntryPoint:
    async def test_console_script_lists_exactly_the_two_documentation_tools(self) -> None:
        async with Client(SERVER) as client:
            listed = await client.list_tools()

        assert {tool.name for tool in listed.tools} == {'search_python_docs', 'read_python_docs'}

    async def test_module_run_lists_exactly_the_two_documentation_tools(self) -> None:
        async with Client(MODULE) as client:
            listed = await client.list_tools()

        assert {tool.name for tool in listed.tools} == {'search_python_docs', 'read_python_docs'}

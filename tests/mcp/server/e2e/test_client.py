from mcp import Client
from python_agent_tools_mcp.server import SERVER_NAME, create_server


class TestServer:
    async def test_client_connects_and_lists_no_tools(self) -> None:
        async with Client(create_server()) as client:
            listed = await client.list_tools()
            server_info = client.server_info

        assert server_info is not None
        assert server_info.name == SERVER_NAME
        assert listed.tools == []

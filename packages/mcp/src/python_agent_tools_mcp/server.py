"""Build the agent-tools-mcp server, which serves no tools yet."""

from mcp.server.mcpserver import MCPServer

SERVER_NAME = 'agent-tools-mcp'


def create_server() -> MCPServer:
    return MCPServer(SERVER_NAME)

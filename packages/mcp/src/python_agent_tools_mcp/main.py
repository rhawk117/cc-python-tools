"""The `python-agent-tools-mcp` console script: serve the agent-tools-mcp server over stdio."""

from python_agent_tools_mcp.server import create_server


def main() -> int:
    create_server().run()
    return 0

"""The `python-agent-tools-docs` console script: serve the Python documentation tools over stdio."""

import anyio

from python_agent_tools_docs.server import serve
from python_agent_tools_docs.settings import Settings


def main() -> int:
    anyio.run(serve, Settings())
    return 0

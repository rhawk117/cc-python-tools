"""The `python-docs-mcp` console script: serve the Python documentation tools over stdio."""

import anyio

from python_docs_mcp.server import serve
from python_docs_mcp.settings import Settings


def main() -> int:
    anyio.run(serve, Settings())
    return 0

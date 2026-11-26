"""The `python-docs-mcp` console script: serve the Python documentation tools over stdio."""

import anyio

from python_docs_mcp.schemas.settings import Settings
from python_docs_mcp.server import serve


def main() -> int:
    anyio.run(serve, Settings())
    return 0

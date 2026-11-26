"""Run the package: serve the Python documentation tools over stdio."""

import anyio

from python_docs_mcp.schemas.settings import Settings
from python_docs_mcp.server import serve


def main() -> int:
    anyio.run(serve, Settings())
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

"""Run the package: serve the Python documentation tools over stdio."""

from python_docs_mcp.app import server


def main() -> int:
    server.run()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

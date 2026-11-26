"""The python-docs-mcp server over stdio: Python standard-library documentation."""

from contextlib import contextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

from python_agent_tools_docs import read_python_docs as read_use_case
from python_agent_tools_docs import search_python_docs as search_use_case
from python_agent_tools_docs.errors import DocumentationToolsError
from python_agent_tools_docs.read_python_docs import DEFAULT_PAGE_CHARACTERS, ReadRequest
from python_agent_tools_docs.search_python_docs import DEFAULT_SEARCH_LIMIT, SearchRequest
from python_agent_tools_docs.services import build_documentation_service, call_deadline

if TYPE_CHECKING:
    from collections.abc import Generator

    from python_agent_tools_docs.services import DocumentationService
    from python_agent_tools_docs.settings import Settings

SERVER_NAME = 'python-docs-mcp'
SERVER_INSTRUCTIONS = (
    'Official Python standard-library documentation for a specific Python version.'
    ' Find exact names with search_python_docs, then read them with read_python_docs.'
)
READ_ONLY_REMOTE = ToolAnnotations(read_only_hint=True, idempotent_hint=True, open_world_hint=True)


@contextmanager
def tool_errors() -> Generator[None]:
    try:
        yield
    except DocumentationToolsError as error:
        raise ToolError(str(error)) from error


@dataclass(frozen=True, slots=True, kw_only=True)
class DocumentationTools:
    service: DocumentationService

    async def search_python_docs(
        self,
        *,
        version: search_use_case.VersionText,
        query: search_use_case.SymbolQuery,
        limit: search_use_case.SearchLimit = DEFAULT_SEARCH_LIMIT,
    ) -> search_use_case.SearchResult:
        """Find official Python standard-library symbols by name for one Python version.

        Each match is labeled exact, prefix, or approximate; treat approximate matches
        as guesses and confirm them before relying on them.
        """
        service = self.service
        request = SearchRequest(version=version, query=query, limit=limit)
        with tool_errors(), call_deadline(service.settings.call_timeout_seconds):
            return await search_use_case.run(service, request)

    async def read_python_docs(  # noqa: PLR0913 - MCP builds the tool's input schema from these keyword parameters
        self,
        *,
        version: search_use_case.VersionText,
        symbol: read_use_case.SymbolName,
        offset: read_use_case.PageOffset = 0,
        max_chars: read_use_case.PageCharacters = DEFAULT_PAGE_CHARACTERS,
    ) -> str:
        """Read one symbol's official documentation as Markdown, one page at a time.

        The first line names the symbol, its kind, the documentation version, and the
        source URL; the last line gives the next offset or marks the end of the section.
        """
        service = self.service
        request = ReadRequest(version=version, symbol=symbol, offset=offset, max_chars=max_chars)
        with tool_errors(), call_deadline(service.settings.call_timeout_seconds):
            return await read_use_case.run(service, request)


def build_server(service: DocumentationService) -> MCPServer:
    documentation = DocumentationTools(service=service)
    server = MCPServer(SERVER_NAME, instructions=SERVER_INSTRUCTIONS)
    server.add_tool(documentation.search_python_docs, annotations=READ_ONLY_REMOTE)
    server.add_tool(
        documentation.read_python_docs, annotations=READ_ONLY_REMOTE, structured_output=False
    )
    return server


async def serve(settings: Settings) -> None:
    async with build_documentation_service(settings) as service:
        await build_server(service).run_stdio_async()

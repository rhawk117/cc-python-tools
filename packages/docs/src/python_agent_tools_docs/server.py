"""The python-docs-mcp server over stdio: Python standard-library documentation."""

import os
from contextlib import contextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING, Annotated

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import Field

from python_agent_tools_docs import read_python_docs as read_use_case
from python_agent_tools_docs import search_python_docs as search_use_case
from python_agent_tools_docs.errors import DocumentationToolsError, VersionRequiredError
from python_agent_tools_docs.project import resolve_floor
from python_agent_tools_docs.read_python_docs import DEFAULT_PAGE_CHARACTERS, ReadRequest
from python_agent_tools_docs.search_python_docs import DEFAULT_SEARCH_LIMIT, SearchRequest
from python_agent_tools_docs.services import build_documentation_service, call_deadline

if TYPE_CHECKING:
    from collections.abc import Generator, Mapping

    from python_agent_tools_docs.services import DocumentationService
    from python_agent_tools_docs.settings import Settings

SERVER_NAME = 'python-docs-mcp'
SERVER_INSTRUCTIONS = (
    'Official Python standard-library documentation for a specific Python version.'
    ' Find exact names with search_python_docs, then read them with read_python_docs.'
)
READ_ONLY_REMOTE = ToolAnnotations(read_only_hint=True, idempotent_hint=True, open_world_hint=True)

type OptionalVersionText = Annotated[
    search_use_case.VersionText | None,
    Field(
        description=(
            'Python minor version such as 3.13.\n\n'
            'Read requires-python in pyproject.toml or .python-version first; do not guess.'
            " Defaults to the lower bound of the project's requires-python."
        )
    ),
]


@contextmanager
def tool_errors() -> Generator[None]:
    try:
        yield
    except DocumentationToolsError as error:
        raise ToolError(str(error)) from error


@dataclass(frozen=True, slots=True, kw_only=True)
class DocumentationTools:
    service: DocumentationService
    environment: Mapping[str, str]

    def resolve_version(self, version: str | None) -> str:
        if version is not None:
            return version

        floor = resolve_floor(self.environment)
        if isinstance(floor, VersionRequiredError):
            raise floor

        return floor.text

    async def search_python_docs(
        self,
        *,
        version: OptionalVersionText = None,
        query: search_use_case.SymbolQuery,
        limit: search_use_case.SearchLimit = DEFAULT_SEARCH_LIMIT,
    ) -> search_use_case.SearchResult:
        """Find official Python standard-library symbols by name for one Python version.

        Each match is labeled exact, prefix, or approximate; treat approximate matches
        as guesses and confirm them before relying on them.
        """
        service = self.service
        with tool_errors(), call_deadline(service.settings.call_timeout_seconds):
            request = SearchRequest(version=self.resolve_version(version), query=query, limit=limit)
            return await search_use_case.run(service, request)

    async def read_python_docs(  # noqa: PLR0913 - MCP builds the tool's input schema from these keyword parameters
        self,
        *,
        version: OptionalVersionText = None,
        symbol: read_use_case.SymbolName,
        offset: read_use_case.PageOffset = 0,
        max_chars: read_use_case.PageCharacters = DEFAULT_PAGE_CHARACTERS,
    ) -> str:
        """Read one symbol's official documentation as Markdown, one page at a time.

        The first line names the symbol, its kind, the documentation version, and the
        source URL; the last line gives the next offset or marks the end of the section.
        """
        service = self.service
        with tool_errors(), call_deadline(service.settings.call_timeout_seconds):
            request = ReadRequest(
                version=self.resolve_version(version),
                symbol=symbol,
                offset=offset,
                max_chars=max_chars,
            )
            return await read_use_case.run(service, request)


def build_server(service: DocumentationService, environment: Mapping[str, str]) -> MCPServer:
    documentation = DocumentationTools(service=service, environment=environment)
    server = MCPServer(SERVER_NAME, instructions=SERVER_INSTRUCTIONS)
    server.add_tool(documentation.search_python_docs, annotations=READ_ONLY_REMOTE)
    server.add_tool(
        documentation.read_python_docs, annotations=READ_ONLY_REMOTE, structured_output=False
    )
    return server


async def serve(settings: Settings) -> None:
    async with build_documentation_service(settings) as service:
        await build_server(service, os.environ).run_stdio_async()

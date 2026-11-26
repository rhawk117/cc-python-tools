"""The python-docs-mcp server over stdio: Python standard-library documentation."""

import os
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from functools import wraps
from typing import TYPE_CHECKING, Annotated, Concatenate, cast

from mcp.server import mcpserver
from mcp.server.mcpserver.exceptions import ResourceError, ToolError
from mcp.server.mcpserver.resolve import Resolve
from mcp.types import ToolAnnotations
from pydantic import Field
from python_agent_tools_core.exception import (
    InvalidVersionError,
    PythonAgentToolsError,
    VersionRequiredError,
)
from python_agent_tools_core.project import resolve_floor
from python_agent_tools_core.version import create_python_version

from python_docs_mcp.lifespan import (
    SERVICE_STATE_KEY,
    ServerLifespan,
    ServiceOptions,
    open_documentation_service,
)
from python_docs_mcp.schemas.base import VersionText
from python_docs_mcp.services import read_python_docs as read_use_case
from python_docs_mcp.services import search_python_docs as search_use_case
from python_docs_mcp.services.completions import RESOURCE_URI, DocumentationCompletions
from python_docs_mcp.services.documentation_service import DocumentationService, call_deadline
from python_docs_mcp.services.read_python_docs import DEFAULT_PAGE_CHARACTERS, ReadRequest
from python_docs_mcp.services.search_python_docs import DEFAULT_SEARCH_LIMIT, SearchRequest
from python_docs_mcp.stores.disk_cache import create_inventory_store

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Generator, Mapping
    from contextlib import AbstractContextManager

    from python_docs_mcp.schemas.settings import Settings

SERVER_NAME = 'python-docs-mcp'
SERVER_INSTRUCTIONS = (
    'Official Python standard-library documentation for a specific Python version.'
    ' Find exact names with search_python_docs, then read them with read_python_docs.'
)
READ_ONLY_REMOTE = ToolAnnotations(read_only_hint=True, idempotent_hint=True, open_world_hint=True)

ProjectVersionText = Annotated[
    VersionText,
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
    except PythonAgentToolsError as error:
        raise ToolError(str(error)) from error


@contextmanager
def resource_errors() -> Generator[None]:
    try:
        yield
    except PythonAgentToolsError as error:
        raise ResourceError(str(error)) from error


@dataclass(frozen=True, slots=True, kw_only=True)
class ContextReporter:
    context: mcpserver.Context

    async def report(self, read: int, total: int | None) -> None:
        await self.context.report_progress(read, total)


def resolve_tool_service(context: mcpserver.Context) -> DocumentationService:
    state = context.request_context.lifespan_context
    service = cast('DocumentationService', state[SERVICE_STATE_KEY])
    return service.reporting_to(ContextReporter(context=context))


ToolServiceDep = Annotated[DocumentationService, Resolve(resolve_tool_service)]


def guarded[**P, R](
    translate: Callable[[], AbstractContextManager[None]],
) -> Callable[
    [Callable[Concatenate[DocumentationTools, P], Awaitable[R]]],
    Callable[Concatenate[DocumentationTools, P], Awaitable[R]],
]:
    def decorate(
        handler: Callable[Concatenate[DocumentationTools, P], Awaitable[R]],
    ) -> Callable[Concatenate[DocumentationTools, P], Awaitable[R]]:
        @wraps(handler)
        async def run(tools: DocumentationTools, /, *args: P.args, **kwargs: P.kwargs) -> R:
            with ExitStack() as stack:
                stack.enter_context(translate())
                stack.enter_context(call_deadline(tools.service.settings.call_timeout_seconds))
                return await handler(tools, *args, **kwargs)

        return run

    return decorate


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

    @guarded(tool_errors)
    async def search_python_docs(  # noqa: PLR0913 - MCP builds the tool's input schema from these keyword parameters
        self,
        *,
        version: ProjectVersionText | None = None,
        query: search_use_case.SymbolQuery,
        limit: search_use_case.SearchLimit = DEFAULT_SEARCH_LIMIT,
        service: ToolServiceDep,
    ) -> search_use_case.SearchResult:
        """Find official Python standard-library symbols by name for one Python version.

        Each match is labeled exact, prefix, or approximate; treat approximate matches
        as guesses and confirm them before relying on them.
        """
        request = SearchRequest(version=self.resolve_version(version), query=query, limit=limit)
        return await search_use_case.run(service, request)

    @guarded(tool_errors)
    async def read_python_docs(  # noqa: PLR0913 - MCP builds the tool's input schema from these keyword parameters
        self,
        *,
        version: ProjectVersionText | None = None,
        symbol: read_use_case.SymbolName,
        offset: read_use_case.PageOffset = 0,
        max_chars: read_use_case.PageCharacters = DEFAULT_PAGE_CHARACTERS,
        service: ToolServiceDep,
    ) -> str:
        """Read one symbol's official documentation as Markdown, one page at a time.

        The first line names the symbol, its kind, the documentation version, and the
        source URL; the last line gives the next offset or marks the end of the section.
        """
        request = ReadRequest(
            version=self.resolve_version(version),
            symbol=symbol,
            offset=offset,
            max_chars=max_chars,
        )
        return await read_use_case.run(service, request)

    @guarded(resource_errors)
    async def read_section(self, version: str, symbol: str) -> str:
        created = create_python_version(version)
        if isinstance(created, InvalidVersionError):
            raise created

        found = await read_use_case.find_symbol(self.service, created, symbol)
        return await self.service.section(found)


def build_server(
    service: DocumentationService, environment: Mapping[str, str]
) -> mcpserver.MCPServer:
    documentation = DocumentationTools(service=service, environment=environment)
    server = mcpserver.MCPServer(
        SERVER_NAME,
        instructions=SERVER_INSTRUCTIONS,
        lifespan=ServerLifespan(service=service, environment=environment).open,
    )
    server.add_tool(documentation.search_python_docs, annotations=READ_ONLY_REMOTE)
    server.add_tool(
        documentation.read_python_docs, annotations=READ_ONLY_REMOTE, structured_output=False
    )
    server.resource(
        RESOURCE_URI,
        name='python_docs',
        title='Python standard-library documentation',
        description="One symbol's whole official documentation section, as Markdown.",
        mime_type='text/markdown',
    )(documentation.read_section)
    server.completion()(DocumentationCompletions(service=service, environment=environment).complete)
    return server


async def serve(settings: Settings) -> None:
    store = create_inventory_store(os.environ, settings.cache_ttl_seconds)
    async with open_documentation_service(settings, ServiceOptions(store=store)) as service:
        await build_server(service, os.environ).run_stdio_async()

"""The python-docs-mcp server: the tools, the resource and the completions declared in one place."""

from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING, Annotated
from urllib.parse import quote

from mcp.server import mcpserver
from mcp.server.mcpserver.exceptions import ResourceError, ToolError
from mcp.server.mcpserver.resolve import Resolve
from mcp.types import ToolAnnotations
from pydantic import BaseModel, Field, ValidationError
from python_agent_tools_core.exception import InvalidVersionError, VersionRequiredError
from python_agent_tools_core.project import resolve_floor
from python_agent_tools_core.version import create_python_version

from python_docs_mcp.core.exception import ServiceUnavailableError
from python_docs_mcp.lifespan import (
    ServerLifespan,
    ServerState,
    get_config_registry,
    get_service_registry,
)
from python_docs_mcp.resolve import ErrorTranslator, MCPCallStack
from python_docs_mcp.schemas.base import VersionText
from python_docs_mcp.server import ArgumentErrorExtension, ArgumentErrorFormatter
from python_docs_mcp.services import read_python_docs as read_use_case
from python_docs_mcp.services import search_python_docs as search_use_case
from python_docs_mcp.services.completions import (
    RESOURCE_URI,
    DocumentationCompletions,
)
from python_docs_mcp.services.documentation_service import DocumentationService
from python_docs_mcp.services.read_python_docs import DEFAULT_PAGE_CHARACTERS, ReadRequest
from python_docs_mcp.services.search_python_docs import DEFAULT_SEARCH_LIMIT, SearchRequest

if TYPE_CHECKING:
    from collections.abc import Mapping

    from mcp.types import (
        Completion,
        CompletionArgument,
        CompletionContext,
        PromptReference,
        ResourceTemplateReference,
    )

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


class SearchArguments(BaseModel):
    version: ProjectVersionText | None = None
    query: search_use_case.SymbolQuery
    limit: search_use_case.SearchLimit = DEFAULT_SEARCH_LIMIT


class ReadArguments(BaseModel):
    version: ProjectVersionText | None = None
    symbol: read_use_case.SymbolName
    offset: read_use_case.PageOffset = 0
    max_chars: read_use_case.PageCharacters = DEFAULT_PAGE_CHARACTERS


class ResourceOffsetArguments(BaseModel):
    offset: read_use_case.PageOffset


def parse_resource_offset(text: str) -> int:
    try:
        return ResourceOffsetArguments.model_validate({'offset': text}).offset
    except ValidationError as problems:
        raise ResourceError(ArgumentErrorFormatter().describe(problems)) from problems


TOOL_ARGUMENT_MODELS: Mapping[str, type[BaseModel]] = MappingProxyType({
    'search_python_docs': SearchArguments,
    'read_python_docs': ReadArguments,
})


@dataclass(frozen=True, slots=True, kw_only=True)
class ContextReporter:
    context: mcpserver.Context[ServerState]

    async def report(self, read: int, total: int | None) -> None:
        await self.context.report_progress(read, total)


def resolve_tool_service(context: mcpserver.Context[ServerState]) -> DocumentationService:
    state = context.request_context.lifespan_context
    return state.service.reporting_to(ContextReporter(context=context))


def resolve_tool_call_stack(context: mcpserver.Context[ServerState]) -> MCPCallStack:
    state = context.request_context.lifespan_context
    return MCPCallStack(
        translator=ErrorTranslator(raises=ToolError),
        deadline_seconds=state.service.settings.call_timeout_seconds,
        environment=state.environment,
    )


def resolve_resource_service() -> DocumentationService:
    service = get_service_registry().get_service()
    if service is None:
        raise ServiceUnavailableError

    return service


def resolve_resource_call_stack(context: mcpserver.Context[ServerState]) -> MCPCallStack:
    state = context.request_context.lifespan_context
    return MCPCallStack(
        translator=ErrorTranslator(raises=ResourceError),
        deadline_seconds=state.service.settings.call_timeout_seconds,
        environment=state.environment,
    )


def resolve_version(environment: Mapping[str, str], version: str | None) -> str:
    if version is not None:
        return version

    floor = resolve_floor(environment)
    if isinstance(floor, VersionRequiredError):
        raise floor

    return floor.text


ToolServiceDep = Annotated[DocumentationService, Resolve(resolve_tool_service)]
ToolCallStackDep = Annotated[MCPCallStack, Resolve(resolve_tool_call_stack)]


def create_server(*, settings: Settings | None = None) -> mcpserver.MCPServer[ServerState]:
    return mcpserver.MCPServer[ServerState](
        SERVER_NAME,
        instructions=SERVER_INSTRUCTIONS,
        lifespan=ServerLifespan(settings=settings).open,
        extensions=[ArgumentErrorExtension(models=TOOL_ARGUMENT_MODELS)],
    )


server = create_server()


@server.tool(annotations=READ_ONLY_REMOTE)
async def search_python_docs(  # noqa: PLR0913 - MCP builds the tool's input schema from these keyword parameters
    *,
    version: ProjectVersionText | None = None,
    query: search_use_case.SymbolQuery,
    limit: search_use_case.SearchLimit = DEFAULT_SEARCH_LIMIT,
    service: ToolServiceDep,
    call_stack: ToolCallStackDep,
) -> search_use_case.SearchResult:
    """Find official Python standard-library symbols by name for one Python version.

    Each match is labeled exact, prefix, or approximate; treat approximate matches
    as guesses and confirm them before relying on them.
    """
    with call_stack.create_callstack():
        request = SearchRequest(
            version=resolve_version(call_stack.environment, version), query=query, limit=limit
        )
        return await search_use_case.run(service, request)


@server.tool(annotations=READ_ONLY_REMOTE, structured_output=False)
async def read_python_docs(  # noqa: PLR0913 - MCP builds the tool's input schema from these keyword parameters
    *,
    version: ProjectVersionText | None = None,
    symbol: read_use_case.SymbolName,
    offset: read_use_case.PageOffset = 0,
    max_chars: read_use_case.PageCharacters = DEFAULT_PAGE_CHARACTERS,
    service: ToolServiceDep,
    call_stack: ToolCallStackDep,
) -> str:
    """Read one symbol's official documentation as Markdown, one page at a time.

    The first line names the symbol, its kind, the documentation version, and the
    source URL; the last line gives the next offset or marks the end of the section.
    """
    with call_stack.create_callstack():
        request = ReadRequest(
            version=resolve_version(call_stack.environment, version),
            symbol=symbol,
            offset=offset,
            max_chars=max_chars,
        )
        return await read_use_case.run(service, request)


@server.resource(
    RESOURCE_URI,
    title='Python standard-library documentation',
    description=(
        "One symbol's official documentation as Markdown, one page at a time;"
        ' the last line names the next offset.'
    ),
    mime_type='text/markdown',
)
async def python_docs(  # noqa: PLR0913 - MCP builds the resource template's parameters from these keyword parameters
    *, version: str, symbol: str, offset: str = '0', context: mcpserver.Context[ServerState]
) -> str:
    service = context.request_context.lifespan_context.service
    call_stack = resolve_resource_call_stack(context)
    with call_stack.create_callstack():
        created = create_python_version(version)
        if isinstance(created, InvalidVersionError):
            raise created

        request = ReadRequest(
            version=created.text,
            symbol=symbol,
            offset=parse_resource_offset(offset),
            max_chars=DEFAULT_PAGE_CHARACTERS,
        )
        continuation = f'read python-docs://{created.text}/{quote(symbol, safe="")}?offset='
        return await read_use_case.run(service, request, continuation)


async def complete_documentation(
    ref: ResourceTemplateReference | PromptReference,
    argument: CompletionArgument,
    context: CompletionContext | None,
) -> Completion | None:
    service = resolve_resource_service()
    environment = get_config_registry().provide_config().environment
    completions = DocumentationCompletions(service=service, environment=environment)
    return await completions.complete(ref, argument, context)


server.completion()(complete_documentation)

"""The python-docs-mcp server: the tools, the resource and the completions declared in one place."""

from typing import TYPE_CHECKING
from urllib.parse import quote

from mcp.server import mcpserver
from mcp.server.mcpserver.exceptions import ResourceError
from mcp.types import ToolAnnotations
from pydantic import ValidationError
from python_agent_tools_core.exception import InvalidVersionError
from python_agent_tools_core.version import create_python_version

from python_docs_mcp import resolve
from python_docs_mcp.lifespan import (
    ServerLifespan,
    ServerState,
    get_config_registry,
)
from python_docs_mcp.schemas import arguments
from python_docs_mcp.services import read_python_docs as read_use_case
from python_docs_mcp.services import search_python_docs as search_use_case
from python_docs_mcp.services.completions import (
    RESOURCE_URI,
    DocumentationCompletions,
)
from python_docs_mcp.services.read_python_docs import ReadRequest
from python_docs_mcp.services.search_python_docs import SearchRequest

if TYPE_CHECKING:
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


def parse_resource_offset(text: str) -> int:
    try:
        return arguments.ResourceOffsetArguments.model_validate({'offset': text}).offset
    except ValidationError as problems:
        raise ResourceError(problems.errors(include_url=False)[0]['msg']) from problems


def create_server(*, settings: Settings | None = None) -> mcpserver.MCPServer[ServerState]:
    return mcpserver.MCPServer[ServerState](
        SERVER_NAME,
        instructions=SERVER_INSTRUCTIONS,
        lifespan=ServerLifespan(settings=settings).open,
    )


server = create_server()


@server.tool(annotations=READ_ONLY_REMOTE)
async def search_python_docs(
    *,
    model_params: arguments.SearchArguments,
    service: resolve.ToolServiceDep,
    call_stack: resolve.ToolCallStackDep,
) -> search_use_case.SearchResult:
    """Find official Python standard-library symbols by name for one Python version.

    Each match is labeled exact, prefix, or approximate; treat approximate matches
    as guesses and confirm them before relying on them.
    """
    with call_stack.create_callstack():
        request = SearchRequest(
            version=resolve.resolve_version(call_stack.environment, model_params.version),
            query=model_params.query,
            limit=model_params.limit,
        )
        return await search_use_case.run(service, request)


@server.tool(annotations=READ_ONLY_REMOTE, structured_output=False)
async def read_python_docs(
    *,
    model_params: arguments.ReadArguments,
    service: resolve.ToolServiceDep,
    call_stack: resolve.ToolCallStackDep,
) -> str:
    """Read one symbol's official documentation as Markdown, one page at a time.

    The first line names the symbol, its kind, the documentation version, and the
    source URL; the last line gives the next offset or marks the end of the section.
    """
    with call_stack.create_callstack():
        request = ReadRequest(
            version=resolve.resolve_version(call_stack.environment, model_params.version),
            symbol=model_params.symbol,
            offset=model_params.offset,
            max_chars=model_params.max_chars,
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
    call_stack = resolve.resolve_resource_call_stack(context)
    with call_stack.create_callstack():
        created = create_python_version(version)
        if isinstance(created, InvalidVersionError):
            raise created

        request = ReadRequest(
            version=created.text,
            symbol=symbol,
            offset=parse_resource_offset(offset),
            max_chars=arguments.DEFAULT_PAGE_CHARACTERS,
        )
        continuation = f'read python-docs://{created.text}/{quote(symbol, safe="")}?offset='
        return await read_use_case.run(service, request, continuation)


async def complete_documentation(
    ref: ResourceTemplateReference | PromptReference,
    argument: CompletionArgument,
    context: CompletionContext | None,
) -> Completion | None:
    service = resolve.resolve_resource_service()
    environment = get_config_registry().provide_config().environment
    completions = DocumentationCompletions(service=service, environment=environment)
    return await completions.complete(ref, argument, context)


server.completion()(complete_documentation)

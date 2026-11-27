"""Resolve the per-call dependencies of the tools and the resource, and their call stack."""

from contextlib import ExitStack
from dataclasses import dataclass
from typing import TYPE_CHECKING, Annotated

from mcp.server import mcpserver
from mcp.server.mcpserver.exceptions import ResourceError, ToolError
from mcp.server.mcpserver.resolve import Resolve
from python_agent_tools_core.exception import PythonAgentToolsError, VersionRequiredError
from python_agent_tools_core.project import resolve_floor

from python_docs_mcp.core.exception import ServiceUnavailableError
from python_docs_mcp.lifespan import ServerState, get_service_registry
from python_docs_mcp.services.documentation_service import DocumentationService, call_deadline

if TYPE_CHECKING:
    from collections.abc import Mapping
    from contextlib import AbstractContextManager
    from types import TracebackType

    from mcp.server.mcpserver.exceptions import MCPServerError


@dataclass(frozen=True, slots=True, kw_only=True)
class ErrorTranslator:
    raises: type[MCPServerError]

    def __enter__(self) -> None:
        return None

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if isinstance(exc, PythonAgentToolsError):
            raise self.raises(str(exc)) from exc


@dataclass(frozen=True, slots=True, kw_only=True)
class MCPCallStack:
    translator: AbstractContextManager[None]
    deadline_seconds: float
    environment: Mapping[str, str]

    def create_callstack(self) -> ExitStack:
        stack = ExitStack()
        stack.enter_context(self.translator)
        stack.enter_context(call_deadline(self.deadline_seconds))
        return stack


ServerContext = mcpserver.Context[ServerState]


@dataclass(frozen=True, slots=True, kw_only=True)
class ContextReporter:
    context: ServerContext

    async def report(self, read: int, total: int | None) -> None:
        await self.context.report_progress(read, total)


def resolve_tool_service(context: ServerContext) -> DocumentationService:
    state = context.request_context.lifespan_context
    return state.service.reporting_to(ContextReporter(context=context))


def build_call_stack(context: ServerContext, raises: type[MCPServerError]) -> MCPCallStack:
    state = context.request_context.lifespan_context
    return MCPCallStack(
        translator=ErrorTranslator(raises=raises),
        deadline_seconds=state.service.settings.call_timeout_seconds,
        environment=state.environment,
    )


def resolve_tool_call_stack(context: ServerContext) -> MCPCallStack:
    return build_call_stack(context, ToolError)


def resolve_resource_state() -> ServerState:
    state = get_service_registry().get_state()
    if state is None:
        raise ServiceUnavailableError

    return state


def resolve_resource_call_stack(context: ServerContext) -> MCPCallStack:
    return build_call_stack(context, ResourceError)


def resolve_version(environment: Mapping[str, str], version: str | None) -> str:
    if version is not None:
        return version

    floor = resolve_floor(environment)
    if isinstance(floor, VersionRequiredError):
        raise floor

    return floor.text


ToolServiceDep = Annotated[DocumentationService, Resolve(resolve_tool_service)]
ToolCallStackDep = Annotated[MCPCallStack, Resolve(resolve_tool_call_stack)]

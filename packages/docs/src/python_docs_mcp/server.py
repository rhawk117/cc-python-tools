"""The MCP extension that turns invalid tool arguments into short, field-named error lines."""

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, override

from mcp.server.extension import Extension
from mcp.types import CallToolResult, TextContent
from pydantic import ValidationError

if TYPE_CHECKING:
    from collections.abc import Mapping

    from mcp.server.context import ServerRequestContext
    from mcp.server.extension import CallNext, HandlerResult
    from mcp.types import CallToolRequestParams
    from pydantic import BaseModel
    from pydantic_core import ErrorDetails

EXTENSION_IDENTIFIER = 'io.github.python-agent-tools/argument-errors'
ERROR_REASONS: Mapping[str, str] = {
    'missing': 'is required',
    'extra_forbidden': 'is not an accepted argument',
    'less_than_equal': 'must be at most {le}',
    'less_than': 'must be less than {lt}',
    'greater_than_equal': 'must be at least {ge}',
    'greater_than': 'must be greater than {gt}',
    'string_too_long': 'is too long (maximum {max_length} characters)',
    'string_too_short': 'is too short (minimum {min_length} characters)',
    'string_pattern_mismatch': 'does not match the expected format',
}


def describe_reason(error: ErrorDetails) -> str:
    template = ERROR_REASONS.get(error['type'])
    if template is None:
        return error['msg'].replace('Input should ', 'must ', 1)

    return template.format(**error.get('ctx', {}))


def describe_error(error: ErrorDetails) -> str:
    field = '.'.join(str(part) for part in error['loc'])
    return f'{field}: {describe_reason(error)}'


def describe_problems(problems: ValidationError) -> str:
    return '\n'.join(describe_error(error) for error in problems.errors(include_url=False))


@dataclass(kw_only=True)
class ArgumentErrorExtension[ToolName: str](Extension):
    models: Mapping[ToolName, type[BaseModel]]
    identifier = EXTENSION_IDENTIFIER

    @override
    async def intercept_tool_call(
        self,
        params: CallToolRequestParams,
        ctx: ServerRequestContext[Any, Any],
        call_next: CallNext,
    ) -> HandlerResult:
        model = next((model for name, model in self.models.items() if name == params.name), None)
        if model is None:
            return await call_next(ctx)

        try:
            model.model_validate(params.arguments or {})
        except ValidationError as problems:
            text = describe_problems(problems)
            return CallToolResult(content=[TextContent(type='text', text=text)], is_error=True)

        return await call_next(ctx)

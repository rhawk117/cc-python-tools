"""The MCP extension that turns invalid tool arguments into short, field-named error lines."""

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal, override

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

type ErrorType = Literal[
    'missing',
    'less_than_equal',
    'less_than',
    'greater_than_equal',
    'greater_than',
    'string_too_long',
    'string_too_short',
    'string_pattern_mismatch',
]


def create_reason_templates() -> dict[ErrorType, str]:
    return {
        'missing': 'is required',
        'less_than_equal': 'must be at most {le}',
        'less_than': 'must be less than {lt}',
        'greater_than_equal': 'must be at least {ge}',
        'greater_than': 'must be greater than {gt}',
        'string_too_long': 'is too long (maximum {max_length} characters)',
        'string_too_short': 'is too short (minimum {min_length} characters)',
        'string_pattern_mismatch': 'does not match the expected format',
    }


@dataclass(slots=True, kw_only=True, frozen=True)
class ArgumentErrorFormatter:
    templates: dict[ErrorType, str] = field(default_factory=create_reason_templates)

    def describe_reason(self, error: ErrorDetails) -> str:
        template = self.templates.get(error['type'])
        if template is None:
            return error['msg'].replace('Input should ', 'must ', 1)

        return template.format(**error.get('ctx', {}))

    def describe_error(self, error: ErrorDetails) -> str:
        field_path = '.'.join(str(part) for part in error['loc'])
        return f'{field_path}: {self.describe_reason(error)}'

    def describe(self, problems: ValidationError) -> str:
        return '\n'.join(map(self.describe_error, problems.errors(include_url=False)))


@dataclass(kw_only=True)
class ArgumentErrorExtension(Extension):
    models: Mapping[str, type[BaseModel]]
    formatter: ArgumentErrorFormatter = field(default_factory=ArgumentErrorFormatter)
    identifier = EXTENSION_IDENTIFIER

    @override
    async def intercept_tool_call(
        self,
        params: CallToolRequestParams,
        ctx: ServerRequestContext[Any, Any],
        call_next: CallNext,
    ) -> HandlerResult:
        model = self.models.get(params.name)
        if model is None:
            return await call_next(ctx)

        try:
            model.model_validate(params.arguments or {})
        except ValidationError as problems:
            text = self.formatter.describe(problems)
            return CallToolResult(content=[TextContent(type='text', text=text)], is_error=True)

        return await call_next(ctx)

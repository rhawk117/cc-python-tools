"""Argument completions for the python-docs resource template."""

from dataclasses import dataclass
from typing import TYPE_CHECKING

from mcp.types import Completion, ResourceTemplateReference

from python_docs_mcp.core.exception import (
    DocumentationToolsError,
    InvalidVersionError,
    VersionRequiredError,
)
from python_docs_mcp.project import resolve_floor
from python_docs_mcp.schemas.domain_types import PythonVersion, create_python_version

if TYPE_CHECKING:
    from collections.abc import Mapping

    from mcp.types import CompletionArgument, CompletionContext, PromptReference

    from python_docs_mcp.schemas.settings import Settings
    from python_docs_mcp.services.documentation_service import DocumentationService

RESOURCE_URI = 'python-docs://{version}/{symbol}'
MAX_COMPLETION_VALUES = 100
VERSION_ARGUMENT = 'version'
SYMBOL_ARGUMENT = 'symbol'


def version_window(settings: Settings) -> list[str]:
    first = PythonVersion(text=settings.completion_floor_version).minor
    last = PythonVersion(text=settings.completion_ceiling_version).minor
    return [f'3.{minor}' for minor in range(first, last + 1)]


def capped(values: list[str]) -> Completion:
    return Completion(
        values=values[:MAX_COMPLETION_VALUES],
        total=len(values),
        has_more=len(values) > MAX_COMPLETION_VALUES,
    )


def resolved_arguments(context: CompletionContext | None) -> dict[str, str]:
    arguments = context.arguments if context else None
    return arguments or {}


@dataclass(frozen=True, slots=True, kw_only=True, eq=False)
class DocumentationCompletions:
    service: DocumentationService
    environment: Mapping[str, str]

    def version_names(self) -> list[str]:
        window = version_window(self.service.settings)
        floor = resolve_floor(self.environment)
        if isinstance(floor, VersionRequiredError) or floor.text not in window:
            return window

        return [floor.text, *(version for version in window if version != floor.text)]

    def complete_version(self, prefix: str) -> Completion:
        return capped([name for name in self.version_names() if name.startswith(prefix)])

    async def symbol_names(self, version_text: str, prefix: str) -> list[str]:
        version = create_python_version(version_text)
        if isinstance(version, InvalidVersionError):
            return []

        try:
            catalog = await self.service.stored_catalog(version)
        except DocumentationToolsError:
            return []

        if catalog is None:
            return []

        folded = prefix.casefold()
        return sorted(name for name in catalog.index.symbols if name.casefold().startswith(folded))

    async def complete_symbol(self, prefix: str, context: CompletionContext | None) -> Completion:
        version_text = resolved_arguments(context).get(VERSION_ARGUMENT, '')
        return capped(await self.symbol_names(version_text, prefix))

    async def complete(
        self,
        ref: ResourceTemplateReference | PromptReference,
        argument: CompletionArgument,
        context: CompletionContext | None,
    ) -> Completion | None:
        if not isinstance(ref, ResourceTemplateReference) or ref.uri != RESOURCE_URI:
            return None

        if argument.name == VERSION_ARGUMENT:
            return self.complete_version(argument.value)

        if argument.name == SYMBOL_ARGUMENT:
            return await self.complete_symbol(argument.value, context)

        return None

"""Download progress: who is watching a version's inventory, and what each watcher is told."""

from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from collections.abc import Generator

    from python_agent_tools_docs.domain import PythonVersion


@runtime_checkable
class ProgressReporter(Protocol):
    async def report(self, read: int, total: int | None) -> None: ...


@dataclass(frozen=True, slots=True, kw_only=True)
class SilentReporter:
    async def report(self, read: int, total: int | None) -> None: ...


@dataclass(frozen=True, slots=True, kw_only=True, eq=False)
class ProgressBoard:
    watchers: dict[PythonVersion, list[ProgressReporter]] = field(default_factory=dict)

    @contextmanager
    def watch(self, version: PythonVersion, reporter: ProgressReporter) -> Generator[None]:
        reporters = self.watchers.setdefault(version, [])
        reporters.append(reporter)
        try:
            yield
        finally:
            reporters.remove(reporter)
            if not reporters:
                self.watchers.pop(version, None)

    async def publish(self, version: PythonVersion, read: int, total: int | None) -> None:
        for reporter in tuple(self.watchers.get(version, ())):
            await reporter.report(read, total)


@dataclass(frozen=True, slots=True, kw_only=True, eq=False)
class VersionProgress:
    board: ProgressBoard
    version: PythonVersion

    async def report(self, read: int, total: int | None) -> None:
        await self.board.publish(self.version, read, total)

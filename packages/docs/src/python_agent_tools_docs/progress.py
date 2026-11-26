"""Download progress: who is watching a version's inventory, and what each watcher is told."""

import logging
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from collections.abc import Generator

    from python_agent_tools_docs.domain import PythonVersion

logger = logging.getLogger(__name__)


@runtime_checkable
class ProgressReporter(Protocol):
    async def report(self, read: int, total: int | None) -> None: ...


@dataclass(frozen=True, slots=True, kw_only=True)
class SilentReporter:
    async def report(self, read: int, total: int | None) -> None: ...


@dataclass(frozen=True, slots=True, kw_only=True, eq=False)
class ProgressBoard:
    watchers: dict[PythonVersion, list[ProgressReporter]] = field(default_factory=dict)
    failed: dict[PythonVersion, set[int]] = field(default_factory=dict)

    @contextmanager
    def watch(self, version: PythonVersion, reporter: ProgressReporter) -> Generator[None]:
        reporters = self.watchers.setdefault(version, [])
        reporters.append(reporter)
        try:
            yield
        finally:
            reporters.remove(reporter)
            self.failed.get(version, set()).discard(id(reporter))
            if not reporters:
                self.watchers.pop(version, None)
                self.failed.pop(version, None)

    def watcher_count(self, version: PythonVersion) -> int:
        return len(self.watchers.get(version, ()))

    async def publish(self, version: PythonVersion, read: int, total: int | None) -> None:
        for reporter in tuple(self.watchers.get(version, ())):
            if id(reporter) in self.failed.get(version, ()):
                continue

            try:
                await reporter.report(read, total)
            except Exception:
                if any(watched is reporter for watched in self.watchers.get(version, ())):
                    self.failed.setdefault(version, set()).add(id(reporter))
                logger.warning('progress watcher failed for %s', version, exc_info=True)


@dataclass(frozen=True, slots=True, kw_only=True, eq=False)
class VersionProgress:
    board: ProgressBoard
    version: PythonVersion

    async def report(self, read: int, total: int | None) -> None:
        await self.board.publish(self.version, read, total)

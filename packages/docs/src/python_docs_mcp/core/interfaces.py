"""Protocols shared by every layer."""

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from datetime import datetime

    from python_agent_tools_core.version import PythonVersion


@runtime_checkable
class ClockInterface(Protocol):
    def now(self) -> datetime: ...

    def epoch_now(self) -> float: ...

    def timestamp(self) -> int: ...

    def monotonic(self) -> float: ...


@runtime_checkable
class Loader[K, V](Protocol):
    async def load(self, key: K, /) -> V: ...


@runtime_checkable
class InventoryStore(Protocol):
    def read(self, version: PythonVersion) -> bytes | None: ...

    def write(self, version: PythonVersion, content: bytes) -> None: ...


@runtime_checkable
class ProgressReporter(Protocol):
    async def report(self, read: int, total: int | None) -> None: ...

"""Protocols shared by every layer."""

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from datetime import datetime


@runtime_checkable
class ClockInterface(Protocol):
    def now(self) -> datetime: ...

    def epoch_now(self) -> float: ...

    def timestamp(self) -> int: ...

    def monotonic(self) -> float: ...


@runtime_checkable
class Loader[K, V](Protocol):
    async def load(self, key: K, /) -> V: ...

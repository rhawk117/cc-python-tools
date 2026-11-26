"""The one clock every time read in the server goes through."""

import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from datetime import tzinfo

    from python_docs_mcp.core.interfaces import ClockInterface

type TimestampUnit = Literal['seconds', 'milliseconds']

MILLISECONDS_PER_SECOND = 1000


@dataclass(slots=True, kw_only=True, frozen=True)
class ServerClock:
    zone: tzinfo = UTC
    unit: TimestampUnit = 'seconds'

    def now(self) -> datetime:
        return datetime.now(self.zone)

    def epoch_now(self) -> float:
        return time.time()

    def timestamp(self) -> int:
        seconds = self.epoch_now()
        if self.unit == 'milliseconds':
            return int(seconds * MILLISECONDS_PER_SECOND)
        return int(seconds)

    def monotonic(self) -> float:
        return time.monotonic()


_server_clock = ServerClock()


def get_server_clock() -> ClockInterface:
    return _server_clock

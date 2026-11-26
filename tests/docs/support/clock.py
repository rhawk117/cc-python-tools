from dataclasses import dataclass, field
from datetime import UTC, datetime


@dataclass(slots=True)
class ClockReading:
    epoch: float = 0
    monotonic: float = 0


@dataclass(slots=True, kw_only=True, frozen=True)
class FakeClock:
    reading: ClockReading = field(default_factory=ClockReading)

    def advance(self, seconds: float) -> None:
        self.reading.epoch += seconds
        self.reading.monotonic += seconds

    def set_epoch(self, seconds: float) -> None:
        self.reading.epoch = seconds

    def now(self) -> datetime:
        return datetime.fromtimestamp(self.reading.epoch, UTC)

    def epoch_now(self) -> float:
        return self.reading.epoch

    def timestamp(self) -> int:
        return int(self.reading.epoch)

    def monotonic(self) -> float:
        return self.reading.monotonic

from datetime import UTC, datetime, timedelta, timezone

import pytest
from python_docs_mcp.core.clock import ServerClock, get_server_clock
from python_docs_mcp.core.interfaces import ClockInterface

from tests.docs.support.clock import FakeClock

pytestmark = pytest.mark.unit


class TestServerClock:
    resolution = 1e-3

    def test_the_shared_clock_is_one_instance_implementing_the_protocol(self) -> None:
        assert get_server_clock() is get_server_clock()
        assert isinstance(get_server_clock(), ClockInterface)

    def test_now_is_aware_in_the_configured_zone(self) -> None:
        zone = timezone(timedelta(hours=2))
        assert ServerClock(zone=zone).now().utcoffset() == timedelta(hours=2)
        assert ServerClock().now().utcoffset() == timedelta(0)

    def test_the_readings_agree_with_the_wall_clock(self) -> None:
        clock = ServerClock()
        before = datetime.now(UTC).timestamp() - self.resolution
        epoch = clock.epoch_now()
        after = clock.now().timestamp() + self.resolution
        assert before <= epoch <= after
        assert abs(clock.timestamp() - epoch) <= 1

    def test_the_timestamp_unit_scales_the_epoch(self) -> None:
        seconds = ServerClock().timestamp()
        milliseconds = ServerClock(unit='milliseconds').timestamp()
        assert abs(milliseconds - seconds * 1000) <= 1000

    def test_monotonic_never_goes_backwards(self) -> None:
        clock = ServerClock()
        first = clock.monotonic()
        assert clock.monotonic() >= first

    def test_the_fake_clock_implements_the_protocol(self) -> None:
        assert isinstance(FakeClock(), ClockInterface)

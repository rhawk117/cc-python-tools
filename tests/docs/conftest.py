import pytest

from tests.docs.support.clock import FakeClock


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()

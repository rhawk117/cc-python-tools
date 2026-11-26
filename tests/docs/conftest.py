import pytest
from python_docs_mcp.lifespan import get_config_registry

from tests.docs.support.clock import FakeClock
from tests.docs.support.server import ServerHarness


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def harness() -> ServerHarness:
    return ServerHarness(registry=get_config_registry())

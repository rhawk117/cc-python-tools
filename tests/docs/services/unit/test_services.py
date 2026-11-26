from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING

import anyio
import pytest
from python_agent_tools_docs.composition import ServiceOptions, open_documentation_service
from python_agent_tools_docs.domain import PythonVersion, create_python_version
from python_agent_tools_docs.errors import CallDeadlineExceededError, VersionNotPublishedError
from python_agent_tools_docs.services import call_deadline
from python_agent_tools_docs.settings import Settings

from tests.docs.support.docs_site import DocsSite
from tests.docs.support.samples import DOCS_VERSION, standard_pages

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from python_agent_tools_docs.services import (
        DocumentationService,
    )

INVENTORY_PATH = f'/{DOCS_VERSION}/objects.inv'
PAGE_PATH = f'/{DOCS_VERSION}/library/os.path.html'


@dataclass(slots=True)
class Clock:
    now: float = 0

    def read(self) -> float:
        return self.now


@dataclass(slots=True, kw_only=True, frozen=True)
class ServiceHarness:
    site: DocsSite
    clock: Clock
    service: DocumentationService


def make_version(text: str) -> PythonVersion:
    version = create_python_version(text)
    assert isinstance(version, PythonVersion)
    return version


@asynccontextmanager
async def run_harness(pages: dict[str, bytes]) -> AsyncGenerator[ServiceHarness]:
    site = DocsSite(pages=pages)
    clock = Clock()
    options = ServiceOptions(transport=site.transport(), timer=clock.read)
    async with open_documentation_service(Settings(), options) as service:
        yield ServiceHarness(site=site, clock=clock, service=service)


class TestCatalog:
    version = make_version(DOCS_VERSION)

    @pytest.fixture
    async def harness(self) -> AsyncGenerator[ServiceHarness]:
        async with run_harness(standard_pages()) as harness:
            yield harness

    @pytest.fixture
    async def empty_harness(self) -> AsyncGenerator[ServiceHarness]:
        async with run_harness({}) as harness:
            yield harness

    async def test_a_second_request_is_served_from_memory(self, harness: ServiceHarness) -> None:
        await harness.service.catalog(self.version)
        await harness.service.catalog(self.version)
        assert harness.site.request_count(INVENTORY_PATH) == 1

    async def test_concurrent_requests_share_one_download(self, harness: ServiceHarness) -> None:
        async with anyio.create_task_group() as callers:
            for _ in range(3):
                callers.start_soon(harness.service.catalog, self.version)
        assert harness.site.request_count(INVENTORY_PATH) == 1

    async def test_a_missing_version_is_remembered_for_the_miss_ttl(
        self, empty_harness: ServiceHarness
    ) -> None:
        harness = empty_harness
        for _ in range(2):
            with pytest.raises(VersionNotPublishedError):
                await harness.service.catalog(self.version)
        requests_inside_window = harness.site.request_count(INVENTORY_PATH)
        harness.clock.now = Settings().missing_version_ttl_seconds + 1
        with pytest.raises(VersionNotPublishedError):
            await harness.service.catalog(self.version)
        assert (requests_inside_window, harness.site.request_count(INVENTORY_PATH)) == (1, 2)


class TestSection:
    version = make_version(DOCS_VERSION)

    @pytest.fixture
    async def harness(self) -> AsyncGenerator[ServiceHarness]:
        async with run_harness(standard_pages()) as harness:
            yield harness

    async def test_a_second_read_is_served_from_memory(self, harness: ServiceHarness) -> None:
        catalog = await harness.service.catalog(self.version)
        symbol = catalog.index.symbols['os.path.join']
        first = await harness.service.section(symbol)
        second = await harness.service.section(symbol)
        assert (first == second, harness.site.request_count(PAGE_PATH)) == (True, 1)


class TestCallDeadline:
    async def test_an_overrun_raises_the_deadline_error(self) -> None:
        with pytest.raises(CallDeadlineExceededError), call_deadline(0.01):
            await anyio.sleep(1)

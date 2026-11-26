from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, override

import anyio
import httpx2
import pytest
from python_agent_tools_core.version import PythonVersion, create_python_version
from python_docs_mcp.core.exception import CallDeadlineExceededError, VersionNotPublishedError
from python_docs_mcp.lifespan import ServiceOptions, open_documentation_service
from python_docs_mcp.schemas.settings import Settings
from python_docs_mcp.services.documentation_service import call_deadline
from python_docs_mcp.stores.disk_cache import NullInventoryStore

from tests.docs.support.docs_site import DocsSite
from tests.docs.support.samples import DOCS_VERSION, standard_pages

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from python_docs_mcp.services.documentation_service import (
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


@dataclass(slots=True, kw_only=True)
class RecordingStore:
    stored: bytes | None = None
    writes: dict[str, bytes] = field(default_factory=dict)

    def read(self, version: PythonVersion) -> bytes | None:
        return self.stored if version.text == DOCS_VERSION else None

    def write(self, version: PythonVersion, content: bytes) -> None:
        self.writes[version.text] = content


@asynccontextmanager
async def run_harness(
    pages: dict[str, bytes], store: RecordingStore | None = None
) -> AsyncGenerator[ServiceHarness]:
    site = DocsSite(pages=pages)
    clock = Clock()
    options = ServiceOptions(
        transport=site.transport(), timer=clock.read, store=store or NullInventoryStore()
    )
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


class TestCatalogLoader:
    version = make_version(DOCS_VERSION)

    async def test_a_fetched_inventory_is_written_to_the_store(self) -> None:
        store = RecordingStore()
        async with run_harness(standard_pages(), store) as harness:
            catalog = await harness.service.catalog(self.version)
        assert 'os.path.join' in catalog.index.symbols
        assert store.writes == {DOCS_VERSION: standard_pages()[INVENTORY_PATH]}

    async def test_a_stored_inventory_is_parsed_without_a_request(self) -> None:
        store = RecordingStore(stored=standard_pages()[INVENTORY_PATH])
        async with run_harness({}, store) as harness:
            catalog = await harness.service.catalog(self.version)
        assert 'os.path.join' in catalog.index.symbols
        assert (harness.site.request_count(INVENTORY_PATH), store.writes) == (0, {})

    async def test_an_unpublished_version_is_named(self) -> None:
        async with run_harness({}) as harness:
            with pytest.raises(VersionNotPublishedError, match=DOCS_VERSION):
                await harness.service.catalog(self.version)


class TestStoredCatalog:
    version = make_version(DOCS_VERSION)

    async def test_an_empty_store_gives_nothing_and_requests_nothing(self) -> None:
        async with run_harness(standard_pages(), RecordingStore()) as harness:
            assert await harness.service.stored_catalog(self.version) is None
        assert harness.site.request_count(INVENTORY_PATH) == 0

    async def test_a_stored_inventory_is_parsed(self) -> None:
        store = RecordingStore(stored=standard_pages()[INVENTORY_PATH])
        async with run_harness({}, store) as harness:
            catalog = await harness.service.stored_catalog(self.version)
        assert catalog is not None
        assert 'os.path.join' in catalog.index.symbols


class TestStoredCatalogCaching:
    version = make_version(DOCS_VERSION)

    async def test_a_second_completion_does_not_parse_again(self) -> None:
        store = RecordingStore(stored=standard_pages()[INVENTORY_PATH])
        async with run_harness({}, store) as harness:
            first = await harness.service.stored_catalog(self.version)
            store.stored = None
            second = await harness.service.stored_catalog(self.version)
        assert first is not None
        assert second is first

    async def test_the_parser_limiter_is_sized_by_settings(self) -> None:
        options = ServiceOptions(transport=DocsSite(pages={}).transport())
        async with open_documentation_service(Settings(parse_concurrency=3), options) as service:
            assert service.loader.parsers.total_tokens == 3


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


class HangingClose(httpx2.AsyncBaseTransport):
    @override
    async def handle_async_request(self, request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(httpx2.codes.OK, request=request)

    @override
    async def aclose(self) -> None:
        await anyio.sleep_forever()


@dataclass(slots=True, eq=False)
class RecordingClose(httpx2.AsyncBaseTransport):
    closed: bool = False

    @override
    async def aclose(self) -> None:
        self.closed = True


class BodyFailedError(Exception):
    pass


class TestShutdown:
    async def test_a_raising_body_still_closes_the_http_client(self) -> None:
        transport = RecordingClose()
        options = ServiceOptions(transport=transport, store=NullInventoryStore())
        with pytest.RaisesGroup(BodyFailedError):
            async with open_documentation_service(Settings(), options):
                raise BodyFailedError
        assert transport.closed

    async def test_a_hanging_client_close_is_abandoned_after_the_shutdown_timeout(self) -> None:
        options = ServiceOptions(transport=HangingClose(), store=NullInventoryStore())
        settings = Settings(shutdown_timeout_seconds=0.05)
        with anyio.fail_after(2):
            async with open_documentation_service(settings, options):
                pass


class TestCallDeadline:
    async def test_an_overrun_raises_the_deadline_error(self) -> None:
        with pytest.raises(CallDeadlineExceededError), call_deadline(0.01):
            await anyio.sleep(1)

import logging
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import anyio
import pytest
from anyio.lowlevel import checkpoint
from mcp import Client
from python_docs_mcp.adapters import progress
from python_docs_mcp.composition import ServiceOptions, open_documentation_service
from python_docs_mcp.schemas.domain_types import PythonVersion
from python_docs_mcp.schemas.settings import Settings
from python_docs_mcp.server import build_server

from tests.docs.support.docs_site import DocsSite
from tests.docs.support.samples import DOCS_VERSION, inventory_bytes, standard_pages

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from mcp.server import mcpserver
    from python_docs_mcp.services.documentation_service import DocumentationService

INVENTORY_PATH = f'/{DOCS_VERSION}/objects.inv'
SEARCH_TOOL = 'search_python_docs'
READ_TOOL = 'read_python_docs'
CHUNK_BYTES = 64


@dataclass(slots=True, kw_only=True, eq=False)
class ProgressLog:
    events: list[tuple[float, float | None]] = field(default_factory=list)
    messages: list[str | None] = field(default_factory=list)

    async def record(self, progress: float, total: float | None, message: str | None) -> None:
        self.events.append((progress, total))
        self.messages.append(message)


@dataclass(frozen=True, slots=True, kw_only=True)
class StoredInventory:
    content: bytes

    def read(self, version: PythonVersion) -> bytes | None:
        return self.content if version.text == DOCS_VERSION else None

    def write(self, version: PythonVersion, content: bytes) -> None: ...


@dataclass(frozen=True, slots=True, kw_only=True, eq=False)
class SharedService:
    site: DocsSite
    service: DocumentationService
    server: mcpserver.MCPServer


@asynccontextmanager
async def open_shared_service(
    site: DocsSite, options: ServiceOptions | None = None
) -> AsyncGenerator[SharedService]:
    options = options or ServiceOptions()
    options = ServiceOptions(transport=site.transport(), store=options.store)
    settings = Settings(download_chunk_bytes=CHUNK_BYTES)
    async with open_documentation_service(settings, options) as service:
        yield SharedService(site=site, service=service, server=build_server(service, {}))


@asynccontextmanager
async def open_client(
    site: DocsSite, options: ServiceOptions | None = None
) -> AsyncGenerator[Client]:
    async with (
        open_shared_service(site, options) as shared,
        Client(shared.server) as client,
    ):
        yield client


class TestInventoryProgress:
    inventory = inventory_bytes()

    def search_arguments(self) -> dict[str, str]:
        return {'version': DOCS_VERSION, 'query': 'os.path.join'}

    @pytest.fixture
    async def client(self) -> AsyncGenerator[Client]:
        async with open_client(DocsSite(pages=standard_pages())) as client:
            yield client

    @pytest.fixture
    async def unsized_client(self) -> AsyncGenerator[Client]:
        site = DocsSite(pages=standard_pages(), unsized=frozenset({INVENTORY_PATH}))
        async with open_client(site) as client:
            yield client

    @pytest.fixture
    async def stored_client(self) -> AsyncGenerator[Client]:
        options = ServiceOptions(store=StoredInventory(content=self.inventory))
        async with open_client(DocsSite(pages=standard_pages()), options) as client:
            yield client

    @pytest.fixture
    def log(self) -> ProgressLog:
        return ProgressLog()

    async def test_a_cold_search_reports_bytes_read_against_the_content_length(
        self, client: Client, log: ProgressLog
    ) -> None:
        await client.call_tool(SEARCH_TOOL, self.search_arguments(), progress_callback=log.record)
        total = float(len(self.inventory))
        assert len(log.events) > 1
        assert {event[1] for event in log.events} == {total}
        assert log.events[-1][0] == total

    async def test_a_cold_read_reports_progress(self, client: Client, log: ProgressLog) -> None:
        arguments = {'version': DOCS_VERSION, 'symbol': 'os.path.join'}
        await client.call_tool(READ_TOOL, arguments, progress_callback=log.record)
        assert log.events[-1][0] == float(len(self.inventory))

    async def test_a_catalog_in_memory_reports_nothing(
        self, client: Client, log: ProgressLog
    ) -> None:
        await client.call_tool(SEARCH_TOOL, self.search_arguments())
        await client.call_tool(SEARCH_TOOL, self.search_arguments(), progress_callback=log.record)
        assert log.events == []

    async def test_a_catalog_from_the_disk_store_reports_nothing(
        self, stored_client: Client, log: ProgressLog
    ) -> None:
        await stored_client.call_tool(
            SEARCH_TOOL, self.search_arguments(), progress_callback=log.record
        )
        assert log.events == []

    async def test_a_response_without_content_length_reports_bytes_with_no_total(
        self, unsized_client: Client, log: ProgressLog
    ) -> None:
        await unsized_client.call_tool(
            SEARCH_TOOL, self.search_arguments(), progress_callback=log.record
        )
        assert log.events[-1] == (float(len(self.inventory)), None)
        assert {event[1] for event in log.events} == {None}


@dataclass(frozen=True, slots=True, kw_only=True, eq=False)
class ClientRun:
    first_log: ProgressLog
    second_log: ProgressLog
    starter: anyio.CancelScope
    results: list[bool]


@dataclass(frozen=True, slots=True, kw_only=True, eq=False)
class WatcherWait:
    service: DocumentationService
    version: PythonVersion
    expected: int

    async def until_ready(self) -> None:
        while self.service.board.watcher_count(self.version) < self.expected:
            await checkpoint()


class TestConcurrentProgress:
    inventory = inventory_bytes()
    bound_seconds = 10
    expected_watchers = 2
    board_logger = progress.logger.name

    @pytest.fixture
    async def shared(self) -> AsyncGenerator[SharedService]:
        async with open_shared_service(DocsSite(pages=standard_pages())) as shared:
            yield shared

    @pytest.fixture
    async def held(self) -> AsyncGenerator[SharedService]:
        site = DocsSite(pages=standard_pages(), held=INVENTORY_PATH)
        async with open_shared_service(site) as held:
            yield held

    @pytest.fixture
    async def run(self) -> ClientRun:
        return ClientRun(
            first_log=ProgressLog(),
            second_log=ProgressLog(),
            starter=anyio.CancelScope(),
            results=[],
        )

    @pytest.fixture
    def watchers(self, held: SharedService) -> WatcherWait:
        version = PythonVersion(text=DOCS_VERSION)
        return WatcherWait(service=held.service, version=version, expected=self.expected_watchers)

    async def search_with_progress(
        self, server: mcpserver.MCPServer, log: ProgressLog, results: list[bool]
    ) -> None:
        async with Client(server) as client:
            result = await client.call_tool(
                SEARCH_TOOL,
                {'version': DOCS_VERSION, 'query': 'os.path.join'},
                progress_callback=log.record,
            )
        results.append(not result.is_error)

    async def search_until_cancelled(
        self, server: mcpserver.MCPServer, log: ProgressLog, scope: anyio.CancelScope
    ) -> None:
        with scope:
            await self.search_with_progress(server, log, [])

    async def test_two_clients_searching_the_same_cold_version_both_get_progress(
        self, shared: SharedService, run: ClientRun
    ) -> None:
        async with anyio.create_task_group() as clients:
            for log in (run.first_log, run.second_log):
                clients.start_soon(self.search_with_progress, shared.server, log, run.results)
        assert run.results == [True, True]
        assert [bool(run.first_log.events), bool(run.second_log.events)] == [True, True]
        assert shared.site.request_count(INVENTORY_PATH) == 1

    async def test_a_normal_search_logs_no_progress_board_warning(
        self, shared: SharedService, run: ClientRun, caplog: pytest.LogCaptureFixture
    ) -> None:
        with caplog.at_level(logging.WARNING, logger=self.board_logger):
            async with anyio.create_task_group() as clients:
                for log in (run.first_log, run.second_log):
                    clients.start_soon(self.search_with_progress, shared.server, log, run.results)
        assert run.results == [True, True]
        assert [r for r in caplog.records if r.name == self.board_logger] == []

    async def test_cancelling_the_client_that_started_a_shared_download_spares_the_other(
        self, held: SharedService, run: ClientRun, watchers: WatcherWait
    ) -> None:
        with anyio.fail_after(self.bound_seconds):
            async with anyio.create_task_group() as clients:
                clients.start_soon(
                    self.search_until_cancelled, held.server, run.first_log, run.starter
                )
                await held.site.wait_until_hold_engaged()
                clients.start_soon(
                    self.search_with_progress, held.server, run.second_log, run.results
                )
                await watchers.until_ready()
                run.starter.cancel()
                held.site.release()
        assert run.results == [True]
        assert run.second_log.events[-1][0] == float(len(self.inventory))
        assert held.site.request_count(INVENTORY_PATH) == 1

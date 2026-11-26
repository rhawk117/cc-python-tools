from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import anyio
import pytest
from mcp import Client
from python_agent_tools_docs.composition import ServiceOptions, open_documentation_service
from python_agent_tools_docs.server import build_server
from python_agent_tools_docs.settings import Settings

from tests.docs.support.docs_site import DocsSite
from tests.docs.support.samples import DOCS_VERSION, inventory_bytes, standard_pages

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from mcp.server import mcpserver
    from python_agent_tools_docs.domain import PythonVersion

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


@asynccontextmanager
async def open_client(
    site: DocsSite, options: ServiceOptions | None = None
) -> AsyncGenerator[Client]:
    settings = Settings(download_chunk_bytes=CHUNK_BYTES)
    options = options or ServiceOptions()
    options = ServiceOptions(transport=site.transport(), store=options.store)
    async with (
        open_documentation_service(settings, options) as service,
        Client(build_server(service, {})) as client,
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


class TestConcurrentProgress:
    inventory = inventory_bytes()

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

    async def test_two_clients_searching_the_same_cold_version_both_get_progress(self) -> None:
        site = DocsSite(pages=standard_pages())
        options = ServiceOptions(transport=site.transport())
        logs = [ProgressLog(), ProgressLog()]
        results: list[bool] = []
        async with open_documentation_service(
            Settings(download_chunk_bytes=CHUNK_BYTES), options
        ) as service:
            server = build_server(service, {})
            async with anyio.create_task_group() as clients:
                for log in logs:
                    clients.start_soon(self.search_with_progress, server, log, results)
        assert results == [True, True]
        assert [bool(log.events) for log in logs] == [True, True]
        assert site.request_count(INVENTORY_PATH) == 1

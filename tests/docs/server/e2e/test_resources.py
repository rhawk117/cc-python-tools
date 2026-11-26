from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING

import pytest
from mcp import Client
from mcp.shared.exceptions import MCPError
from mcp.types import (
    PromptReference,
    ResourceTemplateReference,
    TextContent,
    TextResourceContents,
)
from python_agent_tools_docs.completions import RESOURCE_URI
from python_agent_tools_docs.composition import ServiceOptions, open_documentation_service
from python_agent_tools_docs.disk_cache import DATA_DIRECTORY_VARIABLE, create_inventory_store
from python_agent_tools_docs.project import PROJECT_ROOT_VARIABLE
from python_agent_tools_docs.server import build_server
from python_agent_tools_docs.settings import Settings

from tests.docs.support.docs_site import DocsSite
from tests.docs.support.samples import DOCS_VERSION, standard_pages

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Mapping
    from pathlib import Path

    import httpx2
    from python_agent_tools_docs.domain import PythonVersion

READ_TOOL = 'read_python_docs'
TEMPLATE = ResourceTemplateReference(uri=RESOURCE_URI)


@asynccontextmanager
async def open_client(
    transport: httpx2.AsyncBaseTransport, environment: Mapping[str, str] | None = None
) -> AsyncGenerator[Client]:
    async with (
        open_documentation_service(Settings(), ServiceOptions(transport=transport)) as service,
        Client(build_server(service, environment or {})) as client,
    ):
        yield client


async def complete(client: Client, name: str, value: str, resolved: dict[str, str]) -> list[str]:
    result = await client.complete(TEMPLATE, {'name': name, 'value': value}, resolved)
    return result.completion.values


@pytest.fixture
def site() -> DocsSite:
    return DocsSite(pages=standard_pages())


@pytest.fixture
async def client(site: DocsSite) -> AsyncGenerator[Client]:
    async with open_client(site.transport()) as client:
        yield client


@pytest.fixture
async def floor_client(site: DocsSite, tmp_path: Path) -> AsyncGenerator[Client]:
    tmp_path.joinpath('pyproject.toml').write_text(
        '[project]\nrequires-python = ">=3.12"\n', encoding='utf-8'
    )
    async with open_client(site.transport(), {PROJECT_ROOT_VARIABLE: str(tmp_path)}) as client:
        yield client


class TestTemplate:
    async def test_the_template_is_listed(self, client: Client) -> None:
        listed = await client.list_resource_templates()
        assert [template.uri_template for template in listed.resource_templates] == [RESOURCE_URI]

    async def test_reading_returns_the_whole_section_the_tool_returns(self, client: Client) -> None:
        uri = f'python-docs://{DOCS_VERSION}/os.path.join'
        resource = await client.read_resource(uri)
        content = resource.contents[0]
        tool = await client.call_tool(
            READ_TOOL, {'version': DOCS_VERSION, 'symbol': 'os.path.join', 'max_chars': 12_000}
        )
        page = tool.content[0]
        assert isinstance(content, TextResourceContents)
        assert isinstance(page, TextContent)
        assert content.text in page.text

    async def test_an_unknown_symbol_is_a_resource_error(self, client: Client) -> None:
        with pytest.raises(MCPError, match='Unknown symbol'):
            await client.read_resource(f'python-docs://{DOCS_VERSION}/os.path.nope')


class TestVersionCompletions:
    async def test_the_whole_window_is_offered_without_a_prefix(self, client: Client) -> None:
        values = await complete(client, 'version', '', {})
        assert values == [f'3.{minor}' for minor in range(10, 16)]

    async def test_the_typed_prefix_filters_the_window(self, client: Client) -> None:
        assert await complete(client, 'version', '3.1', {}) == [f'3.1{n}' for n in range(6)]

    async def test_the_project_floor_comes_first(self, floor_client: Client) -> None:
        values = await complete(floor_client, 'version', '', {})
        assert values[:2] == ['3.12', '3.10']

    async def test_another_template_gets_no_values(self, client: Client) -> None:
        other = ResourceTemplateReference(uri='other://{version}')
        result = await client.complete(other, {'name': 'version', 'value': ''})
        assert result.completion.values == []

    async def test_a_prompt_reference_gets_no_values(self, client: Client) -> None:
        result = await client.complete(
            PromptReference(name='anything'), {'name': 'version', 'value': ''}
        )
        assert result.completion.values == []


class TestSymbolCompletions:
    async def test_nothing_is_loaded_so_nothing_is_offered_and_nothing_is_fetched(
        self, client: Client, site: DocsSite
    ) -> None:
        values = await complete(client, 'symbol', 'os', {'version': DOCS_VERSION})
        assert (values, site.requested_urls) == ([], [])

    async def test_a_loaded_inventory_supplies_the_symbols(self, client: Client) -> None:
        await client.read_resource(f'python-docs://{DOCS_VERSION}/os.path')
        values = await complete(client, 'symbol', 'os.path.', {'version': DOCS_VERSION})
        assert values == ['os.path.isfile', 'os.path.join']

    async def test_another_version_stays_empty(self, client: Client) -> None:
        await client.read_resource(f'python-docs://{DOCS_VERSION}/os.path')
        assert await complete(client, 'symbol', 'os', {'version': '3.12'}) == []

    async def test_an_inventory_in_the_disk_store_is_used_without_the_network(
        self, site: DocsSite, tmp_path: Path
    ) -> None:
        store = create_inventory_store({DATA_DIRECTORY_VARIABLE: str(tmp_path)}, 3600)
        warm = ServiceOptions(transport=site.transport(), store=store)
        async with (
            open_documentation_service(Settings(), warm) as service,
            Client(build_server(service, {})) as client,
        ):
            await client.read_resource(f'python-docs://{DOCS_VERSION}/os.path')

        cold_site = DocsSite(pages={})
        cold = ServiceOptions(transport=cold_site.transport(), store=store)
        async with (
            open_documentation_service(Settings(), cold) as service,
            Client(build_server(service, {})) as client,
        ):
            values = await complete(client, 'symbol', 'os.path.j', {'version': DOCS_VERSION})
        assert (values, cold_site.requested_urls) == (['os.path.join'], [])


@dataclass(frozen=True, slots=True, kw_only=True)
class ExpiredEntryStore:
    def read(self, version: PythonVersion) -> bytes | None: ...

    def write(self, version: PythonVersion, content: bytes) -> None: ...

    def contains(self, version: PythonVersion) -> bool:
        return version.text == DOCS_VERSION


class TestExpiredEntryRace:
    async def test_an_entry_that_expires_after_the_presence_check_starts_no_fetch(
        self, site: DocsSite
    ) -> None:
        options = ServiceOptions(transport=site.transport(), store=ExpiredEntryStore())
        async with (
            open_documentation_service(Settings(), options) as service,
            Client(build_server(service, {})) as client,
        ):
            values = await complete(client, 'symbol', 'os', {'version': DOCS_VERSION})
        assert (values, site.requested_urls) == ([], [])

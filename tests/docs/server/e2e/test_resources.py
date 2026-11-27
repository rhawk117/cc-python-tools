import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

import pytest
from mcp import Client
from mcp.shared.exceptions import MCPError
from mcp.types import (
    CompletionArgument,
    PromptReference,
    ResourceTemplateReference,
    TextContent,
    TextResourceContents,
)
from python_agent_tools_core.project import PROJECT_ROOT_VARIABLE
from python_docs_mcp.app import complete_documentation, python_docs
from python_docs_mcp.core.exception import ServiceUnavailableError
from python_docs_mcp.lifespan import ServiceOptions
from python_docs_mcp.services.completions import RESOURCE_URI
from python_docs_mcp.stores.disk_cache import DATA_DIRECTORY_VARIABLE, create_inventory_store

from tests.docs.support.docs_site import DocsSite
from tests.docs.support.samples import (
    DOCS_VERSION,
    FILLER_SENTENCE,
    OS_PATH_PAGE,
    InventoryEntry,
    inventory_bytes,
    standard_pages,
)

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator
    from pathlib import Path

    from python_agent_tools_core.version import PythonVersion
    from python_docs_mcp.lifespan import ServerConfig

    from tests.docs.support.server import ServerHarness

READ_TOOL = 'read_python_docs'
NEXT_OFFSET = re.compile(r'offset=(\d+)')
TEMPLATE = ResourceTemplateReference(uri=RESOURCE_URI)


async def complete(client: Client, name: str, value: str, resolved: dict[str, str]) -> list[str]:
    result = await client.complete(TEMPLATE, {'name': name, 'value': value}, resolved)
    return result.completion.values


@pytest.fixture
def site() -> DocsSite:
    return DocsSite(pages=standard_pages())


@pytest.fixture
def long_site() -> DocsSite:
    pages = standard_pages()
    long_page = OS_PATH_PAGE.replace(FILLER_SENTENCE * 40, FILLER_SENTENCE * 400)
    pages[f'/{DOCS_VERSION}/library/os.path.html'] = long_page.encode()
    return DocsSite(pages=pages)


@pytest.fixture
async def long_client(harness: ServerHarness, long_site: DocsSite) -> AsyncGenerator[Client]:
    async with harness.connect(options=ServiceOptions(transport=long_site.transport())) as client:
        assert isinstance(client, Client)
        yield client


@pytest.fixture
async def client(harness: ServerHarness, site: DocsSite) -> AsyncGenerator[Client]:
    async with harness.connect(options=ServiceOptions(transport=site.transport())) as client:
        assert isinstance(client, Client)
        yield client


@pytest.fixture
async def floor_client(
    harness: ServerHarness, site: DocsSite, tmp_path: Path
) -> AsyncGenerator[Client]:
    tmp_path.joinpath('pyproject.toml').write_text(
        '[project]\nrequires-python = ">=3.12"\n', encoding='utf-8'
    )
    options = ServiceOptions(transport=site.transport())
    environment = {PROJECT_ROOT_VARIABLE: str(tmp_path)}
    async with harness.connect(options=options, environment=environment) as client:
        assert isinstance(client, Client)
        yield client


class TestTemplate:
    async def test_the_template_is_listed(self, client: Client) -> None:
        listed = await client.list_resource_templates()
        assert [template.uri_template for template in listed.resource_templates] == [RESOURCE_URI]

    async def test_the_template_description_is_the_function_docstring(self, client: Client) -> None:
        listed = await client.list_resource_templates()
        assert [template.description for template in listed.resource_templates] == [
            python_docs.__doc__
        ]

    async def test_an_unknown_symbol_is_a_resource_error(self, client: Client) -> None:
        with pytest.raises(MCPError, match='Unknown symbol'):
            await client.read_resource(f'python-docs://{DOCS_VERSION}/os.path.nope')


class TestPaging:
    uri = f'python-docs://{DOCS_VERSION}/os.path'

    async def read_resource_text(self, client: Client, uri: str) -> str:
        resource = await client.read_resource(uri)
        content = resource.contents[0]
        assert isinstance(content, TextResourceContents)
        return content.text

    async def read_tool_text(self, client: Client, offset: int) -> str:
        arguments = {
            'model_params': {'version': DOCS_VERSION, 'symbol': 'os.path', 'offset': offset}
        }
        tool = await client.call_tool(READ_TOOL, arguments)
        page = tool.content[0]
        assert isinstance(page, TextContent)
        return page.text

    def drop_footer(self, text: str) -> str:
        return text.rpartition('\n\n')[0]

    async def test_a_short_section_is_one_page_that_ends(self, client: Client) -> None:
        text = await self.read_resource_text(client, self.uri)
        assert text.splitlines()[-1].startswith('End of section')

    async def test_each_next_offset_reproduces_the_tool_pages_to_the_end(
        self, long_client: Client
    ) -> None:
        pages: list[tuple[str, str]] = []
        resource = ''
        offset = 0
        while offset is not None:
            resource = await self.read_resource_text(long_client, f'{self.uri}?offset={offset}')
            tool = await self.read_tool_text(long_client, offset)
            pages.append((self.drop_footer(resource), self.drop_footer(tool)))
            following = NEXT_OFFSET.search(resource.splitlines()[-1])
            offset = int(following.group(1)) if following else None
        assert len(pages) > 1
        assert resource.splitlines()[-1].startswith('End of section')
        assert all(resource == tool for resource, tool in pages)

    async def test_the_footer_names_the_next_resource_uri(self, long_client: Client) -> None:
        text = await self.read_resource_text(long_client, self.uri)
        assert f'read {self.uri}?offset=' in text.splitlines()[-1]

    async def test_an_offset_past_the_section_end_is_a_resource_error(self, client: Client) -> None:
        with pytest.raises(MCPError, match='past the end of the section'):
            await client.read_resource(f'{self.uri}?offset=1000000')

    async def test_a_malformed_offset_is_a_resource_error_without_raw_validation_text(
        self, client: Client
    ) -> None:
        with pytest.raises(MCPError, match='offset must be ') as raised:
            await client.read_resource(f'{self.uri}?offset=-1')
        assert 'pydantic' not in raised.value.error.message

    async def test_a_non_numeric_offset_is_a_resource_error_without_raw_validation_text(
        self, client: Client
    ) -> None:
        with pytest.raises(MCPError, match='offset must be ') as raised:
            await client.read_resource(f'{self.uri}?offset=abc')
        assert 'pydantic' not in raised.value.error.message


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


class TestOffsetCompletions:
    async def test_the_first_page_is_offered(self, client: Client) -> None:
        assert await complete(client, 'offset', '', {'version': DOCS_VERSION}) == ['0']

    async def test_a_prefix_that_is_not_zero_offers_nothing(self, client: Client) -> None:
        assert await complete(client, 'offset', '5', {}) == []


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
        self, harness: ServerHarness, site: DocsSite, tmp_path: Path
    ) -> None:
        store = create_inventory_store({DATA_DIRECTORY_VARIABLE: str(tmp_path)}, 3600)
        warm = ServiceOptions(transport=site.transport(), store=store)
        async with harness.connect(options=warm) as client:
            await client.read_resource(f'python-docs://{DOCS_VERSION}/os.path')

        cold_site = DocsSite(pages={})
        cold = ServiceOptions(transport=cold_site.transport(), store=store)
        async with harness.connect(options=cold) as client:
            values = await complete(client, 'symbol', 'os.path.j', {'version': DOCS_VERSION})
        assert (values, cold_site.requested_urls) == (['os.path.join'], [])


@dataclass(frozen=True, slots=True, kw_only=True)
class ExpiredEntryStore:
    def read(self, version: PythonVersion) -> bytes | None: ...

    def write(self, version: PythonVersion, content: bytes) -> None: ...


@dataclass(frozen=True, slots=True, kw_only=True)
class BulkInventoryStore:
    symbol_count: int

    def read(self, version: PythonVersion) -> bytes | None:
        entries = [
            InventoryEntry(name=f'bulk.symbol{number}', uri='library/bulk.html#$')
            for number in range(self.symbol_count)
        ]
        return inventory_bytes(entries) if version.text == DOCS_VERSION else None

    def write(self, version: PythonVersion, content: bytes) -> None: ...


class TestCompletionCap:
    symbol_count = 150
    cap = 100

    async def test_more_matches_than_the_cap_return_the_cap_and_flag_more(
        self, harness: ServerHarness, site: DocsSite
    ) -> None:
        store = BulkInventoryStore(symbol_count=self.symbol_count)
        options = ServiceOptions(transport=site.transport(), store=store)
        async with harness.connect(options=options) as client:
            result = await client.complete(
                TEMPLATE, {'name': 'symbol', 'value': 'bulk.'}, {'version': DOCS_VERSION}
            )
        assert (len(result.completion.values), result.completion.has_more) == (self.cap, True)


class TestExpiredEntryRace:
    async def test_an_expired_stored_entry_yields_no_values_and_no_request(
        self, harness: ServerHarness, site: DocsSite
    ) -> None:
        options = ServiceOptions(transport=site.transport(), store=ExpiredEntryStore())
        async with harness.connect(options=options) as client:
            values = await complete(client, 'symbol', 'os', {'version': DOCS_VERSION})
        assert (values, site.requested_urls) == ([], [])


@dataclass(frozen=True, slots=True, kw_only=True, eq=False)
class ForbiddenConfigProvider:
    def provide_config(self) -> ServerConfig:
        message = 'a completion must not read the configuration again'
        raise AssertionError(message)


class TestCompletionFromLifespanState:
    async def test_a_completion_reads_no_configuration_after_startup(
        self, harness: ServerHarness, client: Client
    ) -> None:
        await client.read_resource(f'python-docs://{DOCS_VERSION}/os.path')
        with harness.registry.override(ForbiddenConfigProvider()):
            assert await complete(client, 'version', '3.1', {}) == [f'3.1{n}' for n in range(6)]
            symbols = await complete(client, 'symbol', 'os.path.j', {'version': DOCS_VERSION})
        assert symbols == ['os.path.join']


class TestCompletionWithoutService:
    async def test_a_completion_with_no_service_attached_is_a_domain_error(self) -> None:
        argument = CompletionArgument(name='symbol', value='os')
        with pytest.raises(ServiceUnavailableError):
            await complete_documentation(TEMPLATE, argument, None)

import json
from typing import TYPE_CHECKING

import anyio
import httpx2
import pytest
from mcp import Client
from mcp.types import TextContent
from python_agent_tools_core.project import PROJECT_ROOT_VARIABLE
from python_docs_mcp.lifespan import ServiceOptions
from python_docs_mcp.schemas.settings import Settings

from tests.docs.support.docs_site import DocsSite
from tests.docs.support.samples import DOCS_VERSION, standard_pages

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator
    from pathlib import Path

    from mcp.types import CallToolResult

    from tests.docs.conftest import ServerHarness

SEARCH_TOOL = 'search_python_docs'
READ_TOOL = 'read_python_docs'


async def stalled(request: httpx2.Request) -> httpx2.Response:
    await anyio.sleep(10)
    return httpx2.Response(httpx2.codes.OK, request=request)


def first_text(result: CallToolResult) -> str:
    block = result.content[0]
    assert isinstance(block, TextContent)
    return block.text


@pytest.fixture
async def client(harness: ServerHarness) -> AsyncGenerator[Client]:
    site = DocsSite(pages=standard_pages())
    options = ServiceOptions(transport=site.transport())
    async with harness.connect(options=options) as client:
        assert isinstance(client, Client)
        yield client


@pytest.fixture
async def stalled_client(harness: ServerHarness) -> AsyncGenerator[Client]:
    options = ServiceOptions(transport=httpx2.MockTransport(stalled))
    settings = Settings(call_timeout_seconds=0.05)
    async with harness.connect(settings=settings, options=options) as client:
        assert isinstance(client, Client)
        yield client


@pytest.fixture
async def floor_client(harness: ServerHarness, tmp_path: Path) -> AsyncGenerator[Client]:
    tmp_path.joinpath('pyproject.toml').write_text(
        '[project]\nrequires-python = ">=3.13"\n', encoding='utf-8'
    )
    site = DocsSite(pages=standard_pages())
    options = ServiceOptions(transport=site.transport())
    environment = {PROJECT_ROOT_VARIABLE: str(tmp_path)}
    async with harness.connect(options=options, environment=environment) as client:
        assert isinstance(client, Client)
        yield client


class TestListing:
    async def test_exactly_the_two_documentation_tools_are_listed(self, client: Client) -> None:
        listed = await client.list_tools()
        assert sorted(tool.name for tool in listed.tools) == [READ_TOOL, SEARCH_TOOL]

    async def test_both_tools_advertise_read_only_idempotent_open_world(
        self, client: Client
    ) -> None:
        listed = await client.list_tools()
        hints = [
            (tool.annotations.read_only_hint, tool.annotations.idempotent_hint)
            + (tool.annotations.open_world_hint,)
            for tool in listed.tools
            if tool.annotations is not None
        ]
        assert hints == [(True, True, True)] * 2

    async def test_the_search_limit_is_bounded_and_defaults_to_ten(self, client: Client) -> None:
        listed = await client.list_tools()
        search = next(tool for tool in listed.tools if tool.name == SEARCH_TOOL)
        schema = search.input_schema
        bound = schema['properties']['limit']['maximum']
        default = schema['properties']['limit']['default']
        assert (bound, default) == (30, 10)

    async def test_a_search_limit_above_thirty_is_rejected(self, client: Client) -> None:
        arguments = {'version': DOCS_VERSION, 'query': 'os.path', 'limit': 31}
        result = await client.call_tool(SEARCH_TOOL, arguments)
        assert result.is_error


class TestCalls:
    async def test_search_returns_structured_content_and_the_same_json_text(
        self, client: Client
    ) -> None:
        result = await client.call_tool(SEARCH_TOOL, {'version': DOCS_VERSION, 'query': 'os.path'})
        structured = result.structured_content
        assert structured is not None
        assert (result.is_error, structured['query']) == (False, 'os.path')
        assert structured == json.loads(first_text(result))

    async def test_search_without_a_limit_returns_at_most_ten_matches(self, client: Client) -> None:
        result = await client.call_tool(SEARCH_TOOL, {'version': DOCS_VERSION, 'query': 'o'})
        structured = result.structured_content
        assert structured is not None
        assert len(structured['matches']) <= 10

    async def test_read_frames_the_page_with_a_header_and_a_footer(self, client: Client) -> None:
        arguments = {'version': DOCS_VERSION, 'symbol': 'os.path', 'max_chars': 500}
        result = await client.call_tool(READ_TOOL, arguments)
        lines = first_text(result).splitlines()
        assert (
            lines[0].startswith('os.path (module) | Python 3.13'),
            'offset=' in lines[-1],
        ) == (
            True,
            True,
        )

    async def test_the_last_page_marks_the_end_of_the_section(self, client: Client) -> None:
        arguments = {'version': DOCS_VERSION, 'symbol': 'os.path.isfile'}
        result = await client.call_tool(READ_TOOL, arguments)
        assert first_text(result).splitlines()[-1].startswith('End of section')

    async def test_an_unknown_symbol_is_a_tool_error_with_its_message(self, client: Client) -> None:
        arguments = {'version': DOCS_VERSION, 'symbol': 'os.path.nope'}
        result = await client.call_tool(READ_TOOL, arguments)
        assert (
            result.is_error,
            'Unknown symbol' in first_text(result),
            first_text(result) == f'Error executing tool {READ_TOOL}',
        ) == (True, True, False)

    async def test_an_offset_past_the_section_end_is_a_tool_error_with_its_message(
        self, client: Client
    ) -> None:
        arguments = {'version': DOCS_VERSION, 'symbol': 'os.path.isfile', 'offset': 1_000_000}
        result = await client.call_tool(READ_TOOL, arguments)
        assert (result.is_error, 'exceeds the section length' in first_text(result)) == (True, True)

    async def test_a_call_past_its_deadline_is_a_tool_error(self, stalled_client: Client) -> None:
        arguments = {'version': DOCS_VERSION, 'query': 'os.path'}
        result = await stalled_client.call_tool(SEARCH_TOOL, arguments)
        assert (result.is_error, 'deadline' in first_text(result)) == (True, True)

    async def test_a_read_past_its_deadline_is_a_tool_error(self, stalled_client: Client) -> None:
        arguments = {'version': DOCS_VERSION, 'symbol': 'os.path'}
        result = await stalled_client.call_tool(READ_TOOL, arguments)
        assert (result.is_error, 'deadline' in first_text(result)) == (True, True)

    async def test_a_search_for_an_unpublished_version_is_a_tool_error_with_its_message(
        self, client: Client
    ) -> None:
        result = await client.call_tool(SEARCH_TOOL, {'version': '3.9', 'query': 'os.path'})
        assert (result.is_error, 'documentation is not published' in first_text(result)) == (
            True,
            True,
        )

    async def test_the_tool_inputs_exclude_the_injected_service(self, client: Client) -> None:
        listed = await client.list_tools()
        properties = {tool.name: set(tool.input_schema['properties']) for tool in listed.tools}
        assert properties == {
            SEARCH_TOOL: {'version', 'query', 'limit'},
            READ_TOOL: {'version', 'symbol', 'offset', 'max_chars'},
        }


class TestVersionDefault:
    async def test_the_version_input_is_optional_with_its_description_and_pattern(
        self, client: Client
    ) -> None:
        listed = await client.list_tools()
        for tool in listed.tools:
            version = tool.input_schema['properties']['version']
            variants = version.get('anyOf', [version])
            text = next(variant for variant in variants if variant.get('type') == 'string')
            assert (
                'version' in tool.input_schema.get('required', []),
                {'type': 'null'} in variants,
                'lower bound of the project' in text['description'],
                text['pattern'].startswith('^'),
            ) == (False, True, True, True), tool.name

    async def test_a_search_without_version_reads_the_project_floor(
        self, floor_client: Client
    ) -> None:
        result = await floor_client.call_tool(SEARCH_TOOL, {'query': 'os.path'})
        structured = result.structured_content
        assert structured is not None
        assert (result.is_error, structured['python_version']) == (False, DOCS_VERSION)

    async def test_a_read_without_version_reads_the_project_floor(
        self, floor_client: Client
    ) -> None:
        result = await floor_client.call_tool(READ_TOOL, {'symbol': 'os.path', 'max_chars': 500})
        assert first_text(result).startswith('os.path (module) | Python 3.13')

    async def test_an_explicit_version_wins_over_the_floor(self, floor_client: Client) -> None:
        arguments = {'version': '3.9', 'symbol': 'os.path'}
        result = await floor_client.call_tool(READ_TOOL, arguments)
        assert (result.is_error, '3.13' in first_text(result)) == (True, False)

    @pytest.mark.parametrize('tool', [SEARCH_TOOL, READ_TOOL])
    async def test_no_floor_is_a_tool_error_asking_for_version(
        self, client: Client, tool: str
    ) -> None:
        result = await client.call_tool(tool, {'query': 'os.path', 'symbol': 'os.path'})
        assert (result.is_error, 'Pass version' in first_text(result)) == (True, True)

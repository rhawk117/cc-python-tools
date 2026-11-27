from typing import TYPE_CHECKING, Any

import anyio
import pytest
from hypothesis import given
from hypothesis import strategies as st
from mcp import Client
from mcp.types import TextContent
from python_docs_mcp.lifespan import ServiceOptions, get_config_registry

from tests.docs.support.docs_site import DocsSite
from tests.docs.support.samples import DOCS_VERSION, standard_pages
from tests.docs.support.server import ServerHarness

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Mapping

    from _pytest.mark import ParameterSet
    from mcp.types import CallToolResult, Tool

SEARCH_TOOL = 'search_python_docs'
READ_TOOL = 'read_python_docs'
PYDANTIC_MARKERS = ('errors.pydantic.dev', 'Input should', 'String should', 'Field required')


def tool_name_cases() -> pytest.MarkDecorator:
    members: list[ParameterSet] = [
        pytest.param(SEARCH_TOOL, id=SEARCH_TOOL),
        pytest.param(READ_TOOL, id=READ_TOOL),
    ]
    return pytest.mark.parametrize('tool_name', members)


def first_text(result: CallToolResult) -> str:
    block = result.content[0]
    assert isinstance(block, TextContent)
    return block.text


async def call_tool(tool: str, arguments: Mapping[str, object]) -> CallToolResult:
    harness = ServerHarness(registry=get_config_registry())
    options = ServiceOptions(transport=DocsSite(pages=standard_pages()).transport())
    async with harness.connect(options=options) as client:
        return await client.call_tool(tool, {'model_params': arguments})


def invoke(tool: str, arguments: Mapping[str, object]) -> CallToolResult:
    return anyio.run(call_tool, tool, arguments)


def argument_definition(tool: Tool) -> dict[str, Any]:
    reference = tool.input_schema['properties']['model_params']['$ref']
    return tool.input_schema['$defs'][reference.rsplit('/', 1)[-1]]


@pytest.fixture
async def client(harness: ServerHarness) -> AsyncGenerator[Client]:
    options = ServiceOptions(transport=DocsSite(pages=standard_pages()).transport())
    async with harness.connect(options=options) as client:
        assert isinstance(client, Client)
        yield client


class TestArgumentErrors:
    out_of_range_limits = st.one_of(st.integers(max_value=0), st.integers(min_value=31))
    negative_offsets = st.integers(max_value=-1)
    out_of_range_page_sizes = st.one_of(st.integers(max_value=499), st.integers(min_value=12_001))
    overlong_queries = st.integers(min_value=201, max_value=400).map('q'.__mul__)
    overlong_symbols = st.integers(min_value=301, max_value=500).map('s'.__mul__)
    blank_text = st.text(alphabet=' \t\n', max_size=5)
    malformed_versions = st.text(alphabet='abc.-', min_size=1, max_size=8)
    non_numbers = st.text(alphabet='xyz', min_size=1, max_size=5)

    def assert_field_error(self, result: CallToolResult, field: str) -> None:
        text = first_text(result)
        assert result.is_error
        assert f'model_params.{field}\n  {field} ' in text
        assert not any(marker in text for marker in PYDANTIC_MARKERS)

    @given(limit=out_of_range_limits)
    def test_an_out_of_range_limit_names_the_limit_field(self, limit: int) -> None:
        arguments = {'version': DOCS_VERSION, 'query': 'os.path', 'limit': limit}
        self.assert_field_error(invoke(SEARCH_TOOL, arguments), 'limit')

    @given(limit=non_numbers)
    def test_a_limit_of_the_wrong_type_names_the_limit_field(self, limit: str) -> None:
        arguments = {'version': DOCS_VERSION, 'query': 'os.path', 'limit': limit}
        self.assert_field_error(invoke(SEARCH_TOOL, arguments), 'limit')

    @given(query=st.one_of(blank_text, overlong_queries))
    def test_an_empty_or_overlong_query_names_the_query_field(self, query: str) -> None:
        arguments = {'version': DOCS_VERSION, 'query': query}
        self.assert_field_error(invoke(SEARCH_TOOL, arguments), 'query')

    @given(version=malformed_versions)
    def test_a_malformed_version_names_the_version_field(self, version: str) -> None:
        arguments = {'version': version, 'query': 'os.path'}
        self.assert_field_error(invoke(SEARCH_TOOL, arguments), 'version')

    @given(offset=negative_offsets)
    def test_a_negative_offset_names_the_offset_field(self, offset: int) -> None:
        arguments = {'version': DOCS_VERSION, 'symbol': 'os.path', 'offset': offset}
        self.assert_field_error(invoke(READ_TOOL, arguments), 'offset')

    @given(max_chars=out_of_range_page_sizes)
    def test_an_out_of_range_page_size_names_the_max_chars_field(self, max_chars: int) -> None:
        arguments = {'version': DOCS_VERSION, 'symbol': 'os.path', 'max_chars': max_chars}
        self.assert_field_error(invoke(READ_TOOL, arguments), 'max_chars')

    @given(symbol=st.one_of(blank_text, overlong_symbols))
    def test_an_empty_or_overlong_symbol_names_the_symbol_field(self, symbol: str) -> None:
        arguments = {'version': DOCS_VERSION, 'symbol': symbol}
        self.assert_field_error(invoke(READ_TOOL, arguments), 'symbol')

    @given(limit=out_of_range_limits)
    def test_every_invalid_field_gets_its_own_entry(self, limit: int) -> None:
        arguments = {'version': DOCS_VERSION, 'query': '', 'limit': limit}
        text = first_text(invoke(SEARCH_TOOL, arguments))
        assert 'model_params.limit\n  limit ' in text
        assert 'model_params.query\n  query ' in text


class TestValidArguments:
    valid_limits = st.integers(min_value=1, max_value=30)
    valid_queries = st.text(alphabet='abcdefghij._', min_size=1, max_size=40)

    @given(limit=valid_limits, query=valid_queries)
    def test_valid_arguments_are_served_normally(self, limit: int, query: str) -> None:
        arguments = {'version': DOCS_VERSION, 'query': query, 'limit': limit}
        result = invoke(SEARCH_TOOL, arguments)
        structured = result.structured_content
        assert structured is not None
        assert (result.is_error, len(structured['matches']) <= limit) == (False, True)

    async def test_a_missing_required_argument_is_named(self, client: Client) -> None:
        result = await client.call_tool(SEARCH_TOOL, {'model_params': {'version': DOCS_VERSION}})
        text = first_text(result)
        assert result.is_error
        assert 'required fields missing: query' in text
        assert not any(marker in text for marker in PYDANTIC_MARKERS)


class TestAdvertisedSchema:
    @tool_name_cases()
    async def test_the_fields_are_nested_under_model_params(
        self, client: Client, tool_name: str
    ) -> None:
        listed = await client.list_tools()
        tool: Tool = next(tool for tool in listed.tools if tool.name == tool_name)
        assert (set(tool.input_schema['properties']), tool.input_schema['required']) == (
            {'model_params'},
            ['model_params'],
        )

    async def test_the_search_fields_state_their_bounds_and_descriptions(
        self, client: Client
    ) -> None:
        listed = await client.list_tools()
        tool = next(tool for tool in listed.tools if tool.name == SEARCH_TOOL)
        fields = argument_definition(tool)['properties']
        assert (
            fields['limit']['maximum'],
            fields['limit']['exclusiveMinimum'],
            fields['query']['minLength'],
            fields['query']['maxLength'],
            all('description' in fields[name] for name in ('limit', 'query')),
        ) == (30, 0, 1, 200, True)

    async def test_the_read_fields_state_their_bounds_and_description(self, client: Client) -> None:
        listed = await client.list_tools()
        tool = next(tool for tool in listed.tools if tool.name == READ_TOOL)
        fields = argument_definition(tool)['properties']
        assert (
            fields['max_chars']['minimum'],
            fields['max_chars']['maximum'],
            fields['symbol']['maxLength'],
            fields['offset']['minimum'],
        ) == (500, 12_000, 300, 0)

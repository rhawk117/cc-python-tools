from typing import TYPE_CHECKING, get_args

import anyio
import pytest
from hypothesis import given
from hypothesis import strategies as st
from mcp import Client
from mcp.types import TextContent
from python_docs_mcp.app import TOOL_ARGUMENT_MODELS, ToolName
from python_docs_mcp.lifespan import ServiceOptions, get_config_registry

from tests.docs.support.docs_site import DocsSite
from tests.docs.support.samples import DOCS_VERSION, standard_pages
from tests.docs.support.server import ServerHarness

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from _pytest.mark import ParameterSet
    from mcp.types import CallToolResult, Tool

SEARCH_TOOL = 'search_python_docs'
READ_TOOL = 'read_python_docs'
PYDANTIC_MARKERS = ('validation error for', 'errors.pydantic.dev')


def tool_name_cases() -> pytest.MarkDecorator:
    members: list[ParameterSet] = [pytest.param(name, id=name) for name in get_args(ToolName)]
    return pytest.mark.parametrize('tool_name', members)


def first_text(result: CallToolResult) -> str:
    block = result.content[0]
    assert isinstance(block, TextContent)
    return block.text


async def call_tool(tool: str, arguments: dict[str, object]) -> CallToolResult:
    harness = ServerHarness(registry=get_config_registry())
    options = ServiceOptions(transport=DocsSite(pages=standard_pages()).transport())
    async with harness.connect(options=options) as client:
        return await client.call_tool(tool, arguments)


def invoke(tool: str, arguments: dict[str, object]) -> CallToolResult:
    return anyio.run(call_tool, tool, arguments)


class TestArgumentErrors:
    out_of_range_limits = st.one_of(st.integers(max_value=0), st.integers(min_value=31))
    negative_offsets = st.integers(max_value=-1)
    out_of_range_page_sizes = st.one_of(st.integers(max_value=499), st.integers(min_value=12_001))
    valid_limits = st.integers(min_value=1, max_value=30)
    valid_queries = st.text(alphabet='abcdefghij._', min_size=1, max_size=40)

    @pytest.fixture
    async def client(self, harness: ServerHarness) -> AsyncGenerator[Client]:
        options = ServiceOptions(transport=DocsSite(pages=standard_pages()).transport())
        async with harness.connect(options=options) as client:
            assert isinstance(client, Client)
            yield client

    def assert_field_error(self, result: CallToolResult, field: str) -> None:
        text = first_text(result)
        assert result.is_error
        assert text.startswith(f'{field}: ')
        assert not any(marker in text for marker in PYDANTIC_MARKERS)

    @given(limit=out_of_range_limits)
    def test_an_out_of_range_limit_names_the_limit_field(self, limit: int) -> None:
        arguments = {'version': DOCS_VERSION, 'query': 'os.path', 'limit': limit}
        self.assert_field_error(invoke(SEARCH_TOOL, arguments), 'limit')

    @given(offset=negative_offsets)
    def test_a_negative_offset_names_the_offset_field(self, offset: int) -> None:
        arguments = {'version': DOCS_VERSION, 'symbol': 'os.path', 'offset': offset}
        self.assert_field_error(invoke(READ_TOOL, arguments), 'offset')

    @given(max_chars=out_of_range_page_sizes)
    def test_an_out_of_range_page_size_names_the_max_chars_field(self, max_chars: int) -> None:
        arguments = {'version': DOCS_VERSION, 'symbol': 'os.path', 'max_chars': max_chars}
        self.assert_field_error(invoke(READ_TOOL, arguments), 'max_chars')

    @given(limit=out_of_range_limits)
    def test_every_invalid_field_gets_its_own_line(self, limit: int) -> None:
        arguments = {'version': DOCS_VERSION, 'query': '', 'limit': limit}
        text = first_text(invoke(SEARCH_TOOL, arguments))
        assert sorted(line.split(':')[0] for line in text.splitlines()) == ['limit', 'query']

    @given(limit=valid_limits, query=valid_queries)
    def test_valid_arguments_are_served_normally(self, limit: int, query: str) -> None:
        arguments = {'version': DOCS_VERSION, 'query': query, 'limit': limit}
        result = invoke(SEARCH_TOOL, arguments)
        structured = result.structured_content
        assert structured is not None
        assert (result.is_error, len(structured['matches']) <= limit) == (False, True)

    async def test_a_missing_required_argument_is_named(self, client: Client) -> None:
        result = await client.call_tool(SEARCH_TOOL, {'version': DOCS_VERSION})
        self.assert_field_error(result, 'query')

    async def test_the_map_lists_exactly_the_served_tools(self, client: Client) -> None:
        listed = await client.list_tools()
        assert sorted(tool.name for tool in listed.tools) == sorted(TOOL_ARGUMENT_MODELS)

    @tool_name_cases()
    async def test_the_model_matches_the_advertised_schema(
        self, client: Client, tool_name: ToolName
    ) -> None:
        listed = await client.list_tools()
        tool: Tool = next(tool for tool in listed.tools if tool.name == tool_name)
        schema = TOOL_ARGUMENT_MODELS[tool_name].model_json_schema()
        advertised = (
            set(tool.input_schema['properties']),
            set(tool.input_schema.get('required', [])),
        )
        modeled = (set(schema['properties']), set(schema.get('required', [])))
        assert advertised == modeled

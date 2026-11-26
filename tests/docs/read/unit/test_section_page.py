from dataclasses import dataclass
from typing import TYPE_CHECKING

import pytest
from python_docs_mcp.read_python_docs import SectionPage
from python_docs_mcp.schemas.domain_types import DocumentationUrl, Symbol

if TYPE_CHECKING:
    from _pytest.mark import ParameterSet

SOURCE_URL = DocumentationUrl(text='https://docs.python.org/3.13/library/os.path.html#os.path.join')
JOIN = Symbol(name='os.path.join', kind='function', source_url=SOURCE_URL)
HEADER = f'os.path.join (function) | Python 3.13 documentation | {SOURCE_URL.text}'
SECTION_TEXT = 'abcdefghij'
PAGE_CHARACTERS = 4


@dataclass(slots=True, kw_only=True, frozen=True)
class PageBoundary:
    name: str
    offset: int
    body: str
    footer: str
    marks: tuple[pytest.MarkDecorator, ...] = ()

    @property
    def param(self) -> ParameterSet:
        return pytest.param(self, id=self.name, marks=self.marks)


def section_page_boundary_cases() -> pytest.MarkDecorator:
    first_page = PageBoundary(
        name='offset-zero',
        offset=0,
        body='abcd',
        footer='More: call read_python_docs again with offset=4 (4 of 10 characters shown).',
    )
    mid_section = PageBoundary(
        name='mid-section',
        offset=4,
        body='efgh',
        footer='More: call read_python_docs again with offset=8 (8 of 10 characters shown).',
    )
    ends_on_length = PageBoundary(
        name='offset-plus-page-equals-length',
        offset=6,
        body='ghij',
        footer='End of section (10 characters).',
    )
    at_length = PageBoundary(
        name='offset-equals-length',
        offset=10,
        body='',
        footer='End of section (10 characters).',
    )
    return pytest.mark.parametrize(
        'boundary',
        [first_page.param, mid_section.param, ends_on_length.param, at_length.param],
    )


class TestRender:
    @section_page_boundary_cases()
    def test_the_page_has_a_header_a_body_and_a_footer(self, boundary: PageBoundary) -> None:
        page = SectionPage(
            symbol=JOIN,
            documentation_version='3.13',
            text=SECTION_TEXT,
            offset=boundary.offset,
            max_chars=PAGE_CHARACTERS,
        )
        assert page.render() == f'{HEADER}\n\n{boundary.body}\n\n{boundary.footer}'

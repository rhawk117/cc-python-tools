import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

import pytest
from hypothesis import given
from hypothesis import strategies as st
from python_docs_mcp.schemas.domain_types import DocumentationUrl, Symbol
from python_docs_mcp.services.read_python_docs import SectionPage

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


BODY_FENCE_OPEN = re.compile(r' {0,3}(`{3,}|~{3,})(.*)')
BODY_FENCE_CLOSE = re.compile(r' {0,3}(`{3,}|~{3,})[ \t]*')
NEXT_OFFSET = re.compile(r'offset=(\d+)')


def is_balanced(body: str) -> bool:
    marker = ''
    for line in body.split('\n'):
        closing = BODY_FENCE_CLOSE.fullmatch(line)
        if marker and closing:
            marker = (
                ''
                if closing.group(1).startswith(marker[0]) and len(closing.group(1)) >= len(marker)
                else marker
            )
            continue

        opening = BODY_FENCE_OPEN.fullmatch(line)
        if not marker and opening and not (opening.group(1)[0] == '`' and '`' in opening.group(2)):
            marker = opening.group(1)
    return not marker


prose_lines = st.text(alphabet='ab xyz', max_size=8)
fence_lines = st.builds(
    '{}{}{}'.format,
    st.sampled_from(['', ' ', '   ']),
    st.sampled_from(['`', '~']).flatmap(lambda char: st.integers(3, 5).map(char.__mul__)),
    st.sampled_from(['', 'python', ' text']),
)
section_texts = st.builds(
    '\n'.join,
    st.lists(st.one_of(prose_lines, fence_lines), max_size=12),
)


class TestFencedPages:
    def read_pages(self, text: str, max_chars: int) -> list[SectionPage]:
        pages: list[SectionPage] = []
        offset: int | None = 0
        while offset is not None:
            page = SectionPage(
                symbol=JOIN,
                documentation_version='3.13',
                text=text,
                offset=offset,
                max_chars=max_chars,
            )
            pages.append(page)
            found = NEXT_OFFSET.search(page.footer)
            offset = int(found.group(1)) if found else None
        return pages

    def strip_added_lines(self, page: SectionPage) -> str:
        return page.body.removeprefix(page.opening).removesuffix(page.closing)

    @given(text=section_texts, max_chars=st.integers(1, 30))
    def test_every_page_has_balanced_fences(self, text: str, max_chars: int) -> None:
        pages = self.read_pages(text, max_chars)
        assert all(is_balanced(page.render()) for page in pages)

    @given(text=section_texts, max_chars=st.integers(1, 30))
    def test_pages_reproduce_the_section_once_fence_lines_are_removed(
        self, text: str, max_chars: int
    ) -> None:
        pages = self.read_pages(text, max_chars)
        assert ''.join(map(self.strip_added_lines, pages)) == text

    def test_a_page_ending_inside_a_fence_closes_it_and_the_next_reopens_it(self) -> None:
        first, second = self.read_pages('~~~~ sh\nls\npwd\n~~~~\nend', 10)[:2]
        assert first.closing == '\n~~~~'
        assert second.opening == '~~~~sh\n'

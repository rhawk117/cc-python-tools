import operator
import re
from dataclasses import dataclass
from itertools import accumulate
from typing import TYPE_CHECKING, Literal

import pytest
from hypothesis import assume, example, given
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

type LineStatus = Literal['fence', 'code', 'prose']


def classify_line(line: str, marker: str) -> tuple[LineStatus, str]:
    if marker:
        closing = BODY_FENCE_CLOSE.fullmatch(line)
        if closing and closing.group(1)[0] == marker[0] and len(closing.group(1)) >= len(marker):
            return 'fence', ''

        return 'code', marker

    opening = BODY_FENCE_OPEN.fullmatch(line)
    if opening and not (opening.group(1)[0] == '`' and '`' in opening.group(2)):
        return 'fence', opening.group(1)

    return 'prose', ''


def classify_lines(lines: list[str]) -> tuple[list[LineStatus], str]:
    marker = ''
    statuses: list[LineStatus] = []
    for line in lines:
        status, marker = classify_line(line, marker)
        statuses.append(status)
    return statuses, marker


def is_balanced(body: str) -> bool:
    return not classify_lines(body.split('\n'))[1]


@dataclass(slots=True, kw_only=True, frozen=True)
class SourceLine:
    text: str
    start: int
    status: LineStatus

    @property
    def end(self) -> int:
        return self.start + len(self.text)


def read_source_lines(text: str) -> list[SourceLine]:
    lines = text.split('\n')
    statuses, _ = classify_lines(lines)
    starts = accumulate((len(line) + 1 for line in lines), initial=0)
    return [
        SourceLine(text=line, start=start, status=status)
        for line, start, status in zip(lines, starts, statuses, strict=False)
    ]


class TestPageEnds:
    texts = st.text(alphabet='ab \n', max_size=40)

    @given(text=texts, max_chars=st.integers(1, 30))
    def test_a_page_ends_on_a_newline_unless_its_window_holds_none(
        self, text: str, max_chars: int
    ) -> None:
        pages = read_pages(text, max_chars)
        ends = [
            page.excerpt.endswith('\n')
            or ('\n' not in page.excerpt and len(page.excerpt) == max_chars)
            for page in pages[:-1]
        ]
        assert all(ends)

    @given(text=texts, max_chars=st.integers(1, 30))
    def test_every_page_stays_within_the_page_size(self, text: str, max_chars: int) -> None:
        pages = read_pages(text, max_chars)
        assert all(len(page.excerpt) <= max_chars for page in pages)


def read_pages(text: str, max_chars: int) -> list[SectionPage]:
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


def holding_pages(pages: list[SectionPage], line: SourceLine) -> list[SectionPage]:
    return [page for page in pages if page.offset <= line.start and line.end <= page.end]


def renders_as_in_source(pages: list[SectionPage], line: SourceLine, text: str) -> bool:
    holders = holding_pages(pages, line)
    if len(holders) != 1:
        return False

    page = holders[0]
    body_lines = page.body.split('\n')
    index = bool(page.opening) + text.count('\n', page.offset, line.start)
    statuses, _ = classify_lines(body_lines)
    return (body_lines[index], statuses[index]) == (line.text, line.status)


def find_misrendered_lines(text: str, max_chars: int) -> list[SourceLine]:
    pages = read_pages(text, max_chars)
    lines = [line for line in read_source_lines(text) if 0 < len(line.text) <= max_chars]
    return [line for line in lines if not renders_as_in_source(pages, line, text)]


class TestFencedPages:
    prose_lines = st.text(alphabet='ab xyz', max_size=8)
    fence_lines = st.builds(
        '{}{}{}'.format,
        st.sampled_from(['', ' ', '   ']),
        st.builds(operator.mul, st.sampled_from(['`', '~']), st.integers(3, 5)),
        st.sampled_from(['', 'python', ' text']),
    )
    section_texts = st.builds(
        '\n'.join,
        st.lists(st.one_of(prose_lines, fence_lines), max_size=12),
    )
    closing_fence_split = '```\ncode\n````\nx'
    opening_fence_split = 'abc\n```py\ncode\n```\nafter'

    def strip_added_lines(self, page: SectionPage) -> str:
        assert page.body.startswith(page.opening)
        assert page.body.endswith(page.closing)
        return page.body.removeprefix(page.opening).removesuffix(page.closing)

    def is_added_fence_line(self, page: SectionPage) -> bool:
        opening = page.opening.removesuffix('\n')
        closing = page.closing.removeprefix('\n')
        opening_ok = not opening or BODY_FENCE_OPEN.fullmatch(opening)
        closing_ok = not closing or BODY_FENCE_CLOSE.fullmatch(closing)
        return bool(opening_ok and closing_ok)

    @given(text=section_texts, max_chars=st.integers(1, 30))
    def test_every_page_has_balanced_fences(self, text: str, max_chars: int) -> None:
        pages = read_pages(text, max_chars)
        assert all(is_balanced(page.render()) for page in pages)

    @given(text=section_texts, max_chars=st.integers(1, 30))
    def test_pages_reproduce_the_section_once_fence_lines_are_removed(
        self, text: str, max_chars: int
    ) -> None:
        pages = read_pages(text, max_chars)
        assert all(map(self.is_added_fence_line, pages))
        assert ''.join(map(self.strip_added_lines, pages)) == text

    @pytest.mark.regression
    @given(text=section_texts, max_chars=st.integers(1, 30))
    @example(text='```\ncode', max_chars=3)
    def test_every_line_renders_with_the_status_it_has_in_the_source(
        self, text: str, max_chars: int
    ) -> None:
        fence_lengths = [
            len(line.text) for line in read_source_lines(text) if line.status == 'fence'
        ]
        assume(max(fence_lengths, default=0) <= max_chars)
        assert find_misrendered_lines(text, max_chars) == []

    @pytest.mark.regression
    def test_a_page_boundary_after_a_closing_fence_line_leaves_the_prose_unfenced(self) -> None:
        assert find_misrendered_lines(self.closing_fence_split, 12) == []

    @pytest.mark.regression
    def test_a_page_boundary_after_an_opening_fence_line_keeps_the_code_fenced(self) -> None:
        assert find_misrendered_lines(self.opening_fence_split, 14) == []

    def test_a_page_ending_inside_a_fence_closes_it_and_the_next_reopens_it(self) -> None:
        first, second = read_pages('~~~~ sh\nls\npwd\n~~~~\nend', 12)[:2]
        assert first.closing == '~~~~'
        assert second.opening == '~~~~sh\n'

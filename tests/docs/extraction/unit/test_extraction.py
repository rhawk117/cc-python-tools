"""One symbol's definition or section, cleaned and rendered as Markdown."""

import pytest
from python_agent_tools_docs.domain import DocumentationUrl
from python_agent_tools_docs.errors import MissingAnchorError
from python_agent_tools_docs.extraction import extract_markdown

from tests.docs.support.samples import FILLER_SENTENCE, OS_PATH_PAGE


def kept_text_cases() -> pytest.MarkDecorator:
    return pytest.mark.parametrize(
        'expected',
        [
            pytest.param('os.path.join(path, \\*paths)', id='signature'),
            pytest.param('Join one or more path segments', id='body'),
            pytest.param('(https://docs.python.org/3.13/library/os.html#os.sep)', id='link'),
        ],
    )


def dropped_text_cases() -> pytest.MarkDecorator:
    return pytest.mark.parametrize(
        'unexpected',
        [
            pytest.param('tracking()', id='script'),
            pytest.param('#os.path.join)', id='headerlink'),
            pytest.param('isfile', id='neighbor'),
        ],
    )


class TestExtractMarkdown:
    page_url = 'https://docs.python.org/3.13/library/os.path.html'

    @pytest.fixture
    def join_definition(self) -> str:
        url = DocumentationUrl(text=f'{self.page_url}#os.path.join')
        return extract_markdown(OS_PATH_PAGE.encode(), url)

    @kept_text_cases()
    def test_definition_keeps_signature_body_and_absolute_links(
        self, join_definition: str, expected: str
    ) -> None:
        assert expected in join_definition

    @dropped_text_cases()
    def test_definition_drops_chrome_and_neighbors(
        self, join_definition: str, unexpected: str
    ) -> None:
        assert unexpected not in join_definition

    def test_module_anchor_returns_the_enclosing_section(self) -> None:
        url = DocumentationUrl(text=f'{self.page_url}#module-os.path')
        section = extract_markdown(OS_PATH_PAGE.encode(), url)
        assert FILLER_SENTENCE.strip() in section
        assert 'os.path.isfile(path)' in section

    def test_missing_anchor_is_reported(self) -> None:
        url = DocumentationUrl(text=f'{self.page_url}#os.path.nothing')
        with pytest.raises(MissingAnchorError):
            extract_markdown(OS_PATH_PAGE.encode(), url)

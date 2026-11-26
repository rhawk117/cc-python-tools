import pytest
from python_agent_tools_docs.domain import (
    DocumentationUrl,
    PythonVersion,
    ambiguous_url_violation,
    create_documentation_url,
    create_python_version,
)
from python_agent_tools_docs.errors import (
    AmbiguousUrlError,
    ForeignUrlError,
    InvalidVersionError,
    UnversionedUrlError,
)


def valid_version_cases() -> pytest.MarkDecorator:
    return pytest.mark.parametrize(
        'text', [pytest.param(text, id=text) for text in ('3.0', '3.9', '3.13', '3.99')]
    )


def invalid_version_cases() -> pytest.MarkDecorator:
    texts = ('', '3', '3.', '3.00', '3.01', '3.100', '2.7', '4.1', '3.13.1', ' 3.13', '3.13\n', 'x')
    return pytest.mark.parametrize('text', [pytest.param(text, id=repr(text)) for text in texts])


def foreign_url_cases() -> pytest.MarkDecorator:
    urls = {
        'http': 'http://docs.python.org/3.13/library/os.html',
        'other-host': 'https://example.com/3.13/library/os.html',
        'subdomain': 'https://evil.docs.python.org/3.13/library/os.html',
        'query': 'https://docs.python.org/3.13/library/os.html?x=1',
        'query-before-fragment': 'https://docs.python.org/3.13/library/os.html?x=1#a',
    }
    return pytest.mark.parametrize(
        'url', [pytest.param(url, id=name) for name, url in urls.items()]
    )


def unversioned_url_cases() -> pytest.MarkDecorator:
    urls = {
        'no-path': 'https://docs.python.org',
        'version-only': 'https://docs.python.org/3.13/',
        'no-version': 'https://docs.python.org/library/os.html',
        'bad-version': 'https://docs.python.org/2.7/library/os.html',
        'leading-zero': 'https://docs.python.org/3.01/library/os.html',
    }
    return pytest.mark.parametrize(
        'url', [pytest.param(url, id=name) for name, url in urls.items()]
    )


def ambiguous_url_cases() -> pytest.MarkDecorator:
    urls = {
        'encoded': 'https://docs.python.org/3.13/library/%2e%2e/os.html',
        'dot-segment': 'https://docs.python.org/3.13/./library/os.html',
        'dotdot-segment': 'https://docs.python.org/3.13/library/../os.html',
        'whitespace': 'https://docs.python.org/3.13/library/o s.html',
        'newline': 'https://docs.python.org/3.13/library/os.html\n',
        'backslash': 'https://docs.python.org/3.13\\library/os.html',
        'control': 'https://docs.python.org/3.13/library/\x00os.html',
        'unbalanced-host-bracket': 'https://[',
        'bracket-after-host': 'https://docs.python.org[/3.13/',
    }
    return pytest.mark.parametrize(
        'url', [pytest.param(url, id=name) for name, url in urls.items()]
    )


class TestPythonVersion:
    @valid_version_cases()
    def test_valid_version_is_built(self, text: str) -> None:
        assert create_python_version(text) == PythonVersion(text=text)

    @invalid_version_cases()
    def test_invalid_version_is_returned_as_an_error(self, text: str) -> None:
        result = create_python_version(text)

        assert isinstance(result, InvalidVersionError)
        assert repr(text) in str(result)

    def test_base_url_is_the_versioned_root(self) -> None:
        assert PythonVersion(text='3.13').base_url == 'https://docs.python.org/3.13/'

    def test_minor_is_the_number_after_the_major(self) -> None:
        assert PythonVersion(text='3.13').minor == 13


class TestDocumentationUrl:
    page = 'https://docs.python.org/3.13/library/os.html#os.getcwd'

    @pytest.fixture
    def url(self) -> DocumentationUrl:
        built = create_documentation_url(self.page)
        assert isinstance(built, DocumentationUrl)
        return built

    def test_valid_url_is_built(self, url: DocumentationUrl) -> None:
        assert url == DocumentationUrl(text=self.page)

    def test_parts_are_derived_from_the_text(self, url: DocumentationUrl) -> None:
        assert url.path == '/3.13/library/os.html'
        assert url.version == PythonVersion(text='3.13')
        assert url.page_path == 'library/os.html'
        assert url.fragment == 'os.getcwd'

    def test_page_url_drops_the_fragment(self, url: DocumentationUrl) -> None:
        assert url.page_url == DocumentationUrl(text='https://docs.python.org/3.13/library/os.html')

    @foreign_url_cases()
    def test_foreign_url_is_returned_as_an_error(self, url: str) -> None:
        assert isinstance(create_documentation_url(url), ForeignUrlError)

    @unversioned_url_cases()
    def test_unversioned_url_is_returned_as_an_error(self, url: str) -> None:
        assert isinstance(create_documentation_url(url), UnversionedUrlError)

    @ambiguous_url_cases()
    def test_ambiguous_url_is_returned_as_an_error(self, url: str) -> None:
        assert isinstance(create_documentation_url(url), AmbiguousUrlError)

    @ambiguous_url_cases()
    def test_ambiguity_violation_names_the_url(self, url: str) -> None:
        assert isinstance(ambiguous_url_violation(url), AmbiguousUrlError)

    def test_clean_url_has_no_ambiguity(self) -> None:
        assert ambiguous_url_violation(self.page) is None

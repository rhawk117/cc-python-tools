from dataclasses import dataclass

import anyio
import httpx2
import pytest
from python_agent_tools_docs.domain import (
    DocumentationUrl,
    PythonVersion,
    create_documentation_url,
    create_python_version,
)
from python_agent_tools_docs.errors import (
    DownloadTooLargeError,
    PageNotFoundError,
    RetrievalFailedError,
    UpstreamStatusError,
    VersionNotPublishedError,
)
from python_agent_tools_docs.progress import ProgressBoard
from python_agent_tools_docs.repository import (
    DocumentationSource,
    documentation_http_client,
    inventory_url,
)
from python_agent_tools_docs.settings import Settings

from tests.docs.support.docs_site import DocsSite
from tests.docs.support.samples import DOCS_VERSION, standard_pages

PAGE_PATH = '/3.13/library/os.path.html'
REDIRECT_TARGET = 'https://example.com/elsewhere'


def make_url(text: str) -> DocumentationUrl:
    url = create_documentation_url(text)
    assert isinstance(url, DocumentationUrl)
    return url


def make_version(text: str) -> PythonVersion:
    version = create_python_version(text)
    assert isinstance(version, PythonVersion)
    return version


@dataclass(slots=True, kw_only=True, frozen=True)
class SourceHarness:
    site: DocsSite
    source: DocumentationSource


def create_source(client: httpx2.AsyncClient, settings: Settings) -> DocumentationSource:
    return DocumentationSource(
        client=client,
        downloads=anyio.CapacityLimiter(settings.download_concurrency),
        settings=settings,
        board=ProgressBoard(),
    )


def create_harness(site: DocsSite, settings: Settings) -> SourceHarness:
    client = documentation_http_client(settings, site.transport())
    return SourceHarness(site=site, source=create_source(client, settings))


class TestInventoryUrl:
    def test_url_points_at_the_version_inventory(self) -> None:
        assert (
            inventory_url(make_version('3.13')).text == 'https://docs.python.org/3.13/objects.inv'
        )


class TestFetch:
    page_url = make_url(f'https://docs.python.org{PAGE_PATH}')
    body = b'<html>os.path</html>'

    @pytest.fixture
    def settings(self) -> Settings:
        return Settings(download_max_bytes=64, download_chunk_bytes=16)

    @pytest.fixture
    def harness(self, settings: Settings) -> SourceHarness:
        site = DocsSite(
            pages={PAGE_PATH: self.body, '/3.13/big.html': b'x' * 65},
            redirects={'https://docs.python.org/3.13/moved.html': REDIRECT_TARGET},
        )
        return create_harness(site, settings)

    async def test_success_returns_the_body(self, harness: SourceHarness) -> None:
        assert await harness.source.fetch(self.page_url) == self.body

    async def test_not_found_is_page_not_found(self, harness: SourceHarness) -> None:
        with pytest.raises(PageNotFoundError):
            await harness.source.fetch(make_url('https://docs.python.org/3.13/missing.html'))

    async def test_redirect_is_an_upstream_status_and_not_followed(
        self, harness: SourceHarness
    ) -> None:
        with pytest.raises(UpstreamStatusError):
            await harness.source.fetch(make_url('https://docs.python.org/3.13/moved.html'))
        assert harness.site.requested_origins() == {('https', 'docs.python.org')}

    async def test_oversized_body_is_cut_off(self, harness: SourceHarness) -> None:
        with pytest.raises(DownloadTooLargeError):
            await harness.source.fetch(make_url('https://docs.python.org/3.13/big.html'))

    async def test_transport_failure_names_the_url(self, settings: Settings) -> None:
        def refuse(request: httpx2.Request) -> httpx2.Response:
            message = 'refused'
            raise httpx2.ConnectError(message, request=request)

        client = documentation_http_client(settings, httpx2.MockTransport(refuse))
        source = create_source(client, settings)
        with pytest.raises(RetrievalFailedError, match=self.page_url.text):
            await source.fetch(self.page_url)


class TestFetchInventory:
    version = make_version(DOCS_VERSION)

    async def test_the_inventory_bytes_are_fetched(self) -> None:
        harness = create_harness(DocsSite(pages=standard_pages()), Settings())
        content = await harness.source.fetch_inventory(self.version)
        assert content == standard_pages()[f'/{DOCS_VERSION}/objects.inv']
        assert harness.site.request_count(f'/{DOCS_VERSION}/objects.inv') == 1

    async def test_unpublished_version_is_named(self) -> None:
        harness = create_harness(DocsSite(pages={}), Settings())
        with pytest.raises(VersionNotPublishedError, match=DOCS_VERSION):
            await harness.source.fetch_inventory(self.version)


class TestLimiter:
    def test_the_download_limiter_is_sized_by_settings(self) -> None:
        settings = Settings(download_concurrency=2)
        source = create_source(documentation_http_client(settings), settings)
        assert source.downloads.total_tokens == 2

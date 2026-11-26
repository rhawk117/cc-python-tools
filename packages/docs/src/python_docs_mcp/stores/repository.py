"""Bounded HTTP retrieval of official pages and inventories, with failures translated."""

from dataclasses import dataclass
from typing import TYPE_CHECKING

import httpx2

from python_docs_mcp.adapters.progress import SilentReporter, VersionProgress
from python_docs_mcp.core.exception import (
    DownloadTooLargeError,
    PageNotFoundError,
    RetrievalFailedError,
    UpstreamStatusError,
    VersionNotPublishedError,
)
from python_docs_mcp.schemas.domain_types import DocumentationUrl, create_documentation_url

if TYPE_CHECKING:
    import anyio

    from python_docs_mcp.adapters.progress import ProgressBoard, ProgressReporter
    from python_docs_mcp.core.exception import DocumentationError
    from python_docs_mcp.schemas.domain_types import PythonVersion
    from python_docs_mcp.schemas.settings import Settings


def documentation_http_client(
    settings: Settings, transport: httpx2.AsyncBaseTransport | None = None
) -> httpx2.AsyncClient:
    return httpx2.AsyncClient(
        transport=transport,
        timeout=httpx2.Timeout(
            settings.request_timeout_seconds,
            connect=settings.connect_timeout_seconds,
            pool=settings.pool_timeout_seconds,
        ),
        limits=httpx2.Limits(
            max_connections=settings.http_max_connections,
            max_keepalive_connections=settings.http_max_keepalive_connections,
            keepalive_expiry=settings.http_keepalive_expiry_seconds,
        ),
    )


def inventory_url(version: PythonVersion) -> DocumentationUrl:
    url = create_documentation_url(f'{version.base_url}objects.inv')
    if isinstance(url, DocumentationUrl):
        return url
    raise url


def response_failure(response: httpx2.Response) -> DocumentationError | None:
    if response.status_code == httpx2.codes.NOT_FOUND:
        return PageNotFoundError(str(response.url))
    if not response.is_success:
        return UpstreamStatusError(response.status_code)
    return None


def declared_length(response: httpx2.Response) -> int | None:
    declared = response.headers.get('content-length', '')
    if not declared.isdecimal():
        return None
    return int(declared)


async def bounded_body(
    response: httpx2.Response, settings: Settings, progress: ProgressReporter
) -> bytes:
    total = declared_length(response)
    content = bytearray()
    async for chunk in response.aiter_bytes(chunk_size=settings.download_chunk_bytes):
        if len(content) + len(chunk) > settings.download_max_bytes:
            raise DownloadTooLargeError(settings.download_max_bytes)
        content.extend(chunk)
        await progress.report(len(content), total)
    return bytes(content)


@dataclass(frozen=True, slots=True, kw_only=True, eq=False)
class DocumentationSource:
    client: httpx2.AsyncClient
    downloads: anyio.CapacityLimiter
    settings: Settings
    board: ProgressBoard

    async def fetch(self, url: DocumentationUrl) -> bytes:
        return await self.fetch_reporting(url, SilentReporter())

    async def fetch_reporting(self, url: DocumentationUrl, progress: ProgressReporter) -> bytes:
        try:
            return await self.download(url, progress)
        except httpx2.RequestError as error:
            raise RetrievalFailedError(url.text) from error

    async def download(self, url: DocumentationUrl, progress: ProgressReporter) -> bytes:
        async with (
            self.downloads,
            self.client.stream('GET', url.text, follow_redirects=False) as response,
        ):
            if (failure := response_failure(response)) is not None:
                raise failure
            return await bounded_body(response, self.settings, progress)

    async def fetch_inventory(self, version: PythonVersion) -> bytes:
        try:
            progress = VersionProgress(board=self.board, version=version)
            return await self.fetch_reporting(inventory_url(version), progress)
        except PageNotFoundError as error:
            raise VersionNotPublishedError(version.text) from error

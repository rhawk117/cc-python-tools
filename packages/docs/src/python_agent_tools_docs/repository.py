"""Bounded HTTP retrieval of official pages and inventories, with failures translated."""

from dataclasses import dataclass
from typing import TYPE_CHECKING

import httpx2

from python_agent_tools_docs.domain import DocumentationUrl, create_documentation_url
from python_agent_tools_docs.errors import (
    DownloadTooLargeError,
    PageNotFoundError,
    RetrievalFailedError,
    UpstreamStatusError,
)

if TYPE_CHECKING:
    from python_agent_tools_docs.domain import PythonVersion
    from python_agent_tools_docs.errors import DocumentationError
    from python_agent_tools_docs.settings import Settings


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


async def bounded_body(response: httpx2.Response, settings: Settings) -> bytes:
    content = bytearray()
    async for chunk in response.aiter_bytes(chunk_size=settings.download_chunk_bytes):
        if len(content) + len(chunk) > settings.download_max_bytes:
            raise DownloadTooLargeError(settings.download_max_bytes)
        content.extend(chunk)
    return bytes(content)


@dataclass(frozen=True, slots=True, kw_only=True, eq=False)
class DocumentationSource:
    client: httpx2.AsyncClient
    settings: Settings

    async def fetch(self, url: DocumentationUrl) -> bytes:
        try:
            return await self.download(url)
        except httpx2.RequestError as error:
            raise RetrievalFailedError(url.text) from error

    async def download(self, url: DocumentationUrl) -> bytes:
        async with self.client.stream('GET', url.text, follow_redirects=False) as response:
            if (failure := response_failure(response)) is not None:
                raise failure
            return await bounded_body(response, self.settings)

"""Synthetic docs.python.org site: a transport that serves canned pages and records requests."""

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import httpx2

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Mapping
    from collections.abc import Set as AbstractSet


async def streamed(body: bytes) -> AsyncIterator[bytes]:
    yield body


@dataclass(slots=True, kw_only=True, eq=False)
class DocsSite:
    pages: Mapping[str, bytes]
    unsized: AbstractSet[str] = frozenset()
    redirects: Mapping[str, str] = field(default_factory=dict)
    requested_urls: list[httpx2.URL] = field(default_factory=list)

    def respond(self, request: httpx2.Request) -> httpx2.Response:
        self.requested_urls.append(request.url)
        location = self.redirects.get(str(request.url))
        if location is not None:
            return httpx2.Response(httpx2.codes.FOUND, headers={'Location': location})
        body = self.pages.get(request.url.path)
        if body is None:
            return httpx2.Response(httpx2.codes.NOT_FOUND)
        if request.url.path in self.unsized:
            return httpx2.Response(httpx2.codes.OK, content=streamed(body))
        return httpx2.Response(httpx2.codes.OK, content=body)

    def transport(self) -> httpx2.MockTransport:
        return httpx2.MockTransport(self.respond)

    def request_count(self, path: str) -> int:
        return sum(url.path == path for url in self.requested_urls)

    def requested_origins(self) -> set[tuple[str, str]]:
        return {(url.scheme, url.host) for url in self.requested_urls}

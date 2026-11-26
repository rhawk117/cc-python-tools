"""Synthetic docs.python.org site: a transport that serves canned pages and records requests."""

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import anyio
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
    held: AbstractSet[str] = frozenset()
    first_part_sent: anyio.Event = field(default_factory=anyio.Event)
    released: anyio.Event = field(default_factory=anyio.Event)

    async def held_body(self, body: bytes) -> AsyncIterator[bytes]:
        middle = len(body) // 2
        yield body[:middle]
        self.first_part_sent.set()
        await self.released.wait()
        yield body[middle:]

    async def wait_until_held(self) -> None:
        await self.first_part_sent.wait()

    def release(self) -> None:
        self.released.set()

    def respond(self, request: httpx2.Request) -> httpx2.Response:
        self.requested_urls.append(request.url)
        location = self.redirects.get(str(request.url))
        if location is not None:
            return httpx2.Response(httpx2.codes.FOUND, headers={'Location': location})
        body = self.pages.get(request.url.path)
        if body is None:
            return httpx2.Response(httpx2.codes.NOT_FOUND)
        if request.url.path in self.held:
            return httpx2.Response(httpx2.codes.OK, content=self.held_body(body))
        if request.url.path in self.unsized:
            return httpx2.Response(httpx2.codes.OK, content=streamed(body))
        return httpx2.Response(httpx2.codes.OK, content=body)

    def transport(self) -> httpx2.MockTransport:
        return httpx2.MockTransport(self.respond)

    def request_count(self, path: str) -> int:
        return sum(url.path == path for url in self.requested_urls)

    def requested_origins(self) -> set[tuple[str, str]]:
        return {(url.scheme, url.host) for url in self.requested_urls}

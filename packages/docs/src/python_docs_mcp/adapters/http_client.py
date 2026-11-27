"""Lifecycle-managed HTTP client for official documentation retrieval."""

from typing import TYPE_CHECKING

import httpx2

if TYPE_CHECKING:
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

"""The edge that owns the HTTP client and fill task group whose lifetime is the server's."""

from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from time import monotonic
from typing import TYPE_CHECKING

import anyio

from python_docs_mcp.resolve import LoaderEnvironment, compose_service
from python_docs_mcp.stores.disk_cache import NullInventoryStore
from python_docs_mcp.stores.repository import documentation_http_client

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Callable

    import httpx2

    from python_docs_mcp.schemas.settings import Settings
    from python_docs_mcp.services.documentation_service import DocumentationService
    from python_docs_mcp.stores.disk_cache import InventoryStore


@dataclass(frozen=True, slots=True, kw_only=True, eq=False)
class ServiceOptions:
    transport: httpx2.AsyncBaseTransport | None = None
    timer: Callable[[], float] = monotonic
    store: InventoryStore = field(default_factory=NullInventoryStore)


@asynccontextmanager
async def open_documentation_service(
    settings: Settings, options: ServiceOptions
) -> AsyncGenerator[DocumentationService]:
    client = documentation_http_client(settings, options.transport)
    try:
        async with anyio.create_task_group() as fills:
            environment = LoaderEnvironment(
                fills=fills, settings=settings, store=options.store, timer=options.timer
            )
            yield compose_service(client, environment)
            fills.cancel_scope.cancel()
    finally:
        with anyio.move_on_after(settings.shutdown_timeout_seconds, shield=True):
            await client.aclose()

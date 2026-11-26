"""The edge that owns the HTTP client and fill task group whose lifetime is the server's."""

import os
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import anyio

from python_docs_mcp.core.clock import get_server_clock
from python_docs_mcp.resolve import LoaderEnvironment, compose_service
from python_docs_mcp.schemas.settings import Settings
from python_docs_mcp.stores.disk_cache import NullInventoryStore, create_inventory_store
from python_docs_mcp.stores.repository import documentation_http_client

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Generator, Mapping

    import httpx2
    from mcp.server.mcpserver import MCPServer

    from python_docs_mcp.core.interfaces import (
        ClockInterface,
        ConfigProvider,
        ConfigRegistry,
        ServiceRegistry,
    )
    from python_docs_mcp.services.documentation_service import DocumentationService
    from python_docs_mcp.stores.disk_cache import InventoryStore


@dataclass(frozen=True, slots=True, kw_only=True, eq=False)
class ServiceOptions:
    transport: httpx2.AsyncBaseTransport | None = None
    clock: ClockInterface = field(default_factory=get_server_clock)
    store: InventoryStore = field(default_factory=NullInventoryStore)


@dataclass(frozen=True, slots=True, kw_only=True, eq=False)
class ServerConfig:
    settings: Settings
    options: ServiceOptions
    environment: Mapping[str, str]


@dataclass(frozen=True, slots=True, kw_only=True, eq=False)
class ServerState:
    service: DocumentationService
    environment: Mapping[str, str]


@dataclass(frozen=True, slots=True, kw_only=True, eq=False)
class EnvironmentConfigProvider:
    def provide_config(self) -> ServerConfig:
        settings = Settings()
        store = create_inventory_store(os.environ, settings.cache_ttl_seconds)
        return ServerConfig(
            settings=settings, options=ServiceOptions(store=store), environment=os.environ
        )


def create_default_providers() -> list[ConfigProvider]:
    return [EnvironmentConfigProvider()]


@dataclass(frozen=True, slots=True, kw_only=True, eq=False)
class ConfigHolder:
    providers: list[ConfigProvider] = field(default_factory=create_default_providers)

    def provide_config(self) -> ServerConfig:
        return self.providers[-1].provide_config()

    @contextmanager
    def override(self, provider: ConfigProvider) -> Generator[None]:
        self.providers.append(provider)
        try:
            yield
        finally:
            self.providers.remove(provider)


@dataclass(frozen=True, slots=True, kw_only=True, eq=False)
class ServiceHolder:
    services: list[DocumentationService] = field(default_factory=list)

    def get_service(self) -> DocumentationService | None:
        return next(reversed(self.services), None)

    @contextmanager
    def attach(self, service: DocumentationService) -> Generator[None]:
        self.services.append(service)
        try:
            yield
        finally:
            self.services.remove(service)


_config_holder = ConfigHolder()
_service_holder = ServiceHolder()


def get_config_registry() -> ConfigRegistry:
    return _config_holder


def get_service_registry() -> ServiceRegistry:
    return _service_holder


@dataclass(frozen=True, slots=True, kw_only=True, eq=False)
class ServerLifespan:
    settings: Settings | None = None
    config: ConfigProvider = field(default_factory=get_config_registry)
    services: ServiceRegistry = field(default_factory=get_service_registry)

    @asynccontextmanager
    async def open(self, _server: MCPServer[ServerState]) -> AsyncGenerator[ServerState]:
        config = self.config.provide_config()
        settings = self.settings or config.settings
        async with open_documentation_service(settings, config.options) as service:
            with self.services.attach(service):
                yield ServerState(service=service, environment=config.environment)


@asynccontextmanager
async def open_documentation_service(
    settings: Settings, options: ServiceOptions
) -> AsyncGenerator[DocumentationService]:
    client = documentation_http_client(settings, options.transport)
    try:
        async with anyio.create_task_group() as fills:
            environment = LoaderEnvironment(
                fills=fills, settings=settings, store=options.store, clock=options.clock
            )
            yield compose_service(client, environment)
            fills.cancel_scope.cancel()
    finally:
        with anyio.move_on_after(settings.shutdown_timeout_seconds, shield=True):
            await client.aclose()

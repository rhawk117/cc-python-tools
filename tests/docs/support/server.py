from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING

from mcp import Client
from python_docs_mcp.app import server
from python_docs_mcp.lifespan import ServerConfig, ServiceOptions
from python_docs_mcp.schemas.settings import Settings

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Mapping

    from python_docs_mcp.lifespan import ConfigRegistry


@dataclass(frozen=True, slots=True, kw_only=True, eq=False)
class FixedConfigProvider:
    config: ServerConfig

    def provide_config(self) -> ServerConfig:
        return self.config


@dataclass(frozen=True, slots=True, kw_only=True, eq=False)
class ServerHarness:
    registry: ConfigRegistry

    @asynccontextmanager
    async def connect(
        self,
        *,
        settings: Settings | None = None,
        options: ServiceOptions | None = None,
        environment: Mapping[str, str] | None = None,
    ) -> AsyncGenerator[Client]:
        config = ServerConfig(
            settings=settings or Settings(),
            options=options or ServiceOptions(),
            environment=environment or {},
        )
        with self.registry.override(FixedConfigProvider(config=config)):
            async with Client(server) as client:
                yield client

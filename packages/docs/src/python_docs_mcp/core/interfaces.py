"""Protocols shared by every layer."""

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from contextlib import AbstractContextManager
    from datetime import datetime

    from python_docs_mcp.lifespan import ServerConfig
    from python_docs_mcp.services.documentation_service import DocumentationService


@runtime_checkable
class ClockInterface(Protocol):
    def now(self) -> datetime: ...

    def epoch_now(self) -> float: ...

    def timestamp(self) -> int: ...

    def monotonic(self) -> float: ...


@runtime_checkable
class ConfigProvider(Protocol):
    def provide_config(self) -> ServerConfig: ...


@runtime_checkable
class ConfigRegistry(ConfigProvider, Protocol):
    def override(self, provider: ConfigProvider) -> AbstractContextManager[None]: ...


@runtime_checkable
class ServiceRegistry(Protocol):
    def attach(self, service: DocumentationService) -> AbstractContextManager[None]: ...

    def get_service(self) -> DocumentationService | None: ...

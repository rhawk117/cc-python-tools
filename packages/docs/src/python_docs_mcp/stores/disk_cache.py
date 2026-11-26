"""On-disk cache of fetched inventory bytes under the plugin data directory."""

import hashlib
import os
import tempfile
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, BinaryIO, Protocol, runtime_checkable

from python_docs_mcp.core.clock import get_server_clock

if TYPE_CHECKING:
    from collections.abc import Generator, Mapping

    from python_agent_tools_core.version import PythonVersion

    from python_docs_mcp.core.interfaces import ClockInterface

DATA_DIRECTORY_VARIABLE = 'CLAUDE_PLUGIN_DATA'
CACHE_DIRECTORY = 'python-docs-inventories'


@runtime_checkable
class InventoryStore(Protocol):
    def read(self, version: PythonVersion) -> bytes | None: ...

    def write(self, version: PythonVersion, content: bytes) -> None: ...


@dataclass(frozen=True, slots=True, kw_only=True)
class NullInventoryStore:
    def read(self, version: PythonVersion) -> bytes | None: ...

    def write(self, version: PythonVersion, content: bytes) -> None: ...


@dataclass(frozen=True, slots=True, kw_only=True)
class EntryPaths:
    data: Path
    digest: Path

    def remove(self) -> None:
        self.data.unlink(missing_ok=True)
        self.digest.unlink(missing_ok=True)


@dataclass(frozen=True, slots=True, kw_only=True)
class StoredEntry:
    content: bytes
    digest: bytes
    modified: float


def entry_paths(root: Path, version: PythonVersion) -> EntryPaths | None:
    data = root.joinpath(f'{version.text}.inv').resolve()
    if not data.is_relative_to(root):
        return None

    return EntryPaths(data=data, digest=data.with_suffix('.sha256'))


def digest_of(content: bytes) -> bytes:
    return hashlib.sha256(content).hexdigest().encode('ascii')


def read_entry(paths: EntryPaths) -> StoredEntry | None:
    try:
        return StoredEntry(
            content=paths.data.read_bytes(),
            digest=paths.digest.read_bytes(),
            modified=paths.data.stat().st_mtime,
        )
    except OSError:
        return None


@contextmanager
def removed_on_error(path: Path) -> Generator[None]:
    try:
        yield
    except OSError:
        path.unlink(missing_ok=True)
        raise


def open_descriptor(descriptor: int) -> BinaryIO:
    try:
        return os.fdopen(descriptor, 'wb')
    except OSError:
        os.close(descriptor)
        raise


def replace_atomically(target: Path, content: bytes) -> None:
    descriptor, name = tempfile.mkstemp(dir=target.parent)
    temporary = Path(name)
    with removed_on_error(temporary):
        handle = open_descriptor(descriptor)
        with handle:
            handle.write(content)
    with removed_on_error(temporary):
        temporary.replace(target)


@dataclass(frozen=True, slots=True, kw_only=True)
class DiskInventoryStore:
    root: Path
    ttl_seconds: float
    clock: ClockInterface

    def is_fresh(self, entry: StoredEntry) -> bool:
        age_seconds = self.clock.epoch_now() - entry.modified
        return 0 <= age_seconds <= self.ttl_seconds

    def read(self, version: PythonVersion) -> bytes | None:
        paths = entry_paths(self.root, version)
        if paths is None:
            return None

        entry = read_entry(paths)
        if entry is None:
            return None

        if self.is_fresh(entry) and digest_of(entry.content) == entry.digest:
            return entry.content

        with suppress(OSError):
            paths.remove()
        return None

    def write(self, version: PythonVersion, content: bytes) -> None:
        paths = entry_paths(self.root, version)
        if paths is None:
            return

        with suppress(OSError):
            self.root.mkdir(parents=True, exist_ok=True)
            replace_atomically(paths.digest, digest_of(content))
            replace_atomically(paths.data, content)


def create_inventory_store(
    environment: Mapping[str, str],
    ttl_seconds: float,
    clock: ClockInterface | None = None,
) -> InventoryStore:
    data_directory = environment.get(DATA_DIRECTORY_VARIABLE, '')
    if not data_directory:
        return NullInventoryStore()

    root = Path(data_directory).joinpath(CACHE_DIRECTORY).resolve()
    return DiskInventoryStore(root=root, ttl_seconds=ttl_seconds, clock=clock or get_server_clock())

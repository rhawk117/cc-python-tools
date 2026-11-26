import stat
from dataclasses import dataclass
from typing import TYPE_CHECKING

import pytest
from mcp import Client
from python_agent_tools_docs.composition import ServiceOptions, open_documentation_service
from python_agent_tools_docs.disk_cache import (
    CACHE_DIRECTORY,
    DATA_DIRECTORY_VARIABLE,
    create_inventory_store,
)
from python_agent_tools_docs.domain import PythonVersion, create_python_version
from python_agent_tools_docs.server import build_server
from python_agent_tools_docs.settings import Settings

from tests.docs.support.docs_site import DocsSite
from tests.docs.support.samples import DOCS_VERSION, standard_pages

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from python_agent_tools_docs.disk_cache import InventoryStore

SUFFIXES = {'.inv', '.sha256'}
INVENTORY_PATH = f'/{DOCS_VERSION}/objects.inv'


@dataclass(slots=True)
class Clock:
    now: float = 0

    def read(self) -> float:
        return self.now


def make_version(text: str) -> PythonVersion:
    version = create_python_version(text)
    assert isinstance(version, PythonVersion)
    return version


class TestInventoryStore:
    version = make_version(DOCS_VERSION)
    content = b'inventory bytes'
    ttl_seconds = 60.0

    @pytest.fixture
    def data_directory(self, tmp_path: Path) -> Path:
        return tmp_path.joinpath('plugin-data')

    @pytest.fixture
    def clock(self) -> Clock:
        return Clock()

    @pytest.fixture
    def store(self, data_directory: Path, clock: Clock) -> InventoryStore:
        environment = {DATA_DIRECTORY_VARIABLE: str(data_directory)}
        return create_inventory_store(environment, self.ttl_seconds, clock.read)

    def cached_files(self, data_directory: Path) -> list[Path]:
        return sorted(path for path in data_directory.rglob('*') if path.is_file())

    def test_written_bytes_are_read_back(self, store: InventoryStore) -> None:
        store.write(self.version, self.content)
        assert store.read(self.version) == self.content
        assert store.contains(self.version)

    def test_an_unknown_version_is_absent(self, store: InventoryStore) -> None:
        assert store.read(self.version) is None
        assert not store.contains(self.version)

    def test_a_truncated_copy_is_deleted(self, store: InventoryStore, data_directory: Path) -> None:
        store.write(self.version, self.content)
        data_file = next(
            path for path in self.cached_files(data_directory) if path.suffix == '.inv'
        )
        data_file.write_bytes(self.content[:4])
        assert store.read(self.version) is None
        assert self.cached_files(data_directory) == []

    def test_a_copy_older_than_the_ttl_is_deleted(
        self, store: InventoryStore, data_directory: Path, clock: Clock
    ) -> None:
        store.write(self.version, self.content)
        file_age_seconds = self.ttl_seconds + 1
        data_file = next(
            path for path in self.cached_files(data_directory) if path.suffix == '.inv'
        )
        clock.now = data_file.stat().st_mtime + file_age_seconds
        assert store.read(self.version) is None
        assert self.cached_files(data_directory) == []

    def test_every_cache_path_stays_inside_the_data_directory(
        self, store: InventoryStore, data_directory: Path
    ) -> None:
        store.write(self.version, self.content)
        written = self.cached_files(data_directory)
        assert written
        assert all(path.resolve().is_relative_to(data_directory.resolve()) for path in written)

    def test_an_unset_data_directory_writes_nothing(self, tmp_path: Path, clock: Clock) -> None:
        store = create_inventory_store({}, self.ttl_seconds, clock.read)
        store.write(self.version, self.content)
        assert store.read(self.version) is None
        assert not store.contains(self.version)
        assert list(tmp_path.iterdir()) == []


class TestUnusableDataDirectory:
    version = make_version(DOCS_VERSION)
    content = b'inventory bytes'

    @pytest.fixture
    def read_only_root(self, tmp_path: Path) -> Iterator[Path]:
        root = tmp_path.joinpath('plugin-data')
        root.mkdir()
        root.chmod(stat.S_IRUSR | stat.S_IXUSR)
        yield root
        root.chmod(stat.S_IRWXU)

    def store_for(self, root: Path) -> InventoryStore:
        return create_inventory_store({DATA_DIRECTORY_VARIABLE: str(root)}, 60.0)

    def test_a_read_only_directory_swallows_the_write_and_reads_a_miss(
        self, read_only_root: Path
    ) -> None:
        store = self.store_for(read_only_root)
        store.write(self.version, self.content)
        assert store.read(self.version) is None
        assert list(read_only_root.rglob('*')) == []

    def test_a_failed_replace_leaves_no_temporary_file(self, tmp_path: Path) -> None:
        store = self.store_for(tmp_path)
        cache_directory = tmp_path.joinpath(CACHE_DIRECTORY)
        cache_directory.joinpath(f'{DOCS_VERSION}.inv').mkdir(parents=True)
        store.write(self.version, self.content)
        leftovers = [path for path in cache_directory.iterdir() if path.suffix not in SUFFIXES]
        assert leftovers == []

    def test_an_unreadable_entry_is_a_miss(self, tmp_path: Path) -> None:
        store = self.store_for(tmp_path)
        cache_directory = tmp_path.joinpath(CACHE_DIRECTORY)
        cache_directory.joinpath(f'{DOCS_VERSION}.inv').mkdir(parents=True)
        assert store.read(self.version) is None

    async def test_a_search_still_returns_matches_from_the_network(
        self, read_only_root: Path
    ) -> None:
        site = DocsSite(pages=standard_pages())
        store = self.store_for(read_only_root)
        options = ServiceOptions(transport=site.transport(), store=store)
        async with (
            open_documentation_service(Settings(), options) as service,
            Client(build_server(service, {})) as client,
        ):
            result = await client.call_tool(
                'search_python_docs', {'version': DOCS_VERSION, 'query': 'os.path.join'}
            )
        assert not result.is_error
        assert site.request_count(INVENTORY_PATH) == 1


class TestRestartedServer:
    version = make_version(DOCS_VERSION)

    @pytest.fixture
    def environment(self, tmp_path: Path) -> dict[str, str]:
        return {DATA_DIRECTORY_VARIABLE: str(tmp_path)}

    async def search_after_restart(self, environment: dict[str, str]) -> DocsSite:
        site = DocsSite(pages=standard_pages())
        settings = Settings()
        store = create_inventory_store(environment, settings.cache_ttl_seconds)
        options = ServiceOptions(transport=site.transport(), store=store)
        async with open_documentation_service(settings, options) as service:
            catalog = await service.catalog(self.version)
            assert catalog
        return site

    async def test_a_second_run_serves_the_inventory_from_disk(
        self, environment: dict[str, str]
    ) -> None:
        first = await self.search_after_restart(environment)
        second = await self.search_after_restart(environment)
        assert first.request_count(INVENTORY_PATH) == 1
        assert second.request_count(INVENTORY_PATH) == 0

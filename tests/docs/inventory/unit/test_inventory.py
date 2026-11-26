"""Bounded inventory expansion and symbol indexing."""

import zlib
from dataclasses import dataclass
from typing import TYPE_CHECKING

import pytest
from python_agent_tools_core.version import PythonVersion
from python_docs_mcp.adapters.inventory import parse_inventory
from python_docs_mcp.core.exception import (
    CorruptInventoryError,
    EmptyInventoryError,
    InventoryEntryLimitError,
    InventoryTooLargeError,
    MalformedInventoryError,
    UnsupportedInventoryError,
)
from python_docs_mcp.schemas.settings import Settings

from tests.docs.support.samples import (
    DOCS_VERSION,
    INDEXED_NAMES,
    STANDARD_ENTRIES,
    InventoryEntry,
    inventory_bytes,
    inventory_plaintext,
)

if TYPE_CHECKING:
    from _pytest.mark import ParameterSet
    from python_docs_mcp.core.exception import DocumentationError

ESCAPING_ENTRY = InventoryEntry(name='escape', uri='../2.7/library/os.html#$')
FOREIGN_SCOPE_ENTRY = InventoryEntry(name='guide', uri='howto/logging.html#$', indexed=False)
HEADER = inventory_plaintext(()).removesuffix(b'\n')


@dataclass(slots=True, kw_only=True, frozen=True)
class RejectedInventory:
    name: str
    content: bytes
    error: type[DocumentationError]
    limits: dict[str, int]

    @property
    def param(self) -> ParameterSet:
        return pytest.param(self, id=self.name)


def rejected_inventory_cases() -> pytest.MarkDecorator:
    scenarios = (
        RejectedInventory(
            name='too-many-unusable',
            content=inventory_bytes((*STANDARD_ENTRIES, ESCAPING_ENTRY)),
            error=MalformedInventoryError,
            limits={},
        ),
        RejectedInventory(
            name='empty',
            content=inventory_bytes((FOREIGN_SCOPE_ENTRY,)),
            error=EmptyInventoryError,
            limits={},
        ),
        RejectedInventory(
            name='header',
            content=b'# Sphinx inventory version 1\n',
            error=UnsupportedInventoryError,
            limits={},
        ),
        RejectedInventory(
            name='corrupt',
            content=HEADER + b'\nnot zlib',
            error=CorruptInventoryError,
            limits={},
        ),
        RejectedInventory(
            name='truncated',
            content=HEADER + b'\n' + zlib.compress(b'x' * 4096)[:-4],
            error=CorruptInventoryError,
            limits={},
        ),
        RejectedInventory(
            name='bytes',
            content=inventory_bytes(),
            error=InventoryTooLargeError,
            limits={'inventory_max_bytes': 64},
        ),
        RejectedInventory(
            name='entries',
            content=inventory_bytes(),
            error=InventoryEntryLimitError,
            limits={'inventory_max_entries': 2},
        ),
    )
    return pytest.mark.parametrize('scenario', [scenario.param for scenario in scenarios])


class TestParseInventory:
    version = PythonVersion(text=DOCS_VERSION)

    @pytest.fixture
    def settings(self) -> Settings:
        return Settings()

    def test_indexes_python_symbols_in_indexed_sections(self, settings: Settings) -> None:
        index = parse_inventory(inventory_bytes(), self.version, settings)
        assert set(index.symbols) == INDEXED_NAMES

    def test_expands_dollar_uris_to_the_symbol_anchor(self, settings: Settings) -> None:
        index = parse_inventory(inventory_bytes(), self.version, settings)
        url = index.symbols['object.__getattr__'].source_url
        assert (
            url.text == 'https://docs.python.org/3.13/reference/datamodel.html#object.__getattr__'
        )

    def test_skips_a_tolerable_share_of_unusable_entries(self) -> None:
        tolerant = Settings(max_malformed_entry_ratio=0.5)
        content = inventory_bytes((*STANDARD_ENTRIES, ESCAPING_ENTRY))
        index = parse_inventory(content, self.version, tolerant)
        assert 'escape' not in index.symbols

    @rejected_inventory_cases()
    def test_rejects_unusable_inventories(self, scenario: RejectedInventory) -> None:
        settings = Settings.model_validate(scenario.limits)
        with pytest.raises(scenario.error):
            parse_inventory(scenario.content, self.version, settings)

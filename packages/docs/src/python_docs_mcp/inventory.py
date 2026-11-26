"""Bounded expansion and parsing of Sphinx objects.inv into a version's symbol index."""

import zlib
from typing import TYPE_CHECKING, cast
from urllib.parse import urljoin

from sphobjinv import Inventory

from python_docs_mcp.domain import (
    DocumentationUrl,
    Symbol,
    SymbolIndex,
    ambiguous_url_violation,
    create_documentation_url,
)
from python_docs_mcp.errors import (
    CorruptInventoryError,
    EmptyInventoryError,
    InventoryEntryLimitError,
    InventoryTooLargeError,
    MalformedInventoryError,
    UnparseableInventoryError,
    UnsupportedInventoryError,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

    from sphobjinv import DataObjStr

    from python_docs_mcp.domain import PythonVersion
    from python_docs_mcp.settings import Settings


SPHINX_HEADER_LINES = 4
SPHINX_INVENTORY_MAGIC = b'# Sphinx inventory version 2'


def inflate_inventory_body(compressed: bytes, settings: Settings) -> bytes:
    decoder = zlib.decompressobj()
    try:
        body = decoder.decompress(compressed, settings.inventory_max_bytes + 1)
    except zlib.error as error:
        raise CorruptInventoryError from error
    if len(body) > settings.inventory_max_bytes or decoder.unconsumed_tail:
        raise InventoryTooLargeError(settings.inventory_max_bytes)
    if not decoder.eof or decoder.unused_data:
        raise CorruptInventoryError
    return body


def expand_inventory(content: bytes, settings: Settings) -> bytes:
    *header, compressed = content.split(b'\n', SPHINX_HEADER_LINES)
    if len(header) != SPHINX_HEADER_LINES or header[0] != SPHINX_INVENTORY_MAGIC:
        raise UnsupportedInventoryError
    body = inflate_inventory_body(compressed, settings)
    entry_count = body.count(b'\n') + int(bool(body) and not body.endswith(b'\n'))
    if entry_count > settings.inventory_max_entries:
        raise InventoryEntryLimitError(settings.inventory_max_entries)
    return b'\n'.join([*header, body])


def load_inventory(plaintext: bytes) -> Inventory:
    try:
        return cast('Callable[..., Inventory]', Inventory)(plaintext=plaintext)
    except (ValueError, TypeError, AttributeError, UnicodeError) as error:
        raise UnparseableInventoryError from error


def expanded_uri(entry: DataObjStr) -> str:
    uri = str(entry.uri)
    if not uri.endswith('$'):
        return uri
    return uri.removesuffix('$') + str(entry.name)


def entry_url(entry: DataObjStr, version: PythonVersion) -> DocumentationUrl | None:
    uri = expanded_uri(entry)
    if ambiguous_url_violation(uri) is not None:
        return None

    url = create_documentation_url(urljoin(version.base_url, uri))
    if not isinstance(url, DocumentationUrl):
        return None

    if url.version != version:
        return None

    return url


def is_indexed(url: DocumentationUrl, settings: Settings) -> bool:
    return url.page_path.partition('/')[0] in settings.indexed_sections


def located_symbols(
    entries: Iterable[DataObjStr], version: PythonVersion, settings: Settings
) -> dict[str, Symbol]:
    python_entries = [entry for entry in entries if entry.domain == 'py']
    urls = [entry_url(entry, version) for entry in python_entries]
    malformed = urls.count(None)
    if malformed > settings.max_malformed_entry_ratio * len(python_entries):
        raise MalformedInventoryError(malformed, len(python_entries))
    return {
        entry.name: Symbol(name=entry.name, kind=entry.role, source_url=url)
        for entry, url in zip(python_entries, urls, strict=True)
        if url is not None and is_indexed(url, settings)
    }


def parse_inventory(content: bytes, version: PythonVersion, settings: Settings) -> SymbolIndex:
    inventory = load_inventory(expand_inventory(content, settings))
    symbols = located_symbols(inventory.objects, version, settings)
    if not symbols:
        raise EmptyInventoryError
    return SymbolIndex(documentation_version=str(inventory.version), symbols=symbols)

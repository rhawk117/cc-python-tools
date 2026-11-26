"""Validated documentation versions, official URLs, and the per-version symbol index."""

import re
from dataclasses import dataclass
from urllib.parse import urldefrag, urlsplit

from python_agent_tools_docs.errors import (
    AmbiguousUrlError,
    ForeignUrlError,
    InvalidVersionError,
    UnversionedUrlError,
)

DOCUMENTATION_HOST = 'docs.python.org'
VERSION_PATTERN = r'3\.(0|[1-9][0-9]?)'

type UrlViolation = AmbiguousUrlError | ForeignUrlError | UnversionedUrlError


def python_version_violation(text: str) -> InvalidVersionError | None:
    if re.fullmatch(VERSION_PATTERN, text) is None:
        return InvalidVersionError(text)
    return None


def has_unsafe_characters(url: str) -> bool:
    return not url.isprintable() or any(map(str.isspace, url)) or '\\' in url


def has_ambiguous_path(path: str) -> bool:
    return '%' in path or not {'.', '..'}.isdisjoint(path.split('/'))


def ambiguous_url_violation(url: str) -> AmbiguousUrlError | None:
    if has_unsafe_characters(url):
        return AmbiguousUrlError()

    try:
        path = urlsplit(url).path
    except ValueError:
        return AmbiguousUrlError()

    if has_ambiguous_path(path):
        return AmbiguousUrlError()

    return None


def is_official_origin(url: str) -> bool:
    parsed = urlsplit(url)
    return (
        parsed.scheme == 'https'
        and parsed.netloc == DOCUMENTATION_HOST
        and '?' not in url.partition('#')[0]
    )


def documentation_url_violation(url: str) -> UrlViolation | None:
    if (ambiguity := ambiguous_url_violation(url)) is not None:
        return ambiguity
    if not is_official_origin(url):
        return ForeignUrlError()
    version_text, _, page = urlsplit(url).path.removeprefix('/').partition('/')
    if not page or re.fullmatch(VERSION_PATTERN, version_text) is None:
        return UnversionedUrlError()
    return None


@dataclass(frozen=True, slots=True, kw_only=True)
class PythonVersion:
    text: str

    @property
    def base_url(self) -> str:
        return f'https://{DOCUMENTATION_HOST}/{self.text}/'

    @property
    def minor(self) -> int:
        return int(self.text.removeprefix('3.'))


@dataclass(frozen=True, slots=True, kw_only=True)
class DocumentationUrl:
    text: str

    @property
    def path(self) -> str:
        return urlsplit(self.text).path

    @property
    def version(self) -> PythonVersion:
        return PythonVersion(text=self.path.split('/')[1])

    @property
    def page_path(self) -> str:
        return self.path.removeprefix('/').partition('/')[2]

    @property
    def fragment(self) -> str:
        return urldefrag(self.text).fragment

    @property
    def page_url(self) -> DocumentationUrl:
        return DocumentationUrl(text=urldefrag(self.text).url)


def create_python_version(text: str) -> PythonVersion | InvalidVersionError:
    return python_version_violation(text) or PythonVersion(text=text)


def create_documentation_url(text: str) -> DocumentationUrl | UrlViolation:
    return documentation_url_violation(text) or DocumentationUrl(text=text)


@dataclass(frozen=True, slots=True, kw_only=True)
class Symbol:
    name: str
    kind: str
    source_url: DocumentationUrl


@dataclass(frozen=True, slots=True, kw_only=True)
class SymbolIndex:
    documentation_version: str
    symbols: dict[str, Symbol]

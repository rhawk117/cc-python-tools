"""CommonMark fenced code block tracking for paged section text."""

import re
from dataclasses import dataclass

OPENING_FENCE = re.compile(r' {0,3}(`{3,}|~{3,})(.*)')
MAX_FENCE_INDENT = 3


@dataclass(frozen=True, slots=True, kw_only=True)
class Fence:
    marker: str
    info: str = ''

    @property
    def opening(self) -> str:
        return f'{self.marker}{self.info}'

    @property
    def closing(self) -> str:
        return self.marker

    def is_closed_by(self, line: str) -> bool:
        stripped = line.lstrip(' ')
        indent = len(line) - len(stripped)
        bare = stripped.rstrip(' \t')
        if indent > MAX_FENCE_INDENT or len(bare) < len(self.marker):
            return False

        return bare == self.marker[0] * len(bare)


def read_fence(line: str) -> Fence | None:
    found = OPENING_FENCE.fullmatch(line)
    if found is None:
        return None

    marker, info = found.group(1), found.group(2).strip()
    if marker[0] == '`' and '`' in info:
        return None

    return Fence(marker=marker, info=info)


def advance_fence(fence: Fence | None, line: str) -> Fence | None:
    if fence is None:
        return read_fence(line)

    if fence.is_closed_by(line):
        return None

    return fence


def scan_fence(text: str, fence: Fence | None = None) -> Fence | None:
    for line in text.split('\n'):
        fence = advance_fence(fence, line.rstrip('\r'))
    return fence


def fence_before(text: str, offset: int) -> Fence | None:
    head = text[:offset]
    if text[offset : offset + 1] not in {'\n', ''}:
        head = head.rpartition('\n')[0]
    return scan_fence(head)

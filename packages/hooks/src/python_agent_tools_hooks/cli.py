"""The `python-agent-tools-hooks` console script, which refuses every subcommand for now.

`hooks/hook.sh` runs it with one subcommand per hook in `hooks/hooks.json` and the hook payload on
standard input. No hook is registered yet, so every subcommand is refused with one line on standard
error and exit code 2.
"""

import sys
from dataclasses import dataclass
from typing import TYPE_CHECKING, TextIO

if TYPE_CHECKING:
    from collections.abc import Sequence

REFUSED = 2
PROGRAM = 'python-agent-tools-hooks'


@dataclass(slots=True, kw_only=True, frozen=True)
class HookCommand:
    stderr: TextIO

    def refuse(self, message: str) -> int:
        self.stderr.write(f'{PROGRAM}: {message}\n')
        return REFUSED

    def run(self, argv: Sequence[str]) -> int:
        if len(argv) != 1:
            return self.refuse('expected exactly one subcommand')

        return self.refuse(f'unknown subcommand {argv[0]!r}')


def main() -> int:
    return HookCommand(stderr=sys.stderr).run(sys.argv[1:])

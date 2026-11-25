from pathlib import Path
from typing import TYPE_CHECKING

import anyio

if TYPE_CHECKING:
    from subprocess import CompletedProcess

HOOK_SCRIPT = Path(__file__).resolve().parents[4].joinpath('hooks', 'hook.sh')
SUBCOMMAND = 'session-start'


class TestHookWrapper:
    payload = b'{"hook_event_name": "SessionStart"}'

    async def run_hook(self, subcommand: str) -> CompletedProcess[bytes]:
        return await anyio.run_process(
            ['sh', str(HOOK_SCRIPT), subcommand], input=self.payload, check=False
        )

    async def test_refused_subcommand_reaches_the_cli_and_the_hook_exits_zero(self) -> None:
        done = await self.run_hook(SUBCOMMAND)
        stderr = done.stderr.decode()

        assert done.returncode == 0
        assert done.stdout == b''
        assert f"python-agent-tools-hooks: unknown subcommand '{SUBCOMMAND}'" in stderr
        assert f'python-agent-tools hook did nothing: {SUBCOMMAND} could not run' in stderr

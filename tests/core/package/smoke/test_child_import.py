from typing import TYPE_CHECKING

import anyio

if TYPE_CHECKING:
    from subprocess import CompletedProcess


class TestChildImport:
    command = (
        'uv',
        'run',
        '--isolated',
        '--quiet',
        '--locked',
        '--no-dev',
        '--package',
        'python-agent-tools-core',
        'python',
        '-c',
        'import python_agent_tools_core',
    )

    async def run_child(self) -> CompletedProcess[bytes]:
        return await anyio.run_process(self.command, check=False)

    async def test_locked_core_package_imports_cleanly_in_a_uv_child(self) -> None:
        done = await self.run_child()
        stderr = done.stderr.decode()

        assert done.returncode == 0, stderr
        assert stderr == '', stderr

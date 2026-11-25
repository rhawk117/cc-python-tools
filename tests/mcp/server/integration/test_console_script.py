import json
import sys
from pathlib import Path
from typing import Any

import anyio
from python_agent_tools_mcp.server import SERVER_NAME

CONSOLE_SCRIPT = Path(sys.executable).with_name('python-agent-tools-mcp')
INITIALIZE = {
    'jsonrpc': '2.0',
    'id': 1,
    'method': 'initialize',
    'params': {
        'protocolVersion': '2025-06-18',
        'capabilities': {},
        'clientInfo': {'name': 'console-script-test', 'version': '0'},
    },
}


class TestConsoleScript:
    stdin = f'{json.dumps(INITIALIZE)}\n'.encode()

    async def read_messages(self) -> list[dict[str, Any]]:
        done = await anyio.run_process([str(CONSOLE_SCRIPT)], input=self.stdin, check=False)
        return [json.loads(line) for line in done.stdout.decode().splitlines()]

    async def test_initialize_is_answered_with_the_server_name(self) -> None:
        messages = await self.read_messages()

        reply = next(message for message in messages if message.get('id') == 1)
        assert all(message['jsonrpc'] == '2.0' for message in messages)
        assert reply['result']['serverInfo']['name'] == SERVER_NAME

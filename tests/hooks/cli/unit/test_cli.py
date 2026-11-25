import io

import pytest
from python_agent_tools_hooks.cli import PROGRAM, REFUSED, HookCommand


def refused_argv_cases() -> pytest.MarkDecorator:
    return pytest.mark.parametrize(
        'argv',
        [
            pytest.param([], id='no-subcommand'),
            pytest.param(['session-start'], id='unregistered-subcommand'),
            pytest.param(['session-start', 'extra'], id='two-subcommands'),
        ],
    )


class TestHookCommand:
    def run_command(self, argv: list[str]) -> tuple[int, str]:
        stderr = io.StringIO()
        code = HookCommand(stderr=stderr).run(argv)
        return code, stderr.getvalue()

    @refused_argv_cases()
    def test_argv_is_refused_with_one_line_on_stderr(self, argv: list[str]) -> None:
        code, stderr = self.run_command(argv)

        assert code == REFUSED
        assert stderr.startswith(f'{PROGRAM}: ')
        assert stderr.count('\n') == 1

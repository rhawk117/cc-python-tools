"""Failures shared across the workspace's tools, with messages safe to show the calling model."""


class PythonAgentToolsError(Exception):
    pass


class InvalidVersionError(PythonAgentToolsError, ValueError):
    def __init__(self, version: str) -> None:
        super().__init__(f'{version!r} is not a Python 3 minor version such as 3.13.')


class VersionRequiredError(PythonAgentToolsError):
    def __init__(self, reason: str) -> None:
        super().__init__(
            'Pass version, a Python minor version such as 3.13:'
            f' no default was found because {reason}.'
        )

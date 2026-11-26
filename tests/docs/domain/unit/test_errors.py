import inspect
from dataclasses import dataclass
from typing import TYPE_CHECKING

import pytest
from python_agent_tools_core.exception import (
    InvalidVersionError,
    VersionRequiredError,
)
from python_docs_mcp.core import exception as errors
from python_docs_mcp.core.exception import (
    AmbiguousUrlError,
    CallDeadlineExceededError,
    CapacityError,
    CorruptInventoryError,
    DocumentationError,
    DocumentationToolsError,
    DownloadTooLargeError,
    EmptyExtractionError,
    EmptyInventoryError,
    FillInterruptedError,
    FillTimeoutError,
    ForeignUrlError,
    InventoryEntryLimitError,
    InventoryTooLargeError,
    MalformedInventoryError,
    MissingAnchorError,
    MissingDefinitionBodyError,
    MissingSectionError,
    OffsetOutOfRangeError,
    PageNotFoundError,
    PermanentMissError,
    RetrievalFailedError,
    UnknownSymbolError,
    UnparseableInventoryError,
    UnsupportedInventoryError,
    UnversionedUrlError,
    UpstreamStatusError,
    VersionNotPublishedError,
)

if TYPE_CHECKING:
    from _pytest.mark import ParameterSet
    from python_agent_tools_core.exception import PythonAgentToolsError


@dataclass(slots=True, kw_only=True, frozen=True)
class MessageScenario:
    name: str
    error: PythonAgentToolsError
    message: str

    @property
    def param(self) -> ParameterSet:
        return pytest.param(self, id=self.name)


def message_cases() -> pytest.MarkDecorator:
    scenarios = [
        MessageScenario(
            name='AmbiguousUrlError',
            error=AmbiguousUrlError(),
            message='Encoded, ambiguous, whitespace, or control characters are not allowed'
            ' in documentation URLs.',
        ),
        MessageScenario(
            name='ForeignUrlError',
            error=ForeignUrlError(),
            message='URL must use https://docs.python.org without a query.',
        ),
        MessageScenario(
            name='UnversionedUrlError',
            error=UnversionedUrlError(),
            message='A versioned documentation page path is required.',
        ),
        MessageScenario(
            name='InvalidVersionError',
            error=InvalidVersionError('4.0'),
            message="'4.0' is not a Python 3 minor version such as 3.13.",
        ),
        MessageScenario(
            name='UnsupportedInventoryError',
            error=UnsupportedInventoryError(),
            message='Unsupported or malformed Sphinx inventory header.',
        ),
        MessageScenario(
            name='CorruptInventoryError',
            error=CorruptInventoryError(),
            message='The documentation inventory is corrupt or incomplete.',
        ),
        MessageScenario(
            name='InventoryTooLargeError',
            error=InventoryTooLargeError(10),
            message='Expanded inventory exceeds 10 bytes.',
        ),
        MessageScenario(
            name='InventoryEntryLimitError',
            error=InventoryEntryLimitError(5),
            message='Documentation inventory exceeds 5 entries.',
        ),
        MessageScenario(
            name='UnparseableInventoryError',
            error=UnparseableInventoryError(),
            message='Could not parse the official Python inventory.',
        ),
        MessageScenario(
            name='MalformedInventoryError',
            error=MalformedInventoryError(2, 9),
            message='2 of 9 Python inventory entries have unusable URLs.',
        ),
        MessageScenario(
            name='EmptyInventoryError',
            error=EmptyInventoryError(),
            message='The inventory contains no standard-library symbols.',
        ),
        MessageScenario(
            name='MissingDefinitionBodyError',
            error=MissingDefinitionBodyError(),
            message='The documented symbol has no definition body.',
        ),
        MessageScenario(
            name='MissingAnchorError',
            error=MissingAnchorError('os.getcwd'),
            message="Anchor 'os.getcwd' is missing from the official page.",
        ),
        MessageScenario(
            name='MissingSectionError',
            error=MissingSectionError(),
            message="The symbol's documentation section is missing.",
        ),
        MessageScenario(
            name='EmptyExtractionError',
            error=EmptyExtractionError(),
            message='The extracted documentation is empty.',
        ),
        MessageScenario(
            name='DownloadTooLargeError',
            error=DownloadTooLargeError(7),
            message='Documentation response exceeds 7 bytes.',
        ),
        MessageScenario(
            name='UpstreamStatusError',
            error=UpstreamStatusError(503),
            message='Official documentation returned HTTP 503.',
        ),
        MessageScenario(
            name='PageNotFoundError',
            error=PageNotFoundError('https://docs.python.org/3.13/x.html'),
            message='Official documentation has no page at https://docs.python.org/3.13/x.html.',
        ),
        MessageScenario(
            name='VersionNotPublishedError',
            error=VersionNotPublishedError('3.99'),
            message='Python 3.99 documentation is not published. Read requires-python'
            ' in pyproject.toml or .python-version for the project version.',
        ),
        MessageScenario(
            name='RetrievalFailedError',
            error=RetrievalFailedError('https://docs.python.org/'),
            message='Could not reach the official documentation at https://docs.python.org/.',
        ),
        MessageScenario(
            name='FillTimeoutError',
            error=FillTimeoutError(2.5),
            message='Documentation retrieval exceeded its 2.5s deadline.',
        ),
        MessageScenario(
            name='FillInterruptedError',
            error=FillInterruptedError(),
            message='Documentation retrieval was interrupted; retry the call.',
        ),
        MessageScenario(
            name='CallDeadlineExceededError',
            error=CallDeadlineExceededError(30),
            message='The call exceeded its 30s deadline; retry shortly.',
        ),
        MessageScenario(
            name='UnknownSymbolError-with-suggestions',
            error=UnknownSymbolError('os.getcw', ['os.getcwd', 'os.getcwdb']),
            message="Unknown symbol 'os.getcw' for this Python version."
            ' Closest names: os.getcwd, os.getcwdb.'
            ' Use search_python_docs to find exact names.',
        ),
        MessageScenario(
            name='UnknownSymbolError-without-suggestions',
            error=UnknownSymbolError('zzz', []),
            message="Unknown symbol 'zzz' for this Python version."
            ' Use search_python_docs to find exact names.',
        ),
        MessageScenario(
            name='OffsetOutOfRangeError',
            error=OffsetOutOfRangeError(50, 10),
            message='Offset 50 exceeds the section length (10).',
        ),
        MessageScenario(
            name='CapacityError',
            error=CapacityError('cache', 'page'),
            message='cache must be at least page',
        ),
        MessageScenario(
            name='VersionRequiredError',
            error=VersionRequiredError('no installed Python was found'),
            message='Pass version, a Python minor version such as 3.13:'
            ' no default was found because no installed Python was found.',
        ),
    ]
    return pytest.mark.parametrize('scenario', [scenario.param for scenario in scenarios])


def error_classes() -> list[type[DocumentationToolsError]]:
    return [
        member
        for _, member in inspect.getmembers(errors, inspect.isclass)
        if issubclass(member, DocumentationToolsError)
        and member is not DocumentationToolsError
        and member.__module__ == errors.__name__
    ]


def hierarchy_cases() -> pytest.MarkDecorator:
    return pytest.mark.parametrize(
        'error_class', [pytest.param(cls, id=cls.__name__) for cls in error_classes()]
    )


class TestErrors:
    @message_cases()
    def test_message_matches_the_source_text(self, scenario: MessageScenario) -> None:
        assert str(scenario.error) == scenario.message

    @hierarchy_cases()
    def test_error_sits_under_the_root(self, error_class: type[DocumentationToolsError]) -> None:
        assert issubclass(error_class, DocumentationToolsError)

    def test_every_source_error_class_exists(self) -> None:
        assert len(error_classes()) == 27

    def test_permanent_miss_is_a_documentation_error(self) -> None:
        assert issubclass(VersionNotPublishedError, PermanentMissError)
        assert issubclass(PermanentMissError, DocumentationError)

    def test_input_violations_are_value_errors(self) -> None:
        assert issubclass(InvalidVersionError, ValueError)
        assert issubclass(CapacityError, ValueError)

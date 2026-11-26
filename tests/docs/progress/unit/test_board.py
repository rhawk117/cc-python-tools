import logging
from dataclasses import dataclass, field

import anyio
import pytest
from python_agent_tools_docs.domain import PythonVersion
from python_agent_tools_docs.progress import ProgressBoard

LOGGER_NAME = 'python_agent_tools_docs.progress'


@dataclass(slots=True, kw_only=True)
class RecordingWatcher:
    reports: list[tuple[int, int | None]] = field(default_factory=list)

    async def report(self, read: int, total: int | None) -> None:
        self.reports.append((read, total))


@dataclass(slots=True, kw_only=True)
class RaisingWatcher:
    failure: BaseException
    attempts: list[tuple[int, int | None]] = field(default_factory=list)

    async def report(self, read: int, total: int | None) -> None:
        self.attempts.append((read, total))
        raise self.failure


@dataclass(slots=True, kw_only=True, frozen=True)
class BoardHarness:
    board: ProgressBoard
    version: PythonVersion


class TestProgressBoardPublish:
    @pytest.fixture
    def harness(self) -> BoardHarness:
        return BoardHarness(board=ProgressBoard(), version=PythonVersion(text='3.14'))

    async def test_failing_watcher_does_not_starve_the_others(
        self,
        harness: BoardHarness,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        recorder = RecordingWatcher()
        failing = RaisingWatcher(failure=RuntimeError('dead watcher'))
        with (
            caplog.at_level(logging.WARNING, logger=LOGGER_NAME),
            harness.board.watch(harness.version, failing),
            harness.board.watch(harness.version, recorder),
        ):
            await harness.board.publish(harness.version, 1, 10)
            await harness.board.publish(harness.version, 2, 10)

        assert recorder.reports == [(1, 10), (2, 10)]
        records = [record for record in caplog.records if record.name == LOGGER_NAME]
        assert [record.levelno for record in records] == [logging.WARNING, logging.WARNING]
        assert all(record.exc_info is not None for record in records)

    async def test_cancellation_reaches_the_publisher(self, harness: BoardHarness) -> None:
        cancelled = RaisingWatcher(failure=anyio.get_cancelled_exc_class()())
        with (
            harness.board.watch(harness.version, cancelled),
            pytest.raises(anyio.get_cancelled_exc_class()),
        ):
            await harness.board.publish(harness.version, 1, 10)

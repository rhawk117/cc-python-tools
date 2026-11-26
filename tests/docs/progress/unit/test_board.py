import logging
from contextlib import ExitStack
from dataclasses import dataclass, field

import anyio
import pytest
from python_agent_tools_docs import progress
from python_agent_tools_docs.domain import PythonVersion
from python_agent_tools_docs.progress import ProgressBoard


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


@dataclass(slots=True, kw_only=True)
class LeavingWatcher:
    failure: BaseException
    scope: ExitStack = field(default_factory=ExitStack)
    attempts: list[tuple[int, int | None]] = field(default_factory=list)

    async def report(self, read: int, total: int | None) -> None:
        self.attempts.append((read, total))
        self.scope.close()
        raise self.failure


@dataclass(slots=True, kw_only=True, frozen=True)
class BoardHarness:
    board: ProgressBoard
    version: PythonVersion
    recorder: RecordingWatcher
    failing: RaisingWatcher
    cancelled: RaisingWatcher
    leaving: LeavingWatcher


class TestProgressBoard:
    logger_name = progress.logger.name

    @pytest.fixture
    async def harness(self) -> BoardHarness:
        return BoardHarness(
            board=ProgressBoard(),
            version=PythonVersion(text='3.14'),
            recorder=RecordingWatcher(),
            failing=RaisingWatcher(failure=RuntimeError('dead watcher')),
            cancelled=RaisingWatcher(failure=anyio.get_cancelled_exc_class()()),
            leaving=LeavingWatcher(failure=RuntimeError('left before failing')),
        )

    async def test_failing_watcher_does_not_starve_the_others(
        self,
        harness: BoardHarness,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        with (
            caplog.at_level(logging.WARNING, logger=self.logger_name),
            harness.board.watch(harness.version, harness.failing),
            harness.board.watch(harness.version, harness.recorder),
        ):
            await harness.board.publish(harness.version, 1, 10)
            await harness.board.publish(harness.version, 2, 10)
            await harness.board.publish(harness.version, 3, 10)

        assert harness.recorder.reports == [(1, 10), (2, 10), (3, 10)]
        records = [record for record in caplog.records if record.name == self.logger_name]
        assert [record.levelno for record in records] == [logging.WARNING]
        assert all(record.exc_info is not None for record in records)

    async def test_failed_watcher_is_skipped_after_its_first_failure(
        self,
        harness: BoardHarness,
    ) -> None:
        with harness.board.watch(harness.version, harness.failing):
            await harness.board.publish(harness.version, 1, 10)
            await harness.board.publish(harness.version, 2, 10)

        assert harness.failing.attempts == [(1, 10)]

    async def test_failed_watcher_is_forgotten_when_its_watch_exits(
        self,
        harness: BoardHarness,
    ) -> None:
        with harness.board.watch(harness.version, harness.failing):
            await harness.board.publish(harness.version, 1, 10)
        with harness.board.watch(harness.version, harness.failing):
            await harness.board.publish(harness.version, 2, 10)

        assert harness.failing.attempts == [(1, 10), (2, 10)]

    async def test_failed_watcher_is_forgotten_when_it_exits_beside_another_watcher(
        self,
        harness: BoardHarness,
    ) -> None:
        with harness.board.watch(harness.version, harness.recorder):
            with harness.board.watch(harness.version, harness.failing):
                await harness.board.publish(harness.version, 1, 10)
            with harness.board.watch(harness.version, harness.failing):
                await harness.board.publish(harness.version, 2, 10)

        assert harness.failing.attempts == [(1, 10), (2, 10)]

    async def test_watcher_failing_after_its_watch_exited_leaves_no_failure_record(
        self,
        harness: BoardHarness,
    ) -> None:
        with harness.board.watch(harness.version, harness.recorder):
            harness.leaving.scope.enter_context(
                harness.board.watch(harness.version, harness.leaving),
            )
            await harness.board.publish(harness.version, 1, 10)
            with harness.board.watch(harness.version, harness.leaving):
                await harness.board.publish(harness.version, 2, 10)

        assert harness.leaving.attempts == [(1, 10), (2, 10)]
        assert harness.recorder.reports == [(1, 10), (2, 10)]

    async def test_cancellation_reaches_the_publisher(self, harness: BoardHarness) -> None:
        with (
            harness.board.watch(harness.version, harness.cancelled),
            pytest.raises(anyio.get_cancelled_exc_class()),
        ):
            await harness.board.publish(harness.version, 1, 10)

    async def test_watcher_count_is_zero_when_unwatched(self, harness: BoardHarness) -> None:
        assert harness.board.watcher_count(harness.version) == 0

    async def test_watcher_count_follows_the_watch_blocks(self, harness: BoardHarness) -> None:
        with (
            harness.board.watch(harness.version, harness.recorder),
            harness.board.watch(harness.version, harness.failing),
        ):
            assert harness.board.watcher_count(harness.version) == 2
        assert harness.board.watcher_count(harness.version) == 0

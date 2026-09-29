"""Fix #46, part 4: rate-limited failure logging and the handler_failures counter.

A control handler (or the analog output tracking store) that keeps failing the
same way on every request must not flood the log at whatever rate the peer
sends requests. The first failure of a (function, handler method, exception
type) key logs an ERROR record with its traceback; later failures of the same
key within 60 s are counted, not logged; the next record for that key after
the window reports how many were suppressed. Every covered failure also
increments ``Outstation.handler_failures``, logged or not, so a supervisor can
alarm without parsing logs.
"""

from __future__ import annotations

import logging
import time

import pytest

from dnp3.application.fragment import ObjectBlock, RequestFragment
from dnp3.application.header import RequestHeader
from dnp3.application.qualifiers import ObjectHeader
from dnp3.core.enums import ControlCode, FunctionCode
from dnp3.core.flags import AnalogQuality
from dnp3.core.timestamp import DNP3Timestamp
from dnp3.database import Database
from dnp3.outstation._failure_log import WINDOW_SECONDS
from dnp3.outstation.handler import CommandResult, DefaultCommandHandler
from dnp3.outstation.outstation import Outstation
from dnp3.outstation.peer import PeerId

MASTER_A = PeerId(source=7, connection=1)

_CROB_BODY = bytes.fromhex("03 01 00000000 00000000 00")  # LATCH_ON, count 1, on/off 0, status 0.
_LOGGER_NAME = "dnp3.outstation.outstation"


class _FakeClock:
    """A monotonic clock the flood-control tests advance by hand, without sleeping."""

    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture
def fake_clock(monkeypatch: pytest.MonkeyPatch) -> _FakeClock:
    clock = _FakeClock()
    monkeypatch.setattr(time, "monotonic", clock)
    return clock


def _crob_block(index: int) -> ObjectBlock:
    header = ObjectHeader(group=12, variation=1, qualifier=0x17)
    return ObjectBlock(header=header, data=bytes([1, index]) + _CROB_BODY)


def _ao_block(*indices: int) -> ObjectBlock:
    """A well-formed g41v2 block, one 16-bit-int object per index, value 0."""
    header = ObjectHeader(group=41, variation=2, qualifier=0x17)
    data = bytes([len(indices)])
    for index in indices:
        data += bytes([index]) + (0).to_bytes(2, "little", signed=True) + bytes([0])
    return ObjectBlock(header=header, data=data)


def _direct_operate(*objects: ObjectBlock, no_ack: bool = False, seq: int = 0) -> RequestFragment:
    function = FunctionCode.DIRECT_OPERATE_NO_ACK if no_ack else FunctionCode.DIRECT_OPERATE
    return RequestFragment(header=RequestHeader.build(function=function, seq=seq), objects=objects)


def _select(*objects: ObjectBlock, seq: int = 0) -> RequestFragment:
    return RequestFragment(header=RequestHeader.build(function=FunctionCode.SELECT, seq=seq), objects=objects)


class _RaisingBinaryHandler(DefaultCommandHandler):
    """direct_operate_binary_output and select_binary_output always raise RuntimeError."""

    def direct_operate_binary_output(
        self, index: int, code: ControlCode, count: int, on_time: int, off_time: int
    ) -> CommandResult:
        msg = f"boom direct_operate {index}"
        raise RuntimeError(msg)

    def select_binary_output(
        self, index: int, code: ControlCode, count: int, on_time: int, off_time: int
    ) -> CommandResult:
        msg = f"boom select {index}"
        raise RuntimeError(msg)


class _SucceedingHandler(DefaultCommandHandler):
    """Every control method used by these tests succeeds (the base class rejects by default)."""

    def direct_operate_binary_output(
        self, index: int, code: ControlCode, count: int, on_time: int, off_time: int
    ) -> CommandResult:
        return CommandResult.success()

    def direct_operate_analog_output(self, index: int, value: float) -> CommandResult:
        return CommandResult.success()


class _RaisingUpdateDatabase(Database):
    """update_analog_output always raises RuntimeError, standing for a broken tracking store."""

    def update_analog_output(
        self,
        index: int,
        value: float,
        quality: AnalogQuality | None = None,
        timestamp: DNP3Timestamp | None = None,
    ) -> bool:
        msg = f"boom update_analog_output {index}"
        raise RuntimeError(msg)


def _records(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [r for r in caplog.records if r.name == _LOGGER_NAME]


class TestFloodControlWithinOneWindow:
    """Fifty raises of one key inside the 60 s window give one record (kills the no-suppression mutant)."""

    def test_fifty_raises_give_one_record_and_the_counter_reads_fifty(
        self, fake_clock: _FakeClock, caplog: pytest.LogCaptureFixture
    ) -> None:
        outstation = Outstation(handler=_RaisingBinaryHandler())
        request = _direct_operate(_crob_block(1))

        with caplog.at_level(logging.ERROR, logger=_LOGGER_NAME):
            for _ in range(50):
                outstation.process_request(request.to_bytes())

        assert len(_records(caplog)) == 1
        assert outstation.handler_failures == 50

    def test_the_first_raise_after_the_window_reports_forty_nine_suppressed(
        self, fake_clock: _FakeClock, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Kills both the no-suppressed-count mutant and the window-never-expires mutant."""
        outstation = Outstation(handler=_RaisingBinaryHandler())
        request = _direct_operate(_crob_block(1))

        with caplog.at_level(logging.ERROR, logger=_LOGGER_NAME):
            for _ in range(50):
                outstation.process_request(request.to_bytes())
            fake_clock.advance(WINDOW_SECONDS)
            outstation.process_request(request.to_bytes())

        records = _records(caplog)
        assert len(records) == 2
        assert "49" in records[1].getMessage()
        assert "suppressed" in records[1].getMessage()
        assert outstation.handler_failures == 51

    def test_a_raise_still_inside_the_window_stays_suppressed(
        self, fake_clock: _FakeClock, caplog: pytest.LogCaptureFixture
    ) -> None:
        """A window that expired too early would make this second raise log too."""
        outstation = Outstation(handler=_RaisingBinaryHandler())
        request = _direct_operate(_crob_block(1))

        with caplog.at_level(logging.ERROR, logger=_LOGGER_NAME):
            outstation.process_request(request.to_bytes())
            fake_clock.advance(WINDOW_SECONDS - 1)
            outstation.process_request(request.to_bytes())

        assert len(_records(caplog)) == 1
        assert outstation.handler_failures == 2


class TestTwoKeysAreIndependent:
    def test_two_different_keys_give_two_records(
        self, fake_clock: _FakeClock, caplog: pytest.LogCaptureFixture
    ) -> None:
        outstation = Outstation(handler=_RaisingBinaryHandler())

        with caplog.at_level(logging.ERROR, logger=_LOGGER_NAME):
            outstation.process_request(_direct_operate(_crob_block(1)).to_bytes())
            outstation.process_request(_select(_crob_block(1)).to_bytes(), peer=MASTER_A)

        assert len(_records(caplog)) == 2
        assert outstation.handler_failures == 2


class TestSuccessPathLogsNothing:
    def test_no_record_and_no_counter_change_on_success(
        self, fake_clock: _FakeClock, caplog: pytest.LogCaptureFixture
    ) -> None:
        outstation = Outstation(handler=_SucceedingHandler())
        request = _direct_operate(_crob_block(1))

        with caplog.at_level(logging.ERROR, logger=_LOGGER_NAME):
            responses = outstation.process_request(request.to_bytes())

        assert len(_records(caplog)) == 0
        assert outstation.handler_failures == 0
        assert responses  # sanity: the request was answered normally


class TestNoAckFailureStillLogsOncePerWindow:
    def test_no_ack_raises_repeatedly_but_logs_once(
        self, fake_clock: _FakeClock, caplog: pytest.LogCaptureFixture
    ) -> None:
        outstation = Outstation(handler=_RaisingBinaryHandler())
        request = _direct_operate(_crob_block(1), no_ack=True)

        with caplog.at_level(logging.ERROR, logger=_LOGGER_NAME):
            for _ in range(3):
                responses = outstation.process_request(request.to_bytes())

        assert responses == []
        assert len(_records(caplog)) == 1
        assert outstation.handler_failures == 3


class TestTrackingFailureOnFivePoints:
    """Item 4: the tracking failure used to log per point; the limiter gives one record for the key."""

    def test_five_points_fail_tracking_after_a_successful_operate_give_one_record(
        self, fake_clock: _FakeClock, caplog: pytest.LogCaptureFixture
    ) -> None:
        db = _RaisingUpdateDatabase()
        for index in range(5):
            db.add_analog_output(index)
        outstation = Outstation(database=db, handler=_SucceedingHandler())
        request = _direct_operate(_ao_block(0, 1, 2, 3, 4))

        with caplog.at_level(logging.ERROR, logger=_LOGGER_NAME):
            responses = outstation.process_request(request.to_bytes())

        data = responses[0].objects[0].data
        statuses = [data[1 + position * 4 + 3] for position in range(5)]
        assert statuses == [0, 0, 0, 0, 0]  # every point still answers SUCCESS: the operate itself did not fail
        assert len(_records(caplog)) == 1
        assert outstation.handler_failures == 5


class TestErrorRecordContent:
    """L1: one ERROR record names the function, the point index, and the peer, with a traceback."""

    def test_control_raise_names_function_index_peer_and_carries_a_traceback(
        self, fake_clock: _FakeClock, caplog: pytest.LogCaptureFixture
    ) -> None:
        outstation = Outstation(handler=_RaisingBinaryHandler())
        request = _select(_crob_block(9), seq=1)

        with caplog.at_level(logging.ERROR, logger=_LOGGER_NAME):
            outstation.process_request(request.to_bytes(), peer=MASTER_A)

        records = _records(caplog)
        assert len(records) == 1
        message = records[0].getMessage()
        assert "SELECT" in message
        assert "9" in message
        assert "source=7" in message
        assert "connection=1" in message
        assert records[0].exc_info is not None
        assert records[0].exc_info[0] is RuntimeError

    def test_no_master_supplied_value_in_the_tracking_failure_message(
        self, fake_clock: _FakeClock, caplog: pytest.LogCaptureFixture
    ) -> None:
        db = _RaisingUpdateDatabase()
        db.add_analog_output(0)
        outstation = Outstation(database=db, handler=_SucceedingHandler())
        header = ObjectHeader(group=41, variation=2, qualifier=0x17)
        # A distinctive commanded value: it must never reach the log message.
        block = ObjectBlock(header=header, data=bytes([1, 0]) + (12345).to_bytes(2, "little", signed=True) + bytes([0]))
        request = _direct_operate(block)

        with caplog.at_level(logging.ERROR, logger=_LOGGER_NAME):
            outstation.process_request(request.to_bytes())

        records = _records(caplog)
        assert len(records) == 1
        assert "12345" not in records[0].getMessage()

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
import struct
import time

import pytest

from dnp3.application.fragment import ObjectBlock, RequestFragment
from dnp3.application.header import RequestHeader
from dnp3.application.qualifiers import ObjectHeader
from dnp3.core.enums import ControlCode, FunctionCode
from dnp3.core.flags import AnalogQuality
from dnp3.core.timestamp import DNP3Timestamp
from dnp3.database import Database
from dnp3.database.point import AnalogOutputPoint
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


def _ao_float_block(index: int, value: float) -> ObjectBlock:
    """A well-formed g41v3 (float32) block, one object, for the NaN refusal tests."""
    header = ObjectHeader(group=41, variation=3, qualifier=0x17)
    data = bytes([1, index]) + struct.pack("<f", value) + bytes([0])
    return ObjectBlock(header=header, data=data)


def _direct_operate(*objects: ObjectBlock, no_ack: bool = False, seq: int = 0) -> RequestFragment:
    function = FunctionCode.DIRECT_OPERATE_NO_ACK if no_ack else FunctionCode.DIRECT_OPERATE
    return RequestFragment(header=RequestHeader.build(function=function, seq=seq), objects=objects)


def _select(*objects: ObjectBlock, seq: int = 0) -> RequestFragment:
    return RequestFragment(header=RequestHeader.build(function=FunctionCode.SELECT, seq=seq), objects=objects)


class _RaisingBinaryHandler(DefaultCommandHandler):
    """direct_operate_binary_output, select_binary_output and select_analog_output always raise RuntimeError."""

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

    def select_analog_output(self, index: int, value: float) -> CommandResult:
        msg = f"boom select analog {index}"
        raise RuntimeError(msg)


class _ConfigurableRaisingHandler(DefaultCommandHandler):
    """direct_operate_binary_output always raises a configured exception class."""

    def __init__(self, exc_cls: type[BaseException]) -> None:
        super().__init__()
        self.exc_cls = exc_cls

    def direct_operate_binary_output(
        self, index: int, code: ControlCode, count: int, on_time: int, off_time: int
    ) -> CommandResult:
        msg = f"boom {self.exc_cls.__name__} {index}"
        raise self.exc_cls(msg)


class _InvalidReturnHandler(DefaultCommandHandler):
    """direct_operate_binary_output always returns a fixed, invalid value."""

    def __init__(self, bad_return: object) -> None:
        super().__init__()
        self.bad_return = bad_return

    def direct_operate_binary_output(
        self, index: int, code: ControlCode, count: int, on_time: int, off_time: int
    ) -> CommandResult:
        return self.bad_return  # type: ignore[return-value]


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


class _RaisingLookupDatabase(Database):
    """get_analog_output always raises RuntimeError, standing for a broken lookup."""

    def get_analog_output(self, index: int) -> AnalogOutputPoint | None:
        msg = f"boom get_analog_output {index}"
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
    """The tracking failure used to log per point; the limiter gives one record for the key."""

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
    """One ERROR record names the function, the point index, and the peer, with a traceback."""

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


class TestNanRefusalIsRateLimited:
    """The refusal warning goes through the limiter too, under its own key, at WARNING."""

    def test_fifty_nan_commands_give_one_warning_and_no_counter_change(
        self, fake_clock: _FakeClock, caplog: pytest.LogCaptureFixture
    ) -> None:
        db = Database()
        db.add_analog_output(5, value=1.0)
        outstation = Outstation(database=db, handler=_SucceedingHandler())
        request = _direct_operate(_ao_float_block(5, float("nan")))

        with caplog.at_level(logging.WARNING, logger=_LOGGER_NAME):
            for _ in range(50):
                outstation.process_request(request.to_bytes())

        records = _records(caplog)
        assert len(records) == 1
        assert records[0].levelno == logging.WARNING
        assert outstation.handler_failures == 0

    def test_the_first_warning_after_the_window_reports_forty_nine_suppressed(
        self, fake_clock: _FakeClock, caplog: pytest.LogCaptureFixture
    ) -> None:
        db = Database()
        db.add_analog_output(5, value=1.0)
        outstation = Outstation(database=db, handler=_SucceedingHandler())
        request = _direct_operate(_ao_float_block(5, float("nan")))

        with caplog.at_level(logging.WARNING, logger=_LOGGER_NAME):
            for _ in range(50):
                outstation.process_request(request.to_bytes())
            fake_clock.advance(WINDOW_SECONDS)
            outstation.process_request(request.to_bytes())

        records = _records(caplog)
        assert len(records) == 2
        assert records[1].levelno == logging.WARNING
        assert "49" in records[1].getMessage()
        assert outstation.handler_failures == 0


class TestSuppressedCountWording:
    """The suppressed note names its own basis, not a fixed duration that may not have elapsed."""

    def test_the_note_says_since_the_previous_record_not_a_duration(
        self, fake_clock: _FakeClock, caplog: pytest.LogCaptureFixture
    ) -> None:
        outstation = Outstation(handler=_RaisingBinaryHandler())
        request = _direct_operate(_crob_block(1))

        with caplog.at_level(logging.ERROR, logger=_LOGGER_NAME):
            outstation.process_request(request.to_bytes())  # logs, opens the window
            fake_clock.advance(5.0)
            outstation.process_request(request.to_bytes())  # suppressed
            fake_clock.advance(500.0)  # long past the window
            outstation.process_request(request.to_bytes())  # first after the window

        records = _records(caplog)
        assert len(records) == 2
        message = records[1].getMessage()
        assert "since the previous record" in message
        assert "60" not in message


class TestWindowAnchoredToFirstFailure:
    """A window that slides with each suppressed failure never reaches the anchor's 60 s mark."""

    def test_window_does_not_slide_with_each_suppressed_failure(
        self, fake_clock: _FakeClock, caplog: pytest.LogCaptureFixture
    ) -> None:
        outstation = Outstation(handler=_RaisingBinaryHandler())
        request = _direct_operate(_crob_block(1))

        with caplog.at_level(logging.ERROR, logger=_LOGGER_NAME):
            outstation.process_request(request.to_bytes())  # t=0: logs
            for _ in range(5):
                fake_clock.advance(10.0)
                outstation.process_request(request.to_bytes())  # t=10,20,30,40,50: suppressed
            fake_clock.advance(10.0)  # t=60, 60 s after the first failure
            outstation.process_request(request.to_bytes())

        records = _records(caplog)
        assert len(records) == 2
        assert "5 suppressed" in records[1].getMessage()


class TestKeyIncludesAllThreeFields:
    """Replacing any one field of the key with a constant collapses two independent failures into one."""

    def test_varying_function_only_gives_independent_records(
        self, fake_clock: _FakeClock, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Same handler method (direct_operate_binary_output), same exception type, different function."""
        outstation = Outstation(handler=_RaisingBinaryHandler())

        with caplog.at_level(logging.ERROR, logger=_LOGGER_NAME):
            outstation.process_request(_direct_operate(_crob_block(1)).to_bytes())
            outstation.process_request(_direct_operate(_crob_block(1), no_ack=True).to_bytes())

        assert len(_records(caplog)) == 2

    def test_varying_handler_method_only_gives_independent_records(
        self, fake_clock: _FakeClock, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Same function (SELECT), same exception type, different handler method."""
        outstation = Outstation(handler=_RaisingBinaryHandler())
        outstation.database.add_analog_output(5)

        with caplog.at_level(logging.ERROR, logger=_LOGGER_NAME):
            outstation.process_request(_select(_crob_block(1), seq=1).to_bytes(), peer=MASTER_A)
            outstation.process_request(_select(_ao_block(5), seq=2).to_bytes(), peer=MASTER_A)

        assert len(_records(caplog)) == 2

    def test_varying_exception_type_only_gives_independent_records(
        self, fake_clock: _FakeClock, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Same function (DIRECT_OPERATE), same handler method, different exception type."""
        outstation = Outstation(handler=_ConfigurableRaisingHandler(RuntimeError))
        request = _direct_operate(_crob_block(1))

        with caplog.at_level(logging.ERROR, logger=_LOGGER_NAME):
            outstation.process_request(request.to_bytes())
            outstation.handler = _ConfigurableRaisingHandler(ValueError)
            outstation.process_request(request.to_bytes())

        assert len(_records(caplog)) == 2


class TestRevertingToAPlainLogSurvivesNoLonger:
    """A 50-failures-in-one-window test for each of the three remaining covered failure paths."""

    def test_fifty_invalid_returns_give_one_record_and_the_counter_reads_fifty(
        self, fake_clock: _FakeClock, caplog: pytest.LogCaptureFixture
    ) -> None:
        outstation = Outstation(handler=_InvalidReturnHandler(None))
        request = _direct_operate(_crob_block(1))

        with caplog.at_level(logging.ERROR, logger=_LOGGER_NAME):
            for _ in range(50):
                outstation.process_request(request.to_bytes())

        assert len(_records(caplog)) == 1
        assert outstation.handler_failures == 50

    def test_fifty_invalid_statuses_give_one_record_and_the_counter_reads_fifty(
        self, fake_clock: _FakeClock, caplog: pytest.LogCaptureFixture
    ) -> None:
        outstation = Outstation(handler=_InvalidReturnHandler(CommandResult(status=200)))  # type: ignore[arg-type]
        request = _direct_operate(_crob_block(1))

        with caplog.at_level(logging.ERROR, logger=_LOGGER_NAME):
            for _ in range(50):
                outstation.process_request(request.to_bytes())

        assert len(_records(caplog)) == 1
        assert outstation.handler_failures == 50

    def test_fifty_lookup_failures_give_one_record_and_the_counter_reads_fifty(
        self, fake_clock: _FakeClock, caplog: pytest.LogCaptureFixture
    ) -> None:
        db = _RaisingLookupDatabase()
        db.add_analog_output(5)
        outstation = Outstation(database=db, handler=_SucceedingHandler())
        request = _direct_operate(_ao_block(5))

        with caplog.at_level(logging.ERROR, logger=_LOGGER_NAME):
            for _ in range(50):
                outstation.process_request(request.to_bytes())

        assert len(_records(caplog)) == 1
        assert outstation.handler_failures == 50


class TestPeerAndFunctionOnEveryRecordKind:
    """Dropping the peer or the function name from any of these records survives otherwise."""

    def test_direct_operate_record_names_function_and_peer(
        self, fake_clock: _FakeClock, caplog: pytest.LogCaptureFixture
    ) -> None:
        outstation = Outstation(handler=_RaisingBinaryHandler())
        request = _direct_operate(_crob_block(1))

        with caplog.at_level(logging.ERROR, logger=_LOGGER_NAME):
            outstation.process_request(request.to_bytes(), peer=MASTER_A)

        message = _records(caplog)[0].getMessage()
        assert "DIRECT_OPERATE" in message
        assert "source=7" in message
        assert "connection=1" in message

    def test_no_ack_record_names_function_and_peer(
        self, fake_clock: _FakeClock, caplog: pytest.LogCaptureFixture
    ) -> None:
        outstation = Outstation(handler=_RaisingBinaryHandler())
        request = _direct_operate(_crob_block(1), no_ack=True)

        with caplog.at_level(logging.ERROR, logger=_LOGGER_NAME):
            outstation.process_request(request.to_bytes(), peer=MASTER_A)

        message = _records(caplog)[0].getMessage()
        assert "DIRECT_OPERATE_NO_ACK" in message
        assert "source=7" in message
        assert "connection=1" in message

    def test_tracking_lookup_record_names_function_and_peer(
        self, fake_clock: _FakeClock, caplog: pytest.LogCaptureFixture
    ) -> None:
        db = _RaisingLookupDatabase()
        db.add_analog_output(5)
        outstation = Outstation(database=db, handler=_SucceedingHandler())
        request = _direct_operate(_ao_block(5))

        with caplog.at_level(logging.ERROR, logger=_LOGGER_NAME):
            outstation.process_request(request.to_bytes(), peer=MASTER_A)

        message = _records(caplog)[0].getMessage()
        assert "DIRECT_OPERATE" in message
        assert "source=7" in message
        assert "connection=1" in message

    def test_tracking_update_record_names_function_and_peer(
        self, fake_clock: _FakeClock, caplog: pytest.LogCaptureFixture
    ) -> None:
        db = _RaisingUpdateDatabase()
        db.add_analog_output(5)
        outstation = Outstation(database=db, handler=_SucceedingHandler())
        request = _direct_operate(_ao_block(5))

        with caplog.at_level(logging.ERROR, logger=_LOGGER_NAME):
            outstation.process_request(request.to_bytes(), peer=MASTER_A)

        message = _records(caplog)[0].getMessage()
        assert "DIRECT_OPERATE" in message
        assert "source=7" in message
        assert "connection=1" in message

    def test_nan_refusal_record_names_function_and_peer(
        self, fake_clock: _FakeClock, caplog: pytest.LogCaptureFixture
    ) -> None:
        db = Database()
        db.add_analog_output(5, value=1.0)
        outstation = Outstation(database=db, handler=_SucceedingHandler())
        request = _direct_operate(_ao_float_block(5, float("nan")))

        with caplog.at_level(logging.WARNING, logger=_LOGGER_NAME):
            outstation.process_request(request.to_bytes(), peer=MASTER_A)

        warnings = [r for r in _records(caplog) if r.levelno == logging.WARNING]
        assert len(warnings) == 1
        message = warnings[0].getMessage()
        assert "DIRECT_OPERATE" in message
        assert "source=7" in message
        assert "connection=1" in message


class TestMultipleWindows:
    """A third window still logs; a mutant that only handles one window transition would not reach it."""

    def test_three_consecutive_windows_each_log_once(
        self, fake_clock: _FakeClock, caplog: pytest.LogCaptureFixture
    ) -> None:
        outstation = Outstation(handler=_RaisingBinaryHandler())
        request = _direct_operate(_crob_block(1))

        with caplog.at_level(logging.ERROR, logger=_LOGGER_NAME):
            outstation.process_request(request.to_bytes())  # window 1
            fake_clock.advance(WINDOW_SECONDS)
            outstation.process_request(request.to_bytes())  # window 2
            fake_clock.advance(WINDOW_SECONDS)
            outstation.process_request(request.to_bytes())  # window 3

        assert len(_records(caplog)) == 3
        assert outstation.handler_failures == 3


class TestLiteralSixtySecondWindow:
    """The window is exactly 60 seconds, asserted with literal numbers rather than the constant."""

    def test_window_seconds_is_sixty(self) -> None:
        assert WINDOW_SECONDS == 60.0

    def test_at_fifty_nine_seconds_still_suppressed_at_sixty_it_logs(
        self, fake_clock: _FakeClock, caplog: pytest.LogCaptureFixture
    ) -> None:
        outstation = Outstation(handler=_RaisingBinaryHandler())
        request = _direct_operate(_crob_block(1))

        with caplog.at_level(logging.ERROR, logger=_LOGGER_NAME):
            outstation.process_request(request.to_bytes())
            fake_clock.advance(59.0)
            outstation.process_request(request.to_bytes())
            fake_clock.advance(1.0)  # 59.0 + 1.0 = 60.0 elapsed, not the WINDOW_SECONDS name
            outstation.process_request(request.to_bytes())

        assert len(_records(caplog)) == 2

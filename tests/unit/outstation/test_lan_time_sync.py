"""Tests for RECORD_CURRENT_TIME and WRITE of g50v3 (LAN time sync, issue #142).

IEEE 1815-2012 10.3.3.2: RECORD_CURRENT_TIME (FC 24) records the receipt
instant [B]; a WRITE of g50v3 delivers the written time plus the elapsed time
from [B] to [C] (the instant the clock is set, step e) to the time hook, and
clears NEED_TIME in its own response (4.4.16.1 Rule 2, 10.3.3.2 f).
"""

import pytest

from dnp3.application.builder import build_write_request
from dnp3.application.fragment import ObjectBlock, RequestFragment, ResponseFragment
from dnp3.application.header import RequestHeader
from dnp3.application.qualifiers import ObjectHeader
from dnp3.core.enums import FunctionCode
from dnp3.core.flags import IIN
from dnp3.core.timestamp import DNP3Timestamp
from dnp3.outstation.outstation import Outstation

# 10.3.2 worked example: 2008-01-01T00:00:00.000 UTC, wire octets 00 C4 A5 32 17 01.
_TIME_MS = 1199145600000
_TIME_OCTETS = bytes.fromhex("00c4a5321701")


class _FakeClock:
    """A settable stand-in for time.monotonic, so elapsed time is exact in a test."""

    def __init__(self, start: float = 0.0) -> None:
        self.value = start

    def __call__(self) -> float:
        return self.value


def _record_current_time_request(seq: int = 0) -> RequestFragment:
    return RequestFragment(header=RequestHeader.build(function=FunctionCode.RECORD_CURRENT_TIME, seq=seq))


def _record_current_time(outstation: Outstation, seq: int = 0) -> ResponseFragment:
    responses = outstation.process_request(_record_current_time_request(seq).to_bytes())
    assert len(responses) == 1
    return responses[0]


def _g50v3(qualifier: int, data: bytes) -> ObjectBlock:
    return ObjectBlock(header=ObjectHeader(group=50, variation=3, qualifier=qualifier), data=data)


def _g50v3_write(qualifier: int = 0x07, count: int = 1, octets: bytes = _TIME_OCTETS) -> ObjectBlock:
    """A g50v3 block with a 1-byte count field followed by ``octets``."""
    return _g50v3(qualifier, bytes([count]) + octets)


def _write(outstation: Outstation, *objects: ObjectBlock, seq: int = 0) -> ResponseFragment:
    request = build_write_request(objects=objects, seq=seq)
    responses = outstation.process_request(request.to_bytes())
    assert len(responses) == 1
    return responses[0]


class TestRecordCurrentTime:
    """Item 1: RECORD_CURRENT_TIME answers null and records the receipt instant."""

    def test_returns_null_response_at_request_seq(self) -> None:
        outstation = Outstation()

        response = _record_current_time(outstation, seq=5)

        assert response.header.control.seq == 5
        assert response.header.function == FunctionCode.RESPONSE
        assert not response.objects
        assert not response.header.iin & (IIN.PARAMETER_ERROR | IIN.OBJECT_UNKNOWN | IIN.NO_FUNC_CODE_SUPPORT)

    def test_second_record_replaces_the_first(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """10.3.3.2: 'shall discard the original recorded time and save the
        newer time from the most recently received record current time
        message.' Proven by the elapsed time a later WRITE delivers: it must
        be measured from the second RECORD_CURRENT_TIME, not the first.
        """
        clock = _FakeClock(100.0)
        monkeypatch.setattr("dnp3.outstation.outstation.time.monotonic", clock)
        delivered: list[DNP3Timestamp] = []
        outstation = Outstation(time_handler=delivered.append)

        _record_current_time(outstation, seq=1)
        clock.value = 100.5  # a long gap the first instant would answer wrong
        _record_current_time(outstation, seq=2)
        clock.value = 100.625  # 125 ms after the SECOND record

        _write(outstation, _g50v3_write(), seq=3)

        assert delivered == [DNP3Timestamp(_TIME_MS + 125)]


class TestWriteG50v3Applies:
    """Item 2: a WRITE of g50v3 delivers written time plus elapsed time, clears NEED_TIME."""

    def test_delivers_written_time_plus_elapsed_and_clears_need_time(self, monkeypatch: pytest.MonkeyPatch) -> None:
        clock = _FakeClock(100.0)
        monkeypatch.setattr("dnp3.outstation.outstation.time.monotonic", clock)
        delivered: list[DNP3Timestamp] = []
        outstation = Outstation(time_handler=delivered.append)
        assert IIN.NEED_TIME in outstation.iin

        _record_current_time(outstation, seq=1)
        clock.value = 100.25  # 250 ms from [B] to [C], exact in binary float

        response = _write(outstation, _g50v3_write(), seq=2)

        # Tolerance is exact (0 ms): the clock is fully controlled by this test.
        assert delivered == [DNP3Timestamp(_TIME_MS + 250)]
        assert response.to_bytes() == bytes.fromhex("c2818000")
        assert not response.objects
        assert IIN.NEED_TIME not in outstation.iin

    def test_no_handler_still_clears_need_time(self, monkeypatch: pytest.MonkeyPatch) -> None:
        clock = _FakeClock(0.0)
        monkeypatch.setattr("dnp3.outstation.outstation.time.monotonic", clock)
        outstation = Outstation()

        _record_current_time(outstation, seq=1)
        response = _write(outstation, _g50v3_write(), seq=2)

        assert not response.header.iin & (IIN.PARAMETER_ERROR | IIN.OBJECT_UNKNOWN)
        assert IIN.NEED_TIME not in outstation.iin


class TestWriteG50v3Refused:
    """Item 3: a wrong qualifier or count, or no recorded instant, answers IIN2.2."""

    def test_wrong_qualifier_answers_parameter_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        clock = _FakeClock(50.0)
        monkeypatch.setattr("dnp3.outstation.outstation.time.monotonic", clock)
        delivered: list[DNP3Timestamp] = []
        outstation = Outstation(time_handler=delivered.append)
        _record_current_time(outstation, seq=1)

        block = _g50v3(0x08, (1).to_bytes(2, "little") + _TIME_OCTETS)
        response = _write(outstation, block, seq=2)

        assert delivered == []
        assert IIN.PARAMETER_ERROR in response.header.iin
        assert IIN.NEED_TIME in outstation.iin

    def test_wrong_count_answers_parameter_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        clock = _FakeClock(50.0)
        monkeypatch.setattr("dnp3.outstation.outstation.time.monotonic", clock)
        delivered: list[DNP3Timestamp] = []
        outstation = Outstation(time_handler=delivered.append)
        _record_current_time(outstation, seq=1)

        block = _g50v3_write(qualifier=0x07, count=2, octets=_TIME_OCTETS + _TIME_OCTETS)
        response = _write(outstation, block, seq=2)

        assert delivered == []
        assert IIN.PARAMETER_ERROR in response.header.iin
        assert IIN.NEED_TIME in outstation.iin

    def test_no_recorded_instant_answers_parameter_error_and_delivers_nothing(self) -> None:
        delivered: list[DNP3Timestamp] = []
        outstation = Outstation(time_handler=delivered.append)

        response = _write(outstation, _g50v3_write(), seq=2)

        assert delivered == []
        assert IIN.PARAMETER_ERROR in response.header.iin
        assert IIN.NEED_TIME in outstation.iin

    def test_successful_write_consumes_the_recorded_instant(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """D (build-time decision): a successful WRITE consumes the recorded
        instant. 10.3.3.2 describes one RECORD_CURRENT_TIME/WRITE pair per
        synchronization and 10.3.4.1 forbids retrying either message; a second
        WRITE against a stale instant would silently reuse a [B] that no
        longer corresponds to any pending exchange, so it is refused instead.
        """
        clock = _FakeClock(10.0)
        monkeypatch.setattr("dnp3.outstation.outstation.time.monotonic", clock)
        delivered: list[DNP3Timestamp] = []
        outstation = Outstation(time_handler=delivered.append)
        _record_current_time(outstation, seq=1)
        clock.value = 10.125
        _write(outstation, _g50v3_write(), seq=2)
        assert delivered == [DNP3Timestamp(_TIME_MS + 125)]

        delivered.clear()
        clock.value = 10.25
        response = _write(outstation, _g50v3_write(), seq=3)

        assert delivered == []
        assert IIN.PARAMETER_ERROR in response.header.iin

    def test_raising_handler_leaves_need_time_set_and_instant_unconsumed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The invariant that a raising handler applies nothing extends to the
        recorded instant: a later WRITE with a working handler still succeeds
        using the SAME instant this call never got to consume.
        """
        calls: list[DNP3Timestamp] = []

        def raise_once_then_record(timestamp: DNP3Timestamp) -> None:
            if not calls:
                calls.append(timestamp)
                msg = "handler refuses the time"
                raise ValueError(msg)
            calls.append(timestamp)

        clock = _FakeClock(5.0)
        monkeypatch.setattr("dnp3.outstation.outstation.time.monotonic", clock)
        outstation = Outstation(time_handler=raise_once_then_record)
        _record_current_time(outstation, seq=1)
        clock.value = 5.125

        request = build_write_request(objects=(_g50v3_write(),), seq=2)
        with pytest.raises(ValueError, match="handler refuses the time"):
            outstation.process_request(request.to_bytes())
        assert IIN.NEED_TIME in outstation.iin

        clock.value = 5.25
        response = _write(outstation, _g50v3_write(), seq=3)

        # Both calls used the instant recorded at seq=1: 125 ms and 250 ms.
        assert calls == [DNP3Timestamp(_TIME_MS + 125), DNP3Timestamp(_TIME_MS + 250)]
        assert IIN.NEED_TIME not in outstation.iin
        assert not response.header.iin & IIN.PARAMETER_ERROR


class TestWriteG50v3MalformedFrame:
    """A g50v3 block shorter than its declared width fails to frame before
    Rule W's check runs. The layout row this issue adds (A.23.3) makes that
    a known-width framing failure (PARAMETER_ERROR), not the OBJECT_UNKNOWN
    this outstation answered while g50v3 had no layout row (#140).
    """

    def test_truncated_g50v3_answers_parameter_error_not_object_unknown(self) -> None:
        outstation = Outstation()
        block = ObjectBlock(header=ObjectHeader(group=50, variation=3, qualifier=0x07), data=bytes([1]))

        response = _write(outstation, block, seq=6)

        assert IIN.PARAMETER_ERROR in response.header.iin
        assert IIN.OBJECT_UNKNOWN not in response.header.iin
        assert IIN.NEED_TIME in outstation.iin

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
from dnp3.core.timestamp import TIMESTAMP_SIZE, DNP3Timestamp
from dnp3.outstation.outstation import Outstation
from dnp3.outstation.peer import PeerId

# 10.3.2 worked example: 2008-01-01T00:00:00.000 UTC, wire octets 00 C4 A5 32 17 01.
_TIME_MS = 1199145600000
_TIME_OCTETS = bytes.fromhex("00c4a5321701")


class _FakeClock:
    """A settable stand-in for time.monotonic, so elapsed time is exact in a test."""

    def __init__(self, start: float = 0.0) -> None:
        self.value = start

    def __call__(self) -> float:
        return self.value


class _SteppingClock:
    """A time.monotonic stand-in that returns one value per call from a fixed
    sequence, and raises if called more times than the sequence provides.

    Proves how many times the code under test reads the clock: giving it
    exactly the values a correct single read needs, with no spare, turns an
    unwanted extra read into a loud failure instead of a silently wrong
    delivered time.
    """

    def __init__(self, *values: float) -> None:
        self._values = list(values)
        self._calls = 0

    def __call__(self) -> float:
        if self._calls >= len(self._values):
            msg = f"clock called {self._calls + 1} times; only {len(self._values)} values given"
            raise AssertionError(msg)
        value = self._values[self._calls]
        self._calls += 1
        return value


_PEER_A = PeerId(source=1, connection=1)
_PEER_B = PeerId(source=2, connection=2)

# Largest value a 48-bit DNP3Timestamp can hold without overflowing to_bytes.
_MAX_TIMESTAMP_MS = (1 << (TIMESTAMP_SIZE * 8)) - 1


def _record_current_time_request(seq: int = 0) -> RequestFragment:
    return RequestFragment(header=RequestHeader.build(function=FunctionCode.RECORD_CURRENT_TIME, seq=seq))


def _record_current_time(outstation: Outstation, seq: int = 0, *, peer: PeerId | None = None) -> ResponseFragment:
    responses = outstation.process_request(_record_current_time_request(seq).to_bytes(), peer=peer)
    assert len(responses) == 1
    return responses[0]


def _g50v3(qualifier: int, data: bytes) -> ObjectBlock:
    return ObjectBlock(header=ObjectHeader(group=50, variation=3, qualifier=qualifier), data=data)


def _g50v3_write(qualifier: int = 0x07, count: int = 1, octets: bytes = _TIME_OCTETS) -> ObjectBlock:
    """A g50v3 block with a 1-byte count field followed by ``octets``."""
    return _g50v3(qualifier, bytes([count]) + octets)


def _write(outstation: Outstation, *objects: ObjectBlock, seq: int = 0, peer: PeerId | None = None) -> ResponseFragment:
    request = build_write_request(objects=objects, seq=seq)
    responses = outstation.process_request(request.to_bytes(), peer=peer)
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
        # Pin the whole response, IIN bits included (NEED_TIME 0x10 |
        # DEVICE_RESTART 0x80 = 0x90, both set on a fresh Outstation).
        assert response.to_bytes() == bytes.fromhex("c5819000")

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


class TestRecordCurrentTimePerPeer:
    """The recorded instant is kept per peer (#142), so one master's
    RECORD_CURRENT_TIME never shifts or is consumed by another master's
    g50v3, and it does not outlive the peer's connection.
    """

    def test_another_peers_g50v3_cannot_consume_this_peers_instant(self, monkeypatch: pytest.MonkeyPatch) -> None:
        clock = _FakeClock(100.0)
        monkeypatch.setattr("dnp3.outstation.outstation.time.monotonic", clock)
        delivered: list[DNP3Timestamp] = []
        outstation = Outstation(time_handler=delivered.append)

        _record_current_time(outstation, seq=1, peer=_PEER_A)
        clock.value = 100.5

        response = _write(outstation, _g50v3_write(), seq=2, peer=_PEER_B)

        assert delivered == []
        assert IIN.PARAMETER_ERROR in response.header.iin
        assert IIN.NEED_TIME in outstation.iin

    def test_a_second_peers_record_does_not_shift_the_first_peers_write(self, monkeypatch: pytest.MonkeyPatch) -> None:
        clock = _FakeClock(100.0)
        monkeypatch.setattr("dnp3.outstation.outstation.time.monotonic", clock)
        delivered: list[DNP3Timestamp] = []
        outstation = Outstation(time_handler=delivered.append)

        _record_current_time(outstation, seq=1, peer=_PEER_A)
        clock.value = 100.5
        _record_current_time(outstation, seq=2, peer=_PEER_B)
        clock.value = 100.625

        _write(outstation, _g50v3_write(), seq=3, peer=_PEER_A)

        # 625 ms after peer A's own instant at 100.0; peer B's later instant
        # at 100.5 must not shift peer A's elapsed time.
        assert delivered == [DNP3Timestamp(_TIME_MS + 625)]

    def test_release_connection_drops_that_peers_instant(self, monkeypatch: pytest.MonkeyPatch) -> None:
        clock = _FakeClock(50.0)
        monkeypatch.setattr("dnp3.outstation.outstation.time.monotonic", clock)
        delivered: list[DNP3Timestamp] = []
        outstation = Outstation(time_handler=delivered.append)

        _record_current_time(outstation, seq=1, peer=_PEER_A)
        outstation.release_connection(1)  # _PEER_A.connection
        clock.value = 50.5

        response = _write(outstation, _g50v3_write(), seq=2, peer=_PEER_A)

        assert delivered == []
        assert IIN.PARAMETER_ERROR in response.header.iin


class TestWriteG50v3ConsumesOnlyItsOwnPeer:
    """A successful WRITE consumes only the writing peer's instant (#142);
    another peer's own instant is still usable afterward."""

    def test_a_second_peers_instant_stays_usable_after_this_peers_write(self, monkeypatch: pytest.MonkeyPatch) -> None:
        clock = _FakeClock(100.0)
        monkeypatch.setattr("dnp3.outstation.outstation.time.monotonic", clock)
        delivered: list[DNP3Timestamp] = []
        outstation = Outstation(time_handler=delivered.append)

        _record_current_time(outstation, seq=1, peer=_PEER_A)
        _record_current_time(outstation, seq=2, peer=_PEER_B)
        clock.value = 100.25
        _write(outstation, _g50v3_write(), seq=3, peer=_PEER_A)

        delivered.clear()
        clock.value = 100.5
        response = _write(outstation, _g50v3_write(), seq=4, peer=_PEER_B)

        assert delivered == [DNP3Timestamp(_TIME_MS + 500)]
        assert not response.header.iin & IIN.PARAMETER_ERROR


class TestWriteG50v3Bounded:
    """A written time plus elapsed time that would not fit the 48-bit
    timestamp is refused in the check pass (#142), before any handler call
    and before the sum is ever constructed."""

    def test_sum_over_48_bits_answers_parameter_error_and_delivers_nothing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        clock = _FakeClock(0.0)
        monkeypatch.setattr("dnp3.outstation.outstation.time.monotonic", clock)
        delivered: list[DNP3Timestamp] = []
        outstation = Outstation(time_handler=delivered.append)
        _record_current_time(outstation, seq=1)
        clock.value = 0.001  # 1 ms elapsed: pushes the sum 1 ms past the 48-bit width

        octets = DNP3Timestamp(_MAX_TIMESTAMP_MS).to_bytes()
        response = _write(outstation, _g50v3(0x07, bytes([1]) + octets), seq=2)

        assert delivered == []
        assert IIN.PARAMETER_ERROR in response.header.iin
        assert IIN.NEED_TIME in outstation.iin

    def test_sum_at_the_48_bit_boundary_is_accepted(self, monkeypatch: pytest.MonkeyPatch) -> None:
        clock = _FakeClock(0.0)
        monkeypatch.setattr("dnp3.outstation.outstation.time.monotonic", clock)
        delivered: list[DNP3Timestamp] = []
        outstation = Outstation(time_handler=delivered.append)
        _record_current_time(outstation, seq=1)
        # clock.value stays 0.0: 0 ms elapsed, so the sum lands exactly on the boundary.

        octets = DNP3Timestamp(_MAX_TIMESTAMP_MS).to_bytes()
        response = _write(outstation, _g50v3(0x07, bytes([1]) + octets), seq=2)

        assert delivered == [DNP3Timestamp(_MAX_TIMESTAMP_MS)]
        assert not response.header.iin & IIN.PARAMETER_ERROR


class TestWriteG50v3OneClockReadPerBlock:
    """A g50v3 WRITE reads the clock once per block and uses that one value
    for both the 48-bit check and the delivered time (#142 delta review): a
    second, later read could push a written time that passed the check over
    the 48-bit width before time_handler ever sees it."""

    def test_moving_clock_never_delivers_above_the_48_bit_maximum(self, monkeypatch: pytest.MonkeyPatch) -> None:
        clock = _SteppingClock(0.0, 0.0004, 0.0008)
        monkeypatch.setattr("dnp3.outstation.outstation.time.monotonic", clock)
        delivered: list[DNP3Timestamp] = []
        outstation = Outstation(time_handler=delivered.append)
        _record_current_time(outstation, seq=1)

        octets = DNP3Timestamp(_MAX_TIMESTAMP_MS).to_bytes()
        response = _write(outstation, _g50v3(0x07, bytes([1]) + octets), seq=2)

        if delivered:
            assert delivered == [DNP3Timestamp(_MAX_TIMESTAMP_MS)]
            assert not response.header.iin & IIN.PARAMETER_ERROR
        else:
            assert IIN.PARAMETER_ERROR in response.header.iin


class TestCallTimeHandlerG50v3FailsClosed:
    """The 'cannot happen' guard in _call_time_handler_g50v3 fails closed
    (#142). _write_block_check computes a delivered time for every g50v3
    block it passes, so reaching this method with none is a bug in that
    guarantee; it must raise rather than silently deliver nothing while the
    caller still clears NEED_TIME.
    """

    def test_raises_when_reached_with_no_delivered_time(self) -> None:
        delivered: list[DNP3Timestamp] = []
        outstation = Outstation(time_handler=delivered.append)

        with pytest.raises(RuntimeError, match="no delivered time"):
            outstation._call_time_handler_g50v3(None)

        assert delivered == []


class TestWriteG50v3RefusalKeepsInstant:
    """A refused g50v3 does not consume the recorded instant (#142); a
    following good WRITE still uses it."""

    def test_good_write_after_a_refused_write_uses_the_kept_instant(self, monkeypatch: pytest.MonkeyPatch) -> None:
        clock = _FakeClock(50.0)
        monkeypatch.setattr("dnp3.outstation.outstation.time.monotonic", clock)
        delivered: list[DNP3Timestamp] = []
        outstation = Outstation(time_handler=delivered.append)
        _record_current_time(outstation, seq=1)

        clock.value = 50.1
        bad_qualifier_block = _g50v3(0x08, (1).to_bytes(2, "little") + _TIME_OCTETS)
        refusal = _write(outstation, bad_qualifier_block, seq=2)
        assert IIN.PARAMETER_ERROR in refusal.header.iin
        assert delivered == []

        clock.value = 50.35  # 350 ms after the ORIGINAL instant at 50.0, not the refusal
        response = _write(outstation, _g50v3_write(), seq=3)

        assert delivered == [DNP3Timestamp(_TIME_MS + 350)]
        assert not response.header.iin & IIN.PARAMETER_ERROR


class TestWriteG50v3FractionalElapsed:
    """A fractional elapsed time is rounded to the nearest millisecond,
    not truncated (#142)."""

    def test_fractional_elapsed_milliseconds_round_to_nearest(self, monkeypatch: pytest.MonkeyPatch) -> None:
        clock = _FakeClock(0.0)
        monkeypatch.setattr("dnp3.outstation.outstation.time.monotonic", clock)
        delivered: list[DNP3Timestamp] = []
        outstation = Outstation(time_handler=delivered.append)
        _record_current_time(outstation, seq=1)
        clock.value = 0.1236  # 123.6 ms: round() gives 124, a truncating int() would give 123

        _write(outstation, _g50v3_write(), seq=2)

        assert delivered == [DNP3Timestamp(_TIME_MS + 124)]

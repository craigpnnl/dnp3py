"""Tests for WRITE of g50v1 (time) and the g80v1 NEED_TIME bit (issue #140).

IEEE 1815-2012 4.5.5 and 10.3.3.1: NEED_TIME clears only on an applied time
write or a WRITE of g80v1 index 4 = 0; DELAY_MEASURE never clears it. Rule W
(4.4.4.3 Rule 7): every WRITE block is checked before any is applied.
"""

import pytest

from dnp3.application.builder import build_write_request
from dnp3.application.fragment import ObjectBlock, ResponseFragment
from dnp3.application.qualifiers import ObjectHeader
from dnp3.core.flags import IIN
from dnp3.core.timestamp import DNP3Timestamp
from dnp3.outstation.outstation import Outstation

# 10.3.2 worked example: 2008-01-01T00:00:00.000 UTC, wire octets 00 C4 A5 32 17 01.
_TIME_MS = 1199145600000
_TIME_OCTETS = bytes.fromhex("00c4a5321701")


def _g50v1(qualifier: int, data: bytes) -> ObjectBlock:
    return ObjectBlock(header=ObjectHeader(group=50, variation=1, qualifier=qualifier), data=data)


def _g50v1_write(qualifier: int = 0x07, count: int = 1, octets: bytes = _TIME_OCTETS) -> ObjectBlock:
    """A g50v1 block with a 1-byte count field followed by ``octets``."""
    return _g50v1(qualifier, bytes([count]) + octets)


def _g80v1(qualifier: int, data: bytes) -> ObjectBlock:
    return ObjectBlock(header=ObjectHeader(group=80, variation=1, qualifier=qualifier), data=data)


def _send(outstation: Outstation, *objects: ObjectBlock, seq: int = 0) -> ResponseFragment:
    request = build_write_request(objects=objects, seq=seq)
    responses = outstation.process_request(request.to_bytes())
    assert len(responses) == 1
    return responses[0]


class TestWriteTimeApplies:
    """Item 1: a well-formed g50v1 WRITE delivers the time and clears NEED_TIME."""

    def test_write_time_delivers_value_and_clears_need_time(self) -> None:
        delivered: list[DNP3Timestamp] = []
        outstation = Outstation(time_handler=delivered.append)
        assert IIN.NEED_TIME in outstation.iin

        response = _send(outstation, _g50v1_write(), seq=3)

        assert delivered == [DNP3Timestamp(_TIME_MS)]
        assert response.to_bytes() == bytes.fromhex("c3818000")
        assert not response.objects
        assert IIN.NEED_TIME not in outstation.iin


class TestWriteTimeNoHandler:
    """Item 2: with no time_handler, the write still clears NEED_TIME and answers null."""

    def test_write_time_with_no_handler_still_clears_need_time(self) -> None:
        outstation = Outstation()
        assert IIN.NEED_TIME in outstation.iin

        response = _send(outstation, _g50v1_write(), seq=3)

        assert response.to_bytes() == bytes.fromhex("c3818000")
        assert not response.header.iin & (IIN.PARAMETER_ERROR | IIN.OBJECT_UNKNOWN)
        assert IIN.NEED_TIME not in outstation.iin


class TestWriteTimeMalformedQualifier:
    """Item 3: a qualifier or count A.23.1.2.3 does not fix answers IIN2.2 unapplied."""

    def test_qualifier_0x08_answers_parameter_error(self) -> None:
        delivered: list[DNP3Timestamp] = []
        outstation = Outstation(time_handler=delivered.append)

        block = _g50v1(0x08, (1).to_bytes(2, "little") + _TIME_OCTETS)
        response = _send(outstation, block, seq=5)

        assert delivered == []
        assert IIN.PARAMETER_ERROR in response.header.iin
        assert IIN.NEED_TIME in outstation.iin

    def test_qualifier_0x07_count_2_answers_parameter_error(self) -> None:
        delivered: list[DNP3Timestamp] = []
        outstation = Outstation(time_handler=delivered.append)

        block = _g50v1_write(qualifier=0x07, count=2, octets=_TIME_OCTETS + _TIME_OCTETS)
        response = _send(outstation, block, seq=5)

        assert delivered == []
        assert IIN.PARAMETER_ERROR in response.header.iin
        assert IIN.NEED_TIME in outstation.iin

    def test_qualifier_0x17_indexed_answers_parameter_error(self) -> None:
        delivered: list[DNP3Timestamp] = []
        outstation = Outstation(time_handler=delivered.append)

        block = _g50v1(0x17, bytes([1, 0]) + _TIME_OCTETS)
        response = _send(outstation, block, seq=5)

        assert delivered == []
        assert IIN.PARAMETER_ERROR in response.header.iin
        assert IIN.NEED_TIME in outstation.iin


class TestWriteTimeUnknownWidthVariations:
    """Item 4: g50v2/v3/v0 stop at framing (pins today's refusal) with IIN2.1."""

    def test_g50v2_answers_object_unknown(self) -> None:
        outstation = Outstation()
        block = ObjectBlock(header=ObjectHeader(group=50, variation=2, qualifier=0x07), data=bytes([1]))
        response = _send(outstation, block, seq=6)

        assert IIN.OBJECT_UNKNOWN in response.header.iin
        assert IIN.PARAMETER_ERROR not in response.header.iin
        assert IIN.NEED_TIME in outstation.iin

    def test_g50v3_answers_object_unknown(self) -> None:
        outstation = Outstation()
        block = ObjectBlock(header=ObjectHeader(group=50, variation=3, qualifier=0x07), data=bytes([1]))
        response = _send(outstation, block, seq=6)

        assert IIN.OBJECT_UNKNOWN in response.header.iin
        assert IIN.NEED_TIME in outstation.iin

    def test_g50v0_answers_object_unknown(self) -> None:
        outstation = Outstation()
        block = ObjectBlock(header=ObjectHeader(group=50, variation=0, qualifier=0x07), data=bytes([1]))
        response = _send(outstation, block, seq=6)

        assert IIN.OBJECT_UNKNOWN in response.header.iin
        assert IIN.NEED_TIME in outstation.iin


class TestWriteG80v1IndexFour:
    """Item 6: WRITE of g80v1 index 4 clears NEED_TIME per 4.5.5; index 7 is unaffected."""

    def test_index_4_written_0_clears_need_time_only(self) -> None:
        outstation = Outstation()
        assert IIN.NEED_TIME in outstation.iin
        assert IIN.DEVICE_RESTART in outstation.iin

        response = _send(outstation, _g80v1(0x00, bytes([4, 4, 0x00])), seq=1)

        assert IIN.NEED_TIME not in outstation.iin
        assert IIN.DEVICE_RESTART in outstation.iin
        assert IIN.PARAMETER_ERROR not in response.header.iin

    def test_index_4_written_1_is_a_no_op(self) -> None:
        outstation = Outstation()

        _send(outstation, _g80v1(0x00, bytes([4, 4, 0x01])), seq=1)

        assert IIN.NEED_TIME in outstation.iin

    def test_index_4_to_7_written_0_clears_both_bits(self) -> None:
        outstation = Outstation()

        _send(outstation, _g80v1(0x00, bytes([4, 7, 0x00])), seq=1)

        assert IIN.NEED_TIME not in outstation.iin
        assert IIN.DEVICE_RESTART not in outstation.iin


class TestRuleWAllOrNothing:
    """Item 7: any failing block in a WRITE applies none of the request's blocks."""

    def test_good_g50v1_with_bad_g80v1_qualifier_applies_neither(self) -> None:
        delivered: list[DNP3Timestamp] = []
        outstation = Outstation(time_handler=delivered.append)

        # qualifier 0x01 (2-byte start-stop), start=stop=4, one bit of data:
        # frames fine (unlike an out-of-order range), so this exercises
        # _write_block_error's qualifier check rather than framing refusal.
        response = _send(
            outstation,
            _g50v1_write(),
            _g80v1(0x01, bytes([4, 0, 4, 0, 0x00])),
            seq=8,
        )

        assert delivered == []
        assert IIN.PARAMETER_ERROR in response.header.iin
        assert IIN.NEED_TIME in outstation.iin
        assert IIN.DEVICE_RESTART in outstation.iin

    def test_good_g80v1_clear_restart_with_bad_g50v1_qualifier_applies_neither(self) -> None:
        outstation = Outstation()

        response = _send(
            outstation,
            _g80v1(0x00, bytes([7, 7, 0x00])),
            _g50v1(0x08, (1).to_bytes(2, "little") + _TIME_OCTETS),
            seq=9,
        )

        assert IIN.PARAMETER_ERROR in response.header.iin
        assert IIN.DEVICE_RESTART in outstation.iin
        assert IIN.NEED_TIME in outstation.iin


class TestRuleWFirstFailingBlockWins:
    """Item 8: the IIN of the first failing block is answered, not a later one's."""

    def test_unwritable_object_before_malformed_time_answers_object_unknown_only(self) -> None:
        outstation = Outstation()
        # g30v1 (analog input, flags(1) + 4-byte value): range(start=0, stop=0,
        # 2 bytes) + one object (5 bytes) = 7 bytes, so this frames cleanly.
        g30v1 = ObjectBlock(header=ObjectHeader(group=30, variation=1, qualifier=0x00), data=bytes(7))

        response = _send(
            outstation,
            g30v1,
            _g50v1(0x08, (1).to_bytes(2, "little") + _TIME_OCTETS),
            seq=10,
        )

        assert IIN.OBJECT_UNKNOWN in response.header.iin
        assert IIN.PARAMETER_ERROR not in response.header.iin


class TestRuleWBothValid:
    """Item 9: two valid blocks both apply, in wire order."""

    def test_time_write_and_clear_restart_both_apply(self) -> None:
        delivered: list[DNP3Timestamp] = []
        outstation = Outstation(time_handler=delivered.append)

        response = _send(
            outstation,
            _g50v1_write(),
            _g80v1(0x00, bytes([7, 7, 0x00])),
            seq=11,
        )

        assert delivered == [DNP3Timestamp(_TIME_MS)]
        assert IIN.NEED_TIME not in outstation.iin
        assert IIN.DEVICE_RESTART not in outstation.iin
        assert not response.header.iin & (IIN.NEED_TIME | IIN.DEVICE_RESTART)


class TestWriteTimeHandlerRaises:
    """Item 10: a raising time_handler propagates, and NEED_TIME stays set."""

    def test_raising_handler_propagates_and_leaves_need_time_set(self) -> None:
        def raiser(_timestamp: DNP3Timestamp) -> None:
            msg = "handler refuses the time"
            raise ValueError(msg)

        outstation = Outstation(time_handler=raiser)
        request = build_write_request(objects=(_g50v1_write(),), seq=12)

        with pytest.raises(ValueError, match="handler refuses the time"):
            outstation.process_request(request.to_bytes())

        assert IIN.NEED_TIME in outstation.iin

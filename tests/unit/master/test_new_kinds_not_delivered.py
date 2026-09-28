"""New point kinds from Annex A groups 3, 4, 13, 31, 33, 34, 41 and 43 are
framed but never delivered, end to end through ``Master.process_response``.

None of these kinds has an entry in master.py's delivery table, so adding
their layout rows must not make the master start decoding or delivering
values for them (IEEE 1815-2012 Annex A defines their wire shape; delivery
is a separate, later step). One representative pair per new kind, built with
``struct`` from its own clause rather than the library's own encoder.
"""

import struct

import pytest

from dnp3.master.handler import AnalogValue
from dnp3.master.master import Master
from dnp3.objects.layout import layout_for
from tests.unit.master.delivery import RecordingHandler

# Response header: app control (FIR+FIN, seq 1), RESPONSE function, 2-byte IIN.
RESPONSE_HEADER = bytes([0xC1, 0x81, 0x00, 0x00])

# Qualifier 0x00: 1-octet start and stop indices (one point, index 0).
RANGE_8 = 0x00


def _range_header(group: int, variation: int) -> bytes:
    return bytes([group, variation, RANGE_8, 0, 0])


class TestNewKindsNotDelivered:
    """A block of a newly-framed kind reaches the master and delivers nothing."""

    @pytest.mark.parametrize(
        ("group", "variation", "data"),
        [
            # A.4.2: flag octet, UINT2 state (g3v2, DOUBLE_BIT_INPUT).
            (3, 2, bytes([0x81])),
            # A.9.1: UINT7 status, BSTR1 commanded state (g13v1, BINARY_COMMAND_EVENT).
            (13, 1, bytes([0x00])),
            # A.15.1: flag octet, INT32 (g31v1, FROZEN_ANALOG_INPUT).
            (31, 1, bytes([0x01]) + struct.pack("<i", 12345)),
            # A.18.1: UINT16 deadband, no flags (g34v1, ANALOG_DEADBAND).
            (34, 1, struct.pack("<H", 100)),
            # A.20.1: INT32 requested value, control status octet (g41v1, ANALOG_COMMAND).
            (41, 1, struct.pack("<i", 500) + bytes([0x00])),
            # A.22.1: UINT7 status, BSTR1 reserved, INT32 (g43v1, ANALOG_COMMAND_EVENT).
            (43, 1, bytes([0x00]) + struct.pack("<i", 500)),
        ],
        ids=["g3v2", "g13v1", "g31v1", "g34v1", "g41v1", "g43v1"],
    )
    def test_new_kind_block_delivers_nothing(self, group: int, variation: int, data: bytes) -> None:
        # The pair is framed (a real layout, not an unknown group) yet still not delivered.
        assert layout_for(group, variation) is not None

        handler = RecordingHandler()
        master = Master(handler=handler)
        body = _range_header(group, variation) + data

        info = master.process_response(RESPONSE_HEADER + body)

        assert info is not None
        assert handler.calls == []

    def test_new_kind_block_does_not_disturb_an_earlier_delivered_block(self) -> None:
        """A g30v1 block ahead of a g31v1 block still delivers its analog value."""
        handler = RecordingHandler()
        master = Master(handler=handler)
        body = (
            _range_header(30, 1)
            + bytes([0x01])
            + struct.pack("<i", 2401)
            + _range_header(31, 1)
            + bytes([0x01])
            + struct.pack("<i", 12345)
        )

        info = master.process_response(RESPONSE_HEADER + body)

        assert info is not None
        assert handler.calls == [("on_analog_input", [AnalogValue(index=0, value=2401.0, quality=0x01)])]

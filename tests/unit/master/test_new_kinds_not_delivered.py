"""New point kinds from Annex A groups 13, 31, 33, 34, 41 and 43 are
framed by the wire-level parser, but never reach a decode function or a
handler callback, end to end through ``Master.process_response``: master.py
only batches and decodes a kind with an entry in its delivery table
(``_DELIVERIES``), and none of these new kinds has one. IEEE 1815-2012 Annex A
defines their wire shape; delivery is a separate, later step. One
representative pair per new kind, built with ``struct`` from its own clause
rather than the library's own encoder.
"""

import struct

import pytest

from dnp3.master.handler import AnalogValue
from dnp3.master.master import _DELIVERIES, Master
from dnp3.objects.layout import PointKind, layout_for
from tests.unit.master.delivery import RecordingHandler

# Response header: app control (FIR+FIN, seq 1), RESPONSE function, 2-byte IIN.
RESPONSE_HEADER = bytes([0xC1, 0x81, 0x00, 0x00])

# Qualifier 0x00: 1-octet start and stop indices (one point, index 0).
RANGE_8 = 0x00

# One representative pair per new point kind, with a minimal valid object.
NEW_KIND_BLOCKS = [
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
    # A.33.2: BSTR4 characteristics octet, no flags (g86v2, DATA_SET_CHARACTERISTICS).
    (86, 2, bytes([0x00])),
    # A.39.1: BCD4, 4 digits, 2 octets, no flags (g101v1, BCD_INTEGER).
    (101, 1, bytes([0x34, 0x12])),
    # A.40.1: UINT8 value alone, no flags (g102v1, UNSIGNED_INTEGER).
    (102, 1, bytes([0x05])),
    # A.45.3: UINT32 CSQ, UINT16 user number, no flags (g120v3, AUTHENTICATION).
    (120, 3, struct.pack("<IH", 123456, 7)),
    # A.46.1: flag octet, UINT16 association ID, UINT32 count (g121v1, SECURITY_STATISTIC).
    (121, 1, bytes([0x01]) + struct.pack("<HI", 3, 42)),
    # A.41.1: OSTR1, 1 octet of value, no flags (g110v1, OCTET_STRING).
    (110, 1, bytes([0xAB])),
    # A.42.1: OSTR3, 3 octets of value, no flags (g111v3, OCTET_STRING).
    (111, 3, bytes([0x01, 0x02, 0x03])),
]
NEW_KIND_IDS = [
    "g13v1",
    "g31v1",
    "g34v1",
    "g41v1",
    "g43v1",
    "g86v2",
    "g101v1",
    "g102v1",
    "g120v3",
    "g121v1",
    "g110v1",
    "g111v3",
]

# A.14.1: flag octet, INT32 (g30v1, ANALOG_INPUT): the delivered marker block.
G30V1_DATA = bytes([0x01]) + struct.pack("<i", 2401)
G30V1_EXPECTED = AnalogValue(index=0, value=2401.0, quality=0x01)

# Point kinds the rows above use; master.py delivers none of them.
UNDELIVERED_NEW_KINDS = frozenset(
    {
        PointKind.BINARY_COMMAND_EVENT,
        PointKind.ANALOG_COMMAND,
        PointKind.ANALOG_COMMAND_EVENT,
        PointKind.FROZEN_ANALOG_INPUT,
        PointKind.ANALOG_DEADBAND,
        PointKind.DATA_SET_CHARACTERISTICS,
        PointKind.BCD_INTEGER,
        PointKind.UNSIGNED_INTEGER,
        PointKind.AUTHENTICATION,
        PointKind.SECURITY_STATISTIC,
        PointKind.OCTET_STRING,
    }
)


def _range_header(group: int, variation: int) -> bytes:
    return bytes([group, variation, RANGE_8, 0, 0])


class TestNewKindsNotDelivered:
    """A block of a newly-framed kind reaches the master and delivers nothing."""

    @pytest.mark.parametrize(("group", "variation", "data"), NEW_KIND_BLOCKS, ids=NEW_KIND_IDS)
    def test_new_kind_block_delivers_nothing(self, group: int, variation: int, data: bytes) -> None:
        # The pair is framed: the parser sizes it from its own layout row,
        # the same as any registered group, rather than absorbing the rest
        # of the fragment as an unknown width. It still delivers nothing.
        assert layout_for(group, variation) is not None

        handler = RecordingHandler()
        master = Master(handler=handler)
        body = _range_header(group, variation) + data

        info = master.process_response(RESPONSE_HEADER + body)

        assert info is not None
        assert handler.calls == []

    @pytest.mark.parametrize(("group", "variation", "data"), NEW_KIND_BLOCKS, ids=NEW_KIND_IDS)
    def test_new_kind_block_ahead_of_a_delivered_block_does_not_swallow_it(
        self, group: int, variation: int, data: bytes
    ) -> None:
        """A new-kind block, correctly sized from its own layout row, must not
        cost the g30v1 block that follows it: that is what an unsized block
        absorbing the rest of the fragment would do instead.
        """
        handler = RecordingHandler()
        master = Master(handler=handler)
        body = _range_header(group, variation) + data + _range_header(30, 1) + G30V1_DATA

        info = master.process_response(RESPONSE_HEADER + body)

        assert info is not None
        assert handler.calls == [("on_analog_input", [G30V1_EXPECTED])]

    def test_none_of_the_new_kinds_has_a_delivery_entry(self) -> None:
        """Pins the delivery table's keys directly, not one sample value per
        kind: a row whose codec happens to decode to nothing on its own (g34v1
        is UINT, which `_decode_analog` never handles) must not hide a kind
        that has wrongly gained a callback under a different, decodable codec.
        """
        assert UNDELIVERED_NEW_KINDS.isdisjoint(_DELIVERIES)

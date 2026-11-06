"""Command echoes reach the master as statuses, per IEEE 1815-2012 4.4.4.2.

An outstation answers SELECT, OPERATE and DIRECT_OPERATE by echoing each control
object (g12v1, g41v1 to v4) with its control status octet set (A.8.1.2.3,
A.20.x). The master decodes those into ``CommandResponse`` values, records them
on ``ResponseInfo.command_responses`` for the caller holding the response, and
hands them to a handler that implements ``on_command_response``. Echo bytes are
built with ``struct`` from the clauses, not with the library's own encoder.
"""

import struct

import pytest

from dnp3.core.enums import CommandStatus
from dnp3.master.handler import (
    CommandResponse,
    CommandResponseHandler,
    DefaultSOEHandler,
    ResponseInfo,
)
from dnp3.master.master import _DELIVERIES, Master
from dnp3.objects.layout import PointKind
from tests.unit.master.delivery import RecordingHandler

# Response header: app control (FIR+FIN, seq 1), RESPONSE function, 2-byte IIN.
RESPONSE_HEADER = bytes([0xC1, 0x81, 0x00, 0x00])

# Qualifiers for prefixed records: 1-byte count with 1-byte index, 2-byte count with 2-byte index.
PREFIX_1 = 0x17
PREFIX_2 = 0x28

LATCH_ON = 0x03


def crob_record(status: int, *, code: int = LATCH_ON, count: int = 1, on_time: int = 0, off_time: int = 0) -> bytes:
    """A.8.1: control code, count, on-time, off-time, status."""
    return bytes([code, count]) + struct.pack("<II", on_time, off_time) + bytes([status])


def analog_record(variation: int, value: float, status: int) -> bytes:
    """A.20.1 to A.20.4: the requested value in the variation's encoding, then the status."""
    fmt = {1: "<i", 2: "<h", 3: "<f", 4: "<d"}[variation]
    return struct.pack(fmt, value) + bytes([status])


def block(group: int, variation: int, records: list[tuple[int, bytes]], *, prefix: int = PREFIX_1) -> bytes:
    """One object block with count-prefixed records at the given indexes."""
    if prefix == PREFIX_1:
        header = bytes([group, variation, prefix, len(records)])
        body = b"".join(bytes([index]) + record for index, record in records)
    else:
        header = bytes([group, variation, prefix]) + struct.pack("<H", len(records))
        body = b"".join(struct.pack("<H", index) + record for index, record in records)
    return header + body


def process(*blocks: bytes) -> tuple[ResponseInfo, RecordingHandler]:
    handler = RecordingHandler()
    info = Master(handler=handler).process_response(RESPONSE_HEADER + b"".join(blocks))
    assert info is not None
    return info, handler


class TestDecode:
    """Echo records become CommandResponse values on the response info."""

    def test_crob_echo_is_decoded_with_its_group_and_index(self) -> None:
        info, _ = process(block(12, 1, [(5, crob_record(CommandStatus.SUCCESS))]))

        assert info.command_responses == [CommandResponse(index=5, status=CommandStatus.SUCCESS, group=12)]
        assert info.command_responses[0].is_success

    @pytest.mark.parametrize("variation", [1, 2, 3, 4])
    def test_every_analog_command_variation_is_decoded(self, variation: int) -> None:
        info, _ = process(block(41, variation, [(9, analog_record(variation, 7, CommandStatus.NOT_SUPPORTED))]))

        assert info.command_responses == [CommandResponse(index=9, status=CommandStatus.NOT_SUPPORTED, group=41)]

    def test_two_byte_index_prefix(self) -> None:
        info, _ = process(block(12, 1, [(300, crob_record(CommandStatus.TIMEOUT))], prefix=PREFIX_2))

        assert [(r.index, r.status) for r in info.command_responses] == [(300, CommandStatus.TIMEOUT)]

    def test_several_records_keep_fragment_order(self) -> None:
        info, _ = process(
            block(12, 1, [(2, crob_record(CommandStatus.SUCCESS)), (1, crob_record(CommandStatus.LOCAL))]),
            block(41, 3, [(2, analog_record(3, 1.5, CommandStatus.SUCCESS))]),
        )

        assert [(r.group, r.index, r.status) for r in info.command_responses] == [
            (12, 2, CommandStatus.SUCCESS),
            (12, 1, CommandStatus.LOCAL),
            (41, 2, CommandStatus.SUCCESS),
        ]

    def test_reserved_high_bit_of_the_status_octet_is_ignored(self) -> None:
        """A.8.1.2.3: the status is seven bits; bit 7 is reserved."""
        info, _ = process(block(12, 1, [(0, crob_record(0x80 | CommandStatus.FORMAT_ERROR))]))

        assert info.command_responses[0].status is CommandStatus.FORMAT_ERROR

    def test_undefined_status_code_is_reported_as_undefined(self) -> None:
        info, _ = process(block(41, 1, [(0, analog_record(1, 0, 100))]))

        assert info.command_responses[0].status is CommandStatus.UNDEFINED

    def test_response_without_echoes_has_no_command_responses(self) -> None:
        # A.14.1 analog input, flag octet and INT32: a read, not a command echo.
        info, handler = process(bytes([30, 1, 0x00, 0, 0, 0x01]) + struct.pack("<i", 2401))

        assert info.command_responses == []
        assert [name for name, _ in handler.calls] == ["on_analog_input"]

    def test_short_block_delivers_nothing(self) -> None:
        """An object header carries no length (4.2.2.7); a truncated record is not known to be real."""
        info, _ = process(bytes([12, 1, PREFIX_1, 1, 0]) + crob_record(CommandStatus.SUCCESS)[:-3])

        assert info.command_responses == []


class TestDelivery:
    """Statuses reach a handler with on_command_response and no other."""

    def test_command_kinds_have_delivery_entries(self) -> None:
        assert {PointKind.BINARY_COMMAND, PointKind.ANALOG_COMMAND} <= set(_DELIVERIES)

    def test_default_handler_records_statuses_by_group_and_index(self) -> None:
        handler = DefaultSOEHandler()
        assert isinstance(handler, CommandResponseHandler)
        master = Master(handler=handler)

        info = master.process_response(
            RESPONSE_HEADER
            + block(12, 1, [(0, crob_record(CommandStatus.SUCCESS))])
            + block(41, 1, [(0, analog_record(1, 3, CommandStatus.OUT_OF_RANGE))])
        )

        assert info is not None
        assert handler.get_command_response(12, 0) == CommandResponse(0, CommandStatus.SUCCESS, group=12)
        assert handler.get_command_response(41, 0) == CommandResponse(0, CommandStatus.OUT_OF_RANGE, group=41)
        assert set(handler.command_responses) == {(12, 0), (41, 0)}
        assert handler.last_response is info
        handler.clear()
        assert handler.command_responses == {} and handler.get_command_response(12, 0) is None

    def test_handler_without_the_callback_gets_nothing_but_info_is_still_filled(self) -> None:
        info, handler = process(block(12, 1, [(0, crob_record(CommandStatus.SUCCESS))]))

        assert not isinstance(handler, CommandResponseHandler)
        assert handler.calls == []
        assert len(info.command_responses) == 1

    def test_runs_follow_the_kind_rule(self) -> None:
        """Consecutive blocks of one kind share a callback; a block of another kind ends the run.

        CROB and analog command echoes are different kinds, so a g12 run ends at a g41 block
        even though both are command echoes, the same as for any other pair of kinds.
        """
        calls: list[tuple[str, int]] = []

        class Handler(DefaultSOEHandler):
            def on_command_response(self, values: list[CommandResponse], info: ResponseInfo) -> None:
                calls.append(("command", len(values)))
                super().on_command_response(values, info)

            def on_analog_input(self, values: list, info: ResponseInfo) -> None:
                calls.append(("analog", len(values)))

        Master(handler=Handler()).process_response(
            RESPONSE_HEADER
            + block(12, 1, [(0, crob_record(0)), (1, crob_record(0))])
            + block(41, 1, [(0, analog_record(1, 1, 0))])
            + bytes([30, 1, 0x00, 0, 0, 0x01])
            + struct.pack("<i", 2401)
            + block(12, 1, [(2, crob_record(0))])
        )

        assert calls == [("command", 2), ("command", 1), ("analog", 1), ("command", 1)]

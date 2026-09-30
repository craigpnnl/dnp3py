"""Every request object block reaches the outstation on its own, or the request runs nothing.

Request octets are built from IEEE 1815-2012 Annex A rather than this library's encoders.
An object header carries no length (4.2.2.7), so a block that cannot be framed leaves
every later boundary unknown: the outstation executes nothing from that request and
answers a null response with IIN2.1 for an object of unknown width and IIN2.2 otherwise.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest

from dnp3.application.fragment import ResponseFragment, TruncationReason
from dnp3.application.parser import parse_request
from dnp3.core.enums import CommandStatus, ControlCode, FunctionCode
from dnp3.core.flags import IIN
from dnp3.outstation import Outstation
from dnp3.outstation.config import OutstationConfig
from dnp3.outstation.handler import CommandResult, DefaultCommandHandler
from dnp3.outstation.outstation import _NO_ACK_FUNCTIONS
from dnp3.outstation.peer import PeerId

MASTER_A = PeerId(source=3, connection=1)
MASTER_B = PeerId(source=9, connection=2)

# g12v1 (A.8.1), qualifier 0x17: control code LATCH_ON, count 1, on-time, off-time, status.
_CROB_BODY = bytes.fromhex("03 01 00000000 00000000 00")


def _crob(index: int, count: int = 1) -> bytes:
    return bytes([0x0C, 0x01, 0x17, count, index]) + _CROB_BODY


# g12v2 has no width this outstation knows (Table 4-14 names it as an unknown object).
_G12V2 = bytes([0x0C, 0x02, 0x17, 0x01, 0x02]) + _CROB_BODY
# g41v1 (A.20.1: INT32, status), index 4, value 1000.
_G41V1 = bytes.fromhex("29 01 17 01 04 E8030000 00")
# g41v2 (A.20.2: INT16, status), index 3, value 100.
_G41V2 = bytes.fromhex("29 02 17 01 03 6400 00")
# g41v4 (A.20.4: FLT64, status), index 5, value 0.5.
_G41V4 = bytes.fromhex("29 04 17 01 05 000000000000E03F 00")
# g80v1 (A.28.1), start-stop 7..7, bit 7 (DEVICE_RESTART) written 0.
_G80V1_CLEAR_RESTART = bytes.fromhex("50 01 00 07 07 00")
# g50v1 (A.23.1: DNP3TIME), count 1.
_G50V1 = bytes.fromhex("32 01 07 01 00E8764801 00")
# g50v2 (A.23.2: DNP3TIME, UINT32 interval), count 1: no layout row, so it cannot be framed.
_G50V2 = bytes.fromhex("32 02 07 01 00E8764801 00 10270000")
# g20v0 all counters.
_G20_ALL = bytes.fromhex("14 00 06")
# g60v1 (class 0) and g60v2 (class 1), all objects.
_G60V1_ALL = bytes.fromhex("3C 01 06")
_G60V2_ALL = bytes.fromhex("3C 02 06")
# One octet after a block: too few for an object header.
_TRAILING = bytes([0x14])

_IIN1_RESTART = 0x80

# Every function this outstation executes, each with a request whose first block frames
# and whose later part does not.
_EXECUTED = [
    (FunctionCode.READ, _G60V1_ALL + _TRAILING),
    (FunctionCode.WRITE, _G80V1_CLEAR_RESTART + _G50V1[:-1]),
    (FunctionCode.SELECT, _crob(1) + _crob(2, count=2)),
    (FunctionCode.OPERATE, _crob(1) + _crob(2, count=2)),
    (FunctionCode.DIRECT_OPERATE, _crob(1) + _crob(2, count=2)),
    (FunctionCode.DIRECT_OPERATE_NO_ACK, _crob(1) + _crob(2, count=2)),
    (FunctionCode.IMMEDIATE_FREEZE, _G20_ALL + _TRAILING),
    (FunctionCode.IMMEDIATE_FREEZE_NO_ACK, _G20_ALL + _TRAILING),
    (FunctionCode.FREEZE_CLEAR, _G20_ALL + _TRAILING),
    (FunctionCode.FREEZE_CLEAR_NO_ACK, _G20_ALL + _TRAILING),
    (FunctionCode.COLD_RESTART, _G60V1_ALL + _TRAILING),
    (FunctionCode.WARM_RESTART, _G60V1_ALL + _TRAILING),
    (FunctionCode.ENABLE_UNSOLICITED, _G60V2_ALL + _TRAILING),
    (FunctionCode.DISABLE_UNSOLICITED, _G60V2_ALL + _TRAILING),
    (FunctionCode.DELAY_MEASURE, _G60V1_ALL + _TRAILING),
    (FunctionCode.RECORD_CURRENT_TIME, _G60V1_ALL + _TRAILING),
]
_NO_ACK = {FunctionCode.DIRECT_OPERATE_NO_ACK, FunctionCode.IMMEDIATE_FREEZE_NO_ACK, FunctionCode.FREEZE_CLEAR_NO_ACK}
# A request for each reason framing stops, after a first block that frames, and the IIN2
# octet of its refusal: IIN2.1 for an object of unknown width, IIN2.2 for every other reason.
_REFUSALS = [
    (TruncationReason.UNKNOWN_WIDTH, FunctionCode.SELECT, _crob(1) + _G12V2, 0x02),
    # Range code 3: a virtual address start-stop range.
    (TruncationReason.UNSUPPORTED_RANGE, FunctionCode.READ, _G60V1_ALL + bytes.fromhex("01 02 03 00 00"), 0x04),
    # Prefix code 4: a 1-octet object size prefix, with a 1-octet count.
    (TruncationReason.SIZE_PREFIX, FunctionCode.READ, _G60V1_ALL + bytes.fromhex("01 02 47 01"), 0x04),
    (TruncationReason.RESERVED_QUALIFIER, FunctionCode.READ, _G60V1_ALL + bytes.fromhex("1E 01 0A"), 0x04),
    # g80v1 is packed, so a 1-octet index prefix before each bit cannot be laid out.
    (TruncationReason.PACKED_WITH_INDEX_PREFIX, FunctionCode.WRITE, _G50V1 + bytes.fromhex("50 01 17 01 07 00"), 0x04),
    (TruncationReason.RANGE_NAMES_NO_OBJECT, FunctionCode.WRITE, _G50V1 + bytes.fromhex("50 01 00 07 06"), 0x04),
    (TruncationReason.DATA_SHORTER_THAN_DECLARED, FunctionCode.SELECT, _crob(1) + _crob(2, count=2), 0x04),
    (TruncationReason.TRAILING_OCTETS, FunctionCode.READ, _G60V1_ALL + _TRAILING, 0x04),
]
# Every other request function but CONFIRM. One the outstation starts to execute fails here
# until it joins _EXECUTED.
_UNSUPPORTED = [
    function
    for function in FunctionCode
    if not function.is_response()
    and function != FunctionCode.CONFIRM
    and function not in {executed for executed, _ in _EXECUTED}
]


class _RecordingHandler(DefaultCommandHandler):
    """Records every command and answers SUCCESS."""

    def __init__(self) -> None:
        super().__init__()
        self.bo_selects: list[int] = []
        self.bo_operates: list[int] = []
        self.bo_direct: list[int] = []
        self.ao_selects: list[tuple[int, float]] = []
        self.ao_operates: list[tuple[int, float, int]] = []
        self.freezes: list[bool] = []

    def select_binary_output(
        self, index: int, code: ControlCode, count: int, on_time: int, off_time: int
    ) -> CommandResult:
        self.bo_selects.append(index)
        return CommandResult.success()

    def operate_binary_output(
        self, index: int, code: ControlCode, count: int, on_time: int, off_time: int, select_sequence: int
    ) -> CommandResult:
        self.bo_operates.append(index)
        return CommandResult.success()

    def direct_operate_binary_output(
        self, index: int, code: ControlCode, count: int, on_time: int, off_time: int
    ) -> CommandResult:
        self.bo_direct.append(index)
        return CommandResult.success()

    def select_analog_output(self, index: int, value: float) -> CommandResult:
        self.ao_selects.append((index, value))
        return CommandResult.success()

    def operate_analog_output(self, index: int, value: float, select_sequence: int) -> CommandResult:
        self.ao_operates.append((index, value, select_sequence))
        return CommandResult.success()

    def freeze_counters(self, start: int, stop: int, clear: bool) -> CommandResult:
        self.freezes.append(clear)
        return CommandResult.success()

    @property
    def calls(self) -> int:
        lists = (self.bo_selects, self.bo_operates, self.bo_direct, self.ao_selects, self.ao_operates, self.freezes)
        return sum(len(calls) for calls in lists)


def _outstation() -> tuple[Outstation, _RecordingHandler]:
    handler = _RecordingHandler()
    return Outstation(config=OutstationConfig(time_sync_required=False), handler=handler), handler


def _send(
    outstation: Outstation, function: FunctionCode, objects: bytes, seq: int, peer: PeerId = MASTER_A
) -> list[ResponseFragment]:
    return outstation.process_request(bytes([0xC0 | seq, function.value]) + objects, peer=peer)


def _spy_on_function_handlers(outstation: Outstation, monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Record the name of every Outstation._handle_* method the outstation calls."""
    called: list[str] = []

    def recording(name: str, handle: Callable[..., object]) -> Callable[..., object]:
        def record(*args: object, **kwargs: object) -> object:
            called.append(name)
            return handle(*args, **kwargs)

        return record

    for name in dir(Outstation):
        if name.startswith("_handle_"):
            monkeypatch.setattr(outstation, name, recording(name, getattr(outstation, name)))
    return called


def _only(responses: list[ResponseFragment]) -> ResponseFragment:
    assert len(responses) == 1
    return responses[0]


def _null_response(seq: int, iin2: int) -> bytes:
    """A null RESPONSE (FIR, FIN) from a restarted outstation, with IIN2 set as given."""
    return bytes([0xC0 | seq, 0x81, _IIN1_RESTART, iin2])


class TestEveryBlockReachesTheOutstation:
    """A request of several object blocks acts on every block, not on the first."""

    def test_select_of_two_crob_blocks_selects_both_and_echoes_both(self) -> None:
        outstation, handler = _outstation()
        objects = _crob(1) + _crob(2)

        response = _only(_send(outstation, FunctionCode.SELECT, objects, seq=2))

        assert handler.bo_selects == [1, 2]
        assert response.to_bytes() == _null_response(2, 0x00) + objects

    def test_select_of_a_crob_and_an_analog_output_selects_each(self) -> None:
        outstation, handler = _outstation()
        objects = _crob(1) + _G41V2

        response = _only(_send(outstation, FunctionCode.SELECT, objects, seq=2))

        assert handler.bo_selects == [1]
        assert handler.ao_selects == [(3, 100.0)]
        assert response.to_bytes() == _null_response(2, 0x00) + objects

    def test_operate_of_two_analog_output_blocks_operates_each(self) -> None:
        outstation, handler = _outstation()
        objects = _G41V1 + _G41V4
        _send(outstation, FunctionCode.SELECT, objects, seq=4)

        response = _only(_send(outstation, FunctionCode.OPERATE, objects, seq=5))

        assert handler.ao_operates == [(4, 1000.0, 4), (5, 0.5, 4)]
        assert response.to_bytes() == _null_response(5, 0x00) + objects

    def test_direct_operate_of_two_crob_blocks_operates_both(self) -> None:
        outstation, handler = _outstation()
        objects = _crob(1) + _crob(2)

        response = _only(_send(outstation, FunctionCode.DIRECT_OPERATE, objects, seq=6))

        assert handler.bo_direct == [1, 2]
        assert response.to_bytes() == _null_response(6, 0x00) + objects

    def test_ranged_read_of_two_groups_answers_both_groups(self) -> None:
        outstation, _handler = _outstation()
        for index in (0, 1):
            outstation.database.add_binary_input(index)
            outstation.database.add_analog_input(index)

        response = _only(_send(outstation, FunctionCode.READ, bytes.fromhex("01 02 00 00 01  1E 01 00 00 01"), seq=1))

        assert [(block.header.group, block.header.variation) for block in response.objects] == [(1, 2), (30, 1)]
        assert not response.header.iin & (IIN.PARAMETER_ERROR | IIN.OBJECT_UNKNOWN)

    def test_write_of_time_then_internal_indications_clears_restart(self) -> None:
        outstation, _handler = _outstation()

        response = _only(_send(outstation, FunctionCode.WRITE, _G50V1 + _G80V1_CLEAR_RESTART, seq=3))

        assert not outstation.iin & IIN.DEVICE_RESTART
        assert response.to_bytes() == bytes([0xC3, 0x81, 0x00, 0x00])


class TestUnframeableRequestRunsNothing:
    """A block that cannot be framed refuses the whole request."""

    @pytest.mark.parametrize(("function", "objects"), _EXECUTED, ids=[function.name for function, _ in _EXECUTED])
    def test_framed_first_block_does_not_run_when_a_later_part_fails(
        self, function: FunctionCode, objects: bytes, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        outstation, handler = _outstation()
        called = _spy_on_function_handlers(outstation, monkeypatch)

        responses = _send(outstation, function, objects, seq=3)

        expected = [] if function in _NO_ACK else [_null_response(3, 0x04)]
        assert [response.to_bytes() for response in responses] == expected
        assert called == []
        assert handler.calls == 0
        assert outstation.iin & IIN.DEVICE_RESTART
        assert outstation._state.selection_of(MASTER_A) is None

    def test_select_whose_last_block_is_short_arms_nothing(self) -> None:
        outstation, handler = _outstation()
        objects = _crob(1) + _crob(2, count=2)

        response = _only(_send(outstation, FunctionCode.SELECT, objects, seq=6))

        assert response.to_bytes() == _null_response(6, 0x04)
        assert handler.bo_selects == []
        assert outstation._state.selection_of(MASTER_A) is None
        other = _only(_send(outstation, FunctionCode.SELECT, _crob(1), seq=0, peer=MASTER_B))
        assert other.to_bytes() == _null_response(0, 0x00) + _crob(1)
        assert handler.bo_selects == [1]

    def test_byte_identical_operate_after_a_refused_select_operates_nothing(self) -> None:
        outstation, handler = _outstation()
        objects = _crob(1) + _crob(2, count=2)
        _send(outstation, FunctionCode.SELECT, objects, seq=6)

        response = _only(_send(outstation, FunctionCode.OPERATE, objects, seq=7))

        assert response.to_bytes() == _null_response(7, 0x04)
        assert handler.bo_operates == []

    def test_unknown_object_width_is_object_unknown(self) -> None:
        outstation, handler = _outstation()

        response = _only(_send(outstation, FunctionCode.SELECT, _crob(1) + _G12V2, seq=2))

        assert response.to_bytes() == _null_response(2, 0x02)
        assert handler.calls == 0
        assert outstation._state.selection_of(MASTER_A) is None

    def test_direct_operate_with_a_short_block_operates_nothing(self) -> None:
        outstation, handler = _outstation()

        response = _only(_send(outstation, FunctionCode.DIRECT_OPERATE, _crob(1, count=2), seq=3))

        assert response.to_bytes() == _null_response(3, 0x04)
        assert handler.bo_direct == []

    def test_write_with_a_short_block_applies_no_block(self) -> None:
        outstation, _handler = _outstation()

        response = _only(_send(outstation, FunctionCode.WRITE, _G80V1_CLEAR_RESTART + _G50V1[:-1], seq=5))

        assert response.to_bytes() == _null_response(5, 0x04)
        assert outstation.iin & IIN.DEVICE_RESTART

    def test_read_with_a_reserved_qualifier_is_parameter_error(self) -> None:
        outstation, _handler = _outstation()
        outstation.database.add_binary_input(0)

        response = _only(_send(outstation, FunctionCode.READ, bytes.fromhex("01 02 00 00 00  1E 01 0A"), seq=1))

        assert response.to_bytes() == _null_response(1, 0x04)

    @pytest.mark.parametrize(
        ("reason", "function", "objects", "iin2"),
        _REFUSALS,
        ids=[reason.name for reason, *_ in _REFUSALS],
    )
    def test_refusal_sets_the_iin2_bit_of_its_reason(
        self, reason: TruncationReason, function: FunctionCode, objects: bytes, iin2: int
    ) -> None:
        outstation, handler = _outstation()
        request = bytes([0xC7, function.value]) + objects
        truncation = parse_request(request).truncation
        assert truncation is not None
        assert truncation.reason is reason

        response = _only(outstation.process_request(request, peer=MASTER_A))

        assert response.to_bytes() == _null_response(7, iin2)
        assert handler.calls == 0

    def test_every_truncation_reason_has_a_refusal_case(self) -> None:
        assert {reason for reason, *_ in _REFUSALS} == set(TruncationReason)

    @pytest.mark.parametrize(
        ("function", "objects"),
        [
            (FunctionCode.DIRECT_OPERATE_NO_ACK, _crob(1, count=2)),
            (FunctionCode.IMMEDIATE_FREEZE_NO_ACK, _G20_ALL + bytes([0x14])),
            (FunctionCode.FREEZE_CLEAR_NO_ACK, _G20_ALL + bytes([0x14])),
        ],
        ids=["direct-operate-no-ack", "immediate-freeze-no-ack", "freeze-clear-no-ack"],
    )
    def test_no_ack_request_is_refused_without_a_response(self, function: FunctionCode, objects: bytes) -> None:
        outstation, handler = _outstation()

        responses = _send(outstation, function, objects, seq=3)

        assert responses == []
        assert handler.calls == 0

    def test_freeze_with_trailing_octets_freezes_nothing(self) -> None:
        outstation, handler = _outstation()

        response = _only(_send(outstation, FunctionCode.IMMEDIATE_FREEZE, _G20_ALL + bytes([0x14]), seq=3))

        assert response.to_bytes() == _null_response(3, 0x04)
        assert handler.freezes == []

    def test_unsupported_function_answers_no_function_support(self) -> None:
        """FREEZE_AT_TIME is not executed here, so its unframeable g50v2 does not change the answer."""
        outstation, _handler = _outstation()

        response = _only(_send(outstation, FunctionCode.FREEZE_AT_TIME, _G50V2 + _G20_ALL, seq=4))

        assert response.to_bytes() == _null_response(4, 0x01)

    @pytest.mark.parametrize("function", _UNSUPPORTED, ids=[function.name for function in _UNSUPPORTED])
    def test_every_unsupported_function_obeys_response_policy(
        self, function: FunctionCode, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        outstation, handler = _outstation()
        called = _spy_on_function_handlers(outstation, monkeypatch)

        responses = _send(outstation, function, _G60V1_ALL + _TRAILING, seq=4)

        if function in _NO_ACK_FUNCTIONS:
            assert responses == []
        else:
            assert _only(responses).to_bytes() == _null_response(4, 0x01)
        assert called == []
        assert handler.calls == 0

    @pytest.mark.parametrize("body", [b"", _G20_ALL, _G50V2 + _G20_ALL, _G60V1_ALL + _TRAILING])
    def test_unsupported_freeze_at_time_no_ack_stays_silent(self, body: bytes) -> None:
        """An unsupported NO_ACK function sends no response, even for an unframeable body."""
        outstation, handler = _outstation()

        assert _send(outstation, FunctionCode.FREEZE_AT_TIME_NO_ACK, body, seq=4) == []
        assert handler.calls == 0

    def test_no_ack_functions_are_the_four_the_standard_names(self) -> None:
        """IEEE 1815-2012 4.4.5 to 4.4.8 names four functions that never receive a response."""
        standard = {
            FunctionCode.DIRECT_OPERATE_NO_ACK,
            FunctionCode.IMMEDIATE_FREEZE_NO_ACK,
            FunctionCode.FREEZE_CLEAR_NO_ACK,
            FunctionCode.FREEZE_AT_TIME_NO_ACK,
        }
        assert standard == _NO_ACK_FUNCTIONS


class TestRefusalAndSelection:
    """IEEE 1815-2012 Table 4-9 is applied before the refusal."""

    def test_select_retry_with_an_unframeable_body_is_discarded_and_the_selection_holds(self) -> None:
        outstation, handler = _outstation()
        _send(outstation, FunctionCode.SELECT, _crob(1), seq=2)

        retry = _send(outstation, FunctionCode.SELECT, _crob(1) + _G12V2, seq=2)
        operate = _only(_send(outstation, FunctionCode.OPERATE, _crob(1), seq=3))

        assert retry == []
        assert handler.bo_operates == [1]
        assert operate.to_bytes() == _null_response(3, 0x00) + _crob(1)

    def test_refused_request_ends_the_selection(self) -> None:
        outstation, handler = _outstation()
        _send(outstation, FunctionCode.SELECT, _crob(1), seq=2)
        _send(outstation, FunctionCode.OPERATE, _crob(1) + _G12V2, seq=3)

        operate = _only(_send(outstation, FunctionCode.OPERATE, _crob(1), seq=3))

        assert handler.bo_operates == []
        no_select = bytearray(_crob(1))
        no_select[-1] = int(CommandStatus.NO_SELECT)
        assert operate.to_bytes() == _null_response(3, 0x00) + bytes(no_select)

    def test_confirm_with_unframeable_objects_is_not_answered_and_keeps_the_selection(self) -> None:
        outstation, _handler = _outstation()
        _send(outstation, FunctionCode.SELECT, _crob(1), seq=2)

        responses = _send(outstation, FunctionCode.CONFIRM, bytes([0x0C, 0x01, 0x0A]), seq=2)

        assert responses == []
        assert outstation._state.selection_of(MASTER_A) is not None

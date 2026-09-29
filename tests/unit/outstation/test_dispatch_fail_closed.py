"""Fix #46: a handler exception during request dispatch is answered, not propagated.

``process_request`` already turns a parse failure into a null response with
IIN2.2 (4.5.11). Before this fix, an exception raised by a handler reached
during dispatch (SELECT, OPERATE, DIRECT_OPERATE, a WRITE's time_handler, a
READ's database call, and so on) was not caught anywhere in the outstation
and propagated to the caller.

A control request (SELECT, OPERATE, DIRECT_OPERATE) now answers a raising
point with the normal per-object echo, its status UNDEFINED (127), rather
than a null response for the whole request: the master learns exactly which
points ran (4.4.4.3 Rule 5 and Rule 7). Every other request path keeps the
null-response answer this file originally proved. A no-ack function code
gets no response either way, win or lose (IEEE 1815-2012 4.4.5).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable

import pytest

from dnp3.application.builder import (
    build_all_objects_request,
    build_direct_operate_request,
    build_operate_request,
    build_select_request,
)
from dnp3.application.fragment import ObjectBlock, RequestFragment
from dnp3.application.header import RequestHeader
from dnp3.application.qualifiers import ObjectHeader
from dnp3.core.enums import ControlCode, FunctionCode
from dnp3.core.flags import IIN
from dnp3.core.timestamp import DNP3Timestamp
from dnp3.database import BinaryInputPoint, Database
from dnp3.outstation.config import OutstationConfig
from dnp3.outstation.handler import CommandResult, DefaultCommandHandler
from dnp3.outstation.outstation import Outstation
from dnp3.outstation.peer import UNSPECIFIED_PEER, PeerId

MASTER_A = PeerId(source=3, connection=1)

_IIN1_RESTART = 0x80
_IIN2_PARAMETER_ERROR = 0x04

# g12v1 (A.8.1): control code LATCH_ON, count 1, on-time, off-time, status.
_CROB_BODY = bytes.fromhex("03 01 00000000 00000000 00")


def _crob(index: int) -> ObjectBlock:
    """A well-formed g12v1 block, qualifier 0x17 (1-byte count, 1-byte index), one object."""
    header = ObjectHeader(group=12, variation=1, qualifier=0x17)
    return ObjectBlock(header=header, data=bytes([1, index]) + _CROB_BODY)


def _crob_multi(*indices: int) -> ObjectBlock:
    """A well-formed g12v1 block, qualifier 0x17, one object per index, in wire order."""
    header = ObjectHeader(group=12, variation=1, qualifier=0x17)
    data = bytes([len(indices)])
    for index in indices:
        data += bytes([index]) + _CROB_BODY
    return ObjectBlock(header=header, data=data)


def _g50v1_write(seq: int) -> RequestFragment:
    """A well-formed WRITE of g50v1 (A.23.1.2.3): qualifier 0x07, count 1, one timestamp."""
    octets = bytes.fromhex("00c4a5321701")  # 10.3.2 worked example.
    header = ObjectHeader(group=50, variation=1, qualifier=0x07)
    block = ObjectBlock(header=header, data=bytes([1]) + octets)
    return RequestFragment(header=RequestHeader.build(function=FunctionCode.WRITE, seq=seq), objects=(block,))


def _direct_operate_no_ack(*objects: ObjectBlock, seq: int = 0) -> RequestFragment:
    """No builder exists for this function code; IEEE 1815-2012 4.4.5 forbids any response."""
    header = RequestHeader.build(function=FunctionCode.DIRECT_OPERATE_NO_ACK, seq=seq)
    return RequestFragment(header=header, objects=objects)


def _freeze_no_ack(function: FunctionCode, *, seq: int = 0) -> RequestFragment:
    """A g20v0 (all counters) freeze-family request; 4.4.6-4.4.8 forbid a response to its no-ack form."""
    header = ObjectHeader(group=20, variation=0, qualifier=0x06)
    block = ObjectBlock(header=header, data=b"")
    return RequestFragment(header=RequestHeader.build(function=function, seq=seq), objects=(block,))


def _null_response(seq: int, iin2: int) -> bytes:
    """A null RESPONSE (FIR, FIN) from a freshly restarted outstation, with IIN2 set as given."""
    return bytes([0xC0 | seq, 0x81, _IIN1_RESTART, iin2])


_UNDEFINED_STATUS = 0x7F  # CommandStatus.UNDEFINED (127), Table 11-7.
_CROB_RECORD_SIZE = 12  # 0x17 qualifier: 1-byte index + 11-byte body (control_code..status).


def _echo_response(request: RequestFragment, statuses: list[int], *, iin2: int = 0) -> bytes:
    """Expected echo bytes: the request's object octets with each object's status set.

    Assumes a single g12v1 (0x17) block with one status octet per object, in
    wire order (IEEE 1815-2012 4.4.4.3 Rule 7 and Rule 8).
    """
    seq = request.header.control.seq
    object_octets = bytearray(request.to_bytes()[2:])  # after control + function
    for position, status in enumerate(statuses):
        offset = 3 + 1 + position * _CROB_RECORD_SIZE + (_CROB_RECORD_SIZE - 1)  # header(3) + count(1) + record
        object_octets[offset] = status
    return bytes([0xC0 | seq, 0x81, _IIN1_RESTART, iin2]) + bytes(object_octets)


class _RaisingHandler(DefaultCommandHandler):
    """Every control method succeeds except the one named ``raises``, which raises ``exc``.

    ``raise_on_index`` narrows the raise to one point, so a multi-point
    request can have an earlier point succeed before the raising one.
    """

    def __init__(self, raises: str, exc: type[BaseException] = ValueError, raise_on_index: int | None = None) -> None:
        super().__init__()
        self.raises = raises
        self.exc = exc
        self.raise_on_index = raise_on_index

    def select_binary_output(
        self, index: int, code: ControlCode, count: int, on_time: int, off_time: int
    ) -> CommandResult:
        if self.raises == "select" and self.raise_on_index in (None, index):
            raise self.exc("boom: select_binary_output")
        return CommandResult.success()

    def operate_binary_output(
        self, index: int, code: ControlCode, count: int, on_time: int, off_time: int, select_sequence: int
    ) -> CommandResult:
        if self.raises == "operate":
            raise self.exc("boom: operate_binary_output")
        return CommandResult.success()

    def direct_operate_binary_output(
        self, index: int, code: ControlCode, count: int, on_time: int, off_time: int
    ) -> CommandResult:
        if self.raises == "direct_operate":
            raise self.exc("boom: direct_operate_binary_output")
        return CommandResult.success()

    def freeze_counters(self, start: int, stop: int, clear: bool) -> CommandResult:
        if self.raises == "freeze":
            raise self.exc("boom: freeze_counters")
        return CommandResult.success()


class _RaisingDatabase(Database):
    """A READ of binary inputs raises instead of returning points."""

    def get_all_binary_inputs(self) -> list[BinaryInputPoint]:
        msg = "boom: get_all_binary_inputs"
        raise RuntimeError(msg)


def _outstation(handler: DefaultCommandHandler | None = None) -> Outstation:
    config = OutstationConfig(time_sync_required=False)
    return Outstation(config=config, handler=handler or DefaultCommandHandler())


class TestSelectHandlerRaises:
    """A SELECT handler that raises echoes UNDEFINED for that point, not a propagated exception."""

    def test_echoes_undefined_for_the_raising_point(self) -> None:
        outstation = _outstation(_RaisingHandler("select"))

        request = build_select_request(objects=(_crob(1),), seq=5)
        responses = outstation.process_request(request.to_bytes(), peer=MASTER_A)

        assert len(responses) == 1
        assert responses[0].to_bytes() == _echo_response(request, [_UNDEFINED_STATUS])
        assert IIN.PARAMETER_ERROR not in responses[0].header.iin

    def test_leaves_no_selection_armed(self) -> None:
        """Two points, raise on the second: proves the FIRST point's already-armed select is cleared too.

        With only one point, this assertion cannot fail: that point was never
        armed in the first place, since it raised before ``add_select`` ran.
        """
        outstation = _outstation(_RaisingHandler("select", raise_on_index=2))

        outstation.process_request(build_select_request(objects=(_crob_multi(1, 2),), seq=5).to_bytes(), peer=MASTER_A)

        assert outstation._state.get_select(1, peer=MASTER_A) is None
        assert outstation._state.get_select(2, peer=MASTER_A) is None

    def test_well_formed_select_is_unaffected(self) -> None:
        """Control: a non-raising handler still gets the ordinary SELECT echo, not IIN2.2."""
        outstation = _outstation(_RaisingHandler("none"))

        request = build_select_request(objects=(_crob(1),), seq=5)
        responses = outstation.process_request(request.to_bytes(), peer=MASTER_A)

        assert len(responses) == 1
        assert responses[0].to_bytes() != _echo_response(request, [_UNDEFINED_STATUS])
        assert IIN.PARAMETER_ERROR not in responses[0].header.iin


class TestOperateHandlerRaises:
    """An OPERATE handler that raises echoes UNDEFINED for that point after a successful SELECT."""

    def test_echoes_undefined_and_terminates_the_selection(self) -> None:
        outstation = _outstation(_RaisingHandler("operate"))
        outstation.process_request(build_select_request(objects=(_crob(1),), seq=2).to_bytes(), peer=MASTER_A)

        request = build_operate_request(objects=(_crob(1),), seq=3)
        responses = outstation.process_request(request.to_bytes(), peer=MASTER_A)

        assert len(responses) == 1
        assert responses[0].to_bytes() == _echo_response(request, [_UNDEFINED_STATUS])
        assert IIN.PARAMETER_ERROR not in responses[0].header.iin
        assert outstation._state.selection_of(MASTER_A) is None


class TestDirectOperateHandlerRaises:
    """A DIRECT_OPERATE handler that raises echoes UNDEFINED for that point."""

    def test_echoes_undefined_for_the_raising_point(self) -> None:
        outstation = _outstation(_RaisingHandler("direct_operate"))

        request = build_direct_operate_request(objects=(_crob(1),), seq=7)
        responses = outstation.process_request(request.to_bytes(), peer=MASTER_A)

        assert len(responses) == 1
        assert responses[0].to_bytes() == _echo_response(request, [_UNDEFINED_STATUS])
        assert IIN.PARAMETER_ERROR not in responses[0].header.iin


class TestNoAckHandlerRaises:
    """IEEE 1815-2012 4.4.5 to 4.4.8 forbid any response to a no-ack function code.

    That silence is unconditional: the same silence applies whether the
    request succeeds or a handler raises. With no response, the ERROR log
    record is the only signal a raise happened, so it must fire every time.
    FREEZE_AT_TIME_NO_ACK is not in this set: the outstation has no executor
    for it, so it never reaches a handler that could raise (existing gap,
    out of this fix's scope).
    """

    @pytest.mark.parametrize(
        ("build_request", "raises", "function_name"),
        [
            pytest.param(
                lambda: _direct_operate_no_ack(_crob(1), seq=4),
                "direct_operate",
                "DIRECT_OPERATE_NO_ACK",
                id="direct_operate_no_ack",
            ),
            pytest.param(
                lambda: _freeze_no_ack(FunctionCode.IMMEDIATE_FREEZE_NO_ACK),
                "freeze",
                "IMMEDIATE_FREEZE_NO_ACK",
                id="immediate_freeze_no_ack",
            ),
            pytest.param(
                lambda: _freeze_no_ack(FunctionCode.FREEZE_CLEAR_NO_ACK),
                "freeze",
                "FREEZE_CLEAR_NO_ACK",
                id="freeze_clear_no_ack",
            ),
        ],
    )
    def test_answers_nothing_and_logs_one_error(
        self,
        build_request: Callable[[], RequestFragment],
        raises: str,
        function_name: str,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        outstation = _outstation(_RaisingHandler(raises))

        with caplog.at_level(logging.ERROR, logger="dnp3.outstation.outstation"):
            responses = outstation.process_request(build_request().to_bytes(), peer=MASTER_A)

        assert responses == []
        records = [r for r in caplog.records if r.name == "dnp3.outstation.outstation"]
        assert len(records) == 1
        assert records[0].exc_info is not None
        assert function_name in records[0].getMessage()

    def test_keyboard_interrupt_propagates(self) -> None:
        outstation = _outstation(_RaisingHandler("direct_operate", exc=KeyboardInterrupt))
        request = _direct_operate_no_ack(_crob(1), seq=4)

        with pytest.raises(KeyboardInterrupt):
            outstation.process_request(request.to_bytes(), peer=MASTER_A)


class TestTimeHandlerRaises:
    """A raising time_handler answers IIN2.2 and leaves NEED_TIME set (#140)."""

    def test_answers_parameter_error_and_leaves_need_time_set(self) -> None:
        def _raising_time_handler(timestamp: DNP3Timestamp) -> None:
            msg = "boom: time_handler"
            raise ValueError(msg)

        outstation = Outstation(time_handler=_raising_time_handler)
        assert IIN.NEED_TIME in outstation.iin

        request = _g50v1_write(seq=3)
        responses = outstation.process_request(request.to_bytes())

        assert len(responses) == 1
        assert IIN.PARAMETER_ERROR in responses[0].header.iin
        assert responses[0].header.control.seq == 3
        assert IIN.NEED_TIME in outstation.iin


class TestDatabaseReadRaises:
    """A raising database read answers IIN2.2 instead of an unhandled exception."""

    def test_answers_null_response_with_seq_and_parameter_error(self) -> None:
        outstation = _outstation()
        outstation.database = _RaisingDatabase()

        request = build_all_objects_request(function=FunctionCode.READ, group=1, variation=2, seq=6)
        responses = outstation.process_request(request.to_bytes())

        assert len(responses) == 1
        assert responses[0].to_bytes() == _null_response(6, _IIN2_PARAMETER_ERROR)


class TestOnlyExceptionSubclassesAreCaught:
    """Invariant: KeyboardInterrupt, SystemExit and asyncio.CancelledError still propagate."""

    def test_system_exit_propagates(self) -> None:
        outstation = _outstation(_RaisingHandler("direct_operate", exc=SystemExit))
        request = build_direct_operate_request(objects=(_crob(1),), seq=1)

        with pytest.raises(SystemExit):
            outstation.process_request(request.to_bytes())

    def test_cancelled_error_propagates(self) -> None:
        outstation = _outstation(_RaisingHandler("direct_operate", exc=asyncio.CancelledError))
        request = build_direct_operate_request(objects=(_crob(1),), seq=1)

        with pytest.raises(asyncio.CancelledError):
            outstation.process_request(request.to_bytes())


class TestHandlerExceptionIsLogged:
    """The exception is logged with its traceback and the point index, not swallowed silently."""

    def test_logs_the_traceback_at_error_level(self, caplog: pytest.LogCaptureFixture) -> None:
        outstation = _outstation(_RaisingHandler("direct_operate"))
        request = build_direct_operate_request(objects=(_crob(1),), seq=1)

        with caplog.at_level(logging.ERROR, logger="dnp3.outstation.outstation"):
            outstation.process_request(request.to_bytes())

        records = [r for r in caplog.records if r.name == "dnp3.outstation.outstation"]
        assert len(records) == 1
        record = records[0]
        assert record.levelno == logging.ERROR
        assert record.args == (FunctionCode.DIRECT_OPERATE.name, 1, UNSPECIFIED_PEER)
        assert record.exc_info is not None
        assert record.exc_info[0] is ValueError

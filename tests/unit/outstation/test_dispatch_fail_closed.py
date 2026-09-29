"""Fix #46: a handler exception during request dispatch answers a null response.

``process_request`` already turns a parse failure into a null response with
IIN2.2 (4.5.11). Before this fix, an exception raised by a handler reached
during dispatch (SELECT, OPERATE, DIRECT_OPERATE, a WRITE's time_handler, a
READ's database call, and so on) was not caught anywhere in the outstation
and propagated to the caller. This file proves the same answer now covers
that case, except for a no-ack function code, which IEEE 1815-2012 4.4.5
says never gets a response, win or lose.
"""

from __future__ import annotations

import asyncio
import logging

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
from dnp3.outstation.peer import PeerId

MASTER_A = PeerId(source=3, connection=1)

_IIN1_RESTART = 0x80
_IIN2_PARAMETER_ERROR = 0x04

# g12v1 (A.8.1): control code LATCH_ON, count 1, on-time, off-time, status.
_CROB_BODY = bytes.fromhex("03 01 00000000 00000000 00")


def _crob(index: int) -> ObjectBlock:
    """A well-formed g12v1 block, qualifier 0x17 (1-byte count, 1-byte index), one object."""
    header = ObjectHeader(group=12, variation=1, qualifier=0x17)
    return ObjectBlock(header=header, data=bytes([1, index]) + _CROB_BODY)


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


def _null_response(seq: int, iin2: int) -> bytes:
    """A null RESPONSE (FIR, FIN) from a freshly restarted outstation, with IIN2 set as given."""
    return bytes([0xC0 | seq, 0x81, _IIN1_RESTART, iin2])


class _RaisingHandler(DefaultCommandHandler):
    """Every control method succeeds except the one named ``raises``, which raises ``exc``."""

    def __init__(self, raises: str, exc: type[BaseException] = ValueError) -> None:
        super().__init__()
        self.raises = raises
        self.exc = exc

    def select_binary_output(
        self, index: int, code: ControlCode, count: int, on_time: int, off_time: int
    ) -> CommandResult:
        if self.raises == "select":
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


class _RaisingDatabase(Database):
    """A READ of binary inputs raises instead of returning points."""

    def get_all_binary_inputs(self) -> list[BinaryInputPoint]:
        msg = "boom: get_all_binary_inputs"
        raise RuntimeError(msg)


def _outstation(handler: DefaultCommandHandler | None = None) -> Outstation:
    config = OutstationConfig(time_sync_required=False)
    return Outstation(config=config, handler=handler or DefaultCommandHandler())


class TestSelectHandlerRaises:
    """A SELECT handler that raises answers a null response, not a propagated exception."""

    def test_answers_null_response_with_seq_and_parameter_error(self) -> None:
        outstation = _outstation(_RaisingHandler("select"))

        request = build_select_request(objects=(_crob(1),), seq=5)
        responses = outstation.process_request(request.to_bytes(), peer=MASTER_A)

        assert len(responses) == 1
        assert responses[0].to_bytes() == _null_response(5, _IIN2_PARAMETER_ERROR)

    def test_leaves_no_selection_armed(self) -> None:
        outstation = _outstation(_RaisingHandler("select"))

        outstation.process_request(build_select_request(objects=(_crob(1),), seq=5).to_bytes(), peer=MASTER_A)

        assert outstation._state.selection_of(MASTER_A) is None

    def test_well_formed_select_is_unaffected(self) -> None:
        """Control: a non-raising handler still gets the ordinary SELECT echo, not IIN2.2."""
        outstation = _outstation(_RaisingHandler("none"))

        request = build_select_request(objects=(_crob(1),), seq=5)
        responses = outstation.process_request(request.to_bytes(), peer=MASTER_A)

        assert len(responses) == 1
        assert responses[0].to_bytes() != _null_response(5, _IIN2_PARAMETER_ERROR)
        assert IIN.PARAMETER_ERROR not in responses[0].header.iin


class TestOperateHandlerRaises:
    """An OPERATE handler that raises answers a null response after a successful SELECT."""

    def test_answers_null_response_and_terminates_the_selection(self) -> None:
        outstation = _outstation(_RaisingHandler("operate"))
        outstation.process_request(build_select_request(objects=(_crob(1),), seq=2).to_bytes(), peer=MASTER_A)

        request = build_operate_request(objects=(_crob(1),), seq=3)
        responses = outstation.process_request(request.to_bytes(), peer=MASTER_A)

        assert len(responses) == 1
        assert responses[0].to_bytes() == _null_response(3, _IIN2_PARAMETER_ERROR)
        assert outstation._state.selection_of(MASTER_A) is None


class TestDirectOperateHandlerRaises:
    """A DIRECT_OPERATE handler that raises answers a null response."""

    def test_answers_null_response_with_seq_and_parameter_error(self) -> None:
        outstation = _outstation(_RaisingHandler("direct_operate"))

        request = build_direct_operate_request(objects=(_crob(1),), seq=7)
        responses = outstation.process_request(request.to_bytes(), peer=MASTER_A)

        assert len(responses) == 1
        assert responses[0].to_bytes() == _null_response(7, _IIN2_PARAMETER_ERROR)


class TestDirectOperateNoAckHandlerRaises:
    """IEEE 1815-2012 4.4.5 forbids any response to a no-ack function code.

    DIRECT_OPERATE_NO_ACK behaves like DIRECT_OPERATE except that the
    outstation sends no response at all (4.4.5); that silence is
    unconditional, so the same silence applies whether the request succeeds
    or a handler raises.
    """

    def test_answers_nothing(self) -> None:
        outstation = _outstation(_RaisingHandler("direct_operate"))

        request = _direct_operate_no_ack(_crob(1), seq=4)
        responses = outstation.process_request(request.to_bytes(), peer=MASTER_A)

        assert responses == []


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
    """The exception is logged with its traceback, not swallowed silently."""

    def test_logs_the_traceback_at_error_level(self, caplog: pytest.LogCaptureFixture) -> None:
        outstation = _outstation(_RaisingHandler("direct_operate"))
        request = build_direct_operate_request(objects=(_crob(1),), seq=1)

        with caplog.at_level(logging.ERROR, logger="dnp3.outstation.outstation"):
            outstation.process_request(request.to_bytes())

        records = [r for r in caplog.records if r.name == "dnp3.outstation.outstation"]
        assert len(records) == 1
        record = records[0]
        assert record.levelno == logging.ERROR
        assert FunctionCode.DIRECT_OPERATE.name in record.getMessage()
        assert record.exc_info is not None
        assert record.exc_info[0] is ValueError

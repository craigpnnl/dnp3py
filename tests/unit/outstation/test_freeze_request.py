"""Freeze requests freeze only the counters they name, and refuse other groups.

Qualifier codes: IEEE 1815-2012 Table 4-2 and Table 4-3. IIN bits: Table 4-14.
"""

from __future__ import annotations

import pytest

from dnp3.application.fragment import ObjectBlock, RequestFragment
from dnp3.application.header import RequestHeader
from dnp3.application.qualifiers import ObjectHeader
from dnp3.core.enums import FunctionCode
from dnp3.core.flags import IIN
from dnp3.database import Database
from dnp3.outstation.config import OutstationConfig
from dnp3.outstation.handler import CommandResult, DefaultCommandHandler
from dnp3.outstation.outstation import Outstation


class RecordingFreezeHandler(DefaultCommandHandler):
    def __init__(self, database: Database | None = None) -> None:
        self.calls: list[tuple[int, int, bool]] = []
        self._database = database

    def freeze_counters(self, start: int, stop: int, clear: bool) -> CommandResult:
        self.calls.append((start, stop, clear))
        if self._database is not None:
            for index in list(self._database.counters):
                if start <= index <= stop:
                    self._database.freeze_counter(index)
        return CommandResult.success()


def _freeze(function: FunctionCode, *blocks: tuple[int, int, bytes]) -> bytes:
    objects = tuple(
        ObjectBlock(header=ObjectHeader(group=group, variation=0, qualifier=qualifier), data=data)
        for group, qualifier, data in blocks
    )
    return RequestFragment(header=RequestHeader.build(function=function, seq=1), objects=objects).to_bytes()


def _outstation(handler: RecordingFreezeHandler, database: Database | None = None) -> Outstation:
    return Outstation(
        config=OutstationConfig(time_sync_required=False), handler=handler, database=database or Database()
    )


class TestFreezeRange:
    @pytest.mark.parametrize(
        ("qualifier", "data", "expected"),
        [
            (0x06, b"", [(0, 0xFFFF)]),
            (0x00, bytes([1, 2]), [(1, 2)]),
            (0x01, bytes([3, 0, 9, 1]), [(3, 0x109)]),
            (0x07, bytes([3]), [(0, 2)]),
            (0x17, bytes([3, 0, 1, 5]), [(0, 1), (5, 5)]),
            (0x28, bytes([2, 0, 0, 1, 7, 1]), [(0x100, 0x100), (0x107, 0x107)]),
        ],
    )
    def test_only_named_counters_are_frozen(self, qualifier: int, data: bytes, expected: list[tuple[int, int]]) -> None:
        handler = RecordingFreezeHandler()
        responses = _outstation(handler).process_request(_freeze(FunctionCode.IMMEDIATE_FREEZE, (20, qualifier, data)))
        assert [(start, stop) for start, stop, _ in handler.calls] == expected
        assert not responses[0].header.iin & (IIN.PARAMETER_ERROR | IIN.OBJECT_UNKNOWN)

    def test_clear_is_passed_for_each_range(self) -> None:
        handler = RecordingFreezeHandler()
        _outstation(handler).process_request(_freeze(FunctionCode.FREEZE_CLEAR, (20, 0x17, bytes([2, 0, 4]))))
        assert handler.calls == [(0, 0, True), (4, 4, True)]

    def test_inverted_range_is_parameter_error(self) -> None:
        handler = RecordingFreezeHandler()
        responses = _outstation(handler).process_request(
            _freeze(FunctionCode.IMMEDIATE_FREEZE, (20, 0x00, bytes([5, 1])))
        )
        assert handler.calls == []
        assert IIN.PARAMETER_ERROR in responses[0].header.iin


class TestFreezeGroup:
    @pytest.mark.parametrize("group", [30, 21, 1])
    def test_group_other_than_counters_is_object_unknown(self, group: int) -> None:
        handler = RecordingFreezeHandler()
        responses = _outstation(handler).process_request(_freeze(FunctionCode.IMMEDIATE_FREEZE, (group, 0x06, b"")))
        assert handler.calls == []
        assert IIN.OBJECT_UNKNOWN in responses[0].header.iin

    def test_counter_header_still_frozen_next_to_an_unknown_one(self) -> None:
        handler = RecordingFreezeHandler()
        request = _freeze(FunctionCode.IMMEDIATE_FREEZE, (30, 0x06, b""), (20, 0x00, bytes([0, 0])))
        responses = _outstation(handler).process_request(request)
        assert handler.calls == [(0, 0, False)]
        assert IIN.OBJECT_UNKNOWN in responses[0].header.iin

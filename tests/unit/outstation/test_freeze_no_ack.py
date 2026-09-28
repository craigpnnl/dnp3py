"""Tests for IMMEDIATE_FREEZE_NO_ACK and FREEZE_CLEAR_NO_ACK (issue #121).

IEEE 1815-2012 Table 14-3 (clause 14.4) lists function codes 7-10 on Counter
(group 20) objects as required for a Level 2 outstation. 0x08 and 0x0A are
the NO_ACK forms of 0x07 (IMMEDIATE_FREEZE) and 0x09 (FREEZE_CLEAR): same
freeze semantics, but per the NO_ACK convention already used for
DIRECT_OPERATE_NO_ACK, the outstation sends no response.
"""

from __future__ import annotations

from dnp3.application.fragment import ObjectBlock, RequestFragment
from dnp3.application.header import ApplicationControl, RequestHeader
from dnp3.application.qualifiers import ObjectHeader
from dnp3.core.enums import FunctionCode
from dnp3.database import CounterConfig, Database
from dnp3.outstation.handler import CommandResult, DefaultCommandHandler
from dnp3.outstation.outstation import Outstation


class FreezingCommandHandler(DefaultCommandHandler):
    """Handler that actually freezes counters, like a real vendor handler.

    _handle_freeze only calls handler.freeze_counters; DefaultCommandHandler
    rejects it, so a handler must perform the freeze/clear itself for the
    database to change.
    """

    def __init__(self, database: Database) -> None:
        self._database = database

    def freeze_counters(self, start: int, stop: int, clear: bool) -> CommandResult:
        for index in list(self._database.counters):
            if start <= index <= stop:
                self._database.freeze_counter(index)
                if clear:
                    self._database.update_counter(index, value=0)
        return CommandResult.success()


def _build_request(function: FunctionCode) -> bytes:
    """Build a freeze-family request for g20v0 (all counters)."""
    header = ObjectHeader(group=20, variation=0, qualifier=0x06)
    request = RequestFragment(
        header=RequestHeader(
            control=ApplicationControl(fir=True, fin=True, con=False, uns=False, seq=0),
            function=function,
        ),
        objects=[ObjectBlock(header=header, data=b"")],
    )
    return request.to_bytes()


def _seeded_outstation(value: int) -> tuple[Outstation, Database]:
    db = Database()
    db.add_counter(0, CounterConfig())
    db.add_frozen_counter(0, CounterConfig())
    db.update_counter(0, value=value)
    outstation = Outstation(database=db, handler=FreezingCommandHandler(db))
    return outstation, db


def _seeded_outstation_default_handler(value: int) -> tuple[Outstation, Database]:
    """A plain outstation: DefaultCommandHandler rejects freeze_counters."""
    db = Database()
    db.add_counter(0, CounterConfig())
    db.add_frozen_counter(0, CounterConfig())
    db.update_counter(0, value=value)
    outstation = Outstation(database=db)
    return outstation, db


class TestImmediateFreezeNoAck:
    """FunctionCode 0x08: freezes exactly as 0x07 does, no response."""

    def test_no_response(self) -> None:
        outstation, _ = _seeded_outstation(value=100)
        responses = outstation.process_request(_build_request(FunctionCode.IMMEDIATE_FREEZE_NO_ACK))
        assert responses == []

    def test_frozen_value_matches_acked_form(self) -> None:
        acked, acked_db = _seeded_outstation(value=100)
        acked.process_request(_build_request(FunctionCode.IMMEDIATE_FREEZE))

        no_ack, no_ack_db = _seeded_outstation(value=100)
        no_ack.process_request(_build_request(FunctionCode.IMMEDIATE_FREEZE_NO_ACK))

        assert acked_db.frozen_counters[0].value == 100
        assert no_ack_db.frozen_counters[0].value == acked_db.frozen_counters[0].value

    def test_running_counter_not_cleared(self) -> None:
        outstation, db = _seeded_outstation(value=100)
        outstation.process_request(_build_request(FunctionCode.IMMEDIATE_FREEZE_NO_ACK))
        assert db.counters[0].value == 100

    def test_rejected_by_default_handler_changes_nothing(self) -> None:
        """DefaultCommandHandler.freeze_counters rejects; nothing is frozen."""
        outstation, db = _seeded_outstation_default_handler(value=100)
        responses = outstation.process_request(_build_request(FunctionCode.IMMEDIATE_FREEZE_NO_ACK))
        assert responses == []
        assert db.counters[0].value == 100
        assert db.frozen_counters[0].value == 0


class TestFreezeClearNoAck:
    """FunctionCode 0x0A: freezes and clears exactly as 0x09 does, no response."""

    def test_no_response(self) -> None:
        outstation, _ = _seeded_outstation(value=100)
        responses = outstation.process_request(_build_request(FunctionCode.FREEZE_CLEAR_NO_ACK))
        assert responses == []

    def test_frozen_value_matches_acked_form(self) -> None:
        acked, acked_db = _seeded_outstation(value=100)
        acked.process_request(_build_request(FunctionCode.FREEZE_CLEAR))

        no_ack, no_ack_db = _seeded_outstation(value=100)
        no_ack.process_request(_build_request(FunctionCode.FREEZE_CLEAR_NO_ACK))

        assert acked_db.frozen_counters[0].value == 100
        assert no_ack_db.frozen_counters[0].value == acked_db.frozen_counters[0].value

    def test_running_counter_cleared(self) -> None:
        outstation, db = _seeded_outstation(value=100)
        outstation.process_request(_build_request(FunctionCode.FREEZE_CLEAR_NO_ACK))
        assert db.counters[0].value == 0

    def test_rejected_by_default_handler_changes_nothing(self) -> None:
        """DefaultCommandHandler.freeze_counters rejects; nothing is frozen or cleared."""
        outstation, db = _seeded_outstation_default_handler(value=100)
        responses = outstation.process_request(_build_request(FunctionCode.FREEZE_CLEAR_NO_ACK))
        assert responses == []
        assert db.counters[0].value == 100
        assert db.frozen_counters[0].value == 0

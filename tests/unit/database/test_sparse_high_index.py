"""Sparse high-index support for the MESA vendor region (~50000).

The 1815.2 MESA profile places points at vendor-region indices around 50000
while the database is sized by point COUNT plus headroom, not by maximum index.
These tests prove the database stores and reads back a ~50000-index point whose
index is far above the configured count limit, that the count limit is still
enforced loudly, and that the outstation emits the high-index point on the wire
with the Issue #6 start/stop range qualifier and the correct value.
"""

from dnp3.application.builder import build_integrity_poll
from dnp3.core.flags import AnalogQuality
from dnp3.database import Database, DatabaseConfig
from dnp3.outstation.config import OutstationConfig
from dnp3.outstation.outstation import Outstation

VENDOR_INDEX = 50000
VENDOR_VALUE = 12345


class TestDatabaseSparseHighIndex:
    """The database is count-sized, so a high sparse index round-trips."""

    def test_stores_and_reads_back_high_index_point(self) -> None:
        """A point at index 50000 in a count-5 database reads back exactly."""
        db = Database(config=DatabaseConfig(max_analog_inputs=5))
        db.add_analog_input(VENDOR_INDEX, value=float(VENDOR_VALUE), quality=AnalogQuality.ONLINE)

        point = db.get_analog_input(VENDOR_INDEX)
        assert point is not None
        assert point.index == VENDOR_INDEX
        assert point.value == float(VENDOR_VALUE)
        assert point.quality == AnalogQuality.ONLINE

    def test_index_may_exceed_configured_count_max(self) -> None:
        """The index limit is independent of the configured count limit."""
        db = Database(config=DatabaseConfig(max_analog_inputs=3))
        db.add_analog_input(0, value=1.0)
        db.add_analog_input(VENDOR_INDEX, value=2.0)
        db.add_analog_input(VENDOR_INDEX + 1, value=3.0)

        assert db.analog_input_count == 3
        assert db.get_analog_input(VENDOR_INDEX).value == 2.0
        assert db.get_analog_input(VENDOR_INDEX + 1).value == 3.0

    def test_count_limit_refuses_loudly(self) -> None:
        """Exceeding the configured count raises, even for sparse high indices."""
        db = Database(config=DatabaseConfig(max_analog_inputs=2))
        db.add_analog_input(VENDOR_INDEX, value=1.0)
        db.add_analog_input(VENDOR_INDEX + 1, value=2.0)

        try:
            db.add_analog_input(VENDOR_INDEX + 2, value=3.0)
        except ValueError as exc:
            assert "Maximum analog inputs" in str(exc)
        else:
            raise AssertionError("expected ValueError when the count limit is exceeded")


class TestOutstationHighIndexWire:
    """The outstation emits a high-index static point on the wire correctly."""

    def test_integrity_poll_emits_high_index_with_2byte_start_stop(self) -> None:
        """Index 50000 is emitted with qualifier 0x01 and the value round-trips."""
        db_config = DatabaseConfig(max_analog_inputs=5)
        config = OutstationConfig(time_sync_required=False, database=db_config)
        database = Database(config=db_config)
        database.add_analog_input(VENDOR_INDEX, value=float(VENDOR_VALUE), quality=AnalogQuality.ONLINE)
        outstation = Outstation(config=config, database=database)

        responses = outstation.process_request(build_integrity_poll().to_bytes())

        ai_blocks = [obj for frag in responses for obj in frag.objects if obj.header.group == 30]
        assert len(ai_blocks) == 1
        block = ai_blocks[0]
        # Stop index 50000 > 255 forces the 2-byte start/stop qualifier (Issue #6),
        # never the count+index event form.
        assert block.header.qualifier == 0x01
        start = int.from_bytes(block.data[0:2], "little")
        stop = int.from_bytes(block.data[2:4], "little")
        assert start == VENDOR_INDEX
        assert stop == VENDOR_INDEX
        value = int.from_bytes(block.data[5:9], "little", signed=True)
        assert value == VENDOR_VALUE

"""Tests for #159: a NaN analog input is refused at the database boundary.

Mirrors AnalogOutputPoint (point.py __post_init__ and update(), tested in
test_database.py's TestAnalogOutputOperations): the point keeps its prior
value, quality, timestamp and event state; nothing is synthesized.
"""

import math
import struct

import pytest

from dnp3.core.flags import AnalogQuality
from dnp3.core.timestamp import DNP3Timestamp
from dnp3.database.database import Database
from dnp3.database.point import AnalogInputConfig, AnalogInputPoint, EventClass

ONLINE = AnalogQuality.ONLINE


class TestAnalogInputConstructionRefusesNaN:
    def test_add_analog_input_nan_raises_and_nothing_stored(self) -> None:
        db = Database()
        with pytest.raises(ValueError, match="NaN"):
            db.add_analog_input(0, value=float("nan"))

        assert 0 not in db.analog_inputs
        assert db.get_analog_input(0) is None

    def test_construct_point_directly_with_nan_raises(self) -> None:
        with pytest.raises(ValueError, match="NaN"):
            AnalogInputPoint(index=0, value=float("nan"))

    def test_negative_nan_raises(self) -> None:
        with pytest.raises(ValueError, match="NaN"):
            AnalogInputPoint(index=0, value=-float("nan"))

    def test_non_default_payload_nan_raises(self) -> None:
        """A NaN with a payload other than Python's default quiet NaN bits."""
        payload_nan = struct.unpack("<d", struct.pack("<Q", 0x7FF8000000000001))[0]
        assert math.isnan(payload_nan)
        with pytest.raises(ValueError, match="NaN"):
            AnalogInputPoint(index=0, value=payload_nan)

    def test_second_point_refused_first_point_unaffected(self) -> None:
        db = Database()
        db.add_analog_input(0, value=1.0, quality=ONLINE)
        with pytest.raises(ValueError, match="NaN"):
            db.add_analog_input(1, value=float("nan"))

        assert 1 not in db.analog_inputs
        point0 = db.get_analog_input(0)
        assert point0 is not None
        assert point0.value == 1.0

    def test_infinity_is_still_accepted(self) -> None:
        """Regression: the NaN guard does not reject infinity (issue #159 covers that separately)."""
        db = Database()
        point = db.add_analog_input(0, value=float("inf"))
        assert point.value == float("inf")


class TestAnalogInputUpdateRefusesNaN:
    def test_update_nan_raises_and_prior_state_unchanged(self) -> None:
        db = Database()
        point = db.add_analog_input(0, value=100.0, quality=ONLINE)
        timestamp = DNP3Timestamp(1000)
        db.update_analog_input(0, value=100.0, quality=ONLINE, timestamp=timestamp)
        prior_last_event_value = point.last_event_value

        with pytest.raises(ValueError, match="NaN"):
            db.update_analog_input(0, value=float("nan"))

        assert point.value == 100.0
        assert point.quality == ONLINE
        assert point.timestamp == timestamp
        assert point.last_event_value == prior_last_event_value

    def test_update_nan_queues_no_event(self) -> None:
        db = Database()
        db.add_analog_input(0, AnalogInputConfig(event_class=EventClass.CLASS_1, deadband=0))
        events_before = len(db.event_buffer.class1.events)

        with pytest.raises(ValueError, match="NaN"):
            db.update_analog_input(0, value=float("nan"))

        assert len(db.event_buffer.class1.events) == events_before

    def test_update_negative_nan_raises(self) -> None:
        db = Database()
        db.add_analog_input(0, value=1.0)
        with pytest.raises(ValueError, match="NaN"):
            db.update_analog_input(0, value=-float("nan"))
        point = db.get_analog_input(0)
        assert point is not None
        assert point.value == 1.0

    def test_update_infinity_still_accepted(self) -> None:
        """Regression: the NaN guard does not reject infinity."""
        db = Database()
        db.add_analog_input(0, value=0.0)
        db.update_analog_input(0, value=float("inf"))
        point = db.get_analog_input(0)
        assert point is not None
        assert point.value == float("inf")

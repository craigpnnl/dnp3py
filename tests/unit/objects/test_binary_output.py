"""Tests for Binary Output objects (Groups 10, 11, 12)."""

import pytest
from hypothesis import given
from hypothesis import strategies as st

from dnp3.core.enums import ControlCode as CoreControlCode
from dnp3.core.enums import OperationType, TripCloseCode
from dnp3.core.flags import BinaryQuality
from dnp3.core.timestamp import DNP3Timestamp
from dnp3.objects.base import EventObject, StaticObject
from dnp3.objects.binary_output import (
    BINARY_OUTPUT_EVENT_GROUP,
    BINARY_OUTPUT_STATIC_GROUP,
    CROB,
    CROB_GROUP,
    STATE_BIT,
    BinaryOutputEvent,
    BinaryOutputEventTime,
    BinaryOutputFlags,
    CommandStatus,
    ControlCode,
)

# Quality flags valid for binary output (bits 0-6 only, not STATE bit 7)
VALID_QUALITY_FLAGS = [q for q in BinaryQuality if q != BinaryQuality.STATE and q.value <= 0x7F]


class TestConstants:
    """Tests for binary output constants."""

    def test_static_group(self) -> None:
        """Static group is 10."""
        assert BINARY_OUTPUT_STATIC_GROUP == 10

    def test_event_group(self) -> None:
        """Event group is 11."""
        assert BINARY_OUTPUT_EVENT_GROUP == 11

    def test_crob_group(self) -> None:
        """CROB group is 12."""
        assert CROB_GROUP == 12

    def test_state_bit(self) -> None:
        """State bit is 0x80."""
        assert STATE_BIT == 0x80


class TestControlCode:
    """ControlCode on the object path is the single core definition (IEEE 1815-2012 A.8.1.2)."""

    def test_operation_types(self) -> None:
        """Operation type values."""
        assert ControlCode.NUL == 0x00
        assert ControlCode.PULSE_ON == 0x01
        assert ControlCode.PULSE_OFF == 0x02
        assert ControlCode.LATCH_ON == 0x03
        assert ControlCode.LATCH_OFF == 0x04

    def test_trip_close_codes(self) -> None:
        """Trip-Close code sits in bits 7-6."""
        assert TripCloseCode.NUL == 0
        assert TripCloseCode.CLOSE == 1
        assert TripCloseCode.TRIP == 2
        assert TripCloseCode.RESERVED == 3
        assert int(ControlCode.from_fields(OperationType.NUL, tcc=TripCloseCode.CLOSE)) == 0x40
        assert int(ControlCode.from_fields(OperationType.NUL, tcc=TripCloseCode.TRIP)) == 0x80
        assert int(ControlCode.from_fields(OperationType.NUL, tcc=TripCloseCode.RESERVED)) == 0xC0

    def test_modifiers(self) -> None:
        """Queue is bit 4 and Clear is bit 5."""
        assert int(ControlCode.from_fields(OperationType.NUL, queue=True)) == 0x10
        assert int(ControlCode.from_fields(OperationType.NUL, clear=True)) == 0x20

    def test_combine_flags(self) -> None:
        """Combine operation with modifiers."""
        combined = ControlCode.from_fields(OperationType.PULSE_ON, tcc=TripCloseCode.CLOSE, queue=True)
        assert combined == 0x51

    def test_same_class_as_core(self) -> None:
        """The object-path ControlCode is the core class, not a second definition."""
        assert ControlCode is CoreControlCode


class TestCommandStatus:
    """Tests for CommandStatus enum."""

    def test_common_values(self) -> None:
        """Common status values."""
        assert CommandStatus.SUCCESS == 0
        assert CommandStatus.TIMEOUT == 1
        assert CommandStatus.NO_SELECT == 2
        assert CommandStatus.NOT_SUPPORTED == 4
        assert CommandStatus.LOCAL == 7
        assert CommandStatus.NOT_AUTHORIZED == 9

    def test_all_values_unique(self) -> None:
        """All status codes are unique."""
        values = [s.value for s in CommandStatus]
        assert len(values) == len(set(values))


class TestBinaryOutputFlags:
    """Tests for BinaryOutputFlags (g10v2)."""

    def test_group_variation(self) -> None:
        """Correct group and variation."""
        assert BinaryOutputFlags.GROUP == 10
        assert BinaryOutputFlags.VARIATION == 2

    def test_size(self) -> None:
        """Size is 1 byte."""
        assert BinaryOutputFlags.SIZE == 1

    def test_is_static_object(self) -> None:
        """BinaryOutputFlags is a StaticObject."""
        obj = BinaryOutputFlags(quality=BinaryQuality.ONLINE, state=False)
        assert isinstance(obj, StaticObject)

    def test_create_basic(self) -> None:
        """Create basic binary output with flags."""
        obj = BinaryOutputFlags(quality=BinaryQuality.ONLINE, state=True)
        assert obj.quality == BinaryQuality.ONLINE
        assert obj.state is True

    def test_to_bytes_state_false(self) -> None:
        """Serialize with state=False."""
        obj = BinaryOutputFlags(quality=BinaryQuality.ONLINE, state=False)
        data = obj.to_bytes()
        assert data == bytes([0x01])

    def test_to_bytes_state_true(self) -> None:
        """Serialize with state=True."""
        obj = BinaryOutputFlags(quality=BinaryQuality.ONLINE, state=True)
        data = obj.to_bytes()
        assert data == bytes([0x81])

    def test_from_bytes_state_false(self) -> None:
        """Parse with state=False."""
        obj = BinaryOutputFlags.from_bytes(bytes([0x01]))
        assert obj.quality == BinaryQuality.ONLINE
        assert obj.state is False

    def test_from_bytes_state_true(self) -> None:
        """Parse with state=True."""
        obj = BinaryOutputFlags.from_bytes(bytes([0x81]))
        assert obj.quality == BinaryQuality.ONLINE
        assert obj.state is True

    def test_from_bytes_empty_raises(self) -> None:
        """Empty data raises error."""
        with pytest.raises(ValueError, match="requires 1 byte"):
            BinaryOutputFlags.from_bytes(b"")

    def test_roundtrip(self) -> None:
        """Serialize then parse returns equivalent object."""
        original = BinaryOutputFlags(quality=BinaryQuality.ONLINE | BinaryQuality.LOCAL_FORCED, state=True)
        parsed = BinaryOutputFlags.from_bytes(original.to_bytes())
        assert parsed == original

    @given(
        st.sampled_from(VALID_QUALITY_FLAGS),
        st.booleans(),
    )
    def test_roundtrip_hypothesis(self, quality: BinaryQuality, state: bool) -> None:
        """Property: roundtrip preserves all values."""
        original = BinaryOutputFlags(quality=quality, state=state)
        parsed = BinaryOutputFlags.from_bytes(original.to_bytes())
        assert parsed == original

    def test_is_online_true(self) -> None:
        """is_online returns True when ONLINE flag set."""
        obj = BinaryOutputFlags(quality=BinaryQuality.ONLINE, state=False)
        assert obj.is_online is True

    def test_is_online_false(self) -> None:
        """is_online returns False when ONLINE flag not set."""
        obj = BinaryOutputFlags(quality=BinaryQuality(0), state=False)
        assert obj.is_online is False

    def test_immutable(self) -> None:
        """BinaryOutputFlags is immutable."""
        obj = BinaryOutputFlags(quality=BinaryQuality.ONLINE, state=False)
        with pytest.raises(AttributeError):
            obj.state = True  # type: ignore[misc]


class TestBinaryOutputEvent:
    """Tests for BinaryOutputEvent (g11v1)."""

    def test_group_variation(self) -> None:
        """Correct group and variation."""
        assert BinaryOutputEvent.GROUP == 11
        assert BinaryOutputEvent.VARIATION == 1

    def test_size(self) -> None:
        """Size is 1 byte."""
        assert BinaryOutputEvent.SIZE == 1

    def test_is_event_object(self) -> None:
        """BinaryOutputEvent is an EventObject."""
        obj = BinaryOutputEvent(quality=BinaryQuality.ONLINE, state=False)
        assert isinstance(obj, EventObject)

    def test_create_basic(self) -> None:
        """Create basic binary output event."""
        obj = BinaryOutputEvent(quality=BinaryQuality.ONLINE, state=True)
        assert obj.quality == BinaryQuality.ONLINE
        assert obj.state is True

    def test_to_bytes_state_false(self) -> None:
        """Serialize with state=False."""
        obj = BinaryOutputEvent(quality=BinaryQuality.ONLINE, state=False)
        data = obj.to_bytes()
        assert data == bytes([0x01])

    def test_to_bytes_state_true(self) -> None:
        """Serialize with state=True."""
        obj = BinaryOutputEvent(quality=BinaryQuality.ONLINE, state=True)
        data = obj.to_bytes()
        assert data == bytes([0x81])

    def test_from_bytes_state_false(self) -> None:
        """Parse with state=False."""
        obj = BinaryOutputEvent.from_bytes(bytes([0x01]))
        assert obj.quality == BinaryQuality.ONLINE
        assert obj.state is False

    def test_from_bytes_state_true(self) -> None:
        """Parse with state=True."""
        obj = BinaryOutputEvent.from_bytes(bytes([0x81]))
        assert obj.quality == BinaryQuality.ONLINE
        assert obj.state is True

    def test_from_bytes_empty_raises(self) -> None:
        """Empty data raises error."""
        with pytest.raises(ValueError, match="requires 1 byte"):
            BinaryOutputEvent.from_bytes(b"")

    def test_roundtrip(self) -> None:
        """Serialize then parse returns equivalent object."""
        original = BinaryOutputEvent(quality=BinaryQuality.ONLINE, state=True)
        parsed = BinaryOutputEvent.from_bytes(original.to_bytes())
        assert parsed == original

    @given(
        st.sampled_from(VALID_QUALITY_FLAGS),
        st.booleans(),
    )
    def test_roundtrip_hypothesis(self, quality: BinaryQuality, state: bool) -> None:
        """Property: roundtrip preserves all values."""
        original = BinaryOutputEvent(quality=quality, state=state)
        parsed = BinaryOutputEvent.from_bytes(original.to_bytes())
        assert parsed == original


class TestBinaryOutputEventTime:
    """Tests for BinaryOutputEventTime (g11v2)."""

    def test_group_variation(self) -> None:
        """Correct group and variation."""
        assert BinaryOutputEventTime.GROUP == 11
        assert BinaryOutputEventTime.VARIATION == 2

    def test_size(self) -> None:
        """Size is 7 bytes."""
        assert BinaryOutputEventTime.SIZE == 7

    def test_is_event_object(self) -> None:
        """BinaryOutputEventTime is an EventObject."""
        ts = DNP3Timestamp(milliseconds=0)
        obj = BinaryOutputEventTime(quality=BinaryQuality.ONLINE, state=False, timestamp=ts)
        assert isinstance(obj, EventObject)

    def test_create_basic(self) -> None:
        """Create binary output event with time."""
        ts = DNP3Timestamp(milliseconds=1000)
        obj = BinaryOutputEventTime(quality=BinaryQuality.ONLINE, state=True, timestamp=ts)
        assert obj.quality == BinaryQuality.ONLINE
        assert obj.state is True
        assert obj.timestamp == ts

    def test_to_bytes(self) -> None:
        """Serialize event with timestamp."""
        ts = DNP3Timestamp(milliseconds=0x0102030405)
        obj = BinaryOutputEventTime(quality=BinaryQuality.ONLINE, state=True, timestamp=ts)
        data = obj.to_bytes()
        assert len(data) == 7
        assert data[0] == 0x81  # ONLINE | STATE
        assert data[1:7] == bytes([0x05, 0x04, 0x03, 0x02, 0x01, 0x00])

    def test_from_bytes(self) -> None:
        """Parse event with timestamp."""
        data = bytes([0x81, 0x05, 0x04, 0x03, 0x02, 0x01, 0x00])
        obj = BinaryOutputEventTime.from_bytes(data)
        assert obj.quality == BinaryQuality.ONLINE
        assert obj.state is True
        assert obj.timestamp.milliseconds == 0x0102030405

    def test_from_bytes_too_short_raises(self) -> None:
        """Data too short raises error."""
        with pytest.raises(ValueError, match="requires 7 bytes"):
            BinaryOutputEventTime.from_bytes(bytes([0x81, 0x00, 0x00]))

    def test_roundtrip(self) -> None:
        """Serialize then parse returns equivalent object."""
        ts = DNP3Timestamp(milliseconds=1234567890)
        original = BinaryOutputEventTime(
            quality=BinaryQuality.ONLINE | BinaryQuality.CHATTER_FILTER,
            state=False,
            timestamp=ts,
        )
        parsed = BinaryOutputEventTime.from_bytes(original.to_bytes())
        assert parsed == original

    @given(
        st.sampled_from(VALID_QUALITY_FLAGS),
        st.booleans(),
        st.integers(min_value=0, max_value=2**48 - 1),
    )
    def test_roundtrip_hypothesis(self, quality: BinaryQuality, state: bool, ms: int) -> None:
        """Property: roundtrip preserves all values."""
        ts = DNP3Timestamp(milliseconds=ms)
        original = BinaryOutputEventTime(quality=quality, state=state, timestamp=ts)
        parsed = BinaryOutputEventTime.from_bytes(original.to_bytes())
        assert parsed == original


class TestCROB:
    """Tests for CROB (g12v1)."""

    def test_group_variation(self) -> None:
        """Correct group and variation."""
        assert CROB.GROUP == 12
        assert CROB.VARIATION == 1

    def test_size(self) -> None:
        """Size is 11 bytes."""
        assert CROB.SIZE == 11

    def test_is_static_object(self) -> None:
        """CROB is a StaticObject."""
        obj = CROB(
            control_code=ControlCode.PULSE_ON,
            count=1,
            on_time_ms=1000,
            off_time_ms=0,
            status=CommandStatus.SUCCESS,
        )
        assert isinstance(obj, StaticObject)

    def test_create_basic(self) -> None:
        """Create basic CROB."""
        obj = CROB(
            control_code=ControlCode.PULSE_ON,
            count=1,
            on_time_ms=1000,
            off_time_ms=500,
            status=CommandStatus.SUCCESS,
        )
        assert obj.control_code == ControlCode.PULSE_ON
        assert obj.count == 1
        assert obj.on_time_ms == 1000
        assert obj.off_time_ms == 500
        assert obj.status == CommandStatus.SUCCESS

    def test_count_zero_valid(self) -> None:
        """Count of 0 is valid."""
        obj = CROB(
            control_code=ControlCode.NUL,
            count=0,
            on_time_ms=0,
            off_time_ms=0,
            status=CommandStatus.SUCCESS,
        )
        assert obj.count == 0

    def test_count_max_valid(self) -> None:
        """Count of 255 is valid."""
        obj = CROB(
            control_code=ControlCode.NUL,
            count=255,
            on_time_ms=0,
            off_time_ms=0,
            status=CommandStatus.SUCCESS,
        )
        assert obj.count == 255

    def test_count_negative_raises(self) -> None:
        """Negative count raises error."""
        with pytest.raises(ValueError, match=r"Count.*out of range"):
            CROB(
                control_code=ControlCode.NUL,
                count=-1,
                on_time_ms=0,
                off_time_ms=0,
                status=CommandStatus.SUCCESS,
            )

    def test_count_too_large_raises(self) -> None:
        """Count > 255 raises error."""
        with pytest.raises(ValueError, match=r"Count.*out of range"):
            CROB(
                control_code=ControlCode.NUL,
                count=256,
                on_time_ms=0,
                off_time_ms=0,
                status=CommandStatus.SUCCESS,
            )

    def test_on_time_negative_raises(self) -> None:
        """Negative on_time raises error."""
        with pytest.raises(ValueError, match=r"On time.*out of range"):
            CROB(
                control_code=ControlCode.NUL,
                count=0,
                on_time_ms=-1,
                off_time_ms=0,
                status=CommandStatus.SUCCESS,
            )

    def test_off_time_negative_raises(self) -> None:
        """Negative off_time raises error."""
        with pytest.raises(ValueError, match=r"Off time.*out of range"):
            CROB(
                control_code=ControlCode.NUL,
                count=0,
                on_time_ms=0,
                off_time_ms=-1,
                status=CommandStatus.SUCCESS,
            )

    def test_to_bytes(self) -> None:
        """Serialize CROB."""
        obj = CROB(
            control_code=ControlCode.PULSE_ON,
            count=5,
            on_time_ms=1000,
            off_time_ms=500,
            status=CommandStatus.SUCCESS,
        )
        data = obj.to_bytes()
        assert len(data) == 11
        assert data[0] == 0x01  # PULSE_ON
        assert data[1] == 5  # count
        # on_time = 1000 = 0x000003E8
        assert data[2:6] == bytes([0xE8, 0x03, 0x00, 0x00])
        # off_time = 500 = 0x000001F4
        assert data[6:10] == bytes([0xF4, 0x01, 0x00, 0x00])
        assert data[10] == 0  # SUCCESS

    def test_from_bytes(self) -> None:
        """Parse CROB."""
        data = bytes([0x01, 5, 0xE8, 0x03, 0x00, 0x00, 0xF4, 0x01, 0x00, 0x00, 0])
        obj = CROB.from_bytes(data)
        assert obj.control_code == ControlCode.PULSE_ON
        assert obj.count == 5
        assert obj.on_time_ms == 1000
        assert obj.off_time_ms == 500
        assert obj.status == CommandStatus.SUCCESS

    def test_from_bytes_too_short_raises(self) -> None:
        """Data too short raises error."""
        with pytest.raises(ValueError, match="requires 11 bytes"):
            CROB.from_bytes(bytes([0x01, 0x00]))

    def test_roundtrip(self) -> None:
        """Serialize then parse returns equivalent object."""
        original = CROB(
            control_code=ControlCode.from_fields(OperationType.LATCH_ON, tcc=TripCloseCode.CLOSE),
            count=10,
            on_time_ms=5000,
            off_time_ms=2000,
            status=CommandStatus.NOT_AUTHORIZED,
        )
        parsed = CROB.from_bytes(original.to_bytes())
        assert parsed == original

    @given(
        st.integers(min_value=0, max_value=255).filter(lambda octet: octet & 0x0F <= OperationType.LATCH_OFF),
        st.integers(min_value=0, max_value=255),
        st.integers(min_value=0, max_value=0xFFFFFFFF),
        st.integers(min_value=0, max_value=0xFFFFFFFF),
        st.sampled_from(list(CommandStatus)),
    )
    def test_roundtrip_hypothesis(
        self,
        octet: int,
        count: int,
        on_time_ms: int,
        off_time_ms: int,
        status: CommandStatus,
    ) -> None:
        """Property: roundtrip preserves all values."""
        original = CROB(
            control_code=ControlCode(octet),
            count=count,
            on_time_ms=on_time_ms,
            off_time_ms=off_time_ms,
            status=status,
        )
        parsed = CROB.from_bytes(original.to_bytes())
        assert parsed == original

    def test_pulse_on_factory(self) -> None:
        """pulse_on factory creates correct CROB."""
        obj = CROB.pulse_on(on_time_ms=2000, count=3)
        assert obj.control_code == ControlCode.PULSE_ON
        assert obj.on_time_ms == 2000
        assert obj.count == 3
        assert obj.status == CommandStatus.SUCCESS

    def test_pulse_on_defaults(self) -> None:
        """pulse_on factory has sensible defaults."""
        obj = CROB.pulse_on()
        assert obj.control_code == ControlCode.PULSE_ON
        assert obj.on_time_ms == 1000
        assert obj.off_time_ms == 0
        assert obj.count == 1

    def test_pulse_off_factory(self) -> None:
        """pulse_off factory creates correct CROB."""
        obj = CROB.pulse_off(off_time_ms=2000, count=3)
        assert obj.control_code == ControlCode.PULSE_OFF
        assert obj.off_time_ms == 2000
        assert obj.count == 3
        assert obj.status == CommandStatus.SUCCESS

    def test_pulse_off_defaults(self) -> None:
        """pulse_off factory has sensible defaults."""
        obj = CROB.pulse_off()
        assert obj.control_code == ControlCode.PULSE_OFF
        assert obj.on_time_ms == 0
        assert obj.off_time_ms == 1000
        assert obj.count == 1

    def test_latch_on_factory(self) -> None:
        """latch_on factory creates correct CROB."""
        obj = CROB.latch_on()
        assert obj.control_code == ControlCode.LATCH_ON
        assert obj.on_time_ms == 0
        assert obj.off_time_ms == 0
        assert obj.count == 1
        assert obj.status == CommandStatus.SUCCESS

    def test_latch_off_factory(self) -> None:
        """latch_off factory creates correct CROB."""
        obj = CROB.latch_off()
        assert obj.control_code == ControlCode.LATCH_OFF
        assert obj.on_time_ms == 0
        assert obj.off_time_ms == 0
        assert obj.count == 1
        assert obj.status == CommandStatus.SUCCESS

    def test_immutable(self) -> None:
        """CROB is immutable."""
        obj = CROB.pulse_on()
        with pytest.raises(AttributeError):
            obj.count = 5  # type: ignore[misc]


class TestCROBControlCodeOctet:
    """CROB decodes the control octet with the Table A-2 field layout."""

    @pytest.mark.parametrize("octet", [0x00, 0x20, 0x01, 0x21, 0x03, 0x23, 0x04, 0x24, 0x41, 0x61, 0x81, 0xA1])
    def test_table_a2_octet_round_trips(self, octet: int) -> None:
        """from_bytes then to_bytes keeps the control octet byte for byte."""
        data = bytes([octet, 1]) + (250).to_bytes(4, "little") + (0).to_bytes(4, "little") + bytes([0])
        crob = CROB.from_bytes(data)
        assert int(crob.control_code) == octet
        assert crob.to_bytes() == data

    def test_trip_is_not_clear(self) -> None:
        """0x81 decodes as TRIP + PULSE_ON with Clear 0, not as a clear."""
        data = bytes([0x81, 1]) + bytes(8) + bytes([0])
        code = CROB.from_bytes(data).control_code
        assert code.tcc is TripCloseCode.TRIP
        assert code.op_type is OperationType.PULSE_ON
        assert code.clear is False
        assert code.queue is False

    def test_close_is_not_queue(self) -> None:
        """0x41 decodes as CLOSE + PULSE_ON with Queue 0."""
        data = bytes([0x41, 1]) + bytes(8) + bytes([0])
        code = CROB.from_bytes(data).control_code
        assert code.tcc is TripCloseCode.CLOSE
        assert code.queue is False
        assert code.clear is False

    def test_undefined_op_type_rejected(self) -> None:
        """An Op Type of 5 to 15 is undefined and is not silently accepted."""
        data = bytes([0x85, 1]) + bytes(8) + bytes([0])
        with pytest.raises(ValueError, match="Op Type"):
            CROB.from_bytes(data)

"""Tests for quality flags and IIN bits."""

from dnp3.core.flags import IIN, BinaryQuality, DoubleBitState


class TestBinaryQuality:
    """Tests for binary point quality flags."""

    def test_online_flag(self) -> None:
        """ONLINE flag is bit 0."""
        assert BinaryQuality.ONLINE == 0x01

    def test_restart_flag(self) -> None:
        """RESTART flag is bit 1."""
        assert BinaryQuality.RESTART == 0x02

    def test_comm_lost_flag(self) -> None:
        """COMM_LOST flag is bit 2."""
        assert BinaryQuality.COMM_LOST == 0x04

    def test_remote_forced_flag(self) -> None:
        """REMOTE_FORCED flag is bit 3."""
        assert BinaryQuality.REMOTE_FORCED == 0x08

    def test_local_forced_flag(self) -> None:
        """LOCAL_FORCED flag is bit 4."""
        assert BinaryQuality.LOCAL_FORCED == 0x10

    def test_chatter_filter_flag(self) -> None:
        """CHATTER_FILTER flag is bit 5."""
        assert BinaryQuality.CHATTER_FILTER == 0x20

    def test_state_flag(self) -> None:
        """STATE flag is bit 7."""
        assert BinaryQuality.STATE == 0x80

    def test_combine_flags(self) -> None:
        """Multiple flags can be combined."""
        combined = BinaryQuality.ONLINE | BinaryQuality.RESTART
        assert combined == 0x03
        assert BinaryQuality.ONLINE in combined
        assert BinaryQuality.RESTART in combined

    def test_is_online(self) -> None:
        """Test checking if point is online."""
        flags = BinaryQuality.ONLINE
        assert BinaryQuality.ONLINE in flags

        flags_offline = BinaryQuality(0)
        assert BinaryQuality.ONLINE not in flags_offline


class TestDoubleBitState:
    """Tests for double-bit binary states."""

    def test_intermediate_state(self) -> None:
        """INTERMEDIATE state is 0."""
        assert DoubleBitState.INTERMEDIATE == 0

    def test_off_state(self) -> None:
        """OFF state is 1."""
        assert DoubleBitState.OFF == 1

    def test_on_state(self) -> None:
        """ON state is 2."""
        assert DoubleBitState.ON == 2

    def test_indeterminate_state(self) -> None:
        """INDETERMINATE state is 3."""
        assert DoubleBitState.INDETERMINATE == 3


class TestIIN:
    """Tests for Internal Indications."""

    def test_broadcast_bit(self) -> None:
        """BROADCAST is IIN1 bit 0."""
        assert IIN.BROADCAST == 0x0001

    def test_class1_events_bit(self) -> None:
        """CLASS_1_EVENTS is IIN1 bit 1."""
        assert IIN.CLASS_1_EVENTS == 0x0002

    def test_class2_events_bit(self) -> None:
        """CLASS_2_EVENTS is IIN1 bit 2."""
        assert IIN.CLASS_2_EVENTS == 0x0004

    def test_class3_events_bit(self) -> None:
        """CLASS_3_EVENTS is IIN1 bit 3."""
        assert IIN.CLASS_3_EVENTS == 0x0008

    def test_need_time_bit(self) -> None:
        """NEED_TIME is IIN1 bit 4."""
        assert IIN.NEED_TIME == 0x0010

    def test_local_control_bit(self) -> None:
        """LOCAL_CONTROL is IIN1 bit 5."""
        assert IIN.LOCAL_CONTROL == 0x0020

    def test_device_trouble_bit(self) -> None:
        """DEVICE_TROUBLE is IIN1 bit 6."""
        assert IIN.DEVICE_TROUBLE == 0x0040

    def test_device_restart_bit(self) -> None:
        """DEVICE_RESTART is IIN1 bit 7."""
        assert IIN.DEVICE_RESTART == 0x0080

    def test_no_func_code_support_bit(self) -> None:
        """NO_FUNC_CODE_SUPPORT is IIN2 bit 0."""
        assert IIN.NO_FUNC_CODE_SUPPORT == 0x0100

    def test_object_unknown_bit(self) -> None:
        """OBJECT_UNKNOWN is IIN2 bit 1."""
        assert IIN.OBJECT_UNKNOWN == 0x0200

    def test_parameter_error_bit(self) -> None:
        """PARAMETER_ERROR is IIN2 bit 2."""
        assert IIN.PARAMETER_ERROR == 0x0400

    def test_event_buffer_overflow_bit(self) -> None:
        """EVENT_BUFFER_OVERFLOW is IIN2 bit 3."""
        assert IIN.EVENT_BUFFER_OVERFLOW == 0x0800

    def test_combine_iin_bits(self) -> None:
        """Multiple IIN bits can be combined."""
        combined = IIN.CLASS_1_EVENTS | IIN.CLASS_2_EVENTS
        assert IIN.CLASS_1_EVENTS in combined
        assert IIN.CLASS_2_EVENTS in combined

    def test_iin_to_bytes(self) -> None:
        """IIN can be converted to 2 bytes."""
        iin = IIN.DEVICE_RESTART | IIN.NEED_TIME
        # IIN1 byte, IIN2 byte
        iin1 = iin & 0xFF
        iin2 = (iin >> 8) & 0xFF
        assert iin1 == 0x90  # DEVICE_RESTART (0x80) | NEED_TIME (0x10)
        assert iin2 == 0x00

    def test_iin_from_bytes(self) -> None:
        """IIN can be created from 2 bytes."""
        iin1 = 0x82  # CLASS_1_EVENTS | DEVICE_RESTART
        iin2 = 0x01  # NO_FUNC_CODE_SUPPORT
        iin = IIN(iin1 | (iin2 << 8))
        assert IIN.CLASS_1_EVENTS in iin
        assert IIN.DEVICE_RESTART in iin
        assert IIN.NO_FUNC_CODE_SUPPORT in iin

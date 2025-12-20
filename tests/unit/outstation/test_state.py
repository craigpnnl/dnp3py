"""Tests for outstation state machine."""

import time

from dnp3.core.enums import ControlCode
from dnp3.core.flags import IIN
from dnp3.outstation.state import (
    OutstationState,
    OutstationStateManager,
    SelectState,
    SequenceState,
    UnsolicitedState,
)


class TestOutstationState:
    """Tests for OutstationState enum."""

    def test_idle_state(self) -> None:
        """IDLE state exists."""
        assert OutstationState.IDLE is not None

    def test_processing_state(self) -> None:
        """PROCESSING state exists."""
        assert OutstationState.PROCESSING is not None

    def test_waiting_confirm_state(self) -> None:
        """WAITING_CONFIRM state exists."""
        assert OutstationState.WAITING_CONFIRM is not None

    def test_unsolicited_state(self) -> None:
        """UNSOLICITED state exists."""
        assert OutstationState.UNSOLICITED is not None


class TestSelectState:
    """Tests for SelectState."""

    def test_create_binary_select(self) -> None:
        """Can create binary output SELECT state."""
        select = SelectState(
            index=5,
            is_binary=True,
            control_code=ControlCode.LATCH_ON,
            count=1,
            on_time=1000,
            off_time=500,
            sequence=3,
        )
        assert select.index == 5
        assert select.is_binary is True
        assert select.control_code == ControlCode.LATCH_ON
        assert select.count == 1
        assert select.on_time == 1000
        assert select.off_time == 500
        assert select.sequence == 3

    def test_create_analog_select(self) -> None:
        """Can create analog output SELECT state."""
        select = SelectState(
            index=10,
            is_binary=False,
            analog_value=123.45,
            sequence=7,
        )
        assert select.index == 10
        assert select.is_binary is False
        assert select.analog_value == 123.45
        assert select.sequence == 7

    def test_is_expired_false(self) -> None:
        """is_expired returns False when not expired."""
        select = SelectState(index=0, is_binary=True)
        assert select.is_expired(timeout=10.0) is False

    def test_is_expired_true(self) -> None:
        """is_expired returns True when expired."""
        select = SelectState(
            index=0,
            is_binary=True,
            timestamp=time.monotonic() - 15.0,  # 15 seconds ago
        )
        assert select.is_expired(timeout=10.0) is True

    def test_matches_binary_true(self) -> None:
        """matches_binary returns True for matching parameters."""
        select = SelectState(
            index=5,
            is_binary=True,
            control_code=ControlCode.PULSE_ON,
            count=3,
            on_time=1000,
            off_time=500,
        )
        assert select.matches_binary(
            index=5,
            code=ControlCode.PULSE_ON,
            count=3,
            on_time=1000,
            off_time=500,
        )

    def test_matches_binary_wrong_index(self) -> None:
        """matches_binary returns False for wrong index."""
        select = SelectState(
            index=5,
            is_binary=True,
            control_code=ControlCode.LATCH_ON,
        )
        assert not select.matches_binary(
            index=6,
            code=ControlCode.LATCH_ON,
            count=1,
            on_time=0,
            off_time=0,
        )

    def test_matches_binary_wrong_code(self) -> None:
        """matches_binary returns False for wrong control code."""
        select = SelectState(
            index=5,
            is_binary=True,
            control_code=ControlCode.LATCH_ON,
        )
        assert not select.matches_binary(
            index=5,
            code=ControlCode.LATCH_OFF,
            count=1,
            on_time=0,
            off_time=0,
        )

    def test_matches_binary_not_binary(self) -> None:
        """matches_binary returns False for analog select."""
        select = SelectState(
            index=5,
            is_binary=False,
            analog_value=100.0,
        )
        assert not select.matches_binary(
            index=5,
            code=ControlCode.LATCH_ON,
            count=1,
            on_time=0,
            off_time=0,
        )

    def test_matches_analog_true(self) -> None:
        """matches_analog returns True for matching parameters."""
        select = SelectState(
            index=10,
            is_binary=False,
            analog_value=50.5,
        )
        assert select.matches_analog(index=10, value=50.5)

    def test_matches_analog_wrong_index(self) -> None:
        """matches_analog returns False for wrong index."""
        select = SelectState(
            index=10,
            is_binary=False,
            analog_value=50.5,
        )
        assert not select.matches_analog(index=11, value=50.5)

    def test_matches_analog_wrong_value(self) -> None:
        """matches_analog returns False for wrong value."""
        select = SelectState(
            index=10,
            is_binary=False,
            analog_value=50.5,
        )
        assert not select.matches_analog(index=10, value=50.6)

    def test_matches_analog_is_binary(self) -> None:
        """matches_analog returns False for binary select."""
        select = SelectState(
            index=10,
            is_binary=True,
            control_code=ControlCode.LATCH_ON,
        )
        assert not select.matches_analog(index=10, value=0.0)


class TestSequenceState:
    """Tests for SequenceState."""

    def test_default_values(self) -> None:
        """Default values are correct."""
        state = SequenceState()
        assert state.last_request_seq == -1
        assert state.last_response_seq == 0
        assert state.unsolicited_seq == 0

    def test_next_response_seq(self) -> None:
        """next_response_seq increments and wraps."""
        state = SequenceState()
        assert state.next_response_seq() == 0
        assert state.next_response_seq() == 1
        assert state.next_response_seq() == 2

    def test_next_response_seq_wraps(self) -> None:
        """next_response_seq wraps at 16."""
        state = SequenceState(last_response_seq=15)
        assert state.next_response_seq() == 15
        assert state.next_response_seq() == 0

    def test_next_unsolicited_seq(self) -> None:
        """next_unsolicited_seq increments and wraps."""
        state = SequenceState()
        assert state.next_unsolicited_seq() == 0
        assert state.next_unsolicited_seq() == 1
        assert state.next_unsolicited_seq() == 2

    def test_next_unsolicited_seq_wraps(self) -> None:
        """next_unsolicited_seq wraps at 16."""
        state = SequenceState(unsolicited_seq=15)
        assert state.next_unsolicited_seq() == 15
        assert state.next_unsolicited_seq() == 0


class TestUnsolicitedState:
    """Tests for UnsolicitedState."""

    def test_default_values(self) -> None:
        """Default values are correct."""
        state = UnsolicitedState()
        assert state.class_1_enabled is False
        assert state.class_2_enabled is False
        assert state.class_3_enabled is False
        assert state.startup_complete is False
        assert state.pending_confirm is False
        assert state.confirm_sequence == -1
        assert state.retry_count == 0

    def test_is_class_enabled(self) -> None:
        """is_class_enabled checks correct class."""
        state = UnsolicitedState(class_1_enabled=True)
        assert state.is_class_enabled(1) is True
        assert state.is_class_enabled(2) is False
        assert state.is_class_enabled(3) is False
        assert state.is_class_enabled(0) is False  # Invalid class

    def test_enable_class(self) -> None:
        """enable_class enables correct class."""
        state = UnsolicitedState()
        state.enable_class(1)
        assert state.class_1_enabled is True
        state.enable_class(2)
        assert state.class_2_enabled is True
        state.enable_class(3)
        assert state.class_3_enabled is True

    def test_disable_class(self) -> None:
        """disable_class disables correct class."""
        state = UnsolicitedState(class_1_enabled=True, class_2_enabled=True, class_3_enabled=True)
        state.disable_class(1)
        assert state.class_1_enabled is False
        state.disable_class(2)
        assert state.class_2_enabled is False
        state.disable_class(3)
        assert state.class_3_enabled is False


class TestOutstationStateManager:
    """Tests for OutstationStateManager."""

    def test_default_state(self) -> None:
        """Default state is IDLE with DEVICE_RESTART IIN."""
        manager = OutstationStateManager()
        assert manager.state == OutstationState.IDLE
        assert IIN.DEVICE_RESTART in manager.iin

    def test_set_restart(self) -> None:
        """set_restart sets DEVICE_RESTART IIN."""
        manager = OutstationStateManager(iin=IIN(0))
        manager.set_restart()
        assert IIN.DEVICE_RESTART in manager.iin

    def test_clear_restart(self) -> None:
        """clear_restart clears DEVICE_RESTART IIN."""
        manager = OutstationStateManager()
        manager.clear_restart()
        assert IIN.DEVICE_RESTART not in manager.iin

    def test_set_need_time(self) -> None:
        """set_need_time sets NEED_TIME IIN."""
        manager = OutstationStateManager(iin=IIN(0))
        manager.set_need_time()
        assert IIN.NEED_TIME in manager.iin
        assert manager.need_time is True

    def test_clear_need_time(self) -> None:
        """clear_need_time clears NEED_TIME IIN."""
        manager = OutstationStateManager()
        manager.set_need_time()
        manager.clear_need_time()
        assert IIN.NEED_TIME not in manager.iin
        assert manager.need_time is False

    def test_update_event_flags(self) -> None:
        """update_event_flags sets correct IIN bits."""
        manager = OutstationStateManager(iin=IIN(0))
        manager.update_event_flags(
            class_1_events=True,
            class_2_events=False,
            class_3_events=True,
        )
        assert IIN.CLASS_1_EVENTS in manager.iin
        assert IIN.CLASS_2_EVENTS not in manager.iin
        assert IIN.CLASS_3_EVENTS in manager.iin

    def test_update_event_flags_clears(self) -> None:
        """update_event_flags clears bits when False."""
        manager = OutstationStateManager(iin=IIN.CLASS_1_EVENTS | IIN.CLASS_2_EVENTS | IIN.CLASS_3_EVENTS)
        manager.update_event_flags(
            class_1_events=False,
            class_2_events=False,
            class_3_events=False,
        )
        assert IIN.CLASS_1_EVENTS not in manager.iin
        assert IIN.CLASS_2_EVENTS not in manager.iin
        assert IIN.CLASS_3_EVENTS not in manager.iin

    def test_set_event_overflow(self) -> None:
        """set_event_overflow sets EVENT_BUFFER_OVERFLOW IIN."""
        manager = OutstationStateManager(iin=IIN(0))
        manager.set_event_overflow()
        assert IIN.EVENT_BUFFER_OVERFLOW in manager.iin

    def test_clear_event_overflow(self) -> None:
        """clear_event_overflow clears EVENT_BUFFER_OVERFLOW IIN."""
        manager = OutstationStateManager(iin=IIN.EVENT_BUFFER_OVERFLOW)
        manager.clear_event_overflow()
        assert IIN.EVENT_BUFFER_OVERFLOW not in manager.iin

    def test_add_and_get_select(self) -> None:
        """Can add and retrieve SELECT state."""
        manager = OutstationStateManager()
        select = SelectState(index=5, is_binary=True)
        manager.add_select(select)
        retrieved = manager.get_select(5)
        assert retrieved is select

    def test_get_select_not_found(self) -> None:
        """get_select returns None for unknown index."""
        manager = OutstationStateManager()
        assert manager.get_select(5) is None

    def test_remove_select(self) -> None:
        """remove_select removes SELECT state."""
        manager = OutstationStateManager()
        select = SelectState(index=5, is_binary=True)
        manager.add_select(select)
        manager.remove_select(5)
        assert manager.get_select(5) is None

    def test_remove_select_not_found(self) -> None:
        """remove_select is no-op for unknown index."""
        manager = OutstationStateManager()
        manager.remove_select(5)  # Should not raise

    def test_clear_expired_selects(self) -> None:
        """clear_expired_selects removes expired selections."""
        manager = OutstationStateManager()
        # Add an expired select
        expired = SelectState(
            index=5,
            is_binary=True,
            timestamp=time.monotonic() - 20.0,
        )
        # Add a non-expired select
        active = SelectState(
            index=10,
            is_binary=True,
            timestamp=time.monotonic(),
        )
        manager.add_select(expired)
        manager.add_select(active)

        manager.clear_expired_selects(timeout=10.0)

        assert manager.get_select(5) is None  # Expired, removed
        assert manager.get_select(10) is active  # Not expired, kept

    def test_get_current_iin(self) -> None:
        """get_current_iin returns current IIN."""
        manager = OutstationStateManager(iin=IIN.DEVICE_RESTART | IIN.NEED_TIME)
        iin = manager.get_current_iin()
        assert IIN.DEVICE_RESTART in iin
        assert IIN.NEED_TIME in iin

    def test_set_error_iin(self) -> None:
        """set_error_iin sets error IIN flag."""
        manager = OutstationStateManager(iin=IIN(0))
        manager.set_error_iin(IIN.PARAMETER_ERROR)
        assert IIN.PARAMETER_ERROR in manager.iin

    def test_clear_error_iin(self) -> None:
        """clear_error_iin clears error IIN flag."""
        manager = OutstationStateManager(iin=IIN.PARAMETER_ERROR)
        manager.clear_error_iin(IIN.PARAMETER_ERROR)
        assert IIN.PARAMETER_ERROR not in manager.iin

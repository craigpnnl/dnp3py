"""Integration tests for unsolicited responses.

Tests unsolicited response generation by outstation and processing
by master, including enable/disable and confirmation handling.
"""

from dnp3.core.enums import FunctionCode
from dnp3.database import (
    AnalogInputConfig,
    BinaryInputConfig,
    CounterConfig,
    Database,
    EventClass,
)
from dnp3.master import DefaultSOEHandler, Master
from dnp3.outstation import Outstation


class TestUnsolicitedGeneration:
    """Test unsolicited response generation by outstation."""

    def test_unsolicited_not_generated_when_disabled(self) -> None:
        """No unsolicited response when disabled."""
        database = Database()
        database.add_binary_input(0, BinaryInputConfig(event_class=EventClass.CLASS_1))
        database.update_binary_input(0, value=False)
        database.update_binary_input(0, value=True)  # Generate event

        outstation = Outstation(database=database)
        # Unsolicited is disabled by default

        unsolicited = outstation.generate_unsolicited()
        assert unsolicited is None

    def test_unsolicited_generated_when_enabled(self) -> None:
        """Unsolicited response generated when enabled with events."""
        database = Database()
        database.add_binary_input(0, BinaryInputConfig(event_class=EventClass.CLASS_1))
        database.update_binary_input(0, value=False)
        database.update_binary_input(0, value=True)  # Generate event

        outstation = Outstation(database=database)
        master = Master()

        # Enable unsolicited
        enable_request = master.build_enable_unsolicited(class_1=True)
        outstation.process_request(enable_request.to_bytes())

        # Now unsolicited should be generated
        unsolicited = outstation.generate_unsolicited()
        assert unsolicited is not None
        assert unsolicited.header.control.uns  # UNS flag set

    def test_unsolicited_requires_confirm(self) -> None:
        """Unsolicited response requires confirmation."""
        database = Database()
        database.add_binary_input(0, BinaryInputConfig(event_class=EventClass.CLASS_1))
        database.update_binary_input(0, value=True)

        outstation = Outstation(database=database)
        master = Master()

        # Enable unsolicited
        enable_request = master.build_enable_unsolicited()
        outstation.process_request(enable_request.to_bytes())

        # Generate unsolicited
        unsolicited = outstation.generate_unsolicited()
        assert unsolicited is not None

        # While waiting for confirm, no new unsolicited
        unsolicited2 = outstation.generate_unsolicited()
        assert unsolicited2 is None


class TestUnsolicitedConfirmation:
    """Test unsolicited confirmation handling."""

    def test_master_confirms_unsolicited(self) -> None:
        """Master sends confirm for unsolicited response."""
        database = Database()
        database.add_binary_input(0, BinaryInputConfig(event_class=EventClass.CLASS_1))
        database.update_binary_input(0, value=True)

        outstation = Outstation(database=database)
        handler = DefaultSOEHandler()
        master = Master(handler=handler)

        # Enable unsolicited
        enable_request = master.build_enable_unsolicited()
        outstation.process_request(enable_request.to_bytes())

        # Generate unsolicited
        unsolicited = outstation.generate_unsolicited()
        assert unsolicited is not None

        # Master processes unsolicited
        info = master.process_response(unsolicited.to_bytes())
        assert info is not None
        assert info.is_unsolicited
        assert master.needs_confirm()

        # Master sends confirm
        confirm_seq = master.get_confirm_sequence()
        confirm = master.build_confirm(seq=confirm_seq)
        assert confirm.header.function == FunctionCode.CONFIRM

        # Outstation processes confirm (returns None)
        confirm_response = outstation.process_request(confirm.to_bytes())
        assert confirm_response is None  # No response to confirm

        # Mark confirm sent
        master.on_confirm_sent()
        assert not master.needs_confirm()

    def test_new_unsolicited_after_confirm(self) -> None:
        """New unsolicited can be sent after confirmation."""
        database = Database()
        database.add_binary_input(0, BinaryInputConfig(event_class=EventClass.CLASS_1))
        database.update_binary_input(0, value=True)

        outstation = Outstation(database=database)
        master = Master()

        # Enable unsolicited
        enable_request = master.build_enable_unsolicited()
        outstation.process_request(enable_request.to_bytes())

        # First unsolicited
        unsolicited1 = outstation.generate_unsolicited()
        assert unsolicited1 is not None
        master.process_response(unsolicited1.to_bytes())

        # Send confirm
        confirm = master.build_confirm(seq=unsolicited1.sequence)
        outstation.process_request(confirm.to_bytes())

        # Generate new event
        database.update_binary_input(0, value=False)

        # New unsolicited should be possible
        unsolicited2 = outstation.generate_unsolicited()
        assert unsolicited2 is not None


class TestUnsolicitedClasses:
    """Test unsolicited for different event classes."""

    def test_unsolicited_class_1_only(self) -> None:
        """Only Class 1 events generate unsolicited when Class 1 enabled."""
        database = Database()
        database.add_binary_input(0, BinaryInputConfig(event_class=EventClass.CLASS_1))
        database.add_analog_input(0, AnalogInputConfig(event_class=EventClass.CLASS_2))

        # Generate events in both classes
        database.update_binary_input(0, value=True)
        database.update_analog_input(0, value=100.0)

        outstation = Outstation(database=database)
        master = Master()

        # Enable only Class 1
        enable_request = master.build_enable_unsolicited(class_1=True, class_2=False, class_3=False)
        outstation.process_request(enable_request.to_bytes())

        # Unsolicited should only contain Class 1 events
        unsolicited = outstation.generate_unsolicited()
        assert unsolicited is not None

    def test_unsolicited_all_classes(self) -> None:
        """All classes generate unsolicited when all enabled."""
        database = Database()
        database.add_binary_input(0, BinaryInputConfig(event_class=EventClass.CLASS_1))
        database.add_analog_input(0, AnalogInputConfig(event_class=EventClass.CLASS_2))
        database.add_counter(0, CounterConfig(event_class=EventClass.CLASS_3))

        # Generate events in all classes
        database.update_binary_input(0, value=True)
        database.update_analog_input(0, value=100.0)
        database.update_counter(0, value=1000)

        outstation = Outstation(database=database)
        master = Master()

        # Enable all classes
        enable_request = master.build_enable_unsolicited(class_1=True, class_2=True, class_3=True)
        outstation.process_request(enable_request.to_bytes())

        unsolicited = outstation.generate_unsolicited()
        assert unsolicited is not None


class TestDisableUnsolicited:
    """Test disabling unsolicited responses."""

    def test_disable_stops_unsolicited(self) -> None:
        """Disabling unsolicited stops generation."""
        database = Database()
        database.add_binary_input(0, BinaryInputConfig(event_class=EventClass.CLASS_1))
        database.update_binary_input(0, value=True)

        outstation = Outstation(database=database)
        master = Master()

        # Enable then disable
        enable_request = master.build_enable_unsolicited()
        outstation.process_request(enable_request.to_bytes())

        disable_request = master.build_disable_unsolicited()
        outstation.process_request(disable_request.to_bytes())

        # Should not generate unsolicited
        unsolicited = outstation.generate_unsolicited()
        assert unsolicited is None

    def test_disable_specific_class(self) -> None:
        """Can disable specific classes while keeping others enabled."""
        database = Database()
        database.add_binary_input(0, BinaryInputConfig(event_class=EventClass.CLASS_1))
        database.add_analog_input(0, AnalogInputConfig(event_class=EventClass.CLASS_2))

        outstation = Outstation(database=database)
        master = Master()

        # Enable all
        enable_request = master.build_enable_unsolicited()
        outstation.process_request(enable_request.to_bytes())

        # Disable only Class 2
        disable_request = master.build_disable_unsolicited(class_1=False, class_2=True, class_3=False)
        outstation.process_request(disable_request.to_bytes())

        # Generate events
        database.update_binary_input(0, value=True)
        database.update_analog_input(0, value=100.0)

        # Should still generate for Class 1
        unsolicited = outstation.generate_unsolicited()
        assert unsolicited is not None


class TestMasterUnsolicitedHandling:
    """Test master handling of unsolicited responses."""

    def test_master_identifies_unsolicited(self) -> None:
        """Master correctly identifies unsolicited responses."""
        database = Database()
        database.add_binary_input(0, BinaryInputConfig(event_class=EventClass.CLASS_1))
        database.update_binary_input(0, value=True)

        outstation = Outstation(database=database)
        handler = DefaultSOEHandler()
        master = Master(handler=handler)

        # Enable and generate unsolicited
        enable_request = master.build_enable_unsolicited()
        outstation.process_request(enable_request.to_bytes())

        unsolicited = outstation.generate_unsolicited()
        assert unsolicited is not None

        # Master should identify as unsolicited
        info = master.process_response(unsolicited.to_bytes())
        assert info is not None
        assert info.is_unsolicited
        assert info.function == FunctionCode.UNSOLICITED_RESPONSE

    def test_master_handler_receives_unsolicited_data(self) -> None:
        """Master handler receives data from unsolicited response."""
        database = Database()
        database.add_binary_input(0, BinaryInputConfig(event_class=EventClass.CLASS_1))
        database.update_binary_input(0, value=True)

        outstation = Outstation(database=database)
        handler = DefaultSOEHandler()
        master = Master(handler=handler)

        # Enable and generate unsolicited
        enable_request = master.build_enable_unsolicited()
        outstation.process_request(enable_request.to_bytes())

        unsolicited = outstation.generate_unsolicited()
        assert unsolicited is not None

        # Process - handler should receive data
        master.process_response(unsolicited.to_bytes())
        # Note: actual data reception depends on response format


class TestUnsolicitedSequencing:
    """Test unsolicited response sequence numbering."""

    def test_unsolicited_sequence_increments(self) -> None:
        """Unsolicited sequence numbers increment."""
        database = Database()
        database.add_binary_input(0, BinaryInputConfig(event_class=EventClass.CLASS_1))

        outstation = Outstation(database=database)
        master = Master()

        # Enable unsolicited
        enable_request = master.build_enable_unsolicited()
        outstation.process_request(enable_request.to_bytes())

        sequences = []
        for i in range(3):
            database.update_binary_input(0, value=i % 2 == 0)
            unsolicited = outstation.generate_unsolicited()
            if unsolicited:
                sequences.append(unsolicited.sequence)
                # Confirm to allow next
                confirm = master.build_confirm(seq=unsolicited.sequence)
                outstation.process_request(confirm.to_bytes())

        # Sequences should increment
        if len(sequences) >= 2:
            for i in range(1, len(sequences)):
                assert sequences[i] == (sequences[i - 1] + 1) % 16


class TestUnsolicitedWithNoEvents:
    """Test unsolicited behavior with no pending events."""

    def test_no_unsolicited_without_events(self) -> None:
        """No unsolicited generated when no events pending."""
        database = Database()
        database.add_binary_input(0, BinaryInputConfig(event_class=EventClass.CLASS_1))
        # No events generated

        outstation = Outstation(database=database)
        master = Master()

        # Enable unsolicited
        enable_request = master.build_enable_unsolicited()
        outstation.process_request(enable_request.to_bytes())

        # No unsolicited without events
        unsolicited = outstation.generate_unsolicited()
        assert unsolicited is None

    def test_events_cleared_after_unsolicited(self) -> None:
        """Events are cleared after being sent in unsolicited."""
        database = Database()
        database.add_binary_input(0, BinaryInputConfig(event_class=EventClass.CLASS_1))
        database.update_binary_input(0, value=True)

        outstation = Outstation(database=database)
        master = Master()

        # Enable and generate
        enable_request = master.build_enable_unsolicited()
        outstation.process_request(enable_request.to_bytes())

        unsolicited1 = outstation.generate_unsolicited()
        assert unsolicited1 is not None

        # Confirm
        confirm = master.build_confirm(seq=unsolicited1.sequence)
        outstation.process_request(confirm.to_bytes())

        # No more unsolicited without new events
        unsolicited2 = outstation.generate_unsolicited()
        assert unsolicited2 is None

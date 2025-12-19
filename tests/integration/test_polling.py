"""Integration tests for polling workflows.

Tests various polling operations between master and outstation,
including class polls, range polls, and event handling.
"""

from dnp3.core.enums import FunctionCode
from dnp3.database import (
    AnalogInputConfig,
    BinaryInputConfig,
    CounterConfig,
    Database,
    EventClass,
)
from dnp3.master import DefaultSOEHandler, Master, MasterConfig, PollingConfig
from dnp3.master.polling import create_class_poll, create_integrity_poll
from dnp3.outstation import Outstation


class TestClassPolling:
    """Test class-based polling operations."""

    def test_class_1_poll(self) -> None:
        """Class 1 poll returns class 1 events."""
        database = Database()
        database.add_binary_input(0, BinaryInputConfig(event_class=EventClass.CLASS_1))
        database.update_binary_input(0, value=False)
        database.update_binary_input(0, value=True)  # Generate event

        outstation = Outstation(database=database)
        handler = DefaultSOEHandler()
        master = Master(handler=handler)

        request = master.build_class_poll(class_1=True, class_2=False, class_3=False)
        response = outstation.process_request(request.to_bytes())
        assert response is not None

        info = master.process_response(response.to_bytes())
        assert info is not None
        assert info.function == FunctionCode.RESPONSE

    def test_class_2_poll(self) -> None:
        """Class 2 poll returns class 2 events."""
        database = Database()
        database.add_analog_input(0, AnalogInputConfig(event_class=EventClass.CLASS_2))
        database.update_analog_input(0, value=0.0)
        database.update_analog_input(0, value=100.0)  # Generate event

        outstation = Outstation(database=database)
        handler = DefaultSOEHandler()
        master = Master(handler=handler)

        request = master.build_class_poll(class_1=False, class_2=True, class_3=False)
        response = outstation.process_request(request.to_bytes())
        assert response is not None

        info = master.process_response(response.to_bytes())
        assert info is not None

    def test_class_3_poll(self) -> None:
        """Class 3 poll returns class 3 events."""
        database = Database()
        database.add_counter(0, CounterConfig(event_class=EventClass.CLASS_3))
        database.update_counter(0, value=0)
        database.update_counter(0, value=100)  # Generate event

        outstation = Outstation(database=database)
        handler = DefaultSOEHandler()
        master = Master(handler=handler)

        request = master.build_class_poll(class_1=False, class_2=False, class_3=True)
        response = outstation.process_request(request.to_bytes())
        assert response is not None

        info = master.process_response(response.to_bytes())
        assert info is not None

    def test_all_classes_poll(self) -> None:
        """Poll for all event classes at once."""
        database = Database()
        database.add_binary_input(0, BinaryInputConfig(event_class=EventClass.CLASS_1))
        database.add_analog_input(0, AnalogInputConfig(event_class=EventClass.CLASS_2))
        database.add_counter(0, CounterConfig(event_class=EventClass.CLASS_3))

        # Generate events
        database.update_binary_input(0, value=False)
        database.update_binary_input(0, value=True)
        database.update_analog_input(0, value=50.0)
        database.update_counter(0, value=1000)

        outstation = Outstation(database=database)
        handler = DefaultSOEHandler()
        master = Master(handler=handler)

        request = master.build_class_poll(class_1=True, class_2=True, class_3=True)
        response = outstation.process_request(request.to_bytes())
        assert response is not None

        info = master.process_response(response.to_bytes())
        assert info is not None


class TestEventClearing:
    """Test event clearing after polling."""

    def test_events_cleared_after_poll(self) -> None:
        """Events are cleared from buffer after being polled."""
        database = Database()
        database.add_binary_input(0, BinaryInputConfig(event_class=EventClass.CLASS_1))
        database.update_binary_input(0, value=False)
        database.update_binary_input(0, value=True)  # Generate event

        outstation = Outstation(database=database)
        master = Master()

        # First poll - should get event
        request1 = master.build_class_poll(class_1=True, class_2=False, class_3=False)
        response1 = outstation.process_request(request1.to_bytes())
        assert response1 is not None

        # Second poll - event should be cleared
        request2 = master.build_class_poll(class_1=True, class_2=False, class_3=False)
        response2 = outstation.process_request(request2.to_bytes())
        assert response2 is not None

        # Check that event buffer is empty
        assert database.event_buffer.class1.count == 0

    def test_new_events_after_poll(self) -> None:
        """New events generated after poll are available in next poll."""
        database = Database()
        database.add_binary_input(0, BinaryInputConfig(event_class=EventClass.CLASS_1))
        database.update_binary_input(0, value=False)
        database.update_binary_input(0, value=True)

        outstation = Outstation(database=database)
        handler = DefaultSOEHandler()
        master = Master(handler=handler)

        # First poll clears the event
        request1 = master.build_class_poll(class_1=True, class_2=False, class_3=False)
        response1 = outstation.process_request(request1.to_bytes())
        assert response1 is not None
        master.process_response(response1.to_bytes())

        # Generate new event
        database.update_binary_input(0, value=False)

        # Second poll should get new event
        handler.binary_inputs.clear()
        request2 = master.build_class_poll(class_1=True, class_2=False, class_3=False)
        response2 = outstation.process_request(request2.to_bytes())
        assert response2 is not None
        master.process_response(response2.to_bytes())


class TestPollScheduler:
    """Test poll scheduler integration."""

    def test_scheduler_with_integrity_poll(self) -> None:
        """Poll scheduler manages integrity polls."""
        database = Database()
        database.add_binary_input(0, BinaryInputConfig())
        database.update_binary_input(0, value=True)

        outstation = Outstation(database=database)

        # Create master with polling config
        polling_config = PollingConfig(integrity_poll_interval=0.0)  # Disabled
        config = MasterConfig(polling=polling_config)
        master = Master(config=config)

        # Add manual poll task
        poll_task = create_integrity_poll(interval=0.0)  # One-shot
        master.scheduler.add_task(poll_task)

        # Get next poll
        next_poll = master.get_next_poll()
        assert next_poll is not None
        assert next_poll is poll_task

        # Execute poll
        request = next_poll.build_request(seq=0)
        response = outstation.process_request(request.to_bytes())
        assert response is not None

        master.mark_poll_executed(poll_task)
        assert poll_task.last_poll_time > 0

    def test_scheduler_priority(self) -> None:
        """Poll scheduler respects priority (integrity > class)."""
        master = Master()
        master.scheduler.clear()  # Clear default polls

        class_poll = create_class_poll(class_1=True, interval=0.0)
        integrity_poll = create_integrity_poll(interval=0.0)

        # Add class poll first, then integrity
        master.scheduler.add_task(class_poll)
        master.scheduler.add_task(integrity_poll)

        # Integrity should be returned first despite order
        next_poll = master.get_next_poll()
        assert next_poll is integrity_poll


class TestRangePolling:
    """Test range-based polling operations."""

    def test_range_poll_binary_inputs(self) -> None:
        """Range poll for specific binary inputs."""
        database = Database()
        for i in range(10):
            database.add_binary_input(i, BinaryInputConfig())
            database.update_binary_input(i, value=i % 2 == 0)

        outstation = Outstation(database=database)
        handler = DefaultSOEHandler()
        master = Master(handler=handler)

        # Poll only indices 2-5
        request = master.build_range_poll(group=1, variation=2, start=2, stop=5)
        response = outstation.process_request(request.to_bytes())
        assert response is not None

        info = master.process_response(response.to_bytes())
        assert info is not None

    def test_range_poll_analog_inputs(self) -> None:
        """Range poll for specific analog inputs."""
        database = Database()
        for i in range(10):
            database.add_analog_input(i, AnalogInputConfig())
            database.update_analog_input(i, value=float(i * 10))

        outstation = Outstation(database=database)
        handler = DefaultSOEHandler()
        master = Master(handler=handler)

        request = master.build_range_poll(group=30, variation=1, start=0, stop=4)
        response = outstation.process_request(request.to_bytes())
        assert response is not None

        info = master.process_response(response.to_bytes())
        assert info is not None


class TestMultiplePointTypes:
    """Test polling with multiple point types configured."""

    def test_mixed_point_types_integrity(self) -> None:
        """Integrity poll with multiple point types."""
        database = Database()

        # Add various point types
        for i in range(3):
            database.add_binary_input(i, BinaryInputConfig(event_class=EventClass.CLASS_1))
            database.add_analog_input(i, AnalogInputConfig(event_class=EventClass.CLASS_2))
            database.add_counter(i, CounterConfig(event_class=EventClass.CLASS_3))

        # Update all points
        for i in range(3):
            database.update_binary_input(i, value=i % 2 == 0)
            database.update_analog_input(i, value=float(i * 100))
            database.update_counter(i, value=i * 1000)

        outstation = Outstation(database=database)
        handler = DefaultSOEHandler()
        master = Master(handler=handler)

        request = master.build_integrity_poll()
        response = outstation.process_request(request.to_bytes())
        assert response is not None

        info = master.process_response(response.to_bytes())
        assert info is not None
        assert info.function == FunctionCode.RESPONSE

        # Verify response contains data objects
        assert len(response.objects) > 0

    def test_high_index_points(self) -> None:
        """Polling works with high index points."""
        database = Database()
        database.add_binary_input(1000, BinaryInputConfig())
        database.update_binary_input(1000, value=True)

        outstation = Outstation(database=database)
        handler = DefaultSOEHandler()
        master = Master(handler=handler)

        request = master.build_integrity_poll()
        response = outstation.process_request(request.to_bytes())
        assert response is not None

        info = master.process_response(response.to_bytes())
        assert info is not None


class TestPollTaskExecution:
    """Test poll task building and execution."""

    def test_integrity_poll_task_builds_correct_request(self) -> None:
        """IntegrityPollTask builds correct read request."""
        poll_task = create_integrity_poll()
        request = poll_task.build_request(seq=5)

        assert request.header.function == FunctionCode.READ
        assert request.header.control.seq == 5
        assert len(request.objects) == 4  # Class 1, 2, 3, 0

    def test_class_poll_task_builds_correct_request(self) -> None:
        """ClassPollTask builds correct read request."""
        poll_task = create_class_poll(class_1=True, class_2=True, class_3=False)
        request = poll_task.build_request(seq=3)

        assert request.header.function == FunctionCode.READ
        assert request.header.control.seq == 3
        assert len(request.objects) == 2  # Class 1 and 2 only

    def test_poll_task_timing(self) -> None:
        """Poll task timing works correctly."""
        poll_task = create_integrity_poll(interval=0.0)

        # Initially due (one-shot)
        assert poll_task.is_due()

        # After execution, one-shot is no longer due
        poll_task.mark_executed()
        assert not poll_task.is_due()

        # Reset makes it due again
        poll_task.reset()
        assert poll_task.is_due()

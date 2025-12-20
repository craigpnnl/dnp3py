"""Tests for polling operations."""

from unittest.mock import patch

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from dnp3.core.enums import FunctionCode
from dnp3.master.polling import (
    ClassPollTask,
    IntegrityPollTask,
    PollScheduler,
    PollTask,
    PollType,
    RangePollTask,
    create_class_poll,
    create_integrity_poll,
    create_range_poll,
)


class TestPollType:
    """Tests for PollType enum."""

    def test_poll_types_exist(self) -> None:
        """Test all expected poll types exist."""
        assert PollType.INTEGRITY is not None
        assert PollType.CLASS_0 is not None
        assert PollType.CLASS_1 is not None
        assert PollType.CLASS_2 is not None
        assert PollType.CLASS_3 is not None
        assert PollType.RANGE is not None

    def test_poll_types_are_distinct(self) -> None:
        """Test poll types are distinct values."""
        types = [
            PollType.INTEGRITY,
            PollType.CLASS_0,
            PollType.CLASS_1,
            PollType.CLASS_2,
            PollType.CLASS_3,
            PollType.RANGE,
        ]
        assert len(set(types)) == 6


class TestIntegrityPollTask:
    """Tests for IntegrityPollTask."""

    def test_creation(self) -> None:
        """Test creating integrity poll task."""
        task = IntegrityPollTask()

        assert task.poll_type == PollType.INTEGRITY
        assert task.interval == 0.0
        assert task.last_poll_time == 0.0
        assert task.enabled is True

    def test_with_interval(self) -> None:
        """Test integrity poll with interval."""
        task = IntegrityPollTask(interval=3600.0)

        assert task.interval == 3600.0

    def test_build_request(self) -> None:
        """Test building integrity poll request."""
        task = IntegrityPollTask()

        fragment = task.build_request(seq=5)

        assert fragment.header.function == FunctionCode.READ
        assert fragment.header.control.seq == 5

    def test_is_due_one_shot(self) -> None:
        """Test is_due for one-shot poll (interval=0)."""
        task = IntegrityPollTask(interval=0.0)

        # First time should be due
        assert task.is_due() is True

        task.mark_executed()
        # After execution, one-shot is not due again
        assert task.is_due() is False

    def test_is_due_periodic(self) -> None:
        """Test is_due for periodic poll."""
        task = IntegrityPollTask(interval=10.0)

        with patch("time.monotonic", return_value=1000.0):
            task.mark_executed()

        with patch("time.monotonic", return_value=1005.0):
            # 5 seconds elapsed, interval is 10
            assert task.is_due() is False

        with patch("time.monotonic", return_value=1010.0):
            # 10 seconds elapsed
            assert task.is_due() is True

    def test_is_due_when_disabled(self) -> None:
        """Test is_due when poll is disabled."""
        task = IntegrityPollTask(interval=10.0)
        task.enabled = False

        assert task.is_due() is False

    def test_mark_executed(self) -> None:
        """Test marking poll as executed."""
        task = IntegrityPollTask()

        with patch("time.monotonic", return_value=1000.0):
            task.mark_executed()

        assert task.last_poll_time == 1000.0

    def test_reset(self) -> None:
        """Test resetting poll timing."""
        task = IntegrityPollTask()

        with patch("time.monotonic", return_value=1000.0):
            task.mark_executed()

        assert task.last_poll_time == 1000.0

        task.reset()
        assert task.last_poll_time == 0.0


class TestClassPollTask:
    """Tests for ClassPollTask."""

    def test_creation_default(self) -> None:
        """Test creating class poll task with defaults."""
        task = ClassPollTask()

        assert task.class_1 is False
        assert task.class_2 is False
        assert task.class_3 is False
        assert task.interval == 0.0
        assert task.enabled is True

    def test_class_1_only(self) -> None:
        """Test class 1 poll task."""
        task = ClassPollTask(class_1=True)

        assert task.poll_type == PollType.CLASS_1
        assert task.class_1 is True

    def test_class_2_only(self) -> None:
        """Test class 2 poll task."""
        task = ClassPollTask(class_2=True)

        assert task.poll_type == PollType.CLASS_2
        assert task.class_2 is True

    def test_class_3_only(self) -> None:
        """Test class 3 poll task."""
        task = ClassPollTask(class_3=True)

        assert task.poll_type == PollType.CLASS_3
        assert task.class_3 is True

    def test_multiple_classes(self) -> None:
        """Test poll with multiple classes."""
        task = ClassPollTask(class_1=True, class_2=True, class_3=True)

        assert task.class_1 is True
        assert task.class_2 is True
        assert task.class_3 is True
        # Poll type is CLASS_1 (default) when multiple specified
        assert task.poll_type == PollType.CLASS_1

    def test_build_request(self) -> None:
        """Test building class poll request."""
        task = ClassPollTask(class_1=True, class_2=True)

        fragment = task.build_request(seq=3)

        assert fragment.header.function == FunctionCode.READ
        assert fragment.header.control.seq == 3

    def test_is_due(self) -> None:
        """Test is_due for class poll."""
        task = ClassPollTask(class_1=True, interval=5.0)

        with patch("time.monotonic", return_value=1000.0):
            task.mark_executed()

        with patch("time.monotonic", return_value=1003.0):
            assert task.is_due() is False

        with patch("time.monotonic", return_value=1005.0):
            assert task.is_due() is True


class TestRangePollTask:
    """Tests for RangePollTask."""

    def test_creation(self) -> None:
        """Test creating range poll task."""
        task = RangePollTask(group=1, variation=2, start=0, stop=10)

        assert task.poll_type == PollType.RANGE
        assert task.group == 1
        assert task.variation == 2
        assert task.start == 0
        assert task.stop == 10
        assert task.interval == 0.0

    def test_with_interval(self) -> None:
        """Test range poll with interval."""
        task = RangePollTask(group=30, variation=1, start=0, stop=5, interval=30.0)

        assert task.interval == 30.0

    def test_build_request_small_range(self) -> None:
        """Test building request for small range (1-byte indices)."""
        task = RangePollTask(group=1, variation=2, start=0, stop=100)

        fragment = task.build_request(seq=1)

        assert fragment.header.function == FunctionCode.READ
        assert fragment.header.control.seq == 1

    def test_build_request_medium_range(self) -> None:
        """Test building request for medium range (2-byte indices)."""
        task = RangePollTask(group=30, variation=1, start=0, stop=1000)

        fragment = task.build_request(seq=2)

        assert fragment.header.function == FunctionCode.READ

    def test_build_request_large_range(self) -> None:
        """Test building request for large range (4-byte indices)."""
        task = RangePollTask(group=30, variation=1, start=0, stop=100000)

        fragment = task.build_request(seq=3)

        assert fragment.header.function == FunctionCode.READ

    @given(
        group=st.integers(min_value=1, max_value=120),
        variation=st.integers(min_value=0, max_value=255),
        start=st.integers(min_value=0, max_value=255),
        stop=st.integers(min_value=0, max_value=255),
    )
    @settings(max_examples=50)
    def test_property_based_small_range(self, group: int, variation: int, start: int, stop: int) -> None:
        """Test range poll with various small ranges."""
        if start > stop:
            start, stop = stop, start

        task = RangePollTask(group=group, variation=variation, start=start, stop=stop)
        fragment = task.build_request()

        assert fragment.header.function == FunctionCode.READ


class TestPollScheduler:
    """Tests for PollScheduler."""

    def test_empty_scheduler(self) -> None:
        """Test empty scheduler."""
        scheduler = PollScheduler()

        assert scheduler.task_count == 0
        assert scheduler.get_due_tasks() == []
        assert scheduler.get_next_task() is None
        assert scheduler.get_time_until_next() is None

    def test_add_task(self) -> None:
        """Test adding tasks."""
        scheduler = PollScheduler()
        task1 = IntegrityPollTask()
        task2 = ClassPollTask(class_1=True)

        scheduler.add_task(task1)
        scheduler.add_task(task2)

        assert scheduler.task_count == 2

    def test_remove_task(self) -> None:
        """Test removing tasks."""
        scheduler = PollScheduler()
        task = IntegrityPollTask()

        scheduler.add_task(task)
        assert scheduler.task_count == 1

        scheduler.remove_task(task)
        assert scheduler.task_count == 0

    def test_remove_nonexistent_task(self) -> None:
        """Test removing task that doesn't exist."""
        scheduler = PollScheduler()
        task = IntegrityPollTask()

        # Should not raise
        scheduler.remove_task(task)
        assert scheduler.task_count == 0

    def test_get_due_tasks_all_due(self) -> None:
        """Test getting due tasks when all are due."""
        scheduler = PollScheduler()
        task1 = IntegrityPollTask(interval=0.0)  # One-shot, due immediately
        task2 = ClassPollTask(class_1=True, interval=0.0)  # One-shot

        scheduler.add_task(task1)
        scheduler.add_task(task2)

        due = scheduler.get_due_tasks()
        assert len(due) == 2
        assert task1 in due
        assert task2 in due

    def test_get_due_tasks_some_due(self) -> None:
        """Test getting due tasks when only some are due."""
        scheduler = PollScheduler()
        task1 = IntegrityPollTask(interval=0.0)  # One-shot, due immediately
        task2 = ClassPollTask(class_1=True, interval=10.0)

        scheduler.add_task(task1)
        scheduler.add_task(task2)

        with patch("time.monotonic", return_value=1000.0):
            task2.mark_executed()  # Mark task2 as recently executed

        with patch("time.monotonic", return_value=1005.0):
            due = scheduler.get_due_tasks()
            assert len(due) == 1
            assert task1 in due

    def test_get_next_task_priority(self) -> None:
        """Test next task prioritizes integrity polls."""
        scheduler = PollScheduler()

        # Add tasks in reverse priority order
        range_task = RangePollTask(group=1, variation=2, start=0, stop=10)
        class_3_task = ClassPollTask(class_3=True)
        class_2_task = ClassPollTask(class_2=True)
        class_1_task = ClassPollTask(class_1=True)
        integrity_task = IntegrityPollTask()

        scheduler.add_task(range_task)
        scheduler.add_task(class_3_task)
        scheduler.add_task(class_2_task)
        scheduler.add_task(class_1_task)
        scheduler.add_task(integrity_task)

        # Integrity should be selected first
        next_task = scheduler.get_next_task()
        assert next_task == integrity_task

    def test_get_next_task_class_priority(self) -> None:
        """Test class poll priority order."""
        scheduler = PollScheduler()

        class_3_task = ClassPollTask(class_3=True)
        class_2_task = ClassPollTask(class_2=True)
        class_1_task = ClassPollTask(class_1=True)

        scheduler.add_task(class_3_task)
        scheduler.add_task(class_2_task)
        scheduler.add_task(class_1_task)

        # Class 1 should be selected first
        next_task = scheduler.get_next_task()
        assert next_task == class_1_task

    def test_get_time_until_next_immediate(self) -> None:
        """Test time until next when task is due."""
        scheduler = PollScheduler()
        task = IntegrityPollTask(interval=10.0)

        scheduler.add_task(task)

        # Task hasn't been executed yet, should be due immediately
        with patch("time.monotonic", return_value=1000.0):
            task.mark_executed()

        with patch("time.monotonic", return_value=1010.0):
            time_until = scheduler.get_time_until_next()
            assert time_until == 0.0

    def test_get_time_until_next_future(self) -> None:
        """Test time until next when task is not due."""
        scheduler = PollScheduler()
        task = IntegrityPollTask(interval=10.0)

        scheduler.add_task(task)

        with patch("time.monotonic", return_value=1000.0):
            task.mark_executed()

        with patch("time.monotonic", return_value=1005.0):
            time_until = scheduler.get_time_until_next()
            assert time_until is not None
            assert time_until == pytest.approx(5.0, abs=0.1)

    def test_get_time_until_next_multiple_tasks(self) -> None:
        """Test time until next with multiple tasks."""
        scheduler = PollScheduler()
        task1 = IntegrityPollTask(interval=10.0)
        task2 = ClassPollTask(class_1=True, interval=5.0)

        scheduler.add_task(task1)
        scheduler.add_task(task2)

        with patch("time.monotonic", return_value=1000.0):
            task1.mark_executed()
            task2.mark_executed()

        with patch("time.monotonic", return_value=1003.0):
            # Task2 (interval=5) is closer than task1 (interval=10)
            time_until = scheduler.get_time_until_next()
            assert time_until is not None
            assert time_until == pytest.approx(2.0, abs=0.1)

    def test_get_time_until_next_only_one_shot(self) -> None:
        """Test time until next when only one-shot tasks."""
        scheduler = PollScheduler()
        task = IntegrityPollTask(interval=0.0)

        scheduler.add_task(task)
        task.mark_executed()  # Mark as executed

        # One-shot tasks (interval=0) don't affect time until next
        assert scheduler.get_time_until_next() is None

    def test_clear(self) -> None:
        """Test clearing all tasks."""
        scheduler = PollScheduler()
        scheduler.add_task(IntegrityPollTask())
        scheduler.add_task(ClassPollTask(class_1=True))

        assert scheduler.task_count == 2

        scheduler.clear()
        assert scheduler.task_count == 0

    def test_reset_all(self) -> None:
        """Test resetting all tasks."""
        scheduler = PollScheduler()
        task1 = IntegrityPollTask()
        task2 = ClassPollTask(class_1=True)

        scheduler.add_task(task1)
        scheduler.add_task(task2)

        with patch("time.monotonic", return_value=1000.0):
            task1.mark_executed()
            task2.mark_executed()

        assert task1.last_poll_time == 1000.0
        assert task2.last_poll_time == 1000.0

        scheduler.reset_all()

        assert task1.last_poll_time == 0.0
        assert task2.last_poll_time == 0.0


class TestHelperFunctions:
    """Tests for helper functions."""

    def test_create_integrity_poll(self) -> None:
        """Test create_integrity_poll helper."""
        task = create_integrity_poll(interval=1800.0)

        assert isinstance(task, IntegrityPollTask)
        assert task.interval == 1800.0

    def test_create_integrity_poll_default(self) -> None:
        """Test create_integrity_poll with default interval."""
        task = create_integrity_poll()

        assert task.interval == 3600.0

    def test_create_class_poll(self) -> None:
        """Test create_class_poll helper."""
        task = create_class_poll(
            class_1=True,
            class_2=True,
            class_3=False,
            interval=60.0,
        )

        assert isinstance(task, ClassPollTask)
        assert task.class_1 is True
        assert task.class_2 is True
        assert task.class_3 is False
        assert task.interval == 60.0

    def test_create_class_poll_defaults(self) -> None:
        """Test create_class_poll with defaults."""
        task = create_class_poll()

        assert task.class_1 is True
        assert task.class_2 is True
        assert task.class_3 is True
        assert task.interval == 0.0

    def test_create_range_poll(self) -> None:
        """Test create_range_poll helper."""
        task = create_range_poll(
            group=30,
            variation=1,
            start=0,
            stop=100,
            interval=30.0,
        )

        assert isinstance(task, RangePollTask)
        assert task.group == 30
        assert task.variation == 1
        assert task.start == 0
        assert task.stop == 100
        assert task.interval == 30.0

    def test_create_range_poll_no_interval(self) -> None:
        """Test create_range_poll without interval."""
        task = create_range_poll(group=1, variation=2, start=5, stop=15)

        assert task.interval == 0.0


class TestPollTaskPolymorphism:
    """Tests for PollTask base class behavior."""

    def test_all_tasks_have_build_request(self) -> None:
        """Test all task types have build_request method."""
        tasks: list[PollTask] = [
            IntegrityPollTask(),
            ClassPollTask(class_1=True),
            RangePollTask(group=1, variation=2, start=0, stop=10),
        ]

        for task in tasks:
            fragment = task.build_request()
            assert fragment.header.function == FunctionCode.READ

    def test_all_tasks_have_timing_methods(self) -> None:
        """Test all task types have timing methods."""
        tasks: list[PollTask] = [
            IntegrityPollTask(interval=10.0),
            ClassPollTask(class_1=True, interval=10.0),
            RangePollTask(group=1, variation=2, start=0, stop=10, interval=10.0),
        ]

        for task in tasks:
            # All should be due initially
            assert task.is_due() is True

            with patch("time.monotonic", return_value=1000.0):
                task.mark_executed()

            with patch("time.monotonic", return_value=1005.0):
                # Not due after 5 seconds
                assert task.is_due() is False

            task.reset()
            assert task.last_poll_time == 0.0

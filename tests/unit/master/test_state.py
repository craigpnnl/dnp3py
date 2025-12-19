"""Tests for master state machine."""

from unittest.mock import patch

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from dnp3.master.state import (
    MasterState,
    MasterStateManager,
    SequenceState,
    TaskInfo,
    TaskState,
    UnsolicitedState,
)


class TestMasterState:
    """Tests for MasterState enum."""

    def test_states_exist(self) -> None:
        """Test all expected states exist."""
        assert MasterState.IDLE is not None
        assert MasterState.WAITING_RESPONSE is not None
        assert MasterState.WAITING_CONFIRM is not None

    def test_states_are_distinct(self) -> None:
        """Test states are distinct values."""
        states = [MasterState.IDLE, MasterState.WAITING_RESPONSE, MasterState.WAITING_CONFIRM]
        assert len(set(states)) == 3


class TestTaskState:
    """Tests for TaskState enum."""

    def test_states_exist(self) -> None:
        """Test all expected states exist."""
        assert TaskState.PENDING is not None
        assert TaskState.RUNNING is not None
        assert TaskState.COMPLETED is not None
        assert TaskState.FAILED is not None
        assert TaskState.CANCELLED is not None

    def test_states_are_distinct(self) -> None:
        """Test states are distinct values."""
        states = [
            TaskState.PENDING,
            TaskState.RUNNING,
            TaskState.COMPLETED,
            TaskState.FAILED,
            TaskState.CANCELLED,
        ]
        assert len(set(states)) == 5


class TestSequenceState:
    """Tests for SequenceState."""

    def test_default_values(self) -> None:
        """Test default sequence state."""
        state = SequenceState()

        assert state.last_request_seq == 0
        assert state.expected_response_seq == 0

    def test_next_request_seq(self) -> None:
        """Test getting next request sequence."""
        state = SequenceState()

        # First sequence should be 0
        seq = state.next_request_seq()
        assert seq == 0
        assert state.last_request_seq == 1
        assert state.expected_response_seq == 0

    def test_sequence_wraps_at_16(self) -> None:
        """Test sequence wraps from 15 to 0."""
        state = SequenceState()
        state.last_request_seq = 15

        seq = state.next_request_seq()
        assert seq == 15
        assert state.last_request_seq == 0

    def test_validate_response_seq_correct(self) -> None:
        """Test validating correct response sequence."""
        state = SequenceState()

        seq = state.next_request_seq()
        assert state.validate_response_seq(seq) is True

    def test_validate_response_seq_incorrect(self) -> None:
        """Test validating incorrect response sequence."""
        state = SequenceState()

        state.next_request_seq()  # seq = 0
        assert state.validate_response_seq(1) is False
        assert state.validate_response_seq(15) is False

    @given(st.integers(min_value=0, max_value=100))
    def test_sequence_progression(self, num_requests: int) -> None:
        """Test sequence progression over multiple requests."""
        state = SequenceState()

        for i in range(num_requests):
            seq = state.next_request_seq()
            assert seq == i % 16
            assert state.expected_response_seq == seq


class TestTaskInfo:
    """Tests for TaskInfo."""

    def test_creation(self) -> None:
        """Test creating task info."""
        task = TaskInfo(task_id=1, task_type="poll")

        assert task.task_id == 1
        assert task.task_type == "poll"
        assert task.data is None
        assert task.state == TaskState.PENDING
        assert task.retry_count == 2
        assert task.start_time == 0.0
        assert task.timeout == 5.0

    def test_with_custom_values(self) -> None:
        """Test task with custom values."""
        task = TaskInfo(
            task_id=5,
            task_type="command",
            data={"index": 0},
            retry_count=3,
            timeout=10.0,
        )

        assert task.task_id == 5
        assert task.task_type == "command"
        assert task.data == {"index": 0}
        assert task.retry_count == 3
        assert task.timeout == 10.0

    def test_start(self) -> None:
        """Test starting a task."""
        task = TaskInfo(task_id=1, task_type="poll")

        with patch("time.monotonic", return_value=1000.0):
            task.start()

        assert task.state == TaskState.RUNNING
        assert task.start_time == 1000.0

    def test_complete(self) -> None:
        """Test completing a task."""
        task = TaskInfo(task_id=1, task_type="poll")
        task.start()
        task.complete()

        assert task.state == TaskState.COMPLETED

    def test_fail(self) -> None:
        """Test failing a task."""
        task = TaskInfo(task_id=1, task_type="poll")
        task.start()
        task.fail()

        assert task.state == TaskState.FAILED

    def test_cancel(self) -> None:
        """Test cancelling a task."""
        task = TaskInfo(task_id=1, task_type="poll")
        task.start()
        task.cancel()

        assert task.state == TaskState.CANCELLED

    def test_is_expired_when_not_running(self) -> None:
        """Test expired check when task is not running."""
        task = TaskInfo(task_id=1, task_type="poll", timeout=1.0)

        # Pending task is not expired
        assert task.is_expired() is False

        # Completed task is not expired
        task.state = TaskState.COMPLETED
        assert task.is_expired() is False

    def test_is_expired_when_running_not_timed_out(self) -> None:
        """Test expired check when running but not timed out."""
        task = TaskInfo(task_id=1, task_type="poll", timeout=10.0)

        with patch("time.monotonic", return_value=1000.0):
            task.start()

        with patch("time.monotonic", return_value=1005.0):
            # 5 seconds elapsed, timeout is 10 seconds
            assert task.is_expired() is False

    def test_is_expired_when_running_timed_out(self) -> None:
        """Test expired check when running and timed out."""
        task = TaskInfo(task_id=1, task_type="poll", timeout=5.0)

        with patch("time.monotonic", return_value=1000.0):
            task.start()

        with patch("time.monotonic", return_value=1006.0):
            # 6 seconds elapsed, timeout is 5 seconds
            assert task.is_expired() is True

    def test_can_retry_with_retries(self) -> None:
        """Test can_retry when retries remaining."""
        task = TaskInfo(task_id=1, task_type="poll", retry_count=2)

        assert task.can_retry() is True

    def test_can_retry_without_retries(self) -> None:
        """Test can_retry when no retries remaining."""
        task = TaskInfo(task_id=1, task_type="poll", retry_count=0)

        assert task.can_retry() is False

    def test_decrement_retry(self) -> None:
        """Test decrementing retry count."""
        task = TaskInfo(task_id=1, task_type="poll", retry_count=2)

        task.decrement_retry()
        assert task.retry_count == 1

        task.decrement_retry()
        assert task.retry_count == 0

        # Should not go negative
        task.decrement_retry()
        assert task.retry_count == 0


class TestUnsolicitedState:
    """Tests for UnsolicitedState."""

    def test_default_values(self) -> None:
        """Test default unsolicited state."""
        state = UnsolicitedState()

        assert state.enabled is True
        assert state.last_sequence == -1
        assert state.pending_confirm is False

    def test_custom_values(self) -> None:
        """Test custom unsolicited state."""
        state = UnsolicitedState(
            enabled=False,
            last_sequence=5,
            pending_confirm=True,
        )

        assert state.enabled is False
        assert state.last_sequence == 5
        assert state.pending_confirm is True


class TestMasterStateManager:
    """Tests for MasterStateManager."""

    def test_default_state(self) -> None:
        """Test default manager state."""
        manager = MasterStateManager()

        assert manager.state == MasterState.IDLE
        assert manager.is_idle is True
        assert manager.is_waiting_response is False
        assert manager.current_task is None

    def test_create_task(self) -> None:
        """Test creating a task."""
        manager = MasterStateManager()

        task = manager.create_task("poll", data={"type": "integrity"})

        assert task.task_id == 1
        assert task.task_type == "poll"
        assert task.data == {"type": "integrity"}
        assert task.state == TaskState.PENDING

    def test_create_task_increments_id(self) -> None:
        """Test task ID increments."""
        manager = MasterStateManager()

        task1 = manager.create_task("poll")
        task2 = manager.create_task("command")
        task3 = manager.create_task("poll")

        assert task1.task_id == 1
        assert task2.task_id == 2
        assert task3.task_id == 3

    def test_start_task(self) -> None:
        """Test starting a task."""
        manager = MasterStateManager()
        task = manager.create_task("poll")

        manager.start_task(task)

        assert task.state == TaskState.RUNNING
        assert manager.current_task == task
        assert manager.state == MasterState.WAITING_RESPONSE
        assert manager.is_idle is False
        assert manager.is_waiting_response is True

    def test_start_task_when_already_running(self) -> None:
        """Test starting task when another is running."""
        manager = MasterStateManager()
        task1 = manager.create_task("poll")
        task2 = manager.create_task("command")

        manager.start_task(task1)

        with pytest.raises(RuntimeError, match="Another task is already running"):
            manager.start_task(task2)

    def test_start_task_after_completion(self) -> None:
        """Test starting task after previous completes."""
        manager = MasterStateManager()
        task1 = manager.create_task("poll")
        task2 = manager.create_task("command")

        manager.start_task(task1)
        manager.complete_current_task()

        # Should be able to start new task
        manager.start_task(task2)
        assert manager.current_task == task2

    def test_complete_current_task(self) -> None:
        """Test completing current task."""
        manager = MasterStateManager()
        task = manager.create_task("poll")
        manager.start_task(task)

        manager.complete_current_task()

        assert task.state == TaskState.COMPLETED
        assert manager.state == MasterState.IDLE
        assert manager.is_idle is True

    def test_complete_when_no_task(self) -> None:
        """Test completing when no task running."""
        manager = MasterStateManager()

        # Should not raise, just set state to IDLE
        manager.complete_current_task()
        assert manager.state == MasterState.IDLE

    def test_fail_current_task(self) -> None:
        """Test failing current task."""
        manager = MasterStateManager()
        task = manager.create_task("poll")
        manager.start_task(task)

        manager.fail_current_task()

        assert task.state == TaskState.FAILED
        assert manager.state == MasterState.IDLE

    def test_cancel_current_task(self) -> None:
        """Test cancelling current task."""
        manager = MasterStateManager()
        task = manager.create_task("poll")
        manager.start_task(task)

        manager.cancel_current_task()

        assert task.state == TaskState.CANCELLED
        assert manager.state == MasterState.IDLE

    def test_check_task_timeout_no_task(self) -> None:
        """Test timeout check when no task."""
        manager = MasterStateManager()

        result = manager.check_task_timeout()

        assert result is False

    def test_check_task_timeout_not_expired(self) -> None:
        """Test timeout check when task not expired."""
        manager = MasterStateManager()
        task = manager.create_task("poll", timeout=10.0)

        with patch("time.monotonic", return_value=1000.0):
            manager.start_task(task)

        with patch("time.monotonic", return_value=1005.0):
            result = manager.check_task_timeout()

        assert result is False
        assert task.state == TaskState.RUNNING

    def test_check_task_timeout_expired_with_retry(self) -> None:
        """Test timeout check when expired with retries."""
        manager = MasterStateManager()
        task = manager.create_task("poll", timeout=5.0, retry_count=2)

        with patch("time.monotonic", return_value=1000.0):
            manager.start_task(task)

        with patch("time.monotonic", return_value=1006.0):
            result = manager.check_task_timeout()

        assert result is True
        assert task.state == TaskState.RUNNING  # Restarted
        assert task.retry_count == 1

    def test_check_task_timeout_expired_no_retry(self) -> None:
        """Test timeout check when expired without retries."""
        manager = MasterStateManager()
        task = manager.create_task("poll", timeout=5.0, retry_count=0)

        with patch("time.monotonic", return_value=1000.0):
            manager.start_task(task)

        with patch("time.monotonic", return_value=1006.0):
            result = manager.check_task_timeout()

        assert result is True
        assert task.state == TaskState.FAILED
        assert manager.state == MasterState.IDLE

    def test_unsolicited_received(self) -> None:
        """Test handling unsolicited response."""
        manager = MasterStateManager()

        manager.on_unsolicited_received(sequence=5)

        assert manager.unsolicited.last_sequence == 5
        assert manager.unsolicited.pending_confirm is True

    def test_unsolicited_confirmed(self) -> None:
        """Test handling unsolicited confirm."""
        manager = MasterStateManager()
        manager.on_unsolicited_received(sequence=5)

        manager.on_unsolicited_confirmed()

        assert manager.unsolicited.pending_confirm is False
        assert manager.unsolicited.last_sequence == 5  # Still remembers sequence

    def test_get_next_request_sequence(self) -> None:
        """Test getting next request sequence."""
        manager = MasterStateManager()

        seq1 = manager.get_next_request_sequence()
        seq2 = manager.get_next_request_sequence()
        seq3 = manager.get_next_request_sequence()

        assert seq1 == 0
        assert seq2 == 1
        assert seq3 == 2

    def test_validate_response_sequence(self) -> None:
        """Test validating response sequence."""
        manager = MasterStateManager()

        seq = manager.get_next_request_sequence()

        assert manager.validate_response_sequence(seq) is True
        assert manager.validate_response_sequence(seq + 1) is False

    @given(
        task_type=st.sampled_from(["poll", "command", "unsolicited"]),
        timeout=st.floats(min_value=0.1, max_value=60.0),
        retry_count=st.integers(min_value=0, max_value=5),
    )
    @settings(max_examples=50)
    def test_property_based_task_lifecycle(
        self,
        task_type: str,
        timeout: float,
        retry_count: int,
    ) -> None:
        """Test task lifecycle with various parameters."""
        manager = MasterStateManager()

        task = manager.create_task(
            task_type,
            timeout=timeout,
            retry_count=retry_count,
        )

        assert task.task_type == task_type
        assert task.timeout == timeout
        assert task.retry_count == retry_count

        manager.start_task(task)
        assert manager.is_waiting_response

        manager.complete_current_task()
        assert manager.is_idle
        assert task.state == TaskState.COMPLETED

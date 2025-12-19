"""Master state machine per IEEE 1815-2012.

Tracks master state including sequence numbers, pending tasks,
and communication state.
"""

import time
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any


class MasterState(Enum):
    """High-level master states."""

    IDLE = auto()  # No pending operations
    WAITING_RESPONSE = auto()  # Waiting for response to request
    WAITING_CONFIRM = auto()  # Waiting to send confirmation


class TaskState(Enum):
    """State of a task."""

    PENDING = auto()  # Not yet started
    RUNNING = auto()  # In progress
    COMPLETED = auto()  # Successfully completed
    FAILED = auto()  # Failed after retries
    CANCELLED = auto()  # Cancelled by user


@dataclass
class SequenceState:
    """Application layer sequence number tracking.

    Attributes:
        last_request_seq: Last request sequence sent.
        expected_response_seq: Expected response sequence.
    """

    last_request_seq: int = 0
    expected_response_seq: int = 0

    def next_request_seq(self) -> int:
        """Get next request sequence number.

        Returns:
            Next sequence number (0-15).
        """
        seq = self.last_request_seq
        self.last_request_seq = (self.last_request_seq + 1) % 16
        self.expected_response_seq = seq
        return seq

    def validate_response_seq(self, seq: int) -> bool:
        """Check if response sequence matches expected.

        Args:
            seq: Response sequence number.

        Returns:
            True if sequence matches expected.
        """
        return seq == self.expected_response_seq


@dataclass
class TaskInfo:
    """Information about a pending task.

    Attributes:
        task_id: Unique task identifier.
        task_type: Type of task (poll, command, etc.).
        data: Task-specific data.
        state: Current task state.
        retry_count: Number of retries remaining.
        start_time: When task started.
        timeout: Task timeout in seconds.
    """

    task_id: int
    task_type: str
    data: Any = None
    state: TaskState = TaskState.PENDING
    retry_count: int = 2
    start_time: float = 0.0
    timeout: float = 5.0

    def start(self) -> None:
        """Mark task as started."""
        self.state = TaskState.RUNNING
        self.start_time = time.monotonic()

    def complete(self) -> None:
        """Mark task as completed."""
        self.state = TaskState.COMPLETED

    def fail(self) -> None:
        """Mark task as failed."""
        self.state = TaskState.FAILED

    def cancel(self) -> None:
        """Mark task as cancelled."""
        self.state = TaskState.CANCELLED

    def is_expired(self) -> bool:
        """Check if task has timed out.

        Returns:
            True if task has exceeded timeout.
        """
        if self.state != TaskState.RUNNING:
            return False
        return time.monotonic() - self.start_time > self.timeout

    def can_retry(self) -> bool:
        """Check if task can be retried.

        Returns:
            True if retries remaining.
        """
        return self.retry_count > 0

    def decrement_retry(self) -> None:
        """Decrement retry count."""
        if self.retry_count > 0:
            self.retry_count -= 1


@dataclass
class UnsolicitedState:
    """State for unsolicited response handling.

    Attributes:
        enabled: Whether unsolicited is enabled.
        last_sequence: Last unsolicited sequence received.
        pending_confirm: True if we need to send a confirm.
    """

    enabled: bool = True
    last_sequence: int = -1
    pending_confirm: bool = False


@dataclass
class MasterStateManager:
    """Manages all master state.

    Combines sequence tracking, task management, and
    unsolicited response state.
    """

    state: MasterState = MasterState.IDLE
    sequences: SequenceState = field(default_factory=SequenceState)
    unsolicited: UnsolicitedState = field(default_factory=UnsolicitedState)
    _current_task: TaskInfo | None = field(default=None, init=False)
    _next_task_id: int = field(default=1, init=False)

    @property
    def current_task(self) -> TaskInfo | None:
        """Get the current task."""
        return self._current_task

    @property
    def is_idle(self) -> bool:
        """Check if master is idle."""
        return self.state == MasterState.IDLE

    @property
    def is_waiting_response(self) -> bool:
        """Check if waiting for response."""
        return self.state == MasterState.WAITING_RESPONSE

    def create_task(
        self,
        task_type: str,
        data: Any = None,
        retry_count: int = 2,
        timeout: float = 5.0,
    ) -> TaskInfo:
        """Create a new task.

        Args:
            task_type: Type of task.
            data: Task-specific data.
            retry_count: Number of retries.
            timeout: Task timeout in seconds.

        Returns:
            New TaskInfo instance.
        """
        task = TaskInfo(
            task_id=self._next_task_id,
            task_type=task_type,
            data=data,
            retry_count=retry_count,
            timeout=timeout,
        )
        self._next_task_id += 1
        return task

    def start_task(self, task: TaskInfo) -> None:
        """Start a task.

        Args:
            task: Task to start.

        Raises:
            RuntimeError: If another task is already running.
        """
        if self._current_task is not None and self._current_task.state == TaskState.RUNNING:
            msg = "Another task is already running"
            raise RuntimeError(msg)
        task.start()
        self._current_task = task
        self.state = MasterState.WAITING_RESPONSE

    def complete_current_task(self) -> None:
        """Complete the current task."""
        if self._current_task is not None:
            self._current_task.complete()
        self.state = MasterState.IDLE

    def fail_current_task(self) -> None:
        """Fail the current task."""
        if self._current_task is not None:
            self._current_task.fail()
        self.state = MasterState.IDLE

    def cancel_current_task(self) -> None:
        """Cancel the current task."""
        if self._current_task is not None:
            self._current_task.cancel()
        self.state = MasterState.IDLE

    def check_task_timeout(self) -> bool:
        """Check if current task has timed out.

        Returns:
            True if task timed out and was handled.
        """
        if self._current_task is None:
            return False
        if not self._current_task.is_expired():
            return False

        # Task timed out
        if self._current_task.can_retry():
            self._current_task.decrement_retry()
            self._current_task.start()  # Restart for retry
            return True
        else:
            self._current_task.fail()
            self.state = MasterState.IDLE
            return True

    def on_unsolicited_received(self, sequence: int) -> None:
        """Handle receipt of unsolicited response.

        Args:
            sequence: Unsolicited sequence number.
        """
        self.unsolicited.last_sequence = sequence
        self.unsolicited.pending_confirm = True

    def on_unsolicited_confirmed(self) -> None:
        """Handle sending of unsolicited confirm."""
        self.unsolicited.pending_confirm = False

    def get_next_request_sequence(self) -> int:
        """Get next request sequence number.

        Returns:
            Next sequence number.
        """
        return self.sequences.next_request_seq()

    def validate_response_sequence(self, seq: int) -> bool:
        """Validate response sequence number.

        Args:
            seq: Sequence from response.

        Returns:
            True if sequence is valid.
        """
        return self.sequences.validate_response_seq(seq)

"""Polling operations for DNP3 master.

Provides classes for building and scheduling poll requests
including integrity polls, class polls, and range polls.
"""

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum, auto

from dnp3.application.builder import (
    build_class_poll,
    build_integrity_poll,
    build_read_request,
)
from dnp3.application.fragment import ObjectBlock, RequestFragment
from dnp3.application.qualifiers import ObjectHeader, RangeCode, StartStopRange

# Range size limits for qualifier selection
MAX_UINT8_RANGE = 255
MAX_UINT16_RANGE = 65535


class PollType(Enum):
    """Types of polling operations."""

    INTEGRITY = auto()  # Class 0 + all events
    CLASS_0 = auto()  # Static data only
    CLASS_1 = auto()  # Class 1 events
    CLASS_2 = auto()  # Class 2 events
    CLASS_3 = auto()  # Class 3 events
    RANGE = auto()  # Specific range of points


@dataclass
class PollTask(ABC):
    """Base class for poll tasks.

    Attributes:
        poll_type: Type of poll operation.
        interval: Polling interval in seconds (0=one-shot).
        last_poll_time: Time of last poll.
        enabled: Whether polling is enabled.
    """

    poll_type: PollType
    interval: float = 0.0
    last_poll_time: float = 0.0
    enabled: bool = True

    @abstractmethod
    def build_request(self, seq: int = 0) -> RequestFragment:
        """Build the poll request.

        Args:
            seq: Sequence number for request.

        Returns:
            Request fragment for this poll.
        """
        ...

    def is_due(self) -> bool:
        """Check if poll is due to run.

        Returns:
            True if poll should run now.
        """
        if not self.enabled:
            return False
        if self.interval <= 0:
            return self.last_poll_time == 0  # One-shot
        return time.monotonic() - self.last_poll_time >= self.interval

    def mark_executed(self) -> None:
        """Mark poll as executed."""
        self.last_poll_time = time.monotonic()

    def reset(self) -> None:
        """Reset poll timing."""
        self.last_poll_time = 0.0


@dataclass
class IntegrityPollTask(PollTask):
    """Integrity poll (Class 0 + all events).

    Requests all static data and all pending events.
    """

    poll_type: PollType = field(default=PollType.INTEGRITY, init=False)

    def build_request(self, seq: int = 0) -> RequestFragment:
        """Build integrity poll request."""
        return build_integrity_poll(seq=seq)


@dataclass
class ClassPollTask(PollTask):
    """Class poll for specific event classes.

    Attributes:
        class_1: Include Class 1 events.
        class_2: Include Class 2 events.
        class_3: Include Class 3 events.
    """

    class_1: bool = False
    class_2: bool = False
    class_3: bool = False
    poll_type: PollType = field(default=PollType.CLASS_1, init=False)

    def __post_init__(self) -> None:
        """Set poll type based on classes."""
        if self.class_1 and not self.class_2 and not self.class_3:
            self.poll_type = PollType.CLASS_1
        elif not self.class_1 and self.class_2 and not self.class_3:
            self.poll_type = PollType.CLASS_2
        elif not self.class_1 and not self.class_2 and self.class_3:
            self.poll_type = PollType.CLASS_3

    def build_request(self, seq: int = 0) -> RequestFragment:
        """Build class poll request."""
        return build_class_poll(
            class_1=self.class_1,
            class_2=self.class_2,
            class_3=self.class_3,
            seq=seq,
        )


@dataclass
class RangePollTask(PollTask):
    """Range poll for specific point range.

    Attributes:
        group: Object group number.
        variation: Object variation.
        start: Start index.
        stop: Stop index.
    """

    group: int = 1
    variation: int = 0
    start: int = 0
    stop: int = 0
    poll_type: PollType = field(default=PollType.RANGE, init=False)

    def build_request(self, seq: int = 0) -> RequestFragment:
        """Build range poll request."""
        # Determine range size
        if self.stop <= MAX_UINT8_RANGE:
            range_code = RangeCode.UINT8_START_STOP
            range_data = StartStopRange(start=self.start, stop=self.stop).to_bytes_1()
        elif self.stop <= MAX_UINT16_RANGE:
            range_code = RangeCode.UINT16_START_STOP
            range_data = StartStopRange(start=self.start, stop=self.stop).to_bytes_2()
        else:
            range_code = RangeCode.UINT32_START_STOP
            range_data = StartStopRange(start=self.start, stop=self.stop).to_bytes_4()

        header = ObjectHeader(
            group=self.group,
            variation=self.variation,
            qualifier=range_code,
        )
        block = ObjectBlock(header=header, data=range_data)
        return build_read_request(objects=(block,), seq=seq)


@dataclass
class PollScheduler:
    """Scheduler for managing multiple poll tasks.

    Manages a set of poll tasks and determines which
    polls are due to run.
    """

    _tasks: list[PollTask] = field(default_factory=list)

    def add_task(self, task: PollTask) -> None:
        """Add a poll task.

        Args:
            task: Poll task to add.
        """
        self._tasks.append(task)

    def remove_task(self, task: PollTask) -> None:
        """Remove a poll task.

        Args:
            task: Poll task to remove.
        """
        if task in self._tasks:
            self._tasks.remove(task)

    def get_due_tasks(self) -> list[PollTask]:
        """Get all tasks that are due.

        Returns:
            List of tasks ready to execute.
        """
        return [task for task in self._tasks if task.is_due()]

    def get_next_task(self) -> PollTask | None:
        """Get the next task to execute.

        Returns highest priority due task.

        Returns:
            Next task to execute, or None.
        """
        due = self.get_due_tasks()
        if not due:
            return None

        # Priority: integrity > class polls > range polls
        for poll_type in [PollType.INTEGRITY, PollType.CLASS_1, PollType.CLASS_2, PollType.CLASS_3]:
            for task in due:
                if task.poll_type == poll_type:
                    return task

        return due[0] if due else None

    def get_time_until_next(self) -> float | None:
        """Get time until next scheduled poll.

        Returns:
            Seconds until next poll, or None if no scheduled polls.
        """
        min_time: float | None = None

        for task in self._tasks:
            if not task.enabled or task.interval <= 0:
                continue

            time_since = time.monotonic() - task.last_poll_time
            time_until = task.interval - time_since

            if time_until <= 0:
                return 0.0

            if min_time is None or time_until < min_time:
                min_time = time_until

        return min_time

    @property
    def task_count(self) -> int:
        """Get number of scheduled tasks."""
        return len(self._tasks)

    def clear(self) -> None:
        """Remove all tasks."""
        self._tasks.clear()

    def reset_all(self) -> None:
        """Reset timing on all tasks."""
        for task in self._tasks:
            task.reset()


def create_integrity_poll(interval: float = 3600.0) -> IntegrityPollTask:
    """Create an integrity poll task.

    Args:
        interval: Polling interval in seconds.

    Returns:
        Configured integrity poll task.
    """
    return IntegrityPollTask(interval=interval)


def create_class_poll(
    class_1: bool = True,
    class_2: bool = True,
    class_3: bool = True,
    interval: float = 0.0,
) -> ClassPollTask:
    """Create a class poll task.

    Args:
        class_1: Include Class 1 events.
        class_2: Include Class 2 events.
        class_3: Include Class 3 events.
        interval: Polling interval in seconds.

    Returns:
        Configured class poll task.
    """
    return ClassPollTask(
        class_1=class_1,
        class_2=class_2,
        class_3=class_3,
        interval=interval,
    )


def create_range_poll(
    group: int,
    variation: int,
    start: int,
    stop: int,
    interval: float = 0.0,
) -> RangePollTask:
    """Create a range poll task.

    Args:
        group: Object group number.
        variation: Object variation.
        start: Start index.
        stop: Stop index.
        interval: Polling interval in seconds.

    Returns:
        Configured range poll task.
    """
    return RangePollTask(
        group=group,
        variation=variation,
        start=start,
        stop=stop,
        interval=interval,
    )

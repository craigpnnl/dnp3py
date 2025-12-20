"""DNP3 Master Station implementation per IEEE 1815-2012.

The Master class handles communication with an outstation,
including polling, commands, and unsolicited response handling.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field

from dnp3.application.builder import (
    build_confirm_request,
    build_delay_measure_request,
    build_disable_unsolicited_request,
    build_enable_unsolicited_request,
)
from dnp3.application.fragment import ObjectBlock, RequestFragment, ResponseFragment
from dnp3.application.parser import parse_response
from dnp3.master.commands import (
    CommandBuilder,
    DirectOperateTask,
    OperateTask,
    SelectTask,
)
from dnp3.master.config import MasterConfig
from dnp3.master.handler import (
    AnalogValue,
    BinaryValue,
    CounterValue,
    DefaultSOEHandler,
    ResponseInfo,
    SOEHandler,
)
from dnp3.master.polling import (
    ClassPollTask,
    IntegrityPollTask,
    PollScheduler,
    PollTask,
    RangePollTask,
)
from dnp3.master.state import MasterState, MasterStateManager

# DNP3 group numbers for parsing
GROUP_BINARY_INPUT = 1
GROUP_BINARY_INPUT_EVENT = 2
GROUP_BINARY_OUTPUT = 10
GROUP_BINARY_OUTPUT_EVENT = 11
GROUP_ANALOG_INPUT = 30
GROUP_ANALOG_INPUT_EVENT = 32
GROUP_ANALOG_OUTPUT = 40
GROUP_ANALOG_OUTPUT_EVENT = 42
GROUP_COUNTER = 20
GROUP_COUNTER_EVENT = 22
GROUP_FROZEN_COUNTER = 21
GROUP_TIME_DELAY = 52

# Quality flag mask
QUALITY_ONLINE = 0x01
QUALITY_STATE = 0x80

# DNP3 variation numbers for parsing (IEEE 1815-2012)
VARIATION_PACKED = 1  # Packed format (bits)
VARIATION_FLAGS = 2  # With flags byte
VARIATION_32BIT_FLAGS = 1  # 32-bit value with flags
VARIATION_16BIT_FLAGS = 2  # 16-bit value with flags
VARIATION_32BIT_NO_FLAGS = 3  # 32-bit value, no flags (analog g30v3)
VARIATION_16BIT_NO_FLAGS = 4  # 16-bit value, no flags (analog g30v4)
VARIATION_COUNTER_32BIT_NO_FLAGS = 5  # 32-bit counter, no flags (g20v5)
VARIATION_COUNTER_16BIT_NO_FLAGS = 6  # 16-bit counter, no flags (g20v6)


@dataclass
class Master:
    """DNP3 Master Station implementation.

    Communicates with an outstation to poll data and execute commands.

    Attributes:
        config: Master configuration.
        handler: SOE handler for received data.
    """

    config: MasterConfig = field(default_factory=MasterConfig)
    handler: SOEHandler = field(default_factory=DefaultSOEHandler)
    _state: MasterStateManager = field(default_factory=MasterStateManager, init=False)
    _scheduler: PollScheduler = field(default_factory=PollScheduler, init=False)
    _pending_select: SelectTask | None = field(default=None, init=False)

    def __post_init__(self) -> None:
        """Initialize master state."""
        self._setup_polling()

    def _setup_polling(self) -> None:
        """Set up polling tasks from config."""
        polling = self.config.polling

        if polling.integrity_poll_interval > 0:
            integrity_task = IntegrityPollTask(interval=polling.integrity_poll_interval)
            self._scheduler.add_task(integrity_task)

        if polling.class_1_poll_interval > 0:
            class1_task = ClassPollTask(class_1=True, interval=polling.class_1_poll_interval)
            self._scheduler.add_task(class1_task)

        if polling.class_2_poll_interval > 0:
            class2_task = ClassPollTask(class_2=True, interval=polling.class_2_poll_interval)
            self._scheduler.add_task(class2_task)

        if polling.class_3_poll_interval > 0:
            class3_task = ClassPollTask(class_3=True, interval=polling.class_3_poll_interval)
            self._scheduler.add_task(class3_task)

    @property
    def state(self) -> MasterState:
        """Get current master state."""
        return self._state.state

    @property
    def is_idle(self) -> bool:
        """Check if master is idle."""
        return self._state.is_idle

    @property
    def scheduler(self) -> PollScheduler:
        """Get the poll scheduler."""
        return self._scheduler

    # -------------------------------------------------------------------------
    # Request Building
    # -------------------------------------------------------------------------

    def build_integrity_poll(self) -> RequestFragment:
        """Build an integrity poll request.

        Returns:
            Request fragment for integrity poll.
        """
        task = IntegrityPollTask()
        seq = self._state.get_next_request_sequence()
        return task.build_request(seq=seq)

    def build_class_poll(
        self,
        class_1: bool = True,
        class_2: bool = True,
        class_3: bool = True,
    ) -> RequestFragment:
        """Build a class poll request.

        Args:
            class_1: Include Class 1 events.
            class_2: Include Class 2 events.
            class_3: Include Class 3 events.

        Returns:
            Request fragment for class poll.
        """
        task = ClassPollTask(class_1=class_1, class_2=class_2, class_3=class_3)
        seq = self._state.get_next_request_sequence()
        return task.build_request(seq=seq)

    def build_range_poll(
        self,
        group: int,
        variation: int,
        start: int,
        stop: int,
    ) -> RequestFragment:
        """Build a range poll request.

        Args:
            group: Object group.
            variation: Object variation.
            start: Start index.
            stop: Stop index.

        Returns:
            Request fragment for range poll.
        """
        task = RangePollTask(group=group, variation=variation, start=start, stop=stop)
        seq = self._state.get_next_request_sequence()
        return task.build_request(seq=seq)

    def build_select(self, task: SelectTask) -> RequestFragment:
        """Build a SELECT request.

        Args:
            task: Select task with operations.

        Returns:
            Request fragment for SELECT.
        """
        seq = self._state.get_next_request_sequence()
        self._pending_select = task
        return task.build_request(seq=seq)

    def build_operate(self, task: OperateTask) -> RequestFragment:
        """Build an OPERATE request.

        Args:
            task: Operate task with operations.

        Returns:
            Request fragment for OPERATE.
        """
        seq = self._state.get_next_request_sequence()
        return task.build_request(seq=seq)

    def build_direct_operate(self, task: DirectOperateTask) -> RequestFragment:
        """Build a DIRECT_OPERATE request.

        Args:
            task: Direct operate task with operations.

        Returns:
            Request fragment for DIRECT_OPERATE.
        """
        seq = self._state.get_next_request_sequence()
        return task.build_request(seq=seq)

    def build_enable_unsolicited(
        self,
        class_1: bool = True,
        class_2: bool = True,
        class_3: bool = True,
    ) -> RequestFragment:
        """Build an ENABLE_UNSOLICITED request.

        Args:
            class_1: Enable Class 1.
            class_2: Enable Class 2.
            class_3: Enable Class 3.

        Returns:
            Request fragment for ENABLE_UNSOLICITED.
        """
        seq = self._state.get_next_request_sequence()
        return build_enable_unsolicited_request(
            class_1=class_1,
            class_2=class_2,
            class_3=class_3,
            seq=seq,
        )

    def build_disable_unsolicited(
        self,
        class_1: bool = True,
        class_2: bool = True,
        class_3: bool = True,
    ) -> RequestFragment:
        """Build a DISABLE_UNSOLICITED request.

        Args:
            class_1: Disable Class 1.
            class_2: Disable Class 2.
            class_3: Disable Class 3.

        Returns:
            Request fragment for DISABLE_UNSOLICITED.
        """
        seq = self._state.get_next_request_sequence()
        return build_disable_unsolicited_request(
            class_1=class_1,
            class_2=class_2,
            class_3=class_3,
            seq=seq,
        )

    def build_delay_measure(self) -> RequestFragment:
        """Build a DELAY_MEASURE request.

        Returns:
            Request fragment for DELAY_MEASURE.
        """
        seq = self._state.get_next_request_sequence()
        return build_delay_measure_request(seq=seq)

    def build_confirm(self, seq: int) -> RequestFragment:
        """Build a CONFIRM request.

        Args:
            seq: Sequence number to confirm.

        Returns:
            Request fragment for CONFIRM.
        """
        return build_confirm_request(seq=seq)

    # -------------------------------------------------------------------------
    # Response Processing
    # -------------------------------------------------------------------------

    def process_response(self, data: bytes) -> ResponseInfo | None:
        """Process a response from the outstation.

        Args:
            data: Raw response bytes.

        Returns:
            Response info, or None if parse failed.
        """
        try:
            response = parse_response(data)
        except Exception:
            return None

        return self._process_response_fragment(response)

    def _process_response_fragment(self, response: ResponseFragment) -> ResponseInfo:
        """Process a parsed response fragment.

        Args:
            response: Parsed response fragment.

        Returns:
            Response information.
        """
        info = ResponseInfo(
            function=response.header.function,
            iin=response.header.iin,
            sequence=response.header.control.seq,
            is_unsolicited=response.header.control.uns,
        )

        # Handle unsolicited responses
        if info.is_unsolicited:
            self._state.on_unsolicited_received(info.sequence)

        # Parse data objects and call handler
        self._parse_response_objects(response.objects, info)

        # Update state
        if not info.is_unsolicited and self._state.validate_response_sequence(info.sequence):
            self._state.complete_current_task()

        return info

    def _parse_response_objects(self, objects: Sequence[ObjectBlock], info: ResponseInfo) -> None:
        """Parse response objects and call appropriate handler methods.

        Args:
            objects: Object blocks from response.
            info: Response information.
        """
        binary_inputs: list[BinaryValue] = []
        binary_outputs: list[BinaryValue] = []
        analog_inputs: list[AnalogValue] = []
        analog_outputs: list[AnalogValue] = []
        counters: list[CounterValue] = []
        frozen_counters: list[CounterValue] = []

        for block in objects:
            group = block.header.group

            if group in {GROUP_BINARY_INPUT, GROUP_BINARY_INPUT_EVENT}:
                binary_inputs.extend(self._parse_binary_values(block))
            elif group in {GROUP_BINARY_OUTPUT, GROUP_BINARY_OUTPUT_EVENT}:
                binary_outputs.extend(self._parse_binary_values(block))
            elif group in {GROUP_ANALOG_INPUT, GROUP_ANALOG_INPUT_EVENT}:
                analog_inputs.extend(self._parse_analog_values(block))
            elif group in {GROUP_ANALOG_OUTPUT, GROUP_ANALOG_OUTPUT_EVENT}:
                analog_outputs.extend(self._parse_analog_values(block))
            elif group in {GROUP_COUNTER, GROUP_COUNTER_EVENT}:
                counters.extend(self._parse_counter_values(block))
            elif group == GROUP_FROZEN_COUNTER:
                frozen_counters.extend(self._parse_counter_values(block))

        # Call handler methods
        if binary_inputs:
            self.handler.on_binary_input(binary_inputs, info)
        if binary_outputs:
            self.handler.on_binary_output(binary_outputs, info)
        if analog_inputs:
            self.handler.on_analog_input(analog_inputs, info)
        if analog_outputs:
            self.handler.on_analog_output(analog_outputs, info)
        if counters:
            self.handler.on_counter(counters, info)
        if frozen_counters:
            self.handler.on_frozen_counter(frozen_counters, info)

    def _parse_binary_values(self, block: ObjectBlock) -> list[BinaryValue]:
        """Parse binary values from object block.

        Args:
            block: Object block containing binary data.

        Returns:
            List of parsed binary values.
        """
        values: list[BinaryValue] = []
        data = block.data
        if not data:
            return values

        # Parse based on qualifier - simplified for common cases
        qualifier = block.header.qualifier
        variation = block.header.variation

        # Handle packed format (g1v1) - 1 bit per point
        if variation == VARIATION_PACKED:
            # Packed binary - each byte has 8 points
            # First parse the range to get start index
            offset = 0
            start_index = 0
            if qualifier & 0x0F == 0x00:  # Start-stop 1-byte
                start_index = data[0]
                offset = 2  # start + stop
            elif qualifier & 0x0F == 0x01:  # Start-stop 2-byte
                start_index = int.from_bytes(data[0:2], "little")
                offset = 4

            # Parse packed bits
            bit_index = 0
            for byte_idx in range(offset, len(data)):
                byte_val = data[byte_idx]
                for bit in range(8):
                    if offset + (bit_index // 8) < len(data):
                        value = bool((byte_val >> bit) & 1)
                        values.append(
                            BinaryValue(
                                index=start_index + bit_index,
                                value=value,
                                quality=QUALITY_ONLINE,
                            )
                        )
                    bit_index += 1

        # Handle flags format (g1v2, g10v2) - 1 byte per point
        elif variation == VARIATION_FLAGS:
            offset = 0
            start_index = 0

            # Parse range
            if qualifier & 0x0F == 0x00:  # Start-stop 1-byte
                start_index = data[0]
                offset = 2
            elif qualifier & 0x0F == 0x01:  # Start-stop 2-byte
                start_index = int.from_bytes(data[0:2], "little")
                offset = 4

            # Parse flag bytes
            index = start_index
            for i in range(offset, len(data)):
                flags = data[i]
                value = bool(flags & QUALITY_STATE)
                quality = flags & ~QUALITY_STATE
                values.append(
                    BinaryValue(
                        index=index,
                        value=value,
                        quality=quality,
                    )
                )
                index += 1

        return values

    def _parse_analog_values(self, block: ObjectBlock) -> list[AnalogValue]:
        """Parse analog values from object block.

        Args:
            block: Object block containing analog data.

        Returns:
            List of parsed analog values.
        """
        values: list[AnalogValue] = []
        data = block.data
        if not data:
            return values

        qualifier = block.header.qualifier
        variation = block.header.variation

        # Determine value size based on variation
        # g30v1: 32-bit with flags (5 bytes)
        # g30v2: 16-bit with flags (3 bytes)
        # g30v3: 32-bit no flags (4 bytes)
        # g30v4: 16-bit no flags (2 bytes)
        # g30v5: float with flags (5 bytes)
        # g30v6: double with flags (9 bytes)

        if variation == VARIATION_32BIT_FLAGS:
            value_size = 5  # 1 flag + 4 value
            has_flags = True
            is_32bit = True
        elif variation == VARIATION_16BIT_FLAGS:
            value_size = 3  # 1 flag + 2 value
            has_flags = True
            is_32bit = False
        elif variation == VARIATION_32BIT_NO_FLAGS:
            value_size = 4
            has_flags = False
            is_32bit = True
        elif variation == VARIATION_16BIT_NO_FLAGS:
            value_size = 2
            has_flags = False
            is_32bit = False
        else:
            return values  # Unsupported variation

        # Parse range
        offset = 0
        start_index = 0
        if qualifier & 0x0F == 0x00:
            start_index = data[0]
            offset = 2
        elif qualifier & 0x0F == 0x01:
            start_index = int.from_bytes(data[0:2], "little")
            offset = 4

        # Parse values
        index = start_index
        while offset + value_size <= len(data):
            if has_flags:
                quality = data[offset]
                offset += 1
            else:
                quality = QUALITY_ONLINE

            if is_32bit:
                raw_value = int.from_bytes(data[offset : offset + 4], "little", signed=True)
                offset += 4
            else:
                raw_value = int.from_bytes(data[offset : offset + 2], "little", signed=True)
                offset += 2

            values.append(
                AnalogValue(
                    index=index,
                    value=float(raw_value),
                    quality=quality,
                )
            )
            index += 1

        return values

    def _parse_counter_values(self, block: ObjectBlock) -> list[CounterValue]:
        """Parse counter values from object block.

        Args:
            block: Object block containing counter data.

        Returns:
            List of parsed counter values.
        """
        values: list[CounterValue] = []
        data = block.data
        if not data:
            return values

        qualifier = block.header.qualifier
        variation = block.header.variation

        # g20v1: 32-bit with flags (5 bytes)
        # g20v2: 16-bit with flags (3 bytes)
        # g20v5: 32-bit no flags (4 bytes)
        # g20v6: 16-bit no flags (2 bytes)

        if variation == VARIATION_32BIT_FLAGS:
            value_size = 5
            has_flags = True
            is_32bit = True
        elif variation == VARIATION_16BIT_FLAGS:
            value_size = 3
            has_flags = True
            is_32bit = False
        elif variation == VARIATION_COUNTER_32BIT_NO_FLAGS:
            value_size = 4
            has_flags = False
            is_32bit = True
        elif variation == VARIATION_COUNTER_16BIT_NO_FLAGS:
            value_size = 2
            has_flags = False
            is_32bit = False
        else:
            return values

        # Parse range
        offset = 0
        start_index = 0
        if qualifier & 0x0F == 0x00:
            start_index = data[0]
            offset = 2
        elif qualifier & 0x0F == 0x01:
            start_index = int.from_bytes(data[0:2], "little")
            offset = 4

        # Parse values
        index = start_index
        while offset + value_size <= len(data):
            if has_flags:
                quality = data[offset]
                offset += 1
            else:
                quality = QUALITY_ONLINE

            if is_32bit:
                raw_value = int.from_bytes(data[offset : offset + 4], "little", signed=False)
                offset += 4
            else:
                raw_value = int.from_bytes(data[offset : offset + 2], "little", signed=False)
                offset += 2

            values.append(
                CounterValue(
                    index=index,
                    value=raw_value,
                    quality=quality,
                )
            )
            index += 1

        return values

    # -------------------------------------------------------------------------
    # Convenience Methods
    # -------------------------------------------------------------------------

    def command_builder(self) -> CommandBuilder:
        """Get a new command builder.

        Returns:
            New CommandBuilder instance.
        """
        return CommandBuilder()

    def needs_confirm(self) -> bool:
        """Check if an unsolicited confirm is needed.

        Returns:
            True if confirm should be sent.
        """
        return self._state.unsolicited.pending_confirm

    def get_confirm_sequence(self) -> int:
        """Get the sequence number to confirm.

        Returns:
            Sequence number for confirm.
        """
        return self._state.unsolicited.last_sequence

    def on_confirm_sent(self) -> None:
        """Mark that confirm was sent."""
        self._state.on_unsolicited_confirmed()

    def get_next_poll(self) -> PollTask | None:
        """Get the next poll task to execute.

        Returns:
            Next poll task, or None if none due.
        """
        return self._scheduler.get_next_task()

    def mark_poll_executed(self, task: PollTask) -> None:
        """Mark a poll task as executed.

        Args:
            task: Poll task that was executed.
        """
        task.mark_executed()

    def check_timeout(self) -> bool:
        """Check for and handle task timeout.

        Returns:
            True if timeout occurred.
        """
        return self._state.check_task_timeout()

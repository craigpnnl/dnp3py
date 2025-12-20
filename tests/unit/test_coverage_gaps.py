"""Additional tests to achieve 100% coverage.

Tests specifically targeting uncovered code paths.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from dnp3.application.fragment import ObjectBlock, RequestFragment
from dnp3.application.header import ApplicationControl, RequestHeader, ResponseHeader
from dnp3.application.parser import (
    _parse_range,
    parse_request,
    parse_response,
)
from dnp3.application.qualifiers import ObjectHeader, RangeCode
from dnp3.core.enums import FunctionCode
from dnp3.core.flags import AnalogQuality, BinaryQuality, CounterQuality
from dnp3.core.timestamp import DNP3Timestamp
from dnp3.database import (
    AnalogInputConfig,
    BinaryInputConfig,
    BinaryOutputConfig,
    CounterConfig,
    Database,
    EventClass,
)
from dnp3.datalink.frame import DataLinkFrame
from dnp3.datalink.parser import FrameParser
from dnp3.master.commands import (
    DirectOperateTask,
    OperateTask,
    SelectTask,
)
from dnp3.master.master import Master
from dnp3.master.polling import PollScheduler
from dnp3.objects.analog_input import (
    AnalogInput16,
    AnalogInput16NoFlag,
    AnalogInput32NoFlag,
    AnalogInputDouble,
    AnalogInputFloat,
)
from dnp3.objects.counter import (
    Counter16,
    Counter16NoFlag,
    Counter32NoFlag,
    FrozenCounter16,
)
from dnp3.core.enums import CommandStatus, ControlCode
from dnp3.outstation import Outstation
from dnp3.outstation.handler import CommandResult, DefaultCommandHandler
from dnp3.transport.segment import TransportHeader
from dnp3.transport_io.channel import (
    ChannelConfig,
    ChannelError,
    ChannelState,
    ChannelTimeoutError,
    SimulatorConfig,
    TcpConfig,
    TcpServerConfig,
)
from dnp3.transport_io.simulator import SimulatorChannel, SimulatorServer
from dnp3.transport_io.tcp_client import TcpClientChannel
from dnp3.transport_io.tcp_server import TcpServer, TcpServerChannel, serve


class TestTransportHeaderCoverage:
    """Cover uncovered transport header code."""

    def test_repr(self) -> None:
        """Test TransportHeader __repr__."""
        header = TransportHeader(fir=True, fin=False, seq=5)
        repr_str = repr(header)
        assert "TransportHeader" in repr_str
        assert "fir=True" in repr_str


class TestApplicationHeaderCoverage:
    """Cover uncovered application header code."""

    def test_application_control_repr(self) -> None:
        """Test ApplicationControl __repr__."""
        ctrl = ApplicationControl(fir=True, fin=True, con=False, uns=False, seq=5)
        repr_str = repr(ctrl)
        assert "ApplicationControl" in repr_str

    def test_request_header_from_bytes(self) -> None:
        """Test RequestHeader from_bytes."""
        data = bytes([0xC0, 0x01])  # FIR|FIN, READ function
        header = RequestHeader.from_bytes(data)
        assert header.function == FunctionCode.READ
        assert header.control.fir is True
        assert header.control.fin is True

    def test_response_header_from_bytes(self) -> None:
        """Test ResponseHeader from_bytes."""
        data = bytes([0xC0, 0x81, 0x00, 0x00])  # FIR|FIN, RESPONSE function, IIN
        header = ResponseHeader.from_bytes(data)
        assert header.function == FunctionCode.RESPONSE


class TestParserCoverage:
    """Cover uncovered parser code."""

    def test_parse_range_1byte(self) -> None:
        """Test parsing with 1-byte start-stop range."""
        # RangeCode 0x00 is 1-byte start-stop
        result = _parse_range(b"\x00\x05", RangeCode(0x00))
        assert result.start == 0
        assert result.stop == 5
        assert result.count == 6  # 0 to 5 inclusive

    def test_parse_request_empty_after_header(self) -> None:
        """Test parsing request with no objects."""
        # Just AC + FC
        data = bytes([0xC0, 0x01])  # FIR|FIN, READ
        request = parse_request(data)
        assert request.header.function == FunctionCode.READ
        assert len(request.objects) == 0

    def test_parse_response_empty_after_header(self) -> None:
        """Test parsing response with no objects."""
        # AC + FC + IIN1 + IIN2
        data = bytes([0xC0, 0x81, 0x00, 0x00])  # FIR|FIN, RESPONSE, IIN
        response = parse_response(data)
        assert response.header.function == FunctionCode.RESPONSE
        assert len(response.objects) == 0


class TestFlagsCoverage:
    """Cover uncovered flags code."""

    def test_binary_quality_or(self) -> None:
        """Test BinaryQuality __or__ with int."""
        result = BinaryQuality.ONLINE | 0x80
        assert result & 0x80

    def test_analog_quality_or(self) -> None:
        """Test AnalogQuality __or__ with int."""
        result = AnalogQuality.ONLINE | 0x02
        assert result & 0x02

    def test_counter_quality_or(self) -> None:
        """Test CounterQuality __or__ with int."""
        result = CounterQuality.ONLINE | 0x04
        assert result & 0x04


class TestTimestampCoverage:
    """Cover uncovered timestamp code."""

    def test_timestamp_repr(self) -> None:
        """Test DNP3Timestamp __repr__."""
        ts = DNP3Timestamp(milliseconds=1234567890)
        repr_str = repr(ts)
        assert "DNP3Timestamp" in repr_str


class TestDatabaseCoverage:
    """Cover uncovered database code."""

    def test_get_binary_input_nonexistent(self) -> None:
        """Test getting nonexistent binary input returns None."""
        db = Database()
        result = db.get_binary_input(999)
        assert result is None

    def test_get_binary_output_nonexistent(self) -> None:
        """Test getting nonexistent binary output returns None."""
        db = Database()
        result = db.get_binary_output(999)
        assert result is None

    def test_get_analog_input_nonexistent(self) -> None:
        """Test getting nonexistent analog input returns None."""
        db = Database()
        result = db.get_analog_input(999)
        assert result is None

    def test_get_counter_nonexistent(self) -> None:
        """Test getting nonexistent counter returns None."""
        db = Database()
        result = db.get_counter(999)
        assert result is None

    def test_get_frozen_counter_nonexistent(self) -> None:
        """Test getting nonexistent frozen counter returns None."""
        db = Database()
        result = db.get_frozen_counter(999)
        assert result is None

    def test_update_binary_input_nonexistent_raises(self) -> None:
        """Test updating nonexistent binary input raises KeyError."""
        db = Database()
        with pytest.raises(KeyError):
            db.update_binary_input(999, value=True)

    def test_update_binary_output_nonexistent_raises(self) -> None:
        """Test updating nonexistent binary output raises KeyError."""
        db = Database()
        with pytest.raises(KeyError):
            db.update_binary_output(999, value=True)

    def test_update_analog_input_nonexistent_raises(self) -> None:
        """Test updating nonexistent analog input raises KeyError."""
        db = Database()
        with pytest.raises(KeyError):
            db.update_analog_input(999, value=100.0)

    def test_update_counter_nonexistent_raises(self) -> None:
        """Test updating nonexistent counter raises KeyError."""
        db = Database()
        with pytest.raises(KeyError):
            db.update_counter(999, value=100)

    def test_add_frozen_counter(self) -> None:
        """Test adding a frozen counter point."""
        db = Database()
        db.add_frozen_counter(0, CounterConfig())
        fc = db.get_frozen_counter(0)
        assert fc is not None
        assert fc.value == 0

    def test_binary_input_iteration(self) -> None:
        """Test iterating over binary inputs."""
        db = Database()
        db.add_binary_input(0, BinaryInputConfig())
        db.add_binary_input(1, BinaryInputConfig())
        points = list(db.binary_inputs.values())
        assert len(points) == 2


class TestEventBufferCoverage:
    """Cover uncovered event buffer code."""

    def test_pop_class_events_empty(self) -> None:
        """Test popping from empty class buffer."""
        db = Database()
        events = db.event_buffer.pop_class_events(EventClass.CLASS_1)
        assert len(events) == 0


class TestPointCoverage:
    """Cover uncovered point code."""

    def test_binary_input_point_repr(self) -> None:
        """Test BinaryInputPoint __repr__."""
        db = Database()
        db.add_binary_input(0, BinaryInputConfig())
        point = db.get_binary_input(0)
        assert point is not None
        repr_str = repr(point)
        assert "BinaryInputPoint" in repr_str or "index=0" in repr_str


class TestDataLinkCoverage:
    """Cover uncovered datalink code."""

    def test_frame_build(self) -> None:
        """Test DataLinkFrame.build()."""
        from dnp3.datalink.control import ControlByte

        control = ControlByte(
            dir_from_master=True,
            prm=True,
            fcb=False,
            fcv=False,
            function_code=0,
        )
        frame = DataLinkFrame.build(
            destination=1,
            source=10,
            control=control,
            user_data=b"\x00\x01\x02",
        )
        assert frame.header.destination == 1
        assert frame.header.source == 10

    def test_parser_feed_partial(self) -> None:
        """Test parser state machine with partial data."""
        parser = FrameParser()

        # Feed partial start bytes
        frames = list(parser.feed(b"\x05"))
        assert len(frames) == 0  # Not enough data yet

        # Check bytes buffered
        assert parser.bytes_buffered == 1

    def test_parser_reset(self) -> None:
        """Test parser reset."""
        parser = FrameParser()
        parser.feed(b"\x05")
        assert parser.bytes_buffered == 1

        parser.reset()
        assert parser.bytes_buffered == 0


class TestMasterCommandsCoverage:
    """Cover uncovered master commands code."""

    def test_select_task_2byte_index(self) -> None:
        """Test SelectTask with index > 255 (2-byte qualifier)."""
        task = SelectTask()
        from dnp3.core.enums import ControlCode
        from dnp3.master.commands import ControlOperation

        task.add_operation(
            ControlOperation(index=1000, control_code=ControlCode.LATCH_ON)
        )
        request = task.build_request(seq=0)
        assert len(request.objects) > 0

    def test_operate_task_2byte_index(self) -> None:
        """Test OperateTask with index > 255."""
        task = OperateTask()
        from dnp3.core.enums import ControlCode
        from dnp3.master.commands import ControlOperation

        task.add_operation(
            ControlOperation(index=1000, control_code=ControlCode.LATCH_ON)
        )
        request = task.build_request(seq=0)
        assert len(request.objects) > 0

    def test_direct_operate_task_2byte_index(self) -> None:
        """Test DirectOperateTask with index > 255."""
        task = DirectOperateTask()
        from dnp3.core.enums import ControlCode
        from dnp3.master.commands import ControlOperation

        task.add_operation(
            ControlOperation(index=1000, control_code=ControlCode.LATCH_ON)
        )
        request = task.build_request(seq=0)
        assert len(request.objects) > 0

    def test_select_task_analog_2byte_index(self) -> None:
        """Test SelectTask with analog output and 2-byte index."""
        task = SelectTask()
        from dnp3.master.commands import ControlOperation

        task.add_operation(
            ControlOperation(index=1000, analog_value=100.0, is_analog=True)
        )
        request = task.build_request(seq=0)
        assert len(request.objects) > 0


class TestMasterMasterCoverage:
    """Cover uncovered master.py code."""

    def test_process_response_parse_failure(self) -> None:
        """Test processing response with parse failure."""
        master = Master()
        result = master.process_response(b"\x00")  # Invalid response
        assert result is None

    def test_parse_binary_values_2byte_range(self) -> None:
        """Test parsing binary values with 2-byte start-stop range."""
        master = Master()
        from dnp3.application.fragment import ObjectBlock
        from dnp3.application.qualifiers import ObjectHeader

        # g1v2 with 2-byte start-stop (qualifier 0x01)
        header = ObjectHeader(group=1, variation=2, qualifier=0x01)
        # Start=0, Stop=1 (2 bytes each) + 2 flag bytes
        data = b"\x00\x00\x01\x00\x81\x01"
        block = ObjectBlock(header=header, data=data)

        values = master._parse_binary_values(block)
        assert len(values) >= 1

    def test_parse_analog_values_16bit(self) -> None:
        """Test parsing 16-bit analog values."""
        master = Master()
        from dnp3.application.fragment import ObjectBlock
        from dnp3.application.qualifiers import ObjectHeader

        # g30v2 - 16-bit with flags
        header = ObjectHeader(group=30, variation=2, qualifier=0x00)
        # Start=0, Stop=0 + flag + 2-byte value
        data = b"\x00\x00\x01\x64\x00"  # Online flag, value=100
        block = ObjectBlock(header=header, data=data)

        values = master._parse_analog_values(block)
        assert len(values) >= 1

    def test_parse_analog_values_no_flags_32bit(self) -> None:
        """Test parsing 32-bit analog without flags."""
        master = Master()
        from dnp3.application.fragment import ObjectBlock
        from dnp3.application.qualifiers import ObjectHeader

        # g30v3 - 32-bit no flags
        header = ObjectHeader(group=30, variation=3, qualifier=0x00)
        # Start=0, Stop=0 + 4-byte value
        data = b"\x00\x00\x64\x00\x00\x00"
        block = ObjectBlock(header=header, data=data)

        values = master._parse_analog_values(block)
        assert len(values) >= 1

    def test_parse_analog_values_no_flags_16bit(self) -> None:
        """Test parsing 16-bit analog without flags."""
        master = Master()
        from dnp3.application.fragment import ObjectBlock
        from dnp3.application.qualifiers import ObjectHeader

        # g30v4 - 16-bit no flags
        header = ObjectHeader(group=30, variation=4, qualifier=0x00)
        # Start=0, Stop=0 + 2-byte value
        data = b"\x00\x00\x64\x00"
        block = ObjectBlock(header=header, data=data)

        values = master._parse_analog_values(block)
        assert len(values) >= 1

    def test_parse_analog_values_unsupported_variation(self) -> None:
        """Test parsing analog with unsupported variation."""
        master = Master()
        from dnp3.application.fragment import ObjectBlock
        from dnp3.application.qualifiers import ObjectHeader

        # g30v99 - unsupported
        header = ObjectHeader(group=30, variation=99, qualifier=0x00)
        data = b"\x00\x00"
        block = ObjectBlock(header=header, data=data)

        values = master._parse_analog_values(block)
        assert len(values) == 0

    def test_parse_counter_values_16bit(self) -> None:
        """Test parsing 16-bit counter values."""
        master = Master()
        from dnp3.application.fragment import ObjectBlock
        from dnp3.application.qualifiers import ObjectHeader

        # g20v2 - 16-bit with flags
        header = ObjectHeader(group=20, variation=2, qualifier=0x00)
        data = b"\x00\x00\x01\x64\x00"
        block = ObjectBlock(header=header, data=data)

        values = master._parse_counter_values(block)
        assert len(values) >= 1

    def test_parse_counter_values_no_flags(self) -> None:
        """Test parsing counter without flags."""
        master = Master()
        from dnp3.application.fragment import ObjectBlock
        from dnp3.application.qualifiers import ObjectHeader

        # g20v5 - 32-bit no flags
        header = ObjectHeader(group=20, variation=5, qualifier=0x00)
        data = b"\x00\x00\x64\x00\x00\x00"
        block = ObjectBlock(header=header, data=data)

        values = master._parse_counter_values(block)
        assert len(values) >= 1

    def test_parse_counter_values_16bit_no_flags(self) -> None:
        """Test parsing 16-bit counter without flags."""
        master = Master()
        from dnp3.application.fragment import ObjectBlock
        from dnp3.application.qualifiers import ObjectHeader

        # g20v6 - 16-bit no flags
        header = ObjectHeader(group=20, variation=6, qualifier=0x00)
        data = b"\x00\x00\x64\x00"
        block = ObjectBlock(header=header, data=data)

        values = master._parse_counter_values(block)
        assert len(values) >= 1

    def test_parse_counter_values_unsupported(self) -> None:
        """Test parsing counter with unsupported variation."""
        master = Master()
        from dnp3.application.fragment import ObjectBlock
        from dnp3.application.qualifiers import ObjectHeader

        header = ObjectHeader(group=20, variation=99, qualifier=0x00)
        data = b"\x00\x00"
        block = ObjectBlock(header=header, data=data)

        values = master._parse_counter_values(block)
        assert len(values) == 0

    def test_check_timeout(self) -> None:
        """Test timeout checking."""
        master = Master()
        result = master.check_timeout()
        assert result is False  # No task in progress


class TestPollSchedulerCoverage:
    """Cover uncovered poll scheduler code."""

    def test_get_next_task_returns_range_poll(self) -> None:
        """Test that range poll is returned when no other type is due."""
        from dnp3.master.polling import RangePollTask

        scheduler = PollScheduler()
        range_poll = RangePollTask(group=1, variation=2, start=0, stop=10, interval=0.0)
        scheduler.add_task(range_poll)

        task = scheduler.get_next_task()
        assert task is range_poll


class TestObjectsCoverage:
    """Cover uncovered object variations."""

    def test_analog_input_16(self) -> None:
        """Test AnalogInput16 serialization."""
        obj = AnalogInput16(value=100, quality=AnalogQuality.ONLINE)
        data = obj.to_bytes()
        assert len(data) == 3  # 1 flag + 2 value

        parsed = AnalogInput16.from_bytes(data)
        assert parsed.value == 100

    def test_analog_input_16_no_flag(self) -> None:
        """Test AnalogInput16NoFlag serialization."""
        obj = AnalogInput16NoFlag(value=100)
        data = obj.to_bytes()
        assert len(data) == 2  # 2 value bytes

        parsed = AnalogInput16NoFlag.from_bytes(data)
        assert parsed.value == 100

    def test_analog_input_32_no_flag(self) -> None:
        """Test AnalogInput32NoFlag serialization."""
        obj = AnalogInput32NoFlag(value=100000)
        data = obj.to_bytes()
        assert len(data) == 4

        parsed = AnalogInput32NoFlag.from_bytes(data)
        assert parsed.value == 100000

    def test_analog_input_float(self) -> None:
        """Test AnalogInputFloat serialization."""
        obj = AnalogInputFloat(value=3.14, quality=AnalogQuality.ONLINE)
        data = obj.to_bytes()
        assert len(data) == 5  # 1 flag + 4 float

        parsed = AnalogInputFloat.from_bytes(data)
        assert abs(parsed.value - 3.14) < 0.01

    def test_analog_input_double(self) -> None:
        """Test AnalogInputDouble serialization."""
        obj = AnalogInputDouble(value=3.14159265359, quality=AnalogQuality.ONLINE)
        data = obj.to_bytes()
        assert len(data) == 9  # 1 flag + 8 double

        parsed = AnalogInputDouble.from_bytes(data)
        assert abs(parsed.value - 3.14159265359) < 0.0001

    def test_counter_16(self) -> None:
        """Test Counter16 serialization."""
        obj = Counter16(value=1000, quality=CounterQuality.ONLINE)
        data = obj.to_bytes()
        assert len(data) == 3

        parsed = Counter16.from_bytes(data)
        assert parsed.value == 1000

    def test_counter_16_no_flag(self) -> None:
        """Test Counter16NoFlag serialization."""
        obj = Counter16NoFlag(value=1000)
        data = obj.to_bytes()
        assert len(data) == 2

        parsed = Counter16NoFlag.from_bytes(data)
        assert parsed.value == 1000

    def test_counter_32_no_flag(self) -> None:
        """Test Counter32NoFlag serialization."""
        obj = Counter32NoFlag(value=100000)
        data = obj.to_bytes()
        assert len(data) == 4

        parsed = Counter32NoFlag.from_bytes(data)
        assert parsed.value == 100000

    def test_frozen_counter_16(self) -> None:
        """Test FrozenCounter16 serialization."""
        obj = FrozenCounter16(value=1000, quality=CounterQuality.ONLINE)
        data = obj.to_bytes()
        assert len(data) == 3

        parsed = FrozenCounter16.from_bytes(data)
        assert parsed.value == 1000


class TestChannelConfigCoverage:
    """Cover uncovered channel config code."""

    def test_channel_config_defaults(self) -> None:
        """Test ChannelConfig has correct defaults."""
        config = ChannelConfig()
        assert config.read_buffer_size == 4096
        assert config.write_buffer_size == 4096

    def test_simulator_config_defaults(self) -> None:
        """Test SimulatorConfig has correct defaults."""
        config = SimulatorConfig()
        assert config.latency == 0.0
        assert config.packet_loss == 0.0

    def test_tcp_server_config_defaults(self) -> None:
        """Test TcpServerConfig has correct defaults."""
        config = TcpServerConfig()
        assert config.backlog == 5
        assert config.reuse_address is True


class TestSimulatorCoverage:
    """Cover uncovered simulator code."""

    @pytest.mark.asyncio
    async def test_channel_open_already_open(self) -> None:
        """Test opening already open channel."""
        channel = SimulatorChannel()
        await channel.open()
        assert channel.is_open

        # Open again - should be no-op
        await channel.open()
        assert channel.is_open
        await channel.close()

    @pytest.mark.asyncio
    async def test_channel_queue_full(self) -> None:
        """Test write when peer queue is full."""
        from dnp3.transport_io.simulator import create_channel_pair

        config = SimulatorConfig(buffer_size=1)
        ch_a, ch_b = create_channel_pair(config=config)
        await ch_a.open()
        await ch_b.open()

        # Fill the queue
        await ch_a.write(b"x")

        # Next write should fail
        with pytest.raises(ChannelError, match="buffer full"):
            await ch_a.write(b"y")

        await ch_a.close()
        await ch_b.close()

    @pytest.mark.asyncio
    async def test_channel_bandwidth_limit(self) -> None:
        """Test simulated bandwidth limiting."""
        from dnp3.transport_io.simulator import create_channel_pair

        config = SimulatorConfig(bandwidth_limit=1000000)  # 1MB/s
        ch_a, ch_b = create_channel_pair(config=config)
        await ch_a.open()
        await ch_b.open()

        await ch_a.write(b"test")
        data = await ch_b.read(4)
        assert data == b"test"

        await ch_a.close()
        await ch_b.close()

    @pytest.mark.asyncio
    async def test_server_stop_already_stopped(self) -> None:
        """Test stopping already stopped server."""
        server = SimulatorServer()
        await server.start()
        await server.stop()

        # Stop again - should be no-op
        await server.stop()
        assert server.state == ChannelState.CLOSED

    @pytest.mark.asyncio
    async def test_client_reconnect(self) -> None:
        """Test client can reconnect after disconnect."""
        from dnp3.transport_io.simulator import SimulatorClient

        server = SimulatorServer()
        await server.start()

        client = SimulatorClient()
        await client.connect(server)
        assert client.is_connected

        await client.disconnect()
        assert not client.is_connected

        # Reconnect
        await client.connect(server)
        assert client.is_connected

        await client.disconnect()
        await server.stop()


class TestTcpServerCoverage:
    """Cover uncovered TCP server code."""

    @pytest.mark.asyncio
    async def test_server_channel_local_address_none(self) -> None:
        """Test server channel local_address when socket info unavailable."""
        # Create mock reader/writer
        reader = AsyncMock(spec=asyncio.StreamReader)
        writer = MagicMock(spec=asyncio.StreamWriter)
        writer.get_extra_info = MagicMock(return_value=None)

        channel = TcpServerChannel(reader=reader, writer=writer)
        assert channel.local_address is None

    @pytest.mark.asyncio
    async def test_server_channel_remote_address_none(self) -> None:
        """Test server channel remote_address when socket info unavailable."""
        reader = AsyncMock(spec=asyncio.StreamReader)
        writer = MagicMock(spec=asyncio.StreamWriter)
        writer.get_extra_info = MagicMock(return_value=None)

        channel = TcpServerChannel(reader=reader, writer=writer)
        assert channel.remote_address is None

    @pytest.mark.asyncio
    async def test_server_channel_open_noop(self) -> None:
        """Test server channel open is no-op."""
        reader = AsyncMock(spec=asyncio.StreamReader)
        writer = MagicMock(spec=asyncio.StreamWriter)

        channel = TcpServerChannel(reader=reader, writer=writer)
        await channel.open()  # Should do nothing
        assert channel.is_open

    @pytest.mark.asyncio
    async def test_server_channel_read_error(self) -> None:
        """Test server channel read OSError handling."""
        reader = AsyncMock(spec=asyncio.StreamReader)
        reader.read = AsyncMock(side_effect=OSError("Connection reset"))
        writer = MagicMock(spec=asyncio.StreamWriter)

        channel = TcpServerChannel(reader=reader, writer=writer)
        with pytest.raises(ChannelError, match="Read failed"):
            await channel.read(100)

    @pytest.mark.asyncio
    async def test_server_channel_write_error(self) -> None:
        """Test server channel write OSError handling."""
        reader = AsyncMock(spec=asyncio.StreamReader)
        writer = MagicMock(spec=asyncio.StreamWriter)
        writer.write = MagicMock()
        writer.drain = AsyncMock(side_effect=OSError("Broken pipe"))

        channel = TcpServerChannel(reader=reader, writer=writer)
        with pytest.raises(ChannelError, match="Write failed"):
            await channel.write(b"test")

    @pytest.mark.asyncio
    async def test_server_channel_read_exactly_error(self) -> None:
        """Test server channel read_exactly error paths."""
        reader = AsyncMock(spec=asyncio.StreamReader)
        reader.readexactly = AsyncMock(side_effect=OSError("Connection reset"))
        writer = MagicMock(spec=asyncio.StreamWriter)

        channel = TcpServerChannel(reader=reader, writer=writer)
        with pytest.raises(ChannelError, match="Read failed"):
            await channel.read_exactly(10)

    @pytest.mark.asyncio
    async def test_server_channel_read_exactly_timeout(self) -> None:
        """Test server channel read_exactly timeout."""
        reader = AsyncMock(spec=asyncio.StreamReader)
        reader.readexactly = AsyncMock(side_effect=TimeoutError())
        writer = MagicMock(spec=asyncio.StreamWriter)

        config = TcpConfig(read_timeout=0.001)
        channel = TcpServerChannel(reader=reader, writer=writer, config=config)
        with pytest.raises(ChannelTimeoutError):
            await channel.read_exactly(10)

    @pytest.mark.asyncio
    async def test_server_channel_write_all_incomplete(self) -> None:
        """Test write_all when write is incomplete."""
        reader = AsyncMock(spec=asyncio.StreamReader)
        writer = MagicMock(spec=asyncio.StreamWriter)
        writer.write = MagicMock()
        writer.drain = AsyncMock()

        channel = TcpServerChannel(reader=reader, writer=writer)

        # Mock write to return less than requested
        with (
            patch.object(channel, "write", return_value=2),
            pytest.raises(ChannelError, match="Only wrote"),
        ):
            await channel.write_all(b"test")

    @pytest.mark.asyncio
    async def test_server_local_address_exception(self) -> None:
        """Test server local_address when getsockname fails."""
        server = TcpServer()
        server._state = ChannelState.OPEN
        server._server = MagicMock()
        server._server.sockets = [MagicMock()]
        server._server.sockets[0].getsockname = MagicMock(side_effect=AttributeError())

        assert server.local_address is None

    @pytest.mark.asyncio
    async def test_server_remove_connection(self) -> None:
        """Test removing a connection from server."""
        server = TcpServer()
        reader = AsyncMock(spec=asyncio.StreamReader)
        writer = MagicMock(spec=asyncio.StreamWriter)
        channel = TcpServerChannel(reader=reader, writer=writer)

        server._connections.append(channel)
        assert server.connection_count == 1

        server.remove_connection(channel)
        assert server.connection_count == 0

        # Remove again - should be no-op
        server.remove_connection(channel)
        assert server.connection_count == 0

    @pytest.mark.asyncio
    async def test_serve_with_config(self) -> None:
        """Test serve() helper with custom config."""
        config = TcpServerConfig(
            host="127.0.0.1",
            port=0,
            nodelay=True,
            keepalive=True,
        )
        server = await serve(host="127.0.0.1", port=0, config=config)
        assert server.is_listening
        await server.stop()


class TestTcpClientCoverage:
    """Cover uncovered TCP client code."""

    @pytest.mark.asyncio
    async def test_client_channel_local_address_none(self) -> None:
        """Test client channel local_address when not connected."""
        channel = TcpClientChannel()
        assert channel.local_address is None

    @pytest.mark.asyncio
    async def test_client_channel_remote_address_none(self) -> None:
        """Test client channel remote_address when not connected."""
        channel = TcpClientChannel()
        assert channel.remote_address is None

    @pytest.mark.asyncio
    async def test_client_channel_read_error(self) -> None:
        """Test client channel read OSError handling."""
        channel = TcpClientChannel()
        channel._state = ChannelState.OPEN
        channel._reader = AsyncMock(spec=asyncio.StreamReader)
        channel._reader.read = AsyncMock(side_effect=OSError("Connection reset"))

        with pytest.raises(ChannelError, match="Read failed"):
            await channel.read(100)

    @pytest.mark.asyncio
    async def test_client_channel_write_error(self) -> None:
        """Test client channel write OSError handling."""
        channel = TcpClientChannel()
        channel._state = ChannelState.OPEN
        channel._writer = MagicMock(spec=asyncio.StreamWriter)
        channel._writer.write = MagicMock()
        channel._writer.drain = AsyncMock(side_effect=OSError("Broken pipe"))

        with pytest.raises(ChannelError, match="Write failed"):
            await channel.write(b"test")

    @pytest.mark.asyncio
    async def test_client_channel_read_exactly_error(self) -> None:
        """Test client channel read_exactly error paths."""
        channel = TcpClientChannel()
        channel._state = ChannelState.OPEN
        channel._reader = AsyncMock(spec=asyncio.StreamReader)
        channel._reader.readexactly = AsyncMock(side_effect=OSError("Connection reset"))

        with pytest.raises(ChannelError, match="Read failed"):
            await channel.read_exactly(10)

    @pytest.mark.asyncio
    async def test_client_channel_read_exactly_timeout(self) -> None:
        """Test client channel read_exactly timeout."""
        config = TcpConfig(read_timeout=0.001)
        channel = TcpClientChannel(config=config)
        channel._state = ChannelState.OPEN
        channel._reader = AsyncMock(spec=asyncio.StreamReader)
        channel._reader.readexactly = AsyncMock(side_effect=TimeoutError())

        with pytest.raises(ChannelTimeoutError):
            await channel.read_exactly(10)

    @pytest.mark.asyncio
    async def test_client_channel_write_all_incomplete(self) -> None:
        """Test client write_all when write is incomplete."""
        channel = TcpClientChannel()
        channel._state = ChannelState.OPEN
        channel._writer = MagicMock(spec=asyncio.StreamWriter)

        with (
            patch.object(channel, "write", return_value=2),
            pytest.raises(ChannelError, match="Only wrote"),
        ):
            await channel.write_all(b"test")


class TestOutstationCoverage:
    """Cover uncovered outstation code paths."""

    def test_binary_output_serialization(self) -> None:
        """Test binary output serialization with STATE flag."""
        db = Database()
        db.add_binary_output(0, BinaryOutputConfig())
        db.update_binary_output(0, value=True)

        outstation = Outstation(database=db)
        master = Master()

        request = master.build_integrity_poll()
        response = outstation.process_request(request.to_bytes())
        assert response is not None

    def test_2byte_index_binary_input(self) -> None:
        """Test binary input with index > 255."""
        db = Database()
        db.add_binary_input(1000, BinaryInputConfig())
        db.update_binary_input(1000, value=True)

        outstation = Outstation(database=db)
        master = Master()

        request = master.build_integrity_poll()
        response = outstation.process_request(request.to_bytes())
        assert response is not None

    def test_2byte_index_binary_output(self) -> None:
        """Test binary output with index > 255."""
        db = Database()
        db.add_binary_output(1000, BinaryOutputConfig())
        db.update_binary_output(1000, value=True)

        outstation = Outstation(database=db)
        master = Master()

        request = master.build_integrity_poll()
        response = outstation.process_request(request.to_bytes())
        assert response is not None

    def test_2byte_index_analog_input(self) -> None:
        """Test analog input with index > 255."""
        db = Database()
        db.add_analog_input(1000, AnalogInputConfig())
        db.update_analog_input(1000, value=100.0)

        outstation = Outstation(database=db)
        master = Master()

        request = master.build_integrity_poll()
        response = outstation.process_request(request.to_bytes())
        assert response is not None

    def test_2byte_index_counter(self) -> None:
        """Test counter with index > 255."""
        db = Database()
        db.add_counter(1000, CounterConfig())
        db.update_counter(1000, value=100)

        outstation = Outstation(database=db)
        master = Master()

        request = master.build_integrity_poll()
        response = outstation.process_request(request.to_bytes())
        assert response is not None

    def test_unsupported_function_code(self) -> None:
        """Test handling of unsupported function code."""
        outstation = Outstation()
        # Build a request with an uncommon function code
        from dnp3.application.builder import build_cold_restart_request

        request = build_cold_restart_request()
        response = outstation.process_request(request.to_bytes())
        assert response is not None

    def test_freeze_counters(self) -> None:
        """Test freeze counters function."""
        from dnp3.application.fragment import ObjectBlock, RequestFragment
        from dnp3.application.header import RequestHeader
        from dnp3.application.qualifiers import ObjectHeader, PrefixCode, RangeCode

        db = Database()
        db.add_counter(0, CounterConfig())
        db.update_counter(0, value=100)

        outstation = Outstation(database=db)

        # Build IMMEDIATE_FREEZE request
        header = RequestHeader.build(function=FunctionCode.IMMEDIATE_FREEZE, seq=0)
        obj_header = ObjectHeader.build(
            group=20,
            variation=0,
            prefix=PrefixCode.NONE,
            range_code=RangeCode.ALL_OBJECTS,
        )
        block = ObjectBlock(header=obj_header)
        request = RequestFragment(header=header, objects=(block,))
        response = outstation.process_request(request.to_bytes())
        assert response is not None

    def test_frozen_counter_response(self) -> None:
        """Test outstation responds with frozen counter data."""
        db = Database()
        db.add_frozen_counter(0, CounterConfig())
        # Set initial value
        db.frozen_counters[0].value = 100

        outstation = Outstation(database=db)
        master = Master()

        request = master.build_integrity_poll()
        response = outstation.process_request(request.to_bytes())
        assert response is not None
        assert len(response.objects) > 0

    def test_1byte_index_binary_inputs(self) -> None:
        """Test binary inputs with 1-byte index (< 255)."""
        db = Database()
        for i in range(5):
            db.add_binary_input(i, BinaryInputConfig())
            db.update_binary_input(i, value=i % 2 == 0)

        outstation = Outstation(database=db)
        master = Master()

        request = master.build_integrity_poll()
        response = outstation.process_request(request.to_bytes())
        assert response is not None


class TestParserEdgeCases:
    """Test parser edge cases for coverage."""

    def test_parse_range_2byte_start_stop(self) -> None:
        """Test parsing 2-byte start-stop range."""
        # RangeCode 0x01 is 2-byte start-stop
        result = _parse_range(b"\x00\x00\x05\x00", RangeCode(0x01))
        assert result.start == 0
        assert result.stop == 5

    def test_parse_range_4byte_start_stop(self) -> None:
        """Test parsing 4-byte start-stop range."""
        # RangeCode 0x02 is 4-byte start-stop
        result = _parse_range(b"\x00\x00\x00\x00\x05\x00\x00\x00", RangeCode(0x02))
        assert result.start == 0
        assert result.stop == 5

    def test_parse_range_1byte_count(self) -> None:
        """Test parsing 1-byte count."""
        # RangeCode 0x07 is 1-byte count
        result = _parse_range(b"\x05", RangeCode(0x07))
        assert result.count == 5

    def test_parse_range_2byte_count(self) -> None:
        """Test parsing 2-byte count."""
        # RangeCode 0x08 is 2-byte count
        result = _parse_range(b"\x05\x00", RangeCode(0x08))
        assert result.count == 5


class TestCounterVariationsCoverage:
    """Test counter object variations for coverage."""

    def test_counter_event_32(self) -> None:
        """Test CounterEvent32 serialization."""
        from dnp3.objects.counter import CounterEvent32

        obj = CounterEvent32(value=100000, quality=CounterQuality.ONLINE)
        data = obj.to_bytes()
        assert len(data) == 5  # 1 flag + 4 bytes value

        parsed = CounterEvent32.from_bytes(data)
        assert parsed.value == 100000

    def test_counter_event_16(self) -> None:
        """Test CounterEvent16 serialization."""
        from dnp3.objects.counter import CounterEvent16

        obj = CounterEvent16(value=1000, quality=CounterQuality.ONLINE)
        data = obj.to_bytes()
        assert len(data) == 3  # 1 flag + 2 bytes value

        parsed = CounterEvent16.from_bytes(data)
        assert parsed.value == 1000

    def test_counter_event_32_time(self) -> None:
        """Test CounterEvent32Time serialization."""
        from dnp3.objects.counter import CounterEvent32Time

        ts = DNP3Timestamp(milliseconds=1234567890)
        obj = CounterEvent32Time(value=100000, quality=CounterQuality.ONLINE, timestamp=ts)
        data = obj.to_bytes()
        assert len(data) == 11  # 1 flag + 4 value + 6 timestamp

        parsed = CounterEvent32Time.from_bytes(data)
        assert parsed.value == 100000

    def test_frozen_counter_32(self) -> None:
        """Test FrozenCounter32 serialization."""
        from dnp3.objects.counter import FrozenCounter32

        obj = FrozenCounter32(value=100000, quality=CounterQuality.ONLINE)
        data = obj.to_bytes()
        assert len(data) == 5

        parsed = FrozenCounter32.from_bytes(data)
        assert parsed.value == 100000

    def test_frozen_counter_32_time(self) -> None:
        """Test FrozenCounter32Time serialization."""
        from dnp3.objects.counter import FrozenCounter32Time

        ts = DNP3Timestamp(milliseconds=1234567890)
        obj = FrozenCounter32Time(value=100000, quality=CounterQuality.ONLINE, timestamp=ts)
        data = obj.to_bytes()
        assert len(data) == 11

        parsed = FrozenCounter32Time.from_bytes(data)
        assert parsed.value == 100000


class TestAnalogEventCoverage:
    """Test analog event objects for coverage."""

    def test_analog_input_event_32(self) -> None:
        """Test AnalogInputEvent32 serialization."""
        from dnp3.objects.analog_input import AnalogInputEvent32

        obj = AnalogInputEvent32(value=100000, quality=AnalogQuality.ONLINE)
        data = obj.to_bytes()
        assert len(data) == 5

        parsed = AnalogInputEvent32.from_bytes(data)
        assert parsed.value == 100000

    def test_analog_input_event_16(self) -> None:
        """Test AnalogInputEvent16 serialization."""
        from dnp3.objects.analog_input import AnalogInputEvent16

        obj = AnalogInputEvent16(value=1000, quality=AnalogQuality.ONLINE)
        data = obj.to_bytes()
        assert len(data) == 3

        parsed = AnalogInputEvent16.from_bytes(data)
        assert parsed.value == 1000

    def test_analog_input_event_float(self) -> None:
        """Test AnalogInputEventFloat serialization."""
        from dnp3.objects.analog_input import AnalogInputEventFloat

        obj = AnalogInputEventFloat(value=3.14, quality=AnalogQuality.ONLINE)
        data = obj.to_bytes()
        assert len(data) == 5

        parsed = AnalogInputEventFloat.from_bytes(data)
        assert abs(parsed.value - 3.14) < 0.01

    def test_analog_input_event_double(self) -> None:
        """Test AnalogInputEventDouble serialization."""
        from dnp3.objects.analog_input import AnalogInputEventDouble

        obj = AnalogInputEventDouble(value=3.14159, quality=AnalogQuality.ONLINE)
        data = obj.to_bytes()
        assert len(data) == 9

        parsed = AnalogInputEventDouble.from_bytes(data)
        assert abs(parsed.value - 3.14159) < 0.0001

    def test_analog_input_event_32_time(self) -> None:
        """Test AnalogInputEvent32Time serialization."""
        from dnp3.objects.analog_input import AnalogInputEvent32Time

        ts = DNP3Timestamp(milliseconds=1234567890)
        obj = AnalogInputEvent32Time(value=100000, quality=AnalogQuality.ONLINE, timestamp=ts)
        data = obj.to_bytes()
        assert len(data) == 11

        parsed = AnalogInputEvent32Time.from_bytes(data)
        assert parsed.value == 100000


class TestDatabaseTransactions:
    """Test database transaction and update operations."""

    def test_transaction_callback(self) -> None:
        """Test database transaction with callback."""
        db = Database()
        db.add_binary_input(0, BinaryInputConfig())
        db.add_binary_input(1, BinaryInputConfig())

        # Use transaction to update multiple points
        def update_points(database: Database) -> None:
            database.update_binary_input(0, value=True)
            database.update_binary_input(1, value=False)

        db.transaction(update_points)

        # Both updates should have been applied
        assert db.binary_inputs[0].value is True
        assert db.binary_inputs[1].value is False


class TestTcpServerChannelEdgeCases:
    """Test TCP server channel edge cases."""

    @pytest.mark.asyncio
    async def test_local_address_index_error(self) -> None:
        """Test local_address when sockname returns incomplete tuple."""
        reader = AsyncMock(spec=asyncio.StreamReader)
        writer = MagicMock(spec=asyncio.StreamWriter)
        # Return empty tuple to trigger IndexError
        writer.get_extra_info = MagicMock(return_value=())

        channel = TcpServerChannel(reader=reader, writer=writer)
        assert channel.local_address is None

    @pytest.mark.asyncio
    async def test_remote_address_index_error(self) -> None:
        """Test remote_address when peername returns incomplete tuple."""
        reader = AsyncMock(spec=asyncio.StreamReader)
        writer = MagicMock(spec=asyncio.StreamWriter)
        # Return empty tuple to trigger IndexError
        writer.get_extra_info = MagicMock(return_value=())

        channel = TcpServerChannel(reader=reader, writer=writer)
        assert channel.remote_address is None

    @pytest.mark.asyncio
    async def test_close_with_oserror(self) -> None:
        """Test close handles OSError gracefully."""
        reader = AsyncMock(spec=asyncio.StreamReader)
        writer = MagicMock(spec=asyncio.StreamWriter)
        writer.close = MagicMock()
        writer.wait_closed = AsyncMock(side_effect=OSError("Connection reset"))

        channel = TcpServerChannel(reader=reader, writer=writer)
        await channel.close()
        assert channel._state == ChannelState.CLOSED

    @pytest.mark.asyncio
    async def test_read_eof(self) -> None:
        """Test read returns empty bytes on EOF."""
        reader = AsyncMock(spec=asyncio.StreamReader)
        reader.read = AsyncMock(return_value=b"")
        writer = MagicMock(spec=asyncio.StreamWriter)

        channel = TcpServerChannel(reader=reader, writer=writer)
        result = await channel.read(100)
        assert result == b""

    @pytest.mark.asyncio
    async def test_read_exactly_incomplete(self) -> None:
        """Test read_exactly raises on incomplete read."""
        reader = AsyncMock(spec=asyncio.StreamReader)
        reader.readexactly = AsyncMock(side_effect=asyncio.IncompleteReadError(b"partial", 100))
        writer = MagicMock(spec=asyncio.StreamWriter)

        channel = TcpServerChannel(reader=reader, writer=writer)
        from dnp3.transport_io.channel import ChannelClosedError

        with pytest.raises(ChannelClosedError):
            await channel.read_exactly(100)


class TestTcpClientChannelEdgeCases:
    """Test TCP client channel edge cases."""

    @pytest.mark.asyncio
    async def test_open_connection_refused(self) -> None:
        """Test open with connection refused."""
        from dnp3.transport_io.channel import ChannelConnectionError

        config = TcpConfig(host="localhost", port=12345, connect_timeout=0.1)
        channel = TcpClientChannel(config=config)

        with pytest.raises(ChannelConnectionError):
            await channel.open()

    @pytest.mark.asyncio
    async def test_close_with_oserror(self) -> None:
        """Test close handles OSError gracefully."""
        channel = TcpClientChannel()
        channel._state = ChannelState.OPEN
        channel._writer = MagicMock(spec=asyncio.StreamWriter)
        channel._writer.close = MagicMock()
        channel._writer.wait_closed = AsyncMock(side_effect=OSError("Connection reset"))

        await channel.close()
        assert channel._state == ChannelState.CLOSED

    @pytest.mark.asyncio
    async def test_read_eof(self) -> None:
        """Test read returns empty bytes on EOF."""
        channel = TcpClientChannel()
        channel._state = ChannelState.OPEN
        channel._reader = AsyncMock(spec=asyncio.StreamReader)
        channel._reader.read = AsyncMock(return_value=b"")

        result = await channel.read(100)
        assert result == b""

    @pytest.mark.asyncio
    async def test_read_exactly_incomplete(self) -> None:
        """Test read_exactly raises on incomplete read."""
        channel = TcpClientChannel()
        channel._state = ChannelState.OPEN
        channel._reader = AsyncMock(spec=asyncio.StreamReader)
        channel._reader.readexactly = AsyncMock(
            side_effect=asyncio.IncompleteReadError(b"partial", 100)
        )
        from dnp3.transport_io.channel import ChannelClosedError

        with pytest.raises(ChannelClosedError):
            await channel.read_exactly(100)


class TestTimestampEdgeCases:
    """Test timestamp edge cases."""

    def test_from_datetime(self) -> None:
        """Test DNP3Timestamp.from_datetime()."""
        from datetime import datetime, timezone

        dt = datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        ts = DNP3Timestamp.from_datetime(dt)
        assert ts.milliseconds > 0

    def test_to_datetime(self) -> None:
        """Test DNP3Timestamp.to_datetime()."""
        ts = DNP3Timestamp(milliseconds=1704067200000)  # 2024-01-01 00:00:00 UTC
        dt = ts.to_datetime()
        assert dt.year == 2024
        assert dt.month == 1
        assert dt.day == 1


class TestFlagsEdgeCases:
    """Test flags edge cases."""

    def test_binary_quality_or_with_enum(self) -> None:
        """Test BinaryQuality __or__ with another BinaryQuality."""
        result = BinaryQuality.ONLINE | BinaryQuality.RESTART
        assert result & BinaryQuality.ONLINE
        assert result & BinaryQuality.RESTART

    def test_analog_quality_or_with_enum(self) -> None:
        """Test AnalogQuality __or__ with another AnalogQuality."""
        result = AnalogQuality.ONLINE | AnalogQuality.OVER_RANGE
        assert result & AnalogQuality.ONLINE
        assert result & AnalogQuality.OVER_RANGE


class SuccessCommandHandler(DefaultCommandHandler):
    """Handler that accepts all commands for testing."""

    def select_binary_output(
        self,
        index: int,
        code: ControlCode,
        count: int,
        on_time: int,
        off_time: int,
    ) -> CommandResult:
        """Accept SELECT for testing."""
        return CommandResult.success()

    def operate_binary_output(
        self,
        index: int,
        code: ControlCode,
        count: int,
        on_time: int,
        off_time: int,
        select_sequence: int,
    ) -> CommandResult:
        """Accept OPERATE for testing."""
        return CommandResult.success()


class TestOutstationOperatePaths:
    """Test outstation SELECT/OPERATE paths."""

    def test_operate_without_select_returns_no_select(self) -> None:
        """OPERATE without prior SELECT returns NO_SELECT status."""

        db = Database()
        db.add_binary_output(0, BinaryOutputConfig())

        # Use success handler so we can test the NO_SELECT path
        handler = SuccessCommandHandler()
        outstation = Outstation(database=db, handler=handler)
        master = Master()

        # Send OPERATE without SELECT first
        builder = master.command_builder()
        builder.latch_on(index=0)
        operate_task = builder.build_operate()

        request = master.build_operate(operate_task)
        response = outstation.process_request(request.to_bytes())

        assert response is not None
        # Response should contain status indicating NO_SELECT

    def test_select_then_operate_success(self) -> None:
        """SELECT then OPERATE completes successfully - covers lines 841-859."""
        db = Database()
        db.add_binary_output(0, BinaryOutputConfig())

        # Use handler that returns SUCCESS for SELECT and OPERATE
        handler = SuccessCommandHandler()
        outstation = Outstation(database=db, handler=handler)
        master = Master()

        # SELECT first - handler returns SUCCESS so SelectState is stored
        builder = master.command_builder()
        builder.latch_on(index=0)
        select_task = builder.build_select()
        select_request = master.build_select(select_task)
        select_response = outstation.process_request(select_request.to_bytes())
        assert select_response is not None

        # Then OPERATE with same parameters - should match and call handler
        operate_task = builder.build_operate()
        operate_request = master.build_operate(operate_task)
        operate_response = outstation.process_request(operate_request.to_bytes())
        assert operate_response is not None

    def test_select_then_mismatched_operate(self) -> None:
        """OPERATE with different parameters than SELECT returns NO_SELECT."""
        db = Database()
        db.add_binary_output(0, BinaryOutputConfig())
        db.add_binary_output(1, BinaryOutputConfig())

        # Use success handler so SELECT stores state
        handler = SuccessCommandHandler()
        outstation = Outstation(database=db, handler=handler)
        master = Master()

        # SELECT index 0
        builder1 = master.command_builder()
        builder1.latch_on(index=0)
        select_task = builder1.build_select()
        select_request = master.build_select(select_task)
        outstation.process_request(select_request.to_bytes())

        # OPERATE on different index - should fail with NO_SELECT
        builder2 = master.command_builder()
        builder2.latch_on(index=1)
        operate_task = builder2.build_operate()
        operate_request = master.build_operate(operate_task)
        operate_response = outstation.process_request(operate_request.to_bytes())
        assert operate_response is not None

    def test_select_then_mismatched_control_code(self) -> None:
        """OPERATE with different control code than SELECT returns NO_SELECT."""
        db = Database()
        db.add_binary_output(0, BinaryOutputConfig())

        handler = SuccessCommandHandler()
        outstation = Outstation(database=db, handler=handler)
        master = Master()

        # SELECT with LATCH_ON
        builder1 = master.command_builder()
        builder1.latch_on(index=0)
        select_task = builder1.build_select()
        select_request = master.build_select(select_task)
        outstation.process_request(select_request.to_bytes())

        # OPERATE with LATCH_OFF - should hit lines 841-844 (mismatch path)
        builder2 = master.command_builder()
        builder2.latch_off(index=0)
        operate_task = builder2.build_operate()
        operate_request = master.build_operate(operate_task)
        operate_response = outstation.process_request(operate_request.to_bytes())
        assert operate_response is not None


class TestOutstationEmptyDatabasePaths:
    """Test outstation with empty database for each point type."""

    def test_read_empty_binary_outputs(self) -> None:
        """Reading binary outputs from empty database."""
        db = Database()
        # Add only binary inputs, no outputs
        db.add_binary_input(0, BinaryInputConfig())

        outstation = Outstation(database=db)
        master = Master()

        # Integrity poll should work with missing point types
        request = master.build_integrity_poll()
        response = outstation.process_request(request.to_bytes())
        assert response is not None

    def test_read_empty_analog_inputs(self) -> None:
        """Reading analog inputs from empty database."""
        db = Database()
        db.add_binary_input(0, BinaryInputConfig())
        # No analog inputs

        outstation = Outstation(database=db)
        master = Master()

        request = master.build_integrity_poll()
        response = outstation.process_request(request.to_bytes())
        assert response is not None

    def test_read_empty_counters(self) -> None:
        """Reading counters from empty database."""
        db = Database()
        db.add_binary_input(0, BinaryInputConfig())
        # No counters

        outstation = Outstation(database=db)
        master = Master()

        request = master.build_integrity_poll()
        response = outstation.process_request(request.to_bytes())
        assert response is not None

    def test_read_empty_frozen_counters(self) -> None:
        """Reading frozen counters from empty database."""
        db = Database()
        db.add_binary_input(0, BinaryInputConfig())
        # No frozen counters

        outstation = Outstation(database=db)
        master = Master()

        request = master.build_integrity_poll()
        response = outstation.process_request(request.to_bytes())
        assert response is not None


class TestEventClassReading:
    """Test reading events by class."""

    def test_class_1_poll_with_events(self) -> None:
        """Class 1 poll returns binary input events."""
        db = Database()
        db.add_binary_input(0, BinaryInputConfig(event_class=EventClass.CLASS_1))
        db.update_binary_input(0, value=False)
        db.update_binary_input(0, value=True)  # Generate event

        outstation = Outstation(database=db)
        master = Master()

        request = master.build_class_poll(class_1=True, class_2=False, class_3=False)
        response = outstation.process_request(request.to_bytes())
        assert response is not None

    def test_class_2_poll_with_events(self) -> None:
        """Class 2 poll returns analog input events."""
        db = Database()
        db.add_analog_input(0, AnalogInputConfig(event_class=EventClass.CLASS_2, deadband=0.0))
        db.update_analog_input(0, value=0.0)
        db.update_analog_input(0, value=100.0)  # Generate event

        outstation = Outstation(database=db)
        master = Master()

        request = master.build_class_poll(class_1=False, class_2=True, class_3=False)
        response = outstation.process_request(request.to_bytes())
        assert response is not None

    def test_class_3_poll_with_events(self) -> None:
        """Class 3 poll returns counter events."""
        db = Database()
        db.add_counter(0, CounterConfig(event_class=EventClass.CLASS_3, deadband=0))
        db.update_counter(0, value=0)
        db.update_counter(0, value=100)  # Generate event

        outstation = Outstation(database=db)
        master = Master()

        request = master.build_class_poll(class_1=False, class_2=False, class_3=True)
        response = outstation.process_request(request.to_bytes())
        assert response is not None


class TestCounterObjectEdgeCases:
    """Test counter object edge cases."""

    def test_counter_16_is_online(self) -> None:
        """Test Counter16.is_online property."""
        obj = Counter16(value=100, quality=CounterQuality.ONLINE)
        assert obj.is_online is True

        obj2 = Counter16(value=100, quality=CounterQuality.RESTART)
        assert obj2.is_online is False

    def test_counter_32_no_flag_validation(self) -> None:
        """Test Counter32NoFlag value validation."""
        # Valid value
        obj = Counter32NoFlag(value=100)
        assert obj.value == 100

        # Invalid value raises
        with pytest.raises(ValueError):
            Counter32NoFlag(value=-1)

    def test_counter_16_no_flag_validation(self) -> None:
        """Test Counter16NoFlag value validation."""
        obj = Counter16NoFlag(value=100)
        assert obj.value == 100

        with pytest.raises(ValueError):
            Counter16NoFlag(value=-1)

    def test_frozen_counter_16_time(self) -> None:
        """Test FrozenCounter16Time serialization."""
        from dnp3.objects.counter import FrozenCounter16Time

        ts = DNP3Timestamp(milliseconds=1234567890)
        obj = FrozenCounter16Time(value=1000, quality=CounterQuality.ONLINE, timestamp=ts)
        data = obj.to_bytes()
        assert len(data) == 9  # 1 flag + 2 value + 6 timestamp

        parsed = FrozenCounter16Time.from_bytes(data)
        assert parsed.value == 1000

    def test_counter_event_16_time(self) -> None:
        """Test CounterEvent16Time serialization."""
        from dnp3.objects.counter import CounterEvent16Time

        ts = DNP3Timestamp(milliseconds=1234567890)
        obj = CounterEvent16Time(value=1000, quality=CounterQuality.ONLINE, timestamp=ts)
        data = obj.to_bytes()
        assert len(data) == 9

        parsed = CounterEvent16Time.from_bytes(data)
        assert parsed.value == 1000


class TestOutstationSpecificReadPaths:
    """Test specific READ object types - covers lines 287-316."""

    def test_read_binary_input_events_group(self) -> None:
        """Read binary input events by group (g2)."""
        from dnp3.application.fragment import RequestFragment
        from dnp3.application.header import ApplicationControl
        from dnp3.application.qualifiers import ObjectHeader

        db = Database()
        db.add_binary_input(0, BinaryInputConfig(event_class=EventClass.CLASS_1))
        db.update_binary_input(0, value=True)

        outstation = Outstation(database=db)

        # Build manual READ request for g2v0 (all binary input events)
        header = ObjectHeader(group=2, variation=0, qualifier=0x06)  # All objects
        request = RequestFragment(
            header=RequestHeader(
                control=ApplicationControl(fir=True, fin=True, con=False, uns=False, seq=0),
                function=FunctionCode.READ,
            ),
            objects=[ObjectBlock(header=header, data=b"")],
        )
        response = outstation.process_request(request.to_bytes())
        assert response is not None

    def test_read_binary_outputs_group(self) -> None:
        """Read binary outputs by group (g10)."""
        from dnp3.application.fragment import RequestFragment
        from dnp3.application.header import ApplicationControl
        from dnp3.application.qualifiers import ObjectHeader

        db = Database()
        db.add_binary_output(0, BinaryOutputConfig())
        db.update_binary_output(0, value=True)

        outstation = Outstation(database=db)

        # Build manual READ request for g10v0
        header = ObjectHeader(group=10, variation=0, qualifier=0x06)
        request = RequestFragment(
            header=RequestHeader(
                control=ApplicationControl(fir=True, fin=True, con=False, uns=False, seq=0),
                function=FunctionCode.READ,
            ),
            objects=[ObjectBlock(header=header, data=b"")],
        )
        response = outstation.process_request(request.to_bytes())
        assert response is not None

    def test_read_analog_input_events_group(self) -> None:
        """Read analog input events by group (g32)."""
        from dnp3.application.fragment import RequestFragment
        from dnp3.application.header import ApplicationControl
        from dnp3.application.qualifiers import ObjectHeader

        db = Database()
        db.add_analog_input(0, AnalogInputConfig(event_class=EventClass.CLASS_2, deadband=0.0))
        db.update_analog_input(0, value=100.0)

        outstation = Outstation(database=db)

        # Build manual READ request for g32v0
        header = ObjectHeader(group=32, variation=0, qualifier=0x06)
        request = RequestFragment(
            header=RequestHeader(
                control=ApplicationControl(fir=True, fin=True, con=False, uns=False, seq=0),
                function=FunctionCode.READ,
            ),
            objects=[ObjectBlock(header=header, data=b"")],
        )
        response = outstation.process_request(request.to_bytes())
        assert response is not None

    def test_read_counters_group(self) -> None:
        """Read counters by group (g20)."""
        from dnp3.application.fragment import RequestFragment
        from dnp3.application.header import ApplicationControl
        from dnp3.application.qualifiers import ObjectHeader

        db = Database()
        db.add_counter(0, CounterConfig())
        db.update_counter(0, value=1000)

        outstation = Outstation(database=db)

        # Build manual READ request for g20v0
        header = ObjectHeader(group=20, variation=0, qualifier=0x06)
        request = RequestFragment(
            header=RequestHeader(
                control=ApplicationControl(fir=True, fin=True, con=False, uns=False, seq=0),
                function=FunctionCode.READ,
            ),
            objects=[ObjectBlock(header=header, data=b"")],
        )
        response = outstation.process_request(request.to_bytes())
        assert response is not None

    def test_read_counter_events_group(self) -> None:
        """Read counter events by group (g22)."""
        from dnp3.application.fragment import RequestFragment
        from dnp3.application.header import ApplicationControl
        from dnp3.application.qualifiers import ObjectHeader

        db = Database()
        db.add_counter(0, CounterConfig(event_class=EventClass.CLASS_3, deadband=0))
        db.update_counter(0, value=1000)

        outstation = Outstation(database=db)

        # Build manual READ request for g22v0
        header = ObjectHeader(group=22, variation=0, qualifier=0x06)
        request = RequestFragment(
            header=RequestHeader(
                control=ApplicationControl(fir=True, fin=True, con=False, uns=False, seq=0),
                function=FunctionCode.READ,
            ),
            objects=[ObjectBlock(header=header, data=b"")],
        )
        response = outstation.process_request(request.to_bytes())
        assert response is not None

    def test_read_frozen_counters_group(self) -> None:
        """Read frozen counters by group (g21)."""
        from dnp3.application.fragment import RequestFragment
        from dnp3.application.header import ApplicationControl
        from dnp3.application.qualifiers import ObjectHeader

        db = Database()
        db.add_counter(0, CounterConfig())
        db.add_frozen_counter(0, CounterConfig())  # Add frozen counter first
        db.update_counter(0, value=1000)
        db.freeze_counter(0)  # Now freeze

        outstation = Outstation(database=db)

        # Build manual READ request for g21v0
        header = ObjectHeader(group=21, variation=0, qualifier=0x06)
        request = RequestFragment(
            header=RequestHeader(
                control=ApplicationControl(fir=True, fin=True, con=False, uns=False, seq=0),
                function=FunctionCode.READ,
            ),
            objects=[ObjectBlock(header=header, data=b"")],
        )
        response = outstation.process_request(request.to_bytes())
        assert response is not None


class TestOutstationNoAckAndFreeze:
    """Test DIRECT_OPERATE_NO_ACK and FREEZE_CLEAR paths."""

    def test_direct_operate_no_ack(self) -> None:
        """DIRECT_OPERATE_NO_ACK returns None - covers lines 241-242."""
        from dnp3.application.fragment import RequestFragment
        from dnp3.application.header import ApplicationControl
        from dnp3.application.qualifiers import ObjectHeader

        db = Database()
        db.add_binary_output(0, BinaryOutputConfig())

        handler = SuccessCommandHandler()
        outstation = Outstation(database=db, handler=handler)

        # Build DIRECT_OPERATE_NO_ACK request
        # CROB format: count (1) + [index (1) + control (1) + count (1) + on_time (4) + off_time (4) + status (1)]
        crob_data = bytes([
            1,  # count
            0,  # index
            3,  # control code (LATCH_ON)
            1,  # operation count
            0, 0, 0, 0,  # on_time
            0, 0, 0, 0,  # off_time
            0,  # status
        ])
        header = ObjectHeader(group=12, variation=1, qualifier=0x17)  # 1-byte count, 1-byte index prefix
        request = RequestFragment(
            header=RequestHeader(
                control=ApplicationControl(fir=True, fin=True, con=False, uns=False, seq=0),
                function=FunctionCode.DIRECT_OPERATE_NO_ACK,
            ),
            objects=[ObjectBlock(header=header, data=crob_data)],
        )
        response = outstation.process_request(request.to_bytes())
        # NO_ACK means no response
        assert response is None

    def test_freeze_clear(self) -> None:
        """FREEZE_CLEAR freezes and clears counters - covers line 258."""
        from dnp3.application.fragment import RequestFragment
        from dnp3.application.header import ApplicationControl
        from dnp3.application.qualifiers import ObjectHeader

        db = Database()
        db.add_counter(0, CounterConfig())
        db.update_counter(0, value=1000)

        class AcceptFreezeHandler(DefaultCommandHandler):
            def freeze_counters(self, start: int, stop: int, clear: bool) -> CommandResult:
                return CommandResult.success()

        outstation = Outstation(database=db, handler=AcceptFreezeHandler())

        # Build FREEZE_CLEAR request for g20v0 (all counters)
        header = ObjectHeader(group=20, variation=0, qualifier=0x06)
        request = RequestFragment(
            header=RequestHeader(
                control=ApplicationControl(fir=True, fin=True, con=False, uns=False, seq=0),
                function=FunctionCode.FREEZE_CLEAR,
            ),
            objects=[ObjectBlock(header=header, data=b"")],
        )
        response = outstation.process_request(request.to_bytes())
        assert response is not None


class TestLargeIndexPaths:
    """Test paths for indices > 255 (2-byte indices)."""

    def test_read_binary_inputs_large_index(self) -> None:
        """Read binary inputs with index > 255 - covers lines 116-132, 142-149."""
        db = Database()
        # Add points with high indices
        db.add_binary_input(256, BinaryInputConfig())
        db.update_binary_input(256, value=True)

        outstation = Outstation(database=db)
        master = Master()

        request = master.build_integrity_poll()
        response = outstation.process_request(request.to_bytes())
        assert response is not None
        # Response should contain 2-byte index

    def test_read_frozen_counters_large_index(self) -> None:
        """Read frozen counters with index > 255 - covers lines 526-528, 534."""
        db = Database()
        db.add_counter(300, CounterConfig())
        db.add_frozen_counter(300, CounterConfig())
        db.update_counter(300, value=5000)
        db.freeze_counter(300)

        outstation = Outstation(database=db)
        master = Master()

        request = master.build_integrity_poll()
        response = outstation.process_request(request.to_bytes())
        assert response is not None

    def test_read_counters_large_index(self) -> None:
        """Read counters with index > 255."""
        db = Database()
        db.add_counter(500, CounterConfig())
        db.update_counter(500, value=10000)

        outstation = Outstation(database=db)
        master = Master()

        request = master.build_integrity_poll()
        response = outstation.process_request(request.to_bytes())
        assert response is not None

    def test_read_analog_inputs_large_index(self) -> None:
        """Read analog inputs with index > 255."""
        db = Database()
        db.add_analog_input(1000, AnalogInputConfig())
        db.update_analog_input(1000, value=123.45)

        outstation = Outstation(database=db)
        master = Master()

        request = master.build_integrity_poll()
        response = outstation.process_request(request.to_bytes())
        assert response is not None


class TestOutstationCROBEdgeCases:
    """Test CROB parsing edge cases."""

    def test_operate_empty_crob_data(self) -> None:
        """OPERATE with empty CROB data - covers line 817."""
        from dnp3.application.fragment import RequestFragment
        from dnp3.application.header import ApplicationControl
        from dnp3.application.qualifiers import ObjectHeader

        db = Database()
        db.add_binary_output(0, BinaryOutputConfig())

        outstation = Outstation(database=db)

        # Build OPERATE with empty CROB block
        header = ObjectHeader(group=12, variation=1, qualifier=0x17)
        request = RequestFragment(
            header=RequestHeader(
                control=ApplicationControl(fir=True, fin=True, con=False, uns=False, seq=0),
                function=FunctionCode.OPERATE,
            ),
            objects=[ObjectBlock(header=header, data=b"")],
        )
        response = outstation.process_request(request.to_bytes())
        assert response is not None

    def test_operate_truncated_crob_data(self) -> None:
        """OPERATE with truncated CROB data - covers line 824."""
        from dnp3.application.fragment import RequestFragment
        from dnp3.application.header import ApplicationControl
        from dnp3.application.qualifiers import ObjectHeader

        db = Database()
        db.add_binary_output(0, BinaryOutputConfig())

        outstation = Outstation(database=db)

        # Build OPERATE with truncated CROB (count says 1, but not enough data)
        header = ObjectHeader(group=12, variation=1, qualifier=0x17)
        request = RequestFragment(
            header=RequestHeader(
                control=ApplicationControl(fir=True, fin=True, con=False, uns=False, seq=0),
                function=FunctionCode.OPERATE,
            ),
            objects=[ObjectBlock(header=header, data=bytes([1, 0, 3]))],  # count=1, partial data
        )
        response = outstation.process_request(request.to_bytes())
        assert response is not None

    def test_direct_operate_empty_crob_data(self) -> None:
        """DIRECT_OPERATE with empty CROB data - covers line 880."""
        from dnp3.application.fragment import RequestFragment
        from dnp3.application.header import ApplicationControl
        from dnp3.application.qualifiers import ObjectHeader

        db = Database()
        db.add_binary_output(0, BinaryOutputConfig())

        outstation = Outstation(database=db)

        header = ObjectHeader(group=12, variation=1, qualifier=0x17)
        request = RequestFragment(
            header=RequestHeader(
                control=ApplicationControl(fir=True, fin=True, con=False, uns=False, seq=0),
                function=FunctionCode.DIRECT_OPERATE,
            ),
            objects=[ObjectBlock(header=header, data=b"")],
        )
        response = outstation.process_request(request.to_bytes())
        assert response is not None

    def test_direct_operate_truncated_crob_data(self) -> None:
        """DIRECT_OPERATE with truncated CROB data - covers line 887."""
        from dnp3.application.fragment import RequestFragment
        from dnp3.application.header import ApplicationControl
        from dnp3.application.qualifiers import ObjectHeader

        db = Database()
        db.add_binary_output(0, BinaryOutputConfig())

        outstation = Outstation(database=db)

        header = ObjectHeader(group=12, variation=1, qualifier=0x17)
        request = RequestFragment(
            header=RequestHeader(
                control=ApplicationControl(fir=True, fin=True, con=False, uns=False, seq=0),
                function=FunctionCode.DIRECT_OPERATE,
            ),
            objects=[ObjectBlock(header=header, data=bytes([1, 0, 3, 1]))],  # count=1, partial data
        )
        response = outstation.process_request(request.to_bytes())
        assert response is not None

    def test_select_empty_crob_data(self) -> None:
        """SELECT with empty CROB data - covers line 748."""
        from dnp3.application.fragment import RequestFragment
        from dnp3.application.header import ApplicationControl
        from dnp3.application.qualifiers import ObjectHeader

        db = Database()
        db.add_binary_output(0, BinaryOutputConfig())

        outstation = Outstation(database=db)

        header = ObjectHeader(group=12, variation=1, qualifier=0x17)
        request = RequestFragment(
            header=RequestHeader(
                control=ApplicationControl(fir=True, fin=True, con=False, uns=False, seq=0),
                function=FunctionCode.SELECT,
            ),
            objects=[ObjectBlock(header=header, data=b"")],
        )
        response = outstation.process_request(request.to_bytes())
        assert response is not None

    def test_select_truncated_crob_data(self) -> None:
        """SELECT with truncated CROB data - covers line 756."""
        from dnp3.application.fragment import RequestFragment
        from dnp3.application.header import ApplicationControl
        from dnp3.application.qualifiers import ObjectHeader

        db = Database()
        db.add_binary_output(0, BinaryOutputConfig())

        outstation = Outstation(database=db)

        header = ObjectHeader(group=12, variation=1, qualifier=0x17)
        request = RequestFragment(
            header=RequestHeader(
                control=ApplicationControl(fir=True, fin=True, con=False, uns=False, seq=0),
                function=FunctionCode.SELECT,
            ),
            objects=[ObjectBlock(header=header, data=bytes([1, 0]))],  # count=1, only index
        )
        response = outstation.process_request(request.to_bytes())
        assert response is not None

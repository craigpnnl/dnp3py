"""Tests for the simulator channel."""

import asyncio

import pytest

from dnp3.transport_io.channel import (
    ChannelClosedError,
    ChannelError,
    ChannelState,
    ChannelTimeoutError,
    SimulatorConfig,
)
from dnp3.transport_io.simulator import (
    SimulatorChannel,
    SimulatorClient,
    SimulatorServer,
    create_channel_pair,
)


class TestSimulatorChannel:
    """Tests for SimulatorChannel."""

    def test_initial_state_closed(self) -> None:
        """New channel starts in CLOSED state."""
        channel = SimulatorChannel()
        assert channel.state == ChannelState.CLOSED
        assert channel.is_open is False

    @pytest.mark.asyncio
    async def test_open_channel(self) -> None:
        """Opening channel transitions to OPEN state."""
        channel = SimulatorChannel()
        await channel.open()
        assert channel.state == ChannelState.OPEN
        assert channel.is_open is True

    @pytest.mark.asyncio
    async def test_close_channel(self) -> None:
        """Closing channel transitions to CLOSED state."""
        channel = SimulatorChannel()
        await channel.open()
        await channel.close()
        assert channel.state == ChannelState.CLOSED
        assert channel.is_open is False

    @pytest.mark.asyncio
    async def test_close_already_closed(self) -> None:
        """Closing already closed channel is no-op."""
        channel = SimulatorChannel()
        await channel.close()  # Should not raise
        assert channel.state == ChannelState.CLOSED

    @pytest.mark.asyncio
    async def test_statistics_connect_count(self) -> None:
        """Opening channel increments connect count."""
        channel = SimulatorChannel()
        assert channel.statistics.connect_count == 0
        await channel.open()
        assert channel.statistics.connect_count == 1

    @pytest.mark.asyncio
    async def test_statistics_disconnect_count(self) -> None:
        """Closing channel increments disconnect count."""
        channel = SimulatorChannel()
        await channel.open()
        assert channel.statistics.disconnect_count == 0
        await channel.close()
        assert channel.statistics.disconnect_count == 1

    @pytest.mark.asyncio
    async def test_read_on_closed_raises(self) -> None:
        """Reading from closed channel raises error."""
        channel = SimulatorChannel()
        with pytest.raises(ChannelClosedError):
            await channel.read(100)

    @pytest.mark.asyncio
    async def test_write_on_closed_raises(self) -> None:
        """Writing to closed channel raises error."""
        channel = SimulatorChannel()
        with pytest.raises(ChannelClosedError):
            await channel.write(b"test")

    @pytest.mark.asyncio
    async def test_write_without_peer_raises(self) -> None:
        """Writing without peer raises error."""
        channel = SimulatorChannel()
        await channel.open()
        with pytest.raises(ChannelError, match="No peer"):
            await channel.write(b"test")

    def test_connect_to_peer(self) -> None:
        """Connecting to peer establishes bidirectional link."""
        a = SimulatorChannel(name="a")
        b = SimulatorChannel(name="b")
        a.connect_to(b)
        assert a.peer is b
        assert b.peer is a

    def test_connect_to_already_connected_raises(self) -> None:
        """Connecting to different peer when already connected raises."""
        a = SimulatorChannel(name="a")
        b = SimulatorChannel(name="b")
        c = SimulatorChannel(name="c")
        a.connect_to(b)
        with pytest.raises(ChannelError, match="Already connected"):
            a.connect_to(c)

    def test_connect_to_same_peer_ok(self) -> None:
        """Connecting to same peer again is ok."""
        a = SimulatorChannel(name="a")
        b = SimulatorChannel(name="b")
        a.connect_to(b)
        a.connect_to(b)  # Should not raise
        assert a.peer is b


class TestChannelPairCommunication:
    """Tests for communication between channel pairs."""

    @pytest.mark.asyncio
    async def test_write_and_read(self) -> None:
        """Data written to one channel can be read from peer."""
        a, b = create_channel_pair()
        await a.open()
        await b.open()

        await a.write(b"hello")
        data = await b.read(100)
        assert data == b"hello"

    @pytest.mark.asyncio
    async def test_bidirectional_communication(self) -> None:
        """Both channels can send and receive."""
        a, b = create_channel_pair()
        await a.open()
        await b.open()

        await a.write(b"from a")
        await b.write(b"from b")

        data_a = await a.read(100)
        data_b = await b.read(100)

        assert data_a == b"from b"
        assert data_b == b"from a"

    @pytest.mark.asyncio
    async def test_partial_read(self) -> None:
        """Can read less than available data."""
        a, b = create_channel_pair()
        await a.open()
        await b.open()

        await a.write(b"hello world")
        data1 = await b.read(5)
        data2 = await b.read(6)

        assert data1 == b"hello"
        assert data2 == b" world"

    @pytest.mark.asyncio
    async def test_read_exactly(self) -> None:
        """read_exactly returns exact number of bytes."""
        a, b = create_channel_pair()
        await a.open()
        await b.open()

        await a.write(b"hello")
        data = await b.read_exactly(5)
        assert data == b"hello"

    @pytest.mark.asyncio
    async def test_read_exactly_multiple_writes(self) -> None:
        """read_exactly accumulates across multiple writes."""
        a, b = create_channel_pair()
        await a.open()
        await b.open()

        await a.write(b"hel")
        await a.write(b"lo")
        data = await b.read_exactly(5)
        assert data == b"hello"

    @pytest.mark.asyncio
    async def test_write_all(self) -> None:
        """write_all sends all data."""
        a, b = create_channel_pair()
        await a.open()
        await b.open()

        await a.write_all(b"complete message")
        data = await b.read(100)
        assert data == b"complete message"

    @pytest.mark.asyncio
    async def test_statistics_bytes_sent(self) -> None:
        """Writing updates bytes_sent statistic."""
        a, b = create_channel_pair()
        await a.open()
        await b.open()

        await a.write(b"12345")
        assert a.statistics.bytes_sent == 5

    @pytest.mark.asyncio
    async def test_statistics_bytes_received(self) -> None:
        """Reading updates bytes_received statistic."""
        a, b = create_channel_pair()
        await a.open()
        await b.open()

        await a.write(b"12345")
        await b.read(100)
        assert b.statistics.bytes_received == 5

    @pytest.mark.asyncio
    async def test_statistics_messages_sent(self) -> None:
        """Writing updates messages_sent statistic."""
        a, b = create_channel_pair()
        await a.open()
        await b.open()

        await a.write(b"msg1")
        await a.write(b"msg2")
        assert a.statistics.messages_sent == 2

    @pytest.mark.asyncio
    async def test_close_signals_eof(self) -> None:
        """Closing channel signals EOF to peer."""
        a, b = create_channel_pair()
        await a.open()
        await b.open()

        await a.close()
        data = await b.read(100)
        assert data == b""  # EOF

    @pytest.mark.asyncio
    async def test_read_exactly_eof_raises(self) -> None:
        """read_exactly raises on EOF before requested bytes."""
        a, b = create_channel_pair()
        await a.open()
        await b.open()

        await a.write(b"hi")
        await a.close()

        with pytest.raises(ChannelClosedError, match="EOF"):
            await b.read_exactly(10)


class TestChannelPairFactory:
    """Tests for create_channel_pair factory."""

    def test_creates_connected_pair(self) -> None:
        """Factory creates connected channels."""
        a, b = create_channel_pair()
        assert a.peer is b
        assert b.peer is a

    def test_shared_config(self) -> None:
        """Shared config applies to both channels."""
        config = SimulatorConfig(latency=0.1)
        a, b = create_channel_pair(config=config)
        assert a.config.latency == 0.1
        assert b.config.latency == 0.1

    def test_separate_configs(self) -> None:
        """Can set different configs for each channel."""
        config_a = SimulatorConfig(latency=0.1)
        config_b = SimulatorConfig(latency=0.2)
        a, b = create_channel_pair(config_a=config_a, config_b=config_b)
        assert a.config.latency == 0.1
        assert b.config.latency == 0.2

    def test_channel_names(self) -> None:
        """Factory sets channel names."""
        a, b = create_channel_pair()
        assert a.name == "channel_a"
        assert b.name == "channel_b"


class TestSimulatedConditions:
    """Tests for simulated network conditions."""

    @pytest.mark.asyncio
    async def test_simulated_latency(self) -> None:
        """Latency delays read operations."""
        config = SimulatorConfig(latency=0.05)
        a, b = create_channel_pair(config=config)
        await a.open()
        await b.open()

        await a.write(b"test")

        start = asyncio.get_event_loop().time()
        await b.read(100)
        elapsed = asyncio.get_event_loop().time() - start

        assert elapsed >= 0.05

    @pytest.mark.asyncio
    async def test_read_timeout(self) -> None:
        """Read times out when no data available."""
        config = SimulatorConfig(read_timeout=0.05)
        a, b = create_channel_pair(config=config)
        await a.open()
        await b.open()

        with pytest.raises(ChannelTimeoutError):
            await b.read(100)


class TestSimulatorServer:
    """Tests for SimulatorServer."""

    def test_initial_state(self) -> None:
        """Server starts in CLOSED state."""
        server = SimulatorServer()
        assert server.state == ChannelState.CLOSED
        assert server.is_listening is False
        assert server.local_address is None

    @pytest.mark.asyncio
    async def test_start_server(self) -> None:
        """Starting server transitions to OPEN state."""
        server = SimulatorServer()
        await server.start()
        assert server.state == ChannelState.OPEN
        assert server.is_listening is True
        assert server.local_address is not None

    @pytest.mark.asyncio
    async def test_stop_server(self) -> None:
        """Stopping server transitions to CLOSED state."""
        server = SimulatorServer()
        await server.start()
        await server.stop()
        assert server.state == ChannelState.CLOSED
        assert server.is_listening is False

    @pytest.mark.asyncio
    async def test_accept_raises_when_not_listening(self) -> None:
        """Accept raises when server not listening."""
        server = SimulatorServer()
        with pytest.raises(ChannelClosedError):
            await server.accept()


class TestSimulatorClient:
    """Tests for SimulatorClient."""

    def test_initial_state(self) -> None:
        """Client starts disconnected."""
        client = SimulatorClient()
        assert client.channel is None
        assert client.is_connected is False

    @pytest.mark.asyncio
    async def test_connect_to_server(self) -> None:
        """Client can connect to server."""
        server = SimulatorServer()
        await server.start()

        client = SimulatorClient()
        channel = await client.connect(server)

        assert client.is_connected is True
        assert channel.is_open is True

    @pytest.mark.asyncio
    async def test_disconnect(self) -> None:
        """Client can disconnect."""
        server = SimulatorServer()
        await server.start()

        client = SimulatorClient()
        await client.connect(server)
        await client.disconnect()

        assert client.is_connected is False

    @pytest.mark.asyncio
    async def test_connect_raises_when_server_not_listening(self) -> None:
        """Connect raises when server not listening."""
        server = SimulatorServer()
        client = SimulatorClient()

        with pytest.raises(ChannelError, match="not listening"):
            await client.connect(server)


class TestClientServerCommunication:
    """Tests for client/server communication."""

    @pytest.mark.asyncio
    async def test_basic_communication(self) -> None:
        """Client and server can exchange data."""
        server = SimulatorServer()
        await server.start()

        client = SimulatorClient()
        client_channel = await client.connect(server)
        server_channel = await server.accept()

        await server_channel.open()

        # Client sends to server
        await client_channel.write(b"request")
        data = await server_channel.read(100)
        assert data == b"request"

        # Server sends to client
        await server_channel.write(b"response")
        data = await client_channel.read(100)
        assert data == b"response"

    @pytest.mark.asyncio
    async def test_multiple_clients(self) -> None:
        """Server can handle multiple clients."""
        server = SimulatorServer()
        await server.start()

        client1 = SimulatorClient(name="client1")
        client2 = SimulatorClient(name="client2")

        client1_channel = await client1.connect(server)
        server_channel1 = await server.accept()
        await server_channel1.open()

        client2_channel = await client2.connect(server)
        server_channel2 = await server.accept()
        await server_channel2.open()

        assert server.connection_count == 2

        # Both can communicate independently
        await client1_channel.write(b"from client1")
        await client2_channel.write(b"from client2")

        data1 = await server_channel1.read(100)
        data2 = await server_channel2.read(100)

        assert data1 == b"from client1"
        assert data2 == b"from client2"

    @pytest.mark.asyncio
    async def test_server_stop_closes_connections(self) -> None:
        """Stopping server closes all client connections."""
        server = SimulatorServer()
        await server.start()

        client = SimulatorClient()
        await client.connect(server)
        server_channel = await server.accept()
        await server_channel.open()

        await server.stop()

        assert server_channel.state == ChannelState.CLOSED
        assert server.connection_count == 0


class TestChannelProtocolCompliance:
    """Tests that SimulatorChannel matches Channel protocol."""

    def test_has_state_property(self) -> None:
        """Channel has state property."""
        channel = SimulatorChannel()
        assert hasattr(channel, "state")
        assert isinstance(channel.state, ChannelState)

    def test_has_is_open_property(self) -> None:
        """Channel has is_open property."""
        channel = SimulatorChannel()
        assert hasattr(channel, "is_open")
        assert isinstance(channel.is_open, bool)

    def test_has_statistics_property(self) -> None:
        """Channel has statistics property."""
        channel = SimulatorChannel()
        assert hasattr(channel, "statistics")

    @pytest.mark.asyncio
    async def test_has_open_method(self) -> None:
        """Channel has open method."""
        channel = SimulatorChannel()
        assert hasattr(channel, "open")
        await channel.open()

    @pytest.mark.asyncio
    async def test_has_close_method(self) -> None:
        """Channel has close method."""
        channel = SimulatorChannel()
        await channel.open()
        assert hasattr(channel, "close")
        await channel.close()

    @pytest.mark.asyncio
    async def test_has_read_method(self) -> None:
        """Channel has read method."""
        a, b = create_channel_pair()
        await a.open()
        await b.open()
        await a.write(b"x")
        assert hasattr(b, "read")
        await b.read(1)

    @pytest.mark.asyncio
    async def test_has_write_method(self) -> None:
        """Channel has write method."""
        a, b = create_channel_pair()
        await a.open()
        await b.open()
        assert hasattr(a, "write")
        await a.write(b"x")

    @pytest.mark.asyncio
    async def test_has_read_exactly_method(self) -> None:
        """Channel has read_exactly method."""
        a, b = create_channel_pair()
        await a.open()
        await b.open()
        await a.write(b"xx")
        assert hasattr(b, "read_exactly")
        await b.read_exactly(2)

    @pytest.mark.asyncio
    async def test_has_write_all_method(self) -> None:
        """Channel has write_all method."""
        a, b = create_channel_pair()
        await a.open()
        await b.open()
        assert hasattr(a, "write_all")
        await a.write_all(b"x")

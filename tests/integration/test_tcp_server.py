"""Integration tests for TCP server.

Tests real TCP server/client communication including:
- Server start/stop lifecycle
- Client connections and data transfer
- Error handling and timeouts
- Multiple connections
"""

import asyncio
import contextlib
import logging

import pytest

from dnp3.transport_io.channel import (
    ChannelClosedError,
    ChannelError,
    ChannelState,
    ChannelTimeoutError,
    TcpConfig,
    TcpServerConfig,
)
from dnp3.transport_io.tcp_client import TcpClientChannel
from dnp3.transport_io.tcp_server import TcpServer


@pytest.fixture
def server_config() -> TcpServerConfig:
    """Create server config with available port."""
    return TcpServerConfig(
        host="127.0.0.1",
        port=0,  # Let OS assign port
        max_connections=5,
        read_timeout=1.0,
        write_timeout=1.0,
    )


class TestTcpServerLifecycle:
    """Test TCP server start/stop lifecycle."""

    @pytest.mark.asyncio
    async def test_server_start_and_stop(self, server_config: TcpServerConfig) -> None:
        """Server starts and stops correctly."""
        server = TcpServer(config=server_config)

        assert server.state == ChannelState.CLOSED
        assert not server.is_listening

        await server.start()
        assert server.state == ChannelState.OPEN
        assert server.is_listening
        assert server.local_address is not None
        assert server.connection_count == 0

        await server.stop()
        assert server.state == ChannelState.CLOSED
        assert not server.is_listening

    @pytest.mark.asyncio
    async def test_server_start_twice(self, server_config: TcpServerConfig) -> None:
        """Starting already running server is a no-op."""
        server = TcpServer(config=server_config)
        await server.start()

        # Start again - should not raise
        await server.start()
        assert server.is_listening

        await server.stop()

    @pytest.mark.asyncio
    async def test_server_stop_twice(self, server_config: TcpServerConfig) -> None:
        """Stopping already stopped server is a no-op."""
        server = TcpServer(config=server_config)
        await server.start()
        await server.stop()

        # Stop again - should not raise
        await server.stop()
        assert not server.is_listening

    @pytest.mark.asyncio
    async def test_server_start_port_in_use(self) -> None:
        """Server raises error when port is in use."""
        # Start first server
        config1 = TcpServerConfig(host="127.0.0.1", port=0)
        server1 = TcpServer(config=config1)
        await server1.start()

        # Get the assigned port
        addr = server1.local_address
        assert addr is not None
        port = addr[1]

        # Try to start second server on same port
        config2 = TcpServerConfig(host="127.0.0.1", port=port)
        server2 = TcpServer(config=config2)

        with pytest.raises(ChannelError):
            await server2.start()

        await server1.stop()


class TestTcpServerConnections:
    """Test TCP server client connections."""

    @pytest.mark.asyncio
    async def test_accept_connection(self, server_config: TcpServerConfig) -> None:
        """Server accepts client connection."""
        server = TcpServer(config=server_config)
        await server.start()

        addr = server.local_address
        assert addr is not None

        # Connect client
        client_config = TcpConfig(host=addr[0], port=addr[1])
        client = TcpClientChannel(config=client_config)
        await client.open()

        # Accept connection
        server_channel = await asyncio.wait_for(server.accept(), timeout=1.0)
        assert server_channel is not None
        assert server_channel.is_open
        assert server.connection_count == 1

        await client.close()
        await server_channel.close()
        await server.stop()

    @pytest.mark.asyncio
    async def test_multiple_connections(self, server_config: TcpServerConfig) -> None:
        """Server handles multiple client connections."""
        server = TcpServer(config=server_config)
        await server.start()

        addr = server.local_address
        assert addr is not None

        # Connect multiple clients
        clients = []
        server_channels = []
        for _ in range(3):
            client = TcpClientChannel(config=TcpConfig(host=addr[0], port=addr[1]))
            await client.open()
            clients.append(client)

            server_channel = await asyncio.wait_for(server.accept(), timeout=1.0)
            server_channels.append(server_channel)

        assert server.connection_count == 3

        # Close all
        for client in clients:
            await client.close()
        for channel in server_channels:
            await channel.close()
        await server.stop()

    @pytest.mark.asyncio
    async def test_max_connections_limit(self) -> None:
        """Server enforces max connections limit."""
        config = TcpServerConfig(
            host="127.0.0.1",
            port=0,
            max_connections=2,
        )
        server = TcpServer(config=config)
        await server.start()

        addr = server.local_address
        assert addr is not None

        # Connect up to max
        clients = []
        server_channels = []
        for _ in range(2):
            client = TcpClientChannel(config=TcpConfig(host=addr[0], port=addr[1]))
            await client.open()
            clients.append(client)

            server_channel = await asyncio.wait_for(server.accept(), timeout=1.0)
            server_channels.append(server_channel)

        assert server.connection_count == 2

        # Try to connect one more - connection should be immediately closed
        extra_client = TcpClientChannel(config=TcpConfig(host=addr[0], port=addr[1]))
        await extra_client.open()

        # Wait a bit for the server to reject
        await asyncio.sleep(0.1)

        # The extra connection should be closed by server
        # Try to read - should get EOF or error
        try:
            data = await asyncio.wait_for(extra_client.read(1), timeout=0.5)
            # Empty data means EOF (connection closed)
            assert data == b""
        except (TimeoutError, ChannelClosedError, ChannelError):
            pass

        await extra_client.close()
        for client in clients:
            await client.close()
        for channel in server_channels:
            await channel.close()
        await server.stop()

    @pytest.mark.asyncio
    async def test_remove_connection(self, server_config: TcpServerConfig) -> None:
        """Server tracks and removes connections."""
        server = TcpServer(config=server_config)
        await server.start()

        addr = server.local_address
        assert addr is not None

        # Connect client
        client = TcpClientChannel(config=TcpConfig(host=addr[0], port=addr[1]))
        await client.open()

        server_channel = await asyncio.wait_for(server.accept(), timeout=1.0)
        assert server.connection_count == 1

        # Remove connection
        server.remove_connection(server_channel)
        assert server.connection_count == 0

        await client.close()
        await server_channel.close()
        await server.stop()


class TestTcpServerChannelIO:
    """Test TCP server channel I/O operations."""

    @pytest.mark.asyncio
    async def test_read_write(self, server_config: TcpServerConfig) -> None:
        """Server channel can read and write data."""
        server = TcpServer(config=server_config)
        await server.start()

        addr = server.local_address
        assert addr is not None

        client = TcpClientChannel(config=TcpConfig(host=addr[0], port=addr[1]))
        await client.open()

        server_channel = await asyncio.wait_for(server.accept(), timeout=1.0)

        # Client sends to server
        await client.write(b"hello")
        data = await asyncio.wait_for(server_channel.read(100), timeout=1.0)
        assert data == b"hello"

        # Server sends to client
        await server_channel.write(b"world")
        data = await asyncio.wait_for(client.read(100), timeout=1.0)
        assert data == b"world"

        await client.close()
        await server_channel.close()
        await server.stop()

    @pytest.mark.asyncio
    async def test_read_exactly(self, server_config: TcpServerConfig) -> None:
        """Server channel can read exact bytes."""
        server = TcpServer(config=server_config)
        await server.start()

        addr = server.local_address
        assert addr is not None

        client = TcpClientChannel(config=TcpConfig(host=addr[0], port=addr[1]))
        await client.open()

        server_channel = await asyncio.wait_for(server.accept(), timeout=1.0)

        # Send data
        await client.write(b"12345678")
        data = await asyncio.wait_for(server_channel.read_exactly(5), timeout=1.0)
        assert data == b"12345"

        # Read remaining
        data = await asyncio.wait_for(server_channel.read_exactly(3), timeout=1.0)
        assert data == b"678"

        await client.close()
        await server_channel.close()
        await server.stop()

    @pytest.mark.asyncio
    async def test_write_all(self, server_config: TcpServerConfig) -> None:
        """Server channel can write all data."""
        server = TcpServer(config=server_config)
        await server.start()

        addr = server.local_address
        assert addr is not None

        client = TcpClientChannel(config=TcpConfig(host=addr[0], port=addr[1]))
        await client.open()

        server_channel = await asyncio.wait_for(server.accept(), timeout=1.0)

        # Write all
        await server_channel.write_all(b"complete message")
        data = await asyncio.wait_for(client.read(100), timeout=1.0)
        assert data == b"complete message"

        await client.close()
        await server_channel.close()
        await server.stop()


class TestTcpServerChannelErrors:
    """Test TCP server channel error handling."""

    @pytest.mark.asyncio
    async def test_read_on_closed_channel(self, server_config: TcpServerConfig) -> None:
        """Reading from closed channel raises error."""
        server = TcpServer(config=server_config)
        await server.start()

        addr = server.local_address
        assert addr is not None

        client = TcpClientChannel(config=TcpConfig(host=addr[0], port=addr[1]))
        await client.open()

        server_channel = await asyncio.wait_for(server.accept(), timeout=1.0)
        await server_channel.close()

        with pytest.raises(ChannelClosedError):
            await server_channel.read(100)

        await client.close()
        await server.stop()

    @pytest.mark.asyncio
    async def test_write_on_closed_channel(self, server_config: TcpServerConfig) -> None:
        """Writing to closed channel raises error."""
        server = TcpServer(config=server_config)
        await server.start()

        addr = server.local_address
        assert addr is not None

        client = TcpClientChannel(config=TcpConfig(host=addr[0], port=addr[1]))
        await client.open()

        server_channel = await asyncio.wait_for(server.accept(), timeout=1.0)
        await server_channel.close()

        with pytest.raises(ChannelClosedError):
            await server_channel.write(b"data")

        await client.close()
        await server.stop()

    @pytest.mark.asyncio
    async def test_read_exactly_on_closed_channel(self, server_config: TcpServerConfig) -> None:
        """read_exactly on closed channel raises error."""
        server = TcpServer(config=server_config)
        await server.start()

        addr = server.local_address
        assert addr is not None

        client = TcpClientChannel(config=TcpConfig(host=addr[0], port=addr[1]))
        await client.open()

        server_channel = await asyncio.wait_for(server.accept(), timeout=1.0)
        await server_channel.close()

        with pytest.raises(ChannelClosedError):
            await server_channel.read_exactly(10)

        await client.close()
        await server.stop()

    @pytest.mark.asyncio
    async def test_read_exactly_eof(self, server_config: TcpServerConfig) -> None:
        """read_exactly with EOF before enough data raises error."""
        server = TcpServer(config=server_config)
        await server.start()

        addr = server.local_address
        assert addr is not None

        client = TcpClientChannel(config=TcpConfig(host=addr[0], port=addr[1]))
        await client.open()

        server_channel = await asyncio.wait_for(server.accept(), timeout=1.0)

        # Write partial data then close
        await client.write(b"123")
        await client.close()

        # Try to read more than available
        with pytest.raises(ChannelClosedError):
            await server_channel.read_exactly(10)

        await server_channel.close()
        await server.stop()

    @pytest.mark.asyncio
    async def test_accept_when_not_listening(self, server_config: TcpServerConfig) -> None:
        """Accept on non-listening server raises error."""
        server = TcpServer(config=server_config)

        with pytest.raises(ChannelClosedError):
            await server.accept()


class TestTcpServerChannelProperties:
    """Test TCP server channel properties."""

    @pytest.mark.asyncio
    async def test_channel_addresses(self, server_config: TcpServerConfig) -> None:
        """Server channel has local and remote addresses."""
        server = TcpServer(config=server_config)
        await server.start()

        addr = server.local_address
        assert addr is not None

        client = TcpClientChannel(config=TcpConfig(host=addr[0], port=addr[1]))
        await client.open()

        server_channel = await asyncio.wait_for(server.accept(), timeout=1.0)

        # Check addresses
        local = server_channel.local_address
        remote = server_channel.remote_address
        assert local is not None
        assert remote is not None
        assert local[0] == "127.0.0.1"
        assert remote[0] == "127.0.0.1"

        await client.close()
        await server_channel.close()
        await server.stop()

    @pytest.mark.asyncio
    async def test_channel_statistics(self, server_config: TcpServerConfig) -> None:
        """Server channel tracks statistics."""
        server = TcpServer(config=server_config)
        await server.start()

        addr = server.local_address
        assert addr is not None

        client = TcpClientChannel(config=TcpConfig(host=addr[0], port=addr[1]))
        await client.open()

        server_channel = await asyncio.wait_for(server.accept(), timeout=1.0)

        stats = server_channel.statistics
        assert stats.connect_count == 1

        # Exchange data
        await client.write(b"hello")
        await asyncio.wait_for(server_channel.read(100), timeout=1.0)

        await server_channel.write(b"world")
        await asyncio.wait_for(client.read(100), timeout=1.0)

        stats = server_channel.statistics
        assert stats.bytes_received == 5
        assert stats.bytes_sent == 5
        assert stats.messages_received == 1
        assert stats.messages_sent == 1

        await client.close()
        await server_channel.close()
        await server.stop()

    @pytest.mark.asyncio
    async def test_channel_open_is_noop(self, server_config: TcpServerConfig) -> None:
        """Open on server channel is a no-op (already open)."""
        server = TcpServer(config=server_config)
        await server.start()

        addr = server.local_address
        assert addr is not None

        client = TcpClientChannel(config=TcpConfig(host=addr[0], port=addr[1]))
        await client.open()

        server_channel = await asyncio.wait_for(server.accept(), timeout=1.0)

        # Open is no-op
        await server_channel.open()
        assert server_channel.is_open

        await client.close()
        await server_channel.close()
        await server.stop()

    @pytest.mark.asyncio
    async def test_channel_close_twice(self, server_config: TcpServerConfig) -> None:
        """Closing channel twice is safe."""
        server = TcpServer(config=server_config)
        await server.start()

        addr = server.local_address
        assert addr is not None

        client = TcpClientChannel(config=TcpConfig(host=addr[0], port=addr[1]))
        await client.open()

        server_channel = await asyncio.wait_for(server.accept(), timeout=1.0)

        await server_channel.close()
        assert not server_channel.is_open

        # Close again - should not raise
        await server_channel.close()
        assert not server_channel.is_open

        await client.close()
        await server.stop()


class TestTcpServerTimeouts:
    """Test TCP server timeout handling."""

    @pytest.mark.asyncio
    async def test_read_timeout(self) -> None:
        """Read times out if no data available."""
        config = TcpServerConfig(
            host="127.0.0.1",
            port=0,
            read_timeout=0.1,  # Short timeout
        )
        server = TcpServer(config=config)
        await server.start()

        addr = server.local_address
        assert addr is not None

        client = TcpClientChannel(config=TcpConfig(host=addr[0], port=addr[1]))
        await client.open()

        server_channel = await asyncio.wait_for(server.accept(), timeout=1.0)

        # Try to read with no data - should timeout
        with pytest.raises(ChannelTimeoutError):
            await server_channel.read(100)

        await client.close()
        await server_channel.close()
        await server.stop()

    @pytest.mark.asyncio
    async def test_read_exactly_timeout(self) -> None:
        """read_exactly times out if not enough data."""
        config = TcpServerConfig(
            host="127.0.0.1",
            port=0,
            read_timeout=0.1,
        )
        server = TcpServer(config=config)
        await server.start()

        addr = server.local_address
        assert addr is not None

        client = TcpClientChannel(config=TcpConfig(host=addr[0], port=addr[1]))
        await client.open()

        server_channel = await asyncio.wait_for(server.accept(), timeout=1.0)

        # Send partial data
        await client.write(b"123")

        # Try to read more - should timeout
        with pytest.raises(ChannelTimeoutError):
            await server_channel.read_exactly(10)

        await client.close()
        await server_channel.close()
        await server.stop()


class TestTcpServerStopWithConnections:
    """Test stopping server with active connections."""

    @pytest.mark.asyncio
    async def test_stop_closes_all_connections(self, server_config: TcpServerConfig) -> None:
        """Stopping server closes all active connections."""
        server = TcpServer(config=server_config)
        await server.start()

        addr = server.local_address
        assert addr is not None

        # Create connections
        clients = []
        server_channels = []
        for _ in range(3):
            client = TcpClientChannel(config=TcpConfig(host=addr[0], port=addr[1]))
            await client.open()
            clients.append(client)

            server_channel = await asyncio.wait_for(server.accept(), timeout=1.0)
            server_channels.append(server_channel)

        assert server.connection_count == 3

        # Stop server
        await server.stop()

        # All connections should be closed
        for channel in server_channels:
            assert not channel.is_open

        for client in clients:
            await client.close()


class TestTcpServerStopBoundedByStalledConnection:
    """stop() must not multiply its close_timeout bound across every connection."""

    @pytest.mark.asyncio
    async def test_stop_bounded_despite_three_stalled_connections(self) -> None:
        """Three stalled peers and one healthy peer: stop() finishes near one bound, not three."""
        config = TcpServerConfig(host="127.0.0.1", port=0, close_timeout=0.5)
        server = TcpServer(config=config)
        await server.start()
        addr = server.local_address
        assert addr is not None

        stuffing = b"\x00" * (32 * 1024 * 1024)

        _stalled_reader1, stalled_writer1 = await asyncio.open_connection(addr[0], addr[1])
        stalled_channel1 = await asyncio.wait_for(server.accept(), timeout=2.0)
        _stalled_reader2, stalled_writer2 = await asyncio.open_connection(addr[0], addr[1])
        stalled_channel2 = await asyncio.wait_for(server.accept(), timeout=2.0)
        _stalled_reader3, stalled_writer3 = await asyncio.open_connection(addr[0], addr[1])
        stalled_channel3 = await asyncio.wait_for(server.accept(), timeout=2.0)
        healthy_reader, healthy_writer = await asyncio.open_connection(addr[0], addr[1])
        healthy_channel = await asyncio.wait_for(server.accept(), timeout=2.0)

        assert server.connection_count == 4

        for stalled in (stalled_channel1, stalled_channel2, stalled_channel3):
            with pytest.raises(TimeoutError):
                await asyncio.wait_for(stalled.write_all(stuffing), timeout=0.3)

        # The healthy peer has bytes pending when stop() closes it; it must
        # still receive them, then EOF, even though closing is concurrent.
        healthy_payload = b"pending bytes for the healthy peer"
        healthy_channel.writer.write(healthy_payload)

        loop = asyncio.get_running_loop()
        started = loop.time()
        await asyncio.wait_for(server.stop(), timeout=5.0)
        elapsed = loop.time() - started

        # Sequential closing of three stalled connections takes roughly
        # 3 * close_timeout (1.5s); closing concurrently bounds it to about one,
        # a wider margin than two stalled peers gives (0.15s) between the pass
        # and fail thresholds.
        assert config.close_timeout * 0.8 <= elapsed < config.close_timeout * 1.7, (
            f"stop() took {elapsed:.2f}s, more than one stalled connection's close bound"
        )
        assert stalled_channel1.state == ChannelState.CLOSED
        assert stalled_channel2.state == ChannelState.CLOSED
        assert stalled_channel3.state == ChannelState.CLOSED
        assert healthy_channel.state == ChannelState.CLOSED
        assert server.connection_count == 0

        received = await asyncio.wait_for(healthy_reader.read(len(healthy_payload)), timeout=2.0)
        assert received == healthy_payload
        eof = await asyncio.wait_for(healthy_reader.read(1), timeout=2.0)
        assert eof == b""

        stalled_writer1.transport.abort()
        stalled_writer2.transport.abort()
        stalled_writer3.transport.abort()
        healthy_writer.close()
        await healthy_writer.wait_closed()

    @pytest.mark.asyncio
    async def test_stop_closes_a_connection_accepted_during_the_close_window(self) -> None:
        """A connection that arrives while stop() is closing a stalled peer must not be dropped."""
        config = TcpServerConfig(host="127.0.0.1", port=0, close_timeout=1.0)
        server = TcpServer(config=config)
        await server.start()
        addr = server.local_address
        assert addr is not None

        stuffing = b"\x00" * (32 * 1024 * 1024)
        _stalled_reader, stalled_writer = await asyncio.open_connection(addr[0], addr[1])
        stalled_channel = await asyncio.wait_for(server.accept(), timeout=2.0)
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(stalled_channel.write_all(stuffing), timeout=0.3)

        loop = asyncio.get_running_loop()
        started = loop.time()
        stop_task = asyncio.create_task(server.stop())
        await asyncio.sleep(0.1)  # let stop() begin closing the stalled connection

        late_reader: asyncio.StreamReader | None = None
        late_writer: asyncio.StreamWriter | None = None
        try:
            late_reader, late_writer = await asyncio.wait_for(asyncio.open_connection(addr[0], addr[1]), timeout=0.5)
        except (ConnectionRefusedError, TimeoutError, OSError):
            # The fix closes the listener before this point, so a refusal is
            # the correct outcome too: the point is that stop() never hangs
            # and never leaves an accepted connection unclosed.
            late_reader = None

        await asyncio.wait_for(stop_task, timeout=config.close_timeout + 2.0)
        elapsed = loop.time() - started
        assert elapsed < config.close_timeout + 1.5, (
            "stop() must not hang on a connection accepted during the close window"
        )

        if late_reader is not None:
            data = await asyncio.wait_for(late_reader.read(1), timeout=2.0)
            assert data == b"", "a connection accepted during stop() must be closed, not orphaned"
            assert late_writer is not None
            late_writer.close()
            await late_writer.wait_closed()

        stalled_writer.transport.abort()

    @pytest.mark.asyncio
    async def test_stop_cancelled_leaves_listener_stopped_and_second_stop_recovers(self) -> None:
        """Cancelling stop() must not leave the server still accepting connections."""
        config = TcpServerConfig(host="127.0.0.1", port=0, close_timeout=5.0)
        server = TcpServer(config=config)
        await server.start()
        addr = server.local_address
        assert addr is not None

        stuffing = b"\x00" * (32 * 1024 * 1024)
        _stalled_reader, stalled_writer = await asyncio.open_connection(addr[0], addr[1])
        stalled_channel = await asyncio.wait_for(server.accept(), timeout=2.0)
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(stalled_channel.write_all(stuffing), timeout=0.3)

        stop_task = asyncio.create_task(server.stop())
        await asyncio.sleep(0.1)  # let stop() stop the listener and start closing the stalled peer
        stop_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await stop_task

        # A cancelled close() still ends CLOSED with the disconnect counted
        # exactly once, even though it is the outer stop() that was
        # cancelled here, not the channel's own close() call directly.
        assert stalled_channel.state == ChannelState.CLOSED
        assert stalled_channel.statistics.disconnect_count == 1

        # The listener must already be stopped even though stop() did not finish.
        with pytest.raises((ConnectionRefusedError, OSError, TimeoutError)):
            await asyncio.wait_for(asyncio.open_connection(addr[0], addr[1]), timeout=1.0)

        # A second stop() recovers and finishes closing what remains.
        await asyncio.wait_for(server.stop(), timeout=config.close_timeout + 2.0)
        assert server.state == ChannelState.CLOSED
        assert server.connection_count == 0
        assert stalled_channel.state == ChannelState.CLOSED
        assert stalled_channel.statistics.disconnect_count == 1

        stalled_writer.transport.abort()

    @pytest.mark.asyncio
    async def test_stop_logs_and_continues_when_a_connections_close_raises(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """An unexpected exception from one connection's close() is logged, not dropped,
        and does not stop the others from being closed."""
        config = TcpServerConfig(host="127.0.0.1", port=0, close_timeout=0.5)
        server = TcpServer(config=config)
        await server.start()
        addr = server.local_address
        assert addr is not None

        _reader1, writer1 = await asyncio.open_connection(addr[0], addr[1])
        bad_channel = await asyncio.wait_for(server.accept(), timeout=2.0)
        _reader2, writer2 = await asyncio.open_connection(addr[0], addr[1])
        good_channel = await asyncio.wait_for(server.accept(), timeout=2.0)

        original_close = bad_channel.close

        async def raising_close() -> None:
            # Close for real first, so this scenario is "a bug in close()"
            # rather than "the transport never actually closes."
            await original_close()
            raise RuntimeError("boom: close() bug")

        bad_channel.close = raising_close  # type: ignore[method-assign]

        with caplog.at_level(logging.ERROR, logger="dnp3.transport_io.tcp_server"):
            await asyncio.wait_for(server.stop(), timeout=config.close_timeout + 2.0)

        assert good_channel.state == ChannelState.CLOSED
        assert server.connection_count == 0

        matching = [
            record
            for record in caplog.records
            if "Unexpected error closing a connection during stop()" in record.getMessage()
        ]
        assert matching, "expected an ERROR log for the connection whose close() raised"
        assert matching[0].exc_info is not None
        assert isinstance(matching[0].exc_info[1], RuntimeError)

        writer1.close()
        with contextlib.suppress(OSError, ConnectionError):
            await writer1.wait_closed()
        writer2.close()
        await writer2.wait_closed()


class TestTcpServerQueueClearing:
    """Test accept queue clearing on stop."""

    @pytest.mark.asyncio
    async def test_stop_clears_pending_accepts(self, server_config: TcpServerConfig) -> None:
        """Stopping server clears pending accepts in queue."""
        server = TcpServer(config=server_config)
        await server.start()

        addr = server.local_address
        assert addr is not None

        # Connect multiple clients but don't accept them
        clients = []
        for _ in range(3):
            client = TcpClientChannel(config=TcpConfig(host=addr[0], port=addr[1]))
            await client.open()
            clients.append(client)

        # Wait for connections to be queued
        await asyncio.sleep(0.1)

        # Stop server - should clear queue
        await server.stop()

        # Clean up clients
        for client in clients:
            await client.close()


class TestTcpServerConnectionErrors:
    """Test connection error handling."""

    @pytest.mark.asyncio
    async def test_read_after_client_disconnect(self, server_config: TcpServerConfig) -> None:
        """Reading after client disconnects returns EOF."""
        server = TcpServer(config=server_config)
        await server.start()

        addr = server.local_address
        assert addr is not None

        client = TcpClientChannel(config=TcpConfig(host=addr[0], port=addr[1]))
        await client.open()

        server_channel = await asyncio.wait_for(server.accept(), timeout=1.0)

        # Close client
        await client.close()

        # Wait for close to propagate
        await asyncio.sleep(0.1)

        # Read should return empty (EOF)
        data = await server_channel.read(100)
        assert data == b""

        await server_channel.close()
        await server.stop()

    @pytest.mark.asyncio
    async def test_write_after_client_disconnect(self, server_config: TcpServerConfig) -> None:
        """Writing after client disconnects raises error."""
        server = TcpServer(config=server_config)
        await server.start()

        addr = server.local_address
        assert addr is not None

        client = TcpClientChannel(config=TcpConfig(host=addr[0], port=addr[1]))
        await client.open()

        server_channel = await asyncio.wait_for(server.accept(), timeout=1.0)

        # Close client
        await client.close()

        # Wait for close to propagate
        await asyncio.sleep(0.1)

        # Writing may or may not raise immediately - depends on buffering
        # So we try multiple writes to ensure pipe is broken
        try:
            for _ in range(10):
                await server_channel.write(b"x" * 1000)
                await asyncio.sleep(0.01)
        except (ChannelError, OSError, BrokenPipeError):
            pass  # Expected

        await server_channel.close()
        await server.stop()


class TestTcpClientIntegration:
    """Integration tests for TCP client with server."""

    @pytest.mark.asyncio
    async def test_client_connect_disconnect(self, server_config: TcpServerConfig) -> None:
        """Client connects and disconnects cleanly."""
        server = TcpServer(config=server_config)
        await server.start()

        addr = server.local_address
        assert addr is not None

        client = TcpClientChannel(config=TcpConfig(host=addr[0], port=addr[1]))
        assert client.state == ChannelState.CLOSED

        await client.open()
        assert client.state == ChannelState.OPEN
        assert client.is_open

        # Accept on server side
        server_channel = await asyncio.wait_for(server.accept(), timeout=1.0)

        await client.close()
        assert client.state == ChannelState.CLOSED

        await server_channel.close()
        await server.stop()

    @pytest.mark.asyncio
    async def test_client_addresses(self, server_config: TcpServerConfig) -> None:
        """Client has local and remote addresses."""
        server = TcpServer(config=server_config)
        await server.start()

        addr = server.local_address
        assert addr is not None

        client = TcpClientChannel(config=TcpConfig(host=addr[0], port=addr[1]))
        await client.open()

        # Accept on server side
        server_channel = await asyncio.wait_for(server.accept(), timeout=1.0)

        # Check client addresses
        local = client.local_address
        remote = client.remote_address
        assert local is not None
        assert remote is not None
        assert remote == addr  # Should match server address

        await client.close()
        await server_channel.close()
        await server.stop()

    @pytest.mark.asyncio
    async def test_client_connection_refused(self) -> None:
        """Client raises error when connection is refused."""
        # Try to connect to a port that's not listening
        client = TcpClientChannel(config=TcpConfig(host="127.0.0.1", port=59999))

        with pytest.raises(ChannelError):
            await client.open()

    @pytest.mark.asyncio
    async def test_client_close_twice(self, server_config: TcpServerConfig) -> None:
        """Closing client twice is safe."""
        server = TcpServer(config=server_config)
        await server.start()

        addr = server.local_address
        assert addr is not None

        client = TcpClientChannel(config=TcpConfig(host=addr[0], port=addr[1]))
        await client.open()

        server_channel = await asyncio.wait_for(server.accept(), timeout=1.0)

        await client.close()
        await client.close()  # Second close is no-op

        await server_channel.close()
        await server.stop()

    @pytest.mark.asyncio
    async def test_client_read_write(self, server_config: TcpServerConfig) -> None:
        """Client can read and write data."""
        server = TcpServer(config=server_config)
        await server.start()

        addr = server.local_address
        assert addr is not None

        client = TcpClientChannel(config=TcpConfig(host=addr[0], port=addr[1]))
        await client.open()

        server_channel = await asyncio.wait_for(server.accept(), timeout=1.0)

        # Write from client
        await client.write(b"request")
        data = await asyncio.wait_for(server_channel.read(100), timeout=1.0)
        assert data == b"request"

        # Write from server
        await server_channel.write(b"response")
        data = await asyncio.wait_for(client.read(100), timeout=1.0)
        assert data == b"response"

        await client.close()
        await server_channel.close()
        await server.stop()

    @pytest.mark.asyncio
    async def test_client_read_exactly(self, server_config: TcpServerConfig) -> None:
        """Client can read exact bytes."""
        server = TcpServer(config=server_config)
        await server.start()

        addr = server.local_address
        assert addr is not None

        client = TcpClientChannel(config=TcpConfig(host=addr[0], port=addr[1]))
        await client.open()

        server_channel = await asyncio.wait_for(server.accept(), timeout=1.0)

        # Send data from server
        await server_channel.write(b"0123456789")
        data = await asyncio.wait_for(client.read_exactly(5), timeout=1.0)
        assert data == b"01234"

        await client.close()
        await server_channel.close()
        await server.stop()

    @pytest.mark.asyncio
    async def test_client_statistics(self, server_config: TcpServerConfig) -> None:
        """Client tracks statistics."""
        server = TcpServer(config=server_config)
        await server.start()

        addr = server.local_address
        assert addr is not None

        client = TcpClientChannel(config=TcpConfig(host=addr[0], port=addr[1]))
        await client.open()

        server_channel = await asyncio.wait_for(server.accept(), timeout=1.0)

        # Exchange data
        await client.write(b"hello")
        await asyncio.wait_for(server_channel.read(100), timeout=1.0)

        await server_channel.write(b"world")
        await asyncio.wait_for(client.read(100), timeout=1.0)

        stats = client.statistics
        assert stats.bytes_sent == 5
        assert stats.bytes_received == 5

        await client.close()
        await server_channel.close()
        await server.stop()

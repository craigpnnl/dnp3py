"""Tests for TCP server channel."""

import asyncio

import pytest

from dnp3.transport_io.channel import (
    ChannelClosedError,
    ChannelState,
    TcpServerConfig,
)
from dnp3.transport_io.tcp_server import TcpServer, TcpServerChannel, serve


class TestTcpServer:
    """Tests for TcpServer."""

    def test_initial_state(self) -> None:
        """Server starts in CLOSED state."""
        server = TcpServer()
        assert server.state == ChannelState.CLOSED
        assert server.is_listening is False
        assert server.local_address is None

    def test_default_config(self) -> None:
        """Default config has sensible values."""
        server = TcpServer()
        assert server.config.host == "127.0.0.1"
        assert server.config.port == 20000
        assert server.config.backlog == 5
        assert server.config.reuse_address is True

    def test_custom_config(self) -> None:
        """Can use custom config."""
        config = TcpServerConfig(host="0.0.0.0", port=30000)
        server = TcpServer(config=config)
        assert server.config.host == "0.0.0.0"
        assert server.config.port == 30000

    @pytest.mark.asyncio
    async def test_start_server(self) -> None:
        """Server can start listening."""
        config = TcpServerConfig(host="127.0.0.1", port=0)  # Port 0 = auto-assign
        server = TcpServer(config=config)
        await server.start()

        try:
            assert server.state == ChannelState.OPEN
            assert server.is_listening is True
            assert server.local_address is not None
            assert server.local_address[0] == "127.0.0.1"
            assert server.local_address[1] > 0
        finally:
            await server.stop()

    @pytest.mark.asyncio
    async def test_stop_server(self) -> None:
        """Server can stop."""
        config = TcpServerConfig(host="127.0.0.1", port=0)
        server = TcpServer(config=config)
        await server.start()
        await server.stop()

        assert server.state == ChannelState.CLOSED
        assert server.is_listening is False

    @pytest.mark.asyncio
    async def test_accept_raises_when_not_listening(self) -> None:
        """Accept raises when server not listening."""
        server = TcpServer()
        with pytest.raises(ChannelClosedError):
            await server.accept()

    @pytest.mark.asyncio
    async def test_context_manager(self) -> None:
        """Server works as async context manager."""
        config = TcpServerConfig(host="127.0.0.1", port=0)
        async with TcpServer(config=config) as server:
            assert server.is_listening is True
        assert server.is_listening is False


class TestTcpServerWithClient:
    """Tests for TCP server with actual client connections."""

    @pytest.mark.asyncio
    async def test_accept_connection(self) -> None:
        """Server can accept client connections."""
        config = TcpServerConfig(host="127.0.0.1", port=0)
        server = TcpServer(config=config)
        await server.start()
        port = server.local_address[1]  # type: ignore[index]

        try:
            # Connect a client
            _reader, writer = await asyncio.open_connection("127.0.0.1", port)

            try:
                # Accept on server side
                channel = await asyncio.wait_for(server.accept(), timeout=2.0)
                assert isinstance(channel, TcpServerChannel)
                assert channel.is_open is True
                assert channel.remote_address is not None
                assert server.connection_count == 1
            finally:
                writer.close()
                await writer.wait_closed()
        finally:
            await server.stop()

    @pytest.mark.asyncio
    async def test_server_read_from_client(self) -> None:
        """Server can read data from client."""
        config = TcpServerConfig(host="127.0.0.1", port=0)
        server = TcpServer(config=config)
        await server.start()
        port = server.local_address[1]  # type: ignore[index]

        try:
            _reader, writer = await asyncio.open_connection("127.0.0.1", port)

            try:
                channel = await asyncio.wait_for(server.accept(), timeout=2.0)

                # Client sends data
                writer.write(b"hello from client")
                await writer.drain()

                # Server reads data
                data = await channel.read(100)
                assert data == b"hello from client"
                assert channel.statistics.bytes_received == 17
            finally:
                writer.close()
                await writer.wait_closed()
        finally:
            await server.stop()

    @pytest.mark.asyncio
    async def test_server_write_to_client(self) -> None:
        """Server can write data to client."""
        config = TcpServerConfig(host="127.0.0.1", port=0)
        server = TcpServer(config=config)
        await server.start()
        port = server.local_address[1]  # type: ignore[index]

        try:
            reader, writer = await asyncio.open_connection("127.0.0.1", port)

            try:
                channel = await asyncio.wait_for(server.accept(), timeout=2.0)

                # Server sends data
                await channel.write(b"hello from server")

                # Client reads data
                data = await reader.read(100)
                assert data == b"hello from server"
                assert channel.statistics.bytes_sent == 17
            finally:
                writer.close()
                await writer.wait_closed()
        finally:
            await server.stop()

    @pytest.mark.asyncio
    async def test_bidirectional_communication(self) -> None:
        """Server and client can exchange data bidirectionally."""
        config = TcpServerConfig(host="127.0.0.1", port=0)
        server = TcpServer(config=config)
        await server.start()
        port = server.local_address[1]  # type: ignore[index]

        try:
            reader, writer = await asyncio.open_connection("127.0.0.1", port)

            try:
                channel = await asyncio.wait_for(server.accept(), timeout=2.0)

                # Client sends
                writer.write(b"request")
                await writer.drain()

                # Server receives and responds
                request = await channel.read(100)
                await channel.write(b"response")

                # Client receives
                response = await reader.read(100)

                assert request == b"request"
                assert response == b"response"
            finally:
                writer.close()
                await writer.wait_closed()
        finally:
            await server.stop()

    @pytest.mark.asyncio
    async def test_multiple_connections(self) -> None:
        """Server can handle multiple connections."""
        config = TcpServerConfig(host="127.0.0.1", port=0)
        server = TcpServer(config=config)
        await server.start()
        port = server.local_address[1]  # type: ignore[index]

        try:
            # Connect two clients
            _reader1, writer1 = await asyncio.open_connection("127.0.0.1", port)
            _reader2, writer2 = await asyncio.open_connection("127.0.0.1", port)

            try:
                channel1 = await asyncio.wait_for(server.accept(), timeout=2.0)
                channel2 = await asyncio.wait_for(server.accept(), timeout=2.0)

                assert server.connection_count == 2

                # Both can communicate independently
                writer1.write(b"from client 1")
                await writer1.drain()
                writer2.write(b"from client 2")
                await writer2.drain()

                data1 = await channel1.read(100)
                data2 = await channel2.read(100)

                assert data1 == b"from client 1"
                assert data2 == b"from client 2"
            finally:
                writer1.close()
                await writer1.wait_closed()
                writer2.close()
                await writer2.wait_closed()
        finally:
            await server.stop()

    @pytest.mark.asyncio
    async def test_max_connections(self) -> None:
        """Server respects max_connections limit."""
        config = TcpServerConfig(host="127.0.0.1", port=0, max_connections=1)
        server = TcpServer(config=config)
        await server.start()
        port = server.local_address[1]  # type: ignore[index]

        try:
            # First connection succeeds
            _reader1, writer1 = await asyncio.open_connection("127.0.0.1", port)

            try:
                await asyncio.wait_for(server.accept(), timeout=2.0)
                assert server.connection_count == 1

                # Second connection should be rejected
                reader2, writer2 = await asyncio.open_connection("127.0.0.1", port)

                try:
                    # The connection is accepted at TCP level but closed by server
                    await asyncio.sleep(0.1)
                    # Reading should return EOF (connection closed by server)
                    data = await reader2.read(1)
                    assert data == b""  # EOF
                finally:
                    writer2.close()
                    await writer2.wait_closed()
            finally:
                writer1.close()
                await writer1.wait_closed()
        finally:
            await server.stop()

    @pytest.mark.asyncio
    async def test_stop_closes_connections(self) -> None:
        """Stopping server closes all connections."""
        config = TcpServerConfig(host="127.0.0.1", port=0)
        server = TcpServer(config=config)
        await server.start()
        port = server.local_address[1]  # type: ignore[index]

        _reader, writer = await asyncio.open_connection("127.0.0.1", port)

        try:
            channel = await asyncio.wait_for(server.accept(), timeout=2.0)
            assert channel.is_open is True

            await server.stop()

            assert channel.state == ChannelState.CLOSED
            assert server.connection_count == 0
        finally:
            writer.close()
            await writer.wait_closed()


class TestTcpServerChannel:
    """Tests for TcpServerChannel."""

    @pytest.mark.asyncio
    async def test_read_exactly(self) -> None:
        """Server channel can read exact bytes."""
        config = TcpServerConfig(host="127.0.0.1", port=0)
        server = TcpServer(config=config)
        await server.start()
        port = server.local_address[1]  # type: ignore[index]

        try:
            _reader, writer = await asyncio.open_connection("127.0.0.1", port)

            try:
                channel = await asyncio.wait_for(server.accept(), timeout=2.0)

                writer.write(b"12345")
                await writer.drain()

                data = await channel.read_exactly(5)
                assert data == b"12345"
            finally:
                writer.close()
                await writer.wait_closed()
        finally:
            await server.stop()

    @pytest.mark.asyncio
    async def test_write_all(self) -> None:
        """Server channel write_all sends all data."""
        config = TcpServerConfig(host="127.0.0.1", port=0)
        server = TcpServer(config=config)
        await server.start()
        port = server.local_address[1]  # type: ignore[index]

        try:
            reader, writer = await asyncio.open_connection("127.0.0.1", port)

            try:
                channel = await asyncio.wait_for(server.accept(), timeout=2.0)

                await channel.write_all(b"complete message")
                data = await reader.read(100)
                assert data == b"complete message"
            finally:
                writer.close()
                await writer.wait_closed()
        finally:
            await server.stop()

    @pytest.mark.asyncio
    async def test_read_on_closed_raises(self) -> None:
        """Reading from closed channel raises error."""
        config = TcpServerConfig(host="127.0.0.1", port=0)
        server = TcpServer(config=config)
        await server.start()
        port = server.local_address[1]  # type: ignore[index]

        try:
            _reader, writer = await asyncio.open_connection("127.0.0.1", port)

            try:
                channel = await asyncio.wait_for(server.accept(), timeout=2.0)
                await channel.close()

                with pytest.raises(ChannelClosedError):
                    await channel.read(100)
            finally:
                writer.close()
                await writer.wait_closed()
        finally:
            await server.stop()

    @pytest.mark.asyncio
    async def test_write_on_closed_raises(self) -> None:
        """Writing to closed channel raises error."""
        config = TcpServerConfig(host="127.0.0.1", port=0)
        server = TcpServer(config=config)
        await server.start()
        port = server.local_address[1]  # type: ignore[index]

        try:
            _reader, writer = await asyncio.open_connection("127.0.0.1", port)

            try:
                channel = await asyncio.wait_for(server.accept(), timeout=2.0)
                await channel.close()

                with pytest.raises(ChannelClosedError):
                    await channel.write(b"test")
            finally:
                writer.close()
                await writer.wait_closed()
        finally:
            await server.stop()

    @pytest.mark.asyncio
    async def test_statistics(self) -> None:
        """Channel tracks statistics correctly."""
        config = TcpServerConfig(host="127.0.0.1", port=0)
        server = TcpServer(config=config)
        await server.start()
        port = server.local_address[1]  # type: ignore[index]

        try:
            _reader, writer = await asyncio.open_connection("127.0.0.1", port)

            try:
                channel = await asyncio.wait_for(server.accept(), timeout=2.0)

                # Initial stats
                assert channel.statistics.connect_count == 1
                assert channel.statistics.bytes_sent == 0
                assert channel.statistics.bytes_received == 0

                # Send and receive
                await channel.write(b"hello")
                writer.write(b"world")
                await writer.drain()
                await channel.read(100)

                assert channel.statistics.bytes_sent == 5
                assert channel.statistics.bytes_received == 5

                await channel.close()
                assert channel.statistics.disconnect_count == 1
            finally:
                writer.close()
                await writer.wait_closed()
        finally:
            await server.stop()


class TestServeHelper:
    """Tests for serve() helper function."""

    @pytest.mark.asyncio
    async def test_serve_creates_started_server(self) -> None:
        """serve() creates and starts server."""
        server = await serve(host="127.0.0.1", port=0)

        try:
            assert server.is_listening is True
            assert server.local_address is not None
        finally:
            await server.stop()

    @pytest.mark.asyncio
    async def test_serve_with_config(self) -> None:
        """serve() accepts config."""
        config = TcpServerConfig(backlog=10)
        server = await serve(host="127.0.0.1", port=0, config=config)

        try:
            assert server.is_listening is True
            assert server.config.backlog == 10
        finally:
            await server.stop()

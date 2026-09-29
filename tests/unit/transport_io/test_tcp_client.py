"""Tests for TCP client channel."""

import asyncio

import pytest

from dnp3.transport_io.channel import (
    ChannelClosedError,
    ChannelConnectionError,
    ChannelState,
    ChannelTimeoutError,
    TcpConfig,
)
from dnp3.transport_io.tcp_client import TcpClientChannel, connect


class TestTcpClientChannel:
    """Tests for TcpClientChannel."""

    def test_initial_state_closed(self) -> None:
        """New channel starts in CLOSED state."""
        channel = TcpClientChannel()
        assert channel.state == ChannelState.CLOSED
        assert channel.is_open is False

    def test_default_config(self) -> None:
        """Default config has sensible values."""
        channel = TcpClientChannel()
        assert channel.config.host == "127.0.0.1"
        assert channel.config.port == 20000
        assert channel.config.nodelay is True
        assert channel.config.keepalive is True

    def test_custom_config(self) -> None:
        """Can use custom config."""
        config = TcpConfig(host="192.168.1.1", port=30000)
        channel = TcpClientChannel(config=config)
        assert channel.config.host == "192.168.1.1"
        assert channel.config.port == 30000

    def test_local_address_when_not_connected(self) -> None:
        """Local address is None when not connected."""
        channel = TcpClientChannel()
        assert channel.local_address is None

    def test_remote_address_when_not_connected(self) -> None:
        """Remote address is None when not connected."""
        channel = TcpClientChannel()
        assert channel.remote_address is None

    @pytest.mark.asyncio
    async def test_read_on_closed_raises(self) -> None:
        """Reading from closed channel raises error."""
        channel = TcpClientChannel()
        with pytest.raises(ChannelClosedError):
            await channel.read(100)

    @pytest.mark.asyncio
    async def test_write_on_closed_raises(self) -> None:
        """Writing to closed channel raises error."""
        channel = TcpClientChannel()
        with pytest.raises(ChannelClosedError):
            await channel.write(b"test")

    @pytest.mark.asyncio
    async def test_read_exactly_on_closed_raises(self) -> None:
        """read_exactly on closed channel raises error."""
        channel = TcpClientChannel()
        with pytest.raises(ChannelClosedError):
            await channel.read_exactly(10)

    @pytest.mark.asyncio
    async def test_close_when_already_closed(self) -> None:
        """Closing already closed channel is no-op."""
        channel = TcpClientChannel()
        await channel.close()  # Should not raise
        assert channel.state == ChannelState.CLOSED


class TestTcpClientWithServer:
    """Tests for TCP client with real network operations."""

    @pytest.mark.asyncio
    async def test_connect_to_server(self) -> None:
        """Client can connect to server."""

        # Start a simple echo server
        async def echo_handler(
            reader: asyncio.StreamReader,
            writer: asyncio.StreamWriter,
        ) -> None:
            try:
                while True:
                    data = await reader.read(1024)
                    if not data:
                        break
                    writer.write(data)
                    await writer.drain()
            finally:
                writer.close()
                await writer.wait_closed()

        server = await asyncio.start_server(
            echo_handler,
            host="127.0.0.1",
            port=0,  # Let OS choose port
        )
        addr = server.sockets[0].getsockname()
        port = addr[1]

        try:
            async with server:
                config = TcpConfig(host="127.0.0.1", port=port)
                channel = TcpClientChannel(config=config)
                await channel.open()

                assert channel.state == ChannelState.OPEN
                assert channel.is_open is True
                assert channel.local_address is not None
                assert channel.remote_address == ("127.0.0.1", port)
                assert channel.statistics.connect_count == 1

                await channel.close()
                assert channel.state == ChannelState.CLOSED
                assert channel.statistics.disconnect_count == 1
        finally:
            server.close()
            await server.wait_closed()

    @pytest.mark.asyncio
    async def test_write_and_read(self) -> None:
        """Client can write and read data."""

        async def echo_handler(
            reader: asyncio.StreamReader,
            writer: asyncio.StreamWriter,
        ) -> None:
            try:
                while True:
                    data = await reader.read(1024)
                    if not data:
                        break
                    writer.write(data)
                    await writer.drain()
            finally:
                writer.close()
                await writer.wait_closed()

        server = await asyncio.start_server(
            echo_handler,
            host="127.0.0.1",
            port=0,
        )
        addr = server.sockets[0].getsockname()
        port = addr[1]

        try:
            async with server:
                config = TcpConfig(host="127.0.0.1", port=port)
                channel = TcpClientChannel(config=config)
                await channel.open()

                await channel.write(b"hello")
                response = await channel.read(100)
                assert response == b"hello"

                assert channel.statistics.bytes_sent == 5
                assert channel.statistics.bytes_received == 5

                await channel.close()
        finally:
            server.close()
            await server.wait_closed()

    @pytest.mark.asyncio
    async def test_read_exactly(self) -> None:
        """Client can read exact number of bytes."""

        async def handler(
            reader: asyncio.StreamReader,
            writer: asyncio.StreamWriter,
        ) -> None:
            writer.write(b"12345")
            await writer.drain()
            writer.close()
            await writer.wait_closed()

        server = await asyncio.start_server(
            handler,
            host="127.0.0.1",
            port=0,
        )
        addr = server.sockets[0].getsockname()
        port = addr[1]

        try:
            async with server:
                config = TcpConfig(host="127.0.0.1", port=port)
                channel = TcpClientChannel(config=config)
                await channel.open()

                data = await channel.read_exactly(5)
                assert data == b"12345"

                await channel.close()
        finally:
            server.close()
            await server.wait_closed()

    @pytest.mark.asyncio
    async def test_write_all(self) -> None:
        """write_all sends all data."""
        received: list[bytes] = []

        async def handler(
            reader: asyncio.StreamReader,
            writer: asyncio.StreamWriter,
        ) -> None:
            data = await reader.read(1024)
            received.append(data)
            writer.close()
            await writer.wait_closed()

        server = await asyncio.start_server(
            handler,
            host="127.0.0.1",
            port=0,
        )
        addr = server.sockets[0].getsockname()
        port = addr[1]

        try:
            async with server:
                config = TcpConfig(host="127.0.0.1", port=port)
                channel = TcpClientChannel(config=config)
                await channel.open()

                await channel.write_all(b"complete message")
                await channel.close()

                # Wait for server to receive
                await asyncio.sleep(0.1)
                assert received[0] == b"complete message"
        finally:
            server.close()
            await server.wait_closed()

    @pytest.mark.asyncio
    async def test_read_exactly_eof(self) -> None:
        """read_exactly raises on EOF before requested bytes."""

        async def handler(
            reader: asyncio.StreamReader,
            writer: asyncio.StreamWriter,
        ) -> None:
            writer.write(b"hi")
            await writer.drain()
            writer.close()
            await writer.wait_closed()

        server = await asyncio.start_server(
            handler,
            host="127.0.0.1",
            port=0,
        )
        addr = server.sockets[0].getsockname()
        port = addr[1]

        try:
            async with server:
                config = TcpConfig(host="127.0.0.1", port=port)
                channel = TcpClientChannel(config=config)
                await channel.open()

                with pytest.raises(ChannelClosedError, match="EOF"):
                    await channel.read_exactly(10)

                await channel.close()
        finally:
            server.close()
            await server.wait_closed()

    @pytest.mark.asyncio
    async def test_context_manager(self) -> None:
        """Channel works as async context manager."""

        async def handler(
            reader: asyncio.StreamReader,
            writer: asyncio.StreamWriter,
        ) -> None:
            writer.close()
            await writer.wait_closed()

        server = await asyncio.start_server(
            handler,
            host="127.0.0.1",
            port=0,
        )
        addr = server.sockets[0].getsockname()
        port = addr[1]

        try:
            async with server:
                config = TcpConfig(host="127.0.0.1", port=port)
                async with TcpClientChannel(config=config) as channel:
                    assert channel.is_open is True

                assert channel.is_open is False
        finally:
            server.close()
            await server.wait_closed()

    @pytest.mark.asyncio
    async def test_connect_helper(self) -> None:
        """connect() helper creates connected channel."""

        async def handler(
            reader: asyncio.StreamReader,
            writer: asyncio.StreamWriter,
        ) -> None:
            writer.close()
            await writer.wait_closed()

        server = await asyncio.start_server(
            handler,
            host="127.0.0.1",
            port=0,
        )
        addr = server.sockets[0].getsockname()
        port = addr[1]

        try:
            async with server:
                channel = await connect("127.0.0.1", port)
                assert channel.is_open is True
                await channel.close()
        finally:
            server.close()
            await server.wait_closed()


class TestTcpClientErrors:
    """Tests for TCP client error handling."""

    @pytest.mark.asyncio
    async def test_connect_refused(self) -> None:
        """Connection refused raises appropriate error."""
        # Use a port that's likely not in use
        config = TcpConfig(host="127.0.0.1", port=59999)
        channel = TcpClientChannel(config=config)

        with pytest.raises(ChannelConnectionError):
            await channel.open()

        assert channel.state == ChannelState.CLOSED

    @pytest.mark.asyncio
    async def test_connect_timeout(self) -> None:
        """Connection timeout raises appropriate error."""
        # Use a non-routable IP to cause timeout
        config = TcpConfig(
            host="10.255.255.1",  # Non-routable
            port=20000,
            connect_timeout=0.1,
        )
        channel = TcpClientChannel(config=config)

        with pytest.raises(ChannelTimeoutError):
            await channel.open()

        assert channel.state == ChannelState.CLOSED

    @pytest.mark.asyncio
    async def test_read_eof(self) -> None:
        """Reading after server closes returns empty bytes."""

        async def handler(
            reader: asyncio.StreamReader,
            writer: asyncio.StreamWriter,
        ) -> None:
            writer.close()
            await writer.wait_closed()

        server = await asyncio.start_server(
            handler,
            host="127.0.0.1",
            port=0,
        )
        addr = server.sockets[0].getsockname()
        port = addr[1]

        try:
            async with server:
                config = TcpConfig(host="127.0.0.1", port=port)
                channel = TcpClientChannel(config=config)
                await channel.open()

                # Wait for server handler to close
                await asyncio.sleep(0.1)

                data = await channel.read(100)
                assert data == b""  # EOF

                await channel.close()
        finally:
            server.close()
            await server.wait_closed()

    @pytest.mark.asyncio
    async def test_read_timeout(self) -> None:
        """Read timeout raises appropriate error."""

        async def handler(
            reader: asyncio.StreamReader,
            writer: asyncio.StreamWriter,
        ) -> None:
            await asyncio.sleep(10)  # Never send anything
            writer.close()
            await writer.wait_closed()

        server = await asyncio.start_server(
            handler,
            host="127.0.0.1",
            port=0,
        )
        addr = server.sockets[0].getsockname()
        port = addr[1]

        try:
            async with server:
                config = TcpConfig(
                    host="127.0.0.1",
                    port=port,
                    read_timeout=0.1,
                )
                channel = TcpClientChannel(config=config)
                await channel.open()

                with pytest.raises(ChannelTimeoutError):
                    await channel.read(100)

                await channel.close()
        finally:
            server.close()
            await server.wait_closed()


class TestTcpClientStatistics:
    """Tests for TCP client statistics."""

    @pytest.mark.asyncio
    async def test_bytes_sent_tracking(self) -> None:
        """Bytes sent are tracked correctly."""

        async def handler(
            reader: asyncio.StreamReader,
            writer: asyncio.StreamWriter,
        ) -> None:
            await reader.read(1024)
            writer.close()
            await writer.wait_closed()

        server = await asyncio.start_server(
            handler,
            host="127.0.0.1",
            port=0,
        )
        addr = server.sockets[0].getsockname()
        port = addr[1]

        try:
            async with server:
                config = TcpConfig(host="127.0.0.1", port=port)
                channel = TcpClientChannel(config=config)
                await channel.open()

                await channel.write(b"12345")
                await channel.write(b"67890")
                assert channel.statistics.bytes_sent == 10
                assert channel.statistics.messages_sent == 2

                await channel.close()
        finally:
            server.close()
            await server.wait_closed()

    @pytest.mark.asyncio
    async def test_bytes_received_tracking(self) -> None:
        """Bytes received are tracked correctly."""

        async def handler(
            reader: asyncio.StreamReader,
            writer: asyncio.StreamWriter,
        ) -> None:
            writer.write(b"hello")
            await writer.drain()
            writer.write(b"world")
            await writer.drain()
            await asyncio.sleep(0.5)
            writer.close()
            await writer.wait_closed()

        server = await asyncio.start_server(
            handler,
            host="127.0.0.1",
            port=0,
        )
        addr = server.sockets[0].getsockname()
        port = addr[1]

        try:
            async with server:
                config = TcpConfig(host="127.0.0.1", port=port)
                channel = TcpClientChannel(config=config)
                await channel.open()

                await channel.read(100)
                await channel.read(100)
                # Note: messages_received counts read operations, not network packets
                # bytes_received should be 10 total
                assert channel.statistics.bytes_received == 10

                await channel.close()
        finally:
            server.close()
            await server.wait_closed()


class TestCloseIsBounded:
    """close() finishes even when the peer has stopped reading.

    A graceful close waits for the transport to flush its buffer, which never
    happens once the peer's receive window is full.
    """

    # More than loopback socket buffers hold, so bytes stay queued in the transport.
    STUFFING = b"\x00" * (32 * 1024 * 1024)

    @staticmethod
    async def _peer_that_never_reads() -> tuple[asyncio.Server, int, list[asyncio.StreamWriter]]:
        writers: list[asyncio.StreamWriter] = []

        async def handler(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
            writers.append(writer)

        server = await asyncio.start_server(handler, host="127.0.0.1", port=0)
        return server, server.sockets[0].getsockname()[1], writers

    @staticmethod
    async def _stop(server: asyncio.Server, writers: list[asyncio.StreamWriter]) -> None:
        for writer in writers:
            writer.transport.abort()
        server.close()
        await server.wait_closed()

    async def test_close_with_unsent_bytes_is_bounded(self) -> None:
        """Unsent bytes to a stalled peer are abandoned at the close bound."""
        server, port, writers = await self._peer_that_never_reads()
        try:
            channel = TcpClientChannel(config=TcpConfig(host="127.0.0.1", port=port))
            await channel.open()
            with pytest.raises(TimeoutError):
                await asyncio.wait_for(channel.write_all(self.STUFFING), timeout=0.3)

            sock = channel._writer.get_extra_info("socket")  # type: ignore[union-attr]

            loop = asyncio.get_running_loop()
            started = loop.time()
            await asyncio.wait_for(channel.close(), timeout=5.0)
            elapsed = loop.time() - started

            assert channel.config.close_timeout * 0.9 <= elapsed < channel.config.close_timeout + 1.0
            assert channel.state == ChannelState.CLOSED
            assert channel.statistics.disconnect_count == 1

            # abort() closes the transport asynchronously (scheduled via
            # call_soon); poll rather than assume it has run by the time
            # close() returns.
            deadline = loop.time() + 1.0
            while sock.fileno() != -1 and loop.time() < deadline:
                await asyncio.sleep(0.01)
            assert sock.fileno() == -1, "a stalled close must abort the transport, not merely time out"
        finally:
            await self._stop(server, writers)

    async def test_close_cancelled_mid_wait_still_aborts_transport(self) -> None:
        """Cancelling close() during the bounded wait still aborts the socket
        and still reaches CLOSED with the writer, reader and counter cleaned up.
        """
        server, port, writers = await self._peer_that_never_reads()
        try:
            channel = TcpClientChannel(config=TcpConfig(host="127.0.0.1", port=port, close_timeout=5.0))
            await channel.open()
            with pytest.raises(TimeoutError):
                await asyncio.wait_for(channel.write_all(self.STUFFING), timeout=0.3)

            sock = channel._writer.get_extra_info("socket")  # type: ignore[union-attr]

            close_task = asyncio.create_task(channel.close())
            await asyncio.sleep(0.05)  # let close() start its bounded wait
            close_task.cancel()

            with pytest.raises(asyncio.CancelledError):
                await close_task

            assert channel.state == ChannelState.CLOSED
            assert channel._writer is None
            assert channel._reader is None
            assert channel.statistics.disconnect_count == 1

            loop = asyncio.get_running_loop()
            deadline = loop.time() + 1.0
            while sock.fileno() != -1 and loop.time() < deadline:
                await asyncio.sleep(0.01)
            assert sock.fileno() == -1, "a cancelled close must still abort the transport"
        finally:
            await self._stop(server, writers)

    async def test_close_after_cancelled_close_is_a_noop(self) -> None:
        """A second close() after a cancelled close() raises nothing and stays CLOSED."""
        server, port, writers = await self._peer_that_never_reads()
        try:
            channel = TcpClientChannel(config=TcpConfig(host="127.0.0.1", port=port, close_timeout=5.0))
            await channel.open()
            with pytest.raises(TimeoutError):
                await asyncio.wait_for(channel.write_all(self.STUFFING), timeout=0.3)

            close_task = asyncio.create_task(channel.close())
            await asyncio.sleep(0.05)
            close_task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await close_task

            assert channel.state == ChannelState.CLOSED

            # The second close() must be the no-op guard's job: it must not
            # raise, and must not touch an already-cleared writer/reader.
            await channel.close()

            assert channel.state == ChannelState.CLOSED
            assert channel.statistics.disconnect_count == 1
        finally:
            await self._stop(server, writers)

    async def test_close_to_a_reading_peer_still_delivers_every_byte(self) -> None:
        """The bound does not truncate a healthy close: the peer gets all bytes, then EOF."""
        received = bytearray()
        done = asyncio.Event()

        async def handler(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
            while chunk := await reader.read(65536):
                received.extend(chunk)
            done.set()
            writer.close()

        server = await asyncio.start_server(handler, host="127.0.0.1", port=0)
        port = server.sockets[0].getsockname()[1]
        payload = bytes(range(256)) * 4096
        try:
            channel = TcpClientChannel(config=TcpConfig(host="127.0.0.1", port=port))
            await channel.open()
            channel._writer.write(payload)  # type: ignore[union-attr]
            await channel.close()
            await asyncio.wait_for(done.wait(), timeout=5.0)

            assert bytes(received) == payload
            assert channel.state == ChannelState.CLOSED
        finally:
            server.close()
            await server.wait_closed()

    async def test_concurrent_close_counts_once_and_waits_for_closed(self) -> None:
        """A second close() started while the first is still CLOSING waits until CLOSED and counts one disconnect."""
        server, port, writers = await self._peer_that_never_reads()
        try:
            channel = TcpClientChannel(config=TcpConfig(host="127.0.0.1", port=port, close_timeout=0.3))
            await channel.open()

            async def stuff_until_stalled() -> None:
                while True:
                    await channel.write_all(self.STUFFING)

            with pytest.raises(TimeoutError):
                await asyncio.wait_for(stuff_until_stalled(), timeout=0.3)

            observed_states_on_return: list[ChannelState] = []

            async def call_close() -> None:
                await channel.close()
                observed_states_on_return.append(channel.state)

            first = asyncio.create_task(call_close())
            await asyncio.sleep(0.05)
            assert channel.state == ChannelState.CLOSING

            second = asyncio.create_task(call_close())
            await asyncio.sleep(0.05)
            assert not second.done(), "second close() must wait for the channel to finish closing"

            await asyncio.wait_for(asyncio.gather(first, second), timeout=5.0)

            assert observed_states_on_return == [ChannelState.CLOSED, ChannelState.CLOSED]
            assert channel.state == ChannelState.CLOSED
            assert channel.statistics.disconnect_count == 1
        finally:
            await self._stop(server, writers)

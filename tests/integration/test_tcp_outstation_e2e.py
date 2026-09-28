"""Integration tests for OutstationTcpRunner over real TCP.

Tests the full stack end-to-end: TCP connection, data link framing,
transport reassembly, application processing, and response.
"""

import asyncio
import contextlib
from collections.abc import Awaitable, Callable

import pytest

from dnp3.application.builder import build_integrity_poll
from dnp3.application.parser import parse_response
from dnp3.core.enums import FunctionCode, LinkFunctionCode
from dnp3.core.flags import BinaryQuality
from dnp3.database import AnalogInputConfig, BinaryInputConfig, Database, EventClass
from dnp3.datalink.builder import build_reset_link_state, build_unconfirmed_user_data
from dnp3.datalink.parser import FrameParser
from dnp3.outstation import Outstation, OutstationConfig, OutstationTcpRunner
from dnp3.transport.segment import TransportSegment

MASTER_ADDR = 3
OUTSTATION_ADDR = 1


def _build_request_frame(
    master_addr: int,
    outstation_addr: int,
    request_bytes: bytes,
) -> bytes:
    """Build a complete data link frame containing a DNP3 request."""
    segment = TransportSegment.build(fir=True, fin=True, seq=0, payload=request_bytes)
    frame = build_unconfirmed_user_data(
        destination=outstation_addr,
        source=master_addr,
        dir_from_master=True,
        user_data=segment.to_bytes(),
    )
    return frame.to_bytes()


class TestTcpOutstationE2E:
    """End-to-end tests with real TCP connections."""

    @pytest.mark.asyncio
    async def test_connect_reset_integrity_poll(self) -> None:
        """Start runner on port 0, connect client, send reset + integrity poll, verify response."""
        database = Database()
        database.add_binary_input(0, BinaryInputConfig(event_class=EventClass.CLASS_1))
        database.update_binary_input(0, value=True, quality=BinaryQuality.ONLINE)

        config = OutstationConfig(address=OUTSTATION_ADDR, master_address=MASTER_ADDR)
        outstation = Outstation(config=config, database=database)
        runner = OutstationTcpRunner(outstation=outstation, host="127.0.0.1", port=0)

        # Start runner
        run_task = asyncio.create_task(runner.run())
        await asyncio.sleep(0.2)  # let it bind

        assert runner.is_running
        addr = runner.local_address
        assert addr is not None
        host, port = addr

        try:
            # Connect as client
            reader, writer = await asyncio.open_connection(host, port)

            # Send reset link state
            reset = build_reset_link_state(
                destination=OUTSTATION_ADDR,
                source=MASTER_ADDR,
                dir_from_master=True,
            )
            writer.write(reset.to_bytes())
            await writer.drain()

            # Read ACK
            parser = FrameParser()
            ack_data = await asyncio.wait_for(reader.read(4096), timeout=2.0)
            ack_frames = list(parser.feed(ack_data))
            assert len(ack_frames) >= 1
            assert ack_frames[0].header.control.function_code == LinkFunctionCode.SEC_ACK

            # Send integrity poll
            request = build_integrity_poll(seq=0)
            frame_bytes = _build_request_frame(MASTER_ADDR, OUTSTATION_ADDR, request.to_bytes())
            writer.write(frame_bytes)
            await writer.drain()

            # Read response
            resp_data = await asyncio.wait_for(reader.read(4096), timeout=2.0)
            resp_frames = list(parser.feed(resp_data))
            assert len(resp_frames) >= 1

            resp_frame = resp_frames[0]
            assert resp_frame.user_data
            segment = TransportSegment.from_bytes(resp_frame.user_data)
            response = parse_response(segment.payload)
            assert response.header.function == FunctionCode.RESPONSE

            writer.close()
            await writer.wait_closed()
        finally:
            await runner.stop()
            run_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await run_task

    @pytest.mark.asyncio
    async def test_outstation_with_multiple_point_types(self) -> None:
        """Outstation with binary + analog inputs, integrity poll returns data."""
        database = Database()
        database.add_binary_input(0, BinaryInputConfig(event_class=EventClass.CLASS_1))
        database.add_binary_input(1, BinaryInputConfig(event_class=EventClass.CLASS_1))
        database.update_binary_input(0, value=True, quality=BinaryQuality.ONLINE)
        database.update_binary_input(1, value=False, quality=BinaryQuality.ONLINE)
        database.add_analog_input(0, AnalogInputConfig(event_class=EventClass.CLASS_2))
        database.update_analog_input(0, value=42.5)

        config = OutstationConfig(address=OUTSTATION_ADDR, master_address=MASTER_ADDR)
        outstation = Outstation(config=config, database=database)
        runner = OutstationTcpRunner(outstation=outstation, host="127.0.0.1", port=0)

        run_task = asyncio.create_task(runner.run())
        await asyncio.sleep(0.2)

        addr = runner.local_address
        assert addr is not None
        host, port = addr

        try:
            reader, writer = await asyncio.open_connection(host, port)

            # Send integrity poll directly (no reset needed for unconfirmed)
            request = build_integrity_poll(seq=0)
            frame_bytes = _build_request_frame(MASTER_ADDR, OUTSTATION_ADDR, request.to_bytes())
            writer.write(frame_bytes)
            await writer.drain()

            # Read response
            parser = FrameParser()
            resp_data = await asyncio.wait_for(reader.read(4096), timeout=2.0)
            resp_frames = list(parser.feed(resp_data))
            assert len(resp_frames) >= 1

            resp_frame = resp_frames[0]
            assert resp_frame.user_data
            segment = TransportSegment.from_bytes(resp_frame.user_data)
            response = parse_response(segment.payload)
            assert response.header.function == FunctionCode.RESPONSE
            # Should have object blocks for the points
            assert len(response.objects) > 0

            writer.close()
            await writer.wait_closed()
        finally:
            await runner.stop()
            run_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await run_task


class _SlowCancelHandler:
    """Connection handler that takes noticeable time to unwind on cancel.

    Widens run()'s handoff/shutdown race window enough to hit
    deterministically: the event fires the instant the handler's own
    cancellation begins, which is also the instant run() is parked awaiting
    this task (issue #68).
    """

    def __init__(self, unwind_delay: float = 0.3) -> None:
        self.cancelled_event = asyncio.Event()
        self._unwind_delay = unwind_delay

    async def __call__(self, channel: object) -> None:
        try:
            await asyncio.sleep(3600)
        except asyncio.CancelledError:
            self.cancelled_event.set()
            await asyncio.shield(asyncio.sleep(self._unwind_delay))
            raise


class _RaisingOnCancelOnceHandler:
    """Connection handler whose cancellation cleanup raises a real error on
    the first connection, then delegates to the real handler afterward, so
    a test can prove run() keeps serving the connection that replaced it."""

    def __init__(self, real_handler: Callable[[object], Awaitable[None]]) -> None:
        self._real_handler = real_handler
        self._first = True

    async def __call__(self, channel: object) -> None:
        if self._first:
            self._first = False
            try:
                await asyncio.sleep(3600)
            except asyncio.CancelledError as exc:
                raise RuntimeError("boom: handler failed while being replaced") from exc
        else:
            await self._real_handler(channel)


class TestOutstationTcpRunnerCancellation:
    """run() must propagate a cancellation aimed at it rather than absorb it
    alongside the pre-empted connection task's own cancellation, and must not
    silently drop a real exception from that task (issue #68)."""

    @pytest.mark.asyncio
    async def test_cancel_during_reconnect_handoff_propagates(self) -> None:
        """Cancelling run() while it awaits the pre-empted connection task
        during the reconnect handoff must propagate out of run()."""
        outstation = Outstation(config=OutstationConfig(address=OUTSTATION_ADDR, master_address=MASTER_ADDR))
        runner = OutstationTcpRunner(outstation=outstation, host="127.0.0.1", port=0)
        handler = _SlowCancelHandler()
        runner._handle_connection = handler  # type: ignore[method-assign]

        run_task = asyncio.create_task(runner.run())
        await asyncio.sleep(0.2)
        addr = runner.local_address
        assert addr is not None
        host, port = addr

        _, w1 = await asyncio.open_connection(host, port)
        await asyncio.sleep(0.2)  # w1's connection task is established and running

        _, w2 = await asyncio.open_connection(host, port)
        # w2 triggers the handoff: run() cancels w1's connection task and
        # awaits it. The event fires exactly when run() is parked there.
        await asyncio.wait_for(handler.cancelled_event.wait(), timeout=2.0)
        run_task.cancel()

        try:
            try:
                await asyncio.wait_for(asyncio.shield(run_task), timeout=2.0)
                pytest.fail("run() returned without propagating the cancellation")
            except TimeoutError:
                pytest.fail("run() did not finish after cancel() during the reconnect handoff")
        except asyncio.CancelledError:
            pass
        finally:
            w1.close()
            w2.close()
            if not run_task.done():
                run_task.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await run_task

    @pytest.mark.asyncio
    async def test_cancel_during_shutdown_finally_propagates(self) -> None:
        """Cancelling run() while the finally clause tears down the still-
        running connection task during an ordinary shutdown must propagate,
        not be silently absorbed alongside the child task's own
        cancellation."""
        outstation = Outstation(config=OutstationConfig(address=OUTSTATION_ADDR, master_address=MASTER_ADDR))
        runner = OutstationTcpRunner(outstation=outstation, host="127.0.0.1", port=0)
        handler = _SlowCancelHandler()
        runner._handle_connection = handler  # type: ignore[method-assign]

        run_task = asyncio.create_task(runner.run())
        await asyncio.sleep(0.2)
        addr = runner.local_address
        assert addr is not None
        host, port = addr

        _, w1 = await asyncio.open_connection(host, port)
        await asyncio.sleep(0.2)  # connection task is established and running

        stop_task = asyncio.create_task(runner.stop())
        # stop() sets the shutdown flag; run()'s accept() loop notices within
        # its 1s poll and unwinds into the finally clause, which cancels the
        # still-running connection task and awaits it. The event fires
        # exactly when run() is parked on that await.
        await asyncio.wait_for(handler.cancelled_event.wait(), timeout=2.0)
        run_task.cancel()

        try:
            try:
                await asyncio.wait_for(asyncio.shield(run_task), timeout=2.0)
                pytest.fail("run() returned without propagating the cancellation")
            except TimeoutError:
                pytest.fail("run() did not finish after cancel() during shutdown's finally clause")
        except asyncio.CancelledError:
            pass
        finally:
            w1.close()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await stop_task
            if not run_task.done():
                run_task.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await run_task

    @pytest.mark.asyncio
    async def test_child_task_error_during_handoff_is_logged(self, caplog: pytest.LogCaptureFixture) -> None:
        """A real exception from the pre-empted connection task must be
        logged, and run() must keep serving the connection that replaced it."""
        outstation = Outstation(config=OutstationConfig(address=OUTSTATION_ADDR, master_address=MASTER_ADDR))
        runner = OutstationTcpRunner(outstation=outstation, host="127.0.0.1", port=0)
        real_handler = runner._handle_connection
        runner._handle_connection = _RaisingOnCancelOnceHandler(real_handler)  # type: ignore[method-assign]

        run_task = asyncio.create_task(runner.run())
        await asyncio.sleep(0.2)
        addr = runner.local_address
        assert addr is not None
        host, port = addr

        _, w1 = await asyncio.open_connection(host, port)
        await asyncio.sleep(0.2)  # w1's connection task is established and running

        try:
            with caplog.at_level("ERROR", logger="dnp3.outstation.tcp_runner"):
                reader2, w2 = await asyncio.open_connection(host, port)
                # w2 triggers the handoff: run() cancels w1's connection task,
                # which raises RuntimeError instead of propagating
                # CancelledError, then continues to serve w2.
                reset = build_reset_link_state(
                    destination=OUTSTATION_ADDR,
                    source=MASTER_ADDR,
                    dir_from_master=True,
                )
                w2.write(reset.to_bytes())
                await w2.drain()

                parser = FrameParser()
                ack_data = await asyncio.wait_for(reader2.read(4096), timeout=2.0)
                ack_frames = list(parser.feed(ack_data))
                assert len(ack_frames) >= 1, "run() should still serve the connection that replaced the failed one"
                assert ack_frames[0].header.control.function_code == LinkFunctionCode.SEC_ACK

            error_records = [
                r
                for r in caplog.records
                if r.exc_info is not None and isinstance(r.exc_info[1], RuntimeError) and "boom" in str(r.exc_info[1])
            ]
            assert error_records, "the pre-empted connection task's real error must be logged"
        finally:
            w1.close()
            w2.close()
            await runner.stop()
            run_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await run_task

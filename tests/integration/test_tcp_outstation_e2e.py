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


class _ImmediateFailureHandler:
    """Connection handler that turns its own cancellation into an ordinary
    exception with no further await: the shape needed to race an outer
    cancellation of run() against the child's own completion (issue #68)."""

    async def __call__(self, channel: object) -> None:
        try:
            await asyncio.sleep(3600)
        except asyncio.CancelledError as exc:
            raise RuntimeError("boom: ordinary failure, no further await") from exc


class _PlainCancelHandler:
    """Connection handler that responds to cancellation exactly like an
    ordinary reconnect with no outer cancellation involved: it simply lets
    CancelledError propagate."""

    async def __call__(self, channel: object) -> None:
        await asyncio.sleep(3600)


def _force_outer_cancel_race(
    connection_task: asyncio.Task[None],
    run_task: asyncio.Task[None],
) -> None:
    """Make run_task.cancel() land after run() has already suspended
    awaiting `connection_task`, but before that task's own cancellation is
    delivered, deterministically.

    Natural timing cannot reach this window from outside: winning it by
    accident would require an external cancel() to be queued, via plain
    event-loop scheduling, between run()'s own `connection_task.cancel()`
    call and that same task's next wakeup, which real TCP/accept() timing
    does not offer a hook into. Forced instead by wrapping
    `connection_task.cancel` so that its first invocation (run()'s own
    handoff/shutdown call) defers to the next loop iteration and, in that
    same iteration, calls `run_task.cancel()` before the real cancel(),
    which is what lets Task.cancelling() register on run_task without
    forcing `Task._must_cancel`. Any later call to `connection_task.cancel()`
    (run_task's own delegation once it is cancelled) is passed straight
    through, so the forcing does not recurse.
    """
    loop = asyncio.get_running_loop()
    real_cancel = connection_task.cancel
    state = {"forced": False}

    def wrapped_cancel(*args: object, **kwargs: object) -> bool:
        if state["forced"]:
            return real_cancel(*args, **kwargs)
        state["forced"] = True
        loop.call_soon(run_task.cancel)
        return True

    connection_task.cancel = wrapped_cancel  # type: ignore[method-assign]


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

        assert run_task.done() and run_task.cancelled(), "run_task must end cancelled, not merely raise"
        with pytest.raises((ConnectionRefusedError, OSError)) as exc_info:
            await asyncio.wait_for(asyncio.open_connection(host, port), timeout=2.0)
        assert not isinstance(exc_info.value, TimeoutError), "connect must be refused promptly, not merely time out"

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

        # Set the shutdown flag directly, WITHOUT calling runner.stop(): that
        # method also calls self._server.stop() itself, which would close the
        # listener independently of run()'s own finally clause and mask the
        # bug this test exists to catch. Setting the flag alone still makes
        # run()'s accept() loop notice within its 1s poll and unwind into the
        # finally clause normally, exactly as an ordinary shutdown would.
        runner._shutdown.set()
        # The event fires exactly when run() is parked on the finally
        # clause's own await of the still-running connection task.
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
            if not run_task.done():
                run_task.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await run_task

        assert run_task.done() and run_task.cancelled(), "run_task must end cancelled, not merely raise"
        # The listener must be closed too: a re-raise from inside the
        # finally clause must not skip await self._server.stop() (#68). Only
        # run()'s own teardown can have closed it here, since nothing else
        # called stop().
        try:
            with pytest.raises((ConnectionRefusedError, OSError)) as exc_info:
                await asyncio.wait_for(asyncio.open_connection(host, port), timeout=2.0)
            assert not isinstance(exc_info.value, TimeoutError), "connect must be refused promptly, not merely time out"
        finally:
            await runner.stop()  # hygiene: close the listener for real if the bug left it open

    @pytest.mark.asyncio
    async def test_exception_race_during_handoff_propagates_cancellation(self) -> None:
        """A cancellation of run() that wins the race against the
        pre-empted connection task's own ordinary (non-CancelledError)
        failure at the reconnect handoff must still propagate, not be
        absorbed by the unguarded except-Exception branch."""
        outstation = Outstation(config=OutstationConfig(address=OUTSTATION_ADDR, master_address=MASTER_ADDR))
        runner = OutstationTcpRunner(outstation=outstation, host="127.0.0.1", port=0)
        runner._handle_connection = _ImmediateFailureHandler()  # type: ignore[method-assign]

        run_task = asyncio.create_task(runner.run())
        await asyncio.sleep(0.2)
        addr = runner.local_address
        assert addr is not None
        host, port = addr

        _, w1 = await asyncio.open_connection(host, port)
        await asyncio.sleep(0.2)  # w1's connection task is established and running

        task1 = runner._connection_task
        assert task1 is not None
        _force_outer_cancel_race(task1, run_task)

        _, w2 = await asyncio.open_connection(host, port)
        # w2 triggers the handoff; the forced race makes run_task's
        # cancellation win delegation over task1's own, so task1 completes
        # with RuntimeError while run_task.cancelling() is already > 0.

        try:
            try:
                await asyncio.wait_for(asyncio.shield(run_task), timeout=2.0)
                pytest.fail("run() returned without propagating the cancellation")
            except TimeoutError:
                pytest.fail("run() did not finish after the racing child exception during handoff")
        except asyncio.CancelledError:
            pass
        finally:
            w1.close()
            w2.close()
            if not run_task.done():
                run_task.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await run_task

        assert run_task.done() and run_task.cancelled(), "run_task must end cancelled, not merely raise"

    @pytest.mark.asyncio
    async def test_exception_race_during_shutdown_propagates_cancellation(self) -> None:
        """The same race as the handoff site, forced at the shutdown/finally
        teardown site instead: run()'s own cancellation must still surface
        even though the connection task it is tearing down completes with
        an ordinary exception rather than CancelledError."""
        outstation = Outstation(config=OutstationConfig(address=OUTSTATION_ADDR, master_address=MASTER_ADDR))
        runner = OutstationTcpRunner(outstation=outstation, host="127.0.0.1", port=0)
        runner._handle_connection = _ImmediateFailureHandler()  # type: ignore[method-assign]

        run_task = asyncio.create_task(runner.run())
        await asyncio.sleep(0.2)
        addr = runner.local_address
        assert addr is not None
        host, port = addr

        _, w1 = await asyncio.open_connection(host, port)
        await asyncio.sleep(0.2)  # connection task is established and running

        task1 = runner._connection_task
        assert task1 is not None
        _force_outer_cancel_race(task1, run_task)

        stop_task = asyncio.create_task(runner.stop())
        # stop() unwinds run() into the finally clause normally (no
        # cancellation yet); the finally clause cancels task1 itself, and
        # the forced race makes run_task's own cancellation win delegation
        # over that call, so task1 completes with RuntimeError while
        # run_task.cancelling() is already > 0.

        try:
            try:
                await asyncio.wait_for(asyncio.shield(run_task), timeout=2.0)
                pytest.fail("run() returned without propagating the cancellation")
            except TimeoutError:
                pytest.fail("run() did not finish after the racing child exception during shutdown")
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

        assert run_task.done() and run_task.cancelled(), "run_task must end cancelled, not merely raise"

    @pytest.mark.asyncio
    async def test_reconnect_without_outer_cancellation_keeps_serving(self) -> None:
        """When only the pre-empted connection task is cancelled (an
        ordinary reconnect, with no cancellation aimed at run() itself),
        run() must keep running afterward and stop cleanly on request.
        Pins `_outer_cancellation_pending()` against an always-True
        mutant, which would make this ordinary reconnect look like a
        pending outer cancellation and end run() early."""
        outstation = Outstation(config=OutstationConfig(address=OUTSTATION_ADDR, master_address=MASTER_ADDR))
        runner = OutstationTcpRunner(outstation=outstation, host="127.0.0.1", port=0)
        runner._handle_connection = _PlainCancelHandler()  # type: ignore[method-assign]

        run_task = asyncio.create_task(runner.run())
        await asyncio.sleep(0.2)
        addr = runner.local_address
        assert addr is not None
        host, port = addr

        _, w1 = await asyncio.open_connection(host, port)
        await asyncio.sleep(0.2)

        _, w2 = await asyncio.open_connection(host, port)
        await asyncio.sleep(0.2)  # let the ordinary reconnect handoff complete

        try:
            assert not run_task.done(), "an ordinary reconnect must not end run()"
        finally:
            w1.close()
            w2.close()
            await runner.stop()
            await asyncio.wait_for(run_task, timeout=2.0)

        assert run_task.done() and not run_task.cancelled(), "run() must stop cleanly, not via cancellation"

    @pytest.mark.asyncio
    async def test_child_task_error_during_shutdown_is_logged(self, caplog: pytest.LogCaptureFixture) -> None:
        """A real exception from the connection task torn down in the
        shutdown/finally clause must be logged, matching the handoff site."""
        outstation = Outstation(config=OutstationConfig(address=OUTSTATION_ADDR, master_address=MASTER_ADDR))
        runner = OutstationTcpRunner(outstation=outstation, host="127.0.0.1", port=0)
        runner._handle_connection = _ImmediateFailureHandler()  # type: ignore[method-assign]

        run_task = asyncio.create_task(runner.run())
        await asyncio.sleep(0.2)
        addr = runner.local_address
        assert addr is not None
        host, port = addr

        _, w1 = await asyncio.open_connection(host, port)
        await asyncio.sleep(0.2)  # connection task is established and running

        try:
            with caplog.at_level("ERROR", logger="dnp3.outstation.tcp_runner"):
                await runner.stop()
                # An ordinary shutdown: the connection task is cancelled in
                # the finally clause and raises RuntimeError immediately,
                # no outer cancellation involved.
                await asyncio.wait_for(run_task, timeout=2.0)

            error_records = [
                r
                for r in caplog.records
                if r.getMessage() == "Connection task failed during shutdown"
                and r.exc_info is not None
                and isinstance(r.exc_info[1], RuntimeError)
                and "boom" in str(r.exc_info[1])
            ]
            assert error_records, "the connection task's real error during shutdown must be logged"
        finally:
            w1.close()
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
                if r.getMessage() == "Connection task failed during handoff"
                and r.exc_info is not None
                and isinstance(r.exc_info[1], RuntimeError)
                and "boom" in str(r.exc_info[1])
            ]
            assert error_records, "the pre-empted connection task's real error must be logged"
        finally:
            w1.close()
            w2.close()
            await runner.stop()
            run_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await run_task

"""TCP transport runner for DNP3 masters.

`Master` builds requests and parses responses but owns no I/O; `TcpClientChannel`
moves bytes but knows no DNP3. `MasterTcpRunner` is the layer between them:
data link framing, transport segmentation and reassembly, link reset, and the
multi-fragment application CONFIRM handshake.

    runner = MasterTcpRunner(master=Master(handler=handler), host="10.0.0.5")
    await runner.open()
    try:
        await runner.integrity_poll()
    finally:
        await runner.close()

Scheduling deliberately lives *above* this class. `PollScheduler` models when a
poll is due and is transport-independent; driving it from inside a TCP runner
would make a serial or UDP implementation reimplement the loop. `run_polls()` is
offered as a convenience that composes the two, and is the only method that
knows about time.

This is not a mirror of `OutstationTcpRunner`. The two share a shape at the link
and transport layers, but the seam between them is better extracted once there
are two real implementations to compare than guessed from one.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections import deque
from dataclasses import dataclass, field
from enum import Enum, auto

from dnp3.application.fragment import RequestFragment
from dnp3.application.header import MAX_APP_SEQUENCE
from dnp3.application.parser import ParseError, parse_response_header
from dnp3.core.enums import LinkFunctionCode
from dnp3.datalink.builder import build_reset_link_state, build_unconfirmed_user_data
from dnp3.datalink.frame import DataLinkFrame
from dnp3.datalink.parser import FrameParser
from dnp3.master.handler import ResponseInfo
from dnp3.master.master import Master
from dnp3.master.polling import PollTask
from dnp3.transport.reassembler import Reassembler, ReassemblyError
from dnp3.transport.segment import TransportSegment
from dnp3.transport.segmenter import Segmenter
from dnp3.transport_io.channel import Channel, ChannelError, TcpConfig
from dnp3.transport_io.tcp_client import TcpClientChannel

logger = logging.getLogger(__name__)

READ_CHUNK_SIZE = 4096
"""Bytes requested per channel read. Frames are reassembled across reads."""

MAX_BURST_FRAGMENTS = 512
"""Fragments accepted in one response burst before the exchange is abandoned.

The mod-16 sequence walk wraps, so sequence continuity alone cannot bound a
burst: a peer that keeps incrementing forever stays "in sequence" forever. A
real burst is bounded by the outstation's own database size; this cap is set far
above any legitimate response so it only fires on a peer that will not stop.
"""

_USER_DATA_FUNCTION_CODES = frozenset(
    {
        LinkFunctionCode.PRI_UNCONFIRMED_USER_DATA,
        LinkFunctionCode.PRI_CONFIRMED_USER_DATA,
    }
)
"""Link function codes that carry a transport segment.

An outstation sends responses as primary frames reusing these codes
(`build_primary_frame` sets PRM=1), so a master matches the same values a
master sends.
"""


class LinkResetPolicy(Enum):
    """When to send RESET_LINK_STATE.

    Attributes:
        ON_OPEN: Send a link reset when the channel opens. The default, and what
            IEEE 1815-2012 expects of a master establishing a new association.
        NEVER: Skip the reset. For peers that treat an unsolicited reset as an
            error, or when the link is known to be already reset.
    """

    ON_OPEN = auto()
    NEVER = auto()


class MasterRunnerError(Exception):
    """Raised when the runner cannot complete an exchange."""


class ResponseTimeoutError(MasterRunnerError):
    """Raised when no response fragment arrives before the deadline."""


class LinkError(MasterRunnerError):
    """Raised when the link fails or delivers unusable bytes.

    Wraps the channel and transport layers' own exceptions (`ChannelError`,
    `ReassemblyError`) so a caller can catch everything this runner raises
    under `MasterRunnerError` without importing from those packages.
    """


@dataclass
class _Burst:
    """One solicited response burst, accumulated across fragments.

    Attributes:
        expected_seq: Sequence the next fragment must carry. Seeded with the
            request's own sequence, so the *first* fragment is correlated to the
            request rather than accepted at whatever sequence arrives.
        fragments: Info for each fragment, in arrival order.
    """

    expected_seq: int
    fragments: list[ResponseInfo] = field(default_factory=list)


@dataclass
class MasterTcpRunner:
    """Runs a DNP3 master over TCP, handling the full protocol stack.

    Attributes:
        master: The application-layer master. Supplies request building,
            response parsing, and the SOE handler values are reported to.
        host: Outstation host to connect to.
        port: Outstation TCP port.
        response_timeout: Seconds to wait for a response fragment.
        link_reset: Whether to reset the data link on open.
        channel: Channel to use instead of opening a TCP client. Supplied by
            tests to exercise the stack without a socket.
    """

    master: Master
    host: str = "127.0.0.1"
    port: int = 20000
    response_timeout: float = 10.0
    link_reset: LinkResetPolicy = LinkResetPolicy.ON_OPEN
    channel: Channel | None = None

    _parser: FrameParser = field(default_factory=FrameParser, init=False, repr=False)
    _segmenter: Segmenter = field(default_factory=Segmenter, init=False, repr=False)
    _reassembler: Reassembler | None = field(default=None, init=False, repr=False)
    _owns_channel: bool = field(default=False, init=False, repr=False)
    _pending: deque[DataLinkFrame] = field(default_factory=deque, init=False, repr=False)

    @property
    def is_open(self) -> bool:
        """Whether the underlying channel is open."""
        return self.channel is not None and self.channel.is_open

    @property
    def local_address(self) -> tuple[str, int] | None:
        """Local address of the channel, if it exposes one."""
        return getattr(self.channel, "local_address", None)

    # -- lifecycle ------------------------------------------------------------

    async def open(self) -> None:
        """Open the channel and, by policy, reset the data link.

        Raises:
            MasterRunnerError: The runner is already open. Re-opening would
                replace the reassembler and re-send RESET_LINK_STATE underneath
                any in-flight request.
        """
        # `_reassembler`, not `is_open`: an injected channel is often already
        # open before the runner touches it, and opening the runner over it is
        # the normal test and embedding pattern. Only `open()` sets a
        # reassembler, so it is what distinguishes "runner opened" from
        # "channel happens to be open".
        if self._reassembler is not None:
            msg = "Runner is already open; close() before opening again"
            raise MasterRunnerError(msg)

        if self.channel is None:
            self.channel = TcpClientChannel(config=TcpConfig(host=self.host, port=self.port))
            self._owns_channel = True

        if not self.channel.is_open:
            await self.channel.open()

        # Bound reassembly by the master's own fragment cap so a peer that never
        # sets FIN cannot exhaust memory.
        self._reassembler = Reassembler(max_fragment_size=self.master.config.max_fragment_size)
        # A previous connection may have left a partial frame mid-parse and
        # frames unconsumed; neither belongs in this connection's stream.
        self._parser.reset()
        self._pending.clear()
        logger.info("Master connected to %s:%d", self.host, self.port)

        if self.link_reset is LinkResetPolicy.ON_OPEN:
            await self._send_link_reset()

    async def close(self) -> None:
        """Close the channel if this runner opened it, and clear protocol state.

        An injected channel is left open for its owner to close, but the
        runner's own state is dropped either way: a reused runner must not
        reassemble the next connection's bytes onto the last one's remnants.
        """
        if self.channel is not None and self._owns_channel:
            await self.channel.close()
            self.channel = None
            self._owns_channel = False

        self._reassembler = None
        self._parser.reset()
        self._pending.clear()

    async def __aenter__(self) -> MasterTcpRunner:
        await self.open()
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.close()

    # -- requests -------------------------------------------------------------

    async def integrity_poll(self) -> list[ResponseInfo]:
        """READ Class 0/1/2/3 and report every value to the SOE handler.

        Returns:
            Info for each fragment of the response burst, in arrival order.
        """
        return await self.request(self.master.build_integrity_poll())

    async def class_poll(
        self,
        *,
        class_1: bool = True,
        class_2: bool = True,
        class_3: bool = True,
    ) -> list[ResponseInfo]:
        """READ the named event classes.

        Class 0 (static data) is not a class poll upstream; use
        `integrity_poll()` for a full snapshot.

        Args:
            class_1: Include Class 1 events.
            class_2: Include Class 2 events.
            class_3: Include Class 3 events.

        Returns:
            Info for each fragment of the response burst.
        """
        request = self.master.build_class_poll(
            class_1=class_1,
            class_2=class_2,
            class_3=class_3,
        )
        return await self.request(request)

    async def request(self, request: RequestFragment) -> list[ResponseInfo]:
        """Send one application request and consume its whole response burst.

        A response may span several fragments. The outstation sets CON on every
        non-final fragment and waits for an application CONFIRM before sending
        the next, so this must answer or the exchange stalls until the
        outstation's confirm timer expires.

        Args:
            request: Application request to send.

        Returns:
            Info for each fragment of the burst, in arrival order.

        Raises:
            ResponseTimeoutError: No fragment arrived before the deadline, or
                the burst as a whole outran `response_timeout`.
            LinkError: The link failed or delivered unusable bytes.
            MasterRunnerError: The channel is not open, a fragment did not
                correlate to this request, or the burst exceeded
                `MAX_BURST_FRAGMENTS`.
        """
        self._require_open()
        await self.send(request)

        # One deadline for the whole exchange, not one per fragment: a per
        # fragment deadline lets a peer that answers slowly but steadily hold
        # the request open indefinitely.
        deadline = self._deadline(None)
        burst = _Burst(expected_seq=request.header.control.seq)
        while True:
            info = await self._next_solicited(burst, deadline)
            burst.fragments.append(info)

            if info.con:
                await self.send(self.master.build_confirm(info.sequence))
            if info.fin:
                return burst.fragments

            if len(burst.fragments) >= MAX_BURST_FRAGMENTS:
                msg = (
                    f"Response burst exceeded {MAX_BURST_FRAGMENTS} fragments "
                    "without setting FIN; abandoning the exchange"
                )
                raise MasterRunnerError(msg)

    async def send(self, request: RequestFragment) -> None:
        """Segment an application fragment and frame each segment onto the link.

        Args:
            request: Application request to transmit.
        """
        self._require_open()
        for segment in self._segmenter.segment(request.to_bytes()):
            await self._write_frame(
                build_unconfirmed_user_data(
                    destination=self.master.config.outstation_address,
                    source=self.master.config.address,
                    dir_from_master=True,
                    user_data=segment.to_bytes(),
                )
            )

    # -- unsolicited ----------------------------------------------------------

    async def enable_unsolicited(
        self,
        *,
        class_1: bool = True,
        class_2: bool = True,
        class_3: bool = True,
    ) -> list[ResponseInfo]:
        """Ask the outstation to report the named classes unsolicited.

        Args:
            class_1: Enable Class 1 reporting.
            class_2: Enable Class 2 reporting.
            class_3: Enable Class 3 reporting.

        Returns:
            Info for each fragment of the response burst.
        """
        request = self.master.build_enable_unsolicited(
            class_1=class_1,
            class_2=class_2,
            class_3=class_3,
        )
        return await self.request(request)

    async def disable_unsolicited(
        self,
        *,
        class_1: bool = True,
        class_2: bool = True,
        class_3: bool = True,
    ) -> list[ResponseInfo]:
        """Ask the outstation to stop reporting the named classes unsolicited.

        Args:
            class_1: Disable Class 1 reporting.
            class_2: Disable Class 2 reporting.
            class_3: Disable Class 3 reporting.

        Returns:
            Info for each fragment of the response burst.
        """
        request = self.master.build_disable_unsolicited(
            class_1=class_1,
            class_2=class_2,
            class_3=class_3,
        )
        return await self.request(request)

    async def listen_unsolicited(self, *, timeout: float | None = None) -> ResponseInfo | None:
        """Wait for one unsolicited response, reporting its values and confirming.

        Values reach the SOE handler as a side effect of parsing, the same as for
        a poll. Use this when the master is otherwise idle; unsolicited responses
        that arrive mid-request are handled inline by `request()`.

        `None` means "nothing arrived in time" and nothing more. A link that
        has failed raises `LinkError` rather than returning `None`, so a caller
        looping on this method can tell a quiet outstation from a dead one
        instead of spinning forever on a socket that will never speak again.

        Args:
            timeout: Seconds to wait. None waits `response_timeout`.

        Returns:
            Info for the unsolicited response, or None if none arrived in time.

        Raises:
            LinkError: The link failed or delivered unusable bytes.
            MasterRunnerError: The channel is not open.
        """
        self._require_open()
        deadline = self._deadline(timeout)
        while True:
            try:
                info = await self._receive_fragment(deadline)
            except ResponseTimeoutError as exc:
                logger.debug("No unsolicited response: %s", exc)
                return None
            if info is None or not info.is_unsolicited:
                continue
            return info

    # -- scheduling -----------------------------------------------------------

    async def run_polls(self, *, stop: asyncio.Event | None = None) -> None:
        """Drive the master's `PollScheduler` until stopped.

        Composes scheduling with transport rather than owning either: the
        intervals come from `PollingConfig`, the due-time arithmetic from
        `PollScheduler`, and only the sending happens here. Any other transport
        can reuse the same scheduler the same way.

        A failed poll does not end the loop. One dropped packet on a SCADA link
        is a `ResponseTimeoutError`, and a link that drops is a `LinkError`;
        treating either as fatal would turn a transient blip into permanent
        silence, with `is_open` still reporting `True` and the only trace a
        "Task exception was never retrieved" at shutdown. Failures are logged
        and the loop continues to the next due task. Cancellation and
        programming errors still propagate.

        Callers that need to react to failures rather than read logs should
        drive `poll()` directly; this method is the unsupervised convenience.

        Args:
            stop: Event that ends the loop when set. Without one the loop runs
                until cancelled.
        """
        self._require_open()
        stop = stop if stop is not None else asyncio.Event()

        while not stop.is_set():
            task = self.master.scheduler.get_next_task()
            if task is not None:
                try:
                    await self.poll(task)
                except MasterRunnerError:
                    logger.exception("Scheduled poll failed; continuing")
                continue

            wait = self.master.scheduler.get_time_until_next()
            if wait is None:
                return
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(stop.wait(), timeout=max(wait, 0.0))

    async def poll(self, task: PollTask) -> list[ResponseInfo]:
        """Run one scheduled poll task and mark it executed.

        The request is built by the task itself, using a sequence drawn from the
        master so a scheduled poll is numbered from the same counter as a direct
        one. `Master` allocates request sequences internally for its own
        builders; `next_request_sequence()` exposes that counter so a transport
        can number a task-built request without reaching into master state.

        Args:
            task: Task from the master's scheduler.

        Returns:
            Info for each fragment of the response burst.
        """
        request = task.build_request(seq=self.master.next_request_sequence())
        responses = await self.request(request)
        self.master.mark_poll_executed(task)
        return responses

    # -- protocol stack -------------------------------------------------------

    async def _next_solicited(self, burst: _Burst, deadline: float) -> ResponseInfo:
        """Read until the next fragment of a solicited burst arrives.

        Unsolicited responses interleaved with a request are confirmed and
        skipped: the outstation may report an event at any time, and discarding
        one would lose data the SOE handler has already been given.

        Args:
            burst: Burst being accumulated, for sequence continuity.
            deadline: Event-loop time the whole exchange must finish by.

        Returns:
            Info for the next solicited fragment.

        Raises:
            ResponseTimeoutError: No fragment arrived before the deadline.
            LinkError: The link failed or delivered unusable bytes.
            MasterRunnerError: The fragment did not correlate to the request.
        """
        while True:
            info = await self._receive_fragment(deadline, burst=burst)
            if info is None or info.is_unsolicited:
                continue
            return info

    def _screen_solicited(self, burst: _Burst, data: bytes) -> bool:
        """Correlate raw fragment bytes to the burst before they are dispatched.

        Reads only the application header, which is two bytes and cheap, so an
        uncorrelated fragment is rejected without its objects ever being parsed
        or handed to the SOE handler.

        Unsolicited fragments pass through untouched: they are not part of any
        burst and are confirmed and reported wherever they arrive.

        Args:
            burst: Burst being accumulated.
            data: Reassembled application fragment.

        Returns:
            True if the fragment should be parsed, False if it is not a response
            at all and should be skipped.

        Raises:
            MasterRunnerError: The fragment did not correlate to the request.
        """
        try:
            header, _ = parse_response_header(data)
        except (ParseError, ValueError, IndexError):
            # Not a parseable response header; let process_response log and
            # discard it through the existing path.
            return True
        if header.control.uns:
            return True
        self._check_sequence(burst, header.control.seq)
        return True

    def _check_sequence(self, burst: _Burst, sequence: int) -> None:
        """Correlate a fragment to the request and its place in the burst.

        IEEE 1815-2012 clause 4.2.2.4.5: the first fragment carries the
        request's sequence and each subsequent fragment increments by one,
        modulo 16. Because the burst is seeded with the request's own sequence,
        the same comparison does both jobs: it correlates fragment one to the
        request that is outstanding, and walks the rest.

        Correlating matters most in the ordinary case, not the adversarial one:
        without it, a late answer to a poll that already timed out is served as
        the *next* poll's response, and stale values reach the SOE handler
        looking current.

        Tracked per burst rather than in `SequenceState`, whose
        `last_request_seq` is a request-sequence allocator with a different
        lifetime; this walk lives and dies with one response.

        Args:
            burst: Burst being accumulated.
            sequence: Application sequence the fragment carried.

        Raises:
            MasterRunnerError: The sequence did not match.
        """
        if sequence != burst.expected_seq:
            position = len(burst.fragments) + 1
            detail = "does not match the request" if not burst.fragments else "broke the burst's sequence walk"
            msg = f"Response fragment {position} carried sequence {sequence}, expected {burst.expected_seq}: {detail}"
            raise MasterRunnerError(msg)
        burst.expected_seq = (sequence + 1) % (MAX_APP_SEQUENCE + 1)

    async def _receive_fragment(
        self,
        deadline: float,
        *,
        burst: _Burst | None = None,
    ) -> ResponseInfo | None:
        """Read until one application fragment is parsed, or the deadline passes.

        When accumulating a solicited burst, the fragment's sequence is checked
        *before* `Master.process_response` sees it. That ordering is the whole
        point: `process_response` dispatches parsed values to the SOE handler
        (`master.py:657`) ahead of its own sequence validation, so a fragment
        rejected afterwards has already delivered its values. Raising later
        would tell the caller something was wrong but leave stale analog values
        sitting in the handler as current.

        Args:
            deadline: Event-loop time after which to give up.
            burst: Solicited burst being accumulated, if any. Unsolicited
                listening passes None, having no request to correlate against.

        Returns:
            Info for the fragment, or None if it did not parse as a response.

        Raises:
            ResponseTimeoutError: The deadline passed, or the peer closed.
            LinkError: The link failed or delivered unusable bytes.
            MasterRunnerError: The fragment did not correlate to the request.
        """
        data = await self._read_fragment_bytes(deadline)
        if burst is not None and not self._screen_solicited(burst, data):
            return None
        info = self.master.process_response(data)
        if info is None:
            logger.warning("Discarding %d bytes that did not parse as a response", len(data))
            return None

        # An unsolicited response must be confirmed whether or not the master is
        # mid-request; the outstation retries until it is.
        if info.is_unsolicited and self.master.needs_confirm():
            logger.debug("Confirming unsolicited response seq=%d", info.sequence)
            await self.send(self.master.build_confirm(self.master.get_confirm_sequence()))
            self.master.on_confirm_sent()

        return info

    async def _read_fragment_bytes(self, deadline: float) -> bytes:
        """Read link frames until one application fragment is reassembled.

        Frames addressed elsewhere and link-management frames carrying no user
        data are skipped.

        Args:
            deadline: Event-loop time after which to give up.

        Returns:
            The reassembled application fragment.

        Raises:
            ResponseTimeoutError: The deadline passed, or the peer closed.
            LinkError: The link failed, or a transport segment did not fit the
                stream being reassembled.
        """
        channel, reassembler = self._require_open()
        loop = asyncio.get_running_loop()

        while True:
            # Frames already parsed but not yet consumed come first: one read can
            # yield several, and the fragment that completes here may be followed
            # by frames belonging to the next one.
            while self._pending:
                fragment = self._consume_frame(self._pending.popleft(), reassembler)
                if fragment is not None:
                    return fragment

            remaining = deadline - loop.time()
            if remaining <= 0:
                msg = "Timed out waiting for a response fragment"
                raise ResponseTimeoutError(msg)

            try:
                data = await asyncio.wait_for(channel.read(READ_CHUNK_SIZE), timeout=remaining)
            except TimeoutError as exc:
                msg = "Timed out reading from the outstation"
                raise ResponseTimeoutError(msg) from exc
            except ChannelError as exc:
                # Catches the whole family, not just ChannelClosedError:
                # TcpClientChannel.read raises the bare parent on OSError, so an
                # ECONNRESET (the most common way a real link dies) arrives
                # as ChannelError itself.
                msg = f"Link failed while awaiting a response: {exc}"
                raise LinkError(msg) from exc

            if not data:
                msg = "Peer closed the connection while awaiting a response"
                raise ResponseTimeoutError(msg)

            # Drain the parser in full before handling any frame. `feed()`
            # materializes every complete frame from the chunk, so consuming
            # them inside the iteration and returning early would discard the
            # rest. A kernel that coalesces an ACK with a response, or two
            # back-to-back segments, into one read makes that routine.
            self._pending.extend(self._parser.feed(data))

    def _consume_frame(self, frame: DataLinkFrame, reassembler: Reassembler) -> bytes | None:
        """Filter one link frame and offer its segment to the reassembler.

        Args:
            frame: Frame to consider.
            reassembler: Reassembler accumulating the current fragment.

        Returns:
            The reassembled application fragment, or None if this frame was
            skipped or the fragment is still incomplete.

        Raises:
            LinkError: The segment did not fit the stream being reassembled.
        """
        config = self.master.config
        # Both addresses, not just the destination. A frame merely addressed to
        # this master may still come from another outstation on the same link,
        # and would otherwise satisfy an outstanding request with foreign values.
        if frame.header.destination != config.address:
            return None
        if frame.header.source != config.outstation_address:
            logger.warning(
                "Ignoring frame addressed to this master from source %d; expected %d",
                frame.header.source,
                config.outstation_address,
            )
            return None
        # Link-management frames (ACK, link status) carry no user data
        # and nothing to reassemble. Checked before the function code
        # because the codes collide numerically across the PRM bit:
        # SEC_ACK and PRI_RESET_LINK_STATE are both 0, and
        # SEC_NACK and PRI_RESET_USER_PROCESS are both 1.
        if not frame.user_data:
            return None
        if frame.header.control.function_code not in _USER_DATA_FUNCTION_CODES:
            return None

        try:
            result = reassembler.add(TransportSegment.from_bytes(frame.user_data))
        except ReassemblyError as exc:
            # Fail closed, as the outstation sibling does: drop the partial
            # stream so the next fragment starts clean rather than being
            # assembled onto a desynchronized prefix.
            reassembler.reset()
            msg = f"Transport reassembly failed: {exc}"
            raise LinkError(msg) from exc
        return None if result is None else result.data

    async def _send_link_reset(self) -> None:
        """Send RESET_LINK_STATE.

        The ACK is consumed opportunistically by the next read: a reset is
        advisory for a master, and some outstations answer only once the first
        request arrives.
        """
        await self._write_frame(
            build_reset_link_state(
                destination=self.master.config.outstation_address,
                source=self.master.config.address,
                dir_from_master=True,
            )
        )
        logger.debug("Sent RESET_LINK_STATE to outstation %d", self.master.config.outstation_address)

    async def _write_frame(self, frame: DataLinkFrame) -> None:
        """Write one link frame to the channel.

        Args:
            frame: Frame to transmit.
        """
        channel, _ = self._require_open()
        await channel.write_all(frame.to_bytes())

    def _deadline(self, timeout: float | None) -> float:
        """Absolute event-loop time a wait should end at.

        Args:
            timeout: Seconds to wait, or None for `response_timeout`.

        Returns:
            Event-loop time of the deadline.
        """
        return asyncio.get_running_loop().time() + (self.response_timeout if timeout is None else timeout)

    def _require_open(self) -> tuple[Channel, Reassembler]:
        """Return the channel and reassembler, or fail if `open()` has not run.

        Returning the narrowed pair rather than asserting keeps the invariant
        enforced under `python -O`, where `assert` is stripped.

        Returns:
            The open channel and its reassembler.

        Raises:
            MasterRunnerError: `open()` has not been awaited, or the channel has
                since closed.
        """
        if self.channel is None or self._reassembler is None:
            msg = "open() must be awaited before using the runner"
            raise MasterRunnerError(msg)
        # `is_open` rather than `is not None`: an injected channel closed by its
        # owner, or a peer that dropped the link, would otherwise surface as a
        # bare ChannelClosedError from the first write and a ResponseTimeoutError
        # from the first read: two wrong types for one condition.
        if not self.channel.is_open:
            msg = "Channel is closed; open() must be awaited before using the runner"
            raise MasterRunnerError(msg)
        return self.channel, self._reassembler

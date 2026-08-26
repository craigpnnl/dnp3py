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
from dataclasses import dataclass, field
from enum import Enum, auto

from dnp3.application.fragment import RequestFragment
from dnp3.application.header import MAX_APP_SEQUENCE
from dnp3.core.enums import LinkFunctionCode
from dnp3.datalink.builder import build_reset_link_state, build_unconfirmed_user_data
from dnp3.datalink.frame import DataLinkFrame
from dnp3.datalink.parser import FrameParser
from dnp3.master.handler import ResponseInfo
from dnp3.master.master import Master
from dnp3.master.polling import PollTask
from dnp3.transport.reassembler import Reassembler
from dnp3.transport.segment import TransportSegment
from dnp3.transport.segmenter import Segmenter
from dnp3.transport_io.channel import Channel, ChannelClosedError, TcpConfig
from dnp3.transport_io.tcp_client import TcpClientChannel

logger = logging.getLogger(__name__)

READ_CHUNK_SIZE = 4096
"""Bytes requested per channel read. Frames are reassembled across reads."""

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


@dataclass
class _Burst:
    """One solicited response burst, accumulated across fragments.

    Attributes:
        fragments: Info for each fragment, in arrival order.
        expected_seq: Sequence the next fragment must carry, or None before the
            first fragment has established the walk.
    """

    fragments: list[ResponseInfo] = field(default_factory=list)
    expected_seq: int | None = None


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
        """Open the channel and, by policy, reset the data link."""
        if self.channel is None:
            self.channel = TcpClientChannel(config=TcpConfig(host=self.host, port=self.port))
            self._owns_channel = True

        if not self.channel.is_open:
            await self.channel.open()

        # Bound reassembly by the master's own fragment cap so a peer that never
        # sets FIN cannot exhaust memory.
        self._reassembler = Reassembler(max_fragment_size=self.master.config.max_fragment_size)

        if self.link_reset is LinkResetPolicy.ON_OPEN:
            await self._send_link_reset()

    async def close(self) -> None:
        """Close the channel if this runner opened it."""
        if self.channel is not None and self._owns_channel:
            await self.channel.close()

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
            ResponseTimeoutError: No fragment arrived before the deadline.
            MasterRunnerError: The channel is not open, or a fragment arrived
                out of sequence.
        """
        self._require_open()
        await self.send(request)

        burst = _Burst()
        while True:
            info = await self._next_solicited(burst)
            burst.fragments.append(info)

            if info.con:
                await self.send(self.master.build_confirm(info.sequence))
            if info.fin:
                return burst.fragments

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

        Args:
            timeout: Seconds to wait. None waits `response_timeout`.

        Returns:
            Info for the unsolicited response, or None if none arrived in time.
        """
        self._require_open()
        deadline = self._deadline(timeout)
        while True:
            try:
                info = await self._receive_fragment(deadline)
            except ResponseTimeoutError:
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

        Args:
            stop: Event that ends the loop when set. Without one the loop runs
                until cancelled.
        """
        self._require_open()
        stop = stop if stop is not None else asyncio.Event()

        while not stop.is_set():
            task = self.master.scheduler.get_next_task()
            if task is not None:
                await self.poll(task)
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

    async def _next_solicited(self, burst: _Burst) -> ResponseInfo:
        """Read until the next fragment of a solicited burst arrives.

        Unsolicited responses interleaved with a request are confirmed and
        skipped: the outstation may report an event at any time, and discarding
        one would lose data the SOE handler has already been given.

        Args:
            burst: Burst being accumulated, for sequence continuity.

        Returns:
            Info for the next solicited fragment.

        Raises:
            ResponseTimeoutError: No fragment arrived before the deadline.
            MasterRunnerError: The fragment's sequence broke the walk.
        """
        deadline = self._deadline(None)
        while True:
            info = await self._receive_fragment(deadline)
            if info is None or info.is_unsolicited:
                continue
            self._check_sequence(burst, info)
            return info

    def _check_sequence(self, burst: _Burst, info: ResponseInfo) -> None:
        """Verify a fragment continues the burst's sequence walk.

        IEEE 1815-2012 clause 4.2.2.4.5: the first fragment carries the
        request's sequence and each subsequent fragment increments by one,
        modulo 16. Tracked per burst rather than in `SequenceState`, whose
        `last_request_seq` is a request-sequence allocator with a different
        lifetime; this walk lives and dies with one response.

        Args:
            burst: Burst being accumulated.
            info: Fragment just received.

        Raises:
            MasterRunnerError: The sequence did not match.
        """
        if burst.expected_seq is not None and info.sequence != burst.expected_seq:
            msg = (
                f"Response fragment {len(burst.fragments) + 1} carried sequence "
                f"{info.sequence}, expected {burst.expected_seq}"
            )
            raise MasterRunnerError(msg)
        burst.expected_seq = (info.sequence + 1) % (MAX_APP_SEQUENCE + 1)

    async def _receive_fragment(self, deadline: float) -> ResponseInfo | None:
        """Read until one application fragment is parsed, or the deadline passes.

        Args:
            deadline: Event-loop time after which to give up.

        Returns:
            Info for the fragment, or None if it did not parse as a response.

        Raises:
            ResponseTimeoutError: The deadline passed, or the peer closed.
        """
        data = await self._read_fragment_bytes(deadline)
        info = self.master.process_response(data)
        if info is None:
            logger.warning("Discarding %d bytes that did not parse as a response", len(data))
            return None

        # An unsolicited response must be confirmed whether or not the master is
        # mid-request; the outstation retries until it is.
        if info.is_unsolicited and self.master.needs_confirm():
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
        """
        channel, reassembler = self._require_open()
        loop = asyncio.get_running_loop()

        while True:
            remaining = deadline - loop.time()
            if remaining <= 0:
                msg = "Timed out waiting for a response fragment"
                raise ResponseTimeoutError(msg)

            try:
                data = await asyncio.wait_for(channel.read(READ_CHUNK_SIZE), timeout=remaining)
            except TimeoutError as exc:
                msg = "Timed out reading from the outstation"
                raise ResponseTimeoutError(msg) from exc
            except ChannelClosedError as exc:
                msg = "Channel closed while awaiting a response"
                raise ResponseTimeoutError(msg) from exc

            if not data:
                msg = "Peer closed the connection while awaiting a response"
                raise ResponseTimeoutError(msg)

            for frame in self._parser.feed(data):
                if frame.header.destination != self.master.config.address:
                    continue
                # Link-management frames (ACK, link status) carry no user data
                # and nothing to reassemble. Checked before the function code
                # because the codes collide numerically across the PRM bit:
                # SEC_ACK and PRI_RESET_LINK_STATE are both 0, and
                # SEC_NACK and PRI_RESET_USER_PROCESS are both 1.
                if not frame.user_data:
                    continue
                if frame.header.control.function_code not in _USER_DATA_FUNCTION_CODES:
                    continue

                result = reassembler.add(TransportSegment.from_bytes(frame.user_data))
                if result is not None:
                    return result.data

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
            MasterRunnerError: `open()` has not been awaited.
        """
        if self.channel is None or self._reassembler is None:
            msg = "open() must be awaited before using the runner"
            raise MasterRunnerError(msg)
        return self.channel, self._reassembler

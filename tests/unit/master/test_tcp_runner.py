"""Unit tests for `MasterTcpRunner`, driven over an in-memory channel.

The runner is exercised against a `SimulatorChannel` pair rather than a socket:
these tests cover the protocol stack (framing, reassembly, the CONFIRM
handshake, the sequence walk), which needs no network. Socket-level cover lives
in `tests/integration/test_tcp_master_runner_e2e.py`.

The peer side is deliberately hand-rolled rather than an `Outstation`, so a
fragment burst can be emitted with a chosen sequence, including a wrong one,
which a conformant outstation would never produce.
"""

from __future__ import annotations

import asyncio
import contextlib
import struct

import pytest

from dnp3.application.builder import build_response
from dnp3.application.fragment import ObjectBlock
from dnp3.application.qualifiers import ObjectHeader
from dnp3.core.enums import FunctionCode, LinkFunctionCode
from dnp3.datalink.builder import (
    build_ack,
    build_primary_frame,
    build_unconfirmed_user_data,
)
from dnp3.datalink.parser import FrameParser
from dnp3.master.config import MasterConfig
from dnp3.master.handler import ResponseInfo
from dnp3.master.master import Master
from dnp3.master.polling import IntegrityPollTask
from dnp3.master.tcp_runner import (
    LinkError,
    LinkResetPolicy,
    MasterRunnerError,
    MasterTcpRunner,
    ResponseTimeoutError,
)
from dnp3.transport.segment import TransportSegment
from dnp3.transport_io.channel import ChannelError
from dnp3.transport_io.simulator import create_channel_pair

MASTER_ADDR = 3
OUTSTATION_ADDR = 1
FLAGS_ONLINE = 0x01


class RecordingHandler:
    """Records values and fragment info the master delivers."""

    def __init__(self) -> None:
        self.analog_inputs: dict[int, float] = {}
        self.responses: list[ResponseInfo] = []

    def on_binary_input(self, values: list, info: ResponseInfo) -> None:
        pass

    def on_binary_output(self, values: list, info: ResponseInfo) -> None:
        pass

    def on_analog_input(self, values: list, info: ResponseInfo) -> None:
        self.analog_inputs.update({v.index: v.value for v in values})

    def on_analog_output(self, values: list, info: ResponseInfo) -> None:
        pass

    def on_counter(self, values: list, info: ResponseInfo) -> None:
        pass

    def on_frozen_counter(self, values: list, info: ResponseInfo) -> None:
        pass

    def on_response(self, info: ResponseInfo) -> None:
        self.responses.append(info)


class FakeOutstation:
    """Minimal peer that frames application fragments onto a channel.

    Only what the runner's tests need: emit a burst with chosen sequences, read
    what the master sends, and answer link resets.
    """

    def __init__(self, channel: object) -> None:
        self.channel = channel
        self.parser = FrameParser()
        self.received: list[bytes] = []

    async def send_fragment(self, app_bytes: bytes) -> None:
        """Frame one application fragment as a single transport segment."""
        segment = TransportSegment.build(fir=True, fin=True, seq=0, payload=app_bytes)
        frame = build_unconfirmed_user_data(
            destination=MASTER_ADDR,
            source=OUTSTATION_ADDR,
            dir_from_master=False,
            user_data=segment.to_bytes(),
        )
        await self.channel.write_all(frame.to_bytes())  # type: ignore[attr-defined]

    def frame_fragment(self, app_bytes: bytes) -> bytes:
        """Frame one application fragment, returning the bytes without sending."""
        segment = TransportSegment.build(fir=True, fin=True, seq=0, payload=app_bytes)
        frame = build_unconfirmed_user_data(
            destination=MASTER_ADDR,
            source=OUTSTATION_ADDR,
            dir_from_master=False,
            user_data=segment.to_bytes(),
        )
        return frame.to_bytes()

    async def send_raw(self, data: bytes) -> None:
        """Write pre-framed bytes in one call.

        One `write_all` is one queue item and therefore one `read()` on the far
        side, which is how a coalesced read is reproduced without a real kernel:
        passing two concatenated frames here delivers both in a single read.
        """
        await self.channel.write_all(data)  # type: ignore[attr-defined]

    async def send_fragment_from(self, app_bytes: bytes, *, source: int) -> None:
        """Frame a fragment from an arbitrary source address."""
        segment = TransportSegment.build(fir=True, fin=True, seq=0, payload=app_bytes)
        frame = build_unconfirmed_user_data(
            destination=MASTER_ADDR,
            source=source,
            dir_from_master=False,
            user_data=segment.to_bytes(),
        )
        await self.channel.write_all(frame.to_bytes())  # type: ignore[attr-defined]

    async def send_ack(self) -> None:
        """Answer a link reset with an ACK carrying no user data."""
        ack = build_ack(MASTER_ADDR, OUTSTATION_ADDR, False)
        await self.channel.write_all(ack.to_bytes())  # type: ignore[attr-defined]

    async def read_request_seq(self, timeout: float = 2.0) -> int:
        """Read one request and return the application sequence it carries.

        A real outstation answers with the sequence it was asked on; tests that
        hardcode a response sequence instead are asserting against a peer no
        conformant outstation resembles.
        """
        fragments = await self.read_fragments(1, timeout=timeout)
        return fragments[0][0] & 0x0F

    async def read_fragments(self, count: int, timeout: float = 2.0) -> list[bytes]:
        """Read until `count` application fragments arrive from the master."""
        out: list[bytes] = []
        deadline = asyncio.get_running_loop().time() + timeout
        while len(out) < count:
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                pytest.fail(f"expected {count} fragments, got {len(out)}")
            data = await asyncio.wait_for(
                self.channel.read(4096),  # type: ignore[attr-defined]
                timeout=remaining,
            )
            for frame in self.parser.feed(data):
                if not frame.user_data:
                    continue
                out.append(TransportSegment.from_bytes(frame.user_data).payload)
        return out


def analog_block(index: int, value: float) -> ObjectBlock:
    """One g30v5 (float32) analog input at `index`, count-qualified.

    Qualifier 0x17 is a 1-byte count with a 1-byte index prefix per object, so
    the index travels on the wire and does not have to be consecutive.
    """
    header = ObjectHeader(group=30, variation=5, qualifier=0x17)
    data = bytes([0x01, index, FLAGS_ONLINE]) + struct.pack("<f", value)
    return ObjectBlock(header=header, data=data)


def analog_response(*, seq: int, fir: bool, fin: bool, con: bool, index: int, value: float) -> bytes:
    """Build one response fragment carrying a single analog input.

    Args:
        seq: Application sequence number.
        fir: First-fragment flag.
        fin: Final-fragment flag.
        con: Whether to request an application CONFIRM.
        index: Analog input index.
        value: Analog value.

    Returns:
        Application fragment bytes.
    """
    response = build_response(
        objects=(analog_block(index, value),),
        seq=seq,
        fir=fir,
        fin=fin,
    )
    data = bytearray(response.to_bytes())
    if con:
        data[0] |= 0x20  # CON bit
    return bytes(data)


def make_runner(
    channel: object,
    *,
    link_reset: LinkResetPolicy = LinkResetPolicy.NEVER,
    response_timeout: float = 2.0,
) -> tuple[MasterTcpRunner, RecordingHandler]:
    """Build a runner over a supplied channel, with a recording handler."""
    handler = RecordingHandler()
    master = Master(
        config=MasterConfig(address=MASTER_ADDR, outstation_address=OUTSTATION_ADDR),
        handler=handler,
    )
    runner = MasterTcpRunner(
        master=master,
        channel=channel,  # type: ignore[arg-type]
        link_reset=link_reset,
        response_timeout=response_timeout,
    )
    return runner, handler


class TestLifecycle:
    """Open, close, and guard rails."""

    async def test_requires_open_before_request(self) -> None:
        """Using the runner before open() raises rather than mis-sending."""
        channel_a, _ = create_channel_pair()
        runner, _ = make_runner(channel_a)

        with pytest.raises(MasterRunnerError, match="open"):
            await runner.integrity_poll()

    async def test_open_sends_link_reset_by_policy(self) -> None:
        """ON_OPEN emits a RESET_LINK_STATE frame; NEVER emits nothing."""
        channel_a, channel_b = create_channel_pair()
        await channel_a.open()
        await channel_b.open()

        runner, _ = make_runner(channel_a, link_reset=LinkResetPolicy.ON_OPEN)
        await runner.open()

        data = await asyncio.wait_for(channel_b.read(4096), timeout=1.0)
        frames = list(FrameParser().feed(data))
        assert len(frames) == 1
        assert frames[0].header.control.function_code == LinkFunctionCode.PRI_RESET_LINK_STATE.value

    async def test_never_policy_skips_link_reset(self) -> None:
        """NEVER opens the channel without writing anything."""
        channel_a, channel_b = create_channel_pair()
        await channel_a.open()
        await channel_b.open()

        runner, _ = make_runner(channel_a, link_reset=LinkResetPolicy.NEVER)
        await runner.open()

        with pytest.raises(TimeoutError):
            await asyncio.wait_for(channel_b.read(4096), timeout=0.2)

    async def test_close_leaves_injected_channel_open(self) -> None:
        """A channel the runner did not open is not closed by it."""
        channel_a, _ = create_channel_pair()
        await channel_a.open()
        runner, _ = make_runner(channel_a)
        await runner.open()
        await runner.close()

        assert channel_a.is_open

    async def test_async_context_manager(self) -> None:
        """The runner works as an async context manager."""
        channel_a, _ = create_channel_pair()
        await channel_a.open()
        runner, _ = make_runner(channel_a)

        async with runner as entered:
            assert entered is runner
            assert runner.is_open


class TestSingleFragment:
    """A response that fits one fragment."""

    async def test_integrity_poll_decodes_values(self) -> None:
        """Values from a single-fragment response reach the SOE handler."""
        channel_a, channel_b = create_channel_pair()
        await channel_a.open()
        await channel_b.open()
        runner, handler = make_runner(channel_a)
        await runner.open()
        peer = FakeOutstation(channel_b)

        async def respond() -> None:
            await peer.read_fragments(1)
            await peer.send_fragment(analog_response(seq=0, fir=True, fin=True, con=False, index=4, value=12.5))

        responder = asyncio.create_task(respond())
        infos = await runner.integrity_poll()
        await responder

        assert len(infos) == 1
        assert infos[0].fin is True
        assert handler.analog_inputs[4] == pytest.approx(12.5)

    async def test_no_confirm_when_con_clear(self) -> None:
        """A final fragment without CON is not confirmed."""
        channel_a, channel_b = create_channel_pair()
        await channel_a.open()
        await channel_b.open()
        runner, _ = make_runner(channel_a)
        await runner.open()
        peer = FakeOutstation(channel_b)

        async def respond() -> None:
            await peer.read_fragments(1)
            await peer.send_fragment(analog_response(seq=0, fir=True, fin=True, con=False, index=0, value=1.0))

        responder = asyncio.create_task(respond())
        await runner.integrity_poll()
        await responder

        # Nothing further should arrive from the master.
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(channel_b.read(4096), timeout=0.2)


class TestMultiFragment:
    """Bursts that span fragments, with the CONFIRM handshake."""

    async def test_confirms_each_non_final_fragment(self) -> None:
        """The master confirms every CON fragment and stops at FIN."""
        channel_a, channel_b = create_channel_pair()
        await channel_a.open()
        await channel_b.open()
        runner, handler = make_runner(channel_a)
        await runner.open()
        peer = FakeOutstation(channel_b)
        confirms: list[bytes] = []

        async def respond() -> None:
            await peer.read_fragments(1)
            # Fragment 1 of 3: CON set, awaiting confirm.
            await peer.send_fragment(analog_response(seq=0, fir=True, fin=False, con=True, index=0, value=1.0))
            confirms.extend(await peer.read_fragments(1))
            await peer.send_fragment(analog_response(seq=1, fir=False, fin=False, con=True, index=1, value=2.0))
            confirms.extend(await peer.read_fragments(1))
            await peer.send_fragment(analog_response(seq=2, fir=False, fin=True, con=False, index=2, value=3.0))

        responder = asyncio.create_task(respond())
        infos = await runner.integrity_poll()
        await responder

        assert [i.sequence for i in infos] == [0, 1, 2]
        assert [i.fin for i in infos] == [False, False, True]
        assert len(confirms) == 2
        assert handler.analog_inputs == {
            0: pytest.approx(1.0),
            1: pytest.approx(2.0),
            2: pytest.approx(3.0),
        }

    async def test_confirm_echoes_received_sequence(self) -> None:
        """Each CONFIRM carries the sequence of the fragment it answers.

        Regression guard for the constraint #61 introduced upstream: the
        outstation discards a CONFIRM whose sequence does not match the fragment
        it is awaiting, and does so silently until its confirm timer expires.
        """
        channel_a, channel_b = create_channel_pair()
        await channel_a.open()
        await channel_b.open()
        runner, _ = make_runner(channel_a)
        await runner.open()
        peer = FakeOutstation(channel_b)
        confirms: list[bytes] = []

        seq_holder: list[int] = []

        async def respond() -> None:
            seq = await peer.read_request_seq()
            seq_holder.append(seq)
            await peer.send_fragment(analog_response(seq=seq, fir=True, fin=False, con=True, index=0, value=1.0))
            confirms.extend(await peer.read_fragments(1))
            await peer.send_fragment(
                analog_response(seq=(seq + 1) % 16, fir=False, fin=True, con=False, index=1, value=2.0)
            )

        responder = asyncio.create_task(respond())
        await runner.integrity_poll()
        await responder

        assert len(confirms) == 1
        assert confirms[0][1] == FunctionCode.CONFIRM.value
        # Application control byte low nibble is the sequence.
        assert confirms[0][0] & 0x0F == seq_holder[0]

    async def test_accepts_sequence_wrap(self) -> None:
        """A burst crossing 15 -> 0 is accepted, per modulo-16 sequencing."""
        channel_a, channel_b = create_channel_pair()
        await channel_a.open()
        await channel_b.open()
        runner, _ = make_runner(channel_a)
        await runner.open()
        peer = FakeOutstation(channel_b)

        # Walk the master's own counter so the *next* allocation, the one
        # `build_integrity_poll()` makes, is 15 and its burst is the one that
        # wraps. The wrap has to be reached through the allocator rather than by
        # inventing a response sequence: fragment one is now correlated to the
        # request that was actually sent.
        while runner.master.next_request_sequence() != 14:
            pass

        async def respond() -> None:
            seq = await peer.read_request_seq()
            assert seq == 15, "request should carry the sequence the counter was walked to"
            await peer.send_fragment(analog_response(seq=15, fir=True, fin=False, con=True, index=0, value=1.0))
            await peer.read_fragments(1)
            await peer.send_fragment(analog_response(seq=0, fir=False, fin=True, con=False, index=1, value=2.0))

        responder = asyncio.create_task(respond())
        infos = await runner.integrity_poll()
        await responder

        assert [i.sequence for i in infos] == [15, 0]

    async def test_rejects_non_incrementing_sequence(self) -> None:
        """A repeated sequence raises instead of silently accepting the burst.

        This is the behaviour that would have deadlocked against the outstation
        before #61: a fragment that does not advance the walk is a conformance
        error, not data.
        """
        channel_a, channel_b = create_channel_pair()
        await channel_a.open()
        await channel_b.open()
        runner, _ = make_runner(channel_a)
        await runner.open()
        peer = FakeOutstation(channel_b)

        async def respond() -> None:
            # Fragment one must correlate to the request, so the rejection under
            # test is the repeat rather than a mismatched first fragment.
            seq = await peer.read_request_seq()
            await peer.send_fragment(analog_response(seq=seq, fir=True, fin=False, con=True, index=0, value=1.0))
            await peer.read_fragments(1)
            # Same sequence again: the pre-#61 outstation behaviour.
            await peer.send_fragment(analog_response(seq=seq, fir=False, fin=True, con=False, index=1, value=2.0))

        responder = asyncio.create_task(respond())
        with pytest.raises(MasterRunnerError, match="sequence"):
            await runner.integrity_poll()
        await responder


class TestUnsolicited:
    """Unsolicited responses, standalone and interleaved."""

    async def test_listen_confirms_and_reports(self) -> None:
        """An unsolicited response is confirmed and its values reported."""
        channel_a, channel_b = create_channel_pair()
        await channel_a.open()
        await channel_b.open()
        runner, handler = make_runner(channel_a)
        await runner.open()
        peer = FakeOutstation(channel_b)

        unsolicited = bytearray(analog_response(seq=2, fir=True, fin=True, con=True, index=9, value=42.0))
        unsolicited[0] |= 0x10  # UNS bit
        unsolicited[1] = FunctionCode.UNSOLICITED_RESPONSE.value

        await peer.send_fragment(bytes(unsolicited))
        info = await runner.listen_unsolicited(timeout=2.0)

        assert info is not None
        assert info.is_unsolicited is True
        assert handler.analog_inputs[9] == pytest.approx(42.0)

        confirms = await peer.read_fragments(1)
        assert confirms[0][1] == FunctionCode.CONFIRM.value

    async def test_listen_returns_none_on_timeout(self) -> None:
        """No unsolicited traffic yields None rather than raising."""
        channel_a, channel_b = create_channel_pair()
        await channel_a.open()
        await channel_b.open()
        runner, _ = make_runner(channel_a)
        await runner.open()

        assert await runner.listen_unsolicited(timeout=0.2) is None

    async def test_unsolicited_interleaved_with_poll(self) -> None:
        """An unsolicited response mid-poll is handled without losing the burst.

        The outstation may report an event at any time, including between the
        fragments of a response to a poll. The unsolicited fragment must not be
        counted as part of the burst, nor discarded.
        """
        channel_a, channel_b = create_channel_pair()
        await channel_a.open()
        await channel_b.open()
        runner, handler = make_runner(channel_a)
        await runner.open()
        peer = FakeOutstation(channel_b)

        unsolicited = bytearray(analog_response(seq=6, fir=True, fin=True, con=True, index=99, value=7.0))
        unsolicited[0] |= 0x10
        unsolicited[1] = FunctionCode.UNSOLICITED_RESPONSE.value

        async def respond() -> None:
            await peer.read_fragments(1)
            await peer.send_fragment(analog_response(seq=0, fir=True, fin=False, con=True, index=0, value=1.0))
            # Master's CONFIRM for fragment 1, then its CONFIRM for the
            # unsolicited response; order is not guaranteed, so just drain 2.
            await peer.send_fragment(bytes(unsolicited))
            await peer.read_fragments(2)
            await peer.send_fragment(analog_response(seq=1, fir=False, fin=True, con=False, index=1, value=2.0))

        responder = asyncio.create_task(respond())
        infos = await runner.integrity_poll()
        await responder

        # The burst is the two solicited fragments only.
        assert [i.sequence for i in infos] == [0, 1]
        assert all(not i.is_unsolicited for i in infos)
        # Values from both the poll and the unsolicited report are delivered.
        assert handler.analog_inputs[0] == pytest.approx(1.0)
        assert handler.analog_inputs[1] == pytest.approx(2.0)
        assert handler.analog_inputs[99] == pytest.approx(7.0)


class TestLinkLayer:
    """Frames that must be skipped rather than reassembled."""

    async def test_skips_ack_with_no_user_data(self) -> None:
        """A link ACK is skipped; the response after it is still read."""
        channel_a, channel_b = create_channel_pair()
        await channel_a.open()
        await channel_b.open()
        runner, handler = make_runner(channel_a)
        await runner.open()
        peer = FakeOutstation(channel_b)

        async def respond() -> None:
            await peer.read_fragments(1)
            await peer.send_ack()
            await peer.send_fragment(analog_response(seq=0, fir=True, fin=True, con=False, index=1, value=5.0))

        responder = asyncio.create_task(respond())
        infos = await runner.integrity_poll()
        await responder

        assert len(infos) == 1
        assert handler.analog_inputs[1] == pytest.approx(5.0)

    async def test_skips_frame_addressed_elsewhere(self) -> None:
        """A frame for another master is ignored."""
        channel_a, channel_b = create_channel_pair()
        await channel_a.open()
        await channel_b.open()
        runner, handler = make_runner(channel_a)
        await runner.open()
        peer = FakeOutstation(channel_b)

        async def respond() -> None:
            await peer.read_fragments(1)
            stray = build_unconfirmed_user_data(
                destination=MASTER_ADDR + 40,
                source=OUTSTATION_ADDR,
                dir_from_master=False,
                user_data=TransportSegment.build(
                    fir=True,
                    fin=True,
                    seq=0,
                    payload=analog_response(seq=0, fir=True, fin=True, con=False, index=7, value=99.0),
                ).to_bytes(),
            )
            await channel_b.write_all(stray.to_bytes())
            await peer.send_fragment(analog_response(seq=0, fir=True, fin=True, con=False, index=1, value=5.0))

        responder = asyncio.create_task(respond())
        await runner.integrity_poll()
        await responder

        assert 7 not in handler.analog_inputs
        assert handler.analog_inputs[1] == pytest.approx(5.0)


class TestTimeouts:
    """Deadlines and peer close."""

    async def test_silent_peer_times_out(self) -> None:
        """No response at all raises ResponseTimeoutError."""
        channel_a, channel_b = create_channel_pair()
        await channel_a.open()
        await channel_b.open()
        runner, _ = make_runner(channel_a, response_timeout=0.2)
        await runner.open()

        with pytest.raises(ResponseTimeoutError):
            await runner.integrity_poll()

    async def test_stalled_burst_times_out(self) -> None:
        """A burst that stops mid-way raises rather than hanging forever."""
        channel_a, channel_b = create_channel_pair()
        await channel_a.open()
        await channel_b.open()
        runner, _ = make_runner(channel_a, response_timeout=0.3)
        await runner.open()
        peer = FakeOutstation(channel_b)

        async def respond() -> None:
            await peer.read_fragments(1)
            await peer.send_fragment(analog_response(seq=0, fir=True, fin=False, con=True, index=0, value=1.0))
            # Then nothing: the second fragment never comes.

        responder = asyncio.create_task(respond())
        with pytest.raises(ResponseTimeoutError):
            await runner.integrity_poll()
        await responder


class TestRequestVariants:
    """Request builders that wrap `request()`."""

    @staticmethod
    async def _respond_once(peer: FakeOutstation) -> None:
        """Read one request and answer it with a single-fragment response."""
        await peer.read_fragments(1)
        await peer.send_fragment(analog_response(seq=0, fir=True, fin=True, con=False, index=0, value=1.0))

    async def _exchange(self, call: str, **kwargs: object) -> bytes:
        """Invoke a runner method by name and return the request it sent."""
        channel_a, channel_b = create_channel_pair()
        await channel_a.open()
        await channel_b.open()
        runner, _ = make_runner(channel_a)
        await runner.open()
        peer = FakeOutstation(channel_b)

        sent: list[bytes] = []

        async def respond() -> None:
            sent.extend(await peer.read_fragments(1))
            await peer.send_fragment(analog_response(seq=0, fir=True, fin=True, con=False, index=0, value=1.0))

        responder = asyncio.create_task(respond())
        await getattr(runner, call)(**kwargs)
        await responder
        return sent[0]

    async def test_class_poll_sends_read(self) -> None:
        """class_poll() issues a READ."""
        request = await self._exchange("class_poll", class_1=True, class_2=False, class_3=False)
        assert request[1] == FunctionCode.READ.value

    async def test_enable_unsolicited_sends_function_20(self) -> None:
        """enable_unsolicited() issues ENABLE_UNSOLICITED (0x14)."""
        request = await self._exchange("enable_unsolicited")
        assert request[1] == FunctionCode.ENABLE_UNSOLICITED.value

    async def test_disable_unsolicited_sends_function_21(self) -> None:
        """disable_unsolicited() issues DISABLE_UNSOLICITED (0x15)."""
        request = await self._exchange("disable_unsolicited")
        assert request[1] == FunctionCode.DISABLE_UNSOLICITED.value


class TestScheduledPolls:
    """`poll()` and the `run_polls()` drive loop.

    Scheduling itself is `PollScheduler`'s job and is tested in
    `test_polling.py`; what matters here is that the runner drives it and marks
    tasks executed, so a due task does not fire forever.
    """

    async def test_poll_marks_task_executed(self) -> None:
        """A scheduled task is marked executed after its burst completes."""
        channel_a, channel_b = create_channel_pair()
        await channel_a.open()
        await channel_b.open()
        runner, _ = make_runner(channel_a)
        await runner.open()
        peer = FakeOutstation(channel_b)

        # interval=0 is a one-shot: due immediately, and not due once executed.
        task = IntegrityPollTask()
        assert task.is_due() is True

        async def respond() -> None:
            await peer.read_fragments(1)
            await peer.send_fragment(analog_response(seq=0, fir=True, fin=True, con=False, index=2, value=8.0))

        responder = asyncio.create_task(respond())
        infos = await runner.poll(task)
        await responder

        assert len(infos) == 1
        assert task.is_due() is False

    async def test_poll_sequence_comes_from_master(self) -> None:
        """A task-built request is numbered from the master's own counter."""
        channel_a, channel_b = create_channel_pair()
        await channel_a.open()
        await channel_b.open()
        runner, _ = make_runner(channel_a)
        await runner.open()
        peer = FakeOutstation(channel_b)

        # Consume a sequence so the poll cannot coincidentally match zero.
        first = runner.master.next_request_sequence()

        sent: list[bytes] = []

        async def respond() -> None:
            sent.extend(await peer.read_fragments(1))
            await peer.send_fragment(analog_response(seq=first + 1, fir=True, fin=True, con=False, index=0, value=1.0))

        responder = asyncio.create_task(respond())
        await runner.poll(IntegrityPollTask())
        await responder

        assert sent[0][0] & 0x0F == (first + 1) % 16

    async def test_run_polls_returns_when_nothing_scheduled(self) -> None:
        """With an empty scheduler the loop returns instead of spinning."""
        channel_a, _ = create_channel_pair()
        await channel_a.open()
        runner, _ = make_runner(channel_a)
        await runner.open()
        runner.master.scheduler.clear()

        await asyncio.wait_for(runner.run_polls(), timeout=1.0)

    async def test_run_polls_stops_on_event(self) -> None:
        """Setting the stop event ends the loop after the current poll."""
        channel_a, channel_b = create_channel_pair()
        await channel_a.open()
        await channel_b.open()
        runner, _ = make_runner(channel_a)
        await runner.open()
        peer = FakeOutstation(channel_b)
        runner.master.scheduler.clear()
        runner.master.scheduler.add_task(IntegrityPollTask())

        stop = asyncio.Event()

        async def respond() -> None:
            await peer.read_fragments(1)
            await peer.send_fragment(analog_response(seq=0, fir=True, fin=True, con=False, index=0, value=1.0))
            stop.set()

        responder = asyncio.create_task(respond())
        await asyncio.wait_for(runner.run_polls(stop=stop), timeout=2.0)
        await responder

        assert stop.is_set()


class TestMalformedTraffic:
    """Input the runner must survive rather than crash on."""

    async def test_unparseable_fragment_is_skipped(self) -> None:
        """Bytes that do not parse as a response are dropped, not raised on."""
        channel_a, channel_b = create_channel_pair()
        await channel_a.open()
        await channel_b.open()
        runner, handler = make_runner(channel_a)
        await runner.open()
        peer = FakeOutstation(channel_b)

        async def respond() -> None:
            await peer.read_fragments(1)
            await peer.send_fragment(b"\xff\xff")  # not a response header
            await peer.send_fragment(analog_response(seq=0, fir=True, fin=True, con=False, index=3, value=6.0))

        responder = asyncio.create_task(respond())
        infos = await runner.integrity_poll()
        await responder

        assert len(infos) == 1
        assert handler.analog_inputs[3] == pytest.approx(6.0)

    async def test_non_user_data_function_code_is_skipped(self) -> None:
        """A frame carrying data under a non-user-data code is not reassembled.

        The function code is only consulted once user data is known to be
        present, because the codes collide numerically across the PRM bit.
        """
        channel_a, channel_b = create_channel_pair()
        await channel_a.open()
        await channel_b.open()
        runner, handler = make_runner(channel_a)
        await runner.open()
        peer = FakeOutstation(channel_b)

        async def respond() -> None:
            await peer.read_fragments(1)
            stray = build_primary_frame(
                destination=MASTER_ADDR,
                source=OUTSTATION_ADDR,
                function_code=LinkFunctionCode.PRI_TEST_LINK_STATE,
                dir_from_master=False,
                user_data=TransportSegment.build(
                    fir=True,
                    fin=True,
                    seq=0,
                    payload=analog_response(seq=0, fir=True, fin=True, con=False, index=8, value=77.0),
                ).to_bytes(),
            )
            await channel_b.write_all(stray.to_bytes())
            await peer.send_fragment(analog_response(seq=0, fir=True, fin=True, con=False, index=1, value=5.0))

        responder = asyncio.create_task(respond())
        await runner.integrity_poll()
        await responder

        assert 8 not in handler.analog_inputs
        assert handler.analog_inputs[1] == pytest.approx(5.0)

    async def test_peer_close_raises_timeout_error(self) -> None:
        """A peer that closes mid-exchange raises rather than hanging."""
        channel_a, channel_b = create_channel_pair()
        await channel_a.open()
        await channel_b.open()
        runner, _ = make_runner(channel_a, response_timeout=2.0)
        await runner.open()
        peer = FakeOutstation(channel_b)

        async def close_after_request() -> None:
            await peer.read_fragments(1)
            await channel_b.close()

        closer = asyncio.create_task(close_after_request())
        with pytest.raises(ResponseTimeoutError):
            await runner.integrity_poll()
        await closer


class TestChannelOwnership:
    """The runner closes only channels it opened itself."""

    async def test_local_address_absent_without_channel(self) -> None:
        """`local_address` is None before a channel exists."""
        handler = RecordingHandler()
        master = Master(
            config=MasterConfig(address=MASTER_ADDR, outstation_address=OUTSTATION_ADDR),
            handler=handler,
        )
        runner = MasterTcpRunner(master=master)

        assert runner.local_address is None
        assert runner.is_open is False


class TestReceiveEdgeCases:
    """Paths reached only by unusual peer behaviour."""

    async def test_listen_skips_solicited_response(self) -> None:
        """A solicited fragment arriving while listening is not mistaken for one.

        An outstation may still be answering an earlier request when the master
        starts listening; that fragment is not an unsolicited report.
        """
        channel_a, channel_b = create_channel_pair()
        await channel_a.open()
        await channel_b.open()
        runner, _ = make_runner(channel_a)
        await runner.open()
        peer = FakeOutstation(channel_b)

        await peer.send_fragment(analog_response(seq=0, fir=True, fin=True, con=False, index=0, value=1.0))

        assert await runner.listen_unsolicited(timeout=0.3) is None

    async def test_closed_channel_raises_runner_error(self) -> None:
        """A closed channel is one condition with one exception type.

        Previously a post-close write surfaced a bare `ChannelClosedError` while
        a post-close read surfaced `ResponseTimeoutError`: two types for one
        condition, and neither the `MasterRunnerError` the docstrings promise.
        `_require_open()` now checks `is_open`, so the guard fires before any
        I/O is attempted.
        """
        channel_a, channel_b = create_channel_pair()
        await channel_a.open()
        await channel_b.open()
        runner, _ = make_runner(channel_a, response_timeout=1.0)
        await runner.open()

        await channel_a.close()

        with pytest.raises(MasterRunnerError, match="closed"):
            await runner.integrity_poll()

    async def test_read_side_close_times_out(self) -> None:
        """A channel closed after the request is sent surfaces as a timeout."""
        channel_a, channel_b = create_channel_pair()
        await channel_a.open()
        await channel_b.open()
        runner, _ = make_runner(channel_a, response_timeout=2.0)
        await runner.open()
        peer = FakeOutstation(channel_b)

        async def close_master_side() -> None:
            await peer.read_fragments(1)
            await channel_a.close()

        closer = asyncio.create_task(close_master_side())
        with pytest.raises(ResponseTimeoutError):
            await runner.integrity_poll()
        await closer

    async def test_run_polls_waits_for_a_future_task(self) -> None:
        """A task not yet due makes the loop wait rather than busy-spin."""
        channel_a, _ = create_channel_pair()
        await channel_a.open()
        runner, _ = make_runner(channel_a)
        await runner.open()
        runner.master.scheduler.clear()

        # An interval task with last_poll_time set to now is not due for an
        # hour, so the loop must sleep on the stop event.
        task = IntegrityPollTask(interval=3600.0)
        task.mark_executed()
        runner.master.scheduler.add_task(task)

        stop = asyncio.Event()

        async def stop_soon() -> None:
            await asyncio.sleep(0.1)
            stop.set()

        stopper = asyncio.create_task(stop_soon())
        await asyncio.wait_for(runner.run_polls(stop=stop), timeout=2.0)
        await stopper


class TestRequestCorrelation:
    """A response must belong to the request that is outstanding.

    Without this, the failure is not primarily an injected frame: it is a poll
    that times out, a next poll that goes out, and the outstation's late answer
    to the first being served as the second's response. Stale analog values
    reach the SOE handler looking current, with no exception anywhere.
    """

    async def test_rejects_first_fragment_with_foreign_sequence(self) -> None:
        """A fragment whose sequence is not the request's is refused."""
        channel_a, channel_b = create_channel_pair()
        await channel_a.open()
        await channel_b.open()
        runner, _ = make_runner(channel_a, response_timeout=1.0)
        await runner.open()
        peer = FakeOutstation(channel_b)

        async def respond() -> None:
            seq = await peer.read_request_seq()
            # A sequence that is emphatically not the one asked for.
            await peer.send_fragment(
                analog_response(seq=(seq + 7) % 16, fir=True, fin=True, con=False, index=7, value=4242.0)
            )

        responder = asyncio.create_task(respond())
        with pytest.raises(MasterRunnerError, match="does not match the request"):
            await runner.integrity_poll()
        await responder

    async def test_late_response_is_not_served_as_the_next_poll(self) -> None:
        """The operational case: a timed-out poll's answer arriving during the next.

        Poll one times out. Poll two goes out. The outstation's late answer to
        poll one then arrives carrying poll one's sequence. It must not be
        returned as poll two's response.
        """
        channel_a, channel_b = create_channel_pair()
        await channel_a.open()
        await channel_b.open()
        runner, handler = make_runner(channel_a, response_timeout=0.3)
        await runner.open()
        peer = FakeOutstation(channel_b)

        first_seq = await asyncio.wait_for(_poll_and_time_out(runner, peer), timeout=5.0)

        # Poll two, answered with poll one's stale sequence and a stale value.
        async def respond_stale() -> None:
            await peer.read_request_seq()
            await peer.send_fragment(
                analog_response(seq=first_seq, fir=True, fin=True, con=False, index=3, value=-999.0)
            )

        responder = asyncio.create_task(respond_stale())
        with pytest.raises(MasterRunnerError, match="does not match the request"):
            await runner.integrity_poll()
        await responder

        assert handler.analog_inputs.get(3) != -999.0, "a stale fragment's values must not reach the handler as current"


async def _poll_and_time_out(runner: MasterTcpRunner, peer: FakeOutstation) -> int:
    """Send one poll, let it time out unanswered, and return its sequence."""
    seq_holder: list[int] = []

    async def capture() -> None:
        seq_holder.append(await peer.read_request_seq())

    capturer = asyncio.create_task(capture())
    with pytest.raises(ResponseTimeoutError):
        await runner.integrity_poll()
    await capturer
    return seq_holder[0]


class TestSourceAddressFilter:
    """User data must come from the configured outstation, not merely be addressed here."""

    async def test_rejects_frame_from_foreign_source(self) -> None:
        """A frame addressed to this master from another outstation is ignored."""
        channel_a, channel_b = create_channel_pair()
        await channel_a.open()
        await channel_b.open()
        runner, handler = make_runner(channel_a, response_timeout=0.5)
        await runner.open()
        peer = FakeOutstation(channel_b)

        async def respond() -> None:
            await peer.read_request_seq()
            # Correctly addressed to the master, but from address 9999.
            await peer.send_fragment_from(
                analog_response(seq=0, fir=True, fin=True, con=False, index=5, value=1234.0),
                source=9999,
            )

        responder = asyncio.create_task(respond())
        with pytest.raises(ResponseTimeoutError):
            await runner.integrity_poll()
        await responder

        assert 5 not in handler.analog_inputs, "values from a foreign source must never reach the handler"

    async def test_accepts_frame_from_configured_source(self) -> None:
        """The filter admits the configured outstation, so it is not simply closed."""
        channel_a, channel_b = create_channel_pair()
        await channel_a.open()
        await channel_b.open()
        runner, handler = make_runner(channel_a)
        await runner.open()
        peer = FakeOutstation(channel_b)

        async def respond() -> None:
            seq = await peer.read_request_seq()
            await peer.send_fragment_from(
                analog_response(seq=seq, fir=True, fin=True, con=False, index=5, value=1234.0),
                source=OUTSTATION_ADDR,
            )

        responder = asyncio.create_task(respond())
        await runner.integrity_poll()
        await responder

        assert handler.analog_inputs[5] == 1234.0


class TestCoalescedRead:
    """Frames sharing one TCP read must all be processed.

    `FrameParser.feed()` materializes every complete frame from a chunk before
    the caller sees the first, so consuming them inside the iteration and
    returning early discards the rest. A kernel that coalesces an ACK with a
    response, or two back-to-back segments, into one read makes this routine.
    """

    async def test_second_fragment_in_same_read_is_not_lost(self) -> None:
        """Two response fragments delivered in a single read both arrive."""
        channel_a, channel_b = create_channel_pair()
        await channel_a.open()
        await channel_b.open()
        runner, handler = make_runner(channel_a, response_timeout=1.0)
        await runner.open()
        peer = FakeOutstation(channel_b)

        async def respond() -> None:
            seq = await peer.read_request_seq()
            # A non-final fragment and an ACK in one write, hence one read. The
            # ACK follows the fragment that completes reassembly, so it is the
            # frame the old code discarded.
            first = peer.frame_fragment(analog_response(seq=seq, fir=True, fin=False, con=True, index=0, value=1.0))
            ack = build_ack(MASTER_ADDR, OUTSTATION_ADDR, False).to_bytes()
            await peer.send_raw(first + ack)
            await peer.read_fragments(1)
            await peer.send_fragment(
                analog_response(seq=(seq + 1) % 16, fir=False, fin=True, con=False, index=1, value=2.0)
            )

        responder = asyncio.create_task(respond())
        infos = await runner.integrity_poll()
        await responder

        assert len(infos) == 2
        assert handler.analog_inputs[0] == 1.0
        assert handler.analog_inputs[1] == 2.0

    async def test_ack_preceding_a_response_in_one_read(self) -> None:
        """An ACK coalesced ahead of a response does not swallow the response."""
        channel_a, channel_b = create_channel_pair()
        await channel_a.open()
        await channel_b.open()
        runner, handler = make_runner(channel_a, response_timeout=1.0)
        await runner.open()
        peer = FakeOutstation(channel_b)

        async def respond() -> None:
            seq = await peer.read_request_seq()
            ack = build_ack(MASTER_ADDR, OUTSTATION_ADDR, False).to_bytes()
            body = peer.frame_fragment(analog_response(seq=seq, fir=True, fin=True, con=False, index=9, value=7.5))
            await peer.send_raw(ack + body)

        responder = asyncio.create_task(respond())
        infos = await runner.integrity_poll()
        await responder

        assert len(infos) == 1
        assert handler.analog_inputs[9] == 7.5


class TestBurstBounds:
    """A burst must end, whether or not the peer sets FIN."""

    async def test_endless_burst_is_abandoned(self) -> None:
        """A peer that increments forever is cut off rather than looped on.

        The mod-16 walk wraps, so sequence continuity alone never terminates:
        the peer below stays perfectly in sequence indefinitely.
        """
        channel_a, channel_b = create_channel_pair()
        await channel_a.open()
        await channel_b.open()
        runner, _ = make_runner(channel_a, response_timeout=10.0)
        await runner.open()
        peer = FakeOutstation(channel_b)

        async def respond_forever() -> None:
            seq = await peer.read_request_seq()
            with contextlib.suppress(Exception):
                while True:
                    await peer.send_fragment(
                        analog_response(seq=seq, fir=True, fin=False, con=True, index=0, value=1.0)
                    )
                    await peer.read_fragments(1)
                    seq = (seq + 1) % 16

        responder = asyncio.create_task(respond_forever())
        try:
            with pytest.raises(MasterRunnerError, match="exceeded"):
                await runner.integrity_poll()
        finally:
            responder.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await responder

    async def test_total_deadline_bounds_a_slow_burst(self) -> None:
        """`response_timeout` bounds the exchange, not merely each fragment.

        A peer answering steadily but slowly would otherwise hold a request open
        for as long as it kept talking, since a per-fragment deadline resets on
        every arrival.
        """
        channel_a, channel_b = create_channel_pair()
        await channel_a.open()
        await channel_b.open()
        runner, _ = make_runner(channel_a, response_timeout=0.6)
        await runner.open()
        peer = FakeOutstation(channel_b)

        async def respond_slowly() -> None:
            seq = await peer.read_request_seq()
            with contextlib.suppress(Exception):
                while True:
                    await peer.send_fragment(
                        analog_response(seq=seq, fir=True, fin=False, con=True, index=0, value=1.0)
                    )
                    await peer.read_fragments(1)
                    await asyncio.sleep(0.15)
                    seq = (seq + 1) % 16

        responder = asyncio.create_task(respond_slowly())
        started = asyncio.get_running_loop().time()
        try:
            with pytest.raises(ResponseTimeoutError):
                await runner.integrity_poll()
        finally:
            responder.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await responder
        elapsed = asyncio.get_running_loop().time() - started
        assert elapsed < 3.0, "the exchange must be bounded by response_timeout, not per fragment"


class TestErrorContainment:
    """`run_polls()` must survive the failures a real link produces."""

    async def test_run_polls_survives_a_timeout(self) -> None:
        """A dropped packet does not end the polling loop.

        One `ResponseTimeoutError` is the normal outcome of a single lost frame.
        Ending the loop on it turns a transient blip into permanent silence with
        `is_open` still reporting `True`.
        """
        channel_a, channel_b = create_channel_pair()
        await channel_a.open()
        await channel_b.open()
        runner, handler = make_runner(channel_a, response_timeout=0.2)
        await runner.open()
        peer = FakeOutstation(channel_b)
        runner.master.scheduler.add_task(IntegrityPollTask())

        stop = asyncio.Event()

        async def ignore_then_answer() -> None:
            # First poll: read it and stay silent, forcing a timeout.
            await peer.read_request_seq()
            # Second poll: answer properly. Reaching here at all proves the loop
            # survived the first failure.
            seq = await peer.read_request_seq(timeout=5.0)
            await peer.send_fragment(analog_response(seq=seq, fir=True, fin=True, con=False, index=2, value=55.0))
            stop.set()

        peer_task = asyncio.create_task(ignore_then_answer())
        poll_task = asyncio.create_task(runner.run_polls(stop=stop))
        try:
            await asyncio.wait_for(peer_task, timeout=10.0)
            await asyncio.wait_for(poll_task, timeout=10.0)
        finally:
            stop.set()
            poll_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await poll_task

        assert handler.analog_inputs.get(2) == 55.0, "the loop must keep polling after a timeout"

    async def test_reassembly_error_is_wrapped_as_link_error(self) -> None:
        """An out-of-order transport segment surfaces under `MasterRunnerError`.

        `ReassemblyError` belongs to the transport package and escaped the
        runner's whole documented contract; a caller cannot be asked to import
        from `dnp3.transport` to catch what a master raises.
        """
        channel_a, channel_b = create_channel_pair()
        await channel_a.open()
        await channel_b.open()
        runner, _ = make_runner(channel_a, response_timeout=1.0)
        await runner.open()
        peer = FakeOutstation(channel_b)

        def frame_segment(segment: TransportSegment) -> bytes:
            return build_unconfirmed_user_data(
                destination=MASTER_ADDR,
                source=OUTSTATION_ADDR,
                dir_from_master=False,
                user_data=segment.to_bytes(),
            ).to_bytes()

        async def respond_out_of_order() -> None:
            await peer.read_request_seq()
            body = analog_response(seq=0, fir=True, fin=True, con=False, index=0, value=1.0)
            # A first segment opens assembly, then a continuation whose sequence
            # is not the expected next one. The reassembler only raises from the
            # ASSEMBLING state: a lone out-of-order segment while IDLE is
            # silently dropped, so both segments are needed to reach the error.
            first = TransportSegment.build(fir=True, fin=False, seq=0, payload=body[:4])
            bad = TransportSegment.build(fir=False, fin=True, seq=9, payload=body[4:])
            await peer.send_raw(frame_segment(first) + frame_segment(bad))

        responder = asyncio.create_task(respond_out_of_order())
        try:
            with pytest.raises(LinkError, match="reassembly"):
                await runner.integrity_poll()
        finally:
            responder.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await responder


class TestLinkFailure:
    """A link that dies mid-exchange must surface under `MasterRunnerError`."""

    async def test_connection_reset_becomes_link_error(self) -> None:
        """A bare `ChannelError` is caught, not just `ChannelClosedError`.

        `ChannelClosedError` and `ChannelTimeoutError` are *siblings* under
        `ChannelError`, and `TcpClientChannel.read` raises the bare parent on
        `OSError`. So ECONNRESET, the most common way a real link dies, arrives
        as `ChannelError` itself and previously escaped the runner entirely.
        """

        class ResettingChannel:
            """Channel whose read fails the way a reset socket does."""

            is_open = True

            async def write_all(self, data: bytes) -> None:
                return None

            async def read(self, size: int) -> bytes:
                raise ChannelError("Read failed: [Errno 104] Connection reset by peer")

            async def close(self) -> None:
                self.is_open = False

        runner, _ = make_runner(ResettingChannel(), response_timeout=1.0)
        await runner.open()

        with pytest.raises(LinkError, match="Link failed"):
            await runner.integrity_poll()


class TestPostCloseLifecycle:
    """State must not survive `close()` into the next connection."""

    async def test_request_after_close_raises_runner_error(self) -> None:
        """The documented guard fires rather than a bare channel error."""
        channel_a, channel_b = create_channel_pair()
        await channel_a.open()
        await channel_b.open()
        runner, _ = make_runner(channel_a)
        await runner.open()
        await runner.close()

        with pytest.raises(MasterRunnerError):
            await runner.integrity_poll()

    async def test_close_clears_protocol_state(self) -> None:
        """Reassembler and parser state do not leak into the next connection."""
        channel_a, channel_b = create_channel_pair()
        await channel_a.open()
        await channel_b.open()
        runner, handler = make_runner(channel_a)
        await runner.open()
        peer = FakeOutstation(channel_b)

        # Leave a partial frame mid-parse, then close.
        await peer.send_raw(b"\x05\x64\x0a")
        with contextlib.suppress(Exception):
            await asyncio.wait_for(runner.integrity_poll(), timeout=0.4)
        await runner.close()

        assert runner._reassembler is None
        assert not runner._pending

        # A fresh open must not prepend the old partial frame's bytes.
        channel_c, channel_d = create_channel_pair()
        await channel_c.open()
        await channel_d.open()
        runner.channel = channel_c
        await runner.open()
        peer2 = FakeOutstation(channel_d)

        async def respond() -> None:
            seq = await peer2.read_request_seq()
            await peer2.send_fragment(analog_response(seq=seq, fir=True, fin=True, con=False, index=4, value=8.0))

        responder = asyncio.create_task(respond())
        infos = await runner.integrity_poll()
        await responder
        assert len(infos) == 1
        assert handler.analog_inputs[4] == 8.0

    async def test_double_open_is_refused(self) -> None:
        """Re-opening would replace the reassembler under an in-flight request."""
        channel_a, _ = create_channel_pair()
        await channel_a.open()
        runner, _ = make_runner(channel_a)
        await runner.open()

        with pytest.raises(MasterRunnerError, match="already open"):
            await runner.open()

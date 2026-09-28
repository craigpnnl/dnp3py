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
import time

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
from dnp3.transport_io.simulator import SimulatorChannel, create_channel_pair

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


class _RaisingCloseChannel(SimulatorChannel):
    """A channel whose close() always raises, to prove cleanup still runs."""

    async def close(self) -> None:
        raise ChannelError("boom")


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

    async def test_final_fragment_with_con_is_confirmed(self) -> None:
        """A FIN fragment that sets CON is confirmed before the exchange returns."""
        channel_a, channel_b = create_channel_pair()
        await channel_a.open()
        await channel_b.open()
        runner, handler = make_runner(channel_a)
        await runner.open()
        peer = FakeOutstation(channel_b)
        seq_holder: list[int] = []

        async def respond() -> None:
            seq = await peer.read_request_seq()
            seq_holder.append(seq)
            await peer.send_fragment(analog_response(seq=seq, fir=True, fin=True, con=True, index=3, value=9.5))

        responder = asyncio.create_task(respond())
        infos = await runner.integrity_poll()
        await responder

        assert [(i.fin, i.con) for i in infos] == [(True, True)]
        assert handler.analog_inputs[3] == pytest.approx(9.5)
        confirms = await peer.read_fragments(1, timeout=0.5)
        assert confirms == [bytes([0xC0 | seq_holder[0], FunctionCode.CONFIRM.value])]


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
        # IEEE 1815-2012 4.2.2.4 Rule 18: same SEQ and UNS as the confirmed fragment.
        assert confirms[0][0] & 0x10, "UNS must be set on an unsolicited CONFIRM"
        assert confirms[0][0] & 0x0F == 2
        assert confirms[0][0] & 0x20 == 0, "a CONFIRM never requests confirmation"

    async def test_listen_does_not_confirm_when_con_clear(self) -> None:
        """An unsolicited response with CON clear is reported but not confirmed."""
        channel_a, channel_b = create_channel_pair()
        await channel_a.open()
        await channel_b.open()
        runner, handler = make_runner(channel_a)
        await runner.open()
        peer = FakeOutstation(channel_b)

        unsolicited = bytearray(analog_response(seq=4, fir=True, fin=True, con=False, index=9, value=43.0))
        unsolicited[0] |= 0x10  # UNS bit
        unsolicited[1] = FunctionCode.UNSOLICITED_RESPONSE.value

        await peer.send_fragment(bytes(unsolicited))
        info = await runner.listen_unsolicited(timeout=2.0)

        assert info is not None
        assert info.is_unsolicited is True
        assert handler.analog_inputs[9] == pytest.approx(43.0)
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(channel_b.read(4096), timeout=0.2)

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

        confirms: list[bytes] = []

        async def respond() -> None:
            await peer.read_fragments(1)
            await peer.send_fragment(analog_response(seq=0, fir=True, fin=False, con=True, index=0, value=1.0))
            # Master's CONFIRM for fragment 1, then its CONFIRM for the
            # unsolicited response; order is not guaranteed.
            await peer.send_fragment(bytes(unsolicited))
            confirms.extend(await peer.read_fragments(2))
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
        # Each CONFIRM mirrors the SEQ and UNS of the fragment it answers.
        assert sorted(confirms) == sorted(
            [
                bytes([0xC0, FunctionCode.CONFIRM.value]),
                bytes([0xD6, FunctionCode.CONFIRM.value]),
            ]
        )


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
    """`poll()` runs one scheduler task.

    Scheduling itself is `PollScheduler`'s job and is tested in
    `test_polling.py`; what matters here is that the runner marks tasks
    executed, so a due task does not fire forever.
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

    async def test_peer_close_raises_link_error(self) -> None:
        """A peer that closes mid-exchange raises LinkError and closes the runner."""
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
        with pytest.raises(LinkError, match="closed"):
            await runner.integrity_poll()
        await closer
        assert runner.is_open is False


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

    async def test_listen_does_not_deliver_solicited_values(self, caplog: pytest.LogCaptureFixture) -> None:
        """A solicited fragment's values never reach the handler while listening.

        Only its header is read; the drop is logged, and a later unsolicited
        report on the same listen is still delivered.
        """
        channel_a, channel_b = create_channel_pair()
        await channel_a.open()
        await channel_b.open()
        runner, handler = make_runner(channel_a)
        await runner.open()
        peer = FakeOutstation(channel_b)

        unsolicited = bytearray(analog_response(seq=5, fir=True, fin=True, con=False, index=9, value=42.0))
        unsolicited[0] |= 0x10  # UNS bit
        unsolicited[1] = FunctionCode.UNSOLICITED_RESPONSE.value
        await peer.send_fragment(analog_response(seq=3, fir=True, fin=True, con=False, index=0, value=-777.0))
        await peer.send_fragment(bytes(unsolicited))

        with caplog.at_level("WARNING", logger="dnp3.master.tcp_runner"):
            info = await runner.listen_unsolicited(timeout=1.0)

        assert 0 not in handler.analog_inputs
        assert info is not None
        assert info.is_unsolicited is True
        assert info.sequence == 5
        assert handler.analog_inputs == {9: pytest.approx(42.0)}
        dropped = [r for r in caplog.records if "solicited" in r.getMessage() and "sequence 3" in r.getMessage()]
        assert len(dropped) == 1
        assert dropped[0].levelname == "WARNING"

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

    async def test_read_side_close_raises_link_error(self) -> None:
        """A channel closed after the request is sent is a link failure.

        Per `_read_fragment_bytes`'s own contract, `ResponseTimeoutError` is
        for a deadline passing; a channel known to be closed is a link
        failure, the same as the peer-EOF case in `TestPeerEof`.
        """
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
        with pytest.raises(LinkError, match="not open"):
            await runner.integrity_poll()
        await closer


class TestRequestCorrelation:
    """A response must belong to the request that is outstanding.

    Without this, the failure is not primarily an injected frame: it is a poll
    that times out, a next poll that goes out, and the outstation's late answer
    to the first being served as the second's response. Stale analog values
    reach the SOE handler looking current, with no exception anywhere.
    """

    async def test_rejects_first_fragment_with_foreign_sequence(self) -> None:
        """A fragment whose sequence is not the request's is dropped, not served."""
        channel_a, channel_b = create_channel_pair()
        await channel_a.open()
        await channel_b.open()
        runner, handler = make_runner(channel_a, response_timeout=1.0)
        await runner.open()
        peer = FakeOutstation(channel_b)

        async def respond() -> None:
            seq = await peer.read_request_seq()
            # A sequence that is emphatically not the one asked for.
            await peer.send_fragment(
                analog_response(seq=(seq + 7) % 16, fir=True, fin=True, con=False, index=7, value=4242.0)
            )

        responder = asyncio.create_task(respond())
        with pytest.raises(ResponseTimeoutError):
            await runner.integrity_poll()
        await responder

        assert 7 not in handler.analog_inputs

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
        with pytest.raises(ResponseTimeoutError):
            await runner.integrity_poll()
        await responder

        assert handler.analog_inputs.get(3) != -999.0, "a stale fragment's values must not reach the handler as current"

    async def test_late_answer_does_not_desynchronize_later_polls(self, caplog: pytest.LogCaptureFixture) -> None:
        """One timed-out poll must not make every later poll fail.

        The late answer to poll one arrives ahead of poll two's own answer. It
        is dropped unparsed and unconfirmed, and each later poll still receives
        and delivers its own values.
        """
        channel_a, channel_b = create_channel_pair()
        await channel_a.open()
        await channel_b.open()
        runner, handler = make_runner(channel_a, response_timeout=0.3)
        await runner.open()
        peer = FakeOutstation(channel_b)
        function_codes: list[int] = []

        first_seq = await asyncio.wait_for(_poll_and_time_out(runner, peer), timeout=5.0)
        late_answer = analog_response(seq=first_seq, fir=True, fin=True, con=True, index=3, value=-999.0)

        async def answer(poll_number: int) -> None:
            request = (await peer.read_fragments(1))[0]
            function_codes.append(request[1])
            if poll_number == 0:
                await peer.send_fragment(late_answer)
            seq = request[0] & 0x0F
            await peer.send_fragment(
                analog_response(
                    seq=seq, fir=True, fin=True, con=False, index=10 + poll_number, value=100.0 + poll_number
                )
            )

        polls = 4
        with caplog.at_level("WARNING", logger="dnp3.master.tcp_runner"):
            for poll_number in range(polls):
                responder = asyncio.create_task(answer(poll_number))
                infos = await runner.integrity_poll()
                await responder
                assert len(infos) == 1
                assert infos[0].sequence == (first_seq + 1 + poll_number) % 16
                assert handler.analog_inputs[10 + poll_number] == pytest.approx(100.0 + poll_number)

        assert 3 not in handler.analog_inputs, "the late answer's values must not be delivered"
        assert function_codes == [FunctionCode.READ.value] * polls, "the dropped fragment must not be confirmed"
        dropped = [r for r in caplog.records if "Dropping response fragment" in r.getMessage()]
        assert len(dropped) == 1
        assert dropped[0].levelname == "WARNING"
        assert f"sequence {first_seq}," in dropped[0].getMessage()
        assert f"expected {(first_seq + 1) % 16}" in dropped[0].getMessage()


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
    """Failures a real link produces surface under `MasterRunnerError`."""

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


class TestPeerEof:
    """A peer that closes the connection is a dead link, not a quiet one."""

    class EofChannel:
        """Channel whose reads report EOF, as a socket does once the peer closes."""

        is_open = True

        def __init__(self) -> None:
            self.reads = 0

        async def write_all(self, data: bytes) -> None:
            return None

        async def read(self, size: int) -> bytes:
            self.reads += 1
            return b""

        async def close(self) -> None:
            self.is_open = False

    async def test_listen_raises_link_error_on_eof(self) -> None:
        """`listen_unsolicited` raises promptly instead of returning None forever."""
        channel = self.EofChannel()
        runner, _ = make_runner(channel, response_timeout=5.0)
        await runner.open()

        with pytest.raises(LinkError, match="closed"):
            await asyncio.wait_for(runner.listen_unsolicited(timeout=5.0), timeout=1.0)

        assert runner.is_open is False
        assert channel.reads == 1
        with pytest.raises(MasterRunnerError):
            await runner.listen_unsolicited(timeout=0.1)

    async def test_request_raises_link_error_on_eof(self) -> None:
        """A poll whose read hits EOF raises LinkError, not ResponseTimeoutError."""
        runner, _ = make_runner(self.EofChannel(), response_timeout=5.0)
        await runner.open()

        with pytest.raises(LinkError, match="closed"):
            await asyncio.wait_for(runner.integrity_poll(), timeout=1.0)

        assert runner.is_open is False


class TestWriteFailure:
    """Writes fail inside the runner's error hierarchy and inside its deadline."""

    class FailingWriteChannel:
        """Channel whose writes fail the way a reset socket does."""

        is_open = True

        async def write_all(self, data: bytes) -> None:
            raise ChannelError("Write failed: Connection lost")

        async def read(self, size: int) -> bytes:
            await asyncio.Event().wait()
            return b""

        async def close(self) -> None:
            self.is_open = False

    class StalledWriteChannel:
        """Channel whose writes never complete, as when the peer stops reading."""

        is_open = True

        async def write_all(self, data: bytes) -> None:
            await asyncio.Event().wait()

        async def read(self, size: int) -> bytes:
            await asyncio.Event().wait()
            return b""

        async def close(self) -> None:
            self.is_open = False

    async def test_write_error_from_request_is_link_error(self) -> None:
        """A failed write surfaces from `request()` as LinkError, with its cause."""
        runner, _ = make_runner(self.FailingWriteChannel(), response_timeout=1.0)
        await runner.open()

        with pytest.raises(LinkError, match="Write failed") as raised:
            await asyncio.wait_for(runner.integrity_poll(), timeout=2.0)
        assert isinstance(raised.value.__cause__, ChannelError)

    async def test_write_error_from_poll_is_link_error(self) -> None:
        """A failed write surfaces from `poll()` as LinkError, and the task stays due."""
        runner, _ = make_runner(self.FailingWriteChannel(), response_timeout=1.0)
        await runner.open()
        task = IntegrityPollTask()

        with pytest.raises(LinkError, match="Write failed"):
            await asyncio.wait_for(runner.poll(task), timeout=2.0)
        assert task.is_due() is True

    async def test_stalled_write_ends_at_the_deadline(self) -> None:
        """A write that never completes is abandoned at the exchange deadline."""
        runner, _ = make_runner(self.StalledWriteChannel(), response_timeout=0.3)
        await runner.open()
        loop = asyncio.get_running_loop()

        started = loop.time()
        with pytest.raises(LinkError, match="deadline"):
            await asyncio.wait_for(runner.integrity_poll(), timeout=3.0)
        elapsed = loop.time() - started

        assert 0.25 <= elapsed < 1.0


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


class TestCloseOverStalledSocket:
    """Every close the runner takes finishes when the peer has stopped reading.

    These need a real socket: the hang is in the TCP transport's graceful close,
    which waits for a send buffer the stalled peer never drains.
    """

    # More than loopback socket buffers hold, so bytes stay queued in the transport.
    STUFFING = b"\x00" * (32 * 1024 * 1024)
    # TcpConfig.close_timeout plus scheduling slack.
    CLOSE_BOUND = 2.0

    @staticmethod
    async def _stalled_runner(
        response_timeout: float,
    ) -> tuple[MasterTcpRunner, asyncio.Server, list[asyncio.StreamWriter]]:
        """Open a runner on a socket whose peer never reads, with its send path jammed."""
        writers: list[asyncio.StreamWriter] = []

        async def handler(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
            writers.append(writer)

        server = await asyncio.start_server(handler, host="127.0.0.1", port=0)
        master = Master(
            config=MasterConfig(address=MASTER_ADDR, outstation_address=OUTSTATION_ADDR),
            handler=RecordingHandler(),
        )
        runner = MasterTcpRunner(
            master=master,
            host="127.0.0.1",
            port=server.sockets[0].getsockname()[1],
            link_reset=LinkResetPolicy.NEVER,
            response_timeout=response_timeout,
        )
        await runner.open()
        assert runner.channel is not None
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(runner.channel.write_all(TestCloseOverStalledSocket.STUFFING), timeout=0.3)
        for _ in range(100):
            if writers:
                break
            await asyncio.sleep(0.01)
        assert writers, "server never accepted the connection"
        return runner, server, writers

    @staticmethod
    async def _stop(server: asyncio.Server, writers: list[asyncio.StreamWriter]) -> None:
        for writer in writers:
            writer.transport.abort()
        server.close()
        await server.wait_closed()

    async def test_peer_eof_close_is_bounded(self) -> None:
        """EOF from a peer that stopped reading raises LinkError within the bound."""
        runner, server, writers = await self._stalled_runner(response_timeout=5.0)
        try:
            writers[0].write_eof()
            loop = asyncio.get_running_loop()
            started = loop.time()
            with pytest.raises(LinkError, match="Peer closed the connection"):
                await asyncio.wait_for(runner.listen_unsolicited(timeout=5.0), timeout=8.0)
            elapsed = loop.time() - started

            assert elapsed < self.CLOSE_BOUND
            assert runner.is_open is False
            assert runner.channel is None
        finally:
            await self._stop(server, writers)

    async def test_close_after_write_timeout_is_bounded(self) -> None:
        """A caller's close() after a write timed out returns within the bound."""
        runner, server, writers = await self._stalled_runner(response_timeout=0.3)
        try:
            with pytest.raises(LinkError, match="did not complete before the deadline"):
                await asyncio.wait_for(runner.integrity_poll(), timeout=3.0)

            loop = asyncio.get_running_loop()
            started = loop.time()
            await asyncio.wait_for(runner.close(), timeout=8.0)
            elapsed = loop.time() - started

            assert elapsed < self.CLOSE_BOUND
            assert runner.is_open is False
            assert runner.channel is None
        finally:
            await self._stop(server, writers)


class TestFailedOpen:
    """A failed open() leaves nothing half-open and can be retried."""

    async def test_failed_link_reset_leaves_runner_closed_and_reopenable(self) -> None:
        """A reset that fails to write closes the runner; a later open() succeeds."""
        channel_a, channel_b = create_channel_pair()
        await channel_a.open()
        await channel_b.open()
        await channel_b.close()  # no peer left, so the reset write fails
        runner, _ = make_runner(channel_a, link_reset=LinkResetPolicy.ON_OPEN)

        with pytest.raises(LinkError, match="Link failed while writing") as raised:
            await runner.open()

        assert isinstance(raised.value.__cause__, ChannelError)
        assert runner.is_open is False
        assert runner._reassembler is None
        assert channel_a.is_open, "an injected channel belongs to its owner"
        assert runner.channel is channel_a, "an injected channel is not dropped on a failed open"

        channel_c, channel_d = create_channel_pair()
        await channel_c.open()
        await channel_d.open()
        runner.channel = channel_c
        await runner.open()

        assert runner.is_open is True
        frames = list(FrameParser().feed(await asyncio.wait_for(channel_d.read(4096), timeout=1.0)))
        assert [f.header.control.function_code for f in frames] == [LinkFunctionCode.PRI_RESET_LINK_STATE.value]

    async def test_failed_open_clears_state_even_when_channel_close_raises(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """close() raising during a failed open() still clears the runner's
        state: cleanup runs from a `finally`, not after an unguarded call.
        """

        def factory(config: object) -> SimulatorChannel:
            return _RaisingCloseChannel()  # no peer, so the link reset write fails

        monkeypatch.setattr("dnp3.master.tcp_runner.TcpClientChannel", factory)
        master = Master(
            config=MasterConfig(address=MASTER_ADDR, outstation_address=OUTSTATION_ADDR),
            handler=RecordingHandler(),
        )
        runner = MasterTcpRunner(master=master, link_reset=LinkResetPolicy.ON_OPEN, response_timeout=1.0)

        with pytest.raises(ChannelError, match="boom"):
            await runner.open()

        assert runner.channel is None
        assert runner._owns_channel is False
        assert runner._reassembler is None

    async def test_failed_open_closes_an_owned_channel(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A channel the runner created is closed and dropped when open() fails."""
        created: list[SimulatorChannel] = []
        peers: list[SimulatorChannel] = []

        def factory(config: object) -> SimulatorChannel:
            if not created:
                channel = SimulatorChannel()  # no peer, so the reset write fails
            else:
                channel, peer = create_channel_pair()
                peers.append(peer)
            created.append(channel)
            return channel

        monkeypatch.setattr("dnp3.master.tcp_runner.TcpClientChannel", factory)
        master = Master(
            config=MasterConfig(address=MASTER_ADDR, outstation_address=OUTSTATION_ADDR),
            handler=RecordingHandler(),
        )
        runner = MasterTcpRunner(master=master, link_reset=LinkResetPolicy.ON_OPEN, response_timeout=1.0)

        with pytest.raises(LinkError, match="No peer connected"):
            await runner.open()

        assert created[0].is_open is False
        assert runner.channel is None
        assert runner.is_open is False

        await runner.open()

        assert len(created) == 2
        assert runner.channel is created[1]
        assert runner.is_open is True
        await peers[0].open()
        frames = list(FrameParser().feed(await asyncio.wait_for(peers[0].read(4096), timeout=1.0)))
        assert [f.header.control.function_code for f in frames] == [LinkFunctionCode.PRI_RESET_LINK_STATE.value]


class TestSpentDeadline:
    """A spent deadline stops new work but never strands a CONFIRM already owed.

    Rule: a fragment is not taken for processing once the deadline has passed,
    so its values are not delivered and it stays queued for a later call; a
    CONFIRM owed for values already delivered is written with a minimum budget
    rather than with the time left, which may be none.
    """

    @staticmethod
    def _unsolicited(seq: int, index: int, value: float) -> bytes:
        data = bytearray(analog_response(seq=seq, fir=True, fin=True, con=True, index=index, value=value))
        data[0] |= 0x10  # UNS bit
        data[1] = FunctionCode.UNSOLICITED_RESPONSE.value
        return bytes(data)

    async def test_queued_fragment_is_not_delivered_on_a_spent_deadline(self) -> None:
        """listen_unsolicited(timeout=0) delivers nothing and leaves the fragment queued."""
        channel_a, channel_b = create_channel_pair()
        await channel_a.open()
        await channel_b.open()
        runner, handler = make_runner(channel_a)
        await runner.open()
        peer = FakeOutstation(channel_b)

        # Both frames in one read: the second waits in the runner's frame queue.
        await peer.send_raw(
            peer.frame_fragment(self._unsolicited(4, index=1, value=10.0))
            + peer.frame_fragment(self._unsolicited(5, index=2, value=20.0))
        )
        first = await runner.listen_unsolicited(timeout=1.0)
        assert first is not None
        assert first.sequence == 4
        assert await peer.read_fragments(1) == [bytes([0xD4, FunctionCode.CONFIRM.value])]

        assert await runner.listen_unsolicited(timeout=0) is None
        assert 2 not in handler.analog_inputs
        assert runner.is_open is True
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(channel_b.read(4096), timeout=0.2)

        second = await runner.listen_unsolicited(timeout=1.0)
        assert second is not None
        assert second.sequence == 5
        assert handler.analog_inputs == {1: pytest.approx(10.0), 2: pytest.approx(20.0)}
        assert await peer.read_fragments(1) == [bytes([0xD5, FunctionCode.CONFIRM.value])]

    async def test_confirm_owed_after_the_deadline_is_still_written(self) -> None:
        """Values delivered as the deadline passes are confirmed; the next fragment is not taken."""
        channel_a, channel_b = create_channel_pair()
        await channel_a.open()
        await channel_b.open()
        runner, handler = make_runner(channel_a, response_timeout=0.3)
        await runner.open()
        peer = FakeOutstation(channel_b)

        delivered = handler.on_analog_input

        def slow_handler(values: list[object], info: ResponseInfo) -> None:
            delivered(values, info)
            time.sleep(0.4)  # outlasts response_timeout while the fragment is processed

        handler.on_analog_input = slow_handler  # type: ignore[method-assign]
        confirms: list[bytes] = []

        async def respond() -> None:
            seq = await peer.read_request_seq()
            await peer.send_raw(
                peer.frame_fragment(analog_response(seq=seq, fir=True, fin=False, con=True, index=0, value=1.0))
                + peer.frame_fragment(
                    analog_response(seq=(seq + 1) % 16, fir=False, fin=True, con=False, index=1, value=2.0)
                )
            )
            confirms.extend(await peer.read_fragments(1))
            seq_holder.append(seq)

        seq_holder: list[int] = []
        responder = asyncio.create_task(respond())
        with pytest.raises(ResponseTimeoutError, match="Timed out"):
            await runner.integrity_poll()
        await responder

        assert handler.analog_inputs == {0: pytest.approx(1.0)}
        assert confirms == [bytes([0xC0 | seq_holder[0], FunctionCode.CONFIRM.value])]
        assert runner.is_open is True


# g30v1, count 3, holding one object: the parser stops at this block (IEEE 1815-2012 4.2.2.7).
OVER_DECLARED_G30V1 = bytes([0x1E, 0x01, 0x17, 0x03, 0x05, 0x01, 0x64, 0x00, 0x00, 0x00])
# g30v1, count 1, index 7, value 200: never reached behind the block above.
G30V1_INDEX_7 = bytes([0x1E, 0x01, 0x17, 0x01, 0x07, 0x01, 0xC8, 0x00, 0x00, 0x00])


class TestTruncatedFragments:
    """A fragment the parser cannot read to the end is confirmed as before, and not silent."""

    async def test_truncated_unsolicited_during_request_is_logged_and_confirmed(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Its ResponseInfo is not returned by request() and it delivers no value, so the log is its only trace."""
        channel_a, channel_b = create_channel_pair()
        await channel_a.open()
        await channel_b.open()
        runner, handler = make_runner(channel_a)
        await runner.open()
        peer = FakeOutstation(channel_b)
        # FIR, FIN, CON, UNS, seq 6.
        unsolicited = (
            bytes([0xF6, FunctionCode.UNSOLICITED_RESPONSE.value, 0x00, 0x00]) + OVER_DECLARED_G30V1 + G30V1_INDEX_7
        )
        confirms: list[bytes] = []

        async def respond() -> None:
            seq = await peer.read_request_seq()
            await peer.send_fragment(unsolicited)
            confirms.extend(await peer.read_fragments(1))
            await peer.send_fragment(analog_response(seq=seq, fir=True, fin=True, con=False, index=0, value=1.0))

        with caplog.at_level("WARNING", logger="dnp3.master.master"):
            responder = asyncio.create_task(respond())
            infos = await runner.integrity_poll()
            await responder

        assert [(i.is_unsolicited, i.truncation) for i in infos] == [(False, None)]
        assert handler.analog_inputs == {0: pytest.approx(1.0)}
        assert confirms == [bytes([0xD6, FunctionCode.CONFIRM.value])]
        warnings = [r for r in caplog.records if r.name == "dnp3.master.master" and r.levelname == "WARNING"]
        assert len(warnings) == 1
        assert "data_shorter_than_declared" in warnings[0].getMessage()
        assert "group 30" in warnings[0].getMessage()

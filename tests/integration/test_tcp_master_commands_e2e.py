"""End-to-end: `MasterTcpRunner` controls against a live `Outstation` over TCP.

`test_commands.py` proves the request and echo shapes between `Master` and
`Outstation` in memory; these tests drive the runner's `direct_operate()` and
`select_and_operate()` through the shipped stack over a real socket, with a
command handler that accepts some controls and refuses others, so the statuses
the runner returns are the outstation's own.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

import pytest

from dnp3.core.enums import CommandStatus, ControlCode
from dnp3.database import AnalogOutputConfig, BinaryOutputConfig, Database
from dnp3.master import DefaultSOEHandler, Master, MasterConfig, MasterTcpRunner
from dnp3.outstation import CommandResult, DefaultCommandHandler, Outstation, OutstationConfig, OutstationTcpRunner

MASTER_ADDR = 3
OUTSTATION_ADDR = 1
BIND_TIMEOUT = 5.0
EXCHANGE_TIMEOUT = 5.0
ANALOG_LIMIT = 1000


class PartlyAcceptingHandler(DefaultCommandHandler):
    """Accepts binary output 0 only, and analog values below ANALOG_LIMIT."""

    def __init__(self) -> None:
        self.operated: list[tuple[str, int, float | ControlCode]] = []

    def _binary(self, index: int) -> CommandResult:
        return CommandResult.success() if index == 0 else CommandResult.not_supported()

    def select_binary_output(
        self, index: int, code: ControlCode, count: int, on_time: int, off_time: int
    ) -> CommandResult:
        return self._binary(index)

    def operate_binary_output(
        self, index: int, code: ControlCode, count: int, on_time: int, off_time: int, select_sequence: int
    ) -> CommandResult:
        self.operated.append(("binary", index, code))
        return self._binary(index)

    def direct_operate_binary_output(
        self, index: int, code: ControlCode, count: int, on_time: int, off_time: int
    ) -> CommandResult:
        self.operated.append(("binary", index, code))
        return self._binary(index)

    def direct_operate_analog_output(self, index: int, value: float) -> CommandResult:
        self.operated.append(("analog", index, value))
        return CommandResult.success() if value < ANALOG_LIMIT else CommandResult.out_of_range()


@pytest.fixture
async def stack() -> AsyncIterator[tuple[MasterTcpRunner, Master, PartlyAcceptingHandler]]:
    """An outstation serving on 127.0.0.1 and an open runner connected to it."""
    database = Database()
    database.add_binary_output(0, BinaryOutputConfig())
    database.add_binary_output(1, BinaryOutputConfig())
    database.add_analog_output(0, AnalogOutputConfig())
    handler = PartlyAcceptingHandler()
    outstation = Outstation(
        config=OutstationConfig(address=OUTSTATION_ADDR, master_address=MASTER_ADDR),
        database=database,
        handler=handler,
    )
    os_runner = OutstationTcpRunner(outstation=outstation, host="127.0.0.1", port=0)
    serve_task = asyncio.create_task(os_runner.run())
    loop = asyncio.get_running_loop()
    deadline = loop.time() + BIND_TIMEOUT
    while not (os_runner.is_running and os_runner.local_address is not None):
        if loop.time() > deadline:
            pytest.fail("outstation runner did not bind in time")
        await asyncio.sleep(0.02)
    host, port = os_runner.local_address

    master = Master(
        config=MasterConfig(address=MASTER_ADDR, outstation_address=OUTSTATION_ADDR), handler=DefaultSOEHandler()
    )
    runner = MasterTcpRunner(master=master, host=host, port=port, response_timeout=EXCHANGE_TIMEOUT)
    await runner.open()
    try:
        yield runner, master, handler
    finally:
        await runner.close()
        await os_runner.stop()
        serve_task.cancel()
        with pytest.raises((asyncio.CancelledError, TimeoutError)):
            await asyncio.wait_for(serve_task, timeout=EXCHANGE_TIMEOUT)


class TestDirectOperateOverTcp:
    async def test_statuses_are_the_outstations(
        self, stack: tuple[MasterTcpRunner, Master, PartlyAcceptingHandler]
    ) -> None:
        runner, master, handler = stack
        task = master.command_builder().latch_on(0).latch_on(1).add_analog(0, 5000).build_direct_operate()

        responses = await asyncio.wait_for(runner.direct_operate(task), timeout=EXCHANGE_TIMEOUT)

        assert [(r.group, r.index, r.status) for r in responses] == [
            (12, 0, CommandStatus.SUCCESS),
            (12, 1, CommandStatus.NOT_SUPPORTED),
            (41, 0, CommandStatus.OUT_OF_RANGE),
        ]
        assert ("binary", 0, ControlCode.LATCH_ON) in handler.operated
        soe = master.handler
        assert isinstance(soe, DefaultSOEHandler)
        assert soe.get_command_response(41, 0) is not None


class TestSelectAndOperateOverTcp:
    async def test_accepted_select_is_operated(
        self, stack: tuple[MasterTcpRunner, Master, PartlyAcceptingHandler]
    ) -> None:
        runner, master, handler = stack
        select = master.command_builder().latch_off(0).build_select()

        responses = await asyncio.wait_for(runner.select_and_operate(select), timeout=EXCHANGE_TIMEOUT)

        assert [(r.index, r.status) for r in responses] == [(0, CommandStatus.SUCCESS)]
        assert handler.operated == [("binary", 0, ControlCode.LATCH_OFF)]

    async def test_refused_select_is_not_operated(
        self, stack: tuple[MasterTcpRunner, Master, PartlyAcceptingHandler]
    ) -> None:
        runner, master, handler = stack
        select = master.command_builder().latch_on(0).latch_on(1).build_select()

        responses = await asyncio.wait_for(runner.select_and_operate(select), timeout=EXCHANGE_TIMEOUT)

        assert [r.status for r in responses] == [CommandStatus.SUCCESS, CommandStatus.NOT_SUPPORTED]
        assert handler.operated == []  # nothing reached an operate method

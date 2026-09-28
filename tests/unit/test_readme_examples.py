"""README Quick Start examples run as written and complete their round trip.

The Outstation and Master blocks are extracted verbatim from README.md at
test time, with the hard-coded port 20000 swapped for a bound one: the
executed code is the README's own text, not a hand-maintained copy of it, so
a change that breaks either block fails this test.
"""

import asyncio
from collections.abc import Callable, Coroutine
from pathlib import Path
from typing import Any, cast

import pytest

from dnp3.outstation import OutstationTcpRunner

BIND_TIMEOUT = 5.0
POLL_TIMEOUT = 5.0
README_FIXED_PORT = "20000"

README_PATH = Path(__file__).resolve().parents[2] / "README.md"


def _extract_code_block(readme_text: str, heading: str) -> str:
    """Return the fenced python block that follows `heading` in README.md."""
    heading_index = readme_text.index(heading)
    fence_start = readme_text.index("```python\n", heading_index) + len("```python\n")
    fence_end = readme_text.index("```", fence_start)
    return readme_text[fence_start:fence_end]


def _load_main(source: str, port: int) -> Callable[[], Coroutine[Any, Any, None]]:
    """Load a README block's `main` with its fixed port swapped for `port`.

    The block's own trailing `asyncio.run(main())` call is dropped: it would
    try to start a second event loop inside the one this test already runs
    on, so the caller schedules the returned `main` instead.
    """
    patched = source.replace(f"port={README_FIXED_PORT}", f"port={port}")
    patched = patched.rsplit("asyncio.run(main())", 1)[0]
    namespace: dict[str, object] = {}
    exec(compile(patched, "<readme block>", "exec"), namespace)
    # `main` is loaded at runtime from exec'd README text; there is no static
    # type for it, so this cast is the one boundary crossing in this file.
    return cast(Callable[[], Coroutine[Any, Any, None]], namespace["main"])


class _RunnerRegistry:
    """Records the OutstationTcpRunner a README block constructs.

    The Outstation block keeps its `runner` in a local variable and never
    returns it, so this recovers the instance by standing in for the name
    the block imports, rather than by editing the block's source.
    """

    def __init__(self) -> None:
        self.runners: list[OutstationTcpRunner] = []

    def __call__(self, *args: Any, **kwargs: Any) -> OutstationTcpRunner:
        # Stands in for OutstationTcpRunner's constructor without repeating
        # its signature, so a future field there cannot drift out of sync.
        runner = OutstationTcpRunner(*args, **kwargs)
        self.runners.append(runner)
        return runner


async def _await_bind(serve_task: "asyncio.Task[None]", registry: _RunnerRegistry) -> tuple[str, int]:
    """Wait for the registered runner to bind, surfacing a run() failure at once."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + BIND_TIMEOUT
    while loop.time() < deadline:
        if serve_task.done():
            serve_task.result()
            pytest.fail("outstation runner exited before binding")
        if registry.runners:
            runner = registry.runners[0]
            if runner.is_running and runner.local_address is not None:
                return runner.local_address
        await asyncio.sleep(0.01)
    pytest.fail("outstation runner did not bind in time")


class TestReadmeOutstationQuickStart:
    """The README's Outstation (Server) block, run as written."""

    async def test_binds_and_shuts_down_only_on_cancellation(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The block binds the configured host, and stops only on cancellation."""
        registry = _RunnerRegistry()
        monkeypatch.setattr("dnp3.outstation.OutstationTcpRunner", registry)

        source = _extract_code_block(README_PATH.read_text(), "### Outstation (Server)")
        main = _load_main(source, port=0)
        serve_task: asyncio.Task[None] = asyncio.create_task(main())

        try:
            host, port = await _await_bind(serve_task, registry)
            assert host == "127.0.0.1"
            assert port > 0
        finally:
            serve_task.cancel()
            with pytest.raises((asyncio.CancelledError, TimeoutError)):
                await asyncio.wait_for(serve_task, timeout=POLL_TIMEOUT)


class TestReadmeMasterQuickStart:
    """The README's Master (Client) block, against the Outstation block's server."""

    async def test_integrity_poll_prints_the_configured_values(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """An integrity poll prints exactly the values the outstation block set."""
        registry = _RunnerRegistry()
        monkeypatch.setattr("dnp3.outstation.OutstationTcpRunner", registry)

        readme_text = README_PATH.read_text()
        outstation_main = _load_main(_extract_code_block(readme_text, "### Outstation (Server)"), port=0)
        serve_task: asyncio.Task[None] = asyncio.create_task(outstation_main())

        try:
            _host, port = await _await_bind(serve_task, registry)

            master_main = _load_main(_extract_code_block(readme_text, "### Master (Client)"), port=port)
            await asyncio.wait_for(master_main(), timeout=POLL_TIMEOUT)

            assert capsys.readouterr().out == "True\n42.0\n"
        finally:
            serve_task.cancel()
            with pytest.raises((asyncio.CancelledError, TimeoutError)):
                await asyncio.wait_for(serve_task, timeout=POLL_TIMEOUT)

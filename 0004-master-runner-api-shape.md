# ADR-0004: MasterTcpRunner ships a narrow API, and the shape is chosen on reversibility

Date: 2026-08-27
Status: Proposed. This records a recommendation and awaits maintainer approval; nothing below is settled until this line reads Accepted.

## Context

`MasterTcpRunner` (`src/dnp3/master/tcp_runner.py`, added by PR [#63](https://github.com/craigpnnl/dnp3py/pull/63) against issue [#57](https://github.com/craigpnnl/dnp3py/issues/57)) is the master role's counterpart to `OutstationTcpRunner`. `Master` builds requests and parses responses but owns no I/O; `TcpClientChannel` moves bytes but knows no DNP3. The runner is the layer between them: data link framing, transport segmentation and reassembly, link reset, and the multi-fragment application CONFIRM handshake. It is the first driver the master role has ever had, so everything it exposes is new public surface with no prior art in this package to constrain it.

Four questions were raised in review of that PR. They arrived together because they are all the same question wearing different clothes: what does this class promise callers on the day it merges?

1. Should `link_reset` be a `LinkResetPolicy` enum or a plain `bool`?
2. Should `LinkError` live in the runner module under `MasterRunnerError`, or in `dnp3.core.exceptions` with the rest of the library's exception taxonomy?
3. Should `run_polls()`, an unsupervised scheduling loop, ship with the class?
4. Should using a closed channel raise uniformly, or should the never-opened case be distinguished from the link-since-died case?

The constraint that decides three of the four is that dnp3py is a published package on PyPI and at least one downstream consumer pins a version rather than tracking the tip. A pinning consumer is exactly why the constraint bites: they will upgrade eventually, deliberately, and read a changelog when they do. What they cannot absorb cheaply is a constructor signature or an exception base that changed underneath the pin.

## Reversibility is the deciding axis, not taste

For each question, ask which direction of the eventual correction is cheap.

Adding an enum member, adding a base class to an exception, adding a method, and splitting one exception type into two subclasses of a type already raised are all additive. A pinner who upgrades across any of them sees new names, catches at least as much as before, and keeps working.

Removing a public method, converting a parameter's type, and reparenting an exception onto a base that no longer includes what callers catch are subtractive. A pinner who upgrades across one of those gets a failure at import, at construction, or, worst of the three, at an `except` clause that silently stops matching and turns a handled error into an unhandled one.

Where the two directions cost the same, the question is genuinely about taste and should be settled on readability. Where they do not, reversibility settles it, and it settles against the option that is expensive to undo even when that option reads better today. Three of the four questions below are asymmetric in this way. Saying so plainly is the point of this section: a reader who assumes these were style calls will reopen them as style arguments, and the counterargument will look stronger than it is because the cost it ignores is deferred rather than absent.

One caveat, so the axis is not applied mechanically. Reversibility is an argument for deferring an addition. It is never an argument for shipping something wrong, and nothing below is deferred because it is hard. Decision 3 in particular withholds a method whose current implementation has a measured runtime defect; reversibility explains why withholding is the right response rather than shipping and fixing later, not why the defect can be ignored.

## Decision 1: `link_reset` stays a `LinkResetPolicy` enum

**Decision.** `LinkResetPolicy` stays an enum with members `ON_OPEN` and `NEVER` (`src/dnp3/master/tcp_runner.py:79`), and `MasterTcpRunner.link_reset` keeps that type. It does not become `link_reset: bool`.

**Reason.** Two members and two behaviours mean the enum carries no information a bool does not, today. The asymmetry is entirely in what happens when a third behaviour appears. Adding `LinkResetPolicy.ON_DEMAND` is a pure addition: every existing call site keeps working and keeps meaning what it meant. Converting a published `link_reset: bool` into an enum is a breaking constructor change, and it fails in the nastiest available way, because `MasterTcpRunner(master=m, link_reset=False)` is the documented use of the parameter and `False` is falsy against an enum comparison that will not match it.

The third value has a named claimant rather than a hypothetical one. IEEE 1815-2012 confirmed user data (`LinkFunctionCode.PRI_CONFIRMED_USER_DATA`; `build_confirmed_user_data` already exists at `src/dnp3/datalink/builder.py:115`) is used on serial links, where a link confirm timeout is the signal to re-reset the link state. A serial master therefore resets more than once per association, at a moment neither `ON_OPEN` nor `NEVER` describes. That behaviour is not implemented and this ADR does not schedule it. The point is only that the third member is a protocol requirement someone can point at, not a shape invented to justify the type.

**Strongest argument against.** Two-member enums are the classic type invented for a future that never arrives, and they charge every caller an import and a longer expression for a parameter that reads perfectly as a bool. `LinkResetPolicy.NEVER` is more to type and more to read than `False`. The claimant is real in the standard and absent from this codebase: `src/dnp3/transport_io/` contains only `channel.py`, `tcp_client.py`, `tcp_server.py`, and `simulator.py`, so there is no serial transport here and no scheduled work to add one. If serial never lands, this decision buys nothing at a small permanent cost paid at every call site.

That is the honest shape of the trade, and it is accepted because the cost of being wrong is small, permanent and bounded, while the cost of the other direction is a breaking change at an unknown future time, borne by a consumer who did not choose it.

## Decision 2: `LinkError` ships as built; `core.exceptions` is fixed separately

**Decision.** `LinkError` stays where PR [#63](https://github.com/craigpnnl/dnp3py/pull/63) puts it: in `dnp3.master.tcp_runner`, deriving from `MasterRunnerError`, which derives from `Exception` (`tcp_runner.py:93`, `:97`, `:101`). The library's exception taxonomy is repaired in a separate change, not in this PR.

**Reason.** `dnp3.core.exceptions` is not a taxonomy that `LinkError` could usefully join. It is dead code that actively shadows live names. It defines `DNP3Error` and, beneath it, `CRCError`, `ParseError`, `FrameError`, `TransportError`, `ApplicationError`, `TimeoutError`, `ChannelError`, `CommandError`, and `ConfigError`. Two of those names are shadowed by live classes elsewhere in the package that derive from `Exception` directly rather than from `DNP3Error`: `ChannelError` at `src/dnp3/transport_io/channel.py:231` and `ParseError` at `src/dnp3/application/parser.py:67`. A third live error, `ReassemblyError` at `src/dnp3/transport/reassembler.py:13`, has no `core.exceptions` counterpart at all. Every `raise ChannelError` in the package raises the `transport_io` class; the `core.exceptions` one is raised nowhere in the library. The consequence for a user is precise and silent:

```python
except dnp3.core.exceptions.ChannelError:  # matches nothing the library raises
```

`src/dnp3/core/__init__.py:11` re-exports the dead names, so they are importable, implicitly documented by their presence, and inert.

Putting `LinkError` into that module would place a live exception inside a namespace whose neighbours do not work, which is worse than leaving it in the module that raises it. Under `MasterRunnerError` it does what its docstring promises: a caller catches `MasterRunnerError` and gets everything the runner raises, without importing from `transport_io` or `transport`.

The follow-up, which is the right fix and is deliberately not this PR:

- Make `core.exceptions` canonical, and have each layer module import and re-export its exception from there rather than defining its own. Import-and-re-export, not deletion of the layer names: `from dnp3.transport_io.channel import ChannelError` works today, and deleting it would break a pinner on upgrade for no benefit.
- Reparent `MasterRunnerError` onto `DNP3Error`. Additive for anyone catching `MasterRunnerError`, newly useful for anyone catching `DNP3Error`.
- Give `ResponseTimeoutError` the builtin `TimeoutError` as a second base, so `except TimeoutError` does the obvious thing.

Every item there widens what an `except` clause catches and none narrows it, which is why the whole follow-up can wait without accumulating risk. That work is tracked as [#67](https://github.com/craigpnnl/dnp3py/issues/67), which reports the concrete defect underneath it: `core.exceptions` declares types nothing raises whose names shadow the live ones with a different base, so `except dnp3.core.exceptions.ChannelError` never fires. [#66](https://github.com/craigpnnl/dnp3py/issues/66) is adjacent, reporting `Master.process_response` catching bare `Exception` and flattening every parse failure to `None`. That is the same error-handling neighbourhood but not the same work, and fixing it well probably wants the taxonomy repaired first.

**Strongest argument against.** Shipping `LinkError` in the runner module normalizes the exact pattern that produced the mess: each layer defining its own exception locally with no shared root. The count of orphan hierarchies goes from three to four, and the follow-up gets harder in proportion. There is a real argument that the taxonomy should be fixed first so `LinkError` lands into a working `core.exceptions` on day one and never has a wrong home to migrate from. It is rejected on scope rather than on merit: repairing the taxonomy touches at least `core/exceptions.py`, `core/__init__.py`, `transport_io/channel.py`, `application/parser.py`, and `transport/reassembler.py`, and folding that into a PR that adds a transport driver makes both changes harder to review and hands a future bisect one commit covering two unrelated regressions. The mitigation is that the follow-up is additive, so the cost of having shipped first is close to zero.

## Decision 3: `run_polls()` does not ship in PR [#63](https://github.com/craigpnnl/dnp3py/pull/63); `poll(task)` does

**Decision.** `poll(task)` ships (`tcp_runner.py:451`). `run_polls()` (`tcp_runner.py:410` through `:448` on the branch as built) is removed before merge and is not part of this class's initial public API.

**Reason, first and sufficient on its own: reversibility.** `poll(task)` is the smallest useful thing. It builds a request from a scheduler task, runs the exchange, and marks the task executed. A caller who wants a loop writes one in about five lines around it, and their loop is theirs to supervise. Adding `run_polls()` in a later release is a pure addition. Removing a shipped public method is a breaking change, and it is the kind a pinner meets as an `AttributeError` in production rather than as a failure at import.

**Reason, second: the loop as written is not correct yet**, and it is incorrect in exactly the region a convenience method exists to make safe. Two things are true of it as built.

*It ignores every configured retry count.* `PollingConfig.retry_count` defaults to 2 (`src/dnp3/master/config.py:33`) and `MasterConfig.task_retry_count` defaults to 2 (`src/dnp3/master/config.py:60`), the latter validated as non-negative at `config.py:86`. The string `retry` appears on none of the 773 lines of `src/dnp3/master/tcp_runner.py`. So the only scheduling loop the library offers honours neither of the two retry settings the library invites a user to configure, and a user who sets them gets no error and no effect.

*It starves the event loop on a failing task.* The loop calls `poll(task)`, catches `MasterRunnerError`, logs, and continues. `mark_poll_executed` is reached only on success, so a failing task stays due and `get_next_task()` returns it again immediately. When the failure raises before any suspension point, which is what `_require_open()` does on a closed channel, awaiting the coroutine never yields to the event loop. The loop then spins with no `await` that suspends, and three things follow from that one fact: the `stop` event can never be set by another coroutine, because no other coroutine runs; `asyncio.CancelledError` can never be delivered, because cancellation is delivered at suspension points; and `logger.exception` fires once per iteration, so the log is the flood rather than the warning. Two independent runtime harnesses measured this at 18,871 and 29,446 failed iterations per second, with no yield, no cancellation path, and no escalation. Those two figures come from measurement; the mechanism described above is read from the source.

A convenience method whose documented purpose is to be unsupervised, and whose failure mode is an uncancellable hot loop, is worse than no method at all, because it is the one an unfamiliar caller reaches for first.

**Strongest argument against.** The scheduler is genuinely awkward to drive by hand, and `run_polls()` composes `PollScheduler` with the transport in a way every future transport would otherwise reimplement, which is the duplication the class docstring says it wants to avoid. Withholding it means the first user writes the loop themselves, probably writes it worse, and the library learns nothing from it because the loop lives in their code. The stronger form of the objection is that the two defects above are arguments for fixing the loop, not for withholding it, and that a fixed loop could ship in the same PR. That is fair, and it is rejected on sequencing rather than on substance: fixing it well means deciding retry semantics, which of the two retry counts governs, whether a retry re-enters the scheduler or repeats in place, and what backoff applies. Those are design questions with their own reversibility problem, because retry semantics become observable behaviour the moment they ship. Better to leave the seam empty than to fill it in a hurry; an empty seam costs nothing to fill later.

## Decision 4: a closed channel raises uniformly

**Decision.** Correct as implemented; no change in this PR. `_require_open()` (`tcp_runner.py:750` through the end of the file) raises `MasterRunnerError` both when `open()` has not been awaited and when the channel has since closed, and every public entry point calls it.

**Reason.** The uniformity is a real property rather than an accident. Without it, an injected channel closed by its owner surfaced as a bare channel-closed error from the first write and as a `ResponseTimeoutError` from the first read: two wrong types for one condition. Returning the narrowed `(channel, reassembler)` pair rather than asserting also keeps the invariant enforced under `python -O`, where `assert` is stripped. Both properties are worth keeping and neither is in question.

**Strongest argument against**, accepted here as a real limitation rather than dismissed: the method conflates two conditions that deserve different treatment. "`open()` was never awaited" is a programming error whose only correct response is to fix the calling code. "The channel was open and the link has since died" is an operational condition a long-running SCADA client should expect, log, and recover from by reconnecting. Giving both the same type forces a caller who wants to tell them apart to match on message text, which is the worst discriminator available.

The refinement is to add two subclasses of `MasterRunnerError`, one per condition, and raise those. It is deliberately not in this PR because it is non-breaking whenever it lands: a caller catching `MasterRunnerError` keeps catching both, and a caller who wants the distinction opts in. Since it costs nothing to defer and nothing to add later, this is the one question of the four where timing genuinely does not matter. It should land when someone needs it, ideally alongside the taxonomy work in decision 2 so both arrive as one widening of the error surface.

## The serial-runner test

Each decision is worth checking against the moment the shared seam actually gets cut, which is when a second transport lands. The class docstring already states the position: the outstation and master runners share a shape, but the seam between them is better extracted once there are two real implementations to compare than guessed from one. A serial runner is the likeliest second implementation, since serial is the transport DNP3 was designed for and the one this library does not yet speak. So what does each decision look like on the day a serial master runner exists?

**1. The enum.** This is the decision the test most clearly vindicates. A serial runner is precisely where `ON_DEMAND` becomes necessary, because confirmed user data on a serial link re-resets after a link confirm timeout. Under the enum, the serial runner adds a member and the TCP runner is untouched. Under a bool, the day serial lands is the day the master's constructor signature changes for everyone, including every TCP user who will never send a confirmed frame.

**2. The exceptions.** Neutral to mildly unfavourable, and this is the decision the test pressures most. A serial runner raising its own `LinkError` under its own `SerialRunnerError` gives the package a fourth orphan hierarchy and makes "catch everything a master runner can raise" impossible to write without a tuple of imports. The test therefore converts the taxonomy follow-up from tidy-up into a prerequisite for a second transport. It argues for doing that work before the serial runner. It does not argue for having done it inside PR [#63](https://github.com/craigpnnl/dnp3py/pull/63).

**3. `run_polls()`.** This is the decision that was effectively made under the test already. The scheduling loop is transport-independent by construction, so if it ships as a method on the TCP runner it gets either copied into the serial runner or hoisted into a shared base at the cost of a breaking move. Withholding it means the second transport arrives with the seam still empty and both implementations available to compare, which is the condition the docstring names as the right one for extracting it. If a shared loop is wanted then, it should be extracted from two implementations, and quite possibly not as a method on a transport class at all.

**4. Uniform raising.** Neutral. `_require_open` is per-transport state validation and will be reimplemented in whatever form the serial runner needs. The refinement in decision 4 is worth doing before that point only so both runners raise the same pair of types instead of diverging.

The test changes none of the four calls, which is the useful outcome. Three are unaffected and one, the exceptions, acquires a deadline it did not previously have.

## Consequences

- `MasterTcpRunner` merges with a smaller API than the branch currently carries. `run_polls()` is removed; `poll()`, `request()`, `send()`, `integrity_poll()`, `class_poll()`, the unsolicited controls, and the async context manager remain. Anyone wanting a scheduling loop writes it, and it is about five lines.
- The library keeps a documented exception taxonomy that does not work. Until the follow-up lands, `dnp3.core.exceptions` stays importable, re-exported from `core/__init__.py`, and matched by nothing the library raises. The follow-up issue should say that in those words, so it is not filed as cosmetic and prioritized accordingly.
- The follow-up work is bounded and additive. It touches `core/exceptions.py` (canonical definitions), `core/__init__.py` (re-export set), `transport_io/channel.py`, `application/parser.py`, and `transport/reassembler.py` (import and re-export rather than define), and `master/tcp_runner.py` (reparent `MasterRunnerError` onto `DNP3Error`, add the builtin `TimeoutError` as a second base of `ResponseTimeoutError`, and optionally split the two `_require_open` conditions). No name is removed, so a pin upgrading across it sees only wider `except` clauses.
- Two retry settings stay decorative. `PollingConfig.retry_count` and `MasterConfig.task_retry_count` are configurable, one of them validated, and consumed by no scheduling loop. Withholding `run_polls()` does not create that gap, but it does remove the one place they might plausibly have been honoured, so it is recorded here: the library currently offers configuration it does not act on.
- A future `run_polls()` is unconstrained by this ADR except in one respect. Whatever it decides about retries and cancellation becomes observable behaviour on the day it ships, and is subject to the same reversibility test applied here.

## What would make us revisit

**Decision 1, the enum.** Revisit if the library reaches 1.0 with no serial or UDP transport in sight and `LinkResetPolicy` still has two members. At that point the enum has failed to earn itself, and a major version is the one moment where converting it to a bool is legal. Do not revisit before then: a two-member enum in 0.x is not evidence of anything yet.

**Decision 2, the exception taxonomy.** Revisit, meaning do the follow-up, when either a second runner is being written (see the serial test above) or a user reports that an `except` clause did not fire. Watch for the second trigger in particular, because it will arrive as a confusing bug report rather than as a taxonomy complaint.

**Decision 3, `run_polls()`.** This one needs its conditions spelled out, because "later" is otherwise indefinite and the method will either never return or return unchanged. The scheduling loop ships when all of the following hold:

- Retry semantics are decided and written down: which of `PollingConfig.retry_count` and `MasterConfig.task_retry_count` governs a scheduled poll, whether a retry re-enters the scheduler or repeats in place, and what backoff applies between attempts. Two settings with an overlapping meaning is itself a question this ADR does not settle.
- The loop yields on every path. Specifically, a failure raised before any suspension point must not produce another iteration without an `await` that suspends, so cancellation is deliverable and a `stop` event set from another coroutine is observable.
- A failing task is bounded. Once its retries are exhausted it is either rescheduled to its next due time or dropped, so one dead outstation cannot monopolize the loop.
- Failure is observable without reading logs: a callback, an exception after N consecutive failures, or a returned summary. A `logger.exception` per iteration is not a supervision mechanism.
- A test covers the failing-task case with a bounded run and asserts the iteration count, not merely that the call returned. The defect described in decision 3 is invisible to any test that only asserts a clean shutdown.

Until those hold, `poll(task)` is the API and the caller's own loop is the supervision.

**Decision 4, uniform raising.** Revisit as soon as anyone needs to distinguish a never-opened runner from a dropped link, most likely the first time reconnection logic is written against this class. It is additive, so there is no reason to defer it past that point and no reason to do it before.

## Alternatives Considered

- **Merge PR [#63](https://github.com/craigpnnl/dnp3py/pull/63) as built and correct the API afterwards** (rejected). The option that looks cheapest today and is the most expensive of the set, because it is the only one that publishes something that later has to be taken back. `run_polls()` in a released version is a method with users: removing it is then a breaking change on a published package with a pinning consumer, and keeping it means supporting a loop that ignores the retry configuration and cannot be cancelled. The reversibility axis exists to make this option unattractive before it is taken rather than after.
- **Hold PR [#63](https://github.com/craigpnnl/dnp3py/pull/63) until the exception taxonomy is repaired** (rejected). Correct in the abstract, wrong in sequencing. It blocks the first master transport driver, which is what issue [#57](https://github.com/craigpnnl/dnp3py/issues/57) actually asked for, behind an unrelated cleanup spanning five modules, and it merges two independent changes into one bisect target. The follow-up is additive, so nothing is lost by ordering it second.
- **Decide all four questions on readability rather than on reversibility** (rejected, and named because it is the default anyone will fall back to). On readability alone at least two of the four go the other way: `link_reset: bool` reads better than `LinkResetPolicy.NEVER` at every call site, and a convenience `run_polls()` reads better than a hand-written loop. Readability is the right tiebreaker where the reversibility cost is symmetric, and decision 4 is settled that way. Where the cost is asymmetric, deciding on readability means paying a breaking change later in exchange for reading slightly better in the interim.

## References

- Issue [#57](https://github.com/craigpnnl/dnp3py/issues/57): Add a MasterTcpRunner: the master role has no TCP driver counterpart to OutstationTcpRunner
- PR [#63](https://github.com/craigpnnl/dnp3py/pull/63): feat: add MasterTcpRunner, a TCP driver for the master role
- Issue [#66](https://github.com/craigpnnl/dnp3py/issues/66): Master.process_response catches bare Exception, flattening every parse failure to None with no diagnostic
- Issue [#67](https://github.com/craigpnnl/dnp3py/issues/67): core.exceptions declares exception types that nothing raises and that shadow the live ones

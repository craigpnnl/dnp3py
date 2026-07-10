# DNP3 Control Commands

This guide covers sending and receiving DNP3 control commands with dnp3py:
Control Relay Output Block (CROB, Group 12) for binary outputs, and Analog
Output (Group 41) for analog setpoints. It walks through how a master sends
a control command, how an outstation wires a handler to receive one, and the
wire-level encoding both sides agree on.

The examples below use the in-process fragment API directly (build a
request, serialize it, hand the bytes to the peer, serialize the response
back). Getting those bytes onto an actual TCP connection is the job of
`dnp3.transport_io` and the data link and transport layers underneath the
application layer; this guide stays at the application layer, where control
semantics live.

## Control function codes

DNP3 defines four function codes for control operations, per IEEE 1815-2012
Clause 4. All four are members of `dnp3.core.enums.FunctionCode`:

| Function code | Value | Meaning |
|---|---|---|
| `SELECT` | `0x03` | First step of select-before-operate: validate without executing. |
| `OPERATE` | `0x04` | Second step of select-before-operate: execute a previously selected command. |
| `DIRECT_OPERATE` | `0x05` | Single-step control: validate and execute immediately, response expected. |
| `DIRECT_OPERATE_NO_ACK` | `0x06` | Single-step control with no response. |

dnp3py's outstation dispatches all four. The master side currently builds
requests for `SELECT`, `OPERATE`, and `DIRECT_OPERATE` through `Master` and
`CommandBuilder`; there is no built-in request builder for
`DIRECT_OPERATE_NO_ACK` yet, so a caller who needs that function code has to
assemble the request fragment directly against `dnp3.application.builder`.

## Sending control commands from a master

### CommandBuilder

`Master.command_builder()` returns a fresh `dnp3.master.commands.CommandBuilder`
on every call; builders are not shared state across commands. The builder has
a fluent interface for adding operations, then converts the accumulated
operations into a task for whichever function code you need:

```python
from dnp3.master import Master

master = Master()
builder = master.command_builder()
builder.latch_on(index=0)          # CROB, ControlCode.LATCH_ON
builder.add_analog(index=1, value=42.0)  # Group 41 analog output

# The same operations can be turned into any of the three task types:
select_task = builder.build_select()
operate_task = builder.build_operate()
direct_task = builder.build_direct_operate()
```

`add_crob(index, code, count=1, on_time=0, off_time=0)` and
`add_analog(index, value)` are the general-purpose entry points.
`latch_on`, `latch_off`, `pulse_on`, and `pulse_off` are convenience wrappers
around `add_crob` for the common `ControlCode` values. Stick to `NUL`,
`LATCH_ON`, `LATCH_OFF`, `PULSE_ON`, and `PULSE_OFF` when building CROB
operations: the outstation's request parser only ever compares the low nibble
of the control-code byte against `ControlCode`, so the two remaining enum
members, `CLOSE_PULSE_ON` and `TRIP_PULSE_ON`, are not distinguishable from
`PULSE_ON` once a request reaches the outstation (see "Wire-level reference"
below).

### DIRECT_OPERATE: binary output

```python
from dnp3.database import BinaryOutputConfig, Database
from dnp3.master import Master
from dnp3.outstation import Outstation

database = Database()
database.add_binary_output(0, BinaryOutputConfig())

outstation = Outstation(database=database)
master = Master()

builder = master.command_builder()
builder.latch_on(index=0)
request = master.build_direct_operate(builder.build_direct_operate())

responses = outstation.process_request(request.to_bytes())
response_bytes = responses[0].to_bytes()
```

`request.header.function` is `FunctionCode.DIRECT_OPERATE`. This is the
complete request/response round trip at the fragment level; wiring
`request.to_bytes()` onto a live channel and reading the reply bytes back is
a transport-layer concern outside this guide.

Note that `Outstation()`'s default handler (`DefaultCommandHandler`) rejects
every operation with `CommandStatus.NOT_SUPPORTED`. The example above proves
the request and response round-trip; see "Wiring an outstation" below for a
handler that actually executes the command.

### SELECT then OPERATE: binary output

```python
builder = master.command_builder()
builder.latch_on(index=0)

select_request = master.build_select(builder.build_select())
select_responses = outstation.process_request(select_request.to_bytes())

# Re-use the same builder (same operations) to build OPERATE. The outstation
# checks OPERATE against the stored SELECT state, including the control
# code, count, on_time, and off_time; they must match what was selected.
operate_request = master.build_operate(builder.build_operate())
operate_responses = outstation.process_request(operate_request.to_bytes())
```

`select_request.header.function` is `FunctionCode.SELECT`;
`operate_request.header.function` is `FunctionCode.OPERATE`. A SELECT that is
not followed by a matching OPERATE within the outstation's configured
`select_timeout` (`OutstationConfig.select_timeout`, default 10 seconds)
expires; a late or mismatched OPERATE gets back `CommandStatus.NO_SELECT`.

### DIRECT_OPERATE: analog output

```python
builder = master.command_builder()
builder.add_analog(index=0, value=42.0)
request = master.build_direct_operate(builder.build_direct_operate())

responses = outstation.process_request(request.to_bytes())
```

`CommandBuilder.add_analog` always encodes the value as Group 41 Variation 1
(32-bit signed integer): the analog value is truncated to an `int` before it
is placed on the wire. If you need Variation 2 (16-bit), 3 (float32), or 4
(float64), build the `ObjectBlock` directly against
`dnp3.master.commands.ANALOG_OUTPUT_16_VARIATION` /
`ANALOG_OUTPUT_FLOAT_VARIATION` / `ANALOG_OUTPUT_DOUBLE_VARIATION`; the
builder's fluent interface does not expose variation selection.

**SELECT and OPERATE are not currently wired for analog outputs on the
outstation side.** `CommandBuilder.build_select()` and `.build_operate()`
will happily encode a Group 41 block, and `Outstation` will echo it back, but
`Outstation._handle_select` and `_handle_operate` only dispatch Group 12
(CROB) blocks to the handler; a Group 41 block in a SELECT or OPERATE request
is echoed with `CommandStatus.NOT_SUPPORTED` on every point, regardless of
what your `CommandHandler.select_analog_output` / `operate_analog_output`
implementation would have returned. Use `DIRECT_OPERATE` for analog outputs
until that wiring exists.

### Reading the command result

`Master.process_response(data)` parses a response into a `ResponseInfo`
(function code, IIN, sequence number, unsolicited flag). It does not
currently decode the per-point `CommandStatus` out of a CROB or analog
output echo: `Master`'s response-object parsing recognizes groups 1, 2, 10,
11, 20, 21, 22, 30, 32, 40, and 42 (static data and events), but not group 12
or 41 (the control echoes), so calling it on a control response is safe and
returns a `ResponseInfo`, but tells you nothing about whether any individual
point succeeded. The `CommandResponse` dataclass in
`dnp3.master.handler` exists for exactly this purpose but nothing in the
library constructs one yet.

Until that gap closes, the coarse signal is `ResponseInfo.iin`: a set
`IIN.PARAMETER_ERROR` bit means the outstation could not parse the request at
all (see "Fail-closed behavior" below). For the actual per-point status, read
it out of the response bytes yourself. The response echoes the same object
headers the request used, with only the trailing status byte replaced, so the
layout to walk is the qualifier-derived layout described in "Wire-level
reference":

```python
from dnp3.application.parser import parse_response
from dnp3.core.enums import CommandStatus, QualifierCode

def decode_crob_statuses(response_bytes: bytes) -> list[tuple[int, CommandStatus]]:
    """Decode (index, CommandStatus) pairs from a CROB control response."""
    response = parse_response(response_bytes)
    results: list[tuple[int, CommandStatus]] = []

    for block in response.objects:
        if block.header.group != 12:
            continue
        if block.header.qualifier == QualifierCode.UINT8_COUNT_UINT8_INDEX:
            count_bytes, index_bytes = 1, 1
        elif block.header.qualifier == QualifierCode.UINT16_COUNT_UINT16_INDEX:
            count_bytes, index_bytes = 2, 2
        else:
            continue

        data = block.data
        count = int.from_bytes(data[0:count_bytes], "little")
        offset = count_bytes
        for _ in range(count):
            index = int.from_bytes(data[offset : offset + index_bytes], "little")
            offset += index_bytes
            offset += 10  # control_code(1) + op_count(1) + on_time(4) + off_time(4)
            results.append((index, CommandStatus(data[offset])))
            offset += 1

    return results
```

The same shape applies to Group 41 responses; replace the fixed 10-byte skip
with the analog output value width for the variation in use (4 bytes for
Variation 1 and 3, 2 bytes for Variation 2, 8 bytes for Variation 4).

## Wiring an outstation to receive control commands

### The CommandHandler protocol

An outstation dispatches every control request to its configured
`CommandHandler` (`dnp3.outstation.handler`). Implement the methods you
support; the protocol covers both binary and analog outputs, plus restart and
freeze:

| Method | Called for |
|---|---|
| `select_binary_output` | CROB SELECT. Validate without executing. |
| `operate_binary_output` | CROB OPERATE, after a matching SELECT. Execute. |
| `direct_operate_binary_output` | CROB DIRECT_OPERATE. Validate and execute in one step. |
| `select_analog_output` | Analog output SELECT. Defined by the protocol; not currently reachable, see above. |
| `operate_analog_output` | Analog output OPERATE. Defined by the protocol; not currently reachable, see above. |
| `direct_operate_analog_output` | Analog output DIRECT_OPERATE. Validate and execute in one step. |
| `cold_restart` / `warm_restart` | Restart requests. Return a delay in milliseconds, or `None` to reject. |
| `freeze_counters` | FREEZE / FREEZE_CLEAR requests. |

Each method returns a `CommandResult`, a frozen dataclass carrying a
`CommandStatus` and an optional message. `CommandResult` has classmethod
constructors for the common outcomes: `.success()`, `.not_supported()`,
`.format_error()`, `.hardware_error()`, `.local()`, `.blocked()`, and
`.out_of_range()`. Any other `CommandStatus` value can be constructed
directly: `CommandResult(status=CommandStatus.ALREADY_ACTIVE)`.

`DefaultCommandHandler` implements the full protocol and rejects every
operation with `CommandResult.not_supported()`; restart requests return
`None`. Subclass it and override only the methods your outstation supports.

### A minimal binary output handler

```python
from dnp3.core.enums import ControlCode
from dnp3.database import Database
from dnp3.outstation.handler import CommandResult, DefaultCommandHandler


class RelayHandler(DefaultCommandHandler):
    def __init__(self, database: Database) -> None:
        self._database = database

    def direct_operate_binary_output(
        self,
        index: int,
        code: ControlCode,
        count: int,
        on_time: int,
        off_time: int,
    ) -> CommandResult:
        if self._database.get_binary_output(index) is None:
            return CommandResult.not_supported(f"no binary output at index {index}")
        if code == ControlCode.LATCH_ON:
            self._database.update_binary_output(index, value=True)
        elif code == ControlCode.LATCH_OFF:
            self._database.update_binary_output(index, value=False)
        return CommandResult.success()
```

Wire it into the outstation the same way as any other handler:

```python
database = Database()
database.add_binary_output(0, BinaryOutputConfig())

outstation = Outstation(database=database, handler=RelayHandler(database))
```

For SELECT-before-OPERATE, override `select_binary_output` to validate (index
exists, value in range, output not already active) without touching the
database, and `operate_binary_output` to apply the change; the outstation
handles the SELECT/OPERATE state matching and expiry for you.

### Analog outputs need their own store

The core `Database` (`dnp3.database.Database`) has no storage for analog
outputs (Group 40 static data, Group 41 command echoes): it stores binary
inputs, binary outputs, analog inputs, counters, and frozen counters, but not
analog output values. A `direct_operate_analog_output` implementation has to
track the current value itself, typically validating against a configured
range before accepting it. `dnp3.mesa.command_handler.MesaCommandHandler` is
a working reference implementation of this pattern: it pairs a
`CommandHandler` with a separate analog-output store, validates the incoming
value against the store's configured minimum and maximum, and returns
`CommandResult.out_of_range()` when the value falls outside that range.

## Wire-level reference

### Object groups and qualifiers

CROB is Group 12 Variation 1. Analog output is Group 41, with variation
selecting the value's wire format:

| Variation | Format | Value size |
|---|---|---|
| 1 | 32-bit signed integer | 4 bytes |
| 2 | 16-bit signed integer | 2 bytes |
| 3 | Single-precision float | 4 bytes |
| 4 | Double-precision float | 8 bytes |

Both object types use the same pair of qualifiers, `QualifierCode.UINT8_COUNT_UINT8_INDEX`
(`0x17`) and `QualifierCode.UINT16_COUNT_UINT16_INDEX` (`0x28`), and the count
and index field widths are always derived from the qualifier byte actually
present in the request, never hardcoded:

- `0x17`: a 1-byte count field, followed by that many objects, each prefixed
  with a 1-byte index.
- `0x28`: a 2-byte count field, followed by that many objects, each prefixed
  with a 2-byte index.

A CROB object body (after its index prefix) is always 11 bytes: control code
(1 byte, low nibble is the operation type), operation count (1 byte), on-time
(4 bytes), off-time (4 bytes), and a status byte (1 byte, ignored on request,
set to the result on response). An analog output object body is the index
prefix, the value (sized per the variation table above), and a status byte.

Any qualifier other than `0x17` or `0x28` on a CROB or analog output block is
rejected; there is no fallback interpretation.

### The echo path

Per IEEE 1815-2012, a control response echoes the request's object headers
and data back to the master, with only the per-object status byte replaced
by the actual result. dnp3py's outstation does this literally: the response
object carries the same group, variation, and qualifier as the request, and
every field except the trailing status byte is copied byte-for-byte from
what the master sent. This applies identically whether the qualifier was
`0x17` or `0x28`.

### Fail-closed behavior on malformed frames

Three distinct malformed-input cases are handled explicitly, all resulting
in `CommandStatus.FORMAT_ERROR` for the affected point (or points) rather
than a crash or a silent success:

- **Unknown qualifier.** A CROB or analog output block whose qualifier is
  not `0x17` or `0x28` cannot be sized, so it cannot be parsed at all.
- **Truncated buffer.** The count field declares more objects than the
  remaining data can hold, whether the truncation happens before the first
  object or partway through the declared count.
- **Undefined control-code nibble.** A CROB control-code byte whose low
  nibble does not correspond to a defined `ControlCode` (nibble values `0x05`
  through `0x0F`) fails per-object, without aborting the rest of the block.

A request that fails to parse at the application-layer header level at all
(`Outstation.process_request` catching a parse exception) gets a null
response with no objects and `IIN.PARAMETER_ERROR` set; nothing about the
originally intended points is echoed, because none of them were successfully
identified.

### CommandStatus and IIN

`CommandStatus` (`dnp3.core.enums`) is the per-point result carried in the
response's status byte. The common values:

| Status | Meaning |
|---|---|
| `SUCCESS` (0) | Command executed (or, for SELECT, validated) successfully. |
| `TIMEOUT` (1) | Command timed out. |
| `NO_SELECT` (2) | OPERATE received with no matching prior SELECT. |
| `FORMAT_ERROR` (3) | Malformed request data for this point. |
| `NOT_SUPPORTED` (4) | The point, or the operation on it, is not supported. |
| `OUT_OF_RANGE` (12) | Value outside the point's configured range. |

The full set (19 named values plus `NON_PARTICIPATING` and `UNDEFINED`)
covers every Table 4-5 status from IEEE 1815-2012.

`IIN.PARAMETER_ERROR` is a coarser, header-level signal, not a per-point one.
It is set on the response whenever any part of the request could not be
parsed: an unknown qualifier, a truncated buffer, or an undefined
control-code nibble anywhere in the request. It is not set merely because a
well-formed command was rejected for a business reason: a `NOT_SUPPORTED` or
`OUT_OF_RANGE` result from your `CommandHandler` leaves `IIN.PARAMETER_ERROR`
clear, because the request itself was valid; only its outcome was negative.
Check the per-point `CommandStatus` (via the echoed object, see "Reading the
command result" above) to distinguish a rejected-but-valid command from a
successful one; check `IIN.PARAMETER_ERROR` only to detect that the request
itself was malformed.

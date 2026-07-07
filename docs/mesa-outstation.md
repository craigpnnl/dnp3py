# MESA IEEE 1815.2 Outstation: Profile Guide

This guide covers the PicsProfile format the `dnp3.mesa` outstation consumes.
The profile describes every DNP3 point the outstation exposes: binary
outputs, binary inputs, analog outputs, analog inputs, and counters, plus the
equipment groups, curves, and schedules layered on top of the analog
sections.

dnp3py adopted this format from mesa-tool (the companion Rust conformance
control station) so both tools read the same point map in a cross-repo
conformance loop, instead of maintaining two independent shapes. See ADR-002
for the decision record. Profiles are authored as JSON; there is no
spreadsheet ingestion path.

## Bundled profiles

Four profiles ship inside the package, under
`src/dnp3/mesa/data/profiles/`:

| Selector | File | When to use |
|----------|------|-------------|
| `full` (default) | `full.json` | The full 1815.2 point map. The general case and the conformance-loop default. |
| `mandatory_1815` | `mandatory_1815.json` | Only points mandatory for IEEE 1815.2. Conformance subset. |
| `mandatory_1547` | `mandatory_1547.json` | Only points mandatory for IEEE 1547. Conformance subset. |
| `minimal_1547` | `minimal_1547.json` | The smallest 1547 subset; fastest conformance pass. |

Select a bundled profile by name with `--profile-name`, or point `--profile`
at any other PicsProfile JSON file (a custom device profile, for example).
Omitting both flags defaults to the packaged `full.json`, resolved via
`importlib.resources` so the default works whether dnp3py is running from a
source checkout or installed from a wheel.

## Quick start (CLI)

```
usage: python -m dnp3.mesa [-h] [--profile PROFILE]
                           [--profile-name {full,mandatory_1815,mandatory_1547,minimal_1547}]
                           [--host HOST] [--port PORT] [--address ADDRESS]
                           [--master-address MASTER_ADDRESS] [--meters METERS]
                           [--ders DERS] [--inverters INVERTERS]
                           [--batteries BATTERIES]

options:
  --profile PROFILE           Path to a PicsProfile JSON file (default: bundled full.json)
  --profile-name {full,mandatory_1815,mandatory_1547,minimal_1547}
                              Select a bundled profile by name instead of --profile
                              (mutually exclusive with --profile)
  --host HOST                 Listen address (default: 0.0.0.0)
  --port PORT                 Listen port (default: 20000)
  --address ADDRESS           DNP3 outstation address (default: 1)
  --master-address MASTER_ADDRESS
                              Expected master address (default: 0)
  --meters METERS             Number of meter instances to include
  --ders DERS                 Number of DER instances to include
  --inverters INVERTERS       Number of inverter instances to include
  --batteries BATTERIES       Number of battery instances to include
```

Run the simulator against the bundled full profile (the default, so
`--profile`/`--profile-name` can be omitted entirely):

```bash
python -m dnp3.mesa
```

Run against a conformance subset, or a custom profile:

```bash
python -m dnp3.mesa --profile-name minimal_1547
python -m dnp3.mesa --profile my_device_profile.json
```

### Equipment-count flags

Each equipment group (meters, DERs, inverters, batteries) in a PicsProfile is
an explicit array of instances, each an equipment struct with its own points.
The `--meters`, `--ders`, `--inverters`, and `--batteries` flags include only
the first N instances of that type (1-based), excluding the rest from the
built database:

```bash
# Include only the first meter; exclude all DERs, inverters, and batteries.
python -m dnp3.mesa --profile-name full --meters 1 --ders 0 --inverters 0 --batteries 0
```

An omitted flag includes every instance the profile carries for that type.
Note the analog output (`AO`) section has no `ders` group in PicsProfile, so
`--ders` affects only the binary-input and analog-input DER groups.

### Programmatic API

```python
import asyncio
from pathlib import Path
from dnp3.mesa.outstation import create_mesa_outstation

async def main():
    outstation = create_mesa_outstation(
        profile_path=Path("my_device_profile.json"),
        host="0.0.0.0",
        port=20000,
        address=1,
        master_address=0,
        entity_overrides={"meters": 1, "ders": 0},  # optional
    )
    await outstation.run()

asyncio.run(main())
```

`create_mesa_outstation` returns a `MesaOutstation` dataclass. Call
`await outstation.run()` to start the TCP server; call `await outstation.stop()`
to shut it down cleanly.

## Profile structure

A profile is a single JSON object with six top-level keys, matching
mesa-tool's `PicsProfile` serde struct one for one:

| Key | Type | Description |
|-----|------|--------------|
| `Key` | object | Section start indices and per-equipment-type counts (`KeySheet` in `src/dnp3/mesa/profile.py`). |
| `BO` | object | Binary Output points (`BinaryOutputs`). |
| `BI` | object | Binary Input points, plus equipment instances (`BinaryInputs`). |
| `AO` | object | Analog Output points, plus equipment instances (`AnalogOutputs`). No DER equipment group. |
| `AI` | object | Analog Input points, plus equipment instances, curves, and schedules (`AnalogInputs`). |
| `CTR` | array | Counter points (`CtrPoint`). |

Every point present in the profile is included; there is no `supported` flag
to filter on (unlike the retired pre-PicsProfile format). Equipment instances
are explicit array elements, not per-point annotations.

## Point object fields

Fields common across the four typed point sections (`BoPoint`, `BiPoint`,
`AoPoint`, `AiPoint`) and `CtrPoint`, per `src/dnp3/mesa/profile.py`:

| Field | Type | Present on | Description |
|-------|------|-------------|-------------|
| `point_index` | integer | all | The DNP3 point index. Never synthesized or defaulted; a missing index is a load error, not a zero-fill. |
| `name` | string | all | Human-readable label. |
| `iec_61850_uid` | string | all | The IEC 61850 unique identifier (e.g. `"MMTR.SupWh"`). Stored verbatim; dnp3py does not normalize it. |
| `purpose` | string | all | Functional role. |
| `mandatory_1815` | boolean | all | Whether the point is mandatory under IEEE 1815.2. |
| `mandatory_1547` | boolean | all | Whether the point is mandatory under IEEE 1547. |
| `event_class` | string | `BiPoint`, `AiPoint`, `CtrPoint` (as `counter_event_class` / `frozen_counter_event_class`) | One of `"Class1"`, `"Class2"`, `"Class3"`, `"None"`. Mapped to the DNP3 integer event class (1, 2, 3, 0) at database registration. Any other string is a load error, not a silent fallback. |
| `assoc_bi` / `assoc_bo` / `assoc_ai` / `assoc_ao` | string or null | `BoPoint`, `BiPoint`, `AoPoint`, `AiPoint` respectively | Cross-type reference in `"<PREFIX><N>"` form (e.g. `"AI29"`). On a write to an AO carrying `assoc_ai`, the command handler mirrors the value to the named AI point. |
| `minimum` / `maximum` | integer | `AoPoint`, `AiPoint` | The point's range, expressed as transmission integers. |
| `multiplier` / `offset` | float | `AoPoint`, `AiPoint` | The affine scaling map between engineering units and the transmission integer (see "Engineering-to-transmission scaling" below). Profile metadata; never transmitted on the wire. A zero multiplier is rejected at load. |
| `units` | string | `AoPoint`, `AiPoint` | Engineering units string. |
| `value` | float | `AiPoint` only | The point's initial value, in engineering units. Scaled to a transmission integer before it reaches the database (see below). |
| `state_0` / `state_1` | string | `BoPoint`, `BiPoint` | Labels for the point's two binary states. |
| `frozen_counter_exists` | boolean | `CtrPoint` | Whether a paired frozen counter (group 21) is registered at the same index. |

## Engineering-to-transmission scaling

`AiPoint.value` is an engineering-unit float, as authored in the profile. The
DNP3 wire and dnp3py's `Database` carry the transmission integer, never the
engineering float. `src/dnp3/mesa/database_builder.py` and
`src/dnp3/mesa/scaling.py` apply the conversion before the value reaches
`add_analog_input`:

1. Clamp the engineering value to the point's declared range first. The
   range is expressed in transmission integers (`minimum`, `maximum`); the
   engineering bounds are `minimum * multiplier + offset` and
   `maximum * multiplier + offset`, sorted before clamping (a negative
   multiplier flips the ordering).
2. Scale: `transmission = round((engineering - offset) / multiplier)`.
3. Rounding matches mesa-tool bit for bit: when the raw quotient's fractional
   part exceeds `1e-7`, round half away from zero (not Python's banker's
   rounding); otherwise truncate toward zero.
4. The result must be a finite value within the signed 32-bit range
   (`-2147483648` to `2147483647`); a non-finite engineering value, a zero or
   non-finite multiplier, a non-finite offset, or an out-of-range result
   raises `ScalingError` rather than silently clamping to a wrong integer.

`multiplier` and `offset` are profile metadata only; they are never placed on
the wire. A master applying the inverse map
(`engineering = transmission * multiplier + offset`) recovers the engineering
value from a read; dnp3py's outstation always stores and serves the
transmission integer.

## CTR (counter) wiring

Every entry in the top-level `CTR` array registers as a 32-bit running
counter (group 20, variation 1) at its `point_index`. When
`frozen_counter_exists` is `true`, a paired 32-bit frozen counter (group 21,
variation 1) is registered at the same index. The 32-bit variants are used
because DER energy counters (Wh, VAh) overflow 16 bits. The initial counter
value is 0; PicsProfile carries no initial counter reading. Event class comes
from `counter_event_class` / `frozen_counter_event_class`, mapped the same
way as the other point types.

## Curves and schedules

The `AI` section's `curves`, `schedules_bc`, and `schedules` arrays are
functional sub-groups layered on top of the base analog inputs: each entry
carries header metadata points (`curve_type`, `number_of_points`, `x_units`,
`y_units` for a curve) plus parallel x/y or array value points. Every point
inside every curve and schedule registers in the AI database at its own
absolute index, the same as a base AI point; a base-only registration would
silently drop them.

The curve-edit selector is an ordinary AO in the base AO array whose
`assoc_ai` targets the curve's header AI point, so a write to the selector
rides the same AO-to-AI mirror path as any other association.

**Deferred:** selector-driven multiplexing, where writing a curve or schedule
index changes which curve's or schedule's x/y arrays a subsequent read
exposes, is not implemented. Registration and the plain selector mirror are
in place; full multiplexed edit semantics are left to a follow-up card.

## Authoring notes

- `point_index` is read directly from the profile and is never synthesized.
  A profile with a missing or malformed index fails to load rather than
  silently defaulting.
- `iec_61850_uid` is stored verbatim, including any underscores inside its
  dotted segments; dnp3py does not rewrite or normalize it.
- An unrecognized `event_class` string, a zero `multiplier`, or a missing
  required field raises a load error with context, rather than falling
  through silently.
- `assoc_ai` / `assoc_bi` / `assoc_bo` / `assoc_ao` use the `"<PREFIX><N>"`
  form (e.g. `"AI29"`, `"BI11"`). A malformed association string is a load
  error.

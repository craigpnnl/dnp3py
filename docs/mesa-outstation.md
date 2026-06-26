# MESA IEEE 1815.2 Outstation: Profile Guide

This guide covers how to author or edit a JSON profile for the `dnp3.mesa`
outstation. The profile describes every DNP3 point the outstation exposes and
how many logical entities (meters, DERs, inverters, batteries) it models.

Profiles are authored as JSON today. Spreadsheet (xlsx) ingestion is a planned
future capability, not yet available.

## Profile structure

A profile is a single JSON object with the following top-level keys:

| Key | Type | Description |
|-----|------|-------------|
| `entities` | object | Default entity counts for this profile |
| `binary_outputs` | object | Binary Output (BO) point section |
| `binary_inputs` | object | Binary Input (BI) point section |
| `analog_outputs` | object | Analog Output (AO) point section |
| `analog_inputs` | object | Analog Input (AI) point section |

### `entities`

Declares how many of each entity type the profile was built for. These counts
are used when no `--meters`/`--ders`/`--inverters`/`--batteries` override is
given on the CLI, or when `entity_overrides` is `None` in the Python API.

```json
"entities": {
    "meters": 1,
    "ders": 0,
    "inverters": 0,
    "batteries": 1
}
```

All four keys (`meters`, `ders`, `inverters`, `batteries`) are optional and
default to 0 when omitted.

### Point sections

Each of the four point sections (`binary_outputs`, `binary_inputs`,
`analog_outputs`, `analog_inputs`) has the same shape:

```json
{
    "offsets": { "<label>": <integer>, ... },
    "points":  [ { ... }, ... ]
}
```

#### `offsets`

A map of named index offsets used to separate logical groups within a section.
Common labels in MESA profiles are `scada`, `historical_meters`, and
`historical_batteries`. The loader stores these values on the
`ProfileSection.offsets` attribute but does not currently use them to rewrite
point indices; they are reserved for future multi-entity index arithmetic.

#### `points`

A list of point objects. Points with `"supported": false` are silently skipped
by the loader and are never added to the DNP3 database.

## Point object fields

### Required fields

Every **supported** point (`"supported": true`) must include:

| Field | Type | Description |
|-------|------|-------------|
| `index` | string | DNP3 point reference: `"BO<N>"`, `"BI<N>"`, `"AO<N>"`, or `"AI<N>"` |
| `description` | string | Human-readable label |
| `uid` | string | MESA CIM identifier (e.g. `"DWMX.WMaxPct"`) |
| `purpose` | string | Functional role (e.g. `"Monitoring"`, `"Limit"`) |
| `value` | number | Initial value loaded into the database |
| `supported` | boolean | `true` to include; `false` to skip entirely |

The `index` string determines both the point type and the numeric DNP3 index.
For example, `"AO20000"` maps to Analog Output index 20000.

### Optional fields

| Field | Type | Description |
|-------|------|-------------|
| `associated_index` | string | Cross-type reference, e.g. `"AI0"`: on a DIRECT_OPERATE to this AO, the handler mirrors the value to the named AI point |
| `ieee_1815_2` | boolean | Marks the point as defined in the IEEE 1815.2 profile |
| `ieee_1547_1` | boolean | Marks the point as defined in the IEEE 1547.1 profile |
| `entity_number` | integer | Which entity instance this point belongs to (1-based) |
| `entity_type` | string | Entity category: `"Meter"`, `"DER_Unit"`, `"Inverter"`, or `"Battery"` |
| `entity_index_offset` | integer | Reserved for Phase 2 multi-entity index arithmetic; stored but not yet consumed |
| `minimum` | number | Engineering minimum for the point value |
| `maximum` | number | Engineering maximum for the point value |
| `multiplier` | number | Scaling multiplier (raw value = engineering value / multiplier) |
| `offset` | number | Engineering offset applied after multiplier |
| `units` | string | Engineering units string (e.g. `"watts"`, `"percent"`) |
| `event_class` | integer | DNP3 event class (1, 2, or 3) for change-event generation |

`entity_type` and `entity_number` together identify which logical device a point
belongs to. When an entity override reduces the count below `entity_number`,
that point is excluded from the database.

## Entity overrides

The CLI flags `--meters`, `--ders`, `--inverters`, and `--batteries` override
the counts in `profile.entities`. The Python API accepts the same values via the
`entity_overrides` dict argument to `create_mesa_outstation`.

When an override sets a count lower than the profile default, every point whose
`entity_number` exceeds the new count is excluded from the database. This lets
a single shared profile serve devices with different hardware configurations
without editing the file.

Entity type strings used in point objects map to override keys as follows:

| `entity_type` in profile | Override key |
|--------------------------|--------------|
| `"Meter"` | `meters` |
| `"DER_Unit"` | `ders` |
| `"Inverter"` | `inverters` |
| `"Battery"` | `batteries` |

### Example: suppress all batteries

CLI:
```bash
python -m dnp3.mesa --profile my_profile.json --batteries 0
```

Python API:
```python
create_mesa_outstation(
    profile_path=Path("my_profile.json"),
    entity_overrides={"batteries": 0},
)
```

## Profile template

The package ships a full-featured profile template at
`data/template/profile.json`. It covers all four point types across all four
entity categories and is the recommended starting point for authoring a new
device profile.

## Minimal example

The following self-contained profile defines one system-level Binary Output, two
Binary Inputs (one system-level, one meter entity point), one Analog Output with
a cross-type association, and one Analog Input. It is suitable as a test fixture
or a starting point for a custom profile.

```json
{
    "entities": {"meters": 1, "ders": 0, "inverters": 0, "batteries": 1},
    "binary_outputs": {
        "offsets": {"scada": 0, "historical_meters": 5000, "historical_batteries": 20000},
        "points": [
            {
                "index": "BO0",
                "description": "System Set Lockout State",
                "uid": "DSTO.DEROpSt.disconnected_and_blocked",
                "purpose": "State",
                "associated_index": "BI11",
                "value": 1,
                "ieee_1815_2": true,
                "supported": true
            }
        ]
    },
    "binary_inputs": {
        "offsets": {"scada": 0, "historical_meters": 5000, "historical_batteries": 20000},
        "points": [
            {
                "index": "BI0",
                "description": "DER Available",
                "uid": "DGEN.OpTmh.winTms",
                "purpose": "Monitoring",
                "value": 1,
                "supported": true
            },
            {
                "index": "BI5000",
                "description": "Meter 1 Online",
                "uid": "MMTR.Online",
                "purpose": "Monitoring",
                "value": 1,
                "supported": true,
                "entity_number": 1,
                "entity_type": "Meter",
                "entity_index_offset": 0
            }
        ]
    },
    "analog_outputs": {
        "offsets": {"scada": 0, "historical_meters": 5000, "historical_batteries": 20000},
        "points": [
            {
                "index": "AO0",
                "description": "Active Power Setpoint",
                "uid": "DWMX.WMaxPct",
                "purpose": "Limit",
                "associated_index": "AI0",
                "value": 100,
                "minimum": 0,
                "maximum": 100,
                "multiplier": 0.1,
                "offset": 0,
                "units": "percent",
                "supported": true
            }
        ]
    },
    "analog_inputs": {
        "offsets": {"scada": 0, "historical_meters": 5000, "historical_batteries": 20000},
        "points": [
            {
                "index": "AI0",
                "description": "Active Power",
                "uid": "DWMX.WMaxPct.val",
                "purpose": "Monitoring",
                "value": 0,
                "minimum": 0,
                "maximum": 1000,
                "multiplier": 0.1,
                "offset": 0,
                "units": "watts",
                "supported": true,
                "event_class": 1
            }
        ]
    }
}
```

This example is derived from the unit test fixture at
`tests/unit/mesa/fixtures/test_profile.json`.

## Authoring notes

- Omit a point entirely or set `"supported": false` to exclude it. Unsupported
  points are never added to the DNP3 database.
- DNP3 indices within each section must be unique. The loader does not enforce
  this, but a duplicate index produces undefined behavior at the database level.
- `entity_number` is 1-based. A point with `"entity_number": 1` belongs to the
  first instance of its entity type.
- The `associated_index` field is only meaningful on Analog Output points. When
  a DIRECT_OPERATE is received for an AO with `associated_index`, the command
  handler mirrors the new value to the named Analog Input point. The target AI
  must be present in the database (i.e., it must be a supported point and must
  not be excluded by entity overrides).

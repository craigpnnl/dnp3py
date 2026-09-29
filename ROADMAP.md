# Roadmap

## Goal

Make the dnp3py outstation, through its dnp3.mesa module, conform to
IEEE 1815.2-2025, the DNP3 profile for distributed energy resources, on
top of IEEE 1815-2012 Level 2.

## Milestones, in order

Each milestone links to one epic issue; the epic's sub-issues are the
current work items.

1. Honest documentation. The README states exactly which Level 2 and
   1815.2 rows are met. (epic: #184)
2. Event reads by type. A read of group 2, 22 or 32 returns events of
   that group, binary input events carry time (g2v2, g2v3), and
   limited-quantity reads are honored. (epic: #185)
3. Point configuration from the profile. Event classes, supported
   functions, disabled inputs, the profile version point and deadbands
   come from the device profile. (epic: #186)
4. Confirmed event delivery. Event responses request confirmation and
   events stay buffered until confirmed. (epic: #187)
5. Counters and freezes. Freeze requests, periodic freezing and frozen
   counter events with time, per 1815.2 clause 5.6.3. (epic: #188)
6. Controls, restart and output status. Analog output status reads,
   Class 0 exclusion, cold restart, and select timeouts per output type.
   (epic: #189)
7. Alarms. Alarm groups and alarm ranges, per clause 6.2.3. (epic: #190)
8. DER functions. Curve rules, function timing and a hook for function
   behavior, per clauses 6.1.2 to 6.5. (epic: #191)
9. Conformance evidence. A device profile document and an interoperability
   loop against an independent controlling station. (epic: #192)

## Out of scope

- Physical DER behavior: the library models the protocol, not the device.
- Optional objects: device attributes (group 0), data sets (groups 85 to
  88), ASSIGN_CLASS and floating-point analogs.
- Formal certification, which is done by an independent test house.

## Following progress

Each milestone's epic issue lists its current sub-issues, and its own
progress bar reflects how many are closed. Issues labeled
`1815.2-conformance` are the whole body of this work; the `epic` label
marks the nine parent issues above.

This roadmap will change as work lands and as reviews find more. The
issue tracker is the current source of truth.

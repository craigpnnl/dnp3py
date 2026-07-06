# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed

- **BREAKING:** Replaced the MESA mesa profile format with mesa-tool's
  PicsProfile schema. `data/template/profile.json`, `load_profile`, and the
  internal `Profile`/`ProfileSection`/`ProfilePoint` model changed shape to a
  direct Python twin of `PicsProfile` (uppercase `Key`/`BO`/`BI`/`AO`/`AI`/`CTR`
  sections, named-struct equipment groups, engineering-unit analog values
  scaled to DNP3 transmission integers on load). Profiles in the old format no
  longer load. See ADR-002 (supersedes ADR-001).

### Added

- Bundled the four mesa-tool PicsProfile conformance profiles
  (`full`, `mandatory_1815`, `mandatory_1547`, `minimal_1547`) under
  `src/dnp3/mesa/data/profiles/`, plus the format's JSON schema. `full.json`
  is the CLI default.
- CTR (counter) and curve support in the mesa outstation: counter points
  register into the existing DNP3 counter database, and curve/schedule AI
  points register at their absolute indices with scaled values. Selector-driven
  curve and schedule editing (multiplexing) is deferred to a follow-up.
- `--profile-name {full,mandatory_1815,mandatory_1547,minimal_1547}` CLI flag
  to select a bundled profile by name; `--profile` still accepts an arbitrary
  path and defaults to the packaged `full.json` when neither is given.

## [0.2.0] - 2026-06-26

### Added

- MESA IEEE 1815.2 DER outstation module (`dnp3.mesa`): profile-driven
  simulator for meters, DERs, inverters, and batteries loaded from a JSON
  profile file.
- CLI entry point `python -m dnp3.mesa` with flags for profile path, listen
  address/port, DNP3 addresses, and per-entity-type count overrides.
- `create_mesa_outstation` factory function wiring profile, database, AO store,
  command handler, and TCP runner from a single `profile.json`.
- Bundled profile template at `data/template/profile.json`.

### Fixed

- `_SEQ_MASK` restored in transport segment `to_byte` for wire-output integrity.
- FIR/FIN test assertions corrected to match IEEE 1815-2012.
- Inbound multi-fragment reassembly buffer is now bounded to the configured maximum fragment size, preventing an unbounded-memory condition caused by malformed transport input.
- Event response blocks are now chunked to the fragment-size limit, matching the behavior of static responses.

## [0.1.2] - 2026-06-24

### Fixed

- Build release wheel from the tag so PyPI receives a clean PEP 440 version.

## [0.1.1] - 2026-06-24

### Fixed

- DIRECT_OPERATE: echo CROB index at qualifier-derived width; restore
  IIN.PARAMETER_ERROR on FORMAT_ERROR in control response.
- DIRECT_OPERATE echoes command objects back to master.
- WRITE g80v1 clears the restart bit correctly.
- CROB qualifier handling: close silent-failure and DoS gaps; use start/stop
  range qualifiers for static responses; parse CROB count/index by qualifier.
- AO wire-level qualifier, truncation, and count bugs (mirror of CROB fixes).
- Close three review nits: unknown AO variation handling, sentinel value, and
  event-framing 0x28 coverage.

### Changed

- Refactored restart, unsolicited, and event-framing handlers to remove
  duplication.

## [0.1.0] - 2025-12-17

### Added

- Initial release: pure Python DNP3 implementation (IEEE 1815-2012).
- Application, datalink, transport, and transport_io layers.
- Master and outstation roles with object model.
- Full pytest suite with hypothesis property tests; 99% line coverage.
- PyPI publication with hatch build backend.
- GitHub Actions CI across Python 3.11, 3.12, 3.13, 3.14 on Ubuntu and macOS.

[Unreleased]: https://github.com/craigpnnl/dnp3py/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/craigpnnl/dnp3py/compare/v0.1.2...v0.2.0
[0.1.2]: https://github.com/craigpnnl/dnp3py/compare/v0.1.1...v0.1.2
[0.1.1]: https://github.com/craigpnnl/dnp3py/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/craigpnnl/dnp3py/releases/tag/v0.1.0

# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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

- DIRECT_OPERATE echoes command objects back to master.
- WRITE g80v1 clears the restart bit correctly.

## [0.1.2] - 2026-06-23

### Fixed

- Build release wheel from the tag so PyPI receives a clean PEP 440 version.
- AO wire-level qualifier, truncation, and count bugs (mirror of CROB fixes).
- Close three review nits: unknown AO variation handling, sentinel value, and
  event-framing 0x28 coverage.

## [0.1.1] - 2026-06-23

### Fixed

- DIRECT_OPERATE: echo CROB index at qualifier-derived width; restore
  IIN.PARAMETER_ERROR on FORMAT_ERROR in control response.
- CROB qualifier handling: close silent-failure and DoS gaps; use start/stop
  range qualifiers for static responses; parse CROB count/index by qualifier.
- `_SEQ_MASK` restored in transport segment `to_byte` for wire-output integrity.
- FIR/FIN test assertions corrected to match IEEE 1815-2012.

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

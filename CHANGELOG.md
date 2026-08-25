# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

<!-- version list -->

## [Unreleased]

## [0.3.1] - 2026-08-25

### Fixed

- Master responses carrying more than one object block are no longer
  truncated to the first block. Each block is now delimited by its
  per-object size from the object registry. `parse_object_headers` is
  unchanged and still serves requests, which carry no object data.
- Master value parsers now decode the count qualifiers (`0x17`, `0x28`) that
  every event group uses, together with each object's index prefix.
  Previously the count field and the index prefixes were read as flag and
  value bytes, reporting points at wrong indices with wrong values.
- Bit-packed binary decoding is now selected by object group rather than by
  variation number alone, so binary event blocks (`g2v1`, `g11v1`) are
  decoded as one flags byte per point instead of as packed bits. Packed
  decoding is also bounded by the declared object count, so the unused high
  bits of the final byte are no longer reported as points.
- Master parsing of the float analog variations `g30v5` and `g30v6` no
  longer returns an empty list, and the timestamped event variations
  (`g2v2`, `g2v3`, `g32v3`, `g22v5`) are sized correctly.
- A single malformed object block, such as one carrying a reserved
  qualifier, no longer discards an entire otherwise-valid response.

## [0.3.0] - 2026-07-07

### Changed

- **BREAKING:** Replaced the MESA profile format with mesa-tool's
  PicsProfile schema. `data/template/profile.json`, `load_profile`, and the
  internal `Profile`/`ProfileSection`/`ProfilePoint` model changed shape to a
  direct Python twin of `PicsProfile` (uppercase `Key`/`BO`/`BI`/`AO`/`AI`/`CTR`
  sections, named-struct equipment groups, engineering-unit analog values
  scaled to DNP3 transmission integers on load). Profiles in the old format no
  longer load. See ADR-002 (supersedes ADR-001).

### Added

- Bundled the four mesa-tool PicsProfile conformance profiles
  (`full`, `mandatory_1815`, `mandatory_1547`, `minimal_1547`) under
  `src/dnp3/mesa/data/profiles/`. `full.json` is the CLI default. A
  PicsProfile JSON schema for load-time and CI validation is deferred to a
  follow-up card; the hand-rolled boundary loader in `profile.py` is the
  format's authority for now.
- CTR (counter) and curve support in the mesa outstation: counter points
  register into the existing DNP3 counter database, and curve/schedule AI
  points register at their absolute indices with scaled values. Selector-driven
  curve and schedule editing (multiplexing) is deferred to a follow-up.
- `--profile-name {full,mandatory_1815,mandatory_1547,minimal_1547}` CLI flag
  to select a bundled profile by name; `--profile` still accepts an arbitrary
  path and defaults to the packaged `full.json` when neither is given.

### Fixed

- Packaged-profile resolution now works under non-regular-install packaging
  (zipimport, zipapp) by resolving bundled profiles through
  `importlib.resources.as_file` instead of assuming a real filesystem path;
  the startup summary now prints a stable package-relative identity.
  `--profile` and `--profile-name` are now a real argparse mutually
  exclusive group.
- Counter event timestamps default to change time instead of poll time.
- Duplicate AI point indices during database construction now raise instead
  of silently deduplicating.
- `engineering_to_transmission` guards against a non-finite
  `engineering_value`.
- g22v5 counter events now carry a 48-bit timestamp.

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

[Unreleased]: https://github.com/craigpnnl/dnp3py/compare/v0.3.1...HEAD
[0.3.1]: https://github.com/craigpnnl/dnp3py/compare/v0.3.0...v0.3.1
[0.3.0]: https://github.com/craigpnnl/dnp3py/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/craigpnnl/dnp3py/compare/v0.1.2...v0.2.0
[0.1.2]: https://github.com/craigpnnl/dnp3py/compare/v0.1.1...v0.1.2
[0.1.1]: https://github.com/craigpnnl/dnp3py/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/craigpnnl/dnp3py/releases/tag/v0.1.0

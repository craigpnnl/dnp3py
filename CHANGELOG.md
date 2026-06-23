# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed

- DIRECT_OPERATE echoes command objects back to master; WRITE g80v1 clears the restart bit correctly.

## [0.1.0] - 2025-12-17

### Added

- Initial release: pure Python DNP3 implementation (IEEE 1815-2012).
- Application, datalink, transport, and transport_io layers.
- Master and outstation roles with object model.
- Full pytest suite with hypothesis property tests; 99% line coverage.
- PyPI publication with hatch build backend.
- GitHub Actions CI across Python 3.11, 3.12, 3.13, 3.14 on Ubuntu and macOS.

[Unreleased]: https://github.com/craigpnnl/dnp3py/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/craigpnnl/dnp3py/releases/tag/v0.1.0

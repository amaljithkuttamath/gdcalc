# Changelog

User-visible changes to MCDXKit (formerly gdcalc). The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and versions follow [Semantic Versioning](https://semver.org/). Each pull request with a user-visible change adds a line under `Unreleased`; a release moves those lines under its version.

## Unreleased

### Added

- CI lint and type-check job: `ruff check` (correctness rules) and `mypy`, pinned in `requirements-dev.txt`.

### Fixed

- Unused imports and a late-binding closure in equation inspection flagged by the new lint rules.

## 0.3.0

### Changed

- Renamed the project from gdcalc to MCDXKit with no compatibility aliases: the package, import, `mcdxkit` command, `MCDXKIT_*` environment variables and engine cache path all changed.
- README rewritten as a concise package front page.

## 0.2.1

### Fixed

- PyPI documentation links and package install instructions.

## 0.2.0

### Added

- First public release: GROUP report conversion to CalcpadCE `.cpd`, calculated `.html`, Mathcad `.mcdx` and `.audit.json`, with the CLI, Python SDK, local browser server, container image, contributor workflow and release pipeline.

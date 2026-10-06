# Changelog

User-visible changes to gdcalc. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and versions follow [Semantic Versioning](https://semver.org/). Each pull request with a user-visible change adds a line under `Unreleased`; a release moves those lines under its version.

## Unreleased

### Added

- CI lint and type-check job: `ruff check` (correctness rules) and `mypy`, pinned in `requirements-dev.txt`.

### Changed

- README rewritten as a concise package front page.

### Fixed

- Unused imports and a late-binding closure in equation inspection flagged by the new lint rules.

## 0.2.1

### Fixed

- PyPI documentation links and package install instructions.

## 0.2.0

### Added

- First public release: GROUP report conversion to CalcpadCE `.cpd`, calculated `.html`, Mathcad `.mcdx` and `.audit.json`, with the CLI, Python SDK, local browser server, container image, contributor workflow and release pipeline.

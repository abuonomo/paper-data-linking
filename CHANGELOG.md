# Changelog

All notable changes to this project are documented here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- Continuous integration: the unit test suite and the client build run on every pull request and push to `main` (`.github/workflows/test.yml`).
- `GET /builder/version/` reporting the package version and build commit.
- OpenAPI schema for the public API (`/builder/schema/`) with a Swagger UI.
- Community files: `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, `SECURITY.md`, issue and pull-request templates, `CITATION.cff`.

### Changed
- README: statement of need, quickstart, citation, corrected installation steps; internal design notes moved to `docs/internal/` with an index at `docs/README.md`.
- Version fields aligned (`pyproject.toml`, `client/package.json`, `CITATION.cff`).
- `pytest` collects only `tests/` and excludes integration tests by default.

### Security
- `GET /builder/public/papers/{bibcode}/pdf/` now requires authentication. It returned time-limited links to publisher-licensed PDFs to anonymous callers.

### Notes
- No changes to the extraction pipeline (prompts, catalog, grounding). Results in the companion paper correspond to v1.0.0.

## [1.0.0] - 2026-09-22

Initial public release: extraction pipeline, catalog grounding against VSO and CDAWeb/SPASE, SunPy script generation, validation interface with blinded campaign mode, public read API, deployment tooling. This is the version used for the validation campaign reported in the companion paper. Archived at https://doi.org/10.5281/zenodo.22899457.

[Unreleased]: https://github.com/abuonomo/paper-data-linking/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/abuonomo/paper-data-linking/releases/tag/v1.0.0

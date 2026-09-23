# Changelog

All notable changes to this project are documented here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses [Semantic Versioning](https://semver.org/).

## [Unreleased]

## [1.1.0] - 2026-09-23

### Added
- Continuous integration: the unit test suite and the client build run on every pull request and push to `main` (`.github/workflows/test.yml`).
- `GET /builder/version/` reporting the package version and build commit.
- OpenAPI schema for the public API (`/builder/schema/`) with a Swagger UI.
- Community files: `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, `SECURITY.md`, issue and pull-request templates, `CITATION.cff`.

### Changed
- README: statement of need, quickstart, citation, corrected installation steps; internal design notes moved to `docs/internal/` with an index at `docs/README.md`.
- Version fields aligned (`pyproject.toml`, `client/package.json`, `CITATION.cff`).
- `pytest` collects only `tests/` and excludes integration tests by default.

### Fixed
- Image builds on `main` no longer race: a newer push cancels an in-progress build, so an older commit's images can't overwrite `:latest` after a newer one.
- `GET /builder/public/papers/{bibcode}/similar/` is about 1.5–2× faster uncached (for example 5.4 s → 3.2 s; 10.2 s → 4.6 s) with identical results: the ranking query selects only paper IDs and distances instead of whole paper rows with full text. It is still seconds per uncached paper; per-paper embeddings are the planned fix.
- Browsers could keep a cached `index.html` after a deploy and run the previous release's JavaScript against the new API (seen as "Failed to load paper validation data" after the authentication change). nginx now serves the app shell with `Cache-Control: no-cache`; the content-hashed bundles are still cached.
- `GET /builder/usage_by_mission/` (behind the public usage-explorer page) got the API process killed on every call. Some extracted windows are open-ended (upper bound 9999-12-31) or reach back centuries, and the view built a day-by-mission table over that whole span (about 750 million cells in production). It now counts usages per month from October 1957 to the current month, groups in the database, and caches the result for an hour: about 1.5 s and 10 MB uncached. The response adds `resolution` and `excluded_outside_range`; `dates`, `missions` and `data` keep their shape, with dates now at month starts.

### Security
- Plain-HTTP requests are redirected to HTTPS, and responses carry `Strict-Transport-Security: max-age=31536000` (this host only). The site previously served everything, including the login form, over plain HTTP when asked. nginx now passes the load balancer's `X-Forwarded-Proto` through to Django instead of overwriting it with `http`, so API-generated links (such as pagination `next`) use `https://`.
- `GET /builder/public/papers/{bibcode}/pdf/` now requires authentication. It returned time-limited links to publisher-licensed PDFs to anonymous callers.
- `DEBUG` is off by default (was hard-coded on); set `DJANGO_DEBUG=true` for local development. Debug pages exposed the URLconf and would have exposed settings on errors.
- API routes require authentication by default (`DEFAULT_PERMISSION_CLASSES`). Paper list, paper detail (which include full text), quote search and script-parameter search were reachable anonymously because their views set no permission. Anonymous routes are now an explicit allowlist, enforced by `tests/unit/test_route_permissions.py`.
- Anonymous validation votes removed. The anonymous ID was chosen by the caller, so one client could cast unlimited votes and change the consensus status the public API filters on. Existing anonymous records are kept but no new ones can be created.
- Login attempts are rate-limited per client IP (10 per minute, 100 per day by default) on `/token/` and `/admin/login/`. Both accepted unlimited password guesses.
- The paper list, "my papers" and paper-analysis list endpoints are paginated (25 per page, `page_size` up to 200) and paper lists no longer include full text. They returned whole tables in one response (about 95k papers and 6.5 GB of text in production), so any signed-in user could take the API down with one request. Paper list search covers bibcode and title instead of full text.
- Dependencies with published security advisories updated on the request path: Django 5.2.1 → 5.2.17 (same LTS series), Django REST framework 3.16.0 → 3.18.1, djangorestframework-simplejwt 5.5.0 → 5.5.1, PyJWT 2.9.0 → 2.15.0 (with redis 5.3.0 → 5.3.1, which pinned it), requests 2.32.3 → 2.34.2, urllib3 2.4.0 → 2.8.0, sqlparse 0.5.3 → 0.6.0; client dependencies updated with non-breaking `npm audit fix`. Advisories that need major upgrades (react-pdf/pdf.js, plotly.js, react-syntax-highlighter, react-router 7) and in extraction-pipeline libraries (pypdf, unstructured, nltk, pillow, litellm) are left for 1.2 so the pipeline stays identical to 1.0.0.

### Notes
- No changes to the extraction pipeline (prompts, catalog, grounding). Results in the companion paper correspond to v1.0.0.

## [1.0.0] - 2026-09-22

Initial public release: extraction pipeline, catalog grounding against VSO and CDAWeb/SPASE, SunPy script generation, validation interface with blinded campaign mode, public read API, deployment tooling. This is the version used for the validation campaign reported in the companion paper. Archived at https://doi.org/10.5281/zenodo.22899457.

[Unreleased]: https://github.com/abuonomo/paper-data-linking/compare/v1.1.0...HEAD
[1.1.0]: https://github.com/abuonomo/paper-data-linking/compare/v1.0.0...v1.1.0
[1.0.0]: https://github.com/abuonomo/paper-data-linking/releases/tag/v1.0.0

# Contributing to paper-data-linking

Thanks for your interest. This project is maintained by NASA's Heliophysics Digital Resource Library (HDRL) and developed in the open. Bug reports, documentation fixes, new data sources, and corrections to extracted data references are all welcome.

## Ways to contribute

- **Report a bug or request a feature** — open an issue using the templates. Include the output of `GET /builder/version/` from the instance you are using.
- **Correct a data reference** — if a paper→data link served by the public API is wrong, open an issue with the bibcode, the instrument, and what the paper actually says. Corrections are applied through the validation interface by the curation team.
- **Add a data source** — see [docs/EXTENDING_DATA_SOURCES.md](docs/EXTENDING_DATA_SOURCES.md) for the registry pattern (normalizers, script generator, optional analyzers).
- **Improve documentation** — small fixes as a direct PR; larger reorganizations via an issue first.

## A note on the extraction pipeline

The prompts, instrument catalog, and grounding logic in `paper_data_linking/` determine what the system extracts, and the precision numbers in the companion paper were measured on a specific tagged version (`v1.0.0`). Changes there are *benchmark-affecting*: please open an issue describing the change and the evidence for it before sending a PR, so it can be evaluated against the test set rather than merged blind. Everything else (API, UI, deployment, docs, tests) is ordinary.

## Development setup

Requirements: Python 3.11 with [`uv`](https://docs.astral.sh/uv/), Node 20, Docker (for Postgres/Redis), and `poppler`/`tesseract` for PDF text extraction.

```bash
git clone https://github.com/abuonomo/paper-data-linking.git
cd paper-data-linking
uv python install 3.11
uv sync
cp .env_example .env          # then fill in the values below
docker compose up -d postgres redis
cd api && uv run python manage.py migrate && uv run python manage.py runserver
```

In another terminal: `cd client && npm ci && npm run dev`.

Environment variables the backend reads (`.env` at the repository root):

| Variable | Purpose |
|---|---|
| `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_HOST`, `DB_PORT` | Postgres (pgvector) connection; `docker-compose.yaml` creates the database from the same values |
| `DJANGO_SECRET_KEY` | Django secret |
| `RUNNING_LOCALLY` | `true` outside Docker so the API connects to `localhost` |
| `BASE_URL` | public URL of the API (e.g. `http://localhost:8000`); used to build absolute links in exports |
| `ADS_TOKEN` | NASA ADS API token (paper metadata) |
| `OPENAI_API_KEY` | OpenAI key (embeddings; optionally the extraction model) |
| AWS credentials / `AWS_PROFILE` | only if using Bedrock-hosted models |
| `ALLOWED_HOSTS`, `CORS_ALLOWED_ORIGINS`, `CSRF_TRUSTED_ORIGINS` | deployment hostnames |

## Running tests

```bash
uv run pytest                  # unit suite; needs Postgres on localhost (see DB_* above)
uv run pytest -m integration   # calls real LLM/AWS endpoints — costs money, needs credentials
cd client && npm run lint && npm run build
```

Pytest uses `api/paper_analyzer_app/settings_test.py` (eager Celery, in-memory cache, no Redis) and creates a throwaway `test_<DB_NAME>` database. CI runs the same unit suite and the client build on every pull request (`.github/workflows/test.yml`).

## Code style

- Python: `uv run pylint paper_data_linking api/vso_query_builder` and `uv run bandit -r paper_data_linking api -q` before opening a PR. Absolute imports; Django app layout as in `api/vso_query_builder/`.
- JavaScript/TypeScript: `npm run lint` (currently covers `.ts/.tsx`; `.jsx` files are not linted yet).
- Keep changes focused; one topic per pull request.

## Pull requests

1. Branch from `main`.
2. Fill in the pull-request template — in particular whether the change touches the extraction pipeline and whether deployment needs a new environment variable or migration.
3. CI must pass.
4. A maintainer merges. **Merging to `main` deploys to the production instance automatically**, so merges are done by maintainers after review.

## Getting help

Open an issue, or email anthony.r.buonomo@nasa.gov. For security issues, see [SECURITY.md](SECURITY.md).

## License

By contributing you agree that your contributions are licensed under the MIT License (see [LICENSE](LICENSE) and [NOTICE](NOTICE)).

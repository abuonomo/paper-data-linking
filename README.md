# paper-data-linking

[![tests](https://github.com/abuonomo/paper-data-linking/actions/workflows/test.yml/badge.svg)](https://github.com/abuonomo/paper-data-linking/actions/workflows/test.yml)
[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.22899457.svg)](https://doi.org/10.5281/zenodo.22899457)

**A scientific research tool that connects public heliophysics literature to public data archives.**

`paper-data-linking` reads heliophysics research papers and extracts the data references they contain — which instruments, observatories, and time ranges a paper analyzed — then links those references to the corresponding public data archives so the underlying datasets can be located and reused. It is built to support open, reproducible science.

## Statement of need

Heliophysics papers rarely cite the observational data they analyze in machine-readable form: which instruments, which observatories, and which time windows are stated in prose, and no structured record connects a paper to the archives that hold its data. Data providers therefore cannot see how archival data is used, and researchers cannot search the literature by data. Journal data-availability statements and author-supplied facility keywords cover only a minority of actual usage. `paper-data-linking` extracts these references from full text, matches them to catalog entries in VSO and CDAWeb/SPASE, and produces a runnable query for each, with verbatim supporting quotes located in the source PDF so every reference can be checked. It includes a blinded human-review workflow for measuring extraction precision and a public API for querying validated references. It is intended for mission data stewards, archive operators, informaticians, and researchers doing data-driven literature discovery.

> **Maintained at [github.com/abuonomo/paper-data-linking](https://github.com/abuonomo/paper-data-linking)** — active development happens there. Developed at the University of Maryland, Baltimore County and released under the MIT License (© UMBC; see [LICENSE](LICENSE) and [NOTICE](NOTICE)).

## Scope and intended use

This is a literature-and-metadata tool. To be explicit about what it is and is not:

- It works only with **public scientific literature** and **public data archives**. The external services it queries are:
  - [NASA ADS](https://ui.adsabs.harvard.edu/) (Astrophysics Data System) — public paper metadata.
  - [Virtual Solar Observatory (VSO)](https://sdac.virtualsolar.org/) — public solar instrument data.
  - [CDAWeb](https://cdaweb.gsfc.nasa.gov/) (Coordinated Data Analysis Web) — public heliophysics datasets.
  - [Heliophysics Data Portal / HPDE](https://heliophysicsdata.gsfc.nasa.gov/) — public SPASE dataset metadata.
  - Commercial large-language-model inference APIs (e.g. OpenAI, AWS Bedrock) used purely for text extraction. No proprietary or restricted data is sent to them beyond the public paper text being analyzed.
- It does **not** control spacecraft, command instruments, or perform any flight-dynamics, navigation, or mission-operations function.
- It does **not** process classified information, Controlled Unclassified Information (CUI), or export-controlled (ITAR/EAR) technical data.
- It does not download or redistribute datasets. It identifies references and can generate open data-fetch scripts (using [SunPy](https://sunpy.org/)'s `Fido` client) that an end user runs against the public archives themselves.

In short: it reads public papers, figures out which public datasets they used, and helps you find those datasets.

## How it works

The pipeline runs in stages:

1. **Ingestion** — a paper is added by PDF upload or by bibcode; text is extracted (PyMuPDF, with OCR fallback) and metadata is enriched from NASA ADS.
2. **Analysis** — a language model extracts free-text descriptions of the instruments, observatories, and observation periods the paper analyzed.
3. **Structuring & normalization** — the free text is converted to structured JSON and normalized to canonical instruments, observatories, time ranges, wavelengths, and cadences.
4. **Linking** — normalized records are matched to VSO / CDAWeb datasets and stored as `DatasetUsage` records with supporting quotes and page references.
5. **Script generation** — deterministic, runnable Python (SunPy `Fido`) scripts are generated so a user can fetch the referenced public data.

### Architecture

- **Backend** (`api/`): Django + Django REST Framework, PostgreSQL with `pgvector`, Redis + Celery task queue.
- **Core library** (`paper_data_linking/`): linkers (`vso/`, `cdaweb/`, `general/`), analyzers, PDF processing, LLM clients (via `litellm`), and Pydantic-based configuration.
- **Frontend** (`client/`): React + TypeScript (Vite), served via nginx.

A public, read-only API exposes validated results for querying by mission, instrument, and time range — see [docs/PUBLIC_API.md](docs/PUBLIC_API.md).

## Installation

You will need Docker and Docker Compose.

1. Create an environment file: `cp .env_example .env`, then fill it in. Required: `DB_NAME`, `DB_USER`, `DB_PASSWORD` (Postgres is created from these), `DJANGO_SECRET_KEY`, `ADS_TOKEN` (NASA ADS API), and an LLM key such as `OPENAI_API_KEY`. `BASE_URL` should be the public URL of the API (used in exports). See [CONTRIBUTING.md](CONTRIBUTING.md) for the full list.
2. Create a client environment file at `client/.env`:
   ```
   VITE_BASE_URL=localhost:8000
   VITE_BASE_PROTOCOL=http
   ```
3. Set up the reverse-proxy password: from the repository root run `htpasswd -c .htpasswd <username>` and choose a password (`docker-compose.yaml` mounts this file into the nginx container).
4. From the repository root: `docker compose build` (this may take a while).
5. Start the services: `docker compose up`. Then open `localhost:80` and sign in with the credentials from step 3.

### Local development with `uv`

This project uses [`uv`](https://docs.astral.sh/uv/) for Python dependency management.

```bash
uv python install 3.11
uv venv -p 3.11
source .venv/bin/activate
uv sync
```

Run the unit test suite with `uv run pytest` (needs a local Postgres with pgvector, e.g. `docker compose up -d postgres`; see [CONTRIBUTING.md](CONTRIBUTING.md) for the environment variables). Integration tests that call real LLM services are opt-in: `uv run pytest -m integration`. The same suite runs in CI on every pull request.

## Quickstart

**In the web interface.** Sign in, add a paper by ADS bibcode or PDF upload, and press **Analyze**. Within a few minutes the paper's page lists each extracted data reference with its supporting quotes highlighted in the PDF, its catalog match, and a generated SunPy script. Reviewers mark each reference correct or incorrect; validated references become visible through the public API.

**From the public API** (no account needed; a hosted instance is at `https://paper-data.helioanalytics.io`). Which data does a paper use?

```bash
curl 'https://paper-data.helioanalytics.io/builder/public/papers/2023ApJ...952L..13G/validated-usages/'
```

Which papers used SOHO/LASCO data between 2020 and 2023?

```bash
curl 'https://paper-data.helioanalytics.io/builder/public/papers/validated/?missions=SOHO&instruments=LASCO&start_date=2020-01-01&end_date=2023-12-31&page_size=3&include=1'
```

Each usage record carries the instrument, observatory, observation window, the verbatim quotes that support it, and a `python_snippet` — a self-contained SunPy `Fido` query for that data, for example:

```python
from sunpy.net import Fido, attrs as a

result = Fido.search(
    a.Time("2022-11-12 00:00", "2022-11-13 00:00"),
    a.Source("SOHO"),
    a.Instrument("LASCO"),
)
files = Fido.fetch(result)
```

The full endpoint reference, including the CSV export, is in [docs/PUBLIC_API.md](docs/PUBLIC_API.md); a machine-readable schema is served at `/builder/schema/`.

## Usage

Upload a PDF in the frontend and press **Analyze**, or ingest validated dataset usages from merged pull requests in a public GitHub repository:

```bash
cd api
python manage.py ingest_github_validations --since 2024-01-01T00:00:00Z --limit 50
```

This command runs `bandit` on each candidate script before any execution and runs scripts with `Fido.search`/`Fido.fetch` mocked, so no network access or data fetching occurs during ingestion. See `--dry-run --debug` for a preview of actions.

### Phenomena enrichment (intentional-only)

Phenomenon extraction and `PhenomenonMention` creation **do not run as part of
the standard analysis pipeline**. Phenomena are produced only when explicitly
triggered, for a chosen set of papers, by either of two equivalent entry
points:

- **Django admin**: select `PaperAnalysis` rows → action **"Run phenomena
  enrichment (extract + upsert mentions)"**.
- **Management command**:

  ```bash
  cd api
  python manage.py run_phenomena_enrichment --config <configuration_name>
  # optional flags:
  #   --only-grounded    only papers with >=1 grounded instrument
  #                      (skips off-topic/ungrounded papers entirely)
  #   --papers ID [ID..] restrict to specific paper ids
  #   --sync             run inline instead of via the celery cpu queue
  ```

Per paper, enrichment (1) runs the phenomenon-extraction LLM call for each
data-collection period that has a physical observable and no stored phenomenon
result yet, (2) merges the results into `normalized_instrument_details`, and
(3) upserts `PhenomenonMention` records (with bounded PDF-coordinate lookup)
for the phenomena-validation UI. It is **idempotent and re-runnable**:
already-extracted periods are skipped and mentions are created at most once,
so re-running over the same papers is safe and costs nothing extra beyond the
skip checks. Papers must have completed normalization first (the command
selects only analyses with `normalized_instrument_details`).

Typical workflow after a batch/corpus run: run the command over that run's
`configuration_name` (with `--only-grounded` recommended for large corpora),
wait for the celery `cpu` queue to drain, then review in the
phenomena-validation UI.

## Deployment

The repository ships Docker Compose files (`docker-compose.yaml` and a production overlay `docker-compose.prod.yaml`) suitable for a single-host deployment behind nginx. In a typical setup, a CI pipeline builds the `api` and `client` images, pushes them to a container registry, and a deploy step pulls the latest images on the host:

```bash
docker compose -f docker-compose.yaml -f docker-compose.prod.yaml pull
docker compose -f docker-compose.yaml -f docker-compose.prod.yaml up -d
```

Configure your own registry and host by editing the image references in `docker-compose.prod.yaml` and the CI configuration. Application containers run as a non-root user (UID/GID 1000); align bind-mount ownership accordingly.

PDF storage can optionally use S3 by setting `USE_S3=true` and the related `AWS_STORAGE_BUCKET_NAME` / `AWS_S3_REGION_NAME` variables; it defaults to the local filesystem.

## How CDAWeb selection works

The system processes CDAWeb datasets that carry SPASE links to HPDE representations (roughly 1,921 of 2,867 datasets), because those links are the reliable way to determine the associated instruments.

## Documentation

- [docs/README.md](docs/README.md) — index of all documentation
- [docs/PUBLIC_API.md](docs/PUBLIC_API.md) — public API reference
- [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) — production deployment
- [docs/EXTENDING_DATA_SOURCES.md](docs/EXTENDING_DATA_SOURCES.md) — adding a data archive
- [CHANGELOG.md](CHANGELOG.md)

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for development setup, the test suite, and the pull-request process — including the rule that changes to the extraction pipeline (prompts, catalog, grounding) need an issue with evidence first, because published precision numbers are pinned to a tagged version. Bug reports and feature requests use the [issue templates](https://github.com/abuonomo/paper-data-linking/issues/new/choose). This project follows the [Contributor Covenant](CODE_OF_CONDUCT.md); security issues go through [SECURITY.md](SECURITY.md).

## Citation

If you use this software, please cite it. The metadata is in [CITATION.cff](CITATION.cff) (GitHub's "Cite this repository" button renders it); the archived release is on Zenodo:

```bibtex
@software{paper_data_linking,
  author  = {Buonomo, Anthony R. and Scharnikow, Aidan},
  title   = {paper-data-linking: extracting machine-readable data references from the heliophysics literature},
  year    = {2026},
  publisher = {Zenodo},
  doi     = {10.5281/zenodo.22899457},
  url     = {https://github.com/abuonomo/paper-data-linking}
}
```

The results in the companion validation paper were produced with **v1.0.0** (commit `2ef517d`); a paper citation will be added when it is available.

## License & Copyright

Released under the **MIT License** — see [LICENSE](LICENSE) and [NOTICE](NOTICE).

> **Copyright (c) 2026 University of Maryland, Baltimore County (UMBC)**

Developed at UMBC under NASA cooperative agreement 80NSSC21M0180 (GPHI/PHaSER),
in support of NASA's open-science policy (SPD-41a). Pursuant to the NASA Grant
and Cooperative Agreement Terms "Rights in Data" clause, UMBC retains copyright
and the U.S. Government retains a paid-up, nonexclusive, irrevocable worldwide
license to the software. See [NOTICE](NOTICE) for details.

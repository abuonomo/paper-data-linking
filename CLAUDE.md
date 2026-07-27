# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Architecture Overview

This is a Django-based web application for analyzing heliophysics research papers and extracting data references, particularly focused on identifying usage of solar and heliospheric observatory instruments. The system consists of a Django API backend, React frontend, PostgreSQL database with pgvector extension, Redis for caching and Celery task queue, and associated services.

### Core Components

**Django API** (`api/`): Main Django application with two primary apps:
- `paper_analyzer_app/`: Core Django configuration (settings, URLs, ASGI/WSGI)
- `vso_query_builder/`: Main business logic including models, admin interface, and Celery tasks

**Paper Data Linking Library** (`paper_data_linking/`): Core analysis library containing:
- `linkers/`: Data linking implementations (normalizers, structure analyzers, instrument grounder)
- `analyzers/`: Script generation for dataset usages (VSO, CDAWeb)
- `processing/`: PDF text extraction and processing utilities
- `config/`: Centralized configuration using Pydantic settings

**React Frontend** (`client/`): TypeScript/React application served via nginx

### Data Flow Architecture

1. **Paper Ingestion**: Papers (PDFs) uploaded → text extraction → `Paper` model
2. **Analysis Pipeline**: `PaperAnalysis` created → instrument details extracted from paper text
3. **Structure Analysis**: Instrument details text → structured JSON format using `analyze_paper_instruments_structure`
4. **Normalization**: Structured instrument data → normalized values using `normalize_structured_instrument_details`
5. **Dataset Usage Creation**: Normalized data → `DatasetUsage` records
6. **Deterministic Script Generation**: `DatasetUsage` records → executable Python scripts generated deterministically

## Common Development Commands

### Docker Operations
```bash
# Build and start all services
docker compose up -d --build

# View logs for specific service
docker compose logs -f api
docker compose logs -f celery

# Stop services
docker compose down
```

### Django Management
```bash
# Generate migrations — ALWAYS use this after changing models, never hand-write migration files.
# Run inside the container so Django uses the correct DEFAULT_AUTO_FIELD and installed apps.
docker compose exec api python manage.py makemigrations

# Verify no model changes are missing a migration
docker compose exec api python manage.py makemigrations --check

# Apply migrations
docker compose exec api python manage.py migrate

# Create superuser
docker compose exec api python manage.py createsuperuser

# Django shell
docker compose exec api python manage.py shell
```

### Development Environment Setup
```bash
# Install uv (if not already installed)
curl -LsSf https://astral.sh/uv/install.sh | sh

# Create virtual environment
uv venv -p 3.11

# Activate environment  
source .venv/bin/activate

# Install dependencies
uv sync
```

### Testing
```bash
# Run all tests
pytest

# Run specific test files
pytest tests/test_pdf_processing.py
pytest tests/vso/test_vso_validator.py
```

## Key Models and Relationships

**Core Models**:
- `Paper`: Research papers with PDFs and extracted text
- `PaperAnalysis`: Analysis results including instrument details and support quotes
- `DatasetUsage`: Normalized records of instrument/observatory usage

**Registry Models**:
- `DataSource`, `Observatory`, `Instrument`: Canonical data source definitions

## Celery Task Categories

**Text Extraction**: `extract_paper_text_task`
**Paper Analysis**: `analyze_paper_task`, `analyze_paper_instruments_structure`
**Normalization**: `normalize_structured_instrument_details`, `run_normalized_workflow_chain`
**Dataset Usage Analysis**: `analyze_dataset_usage`, `analyze_paper_dataset_usages`

## Admin Interface Workflow

The Django admin provides the primary interface for managing the analysis pipeline:

1. **Upload Papers**: Create `Paper` records, upload PDFs
2. **Extract Text**: Use "Extract text from PDFs" admin action
3. **Run Analysis**: Use "Run paper analysis" to create `PaperAnalysis`
4. **Structure Analysis**: Use "Run structure analysis" to create structured JSON from instrument details
5. **Normalize Data**: Use normalization actions to create normalized instrument/time data
6. **Create Dataset Usages**: Normalized data automatically creates `DatasetUsage` records
7. **Generate Scripts**: Deterministically generate Python scripts from `DatasetUsage` records
8. **Review Results**: Use admin filters to find successful/failed analyses

## Configuration

Configuration is centralized in `paper_data_linking/config/settings.py` using Pydantic:
- Environment variables loaded from `.env` file
- LLM model configurations
- API keys and tokens
- File paths and directories

## Database Schema Notes

- Uses PostgreSQL with pgvector extension for embeddings
- Time ranges stored as PostgreSQL `DateTimeTZRange` types
- JSON fields used extensively for storing analysis metadata

## Testing Strategy

- Unit tests in `tests/` directory
- PDF processing tests for text extraction
- VSO validator tests for data source validation
- Use `pytest-mock` for mocking external dependencies

## Sandbox Environment

If `.sandbox/bootstrap.sh` exists, you are running inside a sandbox. Services run natively (no Docker). Before doing any work, you MUST bootstrap:

```bash
./.sandbox/bootstrap.sh
```

This starts PostgreSQL + Redis, restores the database, installs Python deps via `uv sync`, runs migrations, and launches the Django dev server + Celery.

After bootstrapping, services are available at:
- API: http://localhost:8000
- Admin: http://localhost:8000/admin
- Flower: http://localhost:5555
- Postgres: localhost:5432
- Redis: localhost:6379

To stop services: `./.sandbox/stop.sh`

Logs are at `.sandbox/logs/` (api.log, celery.log, flower.log).

You have full autonomy in a sandbox — install packages, run destructive commands, modify any files. The environment is fully isolated. Use `uv run` to run Python commands (e.g., `uv run python manage.py shell`).

**Important**: The `paper-data-linking/` directory is also mounted read-only — this is solely to support the git worktree link (`.git` file). Do NOT read or modify files there. Your working directory is the worktree root where this CLAUDE.md lives.


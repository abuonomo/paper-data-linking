# bibcode_collection

Collect heliophysics bibcodes from ADS and download open-access PDFs.

## Setup

```bash
uv sync --extra bibcollect
```

Requires an `ADS_TOKEN` in `.env` at the repo root.

## Experimental filtering

There is also an experimental heliophysics classification pass for trimming a
large manifest before download/import. This is not part of the default pipeline
and should be treated as an analyst workflow, not a production requirement.

Install the extra dependencies with:

```bash
uv sync --extra bibcollect --extra classify
```

Scripts:

```bash
# Rule-based keyword/journal pass using ADS abstracts
PYTHONPATH=. uv run --extra classify python scripts/classify_helio.py data/pipeline-final/manifest.jsonl \
    -o data/pipeline-final/helio_classification.jsonl \
    --checkpoint data/pipeline-final/abstracts_checkpoint.jsonl

# Optional ML follow-up: TF-IDF + logistic regression trained on high-confidence labels
PYTHONPATH=. uv run --extra classify python scripts/train_helio_classifier.py \
    --abstracts data/pipeline-final/abstracts_checkpoint.jsonl \
    --classifications data/pipeline-final/helio_classification.jsonl \
    --sources data/raw/bibcodes/helio_merged.jsonl \
    -o data/pipeline-final/ml_classification.jsonl
```

Outputs are JSONL files intended for inspection and downstream filtering. They
do not currently plug directly into the importer or downloader.

## Pipeline

### 1. Collect bibcodes

Query ADS using multiple strategies (keywords, journals, mission bibgroups, arXiv classes, curated libraries). Outputs one-bibcode-per-line text files, including per-library files for provenance tracking.

```bash
# Dry-run: see counts per strategy without fetching
uv run python -m bibcode_collection.collector --dry-run

# Full collection
uv run python -m bibcode_collection.collector

# Check output
wc -l data/raw/bibcodes/helio/*.txt
```

Strategies are configured in `configs/default.yaml`.

### 2. Merge and deduplicate

Produces JSONL with source provenance tracking: `{"bibcode": "...", "sources": ["helio_keywords", "SOHO"]}`.

```bash
uv run python -m bibcode_collection.merge data/raw/bibcodes/helio/*.txt \
    -o data/raw/bibcodes/helio_merged.jsonl
```

### 3. Build OA manifest

Resolve bibcodes to DOIs and arXiv IDs via ADS, then look up open-access status via Unpaywall. Produces a JSONL manifest with PDF URLs. Accepts both plain text and JSONL input (sources are passed through).

```bash
uv run python -m bibcode_collection.oa_lookup data/raw/bibcodes/helio_merged.jsonl \
    -o data/raw/bibcodes/helio_manifest.jsonl
```

### 4. Download PDFs

Download PDFs using a multi-tier fallback strategy:

1. Direct publisher PDF (via Unpaywall `best_oa_location`)
2. Alternate publisher URLs (other Unpaywall `oa_locations`)
3. arXiv preprint (if the paper has an arXiv ID)
4. Playwright headless browser (opt-in, rarely helps)

#### Local mode (for testing)

```bash
uv run python -m bibcode_collection.pdf_downloader data/raw/bibcodes/helio_manifest.jsonl \
    -o data/raw/bibcodes/helio_pdfs/

# Limit to first N papers
uv run python -m bibcode_collection.pdf_downloader data/raw/bibcodes/helio_manifest.jsonl \
    -o data/raw/bibcodes/helio_pdfs/ --limit 100
```

#### S3 mode (for production runs on EC2)

```bash
uv run python -m bibcode_collection.pdf_downloader data/raw/bibcodes/helio_manifest.jsonl \
    --s3-bucket your-s3-bucket --s3-prefix papers \
    --aws-profile bedrock \
    --exclude-bibcodes existing_bibcodes.txt
```

Options:
- `--s3-bucket`: Upload PDFs to S3 instead of local disk
- `--s3-prefix`: S3 key prefix (default: `papers`)
- `--aws-profile`: AWS profile name (default: env/instance role)
- `--exclude-bibcodes`: Text file of bibcodes to skip (one per line)

### 5. Import into prod database

After PDFs are in S3, create Paper records on the prod server:

```bash
# Export existing bibcodes from prod (to avoid re-downloading)
python manage.py export_bibcodes > existing_bibcodes.txt

# Preview what would be imported
python manage.py import_from_manifest manifest.jsonl --s3-prefix papers --auto-tag --dry-run

# Import for real, with auto-tagging
python manage.py import_from_manifest manifest.jsonl --s3-prefix papers --auto-tag
```

The `--auto-tag` flag reads the `sources` field from the manifest and converts them to Paper tags (e.g., `["helio", "SOHO", "helio_keywords"]`).

## Full EC2 workflow

```bash
# On prod: export existing bibcodes
python manage.py export_bibcodes > existing_bibcodes.txt
scp existing_bibcodes.txt ec2-user@<ec2-ip>:/tmp/

# On EC2 (in tmux):
python -m bibcode_collection.collector                                  # ~10 min
python -m bibcode_collection.merge data/raw/bibcodes/helio/*.txt \
    -o /tmp/merged.jsonl
python -m bibcode_collection.oa_lookup /tmp/merged.jsonl \
    -o /tmp/manifest.jsonl                                              # ~5 hrs
python -m bibcode_collection.pdf_downloader /tmp/manifest.jsonl \
    --s3-bucket your-s3-bucket --s3-prefix papers \
    --aws-profile bedrock \
    --exclude-bibcodes /tmp/existing_bibcodes.txt                       # ~4-8 days

# On prod: import new papers
python manage.py import_from_manifest /tmp/manifest.jsonl --s3-prefix papers --auto-tag
```

## Estimates

Based on a dry-run (Feb 2026) and test downloads:

| Metric | Estimate |
|---|---|
| Raw bibcodes (all strategies, with overlap) | ~306k |
| Unique bibcodes after dedup | ~120-170k |
| With DOIs | ~85% |
| Open access (Unpaywall) | ~65% of those with DOIs |
| Downloadable PDFs | **50-70k** |

### Time

| Phase | Estimate |
|---|---|
| Bibcode collection | ~10 min |
| OA lookup (ADS + Unpaywall) | ~4-5 hours |
| PDF download | ~4-8 days |

The download step is resumable (`--skip-existing` is on by default, including S3 mode).

### Disk space

| Item | Size |
|---|---|
| Bibcode text files + manifest | ~80 MB |
| PDFs (~60-70k at ~1.5 MB avg) | **~90-110 GB** |

In S3 mode, local disk usage is minimal (only temp files during download).

## Publisher access notes

Not all OA papers are directly downloadable. Some publishers block programmatic access:

- **Works**: Springer (SoPh, LRSP), EDP Sciences (A&A), Frontiers, arXiv, institutional repos
- **Blocked**: IOP (ApJ, ApJS, ApJL) uses Radware Bot Manager + hCaptcha; OUP (MNRAS) returns 403; AGU/Wiley (JGRA, GeoRL, SpWea) similar

The arXiv fallback recovers many blocked papers (~41% of ApJ, ~44% of MNRAS have arXiv preprints). AGU journals have low arXiv coverage (~2-7%), so those remain the main gap.

"""Resolve bibcodes to open-access PDF URLs via ADS (DOI) + OpenAlex.

Accepts either:
  - Plain text input (one bibcode per line)
  - JSONL input from merge.py ({"bibcode": "...", "sources": [...]})

When JSONL input is used, the `sources` field is passed through to the manifest.

Resume support: both DOI resolution and OA lookups are checkpointed.
Restarting with the same output file skips already-completed work.
"""

import json
import logging
import time
from pathlib import Path

import requests
from tqdm import tqdm

from .ads_client import ADSClient

logger = logging.getLogger(__name__)

OPENALEX_BASE = "https://api.openalex.org/works"
OPENALEX_BATCH_SIZE = 50  # max DOIs per request (OpenAlex OR filter limit)


def _extract_arxiv_id(identifiers: list[str]) -> str | None:
    """Extract arXiv ID from ADS identifier list (e.g. 'arXiv:2303.15998')."""
    for ident in identifiers:
        if ident.startswith("arXiv:"):
            return ident[6:]  # strip "arXiv:" prefix
    return None


def _normalize_doi(doi: str) -> str:
    """Normalize a DOI to bare lowercase form (strip https://doi.org/ prefix)."""
    if doi.startswith("https://doi.org/"):
        doi = doi[len("https://doi.org/"):]
    elif doi.startswith("http://doi.org/"):
        doi = doi[len("http://doi.org/"):]
    return doi.lower()


def load_input(input_file: Path) -> list[dict]:
    """Load bibcodes from either plain text or JSONL.

    Returns list of dicts with at least {"bibcode": "..."}.
    JSONL records may also include "sources".
    """
    records = []
    text = input_file.read_text()
    first_line = text.strip().split("\n", 1)[0].strip()

    if first_line.startswith("{"):
        # JSONL format
        for line in text.splitlines():
            line = line.strip()
            if line:
                records.append(json.loads(line))
    else:
        # Plain text format
        for line in text.splitlines():
            bibcode = line.strip()
            if bibcode:
                records.append({"bibcode": bibcode})

    return records


def _load_checkpoint(checkpoint_file: Path) -> dict[str, dict]:
    """Load DOI resolution checkpoint: {bibcode: {"doi": ..., "arxiv_id": ...}}."""
    if not checkpoint_file.exists():
        return {}
    result = {}
    for line in checkpoint_file.read_text().splitlines():
        line = line.strip()
        if line:
            record = json.loads(line)
            result[record["bibcode"]] = {
                "doi": record.get("doi"),
                "arxiv_id": record.get("arxiv_id"),
            }
    return result


def resolve_bibcodes(
    client: ADSClient,
    bibcodes: list[str],
    batch_size: int = 2000,
    checkpoint_file: Path | None = None,
) -> dict[str, dict]:
    """Batch-resolve bibcodes to DOIs and arXiv IDs via ADS bigquery endpoint.

    Uses the bigquery endpoint (POST with bibcode list) to avoid URL length limits.
    If checkpoint_file is provided, resolved bibcodes are appended incrementally
    and already-resolved bibcodes are skipped on resume.

    Returns {bibcode: {"doi": str|None, "arxiv_id": str|None}}.
    """
    # Load any existing checkpoint
    result: dict[str, dict] = {}
    if checkpoint_file:
        result = _load_checkpoint(checkpoint_file)
        if result:
            logger.info(f"  Resuming: {len(result):,} bibcodes already resolved")

    # Filter out already-resolved bibcodes
    remaining = [b for b in bibcodes if b not in result]
    if not remaining:
        logger.info("  All bibcodes already resolved (checkpoint)")
        return result

    logger.info(f"  Resolving {len(remaining):,} remaining bibcodes...")

    # Open checkpoint file for appending
    ckpt_fh = open(checkpoint_file, "a") if checkpoint_file else None

    try:
        for i in range(0, len(remaining), batch_size):
            batch = remaining[i : i + batch_size]
            docs = client.bigquery(batch, fields=["bibcode", "doi", "identifier"])
            found = {}
            for d in docs:
                doi = (d.get("doi") or [None])[0]
                arxiv_id = _extract_arxiv_id(d.get("identifier") or [])
                found[d["bibcode"]] = {"doi": doi, "arxiv_id": arxiv_id}

            for b in batch:
                info = found.get(b, {"doi": None, "arxiv_id": None})
                result[b] = info
                if ckpt_fh:
                    ckpt_fh.write(json.dumps({"bibcode": b, **info}) + "\n")

            if ckpt_fh:
                ckpt_fh.flush()

            done = len(result)
            total = len(bibcodes)
            logger.info(f"  resolved {done:,}/{total:,}")

            time.sleep(client.delay)
    finally:
        if ckpt_fh:
            ckpt_fh.close()

    return result


def openalex_batch_lookup(dois: list[str], email: str) -> dict[str, dict]:
    """Look up a batch of DOIs on OpenAlex.

    Args:
        dois: List of bare DOIs (e.g. "10.1234/foo").
        email: Contact email for OpenAlex polite pool.

    Returns {normalized_doi: {"is_oa", "pdf_url", "alt_pdf_urls", "landing_url", "host", "version"}}.
    """
    if not dois:
        return {}

    # Build pipe-separated DOI filter
    doi_filter = "|".join(dois)
    resp = requests.get(
        OPENALEX_BASE,
        params={
            "filter": f"doi:{doi_filter}",
            "per_page": len(dois),
            "select": "doi,open_access,best_oa_location,locations",
            "mailto": email,
        },
    )
    resp.raise_for_status()

    results = {}
    for work in resp.json().get("results", []):
        raw_doi = work.get("doi") or ""
        doi = _normalize_doi(raw_doi)
        if not doi:
            continue

        oa = work.get("open_access") or {}
        best = work.get("best_oa_location") or {}

        # Collect alternate PDF URLs from other locations
        alt_pdf_urls = []
        best_pdf = best.get("pdf_url")
        for loc in work.get("locations") or []:
            url = loc.get("pdf_url")
            if url and url != best_pdf:
                alt_pdf_urls.append(url)

        results[doi] = {
            "is_oa": oa.get("is_oa", False),
            "pdf_url": best_pdf,
            "alt_pdf_urls": alt_pdf_urls,
            "landing_url": best.get("landing_page_url"),
            "host": (best.get("source") or {}).get("type"),
            "version": best.get("version"),
        }

    return results


def _load_existing_manifest(output_file: Path) -> set[str]:
    """Load bibcodes already in the manifest file (for resume)."""
    if not output_file.exists():
        return set()
    done = set()
    for line in output_file.read_text().splitlines():
        line = line.strip()
        if line:
            done.add(json.loads(line)["bibcode"])
    return done


_NO_OA = {"is_oa": False, "pdf_url": None, "alt_pdf_urls": [], "landing_url": None, "host": None, "version": None}


def build_manifest(
    input_records: list[dict],
    email: str,
    output_file: Path,
    ads_client: ADSClient | None = None,
    delay: float = 0.1,
) -> dict:
    """Build a JSONL manifest: bibcode, doi, is_oa, pdf_url, host, version, sources.

    input_records: list of dicts with at least {"bibcode": "..."} and optionally {"sources": [...]}.

    Resume support: if output_file already exists, bibcodes already in it are skipped.
    A DOI resolution checkpoint is stored alongside the output file.

    Returns summary stats dict.
    """
    if ads_client is None:
        ads_client = ADSClient()

    bibcodes = [r["bibcode"] for r in input_records]
    # Build a lookup for extra fields (sources) from input
    extra_fields = {r["bibcode"]: {k: v for k, v in r.items() if k != "bibcode"} for r in input_records}

    # Step 1: Resolve DOIs + arXiv IDs (with checkpoint)
    checkpoint_file = output_file.with_suffix(".doi_checkpoint.jsonl")
    logger.info(f"Resolving DOIs for {len(bibcodes):,} bibcodes...")
    bibcode_info = resolve_bibcodes(ads_client, bibcodes, checkpoint_file=checkpoint_file)

    has_doi = sum(1 for v in bibcode_info.values() if v["doi"])
    has_arxiv = sum(1 for v in bibcode_info.values() if v["arxiv_id"])
    logger.info(f"  {has_doi:,}/{len(bibcodes):,} have DOIs, {has_arxiv:,} have arXiv IDs")

    # Step 2: OpenAlex OA lookup (with resume from existing manifest)
    logger.info("Looking up OA status via OpenAlex...")
    output_file.parent.mkdir(parents=True, exist_ok=True)

    already_done = _load_existing_manifest(output_file)
    if already_done:
        logger.info(f"  Resuming: {len(already_done):,} bibcodes already in manifest")

    remaining_bibcodes = [b for b in bibcodes if b not in already_done]

    stats = {"total": len(bibcodes), "has_doi": 0, "is_oa": 0, "has_pdf_url": 0, "has_arxiv": has_arxiv}

    # Count stats from already-done records
    if already_done:
        for line in output_file.read_text().splitlines():
            line = line.strip()
            if line:
                r = json.loads(line)
                if r.get("doi"):
                    stats["has_doi"] += 1
                if r.get("is_oa"):
                    stats["is_oa"] += 1
                if r.get("pdf_url"):
                    stats["has_pdf_url"] += 1

    # Separate bibcodes with/without DOIs for batching
    remaining_with_doi = []
    remaining_no_doi = []
    for bibcode in remaining_bibcodes:
        info = bibcode_info.get(bibcode, {"doi": None, "arxiv_id": None})
        if info["doi"]:
            remaining_with_doi.append(bibcode)
        else:
            remaining_no_doi.append(bibcode)

    logger.info(
        f"  {len(remaining_with_doi):,} to look up on OpenAlex, "
        f"{len(remaining_no_doi):,} without DOIs"
    )

    # Append mode for resume
    with open(output_file, "a") as f:
        # Write no-DOI records immediately (no API call needed)
        for bibcode in remaining_no_doi:
            info = bibcode_info.get(bibcode, {"doi": None, "arxiv_id": None})
            record = {"bibcode": bibcode, "doi": None, "arxiv_id": info["arxiv_id"]}
            record.update(extra_fields.get(bibcode, {}))
            record.update(_NO_OA)
            f.write(json.dumps(record) + "\n")

        # Batch lookup DOIs on OpenAlex
        n_batches = (len(remaining_with_doi) + OPENALEX_BATCH_SIZE - 1) // OPENALEX_BATCH_SIZE
        pbar = tqdm(total=len(remaining_with_doi), desc="OpenAlex")

        for i in range(0, len(remaining_with_doi), OPENALEX_BATCH_SIZE):
            batch_bibcodes = remaining_with_doi[i : i + OPENALEX_BATCH_SIZE]

            # Collect DOIs for this batch, build doi→bibcode mapping
            doi_to_bibcodes: dict[str, list[str]] = {}
            for bibcode in batch_bibcodes:
                doi = bibcode_info[bibcode]["doi"]
                norm = _normalize_doi(doi)
                doi_to_bibcodes.setdefault(norm, []).append(bibcode)

            # Query OpenAlex
            batch_dois = list(doi_to_bibcodes.keys())
            try:
                oa_results = openalex_batch_lookup(batch_dois, email)
            except requests.HTTPError as e:
                logger.warning(f"  OpenAlex error (batch {i // OPENALEX_BATCH_SIZE + 1}/{n_batches}): {e}")
                oa_results = {}

            # Write records for this batch
            for bibcode in batch_bibcodes:
                info = bibcode_info[bibcode]
                doi = info["doi"]
                norm_doi = _normalize_doi(doi)
                oa = oa_results.get(norm_doi, _NO_OA)

                record = {"bibcode": bibcode, "doi": doi, "arxiv_id": info["arxiv_id"]}
                record.update(extra_fields.get(bibcode, {}))
                record.update(oa)

                if doi:
                    stats["has_doi"] += 1
                if record["is_oa"]:
                    stats["is_oa"] += 1
                if record["pdf_url"]:
                    stats["has_pdf_url"] += 1

                f.write(json.dumps(record) + "\n")

            f.flush()
            pbar.update(len(batch_bibcodes))
            time.sleep(delay)

        pbar.close()

    logger.info(
        f"Done: {stats['has_doi']:,} DOIs, "
        f"{stats['is_oa']:,} OA, "
        f"{stats['has_pdf_url']:,} with PDF URLs"
    )
    return stats


def main():
    import argparse

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    parser = argparse.ArgumentParser(description="Resolve bibcodes to OA PDF URLs")
    parser.add_argument("input_file", type=Path, help="Text file (one bibcode per line) or JSONL from merge.py")
    parser.add_argument("--output", "-o", type=Path, default=None, help="Output JSONL manifest")
    parser.add_argument("--email", default="you@example.com", help="Email for OpenAlex API")
    parser.add_argument("--delay", type=float, default=0.1, help="Delay between OpenAlex requests")
    parser.add_argument("--limit", type=int, default=None, help="Only process first N bibcodes")
    args = parser.parse_args()

    input_records = load_input(args.input_file)
    if args.limit:
        input_records = input_records[: args.limit]

    output = args.output or args.input_file.with_suffix(".manifest.jsonl")

    stats = build_manifest(input_records, args.email, output, delay=args.delay)
    print(json.dumps(stats, indent=2))
    print(f"\nManifest written to: {output}")


if __name__ == "__main__":
    main()

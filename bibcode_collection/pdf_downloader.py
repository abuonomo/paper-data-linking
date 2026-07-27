"""Download OA PDFs from a manifest produced by oa_lookup.

Download strategy (per paper):
  1. Try primary pdf_url with requests
  2. Try each alt_pdf_url with requests
  3. Try arXiv PDF if arXiv ID is available
  4. Fall back to Playwright (headless browser) on primary url

Supports concurrent downloads with per-domain rate limiting.
Optionally uploads to S3 instead of keeping local files.
"""

from __future__ import annotations

import json
import logging
import tempfile
import threading
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests
from tqdm import tqdm

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; helio-bibcodes/1.0; mailto:anthony.r.buonomo@gmail.com)"
}


def sanitize_bibcode(bibcode: str) -> str:
    """Turn a bibcode into a safe filename (replace & and / with _)."""
    return bibcode.replace("&", "_").replace("/", "_")


def _get_domain(url: str) -> str:
    """Extract hostname from a URL for per-domain rate limiting."""
    return urllib.parse.urlparse(url).netloc


def _load_exclusion_set(exclude_file: Path) -> set[str]:
    """Load bibcodes to skip from a text file (one per line)."""
    return {
        line.strip()
        for line in exclude_file.read_text().splitlines()
        if line.strip()
    }


def _load_failed_log(failed_log: Path) -> set[str]:
    """Load previously-failed bibcodes from a JSONL log file."""
    if not failed_log.exists():
        return set()
    failed = set()
    for line in failed_log.read_text().splitlines():
        line = line.strip()
        if line:
            failed.add(json.loads(line)["bibcode"])
    return failed


def _upload_to_s3(local_path: Path, bucket: str, key: str, s3_client) -> None:
    """Upload a local file to S3."""
    s3_client.upload_file(str(local_path), bucket, key)


def _download_requests(url: str, dest: Path, timeout: int = 60) -> bool:
    """Try downloading a PDF with plain requests. Returns True on success."""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=timeout, stream=True)
        resp.raise_for_status()

        content_type = resp.headers.get("Content-Type", "")
        if "html" in content_type:
            logger.debug(f"  requests got HTML for {url}")
            return False
        if "pdf" not in content_type and "octet-stream" not in content_type:
            logger.debug(f"  requests got unexpected content-type {content_type!r} for {url}")

        with open(dest, "wb") as f:
            for chunk in resp.iter_content(chunk_size=8192):
                f.write(chunk)
        return True

    except requests.RequestException as e:
        logger.debug(f"  requests failed for {url}: {e}")
        if dest.exists():
            dest.unlink()
        return False


def _download_playwright(url: str, dest: Path, timeout: int = 30_000) -> bool:
    """Download a PDF using a headless browser. Returns True on success."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        logger.warning("  Playwright not installed — skipping browser fallback")
        return False

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            context = browser.new_context(accept_downloads=True)
            page = context.new_page()

            # Navigate and wait for the PDF to render/download
            resp = page.goto(url, wait_until="networkidle", timeout=timeout)
            if resp is None:
                browser.close()
                return False

            content_type = resp.headers.get("content-type", "")

            if "pdf" in content_type:
                # Page served the PDF directly — save the body
                body = resp.body()
                dest.write_bytes(body)
                browser.close()
                return True

            # Some publishers trigger a download instead of inline display
            # Try clicking any download/PDF button, or just grab the page content
            # For now, if we got HTML it means the publisher needs more interaction
            browser.close()
            logger.debug(f"  Playwright got {content_type} for {url}")
            return False

    except Exception as e:
        logger.debug(f"  Playwright failed for {url}: {e}")
        if dest.exists():
            dest.unlink()
        return False


def download_pdf(record: dict, dest: Path, use_playwright: bool = False,
                 playwright_semaphore: threading.Semaphore | None = None) -> str:
    """Try all available URLs to download a PDF.

    Returns the method used: "requests", "requests_alt", "arxiv", "playwright", or "failed".
    """
    primary_url = record.get("pdf_url")
    alt_urls = record.get("alt_pdf_urls", [])
    arxiv_id = record.get("arxiv_id")

    # 1. Try primary URL with requests
    if primary_url and _download_requests(primary_url, dest):
        return "requests"

    # 2. Try alternate URLs with requests
    for url in alt_urls:
        if _download_requests(url, dest):
            return "requests_alt"

    # 3. Try arXiv PDF if we have an arXiv ID
    if arxiv_id:
        arxiv_url = f"https://arxiv.org/pdf/{arxiv_id}"
        if _download_requests(arxiv_url, dest):
            return "arxiv"

    # 4. Playwright fallback on primary URL (with concurrency limit)
    if use_playwright and primary_url:
        if playwright_semaphore:
            with playwright_semaphore:
                if _download_playwright(primary_url, dest):
                    return "playwright"
        elif _download_playwright(primary_url, dest):
            return "playwright"

    return "failed"


def _list_s3_keys(s3_client, bucket: str, prefix: str) -> set[str]:
    """List all object keys under a prefix in S3. Returns a set of keys."""
    keys = set()
    paginator = s3_client.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix + "/"):
        for obj in page.get("Contents", []):
            keys.add(obj["Key"])
    return keys


def _log_failure(bibcode: str, failed_log_fh, failed_log_lock: threading.Lock | None) -> None:
    """Append a failed bibcode to the failed-log file (thread-safe)."""
    if failed_log_fh is None:
        return
    entry = json.dumps({"bibcode": bibcode, "ts": time.strftime("%Y-%m-%dT%H:%M:%S")}) + "\n"
    with failed_log_lock:
        failed_log_fh.write(entry)
        failed_log_fh.flush()


def _download_one(
    record: dict,
    output_dir: Path | None,
    s3_bucket: str | None,
    s3_prefix: str,
    s3_client,
    skip_existing: bool,
    use_playwright: bool,
    domain_semaphores: dict[str, threading.Semaphore],
    domain_sem_lock: threading.Lock,
    max_per_host: int,
    playwright_semaphore: threading.Semaphore | None,
    existing_s3_keys: set[str] | None = None,
    failed_bibcodes: set[str] | None = None,
    failed_log_fh=None,
    failed_log_lock: threading.Lock | None = None,
) -> tuple[str, str]:
    """Download a single PDF (worker function for thread pool).

    Returns (bibcode, method) where method is one of:
    "requests", "requests_alt", "arxiv", "playwright", "failed", "skipped_existing".
    """
    bibcode = record["bibcode"]
    safe_name = f"{sanitize_bibcode(bibcode)}.pdf"

    # Skip previously-failed bibcodes
    if failed_bibcodes and bibcode in failed_bibcodes:
        return (bibcode, "skipped_failed")

    # Determine primary domain for rate limiting
    primary_url = record.get("pdf_url") or ""
    domain = _get_domain(primary_url) if primary_url else "unknown"

    # Lazily create per-domain semaphore
    with domain_sem_lock:
        if domain not in domain_semaphores:
            domain_semaphores[domain] = threading.Semaphore(max_per_host)

    # Acquire per-domain semaphore to limit concurrent requests to same host
    with domain_semaphores[domain]:
        if s3_bucket:
            # S3 mode
            s3_key = f"{s3_prefix}/{safe_name}"

            if skip_existing and existing_s3_keys is not None and s3_key in existing_s3_keys:
                return (bibcode, "skipped_existing")

            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
                tmp_path = Path(tmp.name)

            try:
                method = download_pdf(record, tmp_path, use_playwright=use_playwright,
                                      playwright_semaphore=playwright_semaphore)
                if method != "failed":
                    _upload_to_s3(tmp_path, s3_bucket, s3_key, s3_client)
                else:
                    _log_failure(bibcode, failed_log_fh, failed_log_lock)
                return (bibcode, method)
            finally:
                if tmp_path.exists():
                    tmp_path.unlink()
        else:
            # Local mode
            dest = output_dir / safe_name

            if skip_existing and dest.exists() and dest.stat().st_size > 0:
                return (bibcode, "skipped_existing")

            method = download_pdf(record, dest, use_playwright=use_playwright,
                                  playwright_semaphore=playwright_semaphore)
            if method == "failed":
                _log_failure(bibcode, failed_log_fh, failed_log_lock)
            return (bibcode, method)


def download_from_manifest(
    manifest_file: Path,
    output_dir: Path | None = None,
    max_downloads: int | None = None,
    skip_existing: bool = True,
    use_playwright: bool = False,
    s3_bucket: str | None = None,
    s3_prefix: str = "papers",
    aws_profile: str | None = None,
    exclude_bibcodes: set[str] | None = None,
    max_workers: int = 8,
    max_per_host: int = 2,
    failed_log: Path | None = None,
) -> dict:
    """Read a JSONL manifest and download all PDFs.

    When s3_bucket is set, PDFs are uploaded to S3 and temp files are cleaned up.
    When s3_bucket is None, PDFs are saved to output_dir (local mode).

    Uses ThreadPoolExecutor for concurrent downloads with per-domain rate limiting.

    Returns summary stats dict.
    """
    s3_client = None
    if s3_bucket:
        import boto3
        session = boto3.Session(profile_name=aws_profile) if aws_profile else boto3.Session()
        s3_client = session.client("s3")
    else:
        if output_dir is None:
            raise ValueError("output_dir is required when not using S3")
        output_dir.mkdir(parents=True, exist_ok=True)

    records = []
    with open(manifest_file) as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))

    downloadable = [r for r in records if r.get("pdf_url") or r.get("arxiv_id")]

    # Filter out excluded bibcodes
    if exclude_bibcodes:
        before = len(downloadable)
        downloadable = [r for r in downloadable if r["bibcode"] not in exclude_bibcodes]
        excluded_count = before - len(downloadable)
    else:
        excluded_count = 0

    if max_downloads:
        downloadable = downloadable[:max_downloads]

    # Load previously-failed bibcodes
    failed_bibcodes: set[str] | None = None
    if failed_log:
        failed_bibcodes = _load_failed_log(failed_log)
        if failed_bibcodes:
            logger.info(f"Loaded {len(failed_bibcodes):,} previously-failed bibcodes from {failed_log}")

    stats = {
        "total_records": len(records),
        "downloadable": len(downloadable),
        "excluded": excluded_count,
        "downloaded_requests": 0,
        "downloaded_requests_alt": 0,
        "downloaded_arxiv": 0,
        "downloaded_playwright": 0,
        "uploaded_s3": 0,
        "skipped_existing": 0,
        "skipped_failed": 0,
        "failed": 0,
    }

    logger.info(
        f"{len(downloadable)} records to download "
        f"(out of {len(records)} total, {excluded_count} excluded, "
        f"{max_workers} workers, {max_per_host} max/host)"
    )

    # Prefetch existing S3 keys to avoid per-record HEAD requests on restart
    existing_s3_keys = None
    if s3_bucket and skip_existing:
        logger.info(f"Listing existing keys in s3://{s3_bucket}/{s3_prefix}/...")
        existing_s3_keys = _list_s3_keys(s3_client, s3_bucket, s3_prefix)
        logger.info(f"  Found {len(existing_s3_keys):,} existing PDFs in S3")

    # Shared state for thread pool
    domain_semaphores: dict[str, threading.Semaphore] = {}
    domain_sem_lock = threading.Lock()
    playwright_semaphore = threading.Semaphore(1) if use_playwright else None
    stats_lock = threading.Lock()
    failed_log_lock = threading.Lock() if failed_log else None
    failed_log_fh = open(failed_log, "a") if failed_log else None

    try:
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(
                    _download_one,
                    record, output_dir, s3_bucket, s3_prefix, s3_client,
                    skip_existing, use_playwright,
                    domain_semaphores, domain_sem_lock, max_per_host,
                    playwright_semaphore, existing_s3_keys,
                    failed_bibcodes, failed_log_fh, failed_log_lock,
                ): record
                for record in downloadable
            }

            with tqdm(total=len(futures), desc="Downloading") as pbar:
                for future in as_completed(futures):
                    record = futures[future]
                    bibcode = record["bibcode"]
                    try:
                        _, method = future.result()
                    except Exception as e:
                        logger.error(f"  Unexpected error for {bibcode}: {e}")
                        method = "failed"
                        _log_failure(bibcode, failed_log_fh, failed_log_lock)

                    with stats_lock:
                        if method == "skipped_existing":
                            stats["skipped_existing"] += 1
                        elif method == "skipped_failed":
                            stats["skipped_failed"] += 1
                        elif method == "failed":
                            stats["failed"] += 1
                            logger.warning(f"  All methods failed for {bibcode}")
                        else:
                            stats[f"downloaded_{method}"] += 1
                            if s3_bucket:
                                stats["uploaded_s3"] += 1

                    pbar.update(1)
    finally:
        if failed_log_fh:
            failed_log_fh.close()

    total_ok = (
        stats["downloaded_requests"] + stats["downloaded_requests_alt"]
        + stats["downloaded_arxiv"] + stats["downloaded_playwright"]
    )
    logger.info(
        f"Done: {total_ok} downloaded "
        f"(requests={stats['downloaded_requests']}, "
        f"alt={stats['downloaded_requests_alt']}, "
        f"arxiv={stats['downloaded_arxiv']}, "
        f"playwright={stats['downloaded_playwright']}), "
        f"{stats['skipped_existing']} skipped, "
        f"{stats['skipped_failed']} skipped (prev failed), "
        f"{stats['excluded']} excluded, "
        f"{stats['failed']} failed"
    )
    if s3_bucket:
        logger.info(f"  {stats['uploaded_s3']} uploaded to s3://{s3_bucket}/{s3_prefix}/")
    return stats


def main():
    import argparse

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    parser = argparse.ArgumentParser(description="Download OA PDFs from manifest")
    parser.add_argument("manifest", type=Path, help="JSONL manifest from oa_lookup")
    parser.add_argument(
        "--output-dir", "-o", type=Path, default=None,
        help="Directory to save PDFs (default: <manifest_dir>/pdfs/). Ignored when --s3-bucket is set.",
    )
    parser.add_argument("--limit", type=int, default=None, help="Max PDFs to download")
    parser.add_argument("--no-skip", action="store_true", help="Re-download existing files")
    parser.add_argument("--playwright", action="store_true", help="Enable Playwright browser fallback (slow)")

    # Concurrency options
    parser.add_argument("--workers", type=int, default=8, help="Number of concurrent download threads (default: 8)")
    parser.add_argument("--max-per-host", type=int, default=2, help="Max concurrent downloads per publisher domain (default: 2)")

    # S3 options
    parser.add_argument("--s3-bucket", default=None, help="S3 bucket name (omit for local-only)")
    parser.add_argument("--s3-prefix", default="papers", help="S3 key prefix (default: papers)")
    parser.add_argument("--aws-profile", default=None, help="AWS profile name (default: env/instance role)")

    # Exclusion / failure tracking
    parser.add_argument(
        "--exclude-bibcodes", type=Path, default=None,
        help="Text file of bibcodes to skip (one per line)",
    )
    parser.add_argument(
        "--failed-log", type=Path, default=None,
        help="JSONL file to log failed bibcodes (read on startup to skip, appended during run)",
    )

    args = parser.parse_args()

    exclude_set = None
    if args.exclude_bibcodes:
        exclude_set = _load_exclusion_set(args.exclude_bibcodes)
        logger.info(f"Loaded {len(exclude_set)} bibcodes to exclude")

    output_dir = args.output_dir or (args.manifest.parent / "pdfs" if not args.s3_bucket else None)

    stats = download_from_manifest(
        args.manifest,
        output_dir=output_dir,
        max_downloads=args.limit,
        skip_existing=not args.no_skip,
        use_playwright=args.playwright,
        s3_bucket=args.s3_bucket,
        s3_prefix=args.s3_prefix,
        aws_profile=args.aws_profile,
        exclude_bibcodes=exclude_set,
        max_workers=args.workers,
        max_per_host=args.max_per_host,
        failed_log=args.failed_log,
    )
    print(json.dumps(stats, indent=2))
    if output_dir:
        print(f"\nPDFs saved to: {output_dir}")
    if args.s3_bucket:
        print(f"\nPDFs uploaded to: s3://{args.s3_bucket}/{args.s3_prefix}/")


if __name__ == "__main__":
    main()

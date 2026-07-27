"""Standalone ADS API client for bibcode collection. No Django dependency."""

import logging
import os
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

logger = logging.getLogger(__name__)

ADS_BASE_URL = "https://api.adsabs.harvard.edu/v1/search/query"
ADS_BIGQUERY_URL = "https://api.adsabs.harvard.edu/v1/search/bigquery"
ADS_MAX_ROWS = 2000  # ADS API max per request
RETRYABLE_CODES = {502, 503, 504, 429}


def _request_with_retry(method, url, max_retries=5, backoff=10, **kwargs):
    """Make an HTTP request with retry on transient errors."""
    for attempt in range(max_retries + 1):
        resp = method(url, **kwargs)
        if resp.status_code not in RETRYABLE_CODES or attempt == max_retries:
            resp.raise_for_status()
            return resp
        wait = backoff * (2 ** attempt)
        logger.warning(f"  HTTP {resp.status_code}, retrying in {wait}s (attempt {attempt + 1}/{max_retries})...")
        time.sleep(wait)
    return resp  # unreachable, but satisfies type checkers


class ADSClient:
    def __init__(self, api_key: str | None = None, delay: float = 1.5):
        self.api_key = api_key or os.environ["ADS_TOKEN"]
        self.headers = {"Authorization": f"Bearer {self.api_key}"}
        self.delay = delay

    def count(self, query: str) -> int:
        """Return numFound for a query without fetching docs."""
        resp = _request_with_retry(
            requests.get,
            ADS_BASE_URL,
            headers=self.headers,
            params={"q": query, "rows": 0},
        )
        return resp.json()["response"]["numFound"]

    def search(
        self,
        query: str,
        fields: list[str] | None = None,
        rows: int = ADS_MAX_ROWS,
        max_results: int | None = None,
    ) -> list[dict]:
        """Paginated search. Returns list of doc dicts."""
        if fields is None:
            fields = ["bibcode"]
        fl = ",".join(fields)
        rows = min(rows, ADS_MAX_ROWS)

        all_docs = []
        start = 0

        while True:
            params = {"q": query, "fl": fl, "rows": rows, "start": start}
            resp = _request_with_retry(
                requests.get, ADS_BASE_URL,
                headers=self.headers, params=params,
            )
            data = resp.json()["response"]
            docs = data["docs"]

            if not docs:
                break

            all_docs.extend(docs)
            logger.info(f"  fetched {len(all_docs)}/{data['numFound']}")

            if len(all_docs) >= data["numFound"]:
                break
            if max_results and len(all_docs) >= max_results:
                all_docs = all_docs[:max_results]
                break

            start += rows
            time.sleep(self.delay)

        return all_docs

    def bigquery(
        self,
        bibcodes: list[str],
        fields: list[str] | None = None,
    ) -> list[dict]:
        """Look up a batch of bibcodes using the ADS bigquery endpoint.

        This avoids URL length limits by sending bibcodes in the POST body.
        Supports up to ~2000 bibcodes per call.
        """
        if fields is None:
            fields = ["bibcode"]
        fl = ",".join(fields)

        # bigquery expects "bibcode\n<bib1>\n<bib2>\n..."
        bigquery_body = "bibcode\n" + "\n".join(bibcodes)

        resp = _request_with_retry(
            requests.post,
            ADS_BIGQUERY_URL,
            headers={**self.headers, "Content-Type": "big-query/csv"},
            params={"q": "*:*", "fl": fl, "rows": len(bibcodes)},
            data=bigquery_body,
        )
        return resp.json()["response"]["docs"]

    def library_count(self, library_id: str) -> int:
        """Return the number of documents in a public ADS library."""
        url = f"https://api.adsabs.harvard.edu/v1/biblib/libraries/{library_id}"
        resp = _request_with_retry(
            requests.get, url,
            headers=self.headers, params={"rows": 0, "start": 0},
        )
        return resp.json()["metadata"]["num_documents"]

    def library_bibcodes(self, library_id: str, rows: int = 2000) -> list[str]:
        """Fetch all bibcodes from a public ADS library."""
        url = f"https://api.adsabs.harvard.edu/v1/biblib/libraries/{library_id}"
        all_bibcodes = []
        start = 0

        while True:
            resp = _request_with_retry(
                requests.get, url,
                headers=self.headers,
                params={"rows": rows, "start": start},
            )
            data = resp.json()
            docs = data["documents"]

            if not docs:
                break

            all_bibcodes.extend(docs)
            num_total = data["metadata"]["num_documents"]
            logger.info(f"  fetched {len(all_bibcodes)}/{num_total}")

            if len(all_bibcodes) >= num_total:
                break

            start += rows
            time.sleep(self.delay)

        return all_bibcodes

#!/usr/bin/env python3
"""
Enrich instrument catalog descriptions using SPASE SMWG GitHub records.

For each entry with a spase://SMWG/Instrument/... code, fetches the
corresponding XML from hpde/SMWG on GitHub and extracts:
  - ResourceName  -> new instrument_name
  - InstrumentType -> appended to description
  - Description (first sentence) -> new description

Produces a CSV table of before/after values for review.
"""

import json
import time
import csv
import sys
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.request import urlopen, Request
from urllib.error import HTTPError, URLError

# ── paths ────────────────────────────────────────────────────────────────────
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))
from paper_data_linking.config.paths import DATA_ASSETS_DIR

CATALOG_PATH = DATA_ASSETS_DIR / "vso" / "merged_instrument_catalog.json"
OUTPUT_CSV      = Path(__file__).parent / "spase_enrichment_preview.csv"
OUTPUT_RAW_JSONL = Path(__file__).parent / "spase_raw_data.jsonl"

GITHUB_RAW = "https://raw.githubusercontent.com/hpde/SMWG/master"
SPASE_NS   = {"s": "http://www.spase-group.org/data/schema"}
RATE_LIMIT_SECONDS = 0.15   # ~6 req/s, well within GitHub raw limits


# ── helpers ──────────────────────────────────────────────────────────────────
def spase_to_github_url(spase_uri: str) -> str:
    """spase://SMWG/Instrument/X/Y  ->  https://raw.githubusercontent.com/hpde/SMWG/master/Instrument/X/Y.xml"""
    path = spase_uri.removeprefix("spase://SMWG/")
    return f"{GITHUB_RAW}/{path}.xml"


def fetch_xml(url: str) -> ET.Element | None:
    try:
        req = Request(url, headers={"User-Agent": "pdl-catalog-enricher/1.0"})
        with urlopen(req, timeout=10) as resp:
            return ET.fromstring(resp.read())
    except HTTPError as e:
        if e.code == 404:
            return None
        raise
    except URLError:
        return None


def text(root: ET.Element, *paths: str) -> str:
    """Return stripped text for the first path that matches, else ''."""
    for path in paths:
        el = root.find(path, SPASE_NS)
        if el is not None and el.text:
            return el.text.strip()
    return ""


def first_sentence(s: str) -> str:
    s = re.sub(r'\s+', ' ', s).strip()
    m = re.search(r'[.!?]', s)
    return s[:m.end()].strip() if m else s[:200]


def enrich(entry: dict, root: ET.Element) -> dict:
    """Return enriched copy of entry using SPASE XML root."""
    resource_name  = text(root, ".//s:ResourceName")
    instrument_type = text(root, ".//s:InstrumentType")
    description_full = text(root, ".//s:Description")

    new_name = resource_name if resource_name else entry["instrument_name"]

    if instrument_type and description_full:
        new_desc = f"{instrument_type}: {first_sentence(description_full)}"
    elif instrument_type:
        new_desc = instrument_type
    elif description_full:
        new_desc = first_sentence(description_full)
    else:
        new_desc = entry["description"]

    return {**entry, "instrument_name": new_name, "description": new_desc}


# ── main ─────────────────────────────────────────────────────────────────────
def main():
    catalog = json.loads(CATALOG_PATH.read_text())

    spase_entries = [
        (i, e) for i, e in enumerate(catalog)
        if str(e.get("instrument_code", "")).startswith("spase://SMWG/Instrument/")
    ]

    print(f"Total catalog entries : {len(catalog)}")
    print(f"SPASE SMWG entries    : {len(spase_entries)}")
    print(f"Output CSV            : {OUTPUT_CSV}")
    print()

    rows = []
    raw_records = []   # saved for LLM enrichment pipeline
    fetched = skipped = errors = 0

    for idx, (cat_idx, entry) in enumerate(spase_entries):
        url = spase_to_github_url(entry["instrument_code"])
        root = fetch_xml(url)
        time.sleep(RATE_LIMIT_SECONDS)

        if root is None:
            skipped += 1
            rows.append({
                "instrument_code"    : entry["instrument_code"],
                "mission_name"       : entry["mission_name"],
                "before_name"        : entry["instrument_name"],
                "after_name"         : "(not found)",
                "before_description" : entry["description"],
                "after_description"  : "(not found)",
                "changed"            : "no - 404",
            })
            continue

        # Extract raw SPASE fields for LLM pipeline
        spase_resource_name   = text(root, ".//s:ResourceName")
        spase_instrument_type = text(root, ".//s:InstrumentType")
        spase_description     = text(root, ".//s:Description")

        raw_records.append({
            "instrument_code"      : entry["instrument_code"],
            "instrument_name"      : entry["instrument_name"],
            "mission_code"         : entry["mission_code"],
            "mission_name"         : entry["mission_name"],
            "data_system"          : entry["data_system"],
            "before_description"   : entry["description"],
            "spase_resource_name"  : spase_resource_name,
            "spase_instrument_type": spase_instrument_type,
            "spase_description"    : spase_description,
        })

        enriched = enrich(entry, root)
        name_changed = enriched["instrument_name"] != entry["instrument_name"]
        desc_changed = enriched["description"]     != entry["description"]
        changed = "yes" if (name_changed or desc_changed) else "no"

        rows.append({
            "instrument_code"    : entry["instrument_code"],
            "mission_name"       : entry["mission_name"],
            "before_name"        : entry["instrument_name"],
            "after_name"         : enriched["instrument_name"],
            "before_description" : entry["description"],
            "after_description"  : enriched["description"],
            "changed"            : changed,
        })
        fetched += 1

        if (idx + 1) % 50 == 0:
            print(f"  {idx+1}/{len(spase_entries)} processed "
                  f"({fetched} enriched, {skipped} not found, {errors} errors)...")

    # ── write CSV ─────────────────────────────────────────────────────────────
    fields = ["instrument_code", "mission_name",
              "before_name", "after_name",
              "before_description", "after_description",
              "changed"]
    with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)

    # ── write raw JSONL for LLM pipeline ─────────────────────────────────────
    with open(OUTPUT_RAW_JSONL, "w", encoding="utf-8") as f:
        for rec in raw_records:
            f.write(json.dumps(rec) + "\n")

    changed_count = sum(1 for r in rows if r["changed"] == "yes")
    print()
    print(f"Done.")
    print(f"  Fetched        : {fetched}")
    print(f"  Not found      : {skipped}")
    print(f"  Changed        : {changed_count}/{len(rows)}")
    print(f"  CSV saved      : {OUTPUT_CSV}")
    print(f"  Raw JSONL saved: {OUTPUT_RAW_JSONL}")


if __name__ == "__main__":
    main()

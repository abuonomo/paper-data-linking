"""Experimentally classify papers as helio vs non-helio using ADS abstracts.

Fetches titles + abstracts from ADS bigquery, then applies keyword matching
to flag papers that are likely not heliophysics.

This is an analyst-facing filtering script, not a production pipeline step.

Usage:
    PYTHONPATH=. uv run --extra classify python scripts/classify_helio.py \
        data/pipeline-final/manifest.jsonl \
        -o data/pipeline-final/helio_classification.jsonl \
        --checkpoint data/pipeline-final/abstracts_checkpoint.jsonl
"""

import json
import logging
import re
import time
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

# --- Heliophysics keyword sets ---

# Primary: strong signal of helio content
HELIO_PRIMARY = {
    # Solar
    "solar", "sun", "sunspot", "corona", "coronal", "photosphere", "chromosphere",
    "heliosphere", "heliospheric", "helioseismology", "solar wind", "solar flare",
    "solar cycle", "solar activity", "solar energetic", "solar magnetic",
    "cme", "coronal mass ejection", "coronal hole", "solar corona",
    "prominences", "prominence", "spicule", "sunquake",
    # Magnetosphere / geospace
    "magnetosphere", "magnetospheric", "magnetopause", "magnetotail",
    "magnetosheath", "geomagnetic", "geospace", "substorm",
    "aurora", "auroral", "radiation belt", "plasmasphere", "ring current",
    # Ionosphere / thermosphere
    "ionosphere", "ionospheric", "thermosphere", "mesosphere",
    # Space weather
    "space weather", "geomagnetically", "interplanetary",
    # Instruments / missions
    "sdo", "soho", "stereo", "parker solar probe", "psp",
    "hinode", "iris", "wind spacecraft", "ace spacecraft",
    "mms", "magnetospheric multiscale", "van allen", "voyager",
    "ulysses", "cluster mission", "themis", "goes",
    "dscovr", "maven", "juno",
}

# Secondary: weaker signal, helio when combined with context
HELIO_SECONDARY = {
    "plasma", "magnetic field", "reconnection", "mhd", "magnetohydrodynamic",
    "alfven", "alfvén", "particle acceleration", "cosmic ray",
    "stellar wind", "stellar corona", "stellar flare",
    "flux rope", "shock wave", "turbulence",
    "radio burst", "type ii", "type iii",
    "extreme ultraviolet", "euv", "x-ray",
}

# Journals that are almost always helio
HELIO_JOURNALS = {
    "SoPh", "JGRA", "JGRB", "JGRC", "JGRD", "GeoRL", "AnGeo",
    "SpWea", "JSWSC", "AdSpR", "STP", "EP&S",
}

# Journals that are almost never helio
NON_HELIO_JOURNALS = {
    "Vacuu", "UltSci", "Sentic", "JMatS", "ITMTT", "TDM", "JCrGr",
    "AcMat", "Mate",
}


def _extract_journal(bibcode: str) -> str:
    """Extract journal abbreviation from bibcode."""
    journal_part = bibcode[4:].rstrip(".")
    match = re.match(r"^([A-Za-z&.]+)", journal_part)
    return match.group(1).rstrip(".") if match else ""


def classify(bibcode: str, title: str, abstract: str) -> dict:
    """Classify a paper as helio or not. Returns {label, confidence, reason}."""
    journal = _extract_journal(bibcode)
    text = f"{title} {abstract}".lower()

    # Quick journal-based classification
    if journal in NON_HELIO_JOURNALS:
        return {"label": "non-helio", "confidence": "high", "reason": f"journal:{journal}"}
    if journal in HELIO_JOURNALS:
        return {"label": "helio", "confidence": "high", "reason": f"journal:{journal}"}

    # Keyword matching
    primary_hits = [kw for kw in HELIO_PRIMARY if kw in text]
    secondary_hits = [kw for kw in HELIO_SECONDARY if kw in text]

    if primary_hits:
        return {
            "label": "helio",
            "confidence": "high" if len(primary_hits) >= 2 else "medium",
            "reason": f"primary:{','.join(primary_hits[:3])}",
        }

    if len(secondary_hits) >= 2:
        return {
            "label": "helio",
            "confidence": "low",
            "reason": f"secondary:{','.join(secondary_hits[:3])}",
        }

    if secondary_hits:
        return {
            "label": "uncertain",
            "confidence": "low",
            "reason": f"weak:{','.join(secondary_hits)}",
        }

    return {"label": "non-helio", "confidence": "medium", "reason": "no_keywords"}


def load_checkpoint(path: Path) -> dict[str, dict]:
    """Load previously fetched abstracts."""
    if not path.exists():
        return {}
    result = {}
    for line in path.read_text().splitlines():
        if line.strip():
            r = json.loads(line)
            result[r["bibcode"]] = r
    return result


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Classify papers as helio vs non-helio")
    parser.add_argument("input", type=Path, help="JSONL manifest or plain bibcode list (one per line)")
    parser.add_argument("-o", "--output", type=Path, required=True, help="Output classification JSONL")
    parser.add_argument("--checkpoint", type=Path, default=None, help="Abstracts checkpoint file")
    parser.add_argument("--limit", type=int, default=None, help="Only process first N bibcodes")
    parser.add_argument("--ads-token", default=None, help="ADS API token (overrides ADS_TOKEN env var)")
    parser.add_argument("--delay", type=float, default=2.0, help="Delay between ADS requests (default: 2.0)")
    args = parser.parse_args()

    from bibcode_collection.ads_client import ADSClient

    # Load bibcodes from manifest JSONL or plain text file
    bibcodes = []
    with open(args.input) as f:
        first_line = f.readline().strip()
        f.seek(0)
        is_jsonl = first_line.startswith("{")

        for line in f:
            line = line.strip()
            if not line:
                continue
            if is_jsonl:
                r = json.loads(line)
                if r.get("pdf_url") or r.get("arxiv_id"):
                    bibcodes.append(r["bibcode"])
            else:
                bibcodes.append(line)

    if args.limit:
        bibcodes = bibcodes[:args.limit]
    logger.info(f"Loaded {len(bibcodes):,} bibcodes from {args.input.name}")

    # Load checkpoint
    checkpoint_path = args.checkpoint or args.output.with_suffix(".abstracts.jsonl")
    abstracts = load_checkpoint(checkpoint_path)
    if abstracts:
        logger.info(f"Checkpoint: {len(abstracts):,} abstracts already fetched")

    # Fetch missing abstracts from ADS
    remaining = [b for b in bibcodes if b not in abstracts]
    if remaining:
        logger.info(f"Fetching {len(remaining):,} abstracts from ADS...")
        client = ADSClient(api_key=args.ads_token, delay=args.delay)
        batch_size = 2000

        with open(checkpoint_path, "a") as ckpt:
            for i in range(0, len(remaining), batch_size):
                batch = remaining[i:i + batch_size]
                try:
                    docs = client.bigquery(batch, fields=["bibcode", "title", "abstract"])
                except Exception as e:
                    logger.error(f"ADS error at batch {i // batch_size}: {e}")
                    continue

                found = {d["bibcode"]: d for d in docs}
                for bib in batch:
                    doc = found.get(bib, {"bibcode": bib})
                    record = {
                        "bibcode": bib,
                        "title": (doc.get("title") or [""])[0],
                        "abstract": doc.get("abstract") or "",
                    }
                    abstracts[bib] = record
                    ckpt.write(json.dumps(record) + "\n")

                ckpt.flush()
                done = min(i + batch_size, len(remaining))
                logger.info(f"  fetched {done:,}/{len(remaining):,}")
                time.sleep(client.delay)

    # Classify
    logger.info("Classifying...")
    from collections import Counter
    stats = Counter()

    with open(args.output, "w") as f:
        for bib in bibcodes:
            info = abstracts.get(bib, {"bibcode": bib, "title": "", "abstract": ""})
            result = classify(bib, info.get("title", ""), info.get("abstract", ""))
            result["bibcode"] = bib
            result["title"] = info.get("title", "")
            f.write(json.dumps(result) + "\n")
            stats[result["label"]] += 1

    logger.info(f"\nClassification results:")
    for label, count in stats.most_common():
        logger.info(f"  {label}: {count:,} ({100 * count / len(bibcodes):.1f}%)")
    logger.info(f"\nWritten to: {args.output}")


if __name__ == "__main__":
    main()

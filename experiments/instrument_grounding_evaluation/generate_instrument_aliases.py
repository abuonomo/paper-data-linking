#!/usr/bin/env python3
"""
LLM-based generation of instrument aliases, suite relationships, and operational gotchas.

For each instrument in the catalog (or a filtered subset), asks an LLM to produce:
  - Common aliases / abbreviations used in heliophysics papers
  - Sub-instrument / parent suite relationships
  - Operational notes (failures, limited use, common confusions)

Output:
  instrument_aliases_draft.json  — structured draft for expert review
  instrument_aliases_draft.csv   — same data in tabular form for easier review

Once reviewed and corrected, copy instrument_aliases_draft.json to:
  paper_data_linking/data_assets/vso/instrument_aliases.json

Usage:
  # All instruments in catalog:
  python generate_instrument_aliases.py

  # Only instruments appearing in a specific tag's papers (recommended first pass):
  python generate_instrument_aliases.py --tag test_set_2026_02_23

  # Specific missions only:
  python generate_instrument_aliases.py --missions SOHO,ACE,Wind
"""

import argparse
import asyncio
import csv
import json
import os
import sys
from pathlib import Path

import litellm
from dotenv import find_dotenv, load_dotenv

load_dotenv(find_dotenv())

# ── paths ────────────────────────────────────────────────────────────────────
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))
from paper_data_linking.config.paths import DATA_ASSETS_DIR

CATALOG_PATH  = DATA_ASSETS_DIR / "vso" / "merged_instrument_catalog.json"
RAW_JSONL     = Path(__file__).parent / "spase_raw_data.jsonl"
OUTPUT_JSON   = Path(__file__).parent / "instrument_aliases_draft.json"
OUTPUT_CSV    = Path(__file__).parent / "instrument_aliases_draft.csv"

MODEL       = "gpt-5.2"
CONCURRENCY = 8
TEMPERATURE = 0.2


# ── prompt ───────────────────────────────────────────────────────────────────
SYSTEM_PROMPT = """\
You are an expert in heliophysics instrumentation with deep knowledge of space \
missions and how instruments are referenced in the scientific literature.

For a given space instrument, provide structured information that will help an \
automated system correctly match instrument mentions in research papers to the \
canonical instrument record.

Respond ONLY with a valid JSON object matching this schema (no markdown, no extra text):
{
  "aliases": ["list of common abbreviations or alternate names used in papers"],
  "sub_instruments": [
    {"name": "sub-instrument name", "note": "brief description of its role"}
  ],
  "parent_suite": "name of parent instrument suite if this is a sub-instrument, else null",
  "operational_notes": "any important caveats: failures, limited use, common confusions, etc. null if none",
  "commonly_confused_with": ["list of other instrument names this is often confused with"],
  "confidence": "high | medium | low"
}

Guidelines:
- aliases: include both acronyms AND spelled-out names people use in papers
- sub_instruments: only include if this IS a suite/package with named components
- parent_suite: e.g. EPHIN → parent is COSTEP; MAG (PSP) → parent is FIELDS
- operational_notes: include things like broken components, instruments rarely used, \
  naming conventions specific to this mission community
- commonly_confused_with: other instruments with similar names or roles
- If you are uncertain, use confidence "low" rather than guessing
"""

def make_user_prompt(entry: dict, raw: dict | None) -> str:
    lines = [
        f"Instrument name  : {entry['instrument_name']}",
        f"Instrument code  : {entry['instrument_code']}",
        f"Mission          : {entry['mission_name']}",
        f"Current desc     : {entry['description']}",
    ]
    if raw:
        if raw.get("spase_instrument_type") and raw["spase_instrument_type"] != "Unspecified":
            lines.append(f"Instrument type  : {raw['spase_instrument_type']}")
        if raw.get("spase_resource_name"):
            lines.append(f"SPASE name       : {raw['spase_resource_name']}")
        if raw.get("spase_description"):
            lines.append(f"SPASE description: {raw['spase_description'][:800]}")
    return "\n".join(lines)


# ── async worker ─────────────────────────────────────────────────────────────
async def process_one(sem: asyncio.Semaphore, entry: dict, raw: dict | None) -> dict:
    async with sem:
        try:
            response = await litellm.acompletion(
                model=MODEL,
                temperature=TEMPERATURE,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user",   "content": make_user_prompt(entry, raw)},
                ],
            )
            content = response.choices[0].message.content.strip()
            # Strip markdown code fences if present
            if content.startswith("```"):
                content = "\n".join(content.split("\n")[1:])
                content = content.rstrip("`").strip()
            llm_result = json.loads(content)
        except json.JSONDecodeError as e:
            llm_result = {"error": f"JSON parse error: {e}", "raw_response": content}
        except Exception as e:
            llm_result = {"error": str(e)}

        return {
            "instrument_code" : entry["instrument_code"],
            "instrument_name" : entry["instrument_name"],
            "mission_name"    : entry["mission_name"],
            "description"     : entry["description"],
            **llm_result,
        }


# ── filtering helpers ─────────────────────────────────────────────────────────
def load_instruments_for_tag(tag: str) -> set[str]:
    """Return set of instrument_codes seen in DatasetUsages for papers with a given tag."""
    # Requires Django setup — only used when --tag is passed
    import django
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "paper_analyzer_app.settings")
    sys.path.insert(0, str(project_root / "api"))
    django.setup()

    from vso_query_builder.models import DatasetUsage, Paper
    paper_ids = Paper.objects.filter(tags__contains=[tag]).values_list("id", flat=True)
    codes = set(
        DatasetUsage.objects.filter(paper__id__in=paper_ids, instrument__isnull=False)
        .values_list("instrument__short_name", flat=True)
        .distinct()
    )
    return codes


# ── main ─────────────────────────────────────────────────────────────────────
async def main(args):
    catalog = json.loads(CATALOG_PATH.read_text())

    # Build raw SPASE lookup if available
    raw_lookup = {}
    if RAW_JSONL.exists():
        for line in RAW_JSONL.read_text().splitlines():
            if line.strip():
                rec = json.loads(line)
                raw_lookup[rec["instrument_code"]] = rec

    # Filter catalog
    entries = catalog
    if args.missions:
        missions = {m.strip() for m in args.missions.split(",")}
        entries = [e for e in entries if e["mission_name"] in missions]
        print(f"Filtered to {len(entries)} entries for missions: {missions}")
    elif args.tag:
        print(f"Loading instruments for tag: {args.tag}")
        relevant_codes = load_instruments_for_tag(args.tag)
        entries = [e for e in entries if e.get("instrument_code") in relevant_codes
                   or e.get("instrument_name") in relevant_codes]
        print(f"Filtered to {len(entries)} entries appearing in tag '{args.tag}'")

    print(f"Instruments to process : {len(entries)}")
    print(f"Model                  : {MODEL}")
    print(f"Concurrency            : {CONCURRENCY}")
    print()

    sem = asyncio.Semaphore(CONCURRENCY)
    tasks = [
        process_one(sem, entry, raw_lookup.get(entry["instrument_code"]))
        for entry in entries
    ]

    results = []
    for i, coro in enumerate(asyncio.as_completed(tasks), 1):
        result = await coro
        results.append(result)
        if i % 20 == 0:
            print(f"  {i}/{len(entries)} done...")

    # Re-sort to catalog order
    code_to_result = {r["instrument_code"]: r for r in results}
    results = [code_to_result[e["instrument_code"]] for e in entries
               if e["instrument_code"] in code_to_result]

    # ── JSON output ───────────────────────────────────────────────────────────
    OUTPUT_JSON.write_text(json.dumps(results, indent=2, ensure_ascii=False))

    # ── CSV output ────────────────────────────────────────────────────────────
    csv_fields = ["instrument_code", "mission_name", "instrument_name", "description",
                  "aliases", "parent_suite", "operational_notes",
                  "commonly_confused_with", "confidence", "error"]
    with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=csv_fields, extrasaction="ignore")
        writer.writeheader()
        for r in results:
            row = {**r}
            if isinstance(row.get("aliases"), list):
                row["aliases"] = "; ".join(row["aliases"])
            if isinstance(row.get("commonly_confused_with"), list):
                row["commonly_confused_with"] = "; ".join(row["commonly_confused_with"])
            if isinstance(row.get("sub_instruments"), list):
                row.pop("sub_instruments", None)
            writer.writerow(row)

    errors = sum(1 for r in results if "error" in r)
    print()
    print(f"Done.")
    print(f"  Processed : {len(results)}")
    print(f"  Errors    : {errors}")
    print(f"  JSON      : {OUTPUT_JSON}")
    print(f"  CSV       : {OUTPUT_CSV}")
    print()
    print("Review and correct the draft, then copy to:")
    print(f"  {DATA_ASSETS_DIR}/vso/instrument_aliases.json")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--tag",      help="Only process instruments seen in papers with this tag")
    group.add_argument("--missions", help="Comma-separated mission names to filter to")
    args = parser.parse_args()
    asyncio.run(main(args))

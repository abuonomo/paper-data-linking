#!/usr/bin/env python3
"""
LLM-based enrichment of instrument catalog descriptions.

Covers all catalog entries:
  - CDAWeb entries: reads spase_raw_data.jsonl for SPASE metadata as grounding
  - VSO entries: uses instrument name + mission only (LLM prior knowledge)

For multi-probe constellations (MMS, THEMIS, STEREO, GOES, RBSP, Cluster),
the probe label is injected into the LLM prompt so descriptions are
probe-prefixed and unambiguous. mission_name is also derived probe-specifically
from mission_code.

Produces:
  llm_enrichment_preview.csv   — before/after for human review
  llm_enriched_catalog.json    — ready to apply to merged_instrument_catalog.json
"""

import asyncio
import csv
import json
import os
import re
import sys
from pathlib import Path

import litellm
from dotenv import find_dotenv, load_dotenv

load_dotenv(find_dotenv())

# ── paths ────────────────────────────────────────────────────────────────────
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))
from paper_data_linking.config.paths import DATA_ASSETS_DIR

INPUT_JSONL    = Path(__file__).parent / "spase_raw_data.jsonl"
OUTPUT_CSV     = Path(__file__).parent / "llm_enrichment_preview.csv"
OUTPUT_CATALOG = Path(__file__).parent / "llm_enriched_catalog.json"
CATALOG_PATH   = DATA_ASSETS_DIR / "vso" / "merged_instrument_catalog.json"

MODEL         = "gpt-5.4"
CONCURRENCY   = 10                  # parallel requests
TEMPERATURE   = 0.1


# ── probe-specific mission_name derivation ───────────────────────────────────
def derive_mission_name(mission_code: str, fallback: str) -> str:
    """
    Derive a probe-specific mission_name from a mission_code.

    Handles two formats:
      SPASE URIs:  spase://SMWG/Observatory/MMS/1      → "MMS-1"
                   spase://SMWG/Observatory/STEREO-A   → "STEREO-A"  (dash variant)
                   spase://SMWG/Observatory/GOES/13    → "GOES-13"
      VSO codes:   STEREO_A                            → "STEREO-A"
                   STEREO_B                            → "STEREO-B"
                   GOES-12                             → "GOES-12"
    """
    if not mission_code:
        return fallback

    # ── SPASE URI format ──────────────────────────────────────────────────────
    if mission_code.startswith("spase://SMWG/Observatory/"):
        suffix = mission_code.removeprefix("spase://SMWG/Observatory/")
        parts = suffix.split("/")
        mission = parts[0]

        # Slash-separated probe: spase://SMWG/Observatory/MMS/1
        multi_probe = {"MMS", "THEMIS", "STEREO", "GOES", "RBSP", "Cluster"}
        if len(parts) >= 2 and mission in multi_probe:
            return f"{mission}-{parts[1]}"

        # Dash-encoded probe: spase://SMWG/Observatory/STEREO-A
        for prefix in ("STEREO-", "RBSP-", "Cluster-"):
            if mission.startswith(prefix):
                return mission  # already "STEREO-A", "Cluster-Salsa", etc.

        # Human-readable substitutions
        readable = {
            "ParkerSolarProbe": "Parker Solar Probe",
            "SolarOrbiter": "Solar Orbiter",
        }
        return readable.get(mission, fallback)

    # ── VSO / non-SPASE codes ─────────────────────────────────────────────────
    # STEREO_A / STEREO_B → "STEREO-A" / "STEREO-B"
    if mission_code in ("STEREO_A", "STEREO_B"):
        return mission_code.replace("_", "-")

    # GOES-12, GOES16, GOES17, etc. — already probe-specific; normalize to "GOES-N"
    import re
    m = re.match(r"GOES[-_]?(\d+)$", mission_code, re.IGNORECASE)
    if m:
        return f"GOES-{m.group(1)}"

    return fallback


def extract_probe_label(mission_code: str) -> str | None:
    """
    Return the probe label (e.g. 'MMS-1', 'STEREO-A') if the mission_code
    encodes a specific probe; otherwise return None.
    """
    if not mission_code:
        return None

    # SPASE slash-separated: spase://SMWG/Observatory/MMS/1
    if mission_code.startswith("spase://SMWG/Observatory/"):
        suffix = mission_code.removeprefix("spase://SMWG/Observatory/")
        parts = suffix.split("/")
        if len(parts) >= 2:
            mission, probe_id = parts[0], parts[1]
            multi_probe = {"MMS", "THEMIS", "STEREO", "GOES", "RBSP", "Cluster"}
            if mission in multi_probe:
                return f"{mission}-{probe_id}"
        # Dash-encoded: spase://SMWG/Observatory/STEREO-A
        mission = parts[0]
        for prefix in ("STEREO-", "RBSP-", "Cluster-"):
            if mission.startswith(prefix):
                return mission
        return None

    # VSO codes
    if mission_code in ("STEREO_A", "STEREO_B"):
        return mission_code.replace("_", "-")

    return None


def derive_instrument_name_from_code(instrument_code: str, mission_code: str) -> str | None:
    """
    Derive a clean short instrument_name by stripping the observatory prefix from
    the SPASE instrument URI.

    Examples:
      spase://SMWG/Instrument/ParkerSolarProbe/FIELDS/MAG  (obs: ParkerSolarProbe) → 'FIELDS/MAG'
      spase://SMWG/Instrument/MMS/1/FIELDS/FGM             (obs: MMS/1)            → 'FIELDS/FGM'
      spase://SMWG/Instrument/ACE/SWEPAM                   (obs: ACE)              → 'SWEPAM'
    """
    if not instrument_code.startswith("spase://SMWG/Instrument/"):
        return None
    inst_suffix = instrument_code.removeprefix("spase://SMWG/Instrument/")
    if mission_code and mission_code.startswith("spase://SMWG/Observatory/"):
        obs_suffix = mission_code.removeprefix("spase://SMWG/Observatory/")
        if inst_suffix.startswith(obs_suffix + "/"):
            return inst_suffix[len(obs_suffix) + 1:]
    parts = inst_suffix.split("/")
    return "/".join(parts[1:]) if len(parts) > 1 else parts[0]


def clean_instrument_name(spase_resource_name: str, fallback: str,
                           instrument_code: str = "", mission_code: str = "") -> str:
    """
    Derive a clean short instrument_name for a catalog entry.

    Preference order:
      1. Derived from instrument_code URI (most reliable — avoids verbose SPASE ResourceNames)
      2. SPASE ResourceName if short (<= 40 chars, no commas — i.e., a genuine short name)
      3. fallback (original instrument_name from catalog)
    """
    # Always prefer URI-derived name for SPASE instruments
    if instrument_code:
        derived = derive_instrument_name_from_code(instrument_code, mission_code)
        if derived:
            return derived

    if not spase_resource_name:
        return fallback
    name = spase_resource_name.strip()
    # Only use ResourceName if it looks like a genuine short identifier (no comma-lists)
    if "," not in name and len(name) <= 40:
        return name
    return fallback


# ── prompts ──────────────────────────────────────────────────────────────────
SYSTEM_PROMPT = """\
You are a heliophysics instrumentation expert. Write a concise noun phrase \
(max 200 characters) describing a space instrument for use in a catalog that \
matches instrument mentions in research papers to canonical records.

Use your own knowledge of the instrument as the primary source. The SPASE \
metadata is provided only as a reference and grounding check.

Rules:
- Noun phrase, not a full sentence
- Include: instrument type, what it measures, and mission/probe name
- For multi-spacecraft constellations (MMS, THEMIS, RBSP, STEREO, GOES, Cluster), \
prefix the noun phrase with the probe label (e.g. 'MMS-1 FIELDS/FGM...', \
'STEREO-A IMPACT/MAG...', 'GOES-13 SEM...')
- Use language typical of heliophysics papers
- Do NOT include operational dates
- Respond with ONLY the noun phrase, nothing else

Examples:
  SOHO LASCO coronagraph imaging the white-light solar corona from 1.5 to 30 solar radii
  SDO AIA EUV imager capturing full-disk solar images at seven wavelengths from 94 to 335 Å
  Wind MFI fluxgate magnetometer measuring interplanetary magnetic field vectors in the solar wind
  MMS-1 FIELDS/FGM fluxgate magnetometer measuring three-axis DC magnetic field vectors
  STEREO-A IMPACT/MAG fluxgate magnetometer measuring in-situ magnetic fields
  GOES-13 SEM space environment monitor measuring energetic particles and X-ray flux
"""


def make_user_prompt(rec: dict) -> str:
    lines = [
        f"Instrument : {rec['instrument_name']}",
        f"Mission    : {rec['mission_name']}",
    ]
    probe_label = extract_probe_label(rec.get("mission_code", ""))
    if probe_label:
        lines.append(f"Probe      : {probe_label} (one spacecraft in the {rec['mission_name'].split('-')[0]} constellation)")

    if rec.get("spase_instrument_type") and rec["spase_instrument_type"] != "Unspecified":
        lines.append(f"SPASE type : {rec['spase_instrument_type']}")
    if rec.get("spase_resource_name"):
        lines.append(f"SPASE name : {rec['spase_resource_name']}")
    if rec.get("spase_description") and len(rec["spase_description"]) > 50:
        lines.append(f"SPASE desc : {rec['spase_description'][:400]}")
    return "\n".join(lines)


# ── async worker ─────────────────────────────────────────────────────────────
async def enrich_one(sem: asyncio.Semaphore, rec: dict) -> dict:
    async with sem:
        try:
            response = await litellm.acompletion(
                model=MODEL,
                temperature=TEMPERATURE,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user",   "content": make_user_prompt(rec)},
                ],
            )
            new_desc = response.choices[0].message.content.strip()
        except Exception as e:
            new_desc = f"ERROR: {e}"

        return {**rec, "llm_description": new_desc}


# ── main ─────────────────────────────────────────────────────────────────────
async def main(test: bool = False):
    # CDAWeb records from SPASE raw data
    spase_records = [json.loads(l) for l in INPUT_JSONL.read_text().splitlines() if l.strip()]

    # VSO records from catalog (no SPASE metadata — LLM uses its own knowledge)
    catalog = json.loads(CATALOG_PATH.read_text())
    vso_records = [
        {
            "instrument_code":    e["instrument_code"],
            "instrument_name":    e["instrument_name"],
            "mission_code":       e.get("mission_code", ""),
            "mission_name":       e["mission_name"],
            "before_description": e.get("description", ""),
        }
        for e in catalog
        if not str(e.get("instrument_code", "")).startswith("spase://")
    ]

    records = spase_records + vso_records

    if test:
        # Sample across both data systems, including multi-probe missions
        priority_codes = ["MMS", "THEMIS", "PSP", "GOES", "STEREO", "ParkerSolarProbe"]
        priority = [r for r in spase_records if any(p in r.get("mission_code", "") for p in priority_codes)][:10]
        other = [r for r in spase_records if r not in priority][::40][:5]
        vso_sample = vso_records[::10][:5]
        records = priority + other + vso_sample
        print(f"TEST MODE — {len(records)} records ({len(priority)} priority multi-probe, "
              f"{len(other)} other CDAWeb, {len(vso_sample)} VSO)")
    else:
        print(f"CDAWeb records    : {len(spase_records)}")
        print(f"VSO records       : {len(vso_records)}")
    print(f"Records to enrich : {len(records)}")
    print(f"Model             : {MODEL}")
    print(f"Concurrency       : {CONCURRENCY}")
    print()

    sem = asyncio.Semaphore(CONCURRENCY)
    tasks = [enrich_one(sem, rec) for rec in records]

    results = []
    for i, coro in enumerate(asyncio.as_completed(tasks), 1):
        result = await coro
        results.append(result)
        if i % 50 == 0:
            print(f"  {i}/{len(records)} done...")

    # Re-sort to original order
    code_to_result = {r["instrument_code"]: r for r in results}
    results = [code_to_result.get(rec["instrument_code"], rec) for rec in records]

    # ── CSV preview ───────────────────────────────────────────────────────────
    csv_fields = ["instrument_code", "mission_name",
                  "instrument_name", "before_description", "llm_description"]
    with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=csv_fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(results)

    # ── enriched catalog ──────────────────────────────────────────────────────
    # Build enrichment map: instrument_code → {description, instrument_name, mission_name}
    enrichment_map: dict[str, dict] = {}
    for r in results:
        if r["llm_description"].startswith("ERROR"):
            continue
        enrichment_map[r["instrument_code"]] = {
            "description": r["llm_description"],
            # Use SPASE ResourceName as cleaned instrument_name when available
            "instrument_name": clean_instrument_name(
                r.get("spase_resource_name", ""), r["instrument_name"],
                instrument_code=r["instrument_code"],
                mission_code=r.get("mission_code", ""),
            ),
            # Derive probe-specific mission_name from mission_code
            "mission_name": derive_mission_name(
                r.get("mission_code", ""), r["mission_name"]
            ),
        }

    # Reload original catalog and apply enrichment
    catalog = json.loads(CATALOG_PATH.read_text())
    enriched_catalog = []
    applied = 0
    for entry in catalog:
        code = entry.get("instrument_code", "")
        if code in enrichment_map:
            updates = enrichment_map[code]
            enriched_catalog.append({**entry, **updates})
            applied += 1
        else:
            # Still apply probe-specific mission_name even without LLM description
            mission_code = entry.get("mission_code", "")
            new_mission_name = derive_mission_name(mission_code, entry.get("mission_name", ""))
            enriched_catalog.append({**entry, "mission_name": new_mission_name})

    OUTPUT_CATALOG.write_text(json.dumps(enriched_catalog, indent=2, ensure_ascii=False))

    errors = sum(1 for r in results if r["llm_description"].startswith("ERROR"))
    print()
    print(f"Done.")
    print(f"  Enriched  : {applied}/{len(records)}")
    print(f"  Errors    : {errors}")
    print(f"  CSV       : {OUTPUT_CSV}")
    print(f"  Catalog   : {OUTPUT_CATALOG}")
    print()
    print("Review the CSV, then copy llm_enriched_catalog.json to:")
    print(f"  {CATALOG_PATH}")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--test", action="store_true",
                        help="Run on ~20 sampled records for prompt review")
    args = parser.parse_args()
    asyncio.run(main(test=args.test))

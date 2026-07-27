#!/usr/bin/env python3
"""
v2 LLM enrichment of instrument catalog descriptions.

Changes vs enrich_catalog_with_llm.py (v1):
  - Model: gpt-5.5
  - Richer descriptions (no 200-char cap): suites enumerate sub-detectors,
    children name their parent suite and siblings, citable handles (channel
    names, energy/frequency/wavelength ranges) are kept, campaign units get
    per-unit identity. Derived from the catalog description audit (June 2026)
    and issues #171/#172/#156/#173.
  - Full SPASE description passed to the model (v1 truncated to 400 chars).
  - Optional REVIEW_NOTE output line when SPASE metadata conflicts with the
    model's domain knowledge (e.g. pre-flight configuration names) -> surfaced
    as a separate CSV column for human review.

Outputs (does NOT touch the live catalog):
  llm_enrichment_preview_v2.csv
  llm_enriched_catalog_v2.json
"""

import asyncio
import csv
import json
import sys
from pathlib import Path

import litellm
from dotenv import find_dotenv, load_dotenv

load_dotenv(find_dotenv())

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
project_root = HERE.parent.parent
sys.path.insert(0, str(project_root))

# Reuse v1 helpers and record loading
from enrich_catalog_with_llm import (  # noqa: E402
    clean_instrument_name,
    derive_mission_name,
    extract_probe_label,
)
from paper_data_linking.config.paths import DATA_ASSETS_DIR  # noqa: E402

INPUT_JSONL    = HERE / "spase_raw_data.jsonl"
OUTPUT_CSV     = HERE / "llm_enrichment_preview_v2.csv"
OUTPUT_CATALOG = HERE / "llm_enriched_catalog_v2.json"
CATALOG_PATH   = DATA_ASSETS_DIR / "vso" / "merged_instrument_catalog.json"

MODEL       = "gpt-5.5"
CONCURRENCY = 10

SYSTEM_PROMPT = """\
You are a heliophysics instrumentation expert. Write a rich catalog description \
of a space instrument. The description is used two ways: (1) embedded for \
similarity search against instrument mentions in research papers, and (2) shown \
to an LLM validation agent that must judge whether a paper's instrument mention \
matches this catalog record. The validator treats your text as ground truth, so \
every sub-instrument, component, and measurement range you omit is a potential \
false negative.

Use your own knowledge of the instrument as the primary source. The SPASE \
metadata is grounding/reference; it is sometimes stale or describes pre-flight \
configurations.

Rules:
- Open with the established pattern: <Probe/Mission> <ACRONYM> (<expanded name>) \
<instrument type> measuring <quantities>. Expand every acronym exactly once.
- Instrument SUITES must enumerate their sub-instruments/sensors by the names \
papers cite: "comprising A (expanded), B (expanded), ...". Include sensors papers \
reference even if the SPASE text omits them.
- SUB-INSTRUMENT entries must name their parent suite and sibling sensors \
(e.g. "one of the three SMS suite sensors alongside SWICS and MASS").
- CAUTION: if the record ID names one sensor but the SPASE ResourceName or \
description shows the record covers a COMBINED investigation (e.g. ID ends in \
/FGM but ResourceName is "Magnetic Field (HED/VHM/FGM)"), describe the record \
as the combined investigation comprising its sensors. Never frame such a record \
as "one sensor alongside its sibling" — downstream validation treats mentions \
of the sibling as invalid sibling-instrument matches.
- Keep citable handles: sub-instrument names, channel/band names, \
energy/frequency/wavelength ranges. Drop engineering internals: detector layer \
names, electronics, geometry factors, telemetry modes, mass/power.
- Campaign or fleet units (balloons, sounding-rocket flights, GOES generations, \
LANL satellites) need per-unit identity: unit designation, campaign, and years. \
No two units may share identical text.
- For multi-spacecraft constellations (MMS, THEMIS, RBSP, STEREO, GOES, Cluster), \
prefix with the probe label (e.g. 'MMS-1 FIELDS/FGM...', 'STEREO-A IMPACT/MAG...').
- Do not include operational date ranges UNLESS they are identity-defining \
(campaign flights, fleet generations) — mission-level history lives elsewhere.
- Target 250-450 characters. One sentence or clause chain; no bullet lists.
- Use language typical of heliophysics papers.

Output format:
- First line: ONLY the description.
- If (and only if) the SPASE metadata conflicts with your knowledge of the flown \
instrument (wrong sub-instrument names, pre-flight configuration, wrong scope), \
add a second line: "REVIEW_NOTE: <one-sentence explanation of the conflict>". \
If you are not confident about sub-instrument names from your own knowledge, \
stick to the SPASE text and do not guess.

Examples:
  Ulysses magnetic field investigation (HED/VHM/FGM), combining a triaxial fluxgate magnetometer (FGM) and a vector helium magnetometer (VHM) to measure interplanetary magnetic field strength and direction in the inner heliosphere, including over the Sun's poles at high solar latitudes

  SOHO CELIAS (Charge, Element, and Isotope Analysis System) time-of-flight mass spectrometer suite measuring solar wind ion charge states, elemental abundances, and isotopic composition; comprising the CTOF (charge time-of-flight), MTOF (mass time-of-flight, with its Proton Monitor PM) and STOF (suprathermal time-of-flight) sensors plus the SEM (Solar EUV Monitor) absolute EUV flux detector

  Wind WAVES plasma and radio wave investigation measuring electric and magnetic field waveforms and radio emissions in the solar wind from a fraction of a Hz to ~14 MHz; comprising the RAD1 and RAD2 radio receivers, the TNR thermal noise receiver, and the TDS time domain sampler, fed by spin-plane and axial electric dipole antennas and a triaxial search coil

  Parker Solar Probe SPAN-A (Solar Probe Analyzer A), the ram-side sensor pair of the SWEAP (Solar Wind Electrons Alphas and Protons) suite alongside the SPC Faraday cup and SPAN-B; combines an ion electrostatic analyzer with time-of-flight mass discrimination (few eV/q to 20 keV/q) and an electron electrostatic analyzer measuring solar wind velocity distributions

  BARREL Balloon 1A X-ray instrument (XRI), a NaI scintillator spectrometer (10 keV-10 MeV) measuring bremsstrahlung X-rays from precipitating radiation-belt electrons; payload 1A of the first BARREL Antarctic balloon campaign (2012-2013), conjugate with the Van Allen Probes

  SAMPEX MAST (Mass Spectrometer Telescope) measuring isotopic composition of energetic nuclei from lithium to nickel (Z=3-28) at 10 to several hundred MeV/nucleon with ~0.2 amu mass resolution, complementing the LICA, HILT, and PET instruments on SAMPEX
"""


def make_user_prompt(rec: dict) -> str:
    lines = [
        f"Instrument : {rec['instrument_name']}",
        f"Mission    : {rec['mission_name']}",
    ]
    probe_label = extract_probe_label(rec.get("mission_code", ""))
    if probe_label:
        lines.append(
            f"Probe      : {probe_label} (one spacecraft in the "
            f"{rec['mission_name'].split('-')[0]} constellation)"
        )
    if rec.get("spase_instrument_type") and rec["spase_instrument_type"] != "Unspecified":
        lines.append(f"SPASE type : {rec['spase_instrument_type']}")
    if rec.get("spase_resource_name"):
        lines.append(f"SPASE name : {rec['spase_resource_name']}")
    if rec.get("spase_description") and len(rec["spase_description"]) > 50:
        lines.append(f"SPASE desc : {rec['spase_description'][:3000]}")
    return "\n".join(lines)


def parse_response(text: str) -> tuple[str, str]:
    """Split model output into (description, review_note)."""
    desc_lines, note = [], ""
    for line in text.strip().splitlines():
        if line.strip().startswith("REVIEW_NOTE:"):
            note = line.strip().removeprefix("REVIEW_NOTE:").strip()
        elif line.strip():
            desc_lines.append(line.strip())
    return " ".join(desc_lines), note


async def enrich_one(sem: asyncio.Semaphore, rec: dict) -> dict:
    async with sem:
        try:
            response = await litellm.acompletion(
                model=MODEL,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": make_user_prompt(rec)},
                ],
            )
            desc, note = parse_response(response.choices[0].message.content)
        except Exception as e:
            desc, note = f"ERROR: {e}", ""
        return {**rec, "llm_description": desc, "review_note": note}


# Curated smoke-test set: known issues + one of each gotcha category
TEST_CODES = [
    "spase://SMWG/Instrument/Ulysses/FGM",          # 171 component scope
    "CELIAS",                                        # 172/156 suite enumeration (VSO, no SPASE)
    "COSTEP",                                        # 156
    "spase://SMWG/Instrument/Wind/WAVES",            # suite, SPASE lacks canonical names
    "spase://SMWG/Instrument/Wind/3DP",              # suite
    "spase://SMWG/Instrument/Wind/EPACT",            # stale SPASE (LEAD vs LEMT/STEP/ELITE)
    "spase://SMWG/Instrument/POLAR/CEPPAD",          # stale SPASE (IPS/IES)
    "spase://SMWG/Instrument/STEREO-A/IMPACT",       # 7-instrument suite
    "spase://SMWG/Instrument/ParkerSolarProbe/SWEAP/SPAN-A",  # child->parent linkage
    "spase://SMWG/Instrument/Wind/SMS/STICS",        # child->parent linkage
    "spase://SMWG/Instrument/BARREL/1A/XRI",         # campaign identity
    "spase://SMWG/Instrument/BARREL/1B/XRI",         # campaign identity (must differ from 1A)
    "spase://SMWG/Instrument/LANL/2001/MPA",         # fleet identity
    "spase://SMWG/Instrument/SAMPEX/MAST",           # selectivity: drop internals
    "spase://SMWG/Instrument/TIMED/GUVI",            # selectivity: keep channels
    "spase://SMWG/Instrument/MMS/1/FIELDS/FGM",      # probe prefix regression check
    "spase://SMWG/Instrument/GOES/12/SEM",           # probe prefix regression check
    "EIT",                                           # simple VSO instrument (should stay tight)
]


async def main(test: bool = False):
    spase_records = [json.loads(l) for l in INPUT_JSONL.read_text().splitlines() if l.strip()]
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
        by_code = {r["instrument_code"]: r for r in records}
        records = [by_code[c] for c in TEST_CODES if c in by_code]
        missing = [c for c in TEST_CODES if c not in by_code]
        print(f"TEST MODE — {len(records)} curated records" + (f" (missing: {missing})" if missing else ""))
    else:
        print(f"CDAWeb records    : {len(spase_records)}")
        print(f"VSO records       : {len(vso_records)}")
    print(f"Records to enrich : {len(records)}")
    print(f"Model             : {MODEL}")
    print()

    sem = asyncio.Semaphore(CONCURRENCY)
    tasks = [enrich_one(sem, rec) for rec in records]
    results = []
    for i, coro in enumerate(asyncio.as_completed(tasks), 1):
        results.append(await coro)
        if i % 50 == 0:
            print(f"  {i}/{len(records)} done...")

    code_to_result = {(r.get("mission_code", ""), r["instrument_code"]): r for r in results}
    results = [code_to_result.get((rec.get("mission_code", ""), rec["instrument_code"]), rec)
               for rec in records]

    csv_fields = ["instrument_code", "mission_name", "instrument_name",
                  "before_description", "llm_description", "review_note"]
    with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=csv_fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(results)

    # Key by (mission_code, instrument_code): VSO short codes like "IMPACT" repeat
    # across missions (STEREO_A/STEREO_B), and code-only keying assigns one
    # mission's description to every same-named entry.
    enrichment_map: dict[tuple, dict] = {}
    for r in results:
        if r["llm_description"].startswith("ERROR"):
            continue
        enrichment_map[(r.get("mission_code", ""), r["instrument_code"])] = {
            "description": r["llm_description"],
            "instrument_name": clean_instrument_name(
                r.get("spase_resource_name", ""), r["instrument_name"],
                instrument_code=r["instrument_code"],
                mission_code=r.get("mission_code", ""),
            ),
            "mission_name": derive_mission_name(r.get("mission_code", ""), r["mission_name"]),
        }

    enriched_catalog = []
    applied = 0
    for entry in catalog:
        key = (entry.get("mission_code", ""), entry.get("instrument_code", ""))
        if key in enrichment_map:
            enriched_catalog.append({**entry, **enrichment_map[key]})
            applied += 1
        else:
            new_mission_name = derive_mission_name(entry.get("mission_code", ""), entry.get("mission_name", ""))
            enriched_catalog.append({**entry, "mission_name": new_mission_name})
    OUTPUT_CATALOG.write_text(json.dumps(enriched_catalog, indent=2, ensure_ascii=False))

    errors = sum(1 for r in results if r["llm_description"].startswith("ERROR"))
    notes = sum(1 for r in results if r["review_note"])
    print(f"\nDone. Applied {applied}/{len(catalog)} | errors {errors} | review notes {notes}")
    print(f"  CSV     : {OUTPUT_CSV}")
    print(f"  Catalog : {OUTPUT_CATALOG}")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--test", action="store_true", help="Run on curated smoke-test records")
    args = parser.parse_args()
    asyncio.run(main(test=args.test))

#!/usr/bin/env python3
"""Replay the exact validation LLM calls behind issues #171/#172/#173,
with the current (old) descriptions vs the v2 descriptions.

Uses the real prompt templates via load_and_render_prompt and the same model
the prod config (bedrock-120b-high-v3) uses for validation:
bedrock/converse/openai.gpt-oss-120b-1:0, temperature 1.0.

Each condition runs N_REPS times (temp 1.0 is nondeterministic).
"""
import asyncio
import json
import re
import sys
from pathlib import Path

import litellm
from dotenv import find_dotenv, load_dotenv

load_dotenv(find_dotenv())
litellm.drop_params = True

# Prefer the bedrock-admin profile over (possibly stale) .env static keys
import os  # noqa: E402
if os.environ.get("AWS_PROFILE"):
    for k in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN"):
        os.environ.pop(k, None)

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
from paper_data_linking.linkers.general.prompt_loader import load_and_render_prompt  # noqa: E402

MODEL = os.environ.get("REPLAY_MODEL", "bedrock/converse/openai.gpt-oss-120b-1:0")
REGION = "us-west-2"
N_REPS = 3

OLD = {e["instrument_code"]: e for e in json.loads(
    (ROOT / "paper_data_linking/data_assets/vso/merged_instrument_catalog.json").read_text())}
NEW = {e["instrument_code"]: e for e in json.loads(
    (ROOT / "experiments/instrument_grounding_evaluation/llm_enriched_catalog_v2.json").read_text())}

WIND_MISSION_OLD = (
    "NASA's Wind spacecraft studies the solar wind, interplanetary plasma, energetic "
    "particles, and waves from a halo orbit around the Sun-Earth L1 point, providing key "
    "heliophysics measurements of the upstream solar wind and near-Earth space environment."
)
WIND_MISSION_NEW = (
    "NASA's Wind spacecraft (launched 1994) studies the solar wind, interplanetary plasma, "
    "energetic particles, and radio/plasma waves. From 1994 to 2004 it flew highly elliptical "
    "petal orbits repeatedly crossing Earth's magnetosphere and radiation belts, with lunar "
    "swingbys and deep magnetotail excursions, before moving permanently in 2004 to a halo "
    "orbit at the Sun-Earth L1 point, where it monitors the upstream solar wind."
)

CASES = []

# ── #171: Ulysses VHM mention vs FGM record ──────────────────────────────────
for label, desc in [("old", OLD["spase://SMWG/Instrument/Ulysses/FGM"]["description"]),
                    ("v2",  NEW["spase://SMWG/Instrument/Ulysses/FGM"]["description"])]:
    CASES.append({
        "case": "#171 Ulysses VHM->FGM", "version": label, "template": "validation",
        "vars": dict(
            original_name="Vector-helium magnetometer",
            original_comments="Vector-helium magnetometer on board Ulysses spacecraft used to "
                              "measure the heliospheric magnetic field",
            matched_instrument_name="Magnetic Field (HED/VHM/FGM)",
            matched_instrument_code="spase://SMWG/Instrument/Ulysses/FGM",
            matched_instrument_description=desc,
            matched_mission_name="Ulysses",
            matched_mission_code="spase://SMWG/Observatory/Ulysses",
            period_infos=[],
        ),
    })

# ── #172: CELIAS PM sub-detector ─────────────────────────────────────────────
for label, desc in [("old", OLD["CELIAS"]["description"]),
                    ("v2",  NEW["CELIAS"]["description"])]:
    CASES.append({
        "case": "#172 PM->CELIAS", "version": label, "template": "validation",
        "vars": dict(
            original_name="PM",
            original_comments="PM on board SOHO spacecraft providing solar wind proton "
                              "density and speed measurements",
            matched_instrument_name="Charge, Element, and Isotope Analysis System",
            matched_instrument_code="CELIAS",
            matched_instrument_description=desc,
            matched_mission_name="Solar and Heliospheric Observatory",
            matched_mission_code="SOHO",
            period_infos=[],
        ),
    })

# ── #173: Wind radiation-belt observation vs L1 mission description ─────────
for label, desc in [("old", WIND_MISSION_OLD), ("v2", WIND_MISSION_NEW)]:
    CASES.append({
        "case": "#173 Wind 1998 rad belts", "version": label, "template": "mission_validation",
        "vars": dict(
            original_name="Wind WAVES",
            original_comments="Whistler-mode waves observed in Earth's radiation belts with "
                              "the WAVES instrument on board the Wind spacecraft",
            matched_mission_name="Wind",
            matched_mission_code="spase://SMWG/Observatory/Wind",
            matched_mission_description=desc,
            period_infos=["Time period: 1998; Observes: whistler-mode plasma waves in the "
                          "outer radiation belt"],
        ),
    })


def decision_of(text: str) -> str:
    m = re.search(r"FINAL DECISION:\s*\**\s*(valid|invalid)", text, re.I)
    return m.group(1).lower() if m else "??"


async def run_one(sem, case, rep):
    system_msg, user_msg = load_and_render_prompt(case["template"], **case["vars"])
    async with sem:
        try:
            resp = await litellm.acompletion(
                model=MODEL, temperature=1.0, aws_region_name=REGION,
                messages=[{"role": "system", "content": system_msg},
                          {"role": "user", "content": user_msg}],
            )
            text = resp.choices[0].message.content or ""
            return {**case, "rep": rep, "decision": decision_of(text), "raw": text}
        except Exception as e:
            return {**case, "rep": rep, "decision": f"ERROR: {e}", "raw": ""}


async def main():
    sem = asyncio.Semaphore(6)
    tasks = [run_one(sem, c, r) for c in CASES for r in range(N_REPS)]
    results = await asyncio.gather(*tasks)

    slug = re.sub(r"[^a-z0-9]+", "-", MODEL.lower()).strip("-")
    out = Path(__file__).parent / f"replay_validation_results_{slug}.json"
    out.write_text(json.dumps(results, indent=1))

    print(f"{'case':28s} {'version':8s} decisions")
    for c in CASES:
        decs = [r["decision"] for r in results
                if r["case"] == c["case"] and r["version"] == c["version"]]
        print(f"{c['case']:28s} {c['version']:8s} {decs}")
    print(f"\nfull transcripts -> {out}")


if __name__ == "__main__":
    asyncio.run(main())

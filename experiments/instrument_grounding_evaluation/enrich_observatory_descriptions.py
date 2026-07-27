#!/usr/bin/env python3
"""Regenerate observatory (mission) descriptions with orbital-phase history.

Fixes the systematic "presentism" failure (issue #173): current prod descriptions
describe only a mission's final/longest orbital phase, so the mission-validation
agent rejects observations from earlier phases (e.g. Wind's 1994-2004 elliptical
magnetospheric orbits vs its current L1 halo orbit).

Input : scratches/prod_observatories_20260413.json (prod DB snapshot dump)
Output: observatory_descriptions_v2.json  ({short_name: description} — the format
        update_observatory_descriptions expects)
        observatory_enrichment_preview.csv (name, current, new, review_note)

Run: uv run python enrich_observatory_descriptions.py [--test]
"""
import asyncio
import csv
import json
import sys
from pathlib import Path

import litellm
from dotenv import load_dotenv

HERE = Path(__file__).parent
ROOT = HERE.parent.parent
load_dotenv(ROOT / ".env")
litellm.drop_params = True

MODEL = "gpt-5.5"
CONCURRENCY = 10
INPUT = ROOT / "scratches/prod_observatories_20260413.json"
OUT_JSON = HERE / "observatory_descriptions_v2.json"
OUT_CSV = HERE / "observatory_enrichment_preview.csv"

SYSTEM_PROMPT = """\
You are a heliophysics mission expert. Write a catalog description of a space \
mission/observatory (or ground-based observatory). The description is shown to \
an LLM validation agent that judges whether a paper's described observations \
could have come from this mission. The agent treats your text as ground truth \
about WHERE the mission was and WHEN — so omitting an orbital phase makes \
observations from that phase look impossible and causes false rejections.

Rules:
- Include the launch year (or operational start) and, if ended, the end year.
- CRITICAL - orbital history: if the mission's trajectory or vantage point \
changed over its life (elliptical orbits before a Lagrange-point halo, planetary \
flybys used for gravity assists with science, deep-tail campaigns, orbit \
raising/relocation, extended-mission phases at new targets), state each phase \
with its years. Never describe only the final or longest phase.
- If the orbit never changed, state it once, simply.
- State the science domain and what the mission observes/measures.
- Optionally name flagship instruments if widely cited.
- Ground-based observatories and station networks: give location/network and \
observation type instead of orbit.
- Multi-spacecraft entries (constellation members, fleet units like LANL/GOES \
satellites): identify the specific unit and its operational years.
- 250-550 characters. Plain prose, no bullet lists.
- Do NOT invent orbital phases you are not confident about. If unsure, describe \
what you know and flag it.

Output format:
- First line: ONLY the description.
- Optional second line: "REVIEW_NOTE: <one sentence>" if (a) you are uncertain \
about the orbital history, or (b) the current description provided conflicts \
with your knowledge.

Examples:
  NASA's Wind spacecraft (launched 1994) studies the solar wind, interplanetary plasma, energetic particles, and radio/plasma waves. From 1994 to 2004 it flew highly elliptical petal orbits repeatedly crossing Earth's magnetosphere and radiation belts, with lunar swingbys and deep magnetotail excursions, before moving permanently in 2004 to a halo orbit at the Sun-Earth L1 point, where it monitors the upstream solar wind.

  Ulysses was a joint ESA/NASA mission (1990-2009) studying the heliosphere in three dimensions. After launch it cruised in the ecliptic to Jupiter, using a February 1992 Jovian flyby (with magnetospheric measurements) to enter a high-inclination heliocentric orbit, then completed three polar passes of the Sun (1994-95, 2000-01, 2006-08) with instruments for solar wind plasma and composition, magnetic fields, energetic particles, and radio/plasma waves.

  ACE (Advanced Composition Explorer, launched 1997) orbits the Sun-Earth L1 point, providing near-continuous upstream measurements of solar wind plasma, magnetic field, ion composition, and energetic particles for heliophysics and space weather; its orbit has not changed over the mission.
"""


def user_prompt(o):
    lines = [f"Mission/Observatory: {o['name']}",
             f"Registry ID: {o['short_name']}",
             f"Data system: {o.get('datasource', '?')}"]
    if (o.get("description") or "").strip():
        lines.append(f"Current catalog description (accurate but may describe only "
                     f"one orbital phase): {o['description'][:600]}")
    return "\n".join(lines)


async def enrich_one(sem, o):
    async with sem:
        try:
            r = await litellm.acompletion(model=MODEL, timeout=180, num_retries=2, messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt(o)},
            ])
            note, desc_lines = "", []
            for l in r.choices[0].message.content.strip().splitlines():
                l = l.strip()
                if l.startswith("REVIEW_NOTE:"):
                    note = l.removeprefix("REVIEW_NOTE:").strip()
                elif l:
                    desc_lines.append(l)
            return {**o, "new_description": " ".join(desc_lines), "review_note": note}
        except Exception as e:
            return {**o, "new_description": f"ERROR: {e}", "review_note": ""}


TEST_IDS = ["spase://SMWG/Observatory/Wind", "spase://SMWG/Observatory/Ulysses",
            "spase://SMWG/Observatory/Geotail", "spase://SMWG/Observatory/ISEE3",
            "SOHO", "spase://SMWG/Observatory/Cluster-Rumba",
            "spase://SMWG/Observatory/LANL/1991", "GOES17",
            "spase://SMWG/Observatory/Ground/PENGUIn.1", "TRACE"]


async def main(test=False):
    observatories = json.loads(INPUT.read_text())
    if test:
        observatories = [o for o in observatories if o["short_name"] in TEST_IDS]
        print(f"TEST MODE - {len(observatories)} observatories")
    print(f"enriching {len(observatories)} observatory descriptions with {MODEL}")

    sem = asyncio.Semaphore(CONCURRENCY)
    results = []
    tasks = [enrich_one(sem, o) for o in observatories]
    for i, coro in enumerate(asyncio.as_completed(tasks), 1):
        results.append(await coro)
        if i % 50 == 0:
            print(f"  {i}/{len(observatories)}")

    by_short = {r["short_name"]: r for r in results}
    results = [by_short[o["short_name"]] for o in observatories]

    ok = {r["short_name"]: r["new_description"] for r in results
          if not r["new_description"].startswith("ERROR")}
    OUT_JSON.write_text(json.dumps(ok, indent=1, ensure_ascii=False))
    with open(OUT_CSV, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["short_name", "name", "description",
                                          "new_description", "review_note"],
                           extrasaction="ignore")
        w.writeheader()
        w.writerows(results)

    errors = sum(1 for r in results if r["new_description"].startswith("ERROR"))
    notes = sum(1 for r in results if r["review_note"])
    print(f"\ndone: {len(ok)} descriptions, {errors} errors, {notes} review notes")
    print(f"  {OUT_JSON}\n  {OUT_CSV}")


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--test", action="store_true")
    args = p.parse_args()
    asyncio.run(main(test=args.test))

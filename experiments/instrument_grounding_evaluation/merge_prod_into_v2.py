#!/usr/bin/env python3
"""Merge prod-curated instrument descriptions into llm_enriched_catalog_v2.json.

For every row where the prod DB description (April 13 snapshot) diverged from the
old catalog JSON (= prod was hand-curated, mostly operational date ranges), merge
prod's facts into the richer v2 description with gpt-5.5. Updates the v2 catalog
in place and writes a review CSV.

Inputs: /tmp/obs_data.sql, /tmp/inst_data.sql (pg_restore table extracts).
"""
import asyncio
import csv
import json
import re
import sys
from pathlib import Path

import litellm
from dotenv import load_dotenv

HERE = Path(__file__).parent
ROOT = HERE.parent.parent
load_dotenv(ROOT / ".env")
litellm.drop_params = True

MODEL = "gpt-5.5"
V2_PATH = HERE / "llm_enriched_catalog_v2.json"
OLD_PATH = ROOT / "paper_data_linking/data_assets/vso/merged_instrument_catalog.json"
OUT_CSV = HERE / "prod_merge_preview.csv"


def parse_copy(path):
    rows, cols, on = [], None, False
    for line in open(path):
        if line.startswith("COPY "):
            cols = re.search(r"\(([^)]+)\)", line).group(1).replace(" ", "").split(",")
            on = True
            continue
        if on:
            if line.strip() == "\\.":
                on = False
                continue
            vals = [None if v == "\\N" else v.replace("\\n", "\n") for v in line.rstrip("\n").split("\t")]
            rows.append(dict(zip(cols, vals)))
    return rows


SYSTEM = """\
You merge two catalog descriptions of the same space instrument into one.

Rules:
- Keep ALL distinct facts from both versions. Especially: operational date ranges
  (e.g. "(2010-2017)", "(2009-present)"), unit/flight/probe identity, sub-instrument
  enumerations with expanded acronyms, energy/frequency/wavelength ranges.
- Prefer the structure and richer wording of VERSION B.
- Place the operational date range from VERSION A (if any) in parentheses right
  after the unit designation, the way VERSION A does.
- The entry describes exactly the unit given in "Unit:". The text MUST identify
  that unit and MUST NOT attribute itself to a different unit/flight/probe.
- Max ~500 characters. Noun-phrase style, no bullet lists.
- First line: ONLY the merged description.
- If the two versions factually conflict (different dates, different sensors),
  add a second line "REVIEW_NOTE: <one sentence>".
"""


def user_prompt(unit, inst, prod_desc, v2_desc):
    return (f"Unit: {unit}\nInstrument: {inst}\n\n"
            f"VERSION A (production, hand-curated):\n{prod_desc}\n\n"
            f"VERSION B (regenerated, richer):\n{v2_desc}")


async def merge_one(sem, key, unit, inst_name, prod_desc, v2_desc):
    async with sem:
        try:
            r = await litellm.acompletion(model=MODEL, timeout=180, num_retries=2, messages=[
                {"role": "system", "content": SYSTEM},
                {"role": "user", "content": user_prompt(unit, inst_name, prod_desc, v2_desc)},
            ])
            lines = [l.strip() for l in r.choices[0].message.content.strip().splitlines() if l.strip()]
            note = ""
            desc_lines = []
            for l in lines:
                if l.startswith("REVIEW_NOTE:"):
                    note = l.removeprefix("REVIEW_NOTE:").strip()
                else:
                    desc_lines.append(l)
            return key, " ".join(desc_lines), note, None
        except Exception as e:
            return key, None, "", str(e)


async def main():
    obs = {o["id"]: o for o in parse_copy("/tmp/obs_data.sql")}
    prod = {}
    for i in parse_copy("/tmp/inst_data.sql"):
        o = obs.get(i["observatory_id"], {})
        prod[(o.get("short_name"), i["short_name"])] = (i["description"] or "").strip()

    old = {(e["mission_code"], e["instrument_code"]): e for e in json.loads(OLD_PATH.read_text())}
    v2 = json.loads(V2_PATH.read_text())
    v2_by = {(e["mission_code"], e["instrument_code"]): e for e in v2}

    jobs = []
    for k, olde in old.items():
        if k in prod and k in v2_by and prod[k] and prod[k] != (olde["description"] or "").strip():
            e = v2_by[k]
            jobs.append((k, e["mission_name"], e["instrument_name"], prod[k], e["description"]))
    print(f"merging {len(jobs)} prod-curated rows")

    sem = asyncio.Semaphore(10)
    results = await asyncio.gather(*[merge_one(sem, k, u, i, p, v) for k, u, i, p, v in jobs])

    rows, errors = [], 0
    for (k, merged, note, err), (k2, unit, iname, pdesc, vdesc) in zip(results, jobs):
        if err:
            errors += 1
            rows.append({"key": str(k), "prod": pdesc, "v2": vdesc, "merged": f"ERROR {err}", "note": ""})
            continue
        v2_by[k]["description"] = merged
        rows.append({"key": str(k), "prod": pdesc, "v2": vdesc, "merged": merged, "note": note})

    V2_PATH.write_text(json.dumps(v2, indent=2, ensure_ascii=False))
    with open(OUT_CSV, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["key", "prod", "v2", "merged", "note"])
        w.writeheader()
        w.writerows(rows)
    notes = sum(1 for r in rows if r["note"])
    print(f"done: {len(rows) - errors} merged, {errors} errors, {notes} review notes -> {OUT_CSV}")


if __name__ == "__main__":
    asyncio.run(main())

# val2026 Review Rubric — v2.1

**Status: PROPOSED.** Anthony approved 2026-08-20 · AJ sign-off: ☐ (date: ______)
Full rationale and campaign mechanics: `VALIDATION_PROTOCOL.md`. Keep this
page open while reviewing.

---

## The one rule

> **Approve iff this paper performs its own analysis on a data product whose
> values derive from this instrument, within this window — as supported by
> the paper's own words.**

- *Own analysis* = a new operation: selects events, computes, fits, plots
  from values, trains/tests a model. Restating or reproducing cited work is
  not an operation.
- *Data product* = files, catalogs, indices, composites — measurement at
  scale. Quoted results from other papers are testimony, not data.
- *Paper's own words* = every field must be traceable to the text, at the
  text's level of specificity. No world knowledge, no capability guesses.

## Decision flow, per claim

1. **Is anything factually wrong** — mission/member, instrument/sibling, or
   a window the paper never asserts? → **Incorrect + uncheck that box.**
   The box is the reason; no category needed.
2. **Tuple right, but not real usage?** → **Incorrect + pick a category**
   (all boxes stay checked):
   - *Doesn't use this data*: **Mention only** · **Cites others' work** ·
     **Reproduced figure**
   - *Analyzes no data at all*: **Instrument/design paper** · **Theory only**
   - **Other…** (note required)
3. **Real usage, faithful tuple?** → **Correct.** One click.
4. **Can't verify from the paper?** → **Unsure.** (Adjudicated later;
   excluded from precision denominators.)

Notes are optional everywhere except *Other* — but every note feeds the
usage-type census, so write them on borderline calls.

## Hard patterns — quick table

| Pattern | Call |
|---|---|
| Catalog-derived value (LASCO CME list, flare catalogs, R&C) | **approve** — tier-1 data product + own analysis qualifies |
| OMNI/composite used; claim names an **unnamed** contributor | **reject, uncheck Mission** — the paper never said it used that craft. If the paper names the sources ("i.e., ACE and Wind") → approve. Component mentioned but only the merged product analyzed → Mention only + note. |
| **Formation constellations** (MMS, Cluster in formation) | **approve members** when the paper frames observation/analysis at fleet level with **no textual restriction** — formation members co-collect; member enumeration is granularity, not invention. An explicit restriction ("use only … from SC1") rejects unnamed members (uncheck Mission). Figures alone never restrict; text does. |
| **Interchangeable series** (GOES birds) | generic mention → approve the **generic/group record** if present; specific unnamed birds → reject (uncheck Mission). Never infer the operational satellite ("should have been GOES-15" is retired). |
| Suite vs sub-instrument (SECCHI vs EUVI) | approve any level the text supports; a sibling never named (V5 when the paper says V2) → reject, uncheck Instrument |
| **GOES/N/SEM on X-ray papers** | **approve** — XRS lives under SEM in the catalog (known judge blind spot) |
| Review paper | genre never decides — a review doing its own analysis on data products qualifies; a reprinted figure doesn't |
| Instrument paper analyzing commissioning/first-light data | those claims **approve** — real windows, real operations |

## Window test (the framing rule)

Grade the window on **how the paper itself discusses the span** — never on
duty cycle or gap size:

- **Correct**: the extent matches a span the paper asserts — a duration
  ("2007 through 2018") or a collectively-framed discrete set ("throughout
  E6 to E21", "events up to the end of 2018"). Sparse interiors are fine;
  add note `window-kind: event-set envelope` for discrete sets.
- **Wrong — uncheck Time window**:
  - *Over-extension*: a date range belonging to a different dataset
    (MDI stamped 1850–2005 from a sunspot-series analysis).
  - *Granularity collapse*: a manufactured union of individually-framed
    events (one event in 1996 + one in 2016 → "1996–2016" the authors never
    assert).
- Never wrong: bounds-form quirks, rounding at the paper's own granularity
  ("January 2007" → 2007-01-01).

## Worked exemplars (calibration precedents)

| Claim | Call | Why |
|---|---|---|
| [PSP/SPAN-A envelope, 2026ApJ...997..174F](https://paper-data.helioanalytics.io/campaign/papers/00607ada-7941-42d9-989e-1b3a5f95b363/claims/333c3609-75d6-4ba8-8d5e-cc6b47698434?campaign=val2026&phase=calibration) | approve | window = min/max of the paper's Table 1; paper frames E6–E21 as one study (~0.1% duty cycle is irrelevant) |
| [STEREO-A/IMPACT 12 yr, 2020ApJ...889..143D](https://paper-data.helioanalytics.io/campaign/papers/7ac05972-0601-4273-abbf-1c5a18c133ee/claims/467f46c2-eec3-4295-a179-f007bbb0083c?campaign=val2026&phase=calibration) | approve | span asserted in text and title; suite-level IMPACT covers SEPT+HET |
| [MMS-3/FIELDS/ADP, 2020ApJ...891L..26H](https://paper-data.helioanalytics.io/campaign/papers/c3168f80-51b0-4553-a8e2-92bc21cb6c75/claims/5d3bd50c-a165-4c29-9210-a599fe35f881?campaign=val2026&phase=calibration) | **approve** (formation rule) | fleet-level analysis framing, no textual restriction — figures showing only MMS1/4 do not restrict |
| [SOHO/CDS, 2000BAAS...32..460M](https://paper-data.helioanalytics.io/campaign/papers/b3daa2ef-6fa8-40f8-b8bb-33aba0539577/claims/e7dd46d0-92c0-407d-87e6-f752d5e1eb8c?campaign=val2026&phase=calibration) | **reject → Cites others' work** | meeting abstract summarizing external analyses; no own operation |

## Ratification checklist (freeze meeting)

- ☐ The usage definition (one rule above)
- ☐ Window framing test, including event-set envelopes (E6–E21 accepted)
- ☐ Formation-fleet rule (MMS-3 → approve; Anthony re-votes Unsure → Correct)
- ☐ BAAS/CDS → reject, "Cites others' work" (both reviewers enter it)
- ☐ Reject categories (5 + Other) as shown in the review UI
- ☐ Amendments after this point are logged here with dates

Once all boxes are checked and both calibration re-verdicts are entered,
bulk review is open.

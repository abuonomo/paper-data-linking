# val2026 Review Rubric — v2.1

Rationale and campaign mechanics live in the paper repo's `VALIDATION_PROTOCOL.md`.
Amendments are logged in this file with dates.

---

## The one rule

> **Approve if — and only if — this paper performs its own analysis on a data
> product whose values come from this instrument, within this window — as
> supported by the paper, read with reasonable domain knowledge.**

- **Its own analysis** — the paper does a new operation: selects events,
  computes, fits, plots from values, trains or tests a model. Restating or
  reproducing someone else's work is not an operation.
- **A data product** — files, catalogs, indices, merged datasets: measurement
  at scale. Individual numbers quoted from other papers are testimony, not
  data.
- **Supported by the paper** — every field must be either stated in the text
  or made **effectively unique** by the text plus reliable domain knowledge
  (a paper using "magnetograms" at a wavelength and date only one instrument
  could supply → that instrument is correct). The line: **unique inference is
  fine; picking among multiple live candidates is guessing; and inference may
  never contradict the text** (grounding antenna V5 when the paper says V2 is
  wrong no matter how capable V5 is).

## How to decide, per claim

1. **Something factually wrong?** Wrong spacecraft, wrong instrument, or a
   time span the paper never asserts → **Incorrect, uncheck that box.**
   The unchecked box is the reason — no category needed.
2. **Everything correctly identified, but not real usage?** →
   **Incorrect, keep all boxes checked, pick a category:**
   - *Doesn't use this data:* Mention only · Cites others' work · Reproduced figure
   - *Analyzes no data at all:* Instrument/design paper · Theory only
   - *Other…* (a note is required)
3. **Real usage, faithful claim?** → **Correct.** One click.
4. **Can't tell from the paper?** → **Unsure.** It gets adjudicated later and
   is excluded from precision numbers.

Notes are optional except for *Other* — but every note feeds the usage-type
census, so write one on any borderline call.

## Hard patterns

### Catalogs and derived products

**A value taken from a catalog** (the LASCO CME catalog, a flare list, the
Richardson & Cane ICME list) **counts as usage.** A catalog is a data product
derived from the instrument; analyzing it is analyzing the instrument's data.
→ **Correct.**

**Merged datasets (OMNI and friends): usage flows through to the
contributors.** OMNI's values *are* the contributing instruments'
measurements, so analyzing OMNI is analyzing their data — a component claim
is **Correct** even when the paper never names the spacecraft. Two checks
still apply:

- **Derivation is parameter-level.** The component must supply the parameters
  actually analyzed: a paper using only the magnetic field (Bz) derives from
  the magnetometers — a claim on a *plasma* instrument for that paper is
  **Incorrect, uncheck Instrument.**
- **Contribution era matters for the window.** If you know the component only
  fed the composite for part of the claimed span (Wind contributes to the
  interplanetary-field composite from 1994, not 1963), judge the window
  accordingly — note it, and uncheck Time window for gross mismatches.

### Constellations and satellite series

**Formation-flying constellations (MMS; Cluster flying in formation).**
The members observe together, so when the paper frames its observations and
analysis at fleet level — with **no restricting sentence** — member claims are
**Correct**, even if figures show only some members. Figures never restrict;
only text does. If the paper *does* restrict ("we use only data from
spacecraft 1"), claims for the other members are **Incorrect, uncheck
Mission.**

**Interchangeable series (the GOES satellites).** A generic mention ("GOES
X-ray flux") supports only the **generic/group record** — approve that if
it's the claim. Claims naming specific satellite numbers the paper never
names are **Incorrect, uncheck Mission.** "It should have been GOES-15 that
year" is guessing among live candidates, not unique inference — several
satellites return data at any time, so a generic mention never determines a
specific bird.

### Instrument naming level

**Suite versus sub-instrument** (SECCHI vs EUVI, FIELDS vs its antennas):
approve whichever level the paper's text supports. A specific sibling the
paper never names — grounding antenna V5 when the paper says V2 — is
**Incorrect, uncheck Instrument.**

**GOES X-ray claims grounded to "SEM"** are **Correct**: the X-Ray Sensor
(XRS) is part of the Space Environment Monitor (SEM) package in our catalog.
(A known blind spot — don't reason from instrument physics here.)

### Document genre

**Genre never decides — operations do.** A review paper that performs its own
analysis on data products counts as usage; a review reprinting a figure does
not. An instrument paper is usually *Instrument/design paper* — but if it
analyzes commissioning or first-light observations, those claims are
**Correct**: real windows, real operations.

## Time windows: the framing rule

Judge a window by **how the paper itself talks about the span** — never by
how sparsely it was observed or how big the gaps are.

**Correct** when the span is one the paper asserts:

- a stated duration — "we study 2007 through 2018";
- a collectively framed set of events — "throughout encounters 6 to 21",
  "events up to the end of 2018". Sparse coverage inside the span is fine;
  add a note like *"window is an envelope of discrete events"*.

**Incorrect — uncheck Time window** when:

- the range belongs to a *different* dataset (SOHO/MDI stamped 1850–2005
  because the paper analyzed a sunspot series) — *over-extension*;
- the extractor invented the span by joining separately-described events
  (one event in 1996 plus one in 2016 becoming "1996–2016") —
  *granularity collapse*.

**Never wrong**: rounding at the paper's own precision ("January 2007"
becoming 2007-01-01), or technical quirks in how range endpoints are stored.

## Worked examples (calibration precedents)

1. **Parker Solar Probe SPAN-A**, Fargette et al. 2026 — **Correct.**
   The window is the first-to-last entry of the paper's own event table, and
   the paper frames encounters 6–21 as one statistical study. Sparse coverage
   inside the span is irrelevant.
   [open claim](https://paper-data.helioanalytics.io/campaign/papers/00607ada-7941-42d9-989e-1b3a5f95b363/claims/333c3609-75d6-4ba8-8d5e-cc6b47698434?campaign=val2026&phase=calibration)
2. **STEREO-A IMPACT**, Dresing et al. 2020 — **Correct.**
   Twelve-year span asserted in the text and the title; suite-level naming
   covers the two sub-instruments used (SEPT and HET).
   [open claim](https://paper-data.helioanalytics.io/campaign/papers/7ac05972-0601-4273-abbf-1c5a18c133ee/claims/467f46c2-eec3-4295-a179-f007bbb0083c?campaign=val2026&phase=calibration)
3. **MMS-3 axial double probe**, 2020 shock paper — **Correct** by the
   formation rule: fleet-level analysis framing, no restricting sentence —
   figures showing only MMS-1 and MMS-4 do not restrict.
   [open claim](https://paper-data.helioanalytics.io/campaign/papers/c3168f80-51b0-4553-a8e2-92bc21cb6c75/claims/5d3bd50c-a165-4c29-9210-a599fe35f881?campaign=val2026&phase=calibration)
4. **SOHO CDS**, 2000 meeting abstract — **Incorrect → Cites others' work.**
   The abstract summarizes analyses done elsewhere; the document performs no
   operation of its own.
   [open claim](https://paper-data.helioanalytics.io/campaign/papers/b3daa2ef-6fa8-40f8-b8bb-33aba0539577/claims/e7dd46d0-92c0-407d-87e6-f752d5e1eb8c?campaign=val2026&phase=calibration)

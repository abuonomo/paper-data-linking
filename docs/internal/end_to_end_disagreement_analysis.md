# End-to-End Disagreement Analysis: standard-gpt54-v2 vs bedrock-120b-high-v2

**Test set:** `test_set_helio_v2_2026_04_06` (200 papers)
**Date:** 2026-04-20

## Overview

| Metric | Value |
|---|---|
| Total papers | 200 |
| Perfect (Obs,Instr) agreement | 111 (55.5%) |
| Any disagreement | 89 (44.5%) |
| GPT total DatasetUsages | 805 |
| Bedrock total DatasetUsages | 815 |
| GPT InstrumentMentions (full) | 515 |
| GPT InstrumentMentions (instrument_no_time) | 28 |
| Bedrock InstrumentMentions (full) | 529 |
| Bedrock InstrumentMentions (instrument_no_time) | 80 |

## Disagreement Breakdown by Category

| Category | Count | Description |
|---|---|---|
| PARTIAL_OVERLAP | 65 | Both extract usages, share some, each has unique ones |
| GPT_EMPTY | 9 | GPT extracts 0, Bedrock extracts ≥1 |
| BED_MUCH_MORE | 7 | Bedrock extracts >2× what GPT does |
| BED_EMPTY | 4 | Bedrock extracts 0, GPT extracts ≥1 |
| GPT_MUCH_MORE | 4 | GPT extracts >2× what Bedrock does |

---

## Diagnosed Sources of Disagreement

### Source 1: Markdown Parser Time Range Bug

**Impact:** 55 Bedrock InstrumentMentions stuck at `instrument_no_time` → 0 DatasetUsages created
**Papers affected:** ~6 papers with ALL periods empty; contributes to 4 BED_EMPTY cases

**Root cause:** The deterministic markdown-to-JSON parser (`markdown_structure_parser.py`) expects time range values on the same line as the `- **Time Range**:` label:

```markdown
- **Time Range**: 2018-10-31 00:00:00 UTC – 2018-11-12 00:00:00 UTC   ← GPT format (works)
```

Bedrock puts the label on one line and the value on the next:

```markdown
- **Time Range**:                                                       ← Bedrock format (empty capture)
    *"Fig. 1...from October 31, 2018 00:00:00 to November 12..."*      ← value on next line (lost)
```

The regex `^-\s+\**Time Range\**:\s*(.*)` matches the label line and captures an empty string. The actual time info on the next line is either an italic quote or a Supporting Quote sub-bullet, which the parser assigns to `time_quotes` but never backfills into the empty `time_range` field.

**Evidence:**
- GPT: 0 papers with empty time_range across 1,017 periods
- Bedrock: 31 periods with empty time_range across 6 papers
- 55 of 80 Bedrock `instrument_no_time` mentions correspond to papers where ALL structured time_ranges are empty
- GPT has 0 such cases

**Proposed fix:** In `_build_period()`, if `time_range` is empty but `time_quotes` is non-empty, use the first time quote as the time_range value. Guaranteed regression-free (only fires when time_range is empty).

**Status:** Fixed. Two changes to `paper_analysis_output_parser.py`:
1. Added `_extract_italic_quote()` to capture `*"..."*` lines and backfill empty `time_range`
2. Added `_build_period()` fallback from `time_quotes` when `time_range` is empty

**Result:** Recovered 21 Bedrock DUs (8 for 2021A&A...650A..14L, 13 for 2013AIPC.1539..139B). 4 remaining empty periods are not real data collection periods (quality notes, cadence metadata) — not parser-fixable.

---

### Source 2: Instrument-Level Grounding Differences (PARTIAL_OVERLAP)

**Impact:** 75 papers with partial overlap (both configs extract, share some, each has unique ones)
**Sub-breakdown:** 36 same observatories / different instruments; 39 different observatories involved.
**Volume:** Bedrock finds more unique instruments in 37 papers, GPT in 29, equal in 9.

#### 2a: PSP Sub-Instrument Resolution (34 disagreements)

Parker Solar Probe dominates instrument-level disagreement. The models agree the paper uses PSP but disagree on which sub-component of the FIELDS or SWEAP suites to ground to:

- **GPT tends to find:** SPAN-A (4), FIELDS generic (4), SWEAP generic (3), LFR (2), HFR (2), TDS (2)
- **Bedrock tends to find:** FIELDS/MAG (4), SPC (2), SWEAP (2)

The PSP instrument hierarchy is unusually deep (FIELDS → RFS → LFR/HFR, FIELDS → MAG, FIELDS → TDS, etc.) and the catalog has entries at multiple levels. Models make different choices about which level to resolve to. Neither is clearly wrong — it depends on whether the paper describes specific sub-instrument data products or the overall suite.

#### 2b: Observatory-Level Differences (39 papers)

When configs disagree on which *observatory* was used:

**Observatories found only by Bedrock:** Wind (6), MMS-3 (4), MMS-4 (4), ACE (3), Helios 1 (2), STEREO-B (2), THEMIS-B (2), MMS-1 (2). Bedrock is more aggressive at expanding constellation families and finding additional missions in multi-instrument papers.

**Observatories found only by GPT:** GOES-10 (3), SOHO (3), Yohkoh (2), GOES-11 (2), SDO (2). GPT is better at resolving specific GOES satellite variants and finding solar instruments in multi-domain papers.

#### 2c: General Pattern

Not a systematic bug — this is genuine model variability at the instrument_selection and instrument_validation stages. Each model sometimes catches instruments the other misses, and vice versa. The partial overlap (shared instruments) is usually the core set; the disagreements are on secondary/peripheral instruments.

**Status:** Characterized, not actionable via single prompt/parser fix. This is the expected irreducible disagreement floor for end-to-end comparison. Precision validation (human review) would determine which model's unique finds are more often correct.

---

### Source 3: Cluster Constellation Variant Expansion

**Impact:** Contributes to BED_MUCH_MORE cases
**Nature:** Bedrock resolves "Cluster" to individual variants (Rumba, Salsa, Samba, Tango) × multiple instruments, while GPT either uses a single variant or produces zero.

**Example:** `2006ApJ...645..704K` — Bedrock extracts 10 usages across 4 Cluster variants × 3 instruments. GPT extracts 0.

**Status:** Partially addressed by the mission_validation family-variant prompt fix. May also involve the mission_identification stage (Cluster variants are deep in the 361-item list).

---

### Source 4: GPT Empty Extractions

**Impact:** 9 papers where GPT extracts 0 but Bedrock extracts ≥1
**Nature:** Diverse — includes papers about:
- OMNI data (composite datasets GPT refuses to ground)
- Review papers where Bedrock is more aggressive at extracting instrument usage
- Niche instruments (Hisaki/EXCEED) that GPT doesn't find

**Pattern:** GPT is more conservative — it returns UNKNOWN or produces no mentions for papers where the instrument usage is indirect or described through composite datasets. Bedrock is more aggressive.

**Status:** Not a bug — reflects different model temperaments. Neither is clearly wrong; GPT avoids false positives at the cost of false negatives, Bedrock does the opposite.

---

### Source 5: MMS Multi-Spacecraft Expansion

**Impact:** Contributes to BED_MUCH_MORE cases
**Nature:** Similar to Source 3 — when a paper mentions "MMS" generically, Bedrock expands to MMS-1/2/3/4 with individual instrument matches. GPT picks a single variant (usually MMS-2).

**Example:** `2024GeoRL..5108894C` — GPT extracts 7 usages (MMS-2 only), Bedrock extracts 15 (MMS-1/2/3/4 plus THEMIS-B and Wind).

**Status:** Related to mission_validation prompt and constellation-member handling.

---

## Not Yet Investigated

- **PARTIAL_OVERLAP instrument-level patterns**: 65 papers need systematic analysis. What fraction are "GPT finds instrument X, Bedrock finds instrument Y for the same paper" vs "both find the same instruments but ground to different catalog entries"?
- **Data system differences**: 7 papers where GPT uses only VSO but Bedrock uses both VSO+CDAWeb (or vice versa). Why does one model trigger grounding in a data system the other doesn't?
- **mission_only mention differences**: GPT has 50 mission_only mentions, Bedrock has 57. These are cases where a mission was identified but no specific instrument was matched. What drives the difference?

---

## Summary

| Source | Papers affected | DUs impacted | Fixable? |
|---|---|---|---|
| Markdown parser time range bug | ~6 directly, ~20 partially | ~55 missing Bedrock DUs | Yes (parser fix) |
| Instrument grounding variability | 65 | Distributed | No (model behavior) |
| Cluster/MMS variant expansion | ~5 | ~30 extra Bedrock DUs | Partially (prompt) |
| GPT conservatism on edge cases | 9 | ~20 missing GPT DUs | No (model behavior) |
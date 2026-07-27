# Test Set: `test_set_helio_v2_2026_04_06`

## Purpose

A 200-paper evaluation set for comparing LLM pipeline configurations on heliophysics papers. Designed to maximize the fraction of papers that yield DatasetUsage records, enabling meaningful comparison of grounding accuracy across models.

## Motivation

The previous test set (`test_set_helio_2026_03_13`) randomly sampled 200 papers from `helio_ml_high_conf` and only 47% yielded DatasetUsages. Post-hoc analysis revealed:

- 136 of 140 non-productive papers had **no mission tag** — they were theory, modeling, review, or tangentially-related papers that don't reference specific instrument data.
- Mission-tagged papers had 48–96% yield when processed, depending on the mission.

This test set addresses the low yield by stratifying the sample by mission tag and applying abstract-based filtering to the general helio portion.

## Sampling Method

### Source Pool

All papers tagged `helio_ml_high_conf` (20,962 total), excluding:
- Papers in any previous test set (6 prior test set tags)
- Papers already processed (having any PaperAnalysis record — 2,202 at time of creation)

Remaining base pool: 20,365 papers.

### Stratification

Papers were sampled from 7 strata, with deduplication between strata (papers selected in an earlier stratum are excluded from later ones):

| Stratum | Tag filter | Pool size | Sampled |
|---------|-----------|-----------|---------|
| SOHO | `soho` or `SOHO` in `helio_ml_high_conf` | 405 | 45 |
| Wind | `wind` or `Wind` in `helio_ml_high_conf` | 673 | 40 |
| IRIS | `IRIS` in `helio_ml_high_conf` | 421 | 35 |
| PSP_FIELDS | `PSP_FIELDS` (any tagged paper) | 185 | 25 |
| PSP_SWEAP | `PSP_SWEAP` (any tagged paper, deduplicated vs FIELDS) | 148 | 15 |
| ACE | `ACE` (any tagged paper) | 43 | 15 |
| General helio | `helio_ml_high_conf`, no mission tags, abstract-filtered | 7,166 | 25 |
| **Total** | | | **200** |

PSP_FIELDS, PSP_SWEAP, and ACE were drawn from the wider paper pool (not restricted to `helio_ml_high_conf`) because these tags have smaller pools.

### Abstract Keyword Filter (General Helio Stratum Only)

The 18,681 untagged `helio_ml_high_conf` papers were filtered using a three-part keyword heuristic on abstract text:

**Exclusion patterns** (disqualify the paper regardless of inclusion matches):
- Theory/modeling: "simulation", "numerical simulation", "MHD simulation", "we model", "theoretical model", "analytical model", "Monte Carlo", "Geant4"
- Reviews: "review of", "we review", "survey of", "are reviewed"
- ML methodology: "machine learning", "neural network", "deep learning", "classifier"
- Non-helio domains: "tropospheric", "continental", "oceanic", "monsoon"
- Lab/prototype: "prototype", "laboratory measurement", "test facility"

**Strong inclusion patterns** (any single match qualifies):
- Known instrument acronyms: EIT, LASCO, MDI, AIA, HMI, RHESSI, GOES, MMS, THEMIS, etc.
- Observatory/mission names: SDO, Hinode, STEREO, TRACE, Yohkoh, Solar Orbiter, etc.
- Data archive references: CDAWeb, OMNIWeb, VSO, SPDF, SDAC

**Medium inclusion patterns** (need 2+ matches to qualify):
- "data from", "observations from", "observed by", "measured by", "in situ"
- "spectrograph", "spectrometer", "coronagraph", "magnetometer", "imager"
- "level 1/2", "calibrated data", "dataset", "time series", "light curve"

**Logic:** `NOT excluded AND (any_strong OR medium_count >= 2)`

**Result:** 7,166 of 18,681 papers passed (38%), 25 sampled from those.

## Characteristics

### Year Distribution

| Decade | Papers |
|--------|--------|
| 1990s | 1 |
| 2000s | 47 |
| 2010s | 93 |
| 2020s | 65 |

### Top Journals

| Journal | Papers |
|---------|--------|
| A&A | 59 |
| ApJ | 49 |
| AnGeo | 21 |
| SoPh | 14 |
| SSRv | 6 |
| ApJS | 6 |
| GeoRL | 5 |

### Mission Tag Overlap

Some papers carry multiple mission tags (e.g., a paper studying both PSP FIELDS and SWEAP):

| Tag | Papers in set |
|-----|--------------|
| SOHO | 52 |
| Wind | 45 |
| IRIS | 35 |
| PSP_FIELDS | 39 |
| PSP_SWEAP | 33 |
| ACE | 17 |

### Data Availability

- All 200 papers have PDFs
- 0 have pre-extracted full text (will be extracted by the pipeline)

## Expected Yield

Based on historical yield rates for processed mission-tagged papers:

| Stratum | Expected yield | Expected productive papers |
|---------|---------------|--------------------------|
| SOHO (45) | ~87–96% | ~40 |
| Wind (40) | ~48–75% | ~24 |
| IRIS (35) | ~82% | ~29 |
| PSP_FIELDS (25) | ~86% | ~22 |
| PSP_SWEAP (15) | ~69% | ~10 |
| ACE (15) | ~62% | ~9 |
| General helio (25) | ~60% (estimated) | ~15 |
| **Total (200)** | | **~149 (75%)** |

## Reproducibility

- Script: `scripts/queries/create_helio_test_set_v2.py`
- Random seed: 42
- Created: 2026-04-06 on production
- Tag: `test_set_helio_v2_2026_04_06`

## Pipeline Configurations Under Test

The following configs were submitted as batch runs against this test set:

- `standard-gpt54`
- `bedrock-120b-high`
- `bedrock-nemotron-high`

All three configs include the new `mission_validation` pipeline stage (added 2026-04-03) which validates mission assignments before creating mission-only InstrumentMention stubs.

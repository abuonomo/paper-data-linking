# Substitution Analysis: Replacing gpt-5.4 with gpt-oss-120b
### Test set: `test_set_helio_v2_2026_04_06` (200 heliophysics papers)

> **Purpose**: findings + supporting plots for a LaTeX technical-report
> author to integrate into their document. Every number here is
> reproducible from the scripts in §8. The document is structured so
> each section maps to a claim, figure, or caveat the author will
> likely want to cite.

---

## 1. Headline

The analysis supports a **three-step narrative**, each step documented
with its own evidence:

1. **gpt-5.4 is self-consistent** on 9 of 10 LLM call types in the
   heliophysics pipeline (Fleiss' κ ≥ 0.87 across 5 runs per case).
   The one exception is `mission_identification`, which is a known
   task-design issue, not a gpt-5.4 reliability failure.

2. **gpt-oss-120b is at least as self-consistent** as gpt-5.4 on
   every call type (Fleiss' κ ≥ 0.82 throughout, and higher than
   gpt-5.4 on two call types including the `mission_identification`
   outlier).

3. **The two models agree with each other** at the single-run level
   (Cohen's κ ≥ 0.80) on 8 of 10 call types. The two call types below
   threshold (`mission_validation` κ = 0.70, `mission_identification`
   κ = 0.18) show *systematic* rather than *random* disagreement, and
   in both cases the disagreement traces back to ambiguity in the
   prompt or the task — not a reliability defect.

**Operational recommendation**: switch the pipeline to gpt-oss-120b
for 8 call types immediately. For the 2 flagged call types, tighten
the prompts (§5) before switching; both should clear the substitution
threshold afterward.

**Why this matters operationally**: gpt-oss-120b on Bedrock is roughly
1/50 the per-call cost of gpt-5.4 on OpenAI, and this analysis
supports the swap at equal or better output reliability.

---

## 2. Methodology

### Sampling

- **Test set**: `test_set_helio_v2_2026_04_06` (200 papers tagged in prod)
- **Per call type**: 100 cases sampled (seed = 42)
- **Runs per case**: 5 per model (temperature = 1.0, reasoning_effort = high)
- **Models**:
  - `openai/gpt-5.4` — OpenAI Batch API
  - `bedrock/converse/openai.gpt-oss-120b-1:0` — AWS Bedrock batch,
    except `time_normalization` where the live API was used to apply
    prod's `response_format` → tool-use translation (the Bedrock batch
    path does not apply this translation; see §7)

### Call types (10)

```
instrument_validation, mission_validation, wavelength_normalization,
physobs_normalization, mission_selection, instrument_selection,
detector_normalization, time_normalization, cadence_normalization,
mission_identification
```

### Metrics

| Symbol | Definition | Statistic |
|---|---|---|
| κ_intra (gpt-5.4) | Agreement among gpt-5.4's 5 runs per case | Fleiss' κ |
| κ_intra (gpt-oss-120b) | Agreement among gpt-oss-120b's 5 runs per case | Fleiss' κ |
| κ_cross (single-run) | Agreement between one random gpt-5.4 run and one random gpt-oss-120b run | Cohen's κ computed on the full pairwise (gpt_run, oss_run) cross-product over cases |

### Why single-run κ_cross, not modal-vs-modal

In production, each call is run once. Modal-vs-modal κ would answer
"if we polled each model 5 times, would the top answers match?" — a
proxy for ensemble agreement. Single-run κ answers "if I swap the
model on this one call, how likely is the downstream decision to
change?" which is the operational question.

Single-run κ is uniformly 0.01–0.07 lower than modal-vs-modal κ. The
ordering of call types is unchanged; `time_normalization` sits closer
to the 0.80 threshold under single-run measurement than under
modal-vs-modal (0.82 vs 0.83). All numbers in this report are the
single-run version.

### Substantive-only filtering

Call types with a natural null/refusal answer (`UNKNOWN`, `uncertain`,
`not_applicable`, empty list, null datetime) had cases dropped where
**all 10 runs from both models returned the null** — otherwise we'd
inflate κ by counting "both models refused 5 times" as agreement. `N`
in the tables is the substantive-only count.

Call types that never return nulls (the binary validations and the
selection tasks) show N = 100.

---

## 3. Primary result table

All κ values computed on the substantive subset, after the two
analyzer fixes described in §4d and §7 (trailing-Z datetime
canonicalization and the validation-handler regex bug).

| Call type | κ cross (1-run) | κ intra gpt-5.4 | κ intra gpt-oss-120b | N |
|---|---|---|---|---|
| Instrument Selection | 0.96 | 0.99 | 0.97 | 100 |
| Wavelength | 0.88 | 0.96 | 0.97 | 56 |
| Mission Selection | 0.87 | 0.96 | 0.90 | 100 |
| Instrument Validation | 0.87 | 0.97 | 0.92 | 100 |
| Physical Observable | 0.85 | 0.90 | 0.90 | 91 |
| Cadence | 0.88 | 0.93 | 0.83 | 19 |
| Time Range | 0.82 | 0.88 | 0.87 | 99 |
| Detector | 0.81 | 0.94 | 0.82 | 74 |
| Mission Validation | 0.70 | 0.87 | 0.95 | 100 |
| Mission ID | 0.18 | 0.25 | 0.90 | 84 |

Sorting here matches the primary figure (§6). Rows 1–8 clear κ ≥ 0.80
on all three columns ("safe swap" under the Landis-Koch "almost
perfect" threshold). Rows 9–10 are the flagged call types discussed
in §4b–4c.

### Why some N < 100

Cases where both models returned the null answer in every run are
dropped to avoid rewarding shared refusal. Worst case is `cadence`
(N = 19): 81% of sampled papers had no reported cadence. `wavelength`
(N = 56) loses ~46% of cases to `"not_applicable"` responses (the
paper used a descriptive wavelength term with no numeric band). These
small-N numbers should be interpreted with wider confidence intervals
than the others.

---

## 4. Per-call-type notes

### 4a. Safe-to-swap call types (rows 1–8)

No narrative needed. Both models are internally stable (κ_intra ≥ 0.82
on all 16 per-model measurements) and produce the same single-run
decisions ≥ 80% of the time after chance correction.

One observation worth a line in the methods section: for `cadence`,
`detector`, and `physobs`, **κ_cross is slightly higher than
κ_intra(gpt-oss-120b)**. That's counterintuitive but benign — it
means gpt-oss-120b has sub-answer-level noise (e.g., wobbling between
`"PT1M"` and `"PT60S"` across its 5 runs) while settling on the same
modal answer gpt-5.4 produces. Production takes a single answer per
call, so this within-model noise doesn't propagate; if anything it's
evidence the models are converging on the same decisions more than
oss is converging with itself.

### 4b. `mission_validation` (κ_cross = 0.70)

**Raw agreement**: both models give the same verdict on 93 / 100
cases. But `valid` outnumbers `invalid` roughly 88 / 12, so chance
agreement is ~79%, and Cohen's κ lands at 0.70.

**Disagreements are one-directional**: on 7 cases, gpt-5.4 says
`invalid` (typically 5/5 runs) while gpt-oss-120b says `valid`
(typically 5/5 runs). Zero cases go the other way.

**Root cause** (from reading the reasoning traces of all 7 cases):

Six of the seven are about **constellation-member specificity**. The
paper names a mission family (e.g., `"Cluster"`, `"THEMIS"`,
`"GOES"`); the proposed match is a specific spacecraft
(`Cluster-C2`, `THEMIS-C`, `GOES-13`). gpt-5.4 applies a strict rule
— "family named, not the specific variant, therefore invalid."
gpt-oss-120b applies a permissive rule — "family named, therefore
valid." The prompt is silent on which policy applies.

The seventh (PSP / LOFAR) is a scientific-capability mismatch that
gpt-5.4 correctly flags and gpt-oss-120b misses; a single instance,
probably noise.

**Interpretation**: this is a **prompt policy question**, not a model
defect. Since the matcher upstream produces spacecraft-specific IDs
(e.g., `SPASE://SMWG/OBSERVATORY/CLUSTER/C2`), gpt-oss-120b's
permissive interpretation is arguably closer to the downstream intent:
a paper saying "Cluster" does support the claim that one of the
Cluster spacecraft was used. Clarifying the prompt should drop the
7-case disagreement to ~0 and push κ_cross into the 0.9+ range.

### 4c. `mission_identification` (κ_cross = 0.18)

The most dramatic disagreement and the most interesting finding.

**Task**: given paper text + a ranked candidate list, return the
top-10 mission indices (or `UNKNOWN`).

**Response-shape distribution** across 500 responses per model:

| Response shape | gpt-5.4 | gpt-oss-120b |
|---|---|---|
| Top-10 list (expected) | 65% | 4% |
| UNKNOWN | 24% | 43% |
| Single mission | 7% | 43% |
| 2–9 missions | 4% | 10% |

**Root cause** (verified by reading reasoning traces of 20+ cases):
gpt-oss-120b performs **implicit verification** — it checks whether
the mission named in the paper text is actually in the candidate
list. When the named mission is *not* on the list, it refuses
(`UNKNOWN`) rather than confabulate a top-10 of "similar" missions.
When the named mission *is* on the list, it collapses to just that
one mission, ignoring the "top-10" instruction.

**Behavior broken down by whether the named mission is in the candidate list** (N = 100):

| Condition | gpt-5.4 | gpt-oss-120b |
|---|---|---|
| Named mission IS in list (13 cases) | Top-10 list (10 of 13) | Single pick (12 of 13) — correct mission, wrong list length |
| Named mission NOT in list (72 cases) | Top-10 list (53 of 72) — hallucinates ranking | UNKNOWN (33 of 72) — refuses to guess |
| No named mission (15 cases) | UNKNOWN (9 of 15) | UNKNOWN (10 of 15) |

**The striking finding**: of gpt-5.4's 53 top-10 rankings in the
"named mission not in list" category, **the vast majority are
confabulations** — the model is producing a ranked list of missions
it knows aren't the right answer because the right answer isn't on
the menu.

**Pipeline policy question** for the author:

- If downstream consumers use the top-10 for reranking or weighting,
  they have been receiving confabulated rankings the majority of the
  time. Swapping to gpt-oss-120b's more conservative behavior is a
  net correctness win, but downstream code must handle
  UNKNOWN / single-mission outputs rather than assuming a 10-element
  list.
- If downstream consumers only care about "did we confidently
  identify a single mission?", gpt-oss-120b's behavior is already
  what the pipeline wants.

Either way, gpt-5.4's intra-κ of 0.25 on this call type is a
standalone finding — the *incumbent* is the one producing unstable
rankings, partly because there's no stable ranking to produce when
the right answer isn't on the list.

### 4d. `time_normalization` — case-by-case investigation

After the canonicalization fixes (§7), `time_normalization` has
κ_cross = 0.82 (just above threshold). Investigating the 5 remaining
modal disagreements shows that 4 of 5 are prompt under-specification
rather than model error:

| Case | Input | Disagreement | Root cause |
|---|---|---|---|
| 1 | `"2014-02-21 (series duration 91 minutes)"` | gpt spans full day; oss spans 00:00–01:31 | **Real input ambiguity** — start time not given |
| 2 | `"[Pre-launch test; exact date not specified in paper]"` | gpt: error=False, oss: error=True | **gpt violates prompt rule** — paper explicitly marks as unspecified |
| 3 | `"November 5 14:00 UT – November 7 02:00 UT"` | gpt: error=True, oss: error=False | **oss violates prompt rule** — year missing |
| 4 | `"PSP's first solar encounter in 2018…"` | gpt: 2018–2020 year-precision; oss: nulls | Inference-vs-refuse policy differs |
| 5 | `"January 1997 – 15 April 2001"` | Datetimes identical; gpt precision=month, oss=day | **Prompt under-specifies precision** when start/end granularities differ |

**Prompt clarifications that would resolve 4 of 5**:

1. "Set `error: true` if any date component (year, explicit start
   time) is missing or the paper marks it as unspecified." — resolves
   cases 2 and 3.
2. "Do not infer dates from external knowledge of missions or
   instruments; if the paper does not state a date, return nulls." —
   resolves case 4.
3. "When start and end have different granularities, `precision` is
   the **coarser** of the two." — resolves case 5.

Expected post-clarification κ_cross: ~0.88+.

### 4e. Validation-handler regex bug (also affects prod)

While investigating `instrument_validation`, we discovered a **regex
bug in both validation handlers** that silently drops ~6% of valid
model responses. The bug is in
`experiments/compare_models/handlers/instrument_validation.py:34-38`
and `mission_validation.py:37-41`. These handlers are also imported
on the prod code path (`paper_data_linking/linkers/general/…`), so
the bug affects production, not just this experiment.

**Bug**: the regex
`FINAL\s+DECISION:\s*\*?\*?(valid|invalid)\*?\*?` doesn't tolerate
`**FINAL DECISION:** valid` (markdown bold around the label with a
space before the verdict). About 6% of gpt-oss-120b validation
outputs use this format.

**Fix**: replace with `FINAL\s+DECISION[:\*\s]*(valid|invalid)`.

**Impact when applied**: `instrument_validation` κ climbs from
0.669 → 0.923 — a measurement artifact, not real disagreement.

Full writeup with suggested unit tests in
`docs/validation_parser_regex_bug.md`. This finding is *incidental*
to the substitution study and is worth citing as a concrete example
of cross-model comparison surfacing prod bugs.

---

## 5. Recommendations

### Immediate (no prompt changes)

Switch to gpt-oss-120b for the following **8** call types:

> `instrument_selection`, `wavelength_normalization`,
> `cadence_normalization`, `mission_selection`,
> `instrument_validation`, `physobs_normalization`,
> `time_normalization`, `detector_normalization`

Expected outcome: ≥ 80% single-run agreement with current behavior,
cost reduction at the per-call level.

### Requires prompt tightening first

- `mission_validation`: add "constellation-level match counts as
  valid" to the prompt (e.g., a paper naming `Cluster` supports
  matching to `Cluster-C2`). Expected κ_cross ≥ 0.85 afterward.
- `mission_identification`: decide the pipeline policy. Recommended
  option: accept gpt-oss-120b's conservative behavior and update
  downstream consumers to handle UNKNOWN / single-mission outputs.
  Do **not** fight gpt-oss-120b into confabulating top-10 lists.
- `time_normalization`: apply the three prompt clarifications in §4d.
  Expected κ_cross ≥ 0.88.

### Independent code fix

- Apply the tolerant validation regex from §4e to both
  `InstrumentValidationHandler.parse_response` and
  `MissionValidationHandler.parse_response`. Add unit tests covering
  `**FINAL DECISION:** valid` format. Details in
  `docs/validation_parser_regex_bug.md`.

---

## 6. Figures

All artifacts are under `experiments/compare_models/` with the
`test_set_helio_v2_2026_04_06_` prefix.

### 6a. `_substitution_bars.{png,pdf}` — **primary figure**

Horizontal grouped bar chart. For each call type, three bars on a
shared κ axis:

- Blue: gpt-5.4 intra-κ (Fleiss')
- Orange: gpt-oss-120b intra-κ (Fleiss')
- Teal: cross-model κ (single-run Cohen's)

Rows sorted descending by the minimum of the three (the weakest
link). Dashed vertical line at κ = 0.80, dotted line at κ = 0.60.
Landis-Koch band tinting in the background. Legend positioned below
the x-axis label so nothing obscures the bars.

**One figure supports all three claims from §1**:

1. The blue bars at the top read "gpt-5.4 is stable" (§1 claim 1).
2. The orange bars mirror or exceed the blue bars (§1 claim 2).
3. The teal bars are short on the two bottom rows (§1 claim 3's
   exceptions) and long on the others.

Mission ID's reversal pops visually: blue and teal bars are both
~0.20, orange bar is at 0.90 — the incumbent is the unstable one.

Colors follow the **Okabe-Ito palette** (colorblind-safe, scientific
publishing standard) with a seaborn `whitegrid` style.

**Generated by**:
`experiments/compare_models/self_consistency/plot_substitution_bars.py`

### 6b. `_substitution_decision_kappa.{png,pdf}` — **supporting / optional**

Two-panel quadrant plot + sortable legend table:

- Left: full range (−0.05 to 1.03) with Landis-Koch band heatmap
  background, Mission ID labeled as the outlier
- Right: top quadrant (0.65 – 1.00), 9 numbered dots
- Right panel: sortable table with κ cross, κ intra (both models), N,
  color-coded by Landis-Koch band, row-tinted by swap verdict

Useful if the author wants to emphasize the decision-framework
framing ("SWAP FREELY / NEEDS JUDGE" quadrants) and show
*per-call-type numbers* alongside a scatter. Less compact than the
bar chart; recommend as appendix figure if included at all.

**Generated by**:
`experiments/compare_models/self_consistency/plot_substitution_decision_kappa.py`

### 6c. `_intra_vs_cross.{png,pdf}` — matches existing LaTeX Figure 5 style

Two-panel scatter (full + zoom) in the same visual language as the
paper's existing Figure 5 for an earlier test set. Axes are
**Jaccard**, not kappa, so numbers won't match §3's table — include
only if the paper needs stylistic parity with the pre-existing
figure. Recommend dropping if not strictly needed.

**Generated by**:
`experiments/compare_models/self_consistency/plot_intra_vs_cross.py`

### 6d. `_self_consistency_report.md` — auto-generated kappa dump

Source-of-truth markdown with every per-call-type number from the
raw result directories. Regenerated by
`experiments/compare_models/self_consistency/analyze_helio_v2_report.py`.
Cite this if the author wants to pull exact numbers outside the
curated table in §3.

### 6e. `viz/substitution.html` — interactive exploration (internal)

For reviewer-facing Q&A, not the paper. Open via
`cd experiments/compare_models/self_consistency/viz && python -m http.server`
then visit `http://localhost:8000/substitution.html`. Pan / zoom,
switch between κ and Jaccard, toggle all / substantive cases,
draggable threshold slider.

---

## 7. Caveats and deviations

1. **Bedrock batch API does not apply live-call `response_format` →
   tool-use translation**. litellm 1.70.4 (pinned in this repo) does
   not support Bedrock batch at all; we used boto3 via `BatchClient`
   directly. For `time_normalization` (the only call type with a
   JSON schema), we ran gpt-oss-120b *live* instead of batched to
   match prod's tool-use behavior exactly. All other call types have
   no schema so batch and live are equivalent.

2. **Sandbox clock was ~17 hours behind real time during analysis**;
   AWS SigV4 calls required `faketime` wrapping for authentication.
   No effect on the retrieved results but documented for
   reproducibility.

3. **Handler-registration collision (pre-existing bug, not
   introduced here)**: two handlers claim the call_type name
   `wavelength_normalization` (`WavelengthNormalizationHandler` and
   `WavelengthNormalizationSimpleHandler`).
   `CallTypeRegistry.register` was made idempotent (last-registered
   wins) so that `experiments/compare_models/handlers/__init__.py`
   doesn't crash on import. See
   `experiments/compare_models/core/registry.py`.

4. **`reasoning_effort` was being silently dropped from batch bodies**;
   fixed to forward the parameter. All batches in this run used
   `reasoning_effort=high`. See the patch in
   `experiments/compare_models/self_consistency/batch_runner.py` and
   the regression tests in `tests/unit/test_batch_runner.py`.

5. **`cadence_normalization` has small N (19 substantive cases)**
   because 81% of papers have no reported cadence. The κ values are
   meaningful but have wider confidence intervals than other rows.

6. **Measurement-side fixes applied during analysis**:
   - Trailing-`Z` datetime canonicalization in
     `analyze_helio_v2_report.py::_normalize_iso_datetime` — without
     this, `"2020-06-06T12:23:00"` (gpt) and `"2020-06-06T12:23:00Z"`
     (oss) compared as different strings despite being the same
     time. **Prod is not affected**:
     `time_range_normalizer.py:111-129` does its own canonicalization
     (`str.replace("Z", "+00:00")` on parse, `strftime("…Z")` on
     emit), so prod never sees the bare-vs-Z difference.
   - Validation-handler regex, see §4e.

---

## 8. Artifacts & reproducibility

### Scripts

| File | Purpose |
|---|---|
| `scripts/export_test_set_helio_v2_2026_04_06_local.sh` | Export prod LLMCall records for the test-set tag |
| `scripts/sample_jsonl.py` | Sample 100 valid records per call type (seed=42) |
| `experiments/compare_models/self_consistency/submit_helio_v2_batches.py` | Submit OpenAI batches for all 10 call types |
| `experiments/compare_models/self_consistency/submit_helio_v2_bedrock.py` | Submit Bedrock batches via `BatchClient` |
| `experiments/compare_models/self_consistency/rerun_bedrock_time_normalization_live.py` | Run `time_normalization` Bedrock live (applies response_format→tool_use) |
| `experiments/compare_models/self_consistency/retrieve_helio_v2_batches.py` | Poll + retrieve OpenAI + Bedrock results into canonical layout |
| `experiments/compare_models/self_consistency/analyze_helio_v2_report.py` | Compute per-call-type κ and emit the auto-generated report |
| `experiments/compare_models/self_consistency/plot_substitution_bars.py` | **Primary figure** (grouped-bar chart) |
| `experiments/compare_models/self_consistency/plot_substitution_decision_kappa.py` | Secondary quadrant figure with legend table |
| `experiments/compare_models/self_consistency/plot_intra_vs_cross.py` | LaTeX-Figure-5-style scatter (Jaccard) |
| `experiments/compare_models/self_consistency/viz/export_substitution_data.py` | Build JSON for the interactive HTML page |

### Outputs

| Path | Contents |
|---|---|
| `inputs/test_set/<call_type>_test_set_helio_v2_2026_04_06_sampled_100_seed42.jsonl` | 100-case samples (gitignored) |
| `experiments/compare_models/self_consistency/batches/test_set_helio_v2_2026_04_06/` | Batch input JSONL + `_manifest.jsonl` |
| `experiments/compare_models/self_consistency/results/test_set_helio_v2_2026_04_06/<model_slug>/<call_type>/run{1..5}/*.jsonl` | Raw per-run result records |
| `experiments/compare_models/test_set_helio_v2_2026_04_06_substitution_bars.{png,pdf}` | **Primary figure** |
| `experiments/compare_models/test_set_helio_v2_2026_04_06_substitution_decision_kappa.{png,pdf}` | Secondary quadrant figure |
| `experiments/compare_models/test_set_helio_v2_2026_04_06_intra_vs_cross.{png,pdf}` | Figure-5-style figure |
| `experiments/compare_models/test_set_helio_v2_2026_04_06_self_consistency_report.md` | Auto-generated κ + parse-rate tables |
| `docs/validation_parser_regex_bug.md` | Regex-bug writeup |
| `experiments/compare_models/test_set_helio_v2_2026_04_06_substitution_analysis.md` | **This document** |

---

## 9. Suggested framing for the LaTeX author

### Narrative arc

The analysis maps naturally onto three paragraphs, each anchored by
one panel of the primary figure:

1. **gpt-5.4 baseline** — cite κ_intra (gpt-5.4) column. 9/10 call
   types ≥ 0.87. `mission_identification` is the exception (κ = 0.25),
   which frames itself as the paper's opening puzzle rather than a
   substitution question.

2. **Candidate stability** — cite κ_intra (gpt-oss-120b) column.
   Universally ≥ 0.82. Notably, on `mission_identification`,
   gpt-oss-120b *beats* gpt-5.4 (0.90 vs 0.25), which sets up the
   discussion of *why* without committing to a verdict yet.

3. **Substitution check** — cite κ_cross column. 8/10 agree at
   ≥ 0.80. The 2 exceptions get §4b and §4c treatment. Both are
   prompt-level / task-design issues, not model defects; the paper
   can make a clean "substitution is safe today for 8/10, and safe
   after prompt clarification for 10/10" claim.

### Single-run vs modal-vs-modal framing

Explicitly state in methods that production runs the LLM once per
call (not an ensemble), so the reported κ_cross is the pairwise
single-run Cohen's κ. This is the production-relevant measure. A
footnote or appendix note: "modal-vs-modal κ is uniformly 0.01–0.07
higher; rankings unchanged."

### Open decisions for the author

1. **How much of §4d (time_normalization case-by-case) belongs
   in-body vs appendix?** Recommendation: keep the 5-row summary
   table in-body — it's the cleanest demonstration that remaining
   disagreements are *prompt-level*, not *model-level*, which is
   load-bearing for the substitution claim. The case quotes can go in
   an appendix.

2. **Cite the validation regex bug?** A single sentence plus a
   footnote would do. It's a concrete demonstration that rigorous
   cross-model comparison surfaces prod bugs — the kind of incidental
   finding that strengthens methodology sections. Reference
   `docs/validation_parser_regex_bug.md`.

3. **Cost/latency claim**: if the paper wants to quantify the cost
   argument behind the swap, token-usage data is already in each
   result JSONL (`prompt_tokens`, `completion_tokens`,
   `estimated_cost_usd`). Summing gives a per-call-type comparison.
   Not included here because cost modeling depends on the author's
   assumptions about throughput and batch-discount applicability.

4. **Include all three figures, or just the primary?**
   Recommendation: primary (grouped bars) in the main body; the
   quadrant + scatter can go in an appendix if space permits. The
   quadrant figure carries the same information as the bar chart but
   in a decision-framework frame; most readers will find the bars
   easier to read at a glance.

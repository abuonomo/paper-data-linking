# Paper-Data Linking: Validation & Model Evaluation Summary

## Executive Summary

This document summarizes two key evaluation efforts for the paper-data-linking pipeline:

1. **Human Validation Precision**: How accurate are the extracted dataset references?
2. **Model Self-Consistency**: How do different LLMs compare on extraction tasks?

---

## Part 1: Validation Precision Statistics

### Overall Precision

| Metric | Value | 95% CI |
|--------|-------|--------|
| **Precision** | 98.2% | [97.8%, 98.5%] |
| Total validated references | 5,578 | |
| Approved | 5,476 | |
| Rejected | 102 | |
| Fully validated papers | 723 | |
| Papers with any validation | 968 | |

*Precision = Approved / (Approved + Rejected). Excludes 2,636 pending and 295 needs_review.*

### Precision by Mission (Wilson Score 95% CI)

| Mission | Approved | Rejected | Precision | 95% CI |
|---------|----------|----------|-----------|--------|
| SOHO | 1,951 | 39 | 98.0% | [97.3%, 98.6%] |
| SDO | 625 | 18 | 97.2% | [95.6%, 98.2%] |
| STEREO-A | 460 | 4 | 99.1% | [97.8%, 99.7%] |
| STEREO-B | 415 | 6 | 98.6% | [96.9%, 99.3%] |
| Wind | 377 | 5 | 98.7% | [97.0%, 99.4%] |
| Hinode | 199 | 3 | 98.5% | [95.7%, 99.5%] |
| RHESSI | 180 | 10 | 94.7% | [90.6%, 97.1%] |
| ACE | 183 | 1 | 99.5% | [97.0%, 99.9%] |
| STEREO (generic) | 152 | 0 | 100% | [97.5%, 100%] |
| GOES | 132 | 7 | 95.0% | [90.0%, 97.5%] |
| GONG | 118 | 3 | 97.5% | [93.0%, 99.2%] |
| TRACE | 115 | 0 | 100% | [96.8%, 100%] |

### Precision by Instrument (Top 15 by volume)

| Instrument | Mission | Approved | Rejected | Precision | 95% CI |
|------------|---------|----------|----------|-----------|--------|
| LASCO | SOHO | 690 | 9 | 98.7% | [97.6%, 99.3%] |
| MDI | SOHO | 583 | 21 | 96.5% | [94.7%, 97.7%] |
| AIA | SDO | 396 | 10 | 97.5% | [95.5%, 98.7%] |
| SECCHI | STEREO | 373 | 6 | 98.4% | [96.6%, 99.3%] |
| EIT | SOHO | 256 | 4 | 98.5% | [96.1%, 99.4%] |
| HMI | SDO | 208 | 8 | 96.3% | [92.9%, 98.1%] |
| RHESSI | RHESSI | 180 | 10 | 94.7% | [90.6%, 97.1%] |
| UVCS | SOHO | 126 | 0 | 100% | [97.0%, 100%] |
| TRACE | TRACE | 115 | 0 | 100% | [96.8%, 100%] |
| Wind/MFI | Wind | 112 | 1 | 99.1% | [95.2%, 99.8%] |
| SUMER | SOHO | 100 | 1 | 99.0% | [94.6%, 99.8%] |
| Wind/SWE | Wind | 94 | 4 | 95.9% | [90.0%, 98.4%] |
| GONG | GONG | 95 | 3 | 96.9% | [91.4%, 99.0%] |
| EIS | Hinode | 78 | 2 | 97.5% | [91.3%, 99.3%] |
| GOES/SEM | GOES | 64 | 3 | 95.5% | [87.6%, 98.5%] |

### Statistically Significant Lower Performers

Instruments where the 95% CI lower bound falls below 95%:

| Instrument | Mission | n | Precision | 95% CI |
|------------|---------|---|-----------|--------|
| 512-ch magnetograph | Kitt Peak | 24 | 87.5% | [69.0%, 95.7%] |
| SEM | GOES-10 | 41 | 92.7% | [80.6%, 97.5%] |
| spectromagnetograph | Kitt Peak | 32 | 93.8% | [79.9%, 98.3%] |
| RHESSI | RHESSI | 190 | 94.7% | [90.6%, 97.1%] |
| GOES/SEM | GOES | 67 | 95.5% | [87.6%, 98.5%] |

### Coverage Statistics

| Metric | Count |
|--------|-------|
| Missions with n ≥ 50 validations | 16 |
| Missions with n ≥ 100 validations | 12 |
| Instruments with n ≥ 50 validations | 25 |
| Instruments with n ≥ 100 validations | 11 |
| Total missions in database | 57 |
| Total instruments in database | 144 |

---

## Part 2: Model Self-Consistency Comparison

We conducted a systematic comparison of OpenAI GPT-5 and Bedrock GPT-OSS-120B across 9 structured extraction call types used in the paper-data-linking pipeline. Our evaluation combined three complementary methods:

1. **Self-consistency**: How often does each model agree with itself across 5 repeated runs?
2. **Cross-model agreement**: How often do the two models agree with each other?
3. **LLM-as-judge**: For disagreements, which model's answer is better?

**Key finding**: Initial metrics suggested Bedrock was comparable or superior to GPT-5 at lower cost. However, deeper analysis revealed that Bedrock frequently fails to follow output format instructions, producing confident-looking but non-compliant responses. When instruction-following is properly weighted, GPT-5 significantly outperforms Bedrock on complex tasks.

---

## Methodology

### Test Set
- **Tag**: `test_set_2025_11_26`
- **Papers**: 100 heliophysics research papers
- **Runs**: 5 independent runs per model per call type

### Metrics
- **Jaccard similarity**: Used for both self-consistency and cross-model agreement
  - For single-value tasks: 1.0 if match, 0.0 if different
  - For set-valued tasks: |A ∩ B| / |A ∪ B|
- **95% confidence intervals**: Computed via bootstrap resampling

### Call Types Evaluated

| Call Type | Task Type | Description |
|-----------|-----------|-------------|
| instrument_validation | binary | Is this a valid instrument? |
| mission_identification | single | Which mission hosts this instrument? |
| mission_selection | set | Select matching missions from candidates |
| instrument_selection | set | Select matching instruments from candidates |
| physobs_normalization | single | Normalize physical observable |
| time_normalization | single | Normalize time range to ISO 8601 |
| wavelength_normalization | single | Normalize wavelength specification |
| cadence_normalization | single | Normalize cadence specification |
| detector_normalization | single | Normalize detector specification |

---

## Results

### 1. Self-Consistency by Model

| Call Type | GPT-5 SC | Bedrock SC | Delta | More Consistent |
|-----------|----------|------------|-------|-----------------|
| mission_identification | 36.2% | 84.1% | -47.9% | Bedrock |
| physobs_normalization | 88.7% | 83.0% | +5.7% | GPT-5 |
| time_normalization | 88.0% | 92.6% | -4.6% | Bedrock |
| detector_normalization | 95.8% | 98.8% | -3.0% | Bedrock |
| instrument_selection | 97.9% | 95.7% | +2.2% | GPT-5 |
| mission_selection | 95.7% | 91.6% | +4.2% | GPT-5 |
| cadence_normalization | 97.5% | 97.5% | 0.0% | Tie |
| wavelength_normalization | 97.4% | 98.3% | -0.9% | ~Same |
| instrument_validation | 100.0% | 100.0% | 0.0% | Tie |

**Notable**: The massive gap on `mission_identification` (36% vs 84%) is explained by instruction-following behavior, not randomness (see Section 4).

### 2. Cross-Model Agreement vs Self-Consistency

![Scatter plot interpretation]

Most call types cluster near the y=x diagonal, indicating cross-model agreement ≈ self-consistency. Points below the diagonal indicate systematic model differences.

| Call Type | Avg Self-Consistency | Cross-Model | Gap |
|-----------|---------------------|-------------|-----|
| wavelength_normalization | 97.9% | 99.8% | -1.9% |
| cadence_normalization | 97.5% | 99.1% | -1.6% |
| instrument_validation | 100.0% | 97.4% | +2.6% |
| detector_normalization | 97.3% | 95.6% | +1.7% |
| instrument_selection | 96.8% | 92.1% | +4.6% |
| mission_selection | 93.6% | 89.1% | +4.5% |
| time_normalization | 90.3% | 86.7% | +3.6% |
| physobs_normalization | 85.9% | 79.5% | +6.4% |
| mission_identification | 60.2% | 50.2% | +9.9% |

**Interpretation**:
- **Negative gap** (wavelength, cadence): Models agree with each other MORE than with themselves - both have variance but converge to similar answers
- **Positive gap** (most tasks): Models have systematic biases that cause disagreement

### 3. LLM-as-Judge Results

We used GPT-5.2 as an independent judge to evaluate disagreement cases. Results shown after adding instruction-following guidance:

| Call Type | GPT-5 Wins | Bedrock Wins | Ties | Cases |
|-----------|------------|--------------|------|-------|
| mission_identification | **90%** | 10% | 0% | 20 |
| physobs_normalization | **67%** | 17% | 17% | 18 |
| mission_selection | **60%** | 20% | 20% | 10 |
| instrument_selection | 43% | **57%** | 0% | 7 |
| time_normalization | 7% | **57%** | 29% | 14 |

---

## Key Findings

### 4. Critical Discovery: Instruction-Following Failure

The most significant finding involves `mission_identification`. The prompt explicitly instructs:

> "Return the numbers (1-N) of the **top 10 most likely missions**, comma-separated."

**Actual model behavior:**

| Model | Returns 10 items | Returns 1 item | Avg items |
|-------|------------------|----------------|-----------|
| GPT-5 | 56.2% | 40.2% | 6.16 |
| Bedrock | 6.2% | 84.2% | 1.78 |

**Bedrock returns single items 84% of the time despite instructions requesting 10.**

This explains:
1. Why Bedrock has higher self-consistency (matching 1 item is easier than matching 10)
2. Why cross-model agreement is low (comparing 10 items vs 1 item)
3. Why initial LLM-as-judge favored Bedrock (single confident answers "look better")

**Before/after adding instruction-following to judge prompt:**

| Metric | Before | After |
|--------|--------|-------|
| GPT-5 wins | 5% | **90%** |
| Bedrock wins | 95% | **10%** |

### 5. Model Behavioral Patterns

**GPT-5 characteristics:**
- Better instruction-following (returns requested number of items)
- More exploratory (returns multiple options when uncertain)
- Better at multi-instance selections (Cluster 1-4, etc.)
- Higher variance on complex tasks

**Bedrock characteristics:**
- More "conservative" (returns single items, UNKNOWN, or "0")
- Better at ISO 8601 formatting (Z suffix for UTC)
- More consistent formatting but less complete
- Fails to follow output format instructions

### 6. Task-Specific Insights

**High agreement tasks** (>95% cross-model):
- `wavelength_normalization`, `cadence_normalization`, `instrument_validation`, `detector_normalization`
- Models behave equivalently; either choice is fine

**Moderate agreement tasks** (85-95% cross-model):
- `instrument_selection`, `mission_selection`, `time_normalization`
- Some systematic differences but generally similar

**Low agreement tasks** (<85% cross-model):
- `physobs_normalization` (79.5%): GPT-5 better at direct observables, Bedrock better at recognizing derived quantities
- `mission_identification` (50.2%): Dominated by instruction-following difference

---

## Evaluation Method Recommendations

### When to use each evaluation approach:

| Method | Best For | Limitations |
|--------|----------|-------------|
| Self-consistency | Measuring model stability, no labels needed | Doesn't measure correctness |
| Cross-model agreement | Detecting systematic differences | Assumes neither model is clearly better |
| LLM-as-judge | Subjective/open-ended outputs, no ground truth | Sensitive to prompt framing, potential bias |
| Precision vs labels | Tasks with validated ground truth | Only measures precision, not recall |

### For this pipeline specifically:

| Call Type | Recommended Evaluation |
|-----------|----------------------|
| instrument_details | LLM-as-judge (no ground truth) |
| structuring | LLM-as-judge (no ground truth) |
| mission_selection | **Precision vs validated labels** |
| instrument_selection | **Precision vs validated labels** |
| time_normalization | **Precision vs validated labels** |
| Others | LLM-as-judge or self-consistency |

---

## Conclusions

### Validation Precision

1. **High overall precision**: 98.2% of validated dataset references are correct, with tight confidence intervals [97.8%, 98.5%].

2. **Consistent across major missions**: SOHO, SDO, STEREO, Wind, ACE all exceed 97% precision with statistically robust sample sizes.

3. **Known problem areas**: Kitt Peak instruments and RHESSI show lower precision (87-95%), warranting investigation into extraction challenges for these data sources.

4. **Good coverage**: Statistically meaningful precision estimates (n ≥ 50) for 16 missions and 25 instruments.

### Model Self-Consistency

5. **Surface metrics are misleading**: Bedrock appeared comparable based on self-consistency and initial judge results, but this masked a fundamental instruction-following failure.

6. **Instruction-following matters**: For structured extraction tasks, a model that ignores output format requirements produces unreliable results regardless of how "confident" individual answers appear.

7. **GPT-5 is the better choice** for this pipeline when instruction-following is properly weighted, despite higher cost.

8. **Bedrock may be acceptable** for simpler normalization tasks (wavelength, cadence, detector) where models behave equivalently.

9. **Evaluation method matters**: LLM-as-judge is sensitive to what you tell the judge to prioritize. Always include instruction-following as a criterion for structured tasks.

---

## Appendix A: Files and Reproducibility

### Self-consistency experiment files:
- `model_comparison_analysis.ipynb`: Main analysis notebook
- `llm_judge.py`: LLM-as-judge evaluation script
- `viz/data/summary.json`: Aggregated statistics
- `judge_results/*.json`: Detailed judgment results
- `results/test_set_2025_11_26/`: Raw model outputs

### Commands to reproduce:
```bash
# Run LLM-as-judge for a call type
python llm_judge.py --call-type mission_identification --max-cases 20 --judge openai/gpt-5.2

# Generate visualization data
# (run cells in model_comparison_analysis.ipynb)
```

## Appendix B: Validation Statistics Methodology

### Data source
- Production database (`DatasetUsage` model)
- Query date: January 28, 2026

### Precision calculation
```
Precision = Approved / (Approved + Rejected)
```

Excludes `pending` and `needs_review` statuses (no ground truth determination made).

### Confidence intervals
Wilson score intervals for binomial proportions (95% CI):
```
CI = (p̂ + z²/2n ± z√(p̂(1-p̂)/n + z²/4n²)) / (1 + z²/n)
```
where z = 1.96 for 95% confidence.

Wilson intervals are preferred over naive intervals because they:
- Work correctly at extreme proportions (e.g., 98%)
- Never produce impossible values (>100% or <0%)
- Have better coverage properties for small samples

---

*Validation statistics: January 28, 2026*
*Self-consistency analysis: January 2026*
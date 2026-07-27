# Self-Consistency Experiments: test_set_2025_11_26

This directory contains experiment configurations for running self-consistency analysis on the validated test set `test_set_2025_11_26`.

## Overview

**Self-consistency** measures how reliably an LLM produces the same answer when given identical inputs at `temperature=1.0`. This reveals:
- Which tasks are **easy** (high agreement across runs)
- Which tasks are **ambiguous** (low agreement - the LLM is "uncertain")
- Cost-performance characteristics of the model

## Model Configuration

- **Model**: `bedrock/openai.gpt-oss-120b-1:0`
- **Temperature**: 1.0 (enables randomness for self-consistency testing)
- **Runs per experiment**: 5
- **Test set**: `test_set_2025_11_26` (100 papers from validated production data)

## Experiment Configs

Each YAML file configures one call type:

| Config File | Call Type | Description |
|-------------|-----------|-------------|
| [instrument_validation.yaml](instrument_validation.yaml) | `instrument_validation` | Validates if matched instrument aligns with paper description |
| [wavelength_normalization.yaml](wavelength_normalization.yaml) | `wavelength_normalization` | Parses raw wavelength strings into structured format |
| [physobs_normalization.yaml](physobs_normalization.yaml) | `physobs_normalization` | Maps raw observable text to VSO-approved physical observables |
| [mission_selection.yaml](mission_selection.yaml) | `mission_selection` | Selects final mission(s) from filtered candidates |
| [instrument_selection.yaml](instrument_selection.yaml) | `instrument_selection` | Selects final instrument(s) from filtered candidates |
| [detector_normalization.yaml](detector_normalization.yaml) | `detector_normalization` | Selects detector from VSO-approved list |
| [time_normalization.yaml](time_normalization.yaml) | `time_normalization` | Parses time ranges into ISO format |
| [cadence_normalization.yaml](cadence_normalization.yaml) | `cadence_normalization` | Normalizes observation cadence to ISO 8601 duration |
| [mission_identification.yaml](mission_identification.yaml) | `mission_identification` | Identifies top candidate missions from large list |

**Note**: `structure_analysis` and `paper_analysis` are excluded because they're challenging to evaluate for equality.

## Workflow

### 1. Export Test Set Data from Production

Download LLM call data from production for the test set:

```bash
./scripts/export_test_set_for_self_consistency.sh
```

This creates JSONL files in `inputs/test_set/` with render context for each call type.

### 2. Run Self-Consistency Experiments

Run all experiments (5 runs each):

```bash
./scripts/run_test_set_self_consistency.sh 5
```

Or run a single experiment:

```bash
./experiments/compare_models/run_self_consistency.sh \
  experiments/compare_models/experiment_configs/test_set_2025_11_26/instrument_validation.yaml \
  5
```

Results are saved in: `experiments/compare_models/prompt_experiments/`

### 3. Analyze Results

Analyze a specific call type:

```bash
python experiments/compare_models/analyze_self_consistency.py \
  instrument_validation_test_set_2025_11_26
```

Generate comprehensive report for all call types:

```bash
python scripts/generate_self_consistency_report.py
```

Report saved to: `experiments/compare_models/test_set_2025_11_26_self_consistency_report.md`

## Metrics

### Fleiss' Kappa (κ)

Measures inter-rater agreement across multiple runs:
- **κ > 0.80**: Excellent agreement
- **κ = 0.60-0.80**: Substantial agreement
- **κ = 0.40-0.60**: Moderate agreement
- **κ < 0.40**: Poor agreement

### Consistency Levels

- **Perfect (5/5)**: All 5 runs produced identical output
- **High (4/5)**: 4 out of 5 runs produced identical output
- **Moderate (3/5)**: 3 out of 5 runs produced identical output
- **Low (2/5)**: Only 2 runs agreed
- **No consistency**: All runs produced different outputs

## Example Output

From previous wavelength normalization experiment:

```
SELF-CONSISTENCY ANALYSIS
================================================================================
Number of runs: 5
Total cases: 100
Valid cases: 100

CONSISTENCY BREAKDOWN:
  Perfect consistency (5/5 identical):  89 (89.0%)
  High consistency (4/5 identical):      5 (5.0%)
  Moderate consistency (3/5 identical):  6 (6.0%)

Fleiss' kappa: 0.929 (excellent agreement)
```

## Cost Analysis

Self-consistency experiments provide cost data for:
1. **Per-run costs**: Total cost to run one complete experiment
2. **Per-case costs**: Average cost per test case
3. **Token usage**: Input/output tokens per run

This enables cost-performance tradeoff analysis for the technical report.

## Use in Technical Report

Self-consistency results demonstrate:

1. **Model Reliability**: High kappa scores show the model is stable and deterministic for well-defined tasks
2. **Ambiguity Detection**: Low agreement cases reveal genuinely ambiguous inputs
3. **Cost-Performance**: Quantify the relationship between model capability and operational costs
4. **Edge Case Discovery**: Identify which types of papers/extractions cause disagreement

## Troubleshooting

**No input files found**:
```bash
# Run export script first
./scripts/export_test_set_for_self_consistency.sh
```

**Missing dependencies**:
```bash
# Install experiment dependencies
pip install -e .[experiments]
```

**Export returns 0 cases**:
- Check that test set papers have been processed with the current LLM pipeline
- Verify `render_context` is populated (migration 0059+)
- Check paper tags: `Paper.objects.filter(tags__contains=['test_set_2025_11_26']).count()`
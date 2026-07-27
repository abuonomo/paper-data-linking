# Prompt Experimentation Framework

This framework allows you to test different system prompt variations across multiple models to find optimal prompt design for model alignment.

## Overview

The disagreement analysis revealed that models interpret validation criteria differently, particularly the "scientific capability match" criterion. This framework lets you experiment with different prompt formulations to improve alignment.

## Files

- **`run_prompt_experiment.py`**: Run experiments with custom system prompts
- **`compare_prompt_experiments.py`**: Compare results across multiple experiments
- **`inputs/instrument_validation_disagreements_9.jsonl`**: The 9 cases where models disagree

## System Prompt Variants

Located in `paper_data_linking/linkers/general/prompts/validation/`:

### `system.xml` (Current/Baseline)
The current prompt with updated criteria clarifications from earlier analysis.

### `system_strict.xml` (Strict Interpretation)
**Key change:** Requires matched instrument to perform ALL described observations alone.

**Modified criterion:**
> Can the matched instrument ALONE perform ALL of the described observations? The matched instrument must be capable of providing ALL the measurements and data products explicitly described, without relying on other instruments in the mission suite.

**Use case:** If you want stricter validation that rejects partial instrument matches.

### `system_lenient.xml` (Lenient Interpretation)
**Key change:** Allows partial matches when other mission instruments provide complementary data.

**Modified criterion:**
> Can the matched instrument contribute meaningfully to the described observations? The matched instrument should provide at least one key measurement or data product described. If other instruments in the same mission suite can provide complementary measurements mentioned in the description, this is acceptable.

**Use case:** If you want to accept matches where the instrument provides some (but not all) of the described data.

## Usage

### 1. Run an Experiment

Test a system prompt across multiple models:

```bash
python experiments/compare_models/run_prompt_experiment.py \
  --input inputs/instrument_validation_disagreements_9.jsonl \
  --system-prompt paper_data_linking/linkers/general/prompts/validation/system.xml \
  --models openai/gpt-5-nano openai/gpt-5-mini openai/gpt-5 \
  --experiment-name baseline
```

**Parameters:**
- `--input`: Path to input cases (use disagreement file to focus on problem cases)
- `--system-prompt`: Path to system prompt XML file
- `--models`: Space-separated list of models to test
- `--experiment-name`: Name for this experiment (creates subdirectory)
- `--output-dir`: Base directory for results (default: `experiments/compare_models/prompt_experiments`)

**Output:**
- Creates directory: `experiments/compare_models/prompt_experiments/{experiment_name}/`
- Saves system prompt used: `system_prompt.xml`
- Saves results per model: `{model}_{timestamp}.jsonl`

### 2. Run Multiple Experiments

Test different prompts:

```bash
# Baseline (current prompt)
python experiments/compare_models/run_prompt_experiment.py \
  --input inputs/instrument_validation_disagreements_9.jsonl \
  --system-prompt paper_data_linking/linkers/general/prompts/validation/system.xml \
  --models openai/gpt-5-nano openai/gpt-5-mini openai/gpt-5 \
  --experiment-name baseline

# Strict interpretation
python experiments/compare_models/run_prompt_experiment.py \
  --input inputs/instrument_validation_disagreements_9.jsonl \
  --system-prompt paper_data_linking/linkers/general/prompts/validation/system_strict.xml \
  --models openai/gpt-5-nano openai/gpt-5-mini openai/gpt-5 \
  --experiment-name strict

# Lenient interpretation
python experiments/compare_models/run_prompt_experiment.py \
  --input inputs/instrument_validation_disagreements_9.jsonl \
  --system-prompt paper_data_linking/linkers/general/prompts/validation/system_lenient.xml \
  --models openai/gpt-5-nano openai/gpt-5-mini openai/gpt-5 \
  --experiment-name lenient
```

### 3. Compare Results

Generate a comparison report:

```bash
python experiments/compare_models/compare_prompt_experiments.py \
  --experiments \
    baseline=experiments/compare_models/prompt_experiments/baseline \
    strict=experiments/compare_models/prompt_experiments/strict \
    lenient=experiments/compare_models/prompt_experiments/lenient \
  --output experiments/compare_models/results/prompt_comparison.html
```

**Output:**
- HTML report showing side-by-side comparison
- Alignment metrics for each experiment
- Case-by-case decision changes

## Creating Custom Prompts

To create your own prompt variant:

1. Copy an existing prompt (e.g., `system.xml`)
2. Modify the criteria, rules, or examples
3. Save with a descriptive name (e.g., `system_custom.xml`)
4. Run experiment with `--system-prompt` pointing to your file

**Key areas to modify:**

- **Validation criteria** (lines 6-12): The five criteria models must check
- **Critical rules** (lines 14-19): Explicit rules that override ambiguity
- **Examples** (lines 21-32): Concrete valid/invalid cases
- **Response format** (lines 34-47): Output structure (usually keep as-is)

## Example Workflow

```bash
# 1. Run baseline to see current behavior
python experiments/compare_models/run_prompt_experiment.py \
  --input inputs/instrument_validation_disagreements_9.jsonl \
  --system-prompt paper_data_linking/linkers/general/prompts/validation/system.xml \
  --models openai/gpt-5-nano openai/gpt-5-mini \
  --experiment-name baseline

# 2. Run strict variant
python experiments/compare_models/run_prompt_experiment.py \
  --input inputs/instrument_validation_disagreements_9.jsonl \
  --system-prompt paper_data_linking/linkers/general/prompts/validation/system_strict.xml \
  --models openai/gpt-5-nano openai/gpt-5-mini \
  --experiment-name strict

# 3. Compare to see which achieves better alignment
python experiments/compare_models/compare_prompt_experiments.py \
  --experiments \
    baseline=experiments/compare_models/prompt_experiments/baseline \
    strict=experiments/compare_models/prompt_experiments/strict \
  --output experiments/compare_models/results/baseline_vs_strict.html

# 4. Open report in browser
open experiments/compare_models/results/baseline_vs_strict.html
```

## Key Disagreement Patterns

Based on analysis, these are the main disagreement cases:

1. **Multiple instruments mentioned, only one matched**
   - Example: "Helios 1 & 2" → Helios 2 only
   - Example: "FIELDS and FPI" → FPI only

2. **Instrument + measurements, only instrument matched**
   - Example: "Magnetometer and plasma" → Magnetometer only

3. **Generic reference → specific sub-component**
   - Example: "MMS FPI" → "MMS 1 FPI DIS"

Use the prompt variants to control how strictly these cases are validated.

## Cost Estimation

Running on 9 cases with 3 models:
- **gpt-5-nano**: ~$0.001 per experiment
- **gpt-5-mini**: ~$0.01 per experiment
- **gpt-5**: ~$0.05 per experiment

Total for one full experiment (all 3 models): ~$0.06

## Tips

1. **Start with 2 models** (e.g., nano + mini) to iterate faster
2. **Use disagreement cases** (9 cases) to focus on problem areas
3. **Test one change at a time** to understand impact
4. **Check alignment metrics** in comparison report
5. **Review specific case changes** to understand why alignment improved/worsened

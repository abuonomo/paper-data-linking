# Comprehensive Model Comparison Experiment

## Overview

This experiment compares 4 different LLM models across 10 different call types to evaluate quality, cost, and performance trade-offs.

## Models Tested

1. **openai/gpt-5** - Flagship model, highest quality
   - Input: $1.250 / 1M tokens
   - Output: $10.000 / 1M tokens

2. **openai/gpt-5-mini** - Balanced performance/cost
   - Input: $0.250 / 1M tokens
   - Output: $2.000 / 1M tokens

3. **openai/gpt-5-nano** - Fast and cheap
   - Input: $0.050 / 1M tokens
   - Output: $0.400 / 1M tokens

4. **bedrock/openai.gpt-oss-120b-1:0** - AWS Bedrock hosted
   - Input: $0.150 / 1M tokens
   - Output: $0.600 / 1M tokens

## Call Types Tested

All call types have handlers implemented in `experiments/compare_models/handlers/`:

1. **mission_identification** (682 cases) - Tier 2 complex
2. **time_normalization** (428 cases) - Tier 3 complex
3. **mission_selection** (379 cases) - Tier 1 simple
4. **instrument_selection** (290 cases) - Tier 1 simple
5. **instrument_validation** (273 cases) - Tier 1 simple
6. **wavelength_normalization** (219 cases) - Tier 3 complex
7. **physobs_normalization** (124 cases) - Tier 3 complex
8. **cadence_normalization** (118 cases) - Tier 3 complex
9. **detector_normalization** (104 cases) - Tier 3 complex
10. **structure_analysis** (98 cases) - Tier 4 complex nested JSON

**Total**: 2,715 test cases per model = 10,860 total API calls

**Excluded**: paper_analysis (no handler implemented)

## Cost & Time Estimates

### Per-Model Costs:
- gpt-5: ~$58.50
- gpt-5-mini: ~$11.70
- gpt-5-nano: ~$2.35
- bedrock gpt-oss-120b: ~$3.50

**Total Cost**: ~$76

### Time Estimate:
- Sequential execution: ~6 hours
- Average: ~2 seconds per API call

## Running the Experiment

### Full Experiment

Run all call types with all models:

```bash
cd /Users/abuonomo/code/nasa/paper-data-linking
./experiments/compare_models/run_full_experiment.sh
```

### Single Call Type

Test a specific call type:

```bash
python experiments/compare_models/run_prompt_experiment.py \
    --call-type detector_normalization \
    --input inputs/test_set/detector_normalization.jsonl \
    --system-prompt paper_data_linking/linkers/general/prompts/detector_normalization/system.xml \
    --models openai/gpt-5-nano openai/gpt-5-mini \
    --experiment-name test_run
```

### Validation Run (Recommended First)

Test with smaller call types first:

```bash
# Run cheapest call types first to validate pipeline
python experiments/compare_models/run_prompt_experiment.py \
    --call-type physobs_normalization \
    --input inputs/test_set/physobs_normalization.jsonl \
    --system-prompt paper_data_linking/linkers/general/prompts/physobs_normalization/system.xml \
    --models openai/gpt-5-nano openai/gpt-5-mini \
    --experiment-name validation_run
```

## Output Structure

Results are saved to:
```
experiments/compare_models/prompt_experiments/<experiment_name>/
├── system_prompt.xml                                  # System prompt used
├── openai_gpt-5_<timestamp>.jsonl                    # Results for gpt-5
├── openai_gpt-5-mini_<timestamp>.jsonl               # Results for gpt-5-mini
├── openai_gpt-5-nano_<timestamp>.jsonl               # Results for gpt-5-nano
└── bedrock_openai.gpt-oss-120b-1_0_<timestamp>.jsonl # Results for bedrock
```

Each JSONL file contains:
- `case_index`: Test case number
- `original_id`: Original LLM call ID from production
- `model_name`: Model used
- `prompt_tokens`, `completion_tokens`, `total_tokens`: Token usage
- `estimated_cost_usd`: Cost estimate
- `duration_ms`: Response time
- `input_messages`: Prompt sent to model
- `output_content`: Raw model response
- `parsed_response`: Parsed/structured response from handler

## Analysis

Use the Jupyter notebook to analyze results:

```bash
jupyter notebook experiments/compare_models/analyze_experiment_results.ipynb
```

The notebook provides:
1. Agreement rates between models
2. Parse success rates
3. Token usage and cost analysis
4. Response time comparison
5. Quality metrics per call type
6. Model-specific failure modes

## Key Metrics

### Agreement Rate
Percentage of cases where two models produce identical responses (exact match or semantic equivalence depending on handler).

### Parse Success Rate
Percentage of responses that successfully parse according to the handler's schema.

### Cost Efficiency
Cost per successful response, comparing quality vs. spend.

### Response Time
Average API latency per call type and model.

## Known Issues

### GPT-5-nano Quality Issues

Based on initial testing, gpt-5-nano shows inconsistent performance on complex tasks:

- **structure_analysis**: Failed to extract all instruments in some cases (1/7 vs 7/7 for mini)
- **Token inefficiency**: Used 2.1x MORE tokens but produced 8.8x LESS output in failure cases
- **Recommendation**: Use with caution for Tier 4 complex nested JSON tasks

### Bedrock Rate Limits

AWS Bedrock may have lower rate limits than OpenAI. If you encounter throttling:
- Add retry logic with exponential backoff (already built into LiteLLM)
- Consider running bedrock separately from OpenAI models

## Test Data Source

All test cases exported from production using:
```bash
./scripts/export_test_set_calls.sh
```

Tag: `test_set_2025_10_10`

Cases include real production data with `render_context` for reproducible prompt rendering.

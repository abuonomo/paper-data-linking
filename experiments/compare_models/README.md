# Multi-Model Comparison & Prompt Experimentation

This folder contains tools for testing LLM prompts across different models and comparing outputs. The system uses **render_context** tracking to enable prompt iteration without re-running the production pipeline.

## Directory Structure

```
experiments/compare_models/
├── core/                    # Framework infrastructure (handlers, registry, schemas)
├── handlers/                # Response parsers for each call type
├── self_consistency/        # Self-consistency analysis (5 runs @ temp=1.0)
│   ├── results/             # Self-consistency experiment outputs
│   │   └── test_set_2025_11_26/
│   │       └── {call_type}/run{N}/
│   ├── self_consistency_experiments.ipynb  # Main notebook (run experiments + analysis)
│   ├── run_experiments.py   # Python runner (used by notebook)
│   └── SELF_CONSISTENCY_REPORT.md
├── model_comparison/        # Cross-model comparison tools
│   ├── results/             # Model comparison experiment outputs
│   ├── analyze_experiment_results.ipynb
│   ├── explore_disagreements.ipynb
│   └── visualize_*.py
├── misc/                    # Ad-hoc scripts, old experiments (for review)
├── run_prompt_experiment.py   # Core experiment runner
└── run_parallel_experiment.py # Parallel experiment runner (multi-model, multi-call-type)
```

## Table of Contents
- [Architecture Overview](#architecture-overview)
- [Prerequisites](#prerequisites)
- [Quick Start](#quick-start)
- [YAML Configuration](#yaml-configuration)
- [Detailed Workflow](#detailed-workflow)
- [Available Call Types](#available-call-types)
- [Troubleshooting](#troubleshooting)

---

## Architecture Overview

### The render_context System

Every LLM call in production now captures the **template variables** used to render the prompt, stored in the `LLMCall.render_context` field. This enables:

1. **Prompt Iteration**: Test new prompt templates on historical data without re-running expensive production pipelines
2. **Model Comparison**: Compare different models using identical inputs reconstructed from render_context
3. **A/B Testing**: Systematically test prompt variations on the same cases

**How it works:**

```
Production Pipeline                         Prompt Experiments
─────────────────                          ──────────────────

1. normalize_data()                        1. export_llm_calls
   ├─ load_and_render_prompt()                ↓
   │  ("physobs_normalization",            2. JSONL with render_context:
   │   instrument_code="C2",                  {
   │   candidates=["intensity"],               "render_context": {
   │   raw_observable="images")                 "template_name": "physobs_...",
   │                                            "instrument_code": "C2",
   ├─ llm_client.completion(                    "candidates": ["intensity"],
   │    prompt_context={...})                   "raw_observable": "images"
   │                                          }
   └─ Saves to LLMCall table                }
      with render_context                      ↓
                                           3. run_prompt_experiment.py
                                              ├─ Uses handler.render_user_message()
                                              ├─ Reconstructs prompt from render_context
                                              ├─ Calls LLM with new template/model
                                              └─ Compares outputs
```

### Key Components

1. **`export_llm_calls`**: Django management command to export LLMCall records as JSONL
2. **`run_prompt_experiment.py`**: Script to re-run experiments with different models/prompts
3. **Handlers** (`handlers/*.py`): Parse and compare responses for each call type
4. **Templates** (`paper_data_linking/linkers/general/prompts/`): XML prompt templates

---

## Prerequisites

1. **Environment setup**:
   ```bash
   # Create .env at repo root with API keys
   echo "OPENAI_API_KEY=your_key_here" >> .env
   ```

2. **Python dependencies**:
   ```bash
   # Install base dependencies
   uv sync

   # Install experiment-specific dependencies (streamlit, seaborn, matplotlib, pyyaml)
   pip install -e .[experiments]
   ```

3. **Database with LLMCall records**:
   - Run production pipeline at least once to populate LLMCall table
   - Ensure calls have `render_context` populated (added in migration 0059)

---

## Quick Start

### Example: Test physobs_normalization with different models

```bash
# 1. Export test cases from production LLMCalls
python api/manage.py export_llm_calls \
  --call-type physobs_normalization \
  --require-render-context \
  --output inputs/physobs_test_10.jsonl \
  --limit 10

# 2. Run experiment on multiple models
PYTHONPATH=. python experiments/compare_models/run_prompt_experiment.py \
  --call-type physobs_normalization \
  --input inputs/physobs_test_10.jsonl \
  --system-prompt paper_data_linking/linkers/general/prompts/physobs_normalization/system.xml \
  --models openai/gpt-5-mini openai/gpt-5-nano \
  --experiment-name physobs_model_comparison \
  --output-dir experiments/compare_models/results

# 3. Check results
ls -lh experiments/compare_models/results/physobs_model_comparison/
# Contains: system_prompt.xml, openai_gpt-5-mini_*.jsonl, openai_gpt-5-nano_*.jsonl
```

**Output includes**:
- Per-model JSONL files with parsed responses
- Token usage and cost per case
- Success/failure rates
- Saved system prompt for reproducibility

---

## YAML Configuration

For running experiments via `run_parallel_experiment.py`, you can use YAML config files:

```bash
python experiments/compare_models/run_parallel_experiment.py \
    --config experiments/compare_models/experiment_configs/my_experiment.yaml
```

### Basic YAML Structure

```yaml
experiment_name: my_experiment
description: "Brief description"

models:
  - openai/gpt-5-mini
  - bedrock/openai.gpt-oss-120b-1:0

call_types:
  - physobs_normalization
  - wavelength_normalization

max_cases: 100      # Limit test cases per call type
max_workers: 4      # Parallel workers
timeout_seconds: 600

call_type_configs:
  physobs_normalization:
    prompt: paper_data_linking/linkers/general/prompts/physobs_normalization/system.xml
    input: inputs/test_set/physobs_normalization.jsonl
    handler_class: PhysObsNormalizationHandler
```

See `misc/EXPERIMENT_CONFIG_GUIDE.md` for full documentation on handlers, prompts, and test data format.

---

## Detailed Workflow

### Step 1: Export LLMCall Records

Export calls from production database with render_context:

```bash
python api/manage.py export_llm_calls \
  --call-type <call_type> \
  --require-render-context \
  --output <output.jsonl> \
  [--limit N] \
  [--config <config_name>] \
  [--paper-bibcode <bibcode>]
```

**Key flags**:
- `--call-type`: Filter by call type (e.g., `physobs_normalization`, `instrument_validation`)
- `--require-render-context`: **Critical** - only exports calls that have render_context populated
- `--limit N`: Export first N matching records
- `--config`: Filter by analysis config name
- `--paper-bibcode`: Filter by specific paper

**Output format (JSONL)**:
```json
{
  "id": "uuid",
  "created_at": "2025-10-10T16:33:45.945744+00:00",
  "call_type": "physobs_normalization",
  "model_name": "openai/gpt-5-mini",
  "provider": "openai",
  "prompt_tokens": 1381,
  "completion_tokens": 45,
  "total_tokens": 1426,
  "estimated_cost_usd": 0.000234,
  "output_content": "intensity",
  "render_context": {
    "template_name": "physobs_normalization",
    "instrument_code": "C2",
    "candidates": ["intensity", "dopplergram"],
    "raw_observable": "imaging data from coronagraph"
  },
  "input_messages": [...],
  "analysis_configs": ["budget"],
  "paper_bibcodes": ["2021ApJS..257...33M"]
}
```

### Step 2: Run Prompt Experiment

Test different models or prompt variations:

```bash
PYTHONPATH=. python experiments/compare_models/run_prompt_experiment.py \
  --call-type <call_type> \
  --input <input.jsonl> \
  --system-prompt <path/to/system.xml> \
  --models <model1> [model2 ...] \
  --experiment-name <name> \
  --output-dir <output_dir> \
  [--timeout-sec 60] \
  [--max-retries 1] \
  [--temperature 1.0]
```

**How it works**:
1. Loads handler for the specified call type
2. For each case:
   - Extracts `render_context` from exported JSONL
   - Calls `handler.render_user_message(test_case)` to reconstruct prompt
   - Uses provided `--system-prompt` (allows testing prompt variations)
   - Calls each model with reconstructed messages
   - Parses and validates response using handler
3. Saves per-model results as JSONL

**Key features**:
- **Prompt iteration**: Change `--system-prompt` to test new templates on same data
- **Model comparison**: Pass multiple `--models` to compare in one run
- **Reproducibility**: Saves system prompt used for each experiment

### Step 3: Analyze Results

Results are saved in experiment directory:

```bash
experiments/compare_models/results/
└── <experiment_name>/
    ├── system_prompt.xml                    # Prompt template used
    ├── openai_gpt-5-mini_20251010_143521.jsonl   # Per-model results
    └── openai_gpt-5-nano_20251010_143531.jsonl
```

**Each result includes**:
```json
{
  "case_index": 1,
  "original_id": "uuid-from-export",
  "model_name": "openai/gpt-5-nano",
  "call_type": "physobs_normalization",
  "created_at": "2025-10-10T14:35:21.123456",
  "provider": "openai",
  "prompt_tokens": 892,
  "completion_tokens": 23,
  "total_tokens": 915,
  "estimated_cost_usd": 0.000156,
  "duration_ms": 1234,
  "input_messages": [...],
  "output_content": "intensity",
  "parsed_response": {
    "physical_observable": "intensity",
    "original_text": "imaging data from coronagraph"
  },
  "system_prompt_path": "paper_data_linking/linkers/general/prompts/physobs_normalization/system.xml"
}
```

**Compare with original**:
```bash
# Quick comparison script
python3 << 'EOF'
import json

# Load original
originals = {}
with open('inputs/test_cases.jsonl') as f:
    for line in f:
        data = json.loads(line)
        originals[data['id']] = data['output_content']

# Load new results
matches = 0
total = 0
with open('experiments/.../openai_gpt-5-nano_*.jsonl') as f:
    for line in f:
        data = json.loads(line)
        total += 1
        if data['output_content'] == originals[data['original_id']]:
            matches += 1

print(f"Agreement: {matches}/{total} ({matches/total*100:.1f}%)")
EOF
```

---

## Available Call Types

### Normalization Call Types

These use structured outputs and have dedicated handlers:

#### 1. `physobs_normalization`
Maps raw observable text to VSO-approved physical observables.

**Export example**:
```bash
python api/manage.py export_llm_calls \
  --call-type physobs_normalization \
  --require-render-context \
  --output inputs/physobs_cases.jsonl
```

**render_context fields**:
- `template_name`: "physobs_normalization"
- `instrument_code`: VSO instrument code (e.g., "C2")
- `candidates`: List of valid physobs for this instrument
- `raw_observable`: Raw text from paper

**Handler**: `handlers/physobs_normalization.py`
- Compares: `physical_observable` field
- Metrics: Exact match (agree/disagree)

#### 2. `wavelength_normalization`
Parses raw wavelength strings into structured format (values, unit, type).

**render_context fields**:
- `template_name`: "wavelength_normalization"
- `raw_wavelength`: Raw wavelength text from paper

**Handler**: `handlers/wavelength_normalization.py`

#### 3. `time_normalization`
Parses time ranges into ISO format.

**render_context fields**:
- `template_name`: "time_normalization"
- `raw_time`: Raw time range text

#### 4. `detector_normalization`
Selects detector from VSO-approved list.

**render_context fields**:
- `template_name`: "detector_normalization"
- `instrument_code`: VSO instrument code
- `candidates`: List of valid detectors
- `raw_detector_context`: Context text for detector identification

#### 5. `cadence_normalization`
Normalizes observation cadence to ISO 8601 duration.

**render_context fields**:
- `template_name`: "cadence_normalization"
- `raw_cadence_context`: Context text containing cadence info

### Grounding Call Types

These use text-based responses:

#### 6. `instrument_validation`
Validates if matched instrument aligns with paper description.

**Export example**:
```bash
python api/manage.py export_llm_calls \
  --call-type instrument_validation \
  --require-render-context \
  --output inputs/validation_cases.jsonl \
  --limit 20
```

**render_context fields**:
- `template_name`: "validation"
- `original_name`: Instrument name from paper
- `original_comments`: Context from paper
- `matched_instrument_name`: Proposed instrument name
- `matched_instrument_code`: Proposed instrument code
- `matched_mission_name`: Proposed mission name
- `matched_mission_code`: Proposed mission code
- `time_info`: Time period if available
- `obs_info`: Observable info if available

**Handler**: `handlers/instrument_validation.py`
- Compares: Extracted decision ("valid" or "invalid")
- Metrics: Agreement, precision, recall, F1

#### 7. `mission_identification`
Identifies top candidate missions from large list (stage 1 of grounding).

**render_context fields**:
- `template_name`: "mission_identification"
- `mission_context`: Extracted mission-focused context
- `missions_text`: Numbered list of all mission candidates
- `mission_count`: Total number of missions
- `top_k`: Number of missions to select (usually 10)

#### 8. `mission_selection`
Selects final mission(s) from filtered candidates (stage 2 of grounding).

**Export example**:
```bash
python api/manage.py export_llm_calls \
  --call-type mission_selection \
  --require-render-context \
  --output inputs/mission_selection.jsonl
```

**render_context fields**:
- `template_name`: "mission_selection"
- `mission_context`: Instrument/mission context
- `candidates_text`: Numbered list of candidate missions
- `candidate_count`: Number of candidates

**Handler**: `handlers/mission_selection.py`
- Compares: Selected mission indices with multiple metrics
- Metrics:
  - **Exact match**: Same missions selected
  - **Top-1 match**: Agreement on primary mission
  - **Set overlap**: Number of overlapping selections
  - **Jaccard similarity**: Quantitative overlap (0.0-1.0)
  - **Ambiguity detection**: Both returned "0" (no match)

**Example output**:
```
Response 1: [1] | Response 2: [1] | Exact match: True | Top-1 match: True | Jaccard: 1.00
Response 1: [1,2,3] | Response 2: [2,3,4] | Exact match: False | Top-1 match: False | Overlap: {2,3} | Jaccard: 0.50
Response 1: [0] | Response 2: [0] | Both ambiguous: True
```

#### 9. `instrument_selection`
Selects final instrument(s) from filtered candidates (stage 3 of grounding).

**render_context fields**:
- `template_name`: "instrument_selection"
- `full_context`: Complete instrument context
- `instruments_text`: Numbered list of candidate instruments
- `instrument_count`: Number of candidates

#### 10. `instrument_multiple_selection`
Identifies all valid instruments when multiple are possible.

**render_context fields**:
- `template_name`: "multiple_matches"
- `full_context`: Complete instrument context
- `instruments_text`: Numbered list of instruments

### Analysis Call Types

#### 11. `paper_analysis`
Extracts instrument details from full paper text.

**render_context fields**:
- `template_name`: "paper_analysis"
- `paper_text`: Full paper text (usually very long)

#### 12. `structure_analysis`
Parses unstructured instrument details into structured JSON.

**render_context fields**:
- `template_name`: "structured_parsing"
- `instruments_details_text`: Raw markdown instrument details

---

## Creating New Handlers

To support a new call type:

### 1. Create handler file

`experiments/compare_models/handlers/my_call_type.py`:

```python
from typing import Optional, Dict, Any
from experiments.compare_models.core.call_handlers import CallTypeHandler, ComparisonResult
from paper_data_linking.linkers.general.prompt_loader import load_and_render_prompt

class MyCallTypeHandler(CallTypeHandler):
    def get_call_type_name(self) -> str:
        return "my_call_type"

    def get_response_format(self) -> Optional[type]:
        # Return Pydantic model for structured output, or None for text
        return None

    def parse_response(self, response: str) -> Optional[Dict[str, Any]]:
        """Parse LLM response into structured dict"""
        # Your parsing logic here
        return {"field": "value"}

    def compare_responses(self, resp1: Optional[Dict], resp2: Optional[Dict]) -> ComparisonResult:
        """Compare two responses and return agreement metrics"""
        agree = (resp1 == resp2)
        details = f"Response 1: {resp1}, Response 2: {resp2}"
        return ComparisonResult(agree=agree, resp1=resp1, resp2=resp2, details=details)

    def format_for_html(self, response: Optional[Dict], is_agreement: bool = True) -> str:
        """Format response for HTML visualization"""
        return f"<span>{response}</span>"

    def get_short_summary(self, response: Optional[Dict]) -> str:
        """Brief summary for logging"""
        return str(response)

    def render_user_message(self, test_case: dict) -> str:
        """Reconstruct user message from render_context"""
        ctx = test_case.get('render_context', {})

        # Extract variables from render_context
        var1 = ctx.get('var1')
        var2 = ctx.get('var2')

        # Use load_and_render_prompt to reconstruct
        _, user_msg = load_and_render_prompt(
            ctx['template_name'],
            var1=var1,
            var2=var2
        )

        return user_msg
```

### 2. Register handler

Add to `experiments/compare_models/handlers/__init__.py`:

```python
from .my_call_type import MyCallTypeHandler

# In __init__.py:
CallTypeRegistry.register(MyCallTypeHandler())

__all__ = [
    # ... existing handlers
    'MyCallTypeHandler',
]
```

### 3. Test handler

```bash
PYTHONPATH=. python experiments/compare_models/run_prompt_experiment.py \
  --call-type my_call_type \
  --input inputs/my_test_cases.jsonl \
  --system-prompt path/to/system.xml \
  --models openai/gpt-5-nano \
  --experiment-name test_my_handler
```

---

## Troubleshooting

### Export Issues

**Problem**: `export_llm_calls` returns 0 records

**Solutions**:
1. Check filter criteria:
   ```bash
   # Check what's in database
   python api/manage.py shell -c "
   from api.vso_query_builder.models import LLMCall
   print('Total LLMCalls:', LLMCall.objects.count())
   print('With render_context:', LLMCall.objects.filter(render_context__isnull=False).count())
   print('Call types:', LLMCall.objects.values_list('call_type', flat=True).distinct())
   "
   ```

2. Remove `--require-render-context` to see all calls:
   ```bash
   python api/manage.py export_llm_calls --call-type physobs_normalization --output test.jsonl
   ```

3. Check if render_context exists in older records:
   - Migration 0059 added `render_context` field
   - Only LLMCalls created after migration have render_context populated
   - Re-run production pipeline to populate render_context for test cases

**Problem**: "No module named 'paper_data_linking'"

**Solution**: Always run from repo root with `PYTHONPATH=.`:
```bash
cd /path/to/paper-data-linking
PYTHONPATH=. python experiments/compare_models/run_prompt_experiment.py ...
```

### Experiment Issues

**Problem**: "Handler not found for call type X"

**Solution**: Check handler is registered:
```bash
PYTHONPATH=. python -c "
from experiments.compare_models.core.registry import CallTypeRegistry
print('Available handlers:', CallTypeRegistry.list_call_types())
"
```

**Problem**: All responses parse as `None`

**Solutions**:
1. Check handler's `parse_response()` method matches actual LLM output format
2. Add debug logging to handler:
   ```python
   def parse_response(self, response: str) -> Optional[Dict]:
       print(f"DEBUG: Raw response: {response!r}")
       # ... parsing logic
   ```
3. Check if model is following expected format (some models ignore structured output hints)

**Problem**: LLM calls timeout

**Solutions**:
```bash
# Increase timeout
--timeout-sec 120

# Reduce retries to fail fast
--max-retries 0

# Test with smaller model first
--models openai/gpt-5-nano
```

### Comparison Issues

**Problem**: Low agreement rate between models

**Analysis steps**:
1. Check if disagreements are legitimate differences vs parsing errors
2. Examine `parsed_response` field in output JSONL
3. Compare raw `output_content` strings
4. Look for patterns:
   - Model A consistently more strict/lenient?
   - Specific cases where models disagree?
   - Are disagreements on edge cases or clear-cut cases?

**Example analysis**:
```python
import json

# Load both result files
with open('gpt-5-mini_results.jsonl') as f:
    mini = [json.loads(line) for line in f]
with open('gpt-5-nano_results.jsonl') as f:
    nano = [json.loads(line) for line in f]

# Find disagreements
for m, n in zip(mini, nano):
    if m['parsed_response'] != n['parsed_response']:
        print(f"Case {m['case_index']}: DISAGREE")
        print(f"  Mini: {m['parsed_response']}")
        print(f"  Nano: {n['parsed_response']}")
        print(f"  Original: {m['original_id']}")
        print()
```

---

## Tips & Best Practices

### 1. Start Small

Always test with a small sample first:
```bash
# Export just 5 cases
--limit 5

# Test on single model
--models openai/gpt-5-nano
```

### 2. Iterative Prompt Development

```bash
# 1. Export baseline test set once
python api/manage.py export_llm_calls \
  --call-type physobs_normalization \
  --require-render-context \
  --output inputs/physobs_dev_set.jsonl \
  --limit 20

# 2. Iterate on prompt template
# Edit: paper_data_linking/linkers/general/prompts/physobs_normalization/system.xml

# 3. Test iteration
PYTHONPATH=. python experiments/compare_models/run_prompt_experiment.py \
  --call-type physobs_normalization \
  --input inputs/physobs_dev_set.jsonl \
  --system-prompt paper_data_linking/linkers/general/prompts/physobs_normalization/system.xml \
  --models openai/gpt-5-nano \
  --experiment-name physobs_iteration_v2

# 4. Compare results, go back to step 2
```

### 3. Cost Management

Track costs across experiments:
```bash
# Extract costs from results
python3 << 'EOF'
import json
import glob

total_cost = 0
total_tokens = 0

for file in glob.glob('experiments/compare_models/results/*/*.jsonl'):
    with open(file) as f:
        for line in f:
            data = json.loads(line)
            total_cost += data.get('estimated_cost_usd', 0)
            total_tokens += data.get('total_tokens', 0)

print(f"Total cost: ${total_cost:.4f}")
print(f"Total tokens: {total_tokens:,}")
print(f"Cost per 1K tokens: ${total_cost / (total_tokens/1000):.4f}")
EOF
```

### 4. Reproducibility

Always save experiment metadata:
```bash
# Experiment tracking template
cat > experiments/compare_models/results/my_experiment/README.md << 'EOF'
# Experiment: my_experiment

**Date**: 2025-10-10
**Goal**: Test gpt-5-nano performance on physobs normalization
**Hypothesis**: Nano will match mini on clear cases but differ on ambiguous ones

## Setup
- Input: inputs/physobs_dev_set.jsonl (20 cases)
- Models: openai/gpt-5-nano
- System prompt: physobs_normalization/system.xml (unchanged from production)

## Results
- Exact match with production: 18/20 (90%)
- Disagreements: Cases 7, 14
- Cost: $0.0034

## Conclusions
- Nano performance acceptable for production
- Cases 7, 14 need manual review (both involve ambiguous observable descriptions)
EOF
```

### 5. Latest Files Helper

```bash
# Add to ~/.bashrc or ~/.zshrc
latest_experiment() {
    ls -td experiments/compare_models/results/*/ | head -1
}

latest_results() {
    ls -t $(latest_experiment)/*.jsonl | head -1
}

# Usage:
cat $(latest_results) | jq '.parsed_response'
```

---

## Streamlit Annotation Tools

Two interactive Streamlit applications are available for analyzing and annotating model disagreements:

### 1. Disagreement Annotator

Interactive tool for manually reviewing and annotating cases where models disagree.

```bash
# Requires streamlit (installed via [experiments] dependencies)
streamlit run experiments/compare_models/model_comparison/disagreement_annotator.py
```

**Features**:
- Side-by-side comparison of model responses
- Manual annotation of correct responses
- Save annotations to JSONL for training data
- Filter by call type and disagreement type

See `misc/ANNOTATOR_README.md` for detailed usage instructions.

### 2. Mission Selection Disagreement Viewer

Specialized viewer for analyzing mission selection disagreements.

```bash
streamlit run experiments/compare_models/model_comparison/mission_selection_disagreement_viewer.py
```

**Features**:
- Visualize mission selection patterns
- Analyze agreement metrics (exact match, top-1, Jaccard)
- Identify systematic disagreement patterns
- Export filtered disagreements for further analysis

---

## Migrating from Old run_compare.py

If you have existing workflows using `run_compare.py`:

**Old approach** (pre-rendered prompts):
```bash
# Export with full messages
python api/manage.py export_llm_calls \
  --call-type instrument_validation \
  --output inputs/validation.jsonl

# Replay same messages
python experiments/compare_models/run_compare.py \
  --input inputs/validation.jsonl \
  --models openai/gpt-5-mini
```

**New approach** (render_context):
```bash
# Export with render_context
python api/manage.py export_llm_calls \
  --call-type instrument_validation \
  --require-render-context \
  --output inputs/validation.jsonl

# Reconstruct and test
PYTHONPATH=. python experiments/compare_models/run_prompt_experiment.py \
  --call-type instrument_validation \
  --input inputs/validation.jsonl \
  --system-prompt paper_data_linking/linkers/general/prompts/validation/system.xml \
  --models openai/gpt-5-mini \
  --experiment-name validation_test
```

**Benefits of new approach**:
- ✅ Can modify prompts without re-exporting
- ✅ Template variables visible in export
- ✅ Supports all call types with render_context
- ✅ Easier debugging (can see what variables were used)

---

## See Also

- **Handler Development**: `misc/README_HANDLERS.md` (detailed guide on creating handlers)
- **Prompt Templates**: `paper_data_linking/linkers/general/prompts/*/system.xml`
- **LLM Tracking**: `api/vso_query_builder/models.py` (LLMCall model definition)
- **Prompt Loader**: `paper_data_linking/linkers/general/prompt_loader.py`
- **Self-Consistency Analysis**: `self_consistency/SELF_CONSISTENCY_REPORT.md`
- **Model Comparison Tools**: `model_comparison/` directory

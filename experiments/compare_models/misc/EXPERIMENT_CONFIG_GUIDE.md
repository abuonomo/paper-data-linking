# Experiment Configuration Guide

This guide explains how to use the YAML-based experiment configuration system for running LLM model comparison experiments.

## Overview

The experiment framework allows you to test different LLM models, prompts, and response formats across various call types (normalization tasks, validation tasks, etc.). Each experiment is defined by a self-contained YAML configuration file.

## Quick Start

### Running an Experiment from YAML Config

```bash
python experiments/compare_models/run_parallel_experiment.py \
    --config experiments/compare_models/experiment_configs/physobs_free_text_example.yaml
```

### Running an Experiment with CLI Arguments (Legacy Mode)

```bash
python experiments/compare_models/run_parallel_experiment.py \
    --models openai/gpt-5-mini bedrock/openai.gpt-oss-120b-1:0 \
    --call-types detector_normalization wavelength_normalization \
    --max-cases 100 \
    --max-workers 4
```

## YAML Configuration Structure

### Basic Example

```yaml
experiment_name: my_experiment
description: "Brief description of what this experiment tests"

# Models to test
models:
  - openai/gpt-5-mini
  - openai/gpt-5-nano
  - bedrock/openai.gpt-oss-120b-1:0

# Call types to run
call_types:
  - physobs_free_text
  - wavelength_normalization

# Experiment parameters
max_cases: 100  # Limit number of test cases per call type
max_workers: 4  # Number of parallel workers
timeout_seconds: 600  # Timeout per task
output_dir: experiments/compare_models/prompt_experiments

# Call type configurations
call_type_configs:
  physobs_normalization:
    # Path to system prompt XML
    prompt: paper_data_linking/linkers/general/prompts/physobs_normalization/system.xml

    # Path to test data JSONL
    input: inputs/test_set/physobs_normalization.jsonl

    # Handler class to use
    handler_class: PhysObsNormalizationFreeTextV2Handler

  wavelength_normalization:
    prompt: paper_data_linking/linkers/general/prompts/wavelength_normalization/system.xml
    input: inputs/test_set/wavelength_normalization.jsonl
    handler_class: WavelengthNormalizationHandler
```

### Configuration Fields

#### Top-Level Fields

- **`experiment_name`** (required): Name for the experiment, used for output directory
- **`description`** (optional): Human-readable description of the experiment
- **`models`** (required): List of model identifiers to test
- **`call_types`** (required): List of call type names to run
- **`max_cases`** (optional): Maximum number of test cases per call type (default: all cases)
- **`max_workers`** (optional): Number of parallel workers (default: 4)
- **`timeout_seconds`** (optional): Timeout per task in seconds (default: 600)
- **`output_dir`** (optional): Base output directory (default: `experiments/compare_models/prompt_experiments`)

#### Call Type Configuration

Each entry in `call_type_configs` maps a call type name to its configuration:

- **`prompt`** (required): Path to system prompt XML file
- **`input`** (required): Path to test data JSONL file
- **`handler_class`** (required): Name of the handler class to use

## Creating Custom Handlers

Handlers are responsible for:
1. Rendering user messages from test data
2. Defining response format (Pydantic schema or free-text)
3. Parsing LLM responses
4. Comparing responses for consistency analysis
5. Formatting results for display

### Handler Architecture

Each handler extends `CallTypeHandler` and implements these methods:

```python
from experiments.compare_models.core.handler import CallTypeHandler, ComparisonResult
from typing import Optional, Dict, Any

class MyCustomHandler(CallTypeHandler):
    def get_call_type_name(self) -> str:
        """Return the call type identifier."""
        return "my_custom_task"

    def get_response_format(self) -> Optional[type]:
        """Return Pydantic model for structured output, or None for free-text."""
        return None  # or MyPydanticModel

    def parse_response(self, response: str) -> Optional[Dict[str, Any]]:
        """Parse the LLM response into a structured format."""
        # Implementation here
        pass

    def compare_responses(self, resp1, resp2) -> ComparisonResult:
        """Compare two responses for consistency analysis."""
        # Implementation here
        pass

    def render_user_message(self, case: Dict[str, Any]) -> str:
        """Render user prompt from test case data."""
        # Load and render Jinja2 template
        pass

    def format_for_html(self, response: Any) -> str:
        """Format response for HTML display (optional)."""
        return str(response)

    def get_short_summary(self, response: Any) -> str:
        """Get short summary for logging (optional)."""
        return str(response)
```

### Handler Philosophy: Opinionated by Design

**Each handler is fully opinionated** - it owns its behavior completely:

- If you want a **different response format** (schema vs free-text), create a new handler
- If you want **different parsing logic**, create a new handler
- If you want **different comparison metrics**, create a new handler

**Do NOT add config toggles** like `use_schema: true/false`. Instead, create variant handlers:
- `PhysObsNormalizationHandler` - uses Pydantic schema
- `PhysObsNormalizationFreeTextHandler` - uses free-text responses

This keeps handlers simple, testable, and maintainable.

### Registering a Handler

After creating your handler, register it in `experiments/compare_models/handlers/__init__.py`:

```python
from experiments.compare_models.handlers.my_custom_handler import MyCustomHandler
from experiments.compare_models.core.registry import CallTypeRegistry

# Register the handler
CallTypeRegistry.register(MyCustomHandler())
```

### Handler with Pydantic Schema Example

```python
from pydantic import BaseModel
from typing import Optional

class MyResponseSchema(BaseModel):
    result: str
    confidence: float

class MySchemaHandler(CallTypeHandler):
    def get_response_format(self) -> Optional[type]:
        return MyResponseSchema  # LLM will generate structured JSON

    def parse_response(self, response: str) -> Optional[Dict[str, Any]]:
        try:
            # Response is already validated by the model provider
            parsed = MyResponseSchema.model_validate_json(response)
            return parsed.model_dump()
        except Exception:
            return None  # Parse failure

    def compare_responses(self, resp1, resp2) -> ComparisonResult:
        match = (resp1.get('result') == resp2.get('result'))
        return ComparisonResult(match=match, details={'result': resp1.get('result')})
```

### Handler with Free-Text Example

```python
class MyFreeTextHandler(CallTypeHandler):
    def get_response_format(self) -> Optional[type]:
        return None  # No schema - free-text response

    def parse_response(self, response: str) -> Optional[Dict[str, Any]]:
        # Custom parsing logic for unstructured text
        lines = response.strip().split('\n')
        if len(lines) < 2:
            return None  # Parse failure

        return {
            'result': lines[0],
            'reasoning': '\n'.join(lines[1:])
        }

    def compare_responses(self, resp1, resp2) -> ComparisonResult:
        match = (resp1.get('result') == resp2.get('result'))
        return ComparisonResult(match=match, details={'result': resp1.get('result')})
```

## Creating Custom Prompts

### Prompt Directory Structure

Each call type should have its own prompt directory:

```
paper_data_linking/linkers/general/prompts/
└── my_custom_task/
    ├── system.xml  # System prompt (instructions)
    └── user.xml    # User prompt template (Jinja2)
```

### System Prompt (system.xml)

The system prompt defines the task and instructions:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<task_instructions>
  You are an expert at normalizing scientific instrument descriptions.

  <task>
  Given an instrument code, list of valid candidates, and a description from a paper,
  identify which candidate best matches the description.
  </task>

  <output_format>
  Return only the matching candidate name, or "UNKNOWN" if no match.
  </output_format>

  <examples>
    <example>
      Instrument: ACE/SWEPAM
      Candidates: ["proton_density", "electron_temperature"]
      Description: "solar wind proton density measurements"
      Answer: proton_density
    </example>
  </examples>
</task_instructions>
```

### User Prompt Template (user.xml)

The user prompt is a Jinja2 template rendered with test case data:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<user_prompt>
Instrument: {{ instrument_code }}

Valid candidates:
{% for candidate in candidates %}
- {{ candidate }}
{% endfor %}

Paper description:
"{{ raw_observable }}"

Which candidate matches this description?
</user_prompt>
```

Available template variables depend on your test data JSONL format and how `render_user_message()` is implemented.

## Test Data Format

Test data is stored as JSONL (one JSON object per line):

```jsonl
{"id": "case1", "raw_inputs": {"instrument_code": "ACE/SWEPAM", "candidates": ["proton_density", "electron_temperature"], "raw_observable": "solar wind proton density"}, "expected_output": {"physical_observable": "proton_density"}}
{"id": "case2", "raw_inputs": {"instrument_code": "SOHO/LASCO", "candidates": ["c2", "c3"], "raw_observable": "coronagraph C2 observations"}, "expected_output": {"physical_observable": "c2"}}
```

### Required Fields

- **`id`**: Unique identifier for the test case
- **`raw_inputs`**: Dictionary of inputs for the handler's `render_user_message()` method
- **`expected_output`**: Ground truth for evaluation (optional)

## Output Structure

Experiments produce output in the following structure:

```
experiments/compare_models/prompt_experiments/
└── my_experiment/
    ├── system_prompt.xml  # Copy of system prompt used
    ├── openai_gpt-5-mini_20241112_143022.jsonl
    ├── openai_gpt-5-nano_20241112_143045.jsonl
    └── bedrock_openai.gpt-oss-120b-1_0_20241112_143101.jsonl
```

Each JSONL file contains results for one model:

```json
{
  "case_index": 1,
  "original_id": "case1",
  "model_name": "openai/gpt-5-mini",
  "call_type": "physobs_free_text",
  "created_at": "2024-11-12T14:30:22.123456",
  "provider": "openai",
  "prompt_tokens": 234,
  "completion_tokens": 12,
  "total_tokens": 246,
  "estimated_cost_usd": 0.000123,
  "duration_ms": 1234,
  "input_messages": [...],
  "output_content": "proton_density",
  "parsed_response": {"result": "proton_density"},
  "system_prompt_path": "..."
}
```

## Analyzing Results

### Self-Consistency Analysis

Run the same experiment 5 times with the same config to measure reliability:

```bash
# Run 5 times
for i in {1..5}; do
  python experiments/compare_models/run_parallel_experiment.py \
    --config experiments/compare_models/experiment_configs/my_experiment.yaml
done

# Analyze consistency
python experiments/compare_models/analyze_self_consistency.py \
    --call-type my_custom_task \
    --experiment-dir experiments/compare_models/prompt_experiments/my_experiment_run1 \
    --experiment-dir experiments/compare_models/prompt_experiments/my_experiment_run2 \
    --experiment-dir experiments/compare_models/prompt_experiments/my_experiment_run3 \
    --experiment-dir experiments/compare_models/prompt_experiments/my_experiment_run4 \
    --experiment-dir experiments/compare_models/prompt_experiments/my_experiment_run5
```

Produces metrics:
- **Fleiss' Kappa**: Multi-rater agreement statistic
- **Parse Success Rate**: % of responses that parse successfully
- **Semantic Consistency**: Agreement rate among parsed responses
- **95% Confidence Intervals**: Bootstrap CIs for reliability

## Example: physobs_free_text Handler (Stub)

The `PhysObsNormalizationFreeTextHandler` is provided as a stub example:

```yaml
# experiments/compare_models/experiment_configs/physobs_free_text_example.yaml
experiment_name: physobs_free_text_example
description: "Test physobs normalization without Pydantic schema"

models:
  - openai/gpt-5-mini

call_types:
  - physobs_free_text

max_cases: 5
max_workers: 2
timeout_seconds: 600

call_type_configs:
  physobs_normalization:
    prompt: paper_data_linking/linkers/general/prompts/physobs_normalization/system.xml
    input: inputs/test_set/physobs_normalization.jsonl
    handler_class: PhysObsNormalizationFreeTextV2Handler
```

## Legacy CLI Mode

The old CLI argument system still works for backward compatibility:

```bash
python experiments/compare_models/run_parallel_experiment.py \
    --models openai/gpt-5-mini bedrock/openai.gpt-oss-120b-1:0 \
    --call-types detector_normalization wavelength_normalization \
    --max-cases 100 \
    --max-workers 4 \
    --experiment-name my_experiment
```

This uses the hardcoded `CALL_TYPES` dictionary in `run_parallel_experiment.py` for call type configurations.

## Best Practices

1. **One config per experiment**: Each experiment should have its own YAML file
2. **Descriptive names**: Use clear experiment names that describe what's being tested
3. **Version prompts**: Keep old prompt versions when creating new ones for comparison
4. **Small test runs first**: Use `max_cases: 5` to quickly test new configs
5. **Self-consistency**: Run experiments 5 times to measure reliability
6. **Opinionated handlers**: Create new handler classes for different approaches, don't add config toggles
7. **Document prompts**: Add XML comments explaining prompt design choices

## Troubleshooting

### Handler not found
```
KeyError: No handler with class name 'MyHandler' is registered
```
**Solution**: Import and register the handler in `experiments/compare_models/handlers/__init__.py`

### Prompt file not found
```
FileNotFoundError: [Errno 2] No such file or directory: 'paper_data_linking/linkers/general/prompts/...'
```
**Solution**: Check the `prompt` path in your YAML config is correct

### High parse failure rate
If `parse_response()` is returning `None` frequently:
- Check your prompt clarity
- Test with `max_cases: 5` first
- Consider simplifying the expected output format
- For free-text handlers, consider using a Pydantic schema instead

### NaN in Fleiss' Kappa
Occurs when too many cases have parse failures (fewer than 2 successful parses):
- Fix prompt/schema issues causing parse failures
- Ensure handler's `parse_response()` is robust

## Related Files

- `experiments/compare_models/core/experiment_config.py` - Pydantic config models
- `experiments/compare_models/core/handler.py` - Base handler class
- `experiments/compare_models/core/registry.py` - Handler registry
- `experiments/compare_models/run_parallel_experiment.py` - Parallel experiment runner
- `experiments/compare_models/run_prompt_experiment.py` - Single experiment runner
- `experiments/compare_models/handlers/` - Handler implementations

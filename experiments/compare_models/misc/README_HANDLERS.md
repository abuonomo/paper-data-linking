# LLM Call Type Handler System

## Overview

The handler system provides a **DRY**, **extensible** framework for experimenting with different LLM call types (validation, normalization, extraction, etc.) across multiple models and system prompts.

## Architecture

### Core Components

1. **`CallTypeHandler`** (`core/call_handlers.py`)
   - Abstract base class defining the interface for all handlers
   - Methods:
     - `get_call_type_name()`: Unique identifier
     - `get_response_format()`: Optional Pydantic schema for structured output
     - `parse_response(response)`: Extract structured data from LLM output
     - `compare_responses(resp1, resp2)`: Compare two parsed responses
     - `format_for_html(response)`: Format for HTML display

2. **`CallTypeRegistry`** (`core/registry.py`)
   - Centralized registry for managing handlers
   - Handlers auto-register on import
   - Retrieve handlers by call type name

3. **Handlers** (`handlers/`)
   - Each call type implements `CallTypeHandler`
   - Auto-registered via `handlers/__init__.py`
   - Currently implemented:
     - **InstrumentValidationHandler**: Binary valid/invalid decisions

### File Structure

```
experiments/compare_models/
├── core/
│   ├── call_handlers.py      # Abstract base class
│   ├── registry.py            # Registry for handlers
│   ├── client.py              # LLM client (existing)
│   └── schemas.py             # Pydantic schemas (existing)
├── handlers/
│   ├── __init__.py            # Auto-register all handlers
│   └── instrument_validation.py
├── run_prompt_experiment.py   # NEW: Handler-based version
├── run_prompt_experiment_old.py  # OLD: Preserved for reference
└── README_HANDLERS.md         # This file
```

## Usage

### Running Experiments

The new `run_prompt_experiment.py` requires a `--call-type` parameter:

```bash
# Instrument validation experiment
python experiments/compare_models/run_prompt_experiment.py \
  --call-type instrument_validation \
  --input inputs/instrument_validation_sample_20.jsonl \
  --system-prompt paper_data_linking/linkers/general/prompts/validation/system.xml \
  --models openai/gpt-5-nano openai/gpt-5-mini openai/gpt-5 \
  --experiment-name test_new_prompt

# List available call types
python -c "from experiments.compare_models.core.registry import CallTypeRegistry; import experiments.compare_models.handlers; print(CallTypeRegistry.list_call_types())"
```

### Output Format

Results are saved as JSONL with these fields:

```json
{
  "case_index": 1,
  "original_id": "...",
  "model_name": "openai/gpt-5-mini",
  "call_type": "instrument_validation",
  "created_at": "2025-10-08T...",
  "provider": "openai",
  "prompt_tokens": 1200,
  "completion_tokens": 150,
  "total_tokens": 1350,
  "estimated_cost_usd": 0.000135,
  "duration_ms": 1234,
  "input_messages": [...],
  "output_content": "...",
  "parsed_response": "valid",       # ← NEW: Handler-parsed result
  "system_prompt_path": "..."
}
```

## Adding New Handlers

### Example: Wavelength Normalization

1. **Create handler** (`handlers/wavelength_normalization.py`):

```python
from experiments.compare_models.core.call_handlers import CallTypeHandler, ComparisonResult
from paper_data_linking.linkers.general.normalizers.normalizer import NormalizedWavelength
from typing import Optional, Type
from pydantic import BaseModel

class WavelengthNormalizationHandler(CallTypeHandler):
    def get_call_type_name(self) -> str:
        return "wavelength_normalization"

    def get_response_format(self) -> Optional[Type[BaseModel]]:
        return NormalizedWavelength

    def parse_response(self, response: str) -> dict:
        # Pydantic JSON parsing
        obj = NormalizedWavelength.model_validate_json(response)
        return obj.model_dump()

    def compare_responses(self, resp1: dict, resp2: dict) -> ComparisonResult:
        # Compare values, unit, type
        agree = (
            resp1.get('values') == resp2.get('values') and
            resp1.get('unit') == resp2.get('unit') and
            resp1.get('type') == resp2.get('type')
        )
        return ComparisonResult(agree=agree, resp1=resp1, resp2=resp2)

    def format_for_html(self, response: dict, is_agreement: bool = True) -> str:
        return f"<pre>{json.dumps(response, indent=2)}</pre>"
```

2. **Register in `handlers/__init__.py`**:

```python
from experiments.compare_models.handlers.wavelength_normalization import WavelengthNormalizationHandler

CallTypeRegistry.register(WavelengthNormalizationHandler())
```

3. **Done!** Now you can run experiments:

```bash
python experiments/compare_models/run_prompt_experiment.py \
  --call-type wavelength_normalization \
  --input inputs/wavelength_test.jsonl \
  --system-prompt paper_data_linking/linkers/general/prompts/wavelength_normalization/system.xml \
  --models openai/gpt-5-mini \
  --experiment-name wavelength_baseline
```

## Benefits

1. **DRY**: Common logic (LLM calls, result storage) written once
2. **Extensible**: Add new call types by implementing one handler
3. **Type-safe**: Each handler defines its own types and parsing logic
4. **Flexible**: Complex comparison logic in code, not config
5. **Testable**: Each component independently tested
6. **Maintainable**: Clear separation of concerns

## Next Steps

### Phase 3: Additional Handlers
- [ ] `WavelengthNormalizationHandler`
- [ ] `PhysObsNormalizationHandler`
- [ ] `CadenceNormalizationHandler`
- [ ] `TimeNormalizationHandler`

### Phase 4: HTML Generation
- [ ] Generic comparison HTML generator
- [ ] Uses `format_for_html()` from handlers
- [ ] Handles arbitrary number of models
- [ ] Highlights disagreements automatically

### Phase 5: Analysis Tools
- [ ] Agreement metrics across models
- [ ] Ground truth comparison (accuracy)
- [ ] Cost analysis per call type
- [ ] Performance benchmarking

## Migration Notes

### Old Script

The old `run_prompt_experiment_old.py` is preserved for reference. It was hardcoded for instrument validation only.

### Breaking Changes

- **New required parameter**: `--call-type`
- **Output format**: Added `parsed_response` field
- **Error handling**: Parse errors stored separately from LLM errors

### Backward Compatibility

Existing analysis scripts that read output JSONL files will continue to work - they just have access to the new `parsed_response` field.

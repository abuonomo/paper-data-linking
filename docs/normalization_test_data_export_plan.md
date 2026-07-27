# Plan: Export Normalization Test Data from Production

## Situation

We've been testing LLM prompt improvements for normalization tasks (physobs, wavelength, time, etc.) and discovered a critical workflow issue:

**Current workflow:**
1. Export LLM calls from production using `export_llm_calls` command
2. Get fully-rendered prompts baked into `input_messages` field
3. To test new prompts → must parse old prompts to extract raw data (fragile!)
4. Can't easily get VSO metadata (candidate lists) without complex queries
5. Period matching between structured and normalized data is implicit

**Problem:**
- Can't iterate on prompts without re-exporting from production
- No access to raw inputs needed for template rendering
- Missing VSO metadata context (valid candidates for physobs/detector)
- Can't perform regression testing (new prompts vs. production outputs)

## Motivation

We want to:
1. **Test new prompts** on real production data without re-parsing old prompts
2. **Compare models** (nano, mini, gpt-5, bedrock) on identical test cases
3. **Regression test** - ensure new prompts don't degrade quality vs. production
4. **Track agreement** - measure consensus across models to identify ambiguous cases

**Key insight:** The data we need already exists in `PaperAnalysis.normalized_instrument_details` - we just need to extract it in a test-friendly format.

## Key Files

### Current Export System
- **`api/vso_query_builder/management/commands/export_llm_calls.py`** - Exports fully-rendered LLM calls (not suitable for testing new prompts)
- **`api/vso_query_builder/models.py`** - Contains `LLMCall`, `PaperAnalysis`, `DatasetUsage` models

### Normalization Pipeline
- **`paper_data_linking/linkers/general/structured_normalizer.py`** - Orchestrates normalization
- **`paper_data_linking/linkers/general/normalizers/physobs_normalizer.py`** - PhysObs normalization
- **`paper_data_linking/linkers/general/normalizers/wavelength_normalizer.py`** - Wavelength normalization
- **`paper_data_linking/linkers/general/normalizers/time_range_normalizer.py`** - Time normalization
- **`paper_data_linking/linkers/general/normalizers/detector_normalizer.py`** - Detector normalization
- **`paper_data_linking/linkers/general/normalizers/cadence_normalizer.py`** - Cadence normalization

### Testing Framework
- **`experiments/compare_models/run_prompt_experiment.py`** - Runs experiments across models
- **`experiments/compare_models/handlers/`** - Call type handlers (physobs, wavelength, etc.)
- **`experiments/compare_models/core/registry.py`** - Handler registry

## Data Structure in Production

### PaperAnalysis.structured_instrument_details
```json
{
  "instruments": [{
    "name": "Helioseismic and Magnetic Imager on SDO",
    "data_collection_periods": [{
      "period_name": "Active Region Study",
      "time_range": "January 2020 - March 2020",
      "wavelengths": "6173 Angstroms",
      "physical_observable": "vector magnetic field Bx By Bz"
    }]
  }]
}
```

### PaperAnalysis.normalized_instrument_details
```json
{
  "instruments": [{
    "name": {
      "original": "Helioseismic and Magnetic Imager on SDO",
      "normalized": {
        "matched_instrument_code": "HMI",
        "matched_mission_code": "SDO",
        "data_system": "vso"
      }
    },
    "data_collection_periods": [{
      "period_name": "Active Region Study",
      "time_range": {
        "original": "January 2020 - March 2020",
        "normalized": {
          "start_datetime": "2020-01-01T00:00:00Z",
          "end_datetime": "2020-03-31T23:59:59Z"
        }
      },
      "physical_observable": {
        "original": "vector magnetic field Bx By Bz",
        "normalized": {
          "physical_observable": "vector_magnetic_field"
        }
      }
    }]
  }]
}
```

## Proposed Solution

### Create New Export Command: `export_normalization_test_data`

**Purpose:** Extract raw inputs + normalized outputs + VSO metadata from production data in a format optimized for testing.

**Location:** `api/vso_query_builder/management/commands/export_normalization_test_data.py`

### Export Format (JSONL)

Each line represents a single normalization task:

```json
{
  "case_id": "uuid",
  "paper_bibcode": "2024ApJ...",
  "call_type": "physobs_normalization",

  "raw_inputs": {
    "raw_observable": "vector magnetic field Bx By Bz"
  },

  "canonical_instrument": {
    "id": "uuid-for-HMI",
    "code": "HMI",
    "full_name": "Helioseismic and Magnetic Imager",
    "observatory_code": "SDO",
    "datasource": "vso"
  },

  "vso_metadata": {
    "valid_physobs_candidates": ["LOS_magnetic_field", "vector_magnetic_field"]
  },

  "expected_output": {
    "physical_observable": "vector_magnetic_field"
  },

  "provenance": {
    "paper_analysis_id": "uuid",
    "instrument_index": 0,
    "period_index": 0,
    "configuration_name": "budget"
  }
}
```

### Command Features

```bash
# Export physobs test cases
python manage.py export_normalization_test_data \
  --call-type physobs_normalization \
  --config budget \
  --limit 100 \
  --output inputs/physobs_test_cases.jsonl

# Export all normalization types
python manage.py export_normalization_test_data \
  --call-type time_normalization \
  --call-type wavelength_normalization \
  --call-type physobs_normalization \
  --output inputs/all_normalizations.jsonl

# List available call types
python manage.py export_normalization_test_data --list-call-types
```

### Implementation Details

#### 1. Parse normalized_instrument_details JSON
```python
def extract_normalization_tasks(paper_analysis):
    """Extract all normalization tasks from a PaperAnalysis."""
    normalized = paper_analysis.normalized_instrument_details
    tasks = []

    for inst_idx, instrument in enumerate(normalized['instruments']):
        inst_code = instrument['name']['normalized']['matched_instrument_code']

        for period_idx, period in enumerate(instrument['data_collection_periods']):
            # Extract physobs normalization
            if 'physical_observable' in period:
                tasks.append({
                    'call_type': 'physobs_normalization',
                    'raw_inputs': {
                        'raw_observable': period['physical_observable']['original']
                    },
                    'canonical_instrument': get_instrument(inst_code),
                    'vso_metadata': get_vso_physobs_candidates(inst_code),
                    'expected_output': period['physical_observable']['normalized'],
                    'provenance': {
                        'paper_analysis_id': str(paper_analysis.id),
                        'instrument_index': inst_idx,
                        'period_index': period_idx
                    }
                })

            # Extract wavelength normalization
            if 'wavelengths' in period:
                # ... similar pattern

            # Extract time normalization
            if 'time_range' in period:
                # ... similar pattern

    return tasks
```

#### 2. Fetch VSO Metadata Fresh
```python
def get_vso_physobs_candidates(instrument_code):
    """Get valid physobs candidates from VSO metadata."""
    # Read from vso_metadata.jsonl (same as PhysObsNormalizer)
    candidates = []
    with open(VSO_METADATA_JSONL) as f:
        for line in f:
            entry = json.loads(line)
            if entry.get('instrument') == instrument_code:
                if entry.get('physobs'):
                    candidates.append(entry['physobs'])
    return sorted(set(candidates))
```

#### 3. Query Strategy
```python
# Get successful normalized paper analyses
paper_analyses = PaperAnalysis.objects.filter(
    status='completed',
    normalized_instrument_details__isnull=False
).select_related('paper')

# Filter by configuration if specified
if config:
    paper_analyses = paper_analyses.filter(configuration_name=config)

# Extract and export tasks
for pa in paper_analyses:
    tasks = extract_normalization_tasks(pa)
    for task in tasks:
        if task['call_type'] == requested_call_type:
            export_task(task, output_file)
```

### Test Runner Updates

Update `run_prompt_experiment.py` to handle new input format:

```python
def load_test_case(case_data):
    """Load test case and render with current prompt templates."""
    call_type = case_data['call_type']
    raw_inputs = case_data['raw_inputs']
    vso_metadata = case_data.get('vso_metadata', {})
    canonical_instrument = case_data['canonical_instrument']

    # Load current prompt templates
    system_msg, user_msg = load_and_render_prompt(
        call_type,
        instrument_code=canonical_instrument['code'],
        candidates=vso_metadata.get('valid_physobs_candidates', []),
        raw_observable=raw_inputs.get('raw_observable')
    )

    # Run model
    response = call_model(system_msg, user_msg, model)

    # Compare to expected output (regression check)
    expected = case_data.get('expected_output')
    matches_production = compare_outputs(response, expected)

    return {
        'model_output': response,
        'expected_output': expected,
        'matches_production': matches_production
    }
```

## Benefits

1. ✅ **No schema changes** - works with existing data
2. ✅ **Works immediately** - can export from current production
3. ✅ **Fresh VSO metadata** - fetched on-demand, no staleness
4. ✅ **Template-agnostic** - test ANY prompt template on same data
5. ✅ **Regression testing** - compare new prompts to production baseline
6. ✅ **Model comparison** - run same test cases across models
7. ✅ **Full provenance** - trace back to source paper + period

## Limitations

1. ⚠️ **JSON parsing** - assumes stable structure of normalized_instrument_details
2. ⚠️ **Period matching by index** - relies on consistent ordering
3. ⚠️ **No LLMCall linkage** - can't trace back to original LLM call easily
4. ⚠️ **Only works for normalized data** - doesn't help with legacy_llm workflow

## Future Enhancements (If Needed)

If export proves too fragile or complex:
- **Option 2:** Enhance `LLMCall` model to store structured inputs/context at creation time
  - Add `structured_inputs` and `render_context` fields
  - Update normalizers to pass raw data when calling LLM
  - Enables richer querying and avoids JSON parsing

## Success Criteria

1. ✅ Can export 100+ test cases per normalization type
2. ✅ Each test case contains raw inputs + VSO metadata + expected output
3. ✅ Test runner can load cases and test with ANY prompt template
4. ✅ Can measure both model agreement AND regression vs. production
5. ✅ Export command runs in <30 seconds for 1000 cases

## Next Steps

1. Implement `export_normalization_test_data` management command
2. Test export on small sample (10 papers)
3. Validate exported format with test runner
4. Export full test sets for each normalization type
5. Re-run wavelength/physobs experiments with new data format
6. Document export process for future use

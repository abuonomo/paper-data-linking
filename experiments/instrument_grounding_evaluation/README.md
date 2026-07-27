# Instrument Grounding Evaluation

This experiment evaluates the accuracy of the `InstrumentGrounder` component in matching textual instrument descriptions to the VSO (Virtual Solar Observatory) catalog.

## Overview

The InstrumentGrounder uses a two-stage process:
1. **Embedding Search**: Uses OpenAI embeddings and pgvector similarity search to find candidate instruments
2. **LLM Grounding**: Uses GPT-4 to analyze context and select the most appropriate match

This evaluation tests how well this process works across various realistic scenarios.

## Files

- `test_cases.jsonl` - Test cases in JSON Lines format
- `evaluate_grounding_accuracy.py` - Main evaluation script
- `README.md` - This documentation

## Test Categories

### Exact Matches
Clear cases where the instrument should be definitively identified:
- LASCO with full name and context
- AIA with wavelength specifications  
- HMI with characteristic 6173 Å line
- EIT with historical context

### Abbreviations
Testing various name format variations:
- Simple abbreviations (e.g., "LASCO")
- Mission/instrument format (e.g., "SOHO/LASCO")
- Case sensitivity handling

### Contextual Clues
Generic instrument names requiring context inference:
- "Magnetograph" + SDO context → should identify HMI
- "EUV telescope" + SDO + wavelengths → should identify AIA

### Ambiguous Cases
Cases that are too generic and should not match:
- "Coronagraph" without mission context
- "EUV Imaging Telescope" without specifics
- "Magnetometer" (too many possibilities)

### Non-VSO Instruments
Instruments not in the space-based VSO catalog:
- Ground-based telescopes
- Laboratory experiments
- Theoretical model outputs

### Similar Instruments
Testing discrimination between similar instruments:
- STEREO/SECCHI vs SOHO/LASCO (both coronagraphs)
- Different EUV telescopes (AIA vs EIT)

### WIND Mission
Less common heliophysics instruments:
- MFI (Magnetic Field Investigation)
- 3DP (3D Plasma and Energetic Particle Investigation)

### Edge Cases
Unusual inputs to test robustness:
- Mixed case text
- Redundant descriptions
- Typos and variations

## Usage

### Basic Evaluation
```bash
cd experiments/instrument_grounding_evaluation
python evaluate_grounding_accuracy.py
```

### Filter by Category
```bash
# Test only exact matches
python evaluate_grounding_accuracy.py --category exact_match

# Test contextual inference
python evaluate_grounding_accuracy.py --category contextual

# Test ambiguous cases
python evaluate_grounding_accuracy.py --category ambiguous
```

### Limit Test Cases
```bash
# Run only first 5 test cases
python evaluate_grounding_accuracy.py --limit 5

# Run first 3 exact match cases
python evaluate_grounding_accuracy.py --category exact_match --limit 3
```

### Detailed Output
```bash
# Verbose output with details for each case
python evaluate_grounding_accuracy.py --verbose

# Save results to JSON file
python evaluate_grounding_accuracy.py --save-results results.json

# Both verbose and save results
python evaluate_grounding_accuracy.py --verbose --save-results detailed_results.json
```

### Dry Run
```bash
# Test configuration without running evaluation
python evaluate_grounding_accuracy.py --dry-run
```

### Custom API Key
```bash
# Use specific OpenAI API key
python evaluate_grounding_accuracy.py --api-key your_key_here
```

## Expected Performance

### Accuracy Targets
- **Exact Matches**: >95% - Clear cases should work reliably
- **Contextual**: >80% - Context clues should usually work
- **Abbreviations**: >90% - Common abbreviations should be recognized
- **Ambiguous**: >90% correct rejection - Should not match ambiguous cases
- **Non-VSO**: >95% correct rejection - Should not match non-space instruments

### Overall Target
- **Overall Accuracy**: >85% across all categories
- **Performance**: <5 seconds average per instrument
- **Error Rate**: <5% (API failures, timeouts, etc.)

## Interpreting Results

### Output Format
```
[01/20] lasco_exact_match
  ✅ Correct match: LASCO/SOHO (2.34s)

[02/20] ambiguous_coronagraph  
  ✅ Correctly identified as no match (1.87s)

[03/20] hmi_from_context
  ❌ Wrong instrument: expected HMI, got AIA (3.12s)
```

### Summary Report
```
INSTRUMENT GROUNDING EVALUATION RESULTS
========================================
Overall Performance:
  Total test cases: 20
  Correct: 17 (85.0%)
  Incorrect: 2
  Errors: 1 (5.0%)

Timing:
  Total time: 45.67s
  Average per case: 2.28s
  Throughput: 0.4 cases/second

By Category:
  exact_match         :  4/ 4 correct (100.0%)
  contextual          :  2/ 3 correct ( 66.7%)
  abbreviation        :  2/ 2 correct (100.0%)
  ambiguous           :  3/ 3 correct (100.0%)
  non_vso             :  3/ 3 correct (100.0%)
```

## Adding New Test Cases

Add new test cases to `test_cases.jsonl` in JSON Lines format:

```json
{
  "name": "unique_test_name",
  "category": "category_name", 
  "instrument_entry": {
    "name": "Instrument Name",
    "general_comments": "Description and context",
    "data_collection_periods": [
      {
        "time_range": "2010-2020",
        "wavelengths": "spectral info", 
        "physical_observable": "what it measures"
      }
    ]
  },
  "expected": {
    "should_match": true,
    "instrument_code": "INSTR",
    "mission_code": "MISSION"
  },
  "description": "Human-readable description of test case"
}
```

### Required Fields
- `name`: Unique identifier for the test case
- `category`: Category for grouping and filtering
- `instrument_entry`: Input to the grounder (must have `name` field)
- `expected`: Expected outcome with `should_match` boolean

### Optional Fields  
- `description`: Human-readable explanation
- `expected.instrument_code`: Expected instrument code (if should_match=true)
- `expected.mission_code`: Expected mission code (if should_match=true)

## Troubleshooting

### Django Setup Issues
```bash
# Ensure you're in the project root
cd /path/to/paper-data-linking

# Activate virtual environment
source .venv/bin/activate

# Check Django can import
python -c "import django; django.setup(); print('Django OK')"
```

### Missing API Key
```bash
# Set environment variable
export OPENAI_API_KEY=your_key_here

# Or pass via command line
python evaluate_grounding_accuracy.py --api-key your_key_here
```

### Database Connection Issues
The evaluation requires access to the VSO instrument database. Ensure:
- PostgreSQL is running
- Database migrations are applied
- VSO instrument data is loaded

### Performance Issues
If evaluation is slow:
- Use `--limit` to test smaller subsets
- Use `--category` to focus on specific areas
- Check network connection for OpenAI API calls
- Monitor token usage costs

## Analysis and Improvement

### Common Failure Patterns
1. **Context Insufficient**: Generic names without enough disambiguating context
2. **Embedding Similarity**: Top candidates don't include the correct instrument
3. **LLM Reasoning**: Model chooses wrong candidate despite correct one being present
4. **Edge Cases**: Unusual formatting or naming conventions

### Improvement Strategies
1. **Enhance Embeddings**: Improve instrument descriptions in database
2. **Better Prompts**: Refine LLM instructions for better reasoning
3. **Context Enrichment**: Add more contextual clues to instrument entries
4. **Confidence Tuning**: Adjust confidence thresholds for matching

### Monitoring Over Time
Run evaluations regularly to:
- Track performance changes after system updates
- Identify degradation in accuracy
- Validate improvements from code changes
- Monitor API cost and performance trends
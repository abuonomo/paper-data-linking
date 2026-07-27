# Instrument Grounding Evaluation System

This directory contains a comprehensive evaluation system for testing the accuracy and reliability of the InstrumentGrounder system used for matching instrument descriptions to the VSO catalog.

## Overview

The InstrumentGrounder system has evolved from basic testing to a sophisticated hierarchical pipeline with multi-target support and post-validation filtering. This evaluation framework provides systematic testing across various realistic scenarios.

## Key Accomplishments

### 1. Multi-Target Support Implementation
- **Problem**: Ambiguous references like "STEREO spacecraft" could legitimately refer to both STEREO-A and STEREO-B
- **Solution**: Implemented multi-target support returning `List[Dict]` for ambiguous cases vs single `Dict` for unambiguous matches
- **Impact**: System can now handle legitimate ambiguity by returning all valid matches

### 2. Hierarchical Grounding Pipeline
- **Architecture**: Mission identification → mission selection → catalog filtering → instrument selection
- **Benefits**: Systematic approach with indexed selection using numbered lists (1-based for LLMs, 0-based for Python)
- **Robustness**: Handles both single-target and multi-target scenarios effectively

### 3. Post-Validation Filtering
- **Motivation**: Discrimination is easier than generation for LLMs
- **Implementation**: Added `_validate_grounding_result()` method that asks LLM to validate if proposed match makes sense
- **Results**: Dramatic accuracy improvement from 58.3% to 75.0%

### 4. Comprehensive Test Data Generation
- **Real Data Foundation**: Created test cases from actual `PaperAnalysis.structured_instrument_details` from database
- **Catalog-Based Synthesis**: Script generates test cases using real instrument entries from merged catalog
- **Realistic Scenarios**: Covers single spacecraft, multi-spacecraft ambiguity, acronym challenges, and generic references

## Files Structure

```
experiments/instrument_grounding_evaluation/
├── INSTRUMENT_GROUNDING_EVALUATION_SUMMARY.md   # This file
├── evaluate_grounding_accuracy.py               # Main evaluation script
├── synthesize_test_data.py                      # Test data generation script
├── comprehensive_instrument_grounding_test_set.jsonl  # Real database examples
├── synthesized_instrument_test_cases.jsonl     # Generated test cases
├── synthesized_evaluation_results.json         # Pre-validation results (58.3% accuracy)
├── validation_test_results.json                # Post-validation results (75.0% accuracy)
└── post_validation_evaluation_results.json     # Full validation results (75.0% accuracy)
```

## Performance Results

### Before Validation (58.3% accuracy)
- **Systematic Errors**: XRI → FOXSI confusion, GOES-13 SEM → GOES-12 SXI mismatches
- **False Positives**: Generic SEM → inappropriate SUVI matches
- **Issue**: System was generating plausible but incorrect matches

### After Validation (75.0% accuracy)
- **Improvement**: 16.7 percentage point increase in accuracy
- **Conservative Behavior**: System now rejects questionable matches rather than guessing incorrectly
- **Validated Rejections**: 
  - Case #2: XRI acronym challenge → correctly rejected ambiguous match
  - Case #9: GOES-13 SEM component → correctly rejected GOES-12 SXI mismatch  
  - Case #12: SEM acronym → correctly rejected inappropriate SUVI match

## Key Insights

1. **Validation Prevents Systematic Errors**: The post-validation filter successfully catches common confusion patterns
2. **Conservative is Better**: Getting "no match" is preferable to getting wrong instrument matches
3. **Multi-Target Support Works**: System correctly handles legitimate ambiguity (e.g., BARREL XRI returning 10 valid matches)
4. **Real Data Matters**: Using actual structured instrument details from the database creates more realistic test scenarios

## Technical Implementation

### Multi-Target Return Format
```python
# Single unambiguous match
{
    "matched_instrument_code": "spase://SMWG/Instrument/GOES/13/SEM",
    "matched_mission_code": "spase://SMWG/Observatory/GOES/13",
    "matched_instrument_name": "SEM",
    "matched_mission_name": "GOES-13",
    "reasoning": "Systematic selection: GOES-13 → SEM"
}

# Multiple ambiguous matches
[
    {
        "matched_instrument_code": "spase://SMWG/Instrument/BARREL/1A/XRI",
        "matched_mission_code": "spase://SMWG/Observatory/BARREL/1A",
        "matched_instrument_name": "XRI",
        "matched_mission_name": "BARREL",
        "reasoning": "Ambiguous reference - valid match 1/10"
    },
    # ... 9 more BARREL XRI variants
]
```

### Validation Process
```python
def _validate_grounding_result(self, instrument_entry: dict, grounding_result: dict) -> dict:
    """Post-validation filter: Ask LLM if the grounding result makes sense"""
    # Skip validation if no match was found
    if not grounding_result.get("matched_instrument_code"):
        return grounding_result
    
    # Ask LLM to validate the match
    validation_prompt = f"""
    ORIGINAL DESCRIPTION: {original_name} - {original_comments}
    PROPOSED MATCH: {proposed_instrument} on {proposed_mission}
    Answer with VALID or INVALID followed by brief reasoning.
    """
    
    # Return None if validation fails, otherwise return original result
```

## Usage

### Running Evaluation
```bash
# Run full evaluation with validation
python evaluate_grounding_accuracy.py --test-cases synthesized_instrument_test_cases.jsonl --save-results results.json

# Run with verbose output for debugging
python evaluate_grounding_accuracy.py --test-cases synthesized_instrument_test_cases.jsonl --verbose

# Run specific category
python evaluate_grounding_accuracy.py --test-cases synthesized_instrument_test_cases.jsonl --category acronym_challenge
```

### Generating Test Data
```bash
# Generate test cases for specific mission
python synthesize_test_data.py --mission-code GOES --num-batches 3 --cases-per-batch 4

# Generate general test cases
python synthesize_test_data.py --num-batches 2 --cases-per-batch 6
```

## Future Enhancements

1. **Fallback Strategy**: When validation rejects a match, try next best candidate rather than returning None
2. **Confidence Scoring**: Add confidence scores to matches to help with threshold tuning
3. **Category-Specific Validation**: Tailor validation prompts based on ambiguity type
4. **Temporal Context**: Incorporate time range information for better mission disambiguation

## Conclusion

The InstrumentGrounder evaluation system demonstrates significant improvement through systematic testing and validation. The 75% accuracy with conservative behavior represents a substantial advancement over the previous 58.3% accuracy with systematic errors. The system now reliably handles multi-target scenarios and prevents false positive matches, making it suitable for production use in the paper data linking pipeline.
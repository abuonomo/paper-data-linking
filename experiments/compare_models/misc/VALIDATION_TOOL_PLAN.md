# Manual Structure Validation Tool - Design Plan

## Overview

Create an interactive HTML validation tool for `structure_analysis` outputs that allows manual assessment of semantic equivalence between model responses.

This tool addresses the challenge of validating complex nested JSON structures where automated comparison (exact name matching) doesn't capture semantic equivalence. For example, two models might extract the same instruments with slightly different names or period groupings that are functionally equivalent.

## Motivation

From testing structure_analysis with nano vs mini:
- **Case 1**: Nano found 1/7 instruments (clear failure)
- **Case 2**: Nano found 3/3, mini found 3/3, but 0% agreement on exact names
- **Case 3**: Similar pattern

The question: Are disagreements due to semantic differences or just formatting/naming variations?

**Key Finding**: Nano used 5.93 tokens/char for failed Case 1 vs 1.1-1.3 for successful cases (mini uses 0.3-0.5 consistently), suggesting structured output validation is doing heavy correction work.

## Tool Requirements

### Primary Use Case
Manually review structure_analysis disagreements to determine if models are producing semantically equivalent results despite superficial differences.

### Layout Design

#### Top Section: Original Input
- Display the markdown `instruments_details_text` that was sent to both models
- Syntax highlighting for markdown
- Collapsible section to save space
- Shows what the models were asked to parse

#### Middle Section: Side-by-Side Comparison
Two columns (Model A | Model B) with:

**Instrument-Level View:**
- Each instrument as an expandable/collapsible card
- Visual indicators:
  - ✓ Green border: Instrument found in both models (exact name match)
  - ⚠️ Yellow border: Potential fuzzy match (similar name in other model)
  - ✗ Red border: Missing in other model

**Instrument Card Contents:**
```
┌─────────────────────────────────────────┐
│ Instrument Name                         │
│ ─────────────────────────────────────── │
│ Role: [role text]                       │
│ Mission: [mission_name]                 │
│ Data Collection Periods: X              │
│   ├─ Period 1: [time_range]            │
│   │   Observable: [physical_obs]       │
│   │   Wavelength: [wavelength]         │
│   └─ Period 2: [time_range]            │
│       Observable: [physical_obs]       │
│       Wavelength: [wavelength]         │
│ Supporting Quotes: [show count]         │
│   [collapsible quote list]             │
└─────────────────────────────────────────┘
```

**Summary Metrics (above cards):**
- Total instruments: X vs Y
- Total periods: X vs Y
- Jaccard similarity: X%
- Overlapping instruments: X
- Model-specific instruments: X (Model A), Y (Model B)

**Raw JSON View:**
- Tabbed interface: "Structured View" | "Raw JSON"
- Pretty-printed JSON with syntax highlighting
- Copy button for each model's output

#### Bottom Section: Validation Controls

**Judgment Radio Buttons:**
- ○ Semantically Equivalent (models extracted same information, just formatted differently)
- ○ Semantically Different (models extracted different information or made different decisions)
- ○ One Model Failed (one clearly missed instruments or made errors)
- ○ Skip/Unclear (need more context or expertise)

**Notes Field:**
- Free-form text area for validation notes
- Suggested format:
  - "Mini missed X instrument that nano found"
  - "Different period groupings but same time coverage"
  - "Nano used abbreviation, mini used full name"

**Navigation:**
- ← Previous Case | Next Case →
- Case counter: "Case 3 of 98"
- Jump to case: [dropdown]
- Progress: "Validated: 15/98 (15%)"

**Auto-Save:**
- Save validation judgment + notes to JSON after each action
- Visual confirmation: "✓ Saved" toast notification

## Technical Implementation

### File Structure

```
experiments/compare_models/
├── validate_structure_analysis.py    # Main script to generate validation tool
├── validation_results/               # Output directory for validation sessions
│   ├── nano_vs_mini_20250129.json   # Validation results
│   └── nano_vs_mini_20250129.html   # Interactive validation tool
└── VALIDATION_TOOL_PLAN.md          # This file
```

### Script: `validate_structure_analysis.py`

**Command-line interface:**
```bash
python experiments/compare_models/validate_structure_analysis.py \
  --model1 experiments/.../nano_results.jsonl \
  --model2 experiments/.../mini_results.jsonl \
  --output validation_tool.html \
  --resume validation_results.json  # Optional: load existing progress
```

**Key Functions:**

1. **`load_experiment_results(jsonl_path)`**
   - Parse JSONL experiment results
   - Extract: case_index, input_messages, output_content, parsed_response
   - Return dict keyed by case_index

2. **`extract_original_input(result)`**
   - Get user message from input_messages
   - Extract instruments_details_text from XML wrapper
   - Return markdown text

3. **`parse_instrument_structure(output_content)`**
   - Parse JSON from model output
   - Extract instruments list with all nested fields
   - Return structured dict

4. **`find_fuzzy_matches(inst_name, other_instruments)`**
   - Check for similar instrument names in other model
   - Use simple string similarity (Levenshtein distance or fuzzy ratio)
   - Return list of potential matches with confidence scores

5. **`generate_html_tool(model1_results, model2_results, output_path, existing_validations=None)`**
   - Generate self-contained HTML file
   - Embed all data as JavaScript
   - Include CSS for layout
   - Include JavaScript for interactivity

### HTML/JavaScript Structure

**Embedded Data Format:**
```javascript
const CASES = [
  {
    case_index: 1,
    original_input: "markdown text...",
    model1: {
      name: "nano",
      instruments: [...],
      raw_json: "..."
    },
    model2: {
      name: "mini",
      instruments: [...],
      raw_json: "..."
    }
  },
  // ... more cases
];

// Load existing validations if resuming
const EXISTING_VALIDATIONS = {
  "1": {judgment: "equivalent", notes: "...", timestamp: "..."},
  // ...
};
```

**JavaScript Functions:**
```javascript
// Core navigation
function loadCase(caseIndex)
function nextCase()
function prevCase()
function jumpToCase(caseIndex)

// Rendering
function renderOriginalInput(text)
function renderInstrumentComparison(model1Insts, model2Insts)
function renderInstrumentCard(instrument, matchStatus)
function toggleInstrumentDetails(instrumentId)

// Validation
function saveValidation(caseIndex, judgment, notes)
function exportValidations()  // Download validation_results.json
function getValidationProgress()

// Utilities
function findFuzzyMatches(instName, otherInstruments)
function calculateJaccard(set1, set2)
function prettifyJSON(jsonString)
```

### Validation Results Format

**File: `validation_results.json`**
```json
{
  "metadata": {
    "created_at": "2025-10-29T15:30:00",
    "model1_file": "experiments/.../nano_results.jsonl",
    "model2_file": "experiments/.../mini_results.jsonl",
    "model1_name": "gpt-5-nano",
    "model2_name": "gpt-5-mini",
    "total_cases": 98,
    "validated_count": 15
  },
  "validations": {
    "1": {
      "judgment": "one_failed",
      "notes": "Nano only found 1/7 instruments. Clear failure case.",
      "timestamp": "2025-10-29T15:31:22",
      "validator": "user"
    },
    "2": {
      "judgment": "equivalent",
      "notes": "Different formatting but same instruments extracted",
      "timestamp": "2025-10-29T15:32:10",
      "validator": "user"
    }
  },
  "summary": {
    "equivalent": 8,
    "different": 3,
    "one_failed": 2,
    "skip": 2,
    "not_validated": 83
  }
}
```

## CSS Styling

Reuse patterns from existing HTML generators:
- `generate_disagreement_html.py` - card layouts, responsive grid
- `wavelength_disagreements_3models.html` - color coding, copy buttons

**Color Scheme:**
- Exact match: `#27ae60` (green)
- Fuzzy match: `#f39c12` (orange/yellow)
- Missing: `#e74c3c` (red)
- Neutral background: `#f9f9f9`

**Layout:**
- Use CSS Grid for side-by-side comparison
- Max width: 1800px
- Responsive: stack vertically on smaller screens
- Sticky header with case navigation

## Future Enhancements

1. **Diff Highlighting**
   - Character-level diff for instrument names
   - Period-by-period alignment and comparison

2. **Fuzzy Matching Suggestions**
   - Auto-suggest potential name matches
   - "These might be the same: 'SDO/AIA' vs 'AIA (SDO)'"

3. **Multi-Model Support**
   - Compare 3+ models simultaneously
   - Majority vote highlighting

4. **Export Analysis**
   - Generate summary report from validation results
   - "Agreement rate: 85% (semantic) vs 30% (exact match)"
   - Common patterns of disagreement

5. **Pre-validation Filtering**
   - Only show cases with disagreements
   - Filter by specific metrics (e.g., Jaccard < 0.8)

6. **Keyboard Shortcuts**
   - E = Equivalent, D = Different, F = Failed, S = Skip
   - Arrow keys for navigation

## Usage Workflow

1. **Run experiment** with two models:
   ```bash
   python run_prompt_experiment.py \
     --call-type structure_analysis \
     --input inputs/structure_analysis_test_98.jsonl \
     --models openai/gpt-5-nano openai/gpt-5-mini \
     --experiment-name nano_vs_mini_validation
   ```

2. **Generate validation tool**:
   ```bash
   python validate_structure_analysis.py \
     --model1 experiments/.../nano_results.jsonl \
     --model2 experiments/.../mini_results.jsonl \
     --output validation_results/nano_vs_mini.html
   ```

3. **Open HTML in browser** and manually review each case:
   - Read original markdown input
   - Compare instrument extraction side-by-side
   - Make judgment: equivalent/different/failed/skip
   - Add notes explaining reasoning
   - Navigate through all cases

4. **Export results**:
   - Click "Export Validations" button in tool
   - Downloads `validation_results.json`
   - Save to version control for reproducibility

5. **Analyze results**:
   ```bash
   python analyze_validation_results.py \
     --validations validation_results/nano_vs_mini.json
   ```
   Output:
   - Semantic agreement rate vs exact match rate
   - Common disagreement patterns
   - Cases where human validation differs from automated comparison

## Benefits

1. **Accurate Assessment**: Distinguish real model differences from formatting variations
2. **Reproducible**: Validation judgments saved to JSON for sharing/review
3. **Efficient**: Interactive tool faster than manual JSON inspection
4. **Insightful**: Identify systematic patterns in model behavior
5. **Reusable**: Same tool works for any structure_analysis comparison

## Example Use Cases

### Use Case 1: Model Selection
**Question**: Should we use nano or mini for structure_analysis in production?

**Process**:
1. Run both on 98-case test set
2. Use validation tool to assess semantic equivalence
3. Calculate: nano semantic accuracy, mini semantic accuracy
4. Decision: If nano 95% vs mini 98% semantic accuracy, but nano 3x cheaper → use nano

### Use Case 2: Prompt Optimization
**Question**: Does modified system prompt improve extraction quality?

**Process**:
1. Run mini with baseline prompt → 98 results
2. Run mini with modified prompt → 98 results
3. Use validation tool to compare same model, different prompts
4. Find cases where modified prompt extracted more/better information

### Use Case 3: Error Analysis
**Question**: What types of instrument descriptions cause failures?

**Process**:
1. Validate nano vs mini on 98 cases
2. Filter validations to "one_failed" or "different" judgments
3. Analyze patterns in original markdown for failed cases
4. Common issues: abbreviations, multiple missions, partial descriptions

## Implementation Priority

**Phase 1 (MVP):**
- [x] Basic HTML generation with side-by-side comparison
- [x] Instrument card view with summary metrics
- [x] Manual validation radio buttons + notes
- [x] Save/load validation results JSON
- [x] Case navigation (prev/next)

**Phase 2 (Enhanced):**
- [ ] Fuzzy matching suggestions
- [ ] Raw JSON view toggle
- [ ] Copy buttons for outputs
- [ ] Progress tracking visualization
- [ ] Jump to case dropdown

**Phase 3 (Advanced):**
- [ ] Keyboard shortcuts
- [ ] Diff highlighting
- [ ] Multi-model (3+) comparison
- [ ] Export analysis report
- [ ] Pre-validation filtering

## Related Files

- `experiments/compare_models/run_prompt_experiment.py` - Generates JSONL results to validate
- `experiments/compare_models/handlers/structure_analysis.py` - Handler with `format_for_html()` method
- `experiments/compare_models/generate_disagreement_html.py` - Reference for HTML generation patterns
- `experiments/compare_models/analyze_experiment_results.ipynb` - Automated analysis notebook
- `paper_data_linking/linkers/general/schemas/structured_instruments.py` - Pydantic schema defining structure

## Token Efficiency Investigation Results

From initial 3-case test (nano vs mini):

**Nano Token Efficiency:**
- Case 1: 5.93 tok/char (FAILURE - 1/7 instruments)
- Case 2: 1.27 tok/char (SUCCESS - 3/3 instruments)
- Case 3: 1.11 tok/char (SUCCESS - 8/8 instruments)

**Mini Token Efficiency (all successful):**
- Case 1: 0.32 tok/char (7/7 instruments)
- Case 2: 0.48 tok/char (3/3 instruments)
- Case 3: 0.30 tok/char (8/8 instruments)

**Conclusion**: When nano struggles (Case 1), OpenAI's structured output validation performs massive internal correction (18x worse token efficiency than mini). This is a model quality issue, not a prompt issue. The validation tool will help identify how often this occurs in the full test set.

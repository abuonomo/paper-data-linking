# Debug Analysis Instructions for ISS Grounding Failure

## Objective
Analyze the `generic_iss_mention` test case failure to understand why the system incorrectly matched "ISS" to International Space Station instruments instead of recognizing it as too ambiguous.

## Setup

1. **Navigate to the correct directory:**
   ```bash
   cd /Users/abuonomo/code/nasa/paper-data-linking/experiments/instrument_grounding_evaluation
   ```

2. **Activate the virtual environment:**
   ```bash
   source /Users/abuonomo/code/nasa/paper-data-linking/.venv/bin/activate
   ```

3. **The debug test case is already created:** `debug_iss_case.jsonl`

## Run Debug Analysis

Execute the evaluation with full verbose output to see every step:

```bash
python evaluate_grounding_accuracy.py --test-cases debug_iss_case.jsonl --verbose
```

## What to Look For

### 1. Mission Identification Stage
- **Input**: "ISS" with generic solar data context
- **Expected Problem**: Should the LLM identify multiple possible missions for "ISS"?
- **Key Questions**:
  - Does it correctly identify both "International Space Station" and "Synoptic Optical Long-term Investigations of the Sun" (SOLIS)?
  - What are the top 10 candidate missions returned?

### 2. Mission Selection Stage  
- **Critical Decision Point**: When presented with candidate missions, does the LLM choose:
  - International Space Station (incorrect for solar context)
  - SOLIS (correct for solar context) 
  - Return '0' for ambiguous (most appropriate)
- **Key Question**: Why doesn't the solar context clue ("solar data", "General solar activity") guide it to SOLIS?

### 3. Multi-Target Detection
- **Expected Behavior**: The system should either:
  - Recognize ambiguity and return no match
  - Return multiple possible matches if truly ambiguous
- **Key Question**: Why does it settle on International Space Station instruments?

### 4. Validation Stage
- **Critical Failure**: Validation approved 3 ISS matches that should have been rejected
- **Key Questions**:
  - What was the validation prompt for each match?
  - Why did the LLM think AMS-02, TEPC, and FPMU are valid for "solar data collection"?
  - Should the validation prompt emphasize scientific context matching?

## Expected Debug Output Sections

Look for these log sections in the verbose output:

1. **`=== INPUT INSTRUMENT ENTRY ===`**
2. **`=== MISSION IDENTIFICATION (INDEXED) ===`** 
3. **`=== OPENAI REQUEST ===` (mission identification)**
4. **`=== OPENAI RESPONSE (CHAT) ===` (candidate missions)**
5. **`=== FINAL MISSION SELECTION ===`**
6. **`=== OPENAI REQUEST ===` (mission selection)**
7. **`=== OPENAI RESPONSE (CHAT) ===` (final mission choice)**
8. **`=== MISSION FILTERING ===`**
9. **`=== FINAL INSTRUMENT SELECTION ===`**
10. **`=== VALIDATION ===` (for each match found)**

## Analysis Questions

After reviewing the debug output, answer:

1. **Mission Identification**: What were the top 10 candidate missions? Did it include SOLIS?

2. **Mission Selection**: When choosing between candidates, what reasoning led to International Space Station over SOLIS or ambiguity?

3. **Context Clues**: How did the system interpret "solar data" and "General solar activity" - did this influence mission selection?

4. **Validation Logic**: For each of the 3 ISS matches (AMS-02, TEPC, FPMU):
   - What was the validation prompt?
   - What was the LLM's reasoning for marking them VALID?
   - Are these instruments actually capable of "solar data collection"?

5. **Multi-Target Behavior**: Why did the system return multiple matches instead of recognizing this as too ambiguous?

## Potential Issues to Investigate

1. **Acronym Handling**: Is "ISS" inherently too ambiguous and should trigger special handling?

2. **Context Weight**: Are the solar-related context clues being properly weighted in mission selection?

3. **Validation Scope**: Is the validation prompt too narrow - focusing only on instrument name matching rather than scientific context appropriateness?

4. **Mission Priority**: Is International Space Station being prioritized over ground-based solar observatories in the mission list ordering?

## Next Steps After Analysis

Based on the debug findings, consider:

1. **Improved Context Weighting**: Enhance mission selection to better use scientific context clues
2. **Enhanced Validation**: Improve validation prompts to check scientific context appropriateness  
3. **Acronym Disambiguation**: Add special handling for highly ambiguous acronyms like "ISS"
4. **Mission Ordering**: Ensure mission candidates are presented in contextually relevant order

## Expected Outcome

This analysis should reveal exactly where in the hierarchical grounding pipeline the incorrect decision was made, allowing for targeted improvements to prevent similar failures.
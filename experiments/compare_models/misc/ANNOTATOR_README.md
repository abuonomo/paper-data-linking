# Disagreement Annotator

Interactive Streamlit app for annotating model disagreements between GPT-5 and GPT-5-mini.

## Quick Start

```bash
# From project root
streamlit run experiments/compare_models/disagreement_annotator.py
```

The app will open in your browser at `http://localhost:8501`

## Features

### 📊 Statistics Dashboard (Sidebar)
- Total disagreements across all call types
- Annotation progress tracker
- Filter by call type
- Filter by annotation status (all/annotated/unannotated)
- Export annotations to CSV

### 🔍 Disagreement Viewer
- Side-by-side comparison of GPT-5 vs GPT-5-mini outputs
- Shows parsed responses, raw outputs, token counts, costs
- Displays handler comparison details
- Full input context (collapsible)

### 📝 Annotation Interface
- **Category**: Classify disagreement type
  - `prompt_ambiguity`: Prompt allows multiple valid interpretations
  - `scientific_ambiguity`: Scientifically ambiguous case (e.g., LET vs SIT)
  - `formatting_error`: JSON/output formatting issue
  - `model_capability_difference`: Genuine model reasoning difference
  - `context_insufficient`: Not enough info to determine correct answer
  - `genuine_error`: Clear error by one or both models
  - `other`: Other cases

- **Correctness**: Who got it right?
  - `gpt5_correct`: GPT-5 is correct
  - `mini_correct`: GPT-5-mini is correct
  - `both_correct_different_interpretation`: Both valid given ambiguity
  - `both_wrong`: Neither is correct
  - `ambiguous_cannot_decide`: Cannot determine correctness
  - `need_more_context`: Need additional information

- **Comment**: Free-form notes
- **Tags**: Comma-separated tags (e.g., "LASCO, null_inference, conservative")

### ⌨️ Keyboard Navigation
- Previous/Next buttons
- Jump to specific case number
- Auto-advance after saving annotation

### 💾 Data Persistence
- Annotations saved to `experiments/compare_models/disagreement_annotations.jsonl`
- Can re-open app and continue where you left off
- Export to CSV at any time

## Example Workflow

1. Start app: `streamlit run experiments/compare_models/disagreement_annotator.py`
2. Review first disagreement
3. Classify it (e.g., "prompt_ambiguity" + "both_correct_different_interpretation")
4. Add comment explaining the issue
5. Add tags for easy filtering later
6. Click "Save Annotation" (auto-advances to next)
7. Repeat for all disagreements
8. Export CSV for analysis

## Output Format

Annotations are saved in JSONL format:

```json
{
  "disagreement_id": "detector_normalization_13",
  "category": "prompt_ambiguity",
  "correctness": "both_correct_different_interpretation",
  "comment": "LASCO without detector specified. GPT-5 conservative (null), mini infers C2",
  "tags": ["LASCO", "null_inference"],
  "timestamp": "2025-10-31T18:30:45.123456"
}
```

## Analysis Tips

After annotation, you can:
- Filter by category to find patterns
- Count how many are prompt issues vs model issues
- Identify which call types have most ambiguity
- Generate recommendations for prompt improvements

## Files

- `disagreement_annotator.py`: Main Streamlit app
- `disagreement_annotations.jsonl`: Saved annotations (created on first save)
- Output CSV: Downloaded via sidebar button

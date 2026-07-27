# Time Model Comparison Tool

A simple framework for comparing how different AI models parse and normalize time expressions from scientific papers.

## What it does

This tool helps test multiple OpenAI models on the same time parsing tasks and compare their accuracy. 

Input: User and system prompts from previous LLM calls with their associated output. 

Process: Run inputted user and system prompts on multiple different OpenAI models, and save the new ouput.

Output: Similar file to input, now with new output from selected model. 

## Quick Start

### 1. Generate Model Outputs
```bash
cd src
python main.py data/gpt5_output.jsonl
```

This runs your input prompts through different models (configured in `MODELS` list) and saves their outputs.

### 2. Compare Results
```bash
python comparison/compare_model_output.py
```

This compares all model outputs against the baseline (`data/gpt5_output.jsonl`) and generates comparison reports.

## How Comparison Works

The tool compares two things:
1. **Datetime accuracy** - Do the extracted dates match (considering precision differences)?
2. **Precision matching** - Do the models identify the same precision level?

### Smart Precision Handling
If the baseline says "year" precision and a model says "day" precision, but both extract the same year, that's considered **correct** for datetime but **incorrect** for precision matching.

**Example:**
- Baseline: `1974-01-01T00:00:00Z` with precision `"year"`
- Model: `1974-03-15T12:30:45Z` with precision `"day"`
- Result: **Datetime correct** (both are 1974), but **Precision mismatch**

## Output Files

Results are saved to `results/` folder:
- `summary_TIMESTAMP.csv` - Condensed accuracy metrics per model
- `detailed_comparison_TIMESTAMP.csv` - Line-by-line comparison data
- `comparison_report_TIMESTAMP.txt` - Human-readable summary

## Adding New Models

Edit the `MODELS` list in `main.py`:
```python
MODELS = ['gpt-4o-mini', 'gpt-4o', 'your-new-model']
```
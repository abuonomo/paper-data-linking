"""Analyze physobs rerendered results with case-insensitive comparison."""
import json
from pathlib import Path
import sys
sys.path.insert(0, '.')

# Load results
base_dir = Path("experiments/compare_models/experiments/compare_models/prompt_experiments/physobs_rerendered_10_all_models")
nano_file = base_dir / "openai_gpt-5-nano_20251009_163754.jsonl"
mini_file = base_dir / "openai_gpt-5-mini_20251009_163853.jsonl"
gpt5_file = base_dir / "openai_gpt-5_20251009_164001.jsonl"

nano_results = [json.loads(line) for line in open(nano_file)]
mini_results = [json.loads(line) for line in open(mini_file)]
gpt5_results = [json.loads(line) for line in open(gpt5_file)]

# Case-sensitive comparison
case_sensitive_agreements = 0
case_insensitive_agreements = 0
disagreements = []

for i in range(10):
    nano_val = nano_results[i]['parsed_response']['physical_observable']
    mini_val = mini_results[i]['parsed_response']['physical_observable']
    gpt5_val = gpt5_results[i]['parsed_response']['physical_observable']

    # Case-sensitive
    if nano_val == mini_val == gpt5_val:
        case_sensitive_agreements += 1

    # Case-insensitive
    if nano_val.lower() == mini_val.lower() == gpt5_val.lower():
        case_insensitive_agreements += 1
    else:
        disagreements.append({
            'case_index': i,
            'nano': nano_val,
            'mini': mini_val,
            'gpt5': gpt5_val,
            'description': nano_results[i]['parsed_response']['original_text'][:60]
        })

print(f"\n{'='*70}")
print(f"PhysObs Normalization Agreement Analysis (NEW PROMPTS)")
print(f"{'='*70}\n")
print(f"Case-sensitive agreement:   {case_sensitive_agreements}/10 ({case_sensitive_agreements*10}%)")
print(f"Case-insensitive agreement: {case_insensitive_agreements}/10 ({case_insensitive_agreements*10}%)")

if disagreements:
    print(f"\nRemaining disagreements (case-insensitive):")
    for d in disagreements:
        print(f"\n  Case {d['case_index']}:")
        print(f"    nano:  {d['nano']}")
        print(f"    mini:  {d['mini']}")
        print(f"    gpt-5: {d['gpt5']}")
        print(f"    Description: {d['description']}...")
else:
    print(f"\n✓ Perfect agreement when ignoring case!")

print(f"\n{'='*70}\n")

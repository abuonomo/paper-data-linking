"""Analyze physobs rerendered experiment results."""
import json
from pathlib import Path
import sys
sys.path.insert(0, '.')
from experiments.compare_models.handlers.physobs_normalization import PhysObsNormalizationHandler

# Load results
base_dir = Path("experiments/compare_models/experiments/compare_models/prompt_experiments/physobs_rerendered_10_all_models")
nano_file = base_dir / "openai_gpt-5-nano_20251009_163754.jsonl"
mini_file = base_dir / "openai_gpt-5-mini_20251009_163853.jsonl"
gpt5_file = base_dir / "openai_gpt-5_20251009_164001.jsonl"

nano_results = [json.loads(line) for line in open(nano_file)]
mini_results = [json.loads(line) for line in open(mini_file)]
gpt5_results = [json.loads(line) for line in open(gpt5_file)]

handler = PhysObsNormalizationHandler()

# Find disagreements
agreements = 0
disagreements = []

for i in range(10):
    nano_parsed = nano_results[i]['parsed_response']
    mini_parsed = mini_results[i]['parsed_response']
    gpt5_parsed = gpt5_results[i]['parsed_response']

    cmp1 = handler.compare_responses(nano_parsed, mini_parsed)
    cmp2 = handler.compare_responses(nano_parsed, gpt5_parsed)
    cmp3 = handler.compare_responses(mini_parsed, gpt5_parsed)

    if cmp1.agree and cmp2.agree and cmp3.agree:
        agreements += 1
    else:
        disagreements.append({
            'case_index': i,
            'nano': nano_results[i],
            'mini': mini_results[i],
            'gpt5': gpt5_results[i],
            'nano_val': nano_parsed['physical_observable'],
            'mini_val': mini_parsed['physical_observable'],
            'gpt5_val': gpt5_parsed['physical_observable']
        })

print(f"\n{'='*60}")
print(f"PhysObs Normalization Agreement Analysis (NEW PROMPTS)")
print(f"{'='*60}\n")
print(f"Agreement rate: {agreements}/10 ({agreements*10}%)")
print(f"Disagreement cases: {len(disagreements)}")

if disagreements:
    print(f"\nDisagreement details:")
    for d in disagreements:
        print(f"\n  Case {d['case_index']}:")
        print(f"    nano:  {d['nano_val']}")
        print(f"    mini:  {d['mini_val']}")
        print(f"    gpt-5: {d['gpt5_val']}")
        print(f"    Paper description: {d['nano']['parsed_response']['original_text'][:60]}...")

print(f"\n{'='*60}")
print(f"Comparison with OLD prompts: 40% → {agreements*10}%")
print(f"Improvement: +{agreements*10 - 40} percentage points")
print(f"{'='*60}\n")

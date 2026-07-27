#!/usr/bin/env python3
"""Compare validation results from multiple models."""
import json
import re
from pathlib import Path
from datetime import datetime
from collections import defaultdict


def extract_decision(text):
    """Extract VALID/INVALID decision from model output."""
    if not text:
        return None

    # Try different formats
    # Format 1: "FINAL DECISION: valid/invalid"
    m = re.search(r'FINAL\s+DECISION:\s*(valid|invalid)', text, re.IGNORECASE)
    if m:
        return m.group(1).lower()

    # Format 2: "CONCLUSION: VALID/INVALID"
    m = re.search(r'CONCLUSION:\s*(VALID|INVALID)', text, re.IGNORECASE)
    if m:
        return m.group(1).lower()

    # Format 3: JSON with "decision" key
    try:
        data = json.loads(text)
        if 'decision' in data:
            return data['decision'].lower()
    except:
        pass

    return None


def load_results(filepath):
    """Load results from JSONL file."""
    results = []
    with open(filepath) as f:
        for line in f:
            if line.strip():
                results.append(json.loads(line))
    return results


def compare_models(baseline_file, *result_files):
    """Compare baseline with multiple result files."""
    baseline = load_results(baseline_file)
    all_results = [load_results(f) for f in result_files]

    # Extract model names from filenames
    model_names = []
    for f in result_files:
        name = Path(f).stem
        # Extract model name from pattern like "openai_gpt-5-mini_20251007_153702"
        parts = name.split('_')
        if len(parts) >= 2:
            model_names.append('_'.join(parts[:2]))  # e.g., "openai_gpt-5-mini"
        else:
            model_names.append(name)

    # Baseline model name
    baseline_name = "baseline (gpt-5-nano)"

    # Compare each line
    comparisons = []
    for idx, baseline_item in enumerate(baseline):
        baseline_decision = extract_decision(baseline_item.get('output_content') or baseline_item.get('response'))

        result_decisions = []
        result_outputs = []
        for results in all_results:
            if idx < len(results):
                decision = extract_decision(results[idx].get('output_content'))
                output = results[idx].get('output_content', '')
                result_decisions.append(decision)
                result_outputs.append(output)
            else:
                result_decisions.append(None)
                result_outputs.append('')

        # Check if there's disagreement
        all_decisions = [baseline_decision] + result_decisions
        if None not in all_decisions and len(set(all_decisions)) > 1:
            # Disagreement found
            comparison = {
                'line': idx + 1,
                'input': baseline_item.get('input_messages', []),
                'baseline_decision': baseline_decision,
                'baseline_output': baseline_item.get('output_content') or baseline_item.get('response', ''),
                'model_decisions': dict(zip(model_names, result_decisions)),
                'model_outputs': dict(zip(model_names, result_outputs))
            }
            comparisons.append(comparison)

    # Calculate agreement stats
    total = len(baseline)
    disagreements = len(comparisons)
    agreement = total - disagreements

    print(f"\n{'='*80}")
    print(f"COMPARISON RESULTS")
    print(f"{'='*80}")
    print(f"Total cases: {total}")
    print(f"Full agreement: {agreement} ({100*agreement/total:.1f}%)")
    print(f"Disagreements: {disagreements} ({100*disagreements/total:.1f}%)")
    print(f"{'='*80}\n")

    if disagreements > 0:
        print(f"\nDISAGREEMENTS ({disagreements} cases):\n")

        # Count outlier patterns
        outlier_counts = defaultdict(int)
        for comp in comparisons:
            decisions = [comp['baseline_decision']] + list(comp['model_decisions'].values())
            decision_counts = {}
            for d in decisions:
                decision_counts[d] = decision_counts.get(d, 0) + 1

            # Find minority decision(s)
            for i, (name, decision) in enumerate([('baseline', comp['baseline_decision'])] + list(comp['model_decisions'].items())):
                if decision_counts[decision] == 1:  # Outlier
                    outlier_counts[name] += 1

        print("Outlier Summary:")
        for name, count in sorted(outlier_counts.items(), key=lambda x: -x[1]):
            print(f"  {name}: {count} times ({100*count/disagreements:.1f}% of disagreements)")
        print()

        for comp in comparisons:
            print(f"\n{'─'*80}")
            print(f"Line {comp['line']}:")

            # Extract original description info from input messages
            if comp['input']:
                user_msg = None
                for msg in comp['input']:
                    if msg.get('role') == 'user':
                        user_msg = msg.get('content', '')
                        break

                if user_msg:
                    # Extract key info from XML
                    name_match = re.search(r'<name>(.*?)</name>', user_msg, re.DOTALL)
                    instrument_match = re.search(r'<instrument>(.*?)</instrument>', user_msg, re.DOTALL)
                    mission_match = re.search(r'<mission>(.*?)</mission>', user_msg, re.DOTALL)

                    if name_match:
                        print(f"  Original: {name_match.group(1).strip()}")
                    if instrument_match:
                        print(f"  → Instrument: {instrument_match.group(1).strip()}")
                    if mission_match:
                        print(f"  → Mission: {mission_match.group(1).strip()}")

            print(f"\n  Decisions:")
            print(f"    {baseline_name}: {comp['baseline_decision'].upper()}")
            for model_name, decision in comp['model_decisions'].items():
                print(f"    {model_name}: {decision.upper()}")

    return comparisons


if __name__ == '__main__':
    import sys

    if len(sys.argv) < 3:
        print("Usage: compare_validation_results.py <baseline.jsonl> <result1.jsonl> [result2.jsonl ...]")
        sys.exit(1)

    baseline = sys.argv[1]
    results = sys.argv[2:]

    comparisons = compare_models(baseline, *results)

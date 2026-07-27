"""
Detailed analysis of cadence_normalization disagreements.
"""
import json
from pathlib import Path
from collections import Counter
from typing import List, Dict, Any

def load_experiment_runs(experiment_dir: str, file_pattern: str):
    """Load all JSONL run files from an experiment directory."""
    exp_path = Path(experiment_dir)
    if not exp_path.exists():
        return []

    jsonl_files = sorted(exp_path.glob(file_pattern))
    runs = []

    for f in jsonl_files:
        with open(f) as file:
            runs.append([json.loads(line) for line in file])

    return runs


def extract_responses_with_context(runs, field='cadences'):
    """Extract responses with full context organized by case index."""
    if not runs:
        return []

    n_cases = len(runs[0])
    cases_with_context = []

    for case_idx in range(n_cases):
        case_data = {
            'case_idx': case_idx,
            'responses': [],
            'raw_responses': [],
            'context': None,
            'input_data': None
        }

        for run_idx, run in enumerate(runs):
            case = run[case_idx]
            parsed = case.get('parsed_response')

            # Get context from first run (extract from user message)
            if run_idx == 0:
                input_messages = case.get('input_messages', [])
                if len(input_messages) > 1:
                    case_data['context'] = input_messages[1].get('content', '')
                else:
                    case_data['context'] = ''
                case_data['input_data'] = case.get('input_data', {})

            if parsed and field in parsed:
                cadences = parsed[field]
                # Normalize to tuple for comparison
                if isinstance(cadences, list):
                    response = tuple(sorted(cadences)) if cadences else 'NONE'
                else:
                    response = cadences
                raw_response = case.get('output_content', '')
            else:
                response = 'PARSE_ERROR'
                raw_response = case.get('output_content', '')

            case_data['responses'].append(response)
            case_data['raw_responses'].append(raw_response)

        cases_with_context.append(case_data)

    return cases_with_context


def categorize_disagreement(responses: List) -> Dict[str, Any]:
    """Categorize the type of disagreement."""
    unique_responses = set(responses)
    response_counts = Counter(responses)

    # Check if it's a NONE vs value disagreement
    has_none = 'NONE' in unique_responses
    has_values = any(r != 'NONE' and r != 'PARSE_ERROR' for r in unique_responses)

    category = {
        'type': None,
        'unique_count': len(unique_responses),
        'majority_response': response_counts.most_common(1)[0][0],
        'majority_count': response_counts.most_common(1)[0][1],
        'distribution': dict(response_counts)
    }

    if has_none and has_values:
        category['type'] = 'NONE_vs_VALUE'
    elif len(unique_responses) == 2 and not has_none:
        category['type'] = 'VALUE_vs_VALUE'
    elif len(unique_responses) > 2:
        category['type'] = 'MULTIPLE_VALUES'
    else:
        category['type'] = 'OTHER'

    return category


def main():
    # Load cadence free text runs
    runs = load_experiment_runs(
        "experiments/compare_models/prompt_experiments/bedrock_120b_cadence_free_text_full",
        "bedrock_openai.gpt-oss-120b-1_0_*.jsonl"
    )

    if not runs:
        print("No experiment data found!")
        return

    print(f"Loaded {len(runs)} runs with {len(runs[0])} cases each\n")
    print("="*80)
    print("DISAGREEMENT ANALYSIS - CADENCE NORMALIZATION FREE TEXT")
    print("="*80)

    # Extract all cases with context
    cases = extract_responses_with_context(runs, 'cadences')

    # Find disagreement cases
    disagreement_cases = []
    for case in cases:
        unique_responses = len(set(case['responses']))
        if unique_responses > 1:
            disagreement_cases.append(case)

    print(f"\nTotal disagreement cases: {len(disagreement_cases)} / {len(cases)}")

    # Categorize disagreements
    disagreement_types = Counter()
    for case in disagreement_cases:
        cat = categorize_disagreement(case['responses'])
        disagreement_types[cat['type']] += 1

    print(f"\nDisagreement types:")
    for dtype, count in disagreement_types.most_common():
        print(f"  {dtype}: {count} cases")

    # Analyze each disagreement case
    print("\n" + "="*80)
    print("DETAILED DISAGREEMENT CASES")
    print("="*80)

    for i, case in enumerate(disagreement_cases):
        cat = categorize_disagreement(case['responses'])

        print(f"\n{'='*80}")
        print(f"Case {case['case_idx']} (Disagreement #{i+1})")
        print(f"Type: {cat['type']}")
        print(f"Unique responses: {cat['unique_count']}")
        print(f"Majority: {cat['majority_response']} ({cat['majority_count']}/5)")
        print(f"Distribution: {cat['distribution']}")
        print(f"\nResponse breakdown:")
        for run_idx, (resp, raw) in enumerate(zip(case['responses'], case['raw_responses'])):
            print(f"  Run {run_idx+1}: {resp}")
            print(f"    Raw: {raw[:100]}")

        print(f"\nInput context (first 800 chars):")
        context = case['context']
        if context:
            print(f"  {context[:800]}")
            if len(context) > 800:
                print(f"  ... ({len(context)} total chars)")
        else:
            print(f"  (No context available)")

        print()

    # Show statistics by disagreement type
    print("\n" + "="*80)
    print("STATISTICS BY DISAGREEMENT TYPE")
    print("="*80)

    for dtype in disagreement_types.keys():
        type_cases = [c for c in disagreement_cases
                     if categorize_disagreement(c['responses'])['type'] == dtype]

        print(f"\n{dtype} ({len(type_cases)} cases):")

        # Show distribution of majority counts
        majority_counts = Counter()
        for case in type_cases:
            cat = categorize_disagreement(case['responses'])
            majority_counts[cat['majority_count']] += 1

        print(f"  Majority agreement distribution:")
        for maj_count, freq in sorted(majority_counts.items(), reverse=True):
            print(f"    {maj_count}/5 agree: {freq} cases")

        # Show most common patterns
        print(f"  Most common response patterns:")
        patterns = Counter()
        for case in type_cases:
            pattern = tuple(sorted(case['responses'], key=str))
            patterns[pattern] += 1

        for pattern, count in patterns.most_common(5):
            print(f"    {pattern}: {count} cases")


if __name__ == "__main__":
    main()

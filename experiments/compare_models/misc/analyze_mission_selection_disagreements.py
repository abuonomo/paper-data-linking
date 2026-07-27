"""
Analyze disagreements in mission_selection self-consistency experiment.
"""
import json
from pathlib import Path
from collections import Counter, defaultdict
from typing import List, Dict, Any

def load_run_data(jsonl_path: Path) -> List[Dict[str, Any]]:
    """Load data from a JSONL file."""
    with open(jsonl_path) as f:
        return [json.loads(line) for line in f]


def main():
    experiment_dir = Path("experiments/compare_models/prompt_experiments/bedrock_120b_mission_selection_full")

    # Find all JSONL files
    jsonl_files = sorted(experiment_dir.glob("bedrock_openai.gpt-oss-120b-1_0_*.jsonl"))

    print(f"Loading {len(jsonl_files)} runs...")

    # Load all runs
    runs_data = [load_run_data(f) for f in jsonl_files]

    # Verify all runs have same number of cases
    n_cases = len(runs_data[0])
    if not all(len(run) == n_cases for run in runs_data):
        print("Error: Runs have different number of cases")
        return

    print(f"Loaded {len(runs_data)} runs with {n_cases} cases each")

    # Organize responses by case
    responses_by_case = []
    contexts_by_case = []

    for case_idx in range(n_cases):
        case_responses = []
        for run in runs_data:
            case = run[case_idx]
            parsed = case.get('parsed_response')
            if parsed:
                is_ambiguous = parsed.get('is_ambiguous', False)
                if is_ambiguous:
                    response = 'AMBIGUOUS'
                else:
                    mission_indices = parsed.get('mission_indices', [])
                    response = tuple(sorted(mission_indices)) if mission_indices else 'EMPTY'
            else:
                response = 'PARSE_ERROR'
            case_responses.append(response)

        # Get context from first run's input messages
        case = runs_data[0][case_idx]
        input_msgs = case.get('input_messages', [])
        user_msg_content = ''
        if input_msgs:
            user_msg_content = input_msgs[-1].get('content', '')

        responses_by_case.append(case_responses)
        contexts_by_case.append({
            'user_message': user_msg_content,
            'original_id': case.get('original_id', 'unknown')
        })

    # Find disagreements
    disagreement_cases = []
    for case_idx, responses in enumerate(responses_by_case):
        unique_responses = set(responses)
        if len(unique_responses) > 1:
            disagreement_cases.append({
                'case_idx': case_idx,
                'responses': responses,
                'unique_responses': unique_responses,
                'context': contexts_by_case[case_idx]
            })

    print(f"\nDisagreement Analysis:")
    print(f"  Perfect agreement: {n_cases - len(disagreement_cases)}/{n_cases} ({100*(n_cases-len(disagreement_cases))/n_cases:.1f}%)")
    print(f"  Some disagreement: {len(disagreement_cases)}/{n_cases} ({100*len(disagreement_cases)/n_cases:.1f}%)")

    # Categorize disagreements
    ambiguous_vs_value = []
    different_values = []
    parse_error_involved = []

    for case in disagreement_cases:
        responses = case['responses']
        unique = case['unique_responses']

        if 'PARSE_ERROR' in unique:
            parse_error_involved.append(case)
        elif 'AMBIGUOUS' in unique or 'EMPTY' in unique:
            ambiguous_vs_value.append(case)
        else:
            different_values.append(case)

    print(f"\n{'='*80}")
    print("DISAGREEMENT CATEGORIES")
    print(f"{'='*80}\n")

    print(f"AMBIGUOUS vs specific value: {len(ambiguous_vs_value)} cases")
    print(f"Different mission indices: {len(different_values)} cases")
    print(f"Parse errors involved: {len(parse_error_involved)} cases")

    # Show detailed examples
    print(f"\n{'='*80}")
    print("DETAILED DISAGREEMENT EXAMPLES")
    print(f"{'='*80}\n")

    # AMBIGUOUS vs value examples
    if ambiguous_vs_value:
        print(f"\n--- AMBIGUOUS vs Specific Value ({len(ambiguous_vs_value)} cases) ---\n")
        for i, case in enumerate(ambiguous_vs_value):
            print(f"Case {case['case_idx']}:")
            print(f"  Responses: {case['responses']}")
            counter = Counter(case['responses'])
            print(f"  Distribution: {dict(counter)}")
            print(f"  User message (first 600 chars):")
            user_msg = case['context']['user_message']
            print(f"    {user_msg[:600]}...")
            print()

    # Different values examples
    if different_values:
        print(f"\n--- Different Mission Indices ({len(different_values)} cases) ---\n")
        for i, case in enumerate(different_values):
            print(f"Case {case['case_idx']}:")
            print(f"  Responses: {case['responses']}")
            counter = Counter(case['responses'])
            print(f"  Distribution: {dict(counter)}")
            print(f"  User message (first 600 chars):")
            user_msg = case['context']['user_message']
            print(f"    {user_msg[:600]}...")
            print()

    # Parse errors
    if parse_error_involved:
        print(f"\n--- Parse Errors Involved ({len(parse_error_involved)} cases) ---\n")
        for i, case in enumerate(parse_error_involved):
            print(f"Case {case['case_idx']}:")
            print(f"  Responses: {case['responses']}")
            counter = Counter(case['responses'])
            print(f"  Distribution: {dict(counter)}")
            print(f"  User message (first 600 chars):")
            user_msg = case['context']['user_message']
            print(f"    {user_msg[:600]}...")
            print()


if __name__ == "__main__":
    main()

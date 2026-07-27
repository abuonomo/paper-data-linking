"""
Analyze disagreements in mission identification self-consistency experiment.
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
    # Load all 5 runs
    runs_data = []
    for i in range(1, 6):
        run_dir = Path(f"experiments/compare_models/prompt_experiments/bedrock_120b_mission_identification_run{i}")
        jsonl_files = list(run_dir.glob("bedrock_openai.gpt-oss-120b-1_0_*.jsonl"))
        if jsonl_files:
            runs_data.append(load_run_data(jsonl_files[0]))

    print(f"Loaded {len(runs_data)} runs")

    # Verify all runs have same number of cases
    n_cases = len(runs_data[0])
    if not all(len(run) == n_cases for run in runs_data):
        print("Error: Runs have different number of cases")
        return

    print(f"Each run has {n_cases} cases")

    # Organize responses by case
    responses_by_case = []
    paper_ids_by_case = []
    raw_contexts_by_case = []

    for case_idx in range(n_cases):
        case_responses = []
        for run in runs_data:
            case = run[case_idx]
            parsed = case.get('parsed_response')
            if parsed:
                # Mission identification returns mission_indices (list) or is_unknown
                is_unknown = parsed.get('is_unknown', False)
                if is_unknown:
                    response = 'UNKNOWN'
                else:
                    mission_indices = parsed.get('mission_indices', [])
                    # Convert list of indices to tuple for hashability
                    response = tuple(sorted(mission_indices)) if mission_indices else 'EMPTY'
            else:
                response = 'PARSE_ERROR'
            case_responses.append(response)

        # Get paper_id and raw context for reference
        paper_id = runs_data[0][case_idx].get('original_id', 'unknown')
        # Get instrument description from input messages
        input_msgs = runs_data[0][case_idx].get('input_messages', [])
        raw_context = ''
        for msg in input_msgs:
            if msg.get('role') == 'user':
                raw_context = msg.get('content', '')[:500]
                break

        responses_by_case.append(case_responses)
        paper_ids_by_case.append(paper_id)
        raw_contexts_by_case.append(raw_context)

    # Count parse success
    total_responses = sum(len(responses) for responses in responses_by_case)
    parse_errors = sum(1 for responses in responses_by_case
                      for r in responses if r == 'PARSE_ERROR')
    parse_success_rate = (total_responses - parse_errors) / total_responses

    print(f"\nParse Success: {total_responses - parse_errors}/{total_responses} ({100*parse_success_rate:.1f}%)")

    # Find disagreements
    disagreement_cases = []
    for case_idx, responses in enumerate(responses_by_case):
        unique_responses = set(responses)
        if len(unique_responses) > 1:
            disagreement_cases.append({
                'case_idx': case_idx,
                'paper_id': paper_ids_by_case[case_idx],
                'responses': responses,
                'unique_responses': unique_responses,
                'raw_context': raw_contexts_by_case[case_idx]
            })

    print(f"\nDisagreement Analysis:")
    print(f"  Perfect agreement: {n_cases - len(disagreement_cases)}/{n_cases} ({100*(n_cases-len(disagreement_cases))/n_cases:.1f}%)")
    print(f"  Some disagreement: {len(disagreement_cases)}/{n_cases} ({100*len(disagreement_cases)/n_cases:.1f}%)")

    # Analyze disagreement patterns
    disagreement_patterns = Counter()
    for case in disagreement_cases:
        # Convert responses to strings for consistent pattern naming
        response_strs = []
        for r in case['responses']:
            if isinstance(r, tuple):
                response_strs.append(str(sorted(list(r))))
            else:
                response_strs.append(str(r))
        pattern = tuple(sorted(response_strs))
        disagreement_patterns[pattern] += 1

    print(f"\n{'='*80}")
    print("DISAGREEMENT PATTERNS")
    print(f"{'='*80}\n")

    for pattern, count in disagreement_patterns.most_common(10):
        print(f"Pattern: {pattern}")
        print(f"  Frequency: {count} cases")
        print()

    # Analyze specific disagreement types
    print(f"\n{'='*80}")
    print("DISAGREEMENT CATEGORIES")
    print(f"{'='*80}\n")

    # Group by response pair types
    unknown_vs_value = []
    different_values = []
    parse_error_involved = []

    for case in disagreement_cases:
        responses = case['responses']
        unique = case['unique_responses']

        if 'PARSE_ERROR' in unique:
            parse_error_involved.append(case)
        elif 'UNKNOWN' in unique or 'EMPTY' in unique:
            unknown_vs_value.append(case)
        else:
            different_values.append(case)

    print(f"UNKNOWN/EMPTY vs specific value: {len(unknown_vs_value)} cases")
    print(f"Different mission indices: {len(different_values)} cases")
    print(f"Parse errors involved: {len(parse_error_involved)} cases")

    # Show examples from each category
    print(f"\n{'='*80}")
    print("DETAILED DISAGREEMENT EXAMPLES")
    print(f"{'='*80}\n")

    # Show UNKNOWN vs value examples
    if unknown_vs_value:
        print(f"\n--- UNKNOWN/EMPTY vs Specific Value ({len(unknown_vs_value)} cases) ---\n")
        for i, case in enumerate(unknown_vs_value[:5]):
            print(f"Case {case['case_idx']} (Paper: {case['paper_id']})")
            print(f"  Responses: {case['responses']}")
            counter = Counter(case['responses'])
            print(f"  Distribution: {dict(counter)}")
            print(f"  Raw context: {case['raw_context'][:200]}...")
            print()

    # Show different values examples
    if different_values:
        print(f"\n--- Different Mission Codes ({len(different_values)} cases) ---\n")
        for i, case in enumerate(different_values[:5]):
            print(f"Case {case['case_idx']} (Paper: {case['paper_id']})")
            print(f"  Responses: {case['responses']}")
            counter = Counter(case['responses'])
            print(f"  Distribution: {dict(counter)}")
            print(f"  Raw context: {case['raw_context'][:200]}...")
            print()

    # Show parse error examples
    if parse_error_involved:
        print(f"\n--- Parse Errors Involved ({len(parse_error_involved)} cases) ---\n")
        for i, case in enumerate(parse_error_involved[:3]):
            print(f"Case {case['case_idx']} (Paper: {case['paper_id']})")
            print(f"  Responses: {case['responses']}")
            counter = Counter(case['responses'])
            print(f"  Distribution: {dict(counter)}")
            print(f"  Raw context: {case['raw_context'][:200]}...")
            print()

    # Response frequency analysis
    print(f"\n{'='*80}")
    print("ALL MISSION INDEX PATTERN FREQUENCIES")
    print(f"{'='*80}\n")

    all_responses = []
    for responses in responses_by_case:
        all_responses.extend(responses)

    response_counts = Counter(all_responses)
    for mission_indices, count in response_counts.most_common(20):
        # Convert tuple to readable string
        if isinstance(mission_indices, tuple):
            display = str(list(mission_indices))
        else:
            display = str(mission_indices)
        print(f"{display:30s}: {count:4d} ({100*count/len(all_responses):5.1f}%)")


if __name__ == "__main__":
    main()

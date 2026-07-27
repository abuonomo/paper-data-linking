#!/usr/bin/env python3
"""Analyze self-consistency across multiple experiment runs.

This script compares model responses across multiple runs of the same experiment
to measure consistency when using temperature=1.0.
"""

import json
import sys
from pathlib import Path
from collections import defaultdict
from typing import Dict, List, Any


def load_jsonl(filepath: Path) -> List[Dict[str, Any]]:
    """Load all records from a JSONL file."""
    records = []
    with open(filepath) as f:
        for line in f:
            records.append(json.loads(line))
    return records


def normalize_response(response: str) -> str:
    """Normalize response text for comparison."""
    return response.strip().lower()


def analyze_consistency(run_dirs: List[Path]) -> Dict[str, Any]:
    """Analyze consistency across multiple runs.

    Args:
        run_dirs: List of directories containing experiment results

    Returns:
        Dictionary with consistency analysis
    """
    # Load all runs
    runs_data = []
    for run_dir in run_dirs:
        jsonl_files = list(run_dir.glob("*.jsonl"))
        if not jsonl_files:
            print(f"Warning: No JSONL files found in {run_dir}")
            continue

        # Assume one JSONL file per run
        jsonl_file = jsonl_files[0]
        records = load_jsonl(jsonl_file)
        runs_data.append({
            'dir': run_dir.name,
            'file': jsonl_file.name,
            'records': records
        })

    if not runs_data:
        return {'error': 'No valid run data found'}

    num_runs = len(runs_data)
    num_cases = len(runs_data[0]['records'])

    # Group responses by case (using original_id or case_index)
    cases_by_id = defaultdict(list)

    for run in runs_data:
        for record in run['records']:
            case_id = record.get('original_id') or record.get('case_index')
            cases_by_id[case_id].append(record)

    # Analyze consistency for each case
    consistency_results = {
        'perfect_consistency': 0,  # All runs identical
        'high_consistency': 0,     # 4/5 identical
        'moderate_consistency': 0, # 3/5 identical
        'low_consistency': 0,      # 2/5 identical
        'no_consistency': 0,       # All different
        'api_errors': 0,           # Cases with API errors
        'parse_errors': 0,         # Cases with parse errors
        'total_cases': len(cases_by_id)
    }

    inconsistent_cases = []
    error_cases = []

    for case_id, records in cases_by_id.items():
        if len(records) != num_runs:
            print(f"Warning: Case {case_id} has {len(records)} records instead of {num_runs}")
            continue

        # Check for errors
        errors = [r for r in records if 'error' in r]
        if errors:
            consistency_results['api_errors'] += 1
            error_cases.append({
                'case_id': case_id,
                'error_count': len(errors),
                'errors': [e['error'] for e in errors]
            })
            continue

        # Extract responses (check both 'output_content' and 'response' fields)
        responses = []
        parse_errors = 0
        for record in records:
            response = record.get('output_content') or record.get('response', '')
            if not response:
                parse_errors += 1
                continue
            responses.append(normalize_response(response))

        if parse_errors > 0:
            consistency_results['parse_errors'] += 1
            error_cases.append({
                'case_id': case_id,
                'parse_error_count': parse_errors
            })
            continue

        # Count unique responses
        unique_responses = set(responses)
        num_unique = len(unique_responses)

        if num_unique == 1:
            consistency_results['perfect_consistency'] += 1
        else:
            # Count frequency of each response
            response_counts = defaultdict(int)
            for resp in responses:
                response_counts[resp] += 1

            max_count = max(response_counts.values())

            if max_count == num_runs - 1:
                consistency_results['high_consistency'] += 1
            elif max_count == 3:
                consistency_results['moderate_consistency'] += 1
            elif max_count == 2:
                consistency_results['low_consistency'] += 1
            else:
                consistency_results['no_consistency'] += 1

            # Record inconsistent case
            inconsistent_cases.append({
                'case_id': case_id,
                'unique_responses': num_unique,
                'response_counts': dict(response_counts),
                'responses': responses
            })

    # Calculate statistics
    valid_cases = consistency_results['total_cases'] - consistency_results['api_errors'] - consistency_results['parse_errors']

    consistency_results['valid_cases'] = valid_cases
    consistency_results['perfect_consistency_pct'] = (consistency_results['perfect_consistency'] / valid_cases * 100) if valid_cases > 0 else 0
    consistency_results['high_consistency_pct'] = (consistency_results['high_consistency'] / valid_cases * 100) if valid_cases > 0 else 0
    consistency_results['moderate_consistency_pct'] = (consistency_results['moderate_consistency'] / valid_cases * 100) if valid_cases > 0 else 0

    return {
        'summary': consistency_results,
        'inconsistent_cases': inconsistent_cases[:10],  # Show first 10
        'error_cases': error_cases[:10],  # Show first 10
        'num_runs': num_runs
    }


def main():
    if len(sys.argv) < 3:
        print("Usage: python analyze_self_consistency.py <test_set> <call_type>")
        print("Example: python analyze_self_consistency.py test_set_2025_11_26 wavelength_normalization")
        sys.exit(1)

    test_set = sys.argv[1]
    call_type = sys.argv[2]

    # Find all run directories - new structure: results/{test_set}/{call_type}/run{N}
    base_dir = Path(__file__).parent / "results" / test_set / call_type
    run_dirs = sorted(base_dir.glob("run*"))

    if not run_dirs:
        print(f"Error: No run directories found in {base_dir}")
        sys.exit(1)

    print(f"Found {len(run_dirs)} runs:")
    for run_dir in run_dirs:
        print(f"  - {run_dir.name}")
    print()

    # Analyze consistency
    results = analyze_consistency(run_dirs)

    if 'error' in results:
        print(f"Error: {results['error']}")
        sys.exit(1)

    # Print summary
    summary = results['summary']
    print("=" * 80)
    print("SELF-CONSISTENCY ANALYSIS")
    print("=" * 80)
    print(f"Number of runs: {results['num_runs']}")
    print(f"Total cases: {summary['total_cases']}")
    print(f"Valid cases: {summary['valid_cases']}")
    print(f"API errors: {summary['api_errors']}")
    print(f"Parse errors: {summary['parse_errors']}")
    print()

    print("CONSISTENCY BREAKDOWN:")
    print(f"  Perfect consistency (5/5 identical): {summary['perfect_consistency']:3d} ({summary['perfect_consistency_pct']:.1f}%)")
    print(f"  High consistency (4/5 identical):    {summary['high_consistency']:3d} ({summary['high_consistency_pct']:.1f}%)")
    print(f"  Moderate consistency (3/5 identical): {summary['moderate_consistency']:3d} ({summary['moderate_consistency_pct']:.1f}%)")
    print(f"  Low consistency (2/5 identical):     {summary['low_consistency']:3d}")
    print(f"  No consistency (all different):      {summary['no_consistency']:3d}")
    print()

    # Print inconsistent cases
    if results['inconsistent_cases']:
        print(f"SAMPLE INCONSISTENT CASES (showing {len(results['inconsistent_cases'])} of {len(results['inconsistent_cases'])}):")
        print("-" * 80)
        for i, case in enumerate(results['inconsistent_cases'][:5], 1):
            print(f"\nCase {i}: {case['case_id']}")
            print(f"  Unique responses: {case['unique_responses']}")
            print(f"  Response distribution:")
            for resp, count in sorted(case['response_counts'].items(), key=lambda x: -x[1]):
                print(f"    {count}x: {resp[:100]}...")

    # Print error cases if any
    if results['error_cases']:
        print(f"\nERROR CASES (showing {len(results['error_cases'])}):")
        print("-" * 80)
        for case in results['error_cases'][:5]:
            print(f"  Case {case['case_id']}: ", end='')
            if 'error_count' in case:
                print(f"{case['error_count']} API errors")
            elif 'parse_error_count' in case:
                print(f"{case['parse_error_count']} parse errors")


if __name__ == '__main__':
    main()
